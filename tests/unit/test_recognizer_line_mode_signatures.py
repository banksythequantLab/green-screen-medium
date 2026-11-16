"""Unit tests for the bundled line-mode signatures (tso-pause, tso-ready)."""
from __future__ import annotations

import pytest

from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.view import ScreenView
from tests.screen_support import load_capture_screen, make_screen

_SIGS = {s.name: s for s in load_bundled_signatures()}


def _matches(name: str, screen) -> bool:
    return signature_matches(_SIGS[name], ScreenView(screen))


def _pause_screen(star_row: int, above: dict | None = None, below: dict | None = None):
    text = {(star_row, 0): " ***"}
    text.update(above or {})
    text.update(below or {})
    return make_screen(24, 80, text=text, cursor=(star_row, 5))


def test_tso_pause_matches_capture():
    assert _matches("tso-pause", load_capture_screen("tso-pause-2"))


@pytest.mark.parametrize("star_row", [10, 11])
@pytest.mark.parametrize(
    "above",
    [
        {},
        {(2, 1): "SOME OTHER TEXT"},
        {(0, 1): "A", (3, 5): "Different words here", (8, 1): "x"},
    ],
)
def test_tso_pause_matches_synthetic_with_any_text_above(star_row, above):
    assert _matches("tso-pause", _pause_screen(star_row, above=above))


@pytest.mark.parametrize("star_row", [10, 11])
def test_tso_pause_rejects_text_below_star_row(star_row):
    screen = _pause_screen(star_row, below={(star_row + 2, 1): "MORE OUTPUT"})
    assert not _matches("tso-pause", screen)


def test_tso_pause_rejects_cursor_not_after_stars():
    screen = make_screen(24, 80, text={(11, 0): " ***"}, cursor=(5, 5))
    assert not _matches("tso-pause", screen)


def test_tso_ready_matches_own_capture():
    assert _matches("tso-ready", load_capture_screen("tso-ready"))


def test_tso_ready_does_not_match_ispf_primary_menu():
    assert not _matches("tso-ready", load_capture_screen("ispf-primary-menu"))


def test_input_not_recognized_and_ready_differ_on_their_captures():
    inr = load_capture_screen("tso-input-not-recognized")
    ready = load_capture_screen("tso-ready")
    assert _matches("tso-input-not-recognized", inr)
    assert not _matches("tso-input-not-recognized", ready)
    assert _matches("tso-ready", ready)
    assert not _matches("tso-ready", inr)
