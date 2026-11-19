"""The Ask functions of the Snippets_Module run by a real Node process (spec ask, task 4.3)."""
from __future__ import annotations

import json
import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.publisher.ask.codes import REFUSAL_SENTENCE
from tests.console_node_ask import call_one, needs_node, run_ask_calls, snippets_source

pytestmark = needs_node

PRINTABLE = re.compile(r"^[\x20-\x7e]{0,100}$")
FUNCTIONS = ("buildAskBody", "askExamples", "askStepToEntries", "askChain", "askRunLine", "askAnswerNotice")


def audit(*rows):
    return [
        {
            "step_index": i, "kind": "send", "phase": "run", "iteration": None,
            "signature": sig, "status": status, "duration_seconds": 0.1,
        }
        for i, (sig, status) in enumerate(rows)
    ]


def tool(turn, id, name, ok=True, code="ok", rows=(), reason=None):
    step = {
        "type": "tool", "turn": turn, "id": id, "tool": name, "arguments": {},
        "ok": ok, "code": code, "duration_ms": 5,
    }
    if reason is not None:
        step["reason"] = reason
        step["result"] = None
    elif ok:
        step["result"] = {"flow": name, "outputs": {}, "audit": audit(*rows)} if rows else {"flow": name, "outputs": {}}
    else:
        error = {"code": code, "message": "m"}
        if rows:
            error["audit"] = audit(*rows)
        step["result"] = {"error": error}
    return step


def model(turn, outcome):
    return {"type": "model", "turn": turn, "outcome": outcome, "tool_calls": 0, "duration_ms": 1}


def trace(*steps):
    return {"model_turns": 1, "tool_calls": 0, "elapsed_ms": 1, "steps": [{"type": "tools", "offered": ["a"]}, *steps]}


def texts(question, tr, answer=""):
    lines = call_one("askChain", question, tr, answer)
    assert all(set(line) == {"text", "step"} for line in lines)
    return [line["text"] for line in lines]


def test_all_six_functions_and_the_constant_are_exported():
    results = run_ask_calls([{"fn": name, "args": []} for name in (*FUNCTIONS, "ASK_REFUSAL")])
    assert not any("threw" in r for r in results)
    src = snippets_source()
    for name in FUNCTIONS:
        assert re.search(rf"export function {name}\(", src)


def test_ask_refusal_equals_the_python_constant():
    assert call_one("ASK_REFUSAL") == REFUSAL_SENTENCE


def test_build_ask_body():
    assert call_one("buildAskBody", 'What "is" this?\n') == '{"question":"What \\"is\\" this?\\n"}'


def test_ask_examples_limits_and_hostile_values():
    flows = [
        {"name": "needs-input", "description": "x", "inputs": [{"name": "a", "required": True}]},
        {"name": "has secret", "description": "x", "inputs": []},
        {"name": "sec", "description": "x", "inputs": [{"name": "p", "secret": True}]},
        {"name": "ok-one", "description": "  Shows\tthe\n  system \u00e9\x00 info  ", "inputs": []},
        {"name": "ok-two", "blurb": "b" * 300, "inputs": [{"name": "o", "required": False}]},
        {"name": "ok_3", "inputs": []},
        {"name": "ok-4", "inputs": []},
        {"name": "x" * 65, "inputs": []},
        None,
        7,
    ]
    items = call_one("askExamples", flows, 3)
    assert [i["text"] for i in items] == [
        "Run ok-one and tell me what it returns.",
        "Run ok-two and tell me what it returns.",
        "Run ok_3 and tell me what it returns.",
    ]
    assert items[0]["hint"] == "Shows the system info"
    assert items[1]["hint"] == "b" * 100
    assert items[2]["hint"] == ""
    assert len(call_one("askExamples", flows, 99)) == 3
    assert len(call_one("askExamples", flows, 1)) == 1
    assert call_one("askExamples", flows, 0) == []
    assert call_one("askExamples", "junk", 3) == []


def test_transcript_line_limits_for_hostile_tool_names():
    long = "n" * 500
    step = tool(1, 1, long)
    entries = call_one("askStepToEntries", step)
    out = run_ask_calls(
        [
            {"fn": "formatTranscriptEntry", "args": [entries["sent"]]},
            {"fn": "formatTranscriptEntry", "args": [entries["received"]]},
        ]
    )
    for item in out:
        assert PRINTABLE.match(item["value"]["line"])
    chain = texts("q", trace(model(1, "tool_calls"), step, model(2, "answer")), "a")
    assert all(PRINTABLE.match(t) for t in chain[1:])


