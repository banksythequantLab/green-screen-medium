"""Node tests for the MCP functions of snippets.js (task 8.2; Requirement 18).

Every test runs the real module under `node` and skips with the fixed reason when
`node` is absent. Failure messages never print an input value.
"""
from __future__ import annotations

import json
import re
import shlex

import pytest

from tests.console_node_mcp import needs_node, run_calls

pytestmark = needs_node

UNDEFINED = {"$": "undefined"}
LINE = re.compile(r"^[\x20-\x7E]{1,100}$")


def call(fn, *args):
    result = run_calls([{"fn": fn, "args": list(args)}])[0]
    assert "error" not in result, f"{fn} raised"
    return result["value"]


def raises(fn, *args):
    return "error" in run_calls([{"fn": fn, "args": list(args)}])[0]


def fmt(entry):
    return call("formatTranscriptEntry", entry)


def line(entry):
    return fmt(entry)["line"]


def received(method, message, status=200, text=UNDEFINED):
    return {"direction": "received", "method": method, "status": status, "text": text, "message": message}


def sent(text):
    return {"direction": "sent", "method": json.loads(text)["method"], "text": text}


SECRET_INPUT = {"name": "password", "type": "string", "secret": True, "required": True, "value": "hunter2"}
USER_INPUT = {"name": "userid", "type": "string", "secret": False, "required": True, "value": "ABC'D\"\\"}
INT_INPUT = {"name": "count", "type": "integer", "secret": False, "required": False, "value": "12345678901234567890"}

AUDIT = [
    {"step_index": 0, "kind": "expect", "phase": "main", "iteration": None, "signature": "tk5-logon", "status": "ok", "duration_seconds": 0.1},
    {"step_index": 1, "kind": "type", "phase": "main", "iteration": None, "signature": None, "status": "ok", "duration_seconds": 0.0},
    {"step_index": 2, "kind": "key", "phase": "main", "iteration": None, "signature": "tk5-logon", "status": "ok", "duration_seconds": 0.0},
    {"step_index": 3, "kind": "handle", "phase": "main", "iteration": None, "signature": None, "status": "skipped", "duration_seconds": 0.0},
    {"step_index": 4, "kind": "expect", "phase": "main", "iteration": None, "signature": "ispf-primary-menu", "status": "ok", "duration_seconds": 0.0},
    {"step_index": 5, "kind": "key", "phase": "main", "iteration": None, "signature": "ispf-primary-menu", "status": "skipped", "duration_seconds": 0.0},
]


# ---- builders -------------------------------------------------------------


def test_builders_give_the_exact_wire_texts():
    assert call("buildInitialize", 1) == (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25",'
        '"capabilities":{},"clientInfo":{"name":"greenscreen-console","version":"1"}}}'
    )
    assert call("buildInitialized") == '{"jsonrpc":"2.0","method":"notifications/initialized"}'
    assert call("buildToolsList", 2) == '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
    assert call("buildToolsCall", 3, "tk5-system-info", []) == (
        '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"tk5-system-info","arguments":{}}}'
    )


@pytest.mark.parametrize("bad", [1.5, "1", None, {"$": "NaN"}, {"$": "Infinity"}, 2**60])
def test_builders_reject_an_id_that_is_not_a_safe_integer(bad):
    assert raises("buildInitialize", bad)
    assert raises("buildToolsList", bad)
    assert raises("buildToolsCall", bad, "x", [])


def test_tools_call_masks_secrets_only_when_asked_and_keeps_integers_exact():
    inputs = [USER_INPUT, SECRET_INPUT, INT_INPUT]
    wire = json.loads(call("buildToolsCall", 3, "n", inputs, False))
    shown = call("buildToolsCall", 3, "n", inputs, True)
    assert wire["params"]["arguments"]["password"] == "hunter2"
    assert wire["params"]["arguments"]["userid"] == "ABC'D\"\\"
    assert "hunter2" not in shown and "<SECRET>" in shown
    assert '"count":12345678901234567890' in shown


