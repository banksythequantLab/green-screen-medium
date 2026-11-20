"""Timed blank frames of ``ScriptedSession`` (more-flows task 6.6; Requirements 24.11, 24.13)."""
from __future__ import annotations

import math

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.runner import run_flow

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    capture,
    pause_variant,
)

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"


def _ident(screen):
    return (screen.cell_grid, screen.cursor_row, screen.cursor_col)


def _is(screen, name):
    return _ident(screen) == _ident(capture(name))


def _session(blanks, clock, stale=0):
    states = [
        ScriptedState(capture("tk5-logon")),
        ScriptedState(capture("ispf-primary-menu"), stale_reads=stale, blanks=blanks),
    ]
    return ScriptedSession(states, clock=clock)


def test_frames_follow_the_clock():
    clock = FakeClock()
    s = _session((0.006, 0.010), clock)
    s.enter()
    # total 0.016: a read at 0, just inside and exactly at/after the end
    assert _is(s.read_screen(), "tso-cleared")
    clock.now = 0.006
    assert _is(s.read_screen(), "tso-cleared")
    clock.now = 0.016 - 0.0001
    assert _is(s.read_screen(), "tso-cleared")
    clock.now = 0.016
    assert _is(s.read_screen(), "ispf-primary-menu")
    clock.now = 5.0
    assert _is(s.read_screen(), "ispf-primary-menu")


def test_frame_time_counts_from_the_key():
    clock = FakeClock()
    clock.now = 10.0
    s = _session((0.05,), clock)
    s.enter()
    clock.now = 10.049
    assert _is(s.read_screen(), "tso-cleared")
    clock.now = 10.05
    assert _is(s.read_screen(), "ispf-primary-menu")


def test_stale_reads_come_first():
    clock = FakeClock()
    s = _session((0.05,), clock, stale=2)
    s.enter()
    assert _is(s.read_screen(), "tk5-logon")
    assert _is(s.read_screen(), "tk5-logon")
    assert _is(s.read_screen(), "tso-cleared")
    clock.now = 0.05
    assert _is(s.read_screen(), "ispf-primary-menu")


def test_blank_is_a_copy():
    clock = FakeClock()
    s = _session((0.05,), clock)
    s.enter()
    a = s.read_screen()
    a.cell_grid[0][0] = 0x41
    assert _is(s.read_screen(), "tso-cleared")


@pytest.mark.parametrize("bad", [0, -0.1, math.inf, -math.inf, math.nan, "0.1", None, True])
def test_bad_blank_values_raise(bad):
    with pytest.raises(ValueError):
        ScriptedState(capture("tk5-logon"), blanks=(0.1, bad))


def test_blanks_without_a_clock_raise():
    with pytest.raises(ValueError):
        ScriptedSession([ScriptedState(capture("tk5-logon"), blanks=(0.01,))])


def test_default_state_has_no_blanks_and_needs_no_clock():
    assert ScriptedState(capture("tk5-logon")).blanks == ()
    ScriptedSession([capture("tk5-logon")])


def _logon_states():
    return [
        ScriptedState(capture("tk5-logon")),
        ScriptedState(capture("tso-password-prompt")),
        ScriptedState(pause_variant(0)),
        ScriptedState(pause_variant(1)),
        ScriptedState(capture("ispf-primary-menu")),
    ]


def _logon_calls(with_clock):
    flow = load_bundled_flows()["tk5-logon"]
    clock = FakeClock()
    session = ScriptedSession(
        _logon_states(), echo_typing=True, clock=clock if with_clock else None
    )
    run_flow(
        flow, session, {"userid": USERID, "password": SENTINEL},
        clock=clock, poll_interval=0.25,
    )
    return session.calls


def test_no_blanks_means_no_change_in_a_logon_run():
    assert _logon_calls(True) == _logon_calls(False)
