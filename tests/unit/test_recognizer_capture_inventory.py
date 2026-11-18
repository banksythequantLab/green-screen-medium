"""Pin the capture set to exactly the ten screens of Requirement 10.2.

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
    "tso-userid-in-use",
    "tso-reconnect-password-prompt",
    "tso-reconnect-ok",
}

_SUFFIX = ".readbuffer.txt"
_ASCII_SUFFIX = ".ascii.txt"
_CAPTURES_DIR = Path(__file__).parents[2] / "captures"


def test_capture_inventory_is_exactly_the_ten_screens():
    paths = sorted(_CAPTURES_DIR.glob(f"*{_SUFFIX}"))
    found = {p.name[: -len(_SUFFIX)] for p in paths}
    unexpected = sorted(f"{n}{_SUFFIX}" for n in found - EXPECTED_NAMES)
    missing = sorted(f"{n}{_SUFFIX}" for n in EXPECTED_NAMES - found)
    assert not unexpected, f"unexpected capture file(s): {unexpected}"
    assert not missing, f"missing capture file(s): {missing}"
    assert len(paths) == 10


def test_every_capture_exists_in_both_file_forms():
    ascii_found = {
        p.name[: -len(_ASCII_SUFFIX)] for p in _CAPTURES_DIR.glob(f"*{_ASCII_SUFFIX}")
    }
    unexpected = sorted(f"{n}{_ASCII_SUFFIX}" for n in ascii_found - EXPECTED_NAMES)
    missing = sorted(f"{n}{_ASCII_SUFFIX}" for n in EXPECTED_NAMES - ascii_found)
    assert not unexpected, f"unexpected capture file(s): {unexpected}"
    assert not missing, f"missing capture file(s): {missing}"


def test_capture_names_constant_matches_inventory():
    assert len(CAPTURE_NAMES) == 10
    assert set(CAPTURE_NAMES) == EXPECTED_NAMES


@pytest.mark.parametrize("name", CAPTURE_NAMES)
def test_every_capture_loads_as_24_by_80(name):
    screen = load_capture_screen(name)
    assert (screen.rows, screen.columns) == (24, 80)
