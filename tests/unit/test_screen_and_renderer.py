"""Unit tests for Screen methods and ScreenRenderer (Task 10.4).

Validates: Requirements 5.2, 5.3, 5.6, 5.7, 5.8, 8.3, 8.4
"""
from __future__ import annotations

import dataclasses

import pytest

from greenscreen.connector.models import Response, SAToken, SFToken, Screen
from greenscreen.connector.parser import ScreenParser
from greenscreen.connector.renderer import ScreenRenderer
from greenscreen.connector.testing.fixtures import load_bundled_fixture


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def make_screen(rows, cols, cells=None, sa=None, cursor=(0, 0)) -> Screen:
    """Build a blank (0x00) screen; `cells` maps (row, col) -> CellValue."""
    grid = [[0x00] * cols for _ in range(rows)]
    for (r, c), v in (cells or {}).items():
        grid[r][c] = v
    sa_tokens = [[] for _ in range(rows)]
    for r, lst in (sa or {}).items():
        sa_tokens[r] = list(lst)
    return Screen(rows, cols, cursor[0], cursor[1], grid, sa_tokens)


def parse_frame(frame) -> Screen:
    parser = ScreenParser()
    status = parser.parse_status_line(frame.status_line)
    return parser.parse_readbuffer(Response(True, frame.data_lines, status))


# ---------------------------------------------------------------------------
# text_at
# ---------------------------------------------------------------------------


class TestTextAt:
    def setup_method(self):
        cells = {(1, c): ord(ch) for c, ch in enumerate("ABCDEF")}
        self.s = make_screen(3, 6, cells)

    def test_valid_range(self):
        assert self.s.text_at(1, 1, 3) == "BCD"

    def test_exact_fit_at_end_of_row(self):
        assert self.s.text_at(1, 4, 2) == "EF"
        assert self.s.text_at(1, 0, 6) == "ABCDEF"

    @pytest.mark.parametrize(
        "row,col,length",
        [
            (-1, 0, 1),   # row < 0
            (3, 0, 1),    # row >= rows
            (0, -1, 1),   # col < 0
            (0, 6, 1),    # col >= cols
            (0, 0, 0),    # length < 1
            (0, 0, -2),   # length < 1
            (0, 4, 3),    # col + length > cols
        ],
    )
    def test_invalid_arguments_raise(self, row, col, length):
        with pytest.raises(ValueError):
            self.s.text_at(row, col, length)


# ---------------------------------------------------------------------------
# text_grid / cell_grid
# ---------------------------------------------------------------------------


class TestTextGrid:
    def test_cell_mapping_and_width(self):
        s = make_screen(2, 5, {(0, 0): SFToken(c0=0xC8), (0, 1): 0x41, (0, 2): 0x20, (1, 4): 0x7C})
        tg = s.text_grid
        assert tg[0] == " A" + "  " + " "  # SF->' ', 'A', ' ', 0x00->' ', 0x00->' '
        assert tg[1] == "    |"
        assert all(len(r) == 5 for r in tg)
        assert len(tg) == 2

    def test_zero_preserved_in_cell_grid(self):
        s = make_screen(1, 3, {(0, 1): 0x20})
        assert s.cell_grid[0][0] == 0x00
        assert s.cell_grid[0][1] == 0x20
        assert s.text_grid[0] == "   "


# ---------------------------------------------------------------------------
# find_field / fields
# ---------------------------------------------------------------------------


class TestFields:
    def test_unformatted_screen(self):
        s = make_screen(3, 4, {(1, 1): 0x41})
        assert s.fields == []
        for r in range(3):
            for c in range(4):
                assert s.find_field(r, c) is None

    def test_single_sf_covers_everything(self):
        s = make_screen(3, 4, {(1, 2): SFToken(c0=0xC8)})
        fields = s.fields
        assert len(fields) == 1
        assert fields[0].byte_length == 3 * 4 - 1
        for r in range(3):
            for c in range(4):
                assert s.find_field(r, c) == fields[0]

    def _two_field_screen(self):
        # linear: SF A at 1 (row0,col1), SF B at 10 (row2,col2); 3x4 grid
        cells = {
            (0, 1): SFToken(c0=0xE1),  # protected(0x20) + modified(0x01) + 0xC0 bits
            (0, 2): 0x58,
            (1, 0): 0x59,
            (2, 2): SFToken(c0=0x1C),   # numeric 0x10 + hidden 0x0C
            (2, 3): 0x31,
            (0, 0): 0x32,               # wrapped cell (linear 0)
        }
        return make_screen(3, 4, cells)

    def test_every_position_resolves_and_matches_fields(self):
        s = self._two_field_screen()
        fields = s.fields
        assert len(fields) == 2
        seen = set()
        for r in range(3):
            for c in range(4):
                f = s.find_field(r, c)
                assert f is not None
                assert f in fields
                seen.add((f.start_row, f.start_col))
        assert seen == {(0, 1), (2, 2)}

    def test_field_contents_spanning_rows(self):
        a = self._two_field_screen().fields[0]
        assert (a.start_row, a.start_col) == (0, 1)
        assert a.byte_length == 8  # linear 2..9
        assert a.text == "X Y" + " " * 5
        assert a.c0 == 0xE1
        assert a.protected and a.modified
        assert not a.numeric and not a.hidden

    def test_wrap_membership(self):
        s = self._two_field_screen()
        sf_b = s.find_field(2, 2)
        assert (sf_b.start_row, sf_b.start_col) == (2, 2)  # SF cell itself
        for pos in [(2, 3), (0, 0)]:  # last cell of grid, wrapped first cell
            assert s.find_field(*pos) == sf_b
        assert s.find_field(0, 1).start_col == 1  # SF A cell itself
        assert s.find_field(0, 1) == s.fields[0]

    def test_wrapping_field_text_and_flags(self):
        b = self._two_field_screen().fields[1]
        assert b.byte_length == 2
        assert b.text == "12"
        assert b.numeric and b.hidden and not b.protected and not b.modified
        assert b.c0 == 0x1C

    def test_hidden_requires_both_bits(self):
        s = make_screen(1, 4, {(0, 0): SFToken(c0=0x08)})
        assert s.fields[0].hidden is False
        s = make_screen(1, 4, {(0, 0): SFToken(c0=0x0C)})
        assert s.fields[0].hidden is True


