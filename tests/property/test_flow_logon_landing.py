# Feature: more-flows, Property 8: A logon landing after a reconnect is released or continued, and nothing else is sent
"""Property 8 of the more-flows spec: the landing after a reconnect (task 6.3).

The account was left logged on, so the logon reconnects. After the password the
host shows 0 to 9 further ``***`` pauses and then one landing: the ISPF menu,
``READY``, the cleared screen or the REENTER prompt. The userid and password
are fake.
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    capture,
    pause_variant,
)
from tests.screen_support import reconnect_pause_screen

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"  # fake password

CALLS_TO_PASSWORD = [
    ("string", USERID),
    ("enter",),
    ("string", "LOGON "),
    ("string", USERID),
    ("string", " RECONNECT"),
    ("enter",),
    ("string", SENTINEL),
    ("enter",),
]

# landing -> (screens shown after the landing screen, keys the Flow sends after it)
_LOGOFF = [("string", "LOGOFF"), ("enter",)]
LANDINGS = {
    "menu": ([], []),
    "ready": ([capture("tso-cleared"), capture("tk5-logon")], [("clear",)] + _LOGOFF),
    "cleared": ([capture("tk5-logon")], _LOGOFF),
    "reenter": (
        [
            capture("tso-listds-reenter-after-pa1"),
            capture("tso-cleared"),
            capture("tk5-logon"),
        ],
        [("pa", 1), ("clear",)] + _LOGOFF,
    ),
}
LANDING_SCREEN = {
    "menu": "ispf-primary-menu",
    "ready": "tso-ready",
    "cleared": "tso-cleared",
    "reenter": "tso-listds-reenter",
}


def _screens(landing: str, pauses: int):
    after, _ = LANDINGS[landing]
    return (
        [
            capture("tk5-logon"),
            capture("tso-userid-in-use"),
            capture("tso-reconnect-password-prompt"),
            capture("tso-reconnect-ok"),
            reconnect_pause_screen(),
        ]
        + [pause_variant(i) for i in range(pauses)]
        + [capture(LANDING_SCREEN[landing])]
        + after
    )


@settings(max_examples=100, deadline=None)
@given(
    landing=st.sampled_from(sorted(LANDINGS)),
    pauses=st.integers(min_value=0, max_value=9),
    data=st.data(),
)
def test_landing_is_released_or_continued_and_nothing_else_is_sent(landing, pauses, data):
    """**Validates: Requirements 22.3, 22.4, 22.5, 22.9**"""
    screens = _screens(landing, pauses)
    stale = data.draw(
        st.lists(
            st.integers(min_value=0, max_value=2),
            min_size=len(screens),
            max_size=len(screens),
        )
    )
    states = [ScriptedState(s, stale_reads=n) for s, n in zip(screens, stale)]
    session = ScriptedSession(states, echo_typing=True)
    flow = load_bundled_flows()["tk5-logon"]

    result, error = None, None
    try:
        result = run_flow(
            flow,
            session,
            {"userid": USERID, "password": SENTINEL},
            clock=FakeClock(),
            poll_interval=0.25,
        )
    except FlowError as exc:
        error = exc

    keys = [c for c in session.calls if c[0] != "read"]
    cleanup = LANDINGS[landing][1]
    # Password Enter, reconnect message Enter, one Enter per pause: 3 + p Enters.
    assert keys == CALLS_TO_PASSWORD + [("enter",)] * (2 + pauses) + cleanup

    if landing == "menu":
        assert error is None
        assert recognize(session.read_screen(), load_bundled_signatures()) == (
            "ispf-primary-menu"
        )
    else:
        assert result is None
        assert error.reason == "unexpected_screen"
        assert error.step_index == 26
        assert list(error.expected) == ["ispf-primary-menu"]
        last = None
        for _ in range(3):  # drain stale copies queued behind the last screen
            last = session.read_screen()
        assert recognize(last, load_bundled_signatures()) == "tk5-logon"
