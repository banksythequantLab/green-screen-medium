"""Call plumbing shared by REST and MCP: limiter, outcome types, error mapping.

Task 2.1 holds the pure parts. Seams for later tasks:

* task 2.2 adds ``CallService`` (worker, deadline, teardown, the Call_Log_Record
  writer) below the marked line;
* task 2.3 adds ``ConnectorSession`` below it as well.

Nothing here reads a value, an exception text or Host_Data. Error bodies are
built from fixed texts and plain data only.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import subprocess
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import anyio
import anyio.to_thread

from greenscreen.connector import Connector, SessionClosedError
from greenscreen.flow import FlowInputError, run_flow
from greenscreen.flow.errors import REASON_CODES, FlowError
from greenscreen.publisher.registry import PublishedFlow, Registry, check_inputs
from greenscreen.publisher.vault import BoundValues, SecretBox

if TYPE_CHECKING:  # pragma: no cover
    from greenscreen.connector import Screen

__all__ = [
    "Session",
    "SessionFactory",
    "PUBLISHER_CODES",
    "ERROR_CODES",
    "LOG_ONLY_OUTCOMES",
    "MESSAGES",
    "HTTP_STATUS",
    "RESPONSE_HEADERS",
    "FLOW_STOP_MEMBERS",
    "Limiter",
    "CallOutcome",
    "error_body",
    "flow_error_data",
    "audit_to_list",
    "CallService",
    "ConnectorSession",
]


class Session(Protocol):
    """The runner's Session protocol plus the lifecycle the Publisher needs."""

    def open(self) -> None: ...
    def read_screen(self) -> Screen: ...
    def string(self, text: str) -> None: ...
    def enter(self) -> None: ...
    def clear(self) -> None: ...
    def pf(self, n: int) -> None: ...
    def pa(self, n: int) -> None: ...
    def close(self) -> None: ...

    def abort(self) -> None:
        """Thread-safe, idempotent; kills the host process without the send path."""
        ...


# Called on the event loop thread; must not block.
SessionFactory = Callable[[], Session]

PUBLISHER_CODES: tuple[str, ...] = (
    "unauthorized",
    "unknown_flow",
    "request_invalid",
    "request_too_large",
    "busy",
    "shutting_down",
    "call_timeout",
    "host_unavailable",
    "internal_error",
)

#: The 22 Error_Codes: 13 Reason_Codes and 9 Publisher_Codes.
ERROR_CODES: frozenset[str] = frozenset(REASON_CODES) | frozenset(PUBLISHER_CODES)

#: Values of a Call_Log_Record ``outcome`` that are never an Error_Code and never
#: appear in a response. Only the log writer of task 2.2 may use them.
LOG_ONLY_OUTCOMES: frozenset[str] = frozenset({"cancelled"})

_RESPONSE_CODES: frozenset[str] = ERROR_CODES | {"ok"}

# Reason_Codes whose Error_Body carries the Flow-stop members (Requirement 6.2).
_FLOW_STOP_CODES: frozenset[str] = frozenset(REASON_CODES) - {"input_invalid"}
FLOW_STOP_MEMBERS: tuple[str, ...] = (
    "step_index",
    "kind",
    "expected",
    "summary",
    "audit",
)

MESSAGES: Mapping[str, str] = {
    # Publisher_Codes
    "unauthorized": "A valid API key is required.",
    "unknown_flow": "No such flow is published.",
    "request_invalid": "The request is not valid.",
    "request_too_large": "The request body is too large.",
    "busy": "All sessions are in use.",
    "shutting_down": "The publisher is shutting down.",
    "call_timeout": "The call did not finish in time.",
    "host_unavailable": "The host session could not be opened.",
    "internal_error": "The publisher failed to run the flow.",
    # Reason_Codes
    "input_invalid": "An input value is not valid.",
    "timeout": "The host was too slow for a step.",
    "run_timeout": "The host was too slow for the whole run.",
    "unknown_screen": "The host showed a screen the flow does not know.",
    "ambiguous_screen": "The host showed a screen that matches more than one signature.",
    "unexpected_screen": "The host showed a known screen the flow did not expect.",
    "loop_limit": "A loop in the flow reached its iteration limit.",
    "bad_target": "A step addressed a field that is not available on the screen.",
    "secret_target": "A step addressed a field that may not receive this input.",
    "hidden_output": "An output would have come from a hidden field.",
    "output_type": "An output value does not have its declared type.",
    "screen_size": "The host screen does not have the expected size.",
    "session_error": "The host session failed during the run.",
}

