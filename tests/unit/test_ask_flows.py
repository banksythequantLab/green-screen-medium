"""Which Flows Ask may offer, and the startup rules that decide it (spec ask, task 2.10).

Requirement 1, criteria 10, 14 and 15, and the eligibility rule of Requirement 16, criterion 4:
a Flow is offerable when its Tool_Worst_Case (registry deadline plus 10) plus twice
``GS_ASK_MODEL_TIMEOUT_SECONDS`` is at most ``GS_ASK_TIMEOUT_SECONDS``.

The bundled Flows are used through ``prepare``. Flow names are limited to ``[a-z0-9_-]{1,64}``
by the Flow loader, which is narrower than the Ask name rule, so ``name_not_allowed`` cannot be
reached through a real Flow; it is tested on ``plan_ask`` with a stand-in registry. No live host,
no model, no network. Keys and the bound value are generated at run time.
"""
from __future__ import annotations

import dataclasses
import types
import uuid

import pytest

pytest.importorskip("fastapi")

from greenscreen.publisher.app import prepare  # noqa: E402
from greenscreen.publisher.ask.service import TOOL_TAIL, plan_ask  # noqa: E402
from greenscreen.publisher.config import (  # noqa: E402
    AskSettings,
    StartupError,
    load_settings,
)
from tests.ask_support import BOUND_PASSWORD, no_network  # noqa: E402,F401  (autouse)

SYSINFO = "tk5-system-info"
LOGOFF = "tk5-logoff"
LOGON = "tk5-logon"
BIND = "GS_BIND_" + "TK5_SYSTEM_INFO__PASSWORD"


def _env(**extra: str) -> dict[str, str]:
    env = {
        "GS_S3270_BINARY": "s3270",
        "GS_HOST": "host.invalid",
        "GS_API_KEY": uuid.uuid4().hex,
        "GS_PUBLISH_FLOWS": SYSINFO,
        BIND: BOUND_PASSWORD,
        "GS_ENABLE_ASK": "true",
        "GS_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "GS_LLM_MODEL": "fake-model",
        "GS_CALL_TIMEOUT": "30",
    }
    env.update(extra)
    return env


def _error(env: dict[str, str]) -> str:
    with pytest.raises(StartupError) as info:
        prepare(env)
    message = str(info.value)
    assert BOUND_PASSWORD not in message and env["GS_API_KEY"] not in message
    return message


# --------------------------------------------------------------------------
# GS_ASK_FLOWS list rules (parser)
# --------------------------------------------------------------------------

def test_ask_flows_empty_item_is_named_without_a_value() -> None:
    with pytest.raises(StartupError) as info:
        load_settings(_env(GS_ASK_FLOWS=f"{SYSINFO},,{LOGOFF}"))
    assert str(info.value) == "GS_ASK_FLOWS: empty_item"


def test_ask_flows_trailing_comma_is_an_empty_item() -> None:
    with pytest.raises(StartupError) as info:
        load_settings(_env(GS_ASK_FLOWS=f"{SYSINFO},"))
    assert str(info.value) == "GS_ASK_FLOWS: empty_item"


def test_ask_flows_duplicate_name_names_the_flow() -> None:
    with pytest.raises(StartupError) as info:
        load_settings(_env(GS_ASK_FLOWS=f"{SYSINFO}, {SYSINFO}"))
    assert str(info.value) == f"GS_ASK_FLOWS: duplicate_name ({SYSINFO})"


def test_ask_flows_items_are_trimmed_and_unset_or_empty_means_all() -> None:
    settings = load_settings(_env(GS_ASK_FLOWS=f" {SYSINFO} , {LOGOFF}"))
    assert settings.ask is not None and settings.ask.flows == (SYSINFO, LOGOFF)
    assert load_settings(_env()).ask.flows is None
    assert load_settings(_env(GS_ASK_FLOWS="")).ask.flows is None


