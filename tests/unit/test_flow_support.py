"""Self-tests for ScriptedSession, FakeClock and the helpers of tests/flow_support.py."""
from __future__ import annotations

import os

import pytest

from tests.flow_support import (
    _CAPTURES_DIR,
    FakeClock,
    ScriptedSession,
    ScriptedState,
    blank_screen,
    capture,
    sentinel_password_screen,
)


def _id(screen):
    """A comparable identity: cells and cursor."""
    return (screen.cell_grid, screen.cursor_row, screen.cursor_col)


A = capture("tk5-logo")
B = capture("tk5-logon")
C = capture("ispf-primary-menu")


# --------------------------------------------------------------------------
# FakeClock
# --------------------------------------------------------------------------

def test_clock_starts_at_zero():
    clock = FakeClock()
    assert clock.monotonic() == 0.0
    assert clock.sleeps == []


def test_clock_sleep_advances_by_exact_seconds_and_records():
    clock = FakeClock()
    clock.sleep(0.1)
    clock.sleep(2.5)
    clock.sleep(0)
    assert clock.monotonic() == 0.1 + 2.5
    assert clock.sleeps == [0.1, 2.5, 0]


def test_clock_sleep_returns_at_once_even_for_long_sleeps():
    import time

    clock = FakeClock()
    start = time.perf_counter()
    clock.sleep(3600.0)
    assert time.perf_counter() - start < 1.0
    assert clock.monotonic() == 3600.0


def test_clock_rejects_negative_sleep():
    clock = FakeClock()
    with pytest.raises(ValueError):
        clock.sleep(-0.1)
    assert clock.monotonic() == 0.0
    assert clock.sleeps == []


# --------------------------------------------------------------------------
# ScriptedState / construction
# --------------------------------------------------------------------------

def test_state_rejects_bad_stale_reads():
    for bad in (-1, 11, 1.0, True):
        with pytest.raises(ValueError):
            ScriptedState(A, stale_reads=bad)
    assert ScriptedState(A, stale_reads=0).stale_reads == 0
    assert ScriptedState(A, stale_reads=10).stale_reads == 10


def test_session_requires_a_state():
    with pytest.raises(ValueError):
        ScriptedSession([])


def test_bare_screens_are_accepted_as_states():
    s = ScriptedSession([A, B])
    assert _id(s.read_screen()) == _id(A)


# --------------------------------------------------------------------------
# Call log
# --------------------------------------------------------------------------

def test_call_log_records_every_call_in_order():
    s = ScriptedSession([A, B, C, A, B, C])
    s.read_screen()
    s.string("hello")
    s.enter()
    s.clear()
    s.pf(3)
    s.pa(2)
    s.close()
    assert s.calls == [
        ("read",),
        ("string", "hello"),
        ("enter",),
        ("clear",),
        ("pf", 3),
        ("pa", 2),
        ("close",),
    ]


# --------------------------------------------------------------------------
# Key advance
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "key", [lambda s: s.enter(), lambda s: s.clear(), lambda s: s.pf(1), lambda s: s.pa(1)]
)
def test_every_key_advances_one_state(key):
    s = ScriptedSession([A, B, C])
    assert _id(s.read_screen()) == _id(A)
    key(s)
    assert _id(s.read_screen()) == _id(B)


def test_string_does_not_advance():
    s = ScriptedSession([A, B])
    s.string("x")
    assert _id(s.read_screen()) == _id(A)


def test_stays_on_last_state_without_error():
    s = ScriptedSession([A, B])
    for _ in range(5):
        s.enter()
    assert _id(s.read_screen()) == _id(B)
    assert _id(s.read_screen()) == _id(B)


# --------------------------------------------------------------------------
# Stale reads and repaints
# --------------------------------------------------------------------------

def test_stale_reads_serve_previous_screen_for_n_reads_then_own():
    s = ScriptedSession([A, ScriptedState(B, stale_reads=3)])
    s.enter()
    for _ in range(3):
        assert _id(s.read_screen()) == _id(A)
    for _ in range(3):
        assert _id(s.read_screen()) == _id(B)


def test_stale_reads_before_any_key_are_not_served():
    s = ScriptedSession([ScriptedState(A, stale_reads=4), B])
    assert _id(s.read_screen()) == _id(A)


def test_stale_reads_use_the_previous_state_not_the_first():
    s = ScriptedSession([A, B, ScriptedState(C, stale_reads=2)])
    s.enter()
    s.enter()
    assert _id(s.read_screen()) == _id(B)
    assert _id(s.read_screen()) == _id(B)
    assert _id(s.read_screen()) == _id(C)


def test_repaints_are_served_once_each_after_stale_reads():
    r1, r2 = blank_screen(), capture("tso-ready")
    s = ScriptedSession([A, ScriptedState(B, stale_reads=1, repaints=(r1, r2))])
    s.enter()
    assert _id(s.read_screen()) == _id(A)
    assert _id(s.read_screen()) == _id(r1)
    assert _id(s.read_screen()) == _id(r2)
    assert _id(s.read_screen()) == _id(B)
    assert _id(s.read_screen()) == _id(B)


