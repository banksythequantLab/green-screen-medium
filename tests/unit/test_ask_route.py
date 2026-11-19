"""``POST /ask``: body rules, answers, errors, the gate, the budget, the record, auth.

Spec ask, task 2.13; Requirements 1.13, 2.1 to 2.10, 6.1, 6.8 to 6.10, 9.1 to 9.4, 10.1,
10.2, 11.3. The model is a ``FakeAdapter`` and the host a Fake_Host; nothing leaves the
machine. Keys are generated per test and never written anywhere.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone

import pytest
from jsonschema import Draft202012Validator

from greenscreen.publisher.ask.adapter import ModelTurn
from greenscreen.publisher.ask.codes import ASK_MESSAGES
from greenscreen.publisher.ask.service import ask_openapi
from greenscreen.publisher.calls import MESSAGES
from tests.ask_support import (
    FLOW,
    AskFakeClock,
    Fail,
    FakeAdapter,
    Turn,
    ask_post,
    build_ask_app,
    no_network,  # noqa: F401  (autouse)
)
from tests.console_support import call_scope
from tests.publisher_support import LogCapture

QUESTION = "What system is this, and which release?"
SCHEMAS = ask_openapi(500, 2000)[1]
TRACE = Draft202012Validator({"$ref": "#/components/schemas/AskTrace", "components": {"schemas": SCHEMAS}})
ERROR_BODY = Draft202012Validator({"$ref": "#/components/schemas/AskErrorBody", "components": {"schemas": SCHEMAS}})
RESPONSE = Draft202012Validator({"$ref": "#/components/schemas/AskResponse", "components": {"schemas": SCHEMAS}})
USERID = '{"userid": "abc"}'


def answer_adapter(text: str = "It is TK5.", clock=None) -> FakeAdapter:
    return FakeAdapter([Turn(answer=text)], clock=clock)


def one(app, question=QUESTION, **kw):
    """One question, no lifespan (the in-process client needs none, and the lifespan of an
    app can be entered only once); tests that need the shutdown drain open it themselves."""
    return asyncio.run(ask_post(app, question, **kw))


def error_of(reply, code: str, status: int, *, trace: bool):
    body = reply.json()
    assert reply.status == status, reply.raw[:300]
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == code
    assert error["message"] == (ASK_MESSAGES.get(code) or MESSAGES[code])
    assert set(error) == ({"code", "message", "trace"} if trace else {"code", "message"})
    ERROR_BODY.validate(body)
    return error


# --------------------------------------------------------------------------
# Body rules and the question
# --------------------------------------------------------------------------

def test_a_wrong_or_missing_media_type_is_request_invalid():
    app = build_ask_app(adapter=answer_adapter())
    for content_type in ("text/plain", "application/jsonx", "multipart/form-data", None):
        reply = one(app, content_type=content_type)
        error_of(reply, "request_invalid", 400, trace=False)
    assert app.adapter.calls == 0


def test_the_media_type_may_carry_parameters_and_any_case():
    app = build_ask_app(adapter=answer_adapter())
    assert one(app, content_type="Application/JSON; charset=utf-8").status == 200


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'"question"',
        b"null",
        b'{"question": "a", "question": "b"}',
        b'{"question": NaN}',
        b'{"question": "' + b"\xff" + b'"}',
    ],
)
def test_a_body_that_is_not_a_json_object_is_request_invalid(body):
    app = build_ask_app(adapter=answer_adapter())
    error_of(one(app, body=body), "request_invalid", 400, trace=False)
    assert app.adapter.calls == 0


def test_a_body_over_the_limit_is_request_too_large():
    app = build_ask_app({"GS_MAX_BODY_BYTES": "1024"}, adapter=answer_adapter())
    body = json.dumps({"question": "q" * 2000}).encode()
    error_of(one(app, body=body), "request_too_large", 413, trace=False)
    # a lying Content-Length is refused before the body is read
    error_of(one(app, body=b"{}", headers={"Content-Length": "999999"}), "request_too_large", 413, trace=False)
    assert app.adapter.calls == 0


def test_a_bad_content_length_is_request_invalid():
    app = build_ask_app(adapter=answer_adapter())
    error_of(one(app, body=b"{}", headers={"Content-Length": "-1"}), "request_invalid", 400, trace=False)


def raw_json(payload) -> bytes:
    return json.dumps(payload).encode("utf-8")


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"question": QUESTION, "extra": 1},
        {"Question": QUESTION},
        {"question": 5},
        {"question": None},
        {"question": ["a"]},
        {"question": ""},
        {"question": "   \t\n  "},
        {"question": "q" * 501},
        {"question": "bad\x00char"},
        {"question": "bell\x07"},
        {"question": "esc\x1b[0m"},
        {"question": "tab\there\rcr"},  # carriage return is a control character
        {"question": "nel\x85"},
        {"question": "\x7fdel"},
    ],
)
def test_question_invalid_cases(payload):
    app = build_ask_app(adapter=answer_adapter())
    reply = one(app, body=raw_json(payload))
    error_of(reply, "question_invalid", 422, trace=False)
    for value in payload.values():
        if isinstance(value, str) and len(value) > 3:
            assert value not in reply.raw.decode("utf-8")  # no part of the question comes back
    assert app.adapter.calls == 0


def test_the_question_is_trimmed_and_counted_in_code_points():
    adapter = answer_adapter()
    app = build_ask_app(adapter=adapter)
    # 500 code points outside the BMP (2 UTF-16 units each) fit; spaces around do not count
    emoji = "\U0001f600" * 500
    reply = one(app, "  " + emoji + "\n\t ")
    assert reply.status == 200, reply.raw[:200]
    sent = json.loads(adapter.received[0])["messages"][1]
    assert sent == {"content": emoji, "role": "user"}
    error_of(one(app, "\U0001f600" * 501), "question_invalid", 422, trace=False)
    # line feed and tab inside the text are allowed
    ok = build_ask_app(adapter=answer_adapter())
    assert one(ok, "line one\n\tline two").status == 200


def test_the_limit_follows_the_setting():
    app = build_ask_app({"GS_ASK_MAX_QUESTION_CHARS": "10"}, adapter=answer_adapter())
    assert one(app, "x" * 10).status == 200
    error_of(one(app, "x" * 11), "question_invalid", 422, trace=False)


# --------------------------------------------------------------------------
# Answers and errors
# --------------------------------------------------------------------------

def test_success_shape_and_headers():
    app = build_ask_app(adapter=answer_adapter("It is TK5."))
    reply = one(app)
    body = reply.json()
    assert reply.status == 200
    assert set(body) == {"answer", "truncated", "trace"}
    assert body["answer"] == "It is TK5." and body["truncated"] is False
    RESPONSE.validate(body)
    TRACE.validate(body["trace"])
    assert reply.headers["cache-control"] == "no-store"
    assert "retry-after" not in reply.headers
    assert reply.headers["content-type"].startswith("application/json")
    assert [s["type"] for s in body["trace"]["steps"]] == ["tools", "model"]
    assert body["trace"]["steps"][0] == {"type": "tools", "offered": [FLOW]}


def test_an_answer_over_the_limit_is_cut_and_marked():
    app = build_ask_app({"GS_ASK_MAX_ANSWER_CHARS": "100"}, adapter=answer_adapter("w" * 150))
    body = one(app).json()
    assert len(body["answer"]) == 100 and body["truncated"] is True


def test_a_question_with_a_tool_call_carries_the_tool_step():
    adapter = FakeAdapter([Turn(calls=((FLOW, USERID),)), Turn(answer="Release V2.2.000.")])
    app = build_ask_app(adapter=adapter)
    reply = one(app)
    body = reply.json()
    assert reply.status == 200
    tool = next(s for s in body["trace"]["steps"] if s["type"] == "tool")
    assert tool["tool"] == FLOW and tool["arguments"] == {"userid": "abc"}
    assert tool["ok"] is True and tool["code"] == "ok" and tool["id"] == 1
    assert tool["result"]["outputs"]["RELEASE"] == "V2.2.000"
    assert body["trace"]["tool_calls"] == 1 and body["trace"]["model_turns"] == 2
    TRACE.validate(body["trace"])
    assert "summary" not in reply.raw.decode("utf-8")
    assert app.host.created == 1 and app.host.closed == 1


def test_a_failure_after_the_agent_started_carries_the_trace():
    app = build_ask_app(adapter=FakeAdapter([Fail("unreachable")]))
    reply = one(app)
    error = error_of(reply, "model_unreachable", 502, trace=True)
    TRACE.validate(error["trace"])
    assert [s["type"] for s in error["trace"]["steps"]] == ["tools"]
    assert reply.headers["cache-control"] == "no-store" and "retry-after" not in reply.headers
    for kind, code, status in (("refused", "model_refused", 502), ("unusable", "model_unusable", 502),
                               ("busy", "model_busy", 503)):
        again = build_ask_app(adapter=FakeAdapter([Fail(kind)]))
        error_of(one(again), code, status, trace=True)


def test_a_flow_stop_is_not_a_failed_question():
    """A tool error goes back to the model; the question ends with 200 and the error in the trace."""
    adapter = FakeAdapter([Turn(calls=((FLOW, '{"userid": "abc"}'),)), Turn(answer="The call failed.")])
    app = build_ask_app(adapter=adapter, host=_stopping_host())
    reply = one(app)
    body = reply.json()
    assert reply.status == 200 and body["answer"] == "The call failed."
    tool = next(s for s in body["trace"]["steps"] if s["type"] == "tool")
    assert tool["ok"] is False and tool["code"] != "ok" and "reason" not in tool
    TRACE.validate(body["trace"])
    assert isinstance(tool["result"]["error"]["expected"], list)


def _stopping_host():
    from tests.publisher_support import FakeHost, ScriptedState, capture

    return FakeHost([ScriptedState(capture("tso-ready"))])  # a screen the Flow does not expect first


def test_an_unexpected_exception_is_internal_error_with_the_partial_trace():
    class Broken:
        async def complete(self, messages, tools, *, timeout_seconds):
            raise ZeroDivisionError("boom " + "secret-marker")

    app = build_ask_app(adapter=Broken())
    reply = one(app)
    error = error_of(reply, "internal_error", 500, trace=True)
    assert "secret-marker" not in reply.raw.decode("utf-8")
    assert [s["type"] for s in error["trace"]["steps"]] == ["tools"]
    assert one(build_ask_app(adapter=answer_adapter())).status == 200  # a new app; and the gate below


def test_the_gate_is_released_after_an_exception():
    calls = {"n": 0}

    class Flaky:
        async def complete(self, messages, tools, *, timeout_seconds):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("first")
            return ModelTurn("fine", ())

    app = build_ask_app(adapter=Flaky())

    async def go():
        async with app.app.lifespan():
            return [await ask_post(app, QUESTION), await ask_post(app, QUESTION)]

    first, second = asyncio.run(go())
    assert first.status == 500 and second.status == 200


# --------------------------------------------------------------------------
# The Ask_Gate
# --------------------------------------------------------------------------

class BlockingAdapter:
    """Answers once ``release`` is set; ``started`` is set when a turn begins."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def complete(self, messages, tools, *, timeout_seconds):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ModelTurn("done", ())


