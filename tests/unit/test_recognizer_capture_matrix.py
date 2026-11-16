"""7-by-7 matrix: every bundled signature against every capture."""
from __future__ import annotations

from pathlib import Path

import pytest

from greenscreen.recognizer.bundled import load_bundled_signatures
from greenscreen.recognizer.matching import signature_matches
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.view import ScreenView
from tests.screen_support import CAPTURE_NAMES, load_capture_screen

CAPTURES_DIR = Path(__file__).parents[2] / "captures"

EXPECTED = {name: name for name in CAPTURE_NAMES}
EXPECTED["tso-pause-2"] = "tso-pause"

def test_capture_glob_has_exactly_seven_files() -> None:
    paths = sorted(CAPTURES_DIR.glob("*.readbuffer.txt"))
    assert len(paths) == 7
    assert len(CAPTURE_NAMES) == 7
    assert {p.name[: -len(".readbuffer.txt")] for p in paths} == set(CAPTURE_NAMES)


def test_seven_bundled_signatures() -> None:
    sigs = load_bundled_signatures()
    assert len(sigs) == 7
    assert {s.name for s in sigs} == set(EXPECTED.values())


@pytest.mark.parametrize("capture", CAPTURE_NAMES)
def test_capture_matches_exactly_its_own_signature(capture: str) -> None:
    sigs = load_bundled_signatures()
    screen = load_capture_screen(capture)
    view = ScreenView(screen)

    matched = []
    performed = 0
    for sig in sigs:
        result = signature_matches(sig, view)
        performed += 1
        if result:
            matched.append(sig.name)

    assert performed == 7
    assert matched == [EXPECTED[capture]]
    assert recognize(screen, sigs) == EXPECTED[capture]


def test_matrix_size_is_49_evaluations() -> None:
    sigs = load_bundled_signatures()
    count = 0
    for capture in CAPTURE_NAMES:
        view = ScreenView(load_capture_screen(capture))
        for sig in sigs:
            signature_matches(sig, view)
            count += 1
    assert count == 7 * 7 == 49
