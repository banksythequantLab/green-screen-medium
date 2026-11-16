"""Property test: the bundled ``tso-pause`` signature is position independent."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.view import ScreenView
from tests.screen_support import make_screen

_PRINTABLE = st.text(alphabet=[chr(c) for c in range(0x20, 0x7F)], max_size=80)


@st.composite
def _pause_screens(draw):
    n = draw(st.integers(1, 22))
    above = draw(st.lists(_PRINTABLE, min_size=n, max_size=n))
    text = {(r, 0): line for r, line in enumerate(above)}
    text[(n, 0)] = " ***"
    return n, make_screen(24, 80, text=text, cursor=(n, 5))


# Feature: screen-recognizer, Property 8: tso-pause matches wherever the *** row sits
# **Validates: Requirements 8.19, 8.20, 11.10**
@settings(max_examples=100, deadline=None)
@given(case=_pause_screens())
def test_tso_pause_matches_wherever_the_stars_row_sits(case):
    n, screen = case
    view = ScreenView(screen)
    signatures = load_bundled_signatures()
    for sig in signatures:
        expected = sig.name == "tso-pause"
        assert signature_matches(sig, view) is expected, (n, sig.name)
