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

import itertools
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
