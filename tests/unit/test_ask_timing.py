"""Timing of one Ask question (spec ask, task 2.12, Requirement 16).

``AskFakeClock`` drives the agent with scripted step durations. ``TOOL_TAIL`` is read from
``greenscreen.publisher.ask.service`` and every Tool_Worst_Case is ``GS_CALL_TIMEOUT + TOOL_TAIL``,
so a later change of the constant (task 6.6 fixes the literals) moves the table with it.
No live host, no real model, no network.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import time
from datetime import datetime, timezone

import anyio
import pytest

from greenscreen.publisher import calls
from greenscreen.publisher.app import prepare
from greenscreen.publisher.ask.agent import Limits, Progress, ToolStep, run_question
from greenscreen.publisher.ask.service import TOOL_TAIL
from greenscreen.publisher.config import StartupError
from tests.ask_support import (
    _BOUND_VARIABLE,
    ASK_ENV,
    BOUND_PASSWORD,
    FLOW,
    AskFakeClock,
    FakeAdapter,
    FakePort,
    PortStep,
    Turn,
    error_result,
    ok_result,
)
from tests.ask_support import ask_post, build_ask_app, no_network  # noqa: F401  (autouse)

CANCEL_SLOP = 0.5
OVERHEAD = 2.0
TUNNEL_LIMIT = 100.0

# (T, M, GS_CALL_TIMEOUT): the table of Requirement 16, criterion 7. C = GS_CALL_TIMEOUT + TOOL_TAIL.
ROWS = [
    pytest.param(90.0, 25.0, 30, id="defaults-T90-M25-CT30"),
    pytest.param(95.0, 25.0, 35, id="T95-M25-CT35"),
    pytest.param(90.0, 15.0, 50, id="T90-M15-CT50"),
    pytest.param(90.0, 30.0, 20, id="T90-M30-CT20"),
    pytest.param(20.0, 1.0, 1, id="T20-M1-C11"),
]


def worst(call_timeout: float) -> float:
    return call_timeout + TOOL_TAIL


def limits(model_timeout: float, **kw) -> Limits:
    base = dict(max_turns=30, max_tool_calls=20, model_timeout=model_timeout, max_answer=2000, max_result=4000)
    base.update(kw)
    return Limits(**base)


def run(adapter, port, clock, lim, *, end, worst_case, closing=lambda: False):
    prog = Progress()
    asyncio.run(
        run_question(
            "Q?", port=port, adapter=adapter, lim=lim, clock=clock, closing=closing,
            allowed={FLOW}, worst={FLOW: worst_case}, end=end, prog=prog,
        )
    )
    return prog


def tool_steps(prog):
    return [s for s in prog.steps if isinstance(s, ToolStep)]


def prepared_env(t: float, m: float, call_timeout: int) -> dict[str, str]:
    return {
        **ASK_ENV, _BOUND_VARIABLE: BOUND_PASSWORD, "GS_API_KEY": "k" * 16,
        "GS_ASK_TIMEOUT_SECONDS": str(t), "GS_ASK_MODEL_TIMEOUT_SECONDS": str(m),
        "GS_CALL_TIMEOUT": str(call_timeout),
    }


# --------------------------------------------------------------------------
# The settings of the table are eligible and C comes from TOOL_TAIL
# --------------------------------------------------------------------------

@pytest.mark.parametrize("t,m,call_timeout", ROWS)
def test_each_row_is_eligible_and_the_planned_worst_case_is_call_timeout_plus_the_tail(t, m, call_timeout):
    plan = prepare(prepared_env(t, m, call_timeout)).ask
    assert plan is not None and plan.eligible == frozenset({FLOW})
    assert plan.worst_case[FLOW] == worst(call_timeout)
    assert worst(call_timeout) + 2 * m <= t
    if t != 20.0:
        assert worst(call_timeout) + 2 * m == t  # zero slack


def test_model_timeout_of_half_the_budget_passes_config_and_leaves_no_eligible_flow():
    with pytest.raises(StartupError) as caught:
        prepare(prepared_env(90.0, 45.0, 1))
    assert "no_offerable_tools" in str(caught.value) and "call_too_long" in str(caught.value)


def test_tool_tail_is_the_worker_grace_plus_the_literal_wait_of_connector_session_abort():
    source = inspect.getsource(calls.ConnectorSession.abort)
    waits = re.findall(r"proc\.wait\(\s*(\d+(?:\.\d+)?)\s*\)", source)
    assert len(waits) == 1, source
    assert TOOL_TAIL == calls._WORKER_GRACE + float(waits[0])


# --------------------------------------------------------------------------
# No step starts that could end after the Question_Deadline
# --------------------------------------------------------------------------

@pytest.mark.parametrize("fraction", [1.0, 0.5, 0.0], ids=["max", "half", "zero"])
@pytest.mark.parametrize("t,m,call_timeout", ROWS)
def test_every_started_step_ends_by_the_deadline_and_the_question_ends_inside_the_tunnel(t, m, call_timeout, fraction):
    c = worst(call_timeout)
    clock = AskFakeClock()
    started: list[tuple[str, float]] = []

    def model_item(messages, tools):
        started.append(("model", clock.now))
        return Turn(calls=((FLOW, "{}"),), seconds=m * fraction)

    def tool_item(name, arguments):
        started.append(("tool", clock.now))
        return PortStep(ok_result(name), c * fraction)

    adapter = FakeAdapter([model_item] * 60, clock=clock)
    port = FakePort(results={FLOW: tool_item}, clock=clock)
    prog = run(adapter, port, clock, limits(m), end=t, worst_case=c)

    assert started, "nothing started"
    for kind, start in started:
        longest = m if kind == "model" else c
        assert start + longest <= t, (kind, start)
        if kind == "tool":
            assert start + c + m <= t  # the tool rule keeps one model turn for the report
    assert clock.now <= t
    assert clock.now + CANCEL_SLOP + OVERHEAD < TUNNEL_LIMIT
    # nothing was canceled: every started call came back as a finished step
    assert [s for s in tool_steps(prog) if s.code != "rejected"] == [s for s in tool_steps(prog) if s.ok]
    assert len(port.called) == sum(1 for kind, _ in started if kind == "tool")
    assert prog.stop_code in {"ask_timeout", "turn_limit", "tool_limit"}


# --------------------------------------------------------------------------
# The worst-case timeline of the demo box and its boundaries
# --------------------------------------------------------------------------

def test_demo_box_timeline_at_worst_case_durations():
    t, m, c = 90.0, 25.0, worst(30)
    assert c == 40.0
    clock = AskFakeClock()
    adapter = FakeAdapter(
        [Turn(calls=((FLOW, "{}"),), seconds=25.0), Turn(calls=((FLOW, "{}"),), seconds=25.0), Turn(answer="late")],
        clock=clock,
    )
    port = FakePort(results={FLOW: PortStep(ok_result(FLOW), 40.0)}, clock=clock)
    prog = run(adapter, port, clock, limits(m), end=t, worst_case=c)
    steps = tool_steps(prog)
    assert [(s.code, s.reason) for s in steps] == [("ok", None), ("rejected", "not_enough_time")]
    assert prog.turns == 2 and adapter.calls == 2  # the third model turn never starts
    assert prog.stop_code == "ask_timeout"
    assert clock.now == 90.0
    assert len(port.called) == 1  # exactly one tool call and two model turns fit


def test_a_tool_call_starts_at_exactly_worst_case_plus_model_timeout_and_not_a_millisecond_less():
    m, c = 25.0, 40.0
    for turn_seconds, expected in ((25.0, "ok"), (25.001, "rejected")):
        clock = AskFakeClock()
        adapter = FakeAdapter([Turn(calls=((FLOW, "{}"),), seconds=turn_seconds), Turn(answer="x")], clock=clock)
        port = FakePort(clock=clock)
        prog = run(adapter, port, clock, limits(m), end=90.0, worst_case=c)
        (step,) = tool_steps(prog)
        assert step.code == expected, turn_seconds
        if expected == "rejected":
            assert step.reason == "not_enough_time" and port.called == [] and prog.tool_calls == 1


def test_a_model_turn_starts_at_exactly_the_model_timeout_and_not_a_millisecond_less():
    m = 25.0
    adapter = FakeAdapter([Turn(answer="fits")])
    prog = run(adapter, FakePort(), AskFakeClock(now=65.0), limits(m), end=90.0, worst_case=40.0)
    assert prog.answer == "fits" and prog.stop_code is None

    adapter = FakeAdapter([Turn(answer="never")])
    prog = run(adapter, FakePort(), AskFakeClock(now=65.001), limits(m), end=90.0, worst_case=40.0)
    assert prog.stop_code == "ask_timeout" and adapter.calls == 0 and prog.turns == 0


def test_the_refused_tool_call_takes_no_time_and_the_next_model_turn_still_runs_when_it_fits():
    clock = AskFakeClock()
    adapter = FakeAdapter([Turn(calls=((FLOW, "{}"),), seconds=40.0), Turn(answer="Tool was refused.")], clock=clock)
    prog = run(adapter, FakePort(clock=clock), clock, limits(25.0), end=90.0, worst_case=40.0)
    assert prog.answer == "Tool was refused." and clock.now == 40.0


# --------------------------------------------------------------------------
# Busy repeats add their 1 second wait to what Remaining must cover
# --------------------------------------------------------------------------

def busy_port(clock, results):
    return FakePort(results={FLOW: results}, clock=clock)


def test_a_busy_repeat_starts_when_remaining_covers_wait_plus_worst_case_plus_model_timeout():
    clock = AskFakeClock()
    # model turn of 24 s: the tool starts with Remaining 66 = 1 + 40 + 25, exactly enough for one repeat
    adapter = FakeAdapter([Turn(calls=((FLOW, "{}"),), seconds=24.0), Turn(answer="ok")], clock=clock)
    port = busy_port(clock, [error_result("busy"), ok_result(FLOW)])
    prog = run(adapter, port, clock, limits(25.0), end=90.0, worst_case=40.0)
    assert clock.sleeps == [1.0] and len(port.called) == 2
    (step,) = tool_steps(prog)
    assert (step.code, step.repeats) == ("ok", 1) and prog.tool_calls == 1  # a repeat is not a new tool call
    assert prog.answer == "ok"


def test_a_busy_repeat_is_refused_a_millisecond_below_the_need_and_the_question_stops_busy():
    clock = AskFakeClock()
    adapter = FakeAdapter([Turn(calls=((FLOW, "{}"),), seconds=24.001), Turn(answer="never")], clock=clock)
    port = busy_port(clock, [error_result("busy"), ok_result(FLOW)])
    prog = run(adapter, port, clock, limits(25.0), end=90.0, worst_case=40.0)
    assert clock.sleeps == [] and len(port.called) == 1
    assert prog.stop_code == "busy" and adapter.calls == 1
    assert tool_steps(prog)[0].repeats == 0


def test_busy_three_times_over_stops_after_three_one_second_waits():
    clock = AskFakeClock()
    adapter = FakeAdapter([Turn(calls=((FLOW, "{}"),)), Turn(answer="never")], clock=clock)
    port = busy_port(clock, [error_result("busy")])
    prog = run(adapter, port, clock, limits(25.0), end=1000.0, worst_case=40.0)
    assert clock.sleeps == [1.0, 1.0, 1.0] and len(port.called) == 4
    assert prog.stop_code == "busy" and tool_steps(prog)[0].repeats == 3 and prog.tool_calls == 1


# --------------------------------------------------------------------------
# Overhead with a real clock
# --------------------------------------------------------------------------

class RealClock:
    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await anyio.sleep(seconds)


def test_a_question_of_zero_duration_steps_takes_under_a_second_on_the_real_clock():
    adapter = FakeAdapter([Turn(calls=((FLOW, '{"userid": "abc"}'),)), Turn(answer="Done.")])
    ask = build_ask_app(adapter=adapter, clock=RealClock(), utcnow=lambda: datetime.now(timezone.utc))

    async def go():
        async with ask.app.lifespan():
            began = time.monotonic()
            reply = await ask_post(ask, "Who is signed on?")
            return reply, time.monotonic() - began

    reply, seconds = asyncio.run(go())
    assert reply.status == 200, reply.raw[:300]
    assert reply.json()["answer"] == "Done."
    assert seconds < 1.0, f"overhead of a question was {seconds:.2f} s"


# --------------------------------------------------------------------------
# Task 6.6: the final numbers (T 90, M 25, TOOL_TAIL 10.0), the operator table, the startup record
# --------------------------------------------------------------------------

import logging  # noqa: E402

from greenscreen.publisher import cli  # noqa: E402
from greenscreen.publisher.ask import service  # noqa: E402

# Requirement 16, criterion 9, copied cell by cell: GS_CALL_TIMEOUT -> yes/no for
# (T 90, M 15), (T 90, M 25), (T 90, M 30), (T 95, M 15), (T 95, M 25), (T 95, M 30).
COLUMNS = [(90, 15), (90, 25), (90, 30), (95, 15), (95, 25), (95, 30)]
OPERATOR_TABLE = {
    20: "yyyyyy",
    30: "yynyyn",
    31: "ynnyyn",
    35: "ynnyyn",
    40: "ynnynn",
    50: "ynnynn",
    55: "nnnynn",
    180: "nnnnnn",
}


def _eligible(t: int, m: int, call_timeout: int) -> bool:
    try:
        plan = prepare(prepared_env(float(t), float(m), call_timeout)).ask
    except StartupError as error:
        assert "no_offerable_tools" in str(error) and "call_too_long: lower GS_CALL_TIMEOUT" in str(error)
        return False
    assert plan is not None and plan.eligible == frozenset({FLOW})
    return True


@pytest.mark.parametrize("call_timeout", sorted(OPERATOR_TABLE))
def test_every_cell_of_the_operator_table(call_timeout):
    got = "".join("y" if _eligible(t, m, call_timeout) else "n" for t, m in COLUMNS)
    assert got == OPERATOR_TABLE[call_timeout], (call_timeout, got)
    for (t, m), cell in zip(COLUMNS, OPERATOR_TABLE[call_timeout]):  # the bracketed sum agrees
        assert ((call_timeout + 10.0 + 2 * m) <= t) == (cell == "y")


@pytest.mark.parametrize("t,m,largest", [(90, 15, 50), (90, 25, 30), (90, 30, 20), (95, 15, 55), (95, 25, 35), (95, 30, 25)])
def test_the_largest_eligible_call_timeout_is_t_minus_ten_minus_two_m(t, m, largest):
    assert largest == t - 10 - 2 * m
    assert _eligible(t, m, largest)
    assert not _eligible(t, m, largest + 1)


def test_the_final_numbers_are_the_documented_literals():
    assert TOOL_TAIL == 10.0
    assert (service.CANCEL_SLOP, service.OVERHEAD, service.WORST_CASE_LIMIT) == (0.5, 2.0, 98.0)
    env = prepared_env(90.0, 25.0, 30)
    del env["GS_ASK_TIMEOUT_SECONDS"], env["GS_ASK_MODEL_TIMEOUT_SECONDS"]  # the defaults are T 90 and M 25
    plan = prepare(env).ask
    assert plan.worst_case_seconds == 92.5 and plan.largest_tool_seconds == 40.0
    assert plan.worst_case == {FLOW: 40.0}


def test_the_largest_allowed_timeout_has_a_worst_case_of_97_5():
    plan = prepare(prepared_env(95.0, 25.0, 35)).ask
    assert plan.worst_case_seconds == 97.5 and plan.largest_tool_seconds == 45.0
    assert plan.worst_case_seconds <= service.WORST_CASE_LIMIT


def test_demo_box_timeline_start_and_end_times():
    clock = AskFakeClock()
    log: list[tuple[str, float]] = []

    def model_item(messages, tools):
        log.append(("model", clock.now))
        return Turn(calls=((FLOW, "{}"),), seconds=25.0)

    def tool_item(name, arguments):
        log.append(("tool", clock.now))
        return PortStep(ok_result(name), 40.0)

    adapter = FakeAdapter([model_item] * 5, clock=clock)
    run(adapter, FakePort(results={FLOW: tool_item}, clock=clock), clock, limits(25.0), end=90.0, worst_case=40.0)
    assert log == [("model", 0.0), ("tool", 25.0), ("model", 65.0)]
    assert clock.now == 90.0


def test_the_remaining_boundaries_of_the_start_rule():
    # Tool: Remaining 65 starts, 64.999 does not. Model turn: 25 starts, 24.999 does not.
    for now, expected in ((25.0, "ok"), (25.001, "rejected")):
        clock = AskFakeClock(now=now)
        adapter = FakeAdapter([Turn(calls=((FLOW, "{}"),)), Turn(answer="x")], clock=clock)
        prog = run(adapter, FakePort(clock=clock), clock, limits(25.0), end=90.0, worst_case=40.0)
        assert tool_steps(prog)[0].code == expected, now
    for now, started in ((65.0, True), (65.001, False)):
        adapter = FakeAdapter([Turn(answer="x")])
        prog = run(adapter, FakePort(), AskFakeClock(now=now), limits(25.0), end=90.0, worst_case=40.0)
        assert (adapter.calls == 1) is started, now


# --- the startup record and the refusal -------------------------------------------------

_STANDARD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime", "taskName"}


def _worst_case_records(caplog):
    return [r for r in caplog.records if r.name == "greenscreen.publisher" and r.getMessage() == "ask worst case"]


def _report(caplog, env):
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="greenscreen.publisher"):
        cli._report_startup(prepare(env))
    return _worst_case_records(caplog)


def test_the_startup_record_has_fixed_text_and_exactly_two_numeric_fields(caplog):
    env = prepared_env(90.0, 25.0, 30)
    (record,) = _report(caplog, env)
    assert record.levelno == logging.INFO and record.msg == "ask worst case" and not record.args
    assert {k: v for k, v in record.__dict__.items() if k not in _STANDARD} == {
        "worst_case_seconds": 92.5, "largest_tool_seconds": 40.0,
    }
    assert all(type(v) is float for k, v in record.__dict__.items() if k not in _STANDARD)


def test_the_startup_record_at_t_95_and_no_record_when_ask_is_off(caplog):
    (record,) = _report(caplog, prepared_env(95.0, 25.0, 35))
    assert (record.worst_case_seconds, record.largest_tool_seconds) == (97.5, 45.0)
    off = {**prepared_env(90.0, 25.0, 30), "GS_ENABLE_ASK": "false"}
    assert _report(caplog, off) == []


REFUSAL = "GS_ASK_TIMEOUT_SECONDS: worst_case_too_long (lower GS_ASK_TIMEOUT_SECONDS)"


@pytest.mark.parametrize("constant,value", [("OVERHEAD", 2.6), ("CANCEL_SLOP", 1.1), ("WORST_CASE_LIMIT", 97.4)])
def test_worst_case_too_long_fires_when_a_constant_is_patched(monkeypatch, constant, value):
    env = prepared_env(95.0, 25.0, 35)  # 97.5 today, below 98.0
    prepare(env)
    monkeypatch.setattr(service, constant, value)
    with pytest.raises(StartupError) as caught:
        prepare(env)
    assert str(caught.value) == REFUSAL


def test_worst_case_too_long_at_exactly_the_limit_does_not_fire(monkeypatch):
    monkeypatch.setattr(service, "OVERHEAD", 2.5)  # 95 + 0.5 + 2.5 = 98.0, not greater
    assert prepare(prepared_env(95.0, 25.0, 35)).ask.worst_case_seconds == 98.0


def test_tool_tail_parts_match_the_source_of_abort_and_the_worker_grace():
    source = inspect.getsource(calls.ConnectorSession.abort)
    assert "proc.wait(5)" in source
    assert service.ABORT_WAIT + service.WORKER_GRACE == TOOL_TAIL == calls._WORKER_GRACE + 5.0
