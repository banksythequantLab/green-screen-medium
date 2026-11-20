"""Immutable data model of a Flow and of a run result.

The classes here hold data only. ``Flow.__post_init__`` normalizes lists to
tuples and numbers to ``float`` and then asks ``validate.structural_violations``
for problems, so no invalid ``Flow`` exists. ``plan`` gives the Step_Index
numbering shared by the validator, the runner and the tests.
"""

from __future__ import annotations

import types
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Union

from greenscreen.flow.errors import FlowDefinitionError

if TYPE_CHECKING:  # pragma: no cover
    from greenscreen.recognizer import ScreenSignature


def _to_float(value: object) -> object:
    """Turn an int or float (never a bool) into a float; leave anything else."""
    if type(value) is int or type(value) is float:
        return float(value)  # type: ignore[arg-type]
    return value


def _to_tuple(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return value


@dataclass(frozen=True, slots=True)
class InputSpec:
    name: str
    type: str
    required: bool
    max_length: int
    regex: str | None = None
    secret: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class OutputSpec:
    name: str
    type: str
    signature: str
    row: int
    col: int
    length: int
    next_row: int | None = None  # first row of a continuation screen (Rows_Output)
    max_rows: int | None = None  # makes it a Rows_Output
    equals: str | None = None  # makes it a Flag_Output
    counts: str | None = None  # name of the Rows_Output whose row count this int output holds


@dataclass(frozen=True, slots=True)
class Timeouts:
    step: float = 10.0
    run: float = 120.0
    finally_: float = 30.0  # the YAML key is "finally"

    def __post_init__(self) -> None:
        for attr in ("step", "run", "finally_"):
            object.__setattr__(self, attr, _to_float(getattr(self, attr)))


@dataclass(frozen=True, slots=True)
class ExpectStep:
    kind: ClassVar[str] = "expect"
    signatures: tuple[str, ...]
    tolerate: tuple[str, ...] = ()
    timeout: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "signatures", _to_tuple(self.signatures))
        object.__setattr__(self, "tolerate", _to_tuple(self.tolerate))
        object.__setattr__(self, "timeout", _to_float(self.timeout))


@dataclass(frozen=True, slots=True)
class TypeStep:
    kind: ClassVar[str] = "type"
    text: str | None = None
    input: str | None = None


@dataclass(frozen=True, slots=True)
class KeyStep:
    kind: ClassVar[str] = "key"
    key: str
    n: int | None = None


@dataclass(frozen=True, slots=True)
class ExtractStep:
    kind: ClassVar[str] = "extract"
    output: str


@dataclass(frozen=True, slots=True)
class CollectStep:
    kind: ClassVar[str] = "collect"
    output: str
    more: str
    max_screens: int


@dataclass(frozen=True, slots=True)
class HandleStep:
    kind: ClassVar[str] = "handle"
    signature: str
    max_count: int
    steps: tuple[Union[TypeStep, KeyStep], ...]
    settle: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "steps", _to_tuple(self.steps))
        object.__setattr__(self, "settle", _to_float(self.settle))


Step = Union[ExpectStep, TypeStep, KeyStep, ExtractStep, CollectStep, HandleStep]


@dataclass(frozen=True, slots=True)
class Flow:
    name: str
    steps: tuple[Step, ...]
    description: str = ""
    inputs: tuple[InputSpec, ...] = ()
    outputs: tuple[OutputSpec, ...] = ()
    finally_steps: tuple[Step, ...] = ()
    timeouts: Timeouts = Timeouts()
    example: str = ""

    def __post_init__(self) -> None:
        for attr in ("steps", "inputs", "outputs", "finally_steps"):
            object.__setattr__(self, attr, _to_tuple(getattr(self, attr)))
        # Local import: validate.py imports this module.
        from greenscreen.flow.validate import structural_violations

        violations = structural_violations(self)
        if violations:
            first = violations[0]
            where = "flow" if first.step_index is None else f"step {first.step_index}"
            raise FlowDefinitionError(f"{where}: {first.field}: {first.rule}")

    def to_yaml(self) -> str:
        from greenscreen.flow.yamlio import to_yaml

        return to_yaml(self)

    @staticmethod
    def from_yaml(
        text: str, signatures: Iterable[ScreenSignature] | None = None
    ) -> Flow:
        from greenscreen.flow.yamlio import from_yaml

        return from_yaml(text, signatures)


@dataclass(frozen=True, slots=True)
class PlanItem:
    index: int  # Step_Index
    phase: str  # "steps" or "finally"
    step: Step
    children: tuple[PlanItem, ...] = ()


def _plan_list(
    steps: Iterable[Step], phase: str, start: int
) -> tuple[tuple[PlanItem, ...], int]:
    items: list[PlanItem] = []
    index = start
    for step in steps:
        own = index
        index += 1
        children: tuple[PlanItem, ...] = ()
        body = getattr(step, "steps", None) if isinstance(step, HandleStep) else None
        if body is not None:
            children, index = _plan_list(body, phase, index)
        items.append(PlanItem(own, phase, step, children))
    return tuple(items), index


def plan(flow: Flow) -> tuple[tuple[PlanItem, ...], tuple[PlanItem, ...]]:
    """Return (steps plan, finally plan) numbered depth-first.

    A Handle_Step takes its index before the Steps of its body, and the
    numbering of ``finally_steps`` continues after ``steps``.
    """
    main, next_index = _plan_list(flow.steps, "steps", 0)
    fin, _ = _plan_list(flow.finally_steps, "finally", next_index)
    return main, fin


@dataclass(frozen=True, slots=True)
class AuditRecord:
    step_index: int
    kind: str
    phase: str  # "steps" | "finally"
    iteration: int | None
    signature: str | None
    status: str  # "ok" | "skipped" | "failed"
    duration_seconds: float


@dataclass(frozen=True, slots=True, repr=False)
class FlowResult:
    flow: str
    outputs: Mapping[str, str | int]
    audit: tuple[AuditRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.outputs, types.MappingProxyType):
            object.__setattr__(
                self, "outputs", types.MappingProxyType(dict(self.outputs))
            )
        object.__setattr__(self, "audit", _to_tuple(self.audit))

    def __repr__(self) -> str:
        return (
            f"FlowResult(flow={self.flow!r}, outputs={list(self.outputs)!r}, "
            f"audit_records={len(self.audit)})"
        )
