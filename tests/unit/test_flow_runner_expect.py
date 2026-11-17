"""Expect_Step and polling of ``run_flow`` (flow-runtime task 10.5).

Covers Requirements 8.1 to 8.8, 8.12, 8.13, 8.15, 8.16, 8.20, 8.21, 12.1, 12.5,
18.7, 18.13, 18.14 and 18.15. Every Session is scripted and every clock is fake.
"""
from __future__ import annotations

import dataclasses

import pytest

from greenscreen.flow import runner as runner_module
from greenscreen.flow.errors import FlowDefinitionError, FlowError
from greenscreen.flow.model import ExpectStep, Flow, KeyStep
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import SignatureError, load_bundled_signatures
from greenscreen.recognizer.summary import RedactedSummary

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    blank_screen,
    capture,
    copy_screen,
    partial_repaint,
)

POLL = 0.25


class ReadSession:
    """Serves ``screens`` one per read (the last one repeats) and logs every call."""

    def __init__(self, screens):
        self._screens = list(screens)
        self._i = 0
        self.calls: list[tuple] = []

    def read_screen(self):
        self.calls.append(("read",))
        screen = self._screens[min(self._i, len(self._screens) - 1)]
        self._i += 1
        return copy_screen(screen)

    def string(self, text):
        self.calls.append(("string", text))

    def enter(self):
        self.calls.append(("enter",))

    def clear(self):
        self.calls.append(("clear",))

    def pf(self, n):
        self.calls.append(("pf", n))

    def pa(self, n):
        self.calls.append(("pa", n))

    def close(self):
        self.calls.append(("close",))


@pytest.fixture
def recognize_calls(monkeypatch):
    """Count the runner's calls of ``recognize`` (the real function still runs)."""
    real = runner_module.recognize
    count = [0]

    def counting(screen, sigs):
        count[0] += 1
        return real(screen, sigs)

    monkeypatch.setattr(runner_module, "recognize", counting)
    return count


def _run(flow, session, clock=None, **kw):
    clock = clock or FakeClock()
    return run_flow(flow, session, {}, clock=clock, poll_interval=POLL, **kw), clock


def _fail(flow, session, clock=None, **kw):
    clock = clock or FakeClock()
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=clock, poll_interval=POLL, **kw)
    return info.value, clock


def _reads(session):
    return sum(1 for c in session.calls if c == ("read",))


def _keys(session):
    return [c for c in session.calls if c[0] in ("enter", "clear", "pf", "pa")]


def _expect_flow(*signatures, tolerate=(), timeout=1.0, extra=()):
    """One Expect_Step; ``extra`` names are referenced by a later Step so they are loaded."""
    steps = [ExpectStep(signatures, tolerate, timeout)]
    if extra:
        steps.append(ExpectStep(tuple(extra), (), timeout))
    return Flow("t", tuple(steps))


# 1.0 s timeout at 0.25 s polling: reads at 0, .25, .5, .75 and 1.0 (five reads, four sleeps).
FIVE_READS = 5


def test_accepted_name_takes_one_read_one_recognize_and_no_sleep(recognize_calls):
    session = ReadSession([capture("tk5-logon")])
    result, clock = _run(_expect_flow("tk5-logon"), session)
    assert _reads(session) == 1
    assert recognize_calls[0] == 1
    assert clock.sleeps == []
    assert result.audit[0].status == "ok"
    assert result.audit[0].signature == "tk5-logon"
    assert _keys(session) == []


def test_each_attempt_is_one_read_and_one_recognize_with_a_sleep_between(recognize_calls):
    session = ReadSession([blank_screen(), blank_screen(), capture("tk5-logon")])
    result, clock = _run(_expect_flow("tk5-logon"), session)
    assert _reads(session) == 3
    assert recognize_calls[0] == 3
    assert clock.sleeps == [POLL, POLL]
    assert result.audit[0].status == "ok"
    # read and sleep alternate; no read follows the accepted screen
    assert session.calls == [("read",)] * 3


def test_second_name_of_signatures_is_accepted():
    session = ReadSession([capture("tso-ready")])
    result, _ = _run(_expect_flow("tk5-logon", "tso-ready"), session)
    assert result.audit[0].signature == "tso-ready"


def test_tolerated_name_is_polled_past_without_a_key(recognize_calls):
    session = ReadSession([capture("tk5-logo"), capture("tk5-logo"), capture("tk5-logon")])
    result, clock = _run(_expect_flow("tk5-logon", tolerate=("tk5-logo",)), session)
    assert _reads(session) == 3
    assert recognize_calls[0] == 3
    assert clock.sleeps == [POLL, POLL]
    assert _keys(session) == []
    assert result.audit[0].signature == "tk5-logon"


