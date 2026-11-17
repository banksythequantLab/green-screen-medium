"""Property 6 of the flow-runtime spec: stale reads and partial repaints add no key."""
from __future__ import annotations

import dataclasses

from hypothesis import given, settings

from greenscreen.flow.runner import run_flow
from tests.flow_support import FakeClock, ScriptedSession
from tests.property import _flow_strategies as fs


def _run(script):
    session = ScriptedSession(script.states())
    result = run_flow(script.flow, session, {}, clock=FakeClock())
    return session.calls, dict(result.outputs)


# Feature: flow-runtime, Property 6: Stale reads and partial repaints add no key
@settings(max_examples=100, deadline=None)
@given(script=fs.chain_scripts(max_stale=5))
def test_stale_reads_and_repaints_add_no_key(script):
    """**Validates: Requirements 8.12, 8.14, 8.20**"""
    baseline = fs.ChainScript(
        tuple(dataclasses.replace(s, stale_reads=0, repaints=()) for s in script.steps),
        script.flow,
    )
    base_calls, base_outputs = _run(baseline)

    # Any FlowError raised here fails the test.
    calls, outputs = _run(script)

    def sent(cs):
        return [c for c in cs if c[0] != "read"]

    assert sent(calls) == sent(base_calls) == script.expected_calls()
    assert outputs == base_outputs
