"""Unit tests for the Flow ``example`` member (spec ``polish``, task 3.2).

Covers Requirements 7.1, 7.2, 7.3, 7.4 and 7.7: the default, the YAML key and
its order, the three validator rules with boundary strings, messages that never
hold the rejected text, ``check_flow``, and a Runner that ignores the member.
"""
from __future__ import annotations

import pytest
import yaml

from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import ExpectStep, Flow
from greenscreen.flow.runner import run_flow
from greenscreen.flow.validate import check_flow
from greenscreen.flow.yamlio import from_yaml, to_yaml
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import FakeClock, ScriptedSession, capture

SIGS = load_bundled_signatures()
STEPS = (ExpectStep(signatures=("tk5-logon",)),)
GOOD = "version: 1\nname: demo\nsteps:\n  - kind: expect\n    signatures: [tk5-logon]\n"


def _yaml(example_line: str) -> str:
    return GOOD.replace("name: demo\n", "name: demo\n" + example_line + "\n")


# --- default and positional construction (7.1) ---------------------------

def test_default_is_empty_and_positional_construction_works():
    flow = Flow("n", STEPS)
    assert flow.example == ""
    assert Flow("n", STEPS, "desc").example == ""


def test_example_is_the_last_member():
    import dataclasses

    assert [f.name for f in dataclasses.fields(Flow)][-1] == "example"


# --- YAML (7.2) ------------------------------------------------------------

def test_key_order_description_then_example():
    text = to_yaml(Flow("n", STEPS, description="d", example="How many?"))
    keys = list(yaml.safe_load(text))
    assert keys.index("example") == keys.index("description") + 1
    assert text.index("description:") < text.index("example:")


def test_empty_example_is_not_emitted():
    assert "example" not in yaml.safe_load(to_yaml(Flow("n", STEPS, description="d")))


def test_example_round_trips():
    flow = Flow("n", STEPS, description="d", example="What time is it?")
    assert from_yaml(to_yaml(flow), SIGS).example == "What time is it?"


def test_reading_empty_example_gives_empty_example():
    assert from_yaml(_yaml("example: ''"), SIGS).example == ""


def test_missing_example_gives_empty_example():
    assert from_yaml(GOOD, SIGS).example == ""


def test_wrong_type_names_the_key():
    with pytest.raises(FlowDefinitionError) as info:
        from_yaml(_yaml("example: 5"), SIGS)
    assert "example" in str(info.value)


# --- the three rules (7.3) -------------------------------------------------

@pytest.mark.parametrize("text", ["", "a", " ", "~", "x" * 200, "a $ {b} $"])
def test_accepted(text):
    assert Flow("n", STEPS, example=text).example == text


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("x" * 201, "too_long"),
        ("a\x1fb", "invalid_text"),
        ("a\x7fb", "invalid_text"),
        ("caf\u00e9", "invalid_text"),
        ("a\nb", "invalid_text"),
        ("show ${HOME}", "interpolation_marker"),
        ("${", "interpolation_marker"),
    ],
)
def test_rejected_with_rule_and_without_the_text(text, rule):
    with pytest.raises(FlowDefinitionError) as info:
        Flow("n", STEPS, example=text)
    msg = str(info.value)
    assert "example" in msg and rule in msg
    assert text not in msg


def test_non_string_is_invalid_text():
    with pytest.raises(FlowDefinitionError) as info:
        Flow("n", STEPS, example=5)  # type: ignore[arg-type]
    assert "invalid_text" in str(info.value)


def test_rule_order_invalid_text_before_too_long_before_marker():
    with pytest.raises(FlowDefinitionError, match="invalid_text"):
        Flow("n", STEPS, example="${" + "x" * 300 + "\x1f")
    with pytest.raises(FlowDefinitionError, match="too_long"):
        Flow("n", STEPS, example="${" + "x" * 300)


def test_yaml_value_is_rejected_without_echo():
    secret = "q" * 150 + "${" + "z" * 60
    with pytest.raises(FlowDefinitionError) as info:
        from_yaml(_yaml(f"example: '{secret}'"), SIGS)
    assert "too_long" in str(info.value)
    assert secret not in str(info.value)
    assert "qqqq" not in str(info.value)


