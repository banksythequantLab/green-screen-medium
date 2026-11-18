"""Unit tests for String() redaction through the Connector (flow-runtime task 1.5).

Every test drives Connector.string() or send() and inspects what leaves the
Connector: DEBUG log records and exceptions (with their __cause__ and
__context__ chain). The redaction helper itself is not imported.

Validates: tn3270-connector Requirements 12.1-12.9, 12.16, 12.19, 12.20,
12.21, 12.23
"""
from __future__ import annotations

import logging
import re
import time

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorTimeoutError, S3270Error
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
CONNECT_CMD = f"Connect({HOST}:{PORT})"

NON_ASCII = "éßжλ"
SENTINEL = 'pw"\\x-unlikely' + NON_ASCII
SENTINEL_NL = SENTINEL + "\n" + "tail"
SENTINEL_CR = SENTINEL + "\r" + "tail"


def escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def action_for(text: str) -> str:
    return f'String("{escaped(text)}")'


def redacted(text: str) -> str:
    return f"String(<{len(text)} chars>)"


def leak_markers(text: str) -> list[str]:
    return [text, escaped(text), action_for(text), "unlikely", NON_ASCII]


def entry(command: str, lines=(), result: str = "ok") -> ScriptedResponse:
    return ScriptedResponse(re.escape(command.strip()), list(lines), STATUS, result)


CONNECT = entry(CONNECT_CMD)


def ok_bytes(n: int = 1) -> bytes:
    return f"{STATUS}\r\nok\r\n".encode() * n


def assert_no_leak(texts: list[str], text: str = SENTINEL) -> None:
    for marker in leak_markers(text):
        for t in texts:
            assert marker not in t, f"{marker!r} leaked in {t!r}"


# ── Fixtures ─────────────────────────────────────────────────────────────

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
def make_connector():
    created: list[RecordingFake] = []

    def make(script):
        fake = RecordingFake(script)
        created.append(fake)
        config = ConnectorConfig(binary="s3270", host=HOST, port=PORT, default_timeout=2.0)
        conn = Connector(config, process_factory=lambda cmd, **kw: fake)
        conn.open()
        return conn, fake

    yield make
    for fake in created:
        fake.terminate()
        fake.close()


def proc_connector(proc) -> Connector:
    config = ConnectorConfig(binary="s3270", host=HOST, port=PORT, default_timeout=2.0)
    conn = Connector(config, process_factory=lambda cmd, **kw: proc)
    conn.open()
    return conn


def all_log_text(logs: LogCapture) -> list[str]:
    texts: list[str] = []
    for rec in logs.records:
        texts.extend(collect_record_text(rec))
    return texts


def records_with(logs: LogCapture, direction: str) -> list:
    return [r for r in logs.records if f"direction={direction}" in r.getMessage()]


# ── Log records ──────────────────────────────────────────────────────────

def test_sent_debug_record_holds_only_redacted_action(make_connector, logs):
    conn, fake = make_connector([CONNECT, entry(action_for(SENTINEL))])
    conn.string(SENTINEL)
    sent = records_with(logs, "sent")
    last = sent[-1]
    texts = collect_record_text(last)
    assert_no_leak(texts)
    assert redacted(SENTINEL) in last.getMessage()
    assert redacted(SENTINEL) in str(last.msg) % last.args
    assert all(redacted(SENTINEL) in str(a) for a in last.args if "String" in str(a))
    assert fake.commands[-1] == action_for(SENTINEL)


def test_received_debug_record_holds_only_redacted_action(make_connector, logs):
    conn, _ = make_connector([CONNECT, entry(action_for(SENTINEL))])
    conn.string(SENTINEL)
    last = records_with(logs, "received")[-1]
    assert_no_leak(collect_record_text(last))
    assert redacted(SENTINEL) in last.getMessage()
    assert_no_leak(all_log_text(logs))


def test_received_record_has_no_response_line_but_data_lines_keep_echo(make_connector, logs):
    action = action_for(SENTINEL)
    echo_line = action
    conn, _ = make_connector([CONNECT, entry(action, lines=[echo_line])])
    resp = conn.string(SENTINEL)
    assert resp.data_lines == [echo_line]
    received = records_with(logs, "received")
    last = received[-1]
    assert last.args == (redacted(SENTINEL), 1, STATUS, "ok")
    assert_no_leak(collect_record_text(last))
    for rec in logs.records:
        for text in collect_record_text(rec):
            assert echo_line not in text


