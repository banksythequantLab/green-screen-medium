"""Property test for suggest_signature structure (screen-recognizer Property 17)."""
from __future__ import annotations

import copy
import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from greenscreen.connector.models import SFToken
from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.signature import (
    CursorFieldMatcher,
    FieldLayoutMatcher,
    TextAtMatcher,
)
from greenscreen.recognizer.suggest import suggest_signature
from tests.property._recognizer_strategies import small_screens

_VALID_RUNS = st.one_of(
    st.builds(
        "{:02d}:{:02d}".format, st.integers(0, 23), st.integers(0, 59)
    ),
    st.builds(
        "{:02d}:{:02d}:{:02d}".format,
        st.integers(0, 23), st.integers(0, 59), st.integers(0, 59),
    ),
    st.builds(
        "{:02d}.{:02d}.{:02d}".format,
        st.integers(1, 31), st.integers(0, 99), st.integers(0, 99),
    ),
)
# Hour 24, minute 60, day 32 and day 00. None contains a valid run inside.
_INVALID_RUNS = st.sampled_from(
    ["24:00", "24:30", "12:60", "09:75", "32.01.20", "00.12.12", "32.10.99", "00.01.01"]
)

_PLANT = st.tuples(st.integers(0, 23), st.integers(0, 79), st.one_of(_VALID_RUNS, _INVALID_RUNS))


def _valid_at(text: str, i: int) -> int:
    """Length of the valid run starting at ``i`` (longest first), else 0."""
    def digits(a: int, b: int) -> bool:
        return len(text) >= b and all(ch in "0123456789" for ch in text[a:b])

    def hh(a: int) -> bool:
        return digits(a, a + 2) and int(text[a:a + 2]) <= 23

    def ms(a: int) -> bool:
        return digits(a, a + 2) and int(text[a:a + 2]) <= 59

    if hh(i) and text[i + 2:i + 3] == ":" and ms(i + 3):
        if text[i + 5:i + 6] == ":" and ms(i + 6):
            return 8
        return 5
    if (digits(i, i + 2) and 1 <= int(text[i:i + 2]) <= 31 and text[i + 2:i + 3] == "."
            and digits(i + 3, i + 5) and text[i + 5:i + 6] == "." and digits(i + 6, i + 8)):
        return 8
    return 0


def _runs(text: str) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(text):
        n = _valid_at(text, i)
        if n:
            out.append((i, n))
            i += n
        else:
            i += 1
    return out


def _oracle_rows(screen) -> tuple[list[str], set[int]]:
    cols, total = screen.columns, screen.rows * screen.columns
    hidden: set[int] = set()
    for f in screen.fields:
        if f.hidden:
            lin = f.start_row * cols + f.start_col
            hidden.update((lin + 1 + k) % total for k in range(f.byte_length))
    rows = []
    for r in range(screen.rows):
        chars = []
        for c in range(cols):
            cell = screen.cell_grid[r][c]
            if isinstance(cell, SFToken) or cell == 0 or r * cols + c in hidden:
                chars.append(" ")
            else:
                chars.append(chr(cell))
        rows.append("".join(chars))
    return rows, hidden


def _plant(screen, plants):
    """Write ' <run> ' into the grid unless any cell is a field start.

    Returns (valid, invalid) lists of (row, col, text) that were written.
    """
    valid, invalid = [], []
    for r, c, run in plants:
        if r >= screen.rows or c + len(run) + 2 > screen.columns:
            continue
        cells = screen.cell_grid[r]
        if any(isinstance(cells[c + k], SFToken) for k in range(len(run) + 2)):
            continue
        for k, ch in enumerate(" " + run + " "):
            cells[c + k] = ord(ch)
        (valid if _is_valid(run) else invalid).append((r, c + 1, run))
    return valid, invalid


def _is_valid(run: str) -> bool:
    return _valid_at(run, 0) == len(run)


def _segments(marked: str) -> list[tuple[int, str]]:
    """Runs of text with no NUL and no two consecutive spaces, trimmed."""
    out, i, n = [], 0, len(marked)
    while i < n:
        if marked[i] in " \x00":
            i += 1
            continue
        j = i
        while j + 1 < n and marked[j + 1] != "\x00" and not (
            marked[j + 1] == " " and (j + 2 >= n or marked[j + 2] in " \x00")
        ):
            j += 1
        out.append((i, marked[i:j + 1]))
        i = j + 1
    return out


