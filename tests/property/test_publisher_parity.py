"""Property 3: both front ends return the same body, and a success body fits its schema.

The app is built once per module (one registry, one event loop, one REST client, two MCP
clients). Each example swaps in a new Fake_Host through a holder, calls the Flow once over
REST and once over MCP, and compares. Input values are made-up Probe_Values, no credential.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.calls import HTTP_STATUS
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from tests.flow_support import FakeClock
from tests.property._publisher_strategies import SETTINGS, fake_host_plans, find_leaks, probes
from tests.publisher_support import MINI, mcp_client, mini_states, FakeHost, rest_client

KEY = "k" * 16
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": KEY,
    "GS_PUBLISH_FLOWS": "tk5-system-info",
}
AUDIT_MEMBERS = {"step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds"}


class _Rig:
    def __init__(self) -> None:
        prepared = prepare(ENV)
        registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
        prepared = dataclasses.replace(prepared, registry=registry)
        self.published = registry["mini"]
        self.holder: list[FakeHost] = [FakeHost(mini_states())]
        self.app = build_app(
            prepared, session_factory=lambda: self.holder[0](), clock=FakeClock(), poll_interval=0.01
        )
        self.loop = asyncio.new_event_loop()
        # the contexts must be entered and exited by one task, so one task owns them
        self.loop.run_until_complete(self._start())
        self.validator = Draft202012Validator(self.published.success_schema)

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
                    m: await stack.enter_async_context(mcp_client(self.app, m))
                    for m in ("legacy", "auto")
                }
                self.ready.set()
                await self.stop.wait()
        finally:
            self.ready.set()

    def call(self, plan, mode, arguments):
        async def both():
            self.holder[0] = plan.build()
            r = await self.rest.post("/flows/mini", json=arguments)
            self.holder[0] = plan.build()
            m = await self.mcp[mode].call_tool("mini", arguments)
            return r, m

        return self.loop.run_until_complete(both())

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


# Every screen a call can put into a response body (the unexpected_screen error carries row
# text). A probe integer whose decimal text occurs in one of them (for example `TERMINAL : 3277`
# on the ISPF menu capture) would be reported by find_leaks although nothing leaked, so the
# strategy leaves such integers out. A real leak is still found: any other value is unchanged.
_SCREEN_TEXT = "\n".join(
    "\n".join(state.screen.text_grid) for state in mini_states()
)


def _arguments():
    return st.tuples(
        probes("str", max_size=8),
        st.one_of(st.none(), probes("str", max_size=8)),
        st.one_of(st.none(), probes("int", max_size=4).filter(lambda n: str(n) not in _SCREEN_TEXT)),
    ).map(
        lambda t: {
            k: v for k, v in (("userid", t[0]), ("password", t[1]), ("count", t[2])) if v is not None
        }
    )


# Feature: publisher, Property 3: Both front ends return the same body, and a success body fits its schema
@SETTINGS
@given(plan=fake_host_plans(), mode=st.sampled_from(("legacy", "auto")), arguments=_arguments())
def test_front_ends_agree_and_success_fits_schema(rig, plan, mode, arguments):
    """**Validates: Requirements 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 11.1, 11.7, 14.2, 14.7**"""
    resp, res = rig.call(plan, mode, arguments)
    rest_body = resp.json()
    mcp_body = res.structured_content

    # same body through both envelopes
    assert rest_body == mcp_body
    assert json.loads(res.content[0].text) == mcp_body
    assert len(res.content) == 1

    if resp.status_code == 200:
        assert res.is_error is False
        assert set(rest_body) == {"flow", "outputs", "audit"}
        assert rest_body["flow"] == "mini"
        assert list(rest_body["outputs"]) == [o.name for o in MINI.outputs]
        assert rig.validator.is_valid(rest_body)
        assert rest_body["audit"] and all(set(e) == AUDIT_MEMBERS for e in rest_body["audit"])
        assert "summary" not in rest_body
    else:
        assert res.is_error is True
        code = rest_body["error"]["code"]
        assert resp.status_code == HTTP_STATUS[code]

    assert find_leaks(resp.text + res.content[0].text, arguments.values()) == []
