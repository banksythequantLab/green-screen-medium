"""Unit tests for every Reason_Code of ``run_flow`` (flow-runtime task 10.12).

One test per entry of ``greenscreen.flow.errors.REASON_CODES`` (``session_error``
once for each Session method), each asserting ``reason``, ``step_index``, sorted
``expected``, ``summary``, ``audit`` and the exact message. Generic tests then
run every case for the message form, secret and hidden-cell leaks, reachability
of Screens, release of the Comparison_Screen, ``__cause__`` and ``__context__``.

Verdicts about secrets are booleans, so a failing assertion never prints them.
Every Session is a scripted fake that serves fresh Screen copies and keeps only
weak references to them; nothing here touches a host.
"""
from __future__ import annotations

import gc
import re
import weakref
from dataclasses import dataclass, field
from typing import Any

import pytest

import greenscreen.flow.runner as runner_module
from greenscreen.connector import ConnectorError, Field, Screen
from greenscreen.connector.models import SFToken
from greenscreen.flow.errors import (
    REASON_CODES,
    FlowDefinitionError,
    FlowError,
    FlowInputError,
)
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    Flow,
    HandleStep,
    InputSpec,
    KeyStep,
    OutputSpec,
    Timeouts,
    TypeStep,
)
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher
from greenscreen.recognizer.summary import RedactedSummary
from greenscreen.recognizer.view import FieldGeom, ScreenView

from tests.flow_support import (
    FakeClock,
    blank_screen,
    capture,
    copy_screen,
    partial_repaint,
    sentinel_password_screen,
)
from tests.screen_support import make_screen

POLL = 0.25
SECRET = "SNTL4821"  # fits the 8-character secret Input
HIDDEN = "Zq7!Kx"  # residual password in the hidden cells of a screen
MENU = "ispf-primary-menu"
_PASSWORD = InputSpec("password", "str", True, 8, None, True)
_TINY = ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),))
_TWIN_A = ScreenSignature("dup-a", (TextAtMatcher(0, 0, "TINY"),))
_TWIN_B = ScreenSignature("dup-b", (TextAtMatcher(0, 0, "TINY"),))

_HOLDER: dict[str, Any] = {"refs": [], "alive_at_raise": None, "built": 0}


# --------------------------------------------------------------------------
# Scripted Session and case machinery
# --------------------------------------------------------------------------

class Sess:
    """Serves Screen copies, advances on keys (or on every read), can raise."""

    def __init__(self, screens, *, per_read=False, raising=None):
        self._screens = list(screens)
        self._per_read = per_read
        self._raising = raising or {}
        self._i = 0
        self.calls: list[tuple] = []
        self.refs: list[weakref.ref] = []

    def _enter_call(self, name, *args):
        self.calls.append((name, *args))
        make = self._raising.get(name)
        if make is not None:
            raise make()

    def _advance(self):
        self._i = min(self._i + 1, len(self._screens) - 1)

    def read_screen(self):
        self._enter_call("read_screen")
        screen = copy_screen(self._screens[self._i])
        if self._per_read:
            self._advance()
        self.refs.append(weakref.ref(screen))
        return screen

    def string(self, text):
        self._enter_call("string", text)

    def enter(self):
        self._enter_call("enter")
        self._advance()

    def clear(self):
        self._enter_call("clear")
        self._advance()

    def pf(self, n):
        self._enter_call("pf", n)
        self._advance()

    def pa(self, n):
        self._enter_call("pa", n)
        self._advance()

    def close(self):
        self.calls.append(("close",))


@dataclass
class Case:
    reason: str
    flow: Flow
    session: Sess
    inputs: dict = field(default_factory=dict)
    signatures: Any = None
    step: int | None = None
    kind: str | None = None
    expected: tuple[str, ...] = ()
    has_summary: bool = False
    statuses: tuple[str, ...] = ()
    message: str = ""


