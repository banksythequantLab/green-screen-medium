from __future__ import annotations

"""ScreenRenderer: serialises a Screen back to ReadBuffer(Ascii) format.

Round-trip guarantee:
    ScreenParser.parse_readbuffer(response_with(ScreenRenderer.render(screen)))
    == screen

The renderer iterates cell_grid directly:
  - int cells  → zero-padded lowercase two-digit hex (e.g. 0x4c → "4c", 0x00 → "00")
  - SFToken    → "SF(c0=xx)" using the raw c0 byte verbatim (never recomputed)
Before each cell, check sa_tokens[row] for any SAToken at that col_index
and emit "SA(42=xx)" first (SA tokens do not occupy a cell position).
"""

from greenscreen.connector.models import SAToken, SFToken, Screen


class ScreenRenderer:
    """Serialises a Screen to ReadBuffer(Ascii) format."""

    def render(self, screen: Screen) -> list[str]:
        """Return one string per row in ReadBuffer(Ascii) format.

        Each string is a space-separated sequence of tokens (no 'data: ' prefix).
        The list has exactly screen.rows elements.

        Token types emitted:
          - Hex cell:  two lowercase hex digits, e.g. "4c", "00"
          - SF token:  "SF(c0=xx)" where xx is the raw c0 byte of the SFToken
          - SA token:  "SA(42=xx)" emitted BEFORE the cell at the recorded col_index
        """
        rows = []
        for row_i, row_cells in enumerate(screen.cell_grid):
            tokens: list[str] = []
            # Build a lookup: col_index → list of SATokens at that position
            sa_at: dict[int, list[SAToken]] = {}
            for col_idx, sa_tok in screen.sa_tokens[row_i]:
                sa_at.setdefault(col_idx, []).append(sa_tok)

            for col_i, cell in enumerate(row_cells):
                # Emit any SA tokens recorded before this column
                for sa_tok in sa_at.get(col_i, []):
                    tokens.append(f"SA(42={sa_tok.value:02x})")
                # Emit the cell itself
                if isinstance(cell, SFToken):
                    tokens.append(f"SF(c0={cell.c0:02x})")
                else:
                    tokens.append(f"{cell:02x}")

            rows.append(" ".join(tokens))
        return rows
