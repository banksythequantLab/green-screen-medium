"""Unit tests for the Extract_Step (flow-runtime task 10.10).

Covers Requirements 3.3 to 3.9, 11.1 to 11.4 and 18.7. Screens come from the
captures through ``tests.flow_support`` or are built in memory; nothing here
touches a host. Cell reads are observed by a list subclass that logs the
indexes read while ``read_region`` runs.
"""
from __future__ import annotations

import pytest

import greenscreen.flow.runner as runner_module
from greenscreen.connector.models import Screen
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    Flow,
    OutputSpec,
)
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    capture,
    copy_screen,
    sentinel_password_screen,
)
from tests.screen_support import make_screen

MENU = "ispf-primary-menu"
POLL = 0.25
SENTINEL = "Zq7!Kx"
BLANK_ROW = 19  # a blank row of the ispf-primary-menu capture


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _menu_with(text: str, col: int = 10, row: int = BLANK_ROW) -> Screen:
    screen = capture(MENU)
    for i, ch in enumerate(text):
        screen.cell_grid[row][col + i] = ord(ch)
    return screen


def _find(screen: Screen, text: str) -> tuple[int, int]:
    codes = [ord(c) for c in text]
    for r, row in enumerate(screen.cell_grid):
        for c in range(len(row) - len(codes) + 1):
            if row[c:c + len(codes)] == codes:
                return r, c
    raise AssertionError("text not on the screen")


def _flow(outputs, *, first=MENU, extras=()):
    steps = (ExpectStep((first,)),) + tuple(ExtractStep(o.name) for o in outputs) + extras
    return Flow("t", steps, outputs=tuple(outputs))


def _out(name="o", type_="str", signature=MENU, row=BLANK_ROW, col=8, length=20):
    return OutputSpec(name, type_, signature, row, col, length)


def _run(flow, screens, **kwargs):
    session = ScriptedSession(screens)
    result = run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL, **kwargs)
    return result, session


def _run_failing(flow, screens, **kwargs):
    session = ScriptedSession(screens)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL, **kwargs)
    return info.value, session


def _visible(err: FlowError) -> str:
    return " ".join([str(err), repr(err), repr(err.args)])


class _TrackedRow(list):
    """A row that logs ``(row_number, column)`` of each single-cell read."""

    def __init__(self, cells, number, tracker):
        super().__init__(cells)
        self._number = number
        self._tracker = tracker

    def __getitem__(self, index):
        if self._tracker.active and isinstance(index, int):
            self._tracker.log.append((self._number, index))
        return super().__getitem__(index)


class _Tracker:
    def __init__(self):
        self.active = False
        self.log: list[tuple[int, int]] = []
        self.region_calls = 0


class _FixedSession:
    """Returns the same screen on every read; records the calls."""

    def __init__(self, screen):
        self._screen = screen
        self.calls: list[tuple] = []

    def read_screen(self):
        self.calls.append(("read",))
        return self._screen

    def string(self, text):
        self.calls.append(("string", text))

    def enter(self):
        self.calls.append(("enter",))

    def clear(self):
        self.calls.append(("clear",))

    def pf(self, n):
        self.calls.append(("pf", n))

    def pa(self, n):
        self.calls.append(("pa", n))

    def close(self):
        self.calls.append(("close",))


@pytest.fixture
def tracker(monkeypatch):
    """Spy on ``read_region``: log cell reads made inside it, count its calls."""
    t = _Tracker()
    real = runner_module.read_region

    def spy(screen, view, row, col, length):
        t.region_calls += 1
        t.active = True
        try:
            return real(screen, view, row, col, length)
        finally:
            t.active = False

    monkeypatch.setattr(runner_module, "read_region", spy)
    return t


def _tracked(screen: Screen, tracker: _Tracker) -> Screen:
    grid = [_TrackedRow(row, n, tracker) for n, row in enumerate(screen.cell_grid)]
    return Screen(
        rows=screen.rows,
        columns=screen.columns,
        cursor_row=screen.cursor_row,
        cursor_col=screen.cursor_col,
        cell_grid=grid,
        sa_tokens=[list(t) for t in screen.sa_tokens],
    )


# --------------------------------------------------------------------------
# 3.4, 11.1 str values: trimming and the empty result
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "start", "length", "expected"),
    [
        ("abc", 8, 9, "abc"),             # spaces on both sides
        ("abc", 10, 6, "abc"),            # trailing only
        ("abc", 7, 6, "abc"),             # leading only
        ("a  b", 8, 10, "a  b"),          # inner spaces kept
    ],
)
def test_str_value_has_leading_and_trailing_spaces_trimmed(text, start, length, expected):
    screen = _menu_with(text, col=10)
    flow = _flow([_out(col=start, length=length)])
    result, _ = _run(flow, [screen])
    assert result.outputs["o"] == expected
    assert type(result.outputs["o"]) is str