HTTP_STATUS: Mapping[str, int] = {
    "unauthorized": 401,
    "request_invalid": 400,
    "request_too_large": 413,
    "unknown_flow": 404,
    "input_invalid": 422,
    "busy": 429,
    "shutting_down": 503,
    "host_unavailable": 502,
    "call_timeout": 504,
    "internal_error": 500,
    "timeout": 504,
    "run_timeout": 504,
    "unknown_screen": 502,
    "ambiguous_screen": 502,
    "unexpected_screen": 502,
    "loop_limit": 502,
    "bad_target": 502,
    "secret_target": 502,
    "hidden_output": 502,
    "output_type": 502,
    "screen_size": 502,
    "session_error": 502,
}

#: Extra response headers for a code (REST only).
RESPONSE_HEADERS: Mapping[str, Mapping[str, str]] = {
    "unauthorized": {"WWW-Authenticate": "Bearer"},
    "busy": {"Retry-After": "1"},
}


class Limiter:
    """Calls in flight. Confined to the event loop: no lock, no await inside."""

    __slots__ = ("limit", "in_flight")

    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be an integer of at least 1")
        self.limit = limit
        self.in_flight = 0

    def try_acquire(self) -> bool:
        if self.in_flight >= self.limit:
            return False
        self.in_flight += 1
        return True

    def release(self) -> None:
        if self.in_flight <= 0:
            raise RuntimeError("release without a held slot")
        self.in_flight -= 1


@dataclass(frozen=True, slots=True)
class CallOutcome:
    """What a front end turns into a response. ``code`` is never ``cancelled``."""

    code: str  # "ok" or an Error_Code
    body: dict
    step_index: int | None = None
    close_failed: bool = False
    session_clean: bool | None = None  # False or None; never True (Requirement 23.6)

    def __post_init__(self) -> None:
        if self.code not in _RESPONSE_CODES:
            raise ValueError("code is not 'ok' or an Error_Code")
        if self.session_clean is not None and self.session_clean is not False:
            raise ValueError("session_clean is False or None")


def error_body(code: str, **members: Any) -> dict:
    """Build ``{"error": {"code", "message", ...}}`` from plain data.

    Only a Flow-stop Reason_Code takes the members of ``FLOW_STOP_MEMBERS``.
    ``input_invalid`` takes ``message`` (the text of the ``FlowInputError``).
    Every other code takes no member and always has its fixed message.
    """
    if code not in ERROR_CODES:
        raise ValueError("unknown error code")
    error: dict[str, Any] = {"code": code, "message": MESSAGES[code]}
    allowed: tuple[str, ...]
    if code == "input_invalid":
        allowed = ("message",)
    elif code in _FLOW_STOP_CODES:
        allowed = FLOW_STOP_MEMBERS
    else:
        allowed = ()
    for name in members:
        if name not in allowed:
            raise ValueError("member not allowed for this code")
    if "message" in members:
        error["message"] = members.pop("message")
    error.update(members)
    return {"error": error}


def audit_to_list(audit: Any) -> list[dict]:
    """Audit_Summary: exactly the seven members of an ``AuditRecord``."""
    return [
        {
            "step_index": r.step_index,
            "kind": r.kind,
            "phase": r.phase,
            "iteration": r.iteration,
            "signature": r.signature,
            "status": r.status,
            "duration_seconds": r.duration_seconds,
        }
        for r in audit
    ]


