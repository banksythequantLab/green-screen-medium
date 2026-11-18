"""Flow loading, publication choice, schema generation and input checking.

Nothing here opens a session or a port. Every ``StartupError`` message holds
file, Flow and rule names, never a value.
"""
from __future__ import annotations

import types
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from greenscreen.flow import (
    Flow,
    FlowDefinitionError,
    FlowInputError,
    load_bundled_flows,
    load_flow,
)
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.flow.model import InputSpec
from greenscreen.publisher.config import StartupError
from greenscreen.publisher.vault import BoundValues, SecretBox
from greenscreen.recognizer import load_bundled_signatures

__all__ = [
    "PublishedFlow",
    "Registry",
    "load_flows",
    "select_published",
    "load_startup_signatures",
    "build_registry",
    "build_schemas",
    "check_inputs",
]

_OPEN_ALLOWANCE = 30.0  # seconds allowed for opening the session (Requirement 10.2)
_BUNDLED = "bundled"
_SAFE_ESCAPES = frozenset("dDwWsSbB")


@dataclass(frozen=True, slots=True)
class _Decl:
    """Stands in for a ``Flow`` in ``prepare_inputs``, which reads only ``inputs``."""

    inputs: tuple[InputSpec, ...]


@dataclass(frozen=True, slots=True)
class PublishedFlow:
    flow: Flow
    source: str  # "bundled" or the file name
    bound_names: frozenset[str]
    decl: _Decl  # Inputs minus bound ones, in declaration order
    input_schema: dict
    output_schema: dict
    success_schema: dict
    summary: str
    deadline: float


Registry = Mapping[str, PublishedFlow]


def load_flows(flows_dir: Path | None) -> dict[str, tuple[Flow, str]]:
    """Load and validate every Flow: bundled first, then ``flows_dir`` by file name."""
    loaded: dict[str, tuple[Flow, str]] = {}
    try:
        signatures = load_bundled_signatures()
        bundled = load_bundled_flows(signatures)
    except Exception:
        raise StartupError("bundled flows: load_failed") from None
    for name, flow in bundled.items():
        loaded[name] = (flow, _BUNDLED)
    if flows_dir is None:
        return loaded

    files: list[Path] | None = None
    try:
        if flows_dir.is_dir():
            files = sorted(p for p in flows_dir.iterdir() if p.is_file() and p.suffix == ".yaml")
    except OSError:
        files = None
    if files is None:
        raise StartupError(f"GS_FLOWS_DIR: not_a_readable_directory ({flows_dir})")

    for path in files:
        problem: str | None = None
        flow: Flow | None = None
        try:
            flow = load_flow(path, signatures)
        except FlowDefinitionError as exc:
            problem = str(exc)
        except Exception:
            problem = "file could not be loaded"
        if flow is None:
            raise StartupError(f"flow file {path.name}: {problem}")
        if flow.name in loaded:
            raise StartupError(
                f"{flow.name}: duplicate in {loaded[flow.name][1]} and {path.name}"
            )
        loaded[flow.name] = (flow, path.name)
    return loaded


def select_published(
    loaded: Mapping[str, tuple[Flow, str]], names: tuple[str, ...] | None
) -> dict[str, tuple[Flow, str]]:
    """Apply the Publish_List. Result keeps loading order, not list order."""
    if names is None:
        return dict(loaded) if not isinstance(loaded, dict) else loaded
    for name in names:
        if name not in loaded:
            raise StartupError(f"GS_PUBLISH_FLOWS: unknown_flow ({name})")
    wanted = set(names)
    return {name: item for name, item in loaded.items() if name in wanted}


def load_startup_signatures() -> Sequence:
    """One call of ``load_bundled_signatures()``; failure carries no cause."""
    try:
        return load_bundled_signatures()
    except Exception:
        raise StartupError("signatures: load_failed") from None


