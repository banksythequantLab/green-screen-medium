"""Property 3: StatusLine serialize–parse round-trip (Task 4.2).

Feature: tn3270-connector
Validates: Requirements 9.3, 6.1, 6.2, 6.3, 6.4, 6.5
"""
from hypothesis import given, settings
from hypothesis import strategies as st
from greenscreen.connector.parser import ScreenParser

# Generate a single non-space printable ASCII token
_token = st.text(
    alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E),
    min_size=1,
    max_size=20,
)

# Exactly 12 tokens; force fields 7-10 (rows, cols, cursor_row, cursor_col) to be
# decimal integers so parsing succeeds
_int_token = st.integers(min_value=0, max_value=9999).map(str)


@st.composite
def _status_line_string(draw):
    tokens = [draw(_token) for _ in range(6)]
    tokens += [draw(_int_token) for _ in range(4)]  # fields 7-10
    tokens += [draw(_token) for _ in range(2)]
    return " ".join(tokens)


@given(_status_line_string())
@settings(max_examples=500)
def test_status_line_roundtrip(raw: str) -> None:
    """parse_status_line(raw).serialize() == raw for any valid 12-token string."""
    # Feature: tn3270-connector, Property 3: StatusLine serialize-parse round-trip
    p = ScreenParser()
    parsed = p.parse_status_line(raw)
    assert parsed.serialize() == raw