def flow_error_data(exc: FlowError) -> dict:
    """Plain-data copy of a ``FlowError``: reads only the documented members."""
    summary = exc.summary
    return {
        "reason": exc.reason,
        "step_index": exc.step_index,
        "kind": exc.kind,
        "expected": list(exc.expected),
        "summary": None if summary is None else summary.to_dict(),
        "audit": audit_to_list(exc.audit),
    }


# ---------------------------------------------------------------------------
# CallService (task 2.2). Task 2.3 adds ConnectorSession below this block.
# ---------------------------------------------------------------------------

_LOG = logging.getLogger("greenscreen.publisher")
_WORKER_GRACE = 5.0  # seconds to wait for a worker after abort()


class _Guarded:
    """Stops every Session call once the Call has been aborted (Requirement 10.4)."""

    __slots__ = ("_session", "_aborted")

    def __init__(self, session: Session, aborted: threading.Event) -> None:
        self._session = session
        self._aborted = aborted

    def _check(self) -> None:
        if self._aborted.is_set():
            raise SessionClosedError("call aborted")

    def read_screen(self) -> Screen:
        self._check()
        return self._session.read_screen()

    def string(self, text: str) -> None:
        self._check()
        self._session.string(text)

    def enter(self) -> None:
        self._check()
        self._session.enter()

    def clear(self) -> None:
        self._check()
        self._session.clear()

    def pf(self, n: int) -> None:
        self._check()
        self._session.pf(n)

    def pa(self, n: int) -> None:
        self._check()
        self._session.pa(n)


@dataclass(slots=True)
class _Result:
    kind: str = ""  # ok, host_unavailable, input_invalid, flow_error, internal, base
    value: Any = None  # FlowResult, str (input_invalid message) or dict (flow error data)
    base: BaseException | None = None
    close_failed: bool = False


@dataclass(slots=True, eq=False)
class _Run:
    session: Any
    flow: Any
    box: SecretBox
    bound: Mapping[str, Any]
    signatures: Any
    clock: Any
    poll: float
    loop: asyncio.AbstractEventLoop
    done: anyio.Event
    aborted: threading.Event = field(default_factory=threading.Event)
    result: _Result = field(default_factory=_Result)
    abort_reason: str | None = None  # timeout, cancel or shutdown


@dataclass(slots=True)
class _Record:
    """What the one Call_Log_Record writer needs. Holds no value."""

    call_id: str
    flow: str
    transport: str
    outcome: str = "internal_error"  # ResponseCode or a log-only outcome
    step_index: int | None = None
    close_failed: bool = False
    session_clean: bool | None = None


def _store_base(res: _Result, exc: BaseException) -> None:
    """Keep the first BaseException of a run (Requirement 6, criterion 8)."""
    if res.kind != "base":
        res.kind, res.base = "base", exc


def _worker(run: _Run) -> None:
    """The only code that touches the session. No secret is bound to a local name."""
    res = run.result
    try:
        try:
            try:
                run.session.open()
            except Exception:
                res.kind = "host_unavailable"
                return
            try:
                res.value = run_flow(
                    run.flow,
                    _Guarded(run.session, run.aborted),
                    run.box.merged(run.bound),
                    signatures=run.signatures,
                    clock=run.clock,
                    poll_interval=run.poll,
                )
                res.kind = "ok"
            except FlowInputError as exc:
                res.kind, res.value = "input_invalid", str(exc)
            except FlowError as exc:
                res.kind, res.value = "flow_error", flow_error_data(exc)
            except Exception:
                res.kind = "internal"  # no str(), no repr(), no attribute reads
        except Exception:  # raised by a handler above
            if not res.kind:
                res.kind = "internal"
        except BaseException as exc:  # from open, run_flow or a handler above
            _store_base(res, exc)
    finally:
        try:
            run.box.clear()
        except Exception:
            pass  # execute() clears the box again
        except BaseException as exc:
            _store_base(res, exc)
        try:
            try:
                run.session.close()
            except Exception:
                res.close_failed = True
            except BaseException as exc:
                _store_base(res, exc)
        finally:
            try:
                run.loop.call_soon_threadsafe(run.done.set)
            except RuntimeError:  # loop already closed
                pass


