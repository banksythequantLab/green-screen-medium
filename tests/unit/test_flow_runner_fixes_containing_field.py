"""Type_Step target lookup through ScreenView.containing_field (task 16.5).

Covers Requirements 10.1, 10.7 and 18.24.
"""
from __future__ import annotations

import pytest

from greenscreen.connector.models import Field, Screen
from greenscreen.flow.model import ExpectStep, Flow, TypeStep
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer.view import ScreenView

from tests.flow_support import FakeClock, ScriptedSession, capture
from tests.screen_support import CAPTURE_NAMES


def _type_flow() -> Flow:
    return Flow("t", (ExpectStep(("tk5-logon",)), TypeStep(text="X")))


def test_type_step_calls_containing_field_with_cursor(monkeypatch):
    calls = []
    original = ScreenView.containing_field

    def spy(self, row, col):
        calls.append((row, col))
        return original(self, row, col)

    monkeypatch.setattr(ScreenView, "containing_field", spy)
    screen = capture("tk5-logon")
    session = ScriptedSession([screen])
    run_flow(_type_flow(), session, {}, clock=FakeClock())
    # the recognizer calls it too (cursor matchers); every call uses the cursor
    assert calls
    assert set(calls) == {(screen.cursor_row, screen.cursor_col)}
    assert ("string", "X") in session.calls


def test_hidden_field_text_is_never_read(monkeypatch):
    reads = []
    original = Field.__getattribute__

    def spy(self, name):
        if name == "text":
            reads.append(self.hidden)
        return original(self, name)

    monkeypatch.setattr(Field, "__getattribute__", spy)

    def forbidden(self, *args, **kwargs):
        raise AssertionError("runner must not use Screen.find_field")

    monkeypatch.setattr(Screen, "find_field", forbidden)
    session = ScriptedSession([capture("tso-password-prompt")])
    flow = Flow("t", (ExpectStep(("tso-password-prompt",)), TypeStep(text="X")))
    run_flow(flow, session, {}, clock=FakeClock())
    assert reads == []


def _has_password(screen: Screen) -> bool:
    for f in screen.fields:
        if f.hidden and f.text.strip():
            return True
    return False


@pytest.mark.parametrize("name", CAPTURE_NAMES)
def test_containing_field_agrees_with_find_field(name):
    screen = capture(name)
    if _has_password(screen):
        pytest.skip("capture holds a typed password")
    view = ScreenView(screen)
    for row in range(screen.rows):
        for col in range(screen.columns):
            geom = view.containing_field(row, col)
            oracle = screen.find_field(row, col)  # test-side oracle only
            if oracle is None:
                assert geom is None
                continue
            assert geom is not None
            assert (geom.start_row, geom.start_col) == (oracle.start_row, oracle.start_col)
            assert geom.byte_length == oracle.byte_length
            assert geom.protected == oracle.protected
            assert geom.hidden == oracle.hidden
