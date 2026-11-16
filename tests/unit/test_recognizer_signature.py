"""Unit tests for ScreenSignature construction-time validation."""

from __future__ import annotations

import pytest

from greenscreen.recognizer.errors import SignatureError
from greenscreen.recognizer.signature import (
    MATCHER_KINDS,
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

OK = TextAtMatcher(0, 0, "LOGON")


def sig(matchers=(OK,), volatile=(), name="ok", description=""):
    return ScreenSignature(name, tuple(matchers), tuple(volatile), description)


def test_valid_signature_builds():
    assert sig().name == "ok"


def test_matcher_kinds():
    assert set(MATCHER_KINDS) == {
        "text_at",
        "row_contains",
        "field_layout",
        "cursor_field",
        "region_regex",
        "last_row",
        "before_cursor",
    }
    assert len(MATCHER_KINDS) == 7


def test_equal_signatures_equal_and_hashable():
    a = sig([OK, RegionRegexMatcher(1, 0, 5, r"\d+")], [VolatileRegion(2, 0, 3)])
    b = sig([OK, RegionRegexMatcher(1, 0, 5, r"\d+")], [VolatileRegion(2, 0, 3)])
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    assert a != sig([OK])


def test_zero_matchers():
    with pytest.raises(SignatureError):
        sig(matchers=())


def test_too_many_matchers():
    sig([RowContainsMatcher(0, "x")] * 50)
    with pytest.raises(SignatureError):
        sig([RowContainsMatcher(0, "x")] * 51)


def test_too_many_regions():
    sig(volatile=[VolatileRegion(5, 0, 1)] * 50)
    with pytest.raises(SignatureError):
        sig(volatile=[VolatileRegion(5, 0, 1)] * 51)


@pytest.mark.parametrize("name", ["", "a" * 65, "Upper", "ok\n", "has space"])
def test_bad_name(name):
    with pytest.raises(SignatureError):
        sig(name=name)


def test_name_boundaries_ok():
    sig(name="a" * 64)
    sig(name="a-b_9")


def test_description_too_long():
    sig(description="d" * 500)
    with pytest.raises(SignatureError):
        sig(description="d" * 501)


@pytest.mark.parametrize("bad", [256, -1, True])
def test_bad_row(bad):
    with pytest.raises(SignatureError):
        sig([TextAtMatcher(bad, 0, "x")])
    with pytest.raises(SignatureError):
        sig([RowContainsMatcher(bad, "x")])
    with pytest.raises(SignatureError):
        sig([CursorFieldMatcher(bad, 0, False)])
    with pytest.raises(SignatureError):
        sig(volatile=[VolatileRegion(bad, 0, 1)])


@pytest.mark.parametrize("bad", [256, -1, False])
def test_bad_col(bad):
    with pytest.raises(SignatureError):
        sig([TextAtMatcher(0, bad, "x")])
    with pytest.raises(SignatureError):
        sig([CursorFieldMatcher(0, bad, True)])
    with pytest.raises(SignatureError):
        sig([RegionRegexMatcher(0, bad, 1, "a")])
    with pytest.raises(SignatureError):
        sig(volatile=[VolatileRegion(0, bad, 1)])


@pytest.mark.parametrize("bad", [256, -1, True])
def test_bad_field_layout_position(bad):
    with pytest.raises(SignatureError):
        sig([FieldLayoutMatcher(1, ((bad, 0),))])
    with pytest.raises(SignatureError):
        sig([FieldLayoutMatcher(1, ((0, bad),))])


@pytest.mark.parametrize("length", [0, -3])
def test_length_below_one(length):
    with pytest.raises(SignatureError):
        sig([RegionRegexMatcher(0, 0, length, "a")])
    with pytest.raises(SignatureError):
        sig(volatile=[VolatileRegion(5, 0, length)])


def test_last_column_above_255():
    sig([RegionRegexMatcher(0, 250, 6, "a")])
    with pytest.raises(SignatureError):
        sig([RegionRegexMatcher(0, 250, 7, "a")])
    with pytest.raises(SignatureError):
        sig(volatile=[VolatileRegion(5, 250, 7)])
    with pytest.raises(SignatureError):
        sig([TextAtMatcher(0, 254, "abc")])


def test_invalid_regex():
    with pytest.raises(SignatureError):
        sig([RegionRegexMatcher(0, 0, 5, "(unclosed")])


def test_over_long_regex():
    sig([RegionRegexMatcher(0, 0, 5, "a" * 200)])
    with pytest.raises(SignatureError):
        sig([RegionRegexMatcher(0, 0, 5, "a" * 201)])


def test_matcher_region_overlap():
    with pytest.raises(SignatureError):
        sig([TextAtMatcher(3, 10, "HELLO")], [VolatileRegion(3, 14, 4)])
    with pytest.raises(SignatureError):
        sig([RegionRegexMatcher(3, 10, 5, "a")], [VolatileRegion(3, 5, 6)])


def test_adjacent_or_other_row_is_not_overlap():
    sig([TextAtMatcher(3, 10, "HELLO")], [VolatileRegion(3, 15, 4)])
    sig([TextAtMatcher(3, 10, "HELLO")], [VolatileRegion(4, 10, 5)])


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TextAtMatcher(0, 0, ""),
        lambda: RowContainsMatcher(0, ""),
        lambda: LastRowMatcher(""),
        lambda: BeforeCursorMatcher(""),
    ],
)
def test_empty_text_for_each_kind(factory):
    with pytest.raises(SignatureError):
        sig([factory()])


def test_field_layout_count_mismatch():
    sig([FieldLayoutMatcher(2, ((1, 1), (2, 2)))])
    with pytest.raises(SignatureError):
        sig([FieldLayoutMatcher(3, ((1, 1), (2, 2)))])
    with pytest.raises(SignatureError):
        sig([FieldLayoutMatcher(0, ((1, 1),))])


SECRET = "S3cr3tT3xt"


@pytest.mark.parametrize(
    "build",
    [
        lambda: sig([TextAtMatcher(0, 254, SECRET)]),
        lambda: sig([TextAtMatcher(3, 10, SECRET)], [VolatileRegion(3, 10, 4)]),
        lambda: sig([RegionRegexMatcher(0, 0, 5, "(" + SECRET)]),
        lambda: sig([RegionRegexMatcher(0, 0, 5, SECRET * 40)]),
        lambda: sig([RegionRegexMatcher(0, 300, 5, SECRET)]),
        lambda: sig([RowContainsMatcher(999, SECRET)]),
        lambda: sig([LastRowMatcher(SECRET), RowContainsMatcher(-1, SECRET)]),
        lambda: sig([BeforeCursorMatcher(SECRET)] * 51),
    ],
)
def test_messages_never_contain_text_or_pattern(build):
    with pytest.raises(SignatureError) as ei:
        build()
    assert SECRET not in str(ei.value)
