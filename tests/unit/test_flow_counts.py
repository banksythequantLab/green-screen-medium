"""Unit tests for the Count_Output, ``OutputSpec.counts`` (polish task 4.2).

Model, YAML and validator rules first, then runs over the scripted pages of
``tests/property/_collect_support.py``. The Flows are built here; nothing touches a host.
A failure message never prints a row.
"""
from __future__ import annotations

import dataclasses
import logging

import pytest

from greenscreen.flow.errors import FlowDefinitionError, FlowError
from greenscreen.flow.model import (
    CollectStep,
    ExpectStep,
    ExtractStep,
    Flow,
    OutputSpec,
    Timeouts,
)
from greenscreen.flow.runner import run_flow
from greenscreen.flow.validate import reference_violations
from greenscreen.flow import yamlio
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import FakeClock, ScriptedSession, ScriptedState
from tests.property._collect_support import page_sequence

T = Timeouts(step=2.0, run=60.0, finally_=30.0)
ARMING = ("tso-ready", "tso-pause")

LINES = OutputSpec(
    "LINES", "str", "tso-ready", 1, 1, 79, next_row=0, max_rows=100
)
COUNT = OutputSpec("N", "int", "tso-ready", 1, 1, 79, counts="LINES")


def _collect_steps(max_screens: int = 5):
    return (ExpectStep(ARMING), CollectStep("LINES", "tso-pause", max_screens))


def _flow(*outputs: OutputSpec, steps=None) -> Flow:
    return Flow(
        "counts-test",
        steps if steps is not None else _collect_steps(),
        outputs=outputs,
        timeouts=T,
    )


def _definition_error(*outputs: OutputSpec, steps=None) -> str:
    with pytest.raises(FlowDefinitionError) as info:
        _flow(*outputs, steps=steps)
    return str(info.value)


# --------------------------------------------------------------------------
# Model and YAML
# --------------------------------------------------------------------------

def test_counts_defaults_to_none_and_is_the_last_member():
    assert OutputSpec("o", "str", "s", 0, 0, 1).counts is None
    assert dataclasses.fields(OutputSpec)[-1].name == "counts"
    assert dataclasses.fields(OutputSpec)[-2].name == "equals"


def test_positional_construction_still_works():
    short = OutputSpec("o", "str", "s", 0, 0, 1)
    assert (short.next_row, short.max_rows, short.equals, short.counts) == (None,) * 4
    nine = OutputSpec("o", "str", "s", 0, 0, 1, 2, 3, "E")
    assert (nine.next_row, nine.max_rows, nine.equals, nine.counts) == (2, 3, "E", None)


def test_yaml_key_comes_after_equals():
    assert list(yamlio._OUTPUT_OPTIONAL)[-2:] == ["equals", "counts"]


def test_count_output_round_trips_through_yaml_after_the_base_keys():
    flow = _flow(LINES, COUNT)
    text = flow.to_yaml()
    lines = [ln.strip() for ln in text.splitlines()]
    at = lines.index("- name: N") if "- name: N" in lines else None
    assert at is not None
    block = lines[at : at + 8]
    keys = [ln.split(":")[0].lstrip("- ") for ln in block]
    assert keys[:7] == ["name", "type", "signature", "row", "col", "length", "counts"]
    assert Flow.from_yaml(text, load_bundled_signatures()) == flow


# --------------------------------------------------------------------------
# Validator rules
# --------------------------------------------------------------------------

def test_valid_count_output_with_only_the_rows_read_is_accepted():
    flow = _flow(LINES, COUNT)
    assert flow.outputs[1].counts == "LINES"


def test_counts_requires_int():
    msg = _definition_error(LINES, dataclasses.replace(COUNT, type="str"))
    assert "output N.counts" in msg and "counts_requires_int" in msg


def test_counts_excludes_extras():
    msg = _definition_error(LINES, dataclasses.replace(COUNT, equals="X"))
    assert "output N.counts" in msg and "counts_excludes_extras" in msg


def test_counts_unknown_output():
    msg = _definition_error(LINES, dataclasses.replace(COUNT, counts="NOPE"))
    assert "output N.counts" in msg and "counts_unknown_output" in msg


def test_counts_naming_itself_is_unknown_output():
    msg = _definition_error(LINES, dataclasses.replace(COUNT, counts="N"))
    assert "output N.counts" in msg and "counts_unknown_output" in msg


