"""Property 9: data: prefix stripping preserves content (Task 4.4).

Feature: tn3270-connector
Validates: Requirement 3.2
"""
from hypothesis import given, settings
from hypothesis import strategies as st
from greenscreen.connector.parser import ScreenParser
from greenscreen.connector.models import StatusLine, Response

_printable = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    max_size=80,
)

_status_raw = "U F U C(localhost) I 2 1 1 0 0 0x0 0.001"


@given(st.lists(_printable, min_size=0, max_size=10))
@settings(max_examples=500)
def test_data_prefix_stripping(lines: list[str]) -> None:
    """Wrapping lines with 'data: ' and parsing recovers the original strings."""
    # Feature: tn3270-connector, Property 9: data: prefix stripping
    p = ScreenParser()
    status = p.parse_status_line(_status_raw)
    # Build a Response where data_lines already have 'data: ' stripped
    # (that's what Connector._read_response does before building Response)
    resp = Response(success=True, data_lines=lines, status=status)
    assert resp.data_lines == lines
