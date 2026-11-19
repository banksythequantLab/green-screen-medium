"""Shared test helpers for the Ask tests (spec ask, task 2.9).

Nothing here starts a subprocess, opens a real connection or writes a file. Keys and
Bound_Values are generated at run time and never written anywhere. The helpers of
``tests/publisher_support.py``, ``tests/console_support.py`` and
``tests/property/_publisher_strategies.py`` are reused by the Ask tests, not copied.

Contents
    ``AskFakeClock``          ``monotonic()``, async ``sleep()``, settable ``now``, ``utcnow()``
    ``Turn``, ``Fail``        the scripted items of the fake adapter
    ``FakeAdapter``           an async context manager yielding itself; records everything
    ``PortStep``, ``FakePort``  a ``ToolPort`` with scripted results and durations
    ``ARGUMENT_CASES``        hostile argument texts, with the Rejected_Call reason each earns
    ``hostile_*``             hostile generators (Hypothesis strategies)
    ``build_ask_app``         a publisher app with Ask on, over a Fake_Host and a fake adapter
    ``ask_post``              one ``POST /ask`` over a raw ASGI scope
    ``no_network``            the autouse fixture that blocks every outbound connection

``no_network`` is autouse only in a module that imports it by name::

    from tests.ask_support import no_network  # noqa: F401  (autouse)

``ToolInfo`` and ``ToolResult`` live in ``greenscreen.publisher.ask.agent``. They are
imported when a helper needs them, so this module can be imported before that module
exists and so that a test that never builds a port does not load the agent.
"""
from __future__ import annotations

import asyncio
import copy
import dataclasses
import functools
import ipaddress
import json
import secrets
import socket
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from hypothesis import strategies as st

from greenscreen.publisher.app import PublisherApp, build_app, prepare
from greenscreen.publisher.ask.adapter import ModelError, ModelTurn, ToolCallRequest
from tests.console_support import BASE_ENV, call_scope
from tests.flow_support import FakeClock
from tests.publisher_support import FakeHost, system_info_states

FLOW = "tk5-system-info"
UNPUBLISHED_FLOW = "tk5-logon"

# The one bound pair of ``build_ask_app``: the password of ``tk5-system-info``. Generated
# once per process (8 characters, the Input's maximum), never written anywhere.
BOUND_PASSWORD: str = secrets.token_hex(4)
_BOUND_VARIABLE = "GS_BIND_" + "TK5_SYSTEM_INFO__PASSWORD"


def _agent() -> Any:
    from greenscreen.publisher.ask import agent

    return agent


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------

class AskFakeClock:
    """A monotonic clock and a wall clock under test control.

    ``now`` is the monotonic reading (settable, starts at 0.0). ``sleep(s)`` is async,
    adds exactly ``s`` and returns at once; every call is kept in ``sleeps``. ``utcnow()``
    is the aware UTC wall clock for the Daily_Budget; set ``utc`` to move it.
    """

    def __init__(
        self,
        now: float = 0.0,
        utc: datetime | None = None,
    ) -> None:
        self.now = float(now)
        self.utc = utc if utc is not None else datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc)
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        """Move both clocks forward by ``seconds``."""
        self.now += float(seconds)
        self.utc += timedelta(seconds=float(seconds))

    def utcnow(self) -> datetime:
        return self.utc


# --------------------------------------------------------------------------
# FakeAdapter
# --------------------------------------------------------------------------

CallSpec = ToolCallRequest | tuple[str, str]


@dataclass(frozen=True)
class Turn:
    """One scripted reply: ``answer`` text, or ``calls`` (a tool turn).

    A call is a ``ToolCallRequest`` or a ``(name, arguments_text)`` pair; the pair gets an
    id ``call_<n>`` that is unique within the question. ``seconds`` is how long the turn
    takes on the clock.
    """

    answer: str | None = None
    calls: tuple[CallSpec, ...] = ()
    seconds: float = 0.0


@dataclass(frozen=True)
class Fail:
    """One scripted failure: ``ModelError(kind)`` after ``seconds``."""

    kind: str
    seconds: float = 0.0


ScriptItem = Turn | Fail | ModelTurn | Callable[[list[dict], list[dict]], "ScriptItem"]