def _session_clean(code: str, abort_reason: str | None) -> bool | None:
    """False when the user id may still be logged on; None makes no claim."""
    if code in ("unknown_screen", "call_timeout") or abort_reason in ("cancel", "shutdown"):
        return False
    return None


class CallService:
    """The one call path shared by REST and MCP (Requirement 3)."""

    def __init__(
        self,
        registry: Registry,
        bound: BoundValues,
        signatures: Iterable[Any],
        limiter: Limiter,
        session_factory: SessionFactory,
        *,
        clock: Any = None,
        poll_interval: float = 0.1,
    ) -> None:
        self._registry = registry
        self._bound = bound
        self._signatures = signatures
        self._limiter = limiter
        self._factory = session_factory
        self._clock = clock
        self._poll = poll_interval
        self._runs: set[_Run] = set()
        self.closing = False

    # -- public ----------------------------------------------------------

    def precheck(self, name: str, transport: str = "rest") -> PublishedFlow | CallOutcome:
        """Resolve the Flow. A rejection is logged here, as no ``execute`` follows."""
        t0 = time.monotonic()
        published = self._registry.get(name) if isinstance(name, str) else None
        if self.closing:
            code = "shutting_down"
        elif published is None:
            code = "unknown_flow"
        else:
            return published
        rec = _Record(secrets.token_hex(8), "unknown", transport, outcome=code)
        if code == "shutting_down" and published is not None:
            rec.flow = published.flow.name
        self._write_log(rec, t0)
        return CallOutcome(code, error_body(code))

    def log_rejection(self, flow: str, transport: str, code: str, started: float) -> None:
        """One Call_Log_Record for a request rejected before ``execute`` (Requirement 8.9).

        ``flow`` is the Flow_Name of a published Flow, otherwise ``unknown``. Only
        ``call_id``, ``flow``, ``transport``, ``outcome`` and ``duration_ms`` are written.
        """
        if code not in ERROR_CODES:
            raise ValueError("unknown error code")
        rec = _Record(secrets.token_hex(8), flow, transport, outcome=code)
        self._write_log(rec, started)

    async def execute(
        self, published: PublishedFlow, box: SecretBox, transport: str
    ) -> CallOutcome:
        t0 = time.monotonic()
        rec = _Record(secrets.token_hex(8), published.flow.name, transport)
        try:
            return await self._execute(published, box, rec)
        finally:
            box.clear()
            self._write_log(rec, t0)

    def begin_shutdown(self) -> None:
        self.closing = True

    async def drain(self, grace: float) -> None:
        """Stop new calls, wait up to ``grace`` for calls in flight, tear down the rest."""
        self.begin_shutdown()
        with anyio.move_on_after(grace):
            while self._runs:
                await anyio.sleep(0.02)
        first: BaseException | None = None
        for run in list(self._runs):
            if run.abort_reason is None:
                run.abort_reason = "shutdown"
            with anyio.CancelScope(shield=True):
                pending = await self._teardown(run)
            if first is None:
                first = pending
        with anyio.move_on_after(1.0):  # let the awaiting calls build their answers
            while self._runs:
                await anyio.sleep(0.01)
        if first is not None:
            raise first

    # -- internals -------------------------------------------------------

    async def _execute(
        self, published: PublishedFlow, box: SecretBox, rec: _Record
    ) -> CallOutcome:
        if self.closing:
            rec.outcome = "shutting_down"
            return CallOutcome("shutting_down", error_body("shutting_down"))
        message = check_inputs(published, box)
        if message is not None:
            rec.outcome = "input_invalid"
            return CallOutcome("input_invalid", error_body("input_invalid", message=message))
        if not self._limiter.try_acquire():
            rec.outcome = "busy"
            return CallOutcome("busy", error_body("busy"))

        base: BaseException | None = None
        try:
            outcome, base = await self._run_slot(published, box, rec)
        finally:
            self._limiter.release()
        if base is not None:
            rec.outcome = "internal_error"
            raise base
        return outcome

    async def _run_slot(
        self, published: PublishedFlow, box: SecretBox, rec: _Record
    ) -> tuple[CallOutcome, BaseException | None]:
        try:
            session = self._factory()
        except Exception:
            rec.outcome = "host_unavailable"
            return CallOutcome("host_unavailable", error_body("host_unavailable")), None

        run = _Run(
            session=session,
            flow=published.flow,
            box=box,
            bound=self._bound.for_flow(published.flow.name),
            signatures=self._signatures,
            clock=self._clock,
            poll=self._poll,
            loop=asyncio.get_running_loop(),
            done=anyio.Event(),
        )
        self._runs.add(run)
        try:
            try:
                threading.Thread(target=_worker, args=(run,), daemon=True).start()
            except BaseException as start_exc:
                close_base: BaseException | None = None
                try:
                    session.close()
                except Exception:
                    rec.close_failed = True
                except BaseException as exc:
                    close_base = exc
                rec.outcome = "internal_error"
                if not isinstance(start_exc, Exception):
                    raise  # no worker ran: close once, then propagate (Requirement 6.8)
                if close_base is not None:
                    raise close_base
                return CallOutcome("internal_error", error_body("internal_error")), None

            shutting = False
            try:
                with anyio.move_on_after(published.deadline) as scope:
                    await run.done.wait()
            except BaseException:
                # Cancelled (client gone, server stopping). Read ``closing`` once.
                shutting = self.closing
                if run.abort_reason is None:
                    run.abort_reason = "shutdown" if shutting else "cancel"
                with anyio.CancelScope(shield=True):
                    await self._teardown(run)  # the cancellation wins over an abort error
                rec.outcome = "shutting_down" if run.abort_reason == "shutdown" else "cancelled"
                rec.session_clean = False
                rec.close_failed = run.result.close_failed
                raise
            if scope.cancelled_caught and run.abort_reason is None:
                run.abort_reason = "timeout"
            pending: BaseException | None = None
            if run.abort_reason is not None:
                with anyio.CancelScope(shield=True):
                    pending = await self._teardown(run)
            outcome, base = self._finish(run, rec)
            if base is None and pending is not None:
                rec.outcome = "internal_error"
                base = pending
            return outcome, base
        finally:
            self._runs.discard(run)

    def _finish(self, run: _Run, rec: _Record) -> tuple[CallOutcome, BaseException | None]:
        """Build the outcome from the worker's result slot, then drop the references."""
        res = run.result
        reason = run.abort_reason
        rec.close_failed = res.close_failed
        step_index: int | None = None
        base: BaseException | None = None
        body: dict
        if res.kind == "base":  # Requirement 6.8 beats a timeout or shutdown answer
            base = res.base
            code, body = "internal_error", error_body("internal_error")
        elif reason == "timeout":
            code, body = "call_timeout", error_body("call_timeout")
        elif reason == "shutdown":
            code, body = "shutting_down", error_body("shutting_down")
        elif res.kind == "ok":
            code = "ok"
            body = {
                "flow": res.value.flow,
                "outputs": dict(res.value.outputs),
                "audit": audit_to_list(res.value.audit),
            }
        elif res.kind == "host_unavailable":
            code, body = "host_unavailable", error_body("host_unavailable")
        elif res.kind == "input_invalid":
            code, body = "input_invalid", error_body("input_invalid", message=res.value)
        elif res.kind == "flow_error" and res.value["reason"] in _FLOW_STOP_CODES:
            data = res.value
            code = data["reason"]
            step_index = data["step_index"]
            body = error_body(
                code,
                step_index=data["step_index"],
                kind=data["kind"],
                expected=data["expected"],
                summary=data["summary"],
                audit=data["audit"],
            )
        else:
            code, body = "internal_error", error_body("internal_error")

        rec.outcome = code
        rec.step_index = step_index
        rec.session_clean = _session_clean(code, reason)
        outcome = CallOutcome(
            code,
            body,
            step_index=step_index,
            close_failed=res.close_failed,
            session_clean=rec.session_clean,
        )
        # Requirement 3.9: nothing of the run stays reachable from this frame.
        res.value = None
        res.base = None
        run.session = None
        run.bound = {}
        return outcome, base

    async def _teardown(self, run: _Run) -> BaseException | None:
        """Abort the session from outside the worker, then wait for the worker.

        Returns a ``BaseException`` (not an ``Exception``) raised by ``abort`` so that
        the caller can propagate it; the wait for the worker happens either way.
        """
        run.aborted.set()
        if run.done.is_set():
            return None
        pending: BaseException | None = None
        try:
            await anyio.to_thread.run_sync(run.session.abort)
        except Exception:
            _LOG.warning("session abort failed")
        except BaseException as exc:
            _LOG.warning("session abort failed")
            pending = exc
        with anyio.move_on_after(_WORKER_GRACE):
            await run.done.wait()
        if not run.done.is_set():
            _LOG.warning("worker_stuck")
        return pending

    def _write_log(self, rec: _Record, t0: float) -> None:
        extra: dict[str, Any] = {
            "call_id": rec.call_id,
            "flow": rec.flow,
            "transport": rec.transport,
            "outcome": rec.outcome,
            "duration_ms": int((time.monotonic() - t0) * 1000),
        }
        if rec.step_index is not None:
            extra["step_index"] = rec.step_index
        if rec.close_failed:
            extra["close_failed"] = True
        if rec.session_clean is False:
            extra["session_clean"] = False
        _LOG.info("call finished", extra=extra)


