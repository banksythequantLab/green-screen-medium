"""Property test for the redacted summary (screen-recognizer)."""
from __future__ import annotations

from hypothesis import given, settings

from greenscreen.recognizer.summary import build_summary
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import small_screens

_PLAIN = (str, int, bool)


def _only_plain(value) -> bool:
    if isinstance(value, _PLAIN):
        return True
    if isinstance(value, list):
        return all(_only_plain(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _only_plain(v) for k, v in value.items())
    return False


# Feature: screen-recognizer, Property 15: Redacted summary shape
# **Validates: Requirements 6.3, 6.4, 6.5, 6.10**
@settings(max_examples=200, deadline=None)
@given(screen=small_screens(allow_hidden=True))
def test_redacted_summary_shape(screen):
    fields = screen.fields
    summary = build_summary(ScreenView(screen))

    # Counts and geometry equal those of the Screen.
    assert summary.rows == screen.rows
    assert summary.columns == screen.columns
    assert summary.cursor == (screen.cursor_row, screen.cursor_col)
    assert summary.field_count == len(fields)
    assert summary.unprotected_count == sum(1 for f in fields if not f.protected)
    assert summary.hidden_count == sum(1 for f in fields if f.hidden)
    assert summary.fields == tuple(
        (f.start_row, f.start_col, f.byte_length, f.protected, f.hidden)
        for f in fields
    )
    if not fields:
        assert summary.field_count == summary.unprotected_count == summary.hidden_count == 0
        assert summary.fields == ()

    # Oracle: hidden data cells are "*", every other cell keeps the Screen's text.
    total = screen.rows * screen.columns
    expected = [list(row) for row in screen.text_grid]
    for f in fields:
        if f.hidden:
            start = f.start_row * screen.columns + f.start_col
            for off in range(1, f.byte_length + 1):
                lin = (start + off) % total
                expected[lin // screen.columns][lin % screen.columns] = "*"

    text = summary.to_text()
    lines = text.split("\n")
    assert len(lines) == screen.rows
    assert len(summary.row_text) == screen.rows
    for r, line in enumerate(lines):
        want = "".join(expected[r])
        # Trailing spaces are dropped; a trailing "*" run is kept.
        assert line == want.rstrip(" ")
        assert line == summary.row_text[r]

    # to_dict holds only str, int, bool, list and dict.
    d = summary.to_dict()
    assert isinstance(d, dict)
    assert _only_plain(d)
    assert len(d["fields"]) == len(fields)
