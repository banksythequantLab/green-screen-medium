"""Finally steps at each stop of the five Command_Flows (more-flows, task 8.9).

Each Flow is stopped while the run holds a screen (the ISPF menu, ``READY``
after ``X``, the cleared screen, a ``***`` pause, the output screen, the
cleared screen before ``LOGOFF``) and the finally steps must end on
``tk5-logon`` with the calls the design lists. Where the shipped Flow has no
way to stop at a screen, the test inserts one ``expect`` step (the Flow is a
``dataclasses.replace`` copy; the shipped file is not touched).

Screens come from the captures and from ``tests.flow_support``; user id and
password are fake values.
"""
from __future__ import annotations

import dataclasses

import pytest

from greenscreen.connector.models import SFToken
from greenscreen.flow import runner
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import CollectStep, ExpectStep, Flow
from greenscreen.flow.runner import run_flow

from tests.command_flow_support import (
    INPUTS,
    POLL,
    SENTINEL,
    closing_states,
    command_states,
    exit_states,
    keys_after_menu,
    load_shipped_flow,
    logon_keys,
    logon_states,
    keys,
)
from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    _recognized,
    capture,
    copy_screen,
    pause_variant,
)
from tests.screen_support import make_screen

ENTER = ("enter",)
CLEAR = ("clear",)
LOGOFF = [("string", "LOGOFF"), ENTER]
DSN = "SYS2.JCLLIB"

# name -> (typed keys of the command block, the screens of the normal success run)
MEMBER_PAGES = ["tso-listds-members"] + [f"tso-listds-members-page{i}" for i in range(2, 8)]
FLOWS = {
    "tk5-time": (2, ["tso-time-output"]),
    "tk5-list-datasets": (2, ["tso-listcat-output"]),
    "tk5-dataset-info": (4, ["tso-listds-output"]),
    "tk5-library-members": (4, MEMBER_PAGES),
    "tk5-job-status": (2, ["tso-status-output"]),
}
NAMES = list(FLOWS)
NEEDS_DSNAME = {"tk5-dataset-info", "tk5-library-members"}


def _inputs(name):
    return {**INPUTS, "dsname": DSN} if name in NEEDS_DSNAME else dict(INPUTS)


def _run(flow, session, name):
    return run_flow(flow, session, _inputs(name), clock=FakeClock(), poll_interval=POLL)


def _stop(name, flow, states):
    """Run to a FlowError; return (error, session)."""
    session = ScriptedSession(states, echo_typing=True)
    with pytest.raises(FlowError) as info:
        _run(flow, session, name)
    return info.value, session


def _finally_records(err):
    return [a for a in err.audit if a.phase == "finally"]


def _finally_keys_ok(err):
    return [a for a in _finally_records(err) if a.kind in ("key", "type") and a.status == "ok"]


def _assert_clean_finally(err, session, *, sent):
    fin = _finally_records(err)
    assert len(fin) == 13
    assert not any(a.status == "failed" for a in fin)
    assert len(_finally_keys_ok(err)) == sent
    assert _recognized(session.read_screen()) == "tk5-logon"
    assert SENTINEL not in repr(err)


def _insert_after(flow, signatures, occurrence, new_signatures):
    positions = [
        i for i, s in enumerate(flow.steps)
        if isinstance(s, ExpectStep) and s.signatures == signatures
    ]
    at = positions[occurrence]
    steps = flow.steps[: at + 1] + (ExpectStep(signatures=new_signatures),) + flow.steps[at + 1:]
    return dataclasses.replace(flow, steps=steps)


def _with_output(flow, output_name, **changes):
    outputs = tuple(
        dataclasses.replace(o, **changes) if o.name == output_name else o
        for o in flow.outputs
    )
    return dataclasses.replace(flow, outputs=outputs)


def _lines_screen(first_row, col, n):
    text = {(0, 0): "CMD"}
    text.update({(first_row + i, col): f"LINE{i}" for i in range(n)})
    text[(first_row + n, 1)] = "READY"
    return make_screen(24, 80, text, [(0, 0, 0xC8)], (first_row + n + 1, 0))


# ------------------------------------------------ stops before the command