@pytest.fixture(autouse=True)
def _probes(monkeypatch):
    """Record Comparison_Screens and the Screens still alive when a FlowError is built."""
    _HOLDER.update(refs=[], alive_at_raise=None, built=0)
    real_build = runner_module.build_comparison

    def spy(pre, current, typed):
        built = real_build(pre, current, typed)
        _HOLDER["refs"].append(weakref.ref(built))
        _HOLDER["built"] += 1
        return built

    class Probe(FlowError):
        def __init__(self, *args, **kwargs):
            gc.collect()
            _HOLDER["alive_at_raise"] = sum(r() is not None for r in _HOLDER["refs"])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(runner_module, "build_comparison", spy)
    monkeypatch.setattr(runner_module, "FlowError", Probe)


def _execute(case: Case) -> FlowError:
    _HOLDER["refs"] = case.session.refs
    with pytest.raises(FlowError) as info:
        run_flow(
            case.flow, case.session, case.inputs,
            signatures=case.signatures, clock=FakeClock(), poll_interval=POLL,
        )
    return info.value


def _assert_case(case: Case) -> FlowError:
    err = _execute(case)
    assert type(err) is (FlowInputError if case.reason == "input_invalid" else err.__class__)
    assert err.reason == case.reason
    assert err.step_index == case.step
    assert err.kind == case.kind
    assert err.expected == case.expected
    assert list(err.expected) == sorted(err.expected)
    if case.has_summary:
        assert isinstance(err.summary, RedactedSummary)
        assert err.summary.rows == 24 or case.reason == "screen_size"
    else:
        assert err.summary is None
    assert tuple(r.status for r in err.audit) == case.statuses
    assert str(err) == case.message
    assert err.args == (case.message,)
    return err


_REGISTRY: list[str] = []


def reason(code: str):
    def mark(fn):
        _REGISTRY.append(code)
        return fn

    return mark


# --------------------------------------------------------------------------
# Case builders
# --------------------------------------------------------------------------

def _menu_with(text: str, col: int = 10, row: int = 19) -> Screen:
    screen = capture(MENU)
    for i, ch in enumerate(text):
        screen.cell_grid[row][col + i] = ord(ch)
    return screen


def _expect(*names, tolerate=(), timeout=1.0):
    return ExpectStep(tuple(names), tuple(tolerate), timeout)


def _case_input_invalid() -> Case:
    return Case(
        "input_invalid",
        Flow("t", (_expect("tk5-logon"),), inputs=(InputSpec("userid", "str", True, 8),)),
        Sess([capture("tk5-logon")]),
        message="input_invalid at step none (none): expected none (0); "
        "input userid violates required",
    )


def _case_timeout() -> Case:
    return Case(
        "timeout",
        Flow("t", (_expect("tk5-logon", tolerate=(MENU,)),)),
        Sess([capture(MENU)]),
        step=0, kind="expect", expected=("tk5-logon",), has_summary=True,
        statuses=("failed",),
        message="timeout at step 0 (expect): expected tk5-logon (1)",
    )


def _case_run_timeout() -> Case:
    return Case(
        "run_timeout",
        Flow(
            "t", (_expect("tk5-logon", tolerate=(MENU,), timeout=60.0),),
            timeouts=Timeouts(10.0, 1.0, 30.0),
        ),
        Sess([capture(MENU)]),
        step=0, kind="expect", statuses=("failed",),
        message="run_timeout at step 0 (expect): expected none (0)",
    )


def _case_unknown_screen() -> Case:
    return Case(
        "unknown_screen",
        Flow("t", (_expect("tk5-logon"),)),
        Sess([blank_screen()]),
        step=0, kind="expect", expected=("tk5-logon",), has_summary=True,
        statuses=("failed",),
        message="unknown_screen at step 0 (expect): expected tk5-logon (1)",
    )


def _case_ambiguous_screen() -> Case:
    return Case(
        "ambiguous_screen",
        Flow("t", (_expect("dup-b", "dup-a"),)),
        Sess([make_screen(24, 80, {(0, 0): "TINY"})]),
        signatures=[_TWIN_A, _TWIN_B],
        step=0, kind="expect", expected=("dup-a", "dup-b"), has_summary=True,
        statuses=("failed",),
        message="ambiguous_screen at step 0 (expect): expected dup-a,dup-b (2)",
    )


def _case_unexpected_screen() -> Case:
    # The menu is loaded because the second Expect_Step names it.
    return Case(
        "unexpected_screen",
        Flow("t", (_expect("tk5-logon"), _expect(MENU))),
        Sess([capture(MENU)]),
        step=0, kind="expect", expected=("tk5-logon",), has_summary=True,
        statuses=("failed",),
        message="unexpected_screen at step 0 (expect): expected tk5-logon (1)",
    )


