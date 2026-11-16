"""Property 7: pf/pa raise ValueError iff n is outside [1, 24].

**Validates: Requirements 3.5**
"""
from __future__ import annotations

import re

import pytest
from hypothesis import given, settings, strategies as st

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.connector import Connector
from greenscreen.connector.testing.fake import FakeS3270, ScriptedResponse

STATUS = "U F U C(h) I 2 24 80 0 0 0x0 0.000"


def _entry(pattern: str) -> ScriptedResponse:
    return ScriptedResponse(pattern, [], STATUS, "ok")


def _run(method: str, n: int) -> None:
    """Fresh Connector + FakeS3270 for one example; assert the property."""
    in_range = 1 <= n <= 24
    expected = f"{method.upper()}({n})"
    script = [_entry(r"Connect\(.*\)")]
    if in_range:
        script.append(_entry(re.escape(expected)))
    script += [_entry(r"Disconnect\(\)"), _entry(r"Quit\(\)")]

    fake = FakeS3270(script)
    conn = Connector(
        ConnectorConfig(binary="fake", host="h", port=3270),
        process_factory=lambda *a, **k: fake,
    )
    try:
        conn.open()
        assert fake._index == 1  # only Connect so far
        call = getattr(conn, method)
        if in_range:
            resp = call(n)
            assert resp.success
            assert fake._index == 2  # exactly one command: PF(n)/PA(n)
        else:
            with pytest.raises(ValueError):
                call(n)
            assert fake._index == 1  # nothing was sent
    finally:
        conn.close()
        # Close the WRITE ends so the reader threads see EOF and exit.
        # (Closing the read end under a blocked reader deadlocks on Windows.)
        fake.terminate()
        fake.stdin.close()
    assert fake._index == len(script)  # only Disconnect/Quit followed


# Feature: tn3270-connector, Property 7: pf/pa raises ValueError iff n out of [1, 24]
@settings(max_examples=100, deadline=None)
@given(n=st.integers(-1000, 1000))
def test_pf_boundary_property(n: int) -> None:
    _run("pf", n)


# Feature: tn3270-connector, Property 7: pf/pa raises ValueError iff n out of [1, 24]
@settings(max_examples=100, deadline=None)
@given(n=st.integers(-1000, 1000))
def test_pa_boundary_property(n: int) -> None:
    _run("pa", n)


@pytest.mark.parametrize("method", ["pf", "pa"])
@pytest.mark.parametrize("n", [0, 1, 24, 25])
def test_explicit_boundaries(method: str, n: int) -> None:
    _run(method, n)
