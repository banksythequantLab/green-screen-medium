"""Property 3 of the flow-runtime spec: no secret or hidden content leaves the runner."""
from __future__ import annotations

import dataclasses
import logging
import re
import traceback

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.flow import FlowError, run_flow
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
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import (
    FakeClock,
    ScriptedSession,
    ScriptedState,
    blank_screen,
    capture,
    pause_variant,
    sentinel_password_screen,
)
from tests.property import _flow_strategies as fs

_PROMPT = "tso-password-prompt"
_ALIAS = "tso-password-alias"
_BUNDLED = load_bundled_signatures()
_ALIAS_SIGS = _BUNDLED + [
    dataclasses.replace(s, name=_ALIAS) for s in _BUNDLED if s.name == _PROMPT
]

_SECRET = InputSpec("pw", "str", True, 8, None, True)
_SECRET_STRICT = InputSpec("pw", "str", True, 8, "[A-Z]+", True)
_TIMEOUTS = Timeouts(0.5, 60.0, 10.0)
_OUT_STR = OutputSpec("OUT", "str", "ispf-primary-menu", 0, 0, 8)
_OUT_INT = OutputSpec("NUM", "int", "ispf-primary-menu", 0, 0, 8)
_OUT_HIDDEN = OutputSpec("PW", "str", _PROMPT, 1, 1, 8)

# (key kind, key step) pairs a Flow may use after typing the secret.
_KEYS = {
    "enter": KeyStep("enter"),
    "clear": KeyStep("clear"),
    "pf": KeyStep("pf", 3),
    "pa": KeyStep("pa", 2),
}
_FAIL_METHODS = ("read_screen", "string", "enter", "clear", "pf", "pa")
_SCENARIOS = (
    "success",
    "residual_wrong_screen",
    "hidden_output",
    "unknown_after_key",
    "output_type",
    "input_invalid",
    "secret_target",
    "bad_target",
    "run_timeout",
    "loop_limit",
    "session_error",
    "prekey_blank",
    "prekey_unknown",
    "ambiguous",
)
# Reason_Codes (None is success) a scenario may end in; the scripts are built to hit the first.
_ALLOWED = {
    "success": {None},
    "residual_wrong_screen": {"timeout", "unexpected_screen"},
    "hidden_output": {"hidden_output"},
    "unknown_after_key": {"unknown_screen"},
    "output_type": {"output_type"},
    "input_invalid": {"input_invalid"},
    "secret_target": {"secret_target"},
    "bad_target": {"bad_target"},
    "run_timeout": {"run_timeout"},
    "loop_limit": {"loop_limit"},
    "session_error": {"session_error", None},
    "prekey_blank": {"unexpected_screen"},
    "prekey_unknown": {"unknown_screen"},
    "ambiguous": {"ambiguous_screen"},
}

_SHAPES = tuple(
    re.compile(p)
    for p in (
        r"flow=\S+ step=\d+ kind=\w+",
        r"flow=\S+ step=\d+ kind=\w+ signature=\S+ count=\d+ ms=\d+",
        r"flow=\S+ step=(\d+|none) reason=\w+",
        r"flow=\S+ count=\d+ ms=\d+",
    )
)


_MARKER_LINE = re.compile(r"\s*[~^]+[\s~^]*")


class _Boom(Exception):
    pass


def _exception(kind: int, sentinel: str) -> Exception:
    if kind == 0:
        return ValueError(sentinel)
    if kind == 1:
        return OSError(f"connection lost: {sentinel}", sentinel)
    if kind == 2:
        return _Boom(sentinel, {"secret": sentinel})
    try:
        raise KeyError(sentinel)
    except KeyError as inner:
        outer = RuntimeError(f"wrapped {sentinel}")
        outer.__cause__ = inner
        return outer


