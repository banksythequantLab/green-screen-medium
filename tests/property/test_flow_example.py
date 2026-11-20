# Feature: polish, Property 1: Example validation agrees with its definition
"""Property 1 of spec polish (task 3.3). Requirements 7.3, 7.4.

No live host, no credential. The oracle below is written from the definition
of the ``example`` member, not from ``greenscreen.flow.validate``.
"""
from __future__ import annotations

import dataclasses

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.validate import check_flow
from greenscreen.recognizer import load_bundled_signatures

SIGNATURES = load_bundled_signatures()
BASE = next(iter(load_bundled_flows(SIGNATURES).values()))

_PRINTABLE = [chr(c) for c in range(0x20, 0x7F)]
_ODD = ["\x00", "\t", "\n", "\r", "\x1f", "\x7f", "\x80", "é", "\u4e2d"]
_ONE = st.one_of(
    *([st.sampled_from(_PRINTABLE)] * 8),
    st.sampled_from(["$", "{"]),
    st.sampled_from(_ODD),
)
_CHUNK = st.one_of(*([_ONE] * 6), st.just("${"))
_MIXED = st.lists(_CHUNK, max_size=260).map(lambda parts: "".join(parts)[:260])
_NEAR_LIMIT = st.builds(
    lambda n, tail: ("a" * n + tail)[: n + len(tail)],
    st.integers(196, 205),
    st.sampled_from(["", "$", "{", "${", "é"]),
)
_EXAMPLES = st.one_of(_MIXED, _MIXED, _NEAR_LIMIT)


def _oracle(s: str) -> str | None:
    """Return None when accepted, else the rule that rejects ``s`` first."""
    if any(not (0x20 <= ord(c) <= 0x7E) for c in s):
        return "invalid_text"
    if len(s) > 200:
        return "too_long"
    if "${" in s:
        return "interpolation_marker"
    return None


@settings(max_examples=300, deadline=None)
@given(_EXAMPLES)
def test_example_validation_agrees_with_its_definition(s: str) -> None:
    expected = _oracle(s)
    event("accepted" if expected is None else f"rejected:{expected}")
    if expected is None:
        check_flow(dataclasses.replace(BASE, example=s), SIGNATURES)
        return
    # Flow validates in __post_init__, so building it is the first rejection.
    with pytest.raises(FlowDefinitionError) as info:
        check_flow(dataclasses.replace(BASE, example=s), SIGNATURES)
    message = str(info.value)
    assert "example" in message
    assert expected in message
    for other in ("invalid_text", "too_long", "interpolation_marker"):
        if other != expected:
            assert other not in message
    if len(s) >= 4:
        assert s not in message


# Feature: polish, Property 2: YAML round trip with example and counts
# Task 4.5. Validates: Requirements 7.2, 7.5, 7.6, 13.2, 13.8
import re

from greenscreen.flow.model import CollectStep, ExpectStep, Flow, OutputSpec
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher

_RT_SIGS = [
    ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),)),
    ScreenSignature("more", (TextAtMatcher(0, 0, "MORE"),)),
]

_RT_EXAMPLES = st.text(alphabet=_PRINTABLE, max_size=200).filter(lambda s: "${" not in s)


def _roundtrip_flow(example: str, with_counts: bool) -> Flow:
    outputs = [OutputSpec("ROWS", "str", "tiny", 3, 2, 10, None, 50)]
    if with_counts:
        outputs.append(OutputSpec("TOTAL", "int", "tiny", 3, 2, 10, counts="ROWS"))
    return Flow(
        "round-trip",
        (ExpectStep(("tiny", "more")), CollectStep("ROWS", "more", 3)),
        description="Round trip flow.",
        outputs=tuple(outputs),
        example=example,
    )


@settings(max_examples=200, deadline=None)
@given(_RT_EXAMPLES, st.booleans())
def test_yaml_round_trip_with_example_and_counts(example: str, with_counts: bool) -> None:
    event("example" if example else "no example")
    event("counts" if with_counts else "no counts")
    flow = _roundtrip_flow(example, with_counts)
    text = flow.to_yaml()
    assert Flow.from_yaml(text, _RT_SIGS) == flow
    has_example = re.search(r"^example:", text, re.M) is not None
    has_counts = re.search(r"^\s*(?:- )?counts:", text, re.M) is not None
    assert has_example == (example != "")
    assert has_counts == with_counts