def test_tools_call_name_with_quote_and_backslash_round_trips():
    name = 'a"b\\c'
    assert json.loads(call("buildToolsCall", 3, name, []))["params"]["name"] == name


# ---- headers --------------------------------------------------------------


def test_request_headers_have_the_four_members_only():
    base = call("mcpRequestHeaders", None, None)
    assert base == {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    full = call("mcpRequestHeaders", "2025-11-25", "abc123")
    assert full["MCP-Protocol-Version"] == "2025-11-25" and full["Mcp-Session-Id"] == "abc123"
    assert len(full) == 4
    assert not any("key" in name.lower() for name in full)


@pytest.mark.parametrize("session", ["", "a b", "caf\u00e9", "tab\t", "\x7f"])
def test_request_headers_drop_an_unusable_session_id(session):
    assert "Mcp-Session-Id" not in call("mcpRequestHeaders", "2025-11-25", session)


def test_request_headers_drop_an_empty_protocol_version():
    assert "MCP-Protocol-Version" not in call("mcpRequestHeaders", "", None)


# ---- parseMcpReply --------------------------------------------------------

MSG = {"jsonrpc": "2.0", "id": 1, "result": {"a": 1}}


def parse(media, text):
    return call("parseMcpReply", media, text)


def test_parse_json_object_array_and_types():
    assert parse("application/json", json.dumps(MSG)) == {"messages": [MSG], "problem": None}
    assert parse("application/json; charset=utf-8", json.dumps(MSG))["messages"] == [MSG]
    assert parse("application/vnd.x+json", json.dumps(MSG))["messages"] == [MSG]
    assert parse(None, json.dumps(MSG))["messages"] == [MSG]
    assert parse("APPLICATION/JSON", json.dumps([MSG, MSG]))["messages"] == [MSG, MSG]


@pytest.mark.parametrize("text", ["", "  \r\n\t "])
def test_parse_empty_text_gives_no_messages_and_no_problem(text):
    assert parse("application/json", text) == {"messages": [], "problem": None}
    assert parse("text/event-stream", text) == {"messages": [], "problem": None}


@pytest.mark.parametrize("text", ["{bad", "7", '"x"', "null", "[1]", "[{}, 2]"])
def test_parse_bad_json(text):
    assert parse("application/json", text) == {"messages": [], "problem": "bad_json"}


def test_parse_unsupported_type():
    assert parse("text/html", "<p>x</p>") == {"messages": [], "problem": "unsupported_type"}


def sse(*events, sep="\n"):
    return (sep + sep).join(events) + sep + sep


def test_sse_one_event_several_events_and_separators():
    one = "data: " + json.dumps(MSG)
    assert parse("text/event-stream", sse(one))["messages"] == [MSG]
    two = sse(one, "data: " + json.dumps({"jsonrpc": "2.0", "method": "x"}))
    assert len(parse("text/event-stream", two)["messages"]) == 2
    assert parse("text/event-stream", sse(one, sep="\r\n"))["messages"] == [MSG]
    assert parse("text/event-stream", sse(one, sep="\r"))["messages"] == [MSG]


def test_sse_ignores_comments_event_id_retry_and_other_fields():
    text = ": hello\nevent: message\nid: 7\nretry: 100\nother: z\ndata: " + json.dumps(MSG) + "\n\n"
    assert parse("text/event-stream", text) == {"messages": [MSG], "problem": None}


def test_sse_joins_multi_line_data_with_a_line_feed():
    text = 'data: {"jsonrpc":"2.0",\ndata: "id":1,\ndata: "result":{}}\n\n'
    assert parse("text/event-stream", text)["messages"] == [{"jsonrpc": "2.0", "id": 1, "result": {}}]


def test_sse_final_event_without_a_blank_line_is_read():
    assert parse("text/event-stream", "data: " + json.dumps(MSG))["messages"] == [MSG]


def test_sse_drops_one_leading_space_only_and_a_leading_bom():
    assert parse("text/event-stream", "data:" + json.dumps(MSG) + "\n\n")["messages"] == [MSG]
    assert parse("text/event-stream", "\ufeffdata: " + json.dumps(MSG) + "\n\n")["messages"] == [MSG]


def test_sse_events_with_empty_data_are_skipped():
    text = "event: ping\n\ndata:\n\ndata\n\ndata: " + json.dumps(MSG) + "\n\n"
    assert parse("text/event-stream", text) == {"messages": [MSG], "problem": None}


@pytest.mark.parametrize("text", ["data: {bad\n\n", "data: 7\n\n", "data: [1]\n\n"])
def test_sse_malformed_or_non_object_data_is_bad_sse(text):
    assert parse("text/event-stream", text) == {"messages": [], "problem": "bad_sse"}


# ---- findReply, hasTool, classify ------------------------------------------


def test_find_reply():
    msgs = [{"jsonrpc": "2.0", "method": "ping", "id": 2}, {"id": 2, "result": {}}, {"id": 2, "error": {"code": 1}}]
    assert call("findReply", msgs, 2) == {"id": 2, "result": {}}
    assert call("findReply", msgs, 3) is None
    assert call("findReply", msgs, "2") is None
    assert call("findReply", UNDEFINED, 2) is None
    assert call("findReply", [{"id": 1, "result": {}}], 1) == {"id": 1, "result": {}}


def test_has_tool():
    listing = {"result": {"tools": [{"name": "a"}, 5, {"name": "b"}]}}
    assert call("hasTool", listing, "b") is True
    assert call("hasTool", listing, "c") is False
    assert call("hasTool", {"result": {}}, "a") is False
    assert call("hasTool", {"error": {}}, "a") is False
    assert call("hasTool", None, "a") is False


SUCCESS = {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "x"}],
           "structuredContent": {"flow": "f", "outputs": {"a": "1", "b": "2"}, "audit": AUDIT}}}
