"""Exceptions raised by the screen recognizer.

None of these derives from ``ConnectorError``, and none stores a ``Screen``,
a grid or a ``Field``.
"""

from __future__ import annotations

from typing import Any


class RecognizerError(Exception):
    """Base class for all recognizer errors."""


class SignatureError(RecognizerError):
    """A signature is invalid, malformed or unreadable."""


class UnknownScreenError(RecognizerError):
    """No signature matched the screen."""

    summary: Any  # RedactedSummary

    def __init__(self, message: str, *, summary: Any) -> None:
        super().__init__(message)
        self.summary = summary


class AmbiguousScreenError(RecognizerError):
    """More than one signature matched the screen."""

    names: tuple[str, ...]

    def __init__(self, message: str, *, names: tuple[str, ...]) -> None:
        super().__init__(message)
        self.names = tuple(names)