def test_counts_target_not_rows():
    plain = OutputSpec("PLAIN", "str", "tso-ready", 1, 1, 79)
    count = dataclasses.replace(COUNT, counts="PLAIN")
    msg = _definition_error(
        plain, count, steps=(ExpectStep(ARMING), ExtractStep("PLAIN"))
    )
    assert "output N.counts" in msg and "counts_target_not_rows" in msg


@pytest.mark.parametrize("member", ["signature", "row", "col", "length"])
def test_counts_region_mismatch(member):
    changed = {"signature": "tso-pause", "row": 2, "col": 0, "length": 40}[member]
    msg = _definition_error(LINES, dataclasses.replace(COUNT, **{member: changed}))
    assert "output N.counts" in msg and "counts_region_mismatch" in msg


def test_counts_not_readable_for_extract():
    steps = (ExpectStep(ARMING), ExtractStep("N"), CollectStep("LINES", "tso-pause", 5))
    msg = _definition_error(LINES, COUNT, steps=steps)
    assert "step 1" in msg and "counts_not_readable" in msg


def test_counts_not_readable_for_collect():
    steps = (
        ExpectStep(ARMING),
        CollectStep("LINES", "tso-pause", 5),
        CollectStep("N", "tso-pause", 5),
    )
    msg = _definition_error(LINES, COUNT, steps=steps)
    assert "step 2" in msg and "counts_not_readable" in msg


def test_count_output_changes_no_signature_reference():
    names = frozenset({"tso-pause"})  # "tso-ready" is missing on purpose
    with_count = _flow(LINES, COUNT)
    without = _flow(LINES)
    assert reference_violations(with_count, frozenset(ARMING)) == []

    def unknown(flow):
        return {v.field.split()[-1] for v in reference_violations(flow, names)}

    assert unknown(with_count) == unknown(without) == {"tso-ready"}
    assert _flow(LINES, COUNT).steps == without.steps


# --------------------------------------------------------------------------
# Runtime
# --------------------------------------------------------------------------

def _session(seq) -> ScriptedSession:
    return ScriptedSession(seq.states())


def _run(flow: Flow, seq):
    return run_flow(flow, _session(seq), {}, clock=FakeClock())


def test_three_pages_of_five_lines_count_15():
    seq = page_sequence([5, 5, 5])
    out = _run(_flow(LINES, COUNT), seq).outputs
    assert out["LINES"].split("\n") == list(seq.all_tokens)
    assert len(out["LINES"].split("\n")) == 15
    assert out["N"] == 15 and type(out["N"]) is int


def test_empty_listing_gives_empty_value_and_count_0():
    out = _run(_flow(LINES, COUNT), page_sequence([0])).outputs
    assert out["LINES"] == ""
    assert "N" in out and out["N"] == 0 and type(out["N"]) is int


def test_extract_of_a_rows_output_sets_the_count():
    seq = page_sequence([3])
    rows = OutputSpec("LINES", "str", "tso-ready", 1, 1, 79, max_rows=10)
    count = dataclasses.replace(COUNT, row=1)
    flow = _flow(
        rows, count, steps=(ExpectStep(("tso-ready",)), ExtractStep("LINES"))
    )
    out = _run(flow, seq).outputs
    assert out["LINES"].split("\n") == list(seq.all_tokens)
    assert out["N"] == 3 and type(out["N"]) is int


def test_loop_limit_stop_returns_no_outputs_and_no_row_text():
    seq = page_sequence([5, 5, 5])
    with pytest.raises(FlowError) as info:
        _run(_flow(LINES, COUNT, steps=_collect_steps(2)), seq)
    err = info.value
    assert err.reason == "loop_limit"
    assert getattr(err, "outputs", None) in (None, {}, ())
    for token in seq.all_tokens:
        assert token not in repr(err) and token not in str(err)


def test_result_repr_and_log_records_hold_no_row_text(caplog):
    seq = page_sequence([5, 5, 5])
    with caplog.at_level(logging.DEBUG, logger="greenscreen.flow"):
        result = _run(_flow(LINES, COUNT), seq)
    shown = repr(result) + "\n".join(r.getMessage() for r in caplog.records)
    shown += "".join(repr(r.args) + str(r.msg) for r in caplog.records)
    assert caplog.records
    for token in seq.all_tokens:
        assert token not in shown.replace(repr(dict(result.outputs)), "")
