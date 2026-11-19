"""``project_trace`` and ``project_result`` on their own (spec ask, task 2.13).

Requirement 9, criteria 1 to 6. The inputs are generated tool bodies that carry
``summary``, ``content``, hidden-field text, a Bound_Value, a key and unknown members;
the output must hold none of them and must validate against ``AskTrace``. Sentinels are
generated per run and never written anywhere.
"""
from __future__ import annotations

import asyncio
import json
import secrets

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from greenscreen.publisher.ask.agent import (
    Limits,
    ModelStep,
    Progress,
    ToolsStep,
    ToolStep,
    run_question,
)
from greenscreen.publisher.ask.service import ask_openapi, project_result, project_trace
from tests.ask_support import (
    FakeAdapter,
    FakePort,
    PortStep,
    Turn,
    AskFakeClock,
    ok_result,
    no_network,  # noqa: F401  (autouse)
    tool_info,
)

_PATH, _SCHEMAS = ask_openapi(500, 2000)
_ROOT = {"$ref": "#/components/schemas/AskTrace", "components": {"schemas": _SCHEMAS}}
TRACE_VALIDATOR = Draft202012Validator(_ROOT)
AUDIT_KEYS = ("step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds")
SETTINGS = settings(
    max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)


def sentinels() -> dict[str, str]:
    """Distinct values that must never reach the projection. Generated per call."""
    return {
        name: "Z" + secrets.token_hex(8)
        for name in ("summary", "content", "hidden", "bound", "key", "unknown", "nested")
    }


def audit_entry(**extra) -> dict:
    entry = {
        "step_index": 3, "kind": "expect", "phase": "steps", "iteration": None,
        "signature": "tk5-logon", "status": "ok", "duration_seconds": 0.25,
    }
    entry.update(extra)
    return entry


def hostile_ok_body(s: dict) -> dict:
    return {
        "flow": "tk5-system-info",
        "outputs": {"RELEASE": "V2.2", "COUNT": 7},
        "audit": [audit_entry(summary=s["summary"], hidden=s["hidden"], extra={"k": s["nested"]})],
        "summary": {"text": s["summary"]},
        "content": [{"type": "text", "text": s["content"]}],
        "api_key": s["key"],
        "bound": s["bound"],
        "unknown": s["unknown"],
    }


def hostile_error_body(s: dict) -> dict:
    return {
        "error": {
            "code": "unknown_screen",
            "message": "The host showed a screen the flow does not know.",
            "step_index": 4,
            "kind": "expect",
            "expected": ["tk5-logon", "ispf-primary-menu"],
            "audit": [audit_entry(hidden=s["hidden"])],
            "summary": {"screen": s["summary"], "hidden": s["hidden"]},
            "content": s["content"],
            "password": s["bound"],
            "extra": {"deep": {"key": s["key"]}},
        },
        "summary": s["summary"],
    }


def assert_no_sentinel(value, s: dict) -> None:
    text = json.dumps(value)
    for name, sentinel in s.items():
        assert sentinel not in text, name
    assert '"summary"' not in text
    assert '"content"' not in text


def trace_of(*steps, turns=1, tool_calls=1) -> dict:
    prog = Progress(turns=turns, tool_calls=tool_calls)
    prog.steps.extend(steps)
    return project_trace(prog, 1234)


def tool_step(code="ok", body=None, *, ok=None, reason=None, arguments=None, repeats=0) -> ToolStep:
    return ToolStep(
        1, 1, "tk5-system-info", {"userid": "abc"} if arguments is None else arguments,
        code == "ok" if ok is None else ok, code, reason, body, 0.5, repeats,
    )


# --------------------------------------------------------------------------
# project_result
# --------------------------------------------------------------------------

def test_success_keeps_only_flow_outputs_and_audit():
    s = sentinels()
    result = project_result("ok", hostile_ok_body(s))
    assert set(result) == {"flow", "outputs", "audit"}
    assert result["flow"] == "tk5-system-info"
    assert result["outputs"] == {"RELEASE": "V2.2", "COUNT": 7}
    assert result["audit"] == [audit_entry()]
    assert_no_sentinel(result, s)


