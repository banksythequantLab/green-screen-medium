"""Property 10: String text never leaves the Connector.

Validates: tn3270-connector Requirements 12.24, 12.25, 12.26, 12.27, 12.28
"""
from __future__ import annotations

import logging
import re
import time

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorTimeoutError, S3270Error
from greenscreen.connector.models import Response
from greenscreen.connector.parser import ScreenParser, _escape_s3270_string
from greenscreen.connector.testing.fake import ScriptedResponse
from tests.connector_support import (
    BrokenPipeProc,
    LogCapture,
    RecordingFake,
    ScriptedProc,
    collect_exception_text,
    collect_record_text,
)

HOST = "host.example"
PORT = 3270
STATUS = "U F U C(127.0.0.1) I 2 24 80 0 0 0x0 0.000"
SCRIPTED_LINE = "done"
ERROR_LINE = "Keyboard locked"

MARKER_ALPHABET = ("ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"      # Greek capitals
                   "αβγδεζηθικλμνξοπρστυφχψω")    # Greek small letters
MODES = ["success", "error", "timeout", "exit", "broken_pipe"]

# Precondition: no marker-alphabet character occurs in a fixed string the
# Connector can put into a log record or an exception message.
_FIXED_STRINGS = [
    "direction=sent action=%s raw=%s", "direction=received action=%s lines=%d status=%s result=%s",
    "String", "chars", "ok", "error", "Connect", "Disconnect", "Quit",
    "s3270", HOST, str(PORT), "0123456789", "\"'\\", STATUS, SCRIPTED_LINE,
    ERROR_LINE, "Timed out waiting for response to", "s3270 returned error for",
    "s3270 subprocess exited during", "s3270 subprocess is not accepting input for",
    "Broken pipe", "BrokenPipeError", "S3270Error", "ConnectorTimeoutError",
]
for _s in _FIXED_STRINGS:
    assert not set(_s) & set(MARKER_ALPHABET), f"marker alphabet overlaps {_s!r}"
assert len(set(MARKER_ALPHABET)) == 48 and MARKER_ALPHABET.isprintable()


def _ok_bytes(n: int = 1) -> bytes:
    return f"{STATUS}\r\nok\r\n".encode() * n


def _entry(pattern: str, lines=(), result: str = "ok") -> ScriptedResponse:
    return ScriptedResponse(pattern, list(lines), STATUS, result)


CONNECT = _entry(re.escape(f"Connect({HOST}:{PORT})"))


@st.composite
def secret_text(draw) -> tuple[str, str]:
    marker = draw(st.text(alphabet=MARKER_ALPHABET, min_size=8, max_size=16))
    body = draw(st.text(
        alphabet=st.one_of(
            st.characters(min_codepoint=0x20, max_codepoint=0x7E),   # includes " and \
            st.characters(min_codepoint=0xA1, max_codepoint=0x2FFF,
                          blacklist_categories=("Cs", "Cc", "Cn", "Co", "Zs")),
        ),
        max_size=3000 - len(marker),                                 # 0 to 2984
    ))
    return marker, marker + body


def _release_fake(fake: RecordingFake) -> None:
    """Stop the fake and close its pipe fds so 100 examples do not exhaust them."""
    fake.terminate()
    for stream in (fake.stdin,):
        try:
            stream.close()
        except Exception:
            pass
    fake._thread.join(timeout=2)
    for stream in (fake.stdout, fake.stderr, fake._stdin_read):
        try:
            stream.close()
        except Exception:
            pass


def _wait_for_command(fake: RecordingFake, count: int) -> None:
    """The fake records commands on its own thread; give it a moment."""
    end = time.monotonic() + 2.0
    while len(fake.commands) < count and time.monotonic() < end:
        time.sleep(0.005)


@given(secret=secret_text(), mode=st.sampled_from(MODES))
@settings(max_examples=100, deadline=None)
def test_string_text_never_leaves_connector(secret: tuple[str, str], mode: str) -> None:
    # Feature: tn3270-connector, Property 10: String text never leaves the Connector
    marker, text = secret
    action = f'String("{_escape_s3270_string(text)}")'
    redacted = f"String(<{len(text)} chars>)"

    fake: RecordingFake | None = None
    proc = None
    if mode == "success":
        fake = RecordingFake([CONNECT, _entry(r"String\(.*\)", [SCRIPTED_LINE])])
        proc = fake
    elif mode == "error":
        fake = RecordingFake([CONNECT, _entry(r"String\(.*\)", [ERROR_LINE], "error")])
        proc = fake
    elif mode == "timeout":
        fake = RecordingFake([CONNECT])
        proc = fake
    elif mode == "exit":
        proc = ScriptedProc(_ok_bytes(1), wait_value=7)
    else:
        proc = BrokenPipeProc(_ok_bytes(1))

    config = ConnectorConfig(binary="s3270", host=HOST, port=PORT, default_timeout=2.0)
    conn = Connector(config, process_factory=lambda cmd, **kw: proc)

    capture = LogCapture(logging.DEBUG)
    logger = logging.getLogger("greenscreen.connector")
    old_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)

    raised: BaseException | None = None
    response = None
    try:
        conn.open()
        if mode == "timeout":
            conn._config.default_timeout = 0.05
        try:
            response = conn.string(text)
        except BaseException as exc:  # noqa: BLE001 - classified below
            raised = exc
        if fake is not None:
            _wait_for_command(fake, 2)
    finally:
        logger.removeHandler(capture)
        logger.setLevel(old_level)
        if fake is not None:
            _release_fake(fake)

    # Expected outcome per mode
    if mode == "success":
        assert raised is None
        assert response == Response(
            success=True, data_lines=[SCRIPTED_LINE],
            status=ScreenParser().parse_status_line(STATUS),
        )
    else:
        expected = ConnectorTimeoutError if mode == "timeout" else S3270Error
        assert isinstance(raised, expected), f"{mode}: raised {raised!r}"
        assert redacted in str(raised)

    # The unmodified Action reached the host double (attempted, for broken pipe)
    if fake is not None:
        assert fake.commands[-1] == action
    elif mode == "exit":
        assert proc.stdin.getvalue().endswith((action + "\n").encode("utf-8"))
    else:
        assert proc.attempted[-1] == (action + "\n").encode("utf-8")

    # The Redacted_Action is in the sent-Action DEBUG record
    sent = [r for r in capture.records
            if r.levelno == logging.DEBUG and "direction=sent" in r.getMessage()
            and redacted in r.getMessage()]
    assert sent, "no sent-Action DEBUG record with the Redacted_Action"

    # Forbidden strings are absent from every record and exception text
    forbidden = [text, marker, ascii(marker)[1:-1]]
    forbidden += sorted({ch for ch in text if ch in MARKER_ALPHABET})
    haystack: list[str] = []
    for record in capture.records:
        haystack.extend(collect_record_text(record))
    if raised is not None:
        haystack.extend(collect_exception_text(raised))
    for needle in forbidden:
        if not needle:
            continue
        for piece in haystack:
            assert needle not in piece, f"{needle!r} leaked in {piece[:80]!r}"

