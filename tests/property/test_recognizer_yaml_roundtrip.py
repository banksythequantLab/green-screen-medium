"""Property test for the signature YAML round trip."""
from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.signature import (
    BeforeCursorMatcher,
    CursorFieldMatcher,
    FieldLayoutMatcher,
    LastRowMatcher,
    RegionRegexMatcher,
    RowContainsMatcher,
    ScreenSignature,
    TextAtMatcher,
    VolatileRegion,
)

# All code points except surrogates, plus edge strings that YAML scalars treat specially.
_ANY_CHAR = st.characters(blacklist_categories=("Cs",))
_EDGE = st.sampled_from(["\x85", " ", "''"])


def _text(min_size: int, max_size: int) -> st.SearchStrategy[str]:
    body = st.text(alphabet=_ANY_CHAR, min_size=min_size, max_size=max_size)
    if min_size <= 1:
        return st.one_of(body, _EDGE)
    return body


_NONEMPTY = _text(1, 40)
_DESCRIPTION = _text(0, 100)
_NAME = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=64)
_VOLATILE = st.builds(
    VolatileRegion,
    row=st.integers(100, 120),
    col=st.integers(0, 100),
    length=st.integers(1, 50),
)
_POSITIONS = st.lists(st.tuples(st.integers(0, 255), st.integers(0, 255)), max_size=5)
_ROW = st.integers(0, 23)
_COL = st.integers(0, 100)


@st.composite
def _matcher(draw):
    kind = draw(st.integers(0, 6))
    if kind == 0:
        return TextAtMatcher(row=draw(_ROW), col=draw(_COL), text=draw(_NONEMPTY))
    if kind == 1:
        return RowContainsMatcher(row=draw(_ROW), text=draw(_NONEMPTY))
    if kind == 2:
        ps = tuple(draw(_POSITIONS))
        return FieldLayoutMatcher(count=len(ps), positions=ps)
    if kind == 3:
        return CursorFieldMatcher(row=draw(_ROW), col=draw(_COL), hidden=draw(st.booleans()))
    if kind == 4:
        return RegionRegexMatcher(
            row=draw(_ROW),
            col=draw(_COL),
            length=draw(st.integers(1, 50)),
            pattern=re.escape(draw(_NONEMPTY)),
        )
    if kind == 5:
        return LastRowMatcher(text=draw(_NONEMPTY))
    return BeforeCursorMatcher(text=draw(_NONEMPTY))


@st.composite
def _signature(draw):
    ms = draw(st.lists(_matcher(), min_size=1, max_size=8))
    # Volatile rows 100..120 never share a row with a matcher rectangle (rows 0..23).
    vs = draw(st.lists(_VOLATILE, max_size=3))
    name = draw(_NAME)
    description = draw(_DESCRIPTION)
    return ScreenSignature(name=name, matchers=tuple(ms), volatile=tuple(vs), description=description)


# Feature: screen-recognizer, Property 6: YAML round trip and determinism
# **Validates: Requirements 4.1, 4.3, 4.5, 4.11, 11.5**
@settings(max_examples=200, deadline=None)
@given(sig=_signature())
def test_yaml_round_trip_and_determinism(sig):
    text = sig.to_yaml()
    assert text.startswith("version: 1")
    assert sig.to_yaml() == text
    assert ScreenSignature.from_yaml(text) == sig
