"""Property test for Visible_Text construction (screen-recognizer)."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.signature import VolatileRegion
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import small_screens


@st.composite
def _regions(draw) -> VolatileRegion:
    col = draw(st.integers(0, 255))
    return VolatileRegion(
        row=draw(st.integers(0, 255)),
        col=col,
        length=draw(st.integers(1, 256 - col)),
    )


# Feature: screen-recognizer, Property 12: Visible_Text construction
# **Validates: Requirements 2.1, 2.5, 2.7, 3.6, 13.2**
@settings(max_examples=200, deadline=None)
@given(
    screen=small_screens(allow_hidden=True),
    regions=st.lists(_regions(), max_size=8),
    near=st.lists(st.tuples(st.integers(0, 23), st.integers(0, 79), st.integers(1, 30)), max_size=6),
)
def test_visible_rows_construction(screen, regions, near):
    # Regions near/inside the screen (overlapping, possibly running off the edge).
    regions = list(regions) + [VolatileRegion(r, c, n) for r, c, n in near]

    expected = [list(row) for row in screen.text_grid]
    for f in screen.fields:
        if f.hidden:
            total = screen.rows * screen.columns
            start = f.start_row * screen.columns + f.start_col
            for off in range(1, f.byte_length + 1):
                lin = (start + off) % total
                expected[lin // screen.columns][lin % screen.columns] = " "
    for reg in regions:
        if 0 <= reg.row < screen.rows:
            for c in range(reg.col, reg.col + reg.length):
                if 0 <= c < screen.columns:
                    expected[reg.row][c] = " "
    expected_rows = tuple("".join(r) for r in expected)

    view = ScreenView(screen)
    assert view.visible_rows(regions) == expected_rows

    if not any(f.hidden for f in screen.fields):
        assert view.visible_rows([]) == tuple(screen.text_grid)
