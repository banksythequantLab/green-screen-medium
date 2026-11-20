"""Test support: screens from the repo captures and synthetic screens.

Used by the screen-recognizer tests. Nothing here needs a live host or a fake
s3270.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from greenscreen.connector.models import Response, Screen, SFToken
from greenscreen.connector.parser import ScreenParser

CAPTURE_NAMES: tuple[str, ...] = (
    "tk5-logo",
    "tk5-logon",
    "tso-input-not-recognized",
    "tso-password-prompt",
    "ispf-primary-menu",
    "tso-ready",
    "tso-pause-2",
    "tso-userid-in-use",
    "tso-reconnect-password-prompt",
    "tso-reconnect-ok",
    "tso-cleared",
    "tso-listcat-level",
    "tso-listcat-level-page2",
    "tso-listcat-level-page3",
    "tso-listcat-output",
    "tso-listds-members",
    "tso-listds-members-page2",
    "tso-listds-members-page3",
    "tso-listds-members-page4",
    "tso-listds-members-page5",
    "tso-listds-members-page6",
    "tso-listds-members-page7",
    "tso-listds-not-in-catalog",
    "tso-listds-output",
    "tso-listds-reenter",
    "tso-listds-reenter-after-pa1",
    "tso-status-output",
    "tso-time-output",
)

_CAPTURES_DIR = Path(__file__).parents[1] / "captures"


def load_capture_screen(name: str) -> Screen:
    """Parse ``captures/<name>.readbuffer.txt`` into a Screen.

    Collects the ``data: `` lines and the status line before ``ok`` of the last
    block in the file. The ``.ascii.txt`` files are not used.
    """
    path = _CAPTURES_DIR / f"{name}.readbuffer.txt"
    blocks: list[tuple[list[str], str | None]] = []
    data: list[str] = []
    status: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("data: "):
            data.append(line[len("data: "):])
        elif line == "ok" and data:
            blocks.append((data, status))
            data = []
            status = None
        elif line not in ("ok", "error", ""):
            status = line
    if not blocks or blocks[-1][1] is None:
        raise ValueError(f"no complete readbuffer block in {path.name}")
    data_lines, status_raw = blocks[-1]
    parser = ScreenParser()
    response = Response(
        success=True,
        data_lines=data_lines,
        status=parser.parse_status_line(status_raw),
    )
    return parser.parse_readbuffer(response)


def make_screen(
    rows: int,
    columns: int,
    text: Mapping[tuple[int, int], str] | None = None,
    fields: Iterable[tuple[int, int, int]] = (),
    cursor: tuple[int, int] = (0, 0),
) -> Screen:
    """Build a Screen of ``0x00`` cells.

    ``text`` maps ``(row, col)`` to a string written from that cell (each
    character must be at most U+00FF). ``fields`` is an iterable of
    ``(row, col, c0)`` written as ``SFToken`` cells after the text, so a field
    start wins over text in the same cell. ``sa_tokens`` is one empty list per row.
    """
    grid: list[list] = [[0x00] * columns for _ in range(rows)]
    for (r, c), s in (text or {}).items():
        for i, ch in enumerate(s):
            if 0 <= r < rows and 0 <= c + i < columns:
                grid[r][c + i] = ord(ch)
    for r, c, c0 in fields:
        grid[r][c] = SFToken(c0)
    return Screen(
        rows=rows,
        columns=columns,
        cursor_row=cursor[0],
        cursor_col=cursor[1],
        cell_grid=grid,
        sa_tokens=[[] for _ in range(rows)],
    )


def in_use_screen(userid: str) -> Screen:
    """Synthetic ``IKJ56425I ... IN USE`` screen after the user id is sent."""
    msg = f"IKJ56425I LOGON REJECTED, USERID {userid} IN USE"
    return make_screen(
        24, 80, {(0, 1): msg},
        [(0, 0, 0xC8), (0, 1 + len(msg), 0xC0)], (1, 0),
    )


def reconnect_prompt_screen(userid: str) -> Screen:
    """Synthetic reconnect password prompt (hidden field under the cursor)."""
    msg = f"IKJ56425I LOGON REJECTED, USERID {userid} IN USE"
    return make_screen(
        24, 80,
        {
            (0, 1): msg,
            (1, 0): f"LOGON {userid} RECONNECT",
            (2, 1): f"IKJ56714A ENTER CURRENT PASSWORD FOR {userid}-",
        },
        [(0, 0, 0xC8), (2, 0, 0xC8), (3, 0, 0xCC)],
        (3, 1),
    )


def reconnect_pause_screen() -> Screen:
    """Synthetic ``***`` pause under the reconnect message (never captured)."""
    return make_screen(
        24, 80,
        {
            (0, 1): "IKT00300I LOGON RECONNECT SUCCESSFUL, SESSION ESTABLISHED",
            (2, 1): "***",
        },
        [(0, 0, 0xC8), (2, 0, 0xC8)],
        (2, 5),
    )


def second_in_use_screen() -> Screen:
    """Synthetic IN USE screen after one more Enter (IKJ56400A on row 2)."""
    return make_screen(
        24, 80,
        {
            (0, 1): "IKJ56425I LOGON REJECTED, USERID FAKEUSR IN USE",
            (2, 1): "IKJ56400A ENTER LOGON OR LOGOFF-",
        },
        [(0, 0, 0xC8), (2, 0, 0xC8)],
        (3, 0),
    )
