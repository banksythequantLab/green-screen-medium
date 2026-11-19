"""The OpenAI-compatible adapter over ``httpx2.MockTransport`` (spec ask, task 2.11).

No real network: every reply is made by a mock transport, and the autouse ``no_network``
fixture fails a test that tries to leave the machine. Keys are generated per test and
never written anywhere.
"""
from __future__ import annotations

import ast
import asyncio
import json
import logging
import secrets
import time
import traceback
from pathlib import Path

import anyio
import httpx2
import pytest

from greenscreen.publisher.ask import openai_compat
from greenscreen.publisher.ask.adapter import ModelError, ModelTurn, ToolCallRequest
from greenscreen.publisher.ask.openai_compat import MAX_REPLY_BYTES, OpenAIAdapter
from tests.ask_support import no_network  # noqa: F401  (autouse)

BASE = "http://127.0.0.1:11434/v1"
MODEL = "fake-model"
EFFORTS = ("none", "minimal", "low", "medium", "high")
FORBIDDEN_MEMBERS = (
    "tool_choice", "parallel_tool_calls", "temperature", "top_p", "max_tokens",
    "max_completion_tokens", "stream", "n", "user", "think",
)
TOOLS = [
    {
        "name": "tk5-system-info",
        "description": "Reads system information.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "second-tool",
        "description": "Another tool.",
        "parameters": {
            "type": "object",
            "properties": {"userid": {"type": "string"}},
            "additionalProperties": False,
        },
    },
]
FIRST_TURN = [
    {"role": "system", "content": "Be brief."},
    {"role": "user", "content": "What is the release? caf\u00e9"},
]
AFTER_TOOL = FIRST_TURN + [
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "tk5-system-info", "arguments": "{}"},
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "content": '{"ok":true}'},
]


@pytest.fixture
def key() -> str:
    return secrets.token_urlsafe(24)


def reply(message: dict, finish: str | None = "stop", **extra: object) -> httpx2.Response:
    choice: dict = {"index": 0, "message": message}
    if finish is not None:
        choice["finish_reason"] = finish
    return httpx2.Response(200, json={"choices": [choice], **extra})


def answer_reply(text: str = "The release is 38.") -> httpx2.Response:
    return reply({"role": "assistant", "content": text})


def tool_call(call_id: str = "call_1", name: str = "tk5-system-info", arguments: object = "{}") -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}


class Recorder:
    """A mock-transport handler that records requests and answers with ``respond``."""

    def __init__(self, respond) -> None:
        self.respond = respond
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self.respond
        return response(request) if callable(response) else response

    def body(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content)


def complete(handler, *, messages=None, tools=TOOLS, effort=None, api_key=None, timeout=5.0):
    async def go() -> ModelTurn:
        adapter = OpenAIAdapter(
            BASE, MODEL, api_key, reasoning_effort=effort, transport=httpx2.MockTransport(handler)
        )
        async with adapter as opened:
            return await opened.complete(
                FIRST_TURN if messages is None else messages, tools, timeout_seconds=timeout
            )

    return asyncio.run(go())


def failure(handler, **kwargs) -> ModelError:
    with pytest.raises(ModelError) as info:
        complete(handler, **kwargs)
    return info.value


def assert_clean(error: ModelError, *secrets_: str) -> None:
    """A ModelError holds its kind and nothing else, and no secret appears anywhere in it."""
    assert error.args == (error.kind,)
    assert error.__context__ is None and error.__cause__ is None
    text = repr(error) + str(error) + "".join(traceback.format_exception(error))
    for secret in secrets_:
        assert secret not in text


def log_text(caplog: pytest.LogCaptureFixture) -> str:
    parts = []
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(record.args))
        parts.append(record.exc_text or "")
        if record.exc_info:
            parts.append("".join(traceback.format_exception(*record.exc_info)))
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Request: line, headers and body members
# --------------------------------------------------------------------------

