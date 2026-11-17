"""Test support for the flow runtime: fake Clock, scripted Session, screen helpers.

Screens come only from ``load_capture_screen`` (the ``captures/*.readbuffer.txt``
files) or ``make_screen``. Nothing here starts a subprocess, talks to a host or
writes a file. The residual-password screen exists only in memory: its sentinel
is checked to occur in no file under ``captures/``.
"""
from __future__ import annotations

import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pytest

from greenscreen.connector.models import Screen, SFToken
from greenscreen.recognizer import (
    UnknownScreenError,
    load_bundled_signatures,
    recognize,
)

from tests.screen_support import CAPTURE_NAMES, load_capture_screen, make_screen

_CAPTURES_DIR = Path(__file__).parents[1] / "captures"
_WINDOWS_WS3270 = r"D:\tools\wc3270\ws3270.exe"

# Recognized (signature) name -> capture it comes from.
_SIGNATURE_CAPTURE: dict[str, str] = {
    "tk5-logo": "tk5-logo",
    "tk5-logon": "tk5-logon",
    "tso-input-not-recognized": "tso-input-not-recognized",
    "tso-password-prompt": "tso-password-prompt",
    "ispf-primary-menu": "ispf-primary-menu",
    "tso-ready": "tso-ready",
    "tso-pause": "tso-pause-2",
}
_CAPTURE_SIGNATURE = {v: k for k, v in _SIGNATURE_CAPTURE.items()}

_SIGNATURES = load_bundled_signatures()
_CAPTURE_CACHE: dict[str, Screen] = {n: load_capture_screen(n) for n in CAPTURE_NAMES}


# --------------------------------------------------------------------------
# Screen copies and capture access
# --------------------------------------------------------------------------

def copy_screen(screen: Screen) -> Screen:
    """Return an independent copy (tokens are frozen and shared)."""
    return Screen(
        rows=screen.rows,
        columns=screen.columns,
        cursor_row=screen.cursor_row,
        cursor_col=screen.cursor_col,
        cell_grid=[list(row) for row in screen.cell_grid],
        sa_tokens=[list(row) for row in screen.sa_tokens],
    )


def capture(name: str) -> Screen:
    """A fresh copy of the cached capture ``name`` (capture or signature name)."""
    name = _SIGNATURE_CAPTURE.get(name, name)
    return copy_screen(_CAPTURE_CACHE[name])


def _recognized(screen: Screen) -> str | None:
    try:
        return recognize(screen, _SIGNATURES)
    except UnknownScreenError:
        return None


# --------------------------------------------------------------------------
# Fake Clock
# --------------------------------------------------------------------------

