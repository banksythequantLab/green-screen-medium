"""Connector releases the three session pipes on every ending path (linux-readiness 2.2).

Runs on every platform. Uses FakeS3270 and in-memory stand-ins: no live host,
no socket, no real s3270. Values are made up.
"""
from __future__ import annotations

import io
import logging
import threading
import time

import pytest

from greenscreen.connector import Connector, ConnectorConfig
from greenscreen.connector.exceptions import ConnectorError, ConnectorTimeoutError
from greenscreen.connector.testing.fake import ScriptedResponse
from tests.connector_support import LogCapture, RecordingFake, ScriptedProc

STATUS = "U F U C(127.0.0.1) I 2 24 80 0 0 0x0 0.000"
OK_REPLY = f"{STATUS}\r\nok\r\n".encode()


def _ok(pattern: str) -> ScriptedResponse:
    return ScriptedResponse(pattern, [], STATUS, "ok")


def _happy_script() -> list[ScriptedResponse]:
    return [_ok(r"Connect\(.*\)"), _ok(r"Disconnect\(\)"), _ok(r"Quit\(\)")]


def _config() -> ConnectorConfig:
    return ConnectorConfig(binary="s3270", host="host.example", port=3270, default_timeout=2.0)


@pytest.fixture
def logs():
    handler = LogCapture()
    logger = logging.getLogger("greenscreen.connector")
    old_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)
    logger.setLevel(old_level)


@pytest.fixture
def fakes():
    created: list[RecordingFake] = []

    def make(script) -> RecordingFake:
        fake = RecordingFake(script)
        created.append(fake)
        return fake

    yield make
    for fake in created:
        fake.terminate()
        fake.close()


def _assert_pipes_closed(proc) -> None:
    assert proc.stdin.closed
    assert proc.stdout.closed
    assert proc.stderr.closed


# ── Fake-backed sessions ─────────────────────────────────────────────────

def test_close_closes_the_three_pipes(fakes):
    fake = fakes(_happy_script())
    conn = Connector(_config(), process_factory=lambda cmd, **kw: fake)
    conn.open()
    conn.close()
    _assert_pipes_closed(fake)


def test_open_failure_closes_the_three_pipes(fakes):
    fake = fakes([ScriptedResponse(r"Connect\(.*\)", [], STATUS, "error")])
    conn = Connector(_config(), process_factory=lambda cmd, **kw: fake)
    with pytest.raises(ConnectorError):
        conn.open()
    _assert_pipes_closed(fake)


def test_pipe_timeout_closes_the_three_pipes(fakes):
    fake = fakes([])  # RecordingFake stays silent once the script is empty
    conn = Connector(_config(), process_factory=lambda cmd, **kw: fake)
    conn._config.default_timeout = 0.05  # the config validator rejects values below 1 s
    with pytest.raises(ConnectorTimeoutError):
        conn.open()
    _assert_pipes_closed(fake)


def test_close_is_idempotent_and_safe_before_open_and_after_failure(fakes):
    fake = fakes(_happy_script())
    conn = Connector(_config(), process_factory=lambda cmd, **kw: fake)
    conn.close()  # never opened
    conn.open()
    conn.close()
    conn.close()
    _assert_pipes_closed(fake)

    failed = fakes([ScriptedResponse(r"Connect\(.*\)", [], STATUS, "error")])
    conn2 = Connector(_config(), process_factory=lambda cmd, **kw: failed)
    with pytest.raises(ConnectorError):
        conn2.open()
    conn2.close()
    _assert_pipes_closed(failed)


# ── A stream whose close() raises ────────────────────────────────────────

class _Pipe(io.BytesIO):
    """BytesIO whose close() can raise OSError; counts the attempts."""

    def __init__(self, data: bytes = b"", fail: bool = False) -> None:
        super().__init__(data)
        self.fail = fail
        self.attempts = 0

    def close(self) -> None:
        self.attempts += 1
        if self.fail:
            raise OSError("boom")
        super().close()


@pytest.mark.parametrize("bad", ["stdin", "stdout", "stderr"])
def test_one_failing_close_does_not_stop_the_others(bad, logs):
    proc = ScriptedProc(OK_REPLY * 3)
    proc.stdin = _Pipe(fail=bad == "stdin")
    proc.stdout = _Pipe(OK_REPLY * 3, fail=bad == "stdout")
    proc.stderr = _Pipe(fail=bad == "stderr")
    conn = Connector(_config(), process_factory=lambda cmd, **kw: proc)
    conn.open()
    conn.close()  # must not raise

    for name in ("stdin", "stdout", "stderr"):
        pipe = getattr(proc, name)
        assert pipe.attempts == 1
        assert pipe.closed is (name != bad)

    failures = [r.getMessage() for r in logs.records if "closing" in r.getMessage()]
    assert len(failures) == 1
    assert bad in failures[0]
    assert "OSError" in failures[0]
    assert "boom" not in failures[0]
    for rec in logs.records:
        if "closing" in rec.getMessage():
            assert rec.levelno == logging.DEBUG


# ── A reader that never reaches end of file ──────────────────────────────

class _BlockedStdout:
    """Answers three commands, then blocks on iteration until released."""

    def __init__(self, release: threading.Event) -> None:
        self._release = release
        self.closed = False
        self.close_calls = 0

    def __iter__(self):
        for _ in range(3):
            yield f"{STATUS}\r\n".encode()
            yield b"ok\r\n"
        self._release.wait(timeout=30)

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


def test_blocked_reader_does_not_hang_close(monkeypatch, logs):
    release = threading.Event()
    proc = ScriptedProc(b"")
    proc.stdout = _BlockedStdout(release)
    monkeypatch.setattr(Connector, "PIPE_JOIN_SECONDS", 0.2)
    conn = Connector(_config(), process_factory=lambda cmd, **kw: proc)
    try:
        conn.open()
        started = time.monotonic()
        conn.close()
        elapsed = time.monotonic() - started

        assert elapsed < 2.0
        assert proc.stdin.closed
        assert proc.stderr.closed
        assert not proc.stdout.closed
        assert proc.stdout.close_calls == 0
        messages = [r.getMessage() for r in logs.records if r.levelno == logging.DEBUG]
        assert any("stdout" in m and "leaving" in m for m in messages)
    finally:
        release.set()
        thread = getattr(conn._reader, "_thread", None)
        if thread is not None:
            thread.join(timeout=2)
