"""Self-tests of the hidden-cell helpers in tests/connector_support.py."""
from __future__ import annotations

from greenscreen.connector.models import Screen, SFToken
from tests.connector_support import (
    collect_exception_text,
    forbidden_forms,
    forms_of_run,
    hidden_runs,
)

HIDDEN = 0xCC  # (c0 & 0x0C) == 0x0C
PLAIN = 0xC8


def _screen(placements: dict[tuple[int, int], object], rows=4, columns=20) -> Screen:
    grid = [[0x20] * columns for _ in range(rows)]
    for (r, c), v in placements.items():
        grid[r][c] = v
    return Screen(rows, columns, 0, 0, grid, [[] for _ in range(rows)])


def _put(placements, row, col, data: bytes):
    for i, b in enumerate(data):
        placements[(row, col + i)] = b


def test_two_hidden_fields_are_found_and_plain_fields_skipped():
    p: dict = {(0, 0): SFToken(PLAIN), (1, 0): SFToken(HIDDEN), (2, 0): SFToken(PLAIN),
               (3, 0): SFToken(0xCC)}
    _put(p, 1, 1, b"abcde")
    _put(p, 3, 1, b"wxyz")
    s = _screen(p)
    runs = hidden_runs(s)
    assert len(runs) == 2
    first, per_row = runs[0]
    assert first == [ord(ch) for ch in "abcde"] + [0x20] * 14
    assert per_row == [first]
    # second run wraps past the end of the screen to the SF at (0, 0)
    second, second_rows = runs[1]
    assert second[:4] == [ord(ch) for ch in "wxyz"]
    assert len(second) == 19  # rest of row 3; the next SF is at (0, 0)
    assert [len(r) for r in second_rows] == [19]


def test_wrapped_run_splits_per_row_and_includes_nulls():
    p: dict = {(0, 18): SFToken(HIDDEN), (1, 5): SFToken(PLAIN), (0, 19): 0, (1, 0): 0x41}
    s = _screen(p)
    whole, rows = hidden_runs(s)[0]
    assert whole[0] == 0 and whole[1] == 0x41
    assert [len(r) for r in rows] == [1, 5]
    assert sum(rows, []) == whole


def test_run_shorter_than_four_bytes_yields_no_forms():
    p: dict = {(0, 0): SFToken(HIDDEN), (0, 4): SFToken(PLAIN), (1, 0): SFToken(PLAIN)}
    _put(p, 0, 1, b"abc")
    s = _screen(p)
    assert hidden_runs(s)[0][0] == [97, 98, 99]
    assert forbidden_forms(s) == set()


def test_forms_of_secret_run_spelled_out():
    # every hex digit of this run is 0-9, so lower and upper case coincide and
    # the set holds the Plain_Form and two distinct Hex_Forms
    assert forms_of_run(list(b"s3Cr3t!x")) == {
        "s3Cr3t!x",
        "7333437233742178",
        "73 33 43 72 33 74 21 78",
    }


def test_forms_of_run_has_four_hex_forms_when_letters_occur():
    assert forms_of_run([0xAB, 0xCD, 0xEF, 0x41]) == {
        "\xab\xcd\xef" + "A",
        "abcdef41",
        "ab cd ef 41",
        "ABCDEF41",
        "AB CD EF 41",
    }


def test_forbidden_forms_include_whole_run_and_row_pieces():
    p: dict = {(0, 14): SFToken(HIDDEN), (1, 5): SFToken(PLAIN)}
    _put(p, 0, 15, b"vwxyz")
    _put(p, 1, 0, b"qrstu")
    s = _screen(p)
    whole, rows = hidden_runs(s)[0]
    assert [len(r) for r in rows] == [5, 5]
    forms = forbidden_forms(s)
    assert "vwxyzqrstu" in forms
    assert "vwxyz" in forms and "qrstu" in forms


def test_one_byte_row_piece_is_skipped():
    p: dict = {(0, 18): SFToken(HIDDEN), (1, 4): SFToken(PLAIN)}
    _put(p, 0, 19, b"z")
    _put(p, 1, 0, b"qrst")
    s = _screen(p)
    forms = forbidden_forms(s)
    assert "zqrst" in forms and "qrst" in forms
    assert "z" not in forms and "7a" not in forms

class _Err(Exception):
    def __init__(self, msg, data_lines):
        super().__init__(msg)
        self.data_lines = data_lines


def test_exclude_attrs_skips_data_lines_on_exc_and_cause_default_keeps_it():
    cause = _Err("inner", ["CAUSE-LINE"])
    exc = _Err("outer", ["OUTER-LINE"])
    exc.__cause__ = cause
    kept = " ".join(collect_exception_text(exc))
    assert "OUTER-LINE" in kept and "CAUSE-LINE" in kept
    skipped = " ".join(collect_exception_text(exc, exclude_attrs={"data_lines"}))
    assert "OUTER-LINE" not in skipped and "CAUSE-LINE" not in skipped
    assert "outer" in skipped and "inner" in skipped
