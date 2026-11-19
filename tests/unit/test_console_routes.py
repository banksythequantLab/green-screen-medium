"""Console routes, headers, secrecy and loader (spec console, task 2.10).

Everything runs through the real ASGI stack over the Fake_Host. API keys and Bound_Values
are generated per test and never written to a file. No live host, no network.
"""
from __future__ import annotations

import asyncio
import importlib.resources
import secrets

import pytest

import greenscreen.publisher.console as console_pkg
from greenscreen.publisher.app import prepare
from greenscreen.publisher.config import StartupError
from tests.console_support import (
    ASSET_DIR,
    BASE_ENV,
    EXPECTED_PAIRS,
    FLOW,
    build_console_app,
)
from tests.property._publisher_strategies import all_leak_forms
from tests.publisher_support import LogCapture, rest_client

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'none'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)
BIND_VAR = "GS_BIND_TK5_SYSTEM_INFO__PASSWORD"
JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

# (path, packaged file, media type), spelled out here on purpose.
ROUTES = [
    ("/", "index.html", "text/html; charset=utf-8"),
    ("/console/console.css", "console.css", "text/css; charset=utf-8"),
    ("/console/console.js", "console.js", "text/javascript; charset=utf-8"),
    ("/console/snippets.js", "snippets.js", "text/javascript; charset=utf-8"),
    ("/console/codes.json", "codes.json", "application/json"),
    ("/console/favicon.svg", "favicon.svg", "image/svg+xml"),
]
PATHS = [r[0] for r in ROUTES]


def run(coro):
    return asyncio.run(coro)


def headers_of(resp) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for name, value in resp.headers.multi_items():
        out.setdefault(name.lower(), []).append(value)
    return out


def send(console_app, method, path, *, key=False, **kwargs):
    """One request through the whole stack, with or without the app's own key."""

    async def go():
        hdrs = {"X-API-Key": console_app.api_key} if key else {}
        hdrs.update(kwargs.pop("headers", {}))
        async with rest_client(console_app.app, headers=hdrs) as c:
            return await c.request(method, path, **kwargs)

    return run(go())


# --------------------------------------------------------------------------
# The six routes
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key", [False, True], ids=["no-key", "key"])
@pytest.mark.parametrize("path,file,media_type", ROUTES)
def test_console_route_status_media_type_headers_and_body(path, file, media_type, key):
    ca = build_console_app()
    resp = send(ca, "GET", path, key=key)
    h = headers_of(resp)
    assert resp.status_code == 200
    assert h["content-type"] == [media_type]
    assert h["content-security-policy"] == [CSP]
    assert h["x-content-type-options"] == ["nosniff"]
    assert h["referrer-policy"] == ["no-referrer"]
    assert h["cache-control"] == ["no-store, no-transform"]
    assert resp.content == (ASSET_DIR / file).read_bytes()
    assert ca.host.factory_calls == 0


def test_the_route_table_matches_the_expected_pairs():
    assert {("GET", p) for p in PATHS} == EXPECTED_PAIRS
    assert [r[:3] for r in console_pkg.ROUTES] == ROUTES


def _flow_success(ca):
    return send(ca, "POST", f"/flows/{FLOW}", key=True, json={"userid": "ABCD1234"})


def _flow_error(ca):
    return send(ca, "POST", f"/flows/{FLOW}", key=True, json=[])


def _mcp(ca):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    return send(ca, "POST", "/mcp", key=True, json=body, headers=JSON_HEADERS)


OTHER_REQUESTS = {
    "health": lambda ca: send(ca, "GET", "/health"),
    "openapi": lambda ca: send(ca, "GET", "/openapi.json", key=True),
    "flow-success": _flow_success,
    "flow-error": _flow_error,
    "mcp": _mcp,
    "unknown-path-key": lambda ca: send(ca, "GET", "/nope", key=True),
    "unknown-path-no-key": lambda ca: send(ca, "GET", "/nope"),
    "unauthorized": lambda ca: send(ca, "GET", "/openapi.json"),
    "wrong-key": lambda ca: send(ca, "GET", "/openapi.json", headers={"X-API-Key": "x" * 22}),
}
ENV_BOUND = {BIND_VAR: "A1b2C3d4"}


@pytest.mark.parametrize("name", OTHER_REQUESTS)
def test_other_routes_have_no_csp_and_an_unchanged_cache_control(name):
    """Requirements 2.5 and 15.3: compare each response with the console absent."""
    do = OTHER_REQUESTS[name]
    on = do(build_console_app(ENV_BOUND, console=True))
    off = do(build_console_app(ENV_BOUND, console=False))
    assert on.status_code == off.status_code
    assert "content-security-policy" not in headers_of(on)
    assert "content-security-policy" not in headers_of(off)
    assert headers_of(on).get("cache-control") == headers_of(off).get("cache-control")
    if name == "flow-error":
        assert on.status_code != 200
    if name == "flow-success":
        assert on.status_code == 200