def test_unknown_screen_is_tolerated_until_the_timeout_then_unknown_screen():
    session = ReadSession([blank_screen()])
    err, clock = _fail(_expect_flow("tk5-logon"), session)
    assert err.reason == "unknown_screen"
    assert err.step_index == 0
    assert err.kind == "expect"
    assert err.expected == ("tk5-logon",)
    assert isinstance(err.summary, RedactedSummary)
    assert _reads(session) == FIVE_READS
    assert clock.sleeps == [POLL] * (FIVE_READS - 1)
    assert _keys(session) == []
    assert err.audit[0].status == "failed"


def test_expected_names_are_sorted_in_the_error():
    session = ReadSession([blank_screen()])
    err, _ = _fail(_expect_flow("tso-ready", "tk5-logon", "ispf-primary-menu"), session)
    assert err.expected == ("ispf-primary-menu", "tk5-logon", "tso-ready")
    assert list(err.expected) == sorted(err.expected)


def test_ambiguous_screen_stops_before_any_further_read_or_sleep():
    base = {s.name: s for s in load_bundled_signatures()}["tk5-logon"]
    twin = dataclasses.replace(base, name="tk5-logon-twin")
    sigs = [base, twin]
    flow = _expect_flow("tk5-logon", tolerate=("tk5-logon-twin",))
    session = ReadSession([capture("tk5-logon")])
    err, clock = _fail(flow, session, signatures=sigs)
    assert err.reason == "ambiguous_screen"
    assert err.step_index == 0
    assert err.expected == ("tk5-logon",)
    assert isinstance(err.summary, RedactedSummary)
    assert _reads(session) == 1
    assert clock.sleeps == []
    assert _keys(session) == []


def test_unexpected_screen_stops_before_any_further_read_or_sleep():
    session = ReadSession([capture("tk5-logo"), capture("tk5-logon")])
    err, clock = _fail(_expect_flow("tk5-logon", "tso-ready", extra=("tk5-logo",)), session)
    assert err.reason == "unexpected_screen"
    assert err.step_index == 0
    assert err.expected == ("tk5-logon", "tso-ready")
    assert isinstance(err.summary, RedactedSummary)
    assert _reads(session) == 1
    assert clock.sleeps == []
    assert _keys(session) == []


def test_timeout_after_a_tolerated_name():
    session = ReadSession([capture("tk5-logo")])
    err, clock = _fail(_expect_flow("tk5-logon", tolerate=("tk5-logo",)), session)
    assert err.reason == "timeout"
    assert err.step_index == 0
    assert err.expected == ("tk5-logon",)
    assert isinstance(err.summary, RedactedSummary)
    assert _reads(session) == FIVE_READS
    assert clock.sleeps == [POLL] * (FIVE_READS - 1)
    assert _keys(session) == []


def test_last_read_unknown_after_a_tolerated_one_reports_unknown_screen():
    session = ReadSession([capture("tk5-logo"), blank_screen()])
    err, _ = _fail(_expect_flow("tk5-logon", tolerate=("tk5-logo",)), session)
    assert err.reason == "unknown_screen"


def _logon_then(next_state, extra=()):
    steps = [
        ExpectStep(("tk5-logon",)),
        KeyStep("enter"),
        ExpectStep(("tso-password-prompt",), (), 1.0),
    ]
    if extra:
        steps.append(ExpectStep(tuple(extra)))
    flow = Flow("t", tuple(steps))
    return flow, ScriptedSession([capture("tk5-logon"), next_state])


def test_timeout_after_the_pre_key_name_with_a_changed_screen():
    flow, session = _logon_then(partial_repaint("tk5-logon", 0))
    err, clock = _fail(flow, session)
    assert err.reason == "timeout"  # Requirement 18.14, not unexpected_screen
    assert err.step_index == 2
    assert err.expected == ("tso-password-prompt",)
    assert isinstance(err.summary, RedactedSummary)
    assert _keys(session) == [("enter",)]
    assert clock.sleeps == [POLL] * (FIVE_READS - 1)


def test_timeout_after_a_screen_equal_to_the_pre_key_screen():
    flow, session = _logon_then(capture("tk5-logon"))
    err, clock = _fail(flow, session)
    assert err.reason == "timeout"
    assert err.step_index == 2
    assert err.expected == ("tso-password-prompt",)
    assert isinstance(err.summary, RedactedSummary)
    assert _keys(session) == [("enter",)]
    assert clock.sleeps == [POLL] * (FIVE_READS - 1)


