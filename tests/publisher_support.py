"""Test support for the publisher: the Fake_Host, the MINI Flow and screen chains.

The Fake_Host is a Session_Factory. Each call returns a ``HostSession`` built on
``ScriptedSession`` (``echo_typing=True``). Screens come only from
``tests/flow_support.py`` helpers (the ``captures/*.readbuffer.txt`` files). Nothing
here starts a subprocess, opens a socket or writes a file, and no credential
appears anywhere: tests supply their own Probe_Values.

Failure injection and blocking
    ``Failure(at, ...)`` raises at the factory, at ``open``, at the n-th call of a
    Session method, or at ``close``. ``block_read=n`` makes the n-th ``read_screen``
    wait until ``abort()`` (which raises ``SessionClosedError`` in the blocked
    call) or ``HostSession.release()`` (the call then continues normally).

Counting rules
    ``created``: sessions the factory returned. ``opened``: sessions whose ``open``
    succeeded. ``closed`` and ``aborted``: sessions with at least one ``close`` or
    ``abort`` call (a ``close`` that raises an injected failure still counts as
    closed). ``live``: created and not closed. ``close_calls`` and ``abort_calls``
    count every call, so a double close is visible.
"""
from __future__ import annotations

import contextlib
import itertools
import logging
import threading
import traceback
import types
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from greenscreen.connector import (
    ConfigurationError,
    ConnectorTimeoutError,
    ParseError,
    S3270Error,
    SessionClosedError,
)
from greenscreen.connector.models import Screen
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    Flow,
    InputSpec,
    KeyStep,
    OutputSpec,
    TypeStep,
)

from tests.flow_support import (
    ScriptedSession,
    ScriptedState,
    capture,
    pause_variant,
)

SESSION_METHODS: tuple[str, ...] = ("read_screen", "string", "enter", "clear", "pf", "pa")
FAILURE_POINTS: tuple[str, ...] = ("factory", "open", "close") + SESSION_METHODS

_BLOCK_TIMEOUT = 30.0  # a test that forgets to release a blocked call fails instead of hanging


# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

def make_exception(exc: type[BaseException] | BaseException, message: str = "injected") -> BaseException:
    """An exception instance. A class is built with ``message`` (and neutral keywords)."""
    if isinstance(exc, BaseException):
        return exc
    if exc is ConfigurationError:
        return ConfigurationError(message, parameter_name="injected")
    if exc is ConnectorTimeoutError:
        return ConnectorTimeoutError(message, operation="injected", deadline=1.0)
    if exc is ParseError:
        return ParseError(message, raw=message)
    if exc is S3270Error:
        return S3270Error(message, action="injected", data_lines=[message])
    return exc(message)


@dataclass(frozen=True)
class Failure:
    """Raise ``exc`` at ``at``.

    ``at`` is one of ``FAILURE_POINTS``. ``n`` is the 1-based call number of that
    point (per session; for ``factory`` it counts factory calls of the host).
    ``session`` limits the failure to the session with that 1-based creation
    number; ``None`` means every session. ``exc`` is an exception class (built with
    ``message``) or an instance (raised as given, also a ``BaseException``).
    """

    at: str
    exc: type[BaseException] | BaseException = RuntimeError
    n: int = 1
    session: int | None = None
    message: str = "injected"

    def __post_init__(self) -> None:
        if self.at not in FAILURE_POINTS:
            raise ValueError(f"unknown failure point {self.at!r}")
        if type(self.n) is not int or self.n < 1:
            raise ValueError("n must be a positive integer")

    def build(self) -> BaseException:
        return make_exception(self.exc, self.message)


# --------------------------------------------------------------------------
# Event log
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CallEvent:
    """One call, recorded when it starts. ``session`` is the 1-based creation number
    (``None`` for ``factory``). ``seq`` is global and strictly increasing across threads."""

    seq: int
    session: int | None
    method: str  # "factory", "open", "close", "abort" or a Session method
    args: tuple
    thread: int


# --------------------------------------------------------------------------
# HostSession
# --------------------------------------------------------------------------