def test_empty_item_wins_over_duplicate_name() -> None:
    with pytest.raises(StartupError) as info:
        load_settings(_env(GS_ASK_FLOWS=f"{SYSINFO},{SYSINFO},"))
    assert str(info.value) == "GS_ASK_FLOWS: empty_item"


# --------------------------------------------------------------------------
# GS_ASK_FLOWS against the registry (prepare)
# --------------------------------------------------------------------------

def test_ask_flows_names_a_loaded_but_unpublished_flow_as_not_published() -> None:
    assert _error(_env(GS_ASK_FLOWS=LOGON)) == f"GS_ASK_FLOWS: not_published ({LOGON})"


def test_ask_flows_names_an_unknown_flow_as_not_published() -> None:
    assert _error(_env(GS_ASK_FLOWS="nope")) == "GS_ASK_FLOWS: not_published (nope)"


def test_ask_flows_names_a_flow_with_a_secret_input() -> None:
    env = _env(GS_PUBLISH_FLOWS=f"{SYSINFO},{LOGON}", GS_ASK_FLOWS=LOGON)
    assert _error(env) == f"GS_ASK_FLOWS: has_secret_input ({LOGON})"


def test_ask_flows_names_a_flow_whose_call_is_too_long() -> None:
    env = _env(GS_CALL_TIMEOUT="31", GS_ASK_FLOWS=SYSINFO)
    assert _error(env) == f"GS_ASK_FLOWS: call_too_long ({SYSINFO}: lower GS_CALL_TIMEOUT)"


def test_ask_flows_first_problem_in_list_order_wins() -> None:
    env = _env(GS_PUBLISH_FLOWS=f"{SYSINFO},{LOGON}", GS_ASK_FLOWS=f"{LOGON},nope")
    assert _error(env) == f"GS_ASK_FLOWS: has_secret_input ({LOGON})"
    env = _env(GS_PUBLISH_FLOWS=f"{SYSINFO},{LOGON}", GS_ASK_FLOWS=f"nope,{LOGON}")
    assert _error(env) == "GS_ASK_FLOWS: not_published (nope)"


def test_ask_flows_limits_the_offered_flows_to_exactly_the_named_ones() -> None:
    env = _env(GS_PUBLISH_FLOWS=f"{SYSINFO},{LOGOFF}", GS_ASK_FLOWS=LOGOFF)
    assert prepare(env).ask.eligible == frozenset({LOGOFF})
    env = _env(GS_PUBLISH_FLOWS=f"{SYSINFO},{LOGOFF}")
    assert prepare(env).ask.eligible == frozenset({SYSINFO, LOGOFF})


def test_without_ask_flows_a_secret_input_flow_is_skipped_silently() -> None:
    env = _env(GS_PUBLISH_FLOWS=f"{SYSINFO},{LOGON}")
    assert prepare(env).ask.eligible == frozenset({SYSINFO})


def _stand_in(deadline: float, secret: bool = False) -> types.SimpleNamespace:
    spec = types.SimpleNamespace(secret=secret)
    return types.SimpleNamespace(decl=types.SimpleNamespace(inputs=(spec,)), deadline=deadline)


def _ask(**over: object) -> AskSettings:
    base = load_settings(_env(GS_CALL_TIMEOUT="30")).ask
    assert base is not None
    return dataclasses.replace(base, **over)


@pytest.mark.parametrize("name", ["has space", "dot.name", "", "a" * 65, "ü", "x/y"])
def test_name_not_allowed_in_ask_flows_names_the_flow(name: str) -> None:
    registry = {name: _stand_in(10.0)}
    with pytest.raises(StartupError) as info:
        plan_ask(registry, _ask(flows=(name,)))
    assert str(info.value) == f"GS_ASK_FLOWS: name_not_allowed ({name})"


