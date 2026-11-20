"""Property 3 of spec polish: the OpenAPI operation carries ``x-ask-example`` if and only if
Ask is on, offers the Flow, and the Flow has an example.

``build_openapi`` reads three members of its ``ask`` argument: ``offered``,
``max_question_chars`` and ``max_answer_chars``. The test passes a three-member stub with
exactly those, so no AskService, model or network is built. Flows are ``MINI`` renamed,
with a random example. No credential is involved.
"""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

from hypothesis import given
from hypothesis import strategies as st

from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.rest import build_openapi
from greenscreen.publisher.vault import BoundValues
from tests.property._publisher_strategies import SETTINGS
from tests.publisher_support import MINI

KEY = "x-ask-example"
FORBIDDEN = {"default", "example", "examples", "const", "enum"}

_example = st.one_of(
    st.just(""),
    st.text(alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E), min_size=1, max_size=60).filter(
        lambda s: "${" not in s
    ),
)
_names = st.lists(st.text(alphabet="abcdefgh", min_size=1, max_size=6), min_size=1, max_size=4, unique=True)


def _walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_keys(value)


def _registry(names, examples):
    flows = {n: (dataclasses.replace(MINI, name=n, example=e), "test") for n, e in zip(names, examples)}
    return build_registry(flows, BoundValues(), 30.0)


def _operations(doc):
    return {p[len("/flows/"):]: i["post"] for p, i in doc["paths"].items() if p.startswith("/flows/")}


# Feature: polish, Property 3: The OpenAPI operation carries the example if and only if Ask offers the Flow and the Flow has one
@SETTINGS
@given(data=st.data(), names=_names, ask_on=st.booleans())
def test_operation_carries_the_example_iff_offered_and_present(data, names, ask_on):
    """**Validates: Requirements 8.4, 8.5, 8.6, 8.7, 8.8**"""
    examples = [data.draw(_example) for _ in names]
    # the offered set: any subset of the registry, plus a name that is not in it
    offered = frozenset(n for n in names if data.draw(st.booleans())) | (
        frozenset({"zz"}) if data.draw(st.booleans()) else frozenset()
    )
    ask = (
        SimpleNamespace(offered=offered, max_question_chars=500, max_answer_chars=2000)
        if ask_on
        else None
    )
    registry = _registry(names, examples)
    bare = _registry(names, [""] * len(names))

    doc = build_openapi(registry, "1", ask)
    base = build_openapi(bare, "1", ask)
    ops, base_ops = _operations(doc), _operations(base)
    assert set(ops) == set(names)

    for name, example in zip(names, examples):
        op = dict(ops[name])
        if ask_on and name in offered and example:
            assert op.pop(KEY) == example
        else:
            assert KEY not in op
        # every other member equals the one built from the same Flow without the example
        assert op == base_ops[name]

    # nothing else in the document changes
    for d in (doc, base):
        for op in _operations(d).values():
            op.pop(KEY, None)
    assert doc == base

    # the /ask schemas legitimately use const and enum; the Flow parts must not
    assert not FORBIDDEN & set(_walk_keys(list(_operations(doc).values())))
    assert build_openapi(registry, "1", ask) == build_openapi(registry, "1", ask)
    assert json.loads(json.dumps(build_openapi(registry, "1", ask))) == build_openapi(registry, "1", ask)
