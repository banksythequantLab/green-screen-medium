"""Limits and outcomes of one Ask question (spec ask, task 2.12, Requirements 3, 6 and 11).

Whole-route examples over the Fake_Host and a ``FakeAdapter`` (one for each outcome of the
design's outcome table), the shield test with ``block_read``, the Ask_Gate, busy repeats,
``shutting_down`` and ``internal_error`` with a partial trace. No live host, no real model.
"""
from __future__ import annotations

import asyncio
import json
import time

import anyio
import pytest

from greenscreen.publisher.ask.agent import Limits, Progress, run_question
from greenscreen.publisher.ask.codes import ASK_HTTP_STATUS
from tests.ask_support import (
    FLOW,
    AskFakeClock,
    Fail,
    FakeAdapter,
    FakePort,
    Turn,
    error_result,
    ok_result,
    ask_post,
    build_ask_app,
    no_network,  # noqa: F401  (autouse)
)
from tests.publisher_support import FakeHost, LogCapture, system_info_states

CALL = ((FLOW, '{"userid": "abc"}'),)


def once(script, *, env=None, question="Who is signed on?", clock=None, host=None, closing=False):
    """Run one question over the whole route and return ``(reply, app, adapter)``."""
    clock = clock if clock is not None else AskFakeClock()
    adapter = FakeAdapter(script, clock=clock)
    ask = build_ask_app(env, adapter, host, clock)
    if closing:
        ask.app.service.closing = True

    async def go():
        async with ask.app.lifespan():
            return await ask_post(ask, question)

    return asyncio.run(go()), ask, adapter


def error_of(reply):
    body = reply.json()
    assert set(body) == {"error"}, body
    return body["error"]


def tool_steps(body_trace):
    return [s for s in body_trace["steps"] if s["type"] == "tool"]


# --------------------------------------------------------------------------
# One example per outcome of the table
# --------------------------------------------------------------------------

def test_outcome_ok_a_final_answer_is_200_and_not_truncated():
    reply, _, _ = once([Turn(answer="Release 8.")])
    assert reply.status == 200
    body = reply.json()
    assert body["answer"] == "Release 8." and body["truncated"] is False
    assert body["trace"]["model_turns"] == 1 and body["trace"]["tool_calls"] == 0


def test_outcome_ok_a_long_answer_is_cut_and_marked_truncated():
    reply, _, _ = once([Turn(answer="x" * 150)], env={"GS_ASK_MAX_ANSWER_CHARS": "100"})
    body = reply.json()
    assert reply.status == 200 and body["answer"] == "x" * 100 and body["truncated"] is True


def test_outcome_turn_limit_is_422_with_the_trace():
    reply, _, adapter = once([Turn(calls=CALL), Turn(answer="never")], env={"GS_ASK_MAX_TURNS": "1"})
    err = error_of(reply)
    assert (reply.status, err["code"]) == (422, "turn_limit") and adapter.calls == 1
    assert err["trace"]["model_turns"] == 1 and len(tool_steps(err["trace"])) == 1


def test_outcome_tool_limit_is_422_after_every_call_of_the_turn_was_answered():
    reply, ask, adapter = once([Turn(calls=CALL * 3), Turn(answer="never")], env={"GS_ASK_MAX_TOOL_CALLS": "1"})
    err = error_of(reply)
    assert (reply.status, err["code"]) == (422, "tool_limit") and adapter.calls == 1
    steps = tool_steps(err["trace"])
    assert [(s["code"], s.get("reason")) for s in steps] == [
        ("ok", None), ("rejected", "tool_limit"), ("rejected", "tool_limit"),
    ]
    assert ask.host.created == 1  # only the first call reached the host


def test_outcome_ask_timeout_is_504_when_remaining_is_below_the_model_timeout():
    # T 95, M 20, C 50: a first turn of 80 s leaves 15 s, below M
    reply, _, adapter = once([Turn(calls=CALL, seconds=80.0), Turn(answer="never")])
    err = error_of(reply)
    assert (reply.status, err["code"]) == (504, "ask_timeout") and adapter.calls == 1
    (step,) = tool_steps(err["trace"])
    assert (step["code"], step["reason"], step["result"]) == ("rejected", "not_enough_time", None)


