from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from greenscreen.recognizer.view import ScreenView


@dataclass(frozen=True, slots=True)
class RedactedSummary:
    """Screen description that is safe to log: hidden data cells appear as ``*``."""

    rows: int
    columns: int
    cursor: tuple[int, int]
    field_count: int
    unprotected_count: int
    hidden_count: int
    # (start_row, start_col, byte_length, protected, hidden)
    fields: tuple[tuple[int, int, int, bool, bool], ...]
    row_text: tuple[str, ...]

    def to_text(self) -> str:
        """``row_text`` joined by newlines: exactly ``rows`` lines."""
        return "\n".join(self.row_text)

    def to_dict(self) -> dict[str, Any]:
        """Plain dict holding only str, int, bool, lists and dicts."""
        return {
            "rows": self.rows,
            "columns": self.columns,
            "cursor": [self.cursor[0], self.cursor[1]],
            "field_count": self.field_count,
            "unprotected_count": self.unprotected_count,
            "hidden_count": self.hidden_count,
            "fields": [
                {
                    "start_row": f[0],
                    "start_col": f[1],
                    "byte_length": f[2],
                    "protected": f[3],
                    "hidden": f[4],
                }
                for f in self.fields
            ],
            "row_text": list(self.row_text),
        }


def build_summary(view: ScreenView) -> RedactedSummary:
    fields = tuple(
        (f.start_row, f.start_col, f.byte_length, f.protected, f.hidden)
        for f in view.fields
    )
    return RedactedSummary(
        rows=view.rows,
        columns=view.columns,
        cursor=(view.cursor_row, view.cursor_col),
        field_count=len(fields),
        unprotected_count=sum(1 for f in view.fields if not f.protected),
        hidden_count=sum(1 for f in view.fields if f.hidden),
        fields=fields,
        row_text=view.summary_rows(),
    )
