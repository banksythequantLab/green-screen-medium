# Feature: ask, Property 4: No question, answer, model text or tool data in any log record
"""Property 4 of the ask spec (task 2.17; Requirements 10.1, 10.2, 10.3, 5.8, 7.5).

One example is one Ask life: an app with Ask on over a Fake_Host, a model double (the
``FakeAdapter``, or the real ``OpenAIAdapter`` over ``httpx2.MockTransport``) with a
generated script of answers, tool turns (hostile argument texts, unknown tools) and
failures of every kind, a Fake_Host that succeeds, stops on wrong screens or raises an
injected exception whose text is a probe, and one to five questions (valid, blank, too
long, with a control character, not a string, a bad body, a wrong media type). Everything
runs through ``POST /ask`` under ``LogCapture`` (root at level 1, plus a handler on every
non-propagating logger). The third-party loggers keep the clamp that ``build_app``
applies, as in production.

Probe_Values are made-up symbols and letters, not credentials. The Publisher key, the
model key and the bound password are generated at run time and never written anywhere.

Scanning rule (as in ``test_publisher_no_leak_logs.py``): an Ask_Record or a
Call_Log_Record carries a random hex id and integers, which can contain a short probe by
chance. For those records only the message, ``args``, ``exc_text``, ``stack_info`` and the
formatted ``exc_info`` are scanned, and every extra field is checked against its exact
type, vocabulary and range instead. Every other record is scanned whole, extra fields
included.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.connector import ConnectorTimeoutError, S3270Error
from greenscreen.publisher.app import _THIRD_PARTY_LOGGERS
from greenscreen.publisher.ask.codes import ASK_ERROR_CODES
from greenscreen.publisher.ask.openai_compat import OpenAIAdapter
from greenscreen.publisher.calls import ERROR_CODES, LOG_ONLY_OUTCOMES
from tests.ask_support import (
    ASK_ENV,
    BOUND_PASSWORD,
    FLOW,
    AskFakeClock,
    Fail,
    FakeAdapter,
    Turn,
    ask_post,
    build_ask_app,
    hostile_calls,
    no_network,  # noqa: F401  (autouse)
)
from tests.property._publisher_strategies import ArbitraryError, all_leak_forms, probes
from tests.publisher_support import FAILURE_POINTS, FakeHost, Failure, LogCapture, system_info_states

PROPERTY_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

LLM_KEY = secrets.token_urlsafe(24)  # generated once per process, never written anywhere
LLM_MODEL = "fake-model"
LLM_URL = ASK_ENV["GS_LLM_BASE_URL"]
ENV = {
    "GS_LLM_API_KEY": LLM_KEY,
    "GS_ASK_DAILY_LIMIT": "3",  # a long list of questions reaches daily_limit
}

FIXED_ASK_TEXTS = ("ask enabled", "ask worst case")
ASK_FIELDS = {"ask_id", "outcome", "model_turns", "tool_calls", "duration_ms", "model_ms", "truncated"}
ASK_REQUIRED = ASK_FIELDS - {"truncated"}
ASK_OUTCOMES = (
    {"ok", "busy", "shutting_down", "internal_error", "request_invalid", "request_too_large"}
    | set(ASK_ERROR_CODES)
)
WORST_CASE_FIELDS = {"worst_case_seconds", "largest_tool_seconds"}
CALL_FIELDS = {"call_id", "flow", "transport", "outcome", "duration_ms", "step_index",
               "close_failed", "session_clean"}
CALL_REQUIRED = {"call_id", "flow", "transport", "outcome", "duration_ms"}
CALL_OUTCOMES = ERROR_CODES | {"ok"} | LOG_ONLY_OUTCOMES
HEX_ID = re.compile(r"[0-9a-f]{16}")
ARG_OK = re.compile(r"""['"]?(\d+|GS_[A-Z0-9_]+|[a-z0-9_-]+)['"]?""")
# GS_ASK_MAX_TOOL_CALLS is 6; the turn that passes it still answers each of its (at most 4)
# calls, and every Rejected_Call counts (tests/unit/test_ask_limits.py), so up to 6 + 4 (six calls pass, then a turn of four is all rejected).
MAX_TOOL_COUNT = 10
MAX_MS = 400_000  # a question ends within 95 s of the clock; 4 questions at most