def test_stale_reads_are_no_answer_yet_and_are_not_recognized(recognize_calls):
    flow, session = _logon_then(ScriptedState(capture("tso-password-prompt"), stale_reads=2))
    result, clock = _run(flow, session)
    # Expect 1 read, Key pre-read, then 2 stale reads and the answer.
    assert _reads(session) == 5
    assert clock.sleeps == [POLL, POLL]
    # recognize: first Expect, the key's comparison screen, the answer; none for stale reads
    assert recognize_calls[0] == 3
    assert _keys(session) == [("enter",)]
    assert [r.status for r in result.audit] == ["ok", "ok", "ok"]


def test_partial_repaint_as_pre_key_name_then_expected_screen_adds_no_key():
    state = ScriptedState(
        capture("tso-password-prompt"), repaints=(partial_repaint("tk5-logon", 0),)
    )
    flow, session = _logon_then(state)
    result, clock = _run(flow, session)
    assert _keys(session) == [("enter",)]  # Requirement 18.13
    assert clock.sleeps == [POLL]
    assert result.audit[-1].signature == "tso-password-prompt"


def test_pre_key_name_in_signatures_is_accepted():
    flow = Flow(
        "t",
        (
            ExpectStep(("tk5-logon",)),
            KeyStep("enter"),
            ExpectStep(("tk5-logon",), (), 1.0),
        ),
    )
    session = ScriptedSession([capture("tk5-logon"), partial_repaint("tk5-logon", 0)])
    result, clock = _run(flow, session)
    assert result.audit[-1].signature == "tk5-logon"
    assert result.audit[-1].status == "ok"
    assert clock.sleeps == []
    assert _keys(session) == [("enter",)]


def test_first_expect_before_any_key_has_no_implicit_tolerance():
    # tk5-logo is neither in signatures nor tolerate and no key has been sent.
    session = ReadSession([capture("tk5-logo")])
    err, clock = _fail(_expect_flow("tk5-logon", extra=("tk5-logo",)), session)
    assert err.reason == "unexpected_screen"  # Requirement 18.15
    assert err.step_index == 0
    assert _reads(session) == 1
    assert clock.sleeps == []


def test_pre_key_name_not_tolerated_in_a_later_expect_without_a_key_sent():
    # After the key the screen changes to another name that is not expected.
    flow, session = _logon_then(capture("tso-ready"), extra=("tso-ready",))
    err, clock = _fail(flow, session)
    assert err.reason == "unexpected_screen"
    assert err.step_index == 2
    assert clock.sleeps == []
    assert _keys(session) == [("enter",)]


def test_step_timeout_defaults_to_the_flow_timeouts_step():
    from greenscreen.flow.model import Timeouts

    flow = Flow("t", (ExpectStep(("tk5-logon",)),), timeouts=Timeouts(step=0.5))
    session = ReadSession([blank_screen()])
    err, clock = _fail(flow, session)
    assert err.reason == "unknown_screen"
    assert _reads(session) == 3  # reads at 0, 0.25 and 0.5
    assert clock.sleeps == [POLL, POLL]


class _Boom:
    """Replacement for ``recognize`` that raises ``make()`` from call number ``at``."""

    def __init__(self, real, make, at):
        self.real, self.make, self.at, self.n = real, make, at, 0

    def __call__(self, screen, sigs):
        self.n += 1
        if self.n >= self.at:
            raise self.make()
        return self.real(screen, sigs)


@pytest.mark.parametrize("make", [lambda: SignatureError("bad"), lambda: TypeError("bad")])
def test_recognizer_failure_in_first_expect_raises_definition_error_and_sends_no_key(
    monkeypatch, make
):
    monkeypatch.setattr(
        runner_module, "recognize", _Boom(runner_module.recognize, make, 1)
    )
    flow = Flow("t", (ExpectStep(("tk5-logon",)), KeyStep("enter")))
    session = ScriptedSession([capture("tk5-logon")])
    with pytest.raises(FlowDefinitionError):
        run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL)
    assert _keys(session) == []


@pytest.mark.parametrize("make", [lambda: SignatureError("bad"), lambda: TypeError("bad")])
def test_recognizer_failure_in_a_later_expect_sends_no_further_key(monkeypatch, make):
    # call 1: first Expect, call 2: the key's comparison screen, call 3: second Expect
    monkeypatch.setattr(
        runner_module, "recognize", _Boom(runner_module.recognize, make, 3)
    )
    flow = Flow(
        "t",
        (
            ExpectStep(("tk5-logon",)),
            KeyStep("enter"),
            ExpectStep(("tso-password-prompt",)),
            KeyStep("enter"),
        ),
    )
    session = ScriptedSession([capture("tk5-logon"), capture("tso-password-prompt")])
    with pytest.raises(FlowDefinitionError):
        run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL)
    assert _keys(session) == [("enter",)]
