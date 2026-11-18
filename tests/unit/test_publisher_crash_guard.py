"""Replaced framework handlers and the CrashGuard (task 5.2, Requirements 6.9 and 6.10).

The uvicorn tests start a real server on a loopback port and serve the Fake_Host only.
No host session and no credential is involved; the marker is made up.
"""
from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request

import httpx2
import pytest
import uvicorn
from pydantic import BaseModel

from greenscreen.publisher.calls import CallService, Limiter
from greenscreen.publisher.config import load_settings
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.rest import CRASH_LOG_TEXT, CrashGuard, build_rest
from greenscreen.publisher.vault import BoundValues
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import FakeClock
from tests.publisher_support import MINI, FakeHost, mini_states

MARKER = "MRK9Q7ZX-not-a-real-secret"
ENV = {"GS_S3270_BINARY": "s3270", "GS_HOST": "host.invalid", "GS_API_KEY": "k" * 16}


class Typed(BaseModel):
    password: int


def make_app():
    registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
    service = CallService(
        registry, BoundValues(), load_bundled_signatures(), Limiter(1),
        FakeHost(mini_states()), clock=FakeClock(),
    )

    async def mcp(scope, receive, send):  # pragma: no cover - never reached
        raise AssertionError

    app = build_rest(service, registry, load_settings(ENV), mcp)

    @app.post("/typed")
    async def typed(body: Typed):  # only here to provoke a validation error
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom " + MARKER)

    return app


def asgi_request(app, method, path, **kw):
    async def go():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.request(method, path, **kw)

    return asyncio.run(go())


def assert_request_invalid(resp):
    assert resp.status_code == 400
    assert resp.json() == {
        "error": {"code": "request_invalid", "message": "The request is not valid."}
    }
    assert resp.headers["cache-control"] == "no-store"


# -- replaced framework handlers ------------------------------------------


def test_validation_error_does_not_echo_the_submitted_value():
    resp = asgi_request(make_app(), "POST", "/typed", json={"password": MARKER})
    assert_request_invalid(resp)
    assert MARKER not in resp.text and "input" not in resp.json()["error"]


def test_unknown_path_is_request_invalid():
    assert_request_invalid(asgi_request(make_app(), "GET", "/no/such/path"))


def test_wrong_method_on_a_flow_route_is_request_invalid():
    assert_request_invalid(asgi_request(make_app(), "GET", "/flows/mini"))


# -- CrashGuard in isolation ------------------------------------------------


def run_asgi(app, scope_type="http"):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app({"type": scope_type, "method": "GET", "path": "/", "headers": []}, receive, send))
    return sent


def test_guard_sends_internal_error_when_nothing_was_sent(caplog):
    async def crash(scope, receive, send):
        raise RuntimeError(MARKER)

    with caplog.at_level(logging.DEBUG):
        sent = run_asgi(CrashGuard(crash))
    assert sent[0]["status"] == 500
    assert json.loads(sent[1]["body"])["error"]["code"] == "internal_error"
    assert (b"cache-control", b"no-store") in sent[0]["headers"]
    guard_records = [r for r in caplog.records if r.name == "greenscreen.publisher"]
    assert [r.getMessage() for r in guard_records] == [CRASH_LOG_TEXT]
    assert guard_records[0].exc_info is None and guard_records[0].exc_text is None
    assert MARKER not in caplog.text


def test_guard_passes_cancellation_through():
    async def cancelled(scope, receive, send):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run_asgi(CrashGuard(cancelled))


def test_guard_ignores_non_http_scopes():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    run_asgi(CrashGuard(app), scope_type="lifespan")
    assert seen == ["lifespan"]


# -- a real uvicorn server --------------------------------------------------


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(0)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_and_get(asgi, path):
    """Serve on loopback with the production uvicorn settings; return (status, body, records)."""
    capture = _Capture()
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(asgi, host="127.0.0.1", port=port, log_config=None, access_log=False)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
                status, body = r.status, r.read().decode()
        except urllib.error.HTTPError as err:
            status, body = err.code, err.read().decode()
    finally:
        server.should_exit = True
        thread.join(10)
        root.removeHandler(capture)
        root.setLevel(old_level)
    return status, body, capture.records


def leaks(records):
    fmt = logging.Formatter()
    texts = [fmt.format(r) + repr(r.args) + str(r.exc_text) for r in records]
    return [t for t in texts if MARKER in t or "Traceback" in t]


def test_without_the_guard_uvicorn_logs_the_traceback():
    # Control: proves the check below can see a leak on the installed versions.
    status, body, records = serve_and_get(make_app(), "/boom")
    assert status == 500 and json.loads(body)["error"]["code"] == "internal_error"
    assert leaks(records)


def test_real_uvicorn_with_the_guard_logs_no_traceback_and_no_marker():
    status, body, records = serve_and_get(CrashGuard(make_app()), "/boom")
    assert status == 500
    assert json.loads(body)["error"]["code"] == "internal_error"
    assert MARKER not in body
    assert leaks(records) == []
    assert all(r.exc_info is None and r.exc_text is None for r in records)
    assert any(r.getMessage() == CRASH_LOG_TEXT for r in records)
