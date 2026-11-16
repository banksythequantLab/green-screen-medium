"""Property 13: ScreenView geometry matches Screen.fields / Screen.find_field."""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import small_screens


def _geom(f) -> tuple:
    return (f.start_row, f.start_col, f.byte_length, f.protected, f.hidden)


@st.composite
def _screens_with_cursor(draw):
    """small_screens (0, 1 and many SFs, hidden allowed) with the cursor often moved
    onto a cell inside a field, so the cursor-in-field branch is exercised."""
    screen = draw(small_screens(max_fields=6, allow_hidden=True))
    if screen.fields and draw(st.booleans()):
        f = draw(st.sampled_from(screen.fields))
        offset = draw(st.integers(0, f.byte_length))
        lin = (f.start_row * screen.columns + f.start_col + offset) % (
            screen.rows * screen.columns
        )
        screen.cursor_row, screen.cursor_col = divmod(lin, screen.columns)
    return screen


# Feature: screen-recognizer, Property 13: Geometry and Input_Field parity
@settings(max_examples=200, deadline=None)
@given(
    screen=_screens_with_cursor(),
    extra_cells=st.lists(
        st.tuples(st.integers(0, 23), st.integers(0, 79)), min_size=0, max_size=40
    ),
)
def test_geometry_and_input_field_parity(screen, extra_cells) -> None:
    """**Validates: Requirements 3.1, 3.8, 1.6, 1.7**"""
    view = ScreenView(screen)
    oracle = screen.fields

    # Every field matches in order and in all geometry attributes.
    assert [_geom(g) for g in view.fields] == [_geom(f) for f in oracle]
    for g in view.fields:
        assert g.linear_start == g.start_row * screen.columns + g.start_col

    # containing_field agrees with find_field at the interesting positions: each
    # field start, its neighbours in linear order, the cursor, the four corners
    # and a handful of random cells.
    rows, cols = screen.rows, screen.columns
    total = rows * cols
    probes: set[tuple[int, int]] = {
        (0, 0), (0, cols - 1), (rows - 1, 0), (rows - 1, cols - 1),
        (screen.cursor_row, screen.cursor_col),
    }
    for f in oracle:
        lin = f.start_row * cols + f.start_col
        for p in (lin - 1, lin, lin + 1):
            if 0 <= p < total:
                probes.add(divmod(p, cols))
    probes.update(extra_cells)
    for r, c in sorted(probes):
        if not (0 <= r < rows and 0 <= c < cols):
            continue
        got = view.containing_field(r, c)
        want = screen.find_field(r, c)
        if want is None:
            assert got is None, (r, c)
        else:
            assert got is not None and _geom(got) == _geom(want), (r, c)
    # input_fields: unprotected fields that are hidden or contain the cursor.
    cursor_field = screen.find_field(screen.cursor_row, screen.cursor_col)
    expected = [
        _geom(f)
        for f in oracle
        if not f.protected and (f.hidden or f == cursor_field)
    ]
    assert [_geom(g) for g in view.input_fields()] == expected
