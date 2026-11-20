"""Unit tests for the ``collect`` step (more-flows Requirements 5 and 6, task 4.6).

Model, YAML and validator rules first, then replays of the real member pages and
the real ``LISTCAT LEVEL(SYS2)`` pages through test-only Flows, then the stop
paths. The Flows are built here; the shipped ``tk5-library-members`` Flow is
replayed in task 8.5. A failure message never prints a row.
"""
from __future__ import annotations

import logging

import pytest

from greenscreen.flow.errors import FlowDefinitionError, FlowError
from greenscreen.flow.model import (
    CollectStep,
    ExpectStep,
    Flow,
    HandleStep,
    KeyStep,
    OutputSpec,
    Timeouts,
    TypeStep,
)
from greenscreen.flow.runner import _referenced_names, run_flow
from greenscreen.flow.validate import reference_violations
from greenscreen.recognizer import load_bundled_signatures
from greenscreen.recognizer.signature import ScreenSignature, TextAtMatcher

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    capture,
)
from tests.screen_support import make_screen

# --------------------------------------------------------------------------
# Test-only Flows
# --------------------------------------------------------------------------

MEMBER_PAGES = (
    "tso-listds-members",
    "tso-listds-members-page2",
    "tso-listds-members-page3",
    "tso-listds-members-page4",
    "tso-listds-members-page5",
    "tso-listds-members-page6",
    "tso-listds-members-page7",
)
LEVEL_PAGES = (
    "tso-listcat-level",
    "tso-listcat-level-page2",
    "tso-listcat-level-page3",
)
T = Timeouts(step=2.0, run=60.0, finally_=30.0)

MEMBERS_OUT = OutputSpec(
    "MEMBERS", "str", "tso-ready", row=7, col=3, length=8, next_row=0, max_rows=200
)
LEVEL_OUT = OutputSpec(
    "LINES", "str", "tso-ready", row=1, col=1, length=79, next_row=0, max_rows=100
)

FINALLY = (
    HandleStep("tso-pause", 20, (KeyStep("enter"),)),  # index 2, body 3
    ExpectStep(("tso-ready",)),  # 4
    KeyStep("clear"),  # 5
    ExpectStep(("tso-cleared",)),  # 6
    TypeStep(text="LOGOFF"),  # 7
    KeyStep("enter"),  # 8
    ExpectStep(("tk5-logon",)),  # 9
)
FINALLY_INDICES = tuple(range(2, 10))
COLLECT_INDEX = 1


def collect_flow(
    output: OutputSpec,
    *,
    max_screens: int,
    arming: tuple[str, ...] = ("tso-ready", "tso-pause"),
    finally_steps=FINALLY,
) -> Flow:
    return Flow(
        "collect-test",
        (ExpectStep(arming), CollectStep(output.name, "tso-pause", max_screens)),
        outputs=(output,),
        finally_steps=finally_steps,
        timeouts=T,
    )


def members_flow(*, max_screens: int = 10, max_rows: int = 200, **kw) -> Flow:
    out = OutputSpec(
        "MEMBERS", "str", "tso-ready", 7, 3, 8, next_row=0, max_rows=max_rows
    )
    return collect_flow(out, max_screens=max_screens, **kw)


def level_flow(*, max_screens: int = 5, max_rows: int = 100, **kw) -> Flow:
    out = OutputSpec(
        "LINES", "str", "tso-ready", 1, 1, 79, next_row=0, max_rows=max_rows
    )
    return collect_flow(out, max_screens=max_screens, **kw)


def states(pages, *, stale: int = 0, tail: bool = True) -> list[ScriptedState]:
    """Page screens (first with no stale reads), then the cleared and logon screens."""
    out = [ScriptedState(capture(pages[0]))]
    out += [ScriptedState(capture(p), stale_reads=stale) for p in pages[1:]]
    if tail:
        out.append(ScriptedState(capture("tso-cleared"), stale_reads=stale))
        out.append(ScriptedState(capture("tk5-logon"), stale_reads=stale))
    return out


def run(flow, session, *, sigs=None):
    return run_flow(flow, session, {}, signatures=sigs, clock=FakeClock())


