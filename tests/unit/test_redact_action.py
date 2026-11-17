"""Unit tests for greenscreen.connector._redact.redact_action.

Validates: tn3270-connector Requirements 12.9-12.14, 12.22.
"""
from __future__ import annotations

import re
import sys

import pytest

from greenscreen.connector._redact import redact_action
from greenscreen.connector.parser import _escape_s3270_string

_SHAPE = re.compile(r"^String\(<(0|[1-9][0-9]*|\?) chars>\)$")


@pytest.mark.parametrize(
    "action, expected",
    [
        (r'String("a\"b")', "String(<3 chars>)"),
        (r'String("a\\b")', "String(<3 chars>)"),
        (r'String("\\\"")', "String(<2 chars>)"),
        ('String("")', "String(<0 chars>)"),
        ('String("abc")', "String(<3 chars>)"),
    ],
)
def test_well_formed(action, expected):
    assert redact_action(action) == expected


@pytest.mark.parametrize(
    "action",
    [
        'String("abc',  # unterminated
        'String("abc\\")',  # body ends in escaped quote, never closed
        'String("abc\\',  # trailing lone backslash
        'String("a","b")',  # two arguments
        "String(abc)",  # unquoted
        'String("a")x',  # text after ")"
        'String("a") ',  # trailing space after ")"
        "String(",
    ],
)
def test_malformed_renders_unknown_length(action):
    assert redact_action(action) == "String(<? chars>)"


@pytest.mark.parametrize(
    "action",
    [
        'Strings("x")',
        "StringX(1)",
        "Enter()",
        "PF(3)",
        "PA(1)",
        "Clear()",
        "MoveCursor(1,2)",
        "Snap(Save)",
        "Connect(192.0.2.1:3270)",
        "Disconnect()",
        "Quit()",
        "ReadBuffer(Ascii)",
        "Ascii()",
        "Wait(8,Output)",
        "Wait(InputField)",
        "",
        "Str",
        # U+017F (long s) and U+212A (Kelvin) must not fold onto ASCII letters
        '\u017fTRING("x")',
        'String\u212a("x")',
        '\u017ftring("x")',
        'Str\u0131ng("x")',
    ],
)
def test_non_string_actions_unchanged(action):
    assert redact_action(action) == action


@pytest.mark.parametrize(
    "action, expected",
    [
        ('string("pw")', "String(<2 chars>)"),
        ('STRING("pw")', "String(<2 chars>)"),
        ('sTrInG("pw")', "String(<2 chars>)"),
        ('  String("pw")', "String(<2 chars>)"),
        ('String ("pw")', "String(<2 chars>)"),
        ('String\t( "pw" )', "String(<2 chars>)"),
        ("string(", "String(<? chars>)"),
    ],
)
def test_case_and_whitespace_variants_are_redacted(action, expected):
    assert redact_action(action) == expected


@pytest.mark.parametrize(
    "text",
    ["", "a", 'pw"\\x-unlikely', "\\", '"', "\u00e9\u4e2d\U0001f600", "x" * 3000],
)
def test_round_trip_with_escape(text):
    out = redact_action(f'String("{_escape_s3270_string(text)}")')
    assert out == f"String(<{len(text)} chars>)"
    assert _SHAPE.match(out)
    if text:
        assert text not in out or len(text) == 1 and text in "String(<chars>)0123456789?"


@pytest.mark.parametrize(
    "action",
    ['String("abc")', 'String("abc', 'string(', '  STRING ("a","b")', 'String("a")x'],
)
def test_string_results_match_shape(action):
    assert _SHAPE.match(redact_action(action))


def test_regex_whitespace_equals_str_isspace():
    pattern = re.compile(r"\s")
    for c in range(sys.maxunicode + 1):
        ch = chr(c)
        assert (pattern.fullmatch(ch) is not None) == ch.isspace(), hex(c)
