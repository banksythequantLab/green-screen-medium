"""Property 5: c0 attribute byte flag correctness (Task 4.3).

Feature: tn3270-connector
Validates: Requirement 5.9
"""
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from greenscreen.connector.models import SFToken, Screen


@given(st.integers(min_value=0, max_value=0xFF))
@settings(max_examples=256)
def test_protected_flag(c0: int) -> None:
    """protected == bool(c0 & 0x20) for all byte values."""
    # Feature: tn3270-connector, Property 5: c0 attribute byte flag correctness
    # Build a minimal Screen with this SFToken and check derived Field
    cell_grid = [[SFToken(c0=c0), 0x41]]
    s = Screen(1, 2, 0, 0, cell_grid, [[]])
    fields = s.fields
    assert len(fields) == 1
    assert fields[0].protected == bool(c0 & 0x20)


@given(st.integers(min_value=0, max_value=0xFF))
@settings(max_examples=256)
def test_modified_flag(c0: int) -> None:
    """modified == bool(c0 & 0x01) for all byte values."""
    cell_grid = [[SFToken(c0=c0), 0x41]]
    s = Screen(1, 2, 0, 0, cell_grid, [[]])
    assert s.fields[0].modified == bool(c0 & 0x01)


@given(st.integers(min_value=0, max_value=0xFF))
@settings(max_examples=256)
def test_numeric_flag(c0: int) -> None:
    """numeric == bool(c0 & 0x10) for all byte values."""
    cell_grid = [[SFToken(c0=c0), 0x41]]
    s = Screen(1, 2, 0, 0, cell_grid, [[]])
    assert s.fields[0].numeric == bool(c0 & 0x10)


@given(st.integers(min_value=0, max_value=0xFF))
@settings(max_examples=256)
def test_hidden_flag(c0: int) -> None:
    """hidden == ((c0 & 0x0C) == 0x0C) for all byte values."""
    cell_grid = [[SFToken(c0=c0), 0x41]]
    s = Screen(1, 2, 0, 0, cell_grid, [[]])
    assert s.fields[0].hidden == ((c0 & 0x0C) == 0x0C)


# Fixture-validated values (from /captures)
@pytest.mark.parametrize("c0,expected_protected", [
    (0xc8, False),  # logon input field — unprotected
    (0xe0, True),
    (0xe8, True),
    (0xf0, True),
    (0xf8, True),
])
def test_fixture_c0_values(c0: int, expected_protected: bool) -> None:
    """c0 values from /captures must decode correctly."""
    cell_grid = [[SFToken(c0=c0), 0x41]]
    s = Screen(1, 2, 0, 0, cell_grid, [[]])
    assert s.fields[0].protected == expected_protected
