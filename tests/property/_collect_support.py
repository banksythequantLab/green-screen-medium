"""Page-sequence builder for the Rows_Output and ``collect`` property tests.

Built on ``tests/screen_support.make_screen``. A line-mode page holds output lines
at column 1, then a last row that is either `` ***`` (a pause: the cursor sits on that
row at column 5) or `` READY`` (the cursor sits on the next row at column 0), the
shapes recorded in ``.kiro/steering`` section "Verified 2026-11-19". Every line of
every page carries a unique blank-free token, so a test can tell which lines reached
a value. This module does not import the runner.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from greenscreen.connector.models import Screen
from tests.flow_support import ScriptedState
from tests.screen_support import make_screen

ROWS = 24
COLUMNS = 80
LINE_COL = 1  # output lines start at column 1 (column 0 is blank)


def line_screen(
    lines: Sequence[str],
    *,
    first_row: int = 0,
    last: str = "ready",
    col: int = LINE_COL,
) -> Screen:
    """A 24x80 line-mode screen: ``lines`` from ``first_row``, then the last row.

    ``last`` is ``"pause"`` (`` ***`` on the row after the lines, cursor on it at
    column 5), ``"ready"`` (`` READY``, cursor on the following row at column 0) or
    ``"none"`` (no last row, cursor at the row after the lines).
    """
    if last not in ("pause", "ready", "none"):
        raise ValueError(f"unknown last row kind: {last!r}")
    end = first_row + len(lines)  # row of the last row
    limit = ROWS - 2 if last == "ready" else ROWS - 1
    if first_row < 0 or end > limit:
        raise ValueError("lines do not fit on the screen")
    text: dict[tuple[int, int], str] = {
        (first_row + i, col): line for i, line in enumerate(lines)
    }
    if last == "pause":
        text[(end, 0)] = " ***"
        cursor = (end, 5)
    elif last == "ready":
        text[(end, 0)] = " READY"
        cursor = (end + 1, 0)
    else:
        cursor = (min(end, ROWS - 1), 0)
    return make_screen(ROWS, COLUMNS, text, cursor=cursor)


@dataclass(frozen=True)
class PageSequence:
    """Pages of a listing: ``tokens[k]`` are the line tokens on page ``k``."""

    tokens: tuple[tuple[str, ...], ...]
    first_row: int
    next_row: int
    final: str  # last row of the last page: "ready" or "pause"

    @property
    def all_tokens(self) -> tuple[str, ...]:
        return tuple(t for page in self.tokens for t in page)

    def screens(self) -> list[Screen]:
        """A fresh Screen per page. Every page but the last ends with a pause."""
        out: list[Screen] = []
        for k, page in enumerate(self.tokens):
            last = self.final if k == len(self.tokens) - 1 else "pause"
            out.append(
                line_screen(page, first_row=self.first_row if k == 0 else self.next_row, last=last)
            )
        return out

    def states(self) -> list[ScriptedState]:
        """The pages as ScriptedStates, one per page, no stale reads."""
        return [ScriptedState(s) for s in self.screens()]


def page_sequence(
    lines_per_page: Sequence[int],
    *,
    first_row: int = 1,
    next_row: int = 0,
    final: str = "ready",
    prefix: str = "T",
) -> PageSequence:
    """Pages with ``lines_per_page[k]`` lines on page ``k`` and a unique token per line.

    The token of line ``j`` on page ``k`` is ``f"{prefix}{k:03d}L{j:03d}"`` (no blank,
    no repeat). Page 0 starts at ``first_row`` (row 0 holds the echo of the command),
    later pages at ``next_row``.
    """
    if not lines_per_page:
        raise ValueError("at least one page")
    if final not in ("ready", "pause"):
        raise ValueError(f"unknown final row kind: {final!r}")
    tokens = tuple(
        tuple(f"{prefix}{k:03d}L{j:03d}" for j in range(n))
        for k, n in enumerate(lines_per_page)
    )
    seq = PageSequence(tokens, first_row, next_row, final)
    seq.screens()  # raises ValueError when a page does not fit
    return seq
