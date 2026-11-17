"""Skipped records of Unmatched_Handle Body_Steps (flow-runtime task 16.1).

Covers Requirements 13.10 to 13.14, 15.7 and 14.8.
"""
from __future__ import annotations

import pytest

from greenscreen.flow import load_bundled_flows
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import (
    ExpectStep,
    Flow,
    HandleStep,
    KeyStep,
    TypeStep,
    plan,
)
from greenscreen.flow.runner import run_flow

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    capture,
    partial_repaint,
)


def _run(flow, states, inputs=None, *, echo=False):
    session = ScriptedSession(states, echo_typing=echo)
    return run_flow(flow, session, inputs or {}, clock=FakeClock()), session


def _run_failing(flow, states):
    session = ScriptedSession(states)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=FakeClock())
    return info.value, session


def _rows(audit):
    return [(r.step_index, r.status, r.iteration) for r in audit]


def _assert_skipped(record, index, kind, phase):
    assert record.step_index == index
    assert record.kind == kind
    assert record.phase == phase
    assert record.status == "skipped"
    assert record.duration_seconds == 0.0
    assert record.iteration is None
    assert record.signature is None


def _no_duplicates(audit):
    pairs = [(r.step_index, r.iteration) for r in audit]
    assert len(pairs) == len(set(pairs))


LOGON = ExpectStep(("tk5-logon",))
UNMATCHED = HandleStep("tk5-logo", 1, (TypeStep(text="X"), KeyStep("enter")))
WRONG = ExpectStep(("ispf-primary-menu",))  # fails on the logon screen


# --------------------------------------------------------------------------
# Unmatched_Handle in steps
# --------------------------------------------------------------------------

def test_steps_unmatched_handle_on_returning_run():
    flow = Flow("t", (LOGON, UNMATCHED))
    result, session = _run(flow, [capture("tk5-logon")])
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "ok", None), (2, "skipped", None), (3, "skipped", None),
    ]
    _assert_skipped(result.audit[2], 2, "type", "steps")
    _assert_skipped(result.audit[3], 3, "key", "steps")
    assert result.audit[1].status == "ok"
    assert not [c for c in session.calls if c[0] != "read"]


def test_steps_unmatched_handle_on_failing_run_and_later_step_has_no_record():
    flow = Flow("t", (LOGON, UNMATCHED, WRONG, ExpectStep(("tk5-logon",))))
    err, _ = _run_failing(flow, [capture("tk5-logon")])
    assert err.reason == "unexpected_screen"
    assert _rows(err.audit) == [
        (0, "ok", None), (1, "ok", None), (2, "skipped", None), (3, "skipped", None),
        (4, "failed", None),
    ]  # Step 5 never began: no record (Requirement 14.8)
    _no_duplicates(err.audit)


# --------------------------------------------------------------------------
# Unmatched_Handle in finally
# --------------------------------------------------------------------------

def test_finally_unmatched_handle_on_returning_run():
    flow = Flow("t", (LOGON,), finally_steps=(UNMATCHED,))
    result, session = _run(flow, [capture("tk5-logon")])
    assert _rows(result.audit) == [
        (0, "ok", None), (1, "ok", None), (2, "skipped", None), (3, "skipped", None),
    ]
    assert all(r.phase == "finally" for r in result.audit[1:])
    _assert_skipped(result.audit[2], 2, "type", "finally")
    _assert_skipped(result.audit[3], 3, "key", "finally")
    assert not [c for c in session.calls if c[0] != "read"]


def test_finally_unmatched_handle_on_failing_run():
    flow = Flow("t", (LOGON, WRONG), finally_steps=(UNMATCHED,))
    err, _ = _run_failing(flow, [capture("tk5-logon")])
    assert err.reason == "unexpected_screen"
    assert _rows(err.audit) == [
        (0, "ok", None), (1, "failed", None),
        (2, "ok", None), (3, "skipped", None), (4, "skipped", None),
    ]
    _no_duplicates(err.audit)


