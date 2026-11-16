"""Unit tests for Connector lifecycle, send, action helpers and waits (Task 10.2).

All tests run against FakeS3270 (or a tiny scripted process object); no network.

Validates: Requirements 2.1, 2.4, 2.5, 2.6, 2.9, 3.1, 3.2, 3.3, 3.5, 3.6, 3.7,
4.1, 4.2, 4.3, 4.6, 7.3, 7.6, 7.7, 7.8
"""
from __future__ import annotations

import io
import logging
import re
import subprocess
import time

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import (
    ConnectorError,
    ConnectorTimeoutError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.connector.models import Response, SFToken, Screen, StatusLine
from greenscreen.connector.renderer import ScreenRenderer
from greenscreen.connector.testing.fake import FakeS3270, ScriptedResponse
from greenscreen.connector.testing.fixtures import load_bundled_fixture

HOST = "host.example"
PORT = 3270
STATUS = "U F U C(127.0.0.1) I 2 24 80 0 0 0x0 0.000"


# ── Local helpers ────────────────────────────────────────────────────────

def entry(command: str, lines=(), result: str = "ok", status: str = STATUS) -> ScriptedResponse:
    return ScriptedResponse(re.escape(command), list(lines), status, result)


def regex_entry(pattern: str, lines=(), result: str = "ok") -> ScriptedResponse:
    return ScriptedResponse(pattern, list(lines), STATUS, result)


CONNECT = entry(f"Connect({HOST}:{PORT})")
DISCONNECT = entry("Disconnect()")
QUIT = entry("Quit()")


class RecordingFake(FakeS3270):
    """FakeS3270 that records commands and stays silent once the script runs out."""

    def __init__(self, script):
        self.commands: list[str] = []
        super().__init__(script)

    def _dispatch(self, command: str) -> None:
        self.commands.append(command)
        if self._index >= len(self._script):
            return  # simulate a hung process: no answer
        super()._dispatch(command)


@pytest.fixture
def make_connector():
    """Return make(script, **cfg) -> (connector, fake, factory_calls)."""
    created: list[tuple[Connector, RecordingFake]] = []

    def make(script, **cfg):
        fake = RecordingFake(script)
        calls: list[list[str]] = []

        def factory(cmd, **kwargs):
            calls.append(list(cmd))
            return fake

        config = ConnectorConfig(
            binary="s3270", host=HOST, port=PORT, default_timeout=cfg.pop("default_timeout", 2.0), **cfg
        )
        conn = Connector(config, process_factory=factory)
        created.append((conn, fake))
        return conn, fake, calls

    yield make
    for _conn, fake in created:
        fake.terminate()


def opened(make, script, **cfg):
    conn, fake, calls = make([CONNECT, *script], **cfg)
    conn.open()
    return conn, fake


def fast(conn: Connector) -> None:
    conn._config.default_timeout = 0.2


class ScriptedProc:
    """Minimal Popen-like object backed by in-memory pipes."""

    def __init__(self, stdout: bytes, wait_exc=None, wait_value=0):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(b"")
        self.calls: list[str] = []
        self._wait_exc = wait_exc
        self._wait_value = wait_value

    def wait(self, timeout=None):
        self.calls.append("wait")
        if self._wait_exc is not None:
            raise self._wait_exc
        return self._wait_value

    def terminate(self):
        self.calls.append("terminate")

    def kill(self):
        self.calls.append("kill")

    def poll(self):
        return None


def ok_bytes(n: int = 1) -> bytes:
    return (f"{STATUS}\r\nok\r\n").encode() * n


# ── open / close ─────────────────────────────────────────────────────────

def test_open_sends_connect_first_and_keeps_host_off_cmdline(make_connector):
    conn, fake, calls = make_connector([CONNECT])
    conn.open()
    assert fake.commands == [f"Connect({HOST}:{PORT})"]
    assert len(calls) == 1
    assert "-model" in calls[0]
    assert "3279-2" in calls[0]
    assert not any(HOST in part for part in calls[0])


def test_close_sends_disconnect_then_quit(make_connector):
    conn, fake = opened(make_connector, [DISCONNECT, QUIT])
    conn.close()
    assert fake.commands == [f"Connect({HOST}:{PORT})", "Disconnect()", "Quit()"]


def test_context_manager_opens_and_closes(make_connector):
    conn, fake, _ = make_connector([CONNECT, DISCONNECT, QUIT])
    with conn as c:
        assert c is conn
        assert fake.commands == [f"Connect({HOST}:{PORT})"]
    assert fake.commands[-2:] == ["Disconnect()", "Quit()"]
    with pytest.raises(SessionClosedError):
        conn.send("Enter()")


def test_context_manager_propagates_body_exception(make_connector):
    conn, fake, _ = make_connector([CONNECT, DISCONNECT, QUIT])
    with pytest.raises(RuntimeError, match="boom"):
        with conn:
            raise RuntimeError("boom")
    assert fake.commands[-1] == "Quit()"
    assert not conn.__exit__(None, None, None)


def test_double_open_raises_without_second_factory_call(make_connector):
    conn, fake, calls = make_connector([CONNECT])
    conn.open()
    with pytest.raises(ConnectorError):
        conn.open()
    assert len(calls) == 1


def test_close_twice_and_close_never_opened_are_silent(make_connector):
    conn, fake = opened(make_connector, [DISCONNECT, QUIT])
    conn.close()
    conn.close()
    fresh, _, calls = make_connector([])
    fresh.close()
    assert calls == []


def test_missing_binary_raises_connector_error_with_path(tmp_path):
    missing = str(tmp_path / "no-such-s3270")
    conn = Connector(ConnectorConfig(binary=missing, host=HOST, port=PORT))
    with pytest.raises(ConnectorError) as ei:
        conn.open()
    # The connector formats the path with !r, which doubles backslashes on Windows.
    assert repr(missing) in str(ei.value)


def test_connect_error_raises_connector_error_and_terminates(make_connector):
    conn, fake, _ = make_connector([entry(f"Connect({HOST}:{PORT})", ["Connection refused"], "error")])
    with pytest.raises(ConnectorError) as ei:
        conn.open()
    msg = str(ei.value)
    assert HOST in msg and str(PORT) in msg
    assert fake.poll() == 0  # terminate() was called


def test_close_escalates_wait_timeout_to_terminate_then_kill(caplog):
    proc = ScriptedProc(
        ok_bytes(3), wait_exc=subprocess.TimeoutExpired(cmd="s3270", timeout=5)
    )
    conn = Connector(
        ConnectorConfig(binary="s3270", host=HOST, port=PORT),
        process_factory=lambda cmd, **kw: proc,
    )
    conn.open()
    with caplog.at_level(logging.WARNING, logger="greenscreen.connector"):
        conn.close()
    assert proc.calls == ["wait", "terminate", "wait", "kill"]
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    conn.close()  # still idempotent


# ── send ─────────────────────────────────────────────────────────────────

def test_send_ok_strips_data_prefix_and_parses_status(make_connector):
    conn, fake = opened(make_connector, [entry("Ascii()", ["row one", "row two"])])
    resp = conn.send("Ascii()")
    assert isinstance(resp, Response)
    assert resp.success is True
    assert resp.data_lines == ["row one", "row two"]
    assert isinstance(resp.status, StatusLine)
    assert resp.status.keyboard_state == "U"
    assert (resp.status.rows, resp.status.columns) == (24, 80)


def test_send_ok_without_data_lines(make_connector):
    conn, _ = opened(make_connector, [entry("Enter()")])
    assert conn.send("Enter()").data_lines == []


def test_send_error_raises_s3270error_with_context(make_connector):
    conn, _ = opened(make_connector, [entry("Enter()", ["Keyboard locked"], "error")])
    with pytest.raises(S3270Error) as ei:
        conn.send("Enter()")
    assert ei.value.action == "Enter()"
    assert ei.value.data_lines == ["Keyboard locked"]
    assert isinstance(ei.value.status_line, StatusLine)


@pytest.mark.parametrize("bad", ["", "Enter()\nQuit()", "a\rb"])
def test_send_rejects_invalid_action_and_writes_nothing(make_connector, bad):
    conn, fake = opened(make_connector, [])
    with pytest.raises(ValueError):
        conn.send(bad)
    time.sleep(0.05)
    assert fake.commands == [f"Connect({HOST}:{PORT})"]


def test_send_hung_process_times_out_terminates_and_closes_session(make_connector):
    conn, fake = opened(make_connector, [])
    fast(conn)
    with pytest.raises(ConnectorTimeoutError) as ei:
        conn.send("Enter()")
    assert "Enter()" in str(ei.value)
    assert fake.poll() == 0
    with pytest.raises(SessionClosedError):
        conn.send("Enter()")


def test_subprocess_exit_mid_session_reports_exit_code():
    proc = ScriptedProc(ok_bytes(1), wait_value=7)
    conn = Connector(
        ConnectorConfig(binary="s3270", host=HOST, port=PORT),
        process_factory=lambda cmd, **kw: proc,
    )
    conn.open()
    with pytest.raises(S3270Error) as ei:
        conn.send("Enter()")
    assert ei.value.exit_code == 7
    start = time.monotonic()
    with pytest.raises(S3270Error):
        conn.send("Enter()")
    assert time.monotonic() - start < 1.0


def test_calls_after_close_raise_session_closed(make_connector):
    conn, _ = opened(make_connector, [DISCONNECT, QUIT])
    conn.close()
    for call in (lambda: conn.send("Enter()"), conn.enter, conn.read_screen, conn.ascii):
        with pytest.raises(SessionClosedError):
            call()


# ── action helpers ───────────────────────────────────────────────────────

def test_string_escapes_backslash_and_quote(make_connector):
    conn, fake = opened(make_connector, [regex_entry(r"String\(.*\)")])
    conn.string('a\\b"c')
    assert fake.commands[-1] == r'String("a\\b\"c")'


def test_string_plain_and_length_limit(make_connector):
    conn, fake = opened(make_connector, [regex_entry(r"String\(.*\)")] * 2)
    conn.string("hello")
    assert fake.commands[-1] == 'String("hello")'
    conn.string("x" * 3000)
    n = len(fake.commands)
    with pytest.raises(ValueError):
        conn.string("x" * 3001)
    time.sleep(0.05)
    assert len(fake.commands) == n


@pytest.mark.parametrize("row,col", [(-1, 0), (0, -1)])
def test_move_cursor_negative_raises(make_connector, row, col):
    conn, fake = opened(make_connector, [])
    with pytest.raises(ValueError):
        conn.move_cursor(row, col)
    time.sleep(0.05)
    assert len(fake.commands) == 1


def test_move_cursor_valid(make_connector):
    conn, fake = opened(make_connector, [entry("MoveCursor(3,7)")])
    conn.move_cursor(3, 7)
    assert fake.commands[-1] == "MoveCursor(3,7)"


def test_pf_pa_bounds_and_wire_format(make_connector):
    conn, fake = opened(
        make_connector,
        [entry("PF(1)"), entry("PF(24)"), entry("PA(1)"), entry("PA(24)"),
         entry("Enter()"), entry("Clear()")],
    )
    conn.pf(1); conn.pf(24); conn.pa(1); conn.pa(24); conn.enter(); conn.clear()
    assert fake.commands[1:] == ["PF(1)", "PF(24)", "PA(1)", "PA(24)", "Enter()", "Clear()"]
    n = len(fake.commands)
    for fn in (conn.pf, conn.pa):
        for bad in (0, 25):
            with pytest.raises(ValueError):
                fn(bad)
    time.sleep(0.05)
    assert len(fake.commands) == n


def test_snap_save(make_connector):
    conn, fake = opened(make_connector, [entry("Snap(Save)")])
    conn.snap_save()
    assert fake.commands[-1] == "Snap(Save)"


# ── waits ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "method,wtype",
    [("wait_for_output", "Output"), ("wait_for_field", "InputField"), ("wait_for_unlock", "Unlock")],
)
def test_wait_commands_explicit_and_default_timeout(make_connector, method, wtype):
    conn, fake = opened(
        make_connector,
        [entry(f"Wait(5,{wtype})"), entry(f"Wait(2,{wtype})"), entry(f"Wait(0.5,{wtype})")],
        default_timeout=2.0,
    )
    getattr(conn, method)(5)
    getattr(conn, method)(None)
    getattr(conn, method)(0.5)
    assert fake.commands[1:] == [f"Wait(5,{wtype})", f"Wait(2,{wtype})", f"Wait(0.5,{wtype})"]


