"""Property test for ScreenSignature construction validation."""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer.errors import SignatureError
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

# ---------------------------------------------------------------- oracle


def _ok_int(v, lo=0, hi=255):
    return type(v) is int and lo <= v <= hi


def _ok_rect(row, col, length):
    return (
        _ok_int(row)
        and _ok_int(col)
        and type(length) is int
        and length >= 1
        and col + length - 1 <= 255
    )


def _oracle_matcher(m):
    """Return (valid, rect) where rect is (row, col, length) for overlap checks."""
    if isinstance(m, TextAtMatcher):
        return _ok_rect(m.row, m.col, len(m.text)), (m.row, m.col, len(m.text))
    if isinstance(m, RowContainsMatcher):
        return _ok_int(m.row), None
    if isinstance(m, FieldLayoutMatcher):
        ok = m.count == len(m.positions) and all(
            _ok_int(r) and _ok_int(c) for r, c in m.positions
        )
        return ok, None
    if isinstance(m, CursorFieldMatcher):
        return _ok_int(m.row) and _ok_int(m.col) and type(m.hidden) is bool, None
    if isinstance(m, RegionRegexMatcher):
        ok = _ok_rect(m.row, m.col, m.length) and len(m.pattern) <= 200
        if ok:
            try:
                re.compile(m.pattern)
            except re.error:
                ok = False
        return ok, (m.row, m.col, m.length)
    return True, None  # last_row / before_cursor with non-empty text


def _oracle_valid(name, description, matchers, volatile):
    if not re.fullmatch(r"[a-z0-9_-]{1,64}", name):
        return False
    if len(description) > 500:
        return False
    if not 1 <= len(matchers) <= 50 or len(volatile) > 50:
        return False
    rects = []
    for m in matchers:
        ok, rect = _oracle_matcher(m)
        if not ok:
            return False
        if rect is not None:
            rects.append(rect)
    for v in volatile:
        if not _ok_rect(v.row, v.col, v.length):
            return False
    for v in volatile:
        for row, col, length in rects:
            if row == v.row and col < v.col + v.length and v.col < col + length:
                return False
    return True


# ------------------------------------------------------------ strategies

_BAD_VALUES = [-1, 256, 1000, True, False, None, "1", 1.0]


def _coord(noisy):
    good = st.sampled_from([0, 1, 40, 254, 255])
    if not noisy:
        return good
    return st.one_of(good, st.sampled_from(_BAD_VALUES))


def _length(noisy):
    good = st.sampled_from([1, 2, 5, 80, 255, 256])
    if not noisy:
        return st.sampled_from([1, 2, 5])
    return st.one_of(good, st.sampled_from([0, -1, True, False, None, "1", 1.0]))


_TEXT = st.sampled_from(["A", "AB", "HELLO", " READY", "x" * 30, "y" * 255, "z" * 256])
_PATTERN = st.sampled_from(
    ["a", r"\d+", "(", "[", "a{2,1}", "*a", "a" * 200, "a" * 201, "(" + "a" * 199 + ")", ""]
)


@st.composite
def _matcher(draw, noisy):
    kind = draw(st.integers(0, 6))
    if kind == 0:
        return TextAtMatcher(draw(_coord(noisy)), draw(_coord(noisy)), draw(_TEXT))
    if kind == 1:
        return RowContainsMatcher(draw(_coord(noisy)), draw(_TEXT))
    if kind == 2:
        positions = tuple(
            (draw(_coord(noisy)), draw(_coord(noisy)))
            for _ in range(draw(st.integers(0, 3)))
        )
        count = len(positions)
        if noisy and draw(st.booleans()):
            count = draw(st.integers(0, 4))
        return FieldLayoutMatcher(count, positions)
    if kind == 3:
        hidden = draw(st.sampled_from([True, False] + ([None, 0, 1] if noisy else [])))
        return CursorFieldMatcher(draw(_coord(noisy)), draw(_coord(noisy)), hidden)
    if kind == 4:
        pattern = draw(_PATTERN if noisy else st.sampled_from(["a", r"\d+", ""]))
        return RegionRegexMatcher(
            draw(_coord(noisy)), draw(_coord(noisy)), draw(_length(noisy)), pattern
        )
    if kind == 5:
        return LastRowMatcher(draw(_TEXT))
    return BeforeCursorMatcher(draw(_TEXT))


@st.composite
def _inputs(draw):
    noisy = draw(st.booleans())
    if noisy:
        name = draw(
            st.one_of(
                st.text(alphabet="abcxyzABC019_- .", max_size=66),
                st.sampled_from(["", "a", "a" * 64, "a" * 65, "Abc", "a b", "a.b", "é"]),
            )
        )
        description = "d" * draw(st.sampled_from([0, 1, 499, 500, 501, 502]))
        n_matchers = draw(st.sampled_from([0, 1, 2, 3, 50, 51]))
        n_volatile = draw(st.sampled_from([0, 1, 2, 3, 50, 51]))
    else:
        name = draw(
            st.one_of(
                st.text(alphabet="abcxyz019_-", min_size=1, max_size=64),
                st.sampled_from(["a", "a" * 64]),
            )
        )
        description = "d" * draw(st.sampled_from([0, 1, 499, 500]))
        n_matchers = draw(st.sampled_from([1, 2, 3, 50]))
        n_volatile = draw(st.sampled_from([0, 1, 2, 3, 50]))
    matchers = tuple(draw(st.lists(_matcher(noisy), min_size=n_matchers, max_size=n_matchers)))
    volatile = tuple(
        VolatileRegion(draw(_coord(noisy)), draw(_coord(noisy)), draw(_length(noisy)))
        for _ in range(n_volatile)
    )
    return name, description, matchers, volatile


# -------------------------------------------------------------- property


# Feature: screen-recognizer, Property 14: Signature validation
# **Validates: Requirements 1.1, 1.9, 1.10, 1.11, 1.12, 1.13**
@settings(max_examples=300, deadline=None)
@given(_inputs())
def test_signature_validation(data):
    name, description, matchers, volatile = data
    expected = _oracle_valid(name, description, matchers, volatile)
    try:
        sig = ScreenSignature(
            name=name, matchers=matchers, volatile=volatile, description=description
        )
    except SignatureError:
        assert not expected
    else:
        assert expected
        assert sig.name == name
        assert len(sig.matchers) == len(matchers)
