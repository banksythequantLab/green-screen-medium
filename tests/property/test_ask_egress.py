# Feature: ask, Property 1: Nothing outside the egress allow-list reaches the model
"""Property 1 of the Ask feature (task 2.14): nothing outside the egress allow-list
reaches the model.

One ``@given`` test. Each example draws a Publisher API key (the app generates it), a
bound password and a bound user id of ``tk5-system-info``, a model API key, a hostile
question, a Fake_Host plan that usually ends in a Flow stop (so a screen ``summary``
exists in the tool result), and a script of model turns that call the offered tool.

Two modes, drawn per example:

* fake adapter: ``FakeAdapter.received`` is the egress;
* real adapter: the service's ``open_adapter`` is replaced by one that builds the real
  ``OpenAIAdapter`` (as ``build_app`` does) over ``httpx2.MockTransport``; the captured
  request bodies are the egress. The configured ``reasoning_effort`` is drawn from the
  five allowed texts or left unset and is read back from the built service's settings.
  The model's replies carry a hostile ``reasoning`` member.

Oracle: no Leak_Form of the secrets in the egress, no screen text, no audit member name
as a key, each ``tool`` message equal to the Model_Facing_Result recomputed here from
the tool result the real ``McpToolPort`` returned, and (real mode) request body keys
within ``model``, ``messages``, ``tools``, ``reasoning_effort`` with no ``tool_choice``,
``reasoning_effort`` present once and equal to the configured text or absent when unset
and the same in every request of the question, and the hostile ``reasoning`` text in no
later request, no response and no log record.

All values are generated here and never written anywhere.
"""
from __future__ import annotations

import asyncio
import json
import re
import string
from dataclasses import replace
from unittest import mock

import httpx2
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.publisher.ask import service as ask_service
from greenscreen.publisher.ask.agent import INTERNAL_TEXT
from greenscreen.publisher.ask.openai_compat import OpenAIAdapter
from tests.ask_support import (
    FLOW,
    AskFakeClock,
    FakeAdapter,
    Turn,
    ask_post,
    build_ask_app,
    no_network,  # noqa: F401  (autouse)
)
from tests.property._publisher_strategies import (
    NAME_ALPHABET,
    SETTINGS,
    HostPlan,
    fake_host_plans,
    find_leaks,
    probes,
)
from tests.publisher_support import FakeHost, LogCapture, system_info_states

EFFORTS = ("none", "minimal", "low", "medium", "high")
ALLOWED_KEYS = {"model", "messages", "tools", "reasoning_effort"}
AUDIT_MEMBERS = (
    "step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds",
)
_AUDIT_KEY = re.compile(r'\\*"(?:' + "|".join(AUDIT_MEMBERS) + r')\\*"\s*:')
_PASSWORD_VARIABLE = "GS_BIND_" + "TK5_SYSTEM_INFO__PASSWORD"
_USERID_VARIABLE = "GS_BIND_" + "TK5_SYSTEM_INFO__USERID"
_BASE_URL = "http://127.0.0.1:11434/v1"

# A Fake_Host plan that stops the Flow on the wrong screen is the common case.
_PLANS = st.one_of(
    fake_host_plans(),
    fake_host_plans().map(lambda p: replace(p, wrong_screens=True)),
    fake_host_plans().map(lambda p: replace(p, wrong_screens=True)),
)
_PHRASES = (
    "reasoning_effort", "tool_choice", "high", "none", '"reasoning_effort": "high"',
    "set reasoning_effort to none", '{"tool_choice": "required"}', "what is the release",
)
_QUESTIONS = st.builds(
    lambda parts, tail: " ".join(parts) + " " + tail,
    st.lists(st.sampled_from(_PHRASES), min_size=1, max_size=6),
    st.text(alphabet=NAME_ALPHABET + " ", max_size=40),
).map(str.strip)
_ANSWERS = st.builds(
    lambda parts, tail: " ".join(parts) + " " + tail + ".",
    st.lists(st.sampled_from(_PHRASES), min_size=1, max_size=3),
    st.text(alphabet=NAME_ALPHABET, min_size=1, max_size=12),
)
_USERIDS = st.text(alphabet="#@$0123456789", min_size=6, max_size=8).filter(lambda s: s[0] in "#@$")
# Digits after a prefix: a random letter string can equal text the request legitimately holds.
_MODEL_KEYS = st.text(alphabet=string.digits, min_size=20, max_size=30).map(lambda d: "MK" + d)
_MARKERS = st.text(alphabet=string.digits, min_size=12, max_size=12).map(lambda d: "RZ" + d)
# 1 or 2 tool-call turns of 1 or 2 calls each, then the answer.
_BATCHES = st.lists(st.integers(1, 2), min_size=1, max_size=2)

