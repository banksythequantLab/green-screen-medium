"""Property test: differences confined to hidden data cells change nothing."""
from __future__ import annotations

import copy

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.errors import AmbiguousScreenError, RecognizerError
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.signature import ScreenSignature, TextAtMatcher
from greenscreen.recognizer.suggest import suggest_signature
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import (
    SENTINEL_ALPHABET,
    sentinel_screens,
    signatures,
    small_screens,
)

_CELL_CHARS = [chr(c) for c in range(0x20, 0x7F)] + SENTINEL_ALPHABET
_REPLACEMENTS = [0] + [ord(ch) for ch in _CELL_CHARS]


def _outcome(fn):
    try:
        return ("ok", fn())
    except AmbiguousScreenError as exc:
        return (type(exc), tuple(exc.names))
    except RecognizerError as exc:
        return (type(exc), None)


# Feature: screen-recognizer, Property 20: Hidden-only differences change nothing
# **Validates: Requirements 3.7, 7.2, 7.5, 13.2, 13.5**
@settings(max_examples=150, deadline=None)
@given(
    rng=st.randoms(use_true_random=False),
    screen=st.one_of(
        sentinel_screens().map(lambda s: s.screen),
        small_screens(allow_hidden=True),
    ),
    sigs=st.lists(signatures(max_matchers=4, max_volatile=1), max_size=3),
)
def test_hidden_only_differences_change_nothing(rng, screen, sigs):
    view = ScreenView(screen)
    cols = screen.columns
    hidden_cells = [
        (i // cols, i % cols) for i, flag in enumerate(view.hidden_mask) if flag
    ]

    # Second screen: copy of the grid with only hidden data cells replaced.
    other = copy.deepcopy(screen)
    for r, c in hidden_cells:
        # Seeded Random: avoids one ``data.draw`` per hidden cell.
        other.cell_grid[r][c] = rng.choice(_REPLACEMENTS)
    other_view = ScreenView(other)

    assert other_view.hidden_mask == view.hidden_mask
    assert other_view.base_rows == view.base_rows

    # A text_at matcher over a hidden run behaves as if the cells held spaces.
    extra: list[ScreenSignature] = []
    if hidden_cells:
        r0, c0 = hidden_cells[0]
        k = 1
        while (
            k < 10
            and c0 + k < cols
            and view.hidden_mask[r0 * cols + c0 + k]
        ):
            k += 1
        spaces = ScreenSignature("hidden-spaces", (TextAtMatcher(r0, c0, " " * k),), (), "")
        assert signature_matches(spaces, view)
        assert signature_matches(spaces, other_view)
        for scr in (screen, other):
            cells = [scr.cell_grid[r0][c0 + i] for i in range(k)]
            if all(isinstance(x, int) and x not in (0, 0x20) for x in cells):
                real = "".join(chr(x) for x in cells)
                probe = ScreenSignature("probe", (TextAtMatcher(r0, c0, real),), (), "")
                assert not signature_matches(probe, ScreenView(scr))
        extra.append(spaces)

    own = _outcome(lambda: suggest_signature(screen))
    if own[0] == "ok":
        extra.append(own[1])

    # Unique names so duplicate-name errors do not mask the property.
    all_sigs = []
    seen: set[str] = set()
    for s in list(sigs) + extra:
        if s.name not in seen:
            seen.add(s.name)
            all_sigs.append(s)

    assert _outcome(lambda: recognize(screen, all_sigs)) == _outcome(
        lambda: recognize(other, all_sigs)
    )
    assert _outcome(lambda: suggest_signature(screen)) == _outcome(
        lambda: suggest_signature(other)
    )