def test_first_turn_request_line_headers_and_body(key):
    handler = Recorder(answer_reply())
    complete(handler, api_key=key)
    (request,) = handler.requests
    assert request.method == "POST"
    assert str(request.url) == BASE + "/chat/completions"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["accept"] == "application/json"
    assert request.headers["authorization"] == "Bearer " + key
    raw = request.content
    body = json.loads(raw)
    assert list(body) == ["model", "messages", "tools"]
    assert body["model"] == MODEL
    assert body["messages"] == FIRST_TURN
    assert body["tools"] == [
        {
            "type": "function",
            "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]},
        }
        for t in TOOLS
    ]
    # Compact separators and plain ASCII (a non-ASCII character is escaped).
    assert raw == json.dumps(body, separators=(",", ":")).encode("ascii")
    assert b"\\u00e9" in raw


def test_request_after_a_tool_result_carries_the_whole_conversation(key):
    handler = Recorder(answer_reply())
    complete(handler, messages=AFTER_TOOL, api_key=key)
    body = handler.body()
    assert list(body) == ["model", "messages", "tools"]
    assert body["messages"] == AFTER_TOOL
    assert handler.requests[0].url.path == "/v1/chat/completions"


def test_trailing_slash_of_the_base_url_is_not_doubled():
    handler = Recorder(answer_reply())

    async def go():
        async with OpenAIAdapter(BASE + "/", MODEL, None, transport=httpx2.MockTransport(handler)) as a:
            await a.complete(FIRST_TURN, TOOLS, timeout_seconds=5.0)

    asyncio.run(go())
    assert str(handler.requests[0].url) == BASE + "/chat/completions"


def test_no_key_means_no_authorization_header():
    handler = Recorder(answer_reply())
    complete(handler, api_key=None)
    assert "authorization" not in handler.requests[0].headers
    handler = Recorder(answer_reply())
    complete(handler, api_key="")
    assert "authorization" not in handler.requests[0].headers


@pytest.mark.parametrize("messages", [FIRST_TURN, AFTER_TOOL], ids=["first_turn", "after_tool"])
@pytest.mark.parametrize("tools", [TOOLS, []], ids=["with_tools", "empty_tools"])
@pytest.mark.parametrize("effort", [None, *EFFORTS])
def test_body_members_are_the_fixed_ones(messages, tools, effort):
    handler = Recorder(answer_reply())
    complete(handler, messages=messages, tools=tools, effort=effort)
    body = handler.body()
    expected = ["model", "messages"] + (["tools"] if tools else []) + (["reasoning_effort"] if effort else [])
    assert list(body) == expected
    assert set(body) <= {"model", "messages", "tools", "reasoning_effort"}
    for name in FORBIDDEN_MEMBERS:
        assert name not in body
    raw = handler.requests[0].content
    assert raw.count(b'"tool_choice"') == 0
    if effort is None:
        assert b"reasoning_effort" not in raw
    else:
        assert body["reasoning_effort"] == effort
        assert raw.count(b'"reasoning_effort"') == 1


def test_a_body_without_effort_has_exactly_the_documented_key_tuple():
    """``_BODY_KEYS`` is the documented fixed tuple; the real body must agree with it."""
    handler = Recorder(answer_reply())
    complete(handler)
    assert tuple(handler.body()) == tuple(openai_compat._BODY_KEYS)


# --------------------------------------------------------------------------
# Reply shapes
# --------------------------------------------------------------------------

def test_an_answer():
    turn = complete(Recorder(answer_reply("Release 38.")))
    assert turn == ModelTurn("Release 38.", ())


def test_one_tool_call():
    turn = complete(Recorder(reply({"role": "assistant", "content": None, "tool_calls": [tool_call()]}, "tool_calls")))
    assert turn == ModelTurn(None, (ToolCallRequest("call_1", "tk5-system-info", "{}"),))


def test_several_tool_calls_keep_the_model_order():
    calls = [tool_call("a1", "second-tool", '{"userid":"x"}'), tool_call("b2"), tool_call("c3", "second-tool", "{}")]
    turn = complete(Recorder(reply({"role": "assistant", "content": None, "tool_calls": calls}, "tool_calls")))
    assert [c.id for c in turn.tool_calls] == ["a1", "b2", "c3"]
    assert turn.tool_calls[0].arguments_text == '{"userid":"x"}'
    assert turn.answer is None


