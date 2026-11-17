"""Unit tests for ScreenParser (Task 10.3).

Validates: Requirements 5.4, 5.5, 5.9, 5.10, 5.11, 6.1-6.7
"""
from __future__ import annotations

import pathlib

import pytest

from greenscreen.connector.exceptions import ParseError
from greenscreen.connector.models import Response, SAToken, SFToken, StatusLine
from greenscreen.connector.parser import ScreenParser
from greenscreen.connector.testing.fixtures import load_bundled_fixture

CAPTURES = pathlib.Path(__file__).parents[2] / "captures"
PARSER = ScreenParser()
STATUS = "U F U C(127.0.0.1) I 2 24 80 22 11 0x0 0.000"


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _status(rows: int = 24, cols: int = 80, crow: int = 0, ccol: int = 0) -> StatusLine:
    return PARSER.parse_status_line(
        f"U F U C(127.0.0.1) I 2 {rows} {cols} {crow} {ccol} 0x0 0.000"
    )


def _parse(lines: list[str], rows: int, cols: int, crow: int = 0, ccol: int = 0):
    return PARSER.parse_readbuffer(
        Response(True, lines, _status(rows, cols, crow, ccol))
    )


def _fixture_screen(name: str):
    frame = load_bundled_fixture(name)[0]
    status = PARSER.parse_status_line(frame.status_line)
    return frame, status, PARSER.parse_readbuffer(Response(True, frame.data_lines, status))


def _non_sa_count(line: str) -> int:
    return sum(1 for t in line.split() if not t.startswith("SA("))


def _capture_data_lines(name: str) -> list[str]:
    text = (CAPTURES / name).read_text(encoding="utf-8")
    return [ln[len("data: "):] for ln in text.splitlines() if ln.startswith("data: ")]


# ---------------------------------------------------------------------------
# parse_status_line
# ---------------------------------------------------------------------------


def test_status_line_valid():
    s = PARSER.parse_status_line("U F U C(127.0.0.1) I 2 24 80 22 11 0x0 0.006")
    assert s.keyboard_state == "U"
    assert s.screen_formatting == "F"
    assert s.field_protection == "U"
    assert s.connection_state == "C(127.0.0.1)"
    assert s.emulator_mode == "I"
    assert s.model_number == "2"
    assert (s.rows, s.columns, s.cursor_row, s.cursor_col) == (24, 80, 22, 11)
    assert all(isinstance(v, int) for v in (s.rows, s.columns, s.cursor_row, s.cursor_col))
    assert s.window_id == "0x0"
    assert s.command_time == "0.006"


def test_status_line_serialize_roundtrip():
    raw = "L F U N N 2 24 80 22 11 0x0 0.001"
    assert PARSER.parse_status_line(raw).serialize() == raw


@pytest.mark.parametrize("raw", [
    "U F U C(127.0.0.1) I 2 24 80 22 11 0x0",
    "U F U C(127.0.0.1) I 2 24 80 22 11 0x0 0.000 extra",
    "",
])
def test_status_line_wrong_token_count(raw):
    with pytest.raises(ParseError) as exc:
        PARSER.parse_status_line(raw)
    assert exc.value.raw == raw


@pytest.mark.parametrize("field,idx", [
    ("rows", 6), ("columns", 7), ("cursor_row", 8), ("cursor_col", 9),
])
def test_status_line_non_integer_field(field, idx):
    tokens = "U F U C(127.0.0.1) I 2 24 80 22 11 0x0 0.000".split()
    tokens[idx] = "abc"
    raw = " ".join(tokens)
    with pytest.raises(ParseError) as exc:
        PARSER.parse_status_line(raw)
    assert field in str(exc.value)
    assert raw in exc.value.raw


# ---------------------------------------------------------------------------
# parse_readbuffer on hand-built responses
# ---------------------------------------------------------------------------


def test_readbuffer_cells_sf_and_dimensions_from_status():
    lines = [
        "SF(c0=c8) 41 00 42 43 44 45 46 47 48 49",
        "00 00 00 00 00 00 00 00 00 ff",
        "SF(c0=e0) 61 62 63 64 65 66 67 68 69 6a",
    ]
    s = _parse(lines, 3, 10, crow=1, ccol=4)
    assert (s.rows, s.columns, s.cursor_row, s.cursor_col) == (3, 10, 1, 4)
    assert len(s.cell_grid) == 3 and all(len(r) == 10 for r in s.cell_grid)
    assert s.cell_grid[0][0] == SFToken(c0=0xC8)
    assert s.cell_grid[0][1] == 0x41
    assert s.cell_grid[2][0] == SFToken(c0=0xE0)
    assert s.cell_grid[1][9] == 0xFF
    # 00 stays 0, not a space, in cell_grid
    assert s.cell_grid[0][2] == 0 and s.cell_grid[0][2] != 0x20
    assert s.text_grid[0][2] == " "


