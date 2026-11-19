# Feature: console, Property 4: The wire transcript never holds the key or a typed secret
"""Property 4: the wire transcript never holds the key or a typed secret.

**Validates: Requirements 18.13, 18.15, 18.19, 18.24**

Requirements 18.13, 18.15, 18.19 and 18.24. The module runs under `node`; one example
is a batch of up to 15 cases and two `node` processes. Failure messages name the case
index and the rule, never a value (the generated key and secrets are test data, but
they are still not printed by this test).

The oracle below is written apart from the module under test: it knows the shapes of
the messages it plants and the names it expects to see in `omitted`.

Deviation from the design text, reported with the task: the design's list of outputs
that must be free of the key names `parseMcpReply` and `classifyToolsCall`. Those two
return the parsed server message as it came, which holds the planted text by
construction. This test therefore checks them for losslessness and kind, and checks
the page's display path (`formatTranscriptEntry` of the same messages) for secrecy.
"""
from __future__ import annotations

import json
import re
import string
from urllib.parse import quote

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.console_node_mcp import needs_node, run_calls

pytestmark = needs_node

LINE = re.compile(r"^[\x20-\x7E]{1,100}$")
UNICODE = st.characters(blacklist_categories=("Cs",))
KEY_CHARS = st.one_of(st.sampled_from(list(string.ascii_letters + string.digits + "-_.+/='\"\\ ")), UNICODE)
NAME_BODY = st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=6)


def forms(value: str) -> list[str]:
    return list(
        {
            value,
            json.dumps(value)[1:-1],
            json.dumps(value, ensure_ascii=False)[1:-1],
            quote(value, safe=""),
            quote(value),
        }
    )