def test_str_value_trims_the_title_row_of_a_real_capture():
    screen = capture(MENU)
    row, col = _find(screen, "ISPF primary option menu")
    flow = _flow([_out(row=row, col=col - 3, length=24 + 6)])
    result, _ = _run(flow, [screen])
    assert result.outputs["o"] == "ISPF primary option menu"


def test_blank_region_gives_the_empty_string():
    flow = _flow([_out(row=BLANK_ROW, col=0, length=30)])
    result, _ = _run(flow, [capture(MENU)])
    assert result.outputs["o"] == ""
    assert type(result.outputs["o"]) is str


# --------------------------------------------------------------------------
# 3.5, 11.2 int conversion and the [0-9]{1,18} limit
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("0012", 12),
        ("  7  ", 7),
        ("0", 0),
        ("999999999999999999", 999999999999999999),   # 18 digits
        ("000000000000000042", 42),                   # 18 digits with zeros
    ],
)
def test_int_output_converts_one_to_eighteen_ascii_digits(text, value):
    flow = _flow([_out(type_="int", col=8, length=22)])
    result, _ = _run(flow, [_menu_with(text, col=10)])
    assert result.outputs["o"] == value
    assert type(result.outputs["o"]) is int


def test_int_output_reads_the_pf_keys_value_of_a_real_capture():
    screen = capture(MENU)
    row, col = _find(screen, "0012")
    flow = _flow([_out(type_="int", row=row, col=col, length=4)])
    result, _ = _run(flow, [screen])
    assert result.outputs["o"] == 12


@pytest.mark.parametrize(
    "text",
    [
        "1234567890123456789",  # 19 digits
        "",                      # nothing but spaces
        "-5",
        "+5",
        "1.5",
        "1 2",
        "04:09",
        "ZQ7KX",
        "\u00b2",                # superscript two: str.isdigit() is true, not [0-9]
    ],
)
def test_int_output_outside_the_digit_rule_raises_output_type(text):
    flow = _flow([_out(type_="int", col=8, length=22)])
    err, session = _run_failing(flow, [_menu_with(text, col=10)])
    assert err.reason == "output_type"
    assert err.step_index == 1
    assert err.kind == "extract"
    assert err.expected == ()
    assert [r.status for r in err.audit] == ["ok", "failed"]
    # No Session call besides the Expect_Step's read.
    assert session.calls == [("read",)]


def test_output_type_error_names_the_output_but_not_the_text():
    flow = _flow([_out("count", "int", col=8, length=22)])
    err, _ = _run_failing(flow, [_menu_with("ZQ7KX", col=10)])
    assert str(err) == (
        "output_type at step 1 (extract): expected none (0); output count"
    )
    assert "ZQ7KX" not in _visible(err)
    assert err.__cause__ is None and err.__context__ is None


def test_int_text_over_the_limit_is_not_echoed():
    digits = "1234567890123456789"
    flow = _flow([_out(type_="int", col=8, length=22)])
    err, _ = _run_failing(flow, [_menu_with(digits, col=10)])
    assert err.reason == "output_type"
    assert digits not in _visible(err)


# --------------------------------------------------------------------------
# 3.7, 11.3 hidden_output
# --------------------------------------------------------------------------

@pytest.mark.parametrize("col", [0, 1, 2])
def test_region_over_a_hidden_field_raises_hidden_output_without_reading_it(tracker, col):
    screen = _tracked(sentinel_password_screen(SENTINEL), tracker)
    flow = _flow([_out("pw", signature="tso-password-prompt", row=1, col=col, length=4)], first="tso-password-prompt")
    session = _FixedSession(screen)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL)
    err = info.value
    assert err.reason == "hidden_output"
    assert err.step_index == 1
    assert err.kind == "extract"
    assert str(err) == "hidden_output at step 1 (extract): expected none (0); output pw"
    assert tracker.region_calls == 1
    assert tracker.log == []  # no cell of the region was read
    assert session.calls == [("read",)]
    assert (SENTINEL in _visible(err)) is False
    assert (SENTINEL in repr(err.summary)) is False
    assert [r.status for r in err.audit] == ["ok", "failed"]
    assert err.__cause__ is None and err.__context__ is None


def test_region_next_to_a_hidden_field_still_reads_normally(tracker):
    # Row 0 of the password prompt holds visible text, so a region there is fine.
    screen = _tracked(sentinel_password_screen(SENTINEL), tracker)
    flow = _flow([_out("line", signature="tso-password-prompt", row=0, col=0, length=5)], first="tso-password-prompt")
    result = run_flow(flow, _FixedSession(screen), {}, clock=FakeClock(), poll_interval=POLL)
    assert type(result.outputs["line"]) is str
    assert tracker.log == [(0, c) for c in range(5)]


# --------------------------------------------------------------------------
# 3.8, 11.4 screen_size
# --------------------------------------------------------------------------

_TINY = ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),))


