"""Example buttons and whole-word hints of the console (spec polish, task 7.2; Requirements 9, 10).

The real ``/openapi.json`` of the six bundled Published_Tools goes through the real
``parseListing`` (extracted from ``console.js``) and the real ``askExamples`` under Node.
The button count is the item count: ``renderAsk`` creates one ``button`` per item, which a
static check pins. Keys and Bound_Values are generated at run time and never printed.
"""
from __future__ import annotations

import re

import pytest

from greenscreen.publisher.app import prepare
from tests.console_node_ask import call_one
from tests.console_node_extract import (
    console_source,
    function_source,
    needs_node,
    run_listing,
)
from tests.console_node import snippets_source
from tests.example_support import SIX, six_tool_document, six_tool_environment

pytestmark = needs_node

OFF = {"GS_ENABLE_ASK": "false"}
TWO = ("tk5-time", "tk5-job-status")
TWO_ENV = {"GS_ASK_FLOWS": ",".join(TWO)}
PRINTABLE = re.compile(r"^[\x20-\x7e]*$")


@pytest.fixture(scope="module")
def flows():
    return prepare(six_tool_environment()).registry


@pytest.fixture(scope="module")
def doc_off():
    return six_tool_document(OFF)[0]


@pytest.fixture(scope="module")
def doc_all():
    return six_tool_document()[0]


@pytest.fixture(scope="module")
def doc_two():
    return six_tool_document(TWO_ENV)[0]


def listing(documents, limit=12, max_question=500):
    return run_listing(documents, limit, max_question)


def synthetic(count: int) -> dict:
    paths = {}
    for i in range(count):
        paths[f"/flows/flow-{i:02d}"] = {
            "post": {"summary": f"Flow number {i}.", "x-ask-example": f"Question {i}?"}
        }
    return {"paths": paths}


# --- the three page cases (Requirement 9) ------------------------------------------


def test_ask_off_gives_zero_items_and_zero_buttons(doc_off):
    [result] = listing([doc_off])
    assert len(result["items"]) == 6  # the tools are listed
    assert all(item["example"] == "" for item in result["items"])
    assert result["examples"] == []


def test_ask_on_with_all_six_gives_six_buttons_in_listing_order(doc_all, flows):
    [result] = listing([doc_all])
    assert [item["name"] for item in result["items"]] == list(SIX)
    expected = [flows[name].flow.example for name in SIX]
    assert [item["example"] for item in result["items"]] == expected
    shown = result["examples"]
    assert [e["text"] for e in shown] == expected
    for entry in shown:
        assert entry["hint"] != ""
        assert len(entry["hint"]) <= 100
        assert PRINTABLE.match(entry["hint"])


def test_two_offered_flows_give_two_buttons(doc_two, flows):
    [result] = listing([doc_two])
    shown = result["examples"]
    assert [e["text"] for e in shown] == [flows[name].flow.example for name in TWO]
    by_name = {i["name"]: i["example"] for i in result["items"]}
    assert [n for n, e in by_name.items() if e] == ["tk5-time", "tk5-job-status"]


def test_render_ask_creates_one_button_per_item():
    body = function_source(console_source(), "renderAsk")
    assert body.count('el("button"') == 1
    assert "for (const item of askExamples(flows, ASK_EXAMPLE_MAX, askMax.maxQuestion))" in body
    assert body.index("for (const item of askExamples") < body.index('el("button"')


def test_click_handler_sets_field_updates_count_and_focuses():
    body = function_source(console_source(), "renderAsk")
    at_value = body.index("refs.askInput.value = item.text;")
    at_count = body.index("updateAskCount();", at_value)
    at_focus = body.index("refs.askInput.focus(", at_count)
    assert at_value < at_count < at_focus


# --- the cap (A18) -----------------------------------------------------------------


def test_the_constant_is_twelve():
    assert call_one("ASK_EXAMPLE_MAX") == 12


@pytest.mark.parametrize("limit", [12, 13])
def test_exactly_twelve_flows_give_twelve_items(limit):
    [result] = run_listing([synthetic(12)], limit, 500)
    assert len(result["examples"]) == 12


@pytest.mark.parametrize("limit", [12, 13, 99])
def test_thirteen_flows_give_twelve_items(limit):
    [result] = run_listing([synthetic(13)], limit, 500)
    assert len(result["examples"]) == 12
    assert result["examples"][-1]["text"] == "Question 11?"


def test_the_literal_three_no_longer_limits_examples():
    for text in (console_source(), snippets_source()):
        assert not re.search(r"askExamples\([^)]*\b3\b", text)
    assert not re.search(r"\b3\b", function_source(snippets_source(), "askExamples"))
    assert not re.search(r"\b3\b", function_source(console_source(), "renderAsk"))


# --- other examples ----------------------------------------------------------------


def test_a_small_question_limit_skips_long_examples(doc_all, flows):
    [result] = run_listing([doc_all], 12, 30)
    expected = [flows[n].flow.example for n in SIX if len(flows[n].flow.example) <= 30]
    assert len(expected) < 6
    assert [e["text"] for e in result["examples"]] == expected


def test_hint_of_each_flow_description_is_a_sentence_or_a_whole_word_cut(flows):
    descriptions = [flows[name].flow.description for name in SIX]
    hints = [call_one("hintText", d) for d in descriptions]
    for description, hint in zip(descriptions, hints):
        assert len(hint) <= 100
        assert PRINTABLE.match(hint)
        norm = re.sub(r" +", " ", re.sub(r"[^\x20-\x7e]", " ", description)).strip()
        if hint.endswith("..."):
            kept = hint[:-3]
            assert norm.startswith(kept)
            assert norm[len(kept)] in " .!?,;:"
        elif hint:
            assert norm.startswith(hint)
            assert hint[-1] in ".!?"


def test_hint_edge_cases():
    assert call_one("hintText", "x" * 300) == ""
    assert call_one("hintText", 5) == ""
    text = " ".join(["word"] * 24)  # 119 characters, no sentence end
    hint = call_one("hintText", text)
    assert hint.endswith("...")
    assert len(hint) <= 100
    assert text.startswith(hint[:-3])
    assert call_one("hintText", "Short one. Second sentence.") == "Short one."


# --- static: nothing about a Flow is in the page code ------------------------------


def test_page_code_names_no_flow_and_no_example_text(flows):
    for text in (console_source(), snippets_source()):
        for name in SIX:
            assert name not in text
        for name in SIX:
            assert flows[name].flow.example not in text
        assert not re.search(r"Run \S+ and tell me", text)
