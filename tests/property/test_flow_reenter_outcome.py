# Feature: more-flows, Property 9: A name the host rejects always ends logged off
"""Property 9 of the more-flows spec: the REENTER outcome (task 8.10).

For any name the Dsn_Rule accepts, each Name_Flow, and a script that answers the
command with the REENTER capture, the run ends with ``unexpected_screen``, the keys
after the command Enter are PA1, Clear, ``LOGOFF``, Enter, the last screen is
``tk5-logon``, and the name occurs in no message or audit field. Fake user id and
password.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.command_flow_support import INPUTS, POLL, command_flow_states, keys_after_menu
from tests.dsname_support import valid_names
from tests.flow_support import FakeClock, ScriptedSession

NAME_FLOWS = ("tk5-dataset-info", "tk5-library-members")
RELEASE_KEYS = [("pa", 1), ("clear",), ("string", "LOGOFF"), ("enter",)]
SIGNATURES = load_bundled_signatures()
REFERENCE_NAME = "SYS2.NOSUCH"


def _fields(error):
    return (
        str(error), error.reason, error.step_index, error.kind, error.expected,
        repr(error.summary), repr(error.audit),
    )


def _error_fields(flow_name, name, stale):
    states = command_flow_states(
        ["tso-listds-reenter", "tso-listds-reenter-after-pa1"], stale=stale
    )
    session = ScriptedSession(states, echo_typing=True)
    try:
        run_flow(
            load_bundled_flows()[flow_name], session, {**INPUTS, "dsname": name},
            clock=FakeClock(), poll_interval=POLL,
        )
    except FlowError as exc:
        return _fields(exc)
    raise AssertionError("the reference run did not stop")


@settings(max_examples=200, deadline=None)
@given(
    flow_name=st.sampled_from(NAME_FLOWS),
    name=valid_names(),
    stale=st.integers(min_value=0, max_value=2),
)
def test_a_name_the_host_rejects_always_ends_logged_off(flow_name, name, stale):
    """**Validates: Requirements 8.3, 13.6, 21.2, 21.3, 21.4, 21.5, 21.6**"""
    states = command_flow_states(
        ["tso-listds-reenter", "tso-listds-reenter-after-pa1"], stale=stale
    )
    session = ScriptedSession(states, echo_typing=True)
    flow = load_bundled_flows()[flow_name]

    result, error = None, None
    try:
        result = run_flow(
            flow,
            session,
            {**INPUTS, "dsname": name},
            clock=FakeClock(),
            poll_interval=POLL,
        )
    except FlowError as exc:
        error = exc

    assert result is None
    assert error is not None and error.reason == "unexpected_screen"

    keys = keys_after_menu(session)
    command_enter = keys.index(("enter",), 3)  # after X, Enter, Clear
    assert keys[command_enter + 1:] == RELEASE_KEYS

    last = None
    for _ in range(4):  # drain stale copies queued behind the last screen
        last = session.read_screen()
    assert recognize(last, SIGNATURES) == "tk5-logon"

    # A short name such as "e" is a substring of any message, so "the name occurs in
    # no field" is checked as: every message and audit field is identical to the
    # fields of a run with a reference name (durations come from FakeClock).
    reference = _error_fields(flow_name, REFERENCE_NAME, stale)
    assert _fields(error) == reference
