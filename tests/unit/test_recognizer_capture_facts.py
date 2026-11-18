"""Facts about the ten repo captures that the bundled signatures rely on.

Every value is read through ``ScreenParser`` on each run. This file may read
``Screen.text_grid`` and ``Screen.fields``; it must never be applied to a screen
holding a typed password.
"""
from __future__ import annotations

import re

from tests.screen_support import load_capture_screen

_DATE = re.compile(r"(?:0[1-9]|[12][0-9]|3[01])\.[0-9]{2}\.[0-9]{2}")
_TIME = re.compile(
    r"(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]|(?:[01][0-9]|2[0-3]):[0-5][0-9]"
)


def _unprotected_starts(screen):
    return [(f.start_row, f.start_col) for f in screen.fields if not f.protected]


def _cursor(screen):
    return (screen.cursor_row, screen.cursor_col)


def _non_blank_rows(screen):
    return [i for i, r in enumerate(screen.text_grid) if r.strip(" ")]


def _scan(screen, pattern):
    return [
        (r, m.start(), m.group())
        for r, line in enumerate(screen.text_grid)
        for m in pattern.finditer(line)
    ]


def _cursor_field(screen):
    f = screen.find_field(screen.cursor_row, screen.cursor_col)
    assert f is not None
    return f


def _assert_text(screen, row, col, text):
    assert screen.text_grid[row][col : col + len(text)] == text


def test_tk5_logo():
    s = load_capture_screen("tk5-logo")
    assert (s.rows, s.columns) == (24, 80)
    assert _cursor(s) == (0, 0)
    assert _cursor_field(s).protected
    assert _unprotected_starts(s) == []
    _assert_text(s, 0, 1, "Hercules Version  :")
    assert "The MVS 3.8j" in s.text_grid[16]
    assert "Tur(n)key System" in s.text_grid[17]
    assert "see SYS2.JCLLIB(CREDITS) for complete credits" in s.text_grid[23]
    assert _scan(s, _DATE) == []
    assert _scan(s, _TIME) == []


def test_tk5_logon():
    s = load_capture_screen("tk5-logon")
    assert _cursor(s) == (22, 11)
    assert _unprotected_starts(s) == [(22, 10)]
    f = _cursor_field(s)
    assert (f.start_row, f.start_col, f.hidden) == (22, 10, False)
    _assert_text(s, 22, 0, "Logon ===>")
    _assert_text(s, 0, 66, "Date")
    _assert_text(s, 1, 66, "Time")
    assert _scan(s, _DATE) == [(0, 72, "15.11.26")]
    assert _scan(s, _TIME) == [(1, 72, "16:25:01")]


def test_tso_input_not_recognized():
    s = load_capture_screen("tso-input-not-recognized")
    assert _cursor(s) == (0, 0)
    assert _unprotected_starts(s) == [(4, 40)]
    f = _cursor_field(s)
    assert (f.start_row, f.start_col) == (4, 40)
    _assert_text(s, 3, 0, "INPUT NOT RECOGNIZED")
    assert _non_blank_rows(s) == [3]
    assert s.text_grid[3].strip(" ") == "INPUT NOT RECOGNIZED"
    assert _scan(s, _DATE) == []
    assert _scan(s, _TIME) == []


def test_tso_password_prompt():
    s = load_capture_screen("tso-password-prompt")
    assert _cursor(s) == (1, 1)
    assert _unprotected_starts(s) == [(0, 0), (0, 35), (1, 0), (23, 79)]
    hidden = [f for f in s.fields if f.hidden]
    assert [(f.start_row, f.start_col) for f in hidden] == [(1, 0)]
    assert hidden[0].c0 == 0xCC
    assert not hidden[0].protected
    f = _cursor_field(s)
    assert (f.start_row, f.start_col, f.hidden) == (1, 0, True)
    assert s.text_grid[0].rstrip(" ") == " ENTER CURRENT PASSWORD FOR HERC01-"
    assert _non_blank_rows(s) == [0]
    assert re.search(
        r"^ ENTER CURRENT PASSWORD FOR [^ ]{1,8}- *$", s.text_grid[0][0:80]
    )
    # Privacy: the hidden field holds only blank cells.
    assert set(hidden[0].text) <= {" "}
    assert _scan(s, _DATE) == []
    assert _scan(s, _TIME) == []


def test_ispf_primary_menu():
    s = load_capture_screen("ispf-primary-menu")
    assert _cursor(s) == (1, 14)
    assert _unprotected_starts(s) == [(1, 13)]
    f = _cursor_field(s)
    assert (f.start_row, f.start_col, f.hidden) == (1, 13, False)
    _assert_text(s, 0, 28, "ISPF primary option menu")
    _assert_text(s, 1, 1, "Option  ===>")
    assert _scan(s, _TIME) == [(3, 71, "04:09")]
    assert _scan(s, _DATE) == []


def test_tso_ready():
    s = load_capture_screen("tso-ready")
    assert _cursor(s) == (1, 0)
    f = _cursor_field(s)
    assert (f.start_row, f.start_col) == (0, 7)
    assert _non_blank_rows(s) == [0]
    assert s.text_grid[0].rstrip(" ") == " READY"
    assert _scan(s, _DATE) == []
    assert _scan(s, _TIME) == []


def test_tso_pause_2():
    s = load_capture_screen("tso-pause-2")
    assert _cursor(s) == (11, 5)
    f = _cursor_field(s)
    assert (f.start_row, f.start_col) == (11, 4)
    rows = _non_blank_rows(s)
    assert rows[-1] == 11
    assert s.text_grid[11].rstrip(" ") == " ***"
    assert _scan(s, _DATE) == []
    assert _scan(s, _TIME) == []


def _field_geometry(screen):
    return [(f.start_row, f.start_col, f.byte_length) for f in screen.fields]


def test_tso_userid_in_use():
    s = load_capture_screen("tso-userid-in-use")
    assert (s.rows, s.columns) == (24, 80)
    assert _cursor(s) == (1, 0)
    assert _field_geometry(s) == [(0, 0, 46), (0, 47, 1871), (23, 79, 0)]
    assert all(not f.protected and not f.hidden for f in s.fields)
    assert _non_blank_rows(s) == [0]


def test_tso_reconnect_password_prompt():
    s = load_capture_screen("tso-reconnect-password-prompt")
    assert (s.rows, s.columns) == (24, 80)
    assert _cursor(s) == (3, 1)
    hidden = [f for f in s.fields if f.hidden]
    assert [(f.start_row, f.start_col, f.byte_length) for f in hidden] == [(3, 0, 1678)]
    f = _cursor_field(s)
    assert (f.start_row, f.start_col, f.hidden) == (3, 0, True)
    assert _non_blank_rows(s) == [0, 1, 2]
    assert "IKJ56714A ENTER CURRENT PASSWORD FOR" in s.text_grid[2]


def test_tso_reconnect_ok():
    s = load_capture_screen("tso-reconnect-ok")
    assert (s.rows, s.columns) == (24, 80)
    assert _cursor(s) == (1, 0)
    assert _field_geometry(s) == [(0, 0, 58), (0, 59, 1859), (23, 79, 0)]
    assert not any(f.hidden for f in s.fields)
    assert _non_blank_rows(s) == [0]