@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize(
    "after, occurrence, wanted, main_keys, tail, sent",
    [
        # ISPF menu held: the menu Handle types X and Enter, then Clear, LOGOFF, Enter.
        (("ispf-primary-menu",), 0, ("tso-ready",), 0,
         [("string", "X"), ENTER, CLEAR, *LOGOFF], 5),
        # READY after X held: Clear, LOGOFF, Enter.
        (("tso-ready",), 0, ("tso-cleared",), 2, [CLEAR, *LOGOFF], 3),
        # Cleared screen held: LOGOFF, Enter.
        (("tso-cleared",), 0, ("tso-ready",), 3, LOGOFF, 2),
    ],
    ids=["menu", "ready", "cleared"],
)
def test_stop_before_the_command_logs_off(name, after, occurrence, wanted, main_keys, tail, sent):
    flow = _insert_after(load_shipped_flow(name), after, occurrence, wanted)
    states = logon_states() + exit_states() + command_states(["tk5-logon"])
    err, session = _stop(name, flow, states)

    assert err.reason == "unexpected_screen"
    assert err.kind == "expect"
    after_menu = keys_after_menu(session)
    assert after_menu[main_keys:] == tail
    assert keys(session)[: len(logon_keys())] == logon_keys()
    _assert_clean_finally(err, session, sent=sent)


# ------------------------------------------------------ the output screen

def _output_cases():
    # name -> (output to change, change, command screen)
    return {
        "tk5-time": ("TIME_TEXT", {}, _lines_screen(1, 1, 4)),
        "tk5-list-datasets": ("DATASETS", {"max_rows": 3}, _lines_screen(2, 1, 4)),
        "tk5-dataset-info": ("DETAILS", {"max_rows": 2}, capture("tso-listds-output")),
        "tk5-library-members": ("MEMBERS", {"max_rows": 2}, _lines_screen(7, 3, 3)),
        "tk5-job-status": ("JOBS", {"max_rows": 2}, _lines_screen(1, 1, 3)),
    }


@pytest.mark.parametrize("name", NAMES)
def test_loop_limit_on_the_output_screen_logs_off_from_ready(name):
    output, change, screen = _output_cases()[name]
    flow = _with_output(load_shipped_flow(name), output, **change)
    states = logon_states() + exit_states() + command_states([screen]) + closing_states()
    err, session = _stop(name, flow, states)

    assert err.reason == "loop_limit"
    cmd_keys, _ = FLOWS[name]
    after_menu = keys_after_menu(session)
    assert len(after_menu) == 3 + cmd_keys + 3
    assert after_menu[-3:] == [CLEAR, *LOGOFF]
    _assert_clean_finally(err, session, sent=3)


def test_hidden_output_on_the_time_screen_logs_off_from_ready():
    flow = load_shipped_flow("tk5-time")
    screen = copy_screen(capture("tso-time-output"))
    assert isinstance(screen.cell_grid[1][0], SFToken)
    screen.cell_grid[1][0] = SFToken(0xCC)  # the field of row 1 becomes hidden
    states = logon_states() + exit_states() + command_states([screen]) + closing_states()
    err, session = _stop("tk5-time", flow, states)

    assert err.reason == "hidden_output"
    assert keys_after_menu(session)[-3:] == [CLEAR, *LOGOFF]
    _assert_clean_finally(err, session, sent=3)


# ------------------------------------------------- a pause mid-listing

def test_pause_held_at_the_time_extract_drains_with_enter_first():
    flow = load_shipped_flow("tk5-time")
    states = (
        logon_states() + exit_states()
        + command_states([pause_variant(0), "tso-ready"]) + closing_states()
    )
    err, session = _stop("tk5-time", flow, states)

    assert err.reason == "unexpected_screen"
    assert err.kind == "extract"
    assert keys_after_menu(session)[5:] == [ENTER, CLEAR, *LOGOFF]
    _assert_clean_finally(err, session, sent=4)


def _limit_to_one_screen(flow):
    steps = tuple(
        dataclasses.replace(s, max_screens=1) if isinstance(s, CollectStep) else s
        for s in flow.steps
    )
    return dataclasses.replace(flow, steps=steps)


@pytest.mark.parametrize(
    "name, screens, drains",
    [
        ("tk5-list-datasets",
         ["tso-listcat-level", "tso-listcat-level-page2", "tso-listcat-level-page3"], 2),
        ("tk5-job-status", [pause_variant(0), "tso-ready"], 1),
        ("tk5-library-members", MEMBER_PAGES, 6),
    ],
)
def test_loop_limit_in_the_middle_of_a_listing_drains_pauses_then_logs_off(
    name, screens, drains
):
    flow = _limit_to_one_screen(load_shipped_flow(name))
    states = logon_states() + exit_states() + command_states(screens) + closing_states()
    err, session = _stop(name, flow, states)

    assert err.reason == "loop_limit"
    cmd_keys, _ = FLOWS[name]
    after_menu = keys_after_menu(session)
    # the collect pressed no Enter (max_screens 1); the finally steps press them all
    assert after_menu[3 + cmd_keys:] == [ENTER] * drains + [CLEAR, *LOGOFF]
    fin = _finally_records(err)
    assert not any(a.status == "failed" for a in fin)
    assert len(_finally_keys_ok(err)) == drains + 3
    assert _recognized(session.read_screen()) == "tk5-logon"
    assert SENTINEL not in repr(err)


