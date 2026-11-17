"""Unit tests for the Flow_Validator (flow-runtime Requirements 2 to 5)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from greenscreen.flow.errors import FlowDefinitionError
from greenscreen.flow.model import (
    ExpectStep,
    ExtractStep,
    Flow,
    HandleStep,
    InputSpec,
    KeyStep,
    OutputSpec,
    Timeouts,
    TypeStep,
)
from greenscreen.flow.validate import (
    check_flow,
    reference_violations,
    structural_violations,
)
from greenscreen.recognizer import ScreenSignature
from greenscreen.recognizer.signature import TextAtMatcher

USER = InputSpec(name="user", type="str", required=True, max_length=8)
OUT = OutputSpec(name="out", type="str", signature="a", row=0, col=0, length=5)
OK_STEPS = (
    ExpectStep(signatures=("a",)),
    TypeStep(input="user"),
    ExtractStep(output="out"),
    KeyStep(key="enter"),
)
NAMES = frozenset({"a", "b", "c"})


def mk(
    steps=OK_STEPS,
    inputs=(USER,),
    outputs=(OUT,),
    finally_steps=(),
    timeouts=None,
    description="",
    name="demo",
) -> Flow:
    """Build a Flow without running construction-time validation."""
    flow = object.__new__(Flow)
    values = {
        "name": name,
        "steps": tuple(steps),
        "description": description,
        "inputs": tuple(inputs),
        "outputs": tuple(outputs),
        "finally_steps": tuple(finally_steps),
        "timeouts": timeouts if timeouts is not None else Timeouts(),
    }
    for key, value in values.items():
        object.__setattr__(flow, key, value)
    return flow


def swap(index, step, steps=OK_STEPS):
    items = list(steps)
    items[index] = step
    return tuple(items)


def found(flow, field, rule, step=None) -> bool:
    return any(
        v.field == field and v.rule == rule and (step is None or v.step_index == step)
        for v in structural_violations(flow)
    )


def test_base_flow_is_valid():
    assert structural_violations(mk()) == []
    assert reference_violations(mk(), NAMES) == []
    sigs = [ScreenSignature(n, (TextAtMatcher(0, 0, "x"),)) for n in NAMES]
    check_flow(mk(), sigs)
    Flow(name="demo", steps=OK_STEPS, inputs=(USER,), outputs=(OUT,))


# ---------------------------------------------------------------- inputs (Req 2)


@pytest.mark.parametrize("bad", ["1x", "", "a" * 33, "a-b"])
def test_input_name_pattern(bad):
    flow = mk(inputs=(replace(USER, name=bad),), steps=swap(1, TypeStep(text="x")))
    assert found(flow, "input[0].name", "invalid_name")


def test_input_duplicate_name_is_case_sensitive():
    dup = (USER, replace(USER))
    assert found(mk(inputs=dup), "input user.name", "duplicate")
    assert not found(mk(inputs=(USER, replace(USER, name="User"))), "input User.name", "duplicate")


def test_input_type():
    assert found(mk(inputs=(replace(USER, type="float"),)), "input user.type", "invalid")


@pytest.mark.parametrize("bad", ["yes", 1, None])
def test_input_required_must_be_boolean(bad):
    assert found(mk(inputs=(replace(USER, required=bad),)), "input user.required", "not_boolean")


@pytest.mark.parametrize("bad", [True, 0, 256, "5", 2.0])
def test_input_max_length_rejected(bad):
    assert found(mk(inputs=(replace(USER, max_length=bad),)), "input user.max_length", "out_of_range")


@pytest.mark.parametrize("ok", [1, 255])
def test_input_max_length_bounds_accepted(ok):
    assert structural_violations(mk(inputs=(replace(USER, max_length=ok),))) == []


@pytest.mark.parametrize("bad", ["(", "", "a" * 201, 5])
def test_input_regex_rejected(bad):
    assert found(mk(inputs=(replace(USER, regex=bad),)), "input user.regex", "invalid")


def test_input_regex_accepted():
    assert structural_violations(mk(inputs=(replace(USER, regex="[a-z]+"),))) == []
    assert structural_violations(mk(inputs=(replace(USER, regex="a" * 200),))) == []


def test_input_secret_with_int_rejected():
    spec = replace(USER, type="int", secret=True)
    assert found(mk(inputs=(spec,)), "input user.secret", "secret_requires_str")


def test_input_secret_must_be_boolean():
    assert found(mk(inputs=(replace(USER, secret="y"),)), "input user.secret", "not_boolean")


def test_input_description_length():
    assert found(mk(inputs=(replace(USER, description="d" * 201),)), "input user.description", "too_long")
    assert structural_violations(mk(inputs=(replace(USER, description="d" * 200),))) == []


def test_input_extra_key_rejected_by_loader():
    text = (
        "version: 1\nname: demo\n"
        "inputs:\n- {name: user, type: str, required: true, max_length: 8, bogus: 1}\n"
        "steps:\n- {expect: {signatures: [a]}}\n- {key: enter}\n"
    )
    with pytest.raises(FlowDefinitionError, match="bogus"):
        Flow.from_yaml(text, [ScreenSignature("a", (TextAtMatcher(0, 0, "x"),))])


# --------------------------------------------------------------- outputs (Req 3)


@pytest.mark.parametrize("bad", ["1x", "", "a" * 33])
def test_output_name_pattern(bad):
    assert found(mk(outputs=(replace(OUT, name=bad),)), "output[0].name", "invalid_name")


def test_output_duplicate_name():
    assert found(mk(outputs=(OUT, replace(OUT))), "output out.name", "duplicate")


def test_output_type():
    assert found(mk(outputs=(replace(OUT, type="bool"),)), "output out.type", "invalid")


@pytest.mark.parametrize(
    "attr,bad",
    [("row", -1), ("row", 24), ("row", True), ("col", -1), ("col", 80), ("length", 0), ("length", 81)],
)
def test_output_region_bounds(attr, bad):
    flow = mk(outputs=(replace(OUT, **{attr: bad}),))
    assert found(flow, f"output out.{attr}", "out_of_range")


@pytest.mark.parametrize("row,col,length", [(23, 79, 1), (0, 0, 80), (0, 75, 5)])
def test_output_region_bounds_accepted(row, col, length):
    assert structural_violations(mk(outputs=(replace(OUT, row=row, col=col, length=length),))) == []


def test_output_col_plus_length_exceeds_row():
    flow = mk(outputs=(replace(OUT, col=76, length=5),))
    assert found(flow, "output out.length", "region_exceeds_row")


# ------------------------------------------------------------------ steps (Req 4)


@pytest.mark.parametrize("sigs", [(), ("a", "b", "c", "a1", "b1", "c1")])
def test_expect_signature_count(sigs):
    assert found(mk(steps=swap(0, ExpectStep(signatures=sigs))), "signatures", "invalid_list", 0)


def test_expect_five_signatures_accepted():
    step = ExpectStep(signatures=("a", "b", "c", "d", "e"))
    assert not found(mk(steps=swap(0, step)), "signatures", "invalid_list")


def test_expect_duplicate_signatures():
    assert found(mk(steps=swap(0, ExpectStep(signatures=("a", "a")))), "signatures", "duplicate", 0)


def test_expect_tolerate_count_and_duplicates():
    six = ExpectStep(signatures=("a",), tolerate=("b", "c", "d", "e", "f", "g"))
    assert found(mk(steps=swap(0, six)), "tolerate", "invalid_list", 0)
    dup = ExpectStep(signatures=("a",), tolerate=("b", "b"))
    assert found(mk(steps=swap(0, dup)), "tolerate", "duplicate", 0)


def test_expect_tolerate_overlap():
    step = ExpectStep(signatures=("a", "b"), tolerate=("b",))
    assert found(mk(steps=swap(0, step)), "tolerate", "overlaps_signatures", 0)


@pytest.mark.parametrize("bad", [0.05, 61, True])
def test_expect_timeout_range(bad):
    step = ExpectStep(signatures=("a",), timeout=bad)
    assert found(mk(steps=swap(0, step)), "timeout", "out_of_range", 0)


@pytest.mark.parametrize("ok", [0.1, 60])
def test_expect_timeout_bounds_accepted(ok):
    assert structural_violations(mk(steps=swap(0, ExpectStep(signatures=("a",), timeout=ok)))) == []


def test_type_step_needs_exactly_one_of_text_and_input():
    both = mk(steps=swap(1, TypeStep(text="x", input="user")))
    neither = mk(steps=swap(1, TypeStep()))
    assert any(v.rule == "exactly_one_required" and v.step_index == 1 for v in structural_violations(both))
    assert any(v.rule == "exactly_one_required" and v.step_index == 1 for v in structural_violations(neither))


@pytest.mark.parametrize("bad", ["", "x" * 256, "caf\u00e9", "a\tb"])
def test_type_text_length_and_characters(bad):
    assert found(mk(steps=swap(1, TypeStep(text=bad))), "text", "invalid_text", 1)


@pytest.mark.parametrize("ok", ["x", "x" * 255, " ~"])
def test_type_text_accepted(ok):
    assert structural_violations(mk(steps=swap(1, TypeStep(text=ok)))) == []


@pytest.mark.parametrize("key", ["tab", "", "PF"])
def test_key_name(key):
    assert found(mk(steps=swap(3, KeyStep(key=key))), "key", "invalid", 3)


@pytest.mark.parametrize("key,n", [("pf", None), ("pf", 0), ("pf", 25), ("pa", 25), ("pf", True), ("pf", 1.0)])
def test_key_n_required_and_range(key, n):
    assert found(mk(steps=swap(3, KeyStep(key=key, n=n))), "n", "out_of_range", 3)


@pytest.mark.parametrize("key", ["enter", "clear"])
def test_key_n_not_allowed_for_enter_and_clear(key):
    assert found(mk(steps=swap(3, KeyStep(key=key, n=1))), "n", "not_allowed", 3)


@pytest.mark.parametrize("key,n", [("pf", 1), ("pf", 24), ("pa", 3), ("enter", None), ("clear", None)])
def test_key_accepted(key, n):
    assert structural_violations(mk(steps=swap(3, KeyStep(key=key, n=n)))) == []


def test_extract_in_finally_rejected():
    fin = (ExpectStep(signatures=("a",)), ExtractStep(output="out"))
    flow = mk(finally_steps=fin)
    assert found(flow, "extract", "not_in_steps", 4 + 1)


def test_extract_undeclared_output():
    assert found(mk(steps=swap(2, ExtractStep(output="nope"))), "output", "undeclared_output", 2)


def test_extract_inside_handle_rejected():
    handle = HandleStep(signature="b", max_count=2, steps=(ExtractStep(output="out"),))
    steps = (ExpectStep(signatures=("a",)), handle, ExpectStep(signatures=("a",)), ExtractStep(output="out"), KeyStep(key="enter"))
    flow = mk(steps=steps, inputs=())
    assert found(flow, "kind", "not_allowed_in_handle", 2)


def test_each_output_needs_exactly_one_extract():
    none = mk(steps=swap(2, KeyStep(key="enter"), OK_STEPS))
    assert found(none, "output out", "needs_exactly_one_extract")
    twice = mk(steps=OK_STEPS[:3] + (ExtractStep(output="out"),) + OK_STEPS[3:])
    assert found(twice, "output out", "needs_exactly_one_extract")


def handle_flow(handle):
    steps = (
        ExpectStep(signatures=("a",)),
        handle,
        ExpectStep(signatures=("a",)),
        TypeStep(input="user"),
        ExtractStep(output="out"),
        KeyStep(key="enter"),
    )
    return mk(steps=steps)


def test_handle_valid():
    assert structural_violations(handle_flow(HandleStep("b", 3, (KeyStep(key="enter"),)))) == []


@pytest.mark.parametrize("bad", [0, 21, True, "3"])
def test_handle_max_count(bad):
    flow = handle_flow(HandleStep("b", bad, (KeyStep(key="enter"),)))
    assert found(flow, "max_count", "out_of_range", 1)


@pytest.mark.parametrize("bad", [-1, 11])
def test_handle_settle(bad):
    flow = handle_flow(HandleStep("b", 3, (KeyStep(key="enter"),), settle=bad))
    assert found(flow, "settle", "out_of_range", 1)


def test_handle_body_size():
    assert found(handle_flow(HandleStep("b", 3, ())), "steps", "invalid_size", 1)
    big = tuple(KeyStep(key="clear") for _ in range(51))
    assert found(handle_flow(HandleStep("b", 3, big)), "steps", "invalid_size", 1)
    ok = tuple(KeyStep(key="clear") for _ in range(50))
    assert not found(handle_flow(HandleStep("b", 3, ok)), "steps", "invalid_size")


def test_handle_body_kinds():
    flow = handle_flow(HandleStep("b", 3, (ExpectStep(signatures=("a",)),)))
    assert found(flow, "kind", "not_allowed_in_handle", 2)


def test_handle_nested_rejected():
    inner = HandleStep("c", 2, (KeyStep(key="enter"),))
    flow = handle_flow(HandleStep("b", 3, (inner,)))
    assert found(flow, "handle", "nested_handle", 2)


# ------------------------------------------------------------ load-time (Req 5)


def test_unknown_signature_names_in_every_place():
    steps = (
        ExpectStep(signatures=("a", "zz"), tolerate=("yy",)),
        HandleStep("xx", 2, (KeyStep(key="enter"),)),
        ExpectStep(signatures=("a",)),
        TypeStep(input="user"),
        ExtractStep(output="out"),
        KeyStep(key="enter"),
    )
    flow = mk(steps=steps, outputs=(replace(OUT, signature="a"),))
    fields = {(v.step_index, v.field) for v in reference_violations(flow, NAMES)}
    assert fields == {(0, "signatures zz"), (0, "tolerate yy"), (1, "signature xx")}
    out_flow = mk(outputs=(replace(OUT, signature="ww"),))
    assert any(
        v.step_index is None and "ww" in v.field and v.rule == "unknown_signature"
        for v in reference_violations(out_flow, NAMES)
    )


def test_check_flow_raises_for_unknown_signature():
    sigs = [ScreenSignature("b", (TextAtMatcher(0, 0, "x"),))]
    with pytest.raises(FlowDefinitionError, match="unknown_signature"):
        check_flow(mk(), sigs)


def test_undeclared_input():
    assert found(mk(steps=swap(1, TypeStep(input="nope"))), "input", "undeclared_input", 1)


def test_unarmed_key_and_type():
    assert found(mk(steps=(KeyStep(key="enter"),), outputs=(), inputs=()), "key", "unarmed", 0)
    flow = mk(steps=(TypeStep(text="x"), ExpectStep(signatures=("a",)), KeyStep(key="enter")), outputs=())
    assert found(flow, "type", "unarmed", 0)
    twice = mk(
        steps=(ExpectStep(signatures=("a",)), KeyStep(key="enter"), KeyStep(key="enter")),
        outputs=(),
    )
    assert found(twice, "key", "unarmed", 2)
    assert not found(twice, "key", "unarmed", 1)


def test_handle_step_leaves_nothing_armed():
    steps = (
        ExpectStep(signatures=("a",)),
        HandleStep("b", 2, (KeyStep(key="enter"),)),
        KeyStep(key="enter"),
    )
    assert found(mk(steps=steps, inputs=(), outputs=()), "key", "unarmed", 3)


def test_handle_body_starts_armed():
    steps = (ExpectStep(signatures=("a",)), HandleStep("b", 2, (TypeStep(text="x"), KeyStep(key="enter"))))
    assert structural_violations(mk(steps=steps, inputs=(), outputs=())) == []


def test_output_signature_must_be_in_arming_expect():
    flow = mk(outputs=(replace(OUT, signature="b"),))
    assert found(flow, "output", "signature_not_in_arming_expect", 2)


def test_extract_after_key_is_unarmed():
    steps = (ExpectStep(signatures=("a",)), KeyStep(key="enter"), ExtractStep(output="out"))
    assert found(mk(steps=steps, inputs=()), "output", "unarmed", 2)


def test_secret_input_in_type_step_input_is_allowed():
    flow = mk(inputs=(replace(USER, secret=True),))
    assert structural_violations(flow) == []


def test_interpolation_marker_in_literal():
    assert found(mk(steps=swap(1, TypeStep(text="${user}"))), "text", "interpolation_marker", 1)


@pytest.mark.parametrize(
    "field,attr,bad",
    [
        ("timeouts.step", "step", 0.05),
        ("timeouts.step", "step", 61.0),
        ("timeouts.run", "run", 0.5),
        ("timeouts.run", "run", 601.0),
        ("timeouts.finally", "finally_", 0.5),
        ("timeouts.finally", "finally_", 121.0),
    ],
)
def test_timeouts_ranges(field, attr, bad):
    assert found(mk(timeouts=Timeouts(**{attr: bad})), field, "out_of_range")


def test_timeouts_bounds_accepted():
    assert structural_violations(mk(timeouts=Timeouts(step=0.1, run=1, finally_=1))) == []
    assert structural_violations(mk(timeouts=Timeouts(step=60, run=600, finally_=120))) == []


# ------------------------------------------------------ ordering and messages


def test_violation_ordering_steps_first_then_flow_level():
    steps = (
        ExpectStep(signatures=("a",)),
        TypeStep(text=""),  # step 1
        ExtractStep(output="out"),
        KeyStep(key="tab"),  # step 3
    )
    flow = mk(
        steps=steps,
        description="d" * 501,
        timeouts=Timeouts(step=0.01),
        outputs=(replace(OUT, row=99),),
    )
    found_list = structural_violations(flow)
    indices = [v.step_index for v in found_list]
    step_part = [i for i in indices if i is not None]
    assert step_part == sorted(step_part)
    first_flow_level = indices.index(None)
    assert all(i is None for i in indices[first_flow_level:])
    assert indices[0] == 1
    flow_level = [(v.requirement, v.criterion, v.field) for v in found_list if v.step_index is None]
    assert flow_level == sorted(flow_level)


def test_construction_message_names_step_field_and_rule():
    with pytest.raises(FlowDefinitionError) as info:
        Flow(name="demo", steps=swap(1, TypeStep(text="")), inputs=(USER,), outputs=(OUT,))
    assert str(info.value) == "step 1: text: invalid_text"


def test_check_flow_message_names_index_kind_field_rule():
    sigs = [ScreenSignature("a", (TextAtMatcher(0, 0, "x"),))]
    with pytest.raises(FlowDefinitionError) as info:
        check_flow(mk(steps=swap(1, TypeStep(input="nope"))), sigs)
    assert str(info.value) == "step 1 (type): field 'input' violates rule 'undeclared_input'"


def test_check_flow_message_for_flow_level_violation():
    sigs = [ScreenSignature("a", (TextAtMatcher(0, 0, "x"),))]
    with pytest.raises(FlowDefinitionError) as info:
        check_flow(mk(description="d" * 501), sigs)
    assert str(info.value) == "flow demo: field 'description' violates rule 'too_long'"


def test_messages_hold_no_yaml_scalar():
    hostile = "ZZ\u00e9SCALAR"
    flow = mk(
        inputs=(replace(USER, name=hostile, regex="(", description="D" * 201),),
        outputs=(replace(OUT, name=hostile, signature=hostile),),
        steps=(
            ExpectStep(signatures=(hostile,), tolerate=(hostile, hostile)),
            TypeStep(text=hostile + "${"),
            TypeStep(input=hostile),
            KeyStep(key=hostile, n=hostile),
        ),
    )
    violations = structural_violations(flow)
    assert violations
    for v in violations:
        assert "SCALAR" not in v.field and "SCALAR" not in v.rule
