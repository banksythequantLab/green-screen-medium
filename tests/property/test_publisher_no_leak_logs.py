"""Property 6: no Input value, Bound_Value or API key in any log record.

One example is one Publisher life: ``prepare`` with Binding_Variables and the API key in an
injected environment, ``build_app``, the lifespan (start), a set of Calls over REST and MCP
(valid, invalid, wrong key, refused during shutdown, read-only routes) and the lifespan end
(drain). Everything runs under ``LogCapture`` (root at level 1, plus a handler on every
non-propagating logger). The third-party loggers keep the clamp that ``build_app`` applies,
as in production; the test resets them first so the clamp is applied again in each example.

Probe_Values are made-up symbols, not credentials. No loader is patched, no network is used.

Scanning rule: a Call_Log_Record carries a random ``call_id`` and integers (durations, step
index), which can contain a 4-digit int probe by chance. For that record only the message,
``args``, ``exc_text``, ``stack_info`` and the formatted ``exc_info`` are scanned, and every
extra field is checked against its exact type and vocabulary instead. Every other record is
scanned whole, extra fields included.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import logging
import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greenscreen.publisher.app import _THIRD_PARTY_LOGGERS, build_app, prepare
from greenscreen.publisher.calls import ERROR_CODES, LOG_ONLY_OUTCOMES
from greenscreen.publisher.registry import build_registry, load_flows
from greenscreen.publisher.vault import BoundValues
from tests.flow_support import FakeClock, ScriptedState, capture
from tests.flow_support import _captures_text
from tests.property._publisher_strategies import (
    SETTINGS,
    BoundSet,
    HostPlan,
    all_leak_forms,
    bad_requests,
    bound_sets,
    fake_host_plans,
    probes,
)
from tests.publisher_support import (
    MINI,
    FakeHost,
    LogCapture,
    mcp_client,
    rest_client,
)

BASE_ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_MAX_BODY_BYTES": "2048",
}
CALL_FIELDS = {"call_id", "flow", "transport", "outcome", "duration_ms", "step_index",
               "close_failed", "session_clean"}
REQUIRED_FIELDS = {"call_id", "flow", "transport", "outcome", "duration_ms"}
OUTCOMES = ERROR_CODES | {"ok"} | LOG_ONLY_OUTCOMES
FLOW_NAMES = {"mini", "unknown", "tk5-logon", "tk5-logoff", "tk5-system-info"}
CALL_ID = re.compile(r"[0-9a-f]{16}")
ARG_OK = re.compile(r"""['"]?(\d+|GS_[A-Z0-9_]+|[a-z0-9_-]+)['"]?""")


@pytest.fixture(scope="module", autouse=True)
def _restore_logger_levels():
    names = ("",) + tuple(_THIRD_PARTY_LOGGERS)
    saved = {n: logging.getLogger(n).level for n in names}
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)


@functools.lru_cache(maxsize=1)
def _bundled():
    return load_flows(None)


@functools.lru_cache(maxsize=1)
def _captured_text() -> str:
    return _captures_text()


def _env(api_key: str, startup_password: str) -> dict[str, str]:
    return {
        **BASE_ENV,
        "GS_API_KEY": api_key,
        "GS_BIND_TK5_LOGON__PASSWORD": startup_password,
        "GS_BIND_TK5_SYSTEM_INFO__PASSWORD": startup_password,
    }


def _residual_screen(sentinel: str):
    """``sentinel_password_screen`` without its per-call re-read of every capture file.

    The helper checks the sentinel against ``captures/`` on each call (about 0.3 s); the
    test does that check against the cached text instead.
    """
    assert sentinel not in _captured_text()
    s = capture("tso-password-prompt")
    hidden = next(f for f in s.fields if f.hidden)
    start = hidden.start_row * s.columns + hidden.start_col + 1
    for i, ch in enumerate(sentinel):
        r, c = divmod((start + i) % (s.rows * s.columns), s.columns)
        s.cell_grid[r][c] = ord(ch)
    return s


def _host_factory(plan: HostPlan, sentinel: str | None):
    def build() -> FakeHost:
        if sentinel is not None:
            return FakeHost([ScriptedState(capture("tk5-logon")),
                             ScriptedState(_residual_screen(sentinel))])
        return plan.build()

    return lambda: build()()