# ---------------------------------------------------------------------------
# equality and immutability
# ---------------------------------------------------------------------------


class TestEqualityAndFrozen:
    def test_equal(self):
        a = make_screen(2, 3, {(0, 0): SFToken(0xC8)}, sa={0: [(1, SAToken(0xF2))]})
        b = make_screen(2, 3, {(0, 0): SFToken(0xC8)}, sa={0: [(1, SAToken(0xF2))]})
        assert a == b

    def test_unequal_sa_token(self):
        a = make_screen(2, 3, sa={0: [(1, SAToken(0xF2))]})
        b = make_screen(2, 3, sa={0: [(1, SAToken(0xF7))]})
        assert a != b

    def test_unequal_cell_zero_vs_space(self):
        assert make_screen(1, 2, {(0, 0): 0x00}) != make_screen(1, 2, {(0, 0): 0x20})

    def test_unequal_cursor(self):
        assert make_screen(1, 2, cursor=(0, 0)) != make_screen(1, 2, cursor=(0, 1))

    def test_frozen(self):
        field = make_screen(1, 4, {(0, 0): SFToken(0xC8)}).fields[0]
        with pytest.raises(dataclasses.FrozenInstanceError):
            field.text = "x"  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            SFToken(0xC8).c0 = 1  # type: ignore[misc]
        with pytest.raises(dataclasses.FrozenInstanceError):
            SAToken(0xF2).value = 1  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------


class TestRenderer:
    def test_exact_output(self):
        s = make_screen(
            2,
            4,
            {(0, 0): SFToken(0x00), (0, 1): 0x4C, (0, 3): SFToken(0xFF), (1, 0): 0x0A},
            sa={0: [(1, SAToken(0xF2)), (3, SAToken(0x00))], 1: [(2, SAToken(0xF7))]},
        )
        assert ScreenRenderer().render(s) == [
            "SF(c0=00) SA(42=f2) 4c 00 SA(42=00) SF(c0=ff)",
            "0a 00 SA(42=f7) 00 00",
        ]

    def test_no_data_prefix_and_row_count(self):
        out = ScreenRenderer().render(make_screen(3, 2))
        assert out == ["00 00"] * 3

    @pytest.mark.parametrize("name", ["tk5-logon", "tk5-logo"])
    def test_fixture_render_equals_data_lines(self, name):
        for frame in load_bundled_fixture(name):
            assert ScreenRenderer().render(parse_frame(frame)) == frame.data_lines

    def test_raw_c0_not_recomputed(self):
        s = make_screen(1, 3, {(0, 1): SFToken(c0=0x00)})
        rendered = ScreenRenderer().render(s)
        assert rendered == ["00 SF(c0=00) 00"]
        status = ScreenParser().parse_status_line("U F U C(h) I 2 1 3 0 0 0x0 0.000")
        back = ScreenParser().parse_readbuffer(Response(True, rendered, status))
        assert back.cell_grid[0][1] == SFToken(c0=0x00)
        assert back == s


# ---------------------------------------------------------------------------
# tk5-logon: Logon ===> input field wraps across rows
# ---------------------------------------------------------------------------


def test_logon_input_field_spans_rows():
    screen = parse_frame(load_bundled_fixture("tk5-logon")[0])
    cols = screen.columns
    total = screen.rows * cols

    sf_linear = [
        r * cols + c
        for r in range(screen.rows)
        for c in range(cols)
        if isinstance(screen.cell_grid[r][c], SFToken)
    ]
    c8 = [
        p for p in sf_linear
        if screen.cell_grid[p // cols][p % cols].c0 == 0xC8
    ]
    assert len(c8) == 1
    start = c8[0]
    nxt = min((p for p in sf_linear if p > start), default=None)
    if nxt is None:
        nxt = min(sf_linear) + total
    expected_len = nxt - start - 1

    assert (start // cols, start % cols) == (22, 10)  # observed in the capture
    assert nxt % total // cols == 23  # next SF is on the following row
    assert expected_len > cols - 11  # span crosses the row boundary

    field = next(f for f in screen.fields if f.c0 == 0xC8)
    assert (field.start_row, field.start_col) == (22, 10)
    assert field.byte_length == expected_len
    assert len(field.text) == expected_len
    assert not field.protected and not field.hidden

    # cell on the same row, and cells on the later row inside the span
    assert screen.find_field(22, 40) == field
    inside_next_row = (nxt - 1) % total
    r, c = divmod(inside_next_row, cols)
    assert r == 23
    assert screen.find_field(r, c) == field
    # the next SF cell itself belongs to a different field
    assert screen.find_field(*divmod(nxt % total, cols)) != field
