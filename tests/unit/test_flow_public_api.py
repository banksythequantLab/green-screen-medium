"""Public API of greenscreen.flow.

**Validates: Requirements 21.1**
"""

import importlib

import pytest

import greenscreen.flow

NAMES = [
    "Flow",
    "load_flow",
    "load_bundled_flows",
    "run_flow",
    "FlowResult",
    "AuditRecord",
    "FlowError",
    "FlowInputError",
    "FlowDefinitionError",
]


@pytest.mark.parametrize("name", NAMES)
def test_name_is_importable(name):
    namespace: dict = {}
    exec(f"from greenscreen.flow import {name}", namespace)
    assert namespace[name] is getattr(importlib.import_module("greenscreen.flow"), name)


def test_all_holds_exactly_the_nine_names():
    assert len(greenscreen.flow.__all__) == 9
    assert sorted(greenscreen.flow.__all__) == sorted(NAMES)