def test_error_keeps_the_named_members_only():
    s = sentinels()
    result = project_result("unknown_screen", hostile_error_body(s))
    assert set(result) == {"error"}
    assert set(result["error"]) == {"code", "message", "step_index", "kind", "expected", "audit"}
    assert result["error"]["expected"] == ["tk5-logon", "ispf-primary-menu"]
    assert result["error"]["audit"] == [audit_entry()]
    assert_no_sentinel(result, s)


def test_rejected_call_and_missing_body_give_none():
    assert project_result("rejected", {"flow": "x", "outputs": {}, "audit": []}) is None
    assert project_result("ok", None) is None
    assert project_result("internal_error", None) is None
    assert project_result("unknown_screen", {"error": "not an object"}) is None
    assert project_result("unknown_screen", {"nope": 1}) is None


def test_values_of_the_wrong_type_are_dropped():
    body = {
        "flow": 5,
        "outputs": {"A": "x", "B": 2, "C": 1.5, "D": True, "E": None, "F": ["x"], "G": {"y": 1}},
        "audit": [
            audit_entry(step_index="3", duration_seconds=float("nan"), status=7),
            "not an object",
            audit_entry(step_index=True),
        ],
    }
    result = project_result("ok", body)
    assert "flow" not in result
    assert result["outputs"] == {"A": "x", "B": 2}
    assert result["audit"] == []  # wrong-typed or incomplete entries are dropped whole
    error = project_result(
        "x",
        {"error": {"code": 1, "message": "m", "step_index": "1", "kind": None,
                   "expected": ["a", 2], "audit": "no"}},
    )
    assert error == {"error": {"message": "m"}}


@SETTINGS
@given(
    st.sampled_from(["ok", "unknown_screen", "input_invalid", "internal_error", "rejected"]),
    st.lists(
        st.dictionaries(
            st.text(min_size=1, max_size=8),
            st.recursive(
                st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=12)),
                lambda c: st.one_of(st.lists(c, max_size=3), st.dictionaries(st.text(max_size=4), c, max_size=3)),
                max_leaves=6,
            ),
            max_size=4,
        ),
        max_size=4,
    ),
)
def test_projection_of_generated_bodies_never_leaks_and_validates(code, noise):
    s = sentinels()
    ok = hostile_ok_body(s)
    err = hostile_error_body(s)
    # unknown members drawn by Hypothesis go into both bodies, next to the sentinels
    for extra in noise:
        for body in (ok, err["error"]):
            for key, value in extra.items():
                if key not in ("flow", "outputs", "audit", "code", "message", "step_index", "kind", "expected"):
                    body[key] = value
    body = ok if code == "ok" else err
    result = project_result(code, body)
    if code == "rejected":
        assert result is None
        return
    assert_no_sentinel(result, s)
    step = tool_step(code, body)
    trace = trace_of(step)
    TRACE_VALIDATOR.validate(trace)
    assert trace["steps"][0]["result"] == result


# --------------------------------------------------------------------------
# project_trace
# --------------------------------------------------------------------------

def test_trace_has_exactly_four_members_and_no_counts():
    trace = trace_of(
        ToolsStep(["tk5-system-info"]),
        ModelStep(1, "tool_calls", 1, 0.0123),
        tool_step("ok", hostile_ok_body(sentinels())),
        ModelStep(2, "answer", 0, 0.5),
        turns=2,
    )
    assert set(trace) == {"model_turns", "tool_calls", "elapsed_ms", "steps"}
    assert trace["model_turns"] == 2 and trace["tool_calls"] == 1 and trace["elapsed_ms"] == 1234
    assert [step["type"] for step in trace["steps"]] == ["tools", "model", "tool", "model"]
    assert trace["steps"][1] == {
        "type": "model", "turn": 1, "outcome": "tool_calls", "tool_calls": 1, "duration_ms": 12,
    }
    text = json.dumps(trace)
    for banned in ('"screens"', '"audit_steps"', '"distinct', '"n"', '"m"'):
        assert banned not in text
    TRACE_VALIDATOR.validate(trace)


