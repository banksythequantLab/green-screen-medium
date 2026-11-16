"""Property test: a suggested signature recognizes the screen it came from."""
from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from greenscreen.connector.models import SFToken
from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.suggest import suggest_signature
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import sentinel_screens, small_screens

_RUNS = ("12:34", "00:00", "23:59", "07:05:09", "31.12.99", "01.01.00")


@st.composite
def screens_with_planted_times(draw):
    """Screens with and without fields or hidden fields, some with time/date runs."""
    base = draw(
        st.one_of(
            small_screens(allow_hidden=False),
            small_screens(allow_hidden=True),
            sentinel_screens().map(lambda s: s.screen),
        )
    )
    for _ in range(draw(st.integers(0, 3))):
        run = draw(st.sampled_from(_RUNS))
        if base.columns < len(run):
            continue
        r = draw(st.integers(0, base.rows - 1))
        c = draw(st.integers(0, base.columns - len(run)))
        row = base.cell_grid[r]
        if any(isinstance(row[c + i], SFToken) for i in range(len(run))):
            continue
        for i, ch in enumerate(run):
            row[c + i] = ord(ch)
    return base


# Feature: screen-recognizer, Property 1: Suggest then recognize
# **Validates: Requirements 5.2, 9.2, 11.1**
@settings(max_examples=200, deadline=None)
@given(screen=screens_with_planted_times())
def test_suggest_then_recognize(screen):
    try:
        sig = suggest_signature(screen)
    except SignatureError:
        # Raised only when every visible cell is blank and there is no field.
        view = ScreenView(screen)
        assert not view.fields
        assert all(r.rstrip(" ") == "" for r in view.base_rows)
        assume(False)
        return
    assert signature_matches(sig, ScreenView(screen))
    assert recognize(screen, [sig]) == sig.name
