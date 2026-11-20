"""Shared test support for the Command_Flows (spec more-flows, task 8.1).

Test support only. Nothing here starts a process, talks to a host or writes a
file. Screens come from ``tests.flow_support.capture`` (the files under
``captures/``) and ``pause_variant``; the user id and password are obviously
fake values, as in ``test_flow_logon_script.py``.

One-off Flow builder (decision of task 8.1): the five shipped Flow files are
produced by a throwaway script at ``%TEMP%\\gs-build\\build_flows.py``
(``BUILD_SCRIPT``), outside the workspace, and the directory is deleted in task
8.7. The script builds each ``Flow`` from the Logon_Prefix (``tk5-logon.steps``
as shipped, 15 steps), the Exit_Fragment (design section 6, "Exit and clear":
``type X``, ``key enter``, ``expect tso-ready``, ``key clear``, ``expect
tso-cleared``), the command block, the Closing_Tail, and the Finally_Block, and
writes ``Flow.to_yaml()`` to ``greenscreen/flow/flows/<name>.yaml``. Tests never
import it.
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from greenscreen.connector.models import Screen
from greenscreen.flow.model import Flow

from tests.flow_support import ScriptedSession, ScriptedState, capture, pause_variant

# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------

FLOWS_DIR = Path(__file__).parents[1] / "greenscreen" / "flow" / "flows"

BUILD_SCRIPT = Path(os.environ.get("TEMP", ".")) / "gs-build" / "build_flows.py"

# --------------------------------------------------------------------------
# Fake credentials (the values of the existing logon tests)
# --------------------------------------------------------------------------

USERID = "FAKEUSR"
SENTINEL = "SNTNL-01"  # fake secret, 8 characters
INPUTS = {"userid": USERID, "password": SENTINEL}

POLL = 0.25

# Keys of the normal logon from the logon screen: userid, Enter, password,
# Enter, then one Enter per ``***`` pause.
LOGON_PAUSES = 2


def logon_keys(pauses: int = LOGON_PAUSES) -> list[tuple]:
    return [
        ("string", USERID),
        ("enter",),
        ("string", SENTINEL),
        ("enter",),
        *[("enter",)] * pauses,
    ]


# --------------------------------------------------------------------------
# Loading a shipped Flow by path
# --------------------------------------------------------------------------

def flow_path(name: str) -> Path:
    return FLOWS_DIR / f"{name}.yaml"


def load_shipped_flow(name: str) -> Flow:
    """Read ``greenscreen/flow/flows/<name>.yaml`` directly; the manifest is not used."""
    return Flow.from_yaml(flow_path(name).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Scripted states
# --------------------------------------------------------------------------

def _state(screen: str | Screen, stale: int) -> ScriptedState:
    return ScriptedState(capture(screen) if isinstance(screen, str) else screen,
                         stale_reads=stale)


def logon_states(stale: int = 0, pauses: int = LOGON_PAUSES) -> list[ScriptedState]:
    """Logo-less normal logon: logon screen, password prompt, pauses, ISPF menu."""
    states = [
        ScriptedState(capture("tk5-logon")),
        _state("tso-password-prompt", stale),
    ]
    states += [_state(pause_variant(i), stale) for i in range(pauses)]
    states.append(_state("ispf-primary-menu", stale))
    return states


def exit_states(stale: int = 0) -> list[ScriptedState]:
    """``X`` and Enter reach ``READY``; Clear reaches the cleared screen."""
    return [_state("tso-ready", stale), _state("tso-cleared", stale)]


def command_states(
    screens: Sequence[str | Screen], stale: int = 0
) -> list[ScriptedState]:
    """One state per screen a command shows (capture or signature names, or Screens).

    The first screen is the one after the command's Enter; each further screen
    is the result of one more Enter.
    """
    return [_state(s, stale) for s in screens]


def closing_states(stale: int = 0) -> list[ScriptedState]:
    """Clear reaches the cleared screen; ``LOGOFF`` and Enter reach the logon screen."""
    return [_state("tso-cleared", stale), _state("tk5-logon", stale)]


def command_flow_states(
    screens: Sequence[str | Screen],
    stale: int = 0,
    pauses: int = LOGON_PAUSES,
) -> list[ScriptedState]:
    """The whole normal path of a Command_Flow, concatenated in order."""
    return (
        logon_states(stale, pauses)
        + exit_states(stale)
        + command_states(screens, stale)
        + closing_states(stale)
    )


def command_session(
    screens: Sequence[str | Screen],
    stale: int = 0,
    pauses: int = LOGON_PAUSES,
    *,
    clock=None,
) -> ScriptedSession:
    return ScriptedSession(
        command_flow_states(screens, stale, pauses), echo_typing=True, clock=clock
    )


# --------------------------------------------------------------------------
# Session call lists
# --------------------------------------------------------------------------

def keys(session: ScriptedSession) -> list[tuple]:
    """Every Session call except reads."""
    return [c for c in session.calls if c[0] != "read"]


def keys_after_menu(
    session: ScriptedSession, pauses: int = LOGON_PAUSES
) -> list[tuple]:
    """The non-read calls after the logon keys, i.e. from ``X`` on."""
    return keys(session)[len(logon_keys(pauses)):]


def typed_after_menu(session: ScriptedSession, pauses: int = LOGON_PAUSES) -> list[str]:
    """The strings typed after the menu, in order."""
    return [c[1] for c in keys_after_menu(session, pauses) if c[0] == "string"]