def test_name_not_allowed_without_ask_flows_is_a_skip_and_a_summary() -> None:
    registry = {"has space": _stand_in(10.0)}
    with pytest.raises(StartupError) as info:
        plan_ask(registry, _ask())
    assert str(info.value) == "GS_ENABLE_ASK: no_offerable_tools (name_not_allowed)"


def test_name_rule_comes_before_the_secret_and_time_rules() -> None:
    registry = {"bad name": _stand_in(1000.0, secret=True)}
    with pytest.raises(StartupError) as info:
        plan_ask(registry, _ask(flows=("bad name",)))
    assert str(info.value) == "GS_ASK_FLOWS: name_not_allowed (bad name)"


def test_secret_rule_comes_before_the_time_rule() -> None:
    registry = {"flow-a": _stand_in(1000.0, secret=True)}
    with pytest.raises(StartupError) as info:
        plan_ask(registry, _ask(flows=("flow-a",)))
    assert str(info.value) == "GS_ASK_FLOWS: has_secret_input (flow-a)"


# --------------------------------------------------------------------------
# no_offerable_tools
# --------------------------------------------------------------------------

def test_defaults_without_call_timeout_offer_no_tool() -> None:
    env = _env()
    del env["GS_CALL_TIMEOUT"]  # the publisher default is 180: C = 190, far above 90
    assert _error(env) == "GS_ENABLE_ASK: no_offerable_tools (call_too_long: lower GS_CALL_TIMEOUT)"


def test_no_offerable_tools_for_a_secret_input_flow_alone_has_no_hint() -> None:
    env = _env(GS_PUBLISH_FLOWS=LOGON)
    del env[BIND]  # the bound pair belongs to a Flow that is not published here
    assert _error(env) == "GS_ENABLE_ASK: no_offerable_tools (has_secret_input)"


def test_no_offerable_tools_message_names_rules_only() -> None:
    message = _error(_env(GS_CALL_TIMEOUT="31"))
    assert message.startswith("GS_ENABLE_ASK: no_offerable_tools (")
    assert SYSINFO not in message


# --------------------------------------------------------------------------
# model_timeout_too_long
# --------------------------------------------------------------------------

def test_model_timeout_too_long_stops_before_the_registry_is_built() -> None:
    # T 40 with the default M 25: 2 * 25 = 50 > 40.
    with pytest.raises(StartupError) as info:
        load_settings(_env(GS_ASK_TIMEOUT_SECONDS="40"))
    assert str(info.value) == "GS_ASK_MODEL_TIMEOUT_SECONDS: model_timeout_too_long"
    with pytest.raises(StartupError) as again:
        prepare(_env(GS_ASK_TIMEOUT_SECONDS="40"))
    assert str(again.value) == "GS_ASK_MODEL_TIMEOUT_SECONDS: model_timeout_too_long"


def test_model_timeout_fits_when_twice_it_equals_the_timeout() -> None:
    env = _env(GS_ASK_TIMEOUT_SECONDS="50", GS_CALL_TIMEOUT="1")
    settings = load_settings(env)
    assert settings.ask.timeout_seconds == 50.0 and settings.ask.model_timeout_seconds == 25.0


# --------------------------------------------------------------------------
# Eligibility boundary: C + 2M == T
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("timeout", "model", "call", "fits"),
    [
        ("90", "25", "30", True),    # exact fit: 40 + 50 = 90
        ("90", "25", "30.5", False),
        ("90", "25", "31", False),
        ("90", "25", "29.9", True),
        ("95", "25", "35", True),    # 45 + 50 = 95
        ("95", "25", "36", False),
        ("90", "15", "50", True),    # 60 + 30 = 90
        ("90", "15", "51", False),
        ("90", "30", "20", True),    # 30 + 60 = 90
        ("90", "30", "21", False),
        ("20", "1", "8", True),      # 18 + 2 = 20
        ("20", "1", "9", False),
    ],
)
def test_eligibility_boundary_is_call_plus_two_model_turns_at_most_the_timeout(
    timeout: str, model: str, call: str, fits: bool
) -> None:
    env = _env(
        GS_ASK_TIMEOUT_SECONDS=timeout,
        GS_ASK_MODEL_TIMEOUT_SECONDS=model,
        GS_CALL_TIMEOUT=call,
    )
    if fits:
        plan = prepare(env).ask
        assert plan.eligible == frozenset({SYSINFO})
        assert plan.worst_case[SYSINFO] == float(call) + TOOL_TAIL
    else:
        assert _error(env) == (
            "GS_ENABLE_ASK: no_offerable_tools (call_too_long: lower GS_CALL_TIMEOUT)"
        )


