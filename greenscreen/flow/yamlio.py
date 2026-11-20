"""Flow <-> YAML (schema version 1) and ``load_flow``.

Parsing uses ``yaml.safe_load`` only and emitting uses ``yaml.safe_dump`` only.
Error messages contain only key names, zero-origin list indexes, line and
column numbers, and (for an unsupported Step kind) a short echo of the kind
that matches ``[A-Za-z0-9_-]{1,32}``. No message uses ``str()`` of a YAML error
or any other YAML scalar. Every ``FlowDefinitionError`` for a YAML or file
problem is raised after the ``except`` block has ended, so ``__cause__`` and
``__context__`` are ``None``.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

import yaml

from greenscreen.flow._echo import echo_kind
from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import (
    CollectStep,
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

if TYPE_CHECKING:  # pragma: no cover
    from greenscreen.recognizer import ScreenSignature

_VERSION = 1
_NOT_MAPPING = "document is not a mapping"

# Schemas: key -> type word, in emitted order.
_TOP = {
    "version": "int",
    "name": "str",
    "description": "str",
    "example": "str",
    "inputs": "list",
    "outputs": "list",
    "timeouts": "dict",
    "steps": "list",
    "finally": "list",
}
_INPUT = {
    "name": "str",
    "type": "str",
    "required": "bool",
    "max_length": "int",
    "secret": "bool",
    "regex": "str",
    "description": "str",
}
_OUTPUT = {
    "name": "str",
    "type": "str",
    "signature": "str",
    "row": "int",
    "col": "int",
    "length": "int",
}
# Optional output keys, emitted after the six above and only when not None.
_OUTPUT_OPTIONAL = {"next_row": "int", "max_rows": "int", "equals": "str", "counts": "str"}
_TIMEOUTS = {"step": "num", "run": "num", "finally": "num"}
_STEP = {
    "expect": {"signatures": "strlist", "tolerate": "strlist", "timeout": "num"},
    "type": {"text": "str", "input": "str"},
    "key": {"key": "str", "n": "int"},
    "extract": {"output": "str"},
    "collect": {"output": "str", "more": "str", "max_screens": "int"},
    "handle": {"signature": "str", "max_count": "int", "settle": "num", "steps": "list"},
}
_STEP_REQUIRED = {
    "expect": ("signatures",),
    "type": (),  # exactly-one rule is checked by the validator
    "key": ("key",),
    "extract": ("output",),
    "collect": ("output", "more", "max_screens"),
    "handle": ("signature", "max_count", "steps"),
}
_WORDS = {
    "int": "an integer",
    "str": "a string",
    "bool": "a boolean",
    "num": "a number",
    "list": "a list",
    "dict": "a mapping",
    "strlist": "a list of strings",
}


# --------------------------------------------------------------------- emit


def _step_to_mapping(step: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": step.kind}
    if isinstance(step, ExpectStep):
        d["signatures"] = list(step.signatures)
        if step.tolerate:
            d["tolerate"] = list(step.tolerate)
        if step.timeout is not None:
            d["timeout"] = step.timeout
    elif isinstance(step, TypeStep):
        if step.text is not None:
            d["text"] = step.text
        if step.input is not None:
            d["input"] = step.input
    elif isinstance(step, KeyStep):
        d["key"] = step.key
        if step.n is not None:
            d["n"] = step.n
    elif isinstance(step, ExtractStep):
        d["output"] = step.output
    elif isinstance(step, CollectStep):
        d["output"] = step.output
        d["more"] = step.more
        d["max_screens"] = step.max_screens
    else:
        d["signature"] = step.signature
        d["max_count"] = step.max_count
        d["settle"] = step.settle
        d["steps"] = [_step_to_mapping(s) for s in step.steps]
    return d


def _input_to_mapping(spec: InputSpec) -> dict[str, Any]:
    d: dict[str, Any] = {
        "name": spec.name,
        "type": spec.type,
        "required": spec.required,
        "max_length": spec.max_length,
        "secret": spec.secret,
    }
    if spec.regex is not None:
        d["regex"] = spec.regex
    if spec.description != "":
        d["description"] = spec.description
    return d


def _output_to_mapping(spec: OutputSpec) -> dict[str, Any]:
    d: dict[str, Any] = {
        "name": spec.name,
        "type": spec.type,
        "signature": spec.signature,
        "row": spec.row,
        "col": spec.col,
        "length": spec.length,
    }
    for key in _OUTPUT_OPTIONAL:
        value = getattr(spec, key, None)
        if value is not None:
            d[key] = value
    return d


def to_yaml(flow: Flow) -> str:
    """Emit ``flow`` as a version-1 YAML document with a fixed key order."""
    doc: dict[str, Any] = {
        "version": _VERSION,
        "name": flow.name,
        "description": flow.description,
    }
    example = getattr(flow, "example", "")
    if example != "":
        doc["example"] = example
    doc.update(
        {
            "inputs": [_input_to_mapping(i) for i in flow.inputs],
            "outputs": [_output_to_mapping(o) for o in flow.outputs],
            "timeouts": {
                "step": flow.timeouts.step,
                "run": flow.timeouts.run,
                "finally": flow.timeouts.finally_,
            },
            "steps": [_step_to_mapping(s) for s in flow.steps],
            "finally": [_step_to_mapping(s) for s in flow.finally_steps],
        }
    )
    return yaml.safe_dump(
        doc,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=False,
        width=10_000,
        indent=2,
    )


# -------------------------------------------------------------------- parse


def _key_text(key: Any) -> str:
    return key[:64] if isinstance(key, str) else "<non-string>"


def _type_ok(v: Any, word: str) -> bool:
    if word == "int":
        return type(v) is int
    if word == "bool":
        return type(v) is bool
    if word == "num":
        return type(v) is int or type(v) is float
    if word == "str":
        return isinstance(v, str)
    if word == "list":
        return isinstance(v, list)
    if word == "dict":
        return isinstance(v, dict)
    return isinstance(v, list) and all(isinstance(x, str) for x in v)  # strlist


def _check_keys(
    where: str,
    obj: dict,
    schema: dict[str, str],
    required: tuple[str, ...],
    skip: tuple[str, ...] = (),
) -> None:
    prefix = f"{where}: " if where else ""
    for key in obj:
        if not isinstance(key, str):
            raise FlowDefinitionError(f"{prefix}mapping key must be a string")
        if key not in schema and key not in skip:
            raise FlowDefinitionError(f"{prefix}unknown key '{_key_text(key)}'")
    for key in required:
        if key not in obj:
            raise FlowDefinitionError(f"{prefix}missing key '{key}'")
    for key, word in schema.items():
        if key in obj and not _type_ok(obj[key], word):
            raise FlowDefinitionError(f"{prefix}key '{key}' must be {_WORDS[word]}")


def _check_version(obj: dict) -> None:
    if "version" not in obj:
        raise FlowDefinitionError("missing key 'version'")
    v = obj["version"]
    if not (type(v) is int and v == _VERSION):
        raise FlowDefinitionError(
            f"key 'version' must be the integer {_VERSION} (found type {type(v).__name__})"
        )


def _list_items(where: str, items: list) -> list[tuple[str, dict]]:
    out = []
    for i, item in enumerate(items):
        w = f"{where}[{i}]"
        if not isinstance(item, dict):
            raise FlowDefinitionError(f"{w}: item is not a mapping")
        out.append((w, item))
    return out


def _step_from_mapping(where: str, m: dict, *, in_body: bool) -> Any:
    kind = m.get("kind") if "kind" in m else None
    if "kind" not in m:
        raise FlowDefinitionError(f"{where}: missing key 'kind'")
    if not isinstance(kind, str):
        raise FlowDefinitionError(f"{where}: key 'kind' must be a string")
    if kind not in _STEP or (in_body and kind not in ("type", "key")):
        raise FlowDefinitionError(f"{where}: unsupported step kind '{echo_kind(kind)}'")
    _check_keys(where, m, _STEP[kind], _STEP_REQUIRED[kind], skip=("kind",))
    if kind == "expect":
        return ExpectStep(
            signatures=tuple(m["signatures"]),
            tolerate=tuple(m.get("tolerate", ())),
            timeout=m.get("timeout"),
        )
    if kind == "type":
        return TypeStep(text=m.get("text"), input=m.get("input"))
    if kind == "key":
        return KeyStep(key=m["key"], n=m.get("n"))
    if kind == "extract":
        return ExtractStep(output=m["output"])
    if kind == "collect":
        return CollectStep(
            output=m["output"], more=m["more"], max_screens=m["max_screens"]
        )
    body = [
        _step_from_mapping(w, item, in_body=True)
        for w, item in _list_items(f"{where} steps", m["steps"])
    ]
    return HandleStep(
        signature=m["signature"],
        max_count=m["max_count"],
        steps=tuple(body),
        settle=m.get("settle", 0.0),
    )


def _build_flow(obj: Any) -> Flow:
    if not isinstance(obj, dict):
        raise FlowDefinitionError(_NOT_MAPPING)
    if "version" in obj:
        _check_version(obj)
    _check_keys("", obj, _TOP, ("version", "name", "steps"))
    _check_version(obj)

    inputs = []
    for w, m in _list_items("inputs", obj.get("inputs", [])):
        _check_keys(w, m, _INPUT, ("name", "type", "required", "max_length"))
        inputs.append(
            InputSpec(
                name=m["name"],
                type=m["type"],
                required=m["required"],
                max_length=m["max_length"],
                regex=m.get("regex"),
                secret=m.get("secret", False),
                description=m.get("description", ""),
            )
        )
    outputs = []
    for w, m in _list_items("outputs", obj.get("outputs", [])):
        _check_keys(w, m, {**_OUTPUT, **_OUTPUT_OPTIONAL}, tuple(_OUTPUT))
        outputs.append(
            OutputSpec(
                **{k: m[k] for k in _OUTPUT},
                **{k: m[k] for k in _OUTPUT_OPTIONAL if k in m},
            )
        )

    timeouts = Timeouts()
    if "timeouts" in obj:
        t = obj["timeouts"]
        _check_keys("timeouts", t, _TIMEOUTS, ())
        timeouts = Timeouts(
            step=t.get("step", 10.0),
            run=t.get("run", 120.0),
            finally_=t.get("finally", 30.0),
        )
    steps = [
        _step_from_mapping(w, m, in_body=False)
        for w, m in _list_items("steps", obj["steps"])
    ]
    fin = [
        _step_from_mapping(w, m, in_body=False)
        for w, m in _list_items("finally", obj.get("finally", []))
    ]
    return Flow(
        name=obj["name"],
        steps=tuple(steps),
        description=obj.get("description", ""),
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        finally_steps=tuple(fin),
        timeouts=timeouts,
        example=obj.get("example", ""),
    )


def _safe_load(text: Any) -> Any:
    """Parse YAML; the error is raised after the except block has ended."""
    if not isinstance(text, str):
        raise FlowDefinitionError("YAML text must be a string")
    if text.strip() == "":
        raise FlowDefinitionError(_NOT_MAPPING)
    message: str | None = None
    doc: Any = None
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = getattr(mark, "line", None)
        column = getattr(mark, "column", None)
        if isinstance(line, int) and isinstance(column, int):
            message = f"malformed YAML at line {line + 1}, column {column + 1}"
        else:
            message = "malformed YAML"
    except (RecursionError, ValueError, TypeError, OverflowError):
        message = "malformed YAML"
    if message is not None:
        raise FlowDefinitionError(message)
    return doc


def _finish(flow: Flow, signatures: Iterable[ScreenSignature] | None) -> Flow:
    from greenscreen.flow.validate import check_flow

    if signatures is None:
        from greenscreen.recognizer import load_bundled_signatures

        signatures = load_bundled_signatures()
    check_flow(flow, signatures)
    return flow


def from_yaml(
    text: str, signatures: Iterable[ScreenSignature] | None = None
) -> Flow:
    """Parse one Flow document and check it against ``signatures``."""
    flow = _build_flow(_safe_load(text))
    return _finish(flow, signatures)


def load_flow(
    path: str | os.PathLike[str],
    signatures: Iterable[ScreenSignature] | None = None,
) -> Flow:
    """Load a Flow from a UTF-8 YAML file."""
    text: str | None = None
    try:
        with open(path, "r", encoding="utf-8", newline=None) as fh:
            text = fh.read()
    except (OSError, ValueError, TypeError):
        text = None
    if text is None:
        raise FlowDefinitionError(f"flow file could not be read: {path}")
    return from_yaml(text, signatures)
