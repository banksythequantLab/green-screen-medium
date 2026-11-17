"""Unit tests for connector._status_for_log (tn3270-connector 12.32, 12.33)."""
from __future__ import annotations

import pytest

from greenscreen.connector.connector import _status_for_log

GOOD = "U F U C(192.168.68.72) I 2 24 80 22 11 0x0 0.000"


def _unparsed(line: str) -> str:
    return f"<unparsed status, {len(line)} chars>"


def test_parsed_status_passes_through():
    assert _status_for_log(GOOD) == GOOD


@pytest.mark.parametrize(
    "line",
    [
        "U F U C(h) I 2 24 80 22 11 0x0",  # 11 tokens
        GOOD + " extra",  # 13 tokens
        "U F U C(h) I 2 ab 80 22 11 0x0 0.000",  # field 7 not digits
        "U F U C(h) I 2 24 80 -1 11 0x0 0.000",  # field 9 negative
        "",
        "SECRETDATA " * 50,
    ],
)
def test_unexpected_line_is_replaced_by_length_only(line):
    result = _status_for_log(line)
    assert result == _unparsed(line)
    for word in set(line.split()):
        if len(word) > 3:
            assert word not in result
