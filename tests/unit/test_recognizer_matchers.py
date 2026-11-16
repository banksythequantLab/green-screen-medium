"""Unit tests for every matcher kind (satisfied and unsatisfied cases).

Covers requirements 1.4-1.8, 1.15, 1.16, 2.3, 7.5, 10.1, 10.11.
"""
from __future__ import annotations

from greenscreen.recognizer.matching import matcher_satisfied, signature_matches
from greenscreen.recognizer.signature import (
    BeforeCursorMatcher,
    CursorFieldMatcher,
    FieldLayoutMatcher,
    LastRowMatcher,
    RegionRegexMatcher,
    RowContainsMatcher,
    ScreenSignature,
    TextAtMatcher,
    VolatileRegion,
)
from greenscreen.recognizer.view import ScreenView
from tests.screen_support import load_capture_screen, make_screen

UNPROTECTED = 0x00
HIDDEN_UNPROTECTED = 0x0C


def check(matcher, screen, volatile=()) -> bool:
    view = ScreenView(screen)
    return matcher_satisfied(matcher, view.visible_rows(volatile), view)


# --- text_at -------------------------------------------------------------

def test_text_at_satisfied_and_unsatisfied():
    s = make_screen(24, 80, {(2, 5): "Hello"})
    assert check(TextAtMatcher(2, 5, "Hello"), s) is True
    assert check(TextAtMatcher(2, 5, "hello"), s) is False
    assert check(TextAtMatcher(2, 6, "Hello"), s) is False


def test_text_at_outside_screen_unsatisfied():
    s = make_screen(24, 80, {(0, 0): "x"})
    assert check(TextAtMatcher(30, 0, "x"), s) is False
    assert check(TextAtMatcher(0, 79, "xy"), s) is False


# --- row_contains --------------------------------------------------------

def test_row_contains_satisfied_and_unsatisfied():
    s = make_screen(24, 80, {(3, 10): "INPUT NOT RECOGNIZED"})
    assert check(RowContainsMatcher(3, "NOT REC"), s) is True
    assert check(RowContainsMatcher(3, "not rec"), s) is False
    assert check(RowContainsMatcher(4, "NOT REC"), s) is False
    assert check(RowContainsMatcher(99, "NOT REC"), s) is False


# --- field_layout --------------------------------------------------------

def test_field_layout_satisfied_and_unsatisfied():
    s = make_screen(
        24, 80, fields=[(0, 0, 0x20), (1, 0, UNPROTECTED), (5, 10, UNPROTECTED)]
    )
    assert check(FieldLayoutMatcher(2, ((1, 0), (5, 10))), s) is True
    assert check(FieldLayoutMatcher(2, ((5, 10), (1, 0))), s) is False
    assert check(FieldLayoutMatcher(1, ((1, 0),)), s) is False


def test_field_layout_zero_fields_on_unformatted_screen():
    s = make_screen(24, 80)
    assert check(FieldLayoutMatcher(0, ()), s) is True
    assert check(FieldLayoutMatcher(1, ((0, 0),)), s) is False


# --- cursor_field --------------------------------------------------------

def test_cursor_field_satisfied_and_unsatisfied():
    s = make_screen(24, 80, fields=[(1, 0, UNPROTECTED)], cursor=(1, 5))
    assert check(CursorFieldMatcher(1, 0, False), s) is True
    assert check(CursorFieldMatcher(1, 0, True), s) is False
    assert check(CursorFieldMatcher(2, 0, False), s) is False


def test_cursor_field_unformatted_screen_unsatisfied():
    s = make_screen(24, 80, cursor=(1, 5))
    assert check(CursorFieldMatcher(1, 0, False), s) is False


# --- region_regex --------------------------------------------------------

def test_region_regex_satisfied_and_unsatisfied():
    s = make_screen(24, 80, {(0, 10): "USER 42"})
    assert check(RegionRegexMatcher(0, 10, 10, r"USER \d+"), s) is True
    assert check(RegionRegexMatcher(0, 10, 10, r"^\d+"), s) is False
    assert check(RegionRegexMatcher(0, 10, 4, r"\d"), s) is False  # region too short


def test_region_regex_outside_screen_unsatisfied():
    s = make_screen(24, 80, {(0, 0): "x"})
    assert check(RegionRegexMatcher(0, 75, 10, "x"), s) is False
    assert check(RegionRegexMatcher(40, 0, 5, "x"), s) is False


# --- last_row ------------------------------------------------------------

def test_last_row_satisfied_on_pause_capture():
    s = load_capture_screen("tso-pause-2")
    assert check(LastRowMatcher(" ***"), s) is True
    assert check(LastRowMatcher("COBOL"), s) is False


