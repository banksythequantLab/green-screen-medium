"""Property 8: audit entries and summaries are free of secrets and mask hidden cells (task 8.4).

One app is built for the module and served by one long-lived event loop on a helper
thread. Each example picks a scenario (a Flow, a Fake_Host script of real capture screens
or a failure injected at a Session call) and probe values, makes one Call over REST and
one over MCP, and checks every ``audit`` list and every ``summary`` object of the two
answers:

* no Leak_Form (plain, JSON-escaped, URL-quoted, hex, base64, ...) of the user id, of the
  password or of the Bound_Value occurs in them;
* in every summary, every data cell of every hidden field is ``*`` in ``row_text``.

Scenarios stop with each Reason_Code that real screens can produce (``timeout``,
``run_timeout``, ``unknown_screen``, ``loop_limit``, ``bad_target``, ``secret_target``,
``hidden_output``, ``output_type``, ``session_error``) and with ``input_invalid``. The
three codes that the bundled screens cannot produce (``ambiguous_screen``,
``unexpected_screen``, ``screen_size``) are raised by the Fake_Host as a ``FlowError``
that carries a real Redacted_Summary of the residual-password screen. The residual
password is the password supplied by the Call (``sentinel_password_screen``), in a
screen that follows the password Enter.

Probes never occur in a capture or in the fixed answer text (see ``_clean``). No
credential is used. A failure message names the place and the kind of hit, never a value.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import threading

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from greenscreen.connector import S3270Error
from greenscreen.flow.errors import REASON_CODES, FlowError
from greenscreen.flow.model import (
    AuditRecord,
    ExpectStep,
    ExtractStep,
    Flow,
    HandleStep,
    InputSpec,
    KeyStep,
    OutputSpec,
    Timeouts,
    TypeStep,
)
from greenscreen.publisher.app import build_app, prepare
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from greenscreen.recognizer import load_bundled_signatures
from greenscreen.recognizer.summary import build_summary
from greenscreen.recognizer.view import ScreenView
from tests.flow_support import (
    FakeClock,
    ScriptedState,
    blank_screen,
    capture,
    pause_variant,
    sentinel_password_screen,
    _captures_text,
)
from tests.property._publisher_strategies import all_leak_forms, probes
from tests.publisher_support import (
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
}
HEADERS = {"X-API-Key": KEY}

# The Bound_Value of every "-b" Flow: a made-up password (symbols only), checked against
# the captures below.
BOUND_PASSWORD = "~^!#=&%@;"[:8]
AUDIT_KEYS = {"step_index", "kind", "phase", "iteration", "signature", "status", "duration_seconds"}

# --------------------------------------------------------------------------
# Flows (local): every one declares the same two Inputs
# --------------------------------------------------------------------------

INPUTS = (
    InputSpec("userid", "str", True, 8),
    InputSpec("password", "str", True, 8, None, True),
)
_RELEASE = OutputSpec("RELEASE", "str", "ispf-primary-menu", 10, 71, 8)

_LOGON = (
    ExpectStep(("tk5-logon",)),
    TypeStep(input="userid"),
    KeyStep("enter"),
    ExpectStep(("tso-password-prompt",)),
    TypeStep(input="password"),
    KeyStep("enter"),
)


def _flow(name: str, steps, outputs=(), timeouts: Timeouts | None = None) -> Flow:
    kwargs = {"timeouts": timeouts or Timeouts(step=0.5, run=60.0, finally_=1.0)}
    return Flow(name=name, steps=tuple(steps), inputs=INPUTS, outputs=outputs, **kwargs)


BASE_FLOWS: dict[str, Flow] = {
    "login": _flow("login", (*_LOGON, ExpectStep(("ispf-primary-menu",)), ExtractStep("RELEASE")),
                   (_RELEASE,)),
    "slowrun": _flow("slowrun", (*_LOGON, ExpectStep(("ispf-primary-menu",)), ExtractStep("RELEASE")),
                     (_RELEASE,), Timeouts(step=60.0, run=1.0, finally_=1.0)),
    "loop": _flow("loop", (*_LOGON, HandleStep("tso-pause", 1, (KeyStep("enter"),)),
                           ExpectStep(("ispf-primary-menu",)), ExtractStep("RELEASE")),
                  (_RELEASE,)),
    "badtarget": _flow("badtarget", (ExpectStep(("tk5-logo",)), TypeStep(input="userid"),
                                     KeyStep("enter"))),
    "secrettarget": _flow("secrettarget", (ExpectStep(("tk5-logon",)), TypeStep(input="password"),
                                           KeyStep("enter"))),
    "hiddenout": _flow("hiddenout", (ExpectStep(("tso-password-prompt",)), ExtractStep("OUT")),
                       (OutputSpec("OUT", "str", "tso-password-prompt", 1, 0, 8),)),
    "outtype": _flow("outtype", (ExpectStep(("ispf-primary-menu",)), ExtractStep("REL")),
                     (OutputSpec("REL", "int", "ispf-primary-menu", 10, 71, 8),)),
}


def _bound_variant(flow: Flow) -> Flow:
    return dataclasses.replace(flow, name=flow.name + "-b")


FLOWS: dict[str, Flow] = {}
for _name, _flow_ in BASE_FLOWS.items():
    FLOWS[_name] = _flow_
    FLOWS[_name + "-b"] = _bound_variant(_flow_)

# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------

L, P, I, PAUSE = "tk5-logon", "tso-password-prompt", "ispf-primary-menu", "pause"


def _injected(code: str, pw: str) -> FlowError:
    """A FlowError with a real Redacted_Summary of the residual-password screen."""
    summary = build_summary(ScreenView(sentinel_password_screen(pw)))
    audit = (AuditRecord(0, "expect", "steps", None, "tk5-logon", "ok", 0.01),
             AuditRecord(1, "type", "steps", None, None, "failed", 0.02))
    return FlowError(code, step_index=1, kind="type", expected=("tk5-logon",),
                     summary=summary, audit=audit)


@dataclasses.dataclass(frozen=True)
class Scenario:
    flow: str
    code: str  # the expected Reason_Code or "ok" or "input_invalid"
    screens: tuple[str, ...] = ()
    failure_at: str | None = None  # a Session call that raises (S3270Error or FlowError)
    inject: str | None = None  # a Reason_Code raised as a FlowError at read_screen


def _scenarios() -> tuple[Scenario, ...]:
    return (
        Scenario("login", "ok", (L, P, I)),
        Scenario("login", "timeout", (L, P, "residual")),
        Scenario("login", "unknown_screen", (L, P, "blank")),
        Scenario("login", "session_error", (L, P, I), failure_at="string"),
        Scenario("login", "input_invalid", (L, P, I)),
        Scenario("slowrun", "run_timeout", (L, P, "residual")),
        Scenario("loop", "loop_limit", (L, P, "pause1", "pause2", "pause3")),
        Scenario("badtarget", "bad_target", ("tk5-logo",)),
        Scenario("secrettarget", "secret_target", (L,)),
        Scenario("hiddenout", "hidden_output", ("residual",)),
        Scenario("outtype", "output_type", (I,)),
        Scenario("login", "ambiguous_screen", ("residual",), inject="ambiguous_screen"),
        Scenario("login", "unexpected_screen", ("residual",), inject="unexpected_screen"),
        Scenario("login", "screen_size", ("residual",), inject="screen_size"),
    )


SCENARIOS = _scenarios()
REACHABLE_BY_SCREENS = {s.code for s in SCENARIOS if s.inject is None}
assert {s.code for s in SCENARIOS} - {"ok", "input_invalid"} == set(REASON_CODES) - {"input_invalid"}


def _screen(token: str, pw: str):
    if token == "residual":
        return sentinel_password_screen(pw)
    if token == "blank":
        return blank_screen()
    if token.startswith("pause"):
        return pause_variant(int(token[5:] or 0))
    return capture(token)


def _host(s: Scenario, pw: str) -> FakeHost:
    states = [ScriptedState(_screen(t, pw)) for t in s.screens]
    failures: tuple[Failure, ...] = ()
    if s.failure_at is not None:
        failures = (Failure(s.failure_at, S3270Error, 1),)
    if s.inject is not None:
        failures = (Failure("read_screen", _injected(s.inject, pw), 1),)
    return FakeHost(states, failures=failures)


# --------------------------------------------------------------------------
# Probes: never part of a capture or of the fixed answer text
# --------------------------------------------------------------------------

_FIXED = "\n".join((
    _captures_text(),
    " ".join(s.name for s in load_bundled_signatures()),
    " ".join(AUDIT_KEYS), "expect type key extract handle steps finally ok skipped failed",
    " ".join(REASON_CODES), "rows columns cursor field_count unprotected_count hidden_count fields",
    "start_row start_col byte_length protected hidden row_text",
    "true false null step_index kind expected summary audit code message error",
))
assert not any(f in _FIXED for f in all_leak_forms([BOUND_PASSWORD])), "Bound_Value occurs in fixed text"


def _clean(value: str) -> bool:
    return not any(f in _FIXED for f in all_leak_forms([value]))


USERIDS = probes("str", min_size=4, max_size=8).filter(_clean)
PASSWORDS = probes("str", min_size=4, max_size=8).filter(_clean)
LONG_USERIDS = probes("str", min_size=9, max_size=12).filter(_clean)


@dataclasses.dataclass(frozen=True)
class Draw:
    scenario: Scenario
    bound: bool
    userid: str
    password: str


@st.composite
def draws(draw) -> Draw:
    scn = draw(st.sampled_from(SCENARIOS))
    userid = draw(LONG_USERIDS if scn.code == "input_invalid" else USERIDS)
    return Draw(scn, draw(st.booleans()), userid, draw(PASSWORDS))


# --------------------------------------------------------------------------
# The module app: built once, served by one loop on a helper thread
# --------------------------------------------------------------------------

class _Served:
    def __init__(self) -> None:
        self.current: FakeHost | None = None
        prepared = prepare(ENV)
        bound = BoundValues({n: {"password": BOUND_PASSWORD} for n in FLOWS if n.endswith("-b")})
        registry = build_registry({n: (f, "test") for n, f in FLOWS.items()}, bound, 30.0)
        prepared = dataclasses.replace(prepared, registry=registry, bound=bound)
        self.app = build_app(
            prepared, session_factory=self._factory, clock=FakeClock(), poll_interval=0.1
        )
        self.loop = asyncio.new_event_loop()
        self.http = None
        self.mcp = None
        self._ready = threading.Event()
        self._failed: BaseException | None = None
        self._stop: asyncio.Event | None = None
        self._thread = threading.Thread(target=self._run, name="audit-loop", daemon=True)

    def _factory(self):
        assert self.current is not None
        return self.current()

    async def _driver(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with rest_client(self.app, headers=HEADERS) as http, \
                    mcp_client(self.app, "auto") as mcp:
                self.http, self.mcp = http, mcp
                self._ready.set()
                await self._stop.wait()
        except BaseException as err:  # noqa: BLE001 - reported to the starting thread
            self._failed = err
            self._ready.set()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._driver())

    def start(self) -> None:
        self._thread.start()
        assert self._ready.wait(30), "app did not start"
        assert self._failed is None, f"app failed to start: {type(self._failed).__name__}"

    def stop(self) -> None:
        if self._stop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(30)

    def run(self, coro, timeout: float = 60.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)


@pytest.fixture(scope="module")
def served():
    s = _Served()
    s.start()
    try:
        yield s
    finally:
        s.stop()


async def _call(served: _Served, name: str, args: dict):
    resp = await served.http.post(f"/flows/{name}", json=args)
    result = await asyncio.wait_for(served.mcp.call_tool(name, args), 30)
    return resp.status_code, resp.json(), result.is_error, result.structured_content


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------

def _hidden_problems(summary: dict) -> list[str]:
    """Hidden data cells that are not ``*`` in ``row_text`` (positions only)."""
    rows, cols = summary["rows"], summary["columns"]
    text = summary["row_text"]
    bad: list[str] = []
    if len(text) != rows:
        bad.append(f"row_text has {len(text)} rows, not {rows}")
    total = rows * cols
    for f in summary["fields"]:
        if not f["hidden"]:
            continue
        start = f["start_row"] * cols + f["start_col"]
        for offset in range(1, f["byte_length"] + 1):
            r, c = divmod((start + offset) % total, cols)
            row = text[r] if r < len(text) else ""
            if c >= len(row) or row[c] != "*":
                bad.append(f"hidden cell r{r}c{c} is not '*'")
                if len(bad) > 5:
                    return bad
    return bad


def _check_body(label: str, body: dict, forms: tuple[str, ...], expect_summary: bool) -> int:
    """Check the audit and summary of one answer. Returns the number of hidden fields seen."""
    holder = body.get("error", body)
    audit = holder.get("audit")
    summary = holder.get("summary")
    hits: list[str] = []
    assert "outputs" in body or "error" in body
    if audit is not None:
        assert isinstance(audit, list)
        for entry in audit:
            assert set(entry) == AUDIT_KEYS, f"{label}: audit entry members"
    if expect_summary:
        assert isinstance(summary, dict), f"{label}: no summary"
    hidden = 0
    for part, value in (("audit", audit), ("summary", summary)):
        if value is None:
            continue
        text = json.dumps(value, ensure_ascii=False) + json.dumps(value)
        hits += [f"{label} {part}: leak form #{i}" for i, f in enumerate(forms) if f in text]
    if isinstance(summary, dict):
        hits += [f"{label} summary: {p}" for p in _hidden_problems(summary)]
        hidden = sum(1 for f in summary["fields"] if f["hidden"])
        assert hidden == summary["hidden_count"], f"{label}: hidden_count"
    assert not hits, "; ".join(hits)
    return hidden


def _pinned() -> list:
    """One pinned Draw per scenario (alternating bound), so every code is hit on every run."""
    out = []
    for i, scn in enumerate(SCENARIOS):
        user = "!#%&=" + "+" * (5 if scn.code == "input_invalid" else 0)
        assert _clean(user) and _clean("?@;|")
        out.append(Draw(scn, i % 2 == 1, user, "?@;|"))
    return out


PINNED = _pinned()


@settings(max_examples=100, deadline=None)
@given(draws())
@example(PINNED[0])
@example(PINNED[1])
@example(PINNED[2])
@example(PINNED[3])
@example(PINNED[4])
@example(PINNED[5])
@example(PINNED[6])
@example(PINNED[7])
@example(PINNED[8])
@example(PINNED[9])
@example(PINNED[10])
@example(PINNED[11])
@example(PINNED[12])
@example(PINNED[13])
def test_audit_and_summary_hold_no_secret_and_mask_hidden_cells(served, d):
    # Feature: publisher, Property 8: Audit entries and summaries are free of secrets and mask hidden cells
    scn = d.scenario
    name = scn.flow + ("-b" if d.bound else "")
    args = {"userid": d.userid} if d.bound else {"userid": d.userid, "password": d.password}
    # The residual password is the password the Call holds (the Bound_Value for "-b" Flows).
    pw = BOUND_PASSWORD if d.bound else d.password
    forms = all_leak_forms([d.userid, pw])
    host = _host(scn, pw)
    served.current = host
    try:
        status, body, is_error, structured = served.run(_call(served, name, args))
    finally:
        host.release_all()
        served.current = None

    assert _same(structured, body), "REST and MCP answers differ"
    assert host.closed == host.created and host.live == 0

    if scn.code == "ok":
        assert status == 200 and not is_error and "outputs" in body
    else:
        assert body["error"]["code"] == scn.code, "unexpected code"
        assert is_error
    if scn.code == "input_invalid":
        assert host.created == 0
    # Non-vacuous: a stop on the residual-password screen carries a summary with a hidden field.
    residual = "residual" in scn.screens and scn.code in (
        "timeout", "hidden_output", "ambiguous_screen", "unexpected_screen", "screen_size")
    for label, answer in (("rest", body), ("mcp", structured)):
        hidden = _check_body(label, answer, forms, residual)
        if residual:
            assert hidden >= 1, f"{label}: the residual screen shows no hidden field"

def _same(a: dict, b: dict) -> bool:
    """Equal answers, ignoring the clock-dependent ``duration_seconds``."""
    def strip(x):
        return json.loads(json.dumps(x), object_hook=lambda m: {
            k: v for k, v in m.items() if k != "duration_seconds"})
    return strip(a) == strip(b)
