"""Parity between the server's trace projection and what the page shows (spec ask, task 4.3).

`project_result` (Python) and `RESULT_SPECS` (JavaScript) are two copies of one allow-list.
These tests keep them equal, keep `summariseRun` equal to a Python reference, and keep the
page from growing a second projection.
"""
from __future__ import annotations

import json
import re
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.publisher.ask.codes import REFUSAL_SENTENCE
from greenscreen.publisher.ask.service import project_result
from tests.console_node_ask import needs_node, run_ask_calls, snippets_source, summarise_run
from tests.console_support import ASSET_DIR

# --- generators ---------------------------------------------------------------------

_TEXT = st.text(max_size=40)
_SHORT = st.text(max_size=20)
_JSONISH = st.recursive(
    st.none() | st.booleans() | st.integers(-1000, 1000) | _SHORT,
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(_SHORT, inner, max_size=3),
    max_leaves=6,
)
_NUMBER = st.integers(-(2**31), 2**31) | st.floats(allow_nan=False, allow_infinity=False, width=32)
_AUDIT_OK = st.fixed_dictionaries(
    {
        "step_index": st.integers(0, 500),
        "kind": _SHORT,
        "phase": _SHORT,
        "iteration": st.none() | st.integers(0, 50),
        "signature": st.none() | _SHORT,
        "status": st.sampled_from(["ok", "skipped", "failed", "retried"]),
        "duration_seconds": st.floats(0, 600, allow_nan=False, width=32),
    }
)
# An audit entry with an extra member, a missing member or a wrong-typed one: the server
# projection drops the extra member or the whole entry; the page must show what is left.
_AUDIT_ANY = (
    _AUDIT_OK
    | st.builds(lambda e, extra: {**e, "content": extra, "summary": extra}, _AUDIT_OK, _JSONISH)
    | st.builds(lambda e, k: {m: v for m, v in e.items() if m != k}, _AUDIT_OK, st.sampled_from(["kind", "status"]))
    | st.builds(lambda e, v: {**e, "step_index": v}, _AUDIT_OK, st.sampled_from(["1", None, True, 1.5]))
    | _JSONISH
)
_AUDITS = st.lists(_AUDIT_ANY, max_size=6)
_OUTPUTS = st.dictionaries(_SHORT, st.one_of(_SHORT, st.integers(-1000, 1000), st.booleans(), st.none(), st.lists(_SHORT, max_size=2)), max_size=4)
_SUCCESS = st.builds(
    lambda flow, outputs, audit, extra: {
        "flow": flow, "outputs": outputs, "audit": audit, "summary": extra, "content": [{"text": extra}], "zz": extra,
    },
    _SHORT, _OUTPUTS, _AUDITS, _JSONISH,
)
_ERROR = st.builds(
    lambda code, message, step, kind, expected, audit, extra: {
        "error": {
            "code": code, "message": message, "step_index": step, "kind": kind,
            "expected": expected, "audit": audit, "hidden": extra,
        },
        "summary": extra,
    },
    st.sampled_from(["unknown_screen", "timeout", "internal_error", "busy"]),
    st.text(max_size=300),
    st.integers(0, 99),
    _SHORT,
    st.lists(_SHORT, max_size=4),
    _AUDITS,
    _JSONISH,
)
_CASES = st.lists(
    st.one_of(st.tuples(st.just("ok"), _SUCCESS), st.tuples(st.just("error"), _ERROR)),
    min_size=1,
    max_size=10,
)


def _jsonrpc_text(shown: str) -> dict:
    """The JSON the page shows: the text before the 'Left out' line."""
    return json.loads(shown.split("\n\nLeft out by this page:")[0])


