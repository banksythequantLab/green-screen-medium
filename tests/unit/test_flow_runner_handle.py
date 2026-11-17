"""Unit tests for the Handle_Step (flow-runtime task 10.9).

Covers Requirements 9.1 to 9.8 and 18.7. Screens come from the captures
through ``tests.flow_support``; time comes from the fake Clock.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import (
    ExpectStep,
    Flow,
    HandleStep,
    KeyStep,
    Timeouts,
    TypeStep,
)
from greenscreen.flow.runner import run_flow

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    blank_screen,
    capture,
    partial_repaint,
    pause_variant,
)

PAUSE = "tso-pause"
POLL = 0.25  # exact in binary floating point, so settle sums are exact


def _run(flow, states, *, echo=False, clock=None):
    clock = clock or FakeClock()
    session = ScriptedSession(states, echo_typing=echo)
    result = run_flow(flow, session, {}, clock=clock, poll_interval=POLL)
    return result, session, clock


def _run_failing(flow, states, *, clock=None):
    clock = clock or FakeClock()
    session = ScriptedSession(states)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=clock, poll_interval=POLL)
    return info.value, session, clock


def _rows(audit):
    return [(r.step_index, r.status, r.iteration) for r in audit]


def _keys(session):
    return [c for c in session.calls if c[0] not in ("read", "string")]


def _reads(session):
    return [c for c in session.calls if c[0] == "read"]


BODY = (KeyStep("enter"),)
# run_flow only knows the signature names a Flow mentions, so each Flow ends in
# (or starts with) a Step that names the screens the script will show.
TAIL = ExpectStep(("ispf-primary-menu",))


# --------------------------------------------------------------------------
# 9.6 zero iterations, 9.1 Current_Screen reuse
# --------------------------------------------------------------------------

def test_zero_iterations_when_first_screen_is_not_the_handled_name():
    flow = Flow("t", (HandleStep(PAUSE, 3, BODY), TAIL))
    result, session, _ = _run(flow, [capture("ispf-primary-menu")])
    assert _rows(result.audit) == [(0, "ok", None), (1, "skipped", None), (2, "ok", None)]
    assert result.audit[0].signature == PAUSE
    assert _keys(session) == []
    assert result.audit[1].duration_seconds == 0.0


def test_zero_iterations_keeps_the_screen_as_current_for_the_next_handle():
    first = HandleStep(PAUSE, 3, BODY)
    second = HandleStep("ispf-primary-menu", 1, BODY)
    flow = Flow("t", (first, second, ExpectStep(("tso-ready",))))
    result, session, _ = _run(flow, [capture("ispf-primary-menu"), capture("tso-ready")])
    # first Handle reads once; second reuses that screen (no read), pre-key read,
    # enter, poll read; the Expect_Step reads once more.
    assert session.calls == [("read",), ("read",), ("enter",), ("read",), ("read",)]
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "skipped", None), (2, "ok", None), (3, "ok", 1), (4, "ok", None),
    ]


def test_current_screen_is_reused_without_read_screen():
    flow = Flow("t", (ExpectStep(("tk5-logon",)), HandleStep(PAUSE, 3, BODY)))
    result, session, _ = _run(flow, [capture("tk5-logon")])
    assert session.calls == [("read",)]  # the Expect_Step's read only
    assert _rows(result.audit)[:2] == [(0, "ok", None), (1, "ok", None)]


def test_current_screen_reused_for_a_matching_handle_too():
    flow = Flow(
        "t", (ExpectStep((PAUSE,), tolerate=("ispf-primary-menu",)), HandleStep(PAUSE, 1, BODY))
    )
    result, session, _ = _run(
        flow, [pause_variant(0), capture("ispf-primary-menu")]
    )
    # Expect read, body pre-key read, enter, one poll read for the next screen
    assert session.calls == [("read",), ("read",), ("enter",), ("read",)]
    assert _rows(result.audit) == [(0, "ok", None), (1, "ok", None), (2, "ok", 1)]


# --------------------------------------------------------------------------
# 9.2, 9.3 one iteration then a different screen
# --------------------------------------------------------------------------

def test_one_iteration_then_a_different_screen_is_kept_as_current():
    flow = Flow("t", (HandleStep(PAUSE, 3, BODY), TAIL))
    states = [pause_variant(0), capture("ispf-primary-menu")]
    result, session, _ = _run(flow, states)
    assert _rows(result.audit) == [(0, "ok", None), (1, "ok", 1), (2, "ok", None)]
    assert result.audit[0].signature == PAUSE
    # Handle read, body pre-key read, enter, next-screen read, Expect_Step read
    assert session.calls == [("read",), ("read",), ("enter",), ("read",), ("read",)]


def test_several_iterations_number_the_body_records_from_one():
    flow = Flow("t", (HandleStep(PAUSE, 5, BODY), TAIL))
    states = [pause_variant(0), pause_variant(1), pause_variant(2), capture("ispf-primary-menu")]
    result, session, _ = _run(flow, states)
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "ok", 1), (1, "ok", 2), (1, "ok", 3), (2, "ok", None),
    ]
    assert _keys(session) == [("enter",)] * 3


# --------------------------------------------------------------------------
# 9.1 unknown screens until the Step timeout
# --------------------------------------------------------------------------

def test_unknown_screen_until_the_step_timeout_raises_unknown_screen():
    flow = Flow("t", (HandleStep(PAUSE, 3, BODY),), timeouts=Timeouts(step=1.0))
    err, session, clock = _run_failing(flow, [blank_screen()])
    assert err.reason == "unknown_screen"
    assert err.step_index == 0
    assert _rows(err.audit) == [(0, "failed", None)]
    assert _keys(session) == []
    assert clock.sleeps == [POLL] * 4


# --------------------------------------------------------------------------
# 9.5 settle
# --------------------------------------------------------------------------

def _after_enter(*states):
    """Flow prefix: Expect the logon screen, press Enter; the Handle_Step runs on the next state."""
    return [capture("tk5-logon"), *states]


_PREFIX = (ExpectStep(("tk5-logon",), tolerate=("ispf-primary-menu",)), KeyStep("enter"))


def test_settle_with_a_different_name_runs_no_body():
    handle = HandleStep(PAUSE, 2, BODY, settle=1.0)
    flow = Flow("t", (*_PREFIX, handle))
    menu = ScriptedState(capture("ispf-primary-menu"), repaints=(pause_variant(0),))
    result, session, clock = _run(flow, _after_enter(menu))
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "ok", None), (2, "ok", None), (3, "skipped", None),
    ]
    assert _keys(session) == [("enter",)]  # only the prefix key
    assert clock.sleeps == [POLL]  # left the settle loop on the first different name


def test_settle_ignores_unknown_screens_and_runs_body_when_still_shown():
    handle = HandleStep(PAUSE, 2, BODY, settle=1.0)
    flow = Flow("t", (*_PREFIX, handle))
    shown = ScriptedState(
        pause_variant(1), repaints=(pause_variant(0), blank_screen())
    )
    states = _after_enter(shown, capture("ispf-primary-menu"))
    result, session, clock = _run(flow, states)
    assert clock.sleeps == [POLL] * 4  # exactly settle seconds on the fake Clock
    assert sum(clock.sleeps) == 1.0
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "ok", None), (2, "ok", None), (3, "ok", 1),
    ]
    assert _keys(session) == [("enter",), ("enter",)]  # prefix key and one body key


def test_settle_zero_does_not_sleep():
    flow = Flow("t", (*_PREFIX, HandleStep(PAUSE, 2, BODY)))
    shown = ScriptedState(pause_variant(0))
    _, _, clock = _run(flow, _after_enter(shown, capture("ispf-primary-menu")))
    assert clock.sleeps == []


def test_settle_reads_use_the_poll_interval_and_the_last_sleep_is_clipped():
    handle = HandleStep(PAUSE, 1, BODY, settle=0.375)
    flow = Flow("t", (*_PREFIX, handle))
    shown = ScriptedState(pause_variant(1), repaints=(pause_variant(0),))
    _, _, clock = _run(flow, _after_enter(shown, capture("ispf-primary-menu")))
    assert clock.sleeps == [0.25, 0.125]


# --------------------------------------------------------------------------
# 9.4, 9.7 loop_limit
# --------------------------------------------------------------------------

@pytest.mark.parametrize("max_count", [1, 2, 4])
def test_loop_limit_after_exactly_max_count_keys(max_count):
    handle = HandleStep(PAUSE, max_count, BODY)
    flow = Flow("t", (handle,))
    states = [pause_variant(i) for i in range(max_count + 3)]
    err, session, _ = _run_failing(flow, states)
    assert err.reason == "loop_limit"
    assert err.step_index == 0
    assert err.kind == "handle"
    assert _keys(session) == [("enter",)] * max_count
    expected = [(0, "failed", None)] + [(1, "ok", i) for i in range(1, max_count + 1)]
    assert _rows(err.audit) == expected


def test_handle_step_is_recorded_failed_and_no_key_follows():
    flow = Flow("t", (HandleStep(PAUSE, 1, BODY), TAIL))
    err, session, _ = _run_failing(flow, [pause_variant(0), pause_variant(1), pause_variant(2)])
    assert err.audit[0].status == "failed"
    assert all(r.step_index != 2 for r in err.audit)  # the next Step never began
    assert _keys(session) == [("enter",)]


# --------------------------------------------------------------------------
# 9.2 the Step timeout restarts for each wait
# --------------------------------------------------------------------------

def test_step_timeout_restarts_for_each_wait():
    handle = HandleStep(PAUSE, 3, BODY)
    flow = Flow("t", (handle, TAIL), timeouts=Timeouts(step=1.0))
    # Every wait serves the Pre_Key_Screen three times (0.75 s of waiting).
    states = [
        pause_variant(0),
        ScriptedState(pause_variant(1), stale_reads=3),
        ScriptedState(pause_variant(2), stale_reads=3),
        ScriptedState(capture("ispf-primary-menu"), stale_reads=3),
    ]
    result, _, clock = _run(flow, states)
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "ok", 1), (1, "ok", 2), (1, "ok", 3), (2, "ok", None),
    ]
    assert sum(clock.sleeps) == 2.25  # longer than the Step timeout in total


def test_one_wait_longer_than_the_step_timeout_raises_timeout():
    handle = HandleStep(PAUSE, 3, BODY)
    flow = Flow("t", (handle, TAIL), timeouts=Timeouts(step=1.0))
    states = [pause_variant(0), ScriptedState(pause_variant(1), stale_reads=6)]
    err, session, _ = _run_failing(flow, states)
    assert err.reason == "timeout"
    assert err.kind == "handle"
    assert err.step_index == 0
    assert _keys(session) == [("enter",)]


# --------------------------------------------------------------------------
# 9.8 pre-key rules for body Steps
# --------------------------------------------------------------------------

def test_body_type_and_key_pass_the_pre_key_check_with_iteration_one():
    handle = HandleStep("tk5-logon", 1, (TypeStep(text="X"), KeyStep("enter")))
    flow = Flow("t", (handle, TAIL))
    result, session, _ = _run(
        flow, [capture("tk5-logon"), capture("ispf-primary-menu")], echo=True
    )
    assert _rows(result.audit) == [(0, "ok", None), (1, "ok", 1), (2, "ok", 1), (3, "ok", None)]
    assert session.calls == [
        ("read",), ("string", "X"), ("read",), ("enter",), ("read",), ("read",),
    ]


def test_body_key_pre_key_failure_names_the_body_step_and_iteration():
    handle = HandleStep(PAUSE, 3, BODY)
    flow = Flow("t", (handle,))
    # After the first Enter the poll sees a pause screen, but the pre-key read of
    # iteration 2 then shows the menu: the pre-key check must stop before any key.
    states = [
        pause_variant(0),
        ScriptedState(capture("ispf-primary-menu"), repaints=(pause_variant(1),)),
    ]
    err, session, _ = _run_failing(flow, states)
    assert err.reason == "unexpected_screen"
    assert err.step_index == 1
    assert err.kind == "key"
    assert err.expected == (PAUSE,)
    assert _rows(err.audit) == [(0, "failed", None), (1, "ok", 1), (1, "failed", 2)]
    assert _keys(session) == [("enter",)]  # no key for iteration 2


# --------------------------------------------------------------------------
# 9.1 the Pre_Key_Name is an accepted name for a Handle_Step
# --------------------------------------------------------------------------

def test_handle_step_accepts_the_pre_key_name_as_the_next_screen():
    handle = HandleStep("ispf-primary-menu", 2, BODY)
    flow = Flow("t", (*_PREFIX, handle, ExpectStep(("tk5-logon",))))
    # After Enter the host repaints the logon screen (the Pre_Key_Name) with a
    # changed cell: a Handle_Step takes it; an Expect_Step would not accept it.
    states = [capture("tk5-logon"), partial_repaint("tk5-logon", 0)]
    result, session, _ = _run(flow, states)
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "ok", None), (2, "ok", None), (3, "skipped", None),
        (4, "ok", None),
    ]
    assert result.audit[2].signature == "ispf-primary-menu"
    assert _keys(session) == [("enter",)]


def test_handle_step_still_waits_while_the_screen_equals_the_pre_key_screen():
    handle = HandleStep("ispf-primary-menu", 2, BODY)
    flow = Flow("t", (*_PREFIX, handle))
    states = [
        capture("tk5-logon"),
        ScriptedState(partial_repaint("tk5-logon", 0), stale_reads=2),
    ]
    result, _, clock = _run(flow, states)
    assert clock.sleeps == [POLL, POLL]  # the two stale reads were "no answer yet"
    assert result.audit[2].status == "ok"
