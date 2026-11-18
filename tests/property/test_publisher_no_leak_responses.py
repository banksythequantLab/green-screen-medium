"""Property 5: no Input value and no Bound_Value in any response (task 8.1).

One app per set of bound Input names (at most eight for the ``MINI`` Flow, built lazily and
kept for the module), one event loop, one REST client and two MCP clients per app. The
registry holds ``MINI`` and two Flows that type a password into the password prompt and
then meet a screen whose hidden cells still hold that password (``sentinel_password_screen``,
in memory only). Each example swaps a new Fake_Host and the Bound_Values of the example
into the app, then observes every response channel: the REST body and headers, the MCP
result in both modes, ``/openapi.json``, ``tools/list`` and ``/health``.

The swappable ``BoundValues`` is a test-local subclass; the values in it are a real
``BoundValues`` object. All values are made-up Probe_Values, no credential.
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

from greenscreen.flow.errors import REASON_CODES, FlowError, FlowInputError
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    Flow,
    InputSpec,
    KeyStep,
    OutputSpec,
    Timeouts,
    TypeStep,
)
from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from tests import flow_support
from tests.flow_support import FakeClock, ScriptedState, capture, sentinel_password_screen
from tests.property._publisher_strategies import (
    SETTINGS,
    BadRequest,
    HostPlan,
    bad_requests,
    bound_sets,
    fake_host_plans,
    find_leaks,
    probes,
)
from tests.publisher_support import (
    MINI,
    Failure,
    FakeHost,
    mcp_client,
    rest_client,
)

KEY = "k" * 16
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": KEY,
    "GS_PUBLISH_FLOWS": "tk5-logon",
    "GS_MAX_BODY_BYTES": "2048",
}
_PROMPT = "tso-password-prompt"
_PW = InputSpec("pw", "str", True, 8, None, True)
_TIMEOUTS = Timeouts(0.5, 60.0, 10.0)
_TYPED = (ExpectStep((_PROMPT,)), TypeStep(input="pw"), KeyStep("enter"))
PW_STOP = Flow(
    name="pw-stop", description="Type a password, then expect a pause that never comes.",
    inputs=(_PW,), steps=_TYPED + (ExpectStep(("tso-pause",)),), timeouts=_TIMEOUTS,
)
PW_HIDDEN = Flow(
    name="pw-hidden", description="Type a password, then read the hidden field back.",
    inputs=(_PW,), outputs=(OutputSpec("PW", "str", _PROMPT, 1, 1, 8),),
    steps=_TYPED + (ExpectStep((_PROMPT,)), ExtractStep("PW")), timeouts=_TIMEOUTS,
)
FLOWS = {"mini": MINI, "pw-stop": PW_STOP, "pw-hidden": PW_HIDDEN}
TARGETS = ("mini", "mini", "pw-stop", "pw-hidden")
MODES = ("legacy", "auto")


# --------------------------------------------------------------------------
# The rig
# --------------------------------------------------------------------------


class _SwapBound(BoundValues):
    """``BoundValues`` whose values can be replaced per example. The names are fixed at
    build time, because the registry builds its schemas from them."""

    def __init__(self, names: frozenset[str]) -> None:
        super().__init__()
        self._fixed = names
        self.current = BoundValues()

    def for_flow(self, flow_name):
        return self.current.for_flow(flow_name)

    def names_for(self, flow_name):
        return self._fixed if flow_name == "mini" else frozenset()


@functools.lru_cache(maxsize=1)
def _base_prepared():
    return prepare(ENV)


class _Rig:
    def __init__(self, loop: asyncio.AbstractEventLoop, names: frozenset[str]) -> None:
        self.loop = loop
        self.bound = _SwapBound(names)
        registry = build_registry({n: (f, "test") for n, f in FLOWS.items()}, self.bound, 30.0)
        prepared = dataclasses.replace(_base_prepared(), registry=registry, bound=self.bound)
        self.holder: list = [FakeHost([])]
        self.app = build_app(
            prepared, session_factory=lambda: self.holder[0](), clock=FakeClock(), poll_interval=0.01
        )
        loop.run_until_complete(self._start())

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


class _Rigs:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.rigs: dict[frozenset[str], _Rig] = {}

    def get(self, names: frozenset[str]) -> _Rig:
        if names not in self.rigs:
            self.rigs[names] = _Rig(self.loop, names)
        return self.rigs[names]

    def close(self) -> None:
        for rig in self.rigs.values():
            rig.close()
        self.loop.close()


@pytest.fixture(scope="module")
def rigs():
    r = _Rigs()
    yield r
    r.close()


# --------------------------------------------------------------------------
# Strategies (local)
# --------------------------------------------------------------------------

_CAPTURES_TEXT = flow_support._captures_text()  # read once; the sentinel must not occur in it


def _numbers_in(node) -> set:
    """Every number (not bool) found by walking a JSON-like structure."""
    if isinstance(node, bool):
        return set()
    if isinstance(node, (int, float)):
        return {node}
    if isinstance(node, dict):
        return set().union(set(), *(_numbers_in(v) for v in node.values()))
    if isinstance(node, (list, tuple)):
        return set().union(set(), *(_numbers_in(v) for v in node))
    return set()


@functools.lru_cache(maxsize=1)
def _schema_constants() -> tuple[str, ...]:
    """The text of every number in the schemas of every Flow of the registry, with and
    without bound Inputs. Derived from the generator, never hard-coded."""
    from greenscreen.publisher.registry import build_schemas

    found: set = set()
    for flow in FLOWS.values():
        names = [s.name for s in flow.inputs]
        for bound in (frozenset(), *(frozenset({n}) for n in names)):
            found |= _numbers_in(build_schemas(flow, bound))
    return tuple(sorted(str(n) for n in found))


def _collides(probe) -> bool:
    """A probe collides when its text occurs inside the text of a schema constant, so the
    constant legitimately present in ``/openapi.json`` would contain the probe."""
    return any(str(probe) in c for c in _schema_constants())


def _clear_of_constants(*values) -> bool:
    return not any(_collides(v) for v in values)


def _bound_sets_clear():
    return bound_sets().filter(lambda b: _clear_of_constants(*b.values))


def _bad_clear():
    return bad_requests(2048).filter(lambda r: _clear_of_constants(*r.values))


def _sentinels() -> st.SearchStrategy[str]:
    return probes("str", max_size=8).filter(lambda s: s not in _CAPTURES_TEXT)


def _flow_error_plans() -> st.SearchStrategy[HostPlan]:
    def build(reason: str, at: str, kind: int) -> HostPlan:
        exc = (
            FlowInputError("userid", "type") if kind == 1
            else FlowError(reason, step_index=2, kind="expect", expected=("b", "a"),
                           summary=None, audit=())
        )
        return HostPlan(False, Failure(at, exc, 1))

    return st.builds(
        build, st.sampled_from(REASON_CODES), st.sampled_from(("read_screen", "string", "enter")),
        st.integers(0, 2),
    )


PLANS = st.one_of(fake_host_plans(), _flow_error_plans())
BAD = st.one_of(st.none(), st.none(), _bad_clear())


def _host(target: str, plan: HostPlan, sentinel: str) -> FakeHost:
    if target == "mini":
        return plan.build()
    states = [ScriptedState(capture(_PROMPT)), ScriptedState(sentinel_password_screen(sentinel))]
    if plan.wrong_screens:
        states.reverse()
    return FakeHost(states, failures=(plan.failure,) if plan.failure else ())


# --------------------------------------------------------------------------
# Observation
# --------------------------------------------------------------------------


def _rest_text(resp) -> str:
    headers = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
    return f"{resp.status_code}\n{headers}\n{resp.text}"


def _mcp_text(result) -> str:
    parts = [result.model_dump_json(), repr(result)]
    parts += [json.dumps(result.structured_content, default=str)]
    parts += [getattr(c, "text", "") or "" for c in result.content]
    return "\n".join(parts)


def _tools_text(listing) -> str:
    return "\n".join(t.model_dump_json() + repr(t) for t in listing.tools)


async def _observe(rig: _Rig, mode: str, target: str, args: dict, bad: BadRequest | None, host_factory):
    texts: list[str] = []
    rig.holder[0] = host_factory()
    if bad is not None:
        resp = await rig.rest.post(
            "/flows/mini", content=bad.body, headers={"Content-Type": bad.content_type}
        )
    else:
        resp = await rig.rest.post(f"/flows/{target}", json=args)
    texts.append(_rest_text(resp))
    mcp_status = None
    if bad is None or bad.arguments is not None:
        rig.holder[0] = host_factory()
        margs = args if bad is None else bad.arguments
        try:
            result = await rig.mcp[mode].call_tool(target if bad is None else "mini", margs)
        except Exception as exc:  # noqa: BLE001 - only a rejected bad request may end here
            if bad is None:
                raise
            texts.append(f"{type(exc).__name__}: {exc}")
        else:
            texts.append(_mcp_text(result))
            mcp_status = result.is_error
    texts.append(_rest_text(await rig.rest.get("/openapi.json")))
    texts.append(_rest_text(await rig.rest.get("/health")))
    texts.append(_tools_text(await rig.mcp[mode].list_tools()))
    return resp.status_code, mcp_status, "\n".join(texts)


# Feature: publisher, Property 5: No Input value or Bound_Value in any response
@SETTINGS
@given(
    bs=_bound_sets_clear(),
    plan=PLANS,
    target=st.sampled_from(TARGETS),
    mode=st.sampled_from(MODES),
    sentinel=_sentinels(),
    bad=BAD,
)
def test_no_input_value_or_bound_value_in_any_response(rigs, bs, plan, target, mode, sentinel, bad):
    """**Validates: Requirements 7.1, 7.7, 7.8, 7.9, 22.10**"""
    rig = rigs.get(frozenset(bs.bound))
    rig.bound.current = BoundValues({"mini": dict(bs.bound)} if bs.bound else None)
    if target == "mini":
        args, bad_used = dict(bs.supplied), bad
        values: tuple = bs.values + (bad.values if bad else ())
    else:
        args, bad_used = {"pw": sentinel}, None
        values = bs.values + (sentinel,)

    status, mcp_error, text = rig.loop.run_until_complete(
        _observe(rig, mode, target, args, bad_used, lambda: _host(target, plan, sentinel))
    )

    leaks = len(find_leaks(text, values))
    assert leaks == 0, f"{leaks} Leak_Form(s) of a Probe_Value found in a response"

    # The check is not vacuous: a clean valid call to MINI succeeds on both front ends.
    if target == "mini" and bad_used is None and plan.failure is None and not plan.wrong_screens:
        assert status == 200 and mcp_error is False


# --------------------------------------------------------------------------
# Helper tests: no probe can equal a schema constant
# --------------------------------------------------------------------------


def test_schema_constants_are_derived_and_include_the_mini_bounds():
    consts = _schema_constants()
    from greenscreen.publisher.registry import build_schemas

    bounds = _numbers_in(build_schemas(MINI)[0]["properties"]["count"])
    assert bounds and {str(n) for n in bounds} <= set(consts)


def test_the_stored_collision_is_rejected_and_a_clean_probe_is_not():
    assert _collides(9999) and not _collides(4711)
    assert all(not _collides(v) for v in ("~^!#", "abcd"))


def test_stored_9999_collision_is_real_in_openapi_and_the_helper_excludes_it(rigs):
    """The old failing example (count=9999 on mini) stays covered even if Hypothesis no
    longer replays it: the unfiltered leak check does fire on ``/openapi.json`` (the
    constant is legitimate there), and the helper rejects 9999 as a probe."""
    rig = rigs.get(frozenset())
    rig.bound.current = BoundValues()
    args = {"userid": "~^!#", "count": 9999}
    status, mcp_error, text = rig.loop.run_until_complete(
        _observe(rig, "auto", "mini", args, None, HostPlan().build)
    )
    assert status == 200 and mcp_error is False
    assert find_leaks(text, (9999,)), "the schema constant 9999 is expected in the responses"
    assert "9999" in _schema_constants() and _collides(9999)
    assert not _clear_of_constants(9999)
    assert _clear_of_constants(4711)


@SETTINGS
@given(bs=_bound_sets_clear(), bad=BAD)
def test_strategies_never_produce_the_stored_9999_probe(bs, bad):
    values = bs.values + (bad.values if bad else ())
    assert all(str(v) != "9999" for v in values)


@SETTINGS
@given(bs=_bound_sets_clear(), bad=BAD)
def test_no_probe_the_strategies_produce_equals_a_schema_constant(bs, bad):
    values = bs.values + (bad.values if bad else ())
    constants = set(_schema_constants())
    assert not {str(v) for v in values} & constants
    assert _clear_of_constants(*values)
