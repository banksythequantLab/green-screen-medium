"""Property 2: the Input_Schema never rejects what the Input_Validator accepts.

Requirements 2.8, 20.3, 22.1, 22.2 (and 4.4 for the excluded integral floats).

The Input_Validator is ``prepare_inputs`` over the declaration of the Inputs that are
not bound (``_Decl``, as ``build_registry`` builds it). The Input_Schema is
``build_schemas(flow, bound_names)[0]``, checked with ``Draft202012Validator``.
Floats are fractional only: ``1.0`` and ``1e3`` are a unit test in
``tests/unit/test_publisher_registry.py``. No value here is a credential.
"""
from __future__ import annotations

from jsonschema import Draft202012Validator
from hypothesis import event, given, settings
from hypothesis import strategies as st

from greenscreen.flow.errors import FlowInputError
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.publisher.registry import _Decl, build_schemas
from tests.property._flow_strategies import flows

_EXTRA_NAMES = ("zz", "extra_0")
_KINDS = 8  # see _value


def _value(spec, kind: int, text: str, num: int, frac: float):
    """One JSON value for ``spec``; ``kind`` 6 means absent (returns a marker)."""
    is_int = spec.type == "int"
    if kind == 0:
        return 7 if is_int else "ABC"  # valid for every pool Input
    if kind == 1:
        return "7" if is_int else 5  # the other JSON type
    if kind == 2:
        return True  # a boolean is not an integer and not a string
    if kind == 3:
        return frac  # fractional float
    if kind == 4:
        return 10**spec.max_length + abs(num) if is_int else "A" * (spec.max_length + 1 + abs(num) % 5)
    if kind == 5:
        return num if is_int else text  # arbitrary value of the right type
    if kind == 7:
        return text if is_int else num  # arbitrary value of the wrong type
    return None


@st.composite
def _cases(draw):
    flow = draw(flows())
    mask = draw(st.lists(st.booleans(), min_size=len(flow.inputs), max_size=len(flow.inputs)))
    bound = frozenset(s.name for s, b in zip(flow.inputs, mask) if b)
    mapping: dict = {}
    for spec in flow.inputs:
        kind = draw(st.integers(0, _KINDS - 1))
        text = draw(st.text(max_size=12))
        num = draw(st.integers(-(10**6), 10**6))
        frac = draw(st.integers(-1000, 1000).map(lambda n: n + 0.5))
        if spec.name in bound and draw(st.integers(0, 3)):
            continue  # most calls leave a Bound_Input out; some supply it
        if kind != 6:
            mapping[spec.name] = _value(spec, kind, text, num, frac)
    for name in _EXTRA_NAMES:
        if draw(st.integers(0, 4)) == 0:
            mapping[name] = draw(st.sampled_from(("ABC", 7, 1.5, True, None)))
    return flow, bound, mapping


def _violates(unbound, mapping) -> bool:
    """The rules that JSON Schema also enforces: required, additionalProperties, type, length."""
    names = {s.name for s in unbound}
    if any(n not in names for n in mapping):
        return True
    for spec in unbound:
        if spec.name not in mapping:
            if spec.required:
                return True
            continue
        v = mapping[spec.name]
        if type(v) is not (int if spec.type == "int" else str):  # bool and float fail here
            return True
        if len(str(v)) > spec.max_length:
            return True
    return False


# Feature: publisher, Property 2: The schema never rejects what the validator accepts
@settings(max_examples=100, deadline=None)
@given(_cases())
def test_schema_never_rejects_what_validator_accepts(case) -> None:
    flow, bound, mapping = case
    unbound = tuple(s for s in flow.inputs if s.name not in bound)
    schema = build_schemas(flow, bound)[0]
    schema_ok = Draft202012Validator(schema).is_valid(mapping)
    try:
        prepare_inputs(_Decl(unbound), mapping)  # type: ignore[arg-type]
        validator_ok = True
    except FlowInputError:
        validator_ok = False

    # Requirement 2.8: one direction only.
    if validator_ok:
        event("validator accepts")
        assert schema_ok
    # Requirement 20.3: a violation of type, required, additionalProperties or
    # maxLength is rejected by both. Bound names count as undeclared (22.2).
    if _violates(unbound, mapping):
        event("violation")
        assert not validator_ok
        assert not schema_ok
    if bound:
        event("with bound inputs")

    # Requirement 22.1: all bound gives an empty schema that accepts only {}.
    if len(bound) == len(flow.inputs):
        event("all bound")
        assert schema["properties"] == {}
        assert "required" not in schema
        assert Draft202012Validator(schema).is_valid({})
        assert schema_ok == (not mapping)
        assert validator_ok == (not mapping)