def test_ask_step_to_entries_ordinary_and_rejected():
    step = tool(1, 2, "tk5-system-info", rows=[("s1", "ok")])
    step["arguments"] = {"x": 1}
    entries = call_one("askStepToEntries", step)
    assert entries["sent"]["direction"] == "sent"
    assert entries["sent"]["method"] == "tools/call"
    assert re.fullmatch(r'\{"jsonrpc":"2\.0","id":2,"method":"tools/call","params":\{"name":"tk5-system-info","arguments":\{"x":1\}\}\}', entries["sent"]["text"])
    assert entries["received"] == {
        "direction": "received", "method": "tools/call", "status": 200, "text": "",
        "message": {"jsonrpc": "2.0", "id": 2, "result": {"isError": False, "structuredContent": step["result"]}},
    }
    failed = call_one("askStepToEntries", tool(1, 1, "t", ok=False, code="timeout"))
    assert failed["received"]["message"]["result"]["isError"] is True
    assert call_one("askStepToEntries", tool(1, 1, "t", ok=False, code="rejected", reason="unknown_tool")) is None
    assert call_one("askStepToEntries", model(1, "answer")) is None
    assert call_one("askStepToEntries", None) is None


def test_chain_answered_with_one_tool():
    rows = [(f"s{i % 9}", "ok") for i in range(27)]
    tr = trace(model(1, "tool_calls"), tool(1, 1, "tk5-system-info", rows=rows), model(2, "answer"))
    lines = call_one("askChain", "What system is this, and which release?", tr, "It is TK5.")
    assert [l["text"] for l in lines] == [
        "You asked: What system is this, and which release?",
        "model turn 1: asked for tool tk5-system-info",
        "MCP tool tk5-system-info: 27 steps on 9 screens",
        "model turn 2: answered",
    ]
    assert [l["step"] for l in lines] == [None, None, 2, None]  # index counts the `tools` step


def test_chain_refused_without_a_tool():
    tr = trace(model(1, "answer"))
    assert texts("What is the capital of France?", tr, "  " + REFUSAL_SENTENCE + "\n") == [
        "You asked: What is the capital of France?",
        "model turn 1: answered without a tool (refused)",
    ]
    assert texts("q", tr, "Paris")[-1] == "model turn 1: answered without a tool"
    assert texts("q", tr, REFUSAL_SENTENCE + " more")[-1] == "model turn 1: answered without a tool"


def test_chain_several_tools_in_one_turn_and_more_than_three():
    tr = trace(model(1, "tool_calls"), tool(1, 1, "a"), tool(1, 2, "b"), tool(1, 3, "a"), model(2, "answer"))
    assert texts("q", tr, "x")[1] == "model turn 1: asked for tools a, b"
    many = trace(model(1, "tool_calls"), *[tool(1, i, n) for i, n in enumerate("abcde", 1)], model(2, "answer"))
    assert texts("q", many, "x")[1] == "model turn 1: asked for tools a, b, c +2 more"
    one_more = trace(model(1, "tool_calls"), *[tool(1, i, n) for i, n in enumerate("abcd", 1)])
    assert texts("q", one_more)[1] == "model turn 1: asked for tools a, b, c +1 more"


def test_chain_rejected_failed_and_ok_tool_lines():
    tr = trace(
        model(1, "tool_calls"),
        tool(1, 1, "a", ok=False, code="rejected", reason="unknown_tool"),
        tool(1, 2, "b", ok=False, code="unknown_screen"),
        tool(1, 3, "c", ok=False, code="timeout", rows=[("s1", "ok"), ("s2", "skipped"), ("s1", "ok")]),
        tool(1, 4, "d"),
        tool(1, 5, "e", rows=[("s1", "ok")]),
        tool(1, 6, "f", ok=False, code="Bad Code!"),
    )
    lines = texts("q", tr)
    assert lines[2:] == [
        "refused tool call 1: unknown_tool",
        "MCP tool b: failed (unknown_screen)",
        "MCP tool c: failed (timeout), 2 steps on 1 screen",
        "MCP tool d: ok",
        "MCP tool e: 1 step on 1 screen",
        "MCP tool f: failed (unknown)",
    ]


def test_chain_has_no_line_for_the_tools_step():
    assert texts("q", trace()) == ["You asked: q"]
    assert texts("q", {"steps": [{"type": "tools", "offered": ["x", "y"]}]}) == ["You asked: q"]


def test_chain_question_cut_and_control_characters():
    long = "é" * 201
    first = texts(long, trace())[0]
    assert first == "You asked: " + "é" * 200 + "\u2026"
    assert texts("é" * 200, trace())[0] == "You asked: " + "é" * 200
    assert texts("a\x00b\r\n\t  c\x1f\x7f\x85d", trace())[0] == "You asked: a b c d"
    astral = "\U0001f600" * 201
    assert texts(astral, trace())[0] == "You asked: " + "\U0001f600" * 200 + "\u2026"


