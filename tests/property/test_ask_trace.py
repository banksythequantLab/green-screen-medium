# Feature: ask, Property 3: The trace is the allow-list projection and nothing else
"""Property 3 of the ask spec (task 2.16).

**Validates: Requirements 9.1, 9.2, 9.3, 9.4, 9.5, 9.6**

Tool results are generated from a recursive strategy: success and error shapes, extra
members, ``summary``, ``content``, hidden-field text, wrong types, long strings and many
audit entries. Each example is driven through ``run_question`` and ``project_trace`` and
through ``POST /ask`` (the in-process tool port replaced by a ``FakePort``).

Oracle: ``AskTrace`` from the served ``/openapi.json`` (Draft 2020-12), equality of every
``tool`` step ``result`` with a test-side projection written separately from the
production one, and ``find_leaks`` over the response body.

``expected`` is a list of strings in the Ask schemas (Requirement 9.4); that is what is
tested here, not the older ``ErrorBody`` schema.

Keys and Bound_Values are generated at run time and never written anywhere. A Bound_Value,
the API key and the hidden text only ever sit in slots that the projection must drop.
"""
from __future__ import annotations

import asyncio
import copy
import json
import math
import secrets
from functools import lru_cache
from typing import Any

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

import pytest

from greenscreen.publisher.ask import service as ask_service
from greenscreen.publisher.ask.agent import Limits, Progress, ToolResult, run_question
from greenscreen.publisher.ask.service import project_trace
from greenscreen.publisher.calls import ERROR_CODES
from tests.ask_support import (
    BOUND_PASSWORD,
    FLOW,
    AskFakeClock,
    FakeAdapter,
    FakePort,
    Turn,
    ask_post,
    build_ask_app,
    no_network,  # noqa: F401  (autouse)
    tool_info,
)
from tests.console_support import call_scope
from tests.property._publisher_strategies import find_leaks, probes

MAX_RESULT = 1500
ENV = {"GS_ASK_MAX_RESULT_CHARS": str(MAX_RESULT)}
QUESTION = "What system is this, and which release?"
USERID = '{"userid": "abc"}'

# --------------------------------------------------------------------------
# Sentinels: one set per process, never written anywhere
# --------------------------------------------------------------------------

SENTINELS = {
    "@@HIDDEN@@": "ZH" + secrets.token_hex(8),
    "@@SUMMARY@@": "ZS" + secrets.token_hex(8),
    "@@CONTENT@@": "ZC" + secrets.token_hex(8),
    "@@EXTRA@@": "ZE" + secrets.token_hex(8),
}
KEY_TOKEN = "@@KEY@@"
BOUND_TOKEN = "@@BOUND@@"
PLACEHOLDERS = (*SENTINELS, KEY_TOKEN, BOUND_TOKEN)


def substitute(value: Any, replacements: dict[str, str]) -> Any:
    """Replace every string that is exactly a placeholder, at any depth."""
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [substitute(v, replacements) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, replacements) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------

_BAD_WORDS = ("summary", "content")
SAFE = st.text("abcdefghijklmnopqrstuvwxyz ", max_size=30).filter(
    lambda t: not any(w in t for w in _BAD_WORDS)
)
LONG = st.integers(200, 900).map(lambda n: "lg" * (n // 2))
TEXT = st.one_of(SAFE, SAFE, LONG)
PLACE = st.sampled_from(PLACEHOLDERS)
# Dropped keys can never collide with a kept name.
EXTRA_KEY = SAFE.map(lambda t: "x_" + t)

JUNK = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(),
        SAFE,
        PLACE,
    ),
    lambda c: st.one_of(st.lists(c, max_size=3), st.dictionaries(SAFE, c, max_size=3)),
    max_leaves=8,
)


def _is_int(v: Any) -> bool:
    return type(v) is int


