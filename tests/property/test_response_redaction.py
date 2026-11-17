"""Property 11: Hidden cell data never leaves the Connector.

Validates: tn3270-connector Requirements 12.38, 12.42, 12.43
"""
from __future__ import annotations

import logging
import re

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import S3270Error
from greenscreen.connector.models import Screen, SFToken, StatusLine
from greenscreen.connector.renderer import ScreenRenderer
from greenscreen.connector.testing.fake import ScriptedResponse
from tests.connector_support import (
    LogCapture,
    RecordingFake,
    collect_exception_text,
    collect_record_text,
    forbidden_forms,
)

HOST = "host.example"
PORT = 3270
READ_PATTERN = re.escape("ReadBuffer(Ascii)")


@st.composite
def screen_with_hidden_field(draw) -> Screen:
    rows = draw(st.integers(2, 24))
    cols = draw(st.integers(10, 80))
    total = rows * cols

    n = draw(st.integers(4, min(32, total - 2)))
    alphabet = draw(st.sampled_from(["printable", "any"]))
    byte_strategy = st.integers(0x20, 0x7E) if alphabet == "printable" else st.integers(0x01, 0xFF)
    hidden = draw(st.lists(byte_strategy, min_size=n, max_size=n))

    # Planted SF position; in a share of examples its column is near the row end.
    if draw(st.booleans()):
        row = draw(st.integers(0, rows - 1))
        col = draw(st.integers(max(0, cols - 6), cols - 1))
        p = row * cols + col
    else:
        p = draw(st.integers(0, total - 1))

    extra = draw(st.lists(st.integers(0, total - 1), max_size=5, unique=True))
    extra_c0 = draw(st.lists(st.integers(0, 0xFF), min_size=len(extra), max_size=len(extra)))
    planted_c0 = (draw(st.integers(0, 0xFF)) & ~0x0C) | 0x0C

    flat: list = list(draw(st.binary(min_size=total, max_size=total)))
    for lin, c0 in zip(extra, extra_c0):
        flat[lin] = SFToken(c0=c0)
    for i, b in enumerate(hidden, start=1):          # the run wraps; it holds no SF
        flat[(p + i) % total] = b
    flat[p] = SFToken(c0=planted_c0)
    # Close the planted field after the run when no other SF follows it closely.
    end = (p + n + 1) % total
    if not any(isinstance(flat[(p + i) % total], SFToken) for i in range(n + 1, n + 2)):
        flat[end] = SFToken(c0=draw(st.integers(0, 0xFF)))

    grid = [flat[r * cols:(r + 1) * cols] for r in range(rows)]
    cursor_row = draw(st.integers(0, rows - 1))
    cursor_col = draw(st.integers(0, cols - 1))
    return Screen(rows, cols, cursor_row, cursor_col, grid, [[] for _ in range(rows)])


def _status(screen: Screen) -> StatusLine:
    return StatusLine(
        keyboard_state="U", screen_formatting="F", field_protection="U",
        connection_state="C(127.0.0.1)", emulator_mode="I", model_number="2",
        rows=screen.rows, columns=screen.columns,
        cursor_row=screen.cursor_row, cursor_col=screen.cursor_col,
        window_id="0x0", command_time="0.000",
    )


def _release_fake(fake: RecordingFake) -> None:
    fake.terminate()
    try:
        fake.stdin.close()
    except Exception:
        pass
    fake._thread.join(timeout=2)
    for stream in (fake.stdout, fake.stderr, fake._stdin_read):
        try:
            stream.close()
        except Exception:
            pass


@given(screen=screen_with_hidden_field(), mode=st.sampled_from(["ok", "error"]))
@settings(max_examples=100, deadline=None)
def test_hidden_cells_never_leave_connector(screen: Screen, mode: str) -> None:
    # Feature: tn3270-connector, Property 11: Hidden cell data never leaves the Connector
    forms = forbidden_forms(screen, min_len=4)
    assert forms, "the planted hidden field must yield forbidden forms"

    lines = ScreenRenderer().render(screen)
    status = _status(screen).serialize()
    fixed_text = " ".join([
        "direction=received action=%s lines=%d status=%s result=%s",
        "direction=sent action=%s raw=%s",
        "ReadBuffer(Ascii)", f"Connect({HOST}:{PORT})", status, "ok", "error",
        "s3270", HOST, "s3270 returned error for 'ReadBuffer(Ascii)'", "S3270Error",
        str(len(lines)), "greenscreen.connector", "None", "True", "False", "2.0",
    ])
    assume(not any(form in fixed_text for form in forms))

    fake = RecordingFake([
        ScriptedResponse(re.escape(f"Connect({HOST}:{PORT})"), [], status, "ok"),
        ScriptedResponse(READ_PATTERN, lines, status, mode),
        ScriptedResponse(re.escape("Disconnect()"), [], status, "ok"),
        ScriptedResponse(re.escape("Quit()"), [], status, "ok"),
    ])
    config = ConnectorConfig(binary="s3270", host=HOST, port=PORT, default_timeout=2.0)
    conn = Connector(config, process_factory=lambda cmd, **kw: fake)

    capture = LogCapture(logging.DEBUG)
    logger = logging.getLogger("greenscreen.connector")
    old_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(logging.DEBUG)

    raised: BaseException | None = None
    result = None
    try:
        conn.open()
        try:
            result = conn.read_screen()
        except BaseException as exc:  # noqa: BLE001 - classified below
            raised = exc
        try:
            conn.close()
        except BaseException as exc:  # noqa: BLE001
            if raised is None:
                raised = exc
    finally:
        logger.removeHandler(capture)
        logger.setLevel(old_level)
        _release_fake(fake)

    if mode == "ok":
        assert raised is None, f"raised {raised!r}"
        assert result == screen
    else:
        assert isinstance(raised, S3270Error), f"raised {raised!r}"
        assert raised.data_lines == lines

    haystack: list[str] = []
    for record in capture.records:
        haystack.extend(collect_record_text(record))
    if raised is not None:
        haystack.extend(collect_exception_text(raised, exclude_attrs={"data_lines"}))
    for form in forms:
        for piece in haystack:
            assert form not in piece, f"hidden form leaked into {piece[:60]!r}"

    received = [r for r in capture.records if "direction=received" in r.getMessage()
                and r.args and r.args[0] == "ReadBuffer(Ascii)"]
    assert len(received) == 1
    assert received[0].args[1] == screen.rows
