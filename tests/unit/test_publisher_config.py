"""Unit tests for greenscreen.publisher.config (settings and publish list)."""
from __future__ import annotations

import pytest
from hypothesis import given, settings as hsettings, strategies as st

from greenscreen.publisher.config import (
    Settings,
    StartupError,
    is_loopback_host,
    load_settings,
    parse_publish_list,
)

# Placeholder values only; none of these is a credential.
KEY = "k" * 16
BASE = {
    "GS_S3270_BINARY": "/opt/s3270-test",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": KEY,
}


def env(**extra: str) -> dict[str, str]:
    d = dict(BASE)
    d.update(extra)
    return d


def fails(environ: dict[str, str], *names: str) -> str:
    with pytest.raises(StartupError) as ei:
        load_settings(environ)
    msg = str(ei.value)
    for n in names:
        assert n in msg
    for v in environ.values():
        if len(v) >= 4 and v not in ("true", "false", "stdio", "http"):
            assert v not in msg, "message holds a variable value"
    return msg


def test_defaults() -> None:
    s = load_settings(env())
    assert isinstance(s, Settings)
    assert (s.connector.binary, s.connector.host, s.connector.port) == ("/opt/s3270-test", "host.invalid", 23)
    assert s.publish_host == "127.0.0.1" and s.publish_port == 8080
    assert s.transport == "http" and s.api_key == KEY and not s.auth_disabled
    assert s.max_concurrency == 1 and s.call_timeout == 180.0
    assert s.max_body_bytes == 65536 and s.shutdown_grace == 10.0
    assert s.enable_docs is False and s.flows_dir is None and s.publish_flows is None


def test_empty_is_unset_and_mapping_only() -> None:
    s = load_settings(env(GS_PUBLISH_PORT="", GS_MAX_CONCURRENCY="", GS_PUBLISH_FLOWS="", GS_FLOWS_DIR=""))
    assert s.publish_port == 8080 and s.max_concurrency == 1
    assert s.publish_flows is None and s.flows_dir is None


@pytest.mark.parametrize(
    "var,lo,hi",
    [
        ("GS_PUBLISH_PORT", 1, 65535),
        ("GS_MAX_CONCURRENCY", 1, 64),
        ("GS_MAX_BODY_BYTES", 1024, 1048576),
        ("GS_CALL_TIMEOUT", 1, 900),
        ("GS_SHUTDOWN_GRACE", 1, 120),
        ("GS_PORT", 1, 65535),
    ],
)
def test_range_edges(var: str, lo: int, hi: int) -> None:
    load_settings(env(**{var: str(lo)}))
    load_settings(env(**{var: str(hi)}))
    fails(env(**{var: str(lo - 1)}), var)
    fails(env(**{var: str(hi + 1)}), var)
    fails(env(**{var: "12x"}), var)


@pytest.mark.parametrize("bad", ["nan", "inf", "-5", "1e3", " 5", "5 ", ""])
def test_call_timeout_rejects_non_finite_and_odd_text(bad: str) -> None:
    if bad == "":
        assert load_settings(env(GS_CALL_TIMEOUT=bad)).call_timeout == 180.0
    else:
        fails(env(GS_CALL_TIMEOUT=bad), "GS_CALL_TIMEOUT")


def test_call_timeout_fraction() -> None:
    assert load_settings(env(GS_CALL_TIMEOUT="2.5")).call_timeout == 2.5


def test_bad_transport_and_booleans() -> None:
    fails(env(GS_TRANSPORT="tcp"), "GS_TRANSPORT")
    fails(env(GS_ENABLE_DOCS="yes"), "GS_ENABLE_DOCS")
    fails(env(GS_AUTH_DISABLED="TRUE"), "GS_AUTH_DISABLED")
    assert load_settings(env(GS_ENABLE_DOCS="true")).enable_docs is True


def test_missing_connector_settings_ignore_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GS_HOST", "from-process.invalid")
    monkeypatch.setenv("GS_S3270_BINARY", "/from/process")
    e = env()
    del e["GS_HOST"]
    fails(e, "GS_HOST")
    e = env()
    del e["GS_S3270_BINARY"]
    fails(e, "GS_S3270_BINARY")


