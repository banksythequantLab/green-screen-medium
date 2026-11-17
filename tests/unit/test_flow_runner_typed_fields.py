"""MDT bit, changed geometry and the full-field case (flow-runtime task 10.7).

Covers Requirements 8.9, 8.10, 8.17, 8.18, 8.19, 18.11 and 18.12.
"""
from __future__ import annotations

import pytest

from greenscreen.connector.models import SFToken
from greenscreen.flow import runner as runner_module
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, Flow, KeyStep, TypeStep
from greenscreen.flow.runner import run_flow
from greenscreen.flow.screens import geometry

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    blank_screen,
    capture,
    copy_screen,
    typed_screen,
)

# (signature name, text typed). The password text is a sentinel absent from captures/.
CASES = [
    ("tk5-logon", "USER1"),
    ("tso-password-prompt", "Qz9#vL"),
    ("ispf-primary-menu", "X"),
    ("tso-ready", "LOGOFF"),
]
_IDS = [c[0] for c in CASES]


class _TypedSession(ScriptedSession):
    """Shows ``typed`` from the first read after ``string``; the key then advances."""

    def __init__(self, base, typed):
        super().__init__([base, blank_screen()])
        self._typed = typed

    def string(self, text):
        self.calls.append(("string", text))
        self._current = copy_screen(self._typed)


def _flow(sig: str, types: int = 1) -> Flow:
    steps = [ExpectStep((sig,))] + [TypeStep(text="X")] * types + [KeyStep("enter")]
    return Flow("t", tuple(steps))


def _keys(session):
    return [c for c in session.calls if c[0] in ("enter", "clear", "pf", "pa")]


class _Spy:
    """Records recognize calls and the Typed_Fields seen at each runner event."""

    def __init__(self, monkeypatch):
        self.recognize_calls = 0
        self.at_key: list[frozenset] = []
        self.after_accept: list[frozenset] = []
        self.after_exec_key: list[frozenset] = []
        S = runner_module._RunState
        orig_recognize = runner_module.recognize
        orig_key, orig_accept, orig_exec_key = S.key, S.accept, S.exec_key

        def recognize(*a, **k):
            self.recognize_calls += 1
            return orig_recognize(*a, **k)

        def key(state, *a, **k):
            self.at_key.append(frozenset(state.typed_fields))
            return orig_key(state, *a, **k)

        def accept(state, *a, **k):
            orig_accept(state, *a, **k)
            self.after_accept.append(frozenset(state.typed_fields))

        def exec_key(state, *a, **k):
            try:
                return orig_exec_key(state, *a, **k)
            finally:
                self.after_exec_key.append(frozenset(state.typed_fields))

        monkeypatch.setattr(runner_module, "recognize", recognize)
        monkeypatch.setattr(S, "key", key)
        monkeypatch.setattr(S, "accept", accept)
        # _EXECUTORS holds the unbound function, so patch the table too
        monkeypatch.setattr(S, "exec_key", exec_key)
        monkeypatch.setitem(runner_module._EXECUTORS, "key", exec_key)


def _run(sig, typed, *, types=1):
    session = _TypedSession(capture(sig), typed)
    result = run_flow(_flow(sig, types), session, {}, clock=FakeClock())
    return result, session


def _run_failing(sig, typed):
    session = _TypedSession(capture(sig), typed)
    with pytest.raises(FlowError) as info:
        run_flow(_flow(sig), session, {}, clock=FakeClock())
    return info.value, session


def _sf_at(screen, row, col):
    cell = screen.cell_grid[row][col]
    assert isinstance(cell, SFToken)
    return cell.c0


def _cursor_field(sig):
    """Test-side oracle; only used on captures that hold no password."""
    assert sig != "tso-password-prompt"
    base = capture(sig)
    return base, base.find_field(base.cursor_row, base.cursor_col)