TOOL_ERROR = {"jsonrpc": "2.0", "id": 3, "result": {"isError": True, "content": [],
              "structuredContent": {"error": {"code": "unexpected_screen", "message": "m", "audit": AUDIT, "summary": "SECRET-TEXT"}}}}


def test_classify_shapes():
    assert call("classifyToolsCall", SUCCESS)["kind"] == "success"
    assert call("classifyToolsCall", SUCCESS)["body"]["flow"] == "f"
    err = call("classifyToolsCall", TOOL_ERROR)
    assert err["kind"] == "tool_error" and err["code"] == "unexpected_screen"
    assert call("classifyToolsCall", {"error": {"code": -32601}}) == {"kind": "rpc_error", "rpcCode": -32601}
    for bad in (
        None, [], {}, {"result": {}}, {"result": {"structuredContent": {"flow": 1, "outputs": {}}}},
        {"result": {"structuredContent": {"flow": "f", "outputs": []}}},
        {"result": {"isError": True, "structuredContent": {"error": {"code": 5}}}},
        {"error": {"code": "x"}},
    ):
        assert call("classifyToolsCall", bad) == {"kind": "unreadable"}


# ---- prettyJson -------------------------------------------------------------


def test_pretty_json_keeps_big_integers_and_matches_parse():
    text = '{"a":12345678901234567890,"b":[1,{"c":null}],"d":{},"e":[]}'
    out = call("prettyJson", text)
    assert "12345678901234567890" in out
    assert json.loads(out) == json.loads(text)
    assert '"d": {}' in out and '"e": []' in out
    assert out.startswith('{\n  "a": 1')


def test_pretty_json_strings_with_brackets_commas_and_escapes():
    text = '{"a":"{[,]}: \\" \\\\","b":"x"}'
    out = call("prettyJson", text)
    assert json.loads(out) == json.loads(text)


@pytest.mark.parametrize("text", ["{", '{"a":1', '{"a":"x', "[}", "{]", "}", '"\\'])
def test_pretty_json_returns_unbalanced_text_unchanged(text):
    assert call("prettyJson", text) == text