def test_last_row_leading_space_is_significant():
    s = load_capture_screen("tso-ready")
    assert check(LastRowMatcher(" READY"), s) is True
    assert check(LastRowMatcher("READY"), s) is False


def test_last_row_uses_last_non_blank_row_and_ignores_trailing_spaces():
    s = make_screen(24, 80, {(2, 0): "first", (7, 3): "last  "})
    assert check(LastRowMatcher("   last"), s) is True
    assert check(LastRowMatcher("first"), s) is False


def test_last_row_unsatisfied_when_no_non_blank_row():
    s = make_screen(24, 80)
    assert check(LastRowMatcher(" READY"), s) is False


# --- before_cursor -------------------------------------------------------

def test_before_cursor_satisfied_on_pause_capture():
    s = load_capture_screen("tso-pause-2")
    assert (s.cursor_row, s.cursor_col) == (11, 5)
    assert check(BeforeCursorMatcher(" ***"), s) is True
    assert check(BeforeCursorMatcher(" READY"), s) is False


def test_before_cursor_leading_space_is_significant():
    s = make_screen(24, 80, {(4, 0): "READY"}, cursor=(4, 7))
    assert check(BeforeCursorMatcher("READY"), s) is True
    assert check(BeforeCursorMatcher(" READY"), s) is False
    s2 = make_screen(24, 80, {(4, 0): " READY"}, cursor=(4, 7))
    assert check(BeforeCursorMatcher(" READY"), s2) is True


def test_before_cursor_excludes_cursor_column():
    s = make_screen(24, 80, {(4, 0): "AB"}, cursor=(4, 1))
    assert check(BeforeCursorMatcher("A"), s) is True
    assert check(BeforeCursorMatcher("AB"), s) is False


def test_before_cursor_unsatisfied_when_cursor_outside_screen():
    base = {(0, 0): "READY"}
    assert check(BeforeCursorMatcher("READY"), make_screen(24, 80, base, cursor=(24, 5))) is False
    assert check(BeforeCursorMatcher("READY"), make_screen(24, 80, base, cursor=(0, 80))) is False
    assert check(BeforeCursorMatcher("READY"), make_screen(24, 80, base, cursor=(-1, 5))) is False


# --- hidden fields and volatile regions ----------------------------------

def test_text_matcher_over_hidden_field_sees_spaces():
    s = make_screen(
        24, 80, {(0, 1): "SECRET"}, fields=[(0, 0, HIDDEN_UNPROTECTED), (0, 10, 0x20)]
    )
    assert check(TextAtMatcher(0, 1, " " * 6), s) is True
    assert check(TextAtMatcher(0, 1, "SECRET"), s) is False
    assert check(RowContainsMatcher(0, "SECRET"), s) is False
    assert check(RegionRegexMatcher(0, 1, 6, r"^ {6}$"), s) is True

    # Whatever the cells hold, the matcher sees spaces.
    other = make_screen(
        24, 80, {(0, 1): "XYZ123"}, fields=[(0, 0, HIDDEN_UNPROTECTED), (0, 10, 0x20)]
    )
    assert check(TextAtMatcher(0, 1, " " * 6), other) is True


def test_volatile_region_blanks_cells_for_own_signature_only():
    s = make_screen(24, 80, {(0, 0): "Time ", (0, 5): "12:34"})
    vol = VolatileRegion(0, 5, 5)
    sig_a = ScreenSignature(
        "sig-a", (TextAtMatcher(0, 0, "Time"), RowContainsMatcher(0, "Time     ")), (vol,)
    )
    sig_b = ScreenSignature("sig-b", (RowContainsMatcher(0, "12:34"),))
    sig_c = ScreenSignature("sig-c", (RowContainsMatcher(0, "Time     "),))
    # sig_a blanks the time; sig_b and sig_c do not see sig_a's volatile region.
    assert signature_matches(sig_a, ScreenView(s)) is True
    assert signature_matches(sig_b, ScreenView(s)) is True
    assert signature_matches(sig_c, ScreenView(s)) is False


def test_signature_requires_every_matcher():
    s = make_screen(24, 80, {(0, 0): "ABC"})
    ok = ScreenSignature("ok", (TextAtMatcher(0, 0, "ABC"), RowContainsMatcher(0, "B")))
    bad = ScreenSignature("bad", (TextAtMatcher(0, 0, "ABC"), RowContainsMatcher(0, "Z")))
    assert signature_matches(ok, ScreenView(s)) is True
    assert signature_matches(bad, ScreenView(s)) is False
