# Feature: more-flows, Property 5: The flag value is 1 exactly when the stripped region text equals `equals`
"""Property 5 of the more-flows spec (task 4.11).

A Flag_Output stores 1 when the stripped region text equals ``equals`` and 0
otherwise. The value is always 0 or 1. No live host: the screen is built in memory.
"""
from __future__ import annotations

from hypothesis import event, given, settings
from hypothesis import strategies as st

from greenscreen.flow import run_flow
from greenscreen.flow.model import ExpectStep, ExtractStep, Flow, OutputSpec
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher
from tests.flow_support import FakeClock, ScriptedSession
from tests.screen_support import make_screen

_TINY = ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),))
_PRINTABLE = st.characters(min_codepoint=0x20, max_codepoint=0x7E)


def _no_blank_edge(text: str) -> bool:
    return text[0] != " " and text[-1] != " "


_TEXT = st.text(alphabet=_PRINTABLE, min_size=1, max_size=20).filter(_no_blank_edge)


@st.composite
def _cases(draw):
    equals = draw(_TEXT)
    same = draw(st.booleans())
    region = equals if same else draw(_TEXT)
    pad_left = draw(st.integers(0, 5))
    pad_right = draw(st.integers(0, 5))
    shown = " " * pad_left + region + " " * pad_right
    row = draw(st.integers(1, 23))
    # The region may be wider than the shown text; equals always fits it.
    min_length = max(len(shown), len(equals))
    col = draw(st.integers(0, 80 - min_length))
    length = draw(st.integers(min_length, 80 - col))
    return equals, region, shown, row, col, length


@settings(max_examples=200, deadline=None)
@given(_cases())
def test_flag_value_is_one_exactly_when_stripped_text_equals(case):
    """**Validates: Requirements 7.2, 7.4**"""
    equals, region, shown, row, col, length = case
    screen = make_screen(24, 80, {(0, 0): "TINY", (row, col): shown}, [])
    flow = Flow(
        "flag",
        (ExpectStep(("tiny",), (), 1.0), ExtractStep("FOUND")),
        outputs=(OutputSpec("FOUND", "int", "tiny", row, col, length, None, None, equals),),
    )
    result = run_flow(flow, ScriptedSession([screen]), {}, signatures=[_TINY], clock=FakeClock())
    value = result.outputs["FOUND"]
    expected = 1 if region == equals else 0
    event(f"flag={expected}")
    assert type(value) is int and value in (0, 1)
    assert value == expected
    if region == equals:
        assert value == 1
