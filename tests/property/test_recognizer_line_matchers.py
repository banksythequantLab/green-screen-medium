"""Property tests for the ``last_row`` and ``before_cursor`` matchers and the
bundled ``tso-pause`` signature."""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.matching import matcher_satisfied, signature_matches
from greenscreen.recognizer.signature import BeforeCursorMatcher, LastRowMatcher
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import line_mode_screens, small_screens
from tests.screen_support import make_screen

_TEXT = st.text(alphabet=[chr(c) for c in range(0x20, 0x7F)], min_size=1, max_size=20)


@st.composite
def _outside_cursor(draw, rows: int, columns: int) -> tuple[int, int]:
    """A cursor that is negative, at or above ``rows``, or at or above ``columns``."""
    kind = draw(st.sampled_from(("neg_row", "neg_col", "row_hi", "col_hi")))
    if kind == "neg_row":
        return draw(st.integers(-1000, -1)), draw(st.integers(-5, columns + 5))
    if kind == "neg_col":
        return draw(st.integers(-5, rows + 5)), draw(st.integers(-1000, -1))
    if kind == "row_hi":
        return rows + draw(st.integers(0, 1000)), draw(st.integers(-5, columns + 5))
    return draw(st.integers(-5, rows + 5)), columns + draw(st.integers(0, 1000))


# Feature: screen-recognizer, Property 9: last_row and before_cursor unsatisfied cases
# **Validates: Requirements 1.15, 1.16, 11.11**
@settings(max_examples=100, deadline=None)
@given(
    data=st.data(),
    blank_dims=st.tuples(st.integers(1, 24), st.integers(1, 80)),
    last_text=_TEXT,
    cursor_text=_TEXT,
    screen=small_screens(),
)
def test_last_row_and_before_cursor_unsatisfied(
    data, blank_dims, last_text, cursor_text, screen
):
    # last_row: a screen with no non-blank visible cell never satisfies it.
    rows, columns = blank_dims
    blank = make_screen(rows, columns)
    blank_view = ScreenView(blank)
    assert not matcher_satisfied(
        LastRowMatcher(last_text), blank_view.visible_rows(()), blank_view
    )

    # before_cursor: a cursor outside the screen is unsatisfied and never raises.
    cursor = data.draw(_outside_cursor(screen.rows, screen.columns))
    screen.cursor_row, screen.cursor_col = cursor
    view = ScreenView(screen)
    assert not matcher_satisfied(
        BeforeCursorMatcher(cursor_text), view.visible_rows(()), view
    )


# Feature: screen-recognizer, Property 8: tso-pause matches wherever the *** row sits
# **Validates: Requirements 8.19, 8.20, 11.10, 11.11**
@settings(max_examples=100, deadline=None)
@given(lm=line_mode_screens())
def test_tso_pause_independent_of_text_above(lm):
    pause = next(s for s in load_bundled_signatures() if s.name == "tso-pause")
    assert 1 <= lm.pause_row <= 22
    assert signature_matches(pause, ScreenView(lm.screen))
