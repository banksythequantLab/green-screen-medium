"""FakeS3270 releases every descriptor and ends its handler thread (all platforms).

No live host, no socket, no real s3270.

Validates: Requirements 1.1, 1.2, 1.3, 1.7
"""
from __future__ import annotations

import re
import time

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.testing.fake import FakeS3270, ScriptedResponse

STATUS = "U F U C(127.0.0.1) I 2 24 80 0 0 0x0 0.000"
DESCRIPTORS = ("stdin", "stdout", "stderr", "_stdin_read", "_stdout_write")


def ok(command: str) -> ScriptedResponse:
    return ScriptedResponse(re.escape(command), [], STATUS, "ok")


def session_script() -> list[ScriptedResponse]:
    return [ok("Connect(unused.invalid:3270)"), ok("Disconnect()"), ok("Quit()")]


def assert_released(fake: FakeS3270) -> None:
    # The handler thread closes _stdin_read asynchronously after stdin is
    # closed, so wait for it before checking anything else.
    fake._thread.join(timeout=5)
    assert not fake._thread.is_alive()
    for name in DESCRIPTORS:
        assert getattr(fake, name).closed is True, f"{name} is still open"


def test_connector_close_releases_every_descriptor():
    fake = FakeS3270(session_script())
    try:
        conn = Connector(
            ConnectorConfig(binary="x", host="unused.invalid", port=3270),
            process_factory=lambda cmd, **kw: fake,
        )
        conn.open()
        conn.close()
        assert_released(fake)
    finally:
        fake.close()


def test_fake_close_releases_every_descriptor():
    fake = FakeS3270([])
    try:
        start = time.monotonic()
        fake.close()
        assert time.monotonic() - start < 5
        assert_released(fake)
    finally:
        fake.close()


@pytest.mark.parametrize("before", [None, "terminate", "kill", "wait"])
def test_close_twice_and_after_other_endings_does_not_raise(before):
    fake = FakeS3270([])
    try:
        if before is not None:
            getattr(fake, before)()
        start = time.monotonic()
        fake.close()
        fake.close()
        assert time.monotonic() - start < 5
        assert_released(fake)
    finally:
        fake.close()