def run_failing(flow, session, *, sigs=None, clock=None) -> FlowError:
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, signatures=sigs, clock=clock or FakeClock())
    return info.value


def enters(session) -> int:
    return sum(1 for c in session.calls if c[0] == "enter")


def enters_before_clear(session) -> int:
    n = 0
    for c in session.calls:
        if c[0] == "clear":
            break
        n += c[0] == "enter"
    return n


def finally_records(audit):
    return [r for r in audit if r.phase == "finally"]


def assert_finally_ran(audit, *, handle_unmatched: bool = False):
    """Every finally step ran. An unmatched Handle (no pause left) skips its body."""
    recs = finally_records(audit)
    assert set(r.step_index for r in recs) == set(FINALLY_INDICES)
    body = 3
    assert all(r.status == "ok" for r in recs if r.step_index != body)
    wanted = "skipped" if handle_unmatched else "ok"
    assert all(r.status == wanted for r in recs if r.step_index == body)


def assert_finally_skipped(audit):
    recs = finally_records(audit)
    assert tuple(r.step_index for r in recs) == FINALLY_INDICES
    assert all(r.status == "skipped" for r in recs)


# --------------------------------------------------------------------------
# YAML
# --------------------------------------------------------------------------

def _collect_flow_yaml() -> tuple[Flow, str]:
    flow = members_flow(max_screens=10)
    return flow, flow.to_yaml()


def test_collect_step_round_trips_through_yaml():
    flow, text = _collect_flow_yaml()
    assert Flow.from_yaml(text, load_bundled_signatures()) == flow
    assert Flow.from_yaml(text).to_yaml() == text


def test_collect_step_key_order_in_yaml():
    _, text = _collect_flow_yaml()
    lines = [ln.strip() for ln in text.splitlines()]
    at = lines.index("- kind: collect")
    assert lines[at : at + 4] == [
        "- kind: collect",
        "output: MEMBERS",
        "more: tso-pause",
        "max_screens: 10",
    ]
    out_at = lines.index("- name: MEMBERS")
    assert lines[out_at : out_at + 8] == [
        "- name: MEMBERS",
        "type: str",
        "signature: tso-ready",
        "row: 7",
        "col: 3",
        "length: 8",
        "next_row: 0",
        "max_rows: 200",
    ]


@pytest.mark.parametrize("missing", ["output", "more", "max_screens"])
def test_collect_step_needs_all_four_keys(missing):
    keys = {"kind": "collect", "output": "MEMBERS", "more": "tso-pause", "max_screens": "3"}
    del keys[missing]
    step = ", ".join(f"{k}: {v}" for k, v in keys.items())
    text = (
        "version: 1\nname: t\noutputs:\n"
        "  - {name: MEMBERS, type: str, signature: tso-ready, row: 7, col: 3,"
        " length: 8, max_rows: 5}\n"
        "steps:\n  - {kind: expect, signatures: [tso-ready, tso-pause]}\n"
        f"  - {{{step}}}\n"
    )
    with pytest.raises(FlowDefinitionError) as info:
        Flow.from_yaml(text)
    assert missing in str(info.value)
    assert "MEMBERS" not in str(info.value)


def test_collect_inside_a_handle_body_is_rejected_by_the_reader():
    text = (
        "version: 1\nname: t\n"
        "steps:\n"
        "  - kind: handle\n    signature: tso-pause\n    max_count: 2\n    steps:\n"
        "      - kind: collect\n        output: MEMBERS\n        more: tso-pause\n"
        "        max_screens: 3\n"
    )
    with pytest.raises(FlowDefinitionError) as info:
        Flow.from_yaml(text)
    assert "unsupported step kind 'collect'" in str(info.value)


# --------------------------------------------------------------------------
# Validator rules
# --------------------------------------------------------------------------

PLAIN_OUT = OutputSpec("MEMBERS", "str", "tso-ready", 7, 3, 8)
EXP = ExpectStep(("tso-ready", "tso-pause"))
COL = CollectStep("MEMBERS", "tso-pause", 10)