# Feature: screen-recognizer, Property 17: Suggested signature structure
@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
@given(
    screen=small_screens(max_fields=5, allow_hidden=True).filter(
        lambda s: s.columns >= 12
    ),
    plants=st.lists(_PLANT, max_size=4),
    name=st.one_of(
        st.none(),
        st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=64),
    ),
)
def test_suggested_signature_structure(screen, plants, name):
    valid, invalid = _plant(screen, plants)
    rows, hidden = _oracle_rows(screen)
    cols = screen.columns
    before = copy.deepcopy(
        (screen.rows, screen.columns, screen.cursor_row, screen.cursor_col,
         screen.cell_grid, screen.sa_tokens)
    )

    # Oracle: volatile runs, excluded cells, selected row.
    runs = [(r, c, n) for r, t in enumerate(rows) for c, n in _runs(t)]
    excluded = {(r, c + k) for r, c, n in runs for k in range(n)}
    selected = next(
        (r for r, t in enumerate(rows)
         if any(ch != " " and (r, c) not in excluded for c, ch in enumerate(t))),
        None,
    )
    blank_text = all(t.strip(" ") == "" for t in rows)
    fields = list(screen.fields)

    if blank_text and not fields:
        with pytest.raises(SignatureError):
            suggest_signature(screen, name)
        return

    sig = suggest_signature(screen, name)

    # Volatile regions: oracle runs (first 50), valid covered, invalid not.
    got = [(v.row, v.col, v.length) for v in sig.volatile]
    assert got == sorted(runs[:50], key=lambda t: (t[0], t[1]))
    if len(runs) <= 50:
        for r, c, run in valid:
            if rows[r][c:c + len(run)] == run:
                assert any(
                    vr == r and vc <= c and c + len(run) <= vc + vl for vr, vc, vl in got
                )
        for r, c, run in invalid:
            if rows[r][c:c + len(run)] == run:
                assert not any(
                    vr == r and vc < c + len(run) and c < vc + vl for vr, vc, vl in got
                )

    # Text matchers: first stable row only, no volatile or hidden cell.
    texts = [m for m in sig.matchers if isinstance(m, TextAtMatcher)]
    expected_texts = []
    if selected is not None:
        marked = "".join(
            "\x00" if (selected, c) in excluded else ch
            for c, ch in enumerate(rows[selected])
        )
        for col, seg in _segments(marked)[:3]:
            if not any(selected * cols + col + k in hidden for k in range(len(seg))):
                expected_texts.append((selected, col, seg))
    assert [(m.row, m.col, m.text) for m in texts] == expected_texts
    for m in texts:
        for k in range(len(m.text)):
            assert (m.row, m.col + k) not in excluded
            assert m.row * cols + m.col + k not in hidden

    # Field layout: exactly one when unprotected fields exist.
    layouts = [m for m in sig.matchers if isinstance(m, FieldLayoutMatcher)]
    unprot = [(f.start_row, f.start_col) for f in fields if not f.protected]
    cf = screen.find_field(screen.cursor_row, screen.cursor_col)
    cursor_expected = cf is not None and not cf.protected
    cursors = [m for m in sig.matchers if isinstance(m, CursorFieldMatcher)]
    if unprot:
        assert len(layouts) == 1
        assert layouts[0].count == len(unprot)
        assert list(layouts[0].positions) == unprot
    else:
        # Count-0 fallback only when nothing else was produced.
        fallback = not texts and not cursor_expected
        assert len(layouts) == (1 if fallback else 0)
        if fallback:
            assert layouts[0].count == 0 and layouts[0].positions == ()

    # Cursor field: exactly one when the cursor is in an Input_Field.
    if cursor_expected:
        assert len(cursors) == 1
        assert (cursors[0].row, cursors[0].col, cursors[0].hidden) == (
            cf.start_row, cf.start_col, cf.hidden
        )
    else:
        assert cursors == []

    assert all(
        isinstance(m, (TextAtMatcher, FieldLayoutMatcher, CursorFieldMatcher))
        for m in sig.matchers
    )

    # Name.
    if name is not None:
        assert sig.name == name
    else:
        assert sig.name == "unnamed-screen" or re.fullmatch(r"[a-z0-9-]{1,64}", sig.name)
        if selected is None:
            assert sig.name == "unnamed-screen"
        else:
            stable = "".join(
                " " if (selected, c) in excluded else ch
                for c, ch in enumerate(rows[selected])
            )
            stripped = re.sub(r"[^a-z0-9-]+", "-", stable.lower()).strip("-")
            allowed = {stripped[:64], stripped[:64].strip("-")} if stripped else set()
            assert sig.name == "unnamed-screen" if not stripped else sig.name in allowed

    # Repeatable, and the screen is unchanged.
    assert suggest_signature(screen, name) == sig
    assert before == (
        screen.rows, screen.columns, screen.cursor_row, screen.cursor_col,
        screen.cell_grid, screen.sa_tokens,
    )
