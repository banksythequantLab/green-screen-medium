"""Extract_Step signature mismatch (flow-runtime task 16.4).

Covers Requirements 11.3, 14.11 and 18.23.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

import greenscreen.flow.runner as runner_module
import greenscreen.flow.screens as screens_module
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, ExtractStep, Flow, OutputSpec
from greenscreen.flow.runner import run_flow

from tests.flow_support import FakeClock, ScriptedSession, capture

_OUTPUT = OutputSpec("FIRST", "str", "ispf-primary-menu", 0, 28, 4)


@pytest.fixture
def read_region_calls(monkeypatch):
    calls = []
    original = screens_module.read_region

    def spy(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    # The runner binds the name at import time, so patch both places.
    monkeypatch.setattr(screens_module, "read_region", spy)
    monkeypatch.setattr(runner_module, "read_region", spy)
    return calls


def _run(flow, state):
    return run_flow(flow, ScriptedSession([capture(state)]), {}, clock=FakeClock())


def test_matching_signature_reads_region_once(read_region_calls):
    flow = Flow(
        "t",
        (ExpectStep(("ispf-primary-menu",)), ExtractStep("FIRST")),
        outputs=(_OUTPUT,),
    )
    result = _run(flow, "ispf-primary-menu")
    assert result.outputs["FIRST"] == "ISPF"
    assert len(read_region_calls) == 1


def _bypass_validation(flow, **fields):
    """Flow validation rejects these shapes, so alter a valid Flow afterwards."""
    for name, value in fields.items():
        object.__setattr__(flow, name, value)
    return flow


def test_mismatch_raises_unexpected_screen_without_reading_region(read_region_calls):
    flow = Flow(
        "t",
        (ExpectStep(("ispf-primary-menu",)), ExtractStep("FIRST")),
        outputs=(_OUTPUT,),
    )
    _bypass_validation(flow, outputs=(replace(_OUTPUT, signature="tk5-logon"),))
    with pytest.raises(FlowError) as info:
        _run(flow, "ispf-primary-menu")
    err = info.value
    assert err.reason == "unexpected_screen"
    assert err.step_index == 1
    assert err.expected == ("tk5-logon",)
    assert err.summary is not None
    assert str(err.summary)
    assert read_region_calls == []


def test_absent_current_screen_has_no_summary(read_region_calls):
    flow = Flow(
        "t",
        (ExpectStep(("ispf-primary-menu",)), ExtractStep("FIRST")),
        outputs=(_OUTPUT,),
    )
    _bypass_validation(flow, steps=(ExtractStep("FIRST"),))
    with pytest.raises(FlowError) as info:
        _run(flow, "ispf-primary-menu")
    err = info.value
    assert err.reason == "unexpected_screen"
    assert err.step_index == 0
    assert err.expected == ("ispf-primary-menu",)
    assert err.summary is None
    assert read_region_calls == []

