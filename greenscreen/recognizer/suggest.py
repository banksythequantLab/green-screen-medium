"""suggest_signature: build a ScreenSignature from a live Screen.

Reads the screen only through ScreenView (blanked rows, hidden mask, geometry).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.signature import (
    CursorFieldMatcher,
    FieldLayoutMatcher,
    ScreenSignature,
    TextAtMatcher,
    VolatileRegion,
)
from greenscreen.recognizer.view import ScreenView

if TYPE_CHECKING:
    from greenscreen.connector.models import Screen

_VOLATILE = re.compile(
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"|(?:[01][0-9]|2[0-3]):[0-5][0-9]"
    r"|(?:0[1-9]|[12][0-9]|3[01])\.[0-9]{2}\.[0-9]{2}",
    re.ASCII,
)
# Text runs: no excluded cell (marked \x00) and no two consecutive spaces.
_SEGMENT = re.compile(r"[^ \x00](?: ?[^ \x00])*")

_MAX_VOLATILE = 50
_MAX_CANDIDATES = 3
_MAX_COORD = 255
_MAX_NAME = 64
_DEFAULT_NAME = "unnamed-screen"


def suggest_signature(screen: Screen, name: str | None = None) -> ScreenSignature:
    view = ScreenView(screen)
    rows = view.base_rows
    columns = view.columns

    if all(r.rstrip(" ") == "" for r in rows) and not view.fields:
        raise SignatureError("screen has no identifying features")

    # Volatile runs, in reading order. All are excluded from text matchers.
    regions: list[VolatileRegion] = []
    excluded: list[set[int]] = []
    for r, text in enumerate(rows):
        cols: set[int] = set()
        for m in _VOLATILE.finditer(text):
            start, end = m.span()
            cols.update(range(start, end))
            if len(regions) < _MAX_VOLATILE and end - 1 <= _MAX_COORD:
                regions.append(VolatileRegion(r, start, end - start))
        excluded.append(cols)

    # Selected row: first with stable (non-space, non-excluded) text.
    selected: int | None = None
    for r, text in enumerate(rows):
        if any(ch != " " and c not in excluded[r] for c, ch in enumerate(text)):
            selected = r
            break

    matchers: list = []
    stable = ""
    if selected is not None:
        r0 = selected
        stable = "".join(
            " " if c in excluded[r0] else ch for c, ch in enumerate(rows[r0])
        )
        marked = "".join(
            "\x00" if c in excluded[r0] else ch for c, ch in enumerate(rows[r0])
        )
        base = r0 * columns
        count = 0
        for m in _SEGMENT.finditer(marked):
            if count >= _MAX_CANDIDATES:
                break
            count += 1
            start, end = m.span()
            if any(view.hidden_mask[base + c] for c in range(start, end)):
                continue
            if end - 1 > _MAX_COORD:
                continue
            matchers.append(TextAtMatcher(r0, start, m.group()))

    unprotected = view.unprotected_fields()
    if unprotected:
        matchers.append(
            FieldLayoutMatcher(
                len(unprotected),
                tuple((f.start_row, f.start_col) for f in unprotected),
            )
        )

    cursor_field = view.containing_field(view.cursor_row, view.cursor_col)
    if cursor_field is not None and any(
        cursor_field is f for f in view.input_fields()
    ):
        matchers.append(
            CursorFieldMatcher(
                cursor_field.start_row, cursor_field.start_col, cursor_field.hidden
            )
        )

    if not matchers:
        matchers.append(FieldLayoutMatcher(0, ()))

    if name is None:
        derived = re.sub(r"[^a-z0-9-]+", "-", stable.lower()).strip("-")[:_MAX_NAME].strip("-")
        name = derived or _DEFAULT_NAME

    return ScreenSignature(
        name=name,
        matchers=tuple(matchers),
        volatile=tuple(sorted(regions, key=lambda v: (v.row, v.col))),
        description="",
    )
