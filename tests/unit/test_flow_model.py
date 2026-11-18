"""Unit tests for the Flow data model (flow-runtime Requirement 1)."""

from __future__ import annotations

import dataclasses
import tomllib
from pathlib import Path

import pytest

from greenscreen.connector.exceptions import ConnectorError
from greenscreen.flow import Flow, FlowDefinitionError, FlowError, FlowInputError
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    HandleStep,
    InputSpec,
    KeyStep,
    OutputSpec,
    TypeStep,
)
from greenscreen.recognizer.errors import RecognizerError

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

# The lists present when task 10.1 started.
EXPECTED_DEPENDENCIES = ["pyyaml>=6.0.3"]
EXPECTED_OPTIONAL = {
    "publish": ["mcp>=2.3,<3", "fastapi>=0.163,<1"],
    "dev": [
        "greenscreen-connector[publish]",
        "hypothesis>=6.170.15",
        "pytest>=8.0",
        "pyyaml>=6.0.3",
        "setuptools>=70.1",
    ],
}


def _pairs(n: int) -> list:
    """2*n Steps: an Expect_Step arming each Key_Step."""
    out: list = []
    for _ in range(n):
        out += [ExpectStep(signatures=("a",)), KeyStep(key="enter")]
    return out


def _inp(i: int) -> InputSpec:
    return InputSpec(name=f"in{i}", type="str", required=False, max_length=5)


def _out(i: int) -> OutputSpec:
    return OutputSpec(
        name=f"out{i}", type="str", signature="a", row=0, col=0, length=1
    )


def _flow(**kw) -> Flow:
    kw.setdefault("name", "demo")
    kw.setdefault("steps", _pairs(1))
    return Flow(**kw)


# ---- immutability -------------------------------------------------------


def test_assign_to_every_field_raises_and_keeps_value():
    flow = _flow(description="d", inputs=[_inp(0)])
    for field in dataclasses.fields(flow):
        before = getattr(flow, field.name)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(flow, field.name, "changed")
        assert getattr(flow, field.name) == before


def test_delete_every_field_raises_and_keeps_value():
    flow = _flow(description="d")
    for field in dataclasses.fields(flow):
        before = getattr(flow, field.name)
        with pytest.raises(dataclasses.FrozenInstanceError):
            delattr(flow, field.name)
        assert getattr(flow, field.name) == before


def test_lists_become_tuples():
    flow = _flow(inputs=[_inp(0)], outputs=[], finally_steps=[])
    assert isinstance(flow.steps, tuple)
    assert isinstance(flow.inputs, tuple)
    assert flow.finally_steps == ()


# ---- bounds of Requirement 1 -------------------------------------------


def test_description_500_ok_501_rejected():
    assert _flow(description="x" * 500).description == "x" * 500
    with pytest.raises(FlowDefinitionError, match="description"):
        _flow(description="x" * 501)


def test_inputs_20_ok_21_rejected():
    assert len(_flow(inputs=[_inp(i) for i in range(20)]).inputs) == 20
    with pytest.raises(FlowDefinitionError, match="inputs"):
        _flow(inputs=[_inp(i) for i in range(21)])


def _with_outputs(n: int) -> Flow:
    steps = [ExpectStep(signatures=("a",))]
    steps += [ExtractStep(output=f"out{i}") for i in range(n)]
    return _flow(steps=steps, outputs=[_out(i) for i in range(n)])


def test_outputs_20_ok_21_rejected():
    assert len(_with_outputs(20).outputs) == 20
    with pytest.raises(FlowDefinitionError, match="outputs"):
        _with_outputs(21)


def test_steps_zero_rejected():
    with pytest.raises(FlowDefinitionError, match="steps"):
        Flow(name="demo", steps=[])


def test_steps_200_ok_201_rejected():
    assert len(_flow(steps=_pairs(100)).steps) == 200
    with pytest.raises(FlowDefinitionError, match="steps"):
        _flow(steps=_pairs(100) + [ExpectStep(signatures=("a",))])


def test_steps_count_includes_handle_bodies():
    body = [TypeStep(text="x")] * 200
    with pytest.raises(FlowDefinitionError, match="steps"):
        _flow(
            steps=[
                ExpectStep(signatures=("a",)),
                HandleStep(signature="a", max_count=1, steps=body[:50]),
            ]
            + _pairs(75)
            + [ExpectStep(signatures=("a",))]
        )


