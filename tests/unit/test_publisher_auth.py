"""Unit tests for greenscreen.publisher.auth (Requirement 13, 19.4). Keys are random per run."""
from __future__ import annotations

import asyncio
import hmac
import json
import secrets

import pytest

from greenscreen.publisher import auth
from greenscreen.publisher.auth import AuthMiddleware, extract_key

KEY = "k" + secrets.token_hex(12)
OTHER = "o" + secrets.token_hex(12)


def H(**items: str) -> list[tuple[bytes, bytes]]:
    return [(k.replace("_", "-").encode(), v.encode()) for k, v in items.items()]


def run(mw, *, path="/flows/x", method="GET", headers=(), scope_type="http"):
    """Drive one request through mw; return (inner_calls, sent_messages)."""
    calls: list[dict] = []

    async def inner(scope, receive, send):
        calls.append(scope)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"inner"})

    wrapped = mw(inner)
    sent: list[dict] = []

    async def receive():  # pragma: no cover - must never be awaited by the guard
        raise AssertionError("body was read")

    async def send(msg):
        sent.append(msg)

    scope = {"type": scope_type, "path": path, "method": method, "headers": list(headers)}
    asyncio.run(wrapped(scope, receive, send))
    return calls, sent


def guard(key=KEY, disabled=False):
    return lambda app: AuthMiddleware(app, api_key=key, disabled=disabled)


def status(sent):
    return sent[0]["status"]


def assert_unauthorized(calls, sent):
    assert calls == []
    assert status(sent) == 401
    body = json.loads(sent[1]["body"])
    assert body == {"error": {"code": "unauthorized", "message": "A valid API key is required."}}


# --- extract_key ---------------------------------------------------------------

def test_extract_x_api_key():
    assert extract_key(H(x_api_key=KEY)) == KEY


def test_extract_bearer_case_insensitive_and_many_spaces():
    assert extract_key(H(authorization=f"Bearer {KEY}")) == KEY
    assert extract_key(H(authorization=f"bEaReR   {KEY}")) == KEY


def test_extract_header_names_any_case():
    assert extract_key([(b"X-API-Key", KEY.encode())]) == KEY


def test_extract_both_equal():
    assert extract_key(H(x_api_key=KEY, authorization=f"Bearer {KEY}")) == KEY


@pytest.mark.parametrize(
    "headers",
    [
        [],
        H(x_api_key=""),
        H(x_api_key="", authorization=f"Bearer {KEY}"),  # empty X-API-Key beside valid Bearer
        H(authorization="Bearer"),
        H(authorization="Bearer "),
        H(authorization=f"Basic {KEY}"),
        H(authorization=f"Bearer{KEY}"),
        H(authorization=f"Bearer {KEY} extra"),
        H(authorization=f"Bearer\t{KEY}"),
        H(authorization=f" Bearer {KEY}"),
        H(authorization=KEY),
        H(x_api_key=KEY, authorization="Basic abc"),  # malformed Authorization beside valid key
        H(x_api_key=KEY, authorization=f"Bearer {OTHER}"),  # differing pair
    ],
)
def test_extract_rejects(headers):
    assert extract_key(headers) is None


def test_extract_repeated_headers_invalid():
    assert extract_key(H(x_api_key=KEY) + H(x_api_key=KEY)) is None
    assert extract_key(H(authorization=f"Bearer {KEY}") * 2) is None


def test_extract_invalid_utf8_is_none():
    assert extract_key([(b"x-api-key", b"\xff\xfe")]) is None


# --- middleware, enabled -------------------------------------------------------

def test_valid_key_either_carrier_and_both():
    for headers in (
        H(x_api_key=KEY),
        H(authorization=f"Bearer {KEY}"),
        H(x_api_key=KEY, authorization=f"Bearer {KEY}"),
    ):
        calls, sent = run(guard(), headers=headers)
        assert len(calls) == 1 and status(sent) == 200


@pytest.mark.parametrize("path", ["/flows/x", "/openapi.json", "/docs", "/mcp", "/nothing"])
def test_every_path_protected(path):
    assert_unauthorized(*run(guard(), path=path, method="POST"))
    calls, sent = run(guard(), path=path, method="POST", headers=H(x_api_key=KEY))
    assert len(calls) == 1


