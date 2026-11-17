"""Type_Step and Key_Step rules of the flow runner (flow-runtime task 10.8).

Covers Requirements 7.2, 7.4, 7.5, 8.14, 8.15, 10.1 to 10.6 and 15.4.
Secret values are only ever compared through booleans.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import (
    ExpectStep,
    Flow,
    HandleStep,
    InputSpec,
    KeyStep,
    TypeStep,
)
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer.signature import (
    FieldLayoutMatcher,
    ScreenSignature,
    TextAtMatcher,
)

from tests.flow_support import FakeClock, ScriptedSession, capture
from tests.screen_support import make_screen

_SECRET = "Zx9!hush"  # test-only value, never printed or asserted on directly

LOGON = ExpectStep(("tk5-logon",))
LOGO = ExpectStep(("tk5-logo",))
PW_PROMPT = ExpectStep(("tso-password-prompt",))
MENU = ExpectStep(("ispf-primary-menu",))

SECRET_IN = InputSpec("pw", "str", True, 16, None, True)
PLAIN_IN = InputSpec("uid", "str", True, 16)
OPTIONAL_IN = InputSpec("nick", "str", False, 16)


def _run(flow, states, inputs=None, *, echo=False, signatures=None):
    session = ScriptedSession(states, echo_typing=echo)
    result = run_flow(
        flow, session, inputs or {}, clock=FakeClock(), signatures=signatures
    )
    return result, session


def _run_failing(flow, states, inputs=None, *, echo=False, signatures=None):
    session = ScriptedSession(states, echo_typing=echo)
    with pytest.raises(FlowError) as info:
        run_flow(
            flow, session, inputs or {}, clock=FakeClock(), signatures=signatures
        )
    return info.value, session


def _strings(session):
    return [c for c in session.calls if c[0] == "string"]


def _keys(session):
    return [c for c in session.calls if c[0] in ("enter", "clear", "pf", "pa")]


def _no_close(session):
    assert ("close",) not in session.calls


# A screen with no field at all, recognized by a private signature.
_NOFIELDS = ScreenSignature(
    "nofields",
    (TextAtMatcher(0, 1, "NOFIELDS"), FieldLayoutMatcher(0, ())),
)


def _nofields_screen():
    return make_screen(24, 80, {(0, 1): "NOFIELDS"})


# --------------------------------------------------------------------------
# bad_target (Requirement 10.1)
# --------------------------------------------------------------------------

def test_protected_cursor_field_is_bad_target_with_no_string_call():
    flow = Flow("t", (LOGO, TypeStep(text="X")))
    err, session = _run_failing(flow, [capture("tk5-logo")])
    assert err.reason == "bad_target"
    assert err.step_index == 1 and err.kind == "type"
    assert _strings(session) == [] and _keys(session) == []
    assert [(r.step_index, r.status) for r in err.audit] == [(0, "ok"), (1, "failed")]
    _no_close(session)


def test_missing_cursor_field_is_bad_target_with_no_string_call():
    flow = Flow("t", (ExpectStep(("nofields",)), TypeStep(text="X")))
    err, session = _run_failing(
        flow, [_nofields_screen()], signatures=[_NOFIELDS]
    )
    assert err.reason == "bad_target"
    assert _strings(session) == [] and _keys(session) == []
    _no_close(session)


def test_bad_target_leaves_current_screen_unchanged():
    # The finally Handle_Step reuses the Current_Screen when one exists; its
    # key is sent only if bad_target did not clear the Current_Screen.
    flow = Flow(
        "t",
        (LOGO, TypeStep(text="X")),
        finally_steps=(HandleStep("tk5-logo", 1, (KeyStep("enter"),)),),
    )
    err, session = _run_failing(
        flow, [capture("tk5-logo"), capture("tk5-logon")]
    )
    assert err.reason == "bad_target"
    assert _strings(session) == []
    assert [c[0] for c in _keys(session)] == ["enter"]
    _no_close(session)


def test_bad_target_on_missing_field_leaves_current_screen_unchanged():
    flow = Flow(
        "t",
        (ExpectStep(("nofields",)), TypeStep(text="X")),
        finally_steps=(HandleStep("nofields", 1, (KeyStep("enter"),)),),
    )
    err, session = _run_failing(
        flow, [_nofields_screen(), capture("tk5-logon")], signatures=[_NOFIELDS]
    )
    assert err.reason == "bad_target"
    assert _strings(session) == []
    assert [c[0] for c in _keys(session)] == ["enter"]


# --------------------------------------------------------------------------
# Secret and non-secret Inputs (Requirements 10.2, 10.3)
# --------------------------------------------------------------------------

def test_secret_input_into_visible_field_is_secret_target():
    flow = Flow("t", (LOGON, TypeStep(input="pw")), inputs=(SECRET_IN,))
    err, session = _run_failing(flow, [capture("tk5-logon")], {"pw": _SECRET})
    assert err.reason == "secret_target"
    assert err.step_index == 1
    assert _strings(session) == [] and _keys(session) == []
    assert (_SECRET in str(err)) is False
    assert (_SECRET in repr(err.audit)) is False
    _no_close(session)


def test_secret_input_into_hidden_field_calls_string_exactly_once():
    flow = Flow(
        "t",
        (PW_PROMPT, TypeStep(input="pw"), KeyStep("enter"), MENU),
        inputs=(SECRET_IN,),
    )
    result, session = _run(
        flow,
        [capture("tso-password-prompt"), capture("ispf-primary-menu")],
        {"pw": _SECRET},
        echo=True,
    )
    strings = _strings(session)
    assert len(strings) == 1
    assert (strings[0][1] == _SECRET) is True
    assert (_SECRET in repr(result)) is False
    _no_close(session)


def test_non_secret_input_into_hidden_field_is_allowed():
    flow = Flow(
        "t",
        (PW_PROMPT, TypeStep(input="uid"), KeyStep("enter"), MENU),
        inputs=(PLAIN_IN,),
    )
    result, session = _run(
        flow,
        [capture("tso-password-prompt"), capture("ispf-primary-menu")],
        {"uid": "HELLO"},
        echo=True,
    )
    assert _strings(session) == [("string", "HELLO")]
    assert [r.status for r in result.audit] == ["ok"] * 4


# --------------------------------------------------------------------------
# Optional Input not supplied (Requirement 10.4)
# --------------------------------------------------------------------------

def test_unsupplied_optional_input_skips_every_type_step_that_uses_it():
    flow = Flow(
        "t",
        (
            LOGON,
            TypeStep(input="nick"),
            TypeStep(input="nick"),
            TypeStep(text="AB"),
            KeyStep("enter"),
            LOGON,
        ),
        inputs=(OPTIONAL_IN,),
    )
    result, session = _run(
        flow, [capture("tk5-logon"), capture("tk5-logon")], {}, echo=True
    )
    assert [(r.step_index, r.kind, r.status) for r in result.audit] == [
        (0, "expect", "ok"),
        (1, "type", "skipped"),
        (2, "type", "skipped"),
        (3, "type", "ok"),
        (4, "key", "ok"),
        (5, "expect", "ok"),
    ]
    assert _strings(session) == [("string", "AB")]


def test_supplied_optional_input_is_typed():
    flow = Flow(
        "t", (LOGON, TypeStep(input="nick"), KeyStep("enter")), inputs=(OPTIONAL_IN,)
    )
    result, session = _run(
        flow, [capture("tk5-logon"), capture("tk5-logon")], {"nick": "bob"}, echo=True
    )
    assert _strings(session) == [("string", "bob")]
    assert result.audit[1].status == "ok"


def test_unsupplied_optional_input_in_handle_body_is_skipped_each_iteration():
    handle = HandleStep("tk5-logon", 2, (TypeStep(input="nick"), KeyStep("enter")))
    flow = Flow("t", (handle, MENU), inputs=(OPTIONAL_IN,))
    result, session = _run(
        flow,
        [capture("tk5-logon"), capture("ispf-primary-menu")],
        {},
        echo=True,
    )
    types = [r for r in result.audit if r.kind == "type"]
    assert [r.status for r in types] == ["skipped"]
    assert _strings(session) == []
    assert [c[0] for c in _keys(session)] == ["enter"]


# --------------------------------------------------------------------------
# Literal text (Requirement 7.2 / 10.5)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text", ["X", "  lead and trail  ", "A  B", "%&*()~", "A" * 255]
)
def test_string_receives_declared_text_unchanged(text):
    flow = Flow("t", (LOGON, TypeStep(text=text), KeyStep("enter")))
    _, session = _run(
        flow, [capture("tk5-logon"), capture("ispf-primary-menu")], echo=False
    )
    strings = _strings(session)
    assert len(strings) == 1
    assert (strings[0][1] == text) is True
    assert type(strings[0][1]) is str


def test_non_secret_input_value_is_passed_unchanged():
    flow = Flow(
        "t", (LOGON, TypeStep(input="uid"), KeyStep("enter")), inputs=(PLAIN_IN,)
    )
    _, session = _run(
        flow,
        [capture("tk5-logon"), capture("ispf-primary-menu")],
        {"uid": " a b "},
    )
    assert _strings(session) == [("string", " a b ")]


# --------------------------------------------------------------------------
# Keys (Requirements 8.14, 8.15, 10.6)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["pf", "pa"])
@pytest.mark.parametrize("n", [1, 3, 24])
def test_pf_and_pa_call_session_exactly_once_with_n(key, n):
    flow = Flow("t", (LOGON, KeyStep(key, n), MENU))
    _, session = _run(flow, [capture("tk5-logon"), capture("ispf-primary-menu")])
    assert _keys(session) == [(key, n)]
    _no_close(session)


@pytest.mark.parametrize("key", ["enter", "clear"])
def test_enter_and_clear_call_session_exactly_once(key):
    flow = Flow("t", (LOGON, KeyStep(key), MENU))
    _, session = _run(flow, [capture("tk5-logon"), capture("ispf-primary-menu")])
    assert _keys(session) == [(key,)]


def test_at_most_one_key_per_accepted_screen():
    flow = Flow(
        "t",
        (LOGON, KeyStep("enter"), MENU, KeyStep("pf", 3), LOGON),
    )
    result, session = _run(
        flow,
        [capture("tk5-logon"), capture("ispf-primary-menu"), capture("tk5-logon")],
    )
    assert [c[0] for c in _keys(session)] == ["enter", "pf"]
    assert [r.status for r in result.audit] == ["ok"] * 5


def test_no_key_is_sent_while_current_screen_is_absent(monkeypatch):
    # Two Key_Steps in a row cannot pass the Flow validator, so the validator
    # is bypassed to reach the runner's own guard (Requirement 8.15).
    import greenscreen.flow.validate as validate

    monkeypatch.setattr(validate, "structural_violations", lambda flow: [])
    flow = Flow("t", (LOGON, KeyStep("enter"), KeyStep("enter")))
    err, session = _run_failing(
        flow, [capture("tk5-logon"), capture("ispf-primary-menu")]
    )
    assert err.reason == "unexpected_screen"
    assert err.step_index == 2 and err.kind == "key"
    assert [c[0] for c in _keys(session)] == ["enter"]
    reads_before = [c for c in session.calls].count(("read",))
    assert reads_before == 2  # one Expect read, one pre-key read; none for step 2
    _no_close(session)


# --------------------------------------------------------------------------
# close is never called (Requirement 15.4)
# --------------------------------------------------------------------------

def test_close_not_called_on_success():
    flow = Flow("t", (LOGON, KeyStep("enter"), MENU))
    _, session = _run(flow, [capture("tk5-logon"), capture("ispf-primary-menu")])
    _no_close(session)


def test_close_not_called_when_run_flow_raises_flow_error():
    flow = Flow("t", (LOGON, MENU))
    err, session = _run_failing(flow, [capture("tk5-logon")])
    assert err.reason == "unexpected_screen"
    _no_close(session)


def test_close_not_called_when_session_raises_during_string():
    class Boom(ScriptedSession):
        def string(self, text):
            self.calls.append(("string", text))
            raise OSError("boom")

    flow = Flow("t", (LOGON, TypeStep(text="X")))
    session = Boom([capture("tk5-logon")])
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=FakeClock())
    assert info.value.reason == "session_error"
    _no_close(session)


def test_close_not_called_when_a_base_exception_escapes():
    class Interrupt(ScriptedSession):
        def enter(self):
            self.calls.append(("enter",))
            raise KeyboardInterrupt

    flow = Flow("t", (LOGON, KeyStep("enter")))
    session = Interrupt([capture("tk5-logon")])
    with pytest.raises(KeyboardInterrupt):
        run_flow(flow, session, {}, clock=FakeClock())
    _no_close(session)
