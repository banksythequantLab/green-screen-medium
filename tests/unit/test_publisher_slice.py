"""Day-one slice (task 3.3): ``tk5-system-info`` over REST and MCP on the Fake_Host.

Screens come from ``captures/`` through the ``tests/publisher_support.py`` helpers. The
userid and password are made-up Probe_Values, not credentials. No live host, no loader
patching.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging

import httpx2
import pytest
from mcp import Client

import greenscreen.publisher.app as app_module
from greenscreen.publisher import app as publisher_app
from greenscreen.publisher.app import build_app, limit_third_party_loggers, prepare
from greenscreen.publisher.calls import ConnectorSession
from greenscreen.publisher.config import StartupError
from tests.flow_support import FakeClock
from tests.publisher_support import FakeHost, system_info_states

USERID = "PRBU7Q2X"
PASSWORD = "PRBP9Z4K"
ARGS = {"userid": USERID, "password": PASSWORD}

KEY = {"X-API-Key": "k" * 16}  # the Auth_Guard is in front since task 5.5

ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_PUBLISH_FLOWS": "tk5-system-info",
}


def make(env=None):
    host = FakeHost(system_info_states())
    app = build_app(prepare(env or ENV), session_factory=host, clock=FakeClock(), poll_interval=0.01)
    return app, host


async def rest_call(app, name="tk5-system-info", body=ARGS):
    async with app.lifespan():
        transport = httpx2.ASGITransport(app=app.asgi)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", headers=KEY) as client:
            return await client.post(f"/flows/{name}", json=body)


async def mcp_call(app, mode="auto", name="tk5-system-info", body=ARGS):
    async with Client(app.server, mode=mode) as client:
        return await client.call_tool(name, body)


def test_rest_and_mcp_success_bodies_are_equal():
    rest_app, rest_host = make()
    resp = asyncio.run(rest_call(rest_app))
    assert resp.status_code == 200
    rest_body = resp.json()

    mcp_app, mcp_host = make()
    res = asyncio.run(mcp_call(mcp_app))
    assert res.is_error is False
    mcp_body = res.structured_content

    assert rest_body == mcp_body
    assert json.loads(res.content[0].text) == mcp_body
    assert rest_body["flow"] == "tk5-system-info"
    assert set(rest_body["outputs"]) == {"USERID", "SYSTEMID", "RELEASE", "TERMINAL"}
    assert rest_body["audit"]
    for host in (rest_host, mcp_host):
        assert host.created == 1 and host.opened == 1 and host.closed == 1
    dumped = json.dumps(rest_body)
    assert USERID not in dumped and PASSWORD not in dumped


def test_mcp_legacy_mode_gives_the_same_body():
    rest_app, _ = make()
    rest_body = asyncio.run(rest_call(rest_app)).json()
    mcp_app, _ = make()
    res = asyncio.run(mcp_call(mcp_app, mode="legacy"))
    assert res.structured_content == rest_body


def test_prepare_publishes_only_the_allow_listed_flow(monkeypatch):
    order: list[str] = []
    for name in ("load_flows", "parse_publish_list", "select_published", "build_registry"):
        real = getattr(app_module, name)

        def spy(*a, _real=real, _name=name, **k):
            order.append(_name)
            return _real(*a, **k)

        monkeypatch.setattr(app_module, name, spy)

    prepared = prepare(ENV)
    assert order == ["load_flows", "parse_publish_list", "select_published", "build_registry"]
    assert list(prepared.registry) == ["tk5-system-info"]
    assert prepared.loaded_count == 3
    assert len(prepared.signatures) > 0

    app = build_app(prepared, session_factory=FakeHost(system_info_states()), clock=FakeClock())

    async def health():
        async with app.lifespan():
            transport = httpx2.ASGITransport(app=app.asgi)
            async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
                return (await c.get("/health")).json()

    assert asyncio.run(health()) == {"status": "ok", "flows": 1}

    tools = asyncio.run(_list_tools(app))
    assert [t.name for t in tools] == ["tk5-system-info"]


async def _list_tools(app):
    async with Client(app.server, mode="auto") as client:
        return (await client.list_tools()).tools


def test_prepare_settings_failure_runs_before_any_flow_is_loaded(monkeypatch):
    called: list[str] = []
    real = app_module.load_flows
    monkeypatch.setattr(app_module, "load_flows", lambda *a, **k: called.append("x") or real(*a, **k))
    with pytest.raises(StartupError):
        prepare({"GS_PUBLISH_FLOWS": "tk5-system-info"})  # no GS_HOST
    assert called == []


def test_unset_allow_list_publishes_every_loaded_flow():
    env = {k: v for k, v in ENV.items() if k != "GS_PUBLISH_FLOWS"}
    prepared = prepare(env)
    assert len(prepared.registry) == prepared.loaded_count == 3


def test_unpublished_flow_is_unknown_over_both_front_ends():
    app, host = make()
    rest = asyncio.run(rest_call(app, name="tk5-logon", body={}))
    other = asyncio.run(rest_call(make()[0], name="no-such-flow", body={}))
    assert rest.status_code == other.status_code == 404
    assert rest.json() == other.json()
    res = asyncio.run(mcp_call(make()[0], name="tk5-logon", body={}))
    assert res.is_error and res.structured_content["error"]["code"] == "unknown_flow"
    assert host.factory_calls == 0


def test_build_app_uses_the_injected_factory():
    host = FakeHost(system_info_states())
    app = build_app(prepare(ENV), session_factory=host, clock=FakeClock())
    assert app.service._factory is host


def test_default_factory_is_a_connector_session_and_no_env_var_selects_one():
    app = build_app(prepare(ENV))
    session = app.service._factory()
    assert isinstance(session, ConnectorSession)  # built, not opened: no process starts
    for obj in (build_app, prepare, publisher_app):
        text = inspect.getsource(obj)
        assert "getenv" not in text and "os.environ" not in text
    assert "import os" not in inspect.getsource(app_module)
    # an environment that names a factory changes nothing
    env = {**ENV, "GS_SESSION_FACTORY": "fake", "GS_FAKE_HOST": "1"}
    app = build_app(prepare(env))
    assert isinstance(app.service._factory(), ConnectorSession)


def test_logger_clamp_raises_low_levels_and_keeps_high_ones():
    names = ("uvicorn", "starlette", "mcp", "anyio", "httpx2", "httpcore2", "asyncio")
    saved = {n: logging.getLogger(n).level for n in names}
    try:
        for n in names:
            logging.getLogger(n).setLevel(logging.DEBUG)
        logging.getLogger("uvicorn").setLevel(logging.ERROR)
        limit_third_party_loggers()
        assert logging.getLogger("uvicorn").level == logging.ERROR
        for n in names[1:]:
            assert logging.getLogger(n).level == logging.INFO
        # build_app applies it too
        logging.getLogger("mcp").setLevel(logging.DEBUG)
        build_app(prepare(ENV))
        assert logging.getLogger("mcp").level == logging.INFO
    finally:
        for n, level in saved.items():
            logging.getLogger(n).setLevel(level)


def test_package_exports_are_lazy():
    import subprocess
    import sys

    code = (
        "import sys, greenscreen.publisher as p;"
        "assert not {'mcp','fastapi','starlette','uvicorn'} & set(sys.modules);"
        "assert callable(p.build_app) and callable(p.prepare)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