@pytest.mark.parametrize("bad", [0, -1, 3600.5])
def test_wait_invalid_timeout_raises(make_connector, bad):
    conn, fake = opened(make_connector, [])
    with pytest.raises(ValueError):
        conn.wait_for_output(bad)
    time.sleep(0.05)
    assert len(fake.commands) == 1


def test_wait_timeout_error_maps_to_connector_timeout(make_connector):
    conn, _ = opened(make_connector, [entry("Wait(5,Unlock)", ["Timed out waiting"], "error")])
    with pytest.raises(ConnectorTimeoutError) as ei:
        conn.wait_for_unlock(5)
    assert "Unlock" in str(ei.value) and "5" in str(ei.value)
    assert ei.value.deadline == 5


def test_wait_other_error_raises_s3270error_with_text(make_connector):
    conn, _ = opened(make_connector, [entry("Wait(5,Output)", ["Not connected"], "error")])
    with pytest.raises(S3270Error) as ei:
        conn.wait_for_output(5)
    assert "Not connected" in str(ei.value)


# ── screen capture ───────────────────────────────────────────────────────

def logon_entry() -> ScriptedResponse:
    frame = load_bundled_fixture("tk5-logon")[0]
    return ScriptedResponse(re.escape("ReadBuffer(Ascii)"), frame.data_lines, frame.status_line, frame.result)


