"""Unit tests for Input checking (flow-runtime Requirements 2.6 to 2.9).

Failing assertions are built as booleans so that a supplied value, secret or
not, can never be printed by pytest.
"""

from __future__ import annotations

import pytest

from greenscreen.flow import Flow, FlowInputError
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.flow.model import ExpectStep, InputSpec, KeyStep, TypeStep
from greenscreen.flow.runner import run_flow
from tests.flow_support import FakeClock, ScriptedSession, capture

SECRET_VALUE = "zq9Xs3cret"
PLAIN_VALUE = "kw7Plain"


def _flow() -> Flow:
    return Flow(
        name="inputs_demo",
        inputs=[
            InputSpec(name="user", type="str", required=True, max_length=10, regex="[a-zA-Z0-9]+"),
            InputSpec(name="pw", type="str", required=False, max_length=10, secret=True),
            InputSpec(name="count", type="int", required=False, max_length=3),
        ],
        steps=[
            ExpectStep(signatures=("tk5-logon",)),
            TypeStep(input="user"),
            KeyStep(key="enter"),
        ],
    )


def _exception_text(exc: BaseException) -> str:
    parts = [str(exc), repr(exc)]
    parts += [repr(a) for a in exc.args]
    parts += [repr(v) for v in vars(exc).values()]
    return "\n".join(parts)


def _run_expect_error(supplied: dict) -> tuple[FlowInputError, ScriptedSession]:
    session = ScriptedSession([capture("tk5-logon")])
    try:
        run_flow(_flow(), session, supplied, clock=FakeClock())
    except FlowInputError as exc:
        return exc, session
    raise AssertionError("FlowInputError was not raised")


# (case id, supplied mapping, offending Input name, rule, values that must not leak)
CASES = [
    ("missing_required", {"pw": SECRET_VALUE}, "user", "required", [SECRET_VALUE]),
    ("wrong_type_int_for_str", {"user": 12345678}, "user", "type", ["12345678"]),
    ("wrong_type_str_for_int", {"user": "ok", "count": "987"}, "count", "type", ["987"]),
    ("bool_for_int", {"user": "ok", "count": True}, "count", "type", []),
    ("wrong_type_secret", {"user": "ok", "pw": 424242}, "pw", "type", ["424242"]),
    ("too_long_str", {"user": PLAIN_VALUE + "abcdef"}, "user", "max_length", [PLAIN_VALUE + "abcdef"]),
    ("too_long_secret", {"user": "ok", "pw": SECRET_VALUE + "xyz"}, "pw", "max_length", [SECRET_VALUE + "xyz"]),
    ("too_long_after_str_of_int", {"user": "ok", "count": 123456}, "count", "max_length", ["123456"]),
    ("regex_mismatch", {"user": "bad-kw7"}, "user", "regex", ["bad-kw7"]),
    ("non_printable_ascii", {"user": "ab\x01cd"}, "user", "printable_ascii", ["ab\x01cd"]),
    ("non_ascii_char", {"user": "ab\u00e9cd"}, "user", "printable_ascii", ["ab\u00e9cd"]),
    ("non_printable_secret", {"user": "ok", "pw": SECRET_VALUE[:9] + "\n"}, "pw", "printable_ascii", [SECRET_VALUE[:9]]),
    ("undeclared_name", {"user": "ok", "extra": PLAIN_VALUE}, "extra", "undeclared", [PLAIN_VALUE]),
]


@pytest.mark.parametrize(
    "supplied,name,rule,secrets",
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_input_rule_violation(supplied, name, rule, secrets):
    exc, session = _run_expect_error(supplied)

    assert (exc.reason == "input_invalid") is True
    assert (f"input {name} violates {rule}" in str(exc)) is True
    assert (exc.step_index is None and exc.summary is None and exc.audit == ()) is True
    assert (session.calls == []) is True

    text = _exception_text(exc)
    leaked = [s for s in secrets if s in text]
    assert (leaked == []) is True
    # No supplied string value (secret or not) appears anywhere.
    for value in supplied.values():
        if isinstance(value, str):
            assert (value in text) is False


@pytest.mark.parametrize(
    "supplied,name,rule,secrets",
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_prepare_inputs_raises_same_error(supplied, name, rule, secrets):
    with pytest.raises(FlowInputError) as info:
        prepare_inputs(_flow(), supplied)
    assert (f"input {name} violates {rule}" in str(info.value)) is True


def test_valid_inputs_pass_and_hold_no_secret_value():
    prepared = prepare_inputs(
        _flow(), {"user": PLAIN_VALUE, "pw": SECRET_VALUE, "count": 42}
    )
    assert (prepared.values == {"user": PLAIN_VALUE, "count": "42"}) is True
    assert (prepared.supplied_secrets == frozenset({"pw"})) is True
    assert (SECRET_VALUE in repr(prepared)) is False
