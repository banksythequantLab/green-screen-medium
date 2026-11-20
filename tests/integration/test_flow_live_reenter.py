"""Live proof that a name the host rejects does not lock the account (more-flows task 9.4).

A test-only Flow (``tk5-probe-reenter``, built in memory from ``tk5-dataset-info``
with a relaxed ``dsname`` pattern) types a name the host rejects, so the host
shows ``REENTER -``. The Flow must stop with ``unexpected_screen`` at its
``extract`` step and release the account through PA1, Clear and LOGOFF. A second
call with ``tk5-time`` then takes the normal path (no IN USE recovery).

Skips when the host is unreachable or TK5_USERNAME / TK5_PASSWORD is unset.
A Cleanup_Helper logs the account off on every path. No credential and no
screen is printed or stored. Run with the Publisher stopped.
"""
from __future__ import annotations

import time
from dataclasses import replace

import pytest

from greenscreen.flow import load_bundled_flows

from tests.integration.live_flow_support import (
    CLEANUP_FAILED_MESSAGE,
    CleanupFailed,
    cleanup_logoff,
    leak_watch,
    live_setup,
    run_once,
)
from tests.integration.test_flow_live_recovery import in_use_iterations

BAD_NAMES = ["A..B", "1ABC"]


def probe_flow():
    """Return the test-only Flow; the bundled Flow is not changed."""
    base = load_bundled_flows()["tk5-dataset-info"]
    inputs = tuple(
        replace(spec, regex=".{1,44}") if spec.name == "dsname" else spec
        for spec in base.inputs
    )
    return replace(base, name="tk5-probe-reenter", inputs=inputs)


@pytest.mark.integration
@pytest.mark.parametrize("bad_name", BAD_NAMES)
def test_live_reenter_ends_logged_off(request, record_property, bad_name):
    user, password, config = live_setup(request)
    flows = load_bundled_flows()
    time_flow = flows["tk5-time"]
    probe = probe_flow()
    creds = {"userid": user, "password": password}

    started = time.perf_counter()
    in_flight: BaseException | None = None
    try:
        with leak_watch(password) as leak_check:
            r1, e1, final1 = run_once(config, probe, {**creds, "dsname": bad_name})
            assert r1 is None and e1 is not None, "the probe was expected to stop"
            record_property("probe_step_index", e1.step_index)
            assert e1.reason == "unexpected_screen"
            assert e1.kind == "extract"
            assert final1 == "tk5-logon"  # PA1, Clear, LOGOFF released the account

            # The next call proves the account was logged off: normal path only.
            r2, e2, final2 = run_once(config, time_flow, creds)
            leak_check([r for r in (r1, r2) if r is not None], [e for e in (e1, e2) if e])
        if e2 is not None:
            pytest.fail(
                f"second call stopped: reason={e2.reason} step={e2.step_index}",
                pytrace=False,
            )
        assert in_use_iterations(time_flow, r2) == 0
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