@pytest.fixture(scope="module", autouse=True)
def _restore_logger_levels():
    names = ("",) + tuple(_THIRD_PARTY_LOGGERS)
    saved = {n: logging.getLogger(n).level for n in names}
    yield
    for n, level in saved.items():
        logging.getLogger(n).setLevel(level)


# --------------------------------------------------------------------------
# The real adapter over a scripted transport
# --------------------------------------------------------------------------

class _ViaMockTransport:
    """The real ``OpenAIAdapter`` over ``httpx2.MockTransport``, one client per reply.

    The script items are the same as the ``FakeAdapter``'s, turned into HTTP replies:
    an answer or a tool turn is a 200 chat completion, a failure is a status or a raised
    transport error whose text holds a probe. A used-up script answers with an empty
    ``choices`` list (the adapter's ``unusable``).
    """

    def __init__(self, script: list[Any], error_text: str, reasoning: str = "") -> None:
        self._script = script
        self._error_text = error_text
        self._reasoning = reasoning
        self._position = 0
        self._ids = 0

    async def complete(self, messages: list[dict], tools: list[dict], *, timeout_seconds: float):
        transport = httpx2.MockTransport(self._handle)
        async with OpenAIAdapter(LLM_URL, LLM_MODEL, LLM_KEY, transport=transport) as adapter:
            return await adapter.complete(messages, tools, timeout_seconds=timeout_seconds)

    def _extras(self) -> dict[str, Any]:
        """Hostile members every reply carries: the probe in ``reasoning``, ``usage``, an unknown one."""
        r = self._reasoning
        return {
            "reasoning": r,
            "usage": {"prompt_tokens": 7, "prompt_tokens_details": {"cached_tokens": 0, "note": r}},
            "system_fingerprint": r,
            "unknown_member": {"reasoning": r},
        }

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if self._position >= len(self._script):
            return httpx2.Response(200, json={"choices": [], **self._extras()})
        item = self._script[self._position]
        self._position += 1
        if isinstance(item, Fail):
            if item.kind == "unreachable":
                raise httpx2.ConnectError(self._error_text)
            status = {"refused": 401, "busy": 429}.get(item.kind)
            if status is not None:
                return httpx2.Response(
                    status, json={"error": {"message": self._error_text}, **self._extras()}
                )
            return httpx2.Response(200, json={"choices": [], **self._extras()})
        if item.calls:
            calls = []
            for name, text in item.calls:
                self._ids += 1
                calls.append({
                    "id": f"call_{self._ids}", "type": "function",
                    "function": {"name": name, "arguments": text},
                })
            message: dict[str, Any] = {"role": "assistant", "content": None, "tool_calls": calls}
            message["reasoning"] = self._reasoning
            return httpx2.Response(
                200,
                json={"choices": [{"message": message, "finish_reason": "tool_calls"}], **self._extras()},
            )
        message = {"role": "assistant", "content": item.answer, "reasoning": self._reasoning}
        return httpx2.Response(
            200, json={"choices": [{"message": message, "finish_reason": "stop"}], **self._extras()}
        )


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Question:
    kind: str
    probe: str
    other: str

    def send(self) -> dict[str, Any]:
        """Keyword arguments for ``ask_post``."""
        if self.kind == "valid":
            return {"question": f"{self.probe} {self.other}?"}
        if self.kind == "blank":
            return {"question": "   "}
        if self.kind == "long":
            return {"question": self.probe * 130}
        if self.kind == "control":
            return {"question": self.probe + "\x00"}
        if self.kind == "non_string":
            return {"question": [self.probe]}
        if self.kind == "bad_body":
            return {"question": None, "body": self.probe.encode("utf-8")}
        return {"question": f"{self.probe}?", "content_type": "text/plain"}  # bad_type

    def values(self) -> list[str]:
        out = [self.probe, self.other]
        sent = self.send().get("question")
        if isinstance(sent, str):
            out.append(sent)
        return out


@dataclass(frozen=True)
class Scenario:
    real_adapter: bool
    host_kind: str  # "ok", "wrong_screens" or "failure"
    failure: Failure | None
    script: tuple[Any, ...]
    questions: tuple[Question, ...]
    error_text: str
    values: tuple[str, ...]
    reasoning: str = ""


