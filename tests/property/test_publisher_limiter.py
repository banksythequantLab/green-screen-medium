"""Property 11 (task 7.6): the Limiter never lets more than the limit through.

Concurrent Calls of ``tk5-system-info`` over REST and over MCP (both modes) share one
``CallService``. Every session blocks in its first ``read_screen`` until the test releases
it, so a Slot stays held while the test counts. No real sleep stands in for a state: the
test polls Fake_Host events (a short yield, with a hard deadline) and the transport clock
is a ``FakeClock``. The user id and password are made-up Probe_Values, not credentials.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import time

import httpx2
from hypothesis import given, settings
from hypothesis import strategies as st
from mcp import Client

from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.calls import Limiter
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import ArbitraryError
from tests.publisher_support import FAILURE_POINTS, FakeHost, Failure, system_info_states

FLOW = "tk5-system-info"
ARGS = {"userid": "PRBU7Q2X", "password": "PRBP9Z4K"}
KEY = {"X-API-Key": "k" * 16}
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_PUBLISH_FLOWS": FLOW,
}
TRANSPORTS = ("rest", "legacy", "auto")
_DEADLINE = 20.0


@functools.lru_cache(maxsize=1)
def _prepared():
    return prepare(ENV)


class _TrackingLimiter(Limiter):
    """A real Limiter that records the peak in flight and the refusals."""

    def __init__(self, limit: int) -> None:
        super().__init__(limit)
        self.peak = 0
        self.refused = 0

    def try_acquire(self) -> bool:
        ok = super().try_acquire()
        if ok:
            self.peak = max(self.peak, self.in_flight)
        else:
            self.refused += 1
        return ok


_FAILURE_TABLE = [None] * 12 + [
    (at, exc) for at in FAILURE_POINTS for exc in (RuntimeError, OSError, ArbitraryError)
]
_FAILURES = len(_FAILURE_TABLE)
# Weighted pool: mostly 1 to 4, sometimes up to the maximum of 64.
_LIMITS = [1] * 10 + [2] * 8 + [3] * 6 + [4] * 5 + [5, 9, 20, 64]


@st.composite
def scenarios(draw):
    # Threads dominate the cost, so small limits are drawn more often than large ones;
    # the whole range 1 to 64 is still reached.
    limit = draw(st.sampled_from(_LIMITS))
    n = draw(st.integers(1, limit + 2))
    # Per Call: a transport and one outcome per session ordinal (and per factory call):
    # success (most draws), a stop on the wrong screens, or a failure at a point.
    # One MCP mode per example (a second MCP client costs more than a call); both
    # modes are covered across examples.
    mode = draw(st.sampled_from(("legacy", "auto")))
    per_call = st.tuples(st.sampled_from(("rest", mode)), st.booleans(), st.integers(0, _FAILURES - 1))
    drawn = draw(st.lists(per_call, min_size=n, max_size=n))
    transports = [t for t, _, _ in drawn]
    outcomes = [(w, _FAILURE_TABLE[f]) for _, w, f in drawn]
    return limit, transports, outcomes


@functools.lru_cache(maxsize=1)
def _states_cached():
    states = system_info_states()
    return states, list(reversed(states))


class _Lazy:
    def __getitem__(self, i):
        return _states_cached()[i]


_STATES = _Lazy()


def _host(outcomes) -> FakeHost:
    failures = []
    for k, (_wrong, fail) in enumerate(outcomes, start=1):
        if fail is not None:
            at, exc = fail
            failures.append(Failure(at, exc, 1 if at != "factory" else k, None if at == "factory" else k))

    def script(number: int):
        wrong = outcomes[number - 1][0] if number <= len(outcomes) else False
        return _STATES[1] if wrong else _STATES[0]

    return FakeHost(script, failures=failures, block_read=1)


def _code(status_or_error, body) -> str:
    return "ok" if not status_or_error else body["error"]["code"]


async def _scenario(limit, transports, outcomes):
    prepared = _prepared()
    prepared = dataclasses.replace(
        prepared, settings=dataclasses.replace(prepared.settings, max_concurrency=limit)
    )
    host = _host(outcomes)
    peak_live = 0

    def factory():
        nonlocal peak_live
        session = host()
        peak_live = max(peak_live, host.live)
        return session

    app = build_app(prepared, session_factory=factory, clock=FakeClock(), poll_interval=0.01)
    limiter = _TrackingLimiter(limit)
    app.service._limiter = limiter
    n = len(transports)
    codes: list[str | None] = [None] * n

    async def call(i, rest, legacy, auto):
        kind = transports[i]
        if kind == "rest":
            resp = await rest.post(f"/flows/{FLOW}", json=ARGS)
            codes[i] = _code(resp.status_code != 200, resp.json())
        else:
            res = await (legacy if kind == "legacy" else auto).call_tool(FLOW, ARGS)
            codes[i] = _code(res.is_error, res.structured_content)

    async with app.lifespan():
        transport = httpx2.ASGITransport(app=app.asgi)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test", headers=KEY) as rest:
            async with contextlib.AsyncExitStack() as stack:
                # An MCP client costs more than a call, so open only the modes in use.
                legacy = await stack.enter_async_context(Client(app.server, mode="legacy")) if "legacy" in transports else None
                auto = await stack.enter_async_context(Client(app.server, mode="auto")) if "auto" in transports else None
                tasks = [asyncio.ensure_future(call(i, rest, legacy, auto)) for i in range(n)]
                try:
                    # Stable: every Call is finished or has its session blocked in a read.
                    deadline = time.monotonic() + _DEADLINE
                    while True:
                        done = sum(t.done() for t in tasks)
                        blocked = sum(1 for s in list(host.sessions) if s.blocked.is_set() and not s.is_closed)
                        # Sample while Slots are held, before anything is released.
                        assert limiter.in_flight <= limit and host.live <= limit
                        if done + blocked == n:
                            break
                        assert time.monotonic() < deadline, "calls did not settle"
                        await asyncio.sleep(0)
                    assert limiter.in_flight == blocked
                    assert limiter.peak <= limit and peak_live <= limit
                finally:
                    host.release_all()
                results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), _DEADLINE)
                for r in results:
                    assert not isinstance(r, BaseException)

    busy = sum(1 for c in codes if c == "busy")
    assert all(c is not None for c in codes)
    return limiter, host, busy, peak_live


# Feature: publisher, Property 11: The Limiter never lets more than the limit through
@settings(max_examples=100, deadline=None)
@given(scenarios())
def test_limiter_never_lets_more_than_the_limit_through(scenario):
    limit, transports, outcomes = scenario
    limiter, host, busy, peak_live = asyncio.run(_scenario(limit, transports, outcomes))
    n = len(transports)
    # in flight never above the limit; Slots and live sessions return to zero
    assert limiter.peak <= limit
    assert peak_live <= limit
    assert limiter.in_flight == 0
    assert host.live == 0
    assert host.closed == host.created
    # every rejection is `busy`, was not queued and opened no session: the factory ran
    # exactly once for each Call that got a Slot
    assert busy == limiter.refused
    assert host.factory_calls == n - busy
