"""ConnectorSession over a stand-in process that never answers ReadBuffer.

No s3270 binary, no host and no credential is used. The stand-in is a short
Python script that answers ``Connect(...)`` and then reads stdin forever.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from greenscreen.connector import (
    ConnectorConfig,
    ConnectorError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.publisher.calls import ConnectorSession

STATUS = "U F U C(127.0.0.1) I 2 24 80 0 0 0x0 0.000"

STAND_IN = f"""
import sys
sys.stdout.write("{STATUS}\\nok\\n")
sys.stdout.flush()
for line in sys.stdin:
    pass
"""


def _popen(cmd, **kwargs):
    return subprocess.Popen([sys.executable, "-c", STAND_IN], **kwargs)


@pytest.fixture
def made():
    sessions: list[ConnectorSession] = []

    def make() -> ConnectorSession:
        s = ConnectorSession(
            ConnectorConfig(binary="stand-in", host="host.invalid", port=3270, default_timeout=30.0),
            popen=_popen,
        )
        sessions.append(s)
        return s

    yield make
    for s in sessions:
        s.abort()


def _blocked_read(session: ConnectorSession):
    box: dict[str, object] = {}

    def run() -> None:
        try:
            session.read_screen()
            box["error"] = None
        except BaseException as exc:  # noqa: BLE001 - the test inspects the type
            box["error"] = exc
        box["t"] = time.monotonic()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t, box


def test_abort_unblocks_a_blocked_read_with_an_error(made):
    s = made()
    s.open()
    t, box = _blocked_read(s)
    time.sleep(0.3)
    assert t.is_alive()  # the stand-in never answers ReadBuffer
    t0 = time.monotonic()
    s.abort()
    t.join(5)
    assert not t.is_alive()
    assert isinstance(box["error"], S3270Error)
    assert box["t"] - t0 < 3


def test_close_after_abort_returns_at_once_and_later_enter_is_refused(made):
    s = made()
    s.open()
    t, _ = _blocked_read(s)
    time.sleep(0.2)
    s.abort()
    t.join(5)
    t0 = time.monotonic()
    s.close()
    assert time.monotonic() - t0 < 2
    with pytest.raises(SessionClosedError):
        s.enter()


def test_abort_is_idempotent(made):
    s = made()
    s.open()
    s.abort()
    s.abort()
    s.close()


def test_abort_before_open_makes_open_raise(made):
    s = made()
    s.abort()
    with pytest.raises(ConnectorError):
        s.open()
    s.close()  # nothing was opened; returns