def test_pretty_json_drops_whitespace_outside_strings():
    assert call("prettyJson", ' { "a" : [ ] } ') == '{\n  "a": []\n}'


# ---- Transcript_Line grammar -------------------------------------------------

INIT_REPLY = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
              "serverInfo": {"name": "greenscreen-publisher", "version": "0.1.0", "extra": 1}}}


def test_line_sent_rows():
    assert line(sent(call("buildInitialize", 1))) == "sent initialize: protocol 2025-11-25"
    assert line(sent(call("buildInitialized"))) == "sent notifications/initialized"
    assert line(sent(call("buildToolsList", 2))) == "sent tools/list"
    wire = call("buildToolsCall", 3, "tk5-system-info", [USER_INPUT, SECRET_INPUT], True)
    assert line(sent(wire)) == "sent tools/call: tk5-system-info"
    unknown = '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"1999-01-01"}}'
    assert line(sent(unknown)) == "sent initialize: protocol ?"


def test_line_received_initialize_and_list_rows():
    assert line(received("initialize", INIT_REPLY)) == "received initialize: greenscreen-publisher, protocol 2025-11-25"
    anon = {"id": 1, "result": {"protocolVersion": "1999-01-01"}}
    assert line(received("initialize", anon)) == "received initialize: unknown server, protocol ?"

    def listing(n):
        return {"id": 2, "result": {"tools": [{"name": f"t{i}"} for i in range(n)]}}

    assert line(received("tools/list", listing(1))) == "received tools/list: 1 tool, t0"
    assert line(received("tools/list", listing(0))) == "received tools/list: 0 tools"
    assert line(received("tools/list", listing(3))) == "received tools/list: 3 tools, t0, t1, t2"
    assert line(received("tools/list", listing(5))) == "received tools/list: 5 tools, t0, t1, t2, +2 more"


def test_line_received_202_and_nothing_readable():
    assert line(received("notifications/initialized", None, 202, "")) == "received notifications/initialized: HTTP 202, no body"
    assert fmt(received("notifications/initialized", None, 202, ""))["text"] == "(no body)"
    got = fmt(received("tools/list", None, 502, "<html>"))
    assert got["line"] == "received tools/list: nothing readable, HTTP 502"
    assert got["text"] == "(nothing readable)"
    assert line(received("tools/call", None, 200, "")) == "received tools/call: nothing readable, HTTP 200"


def test_line_received_call_rows():
    assert line(received("tools/call", SUCCESS)) == "received result: 2 outputs, 6 audit entries"
    one = {"id": 3, "result": {"structuredContent": {"flow": "f", "outputs": {"a": "1"}, "audit": AUDIT[:1]}}}
    assert line(received("tools/call", one)) == "received result: 1 output, 1 audit entry"
    no_audit = {"id": 3, "result": {"structuredContent": {"flow": "f", "outputs": {}}}}
    assert line(received("tools/call", no_audit)) == "received result: 0 outputs, 0 audit entries"
    assert line(received("tools/call", TOOL_ERROR)) == "received error: unexpected_screen"
    odd = {"id": 3, "result": {"isError": True, "structuredContent": {"error": {"code": "Bad Code!"}}}}
    assert line(received("tools/call", odd)) == "received error: unknown"
    long_code = {"id": 3, "result": {"isError": True, "structuredContent": {"error": {"code": "a" * 41}}}}
    assert line(received("tools/call", long_code)) == "received error: unknown"


def test_line_received_error_objects_never_show_message_or_data():
    rpc = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "HOSTILE-MESSAGE", "data": "HOSTILE-DATA"}}
    got = fmt(received("tools/list", rpc))
    assert got["line"] == "received error: JSON-RPC -32601"
    assert "HOSTILE" not in got["text"] and "HOSTILE" not in got["line"]
    assert json.loads(got["text"].split("\n\nLeft out")[0])["error"] == {"code": -32601, "text": "Method not found"}
    assert got["omitted"] == ["error.message", "error.data"]
    assert line(received("tools/list", rpc, 400)) == "received error: JSON-RPC -32601, HTTP 400"
    assert line(received("tools/list", {"jsonrpc": "2.0", "id": None, "error": {"code": 1.5}}, 406)) == "received error: JSON-RPC ?, HTTP 406"
    body = {"error": {"code": "unauthorized", "message": "m"}}
    assert line(received("initialize", body, 401)) == "received error: unauthorized, HTTP 401"
    assert line(received("initialize", {"error": {"code": "No Good"}}, 500)) == "received error: unknown, HTTP 500"


