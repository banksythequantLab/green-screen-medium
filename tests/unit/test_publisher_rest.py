"""REST routes of the publisher (task 3.1), through an ASGI client. No live host.

The MCP route gets a dummy ASGI app: the MCP server is task 3.2. Auth, the crash
guard and the replaced framework handlers are later tasks and are not tested here.
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import httpx2
import pytest

from greenscreen.publisher.calls import CallService, Limiter
from greenscreen.publisher.config import load_settings
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.rest import build_rest
from greenscreen.publisher.vault import BoundValues
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import FakeClock, ScriptedState, capture
from tests.publisher_support import MINI, FakeHost, mini_states

SIGS = load_bundled_signatures()
PROBE = "PRB7Q2XZ"  # a made-up userid value, never a real one
LIMIT = 2048

ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_MAX_BODY_BYTES": str(LIMIT),
}


async def _dummy_mcp(scope, receive, send):  # pragma: no cover - never reached
    raise AssertionError("the MCP route is not exercised here")


class _Boom:
    """A factory that fails the test when it is called."""

    calls = 0

    def __call__(self):
        _Boom.calls += 1
        raise AssertionError("session factory must not be called")


def make_app(factory, flows=None):
    flows = flows or {"mini": MINI}
    registry = build_registry({n: (f, "test") for n, f in flows.items()}, BoundValues(), 30.0)
    service = CallService(
        registry, BoundValues(), SIGS, Limiter(1), factory,
        call_timeout=30.0, shutdown_grace=1.0, clock=FakeClock(),
    )
    return build_rest(service, registry, load_settings(ENV), _dummy_mcp)


def run(app, fn: Callable):
    async def go():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as client:
            return await fn(client)

    return asyncio.run(go())


def post(app, content, headers=None, name="mini"):
    hdrs = {"content-type": "application/json"} if headers is None else headers
    return run(app, lambda c: c.post(f"/flows/{name}", content=content, headers=hdrs))


def assert_error(resp, status, code):
    assert resp.status_code == status
    body = resp.json()
    assert set(body) == {"error"}
    assert body["error"]["code"] == code
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["content-type"].startswith("application/json")


@pytest.fixture(autouse=True)
def _reset_boom():
    _Boom.calls = 0


# -- success and Flow stop -------------------------------------------------


def test_success_runs_mini_flow():
    host = FakeHost(mini_states())
    resp = post(make_app(host), json.dumps({"userid": PROBE}))
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"flow", "outputs", "audit"}
    assert body["flow"] == "mini"
    assert set(body["outputs"]) == {"RELEASE"}
    assert PROBE not in resp.text
    assert resp.headers["cache-control"] == "no-store"
    assert host.created == 1 and host.closed == 1


def test_flow_stop_is_an_error_body_with_502():
    states = [ScriptedState(capture("tk5-logon")), ScriptedState(capture("tso-ready"))]
    host = FakeHost(states)
    resp = post(make_app(host), json.dumps({"userid": PROBE}))
    assert resp.status_code == 502
    err = resp.json()["error"]
    assert err["code"] in {"unexpected_screen", "unknown_screen"}
    assert {"step_index", "kind", "expected", "summary", "audit"} <= set(err)
    assert PROBE not in resp.text
    assert host.closed == 1


def test_input_invalid_names_rule_not_value():
    resp = post(make_app(_Boom()), json.dumps({"userid": PROBE + "TOOLONGFORIT"}))
    assert_error(resp, 422, "input_invalid")
    assert PROBE not in resp.text
    assert _Boom.calls == 0


# -- request shape ---------------------------------------------------------


def test_wrong_media_type():
    resp = post(make_app(_Boom()), json.dumps({"userid": PROBE}), {"content-type": "text/plain"})
    assert_error(resp, 400, "request_invalid")
    resp = post(make_app(_Boom()), json.dumps({"userid": PROBE}), {})
    assert_error(resp, 400, "request_invalid")
    assert _Boom.calls == 0


def test_media_type_parameters_accepted():
    host = FakeHost(mini_states())
    hdrs = {"content-type": "Application/JSON; charset=utf-8"}
    resp = post(make_app(host), json.dumps({"userid": PROBE}), hdrs)
    assert resp.status_code == 200


@pytest.mark.parametrize(
    "body",
    [
        b'{"userid": "' + PROBE.encode() + b'"',  # malformed
        b'{"userid": "A", "userid": "' + PROBE.encode() + b'"}',  # duplicate key
        b'{"count": NaN}',
        b'{"count": Infinity}',
        b'{"count": -Infinity}',
        b'["' + PROBE.encode() + b'"]',  # array body
        b'"' + PROBE.encode() + b'"',
        b"",
        b'{"userid": "\xff' + PROBE.encode() + b'"}',  # invalid UTF-8
        b'{"a": {"b": 1, "b": 2}}',  # duplicate key at depth
    ],
)
def test_bad_json_is_request_invalid_without_echo(body):
    resp = post(make_app(_Boom()), body)
    assert_error(resp, 400, "request_invalid")
    assert PROBE not in resp.text
    assert _Boom.calls == 0


@pytest.mark.parametrize("count", ["1.0", "1e3", "true", "false"])
def test_int_input_rejects_float_and_bool(count):
    resp = post(make_app(_Boom()), f'{{"userid": "{PROBE}", "count": {count}}}')
    assert_error(resp, 422, "input_invalid")
    assert _Boom.calls == 0


def test_oversize_with_content_length():
    body = json.dumps({"userid": "x" * (LIMIT + 10)})
    resp = post(make_app(_Boom()), body)
    assert_error(resp, 413, "request_too_large")
    assert _Boom.calls == 0


def test_oversize_chunked_stops_reading_at_the_limit():
    sent: list[int] = []

    async def chunks():
        for _ in range(100):
            sent.append(1)
            yield b" " * 512

    resp = run(
        make_app(_Boom()),
        lambda c: c.post(
            "/flows/mini", content=chunks(), headers={"content-type": "application/json"}
        ),
    )
    assert_error(resp, 413, "request_too_large")
    assert _Boom.calls == 0
    assert len(sent) < 100  # the rest of the body was not pulled


# -- unknown flows ---------------------------------------------------------


def test_unpublished_loaded_flow_looks_like_unknown_name():
    # only "mini" is published; the bundled "tk5-logoff" is loaded but left out
    app = make_app(_Boom())
    left_out = post(app, json.dumps({}), name="tk5-logoff")
    unknown = post(app, json.dumps({}), name="no-such-flow")
    assert_error(left_out, 404, "unknown_flow")
    assert left_out.json() == unknown.json()
    assert _Boom.calls == 0


def test_unknown_flow_is_decided_before_the_body_is_read():
    resp = post(make_app(_Boom()), b"not json at all", {}, name="nope")
    assert_error(resp, 404, "unknown_flow")


# -- /health ---------------------------------------------------------------


def test_health_counts_published_flows_and_never_calls_the_factory():
    app = make_app(_Boom())  # one published flow, however many were loaded
    resp = run(app, lambda c: c.get("/health"))
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "flows": 1}
    assert resp.headers["cache-control"] == "no-store"
    assert _Boom.calls == 0


# -- /mcp route ------------------------------------------------------------


def test_mcp_route_is_the_given_asgi_app():
    seen: list[tuple[str, str]] = []

    async def mcp(scope, receive, send):
        seen.append((scope["method"], scope["path"]))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
    service = CallService(
        registry, BoundValues(), SIGS, Limiter(1), _Boom(),
        call_timeout=30.0, shutdown_grace=1.0, clock=FakeClock(),
    )
    app = build_rest(service, registry, load_settings(ENV), mcp)
    resp = run(app, lambda c: c.post("/mcp", content=b"{}"))
    assert resp.status_code == 204
    assert resp.headers["cache-control"] == "no-store"
    assert seen == [("POST", "/mcp")]