def _case_loop_limit() -> Case:
    return Case(
        "loop_limit",
        Flow(
            "t",
            (HandleStep("tk5-logo", 1, (KeyStep("enter"),)), _expect("tk5-logon")),
        ),
        Sess([capture("tk5-logo"), partial_repaint("tk5-logo", 0), partial_repaint("tk5-logo", 1)]),
        step=0, kind="handle", statuses=("failed", "ok"),
        message="loop_limit at step 0 (handle): expected none (0)",
    )


def _case_bad_target() -> Case:
    screen = capture("tso-ready")
    screen.cell_grid[0][0] = SFToken(0xE8)  # protected
    screen.cursor_row, screen.cursor_col = 0, 2
    return Case(
        "bad_target",
        Flow("t", (_expect("tso-ready"), TypeStep(text="X"))),
        Sess([screen]),
        step=1, kind="type", has_summary=True, statuses=("ok", "failed"),
        message="bad_target at step 1 (type): expected none (0)",
    )


def _case_secret_target() -> Case:
    return Case(
        "secret_target",
        Flow("t", (_expect("tk5-logon"), TypeStep(input="password")), inputs=(_PASSWORD,)),
        Sess([capture("tk5-logon")]),
        inputs={"password": SECRET},
        step=1, kind="type", has_summary=True, statuses=("ok", "failed"),
        message="secret_target at step 1 (type): expected none (0)",
    )


def _case_hidden_output() -> Case:
    return Case(
        "hidden_output",
        Flow(
            "t", (_expect("tso-password-prompt"), ExtractStep("pw")),
            outputs=(OutputSpec("pw", "str", "tso-password-prompt", 1, 0, 4),),
        ),
        Sess([sentinel_password_screen(HIDDEN)]),
        step=1, kind="extract", has_summary=True, statuses=("ok", "failed"),
        message="hidden_output at step 1 (extract): expected none (0); output pw",
    )


def _case_output_type() -> Case:
    return Case(
        "output_type",
        Flow(
            "t", (_expect(MENU), ExtractStep("count")),
            outputs=(OutputSpec("count", "int", MENU, 19, 8, 22),),
        ),
        Sess([_menu_with("ZQ7KX")]),
        step=1, kind="extract", has_summary=True, statuses=("ok", "failed"),
        message="output_type at step 1 (extract): expected none (0); output count",
    )


def _case_screen_size() -> Case:
    return Case(
        "screen_size",
        Flow(
            "t", (_expect("tiny"), ExtractStep("o")),
            outputs=(OutputSpec("o", "str", "tiny", 0, 0, 4),),
        ),
        Sess([make_screen(23, 80, {(0, 0): "TINY"})]),
        signatures=[_TINY],
        step=1, kind="extract", has_summary=True, statuses=("ok", "failed"),
        message="screen_size at step 1 (extract): expected none (0); output o",
    )


_METHOD_STEP = {
    "read_screen": (0, "expect", ("failed",)),
    "string": (1, "type", ("ok", "failed")),
    "enter": (1, "key", ("ok", "failed")),
    "clear": (1, "key", ("ok", "failed")),
    "pf": (1, "key", ("ok", "failed")),
    "pa": (1, "key", ("ok", "failed")),
}


def _case_session_error(method: str, make=None, name: str = "RuntimeError") -> Case:
    make = make or (lambda: RuntimeError(f"boom {SECRET}", SECRET))
    steps: tuple = (_expect("tk5-logon"),)
    if method == "string":
        steps += (TypeStep(text="X"),)
    elif method in ("enter", "clear"):
        steps += (KeyStep(method),)
    elif method == "pf":
        steps += (KeyStep("pf", 3),)
    elif method == "pa":
        steps += (KeyStep("pa", 1),)
    step, kind, statuses = _METHOD_STEP[method]
    return Case(
        "session_error",
        Flow("t", steps),
        Sess([capture("tk5-logon")], raising={method: make}),
        step=step, kind=kind, statuses=statuses,
        message=f"session_error at step {step} ({kind}): expected none (0); {name}",
    )