# ---------------------------------------------------------------------------
# ConnectorSession (task 2.3): the default Session_Factory product.
# ---------------------------------------------------------------------------


class ConnectorSession:
    """A ``Connector`` that can be aborted from another thread (Requirement 10.3).

    One thread (the worker) calls ``open``, every Session method and ``close``.
    ``abort()`` is the only cross-thread call. It never touches the Connector:
    it sets a flag and kills the s3270 process captured by ``_spawn``. A blocked
    read then fails with ``S3270Error`` (EOF), and ``close()`` on the dead
    process returns at once.
    """

    def __init__(
        self,
        config: Any,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self._lock = threading.Lock()
        self._proc: Any = None
        self._aborted = False
        self._popen = popen
        self._conn = Connector(config, process_factory=self._spawn)

    def _spawn(self, cmd: Any, **kwargs: Any) -> Any:
        # Called by Connector.open on the worker thread. Connector maps the
        # OSError to a ConnectorError, so open() after abort() raises.
        with self._lock:
            if self._aborted:
                raise OSError("aborted")
            self._proc = self._popen(cmd, **kwargs)
            return self._proc

    def abort(self) -> None:
        """Thread-safe and idempotent. Kills and reaps the s3270 process."""
        with self._lock:
            self._aborted = True
            proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            pass

    def open(self) -> None:
        self._conn.open()

    def close(self) -> None:
        self._conn.close()

    def read_screen(self) -> Screen:
        return self._conn.read_screen()

    def string(self, text: str) -> None:
        self._conn.string(text)

    def enter(self) -> None:
        self._conn.enter()

    def clear(self) -> None:
        self._conn.clear()

    def pf(self, n: int) -> None:
        self._conn.pf(n)

    def pa(self, n: int) -> None:
        self._conn.pa(n)
