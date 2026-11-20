"""Scripted logon landings after a reconnect (more-flows task 6.2, Requirement 22).

The account was left logged on, so the host answers the user id with
``IN USE``; the flow reconnects. The reconnected session then shows one of
several landings. The menu is the normal result. ``READY``, the cleared screen
and a ``REENTER -`` prompt are released (the flow logs off) and the call stops
with ``unexpected_screen`` at step 26. Screens come from the captures and the
synthetic builders. The userid and password are fake.
"""
from __future__ import annotations

import dataclasses
import logging
from importlib import resources

import pytest

from greenscreen.flow.bundled import load_bundled_flows
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
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.connector_support import LogCapture, collect_record_text, forms_of_run
from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    blank_screen,
    capture,
    pause_variant,
)
from tests.screen_support import reconnect_pause_screen

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"  # fake password, 8 characters
POLL = 0.25
FLOW_NAMES = ["tk5-logon", "tk5-system-info"]

PASSWORD_FORMS = forms_of_run([ord(c) for c in SENTINEL])

CALLS_TO_PASSWORD = [
    ("string", USERID),
    ("enter",),
    ("string", "LOGON "),
    ("string", USERID),
    ("string", " RECONNECT"),
    ("enter",),
    ("string", SENTINEL),
    ("enter",),
]
ENTER = ("enter",)
CLEAR = ("clear",)
PA1 = ("pa", 1)
LOGOFF = [("string", "LOGOFF"), ENTER]


