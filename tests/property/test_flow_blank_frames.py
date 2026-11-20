# Feature: more-flows, Property 12: Transient blank frames change neither the keys, the strings nor the outcome
"""Property 12 of the more-flows spec: transient blank frames change nothing (task 6.8).

Every bundled Flow, by manifest name, runs its normal-path script twice: once
as is, once with 0 to 3 blank frames of 6 to 43 ms after every key. The blank
frame is the real ``tso-cleared`` capture, as the host shows it for a moment.
The userid and password are fake. A bundled Flow with no script here fails the
completeness test; the registry holds all eight bundled Flows (task 8.7).
"""
from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError
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
_LOGON = (
    lambda: capture("tk5-logo"),
    lambda: capture("tk5-logon"),
    lambda: capture("tso-password-prompt"),
    lambda: pause_variant(0),
    lambda: pause_variant(1),
    lambda: capture("ispf-primary-menu"),
)

# Flow name -> (inputs, factories of the screens shown, the first one before any key).
SCRIPTS = {
    "tk5-logon": (
        {"userid": USERID, "password": SENTINEL},
        _LOGON,
    ),
    "tk5-logoff": (
        {},
        (
            lambda: capture("ispf-primary-menu"),
            lambda: capture("tso-ready"),
            lambda: capture("tk5-logon"),
        ),
    ),
    "tk5-system-info": (
        {"userid": USERID, "password": SENTINEL},
        _LOGON
        + (
            lambda: capture("tso-ready"),
            lambda: capture("tk5-logon"),
        ),
    ),
}

DSN = "SYS2.JCLLIB"
_MEMBER_PAGES = ("tso-listds-members",) + tuple(
    f"tso-listds-members-page{i}" for i in range(2, 8)
)


def _command(screens, extra_inputs=None):
    """Normal path of a Command_Flow: logon, X, Clear, the command's screens, Clear, LOGOFF."""
    inputs = {"userid": USERID, "password": SENTINEL, **(extra_inputs or {})}
    factories = (
        _LOGON
        + (
            lambda: capture("tso-ready"),
            lambda: capture("tso-cleared"),
        )
        + tuple((lambda n=n: capture(n)) for n in screens)
        + (
            lambda: capture("tso-cleared"),
            lambda: capture("tk5-logon"),
        )
    )
    return inputs, factories


SCRIPTS.update(
    {
        "tk5-time": _command(["tso-time-output"]),
        "tk5-list-datasets": _command(["tso-listcat-output"]),
        "tk5-dataset-info": _command(["tso-listds-output"], {"dsname": DSN}),
        "tk5-library-members": _command(_MEMBER_PAGES, {"dsname": DSN}),
        "tk5-job-status": _command(["tso-status-output"]),
    }
)

EIGHT_BUNDLED_NAMES = (
    "tk5-logon",
    "tk5-logoff",
    "tk5-system-info",
    "tk5-time",
    "tk5-list-datasets",
    "tk5-dataset-info",
    "tk5-library-members",
    "tk5-job-status",
)


def _assert_every_bundled_flow_has_a_script():
    bundled = set(load_bundled_flows())
    assert set(SCRIPTS) == set(EIGHT_BUNDLED_NAMES) and len(SCRIPTS) == 8
    assert bundled == set(EIGHT_BUNDLED_NAMES)
    assert set(SCRIPTS) == bundled, (
        f"no script for {sorted(bundled - set(SCRIPTS))}, "
        f"script for no bundled flow: {sorted(set(SCRIPTS) - bundled)}"
    )


def _run(name, stale, blanks, poll):
    """Run ``name``; ``blanks`` is a list per screen (None for the plain run)."""
    inputs, factories = SCRIPTS[name]
    clock = FakeClock()
    states = []
    for i, make in enumerate(factories):
        states.append(
            ScriptedState(
                make(),
                stale_reads=0 if i == 0 else stale[i],
                blanks=() if blanks is None or i == 0 else tuple(blanks[i]),
            )
        )
    session = ScriptedSession(
        states, echo_typing=True, clock=clock if blanks is not None else None
    )
    flow = load_bundled_flows()[name]
    try:
        result = run_flow(flow, session, dict(inputs), clock=clock, poll_interval=poll)
        error = None
    except FlowError as exc:
        result, error = None, exc
    return session, result, error


def _outcome(result, error):
    if error is None:
        audit = result.audit
        return ("ok", dict(result.outputs)), _audit(audit)
    return (
        ("error", error.reason, error.step_index, error.kind),
        _audit(error.audit),
    )


def _audit(records):
    return [(r.step_index, r.status, r.signature) for r in records]


def _non_reads(session):
    return [c for c in session.calls if c[0] != "read"]


def _reads(session):
    return sum(1 for c in session.calls if c[0] == "read")


@settings(max_examples=150, deadline=None)
@given(
    name=st.sampled_from(sorted(SCRIPTS)),
    poll=st.sampled_from([0.01, 0.05, 0.1, 0.5]),
    data=st.data(),
)
def test_transient_blank_frames_change_neither_keys_nor_strings_nor_outcome(
    name, poll, data
):
    """**Validates: Requirements 24.5, 24.9, 24.11, 24.12**"""
    _assert_every_bundled_flow_has_a_script()
    n = len(SCRIPTS[name][1])
    stale = data.draw(
        st.lists(st.integers(min_value=0, max_value=2), min_size=n, max_size=n)
    )
    blanks = data.draw(
        st.lists(
            st.lists(
                st.floats(min_value=0.006, max_value=0.043),
                min_size=0,
                max_size=3,
            ),
            min_size=n,
            max_size=n,
        )
    )

    base_session, base_result, base_error = _run(name, stale, None, poll)
    blank_session, blank_result, blank_error = _run(name, stale, blanks, poll)

    assert _outcome(blank_result, blank_error) == _outcome(base_result, base_error)
    base_keys = _non_reads(base_session)
    assert _non_reads(blank_session) == base_keys
    assert _reads(blank_session) >= _reads(base_session)
    if ("string", "LOGOFF") not in base_keys:
        assert ("string", "LOGOFF") not in _non_reads(blank_session)
