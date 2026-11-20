"""Live proof of the Logon_Cleanup of ``tk5-time`` (more-flows task 9.4).

For each orphan state (``ready``, ``cleared``, ``reenter``) the session is left
logged on by dropping the connection, then ``tk5-time`` runs twice. The first
call reconnects and releases the account, so it ends with ``unexpected_screen``
at step index 26 (expected ``ispf-primary-menu``). The second call succeeds.

Skips when the host is unreachable or TK5_USERNAME / TK5_PASSWORD is unset.
A Cleanup_Helper logs the account off on every path. No credential and no
screen is printed or stored. Run with the Publisher stopped.
"""
from __future__ import annotations

import time

import pytest

from greenscreen.flow import load_bundled_flows

from tests.integration.live_flow_support import (
    CLEANUP_FAILED_MESSAGE,
    CleanupFailed,
    cleanup_logoff,
    leak_watch,
    live_setup,
    orphan_session,
    run_once,
)

RELEASE_STEP_INDEX = 26


@pytest.mark.integration
@pytest.mark.parametrize("state", ["ready", "cleared", "reenter"])
def test_live_cleanup_releases_orphan(request, record_property, state):
    user, password, config = live_setup(request)
    flow = load_bundled_flows()["tk5-time"]
    creds = {"userid": user, "password": password}

    started = time.perf_counter()
    in_flight: BaseException | None = None
    try:
        orphan_session(config, user, password, state)
        with leak_watch(password) as leak_check:
            r1, e1, final1 = run_once(config, flow, creds)
            assert r1 is None and e1 is not None, "the first call was expected to stop"
            record_property("first_call_step_index", e1.step_index)
            assert e1.reason == "unexpected_screen"
            assert e1.step_index == RELEASE_STEP_INDEX
            assert tuple(e1.expected) == ("ispf-primary-menu",)
            assert final1 == "tk5-logon"  # the released session ended at the logon screen

            r2, e2, final2 = run_once(config, flow, creds)
            leak_check([r for r in (r1, r2) if r is not None], [e for e in (e1, e2) if e])
        if e2 is not None:
            pytest.fail(
                f"second call stopped: reason={e2.reason} step={e2.step_index}",
                pytrace=False,
            )
        assert r2.outputs["TIME_TEXT"].strip().startswith("TIME-")
        assert final2 == "tk5-logon"
    except BaseException as exc:  # noqa: BLE001 - kept as __cause__ if cleanup fails
        in_flight = exc
        raise
    finally:
        record_property("duration_seconds", round(time.perf_counter() - started, 2))
        try:
            cleanup_logoff(config, user, password)
        except CleanupFailed:
            raise AssertionError(CLEANUP_FAILED_MESSAGE) from in_flight
