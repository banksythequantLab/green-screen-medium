"""Property 14 of the more-flows spec: the signature YAML round trip with ``stable_for``."""
from __future__ import annotations

import dataclasses

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.recognizer import SignatureError
from greenscreen.recognizer.signature import ScreenSignature
from tests.property._recognizer_strategies import signatures

_VALID = st.one_of(
    st.just(0),
    st.just(5),
    st.integers(0, 5),
    st.floats(min_value=0.0, max_value=5.0, allow_nan=False, allow_infinity=False),
)

_BAD = st.one_of(
    st.booleans(),
    st.text(max_size=8),
    st.integers(max_value=-1),
    st.floats(max_value=-1e-9, allow_nan=False, allow_infinity=False),
    st.integers(min_value=6),
    st.floats(min_value=5.000001, allow_nan=False, allow_infinity=False),
)


def _with_value(sig: ScreenSignature, value: object) -> str:
    """The YAML of ``sig`` with ``stable_for`` set to ``value`` (any type)."""
    doc = yaml.safe_load(sig.to_yaml())
    doc["stable_for"] = value
    return yaml.safe_dump(doc, sort_keys=False)


# Feature: more-flows, Property 14: The signature YAML round trip holds with stable_for
# **Validates: Requirements 24.1, 24.2, 24.3**
@settings(max_examples=100, deadline=None)
@given(sig=signatures(), value=_VALID, bad=_BAD)
def test_stable_for_yaml_round_trip(sig, value, bad):
    s = dataclasses.replace(sig, stable_for=value)
    text = s.to_yaml()
    assert ScreenSignature.from_yaml(text) == s
    has_line = any(line.startswith("stable_for:") for line in text.splitlines())
    assert has_line == (value != 0)
    assert s.to_yaml() == text

    with pytest.raises(SignatureError) as caught:
        ScreenSignature.from_yaml(_with_value(sig, bad))
    assert "stable_for" in str(caught.value)
    with pytest.raises(SignatureError) as caught:
        dataclasses.replace(sig, stable_for=bad)
    assert "stable_for" in str(caught.value)
