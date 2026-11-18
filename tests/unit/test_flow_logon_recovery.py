"""Scripted recovery paths of the bundled ``tk5-logon`` flow (logon-recovery task 6.1).

The account was left logged on, so the host answers the user id with
``IKJ56425I ... IN USE``. The flow types ``LOGON <id> RECONNECT``, gives the
password and presses Enter until the ISPF menu shows. Screens come from the
captures and the synthetic builders. The userid and password are fake.
"""
from __future__ import annotations

import logging

import pytest

from greenscreen.connector.models import SFToken
from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import recognize, load_bundled_signatures
from greenscreen.recognizer.signature import RegionRegexMatcher, ScreenSignature

from tests.connector_support import LogCapture, collect_record_text, forms_of_run
from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    blank_screen,
    capture,
)
from tests.screen_support import reconnect_pause_screen, second_in_use_screen

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"  # fake password, 8 characters
POLL = 0.25

PASSWORD_FORMS = forms_of_run([ord(c) for c in SENTINEL])

# Calls up to and including the Enter that sends the reconnect command.
CALLS_TO_RECONNECT = [
    ("string", USERID),
    ("enter",),
    ("string", "LOGON "),
    ("string", USERID),
    ("string", " RECONNECT"),
    ("enter",),
]
CALLS_TO_PASSWORD = CALLS_TO_RECONNECT + [("string", SENTINEL), ("enter",)]


def _states(*screens):
    return [ScriptedState(s) for s in screens]


def _recovery_screens():
    return [
        capture("tk5-logon"),
        capture("tso-userid-in-use"),
        capture("tso-reconnect-password-prompt"),
        capture("tso-reconnect-ok"),
        reconnect_pause_screen(),
        capture("ispf-primary-menu"),
    ]


@pytest.fixture
def log_records():
    handler = LogCapture(logging.DEBUG)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def _run(screens):
    flow = load_bundled_flows()["tk5-logon"]
    session = ScriptedSession(_states(*screens), echo_typing=True)
    try:
        result = run_flow(
            flow,
            session,
            {"userid": USERID, "password": SENTINEL},
            clock=FakeClock(),
            poll_interval=POLL,
        )
        return result, None, session
    except FlowError as exc:
        return None, exc, session


def _keys(session):
    return [c for c in session.calls if c[0] != "read"]


def _leak_verdict(result, error, records) -> bool:
    """True when the password occurs in any output form. Booleans only."""
    texts: list[str] = []
    if result is not None:
        texts += [repr(result), repr(result.audit)]
    if error is not None:
        texts += [str(error), repr(error), repr(error.audit)]
    for record in records:
        texts += collect_record_text(record)
    return any(form in text for text in texts for form in PASSWORD_FORMS)


def _assert_no_leak(result, error, records):
    assert _leak_verdict(result, error, records) is False


def test_recovery_logon_sends_ten_calls_and_ends_at_menu(log_records):
    result, error, session = _run(_recovery_screens())
    assert error is None
    assert _keys(session) == CALLS_TO_PASSWORD + [("enter",), ("enter",)]
    final = session.read_screen()
    assert recognize(final, load_bundled_signatures()) == "ispf-primary-menu"
    assert result.audit[-1].status == "ok"
    assert result.audit[-1].signature == "ispf-primary-menu"
    _assert_no_leak(result, error, log_records)


def test_recovery_logon_audit_of_steps_7_to_18(log_records):
    result, error, _ = _run(_recovery_screens())
    assert error is None
    by_index = {r.step_index: r for r in result.audit if r.phase == "steps"}
    for i in range(7, 19):
        assert by_index[i].status == "ok", i
    assert by_index[7].signature == "tso-userid-in-use"
    assert by_index[12].signature == "tso-reconnect-password-prompt"
    assert by_index[15].signature == "tso-reconnect-ok"
    assert by_index[17].signature == "tso-pause"
    for i in (8, 9, 10, 11, 16, 18):
        assert by_index[i].iteration == 1, i
    assert [by_index[i].kind for i in (8, 9, 10, 11)] == ["type", "type", "type", "key"]