def test_line_received_unrecognised_rows():
    assert line(received("tools/list", {"jsonrpc": "2.0", "method": "sampling/createMessage", "id": 9})) == (
        "received sampling/createMessage: unrecognised message"
    )
    assert line(received("tools/list", {"jsonrpc": "2.0", "id": 2})) == "received tools/list: unrecognised message"
    assert line(received("tools/list", {"id": 2, "result": {"tools": "x"}})) == "received tools/list: unrecognised message"
    assert line(received("tools/call", {"id": 3, "result": {"structuredContent": {}}})) == "received tools/call: unrecognised message"
    assert line(received("x" * 60, {"id": 2})) == "received " + "x" * 40 + ": unrecognised message"


def test_line_cut_at_100_characters_and_character_rule():
    name = "n" * 40
    tools = {"id": 2, "result": {"tools": [{"name": name}] * 6}}
    got = line(received("tools/list", tools))
    assert len(got) == 100 and got.endswith("...") and LINE.match(got)
    assert got.startswith("received tools/list: 6 tools, " + name)
    hostile = {"id": 1, "result": {"serverInfo": {"name": "a\nb\r\t\u00e9\u4e2d\ud83d\ude00\x00z"}}}
    got = line(received("initialize", hostile))
    assert LINE.match(got) and "\n" not in got and "\r" not in got
    assert got.startswith("received initialize: a?b??")


def test_entry_text_projection_names_what_it_leaves_out():
    got = fmt(received("tools/call", TOOL_ERROR))
    shown = json.loads(got["text"].split("\n\nLeft out")[0])
    assert "content" not in shown["result"]
    assert "summary" not in json.dumps(shown) and "SECRET-TEXT" not in got["text"]
    assert shown["result"]["structuredContent"]["error"]["code"] == "unexpected_screen"
    assert got["omitted"] == ["content", "structuredContent.error.summary"]
    assert got["text"].endswith("Left out by this page: content, structuredContent.error.summary")
    ok = fmt(received("tools/call", SUCCESS))
    assert ok["omitted"] == ["content"]
    clean = fmt(received("tools/call", {"jsonrpc": "2.0", "id": 3, "result": {"structuredContent": {"flow": "f", "outputs": {}}}}))
    assert clean["omitted"] == [] and "Left out" not in clean["text"]


def test_entry_text_projection_of_initialize_list_and_other():
    got = fmt(received("initialize", INIT_REPLY))
    assert json.loads(got["text"].split("\n\nLeft out")[0])["result"]["serverInfo"] == {"name": "greenscreen-publisher", "version": "0.1.0"}
    assert got["omitted"] == ["serverInfo.extra"]
    tools = {"id": 2, "result": {"tools": [{"name": "a", "title": "T", "inputSchema": {}, "_meta": {}}], "nextCursor": "c"}}
    got = fmt(received("tools/list", tools))
    assert got["omitted"] == ["tools[].title", "tools[]._meta", "nextCursor"]
    other = fmt(received("x", {"jsonrpc": "2.0", "id": 9, "method": "m", "params": {"a": 1}}))
    assert json.loads(other["text"].split("\n\nLeft out")[0]) == {"jsonrpc": "2.0", "id": 9, "method": "m"}
    assert other["omitted"] == ["params"]


