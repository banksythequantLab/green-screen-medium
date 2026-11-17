"""ScreenParser: parses s3270 ReadBuffer(Ascii) responses into Screen objects.

Also provides s3270 String() argument escaping helpers.
"""
from __future__ import annotations

import re

from greenscreen.connector.exceptions import ParseError
from greenscreen.connector.models import (
    CellValue,
    Response,
    SAToken,
    SFToken,
    Screen,
    StatusLine,
)

# ---------------------------------------------------------------------------
# Token patterns
# ---------------------------------------------------------------------------
_HEX_CELL = re.compile(r"^[0-9a-fA-F]{2}$")
_SF_TOKEN = re.compile(r"^SF\(c0=([0-9a-fA-F]{2})\)$")
_SA_TOKEN = re.compile(r"^SA\(42=([0-9a-fA-F]{2})\)$")


# ---------------------------------------------------------------------------
# s3270 String() argument escaping helpers
# ---------------------------------------------------------------------------


def _escape_s3270_string(text: str) -> str:
    """Encode a Python string for s3270 String() argument.

    Rules (order matters — backslashes first):
      1. \\ → \\\\
      2. " → \\"
    Returns the escaped text WITHOUT the surrounding double-quote wrapper
    (the caller adds those).
    """
    text = text.replace("\\", "\\\\")  # step 1: backslashes first
    text = text.replace('"', '\\"')    # step 2: double-quotes
    return text


def _unescape_s3270_string(escaped: str) -> str:
    """Inverse of _escape_s3270_string.

    Also used by _redact.py to count the Decoded_Length of a String Action.

    Processes escape sequences left-to-right; \\X → X for any X.
    """
    result: list[str] = []
    i = 0
    while i < len(escaped):
        if escaped[i] == "\\" and i + 1 < len(escaped):
            result.append(escaped[i + 1])
            i += 2
        else:
            result.append(escaped[i])
            i += 1
    return "".join(result)


# ---------------------------------------------------------------------------
# ScreenParser
# ---------------------------------------------------------------------------


class ScreenParser:
    """Parses s3270 ReadBuffer(Ascii) responses into Screen objects."""

    def parse_status_line(self, raw: str) -> StatusLine:
        """Parse a 12-token s3270 status line. Raises ParseError on failure."""
        tokens = raw.split()
        if len(tokens) != 12:
            raise ParseError(
                f"Status line must have 12 tokens, got {len(tokens)}: {raw!r}",
                raw=raw,
            )
        int_field_names = ("rows", "columns", "cursor_row", "cursor_col")
        int_field_indices = (6, 7, 8, 9)
        parsed: dict[str, int] = {}
        for name, idx in zip(int_field_names, int_field_indices):
            try:
                parsed[name] = int(tokens[idx])
            except ValueError:
                raise ParseError(
                    f"Status line field '{name}' is not a decimal integer"
                    f" (got {tokens[idx]!r}): {raw!r}",
                    raw=raw,
                )
        return StatusLine(
            keyboard_state=tokens[0],
            screen_formatting=tokens[1],
            field_protection=tokens[2],
            connection_state=tokens[3],
            emulator_mode=tokens[4],
            model_number=tokens[5],
            rows=parsed["rows"],
            columns=parsed["columns"],
            cursor_row=parsed["cursor_row"],
            cursor_col=parsed["cursor_col"],
            window_id=tokens[10],
            command_time=tokens[11],
        )

    def parse_readbuffer(self, response: Response) -> Screen:
        """Build a Screen from a single ReadBuffer(Ascii) response.

        Derives rows, columns, cursor_row, cursor_col from response.status.
        Tokenizes response.data_lines to build cell_grid and sa_tokens.
        """
        status = response.status
        rows = status.rows
        cols = status.columns
        cell_grid, sa_tokens = self._tokenize(response.data_lines, rows, cols)
        return Screen(
            rows=rows,
            columns=cols,
            cursor_row=status.cursor_row,
            cursor_col=status.cursor_col,
            cell_grid=cell_grid,
            sa_tokens=sa_tokens,
        )

    def _tokenize(
        self,
        data_lines: list[str],
        rows: int,
        cols: int,
    ) -> tuple[list[list[CellValue]], list[list[tuple[int, SAToken]]]]:
        """Tokenize ReadBuffer(Ascii) data lines into cell_grid and sa_tokens.

        s3270 emits exactly one row of data per ``data:`` line, with exactly
        ``cols`` non-SA tokens per row.  SA(42=xx) tokens do NOT advance
        col_index (verified: every row has exactly 80 non-SA tokens).

        col_index is reset at the end of each row; cross-row field spanning is
        handled by the linear-position arithmetic in Screen.fields /
        Screen.find_field — not by the tokenizer.
        """
        cell_grid: list[list[CellValue]] = []
        sa_tokens: list[list[tuple[int, SAToken]]] = []

        for _ in range(rows):
            cell_grid.append([0x00] * cols)
            sa_tokens.append([])

        for row_i, raw_line in enumerate(data_lines):
            if row_i >= rows:
                break
            # Strip leading "data: " prefix if present
            line = (
                raw_line[len("data: "):]
                if raw_line.startswith("data: ")
                else raw_line
            )
            col_index = 0
            for tok_i, token in enumerate(line.split()):
                m_sf = _SF_TOKEN.match(token)
                m_sa = _SA_TOKEN.match(token)
                if _HEX_CELL.match(token):
                    if col_index < cols:
                        cell_grid[row_i][col_index] = int(token, 16)
                    col_index += 1
                elif m_sf:
                    nn = int(m_sf.group(1), 16)
                    if col_index < cols:
                        cell_grid[row_i][col_index] = SFToken(c0=nn)
                    col_index += 1
                elif m_sa:
                    val = int(m_sa.group(1), 16)
                    sa_tokens[row_i].append((col_index, SAToken(value=val)))
                    # SA does NOT advance col_index
                else:
                    raise ParseError(
                        f"Unrecognised ReadBuffer token at row {row_i}, "
                        f"index {tok_i}, length {len(token)}",
                        raw="",
                    )
            # col_index is local to the loop body; resets automatically each row

        return cell_grid, sa_tokens
