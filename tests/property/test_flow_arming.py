"""Property 7 of the flow-runtime spec: every Key_Step and Type_Step needs an arming Step."""
from __future__ import annotations

import re
from unittest import mock

import pytest
from hypothesis import assume, given, settings

from greenscreen.flow.model import ExpectStep, Flow, HandleStep, KeyStep, TypeStep
from greenscreen.flow.validate import FlowDefinitionError
from tests.property import _flow_strategies as fs


def _first_unarmed(steps: tuple) -> tuple[int, int]:
    """(top-level position, Step_Index) of the first unarmed Key_Step or Type_Step.

    Armed means an Expect_Step earlier in the list with no Key_Step between. A
    Handle_Step does not arm the Step after it. Numbering is depth-first, a
    Handle_Step before its body.
    """
    armed = False
    index = 0
    for pos, step in enumerate(steps):
        if isinstance(step, ExpectStep):
            armed = True
        elif isinstance(step, (KeyStep, TypeStep)):
            if not armed:
                return pos, index
            armed = armed and isinstance(step, TypeStep)
        elif isinstance(step, HandleStep):
            armed = False
            index += len(step.steps)
        index += 1
    raise AssertionError("no unarmed Step in the unarmed variant")


# Feature: flow-runtime, Property 7: Every Key_Step and Type_Step needs an arming Step
@settings(max_examples=100, deadline=None)
@given(parts=fs.PARTS, k=fs.st.integers(0, 5))
def test_unarmed_key_or_type_step_is_rejected_and_repair_is_valid(parts, k):
    """**Validates: Requirements 5.6, 5.7, 5.8**"""
    # The repaired Flow (every action block armed) must be valid.
    repaired = fs.build_from_parts(parts)
    assert isinstance(repaired, Flow)

    try:
        fs.build_from_parts(parts, unarm=k)
    except ValueError:
        assume(False)  # no action block to unarm
    except FlowDefinitionError as error:
        message = str(error)
    else:
        pytest.fail("the unarmed variant was accepted by the validator")

    # Capture the unarmed variant's Steps without running the validator.
    with mock.patch.object(fs, "Flow", lambda **kwargs: kwargs):
        raw = fs.build_from_parts(parts, unarm=k)
    steps = raw["steps"]
    pos, index = _first_unarmed(steps)

    assert message.startswith(f"step {index}:"), (message, index)
    assert re.search(r"unarmed", message), message

    # An Expect_Step immediately before that Step makes the Flow valid.
    fixed = steps[:pos] + (ExpectStep((fs.SIGNATURE_NAMES[0],)),) + steps[pos:]
    Flow(**{**raw, "steps": fixed})
