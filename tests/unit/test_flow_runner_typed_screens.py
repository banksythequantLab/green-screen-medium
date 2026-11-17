"""Typed screens of the shipped flows are accepted and the key is sent (task 10.6).

Covers Requirements 8.9, 8.17, 8.19, 10.4, 10.5, 18.11 and 18.16.

Each Pre_Key_Screen is built in memory from the accepted capture with
``typed_screen``. Verdicts about the sentinel are booleans, so a failing
assertion never prints it.
"""
from __future__ import annotations

import logging

import pytest

from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, Flow, InputSpec, KeyStep, TypeStep
from greenscreen.flow.runner import run_flow

from tests.flow_support import FakeClock, ScriptedSession, capture, typed_screen

SENTINEL = "SNTL4821"  # fits the 8-character secret Input


class TypingSession(ScriptedSession):
    """``string`` records the call, then the session shows the typed screen."""

    def __init__(self, states, typed):
        super().__init__(states)
        self._typed = typed

    def string(self, text):
        self.calls.append(("string", text))
        self._current = self._typed


def _leaks(value) -> bool:
    return SENTINEL in repr(value) or SENTINEL in str(value)


def _run(signature, text, next_signature, *, secret=False):
    typed = typed_screen(capture(signature), text)
    session = TypingSession([capture(signature), capture(next_signature)], typed)
    spec = InputSpec("value", "str", True, 16, None, secret)
    flow = Flow(
        "typed",
        (
            ExpectStep((signature,)),
            TypeStep(input="value"),
            KeyStep("enter"),
            ExpectStep((next_signature,)),
        ),
        inputs=(spec,),
    )
    result = run_flow(flow, session, {"value": text}, clock=FakeClock())
    return session, result


@pytest.mark.parametrize(
    ("signature", "text", "next_signature"),
    [
        ("tk5-logon", "someuser", "tso-password-prompt"),
        ("ispf-primary-menu", "X", "tso-ready"),
        ("tso-ready", "LOGOFF", "tk5-logon"),
    ],
)
def test_typed_screen_is_accepted_and_key_is_sent(signature, text, next_signature):
    session, result = _run(signature, text, next_signature)
    assert session.calls.count(("string", text)) == 1
    assert [c for c in session.calls if c[0] in ("enter", "clear", "pf", "pa")] == [("enter",)]
    assert ("close",) not in session.calls
    assert sum(1 for r in result.audit if r.kind == "key") == 1


def test_password_typed_into_hidden_field_leaks_nowhere(caplog):
    signature = "tso-password-prompt"
    screen = capture(signature)
    field = screen.find_field(screen.cursor_row, screen.cursor_col)
    assert field is not None and field.hidden
    caplog.set_level(0)
    logging.getLogger().setLevel(0)
    try:
        session, result = _run(signature, SENTINEL, "ispf-primary-menu", secret=True)
        failure = None
    except FlowError as err:  # pragma: no cover - reported through the verdicts below
        failure = err
    assert failure is None
    assert session.calls.count(("string", SENTINEL)) == 1
    assert [c for c in session.calls if c[0] == "enter"] == [("enter",)]
    verdicts = [
        _leaks(result),
        _leaks(result.audit),
        _leaks(result.outputs),
        any(_leaks(r.getMessage()) or _leaks(r.args) or _leaks(r.__dict__) for r in caplog.records),
        _leaks(caplog.text),
    ]
    assert not any(verdicts)