class HostSession:
    """A fake session. Implements ``open``, ``close``, ``abort`` and the Session protocol."""

    def __init__(
        self,
        host: "FakeHost",
        number: int,
        states: Sequence[ScriptedState | Screen],
        *,
        failures: Sequence[Failure],
        block_read: int | None,
    ) -> None:
        self._host = host
        self.number = number
        self._scripted = ScriptedSession(states, echo_typing=True)
        self._failures = [f for f in failures if f.session in (None, number)]
        self._block_read = block_read
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._opened = False
        self._closed = False
        self._aborted = False
        self._wake = threading.Event()
        self.blocked = threading.Event()  # set while a read_screen waits
        self.abort_calls = 0
        self.close_calls = 0

    # -- inspection --
    @property
    def calls(self) -> list[tuple]:
        """The calls that reached the scripted session (typing and keys, reads)."""
        return list(self._scripted.calls)

    @property
    def is_aborted(self) -> bool:
        return self._aborted

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def is_opened(self) -> bool:
        return self._opened

    def release(self) -> None:
        """Let a blocked ``read_screen`` continue normally (it raises if aborted)."""
        self._wake.set()

    # -- internals --
    def _begin(self, method: str, args: tuple = ()) -> int:
        self._host._record(self.number, method, args)
        with self._lock:
            n = self._counts.get(method, 0) + 1
            self._counts[method] = n
        return n

    def _inject(self, method: str, n: int) -> None:
        for f in self._failures:
            if f.at == method and f.n == n:
                raise f.build()

    def _require_usable(self) -> None:
        if self._aborted:
            raise SessionClosedError("session aborted")
        if self._closed:
            raise SessionClosedError("session closed")
        if not self._opened:
            raise RuntimeError("session not opened")

    # -- lifecycle --
    def open(self) -> None:
        n = self._begin("open")
        if self._aborted:
            raise SessionClosedError("session aborted")
        if self._closed:
            raise SessionClosedError("session closed")
        if self._opened:
            raise RuntimeError("session already opened")
        self._inject("open", n)
        self._opened = True
        self._host._count("opened")

    def close(self) -> None:
        n = self._begin("close")
        with self._lock:
            first = not self._closed
            self._closed = True
            self.close_calls += 1
        self._host._count("close_calls")
        if first:
            self._host._count("closed")
        self._inject("close", n)

    def abort(self) -> None:
        """Thread-safe and idempotent. Releases a blocked call, which then raises."""
        self._begin("abort")
        with self._lock:
            first = not self._aborted
            self._aborted = True
            self.abort_calls += 1
        self._host._count("abort_calls")
        if first:
            self._host._count("aborted")
        self._wake.set()

    # -- Session protocol --
    def _call(self, method: str, args: tuple, action: Callable[[], Any]) -> Any:
        n = self._begin(method, args)
        self._require_usable()
        self._inject(method, n)
        return action()

    def read_screen(self) -> Screen:
        n = self._begin("read_screen")
        self._require_usable()
        self._inject("read_screen", n)
        if self._block_read is not None and n == self._block_read:
            self.blocked.set()
            if not self._wake.wait(_BLOCK_TIMEOUT):
                raise AssertionError("blocked read_screen was never released")
            if self._aborted:
                raise SessionClosedError("session aborted")
        return self._scripted.read_screen()

    def string(self, text: str) -> None:
        self._call("string", (text,), lambda: self._scripted.string(text))

    def enter(self) -> None:
        self._call("enter", (), self._scripted.enter)

    def clear(self) -> None:
        self._call("clear", (), self._scripted.clear)

    def pf(self, n: int) -> None:
        self._call("pf", (n,), lambda: self._scripted.pf(n))

    def pa(self, n: int) -> None:
        self._call("pa", (n,), lambda: self._scripted.pa(n))


# --------------------------------------------------------------------------
# FakeHost (the Session_Factory)
# --------------------------------------------------------------------------