def test_finally_zero_and_50_ok_51_rejected():
    assert _flow(finally_steps=[]).finally_steps == ()
    assert len(_flow(finally_steps=_pairs(25)).finally_steps) == 50
    with pytest.raises(FlowDefinitionError, match="finally"):
        _flow(finally_steps=_pairs(25) + [ExpectStep(signatures=("a",))])


# ---- the five Step kinds ------------------------------------------------


def test_expect_step_kind():
    step = ExpectStep(signatures=["a"], tolerate=["b"], timeout=2)
    assert step.kind == "expect"
    assert step.signatures == ("a",) and step.tolerate == ("b",)
    assert step.timeout == 2.0 and isinstance(step.timeout, float)
    assert _flow(steps=[step]).steps == (step,)


def test_type_step_kind():
    step = TypeStep(text="hello")
    assert step.kind == "type"
    flow = _flow(steps=[ExpectStep(signatures=("a",)), step])
    assert flow.steps[1] is step


def test_key_step_kind():
    step = KeyStep(key="pf", n=3)
    assert step.kind == "key"
    flow = _flow(steps=[ExpectStep(signatures=("a",)), step])
    assert flow.steps[1] is step


def test_extract_step_kind():
    step = ExtractStep(output="out0")
    assert step.kind == "extract"
    flow = _flow(
        steps=[ExpectStep(signatures=("a",)), step], outputs=[_out(0)]
    )
    assert flow.steps[1] is step


def test_handle_step_kind():
    step = HandleStep(
        signature="a", max_count=2, steps=[TypeStep(text="x"), KeyStep(key="enter")],
        settle=1,
    )
    assert step.kind == "handle"
    assert isinstance(step.steps, tuple) and step.settle == 1.0
    assert isinstance(step.settle, float)
    flow = _flow(steps=[ExpectStep(signatures=("a",)), step])
    assert flow.steps[1] is step


def test_unsupported_kind_in_yaml_names_the_kind():
    text = (
        "version: 1\nname: demo\nsteps:\n"
        "  - kind: expect\n    signatures: [a]\n"
        "  - kind: frobnicate\n"
    )
    with pytest.raises(FlowDefinitionError, match="frobnicate"):
        Flow.from_yaml(text, signatures=[])


def _bogus(kind):
    class Bogus:
        pass

    b = Bogus()
    b.kind = kind
    return b


def test_unsupported_step_object_names_the_kind():
    with pytest.raises(FlowDefinitionError) as ei:
        _flow(steps=[_bogus("bogus")])
    assert str(ei.value) == "step 0: kind: unknown_kind 'bogus'"


def test_unsupported_kind_at_32_chars_is_echoed_and_33_is_not():
    ok = "a" * 32
    with pytest.raises(FlowDefinitionError) as ei:
        _flow(steps=[_bogus(ok)])
    assert f"'{ok}'" in str(ei.value)
    with pytest.raises(FlowDefinitionError) as ei:
        _flow(steps=[_bogus(ok + "a")])
    assert str(ei.value) == "step 0: kind: unknown_kind '<invalid>'"


@pytest.mark.parametrize(
    "hostile",
    ["bad\nkind", "it's \"q\"", "x" * 200, "${x}", "k\u00e9\u4e2d", "", 5, None],
)
def test_unsupported_kind_hostile_value_is_not_echoed(hostile):
    with pytest.raises(FlowDefinitionError) as ei:
        _flow(steps=[_bogus(hostile)])
    err = ei.value
    assert "unknown_kind '<invalid>'" in str(err)
    if isinstance(hostile, str) and hostile:
        for text in (str(err), repr(err), *map(str, err.args)):
            assert hostile not in text


# ---- exception hierarchy ------------------------------------------------


@pytest.mark.parametrize("cls", [FlowError, FlowInputError, FlowDefinitionError])
def test_flow_errors_are_not_connector_or_recognizer_errors(cls):
    assert not issubclass(cls, ConnectorError)
    assert not issubclass(cls, RecognizerError)


# ---- dependencies -------------------------------------------------------


def test_pyproject_dependency_lists_unchanged():
    # The `publish` extra and the dev entry for it are allowed by publisher Requirement 18.3.
    project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
    assert project["dependencies"] == EXPECTED_DEPENDENCIES
    assert project["optional-dependencies"] == EXPECTED_OPTIONAL
