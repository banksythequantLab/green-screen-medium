"""The OpenAI-compatible chat completions adapter.

The only module under ``greenscreen/`` that names ``httpx2``. It sends one POST per
model turn, classifies the reply by HTTP status, and reads only the reply members it
needs. The text of an error reply, of ``reasoning`` and of any unknown member is never
read, stored, logged or returned. ``ModelError`` carries a kind and nothing else.
"""

from __future__ import annotations

import json
from typing import Any

import anyio
import httpx2

from greenscreen.publisher.ask.adapter import ModelError, ModelTurn, ToolCallRequest

MAX_REPLY_BYTES = 1_048_576
_MAX_ID_CHARS = 200

# The fixed members of a request body. ``reasoning_effort`` is the one optional
# member and is added only by ``_body`` when the operator set it. ``tool_choice``,
# ``parallel_tool_calls``, ``temperature``, ``top_p``, ``max_tokens``, ``stream``,
# ``n``, ``user`` and ``think`` are never sent.
_BODY_KEYS = ("model", "messages", "tools")


def _body(model: str, messages: list[dict], tools: list[dict], effort: str | None) -> dict:
    """Build the request body from the fixed members and the one optional member."""
    body: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                },
            }
            for tool in tools
        ]
    if effort is not None:
        body["reasoning_effort"] = effort
    return body


def _status_kind(status: int) -> str | None:
    """The failure kind for a status, or None when the status is 200."""
    if status == 200:
        return None
    if status in (429, 503):
        return "busy"
    if status == 408 or 500 <= status <= 599:
        return "unreachable"
    if 400 <= status <= 499:
        return "refused"
    return "unusable"


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _parse_calls(raw: list) -> tuple[ToolCallRequest, ...] | None:
    calls: list[ToolCallRequest] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            return None
        kind = item.get("type")
        if kind is not None and kind != "function":
            return None
        call_id = item.get("id")
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= _MAX_ID_CHARS:
            return None
        function = item.get("function")
        if not isinstance(function, dict):
            return None
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, str):
            return None
        if call_id in seen:
            return None
        seen.add(call_id)
        calls.append(ToolCallRequest(call_id, name, arguments))
    return tuple(calls)


def _parse_reply(data: object) -> ModelTurn | str:
    """A ``ModelTurn``, or the failure kind. Reads only ``choices[0]`` members named in the design."""
    if not isinstance(data, dict):
        return "unusable"
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return "unusable"
    choice = choices[0]
    if not isinstance(choice, dict):
        return "unusable"
    message = choice.get("message")
    if not isinstance(message, dict):
        return "unusable"
    finish = choice.get("finish_reason")
    if finish == "length":
        return "unusable"
    if finish == "content_filter":
        return "refused"
    refusal = message.get("refusal")
    if isinstance(refusal, str) and refusal != "":
        return "refused"
    raw_calls = message.get("tool_calls")
    if raw_calls is not None and not isinstance(raw_calls, list):
        return "unusable"
    if raw_calls:
        calls = _parse_calls(raw_calls)
        if calls is None:
            return "unusable"
        return ModelTurn(None, calls)
    content = message.get("content")
    if _nonblank(content):
        return ModelTurn(content, ())
    return "unusable"


class OpenAIAdapter:
    """Async context manager: one ``httpx2.AsyncClient`` per question."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        *,
        reasoning_effort: str | None = None,
        transport: Any = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._key = api_key
        self._effort = reasoning_effort
        self._transport = transport
        self._client: httpx2.AsyncClient | None = None

    def __repr__(self) -> str:
        return "OpenAIAdapter(configured)"

    async def __aenter__(self) -> OpenAIAdapter:
        self._client = httpx2.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            verify=True,
            transport=self._transport,
        )
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_seconds: float,
    ) -> ModelTurn:
        client = self._client
        if client is None:
            raise RuntimeError("adapter is not open")
        payload = json.dumps(
            _body(self._model, messages, tools, self._effort),
            separators=(",", ":"),
        ).encode("ascii")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._key:
            headers["Authorization"] = "Bearer " + self._key
        result: ModelTurn | str
        try:
            with anyio.fail_after(timeout_seconds):
                result = await self._exchange(client, payload, headers, timeout_seconds)
        except (httpx2.HTTPError, httpx2.StreamError, TimeoutError, OSError):
            result = "unreachable"
        # Raised after the except block ends so __context__ is empty: an httpx2
        # exception keeps the request, and the request holds the Authorization header.
        if isinstance(result, str):
            raise ModelError(result)
        return result

    async def _exchange(
        self,
        client: httpx2.AsyncClient,
        payload: bytes,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> ModelTurn | str:
        async with client.stream(
            "POST",
            self._url,
            content=payload,
            headers=headers,
            timeout=httpx2.Timeout(timeout_seconds),
        ) as response:
            kind = _status_kind(response.status_code)
            if kind is not None:
                return kind  # the body of an error reply is never read
            media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if media != "application/json":
                return "unusable"
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_REPLY_BYTES:
                    return "unusable"
                chunks.append(chunk)
        try:
            data = json.loads(b"".join(chunks))
        except (ValueError, RecursionError):
            return "unusable"
        return _parse_reply(data)
