# Feature: tn3270-connector, Property 8: wait timeout substitution
"""Property 8: wait_* methods send Wait(N,<Type>) with N = explicit timeout,
or config.default_timeout when the timeout is None.

**Validates: Requirements 4.1, 4.2, 4.3**
"""
from __future__ import annotations

import re

import pytest
from hypothesis import given, settings, strategies as st

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.testing.fake import FakeS3270, ScriptedResponse

STATUS = "U F U C(h) I 2 24 80 0 0 0x0 0.000"

WAIT_METHODS = [
    ("wait_for_output", "Output"),
    ("wait_for_field", "InputField"),
    ("wait_for_unlock", "Unlock"),
]


class RecordingFake(FakeS3270):
    """FakeS3270 that records every command it receives."""

    def __init__(self, script: list[ScriptedResponse]) -> None:
        self.commands: list[str] = []
        super().__init__(script)

    def _dispatch(self, command: str) -> None:
        self.commands.append(command)
        super()._dispatch(command)


def _ok(pattern: str) -> ScriptedResponse:
    return ScriptedResponse(pattern, [], STATUS, "ok")


def _make(default_timeout: float, with_wait: bool = True) -> tuple[Connector, RecordingFake]:
    script = [_ok(r"Connect\(.*\)")]
    if with_wait:
        script.append(_ok(r"Wait\((.+),(Output|InputField|Unlock)\)"))
    script += [_ok(r"Disconnect\(\)"), _ok(r"Quit\(\)")]
    fake = RecordingFake(script)
    cfg = ConnectorConfig(
        binary="s3270", host="localhost", port=23, default_timeout=default_timeout
    )
    return Connector(cfg, process_factory=lambda *a, **k: fake), fake


default_timeouts = st.one_of(
    st.floats(min_value=1.0, max_value=3600.0, allow_nan=False),
    st.integers(min_value=1, max_value=3600).map(float),
)
explicit_timeouts = st.one_of(
    st.none(),
    st.floats(min_value=0.001, max_value=3600.0, allow_nan=False),
    st.integers(min_value=1, max_value=3600).map(float),
)

WIRE_RE = re.compile(r"^\d+(\.\d{1,3})?$")


@pytest.mark.parametrize("method,wait_type", WAIT_METHODS)
@settings(max_examples=100, deadline=None)
@given(default=default_timeouts, explicit=explicit_timeouts)
def test_wait_timeout_substitution(method, wait_type, default, explicit):
    conn, fake = _make(default)
    with conn:
        getattr(conn, method)(explicit)
    intended = default if explicit is None else explicit

    wait_cmds = [c for c in fake.commands if c.startswith("Wait(")]
    assert len(wait_cmds) == 1
    m = re.fullmatch(r"Wait\((.+),(\w+)\)", wait_cmds[0])
    assert m is not None
    n_text, sent_type = m.groups()
    assert sent_type == wait_type
    assert n_text == Connector._format_seconds(intended)
    # Wire value is rounded to 3 decimals, fixed-point, no exponent.
    assert WIRE_RE.match(n_text), n_text
    assert "." not in n_text or not n_text.endswith("0")
    assert not n_text.endswith(".")
    assert "e" not in n_text.lower()
    assert abs(float(n_text) - intended) <= 0.0005 + 1e-9
    assert 0.001 <= float(n_text) <= 3600


@pytest.mark.parametrize("method,wait_type", WAIT_METHODS)
@pytest.mark.parametrize(
    "bad",
    [0.0, -1.0, -0.001, 3600.001, 1e9, 1e-5, 5e-324, 0.0004, 0.0009,
     float("nan"), float("inf"), float("-inf"), True, "5"],
)
def test_out_of_range_timeout_raises_and_sends_nothing(method, wait_type, bad):
    conn, fake = _make(30.0, with_wait=False)
    with conn:
        before = list(fake.commands)
        with pytest.raises(ValueError):
            getattr(conn, method)(bad)
        assert fake.commands == before


@pytest.mark.parametrize("method,wait_type", WAIT_METHODS)
def test_minimum_timeout_accepted_in_fixed_point(method, wait_type):
    conn, fake = _make(30.0)
    with conn:
        getattr(conn, method)(0.001)
    assert f"Wait(0.001,{wait_type})" in fake.commands
    assert not any("e-" in c for c in fake.commands)


@pytest.mark.parametrize("method,wait_type", WAIT_METHODS)
def test_none_timeout_uses_default(method, wait_type):
    conn, fake = _make(12.5)
    with conn:
        getattr(conn, method)(None)
    assert f"Wait(12.5,{wait_type})" in fake.commands
