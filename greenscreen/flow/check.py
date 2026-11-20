"""Check a Flow YAML file: ``python -m greenscreen.flow.check <file.yaml>``.

Validates the file against the bundled signatures and changes nothing. Exit
codes: 0 valid, 1 violation, 2 usage, 3 file missing or unreadable, 4 not a
YAML mapping, 5 bundled signatures could not be loaded.

Output carries no YAML value and no screen data: only the file name, the
``FlowDefinitionError`` message (key names, step indexes, rule names) and,
for a parse failure, the line and column of the parser's mark.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import Flow

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2
EXIT_NO_FILE = 3
EXIT_NOT_YAML = 4
EXIT_NO_SIGNATURES = 5

USAGE = "usage: python -m greenscreen.flow.check <file.yaml>"
_MAX_LINE = 200


def _clean(value: str) -> str:
    """Printable ASCII only, at most 200 characters."""
    out = "".join(c if " " <= c <= "~" else "?" for c in value)
    return out[:_MAX_LINE]


def _fail(code: int, line: str) -> int:
    print(_clean(line), file=sys.stderr)
    return code


def _read_bytes(path: Path) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except (OSError, ValueError):
        return None


def _parse(data: bytes) -> tuple[str | None, str]:
    """Return (decoded text or None, error line). Text is None on failure."""
    message = "error: not a YAML mapping"
    decoded: str | None = None
    try:
        decoded = data.decode("utf-8")
        doc: Any = yaml.safe_load(decoded)
        if not isinstance(doc, dict):
            decoded = None
    except yaml.YAMLError as exc:
        decoded = None
        mark = getattr(exc, "problem_mark", None)
        line = getattr(mark, "line", None)
        column = getattr(mark, "column", None)
        if isinstance(line, int) and isinstance(column, int):
            message += f" (line {line + 1}, column {column + 1})"
    except (UnicodeDecodeError, RecursionError, ValueError, TypeError, OverflowError):
        decoded = None
    return decoded, message


def _signatures() -> Any:
    try:
        from greenscreen.recognizer import load_bundled_signatures

        return list(load_bundled_signatures())
    except Exception:  # noqa: BLE001 - any failure is exit 5, nothing printed from it
        return None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] == "" or args[0].startswith("-"):
        return _fail(EXIT_USAGE, USAGE)
    path = Path(args[0])

    data = _read_bytes(path)
    if data is None:
        return _fail(EXIT_NO_FILE, "error: file not found or not readable")

    flow_text, parse_error = _parse(data)
    if flow_text is None:
        return _fail(EXIT_NOT_YAML, parse_error)

    signatures = _signatures()
    if signatures is None:
        return _fail(EXIT_NO_SIGNATURES, "error: bundled signatures could not be loaded")

    message: str | None = None
    try:
        Flow.from_yaml(flow_text, signatures)
    except FlowDefinitionError as exc:
        message = str(exc)
    if message is not None:
        return _fail(EXIT_VIOLATION, "violation: " + message)

    print("ok: " + _clean(path.name))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
