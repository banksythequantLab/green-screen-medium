"""Live run of each more-flows Command_Flow through a Connector (more-flows task 9.4).

Written to be collected, not run in CI. Skips when the host is unreachable or
TK5_USERNAME / TK5_PASSWORD is unset. Every test logs the account off in a
``finally`` (Cleanup_Helper). Credentials come from the environment only; no
credential and no screen is printed, stored or put into a failure message.
Run with the Publisher stopped: one session per user id.
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
    run_once,
)

LIST_NAME = "SYS2.JCLLIB"
MISSING_NAME = "NO.SUCH.DSN"


def _lines(value) -> list[str]:
    return [line for line in str(value).splitlines() if line.strip()]


def _check_time(out, user):
    assert list(out) == ["TIME_TEXT"]
    assert out["TIME_TEXT"].strip().startswith("TIME-")


def _check_datasets(out, user):
    names = _lines(out["DATASETS"])
    assert names
    assert all(n.strip().casefold().startswith(user.casefold()) for n in names)


def _check_jobs(out, user):
    lines = _lines(out["JOBS"])
    assert any("EXECUTING" in line for line in lines)


def _check_info_found(out, user):
    assert out["FOUND"] == 1
    assert len(_lines(out["DETAILS"])) >= 3


def _check_info_missing(out, user):
    assert out["FOUND"] == 0
    assert str(out["DETAILS"]).strip() == ""


def _check_members(out, user):
    members = [m.strip() for m in _lines(out["MEMBERS"])]
    assert members[:3] == ["$$$INDEX", "$HISTORY", "ADDALIAS"]
    assert len(members) > 20
    assert len(set(members)) == len(members)


def _check_members_missing(out, user):
    assert str(out["MEMBERS"]).strip() == ""


CASES = [
    ("tk5-time", {}, _check_time),
    ("tk5-list-datasets", {}, _check_datasets),
    ("tk5-job-status", {}, _check_jobs),
    ("tk5-dataset-info", {"dsname": LIST_NAME}, _check_info_found),
    ("tk5-dataset-info", {"dsname": LIST_NAME.lower()}, _check_info_found),
    ("tk5-dataset-info", {"dsname": MISSING_NAME}, _check_info_missing),
    ("tk5-library-members", {"dsname": LIST_NAME}, _check_members),
    ("tk5-library-members", {"dsname": MISSING_NAME}, _check_members_missing),
]


@pytest.mark.integration
@pytest.mark.parametrize(
    "flow_name, extra, check",
    CASES,
    ids=[f"{n}-{i}" for i, (n, _, _) in enumerate(CASES)],
)
def test_live_command_flow(request, record_property, flow_name, extra, check):
    user, password, config = live_setup(request)
    flow = load_bundled_flows()[flow_name]
    inputs = {"userid": user, "password": password, **extra}

    started = time.perf_counter()
    in_flight: BaseException | None = None
    try:
        with leak_watch(password) as leak_check:
            result, error, final_name = run_once(config, flow, inputs)
            leak_check([result] if result is not None else [], [error] if error else [])
        if error is not None:
            pytest.fail(
                f"{flow_name} stopped: reason={error.reason} step={error.step_index}",
                pytrace=False,
            )
        assert final_name == "tk5-logon"
        check(result.outputs, user)
    except BaseException as exc:  # noqa: BLE001 - kept as __cause__ if cleanup fails
        in_flight = exc
        raise
    finally:
        record_property("duration_seconds", round(time.perf_counter() - started, 2))
        try:
            cleanup_logoff(config, user, password)
        except CleanupFailed:
            raise AssertionError(CLEANUP_FAILED_MESSAGE) from in_flight