def test_entry_text_cuts_a_long_error_message_and_limits_names():
    long_message = {"id": 3, "result": {"isError": True, "structuredContent": {"error": {"code": "x", "message": "m" * 400}}}}
    shown = json.loads(fmt(received("tools/call", long_message))["text"])
    assert len(shown["result"]["structuredContent"]["error"]["message"]) == 300
    many = {"id": 3, "result": {"structuredContent": {"flow": "f", "outputs": {}, **{f"x{i}": 1 for i in range(20)}}}}
    names = fmt(received("tools/call", many))["omitted"]
    assert len(names) == 13 and names[-1] == "\u2026"


def test_sent_entry_text_is_pretty_and_masks_secrets():
    wire = call("buildToolsCall", 3, "n", [SECRET_INPUT], True)
    got = fmt(sent(wire))
    assert "hunter2" not in got["text"] and "<SECRET>" in got["text"]
    assert got["omitted"] == [] and json.loads(got["text"]) == json.loads(wire)


def test_no_line_has_a_line_feed():
    for message in (SUCCESS, TOOL_ERROR, INIT_REPLY):
        assert "\n" not in line(received("tools/call", message))


# ---- label, fit, strip ------------------------------------------------------


@pytest.mark.parametrize("value,expected", [(True, "Collapse all"), (False, "Expand all"), ("true", "Expand all"), (1, "Expand all"), (None, "Expand all"), (UNDEFINED, "Expand all")])
def test_toggle_all_label(value, expected):
    assert call("toggleAllLabel", value) == expected


@pytest.mark.parametrize(
    "bottom,limit,expected",
    [(720, 720, True), (721, 720, False), (1, 720, True), (0, 720, False), (-5, 720, False), (10, 0, False), (10, -1, False),
     ({"$": "NaN"}, 720, False), (10, {"$": "NaN"}, False), ({"$": "Infinity"}, 720, False), (10, {"$": "Infinity"}, False),
     ("100", 720, False), (100, "720", False), (None, 720, False), (UNDEFINED, UNDEFINED, False), (0.5, 720.5, True)],
)
def test_fits_in_first_screen(bottom, limit, expected):
    assert call("fitsInFirstScreen", bottom, limit) is expected


def test_summarise_run_worked_example_and_edges():
    assert call("summariseRun", AUDIT) == {"steps": 4, "screens": 2}
    assert call("summariseRun", []) == {"steps": 0, "screens": 0}
    for bad in (None, {}, "x", UNDEFINED):
        assert call("summariseRun", bad) == {"steps": 0, "screens": 0}
    assert call("summariseRun", [1, None, "x", [], {"status": "ok", "signature": ""}]) == {"steps": 1, "screens": 0}
    assert call("summariseRun", [{"status": "weird", "signature": "s"}, {"signature": "s"}]) == {"steps": 2, "screens": 1}


def test_strip_stages():
    assert call("stripStages", "mcp", "tk5-system-info", {"steps": 4, "screens": 2}) == [
        "MCP client (this page)", "MCP tool tk5-system-info", "3270 screens: 4 steps on 2 distinct screens"]
    assert call("stripStages", "rest", "f", {"steps": 1, "screens": 1}) == [
        "REST client (this page)", "POST /flows/f", "3270 screens: 1 step on 1 distinct screen"]
    assert call("stripStages", "mcp", "t", {"steps": 0, "screens": 0})[2] == "3270 screens: 0 steps on 0 distinct screens"
    assert call("stripStages", "mcp", "n" * 100, {"steps": 1, "screens": 1})[1] == "MCP tool " + "n" * 80


@pytest.mark.parametrize("code,text", [(-32700, "Parse error"), (-32600, "Invalid request"), (-32601, "Method not found"),
                                       (-32602, "Invalid params"), (-32603, "Internal error"), (5, "Unknown error code"),
                                       ("-32601", "Unknown error code"), (None, "Unknown error code")])
def test_json_rpc_error_text(code, text):
    assert call("jsonRpcErrorText", code) == text


def test_the_curl_text_still_decodes_after_the_additions():
    # An existing export still works from the extended module.
    out = call("buildCurl", "http://x", "f", [USER_INPUT])
    assert json.loads(shlex.split(out)[-1])["userid"] == "ABC'D\"\\"
