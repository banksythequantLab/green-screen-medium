"""Typed-over `tso-cleared` and the negative cases of `tso-reenter` (more-flows 3.4).

Needs no live host. Failure messages name a capture and a signature only.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.screens import build_comparison
from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.errors import UnknownScreenError
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.view import ScreenView
from tests.flow_support import typed_screen
from tests.screen_support import CAPTURE_NAMES, load_capture_screen

_SIGS = load_bundled_signatures()


def _matching(screen) -> list[str]:
    view = ScreenView(screen)
    return [s.name for s in _SIGS if signature_matches(s, view)]


def test_typed_over_cleared_screen_is_unknown_until_compared():
    cleared = load_capture_screen("tso-cleared")
    typed = typed_screen(cleared, "LISTCAT", mdt=True)
    assert typed != cleared
    with pytest.raises(UnknownScreenError):
        recognize(typed, _SIGS)

    field = cleared.find_field(cleared.cursor_row, cleared.cursor_col)
    assert field is not None
    triple = (field.start_row, field.start_col, field.byte_length)
    comparison = build_comparison(typed, cleared, [triple])
    assert recognize(comparison, _SIGS) == "tso-cleared"


def test_tso_reenter_matches_its_capture_only():
    assert _matching(load_capture_screen("tso-listds-reenter")) == ["tso-reenter"]


def test_tso_reenter_does_not_match_the_after_pa1_capture():
    screen = load_capture_screen("tso-listds-reenter-after-pa1")
    assert "tso-reenter" not in _matching(screen)
    assert recognize(screen, _SIGS) == "tso-ready"


def test_tso_reenter_signature_matches_no_other_capture():
    sig = next(s for s in _SIGS if s.name == "tso-reenter")
    others = [
        n for n in CAPTURE_NAMES
        if n != "tso-listds-reenter"
        and signature_matches(sig, ScreenView(load_capture_screen(n)))
    ]
    assert others == [], f"tso-reenter also matched captures {others}"


def test_tso_cleared_matches_no_other_capture():
    sig = next(s for s in _SIGS if s.name == "tso-cleared")
    others = [
        n for n in CAPTURE_NAMES
        if n != "tso-cleared"
        and signature_matches(sig, ScreenView(load_capture_screen(n)))
    ]
    assert others == [], f"tso-cleared also matched captures {others}"


def test_no_other_signature_matches_the_tso_cleared_capture():
    assert _matching(load_capture_screen("tso-cleared")) == ["tso-cleared"]