# ----------------------------------------- the cleared screen before LOGOFF

@pytest.mark.parametrize("name", NAMES)
def test_cleared_screen_held_before_logoff_sends_logoff_and_enter(name):
    flow = _insert_after(load_shipped_flow(name), ("tso-cleared",), -1, ("tso-ready",))
    cmd_keys, screens = FLOWS[name]
    states = logon_states() + exit_states() + command_states(screens) + closing_states()
    err, session = _stop(name, flow, states)

    assert err.reason == "unexpected_screen"
    assert err.kind == "expect"
    after_menu = keys_after_menu(session)
    main = 3 + cmd_keys + (len(screens) - 1) + 1  # X, Enter, Clear, command, Enters, Clear
    assert len(after_menu) == main + 2
    assert after_menu[-3:] == [CLEAR, *LOGOFF]
    _assert_clean_finally(err, session, sent=2)


# ------------------------------------------------------------- success

@pytest.mark.parametrize("name", NAMES)
def test_success_sends_no_finally_key(name):
    flow = load_shipped_flow(name)
    cmd_keys, screens = FLOWS[name]
    states = logon_states() + exit_states() + command_states(screens) + closing_states()
    session = ScriptedSession(states, echo_typing=True)
    result = _run(flow, session, name)

    fin = [a for a in result.audit if a.phase == "finally"]
    assert len(fin) == 13
    handles = [a for a in fin if a.kind == "handle"]
    assert len(handles) == 5 and all(a.status == "ok" for a in handles)
    assert [a.kind for a in fin if a.status == "ok"].count("expect") == 1
    assert not [a for a in fin if a.kind in ("key", "type") and a.status != "skipped"]
    assert sum(a.status == "skipped" for a in fin) == 7

    calls = session.calls
    last_send = max(i for i, c in enumerate(calls) if c[0] != "read")
    assert keys(session)[-2:] == LOGOFF
    assert {c[0] for c in calls[last_send + 1:]} == {"read"}
    expected_main = len(logon_keys()) + 3 + cmd_keys + (len(screens) - 1) + 3
    assert len(keys(session)) == expected_main
    assert _recognized(session.read_screen()) == "tk5-logon"


# ---------------------------------------------------------- Finding 10

def test_finding_10_stop_on_an_unlisted_screen_skips_every_finally_step():
    """EXPECTED FAILURE of the design (Finding 10, risk R4), pinned on purpose.

    A test-only copy of ``tk5-dataset-info`` whose ``expect`` after the command
    Enter omits ``tso-reenter`` meets the REENTER screen. The runner holds no
    Current_Screen after a key, so the stop is ``unexpected_screen`` with
    ``current`` None, every finally step is ``skipped``, and no key follows the
    command Enter: the account is left at the ``REENTER -`` prompt.

    A later runner change (finally steps that run from an unlisted screen)
    makes this test fail ON PURPOSE. Then update this test and the design
    (Open decision 6, "Error Handling" table), do not revert the runner.
    """
    flow = load_shipped_flow("tk5-dataset-info")
    at = next(
        i for i, s in enumerate(flow.steps)
        if isinstance(s, ExpectStep) and "tso-reenter" in s.signatures
    )
    steps = list(flow.steps)
    steps[at] = ExpectStep(signatures=("tso-ready",))
    flow = dataclasses.replace(flow, steps=tuple(steps))
    states = (
        logon_states() + exit_states()
        + command_states(["tso-listds-reenter", "tso-listds-reenter-after-pa1"])
        + closing_states()
    )
    err, session = _stop("tk5-dataset-info", flow, states)

    assert err.reason == "unexpected_screen"
    assert err.kind == "expect"
    assert err.expected == ("tso-ready",)
    fin = _finally_records(err)
    assert len(fin) == 13 and all(a.status == "skipped" for a in fin)
    after_menu = keys_after_menu(session)
    assert after_menu[-1] == ENTER and len(after_menu) == 3 + 4  # nothing after the Enter
    assert _recognized(session.read_screen()) == "tso-reenter"
    assert SENTINEL not in repr(err)


# ------------------------------------------------------ skip reasons

def test_finally_skip_reasons_are_unchanged():
    expected = {
        "unknown_screen", "ambiguous_screen", "timeout", "run_timeout",
        "session_error", "input_invalid", "definition",
    }
    assert runner._FINALLY_SKIP_REASONS == expected
    assert runner.FINALLY_SKIP_REASONS == expected
    assert isinstance(runner._FINALLY_SKIP_REASONS, frozenset)
    assert Flow  # the import documents which model the tests copy
