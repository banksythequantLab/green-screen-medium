"""The whole publisher stack (task 5.5): CrashGuard(AuthMiddleware(FastAPI)) with ``/mcp``.

Everything runs through the real ASGI stack on the Fake_Host. The key, the user id and
the bound password below are made-up Probe_Values, not credentials. No live host, no
loader patching, no network.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.calls import HTTP_STATUS, error_body
from greenscreen.publisher.config import StartupError
from tests.flow_support import FakeClock
from tests.publisher_support import FakeHost, system_info_states

API_KEY = "PRBK-api-key-0123456789"
USERID = "PRBU7Q2X"
BOUND = "PRBB5M8W"
FLOW = "tk5-system-info"
BIND_VAR = "GS_BIND_TK5_SYSTEM_INFO__PASSWORD"
JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": API_KEY,
    "GS_PUBLISH_FLOWS": FLOW,
    "GS_ENABLE_DOCS": "true",
    BIND_VAR: BOUND,
}
CARRIERS = {
    "x-api-key": {"X-API-Key": API_KEY},
    "bearer": {"Authorization": f"Bearer {API_KEY}"},
    "both": {"X-API-Key": API_KEY, "Authorization": f"Bearer {API_KEY}"},
}
SECRETS = (API_KEY, BOUND)


def make(env=None, script=None):
    host = FakeHost(script or system_info_states())
    app = build_app(prepare(env or ENV), session_factory=host, clock=FakeClock(), poll_interval=0.01)
    return app, host


@contextlib.asynccontextmanager
async def running(app, headers=None, base_url="http://test"):
    async with app.lifespan():
        transport = httpx2.ASGITransport(app=app.asgi)
        async with httpx2.AsyncClient(transport=transport, base_url=base_url, headers=headers) as c:
            yield c


@contextlib.asynccontextmanager
async def mcp_client(http, mode, base="http://test"):
    async with Client(streamable_http_client(f"{base}/mcp", http_client=http), mode=mode) as c:
        yield c


def jsonrpc(method, params=None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def run(coro):
    return asyncio.run(coro)


def unauthorized_body():
    return error_body("unauthorized")


def assert_no_secret(*texts):
    for text in texts:
        for secret in SECRETS:
            assert secret not in text


# --------------------------------------------------------------------------
# Auth over every route and /mcp
# --------------------------------------------------------------------------

ROUTES = [
    ("POST", f"/flows/{FLOW}", {"userid": USERID}),
    ("POST", "/flows/no-such-flow", {}),
    ("GET", "/openapi.json", None),
    ("GET", "/docs", None),
    ("GET", "/nope", None),
    ("POST", "/mcp", jsonrpc("tools/list")),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_route_and_mcp_answer_unauthorized_without_a_key(method, path, body):
    app, host = make()

    async def go():
        async with running(app) as c:
            plain = await c.request(method, path, json=body, headers=JSON_HEADERS if body else None)
            wrong = await c.request(
                method, path, json=body, headers={**(JSON_HEADERS if body else {}), "X-API-Key": "x" * 22}
            )
            return plain, wrong

    plain, wrong = run(go())
    for resp in (plain, wrong):
        assert resp.status_code == 401
        assert resp.json() == unauthorized_body()
    assert host.factory_calls == 0


@pytest.mark.parametrize("carrier", CARRIERS)
@pytest.mark.parametrize("method,path,body", [r for r in ROUTES if r[2] != {} and r[1] != "/nope"])
def test_every_route_opens_with_either_key_carrier(carrier, method, path, body):
    app, host = make()

    async def go():
        async with running(app, headers=CARRIERS[carrier]) as c:
            return await c.request(method, path, json=body, headers=JSON_HEADERS if body else None)

    resp = run(go())
    assert resp.status_code == 200, resp.text
    assert resp.text != json.dumps(unauthorized_body())
    assert resp.text.replace(" ", "") != json.dumps(unauthorized_body()).replace(" ", "")
    assert_no_secret(resp.text)


def test_unknown_path_with_a_key_is_request_invalid_not_unauthorized():
    app, _ = make()

    async def go():
        async with running(app, headers=CARRIERS["bearer"]) as c:
            return await c.get("/nope")

    resp = run(go())
    assert resp.status_code == 400 and resp.json()["error"]["code"] == "request_invalid"


def test_health_is_open_with_and_without_a_key():
    app, host = make()

    async def go():
        async with running(app) as c:
            anon = await c.get("/health")
            wrong = await c.get("/health", headers={"X-API-Key": "bad"})
            post = await c.post("/health")  # only GET /health is open
            return anon, wrong, post

    anon, wrong, post = run(go())
    assert anon.status_code == 200 and anon.json() == {"status": "ok", "flows": 1}
    assert wrong.status_code == 200
    assert post.status_code == 401
    assert host.factory_calls == 0


# --------------------------------------------------------------------------
# Auth disabled (Requirement 13.7: the Host rule covers every path, /health too)
# --------------------------------------------------------------------------

DISABLED = {k: v for k, v in ENV.items() if k != "GS_API_KEY"} | {"GS_AUTH_DISABLED": "true"}


def test_auth_disabled_needs_no_key_on_a_loopback_host():
    app, host = make(DISABLED)

    async def go():
        async with running(app, base_url="http://127.0.0.1") as c:
            rest = await c.post(f"/flows/{FLOW}", json={"userid": USERID})
            doc = await c.get("/openapi.json")
            async with mcp_client(c, "auto", "http://127.0.0.1") as m:
                tools = (await m.list_tools()).tools
            return rest, doc, tools

    rest, doc, tools = run(go())
    assert rest.status_code == 200 and doc.status_code == 200
    assert [t.name for t in tools] == [FLOW]


@pytest.mark.parametrize("path", ["/health", "/openapi.json", "/mcp"])
def test_auth_disabled_rejects_a_foreign_host_on_every_path_including_health(path):
    app, host = make(DISABLED)

    async def go():
        async with running(app, base_url="http://evil.example") as c:
            if path == "/mcp":
                return await c.post(path, json=jsonrpc("tools/list"), headers=JSON_HEADERS)
            return await c.get(path)

    resp = run(go())
    assert resp.status_code == 401 and resp.json() == unauthorized_body()
    assert host.factory_calls == 0


def test_auth_disabled_with_a_non_loopback_publish_host_stops_the_startup():
    with pytest.raises(StartupError) as info:
        prepare({**DISABLED, "GS_PUBLISH_HOST": "0.0.0.0"})
    assert "GS_AUTH_DISABLED" in str(info.value) and BOUND not in str(info.value)


# --------------------------------------------------------------------------
# MCP over HTTP, both protocol eras, with the key
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["legacy", "auto"])
@pytest.mark.parametrize("carrier", ["x-api-key", "bearer"])
def test_mcp_over_http_with_the_key_in_both_eras(mode, carrier, caplog):
    caplog.set_level(logging.DEBUG)
    app, host = make()

    async def go():
        async with running(app, headers=CARRIERS[carrier]) as c:
            async with mcp_client(c, mode) as m:
                tools = (await m.list_tools()).tools
                result = await m.call_tool(FLOW, {"userid": USERID})
            return tools, result

    tools, result = run(go())
    assert [t.name for t in tools] == [FLOW]
    assert result.is_error is False
    assert result.structured_content["flow"] == FLOW
    assert host.created == 1 and host.closed == 1
    assert_no_secret(json.dumps(result.structured_content), result.content[0].text, caplog.text)


@pytest.mark.parametrize("mode", ["legacy", "auto"])
def test_mcp_over_http_without_a_key_does_not_connect(mode):
    app, host = make()

    async def go():
        async with running(app) as c:
            async with mcp_client(c, mode) as m:
                await m.list_tools()

    with pytest.raises(BaseException):  # the SDK client raises its own error type or a group
        run(go())
    assert host.factory_calls == 0


def test_oversize_mcp_body_gets_plain_text_413_and_opens_no_session():
    env = {**ENV, "GS_MAX_BODY_BYTES": "1024"}
    app, host = make(env)
    marker = "PRBX" * 600
    body = jsonrpc("tools/call", {"name": FLOW, "arguments": {"userid": marker}})

    async def go():
        async with running(app, headers=CARRIERS["x-api-key"]) as c:
            big = await c.post("/mcp", json=body, headers=JSON_HEADERS)
            # the same limit does not reject a small request
            small = await c.post("/mcp", json=jsonrpc("tools/list"), headers=JSON_HEADERS)
            return big, small

    big, small = run(go())
    assert big.status_code == 413
    assert "json" not in big.headers.get("content-type", "")
    assert big.text and not big.text.lstrip().startswith(("{", "["))  # plain text, not an Error_Body
    assert marker[:8] not in big.text and API_KEY not in big.text
    assert small.status_code == 200
    assert host.factory_calls == 0


# --------------------------------------------------------------------------
# Bound inputs
# --------------------------------------------------------------------------

def test_bound_inputs_are_absent_from_schemas_tools_and_openapi():
    app, _ = make()

    async def go():
        async with running(app, headers=CARRIERS["bearer"]) as c:
            doc = (await c.get("/openapi.json")).json()
            async with mcp_client(c, "auto") as m:
                tools = (await m.list_tools()).tools
            return doc, tools

    doc, tools = run(go())
    schema = doc["paths"][f"/flows/{FLOW}"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert "userid" in schema["properties"] and "password" not in schema["properties"]
    assert "password" not in schema.get("required", [])
    assert "password" not in json.dumps(schema)
    (tool,) = tools
    assert "password" not in tool.input_schema["properties"]
    assert tool.input_schema == schema
    assert_no_secret(json.dumps(doc), json.dumps(tool.input_schema))


def test_bound_value_is_merged_at_call_time_and_typed_into_the_host(caplog):
    caplog.set_level(logging.DEBUG)
    app, host = make()
    seen: list[str] = []

    async def go():
        async with running(app, headers=CARRIERS["x-api-key"]) as c:
            rest = await c.post(f"/flows/{FLOW}", json={"userid": USERID})
            async with mcp_client(c, "auto") as m:
                mcp = await m.call_tool(FLOW, {"userid": USERID})
            seen.extend([rest.text, json.dumps(mcp.structured_content), mcp.content[0].text])
            return rest, mcp

    rest, mcp = run(go())
    assert rest.status_code == 200 and mcp.is_error is False
    assert rest.json() == mcp.structured_content
    assert host.created == 2
    for session in host.sessions:
        typed = [c[1] for c in session.calls if c[0] == "string"]
        assert USERID in typed and BOUND in typed  # the Bound_Value reached run_flow
    assert_no_secret(*seen, caplog.text)
    assert USERID not in caplog.text


@pytest.mark.parametrize("via", ["rest", "mcp"])
def test_supplying_a_bound_name_is_input_invalid_with_no_echo(via, caplog):
    caplog.set_level(logging.DEBUG)
    app, host = make()
    supplied = "PRBS3N6T"
    body = {"userid": USERID, "password": supplied}

    async def go():
        async with running(app, headers=CARRIERS["bearer"]) as c:
            if via == "rest":
                resp = await c.post(f"/flows/{FLOW}", json=body)
                return resp.status_code, resp.json(), resp.text
            async with mcp_client(c, "auto") as m:
                res = await m.call_tool(FLOW, body)
            return None, res.structured_content, res.content[0].text

    status, payload, text = run(go())
    if via == "rest":
        assert status == HTTP_STATUS["input_invalid"]
    assert payload["error"]["code"] == "input_invalid"
    assert host.factory_calls == 0
    for dump in (json.dumps(payload), text, caplog.text):
        assert_no_secret(dump)
        assert supplied not in dump and USERID not in dump


# --------------------------------------------------------------------------
# GS_PUBLISH_FLOWS demo setting
# --------------------------------------------------------------------------

OTHERS = ("tk5-logon", "tk5-logoff")


def test_demo_setting_publishes_only_the_system_info_flow():
    env = {k: v for k, v in ENV.items() if k != BIND_VAR}
    app, host = make(env)

    async def go():
        async with running(app, headers=CARRIERS["x-api-key"]) as c:
            health = (await c.get("/health")).json()
            doc = (await c.get("/openapi.json")).json()
            unknown = await c.post("/flows/no-such-flow", json={})
            rest = [await c.post(f"/flows/{n}", json={}) for n in OTHERS]
            async with mcp_client(c, "auto") as m:
                tools = (await m.list_tools()).tools
                unk_mcp = await m.call_tool("no-such-flow", {})
                mcp = [await m.call_tool(n, {}) for n in OTHERS]
            return health, doc, unknown, rest, tools, unk_mcp, mcp

    health, doc, unknown, rest, tools, unk_mcp, mcp = run(go())
    assert health == {"status": "ok", "flows": 1}
    assert [p for p in doc["paths"] if p.startswith("/flows/")] == [f"/flows/{FLOW}"]
    assert [t.name for t in tools] == [FLOW]
    for name in OTHERS:
        assert name not in json.dumps(doc) and name not in [t.name for t in tools]
    for resp in rest:
        assert resp.status_code == unknown.status_code == 404
        assert resp.json() == unknown.json() and resp.json()["error"]["code"] == "unknown_flow"
    for res in mcp:
        assert res.is_error and res.structured_content == unk_mcp.structured_content
        assert res.structured_content["error"]["code"] == "unknown_flow"
    assert host.factory_calls == 0


def test_unset_publish_list_publishes_all_eight_flows():
    env = {k: v for k, v in ENV.items() if k not in ("GS_PUBLISH_FLOWS", BIND_VAR)}
    app, _ = make(env)

    async def go():
        async with running(app, headers=CARRIERS["x-api-key"]) as c:
            health = (await c.get("/health")).json()
            doc = (await c.get("/openapi.json")).json()
            async with mcp_client(c, "auto") as m:
                tools = (await m.list_tools()).tools
            return health, doc, tools

    health, doc, tools = run(go())
    assert health["flows"] == 8
    assert len([p for p in doc["paths"] if p.startswith("/flows/")]) == 8
    assert len(tools) == 8


def test_binding_a_flow_the_list_leaves_out_stops_the_startup():
    env = {**ENV, "GS_BIND_TK5_LOGON__PASSWORD": BOUND}
    with pytest.raises(StartupError) as info:
        prepare(env)
    assert "flow_not_published" in str(info.value) and BOUND not in str(info.value)