# --- check_flow (7.4) ------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "rule"),
    [("x" * 201, "too_long"), ("a\x1f", "invalid_text"), ("${x", "interpolation_marker")],
)
def test_check_flow_names_field_and_rule(text, rule):
    flow = Flow("n", STEPS)
    object.__setattr__(flow, "example", text)  # bypass construction-time checks
    with pytest.raises(FlowDefinitionError) as info:
        check_flow(flow, SIGS)
    msg = str(info.value)
    assert "'example'" in msg and f"'{rule}'" in msg
    assert text not in msg


def test_check_flow_accepts_a_good_example():
    check_flow(Flow("n", STEPS, example="Is it up?"), SIGS)


# --- the Runner ignores the member (7.7) ----------------------------------

def _run(example: str):
    flow = Flow("n", STEPS, example=example)
    session = ScriptedSession([capture("tk5-logon")])
    result = run_flow(flow, session, {}, signatures=SIGS, clock=FakeClock())
    return result, session.calls


def test_runner_ignores_example():
    marker = "Zebra question text"
    with_ex, calls_with = _run(marker)
    without, calls_without = _run("")
    assert with_ex.flow == without.flow
    assert dict(with_ex.outputs) == dict(without.outputs)
    assert with_ex.audit == without.audit
    assert calls_with == calls_without
    assert marker not in repr(with_ex)
    assert marker not in repr(with_ex.audit)


# --- the bundled Flows (spec polish, task 5.2; Requirements 8.1, 8.2, 8.3) --

import re  # noqa: E402

from greenscreen.flow.inputs import prepare_inputs  # noqa: E402
from tests.command_flow_support import flow_path, load_shipped_flow  # noqa: E402

WITH_EXAMPLE = {
    "tk5-system-info": "What system and release is the mainframe running?",
    "tk5-time": "What time is it on the mainframe?",
    "tk5-list-datasets": "Which data sets does this account have?",
    "tk5-dataset-info": "What are the record format and volume of SYS2.JCLLIB?",
    "tk5-job-status": "Which jobs are running for this account?",
    "tk5-library-members": "Which members does SYS2.JCLLIB have?",
}
WITHOUT_EXAMPLE = ("tk5-logon", "tk5-logoff")


@pytest.mark.parametrize("name", sorted(WITH_EXAMPLE))
def test_bundled_example_shape(name):
    text = load_shipped_flow(name).example
    assert text.endswith("?")
    assert 10 <= len(text) <= 120
    assert all(0x20 <= ord(c) <= 0x7E for c in text)
    assert not any(c in text[:-1] for c in ";#@?")
    assert not any(c in text for c in ";#@")


@pytest.mark.parametrize("name", sorted(WITH_EXAMPLE))
def test_bundled_example_text(name):
    assert load_shipped_flow(name).example == WITH_EXAMPLE[name]


@pytest.mark.parametrize("name", WITHOUT_EXAMPLE)
def test_logon_and_logoff_have_no_example(name):
    flow = load_shipped_flow(name)
    assert flow.example == ""
    assert not re.search(r"^example:", flow_path(name).read_text(encoding="utf-8"), re.M)


@pytest.mark.parametrize("name", ["tk5-dataset-info", "tk5-library-members"])
def test_name_flow_example_holds_an_accepted_dsname(name):
    flow = load_shipped_flow(name)
    (token,) = re.findall(r"\b[A-Z0-9$#@]+(?:\.[A-Z0-9$#@]+)+\b", flow.example)
    prepared = prepare_inputs(
        flow, {"userid": "FAKEUSR", "password": "SNTNL-01", "dsname": token}
    )
    assert prepared.values["dsname"] == token


@pytest.mark.parametrize("name", sorted(WITH_EXAMPLE))
def test_shipped_yaml_equals_to_yaml(name):
    flow = load_shipped_flow(name)
    raw = flow_path(name).read_bytes().decode("utf-8")
    assert raw.replace("\r\n", "\n") == flow.to_yaml().replace("\r\n", "\n")