def test_outcome_not_enough_time_for_a_tool_goes_on_to_the_next_model_turn():
    # Remaining 65 after the first turn: below C + M = 70 (tool refused) and above M (turn runs)
    reply, ask, _ = once([Turn(calls=CALL, seconds=30.0), Turn(answer="The tool could not run.")])
    body = reply.json()
    assert reply.status == 200 and body["answer"] == "The tool could not run."
    (step,) = tool_steps(body["trace"])
    assert (step["code"], step["reason"], step["ok"]) == ("rejected", "not_enough_time", False)
    assert body["trace"]["tool_calls"] == 1 and ask.host.created == 0


@pytest.mark.parametrize("kind,code,status", [
    ("unreachable", "model_unreachable", 502), ("refused", "model_refused", 502),
    ("unusable", "model_unusable", 502), ("busy", "model_busy", 503),
])
def test_outcome_model_failures_keep_their_codes_and_statuses(kind, code, status):
    reply, _, _ = once([Fail(kind)])
    err = error_of(reply)
    assert (reply.status, err["code"]) == (status, code) == (ASK_HTTP_STATUS[code], code)
    assert err["trace"]["model_turns"] == 1


def test_outcome_a_turn_with_neither_a_tool_call_nor_an_answer_is_model_unusable():
    reply, _, _ = once([Turn(answer="  ")])
    assert (reply.status, error_of(reply)["code"]) == (502, "model_unusable")


def test_outcome_a_failed_tool_call_is_not_a_failed_question():
    # a second question over the same Fake_Host would not log on: the flow gets a wrong screen
    reply, _, _ = once([Turn(calls=((FLOW, '{"userid": "waytoolongforthefield"}'),)), Turn(answer="Input rejected.")])
    body = reply.json()
    assert reply.status == 200 and body["answer"] == "Input rejected."
    (step,) = tool_steps(body["trace"])
    assert step["ok"] is False and step["code"] == "input_invalid"


def test_outcome_question_invalid_is_422_without_a_trace_or_a_model_call():
    long_question = "q" * 501
    reply, _, adapter = once([Turn(answer="never")], question=long_question)
    err = error_of(reply)
    assert (reply.status, err["code"]) == (422, "question_invalid") and "trace" not in err
    assert adapter.calls == 0


def test_outcome_shutting_down_before_the_question_is_503_and_calls_nothing():
    reply, ask, adapter = once([Turn(answer="never")], closing=True)
    err = error_of(reply)
    assert (reply.status, err["code"]) == (503, "shutting_down") and adapter.calls == 0


def test_outcome_internal_error_is_500_with_the_partial_trace():
    def boom(messages, tools):
        raise RuntimeError("LEAKPROBE-should-not-appear")

    reply, _, _ = once([Turn(calls=CALL), boom])
    err = error_of(reply)
    assert (reply.status, err["code"]) == (500, "internal_error")
    assert "LEAKPROBE" not in reply.raw.decode()
    assert err["trace"]["model_turns"] == 2 and len(tool_steps(err["trace"])) == 1
    assert tool_steps(err["trace"])[0]["code"] == "ok"


# --------------------------------------------------------------------------
# The Ask_Gate and the Daily_Budget
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,first,env,question,status", [
    ("ok", Turn(answer="a"), None, "Q?", 200),
    ("model_failure", Fail("unreachable"), None, "Q?", 502),
    ("model_unusable", Turn(answer=""), None, "Q?", 502),
    ("turn_limit", Turn(calls=CALL), {"GS_ASK_MAX_TURNS": "1"}, "Q?", 422),
    ("question_invalid", None, None, "", 422),
])
def test_the_gate_is_released_on_every_path(name, first, env, question, status):
    script = ([first] if first is not None else []) + [Turn(answer="again")]
    clock = AskFakeClock()
    ask = build_ask_app(env, FakeAdapter(script, clock=clock), None, clock)

    async def go():
        async with ask.app.lifespan():
            one = await ask_post(ask, question)
            two = await ask_post(ask, "Second?")
            return one, two

    one, two = asyncio.run(go())
    assert one.status == status, one.raw[:200]
    assert two.status == 200 and two.json()["answer"] in {"again", "a"}  # not busy


def test_the_gate_is_released_after_an_internal_error():
    def boom(messages, tools):
        raise RuntimeError("x")

    clock = AskFakeClock()
    ask = build_ask_app(None, FakeAdapter([boom, Turn(answer="again")], clock=clock), None, clock)

    async def go():
        async with ask.app.lifespan():
            return await ask_post(ask, "Q?"), await ask_post(ask, "Q2?")

    one, two = asyncio.run(go())
    assert one.status == 500 and two.status == 200


async def wait_blocked(host: FakeHost, seconds: float = 10.0) -> None:
    began = time.monotonic()
    while not (host.sessions and host.sessions[0].blocked.is_set()):
        if time.monotonic() - began > seconds:
            raise AssertionError("the host read never blocked")
        await asyncio.sleep(0.01)