def strings(value):
    """Every string in a JSON value, member names included."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, dict):
        for name, item in value.items():
            yield name
            yield from strings(item)


@st.composite
def cases(draw):
    key = "GSK" + draw(st.text(KEY_CHARS, min_size=13, max_size=61))
    secrets = [
        "SECRET-" + draw(st.text(string.hexdigits.lower(), min_size=8, max_size=24))
        for _ in range(draw(st.integers(0, 2)))
    ]
    if len(set(secrets)) != len(secrets):
        secrets = secrets[:1]
    forbidden = [key, *secrets]

    def free(text: str) -> bool:
        return not any(form in text for item in forbidden for form in forms(item))

    def fact(max_size=60):
        return draw(st.text(UNICODE, min_size=1, max_size=max_size).filter(free))

    typed = [
        {"name": f"n{i}", "type": "string", "secret": False, "required": True, "value": draw(st.text(UNICODE, max_size=30).filter(free))}
        for i in range(draw(st.integers(0, 3)))
    ]
    if draw(st.booleans()):
        typed.append({"name": "count", "type": "integer", "secret": False, "required": True, "value": draw(st.from_regex(r"-?(0|[1-9][0-9]{0,24})", fullmatch=True))})
    inputs = typed + [
        {"name": f"s{i}", "type": "string", "secret": True, "required": True, "value": value}
        for i, value in enumerate(secrets)
    ]
    return {
        "key": key,
        "secrets": secrets,
        "inputs": inputs,
        "flow": fact(),
        "server": fact(),
        "tools": [fact() for _ in range(draw(st.integers(1, 4)))],
        "code": draw(st.one_of(st.from_regex(r"[a-z_]{1,40}", fullmatch=True), st.text(UNICODE, min_size=1, max_size=60).filter(free))),
        "rpc": draw(st.sampled_from([-32700, -32600, -32601, -32602, -32603, 7, -1])),
        "session": draw(st.one_of(st.none(), st.text(string.ascii_letters + string.digits, min_size=1, max_size=20))),
        "names": ["x_" + draw(NAME_BODY) + str(i) for i in range(4)],
    }


AUDIT_ROW = {"step_index": 0, "kind": "expect", "phase": "main", "iteration": None, "signature": "tk5-logon", "status": "ok", "duration_seconds": 0.1}


def planted_messages(case):
    """The received messages with the key and the secrets planted outside the allow-lists, and the expected omissions."""
    plant = " ".join([case["key"], *case["secrets"]])
    n0, n1 = case["names"][0], case["names"][1]
    row = {**AUDIT_ROW, n0: plant}
    return {
        "initialize": (
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": case["server"], "version": "1", n0: plant}, "instructions": plant, n1: plant}},
            {f"serverInfo.{n0}", "instructions", n1},
        ),
        "tools/list": (
            {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": name, "description": "d", "inputSchema": {"type": "object"}, "title": plant, n0: {"deep": plant}} for name in case["tools"]], "nextCursor": plant}},
            {"tools[].title", f"tools[].{n0}", "nextCursor"},
        ),
        "call_ok": (
            {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": plant}], "structuredContent": {"flow": case["flow"], "outputs": {"o": "v"}, "audit": [row, row], "summary": plant, n1: plant}}},
            {"content", f"structuredContent.audit[].{n0}", "structuredContent.summary", f"structuredContent.{n1}"},
        ),
        "call_error": (
            {"jsonrpc": "2.0", "id": 3, "result": {"isError": True, "content": [{"type": "text", "text": plant}], "structuredContent": {"error": {"code": case["code"], "message": "m", "step_index": 1, "kind": "expect", "expected": "x", "audit": [row], "summary": plant, n1: plant}}}},
            {"content", f"structuredContent.error.audit[].{n0}", "structuredContent.error.summary", f"structuredContent.error.{n1}"},
        ),
        "rpc": (
            {"jsonrpc": "2.0", "id": 1, "error": {"code": case["rpc"], "message": plant, "data": {"a": plant}}, n0: plant},
            {"error.message", "error.data", n0},
        ),
        "publisher": ({"error": {"code": "unauthorized", "message": plant}}, {"error"}),
        "other": ({"jsonrpc": "2.0", "id": 9, "method": "sampling/create", "params": {"a": plant}, n0: plant}, {"params", n0}),
    }


def check(ok: bool, index: int, rule: str) -> None:
    if not ok:
        pytest.fail(f"case {index}: rule broken: {rule}")


def check_clean(index: int, label: str, output, case) -> None:
    for text in strings(output):
        for item in (case["key"], *case["secrets"]):
            for form in forms(item):
                if form in text:
                    pytest.fail(f"case {index}: {label} holds a forbidden value")


def run_batch(batch):
    # Phase 1: builders and headers.
    first = []
    for case in batch:
        first += [
            {"fn": "buildInitialize", "args": [1]},
            {"fn": "buildInitialized", "args": []},
            {"fn": "buildToolsList", "args": [2]},
            {"fn": "buildToolsCall", "args": [3, case["flow"], case["inputs"], True]},
            {"fn": "buildToolsCall", "args": [3, case["flow"], case["inputs"], False]},
            {"fn": "mcpRequestHeaders", "args": ["2025-11-25", case["session"]]},
        ]
    built = run_calls(first)
    for number, result in enumerate(built):
        check("error" not in result, number // 6, "a builder raised")

    second = []
    plan = []
    for index, case in enumerate(batch):
        init_t, inited_t, list_t, call_masked, call_wire, headers = (built[index * 6 + n]["value"] for n in range(6))
        msgs = planted_messages(case)
        sent = [("initialize", init_t), ("notifications/initialized", inited_t), ("tools/list", list_t), ("tools/call", call_masked)]
        for method, text in sent:
            second.append({"fn": "formatTranscriptEntry", "args": [{"direction": "sent", "method": method, "text": text}]})
            plan.append((index, f"sent {method}", None))
        for label, method, status in (
            ("initialize", "initialize", 200), ("tools/list", "tools/list", 200), ("call_ok", "tools/call", 200),
            ("call_error", "tools/call", 200), ("rpc", "tools/list", 400), ("publisher", "tools/call", 401), ("other", "tools/call", 200),
        ):
            message, expected = msgs[label]
            second.append({"fn": "formatTranscriptEntry", "args": [{"direction": "received", "method": method, "status": status, "text": "x", "message": message}]})
            plan.append((index, f"received {label}", expected))
        second.append({"fn": "formatTranscriptEntry", "args": [{"direction": "received", "method": "tools/call", "status": 202, "text": " ".join([case["key"], *case["secrets"]]), "message": None}]})
        plan.append((index, "received unreadable", set()))
        second.append({"fn": "formatTranscriptEntry", "args": [{"direction": "received", "method": "notifications/initialized", "status": 202, "text": "", "message": None}]})
        plan.append((index, "received 202", set()))
        for label in ("initialize", "call_ok", "call_error"):
            message = msgs[label][0]
            second.append({"fn": "parseMcpReply", "args": ["application/json", json.dumps(message)]})
            plan.append((index, f"parse json {label}", message))
            second.append({"fn": "parseMcpReply", "args": ["text/event-stream", "data: " + json.dumps(message) + "\n\n"]})
            plan.append((index, f"parse sse {label}", message))
        second.append({"fn": "classifyToolsCall", "args": [msgs["call_ok"][0]]})
        plan.append((index, "classify ok", "success"))
        second.append({"fn": "classifyToolsCall", "args": [msgs["call_error"][0]]})
        plan.append((index, "classify error", "tool_error"))
        second.append({"fn": "summariseRun", "args": [[AUDIT_ROW, {**AUDIT_ROW, "status": "skipped"}]]})
        plan.append((index, "summarise", {"steps": 1, "screens": 1}))
        for via in ("mcp", "rest"):
            second.append({"fn": "stripStages", "args": [via, case["tools"][0], {"steps": 1, "screens": 1}]})
            plan.append((index, f"strip {via}", None))
    done = run_calls(second)

    for index, case in enumerate(batch):
        init_t, inited_t, list_t, call_masked, call_wire, headers = (built[index * 6 + n]["value"] for n in range(6))
        # Builders: key-free in every form; masked text free of secrets.
        for label, text in (("initialize", init_t), ("initialized", inited_t), ("tools/list", list_t), ("masked call", call_masked), ("wire call", call_wire)):
            check_clean_key(index, label, text, case)
        check_clean(index, "masked call", call_masked, case)
        check_clean_key(index, "headers", headers, case)
        check("key" not in " ".join(name.lower() for name in headers), index, "a header member is named like a key")
        # Masked and unmasked arguments.
        masked = json.loads(call_masked)["params"]["arguments"]
        wire = json.loads(call_wire)
        arguments = wire["params"]["arguments"]
        for item in case["inputs"]:
            if item["secret"]:
                check(masked[item["name"]] == "<SECRET>", index, "a Secret_Input is not masked")
                check(arguments[item["name"]] == item["value"], index, "the wire form lost a typed value")
            elif item["type"] == "string":
                check(masked[item["name"]] == item["value"] and arguments[item["name"]] == item["value"], index, "a typed value changed")
        del wire["params"]["arguments"]
        check_clean(index, "wire call outside arguments", wire, case)

    for (index, label, expected), result in zip(plan, done):
        case = batch[index]
        check("error" not in result, index, f"{label} raised")
        value = result["value"]
        if label.startswith("parse"):
            check(value == {"messages": [expected], "problem": None}, index, f"{label} is not lossless")
        elif label.startswith("classify"):
            check(value["kind"] == expected, index, f"{label} gave a different kind")
        elif label == "summarise":
            check(value == expected, index, "summariseRun counts differ")
        elif label.startswith("strip"):
            check_clean(index, label, value, case)
            check(len(value) == 3, index, "a strip has three stages")
        else:
            check_clean(index, label, value, case)
            check(LINE.match(value["line"]) is not None, index, f"{label}: the line is not one printable ASCII line of at most 100 characters")
            if expected is not None:
                check(set(value["omitted"]) == expected, index, f"{label}: omitted names differ")
            if label == "sent tools/call":
                for item in case["inputs"]:
                    if item["secret"]:
                        check(json.loads(value["text"])["params"]["arguments"][item["name"]] == "<SECRET>", index, "a sent entry does not mask a Secret_Input")


def check_clean_key(index: int, label: str, output, case) -> None:
    for text in strings(output if not isinstance(output, str) else [output]):
        for form in forms(case["key"]):
            if form in text:
                pytest.fail(f"case {index}: {label} holds the key")


@given(st.lists(cases(), min_size=1, max_size=15))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
def test_wire_transcript_never_holds_the_key_or_a_typed_secret(batch):
    run_batch(batch)
