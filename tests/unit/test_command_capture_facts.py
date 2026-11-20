"""Facts about the 18 promoted command captures (design, "Capture facts").

Rows and columns count from 0. A row entry is ``row:first_col:length`` where
first_col is the first non-blank cell and length runs to the last non-blank
cell. A field entry is ``row:col`` of a field start. Needs no live host. No
user id appears here: only positions and lengths are pinned, plus fixed words
of the host (READY, ***, REENTER -). A failure message names a capture and a
fact, never a screen row.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from greenscreen.connector.models import SFToken
from greenscreen.recognizer.view import ScreenView

from tests.screen_support import load_capture_screen


@dataclass(frozen=True)
class Facts:
    cursor: tuple[int, int]
    rows: str
    fields: str


def _rows(facts: Facts) -> dict[int, tuple[int, int]]:
    out = {}
    for item in facts.rows.split():
        r, c, n = (int(x) for x in item.split(":"))
        out[r] = (c, n)
    return out


def _fields(facts: Facts) -> list[tuple[int, int]]:
    return [tuple(int(x) for x in item.split(":")) for item in facts.fields.split()]


FACTS: dict[str, Facts] = {
    "tso-cleared": Facts(
        cursor=(0, 0),
        rows=(
            ""
        ),
        fields=(
            "23:79 "
        ),
    ),
    "tso-time-output": Facts(
        cursor=(3, 0),
        rows=(
            "0:0:4 1:1:77 2:1:5 "
        ),
        fields=(
            "1:0 1:78 2:0 2:7 23:79 "
        ),
    ),
    "tso-listcat-output": Facts(
        cursor=(10, 0),
        rows=(
            "0:0:7 1:1:24 2:1:14 3:1:11 4:1:15 5:1:15 6:1:15 7:1:16 8:1:19 9:1:5 "
        ),
        fields=(
            "1:0 1:25 2:0 2:15 3:0 3:12 4:0 4:16 5:0 5:16 6:0 6:16 7:0 7:17 8:0 8:20 9:0 9:7 23:79 "
        ),
    ),
    "tso-listcat-level": Facts(
        cursor=(23, 5),
        rows=(
            "0:0:19 1:1:27 2:6:24 3:1:28 4:6:24 5:1:28 6:6:24 7:1:27 8:6:24 9:1:33 10:6:24 11:1:33 "
            "12:6:24 13:1:25 14:6:24 15:1:25 16:6:24 17:1:29 18:6:24 19:1:29 20:6:24 21:1:29 22:6:24 "
            "23:1:3 "
        ),
        fields=(
            "1:0 1:28 2:0 2:30 3:0 3:29 4:0 4:30 5:0 5:29 6:0 6:30 7:0 7:28 8:0 8:30 9:0 9:34 10:0 "
            "10:30 11:0 11:34 12:0 12:30 13:0 13:26 14:0 14:30 15:0 15:26 16:0 16:30 17:0 17:30 18:0 "
            "18:30 19:0 19:30 20:0 20:30 21:0 21:30 22:0 22:30 23:0 23:4 23:79 "
        ),
    ),
    "tso-listcat-level-page2": Facts(
        cursor=(23, 5),
        rows=(
            "0:1:29 1:6:24 2:1:29 3:6:24 4:1:29 5:6:24 6:1:27 7:6:24 8:1:28 9:6:24 10:1:27 11:6:24 "
            "12:1:28 13:6:24 14:1:31 15:6:24 16:1:32 17:6:24 18:1:32 19:6:24 20:1:43 21:6:24 22:1:34 "
            "23:1:3 "
        ),
        fields=(
            "0:0 0:30 1:0 1:30 2:0 2:30 3:0 3:30 4:0 4:30 5:0 5:30 6:0 6:28 7:0 7:30 8:0 8:29 9:0 "
            "9:30 10:0 10:28 11:0 11:30 12:0 12:29 13:0 13:30 14:0 14:32 15:0 15:30 16:0 16:33 17:0 "
            "17:30 18:0 18:33 19:0 19:30 20:0 20:44 21:0 21:30 22:0 22:35 23:0 23:4 23:79 "
        ),
    ),
    "tso-listcat-level-page3": Facts(
        cursor=(6, 0),
        rows=(
            "0:6:24 1:1:29 2:6:24 3:1:29 4:6:24 5:1:5 "
        ),
        fields=(
            "0:0 0:30 1:0 1:30 2:0 2:30 3:0 3:30 4:0 4:30 5:0 5:7 23:79 "
        ),
    ),
    "tso-listds-output": Facts(
        cursor=(7, 0),
        rows=(
            "0:0:25 1:1:16 2:1:27 3:3:22 4:1:11 5:3:6 6:1:5 "
        ),
        fields=(
            "1:0 1:17 2:0 2:28 3:0 3:25 4:0 4:12 5:0 5:9 6:0 6:7 23:79 "
        ),
    ),
    "tso-listds-not-in-catalog": Facts(
        cursor=(4, 0),
        rows=(
            "0:0:20 1:1:11 2:1:37 3:1:5 "
        ),
        fields=(
            "1:0 1:12 2:0 2:38 3:0 3:7 23:79 "
        ),
    ),
    "tso-listds-reenter": Facts(
        cursor=(3, 0),
        rows=(
            "0:0:13 1:1:29 2:1:9 "
        ),
        fields=(
            "1:0 1:30 2:0 2:10 23:79 "
        ),
    ),
    "tso-listds-reenter-after-pa1": Facts(
        cursor=(5, 0),
        rows=(
            "0:0:13 1:1:29 2:1:9 3:1:1 4:1:5 "
        ),
        fields=(
            "1:0 1:30 2:0 2:10 3:0 3:2 4:0 4:7 23:79 "
        ),
    ),
    "tso-listds-members": Facts(
        cursor=(23, 5),
        rows=(
            "0:0:28 1:1:11 2:1:27 3:3:22 4:1:11 5:3:6 6:1:11 7:3:8 8:3:8 9:3:8 10:3:7 11:3:8 12:3:8 "
            "13:3:8 14:3:8 15:3:8 16:3:8 17:3:8 18:3:8 19:3:8 20:3:8 21:3:7 22:3:7 23:1:3 "
        ),
        fields=(
            "1:0 1:12 2:0 2:28 3:0 3:25 4:0 4:12 5:0 5:9 6:0 6:12 7:0 7:11 8:0 8:11 9:0 9:11 10:0 "
            "10:10 11:0 11:11 12:0 12:11 13:0 13:11 14:0 14:11 15:0 15:11 16:0 16:11 17:0 17:11 18:0 "
            "18:11 19:0 19:11 20:0 20:11 21:0 21:10 22:0 22:10 23:0 23:4 23:79 "
        ),
    ),
    "tso-listds-members-page2": Facts(
        cursor=(23, 5),
        rows=(
            "0:3:7 1:3:8 2:3:8 3:3:8 4:3:7 5:3:8 6:3:8 7:3:8 8:3:8 9:3:8 10:3:6 11:3:8 12:3:8 13:3:8 "
            "14:3:8 15:3:8 16:3:7 17:3:7 18:3:7 19:3:8 20:3:8 21:3:7 22:3:7 23:1:3 "
        ),
        fields=(
            "0:0 0:10 1:0 1:11 2:0 2:11 3:0 3:11 4:0 4:10 5:0 5:11 6:0 6:11 7:0 7:11 8:0 8:11 9:0 "
            "9:11 10:0 10:9 11:0 11:11 12:0 12:11 13:0 13:11 14:0 14:11 15:0 15:11 16:0 16:10 17:0 "
            "17:10 18:0 18:10 19:0 19:11 20:0 20:11 21:0 21:10 22:0 22:10 23:0 23:4 23:79 "
        ),
    ),
    "tso-listds-members-page3": Facts(
        cursor=(23, 5),
        rows=(
            "0:3:5 1:3:7 2:3:6 3:3:7 4:3:5 5:3:8 6:3:5 7:3:4 8:3:8 9:3:8 10:3:7 11:3:5 12:3:8 13:3:8 "
            "14:3:8 15:3:7 16:3:8 17:3:7 18:3:7 19:3:6 20:3:5 21:3:4 22:3:7 23:1:3 "
        ),
        fields=(
            "0:0 0:8 1:0 1:10 2:0 2:9 3:0 3:10 4:0 4:8 5:0 5:11 6:0 6:8 7:0 7:7 8:0 8:11 9:0 9:11 "
            "10:0 10:10 11:0 11:8 12:0 12:11 13:0 13:11 14:0 14:11 15:0 15:10 16:0 16:11 17:0 17:10 "
            "18:0 18:10 19:0 19:9 20:0 20:8 21:0 21:7 22:0 22:10 23:0 23:4 23:79 "
        ),
    ),
    "tso-listds-members-page4": Facts(
        cursor=(23, 5),
        rows=(
            "0:3:8 1:3:7 2:3:8 3:3:8 4:3:8 5:3:8 6:3:7 7:3:7 8:3:8 9:3:7 10:3:8 11:3:8 12:3:7 13:3:8 "
            "14:3:8 15:3:8 16:3:8 17:3:8 18:3:8 19:3:7 20:3:7 21:3:7 22:3:8 23:1:3 "
        ),
        fields=(
            "0:0 0:11 1:0 1:10 2:0 2:11 3:0 3:11 4:0 4:11 5:0 5:11 6:0 6:10 7:0 7:10 8:0 8:11 9:0 "
            "9:10 10:0 10:11 11:0 11:11 12:0 12:10 13:0 13:11 14:0 14:11 15:0 15:11 16:0 16:11 17:0 "
            "17:11 18:0 18:11 19:0 19:10 20:0 20:10 21:0 21:10 22:0 22:11 23:0 23:4 23:79 "
        ),
    ),
    "tso-listds-members-page5": Facts(
        cursor=(23, 5),
        rows=(
            "0:3:8 1:3:8 2:3:7 3:3:7 4:3:7 5:3:7 6:3:7 7:3:7 8:3:7 9:3:7 10:3:8 11:3:8 12:3:8 13:3:8 "
            "14:3:8 15:3:7 16:3:8 17:3:8 18:3:8 19:3:8 20:3:7 21:3:7 22:3:8 23:1:3 "
        ),
        fields=(
            "0:0 0:11 1:0 1:11 2:0 2:10 3:0 3:10 4:0 4:10 5:0 5:10 6:0 6:10 7:0 7:10 8:0 8:10 9:0 "
            "9:10 10:0 10:11 11:0 11:11 12:0 12:11 13:0 13:11 14:0 14:11 15:0 15:10 16:0 16:11 17:0 "
            "17:11 18:0 18:11 19:0 19:11 20:0 20:10 21:0 21:10 22:0 22:11 23:0 23:4 23:79 "
        ),
    ),
    "tso-listds-members-page6": Facts(
        cursor=(23, 5),
        rows=(
            "0:3:7 1:3:8 2:3:8 3:3:8 4:3:7 5:3:8 6:3:8 7:3:8 8:3:8 9:3:7 10:3:7 11:3:7 12:3:8 13:3:8 "
            "14:3:7 15:3:7 16:3:8 17:3:7 18:3:7 19:3:8 20:3:8 21:3:8 22:3:8 23:1:3 "
        ),
        fields=(
            "0:0 0:10 1:0 1:11 2:0 2:11 3:0 3:11 4:0 4:10 5:0 5:11 6:0 6:11 7:0 7:11 8:0 8:11 9:0 "
            "9:10 10:0 10:10 11:0 11:10 12:0 12:11 13:0 13:11 14:0 14:10 15:0 15:10 16:0 16:11 17:0 "
            "17:10 18:0 18:10 19:0 19:11 20:0 20:11 21:0 21:11 22:0 22:11 23:0 23:4 23:79 "
        ),
    ),
    "tso-listds-members-page7": Facts(
        cursor=(6, 0),
        rows=(
            "0:3:8 1:3:7 2:3:6 3:3:8 4:3:7 5:1:5 "
        ),
        fields=(
            "0:0 0:11 1:0 1:10 2:0 2:9 3:0 3:11 4:0 4:10 5:0 5:7 23:79 "
        ),
    ),
    "tso-status-output": Facts(
        cursor=(3, 0),
        rows=(
            "0:0:6 1:1:30 2:1:5 "
        ),
        fields=(
            "1:0 1:31 2:0 2:7 23:79 "
        ),
    ),
}

# Prompt_Row (highest row with a visible non-blank cell) and its fixed text.
PROMPT: dict[str, tuple[int, str]] = {
    "tso-cleared": (-1, ""),
    "tso-time-output": (2, "READY"),
    "tso-listcat-output": (9, "READY"),
    "tso-listcat-level": (23, "***"),
    "tso-listcat-level-page2": (23, "***"),
    "tso-listcat-level-page3": (5, "READY"),
    "tso-listds-output": (6, "READY"),
    "tso-listds-not-in-catalog": (3, "READY"),
    "tso-listds-reenter": (2, "REENTER -"),
    "tso-listds-reenter-after-pa1": (4, "READY"),
    "tso-listds-members": (23, "***"),
    "tso-listds-members-page2": (23, "***"),
    "tso-listds-members-page3": (23, "***"),
    "tso-listds-members-page4": (23, "***"),
    "tso-listds-members-page5": (23, "***"),
    "tso-listds-members-page6": (23, "***"),
    "tso-listds-members-page7": (5, "READY"),
    "tso-status-output": (2, "READY"),
}

MEMBER_PAGES = (
    ("tso-listds-members", 7, 16),
    ("tso-listds-members-page2", 0, 23),
    ("tso-listds-members-page3", 0, 23),
    ("tso-listds-members-page4", 0, 23),
    ("tso-listds-members-page5", 0, 23),
    ("tso-listds-members-page6", 0, 23),
    ("tso-listds-members-page7", 0, 5),
)

_NAMES = sorted(FACTS)


def _prompt_row(screen) -> int:
    base = ScreenView(screen).base_rows
    rows = [r for r, text in enumerate(base) if text.strip(" ")]
    return rows[-1] if rows else -1


def test_the_table_covers_the_18_command_captures():
    assert len(FACTS) == 18
    assert set(PROMPT) == set(FACTS)


@pytest.mark.parametrize("name", _NAMES)
def test_cursor(name):
    screen = load_capture_screen(name)
    assert (screen.cursor_row, screen.cursor_col) == FACTS[name].cursor, f"{name}: cursor"


@pytest.mark.parametrize("name", _NAMES)
def test_non_blank_rows_with_first_column_and_length(name):
    grid = load_capture_screen(name).text_grid
    actual = {}
    for r, text in enumerate(grid):
        stripped = text.strip(" ")
        if stripped:
            actual[r] = (len(text) - len(text.lstrip(" ")), len(stripped))
    assert actual == _rows(FACTS[name]), f"{name}: non-blank rows"


@pytest.mark.parametrize("name", _NAMES)
def test_field_starts_are_all_unprotected_and_not_hidden(name):
    screen = load_capture_screen(name)
    starts = [
        (r, c)
        for r, row in enumerate(screen.cell_grid)
        for c, cell in enumerate(row)
        if isinstance(cell, SFToken)
    ]
    assert starts == _fields(FACTS[name]), f"{name}: field start positions"
    assert all(not f.protected and not f.hidden for f in screen.fields), (
        f"{name}: a field is protected or hidden"
    )
    unprotected = [(f.start_row, f.start_col) for f in ScreenView(screen).unprotected_fields()]
    assert unprotected == starts, f"{name}: unprotected field starts"


@pytest.mark.parametrize("name", _NAMES)
def test_prompt_row_and_its_text(name):
    screen = load_capture_screen(name)
    row, text = PROMPT[name]
    assert _prompt_row(screen) == row, f"{name}: Prompt_Row"
    if row >= 0:
        assert screen.text_grid[row].strip(" ") == text, f"{name}: Prompt_Row text"


# Captures whose row 0 is the echo of the typed command (column 0). The other
# screens are continuation screens that start at row 0 with output.
_NO_ECHO = {
    "tso-listcat-level-page2", "tso-listcat-level-page3", "tso-listds-members-page2",
    "tso-listds-members-page3", "tso-listds-members-page4", "tso-listds-members-page5",
    "tso-listds-members-page6", "tso-listds-members-page7",
}


@pytest.mark.parametrize("name", [n for n in _NAMES if n != "tso-cleared"])
def test_echo_row_starts_at_column_0_and_output_rows_after_column_0(name):
    rows = _rows(FACTS[name])
    first_output_row = 0 if name in _NO_ECHO else 1
    if name not in _NO_ECHO:
        assert rows[0][0] == 0, f"{name}: echo row does not start at column 0"
    for r, (col, _) in rows.items():
        if r >= first_output_row and not name.startswith("tso-listds-members"):
            assert col >= 1, f"{name}: row {r} starts at column 0"

def _member_names(page: str, first_row: int, count: int) -> list[str]:
    screen = load_capture_screen(page)
    names = []
    for r in range(first_row, first_row + count):
        row = screen.cell_grid[r]
        assert isinstance(row[0], SFToken), f"{page}: row {r} has no field start at column 0"
        assert row[1] in (0, 0x20) and row[2] in (0, 0x20), f"{page}: row {r} cells 1 and 2 are not blank"
        name = screen.text_grid[r][3:11].strip(" ")
        assert name != "", f"{page}: row {r} has no member name at column 3"
        names.append(name)
    return names


def test_member_names_start_at_column_3_in_all_136_rows():
    total = 0
    for page, first_row, count in MEMBER_PAGES:
        names = _member_names(page, first_row, count)
        assert all(4 <= len(n) <= 8 and " " not in n for n in names), f"{page}: member name shape"
        total += len(names)
    assert total == 136


def test_member_counts_per_page_and_the_row_after_them():
    for page, first_row, count in MEMBER_PAGES:
        screen = load_capture_screen(page)
        rows = _rows(FACTS[page])
        member_rows = [r for r in rows if r >= first_row and rows[r][0] == 3]
        assert member_rows == list(range(first_row, first_row + count)), f"{page}: member rows"
    assert [c for _, _, c in MEMBER_PAGES] == [16, 23, 23, 23, 23, 23, 5]


def test_first_three_and_last_member_names():
    first = _member_names("tso-listds-members", 7, 16)
    last = _member_names("tso-listds-members-page7", 0, 5)
    assert first[:3] == ["$$$INDEX", "$HISTORY", "ADDALIAS"]
    assert last[-1] == "ZAPDSCB"


def test_listcat_output_rows_hold_one_token_each():
    screen = load_capture_screen("tso-listcat-output")
    prompt = _prompt_row(screen)
    assert prompt == 9
    grid = screen.text_grid
    assert [len(grid[r].split()) for r in range(2, prompt)] == [1] * 7
