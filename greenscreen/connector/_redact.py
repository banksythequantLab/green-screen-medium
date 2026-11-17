"""Action redaction: turns an s3270 Action into text that may leave the Connector.

A String() Action can carry a host password, so its argument is never shown;
only the decoded length is. Every other Action is returned unchanged.
"""
from __future__ import annotations

import re

from greenscreen.connector.parser import _unescape_s3270_string

# "String" in any ASCII letter case, optional whitespace, "(".
# Explicit [Ss][Tt]... classes are used instead of re.IGNORECASE because
# IGNORECASE on a str pattern also folds U+017F and U+212A onto ASCII letters.
# \s on a str pattern is Unicode whitespace, which is the str.isspace() set.
_STRING_NAME = re.compile(r"\s*[Ss][Tt][Rr][Ii][Nn][Gg]\s*\(")

# Whole-Action shape of a Well_Formed_String_Action. Group 1 is the body.
# DOTALL lets "\." match a backslash followed by a newline. Nothing is
# allowed after ")" (used with fullmatch).
_WELL_FORMED = re.compile(
    r'\s*[Ss][Tt][Rr][Ii][Nn][Gg]\s*\(\s*"((?:[^"\\]|\\.)*)"\s*\)',
    re.DOTALL,
)


def redact_action(action: str) -> str:
    """Return ``action`` unchanged unless it is a String Action.

    A well-formed String Action becomes ``String(<N chars>)``; a malformed
    one becomes ``String(<? chars>)``. Pure: no logging, state or I/O.
    """
    if _STRING_NAME.match(action) is None:
        return action
    m = _WELL_FORMED.fullmatch(action)
    if m is None:
        return "String(<? chars>)"
    n = len(_unescape_s3270_string(m.group(1)))
    return f"String(<{n} chars>)"
