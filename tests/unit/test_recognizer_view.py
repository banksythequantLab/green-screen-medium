"""Unit tests for ScreenView on the captures and on synthetic screens."""
from __future__ import annotations

from greenscreen.recognizer.matching import matcher_satisfied
from greenscreen.recognizer.signature import CursorFieldMatcher, FieldLayoutMatcher
from greenscreen.recognizer.view import ScreenView
from tests.screen_support import load_capture_screen, make_screen


def _starts(fields):
    return [(f.start_row, f.start_col) for f in fields]


def test_password_prompt_hidden_field_is_input_field():
    view = ScreenView(load_capture_screen("tso-password-prompt"))
    inputs = _starts(view.input_fields())
    assert (1, 0) in inputs
    assert (0, 0) not in inputs
    hidden = next(f for f in view.fields if (f.start_row, f.start_col) == (1, 0))
    assert hidden.hidden and not hidden.protected
    plain = next(f for f in view.fields if (f.start_row, f.start_col) == (0, 0))
    assert not plain.protected and not plain.hidden


def test_ispf_menu_single_input_field_holds_cursor():
    view = ScreenView(load_capture_screen("ispf-primary-menu"))
    inputs = view.input_fields()
    assert len(inputs) == 1
    cursor_field = view.containing_field(view.cursor_row, view.cursor_col)
    assert inputs[0] is cursor_field
    assert not inputs[0].protected


def test_unformatted_screen_geometry():
    screen = make_screen(24, 80, text={(0, 0): "HELLO"}, cursor=(3, 4))
    view = ScreenView(screen)
    assert view.containing_field(3, 4) is None
    assert view.fields == ()
    assert view.unprotected_fields() == ()
    assert view.input_fields() == ()


def test_unformatted_screen_matchers():
    view = ScreenView(make_screen(24, 80, cursor=(3, 4)))
    rows = view.visible_rows(())
    assert not matcher_satisfied(CursorFieldMatcher(3, 4, False), rows, view)
    assert matcher_satisfied(FieldLayoutMatcher(0, ()), rows, view)


def test_hidden_unprotected_field_without_cursor_is_input_field():
    # Hidden unprotected field at (5, 0); the cursor sits in a protected field.
    screen = make_screen(
        24,
        80,
        text={(5, 1): "SECRET"},
        fields=[(0, 0, 0x20), (5, 0, 0x0C), (6, 0, 0x20)],
        cursor=(0, 5),
    )
    view = ScreenView(screen)
    cursor_field = view.containing_field(0, 5)
    assert cursor_field is not None and cursor_field.protected
    inputs = view.input_fields()
    assert _starts(inputs) == [(5, 0)]
    assert inputs[0].hidden
    assert "SECRET" not in "".join(view.base_rows)
    assert "******" in view.summary_rows()[5]
