"""Property test: volatile content does not affect the match result (screen-recognizer)."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.connector.models import Screen
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.suggest import suggest_signature
from greenscreen.recognizer.view import ScreenView
from tests.screen_support import make_screen

_PRINTABLE = [chr(c) for c in range(0x20, 0x7F)]
_HIDDEN_C0 = 0xC0 | 0x0C
_UNPROT_C0 = 0xC0


@st.composite
def _time_or_date(draw) -> str:
    if draw(st.booleans()):
        return f"{draw(st.integers(0, 23)):02d}:{draw(st.integers(0, 59)):02d}"
    return f"{draw(st.integers(1, 28)):02d}.{draw(st.integers(1, 12)):02d}.{draw(st.integers(0, 99)):02d}"


@st.composite
def _screens_with_runs(draw) -> Screen:
    """24x80 screen: a title, a hidden field, an input field, and HH:MM / DD.MM.YY runs."""
    text = {(0, 20): draw(st.text(alphabet=_PRINTABLE[1:], min_size=3, max_size=12))}
    rows = draw(st.lists(st.integers(3, 22), min_size=1, max_size=6, unique=True))
    for r in rows:
        label = draw(st.text(alphabet="ABCDEFGHIJ ", min_size=0, max_size=6))
        col = draw(st.integers(len(label), 60))
        if label:
            text[(r, col - len(label))] = label
        text[(r, col)] = draw(_time_or_date())
    fields = []
    if draw(st.booleans()):  # hidden field on rows 0..1, closed by an SF on row 1
        fields.append((1, draw(st.integers(0, 5)), _HIDDEN_C0))
        fields.append((1, draw(st.integers(40, 70)), 0xC0 | 0x20))
        text[(1, 6)] = "x"  # data inside the hidden extent (must stay blanked)
    if draw(st.booleans()):
        fields.append((2, draw(st.integers(0, 70)), _UNPROT_C0))
    cursor = (draw(st.integers(0, 23)), draw(st.integers(0, 79)))
    return make_screen(24, 80, text=text, fields=fields, cursor=cursor)


# Feature: screen-recognizer, Property 2: Volatile content does not affect the result
# **Validates: Requirements 2.2, 2.4, 9.8, 11.2**
@settings(max_examples=150, deadline=None)
@given(screen=_screens_with_runs(), data=st.data())
def test_volatile_content_does_not_affect_result(screen, data):
    sig = suggest_signature(screen)
    assert sig.volatile  # every planted run on rows 3..22 is a suggested region

    before = signature_matches(sig, ScreenView(screen))
    assert before is True

    grid = [list(row) for row in screen.cell_grid]  # copy; the original is untouched
    hidden = ScreenView(screen).hidden_mask
    for reg in sig.volatile:
        for c in range(reg.col, reg.col + reg.length):
            cell = grid[reg.row][c]
            if not isinstance(cell, int) or hidden[reg.row * screen.columns + c]:
                continue  # keep SF tokens and hidden-field cells unchanged
            grid[reg.row][c] = ord(data.draw(st.sampled_from(_PRINTABLE)))

    mutated = Screen(
        rows=screen.rows,
        columns=screen.columns,
        cursor_row=screen.cursor_row,
        cursor_col=screen.cursor_col,
        cell_grid=grid,
        sa_tokens=[list(t) for t in screen.sa_tokens],
    )
    after = signature_matches(sig, ScreenView(mutated))
    assert after == before
    assert after is True
