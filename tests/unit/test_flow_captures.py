"""Capture facts the flow package depends on (task 10.16).

Covers Requirements 8.17, 10.7, 17.13, 17.14, 18.5 and 18.10.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from greenscreen.connector.models import SFToken
from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.recognizer.view import ScreenView

from tests.connector_support import forms_of_run
from tests.flow_support import capture, sentinel_password_screen
from tests.screen_support import CAPTURE_NAMES

_CAPTURES_DIR = Path(__file__).parents[2] / "captures"
_SUFFIX = ".readbuffer.txt"

_EXPECTED_NAMES = {
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
    "tso-cleared",
    "tso-listcat-level",
    "tso-listcat-level-page2",
    "tso-listcat-level-page3",
    "tso-listcat-output",
    "tso-listds-members",
    "tso-listds-members-page2",
    "tso-listds-members-page3",
    "tso-listds-members-page4",
    "tso-listds-members-page5",
    "tso-listds-members-page6",
    "tso-listds-members-page7",
    "tso-listds-not-in-catalog",
    "tso-listds-output",
    "tso-listds-reenter",
    "tso-listds-reenter-after-pa1",
    "tso-status-output",
    "tso-time-output",
}

_LABELS = {
    "USERID": "USERID   :",
    "TERMINAL": "TERMINAL :",
    "RELEASE": "RELEASE  :",
    "SYSTEMID": "SYSTEMID :",
}
_LABEL_COL = 60


# --------------------------------------------------------------------------
# tk5-system-info Output regions on the ISPF primary menu
# --------------------------------------------------------------------------

def _outputs():
    flow = load_bundled_flows()["tk5-system-info"]
    return {o.name: o for o in flow.outputs}


def test_system_info_has_exactly_the_four_labelled_outputs():
    assert set(_outputs()) == set(_LABELS)


@pytest.mark.parametrize("name", sorted(_LABELS))
def test_output_region_is_inside_the_menu_and_not_hidden(name):
    out = _outputs()[name]
    assert out.signature == "ispf-primary-menu"
    screen = capture("ispf-primary-menu")
    assert 0 <= out.row < screen.rows
    assert out.length >= 1
    assert 0 <= out.col
    assert out.col + out.length <= screen.columns
    view = ScreenView(screen)
    for col in range(out.col, out.col + out.length):
        geom = view.containing_field(out.row, col)
        assert geom is not None
        assert geom.hidden is False


@pytest.mark.parametrize("name", sorted(_LABELS))
def test_text_at_col_60_of_the_output_row_is_the_label(name):
    out = _outputs()[name]
    label = _LABELS[name]
    screen = capture("ispf-primary-menu")
    assert screen.text_at(out.row, _LABEL_COL, len(label)) == label


# --------------------------------------------------------------------------
# ScreenView.containing_field agrees with Screen.find_field at every cursor
# --------------------------------------------------------------------------

def _holds_password(screen) -> bool:
    """True if a hidden field holds a non-blank cell. Reads cells only, returns a bool."""
    total = screen.rows * screen.columns
    for f in screen.fields:
        if not f.hidden:
            continue
        start = f.start_row * screen.columns + f.start_col
        for i in range(1, f.byte_length + 1):
            r, c = divmod((start + i) % total, screen.columns)
            cell = screen.cell_grid[r][c]
            if not isinstance(cell, SFToken) and cell not in (0x00, 0x20):
                return True
    return False


@pytest.mark.parametrize("name", CAPTURE_NAMES)
def test_containing_field_agrees_with_find_field_at_the_cursor(name):
    screen = capture(name)
    assert _holds_password(screen) is False
    geom = ScreenView(screen).containing_field(screen.cursor_row, screen.cursor_col)
    oracle = screen.find_field(screen.cursor_row, screen.cursor_col)
    if oracle is None:
        assert geom is None
        return
    assert geom is not None
    assert (geom.start_row, geom.start_col) == (oracle.start_row, oracle.start_col)
    assert geom.byte_length == oracle.byte_length
    assert geom.protected == oracle.protected
    assert geom.hidden == oracle.hidden


# --------------------------------------------------------------------------
# The capture set and the password sentinel
# --------------------------------------------------------------------------

def test_readbuffer_captures_are_exactly_the_ten_names():
    names = {p.name[: -len(_SUFFIX)] for p in _CAPTURES_DIR.glob(f"*{_SUFFIX}")}
    unexpected = sorted(f"{n}{_SUFFIX}" for n in names - _EXPECTED_NAMES)
    missing = sorted(f"{n}{_SUFFIX}" for n in _EXPECTED_NAMES - names)
    assert not unexpected, f"unexpected capture file(s): {unexpected}"
    assert not missing, f"missing capture file(s): {missing}"
    assert set(CAPTURE_NAMES) == _EXPECTED_NAMES


def test_no_capture_holds_a_typed_password():
    assert [n for n in CAPTURE_NAMES if _holds_password(capture(n))] == []


@pytest.mark.parametrize("name", sorted(_EXPECTED_NAMES))
def test_every_capture_has_only_blank_hidden_cells(name):
    assert _holds_password(capture(name)) is False, f"capture {name} holds a hidden-field cell"


def test_no_password_hex_form_occurs_in_any_capture_file():
    password = os.environ.get("TK5_PASSWORD", "")
    if not password:
        pytest.skip("TK5_PASSWORD is unset or empty")
    forms = forms_of_run(list(password.encode("utf-8")))
    offenders = []
    for path in sorted(_CAPTURES_DIR.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found = False
        for form in forms:
            found = found or (form in text)
        if found:
            offenders.append(path.name)
    # Verdict is a boolean list check; the message names files only.
    assert offenders == [], f"capture file(s) contain the password: {offenders}"


def test_no_capture_exists_for_the_screen_after_the_password_entry():
    stems = set()
    for path in _CAPTURES_DIR.rglob("*"):
        if path.is_file():
            stems.add(path.name.split(".")[0])
    assert sorted(stems - _EXPECTED_NAMES) == []
    assert "tso-pause" not in stems
    assert "tso-pause-1" not in stems


@pytest.mark.parametrize("sentinel", ["Qz9#vL", "zXq7!kP2"])
def test_sentinel_occurs_in_no_file_under_captures(sentinel):
    sentinel_password_screen(sentinel)  # asserts absence itself
    hex_form = " ".join(f"{ord(ch):02x}" for ch in sentinel)
    plain_found = False
    hex_found = False
    for path in _CAPTURES_DIR.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        plain_found = plain_found or sentinel in text
        hex_found = hex_found or hex_form in text.lower()
    assert plain_found is False
    assert hex_found is False