_BUILDERS = {
    "input_invalid": _case_input_invalid,
    "timeout": _case_timeout,
    "run_timeout": _case_run_timeout,
    "unknown_screen": _case_unknown_screen,
    "ambiguous_screen": _case_ambiguous_screen,
    "unexpected_screen": _case_unexpected_screen,
    "loop_limit": _case_loop_limit,
    "bad_target": _case_bad_target,
    "secret_target": _case_secret_target,
    "hidden_output": _case_hidden_output,
    "output_type": _case_output_type,
    "screen_size": _case_screen_size,
    "session_error": lambda: _case_session_error("enter"),
}


# --------------------------------------------------------------------------
# One test per Reason_Code
# --------------------------------------------------------------------------

@reason("input_invalid")
def test_input_invalid():
    case = _case_input_invalid()
    err = _assert_case(case)
    assert isinstance(err, FlowInputError)
    assert case.session.calls == []  # no Session call before the Inputs are valid


@reason("timeout")
def test_timeout():
    case = _case_timeout()
    _assert_case(case)
    assert not any(c[0] in ("enter", "clear", "pf", "pa", "string") for c in case.session.calls)


@reason("run_timeout")
def test_run_timeout():
    case = _case_run_timeout()
    _assert_case(case)
    assert not any(c[0] in ("enter", "clear", "pf", "pa", "string") for c in case.session.calls)


@reason("unknown_screen")
def test_unknown_screen():
    _assert_case(_case_unknown_screen())


@reason("ambiguous_screen")
def test_ambiguous_screen():
    case = _case_ambiguous_screen()
    _assert_case(case)
    assert case.session.calls == [("read_screen",)]  # stopped at once


@reason("unexpected_screen")
def test_unexpected_screen():
    case = _case_unexpected_screen()
    _assert_case(case)
    assert case.session.calls == [("read_screen",)]


@reason("loop_limit")
def test_loop_limit():
    case = _case_loop_limit()
    _assert_case(case)
    assert [c for c in case.session.calls if c[0] == "enter"] == [("enter",)]


@reason("bad_target")
def test_bad_target():
    case = _case_bad_target()
    _assert_case(case)
    assert not any(c[0] == "string" for c in case.session.calls)


@reason("secret_target")
def test_secret_target():
    case = _case_secret_target()
    _assert_case(case)
    assert not any(c[0] == "string" for c in case.session.calls)


@reason("hidden_output")
def test_hidden_output():
    _assert_case(_case_hidden_output())


@reason("output_type")
def test_output_type():
    _assert_case(_case_output_type())


@reason("screen_size")
def test_screen_size():
    _assert_case(_case_screen_size())


@reason("session_error")
@pytest.mark.parametrize("method", ["read_screen", "string", "enter", "clear", "pf", "pa"])
def test_session_error_for_each_session_method(method):
    case = _case_session_error(method)
    err = _assert_case(case)
    # only the class name and the Step_Index; nothing of the exception itself
    assert (SECRET in str(err)) is False
    assert ("boom" in str(err)) is False
    assert err.__cause__ is None
    assert err.__context__ is None
    assert err.__suppress_context__ is True
    assert case.session.calls[-1][0] == method  # nothing was sent afterwards
    assert ("close",) not in case.session.calls


def test_session_error_for_a_secret_type_step_with_a_foreign_exception():
    class HostGlitch(Exception):
        pass

    case = Case(
        "session_error",
        Flow(
            "t", (_expect("tso-password-prompt"), TypeStep(input="password")),
            inputs=(_PASSWORD,),
        ),
        Sess(
            [capture("tso-password-prompt")],
            raising={"string": lambda: HostGlitch(f"glitch {SECRET}", SECRET)},
        ),
        inputs={"password": SECRET},
        step=1, kind="type", statuses=("ok", "failed"),
        message="session_error at step 1 (type): expected none (0); HostGlitch",
    )
    err = _assert_case(case)
    assert not any(_leaks(v, SECRET) for v in _surface(err))
    assert err.__cause__ is None and err.__context__ is None


