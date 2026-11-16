from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Union


@dataclass(frozen=True)
class SFToken:
    """A 3270 field-attribute token; occupies one cell position in the buffer."""

    c0: int  # raw attribute byte, e.g. 0xc8, 0xe0


@dataclass(frozen=True)
class SAToken:
    """A 3270 color-attribute token (SA(42=xx)); does NOT occupy a cell position.

    Verified 2026-11-15: SA tokens do not occupy cells. Every row in both
    ReadBuffer captures has exactly 80 non-SA tokens, including logon rows
    that carry up to 8 SA tokens each.
    """

    value: int  # raw value byte, e.g. 0xf2


# CellValue is either an int (0x00–0xFF, the raw ASCII byte) or an SFToken.
# SAToken is recorded in a separate per-row list (not in the main cell grid).
CellValue = Union[int, SFToken]


@dataclass(frozen=True)
class StatusLine:
    """The 12-token status line that s3270 appends to every response."""

    keyboard_state: str     # field 1, e.g. "U"
    screen_formatting: str  # field 2
    field_protection: str   # field 3
    connection_state: str   # field 4, e.g. "C(127.0.0.1)"
    emulator_mode: str      # field 5
    model_number: str       # field 6, e.g. "2"
    rows: int               # field 7, decimal integer
    columns: int            # field 8, decimal integer
    cursor_row: int         # field 9, zero-origin
    cursor_col: int         # field 10, zero-origin
    window_id: str          # field 11, e.g. "0x0"
    command_time: str       # field 12, e.g. "0.006"

    def serialize(self) -> str:
        """Reconstruct the original 12-token status line string."""
        return (
            f"{self.keyboard_state} {self.screen_formatting} "
            f"{self.field_protection} {self.connection_state} "
            f"{self.emulator_mode} {self.model_number} "
            f"{self.rows} {self.columns} "
            f"{self.cursor_row} {self.cursor_col} "
            f"{self.window_id} {self.command_time}"
        )


@dataclass(frozen=True)
class Field:
    """A 3270 field: the span from one SF token to the cell before the next SF token,
    wrapping across row boundaries.

    Attribute byte (c0) bit definitions (IBM 3270 Data Stream Programmer's Reference):
      Bit 5 (0x20): protected  — operator cannot modify the field
      Bit 4 (0x10): numeric    — only numeric input accepted
      Bits 3,2 (0x0C): display intensity; 0x0C = non-display (hidden/password)
      Bit 0 (0x01): modified   — field has been modified since last read

    SECURITY: Components using Field objects MUST check `hidden` before logging
    or storing `text`. Hidden fields contain passwords and must never appear in
    logs or persistent storage.
    """
    start_row: int    # zero-origin row of the SF token
    start_col: int    # zero-origin col of the SF token
    byte_length: int  # number of data cells after the SF cell up to the next SF (wrapping)
    protected: bool   # bool(c0 & 0x20)
    numeric: bool     # bool(c0 & 0x10)
    hidden: bool      # (c0 & 0x0C) == 0x0C — non-display / password field
    modified: bool    # bool(c0 & 0x01)
    c0: int           # raw attribute byte, e.g. 0xc8
    text: str         # decoded field content, exactly byte_length chars
                      # (0x00 and SFToken cells → ' ', other bytes → chr(byte))


