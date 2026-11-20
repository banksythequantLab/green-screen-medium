"""Timing, Ask eligibility and Ask result sizing of the Command_Flows (more-flows, task 9.2).

Timing is read from the bundled Flow files and the real registry. Eligibility goes through the
real ``prepare`` and ``plan_ask`` (``greenscreen/publisher/ask/service.py`` is not changed).
Sizing runs each Flow on the real captures, counts the characters the model would see
(``facing`` serialised as ``run_question`` does), and computes the worst case from the caps.
A result over the limit is checked through ``run_question`` with a scripted port. No live host,
no real model, no network. The password value is generated at run time.
"""
from __future__ import annotations

import asyncio
import json
import secrets

import pytest

pytest.importorskip("fastapi")

from greenscreen.flow.bundled import load_bundled_flows  # noqa: E402
from greenscreen.flow.runner import run_flow  # noqa: E402
from greenscreen.publisher.app import prepare  # noqa: E402
from greenscreen.publisher.ask.agent import (  # noqa: E402
    Limits,
    Progress,
    ToolResult,
    ToolStep,
    facing,
    run_question,
)
from greenscreen.publisher.ask.codes import REJECT_REASONS  # noqa: E402
from greenscreen.publisher.ask.service import TOOL_TAIL  # noqa: E402
from greenscreen.publisher.config import StartupError  # noqa: E402
from greenscreen.publisher.registry import build_registry, load_flows  # noqa: E402
from tests.ask_support import (  # noqa: E402
    AskFakeClock,
    FakeAdapter,
    FakePort,
    Turn,
    ok_result,
    tool_info,
)
from tests.ask_support import no_network  # noqa: E402,F401  (autouse)
from tests.command_flow_support import INPUTS, POLL, command_session  # noqa: E402
from tests.flow_support import FakeClock  # noqa: E402

FIVE = (
    "tk5-time", "tk5-list-datasets", "tk5-dataset-info", "tk5-library-members", "tk5-job-status",
)
SIX = FIVE + ("tk5-system-info",)
MEMBER_PAGES = ["tso-listds-members"] + [f"tso-listds-members-page{i}" for i in range(2, 8)]
DSN = "SYS2.JCLLIB"
LIMIT = 4000

# Requirement 4.6 and design section 8 (LF counted as the two characters of its JSON escape).
MEASURED = {
    "tk5-time": 123, "tk5-list-datasets": 171, "tk5-dataset-info": 105,
    "tk5-library-members": 1354, "tk5-job-status": 77,
}
WORST = {
    "tk5-time": 287, "tk5-list-datasets": 2812, "tk5-dataset-info": 1680,
    "tk5-library-members": 2079, "tk5-job-status": 3285,
}

FLOWS = load_bundled_flows()


def _bind(name: str) -> str:
    return "GS_BIND_" + name.upper().replace("-", "_") + "__PASSWORD"


def _env(bound: tuple[str, ...] = SIX, publish: tuple[str, ...] = SIX, **extra: str) -> dict[str, str]:
    value = secrets.token_hex(4)
    env = {
        "GS_S3270_BINARY": "s3270",
        "GS_HOST": "host.invalid",
        "GS_API_KEY": secrets.token_hex(12),
        "GS_PUBLISH_FLOWS": ",".join(publish),
        "GS_ENABLE_ASK": "true",
        "GS_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "GS_LLM_MODEL": "fake-model",
        "GS_CALL_TIMEOUT": "30",
        "GS_ASK_TIMEOUT_SECONDS": "90",
        "GS_ASK_MODEL_TIMEOUT_SECONDS": "25",
    }
    env.update({_bind(n): value for n in bound})
    env.update(extra)
    return env


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", FIVE)
def test_run_plus_finally_plus_four_fits_thirty_and_step_fits_run(name):
    t = FLOWS[name].timeouts
    assert t.run + t.finally_ + 4.0 <= 30.0
    assert t.step <= t.run


@pytest.mark.parametrize("name", FIVE)
def test_registry_deadline_is_thirty_at_call_timeout_thirty(name):
    registry = build_registry(load_flows(None), prepare(_env()).bound, 30.0)
    assert registry[name].deadline == 30.0
    assert prepare(_env()).registry[name].deadline == 30.0


# --------------------------------------------------------------------------
# Ask eligibility
# --------------------------------------------------------------------------

def test_plan_ask_offers_all_five_and_system_info_with_the_documented_numbers():
    prepared = prepare(_env())
    plan = prepared.ask
    assert plan is not None and plan.eligible == frozenset(SIX)
    for name in SIX:
        assert prepared.registry[name].deadline + TOOL_TAIL + 2 * 25 == 90.0
        assert plan.worst_case[name] == 40.0
    assert plan.worst_case_seconds == 92.5
    assert plan.largest_tool_seconds == 40.0


@pytest.mark.parametrize("name", FIVE)
def test_a_flow_with_an_unbound_password_is_not_offered(name):
    env = _env(bound=("tk5-system-info",), publish=("tk5-system-info", name))
    assert prepare(env).ask.eligible == frozenset({"tk5-system-info"})
    with pytest.raises(StartupError) as info:
        prepare({**env, "GS_ASK_FLOWS": name})
    assert str(info.value) == f"GS_ASK_FLOWS: has_secret_input ({name})"