def rule_text(**kw) -> str:
    kw.setdefault("outputs", (MEMBERS_OUT,))
    kw.setdefault("steps", (EXP, COL))
    with pytest.raises(FlowDefinitionError) as info:
        Flow("t", **kw)
    return str(info.value)


def test_the_valid_shape_is_accepted():
    Flow("t", (EXP, COL), outputs=(MEMBERS_OUT,))
    # collect leaves the Flow armed: a key may follow, as after extract
    Flow("t", (EXP, COL, KeyStep("clear")), outputs=(MEMBERS_OUT,))
    # further signatures in the arming Expect are allowed
    Flow(
        "t",
        (ExpectStep(("tso-ready", "tso-pause", "tso-reenter")), COL),
        outputs=(MEMBERS_OUT,),
    )


def test_rule_not_a_rows_output():
    assert "output: not_a_rows_output" in rule_text(outputs=(PLAIN_OUT,))


def test_rule_more_invalid_name():
    text = rule_text(steps=(EXP, CollectStep("MEMBERS", "Bad Name", 10)))
    assert "more: invalid_name" in text


def test_rule_more_same_as_output_signature():
    text = rule_text(steps=(EXP, CollectStep("MEMBERS", "tso-ready", 10)))
    assert "more: same_as_output_signature" in text


@pytest.mark.parametrize("bad", [0, 51, -1, True])
def test_rule_max_screens_out_of_range(bad):
    text = rule_text(steps=(EXP, CollectStep("MEMBERS", "tso-pause", bad)))
    assert "max_screens: out_of_range" in text


@pytest.mark.parametrize("good", [1, 50])
def test_max_screens_limits_are_accepted(good):
    Flow("t", (EXP, CollectStep("MEMBERS", "tso-pause", good)), outputs=(MEMBERS_OUT,))


@pytest.mark.parametrize(
    "arming", [("tso-ready",), ("tso-pause",), ("tso-reenter", "tso-cleared")]
)
def test_rule_signature_not_in_arming_expect(arming):
    text = rule_text(steps=(ExpectStep(arming), COL))
    assert "output: signature_not_in_arming_expect" in text


def test_rule_unarmed_without_expect_or_after_a_key():
    assert "output: unarmed" in rule_text(steps=(COL,))
    assert "output: unarmed" in rule_text(steps=(EXP, KeyStep("enter"), COL))


def test_rule_not_in_steps():
    text = rule_text(steps=(EXP, COL), finally_steps=(EXP, COL))
    assert "collect: not_in_steps" in text


def test_rule_not_allowed_in_handle():
    body = HandleStep("tso-pause", 1, (COL,))
    text = rule_text(steps=(EXP, COL), finally_steps=(body,))
    assert "kind: not_allowed_in_handle" in text


def test_rule_undeclared_output():
    text = rule_text(steps=(EXP, CollectStep("NOPE", "tso-pause", 3)))
    assert "output: undeclared_output" in text


def test_rule_needs_exactly_one_read_for_two_collects():
    assert "needs_exactly_one_read" in rule_text(steps=(EXP, COL, COL))
    assert "needs_exactly_one_read" in rule_text(steps=(EXP,))


def test_validator_messages_hold_no_scalar():
    text = rule_text(steps=(EXP, CollectStep("MEMBERS", "Bad Name", 10)))
    assert "Bad Name" not in text


# --------------------------------------------------------------------------
# Signature references
# --------------------------------------------------------------------------

def _unchecked(flow: Flow, **fields) -> Flow:
    """A copy with fields replaced and no validation (a shape the validator refuses)."""
    new = object.__new__(Flow)
    for name in ("name", "steps", "description", "inputs", "outputs", "finally_steps", "timeouts"):
        object.__setattr__(new, name, fields.get(name, getattr(flow, name)))
    return new