def test_a_second_question_gets_busy_at_once_and_the_gate_is_released_after():
    async def go():
        adapter = BlockingAdapter()
        app = build_ask_app(adapter=adapter)
        async with app.app.lifespan():
            first = asyncio.create_task(ask_post(app, QUESTION))
            await asyncio.wait_for(adapter.started.wait(), 5)
            second = await ask_post(app, "second")
            adapter.release.set()
            done = await first
            third = await ask_post(app, "third")
        return second, done, third, adapter

    second, done, third, adapter = asyncio.run(go())
    error_of(second, "busy", 429, trace=False)
    assert second.headers["retry-after"] == "1" and second.headers["cache-control"] == "no-store"
    assert done.status == 200 and third.status == 200
    assert adapter.calls == 2  # the busy question never reached the model


# --------------------------------------------------------------------------
# The Daily_Budget
# --------------------------------------------------------------------------

def utc(day: int, hour: int, minute: int, second: int, micro: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, second, micro, tzinfo=timezone.utc)


def budget_app(limit: int, now: datetime, script=None):
    clock = AskFakeClock(utc=now)
    adapter = FakeAdapter(script if script is not None else [Turn(answer="ok")] * 20, clock=clock)
    return build_ask_app({"GS_ASK_DAILY_LIMIT": str(limit)}, adapter=adapter, clock=clock), clock