def logged_off(host: FakeHost) -> bool:
    return any(e.method == "string" and e.args == ("LOGOFF",) for e in host.events)


def test_a_second_question_while_one_runs_is_busy_at_once_and_uses_no_budget():
    clock = AskFakeClock()
    host = FakeHost(system_info_states(), block_read=1)
    adapter = FakeAdapter([Turn(calls=CALL), Turn(answer="first"), Turn(answer="third")], clock=clock)
    ask = build_ask_app({"GS_ASK_DAILY_LIMIT": "2"}, adapter, host, clock)

    async def go():
        async with ask.app.lifespan():
            first = asyncio.create_task(ask_post(ask, "One?"))
            await wait_blocked(host)
            busy = await ask_post(ask, "Two?")
            host.release_all()
            one = await first
            three = await ask_post(ask, "Three?")
            four = await ask_post(ask, "Four?")
            return busy, one, three, four

    busy, one, three, four = asyncio.run(go())
    assert busy.status == 429 and busy.headers["retry-after"] == "1"
    err = error_of(busy)
    assert err["code"] == "busy" and "trace" not in err
    assert one.status == 200 and one.json()["answer"] == "first"
    assert three.status == 200  # the busy question took nothing from the budget of 2
    assert four.status == 429 and error_of(four)["code"] == "daily_limit"
    assert four.headers["retry-after"] == "43200"  # the fake clock stands at 12:00 UTC
    assert adapter.calls == 3  # the fourth question never reached the model


# --------------------------------------------------------------------------
# A started tool call is never canceled
# --------------------------------------------------------------------------

def test_a_tool_call_in_flight_when_the_deadline_passes_finishes_and_runs_its_logoff_steps():
    clock = AskFakeClock()
    host = FakeHost(system_info_states(), block_read=1)
    adapter = FakeAdapter([Turn(calls=CALL), Turn(answer="never asked")], clock=clock)
    ask = build_ask_app(None, adapter, host, clock)

    async def go():
        async with ask.app.lifespan():
            task = asyncio.create_task(ask_post(ask, "Who is signed on?"))
            await wait_blocked(host)
            clock.advance(500.0)  # the Question_Deadline passes while the call runs
            await asyncio.sleep(0.1)
            aborts_while_running = host.abort_calls
            host.release_all()
            return aborts_while_running, await task

    aborts_while_running, reply = asyncio.run(go())
    assert aborts_while_running == 0 and host.abort_calls == 0
    err = error_of(reply)
    assert (reply.status, err["code"]) == (504, "ask_timeout")
    (step,) = tool_steps(err["trace"])
    assert (step["ok"], step["code"]) == (True, "ok")  # the call came back with its outputs
    assert host.closed == 1 and logged_off(host)
    assert adapter.calls == 1


async def direct_post(ask, question) -> None:
    """``POST /ask`` driven in the caller's own task (``call_scope`` wraps the app in
    ``asyncio.wait_for``, a second task, so an anyio cancel scope would not reach it)."""
    body = json.dumps({"question": question}).encode()
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await anyio.sleep_forever()

    async def send(message):
        return None

    headers = [(b"x-api-key", ask.api_key.encode()), (b"content-type", b"application/json")]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": "/ask", "raw_path": b"/ask", "query_string": b"", "root_path": "", "headers": headers,
        "server": ("test", 80), "client": ("127.0.0.1", 50000),
    }
    await ask.app.asgi(scope, receive, send)


def test_canceling_the_request_while_a_tool_runs_does_not_cancel_the_tool_and_frees_the_gate():
    clock = AskFakeClock()
    host = FakeHost(system_info_states(), block_read=1)
    adapter = FakeAdapter([Turn(calls=CALL), Turn(answer="after")], clock=clock)  # the canceled question never asks again
    ask = build_ask_app(None, adapter, host, clock)
    seen: dict = {}

    async def go():
        async with ask.app.lifespan():
            scopes: list[anyio.CancelScope] = []

            async def question():
                with anyio.CancelScope() as scope:
                    scopes.append(scope)
                    await direct_post(ask, "Who is signed on?")
                seen["canceled"] = scope.cancel_called

            async with anyio.create_task_group() as group:
                group.start_soon(question)
                await wait_blocked(host)
                scopes[0].cancel()
                await anyio.sleep(0.15)
                seen["aborts_while_running"] = host.abort_calls
                host.release_all()
            seen["after"] = await ask_post(ask, "Next?")

    with LogCapture() as logs:
        logs.refresh()
        asyncio.run(go())
    assert seen["canceled"] is True and seen["aborts_while_running"] == 0
    assert host.abort_calls == 0 and host.closed == 1 and logged_off(host)
    assert seen["after"].status == 200 and seen["after"].json()["answer"] == "after"  # the gate is free
    records = [r for r in logs.records if r.message == "ask finished"]
    assert [r.fields["outcome"] for r in records] == ["internal_error", "ok"]


