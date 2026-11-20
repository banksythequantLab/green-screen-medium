# Feature: more-flows, Property 1: Rows extraction matches the reference model
"""Properties 1, 2 and 7 of the more-flows spec (task 4.9).

Property 1: a Rows_Output read matches a reference model written here.
Property 2: hidden cells never reach a value or any output.
Property 7: ``Flow.from_yaml(flow.to_yaml()) == flow`` over ``COMMAND_FLOWS``.

No live host: screens are built in memory. Verdicts are booleans; a row or probe is
never formatted into a failure message.
"""
from __future__ import annotations

import logging
import traceback

from hypothesis import event, given, settings
from hypothesis import strategies as st

from greenscreen.connector import Screen
from greenscreen.flow import FlowError, run_flow
from greenscreen.flow.model import ExpectStep, ExtractStep, Flow, OutputSpec
from greenscreen.recognizer import ScreenSignature, load_bundled_signatures
from greenscreen.recognizer.signature import TextAtMatcher
from tests.flow_support import FakeClock, ScriptedSession
from tests.property._collect_support import line_screen
from tests.property._flow_strategies import COMMAND_FLOWS
from tests.screen_support import make_screen

_TINY = ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),))
_LINE_ALPHABET = "abcdefgh 01234"  # no '*', no upper case: the pause and READY rows stay distinct
_VISIBLE_ALPHABET = "ABCDEF 012"
_PROBE_ALPHABET = "\u00a7\u00b6\u00a4"  # in no visible text, log or traceback
_BUNDLED = load_bundled_signatures()


# --------------------------------------------------------------------------
# Reference model (reads cell_grid directly, shares no code with the runner)
# --------------------------------------------------------------------------

def _row_text(screen: Screen, r: int, hidden: frozenset[int] = frozenset()) -> str:
    out = []
    for c, cell in enumerate(screen.cell_grid[r]):
        linear = r * screen.columns + c
        if linear in hidden or not isinstance(cell, int) or cell == 0:
            out.append(" ")
        else:
            out.append(chr(cell))
    return "".join(out)


def _reference(
    screen: Screen, row: int, col: int, length: int, hidden: frozenset[int] = frozenset()
) -> tuple[list[str], bool]:
    """(stripped non-empty region texts of rows ``row`` to P-1, a hidden cell was read)."""
    prompt = -1
    for r in range(screen.rows - 1, -1, -1):
        if _row_text(screen, r, hidden).strip(" "):
            prompt = r
            break
    lines: list[str] = []
    for r in range(row, prompt):
        if any(r * screen.columns + c in hidden for c in range(col, col + length)):
            return [], True
        text = _row_text(screen, r, hidden)[col : col + length].strip(" ")
        if text:
            lines.append(text)
    return lines, False


def _flow(row: int, col: int, length: int, max_rows: int) -> Flow:
    return Flow(
        "rows",
        (ExpectStep(("tiny",), (), 1.0), ExtractStep("OUT")),
        outputs=(OutputSpec("OUT", "str", "tiny", row, col, length, None, max_rows),),
    )


def _baseline_flow() -> Flow:
    return Flow("base", (ExpectStep(("tiny",), (), 1.0),))


def _with_tiny(screen: Screen) -> Screen:
    for i, ch in enumerate("TINY"):
        screen.cell_grid[0][i] = ord(ch)
    return screen


# --------------------------------------------------------------------------
# Property 1
# --------------------------------------------------------------------------

@st.composite
def _row_cases(draw):
    last = draw(st.sampled_from(("pause", "ready", "none")))
    lcol = draw(st.integers(0, 30))
    first_row = draw(st.integers(1, 6))
    room = (22 if last == "ready" else 23) - first_row
    lines = draw(
        st.lists(
            st.text(alphabet=_LINE_ALPHABET, min_size=1, max_size=80 - lcol),
            min_size=min(room, draw(st.integers(0, 6))),
            max_size=room,
        )
    )
    screen = _with_tiny(line_screen(lines, first_row=first_row, last=last, col=lcol))
    row = draw(st.one_of(st.integers(0, first_row), st.integers(0, 23)))
    col = draw(st.one_of(st.integers(0, lcol), st.integers(0, 79)))
    length = draw(st.integers(1, 80 - col))
    ref, _ = _reference(screen, row, col, length)
    # Centre the limit on the reference count so both sides of the boundary occur.
    max_rows = draw(
        st.one_of(
            st.integers(1, 30),
            st.integers(-1, 1).map(lambda d: max(1, len(ref) + d)),
        )
    )
    return screen, last, row, col, length, max_rows