def questions(app, *texts, mid=None):
    async def go():
        out = []
        async with app.app.lifespan():
            for text in texts:
                out.append(await ask_post(app, text))
                if mid is not None:
                    mid()
        return out

    return asyncio.run(go())


def test_the_daily_limit_answers_429_with_the_seconds_to_midnight_and_resets():
    app, clock = budget_app(2, utc(20, 23, 59, 30))

    async def go():
        async with app.app.lifespan():
            replies = [await ask_post(app, "one"), await ask_post(app, "two"), await ask_post(app, "three")]
            clock.utc = utc(21, 0, 0, 1)  # after midnight UTC
            replies.append(await ask_post(app, "four"))
            return replies

    one_, two, three, four = asyncio.run(go())
    assert one_.status == two.status == 200
    error_of(three, "daily_limit", 429, trace=False)
    assert three.headers["retry-after"] == "30" and three.headers["cache-control"] == "no-store"
    assert four.status == 200


@pytest.mark.parametrize(
    "now, seconds",
    [
        (utc(20, 0, 0, 0), "86400"),  # the largest value
        (utc(20, 23, 59, 59, 999999), "1"),  # a fraction rounds up, never to 0
        (utc(20, 23, 59, 59), "1"),
        (utc(20, 12, 0, 0), "43200"),
        (utc(20, 12, 0, 0, 1), "43200"),  # 43199.999999 s rounds up
    ],
)
def test_retry_after_is_whole_seconds_from_1_to_86400(now, seconds):
    app, _ = budget_app(1, now)
    first, second = questions(app, "one", "two")
    assert first.status == 200
    assert second.status == 429 and second.headers["retry-after"] == seconds
    assert 1 <= int(second.headers["retry-after"]) <= 86400


