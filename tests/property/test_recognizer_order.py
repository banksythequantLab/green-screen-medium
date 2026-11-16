"""Property 7: recognition ignores signature order and iterator form."""
from __future__ import annotations

import dataclasses

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.errors import (
    AmbiguousScreenError,
    SignatureError,
    UnknownScreenError,
)
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.suggest import suggest_signature
from tests.property._recognizer_strategies import signatures, small_screens


def _outcome(screen, sigs):
    try:
        return ("ok", recognize(screen, sigs))
    except AmbiguousScreenError as exc:
        return ("AmbiguousScreenError", tuple(sorted(exc.names)))
    except UnknownScreenError:
        return ("UnknownScreenError", None)


@st.composite
def _scenario(draw):
    screen = draw(small_screens(allow_hidden=True))
    try:
        base = suggest_signature(screen)
    except SignatureError:
        base = None
    n_copies = draw(st.integers(0, 10)) if base is not None else 0
    n_other = draw(st.integers(0, 10 - n_copies))
    sigs = [dataclasses.replace(base, name=f"copy-{i}") for i in range(n_copies)]
    for i in range(n_other):
        other = draw(signatures())
        sigs.append(dataclasses.replace(other, name=f"other-{i}"))
    perms = [draw(st.permutations(sigs)) for _ in range(3)]
    return screen, sigs, perms


# Feature: screen-recognizer, Property 7: Recognition ignores signature order and iterator form
@given(_scenario())
@settings(max_examples=150, deadline=None)
def test_recognition_ignores_order_and_iterator_form(scenario):
    screen, sigs, perms = scenario
    expected = _outcome(screen, list(sigs))
    for perm in perms:
        assert _outcome(screen, list(perm)) == expected
    assert _outcome(screen, iter(sigs)) == expected
    assert _outcome(screen, iter(perms[0])) == expected
