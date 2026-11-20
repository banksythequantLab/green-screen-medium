"""Scripted reconnect into deep ``***`` pauses (more-flows task 6.10, Requirement 25).

The logon Handle on ``tso-pause`` allows 10 Enters. A reconnect into 9 further
pauses (the pause under the reconnect message plus ``pause_variant(0..8)``) is
drained and released by one call; the call after it takes the normal path. With
10 further pauses the call stops with ``loop_limit`` at step 17. The userid and
password are fake.
"""
from __future__ import annotations

import logging

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.connector_support import LogCapture, collect_record_text, forms_of_run
from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    capture,
    pause_variant,
)
from tests.screen_support import reconnect_pause_screen

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"  # fake password, 8 characters
POLL = 0.25
FLOW_NAMES = ["tk5-logon", "tk5-system-info"]
PASSWORD_FORMS = forms_of_run([ord(c) for c in SENTINEL])

ENTER = ("enter",)
CLEAR = ("clear",)
LOGOFF = [("string", "LOGOFF"), ENTER]
CALLS_TO_PASSWORD = [
    ("string", USERID),
    ENTER,
    ("string", "LOGON "),
    ("string", USERID),
    ("string", " RECONNECT"),
    ENTER,
    ("string", SENTINEL),
    ENTER,
]


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


def _reconnect_states(stale, further, *tail):
    screens = [
        capture("tk5-logon"),
        capture("tso-userid-in-use"),
        capture("tso-reconnect-password-prompt"),
        capture("tso-reconnect-ok"),
        reconnect_pause_screen(),
        *[pause_variant(i) for i in range(further)],
        *tail,
    ]
    return [ScriptedState(s, stale_reads=stale) for s in screens]


def _run(flow_name, states, inputs=None):
    flow = load_bundled_flows()[flow_name]
    session = ScriptedSession(states, echo_typing=True)
    try:
        result = run_flow(
            flow,
            session,
            inputs or {"userid": USERID, "password": SENTINEL},
            clock=FakeClock(),
            poll_interval=POLL,
        )
        return result, None, session
    except FlowError as exc:
        return None, exc, session


def _keys(session):
    return [c for c in session.calls if c[0] != "read"]


def _final_name(session):
    last = None
    for _ in range(3):  # drain stale copies queued behind the last screen
        last = session.read_screen()
    return recognize(last, load_bundled_signatures())


def _leaks(result, error, records) -> bool:
    texts: list[str] = []
    if result is not None:
        texts += [repr(result), repr(result.audit)]
    if error is not None:
        texts += [str(error), repr(error), repr(error.audit)]
    for record in records:
        texts += collect_record_text(record)
    return any(form in text for text in texts for form in PASSWORD_FORMS)


def _normal_states(flow_name, stale=0):
    """The second call: a new Session that starts at the logon screen, 2 pauses."""
    states = [
        capture("tk5-logon"),
        capture("tso-password-prompt"),
        pause_variant(0),
        pause_variant(1),
        capture("ispf-primary-menu"),
    ]
    if flow_name == "tk5-system-info":
        states += [capture("tso-ready"), capture("tk5-logon")]
    return [ScriptedState(s, stale_reads=stale) for s in states]


NORMAL_KEYS = [("string", USERID), ENTER, ("string", SENTINEL), ENTER, ENTER, ENTER]
NORMAL_TAIL = {
    "tk5-logon": [],
    "tk5-system-info": [("string", "X"), ENTER, *LOGOFF],
}


# (a) and (b): 9 further pauses, released in one call, then the normal path
@pytest.mark.parametrize("stale", [0, 1, 2])
@pytest.mark.parametrize("flow_name", FLOW_NAMES)
def test_nine_further_pauses_are_drained_and_released_then_next_call_is_normal(
    flow_name, stale, log_records
):
    states = _reconnect_states(
        stale, 9, capture("tso-ready"), capture("tso-cleared"), capture("tk5-logon")
    )
    result, error, session = _run(flow_name, states)
    assert result is None
    assert error.reason == "unexpected_screen"
    assert error.step_index == 26
    assert list(error.expected) == ["ispf-primary-menu"]
    # 12 Enters from the password Enter on, then Clear, LOGOFF, Enter.
    assert _keys(session) == CALLS_TO_PASSWORD + [ENTER] * 11 + [CLEAR, *LOGOFF]
    assert _final_name(session) == "tk5-logon"
    assert _leaks(result, error, log_records) is False

    # Second call: a new Session at the logon screen.
    result2, error2, session2 = _run(flow_name, _normal_states(flow_name, stale))
    assert error2 is None
    assert _keys(session2) == NORMAL_KEYS + NORMAL_TAIL[flow_name]
    if flow_name == "tk5-logon":
        assert result2.audit[-1].signature == "ispf-primary-menu"
    else:
        assert len(result2.outputs) == 4
        assert _final_name(session2) == "tk5-logon"
    assert _leaks(result2, error2, log_records) is False


# (c): 10 further pauses exceed the Handle
@pytest.mark.parametrize("stale", [0, 1, 2])
@pytest.mark.parametrize("flow_name", FLOW_NAMES)
def test_ten_further_pauses_stop_with_loop_limit_and_send_no_key_after(
    flow_name, stale, log_records
):
    result, error, session = _run(flow_name, _reconnect_states(stale, 10))
    assert result is None
    assert error.reason == "loop_limit"
    assert error.step_index == 17
    # 12 Enters from the password Enter on; nothing follows the last Enter,
    # not even from the finally steps of tk5-system-info.
    assert _keys(session) == CALLS_TO_PASSWORD + [ENTER] * 11
    assert _leaks(result, error, log_records) is False


# (d): one pause, REENTER and cleared, give the keys of test_flow_logon_cleanup.py
@pytest.mark.parametrize("flow_name", FLOW_NAMES)
def test_one_pause_then_cleared_keeps_the_cleanup_keys(flow_name):
    states = _reconnect_states(0, 1, capture("tso-cleared"), capture("tk5-logon"))
    _, error, session = _run(flow_name, states)
    assert error.reason == "unexpected_screen" and error.step_index == 26
    assert _keys(session) == CALLS_TO_PASSWORD + [ENTER] * 3 + LOGOFF


@pytest.mark.parametrize("flow_name", FLOW_NAMES)
def test_one_pause_then_reenter_keeps_the_cleanup_keys(flow_name):
    states = _reconnect_states(
        0,
        1,
        capture("tso-listds-reenter"),
        capture("tso-listds-reenter-after-pa1"),
        capture("tso-cleared"),
        capture("tk5-logon"),
    )
    _, error, session = _run(flow_name, states)
    assert error.reason == "unexpected_screen" and error.step_index == 26
    assert _keys(session) == CALLS_TO_PASSWORD + [ENTER] * 3 + [("pa", 1), CLEAR, *LOGOFF]
    assert _final_name(session) == "tk5-logon"
