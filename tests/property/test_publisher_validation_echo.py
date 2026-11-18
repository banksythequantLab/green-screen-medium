"""Property 9: a validation error never echoes a submitted value (task 8.5).

One app for the module (built once, with its REST client and its two MCP clients inside one
long-lived task of one event loop). The registry holds ``RX``, a local Flow made for this test:
``MINI``'s steps and Inputs plus a regex on ``userid`` and a bound Input ``token``. The shared
``bad_requests()`` strategy (for ``MINI``-shaped Flows) supplies every kind except the regex
violation, which is generated here. ``RX`` is built here and no shared file is edited.

Each example sends one bad request over REST (with a Content-Length or chunked, so an oversize
body is seen both ways) and, when the kind has an MCP form, over MCP in one of the two modes.
Every channel is checked for every Leak_Form of every submitted value and for an ``input``
member, and the Fake_Host must see zero factory calls. All values are made-up Probe_Values.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import functools
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from greenscreen.flow.model import InputSpec
from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import (
    SETTINGS,
    BadRequest,
    bad_requests,
    find_leaks,
    probes,
)
from tests.publisher_support import MINI, FakeHost, mcp_client, mini_states, rest_client

KEY = "k" * 16
MAX_BODY = 2048
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": KEY,
    "GS_PUBLISH_FLOWS": "tk5-logon",
    "GS_MAX_BODY_BYTES": str(MAX_BODY),
}
MODES = ("legacy", "auto")
BOUND_VALUE = "!#%&*+"  # the Bound_Value of ``token``; a probe, never a credential

RX = dataclasses.replace(
    MINI,
    name="rx",
    inputs=(
        InputSpec("userid", "str", True, 8, "[a-z]{1,8}"),
        InputSpec("password", "str", False, 8, None, True),
        InputSpec("count", "int", False, 4),
        InputSpec("token", "str", False, 8),
    ),
)

_CODE_OF_KIND = {"oversize": "request_too_large"}
_INPUT_KINDS = {"wrong_type", "too_long", "undeclared", "missing", "bound_name", "regex"}
_STATUS = {"input_invalid": 422, "request_too_large": 413, "request_invalid": 400}


def _expected_code(kind: str) -> str:
    if kind in _INPUT_KINDS:
        return "input_invalid"
    return _CODE_OF_KIND.get(kind, "request_invalid")


# --------------------------------------------------------------------------
# The rig
# --------------------------------------------------------------------------


class _Rig:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        bound = BoundValues({"rx": {"token": BOUND_VALUE}})
        registry = build_registry({"rx": (RX, "test")}, bound, 30.0)
        prepared = dataclasses.replace(prepare(ENV), registry=registry, bound=bound)
        self.holder: list = [FakeHost([])]
        self.app = build_app(
            prepared, session_factory=lambda: self.holder[0](), clock=FakeClock(),
            poll_interval=0.1,
        )
        self.loop.run_until_complete(self._start())

    async def _start(self) -> None:
        self.ready = asyncio.Event()
        self.stop = asyncio.Event()
        self.owner = asyncio.ensure_future(self._own())
        await self.ready.wait()
        if self.owner.done():
            self.owner.result()

    async def _own(self) -> None:
        try:
            async with contextlib.AsyncExitStack() as stack:
                self.rest = await stack.enter_async_context(
                    rest_client(self.app, headers={"X-API-Key": KEY})
                )
                self.mcp = {
                    m: await stack.enter_async_context(mcp_client(self.app, m)) for m in MODES
                }
                self.ready.set()
                await self.stop.wait()
        finally:
            self.ready.set()

    def close(self) -> None:
        async def stop() -> None:
            self.stop.set()
            await self.owner

        self.loop.run_until_complete(stop())
        self.loop.close()


@pytest.fixture(scope="module")
def rig():
    r = _Rig()
    yield r
    r.close()


# --------------------------------------------------------------------------
# Strategies (local)
# --------------------------------------------------------------------------


def _regex_violations() -> st.SearchStrategy[BadRequest]:
    """A ``userid`` of at most 8 printable characters that the regex ``[a-z]{1,8}`` refuses."""

    def build(prefix: str, probe: str, other: str) -> BadRequest:
        value = prefix + probe
        args = {"userid": value, "password": other}
        return BadRequest("regex", json.dumps(args).encode("utf-8"), "application/json", args,
                          (value, other))

    return st.builds(
        build,
        st.text(alphabet="abcdefgh", max_size=2),
        probes("str", max_size=6),
        probes("str"),
    )


BAD = st.one_of(bad_requests(MAX_BODY, bound_input="token"), _regex_violations())


async def _chunks(data: bytes):
    for i in range(0, len(data), 512):
        yield data[i : i + 512]


# --------------------------------------------------------------------------
# Observation
# --------------------------------------------------------------------------


def _has_input_member(node) -> bool:
    if isinstance(node, dict):
        return "input" in node or any(_has_input_member(v) for v in node.values())
    if isinstance(node, list):
        return any(_has_input_member(v) for v in node)
    return False


def _json_or_none(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def _rest_text(resp) -> str:
    headers = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
    return f"{resp.status_code}\n{headers}\n{resp.text}"


def _mcp_text(result) -> str:
    parts = [result.model_dump_json(), repr(result), json.dumps(result.structured_content, default=str)]
    parts += [getattr(c, "text", "") or "" for c in result.content]
    return "\n".join(parts)


async def _observe(rig: _Rig, mode: str, bad: BadRequest, chunked: bool) -> dict:
    texts: list[str] = []
    documents: list = []
    out: dict = {}

    content = _chunks(bad.body) if chunked else bad.body
    resp = await rig.rest.post("/flows/rx", content=content, headers={"Content-Type": bad.content_type})
    texts.append(_rest_text(resp))
    documents.append(_json_or_none(resp.text))
    out["status"] = resp.status_code
    out["code"] = (documents[-1] or {}).get("error", {}).get("code") if isinstance(documents[-1], dict) else None
    out["content_length_sent"] = resp.request.headers.get("content-length") is not None

    out["mcp_rejected"] = None
    if bad.arguments is not None:
        try:
            result = await rig.mcp[mode].call_tool("rx", bad.arguments)
        except Exception as exc:  # noqa: BLE001 - a rejected request may end as a protocol error
            texts.append(f"{type(exc).__name__}: {exc}")
            out["mcp_rejected"] = True
        else:
            texts.append(_mcp_text(result))
            documents.append(result.structured_content)
            documents += [_json_or_none(getattr(c, "text", "") or "") for c in result.content]
            out["mcp_rejected"] = bool(result.is_error)

    out["text"] = "\n".join(texts)
    out["input_member"] = any(_has_input_member(d) for d in documents)
    return out


# Feature: publisher, Property 9: Validation errors never echo a submitted value
@SETTINGS
@given(bad=BAD, mode=st.sampled_from(MODES), chunked=st.booleans())
def test_validation_errors_never_echo_a_submitted_value(rig, bad, mode, chunked):
    """**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.7, 7.5, 11.2, 22.2**"""
    host = FakeHost(mini_states())
    rig.holder[0] = host

    seen = rig.loop.run_until_complete(_observe(rig, mode, bad, chunked))

    leaks = len(find_leaks(seen["text"], bad.values + (BOUND_VALUE,)))
    assert leaks == 0, f"{leaks} Leak_Form(s) of a submitted value found (kind {bad.kind})"
    assert not seen["input_member"], f"an `input` member in a response (kind {bad.kind})"
    assert host.factory_calls == 0, f"the Session_Factory was called (kind {bad.kind})"

    # Not vacuous: the request was refused with the code of its kind, on both front ends.
    code = _expected_code(bad.kind)
    assert (seen["status"], seen["code"]) == (_STATUS[code], code), f"kind {bad.kind}"
    if chunked:
        assert not seen["content_length_sent"]
    if bad.arguments is not None:
        assert seen["mcp_rejected"] is True, f"MCP accepted a bad request (kind {bad.kind})"
