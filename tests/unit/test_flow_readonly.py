"""The bundled Flows can only read (spec more-flows, task 8.8, Requirement 9).

Runs the five Command_Flows against scripted real captures; no host is used.
The literal sets of the five new Flows live here. The three older Flows keep
their own literal test, ``test_flow_bundled.py::test_no_literal_credentials_or_
placeholders``, over ``NAMES[:3]``. ``test_every_bundled_flow_is_covered_by_
exactly_one_literal_test`` ties the two together (condition X8).
"""
from __future__ import annotations

import re

import pytest
import yaml

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.model import HandleStep, KeyStep, TypeStep
from greenscreen.flow.runner import run_flow

from tests.command_flow_support import (
    FLOWS_DIR,
    INPUTS,
    POLL,
    SENTINEL,
    USERID,
    command_session,
    keys,
    logon_keys,
    typed_after_menu,
)
from tests.flow_support import FakeClock, capture
from tests.unit.test_flow_bundled import NAMES as ALL_NAMES

READ_ONLY_SET = frozenset(
    {"X", "LOGOFF", "LOGON ", " RECONNECT", "TIME", "LISTCAT", "STATUS",
     "LISTDS '", "'", "' MEMBERS"}
)
LOGON_LITERALS = frozenset({"X", "LOGOFF", "LOGON ", " RECONNECT"})

# The literal sets of the five Command_Flows: only the command literals.
COMMAND_LITERALS = {
    "tk5-time": frozenset({"TIME"}),
    "tk5-list-datasets": frozenset({"LISTCAT"}),
    "tk5-dataset-info": frozenset({"LISTDS '", "'"}),
    "tk5-library-members": frozenset({"LISTDS '", "' MEMBERS"}),
    "tk5-job-status": frozenset({"STATUS"}),
}

# A: bundled names; B: names covered by test_flow_bundled; C: names covered here.
SET_B = frozenset(ALL_NAMES[:3])
SET_C = frozenset(COMMAND_LITERALS)

FIXED_LITERAL_FLOWS = ("tk5-time", "tk5-list-datasets", "tk5-job-status")
NAME_FLOWS = ("tk5-dataset-info", "tk5-library-members")


@pytest.fixture(scope="module")
def flows():
    return load_bundled_flows()


# ------------------------------------------------------------ walking a Flow

def _walk(flow):
    """Yield (step, handle_signature or None) for steps, finally and Handle bodies."""
    for step in (*flow.steps, *flow.finally_steps):
        yield step, None
        if isinstance(step, HandleStep):
            for inner in step.steps:
                yield inner, step.signature


def _literals(flow) -> set[str]:
    return {
        s.text for s, _ in _walk(flow) if isinstance(s, TypeStep) and s.text is not None
    }


# ------------------------------------------------------ the literals (9.1, 9.5)

def test_every_bundled_flow_types_only_read_only_literals(flows):
    for name, flow in flows.items():
        assert _literals(flow) <= READ_ONLY_SET, name


@pytest.mark.parametrize("name", sorted(COMMAND_LITERALS))
def test_command_flow_contains_exactly_its_own_command_literals(flows, name):
    literals = _literals(flows[name])
    assert literals == LOGON_LITERALS | COMMAND_LITERALS[name]
    assert literals - LOGON_LITERALS == COMMAND_LITERALS[name]


