from __future__ import annotations

import asyncio
import copy
import json
from types import SimpleNamespace

from fastapi.openapi.models import OpenAPI
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from greenscreen.publisher.mcp_server import build_mcp_server
from greenscreen.publisher.registry import build_registry, build_schemas
from greenscreen.publisher.rest import build_openapi
from greenscreen.publisher.vault import BoundValues
from tests.property import _flow_strategies as fs
from tests.property._publisher_strategies import find_leaks, probes
from tests.publisher_support import mcp_client

FORBIDDEN_KEYS = frozenset({"default", "examples", "example", "const", "enum"})
AUDIT_MEMBERS = [
    "step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds",
]


@st.composite
def _cases(draw):
    """A Flow, a subset of its Input names (the Bound_Inputs) and one probe per kind."""
    flow = draw(fs.flows())
    names = [s.name for s in flow.inputs]
    bound = frozenset(draw(st.sets(st.sampled_from(names)))) if names else frozenset()
    return flow, bound, draw(probes("str")), draw(probes("int"))


def _keys(node) -> set[str]:
    """Every dict key at any depth, so a forbidden keyword is found wherever it sits."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(node, list):
        for item in node:
            found |= _keys(item)
    return found


def _tools_list(server) -> dict:
    async def go():
        async with mcp_client(SimpleNamespace(server=server), "auto") as client:
            return {t.name: t for t in (await client.list_tools()).tools}

    return asyncio.run(go())


# Feature: publisher, Property 1: Schemas are valid, deterministic, free of values and embedded unchanged
@settings(max_examples=100, deadline=None)
@given(case=_cases())
def test_schemas_are_valid_deterministic_free_of_values_and_embedded_unchanged(case):
    """**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.9, 2.10, 2.11, 2.12, 12.2, 12.5, 12.7, 22.1**"""
    flow, bound, str_probe, int_probe = case
    inp, out, suc = build_schemas(flow, bound)

    # valid draft 2020-12, JSON-serialisable, no forbidden keyword anywhere
    for schema in (inp, out, suc):
        Draft202012Validator.check_schema(schema)
        json.dumps(schema)
        assert not (_keys(schema) & FORBIDDEN_KEYS)

    # deterministic on equal arguments, also for an equal copy of the Flow
    assert build_schemas(flow, bound) == (inp, out, suc)
    assert build_schemas(copy.deepcopy(flow), frozenset(bound)) == (inp, out, suc)

    # Input_Schema structure
    remaining = [s for s in flow.inputs if s.name not in bound]
    assert inp["type"] == "object"
    assert inp["additionalProperties"] is False
    assert list(inp["properties"]) == [s.name for s in remaining]
    required = [s.name for s in remaining if s.required]
    if required:
        assert inp["required"] == required
    else:
        assert "required" not in inp
    for spec in remaining:
        prop = inp["properties"][spec.name]
        assert ("writeOnly" in prop) == spec.secret
        if spec.secret:
            assert prop["writeOnly"] is True
        assert (prop.get("description") == spec.description) if spec.description else (
            "description" not in prop
        )
        if spec.type == "int":
            m = spec.max_length
            assert prop["type"] == "integer"
            assert prop["maximum"] == 10**m - 1
            assert prop["minimum"] == (-(10 ** (m - 1) - 1) if m > 1 else 0)
            assert "pattern" not in prop and "maxLength" not in prop
        else:
            assert prop["type"] == "string"
            assert prop["maxLength"] == spec.max_length
            if spec.regex is None:
                assert "pattern" not in prop
            else:
                # the pattern is dropped when the regex is not ECMA-safe; never changed
                assert prop.get("pattern", f"^(?:{spec.regex})$") == f"^(?:{spec.regex})$"

    # Output_Schema and Success_Schema: Outputs and Flow name only, nothing from an Input
    out_names = [o.name for o in flow.outputs]
    assert out["type"] == "object" and out["additionalProperties"] is False
    assert list(out["properties"]) == out_names
    assert out["required"] == out_names
    for o in flow.outputs:
        assert out["properties"][o.name] == {"type": "integer" if o.type == "int" else "string"}
    assert suc["properties"]["flow"] == {"type": "string"}
    assert suc["properties"]["outputs"] == out
    audit_item = suc["properties"]["audit"]["items"]
    assert suc["properties"]["audit"]["type"] == "array"
    assert list(audit_item["properties"]) == AUDIT_MEMBERS
    assert audit_item["required"] == AUDIT_MEMBERS
    assert audit_item["additionalProperties"] is False
    assert suc["required"] == ["flow", "outputs", "audit"] and suc["additionalProperties"] is False
    all_bound = build_schemas(flow, frozenset(s.name for s in flow.inputs))
    assert (all_bound[1], all_bound[2]) == (out, suc)
    assert (build_schemas(flow)[1], build_schemas(flow)[2]) == (out, suc)

    # registry, OpenAPI document and tools/list embed the same schemas, and no bound value
    values = {s.name: (int_probe if s.type == "int" else str_probe) for s in flow.inputs if s.name in bound}
    registry = build_registry(
        {flow.name: (flow, "bundled")},
        BoundValues({flow.name: values} if values else None),
        60.0,
    )
    entry = registry[flow.name]
    assert (entry.input_schema, entry.output_schema, entry.success_schema) == (inp, out, suc)

    doc = build_openapi(registry, "0")
    OpenAPI.model_validate(doc)
    operation = doc["paths"][f"/flows/{flow.name}"]["post"]
    assert operation["operationId"] == flow.name
    assert operation["summary"] == (flow.description or f"Run flow {flow.name}.")
    assert operation["requestBody"]["content"]["application/json"]["schema"] == inp
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == suc

    tool = _tools_list(build_mcp_server(None, registry))[flow.name]  # type: ignore[arg-type]
    assert tool.input_schema == inp
    assert tool.output_schema == suc
    assert tool.description == operation["summary"]

    for name in bound:
        assert name not in inp["properties"] and name not in inp.get("required", [])
    if values:
        texts = [json.dumps(doc), json.dumps(tool.input_schema), json.dumps(tool.output_schema)]
        for text in texts:
            assert find_leaks(text, values.values()) == []