def test_read_screen_sends_only_readbuffer_and_parses_fixture(make_connector):
    conn, fake = opened(make_connector, [logon_entry()])
    screen = conn.read_screen()
    assert fake.commands[1:] == ["ReadBuffer(Ascii)"]
    assert screen.rows == 24
    assert any("Logon ===>" in row for row in screen.text_grid)


def test_ascii_sends_ascii(make_connector):
    conn, fake = opened(make_connector, [entry("Ascii()", ["x"])])
    assert conn.ascii().data_lines == ["x"]
    assert fake.commands[-1] == "Ascii()"


# ── wait_for_text ────────────────────────────────────────────────────────

def _screen_entry(screen: Screen) -> ScriptedResponse:
    return ScriptedResponse(
        re.escape("ReadBuffer(Ascii)"), ScreenRenderer().render(screen), STATUS, "ok"
    )


def _blank_cells():
    return [[0x00] * 80 for _ in range(24)]


def blank_screen() -> Screen:
    return Screen(24, 80, 0, 0, _blank_cells(), [[] for _ in range(24)])


def hidden_screen(secret: str) -> Screen:
    cells = [[0x20] * 80 for _ in range(24)]
    cells[0][0] = SFToken(0xFC)  # non-display field
    for i, ch in enumerate(secret):
        cells[0][1 + i] = ord(ch)
    cells[0][1 + len(secret)] = SFToken(0xC0)  # visible, ends hidden field
    return Screen(24, 80, 0, 0, cells, [[] for _ in range(24)])