class FakeAdapter:
    """A model adapter that returns scripted replies and records what it is given.

    ``script`` is a sequence of ``Turn``, ``Fail``, ``ModelTurn`` or a callable
    ``(messages, tools) -> item``, used one per ``complete`` call. When the script is
    used up the adapter raises ``ModelError("unusable")`` and sets ``exhausted``.

    ``received`` holds, per call, ``json.dumps({"messages", "tools"}, sort_keys=True)`` of
    exactly what the adapter was given (so a later change to the lists cannot hide a
    leak). ``timeouts`` holds each ``timeout_seconds``. With a ``clock`` the clock moves
    by the item's ``seconds`` before the reply or the failure. The adapter is an async
    context manager that yields itself, so ``build_app(model_adapter=adapter)`` can wrap
    it in ``nullcontext`` or use it directly.
    """

    def __init__(
        self,
        script: Iterable[ScriptItem] = (),
        *,
        clock: AskFakeClock | None = None,
    ) -> None:
        self._script = list(script)
        self._clock = clock
        self._position = 0
        self._ids = 0
        self.received: list[str] = []
        self.timeouts: list[float] = []
        self.exhausted = False
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> "FakeAdapter":
        self.entered += 1
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.exited += 1

    @property
    def calls(self) -> int:
        return len(self.received)

    def _call_id(self) -> str:
        self._ids += 1
        return f"call_{self._ids}"

    def _build(self, item: Turn) -> ModelTurn:
        calls = []
        for spec in item.calls:
            if isinstance(spec, ToolCallRequest):
                calls.append(spec)
            else:
                name, text = spec
                calls.append(ToolCallRequest(self._call_id(), name, text))
        return ModelTurn(item.answer, tuple(calls))

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_seconds: float,
    ) -> ModelTurn:
        self.received.append(json.dumps({"messages": messages, "tools": tools}, sort_keys=True))
        self.timeouts.append(timeout_seconds)
        if self._position >= len(self._script):
            self.exhausted = True
            raise ModelError("unusable")
        item = self._script[self._position]
        self._position += 1
        if callable(item) and not isinstance(item, (Turn, Fail, ModelTurn)):
            item = item(copy.deepcopy(messages), copy.deepcopy(tools))
        seconds = getattr(item, "seconds", 0.0)
        if self._clock is not None and seconds:
            self._clock.advance(seconds)
        if isinstance(item, Fail):
            raise ModelError(item.kind)
        if isinstance(item, ModelTurn):
            return item
        return self._build(item)


# --------------------------------------------------------------------------
# FakePort
# --------------------------------------------------------------------------

def ok_result(flow: str = FLOW, outputs: Mapping[str, Any] | None = None) -> Any:
    """A successful ``ToolResult`` shaped like the one ``McpToolPort`` builds."""
    body = {"flow": flow, "outputs": dict(outputs or {}), "audit": []}
    return _agent().ToolResult("ok", body)


def error_result(code: str, message: str = "scripted error") -> Any:
    """A tool error ``ToolResult``: ``{"error": {"code", "message"}}`` with that code."""
    return _agent().ToolResult(code, {"error": {"code": code, "message": message}})


@dataclass(frozen=True)
class PortStep:
    """One scripted tool result and how long the call takes on the clock."""

    result: Any
    seconds: float = 0.0


def tool_info(
    name: str = FLOW,
    *,
    properties: Mapping[str, Any] | None = None,
    description: str = "A scripted tool.",
    secret: bool = False,
) -> Any:
    """A ``ToolInfo`` with an object schema that rejects unknown names."""
    props = dict(properties if properties is not None else {"userid": {"type": "string"}})
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    return _agent().ToolInfo(name, description, schema, secret=secret)


