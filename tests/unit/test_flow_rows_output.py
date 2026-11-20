"""Unit tests for Rows_Output and Flag_Output (more-flows task 4.5).

Covers Requirements 3.2 to 3.5, 3.7, 4.1 to 4.5, 4.7, 4.10 and 7.1: the YAML
form, every validator rule for outputs, the shipped ``tk5-logoff.yaml`` and
the runner on scripted captures. Examples only; nothing touches a host.
Screens come from the captures or are built in memory. No message or failure
is expected to print a row or a screen.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from greenscreen.connector.models import SFToken
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, ExtractStep, Flow, OutputSpec
from greenscreen.flow.runner import run_flow
from greenscreen.flow.validate import structural_violations
from greenscreen.flow.yamlio import from_yaml, to_yaml
from greenscreen.recognizer import ScreenSignature, load_bundled_signatures
from greenscreen.recognizer.signature import TextAtMatcher

from tests.flow_support import FakeClock, ScriptedSession, capture
from tests.screen_support import make_screen

READY = "tso-ready"
POLL = 0.25
SENTINEL = "Zq7!Kx"
_FLOWS_DIR = Path(__file__).parents[2] / "greenscreen" / "flow" / "flows"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _out(name="o", type_="str", signature=READY, row=1, col=1, length=79, **extra):
    return OutputSpec(name, type_, signature, row, col, length, **extra)


def _flow(outputs, reads=None, name="rows-demo"):
    """A Flow that expects ``READY`` and extracts each output once (or ``reads``)."""
    if reads is None:
        reads = [o.name for o in outputs]
    steps = (ExpectStep((READY,)),) + tuple(ExtractStep(n) for n in reads)
    return Flow(name, steps, outputs=tuple(outputs))


def _violations(outputs, reads=None) -> set[tuple[str, str]]:
    """Every (field, rule) pair for a Flow, built without the constructor's check."""
    if reads is None:
        reads = [o.name for o in outputs]
    steps = (ExpectStep((READY,)),) + tuple(ExtractStep(n) for n in reads)
    flow = object.__new__(Flow)
    values = {
        "name": "v", "steps": steps, "description": "", "inputs": (),
        "outputs": tuple(outputs), "finally_steps": (),
        "timeouts": Flow.__dataclass_fields__["timeouts"].default,
    }
    for key, value in values.items():
        object.__setattr__(flow, key, value)
    return {(v.field, v.rule) for v in structural_violations(flow)}


def _run(flow, screens, **kwargs):
    session = ScriptedSession(screens)
    result = run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL, **kwargs)
    return result, session


def _run_failing(flow, screens, **kwargs):
    session = ScriptedSession(screens)
    with pytest.raises(FlowError) as info:
        run_flow(flow, session, {}, clock=FakeClock(), poll_interval=POLL, **kwargs)
    return info.value, session


def _visible(err: FlowError) -> str:
    # The message, repr and args. ``err.summary`` is the designed redacted
    # screen summary (hidden cells masked); only the sentinel test inspects it.
    return " ".join([str(err), repr(err), repr(err.args)])


# --------------------------------------------------------------------------
# 3.2 YAML: key order, byte equality, plain outputs unchanged
# --------------------------------------------------------------------------

_ROWS_FLAG_FLOW = _flow(
    [
        _out("LINES", row=2, col=1, length=79, next_row=0, max_rows=10),
        _out("FOUND", "int", row=1, col=1, length=5, equals="READY"),
    ]
)

_EXPECTED_YAML = """\
version: 1
name: rows-demo
description: ''
inputs: []
outputs:
- name: LINES
  type: str
  signature: tso-ready
  row: 2
  col: 1
  length: 79
  next_row: 0
  max_rows: 10
- name: FOUND
  type: int
  signature: tso-ready
  row: 1
  col: 1
  length: 5
  equals: READY
timeouts:
  step: 10.0
  run: 120.0
  finally: 30.0
steps:
- kind: expect
  signatures:
  - tso-ready
- kind: extract
  output: LINES
- kind: extract
  output: FOUND
finally: []
"""


