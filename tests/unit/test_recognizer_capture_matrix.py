"""10-by-10 matrix: every bundled signature against every capture."""
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

def test_capture_glob_has_exactly_ten_files() -> None:
    paths = sorted(CAPTURES_DIR.glob("*.readbuffer.txt"))
    found = {p.name[: -len(".readbuffer.txt")] for p in paths}
    unexpected = sorted(f"{n}.readbuffer.txt" for n in found - set(CAPTURE_NAMES))
    missing = sorted(f"{n}.readbuffer.txt" for n in set(CAPTURE_NAMES) - found)
    assert not unexpected, f"unexpected capture file(s): {unexpected}"
    assert not missing, f"missing capture file(s): {missing}"
    assert len(paths) == 10
    assert len(CAPTURE_NAMES) == 10


def test_ten_bundled_signatures() -> None:
    sigs = load_bundled_signatures()
    assert len(sigs) == 10
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

    assert performed == 10
    assert matched == [EXPECTED[capture]], (
        f"capture {capture}: satisfied signatures {matched}, expected [{EXPECTED[capture]}]"
    )
    assert recognize(screen, sigs) == EXPECTED[capture]


def test_matrix_size_is_100_evaluations() -> None:
    sigs = load_bundled_signatures()
    count = 0
    for capture in CAPTURE_NAMES:
        view = ScreenView(load_capture_screen(capture))
        for sig in sigs:
            signature_matches(sig, view)
            count += 1
    assert count == 10 * 10 == 100


@pytest.mark.parametrize(
    "sig_name,capture",
    [
        ("tso-reconnect-password-prompt", "tso-password-prompt"),
        ("tso-password-prompt", "tso-reconnect-password-prompt"),
    ],
)
def test_the_two_password_prompts_do_not_match_each_other(sig_name: str, capture: str) -> None:
    sig = next(s for s in load_bundled_signatures() if s.name == sig_name)
    view = ScreenView(load_capture_screen(capture))
    assert not signature_matches(sig, view), f"signature {sig_name} matched capture {capture}"