def test_finish_reason_stop_with_tool_calls_is_still_a_tool_turn():
    for finish in ("stop", None, "tool_calls", "function_call"):
        turn = complete(Recorder(reply({"role": "assistant", "tool_calls": [tool_call()]}, finish)))
        assert turn.answer is None and len(turn.tool_calls) == 1


def test_content_beside_tool_calls_is_ignored():
    turn = complete(Recorder(reply({"content": "thinking aloud", "tool_calls": [tool_call()]})))
    assert turn.answer is None and len(turn.tool_calls) == 1


@pytest.mark.parametrize("arguments", ["{}", "", '{"a":1}', "not json at all", "[1]"])
def test_arguments_text_is_passed_through_unparsed(arguments):
    turn = complete(Recorder(reply({"tool_calls": [tool_call(arguments=arguments)]})))
    assert turn.tool_calls[0].arguments_text == arguments


def test_type_function_or_absent_is_accepted():
    call = tool_call()
    del call["type"]
    turn = complete(Recorder(reply({"tool_calls": [call]})))
    assert len(turn.tool_calls) == 1


def test_an_empty_tool_calls_list_falls_back_to_content():
    turn = complete(Recorder(reply({"content": "Plain.", "tool_calls": []})))
    assert turn == ModelTurn("Plain.", ())
    turn = complete(Recorder(reply({"content": "Plain.", "tool_calls": None, "refusal": None})))
    assert turn == ModelTurn("Plain.", ())


def test_only_the_first_choice_is_read():
    handler = Recorder(
        httpx2.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "first"}, "finish_reason": "stop"},
                    {"message": {"content": None}, "finish_reason": "content_filter"},
                ]
            },
        )
    )
    assert complete(handler) == ModelTurn("first", ())


def test_reasoning_and_usage_members_are_ignored():
    think = "PRIVATE-" + secrets.token_hex(6)
    message = {
        "role": "assistant",
        "content": "Answer.",
        "reasoning": think,
        "reasoning_content": think,
        "extra": {"deep": [1, 2]},
    }
    handler = Recorder(
        reply(
            message,
            "stop",
            usage={"prompt_tokens": 3, "completion_tokens": 4, "prompt_tokens_details": {"cached_tokens": 1}},
            system_fingerprint="fp",
            unknown_member=[1, {"a": 2}],
        )
    )
    turn = complete(handler)
    assert turn == ModelTurn("Answer.", ())
    assert think not in repr(turn)
    # Also with tool calls and a reasoning member that is not even a string.
    message = {"reasoning": {"steps": [think]}, "tool_calls": [tool_call()]}
    turn = complete(Recorder(reply(message)))
    assert turn == ModelTurn(None, (ToolCallRequest("call_1", "tk5-system-info", "{}"),))
    assert think not in repr(turn)


def test_finish_reason_tool_calls_without_tool_calls_falls_to_the_content_rule():
    for message in ({"content": "Plain."}, {"content": "Plain.", "tool_calls": []}):
        assert complete(Recorder(reply(message, "tool_calls"))) == ModelTurn("Plain.", ())
    for message in ({"content": None}, {"content": "  "}, {}):
        assert failure(Recorder(reply(message, "tool_calls"))).kind == "unusable"