def test_api_key_rules() -> None:
    e = env()
    del e["GS_API_KEY"]
    fails(e, "GS_API_KEY")
    fails(env(GS_API_KEY="short-key-15chr"), "GS_API_KEY")
    assert load_settings(env(GS_API_KEY="k" * 16)).api_key == "k" * 16


def test_auth_disabled_needs_loopback() -> None:
    e = env(GS_AUTH_DISABLED="true", GS_PUBLISH_HOST="0.0.0.0")
    del e["GS_API_KEY"]
    fails(e, "GS_AUTH_DISABLED", "GS_PUBLISH_HOST")
    for host in ("127.0.0.1", "127.9.9.9", "::1", "[::1]", "localhost"):
        e = env(GS_AUTH_DISABLED="true", GS_PUBLISH_HOST=host)
        del e["GS_API_KEY"]
        assert load_settings(e).auth_disabled is True


def test_stdio_ignores_key_and_auth_rules() -> None:
    e = env(GS_TRANSPORT="stdio", GS_API_KEY="x", GS_AUTH_DISABLED="true", GS_PUBLISH_HOST="0.0.0.0")
    s = load_settings(e)
    assert s.transport == "stdio" and s.api_key is None
    e = env(GS_TRANSPORT="stdio")
    del e["GS_API_KEY"]
    load_settings(e)


def test_repr_hides_key() -> None:
    assert KEY not in repr(load_settings(env()))


def test_is_loopback_host() -> None:
    assert not is_loopback_host("example.com") and not is_loopback_host("10.0.0.1")


# --- parse_publish_list -------------------------------------------------

def test_publish_list_unset_and_empty() -> None:
    assert parse_publish_list(None) is None
    assert parse_publish_list("") is None


def test_publish_list_valid_and_trimmed() -> None:
    assert parse_publish_list("tk5-system-info") == ("tk5-system-info",)
    assert parse_publish_list(" a , b\t,c ") == ("a", "b", "c")
    assert parse_publish_list("b,a") == ("b", "a")  # list order kept; registry orders later


@pytest.mark.parametrize("text", ["a,", ",a", "a,,b", " ", "  ,  ", ","])
def test_publish_list_empty_item(text: str) -> None:
    with pytest.raises(StartupError) as ei:
        parse_publish_list(text)
    assert "GS_PUBLISH_FLOWS" in str(ei.value) and "empty_item" in str(ei.value)


def test_publish_list_duplicate() -> None:
    with pytest.raises(StartupError) as ei:
        parse_publish_list("a, b ,a")
    m = str(ei.value)
    assert "GS_PUBLISH_FLOWS" in m and "duplicate_name" in m and "a" in m


def test_publish_list_check_order_empty_before_duplicate() -> None:
    with pytest.raises(StartupError) as ei:
        parse_publish_list("a,a,")
    assert "empty_item" in str(ei.value)


def test_publish_list_names_are_case_sensitive() -> None:
    assert parse_publish_list("A,a") == ("A", "a")


def test_load_settings_keeps_raw_publish_flows_including_whitespace_only() -> None:
    assert load_settings(env(GS_PUBLISH_FLOWS="a,b")).publish_flows == "a,b"
    s = load_settings(env(GS_PUBLISH_FLOWS=" "))
    assert s.publish_flows == " "
    with pytest.raises(StartupError):
        parse_publish_list(s.publish_flows)


_NAME = st.from_regex(r"[a-z0-9_-]{1,12}", fullmatch=True)


@given(st.lists(_NAME, min_size=1, max_size=6, unique=True), st.text(alphabet=" \t", max_size=2))
@hsettings(max_examples=100, deadline=None)
def test_publish_list_roundtrip(names: list[str], pad: str) -> None:
    # Feature: publisher, publish list parse: padded unique names come back trimmed, in order.
    text = ",".join(pad + n + pad for n in names)
    assert parse_publish_list(text) == tuple(names)