# --------------------------------------------------------------------------
# Matched handles add nothing
# --------------------------------------------------------------------------

def test_matched_handle_has_iteration_records_and_no_skipped():
    handle = HandleStep("tk5-logon", 2, (KeyStep("enter"),))
    flow = Flow("t", (handle, WRONG))
    result, _ = _run(flow, [capture("tk5-logon"), capture("ispf-primary-menu")])
    assert _rows(result.audit) == [(0, "ok", None), (1, "ok", 1), (2, "ok", None)]


def test_loop_limit_keeps_iteration_records_and_adds_no_skipped():
    handle = HandleStep("tk5-logon", 1, (KeyStep("enter"),))
    flow = Flow("t", (handle,))
    err, _ = _run_failing(
        flow, [capture("tk5-logon"), partial_repaint("tk5-logon", 0)]
    )
    assert err.reason == "loop_limit"
    assert _rows(err.audit) == [(0, "failed", None), (1, "ok", 1)]


# --------------------------------------------------------------------------
# _skip_finally does not duplicate
# --------------------------------------------------------------------------

def test_skip_finally_adds_no_duplicate_after_body_failure():
    handle = HandleStep(
        "tk5-logo", 1, (TypeStep(text="X"), KeyStep("enter")),
    )
    flow = Flow(
        "t", (ExpectStep(("tk5-logo",)),),
        finally_steps=(handle, ExpectStep(("tk5-logo",))),
    )
    err, _ = _run_failing(flow, [capture("tk5-logo")])
    assert err.reason == "bad_target"
    assert _rows(err.audit) == [
        (0, "ok", None),
        (1, "failed", None),
        (2, "failed", 1),
        (3, "skipped", None),
        (4, "skipped", None),
    ]
    _assert_skipped(err.audit[3], 3, "key", "finally")
    _no_duplicates(err.audit)


# --------------------------------------------------------------------------
# Real bundled flows on captures
# --------------------------------------------------------------------------

_INPUTS = {"userid": "TESTUSER", "password": "TESTPW"}


def test_bundled_tk5_logon_skips_logo_inr_and_pause_bodies():
    flow = load_bundled_flows()["tk5-logon"]
    states = [
        capture("tk5-logon"),
        capture("tso-password-prompt"),
        capture("ispf-primary-menu"),
    ]
    result, _ = _run(flow, states, _INPUTS, echo=True)
    main, _ = plan(flow)
    by_index = {r.step_index: r for r in result.audit}
    for item in (main[0], main[1], main[8]):
        assert by_index[item.index].status == "ok"
        for child in item.children:
            _assert_skipped(by_index[child.index], child.index, "key", "steps")
    assert (by_index[1].status, by_index[3].status) == ("skipped", "skipped")
    _no_duplicates(result.audit)
    positions = [r.step_index for r in result.audit]
    assert positions == sorted(positions)


def test_bundled_tk5_system_info_skips_main_and_finally_bodies():
    flow = load_bundled_flows()["tk5-system-info"]
    states = [
        capture("tk5-logon"),
        capture("tso-password-prompt"),
        capture("ispf-primary-menu"),
        capture("tso-ready"),
        capture("tk5-logon"),
    ]
    result, _ = _run(flow, states, _INPUTS, echo=True)
    main, fin = plan(flow)
    by_index = {r.step_index: r for r in result.audit}
    _no_duplicates(result.audit)
    assert by_index[1].status == "skipped" and by_index[3].status == "skipped"
    unmatched = [main[0], main[1], main[8], *[i for i in fin if i.children]]
    for item in unmatched:
        assert by_index[item.index].status == "ok"
        for child in item.children:
            _assert_skipped(
                by_index[child.index], child.index, child.step.kind, item.phase
            )

    def walk(items):
        for item in items:
            yield item
            yield from walk(item.children)

    for item in walk(fin):
        assert item.index in by_index, f"finally Step {item.index} has no record"