def test_extra_reply_members_are_unread_and_the_next_assistant_message_is_the_agents_own(caplog):
    from greenscreen.publisher.ask.agent import Limits, Progress, run_question
    from tests.ask_support import FLOW, AskFakeClock, FakePort

    think = "PRIVATE-" + secrets.token_hex(6)
    extras = dict(
        usage={"prompt_tokens": 3, "prompt_tokens_details": {"cached_tokens": 1}},
        system_fingerprint="fp",
        unknown_member=[1, {"a": 2}],
    )
    call = tool_call(name=FLOW, arguments="{}")
    first = reply(
        {"role": "assistant", "content": None, "tool_calls": [call], "reasoning": think,
         "reasoning_content": think, "extra": 1},
        "stop",
        **extras,
    )
    replies = iter([first, reply({"role": "assistant", "content": "Done.", "reasoning": think}, "stop", **extras)])
    handler = Recorder(lambda request: next(replies))
    prog = Progress()
    lim = Limits(max_turns=8, max_tool_calls=6, model_timeout=25.0, max_answer=2000, max_result=4000)

    async def go() -> None:
        async with OpenAIAdapter(BASE, MODEL, None, transport=httpx2.MockTransport(handler)) as adapter:
            await run_question(
                "What is the release?", port=FakePort(), adapter=adapter, lim=lim, clock=AskFakeClock(),
                closing=lambda: False, allowed={FLOW}, worst={FLOW: 40.0}, end=1000.0, prog=prog,
            )

    with caplog.at_level(1):
        asyncio.run(go())
    assert prog.answer == "Done."
    assistant = handler.body(1)["messages"][2]
    assert set(assistant) == {"role", "content", "tool_calls"}
    assert think not in handler.requests[1].content.decode()
    assert think not in log_text(caplog) and think not in repr(prog)


def test_a_reasoning_probe_is_in_no_log_record_or_error_text(caplog):
    think = "PRIVATE-" + secrets.token_hex(6)
    with caplog.at_level(1):
        complete(Recorder(reply({"content": "ok", "reasoning": think}, "stop", usage={"x": think})))
        error = failure(Recorder(reply({"content": None, "reasoning": think}, "stop")))
    assert_clean(error, think)
    assert think not in log_text(caplog)


# --------------------------------------------------------------------------
# Status classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (429, "busy"), (503, "busy"),
        (408, "unreachable"), (500, "unreachable"), (501, "unreachable"), (502, "unreachable"),
        (504, "unreachable"), (599, "unreachable"),
        (400, "refused"), (401, "refused"), (403, "refused"), (404, "refused"), (409, "refused"),
        (422, "refused"), (499, "refused"),
        (201, "unusable"), (202, "unusable"), (204, "unusable"), (301, "unusable"), (302, "unusable"),
        (304, "unusable"), (307, "unusable"), (308, "unusable"),
    ],
)
def test_status_table(status, kind, key):
    probe = "ERRBODY-" + secrets.token_hex(6)
    handler = Recorder(httpx2.Response(status, json={"error": {"message": probe}}, headers={"location": BASE + "/x"} if 300 <= status < 400 else {}))
    error = failure(handler, api_key=key)
    assert error.kind == kind
    assert len(handler.requests) == 1  # no retry, no redirect followed
    assert_clean(error, probe, key)


def test_a_redirect_is_not_followed():
    handler = Recorder(httpx2.Response(302, headers={"location": "http://127.0.0.1:9/elsewhere"}))
    assert failure(handler).kind == "unusable"
    assert [r.url.port for r in handler.requests] == [11434]


