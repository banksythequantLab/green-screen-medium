"""Property 4: error mapping is total, single-valued and fixed-text (task 7.5).

One generated scenario per example, driven through REST and (where the code is
reachable there) MCP, each front end on its own app and its own Fake_Host:

* ``host``: an exception class, a ``FlowError`` of each of the 13 Reason_Codes or a
  ``FlowInputError`` injected at the factory, ``open``, ``close`` or any Session call;
* ``base``: a ``BaseException`` that is not an ``Exception`` at a Session call that the
  ``MINI`` Flow reaches;
* ``runflow``: ``run_flow`` itself raising an exception class (Requirement 6.4);
* ``pub``: the Publisher_Codes that do not come from an injected exception.

The expected code, status and members come from the tables below, which restate
the design table and Requirements 6.1 to 6.6, not from ``greenscreen.publisher.calls``.
Probe values and credentials are not used: the one Input is a made-up user id.
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import json
import logging
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.connector import (
    ConfigurationError,
    ConnectorTimeoutError,
    ParseError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.flow.errors import REASON_CODES, FlowDefinitionError, FlowError, FlowInputError
from greenscreen.publisher import calls
from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import ArbitraryError, InjectedBase
from tests.publisher_support import (
    FAILURE_POINTS,
    MINI,
    Failure,
    FakeHost,
    LogCapture,
    mcp_client,
    make_exception,
    mini_states,
    rest_client,
)

KEY = "k" * 16
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": KEY,
    "GS_PUBLISH_FLOWS": "tk5-logon",
    "GS_MAX_BODY_BYTES": "1024",
}
HEADERS = {"X-API-Key": KEY}
ARGS = {"userid": "ABCDEFGH"}

# Design table (HTTP status per Error_Code), restated here.
STATUS = {
    "unauthorized": 401, "request_invalid": 400, "request_too_large": 413,
    "unknown_flow": 404, "input_invalid": 422, "busy": 429, "shutting_down": 503,
    "host_unavailable": 502, "call_timeout": 504, "internal_error": 500,
    "timeout": 504, "run_timeout": 504, "unknown_screen": 502, "ambiguous_screen": 502,
    "unexpected_screen": 502, "loop_limit": 502, "bad_target": 502, "secret_target": 502,
    "hidden_output": 502, "output_type": 502, "screen_size": 502, "session_error": 502,
}
PUBLISHER = ("unauthorized", "unknown_flow", "request_invalid", "request_too_large", "busy",
             "shutting_down", "call_timeout", "host_unavailable", "internal_error")
FLOW_STOP = tuple(c for c in REASON_CODES if c != "input_invalid")
STOP_MEMBERS = {"code", "message", "step_index", "kind", "expected", "summary", "audit"}
AUDIT_MEMBERS = {"step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds"}

EXC_CLASSES = {
    "FlowDefinitionError": FlowDefinitionError,
    "S3270Error": S3270Error,
    "ConnectorTimeoutError": ConnectorTimeoutError,
    "ParseError": ParseError,
    "ConfigurationError": ConfigurationError,
    "SessionClosedError": SessionClosedError,
    "OSError": OSError,
    "RuntimeError": RuntimeError,
    "ArbitraryError": ArbitraryError,
}
# Keys of the injected "exception": the nine classes, 13 FlowErrors, one FlowInputError.
EXC_KEYS = (*EXC_CLASSES, *(f"flow:{r}" for r in FLOW_STOP), "input")
# Points of the MINI Flow that run (the others are never called).
REACHED = ("read_screen", "string", "enter")

UNIVERSE: tuple[tuple, ...] = (
    *(("host", at, key) for at in FAILURE_POINTS for key in EXC_KEYS),
    *(("base", at) for at in REACHED),
    *(("runflow", key) for key in EXC_CLASSES),
    *(("pub", name) for name in (
        "unauthorized", "unknown_flow", "request_invalid", "request_too_large",
        "busy", "shutting_down", "call_timeout")),
)
SCENARIOS = st.sampled_from(UNIVERSE)

REST_ONLY = {"unauthorized", "request_invalid", "request_too_large"}


@functools.lru_cache(maxsize=None)
def _prepared(call_timeout: float):
    base = prepare(ENV)
    registry = build_registry({"mini": (MINI, "test")}, BoundValues(), call_timeout)
    return dataclasses.replace(base, registry=registry)


def _exception(key: str):
    """A fresh exception instance for ``key`` (FlowError needs constructor arguments)."""
    if key == "input":
        return FlowInputError("userid", "type")
    if key.startswith("flow:"):
        return FlowError(
            key[5:], step_index=2, kind="expect", expected=("b", "a"), summary=None, audit=()
        )
    return make_exception(EXC_CLASSES[key], "injected")


def _expected(scn: tuple, exc) -> tuple[str, str | None]:
    """(code or "ok", required message or None) for a scenario, from the spec."""
    if scn[0] == "pub":
        return scn[1], None
    if scn[0] == "runflow":
        return "internal_error", None
    if scn[0] == "base":
        raise AssertionError("base scenarios have no response")
    _, at, key = scn
    if at in ("factory", "open"):
        return "host_unavailable", None  # any Exception at open (Requirement 6.4)
    if at == "close":
        return "ok", None  # the exception is ignored for the response (Requirement 3.5)
    if at not in REACHED:
        return "ok", None  # the Flow never makes that call
    if isinstance(exc, FlowInputError):
        return "input_invalid", str(exc)
    if isinstance(exc, FlowError):
        return exc.reason, None  # passes through the runner unchanged
    return "session_error", None  # the runner turns Session exceptions into session_error


def _strip(body):
    """A body without the (clock dependent) ``duration_seconds`` of each audit entry."""
    return json.loads(json.dumps(body), object_hook=lambda d: {
        k: v for k, v in d.items() if k != "duration_seconds"})


def _check_body(code: str, message: str | None, body: dict) -> None:
    if code == "ok":
        assert set(body) == {"flow", "outputs", "audit"}
        for entry in body["audit"]:
            assert set(entry) == AUDIT_MEMBERS
        return
    assert set(body) == {"error"}
    err = body["error"]
    assert err["code"] == code and code in STATUS
    if code in FLOW_STOP:
        assert set(err) == STOP_MEMBERS
        assert isinstance(err["expected"], list) and isinstance(err["audit"], list)
        for entry in err["audit"]:
            assert set(entry) == AUDIT_MEMBERS
    else:
        assert set(err) == {"code", "message"}
    if code == "input_invalid":
        assert err["message"] == message
    else:
        assert isinstance(err["message"], str) and err["message"]
        assert "cancelled" not in err["message"].lower()


def _flatten(err: BaseException) -> list[BaseException]:
    subs = getattr(err, "exceptions", None)
    if subs is None:
        return [err]
    return [leaf for sub in subs for leaf in _flatten(sub)]


def _make(scn: tuple, exc):
    """(host, app) for one front end."""
    failures: tuple[Failure, ...] = ()
    block = None
    timeout = 30.0
    if scn[0] == "host":
        failures = (Failure(scn[1], exc, 1),)
    elif scn[0] == "base":
        failures = (Failure(scn[1], exc, 1),)
    elif scn == ("pub", "call_timeout"):
        block, timeout = 1, 0.05
    host = FakeHost(mini_states(), failures=failures, block_read=block)
    app = build_app(_prepared(timeout), session_factory=host, clock=FakeClock(), poll_interval=0.01)
    return host, app


async def _rest(scn: tuple, exc):
    host, app = _make(scn, exc)
    name = "nope" if scn == ("pub", "unknown_flow") else "mini"
    headers = {} if scn == ("pub", "unauthorized") else HEADERS
    kwargs: dict = {"json": ARGS}
    if scn == ("pub", "request_invalid"):
        kwargs = {"content": b"[1]", "headers": {"Content-Type": "application/json"}}
    elif scn == ("pub", "request_too_large"):
        kwargs = {"content": b'{"userid": "' + b"A" * 2000 + b'"}',
                  "headers": {"Content-Type": "application/json"}}
    try:
        async with rest_client(app, headers=headers) as client:
            if scn == ("pub", "busy"):
                assert app.service._limiter.try_acquire()
            if scn == ("pub", "shutting_down"):
                app.service.begin_shutdown()
            try:
                resp = await client.post(f"/flows/{name}", **kwargs)
            except BaseException as err:  # noqa: BLE001 - the base scenario expects one
                return host, app, err
            finally:
                if scn == ("pub", "busy"):
                    app.service._limiter.release()
    finally:
        host.release_all()
    return host, app, resp


async def _mcp(scn: tuple, exc):
    host, app = _make(scn, exc)
    name = "nope" if scn == ("pub", "unknown_flow") else "mini"
    try:
        async with mcp_client(app, "auto") as client:
            if scn == ("pub", "busy"):
                assert app.service._limiter.try_acquire()
            if scn == ("pub", "shutting_down"):
                app.service.begin_shutdown()
            try:
                return host, app, await asyncio.wait_for(client.call_tool(name, ARGS), 20)
            except BaseException as err:  # noqa: BLE001 - the base scenario expects one
                return host, app, err
            finally:
                if scn == ("pub", "busy"):
                    app.service._limiter.release()
    finally:
        host.release_all()


def _check_clean(host: FakeHost, app) -> None:
    """The session was closed and the Slot released (Requirements 3.3, 6.8)."""
    assert host.closed == host.created
    assert host.live == 0
    assert app.service._limiter.in_flight == 0


def _runflow_patch(scn: tuple, exc):
    if scn[0] != "runflow":
        return mock.patch.object(calls, "run_flow", calls.run_flow)

    def boom(*args, **kwargs):
        raise exc

    return mock.patch.object(calls, "run_flow", boom)


@settings(max_examples=100, deadline=None)
@given(SCENARIOS)
def test_error_mapping_is_total_single_valued_and_fixed_text(scn):
    # Feature: publisher, Property 4: Error mapping is total, single-valued and fixed-text
    assert set(calls.HTTP_STATUS) == set(STATUS) == set(calls.MESSAGES) == calls.ERROR_CODES
    assert dict(calls.HTTP_STATUS) == STATUS
    assert "cancelled" not in calls.HTTP_STATUS and "cancelled" not in calls.MESSAGES
    assert calls.LOG_ONLY_OUTCOMES.isdisjoint(calls.ERROR_CODES)
    assert len(REASON_CODES) == 13 and len(PUBLISHER) == 9 and len(STATUS) == 22

    key = scn[2] if scn[0] == "host" else scn[1] if scn[0] == "runflow" else None
    exc = (
        InjectedBase("injected") if scn[0] == "base"
        else _exception(key) if key is not None else None
    )
    base = scn[0] == "base"
    code, message = ("ok", None) if base else _expected(scn, exc)

    with LogCapture() as logs, _runflow_patch(scn, exc):
        rest_host, rest_app, resp = asyncio.run(_rest(scn, exc))
        mcp = None
        if not (scn[0] == "pub" and scn[1] in REST_ONLY):
            mcp = asyncio.run(_mcp(scn, exc))

    if base:
        assert isinstance(resp, BaseException)
        assert any(e is exc for e in _flatten(resp)), "BaseException must re-raise unchanged"
        _check_clean(rest_host, rest_app)
        mcp_host, mcp_app, result = mcp
        assert isinstance(result, BaseException)
        assert any(e is exc for e in _flatten(result)), "BaseException must re-raise unchanged"
        _check_clean(mcp_host, mcp_app)
    else:
        assert not isinstance(resp, BaseException)
        assert resp.status_code == (200 if code == "ok" else STATUS[code])
        rest_body = resp.json()
        _check_body(code, message, rest_body)
        _check_clean(rest_host, rest_app)
        if scn == ("pub", "unauthorized"):
            assert resp.headers["www-authenticate"] == "Bearer"
        if scn == ("pub", "busy"):
            assert resp.headers["retry-after"] == "1"
        assert "cancelled" not in resp.text.lower()

        if mcp is not None:
            mcp_host, mcp_app, result = mcp
            assert not isinstance(result, BaseException)
            assert result.is_error is (code != "ok")
            body = result.structured_content
            _check_body(code, message, body)
            assert json.loads(result.content[0].text) == body
            assert _strip(body) == _strip(rest_body)
            _check_clean(mcp_host, mcp_app)

    # No exception reached the SDK error path: the mcp loggers wrote no ERROR record.
    if not base:
        assert not [
            r for r in logs.records
            if r.logger.split(".")[0] == "mcp" and r.level >= logging.ERROR
        ]