# --------------------------------------------------------------------------
# MDT bit set and clear
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mdt", [True, False], ids=["mdt-set", "mdt-clear"])
@pytest.mark.parametrize("sig,text", CASES, ids=_IDS)
def test_typed_screen_passes_with_mdt_set_or_clear(sig, text, mdt):
    base = capture(sig)
    typed = typed_screen(base, text, mdt=mdt)
    # the helper really set or cleared the bit on the field attribute
    changed = [
        typed.cell_grid[r][c].c0 & 0x01
        for r in range(typed.rows)
        for c in range(typed.columns)
        if isinstance(typed.cell_grid[r][c], SFToken)
        and typed.cell_grid[r][c] != base.cell_grid[r][c]
    ]
    assert changed == ([1] if mdt else [])

    result, session = _run(sig, typed)

    assert len(_keys(session)) == 1
    assert [r.status for r in result.audit] == ["ok", "ok", "ok"]


def test_mdt_values_are_c9_and_c8_on_the_logon_field():
    base, field = _cursor_field("tk5-logon")
    assert _sf_at(base, field.start_row, field.start_col) == 0xC8
    on = typed_screen(base, "USER1", mdt=True)
    off = typed_screen(base, "USER1", mdt=False)
    assert _sf_at(on, field.start_row, field.start_col) == 0xC9
    assert _sf_at(off, field.start_row, field.start_col) == 0xC8


# --------------------------------------------------------------------------
# Geometry check on tk5-logon
# --------------------------------------------------------------------------

def _with_attribute(screen, row, col, c0):
    out = copy_screen(screen)
    out.cell_grid[row][col] = SFToken(c0)
    return out


def test_geometry_ignores_mdt_but_not_the_protected_bit():
    base, field = _cursor_field("tk5-logon")
    r, c = field.start_row, field.start_col
    assert geometry(base) == geometry(_with_attribute(base, r, c, 0xC9))
    assert geometry(base) != geometry(_with_attribute(base, r, c, 0xE8))


def test_logon_input_field_c9_copy_passes_the_geometry_check():
    base, field = _cursor_field("tk5-logon")
    typed = _with_attribute(
        typed_screen(base, "USER1"), field.start_row, field.start_col, 0xC9
    )
    result, session = _run("tk5-logon", typed)
    assert len(_keys(session)) == 1
    assert result.audit[-1].status == "ok"


def test_logon_input_field_e8_copy_fails_the_geometry_check(monkeypatch):
    base, field = _cursor_field("tk5-logon")
    typed = _with_attribute(
        typed_screen(base, "USER1"), field.start_row, field.start_col, 0xE8
    )
    spy = _Spy(monkeypatch)
    err, session = _run_failing("tk5-logon", typed)
    assert err.reason == "unexpected_screen"
    assert _keys(session) == []
    assert spy.recognize_calls == 1  # the Expect_Step only


# --------------------------------------------------------------------------
# Changed geometry (Requirement 18.12)
# --------------------------------------------------------------------------

def _move_start(screen, field):
    out = copy_screen(screen)
    r, c = field.start_row, field.start_col
    c0 = _sf_at(out, r, c)
    out.cell_grid[r][c] = 0x00
    out.cell_grid[r][c + 1] = SFToken(c0)
    return out


def _shorten(screen, field):
    out = copy_screen(screen)
    # a new field start inside the field splits it, so the length changes
    r, c = divmod(
        (field.start_row * out.columns + field.start_col + 2) % (out.rows * out.columns),
        out.columns,
    )
    out.cell_grid[r][c] = SFToken(0xC8)
    return out


def _change_attribute(screen, field):
    return _with_attribute(screen, field.start_row, field.start_col, 0xE8)


@pytest.mark.parametrize(
    "mutate", [_move_start, _shorten, _change_attribute],
    ids=["start-position", "length", "attribute"],
)
@pytest.mark.parametrize("sig,text", [c for c in CASES if c[0] != "tso-password-prompt"],
                         ids=["tk5-logon", "ispf-primary-menu", "tso-ready"])
def test_changed_geometry_raises_unexpected_screen_without_key_or_recognize(
    monkeypatch, sig, text, mutate
):
    base, field = _cursor_field(sig)
    typed = mutate(typed_screen(base, text), field)
    assert geometry(typed) != geometry(base)
    spy = _Spy(monkeypatch)

    err, session = _run_failing(sig, typed)

    assert err.reason == "unexpected_screen"
    assert err.step_index == 2 and err.kind == "key"
    assert _keys(session) == []
    assert spy.recognize_calls == 1  # the Expect_Step only, none for the Key_Step