@pytest.mark.parametrize(
    "name, screens, reason, calls",
    [
        (
            "loop_limit",
            [capture("tk5-logon"), capture("tso-userid-in-use"), capture("tso-userid-in-use")],
            "loop_limit",
            CALLS_TO_RECONNECT,
        ),
        (
            "second_in_use_after_command",
            [capture("tk5-logon"), capture("tso-userid-in-use"), second_in_use_screen()],
            "unknown_screen",
            CALLS_TO_RECONNECT,
        ),
        (
            "blank_after_password",
            [
                capture("tk5-logon"),
                capture("tso-userid-in-use"),
                capture("tso-reconnect-password-prompt"),
                blank_screen(),
            ],
            "unknown_screen",
            CALLS_TO_PASSWORD,
        ),
        (
            "blank_after_reconnect_ok_enter",
            [
                capture("tk5-logon"),
                capture("tso-userid-in-use"),
                capture("tso-reconnect-password-prompt"),
                capture("tso-reconnect-ok"),
                blank_screen(),
            ],
            "unknown_screen",
            CALLS_TO_PASSWORD + [("enter",)],
        ),
        (
            "second_in_use_directly",
            [capture("tk5-logon"), second_in_use_screen()],
            "unknown_screen",
            [("string", USERID), ("enter",)],
        ),
    ],
)
def test_stop_cases_send_nothing_after_the_stop(name, screens, reason, calls, log_records):
    result, error, session = _run(screens)
    assert result is None, name
    assert error.reason == reason, name
    assert _keys(session) == calls, name
    _assert_no_leak(result, error, log_records)


# --------------------------------------------------------------------------
# secret_target (task 6.2)
# --------------------------------------------------------------------------

def _visible_reconnect_prompt():
    """The reconnect prompt capture with its hidden field made visible (c0 cc -> c8)."""
    screen = capture("tso-reconnect-password-prompt")
    token = screen.cell_grid[3][0]
    assert isinstance(token, SFToken) and token.c0 == 0xCC
    screen.cell_grid[3][0] = SFToken(0xC8)
    assert not any(f.hidden for f in screen.fields)
    return screen


def _visible_prompt_screens():
    return [capture("tk5-logon"), capture("tso-userid-in-use"), _visible_reconnect_prompt()]


def _row2_only_signatures():
    """Bundled Signatures with a test-only reconnect prompt Signature (row-2 regex alone)."""
    test_only = ScreenSignature(
        "tso-reconnect-password-prompt",
        (
            RegionRegexMatcher(
                2, 0, 80, r"^ IKJ56714A ENTER CURRENT PASSWORD FOR [^ ]{1,8}- *$"
            ),
        ),
    )
    return [
        test_only if s.name == "tso-reconnect-password-prompt" else s
        for s in load_bundled_signatures()
    ]


def _password_typed(session) -> bool:
    return any(c[0] == "string" and c[1] == SENTINEL for c in session.calls)


def test_visible_reconnect_prompt_stops_at_the_expect_step_with_bundled_signatures(log_records):
    result, error, session = _run(_visible_prompt_screens())
    assert result is None
    assert error.reason == "unknown_screen"
    assert _keys(session) == CALLS_TO_RECONNECT
    assert _password_typed(session) is False
    _assert_no_leak(result, error, log_records)


def test_visible_reconnect_prompt_with_test_only_signature_stops_with_secret_target(log_records):
    flow = load_bundled_flows()["tk5-logon"]
    session = ScriptedSession(_states(*_visible_prompt_screens()), echo_typing=True)
    error = None
    result = None
    try:
        result = run_flow(
            flow,
            session,
            {"userid": USERID, "password": SENTINEL},
            signatures=_row2_only_signatures(),
            clock=FakeClock(),
            poll_interval=POLL,
        )
    except FlowError as exc:
        error = exc
    assert result is None
    assert error is not None and error.reason == "secret_target"
    assert _keys(session) == CALLS_TO_RECONNECT
    assert _password_typed(session) is False
    _assert_no_leak(result, error, log_records)
