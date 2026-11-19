# Feature: ask, Property 5: Ask off changes no existing response
"""Property 5: an empty ``GS_ENABLE_ASK`` changes no existing response (spec ask, task 2.18).

Two apps are built from the same environment, one with ``GS_ENABLE_ASK`` set to an empty
string and one without the variable, each over its own Fake_Host with the same plan. The
same requests go to both and the status, all response headers and the body are compared.
The key and the input values are made-up Probe_Values, no credential. Failure messages
carry no value.
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
from tests.publisher_support import MINI

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
ASK_BODY = json.dumps({"question": "what system is this?"}).encode()


@functools.lru_cache(maxsize=2)
def _prepared(empty_switch: bool):
    env = dict(ENV)
    if empty_switch:
        env["GS_ENABLE_ASK"] = ""
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
        ("POST", "/ask", JSON, ASK_BODY),
        ("GET", "/ask", AUTH, b""),
    ]


def _run(empty_switch: bool, plan, requests):
    app = build_app(
        _prepared(empty_switch), session_factory=plan.build(), clock=FakeClock(), poll_interval=0.01
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


@settings(max_examples=100, deadline=None)
@given(
    plan=fake_host_plans(),
    valid=_arguments(),
    bad=st.one_of(st.none(), bad_requests()),
)
def test_ask_off_changes_no_existing_response(plan, valid, bad):
    """**Validates: Requirements 14.1, 14.3, 1.13, 2.8**"""
    body, ctype = (valid, "application/json") if bad is None else (bad.body, bad.content_type)
    requests = _requests(body, ctype)
    unset = _run(False, plan, requests)
    empty = _run(True, plan, requests)

    for i, (a, b) in enumerate(zip(unset, empty)):
        label = f"request {i} ({requests[i][0]} {requests[i][1]})"
        if a[0] != b[0]:
            pytest.fail(f"{label}: status differs with an empty GS_ENABLE_ASK")
        if sorted(a[1]) != sorted(b[1]):
            pytest.fail(f"{label}: response headers differ with an empty GS_ENABLE_ASK")
        if a[2] != b[2]:
            pytest.fail(f"{label}: body differs with an empty GS_ENABLE_ASK")

    if unset[1][2] != empty[1][2]:
        pytest.fail("openapi.json bytes differ with an empty GS_ENABLE_ASK")