def test_reference_violations_include_more():
    flow = Flow("t", (EXP, CollectStep("MEMBERS", "tso-pause", 3)), outputs=(MEMBERS_OUT,))
    names = frozenset({"tso-ready", "tso-pause"})
    assert reference_violations(flow, names) == []
    bare = _unchecked(flow, steps=(ExpectStep(("tso-ready",)), CollectStep("MEMBERS", "zz-gone", 3)))
    found = reference_violations(bare, names)
    assert [(v.step_index, v.field, v.rule) for v in found] == [
        (1, "more zz-gone", "unknown_signature")
    ]


def test_referenced_names_include_more():
    flow = Flow("t", (EXP, COL), outputs=(MEMBERS_OUT,))
    bare = _unchecked(flow, steps=(ExpectStep(("tso-ready",)), CollectStep("MEMBERS", "zz-more", 3)))
    assert _referenced_names(bare) == {"tso-ready", "zz-more"}
    assert {"tso-ready", "tso-pause"} <= _referenced_names(flow)


# --------------------------------------------------------------------------
# Replay of the seven real member pages
# --------------------------------------------------------------------------

def _members_run(stale: int = 0):
    session = ScriptedSession(states(MEMBER_PAGES, stale=stale))
    result = run(members_flow(), session)
    return result, session


def test_seven_member_pages_give_136_names_in_screen_order():
    result, session = _members_run()
    names = result.outputs["MEMBERS"].split("\n")
    assert len(names) == 136
    assert names[:3] == ["$$$INDEX", "$HISTORY", "ADDALIAS"]
    assert names[-1] == "ZAPDSCB"
    assert all(n == n.strip() and n for n in names)
    assert enters_before_clear(session) == 6
    assert_finally_ran(result.audit, handle_unmatched=True)


def test_member_names_equal_the_rows_of_the_captures():
    result, _ = _members_run()
    expected = []
    for page in MEMBER_PAGES:
        screen = capture(page)
        texts = [
            "".join(
                chr(c) if isinstance(c, int) and c else " " for c in screen.cell_grid[r][3:11]
            ).strip()
            for r in range(24)
        ]
        full = [
            "".join(chr(c) if isinstance(c, int) and c else " " for c in row).strip()
            for row in screen.cell_grid
        ]
        prompt = max(r for r, t in enumerate(full) if t)  # the *** or READY row
        first = 7 if page == MEMBER_PAGES[0] else 0
        expected += [t for t in texts[first:prompt] if t]
    assert result.outputs["MEMBERS"].split("\n") == expected


def test_collect_leaves_one_audit_record_at_the_step_index():
    result, _ = _members_run()
    recs = [r for r in result.audit if r.kind == "collect"]
    assert len(recs) == 1
    rec = recs[0]
    assert (rec.step_index, rec.phase, rec.iteration) == (COLLECT_INDEX, "steps", None)
    assert (rec.signature, rec.status) == ("tso-ready", "ok")
    assert [r.step_index for r in result.audit if r.phase == "steps"] == [0, 1]


def test_debug_log_holds_the_screen_count_and_no_row(caplog):
    with caplog.at_level(logging.DEBUG, logger="greenscreen.flow"):
        _members_run()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "kind=collect signature=tso-ready count=7" in text
    for needle in ("$$$INDEX", "ZAPDSCB", "ADDALIAS"):
        assert needle not in text


@pytest.mark.parametrize("stale", [0, 1, 2])
def test_member_replay_is_the_same_with_stale_reads(stale):
    base, _ = _members_run(0)
    result, session = _members_run(stale)
    assert result.outputs["MEMBERS"] == base.outputs["MEMBERS"]
    assert enters_before_clear(session) == 6
    assert [(r.step_index, r.kind, r.status) for r in result.audit] == [
        (r.step_index, r.kind, r.status) for r in base.audit
    ]


# --------------------------------------------------------------------------
# Replay of the three LISTCAT LEVEL(SYS2) pages
# --------------------------------------------------------------------------

def _level_run(stale: int = 0):
    session = ScriptedSession(states(LEVEL_PAGES, stale=stale))
    result = run(level_flow(), session)
    return result, session