def test_an_error_reply_body_is_never_read():
    class Boom(httpx2.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("the error body was read")
            yield b""  # pragma: no cover

    handler = Recorder(httpx2.Response(500, stream=Boom()))
    assert failure(handler).kind == "unreachable"


# --------------------------------------------------------------------------
# Unusable, refused and busy 200 replies
# --------------------------------------------------------------------------

def json_reply(payload: object, **headers: str) -> httpx2.Response:
    return httpx2.Response(200, content=json.dumps(payload).encode(), headers={"content-type": "application/json", **headers})


UNUSABLE = {
    "empty_choices": {"choices": []},
    "no_choices": {"id": "x"},
    "choices_not_list": {"choices": {"message": {"content": "a"}}},
    "choice_not_object": {"choices": ["a"]},
    "no_message": {"choices": [{"finish_reason": "stop"}]},
    "message_not_object": {"choices": [{"message": "text"}]},
    "top_level_list": [{"choices": []}],
    "top_level_string": "text",
    "length": {"choices": [{"message": {"content": "cut off"}, "finish_reason": "length"}]},
    "length_with_calls": {"choices": [{"message": {"tool_calls": [tool_call()]}, "finish_reason": "length"}]},
    "arguments_object": {"choices": [{"message": {"tool_calls": [tool_call(arguments={"a": 1})]}}]},
    "arguments_null": {"choices": [{"message": {"tool_calls": [tool_call(arguments=None)]}}]},
    "arguments_missing": {"choices": [{"message": {"tool_calls": [{"id": "c", "function": {"name": "t"}}]}}]},
    "name_missing": {"choices": [{"message": {"tool_calls": [{"id": "c", "function": {"arguments": "{}"}}]}}]},
    "name_not_string": {"choices": [{"message": {"tool_calls": [tool_call(name=7)]}}]},
    "function_missing": {"choices": [{"message": {"tool_calls": [{"id": "c"}]}}]},
    "id_missing": {"choices": [{"message": {"tool_calls": [{"function": {"name": "t", "arguments": "{}"}}]}}]},
    "id_empty": {"choices": [{"message": {"tool_calls": [tool_call(call_id="")]}}]},
    "id_too_long": {"choices": [{"message": {"tool_calls": [tool_call(call_id="i" * 201)]}}]},
    "id_not_string": {"choices": [{"message": {"tool_calls": [tool_call(call_id=5)]}}]},
    "duplicate_ids": {"choices": [{"message": {"tool_calls": [tool_call("dup"), tool_call("dup", "second-tool")]}}]},
    "type_custom": {"choices": [{"message": {"tool_calls": [{**tool_call(), "type": "custom"}]}}]},
    "one_bad_call_among_good": {"choices": [{"message": {"tool_calls": [tool_call("a"), {"id": "b"}]}}]},
    "tool_calls_not_list": {"choices": [{"message": {"tool_calls": "x"}}]},
    "tool_call_not_object": {"choices": [{"message": {"tool_calls": ["x"]}}]},
    "content_null": {"choices": [{"message": {"content": None}}]},
    "content_blank": {"choices": [{"message": {"content": " \n\t"}}]},
    "content_empty": {"choices": [{"message": {"content": ""}}]},
    "content_not_string": {"choices": [{"message": {"content": ["a"]}}]},
    "content_missing": {"choices": [{"message": {"role": "assistant"}}]},
}


@pytest.mark.parametrize("name", sorted(UNUSABLE))
def test_unusable_shapes(name):
    assert failure(Recorder(json_reply(UNUSABLE[name]))).kind == "unusable"


def test_non_json_bodies_are_unusable():
    for content in (b"not json", b"", b"{", b"\xff\xfe", b"[" * 100_000):
        handler = Recorder(httpx2.Response(200, content=content, headers={"content-type": "application/json"}))
        assert failure(handler).kind == "unusable"


def test_the_wrong_media_type_is_unusable():
    body = json.dumps({"choices": [{"message": {"content": "hi"}}]}).encode()
    for headers in ({"content-type": "text/html"}, {"content-type": "text/plain"}, {}):
        assert failure(Recorder(httpx2.Response(200, content=body, headers=headers))).kind == "unusable"
    ok = httpx2.Response(200, content=body, headers={"content-type": "Application/JSON; charset=utf-8"})
    assert complete(Recorder(ok)) == ModelTurn("hi", ())


def test_a_2_mib_body_is_unusable():
    big = httpx2.Response(200, content=b" " * (2 * 1024 * 1024), headers={"content-type": "application/json"})
    assert failure(Recorder(big)).kind == "unusable"


def test_the_reply_cap_is_one_mebibyte_inclusive():
    head = json.dumps({"choices": [{"message": {"content": "edge"}}]}).encode()
    headers = {"content-type": "application/json"}
    at_cap = head + b" " * (MAX_REPLY_BYTES - len(head))
    assert len(at_cap) == MAX_REPLY_BYTES == 1_048_576
    assert complete(Recorder(httpx2.Response(200, content=at_cap, headers=headers))) == ModelTurn("edge", ())
    over = at_cap + b" "
    assert failure(Recorder(httpx2.Response(200, content=over, headers=headers))).kind == "unusable"


def test_content_filter_is_refused():
    for message in ({"content": None}, {"content": "partial"}, {"tool_calls": [tool_call()]}):
        reply_ = reply(message, "content_filter")
        assert failure(Recorder(reply_)).kind == "refused"


def test_a_non_empty_refusal_is_refused():
    text = "REFUSAL-" + secrets.token_hex(6)
    error = failure(Recorder(reply({"content": None, "refusal": text})))
    assert error.kind == "refused"
    assert_clean(error, text)
    # Refusal wins over content and over tool calls.
    assert failure(Recorder(reply({"content": "a", "refusal": "no"}))).kind == "refused"
    assert failure(Recorder(reply({"tool_calls": [tool_call()], "refusal": "no"}))).kind == "refused"


def test_an_empty_or_null_refusal_is_not_a_refusal():
    assert complete(Recorder(reply({"content": "ok", "refusal": ""}))) == ModelTurn("ok", ())
    assert complete(Recorder(reply({"content": "ok", "refusal": None}))) == ModelTurn("ok", ())


# --------------------------------------------------------------------------
# Transport failures and the total deadline
# --------------------------------------------------------------------------

def test_transport_exceptions_become_unreachable(key):
    for exc in (
        lambda r: httpx2.ConnectError("boom", request=r),
        lambda r: httpx2.ReadTimeout("slow", request=r),
        lambda r: httpx2.TooManyRedirects("loop", request=r),
        lambda r: httpx2.RemoteProtocolError("bad", request=r),
        lambda r: OSError("os level"),
        lambda r: TimeoutError("late"),
    ):
        def handler(request, exc=exc):
            raise exc(request)

        error = failure(handler, api_key=key)
        assert error.kind == "unreachable"
        assert_clean(error, key)


def test_a_stalled_transport_hits_the_total_deadline():
    async def stall(request: httpx2.Request) -> httpx2.Response:
        await anyio.sleep(30)
        return answer_reply()

    started = time.monotonic()
    error = failure(stall, timeout=0.05)
    assert error.kind == "unreachable"
    assert time.monotonic() - started < 5.0
    assert_clean(error)


def test_a_reply_body_that_stalls_hits_the_total_deadline():
    class Slow(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"choices":'
            await anyio.sleep(30)
            yield b"[]}"

    handler = Recorder(httpx2.Response(200, headers={"content-type": "application/json"}, stream=Slow()))
    started = time.monotonic()
    assert failure(handler, timeout=0.05).kind == "unreachable"
    assert time.monotonic() - started < 5.0


def test_a_fast_reply_under_a_small_timeout_still_works():
    assert complete(Recorder(answer_reply()), timeout=2.0).answer


# --------------------------------------------------------------------------
# Effort on error statuses, secrecy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [400, 422, 401])
@pytest.mark.parametrize("messages", [FIRST_TURN, AFTER_TOOL], ids=["first_turn", "after_tool"])
def test_a_rejection_with_effort_set_is_refused_with_no_second_request(status, messages, key, caplog):
    effort = "medium"
    handler = Recorder(httpx2.Response(status, json={"error": {"message": f"unknown {effort} member"}}))
    with caplog.at_level(1):
        error = failure(handler, messages=messages, effort=effort, api_key=key)
    assert error.kind == "refused"
    assert len(handler.requests) == 1
    assert handler.body()["reasoning_effort"] == effort
    assert_clean(error, key, "reasoning_effort", effort)
    text = log_text(caplog)
    assert key not in text and "reasoning_effort" not in text


def test_the_key_is_in_no_repr_exception_or_log_record(key, caplog):
    adapter = OpenAIAdapter(BASE, MODEL, key, reasoning_effort="low")
    assert key not in repr(adapter) and key not in str(adapter)
    assert "low" not in repr(adapter)
    cases = [
        httpx2.Response(401), httpx2.Response(500), httpx2.Response(429),
        httpx2.Response(200, content=b"nope", headers={"content-type": "application/json"}),
        answer_reply(),
    ]
    with caplog.at_level(1):
        for response in cases:
            try:
                complete(Recorder(response), api_key=key)
            except ModelError as error:
                assert_clean(error, key)

        def boom(request):
            raise httpx2.ConnectError("x", request=request)

        assert_clean(failure(boom, api_key=key), key)
    assert key not in log_text(caplog)
    assert key not in "".join(f"{r.name}{r.pathname}{r.msg!r}" for r in caplog.records)


def test_the_key_is_per_request_not_a_client_default(key):
    seen: list[httpx2.Request] = []

    async def go():
        async with OpenAIAdapter(BASE, MODEL, key, transport=httpx2.MockTransport(lambda r: (seen.append(r), answer_reply())[1])) as a:
            assert a._client is not None
            assert "authorization" not in {k.lower() for k in a._client.headers}
            await a.complete(FIRST_TURN, TOOLS, timeout_seconds=5.0)

    asyncio.run(go())
    assert seen[0].headers["authorization"] == "Bearer " + key


def test_complete_outside_the_context_is_a_programming_error():
    adapter = OpenAIAdapter(BASE, MODEL, None)
    with pytest.raises(RuntimeError):
        asyncio.run(adapter.complete(FIRST_TURN, TOOLS, timeout_seconds=1.0))


def test_model_error_has_empty_context_after_a_transport_failure(key):
    def boom(request):
        raise httpx2.ConnectError("x", request=request)

    error = failure(boom, api_key=key)
    assert error.__context__ is None and error.__cause__ is None
    assert error.__suppress_context__ is False  # nothing was chained, nothing needs hiding


# --------------------------------------------------------------------------
# The guard test: the no_network fixture blocked a real connection
# --------------------------------------------------------------------------

def test_a_real_connection_is_blocked_and_becomes_unreachable(no_network, key):
    """Reserved name, no transport: the fixture records the attempt and the failure is ``unreachable``."""
    no_network.expect_attempts()

    async def go():
        async with OpenAIAdapter("https://llm.invalid/v1", MODEL, key) as adapter:
            return await adapter.complete(FIRST_TURN, TOOLS, timeout_seconds=5.0)

    with pytest.raises(ModelError) as info:
        asyncio.run(go())
    assert info.value.kind == "unreachable"
    assert_clean(info.value, key)
    assert any("llm.invalid" in attempt for attempt in no_network.attempts)


# --------------------------------------------------------------------------
# Static pins on openai_compat.py
# --------------------------------------------------------------------------

SOURCE_PATH = Path(openai_compat.__file__)
TREE = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))


