"""Unit tests for ``recognize``.

Covers requirements 5.1-5.6, 5.9, 5.10, 6.1, 6.6, 10.5, 10.6, 10.9.
"""
from __future__ import annotations

import builtins
import re
import socket
import subprocess
import time

import pytest

from greenscreen.connector.exceptions import ConnectorError
from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.errors import (
    AmbiguousScreenError,
    RecognizerError,
    SignatureError,
    UnknownScreenError,
)
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.signature import (
    FieldLayoutMatcher,
    RowContainsMatcher,
    ScreenSignature,
    TextAtMatcher,
)
from tests.screen_support import load_capture_screen, make_screen

SECRET = "ZQXSECRETROW"


def _screen():
    return make_screen(5, 20, text={(0, 0): "HELLO", (1, 0): SECRET})


def _hello(name: str) -> ScreenSignature:
    return ScreenSignature(name=name, matchers=(TextAtMatcher(0, 0, "HELLO"),))


def _nope(name: str) -> ScreenSignature:
    return ScreenSignature(name=name, matchers=(TextAtMatcher(0, 0, "NOPE"),))


def test_single_match_returns_name():
    assert recognize(_screen(), [_nope("a"), _hello("b")]) == "b"


def test_empty_list_raises_unknown():
    with pytest.raises(UnknownScreenError) as ei:
        recognize(_screen(), [])
    assert "0 signatures evaluated" in str(ei.value)


def test_no_match_raises_unknown():
    with pytest.raises(UnknownScreenError):
        recognize(_screen(), [_nope("a")])


def test_ambiguous_names_sorted_and_exact_without_screen_text():
    sigs = [_hello("zeta"), _nope("other"), _hello("alpha"), _hello("mid")]
    with pytest.raises(AmbiguousScreenError) as ei:
        recognize(_screen(), sigs)
    exc = ei.value
    assert exc.names == ("alpha", "mid", "zeta")
    message = str(exc)
    for name in exc.names:
        assert name in message
    assert "other" not in message
    assert "HELLO" not in message and SECRET not in message
    assert SECRET not in repr(exc) and "HELLO" not in repr(exc)


def test_duplicate_names_raise_before_any_matcher_runs():
    # A screen that would fail ScreenView construction if reached.
    class BadScreen:
        pass

    sigs = [_hello("dup"), _nope("dup"), _hello("one"), _nope("one"), _hello("ok")]
    with pytest.raises(SignatureError) as ei:
        recognize(BadScreen(), sigs)  # type: ignore[arg-type]
    assert "dup" in str(ei.value) and "one" in str(ei.value)
    assert "ok" not in str(ei.value).split(":", 1)[1]


def test_non_signature_element_raises_type_error():
    with pytest.raises(TypeError):
        recognize(_screen(), [_hello("a"), "b"])  # type: ignore[list-item]


def test_iterator_consumed_once_and_same_result():
    sigs = [_nope("a"), _hello("b")]
    it = iter(sigs)
    assert recognize(_screen(), it) == "b"
    assert list(it) == []
    assert recognize(_screen(), iter(sigs)) == recognize(_screen(), sigs)


def test_order_independence():
    sigs = [_hello("c"), _nope("a"), _hello("b"), _nope("d")]
    results = set()
    for ordering in (sigs, list(reversed(sigs)), sigs[2:] + sigs[:2]):
        with pytest.raises(AmbiguousScreenError) as ei:
            recognize(_screen(), ordering)
        results.add(ei.value.names)
    assert results == {("b", "c")}
    assert recognize(_screen(), list(reversed([_nope("a"), _hello("b")]))) == "b"


def test_unknown_for_ispf_without_ispf_signature_shows_option_prompt():
    screen = load_capture_screen("ispf-primary-menu")
    bundled = load_bundled_signatures()
    assert recognize(screen, bundled) == "ispf-primary-menu"
    reduced = [s for s in bundled if s.name != "ispf-primary-menu"]
    assert len(reduced) == 9
    with pytest.raises(UnknownScreenError) as ei:
        recognize(screen, reduced)
    text = ei.value.summary.to_text()
    assert "Option  ===>" in text
    assert len(text.split("\n")) == 24
    assert "*" not in text
    assert ei.value.summary.hidden_count == 0


def test_unknown_message_is_one_line_of_counts_and_cursor():
    screen = load_capture_screen("ispf-primary-menu")
    with pytest.raises(UnknownScreenError) as ei:
        recognize(screen, [_nope("a"), _nope("b")])
    message = str(ei.value)
    assert re.fullmatch(
        r"no signature matches: 24x80 screen, cursor \(\d+, \d+\), "
        r"\d+ fields \(\d+ unprotected, \d+ hidden\), 2 signatures evaluated",
        message,
    )
    assert "\n" not in message
    assert "ISPF" not in message and "Option" not in message
    assert ei.value.__cause__ is None and ei.value.__context__ is None


def test_recognizer_errors_are_not_connector_errors():
    for cls in (SignatureError, UnknownScreenError, AmbiguousScreenError):
        assert issubclass(cls, RecognizerError)
        assert not issubclass(cls, ConnectorError)
    assert not issubclass(RecognizerError, ConnectorError)


def test_recognize_does_no_network_subprocess_or_file_io(monkeypatch):
    bundled = load_bundled_signatures()  # load before open is patched
    screen = load_capture_screen("tk5-logon")
    calls: list[str] = []

    def fail(name):
        def _fail(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"{name} must not be used by recognize")

        return _fail

    class FailSocket:
        def __init__(self, *args, **kwargs):
            calls.append("socket")
            raise AssertionError("socket must not be used by recognize")

    class FailPopen:
        def __init__(self, *args, **kwargs):
            calls.append("Popen")
            raise AssertionError("Popen must not be used by recognize")

    monkeypatch.setattr(socket, "socket", FailSocket)
    monkeypatch.setattr(subprocess, "Popen", FailPopen)
    monkeypatch.setattr(builtins, "open", fail("open"))

    assert recognize(screen, bundled) == "tk5-logon"
    with pytest.raises(UnknownScreenError):
        recognize(screen, [_nope("x")])
    with pytest.raises(AmbiguousScreenError):
        recognize(screen, [*bundled, _always("always-a"), _always("always-b")])
    assert calls == []


def _always(name: str) -> ScreenSignature:
    # Matches any screen whose row 0 holds a space.
    return ScreenSignature(name=name, matchers=(RowContainsMatcher(0, " "),))


def test_benchmark_100_signatures_within_2_seconds():
    screen = make_screen(
        24, 80, text={(r, 0): f"ROW{r:02d} " + "ABCDEFGHIJ" * 7 for r in range(24)}
    )
    sigs = []
    for i in range(100):
        matchers = [
            TextAtMatcher(row=k % 24, col=0, text=f"ROW{k % 24:02d} ")
            for k in range(9)
        ]
        # The last matcher is unsatisfied for most signatures; a few match.
        matchers.append(
            RowContainsMatcher(row=23, text="ABCDEFGHIJ" if i % 50 == 0 else f"Q{i}")
        )
        sigs.append(ScreenSignature(name=f"sig-{i}", matchers=tuple(matchers)))
    start = time.perf_counter()
    with pytest.raises(AmbiguousScreenError) as ei:
        recognize(screen, sigs)
    elapsed = time.perf_counter() - start
    assert ei.value.names == ("sig-0", "sig-50")
    assert elapsed < 2.0
