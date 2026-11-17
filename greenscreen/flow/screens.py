"""Cell-level screen helpers for the flow runner.

This is the only module of the package that reads ``Screen.cell_grid``. It
never reads ``Screen.text_grid``, ``Screen.fields``, ``Screen.find_field`` or
``Field.text``, so the text of a hidden field is never turned into a ``str``.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import TYPE_CHECKING

from greenscreen.connector.models import Screen, SFToken

if TYPE_CHECKING:
    from greenscreen.recognizer.view import ScreenView

MDT = 0x01  # 3270 modified-data-tag bit of the attribute byte

# (rows, columns, ((linear_start, c0 & ~MDT), ...))
Geometry = tuple[int, int, tuple[tuple[int, int], ...]]


def geometry(screen: Screen) -> Geometry:
    """Size and field start positions with attribute bytes, MDT bit cleared.

    The protected bit (0x20) is not masked. Integer cells are never decoded.
    """
    columns = screen.columns
    starts: list[tuple[int, int]] = []
    for r, row in enumerate(screen.cell_grid):
        base = r * columns
        for c, cell in enumerate(row):
            if isinstance(cell, SFToken):
                starts.append((base + c, cell.c0 & ~MDT))
    return (screen.rows, columns, tuple(starts))


def build_comparison(
    pre: Screen,
    current: Screen,
    typed: Collection[tuple[int, int, int]],
) -> Screen:
    """Copy ``pre`` and restore the data cells of every Typed_Field from ``current``.

    ``typed`` holds ``(start_row, start_col, byte_length)`` triples. The caller
    has already checked that both screens have equal geometry, so every
    position inside a Typed_Field is a data cell on both screens. The cursor
    and SA tokens of ``pre`` are kept.
    """
    cols = pre.columns
    total = pre.rows * cols
    grid = [row[:] for row in pre.cell_grid]
    for row, col, length in typed:
        base = row * cols + col
        for offset in range(1, length + 1):
            r, c = divmod((base + offset) % total, cols)
            grid[r][c] = current.cell_grid[r][c]
    return Screen(
        rows=pre.rows,
        columns=cols,
        cursor_row=pre.cursor_row,
        cursor_col=pre.cursor_col,
        cell_grid=grid,
        sa_tokens=[list(t) for t in pre.sa_tokens],
    )


def read_region(
    screen: Screen, view: ScreenView, row: int, col: int, length: int
) -> str | None:
    """Return the text of a region, or ``None`` if any cell is hidden.

    No cell is read when a hidden cell is found. ``SFToken`` and ``0x00`` cells
    read as spaces. The caller guarantees the region lies inside the screen.
    """
    columns = view.columns
    base = row * columns + col
    mask = view.hidden_mask
    for i in range(base, base + length):
        if mask[i]:
            return None
    cells = screen.cell_grid[row]
    chars: list[str] = []
    for c in range(col, col + length):
        cell = cells[c]
        if isinstance(cell, SFToken) or cell == 0x00:
            chars.append(" ")
        else:
            chars.append(chr(cell))
    return "".join(chars)


def same_screen(a: Screen, b: Screen) -> bool:
    """True when cells, SA tokens and cursor are equal (``Screen.__eq__``)."""
    return a == b