def test_chain_singular_forms():
    tr = trace(model(1, "tool_calls"), tool(1, 1, "a", rows=[("s", "ok")]))
    assert texts("q", tr)[1:] == ["model turn 1: asked for tool a", "MCP tool a: 1 step on 1 screen"]
    two = trace(tool(1, 1, "a", rows=[("s", "ok"), ("t", "ok")]))
    assert texts("q", two)[1] == "MCP tool a: 2 steps on 2 screens"
    assert call_one("askRunLine", tr) == "1 step on 1 distinct screen"
    assert call_one("askRunLine", two) == "2 steps on 2 distinct screens"
    assert call_one("askRunLine", trace(tool(1, 1, "a"))) == ""


def test_chain_long_lines_are_cut_to_100_printable_characters():
    names = ["n" * 60, "m" * 60, "k" * 60]
    steps = [model(1, "tool_calls"), *[tool(1, i, n) for i, n in enumerate(names, 1)]]
    lines = texts("q", trace(*steps))
    assert all(PRINTABLE.match(t) for t in lines[1:])
    assert lines[1].endswith("...") and len(lines[1]) == 100
    odd = trace(model(1, "tool_calls"), tool(1, 1, "caf\u00e9"), tool(1, 2, "a", ok=False, code="rejected", reason="r\u00e9"))
    assert all(PRINTABLE.match(t) for t in texts("q", odd)[1:])


def test_notice_and_run_line():
    assert call_one("askAnswerNotice", True) == "The answer was cut to the length limit."
    for value in (False, None, "true", 1):
        assert call_one("askAnswerNotice", value) == ""


def test_no_function_throws_on_junk_input():
    junk = [None, 0, -1, 1.5, "", "x", True, [], [None], {}, {"steps": 5}, {"steps": [None, 1, "a", {"type": "tool"}, {"type": "model"}]},
            {"steps": [{"type": "tool", "tool": 5, "code": 7, "result": 3, "turn": "x"}]},
            {"steps": [{"type": "model", "outcome": "tool_calls", "turn": None}]}]
    calls = []
    for a in junk:
        for b in junk:
            calls.append({"fn": "askChain", "args": [a, b, a]})
        calls.append({"fn": "askStepToEntries", "args": [a]})
        calls.append({"fn": "askRunLine", "args": [a]})
        calls.append({"fn": "askAnswerNotice", "args": [a]})
        calls.append({"fn": "buildAskBody", "args": [a]})
        calls.append({"fn": "askExamples", "args": [a, a]})
        calls.append({"fn": "askExamples", "args": [[a, {"name": "ok", "inputs": a}], 3]})
    results = run_ask_calls(calls)
    assert not [c["fn"] for c, r in zip(calls, results) if "threw" in r]
    for call, result in zip(calls, results):
        if call["fn"] == "askChain":
            assert result["value"][0]["text"].startswith("You asked: ")
            assert all(PRINTABLE.match(line["text"]) for line in result["value"][1:])


def test_run_line_counts_come_from_summarise_run():
    # Requirements 9.1, 12.8: askRunLine uses summariseRun over every tool step's audit.
    rows_a = [("s1", "ok"), ("s2", "skipped"), ("s1", "ok")]
    rows_b = [("s2", "ok"), ("s3", "ok")]
    tr = trace(model(1, "tool_calls"), tool(1, 1, "a", rows=rows_a), tool(1, 2, "b", rows=rows_b))
    combined = audit(*rows_a) + audit(*rows_b)
    counts = call_one("summariseRun", combined)
    line = call_one("askRunLine", tr)
    assert line == f"{counts['steps']} steps on {counts['screens']} distinct screens"
    assert (counts["steps"], counts["screens"]) == (4, 3)
    src = snippets_source()
    start = src.index("export function askRunLine(")
    body = src[start : src.index("export function askAnswerNotice(")]
    assert "summariseRun(" in body


def test_ask_functions_do_not_modify_answer_text():
    # Requirement 12.5: the page does not touch asterisks or underscores (the server does).
    src = snippets_source()
    for name in FUNCTIONS:
        start = src.index(f"export function {name}(")
        nxt = src.find("export ", start + 10)
        body = src[start : nxt if nxt != -1 else len(src)]
        assert not re.search(r"""\.replace(All)?\s*\(\s*(/[^/\n]*[*_][^/\n]*/|["'][*_]+["'])""", body), name


# --------------------------------------------------------------------------
# Task 11.1: askParse and askCounterText (Requirement 12, criterion 17)
# --------------------------------------------------------------------------

def recorded_openapi(env=None):
    """The real /openapi.json of an app with Ask on, as parsed JSON."""
    import asyncio

    from tests.ask_support import build_ask_app
    from tests.console_support import call_scope

    app = build_ask_app(env)
    status, _, raw = asyncio.run(call_scope(app.app.asgi, "GET", "/openapi.json", {"X-API-Key": app.api_key}))
    assert status == 200
    return json.loads(raw)


