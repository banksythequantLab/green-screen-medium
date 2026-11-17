"""Unit tests for the YAML loader (flow-runtime Requirement 6)."""

from __future__ import annotations

import os

import pytest
import yaml

from greenscreen.flow import yamlio
from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import ExpectStep, Flow
from greenscreen.flow.yamlio import from_yaml, load_flow, to_yaml
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher

SIGS = [ScreenSignature("a", (TextAtMatcher(0, 0, "x"),))]

GOOD = "version: 1\nname: demo\nsteps:\n  - kind: expect\n    signatures: [a]\n"


def load_text(text: str) -> Flow:
    return from_yaml(text, SIGS)


def fail(text: str) -> FlowDefinitionError:
    with pytest.raises(FlowDefinitionError) as info:
        load_text(text)
    return info.value


def assert_no_chain(exc: BaseException) -> None:
    assert exc.__cause__ is None
    assert exc.__context__ is None


def test_good_document_loads():
    flow = load_text(GOOD)
    assert flow.name == "demo"
    assert flow.steps == (ExpectStep(signatures=("a",)),)


def test_malformed_yaml_reports_line_and_column():
    exc = fail("version: 1\nname: [unclosed\n")
    assert "malformed YAML at line" in str(exc)
    assert "column" in str(exc)
    assert_no_chain(exc)


@pytest.mark.parametrize("text", ["", "   \n  \n", "\n", "- a\n- b\n", "just text\n"])
def test_not_a_mapping(text):
    exc = fail(text)
    assert "not a mapping" in str(exc)
    assert_no_chain(exc)


def test_whitespace_only_with_tab_is_not_a_mapping():
    # Task 5.1: empty or whitespace-only text says the document is not a mapping.
    # Currently FAILS: a tab makes yaml.safe_load raise, so the loader reports
    # "malformed YAML at line 1, column 1" instead. Production defect in yamlio.
    exc = fail("\t\n")
    assert "not a mapping" in str(exc)
    assert_no_chain(exc)


@pytest.mark.parametrize("text", ["\t", "\t\n", "  \t\n", "\n\t  \n"])
def test_tab_whitespace_only_is_not_a_mapping(text):
    exc = fail(text)
    assert str(exc) == "document is not a mapping"
    assert_no_chain(exc)


def test_tab_containing_malformed_document_still_reports_position():
    exc = fail("version: 1\n\tname: demo\n")
    assert "malformed YAML at line 2, column 1" in str(exc)
    assert_no_chain(exc)


def test_unknown_top_level_key_names_key():
    exc = fail(GOOD + "bogus: 1\n")
    assert "unknown key 'bogus'" in str(exc)
    assert_no_chain(exc)


def test_unknown_step_key_names_index_and_key():
    steps = "".join("  - kind: expect\n    signatures: [a]\n" for _ in range(3))
    steps += "  - kind: expect\n    signatures: [a]\n    foo: 1\n"
    exc = fail("version: 1\nname: demo\nsteps:\n" + steps)
    assert "steps[3]" in str(exc)
    assert "unknown key 'foo'" in str(exc)
    assert_no_chain(exc)


def test_unsupported_step_kind_names_index():
    exc = fail("version: 1\nname: demo\nsteps:\n  - kind: dance\n")
    assert "steps[0]" in str(exc)
    assert "dance" in str(exc)
    assert_no_chain(exc)


@pytest.mark.parametrize("missing", ["name", "steps"])
def test_missing_required_key(missing):
    doc = yaml.safe_load(GOOD)
    del doc[missing]
    exc = fail(yaml.safe_dump(doc))
    assert f"missing key '{missing}'" in str(exc)
    assert_no_chain(exc)


def test_missing_required_key_in_list_item_names_index():
    text = GOOD + "outputs:\n  - name: o\n"
    exc = fail(text)
    assert "outputs[0]" in str(exc)
    assert "missing key" in str(exc)
    assert_no_chain(exc)


def test_wrong_value_type_names_key():
    exc = fail("version: 1\nname: 5\nsteps: []\n")
    assert "key 'name'" in str(exc)
    assert "string" in str(exc)
    assert_no_chain(exc)


def test_wrong_value_type_in_list_item_names_index_and_key():
    text = GOOD + (
        "inputs:\n"
        "  - {name: u, type: str, required: true, max_length: 5}\n"
        "  - {name: v, type: str, required: true, max_length: '5'}\n"
    )
    exc = fail(text)
    assert "inputs[1]" in str(exc)
    assert "key 'max_length'" in str(exc)
    assert_no_chain(exc)


def test_list_item_not_a_mapping_names_index():
    exc = fail("version: 1\nname: demo\nsteps:\n  - 5\n")
    assert "steps[0]" in str(exc)
    assert_no_chain(exc)


@pytest.mark.parametrize("literal", ["true", '"1"', "1.0", "2"])
def test_bad_version_values(literal):
    exc = fail(GOOD.replace("version: 1", f"version: {literal}", 1))
    assert "'version'" in str(exc)
    assert_no_chain(exc)


def test_missing_version():
    exc = fail(GOOD.replace("version: 1\n", "", 1))
    assert "missing key 'version'" in str(exc)
    assert_no_chain(exc)


def test_version_is_first_emitted_key_and_integer_one():
    flow = load_text(GOOD)
    text = to_yaml(flow)
    assert text.startswith("version: 1\n")
    doc = yaml.safe_load(text)
    assert next(iter(doc)) == "version"
    assert type(doc["version"]) is int and doc["version"] == 1


def test_missing_file_names_path(tmp_path):
    path = tmp_path / "nope.yaml"
    with pytest.raises(FlowDefinitionError) as info:
        load_flow(path, SIGS)
    assert str(path) in str(info.value)
    assert_no_chain(info.value)


def test_directory_names_path(tmp_path):
    with pytest.raises(FlowDefinitionError) as info:
        load_flow(tmp_path, SIGS)
    assert str(tmp_path) in str(info.value)
    assert_no_chain(info.value)


def test_permission_error_names_path(tmp_path, monkeypatch):
    path = tmp_path / "locked.yaml"
    path.write_text(GOOD, encoding="utf-8")

    def deny(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(yamlio, "open", deny, raising=False)
    with pytest.raises(FlowDefinitionError) as info:
        load_flow(path, SIGS)
    assert str(path) in str(info.value)
    assert_no_chain(info.value)


def test_invalid_utf8_names_path(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_bytes(GOOD.encode("utf-8") + b"\xff\xfe\x80\n")
    with pytest.raises(FlowDefinitionError) as info:
        load_flow(path, SIGS)
    assert str(path) in str(info.value)
    assert_no_chain(info.value)


def test_load_flow_reads_valid_file(tmp_path):
    path = tmp_path / "ok.yaml"
    path.write_text(GOOD, encoding="utf-8")
    assert load_flow(path, SIGS).name == "demo"


class _EnvSpy(dict):
    def __init__(self):
        super().__init__()
        self.touched = []

    def __getitem__(self, key):
        self.touched.append(key)
        return super().__getitem__(key)

    def get(self, key, default=None):
        self.touched.append(key)
        return super().get(key, default)

    def __contains__(self, key):
        self.touched.append(key)
        return super().__contains__(key)


def test_loader_reads_no_environment_variable(tmp_path, monkeypatch):
    path = tmp_path / "ok.yaml"
    path.write_text(GOOD, encoding="utf-8")
    spy = _EnvSpy()
    monkeypatch.setattr(os, "environ", spy)
    flow = load_flow(path, SIGS)
    with pytest.raises(FlowDefinitionError):
        load_text("")
    assert flow.name == "demo"
    assert spy.touched == []