def _is_number(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


def wrong(*accepted: Any) -> st.SearchStrategy[Any]:
    """Junk that is not accepted by any of the predicates."""
    return JUNK.filter(lambda v: not any(p(v) for p in accepted))


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


def _is_none(v: Any) -> bool:
    return v is None


AUDIT_KEYS = ("step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds")
AUDIT_SLOTS = {
    "step_index": (st.integers(0, 99), wrong(_is_int)),
    "kind": (SAFE, wrong(_is_str)),
    "phase": (SAFE, wrong(_is_str)),
    "iteration": (st.one_of(st.none(), st.integers(0, 9)), wrong(_is_int, _is_none)),
    "signature": (st.one_of(st.none(), SAFE), wrong(_is_str, _is_none)),
    "status": (SAFE, wrong(_is_str)),
    "duration_seconds": (
        st.one_of(st.integers(0, 600), st.floats(0, 600, allow_nan=False)),
        st.one_of(st.sampled_from([math.nan, math.inf, -math.inf]), wrong(_is_number)),
    ),
}


def _slot(name: str) -> st.SearchStrategy[Any]:
    good, bad = AUDIT_SLOTS[name]
    return st.one_of(good, good, bad)


AUDIT_ENTRY = st.builds(
    lambda base, drop, extra: {
        **{k: v for k, v in base.items() if k not in drop},
        **extra,
    },
    st.fixed_dictionaries({k: _slot(k) for k in AUDIT_KEYS}),
    st.sets(st.sampled_from(AUDIT_KEYS), max_size=3),
    st.dictionaries(EXTRA_KEY, JUNK, max_size=2),
)
AUDIT = st.lists(st.one_of(AUDIT_ENTRY, AUDIT_ENTRY, AUDIT_ENTRY, JUNK), max_size=25)

OUTPUT_VALUE = st.one_of(TEXT, st.integers(-10**6, 10**6), wrong(_is_str, _is_int))
OUTPUTS = st.dictionaries(SAFE.filter(bool), OUTPUT_VALUE, max_size=6)

# Members that carry hostile text and must never be kept.
HOSTILE_EXTRAS = st.fixed_dictionaries(
    {},
    optional={
        "summary": st.one_of(PLACE, JUNK),
        "content": st.one_of(
            st.just([{"type": "text", "text": "@@CONTENT@@"}]), PLACE, JUNK
        ),
        "api_key": st.just(KEY_TOKEN),
        "password": st.just(BOUND_TOKEN),
        "screen": st.just({"hidden": "@@HIDDEN@@"}),
    },
)
EXTRAS = st.builds(
    lambda a, b: {**a, **b}, HOSTILE_EXTRAS, st.dictionaries(EXTRA_KEY, JUNK, max_size=3)
)

SUCCESS_BODY = st.builds(
    lambda core, extras: {**core, **extras},
    st.fixed_dictionaries(
        {},
        optional={
            "flow": st.one_of(SAFE, SAFE, wrong(_is_str)),
            "outputs": st.one_of(OUTPUTS, OUTPUTS, wrong(lambda v: isinstance(v, dict))),
            "audit": st.one_of(AUDIT, AUDIT, wrong(lambda v: isinstance(v, list))),
        },
    ),
    EXTRAS,
)

ERROR_CORE = st.builds(
    lambda core, extras: {**core, **extras},
    st.fixed_dictionaries(
        {},
        optional={
            "code": st.one_of(SAFE, wrong(_is_str)),
            "message": st.one_of(SAFE, wrong(_is_str)),
            "kind": st.one_of(SAFE, wrong(_is_str)),
            "step_index": st.one_of(st.integers(0, 99), wrong(_is_int)),
            "expected": st.one_of(
                st.lists(SAFE, max_size=6),
                st.lists(st.one_of(SAFE, wrong(_is_str)), min_size=1, max_size=4),
                wrong(lambda v: isinstance(v, list)),
            ),
            "audit": st.one_of(AUDIT, wrong(lambda v: isinstance(v, list))),
        },
    ),
    EXTRAS,
)
ERROR_BODY = st.builds(
    lambda error, extras: {"error": error, **extras},
    st.one_of(ERROR_CORE, ERROR_CORE, wrong(lambda v: isinstance(v, dict))),
    EXTRAS,
)

CODES = ["ok"] + sorted(ERROR_CODES - {"busy", "shutting_down"})
TOOL_RESULT = st.tuples(
    st.sampled_from(CODES),
    st.one_of(SUCCESS_BODY, ERROR_BODY, ERROR_BODY, st.none()),
)

# A scenario: results for the calls that reach the port, plus how many bad calls and
# where the turn is split. At most four good and two bad calls (the limit is six).
SCENARIO = st.tuples(
    st.lists(TOOL_RESULT, min_size=1, max_size=4),
    st.lists(st.sampled_from(["unknown_tool", "unknown_argument"]), max_size=2),
    st.randoms(use_true_random=False),
    st.integers(0, 6),
)


# --------------------------------------------------------------------------
# The test-side projection (written separately from ``project_result``)
# --------------------------------------------------------------------------

def _audit_oracle(items: Any) -> list[dict]:
    rules = {
        "step_index": lambda v: type(v) is int,
        "kind": lambda v: type(v) is str,
        "phase": lambda v: type(v) is str,
        "iteration": lambda v: v is None or type(v) is int,
        "signature": lambda v: v is None or type(v) is str,
        "status": lambda v: type(v) is str,
        "duration_seconds": lambda v: type(v) in (int, float)
        and not (type(v) is float and (math.isnan(v) or math.isinf(v))),
    }
    kept = []
    for item in items:
        if type(item) is not dict:
            continue
        if all(k in item and rules[k](item[k]) for k in AUDIT_KEYS):
            kept.append({k: item[k] for k in AUDIT_KEYS})
    return kept


def oracle(code: str, body: Any) -> dict | None:
    if code == "rejected" or type(body) is not dict:
        return None
    if code == "ok":
        result: dict = {}
        if type(body.get("flow")) is str:
            result["flow"] = body["flow"]
        if type(body.get("outputs")) is dict:
            result["outputs"] = {
                k: v for k, v in body["outputs"].items() if type(v) in (str, int)
            }
        if type(body.get("audit")) is list:
            result["audit"] = _audit_oracle(body["audit"])
        return result
    error = body.get("error")
    if type(error) is not dict:
        return None
    kept: dict = {}
    for name in ("code", "message", "kind"):
        if type(error.get(name)) is str:
            kept[name] = error[name]
    if type(error.get("step_index")) is int:
        kept["step_index"] = error["step_index"]
    expected = error.get("expected")
    if type(expected) is list and all(type(e) is str for e in expected):
        kept["expected"] = list(expected)
    if type(error.get("audit")) is list:
        kept["audit"] = _audit_oracle(error["audit"])
    return {"error": kept}


# --------------------------------------------------------------------------
# Drivers and checks
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def trace_validator() -> Draft202012Validator:
    """``AskTrace`` taken from the document the app serves at ``/openapi.json``."""
    app = build_ask_app(ENV)
    status, _, raw = asyncio.run(
        call_scope(app.app.asgi, "GET", "/openapi.json", {"X-API-Key": app.api_key})
    )
    assert status == 200
    doc = json.loads(raw)
    assert "AskTrace" in doc["components"]["schemas"]
    return Draft202012Validator(
        {"$ref": "#/components/schemas/AskTrace", "components": doc["components"]}
    )


def recording_port(results: list[ToolResult]) -> tuple[FakePort, list[ToolResult]]:
    returned: list[ToolResult] = []
    queue = iter(copy.deepcopy(results))

    def next_result(name: str, arguments: dict) -> ToolResult:
        item = next(queue)
        returned.append(item)
        return item

    return FakePort([tool_info()], {FLOW: next_result}), returned


def script_for(good: list[ToolResult], bad: list[str], rnd: Any, split: int) -> list[Turn]:
    calls: list[tuple[str, str]] = [(FLOW, USERID)] * len(good)
    for kind in bad:
        calls.append(("nope", "{}") if kind == "unknown_tool" else (FLOW, '{"nope": 1}'))
    rnd.shuffle(calls)
    cut = min(split, len(calls))
    turns = [Turn(calls=tuple(part)) for part in (calls[:cut], calls[cut:]) if part]
    return turns + [Turn(answer="done")]


def keys_of(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys_of(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys_of(item)


def check_text_clean(value: Any, text: str, leak_values: list[Any]) -> None:
    for token, sentinel in SENTINELS.items():
        assert sentinel not in text, token
    assert find_leaks(text, leak_values) == []
    assert not {"summary", "content"} & set(keys_of(value))


def check_trace(trace: dict, returned: list[ToolResult]) -> None:
    trace_validator().validate(trace)
    used = 0
    tool_steps = [s for s in trace["steps"] if s["type"] == "tool"]
    assert [s["id"] for s in tool_steps] == list(range(1, len(tool_steps) + 1))
    assert trace["tool_calls"] == len(tool_steps)
    for step in tool_steps:
        if step["code"] == "rejected":
            assert step["result"] is None and step["arguments"] == {}
            assert step["ok"] is False and "reason" in step
            if step["reason"] != "result_too_large":
                continue  # this call never reached the port
        else:
            assert "reason" not in step
        got = returned[used]
        used += 1
        if step["code"] != "rejected":
            assert step["code"] == got.code
            assert step["result"] == oracle(got.code, got.body)
    assert used == len(returned)


# --------------------------------------------------------------------------
# Property 3
# --------------------------------------------------------------------------

@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.function_scoped_fixture,
    ],
)
@given(SCENARIO, probes("str"))
def test_the_trace_is_the_allow_list_projection_and_nothing_else(scenario, secret_probe):
    raw_results, bad, rnd, split = scenario
    # Visible text must be disjoint from the values that may not leak.
    fixed_values = [BOUND_PASSWORD, secret_probe]
    assume(not find_leaks(json.dumps(raw_results), fixed_values))

    script = script_for(raw_results, bad, rnd, split)
    app = build_ask_app(ENV, adapter=FakeAdapter(script))
    replacements = {**SENTINELS, KEY_TOKEN: app.api_key, BOUND_TOKEN: BOUND_PASSWORD}
    results = [ToolResult(code, substitute(body, replacements)) for code, body in raw_results]
    leak_values = [*fixed_values, app.api_key]

    # 1. project_trace over a direct run of the agent.
    port, returned = recording_port(results)
    prog = Progress()
    lim = Limits(
        max_turns=8, max_tool_calls=6, model_timeout=20.0, max_answer=2000, max_result=MAX_RESULT
    )
    direct_adapter = FakeAdapter(script)
    asyncio.run(
        run_question(
            QUESTION, port=port, adapter=direct_adapter, lim=lim, clock=AskFakeClock(),
            closing=lambda: False, allowed=frozenset({FLOW}), worst={FLOW: 50.0},
            end=95.0, prog=prog,
        )
    )
    assert prog.answer == "done" and prog.stop_code is None
    trace = project_trace(prog, 0)
    check_trace(trace, returned)
    check_text_clean(trace, json.dumps(trace), leak_values)

    # 2. The route, with the in-process tool port replaced by a FakePort.
    route_port, route_returned = recording_port(results)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ask_service, "McpToolPort", lambda client: route_port)
        reply = asyncio.run(ask_post(app, QUESTION))
    assert reply.status == 200, reply.raw[:300]
    body = reply.json()
    assert body["answer"] == "done"
    check_trace(body["trace"], route_returned)
    check_text_clean(body, reply.raw.decode("utf-8"), leak_values)
    assert body["trace"]["steps"] == trace["steps"]