def test_to_yaml_emits_the_optional_keys_in_order_after_length():
    assert to_yaml(_ROWS_FLAG_FLOW) == _EXPECTED_YAML


def test_optional_output_keys_load_in_file_order():
    doc = yaml.safe_load(_ROWS_FLAG_FLOW.to_yaml())
    assert list(doc["outputs"][0]) == [
        "name", "type", "signature", "row", "col", "length", "next_row", "max_rows"
    ]
    assert list(doc["outputs"][1]) == [
        "name", "type", "signature", "row", "col", "length", "equals"
    ]


def test_yaml_round_trip_keeps_rows_and_flag_outputs():
    sigs = load_bundled_signatures()
    again = from_yaml(_EXPECTED_YAML, sigs)
    assert again == _ROWS_FLAG_FLOW
    assert again.outputs[0].max_rows == 10 and again.outputs[0].next_row == 0
    assert again.outputs[1].equals == "READY"
    assert again.to_yaml() == _EXPECTED_YAML


def test_output_without_the_three_keys_is_emitted_as_before():
    text = _flow([_out("PLAIN", row=3, col=2, length=9)]).to_yaml()
    assert "outputs:\n- name: PLAIN\n  type: str\n  signature: tso-ready\n" in text
    assert "  row: 3\n  col: 2\n  length: 9\ntimeouts:" in text
    for key in ("next_row", "max_rows", "equals"):
        assert key not in text


def test_next_row_zero_is_emitted_because_it_is_not_none():
    text = _flow([_out(max_rows=3, next_row=0)]).to_yaml()
    assert "  next_row: 0\n  max_rows: 3\n" in text


def test_shipped_logoff_yaml_equals_to_yaml_byte_for_byte():
    raw = (_FLOWS_DIR / "tk5-logoff.yaml").read_bytes().decode("utf-8")
    flow = from_yaml(raw, load_bundled_signatures())
    assert flow.to_yaml() == raw


# --------------------------------------------------------------------------
# 3.3, 3.4, 3.5, 7.1 validator rules for outputs
# --------------------------------------------------------------------------

def test_valid_rows_and_flag_outputs_have_no_violation():
    assert _violations(list(_ROWS_FLAG_FLOW.outputs)) == set()
    assert _violations([_out(max_rows=1), _out("B", max_rows=500, next_row=23)]) == set()


def test_rows_requires_str():
    found = _violations([_out(type_="int", max_rows=5)])
    assert ("output o.max_rows", "rows_requires_str") in found


@pytest.mark.parametrize("max_rows", [0, -1, 501])
def test_max_rows_out_of_range(max_rows):
    assert ("output o.max_rows", "out_of_range") in _violations([_out(max_rows=max_rows)])


@pytest.mark.parametrize("next_row", [-1, 24])
def test_next_row_out_of_range(next_row):
    found = _violations([_out(max_rows=5, next_row=next_row)])
    assert ("output o.next_row", "out_of_range") in found


def test_next_row_requires_rows():
    found = _violations([_out(next_row=0)])
    assert ("output o.next_row", "next_row_requires_rows") in found


def test_equals_requires_int():
    assert ("output o.equals", "equals_requires_int") in _violations([_out(equals="READY")])


@pytest.mark.parametrize("text", ["", "caf\u00e9", "x" * 81])
def test_equals_invalid_text(text):
    found = _violations([_out(type_="int", length=80, col=0, equals=text)])
    assert ("output o.equals", "invalid_text") in found


def test_equals_longer_than_region():
    found = _violations([_out(type_="int", length=3, equals="abcd")])
    assert ("output o.equals", "longer_than_region") in found
    assert ("output o.equals", "longer_than_region") not in _violations(
        [_out(type_="int", length=4, equals="abcd")]
    )


def test_equals_excludes_rows():
    found = _violations([_out(type_="int", length=5, equals="X", max_rows=5)])
    assert ("output o.equals", "equals_excludes_rows") in found


@pytest.mark.parametrize("text", [" X", "X ", " X "])
def test_equals_blank_edge_for_a_leading_or_trailing_blank(text):
    found = _violations([_out(type_="int", length=5, equals=text)])
    assert ("output o.equals", "equals_blank_edge") in found