def test_demo_box_numbers_give_tool_worst_case_forty() -> None:
    plan = prepare(_env(GS_CALL_TIMEOUT="30")).ask  # T 90 and M 25 are the defaults
    assert TOOL_TAIL == 10.0
    assert dict(plan.worst_case) == {SYSINFO: 40.0}


def test_call_timeout_31_at_the_defaults_is_call_too_long_with_its_hint() -> None:
    assert _error(_env(GS_CALL_TIMEOUT="31")) == (
        "GS_ENABLE_ASK: no_offerable_tools (call_too_long: lower GS_CALL_TIMEOUT)"
    )


def test_deadline_is_capped_by_the_flow_not_only_by_call_timeout() -> None:
    # The flow's own run + finally + 30 is 180; a call timeout above it does not raise the deadline.
    registry = prepare(_env(GS_CALL_TIMEOUT="900", GS_ENABLE_ASK="false")).registry
    assert registry[SYSINFO].deadline == 180.0


# --------------------------------------------------------------------------
# Fixed_Hint (task 6.6, Requirement 1 criterion 10)
# --------------------------------------------------------------------------

def test_every_hint_is_one_lower_case_verb_and_one_setting_name_without_digits() -> None:
    import re

    from greenscreen.publisher.ask.service import HINTS

    assert set(HINTS) == {"call_too_long", "worst_case_too_long"}
    for rule, hint in HINTS.items():
        assert re.fullmatch(r"^[a-z]+ GS_[A-Z_]+$", hint), (rule, hint)
        assert not any(ch.isdigit() for ch in hint)
    assert HINTS["call_too_long"] == "lower GS_CALL_TIMEOUT"
    assert HINTS["worst_case_too_long"] == "lower GS_ASK_TIMEOUT_SECONDS"


def test_no_other_rule_carries_a_hint_in_a_message() -> None:
    env = _env(GS_PUBLISH_FLOWS=LOGON)
    del env[BIND]
    assert ":" not in _error(env).split("(", 1)[1]  # has_secret_input has no hint


def test_the_two_hinted_messages_end_with_their_hint() -> None:
    from greenscreen.publisher.ask import service

    assert _error(_env(GS_CALL_TIMEOUT="31", GS_ASK_FLOWS=SYSINFO)).endswith(f"call_too_long ({SYSINFO}: lower GS_CALL_TIMEOUT)")
    registry = {"flow-a": _stand_in(30.0)}
    patched = dataclasses.replace(_ask(), timeout_seconds=95.0)
    original = service.WORST_CASE_LIMIT
    service.WORST_CASE_LIMIT = 97.0
    try:
        with pytest.raises(StartupError) as info:
            plan_ask(registry, patched)
    finally:
        service.WORST_CASE_LIMIT = original
    assert str(info.value) == "GS_ASK_TIMEOUT_SECONDS: worst_case_too_long (lower GS_ASK_TIMEOUT_SECONDS)"


def test_the_default_environment_message_is_exact() -> None:
    env = _env()
    del env["GS_CALL_TIMEOUT"]
    assert _error(env) == "GS_ENABLE_ASK: no_offerable_tools (call_too_long: lower GS_CALL_TIMEOUT)"
