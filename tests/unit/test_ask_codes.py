"""The Ask error-code tables (spec ask, task 2.10; Requirement 11).

The expected values are spelled out here on purpose, so a change in ``codes.py`` is noticed.
No live host, no model, no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from greenscreen.publisher.ask import codes
from greenscreen.publisher.ask.codes import (
    ASK_ERROR_CODES,
    ASK_HTTP_STATUS,
    ASK_MESSAGES,
    REFUSAL_SENTENCE,
    REJECT_REASONS,
)
from greenscreen.publisher.calls import ERROR_CODES, HTTP_STATUS, MESSAGES
from tests.ask_support import no_network  # noqa: F401  (autouse)

EXPECTED_STATUS = {
    "question_invalid": 422,
    "daily_limit": 429,
    "tool_limit": 422,
    "turn_limit": 422,
    "ask_timeout": 504,
    "model_unreachable": 502,
    "model_refused": 502,
    "model_unusable": 502,
    "model_busy": 503,
}

EXPECTED_MESSAGES = {
    "question_invalid": "The question is not valid.",
    "daily_limit": (
        "The daily limit of questions has been reached. The count is kept in memory and "
        "resets at 00:00 UTC and when the server restarts."
    ),
    "tool_limit": "The question needed more tool calls than allowed.",
    "turn_limit": "The question needed more model turns than allowed.",
    "ask_timeout": (
        "The question ran out of time and was stopped before the next step could finish."
    ),
    "model_unreachable": "The language model could not be reached or did not answer in time.",
    "model_refused": "The language model refused the request.",
    "model_unusable": "The language model returned something that cannot be used.",
    "model_busy": "The language model is busy. Try again in a minute.",
}

EXPECTED_REJECT = {
    "unknown_tool": "That tool is not available.",
    "arguments_too_large": "The arguments are too long.",
    "arguments_not_json": "The arguments are not valid JSON.",
    "arguments_not_object": "The arguments must be a JSON object.",
    "arguments_too_deep": "The arguments are nested too deeply.",
    "unknown_argument": "The arguments contain a name that the tool does not accept.",
    "tool_limit": "The limit of tool calls for this question has been reached.",
    "not_enough_time": "There is not enough time left to run this tool.",
    "result_too_large": "The result of the tool was too large to show.",
}


def test_the_three_tables_have_equal_key_sets() -> None:
    assert set(ASK_ERROR_CODES) == set(ASK_HTTP_STATUS) == set(ASK_MESSAGES)
    assert len(ASK_ERROR_CODES) == 9
    assert set(ASK_ERROR_CODES) == set(EXPECTED_STATUS)


def test_ask_codes_are_disjoint_from_the_publisher_codes() -> None:
    assert not set(ASK_ERROR_CODES) & set(ERROR_CODES)
    assert not set(ASK_HTTP_STATUS) & set(HTTP_STATUS)
    assert not set(ASK_MESSAGES) & set(MESSAGES)
    assert len(ERROR_CODES) == 22  # the existing tables are untouched


def test_statuses_are_the_fixed_values() -> None:
    assert dict(ASK_HTTP_STATUS) == EXPECTED_STATUS


def test_messages_are_the_fixed_texts() -> None:
    assert dict(ASK_MESSAGES) == EXPECTED_MESSAGES


@pytest.mark.parametrize("code", sorted(EXPECTED_MESSAGES))
def test_each_message_is_one_plain_sentence_group_without_values(code: str) -> None:
    text = ASK_MESSAGES[code]
    assert text.isprintable() and text == text.strip()
    assert text.endswith(".")
    assert len(text) <= 200
    assert not any(ch in text for ch in "{}<>%$")


def test_reject_reasons_are_the_nine_fixed_texts() -> None:
    assert dict(REJECT_REASONS) == EXPECTED_REJECT
    assert all(text.isprintable() and len(text) <= 100 for text in REJECT_REASONS.values())


def test_reject_reasons_are_not_error_codes_except_the_one_shared_word() -> None:
    # ``tool_limit`` names both the end-of-question code and the rejected-call reason.
    shared = set(REJECT_REASONS) & set(ASK_ERROR_CODES)
    assert shared == {"tool_limit"}
    assert not set(REJECT_REASONS) & set(ERROR_CODES)


def test_the_module_exports_only_the_four_tables_and_the_refusal_sentence() -> None:
    public = {n for n in vars(codes) if not n.startswith("_") and n.isupper()}
    assert public == {"ASK_ERROR_CODES", "ASK_HTTP_STATUS", "ASK_MESSAGES", "REJECT_REASONS", "REFUSAL_SENTENCE"}


REFUSAL_LITERAL = "I can only answer questions about this mainframe, using its tools, and I cannot answer that."


def test_refusal_sentence_is_the_literal() -> None:
    assert REFUSAL_SENTENCE == REFUSAL_LITERAL


def test_the_refusal_sentence_text_is_in_codes_py_only() -> None:
    # After task 4.2 the page holds it as ASK_REFUSAL in snippets.js; that task tests it.
    root = Path(__file__).resolve().parents[2] / "greenscreen"
    holders = sorted(
        p.relative_to(root).as_posix() for p in root.rglob("*.py")
        if REFUSAL_LITERAL in p.read_text(encoding="utf-8")
    )
    assert holders == ["publisher/ask/codes.py"]