_TEST_SETTINGS = settings(SETTINGS, suppress_health_check=[HealthCheck.function_scoped_fixture])


def _states(plan: HostPlan):
    states = system_info_states()
    return list(reversed(states)) if plan.wrong_screens else states


def _facing_text(res) -> str:
    """The Model_Facing_Result rule, written again here (design section 4)."""
    body = res.body or {}
    if res.code == "ok":
        shown = {"flow": body.get("flow"), "outputs": body.get("outputs")}
    else:
        err = body.get("error") if isinstance(body.get("error"), dict) else {}
        msg = err.get("message") if isinstance(err.get("message"), str) else INTERNAL_TEXT
        shown = {"error": {"code": res.code, "message": msg[:300]}}
    return json.dumps(shown, separators=(",", ":"))


def _row_texts(node) -> list[str]:
    """Every string in a ``row_text`` list found anywhere in a result body."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "row_text" and isinstance(value, list):
                found += [v for v in value if isinstance(v, str)]
            else:
                found += _row_texts(value)
    elif isinstance(node, list):
        for value in node:
            found += _row_texts(value)
    return found


def _top_level_keys(raw: bytes) -> list[str]:
    """The member names of the top-level object of ``raw``, duplicates kept."""
    pairs_seen: list[list[tuple[str, object]]] = []

    def hook(pairs):
        pairs_seen.append(list(pairs))
        return dict(pairs)

    json.loads(raw, object_pairs_hook=hook)
    return [k for k, _ in pairs_seen[-1]]  # the outermost object completes last


def _reply_message(n: int, batches: list[int], answer: str, marker: str) -> dict:
    if n < len(batches):
        calls = [
            {
                "id": f"call_{n}_{i}",
                "type": "function",
                "function": {"name": FLOW, "arguments": "{}"},
            }
            for i in range(batches[n])
        ]
        message = {"role": "assistant", "content": None, "tool_calls": calls}
        finish = "tool_calls"
    else:
        message = {"role": "assistant", "content": answer}
        finish = "stop"
    message["reasoning"] = marker  # hostile member: must never come back
    return {
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10,
            "prompt_tokens_details": {"cached_tokens": 0, "note": marker},
        },
        "system_fingerprint": marker,
        "unknown_member": {"reasoning": marker},
    }


@_TEST_SETTINGS
@given(
    real=st.booleans(),
    effort=st.sampled_from((None,) + EFFORTS),
    password=probes("str", min_size=4, max_size=8),
    userid=_USERIDS,
    model_key=_MODEL_KEYS,
    question=_QUESTIONS,
    answer=_ANSWERS,
    plan=_PLANS,
    batches=_BATCHES,
    marker=_MARKERS,
)
def test_nothing_outside_the_egress_allow_list_reaches_the_model(
    real, effort, password, userid, model_key, question, answer, plan, batches, marker
):
    """**Validates: Requirements 7.1, 7.2, 7.3, 7.5, 7.8, 3.7, 8.1, 5.12, 5.13**"""
    env = {
        _PASSWORD_VARIABLE: password,
        _USERID_VARIABLE: userid,
        "GS_LLM_API_KEY": model_key,
    }
    if real and effort is not None:
        env["GS_LLM_REASONING_EFFORT"] = effort
    clock = AskFakeClock()
    host = FakeHost(
        lambda _n: _states(plan), failures=(plan.failure,) if plan.failure else ()
    )

    bodies: list[bytes] = []
    results: list = []

    if real:
        def handler(request: httpx2.Request) -> httpx2.Response:
            bodies.append(request.content)
            return httpx2.Response(200, json=_reply_message(len(bodies) - 1, batches, answer, marker))

        ask = build_ask_app(env, FakeAdapter((), clock=clock), host, clock)
        svc = ask.app.ask
        configured = svc._ask.reasoning_effort
        assert configured == (effort if real else None)
        # What build_app puts there when no double is given, over a mock transport.
        svc._open_adapter = lambda: OpenAIAdapter(
            svc._ask.base_url, svc._ask.model, svc._ask.llm_api_key,
            reasoning_effort=svc._ask.reasoning_effort,
            transport=httpx2.MockTransport(handler),
        )
    else:
        script = [Turn(calls=((FLOW, "{}"),) * n) for n in batches] + [Turn(answer=answer)]
        adapter = FakeAdapter(script, clock=clock)
        ask = build_ask_app(env, adapter, host, clock)

    original_call = ask_service.McpToolPort.call

    async def recording_call(self, name, arguments):
        res = await original_call(self, name, arguments)
        results.append(res)
        return res

    async def go():
        async with ask.app.lifespan():
            return await ask_post(ask, question)

    with LogCapture() as logs, mock.patch.object(ask_service.McpToolPort, "call", recording_call):
        logs.refresh()
        reply = asyncio.run(go())
        log_texts = logs.texts()

    assert reply.status == 200, reply.raw[:200]  # the extra reply members cause no error
    assert "answer" in reply.json()
    assert len(results) == sum(batches)

    # --- what the model was sent --------------------------------------------------------
    if real:
        assert len(bodies) == len(batches) + 1
        sent = [json.loads(b) for b in bodies]
        egress = [b.decode("utf-8") for b in bodies]
    else:
        assert len(ask.adapter.received) == len(batches) + 1
        sent = [json.loads(r) for r in ask.adapter.received]
        egress = list(ask.adapter.received)
    haystack = "\n".join(egress)

    # 1. no Leak_Form of the API key, a bound value or the model's own key
    secrets_ = (ask.api_key, password, userid, model_key)
    assert find_leaks(haystack, secrets_) == []

    # 2. no screen text of a tool result (rows the first request already holds are skipped)
    first = egress[0]
    rows = {
        r.strip()
        for res in results
        for r in _row_texts(res.body)
        if len(r.strip()) >= 8 and r.strip() not in first
    }
    assert [r for r in rows if r in haystack] == []

    # 3. none of the seven audit member names as a key
    assert _AUDIT_KEY.search(haystack) is None

    # 4. each tool message equals the Model_Facing_Result of its tool result, in order
    tool_messages = [m["content"] for m in sent[-1]["messages"] if m.get("role") == "tool"]
    assert tool_messages == [_facing_text(res) for res in results]

    if not real:
        return

    # 5. real adapter: body keys, tool_choice, reasoning_effort
    for raw in bodies:
        keys = _top_level_keys(raw)
        assert len(keys) == len(set(keys)) and set(keys) <= ALLOWED_KEYS
        assert "tool_choice" not in keys
        body = json.loads(raw)
        if effort is None:
            assert "reasoning_effort" not in body
        else:
            assert keys.count("reasoning_effort") == 1
            assert body["reasoning_effort"] == effort
    assert len({json.loads(raw).get("reasoning_effort") for raw in bodies}) == 1

    # 6. the hostile `reasoning` text appears in no request, response or log record
    assert marker not in haystack
    assert marker not in reply.raw.decode("utf-8")
    assert [t for t in log_texts if marker in t] == []
