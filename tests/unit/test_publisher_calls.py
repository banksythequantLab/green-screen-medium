"""CallService tests against the Fake_Host (Requirements 3, 6, 8, 9, 10, 23). No live host.

Nothing here patches a loader: the Startup_Signatures are loaded once. Screens come
from ``captures/`` through the Fake_Host helpers. The Probe_Values are made up.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

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
        clock=transport_clock or FakeClock(),
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


def test_base_exception_from_close_is_reraised_without_waiting_for_the_deadline(caplog):
    boom = Boom("CLOSEBOOMPROBE")
    host = FakeHost(mini_states(), failures=[Failure("close", boom)])
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter, call_timeout=60.0)

    async def main():
        # hard bound far below the 60 s Call_Deadline: a hang fails here
        return await asyncio.wait_for(call(svc), timeout=10.0)

    started = time.monotonic()
    with pytest.raises(Boom) as info:
        asyncio.run(main())
    assert time.monotonic() - started < 10.0
    assert info.value is boom
    assert host.close_calls == 1 and limiter.in_flight == 0
    assert limiter.closes_at_release == [1]  # closed before the slot was released
    rec = only_record(caplog)
    assert rec["outcome"] == "internal_error"
    assert "close_failed" not in rec and "session_clean" not in rec
    assert "CLOSEBOOMPROBE" not in repr(vars(records(caplog)[0]))


def _run_base(svc, limit=10.0):
    """Run one call under a hard timeout far below the 60 s Call_Deadline."""
    async def main():
        return await asyncio.wait_for(call(svc), timeout=limit)

    started = time.monotonic()
    try:
        asyncio.run(main())
    finally:
        assert time.monotonic() - started < limit


def test_base_exception_from_open_is_reraised_after_close_and_slot_release(caplog):
    boom = Boom("OPENBOOMPROBE")
    host = FakeHost(mini_states(), failures=[Failure("open", boom)])
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter, call_timeout=60.0)
    with pytest.raises(Boom) as info:
        _run_base(svc)
    assert info.value is boom
    assert host.created == 1 and host.close_calls == 1 and limiter.in_flight == 0
    assert limiter.closes_at_release == [1]
    rec = only_record(caplog)
    assert rec["outcome"] == "internal_error"
    assert "close_failed" not in rec and "session_clean" not in rec
    assert "OPENBOOMPROBE" not in repr(vars(records(caplog)[0]))


def test_base_exception_from_factory_is_reraised_after_slot_release(caplog):
    boom = Boom("FACTBOOMPROBE")
    host = FakeHost(mini_states(), failures=[Failure("factory", boom)])
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter, call_timeout=60.0)
    with pytest.raises(Boom) as info:
        _run_base(svc)
    assert info.value is boom
    assert host.created == 0 and host.close_calls == 0 and limiter.in_flight == 0
    assert limiter.acquires == 1 and limiter.closes_at_release == [0]
    rec = only_record(caplog)
    assert rec["outcome"] == "internal_error" and "close_failed" not in rec


@pytest.mark.parametrize("first_at", ["open", "read_screen"])
def test_first_stored_base_exception_wins_over_one_from_close(first_at):
    first, second = Boom("FIRST"), Boom("SECOND")
    host = FakeHost(mini_states(), failures=[Failure(first_at, first), Failure("close", second)])
    svc = make(host, call_timeout=60.0)
    with pytest.raises(Boom) as info:
        _run_base(svc)
    assert info.value is first
    assert host.close_calls == 1 and svc._limiter.in_flight == 0


def test_base_exception_from_thread_start_closes_the_session_and_is_reraised(monkeypatch, caplog):
    from types import SimpleNamespace

    from greenscreen.publisher import calls

    boom = Boom("STARTBOOMPROBE")

    class BadThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise boom

    monkeypatch.setattr(calls, "threading", SimpleNamespace(Thread=BadThread, Event=threading.Event))
    host = FakeHost(mini_states())
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter, call_timeout=60.0)
    with pytest.raises(Boom) as info:
        _run_base(svc)
    assert info.value is boom
    assert host.created == 1 and host.opened == 0 and host.close_calls == 1
    assert limiter.in_flight == 0 and limiter.closes_at_release == [1]
    assert not svc._runs
    rec = only_record(caplog)
    assert rec["outcome"] == "internal_error" and "close_failed" not in rec


def test_base_exception_from_box_clear_in_the_worker_is_stored_and_reraised(monkeypatch, caplog):
    boom = Boom("CLEARBOOMPROBE")
    real_clear = SecretBox.clear
    loop_thread = threading.get_ident()

    def clear(self):
        if threading.get_ident() != loop_thread:
            raise boom
        real_clear(self)

    monkeypatch.setattr(SecretBox, "clear", clear)
    host = FakeHost(mini_states())
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter, call_timeout=60.0)
    with pytest.raises(Boom) as info:
        _run_base(svc)
    assert info.value is boom
    assert host.close_calls == 1 and limiter.in_flight == 0
    assert only_record(caplog)["outcome"] == "internal_error"


def test_base_exception_after_deadline_abort_beats_call_timeout(caplog):
    boom = Boom("LATEBOOMPROBE")
    host = FakeHost(mini_states(), block_read=1, failures=[Failure("close", boom)])
    limiter = SpyLimiter(1, host)
    svc = make(host, limiter=limiter, call_timeout=0.2)
    with pytest.raises(Boom) as info:
        _run_base(svc)
    assert info.value is boom
    assert host.aborted == 1 and host.close_calls == 1 and limiter.in_flight == 0
    assert only_record(caplog)["outcome"] == "internal_error"


def _abort_raising(host, exc):
    def factory():
        session = host()
        original = session.abort

        def abort():
            original()  # still releases the blocked read
            raise exc

        session.abort = abort
        return session

    return factory


def test_base_exception_from_abort_at_the_deadline_is_reraised_after_the_worker_ends(caplog):
    boom = Boom("ABORTBOOMPROBE")
    host = FakeHost(mini_states(), block_read=1)
    limiter = SpyLimiter(1, host)
    svc = make(_abort_raising(host, boom), limiter=limiter, call_timeout=0.2)
    with pytest.raises(Boom) as info:
        _run_base(svc)
    assert info.value is boom
    assert host.close_calls == 1 and limiter.in_flight == 0
    assert limiter.closes_at_release == [1]  # worker closed before the slot was released
    assert only_record(caplog)["outcome"] == "internal_error"


def test_base_exception_from_abort_during_drain_is_reraised_by_drain():
    boom = Boom("DRAINBOOMPROBE")
    host = FakeHost(mini_states(), block_read=1)
    svc = make(_abort_raising(host, boom))

    async def main():
        task = asyncio.create_task(call(svc))
        try:
            await until_blocked(host)
            with pytest.raises(Boom) as info:
                await asyncio.wait_for(svc.drain(0), 10.0)
            out = await asyncio.wait_for(task, 10.0)
            return info.value, out
        finally:
            host.release_all()

    got, out = asyncio.run(main())
    assert got is boom and out.code == "shutting_down"
    assert host.close_calls == 1 and svc._limiter.in_flight == 0


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


# --------------------------------------------------------------------------
# Frames of an exception path hold no value (Property 10 fixes)
# --------------------------------------------------------------------------

def _publisher_frames(err):
    tb = err.__traceback__
    while tb is not None:
        if str(tb.tb_frame.f_globals.get("__name__", "")).startswith("greenscreen.publisher"):
            yield tb.tb_frame
        tb = tb.tb_next


BOUND_PROBE = "BND4K9TW"  # a made-up bound password value


def test_run_slot_frame_holds_no_bound_value_after_a_cancelled_call():
    from greenscreen.publisher.calls import _Run

    host = FakeHost(mini_states(), block_read=1)
    bound = BoundValues({"mini": {"password": BOUND_PROBE}})
    registry = build_registry({"mini": (MINI, "test")}, bound, 30.0)
    svc = CallService(registry, bound, SIGS, Limiter(1), host, clock=FakeClock())

    async def main():
        task = asyncio.create_task(
            svc.execute(registry.get("mini"), SecretBox.adopt({"userid": PROBE}), "rest")
        )
        try:
            await until_blocked(host)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError as err:
                return err
            raise AssertionError("the call was not cancelled")
        finally:
            host.release_all()

    err = asyncio.run(main())
    runs = [
        v for f in _publisher_frames(err) if f.f_code.co_name == "_run_slot"
        for v in f.f_locals.values() if isinstance(v, _Run)
    ]
    assert runs, "no _run_slot frame with a run in the traceback"
    for run in runs:
        assert BOUND_PROBE not in list(run.bound.values())
        assert not run.bound
    assert BOUND_PROBE in list(bound.for_flow("mini").values())  # the vault itself is intact


class _Boom(BaseException):
    pass


def _string_frames(call, text):
    try:
        call(text)
    except _Boom as err:
        return [f for f in _publisher_frames(err) if f.f_code.co_name == "string"]
    raise AssertionError("expected _Boom")


def test_guarded_string_frame_does_not_keep_the_typed_text():
    from greenscreen.publisher.calls import _Guarded

    class Raising:
        def string(self, text):
            raise _Boom("x")

    frames = _string_frames(_Guarded(Raising(), threading.Event()).string, PROBE)
    assert frames
    assert all(f.f_locals.get("text") != PROBE for f in frames)


def test_guarded_string_frame_does_not_keep_the_text_when_the_call_is_aborted():
    from greenscreen.connector import SessionClosedError
    from greenscreen.publisher.calls import _Guarded

    aborted = threading.Event()
    aborted.set()
    guarded = _Guarded(object(), aborted)
    try:
        guarded.string(PROBE)
    except SessionClosedError as err:
        frames = [f for f in _publisher_frames(err) if f.f_code.co_name == "string"]
    assert frames and all(f.f_locals.get("text") != PROBE for f in frames)


def test_connector_session_string_frame_does_not_keep_the_typed_text():
    from greenscreen.publisher.calls import ConnectorSession

    class Conn:
        def string(self, text):
            raise _Boom("x")

    session = object.__new__(ConnectorSession)
    session._conn = Conn()
    frames = _string_frames(session.string, PROBE)
    assert frames
    assert all(f.f_locals.get("text") != PROBE for f in frames)
