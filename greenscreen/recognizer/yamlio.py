"""Signature <-> YAML (schema version 1) and ``load_signatures``.

Parsing uses ``yaml.safe_load`` only and emitting uses ``yaml.safe_dump`` only.
Error messages contain only key names, signature names, matcher kinds, line and
column numbers and zero-origin indexes. The one YAML scalar that may be echoed
is a truncated ``version`` value. No message uses ``str()`` of a YAML error.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.signature import (
    BeforeCursorMatcher,
    CursorFieldMatcher,
    FieldLayoutMatcher,
    LastRowMatcher,
    RegionRegexMatcher,
    RowContainsMatcher,
    ScreenSignature,
    TextAtMatcher,
    VolatileRegion,
)

logger = logging.getLogger("greenscreen.recognizer")

_VERSION = 1
_INVALID_STRUCTURE = "document structure is invalid"

_DOC_REQUIRED = ("version", "name", "matchers")

# kind -> ((key, expected type), ...) in emitted order, excluding "kind".
_MATCHER_SCHEMA: dict[str, tuple[tuple[str, type], ...]] = {
    "text_at": (("row", int), ("col", int), ("text", str)),
    "row_contains": (("row", int), ("text", str)),
    "field_layout": (("count", int), ("positions", list)),
    "cursor_field": (("row", int), ("col", int), ("hidden", bool)),
    "region_regex": (("row", int), ("col", int), ("length", int), ("pattern", str)),
    "last_row": (("text", str),),
    "before_cursor": (("text", str),),
}
_MATCHER_CLASSES = {
    "text_at": TextAtMatcher,
    "row_contains": RowContainsMatcher,
    "cursor_field": CursorFieldMatcher,
    "region_regex": RegionRegexMatcher,
    "last_row": LastRowMatcher,
    "before_cursor": BeforeCursorMatcher,
}
_TYPE_WORDS = {int: "an integer", str: "a string", bool: "a boolean", list: "a list"}
_POSITION_KEYS = (("row", int), ("col", int))
_VOLATILE_KEYS = (("row", int), ("col", int), ("length", int))


# --------------------------------------------------------------------- emit


def _matcher_to_mapping(m: Any) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": m.kind}
    if isinstance(m, FieldLayoutMatcher):
        d["count"] = m.count
        d["positions"] = [{"row": p[0], "col": p[1]} for p in m.positions]
        return d
    for key, _ in _MATCHER_SCHEMA[m.kind]:
        d[key] = getattr(m, key)
    return d


def to_yaml(sig: ScreenSignature) -> str:
    """Emit ``sig`` as a version-1 YAML document with a fixed key order."""
    doc: dict[str, Any] = {
        "version": _VERSION,
        "name": sig.name,
        "description": sig.description,
        "matchers": [_matcher_to_mapping(m) for m in sig.matchers],
        "volatile": [
            {"row": v.row, "col": v.col, "length": v.length} for v in sig.volatile
        ],
    }
    if sig.stable_for > 0:
        items = list(doc.items())
        items.insert(3, ("stable_for", float(sig.stable_for)))
        doc = dict(items)
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


def _check_keys(
    where: str,
    obj: dict,
    schema: tuple[tuple[str, type], ...],
    *,
    required: tuple[str, ...] | None = None,
    skip: tuple[str, ...] = (),
) -> None:
    """Check unknown, missing and wrongly typed keys of ``obj``."""
    allowed = {k for k, _ in schema} | set(skip)
    prefix = f"{where}: " if where else ""
    for key in obj:
        if not isinstance(key, str):
            raise SignatureError(f"{prefix}mapping key must be a string")
        if key not in allowed:
            raise SignatureError(f"{prefix}unknown key '{_key_text(key)}'")
    req = required if required is not None else tuple(k for k, _ in schema)
    for key in req:
        if key not in obj:
            raise SignatureError(f"{prefix}missing key '{key}'")
    for key, expected in schema:
        if key not in obj:
            continue
        v = obj[key]
        ok = type(v) is bool if expected is bool else (
            type(v) is int if expected is int else isinstance(v, expected)
        )
        if not ok:
            raise SignatureError(f"{prefix}key '{key}' must be {_TYPE_WORDS[expected]}")


def _check_version(obj: dict) -> None:
    if "version" not in obj:
        raise SignatureError("missing key 'version'")
    v = obj["version"]
    if not (type(v) is int and v == _VERSION):
        shown = repr(v)[:32]
        raise SignatureError(f"unsupported version {shown} (type {type(v).__name__})")


def _matcher_from_mapping(index: int, m: Any) -> Any:
    if not isinstance(m, dict):
        raise SignatureError(f"matchers[{index}]: {_INVALID_STRUCTURE}")
    kind = m.get("kind") if "kind" in m else None
    if not isinstance(kind, str) or kind not in _MATCHER_SCHEMA:
        raise SignatureError(f"matchers[{index}]: unknown or missing 'kind'")
    where = f"matchers[{index}] ({kind})"
    _check_keys(where, m, _MATCHER_SCHEMA[kind], skip=("kind",))
    if kind == "field_layout":
        positions = []
        for i, p in enumerate(m["positions"]):
            pwhere = f"{where} positions[{i}]"
            if not isinstance(p, dict):
                raise SignatureError(f"{pwhere}: {_INVALID_STRUCTURE}")
            _check_keys(pwhere, p, _POSITION_KEYS)
            positions.append((p["row"], p["col"]))
        if m["count"] != len(positions):
            raise SignatureError(f"{where}: key 'count' differs from number of positions")
        return FieldLayoutMatcher(count=m["count"], positions=tuple(positions))
    cls = _MATCHER_CLASSES[kind]
    return cls(**{k: m[k] for k, _ in _MATCHER_SCHEMA[kind]})


def _build_signature(obj: Any) -> ScreenSignature:
    if not isinstance(obj, dict):
        raise SignatureError(_INVALID_STRUCTURE)
    if "version" in obj:
        _check_version(obj)
    schema = (
        ("version", int),
        ("name", str),
        ("description", str),
        ("matchers", list),
        ("volatile", list),
    )
    _check_keys("", obj, schema, required=_DOC_REQUIRED, skip=("stable_for",))
    _check_version(obj)
    stable_for = obj.get("stable_for", 0.0)
    if type(stable_for) not in (int, float):
        raise SignatureError("key 'stable_for' must be a number")

    matchers = tuple(_matcher_from_mapping(i, m) for i, m in enumerate(obj["matchers"]))
    volatile = []
    for j, v in enumerate(obj.get("volatile", [])):
        vwhere = f"volatile[{j}]"
        if not isinstance(v, dict):
            raise SignatureError(f"{vwhere}: {_INVALID_STRUCTURE}")
        _check_keys(vwhere, v, _VOLATILE_KEYS)
        volatile.append(VolatileRegion(row=v["row"], col=v["col"], length=v["length"]))
    return ScreenSignature(
        name=obj["name"],
        matchers=matchers,
        volatile=tuple(volatile),
        description=obj.get("description", ""),
        stable_for=stable_for,
    )


def _signature_from_mapping(obj: Any, index: int | None = None) -> ScreenSignature:
    """Build a signature from a parsed mapping; ``index`` prefixes list items."""
    try:
        return _build_signature(obj)
    except SignatureError as exc:
        if index is None:
            raise
        raise SignatureError(f"signature[{index}]: {exc}") from None


def _safe_load(text: Any) -> Any:
    if not isinstance(text, str):
        raise SignatureError("YAML text must be a string")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = getattr(mark, "line", None)
        column = getattr(mark, "column", None)
        if isinstance(line, int) and isinstance(column, int):
            raise SignatureError(
                f"malformed YAML at line {line + 1}, column {column + 1}"
            ) from None
        raise SignatureError("malformed YAML") from None
    except RecursionError:
        raise SignatureError(_INVALID_STRUCTURE) from None


def from_yaml(text: str) -> ScreenSignature:
    """Parse one signature mapping. A list or an empty document is rejected."""
    return _signature_from_mapping(_safe_load(text))


def load_signatures(path: str | os.PathLike[str]) -> list[ScreenSignature]:
    """Load one mapping or a list of mappings from a YAML file, in file order."""
    try:
        with open(path, "r", encoding="utf-8", newline=None) as fh:
            text = fh.read()
    except (OSError, ValueError, TypeError):
        raise SignatureError(f"signature file could not be read: {path}") from None

    doc = _safe_load(text)
    if isinstance(doc, dict):
        items = [doc]
        indexed = False
    elif isinstance(doc, list):
        items = doc
        indexed = True
    else:
        raise SignatureError(_INVALID_STRUCTURE)

    sigs = [
        _signature_from_mapping(item, i if indexed else None)
        for i, item in enumerate(items)
    ]
    first: dict[str, int] = {}
    for i, sig in enumerate(sigs):
        if sig.name in first:
            raise SignatureError(
                f"duplicate signature name '{sig.name}' at indexes {first[sig.name]} and {i}"
            )
        first[sig.name] = i
    logger.debug("loaded %d signatures", len(sigs))
    return sigs
