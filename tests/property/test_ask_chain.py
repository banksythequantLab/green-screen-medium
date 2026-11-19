"""Property 6 of spec ask: the lines of the Chain (task 4.3).

Runs `askChain` under Node, one `node` process per generated batch of cases.
"""
from __future__ import annotations

import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.publisher.ask.codes import REFUSAL_SENTENCE, REJECT_REASONS
from tests.console_node_ask import needs_node, run_ask_calls, summarise_run

pytestmark = needs_node

PRINTABLE = re.compile(r"^[\x20-\x7e]{0,100}$")
# JavaScript's `\s` and `trim()` set (Python's differs on U+FEFF and a few others).
JS_SPACE = (
    "\t\n\u000b\u000c\r \u00a0\u1680"
    + "".join(chr(c) for c in range(0x2000, 0x200B))
    + "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
SPACES = re.compile("[" + "".join(re.escape(c) for c in JS_SPACE) + "]+")
CODES = ("unknown_screen", "timeout", "internal_error", "busy", "run_timeout", "session_error")

# --- generators -----------------------------------------------------------------------

_hex = st.text(alphabet="0123456789abcdef", min_size=24, max_size=32)
_PROBES = st.builds(
    lambda a, b, c: ("gsk_" + a, "sk-" + b, "https://llm-" + c + ".example/v1"), _hex, _hex, _hex
)
_TEXT = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=60)
_QUESTION = st.one_of(
    _TEXT,
    st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=195, max_size=230),
    st.text(alphabet="ab \t\n\r\x00\x1f\x7f\x85\u00a0\ufeff\u2028", max_size=40),
)
_NAME = st.from_regex(r"[a-z0-9_-]{1,64}", fullmatch=True)
_SIG = st.none() | st.sampled_from(["", "s1", "s2", "s3", "s4"])
_ROW = st.tuples(_SIG, st.sampled_from(["ok", "ok", "skipped", "failed"]))
_ANSWER = st.one_of(
    st.just(REFUSAL_SENTENCE),
    st.builds(lambda pad, tail: pad + REFUSAL_SENTENCE + pad + tail, st.sampled_from(["", " ", "\n"]), st.sampled_from(["", " x"])),
    _TEXT,
)
_TOOL = st.fixed_dictionaries(
    {
        "name": _NAME,
        "kind": st.sampled_from(["rejected", "ok", "ok_audit", "fail", "fail_audit"]),
        "code": st.sampled_from(CODES),
        "reason": st.sampled_from(sorted(REJECT_REASONS)),
        "rows": st.lists(_ROW, min_size=1, max_size=12),
    }
)
# Each turn is the list of tool calls the model asked for; the last turn may be an answer.
_CASE = st.fixed_dictionaries(
    {
        "question": _QUESTION,
        "turns": st.lists(st.lists(_TOOL, min_size=1, max_size=6), max_size=3),
        "ends": st.sampled_from(["answer", "stopped"]),
        "answer": _ANSWER,
        "probes": _PROBES,
    }
)


def audit_rows(rows, probes):
    return [
        {
            "step_index": i, "kind": "send", "phase": "run", "iteration": None, "signature": sig,
            "status": status, "duration_seconds": 0.5, "extra": probes[0],
        }
        for i, (sig, status) in enumerate(rows)
    ]