def test_readbuffer_data_prefix_is_stripped():
    s = _parse(["data: 41 42"], 1, 2)
    assert s.cell_grid == [[0x41, 0x42]]


def test_readbuffer_sa_token_position_and_no_cell():
    lines = ["41 SA(42=f2) 42 43 SA(42=00) 44"]
    s = _parse(lines, 1, 6)
    assert s.sa_tokens[0] == [(1, SAToken(0xF2)), (3, SAToken(0x00))]
    # SA doesn't occupy a cell: following cells keep consecutive columns
    assert s.cell_grid[0] == [0x41, 0x42, 0x43, 0x44, 0, 0]


@pytest.mark.parametrize("bad", ["zz", "SF(c0=zz)", "SF(c0=e)", "SA(42=zz)", "4"])
def test_readbuffer_bad_token_raises(bad):
    with pytest.raises(ParseError) as exc:
        _parse(["41 " + bad + " 42"], 1, 3)
    assert exc.value.raw == ""
    assert str(exc.value) == f"Unrecognised ReadBuffer token at row 0, index 1, length {len(bad)}"


# ---------------------------------------------------------------------------
# c0 decoding
# ---------------------------------------------------------------------------


def _single_field(c0: str):
    s = _parse([f"SF(c0={c0}) 41 42"], 1, 3)
    fields = s.fields
    assert len(fields) == 1
    return fields[0]


def test_c0_c8_unprotected():
    f = _single_field("c8")
    assert not f.protected and not f.hidden and not f.modified and not f.numeric
    assert f.c0 == 0xC8


@pytest.mark.parametrize("c0,numeric", [("e0", False), ("e8", False), ("f0", True), ("f8", True)])
def test_c0_protected_values(c0, numeric):
    f = _single_field(c0)
    assert f.protected
    assert f.hidden is False
    assert f.modified is False
    # bit 0x10 is set in f0/f8 and clear in e0/e8
    assert f.numeric is numeric


def test_c0_cc_hidden():
    f = _single_field("cc")
    assert f.hidden is True
    assert not f.protected


# ---------------------------------------------------------------------------
# Fixture-based
# ---------------------------------------------------------------------------


def test_logo_fixture():
    frame, status, s = _fixture_screen("tk5-logo")
    assert (s.rows, s.columns) == (24, 80)
    assert s.fields and all(f.protected for f in s.fields)
    assert not [f for f in s.fields if not f.protected]
    assert any("Hercules" in line for line in s.text_grid)
    assert not any(row for row in s.sa_tokens)
    assert not any("SA(" in line for line in frame.data_lines)


def test_logon_fixture_fields_and_cursor():
    frame, status, s = _fixture_screen("tk5-logon")
    assert (s.rows, s.columns) == (24, 80)
    assert (s.cursor_row, s.cursor_col) == (22, 11)
    assert any("Logon ===>" in line for line in s.text_grid)
    unprot = [f for f in s.fields if not f.protected]
    assert len(unprot) == 1
    f = unprot[0]
    assert f.c0 == 0xC8
    row = 22
    assert s.text_grid[row].startswith("Logon ===>")
    assert (f.start_row, f.start_col) == (row, 10)  # SF cell right after the prompt
    assert s.cell_grid[row][10] == SFToken(0xC8)


def test_logon_sa_regression_80_non_sa_tokens_per_row():
    frame, _, s = _fixture_screen("tk5-logon")
    assert len(frame.data_lines) == 24
    for line in frame.data_lines:
        assert _non_sa_count(line) == 80
    assert any(len(line.split()) > 80 for line in frame.data_lines)
    assert all(len(r) == 80 for r in s.cell_grid)
    assert any(row for row in s.sa_tokens)


@pytest.mark.parametrize("name", ["tk5-logon.readbuffer.txt", "tk5-logo.readbuffer.txt"])
def test_raw_captures_80_non_sa_tokens_per_row(name):
    lines = _capture_data_lines(name)
    assert len(lines) == 24
    for line in lines:
        assert _non_sa_count(line) == 80
    s = _parse(lines, 24, 80)
    assert all(len(r) == 80 for r in s.cell_grid)


# ---------------------------------------------------------------------------
# Field spanning
# ---------------------------------------------------------------------------


def test_logon_field_spans_rows_and_partition():
    _, _, s = _fixture_screen("tk5-logon")
    total = s.rows * s.columns
    flat = [c for row in s.cell_grid for c in row]
    sf_pos = [i for i, c in enumerate(flat) if isinstance(c, SFToken)]

    f = next(x for x in s.fields if not x.protected)
    start = f.start_row * s.columns + f.start_col
    nxt = sf_pos[(sf_pos.index(start) + 1) % len(sf_pos)]
    expected = (nxt - start - 1) % total
    assert f.byte_length == expected
    assert f.byte_length > s.columns - f.start_col - 1  # actually crosses a row

    assert sum(x.byte_length + 1 for x in s.fields) == total
