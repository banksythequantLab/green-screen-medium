"""Property 8 of the flow-runtime spec: typing never blocks the following key."""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.flow.model import ExpectStep, Flow, InputSpec, KeyStep, TypeStep
from greenscreen.flow.runner import run_flow
from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    blank_screen,
    capture,
    copy_screen,
    typed_screen,
)
from tests.property import _flow_strategies as fs


class _TypedSession(ScriptedSession):
    """Shows the in-memory typed screen from the first read after ``string``."""

    def __init__(self, base, typed):
        super().__init__([base, blank_screen()])
        self._typed = typed

    def string(self, text):
        self.calls.append(("string", text))
        self._current = copy_screen(self._typed)


def _check(case):
    base = capture(case.name)
    typed = typed_screen(base, case.text, mdt=case.mdt)  # in memory only
    session = _TypedSession(base, typed)
    # The text goes through a declared non-secret Input, so "${" and any other
    # printable ASCII is data, not a literal that the validator would parse.
    flow = Flow(
        "typed",
        (ExpectStep((case.name,)), TypeStep(input="value"), KeyStep("enter")),
        inputs=(InputSpec("value", "str", True, 255),),
    )

    # Any FlowError propagates and fails the test; nothing is caught here.
    run_flow(flow, session, {"value": case.text}, clock=FakeClock())

    sent = [c for c in session.calls if c[0] != "read"]
    # Booleans only: the typed text may be a password-prompt entry.
    assert (sent == [("string", case.text), ("enter",)]) is True


# Feature: flow-runtime, Property 8: Typing never blocks the following key
@settings(max_examples=100, deadline=None)
@given(case=fs.typed_cases())
def test_typing_never_blocks_the_following_key(case):
    """**Validates: Requirements 8.9, 8.17, 8.19, 10.4, 10.5**"""
    _check(case)


# Feature: logon-recovery, Property 8 (flow-runtime) for the two recovery screens
@pytest.mark.parametrize(
    "name", ["tso-userid-in-use", "tso-reconnect-password-prompt"]
)
@settings(max_examples=100, deadline=None)
@given(data=st.data())
def test_typing_never_blocks_on_recovery_screens(name, data):
    """**Validates: Requirements 9.1, 9.2, 9.4**"""
    _check(data.draw(fs.typed_cases(names=(name,))))
