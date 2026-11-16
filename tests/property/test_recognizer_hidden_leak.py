"""Property test: hidden content never leaks (screen-recognizer)."""
from __future__ import annotations

import dataclasses
import logging

import pytest
from hypothesis import assume, given, settings

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
from tests.property._recognizer_strategies import sentinel_screens


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.texts: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.texts.append(str(record.msg))
        try:
            self.texts.append(record.getMessage())
        except Exception:
            pass
        args = record.args
        if args:
            self.texts.append(repr(args))
            for a in args.values() if isinstance(args, dict) else args:
                self.texts.append(str(a))
                self.texts.append(repr(a))


def _exception_texts(exc: BaseException) -> list[str]:
    out = [str(exc), repr(exc), repr(exc.args)]
    out += [str(a) for a in exc.args]
    for value in vars(exc).values():
        out += [str(value), repr(value)]
    return out


# Feature: screen-recognizer, Property 4: Hidden content never appears in any output
# **Validates: Requirements 6.7, 7.1, 7.4, 9.11, 13.1, 11.4**
@settings(max_examples=100, deadline=None)
@given(pair=sentinel_screens())
def test_hidden_content_never_appears_in_any_output(pair):
    screen, sentinel = pair
    logger = logging.getLogger("greenscreen.recognizer")
    handler = _Collect()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        try:
            sig = suggest_signature(screen, name="base")
        except SignatureError:
            assume(False)
        outputs = [repr(sig), sig.to_yaml()]

        never = ScreenSignature(
            name="never",
            matchers=(TextAtMatcher(row=screen.rows, col=0, text="X"),),
        )
        with pytest.raises(UnknownScreenError) as unknown:
            recognize(screen, [never])
        outputs += _exception_texts(unknown.value)

        twin_a = dataclasses.replace(sig, name="twin-a")
        twin_b = dataclasses.replace(sig, name="twin-b")
        with pytest.raises(AmbiguousScreenError) as ambiguous:
            recognize(screen, [twin_a, twin_b, never])
        outputs += _exception_texts(ambiguous.value)

        summary = build_summary(ScreenView(screen))
        outputs += [summary.to_text(), repr(summary), repr(summary.to_dict()), str(summary.to_dict())]

        # A matching run as well, so DEBUG records are produced on that path.
        assert recognize(screen, [twin_a, never]) == "twin-a"
        outputs += handler.texts
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    blob = "\n".join(outputs)
    lowered = blob.lower()
    for ch in set(sentinel):
        assert ch not in blob
        assert f"\\x{ord(ch):02x}" not in lowered
