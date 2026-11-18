"""MCP front end tests: in-memory ``Client`` in both protocol eras (Requirement 14).

The Fake_Host serves every call; no live host and no loader patching. The Probe_Value
is made up.
"""
from __future__ import annotations

import asyncio
import contextlib
import json

import httpx2
import pytest
from mcp import Client
from starlette.applications import Starlette
from starlette.routing import Route

from greenscreen.publisher.calls import CallOutcome, CallService, Limiter
from greenscreen.publisher.config import load_settings
from greenscreen.publisher.mcp_server import build_manager, build_mcp_server
from greenscreen.publisher.registry import build_registry, load_flows
from greenscreen.publisher.vault import BoundValues
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import FakeClock
from tests.publisher_support import MINI, FakeHost, mini_states

SIGS = load_bundled_signatures()
PROBE = "PRB7Q2XZ"
MODES = ["legacy", "auto"]


def make_service(host, registry):
    return CallService(
        registry, BoundValues(), SIGS, Limiter(1), host,
        call_timeout=30.0, shutdown_grace=1.0, clock=FakeClock(),
    )


def bundled_registry():
    loaded = load_flows(None)
    return build_registry(loaded, BoundValues(), 30.0)


def mini_registry():
    return build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)


def run_client(server, mode, action):
    async def go():
        async with Client(server, mode=mode) as client:
            return await action(client)

    return asyncio.run(go())


@pytest.mark.parametrize("mode", MODES)
def test_tools_list_equals_generator_output(mode):
    registry = bundled_registry()
    host = FakeHost(mini_states())
    server = build_mcp_server(make_service(host, registry), registry)
    result = run_client(server, mode, lambda c: c.list_tools())
    assert [t.name for t in result.tools] == list(registry)
    for tool in result.tools:
        p = registry[tool.name]
        assert tool.description == p.summary
        assert tool.input_schema == p.input_schema
        assert tool.output_schema == p.success_schema
    assert host.factory_calls == 0
    assert "cancelled" not in json.dumps([t.model_dump(mode="json") for t in result.tools])


@pytest.mark.parametrize("mode", MODES)
def test_call_success_returns_structured_and_text(mode):
    registry = mini_registry()
    host = FakeHost(mini_states())
    server = build_mcp_server(make_service(host, registry), registry)
    res = run_client(server, mode, lambda c: c.call_tool("mini", {"userid": PROBE}))
    assert res.is_error is False
    body = res.structured_content
    assert body["flow"] == "mini" and set(body) == {"flow", "outputs", "audit"}
    assert set(body["outputs"]) == {"RELEASE"}
    assert len(res.content) == 1 and json.loads(res.content[0].text) == body
    assert PROBE not in json.dumps(body)
    assert host.created == 1 and host.closed == 1


@pytest.mark.parametrize("mode", MODES)
def test_call_flow_stop_is_error_result_with_error_body(mode):
    registry = mini_registry()
    host = FakeHost(list(reversed(mini_states())))  # the menu first: the Flow stops
    server = build_mcp_server(make_service(host, registry), registry)
    res = run_client(server, mode, lambda c: c.call_tool("mini", {"userid": PROBE}))
    assert res.is_error is True
    err = res.structured_content["error"]
    assert err["code"] in {"unexpected_screen", "unknown_screen", "timeout"}
    assert json.loads(res.content[0].text) == res.structured_content
    assert PROBE not in json.dumps(res.structured_content)
    assert "cancelled" not in json.dumps(res.structured_content)


@pytest.mark.parametrize("mode", MODES)
def test_invalid_arguments_give_input_invalid_without_a_session(mode):
    registry = mini_registry()
    host = FakeHost(mini_states())
    server = build_mcp_server(make_service(host, registry), registry)
    res = run_client(
        server, mode, lambda c: c.call_tool("mini", {"userid": PROBE, "count": PROBE})
    )
    assert res.is_error is True
    assert res.structured_content["error"]["code"] == "input_invalid"
    assert PROBE not in json.dumps(res.structured_content)
    assert PROBE not in res.content[0].text
    assert host.factory_calls == 0


