"""Property 13 of the more-flows spec: a blank is accepted once it has stayed the Settle_Time."""
from __future__ import annotations

from hypothesis import event, given, settings
from hypothesis import strategies as st

from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import ExpectStep, Flow, KeyStep, Timeouts
from greenscreen.flow.runner import run_flow
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import FakeClock, capture, copy_screen

# The settle value comes from the shipped signature, never a literal here.
_SETTLE = next(s.stable_for for s in load_bundled_signatures() if s.name == "tso-cleared")
_SIGS = [s for s in load_bundled_signatures() if s.name in ("tso-ready", "tso-cleared")]


def _flow(timeout: float) -> Flow:
    # tso-ready is the start screen; "tk5-logo" (the other frame) is in no signature of the Flow.
    return Flow(
        name="stable-model",
        steps=(
            ExpectStep(("tso-ready",)),
            KeyStep("clear"),
            ExpectStep(("tso-cleared",), timeout=timeout),
        ),
        timeouts=Timeouts(step=timeout, run=600.0),
    )


def _is_blank_at(frames: list[tuple[bool, int]], elapsed: float) -> bool:
    """Frame kind (True = blank) shown ``elapsed`` seconds after the key."""
    edge = 0.0
    for blank, ms in frames:
        edge += ms / 1000
        if elapsed < edge:
            return blank
    return frames[-1][0]  # the last frame stays


class _TimelineSession:
    """Shows ``tso-ready`` until Clear, then the frames on the Clock."""

    def __init__(self, frames: list[tuple[bool, int]], clock: FakeClock) -> None:
        self._frames = frames
        self._clock = clock
        self._t0: float | None = None
        self.calls: list[tuple] = []

    def read_screen(self):
        self.calls.append(("read",))
        if self._t0 is None:
            return capture("tso-ready")
        blank = _is_blank_at(self._frames, self._clock.monotonic() - self._t0)
        return copy_screen(capture("tso-cleared" if blank else "tk5-logo"))

    def clear(self) -> None:
        self.calls.append(("clear",))
        self._t0 = self._clock.monotonic()

    def string(self, text: str) -> None:
        raise AssertionError("no typing in this Flow")

    def enter(self) -> None:
        raise AssertionError("no Enter in this Flow")

    def pf(self, n: int) -> None:
        raise AssertionError("no PF in this Flow")

    def pa(self, n: int) -> None:
        raise AssertionError("no PA in this Flow")

    def close(self) -> None:
        self.calls.append(("close",))


def _model(frames, poll: float, timeout: float):
    """Predict (accepted, Clock reading at the end) with a plain loop."""
    now = 0.0  # the key is pressed at Clock 0.0; the first read is at once
    since: float | None = None
    while True:
        if _is_blank_at(frames, now - 0.0):
            if since is None:
                since = now
            if now - since >= _SETTLE:
                return True, now
        else:
            since = None
        if now - 0.0 >= timeout:
            return False, now
        now += poll


@st.composite
def _timelines(draw):
    n = draw(st.integers(1, 8))
    first_blank = draw(st.booleans())
    return [
        ((i % 2 == 0) == first_blank, draw(st.integers(1, 700))) for i in range(n)
    ]


# Feature: more-flows, Property 13: A blank screen is accepted exactly when it has stayed the Settle_Time
# **Validates: Requirements 24.5, 24.6, 24.15**
@settings(max_examples=200, deadline=None)
@given(
    frames=_timelines(),
    poll=st.sampled_from([0.01, 0.05, 0.1, 0.25, 0.5, 1.0]),
    timeout=st.sampled_from([0.1, 0.2, 0.5, 1.0, 2.5, 5.0]),
)
def test_blank_accepted_exactly_when_settled(frames, poll, timeout):
    expected_ok, expected_clock = _model(frames, poll, timeout)
    event(f"accepted={expected_ok}")

    clock = FakeClock()
    session = _TimelineSession(frames, clock)
    try:
        result = run_flow(_flow(timeout), session, {}, signatures=_SIGS, clock=clock, poll_interval=poll)
    except FlowError as exc:
        assert not expected_ok, f"model predicted acceptance, got {exc.reason!r}"
        assert exc.reason == "unknown_screen"
        assert exc.step_index == 2
        assert clock.now == expected_clock
    else:
        assert expected_ok, "model predicted a stop, the step accepted"
        assert result.audit[-1].signature == "tso-cleared"
        assert clock.now == expected_clock