class FakeHost:
    """A Session_Factory: ``host()`` returns a new ``HostSession``.

    ``script`` is a list of states, or a callable that gets the 1-based session
    number and returns the states for that session.
    """

    def __init__(
        self,
        script: Sequence[ScriptedState | Screen] | Callable[[int], Sequence[ScriptedState | Screen]],
        *,
        failures: Sequence[Failure] = (),
        block_read: int | None = None,
    ) -> None:
        self._script = script
        self._failures = tuple(failures)
        self._block_read = block_read
        self._lock = threading.Lock()
        self._seq = itertools.count(1)
        self._counters = {
            "factory_calls": 0,
            "created": 0,
            "opened": 0,
            "closed": 0,
            "aborted": 0,
            "close_calls": 0,
            "abort_calls": 0,
        }
        self.sessions: list[HostSession] = []
        self.events: list[CallEvent] = []

    # -- internals (called by HostSession) --
    def _record(self, session: int | None, method: str, args: tuple) -> None:
        with self._lock:
            self.events.append(
                CallEvent(next(self._seq), session, method, args, threading.get_ident())
            )

    def _count(self, name: str) -> None:
        with self._lock:
            self._counters[name] += 1

    # -- counters --
    @property
    def factory_calls(self) -> int:
        return self._counters["factory_calls"]

    @property
    def created(self) -> int:
        return self._counters["created"]

    @property
    def opened(self) -> int:
        return self._counters["opened"]

    @property
    def closed(self) -> int:
        return self._counters["closed"]

    @property
    def aborted(self) -> int:
        return self._counters["aborted"]

    @property
    def close_calls(self) -> int:
        return self._counters["close_calls"]

    @property
    def abort_calls(self) -> int:
        return self._counters["abort_calls"]

    @property
    def live(self) -> int:
        """Sessions created and not yet closed."""
        with self._lock:
            return sum(1 for s in self.sessions if not s.is_closed)

    # -- factory --
    def __call__(self) -> HostSession:
        self._record(None, "factory", ())
        with self._lock:
            self._counters["factory_calls"] += 1
            n = self._counters["factory_calls"]
        for f in self._failures:
            if f.at == "factory" and f.n == n:
                raise f.build()
        with self._lock:
            number = self._counters["created"] + 1
        states = self._script(number) if callable(self._script) else self._script
        session = HostSession(
            self, number, states, failures=self._failures, block_read=self._block_read
        )
        with self._lock:
            self._counters["created"] += 1
            self.sessions.append(session)
        return session

    def release_all(self) -> None:
        """Release every blocked read (test cleanup)."""
        for s in list(self.sessions):
            s.release()

    # -- inspection --
    def events_for(self, session: int) -> list[CallEvent]:
        with self._lock:
            return [e for e in self.events if e.session == session]


# --------------------------------------------------------------------------
# The MINI Flow and screen chains
# --------------------------------------------------------------------------

MINI = Flow(
    name="mini",
    description="Type the user id at the logon screen and read the release from the ISPF menu.",
    inputs=(
        InputSpec("userid", "str", True, 8),
        InputSpec("password", "str", False, 8, None, True),
        InputSpec("count", "int", False, 4),
    ),
    outputs=(OutputSpec("RELEASE", "str", "ispf-primary-menu", 10, 71, 8),),
    steps=(
        ExpectStep(("tk5-logon",)),
        TypeStep(input="userid"),
        KeyStep("enter"),
        ExpectStep(("ispf-primary-menu",)),
        ExtractStep("RELEASE"),
    ),
)


def mini_states() -> list[ScriptedState]:
    """Script for ``MINI``: the logon screen, then the ISPF primary menu."""
    return [ScriptedState(capture("tk5-logon")), ScriptedState(capture("ispf-primary-menu"))]


def system_info_states() -> list[ScriptedState]:
    """Script for the bundled ``tk5-system-info`` Flow, a whole run to the logoff.

    Logon, password prompt, one ``***`` pause, ISPF menu, READY, logon again. The Flow
    advances the script with Enter at each of the five transitions.
    """
    return [
        ScriptedState(capture("tk5-logon")),
        ScriptedState(capture("tso-password-prompt")),
        ScriptedState(pause_variant(0)),
        ScriptedState(capture("ispf-primary-menu")),
        ScriptedState(capture("tso-ready")),
        ScriptedState(capture("tk5-logon")),
    ]


# --------------------------------------------------------------------------
# LogCapture (task 7.1)
# --------------------------------------------------------------------------

_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("n", 0, "p", 0, "m", (), None).__dict__
) | {"message", "asctime"}


@dataclass(frozen=True)
class CapturedRecord:
    """One log record, copied as text so that the record object is not kept alive.

    ``fields`` holds the non-standard attributes (the ``extra`` of the call), which is
    where the Call_Log_Record carries its members.
    """

    logger: str
    level: int
    message: str
    args: tuple[str, ...]  # str() and repr() of every element of record.args
    exc_text: str | None
    stack_info: str | None
    exc_info_text: str | None
    fields: dict[str, Any] = field(default_factory=dict)

    def texts(self) -> list[str]:
        """Every string that can carry a value: message, args, exc and stack text, fields."""
        out = [self.message, *self.args]
        out += [t for t in (self.exc_text, self.stack_info, self.exc_info_text) if t]
        for key, value in self.fields.items():
            out += [str(key), str(value), repr(value)]
        return out


