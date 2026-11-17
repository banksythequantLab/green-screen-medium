"""Unit tests for the finally rules of the flow runner (flow-runtime task 10.11).

Covers Requirements 12.2, 12.3, 13.1 to 13.9, 14.8, 15.2, 15.4 and 18.7.
Custom in-memory signatures give full control over which screen the Session
shows at each read; the capture-based cases need real field layouts.
Secret values are only compared through booleans.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.errors import FlowError, FlowInputError
from greenscreen.flow.model import (
    ExpectStep,
    Flow,
    HandleStep,
    InputSpec,
    KeyStep,
    Timeouts,
    TypeStep,
    plan,
)
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer.signature import ScreenSignature, TextAtMatcher

from tests.flow_support import FakeClock, ScriptedSession, capture
from tests.screen_support import make_screen

_SECRET = "Zx9!hush"  # test-only value, never printed or asserted on directly


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _scr(text: str, variant: str = "") -> object:
    cells = {(0, 1): text}
    if variant:
        cells[(5, 1)] = variant
    return make_screen(24, 80, cells)


SIGS = [
    ScreenSignature("scr-a", (TextAtMatcher(0, 1, "SCRA"),)),
    ScreenSignature("scr-b", (TextAtMatcher(0, 1, "SCRB"),)),
    ScreenSignature("amb-1", (TextAtMatcher(0, 1, "AMBG"),)),
    ScreenSignature("amb-2", (TextAtMatcher(0, 1, "AMBG"),)),
]


class ListSession:
    """Serves ``reads`` in order (the last one repeats) and records every call."""

    def __init__(self, reads, *, clock=None, tick=0.0, raise_on_read=None):
        self._reads = list(reads)
        self._n = 0
        self._clock = clock
        self._tick = tick
        self._raise_on = raise_on_read
        self.calls: list[tuple] = []

    def read_screen(self):
        self.calls.append(("read",))
        self._n += 1
        if self._clock is not None:
            self._clock.now += self._tick
        if self._raise_on == self._n:
            raise RuntimeError("boom")
        i = min(self._n - 1, len(self._reads) - 1)
        return _copy(self._reads[i])

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


def _copy(screen):
    from tests.flow_support import copy_screen

    return copy_screen(screen)


def _keys(session):
    return [c for c in session.calls if c[0] in ("enter", "clear", "pf", "pa")]


def _flatten(items):
    for item in items:
        yield item
        yield from _flatten(item.children)


def _finally_indices(flow):
    return [i.index for i in _flatten(plan(flow)[1])]


def _all_finally_recorded(flow, audit):
    recorded = {r.step_index for r in audit if r.phase == "finally"}
    assert set(_finally_indices(flow)) <= recorded


def _status(audit):
    return [(r.step_index, r.status) for r in audit]


A = ExpectStep(("scr-a",))
B = ExpectStep(("scr-b",))
ENTER = KeyStep("enter")
BODY = HandleStep("scr-a", 1, (ENTER,))  # finally Handle: takes index n, body n+1
T1 = Timeouts(step=1.0, run=60.0, finally_=10.0)
# An Expect_Step that times out on scr-a (tolerated), then a Handle that must be skipped.
FAIL_FIN = (ExpectStep(("scr-b",), tolerate=("scr-a",)), BODY)


def _run_failing(flow, session, clock=None, inputs=None, sigs=SIGS):
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, inputs or {}, signatures=sigs, clock=clock or FakeClock())
    return info.value


# --------------------------------------------------------------------------
# 13.1 finally after success with the carried Current_Screen
# --------------------------------------------------------------------------

def test_finally_runs_after_success_with_the_carried_screen():
    flow = Flow("t", (A,), finally_steps=(BODY, B))
    session = ListSession([_scr("SCRA"), _scr("SCRA"), _scr("SCRB"), _scr("SCRB")])
    result = run_flow(flow, session, {}, signatures=SIGS, clock=FakeClock())
    # main Expect read; no read for the carried screen in the Handle; body pre-key
    # read, key, poll read; finally Expect read
    assert session.calls == [("read",), ("read",), ("enter",), ("read",), ("read",)]
    assert _status(result.audit) == [(0, "ok"), (1, "ok"), (2, "ok"), (3, "ok")]
    assert [r.phase for r in result.audit] == ["steps", "finally", "finally", "finally"]
    assert ("close",) not in session.calls


# --------------------------------------------------------------------------
# 13.2 finally after a failure that leaves a Current_Screen
# --------------------------------------------------------------------------

def test_finally_runs_after_unexpected_screen_with_a_held_screen():
    flow = Flow("t", (A, B), finally_steps=(BODY,), timeouts=T1)
    session = ListSession([_scr("SCRA"), _scr("SCRA"), _scr("SCRA"), _scr("SCRB")])
    err = _run_failing(flow, session)
    assert err.reason == "unexpected_screen" and err.step_index == 1
    assert len(_keys(session)) == 1
    assert _status(err.audit) == [(0, "ok"), (1, "failed"), (2, "ok"), (3, "ok")]


def test_finally_runs_after_loop_limit():
    flow = Flow("t", (BODY, B), finally_steps=(BODY,), timeouts=T1)
    reads = [_scr("SCRA", "V0"), _scr("SCRA", "V0"), _scr("SCRA", "V1"),
             _scr("SCRA", "V1"), _scr("SCRB")]
    session = ListSession(reads)
    err = _run_failing(flow, session)
    assert err.reason == "loop_limit" and err.step_index == 0
    assert len(_keys(session)) == 2  # one body key, one finally key
    assert _status(err.audit) == [
        (0, "failed"), (1, "ok"), (3, "ok"), (4, "ok"),
    ]
    assert [r.phase for r in err.audit] == ["steps", "steps", "finally", "finally"]


def test_finally_runs_after_bad_target():
    fin = (HandleStep("tk5-logo", 1, (ENTER,)), ExpectStep(("tso-ready",)))
    flow = Flow("t", (ExpectStep(("tk5-logo",)), TypeStep(text="X")), finally_steps=fin)
    session = ScriptedSession([capture("tk5-logo"), capture("tso-ready")])
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=FakeClock())
    err = info.value
    assert err.reason == "bad_target" and err.step_index == 1
    assert [c for c in session.calls if c[0] == "string"] == []
    assert [c for c in session.calls if c[0] == "enter"] == [("enter",)]
    assert _status(err.audit) == [(0, "ok"), (1, "failed"), (2, "ok"), (3, "ok"), (4, "ok")]


def test_finally_runs_after_secret_target_without_typing_the_secret():
    fin = (HandleStep("tk5-logon", 1, (ENTER,)), ExpectStep(("tso-ready",)))
    flow = Flow(
        "t",
        (ExpectStep(("tk5-logon",)), TypeStep(input="pw")),
        inputs=(InputSpec("pw", "str", True, 16, None, True),),
        finally_steps=fin,
    )
    session = ScriptedSession([capture("tk5-logon"), capture("tso-ready")])
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {"pw": _SECRET}, clock=FakeClock())
    err = info.value
    assert err.reason == "secret_target" and err.step_index == 1
    assert [c for c in session.calls if c[0] == "string"] == []
    assert [c for c in session.calls if c[0] == "enter"] == [("enter",)]
    leaked = _SECRET in str(err) or _SECRET in repr(session.calls)
    assert leaked is False
    assert _status(err.audit) == [(0, "ok"), (1, "failed"), (2, "ok"), (3, "ok"), (4, "ok")]


# --------------------------------------------------------------------------
# 13.3, 13.9 skipped finally: zero keys, a skipped record for every index
# --------------------------------------------------------------------------

def _timeout_flow(timeouts):
    return Flow(
        "t", (A, ExpectStep(("scr-b",), tolerate=("scr-a",))),
        finally_steps=(BODY,), timeouts=timeouts,
    )


_KEY_FLOW = Flow(
    "t",
    (ExpectStep(("scr-a",), tolerate=("amb-1", "amb-2")), ENTER),
    finally_steps=(BODY,),
    timeouts=T1,
)

_SKIP_CASES = {
    "unknown_screen": (_KEY_FLOW, lambda: ListSession([_scr("SCRA"), _scr("UNKN")])),
    "ambiguous_screen": (_KEY_FLOW, lambda: ListSession([_scr("SCRA"), _scr("AMBG")])),
    "timeout": (_timeout_flow(T1), lambda: ListSession([_scr("SCRA")])),
    "run_timeout": (
        _timeout_flow(Timeouts(step=10.0, run=1.0, finally_=10.0)),
        lambda: ListSession([_scr("SCRA")]),
    ),
    "session_error": (_KEY_FLOW, lambda: ListSession([_scr("SCRA")], raise_on_read=2)),
}


@pytest.mark.parametrize("reason", sorted(_SKIP_CASES))
def test_finally_is_skipped_after_these_reasons_with_a_screen_held(reason):
    flow, make_session = _SKIP_CASES[reason]
    session = make_session()
    err = _run_failing(flow, session)
    assert err.reason == reason
    assert _keys(session) == []
    fin = [r for r in err.audit if r.phase == "finally"]
    assert [r.step_index for r in fin] == _finally_indices(flow) == [2, 3]
    assert all(
        (r.status, r.duration_seconds, r.iteration, r.signature)
        == ("skipped", 0.0, None, None)
        for r in fin
    )
    _all_finally_recorded(flow, err.audit)


def test_finally_is_skipped_when_no_current_screen_is_held():
    flow = Flow("t", (B,), finally_steps=(BODY,), timeouts=T1)
    session = ListSession([_scr("SCRA")])
    err = _run_failing(flow, session)
    assert err.reason == "unexpected_screen"
    assert _keys(session) == []
    assert _status(err.audit) == [(0, "failed"), (1, "skipped"), (2, "skipped")]
    _all_finally_recorded(flow, err.audit)


def test_input_invalid_runs_no_finally_and_makes_no_session_call():
    flow = Flow("t", (A,), inputs=(InputSpec("uid", "str", True, 8),), finally_steps=(BODY,))
    session = ListSession([_scr("SCRA")])
    with pytest.raises(FlowInputError) as info:
        run_flow(flow, session, {}, signatures=SIGS, clock=FakeClock())
    assert info.value.reason == "input_invalid"
    assert isinstance(info.value, FlowError)
    assert session.calls == []
    assert info.value.audit == ()


# --------------------------------------------------------------------------
# 13.5, 13.6, 13.8 failed Finally_Steps
# --------------------------------------------------------------------------

def test_main_error_wins_over_a_failed_finally_step():
    flow = Flow("t", (A, B), finally_steps=FAIL_FIN, timeouts=T1)
    session = ListSession([_scr("SCRA")])
    err = _run_failing(flow, session)
    assert err.reason == "unexpected_screen" and err.step_index == 1
    assert _status(err.audit) == [
        (0, "ok"), (1, "failed"), (2, "failed"), (3, "skipped"), (4, "skipped"),
    ]
    assert _keys(session) == []
    _all_finally_recorded(flow, err.audit)


def test_failed_finally_step_after_success_is_raised_and_skips_later_steps():
    flow = Flow("t", (A,), finally_steps=FAIL_FIN, timeouts=T1)
    session = ListSession([_scr("SCRA")])
    err = _run_failing(flow, session)
    assert err.reason == "timeout" and err.step_index == 1
    assert _status(err.audit) == [(0, "ok"), (1, "failed"), (2, "skipped"), (3, "skipped")]
    assert all(r.duration_seconds == 0.0 for r in err.audit[2:])
    assert _keys(session) == []
    _all_finally_recorded(flow, err.audit)


def test_failed_handle_in_finally_skips_later_steps():
    flow = Flow("t", (A,), finally_steps=(BODY, B), timeouts=T1)
    reads = [_scr("SCRA", "V0"), _scr("SCRA", "V0"), _scr("SCRA", "V1")]
    session = ListSession(reads)
    err = _run_failing(flow, session)
    # the Handle reuses the carried screen, runs one iteration, then sees scr-a again
    assert err.reason == "loop_limit" and err.step_index == 1
    assert err.audit[-1].step_index == 3 and err.audit[-1].status == "skipped"
    assert len(_keys(session)) == 1
    _all_finally_recorded(flow, err.audit)


# --------------------------------------------------------------------------
# 13.7 finally budget
# --------------------------------------------------------------------------

def test_finally_budget_raises_run_timeout():
    wait = ExpectStep(("scr-b",), tolerate=("scr-a",))
    flow = Flow(
        "t", (A,), finally_steps=(wait, ENTER),
        timeouts=Timeouts(step=10.0, run=60.0, finally_=1.0),
    )
    session = ListSession([_scr("SCRA")])
    err = _run_failing(flow, session, clock=FakeClock())
    assert err.reason == "run_timeout" and err.step_index == 1
    assert _keys(session) == []
    assert _status(err.audit) == [(0, "ok"), (1, "failed"), (2, "skipped")]


# --------------------------------------------------------------------------
# 14.8, 15.2 audit trail order and durations from the fake Clock
# --------------------------------------------------------------------------

def test_audit_holds_every_step_in_order_with_clock_durations():
    clock = FakeClock()
    flow = Flow("t", (A, ENTER, B), finally_steps=(B,))
    session = ListSession(
        [_scr("SCRA"), _scr("SCRA"), _scr("SCRB")], clock=clock, tick=0.5
    )
    result = run_flow(flow, session, {}, signatures=SIGS, clock=clock)
    assert [r.step_index for r in result.audit] == [0, 1, 2, 3]
    assert [r.phase for r in result.audit] == ["steps", "steps", "steps", "finally"]
    assert [r.kind for r in result.audit] == ["expect", "key", "expect", "expect"]
    assert [r.duration_seconds for r in result.audit] == [0.5, 0.5, 0.5, 0.5]
