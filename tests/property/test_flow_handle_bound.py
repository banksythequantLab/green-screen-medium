"""Property 5 of the flow-runtime spec: a Handle_Step runs at most max_count iterations."""
from __future__ import annotations

import pytest
from hypothesis import given, settings

from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, Flow, HandleStep, KeyStep
from greenscreen.flow.runner import run_flow
from tests.flow_support import FakeClock, ScriptedSession, capture, pause_variant
from tests.property import _flow_strategies as fs

_KEYS = ("enter", "clear", "pf", "pa")
_HANDLED = "tso-pause"
_NEXT = "ispf-primary-menu"


def _flow(max_count: int) -> Flow:
    # The Expect_Step names the next screen so the runner can recognize it.
    return Flow(
        "handle_bound",
        (HandleStep(_HANDLED, max_count, (KeyStep("enter"),)), ExpectStep((_NEXT,))),
    )


# Feature: flow-runtime, Property 5: A Handle_Step runs at most max_count iterations
@settings(max_examples=100, deadline=None)
@given(case=fs.handle_counts())
def test_handle_step_runs_at_most_max_count_iterations(case):
    """**Validates: Requirements 9.2, 9.3, 9.4, 9.6, 9.7, 12.6**"""
    n = case.max_count
    over = case.forever or case.shown > n
    # Distinct handled screens, so a repeated screen is never read as "no answer yet".
    shown = n + 1 if over else case.shown
    states = [pause_variant(i) for i in range(shown)]
    if not over:
        states.append(capture(_NEXT))
    session = ScriptedSession(states)
    flow = _flow(n)

    if over:
        with pytest.raises(FlowError) as caught:
            run_flow(flow, session, {}, clock=FakeClock())
        error = caught.value
        assert error.reason == "loop_limit"
        assert error.step_index == 0
        keys = [c for c in session.calls if c[0] in _KEYS]
        assert keys == [("enter",)] * n
        # No key (or typing) follows the last key: only reads.
        last_key = max(i for i, c in enumerate(session.calls) if c[0] in _KEYS)
        assert all(c == ("read",) for c in session.calls[last_key + 1 :])
        assert not any(c[0] == "string" for c in session.calls)
        handle = [a for a in error.audit if a.kind == "handle"]
        assert len(handle) == 1 and handle[0].status == "failed" and handle[0].step_index == 0
        body = [a for a in error.audit if a.kind == "key"]
        assert [a.iteration for a in body] == list(range(1, n + 1))
        assert all(a.status == "ok" for a in body)
        assert not any(a.status == "skipped" for a in error.audit)
    else:
        result = run_flow(flow, session, {}, clock=FakeClock())
        keys = [c for c in session.calls if c[0] in _KEYS]
        assert keys == [("enter",)] * case.shown
        handle = [a for a in result.audit if a.kind == "handle"]
        assert len(handle) == 1 and handle[0].status == "ok"
        body = [a for a in result.audit if a.kind == "key" and a.status != "skipped"]
        assert [a.iteration for a in body] == list(range(1, case.shown + 1))
        skipped = [a for a in result.audit if a.kind == "key" and a.status == "skipped"]
        assert len(skipped) == (1 if case.shown == 0 else 0)
