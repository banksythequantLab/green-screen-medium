"""Property 6: text_at extracts the correct substring (Task 8.5).

Feature: tn3270-connector
Validates: Requirements 5.6, 5.7
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.connector.models import Screen, SFToken, SAToken


@st.composite
def arbitrary_screen(draw):
    """Build a Screen from a raw cell grid with SF tokens at chosen positions."""
    rows = draw(st.one_of(st.integers(1, 6), st.integers(1, 24)))
    cols = draw(st.one_of(st.integers(1, 8), st.integers(1, 80)))
    total = rows * cols

    sf_linears = draw(
        st.lists(st.integers(min_value=0, max_value=total - 1),
                 min_size=0, max_size=min(10, total), unique=True)
    )
    sf_c0s = draw(st.lists(st.integers(0, 0xFF),
                           min_size=len(sf_linears), max_size=len(sf_linears)))

    # Bulk-draw all cells as one binary blob; bias toward 0x00 by zeroing
    # all bytes below a per-example threshold.
    zero_below = draw(st.sampled_from([0, 0, 64, 192, 256]))
    raw = draw(st.binary(min_size=total, max_size=total))
    flat = [0 if b < zero_below else b for b in raw]
    for lin, c0 in zip(sf_linears, sf_c0s):
        flat[lin] = SFToken(c0=c0)
    cell_grid = [flat[r * cols:(r + 1) * cols] for r in range(rows)]

    sa_tokens = [[] for _ in range(rows)]
    cursor_row = draw(st.integers(min_value=0, max_value=rows - 1))
    cursor_col = draw(st.integers(min_value=0, max_value=cols - 1))
    return Screen(rows, cols, cursor_row, cursor_col, cell_grid, sa_tokens)


def _expected_char(cell) -> str:
    if isinstance(cell, SFToken) or cell == 0x00:
        return " "
    return chr(cell)


@given(st.data())
@settings(max_examples=200, deadline=None)
def test_text_at_matches_text_grid_slice(data) -> None:
    # Feature: tn3270-connector, Property 6: text_at extracts the correct substring
    screen = data.draw(arbitrary_screen())
    row = data.draw(st.integers(min_value=0, max_value=screen.rows - 1))
    col = data.draw(st.integers(min_value=0, max_value=screen.columns - 1))
    length = data.draw(st.integers(min_value=1, max_value=screen.columns - col))

    result = screen.text_at(row, col, length)

    assert result == screen.text_grid[row][col:col + length]
    assert len(result) == length


@given(st.data())
@settings(max_examples=200, deadline=None)
def test_text_at_out_of_bounds_raises(data) -> None:
    # Feature: tn3270-connector, Property 6: text_at extracts the correct substring
    screen = data.draw(arbitrary_screen())
    rows, cols = screen.rows, screen.columns
    row = data.draw(st.integers(min_value=0, max_value=rows - 1))
    col = data.draw(st.integers(min_value=0, max_value=cols - 1))
    length = data.draw(st.integers(min_value=1, max_value=cols - col))

    bad_row = data.draw(st.one_of(
        st.integers(max_value=-1), st.integers(min_value=rows)))
    bad_col = data.draw(st.one_of(
        st.integers(max_value=-1), st.integers(min_value=cols)))
    bad_length = data.draw(st.integers(max_value=0))
    too_long = data.draw(st.integers(min_value=cols - col + 1, max_value=cols + 200))

    with pytest.raises(ValueError):
        screen.text_at(bad_row, col, length)
    with pytest.raises(ValueError):
        screen.text_at(row, bad_col, length)
    with pytest.raises(ValueError):
        screen.text_at(row, col, bad_length)
    with pytest.raises(ValueError):
        screen.text_at(row, col, too_long)


@given(st.data())
@settings(max_examples=200, deadline=None)
def test_text_at_cell_decoding(data) -> None:
    # Feature: tn3270-connector, Property 6: text_at extracts the correct substring
    screen = data.draw(arbitrary_screen())
    row = data.draw(st.integers(min_value=0, max_value=screen.rows - 1))
    col = data.draw(st.integers(min_value=0, max_value=screen.columns - 1))
    length = data.draw(st.integers(min_value=1, max_value=screen.columns - col))

    expected = "".join(
        _expected_char(c) for c in screen.cell_grid[row][col:col + length]
    )
    assert screen.text_at(row, col, length) == expected
