"""The REENTER outcome of the two Name_Flows (more-flows task 8.10, Requirement 21).

``tk5-dataset-info`` and ``tk5-library-members`` type a data set name. When the host
rejects a name the validation let through, it shows ``REENTER -`` and waits. The
Flow stops with ``unexpected_screen`` (HTTP 502, reason code unchanged) after it
has sent PA1, Clear, ``LOGOFF`` and Enter. A name the validation rejects never
reaches the host (HTTP 422 ``input_invalid``, decision X3). Fake user id and
password; no live host.
"""
from __future__ import annotations

import json
import logging

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError, FlowInputError
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.command_flow_support import (
    INPUTS,
    POLL,
    SENTINEL,
    USERID,
    command_flow_states,
    command_session,
    keys_after_menu,
    logon_keys,
    typed_after_menu,
)
from tests.flow_support import FakeClock, ScriptedSession, partial_repaint
from tests.publisher_support import FakeHost
from tests.unit.test_publisher_calls import only_record
from tests.unit.test_publisher_rest import assert_error, make_app, post

NAME_FLOWS = ["tk5-dataset-info", "tk5-library-members"]
FIXED_FLOWS = ["tk5-time", "tk5-list-datasets", "tk5-job-status"]
GOOD_NAME = "SYS2.NOSUCH"

REENTER = "tso-listds-reenter"
AFTER_PA1 = "tso-listds-reenter-after-pa1"

# After the command Enter: PA1, Clear, LOGOFF, Enter and nothing else.
RELEASE_KEYS = [("pa", 1), ("clear",), ("string", "LOGOFF"), ("enter",)]


def _run(flow_name, session, name=GOOD_NAME):
    flow = load_bundled_flows()[flow_name]
    try:
        result = run_flow(
            flow, session, {**INPUTS, "dsname": name}, clock=FakeClock(), poll_interval=POLL
        )
        return result, None
    except FlowError as exc:
        return None, exc


def _reenter_session():
    return command_session([REENTER, AFTER_PA1])


def _final_name(session):
    return recognize(session.read_screen(), load_bundled_signatures())


@pytest.fixture(autouse=True)
def _info_log(caplog):
    caplog.set_level(logging.INFO, logger="greenscreen.publisher")


# --------------------------------------------------------------------------
# Flow level
# --------------------------------------------------------------------------

@pytest.mark.parametrize("flow_name", NAME_FLOWS)
def test_reenter_ends_logged_off_with_unexpected_screen(flow_name):
    session = _reenter_session()
    result, error = _run(flow_name, session)
    assert result is None
    assert error.reason == "unexpected_screen"
    assert error.step_index == 37
    assert error.kind in {"extract", "collect"}
    assert "tso-ready" in error.expected and "tso-reenter" not in error.expected
    assert _final_name(session) == "tk5-logon"

    after_command = keys_after_menu(session)
    # X, Enter, Clear, then LISTDS ' + name + closer, Enter; then the release keys.
    command_enter = after_command.index(("enter",), 3)
    assert after_command[command_enter + 1:] == RELEASE_KEYS
    typed = typed_after_menu(session)
    assert typed.count(GOOD_NAME) == 1
    after = after_command[command_enter + 1:]
    assert [c[1] for c in after if c[0] == "string"] == ["LOGOFF"]
    finals = [r for r in error.audit if r.phase == "finally"]
    assert finals and all(r.status in {"ok", "skipped"} for r in finals)
    assert [r.status for r in finals if r.status == "ok"]
    assert all(r.status == "ok" for r in finals if r.kind == "expect")
    assert finals[-1].kind == "expect" and finals[-1].signature == "tk5-logon"
    assert GOOD_NAME not in str(error) and GOOD_NAME not in repr(error.audit)


@pytest.mark.parametrize("flow_name", NAME_FLOWS)
def test_logon_keys_precede_the_command(flow_name):
    session = _reenter_session()
    _run(flow_name, session)
    start = [c for c in session.calls if c[0] != "read"]
    assert start[: len(logon_keys())] == logon_keys()


@pytest.mark.parametrize("distinct", [True, False])
@pytest.mark.parametrize("flow_name", NAME_FLOWS)
def test_repeated_reenter_sends_at_most_three_pa1(flow_name, distinct):
    # Distinct repeats are REENTER screens that differ in a cell (the host's echo of
    # the new operand). Identical repeats look like "no answer yet" to the runner, so
    # the finally Handle waits for a change, runs out of `finally` time and stops
    # after one PA1. Both ways end with the main stop and a failed finally step.
    repeats = [partial_repaint(REENTER, i) if distinct else REENTER for i in range(6)]
    states = command_flow_states([REENTER, *repeats])
    session = ScriptedSession(states, echo_typing=True)
    result, error = _run(flow_name, session)
    assert result is None
    assert error.reason == "unexpected_screen"
    sent = [c for c in session.calls if c == ("pa", 1)]
    assert len(sent) <= 3
    if distinct:
        assert len(sent) == 3
    failed = [r for r in error.audit if r.status == "failed"]
    assert {r.phase for r in failed} == {"steps", "finally"}
    assert GOOD_NAME not in str(error) and GOOD_NAME not in repr(error.audit)


@pytest.mark.parametrize("flow_name", NAME_FLOWS)
def test_rejected_name_never_reaches_the_host(flow_name):
    session = _reenter_session()
    flow = load_bundled_flows()[flow_name]
    with pytest.raises(FlowInputError) as info:
        run_flow(
            flow, session, {**INPUTS, "dsname": "A..B"}, clock=FakeClock(), poll_interval=POLL
        )
    assert info.value.reason == "input_invalid"
    assert session.calls == []
    assert "A..B" not in str(info.value)


@pytest.mark.parametrize("flow_name", FIXED_FLOWS)
def test_fixed_literal_flows_do_not_list_tso_reenter_in_an_expect(flow_name):
    flow = load_bundled_flows()[flow_name]
    for step in flow.steps:
        if step.kind in {"expect"}:
            assert "tso-reenter" not in step.signatures
    for output in flow.outputs:
        assert output.signature != "tso-reenter"


# --------------------------------------------------------------------------
# Publisher path
# --------------------------------------------------------------------------

def _body(name):
    return json.dumps({"userid": USERID, "password": SENTINEL, "dsname": name})


@pytest.mark.parametrize("flow_name", NAME_FLOWS)
def test_publisher_answers_502_unexpected_screen_without_session_clean(flow_name, caplog):
    host = FakeHost(command_flow_states([REENTER, AFTER_PA1]))
    app = make_app(host, {flow_name: load_bundled_flows()[flow_name]})
    resp = post(app, _body(GOOD_NAME), name=flow_name)
    assert_error(resp, 502, "unexpected_screen")
    assert resp.json()["error"]["step_index"] == 37
    assert GOOD_NAME not in resp.text and SENTINEL not in resp.text
    record = only_record(caplog)
    assert record["outcome"] == "unexpected_screen"
    assert "session_clean" not in record
    assert host.created == 1 and host.closed == 1


@pytest.mark.parametrize("flow_name", NAME_FLOWS)
def test_publisher_answers_422_for_a_rejected_name_and_never_calls_the_host(flow_name):
    calls = []

    def factory():
        calls.append(1)
        raise AssertionError("the host factory must not be called")

    app = make_app(factory, {flow_name: load_bundled_flows()[flow_name]})
    resp = post(app, _body("A..B"), name=flow_name)
    assert_error(resp, 422, "input_invalid")
    assert "A..B" not in resp.text and SENTINEL not in resp.text
    assert calls == []
