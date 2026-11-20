"""The stable-blank rule in the Runner (more-flows task 6.7; Requirements 24.5 to 24.16).

Uses ``ScriptedSession`` with timed blank frames and ``FakeClock``. Needs no live
host. The Settle_Time is read from the loaded ``tso-cleared`` signature, never
written here. The userid and password are obviously fake values.
"""
from __future__ import annotations

import math

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import (
    CollectStep,
    ExpectStep,
    Flow,
    HandleStep,
    KeyStep,
    OutputSpec,
    Timeouts,
    TypeStep,
    plan,
)
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    blank_screen,
    capture,
    has_partial_repaint,
    partial_repaint,
    pause_variant,
)
from tests.screen_support import reconnect_pause_screen

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"  # fake password, 8 characters
INPUTS = {"userid": USERID, "password": SENTINEL}

SIGS = load_bundled_signatures()
SETTLE = next(s.stable_for for s in SIGS if s.name == "tso-cleared")
EPS = 1e-9
POLLS = (0.01, 0.1, 0.5)
T = Timeouts(step=10.0, run=600.0, finally_=30.0)

# Names a test-only Flow lists so that its Runner can recognize them (only referenced
# signatures are loaded). The cleared screen must be known for the rule to apply to it.
KNOWN_AFTER = ("ispf-primary-menu", "tk5-logon", "tso-cleared")
ENTER = ("enter",)
CLEAR = ("clear",)
LOGOFF = ("string", "LOGOFF")

