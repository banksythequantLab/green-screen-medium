"""Property test: recognition outcomes and messages (Property 16)."""
from __future__ import annotations

import copy
import dataclasses
import re

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.errors import (
    AmbiguousScreenError,
    SignatureError,
    UnknownScreenError,
)
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.signature import ScreenSignature, TextAtMatcher
from greenscreen.recognizer.suggest import suggest_signature
from greenscreen.recognizer.summary import build_summary
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import small_screens

_NAME = st.text(alphabet="abcdefghij0123456789-_", min_size=1, max_size=10)

_UNKNOWN_MESSAGE = re.compile(
    r"no signature matches: \d+x\d+ screen, cursor \(\d+, \d+\), "
    r"\d+ fields \(\d+ unprotected, \d+ hidden\), \d+ signatures evaluated"
)


def _non_matching(name: str, screen) -> ScreenSignature:
    """A signature that can never match: its text_at row is below the screen."""
    return ScreenSignature(
        name=name,
        matchers=(TextAtMatcher(row=screen.rows, col=0, text="X"),),
    )


# Feature: screen-recognizer, Property 16: Recognition outcomes and messages
@settings(max_examples=150, deadline=None)
@given(
    screen=small_screens(allow_hidden=True),
    names=st.lists(_NAME, min_size=1, max_size=8, unique=True),
    n_match=st.integers(0, 4),
    order_seed=st.randoms(use_true_random=False),
)
def test_recognition_outcomes_and_messages(screen, names, n_match, order_seed):
    """**Validates: Requirements 5.3, 5.4, 5.5, 5.8, 6.2, 6.6, 6.8**"""
    try:
        base = suggest_signature(screen, name="base")
    except SignatureError:
        assume(False)
    n_match = min(n_match, len(names))
    matching_names = names[:n_match]
    other_names = names[n_match:]
    sigs = [dataclasses.replace(base, name=n) for n in matching_names]
    sigs += [_non_matching(n, screen) for n in other_names]
    order_seed.shuffle(sigs)

    screen_before = copy.deepcopy(screen)
    sigs_before = copy.deepcopy(sigs)

    if n_match == 1:
        assert recognize(screen, sigs) == matching_names[0]
    elif n_match == 0:
        with pytest.raises(UnknownScreenError) as info:
            recognize(screen, sigs)
        exc = info.value
        assert exc.summary == build_summary(ScreenView(screen_before))
        message = str(exc)
        assert re.fullmatch(r"[^\n]*", message)
        assert _UNKNOWN_MESSAGE.fullmatch(message)
        assert f"{len(sigs)} signatures evaluated" in message
    else:
        with pytest.raises(AmbiguousScreenError) as info:
            recognize(screen, sigs)
        exc = info.value
        assert list(exc.names) == sorted(matching_names)
        assert len(set(exc.names)) == len(exc.names)
        message = str(exc)
        assert "\n" not in message
        assert message == f"{n_match} signatures match: " + ", ".join(sorted(matching_names))

    # Neither argument changed, whether recognize returned or raised.
    assert screen == screen_before
    assert sigs == sigs_before

    # Duplicate names raise SignatureError naming each duplicated name.
    dup_names = sorted(set(names[:2]))
    dup_sigs = sigs + [_non_matching(n, screen) for n in dup_names]
    with pytest.raises(SignatureError) as dup_info:
        recognize(screen, dup_sigs)
    for n in dup_names:
        assert n in str(dup_info.value)
    assert screen == screen_before