@pytest.fixture
def log_records():
    handler = LogCapture(logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def _base(stale=0):
    """Screens up to and including the pause under the reconnect message."""
    return [
        ScriptedState(capture("tk5-logon")),
        ScriptedState(capture("tso-userid-in-use")),
        ScriptedState(capture("tso-reconnect-password-prompt")),
        ScriptedState(capture("tso-reconnect-ok"), stale_reads=stale),
        ScriptedState(reconnect_pause_screen(), stale_reads=stale),
    ]


def _then(stale, *screens):
    return _base(stale) + [ScriptedState(s, stale_reads=stale) for s in screens]


def _logon():
    return capture("tk5-logon")


def _landing_states(landing, stale=0):
    """The scripted states of one landing row (for ``tk5-logon``)."""
    if landing == "menu":
        return _then(stale, capture("ispf-primary-menu"))
    if landing == "ready":
        return _then(stale, capture("tso-ready"), capture("tso-cleared"), _logon())
    if landing == "cleared":
        return _then(stale, capture("tso-cleared"), _logon())
    if landing == "reenter":
        return _then(
            stale,
            capture("tso-listds-reenter"),
            capture("tso-listds-reenter-after-pa1"),
            capture("tso-cleared"),
            _logon(),
        )
    if landing == "pause_then_ready":
        return _then(
            stale, pause_variant(0), capture("tso-ready"), capture("tso-cleared"), _logon()
        )
    if landing == "ten_pauses":
        return _then(stale, *[pause_variant(i) for i in range(10)])
    if landing == "unknown":
        return _then(stale, blank_screen())
    raise AssertionError(landing)


# landing -> (keys after the password Enter, reason, step_index)
EXPECTED = {
    "menu": ([ENTER, ENTER], None, None),
    "ready": ([ENTER, ENTER, CLEAR, *LOGOFF], "unexpected_screen", 26),
    "cleared": ([ENTER, ENTER, *LOGOFF], "unexpected_screen", 26),
    "reenter": ([ENTER, ENTER, PA1, CLEAR, *LOGOFF], "unexpected_screen", 26),
    "pause_then_ready": ([ENTER, ENTER, ENTER, CLEAR, *LOGOFF], "unexpected_screen", 26),
    "ten_pauses": ([ENTER] * 11, "loop_limit", 17),
    "unknown": ([ENTER, ENTER], "unknown_screen", 17),
}


def _states_for(flow_name, landing, stale=0):
    states = _landing_states(landing, stale)
    if flow_name == "tk5-system-info" and landing == "menu":
        states += [
            ScriptedState(capture("tso-ready"), stale_reads=stale),
            ScriptedState(_logon(), stale_reads=stale),
        ]
    return states


def _run(flow, states):
    session = ScriptedSession(states, echo_typing=True)
    try:
        result = run_flow(
            flow,
            session,
            {"userid": USERID, "password": SENTINEL},
            clock=FakeClock(),
            poll_interval=POLL,
        )
        return result, None, session
    except FlowError as exc:
        return None, exc, session


def _keys(session):
    return [c for c in session.calls if c[0] != "read"]


def _leak_verdict(result, error, records) -> bool:
    """True when the password occurs in any output form. Booleans only."""
    texts: list[str] = []
    if result is not None:
        texts += [repr(result), repr(result.audit)]
    if error is not None:
        texts += [str(error), repr(error), repr(error.audit)]
    for record in records:
        texts += collect_record_text(record)
    return any(form in text for text in texts for form in PASSWORD_FORMS)


def _final_name(session):
    return recognize(session.read_screen(), load_bundled_signatures())


# --------------------------------------------------------------------------
# One scripted run per landing row, for each Flow
# --------------------------------------------------------------------------

@pytest.mark.parametrize("landing", list(EXPECTED))
@pytest.mark.parametrize("flow_name", FLOW_NAMES)
def test_landing_row(flow_name, landing, log_records):
    flow = load_bundled_flows()[flow_name]
    result, error, session = _run(flow, _states_for(flow_name, landing))
    after_password, reason, step_index = EXPECTED[landing]
    if reason is not None:
        assert _keys(session) == CALLS_TO_PASSWORD + after_password
    if reason is None:
        assert error is None
        assert result.audit[-1].status == "ok"
        if flow_name == "tk5-logon":
            assert result.audit[-1].signature == "ispf-primary-menu"
            assert _final_name(session) == "ispf-primary-menu"
        else:
            assert len(result.outputs) == 4
            assert _final_name(session) == "tk5-logon"
        # No key follows the last Enter of the logon on the menu path.
        assert (
            _keys(session)
            == CALLS_TO_PASSWORD + [ENTER, ENTER]
            + ([("string", "X"), ENTER, ("string", "LOGOFF"), ENTER]
               if flow_name == "tk5-system-info" else [])
        )
    else:
        assert result is None
        assert error.reason == reason
        assert error.step_index == step_index
        if reason == "unexpected_screen":
            assert list(error.expected) == ["ispf-primary-menu"]
            assert _final_name(session) == "tk5-logon"
    assert _leak_verdict(result, error, log_records) is False


@pytest.mark.parametrize("landing", ["ready", "cleared", "reenter", "pause_then_ready"])
def test_system_info_finally_does_nothing_after_a_released_landing(landing):
    flow = load_bundled_flows()["tk5-system-info"]
    _, error, session = _run(flow, _states_for("tk5-system-info", landing))
    assert error.reason == "unexpected_screen"
    finals = [r for r in error.audit if r.phase == "finally"]
    assert sum(1 for r in finals if r.status == "ok") == 3
    assert sum(1 for r in finals if r.status == "skipped") == 4
    assert _keys(session) == CALLS_TO_PASSWORD + EXPECTED[landing][0]


@pytest.mark.parametrize("landing", ["ready", "cleared", "reenter", "pause_then_ready"])
def test_released_landing_sends_no_key_after_the_logoff(landing):
    flow = load_bundled_flows()["tk5-logon"]
    _, error, session = _run(flow, _states_for("tk5-logon", landing))
    assert error is not None
    assert _keys(session)[-2:] == LOGOFF


@pytest.mark.parametrize("stale", [0, 1, 2])
@pytest.mark.parametrize("landing", ["ready", "cleared", "reenter"])
def test_released_landing_with_stale_reads(landing, stale):
    flow = load_bundled_flows()["tk5-logon"]
    _, error, session = _run(flow, _landing_states(landing, stale))
    assert error.reason == "unexpected_screen" and error.step_index == 26
    assert _keys(session) == CALLS_TO_PASSWORD + EXPECTED[landing][0]
    assert _final_name(session) == "tk5-logon"


# --------------------------------------------------------------------------
# tk5-system-info: its finally Handles do nothing after a released landing
# --------------------------------------------------------------------------

def test_system_info_finally_handles_run_zero_iterations_on_the_normal_path():
    flow = load_bundled_flows()["tk5-system-info"]
    result, error, session = _run(flow, _states_for("tk5-system-info", "menu"))
    assert error is None
    finals = [r for r in result.audit if r.phase == "finally"]
    assert [(r.kind, r.status) for r in finals if r.status == "ok"] == [
        ("handle", "ok"), ("handle", "ok"), ("expect", "ok"),
    ]
    assert sum(1 for r in finals if r.status == "skipped") == 4
    assert [c for c in _keys(session)][-4:] == [
        ("string", "X"), ENTER, ("string", "LOGOFF"), ENTER,
    ]


# --------------------------------------------------------------------------
# Plan indices and shipped text
# --------------------------------------------------------------------------

def _describe(item):
    step = item.step
    if isinstance(step, HandleStep):
        return (item.index, "handle", step.signature, step.max_count)
    if isinstance(step, KeyStep):
        return (item.index, "key", step.key, step.n)
    if isinstance(step, TypeStep):
        return (item.index, "type", step.text or step.input, None)
    assert isinstance(step, ExpectStep)
    return (item.index, "expect", step.signatures, None)


def _flat(items):
    out = []
    for item in items:
        out.append(item)
        out.extend(_flat(item.children))
    return out


LOGON_TAIL = [
    (17, "handle", "tso-pause", 10),
    (18, "key", "enter", None),
    (19, "handle", "tso-reenter", 3),
    (20, "key", "pa", 1),
    (21, "handle", "tso-ready", 1),
    (22, "key", "clear", None),
    (23, "handle", "tso-cleared", 1),
    (24, "type", "LOGOFF", None),
    (25, "key", "enter", None),
    (26, "expect", ("ispf-primary-menu",), None),
]


@pytest.mark.parametrize("flow_name", FLOW_NAMES)
def test_plan_indices_17_to_26(flow_name):
    flow = load_bundled_flows()[flow_name]
    main, _ = plan(flow)
    described = [_describe(i) for i in _flat(main) if 17 <= i.index <= 26]
    assert described == LOGON_TAIL


def test_system_info_own_steps_start_at_27_and_finally_stays_at_38_to_44():
    flow = load_bundled_flows()["tk5-system-info"]
    main, fin = plan(flow)
    flat = _flat(main)
    assert [(i.index, i.step.kind) for i in flat if i.index >= 27] == [
        (27, "extract"), (28, "extract"), (29, "extract"), (30, "extract"),
        (31, "expect"), (32, "type"), (33, "key"), (34, "expect"),
        (35, "type"), (36, "key"), (37, "expect"),
    ]
    assert [i.index for i in _flat(fin)] == list(range(38, 45))


@pytest.mark.parametrize("name", FLOW_NAMES)
def test_shipped_yaml_equals_to_yaml(name):
    text = (
        resources.files("greenscreen.flow.flows")
        .joinpath(f"{name}.yaml")
        .read_text(encoding="utf-8")
    )
    flow = load_bundled_flows()[name]
    assert flow.to_yaml() == text
    assert Flow.from_yaml(flow.to_yaml()) == flow


# --------------------------------------------------------------------------
# The normal path is unchanged by the three new Handles
# --------------------------------------------------------------------------

_NEW_HANDLES = ("tso-reenter", "tso-ready", "tso-cleared")


def _without_new_handles(flow):
    kept = tuple(
        s for s in flow.steps
        if not (isinstance(s, HandleStep) and s.signature in _NEW_HANDLES)
    )
    assert len(kept) == len(flow.steps) - 3
    return dataclasses.replace(flow, steps=kept)


def _normal_states(flow_name, pauses, stale):
    states = [
        ScriptedState(capture("tk5-logon")),
        ScriptedState(capture("tso-password-prompt"), stale_reads=stale),
    ]
    states += [ScriptedState(pause_variant(i), stale_reads=stale) for i in range(pauses)]
    states.append(ScriptedState(capture("ispf-primary-menu"), stale_reads=stale))
    if flow_name == "tk5-system-info":
        states += [
            ScriptedState(capture("tso-ready"), stale_reads=stale),
            ScriptedState(capture("tk5-logon"), stale_reads=stale),
        ]
    return states


def _plain(records):
    return [(r.step_index, r.kind, r.phase, r.iteration, r.signature, r.status) for r in records]


@pytest.mark.parametrize("stale", [0, 1, 2])
@pytest.mark.parametrize("flow_name", FLOW_NAMES)
def test_normal_path_calls_and_audit_match_the_flow_without_the_handles(flow_name, stale):
    full = load_bundled_flows()[flow_name]
    old = _without_new_handles(full)
    inputs = {"userid": USERID, "password": SENTINEL}
    runs = []
    for flow in (full, old):
        session = ScriptedSession(_normal_states(flow_name, 2, stale), echo_typing=True)
        result = run_flow(flow, session, inputs, clock=FakeClock(), poll_interval=POLL)
        runs.append((result, session))
    (new_result, new_session), (old_result, old_session) = runs
    # Session calls, reads included, are identical.
    assert new_session.calls == old_session.calls
    new_audit, old_audit = _plain(new_result.audit), _plain(old_result.audit)
    # Indices 0 to 18 are equal; 19 to 25 are new; later records are shifted by 7.
    assert [r for r in new_audit if r[0] < 19] == [r for r in old_audit if r[0] < 19]
    added = [r for r in new_audit if 19 <= r[0] <= 25]
    assert [(r[0], r[1], r[5]) for r in added] == [
        (19, "handle", "ok"), (20, "key", "skipped"),
        (21, "handle", "ok"), (22, "key", "skipped"),
        (23, "handle", "ok"), (24, "type", "skipped"), (25, "key", "skipped"),
    ]
    # Finally records sit after the main plan, so they shift as well.
    shifted_old = [(r[0] + 7,) + r[1:] for r in old_audit if r[0] >= 19]
    assert [r for r in new_audit if r[0] >= 26] == shifted_old
    assert SENTINEL not in repr(new_result) and SENTINEL not in repr(new_result.audit)
