"""A definition error skips every Finally_Step (flow-runtime task 16.5).

Covers Requirements 13.3, 18.22 and 18.24. The containing_field tests are in
``test_flow_runner_fixes_containing_field.py``.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import (
    ExpectStep,
    Flow,
    HandleStep,
    KeyStep,
    TypeStep,
    plan,
)
from greenscreen.flow import runner as runner_module
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import FakeClock, ScriptedSession, capture


def _signatures():
    by_name = {s.name: s for s in load_bundled_signatures()}
    # A duplicated name makes ``recognize`` raise SignatureError.
    return [by_name["tk5-logon"], by_name["tk5-logon"], by_name["tk5-logo"]]


def _flow() -> Flow:
    handle = HandleStep("tk5-logo", 1, (TypeStep(text="X"), KeyStep("enter")))
    return Flow(
        "t",
        (ExpectStep(("tk5-logon",)),),
        finally_steps=(handle, ExpectStep(("tk5-logon",))),
    )


def _walk(items):
    for item in items:
        yield item
        yield from _walk(item.children)


def test_definition_error_skips_every_finally_step(monkeypatch):
    flow = _flow()
    captured = []
    original = runner_module._RunState.release

    def spy(self):
        captured.append(self)
        return original(self)

    monkeypatch.setattr(runner_module._RunState, "release", spy)
    session = ScriptedSession([capture("tk5-logon")])

    with pytest.raises(FlowDefinitionError):
        run_flow(flow, session, {}, signatures=_signatures(), clock=FakeClock())

    assert [c for c in session.calls if c[0] != "read"] == []  # no key sent at all
    assert len(captured) == 1
    audit = captured[0].audit
    _, fin = plan(flow)
    expected = sorted(i.index for i in _walk(fin))
    assert expected  # the finally plan is not empty
    finally_records = [r for r in audit if r.phase == "finally"]
    assert sorted(r.step_index for r in finally_records) == expected
    for record in finally_records:
        assert record.status == "skipped"
        assert record.duration_seconds == 0.0
    # the Expect_Step of the steps phase is the one that failed
    assert [(r.step_index, r.status) for r in audit if r.phase == "steps"] == [
        (0, "failed")
    ]


def test_definition_is_a_finally_skip_reason():
    assert "definition" in runner_module._FINALLY_SKIP_REASONS