class FakePort:
    """A ``ToolPort`` with scripted results and durations.

    ``tools`` is a list of ``ToolInfo`` (default: one tool named ``tk5-system-info``).
    ``results`` maps a tool name to a ``ToolResult``, a ``PortStep``, a callable
    ``(name, arguments) -> ToolResult | PortStep``, or a list of those. A list is used in
    order and its last element repeats. A tool with no entry answers ``ok_result(name)``.
    With a ``clock`` the clock moves by the step's ``seconds`` while the call is awaited.

    ``called`` records ``(name, arguments)`` with a deep copy of the arguments taken before
    the call (the real port empties the dict it is given), so a test sees what was sent.
    """

    def __init__(
        self,
        tools: Sequence[Any] | None = None,
        results: Mapping[str, Any] | None = None,
        *,
        clock: AskFakeClock | None = None,
    ) -> None:
        self._tools = list(tools) if tools is not None else [tool_info()]
        self._results = dict(results or {})
        self._clock = clock
        self._used: dict[str, int] = {}
        self.called: list[tuple[str, dict]] = []
        self.listed = 0

    async def list_tools(self) -> list[Any]:
        self.listed += 1
        return list(self._tools)

    def _next(self, name: str, arguments: dict) -> PortStep:
        entry = self._results.get(name)
        if isinstance(entry, (list, tuple)) and not isinstance(entry, PortStep):
            index = self._used.get(name, 0)
            self._used[name] = index + 1
            entry = entry[min(index, len(entry) - 1)]
        if callable(entry) and not isinstance(entry, PortStep):
            entry = entry(name, arguments)
        if entry is None:
            entry = ok_result(name)
        if not isinstance(entry, PortStep):
            entry = PortStep(entry)
        return entry

    async def call(self, name: str, arguments: dict) -> Any:
        self.called.append((name, copy.deepcopy(arguments)))
        step = self._next(name, arguments)
        if self._clock is not None and step.seconds:
            self._clock.advance(step.seconds)
        await asyncio.sleep(0)  # a real port awaits; keep the call a real suspension point
        return step.result


# --------------------------------------------------------------------------
# Hostile generators
# --------------------------------------------------------------------------

# Argument texts a hostile model can send. The value is the reason the agent must give
# (``REJECT_REASONS`` name), or ``None`` when the text is acceptable to the agent (it is
# then ``CallService``'s turn to validate it).
_HUGE = '{"userid": "' + "q" * 5000 + '"}'
_DEEP = '{"userid": {"a": {"b": {"c": {"d": {"e": 1}}}}}}'
_RECURSION = "[" * 2000 + "]" * 2000  # under 4 096 characters, deeper than the parser allows


def hostile_argument_text(kind: str, *, value: str = "zq", bound_name: str = "password") -> str:
    """The argument text of one hostile ``kind`` (a key of ``ARGUMENT_CASES``)."""
    texts = {
        "valid": json.dumps({"userid": value}),
        "empty": "",
        "blank": "  \t\n ",
        "empty_object": "{}",
        "huge": _HUGE,
        "deep": _DEEP,
        "recursion": _RECURSION,
        "duplicate_key": '{"userid": "a", "userid": "b"}',
        "nan": '{"userid": NaN}',
        "infinity": '{"userid": -Infinity}',
        "not_json": '{"userid": ',
        "null": "null",
        "list": "[]",
        "string": '"userid"',
        "number": "1",
        "true": "true",
        "bound_input": json.dumps({bound_name: value}),
        "unknown_name": '{"nope": 1}',
        "extra_name": json.dumps({"userid": value, "extra": 1}),
    }
    return texts[kind]


ARGUMENT_CASES: dict[str, str | None] = {
    "valid": None,
    "empty": None,  # empty or blank text means {} (Decision 26)
    "blank": None,
    "empty_object": None,
    "huge": "arguments_too_large",
    "deep": "arguments_too_deep",
    "recursion": "arguments_too_deep",
    "duplicate_key": "arguments_not_json",
    "nan": "arguments_not_json",
    "infinity": "arguments_not_json",
    "not_json": "arguments_not_json",
    "null": "arguments_not_object",
    "list": "arguments_not_object",
    "string": "arguments_not_object",
    "number": "arguments_not_object",
    "true": "arguments_not_object",
    "bound_input": "unknown_argument",
    "unknown_name": "unknown_argument",
    "extra_name": "unknown_argument",
}

UNKNOWN_TOOL_NAMES: tuple[str, ...] = (
    "nope",
    "",
    " ",
    "TK5-SYSTEM-INFO",
    "tk5-system-info ",
    "tk5_system_info",
    "../etc/passwd",
    "x" * 200,
    "tk5-system-info\n",
)


