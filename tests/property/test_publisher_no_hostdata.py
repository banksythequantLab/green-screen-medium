"""Property 7 (task 8.3): no Host_Data in any response or log record.

One app is built for the module and served by one long-lived event loop on a helper
thread (the MCP session manager and the anyio scopes of the clients must be entered and
left by one task). Each example swaps the Fake_Host behind a delegating Session_Factory,
makes one Call over REST and one over MCP with every logger captured at level 1, and
looks for Host_Data in the responses and the records:

* a marker in an injected exception (``S3270Error.data_lines``, ``ParseError.raw`` and
  the message of the other classes), raised at the factory, ``open``, any Session call
  or ``close``;
* hidden cell text, on a screen whose hidden field holds a made-up residual password;
* ``Traceback``, a frame file path and a ``Screen`` or ``Field`` repr.

The user id is a made-up value. No credential is used. A failure message names the
place and the kind of hit, never the value.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import threading

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import greenscreen
from greenscreen.connector import (
    ConfigurationError,
    ConnectorTimeoutError,
    ParseError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from tests.flow_support import FakeClock, ScriptedState, sentinel_password_screen
from tests.property._publisher_strategies import ArbitraryError, all_leak_forms, probes
from tests.publisher_support import (
    FAILURE_POINTS,
    MINI,
    Failure,
    FakeHost,
    LogCapture,
    mcp_client,
    mini_states,
    rest_client,
)

KEY = "k" * 16
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": KEY,
    "GS_PUBLISH_FLOWS": "tk5-logon",
}
HEADERS = {"X-API-Key": KEY}
ARGS = {"userid": "ABCDEFGH"}
EXC_KINDS = ("S3270Error", "ConnectorTimeoutError", "ParseError", "ConfigurationError",
             "SessionClosedError", "Exception")
SCREENS = ("good", "wrong", "hidden")

_PKG_DIR = os.path.dirname(os.path.abspath(greenscreen.__file__))
_ROOT_DIR = os.path.dirname(_PKG_DIR)
FIXED_FORBIDDEN = tuple(dict.fromkeys((
    "Traceback", 'File "', "site-packages", "Screen(", "Field(", "SFToken(", "cell_grid",
    _PKG_DIR, _PKG_DIR.replace("\\", "/"), _ROOT_DIR, _ROOT_DIR.replace("\\", "/"),
)))
PATH_RE = re.compile(r"\.py\b")


# --------------------------------------------------------------------------
# The module app: built once, served by one loop on a helper thread
# --------------------------------------------------------------------------

class _Served:
    """The app, its two clients and the loop thread. ``current`` is the Fake_Host."""

    def __init__(self) -> None:
        self.current: FakeHost | None = None
        prepared = prepare(ENV)
        registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
        prepared = dataclasses.replace(prepared, registry=registry)
        self.app = build_app(
            # FakeClock: a poll costs no real time, only one recognition, so a long
            # interval keeps an Expect that waits out its timeout cheap.
            prepared, session_factory=self._factory, clock=FakeClock(), poll_interval=0.5
        )
        self.loop = asyncio.new_event_loop()
        self.http = None
        self.mcp = None
        self._ready = threading.Event()
        self._failed: BaseException | None = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, name="hostdata-loop", daemon=True)

    def _factory(self):
        assert self.current is not None
        return self.current()

    async def _driver(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with rest_client(self.app, headers=HEADERS) as http, \
                    mcp_client(self.app, "auto") as mcp:
                self.http, self.mcp = http, mcp
                self._ready.set()
                await self._stop.wait()
        except BaseException as err:  # noqa: BLE001 - reported to the starting thread
            self._failed = err
            self._ready.set()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._driver())

    def start(self) -> None:
        self._thread.start()
        assert self._ready.wait(30), "app did not start"
        assert self._failed is None, f"app failed to start: {type(self._failed).__name__}"

    def stop(self) -> None:
        if self._stop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(30)

    def run(self, coro, timeout: float = 30.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


@pytest.fixture(scope="module")
def served():
    s = _Served()
    s.start()
    try:
        yield s
    finally:
        s.stop()


# --------------------------------------------------------------------------
# Scenario strategy (local)
# --------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class Scenario:
    exc: str
    at: str | None  # None: no injected failure
    n: int
    screens: str
    marker: str
    hidden: str


SCENARIOS = st.builds(
    Scenario,
    st.sampled_from(EXC_KINDS),
    st.sampled_from((None, *FAILURE_POINTS, *FAILURE_POINTS)),
    st.integers(1, 2),
    st.sampled_from(SCREENS),
    probes("str", min_size=6, max_size=12),
    probes("str", min_size=4, max_size=8),
)


def _exception(kind: str, marker: str) -> BaseException:
    if kind == "S3270Error":
        return S3270Error(marker, action="injected", data_lines=[marker, marker + marker])
    if kind == "ConnectorTimeoutError":
        return ConnectorTimeoutError(marker, operation="injected", deadline=1.0)
    if kind == "ParseError":
        return ParseError(marker, raw=marker)
    if kind == "ConfigurationError":
        return ConfigurationError(marker, parameter_name="injected")
    if kind == "SessionClosedError":
        return SessionClosedError(marker)
    return ArbitraryError(marker)


def _host(s: Scenario) -> FakeHost:
    good = mini_states()
    if s.screens == "wrong":
        states = list(reversed(good))
    elif s.screens == "hidden":
        states = [ScriptedState(sentinel_password_screen(s.hidden)), *good[1:]]
    else:
        states = good
    failures = ()
    if s.at is not None:
        failures = (Failure(s.at, _exception(s.exc, s.marker), s.n),)
    return FakeHost(states, failures=failures)


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------

async def _rest(served: _Served):
    resp = await served.http.post("/flows/mini", json=ARGS)
    return resp.status_code, resp.text, "\n".join(f"{k}: {v}" for k, v in resp.headers.items())


async def _mcp(served: _Served):
    result = await asyncio.wait_for(served.mcp.call_tool("mini", ARGS), 20)
    texts = [getattr(c, "text", "") or "" for c in result.content]
    return result, "\n".join(texts) + "\n" + json.dumps(result.structured_content)


def _verdicts(where: str, text: str, forms: tuple[str, ...]) -> list[str]:
    """Descriptions of every Host_Data hit in ``text`` (never the matched text)."""
    out = [f"{where}: marker or hidden-text form #{i}" for i, f in enumerate(forms) if f in text]
    out += [f"{where}: forbidden text #{i}" for i, f in enumerate(FIXED_FORBIDDEN) if f in text]
    if PATH_RE.search(text):
        out.append(f"{where}: a .py file path")
    return out


@settings(max_examples=100, deadline=None)
@given(SCENARIOS)
def test_no_host_data_in_responses_or_logs(served, scn):
    # Feature: publisher, Property 7: No Host_Data in responses or logs
    host = _host(scn)
    forms = all_leak_forms([scn.marker, scn.hidden])
    served.current = host
    try:
        with LogCapture() as logs:
            status, rest_text, rest_headers = served.run(_rest(served))
            result, mcp_text = served.run(_mcp(served))
            logs.refresh()
    finally:
        host.release_all()
        served.current = None

    # The calls really happened and answered (no vacuous pass).
    body = json.loads(rest_text)
    assert isinstance(body, dict) and (set(body) == {"error"} or "outputs" in body)
    assert status in (200, 400, 404, 422, 429, 500, 502, 503, 504)
    assert isinstance(result.structured_content, dict)
    assert len(logs.call_records()) >= 2, "each Call writes one Call_Log_Record"
    assert host.closed == host.created and host.live == 0

    hits = _verdicts("rest body", rest_text, forms)
    hits += _verdicts("rest headers", rest_headers, forms)
    hits += _verdicts("mcp result", mcp_text, forms)
    for i, record in enumerate(logs.records):
        for text in record.texts():
            for d in _verdicts(f"log record {i} ({record.logger}, level {record.level})",
                               text, forms):
                if d not in hits:
                    hits.append(d)
    assert not hits, "Host_Data in output: " + "; ".join(hits)