_QUESTION_KINDS = ("valid", "valid", "valid", "blank", "long", "control", "non_string", "bad_body", "bad_type")
_FAIL_KINDS = ("unreachable", "refused", "unusable", "busy")
_EXCEPTIONS = (RuntimeError, OSError, ValueError, S3270Error, ConnectorTimeoutError, ArbitraryError)
_USERIDS = st.text(alphabet="qxzjkw", min_size=4, max_size=8)  # matches the userid regex


@st.composite
def _scenarios(draw) -> Scenario:
    uid = draw(_USERIDS)
    error_text = draw(probes("str", min_size=8, max_size=16))
    reasoning = draw(probes("str", min_size=8, max_size=16))  # hostile `reasoning` Probe_Value
    values: list[str] = [uid, error_text, reasoning]

    def answer_item():
        probe = draw(probes("str", min_size=4, max_size=12))
        times = draw(st.sampled_from((1, 1, 2, 300)))  # 300 repeats are cut to the limit
        values.append(probe)
        return Turn(answer=probe * times, seconds=draw(st.sampled_from((0.0, 0.0, 30.0))))

    def tool_item():
        calls = draw(hostile_calls(value=uid, max_calls=4))
        return Turn(calls=calls, seconds=draw(st.sampled_from((0.0, 0.0, 30.0))))

    def fail_item():
        return Fail(draw(st.sampled_from(_FAIL_KINDS)), seconds=draw(st.sampled_from((0.0, 0.0, 30.0))))

    item = st.sampled_from(("answer", "tool", "tool", "fail"))
    script = []
    for kind in draw(st.lists(item, min_size=0, max_size=10)):
        script.append({"answer": answer_item, "tool": tool_item, "fail": fail_item}[kind]())
    questions = []
    for kind in draw(st.lists(st.sampled_from(_QUESTION_KINDS), min_size=1, max_size=5)):
        q = Question(kind, draw(probes("str", min_size=4, max_size=8)), draw(probes("str")))
        questions.append(q)
        values.extend(q.values())

    host_kind = draw(st.sampled_from(("ok", "ok", "wrong_screens", "failure")))
    failure = None
    if host_kind == "failure":
        failure = Failure(
            draw(st.sampled_from(FAILURE_POINTS)),
            draw(st.sampled_from(_EXCEPTIONS)),
            draw(st.sampled_from((1, 2))),
            None,
            error_text,
        )
    return Scenario(
        draw(st.booleans()), host_kind, failure, tuple(script), tuple(questions),
        error_text, tuple(dict.fromkeys(values)), reasoning,
    )


def _host(s: Scenario) -> FakeHost:
    states = system_info_states()
    if s.host_kind == "wrong_screens":
        states = list(reversed(states))
    return FakeHost(states, failures=(s.failure,) if s.failure else ())


# --------------------------------------------------------------------------
# The checks
# --------------------------------------------------------------------------

def _scan_texts(rec) -> list[str]:
    if rec.logger.startswith("greenscreen.publisher") and rec.message in (
        "call finished", "ask finished"
    ):
        return [t for t in (rec.message, *rec.args, rec.exc_text, rec.stack_info, rec.exc_info_text) if t]
    return rec.texts()


def _is_count(value: Any, upper: int) -> bool:
    return type(value) is int and 0 <= value <= upper