def hostile_argument_texts(
    *, kinds: Sequence[str] | None = None, value: str = "zq", bound_name: str = "password"
) -> st.SearchStrategy[str]:
    """Argument texts drawn from ``ARGUMENT_CASES`` (all kinds, or ``kinds``)."""
    chosen = tuple(kinds) if kinds is not None else tuple(ARGUMENT_CASES)
    return st.sampled_from(chosen).map(
        lambda k: hostile_argument_text(k, value=value, bound_name=bound_name)
    )


def hostile_tool_names(
    offered: Sequence[str] = (FLOW,),
    *,
    unpublished: Sequence[str] = (UNPUBLISHED_FLOW,),
    ineligible: Sequence[str] = (),
    unknown: Sequence[str] = UNKNOWN_TOOL_NAMES,
) -> st.SearchStrategy[str]:
    """Tool names: the offered ones, Loaded but unpublished Flows, ineligible Flows
    (for instance one with a Secret_Input) and names that exist nowhere."""
    return st.sampled_from(tuple(offered) + tuple(unpublished) + tuple(ineligible) + tuple(unknown))


def hostile_calls(
    offered: Sequence[str] = (FLOW,),
    *,
    unpublished: Sequence[str] = (UNPUBLISHED_FLOW,),
    ineligible: Sequence[str] = (),
    unknown: Sequence[str] = UNKNOWN_TOOL_NAMES,
    min_calls: int = 1,
    max_calls: int = 4,
    value: str = "zq",
    bound_name: str = "password",
) -> st.SearchStrategy[tuple[tuple[str, str], ...]]:
    """One turn of ``min_calls`` to ``max_calls`` ``(name, arguments_text)`` pairs.

    Several calls in one turn and repeated names both occur (the list may hold the same
    pair twice). Pass the result to ``Turn(calls=...)``.
    """
    call = st.tuples(
        hostile_tool_names(offered, unpublished=unpublished, ineligible=ineligible, unknown=unknown),
        hostile_argument_texts(value=value, bound_name=bound_name),
    )
    return st.lists(call, min_size=min_calls, max_size=max_calls).map(tuple)


HUGE_ANSWER = "a" * 30000  # over the largest GS_ASK_MAX_ANSWER_CHARS (20 000)
CONTROL_ANSWER = "ok\x00\x07\x1b[31m\x7f\u2028\r\nend"
_ANSWER_ALPHABET = st.characters(blacklist_categories=("Cs",))


def hostile_answers() -> st.SearchStrategy[str]:
    """Final answers: ordinary text, control characters, very long text, odd Unicode."""
    return st.one_of(
        st.just(HUGE_ANSWER),
        st.just(CONTROL_ANSWER),
        st.text(_ANSWER_ALPHABET, min_size=1, max_size=300).filter(lambda t: t.strip() != ""),
        st.integers(2001, 25000).map(lambda n: "w" * n),
    )


# --------------------------------------------------------------------------
# build_ask_app and ask_post
# --------------------------------------------------------------------------

ASK_ENV: dict[str, str] = {
    **BASE_ENV,
    "GS_ENABLE_ASK": "true",
    "GS_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
    "GS_LLM_MODEL": "fake-model",
    # C = GS_CALL_TIMEOUT + 10 = 50; C + 2M = 90 fits GS_ASK_TIMEOUT_SECONDS 95.
    "GS_CALL_TIMEOUT": "40",
    "GS_ASK_TIMEOUT_SECONDS": "95",
    "GS_ASK_MODEL_TIMEOUT_SECONDS": "20",
}

_PLACEHOLDER_KEY = "k" * 16


@dataclass(frozen=True)
class AskApp:
    """An app with Ask on, the API key it accepts, and the fakes behind it."""

    app: PublisherApp
    api_key: str
    host: FakeHost
    adapter: FakeAdapter
    clock: AskFakeClock


@functools.lru_cache(maxsize=16)
def _prepared(items: tuple[tuple[str, str], ...]):
    return prepare(dict(items))