def test_wait_for_text_returns_screen_after_blank_first_poll(make_connector):
    conn, fake = opened(make_connector, [_screen_entry(blank_screen()), logon_entry()])
    screen = conn.wait_for_text("Logon ===>", timeout=2, poll_interval=0.01)
    assert fake.commands.count("ReadBuffer(Ascii)") == 2
    assert any("Logon ===>" in row for row in screen.text_grid)


def test_wait_for_text_times_out(make_connector):
    conn, _ = opened(make_connector, [_screen_entry(blank_screen())] * 60)
    with pytest.raises(ConnectorTimeoutError) as ei:
        conn.wait_for_text("never here", timeout=0.3, poll_interval=0.05)
    assert ei.value.operation == "wait_for_text"


def test_wait_for_text_ignores_hidden_field_content(make_connector):
    conn, _ = opened(make_connector, [_screen_entry(hidden_screen("hunter2"))] * 60)
    # Hidden text is never matched...
    with pytest.raises(ConnectorTimeoutError):
        conn.wait_for_text("hunter2", timeout=0.3, poll_interval=0.05)


def test_wait_for_text_error_does_not_leak_hidden_text(make_connector):
    conn, _ = opened(make_connector, [_screen_entry(hidden_screen("hunter2"))] * 60)
    with pytest.raises(ConnectorTimeoutError) as ei:
        conn.wait_for_text("absent", timeout=0.3, poll_interval=0.05)
    assert "hunter2" not in str(ei.value)


