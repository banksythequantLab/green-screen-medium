"""Flow runner: ``run_flow``, run state, Session access and screen polling.

Failures travel inside the runner as plain data (``_Failure``) and are turned
into a ``FlowError`` only after every ``Screen`` has been released, in a frame
that holds none and outside any ``except`` block (so ``__context__`` is None).

Extension points for later tasks:

* Step executors are methods of ``_RunState`` registered by Step kind in
  ``_EXECUTORS``. Each takes a ``PlanItem`` and the body iteration (or None)
  and returns a ``_StepDone``; a failure is signalled by raising ``_Halt``.
  ``type``, ``key``, ``extract`` and ``handle`` raise ``NotImplementedError``
  until tasks 7.4 and 7.5 replace them.
* ``_RunState.run_finally`` is the hook for task 7.6.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from greenscreen.connector import Screen
from greenscreen.flow.clock import Clock, SystemClock
from greenscreen.flow.errors import FlowDefinitionError, FlowError
from greenscreen.flow.inputs import PreparedInputs, prepare_inputs
from greenscreen.flow.model import (
    AuditRecord,
    CollectStep,
    ExpectStep,
    ExtractStep,
    Flow,
    FlowResult,
    HandleStep,
    KeyStep,
    PlanItem,
    TypeStep,
    plan,
)
from greenscreen.flow.screens import (
    Geometry,
    build_comparison,
    geometry,
    read_region,
    read_rows,
    same_screen,
)
from greenscreen.recognizer import (
    AmbiguousScreenError,
    ScreenSignature,
    SignatureError,
    UnknownScreenError,
    load_bundled_signatures,
    recognize,
)
from greenscreen.recognizer.summary import RedactedSummary, build_summary
from greenscreen.recognizer.view import ScreenView

logger = logging.getLogger("greenscreen.flow")

_INT_TEXT = re.compile(r"[0-9]{1,18}")
_FINALLY_SKIP_REASONS = frozenset(
    {
        "unknown_screen",
        "ambiguous_screen",
        "timeout",
        "run_timeout",
        "session_error",
        "input_invalid",
        "definition",
    }
)
FINALLY_SKIP_REASONS: frozenset[str] = _FINALLY_SKIP_REASONS
_MIN_POLL = 0.01
_MAX_POLL = 1.0


class Session(Protocol):
    """What the runner needs from a terminal session.

    ``close`` is declared for completeness; ``run_flow`` never calls it.
    """

    def read_screen(self) -> Screen: ...
    def string(self, text: str) -> None: ...
    def enter(self) -> None: ...
    def clear(self) -> None: ...
    def pf(self, n: int) -> None: ...
    def pa(self, n: int) -> None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------
# Internal data (never stored in a result, exception or log record)
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Accepted:
    screen: Screen  # may hold hidden cells; dropped by _RunState.release()
    name: str
    geometry: Geometry
    view: ScreenView | None = None  # built lazily by _RunState.view_of


@dataclass(frozen=True, slots=True)
class _Failure:
    reason: str  # a Reason_Code, or "definition" (becomes FlowDefinitionError)
    step_index: int | None
    kind: str | None
    expected: tuple[str, ...]
    summary: RedactedSummary | None
    detail: str = ""


class _Halt(Exception):
    """Internal control flow only; carries one _Failure; never leaves run_flow."""

    def __init__(self, failure: _Failure) -> None:
        super().__init__(failure.reason)
        self.failure = failure


@dataclass(frozen=True, slots=True)
class _StepDone:
    status: str = "ok"  # "ok" | "skipped"
    signature: str | None = None
    count: int = 0  # reads, keys or iterations, for the DEBUG record


@dataclass(frozen=True, slots=True)
class _Outcome:
    """Result of one ``recognize`` call, as plain data."""

    kind: str  # "name" | "unknown" | "ambiguous" | "definition"
    name: str = ""
    summary: RedactedSummary | None = None
    detail: str = ""


class _Stable:
    """Stable_Record: one per ``poll`` or ``_settle`` call (Requirement 24)."""

    __slots__ = ("screen", "since")

    def __init__(self) -> None:
        self.screen: Screen | None = None
        self.since = 0.0

    def held(self, screen: Screen, now: float) -> float:
        """Seconds this exact screen has been read unchanged in this call."""
        if self.screen is None or not same_screen(screen, self.screen):
            self.screen, self.since = screen, now
        return now - self.since


# --------------------------------------------------------------------------
# Run state
# --------------------------------------------------------------------------


class _RunState:
    def __init__(
        self,
        flow: Flow,
        session: Session,
        sigs: list[ScreenSignature],
        clock: Clock,
        poll_interval: float,
        prepared: PreparedInputs,
        inputs: Mapping[str, object],
    ) -> None:
        self.flow = flow
        self.session = session
        self.sigs = sigs
        self.stable = {s.name: s.stable_for for s in sigs if s.stable_for > 0}
        self.clock = clock
        self.poll_interval = poll_interval
        self.prepared = prepared
        self._inputs: Mapping[str, object] | None = inputs  # Secret_Values live here

        self.current: _Accepted | None = None
        self.pre_key_screen: Screen | None = None
        self.pre_key_name: str | None = None
        self.typed_fields: set[tuple[int, int, int]] = set()

        self.audit: list[AuditRecord] = []
        self.outputs: dict[str, str | int] = {}

        self.phase = "steps"
        self.phase_start = 0.0
        self.phase_limit = flow.timeouts.run

    # -- lifecycle -------------------------------------------------------

    def release(self) -> None:
        """Drop every Screen, the cached views and the inputs mapping."""
        self.current = None
        self.pre_key_screen = None
        self.pre_key_name = None
        self.typed_fields = set()
        self._inputs = None

    def view_of(self, accepted: _Accepted) -> ScreenView:
        if accepted.view is None:
            accepted.view = ScreenView(accepted.screen)
        return accepted.view

    def accept(self, screen: Screen, name: str) -> None:
        """Make ``screen`` the Current_Screen and forget the last key."""
        self.current = _Accepted(screen, name, geometry(screen))
        self.pre_key_screen = None
        self.pre_key_name = None
        self.typed_fields = set()

    # -- phases ----------------------------------------------------------

    def run_phase(self, phase: str) -> _Failure | None:
        """Run the main ``steps``. Returns None or the failure that stopped it."""
        main, _ = plan(self.flow)
        self.phase = "steps"
        self.phase_start = self.clock.monotonic()
        self.phase_limit = self.flow.timeouts.run
        failure: _Failure | None = None
        try:
            self.run_items(main, None)
        except _Halt as halt:
            failure = halt.failure
        return failure

    def run_finally(self, main_failure: _Failure | None) -> _Failure | None:
        """Run or skip the Finally_Steps. Returns None or the Finally failure.

        The caller lets the main failure win over the one returned here.
        """
        _, fin = plan(self.flow)
        if not fin:
            return None
        skip = main_failure is not None and (
            main_failure.reason in _FINALLY_SKIP_REASONS or self.current is None
        )
        if skip:
            self._skip_finally(fin)
            return None
        self.phase = "finally"
        self.phase_start = self.clock.monotonic()
        self.phase_limit = self.flow.timeouts.finally_
        failure: _Failure | None = None
        try:
            self.run_items(fin, None)
        except _Halt as halt:
            failure = halt.failure
            self._skip_finally(fin)
        return failure

    def _skip_finally(self, fin: Iterable[PlanItem]) -> None:
        """Append a ``skipped`` record for each finally Step_Index with no record."""
        recorded = {r.step_index for r in self.audit if r.phase == "finally"}

        def walk(items: Iterable[PlanItem]) -> None:
            for item in items:
                if item.index not in recorded:
                    self.audit.append(
                        AuditRecord(
                            item.index, item.step.kind, item.phase, None, None,
                            "skipped", 0.0,
                        )
                    )
                    recorded.add(item.index)
                walk(item.children)

        walk(fin)

    # -- Step dispatch ---------------------------------------------------

    def run_items(self, items: Iterable[PlanItem], iteration: int | None) -> None:
        for item in items:
            self.run_item(item, iteration)

    def run_item(self, item: PlanItem, iteration: int | None) -> None:
        idx = item.index
        kind = item.step.kind
        phase = item.phase
        _log("flow=%s step=%d kind=%s", self.flow.name, idx, kind)
        started = self.clock.monotonic()
        slot = len(self.audit)
        self.audit.append(AuditRecord(idx, kind, phase, iteration, None, "failed", 0.0))
        executor = _EXECUTORS[kind]
        try:
            done = executor(self, item, iteration)
        except _Halt:
            self.audit[slot] = AuditRecord(
                idx, kind, phase, iteration, None, "failed",
                self.clock.monotonic() - started,
            )
            raise
        elapsed = self.clock.monotonic() - started
        self.audit[slot] = AuditRecord(
            idx, kind, phase, iteration, done.signature, done.status, elapsed
        )
        _log(
            "flow=%s step=%d kind=%s signature=%s count=%d ms=%d",
            self.flow.name, idx, kind, done.signature or "none", done.count,
            int(elapsed * 1000),
        )

    # -- budget and Session access --------------------------------------

    def _budget(self, idx: int | None, kind: str | None) -> None:
        if self.clock.monotonic() - self.phase_start >= self.phase_limit:
            raise _Halt(_Failure("run_timeout", idx, kind, (), None))

    def _session_failure(self, idx: int | None, kind: str | None, name: str) -> _Halt:
        return _Halt(_Failure("session_error", idx, kind, (), None, name))

    def read(self, idx: int | None, kind: str | None) -> Screen:
        self._budget(idx, kind)
        failed: str | None = None
        screen: Screen | None = None
        try:
            screen = self.session.read_screen()
        except FlowError:
            raise  # Requirement 7.9: unchanged; run_flow releases and re-raises
        except Exception as exc:  # noqa: BLE001 - Requirement 7.6: only the class name is kept
            failed = type(exc).__name__
        if failed is not None or screen is None:
            raise self._session_failure(idx, kind, failed or "NoScreen") from None
        return screen

    def string(self, idx: int | None, kind: str | None, text: str) -> None:
        """Type ``text``. Any Exception except a FlowError becomes session_error."""
        self._budget(idx, kind)
        failed: str | None = None
        try:
            self.session.string(text)
        except FlowError:
            raise
        except Exception as exc:  # noqa: BLE001 - only the class name is kept
            failed = type(exc).__name__
        if failed is not None:
            raise self._session_failure(idx, kind, failed) from None

    def key(
        self, idx: int | None, kind: str | None, key: str, n: int | None = None
    ) -> None:
        """Send exactly one of enter, clear, pf(n), pa(n)."""
        self._budget(idx, kind)
        failed: str | None = None
        try:
            if key == "enter":
                self.session.enter()
            elif key == "clear":
                self.session.clear()
            elif key == "pf":
                self.session.pf(n)  # type: ignore[arg-type]
            elif key == "pa":
                self.session.pa(n)  # type: ignore[arg-type]
            else:  # unreachable for a validated Flow
                raise ValueError("unknown key")
        except FlowError:
            raise
        except Exception as exc:  # noqa: BLE001 - only the class name is kept
            failed = type(exc).__name__
        if failed is not None:
            raise self._session_failure(idx, kind, failed) from None

    # -- recognition -----------------------------------------------------

    def recognize(
        self,
        screen: Screen,
        held: float | None = None,
        confirmed: str | None = None,
    ) -> _Outcome:
        """One ``recognize`` call turned into plain data (no exception escapes).

        A screen whose signature has ``stable_for`` is unknown until it has been
        read unchanged for that long (``held``), unless it is ``confirmed``.
        """
        outcome: _Outcome
        try:
            name = recognize(screen, self.sigs)
            need = self.stable.get(name)
            if (
                need is not None
                and name != confirmed
                and (held is None or held < need)
            ):
                return _Outcome("unknown")
            outcome = _Outcome("name", name=name)
        except UnknownScreenError as exc:
            outcome = _Outcome("unknown", summary=exc.summary)
        except AmbiguousScreenError:
            outcome = _Outcome("ambiguous")
        except (SignatureError, TypeError) as exc:
            outcome = _Outcome("definition", detail=type(exc).__name__)
        return outcome

    def halt(
        self,
        reason: str,
        idx: int | None,
        kind: str | None,
        expected: Iterable[str],
        screen: Screen | None = None,
        summary: RedactedSummary | None = None,
        detail: str = "",
    ) -> _Halt:
        """Build the _Halt for a failure; the summary comes from ``screen`` if needed."""
        if summary is None and screen is not None:
            summary = build_summary(ScreenView(screen))
        return _Halt(
            _Failure(reason, idx, kind, tuple(sorted(expected)), summary, detail)
        )

    def halt_for_outcome(
        self,
        outcome: _Outcome,
        idx: int | None,
        kind: str | None,
        expected: Iterable[str],
        screen: Screen,
    ) -> _Halt:
        """Halt for an unknown, ambiguous or definition outcome."""
        if outcome.kind == "definition":
            return self.halt("definition", idx, kind, (), detail=outcome.detail)
        reason = "unknown_screen" if outcome.kind == "unknown" else "ambiguous_screen"
        return self.halt(reason, idx, kind, expected, screen, outcome.summary)

    # -- polling ---------------------------------------------------------

    def poll(
        self,
        idx: int,
        kind: str,
        *,
        accepted: Iterable[str] = (),
        tolerate: Iterable[str] = (),
        timeout: float,
        accept_any: bool = False,
        expected: Iterable[str] | None = None,
    ) -> tuple[str, int]:
        """Read and recognize until a screen is accepted. Returns (name, reads).

        Accepts a name in ``accepted`` (any name when ``accept_any``), tolerates
        ``tolerate``, the Pre_Key_Name and unknown screens until ``timeout``,
        treats a screen equal to the Pre_Key_Screen as "no answer yet", and
        halts at once on an ambiguous or unexpected screen.
        """
        accepted_set = frozenset(accepted)
        tolerate_set = frozenset(tolerate)
        shown = tuple(sorted(accepted_set if expected is None else expected))
        start = self.clock.monotonic()
        reads = 0
        tracker = _Stable() if self.stable else None
        while True:
            screen = self.read(idx, kind)
            reads += 1
            held = None if tracker is None else tracker.held(screen, self.clock.monotonic())
            last = "same"
            unknown_summary: RedactedSummary | None = None
            pre = self.pre_key_screen
            if pre is None or not same_screen(screen, pre):
                outcome = self.recognize(screen, held)
                if outcome.kind == "unknown":
                    last = "unknown"
                    unknown_summary = outcome.summary
                elif outcome.kind != "name":
                    raise self.halt_for_outcome(outcome, idx, kind, shown, screen)
                else:
                    name = outcome.name
                    if accept_any or name in accepted_set:
                        self.accept(screen, name)
                        return name, reads
                    if name in tolerate_set:
                        last = "tolerated"
                    elif pre is not None and name == self.pre_key_name:
                        last = "prekey"
                    else:
                        raise self.halt("unexpected_screen", idx, kind, shown, screen)
            if self.clock.monotonic() - start >= timeout:
                if last == "unknown":
                    raise self.halt(
                        "unknown_screen", idx, kind, shown, screen, unknown_summary
                    )
                raise self.halt("timeout", idx, kind, shown, screen)
            self.clock.sleep(self.poll_interval)

    # -- step executors --------------------------------------------------

    def exec_expect(self, item: PlanItem, iteration: int | None) -> _StepDone:
        step = item.step
        assert isinstance(step, ExpectStep)
        timeout = step.timeout if step.timeout is not None else self.flow.timeouts.step
        name, reads = self.poll(
            item.index,
            "expect",
            accepted=step.signatures,
            tolerate=step.tolerate,
            timeout=timeout,
        )
        return _StepDone("ok", name, reads)

    def exec_type(self, item: PlanItem, iteration: int | None) -> _StepDone:
        step = item.step
        assert isinstance(step, TypeStep)
        idx = item.index
        secret_name: str | None = None
        literal: str | None = None
        if step.input is not None:
            name = step.input
            if name in self.prepared.supplied_secrets:
                secret_name = name
            elif name in self.prepared.values:
                literal = self.prepared.values[name]
            else:
                return _StepDone("skipped")  # optional Input not supplied
        else:
            literal = step.text
            assert literal is not None

        current = self.current
        if current is None:  # unreachable for a validated Flow
            raise self.halt("unexpected_screen", idx, "type", ())
        view = self.view_of(current)
        field = view.containing_field(current.screen.cursor_row, current.screen.cursor_col)
        if field is None or field.protected:
            raise self.halt("bad_target", idx, "type", (), current.screen)
        if secret_name is not None and not field.hidden:
            raise self.halt("secret_target", idx, "type", (), current.screen)

        if secret_name is not None:
            self._type_secret(idx, secret_name)
        else:
            assert literal is not None
            self.string(idx, "type", literal)
        self.typed_fields.add((field.start_row, field.start_col, field.byte_length))
        return _StepDone("ok")

    def _type_secret(self, idx: int, name: str) -> None:
        """Type a Secret_Value; it lives only in a local that is deleted here."""
        inputs = self._inputs
        secret_value = inputs[name] if inputs is not None else ""
        del inputs
        try:
            self.string(idx, "type", str(secret_value))
        finally:
            del secret_value

    def exec_key(self, item: PlanItem, iteration: int | None) -> _StepDone:
        step = item.step
        assert isinstance(step, KeyStep)
        idx = item.index
        left = self._press(idx, "key", step.key, step.n)
        return _StepDone("ok", left, 1)

    def _press(self, idx: int, kind: str, key: str, n: int | None) -> str:
        """Pre-key check, send the key, leave the screen. Returns the name left."""
        current = self.current
        if current is None:  # Requirement 8.15: no key without a Current_Screen
            raise self.halt("unexpected_screen", idx, kind, ())
        expected = (current.name,)
        pre = self.read(idx, kind)
        failure = self._key_check(pre, current, idx, expected, kind)
        if failure is not None:
            raise failure
        self.key(idx, kind, key, n)
        self.pre_key_screen = pre
        self.pre_key_name = current.name
        self.current = None
        self.typed_fields = set()
        return current.name

    def _key_check(
        self,
        pre: Screen,
        current: _Accepted,
        idx: int,
        expected: tuple[str, ...],
        kind: str,
    ) -> _Halt | None:
        """Pre-key check. Returns a _Halt or None; holds no exception in flight."""
        if geometry(pre) != current.geometry:
            return self.halt("unexpected_screen", idx, kind, expected, pre)
        comparison = build_comparison(pre, current.screen, self.typed_fields)
        outcome = self.recognize(comparison, None, current.name)
        del comparison
        if outcome.kind == "definition":
            return self.halt("definition", idx, kind, (), detail=outcome.detail)
        if outcome.kind != "name":
            reason = "unknown_screen" if outcome.kind == "unknown" else "ambiguous_screen"
            return self.halt(reason, idx, kind, expected, pre)
        if outcome.name != current.name:
            return self.halt("unexpected_screen", idx, kind, expected, pre)
        return None

    def exec_extract(self, item: PlanItem, iteration: int | None) -> _StepDone:
        step = item.step
        assert isinstance(step, ExtractStep)
        idx = item.index
        output = next(o for o in self.flow.outputs if o.name == step.output)
        detail = f"output {output.name}"
        current = self.current
        if current is None or current.name != output.signature:
            raise self.halt(
                "unexpected_screen", idx, "extract", (output.signature,),
                None if current is None else current.screen,
            )
        screen = current.screen
        if screen.rows < 24 or screen.columns < 80:
            raise self.halt("screen_size", idx, "extract", (), screen, detail=detail)
        view = self.view_of(current)
        if output.max_rows is not None:  # Rows_Output
            rows = read_rows(screen, view, output.row, output.col, output.length)
            if rows is None:
                raise self.halt(
                    "hidden_output", idx, "extract", (), screen, detail=detail
                )
            if len(rows) > output.max_rows:
                raise self.halt("loop_limit", idx, "extract", (), screen, detail=detail)
            self.outputs[output.name] = "\n".join(rows)
            return _StepDone("ok", current.name, 0)
        raw = read_region(screen, view, output.row, output.col, output.length)
        if raw is None:
            raise self.halt("hidden_output", idx, "extract", (), screen, detail=detail)
        text = raw.strip(" ")
        if output.equals is not None:  # Flag_Output
            self.outputs[output.name] = 1 if text == output.equals else 0
            return _StepDone("ok", current.name, 0)
        value: str | int = text
        if output.type == "int":
            if _INT_TEXT.fullmatch(text) is None:
                raise self.halt("output_type", idx, "extract", (), screen, detail=detail)
            value = int(text)
        self.outputs[output.name] = value
        return _StepDone("ok", current.name, 0)

    def exec_collect(self, item: PlanItem, iteration: int | None) -> _StepDone:
        step = item.step
        assert isinstance(step, CollectStep)
        idx = item.index
        output = next(o for o in self.flow.outputs if o.name == step.output)
        assert output.max_rows is not None
        accepted = (output.signature, step.more)
        detail = f"output {output.name}"
        cur = self.current
        if cur is None or cur.name not in accepted:
            raise self.halt(
                "unexpected_screen", idx, "collect", accepted,
                None if cur is None else cur.screen,
            )
        rows: list[str] = []
        screens = 0
        while True:
            screens += 1
            screen = cur.screen
            if screen.rows < 24 or screen.columns < 80:
                raise self.halt(
                    "screen_size", idx, "collect", (), screen, detail=detail
                )
            first = (
                output.row
                if screens == 1 or output.next_row is None
                else output.next_row
            )
            got = read_rows(
                screen, self.view_of(cur), first, output.col, output.length
            )
            if got is None:
                raise self.halt(
                    "hidden_output", idx, "collect", (), screen, detail=detail
                )
            rows.extend(got)
            del got
            if len(rows) > output.max_rows:
                raise self.halt(
                    "loop_limit", idx, "collect", (), screen, detail=detail
                )
            if cur.name == output.signature:
                break
            if screens >= step.max_screens:
                raise self.halt(
                    "loop_limit", idx, "collect", (), screen, detail=detail
                )
            self._press(idx, "collect", "enter", None)
            self.poll(
                idx, "collect", accepted=accepted,
                timeout=self.flow.timeouts.step, expected=accepted,
            )
            cur = self.current
            assert cur is not None
        self.outputs[output.name] = "\n".join(rows)
        return _StepDone("ok", cur.name, screens)

    def exec_handle(self, item: PlanItem, iteration: int | None) -> _StepDone:
        step = item.step
        assert isinstance(step, HandleStep)
        idx = item.index
        sig = step.signature
        timeout = self.flow.timeouts.step
        if self.current is None:
            self.poll(
                idx, "handle", accept_any=True, timeout=timeout, expected=(sig,)
            )
        current = self.current
        assert current is not None
        name = current.name
        count = 0
        if name == sig and step.settle > 0:
            name = self._settle(idx, step.settle, sig)
        while name == sig:
            if count >= step.max_count:
                raise self.halt("loop_limit", idx, "handle", ())
            count += 1
            self.run_items(item.children, count)
            name, _ = self.poll(
                idx, "handle", accept_any=True, timeout=timeout, expected=(sig,)
            )
        if count == 0:
            self._skip_body(item)  # Requirements 13.10, 15.7: Unmatched_Handle
        return _StepDone("ok", sig, count)

    def _skip_body(self, item: PlanItem) -> None:
        """Append one ``skipped`` record per Body_Step; no clock, no Session call."""
        for child in item.children:
            self.audit.append(
                AuditRecord(
                    child.index, child.step.kind, item.phase, None, None,
                    "skipped", 0.0,
                )
            )

    def _settle(self, idx: int, settle: float, sig: str) -> str:
        """Watch the handled screen for up to ``settle`` seconds; return its name."""
        start = self.clock.monotonic()
        tracker = _Stable() if self.stable else None
        while True:
            remaining = settle - (self.clock.monotonic() - start)
            if remaining <= 0:
                return sig
            self.clock.sleep(min(self.poll_interval, remaining))
            screen = self.read(idx, "handle")
            held = None if tracker is None else tracker.held(screen, self.clock.monotonic())
            outcome = self.recognize(screen, held)
            if outcome.kind == "name":
                self.accept(screen, outcome.name)
                if outcome.name != sig:
                    return outcome.name
            elif outcome.kind != "unknown":
                raise self.halt_for_outcome(outcome, idx, "handle", (sig,), screen)


# Step kind -> executor. Later tasks replace the stubs above, not this table.
_EXECUTORS = {
    "expect": _RunState.exec_expect,
    "type": _RunState.exec_type,
    "key": _RunState.exec_key,
    "extract": _RunState.exec_extract,
    "collect": _RunState.exec_collect,
    "handle": _RunState.exec_handle,
}


# --------------------------------------------------------------------------
# Logging: the only function that touches the logger
# --------------------------------------------------------------------------


def _log(fmt: str, *args: str | int) -> None:
    logger.debug(fmt, *args)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _referenced_names(flow: Flow) -> set[str]:
    names: set[str] = set()
    main, fin = plan(flow)
    stack = list(main) + list(fin)
    while stack:
        item = stack.pop()
        step = item.step
        if isinstance(step, ExpectStep):
            names.update(step.signatures)
            names.update(step.tolerate)
        elif isinstance(step, HandleStep):
            names.add(step.signature)
        elif isinstance(step, CollectStep):
            names.add(step.more)
        stack.extend(item.children)
    names.update(out.signature for out in flow.outputs)
    return names


def _resolve_signatures(
    flow: Flow, signatures: Iterable[ScreenSignature] | None
) -> list[ScreenSignature]:
    pool = list(load_bundled_signatures() if signatures is None else signatures)
    wanted = _referenced_names(flow)
    chosen = [s for s in pool if getattr(s, "name", None) in wanted]
    missing = sorted(wanted - {s.name for s in chosen})
    if missing:
        raise FlowDefinitionError(
            "flow references unknown signature(s): " + ", ".join(missing)
        )
    return chosen


def _clear_frames(tb: object) -> None:
    """Empty the locals of finished ``greenscreen.flow`` frames of a traceback.

    The first entry is the ``run_flow`` frame, which is still executing.
    """
    entry = getattr(tb, "tb_next", None)
    while entry is not None:
        frame = entry.tb_frame
        if str(frame.f_globals.get("__name__", "")).startswith("greenscreen.flow"):
            try:
                frame.clear()
            except RuntimeError:  # frame still executing
                pass
        entry = entry.tb_next


def run_flow(
    flow: Flow,
    session: Session,
    inputs: Mapping[str, str | int],
    *,
    signatures: Iterable[ScreenSignature] | None = None,
    clock: Clock | None = None,
    poll_interval: float = 0.1,
) -> FlowResult:
    """Replay ``flow`` on ``session`` and return its outputs and audit trail.

    Raises ``ValueError`` for a ``poll_interval`` outside 0.01 to 1 (before any
    Session call), ``FlowInputError`` for bad inputs (before any Session call),
    ``FlowDefinitionError`` for a missing signature, and ``FlowError`` when the
    run stops. ``session.close`` is never called.
    """
    state: _RunState | None = None
    prepared: PreparedInputs | None = None
    try:
        if (
            type(poll_interval) not in (int, float)
            or not _MIN_POLL <= poll_interval <= _MAX_POLL
        ):
            raise ValueError("poll_interval must be a number from 0.01 to 1")
        use_clock: Clock = SystemClock() if clock is None else clock
        sigs = _resolve_signatures(flow, signatures)
        prepared = prepare_inputs(flow, inputs)  # FlowInputError, no Session call yet

        state = _RunState(
            flow, session, sigs, use_clock, float(poll_interval), prepared, inputs
        )
        run_start = use_clock.monotonic()
        failure = state.run_phase("steps")
        finally_failure = state.run_finally(failure)
    except BaseException:
        # Bad poll_interval, FlowInputError, FlowDefinitionError, KeyboardInterrupt,
        # SystemExit, a FlowError from a Session, or a bug: release, empty the
        # runner's frames, re-raise the same object.
        if state is not None:
            state.release()
        _clear_frames(sys.exc_info()[2])
        del state, inputs, prepared
        raise
    audit = tuple(state.audit)
    extracted = state.outputs
    # Declaration order, not Extract_Step execution order (one entry per Output).
    outputs = {o.name: extracted[o.name] for o in flow.outputs if o.name in extracted}
    state.release()
    del state, inputs, prepared

    final = failure if failure is not None else finally_failure
    if final is None:
        _log(
            "flow=%s count=%d ms=%d",
            flow.name, len(audit), int((use_clock.monotonic() - run_start) * 1000),
        )
        return FlowResult(flow.name, outputs, audit)

    _log(
        "flow=%s step=%s reason=%s",
        flow.name, "none" if final.step_index is None else final.step_index,
        final.reason,
    )
    if final.reason == "definition":
        raise FlowDefinitionError(f"recognizer failed: {final.detail}") from None
    raise FlowError(
        final.reason,
        step_index=final.step_index,
        kind=final.kind,
        expected=final.expected,
        summary=final.summary,
        audit=audit,
        detail=final.detail,
    ) from None
