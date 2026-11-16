"""Unit tests for ConnectorConfig. Validates Requirements 1.1, 1.2, 1.3, 1.4, 7.1-7.6."""
import dataclasses

import pytest

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("GS_S3270_BINARY", "GS_HOST", "GS_PORT"):
        monkeypatch.delenv(name, raising=False)


def make(**kw):
    base = {"binary": "/usr/bin/s3270", "host": "example.invalid"}
    base.update(kw)
    return ConnectorConfig(**base)


def test_all_fields_explicit():
    c = ConnectorConfig(binary="b", host="h", port=2323, model="3278-4", default_timeout=5.0)
    assert (c.binary, c.host, c.port, c.model, c.default_timeout) == ("b", "h", 2323, "3278-4", 5.0)


def test_defaults():
    c = make()
    assert c.model == "3279-2"
    assert c.default_timeout == 30.0
    assert c.port == 23


def test_env_fallbacks(monkeypatch):
    monkeypatch.setenv("GS_S3270_BINARY", "envbin")
    monkeypatch.setenv("GS_HOST", "envhost")
    monkeypatch.setenv("GS_PORT", "3270")
    c = ConnectorConfig()
    assert (c.binary, c.host, c.port) == ("envbin", "envhost", 3270)


def test_explicit_args_win_over_env(monkeypatch):
    monkeypatch.setenv("GS_S3270_BINARY", "envbin")
    monkeypatch.setenv("GS_HOST", "envhost")
    monkeypatch.setenv("GS_PORT", "3270")
    c = ConnectorConfig(binary="b", host="h", port=992)
    assert (c.binary, c.host, c.port) == ("b", "h", 992)


def test_empty_string_args_fall_back_to_env(monkeypatch):
    monkeypatch.setenv("GS_S3270_BINARY", "envbin")
    monkeypatch.setenv("GS_HOST", "envhost")
    c = ConnectorConfig(binary="", host="")
    assert (c.binary, c.host) == ("envbin", "envhost")


@pytest.mark.parametrize("kw,param", [
    ({"binary": ""}, "binary"),
    ({"host": ""}, "host"),
])
def test_missing_required(kw, param):
    with pytest.raises(ConfigurationError) as ei:
        make(**kw)
    assert ei.value.parameter_name == param
    assert param in str(ei.value)


@pytest.mark.parametrize("port", [0, 65536])
def test_invalid_explicit_port(port):
    with pytest.raises(ConfigurationError) as ei:
        make(port=port)
    assert ei.value.parameter_name == "port"
    assert "port" in str(ei.value).lower()


def test_explicit_port_minus_one_raises(monkeypatch):
    monkeypatch.setenv("GS_PORT", "3270")
    with pytest.raises(ConfigurationError) as ei:
        ConnectorConfig(binary="b", host="h", port=-1)
    assert ei.value.parameter_name == "port"


def test_explicit_none_port_uses_default():
    assert make(port=None).port == 23


def test_explicit_none_port_uses_env(monkeypatch):
    monkeypatch.setenv("GS_PORT", "3270")
    assert make(port=None).port == 3270


def test_empty_env_port_ignored(monkeypatch):
    monkeypatch.setenv("GS_PORT", "")
    assert make().port == 23


@pytest.mark.parametrize("port", [True, False, "3270", 23.0])
def test_non_int_explicit_port_rejected(port):
    with pytest.raises(ConfigurationError) as ei:
        make(port=port)
    assert ei.value.parameter_name == "port"


@pytest.mark.parametrize("value", ["0", "-1", "65536"])
def test_out_of_range_env_port(monkeypatch, value):
    monkeypatch.setenv("GS_PORT", value)
    with pytest.raises(ConfigurationError) as ei:
        make()
    assert ei.value.parameter_name == "port"


def test_non_integer_env_port(monkeypatch):
    monkeypatch.setenv("GS_PORT", "abc")
    with pytest.raises(ConfigurationError) as ei:
        make()
    assert ei.value.parameter_name == "port"
    assert "GS_PORT" in str(ei.value)


@pytest.mark.parametrize("port", [1, 65535])
def test_boundary_ports_accepted(port):
    assert make(port=port).port == port


@pytest.mark.parametrize("t", [0.99, 3600.01])
def test_invalid_timeout(t):
    with pytest.raises(ConfigurationError) as ei:
        make(default_timeout=t)
    assert ei.value.parameter_name == "default_timeout"
    assert "default_timeout" in str(ei.value)


@pytest.mark.parametrize("t", [1.0, 3600.0])
def test_boundary_timeouts_accepted(t):
    assert make(default_timeout=t).default_timeout == t


def test_empty_model_rejected():
    with pytest.raises(ConfigurationError) as ei:
        make(model="")
    assert ei.value.parameter_name == "model"
    assert "model" in str(ei.value).lower()


def test_no_credential_fields():
    names = {f.name for f in dataclasses.fields(ConnectorConfig)}
    assert not {"username", "password", "user", "passwd"} & names


def test_credentials_not_read_from_env(monkeypatch):
    monkeypatch.setenv("GS_USERNAME", "u")
    monkeypatch.setenv("GS_PASSWORD", "p")
    c = make()
    assert "u" not in vars(c).values() and "p" not in vars(c).values()
    assert not hasattr(c, "username") and not hasattr(c, "password")
