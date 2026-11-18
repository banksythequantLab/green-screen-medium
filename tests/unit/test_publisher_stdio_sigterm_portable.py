"""Portable regression test for the stdio SIGTERM stop (linux-readiness Requirement 2.8).

The test is portable in structure, not in the delivery call. The child
(``tests/publisher_sigterm_entry.py``) runs the real stdio server on the Fake_Host and
delivers SIGTERM to itself once ``cli._on_sigterm`` is installed: on Windows with
``signal.raise_signal`` (in-process), on POSIX with ``os.kill`` on its own pid (through
the kernel, but not sent by another process). The
parent keeps the child's stdin open and idle and expects exit code 0 within 30 s. Without
the daemon-thread stdin copier the child's ``main()`` returns but the process stays alive
in ``threading._shutdown``, waiting for a non-daemon anyio reader thread blocked on stdin.

What this cannot prove: a SIGTERM sent by another process (an external ``kill -TERM``;
on Windows not even a kernel-delivered signal), the selector event loop used on Linux,
and Python 3.12 to 3.14. These stay Reviewer_Checks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

pytest.importorskip("uvicorn")

from greenscreen.publisher import cli  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHILD = "tests.publisher_sigterm_entry"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GS_", "TK5_"))}
    env.update(
        {
            "GS_S3270_BINARY": "unused-" + uuid.uuid4().hex[:8],
            "GS_HOST": "unused.invalid",
            "GS_TRANSPORT": "stdio",
            "GS_PUBLISH_FLOWS": "tk5-system-info",
        }
    )
    return env


def test_stdio_sigterm_with_idle_open_stdin_exits_0(tmp_path):
    report, errfile = tmp_path / "report.json", tmp_path / "stderr.txt"
    with errfile.open("wb") as err:
        proc = subprocess.Popen(
            [sys.executable, "-m", CHILD, str(report)],
            cwd=ROOT, env=_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
        )
        watchdog = threading.Timer(90, proc.kill)
        watchdog.start()
        try:
            # stdin stays open and idle until after the assertion
            assert proc.wait(timeout=30) == 0
            assert proc.stdin is not None and not proc.stdin.closed
        finally:
            watchdog.cancel()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            for pipe in (proc.stdin, proc.stdout):
                if pipe is not None:
                    pipe.close()
    result = json.loads(report.read_text())
    assert result["rc"] == 0
    assert result["live"] == 0


# -- helpers of the copier ---------------------------------------------------


@pytest.fixture
def pipes():
    made: list[int] = []

    def make() -> tuple[int, int]:
        r, w = os.pipe()
        made.extend((r, w))
        return r, w

    yield make
    for fd in made:
        try:
            os.close(fd)
        except OSError:
            pass


def _start(in_fd: int, feed_w: int) -> tuple[threading.Thread, list]:
    errors: list = []
    t = threading.Thread(
        target=lambda: _run(in_fd, feed_w, errors), daemon=True, name="test-copier"
    )
    t.start()
    return t, errors


def _run(in_fd: int, feed_w: int, errors: list) -> None:
    try:
        cli._copy_stdin(in_fd, feed_w)
    except BaseException as exc:  # pragma: no cover - failure path
        errors.append(exc)


def _read_all(fd: int) -> bytes:
    out = b""
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            return out
        out += chunk


def test_copier_copies_bytes_unchanged_and_in_order_then_closes_feed(pipes):
    in_r, in_w = pipes()
    feed_r, feed_w = pipes()
    data = bytes(range(256)) * 200  # larger than a pipe buffer
    t, errors = _start(in_r, feed_w)

    def produce():
        for i in range(0, len(data), 1000):
            os.write(in_w, data[i : i + 1000])
        os.close(in_w)  # EOF on the real stdin

    threading.Thread(target=produce, daemon=True).start()
    assert _read_all(feed_r) == data  # EOF on the feed ends the read
    t.join(5)
    assert not t.is_alive() and errors == []


def test_double_close_of_the_feed_is_safe(pipes, monkeypatch):
    _r, feed_w = pipes()
    monkeypatch.setattr(cli, "_FEED", {"fd": feed_w, "closed": False})
    cli._close_feed(feed_w)
    cli._close_feed(feed_w)
    cli._stdin_feed_close()
    assert cli._FEED["closed"] is True
    with pytest.raises(OSError):
        os.write(feed_w, b"x")


def test_write_to_a_closed_feed_ends_the_copier_without_raising(pipes):
    in_r, in_w = pipes()
    _feed_r, feed_w = pipes()
    os.close(feed_w)
    t, errors = _start(in_r, feed_w)
    os.write(in_w, b"data")
    t.join(5)
    assert not t.is_alive() and errors == []
