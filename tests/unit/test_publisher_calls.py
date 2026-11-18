"""CallService tests against the Fake_Host (Requirements 3, 6, 8, 9, 10, 23). No live host.

Nothing here patches a loader: the Startup_Signatures are loaded once. Screens come
from ``captures/`` through the Fake_Host helpers. The Probe_Values are made up.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading

import pytest

from greenscreen.flow.model import ExpectStep, Flow, KeyStep
from greenscreen.publisher.calls import CallOutcome, CallService, Limiter
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues, SecretBox
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import FakeClock, ScriptedState, blank_screen, capture
from tests.publisher_support import MINI, Failure, FakeHost, mini_states

SIGS = load_bundled_signatures()
PROBE = "PRB7Q2XZ"  # a made-up userid value
LOGGER = "greenscreen.publisher"
LOG_FIELDS = {
    "call_id", "flow", "transport", "outcome", "duration_ms",
    "step_index", "close_failed", "session_clean",
}

# a Flow that tolerates the menu while it waits for the logon screen: ends in `timeout`
TIMEOUT_FLOW = Flow(
    "slow", (ExpectStep(("tk5-logon",), ("ispf-primary-menu",), 1.0),)
)
# the main phase works, the finally phase meets an unknown screen
FINALLY_FLOW = Flow(
    "fin",
    (ExpectStep(("tk5-logon",)),),
    finally_steps=(
        ExpectStep(("tk5-logon",)), KeyStep("enter"), ExpectStep(("ispf-primary-menu",))
    ),
)

_seen: list[object] = []


@pytest.fixture(autouse=True)
def _no_cancelled_in_responses(caplog):
    """Requirement 8.8: the text `cancelled` is in no CallOutcome of this file."""
    caplog.set_level(logging.INFO, logger=LOGGER)
    _seen.clear()
    yield
    for out in _seen:
        assert "cancelled" not in repr(out)
        assert "cancelled" not in json.dumps(out.body)


class SpyLimiter(Limiter):
    def __init__(self, limit: int, host: FakeHost) -> None:
        super().__init__(limit)
        self.host = host
        self.acquires = 0
        self.closes_at_release: list[int] = []

    def try_acquire(self) -> bool:
        self.acquires += 1
        return super().try_acquire()

    def release(self) -> None:
        self.closes_at_release.append(self.host.close_calls)
        super().release()


def make(host, flows=None, *, call_timeout=30.0, limiter=None, transport_clock=None):
    flows = flows or {"mini": MINI}
    registry = build_registry({n: (f, "test") for n, f in flows.items()}, BoundValues(), call_timeout)
    return CallService(
        registry, BoundValues(), SIGS, limiter or Limiter(1), host,
        call_timeout=call_timeout, shutdown_grace=1.0, clock=transport_clock or FakeClock(),
    )


async def call(svc, name="mini", values=None, transport="rest"):
    pre = svc.precheck(name, transport)
    if isinstance(pre, CallOutcome):
        _seen.append(pre)
        return pre
    box = SecretBox.adopt(dict({"userid": PROBE} if values is None else values))
    out = await svc.execute(pre, box, transport)
    _seen.append(out)
    return out


def records(caplog):
    return [r for r in caplog.records if r.name == LOGGER and r.getMessage() == "call finished"]


def extra(record) -> dict:
    return {k: getattr(record, k) for k in LOG_FIELDS if hasattr(record, k)}


def only_record(caplog) -> dict:
    recs = records(caplog)
    assert len(recs) == 1
    return extra(recs[0])


async def until_blocked(host, n=1):
    for _ in range(500):
        if len(host.sessions) >= n and host.sessions[n - 1].blocked.is_set():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("no call became blocked")


def assert_clean_log(caplog, *secrets):
    for r in records(caplog):
        text = repr(vars(r))
        for s in (PROBE, "Logon ===>", *secrets):
            assert s not in text
        assert not (set(extra(r)) - LOG_FIELDS)


# --------------------------------------------------------------------------
# Lifecycle
# --------------------------------------------------------------------------

def test_success_closes_before_slot_release_and_uses_one_session_per_call(caplog):
    host = FakeHost(mini_states())
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter)

    async def main():
        a = await call(svc)
        b = await call(svc)
        return a, b

    a, b = asyncio.run(main())
    assert a.code == b.code == "ok"
    assert set(a.body) == {"flow", "outputs", "audit"} and a.session_clean is None
    assert (host.created, host.opened, host.closed, host.close_calls) == (2, 2, 2, 2)
    assert host.sessions[0] is not host.sessions[1]
    assert limiter.closes_at_release == [1, 2]  # closed before each release
    assert limiter.in_flight == 0
    assert [e["outcome"] for e in map(extra, records(caplog))] == ["ok", "ok"]
    assert_clean_log(caplog, a.body["outputs"]["RELEASE"])


def test_close_raising_sets_close_failed_and_keeps_the_response(caplog):
    host = FakeHost(mini_states(), failures=[Failure("close", RuntimeError, message="CLOSEPROBE-text")])
    svc = make(host)
    out = asyncio.run(call(svc))
    assert out.code == "ok" and out.close_failed is True
    rec = only_record(caplog)
    assert rec["close_failed"] is True and rec["outcome"] == "ok"
    assert "CLOSEPROBE" not in repr(vars(records(caplog)[0]))
    assert svc._limiter.in_flight == 0


def test_open_failure_gives_host_unavailable_with_the_session_closed(caplog):
    host = FakeHost(mini_states(), failures=[Failure("open", RuntimeError)])
    limiter = SpyLimiter(1, host)
    out = asyncio.run(call(make(host, limiter=limiter)))
    assert out.code == "host_unavailable"
    assert out.body == {"error": {"code": "host_unavailable", "message": "The host session could not be opened."}}
    assert (host.created, host.opened, host.closed) == (1, 0, 1)
    assert limiter.closes_at_release == [1] and limiter.in_flight == 0
    rec = only_record(caplog)
    assert rec["outcome"] == "host_unavailable" and "session_clean" not in rec


def test_factory_failure_gives_host_unavailable_and_releases_the_slot(caplog):
    host = FakeHost(mini_states(), failures=[Failure("factory", RuntimeError)])
    limiter = SpyLimiter(1, host)
    out = asyncio.run(call(make(host, limiter=limiter)))
    assert out.code == "host_unavailable" and host.created == 0
    assert limiter.in_flight == 0
    assert "session_clean" not in only_record(caplog)


def test_run_flow_runs_off_the_event_loop_thread():
    host = FakeHost(mini_states())
    loop_thread = threading.get_ident()
    asyncio.run(call(make(host)))
    session_events = [e for e in host.events if e.session is not None]
    assert session_events
    assert all(e.thread != loop_thread for e in session_events if e.method != "abort")
    assert [e.thread for e in host.events if e.method == "factory"] == [loop_thread]


# --------------------------------------------------------------------------
# Validation, busy, precheck
# --------------------------------------------------------------------------

@pytest.mark.parametrize("values", [{}, {"userid": "TOOLONGUSERID"}, {"userid": PROBE, "extra": "x"}])
def test_invalid_input_stops_before_slot_and_factory(values, caplog):
    host = FakeHost(mini_states())
    limiter = SpyLimiter(1, host)
    out = asyncio.run(call(make(host, limiter=limiter), values=values))
    assert out.code == "input_invalid"
    assert host.factory_calls == 0 and limiter.acquires == 0
    assert PROBE not in json.dumps(out.body) and "TOOLONGUSERID" not in json.dumps(out.body)
    assert only_record(caplog)["outcome"] == "input_invalid"


def test_busy_rejects_at_once_without_queueing_or_a_session(caplog):
    host = FakeHost(mini_states(), block_read=1)
    svc = make(host)

    async def main():
        first = asyncio.create_task(call(svc))
        try:
            await until_blocked(host)
            second = await asyncio.wait_for(call(svc), 2.0)
            factory_calls_while_busy = host.factory_calls
        finally:
            host.release_all()
        return second, factory_calls_while_busy, await first

    second, factory_calls, first = asyncio.run(main())
    assert second.code == "busy" and factory_calls == 1
    assert second.body["error"]["message"] == "All sessions are in use."
    assert first.code == "ok" and svc._limiter.in_flight == 0
    assert [extra(r)["outcome"] for r in records(caplog)] == ["busy", "ok"]


def test_precheck_rejects_unknown_flow_and_shutdown_with_a_log_record(caplog):
    host = FakeHost(mini_states())
    svc = make(host)
    out = svc.precheck("nope", "mcp")
    _seen.append(out)
    assert isinstance(out, CallOutcome) and out.code == "unknown_flow"
    rec = only_record(caplog)
    assert rec["flow"] == "unknown" and rec["transport"] == "mcp" and rec["outcome"] == "unknown_flow"
    assert not isinstance(svc.precheck("mini"), CallOutcome)  # a known flow resolves
    svc.begin_shutdown()
    out2 = svc.precheck("mini", "rest")
    _seen.append(out2)
    assert out2.code == "shutting_down" and host.factory_calls == 0
    assert extra(records(caplog)[-1])["flow"] == "mini"
    assert "session_clean" not in extra(records(caplog)[-1])


# --------------------------------------------------------------------------
# Deadline, cancellation, BaseException, drain
# --------------------------------------------------------------------------

def test_deadline_with_blocked_read_gives_call_timeout_and_aborts(caplog):
    host = FakeHost(mini_states(), block_read=1)
    limiter = SpyLimiter(1, host)
    svc = make(host, call_timeout=0.3, limiter=limiter)
    try:
        out = asyncio.run(call(svc))
    finally:
        host.release_all()
    assert out.code == "call_timeout" and out.step_index is None
    assert out.body == {"error": {"code": "call_timeout", "message": "The call did not finish in time."}}
    assert out.session_clean is False
    assert host.sessions[0].is_aborted and host.aborted == 1 and host.closed == 1
    assert limiter.in_flight == 0 and limiter.closes_at_release == [1]
    # no key reached the host, before or after the abort
    assert not [e for e in host.events if e.method in ("string", "enter", "clear", "pf", "pa")]
    rec = only_record(caplog)
    assert rec["outcome"] == "call_timeout" and rec["session_clean"] is False
    assert "step_index" not in rec


def test_cancellation_tears_down_logs_cancelled_and_reraises(caplog):
    host = FakeHost(mini_states(), block_read=1)
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter)

    async def main():
        task = asyncio.create_task(call(svc))
        try:
            await until_blocked(host)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            host.release_all()

    asyncio.run(main())
    assert host.aborted == 1 and host.closed == 1 and limiter.in_flight == 0
    rec = only_record(caplog)
    assert rec["outcome"] == "cancelled" and rec["session_clean"] is False
    assert not _seen  # a cancelled call produced no response


def test_cancellation_while_closing_logs_shutting_down(caplog):
    host = FakeHost(mini_states(), block_read=1)
    svc = make(host)

    async def main():
        task = asyncio.create_task(call(svc))
        try:
            await until_blocked(host)
            svc.begin_shutdown()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            host.release_all()

    asyncio.run(main())
    rec = only_record(caplog)
    assert rec["outcome"] == "shutting_down" and rec["session_clean"] is False
    assert host.aborted == 1 and host.closed == 1


class Boom(BaseException):
    pass


def test_base_exception_is_reraised_unchanged_after_teardown(caplog):
    boom = Boom("BOOMPROBE")
    host = FakeHost(mini_states(), failures=[Failure("read_screen", boom)])
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter)
    with pytest.raises(Boom) as info:
        asyncio.run(call(svc))
    assert info.value is boom
    assert host.closed == 1 and limiter.in_flight == 0
    rec = only_record(caplog)
    assert rec["outcome"] == "internal_error" and "session_clean" not in rec
    assert "BOOMPROBE" not in repr(vars(records(caplog)[0]))


def test_drain_tears_down_an_open_call_and_the_call_logs_shutting_down(caplog):
    host = FakeHost(mini_states(), block_read=1)
    svc = make(host)

    async def main():
        task = asyncio.create_task(call(svc))
        try:
            await until_blocked(host)
            await svc.drain(0)
            out = await asyncio.wait_for(task, 5.0)
            after = await call(svc)  # new calls are refused once shutting down
            return out, after
        finally:
            host.release_all()

    out, after = asyncio.run(main())
    assert out.code == "shutting_down" and out.session_clean is False
    assert after.code == "shutting_down"
    assert host.aborted == 1 and host.closed == 1 and host.created == 1
    recs = [extra(r) for r in records(caplog)]
    assert recs[0] == {**recs[0], "outcome": "shutting_down", "session_clean": False}
    assert recs[1]["outcome"] == "shutting_down" and "session_clean" not in recs[1]
    assert svc._limiter.in_flight == 0


# --------------------------------------------------------------------------
# Flow stops, session_clean and the log record
# --------------------------------------------------------------------------

def _stop_case(name):
    if name == "unknown_screen":
        return MINI, [ScriptedState(blank_screen())]
    if name == "unknown_screen_finally":
        return FINALLY_FLOW, [ScriptedState(capture("tk5-logon")), ScriptedState(blank_screen())]
    if name == "unexpected_screen":
        return MINI, [ScriptedState(capture("ispf-primary-menu"))]
    if name == "timeout":
        return TIMEOUT_FLOW, [ScriptedState(capture("ispf-primary-menu"))]
    raise AssertionError(name)


@pytest.mark.parametrize(
    "case, code, clean",
    [
        ("unknown_screen", "unknown_screen", False),
        ("unknown_screen_finally", "unknown_screen", False),
        ("unexpected_screen", "unexpected_screen", None),
        ("timeout", "timeout", None),
    ],
)
def test_flow_stops_carry_the_flow_stop_members_and_session_clean(case, code, clean, caplog):
    flow, states = _stop_case(case)
    host = FakeHost(states)
    svc = make(host, {flow.name: flow})
    values = {"userid": PROBE} if flow is MINI else {}
    out = asyncio.run(call(svc, flow.name, values))
    assert out.code == code
    err = out.body["error"]
    assert err["code"] == code
    assert set(err) == {"code", "message", "step_index", "kind", "expected", "summary", "audit"}
    assert out.step_index == err["step_index"]
    assert out.session_clean is clean
    if case == "unknown_screen_finally":
        assert any(a["phase"] == "finally" for a in err["audit"])
    rec = only_record(caplog)
    assert rec["outcome"] == code and rec["step_index"] == err["step_index"]
    if clean is False:
        assert rec["session_clean"] is False
    else:
        assert "session_clean" not in rec
    assert host.closed == 1 and host.aborted == 0
    assert_clean_log(caplog)


def test_success_log_has_no_session_clean_and_no_value(caplog):
    host = FakeHost(mini_states())
    out = asyncio.run(call(make(host)))
    rec = only_record(caplog)
    assert rec["outcome"] == "ok" and set(rec) == {"call_id", "flow", "transport", "outcome", "duration_ms"}
    assert isinstance(rec["duration_ms"], int) and rec["flow"] == "mini" and rec["transport"] == "rest"
    assert_clean_log(caplog, *map(str, out.body["outputs"].values()))