def build_ask_app(
    env: Mapping[str, str] | None = None,
    adapter: Any = None,
    host: FakeHost | None = None,
    clock: AskFakeClock | None = None,
    utcnow: Callable[[], datetime] | None = None,
) -> AskApp:
    """Build the publisher app with Ask on, over a Fake_Host and a model double.

    ``env`` is merged over ``ASK_ENV`` (one published Flow, ``tk5-system-info``, with its
    password bound to a per-process generated value; ``GS_CALL_TIMEOUT`` 40; model URL on
    a loopback address, never contacted). ``GS_API_KEY`` is replaced by a key generated
    for this call; an ``env`` value for it is ignored. ``prepare`` runs once per distinct
    environment (``functools.lru_cache``); its result is immutable, so each call builds a
    new app on a copy whose settings carry the generated key.

    ``adapter`` defaults to an empty ``FakeAdapter``; ``host`` to a Fake_Host that plays a
    whole ``tk5-system-info`` run; ``clock`` to an ``AskFakeClock`` (given to the app as
    ``ask_clock``); ``utcnow`` to ``clock.utcnow``. The Fake_Host is driven by its own
    ``FakeClock``, so a Flow run does not move the Ask clock.
    """
    ask_clock = clock if clock is not None else AskFakeClock()
    model = adapter if adapter is not None else FakeAdapter((), clock=ask_clock)
    fake_host = host if host is not None else FakeHost(system_info_states())
    merged = {
        **ASK_ENV,
        _BOUND_VARIABLE: BOUND_PASSWORD,
        **(env or {}),
        "GS_API_KEY": _PLACEHOLDER_KEY,
    }
    prepared = _prepared(tuple(sorted(merged.items())))
    api_key = secrets.token_urlsafe(24)
    settings = prepared.settings
    if settings.transport != "stdio":
        settings = dataclasses.replace(settings, api_key=api_key)
    prepared = dataclasses.replace(prepared, settings=settings)
    app = build_app(
        prepared,
        session_factory=fake_host,
        clock=FakeClock(),
        poll_interval=0.01,
        model_adapter=model,
        ask_clock=ask_clock,
        ask_utcnow=utcnow if utcnow is not None else ask_clock.utcnow,
    )
    return AskApp(app, api_key, fake_host, model, ask_clock)


@dataclass(frozen=True)
class AskReply:
    """The answer to one ``POST /ask``: status, lower-case header names, raw body."""

    status: int
    headers: dict[str, str]
    raw: bytes

    def json(self) -> Any:
        return json.loads(self.raw)


async def ask_post(
    app: AskApp | PublisherApp,
    question: Any,
    key: str | None = None,
    *,
    body: bytes | None = None,
    content_type: str | None = "application/json",
    headers: Mapping[str, str] | None = None,
    timeout: float = 20.0,
) -> AskReply:
    """``POST /ask`` through the whole ASGI stack with a raw scope.

    ``question`` goes into ``{"question": question}``. ``key`` defaults to the key of an
    ``AskApp``; pass ``""`` to send no key header. ``body`` replaces the encoded body
    (for body-rule tests), ``content_type=None`` sends no ``Content-Type``, and
    ``headers`` adds or overrides headers. Wrap the call in ``app.app.lifespan()`` when the
    test needs the shutdown drain.
    """
    asgi_app = app.app if isinstance(app, AskApp) else app
    if key is None and isinstance(app, AskApp):
        key = app.api_key
    sent: dict[str, str] = {}
    if key:
        sent["X-API-Key"] = key
    if content_type is not None:
        sent["Content-Type"] = content_type
    sent.update(headers or {})
    payload = body if body is not None else json.dumps({"question": question}).encode("utf-8")
    status, raw_headers, data = await call_scope(
        asgi_app.asgi, "POST", "/ask", sent, body=payload, timeout=timeout
    )
    return AskReply(
        status,
        {k.decode("latin-1"): v.decode("latin-1") for k, v in raw_headers},
        data,
    )


# --------------------------------------------------------------------------
# no_network
# --------------------------------------------------------------------------

class NetworkGuard:
    """What the ``no_network`` fixture saw.

    ``attempts`` holds one text per blocked attempt: the kind and the host, never a
    payload. ``loopback_connects`` counts the allowed loopback ``connect`` calls (the
    event loop's own self-pipe makes one on Windows). A test that needs the attempt to
    happen (the one guard test) calls ``expect_attempts()``; any other test with a record
    fails at teardown.
    """

    def __init__(self) -> None:
        self.attempts: list[str] = []
        self.loopback_connects = 0
        self.expected = False

    def expect_attempts(self) -> None:
        self.expected = True

    def record(self, kind: str, target: Any) -> None:
        host = target[0] if isinstance(target, tuple) and target else target
        self.attempts.append(f"{kind} {host!s}")

    def kinds(self) -> list[str]:
        return [a.split(" ", 1)[0] for a in self.attempts]


