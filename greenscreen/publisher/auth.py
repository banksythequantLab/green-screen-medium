"""API key check as a pure ASGI middleware (Requirement 13).

The middleware wraps the whole application, so REST, ``/openapi.json``, ``/docs`` and
``/mcp`` share one rule. Every failure gives the same fixed ``unauthorized`` body, sent
before any request body is read. No header value is logged, stored or put in a response.
"""
from __future__ import annotations

import hmac
import json
import re
from collections.abc import Sequence

from greenscreen.publisher.calls import HTTP_STATUS, RESPONSE_HEADERS, error_body
from greenscreen.publisher.config import is_loopback_host

__all__ = ["extract_key", "AuthMiddleware"]

_BEARER = re.compile(rb"[Bb][Ee][Aa][Rr][Ee][Rr] +([!-~]+)")
_HEALTH_PATH = "/health"


def extract_key(headers: Sequence[tuple[bytes, bytes]]) -> str | None:
    """The presented key by the rules of Requirement 13.11, or ``None`` if there is none
    or the headers are malformed. Works on the raw ASGI list so duplicates are visible."""
    api_values = [v for k, v in headers if k.lower() == b"x-api-key"]
    auth_values = [v for k, v in headers if k.lower() == b"authorization"]
    if len(api_values) > 1 or len(auth_values) > 1:
        return None
    from_api: bytes | None = None
    from_bearer: bytes | None = None
    if api_values:
        if not api_values[0]:
            return None
        from_api = api_values[0]
    if auth_values:
        match = _BEARER.fullmatch(auth_values[0])
        if match is None:
            return None
        from_bearer = match.group(1)
    if from_api is not None and from_bearer is not None:
        if not hmac.compare_digest(from_api, from_bearer):
            return None
        chosen = from_api
    else:
        chosen = from_api if from_api is not None else from_bearer
    if chosen is None:
        return None
    try:
        return chosen.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _host_is_loopback(headers: Sequence[tuple[bytes, bytes]]) -> bool:
    values = [v for k, v in headers if k.lower() == b"host"]
    if len(values) != 1:
        return False
    try:
        text = values[0].decode("ascii").strip()
    except UnicodeDecodeError:
        return False
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return False
        rest = text[end + 1 :]
        if rest and not re.fullmatch(r":[0-9]*", rest):
            return False
        host = text[: end + 1]
    else:
        if text.count(":") > 1:  # bare IPv6 without brackets is not a valid Host
            return False
        host, sep, port = text.partition(":")
        if sep and not port.isdigit():
            return False
    return bool(host) and is_loopback_host(host)


_BODY = json.dumps(error_body("unauthorized")).encode("utf-8")
_HEADERS: list[tuple[bytes, bytes]] = [
    (b"content-type", b"application/json"),
    (b"content-length", str(len(_BODY)).encode("ascii")),
    (b"cache-control", b"no-store"),
] + [(k.lower().encode("ascii"), v.encode("ascii")) for k, v in RESPONSE_HEADERS["unauthorized"].items()]


class AuthMiddleware:
    def __init__(
        self,
        app,
        *,
        api_key: str | None,
        disabled: bool,
        exempt: frozenset[tuple[str, str]] = frozenset(),
    ) -> None:
        self._app = app
        self._exempt = exempt
        self._key = api_key.encode("utf-8") if api_key is not None else None
        self._disabled = disabled

    def __repr__(self) -> str:
        return f"AuthMiddleware(disabled={self._disabled})"

    async def __call__(self, scope, receive, send) -> None:
        kind = scope["type"]
        if kind == "lifespan":
            await self._app(scope, receive, send)
            return
        if kind != "http":
            if kind == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        if self._allowed(scope):
            await self._app(scope, receive, send)
            return
        await send(
            {"type": "http.response.start", "status": HTTP_STATUS["unauthorized"], "headers": _HEADERS}
        )
        await send({"type": "http.response.body", "body": _BODY})

    def _allowed(self, scope) -> bool:
        headers = scope.get("headers") or []
        if self._disabled:
            return _host_is_loopback(headers)
        pair = (scope.get("method"), scope.get("path"))
        if pair in self._exempt or pair == ("GET", _HEALTH_PATH):
            return True
        if self._key is None:  # fail closed
            return False
        presented = extract_key(headers)
        if presented is None:
            return False
        return hmac.compare_digest(presented.encode("utf-8"), self._key)
