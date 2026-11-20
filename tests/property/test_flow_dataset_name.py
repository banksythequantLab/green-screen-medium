# Feature: more-flows, Property 6: The input verdict equals the independent scanner, and accepted names are typed exactly
"""Properties 6 and 10 of spec more-flows (task 5.3).

Requirements 8.2 to 8.6, 20.1, 20.6, 20.8, 20.9. No live host, no credential.
"""
from __future__ import annotations

from hypothesis import event, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from greenscreen.flow.errors import FlowInputError
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.flow.runner import run_flow
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from tests.dsname_support import (
    dsname_candidates,
    name_flow,
    name_session,
    scanner,
    typed_strings,
)
from tests.flow_support import FakeClock

_FLOW = name_flow()
_FLOW_MEMBERS = name_flow(members=True)


def _runtime_accepts(name: str) -> bool:
    try:
        prepare_inputs(_FLOW, {"dsname": name})
    except FlowInputError:
        return False
    return True


@settings(max_examples=300, deadline=None)
@given(dsname_candidates(), st.booleans())
def test_verdict_equals_scanner_and_accepted_names_are_typed_exactly(
    name: str, members: bool
) -> None:
    expected = scanner(name)
    assert _runtime_accepts(name) is expected
    if not expected:
        event("rejected")
        return
    event("accepted")
    session = name_session()
    run_flow(
        _FLOW_MEMBERS if members else _FLOW,
        session,
        {"dsname": name},
        clock=FakeClock(),
    )
    closing = "' MEMBERS" if members else "'"
    assert typed_strings(session) == ["LISTDS '", name, closing]


# Feature: more-flows, Property 10: The published schema agrees with the runtime
_PUBLISHED = build_registry(
    {_FLOW.name: (_FLOW, "test")}, BoundValues(), call_timeout=60.0
)[_FLOW.name]
_VALIDATOR = Draft202012Validator(_PUBLISHED.input_schema)


@settings(max_examples=200, deadline=None)
@given(dsname_candidates().filter(lambda s: "\n" not in s and "\r" not in s))
def test_published_schema_agrees_with_runtime_and_scanner(name: str) -> None:
    schema_ok = _VALIDATOR.is_valid({"dsname": name})
    runtime_ok = _runtime_accepts(name)
    expected = scanner(name)
    event("accepted" if expected else "rejected")
    assert schema_ok == runtime_ok == expected
