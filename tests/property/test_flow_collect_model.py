# Feature: more-flows, Property 3: collect matches the page model
"""Properties 3, 4 and 11 of the more-flows spec (task 4.10).

Property 3: a ``collect`` step matches a page model written here.
Property 4: a bad screen in the middle of a ``collect`` stops the run at once.
Property 11: a ``collect`` leaves one allow-listed audit record.

No live host: the pages are scripted screens (``ScriptedSession``). A row is never
formatted into a failure message.
"""
from __future__ import annotations

import dataclasses

from hypothesis import event, given, settings
from hypothesis import strategies as st

from greenscreen.flow import FlowError, run_flow
from greenscreen.flow.model import (
    AuditRecord,
    CollectStep,
    ExpectStep,
    Flow,
    OutputSpec,
    Timeouts,
)
from tests.flow_support import FakeClock, ScriptedSession, ScriptedState, capture
from tests.property._collect_support import PageSequence, page_sequence
from tests.screen_support import make_screen

_T = Timeouts(step=2.0, run=600.0, finally_=30.0)
_AUDIT_MEMBERS = (
    "step_index",
    "kind",
    "phase",
    "iteration",
    "signature",
    "status",
    "duration_seconds",
)
_COLLECT_INDEX = 1


# --------------------------------------------------------------------------
# Flows and sessions
# --------------------------------------------------------------------------

def _flow(seq: PageSequence, max_rows: int, max_screens: int, finally_steps=()) -> Flow:
    out = OutputSpec(
        "OUT", "str", "tso-ready", seq.first_row, 1, 79, next_row=seq.next_row, max_rows=max_rows
    )
    return Flow(
        "collect-model",
        (
            ExpectStep(("tso-ready", "tso-pause")),
            CollectStep("OUT", "tso-pause", max_screens),
        ),
        outputs=(out,),
        finally_steps=finally_steps,
        timeouts=_T,
    )


def _session(screens, stale: int) -> ScriptedSession:
    states = [ScriptedState(screens[0])]
    states += [ScriptedState(s, stale_reads=stale) for s in screens[1:]]
    return ScriptedSession(states)


def _enters(session: ScriptedSession) -> int:
    return sum(1 for c in session.calls if c[0] == "enter")


def _run(flow: Flow, session: ScriptedSession, clock: FakeClock | None = None):
    """(result, error): exactly one of them is None."""
    try:
        return run_flow(flow, session, {}, clock=clock or FakeClock()), None
    except FlowError as caught:
        return None, caught


# --------------------------------------------------------------------------
# Strategies
# --------------------------------------------------------------------------

@st.composite
def _page_counts(draw, cap: int, min_pages: int, max_pages: int):
    """Line counts per page. An empty More_Screen after the first page would equal the
    page before it, which the runner reads as "no answer yet" (a stale read), so only
    the first and the last page may be empty."""
    n = draw(st.integers(min_pages, max_pages))
    counts = [draw(st.integers(0, cap))]
    counts += [draw(st.integers(1, cap)) for _ in range(n - 2)]
    if n > 1:
        counts.append(draw(st.integers(0, cap)))
    return counts


@st.composite
def _listings(draw, *, max_lines: int = 22, max_pages: int = 13):
    """(PageSequence, max_rows, max_screens, stale) with limits around the model."""
    first_row = draw(st.integers(1, 6))
    next_row = draw(st.integers(0, 4))
    cap = min(max_lines, 22 - max(first_row, next_row))
    pages = draw(_page_counts(cap, 1, max_pages))
    seq = page_sequence(pages, first_row=first_row, next_row=next_row)
    total, n = sum(pages), len(pages)
    max_rows = draw(
        st.one_of(
            st.integers(1, 300),
            st.integers(-1, 1).map(lambda d: max(1, total + d)),
        )
    )
    max_screens = draw(
        st.one_of(
            st.integers(1, 14),
            st.integers(-1, 1).map(lambda d: min(50, max(1, n + d))),
        )
    )
    stale = draw(st.integers(0, 2))
    return seq, max_rows, max_screens, stale


# --------------------------------------------------------------------------
# Property 3
# --------------------------------------------------------------------------

