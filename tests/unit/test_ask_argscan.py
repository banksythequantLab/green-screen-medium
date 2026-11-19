"""``exceeds_depth``: the version-independent argument depth scan (Decision 33)."""
from __future__ import annotations

import time

import pytest
from hypothesis import given, settings, strategies as st

from greenscreen.publisher.ask.argscan import MAX_ARGUMENT_DEPTH, exceeds_depth


def test_the_limit_is_four():
    assert MAX_ARGUMENT_DEPTH == 4


@pytest.mark.parametrize("text, expected", [
    ('{"a":{"b":{"c":{"d":1}}}}', False),
    ('{"a":{"b":{"c":{"d":{"e":1}}}}}', True),
    ("[[[[1]]]]", False),
    ("[[[[[1]]]]]", True),
    ('{"a":[{"b":[1]}]}', False),
    ('{"a":[{"b":[{"c":1}]}]}', True),
    ("[{" * 2 + "1" + "}]" * 2, False),
    ("[{" * 3, True),
])
def test_depth_four_is_false_and_five_is_true(text, expected):
    assert exceeds_depth(text, 4) is expected


def test_brackets_inside_strings_do_not_count():
    assert exceeds_depth('{"a": "[[[[[[["}', 4) is False


def test_an_escaped_quote_does_not_end_a_string():
    assert exceeds_depth(r'{"a": "\"[[[[[["}', 4) is False


def test_an_escaped_backslash_before_a_quote_ends_the_string():
    assert exceeds_depth(r'{"a": "\\"}' + "[[[[[", 4) is True


def test_a_hundred_thousand_open_brackets_is_true_and_fast():
    start = time.perf_counter()
    assert exceeds_depth("[" * 100000, 4) is True
    assert time.perf_counter() - start < 1.0


def test_a_hundred_thousand_characters_of_shallow_text_is_false_and_fast():
    text = "[" + "1," * 49998 + "1]"
    assert len(text) >= 99990
    start = time.perf_counter()
    assert exceeds_depth(text, 4) is False
    assert time.perf_counter() - start < 1.0


def test_the_recursion_fixture_is_too_deep_without_a_parser():
    assert exceeds_depth("[" * 2000 + "]" * 2000, 4) is True


@pytest.mark.parametrize("text", ["}}}}}{{{{", '{"a": }', '{"a": "unterminated [[[[[[[[', ""])
def test_unbalanced_or_unterminated_text_that_never_exceeds_the_limit_is_false(text):
    assert exceeds_depth(text, 4) is False


def test_closing_brackets_at_depth_zero_do_not_make_the_depth_negative():
    assert exceeds_depth("]]]]" + "[[[[", 4) is False
    assert exceeds_depth("]]]]" + "[[[[[", 4) is True


@settings(max_examples=200, deadline=None)
@given(st.text(alphabet=list('{}[]"\\ab:,1 '), max_size=300), st.integers(min_value=0, max_value=6))
def test_it_never_raises(text, limit):
    assert exceeds_depth(text, limit) in (True, False)