@needs_node
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(cases=_CASES)
def test_page_shows_exactly_the_server_projection(cases):
    # Feature: ask, parity of project_result and RESULT_SPECS.
    steps = []
    for index, (code, body) in enumerate(cases, start=1):
        steps.append(
            {
                "type": "tool", "turn": 1, "id": index, "tool": "tk5-system-info",
                "arguments": {}, "ok": code == "ok", "code": code if code == "ok" else body["error"]["code"],
                "result": project_result(code if code == "ok" else body["error"]["code"], body),
            }
        )
    calls = []
    for step in steps:
        calls.append({"fn": "askStepToEntries", "args": [step]})
    entries = run_ask_calls(calls)
    shown_calls = []
    for entry in entries:
        assert "threw" not in entry and entry["value"] is not None
        shown_calls.append({"fn": "formatTranscriptEntry", "args": [entry["value"]["received"]]})
    shown = run_ask_calls(shown_calls)
    for step, out in zip(steps, shown):
        assert "threw" not in out
        value = out["value"]
        assert value["omitted"] == []
        assert "Left out by this page" not in value["text"]
        expected = {
            "jsonrpc": "2.0",
            "id": step["id"],
            "result": {"isError": step["ok"] is not True, "structuredContent": step["result"]},
        }
        assert _jsonrpc_text(value["text"]) == expected


@needs_node
@settings(max_examples=100, deadline=None)
@given(batches=st.lists(st.lists(_AUDIT_ANY, max_size=8), min_size=1, max_size=10))
def test_node_summarise_run_equals_python_reference(batches):
    # Feature: ask, parity of summariseRun and the Python reference.
    started = time.perf_counter()
    results = run_ask_calls([{"fn": "summariseRun", "args": [audit]} for audit in batches])
    for audit, result in zip(batches, results):
        assert result == {"value": summarise_run(audit)}
    assert time.perf_counter() - started < 30


@needs_node
def test_summarise_run_junk_input():
    results = run_ask_calls(
        [{"fn": "summariseRun", "args": [junk]} for junk in (None, 5, "x", {}, [None, 3, "a", {"status": "skipped"}])]
    )
    assert [r["value"] for r in results] == [{"steps": 0, "screens": 0}] * 4 + [{"steps": 0, "screens": 0}]


def test_refusal_sentence_matches_snippets_constant():
    match = re.search(r'export const ASK_REFUSAL = "([^"]*)";', snippets_source())
    assert match is not None
    assert match.group(1) == REFUSAL_SENTENCE


# --- static: no second projection ---------------------------------------------------

_ASK_FUNCTIONS = (
    "buildAskBody", "askExamples", "askStepToEntries", "askChain", "askRunLine", "askAnswerNotice",
)


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    brace = source.index("{", source.index(")", start))
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unbalanced braces in {name}")


def test_snippets_has_one_projection_and_the_ask_functions_define_none():
    source = snippets_source()
    assert len(re.findall(r"\bconst RESULT_SPECS\b", source)) == 1
    assert len(re.findall(r"\bfunction formatTranscriptEntry\b", source)) == 1
    assert len(re.findall(r"\bfunction project\w*\(", source)) == 2  # project, projectMessage (pre-existing)
    for name in _ASK_FUNCTIONS:
        body = _function_body(source, name)
        # no allow-list copy: no spec object of member names, no per-member picking of result fields
        assert "_SPEC" not in body and "SPECS" not in body, name
        assert not re.search(r"\bfunction\s+\w*(project|allow)\w*", body, re.I), name
        for member in ("structuredContent", "outputs", "step_index", "duration_seconds", "expected"):
            assert member not in body or name == "askStepToEntries" and member == "structuredContent", (name, member)


def test_console_js_reuses_the_one_projection():
    text = (ASSET_DIR / "console.js").read_text(encoding="utf-8")
    assert not re.search(r"function\s+\w*(project|allowList)\w*\s*\(", text, re.I)
    assert not re.search(r"\b(const|let)\s+\w*(project|allowList)\w*\s*=\s*(\(|function)", text, re.I)
    if "askChain" not in text and "askStepToEntries" not in text:
        pytest.skip("console.js does not use the Ask functions yet (task 4.5 not written)")
    assert "formatTranscriptEntry(" in text
    assert "askStepToEntries(" in text


# --- task 8.2: the trace carries no count member -------------------------------------


def test_ask_trace_schema_has_no_count_member():
    # Requirements 9.1, 12.8: the page computes counts with summariseRun; the server sends none.
    from greenscreen.publisher.ask.service import ask_openapi

    schema = ask_openapi(500, 2000)[1]["AskTrace"]
    assert set(schema["properties"]) == {"model_turns", "tool_calls", "elapsed_ms", "steps"}
    assert schema["additionalProperties"] is False
    for banned in ("steps_count", "screens"):
        assert banned not in schema["properties"]
        assert banned not in json.dumps(schema["properties"]["steps"]), banned