def _check_permitted_ask(rec) -> str | None:
    """None when the record is one the Ask package and the publisher may write, else a reason."""
    if rec.logger.startswith("greenscreen.publisher.ask") and rec.message not in (
        "ask finished", *FIXED_ASK_TEXTS
    ):
        return "record of the Ask package with a text that is not fixed"
    if rec.logger in ("httpx2", "httpcore2") and rec.level < logging.WARNING:
        return "httpx2 or httpcore2 record below WARNING"
    if not rec.logger.startswith("greenscreen.publisher"):
        return None
    if rec.exc_text or rec.stack_info or rec.exc_info_text:
        return "exception or stack text"
    f = rec.fields
    if rec.message == "ask finished":
        if rec.level != logging.INFO or rec.args:
            return "ask record level or args"
        if not ASK_REQUIRED <= set(f) or not set(f) <= ASK_FIELDS:
            return "ask record field names"
        if not (isinstance(f["ask_id"], str) and HEX_ID.fullmatch(f["ask_id"])):
            return "ask_id"
        if f["outcome"] not in ASK_OUTCOMES:
            return "ask outcome"
        if not _is_count(f["model_turns"], 8) or not _is_count(f["tool_calls"], MAX_TOOL_COUNT):
            return "turn or tool counts"
        if not _is_count(f["duration_ms"], MAX_MS) or not _is_count(f["model_ms"], MAX_MS):
            return "ask durations"
        if "truncated" in f and f["truncated"] is not True:
            return "truncated"
        return None
    if rec.message in FIXED_ASK_TEXTS:
        if rec.message == "ask enabled":
            return None if not f and not rec.args else "ask enabled has fields"
        if set(f) != WORST_CASE_FIELDS or any(type(v) is not float for v in f.values()):
            return "ask worst case fields"
        return None
    if rec.message == "call finished":
        if rec.level != logging.INFO or rec.args:
            return "call record level or args"
        if not CALL_REQUIRED <= set(f) or not set(f) <= CALL_FIELDS:
            return "call record field names"
        if not (isinstance(f["call_id"], str) and HEX_ID.fullmatch(f["call_id"])):
            return "call_id"
        if f["flow"] != FLOW or f["transport"] != "ask":
            return "flow or transport"
        if f["outcome"] not in CALL_OUTCOMES:
            return "call outcome"
        for key in ("duration_ms", "step_index"):
            if key in f and not _is_count(f[key], MAX_MS):
                return key
        if "close_failed" in f and f["close_failed"] is not True:
            return "close_failed"
        if "session_clean" in f and f["session_clean"] is not False:
            return "session_clean"
        return None
    if f:
        return "extra fields on a record that is not an Ask or call record"
    for text in rec.args:
        if not ARG_OK.fullmatch(text):
            return "argument outside the permitted kinds"
    if "%" in rec.message or len(rec.message) > 80:
        return "message is not fixed text"
    return None


def _strings(node: Any, key: str | None = None):
    """Every string or integer value of ``outputs`` members, and the answer, in a body."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "answer" and isinstance(v, str):
                yield v
            elif k == "outputs" and isinstance(v, dict):
                for o in v.values():
                    if isinstance(o, (str, int)) and len(str(o)) >= 4:
                        yield str(o)
            else:
                yield from _strings(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v, key)


async def _life(s: Scenario, adapter: Any, host: FakeHost, clock: AskFakeClock):
    built = build_ask_app(ENV, adapter=adapter, host=host, clock=clock)
    seen: list[str] = [built.api_key]
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(built.app.lifespan())
        for q in s.questions:
            reply = await ask_post(built, **q.send())
            try:
                body = reply.json()
            except ValueError:
                continue
            seen.extend(t for t in _strings(body) if len(t) <= 3000)
    return seen


# Feature: ask, Property 4: No question, answer, model text or tool data in any log record
@PROPERTY_SETTINGS
@given(_scenarios())
def test_no_question_answer_model_text_or_tool_data_in_any_log_record(s: Scenario):
    """**Validates: Requirements 10.1, 10.2, 10.3, 5.8, 7.5**"""
    clock = AskFakeClock()
    adapter = (
        _ViaMockTransport(list(s.script), s.error_text, s.reasoning)
        if s.real_adapter
        else FakeAdapter(list(s.script), clock=clock)
    )
    for name in _THIRD_PARTY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)  # build_app applies the clamp again
    with LogCapture() as cap:
        seen = asyncio.run(_life(s, adapter, _host(s), clock))
        cap.refresh()
        records = cap.records

    forms = all_leak_forms([
        *s.values, *seen, BOUND_PASSWORD, LLM_KEY, LLM_MODEL, LLM_URL,
    ])
    asks = [r for r in records if r.message == "ask finished"]
    assert len(asks) == len(s.questions), "not one Ask_Record per question"
    leaks = [f"{r.logger} level={r.level}" for r in records
             if any(f in t for t in _scan_texts(r) for f in forms)]
    assert leaks == [], f"a question, answer, model text, tool value or key reached a log record: {leaks}"
    bad = [(r.logger, why) for r in records for why in [_check_permitted_ask(r)] if why]
    assert bad == [], f"records outside the permitted set: {bad}"
