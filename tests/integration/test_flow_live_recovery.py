"""Live proof of logon recovery from ``USERID ... IN USE`` (logon-recovery Requirement 8).

Steps: (a) run ``tk5-logon``, (b) drop the connection without LOGOFF, (c) run
``tk5-system-info`` on a new connection (must take the recovery path), (d) run
it once more (must take the normal path). A Cleanup_Helper logs the account off
on every exit path.

TK5_USERNAME and TK5_PASSWORD come from the environment only. No credential is
written in this file, no screen is captured and no file is written. Verdicts on
the password are booleans, so a failure message never contains it.
"""
from __future__ import annotations

import logging
import os
import time

import pytest

from greenscreen.connector.connector import Connector
from greenscreen.connector.exceptions import ConnectorError, ConnectorTimeoutError
from greenscreen.flow import load_bundled_flows, run_flow
from greenscreen.flow.errors import FlowError
from greenscreen.flow.model import HandleStep, plan
from greenscreen.recognizer import load_bundled_signatures, recognize

from tests.connector_support import LogCapture, collect_exception_text, collect_record_text
from tests.flow_support import live_connector_config
from tests.integration.test_flow_live_system_info import _password_forms

OUTPUT_ORDER = ["USERID", "SYSTEMID", "RELEASE", "TERMINAL"]
WAIT_SECONDS = 15.0
MAX_MENU_ENTERS = 5

CLEANUP_FAILED_MESSAGE = (
    "cleanup could not log the account off; the account may still be locked. "
    "Recover manually by typing `LOGON <id> RECONNECT` at the IN USE screen."
)


class CleanupFailed(Exception):
    """The Cleanup_Helper could not complete a logoff. Holds no credential."""


def in_use_iterations(flow, result) -> int:
    """Count ``ok`` runs of the in-use Handle_Step body (last child = its Key_Step)."""
    main, _ = plan(flow)
    handle = next(
        item for item in main
        if isinstance(item.step, HandleStep) and item.step.signature == "tso-userid-in-use"
    )
    last_child = handle.children[-1].index
    return sum(
        1 for rec in result.audit
        if rec.step_index == last_child and rec.status == "ok"
    )


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


def cleanup_logoff(config, user: str, password: str) -> None:
    """Log the account off with raw Connector calls and text waits only."""
    try:
        with Connector(config) as conn:
            # OPEN
            try:
                conn.wait_for_text("Logon ===>", timeout=4)
            except ConnectorTimeoutError:
                conn.enter()
                conn.wait_for_text("Logon ===>", timeout=WAIT_SECONDS)
            # USERID
            conn.string(user)
            conn.enter()
            seen = _wait_any(conn, ["ENTER CURRENT PASSWORD FOR", "IN USE"])
            if seen == "IN USE":
                # IN_USE
                conn.string("LOGON " + user + " RECONNECT")
                conn.enter()
                conn.wait_for_text("ENTER CURRENT PASSWORD FOR", timeout=WAIT_SECONDS)
            # PASSWORD
            conn.string(password)
            conn.enter()
            # ADVANCE
            enters = 0
            while True:
                seen = _wait_any(
                    conn, ["ISPF primary option menu", "READY", "IKT00300I", "***"]
                )
                if seen in ("ISPF primary option menu", "READY"):
                    break
                if enters >= MAX_MENU_ENTERS:
                    raise CleanupFailed("ISPF menu did not appear")
                conn.enter()
                enters += 1
            if seen == "ISPF primary option menu":
                # MENU
                conn.string("X")
                conn.enter()
                conn.wait_for_text("READY", timeout=WAIT_SECONDS)
            # READY
            conn.string("LOGOFF")
            conn.enter()
            conn.wait_for_text("Logon ===>", timeout=WAIT_SECONDS)
    except CleanupFailed:
        raise
    except (ConnectorError, OSError, ValueError):  # the account may be locked
        raise CleanupFailed("cleanup step failed") from None


def _assert_outputs(result, user: str, final_name) -> None:
    assert list(result.outputs) == OUTPUT_ORDER
    assert result.outputs["USERID"].casefold() == user.casefold()
    assert result.outputs["SYSTEMID"].strip() != ""
    assert result.outputs["RELEASE"].strip() != ""
    assert final_name == "tk5-logon"


@pytest.mark.integration
def test_live_recovery_from_user_in_use(request, record_property):
    missing = [
        name for name in ("TK5_USERNAME", "TK5_PASSWORD")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.skip("unset or empty environment variable(s): " + ", ".join(missing))
    user = os.environ["TK5_USERNAME"]
    password = os.environ["TK5_PASSWORD"]
    creds = {"userid": user, "password": password}

    request.getfixturevalue("host_reachable")  # skips when the host is unreachable
    config = live_connector_config()  # skips when no binary is found
    flows = load_bundled_flows()
    logon_flow = flows["tk5-logon"]
    info_flow = flows["tk5-system-info"]
    signatures = load_bundled_signatures()

    capture = LogCapture(logging.DEBUG)
    root = logging.getLogger()
    connector_logger = logging.getLogger("greenscreen.connector")
    old_root_level = root.level
    old_conn_level = connector_logger.level
    root.addHandler(capture)
    root.setLevel(logging.DEBUG)
    connector_logger.setLevel(logging.DEBUG)

    results: list = []
    errors: list[BaseException] = []

    def leak_check() -> None:
        haystack: list[str] = []
        for rec in capture.records:
            haystack.extend(collect_record_text(rec))
        for err in errors:
            haystack.extend(collect_exception_text(err))
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

    def run(flow):
        with Connector(config) as conn:
            try:
                res = run_flow(flow, conn, creds)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)
                leak_check()
                if isinstance(exc, FlowError):
                    pytest.fail(
                        f"flow stopped: reason={exc.reason} step={exc.step_index}",
                        pytrace=False,
                    )
                raise
            results.append(res)
            return res, recognize(conn.read_screen(), signatures)

    started = time.perf_counter()
    in_flight: BaseException | None = None
    try:
        try:
            # (a) log on; (b) leaving the block drops the connection, no LOGOFF
            with Connector(config) as conn:
                try:
                    res = run_flow(logon_flow, conn, creds)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)
                    leak_check()
                    if isinstance(exc, FlowError):
                        pytest.fail(
                            f"logon stopped: reason={exc.reason} step={exc.step_index}",
                            pytrace=False,
                        )
                    raise
                results.append(res)

            # (c) must take the recovery path
            r1, final1 = run(info_flow)
            n1 = in_use_iterations(info_flow, r1)
            if n1 == 0:
                leak_check()
                pytest.skip("lock was not reproduced; recovery path was not exercised")
            _assert_outputs(r1, user, final1)
            assert n1 >= 1

            # (d) proves (c) logged off: the normal path again
            r2, final2 = run(info_flow)
            _assert_outputs(r2, user, final2)
            assert in_use_iterations(info_flow, r2) == 0

            leak_check()
        except BaseException as exc:  # noqa: BLE001 - keep for __cause__ if cleanup fails
            in_flight = exc
            raise
        finally:
            root.removeHandler(capture)
            root.setLevel(old_root_level)
            connector_logger.setLevel(old_conn_level)
    finally:
        record_property("duration_seconds", round(time.perf_counter() - started, 2))
        try:
            cleanup_logoff(config, user, password)
        except CleanupFailed:
            raise AssertionError(CLEANUP_FAILED_MESSAGE) from in_flight
