"""session_clean for every stop that skips the finally steps (logon-recovery Requirement 12)."""
from __future__ import annotations

import asyncio
import logging

import pytest

from greenscreen.flow.bundled import load_bundled_flows
from greenscreen.publisher.calls import ERROR_CODES, _FINALLY_SKIPPED_STOPS, _session_clean

from tests.flow_support import FakeClock, ScriptedState, capture  # noqa: F401
from tests.publisher_support import FakeHost
from tests.screen_support import second_in_use_screen
from tests.unit.test_publisher_calls import call, make, only_record

FIVE = frozenset(
    {"unknown_screen", "ambiguous_screen", "timeout", "run_timeout", "session_error"}
)


def test_derived_set_equals_the_five_reasons() -> None:
    extra = sorted(_FINALLY_SKIPPED_STOPS - FIVE)
    missing = sorted(FIVE - _FINALLY_SKIPPED_STOPS)
    assert not extra and not missing, f"unexpected {extra}, missing {missing}"


@pytest.mark.parametrize("code", sorted(ERROR_CODES | {"ok"}))
def test_session_clean_table(code: str) -> None:
    expected = False if code in FIVE | {"call_timeout"} else None
    assert _session_clean(code, None) is expected
    assert _session_clean(code, "cancel") is False
    assert _session_clean(code, "shutdown") is False


@pytest.fixture(autouse=True)
def _info_log(caplog):
    caplog.set_level(logging.INFO, logger="greenscreen.publisher")


def _logon():
    return load_bundled_flows()["tk5-logon"]


def _run(states, caplog):
    host = FakeHost(states)
    svc = make(host, {"tk5-logon": _logon()})
    out = asyncio.run(call(svc, "tk5-logon", {"userid": "FAKEUSR", "password": "SNTNL-01"}))
    return out, only_record(caplog)


def test_failed_recovery_is_marked_unknown_screen(caplog) -> None:
    out, rec = _run(
        [capture("tk5-logon"), capture("tso-userid-in-use"), second_in_use_screen()], caplog
    )
    assert out.code == "unknown_screen" and out.session_clean is False
    assert rec["outcome"] == "unknown_screen" and rec["session_clean"] is False


def test_recovery_screen_that_never_arrives_is_marked_timeout(caplog) -> None:
    out, rec = _run([capture("tk5-logon"), capture("tso-userid-in-use")], caplog)
    assert out.code == "timeout" and out.session_clean is False
    assert rec["outcome"] == "timeout" and rec["session_clean"] is False


def test_in_use_twice_is_loop_limit_without_a_claim(caplog) -> None:
    out, rec = _run(
        [capture("tk5-logon"), capture("tso-userid-in-use"), capture("tso-userid-in-use")],
        caplog,
    )
    assert out.code == "loop_limit" and out.session_clean is None
    assert rec["outcome"] == "loop_limit" and "session_clean" not in rec
