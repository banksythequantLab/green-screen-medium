"""Property 13: authentication, driven through the whole stack.

``CrashGuard(AuthMiddleware(app))`` is built once per mode (key required, auth disabled)
and entered once in a background event loop. Requests are raw ASGI calls, so the test can
count how often the application reads the request body. The API key is made up at run
time (never written to a file); the fake host serves no session in any example.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.auth import extract_key
from greenscreen.publisher.calls import HTTP_STATUS, RESPONSE_HEADERS, error_body
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import find_leaks, key_headers, probes
from tests.publisher_support import FakeHost, system_info_states

FLOW = "tk5-system-info"
API_KEY = secrets.token_urlsafe(24)  # runtime only, 32 printable characters
BASE_ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_PUBLISH_FLOWS": FLOW,
    "GS_ENABLE_DOCS": "true",
}
ENABLED_ENV = {**BASE_ENV, "GS_API_KEY": API_KEY}
DISABLED_ENV = {**BASE_ENV, "GS_AUTH_DISABLED": "true"}

FIXED_BODY = json.dumps(error_body("unauthorized")).encode("utf-8")
FIXED_STATUS = HTTP_STATUS["unauthorized"]
JSON = (b"content-type", b"application/json")
ACCEPT = (b"accept", b"application/json, text/event-stream")

# (method, path, body kind): Flow routes, the OpenAPI document, the docs page, /mcp, /health
TARGETS = [
    ("POST", f"/flows/{FLOW}", "flow"),
    ("POST", "/flows/no-such-flow", "flow"),
    ("GET", "/openapi.json", None),
    ("GET", "/docs", None),
    ("POST", "/mcp", "mcp"),
    ("GET", "/health", None),
]

# (kind, Host header values, loopback?)
HOSTS = [
    ("localhost", [b"localhost"], True),
    ("localhost_port", [b"localhost:8000"], True),
    ("ipv4", [b"127.0.0.1"], True),
    ("ipv4_net_port", [b"127.8.9.1:80"], True),
    ("ipv6_port", [b"[::1]:8000"], True),
    ("ipv6", [b"[::1]"], True),
    ("public_name", [b"example.com"], False),
    ("lan_ip_port", [b"192.168.68.72:8000"], False),
    ("suffix_trick", [b"localhost.evil.com"], False),
    ("prefix_trick", [b"127.0.0.1.evil.com:80"], False),
    ("empty", [b""], False),
    ("missing", [], False),
    ("repeated_same", [b"localhost", b"localhost"], False),
    ("repeated_mixed", [b"localhost", b"evil.com"], False),
    ("non_ascii", [b"loc\xe4lhost"], False),
    ("bad_port", [b"localhost:abc"], False),
    ("bare_ipv6", [b"::1"], False),
]

_SEEN: dict[str, object] = {}


class Harness:
    """Two apps, each entered once inside one long-lived task of a background loop."""

    def __init__(self) -> None:
        self.hosts = {m: FakeHost(system_info_states()) for m in ("enabled", "disabled")}
        self.apps = {
            "enabled": build_app(prepare(ENABLED_ENV), session_factory=self.hosts["enabled"],
                                 clock=FakeClock(), poll_interval=0.01),
            "disabled": build_app(prepare(DISABLED_ENV), session_factory=self.hosts["disabled"],
                                  clock=FakeClock(), poll_interval=0.01),
        }
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self._thread.start()
        self._ready = asyncio.run_coroutine_threadsafe(self._start(), self.loop)
        self._ready.result(timeout=30)

    async def _start(self) -> None:
        self._stop = asyncio.Event()
        started = asyncio.Event()

        async def hold() -> None:
            async with self.apps["enabled"].lifespan():
                async with self.apps["disabled"].lifespan():
                    started.set()
                    await self._stop.wait()

        self._task = asyncio.create_task(hold())
        waiter = asyncio.create_task(started.wait())
        await asyncio.wait({self._task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if self._task.done():
            self._task.result()

    def close(self) -> None:
        async def stop() -> None:
            self._stop.set()
            await self._task

        asyncio.run_coroutine_threadsafe(stop(), self.loop).result(timeout=30)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=10)
        self.loop.close()

    def request(self, mode: str, method: str, path: str, headers, body: bytes):
        async def go():
            reads = 0
            sent_body = False

            async def receive():
                nonlocal reads, sent_body
                reads += 1
                if not sent_body:
                    sent_body = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            out: list[dict] = []

            async def send(message):
                out.append(message)

            scope = {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
                "query_string": b"", "root_path": "", "headers": list(headers),
                "server": ("test", 80), "client": ("127.0.0.1", 50000),
            }
            await asyncio.wait_for(self.apps[mode].asgi(scope, receive, send), 20)
            start = next(m for m in out if m["type"] == "http.response.start")
            data = b"".join(m.get("body", b"") for m in out if m["type"] == "http.response.body")
            return start["status"], [(k.lower(), v) for k, v in start["headers"]], data, reads

        return asyncio.run_coroutine_threadsafe(go(), self.loop).result(timeout=30)


@pytest.fixture(scope="module")
def harness():
    h = Harness()
    try:
        yield h
    finally:
        h.close()


def _body_for(kind, probe: str) -> bytes:
    if kind == "flow":
        return json.dumps({"userid": probe, "undeclared": probe}).encode()
    if kind == "mcp":
        return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
    return b""


@st.composite
def requests_(draw):
    mode = draw(st.sampled_from(["enabled", "disabled"]))
    key_case = draw(key_headers(API_KEY))
    host = draw(st.sampled_from(HOSTS))
    target = draw(st.sampled_from(TARGETS))
    probe = draw(probes("str", min_size=6, max_size=12))
    return mode, key_case, host, target, probe


@settings(max_examples=100, deadline=None)
@given(requests_())
def test_authentication(harness, case):
    # Feature: publisher, Property 13: Authentication
    mode, key_case, (host_kind, host_values, loopback), (method, path, body_kind), probe = case
    headers = list(key_case.headers) + [(b"host", v) for v in host_values]
    body = _body_for(body_kind, probe)
    if body_kind:
        headers += [JSON, ACCEPT, (b"content-length", str(len(body)).encode())]

    # the model: extract_key is the oracle of the key part, the Host rule of the disabled part
    presented = extract_key(key_case.headers)
    assert key_case.accepted == (presented == API_KEY)
    if mode == "enabled":
        expect_open = (method == "GET" and path == "/health") or key_case.accepted
    else:
        expect_open = loopback

    host = harness.hosts[mode]
    sessions_before = host.factory_calls
    status, resp_headers, data, reads = harness.request(mode, method, path, headers, body)

    assert host.factory_calls == sessions_before == 0  # no session in any example
    assert host.created == 0

    unauthorized = status == FIXED_STATUS and data == FIXED_BODY
    if expect_open:
        assert not unauthorized
        assert status != 401
    else:
        assert unauthorized
        assert reads == 0  # the body was never read
        expected_extra = {k.lower().encode(): v.encode() for k, v in RESPONSE_HEADERS["unauthorized"].items()}
        for k, v in expected_extra.items():
            assert (k, v) in resp_headers
        # every unauthorized response is identical, whatever the cause
        shape = (status, tuple(sorted(resp_headers)), data)
        assert _SEEN.setdefault("shape", shape) == shape
        # no probe, key or presented value in the response
        text = data.decode("utf-8") + "".join(v.decode("latin-1") for _, v in resp_headers)
        assert not find_leaks(text, [probe, API_KEY])

    # the key never appears in any response, accepted or not
    text = data.decode("utf-8", "replace") + "".join(v.decode("latin-1") for _, v in resp_headers)
    assert API_KEY not in text
