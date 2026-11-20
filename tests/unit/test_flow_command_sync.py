"""The five Command_Flows must share logon, exit, closing and finally steps exactly.

Spec more-flows, task 8.8 (Requirements 8.4, 10.1 to 10.4). ``test_flow_sync.py``
keeps asserting the three older Flows and is not edited. The expected steps are
written out here, independent of the shipped files.
"""
from __future__ import annotations

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.model import (
    CollectStep,
    ExpectStep,
    ExtractStep,
    HandleStep,
    KeyStep,
    TypeStep,
    plan,
)

COMMAND_FLOWS = (
    "tk5-time",
    "tk5-list-datasets",
    "tk5-dataset-info",
    "tk5-library-members",
    "tk5-job-status",
)

# (last main plan index, first finally index, last finally index), design section 6.
PLAN_INDICES = {
    "tk5-time": (40, 41, 53),
    "tk5-list-datasets": (40, 41, 53),
    "tk5-dataset-info": (43, 44, 56),
    "tk5-library-members": (42, 43, 55),
    "tk5-job-status": (40, 41, 53),
}

ENTER = KeyStep(key="enter")
CLEAR = KeyStep(key="clear")


def _expect(*names):
    return ExpectStep(signatures=tuple(names))


EXIT_FRAGMENT = (
    TypeStep(text="X"),
    ENTER,
    _expect("tso-ready"),
    CLEAR,
    _expect("tso-cleared"),
)

CLOSING_TAIL = (
    CLEAR,
    _expect("tso-cleared"),
    TypeStep(text="LOGOFF"),
    ENTER,
    _expect("tk5-logon"),
)

FINALLY_BLOCK = (
    HandleStep(
        signature="ispf-primary-menu", max_count=1, settle=0.0,
        steps=(TypeStep(text="X"), ENTER),
    ),
    HandleStep(signature="tso-pause", max_count=20, settle=0.0, steps=(ENTER,)),
    HandleStep(
        signature="tso-reenter", max_count=3, settle=0.0,
        steps=(KeyStep(key="pa", n=1),),
    ),
    HandleStep(signature="tso-ready", max_count=1, settle=0.0, steps=(CLEAR,)),
    HandleStep(
        signature="tso-cleared", max_count=1, settle=0.0,
        steps=(TypeStep(text="LOGOFF"), ENTER),
    ),
    _expect("tk5-logon"),
)

COMMAND_STEPS = {
    "tk5-time": (
        TypeStep(text="TIME"), ENTER, _expect("tso-ready", "tso-pause"),
        ExtractStep(output="TIME_TEXT"),
    ),
    "tk5-list-datasets": (
        TypeStep(text="LISTCAT"), ENTER, _expect("tso-ready", "tso-pause"),
        CollectStep(output="DATASETS", more="tso-pause", max_screens=5),
    ),
    "tk5-dataset-info": (
        TypeStep(text="LISTDS '"), TypeStep(input="dsname"), TypeStep(text="'"),
        ENTER, _expect("tso-ready", "tso-reenter"),
        ExtractStep(output="FOUND"), ExtractStep(output="DETAILS"),
    ),
    "tk5-library-members": (
        TypeStep(text="LISTDS '"), TypeStep(input="dsname"),
        TypeStep(text="' MEMBERS"), ENTER,
        _expect("tso-ready", "tso-pause", "tso-reenter"),
        CollectStep(output="MEMBERS", more="tso-pause", max_screens=10),
    ),
    "tk5-job-status": (
        TypeStep(text="STATUS"), ENTER, _expect("tso-ready", "tso-pause"),
        CollectStep(output="JOBS", more="tso-pause", max_screens=3),
    ),
}

PREFIX_LEN = 15


@pytest.fixture(scope="module")
def flows():
    return load_bundled_flows()


@pytest.fixture(scope="module")
def logon(flows):
    return flows["tk5-logon"]


@pytest.mark.parametrize("name", COMMAND_FLOWS)
def test_steps_are_prefix_exit_command_closing_tail(flows, logon, name):
    steps = flows[name].steps
    prefix = steps[:PREFIX_LEN]
    assert len(logon.steps) == PREFIX_LEN
    assert prefix == logon.steps[:PREFIX_LEN]

    command = COMMAND_STEPS[name]
    expected_tail = EXIT_FRAGMENT + command + CLOSING_TAIL
    assert steps[PREFIX_LEN:] == expected_tail
    assert len(steps) == PREFIX_LEN + 5 + len(command) + 5


@pytest.mark.parametrize("name", COMMAND_FLOWS)
def test_inputs_begin_with_the_two_logon_inputs(flows, logon, name):
    inputs = flows[name].inputs
    assert len(logon.inputs) == 2
    assert inputs[:2] == logon.inputs
    own = ["dsname"] if name in ("tk5-dataset-info", "tk5-library-members") else []
    assert [i.name for i in inputs[2:]] == own


@pytest.mark.parametrize("name", COMMAND_FLOWS)
def test_finally_equals_the_finally_block(flows, name):
    assert flows[name].finally_steps == FINALLY_BLOCK


def test_finally_is_equal_in_all_five(flows):
    blocks = {flows[n].finally_steps for n in COMMAND_FLOWS}
    assert len(blocks) == 1


@pytest.mark.parametrize("name", COMMAND_FLOWS)
def test_plan_indices(flows, name):
    last_main, first_fin, last_fin = PLAN_INDICES[name]
    main, fin = plan(flows[name])
    assert main[-1].index == last_main
    assert fin[0].index == first_fin
    assert fin[-1].index == last_fin
    assert last_fin - first_fin + 1 == 13
    assert first_fin == last_main + 1


@pytest.mark.parametrize("name", COMMAND_FLOWS)
def test_timeouts(flows, name):
    t = flows[name].timeouts
    assert (t.step, t.run, t.finally_) == (10.0, 20.0, 6.0)
