"""Property 4 of the flow-runtime spec: a key is sent only after a verified screen,
and an unknown screen stops the run."""
from __future__ import annotations

import dataclasses

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.connector.models import SFToken
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, KeyStep, Timeouts
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures, recognize
from tests.flow_support import FakeClock, ScriptedSession, copy_screen
from tests.property import _flow_strategies as fs

_BUNDLED = list(load_bundled_signatures())
_BY_NAME = {s.name: s for s in _BUNDLED}
_KEYS = ("enter", "clear", "pf", "pa")
POLL = 0.1


class RecordingSession(ScriptedSession):
    """ScriptedSession that also keeps, for every key, the screen read just before it."""

    def __init__(self, states):
        super().__init__(states)
        self.last_read = None
        self.key_pre_screens: list = []

    def read_screen(self):
        screen = super().read_screen()
        self.last_read = copy_screen(screen)
        return screen

    def _note_key(self):
        self.key_pre_screens.append(self.last_read)

    def enter(self):
        self._note_key()
        super().enter()

    def clear(self):
        self._note_key()
        super().clear()

    def pf(self, n):
        self._note_key()
        super().pf(n)

    def pa(self, n):
        self._note_key()
        super().pa(n)


def _geometry(screen):
    """Size and start cells of every field, MDT bit ignored (test-side model)."""
    starts = tuple(
        (r, c, tok.c0 & ~0x01)
        for r, row in enumerate(screen.cell_grid)
        for c, tok in enumerate(row)
        if isinstance(tok, SFToken)
    )
    return screen.rows, screen.columns, starts


def _restore_typed(pre, current):
    """Comparison model: the cursor field's data cells come from the Current_Screen."""
    out = copy_screen(pre)
    field = current.find_field(current.cursor_row, current.cursor_col)
    if field is None:
        return out
    total = current.rows * current.columns
    start = field.start_row * current.columns + field.start_col
    for k in range(1, field.byte_length + 1):
        pos = (start + k) % total
        r, c = divmod(pos, current.columns)
        out.cell_grid[r][c] = current.cell_grid[r][c]
    return out


def _is_key(call):
    return call[0] in _KEYS


# Feature: flow-runtime, Property 4: A key is sent only after a verified screen, and an unknown screen stops the run
@settings(max_examples=100, deadline=None)
@given(script=fs.chain_scripts(), data=st.data(), ambiguous=st.booleans())
def test_unknown_or_ambiguous_screen_stops_the_run_with_no_further_input(script, data, ambiguous):
    """**Validates: Requirements 8.7, 8.9, 8.11, 8.14, 13.3**"""
    steps = script.steps
    n = len(steps)
    signatures = list(_BUNDLED)
    fail_at = None
    flow = script.flow
    if ambiguous:
        j = data.draw(st.integers(0, n - 1), label="twinned step")
        twin_name = steps[j].name + "-twin"
        signatures.append(dataclasses.replace(_BY_NAME[steps[j].name], name=twin_name))
        first = next(i for i, s in enumerate(steps) if s.name == steps[j].name)
        failing = first
        expect0 = dataclasses.replace(flow.steps[0], tolerate=(twin_name,))
        main = (expect0,) + flow.steps[1:]
    else:
        fail_at = data.draw(st.integers(0, n - 1), label="blank step")
        failing = fail_at
        main = flow.steps
    # A Finally plan that would send a key if it ran.
    finally_steps = (ExpectStep((steps[0].name,)), KeyStep("enter"))
    flow = dataclasses.replace(
        flow, steps=main, finally_steps=finally_steps, timeouts=Timeouts(1.2, 60.0, 30.0)
    )

    session = RecordingSession(script.states(fail_at=fail_at))
    with pytest.raises(FlowError) as caught:
        run_flow(flow, session, {}, signatures=signatures, clock=FakeClock(), poll_interval=POLL)
    error = caught.value
    assert error.reason == ("ambiguous_screen" if ambiguous else "unknown_screen")

    calls = session.calls
    # Nothing but reads follows the read that caused the error (no string, no key, no Finally key).
    assert calls[-1] == ("read",)
    sent = [c for c in calls if c[0] != "read"]
    expected = []
    for step in steps[:failing]:
        if step.literal is not None:
            expected.append(("string", step.literal))
        expected.append(step.key)
    assert sent == expected

    keys = [c for c in sent if _is_key(c)]
    accepted = failing  # screens 0 .. failing-1 were accepted
    assert len(keys) <= accepted
    assert len(keys) == len(session.key_pre_screens)

    # Every key was preceded by a Pre_Key_Screen of the Current_Screen's geometry that the
    # Comparison model recognizes as the Current_Screen name.
    own = script.states()
    for i, pre in enumerate(session.key_pre_screens):
        current = own[i].screen
        assert _geometry(pre) == _geometry(current)
        assert recognize(_restore_typed(pre, current), _BUNDLED) == steps[i].name
