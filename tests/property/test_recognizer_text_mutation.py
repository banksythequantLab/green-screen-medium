"""Property test: one changed text-matched cell breaks the match (screen-recognizer)."""
from __future__ import annotations

import copy

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.signature import TextAtMatcher
from greenscreen.recognizer.suggest import suggest_signature
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import small_screens


# Feature: screen-recognizer, Property 3: Changing one text-matched cell breaks the match
# **Validates: Requirements 1.4, 11.3**
@settings(max_examples=200, deadline=None)
@given(
    screen=small_screens(allow_hidden=True),
    pick=st.data(),
)
def test_one_cell_mutation_breaks_match(screen, pick):
    try:
        sig = suggest_signature(screen)
    except SignatureError:
        assume(False)
    text_matchers = [m for m in sig.matchers if isinstance(m, TextAtMatcher)]
    assume(text_matchers)

    # Sanity: the unmodified screen matches its own suggested signature.
    assert signature_matches(sig, ScreenView(screen))

    m = pick.draw(st.sampled_from(text_matchers))
    offset = pick.draw(st.integers(0, len(m.text) - 1))
    row, col = m.row, m.col + offset
    shift = pick.draw(st.integers(1, 94))

    mutated = copy.deepcopy(screen)  # never touch the original
    original = m.text[offset]
    replacement = chr(0x20 + (ord(original) - 0x20 + shift) % 95)
    assert replacement != original
    mutated.cell_grid[row][col] = ord(replacement)

    assert not signature_matches(sig, ScreenView(mutated))
