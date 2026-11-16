from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from greenscreen.connector.models import SFToken

if TYPE_CHECKING:
    from greenscreen.connector.models import Screen
    from greenscreen.recognizer.signature import VolatileRegion


@dataclass(frozen=True, slots=True)
class FieldGeom:
    """Geometry and attributes of one field. Holds no cell content."""

    start_row: int
    start_col: int
    byte_length: int
    protected: bool
    hidden: bool
    linear_start: int  # start_row * columns + start_col


class ScreenView:
    """Blanked, content-safe view of a Screen.

    Reads ``Screen.cell_grid`` once in the constructor and keeps no reference
    to the Screen or its grids. Hidden data cells never appear in any
    attribute except as ``*`` in ``summary_rows`` and as marks in
    ``hidden_mask``.
    """

    __slots__ = (
        "rows",
        "columns",
        "cursor_row",
        "cursor_col",
        "fields",
        "base_rows",
        "hidden_mask",
        "_starts",
        "_summary_rows",
    )

    def __init__(self, screen: Screen) -> None:
        rows = screen.rows
        columns = screen.columns
        grid = screen.cell_grid
        total = rows * columns
        self.rows = rows
        self.columns = columns
        self.cursor_row = screen.cursor_row
        self.cursor_col = screen.cursor_col

        # Characters and SF positions in one pass.
        chars: list[str] = []
        sfs: list[tuple[int, int]] = []  # (linear, c0)
        for r in range(rows):
            row_cells = grid[r]
            for c in range(columns):
                cell = row_cells[c]
                if isinstance(cell, SFToken):
                    sfs.append((r * columns + c, cell.c0))
                    chars.append(" ")
                elif cell == 0x00:
                    chars.append(" ")
                else:
                    chars.append(chr(cell))

        # Field geometry, same arithmetic as Screen.fields.
        geoms: list[FieldGeom] = []
        n = len(sfs)
        for i, (linear, c0) in enumerate(sfs):
            if n == 1:
                length = total - 1
            else:
                next_linear = sfs[(i + 1) % n][0]
                if next_linear > linear:
                    length = next_linear - linear - 1
                else:
                    length = (total - linear - 1) + next_linear
            start_row, start_col = divmod(linear, columns)
            geoms.append(
                FieldGeom(
                    start_row=start_row,
                    start_col=start_col,
                    byte_length=length,
                    protected=bool(c0 & 0x20),
                    hidden=(c0 & 0x0C) == 0x0C,
                    linear_start=linear,
                )
            )
        self.fields = tuple(geoms)
        self._starts = tuple(g.linear_start for g in geoms)

        # Hidden mask over data cells.
        mask = bytearray(total)
        for g in geoms:
            if g.hidden:
                for offset in range(1, g.byte_length + 1):
                    mask[(g.linear_start + offset) % total] = 1
        self.hidden_mask = bytes(mask)

        base: list[str] = []
        summary: list[str] = []
        for r in range(rows):
            lo = r * columns
            hi = lo + columns
            base_chars = []
            sum_chars = []
            for i in range(lo, hi):
                if mask[i]:
                    base_chars.append(" ")
                    sum_chars.append("*")
                else:
                    ch = chars[i]
                    base_chars.append(ch)
                    sum_chars.append(ch)
            base.append("".join(base_chars))
            summary.append("".join(sum_chars).rstrip(" "))
        self.base_rows = tuple(base)
        self._summary_rows = tuple(summary)

    def visible_rows(self, volatile: Sequence[VolatileRegion]) -> tuple[str, ...]:
        """base_rows with every cell in any (clipped) volatile region blanked."""
        touched: dict[int, list[str]] = {}
        for region in volatile:
            if region.row < 0 or region.row >= self.rows:
                continue
            start = max(region.col, 0)
            end = min(region.col + region.length, self.columns)
            if start >= end:
                continue
            cells = touched.get(region.row)
            if cells is None:
                cells = list(self.base_rows[region.row])
                touched[region.row] = cells
            for c in range(start, end):
                cells[c] = " "
        if not touched:
            return self.base_rows
        return tuple(
            "".join(touched[r]) if r in touched else row
            for r, row in enumerate(self.base_rows)
        )

    def containing_field(self, row: int, col: int) -> FieldGeom | None:
        """Field containing (row, col), or None if outside the screen or unformatted."""
        if not self.fields:
            return None
        if not (0 <= row < self.rows and 0 <= col < self.columns):
            return None
        linear = row * self.columns + col
        idx = bisect_right(self._starts, linear) - 1
        # idx == -1 wraps to the last field.
        return self.fields[idx]

    def unprotected_fields(self) -> tuple[FieldGeom, ...]:
        return tuple(f for f in self.fields if not f.protected)

    def input_fields(self) -> tuple[FieldGeom, ...]:
        """Unprotected fields that are hidden or contain the cursor."""
        cursor_field = self.containing_field(self.cursor_row, self.cursor_col)
        return tuple(
            f
            for f in self.fields
            if not f.protected and (f.hidden or f is cursor_field)
        )

    def summary_rows(self) -> tuple[str, ...]:
        """Rows with hidden data cells as '*' and trailing spaces removed."""
        return self._summary_rows
