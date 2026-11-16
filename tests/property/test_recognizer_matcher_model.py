"""Property test: matchers agree with an independent direct model (screen-recognizer)."""
from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.matching import matcher_satisfied, signature_matches
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
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import (
    _overlaps,
    matchers,
    small_screens,
    volatile_regions,
)

_PATTERNS = [r"[A-Z]+", r"\d+", r"^ *$", r"READY", r"[^ ]{1,8}-", r"x|y", r"."]


# ------------------------------------------------------------------ oracle

def _oracle_rows(screen, regions):
    """Visible_Text from text_grid, blanking hidden data cells and volatile regions."""
    rows, cols = screen.rows, screen.columns
    total = rows * cols
    grid = [list(r) for r in screen.text_grid]
    for f in screen.fields:
        if f.hidden:  # attributes only; Field.text is never read
            start = f.start_row * cols + f.start_col
            for off in range(1, f.byte_length + 1):
                lin = (start + off) % total
                grid[lin // cols][lin % cols] = " "
    for reg in regions:
        if 0 <= reg.row < rows:
            for c in range(reg.col, reg.col + reg.length):
                if 0 <= c < cols:
                    grid[reg.row][c] = " "
    return ["".join(r) for r in grid]


def _oracle_satisfied(m, screen, rows) -> bool:
    R, C = screen.rows, screen.columns
    kind = m.kind
    if kind == "text_at":
        if not (0 <= m.row < R) or m.col + len(m.text) > C:
            return False
        return rows[m.row][m.col : m.col + len(m.text)] == m.text
    if kind == "row_contains":
        return 0 <= m.row < R and m.text in rows[m.row]
    if kind == "field_layout":
        pos = [(f.start_row, f.start_col) for f in screen.fields if not f.protected]
        return pos == list(m.positions) and len(pos) == m.count
    if kind == "cursor_field":
        cr, cc = screen.cursor_row, screen.cursor_col
        if not (0 <= cr < R and 0 <= cc < C):
            return False
        f = screen.find_field(cr, cc)
        if f is None or f.protected:  # cursor is inside f, so unprotected == Input_Field
            return False
        return (f.start_row, f.start_col, f.hidden) == (m.row, m.col, m.hidden)
    if kind == "region_regex":
        if not (0 <= m.row < R) or m.col + m.length > C:
            return False
        return re.compile(m.pattern).search(rows[m.row][m.col : m.col + m.length]) is not None
    if kind == "last_row":
        nonblank = [r for r in rows if r.strip(" ") != ""]
        return bool(nonblank) and nonblank[-1].rstrip(" ") == m.text
    if kind == "before_cursor":
        cr, cc = screen.cursor_row, screen.cursor_col
        if not (0 <= cr < R and 0 <= cc < C):
            return False
        return rows[cr][:cc].rstrip(" ").endswith(m.text)
    raise AssertionError(kind)


# ------------------------------------------------------------- strategies

@st.composite
def _targeted_matchers(draw, screen, regions):
    """Matchers aimed at the oracle view of the screen, some deliberately wrong."""
    rows = _oracle_rows(screen, regions)
    R, C = screen.rows, screen.columns
    kind = draw(st.sampled_from(
        ["text_at", "row_contains", "field_layout", "cursor_field",
         "region_regex", "last_row", "before_cursor"]))
    r = draw(st.integers(0, R - 1))
    c = draw(st.integers(0, C - 1))
    n = draw(st.integers(1, 10))
    sl = rows[r][c : c + n] or " "
    if draw(st.booleans()):  # sometimes corrupt the text so the matcher fails
        sl = sl[:-1] + draw(st.sampled_from("QZ!"))
    if kind == "text_at":
        return TextAtMatcher(r, c, sl)
    if kind == "row_contains":
        return RowContainsMatcher(r, sl)
    if kind == "field_layout":
        pos = [(f.start_row, f.start_col) for f in screen.fields if not f.protected]
        if draw(st.booleans()) and pos:
            pos = pos[:-1]
        return FieldLayoutMatcher(len(pos), tuple(pos))
    if kind == "cursor_field":
        f = screen.find_field(screen.cursor_row, screen.cursor_col)
        if f is not None and draw(st.booleans()):
            return CursorFieldMatcher(f.start_row, f.start_col, f.hidden != draw(st.booleans()))
        return CursorFieldMatcher(r, c, draw(st.booleans()))
    if kind == "region_regex":
        return RegionRegexMatcher(r, c, draw(st.integers(1, 40)), draw(st.sampled_from(_PATTERNS)))
    if kind == "last_row":
        nonblank = [x for x in rows if x.strip(" ") != ""]
        text = nonblank[-1].rstrip(" ") if nonblank else sl
        if draw(st.booleans()):
            text = text.lstrip(" ") or sl
        return LastRowMatcher(text)
    # before_cursor
    cr, cc = screen.cursor_row, screen.cursor_col
    before = rows[cr][:cc].rstrip(" ")
    text = before[-draw(st.integers(1, 5)):] if before else sl
    return BeforeCursorMatcher(text or sl)


@st.composite
def _cases(draw):
    screen = draw(small_screens(allow_hidden=True, max_fields=6))
    regions = draw(st.lists(volatile_regions(), max_size=3))
    ms = draw(st.lists(
        st.one_of(_targeted_matchers(screen, regions), matchers()),
        min_size=1, max_size=6))
    regions = [v for v in regions if not any(_overlaps(m, v) for m in ms)]
    sig = ScreenSignature(name="sig", matchers=ms, volatile=regions)
    return screen, sig


# Feature: screen-recognizer, Property 10: Matchers agree with a direct model
# **Validates: Requirements 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.15, 1.16, 3.4, 3.5**
@settings(max_examples=300, deadline=None)
@given(case=_cases())
def test_matchers_agree_with_direct_model(case):
    screen, sig = case
    rows = _oracle_rows(screen, sig.volatile)
    view = ScreenView(screen)
    view_rows = view.visible_rows(sig.volatile)
    assert list(view_rows) == rows

    expected = []
    for m in sig.matchers:
        want = _oracle_satisfied(m, screen, rows)
        expected.append(want)
        assert matcher_satisfied(m, view_rows, view) is want, m
    assert signature_matches(sig, view) is all(expected)