# ── Exception scenarios (one per place of Requirement 12.19) ─────────────

def _error_response(make_connector):
    conn, _ = make_connector([CONNECT, entry(action_for(SENTINEL), result="error")])
    with pytest.raises(S3270Error) as ei:
        conn.string(SENTINEL)
    return ei.value, SENTINEL


def _broken_pipe(make_connector):
    proc = BrokenPipeProc(ok_bytes(1))
    conn = proc_connector(proc)
    with pytest.raises(S3270Error) as ei:
        conn.string(SENTINEL)
    assert proc.attempted[-1] == (action_for(SENTINEL) + "\n").encode("utf-8")
    return ei.value, SENTINEL


def _subprocess_exit(make_connector):
    conn = proc_connector(ScriptedProc(ok_bytes(1), wait_value=7))
    with pytest.raises(S3270Error) as ei:
        conn.string(SENTINEL)
    assert ei.value.exit_code == 7
    return ei.value, SENTINEL


def _send_timeout(make_connector):
    conn, _ = make_connector([CONNECT])  # no scripted answer: the fake stays silent
    conn._config.default_timeout = 0.05
    with pytest.raises(ConnectorTimeoutError) as ei:
        conn.string(SENTINEL)
    return ei.value, SENTINEL


def _make_invalid(text):
    def scenario(make_connector):
        conn, fake = make_connector([CONNECT])
        with pytest.raises(ValueError) as ei:
            conn.string(text)
        time.sleep(0.1)
        assert fake.commands == [CONNECT_CMD]
        return ei.value, text

    return scenario


SCENARIOS = {
    "error_response": _error_response,
    "broken_pipe": _broken_pipe,
    "subprocess_exit": _subprocess_exit,
    "send_timeout": _send_timeout,
    "newline": _make_invalid(SENTINEL_NL),
    "carriage_return": _make_invalid(SENTINEL_CR),
}


@pytest.mark.parametrize("place", list(SCENARIOS))
def test_exception_message_and_attribute_hold_redacted_action(place, make_connector, logs):
    exc, text = SCENARIOS[place](make_connector)
    shown = redacted(text)
    assert shown in str(exc)
    if isinstance(exc, S3270Error):
        assert exc.action == shown
    elif isinstance(exc, ConnectorTimeoutError):
        assert exc.operation == shown
        assert exc.deadline == 0.05
    assert_no_leak([str(exc), *map(str, exc.args)], text)
    assert_no_leak(all_log_text(logs), text)


@pytest.mark.parametrize("place", list(SCENARIOS))
def test_exception_rendering_and_chain_never_hold_text(place, make_connector, logs):
    exc, text = SCENARIOS[place](make_connector)
    texts = collect_exception_text(exc)
    assert_no_leak(texts, text)
    assert any(redacted(text) in t for t in texts)
    if isinstance(exc, ValueError):
        assert exc.__cause__ is None and exc.__context__ is None


# ── send() with every spelling of String ─────────────────────────────────

PREFIXES = ["string(", "STRING(", "sTrInG(", "  String(", "String ("]


@pytest.mark.parametrize("result", ["ok", "error"])
@pytest.mark.parametrize("prefix", PREFIXES)
def test_send_redacts_every_spelling(prefix, result, make_connector, logs):
    action = f'{prefix}"{escaped(SENTINEL)}")'
    conn, fake = make_connector([CONNECT, entry(action, result=result)])
    if result == "ok":
        conn.send(action)
    else:
        with pytest.raises(S3270Error) as ei:
            conn.send(action)
        assert ei.value.action == redacted(SENTINEL)
        assert redacted(SENTINEL) in str(ei.value)
        assert_no_leak(collect_exception_text(ei.value))
    for direction in ("sent", "received"):
        rec = records_with(logs, direction)[-1]
        assert redacted(SENTINEL) in rec.getMessage()
    assert_no_leak(all_log_text(logs))
    assert fake.commands[-1] == action


# ── Wait operations after a string() call ────────────────────────────────

WAITS = [
    ("wait_for_output", "Output"),
    ("wait_for_field", "InputField"),
    ("wait_for_unlock", "Unlock"),
]