@pytest.mark.parametrize(("rows", "columns"), [(23, 80), (24, 79), (12, 40), (1, 4)])
def test_screen_under_24_by_80_raises_screen_size(rows, columns, tracker):
    screen = _tracked(make_screen(rows, columns, {(0, 0): "TINY  SECRETISH"}), tracker)
    flow = _flow([_out(signature="tiny", row=0, col=0, length=4)], first="tiny")
    session = _FixedSession(screen)
    with pytest.raises(FlowError) as info:
        run_flow(
            flow, session, {}, signatures=[_TINY], clock=FakeClock(), poll_interval=POLL
        )
    err = info.value
    assert err.reason == "screen_size"
    assert err.step_index == 1
    assert err.kind == "extract"
    assert str(err) == "screen_size at step 1 (extract): expected none (0); output o"
    assert tracker.region_calls == 0  # nothing was read for the region
    assert session.calls == [("read",)]


def test_screen_of_exactly_24_by_80_is_accepted():
    screen = make_screen(24, 80, {(0, 0): "TINY  value"})
    flow = _flow([_out(signature="tiny", row=0, col=6, length=10)], first="tiny")
    result, _ = _run(flow, [screen], signatures=[_TINY])
    assert result.outputs["o"] == "value"


# --------------------------------------------------------------------------
# 18.7 unexpected_screen and the no-read guarantees
# --------------------------------------------------------------------------

def test_current_screen_name_differing_from_the_output_signature_reads_no_cell(tracker):
    screen = _tracked(capture("tk5-logon"), tracker)
    # The arming Expect_Step lists both names, so the Flow validates; the screen
    # shown is the one that is not the Output signature.
    flow = Flow(
        "t",
        (ExpectStep(("tk5-logon", MENU)), ExtractStep("o")),
        outputs=(_out(signature=MENU),),
    )
    session = _FixedSession(screen)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL)
    err = info.value
    assert err.reason == "unexpected_screen"
    assert err.step_index == 1
    assert err.kind == "extract"
    assert err.expected == (MENU,)
    assert tracker.region_calls == 0
    assert tracker.log == []
    assert session.calls == [("read",)]
    assert [r.status for r in err.audit] == ["ok", "failed"]


def test_extract_steps_make_no_read_screen_call():
    outputs = [
        _out("a", row=0, col=0, length=10),
        _out("b", row=0, col=10, length=10),
        _out("c", "int", row=BLANK_ROW, col=10, length=3),
    ]
    flow = _flow(outputs)
    result, session = _run(flow, [_menu_with("42", col=10)])
    assert session.calls == [("read",)]  # the Expect_Step's read only
    assert [r.kind for r in result.audit] == ["expect", "extract", "extract", "extract"]
    assert all(r.status == "ok" for r in result.audit)
    assert all(r.signature == MENU for r in result.audit)


def test_extract_uses_no_clock_time():
    clock = FakeClock()
    flow = _flow([_out()])
    run_flow(flow, ScriptedSession([capture(MENU)]), {}, clock=clock, poll_interval=POLL)
    assert clock.sleeps == []
    assert clock.now == 0.0


# --------------------------------------------------------------------------
# 3.3, 3.9 FlowResult.outputs
# --------------------------------------------------------------------------

def test_outputs_has_exactly_one_entry_per_output_with_the_declared_type():
    screen = capture(MENU)
    t_row, t_col = _find(screen, "ISPF primary option menu")
    k_row, k_col = _find(screen, "0012")
    outputs = [
        _out("title", "str", row=t_row, col=t_col, length=24),
        _out("pf_keys", "int", row=k_row, col=k_col, length=4),
        _out("empty", "str", row=BLANK_ROW, col=0, length=10),
    ]
    flow = _flow(outputs)
    result, _ = _run(flow, [screen])
    assert list(result.outputs) == ["title", "pf_keys", "empty"]
    assert result.outputs == {"title": "ISPF primary option menu", "pf_keys": 12, "empty": ""}
    assert type(result.outputs["title"]) is str
    assert type(result.outputs["pf_keys"]) is int
    assert type(result.outputs["empty"]) is str


def test_outputs_follow_declaration_order_not_extract_order():
    outputs = [_out("first", row=0, col=0, length=5), _out("second", row=0, col=30, length=4)]
    flow = Flow(
        "t",
        (ExpectStep((MENU,)), ExtractStep("second"), ExtractStep("first")),
        outputs=tuple(outputs),
    )
    result, _ = _run(flow, [capture(MENU)])
    assert list(result.outputs) == ["first", "second"]


def test_a_flow_without_outputs_returns_an_empty_mapping():
    flow = Flow("t", (ExpectStep((MENU,)),))
    result, _ = _run(flow, [capture(MENU)])
    assert dict(result.outputs) == {}


def test_extract_does_not_change_the_screen_it_reads():
    screen = capture(MENU)
    before = copy_screen(screen)
    _run(_flow([_out(row=0, col=0, length=30)]), [screen])
    assert screen == before
