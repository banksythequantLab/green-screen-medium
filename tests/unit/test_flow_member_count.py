"""``MEMBER_COUNT`` of ``tk5-library-members`` (spec polish, task 5.2; Requirement 15).

Replays the real member-page captures, checks the generated schemas against the
literals of design section 10, calls the Flow over REST and MCP on a Fake_Host,
and checks the Ask projection. No live host.
"""
from __future__ import annotations

import asyncio

import pytest

from greenscreen.flow.model import Flow
from greenscreen.flow.runner import run_flow
from greenscreen.flow.validate import check_flow
from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.ask.service import project_result
from greenscreen.publisher.registry import build_schemas
from greenscreen.recognizer.bundled import load_bundled_signatures

from tests.command_flow_support import (
    INPUTS,
    POLL,
    command_flow_states,
    command_session,
    load_shipped_flow,
)
from tests.flow_support import FakeClock
from tests.publisher_support import FakeHost, mcp_client, rest_client

NAME = "tk5-library-members"
DSN = "SYS2.JCLLIB"
MEMBER_PAGES = ["tso-listds-members"] + [f"tso-listds-members-page{i}" for i in range(2, 8)]

API_KEY = "PRBK-api-key-0123456789"
HEADERS = {"X-API-Key": API_KEY}

AUDIT_PROPS = {
    "step_index": {"type": "integer"},
    "kind": {"type": "string"},
    "phase": {"type": "string"},
    "iteration": {"type": ["integer", "null"]},
    "signature": {"type": ["string", "null"]},
    "status": {"type": "string"},
    "duration_seconds": {"type": "number"},
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"MEMBERS": {"type": "string"}, "MEMBER_COUNT": {"type": "integer"}},
    "additionalProperties": False,
    "required": ["MEMBERS", "MEMBER_COUNT"],
}
SUCCESS_SCHEMA = {
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


def _run_dsn(flow: Flow, session, name: str = DSN):
    return run_flow(
        flow, session, {**INPUTS, "dsname": name}, clock=FakeClock(), poll_interval=POLL
    )


# --- the shipped Flow --------------------------------------------------------

def test_shipped_flow_loads_and_passes_check_flow():
    flow = load_shipped_flow(NAME)
    check_flow(flow, load_bundled_signatures())


def test_outputs_are_members_then_member_count_with_the_same_region():
    members, count = load_shipped_flow(NAME).outputs
    assert (members.name, count.name) == ("MEMBERS", "MEMBER_COUNT")
    assert count.type == "int"
    assert count.counts == "MEMBERS"
    for attr in ("signature", "row", "col", "length"):
        assert getattr(count, attr) == getattr(members, attr)
    assert (count.signature, count.row, count.col, count.length) == ("tso-ready", 7, 3, 8)


# --- replay of the real captures ---------------------------------------------

def test_seven_real_pages_give_member_count_136():
    flow = load_shipped_flow(NAME)
    result = _run_dsn(flow, command_session(MEMBER_PAGES))
    count = result.outputs["MEMBER_COUNT"]
    print("MEMBER_COUNT on the captures:", count)
    assert count == 136
    assert type(count) is int
    assert len(result.outputs["MEMBERS"].split("\n")) == 136


def test_not_in_catalog_gives_count_zero_and_empty_members():
    flow = load_shipped_flow(NAME)
    result = _run_dsn(flow, command_session(["tso-listds-not-in-catalog"]))
    assert result.outputs["MEMBERS"] == ""
    assert result.outputs["MEMBER_COUNT"] == 0
    assert type(result.outputs["MEMBER_COUNT"]) is int


# --- schemas -----------------------------------------------------------------

def test_build_schemas_equals_the_literals_of_the_design():
    _, output_schema, success_schema = build_schemas(load_shipped_flow(NAME))
    assert output_schema == OUTPUT_SCHEMA
    assert success_schema == SUCCESS_SCHEMA


# --- REST and MCP ------------------------------------------------------------

def _env() -> dict[str, str]:
    stem = "GS_BIND_" + NAME.upper().replace("-", "_")
    return {
        "GS_S3270_BINARY": "s3270",
        "GS_HOST": "host.invalid",
        "GS_API_KEY": API_KEY,
        f"{stem}__USERID": "PRBU7Q2X",
        f"{stem}__PASSWORD": "PRBB5M8W",
    }


def _app(script):
    host = FakeHost(script)
    app = build_app(prepare(_env()), session_factory=host, clock=FakeClock(), poll_interval=0.01)
    return app, host


def test_rest_returns_member_count_as_a_json_number():
    app, _host = _app(command_flow_states(MEMBER_PAGES))

    async def go():
        async with rest_client(app, headers=HEADERS) as c:
            return await c.post(f"/flows/{NAME}", json={"dsname": DSN})

    resp = asyncio.run(go())
    assert resp.status_code == 200, resp.text
    outputs = resp.json()["outputs"]
    assert outputs["MEMBER_COUNT"] == 136
    assert type(outputs["MEMBER_COUNT"]) is int
    assert list(outputs) == ["MEMBERS", "MEMBER_COUNT"]
    assert '"MEMBER_COUNT":136' in resp.text.replace(" ", "")


def test_mcp_output_schema_equals_the_rest_200_schema():
    app, _host = _app([])

    async def go():
        async with rest_client(app, headers=HEADERS) as c:
            doc = (await c.get("/openapi.json")).json()
            async with mcp_client(app, "auto") as m:
                tools = (await m.list_tools()).tools
        return doc, {t.name: t for t in tools}

    doc, tools = asyncio.run(go())
    rest = doc["paths"][f"/flows/{NAME}"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert tools[NAME].output_schema == rest
    assert rest == SUCCESS_SCHEMA


# --- the Ask projection ------------------------------------------------------

def test_ask_projection_keeps_an_int_count_and_drops_a_bool():
    body = {"flow": NAME, "outputs": {"MEMBERS": "A\nB", "MEMBER_COUNT": 2}, "audit": []}
    kept = project_result("ok", body)["outputs"]
    assert kept == {"MEMBERS": "A\nB", "MEMBER_COUNT": 2}
    assert type(kept["MEMBER_COUNT"]) is int

    body["outputs"]["MEMBER_COUNT"] = True
    dropped = project_result("ok", body)["outputs"]
    assert "MEMBER_COUNT" not in dropped
    assert dropped == {"MEMBERS": "A\nB"}