def _body_function() -> ast.FunctionDef:
    (found,) = [n for n in ast.walk(TREE) if isinstance(n, ast.FunctionDef) and n.name == "_body"]
    return found


def test_body_takes_exactly_four_parameters_and_adds_no_other_key():
    func = _body_function()
    assert [a.arg for a in func.args.args] == ["model", "messages", "tools", "effort"]
    assert not (func.args.vararg or func.args.kwarg or func.args.kwonlyargs)
    keys: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            assert all(isinstance(k, ast.Constant) for k in node.keys), "a computed dict key in _body"
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.ctx, ast.Store):
            keys.add(node.slice.value)
        assert not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"update", "setdefault"})
    assert keys == {"model", "messages", "tools", "reasoning_effort"} | {"type", "function", "name", "description", "parameters"}
    # The optional member is guarded by the effort parameter, and that is the only guard of a body key.
    source = ast.get_source_segment(SOURCE_PATH.read_text(encoding="utf-8"), func)
    assert source.count('body["reasoning_effort"]') == 1
    assert "effort is not None" in source


def test_no_forbidden_parameter_name_appears_as_a_key_or_keyword_anywhere():
    for node in ast.walk(TREE):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in FORBIDDEN_MEMBERS
        if isinstance(node, ast.keyword):
            assert node.arg not in FORBIDDEN_MEMBERS
        if isinstance(node, ast.arg):
            assert node.arg not in FORBIDDEN_MEMBERS


def test_documented_key_tuple_is_the_fixed_members():
    assert openai_compat._BODY_KEYS == ("model", "messages", "tools")


def test_source_has_no_logging_and_no_print():
    names = {n.id for n in ast.walk(TREE) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(TREE) if isinstance(n, ast.Import) for a in n.names}
    assert "logging" not in imported and "print" not in names
    assert logging.getLogger("greenscreen.publisher.ask.openai_compat").handlers == []