def test_equals_with_inner_blank_is_accepted():
    assert _violations([_out(type_="int", length=5, equals="A B")]) == set()


@pytest.mark.parametrize("reads", [[], ["o", "o"]])
def test_rows_output_needs_exactly_one_read(reads):
    found = _violations([_out(max_rows=5)], reads=reads)
    assert ("output o", "needs_exactly_one_read") in found
    assert ("output o", "needs_exactly_one_extract") not in found


@pytest.mark.parametrize("reads", [[], ["o", "o"]])
def test_plain_output_still_reports_needs_exactly_one_extract(reads):
    found = _violations([_out()], reads=reads)
    assert ("output o", "needs_exactly_one_extract") in found
    assert ("output o", "needs_exactly_one_read") not in found


def test_region_exceeds_row_for_a_rows_output():
    found = _violations([_out(col=70, length=20, max_rows=5)])
    assert ("output o.length", "region_exceeds_row") in found


def test_constructor_rejects_a_bad_output_with_rule_names_only():
    with pytest.raises(Exception) as info:
        _flow([_out(type_="int", max_rows=5)])
    assert type(info.value).__name__ == "FlowDefinitionError"
    assert str(info.value) == "flow: output o.max_rows: rows_requires_str"


def test_violation_messages_hold_no_equals_text():
    flow = object.__new__(Flow)
    bad = _out(type_="int", length=5, equals=" PROBE")
    for key, value in {
        "name": "v", "steps": (ExpectStep((READY,)), ExtractStep("o")),
        "description": "", "inputs": (), "outputs": (bad,), "finally_steps": (),
        "timeouts": Flow.__dataclass_fields__["timeouts"].default,
    }.items():
        object.__setattr__(flow, key, value)
    for v in structural_violations(flow):
        assert "PROBE" not in repr(v)


# --------------------------------------------------------------------------
# 4.1 to 4.5 runner: rows on real captures
# --------------------------------------------------------------------------

def test_rows_on_time_output_is_the_one_line_of_row_1():
    flow = _flow([_out("o", row=1, col=1, length=79, max_rows=5)])
    result, session = _run(flow, [capture("tso-time-output")])
    assert result.outputs["o"] == (
        "TIME-09:36:45 PM. CPU-00:00:00 SERVICE-7578 SESSION-00:00:06 NOVEMBER 19,2026"
    )
    assert type(result.outputs["o"]) is str
    assert session.calls == [("read",)]  # extract adds no Session call
    assert [r.kind for r in result.audit] == ["expect", "extract"]


def test_rows_on_listcat_output_are_seven_names_joined_by_lf():
    flow = _flow([_out("o", row=2, col=1, length=79, max_rows=20)])
    result, _ = _run(flow, [capture("tso-listcat-output")])
    lines = result.outputs["o"].split("\n")
    assert len(lines) == 7
    assert [ln.split(".", 1)[1] for ln in lines] == [
        "CMDPROC", "EXEC", "ISP.PLIB", "ISP.PROF", "TEST.ASM", "TEST.CNTL", "TEST.LOADLIB",
    ]
    assert len({ln.split(".")[0] for ln in lines}) == 1  # one user id prefix
    assert all(ln == ln.strip() and ln for ln in lines)


def test_rows_exactly_at_max_rows_are_accepted():
    flow = _flow([_out("o", row=2, max_rows=7)])
    result, _ = _run(flow, [capture("tso-listcat-output")])
    assert len(result.outputs["o"].split("\n")) == 7


@pytest.mark.parametrize(
    ("capture_name", "row"),
    [("tso-time-output", 2), ("tso-time-output", 20), ("tso-listcat-output", 9),
     ("tso-listcat-output", 23)],
)
def test_row_at_or_after_the_prompt_row_gives_the_empty_string(capture_name, row):
    flow = _flow([_out("o", row=row, col=1, length=79, max_rows=5)])
    result, _ = _run(flow, [capture(capture_name)])
    assert result.outputs["o"] == ""
    assert type(result.outputs["o"]) is str


