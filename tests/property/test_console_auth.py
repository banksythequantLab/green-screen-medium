"""Property 1 of the console spec: only the six console routes are open without a key."""
from __future__ import annotations

import asyncio
import functools
import json

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.publisher.calls import error_body
from tests.console_support import EXPECTED_PAIRS, build_console_app, call_scope
from tests.property._publisher_strategies import key_headers

UNAUTHORIZED = error_body("unauthorized")
OPEN = EXPECTED_PAIRS | {("GET", "/health")}
EXACT_PATHS = sorted({p for _, p in OPEN})

# Valid cases of key_headers are left out: with a valid key everything is allowed.
_PROBE_KEY = "k" * 24
_INVALID = key_headers(_PROBE_KEY).filter(lambda c: not c.accepted)


@functools.lru_cache(maxsize=1)
def _app():
    return build_console_app({"GS_ENABLE_DOCS": "true"})


_TOKENS = ("GET", "HEAD", "OPTIONS", "POST", "PUT", "DELETE", "PATCH")
methods = st.one_of(
    st.sampled_from(_TOKENS),
    st.sampled_from(_TOKENS).map(str.lower),
    st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz", min_size=1, max_size=8),
)

_exact = st.sampled_from(EXACT_PATHS)
_text = st.text(alphabet=st.characters(codec="utf-8", exclude_categories=("Cs",)), max_size=30)
_junk = st.sampled_from(["/", "//", "..", "/..", "%2e", "%2F", "%00", "?x=1", "#a", " ", "/x"])
paths = st.one_of(
    _exact,
    _exact.map(lambda p: p + "/"),
    _exact.map(lambda p: p.upper()),
    _exact.map(lambda p: p.swapcase()),
    _exact.map(lambda p: p.replace("/", "//")),
    _exact.map(lambda p: p.replace("/", "%2F")),
    _exact.map(lambda p: "/.." + p),
    _exact.map(lambda p: "/console/.." + p),
    st.tuples(_exact, _junk).map(lambda t: t[0] + t[1]),
    st.tuples(_junk, _exact).map(lambda t: t[0] + t[1]),
    st.tuples(_exact, _text).map(lambda t: t[0] + t[1]),
    _text.map(lambda t: "/" + t),
    _text,
)


def _unauthorized(status: int, body: bytes) -> bool:
    if status != 401:
        return False
    try:
        return json.loads(body) == UNAUTHORIZED
    except ValueError:
        return False


@settings(max_examples=100, deadline=None)
@given(method=methods, path=paths, case=_INVALID)
def test_only_the_six_console_routes_are_open_without_a_key(method, path, case):
    # Feature: console, Property 1: Only the six console routes are open without a key
    # Validates: Requirements 3.1, 3.3, 3.4, 3.6, 3.7
    app = _app()
    status, _, body = asyncio.run(call_scope(app.app.asgi, method, path, list(case.headers)))
    should_be_open = (method, path) in OPEN
    assert _unauthorized(status, body) == (not should_be_open), (
        f"method={method!r} path={path!r} key_case={case.kind} status={status}"
    )