GOLDEN_LOGON = [
    ("string", USERID), ENTER,
    ("string", SENTINEL), ENTER, ENTER, ENTER,
]
GOLDEN_SYSTEM_INFO = GOLDEN_LOGON + [
    ("string", "X"), ENTER, ("string", "LOGOFF"), ENTER,
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

class TimedSession(ScriptedSession):
    """A ScriptedSession that remembers the Clock reading of every call."""

    def __init__(self, states, clock, **kw):
        super().__init__(states, clock=clock, **kw)
        self.stamp_clock = clock
        self.times: list[float] = []

    def _stamp(self) -> None:
        self.times.append(self.stamp_clock.monotonic())

    def read_screen(self):
        self._stamp()
        return super().read_screen()

    def string(self, text):
        self._stamp()
        super().string(text)

    def enter(self):
        self._stamp()
        super().enter()

    def clear(self):
        self._stamp()
        super().clear()

    def pf(self, n):
        self._stamp()
        super().pf(n)

    def pa(self, n):
        self._stamp()
        super().pa(n)


def keys(session) -> list[tuple]:
    return [c for c in session.calls if c[0] != "read"]


def reads(session) -> int:
    return sum(1 for c in session.calls if c[0] == "read")


def run(flow, states, poll, *, inputs=None, echo=False):
    clock = FakeClock()
    session = TimedSession(states, clock, echo_typing=echo)
    try:
        result = run_flow(
            flow, session, inputs or {}, signatures=SIGS, clock=clock, poll_interval=poll
        )
        return result, None, session, clock
    except FlowError as exc:
        return None, exc, session, clock


def first_read_after(session, call) -> float:
    """Clock reading of the first read that follows the first ``call``."""
    i = session.calls.index(call)
    j = next(k for k in range(i + 1, len(session.calls)) if session.calls[k] == ("read",))
    return session.times[j]


def time_of(session, call, *, after: tuple | None = None) -> float:
    start = 0 if after is None else session.calls.index(after) + 1
    i = next(k for k in range(start, len(session.calls)) if session.calls[k] == call)
    return session.times[i]


def _ready():
    return ScriptedState(capture("tso-ready"))


def _expect_flow() -> Flow:
    """READY, Clear, wait for the cleared screen, then log off."""
    return Flow(
        "blank-expect",
        (
            ExpectStep(("tso-ready",), tolerate=KNOWN_AFTER),
            KeyStep("clear"),
            ExpectStep(("tso-cleared",)),
            TypeStep(text="LOGOFF"),
            KeyStep("enter"),
        ),
        timeouts=T,
    )


def _handle_flow() -> Flow:
    """READY, Clear, then a Handle on the cleared screen whose body logs off."""
    return Flow(
        "blank-handle",
        (
            ExpectStep(("tso-ready",), tolerate=KNOWN_AFTER),
            KeyStep("clear"),
            HandleStep("tso-cleared", 1, (TypeStep(text="LOGOFF"), KeyStep("enter"))),
        ),
        timeouts=T,
    )


# --------------------------------------------------------------------------
# (a) The live failure, exactly
# --------------------------------------------------------------------------

def _logon_states(blank: float | None, stale: int, *, system_info: bool):
    states = [
        ScriptedState(capture("tk5-logon")),
        ScriptedState(
            capture("tso-password-prompt"),
            stale_reads=stale,
            blanks=() if blank is None else (blank,),
        ),
        ScriptedState(pause_variant(0), stale_reads=stale),
        ScriptedState(pause_variant(1), stale_reads=stale),
        ScriptedState(capture("ispf-primary-menu"), stale_reads=stale),
    ]
    if system_info:
        states += [
            ScriptedState(capture("tso-ready"), stale_reads=stale),
            ScriptedState(capture("tk5-logon"), stale_reads=stale),
        ]
    return states


@pytest.mark.parametrize("stale", [0, 1, 2])
@pytest.mark.parametrize("poll", POLLS)
@pytest.mark.parametrize(
    "flow_name, golden",
    [("tk5-logon", GOLDEN_LOGON), ("tk5-system-info", GOLDEN_SYSTEM_INFO)],
)
def test_the_live_failure_a_6_ms_blank_after_the_logon_enter(flow_name, golden, poll, stale):
    flow = load_bundled_flows()[flow_name]
    system_info = flow_name == "tk5-system-info"
    result, error, session, _ = run(
        flow, _logon_states(0.006, stale, system_info=system_info), poll,
        inputs=INPUTS, echo=True,
    )
    assert error is None, getattr(error, "reason", None)
    assert keys(session) == golden
    assert result.audit[-1].status == "ok"
    assert result.audit[-1].signature == ("tk5-logon" if system_info else "ispf-primary-menu")
    if system_info:
        assert len(result.outputs) == 4
    # The blank costs extra reads only (none when a stale read already outlasted it).
    _, _, baseline, _ = run(
        flow, _logon_states(None, stale, system_info=system_info), poll,
        inputs=INPUTS, echo=True,
    )
    assert keys(baseline) == golden
    assert reads(session) >= reads(baseline)
    if stale == 0:
        assert reads(session) > reads(baseline)
    assert SENTINEL not in repr(result) and SENTINEL not in repr(result.audit)


# --------------------------------------------------------------------------
# (b) A blank that stays is accepted after the Settle_Time
# --------------------------------------------------------------------------

def _stays_states():
    return [_ready(), ScriptedState(capture("tso-cleared")), ScriptedState(capture("tk5-logon"))]


@pytest.mark.parametrize("poll", POLLS)
def test_a_blank_that_stays_is_accepted_by_expect_after_the_settle_time(poll):
    _, error, session, clock = run(_expect_flow(), _stays_states(), poll)
    assert error is None
    assert keys(session) == [CLEAR, LOGOFF, ENTER]
    first = first_read_after(session, CLEAR)
    accepted = time_of(session, LOGOFF)
    assert SETTLE - EPS <= accepted - first <= SETTLE + poll + EPS


@pytest.mark.parametrize("poll", POLLS)
def test_a_blank_that_stays_is_accepted_by_a_handle_after_the_settle_time(poll):
    _, error, session, clock = run(_handle_flow(), _stays_states(), poll)
    assert error is None
    assert keys(session) == [CLEAR, LOGOFF, ENTER]
    first = first_read_after(session, CLEAR)
    accepted = time_of(session, LOGOFF)
    assert SETTLE - EPS <= accepted - first <= SETTLE + poll + EPS


@pytest.mark.parametrize("poll", POLLS)
def test_the_added_delay_is_the_first_poll_tick_at_or_after_the_settle_time(poll):
    """The figure for the report: the smallest multiple of the poll interval >= Settle_Time."""
    _, _, session, _ = run(_expect_flow(), _stays_states(), poll)
    advance = time_of(session, LOGOFF) - first_read_after(session, CLEAR)
    ticks = math.ceil(SETTLE / poll - 1e-6)
    assert advance == pytest.approx(ticks * poll, abs=poll * 0.6)
    assert advance < SETTLE + poll + EPS


@pytest.mark.parametrize("poll", POLLS)
def test_a_blank_that_stays_after_a_transient_prefix_still_waits_from_its_first_read(poll):
    states = [
        _ready(),
        ScriptedState(capture("tso-cleared"), blanks=(0.043,)),
        ScriptedState(capture("tk5-logon")),
    ]
    _, error, session, _ = run(_expect_flow(), states, poll)
    assert error is None
    first = first_read_after(session, CLEAR)
    assert SETTLE - EPS <= time_of(session, LOGOFF) - first <= SETTLE + poll + EPS


# --------------------------------------------------------------------------
# (c) A blank that changes inside the Settle_Time is never accepted
# --------------------------------------------------------------------------

# final screen -> (reason through expect, reason through a Handle or None for success)
FINALS = {
    "same-as-pre-key": (lambda: capture("tso-ready"), "timeout", "timeout"),
    "unknown": (blank_screen, "unknown_screen", "unknown_screen"),
    "other-known": (lambda: capture("ispf-primary-menu"), "unexpected_screen", None),
}


def _after_clear_state(kind: str, final):
    """The state after Clear. ``kind`` is the shape of the blank."""
    if kind == "short-blank":  # one 0.25 s blank, below the Settle_Time
        assert 0.25 < SETTLE
        return ScriptedState(final, blanks=(0.25,))
    if kind == "returns":  # the blank comes back after a different screen, several times
        other = capture("tso-ready")
        cleared = capture("tso-cleared")
        frames = [cleared, other] * 4 + [cleared]
        return ScriptedState(final, repaints=tuple(frames))
    raise AssertionError(kind)


@pytest.mark.parametrize("poll", POLLS)
@pytest.mark.parametrize("final_name", list(FINALS))
@pytest.mark.parametrize("kind", ["short-blank", "returns"])
def test_a_changing_blank_is_never_accepted_by_expect(kind, final_name, poll):
    make, reason, _ = FINALS[final_name]
    states = [_ready(), _after_clear_state(kind, make())]
    result, error, session, _ = run(_expect_flow(), states, poll)
    assert result is None
    assert error.reason == reason
    assert keys(session) == [CLEAR]
    assert LOGOFF not in keys(session)


@pytest.mark.parametrize("poll", POLLS)
@pytest.mark.parametrize("final_name", list(FINALS))
@pytest.mark.parametrize("kind", ["short-blank", "returns"])
def test_a_changing_blank_is_never_accepted_by_a_handle(kind, final_name, poll):
    make, _, reason = FINALS[final_name]
    states = [_ready(), _after_clear_state(kind, make())]
    result, error, session, _ = run(_handle_flow(), states, poll)
    assert keys(session) == [CLEAR]
    assert LOGOFF not in keys(session)
    if reason is None:
        assert error is None
        assert [r.status for r in result.audit[-2:]] == ["skipped", "skipped"]
    else:
        assert error.reason == reason


@pytest.mark.parametrize("poll", POLLS)
@pytest.mark.parametrize("kind", ["short-blank", "returns"])
def test_the_span_restarts_on_every_change_not_only_the_first_read(kind, poll):
    """Reads of the blank are far apart in time but never consecutive: none is accepted."""
    final = capture("ispf-primary-menu")
    states = [_ready(), _after_clear_state(kind, final)]
    _, error, session, _ = run(_expect_flow(), states, poll)
    assert error.reason == "unexpected_screen"  # the menu is the first thing accepted or refused
    assert error.expected == ("tso-cleared",)


def _settle_flow() -> Flow:
    # After Enter the handled screen is READY. The body presses Enter, so a second
    # Enter shows that the settle watch ended on READY and not on the blank.
    return Flow(
        "blank-settle",
        (
            ExpectStep(("tso-ready",), tolerate=KNOWN_AFTER),
            KeyStep("enter"),
            HandleStep("tso-ready", 20, (KeyStep("enter"),), settle=0.6),
        ),
        timeouts=Timeouts(step=10.0, run=600.0, finally_=30.0),
    )


@pytest.mark.parametrize("poll", POLLS)
def test_a_changing_blank_is_never_accepted_by_the_settle_watch(poll):
    assert has_partial_repaint("tso-ready")
    # The settle watch reads about 0.6 / poll screens; the flicker is no longer than that,
    # so the watch consumes all of it and ends on the READY screen served afterwards.
    pairs = int(0.6 / poll) // 2
    flicker = [capture("tso-cleared"), capture("tso-ready")] * pairs
    states = [
        _ready(),
        ScriptedState(
            capture("tso-ready"),
            repaints=(partial_repaint("tso-ready", 0), *flicker),
        ),
        ScriptedState(capture("tk5-logon")),
    ]
    result, error, session, _ = run(_settle_flow(), states, poll)
    assert error is None, getattr(error, "reason", None)
    # The first Enter leaves READY; the second is the Handle body, which runs only if
    # the watch ended on READY (a blank accepted as tso-cleared would skip the body).
    assert keys(session) == [ENTER, ENTER]
    assert [r.status for r in result.audit if r.step_index == 3] == ["ok"]


# collect: a blank between two pages is waited through

_LEVEL_OUT = OutputSpec(
    "LINES", "str", "tso-ready", row=1, col=1, length=79, next_row=0, max_rows=100
)


def _collect_flow() -> Flow:
    return Flow(
        "blank-collect",
        (ExpectStep(("tso-ready", "tso-pause"), tolerate=("tso-cleared",)), CollectStep("LINES", "tso-pause", 5)),
        outputs=(_LEVEL_OUT,),
        timeouts=T,
    )


def _pages(page2_extra: dict, page3_extra: dict):
    return [
        ScriptedState(capture("tso-listcat-level")),
        ScriptedState(capture("tso-listcat-level-page2"), **page2_extra),
        ScriptedState(capture("tso-listcat-level-page3"), **page3_extra),
    ]


@pytest.mark.parametrize("poll", POLLS)
def test_a_blank_between_two_pages_is_waited_through_by_collect(poll):
    base, error, base_session, _ = run(_collect_flow(), _pages({}, {}), poll)
    assert error is None
    assert keys(base_session) == [ENTER, ENTER]
    lines = base.outputs["LINES"].split("\n")
    assert len(lines) == 50

    variants = [
        ({"blanks": (0.006,)}, {"blanks": (0.043,)}),
        ({"blanks": (0.25,)}, {"blanks": (0.25,)}),
        (
            {"repaints": (capture("tso-cleared"), capture("tso-listcat-level"),
                          capture("tso-cleared"))},
            {"repaints": (capture("tso-cleared"),), "blanks": (0.2,)},
        ),
    ]
    for page2, page3 in variants:
        result, error, session, _ = run(_collect_flow(), _pages(page2, page3), poll)
        assert error is None, error.reason
        assert result.outputs == base.outputs
        assert keys(session) == [ENTER, ENTER]
        assert result.audit[-1].kind == "collect"


# --------------------------------------------------------------------------
# (d) The logon landing never types LOGOFF into a transient blank
# --------------------------------------------------------------------------

CALLS_TO_PASSWORD = [
    ("string", USERID),
    ENTER,
    ("string", "LOGON "),
    ("string", USERID),
    ("string", " RECONNECT"),
    ENTER,
    ("string", SENTINEL),
    ENTER,
]


def _reconnect_states(flow_name, stale, where, blank, landing="menu"):
    on_pause = (blank,) if where in ("pause", "both") and blank else ()
    on_landing = (blank,) if where in ("landing", "both") and blank else ()
    states = [
        ScriptedState(capture("tk5-logon")),
        ScriptedState(capture("tso-userid-in-use")),
        ScriptedState(capture("tso-reconnect-password-prompt")),
        ScriptedState(capture("tso-reconnect-ok"), stale_reads=stale),
        ScriptedState(reconnect_pause_screen(), stale_reads=stale, blanks=on_pause),
    ]
    if landing == "menu":
        states.append(
            ScriptedState(capture("ispf-primary-menu"), stale_reads=stale, blanks=on_landing)
        )
        if flow_name == "tk5-system-info":
            states += [
                ScriptedState(capture("tso-ready"), stale_reads=stale),
                ScriptedState(capture("tk5-logon"), stale_reads=stale),
            ]
    elif landing == "cleared":
        states += [
            ScriptedState(capture("tso-cleared"), stale_reads=stale, blanks=on_landing),
            ScriptedState(capture("tk5-logon"), stale_reads=stale),
        ]
    else:
        raise AssertionError(landing)
    return states


@pytest.mark.parametrize("poll", [0.01, 0.1])
@pytest.mark.parametrize("stale", [0, 1, 2])
@pytest.mark.parametrize("blank", [0.006, 0.043])
@pytest.mark.parametrize("where", ["pause", "landing", "both"])
@pytest.mark.parametrize("flow_name", ["tk5-logon", "tk5-system-info"])
def test_a_blank_after_the_reconnect_message_or_a_pause_never_types_logoff(
    flow_name, where, blank, stale, poll
):
    flow = load_bundled_flows()[flow_name]
    _, base_error, base, _ = run(
        flow, _reconnect_states(flow_name, stale, where, None), poll, inputs=INPUTS, echo=True
    )
    assert base_error is None
    result, error, session, _ = run(
        flow, _reconnect_states(flow_name, stale, where, blank), poll, inputs=INPUTS, echo=True
    )
    assert error is None, getattr(error, "reason", None)
    assert keys(session) == keys(base) == CALLS_TO_PASSWORD + [ENTER, ENTER] + (
        [("string", "X"), ENTER, LOGOFF, ENTER] if flow_name == "tk5-system-info" else []
    )
    if flow_name == "tk5-logon":
        assert LOGOFF not in keys(session)
    else:
        assert keys(session).count(LOGOFF) == 1
    assert reads(session) >= reads(base)
    assert SENTINEL not in repr(result) and SENTINEL not in repr(result.audit)


@pytest.mark.parametrize("poll", [0.1, 0.25])
@pytest.mark.parametrize("blank", [None, 0.043])
@pytest.mark.parametrize("flow_name", ["tk5-logon", "tk5-system-info"])
def test_a_genuine_cleared_landing_still_types_logoff_and_enter(flow_name, blank, poll):
    flow = load_bundled_flows()[flow_name]
    states = _reconnect_states(flow_name, 0, "landing", blank, landing="cleared")
    result, error, session, _ = run(flow, states, poll, inputs=INPUTS, echo=True)
    assert result is None
    assert error.reason == "unexpected_screen"
    assert error.step_index == 26
    assert list(error.expected) == ["ispf-primary-menu"]
    assert keys(session) == CALLS_TO_PASSWORD + [ENTER, ENTER, LOGOFF, ENTER]


# --------------------------------------------------------------------------
# (e) A cleared Current_Screen needs no second span before the next key
# --------------------------------------------------------------------------

@pytest.mark.parametrize("poll", POLLS)
def test_the_key_after_expect_cleared_is_sent_after_one_span_not_two(poll):
    _, error, session, _ = run(_expect_flow(), _stays_states(), poll)
    assert error is None
    first = first_read_after(session, CLEAR)
    typed = time_of(session, LOGOFF)
    pressed = time_of(session, ENTER)
    assert SETTLE - EPS <= typed - first <= SETTLE + poll + EPS
    # No wait between the typed text and the Enter: the pre-key read is accepted at once.
    assert pressed == typed
    assert pressed - first < 2 * SETTLE


# --------------------------------------------------------------------------
# (f) No bundled Flow can give the rule too little time
# --------------------------------------------------------------------------

def _all_items(items):
    for item in items:
        yield item
        yield from _all_items(item.children)


def test_no_bundled_expect_of_the_cleared_screen_has_a_timeout_below_one_second():
    seen = 0
    for name, flow in load_bundled_flows().items():
        assert flow.timeouts.step >= 1.0, name
        main, fin = plan(flow)
        for item in _all_items(main + fin):
            step = item.step
            if isinstance(step, ExpectStep) and "tso-cleared" in step.signatures + step.tolerate:
                seen += 1
                effective = step.timeout if step.timeout is not None else flow.timeouts.step
                assert effective >= 1.0, (name, item.index)
                assert effective > SETTLE + 0.5, (name, item.index)
            if isinstance(step, HandleStep) and step.signature == "tso-cleared":
                seen += 1
    assert seen >= 1  # the logon Flows hold the cleared Handle


# --------------------------------------------------------------------------
# (g) Two genuine cleared screens per Command_Flow, once they are bundled
# --------------------------------------------------------------------------

COMMAND_FLOWS = {  # name -> legitimate worst figure of Requirement 16.4 (seconds)
    "tk5-time": 12.0,
    "tk5-list-datasets": 12.0,
    "tk5-dataset-info": 12.0,
    "tk5-library-members": 18.0,  # 10 screens; 17.0 with 7
    "tk5-job-status": 12.0,
}
POLL_DEFAULT = 0.1  # the Publisher's poll interval


def test_each_command_flow_holds_two_cleared_expects_and_fits_its_run_limit():
    bundled = load_bundled_flows()
    missing = [n for n in COMMAND_FLOWS if n not in bundled]
    if missing:
        pytest.skip("the five Command_Flows are not bundled before task 8.7")
    added = 2 * (SETTLE + POLL_DEFAULT)  # 0.8 s with the shipped values
    for name, worst in COMMAND_FLOWS.items():
        flow = bundled[name]
        main, _ = plan(flow)
        cleared = [
            i for i in _all_items(main)
            if isinstance(i.step, ExpectStep) and i.step.signatures == ("tso-cleared",)
        ]
        assert len(cleared) == 2, name
        assert worst + added <= flow.timeouts.run, name