def _copy_record(record: logging.LogRecord) -> CapturedRecord:
    try:
        message = record.getMessage()
    except Exception:  # a bad format call must not hide the record
        message = f"<unformattable> {record.msg!r}"
    raw_args = record.args
    if isinstance(raw_args, dict):
        elements: list[Any] = list(raw_args.values())
    elif isinstance(raw_args, tuple):
        elements = list(raw_args)
    else:
        elements = [] if raw_args is None else [raw_args]
    args = tuple(t for a in elements for t in (str(a), repr(a)))
    exc_info_text = None
    if record.exc_info and record.exc_info[0] is not None:
        exc_info_text = "".join(traceback.format_exception(*record.exc_info))
    fields = {k: v for k, v in record.__dict__.items() if k not in _STANDARD_RECORD_ATTRS}
    return CapturedRecord(
        record.name, record.levelno, message, args, record.exc_text, record.stack_info,
        exc_info_text, fields,
    )


class _Recorder(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=1)
        self.records: list[CapturedRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(_copy_record(record))


class LogCapture:
    """Record every log record of every logger at level 1 (below DEBUG).

    The root logger gets the level and a recording handler. A record of a logger with
    ``propagate = False`` never reaches the root handler, so the same handler is also
    attached to each such logger found in ``logging.root.manager.loggerDict``. Call
    ``refresh()`` after ``build_app`` (or anything that creates loggers) to attach to
    loggers created since ``__enter__``. Loggers with their own level (the clamp of
    ``limit_third_party_loggers``) keep it, as in production.
    """

    def __init__(self) -> None:
        self._handler = _Recorder()
        self._attached: list[logging.Logger] = []
        self._root_level = logging.NOTSET

    def __enter__(self) -> "LogCapture":
        root = logging.getLogger()
        self._root_level = root.level
        root.setLevel(1)
        root.addHandler(self._handler)
        self._attached = [root]
        self.refresh()
        return self

    def __exit__(self, *exc_info: object) -> None:
        for logger in self._attached:
            logger.removeHandler(self._handler)
        self._attached = []
        logging.getLogger().setLevel(self._root_level)

    def refresh(self) -> None:
        """Attach to every non-propagating logger that exists now (idempotent)."""
        for logger in list(logging.root.manager.loggerDict.values()):
            if (
                isinstance(logger, logging.Logger)
                and not logger.propagate
                and logger not in self._attached
            ):
                logger.addHandler(self._handler)
                self._attached.append(logger)

    @property
    def records(self) -> list[CapturedRecord]:
        return list(self._handler.records)

    def texts(self) -> list[str]:
        return [t for r in self.records for t in r.texts()]

    def call_records(self) -> list[CapturedRecord]:
        """The Call_Log_Records of the publisher."""
        return [
            r for r in self.records
            if r.logger == "greenscreen.publisher" and r.message == "call finished"
        ]

    def find(self, forms: Iterable[str]) -> list[str]:
        """Descriptions (logger and level, never the text) of records holding any form."""
        wanted = [f for f in forms if f]
        hits: list[str] = []
        for r in self.records:
            if any(f in t for t in r.texts() for f in wanted):
                hits.append(f"{r.logger} level={r.level}")
        return hits


# --------------------------------------------------------------------------
# Frame scanner (Property 10)
# --------------------------------------------------------------------------

_SCAN_DEPTH = 4
_OPAQUE_NAMES = frozenset({"BoundValues", "PublishedFlow"})
_SKIP_TYPES = (types.ModuleType, type, types.FunctionType, types.BuiltinFunctionType,
               types.MethodType, types.CodeType, types.FrameType, types.TracebackType)


def _holds_probe(value: object, probes: Sequence[Any]) -> bool:
    if isinstance(value, str):
        return any(isinstance(p, str) and p in value for p in probes)
    if isinstance(value, (bytes, bytearray)):
        return any(isinstance(p, str) and p.encode("utf-8") in bytes(value) for p in probes)
    if type(value) is int:
        return any(type(p) is int and p == value for p in probes)
    return False


def _scan_value(
    value: object, probes: Sequence[Any], mappings: Sequence[object], depth: int,
    seen: set[int], path: str, out: list[str],
) -> None:
    if any(value is m for m in mappings):
        out.append(f"{path}: the mapping given to run_flow")
        return
    if _holds_probe(value, probes):
        out.append(f"{path}: a probe value")
        return
    if isinstance(value, Screen):
        out.append(f"{path}: a Screen")
        return
    if depth <= 0 or isinstance(value, _SKIP_TYPES) or id(value) in seen:
        return
    if type(value).__name__ in _OPAQUE_NAMES:
        return
    seen.add(id(value))
    kids: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for k, v in list(value.items()):
            kids += [("key", k), (f"[{k!r}]" if isinstance(k, str) and len(k) < 20 else "[..]", v)]
    elif isinstance(value, (list, tuple, set, frozenset)):
        kids = [(f"[{i}]", v) for i, v in enumerate(list(value))]
    else:
        module = getattr(type(value), "__module__", "") or ""
        if not module.startswith(("greenscreen", "tests")):
            return  # third-party and stdlib objects: only plain containers are walked
        for klass in type(value).__mro__:
            for slot in getattr(klass, "__slots__", ()) or ():
                if isinstance(slot, str) and hasattr(value, slot):
                    kids.append((f".{slot}", getattr(value, slot)))
        kids += [(f".{k}", v) for k, v in list(getattr(value, "__dict__", {}).items())]
    for label, kid in kids:
        _scan_value(kid, probes, mappings, depth - 1, seen, f"{path}{label}", out)


def _chain(err: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    todo = [err]
    while todo:
        e = todo.pop()
        if e is None or any(e is o for o in out):
            continue
        out.append(e)
        todo += [e.__cause__, e.__context__]  # type: ignore[list-item]
    return out


def scan_frames(
    err: BaseException, probes: Iterable[Any], *, mappings: Iterable[object] = ()
) -> list[str]:
    """Findings for every frame of ``greenscreen.publisher`` in ``err`` and its chain.

    A finding names the module, the function, the local and the kind of hit, never the
    value. ``probes`` are strings or ints. ``mappings`` are the objects handed to
    ``run_flow``; a local that IS one of them (identity) is flagged. A ``BoundValues``
    and a ``PublishedFlow`` are opaque: they are the permitted long-lived holders. A
    ``Screen`` is flagged wherever it is found. Objects are walked only when their
    class lives in ``greenscreen`` or ``tests`` (plus dict, list, tuple, set, frozenset),
    to depth 4, so a scan stays cheap.
    """
    wanted = [p for p in probes if p is not None and not isinstance(p, bool)]
    held = list(mappings)
    out: list[str] = []
    for e in _chain(err):
        for frame, _lineno in traceback.walk_tb(e.__traceback__):
            module = str(frame.f_globals.get("__name__", ""))
            if not module.startswith("greenscreen.publisher"):
                continue
            where = f"{module}.{frame.f_code.co_name}"
            seen: set[int] = set()
            for name, value in list(frame.f_locals.items()):
                _scan_value(value, wanted, held, _SCAN_DEPTH, seen, f"{where} local {name}", out)
    return out


def formatted_traceback(err: BaseException) -> str:
    """``"".join(traceback.format_exception(err))``, which follows the chain."""
    return "".join(traceback.format_exception(err))


# --------------------------------------------------------------------------
# Clients
# --------------------------------------------------------------------------

MCP_MODES: tuple[str, ...] = ("legacy", "auto")


@contextlib.asynccontextmanager
async def rest_client(
    app: Any, *, headers: dict[str, str] | None = None, base_url: str = "http://test"
) -> AsyncIterator[Any]:
    """An ``httpx2.AsyncClient`` on the ASGI app, inside the lifespan of ``app``.

    ``app`` is a ``PublisherApp`` (``app.asgi``, ``app.lifespan()``).
    """
    import httpx2

    async with app.lifespan():
        transport = httpx2.ASGITransport(app=app.asgi)
        async with httpx2.AsyncClient(
            transport=transport, base_url=base_url, headers=headers
        ) as client:
            yield client


@contextlib.asynccontextmanager
async def mcp_client(app: Any, mode: str = "auto") -> AsyncIterator[Any]:
    """The in-memory MCP ``Client`` on ``app.server``. ``mode`` is ``legacy`` or ``auto``."""
    from mcp import Client

    async with Client(app.server, mode=mode) as client:
        yield client


@contextlib.asynccontextmanager
async def mcp_http_client(http: Any, mode: str = "auto", base: str = "http://test") -> AsyncIterator[Any]:
    """An MCP ``Client`` over Streamable HTTP through an open ``httpx2`` client."""
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client

    async with Client(streamable_http_client(f"{base}/mcp", http_client=http), mode=mode) as client:
        yield client
