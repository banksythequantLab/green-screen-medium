"""Requirement 14.7: no ``greenscreen.flow`` traceback frame keeps caller data.

Covers the three exits that leave ``run_flow`` before any step runs: the
``FlowInputError``, the ``FlowDefinitionError`` and the ``poll_interval``
``ValueError``. Verdicts are booleans only; a value is never formatted into a
failure message, so a secret is never shown.
"""
from __future__ import annotations

import pytest

from greenscreen.connector import Screen
from greenscreen.flow.errors import FlowDefinitionError, FlowInputError
from greenscreen.flow.model import ExpectStep, Flow, InputSpec
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher

from tests.flow_support import FakeClock, ScriptedSession, capture

SECRET_TEXT = "SNTL4821"
SECRET_INT = 73650912  # rendered text "73650912"
_NEEDLES = (SECRET_TEXT, str(SECRET_INT))
_TINY = ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),))

_INPUTS_SPECS = (
    InputSpec("password", "str", True, 8, None, True),
    InputSpec("count", "int", True, 8),
    InputSpec("tail", "str", True, 8),
)


def _holds(value, inputs, depth=0) -> bool:
    """True if ``value`` is the inputs mapping, a Screen, or contains a needle."""
    if value is inputs or isinstance(value, Screen):
        return True
    if isinstance(value, str):
        return any(n in value for n in _NEEDLES)
    if isinstance(value, bytes):
        return any(n.encode() in value for n in _NEEDLES)
    if type(value) is int:
        return any(n in str(value) for n in _NEEDLES)
    if depth > 6:
        return False
    if isinstance(value, dict):
        return any(
            _holds(k, inputs, depth + 1) or _holds(v, inputs, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_holds(v, inputs, depth + 1) for v in value)
    if isinstance(value, BaseException):
        return _holds(value.args, inputs, depth + 1)
    return False


def _frame_verdicts(err, inputs) -> list[bool]:
    verdicts = []
    tb = err.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if str(frame.f_globals.get("__name__", "")).startswith("greenscreen.flow"):
            verdicts.extend(_holds(v, inputs) for v in list(frame.f_locals.values()))
        tb = tb.tb_next
    return verdicts


def _flow() -> Flow:
    return Flow(
        "t", (ExpectStep(("tk5-logon",), (), 1.0),), inputs=_INPUTS_SPECS
    )


def _run_and_catch(exc_type, **kwargs):
    session = ScriptedSession([capture("tk5-logon")])
    inputs = kwargs.pop("inputs")
    try:
        run_flow(kwargs.pop("flow"), session, inputs, clock=FakeClock(), **kwargs)
    except exc_type as exc:
        return exc, session, inputs
    raise AssertionError("expected exception was not raised")


def _check(err, session, inputs, exc_type, args) -> None:
    assert type(err) is exc_type
    assert err.args == args
    assert err.__cause__ is None and err.__context__ is None
    assert session.calls == []
    verdicts = _frame_verdicts(err, inputs)
    assert verdicts, "no greenscreen.flow frame was walked"
    assert not any(verdicts)


def test_flow_input_error_leaves_no_input_in_any_flow_frame():
    inputs = {"password": SECRET_TEXT, "count": SECRET_INT, "tail": SECRET_TEXT + "XX"}
    err, session, inputs = _run_and_catch(
        FlowInputError, flow=_flow(), inputs=inputs
    )
    assert str(err).endswith("input tail violates max_length")
    _check(err, session, inputs, FlowInputError, err.args)
    assert len(err.args) == 1


def test_flow_definition_error_leaves_no_input_in_any_flow_frame():
    inputs = {"password": SECRET_TEXT, "count": SECRET_INT, "tail": SECRET_TEXT}
    err, session, inputs = _run_and_catch(
        FlowDefinitionError, flow=_flow(), inputs=inputs, signatures=[_TINY]
    )
    assert "tk5-logon" in str(err)
    _check(err, session, inputs, FlowDefinitionError, err.args)


@pytest.mark.parametrize("interval", [0.0, 5])
def test_poll_interval_value_error_leaves_no_input_in_any_flow_frame(interval):
    inputs = {"password": SECRET_TEXT, "count": SECRET_INT, "tail": SECRET_TEXT}
    err, session, inputs = _run_and_catch(
        ValueError, flow=_flow(), inputs=inputs, poll_interval=interval
    )
    assert str(err) == "poll_interval must be a number from 0.01 to 1"
    _check(err, session, inputs, ValueError, ("poll_interval must be a number from 0.01 to 1",))