def test_wrong_and_missing_key_same_response():
    outs = []
    for headers in (
        [],
        H(x_api_key=OTHER),
        H(authorization=f"Bearer {OTHER}"),
        H(x_api_key=KEY, authorization=f"Bearer {OTHER}"),
        H(authorization="garbage"),
        H(x_api_key=""),
        H(x_api_key=KEY[:-1]),
        H(x_api_key=KEY + "x"),
    ):
        calls, sent = run(guard(), headers=headers)
        assert_unauthorized(calls, sent)
        outs.append(sent)
    assert all(o == outs[0] for o in outs)


def test_response_headers():
    _, sent = run(guard())
    hdrs = dict(sent[0]["headers"])
    assert hdrs[b"content-type"] == b"application/json"
    assert hdrs[b"cache-control"] == b"no-store"
    assert hdrs[b"www-authenticate"] == b"Bearer"
    assert int(hdrs[b"content-length"]) == len(sent[1]["body"])
    assert KEY.encode() not in sent[1]["body"]


def test_health_open_only_for_get():
    calls, sent = run(guard(), path="/health", method="GET")
    assert len(calls) == 1 and status(sent) == 200
    assert_unauthorized(*run(guard(), path="/health", method="POST"))
    assert_unauthorized(*run(guard(), path="/health/", method="GET"))


def test_no_configured_key_fails_closed():
    assert_unauthorized(*run(guard(key=None), headers=H(x_api_key=KEY)))


def test_non_ascii_key_compares_as_utf8():
    key = "clé-" + secrets.token_hex(8)
    mw = guard(key=key)
    calls, _ = run(mw, headers=[(b"x-api-key", key.encode("utf-8"))])
    assert len(calls) == 1


def test_lifespan_passes_through():
    calls, _ = run(guard(), scope_type="lifespan")
    assert len(calls) == 1


def test_websocket_refused_without_reaching_app():
    calls, sent = run(guard(), scope_type="websocket", headers=H(x_api_key=KEY))
    assert calls == [] and sent == [{"type": "websocket.close", "code": 1008}]


def test_repr_has_no_key():
    assert KEY not in repr(AuthMiddleware(None, api_key=KEY, disabled=False))


# --- middleware, disabled (loopback Host rule) ---------------------------------

@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8080", "LOCALHOST", "127.0.0.1", "127.0.0.1:9", "127.5.5.5", "[::1]", "[::1]:8080"],
)
def test_disabled_accepts_loopback_host_without_key(host):
    calls, sent = run(guard(key=None, disabled=True), headers=H(host=host))
    assert len(calls) == 1 and status(sent) == 200


@pytest.mark.parametrize(
    "headers",
    [
        [],
        H(host="evil.example"),
        H(host="evil.example:80"),
        H(host="localhost.evil.example"),
        H(host="192.168.1.5"),
        H(host=""),
        H(host="[::1"),
        H(host="::1"),
        H(host="localhost:abc"),
        H(host="localhost") + H(host="evil.example"),
    ],
)
def test_disabled_rejects_other_hosts(headers):
    assert_unauthorized(*run(guard(key=None, disabled=True), headers=headers))


def test_disabled_applies_to_every_path_including_health():
    assert_unauthorized(*run(guard(key=None, disabled=True), path="/health", headers=H(host="evil.example")))


# --- constant-time comparison (Requirement 19.4) -------------------------------

def test_comparison_uses_hmac_compare_digest_on_bytes(monkeypatch):
    seen: list[tuple[object, object]] = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(auth.hmac, "compare_digest", spy)
    calls, _ = run(guard(), headers=H(x_api_key=OTHER))
    assert calls == []
    assert seen == [(OTHER.encode(), KEY.encode())]
    seen.clear()
    calls, _ = run(guard(), headers=H(x_api_key=KEY, authorization=f"Bearer {KEY}"))
    assert len(calls) == 1
    assert all(isinstance(a, bytes) and isinstance(b, bytes) for a, b in seen)
    assert (KEY.encode(), KEY.encode()) in seen


def test_key_comparison_never_uses_python_equality():
    class Boom(str):
        def __eq__(self, other):
            raise AssertionError("== used on the key")

        __hash__ = str.__hash__

        def __ne__(self, other):
            raise AssertionError("!= used on the key")

    calls, _ = run(guard(key=Boom(KEY)), headers=H(x_api_key=KEY))
    assert len(calls) == 1
    assert_unauthorized(*run(guard(key=Boom(KEY)), headers=H(x_api_key=OTHER)))
