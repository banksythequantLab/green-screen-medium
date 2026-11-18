"""Unit tests for the limiter, outcome types and error table of publisher.calls."""
from __future__ import annotations

import pytest

from greenscreen.flow.errors import REASON_CODES, FlowError
from greenscreen.flow.model import AuditRecord
from greenscreen.publisher.calls import (
    ERROR_CODES,
    FLOW_STOP_MEMBERS,
    HTTP_STATUS,
    LOG_ONLY_OUTCOMES,
    MESSAGES,
    PUBLISHER_CODES,
    RESPONSE_HEADERS,
    CallOutcome,
    Limiter,
    error_body,
    flow_error_data,
)

FLOW_STOP = [c for c in REASON_CODES if c != "input_invalid"]


def test_code_sets_have_expected_sizes() -> None:
    assert len(REASON_CODES) == 13
    assert len(PUBLISHER_CODES) == 9
    assert len(ERROR_CODES) == 22
    assert set(REASON_CODES).isdisjoint(PUBLISHER_CODES)


def test_tables_are_total_over_the_22_codes_and_nothing_else() -> None:
    assert set(HTTP_STATUS) == ERROR_CODES
    assert set(MESSAGES) == ERROR_CODES
    assert set(RESPONSE_HEADERS) <= ERROR_CODES


def test_cancelled_is_log_only() -> None:
    assert LOG_ONLY_OUTCOMES == frozenset({"cancelled"})
    assert LOG_ONLY_OUTCOMES.isdisjoint(ERROR_CODES)
    assert "cancelled" not in HTTP_STATUS
    assert "cancelled" not in MESSAGES
    assert not any("cancelled" in text.lower() for text in MESSAGES.values())


@pytest.mark.parametrize("code", sorted(ERROR_CODES))
def test_each_code_has_one_status_and_one_fixed_message(code: str) -> None:
    assert isinstance(HTTP_STATUS[code], int) and 400 <= HTTP_STATUS[code] <= 599
    assert isinstance(MESSAGES[code], str) and MESSAGES[code]
    body = error_body(code)
    assert body == {"error": {"code": code, "message": MESSAGES[code]}}


def test_status_values_of_the_design_table() -> None:
    assert HTTP_STATUS["unauthorized"] == 401
    assert HTTP_STATUS["request_invalid"] == 400
    assert HTTP_STATUS["request_too_large"] == 413
    assert HTTP_STATUS["unknown_flow"] == 404
    assert HTTP_STATUS["input_invalid"] == 422
    assert HTTP_STATUS["busy"] == 429
    assert HTTP_STATUS["shutting_down"] == 503
    assert HTTP_STATUS["host_unavailable"] == 502
    assert HTTP_STATUS["internal_error"] == 500
    assert {HTTP_STATUS[c] for c in ("call_timeout", "timeout", "run_timeout")} == {504}
    assert {HTTP_STATUS[c] for c in FLOW_STOP if c not in ("timeout", "run_timeout")} == {502}
    assert RESPONSE_HEADERS["busy"] == {"Retry-After": "1"}
    assert RESPONSE_HEADERS["unauthorized"] == {"WWW-Authenticate": "Bearer"}


def test_input_invalid_takes_only_message() -> None:
    body = error_body("input_invalid", message="input x violates type")
    assert body == {"error": {"code": "input_invalid", "message": "input x violates type"}}
    with pytest.raises(ValueError):
        error_body("input_invalid", step_index=1)


@pytest.mark.parametrize("code", FLOW_STOP)
def test_flow_stop_codes_take_exactly_the_flow_members(code: str) -> None:
    members = {
        "step_index": 3,
        "kind": "expect",
        "expected": ["a"],
        "summary": None,
        "audit": [],
    }
    assert tuple(members) == FLOW_STOP_MEMBERS
    body = error_body(code, **members)
    assert set(body["error"]) == {"code", "message", *FLOW_STOP_MEMBERS}
    assert body["error"]["message"] == MESSAGES[code]
    with pytest.raises(ValueError):
        error_body(code, message="override")
    with pytest.raises(ValueError):
        error_body(code, extra=1)


@pytest.mark.parametrize("code", sorted(set(PUBLISHER_CODES)))
def test_publisher_codes_take_no_members(code: str) -> None:
    for name in ("message", "step_index", "audit"):
        with pytest.raises(ValueError):
            error_body(code, **{name: 1})


def test_unknown_code_is_refused() -> None:
    for bad in ("cancelled", "ok", "nope"):
        with pytest.raises(ValueError):
            error_body(bad)


def test_limiter_accepts_exactly_its_limit() -> None:
    lim = Limiter(2)
    assert [lim.try_acquire() for _ in range(4)] == [True, True, False, False]
    assert lim.in_flight == 2
    lim.release()
    assert lim.try_acquire() is True
    lim.release()
    lim.release()
    assert lim.in_flight == 0
    with pytest.raises(RuntimeError):
        lim.release()


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "1"])
def test_limiter_rejects_bad_limit(bad) -> None:
    with pytest.raises(ValueError):
        Limiter(bad)


def test_outcome_accepts_ok_and_every_error_code() -> None:
    assert CallOutcome("ok", {}).code == "ok"
    for code in ERROR_CODES:
        assert CallOutcome(code, error_body(code)).code == code


@pytest.mark.parametrize("code", ["cancelled", "", "OK", "bogus"])
def test_outcome_refuses_other_codes(code: str) -> None:
    with pytest.raises(ValueError):
        CallOutcome(code, {})


def test_cancelled_outcome_is_refused_explicitly() -> None:
    with pytest.raises(ValueError):
        CallOutcome("cancelled", {})


def test_outcome_session_clean_is_false_or_none_only() -> None:
    assert CallOutcome("ok", {}).session_clean is None
    assert CallOutcome("unknown_screen", {}, session_clean=False).session_clean is False
    with pytest.raises(ValueError):
        CallOutcome("ok", {}, session_clean=True)


def test_flow_error_data_is_plain_data() -> None:
    rec = AuditRecord(0, "expect", "steps", None, "tk5-logon", "failed", 0.25)
    exc = FlowError(
        "unknown_screen",
        step_index=0,
        kind="expect",
        expected=("b", "a"),
        summary=None,
        audit=[rec],
    )
    data = flow_error_data(exc)
    assert data == {
        "reason": "unknown_screen",
        "step_index": 0,
        "kind": "expect",
        "expected": ["a", "b"],
        "summary": None,
        "audit": [
            {
                "step_index": 0,
                "kind": "expect",
                "phase": "steps",
                "iteration": None,
                "signature": "tk5-logon",
                "status": "failed",
                "duration_seconds": 0.25,
            }
        ],
    }
    body = error_body(data["reason"], **{k: v for k, v in data.items() if k != "reason"})
    assert set(body["error"]) == {"code", "message", *FLOW_STOP_MEMBERS}