class _TestSession(ScriptedSession):
    """A ScriptedSession that can raise at a call and can swap one read."""

    def __init__(self, states, *, echo_typing, fail=None, swap=None):
        super().__init__(states, echo_typing=echo_typing)
        self._fail = fail  # (method, nth call, exception)
        self._swap = swap or {}  # nth read -> Screen
        self._counts: dict[str, int] = {}

    def _maybe_fail(self, method: str) -> None:
        n = self._counts[method] = self._counts.get(method, 0) + 1
        if self._fail and self._fail[0] == method and self._fail[1] == n:
            raise self._fail[2]

    def read_screen(self):
        self._maybe_fail("read_screen")
        screen = super().read_screen()
        return self._swap.get(self._counts["read_screen"], screen)

    def string(self, text):
        self._maybe_fail("string")
        super().string(text)

    def enter(self):
        self._maybe_fail("enter")
        super().enter()

    def clear(self):
        self._maybe_fail("clear")
        super().clear()

    def pf(self, n):
        self._maybe_fail("pf")
        super().pf(n)

    def pa(self, n):
        self._maybe_fail("pa")
        super().pa(n)


def _unknown_prompt():
    """A screen with the prompt's geometry that no Signature accepts."""
    screen = capture(_PROMPT)
    for col in range(screen.columns):
        if isinstance(screen.cell_grid[0][col], int):
            screen.cell_grid[0][col] = ord("Z")
    return screen


def _build(scenario: str, key: str, sentinel: str, fail_method: str):
    """Return (flow, states, supplied value, signatures, swap) for a scenario."""
    keystep = _KEYS[fail_method if fail_method in _KEYS else key]
    prompt = ExpectStep((_PROMPT,))
    typed = (prompt, TypeStep(input="pw"), keystep)
    inputs = (_SECRET,)
    outputs: tuple = ()
    steps: tuple = typed
    states = [capture(_PROMPT), pause_variant(0), capture("ispf-primary-menu")]
    signatures = _BUNDLED
    swap: dict = {}
    timeouts = _TIMEOUTS
    value = sentinel

    after_pause = (ExpectStep(("tso-pause",)), KeyStep("enter"), ExpectStep(("ispf-primary-menu",)))
    if scenario in ("success", "session_error"):
        outputs = (_OUT_STR,)
        steps = typed + after_pause + (ExtractStep("OUT"),)
    elif scenario == "residual_wrong_screen":
        steps = typed + (ExpectStep(("tso-pause",)),)
        states = [capture(_PROMPT), sentinel_password_screen(sentinel)]
    elif scenario == "hidden_output":
        outputs = (_OUT_HIDDEN,)
        steps = typed + (ExpectStep((_PROMPT,)), ExtractStep("PW"))
        states = [capture(_PROMPT), sentinel_password_screen(sentinel)]
    elif scenario == "unknown_after_key":
        steps = typed + (ExpectStep(("tso-pause",)),)
        states = [capture(_PROMPT), blank_screen()]
    elif scenario == "output_type":
        outputs = (_OUT_INT,)
        steps = typed + after_pause + (ExtractStep("NUM"),)
    elif scenario == "input_invalid":
        inputs = (_SECRET_STRICT,)
        value = sentinel
    elif scenario == "secret_target":
        steps = (ExpectStep(("tk5-logon",)), TypeStep(input="pw"), keystep)
        states = [capture("tk5-logon")]
    elif scenario == "bad_target":
        steps = (ExpectStep(("tk5-logo",)), TypeStep(input="pw"), keystep)
        states = [capture("tk5-logo")]
    elif scenario == "run_timeout":
        steps = typed + (ExpectStep(("tso-pause",)),)
        states = [capture(_PROMPT), sentinel_password_screen(sentinel)]
        timeouts = Timeouts(5.0, 1.0, 10.0)
    elif scenario == "loop_limit":
        steps = typed + (HandleStep("tso-pause", 1, (KeyStep("enter"),)),)
        states = [capture(_PROMPT)] + [pause_variant(i) for i in range(4)]
    elif scenario == "prekey_blank":
        swap = {2: blank_screen()}
    elif scenario == "prekey_unknown":
        swap = {2: _unknown_prompt()}
    elif scenario == "ambiguous":
        steps = (ExpectStep((_PROMPT,), (_ALIAS,)), TypeStep(input="pw"), keystep)
        signatures = _ALIAS_SIGS
    flow = Flow(
        name="leak-flow",
        steps=steps,
        inputs=inputs,
        outputs=outputs,
        timeouts=timeouts,
    )
    return flow, states, value, signatures, swap


