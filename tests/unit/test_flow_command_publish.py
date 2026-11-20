"""Publisher shapes of the five Command_Flows (more-flows, task 9.1). No live host.

The eight bundled Flows are published through the real registry and ``build_app`` on a
Fake_Host. The user id and password below are made-up values bound by environment
variables, as for the Ask plan; they are not credentials.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.publisher.app import build_app, prepare

from tests.command_flow_support import command_flow_states
from tests.dsname_support import DSNAME_SPEC
from tests.flow_support import FakeClock
from tests.publisher_support import FakeHost, mcp_client, rest_client

API_KEY = "PRBK-api-key-0123456789"
BOUND_USER = "PRBU7Q2X"
BOUND_PASS = "PRBB5M8W"
HEADERS = {"X-API-Key": API_KEY}

EIGHT = (
    "tk5-logon", "tk5-logoff", "tk5-system-info", "tk5-time", "tk5-list-datasets",
    "tk5-dataset-info", "tk5-library-members", "tk5-job-status",
)
NAME_FLOWS = ("tk5-dataset-info", "tk5-library-members")
NO_INPUT_FLOWS = ("tk5-time", "tk5-list-datasets", "tk5-job-status")
FIVE = EIGHT[3:]
OUTPUTS = {
    "tk5-time": {"TIME_TEXT": {"type": "string"}},
    "tk5-list-datasets": {"DATASETS": {"type": "string"}},
    "tk5-dataset-info": {"FOUND": {"type": "integer"}, "DETAILS": {"type": "string"}},
    "tk5-library-members": {"MEMBERS": {"type": "string"}},
    "tk5-job-status": {"JOBS": {"type": "string"}},
}
AUDIT_MEMBERS = {
    "step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds",
}
MEMBER_PAGES = ["tso-listds-members"] + [f"tso-listds-members-page{i}" for i in range(2, 8)]


def _env() -> dict[str, str]:
    env = {
        "GS_S3270_BINARY": "s3270",
        "GS_HOST": "host.invalid",
        "GS_API_KEY": API_KEY,
    }
    for name in FIVE:
        stem = "GS_BIND_" + name.upper().replace("-", "_")
        env[f"{stem}__USERID"] = BOUND_USER
        env[f"{stem}__PASSWORD"] = BOUND_PASS
    return env


def _app(script):
    host = FakeHost(script)
    app = build_app(prepare(_env()), session_factory=host, clock=FakeClock(), poll_interval=0.01)
    return app, host


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def shapes():
    """OpenAPI document, MCP tools and flow descriptions from one real app."""
    app, host = _app([])

    async def go():
        async with rest_client(app, headers=HEADERS) as c:
            doc = (await c.get("/openapi.json")).json()
            async with mcp_client(app, "auto") as m:
                tools = (await m.list_tools()).tools
        return doc, tools

    doc, tools = _run(go())
    assert host.factory_calls == 0
    return doc, {t.name: t for t in tools}, load_bundled_flows()


def _op(doc, name):
    return doc["paths"][f"/flows/{name}"]["post"]


def _request_schema(doc, name):
    return _op(doc, name)["requestBody"]["content"]["application/json"]["schema"]


def test_all_eight_flows_are_published(shapes):
    doc, tools, flows = shapes
    assert tuple(tools) == EIGHT
    assert tuple(flows) == EIGHT
    assert {p for p in doc["paths"] if p.startswith("/flows/")} == {f"/flows/{n}" for n in EIGHT}


@pytest.mark.parametrize("name", NAME_FLOWS)
def test_name_flows_take_a_bounded_dsname(shapes, name):
    doc, tools, _ = shapes
    expected = {
        "type": "object",
        "properties": {
            "dsname": {
                "type": "string",
                "maxLength": 44,
                "pattern": f"^(?:{DSNAME_SPEC.regex})$",
                "description": DSNAME_SPEC.description,
            }
        },
        "required": ["dsname"],
        "additionalProperties": False,
    }
    rest = _request_schema(doc, name)
    assert rest == expected
    assert tools[name].input_schema == expected
    assert rest["properties"]["dsname"]["maxLength"] == 44
    assert "userid" not in json.dumps(rest) and "password" not in json.dumps(rest)


@pytest.mark.parametrize("name", NO_INPUT_FLOWS)
def test_other_flows_take_no_input(shapes, name):
    doc, tools, _ = shapes
    expected = {"type": "object", "properties": {}, "additionalProperties": False}
    assert _request_schema(doc, name) == expected
    assert tools[name].input_schema == expected


@pytest.mark.parametrize("name", FIVE)
def test_output_schemas(shapes, name):
    doc, tools, _ = shapes
    want = OUTPUTS[name]
    rest = _op(doc, name)["responses"]["200"]["content"]["application/json"]["schema"]
    assert rest["properties"]["outputs"]["properties"] == want
    assert list(rest["properties"]["outputs"]["required"]) == list(want)
    assert rest["properties"]["outputs"]["additionalProperties"] is False
    mcp = tools[name].output_schema
    assert mcp == rest
    assert set(mcp["properties"]) == {"flow", "outputs", "audit"}
    # a multi-line output is one string, a flag is an integer
    types = {k: v["type"] for k, v in mcp["properties"]["outputs"]["properties"].items()}
    assert all(t == "string" for k, t in types.items() if k != "FOUND")
    if name == "tk5-dataset-info":
        assert types["FOUND"] == "integer"


@pytest.mark.parametrize("name", EIGHT)
def test_audit_item_schema_is_unchanged(shapes, name):
    _, tools, _ = shapes
    item = tools[name].output_schema["properties"]["audit"]["items"]
    assert set(item["properties"]) == AUDIT_MEMBERS
    assert len(item["properties"]) == 7
    assert item["properties"]["kind"]["type"] == "string"


@pytest.mark.parametrize("name", EIGHT)
def test_description_is_used_unchanged_as_summary_and_tool_description(shapes, name):
    doc, tools, flows = shapes
    assert flows[name].description
    assert _op(doc, name)["summary"] == flows[name].description
    assert tools[name].description == flows[name].description


def test_library_members_rest_call_over_seven_real_pages():
    app, host = _app(command_flow_states(MEMBER_PAGES))

    async def go():
        async with rest_client(app, headers=HEADERS) as c:
            return await c.post("/flows/tk5-library-members", json={"dsname": "SYS2.JCLLIB"})

    resp = _run(go())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    members = body["outputs"]["MEMBERS"]
    assert len(members.split("\n")) == 136
    assert len(members) == 1145
    collects = [a for a in body["audit"] if a["kind"] == "collect"]
    assert len(collects) == 1 and collects[0]["status"] == "ok"
    assert host.factory_calls == 1
    assert BOUND_PASS not in resp.text and BOUND_USER not in resp.text


def test_bad_dsname_is_422_input_invalid_and_never_reaches_the_host():
    app, host = _app(command_flow_states(MEMBER_PAGES))

    async def go():
        async with rest_client(app, headers=HEADERS) as c:
            return [
                await c.post(f"/flows/{n}", json={"dsname": "A..B"}) for n in NAME_FLOWS
            ]

    for resp in _run(go()):
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "input_invalid"
        assert "A..B" not in resp.text
    assert host.factory_calls == 0


@pytest.mark.parametrize("name", NO_INPUT_FLOWS)
def test_extra_input_is_rejected_for_flows_without_inputs(name):
    app, host = _app([])

    async def go():
        async with rest_client(app, headers=HEADERS) as c:
            return await c.post(f"/flows/{name}", json={"dsname": "SYS2.JCLLIB"})

    resp = _run(go())
    assert resp.status_code == 422
    assert host.factory_calls == 0
