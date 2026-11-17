"""Property 1 of flow-runtime: YAML round trip and determinism."""
from __future__ import annotations

import yaml
from hypothesis import given, settings

from greenscreen.flow.model import Flow
from greenscreen.recognizer import load_bundled_signatures
from tests.property._flow_strategies import flows

SIGNATURES = load_bundled_signatures()


@settings(max_examples=100, deadline=None)
@given(flows())
def test_yaml_round_trip_and_determinism(flow: Flow) -> None:
    # Feature: flow-runtime, Property 1: YAML round trip and determinism
    # **Validates: Requirements 1.1, 6.3, 6.4, 6.5**
    text = flow.to_yaml()

    assert Flow.from_yaml(text, SIGNATURES) == flow
    assert flow.to_yaml() == text

    document = yaml.safe_load(text)
    first_key = next(iter(document))
    assert first_key == "version"
    assert document["version"] == 1
    assert type(document["version"]) is int
