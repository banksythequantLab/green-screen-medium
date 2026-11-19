"""codes.json holds the publisher codes, the Ask codes and the page-side keys (spec ask, 4.1).

Requirements: 11.4, 11.5, 11.6
"""

from __future__ import annotations

import json
from importlib import resources

from greenscreen.publisher.ask.codes import ASK_ERROR_CODES, ASK_HTTP_STATUS, REJECT_REASONS
from greenscreen.publisher.calls import ERROR_CODES, HTTP_STATUS

PAGE_SIDE = {"no_response", "unreadable_reply", "unknown_code", "ask_unavailable", "ask_reply_unreadable"}


def _table() -> dict:
    text = resources.files("greenscreen.publisher.console").joinpath("codes.json").read_text(encoding="utf-8")
    return json.loads(text)


def test_exact_key_set() -> None:
    assert len(ERROR_CODES) == 22 and len(ASK_ERROR_CODES) == 9
    assert set(_table()) == set(ERROR_CODES) | set(ASK_ERROR_CODES) | PAGE_SIDE


def test_status_matches_tables_and_page_side_is_null() -> None:
    table = _table()
    for code in ERROR_CODES:
        assert table[code]["status"] == HTTP_STATUS[code], code
    for code in ASK_ERROR_CODES:
        assert table[code]["status"] == ASK_HTTP_STATUS[code], code
    for key in PAGE_SIDE:
        assert table[key]["status"] is None, key


def test_texts_are_non_empty_and_short() -> None:
    for key, entry in _table().items():
        assert isinstance(entry["text"], str) and 0 < len(entry["text"]) <= 200, key


def test_no_cancelled_key_and_no_reject_reason_key() -> None:
    table = _table()
    assert "cancelled" not in table
    for reason in set(REJECT_REASONS) - {"tool_limit"}:  # tool_limit is also an Ask code
        assert reason not in table, reason


def test_daily_limit_text_names_reset_time() -> None:
    text = _table()["daily_limit"]["text"]
    assert "00:00 UTC" in text and "restart" in text


def test_model_unreachable_text_keeps_timeout_sentence() -> None:
    table = _table()
    text = table["model_unreachable"]["text"]
    assert text == "The AI service could not be reached, or it took too long to answer. Try again in a minute."
    assert len(text) <= 200
    assert not any(ch.isdigit() for ch in text)  # no seconds quoted
    assert "model_timeout" not in table and "model_timeout" not in ASK_ERROR_CODES