def test_next_key_discards_unread_queue():
    s = ScriptedSession([A, ScriptedState(B, stale_reads=5), C])
    s.enter()
    s.enter()
    # The 5 unread stale reads of state B are dropped; C has none of its own.
    assert _id(s.read_screen()) == _id(C)


# --------------------------------------------------------------------------
# Copies
# --------------------------------------------------------------------------

def test_read_returns_independent_copies():
    s = ScriptedSession([A])
    first = s.read_screen()
    first.cell_grid[0][0] = 0x58
    first.cursor_row = 5
    second = s.read_screen()
    assert first is not second
    assert _id(second) == _id(A)
    assert second.cell_grid[0][0] == A.cell_grid[0][0]


def test_session_does_not_alias_the_input_screen():
    src = capture("tk5-logon")
    s = ScriptedSession([src])
    src.cell_grid[0][0] = 0x58
    assert s.read_screen().cell_grid[0][0] != 0x58


# --------------------------------------------------------------------------
# echo_typing
# --------------------------------------------------------------------------

def test_echo_typing_writes_text_into_cursor_field():
    s = ScriptedSession([B], echo_typing=True)
    before = s.read_screen()
    s.string("USER1")
    after = s.read_screen()
    r, c = before.cursor_row, before.cursor_col
    assert [after.cell_grid[r][c + i] for i in range(5)] == [ord(ch) for ch in "USER1"]
    assert (after.cursor_row, after.cursor_col) == (r, c + 5)


def test_without_echo_typing_screen_is_unchanged():
    s = ScriptedSession([B])
    s.string("USER1")
    assert _id(s.read_screen()) == _id(B)


def test_echo_typing_with_no_target_leaves_screen_alone():
    s = ScriptedSession([blank_screen()], echo_typing=True)
    s.string("x")
    assert _id(s.read_screen()) == _id(blank_screen())
    assert s.calls[0] == ("string", "x")


# --------------------------------------------------------------------------
# sentinel_password_screen
# --------------------------------------------------------------------------

def test_sentinel_is_in_hidden_cells_and_absent_from_captures():
    sentinel = "Qz9#vL"
    screen = sentinel_password_screen(sentinel)
    hidden = next(f for f in screen.fields if f.hidden)
    cells = []
    pos = hidden.start_row * screen.columns + hidden.start_col + 1
    for i in range(len(sentinel)):
        r, c = divmod(pos + i, screen.columns)
        cells.append(screen.cell_grid[r][c])
    assert cells == [ord(ch) for ch in sentinel]
    for root, _dirs, files in os.walk(_CAPTURES_DIR):
        for name in files:
            text = open(os.path.join(root, name), encoding="utf-8", errors="replace").read()
            assert sentinel not in text


def test_sentinel_hex_form_is_not_in_captures_either():
    sentinel = "Qz9#vL"
    hexed = " ".join(f"{ord(ch):02x}" for ch in sentinel)
    for root, _dirs, files in os.walk(_CAPTURES_DIR):
        for name in files:
            text = open(os.path.join(root, name), encoding="utf-8", errors="replace").read()
            assert hexed not in text


def test_sentinel_rejects_bad_length_and_captured_text():
    with pytest.raises(ValueError):
        sentinel_password_screen("")
    with pytest.raises(ValueError):
        sentinel_password_screen("123456789")
    with pytest.raises(AssertionError):
        sentinel_password_screen("Logon")  # occurs in captures/


def test_sentinel_screen_does_not_alter_the_cached_capture():
    sentinel_password_screen("Qz9#vL")
    assert _id(capture("tso-password-prompt")) == _id(capture("tso-password-prompt"))
    hidden = next(f for f in capture("tso-password-prompt").fields if f.hidden)
    assert hidden is not None
    cap = capture("tso-password-prompt")
    pos = hidden.start_row * cap.columns + hidden.start_col + 1
    r, c = divmod(pos, cap.columns)
    assert cap.cell_grid[r][c] != ord("Q")


# --------------------------------------------------------------------------
# No file writes
# --------------------------------------------------------------------------

def _snapshot(root):
    out = {}
    for dirpath, _d, files in os.walk(root):
        for f in files:
            p = os.path.join(dirpath, f)
            st = os.stat(p)
            out[p] = (st.st_size, st.st_mtime_ns)
    return out


def test_helpers_write_no_file(tmp_path, monkeypatch):
    from tests import flow_support as fs

    monkeypatch.chdir(tmp_path)
    before_captures = _snapshot(_CAPTURES_DIR)

    clock = FakeClock()
    clock.sleep(1.0)
    s = ScriptedSession([B, A], echo_typing=True)
    s.read_screen()
    s.string("abc")
    s.enter()
    s.read_screen()
    s.close()
    sentinel_password_screen("Qz9#vL")
    fs.pause_variant(3)
    fs.partial_repaint("tk5-logon", 1)
    fs.typed_screen(B, "x")
    fs.blank_screen()

    assert list(tmp_path.iterdir()) == []
    assert _snapshot(_CAPTURES_DIR) == before_captures
