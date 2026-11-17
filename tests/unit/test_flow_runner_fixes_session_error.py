"""Every Exception of a Session call becomes ``session_error`` (flow-runtime task 16.2).

Covers Requirements 7.6 to 7.9, 14.9, 14.10, 16.9 and 18.17 to 18.19.

Verdicts about the sentinel are built as booleans so that a failing assertion
never prints it.
"""
from __future__ import annotations

import sys
import traceback
from collections.abc import Mapping

import pytest

from greenscreen.connector import Field, Screen
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, Flow, InputSpec, KeyStep, TypeStep
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer.view import FieldGeom, ScreenView

from tests.flow_support import FakeClock, ScriptedSession, capture

SENTINEL = "SNTL4821"  # fits the 8-character secret Input
MESSAGE = f"boom {SENTINEL}"

_PASSWORD = InputSpec("password", "str", True, 8, None, True)


class RaisingSession(ScriptedSession):
    """A ScriptedSession whose ``method`` records the call, then raises ``make()``."""

    def __init__(self, states, method, make):
        super().__init__(states)
        self._method = method
        self._make = make
        for name in ("read_screen", "string", "enter", "clear", "pf", "pa"):
            if name == method:
                setattr(self, name, self._raise)

    def _raise(self, *args):
        self.calls.append((self._method, *args))
        raise self._make()


def _runtime_error():
    return RuntimeError(MESSAGE, SENTINEL)


def _flow(method, *, finally_steps=()):
    if method == "read_screen":
        return Flow("t", (ExpectStep(("tk5-logon",)),), finally_steps=finally_steps), 0
    if method == "string":
        return (
            Flow(
                "t",
                (ExpectStep(("tso-password-prompt",)), TypeStep(input="password")),
                inputs=(_PASSWORD,),
                finally_steps=finally_steps,
            ),
            1,
        )
    key = {
        "enter": KeyStep("enter"),
        "clear": KeyStep("clear"),
        "pf": KeyStep("pf", 3),
        "pa": KeyStep("pa", 1),
    }[method]
    return Flow("t", (ExpectStep(("tk5-logon",)), key), finally_steps=finally_steps), 1


def _screen_for(method):
    return capture("tso-password-prompt" if method == "string" else "tk5-logon")


def _leaks(value, depth=0):
    """True when the sentinel occurs in ``value`` (strings, containers, reprs)."""
    if depth > 6:
        return False
    if isinstance(value, str):
        return SENTINEL in value
    if isinstance(value, bytes):
        return SENTINEL.encode() in value
    if isinstance(value, Mapping):
        return any(_leaks(k, depth + 1) or _leaks(v, depth + 1) for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_leaks(v, depth + 1) for v in value)
    if isinstance(value, BaseException):
        return _leaks(value.args, depth + 1) or SENTINEL in repr(value)
    return SENTINEL in repr(value)


def _attribute_verdicts(err):
    verdicts = [_leaks(str(err)), _leaks(repr(err)), _leaks(err.args)]
    for name in dir(err):
        if name.startswith("__"):
            continue
        verdicts.append(_leaks(getattr(err, name)))
    for name, value in vars(err).items():
        verdicts.append(_leaks(name) or _leaks(value))
    return verdicts


def _flow_frames(err):
    tb = err.__traceback__
    while tb is not None:
        if str(tb.tb_frame.f_globals.get("__name__", "")).startswith("greenscreen.flow"):
            yield tb.tb_frame
        tb = tb.tb_next


def _held(value, inputs, depth=0):
    """True when a frame local is a Screen, a Field, the inputs mapping or holds the sentinel."""
    if value is inputs or isinstance(value, (Screen, Field, FieldGeom, ScreenView)):
        return True
    if depth > 6:
        return False
    if isinstance(value, Mapping):
        return any(_held(v, inputs, depth + 1) for v in value.values()) or _leaks(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_held(v, inputs, depth + 1) for v in value)
    return _leaks(value)


def _frame_verdicts(err, inputs):
    return [
        _held(value, inputs)
        for frame in _flow_frames(err)
        for value in list(frame.f_locals.values())
    ]


def _run(method, make, *, finally_steps=()):
    flow, _ = _flow(method, finally_steps=finally_steps)
    session = RaisingSession([_screen_for(method)], method, make)
    inputs = {"password": SENTINEL} if method == "string" else {}
    return flow, session, inputs


@pytest.mark.parametrize("method", ["read_screen", "string", "enter", "clear", "pf", "pa"])
def test_any_exception_becomes_session_error_without_leaks(method):
    flow, session, inputs = _run(method, _runtime_error)
    _, step_index = _flow(method)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, inputs, clock=FakeClock())
    err = info.value
    assert err.reason == "session_error"
    assert err.step_index == step_index
    assert "RuntimeError" in str(err)
    assert "boom" not in str(err)
    assert err.__cause__ is None
    assert err.__context__ is None
    assert not any(_attribute_verdicts(err))
    text = "".join(traceback.format_exception(type(err), err, err.__traceback__))
    assert SENTINEL not in text
    assert "boom" not in text
    verdicts = _frame_verdicts(err, inputs)
    assert not any(verdicts)


def test_flow_error_from_session_passes_through_unchanged():
    raised = FlowError(
        "unexpected_screen", step_index=99, kind="expect", expected=("x",),
        summary=None, audit=(),
    )
    flow, session, inputs = _run("enter", lambda: raised)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, inputs, clock=FakeClock())
    assert info.value is raised
    assert raised.reason == "unexpected_screen"
    assert raised.step_index == 99


@pytest.mark.parametrize("method", ["string", "enter"])
@pytest.mark.parametrize("make", [KeyboardInterrupt, lambda: SystemExit(3)])
def test_base_exception_propagates_same_object_after_release(method, make):
    made = []

    def build():
        made.append(make())
        return made[0]

    finally_steps = (ExpectStep(("tk5-logon",)), KeyStep("clear"))
    flow, session, inputs = _run(method, build, finally_steps=finally_steps)
    with pytest.raises(BaseException) as info:
        run_flow(flow, session, inputs, clock=FakeClock())
    err = info.value
    assert err is made[0]
    assert not isinstance(err, Exception)
    assert session.calls[-1][0] == method  # nothing was sent after the failing call
    assert ("clear",) not in session.calls  # no Finally_Step ran
    assert ("close",) not in session.calls
    assert not any(_frame_verdicts(err, inputs))
    # the traceback ends in the runner; the interpreter state is untouched
    assert sys.exc_info() == (None, None, None)