def build(case):
    """Return (trace, expected_lines) for one case; the expected lines are the grammar."""
    pub, key, url = case["probes"]
    steps = [{"type": "tools", "offered": ["a"]}]
    expected_tail: list[str] = []
    tool_id = 0
    seen_tool = False
    for turn_index, turn in enumerate(case["turns"], start=1):
        steps.append({"type": "model", "turn": turn_index, "outcome": "tool_calls", "tool_calls": len(turn), "duration_ms": 1})
        distinct: list[str] = []
        for tool in turn:
            if tool["name"][:40] not in distinct:
                distinct.append(tool["name"][:40])
        shown = ", ".join(distinct[:3]) + (f" +{len(distinct) - 3} more" if len(distinct) > 3 else "")
        expected_tail.append(finish(f"model turn {turn_index}: asked for {'tool' if len(distinct) == 1 else 'tools'} {shown}"))
        for tool in turn:
            tool_id += 1
            seen_tool = True
            base = {
                "type": "tool", "turn": turn_index, "id": tool_id, "tool": tool["name"],
                "arguments": {"api_key": pub, "url": url}, "duration_ms": 1,
            }
            name = tool["name"][:40]
            if tool["kind"] == "rejected":
                base.update(ok=False, code="rejected", reason=tool["reason"], result=None)
                expected_tail.append(finish(f"refused tool call {tool_id}: {tool['reason'][:60]}"))
            elif tool["kind"].startswith("ok"):
                rows = audit_rows(tool["rows"], case["probes"]) if tool["kind"] == "ok_audit" else None
                result = {"flow": name, "outputs": {"o": key}}
                if rows is not None:
                    result["audit"] = rows
                base.update(ok=True, code="ok", result=result)
                expected_tail.append(finish(f"MCP tool {name}: " + (counts(rows) if rows else "ok")))
            else:
                rows = audit_rows(tool["rows"], case["probes"]) if tool["kind"] == "fail_audit" else None
                error = {"code": tool["code"], "message": key}
                if rows is not None:
                    error["audit"] = rows
                base.update(ok=False, code=tool["code"], result={"error": error})
                text = f"MCP tool {name}: failed ({tool['code']})"
                expected_tail.append(finish(text + (", " + counts(rows) if rows else "")))
            steps.append(base)
    answer = ""
    if case["ends"] == "answer":
        turn_number = len(case["turns"]) + 1
        answer = case["answer"]
        refused = answer.strip(" \t\n") == REFUSAL_SENTENCE
        tail = "answered" if seen_tool else "answered without a tool"
        steps.append({"type": "model", "turn": turn_number, "outcome": "answer", "tool_calls": 0, "duration_ms": 1})
        expected_tail.append(finish(f"model turn {turn_number}: {tail}" + (" (refused)" if refused else "")))
    trace = {"model_turns": 1, "tool_calls": tool_id, "elapsed_ms": 1, "steps": steps}
    return trace, answer, [first_line(case["question"])] + expected_tail


def finish(line):
    return line if len(line) <= 100 else line[:97] + "..."


def counts(rows):
    total = summarise_run(rows)
    steps, screens = total["steps"], total["screens"]
    return f"{steps} step{'' if steps == 1 else 's'} on {screens} screen{'' if screens == 1 else 's'}"


def first_line(question):
    text = SPACES.sub(" ", CONTROL.sub(" ", question)).strip(JS_SPACE)
    return "You asked: " + (text[:200] + "\u2026" if len(text) > 200 else text)


@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(cases=st.lists(_CASE, min_size=1, max_size=6))
def test_chain_lines_follow_the_grammar_and_hold_no_key(cases):
    # Feature: ask, Property 6: No Chain line holds a key, and every line follows the grammar
    # **Validates: Requirements 12.7, 12.8**
    built = [build(case) for case in cases]
    results = run_ask_calls(
        [{"fn": "askChain", "args": [case["question"], trace, answer]} for case, (trace, answer, _) in zip(cases, built)]
    )
    for case, (trace, _answer, expected), result in zip(cases, built, results):
        assert "threw" not in result
        lines = [line["text"] for line in result["value"]]
        assert lines == expected
        assert lines[0].startswith("You asked: ")
        assert all(PRINTABLE.match(line) for line in lines[1:])
        for probe in case["probes"]:
            assert not any(probe in line for line in lines)
        # no line for the offered-tools step; tool lines carry the index of their own step
        for line in result["value"]:
            if line["step"] is not None:
                assert trace["steps"][line["step"]]["type"] == "tool"
        assert not any(line.startswith("tools") for line in lines)
