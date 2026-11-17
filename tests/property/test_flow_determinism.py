"""Property 2 of the flow-runtime spec: runs are deterministic and terminate."""
from __future__ import annotations

import dataclasses

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.flow.errors import FlowError
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import FakeClock, ScriptedSession
from tests.property import _flow_strategies as fs


# Loaded once: run_flow would otherwise re-parse the bundled YAML on every run.
_SIGNATURES = tuple(load_bundled_signatures())


def _run(script, fail_at):
    session = ScriptedSession(script.states(fail_at=fail_at))
    clock = FakeClock()
    try:
        result = run_flow(script.flow, session, {}, signatures=_SIGNATURES, clock=clock)
    except FlowError as error:
        return session.calls, ("error", error.reason, error.step_index, error.expected), error.audit
    return session.calls, ("ok", dict(result.outputs)), result.audit


def _trail(audit):
    return [dataclasses.replace(r, duration_seconds=0.0) for r in audit]


# Feature: flow-runtime, Property 2: Runs are deterministic and terminate
@settings(max_examples=100, deadline=None)
@given(script=fs.chain_scripts(max_screens=4, max_stale=3, step_timeout=1.0), fail=st.one_of(st.none(), st.integers(0, 5)))
def test_runs_are_deterministic_and_terminate(script, fail):
    """**Validates: Requirements 3.9, 8.4, 12.6, 15.6**"""
    fail_at = None if fail is None else fail % len(script.steps)

    calls1, outcome1, audit1 = _run(script, fail_at)
    calls2, outcome2, audit2 = _run(script, fail_at)

    assert outcome1 == outcome2
    assert calls1 == calls2
    assert _trail(audit1) == _trail(audit2)

    if outcome1[0] == "ok":
        assert list(outcome1[1]) == [o.name for o in script.flow.outputs]

    # Finite: no Step polls more than timeout / poll_interval times, and each
    # Step makes at most one pre-key read and one typing and one key call.
    timeouts = script.flow.timeouts
    per_step = int(timeouts.step / 0.1) + 4
    bound = len(script.flow.steps) * per_step + len(script.flow.finally_steps) * per_step
    assert len(calls1) <= bound