@settings(max_examples=200, deadline=None)
@given(_row_cases())
def test_rows_extraction_matches_the_reference_model(case):
    """**Validates: Requirements 4.1, 4.3, 4.5, 4.8**"""
    screen, last, row, col, length, max_rows = case
    expected, _ = _reference(screen, row, col, length)
    flow = _flow(row, col, length, max_rows)

    baseline = ScriptedSession([screen])
    run_flow(_baseline_flow(), baseline, {}, signatures=[_TINY], clock=FakeClock())
    session = ScriptedSession([screen])
    try:
        result = run_flow(flow, session, {}, signatures=[_TINY], clock=FakeClock())
        error = None
    except FlowError as caught:
        result, error = None, caught

    over = len(expected) > max_rows
    event(f"loop_limit={over}")
    if over:
        assert error is not None and error.reason == "loop_limit"
        assert error.step_index == 1
    else:
        assert error is None and result is not None
        value = result.outputs["OUT"]
        assert value == "\n".join(expected)
        assert (value.split("\n") if expected else []) == expected
        assert all("\n" not in line and line == line.strip(" ") and line for line in expected)
        # Nothing of the prompt row: its text is " ***" or " READY".
        if last == "pause":
            assert "***" not in value
        if last == "ready":
            assert "READY" not in value
    # The extract step sends nothing: the calls equal those of an Expect-only run.
    assert session.calls == baseline.calls


# --------------------------------------------------------------------------
# Property 2
# --------------------------------------------------------------------------

@st.composite
def _hidden_cases(draw):
    rows = draw(
        st.lists(
            st.tuples(
                st.integers(1, 23),
                st.integers(0, 40),
                st.text(alphabet=_VISIBLE_ALPHABET, min_size=1, max_size=39),
            ),
            max_size=8,
        )
    )
    text = {(0, 0): "TINY"}
    for r, c, s in rows:
        text[(r, c)] = s
    start = draw(st.integers(4, 1900))
    size = draw(st.integers(1, min(300, 1918 - start)))
    end = start + size + 1  # the closing field start; hidden data cells are start+1 .. end-1
    probe = draw(st.text(alphabet=_PROBE_ALPHABET, min_size=1, max_size=min(size, 8)))
    columns = 80
    screen = make_screen(
        24,
        columns,
        text,
        [(start // columns, start % columns, 0xCC), (end // columns, end % columns, 0xE0)],
    )
    for i, ch in enumerate(probe):
        r, c = divmod(start + 1 + i, columns)
        screen.cell_grid[r][c] = ord(ch)
    hidden = frozenset(range(start + 1, end))
    # Make a read of the hidden range likely: half of the regions are wide.
    wide = draw(st.booleans())
    row = draw(st.integers(0, 22))
    col = 0 if wide else draw(st.integers(0, 79))
    length = 80 if wide else draw(st.integers(1, 80 - col))
    return screen, hidden, probe, row, col, length


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _holds(value, probe: str, depth: int = 0) -> bool:
    if isinstance(value, Screen):
        return True
    if isinstance(value, str):
        return probe in value
    if depth > 6:
        return False
    if isinstance(value, dict):
        return any(_holds(k, probe, depth + 1) or _holds(v, probe, depth + 1) for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_holds(v, probe, depth + 1) for v in value)
    return False


def _frames_hold(err: BaseException, probe: str) -> bool:
    tb = err.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if str(frame.f_globals.get("__name__", "")).startswith("greenscreen.flow"):
            if any(_holds(v, probe) for v in list(frame.f_locals.values())):
                return True
        tb = tb.tb_next
    return False


# Feature: more-flows, Property 2: Hidden cells never reach a value or any output
@settings(max_examples=200, deadline=None)
@given(_hidden_cases())
def test_hidden_cells_never_reach_a_value_or_any_output(case):
    """**Validates: Requirements 4.2, 4.9**"""
    screen, hidden, probe, row, col, length = case
    expected, hit = _reference(screen, row, col, length, hidden)
    flow = _flow(row, col, length, 500)
    session = ScriptedSession([screen])

    logger = logging.getLogger("greenscreen.flow")
    handler = _Collect()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    error: FlowError | None = None
    result = None
    try:
        try:
            result = run_flow(flow, session, {}, signatures=[_TINY], clock=FakeClock())
        except FlowError as caught:
            error = caught
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    event(f"hidden_read={hit}")
    texts: list[str] = []
    if hit:
        assert error is not None and error.reason == "hidden_output"
        assert error.step_index == 1
    else:
        assert error is None and result is not None
        assert result.outputs["OUT"] == "\n".join(expected)
    if result is not None:
        texts += [repr(result), str(result), repr(dict(result.outputs))]
        texts += [repr(r) for r in result.audit]
    if error is not None:
        texts += [str(error), repr(error), repr(error.args), repr(vars(error))]
        if error.summary is not None:
            texts += [repr(error.summary), error.summary.to_text()]
        texts += [repr(r) for r in error.audit]
        texts.append("".join(traceback.format_exception(error)))
        assert not _frames_hold(error, probe)
    for record in handler.records:
        texts += [str(record.msg), record.getMessage(), repr(record.args)]
    assert not any(probe in text for text in texts)


# --------------------------------------------------------------------------
# Property 7
# --------------------------------------------------------------------------

# Feature: more-flows, Property 7: Flow YAML round trip
@settings(max_examples=150, deadline=None)
@given(COMMAND_FLOWS)
def test_command_flow_yaml_round_trip(flow: Flow) -> None:
    """**Validates: Requirements 3.1, 3.2, 3.6, 5.1**"""
    text = flow.to_yaml()
    assert Flow.from_yaml(text, _BUNDLED) == flow
    assert flow.to_yaml() == text