@pytest.mark.parametrize("mode", MODES)
def test_missing_arguments_object_is_handled(mode):
    registry = mini_registry()
    host = FakeHost(mini_states())
    server = build_mcp_server(make_service(host, registry), registry)
    res = run_client(server, mode, lambda c: c.call_tool("mini"))
    assert res.is_error is True
    assert res.structured_content["error"]["code"] == "input_invalid"


@pytest.mark.parametrize("mode", MODES)
def test_unknown_and_unpublished_tools_give_the_same_unknown_flow_result(mode):
    # tk5-logon is loaded but not published: only "mini" is in the registry
    registry = mini_registry()
    host = FakeHost(mini_states())
    server = build_mcp_server(make_service(host, registry), registry)

    async def act(client):
        listing = await client.list_tools()
        a = await client.call_tool("tk5-logon", {"userid": PROBE})
        b = await client.call_tool("no-such-flow", {"userid": PROBE})
        return listing, a, b

    listing, a, b = run_client(server, mode, act)
    assert [t.name for t in listing.tools] == ["mini"]
    assert a.is_error and b.is_error
    assert a.structured_content == b.structured_content
    assert a.structured_content["error"]["code"] == "unknown_flow"
    assert PROBE not in json.dumps(a.structured_content)
    assert host.factory_calls == 0


@pytest.mark.parametrize("mode", MODES)
def test_no_resource_or_prompt_capability(mode):
    registry = mini_registry()
    server = build_mcp_server(make_service(FakeHost(mini_states()), registry), registry)

    async def act(client):
        caps = client.server_capabilities
        return caps, await client.list_tools()

    caps, _ = run_client(server, mode, act)
    assert caps.tools is not None
    assert caps.resources is None
    assert caps.prompts is None


@pytest.mark.parametrize("mode", MODES)
def test_exception_in_the_call_path_becomes_internal_error(mode, caplog):
    registry = mini_registry()
    service = make_service(FakeHost(mini_states()), registry)

    async def boom(*args, **kwargs):
        raise RuntimeError("boom " + PROBE)

    service.execute = boom  # the handler must catch every Exception
    server = build_mcp_server(service, registry)
    res = run_client(server, mode, lambda c: c.call_tool("mini", {"userid": PROBE}))
    assert res.is_error is True
    assert res.structured_content["error"]["code"] == "internal_error"
    assert PROBE not in json.dumps(res.structured_content)
    assert PROBE not in res.content[0].text
    for record in caplog.records:
        assert PROBE not in record.getMessage()
        assert record.exc_info is None


def test_cancelled_cannot_be_a_call_outcome():
    with pytest.raises(ValueError):
        CallOutcome("cancelled", {})


def test_manager_is_stateless_json_and_caps_the_body():
    env = {
        "GS_HOST": "localhost",
        "GS_S3270_BINARY": "s3270-not-run",
        "GS_API_KEY": "k" * 20,
        "GS_MAX_BODY_BYTES": "1024",
    }
    settings = load_settings(env)
    registry = mini_registry()
    host = FakeHost(mini_states())
    server = build_mcp_server(make_service(host, registry), registry)
    manager = build_manager(server, settings)

    from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    app = Starlette(routes=[Route("/mcp", StreamableHTTPASGIApp(manager))], lifespan=lifespan)

    async def go():
        async with lifespan(app):
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://localhost") as c:
                return await c.post(
                    "/mcp",
                    content=b"x" * 5000 + PROBE.encode(),
                    headers={
                        "content-type": "application/json",
                        "accept": "application/json, text/event-stream",
                    },
                )

    resp = asyncio.run(go())
    assert resp.status_code == 413
    assert PROBE not in resp.text
    assert host.factory_calls == 0
