"""Exceptions of the flow runtime.

None of these classes derives from ``ConnectorError`` or ``RecognizerError``.
None stores a ``Screen``, ``Field`` or input value; ``summary`` is a
``RedactedSummary`` whose hidden cells are already masked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from greenscreen.flow.model import AuditRecord
    from greenscreen.recognizer.summary import RedactedSummary

REASON_CODES: tuple[str, ...] = (
    "input_invalid",
    "timeout",
    "run_timeout",
    "unknown_screen",
    "ambiguous_screen",
    "unexpected_screen",
    "loop_limit",
    "bad_target",
    "secret_target",
    "hidden_output",
    "output_type",
    "screen_size",
    "session_error",
)

_MAX_MESSAGE = 500
_INPUT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")


class FlowError(Exception):
    """Raised when a run stops. Carries plain data only."""

    reason: str
    step_index: int | None
    kind: str | None
    expected: tuple[str, ...]
    summary: RedactedSummary | None
    audit: tuple[AuditRecord, ...]

    def __init__(
        self,
        reason: str,
        *,
        step_index: int | None,
        kind: str | None,
        expected: Iterable[str],
        summary: RedactedSummary | None,
        audit: Iterable[AuditRecord],
        detail: str = "",
    ) -> None:
        names = tuple(sorted(expected))
        message = (
            f"{reason} at step {'none' if step_index is None else step_index} "
            f"({kind if kind else 'none'}): expected "
            f"{','.join(names) if names else 'none'} ({len(names)})"
        )
        if detail:
            message += f"; {detail}"
        message = " ".join(message.split())[:_MAX_MESSAGE]
        super().__init__(message)
        self.reason = reason
        self.step_index = step_index
        self.kind = kind
        self.expected = names
        self.summary = summary
        self.audit = tuple(audit)


class FlowInputError(FlowError):
    """An Input value or name violates the Flow's declaration."""

    def __init__(self, name: str, rule: str) -> None:
        shown = name if isinstance(name, str) and _INPUT_NAME.fullmatch(name) else "<invalid name>"
        super().__init__(
            "input_invalid",
            step_index=None,
            kind=None,
            expected=(),
            summary=None,
            audit=(),
            detail=f"input {shown} violates {rule}",
        )


class FlowDefinitionError(Exception):
    """A Flow cannot be loaded or validated."""