@pytest.mark.parametrize(
    ("make", "name"),
    [
        (lambda: ConnectorError(f"c {SECRET}"), "ConnectorError"),
        (lambda: OSError(f"o {SECRET}"), "OSError"),
        # Requirement 7.6 converts any Exception, not only these two.
        (lambda: RuntimeError(f"r {SECRET}"), "RuntimeError"),
        (lambda: KeyError(SECRET), "KeyError"),
    ],
)
def test_session_exceptions_are_converted_outside_a_secret_type_step(make, name):
    err = _assert_case(_case_session_error("enter", make, name))
    assert not any(_leaks(v, SECRET) for v in _surface(err))


def test_the_tests_cover_reason_codes_exactly():
    assert len(_REGISTRY) == len(set(_REGISTRY))
    assert tuple(sorted(_REGISTRY)) == tuple(sorted(REASON_CODES))
    assert tuple(sorted(_BUILDERS)) == tuple(sorted(REASON_CODES))


# --------------------------------------------------------------------------
# Generic checks, run for every Reason_Code
# --------------------------------------------------------------------------

_LINE = re.compile(
    r"[a-z_]+ at step (?:none|\d+) \((?:none|[a-z]+)\): "
    r"expected (?:none|[A-Za-z0-9_-]+(?:,[A-Za-z0-9_-]+)*) \(\d+\)(?:; [^\r\n]+)?"
)


def _leaks(value, sentinel, depth=0) -> bool:
    if depth > 6:
        return False
    if isinstance(value, str):
        return sentinel in value
    if isinstance(value, bytes):
        return sentinel.encode() in value
    if isinstance(value, dict):
        return any(_leaks(k, sentinel, depth + 1) or _leaks(v, sentinel, depth + 1)
                   for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_leaks(v, sentinel, depth + 1) for v in value)
    if isinstance(value, BaseException):
        return _leaks(value.args, sentinel, depth + 1) or sentinel in repr(value)
    return sentinel in repr(value)


def _surface(err):
    """Every value a caller can reach on the error, plus its text forms."""
    yield str(err)
    yield repr(err)
    yield err.args
    for name in dir(err):
        if not name.startswith("__"):
            yield getattr(err, name)
    yield vars(err)
    if getattr(err, "summary", None) is not None:
        yield err.summary.to_text()
        yield err.summary.to_dict()
    yield [repr(r) for r in err.audit]


def _flow_frames(err):
    tb = err.__traceback__
    while tb is not None:
        if str(tb.tb_frame.f_globals.get("__name__", "")).startswith("greenscreen.flow"):
            yield tb.tb_frame
        tb = tb.tb_next


def _holds_screen(value, inputs, depth=0) -> bool:
    if value is inputs or isinstance(value, (Screen, Field, FieldGeom, ScreenView)):
        return True
    if depth > 6:
        return False
    if isinstance(value, dict):
        return any(_holds_screen(v, inputs, depth + 1) for v in value.values())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_holds_screen(v, inputs, depth + 1) for v in value)
    return False


_ALL = sorted(_BUILDERS)


@pytest.mark.parametrize("code", _ALL)
def test_message_is_one_documented_line_of_at_most_500_characters(code):
    err = _execute(_BUILDERS[code]())
    text = str(err)
    assert len(text) <= 500
    assert "\n" not in text and "\r" not in text
    assert _LINE.fullmatch(text) is not None
    assert text.startswith(f"{code} at step ")
    count = int(re.search(r"\((\d+)\)", text.split(": expected ", 1)[1]).group(1))
    assert count == len(err.expected)


@pytest.mark.parametrize("code", _ALL)
def test_error_text_and_attributes_hold_no_secret_and_no_hidden_cell(code):
    case = _BUILDERS[code]()
    err = _execute(case)
    verdicts = [
        _leaks(value, sentinel)
        for value in _surface(err)
        for sentinel in (SECRET, HIDDEN)
    ]
    assert not any(verdicts)


@pytest.mark.parametrize("code", _ALL)
def test_no_screen_is_reachable_from_the_error(code):
    case = _BUILDERS[code]()
    err = _execute(case)
    for name in dir(err):
        if not name.startswith("__"):
            assert _holds_screen(getattr(err, name), case.inputs) is False
    assert _holds_screen(err.args, case.inputs) is False
    assert _holds_screen(vars(err), case.inputs) is False
    frame_verdicts = [
        _holds_screen(value, case.inputs)
        for frame in _flow_frames(err)
        for value in list(frame.f_locals.values())
    ]
    assert not any(frame_verdicts)
    gc.collect()
    assert [r() is not None for r in case.session.refs].count(True) == 0


