"""Property 2: the console changes no existing response (spec console, task 2.12).

Two apps are built from the same environment except ``GS_ENABLE_CONSOLE``, each over its
own Fake_Host with the same plan. The same four requests go to both and the status, all
response headers and the body are compared. The key and the input values are made-up
Probe_Values, no credential. Failure messages carry no value.
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from tests.console_support import call_scope
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import bad_requests, fake_host_plans, probes
from tests.publisher_support import MINI, mini_states

KEY = "k" * 16
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": KEY,
    "GS_PUBLISH_FLOWS": "tk5-system-info",
}
AUTH = {"x-api-key": KEY, "host": "test"}
JSON = {**AUTH, "content-type": "application/json", "accept": "application/json, text/event-stream"}
TOOLS_LIST = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()


@functools.lru_cache(maxsize=2)
def _prepared(console: bool):
    env = dict(ENV)
    if console:
        env["GS_ENABLE_CONSOLE"] = "true"
    prepared = prepare(env)
    registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
    return dataclasses.replace(prepared, registry=registry)


def _arguments():
    return st.tuples(
        probes("str", max_size=8),
        st.one_of(st.none(), probes("str", max_size=8)),
        st.one_of(st.none(), probes("int", max_size=4)),
    ).map(
        lambda t: json.dumps(
            {k: v for k, v in (("userid", t[0]), ("password", t[1]), ("count", t[2])) if v is not None}
        ).encode()
    )


def _requests(flow_body: bytes, flow_type: str):
    return [
        ("POST", "/flows/mini", {**AUTH, "content-type": flow_type}, flow_body),
        ("GET", "/openapi.json", AUTH, b""),
        ("GET", "/health", AUTH, b""),
        ("POST", "/mcp", JSON, TOOLS_LIST),
    ]


def _run(console: bool, plan, requests):
    app = build_app(
        _prepared(console), session_factory=plan.build(), clock=FakeClock(), poll_interval=0.01
    )

    async def go():
        async with app.lifespan():
            return [
                await call_scope(app.asgi, method, path, headers, body=body)
                for method, path, headers, body in requests
            ]

    return asyncio.run(go())


@pytest.fixture(scope="module", autouse=True)
def _warm():
    _prepared(False), _prepared(True)


# Feature: console, Property 2: The console changes no existing response
@settings(max_examples=100, deadline=None)
@given(
    plan=fake_host_plans(),
    valid=_arguments(),
    bad=st.one_of(st.none(), bad_requests()),
)
def test_console_changes_no_existing_response(plan, valid, bad):
    """**Validates: Requirements 4.5, 6.6, 6.7, 13.1, 13.2, 15.2**"""
    body, ctype = (valid, "application/json") if bad is None else (bad.body, bad.content_type)
    requests = _requests(body, ctype)
    off = _run(False, plan, requests)
    on = _run(True, plan, requests)

    for i, (a, b) in enumerate(zip(off, on)):
        label = f"request {i} ({requests[i][0]} {requests[i][1]})"
        if a[0] != b[0]:
            pytest.fail(f"{label}: status differs with the console on")
        if sorted(a[1]) != sorted(b[1]):
            pytest.fail(f"{label}: response headers differ with the console on")
        if a[2] != b[2]:
            pytest.fail(f"{label}: body differs with the console on")

    # GET /openapi.json: the same bytes
    if off[1][2] != on[1][2]:
        pytest.fail("openapi.json bytes differ with the console on")