# --------------------------------------------------------------------------
# HEAD and OPTIONS: recorded behaviour (design, "Recorded responses")
# --------------------------------------------------------------------------

@pytest.mark.parametrize("console", [True, False], ids=["console-on", "console-off"])
@pytest.mark.parametrize("key", [False, True], ids=["no-key", "key"])
@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
@pytest.mark.parametrize("path", ["/", "/console/console.css"])
def test_head_and_options_are_never_open_and_answer_as_an_unknown_method(path, method, key, console):
    ca = build_console_app(console=console)
    resp = send(ca, method, path, key=key)
    assert resp.status_code == (400 if key else 401)
    h = headers_of(resp)
    assert "allow" not in h
    assert "content-security-policy" not in h
    if method == "HEAD":
        assert resp.content == b""
    elif key:
        assert resp.json()["error"]["code"] == "request_invalid"
    else:
        assert resp.json()["error"]["code"] == "unauthorized"
    assert ca.host.factory_calls == 0


def _rest_routes(ca):
    fastapi_app = ca.app.asgi.app._app  # CrashGuard -> AuthMiddleware -> FastAPI
    return [r for r in fastapi_app.router.routes if getattr(r, "path", None) in PATHS]


def test_no_head_route_exists_and_every_console_route_is_get_only():
    routes = _rest_routes(build_console_app(console=True))
    assert sorted(r.path for r in routes) == sorted(PATHS)
    for r in routes:
        assert set(r.methods) == {"GET"}
    assert _rest_routes(build_console_app(console=False)) == []


# --------------------------------------------------------------------------
# Secrecy and logging (Requirements 10.1, 10.2, 10.8)
# --------------------------------------------------------------------------

def test_console_requests_leak_no_key_or_bound_value_and_write_no_call_record():
    bound = "P" + secrets.token_hex(4)[:7]
    ca = build_console_app({BIND_VAR: bound})
    forms = all_leak_forms([ca.api_key, bound])
    assert forms
    responses = []

    async def go():
        async with rest_client(ca.app) as c:
            for path in PATHS:
                responses.append(await c.get(path))
                responses.append(await c.get(path, headers={"X-API-Key": ca.api_key}))

    with LogCapture() as logs:
        logs.refresh()
        run(go())
        logs.refresh()
    texts = []
    for resp in responses:
        assert resp.status_code == 200
        texts.append(resp.text)
        texts.extend(f"{k}: {v}" for k, v in resp.headers.multi_items())
    leaked = [i for i, t in enumerate(texts) if any(f in t for f in forms)]
    assert not leaked, f"leak form found in {len(leaked)} response part(s)"
    assert not logs.find(forms), "leak form found in a log record"
    assert logs.call_records() == []
    assert ca.host.factory_calls == 0


# --------------------------------------------------------------------------
# Loader
# --------------------------------------------------------------------------

def test_load_assets_returns_the_six_assets():
    assets = console_pkg.load_assets()
    assert [(a.path, a.file, a.media_type) for a in assets] == ROUTES
    for a in assets:
        assert a.body == (ASSET_DIR / a.file).read_bytes()


class _Failing:
    def __init__(self, real, file):
        self._real, self._file = real, file

    def joinpath(self, name):
        if name == self._file:
            return _FailingFile(rf"C:\secret\machine\path\{name}")
        return self._real.joinpath(name)


class _FailingFile:
    def __init__(self, text):
        self._text = text

    def read_bytes(self):
        raise FileNotFoundError(self._text)


@pytest.mark.parametrize("file", ["index.html", "codes.json", "favicon.svg"])
def test_prepare_names_a_missing_asset_and_no_machine_path(monkeypatch, file):
    real_files = importlib.resources.files

    def files(anchor, *args, **kwargs):
        target = real_files(anchor, *args, **kwargs)
        if anchor == "greenscreen.publisher.console":
            return _Failing(target, file)
        return target

    monkeypatch.setattr(importlib.resources, "files", files)
    env = {**BASE_ENV, "GS_API_KEY": secrets.token_urlsafe(24), "GS_ENABLE_CONSOLE": "true"}
    with pytest.raises(StartupError) as info:
        prepare(env)
    message = str(info.value)
    assert file in message
    assert "\\" not in message and "/" not in message and ":" not in message.replace("console:", "")
    assert "secret" not in message