def test_tool_step_members_and_order():
    step = trace_of(tool_step("ok", hostile_ok_body(sentinels()), repeats=2))["steps"][0]
    assert list(step) == [
        "type", "turn", "id", "tool", "arguments", "ok", "code", "result", "duration_ms", "repeats",
    ]
    assert step["arguments"] == {"userid": "abc"} and step["repeats"] == 2
    plain = trace_of(tool_step("ok", {"flow": "f", "outputs": {}, "audit": []}))["steps"][0]
    assert "repeats" not in plain and "reason" not in plain


def test_rejected_step_has_empty_arguments_null_result_and_a_reason():
    step = trace_of(
        tool_step("rejected", None, ok=False, reason="unknown_argument", arguments={})
    )["steps"][0]
    assert step["code"] == "rejected" and step["reason"] == "unknown_argument"
    assert step["arguments"] == {} and step["result"] is None and step["ok"] is False
    TRACE_VALIDATOR.validate(trace_of(tool_step("rejected", None, ok=False, reason="tool_limit", arguments={})))


def test_trace_with_a_stop_error_and_expected_validates():
    s = sentinels()
    trace = trace_of(tool_step("unknown_screen", hostile_error_body(s), ok=False))
    TRACE_VALIDATOR.validate(trace)
    assert trace["steps"][0]["result"]["error"]["expected"] == ["tk5-logon", "ispf-primary-menu"]
    assert_no_sentinel(trace, s)


def test_an_unknown_member_in_a_step_would_fail_the_schema():
    """Self-check of the validator: it is strict, so a passing trace means something."""
    trace = trace_of(tool_step("ok", {"flow": "f", "outputs": {}, "audit": []}))
    trace["steps"][0]["extra"] = 1
    assert not TRACE_VALIDATOR.is_valid(trace)


# --------------------------------------------------------------------------
# Requirement 9.2 and 9.3 on a result that is too large (run through the agent)
# --------------------------------------------------------------------------

def run_agent(port, adapter, *, max_result: int):
    clock = AskFakeClock()
    prog = Progress()
    lim = Limits(max_turns=8, max_tool_calls=6, model_timeout=25.0, max_answer=2000, max_result=max_result)
    asyncio.run(
        run_question(
            "q", port=port, adapter=adapter, lim=lim, clock=clock, closing=lambda: False,
            allowed=frozenset({"tk5-system-info"}), worst={"tk5-system-info": 40.0},
            end=90.0, prog=prog,
        )
    )
    return prog


def test_a_result_over_the_size_limit_is_traced_as_a_rejected_call():
    """Requirement 9.2 (``reason`` only when ``code`` is ``rejected``), 9.3 (a Rejected_Call
    carries ``arguments`` ``{}``) and 9.4 (``result`` ``null`` for a Rejected_Call); design
    "Decisions" lists a rejected ``result_too_large`` step as ``result: null``, ``arguments: {}``."""
    big = ok_result(outputs={"RELEASE": "x" * 600})
    port = FakePort([tool_info()], {"tk5-system-info": PortStep(big)})
    adapter = FakeAdapter([Turn(calls=(("tk5-system-info", '{"userid": "abc"}'),)), Turn(answer="done")])
    prog = run_agent(port, adapter, max_result=200)
    assert prog.answer == "done"
    steps = project_trace(prog, 0)["steps"]
    tool = next(step for step in steps if step["type"] == "tool")
    assert tool["code"] == "rejected"
    assert tool["reason"] == "result_too_large"
    assert tool["arguments"] == {}
    assert tool["result"] is None
    TRACE_VALIDATOR.validate(project_trace(prog, 0))


def test_reason_appears_only_on_a_rejected_step():
    big = ok_result(outputs={"RELEASE": "x" * 600})
    port = FakePort([tool_info()], {"tk5-system-info": PortStep(big)})
    adapter = FakeAdapter(
        [Turn(calls=(("tk5-system-info", '{"userid": "abc"}'), ("nope", "{}"))), Turn(answer="done")]
    )
    steps = [s for s in project_trace(run_agent(port, adapter, max_result=200), 0)["steps"] if s["type"] == "tool"]
    assert len(steps) == 2
    for step in steps:
        assert ("reason" in step) == (step["code"] == "rejected"), step["code"]