@pytest.mark.parametrize("stale", [0, 1, 2])
def test_level_pages_give_50_lines_with_the_split_entry_adjacent(stale):
    result, session = _level_run(stale)
    lines = result.outputs["LINES"].split("\n")
    assert len(lines) == 50
    assert lines[44] == "NONVSAM ------- SYS2.SUPRTREK.HELP"
    assert lines[45] == "IN-CAT --- SYS1.MCAT.TK5"
    assert enters_before_clear(session) == 2
    assert_finally_ran(result.audit, handle_unmatched=True)


# --------------------------------------------------------------------------
# Caps
# --------------------------------------------------------------------------

def test_max_screens_3_stops_with_loop_limit_and_runs_the_finally_steps():
    flow = members_flow(max_screens=3)
    session = ScriptedSession(states(MEMBER_PAGES))
    err = run_failing(flow, session)
    assert (err.reason, err.step_index, err.kind) == ("loop_limit", COLLECT_INDEX, "collect")
    assert_finally_ran(err.audit)
    # 2 at the collect, 4 by the finally Handle through pages 4 to 7, 1 for LOGOFF
    assert enters(session) == 2 + 4 + 1
    assert ("string", "LOGOFF") in session.calls


@pytest.mark.parametrize("max_screens", [1, 2, 3, 5])
def test_collect_presses_enter_at_most_max_screens_minus_one_times(max_screens):
    flow = members_flow(max_screens=max_screens, finally_steps=())
    session = ScriptedSession(states(MEMBER_PAGES, tail=False))
    err = run_failing(flow, session)
    assert err.reason == "loop_limit"
    assert enters(session) == max_screens - 1
    assert not any(r.kind == "collect" and r.status == "ok" for r in err.audit)


def test_loop_limit_stores_no_value_and_names_no_row():
    err = run_failing(members_flow(max_screens=3), ScriptedSession(states(MEMBER_PAGES)))
    assert "MEMBERS" not in str(err.__dict__.get("outputs", ""))
    for name in ("$$$INDEX", "$HISTORY"):
        assert name not in str(err) and name not in repr(err.audit)


def test_max_rows_30_gives_loop_limit_on_page_2():
    flow = level_flow(max_rows=30, finally_steps=())
    session = ScriptedSession(states(LEVEL_PAGES, tail=False))
    err = run_failing(flow, session)
    assert (err.reason, err.step_index) == ("loop_limit", COLLECT_INDEX)
    assert enters(session) == 1  # page 2 was read; it already held more than 30 rows


def test_max_rows_30_runs_the_finally_steps():
    session = ScriptedSession(states(LEVEL_PAGES))
    err = run_failing(level_flow(max_rows=30), session)
    assert err.reason == "loop_limit"
    assert_finally_ran(err.audit)
    assert enters(session) == 1 + 1 + 1  # collect, finally Handle, LOGOFF


def test_max_rows_exactly_50_is_accepted_and_49_is_not():
    result = run(level_flow(max_rows=50), ScriptedSession(states(LEVEL_PAGES)))
    assert len(result.outputs["LINES"].split("\n")) == 50
    err = run_failing(level_flow(max_rows=49), ScriptedSession(states(LEVEL_PAGES)))
    assert err.reason == "loop_limit"


# --------------------------------------------------------------------------
# Stops that skip the finally steps, and a stop that keeps them
# --------------------------------------------------------------------------

def _blank_at(screen_number: int):
    pages = [capture(p) for p in MEMBER_PAGES]
    pages[screen_number - 1] = make_screen(24, 80)
    return [ScriptedState(s) for s in pages]


@pytest.mark.parametrize("screen_number", [3, 4])
def test_blank_page_gives_unknown_screen_after_the_step_timeout(screen_number):
    clock = FakeClock()
    session = ScriptedSession(_blank_at(screen_number))
    err = run_failing(members_flow(), session, clock=clock)
    assert (err.reason, err.step_index, err.kind) == ("unknown_screen", COLLECT_INDEX, "collect")
    assert enters(session) == screen_number - 1
    assert clock.now >= T.step
    assert_finally_skipped(err.audit)


