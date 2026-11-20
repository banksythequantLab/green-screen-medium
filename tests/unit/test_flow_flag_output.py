"""Unit tests for the Flag_Output (more-flows task 4.7).

Covers Requirements 7.2, 7.3, 7.5 and 7.6. Screens come from the real captures
through ``tests.flow_support``; the Flows are test-only; nothing touches a host.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, ExtractStep, Flow, OutputSpec
from greenscreen.flow.runner import run_flow
from greenscreen.publisher.registry import build_schemas

from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    capture,
    sentinel_password_screen,
)

READY = "tso-ready"
EQUALS = "--RECFM-LRECL-BLKSIZE-DSORG"
SENTINEL = "Zq7!Kx"

FLAG = OutputSpec("FOUND", "int", READY, 2, 1, 27, equals=EQUALS)
DETAILS = OutputSpec("DETAILS", "str", READY, 3, 1, 79, max_rows=10)


def _flow(*outputs: OutputSpec, first: str = READY) -> Flow:
    steps = (ExpectStep((first,)),) + tuple(ExtractStep(o.name) for o in outputs)
    return Flow("t", steps, outputs=tuple(outputs))


def _run(flow: Flow, screen):
    return run_flow(
        flow, ScriptedSession([screen]), {}, clock=FakeClock(), poll_interval=0.25
    )


def _outputs(result) -> dict:
    return dict(result.outputs)


def test_found_on_listds_output_gives_flag_1_and_three_detail_lines() -> None:
    out = _outputs(_run(_flow(FLAG, DETAILS), capture("tso-listds-output")))
    assert out["FOUND"] == 1
    assert out["DETAILS"] == "\n".join(["FB    80    27920   PO", "--VOLUMES--", "TSO001"])


def test_missing_data_set_gives_flag_0_and_empty_details() -> None:
    out = _outputs(_run(_flow(FLAG, DETAILS), capture("tso-listds-not-in-catalog")))
    assert out["FOUND"] == 0
    assert out["DETAILS"] == ""


def test_flag_value_is_a_plain_int_0_or_1() -> None:
    for name, want in (("tso-listds-output", 1), ("tso-listds-not-in-catalog", 0)):
        value = _outputs(_run(_flow(FLAG), capture(name)))["FOUND"]
        assert type(value) is int and value == want


def test_inner_blank_difference_gives_0() -> None:
    screen = capture("tso-listds-output")
    # Row 2 col 1 holds "--RECFM-...": blank the "-" after RECFM (col 1 + 7).
    assert screen.cell_grid[2][1 + 7] == ord("-")
    screen.cell_grid[2][1 + 7] = ord(" ")
    assert _outputs(_run(_flow(FLAG), screen))["FOUND"] == 0


def test_hidden_cell_in_flag_region_stops_with_hidden_output() -> None:
    flag = OutputSpec("FOUND", "int", "tso-password-prompt", 1, 0, 4, equals="X")
    flow = _flow(flag, first="tso-password-prompt")
    with pytest.raises(FlowError) as info:
        _run(flow, sentinel_password_screen(SENTINEL))
    err = info.value
    assert err.reason == "hidden_output"
    assert err.kind == "extract"
    assert SENTINEL not in " ".join([str(err), repr(err), repr(err.args)])


def test_flag_output_schema_through_the_registry_is_integer() -> None:
    _, out, success = build_schemas(_flow(FLAG), frozenset())
    assert out["properties"]["FOUND"] == {"type": "integer"}
    assert success["properties"]["outputs"]["properties"]["FOUND"] == {"type": "integer"}