def _host_of(address: Any) -> str | None:
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
        return host if isinstance(host, str) else None
    return None


def _is_loopback_literal(host: str | None) -> bool:
    """True for a literal loopback IP address. A name is never allowed (it needs a lookup)."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool((mapped or ip).is_loopback)


def _blocked(guard: NetworkGuard, kind: str, target: Any) -> OSError:
    guard.record(kind, target)
    return OSError(f"network access blocked by the no_network fixture ({kind})")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch):
    """Block every outbound connection except ``connect`` to a loopback IP literal.

    Patches ``socket.socket.connect`` and ``connect_ex`` (loopback IP literals and Unix
    sockets pass; anything else is recorded and raises ``OSError``), ``socket.getaddrinfo``,
    ``socket.gethostbyname``, ``socket.create_connection`` and, on the event-loop classes,
    ``getaddrinfo``, ``create_connection``, ``create_datagram_endpoint`` and
    ``sock_connect`` (the last passes loopback literals). It yields a ``NetworkGuard``.
    A record fails the test at teardown unless the test called ``expect_attempts()``.
    """
    import asyncio.base_events as base_events
    import asyncio.proactor_events as proactor_events
    import asyncio.selector_events as selector_events

    guard = NetworkGuard()
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def _check(self: socket.socket, address: Any, kind: str) -> bool:
        if getattr(socket, "AF_UNIX", None) is not None and self.family == socket.AF_UNIX:
            return True
        if _is_loopback_literal(_host_of(address)):
            guard.loopback_connects += 1
            return True
        guard.record(kind, address)
        return False

    def connect(self: socket.socket, address: Any) -> None:
        if not _check(self, address, "connect"):
            raise OSError("network access blocked by the no_network fixture (connect)")
        return real_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        if not _check(self, address, "connect_ex"):
            return 10061  # WSAECONNREFUSED-like; also a plain nonzero errno elsewhere
        return real_connect_ex(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        raise _blocked(guard, "getaddrinfo", host)

    def gethostbyname(host: Any) -> Any:
        raise _blocked(guard, "gethostbyname", host)

    def create_connection(address: Any, *args: Any, **kwargs: Any) -> Any:
        raise _blocked(guard, "create_connection", address)

    async def loop_getaddrinfo(self: Any, host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        raise _blocked(guard, "loop.getaddrinfo", host)

    async def loop_create_connection(self: Any, factory: Any, host: Any = None, *args: Any, **kwargs: Any) -> Any:
        raise _blocked(guard, "loop.create_connection", host)

    async def loop_create_datagram_endpoint(self: Any, factory: Any, *args: Any, **kwargs: Any) -> Any:
        raise _blocked(guard, "loop.create_datagram_endpoint", kwargs.get("remote_addr"))

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(socket, "gethostbyname", gethostbyname)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(base_events.BaseEventLoop, "getaddrinfo", loop_getaddrinfo)
    monkeypatch.setattr(base_events.BaseEventLoop, "create_connection", loop_create_connection)
    monkeypatch.setattr(
        base_events.BaseEventLoop, "create_datagram_endpoint", loop_create_datagram_endpoint
    )
    for cls in (selector_events.BaseSelectorEventLoop, proactor_events.BaseProactorEventLoop):
        real_sock_connect = cls.sock_connect

        def make(real: Any) -> Any:
            async def sock_connect(self: Any, sock: Any, address: Any) -> Any:
                if _is_loopback_literal(_host_of(address)):
                    guard.loopback_connects += 1
                    return await real(self, sock, address)
                raise _blocked(guard, "loop.sock_connect", address)

            return sock_connect

        monkeypatch.setattr(cls, "sock_connect", make(real_sock_connect))

    yield guard

    monkeypatch.undo()
    if guard.attempts and not guard.expected:
        pytest.fail(
            "the test tried to reach the network: " + "; ".join(guard.attempts[:5]),
            pytrace=False,
        )
