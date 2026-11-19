"""The key check exempts exactly the six console routes (spec console, task 2.11).

Requests go through the real ASGI stack on the Fake_Host with raw scopes, so a path
reaches the middleware as written. The API key is generated per test, never printed.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from greenscreen.publisher.auth import AuthMiddleware
from greenscreen.publisher.calls import error_body
from tests.console_support import EXPECTED_PAIRS, build_console_app, call_scope

UNAUTHORIZED = error_body("unauthorized")
SIX = sorted(EXPECTED_PAIRS)
PATHS = sorted(p for _, p in EXPECTED_PAIRS)
FLOW = "tk5-system-info"


def is_unauthorized(status: int, body: bytes) -> bool:
    return status == 401 and json.loads(body) == UNAUTHORIZED


def call(app, method, path, headers=None):
    return asyncio.run(call_scope(app.app.asgi, method, path, headers))


def test_empty_default_exempts_nothing():
    reached: list[tuple[str, str]] = []

    async def inner(scope, receive, send):
        reached.append((scope["method"], scope["path"]))

    guard = AuthMiddleware(inner, api_key="k" * 16, disabled=False)
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    for method, path in SIX:
        scope = {"type": "http", "method": method, "path": path, "headers": []}
        asyncio.run(guard(scope, receive, send))
    assert reached == []
    assert [m["status"] for m in sent if m["type"] == "http.response.start"] == [401] * 6


@pytest.mark.parametrize("method,path", SIX)
def test_the_six_pairs_pass_without_a_key_when_on(method, path):
    app = build_console_app()
    status, _, body = call(app, method, path)
    assert status == 200
    assert not is_unauthorized(status, body)
    assert app.host.factory_calls == 0


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/console/console.css/"),
        ("GET", "/console/"),
        ("GET", "//"),
        ("GET", "///"),
        ("GET", "/console/console.css?x=1"),
        ("GET", "/?x=1"),
        ("GET", "/console/console.css#a"),
        ("GET", "/CONSOLE/console.css"),
        ("GET", "/console/CONSOLE.CSS"),
        ("GET", "/Console/console.js"),
        ("GET", "/console/../"),
        ("GET", "/console//console.js"),
        ("GET", "/console/console%2ejs"),
        ("GET", "/index.html"),
        ("GET", "/health/"),
        ("get", "/"),
        ("Get", "/console/codes.json"),
    ],
)
def test_comparison_is_exact_for_a_near_miss_path_or_method(method, path):
    app = build_console_app()
    status, _, body = call(app, method, path)
    assert is_unauthorized(status, body)
    assert app.host.factory_calls == 0


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH"])
@pytest.mark.parametrize("path", PATHS)
def test_other_methods_on_a_console_path_need_a_key(method, path):
    app = build_console_app()
    status, _, body = call(app, method, path)
    assert is_unauthorized(status, body)
    assert app.host.factory_calls == 0


def test_a_wrong_key_does_not_change_an_exempt_route_and_a_key_does_not_hurt():
    app = build_console_app()
    for headers in ({"x-api-key": "wrong-key-value"}, {"x-api-key": app.api_key}):
        status, _, _ = call(app, "GET", "/", headers)
        assert status == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", f"/flows/{FLOW}"),
        ("POST", "/flows/no-such-flow"),
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("POST", "/mcp"),
        ("GET", "/mcp"),
        ("GET", "/nope"),
    ],
)
def test_other_routes_stay_protected_with_the_console_on(method, path):
    app = build_console_app({"GS_ENABLE_DOCS": "true"})
    for headers in (None, {"x-api-key": "wrong-key-value"}, {"authorization": "Basic abc"}):
        status, _, body = call(app, method, path, headers)
        assert is_unauthorized(status, body)
    assert app.host.factory_calls == 0


def test_health_stays_open_and_only_for_get():
    app = build_console_app()
    status, _, _ = call(app, "GET", "/health")
    assert status == 200
    status, _, body = call(app, "POST", "/health")
    assert is_unauthorized(status, body)


DISABLED = {"GS_AUTH_DISABLED": "true"}


@pytest.mark.parametrize("method,path", SIX)
@pytest.mark.parametrize("host", ["localhost", "127.0.0.1:8080", "[::1]"])
def test_disabled_auth_serves_console_routes_on_a_loopback_host(method, path, host):
    app = build_console_app(DISABLED)
    status, _, _ = call(app, method, path, {"host": host})
    assert status == 200


@pytest.mark.parametrize("method,path", SIX)
@pytest.mark.parametrize("host", ["evil.example", "203.0.113.7:8080", "localhost.evil.example"])
def test_disabled_auth_refuses_a_foreign_host_on_console_routes(method, path, host):
    app = build_console_app(DISABLED)
    status, _, body = call(app, method, path, {"host": host})
    assert is_unauthorized(status, body)


def test_disabled_auth_refuses_a_missing_host_on_console_routes():
    app = build_console_app(DISABLED)
    status, _, body = call(app, "GET", "/")
    assert is_unauthorized(status, body)
