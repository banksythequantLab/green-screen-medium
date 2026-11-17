"""FlowResult.outputs follows declaration order (flow-runtime task 16.3).

Covers Requirement 17.20.
"""
from __future__ import annotations

import types

from greenscreen.flow import load_bundled_flows
from greenscreen.flow.model import ExpectStep, ExtractStep, Flow, OutputSpec
from greenscreen.flow.runner import run_flow

from tests.flow_support import FakeClock, ScriptedSession, capture

_INPUTS = {"userid": "TESTUSER", "password": "TESTPW"}


def test_outputs_follow_declaration_order_not_extract_order():
    outputs = (
        OutputSpec("FIRST", "str", "ispf-primary-menu", 0, 28, 4),
        OutputSpec("SECOND", "str", "ispf-primary-menu", 0, 33, 7),
        OutputSpec("THIRD", "str", "ispf-primary-menu", 1, 1, 6),
    )
    flow = Flow(
        "order-test",
        (
            ExpectStep(("ispf-primary-menu",)),
            ExtractStep("THIRD"),
            ExtractStep("FIRST"),
            ExtractStep("SECOND"),
        ),
        outputs=outputs,
    )
    result = run_flow(
        flow, ScriptedSession([capture("ispf-primary-menu")]), {}, clock=FakeClock()
    )
    assert isinstance(result.outputs, types.MappingProxyType)
    assert list(result.outputs) == ["FIRST", "SECOND", "THIRD"]
    assert result.outputs["FIRST"] == "ISPF"
    assert result.outputs["SECOND"] == "primary"
    assert result.outputs["THIRD"] == "Option"


def test_bundled_tk5_system_info_outputs_order():
    flow = load_bundled_flows()["tk5-system-info"]
    states = [
        capture("tk5-logon"),
        capture("tso-password-prompt"),
        capture("ispf-primary-menu"),
        capture("tso-ready"),
        capture("tk5-logon"),
    ]
    session = ScriptedSession(states, echo_typing=True)
    result = run_flow(flow, session, _INPUTS, clock=FakeClock())
    assert list(result.outputs) == ["USERID", "SYSTEMID", "RELEASE", "TERMINAL"]