def test_wait_for_text_argument_validation(make_connector):
    conn, fake = opened(make_connector, [])
    with pytest.raises(ValueError):
        conn.wait_for_text("")
    for bad in (0, -0.1):
        with pytest.raises(ValueError):
            conn.wait_for_text("x", poll_interval=bad)
    time.sleep(0.05)
    assert len(fake.commands) == 1


# ── logging ──────────────────────────────────────────────────────────────

def test_debug_logging_records_sent_and_received(make_connector, caplog):
    conn, _ = opened(make_connector, [entry("Enter()")])
    with caplog.at_level(logging.DEBUG, logger="greenscreen.connector"):
        conn.enter()
    msgs = [r.getMessage() for r in caplog.records if r.name == "greenscreen.connector"]
    assert any("sent" in m and "Enter()" in m for m in msgs)
    assert any("received" in m and "Enter()" in m for m in msgs)


# ── _format_seconds / timeout validation ─────────────────────────────────

class TestFormatSeconds:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (30.0, "30"), (1.5, "1.5"), (0.25, "0.25"), (2.5, "2.5"),
            (0.001, "0.001"), (3600.0, "3600"), (100, "100"), (10.0, "10"),
            (1 / 3, "0.333"), (2.0000001, "2"), (0.0005, "0.001"),
            (1e-5, "0.001"), (3600.0004, "3600"),
        ],
    )
    def test_fixed_point_output(self, value, expected):
        assert Connector._format_seconds(value) == expected

    @pytest.mark.parametrize("value", [1e-3, 0.0012, 1e-5, 5e-324, 3599.9999])
    def test_never_scientific_notation(self, value):
        assert "e" not in Connector._format_seconds(value).lower()


@pytest.mark.parametrize(
    "bad",
    [0.0009, 0.0004, 1e-5, 5e-324, float("nan"), float("inf"), True, "5"],
)
def test_wait_rejects_bad_timeouts_and_sends_nothing(make_connector, bad):
    conn, fake = opened(make_connector, [])
    with pytest.raises(ValueError):
        conn.wait_for_output(bad)
    time.sleep(0.05)
    assert len(fake.commands) == 1


def test_wait_minimum_timeout_accepted(make_connector):
    conn, fake = opened(make_connector, [entry("Wait(0.001,Output)")])
    conn.wait_for_output(0.001)
    assert fake.commands[-1] == "Wait(0.001,Output)"
