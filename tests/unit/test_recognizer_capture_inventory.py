"""Pin the capture set to exactly the seven screens of Requirement 10.2.

A new capture (in particular one of a screen holding a residual password,
Requirement 13.6) fails this test until the requirements are updated.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.screen_support import CAPTURE_NAMES, load_capture_screen

EXPECTED_NAMES = {
    "tk5-logo",
    "tk5-logon",
    "tso-input-not-recognized",
    "tso-password-prompt",
    "ispf-primary-menu",
    "tso-ready",
    "tso-pause-2",
}

_SUFFIX = ".readbuffer.txt"
_CAPTURES_DIR = Path(__file__).parents[2] / "captures"


def test_capture_inventory_is_exactly_the_seven_screens():
    paths = sorted(_CAPTURES_DIR.glob(f"*{_SUFFIX}"))
    assert len(paths) == 7
    assert {p.name[: -len(_SUFFIX)] for p in paths} == EXPECTED_NAMES


def test_capture_names_constant_matches_inventory():
    assert len(CAPTURE_NAMES) == 7
    assert set(CAPTURE_NAMES) == EXPECTED_NAMES


@pytest.mark.parametrize("name", CAPTURE_NAMES)
def test_every_capture_loads_as_24_by_80(name):
    screen = load_capture_screen(name)
    assert (screen.rows, screen.columns) == (24, 80)