@pytest.mark.parametrize("method,wtype", WAITS)
def test_wait_error_response_after_string_has_no_response_text(method, wtype, make_connector, logs):
    wait = f"Wait(5,{wtype})"
    conn, _ = make_connector(
        [CONNECT, entry(action_for(SENTINEL)), entry(wait, ["Not connected"], "error")]
    )
    conn.string(SENTINEL)
    with pytest.raises(S3270Error) as ei:
        getattr(conn, method)(5)
    exc = ei.value
    assert str(exc) == f"s3270 returned error for {wait!r}"
    assert "Not connected" not in str(exc) and "Not connected" not in repr(exc)
    assert exc.action == wait
    assert exc.data_lines == ["Not connected"]
    assert_no_leak(collect_exception_text(exc))
    assert_no_leak(all_log_text(logs))


@pytest.mark.parametrize("method,wtype", WAITS)
def test_wait_pipe_timeout_after_string_is_unchanged(method, wtype, make_connector, logs):
    wait = f"Wait(0.05,{wtype})"
    conn, _ = make_connector([CONNECT, entry(action_for(SENTINEL))])
    conn.string(SENTINEL)
    conn._config.default_timeout = 0.05
    conn.WAIT_GRACE_SECONDS = 0.05
    with pytest.raises(ConnectorTimeoutError) as ei:
        getattr(conn, method)()
    exc = ei.value
    deadline = 0.05 + 0.05
    assert str(exc) == (
        f"Timed out waiting for response to {wait!r}: Pipe read timed out after {deadline}s"
    )
    assert exc.operation == wait
    assert exc.deadline == deadline
    assert_no_leak(collect_exception_text(exc))
    assert_no_leak(all_log_text(logs))


# ══ Task 14.4: response redaction (tn3270-connector criteria 29 to 41) ═══
# Validates: tn3270-connector Requirements 12.29-12.41, 12.45

from greenscreen.connector.exceptions import ParseError  # noqa: E402
from greenscreen.connector.models import Response, SFToken, Screen  # noqa: E402
from greenscreen.connector.parser import ScreenParser  # noqa: E402
from greenscreen.connector.renderer import ScreenRenderer  # noqa: E402
from tests.connector_support import forbidden_forms  # noqa: E402

RECEIVED_FORMAT = "direction=received action=%s lines=%d status=%s result=%s"
LINE_1 = "response-line-one-xyz"
LINE_2 = "response-line-two-xyz"
SECRET_BYTES = b"s3Cr3t!x"


def received_records(logs: LogCapture) -> list:
    return [r for r in logs.records if str(r.msg).startswith("direction=received")]


def reset_logs(logs: LogCapture) -> None:
    logs.records.clear()


def assert_absent(texts: list[str], needles) -> None:
    for needle in needles:
        for t in texts:
            assert needle not in t, f"{needle!r} found in {t!r}"


def hidden_screen() -> Screen:
    """24x80 screen with a label and one hidden field holding SECRET_BYTES."""
    grid = [[0x00] * 80 for _ in range(24)]
    grid[2][0] = SFToken(0xE0)
    for i, b in enumerate(b"Password:"):
        grid[2][1 + i] = b
    grid[2][11] = SFToken(0xCC)  # unprotected, non-display
    for i, b in enumerate(SECRET_BYTES):
        grid[2][12 + i] = b
    grid[2][20] = SFToken(0xE0)
    return Screen(
        rows=24, columns=80, cursor_row=0, cursor_col=0,
        cell_grid=grid, sa_tokens=[[] for _ in range(24)],
    )


# ── Received_Record shape ────────────────────────────────────────────────

def test_received_record_shape_for_ok(make_connector, logs):
    conn, _ = make_connector([CONNECT, entry("Enter()", [LINE_1, LINE_2])])
    reset_logs(logs)
    resp = conn.enter()
    assert resp.data_lines == [LINE_1, LINE_2]
    recs = received_records(logs)
    assert len(recs) == 1
    rec = recs[0]
    assert rec.msg == RECEIVED_FORMAT
    assert rec.args == ("Enter()", 2, STATUS, "ok")
    assert rec.getMessage() == (
        f"direction=received action=Enter() lines=2 status={STATUS} result=ok"
    )
    assert_absent(all_log_text(logs), [LINE_1, LINE_2])


def test_received_record_shape_for_error(make_connector, logs):
    conn, _ = make_connector([CONNECT, entry("Enter()", [LINE_1], "error")])
    reset_logs(logs)
    with pytest.raises(S3270Error):
        conn.enter()
    recs = received_records(logs)
    assert len(recs) == 1
    assert recs[0].args == ("Enter()", 1, STATUS, "error")
    assert_absent(all_log_text(logs), [LINE_1])