def test_changed_geometry_on_the_password_prompt_is_checked_without_the_oracle(monkeypatch):
    base = capture("tso-password-prompt")
    typed = typed_screen(base, "Qz9#vL")
    # replace the attribute of the hidden field (cc) by a visible unprotected one
    hidden = next(f for f in base.fields if f.hidden)
    typed = _with_attribute(typed, hidden.start_row, hidden.start_col, 0xC8)
    spy = _Spy(monkeypatch)

    err, session = _run_failing("tso-password-prompt", typed)

    assert err.reason == "unexpected_screen"
    assert _keys(session) == []
    assert spy.recognize_calls == 1


# --------------------------------------------------------------------------
# Full field
# --------------------------------------------------------------------------

def _full_text(base, field):
    total = base.rows * base.columns
    ls = field.start_row * base.columns + field.start_col
    lc = base.cursor_row * base.columns + base.cursor_col
    offset = (lc - ls) % total
    return "A" * (field.byte_length - offset + 1)


@pytest.mark.parametrize("sig", ["tk5-logon", "ispf-primary-menu"])
def test_full_field_with_cursor_outside_raises_unknown_screen(monkeypatch, sig):
    base, field = _cursor_field(sig)
    typed = typed_screen(base, _full_text(base, field), cursor="outside")
    spy = _Spy(monkeypatch)

    err, session = _run_failing(sig, typed)

    assert err.reason == "unknown_screen"
    assert err.step_index == 2 and err.kind == "key"
    assert _keys(session) == []
    assert spy.recognize_calls == 2  # Expect_Step and the Comparison_Screen


def test_full_field_with_cursor_outside_passes_on_tso_ready():
    base, field = _cursor_field("tso-ready")
    typed = typed_screen(base, _full_text(base, field), cursor="outside")

    result, session = _run("tso-ready", typed)

    assert len(_keys(session)) == 1
    assert [r.status for r in result.audit] == ["ok", "ok", "ok"]


# --------------------------------------------------------------------------
# Typed_Fields bookkeeping
# --------------------------------------------------------------------------

def test_typing_twice_into_one_field_gives_one_typed_field_entry(monkeypatch):
    base, field = _cursor_field("tk5-logon")
    spy = _Spy(monkeypatch)

    _, session = _run("tk5-logon", typed_screen(base, "USER1"), types=2)

    assert [c for c in session.calls if c[0] == "string"] == [("string", "X")] * 2
    assert spy.at_key == [
        frozenset({(field.start_row, field.start_col, field.byte_length)})
    ]


def test_typed_fields_are_emptied_on_accept_and_when_a_key_is_sent(monkeypatch):
    base, _ = _cursor_field("tk5-logon")
    spy = _Spy(monkeypatch)

    _run("tk5-logon", typed_screen(base, "USER1"))

    assert len(spy.at_key) == 1 and len(spy.at_key[0]) == 1
    assert spy.after_accept == [frozenset()]
    assert spy.after_exec_key == [frozenset()]


def test_typed_fields_are_emptied_when_the_next_screen_is_accepted(monkeypatch):
    base, _ = _cursor_field("tk5-logon")
    # Expect, Type, Key, then an Expect that accepts the next screen (tk5-logon again)
    flow = Flow(
        "t",
        (
            ExpectStep(("tk5-logon",)),
            TypeStep(text="X"),
            KeyStep("enter"),
            ExpectStep(("tk5-logon",)),
        ),
    )
    session = _TypedSession(capture("tk5-logon"), typed_screen(base, "USER1"))
    session._states[1] = type(session._states[1])(capture("tk5-logon"))
    seen: list[frozenset] = []
    S = runner_module._RunState
    orig_accept = S.accept

    def accept(state, *a, **k):
        orig_accept(state, *a, **k)
        seen.append(frozenset(state.typed_fields))

    monkeypatch.setattr(S, "accept", accept)

    run_flow(flow, session, {}, clock=FakeClock())

    assert seen == [frozenset(), frozenset()]