@dataclass
class Screen:
    """The central model holding the raw 3270 screen buffer.

    Primary storage is the cell grid; text_grid and fields are computed properties.
    """

    rows: int
    columns: int
    cursor_row: int   # zero-origin
    cursor_col: int   # zero-origin
    # Primary storage: raw cell grid.
    # Each row is exactly `columns` CellValues.
    # int cell = raw byte (0x00 stays 0x00, NOT promoted to space).
    # SFToken cell = field-attribute start at that position.
    cell_grid: list[list[CellValue]]
    # SA tokens: per-row list of (col_index, SAToken) pairs, in order of appearance.
    sa_tokens: list[list[tuple[int, SAToken]]]

    @staticmethod
    def _build_field(
        r: int,
        c: int,
        sf_tok: SFToken,
        byte_length: int,
        cell_grid: list[list[CellValue]],
        columns: int,
    ) -> "Field":
        """Shared helper: construct a Field from an SFToken position and span length.

        byte_length is the number of data cells following the SF cell (not counting
        the SF cell itself). text is decoded from those cells.
        This is the single construction path used by both Screen.fields and
        Screen.find_field, so the two code paths cannot drift.
        """
        total_cells = len(cell_grid) * columns
        sf_linear = r * columns + c
        chars: list[str] = []
        for offset in range(1, byte_length + 1):
            linear = (sf_linear + offset) % total_cells
            row_i, col_i = divmod(linear, columns)
            cell = cell_grid[row_i][col_i]
            if isinstance(cell, SFToken) or cell == 0x00:
                chars.append(' ')
            else:
                chars.append(chr(cell))
        text = ''.join(chars)
        c0 = sf_tok.c0
        return Field(
            start_row=r,
            start_col=c,
            byte_length=byte_length,
            protected=bool(c0 & 0x20),
            numeric=bool(c0 & 0x10),
            hidden=(c0 & 0x0C) == 0x0C,
            modified=bool(c0 & 0x01),
            c0=c0,
            text=text,
        )

    @property
    def text_grid(self) -> list[str]:
        """Derived view: one string per row.

        SFToken cells → ' ', int 0x00 → ' ', other int bytes → chr(byte).
        """
        rows = []
        for row in self.cell_grid:
            chars = []
            for cell in row:
                if isinstance(cell, SFToken):
                    chars.append(" ")
                elif cell == 0x00:
                    chars.append(" ")
                else:
                    chars.append(chr(cell))
            rows.append("".join(chars))
        return rows

    @property
    def fields(self) -> list[Field]:
        """Derived view: Fields from SF token positions, in linear order.

        A field runs from its SFToken cell to the cell before the next SFToken,
        wrapping across row boundaries. byte_length counts data cells only
        (the SF cell itself is not counted).
        """
        total_cells = self.rows * self.columns
        sf_positions: list[tuple[int, int, int, SFToken]] = []
        for row_i, row in enumerate(self.cell_grid):
            for col_i, cell in enumerate(row):
                if isinstance(cell, SFToken):
                    sf_positions.append((row_i * self.columns + col_i, row_i, col_i, cell))

        n = len(sf_positions)
        result: list[Field] = []
        for i, (linear_pos, r, c, sf_tok) in enumerate(sf_positions):
            if n == 1:
                byte_length = total_cells - 1
            else:
                next_linear = sf_positions[(i + 1) % n][0]
                if next_linear > linear_pos:
                    byte_length = next_linear - linear_pos - 1
                else:
                    # Wrapping: cells from sf+1 to end, then 0 to next_linear-1
                    byte_length = (total_cells - linear_pos - 1) + next_linear
            result.append(self._build_field(r, c, sf_tok, byte_length, self.cell_grid, self.columns))
        return result

    def text_at(self, row: int, col: int, length: int) -> str:
        """Extract `length` chars from text_grid[row] starting at col (zero-origin).

        Raises ValueError for any out-of-bounds argument.
        """
        if not (0 <= row < self.rows):
            raise ValueError(f"row {row} out of range [0, {self.rows - 1}]")
        if not (0 <= col < self.columns):
            raise ValueError(f"col {col} out of range [0, {self.columns - 1}]")
        if length < 1:
            raise ValueError(f"length must be >= 1, got {length}")
        if col + length > self.columns:
            raise ValueError(
                f"range [{col}, {col + length - 1}] exceeds row boundary {self.columns - 1}"
            )
        tg = self.text_grid
        return tg[row][col : col + length]

    def find_field(self, row: int, col: int) -> Field | None:
        """Return the Field containing (row, col), or None.

        On a formatted screen (at least one SF token) every cell position
        resolves to exactly one Field. Returns None only on an unformatted
        screen (no SF tokens).
        """
        total_cells = self.rows * self.columns
        target_linear = row * self.columns + col

        sf_positions: list[tuple[int, int, int, SFToken]] = []
        for r, row_cells in enumerate(self.cell_grid):
            for c_i, cell in enumerate(row_cells):
                if isinstance(cell, SFToken):
                    sf_positions.append((r * self.columns + c_i, r, c_i, cell))

        if not sf_positions:
            return None

        n = len(sf_positions)
        for i, (linear_pos, r, c, sf_tok) in enumerate(sf_positions):
            if n == 1:
                byte_length = total_cells - 1
                return self._build_field(r, c, sf_tok, byte_length, self.cell_grid, self.columns)

            next_linear = sf_positions[(i + 1) % n][0]
            if next_linear > linear_pos:
                # Non-wrapping span: [linear_pos, next_linear)
                if linear_pos <= target_linear < next_linear:
                    byte_length = next_linear - linear_pos - 1
                    return self._build_field(r, c, sf_tok, byte_length, self.cell_grid, self.columns)
            else:
                # Wrapping span: [linear_pos, total_cells) ∪ [0, next_linear)
                if target_linear >= linear_pos or target_linear < next_linear:
                    byte_length = (total_cells - linear_pos - 1) + next_linear
                    return self._build_field(r, c, sf_tok, byte_length, self.cell_grid, self.columns)
        return None

    def __eq__(self, other: object) -> bool:
        """Equality on cell_grid and sa_tokens only. Derived views are ignored."""
        if not isinstance(other, Screen):
            return NotImplemented
        return (
            self.rows == other.rows
            and self.columns == other.columns
            and self.cursor_row == other.cursor_row
            and self.cursor_col == other.cursor_col
            and self.cell_grid == other.cell_grid
            and self.sa_tokens == other.sa_tokens
        )


@dataclass(frozen=True)
class Response:
    """The parsed result of one s3270 action."""

    success: bool
    data_lines: list[str]  # "data: " prefix stripped
    status: StatusLine