def test_received_record_for_string_echo_line(make_connector, logs):
    action = action_for(SENTINEL)
    conn, _ = make_connector([CONNECT, entry(action, [action])])
    reset_logs(logs)
    resp = conn.string(SENTINEL)
    rec = received_records(logs)[0]
    assert rec.args[0] == redacted(SENTINEL)
    assert resp.data_lines == [action]
    assert_absent(all_log_text(logs), [action, escaped(SENTINEL)])


# ── Status line guard ────────────────────────────────────────────────────

def test_unparseable_status_is_not_logged_then_parse_error(make_connector, logs):
    bad = "Keyboard locked"
    conn, _ = make_connector([CONNECT, ScriptedResponse("Enter\\(\\)", [], bad, "ok")])
    reset_logs(logs)
    with pytest.raises(ParseError):
        conn.enter()
    rec = received_records(logs)[0]
    assert rec.args[2] == "<unparsed status, 15 chars>"
    assert_absent(all_log_text(logs), [bad])


GOOD_FIELDS = STATUS.split()


def _variant(index: int, value: str) -> str:
    fields = list(GOOD_FIELDS)
    fields[index] = value
    return " ".join(fields)


STATUS_VARIANTS = [
    " ".join(GOOD_FIELDS[:11]),
    " ".join(GOOD_FIELDS + ["extra"]),
    _variant(7, "ab"),
    _variant(9, "-1"),
    "",
]


@pytest.mark.parametrize("status", STATUS_VARIANTS)
def test_status_guard_variants_log_only_a_length(status, make_connector, logs):
    conn, _ = make_connector([CONNECT, ScriptedResponse("Enter\\(\\)", [], status, "ok")])
    reset_logs(logs)
    try:
        conn.enter()
    except ParseError:
        pass
    rec = received_records(logs)[0]
    assert rec.args[2] == f"<unparsed status, {len(status)} chars>"
    if status:
        assert_absent(all_log_text(logs), [status])


# ── _wait responses ──────────────────────────────────────────────────────

def test_wait_error_response_text_stays_out_of_exception(make_connector, logs):
    conn, _ = make_connector(
        [CONNECT, entry("Wait(5,Output)", ["Not connected"], "error")]
    )
    with pytest.raises(S3270Error) as ei:
        conn.wait_for_output(5)
    exc = ei.value
    assert str(exc) == "s3270 returned error for 'Wait(5,Output)'"
    assert "Not connected" not in str(exc)
    assert "Not connected" not in repr(exc)
    assert all("Not connected" not in str(a) for a in exc.args)
    assert exc.data_lines == ["Not connected"]
    assert_absent(all_log_text(logs), ["Not connected"])


def test_wait_timeout_response_text_stays_out_of_exception(make_connector, logs):
    conn, _ = make_connector(
        [CONNECT, entry("Wait(5,Output)", ["Timed out waiting"], "error")]
    )
    with pytest.raises(ConnectorTimeoutError) as ei:
        conn.wait_for_output(5)
    exc = ei.value
    assert str(exc) == "Wait(Output) timed out after 5s"
    assert exc.operation == "Wait(Output)"
    assert exc.deadline == 5
    assert "Timed out waiting" not in repr(exc)
    assert all("Timed out waiting" not in str(a) for a in exc.args)
    assert isinstance(exc.__cause__, S3270Error)
    assert exc.__cause__.data_lines == ["Timed out waiting"]
    assert_absent(
        collect_exception_text(exc, exclude_attrs={"data_lines"}), ["Timed out waiting"]
    )
    assert_absent(all_log_text(logs), ["Timed out waiting"])


# ── ReadBuffer token ─────────────────────────────────────────────────────

BAD_TOKEN_STATUS = "U F U C(127.0.0.1) I 2 1 3 0 0 0x0 0.000"
BAD_TOKEN_MESSAGE = "Unrecognised ReadBuffer token at row 0, index 1, length 2"


def _assert_bad_token(exc: ParseError) -> None:
    assert str(exc) == BAD_TOKEN_MESSAGE
    assert exc.raw == ""
    assert "zz" not in str(exc) and "zz" not in repr(exc)
    assert all("zz" not in str(a) for a in exc.args)


def test_bad_readbuffer_token_through_read_screen(make_connector, logs):
    conn, _ = make_connector(
        [CONNECT, ScriptedResponse(r"ReadBuffer\(Ascii\)", ["41 zz 42"], BAD_TOKEN_STATUS, "ok")]
    )
    with pytest.raises(ParseError) as ei:
        conn.read_screen()
    _assert_bad_token(ei.value)
    assert_absent(all_log_text(logs), ["zz"])


