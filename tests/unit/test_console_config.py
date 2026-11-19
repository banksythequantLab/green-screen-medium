"""The console switch and the off-switch behaviour (spec console, task 2.9).

Everything runs on the Fake_Host or on ``load_settings`` alone. API keys are generated
per test and never written anywhere. No live host, no network.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from greenscreen.publisher.app import prepare  # noqa: E402
from greenscreen.publisher.calls import error_body  # noqa: E402
from greenscreen.publisher.config import StartupError, load_settings  # noqa: E402
from tests.console_support import (  # noqa: E402
    BASE_ENV,
    EXPECTED_PAIRS,
    build_console_app,
    call_scope,
)
from tests.publisher_support import LogCapture  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SIX_PATHS = sorted(path for _method, path in EXPECTED_PAIRS)


def _env(**extra: str) -> dict[str, str]:
    return {**BASE_ENV, "GS_API_KEY": uuid.uuid4().hex, **extra}


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# GS_ENABLE_CONSOLE parsing (Requirements 1.1, 1.2, 1.3)
# --------------------------------------------------------------------------


def test_console_is_off_when_the_variable_is_unset():
    assert load_settings(_env()).enable_console is False


@pytest.mark.parametrize(
    "value,expected", [("", False), ("true", True), ("false", False)]
)
def test_console_switch_accepts_empty_true_and_false(value, expected):
    assert load_settings(_env(GS_ENABLE_CONSOLE=value)).enable_console is expected


def test_console_switch_rejects_any_other_value_and_never_names_it():
    value = "maybe-" + uuid.uuid4().hex[:8]
    with pytest.raises(StartupError) as info:
        load_settings(_env(GS_ENABLE_CONSOLE=value))
    message = str(info.value)
    assert "GS_ENABLE_CONSOLE" in message
    assert "not_a_boolean (true or false)" in message
    assert value not in message


@pytest.mark.parametrize("value", ["True", "TRUE", "1", "yes", " true"])
def test_console_switch_is_exact_text(value):
    with pytest.raises(StartupError) as info:
        load_settings(_env(GS_ENABLE_CONSOLE=value))
    assert "GS_ENABLE_CONSOLE: not_a_boolean" in str(info.value)


def test_settings_repr_is_unchanged_by_the_new_field():
    settings = load_settings(_env(GS_ENABLE_CONSOLE="true"))
    text = repr(settings)
    assert text == (
        f"Settings(transport={settings.transport!r}, "
        f"publish_host={settings.publish_host!r}, publish_port={settings.publish_port})"
    )
    assert "console" not in text.lower()


# --------------------------------------------------------------------------
# stdio ignores the setting (Requirement 1.5)
# --------------------------------------------------------------------------


def test_stdio_ignores_the_console_switch():
    base = _env(GS_TRANSPORT="stdio")
    with_switch = prepare({**base, "GS_ENABLE_CONSOLE": "true"})
    without = prepare(base)
    assert with_switch.settings.transport == "stdio"
    assert with_switch.console == ()
    assert without.console == ()
    assert [f for f in with_switch.registry] == [f for f in without.registry]


def test_http_with_the_switch_on_loads_six_assets_and_off_loads_none():
    on = prepare(_env(GS_ENABLE_CONSOLE="true"))
    off = prepare(_env())
    assert {(a.path) for a in on.console} == set(SIX_PATHS)
    assert len(on.console) == 6
    assert off.console == ()


# --------------------------------------------------------------------------
# .env.example (Requirement 1.8)
# --------------------------------------------------------------------------


def test_env_example_gains_one_comment_line_and_one_name_line():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    names = [i for i, line in enumerate(lines) if "GS_ENABLE_CONSOLE" in line]
    assert len(names) == 1
    at = names[0]
    assert lines[at] == "GS_ENABLE_CONSOLE="
    assert lines[at - 1].startswith("# ") and "console" in lines[at - 1].lower()
    # the name sits right after the docs switch, which it parallels
    assert lines[at - 2] == "GS_ENABLE_DOCS="
    assert not lines[at + 1].startswith("GS_ENABLE_CONSOLE")
    # no value, no secret-like text on any line that names a variable of this spec
    for line in lines:
        if line.startswith("GS_"):
            assert re.fullmatch(r"GS_[A-Z0-9_]+=", line), "a variable line holds a value"


# --------------------------------------------------------------------------
# Console off: each of the six paths is an unknown path (Requirements 1.9, 13.7)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", SIX_PATHS)
def test_console_off_without_a_key_is_unauthorized(path):
    built = build_console_app(console=False)
    status, headers, body = run(call_scope(built.app.asgi, "GET", path))
    assert status == 401
    assert _loads(body) == error_body("unauthorized")
    assert (b"www-authenticate", b"Bearer") in headers
    assert not any(name == b"content-security-policy" for name, _ in headers)
    assert built.host.factory_calls == 0


@pytest.mark.parametrize("path", SIX_PATHS)
def test_console_off_with_a_key_is_request_invalid(path):
    built = build_console_app(console=False)
    status, headers, body = run(
        call_scope(built.app.asgi, "GET", path, {"X-API-Key": built.api_key})
    )
    assert status == 400
    assert _loads(body)["error"]["code"] == "request_invalid"
    assert not any(name == b"content-security-policy" for name, _ in headers)
    assert built.api_key.encode() not in body
    assert built.host.factory_calls == 0


@pytest.mark.parametrize("path", SIX_PATHS)
def test_console_off_with_a_wrong_key_is_unauthorized(path):
    built = build_console_app(console=False)
    status, _headers, body = run(
        call_scope(built.app.asgi, "GET", path, {"X-API-Key": "x" * 22})
    )
    assert status == 401
    assert _loads(body)["error"]["code"] == "unauthorized"


def test_console_off_startup_log_has_no_console_record():
    from greenscreen.publisher import cli

    with LogCapture() as logs:
        build_console_app(console=False)
        cli._report_startup(prepare(_env()))
        logs.refresh()
        texts = [t.lower() for t in logs.texts()]
    assert any("publishing" in t for t in texts)
    assert not [t for t in texts if "console" in t]


def _loads(body: bytes):
    import json

    return json.loads(body)


# --------------------------------------------------------------------------
# GET /docs depends only on GS_ENABLE_DOCS (Requirement 13.5)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("console", [True, False])
@pytest.mark.parametrize("docs,expected", [("true", 200), ("false", 400), ("", 400)])
def test_docs_depends_only_on_the_docs_switch(console, docs, expected):
    built = build_console_app({"GS_ENABLE_DOCS": docs}, console=console)

    async def go():
        async with built.app.lifespan():
            keyed = await call_scope(
                built.app.asgi, "GET", "/docs", {"X-API-Key": built.api_key}
            )
            bare = await call_scope(built.app.asgi, "GET", "/docs")
            spec = await call_scope(
                built.app.asgi, "GET", "/openapi.json", {"X-API-Key": built.api_key}
            )
        return keyed, bare, spec

    keyed, bare, spec = run(go())
    assert keyed[0] == expected
    assert bare[0] == 401  # /docs is never open without a key
    assert spec[0] == 200  # /openapi.json is served in both cases
    if expected == 400:
        assert _loads(keyed[2])["error"]["code"] == "request_invalid"