def counter_after_parse(doc, used):
    """Run askParse then askCounterText(used, parsed.maxQuestion) in one Node process."""
    parsed = call_one("askParse", doc)
    assert parsed is not None
    return parsed, call_one("askCounterText", used, parsed["maxQuestion"])


def test_real_openapi_document_gives_the_counter_text():
    doc = recorded_openapi()
    parsed = call_one("askParse", doc)
    assert parsed == {"maxQuestion": 500}
    assert counter_after_parse(doc, 0)[1] == "0 / 500"
    assert counter_after_parse(doc, 65)[1] == "65 / 500"


def test_real_openapi_document_with_the_limit_at_321():
    doc = recorded_openapi({"GS_ASK_MAX_QUESTION_CHARS": "321"})
    assert call_one("askParse", doc) == {"maxQuestion": 321}
    assert counter_after_parse(doc, 0)[1] == "0 / 321"


def test_counter_text_of_the_parse_object_is_empty_never_object_text():
    parsed = call_one("askParse", recorded_openapi())
    assert isinstance(parsed, dict)
    results = run_ask_calls([{"fn": "askCounterText", "args": [5, parsed]}])
    assert results[0]["value"] == ""
    assert "[object" not in results[0]["value"]


def test_counter_text_rejects_bad_limits_and_bad_counts():
    bad_max = [None, "undefined", "NaN", -1, 1.5, "5", 0, 2001, [], [500], {}, {"maxQuestion": 500}, True]
    calls = [{"fn": "askCounterText", "args": [5, m]} for m in bad_max]
    calls.append({"fn": "askCounterText", "args": [5]})  # max undefined
    bad_used = [None, -1, 1.5, "5", [], [5], {}, {"a": 1}, True, 2**60]
    calls += [{"fn": "askCounterText", "args": [u, 500]} for u in bad_used]
    for result in run_ask_calls(calls):
        assert result == {"value": ""}
    good = run_ask_calls(
        [
            {"fn": "askCounterText", "args": [0, 1]},
            {"fn": "askCounterText", "args": [0, 2000]},
            {"fn": "askCounterText", "args": [7, 500]},
        ]
    )
    assert [g["value"] for g in good] == ["0 / 1", "0 / 2000", "7 / 500"]


def ask_doc(max_length=500, *, drop=None):
    schema = {"properties": {"question": {"type": "string", "maxLength": max_length}}}
    post = {"requestBody": {"content": {"application/json": {"schema": schema}}}}
    doc = {"paths": {"/ask": {"post": post}}}
    if drop == "path":
        doc["paths"] = {"/other": {"post": post}}
    elif drop == "post":
        doc["paths"]["/ask"] = {"get": post}
    elif drop == "schema":
        del post["requestBody"]["content"]["application/json"]["schema"]
    return doc


def test_ask_parse_accepts_and_rejects_documents():
    docs = [
        ask_doc(), ask_doc(drop="path"), ask_doc(drop="post"), ask_doc(0), ask_doc(2001),
        ask_doc("500"), ask_doc(500.5), ask_doc(drop="schema"), ask_doc(1), ask_doc(2000),
        None, [], "paths", 5, {}, {"paths": []}, {"paths": {"/ask": []}},
    ]
    results = run_ask_calls([{"fn": "askParse", "args": [d]} for d in docs])
    assert [r["value"] for r in results] == [
        {"maxQuestion": 500}, None, None, None, None, None, None, None,
        {"maxQuestion": 1}, {"maxQuestion": 2000},
        None, None, None, None, None, None, None,
    ]


JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers(-(2**70), 2**70) | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=12),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=6), inner, max_size=3),
    max_leaves=6,
)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(st.tuples(JSON_VALUES, JSON_VALUES), min_size=1, max_size=20))
def test_counter_text_never_throws_and_never_prints_object_text(pairs):
    calls = [{"fn": "askCounterText", "args": [u, m]} for u, m in pairs]
    calls += [{"fn": "askParse", "args": [u]} for u, _ in pairs]
    for call, result in zip(calls, run_ask_calls(calls)):
        assert "threw" not in result
        if call["fn"] == "askCounterText":
            assert isinstance(result["value"], str)
            assert "[object" not in result["value"]


def test_new_functions_keep_the_module_pure():
    src = snippets_source()
    start = src.index("export function askParse(")
    body = src[start:]
    assert "summary" not in src.lower()
    assert "console." not in src
    assert not re.search(r"^\s*import\b", src, re.MULTILINE)
    assert not re.search(r"function\s+\w+\s*\([^)]*key", body, re.IGNORECASE)
