"""Property test: recognizer exceptions hold no Screen reference (Property 19)."""
from __future__ import annotations

import gc
import logging
import types

from hypothesis import given, settings
from hypothesis import strategies as st

from greenscreen.connector.models import Field, Screen
from greenscreen.recognizer.errors import (
    AmbiguousScreenError,
    SignatureError,
    UnknownScreenError,
)
from greenscreen.recognizer.recognizer import recognize
from greenscreen.recognizer.signature import (
    RegionRegexMatcher,
    ScreenSignature,
    TextAtMatcher,
)
from tests.property._recognizer_strategies import small_screens

_SKIP = (
    types.ModuleType,
    type,
    types.FunctionType,
    types.BuiltinFunctionType,
    types.MethodType,
    logging.Logger,
)


def _reachable(roots) -> list:
    """Objects reachable from ``roots`` via gc.get_referents, skipping code and modules."""
    seen: dict[int, object] = {}
    stack = list(roots)
    while stack:
        obj = stack.pop()
        if id(obj) in seen or isinstance(obj, _SKIP):
            continue
        seen[id(obj)] = obj
        stack.extend(gc.get_referents(obj))
    return list(seen.values())


def _recognizer_frame_locals(exc: BaseException) -> list:
    """Locals of traceback frames whose module is inside greenscreen.recognizer."""
    values = []
    tb = exc.__traceback__
    while tb is not None:
        frame = tb.tb_frame
        if frame.f_globals.get("__name__", "").startswith("greenscreen.recognizer"):
            values.extend(frame.f_locals.values())
        tb = tb.tb_next
    return values


def _never_matching(name: str, screen: Screen) -> ScreenSignature:
    return ScreenSignature(
        name=name, matchers=(TextAtMatcher(row=screen.rows, col=0, text="X"),)
    )


def _always_matching(name: str) -> ScreenSignature:
    """Matches every screen: the regex accepts the empty string."""
    return ScreenSignature(
        name=name,
        matchers=(RegionRegexMatcher(row=0, col=0, length=1, pattern=r"(?s).*"),),
    )


# Feature: screen-recognizer, Property 19: Exceptions hold no Screen reference
@settings(max_examples=150, deadline=None)
@given(
    screen=small_screens(allow_hidden=True),
    scenario=st.sampled_from(["unknown", "ambiguous", "duplicate", "type_error"]),
    n_sigs=st.integers(0, 3),
)
def test_exceptions_hold_no_screen_reference(screen, scenario, n_sigs):
    """**Validates: Requirements 13.1, 13.4**"""
    if scenario == "unknown":
        sigs = [_never_matching(f"n{i}", screen) for i in range(n_sigs)]
        expected = UnknownScreenError
    elif scenario == "ambiguous":
        sigs = [_always_matching(f"a{i}") for i in range(2 + n_sigs)]
        expected = AmbiguousScreenError
    elif scenario == "duplicate":
        sigs = [_always_matching("dup") for _ in range(2 + n_sigs)]
        expected = SignatureError
    else:
        sigs = [_always_matching(f"t{i}") for i in range(n_sigs)] + ["not-a-signature"]
        expected = TypeError

    exc = None
    try:
        recognize(screen, sigs)
    except Exception as e:  # noqa: BLE001
        exc = e
    assert type(exc) is expected, f"expected {expected.__name__}, got {exc!r}"

    assert exc.__cause__ is None
    assert exc.__context__ is None

    roots = list(exc.args) + list(vars(exc).values()) + _recognizer_frame_locals(exc)
    forbidden = {id(screen), id(screen.cell_grid)} | {id(r) for r in screen.cell_grid}
    for obj in _reachable(roots):
        assert id(obj) not in forbidden, f"reference to screen data: {type(obj).__name__}"
        assert not isinstance(obj, (Screen, Field)), f"reference to {type(obj).__name__}"
