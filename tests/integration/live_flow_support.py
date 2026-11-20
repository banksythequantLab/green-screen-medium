"""Shared support for the more-flows live integration tests (task 9.4).

Holds the skip logic, the Cleanup_Helper that logs the account off from any
landing, the orphan helper, and the password leak check.

TK5_USERNAME and TK5_PASSWORD come from the environment only. Nothing here
prints, logs or stores a credential or a screen: failures raise exceptions whose
text holds no screen data, and the password verdicts are booleans.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager

import pytest

from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorError, ConnectorTimeoutError
from greenscreen.recognizer import load_bundled_signatures, recognize
from greenscreen.recognizer.errors import AmbiguousScreenError, UnknownScreenError

from tests.connector_support import LogCapture, collect_exception_text, collect_record_text
from tests.flow_support import live_connector_config
from tests.integration.test_flow_live_system_info import _password_forms

WAIT_SECONDS = 15.0
CLEANUP_DEADLINE = 60.0
CLEARED_STABLE_SECONDS = 0.5
LOGO_ENTER_SECONDS = 3.0
SAME_SCREEN_RETRY_SECONDS = 3.0
MAX_ACTIONS = 40

CLEANUP_FAILED_MESSAGE = (
    "cleanup could not log the account off; the account may still be locked. "
    "Recover manually: `LOGON <id> RECONNECT` at the IN USE screen, the password, "
    "Enter until the screen settles, then PA1 (at a REENTER prompt), Clear, "
    "`LOGOFF`, Enter."
)


class CleanupFailed(Exception):
    """The Cleanup_Helper or the orphan helper could not finish. Holds no data."""


def live_setup(request):
    """Skip unless credentials, host and a binary exist; return (user, password, config)."""
    missing = [
        name for name in ("TK5_USERNAME", "TK5_PASSWORD")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.skip("unset or empty environment variable(s): " + ", ".join(missing))
    request.getfixturevalue("host_reachable")  # skips when the host is unreachable
    config = live_connector_config()  # skips when no binary is found
    return os.environ["TK5_USERNAME"], os.environ["TK5_PASSWORD"], config


def _name_of(conn, signatures):
    """Return (signature name or None, screen)."""
    screen = conn.read_screen()
    try:
        return recognize(screen, signatures), screen
    except (UnknownScreenError, AmbiguousScreenError):
        return None, screen


def _wait_any(conn, texts, timeout: float = WAIT_SECONDS) -> str:
    end = time.monotonic() + timeout
    while True:
        for text in texts:
            try:
                conn.wait_for_text(text, timeout=0.3, poll_interval=0.1)
                return text
            except ConnectorTimeoutError:
                continue
        if time.monotonic() >= end:
            raise CleanupFailed("no expected screen text appeared")


def _open_to_logon(conn) -> None:
    try:
        conn.wait_for_text("Logon ===>", timeout=4)
    except ConnectorTimeoutError:
        conn.enter()
        conn.wait_for_text("Logon ===>", timeout=WAIT_SECONDS)


def cleanup_logoff(config, user: str, password: str) -> None:
    """Log the account off from any landing, including IN USE, READY, the cleared
    screen, a REENTER prompt and a pause. Uses signature names only."""
    signatures = load_bundled_signatures()
    try:
        with Connector(config) as conn:
            started = time.monotonic()
            changed_at = started
            previous = None
            acted_grid = None
            acted_at = 0.0
            logoff_sent = False
            actions = 0
            while True:
                now = time.monotonic()
                if now - started > CLEANUP_DEADLINE or actions > MAX_ACTIONS:
                    raise CleanupFailed("cleanup did not reach the logon screen")
                name, screen = _name_of(conn, signatures)
                grid = screen.text_grid
                if grid != previous:
                    previous = grid
                    changed_at = now
                held = now - changed_at
                if grid == acted_grid and now - acted_at < SAME_SCREEN_RETRY_SECONDS:
                    time.sleep(0.1)
                    continue
                if name == "tk5-logon":
                    if logoff_sent:
                        return
                    conn.string(user)
                    conn.enter()
                elif name == "tk5-logo":
                    if held < LOGO_ENTER_SECONDS:
                        time.sleep(0.1)
                        continue
                    conn.enter()
                elif name == "tso-input-not-recognized":
                    conn.clear()
                elif name in ("tso-password-prompt", "tso-reconnect-password-prompt"):
                    conn.string(password)
                    conn.enter()
                elif name == "tso-userid-in-use":
                    conn.string("LOGON " + user + " RECONNECT")
                    conn.enter()
                elif name in ("tso-reconnect-ok", "tso-pause"):
                    conn.enter()
                elif name == "ispf-primary-menu":
                    conn.string("X")
                    conn.enter()
                elif name == "tso-reenter":
                    conn.pa(1)
                elif name == "tso-ready":
                    conn.clear()
                elif name == "tso-cleared":
                    if held < CLEARED_STABLE_SECONDS:
                        time.sleep(0.1)
                        continue
                    conn.string("LOGOFF")
                    conn.enter()
                    logoff_sent = True
                else:
                    time.sleep(0.1)  # unknown or transient screen: keep waiting
                    continue
                actions += 1
                acted_grid = grid
                acted_at = time.monotonic()
    except CleanupFailed:
        raise
    except (ConnectorError, OSError, ValueError):  # the account may be locked
        raise CleanupFailed("cleanup step failed") from None


def orphan_session(config, user: str, password: str, state: str) -> None:
    """Log on, leave the session in ``state`` and drop the connection without LOGOFF.

    ``state`` is ``ready``, ``cleared`` or ``reenter``. The only commands typed
    are ``X``, Clear and ``LISTDS 'A..B'`` (read-only; the host rejects the name
    and waits at ``REENTER -``).
    """
    assert state in ("ready", "cleared", "reenter")
    try:
        with Connector(config) as conn:
            _open_to_logon(conn)
            conn.string(user)
            conn.enter()
            if _wait_any(conn, ["ENTER CURRENT PASSWORD FOR", "IN USE"]) == "IN USE":
                raise CleanupFailed("the account is already in use")
            conn.string(password)
            conn.enter()
            enters = 0
            while True:
                seen = _wait_any(conn, ["ISPF primary option menu", "***"])
                if seen == "ISPF primary option menu":
                    break
                if enters >= 5:
                    raise CleanupFailed("ISPF menu did not appear")
                conn.enter()
                enters += 1
            conn.string("X")
            conn.enter()
            conn.wait_for_text("READY", timeout=WAIT_SECONDS)
            if state in ("cleared", "reenter"):
                conn.clear()
                time.sleep(0.5)  # let the blank screen hold past the transient
            if state == "reenter":
                conn.string("LISTDS 'A..B'")
                conn.enter()
                conn.wait_for_text("REENTER -", timeout=WAIT_SECONDS)
        # leaving the block closes the connection without LOGOFF
    except CleanupFailed:
        raise
    except (ConnectorError, OSError, ValueError):
        raise CleanupFailed("could not create the orphan session") from None


def final_screen_name(conn) -> str | None:
    name, _ = _name_of(conn, load_bundled_signatures())
    return name


@contextmanager
def leak_watch(password: str):
    """Capture logs; ``check(results, errors)`` fails if any password form occurs."""
    capture = LogCapture(logging.DEBUG)
    root = logging.getLogger()
    connector_logger = logging.getLogger("greenscreen.connector")
    old_root, old_conn = root.level, connector_logger.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    connector_logger.setLevel(logging.DEBUG)

    def check(results, errors) -> None:
        haystack: list[str] = []
        for rec in capture.records:
            haystack.extend(collect_record_text(rec))
        for err in errors:
            haystack.extend(collect_exception_text(err))
            for audit in getattr(err, "audit", ()):
                haystack.append(repr(audit))
                haystack.append(str(audit))
            haystack.append(repr(getattr(err, "summary", "")))
        for res in results:
            haystack.append(repr(res))
            for audit in res.audit:
                haystack.append(repr(audit))
                haystack.append(str(audit))
        plain_forms, hex_forms = _password_forms(password)
        forms = list(plain_forms)
        if len(password) >= 4:
            forms += hex_forms
        for form_index, form in enumerate(forms):
            absent = all(form not in text for text in haystack)
            assert absent, f"password form {form_index} found in captured output"

    try:
        yield check
    finally:
        root.removeHandler(capture)
        root.setLevel(old_root)
        connector_logger.setLevel(old_conn)


def run_once(config, flow, inputs):
    """Run ``flow`` on a new Connector. Return (result, error, final screen name).

    ``error`` is a FlowError when the run stopped; any other exception propagates.
    """
    from greenscreen.flow import run_flow
    from greenscreen.flow.errors import FlowError

    with Connector(config) as conn:
        try:
            result = run_flow(flow, conn, inputs)
        except FlowError as exc:
            return None, exc, final_screen_name(conn)
        return result, None, final_screen_name(conn)
