"""Coverage tests for the console error-code table (task 4.6).

The table is read from the installed package, and ``ERROR_CODES`` and
``HTTP_STATUS`` come from the production module, so a code added to the
publisher without an entry here fails.

Requirements: 8.1, 8.2, 8.3, 8.5, 8.7, 8.8
"""

from __future__ import annotations

import json
import re
from importlib import resources

import pytest

from greenscreen.publisher.calls import ERROR_CODES, HTTP_STATUS

PAGE_SIDE = {"no_response", "unreadable_reply", "unknown_code"}


def _read(name: str) -> str:
    return (
        resources.files("greenscreen.publisher.console")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def codes() -> dict:
    table = json.loads(_read("codes.json"))
    assert isinstance(table, dict)
    return table


def test_error_code_keys_equal_error_codes(codes):
    assert len(ERROR_CODES) == 22
    assert set(codes) - PAGE_SIDE == set(ERROR_CODES)


def test_status_equals_http_status(codes):
    for code in ERROR_CODES:
        assert codes[code]["status"] == HTTP_STATUS[code], code


def test_each_text_is_short_non_empty_string(codes):
    for key, entry in codes.items():
        text = entry["text"]
        assert isinstance(text, str), key
        assert 0 < len(text) <= 200, key


def test_busy_text_words(codes):
    text = codes["busy"]["text"].lower()
    assert "busy" in text
    assert "try again" in text


def test_unauthorized_text_has_key(codes):
    assert "key" in codes["unauthorized"]["text"].lower()


def test_page_side_keys_exist_and_are_not_error_codes(codes):
    for key in PAGE_SIDE:
        assert key in codes
        assert key not in ERROR_CODES
        assert codes[key]["status"] is None


def test_no_cancelled_key(codes):
    assert "cancelled" not in codes


def test_show_message_only_on_input_invalid(codes):
    assert codes["input_invalid"].get("show_message") is True
    for key, entry in codes.items():
        if key != "input_invalid":
            assert "show_message" not in entry, key


def test_console_js_holds_no_error_code_literal():
    source = _read("console.js")
    for code in sorted(ERROR_CODES):
        pattern = r"""(["'`])""" + re.escape(code) + r"""\1"""
        assert re.search(pattern, source) is None, code
