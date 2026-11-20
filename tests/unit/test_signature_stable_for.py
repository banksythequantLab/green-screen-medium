"""The optional ``stable_for`` signature member (more-flows task 6.7; Requirements 24.1, 24.2, 24.4).

Needs no live host. Error messages must name the key and show no value.
"""
from __future__ import annotations

from importlib import resources

import pytest

from greenscreen.flow.screens import build_comparison
from greenscreen.recognizer import load_bundled_signatures, recognize
from greenscreen.recognizer.bundled import _MANIFEST
from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.signature import ScreenSignature, TextAtMatcher

from tests.flow_support import typed_screen
from tests.screen_support import load_capture_screen

_SIGS = load_bundled_signatures()
_BY_NAME = {s.name: s for s in _SIGS}


def _file_text(name: str) -> str:
    return (
        resources.files("greenscreen.recognizer.signatures")
        .joinpath(f"{name}.yaml")
        .read_text(encoding="utf-8")
    )


def _sig(stable_for) -> ScreenSignature:
    return ScreenSignature(
        name="sample",
        matchers=(TextAtMatcher(row=0, col=0, text="HELLO"),),
        description="A sample.",
        stable_for=stable_for,
    )


def _cleared_text_with(line: str) -> str:
    text = _file_text("tso-cleared")
    assert "stable_for: 0.3\n" in text
    return text.replace("stable_for: 0.3\n", line + "\n" if line else "")


# --------------------------------------------------------------------------
# Emit
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [0.3, 1, 5, 4.5])
def test_stable_for_is_emitted_directly_after_description(value):
    lines = _sig(value).to_yaml().splitlines()
    at = next(i for i, ln in enumerate(lines) if ln.startswith("description:"))
    assert lines[at + 1].startswith("stable_for: ")
    assert sum(ln.startswith("stable_for:") for ln in lines) == 1
    assert lines[at + 2] == "matchers:"


@pytest.mark.parametrize("value", [0, 0.0])
def test_no_stable_for_line_when_zero(value):
    assert "stable_for" not in _sig(value).to_yaml()
    assert "stable_for" not in ScreenSignature(
        name="sample", matchers=(TextAtMatcher(row=0, col=0, text="HELLO"),)
    ).to_yaml()


def test_the_other_eleven_bundled_files_equal_their_emitted_text_and_hold_no_stable_for():
    others = [n for n in _MANIFEST if n != "tso-cleared"]
    assert len(others) == 11
    for name in others:
        text = _file_text(name)
        assert _BY_NAME[name].to_yaml() == text, name
        assert "stable_for" not in text, name
        assert _BY_NAME[name].stable_for == 0.0, name


def test_tso_cleared_loads_with_the_settle_time_and_its_file_equals_the_emitted_text():
    sig = _BY_NAME["tso-cleared"]
    assert sig.stable_for == 0.3
    assert isinstance(sig.stable_for, float)
    text = _file_text("tso-cleared")
    assert sig.to_yaml() == text
    assert ScreenSignature.from_yaml(text) == sig


# --------------------------------------------------------------------------
# Reader
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "literal, secret",
    [
        ("true", "true"),
        ("SECRETWORD", "SECRETWORD"),
        ("'0.3'", "'0.3'"),
        ("-0.7", "0.7"),
        ("5.01", "5.01"),
        ("[7919]", "7919"),
    ],
)
def test_bad_values_are_rejected_naming_the_key_and_showing_no_value(literal, secret):
    text = _cleared_text_with(f"stable_for: {literal}")
    with pytest.raises(SignatureError) as info:
        ScreenSignature.from_yaml(text)
    message = str(info.value)
    assert "stable_for" in message
    assert secret.strip("'") not in message
    assert "True" not in message


def test_an_int_is_accepted_and_stored_as_a_float():
    sig = ScreenSignature.from_yaml(_cleared_text_with("stable_for: 1"))
    assert sig.stable_for == 1.0
    assert isinstance(sig.stable_for, float)


def test_the_bounds_are_accepted():
    assert ScreenSignature.from_yaml(_cleared_text_with("stable_for: 0")).stable_for == 0.0
    assert ScreenSignature.from_yaml(_cleared_text_with("stable_for: 5")).stable_for == 5.0


def test_another_unknown_key_is_still_refused_by_name():
    text = _cleared_text_with("stable_for: 0.3\nbogus: 1")
    with pytest.raises(SignatureError, match="unknown key 'bogus'"):
        ScreenSignature.from_yaml(text)


def test_the_constructor_refuses_the_same_values():
    for bad in (True, "0.3", -1, 5.01, [1]):
        with pytest.raises(SignatureError) as info:
            _sig(bad)
        assert "stable_for" in str(info.value)


# --------------------------------------------------------------------------
# recognize stays pure
# --------------------------------------------------------------------------

def test_recognize_returns_tso_cleared_for_the_capture_and_the_typed_over_screen():
    cleared = load_capture_screen("tso-cleared")
    assert recognize(cleared, _SIGS) == "tso-cleared"

    typed = typed_screen(cleared, "LISTCAT", mdt=True)
    field = cleared.find_field(cleared.cursor_row, cleared.cursor_col)
    assert field is not None
    triple = (field.start_row, field.start_col, field.byte_length)
    comparison = build_comparison(typed, cleared, [triple])
    assert recognize(comparison, _SIGS) == "tso-cleared"
