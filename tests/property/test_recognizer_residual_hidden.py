"""Property test: residual hidden content on non-password screens (Property 5).

Synthetic screens only. No capture of a residual-password screen is used.
"""
from __future__ import annotations

import copy
import json
import logging

import pytest
from hypothesis import given, settings

from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.errors import AmbiguousScreenError, UnknownScreenError
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.signature import ScreenSignature, TextAtMatcher
from greenscreen.recognizer.suggest import suggest_signature
from greenscreen.recognizer.summary import build_summary
from greenscreen.recognizer.view import ScreenView
from tests.property._recognizer_strategies import line_mode_screens

_PAUSE = next(s for s in load_bundled_signatures() if s.name == "tso-pause")


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _forms(sentinel: str) -> list[str]:
    forms = list(sentinel)
    for ch in sentinel:
        forms.append(f"\\x{ord(ch):02x}")
        forms.append(f"\\x{ord(ch):02X}")
    return forms


def _blank_residual(screen):
    clean = copy.deepcopy(screen)
    for row in clean.cell_grid:
        for i, cell in enumerate(row):
            if isinstance(cell, int) and cell >= 0xC0:
                row[i] = 0x20
    return clean


def _exception_texts(exc: Exception) -> list[str]:
    texts = [str(exc), repr(exc), repr(exc.args)]
    texts += [str(a) for a in exc.args]
    texts.append(repr(vars(exc)))
    for v in vars(exc).values():
        texts.append(str(v))
        texts.append(repr(v))
    return texts


# Feature: screen-recognizer, Property 5: Residual hidden content on non-password screens
@settings(max_examples=100, deadline=None)
@given(case=line_mode_screens(with_hidden=True))
def test_residual_hidden_content_never_leaks(case):
    """**Validates: Requirements 13.1, 13.3, 13.7**"""
    screen, _pause_row, sentinel = case
    assert sentinel
    clean = _blank_residual(screen)
    assert not any(
        isinstance(c, int) and c >= 0xC0 for row in clean.cell_grid for c in row
    )

    collector = _Collector()
    logger = logging.getLogger("greenscreen.recognizer")
    old_level, old_prop = logger.level, logger.propagate
    logger.addHandler(collector)
    logger.setLevel(logging.DEBUG)
    try:
        texts: list[str] = []

        # recognize: same result with and without the residual content.
        assert recognize(screen, [_PAUSE]) == "tso-pause"
        assert recognize(clean, [_PAUSE]) == "tso-pause"

        # suggest_signature output.
        sig = suggest_signature(screen)
        texts += [sig.to_yaml(), repr(sig)]
        assert sig.to_yaml() == suggest_signature(clean).to_yaml()

        # UnknownScreenError.
        never = ScreenSignature(
            name="never", matchers=(TextAtMatcher(row=screen.rows, col=0, text="X"),)
        )
        with pytest.raises(UnknownScreenError) as unknown:
            recognize(screen, [never])
        with pytest.raises(UnknownScreenError) as unknown_clean:
            recognize(clean, [never])
        texts += _exception_texts(unknown.value)
        summary = unknown.value.summary
        texts += [summary.to_text(), json.dumps(summary.to_dict()), repr(summary)]
        assert summary == unknown_clean.value.summary
        assert summary == build_summary(ScreenView(screen))

        # AmbiguousScreenError.
        twin = ScreenSignature(name="tso-pause-twin", matchers=_PAUSE.matchers)
        with pytest.raises(AmbiguousScreenError) as ambiguous:
            recognize(screen, [_PAUSE, twin])
        texts += _exception_texts(ambiguous.value)

        # DEBUG records.
        assert collector.records
        for rec in collector.records:
            texts.append(rec.getMessage())
            texts.append(str(rec.msg))
            texts.append(repr(rec.args))
    finally:
        logger.removeHandler(collector)
        logger.setLevel(old_level)
        logger.propagate = old_prop

    for text in texts:
        for form in _forms(sentinel):
            assert form.lower() not in text.lower()