class FakeClock:
    """Time starts at 0.0; ``sleep(s)`` adds exactly ``s`` and returns at once."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("sleep seconds must not be negative")
        self.sleeps.append(seconds)
        self.now += seconds


# --------------------------------------------------------------------------
# Typing into a screen
# --------------------------------------------------------------------------

def _type_into(
    screen: Screen,
    text: str,
    *,
    mdt: bool,
    cursor: str,
    truncate: bool = False,
) -> Screen:
    """Copy of ``screen`` with ``text`` written from the cursor into its field."""
    total = screen.rows * screen.columns
    f = screen.find_field(screen.cursor_row, screen.cursor_col)
    if f is None:
        raise ValueError("screen has no field at the cursor")
    ls = f.start_row * screen.columns + f.start_col
    lc = screen.cursor_row * screen.columns + screen.cursor_col
    offset = (lc - ls) % total
    if offset == 0 or offset > f.byte_length:
        raise ValueError("cursor is not on a data cell of its field")
    remaining = f.byte_length - offset + 1
    if len(text) > remaining:
        if not truncate:
            raise ValueError("text does not fit in the cursor field")
        text = text[:remaining]
    out = copy_screen(screen)
    for i, ch in enumerate(text):
        if ord(ch) > 0xFF:
            raise ValueError("text must be at most U+00FF per character")
        r, c = divmod((lc + i) % total, screen.columns)
        out.cell_grid[r][c] = ord(ch)
    sf = out.cell_grid[f.start_row][f.start_col]
    assert isinstance(sf, SFToken)
    c0 = (sf.c0 | 0x01) if mdt else (sf.c0 & ~0x01)
    out.cell_grid[f.start_row][f.start_col] = SFToken(c0)

    if cursor == "inside":
        new = min(offset + len(text), f.byte_length)
        r, c = divmod((ls + new) % total, screen.columns)
    elif cursor == "outside":
        other = next(
            (g for g in screen.fields if (g.start_row, g.start_col) != (f.start_row, f.start_col)
             and g.byte_length > 0),
            None,
        )
        if other is None:
            raise ValueError("screen has no second field for an outside cursor")
        r, c = divmod((other.start_row * screen.columns + other.start_col + 1) % total,
                      screen.columns)
    else:
        raise ValueError("cursor must be 'inside' or 'outside'")
    out.cursor_row, out.cursor_col = r, c
    return out


def typed_screen(
    screen: Screen,
    text: str,
    *,
    mdt: bool = False,
    cursor: str = "inside",
) -> Screen:
    """The screen after a user typed ``text`` into the cursor field.

    ``mdt`` sets or clears the modified bit of the field attribute. ``cursor``
    is ``"inside"`` (just after the text, clamped to the field) or ``"outside"``
    (first data cell of another field).
    """
    return _type_into(screen, text, mdt=mdt, cursor=cursor)


# --------------------------------------------------------------------------
# Scripted Session
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ScriptedState:
    screen: Screen
    stale_reads: int = 0
    repaints: tuple[Screen, ...] = ()

    def __post_init__(self) -> None:
        if type(self.stale_reads) is not int or not 0 <= self.stale_reads <= 10:
            raise ValueError("stale_reads must be an integer from 0 to 10")
        object.__setattr__(self, "repaints", tuple(self.repaints))


class ScriptedSession:
    """Implements the Session protocol over an ordered list of states."""

    def __init__(self, states: Sequence[ScriptedState | Screen], *, echo_typing: bool = False):
        items = [s if isinstance(s, ScriptedState) else ScriptedState(s) for s in states]
        if not items:
            raise ValueError("at least one state is required")
        self._states = items
        self._echo = echo_typing
        self._index = 0
        self._queue: list[Screen] = []
        self._current = copy_screen(items[0].screen)
        self.calls: list[tuple] = []

    # -- internals --
    def _advance(self) -> None:
        if self._index + 1 >= len(self._states):
            return
        previous = self._current
        self._index += 1
        state = self._states[self._index]
        self._queue = (
            [copy_screen(previous) for _ in range(state.stale_reads)]
            + [copy_screen(r) for r in state.repaints]
        )
        self._current = copy_screen(state.screen)

    # -- Session protocol --
    def read_screen(self) -> Screen:
        self.calls.append(("read",))
        if self._queue:
            return self._queue.pop(0)
        return copy_screen(self._current)

    def string(self, text: str) -> None:
        self.calls.append(("string", text))
        if self._echo:
            try:
                self._current = _type_into(
                    self._current, text, mdt=True, cursor="inside", truncate=True
                )
            except ValueError:
                pass  # a host would reject typing here; the screen stays as is

    def enter(self) -> None:
        self.calls.append(("enter",))
        self._advance()

    def clear(self) -> None:
        self.calls.append(("clear",))
        self._advance()

    def pf(self, n: int) -> None:
        self.calls.append(("pf", n))
        self._advance()

    def pa(self, n: int) -> None:
        self.calls.append(("pa", n))
        self._advance()

    def close(self) -> None:
        self.calls.append(("close",))


# --------------------------------------------------------------------------
# Synthetic screens
# --------------------------------------------------------------------------

def _write_row(screen: Screen, row: int, col: int, text: str) -> None:
    for i, ch in enumerate(text):
        screen.cell_grid[row][col + i] = ord(ch)


def _clear_row(screen: Screen, row: int) -> None:
    for c in range(screen.columns):
        if not isinstance(screen.cell_grid[row][c], SFToken):
            screen.cell_grid[row][c] = 0x00


def pause_variant(i: int) -> Screen:
    """The i-th distinct ``tso-pause`` screen (varying text and ``***`` row)."""
    if i < 0:
        raise ValueError("i must not be negative")
    return copy_screen(_pause_prototype(i))


@lru_cache(maxsize=256)
def _pause_prototype(i: int) -> Screen:
    s = capture("tso-pause-2")
    for row in (7, 11):
        _clear_row(s, row)
    _write_row(s, 7, 1, f"VARIANT {i:06d} DOES IT WITH BUGS")
    star_row = 10 + (i % 3)
    _clear_row(s, 11)
    _write_row(s, star_row, 1, "***")
    s.cursor_row, s.cursor_col = star_row, 5
    return s


_REPAINT_CHARS = (" ", "#", "$", "%", "&")
_MAX_REPAINT_CELLS = 6


def _find_repaint_cells() -> dict[str, list[tuple[int, int, tuple[str, ...]]]]:
    found: dict[str, list[tuple[int, int, tuple[str, ...]]]] = {}
    for sig_name, cap_name in _SIGNATURE_CAPTURE.items():
        base = _CAPTURE_CACHE[cap_name]
        cells: list[tuple[int, int, tuple[str, ...]]] = []
        for r in range(base.rows):
            for c in range(base.columns):
                if len(cells) >= _MAX_REPAINT_CELLS:
                    break
                if isinstance(base.cell_grid[r][c], SFToken):
                    continue
                good: list[str] = []
                for ch in _REPAINT_CHARS:
                    if base.cell_grid[r][c] == ord(ch):
                        continue
                    trial = copy_screen(base)
                    trial.cell_grid[r][c] = ord(ch)
                    if _recognized(trial) == sig_name:
                        good.append(ch)
                if good:
                    cells.append((r, c, tuple(good)))
        found[sig_name] = cells
    return found


_REPAINT_CELLS = _find_repaint_cells()


def partial_repaint(name: str, i: int) -> Screen:
    """A screen that differs from the capture in a cell but still recognizes as ``name``.

    ``name`` is a signature name or a capture name. Different ``i`` give
    different screens (cycling through cells, then replacement characters).
    """
    sig_name = _CAPTURE_SIGNATURE.get(name, name)
    if not _REPAINT_CELLS.get(sig_name):
        raise LookupError(f"no partial repaint cell found for {name!r}")
    return copy_screen(_repaint_prototype(sig_name, i))


@lru_cache(maxsize=512)
def _repaint_prototype(sig_name: str, i: int) -> Screen:
    cells = _REPAINT_CELLS[sig_name]
    s = capture(sig_name)
    r, c, chars = cells[i % len(cells)]
    k = i // len(cells)
    s.cell_grid[r][c] = ord(chars[k % len(chars)])
    return s


def blank_screen() -> Screen:
    """A 24 by 80 screen of null cells, no fields. Always unknown."""
    return copy_screen(_blank_prototype())


@lru_cache(maxsize=1)
def _blank_prototype() -> Screen:
    return make_screen(24, 80)


def sentinel_password_screen(sentinel: str) -> Screen:
    """A copy of ``tso-password-prompt`` whose hidden field cells hold ``sentinel``.

    Models the residual password. Exists only in memory.
    """
    if not 1 <= len(sentinel) <= 8:
        raise ValueError("sentinel must be 1 to 8 characters")
    _assert_absent_from_captures(sentinel)
    s = capture("tso-password-prompt")
    hidden = next((f for f in s.fields if f.hidden), None)
    if hidden is None:
        raise AssertionError("tso-password-prompt has no hidden field")
    total = s.rows * s.columns
    start = hidden.start_row * s.columns + hidden.start_col + 1
    for i, ch in enumerate(sentinel):
        r, c = divmod((start + i) % total, s.columns)
        s.cell_grid[r][c] = ord(ch)
    return s


def _captures_text() -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(_CAPTURES_DIR.rglob("*")) if p.is_file()
    )


def _assert_absent_from_captures(sentinel: str) -> None:
    assert sentinel not in _captures_text(), "sentinel occurs in a file under captures/"


# Import-time checks of the helpers (cheap, and they fail loudly if a signature changes).
_assert_absent_from_captures("zq7!Kx")
for _i in range(12):
    assert _recognized(pause_variant(_i)) == "tso-pause", f"pause_variant({_i})"
assert _recognized(blank_screen()) is None, "blank_screen must be unknown"
del _i


# --------------------------------------------------------------------------
# Live host config (repeats the lookup of the existing integration tests)
# --------------------------------------------------------------------------

def live_connector_config():
    """ConnectorConfig for the live host; skips the test if no binary is found."""
    from greenscreen.connector.config import ConnectorConfig

    binary = os.environ.get("GS_S3270_BINARY")
    if not binary:
        for name in ("s3270", "ws3270"):
            binary = shutil.which(name)
            if binary:
                break
    if not binary and os.path.isfile(_WINDOWS_WS3270):
        binary = _WINDOWS_WS3270
    if not binary:
        pytest.skip(
            "no s3270/ws3270 binary: set GS_S3270_BINARY, add one to PATH, "
            f"or install {_WINDOWS_WS3270}"
        )
    return ConnectorConfig(
        binary=binary,
        host=os.environ.get("GS_HOST", "192.168.68.72"),
        port=int(os.environ.get("GS_PORT", "3270")),
    )