def _ecma_safe(regex: str) -> bool:
    """True when ``^(?:regex)$`` means the same in Python ``re`` and ECMA-262."""
    n = len(regex)
    i = 0
    prev = ""
    while i < n:
        ch = regex[i]
        if ch == "\\":
            if i + 1 >= n:
                return False
            nxt = regex[i + 1]
            if nxt.isalnum() or nxt == "_":
                if nxt not in _SAFE_ESCAPES:
                    return False
            i += 2
            prev = ""  # an escaped char is a plain atom
            continue
        if ch == "(" and regex.startswith("(?", i) and not regex.startswith("(?:", i):
            return False
        if ch == "[" and regex.startswith("[:", i):
            return False
        if ch == "+" and prev in ("*", "+", "?", "}"):
            return False
        prev = ch
        i += 1
    return True


def _input_property(spec: InputSpec) -> dict:
    if spec.type == "int":
        m = spec.max_length
        prop: dict = {
            "type": "integer",
            "maximum": 10**m - 1,
            "minimum": -(10 ** (m - 1) - 1) if m > 1 else 0,
        }
    else:
        prop = {"type": "string", "maxLength": spec.max_length}
        if spec.regex is not None and _ecma_safe(spec.regex):
            prop["pattern"] = f"^(?:{spec.regex})$"
    if spec.secret:
        prop["writeOnly"] = True
    if spec.description:
        prop["description"] = spec.description
    return prop


def build_schemas(
    flow: Flow, bound_names: frozenset[str] = frozenset()
) -> tuple[dict, dict, dict]:
    """The one Schema_Generator: ``(input_schema, output_schema, success_schema)``."""
    inputs = [s for s in flow.inputs if s.name not in bound_names]
    input_schema: dict = {
        "type": "object",
        "properties": {s.name: _input_property(s) for s in inputs},
        "additionalProperties": False,
    }
    required = [s.name for s in inputs if s.required]
    if required:
        input_schema["required"] = required

    output_schema: dict = {
        "type": "object",
        "properties": {
            o.name: {"type": "integer" if o.type == "int" else "string"} for o in flow.outputs
        },
        "additionalProperties": False,
        "required": [o.name for o in flow.outputs],
    }
    audit_props = {
        "step_index": {"type": "integer"},
        "kind": {"type": "string"},
        "phase": {"type": "string"},
        "iteration": {"type": ["integer", "null"]},
        "signature": {"type": ["string", "null"]},
        "status": {"type": "string"},
        "duration_seconds": {"type": "number"},
    }
    success_schema: dict = {
        "type": "object",
        "properties": {
            "flow": {"type": "string"},
            "outputs": {
                "type": "object",
                "properties": {k: dict(v) for k, v in output_schema["properties"].items()},
                "additionalProperties": False,
                "required": list(output_schema["required"]),
            },
            "audit": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": audit_props,
                    "additionalProperties": False,
                    "required": list(audit_props),
                },
            },
        },
        "additionalProperties": False,
        "required": ["flow", "outputs", "audit"],
    }
    return input_schema, output_schema, success_schema


def build_registry(
    published: Mapping[str, tuple[Flow, str]], bound: BoundValues, call_timeout: float
) -> Registry:
    """Immutable mapping of the Published_Flows, in publication order."""
    entries: dict[str, PublishedFlow] = {}
    for name, (flow, source) in published.items():
        bound_names = frozenset(bound.names_for(name))
        inp, out, suc = build_schemas(flow, bound_names)
        entries[name] = PublishedFlow(
            flow=flow,
            source=source,
            bound_names=bound_names,
            decl=_Decl(tuple(s for s in flow.inputs if s.name not in bound_names)),
            input_schema=inp,
            output_schema=out,
            success_schema=suc,
            summary=flow.description or f"Run flow {name}.",
            deadline=min(
                call_timeout,
                flow.timeouts.run + flow.timeouts.finally_ + _OPEN_ALLOWANCE,
            ),
        )
    return types.MappingProxyType(entries)


def check_inputs(published: PublishedFlow, box: SecretBox) -> str | None:
    """Validate the supplied values; return the error message, or ``None``."""
    message: str | None = None
    try:
        prepare_inputs(published.decl, box.mapping())  # type: ignore[arg-type]
    except FlowInputError as exc:
        message = str(exc)
    return message