def _error_texts(err: BaseException) -> list[str]:
    texts = [str(err), repr(err), repr(err.args), repr(vars(err))]
    summary = getattr(err, "summary", None)
    if summary is not None:
        texts += [repr(summary), summary.to_text()]
    texts += [repr(r) for r in getattr(err, "audit", ())]
    formatted = "".join(traceback.format_exception(err))
    # Python 3.11 marks the failing expression of a source line with ``~~~^^^``.
    # Those marker-only lines are made of the sentinel alphabet and carry no text.
    kept = [ln for ln in formatted.splitlines() if not _MARKER_LINE.fullmatch(ln)]
    texts.append("\n".join(kept))
    return texts


def _run(flow, session, inputs, signatures, clock):
    # One line, so the traceback of a raised error shows no caret markers
    # (``~~~^^^``) that would collide with the sentinel alphabet.
    return run_flow(flow, session, inputs, signatures=signatures, clock=clock)


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


# Feature: flow-runtime, Property 3: No secret or hidden content leaves the runner
@settings(max_examples=100, deadline=None)
@given(
    scenario=st.sampled_from(_SCENARIOS),
    sentinel=fs.secrets(),
    key=st.sampled_from(sorted(_KEYS)),
    echo=st.booleans(),
    fail_method=st.sampled_from(_FAIL_METHODS),
    fail_nth=st.integers(1, 3),
    exc_kind=st.integers(0, 3),
)
def test_no_secret_or_hidden_content_leaves_the_runner(
    scenario, sentinel, key, echo, fail_method, fail_nth, exc_kind
):
    """**Validates: Requirements 10.9, 14.4, 14.5, 14.6, 15.3, 15.5, 16.1, 16.2, 16.4, 16.8**"""
    flow, states, value, signatures, swap = _build(scenario, key, sentinel, fail_method)
    fail = None
    if scenario == "session_error":
        fail = (fail_method, fail_nth, _exception(exc_kind, sentinel))
    session = _TestSession(
        [ScriptedState(s) for s in states], echo_typing=echo, fail=fail, swap=swap
    )

    logger = logging.getLogger("greenscreen.flow")
    handler = _Collect()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    error: FlowError | None = None
    result = None
    try:
        try:
            result = _run(flow, session, {"pw": value}, signatures, FakeClock())
        except FlowError as caught:
            error = caught
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)

    reason = None if error is None else error.reason
    reason_allowed = reason in _ALLOWED[scenario]
    assert reason_allowed, (scenario, reason)

    texts: list[str] = []
    if result is not None:
        texts += [repr(result), str(result), result.flow, repr(dict(result.outputs))]
        texts += [repr(r) for r in result.audit]
    if error is not None:
        texts += _error_texts(error)
        message = str(error)
        step = "none" if error.step_index is None else error.step_index
        assert error.__cause__ is None
        assert error.__context__ is None
        assert "\n" not in message and "\r" not in message
        assert len(message) <= 500
        has_reason_and_step = error.reason in message and f"at step {step} " in message
        assert has_reason_and_step
    for record in handler.records:
        shown = record.getMessage()
        texts += [str(record.msg), shown, repr(record.args)]
        assert record.levelno == logging.DEBUG
        assert all(type(a) in (str, int) for a in record.args)
        matches_a_shape = any(p.fullmatch(shown) for p in _SHAPES)
        assert matches_a_shape

    leaked = any(sentinel in text for text in texts)
    assert not leaked
