"""Unit tests for greenscreen.recognizer.suggest.suggest_signature (task 8.2)."""
from __future__ import annotations

import copy

import pytest

from greenscreen.recognizer import SignatureError, recognize
from greenscreen.recognizer.signature import (
    CursorFieldMatcher,
    FieldLayoutMatcher,
    TextAtMatcher,
    VolatileRegion,
)
from greenscreen.recognizer.suggest import suggest_signature
from tests.screen_support import load_capture_screen, make_screen

UNPROTECTED = 0x00
PROTECTED = 0x20
HIDDEN = 0x0C  # unprotected, non-display


def test_empty_screen_has_no_identifying_features() -> None:
    with pytest.raises(SignatureError, match="no identifying features"):
        suggest_signature(make_screen(24, 80))


def test_screen_with_only_a_field_gets_layout_and_cursor() -> None:
    screen = make_screen(24, 80, fields=[(5, 5, UNPROTECTED)], cursor=(6, 0))
    sig = suggest_signature(screen)
    assert sig.name == "unnamed-screen"
    assert sig.matchers == (
        FieldLayoutMatcher(1, ((5, 5),)),
        CursorFieldMatcher(5, 5, False),
    )
    assert sig.volatile == ()
    assert recognize(screen, [sig]) == "unnamed-screen"


def test_count_zero_layout_fallback() -> None:
    # Only a protected field and no text: no text candidate, no unprotected or input field.
    screen = make_screen(24, 80, fields=[(0, 0, PROTECTED)])
    sig = suggest_signature(screen)
    assert sig.matchers == (FieldLayoutMatcher(0, ()),)
    assert recognize(screen, [sig]) == sig.name


def test_supplied_name_used_unchanged() -> None:
    screen = make_screen(24, 80, text={(0, 0): "Hello World"})
    assert suggest_signature(screen, name="my_name-1").name == "my_name-1"
    assert suggest_signature(screen).name == "hello-world"


def test_first_row_only_clock_selects_next_stable_row() -> None:
    screen = make_screen(
        24, 80, text={(0, 70): "10:15:30", (2, 0): "Hello World"}
    )
    sig = suggest_signature(screen)
    assert sig.volatile == (VolatileRegion(0, 70, 8),)
    assert sig.matchers == (TextAtMatcher(2, 0, "Hello World"),)
    assert sig.name == "hello-world"
    assert recognize(screen, [sig]) == sig.name


def test_name_excludes_date_and_time() -> None:
    screen = make_screen(
        24, 80, text={(0, 0): "Logon", (0, 20): "15.11.26", (0, 40): "Time", (0, 50): "16:25"}
    )
    sig = suggest_signature(screen)
    assert sig.name == "logon-time"
    assert VolatileRegion(0, 20, 8) in sig.volatile
    assert VolatileRegion(0, 50, 5) in sig.volatile
    texts = [m.text for m in sig.matchers if isinstance(m, TextAtMatcher)]
    assert texts == ["Logon", "Time"]


def test_name_is_unnamed_screen_when_derived_value_empty() -> None:
    screen = make_screen(24, 80, text={(0, 0): "***"})
    assert suggest_signature(screen).name == "unnamed-screen"


def test_name_truncated_to_64_characters() -> None:
    screen = make_screen(24, 80, text={(0, 0): "a" * 100})
    assert suggest_signature(screen).name == "a" * 64


def test_tk5_logon_capture() -> None:
    screen = load_capture_screen("tk5-logon")
    sig = suggest_signature(screen)
    # Row 0 is "Terminal   CUU0C0 ... Date  <dd.mm.yy>"; the date is blanked, so the
    # name is the lowercase words joined by single dashes (Req 9.7).
    assert sig.name == "terminal-cuu0c0-date"
    assert VolatileRegion(0, 72, 8) in sig.volatile
    assert VolatileRegion(1, 72, 8) in sig.volatile
    assert TextAtMatcher(0, 0, "Terminal") in sig.matchers
    assert recognize(screen, [sig]) == sig.name


def test_ispf_primary_menu_capture() -> None:
    screen = load_capture_screen("ispf-primary-menu")
    sig = suggest_signature(screen)
    assert sig.name == "ispf-primary-option-menu"
    assert sig.volatile == (VolatileRegion(3, 71, 5),)
    assert TextAtMatcher(0, 28, "ISPF primary option menu") in sig.matchers
    assert FieldLayoutMatcher(1, ((1, 13),)) in sig.matchers
    assert CursorFieldMatcher(1, 13, False) in sig.matchers
    assert recognize(screen, [sig]) == sig.name


def test_hidden_field_recorded_by_position_and_flag_only() -> None:
    screen = make_screen(
        24,
        80,
        text={(0, 0): "Password:", (0, 10): "secret"},
        fields=[(0, 9, HIDDEN), (0, 20, PROTECTED)],
        cursor=(0, 10),
    )
    sig = suggest_signature(screen)
    assert sig.matchers == (
        TextAtMatcher(0, 0, "Password:"),
        FieldLayoutMatcher(1, ((0, 9),)),
        CursorFieldMatcher(0, 9, True),
    )
    assert "secret" not in sig.to_yaml()
    assert recognize(screen, [sig]) == sig.name


def test_all_candidates_overlapping_hidden_field_leave_layout_only() -> None:
    screen = make_screen(
        24,
        80,
        text={(0, 1): "secret"},
        fields=[(0, 0, HIDDEN), (0, 10, PROTECTED)],
        cursor=(5, 5),  # outside the hidden field: no cursor matcher
    )
    before = copy.deepcopy(screen.cell_grid)
    sig = suggest_signature(screen)
    assert not any(isinstance(m, TextAtMatcher) for m in sig.matchers)
    assert sig.matchers == (FieldLayoutMatcher(1, ((0, 0),)),)
    assert sig.name == "unnamed-screen"
    assert "secret" not in sig.to_yaml()
    assert screen.cell_grid == before
    assert recognize(screen, [sig]) == sig.name


def test_suggest_does_not_modify_screen_and_is_deterministic() -> None:
    screen = load_capture_screen("tk5-logon")
    before = copy.deepcopy(screen.cell_grid)
    first = suggest_signature(screen)
    assert screen.cell_grid == before
    assert suggest_signature(screen) == first