# --------------------------------------------------------------------------
# Busy repeats, shutting_down and partial traces at the agent
# --------------------------------------------------------------------------

def agent_run(adapter, port, clock, *, closing=lambda: False, end=1000.0):
    prog = Progress()
    lim = Limits(max_turns=8, max_tool_calls=6, model_timeout=25.0, max_answer=2000, max_result=4000)
    asyncio.run(run_question(
        "Q?", port=port, adapter=adapter, lim=lim, clock=clock, closing=closing,
        allowed={FLOW}, worst={FLOW: 40.0}, end=end, prog=prog,
    ))
    return prog


def test_busy_repeats_do_not_count_against_the_tool_limit_and_do_not_call_the_model():
    clock = AskFakeClock()
    adapter = FakeAdapter([Turn(calls=CALL), Turn(answer="ok")], clock=clock)
    port = FakePort(results={FLOW: [error_result("busy"), error_result("busy"), ok_result(FLOW)]}, clock=clock)
    prog = agent_run(adapter, port, clock)
    assert prog.tool_calls == 1 and adapter.calls == 2 and clock.sleeps == [1.0, 1.0]
    assert prog.answer == "ok"


def test_a_busy_result_that_stays_busy_stops_the_question_with_busy():
    clock = AskFakeClock()
    adapter = FakeAdapter([Turn(calls=CALL), Turn(answer="never")], clock=clock)
    prog = agent_run(adapter, FakePort(results={FLOW: error_result("busy")}, clock=clock), clock)
    assert prog.stop_code == "busy" and adapter.calls == 1


def test_a_shutting_down_tool_result_stops_without_a_repeat():
    clock = AskFakeClock()
    adapter = FakeAdapter([Turn(calls=CALL), Turn(answer="never")], clock=clock)
    port = FakePort(results={FLOW: error_result("shutting_down")}, clock=clock)
    prog = agent_run(adapter, port, clock)
    assert prog.stop_code == "shutting_down" and len(port.called) == 1 and clock.sleeps == []


def test_closing_during_a_tool_call_lets_the_call_finish_and_starts_nothing_more():
    clock = AskFakeClock()
    state = {"closing": False}

    def call_and_close(name, arguments):
        state["closing"] = True  # the publisher starts to shut down while the call runs
        return ok_result(name)

    adapter = FakeAdapter([Turn(calls=CALL * 2), Turn(answer="never")], clock=clock)
    port = FakePort(results={FLOW: call_and_close}, clock=clock)
    prog = agent_run(adapter, port, clock, closing=lambda: state["closing"])
    assert prog.stop_code == "shutting_down"
    assert len(port.called) == 1 and adapter.calls == 1  # the call in flight finished; no second call, no turn
    steps = [s for s in prog.steps if hasattr(s, "tool")]
    assert [s.code for s in steps] == ["ok"]


def test_closing_before_the_first_turn_asks_the_model_nothing():
    clock = AskFakeClock()
    adapter = FakeAdapter([Turn(answer="never")], clock=clock)
    prog = agent_run(adapter, FakePort(), clock, closing=lambda: True)
    assert prog.stop_code == "shutting_down" and adapter.calls == 0


def test_an_exception_in_the_loop_leaves_the_partial_progress_behind():
    clock = AskFakeClock()

    def boom(messages, tools):
        raise RuntimeError("x")

    adapter = FakeAdapter([Turn(calls=CALL), boom], clock=clock)
    prog = Progress()
    lim = Limits(max_turns=8, max_tool_calls=6, model_timeout=25.0, max_answer=2000, max_result=4000)
    with pytest.raises(RuntimeError):
        asyncio.run(run_question(
            "Q?", port=FakePort(), adapter=adapter, lim=lim, clock=clock, closing=lambda: False,
            allowed={FLOW}, worst={FLOW: 40.0}, end=1000.0, prog=prog,
        ))
    assert prog.turns == 2 and prog.tool_calls == 1 and len(prog.steps) == 3  # tools, model, tool; the failed second turn has no step