@settings(max_examples=200, deadline=None)
@given(_listings())
def test_collect_matches_the_page_model(case):
    """**Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.6, 6.11**"""
    seq, max_rows, max_screens, stale = case
    n_pages = len(seq.tokens)
    session = _session(seq.screens(), stale)
    result, error = _run(_flow(seq, max_rows, max_screens), session)

    over = len(seq.all_tokens) > max_rows or n_pages > max_screens
    event(f"loop_limit={over}")
    assert _enters(session) <= max_screens - 1
    if over:
        assert result is None
        assert error is not None and error.reason == "loop_limit"
        assert error.step_index == _COLLECT_INDEX
        assert "OUT" not in getattr(error, "outputs", {})
    else:
        assert error is None and result is not None
        assert result.outputs["OUT"] == "\n".join(seq.all_tokens)
        assert _enters(session) == n_pages - 1


# --------------------------------------------------------------------------
# Property 4
# --------------------------------------------------------------------------

@st.composite
def _bad_page_cases(draw):
    """A listing of 2 to 13 pages, one page after the first replaced by a bad screen."""
    first_row = draw(st.integers(1, 6))
    next_row = draw(st.integers(0, 4))
    cap = min(10, 22 - max(first_row, next_row))
    pages = draw(_page_counts(cap, 2, 13))
    seq = page_sequence(pages, first_row=first_row, next_row=next_row)
    k = draw(st.integers(1, len(pages) - 1))
    kind = draw(st.sampled_from(("blank", "text", "ispf")))
    stale = draw(st.integers(0, 2))
    extra = draw(st.integers(0, 3))  # room above the limit, so the limit never fires first
    return seq, k, kind, stale, k + 1 + extra


def _bad_screen(kind: str, draw_text: str):
    if kind == "blank":
        return make_screen(24, 80)
    if kind == "text":
        return make_screen(24, 80, {(3, 2): draw_text})
    return capture("ispf-primary-menu")


@settings(max_examples=200, deadline=None)
@given(_bad_page_cases(), st.text(alphabet="QXZ", min_size=1, max_size=20))
def test_a_bad_screen_in_the_middle_of_a_collect_stops_the_run_at_once(case, text):
    """**Validates: Requirements 6.7, 6.12**"""
    seq, k, kind, stale, max_screens = case
    screens = seq.screens()
    screens[k] = _bad_screen(kind, text)
    # The probe Flow names the ISPF menu in its finally steps, so that signature is known.
    probe = (ExpectStep(("ispf-primary-menu",)),)
    clock = FakeClock()
    session = _session(screens, stale)
    result, error = _run(_flow(seq, 500, max_screens, finally_steps=probe), session, clock)

    assert result is None and error is not None
    assert error.step_index == _COLLECT_INDEX and error.kind == "collect"
    assert _enters(session) == k
    if kind == "ispf":
        assert error.reason == "unexpected_screen"
        assert clock.now < _T.step  # no wait for the step timeout
    else:
        assert error.reason == "unknown_screen"
        assert clock.now >= _T.step


# --------------------------------------------------------------------------
# Property 11
# --------------------------------------------------------------------------

@settings(max_examples=200, deadline=None)
@given(_listings(max_lines=12, max_pages=6))
def test_a_collect_leaves_one_allow_listed_audit_record(case):
    """**Validates: Requirements 6.8**"""
    seq, max_rows, max_screens, stale = case
    session = _session(seq.screens(), stale)
    result, error = _run(_flow(seq, max_rows, max_screens), session)

    over = len(seq.all_tokens) > max_rows or len(seq.tokens) > max_screens
    audit = error.audit if error is not None else result.audit
    records = [r for r in audit if r.kind == "collect"]
    assert len(records) == 1
    rec = records[0]
    assert type(rec) is AuditRecord
    assert tuple(f.name for f in dataclasses.fields(rec)) == _AUDIT_MEMBERS
    assert rec.step_index == _COLLECT_INDEX
    assert rec.iteration is None
    assert rec.phase == "steps"
    if over:
        assert error is not None and error.reason == "loop_limit"
        assert rec.status == "failed"
    else:
        assert rec.status == "ok"
        assert rec.signature == "tso-ready"
