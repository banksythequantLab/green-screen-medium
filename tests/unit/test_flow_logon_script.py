"""Scripted run of the bundled ``tk5-logon`` flow (flow-runtime task 10.14).

Covers Requirements 17.4 to 17.8, 18.8 and 18.9. Screens come from the
captures; the userid and password are obviously fake values.
"""
from __future__ import annotations

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
SENTINEL = "SNTNL-01"  # fake password, 8 characters
POLL = 0.25

FULL_KEYS = [
    ("enter",),
    ("string", USERID),
    ("enter",),
    ("string", SENTINEL),
    ("enter",),
    ("enter",),
    ("enter",),
]


def _script(start, stale=0):
    names = {
        "logo": ["tk5-logo", "tk5-logon"],
        "logon": ["tk5-logon"],
        "inr": ["tso-input-not-recognized", "tk5-logon"],
    }[start]
    states = [ScriptedState(capture(names[0]))]
    states += [ScriptedState(capture(n), stale_reads=stale) for n in names[1:]]
    states += [
        ScriptedState(capture("tso-password-prompt"), stale_reads=stale),
        ScriptedState(pause_variant(0), stale_reads=stale),
        ScriptedState(pause_variant(1), stale_reads=stale),
        ScriptedState(capture("ispf-primary-menu"), stale_reads=stale),
    ]
    return states


def _run(start, stale=0):
    flow = load_bundled_flows()["tk5-logon"]
    session = ScriptedSession(_script(start, stale), echo_typing=True)
    result = run_flow(
        flow,
        session,
        {"userid": USERID, "password": SENTINEL},
        clock=FakeClock(),
        poll_interval=POLL,
    )
    return result, session


def _keys(session):
    return [c for c in session.calls if c[0] != "read"]


def _identity(screen):
    return (screen.cell_grid, screen.cursor_row, screen.cursor_col)


def _assert_ends_at_menu(session, result):
    final = session.read_screen()
    expected = capture("ispf-primary-menu")
    assert _identity(final) == _identity(expected)
    assert result.audit[-1].status == "ok"
    assert result.audit[-1].signature == "ispf-primary-menu"
    assert SENTINEL not in repr(result)


@pytest.mark.parametrize("stale", [0, 1, 2])
def test_full_sequence_from_logo(stale):
    result, session = _run("logo", stale)
    assert _keys(session) == FULL_KEYS
    _assert_ends_at_menu(session, result)


@pytest.mark.parametrize("stale", [0, 1, 2])
def test_logon_screen_served_directly_skips_logo_enter(stale):
    result, session = _run("logon", stale)
    assert _keys(session) == FULL_KEYS[1:]
    _assert_ends_at_menu(session, result)


@pytest.mark.parametrize("stale", [0, 1])
def test_input_not_recognized_start_sends_clear_first(stale):
    result, session = _run("inr", stale)
    keys = _keys(session)
    assert keys[0] == ("clear",)
    assert keys[1:] == FULL_KEYS[1:]
    _assert_ends_at_menu(session, result)


def test_secret_never_reaches_audit_text():
    result, _ = _run("logo")
    assert SENTINEL not in repr(result.audit)
    assert SENTINEL not in repr(dict(result.outputs))