def test_bad_readbuffer_token_through_parser():
    parser = ScreenParser()
    status = parser.parse_status_line(BAD_TOKEN_STATUS)
    with pytest.raises(ParseError) as ei:
        parser.parse_readbuffer(Response(success=True, data_lines=["41 zz 42"], status=status))
    _assert_bad_token(ei.value)


# ── Hidden cells (criteria 40 and 41) ────────────────────────────────────

def _hidden_script(result: str):
    screen = hidden_screen()
    lines = ScreenRenderer().render(screen)
    return screen, lines, ScriptedResponse(r"ReadBuffer\(Ascii\)", lines, STATUS, result)


def _named_forms() -> set[str]:
    """The five forms of b"s3Cr3t!x", spelled out. Every hex digit is 0-9, so
    the lowercase and uppercase spellings coincide."""
    plain = "s3Cr3t!x"
    hex_lower = "7333437233742178"
    hex_lower_spaced = "73 33 43 72 33 74 21 78"
    hex_upper = "7333437233742178"
    hex_upper_spaced = "73 33 43 72 33 74 21 78"
    return {plain, hex_lower, hex_lower_spaced, hex_upper, hex_upper_spaced}


def test_hidden_cells_do_not_reach_records_on_ok(make_connector, logs):
    screen, _, scripted = _hidden_script("ok")
    forms = forbidden_forms(screen)
    assert forms == _named_forms()
    conn, _ = make_connector([CONNECT, scripted])
    result = conn.read_screen()
    assert result == screen
    assert_absent(all_log_text(logs), forms)


def test_hidden_cells_do_not_reach_exception_on_error(make_connector, logs):
    screen, lines, scripted = _hidden_script("error")
    forms = forbidden_forms(screen)
    assert forms == _named_forms()
    conn, _ = make_connector([CONNECT, scripted])
    with pytest.raises(S3270Error) as ei:
        conn.read_screen()
    exc = ei.value
    assert exc.data_lines == lines
    assert_absent(collect_exception_text(exc, exclude_attrs={"data_lines"}), forms)
    for linked in (exc.__cause__, exc.__context__):
        if linked is not None:
            assert_absent(collect_exception_text(linked, exclude_attrs={"data_lines"}), forms)
    assert_absent(all_log_text(logs), forms)


# ── Whole session and exception chain ────────────────────────────────────

def test_whole_session_records_hold_no_response_text(make_connector, logs):
    screen = hidden_screen()
    lines = ScreenRenderer().render(screen)
    echo = "string-echo-line-xyz"
    buffer = lambda: ScriptedResponse(r"ReadBuffer\(Ascii\)", lines, STATUS, "ok")  # noqa: E731
    script = [
        CONNECT,
        entry(action_for("hello"), [echo]),
        entry("Enter()", [LINE_1, LINE_2]),
        buffer(),
        buffer(),  # wait_for_text polls once
        entry("Disconnect()", ["disc-line-xyz"]),
        entry("Quit()", ["quit-line-xyz"]),
    ]
    fake = RecordingFake(script)
    config = ConnectorConfig(binary="s3270", host=HOST, port=PORT, default_timeout=2.0)
    conn = Connector(config, process_factory=lambda cmd, **kw: fake)
    try:
        conn.open()
        conn.string("hello")
        conn.enter()
        assert conn.read_screen() == screen
        assert conn.wait_for_text("Password:") == screen
        conn.close()
    finally:
        fake.terminate()
        fake.close()
    scripted = [echo, LINE_1, LINE_2, "disc-line-xyz", "quit-line-xyz", *lines]
    texts = all_log_text(logs)
    assert texts
    assert_absent(texts, [*scripted, *forbidden_forms(screen)])


@pytest.mark.parametrize(
    "command,lines,method",
    [
        ("Enter()", [LINE_1, LINE_2], "enter"),
        ("Wait(5,Output)", ["Not connected"], "wait_for_output"),
        ("Wait(5,Output)", ["Timed out waiting"], "wait_for_output"),
    ],
)
def test_exception_chain_holds_no_data_line(command, lines, method, make_connector):
    conn, _ = make_connector([CONNECT, entry(command, lines, "error")])
    call = getattr(conn, method)
    with pytest.raises(Exception) as ei:
        call(5) if method.startswith("wait") else call()
    exc = ei.value
    assert_absent(collect_exception_text(exc, exclude_attrs={"data_lines"}), lines)