def test_the_prompt_row_itself_is_never_read():
    flow = _flow([_out("o", row=8, col=1, length=79, max_rows=5)])
    result, _ = _run(flow, [capture("tso-listcat-output")])
    assert result.outputs["o"].endswith("TEST.LOADLIB")
    assert "READY" not in result.outputs["o"]
    assert "\n" not in result.outputs["o"]


def test_rows_over_max_rows_stop_with_loop_limit_and_no_value():
    screen = capture("tso-listcat-output")
    prefix = "".join(chr(c) for c in screen.cell_grid[2][1:7])
    flow = _flow([_out("o", row=2, col=1, length=79, max_rows=6)])
    err, session = _run_failing(flow, [screen])
    assert err.reason == "loop_limit"
    assert err.step_index == 1
    assert err.kind == "extract"
    assert str(err) == "loop_limit at step 1 (extract): expected none (0); output o"
    assert [r.status for r in err.audit] == ["ok", "failed"]
    assert session.calls == [("read",)]
    assert prefix not in _visible(err)  # no row text in the failure
    assert "CMDPROC" not in _visible(err)


def _screen_with_hidden_row():
    screen = capture("tso-listcat-output")
    row = 3
    screen.cell_grid[row][0] = SFToken(0xCC)  # hidden, protected-off field start
    for i, ch in enumerate(SENTINEL):
        screen.cell_grid[row][2 + i] = ord(ch)
    screen.cell_grid[row][79] = SFToken(0xE0)  # closes the hidden field
    return screen


def test_hidden_cell_in_a_read_row_stops_with_hidden_output():
    flow = _flow([_out("o", row=2, col=1, length=79, max_rows=20)])
    err, session = _run_failing(flow, [_screen_with_hidden_row()])
    assert err.reason == "hidden_output"
    assert err.step_index == 1
    assert err.kind == "extract"
    assert str(err) == "hidden_output at step 1 (extract): expected none (0); output o"
    assert session.calls == [("read",)]
    assert SENTINEL not in _visible(err)
    assert SENTINEL not in repr(err.summary)  # hidden cells are masked in the summary
    assert "CMDPROC" not in _visible(err)


def test_hidden_cell_in_a_row_that_is_not_read_does_not_stop_the_run():
    flow = _flow([_out("o", row=5, col=1, length=79, max_rows=20)])
    result, _ = _run(flow, [_screen_with_hidden_row()])
    assert result.outputs["o"].count("\n") == 3  # rows 5 to 8
    assert SENTINEL not in result.outputs["o"]


_TINY = ScreenSignature("tiny", (TextAtMatcher(0, 0, "TINY"),))


@pytest.mark.parametrize(("rows", "columns"), [(23, 80), (24, 79), (12, 40)])
def test_screen_smaller_than_24_by_80_stops_with_screen_size(rows, columns):
    screen = make_screen(rows, columns, {(0, 0): "TINY", (1, 0): "SECRETISH"})
    flow = Flow(
        "t",
        (ExpectStep(("tiny",)), ExtractStep("o")),
        outputs=(_out("o", signature="tiny", row=1, col=0, length=9, max_rows=5),),
    )
    err, session = _run_failing(flow, [screen], signatures=[_TINY])
    assert err.reason == "screen_size"
    assert err.step_index == 1
    assert err.kind == "extract"
    assert str(err) == "screen_size at step 1 (extract): expected none (0); output o"
    assert session.calls == [("read",)]
    assert "SECRETISH" not in _visible(err)


def test_plain_output_is_unchanged_by_the_rows_code():
    flow = _flow([_out("o", row=2, col=1, length=79)])
    result, _ = _run(flow, [capture("tso-listcat-output")])
    value = result.outputs["o"]
    assert "\n" not in value
    assert value.split(".", 1)[1] == "CMDPROC"  # row 2 only, not the rows below


def test_plain_int_output_still_follows_the_digit_rule():
    flow = _flow([_out("o", "int", row=1, col=1, length=4)])
    err, _ = _run_failing(flow, [capture("tso-time-output")])  # text "TIME"
    assert err.reason == "output_type"
    assert str(err) == "output_type at step 1 (extract): expected none (0); output o"
