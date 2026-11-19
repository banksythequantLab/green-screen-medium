"""Ask settings: every variable, default, range edge and rule name (spec ask, task 2.10).

Requirement 1 and Decision 30 (``GS_LLM_REASONING_EFFORT``). Everything runs on
``load_settings`` and ``prepare`` alone; no live host, no model, no network. Keys are
generated per test and never written anywhere. Every rule message is compared as a whole, so
a value in a message fails the test.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import re
import secrets
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

from greenscreen.publisher import cli  # noqa: E402
from greenscreen.publisher.app import prepare  # noqa: E402
from greenscreen.publisher.config import (  # noqa: E402
    REASONING_EFFORTS,
    AskSettings,
    StartupError,
    is_ask_loopback_host,
    load_settings,
)
from tests.ask_support import BOUND_PASSWORD, no_network  # noqa: E402,F401  (autouse)

ROOT = Path(__file__).resolve().parents[2]
LOGGER = "greenscreen.publisher"
BIND = "GS_BIND_" + "TK5_SYSTEM_INFO__PASSWORD"
EFFORT_MESSAGE = "GS_LLM_REASONING_EFFORT: not_allowed (none, minimal, low, medium, high)"

ASK_VARIABLES = (
    "GS_ENABLE_ASK",
    "GS_LLM_BASE_URL",
    "GS_LLM_MODEL",
    "GS_LLM_API_KEY",
    "GS_LLM_REASONING_EFFORT",
    "GS_ASK_MAX_TOOL_CALLS",
    "GS_ASK_MAX_TURNS",
    "GS_ASK_TIMEOUT_SECONDS",
    "GS_ASK_MODEL_TIMEOUT_SECONDS",
    "GS_ASK_FLOWS",
    "GS_ASK_MAX_QUESTION_CHARS",
    "GS_ASK_MAX_ANSWER_CHARS",
    "GS_ASK_MAX_RESULT_CHARS",
    "GS_ASK_DAILY_LIMIT",
)


def _env(**extra: str) -> dict[str, str]:
    env = {
        "GS_S3270_BINARY": "s3270",
        "GS_HOST": "host.invalid",
        "GS_API_KEY": uuid.uuid4().hex,
        "GS_PUBLISH_FLOWS": "tk5-system-info",
        "GS_ENABLE_ASK": "true",
        "GS_LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "GS_LLM_MODEL": "fake-model",
    }
    env.update(extra)
    return env


def _ask(**extra: str) -> AskSettings:
    ask = load_settings(_env(**extra)).ask
    assert ask is not None
    return ask


def _error(**extra: str) -> str:
    with pytest.raises(StartupError) as info:
        load_settings(_env(**extra))
    return str(info.value)


# --------------------------------------------------------------------------
# GS_ENABLE_ASK
# --------------------------------------------------------------------------

def test_ask_is_off_when_the_switch_is_unset_empty_or_false() -> None:
    env = _env()
    del env["GS_ENABLE_ASK"]
    assert load_settings(env).ask is None
    assert load_settings(_env(GS_ENABLE_ASK="")).ask is None
    assert load_settings(_env(GS_ENABLE_ASK="false")).ask is None


@pytest.mark.parametrize("value", ["TRUE", "True", "1", "yes", " true", "true ", "on", "tru"])
def test_the_switch_is_exact_text_and_a_bad_value_is_never_named(value: str) -> None:
    message = _error(GS_ENABLE_ASK=value)
    assert message == "GS_ENABLE_ASK: not_a_boolean (true or false)"


def test_the_switch_is_parsed_even_when_ask_would_be_ignored() -> None:
    assert _error(GS_TRANSPORT="stdio", GS_ENABLE_ASK="maybe") == (
        "GS_ENABLE_ASK: not_a_boolean (true or false)"
    )


def test_switch_on_loads_the_ask_settings() -> None:
    assert isinstance(load_settings(_env()).ask, AskSettings)


# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

def test_defaults() -> None:
    ask = _ask()
    assert ask.base_url == "http://127.0.0.1:11434/v1"
    assert ask.model == "fake-model"
    assert ask.llm_api_key is None
    assert ask.reasoning_effort is None
    assert ask.max_tool_calls == 6
    assert ask.max_turns == 8
    assert ask.timeout_seconds == 90.0
    assert ask.model_timeout_seconds == 25.0
    assert ask.flows is None
    assert ask.max_question_chars == 500
    assert ask.max_answer_chars == 2000
    assert ask.max_result_chars == 4000
    assert ask.daily_limit == 100


def test_empty_values_are_unset_and_give_the_defaults() -> None:
    empty = {name: "" for name in ASK_VARIABLES if name not in (
        "GS_ENABLE_ASK", "GS_LLM_BASE_URL", "GS_LLM_MODEL"
    )}
    assert _ask(**empty) == _ask()


def test_the_defaults_themselves_pass_the_start_rules() -> None:
    ask = _ask()
    assert 2 * ask.model_timeout_seconds <= ask.timeout_seconds
    assert 20.0 <= ask.timeout_seconds <= 95.0


# --------------------------------------------------------------------------
# Ranges: each edge, each rule name
# --------------------------------------------------------------------------

INT_SETTINGS = [
    ("GS_ASK_MAX_TOOL_CALLS", "max_tool_calls", 1, 20),
    ("GS_ASK_MAX_TURNS", "max_turns", 1, 30),
    ("GS_ASK_MAX_QUESTION_CHARS", "max_question_chars", 1, 2000),
    ("GS_ASK_MAX_ANSWER_CHARS", "max_answer_chars", 100, 20000),
    ("GS_ASK_MAX_RESULT_CHARS", "max_result_chars", 200, 20000),
    ("GS_ASK_DAILY_LIMIT", "daily_limit", 1, 100000),
]


@pytest.mark.parametrize(("name", "attr", "lo", "hi"), INT_SETTINGS)
def test_integer_range_edges(name: str, attr: str, lo: int, hi: int) -> None:
    assert getattr(_ask(**{name: str(lo)}), attr) == lo
    assert getattr(_ask(**{name: str(hi)}), attr) == hi
    rule = f"{name}: out_of_range ({lo} to {hi})"
    assert _error(**{name: str(lo - 1)}) == rule
    assert _error(**{name: str(hi + 1)}) == rule


@pytest.mark.parametrize(("name", "attr", "lo", "hi"), INT_SETTINGS)
@pytest.mark.parametrize("bad", ["abc", "1.5", "-1", "+1", " 5", "5 ", "1e3", "0x10", "\u0663"])
def test_integer_settings_reject_non_integers_without_the_value(
    name: str, attr: str, lo: int, hi: int, bad: str
) -> None:
    assert _error(**{name: bad}) == f"{name}: not_an_integer"


def test_timeout_range_edges() -> None:
    assert _ask(GS_ASK_TIMEOUT_SECONDS="20", GS_ASK_MODEL_TIMEOUT_SECONDS="10").timeout_seconds == 20.0
    assert _ask(GS_ASK_TIMEOUT_SECONDS="95").timeout_seconds == 95.0
    assert _ask(GS_ASK_TIMEOUT_SECONDS="95.0").timeout_seconds == 95.0
    rule = "GS_ASK_TIMEOUT_SECONDS: out_of_range (20 to 95)"
    assert _error(GS_ASK_TIMEOUT_SECONDS="19.9") == rule
    assert _error(GS_ASK_TIMEOUT_SECONDS="95.1") == rule
    assert _error(GS_ASK_TIMEOUT_SECONDS="0") == rule
    assert _error(GS_ASK_TIMEOUT_SECONDS="1000") == rule


def test_model_timeout_range_edges() -> None:
    assert _ask(GS_ASK_MODEL_TIMEOUT_SECONDS="1").model_timeout_seconds == 1.0
    both = _ask(GS_ASK_MODEL_TIMEOUT_SECONDS="47.5", GS_ASK_TIMEOUT_SECONDS="95")
    assert both.model_timeout_seconds == 47.5
    rule = "GS_ASK_MODEL_TIMEOUT_SECONDS: out_of_range (1 to 60)"
    assert _error(GS_ASK_MODEL_TIMEOUT_SECONDS="0.9") == rule
    assert _error(GS_ASK_MODEL_TIMEOUT_SECONDS="60.1") == rule
    # 60 is in range, but twice 60 is more than the largest timeout.
    assert _error(GS_ASK_MODEL_TIMEOUT_SECONDS="60", GS_ASK_TIMEOUT_SECONDS="95") == (
        "GS_ASK_MODEL_TIMEOUT_SECONDS: model_timeout_too_long"
    )


@pytest.mark.parametrize("name", ["GS_ASK_TIMEOUT_SECONDS", "GS_ASK_MODEL_TIMEOUT_SECONDS"])
@pytest.mark.parametrize("bad", ["abc", "-1", "1e3", "1.", ".5", "nan", "inf", "5 s", " 5"])
def test_seconds_settings_reject_non_numbers_without_the_value(name: str, bad: str) -> None:
    assert _error(**{name: bad}) == f"{name}: not_a_number"


def test_model_timeout_too_long_at_the_exact_edge_is_allowed() -> None:
    ask = _ask(GS_ASK_TIMEOUT_SECONDS="50", GS_ASK_MODEL_TIMEOUT_SECONDS="25")
    assert 2 * ask.model_timeout_seconds == ask.timeout_seconds


def test_timeout_40_with_the_default_model_timeout_is_model_timeout_too_long() -> None:
    assert _error(GS_ASK_TIMEOUT_SECONDS="40") == (
        "GS_ASK_MODEL_TIMEOUT_SECONDS: model_timeout_too_long"
    )
    assert _error(GS_ASK_TIMEOUT_SECONDS="49.9") == (
        "GS_ASK_MODEL_TIMEOUT_SECONDS: model_timeout_too_long"
    )
    assert _ask(GS_ASK_TIMEOUT_SECONDS="40", GS_ASK_MODEL_TIMEOUT_SECONDS="20").timeout_seconds == 40.0


# --------------------------------------------------------------------------
# The fixed order of the checks
# --------------------------------------------------------------------------

ORDERED_BAD = [
    ("GS_LLM_BASE_URL", "not a url", "not_a_url"),
    ("GS_LLM_MODEL", "bad model", "invalid_model_name"),
    ("GS_LLM_API_KEY", "bad key", "invalid_key"),
    ("GS_LLM_REASONING_EFFORT", "extreme", "not_allowed (none, minimal, low, medium, high)"),
    ("GS_ASK_MAX_TOOL_CALLS", "x", "not_an_integer"),
    ("GS_ASK_MAX_TURNS", "x", "not_an_integer"),
    ("GS_ASK_TIMEOUT_SECONDS", "x", "not_a_number"),
    ("GS_ASK_MODEL_TIMEOUT_SECONDS", "x", "not_a_number"),
    ("GS_ASK_MAX_QUESTION_CHARS", "x", "not_an_integer"),
    ("GS_ASK_MAX_ANSWER_CHARS", "x", "not_an_integer"),
    ("GS_ASK_MAX_RESULT_CHARS", "x", "not_an_integer"),
    ("GS_ASK_DAILY_LIMIT", "x", "not_an_integer"),
]


@pytest.mark.parametrize("index", range(len(ORDERED_BAD)))
def test_the_first_failing_variable_in_the_fixed_order_is_reported(index: int) -> None:
    extra = {name: value for name, value, _rule in ORDERED_BAD[index:]}
    name, _value, rule = ORDERED_BAD[index]
    assert _error(**extra) == f"{name}: {rule}"


def test_model_timeout_too_long_comes_after_every_single_variable_check() -> None:
    # Also invalid: the daily limit, the last single check. It must be reported first.
    assert _error(
        GS_ASK_TIMEOUT_SECONDS="20", GS_ASK_MODEL_TIMEOUT_SECONDS="30", GS_ASK_DAILY_LIMIT="x"
    ) == "GS_ASK_DAILY_LIMIT: not_an_integer"
    assert _error(
        GS_ASK_TIMEOUT_SECONDS="20", GS_ASK_MODEL_TIMEOUT_SECONDS="30", GS_ASK_FLOWS="a,,b"
    ) == "GS_ASK_MODEL_TIMEOUT_SECONDS: model_timeout_too_long"


def test_ask_flows_list_rules_come_last() -> None:
    assert _error(GS_ASK_FLOWS="a,,b") == "GS_ASK_FLOWS: empty_item"


# --------------------------------------------------------------------------
# GS_LLM_BASE_URL
# --------------------------------------------------------------------------

def test_base_url_missing() -> None:
    env = _env()
    del env["GS_LLM_BASE_URL"]
    with pytest.raises(StartupError) as info:
        load_settings(env)
    assert str(info.value) == "GS_LLM_BASE_URL: missing"
    assert _error(GS_LLM_BASE_URL="") == "GS_LLM_BASE_URL: missing"


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/v1",
        "example.com/v1",
        "http://",
        "https:///v1",
        "http://exa mple.com",
        "http://127.0.0.1:99999",
        "http://127.0.0.1:port",
        "http://127.0.0.1/\n",
        "http://\u00fc.example",
        "file:///etc/hosts",
        "  http://127.0.0.1",
        "http://127.0.0.1 ",
        "//127.0.0.1/v1",
    ],
)
def test_base_url_that_is_not_a_url(url: str) -> None:
    assert _error(GS_LLM_BASE_URL=url) == "GS_LLM_BASE_URL: not_a_url"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "http://127.0.0.2/v1",
        "http://localhost.evil.com/v1",
        "http://127.0.0.1.evil.com/v1",
        "http://0.0.0.0/v1",
        "http://[::2]/v1",
        "http://192.168.68.72:11434/v1",
    ],
)
def test_plain_http_to_a_non_loopback_host_needs_https(url: str) -> None:
    assert _error(GS_LLM_BASE_URL=url, GS_LLM_API_KEY="k" * 20) == (
        "GS_LLM_BASE_URL: https_required"
    )


def test_credentials_in_the_url_are_named_without_them() -> None:
    sentinel = secrets.token_hex(6)
    for url in (
        f"https://user:{sentinel}@example.com/v1",
        f"https://{sentinel}@example.com/v1",
        f"https://:{sentinel}@example.com/v1",
        f"http://user:{sentinel}@127.0.0.1/v1",
    ):
        message = _error(GS_LLM_BASE_URL=url, GS_LLM_API_KEY="k" * 20)
        assert message == "GS_LLM_BASE_URL: credentials_in_url"
        assert sentinel not in message


def test_query_or_fragment_in_the_url_is_named_without_it() -> None:
    sentinel = secrets.token_hex(6)
    for url in (
        f"https://example.com/v1?key={sentinel}",
        f"https://example.com/v1#{sentinel}",
        "https://example.com/v1?",
        "https://example.com/v1#",
        f"http://127.0.0.1/v1?{sentinel}",
    ):
        message = _error(GS_LLM_BASE_URL=url, GS_LLM_API_KEY="k" * 20)
        assert message == "GS_LLM_BASE_URL: query_in_url"
        assert sentinel not in message


@pytest.mark.parametrize(
    ("url", "stored"),
    [
        ("http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1"),
        ("http://127.0.0.1:11434/v1/", "http://127.0.0.1:11434/v1"),
        ("http://127.0.0.1:11434/v1//", "http://127.0.0.1:11434/v1"),
        ("http://127.0.0.1", "http://127.0.0.1"),
        ("http://127.0.0.1/", "http://127.0.0.1"),
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://LOCALHOST:11434/v1", "http://LOCALHOST:11434/v1"),
        ("http://[::1]:11434/v1", "http://[::1]:11434/v1"),
        ("https://127.0.0.1:8443/v1", "https://127.0.0.1:8443/v1"),
        ("HTTP://127.0.0.1/v1", "http://127.0.0.1/v1"),
    ],
)
def test_loopback_urls_are_accepted_without_a_key_and_rebuilt(url: str, stored: str) -> None:
    ask = _ask(GS_LLM_BASE_URL=url)
    assert ask.base_url == stored
    assert ask.llm_api_key is None


@pytest.mark.parametrize(
    ("url", "stored"),
    [
        ("https://api.example.com/v1", "https://api.example.com/v1"),
        ("https://api.example.com/", "https://api.example.com"),
        ("https://api.example.com:8443/openai/v1/", "https://api.example.com:8443/openai/v1"),
    ],
)
def test_https_urls_to_other_hosts_are_accepted_with_a_key(url: str, stored: str) -> None:
    key = secrets.token_urlsafe(24)
    ask = _ask(GS_LLM_BASE_URL=url, GS_LLM_API_KEY=key)
    assert ask.base_url == stored
    assert ask.llm_api_key == key


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("LocalHost", True),
        ("127.0.0.2", False),
        ("0.0.0.0", False),
        ("example.com", False),
        ("localhost.example", False),
        ("", False),
    ],
)
def test_ask_loopback_hosts_are_exactly_three(host: str, expected: bool) -> None:
    assert is_ask_loopback_host(host) is expected


# --------------------------------------------------------------------------
# GS_LLM_MODEL
# --------------------------------------------------------------------------

def test_model_missing() -> None:
    env = _env()
    del env["GS_LLM_MODEL"]
    with pytest.raises(StartupError) as info:
        load_settings(env)
    assert str(info.value) == "GS_LLM_MODEL: missing"
    assert _error(GS_LLM_MODEL="") == "GS_LLM_MODEL: missing"


@pytest.mark.parametrize(
    "model",
    ["gpt-4o", "llama3.2:latest", "org/model@v1", "A_b.c-d", "a", "a" * 100, "qwen3:8b"],
)
def test_valid_model_names(model: str) -> None:
    assert _ask(GS_LLM_MODEL=model).model == model


@pytest.mark.parametrize(
    "model", ["a" * 101, "has space", "x$", "\u00fc", "a\n", "a\tb", "a;b", "a|b", "a,b", "a+b"]
)
def test_invalid_model_names(model: str) -> None:
    assert _error(GS_LLM_MODEL=model) == "GS_LLM_MODEL: invalid_model_name"


# --------------------------------------------------------------------------
# GS_LLM_API_KEY
# --------------------------------------------------------------------------

def test_the_key_is_required_unless_the_host_is_loopback() -> None:
    assert _error(GS_LLM_BASE_URL="https://api.example.com/v1") == "GS_LLM_API_KEY: missing"
    assert _error(GS_LLM_BASE_URL="https://api.example.com/v1", GS_LLM_API_KEY="") == (
        "GS_LLM_API_KEY: missing"
    )
    assert _ask().llm_api_key is None
    assert _ask(GS_LLM_BASE_URL="https://localhost/v1").llm_api_key is None


def test_a_loopback_host_may_still_carry_a_key() -> None:
    key = secrets.token_urlsafe(20)
    assert _ask(GS_LLM_API_KEY=key).llm_api_key == key


@pytest.mark.parametrize("length", [1, 8, 512])
def test_key_lengths_that_are_accepted(length: int) -> None:
    key = "k" * length
    assert _ask(GS_LLM_API_KEY=key).llm_api_key == key


def test_keys_that_are_not_printable_ascii_without_space_are_invalid_and_never_named() -> None:
    sentinel = secrets.token_hex(6)
    bad = [
        "k" * 513,
        f"{sentinel} {sentinel}",
        f"{sentinel}\t",
        f"{sentinel}\n",
        f"{sentinel}\u00fc",
        f"{sentinel}\x7f",
        f"{sentinel}\x00",
        f" {sentinel}",
    ]
    for key in bad:
        message = _error(GS_LLM_API_KEY=key)
        assert message == "GS_LLM_API_KEY: invalid_key"
        assert sentinel not in message


# --------------------------------------------------------------------------
# GS_LLM_REASONING_EFFORT (Decision 30)
# --------------------------------------------------------------------------

def test_the_constant_holds_the_five_values_in_order() -> None:
    assert REASONING_EFFORTS == ("none", "minimal", "low", "medium", "high")


@pytest.mark.parametrize("value", ["none", "minimal", "low", "medium", "high"])
def test_each_allowed_effort_is_stored_exactly(value: str) -> None:
    assert _ask(GS_LLM_REASONING_EFFORT=value).reasoning_effort == value


def test_effort_unset_and_empty_are_none() -> None:
    assert _ask().reasoning_effort is None
    assert _ask(GS_LLM_REASONING_EFFORT="").reasoning_effort is None


@pytest.mark.parametrize(
    "value",
    [
        "NONE",
        "Low",
        "HIGH",
        "off",
        "xhigh",
        "max",
        "true",
        "ultra",
        " low",
        "low ",
        "low\n",
        "\nlow",
        "lo w",
        " ",
        "low,high",
        "x" * 1000,
    ],
)
def test_any_other_effort_stops_the_start_with_the_fixed_message(value: str) -> None:
    message = _error(GS_LLM_REASONING_EFFORT=value)
    assert message == EFFORT_MESSAGE


def test_the_effort_is_ignored_while_ask_is_off_or_on_stdio() -> None:
    assert load_settings(_env(GS_ENABLE_ASK="false", GS_LLM_REASONING_EFFORT="off")).ask is None
    assert load_settings(_env(GS_TRANSPORT="stdio", GS_LLM_REASONING_EFFORT="off")).ask is None
    env = _env(GS_LLM_REASONING_EFFORT="off")
    del env["GS_ENABLE_ASK"]
    assert load_settings(env).ask is None


# --------------------------------------------------------------------------
# Ignored while off, and on stdio
# --------------------------------------------------------------------------

def _garbage() -> dict[str, str]:
    return {
        name: "!! not valid !!"
        for name in ASK_VARIABLES
        if name != "GS_ENABLE_ASK"
    }


@pytest.mark.parametrize("switch", [None, "", "false"])
def test_every_ask_variable_is_ignored_while_ask_is_off(switch: str | None) -> None:
    env = _env(**_garbage())
    if switch is None:
        del env["GS_ENABLE_ASK"]
    else:
        env["GS_ENABLE_ASK"] = switch
    assert load_settings(env).ask is None


def test_every_ask_variable_is_ignored_on_stdio() -> None:
    env = _env(**_garbage(), GS_TRANSPORT="stdio")
    del env["GS_API_KEY"]
    assert load_settings(env).ask is None


def test_the_http_transport_default_reads_them() -> None:
    assert _error(**_garbage()) == "GS_LLM_BASE_URL: not_a_url"


# --------------------------------------------------------------------------
# No value in a message; no value in a repr
# --------------------------------------------------------------------------

def test_no_rule_message_holds_a_supplied_value() -> None:
    sentinel = "S" + secrets.token_hex(8)
    cases = {
        "GS_LLM_BASE_URL": f"https://{sentinel}.example.com:{sentinel}/v1",
        "GS_LLM_MODEL": f"bad {sentinel}",
        "GS_LLM_API_KEY": f"bad {sentinel}",
        "GS_LLM_REASONING_EFFORT": sentinel,
        "GS_ASK_MAX_TOOL_CALLS": sentinel,
        "GS_ASK_MAX_TURNS": f"99{sentinel}",
        "GS_ASK_TIMEOUT_SECONDS": sentinel,
        "GS_ASK_MODEL_TIMEOUT_SECONDS": sentinel,
        "GS_ASK_MAX_QUESTION_CHARS": sentinel,
        "GS_ASK_MAX_ANSWER_CHARS": sentinel,
        "GS_ASK_MAX_RESULT_CHARS": sentinel,
        "GS_ASK_DAILY_LIMIT": sentinel,
        "GS_ENABLE_ASK": sentinel,
    }
    for name, value in cases.items():
        message = _error(**{name: value})
        assert sentinel not in message, name
        assert message.startswith(name + ":"), name


def test_repr_of_settings_and_ask_settings_shows_no_ask_value() -> None:
    key = secrets.token_urlsafe(24)
    model = "m" + secrets.token_hex(6)
    url = f"https://{secrets.token_hex(4)}.example.com/v1"
    settings = load_settings(
        _env(
            GS_LLM_BASE_URL=url,
            GS_LLM_MODEL=model,
            GS_LLM_API_KEY=key,
            GS_LLM_REASONING_EFFORT="high",
            GS_ASK_FLOWS="tk5-system-info",
        )
    )
    ask = settings.ask
    assert ask is not None
    assert repr(ask) == "AskSettings(configured)"
    assert str(ask) == "AskSettings(configured)"
    assert f"{ask!r}" == "AskSettings(configured)"
    text = repr(settings)
    for value in (key, model, url, "example.com", "high", "tk5-system-info", settings.api_key):
        assert value not in text
    assert text == (
        f"Settings(transport='http', publish_host={settings.publish_host!r}, "
        f"publish_port={settings.publish_port})"
    )
    assert settings.api_key and settings.api_key not in text


def test_a_frozen_dataclass_cannot_be_changed() -> None:
    ask = _ask()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ask.model = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------
# cli: the key is removed from the environment; the startup record
# --------------------------------------------------------------------------

def test_scrub_environment_removes_the_llm_key_with_the_other_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GS_LLM_API_KEY", secrets.token_hex(8))
    monkeypatch.setenv("GS_API_KEY", secrets.token_hex(8))
    monkeypatch.setenv(BIND, secrets.token_hex(4))
    monkeypatch.setenv("GS_LLM_MODEL", "fake-model")
    cli._scrub_environment()
    assert "GS_LLM_API_KEY" not in os.environ
    assert "GS_API_KEY" not in os.environ
    assert BIND not in os.environ
    assert os.environ["GS_LLM_MODEL"] == "fake-model"  # not secret, stays


def _records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER]


def _prepared(**extra: str):
    return prepare(_env(GS_CALL_TIMEOUT="30", **{BIND: BOUND_PASSWORD}, **extra))


def test_startup_writes_the_ask_enabled_record_with_no_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    prepared = _prepared()
    plain = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
    standard = set(plain.__dict__) | {"message", "asctime", "taskName"}
    with caplog.at_level(logging.INFO, logger=LOGGER):
        cli._report_startup(prepared)
    records = _records(caplog)
    ask = [r for r in records if r.getMessage() == "ask enabled"]
    assert len(ask) == 1
    assert ask[0].levelno == logging.INFO
    assert set(ask[0].__dict__) - standard == set()
    assert records[0].msg == "publishing %d of %d flows over %s"
    assert records.index(ask[0]) > 0


def test_ask_enabled_record_follows_the_console_record(caplog: pytest.LogCaptureFixture) -> None:
    prepared = _prepared(GS_ENABLE_CONSOLE="true")
    with caplog.at_level(logging.INFO, logger=LOGGER):
        cli._report_startup(prepared)
    messages = [r.getMessage() for r in _records(caplog)]
    assert messages.index("console enabled") < messages.index("ask enabled")


def test_no_ask_record_while_ask_is_off(caplog: pytest.LogCaptureFixture) -> None:
    prepared = prepare(_env(GS_ENABLE_ASK="false"))
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        cli._report_startup(prepared)
    assert not [r for r in caplog.records if "ask" in r.getMessage().lower()]


def test_startup_records_hold_no_ask_value(caplog: pytest.LogCaptureFixture) -> None:
    key = secrets.token_urlsafe(24)
    model = "m" + secrets.token_hex(6)
    prepared = _prepared(GS_LLM_API_KEY=key, GS_LLM_MODEL=model)
    with caplog.at_level(logging.DEBUG, logger=LOGGER):
        cli._report_startup(prepared)
    blob = " ".join(repr(r.__dict__) for r in caplog.records)
    assert key not in blob and model not in blob and "11434" not in blob


# --------------------------------------------------------------------------
# .env.example
# --------------------------------------------------------------------------

def _env_example() -> list[str]:
    return (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("name", ASK_VARIABLES)
def test_env_example_names_each_ask_variable_once_with_an_empty_value_and_a_comment(
    name: str,
) -> None:
    lines = _env_example()
    at = [i for i, line in enumerate(lines) if line.startswith(name + "=")]
    assert len(at) == 1
    assert lines[at[0]] == f"{name}="
    comment = lines[at[0] - 1]
    assert comment.startswith("# ") and len(comment) > 10


def test_env_example_comment_for_the_effort_lists_the_five_values() -> None:
    lines = _env_example()
    comment = lines[lines.index("GS_LLM_REASONING_EFFORT=") - 1]
    for value in REASONING_EFFORTS:
        assert value in comment


def test_env_example_has_no_value_on_any_variable_line() -> None:
    for line in _env_example():
        if line.startswith("GS_"):
            assert re.fullmatch(r"GS_[A-Z0-9_]+=", line), "a variable line holds a value"


def test_env_example_comments_state_the_ask_timing_rule_and_ranges() -> None:
    lines = _env_example()

    def comment_of(name: str) -> str:
        return lines[lines.index(name + "=") - 1]

    assert "20 to 95" in comment_of("GS_ASK_TIMEOUT_SECONDS") and "default 90" in comment_of("GS_ASK_TIMEOUT_SECONDS")
    model = comment_of("GS_ASK_MODEL_TIMEOUT_SECONDS")
    assert "1 to 60" in model and "default 25" in model and "twice" in model
    assert (
        "# With Ask on and the defaults, GS_CALL_TIMEOUT must be 30 or less (30 recommended);"
        " 31 or more stops the start."
    ) in lines