@pytest.mark.parametrize("name", FIVE)
def test_ask_flows_accepts_each_of_the_five_names(name):
    plan = prepare(_env(GS_ASK_FLOWS=name)).ask
    assert plan.eligible == frozenset({name})
    assert plan.worst_case == {name: 40.0}
    assert plan.worst_case_seconds == 92.5 and plan.largest_tool_seconds == 40.0


# --------------------------------------------------------------------------
# Ask sizing
# --------------------------------------------------------------------------

def _rows_outputs():
    return [(n, o) for n, f in FLOWS.items() for o in f.outputs if o.max_rows is not None]


def test_there_is_a_rows_output_in_each_command_flow():
    assert {n for n, _ in _rows_outputs()} >= set(FIVE)


@pytest.mark.parametrize("name,out", _rows_outputs(), ids=lambda v: v if isinstance(v, str) else v.name)
def test_rows_output_formula_stays_under_the_limit(name, out):
    assert out.max_rows * (out.length + 2) + 200 <= LIMIT


def _model_text(name: str, outputs: dict) -> str:
    res = ToolResult("ok", {"flow": name, "outputs": outputs})
    return json.dumps(facing(res), separators=(",", ":"))


def _worst_outputs(name: str) -> dict:
    outputs: dict = {}
    for o in FLOWS[name].outputs:
        if o.equals is not None:
            outputs[o.name] = 1
        elif o.max_rows is not None:
            outputs[o.name] = "\n".join(["a" * o.length] * o.max_rows)
        else:
            outputs[o.name] = "a" * o.length
    return outputs


@pytest.mark.parametrize("name", FIVE)
def test_worst_case_from_the_caps_is_under_the_limit(name):
    size = len(_model_text(name, _worst_outputs(name)))
    assert size == WORST[name]
    assert size < LIMIT
    assert max(WORST.values()) == WORST["tk5-job-status"] == 3285


def _screens(name: str) -> list[str]:
    return {
        "tk5-time": ["tso-time-output"],
        "tk5-list-datasets": ["tso-listcat-output"],
        "tk5-dataset-info": ["tso-listds-output"],
        "tk5-library-members": MEMBER_PAGES,
        "tk5-job-status": ["tso-status-output"],
    }[name]


@pytest.mark.parametrize("name", FIVE)
def test_measured_size_on_the_real_captures_is_under_the_limit(name):
    inputs = {**INPUTS, "dsname": DSN} if name in ("tk5-dataset-info", "tk5-library-members") else INPUTS
    result = run_flow(FLOWS[name], command_session(_screens(name)), inputs, clock=FakeClock(), poll_interval=POLL)
    size = len(_model_text(name, dict(result.outputs)))
    assert size == MEASURED[name]
    assert size < LIMIT


# --------------------------------------------------------------------------
# A result over the limit is a Rejected_Call and nothing else happens
# --------------------------------------------------------------------------

def _over(char: str):
    """Flows whose Rows_Output, full of ``char``, serialises to more than the limit."""
    names = []
    for name in FIVE:
        outputs = _worst_outputs(name)
        for o in FLOWS[name].outputs:
            if o.max_rows is not None:
                outputs[o.name] = "\n".join([char * o.length] * o.max_rows)
        if len(_model_text(name, outputs)) > LIMIT:
            names.append(name)
    return names


QUOTED = [(n, c) for c in ('"', "\\") for n in _over(c)]


def test_quotes_and_backslashes_exceed_the_limit_for_the_largest_flow():
    assert ("tk5-job-status", '"') in QUOTED and ("tk5-job-status", "\\") in QUOTED


@pytest.mark.parametrize("name,char", QUOTED)
def test_a_result_full_of_escapes_is_result_too_large_with_no_other_effect(name, char):
    outputs = _worst_outputs(name)
    for o in FLOWS[name].outputs:
        if o.max_rows is not None:
            outputs[o.name] = "\n".join([char * o.length] * o.max_rows)
    port = FakePort(tools=[tool_info(name, properties={})], results={name: ok_result(name, outputs)})
    adapter = FakeAdapter([Turn(calls=((name, "{}"),)), Turn(answer="done")])
    prog = Progress()
    lim = Limits(max_turns=8, max_tool_calls=6, model_timeout=25.0, max_answer=2000, max_result=LIMIT)
    asyncio.run(run_question(
        "Q?", port=port, adapter=adapter, lim=lim, clock=AskFakeClock(), closing=lambda: False,
        allowed={name}, worst={name: 40.0}, end=1000.0, prog=prog,
    ))
    rejected = json.dumps(
        {"error": {"code": "rejected", "message": REJECT_REASONS["result_too_large"]}},
        separators=(",", ":"),
    )
    sent = json.loads(adapter.received[1])["messages"]
    assert [m["content"] for m in sent if m["role"] == "tool"] == [rejected]
    (step,) = [s for s in prog.steps if isinstance(s, ToolStep)]
    assert (step.code, step.reason, step.body, step.arguments) == (
        "rejected", "result_too_large", None, {},
    )
    assert port.called == [(name, {})]
    assert (prog.stop_code, prog.answer, prog.tool_calls, prog.turns) == (None, "done", 1, 2)
