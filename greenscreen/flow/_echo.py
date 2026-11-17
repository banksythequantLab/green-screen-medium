"""Shared sanitiser for echoing an untrusted Step kind in an error message."""

from __future__ import annotations

import re

_KIND_ECHO = re.compile(r"[A-Za-z0-9_-]{1,32}")


def echo_kind(kind: object) -> str:
    """Return ``kind`` if it is 1 to 32 of ``[A-Za-z0-9_-]``, else ``<invalid>``."""
    if isinstance(kind, str) and _KIND_ECHO.fullmatch(kind):
        return kind
    return "<invalid>"
