"""Property test: addressing outside the screen never raises (Property 11)."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.matching import matcher_satisfied, signature_matches
from greenscreen.recognizer.signature import (
    BeforeCursorMatcher,
    CursorFieldMatcher,
    RegionRegexMatcher,
    RowContainsMatcher,
    ScreenSignature,
    TextAtMatcher,
    VolatileRegion,
)
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import small_screens

_TEXT = st.text(alphabet="ABC xyz", min_size=1, max_size=8)


@st.composite
def _addressed(draw):
    """A text_at, row_contains or region_regex matcher with row/col up to 255."""
    kind = draw(st.sampled_from(["text_at", "row_contains", "region_regex"]))
    row = draw(st.integers(0, 255))
    if kind == "row_contains":
        return RowContainsMatcher(row=row, text=draw(_TEXT))
    if kind == "text_at":
        text = draw(_TEXT)
        col = draw(st.integers(0, 256 - len(text)))
        return TextAtMatcher(row=row, col=col, text=text)
    col = draw(st.integers(0, 255))
    length = draw(st.integers(1, 256 - col))
    return RegionRegexMatcher(row=row, col=col, length=length, pattern=".")


def _extent(m) -> tuple[int, int]:
    """(row, last column + 1) of the addressed rectangle; row_contains has width 0."""
    if isinstance(m, TextAtMatcher):
        return m.row, m.col + len(m.text)
    if isinstance(m, RegionRegexMatcher):
        return m.row, m.col + m.length
    return m.row, 0


def _is_outside(m, rows: int, cols: int) -> bool:
    row, end = _extent(m)
    return row >= rows or end > cols


def _overlaps(m, v: VolatileRegion) -> bool:
    row, end = _extent(m)
    if isinstance(m, RowContainsMatcher):
        return False
    return m.row == v.row and m.col < v.col + v.length and v.col < end


def _expected_rows(base: tuple[str, ...], vols, rows: int, cols: int):
    grid = [list(r) for r in base]
    for v in vols:
        if v.row >= rows:
            continue
        for c in range(v.col, min(v.col + v.length, cols)):
            grid[v.row][c] = " "
    return tuple("".join(r) for r in grid)


# Feature: screen-recognizer, Property 11: Out-of-screen addressing never raises
@settings(max_examples=200, deadline=None)
@given(
    screen=small_screens(),
    ms=st.lists(_addressed(), min_size=1, max_size=5),
    vols=st.lists(
        st.builds(
            VolatileRegion,
            row=st.integers(0, 255),
            col=st.integers(0, 255),
            length=st.integers(1, 12),
        ).filter(lambda v: v.col + v.length <= 256),
        max_size=4,
    ),
    cursor=st.tuples(st.integers(0, 255), st.integers(0, 255)),
    cursor_text=_TEXT,
)
def test_out_of_screen_addressing_never_raises(screen, ms, vols, cursor, cursor_text):
    """**Validates: Requirements 1.14, 2.6**"""
    rows, cols = screen.rows, screen.columns
    view = ScreenView(screen)

    # Volatile regions are clipped: result equals blanking only in-screen cells.
    visible = view.visible_rows(vols)
    assert visible == _expected_rows(view.base_rows, vols, rows, cols)
    assert len(visible) == rows and all(len(r) == cols for r in visible)

    # Matchers addressing outside the screen are unsatisfied, never raise.
    for m in ms:
        result = matcher_satisfied(m, visible, view)
        if _is_outside(m, rows, cols):
            assert result is False

    # Cursor-based matchers with the cursor outside the screen.
    screen.cursor_row, screen.cursor_col = cursor
    cview = ScreenView(screen)
    outside_cursor = cursor[0] >= rows or cursor[1] >= cols
    crows = cview.visible_rows(())
    before = BeforeCursorMatcher(text=cursor_text)
    cur_field = CursorFieldMatcher(row=cursor[0], col=cursor[1], hidden=False)
    r_before = matcher_satisfied(before, crows, cview)
    r_field = matcher_satisfied(cur_field, crows, cview)
    if outside_cursor:
        assert r_before is False
        assert r_field is False

    # A signature with an outside matcher does not match, and never raises.
    outside = [m for m in ms if _is_outside(m, rows, cols)]
    safe_vols = tuple(v for v in vols if not any(_overlaps(m, v) for m in ms))
    sig = ScreenSignature(name="probe", matchers=tuple(ms), volatile=safe_vols)
    matched = signature_matches(sig, view)
    if outside:
        assert matched is False
