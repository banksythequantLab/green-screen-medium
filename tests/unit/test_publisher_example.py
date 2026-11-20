"""``x-ask-example`` in the OpenAPI document (spec polish, task 6.2; Requirement 8).

The real application over the six bundled Published_Tools, Fake_Host, no network.
Keys and Bound_Values are generated at run time and never written anywhere.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
from types import SimpleNamespace

import pytest

from greenscreen.publisher.app import prepare
from greenscreen.publisher.registry import build_schemas
from greenscreen.publisher.rest import _package_version, build_openapi
from tests.ask_support import build_ask_app, no_network  # noqa: F401  (autouse)
from tests.example_support import (
    SIX,
    fetch_document,
    six_tool_document,
    six_tool_environment,
    six_tool_overrides,
)
from tests.publisher_support import mcp_client, rest_client

KEY = "x-ask-example"
OFF = {"GS_ENABLE_ASK": "false"}
TWO = ("tk5-time", "tk5-job-status")
TWO_ENV = {"GS_ASK_FLOWS": ",".join(TWO)}
FORBIDDEN = {"default", "example", "examples", "const", "enum"}


def prepared_for(env: dict | None = None):
    return prepare(six_tool_environment(env))


def operations(doc: dict) -> dict[str, dict]:
    return {
        path[len("/flows/"):]: item["post"]
        for path, item in doc["paths"].items()
        if path.startswith("/flows/")
    }


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_keys(value)


def examples_of(env: dict | None = None) -> dict[str, str]:
    registry = prepared_for(env).registry
    return {n: registry[n].flow.example for n in SIX}


def strip_example(doc: dict) -> dict:
    doc = json.loads(json.dumps(doc))
    for op in operations(doc).values():
        op.pop(KEY, None)
    return doc


# --------------------------------------------------------------------------
# (a) Ask off
# --------------------------------------------------------------------------

def test_the_six_flows_have_examples():
    assert all(examples_of().values())


def test_ask_off_has_no_example_member_anywhere_and_no_ask_path():
    doc, app = six_tool_document(OFF)
    assert app.app.ask is None
    assert set(operations(doc)) == set(SIX)
    assert KEY not in set(walk_keys(doc))
    assert "/ask" not in doc["paths"]


# --------------------------------------------------------------------------
# (b) Ask on, all six eligible
# --------------------------------------------------------------------------

def test_ask_on_gives_exactly_six_operations_the_example_of_their_flow():
    doc, app = six_tool_document()
    ops = operations(doc)
    assert set(ops) == set(SIX)
    expected = examples_of()
    with_member = {n for n, op in ops.items() if KEY in op}
    assert with_member == set(SIX)
    for name, op in ops.items():
        assert op[KEY] == expected[name]
        assert list(op)[-1] == KEY  # the last member of the operation
    assert sum(1 for k in walk_keys(doc) if k == KEY) == 6


def test_ask_on_changes_nothing_else_in_any_operation():
    on, _ = six_tool_document()
    off, _ = six_tool_document(OFF)
    on_ops, off_ops = operations(on), operations(off)
    for name in SIX:
        assert {k: v for k, v in on_ops[name].items() if k != KEY} == off_ops[name]
    rest = strip_example(on)
    rest["paths"].pop("/ask")
    for name in ("AskResponse", "AskTrace", "AskErrorBody"):
        rest["components"]["schemas"].pop(name)
    assert rest == off


# --------------------------------------------------------------------------
# (c) Ask on, GS_ASK_FLOWS limited
# --------------------------------------------------------------------------

def test_ask_flows_limits_the_member_to_the_named_flows():
    doc, app = six_tool_document(TWO_ENV)
    expected = examples_of(TWO_ENV)
    ops = operations(doc)
    for name in SIX:
        if name in TWO:
            assert ops[name][KEY] == expected[name]
        else:
            assert KEY not in ops[name]
            assert expected[name]  # the Flow has an example, it is just not offered
    assert sum(1 for k in walk_keys(doc) if k == KEY) == 2
    assert app.app.ask.offered == frozenset(TWO)


# --------------------------------------------------------------------------
# tk5-library-members: the literal of design section 10
# --------------------------------------------------------------------------

AUDIT_PROPS = {
    "step_index": {"type": "integer"},
    "kind": {"type": "string"},
    "phase": {"type": "string"},
    "iteration": {"type": ["integer", "null"]},
    "signature": {"type": ["string", "null"]},
    "status": {"type": "string"},
    "duration_seconds": {"type": "number"},
}
DESCRIPTION = (
    "List the member names of a partitioned data set (library) by name (TSO LISTDS with "
    "MEMBERS). MEMBERS holds one member name per line, in the host's order, up to 200. "
    "MEMBER_COUNT is the number of names in MEMBERS. A longer list stops the call with an "
    "error. An empty MEMBERS means the library has no members or does not exist. Call "
    "tk5-dataset-info to tell the two apart. Read-only."
)
LIBRARY_OPERATION = {
    "operationId": "tk5-library-members",
    "summary": DESCRIPTION,
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "dsname": {
                            "type": "string",
                            "maxLength": 44,
                            "pattern": (
                                "^(?:[A-Za-z$#@][A-Za-z0-9$#@]{0,7}"
                                "(?:\\.[A-Za-z$#@][A-Za-z0-9$#@]{0,7}){0,21})$"
                            ),
                            "description": (
                                "Data set name, e.g. SYS2.JCLLIB, any case. Up to 44 characters. "
                                "Dot-separated qualifiers of 1-8 characters, each starting with a "
                                "letter, dollar, number sign or at sign, then letters, digits or "
                                "those."
                            ),
                        }
                    },
                    "additionalProperties": False,
                    "required": ["dsname"],
                }
            }
        },
    },
    "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
}
LIBRARY_200 = {
    "description": "The flow finished.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "flow": {"type": "string"},
                    "outputs": {
                        "type": "object",
                        "properties": {
                            "MEMBERS": {"type": "string"},
                            "MEMBER_COUNT": {"type": "integer"},
                        },
                        "additionalProperties": False,
                        "required": ["MEMBERS", "MEMBER_COUNT"],
                    },
                    "audit": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": AUDIT_PROPS,
                            "additionalProperties": False,
                            "required": [
                                "step_index", "kind", "phase", "iteration", "signature",
                                "status", "duration_seconds",
                            ],
                        },
                    },
                },
                "additionalProperties": False,
                "required": ["flow", "outputs", "audit"],
            }
        }
    },
}
LIBRARY_EXAMPLE = "Which members does SYS2.JCLLIB have?"


def check_library(op: dict, other: dict, with_example: bool) -> None:
    body = {k: v for k, v in op.items() if k not in ("responses", KEY)}
    assert body == LIBRARY_OPERATION
    assert op["responses"]["200"] == LIBRARY_200
    errors = {k: v for k, v in op["responses"].items() if k != "200"}
    assert errors == {k: v for k, v in other["responses"].items() if k != "200"}
    assert errors  # the shared error statuses are there
    if with_example:
        assert op[KEY] == LIBRARY_EXAMPLE
        assert list(op)[-1] == KEY
    else:
        assert KEY not in op


def test_library_members_operation_equals_the_design_literal_with_ask_on():
    doc, _ = six_tool_document()
    ops = operations(doc)
    check_library(ops["tk5-library-members"], ops["tk5-dataset-info"], True)


def test_library_members_operation_equals_the_design_literal_with_ask_off():
    doc, _ = six_tool_document(OFF)
    ops = operations(doc)
    check_library(ops["tk5-library-members"], ops["tk5-dataset-info"], False)


# --------------------------------------------------------------------------
# More examples
# --------------------------------------------------------------------------

@pytest.mark.parametrize("env", [None, TWO_ENV], ids=["unset", "set"])
def test_offered_equals_the_plan_eligible(env):
    _, app = six_tool_document(env)
    prepared = prepared_for(env)
    offered = app.app.ask.offered
    assert isinstance(offered, frozenset)
    assert offered == prepared.ask.eligible
    assert offered == (frozenset(TWO) if env else frozenset(SIX))


def test_a_flow_with_an_empty_example_gets_no_member_even_when_offered():
    _, app = six_tool_document()
    registry = dict(prepared_for().registry)
    target = "tk5-time"
    assert target in app.app.ask.offered
    registry[target] = dataclasses.replace(
        registry[target], flow=dataclasses.replace(registry[target].flow, example="")
    )
    doc = build_openapi(registry, _package_version(), app.app.ask)
    ops = operations(doc)
    assert KEY not in ops[target]
    assert {n for n, op in ops.items() if KEY in op} == set(SIX) - {target}


def test_the_document_is_built_once_and_is_pure_in_its_inputs(monkeypatch):
    doc, app = six_tool_document()
    registry = prepared_for().registry
    first = fetch_document(app)[1]
    # a later environment change does not alter the served document
    monkeypatch.setenv("GS_ASK_FLOWS", "tk5-time")
    monkeypatch.setenv("GS_ENABLE_ASK", "false")
    second = fetch_document(app)[1]
    assert first == second
    assert json.loads(first) == doc
    assert build_openapi(registry, _package_version(), app.app.ask) == doc

    # the function itself: another offered set gives another document
    other = SimpleNamespace(
        offered=frozenset({"tk5-time"}),
        max_question_chars=app.app.ask.max_question_chars,
        max_answer_chars=app.app.ask.max_answer_chars,
    )
    changed = build_openapi(registry, _package_version(), other)
    assert changed != doc
    assert sum(1 for k in walk_keys(changed) if k == KEY) == 1
    assert build_openapi(registry, _package_version(), other) == changed


@pytest.mark.parametrize("env", [OFF, None, TWO_ENV], ids=["off", "on", "two"])
def test_no_default_example_const_or_enum_in_the_flow_parts(env):
    doc, _ = six_tool_document(env)
    # the Ask schemas ("/ask" and the three Ask schemas) use ``const`` for their own unions
    parts = [op for op in operations(doc).values()]
    parts.append(doc["components"]["schemas"]["ErrorBody"])
    parts.append(doc["components"]["securitySchemes"])
    parts.append(doc["paths"]["/health"])
    assert FORBIDDEN.isdisjoint(set(walk_keys(parts)))


def test_the_mcp_tools_are_unchanged_by_the_example():
    _, app = six_tool_document()
    registry = prepared_for().registry

    async def go():
        async with mcp_client(app.app, "auto") as client:
            return {t.name: t for t in (await client.list_tools()).tools}

    tools = asyncio.run(go())
    assert set(tools) == set(SIX)
    for name in SIX:
        published = registry[name]
        input_schema, _output, success = build_schemas(published.flow, published.bound_names)
        tool = tools[name]
        assert tool.description == published.summary
        assert tool.input_schema == input_schema
        assert tool.output_schema == success
        assert published.flow.example not in json.dumps(tool.model_dump(mode="json"))


def test_the_error_bodies_are_the_same_with_ask_on_and_off():
    async def bodies(env):
        app = build_ask_app(six_tool_overrides(env))
        async with rest_client(app.app, headers={"X-API-Key": app.api_key}) as client:
            results = [
                await client.post("/flows/tk5-dataset-info", json={"dsname": "A..B"}),
                await client.post("/flows/tk5-dataset-info", json={}),
                await client.post("/flows/no-such-flow", json={}),
            ]
        return [(r.status_code, r.json()) for r in results]

    on = asyncio.run(bodies(None))
    off = asyncio.run(bodies(OFF))
    assert on == off
    assert [status for status, _ in on][:2] == [422, 422]


def test_no_example_text_reaches_the_log(caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    unique = {"GS_ASK_MAX_QUESTION_CHARS": "1234"}  # a fresh ``prepare``: startup is logged too

    async def go():
        app = build_ask_app(six_tool_overrides(unique))
        async with rest_client(app.app, headers={"X-API-Key": app.api_key}) as client:
            return await client.post("/flows/tk5-system-info", json={})

    response = asyncio.run(go())
    assert response.status_code == 200
    text = caplog.text
    for example in examples_of().values():
        assert example not in text
