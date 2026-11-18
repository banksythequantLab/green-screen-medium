"""Property 12 (task 7.7): the session lifecycle of a Call.

Each scenario runs one to three Calls of ``tk5-system-info`` in sequence through one
``CallService`` (limit 1, a ``Limiter`` that records what was closed when a Slot was
released). Every Call gets its own Fake_Host: success, the wrong screens, a failure
(including a ``BaseException``) at the factory, ``open``, any Session method or ``close``,
a blocked read that outlives the Call deadline, a cancellation while the read is blocked,
and Calls rejected before the Slot. No real sleep stands in for a state: the test polls
Fake_Host events with a hard deadline, so a hang fails the example instead of the suite.
The user id and password are made-up Probe_Values, not credentials.
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import time
from dataclasses import dataclass

from hypothesis import example, given, settings
from hypothesis import strategies as st

from greenscreen.connector import (
    ConnectorTimeoutError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.publisher.app import prepare
from greenscreen.publisher.calls import CallOutcome, CallService, Limiter
from greenscreen.publisher.vault import SecretBox
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import ArbitraryError, InjectedBase
from tests.publisher_support import FAILURE_POINTS, Failure, FakeHost, system_info_states

FLOW = "tk5-system-info"
ARGS = {"userid": "PRBU7Q2X", "password": "PRBP9Z4K"}
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_PUBLISH_FLOWS": FLOW,
}
_NORMAL_DEADLINE = 30.0  # the Call deadline of a Call that is not meant to time out
_SHORT_DEADLINE = 0.05  # the Call deadline of a Call whose read stays blocked
_HARD = 3.0  # hard limit for anything the test waits for; a hang fails here
_EXCS = (RuntimeError, OSError, ArbitraryError, SessionClosedError, S3270Error,
         ConnectorTimeoutError, InjectedBase)
_KINDS = (
    ["ok"] * 5 + ["wrong"] * 2 + ["fail"] * 8
    + ["timeout"] * 2 + ["cancel"] * 2 + ["bad_input", "unknown_flow", "closing", "busy"]
)


@functools.lru_cache(maxsize=1)
def _prepared():
    return prepare(ENV)


@functools.lru_cache(maxsize=1)
def _states():
    states = system_info_states()
    return states, list(reversed(states))


@dataclass(frozen=True)
class Plan:
    kind: str
    failure: Failure | None = None


_FAIL_POOL = tuple(Failure(at, exc, 1, None) for at in FAILURE_POINTS for exc in _EXCS)
_BASE_POINTS = ("factory", "open")
_CLOSE_POOL = (None,) * 3 + tuple(Failure("close", exc, 1, None) for exc in _EXCS)


@st.composite
def plans(draw):
    kind = draw(st.sampled_from(_KINDS))
    failure = None
    if kind == "fail":
        failure = draw(st.sampled_from(_FAIL_POOL))
        if failure.at in _BASE_POINTS and failure.exc is InjectedBase:
            # a fresh instance, so the test can check that the same object comes back
            failure = Failure(failure.at, InjectedBase("injected base"), 1, None)
    elif kind in ("timeout", "cancel", "ok", "wrong"):
        failure = draw(st.sampled_from(_CLOSE_POOL))
    return Plan(kind, failure)


def _host(plan: Plan) -> FakeHost:
    good, wrong = _states()
    failures = (plan.failure,) if plan.failure else ()
    block = 1 if plan.kind in ("timeout", "cancel") else None
    return FakeHost(wrong if plan.kind == "wrong" else good, failures=failures, block_read=block)


class _Limiter(Limiter):
    """A real Limiter that notes a Slot released while a created session is still open."""

    def __init__(self, limit: int, sessions: list) -> None:
        super().__init__(limit)
        self._sessions = sessions
        self.early_release: list[int] = []

    def release(self) -> None:
        for s in list(self._sessions):
            if s.close_calls == 0:
                self.early_release.append(s.number)
        super().release()


async def _until(predicate, what: str) -> None:
    deadline = time.monotonic() + _HARD
    while not predicate():
        assert time.monotonic() < deadline, f"hang: {what}"
        await asyncio.sleep(0)


async def _hard(task: asyncio.Future, what: str):
    try:
        return await asyncio.wait_for(asyncio.shield(task), _HARD)
    except asyncio.TimeoutError:
        raise AssertionError(f"hang: {what}") from None


async def _scenario(plan_list):
    prepared = _prepared()
    published = prepared.registry.get(FLOW)
    sessions: list = []  # every session the factory returned, across Calls
    hosts: list[FakeHost] = []
    current: list[FakeHost] = []

    def factory():
        session = current[0]()
        sessions.append(session)
        return session

    limiter = _Limiter(1, sessions)
    service = CallService(
        prepared.registry, prepared.bound, prepared.signatures, limiter, factory,
        clock=FakeClock(), poll_interval=0.01,
    )
    snapshots: list[tuple] = []  # (session, calls recorded when the Call was torn down)
    rejected_hosts: list[FakeHost] = []

    for plan in plan_list:
        host = _host(plan)
        current[:] = [host]
        hosts.append(host)
        kind = plan.kind
        timed_out = kind == "timeout"
        pub = dataclasses.replace(
            published, deadline=_SHORT_DEADLINE if timed_out else _NORMAL_DEADLINE
        )
        args = dict(ARGS)
        if kind == "bad_input":
            args["qxzjkw"] = "x"  # an undeclared Input
        if kind == "unknown_flow":
            out = service.precheck("no-such-flow")
            assert isinstance(out, CallOutcome) and out.code == "unknown_flow"
            rejected_hosts.append(host)
            continue
        if kind == "closing":
            service.closing = True
        if kind == "busy":
            assert limiter.try_acquire()
        before = len(sessions)
        try:
            task = asyncio.ensure_future(service.execute(pub, SecretBox.adopt(args), "rest"))
            if kind == "cancel":
                await _until(lambda: len(sessions) > before and sessions[-1].blocked.is_set(),
                             "the read did not block")
                task.cancel()
                try:
                    await _hard(task, "cancelled call did not end")
                except asyncio.CancelledError:
                    pass
                else:
                    raise AssertionError("cancellation did not reach the caller")
            else:
                try:
                    outcome = await _hard(task, "call did not finish")
                except InjectedBase as raised:
                    outcome = None  # a BaseException is re-raised to the caller (design)
                    f = plan.failure
                    if f is not None and f.at in _BASE_POINTS and isinstance(f.exc, BaseException):
                        # the very object injected, after teardown and Slot release
                        assert raised is f.exc
                        assert limiter.in_flight == 0
                        assert limiter.early_release == []
                        created = len(sessions) - before
                        assert created == (1 if f.at == "open" else 0)
                        for s in sessions[before:]:
                            assert s.close_calls == 1 and s.is_closed
                else:
                    f = plan.failure
                    assert not (
                        f is not None and f.at in _BASE_POINTS and isinstance(f.exc, BaseException)
                    ), "an injected BaseException was not re-raised"
                if kind == "ok" and plan.failure is None:
                    assert outcome is not None and outcome.code == "ok"
                if kind == "bad_input":
                    assert outcome.code == "input_invalid"
                if kind == "closing":
                    assert outcome.code == "shutting_down"
                if kind == "busy":
                    assert outcome.code == "busy"
                if timed_out and plan.failure is None:
                    assert outcome.code == "call_timeout"
        finally:
            service.closing = False
            if kind == "busy":
                limiter.release()
        if kind in ("closing", "busy", "bad_input"):
            rejected_hosts.append(host)
        if kind in ("timeout", "cancel") and len(sessions) > before:
            session = sessions[-1]
            snapshots.append((session, session.calls))
            host.release_all()
            await asyncio.sleep(0)
    for h in hosts:
        h.release_all()
    return service, limiter, sessions, hosts, rejected_hosts, snapshots


# Feature: publisher, Property 12: Session lifecycle
@settings(max_examples=100, deadline=None)
@example([Plan("fail", Failure("factory", InjectedBase("injected base"), 1, None))])
@example([Plan("fail", Failure("open", InjectedBase("injected base"), 1, None))])
@given(st.lists(plans(), min_size=1, max_size=3))
def test_session_lifecycle(plan_list):
    service, limiter, sessions, hosts, rejected, snapshots = asyncio.run(_scenario(plan_list))

    # the Slot count returns to zero
    assert limiter.in_flight == 0
    # no Slot was released while a created session was still open
    assert limiter.early_release == []
    # every created session was closed exactly once; none was reused
    assert len({id(s) for s in sessions}) == len(sessions)
    for s in sessions:
        assert s.close_calls == 1
        assert s.is_closed
    for h in hosts:
        assert h.closed == h.created
        assert h.close_calls == h.created
        assert h.live == 0
        for s in h.sessions:
            assert sum(1 for e in h.events_for(s.number) if e.method == "open") <= 1
    assert sum(h.created for h in hosts) == len(sessions)
    # a Call rejected before the Slot created zero sessions
    for h in rejected:
        assert h.factory_calls == 0 and h.created == 0 and h.events == []
    # nothing was sent to a session after its Call timed out or was cancelled
    for session, calls in snapshots:
        assert session.calls == calls
        assert session.is_aborted
