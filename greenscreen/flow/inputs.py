"""Validation and rendering of Input values (Requirement 2.6 to 2.9).

No error message or attribute produced here contains a supplied value. A
``PreparedInputs`` holds the rendered values of supplied non-secret Inputs and
only the names of supplied Secret_Inputs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from greenscreen.flow.errors import FlowInputError
from greenscreen.flow.model import Flow


@dataclass(frozen=True, slots=True, repr=False)
class PreparedInputs:
    values: dict[str, str]  # rendered values of supplied non-secret Inputs
    supplied_secrets: frozenset[str]  # names only, never values

    def __repr__(self) -> str:
        return (
            f"PreparedInputs(values={sorted(self.values)!r}, "
            f"supplied_secrets={sorted(self.supplied_secrets)!r})"
        )


def _render(value: object) -> str | None:
    """Render a str or int; None if it cannot be rendered (huge int)."""
    if type(value) is str:
        return value  # type: ignore[return-value]
    try:
        return str(value)
    except ValueError:  # int too large for str() (digit limit)
        return None


def _is_printable_ascii(text: str) -> bool:
    return all(0x20 <= ord(ch) <= 0x7E for ch in text)


def prepare_inputs(flow: Flow, supplied: Mapping[str, object]) -> PreparedInputs:
    """Check ``supplied`` against ``flow.inputs`` and return the rendered values.

    Raises ``FlowInputError`` naming the Input and the rule for the first
    failure. Declared Inputs are checked in declaration order, then names that
    no Input declares in sorted order.
    """
    values: dict[str, str] = {}
    secrets: set[str] = set()
    declared = {spec.name for spec in flow.inputs}
    failure: tuple[str, str] | None = None
    value: object = None
    rendered: str | None = None

    for spec in flow.inputs:
        if spec.name not in supplied:
            if spec.required:
                failure = (spec.name, "required")
                break
            continue
        value = supplied[spec.name]
        if spec.type == "int":
            type_ok = type(value) is int  # a bool is not an int
        else:
            type_ok = type(value) is str
        if not type_ok:
            failure = (spec.name, "type")
            break
        rendered = _render(value)
        if rendered is None or len(rendered) > spec.max_length:
            failure = (spec.name, "max_length")
            break
        if not _is_printable_ascii(rendered):
            failure = (spec.name, "printable_ascii")
            break
        if spec.regex is not None and re.fullmatch(spec.regex, rendered) is None:
            failure = (spec.name, "regex")
            break
        if spec.secret:
            secrets.add(spec.name)
        else:
            values[spec.name] = rendered

    if failure is None:
        extra = [name for name in supplied if name not in declared]
        if extra:
            extra.sort(key=lambda n: (type(n).__name__, str(n)))
            failure = (extra[0], "undeclared")  # type: ignore[assignment]

    if failure is not None:
        # Requirement 14.7: no frame of the traceback may keep a supplied or
        # rendered value (the error names the Input and the rule only).
        values.clear()
        supplied = None  # type: ignore[assignment]
        value = rendered = None
        del supplied, value, rendered
        raise FlowInputError(failure[0], failure[1])
    return PreparedInputs(values=values, supplied_secrets=frozenset(secrets))
