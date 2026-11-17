"""The three bundled flows must not drift apart (Requirements 17.11, 17.12, 17.17)."""

from __future__ import annotations

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.flow.model import ExtractStep


@pytest.fixture(scope="module")
def flows():
    return load_bundled_flows()


def _split(flows):
    logon = flows["tk5-logon"].steps
    logoff = flows["tk5-logoff"].steps
    info = flows["tk5-system-info"].steps
    return logon, logoff, info


def test_system_info_starts_with_logon_steps(flows):
    logon, _, info = _split(flows)
    assert info[: len(logon)] == logon


def test_system_info_ends_with_logoff_steps(flows):
    _, logoff, info = _split(flows)
    assert info[len(info) - len(logoff) :] == logoff


def test_system_info_inputs_equal_logon_inputs(flows):
    assert flows["tk5-system-info"].inputs == flows["tk5-logon"].inputs


def test_steps_between_are_exactly_the_four_extract_steps(flows):
    logon, logoff, info = _split(flows)
    middle = info[len(logon) : len(info) - len(logoff)]
    assert len(middle) == 4
    assert all(isinstance(step, ExtractStep) for step in middle)
    assert len(info) == len(logon) + 4 + len(logoff)