def test_the_budget_is_not_written_anywhere_and_is_counted_per_process(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app, _ = budget_app(1, utc(20, 12, 0, 0))
    questions(app, "one", "two")
    assert list(tmp_path.iterdir()) == []
    fresh, _ = budget_app(1, utc(20, 12, 0, 0))  # a new process: a full budget
    assert questions(fresh, "one")[0].status == 200


def test_rejections_before_acceptance_consume_no_budget():
    app, _ = budget_app(1, utc(20, 12, 0, 0))

    async def go():
        async with app.app.lifespan():
            rejected = [
                await ask_post(app, QUESTION, content_type="text/plain"),  # request_invalid
                await ask_post(app, QUESTION, body=b"[]"),  # request_invalid
                await ask_post(app, QUESTION, body=b"x" * 70000),  # request_too_large
                await ask_post(app, ""),  # question_invalid
                await ask_post(app, 5),  # question_invalid
                await ask_post(app, QUESTION, key="wrong-" + app.api_key),  # unauthorized
            ]
            accepted = await ask_post(app, "the one")
            over = await ask_post(app, "too many")
            return rejected, accepted, over

    rejected, accepted, over = asyncio.run(go())
    assert [r.status for r in rejected] == [400, 400, 413, 422, 422, 401]
    assert accepted.status == 200
    assert over.status == 429


def test_shutting_down_consumes_no_budget():
    app, _ = budget_app(1, utc(20, 12, 0, 0))

    async def go():
        async with app.app.lifespan():
            app.app.service.begin_shutdown()
            closing = await ask_post(app, QUESTION)
            app.app.service.closing = False  # the same process, only to look at the budget
            after = await ask_post(app, QUESTION)
            return closing, after

    closing, after = asyncio.run(go())
    error_of(closing, "shutting_down", 503, trace=False)
    assert after.status == 200


def test_busy_at_the_gate_consumes_no_budget():
    async def go():
        adapter = BlockingAdapter()
        clock = AskFakeClock(utc=utc(20, 12, 0, 0))
        app = build_ask_app({"GS_ASK_DAILY_LIMIT": "2"}, adapter=adapter, clock=clock)
        async with app.app.lifespan():
            first = asyncio.create_task(ask_post(app, "first"))
            await asyncio.wait_for(adapter.started.wait(), 5)
            busy = await ask_post(app, "busy")
            adapter.release.set()
            await first
            second = await ask_post(app, "second")  # the second question of the two allowed
            third = await ask_post(app, "third")
        return busy, second, third

    busy, second, third = asyncio.run(go())
    assert busy.status == 429 and busy.json()["error"]["code"] == "busy"
    assert second.status == 200
    assert third.status == 429 and third.json()["error"]["code"] == "daily_limit"


def test_a_failed_question_still_counts():
    app, _ = budget_app(1, utc(20, 12, 0, 0), script=[Fail("refused"), Turn(answer="x")])
    first, second = questions(app, "one", "two")
    assert first.status == 502 and second.json()["error"]["code"] == "daily_limit"


# --------------------------------------------------------------------------
# The Ask_Record
# --------------------------------------------------------------------------

FIELD_TYPES = {
    "ask_id": str, "outcome": str, "model_turns": int, "tool_calls": int,
    "duration_ms": int, "model_ms": int, "truncated": bool,
}


def ask_records(logs: LogCapture):
    logs.refresh()
    return [r for r in logs.records if r.message == "ask finished"]


def check_record(record, outcome: str, **counts):
    fields = record.fields
    assert record.logger == "greenscreen.publisher" and record.level == 20
    assert set(fields) <= set(FIELD_TYPES) and {"ask_id", "outcome"} <= set(fields)
    assert re.fullmatch(r"[0-9a-f]{16}", fields["ask_id"])
    assert fields["outcome"] == outcome
    for name, value in fields.items():
        assert type(value) is FIELD_TYPES[name], name
        if isinstance(value, int) and not isinstance(value, bool):
            assert value >= 0
    for name, value in counts.items():
        assert fields[name] == value, name


def test_one_ask_record_per_question_with_the_permitted_fields_only():
    adapter = FakeAdapter(
        [Turn(calls=((FLOW, USERID),)), Turn(answer="a" * 150), Turn(answer="b" * 10), Fail("unreachable")]
    )
    app = build_ask_app({"GS_ASK_MAX_ANSWER_CHARS": "100", "GS_ASK_DAILY_LIMIT": "3"}, adapter=adapter)

    async def go():
        async with app.app.lifespan():
            out = []
            out.append(await ask_post(app, "question one"))  # tool call, answer cut: ok + truncated
            out.append(await ask_post(app, "question two", content_type="text/plain"))
            out.append(await ask_post(app, ""))
            out.append(await ask_post(app, "question four"))  # ok
            out.append(await ask_post(app, "question five"))  # model_unreachable
            out.append(await ask_post(app, "question six"))  # daily_limit
            return out

    with LogCapture() as logs:
        replies = asyncio.run(go())
        records = ask_records(logs)
    assert [r.status for r in replies] == [200, 400, 422, 200, 502, 429]
    outcomes = [r.fields["outcome"] for r in records]
    assert outcomes == ["ok", "request_invalid", "question_invalid", "ok", "model_unreachable", "daily_limit"]
    check_record(records[0], "ok", model_turns=2, tool_calls=1, truncated=True)
    check_record(records[1], "request_invalid", model_turns=0, tool_calls=0, model_ms=0)
    check_record(records[2], "question_invalid", model_turns=0, tool_calls=0)
    check_record(records[3], "ok", model_turns=1, tool_calls=0)
    assert "truncated" not in records[3].fields  # present only when true
    check_record(records[4], "model_unreachable", model_turns=1)
    check_record(records[5], "daily_limit", model_turns=0, tool_calls=0)
    assert len({r.fields["ask_id"] for r in records}) == 6


def test_the_busy_and_shutting_down_questions_write_a_record():
    async def go():
        adapter = BlockingAdapter()
        app = build_ask_app(adapter=adapter)
        async with app.app.lifespan():
            first = asyncio.create_task(ask_post(app, "first"))
            await asyncio.wait_for(adapter.started.wait(), 5)
            await ask_post(app, "busy")
            adapter.release.set()
            await first
            app.app.service.begin_shutdown()
            await ask_post(app, "closing")

    with LogCapture() as logs:
        asyncio.run(go())
        outcomes = [r.fields["outcome"] for r in ask_records(logs)]
    assert outcomes == ["busy", "ok", "shutting_down"]  # the busy one ends first


def test_no_ask_record_for_an_auth_rejection_or_another_path():
    app = build_ask_app(adapter=answer_adapter())

    async def go():
        async with app.app.lifespan():
            await ask_post(app, QUESTION, key="")  # no key
            await ask_post(app, QUESTION, key="wrong-" + app.api_key)
            await ask_post(app, QUESTION, headers={"Authorization": "Bearer wrong"}, key="")
            await call_scope(app.app.asgi, "GET", "/health", {})

    with LogCapture() as logs:
        asyncio.run(go())
        assert ask_records(logs) == []


def test_the_ask_record_and_the_call_record_hold_no_question_or_answer():
    question = "A very particular question about zebra-quokka-17"
    answer = "An equally particular answer: walrus-lemur-42"
    adapter = FakeAdapter([Turn(calls=((FLOW, USERID),)), Turn(answer=answer)])
    app = build_ask_app(adapter=adapter)
    with LogCapture() as logs:
        reply = one(app, question)
        logs.refresh()
        texts = "\n".join(logs.texts())
    assert reply.status == 200
    for needle in (question, answer, "zebra-quokka", "walrus-lemur", USERID, "fake-model", "127.0.0.1", app.api_key):
        assert needle not in texts, needle
    calls = logs.call_records()
    assert len(calls) == 1 and calls[0].fields["transport"] == "ask"


# --------------------------------------------------------------------------
# Auth: no exempt pair, and Ask off
# --------------------------------------------------------------------------

def test_post_ask_without_a_key_is_401_before_the_body_is_read():
    app = build_ask_app(adapter=answer_adapter())

    async def go():
        async with app.app.lifespan():
            bare = await ask_post(app, QUESTION, key="")
            wrong = await ask_post(app, QUESTION, key="wrong-" + app.api_key)
            huge = await ask_post(app, QUESTION, key="", body=b"x" * 2_000_000, headers={"Content-Length": "2000000"})
            bearer = await ask_post(app, QUESTION, key="", headers={"Authorization": "Bearer " + app.api_key})
            return bare, wrong, huge, bearer

    bare, wrong, huge, bearer = asyncio.run(go())
    for reply in (bare, wrong, huge):
        assert reply.status == 401 and reply.json()["error"]["code"] == "unauthorized"
        assert set(reply.json()["error"]) == {"code", "message"}
    assert bare.raw == wrong.raw == huge.raw  # one fixed body
    assert bearer.status == 200  # the second security alternative
    assert app.adapter.calls == 1


def test_no_exempt_pair_names_ask():
    from greenscreen.publisher.console import PAIRS

    assert not [pair for pair in PAIRS if "/ask" in pair[1]]


def test_with_ask_off_post_ask_is_an_unknown_path():
    app = build_ask_app({"GS_ENABLE_ASK": "false"})
    assert app.app.ask is None

    async def go():
        async with app.app.lifespan():
            without = await ask_post(app, QUESTION, key="")
            wrong = await ask_post(app, QUESTION, key="wrong-" + app.api_key)
            valid = await ask_post(app, QUESTION)
            other = await call_scope(app.app.asgi, "GET", "/ask", {"X-API-Key": app.api_key})
            return without, wrong, valid, other

    without, wrong, valid, other = asyncio.run(go())
    assert without.status == wrong.status == 401
    assert without.json()["error"]["code"] == "unauthorized"
    assert valid.status == 400 and valid.json()["error"]["code"] == "request_invalid"
    assert other[0] in (400, 405) and json.loads(other[2])["error"]["code"] == "request_invalid"
    assert app.adapter.calls == 0
