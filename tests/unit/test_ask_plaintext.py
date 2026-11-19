"""plain_answer (spec ask, task 10.3; Requirement 18, criteria 4 to 8). Pure, no host, no model."""
from __future__ import annotations

import time

import pytest
from hypothesis import given, settings, strategies as st

from greenscreen.publisher.ask.plaintext import plain_answer

CASES = [
    ("You are logged on as user **HERC01** using a **3277** terminal.",
     "You are logged on as user HERC01 using a 3277 terminal."),
    ("**warning", "**warning"),
    ("warning**", "warning**"),
    ("snake_case_name", "snake_case_name"),
    ("tk5_logon", "tk5_logon"),
    ("a * b * c", "a * b * c"),
    ("2*3*4", "2*3*4"),
    ("* item one", "* item one"),
    ("* item *two*", "* item two"),
    ("__init__", "init"),
    ("__x__", "x"),
    ("a _x_ b", "a x b"),
    ("_x_", "x"),
    ("_x_ end", "x end"),
    ("start _x_", "start x"),
    ("a_x_b", "a_x_b"),
    ("*x*", "x"),
    ("`a_b`", "a_b"),
    ("```", "```"),
    ("****", "****"),
    ("__", "__"),
    ("` `", "` `"),
    ("`", "`"),
    ("**a *b* c**", "a b c"),
    ("*a **b** c*", "a b c"),
    ("**a *b** c*", "a b c"),
    ("`**x**`", "x"),
    ("***x***", "***x***"),
    ("**Name:** value", "Name: value"),
    ("(**x**)", "(x)"),
    ("**x**s", "**x**s"),
    ("**a\nb**", "**a\nb**"),
    ("", ""),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_exact_outputs(text, expected):
    assert plain_answer(text) == expected


def test_a_pair_of_200_characters_is_stripped_and_of_201_is_left():
    assert plain_answer("**" + "a" * 200 + "**") == "a" * 200
    assert plain_answer("**" + "a" * 201 + "**") == "**" + "a" * 201 + "**"
    assert plain_answer("`" + "a" * 200 + "`") == "a" * 200
    assert plain_answer("`" + "a" * 201 + "`") == "`" + "a" * 201 + "`"


MARKERS = "*_`"
ALPHABET = st.sampled_from(list("*_` abXY09\n"))


@settings(max_examples=300, deadline=None)
@given(st.text(alphabet=ALPHABET, max_size=300))
def test_invariants(text):
    out = plain_answer(text)
    assert len(out) <= len(text)
    assert set(out) <= set(text)
    if not any(c in text for c in MARKERS):
        assert out == text


@pytest.mark.parametrize("unit", ["*a ", "_a ", "` ", "*", "_", "**a ", "__a ", "`a ", "*_` "])
def test_adversarial_long_input_is_processed_in_linear_time(unit):
    text = (unit * (200_000 // len(unit) + 1))[:200_000]
    started = time.perf_counter()
    out = plain_answer(text)
    elapsed = time.perf_counter() - started
    print(f"plain_answer {unit!r} x 200000 chars: {elapsed:.3f}s")
    assert elapsed < 5.0
    assert len(out) <= len(text)


@pytest.mark.parametrize("unit", ["*", "_", "` ", "*_` ", "*a "])
def test_100000_character_mixes_stay_under_a_time_bound(unit):
    text = (unit * (100_000 // len(unit) + 1))[:100_000]
    started = time.perf_counter()
    plain_answer(text)
    assert time.perf_counter() - started < 5.0
