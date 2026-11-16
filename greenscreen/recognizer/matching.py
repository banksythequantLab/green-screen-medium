"""Evaluate matchers and signatures against a ScreenView.

All text matchers read the rows returned by ``ScreenView.visible_rows``, so
hidden and volatile cells are already blank. ``field_layout`` and
``cursor_field`` read geometry only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from greenscreen.recognizer.signature import (
    BeforeCursorMatcher,
    CursorFieldMatcher,
    FieldLayoutMatcher,
    LastRowMatcher,
    Matcher,
    RegionRegexMatcher,
    RowContainsMatcher,
    ScreenSignature,
    TextAtMatcher,
)
from greenscreen.recognizer.view import ScreenView

_MAX_REGION = 256


def _text_at(m: TextAtMatcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    if not (0 <= m.row < view.rows) or m.col < 0:
        return False
    if m.col + len(m.text) > view.columns:
        return False
    return rows[m.row][m.col : m.col + len(m.text)] == m.text


def _row_contains(m: RowContainsMatcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    if not (0 <= m.row < view.rows):
        return False
    return m.text in rows[m.row]


def _field_layout(m: FieldLayoutMatcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    actual = [(f.start_row, f.start_col) for f in view.unprotected_fields()]
    return actual == [tuple(p) for p in m.positions]


def _cursor_field(m: CursorFieldMatcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    if not (0 <= view.cursor_row < view.rows and 0 <= view.cursor_col < view.columns):
        return False
    f = view.containing_field(view.cursor_row, view.cursor_col)
    if f is None or not any(f is g for g in view.input_fields()):
        return False
    return (f.start_row, f.start_col, f.hidden) == (m.row, m.col, m.hidden)


def _region_regex(m: RegionRegexMatcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    if not (0 <= m.row < view.rows) or m.col < 0 or m.length < 1:
        return False
    if m.col + m.length > view.columns or m._compiled is None:
        return False
    end = m.col + min(m.length, _MAX_REGION)
    return m._compiled.search(rows[m.row][m.col : end]) is not None


def _last_row(m: LastRowMatcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    for row in reversed(rows):
        stripped = row.rstrip(" ")
        if stripped:
            return stripped == m.text
    return False


def _before_cursor(m: BeforeCursorMatcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    r, c = view.cursor_row, view.cursor_col
    if not (0 <= r < view.rows and 0 <= c < view.columns):
        return False
    return rows[r][:c].rstrip(" ").endswith(m.text)


_DISPATCH: dict[type, Callable[[Any, tuple[str, ...], ScreenView], bool]] = {
    TextAtMatcher: _text_at,
    RowContainsMatcher: _row_contains,
    FieldLayoutMatcher: _field_layout,
    CursorFieldMatcher: _cursor_field,
    RegionRegexMatcher: _region_regex,
    LastRowMatcher: _last_row,
    BeforeCursorMatcher: _before_cursor,
}


def matcher_satisfied(m: Matcher, rows: tuple[str, ...], view: ScreenView) -> bool:
    try:
        fn = _DISPATCH[type(m)]
    except KeyError:
        raise TypeError(f"unknown matcher type {type(m).__name__}") from None
    return fn(m, rows, view)


def signature_matches(sig: ScreenSignature, view: ScreenView) -> bool:
    rows = view.visible_rows(sig.volatile)
    return all(matcher_satisfied(m, rows, view) for m in sig.matchers)
