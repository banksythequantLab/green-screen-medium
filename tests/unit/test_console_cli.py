"""The startup report and one real-process smoke test (spec console, task 2.9).

The subprocess runs ``tests/publisher_cli_entry.py`` (the real ``cli.main`` on the
Fake_Host), started as the graceful-stop test of ``test_publisher_cli.py`` starts it.
The API key is generated per run and never written to a file.
"""
from __future__ import annotations

import logging
import os
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("uvicorn")

from greenscreen.publisher import cli  # noqa: E402
from greenscreen.publisher.app import prepare  # noqa: E402
from tests.console_support import BASE_ENV  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
WIN = sys.platform == "win32"
LOGGER = "greenscreen.publisher"


def _env(**extra: str) -> dict[str, str]:
    return {**BASE_ENV, "GS_API_KEY": secrets.token_urlsafe(24), **extra}


def _records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER]


# --------------------------------------------------------------------------
# _report_startup (Requirements 1.6, 1.7)
# --------------------------------------------------------------------------


def test_report_startup_writes_the_existing_record_then_one_console_record(caplog):
    prepared = prepare(_env(GS_ENABLE_CONSOLE="true"))
    with caplog.at_level(logging.INFO, logger=LOGGER):
        cli._report_startup(prepared)
    records = _records(caplog)
    assert len(records) == 2
    first, second = records
    assert first.msg == "publishing %d of %d flows over %s"
    assert first.args == (len(prepared.registry), prepared.loaded_count, "http")
    assert first.levelno == logging.INFO
    assert second.getMessage() == "console enabled"
    assert second.levelno == logging.INFO
    assert second.args in ((), None)


def test_console_record_carries_no_extra_field(caplog):
    prepared = prepare(_env(GS_ENABLE_CONSOLE="true"))
    plain = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
    standard = set(plain.__dict__) | {"message", "asctime", "taskName"}
    with caplog.at_level(logging.INFO, logger=LOGGER):
        cli._report_startup(prepared)
    console = [r for r in _records(caplog) if r.getMessage() == "console enabled"]
    assert len(console) == 1
    assert set(console[0].__dict__) - standard == set()


def test_report_startup_writes_no_console_record_when_the_console_is_off(caplog):
    prepared = prepare(_env())
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        cli._report_startup(prepared)
    records = _records(caplog)
    assert [r.msg for r in records] == ["publishing %d of %d flows over %s"]
    assert not [r for r in caplog.records if "console" in r.getMessage().lower()]


def test_report_startup_writes_no_console_record_under_stdio(caplog):
    prepared = prepare(_env(GS_TRANSPORT="stdio", GS_ENABLE_CONSOLE="true"))
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        cli._report_startup(prepared)
    records = _records(caplog)
    assert len(records) == 1 and records[0].args[2] == "stdio"


# --------------------------------------------------------------------------
# One real process (Requirements 1.4, 2.5)
# --------------------------------------------------------------------------

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'none'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_subprocess_serves_the_page_with_the_csp_header(tmp_path):
    port = _free_port()
    key = secrets.token_urlsafe(24)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GS_", "TK5_"))}
    env.update(
        {
            "GS_S3270_BINARY": "unused-" + secrets.token_hex(4),
            "GS_HOST": "unused.invalid",
            "GS_PUBLISH_PORT": str(port),
            "GS_API_KEY": key,
            "GS_PUBLISH_FLOWS": "tk5-system-info",
            "GS_ENABLE_CONSOLE": "true",
        }
    )
    report, errpath = tmp_path / "report.json", tmp_path / "stderr.txt"
    errfile = errpath.open("wb")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.publisher_cli_entry", str(report)],
        cwd=ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=errfile,
        creationflags=flags,
    )
    watchdog = threading.Timer(90, proc.kill)
    watchdog.start()
    try:
        url = f"http://127.0.0.1:{port}/"
        deadline = time.monotonic() + 40
        while True:
            assert proc.poll() is None, errpath.read_text(errors="replace")
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    status = response.status
                    headers = response.headers  # case-insensitive lookup
                    body = response.read()
                break
            except (urllib.error.URLError, OSError):
                assert time.monotonic() < deadline, "server did not start"
                time.sleep(0.2)
        assert status == 200  # no key was sent
        assert headers["Content-Security-Policy"] == CSP
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert key.encode() not in body
        proc.send_signal(signal.CTRL_BREAK_EVENT if WIN else signal.SIGTERM)
        assert proc.wait(timeout=30) == 0
    finally:
        watchdog.cancel()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        errfile.close()
    err = errpath.read_text(errors="replace")
    assert "console enabled" in err
    assert err.index("publishing") < err.index("console enabled")
    assert key not in err
