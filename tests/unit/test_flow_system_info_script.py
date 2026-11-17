"""Scripted run of the bundled ``tk5-system-info`` flow (flow-runtime task 10.15).

Covers Requirements 17.11, 17.12, 17.15 and 17.16. Screens come from the
captures; the userid and password are obviously fake values.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExtractStep
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    capture,
    pause_variant,
)
from tests.screen_support import load_capture_screen

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"  # fake password, 8 characters
POLL = 0.25

OUTPUT_ORDER = ["USERID", "TERMINAL", "RELEASE", "SYSTEMID"]
REGIONS = {  # name -> (row, col, length), as in the flow definition
    "USERID": (2, 71, 8),
    "SYSTEMID": (12, 71, 8),
    "RELEASE": (10, 71, 8),
    "TERMINAL": (4, 71, 8),
}


def _states(*, fail_at_key: bool = False):
    # With fail_at_key the reads after the menu are three plain menu repaints
    # and then READY, so the pre-key read of the Enter after `X` differs from
    # the Current_Screen: unexpected_screen with the menu held, after the four
    # Extract_Steps. The Finally_Steps then log off.
    repaints = ()
    if fail_at_key:
        repaints = (
            capture("ispf-primary-menu"),
            capture("ispf-primary-menu"),
            capture("ispf-primary-menu"),
            capture("tso-ready"),
        )
    return [
        ScriptedState(capture("tk5-logo")),
        ScriptedState(capture("tk5-logon")),
        ScriptedState(capture("tso-password-prompt")),
        ScriptedState(pause_variant(0)),
        ScriptedState(pause_variant(1)),
        ScriptedState(capture("ispf-primary-menu"), repaints=repaints),
        ScriptedState(capture("tso-ready")),
        ScriptedState(capture("tk5-logon")),
    ]


def _run(*, fail_at_key: bool = False):
    flow = load_bundled_flows()["tk5-system-info"]
    session = ScriptedSession(_states(fail_at_key=fail_at_key), echo_typing=True)
    inputs = {"userid": USERID, "password": SENTINEL}
    try:
        result = run_flow(flow, session, inputs, clock=FakeClock(), poll_interval=POLL)
        error = None
    except FlowError as exc:
        result, error = None, exc
    return flow, session, result, error


def _keys(session):
    return [c for c in session.calls if c[0] != "read"]


def test_outputs_equal_capture_text_at_each_region():
    _, _, result, error = _run()
    assert error is None
    menu = load_capture_screen("ispf-primary-menu")
    assert set(result.outputs) == set(REGIONS)
    assert len(result.outputs) == 4
    for name, (row, col, length) in REGIONS.items():
        expected = menu.text_at(row, col, length).strip()
        assert expected != ""
        assert result.outputs[name] == expected


def test_key_sequence_and_final_screen_is_logon():
    _, session, result, error = _run()
    assert error is None
    assert _keys(session) == [
        ("enter",),
        ("string", USERID),
        ("enter",),
        ("string", SENTINEL),
        ("enter",),
        ("enter",),
        ("enter",),
        ("string", "X"),
        ("enter",),
        ("string", "LOGOFF"),
        ("enter",),
    ]
    final = session.read_screen()
    assert recognize(final, load_bundled_signatures()) == "tk5-logon"
    assert result.audit[-1].status == "ok"
    assert result.audit[-1].signature == "tk5-logon"


def test_audit_holds_the_four_extract_steps_in_order():
    flow, _, result, error = _run()
    assert error is None
    names = [s.output for s in flow.steps if isinstance(s, ExtractStep)]
    assert names == OUTPUT_ORDER
    records = [r for r in result.audit if r.kind == "extract"]
    assert len(records) == 4
    # Step_Index counts handle bodies, so check order and adjacency only.
    indexes = [r.step_index for r in records]
    assert indexes == list(range(indexes[0], indexes[0] + 4))
    assert all(r.phase == "steps" and r.status == "ok" for r in records)
    assert all(r.signature == "ispf-primary-menu" for r in records)


def test_secret_absent_from_result_text():
    _, _, result, _ = _run()
    assert SENTINEL not in repr(result)
    assert SENTINEL not in repr(result.audit)


def test_failure_after_extracts_runs_finally_steps_that_log_off():
    flow, session, result, error = _run(fail_at_key=True)
    assert result is None
    assert error is not None
    assert error.reason == "unexpected_screen"
    assert error.kind == "key"
    # Main run typed X and stopped before its Enter; the Finally_Steps then
    # typed X, Enter, LOGOFF, Enter.
    assert _keys(session)[-5:] == [
        ("string", "X"),
        ("string", "X"),
        ("enter",),
        ("string", "LOGOFF"),
        ("enter",),
    ]
    final = session.read_screen()
    assert recognize(final, load_bundled_signatures()) == "tk5-logon"
    extracts = [r for r in error.audit if r.kind == "extract" and r.phase == "steps"]
    assert len(extracts) == 4
    assert all(r.status == "ok" for r in extracts)
    finals = [r for r in error.audit if r.phase == "finally"]
    # Three Finally_Steps plus their handle bodies (2 + 2 + 0 records).
    assert [r.kind for r in finals if r.kind in ("handle", "expect")] == [
        "handle", "handle", "expect"
    ]
    assert finals[-1].kind == "expect" and finals[-1].status == "ok"
    assert all(r.status == "ok" for r in finals)
    assert SENTINEL not in repr(error) and SENTINEL not in repr(error.audit)
