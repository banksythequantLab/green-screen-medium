"""Bounds, validity and cost of the ``flows()`` strategy (task 18.2).

Timings of task 18.1 (100 draws, best of three, ``time.perf_counter``, dev machine),
copied from the docstring of ``tests/property/_flow_strategies.py``:

    before the trim: 2.769 s for 100 draws, 3.293 s for 100 draws with the YAML round trip
    after the trim:  0.163 s for 100 draws, 1.030 s for 100 draws with the YAML round trip

The ``perf`` test asserts the round-trip figure stays under 1.5 s. A slow or loaded
machine can deselect it with ``-m 'not perf'``.
"""
from __future__ import annotations

import os
import time

import pytest
from hypothesis import given, settings

from greenscreen.flow.model import Flow, HandleStep
from greenscreen.flow.validate import check_flow
from greenscreen.recognizer import load_bundled_signatures
from tests.property._flow_strategies import flows

SIGNATURES = load_bundled_signatures()


def _handles(steps):
    return [s for s in steps if isinstance(s, HandleStep)]


@settings(max_examples=100, deadline=None, database=None, derandomize=True)
@given(flows())
def test_drawn_flows_stay_within_bounds(flow: Flow) -> None:
    assert len(flow.steps) <= 6
    assert len(flow.inputs) <= 2
    assert len(flow.outputs) <= 2
    assert len(flow.finally_steps) <= 2
    for handle in _handles(flow.steps) + _handles(flow.finally_steps):
        assert 1 <= len(handle.steps) <= 2


@settings(max_examples=300, deadline=None, database=None, derandomize=True)
@given(flows())
def test_drawn_flows_are_valid_and_round_trip(flow: Flow) -> None:
    assert isinstance(flow, Flow)
    check_flow(flow, SIGNATURES)
    assert Flow.from_yaml(flow.to_yaml(), SIGNATURES) == flow


@pytest.mark.perf
@pytest.mark.skipif(
    os.environ.get("GS_RUN_PERF") != "1",
    reason="perf test is opt-in: set GS_RUN_PERF=1 to run it",
)
def test_100_draws_with_round_trip_under_budget() -> None:
    elapsed: list[float] = []

    @settings(max_examples=100, deadline=None, database=None, derandomize=True)
    @given(flows())
    def run(flow: Flow) -> None:
        Flow.from_yaml(flow.to_yaml(), SIGNATURES)

    for _ in range(3):
        start = time.perf_counter()
        run()
        elapsed.append(time.perf_counter() - start)
    assert min(elapsed) < 1.5, f"best of three was {min(elapsed):.3f} s: {elapsed}"