async def _life(env, bound: BoundSet, plan, sentinel, mode, bad, wrong_key, api_key):
    prepared = prepare(env)  # startup: settings, bindings, registry; opens no session
    published = {**_bundled(), "mini": (MINI, "test")}
    store = BoundValues({
        "tk5-logon": {"password": env["GS_BIND_TK5_LOGON__PASSWORD"]},
        "tk5-system-info": {"password": env["GS_BIND_TK5_SYSTEM_INFO__PASSWORD"]},
        "mini": dict(bound.bound),
    })
    registry = build_registry(published, store, prepared.settings.call_timeout)
    prepared = dataclasses.replace(prepared, registry=registry, bound=store)
    app = build_app(
        prepared, session_factory=_host_factory(plan, sentinel), clock=FakeClock(),
        poll_interval=1.0,
    )
    supplied = dict(bound.supplied)
    async with contextlib.AsyncExitStack() as stack:
        rest = await stack.enter_async_context(rest_client(app, headers={"X-API-Key": api_key}))
        mcp = await stack.enter_async_context(mcp_client(app, mode))
        await rest.post("/flows/mini", json=supplied)
        await mcp.call_tool("mini", supplied)
        if bad is not None:
            await rest.post("/flows/mini", content=bad.body, headers={"content-type": bad.content_type})
            if bad.arguments is not None:
                await mcp.call_tool("mini", bad.arguments)
        denied = await rest.post("/flows/mini", json=supplied, headers={"X-API-Key": wrong_key})
        assert denied.status_code == 401
        await rest.get("/health")
        await rest.get("/openapi.json")
        await mcp.list_tools()
        app.service.begin_shutdown()
        await rest.post("/flows/mini", json=supplied)
    # leaving the lifespan drains the service (shutdown)


def _scan_texts(rec) -> list[str]:
    if rec.logger.startswith("greenscreen.publisher") and rec.message == "call finished":
        return [t for t in (rec.message, *rec.args, rec.exc_text, rec.stack_info, rec.exc_info_text) if t]
    return rec.texts()


def _check_permitted(rec) -> str | None:
    """None when the greenscreen.publisher record has only permitted fields, else a reason."""
    if rec.exc_text or rec.stack_info or rec.exc_info_text:
        return "exception or stack text"
    f = rec.fields
    if rec.message == "call finished":
        if rec.level != logging.INFO or rec.args:
            return "call record level or args"
        if not REQUIRED_FIELDS <= set(f) or not set(f) <= CALL_FIELDS:
            return "call record field names"
        if not (isinstance(f["call_id"], str) and CALL_ID.fullmatch(f["call_id"])):
            return "call_id"
        if f["flow"] not in FLOW_NAMES or f["transport"] not in ("rest", "mcp"):
            return "flow or transport"
        if f["outcome"] not in OUTCOMES:
            return "outcome"
        for key in ("duration_ms", "step_index"):
            if key in f and (type(f[key]) is not int or f[key] < 0):
                return key
        if "close_failed" in f and f["close_failed"] is not True:
            return "close_failed"
        if "session_clean" in f and f["session_clean"] is not False:
            return "session_clean"
        return None
    if f:
        return "extra fields on a non-call record"
    for text in rec.args:
        if not ARG_OK.fullmatch(text):
            return "argument outside the permitted kinds"
    if "%" in rec.message or len(rec.message) > 80:
        return "message is not fixed text"
    return None


@st.composite
def _lives(draw):
    bound = draw(bound_sets(MINI))
    bound_names = list(bound.bound)
    bad_choices = [bad_requests(bound_input=n) for n in (None, *bound_names)]
    return (
        bound,
        draw(fake_host_plans()),
        draw(st.booleans()),
        draw(st.sampled_from(("legacy", "auto"))),
        draw(st.one_of(st.none(), *bad_choices)),
        draw(probes("str", min_size=16, max_size=24)),
        draw(probes("str", min_size=16, max_size=24)),
        draw(probes("str", max_size=8)),
    )


# Feature: publisher, Property 6: No Input value or Bound_Value in any log record
@SETTINGS
@given(_lives())
def test_no_value_in_any_log_record(life):
    """**Validates: Requirements 7.2, 7.7, 8.2, 8.3, 8.4, 13.8, 22.10**"""
    bound, plan, use_sentinel, mode, bad, api_key, wrong_key, startup_pw = life
    if wrong_key == api_key:
        wrong_key += "x"
    password = bound.supplied.get("password") or bound.bound.get("password")
    sentinel = (
        password if use_sentinel and isinstance(password, str) and password not in _captured_text()
        else None
    )
    values = [*bound.values, api_key, wrong_key, startup_pw, *(bad.values if bad else ())]
    if sentinel is not None:
        values.append(sentinel)
    forms = all_leak_forms(values)

    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)  # build_app applies the clamp again
    with LogCapture() as cap:
        asyncio.run(_life(_env(api_key, startup_pw), bound, plan, sentinel, mode, bad, wrong_key, api_key))
        cap.refresh()
        records = cap.records

    assert cap.call_records(), "no Call_Log_Record was written"
    leaks = [f"{r.logger} level={r.level}" for r in records
             if any(f in t for t in _scan_texts(r) for f in forms)]
    assert leaks == [], f"a value or the API key reached a log record: {leaks}"
    bad_fields = [(r.logger, why) for r in records
                  if r.logger.startswith("greenscreen.publisher")
                  for why in [_check_permitted(r)] if why]
    assert bad_fields == [], f"records with fields outside the permitted set: {bad_fields}"