def test_ispf_menu_as_page_3_gives_unexpected_screen_at_once():
    flow = members_flow(arming=("tso-ready", "tso-pause", "ispf-primary-menu"))
    pages = [capture(p) for p in MEMBER_PAGES]
    pages[2] = capture("ispf-primary-menu")
    clock = FakeClock()
    session = ScriptedSession([ScriptedState(s) for s in pages])
    err = run_failing(flow, session, clock=clock)
    assert (err.reason, err.step_index, err.kind) == ("unexpected_screen", COLLECT_INDEX, "collect")
    assert err.expected == ("tso-pause", "tso-ready")
    assert enters(session) == 2
    assert clock.now < T.step  # no waiting for the timeout
    assert_finally_skipped(err.audit)  # the Finding 10 limit: no held screen


def test_a_held_screen_that_is_neither_name_is_unexpected_and_keeps_the_finally_steps():
    # Expect holds tso-reenter, then collect stops at once; the finally steps run.
    fin = (
        ExpectStep(("tso-reenter",)),  # 2
        KeyStep("pa", 1),  # 3
        ExpectStep(("tso-ready",)),  # 4
    )
    flow = members_flow(arming=("tso-ready", "tso-pause", "tso-reenter"), finally_steps=fin)
    session = ScriptedSession(
        [ScriptedState(capture("tso-listds-reenter")), ScriptedState(capture("tso-ready"))]
    )
    err = run_failing(flow, session)
    assert (err.reason, err.step_index) == ("unexpected_screen", COLLECT_INDEX)
    assert err.expected == ("tso-pause", "tso-ready")
    assert ("pa", 1) in session.calls
    assert [r.status for r in finally_records(err.audit)] == ["ok", "ok", "ok"]


def _ambiguous_signatures():
    marker = (TextAtMatcher(0, 1, "AMBIGUOUS"),)
    return list(load_bundled_signatures()) + [
        ScreenSignature("amb-a", marker),
        ScreenSignature("amb-b", marker),
    ]


def test_ambiguous_screen_mid_listing_stops_with_ambiguous_screen():
    flow = members_flow(arming=("tso-ready", "tso-pause", "amb-a", "amb-b"))
    pages = [capture(p) for p in MEMBER_PAGES]
    pages[2] = make_screen(24, 80, {(0, 1): "AMBIGUOUS"})
    session = ScriptedSession([ScriptedState(s) for s in pages])
    err = run_failing(flow, session, sigs=_ambiguous_signatures())
    assert (err.reason, err.step_index, err.kind) == ("ambiguous_screen", COLLECT_INDEX, "collect")
    assert enters(session) == 2
    assert_finally_skipped(err.audit)


class _FailingSession(ScriptedSession):
    """Raises on the first read after ``after`` Enter keys."""

    def __init__(self, items, after: int) -> None:
        super().__init__(items)
        self._after = after

    def read_screen(self):
        if sum(1 for c in self.calls if c[0] == "enter") >= self._after:
            self.calls.append(("read",))
            raise OSError("scripted failure")
        return super().read_screen()


def test_session_error_mid_listing_stops_with_session_error():
    session = _FailingSession(states(MEMBER_PAGES), after=2)
    err = run_failing(members_flow(), session)
    assert (err.reason, err.step_index, err.kind) == ("session_error", COLLECT_INDEX, "collect")
    assert enters(session) == 2
    assert_finally_skipped(err.audit)
    assert "scripted failure" not in str(err)


@pytest.mark.parametrize("stale", [0, 1, 2])
def test_stop_reasons_are_the_same_with_stale_reads(stale):
    blank = ScriptedSession(
        [ScriptedState(capture(MEMBER_PAGES[0]))]
        + [ScriptedState(capture(MEMBER_PAGES[1]), stale_reads=stale)]
        + [ScriptedState(make_screen(24, 80), stale_reads=stale)]
    )
    assert run_failing(members_flow(), blank).reason == "unknown_screen"
    capped = ScriptedSession(states(MEMBER_PAGES, stale=stale))
    assert run_failing(members_flow(max_screens=3), capped).reason == "loop_limit"
    failing = _FailingSession(states(MEMBER_PAGES, stale=stale), after=2)
    assert run_failing(members_flow(), failing).reason == "session_error"