@pytest.mark.parametrize("name", sorted(COMMAND_LITERALS))
def test_yaml_text_values_are_in_the_read_only_set(name):
    text = (FLOWS_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    assert "${" not in text
    found = []
    for line in text.splitlines():
        m = re.match(r"\s*(?:- )?(?:text|default|value|userid|password)\s*:\s*(.+)", line)
        if m:
            found.append(yaml.safe_load(m.group(1)))
    assert found
    for value in found:
        assert value in READ_ONLY_SET, f"unexpected literal in {name}.yaml"
    assert set(found) == LOGON_LITERALS | COMMAND_LITERALS[name]


# ------------------------------------------------------ inputs and keys (9.2)

@pytest.mark.parametrize("name", sorted(COMMAND_LITERALS))
def test_typed_inputs_are_userid_password_or_dsname(flows, name):
    for step, _ in _walk(flows[name]):
        if isinstance(step, TypeStep) and step.input is not None:
            assert step.input in ("userid", "password", "dsname")
            assert step.text is None


def test_no_pf_key_and_pa_only_n1_in_a_reenter_handle(flows):
    for name, flow in flows.items():
        for step, handle in _walk(flow):
            if not isinstance(step, KeyStep):
                continue
            assert step.key != "pf", name
            if step.key == "pa":
                assert handle == "tso-reenter", name
                assert step.n == 1, name


@pytest.mark.parametrize("name", sorted(COMMAND_LITERALS))
def test_command_flow_has_pa1_in_logon_cleanup_and_finally(flows, name):
    flow = flows[name]
    for steps in (flow.steps, flow.finally_steps):
        pa = [
            s for s in steps
            if isinstance(s, HandleStep) and s.signature == "tso-reenter"
        ]
        assert len(pa) == 1
        assert pa[0].steps == (KeyStep(key="pa", n=1),)


@pytest.mark.parametrize("name", FIXED_LITERAL_FLOWS)
def test_fixed_literal_flows_do_not_expect_reenter(flows, name):
    for step in (*flows[name].steps, *flows[name].finally_steps):
        sigs = getattr(step, "signatures", ())
        assert "tso-reenter" not in sigs


@pytest.mark.parametrize("name", NAME_FLOWS)
def test_name_flows_do_expect_reenter_after_the_command(flows, name):
    assert any(
        "tso-reenter" in getattr(s, "signatures", ()) for s in flows[name].steps
    )


# ------------------------------------------- Session calls and echo (9.4, 9.6)

MEMBER_PAGES = ["tso-listds-members"] + [
    f"tso-listds-members-page{i}" for i in range(2, 8)
]
MEMBERS_NAME = "SYS2.JCLLIB"

# name -> (screens, paging Enters, typed command strings before the name logic)
SCRIPTS = {
    "tk5-time": (["tso-time-output"], 0),
    "tk5-list-datasets": (["tso-listcat-output"], 0),
    "tk5-dataset-info": (["tso-listds-output"], 0),
    "tk5-library-members": (MEMBER_PAGES, 6),
    "tk5-job-status": (["tso-status-output"], 0),
}


def _row0(screen) -> str:
    return "".join(
        chr(c) if isinstance(c, int) and c else " " for c in screen.cell_grid[0]
    ).rstrip()


def _dsname_from_echo(echo: str, head: str, tail: str) -> str:
    assert echo.startswith(head) and echo.endswith(tail)
    return echo[len(head): len(echo) - len(tail)]


def _inputs_and_command(name):
    """Inputs for the run and the typed command strings, as the Flow must type them."""
    screens, _ = SCRIPTS[name]
    echo = _row0(capture(screens[0]))
    if name == "tk5-dataset-info":
        dsn = _dsname_from_echo(echo, "LISTDS '", "'")
        return {**INPUTS, "dsname": dsn}, ["LISTDS '", dsn, "'"]
    if name == "tk5-library-members":
        dsn = _dsname_from_echo(echo, "LISTDS '", "' MEMBERS")
        return {**INPUTS, "dsname": dsn}, ["LISTDS '", dsn, "' MEMBERS"]
    return dict(INPUTS), [{"tk5-time": "TIME", "tk5-list-datasets": "LISTCAT",
                           "tk5-job-status": "STATUS"}[name]]


def _run_script(flows, name):
    inputs, command = _inputs_and_command(name)
    screens, _ = SCRIPTS[name]
    session = command_session(screens)
    run_flow(flows[name], session, inputs, clock=FakeClock(), poll_interval=POLL)
    return session, inputs, command


@pytest.mark.parametrize("name", sorted(COMMAND_LITERALS))
def test_session_call_sequence_is_logon_exit_command_paging_closing(flows, name):
    session, inputs, command = _run_script(flows, name)
    paging = SCRIPTS[name][1]
    expected = [
        *logon_keys(),
        ("string", "X"), ("enter",), ("clear",),
        *[("string", t) for t in command], ("enter",),
        *[("enter",)] * paging,
        ("clear",), ("string", "LOGOFF"), ("enter",),
    ]
    assert keys(session) == expected
    assert typed_after_menu(session) == ["X", *command, "LOGOFF"]


@pytest.mark.parametrize("name", sorted(COMMAND_LITERALS))
def test_command_typed_in_order_reproduces_the_echo_row_of_the_capture(flows, name):
    session, inputs, command = _run_script(flows, name)
    typed = typed_after_menu(session)
    assert typed[0] == "X" and typed[-1] == "LOGOFF"
    screens, _ = SCRIPTS[name]
    assert "".join(typed[1:-1]) == _row0(capture(screens[0]))
    if name in NAME_FLOWS:
        assert inputs["dsname"] in typed
        assert inputs["dsname"].strip()


def test_the_members_capture_echoes_the_library_name():
    assert _inputs_and_command("tk5-library-members")[0]["dsname"] == MEMBERS_NAME


@pytest.mark.parametrize("name", sorted(COMMAND_LITERALS))
def test_secrets_are_typed_once_and_only_in_the_logon(flows, name):
    session, _, _ = _run_script(flows, name)
    strings = [c[1] for c in keys(session) if c[0] == "string"]
    assert strings.count(SENTINEL) == 1
    assert strings.index(SENTINEL) == 1
    assert USERID in strings[:1]


# ------------------------------------------------ coverage (condition X8)

def coverage_problems(a, b, c) -> list[str]:
    """Why the sets ``a`` (bundled), ``b`` (older literal test) and ``c`` (this file) do not fit."""
    problems = []
    both = sorted(set(b) & set(c))
    if both:
        problems.append(f"covered by both literal tests: {both}")
    neither = sorted(set(a) - set(b) - set(c))
    if neither:
        problems.append(f"covered by no literal test: {neither}")
    extra = sorted((set(b) | set(c)) - set(a))
    if extra:
        problems.append(f"covered but not bundled: {extra}")
    return problems


def test_every_bundled_flow_is_covered_by_exactly_one_literal_test():
    a = set(load_bundled_flows())
    assert SET_B.isdisjoint(SET_C)
    assert a == SET_B | SET_C
    assert coverage_problems(a, SET_B, SET_C) == []


def test_coverage_check_fails_for_a_ninth_name_in_neither_set():
    a = set(load_bundled_flows()) | {"tk5-ninth"}
    problems = coverage_problems(a, SET_B, SET_C)
    assert problems and "tk5-ninth" in problems[0]


def test_coverage_check_fails_for_a_ninth_name_in_both_sets():
    a = set(load_bundled_flows()) | {"tk5-ninth"}
    problems = coverage_problems(a, SET_B | {"tk5-ninth"}, SET_C | {"tk5-ninth"})
    assert problems and "tk5-ninth" in problems[0]
