"""Property 4: s3270 string escaping round-trip (Task 7.2).

Feature: tn3270-connector
Validates: Requirements 9.6, 3.6
"""
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.connector.parser import _escape_s3270_string, _unescape_s3270_string


@given(
    st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        max_size=3000,
    )
)
@settings(max_examples=500)
def test_escape_unescape_roundtrip(text: str) -> None:
    """unescape(escape(text)) == text for any printable ASCII string up to 3000 chars."""
    # Feature: tn3270-connector, Property 4: s3270 string escaping round-trip
    escaped = _escape_s3270_string(text)
    recovered = _unescape_s3270_string(escaped)
    assert recovered == text, (
        f"Round-trip failed.\n"
        f"Original: {text!r}\n"
        f"Escaped:  {escaped!r}\n"
        f"Recovered:{recovered!r}\n"
    )


@given(
    st.text(
        alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
        max_size=3000,
    )
)
@settings(max_examples=200)
def test_escaped_contains_no_bare_backslash_or_quote(text: str) -> None:
    """After escaping, every backslash and double-quote is preceded by a backslash."""
    escaped = _escape_s3270_string(text)
    i = 0
    while i < len(escaped):
        ch = escaped[i]
        if ch == "\\":
            # Must be followed by another char (the escaped character)
            assert i + 1 < len(escaped), f"Trailing backslash in {escaped!r}"
            i += 2
        else:
            # Non-backslash char must not be a bare double-quote
            # (a double-quote may only appear after a backslash)
            assert ch != '"', f"Bare double-quote at position {i} in {escaped!r}"
            i += 1


# Spot-check specific cases
import pytest

@pytest.mark.parametrize("original,expected_escaped", [
    ("hello", "hello"),
    ('say "hi"', r'say \"hi\"'),
    ("back\\slash", r"back\\slash"),
    ('"both\\', r'\"both\\'),
    ("", ""),
])
def test_escape_specific_cases(original: str, expected_escaped: str) -> None:
    assert _escape_s3270_string(original) == expected_escaped
