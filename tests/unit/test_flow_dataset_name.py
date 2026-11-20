"""Unit tests for the ``dsname`` input rule (spec more-flows, task 5.2).

Covers Requirements 8.1 to 8.4, 20.1 to 20.4 and 20.7 through ``prepare_inputs``
and ``run_flow`` over a ``ScriptedSession``. No live host.
"""
from __future__ import annotations

import re
import time

import pytest

from greenscreen.flow.errors import FlowInputError
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.flow.runner import run_flow
from greenscreen.publisher.registry import _ecma_safe
from tests.dsname_support import (
    DSNAME_DESCRIPTION,
    DSNAME_REGEX,
    DSNAME_SPEC,
    name_flow,
    name_session,
    typed_strings,
)
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import PROBE_ALPHABET

FLOW = name_flow()

ACCEPTED = [
    "SYS2.JCLLIB",
    "sys2.jcllib",
    "$A.#B.@C",
    "ABCDEFGH",
    ".".join("A" * 22),  # 22 one-character qualifiers, 43 characters
    ".".join(["AB"] + ["A"] * 21),  # 22 qualifiers, 44 characters
    "A",
    "A1",
]

def _rule(name: str) -> str:
    with pytest.raises(FlowInputError) as info:
        prepare_inputs(FLOW, {"dsname": name})
    return str(info.value)


def test_constants_are_the_design_input():
    assert DSNAME_SPEC.max_length == 44 and DSNAME_SPEC.regex == DSNAME_REGEX
    assert DSNAME_SPEC.required and not DSNAME_SPEC.secret


@pytest.mark.parametrize("name", ACCEPTED)
def test_accepted_names_are_prepared_unchanged(name):
    assert len(name) <= 44
    assert prepare_inputs(FLOW, {"dsname": name}).values == {"dsname": name}


def test_boundary_lengths_of_the_examples():
    assert len(".".join("A" * 22)) == 43
    assert len(ACCEPTED[5]) == 44
    assert len(".".join("A" * 23)) == 45


@pytest.mark.parametrize(
    "name",
    [
        "A..B", "1ABC", ".A", "A.", "A-B", "A_B", "ABCDEFGHI", "A B", "A'B",
        "A(B)", "A,B", "", "A\tB", "A\nB", "A\x00B", "A\x7fB", "A\u00e9B",
        "\uff11ABC", "A\u200fB", ".".join("A" * 23), "ABCDEFGH.ABCDEFGH.ABCDEFGH.ABCDEFGH.ABCDEFG.A",
    ],
)
def test_rejected_names_raise_input_invalid_without_the_value(name):
    with pytest.raises(FlowInputError) as info:
        prepare_inputs(FLOW, {"dsname": name})
    err = info.value
    assert err.reason == "input_invalid"
    assert "dsname" in str(err)
    if len(name) >= 2:
        assert name not in str(err)
    assert re.search(r"violates (regex|max_length|printable_ascii)\b", str(err))


def test_rule_names_for_the_three_kinds_of_fault():
    assert _rule("A..B").endswith("violates regex")
    assert _rule("A\u00e9B").endswith("violates printable_ascii")
    assert _rule("A" * 45).endswith("violates max_length")


def test_45_character_name_with_valid_qualifiers_is_rejected_on_length():
    name = "ABCDEFGH.ABCDEFGH.ABCDEFGH.ABCDEFGH.ABCDEFG.A"  # 6 valid qualifiers, 45 characters
    assert len(name) == 45
    assert _rule(name).endswith("violates max_length")


def test_length_is_checked_before_the_pattern():
    # Over 44 characters and also pattern-violating and non-ASCII: length wins.
    assert _rule("!" * 45).endswith("violates max_length")
    assert _rule("\u00e9" * 45).endswith("violates max_length")
    # Within 44 and non-ASCII: printable check comes before the pattern.
    assert _rule("\u00e9").endswith("violates printable_ascii")


def test_lower_case_is_accepted_as_given():
    assert prepare_inputs(FLOW, {"dsname": "sys2.jcllib"}).values["dsname"] == "sys2.jcllib"


@pytest.mark.parametrize("members", [False, True])
@pytest.mark.parametrize("name", ["SYS2.JCLLIB", "sys2.jcllib", "$A.#B.@C", ACCEPTED[5]])
def test_accepted_name_is_typed_between_the_literals(name, members):
    session = name_session()
    run_flow(name_flow(members=members), session, {"dsname": name}, clock=FakeClock())
    closing = "' MEMBERS" if members else "'"
    assert typed_strings(session) == ["LISTDS '", name, closing]


@pytest.mark.parametrize("members", [False, True])
@pytest.mark.parametrize(
    "name", ["A..B", "1ABC", ".A", "A.", "A B", "A'B", "A(B)", "A,B", "", "A\x00B", "A\u00e9B", "A" * 45]
)
def test_rejected_name_stops_before_any_session_call(name, members):
    session = name_session()
    with pytest.raises(FlowInputError) as info:
        run_flow(name_flow(members=members), session, {"dsname": name}, clock=FakeClock())
    assert info.value.reason == "input_invalid"
    assert "dsname" in str(info.value)
    if len(name) >= 2:
        assert name not in str(info.value)
    assert session.calls == []


def test_pattern_has_bounded_quantifiers_only():
    assert len(DSNAME_REGEX) <= 200
    assert not re.search(r"[*+]", DSNAME_REGEX)
    assert not re.search(r"(?<!\\)\?(?!:)", DSNAME_REGEX)
    for q in re.findall(r"\{[^}]*\}", DSNAME_REGEX):
        assert re.fullmatch(r"\{\d+(,\d+)?\}", q)
    assert _ecma_safe(DSNAME_REGEX)


def test_near_miss_is_matched_in_negligible_time():
    near = ".".join(["ABCDEFGH"] * 5) + "!" * 5  # 49 characters, faulty tail
    assert len(near) == 49
    start = time.perf_counter()
    for _ in range(200):
        assert re.fullmatch(DSNAME_REGEX, near) is None
    assert time.perf_counter() - start < 0.5


def test_description_is_short_and_free_of_probe_characters():
    assert len(DSNAME_DESCRIPTION) <= 200
    assert not set(PROBE_ALPHABET) & set(DSNAME_DESCRIPTION)
