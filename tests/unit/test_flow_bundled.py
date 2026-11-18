"""Unit tests for load_bundled_flows (flow-runtime Requirement 17)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import greenscreen.flow.bundled as bundled_mod
from greenscreen.flow import FlowDefinitionError, load_bundled_flows
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    HandleStep,
    KeyStep,
    TypeStep,
)
from greenscreen.flow.validate import check_flow, reference_violations, structural_violations
from greenscreen.recognizer import load_bundled_signatures

NAMES = ("tk5-logon", "tk5-logoff", "tk5-system-info")
FLOWS_DIR = Path(bundled_mod.__file__).parent / "flows"


@pytest.fixture(scope="module")
def flows():
    return load_bundled_flows()


def _expect(*names):
    return ExpectStep(signatures=tuple(names))


# --- Requirement 17.1, 17.2 -------------------------------------------------


def test_exactly_three_entries_with_expected_keys(flows):
    assert set(flows) == set(NAMES)
    assert len(flows) == 3
    for name, flow in flows.items():
        assert flow.name == name


def test_exactly_three_yaml_files_shipped():
    assert sorted(p.name for p in FLOWS_DIR.glob("*.yaml")) == sorted(
        f"{n}.yaml" for n in NAMES
    )


def test_loads_from_another_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert set(load_bundled_flows()) == set(NAMES)


# --- Requirement 17.18 ------------------------------------------------------


def test_every_bundled_flow_passes_validator(flows):
    sigs = load_bundled_signatures()
    names = frozenset(s.name for s in sigs)
    for flow in flows.values():
        assert structural_violations(flow) == []
        assert reference_violations(flow, names) == []
        check_flow(flow, sigs)


# --- Requirement 17.4 to 17.8 (tk5-logon) -----------------------------------


def test_logon_inputs_and_no_outputs(flows):
    flow = flows["tk5-logon"]
    assert flow.outputs == ()
    userid, password = flow.inputs
    assert (userid.name, userid.type, userid.required, userid.max_length) == (
        "userid",
        "str",
        True,
        8,
    )
    assert userid.regex == "[A-Za-z0-9@#$]{1,8}"
    assert userid.secret is False
    assert (password.name, password.type, password.required, password.max_length) == (
        "password",
        "str",
        True,
        8,
    )
    assert password.secret is True


def test_logon_ends_on_ispf_primary_menu(flows):
    assert flows["tk5-logon"].steps[-1] == _expect("ispf-primary-menu")


def test_logon_logo_handle_step(flows):
    handles = [
        s
        for s in flows["tk5-logon"].steps
        if isinstance(s, HandleStep) and s.signature == "tk5-logo"
    ]
    assert len(handles) == 1
    assert handles[0].settle >= 3
    assert handles[0].steps == (KeyStep(key="enter"),)


def test_logon_input_not_recognized_handle_step(flows):
    handles = [
        s
        for s in flows["tk5-logon"].steps
        if isinstance(s, HandleStep) and s.signature == "tso-input-not-recognized"
    ]
    assert len(handles) == 1
    assert handles[0].steps == (KeyStep(key="clear"),)


def test_logon_pause_handle_step(flows):
    handles = [
        s
        for s in flows["tk5-logon"].steps
        if isinstance(s, HandleStep) and s.signature == "tso-pause"
    ]
    assert len(handles) == 1
    assert handles[0].max_count == 5
    assert handles[0].steps == (KeyStep(key="enter"),)


def test_logon_typing_sequence(flows):
    steps = flows["tk5-logon"].steps
    top = [s for s in steps if not isinstance(s, HandleStep)]
    assert top == [
        _expect("tk5-logon"),
        TypeStep(input="userid"),
        KeyStep(key="enter"),
        _expect("tso-password-prompt", "tso-reconnect-password-prompt"),
        TypeStep(input="password"),
        KeyStep(key="enter"),
        _expect("ispf-primary-menu"),
    ]
    typed = []

    def walk(items):
        for s in items:
            if isinstance(s, TypeStep) and s.input is not None:
                typed.append(s.input)
            elif isinstance(s, HandleStep):
                walk(s.steps)

    walk(steps)
    assert typed == ["userid", "userid", "password"]


# --- Requirement 17.9, 17.10 (tk5-logoff) -----------------------------------


def test_logoff_has_exact_seven_steps(flows):
    flow = flows["tk5-logoff"]
    assert flow.inputs == ()
    assert flow.outputs == ()
    assert flow.steps == (
        _expect("ispf-primary-menu"),
        TypeStep(text="X"),
        KeyStep(key="enter"),
        _expect("tso-ready"),
        TypeStep(text="LOGOFF"),
        KeyStep(key="enter"),
        _expect("tk5-logon"),
    )


# --- Requirement 17.11 to 17.13, 17.15 (tk5-system-info) --------------------


def test_system_info_inputs_match_logon(flows):
    assert flows["tk5-system-info"].inputs == flows["tk5-logon"].inputs


def test_system_info_outputs_and_regions(flows):
    outs = flows["tk5-system-info"].outputs
    assert [o.name for o in outs] == ["USERID", "SYSTEMID", "RELEASE", "TERMINAL"]
    regions = {o.name: (o.row, o.col, o.length) for o in outs}
    assert regions == {
        "USERID": (2, 71, 8),
        "TERMINAL": (4, 71, 8),
        "RELEASE": (10, 71, 8),
        "SYSTEMID": (12, 71, 8),
    }
    for o in outs:
        assert o.type == "str"
        assert o.signature == "ispf-primary-menu"


def test_system_info_steps_compose_logon_extracts_logoff(flows):
    logon = flows["tk5-logon"].steps
    logoff = flows["tk5-logoff"].steps
    steps = flows["tk5-system-info"].steps
    extracts = [i for i, s in enumerate(steps) if isinstance(s, ExtractStep)]
    assert len(extracts) == 4
    assert extracts == list(range(extracts[0], extracts[0] + 4))
    assert steps[: extracts[0]] == logon
    assert steps[extracts[-1] + 1 :] == logoff


def test_system_info_finally_steps(flows):
    assert flows["tk5-system-info"].finally_steps == (
        HandleStep(
            signature="ispf-primary-menu",
            max_count=1,
            steps=(TypeStep(text="X"), KeyStep(key="enter")),
        ),
        HandleStep(
            signature="tso-ready",
            max_count=1,
            steps=(TypeStep(text="LOGOFF"), KeyStep(key="enter")),
        ),
        _expect("tk5-logon"),
    )


# --- shipped text equals to_yaml() -----------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_shipped_yaml_equals_to_yaml(flows, name):
    shipped = (FLOWS_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    assert flows[name].to_yaml() == shipped


# --- failures ---------------------------------------------------------------


class _Node:
    def __init__(self, files):
        self._files = files

    def joinpath(self, name):
        return _File(name, self._files[name.removesuffix(".yaml")])


class _File:
    def __init__(self, name, content):
        self.name = name
        self._content = content

    def read_text(self, encoding=None):
        if isinstance(self._content, BaseException):
            raise self._content
        return self._content


def _patched(monkeypatch, overrides):
    real = {n: (FLOWS_DIR / f"{n}.yaml").read_text(encoding="utf-8") for n in NAMES}
    real.update(overrides)
    real_files = bundled_mod.resources.files

    def fake_files(package):
        if package == "greenscreen.flow.flows":
            return _Node(real)
        return real_files(package)

    monkeypatch.setattr(bundled_mod.resources, "files", fake_files)


@pytest.mark.parametrize("name", NAMES)
def test_missing_file_raises_naming_file(monkeypatch, name):
    _patched(monkeypatch, {name: FileNotFoundError("gone")})
    with pytest.raises(FlowDefinitionError) as info:
        load_bundled_flows()
    assert f"{name}.yaml" in str(info.value)


@pytest.mark.parametrize("name", NAMES)
def test_broken_yaml_raises_naming_file(monkeypatch, name):
    _patched(monkeypatch, {name: "version: 1\nname: [unclosed\n"})
    with pytest.raises(FlowDefinitionError) as info:
        load_bundled_flows()
    assert f"{name}.yaml" in str(info.value)


def test_invalid_flow_raises_naming_file(monkeypatch):
    text = (FLOWS_DIR / "tk5-logoff.yaml").read_text(encoding="utf-8")
    text = text.replace("name: tk5-logoff", "name: tk5-logoff\nbogus_key: 1", 1)
    _patched(monkeypatch, {"tk5-logoff": text})
    with pytest.raises(FlowDefinitionError) as info:
        load_bundled_flows()
    assert "tk5-logoff.yaml" in str(info.value)


def test_unknown_signature_raises_naming_file(monkeypatch):
    text = (FLOWS_DIR / "tk5-logoff.yaml").read_text(encoding="utf-8")
    text = text.replace("tso-ready", "no-such-screen")
    _patched(monkeypatch, {"tk5-logoff": text})
    with pytest.raises(FlowDefinitionError) as info:
        load_bundled_flows()
    assert "tk5-logoff.yaml" in str(info.value)


def test_failure_returns_no_dict(monkeypatch):
    _patched(monkeypatch, {"tk5-system-info": FileNotFoundError("gone")})
    result = None
    with pytest.raises(FlowDefinitionError):
        result = load_bundled_flows()
    assert result is None


# --- no cache ---------------------------------------------------------------


def test_two_calls_return_distinct_dicts():
    a = load_bundled_flows()
    b = load_bundled_flows()
    assert a is not b
    assert a == b


# --- Requirement 17.19 ------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_no_literal_credentials_or_placeholders(name):
    text = (FLOWS_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    assert "${" not in text
    for line in text.splitlines():
        m = re.match(r"\s*(?:- )?(?:text|default|value|userid|password)\s*:\s*(.+)", line)
        if m:
            value = m.group(1).strip().strip("'\"")
            assert value in {"X", "LOGOFF", "LOGON ", " RECONNECT"}, (
                f"unexpected literal in {name}.yaml"
            )