@pytest.mark.parametrize("code", _ALL)
def test_every_screen_is_released_before_the_error_is_built(code):
    case = _BUILDERS[code]()
    err = _execute(case)
    if code == "input_invalid":
        assert _HOLDER["alive_at_raise"] is None  # no run, no FlowError from the runner
    else:
        assert _HOLDER["alive_at_raise"] == 0
    assert isinstance(err, FlowError)


@pytest.mark.parametrize("code", _ALL)
def test_every_error_has_no_cause_and_no_context(code):
    err = _execute(_BUILDERS[code]())
    assert err.__cause__ is None
    assert err.__context__ is None


def test_comparison_screen_is_released_before_the_error_is_raised():
    logon = capture("tk5-logon")
    altered = capture("tk5-logon")
    for r in (0, 1, 22):  # the rows the signature reads; fields are untouched
        for c in range(altered.columns):
            if not isinstance(altered.cell_grid[r][c], SFToken):
                altered.cell_grid[r][c] = ord("#")
    case = Case(
        "unknown_screen",
        Flow("t", (_expect("tk5-logon"), KeyStep("enter"))),
        Sess([logon, altered], per_read=True),
        step=1, kind="key", expected=("tk5-logon",), has_summary=True,
        statuses=("ok", "failed"),
        message="unknown_screen at step 1 (key): expected tk5-logon (1)",
    )
    err = _assert_case(case)
    assert _HOLDER["built"] == 1  # a Comparison_Screen existed
    assert _HOLDER["alive_at_raise"] == 0  # and was gone before FlowError was built
    assert not any(c[0] == "enter" for c in case.session.calls)
    assert err.__cause__ is None and err.__context__ is None


# --------------------------------------------------------------------------
# FlowInputError, FlowDefinitionError, poll_interval
# --------------------------------------------------------------------------

def test_flow_input_error_for_a_secret_value_names_the_input_only():
    flow = Flow("t", (_expect("tso-password-prompt"),), inputs=(_PASSWORD,))
    session = Sess([capture("tso-password-prompt")])
    with pytest.raises(FlowInputError) as info:
        run_flow(flow, session, {"password": SECRET + "X"}, clock=FakeClock())
    err = info.value
    assert str(err) == (
        "input_invalid at step none (none): expected none (0); "
        "input password violates max_length"
    )
    assert not any(_leaks(v, SECRET) for v in _surface(err))
    assert err.__cause__ is None and err.__context__ is None
    assert session.calls == []


def test_flow_definition_error_holds_no_secret_and_no_cause():
    flow = Flow("t", (_expect("tso-password-prompt"),), inputs=(_PASSWORD,))
    session = Sess([capture("tso-password-prompt")])
    with pytest.raises(FlowDefinitionError) as info:
        run_flow(flow, session, {"password": SECRET}, signatures=[], clock=FakeClock())
    err = info.value
    assert "tso-password-prompt" in str(err)
    assert not any(_leaks(v, SECRET) for v in (str(err), repr(err), err.args))
    assert err.__cause__ is None and err.__context__ is None
    assert session.calls == []


@pytest.mark.parametrize("interval", [0, 0.009, 0.0099, 1.01, 5, -0.5])
def test_poll_interval_outside_the_range_raises_value_error_before_any_call(interval):
    session = Sess([capture("tk5-logon")])
    with pytest.raises(ValueError):
        run_flow(
            Flow("t", (_expect("tk5-logon"),)), session, {},
            clock=FakeClock(), poll_interval=interval,
        )
    assert session.calls == []


@pytest.mark.parametrize("interval", [0.01, 0.5, 1, 1.0])
def test_poll_interval_inside_the_range_is_accepted(interval):
    session = Sess([capture("tk5-logon")])
    result = run_flow(
        Flow("t", (_expect("tk5-logon"),)), session, {},
        clock=FakeClock(), poll_interval=interval,
    )
    assert [r.status for r in result.audit] == ["ok"]
