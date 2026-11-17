"""Flow_Validator: load-time checks of a Flow (flow-runtime Requirements 1 to 5).

``structural_violations`` needs no Signature set and runs on every ``Flow``
construction. ``reference_violations`` and ``check_flow`` add the check against
a Signature set. The validator reads no environment variable, file or Session.

Messages hold only fixed rule text, field names, Step_Index, Flow_Name,
Signature_Names and Input or Output names, never another YAML scalar.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from greenscreen.flow._echo import echo_kind
from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    Flow,
    HandleStep,
    InputSpec,
    KeyStep,
    OutputSpec,
    PlanItem,
    Timeouts,
    TypeStep,
    plan,
)

if TYPE_CHECKING:  # pragma: no cover
    from greenscreen.recognizer import ScreenSignature

_FLOW_NAME = re.compile(r"[a-z0-9_-]{1,64}")
_IO_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
_SIG_NAME = re.compile(r"[a-z0-9_-]{1,64}")
_KEYS = ("enter", "clear", "pf", "pa")


@dataclass(frozen=True, slots=True)
class Violation:
    step_index: int | None
    requirement: int  # 1..5
    criterion: int
    field: str
    rule: str  # short fixed text; never a YAML scalar


def _is_int(v: object) -> bool:
    return type(v) is int


def _is_num(v: object) -> bool:
    return type(v) is int or type(v) is float


def _in_range(v: object, lo: float, hi: float) -> bool:
    return _is_num(v) and lo <= v <= hi  # type: ignore[operator]


def _printable(s: str) -> bool:
    return all(0x20 <= ord(c) <= 0x7E for c in s)


def _is_sig_name(v: object) -> bool:
    return isinstance(v, str) and _SIG_NAME.fullmatch(v) is not None


def _label(kind: str, index: int, name: object) -> str:
    """Name an Input or Output by name, or by position when the name is unusable."""
    if isinstance(name, str) and _IO_NAME.fullmatch(name):
        return f"{kind} {name}"
    return f"{kind}[{index}]"


class _Collector:
    def __init__(self) -> None:
        self.items: list[Violation] = []

    def add(
        self, step: int | None, req: int, crit: int, field: str, rule: str
    ) -> None:
        self.items.append(Violation(step, req, crit, field, rule))


def _check_flow_fields(flow: Flow, out: _Collector, step_total: int, fin_total: int) -> None:
    name = flow.name
    if not isinstance(name, str) or _FLOW_NAME.fullmatch(name) is None:
        out.add(None, 1, 6, "name", "invalid_name")
    if not isinstance(flow.description, str) or len(flow.description) > 500:
        out.add(None, 1, 6, "description", "too_long")
    if len(flow.inputs) > 20:
        out.add(None, 1, 6, "inputs", "too_many")
    if len(flow.outputs) > 20:
        out.add(None, 1, 6, "outputs", "too_many")
    if step_total < 1:
        out.add(None, 1, 6, "steps", "empty")
    elif step_total > 200:
        out.add(None, 1, 6, "steps", "too_many")
    if fin_total > 50:
        out.add(None, 1, 6, "finally", "too_many")

    t = flow.timeouts
    if not isinstance(t, Timeouts):
        out.add(None, 5, 12, "timeouts", "invalid")
        return
    if not _in_range(t.step, 0.1, 60):
        out.add(None, 5, 12, "timeouts.step", "out_of_range")
    if not _in_range(t.run, 1, 600):
        out.add(None, 5, 12, "timeouts.run", "out_of_range")
    if not _in_range(t.finally_, 1, 120):
        out.add(None, 5, 12, "timeouts.finally", "out_of_range")


def _check_inputs(flow: Flow, out: _Collector) -> None:
    seen: set[str] = set()
    for i, spec in enumerate(flow.inputs):
        if not isinstance(spec, InputSpec):
            out.add(None, 2, 2, f"inputs[{i}]", "invalid")
            continue
        label = _label("input", i, spec.name)
        if not isinstance(spec.name, str) or _IO_NAME.fullmatch(spec.name) is None:
            out.add(None, 2, 1, f"{label}.name", "invalid_name")
        elif spec.name in seen:
            out.add(None, 2, 1, f"{label}.name", "duplicate")
        else:
            seen.add(spec.name)
        if spec.type not in ("str", "int"):
            out.add(None, 2, 2, f"{label}.type", "invalid")
        if type(spec.required) is not bool:
            out.add(None, 2, 2, f"{label}.required", "not_boolean")
        if not (_is_int(spec.max_length) and 1 <= spec.max_length <= 255):
            out.add(None, 2, 2, f"{label}.max_length", "out_of_range")
        if spec.regex is not None:
            ok = isinstance(spec.regex, str) and 1 <= len(spec.regex) <= 200
            if ok:
                try:
                    re.compile(spec.regex)
                except (re.error, RecursionError, OverflowError):
                    ok = False
            if not ok:
                out.add(None, 2, 2, f"{label}.regex", "invalid")
        if type(spec.secret) is not bool:
            out.add(None, 2, 2, f"{label}.secret", "not_boolean")
        elif spec.secret and spec.type != "str":
            out.add(None, 2, 4, f"{label}.secret", "secret_requires_str")
        if not isinstance(spec.description, str) or len(spec.description) > 200:
            out.add(None, 2, 3, f"{label}.description", "too_long")


def _check_outputs(flow: Flow, out: _Collector) -> None:
    seen: set[str] = set()
    for i, spec in enumerate(flow.outputs):
        if not isinstance(spec, OutputSpec):
            out.add(None, 3, 1, f"outputs[{i}]", "invalid")
            continue
        label = _label("output", i, spec.name)
        if not isinstance(spec.name, str) or _IO_NAME.fullmatch(spec.name) is None:
            out.add(None, 3, 1, f"{label}.name", "invalid_name")
        elif spec.name in seen:
            out.add(None, 3, 1, f"{label}.name", "duplicate")
        else:
            seen.add(spec.name)
        if spec.type not in ("str", "int"):
            out.add(None, 3, 1, f"{label}.type", "invalid")
        if not _is_sig_name(spec.signature):
            out.add(None, 3, 1, f"{label}.signature", "invalid_name")
        row_ok = _is_int(spec.row) and 0 <= spec.row <= 23
        col_ok = _is_int(spec.col) and 0 <= spec.col <= 79
        len_ok = _is_int(spec.length) and 1 <= spec.length <= 80
        if not row_ok:
            out.add(None, 3, 1, f"{label}.row", "out_of_range")
        if not col_ok:
            out.add(None, 3, 1, f"{label}.col", "out_of_range")
        if not len_ok:
            out.add(None, 3, 1, f"{label}.length", "out_of_range")
        if col_ok and len_ok and spec.col + spec.length > 80:
            out.add(None, 3, 1, f"{label}.length", "region_exceeds_row")


def _bodies_are_tuples(steps: object) -> bool:
    """True when every Handle_Step body, at any depth, is a tuple (so plan() works)."""
    if not isinstance(steps, tuple):
        return False
    for s in steps:
        if isinstance(s, HandleStep) and not _bodies_are_tuples(s.steps):
            return False
    return True


def _count(items: Iterable[PlanItem]) -> int:
    return sum(1 + _count(i.children) for i in items)


class _StepWalk:
    def __init__(self, flow: Flow, out: _Collector) -> None:
        self.out = out
        self.inputs = {
            s.name: s
            for s in flow.inputs
            if isinstance(s, InputSpec) and isinstance(s.name, str)
        }
        self.outputs = {
            s.name: s
            for s in flow.outputs
            if isinstance(s, OutputSpec) and isinstance(s.name, str)
        }
        self.extract_counts: dict[str, int] = {}

    def walk(self, items: tuple[PlanItem, ...], *, armed: bool, in_steps: bool) -> None:
        arming: ExpectStep | None = None
        for item in items:
            step, idx = item.step, item.index
            if isinstance(step, ExpectStep):
                self._expect(step, idx)
                armed, arming = True, step
            elif isinstance(step, TypeStep):
                self._type(step, idx, armed)
            elif isinstance(step, KeyStep):
                self._key(step, idx, armed)
                armed, arming = False, None
            elif isinstance(step, ExtractStep):
                self._extract(step, idx, arming, in_steps)
            elif isinstance(step, HandleStep):
                self._handle(item, step)
                armed, arming = False, None
            else:
                self.out.add(idx, 4, 9, "kind", f"unknown_kind '{echo_kind(getattr(step, 'kind', None))}'")

    def _expect(self, step: ExpectStep, idx: int) -> None:
        add = self.out.add
        sigs, tol = step.signatures, step.tolerate
        if (
            not isinstance(sigs, tuple)
            or not 1 <= len(sigs) <= 5
            or not all(_is_sig_name(s) for s in sigs)
        ):
            add(idx, 4, 1, "signatures", "invalid_list")
        elif len(set(sigs)) != len(sigs):
            add(idx, 4, 1, "signatures", "duplicate")
        if not isinstance(tol, tuple) or len(tol) > 5 or not all(_is_sig_name(s) for s in tol):
            add(idx, 4, 1, "tolerate", "invalid_list")
        else:
            if len(set(tol)) != len(tol):
                add(idx, 4, 1, "tolerate", "duplicate")
            if isinstance(sigs, tuple) and set(tol) & set(sigs):
                add(idx, 4, 1, "tolerate", "overlaps_signatures")
        if step.timeout is not None and not _in_range(step.timeout, 0.1, 60):
            add(idx, 4, 1, "timeout", "out_of_range")

    def _type(self, step: TypeStep, idx: int, armed: bool) -> None:
        add = self.out.add
        has_text, has_input = step.text is not None, step.input is not None
        if has_text == has_input:
            add(idx, 4, 10, "text" if has_text else "input", "exactly_one_required")
        elif has_text:
            text = step.text
            if not isinstance(text, str) or not 1 <= len(text) <= 255 or not _printable(text):
                add(idx, 4, 2, "text", "invalid_text")
            elif "${" in text:
                add(idx, 5, 11, "text", "interpolation_marker")
        else:
            if not isinstance(step.input, str) or step.input not in self.inputs:
                add(idx, 5, 2, "input", "undeclared_input")
        if not armed:
            add(idx, 5, 7, "type", "unarmed")

    def _key(self, step: KeyStep, idx: int, armed: bool) -> None:
        add = self.out.add
        if step.key not in _KEYS:
            add(idx, 4, 3, "key", "invalid")
        elif step.key in ("pf", "pa"):
            if not (_is_int(step.n) and 1 <= step.n <= 24):  # type: ignore[operator]
                add(idx, 4, 3, "n", "out_of_range")
        elif step.n is not None:
            add(idx, 4, 3, "n", "not_allowed")
        if not armed:
            add(idx, 5, 6, "key", "unarmed")

    def _extract(
        self, step: ExtractStep, idx: int, arming: ExpectStep | None, in_steps: bool
    ) -> None:
        add = self.out.add
        if not in_steps:
            add(idx, 4, 7, "extract", "not_in_steps")
        name = step.output
        spec = self.outputs.get(name) if isinstance(name, str) else None
        if spec is None:
            add(idx, 4, 4, "output", "undeclared_output")
            return
        if in_steps:
            self.extract_counts[name] = self.extract_counts.get(name, 0) + 1
        if arming is None or not isinstance(arming.signatures, tuple):
            add(idx, 5, 9, "output", "unarmed")
        elif spec.signature not in arming.signatures:
            add(idx, 5, 9, "output", "signature_not_in_arming_expect")

    def _handle(self, item: PlanItem, step: HandleStep) -> None:
        add, idx = self.out.add, item.index
        if not _is_sig_name(step.signature):
            add(idx, 4, 5, "signature", "invalid_name")
        if not (_is_int(step.max_count) and 1 <= step.max_count <= 20):  # type: ignore[operator]
            add(idx, 5, 4, "max_count", "out_of_range")
        if not _in_range(step.settle, 0, 10):
            add(idx, 4, 5, "settle", "out_of_range")
        if not 1 <= len(item.children) <= 50:
            add(idx, 4, 5, "steps", "invalid_size")
        body: list[PlanItem] = []
        for child in item.children:
            if isinstance(child.step, HandleStep):
                add(child.index, 5, 5, "handle", "nested_handle")
            elif not isinstance(child.step, (TypeStep, KeyStep)):
                add(child.index, 4, 5, "kind", "not_allowed_in_handle")
            else:
                body.append(child)
        self.walk(tuple(body), armed=True, in_steps=False)

    def finish(self) -> None:
        for i, spec in enumerate(self.outputs.values()):
            n = self.extract_counts.get(spec.name, 0)
            if n != 1:
                self.out.add(
                    None, 4, 7, _label("output", i, spec.name), "needs_exactly_one_extract"
                )


def _sort_key(v: Violation) -> tuple:
    if v.step_index is not None:
        return (0, v.step_index, v.requirement, v.criterion, v.field)
    return (1, 0, v.requirement, v.criterion, v.field)


def structural_violations(flow: Flow) -> list[Violation]:
    """Return every violation that needs no Signature set, first violation first."""
    out = _Collector()
    walk_ok = (
        isinstance(flow.steps, tuple)
        and isinstance(flow.finally_steps, tuple)
        and _bodies_are_tuples(flow.steps)
        and _bodies_are_tuples(flow.finally_steps)
    )
    if not walk_ok:
        out.add(None, 1, 6, "steps", "invalid")
        return out.items
    main, fin = plan(flow)
    _check_flow_fields(flow, out, _count(main), _count(fin))
    _check_inputs(flow, out)
    _check_outputs(flow, out)
    walker = _StepWalk(flow, out)
    walker.walk(main, armed=False, in_steps=True)
    walker.walk(fin, armed=False, in_steps=False)
    walker.finish()
    return sorted(out.items, key=_sort_key)


def reference_violations(flow: Flow, names: frozenset[str]) -> list[Violation]:
    """Report each Signature_Name used by the Flow that is not in ``names``."""
    out = _Collector()

    def check(items: tuple[PlanItem, ...]) -> None:
        for item in items:
            step = item.step
            if isinstance(step, ExpectStep):
                for field, used in (("signatures", step.signatures), ("tolerate", step.tolerate)):
                    for name in used:
                        if name not in names:
                            out.add(item.index, 5, 1, f"{field} {name}", "unknown_signature")
            elif isinstance(step, HandleStep):
                if step.signature not in names:
                    out.add(item.index, 5, 1, f"signature {step.signature}", "unknown_signature")
                check(item.children)

    main, fin = plan(flow)
    check(main)
    check(fin)
    for i, spec in enumerate(flow.outputs):
        if spec.signature not in names:
            out.add(
                None, 5, 1, f"{_label('output', i, spec.name)}.signature {spec.signature}",
                "unknown_signature",
            )
    return sorted(out.items, key=_sort_key)


def check_flow(flow: Flow, signatures: Iterable[ScreenSignature]) -> None:
    """Raise ``FlowDefinitionError`` for the first violation against ``signatures``."""
    names = frozenset(s.name for s in signatures)
    found = structural_violations(flow) + reference_violations(flow, names)
    if not found:
        return
    found.sort(key=_sort_key)
    first = found[0]
    if first.step_index is None:
        raise FlowDefinitionError(f"flow {flow.name}: field '{first.field}' violates rule '{first.rule}'")
    kind = _kind_of(flow, first.step_index)
    raise FlowDefinitionError(
        f"step {first.step_index} ({kind}): field '{first.field}' violates rule '{first.rule}'"
    )


def _kind_of(flow: Flow, index: int) -> str:
    def find(items: tuple[PlanItem, ...]) -> str | None:
        for item in items:
            if item.index == index:
                return getattr(item.step, "kind", "unknown")
            found = find(item.children)
            if found is not None:
                return found
        return None

    main, fin = plan(flow)
    return find(main) or find(fin) or "unknown"
