"""Publisher settings: environment parsing only (no I/O, no session, no port).

Every ``StartupError`` message holds a variable name and a rule name, never a
value of any variable.  ``parse_bindings`` is added by a later task.
"""
from __future__ import annotations

import ipaddress
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.exceptions import ConfigurationError

__all__ = ["StartupError", "Settings", "load_settings", "parse_publish_list", "is_loopback_host"]

_INT_RE = re.compile(r"[0-9]+")
_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_API_KEY_MIN = 16
_CONNECTOR_PARAMS = {"binary": "GS_S3270_BINARY", "host": "GS_HOST", "port": "GS_PORT"}


class StartupError(Exception):
    """A startup check failed. The message holds names and rules, never values."""


@dataclass(frozen=True, slots=True)
class Settings:
    connector: ConnectorConfig
    publish_host: str
    publish_port: int
    transport: str  # "http" | "stdio"
    api_key: str | None
    auth_disabled: bool
    max_concurrency: int
    call_timeout: float
    max_body_bytes: int
    shutdown_grace: float
    enable_docs: bool
    flows_dir: Path | None
    publish_flows: str | None  # raw GS_PUBLISH_FLOWS; None when unset or zero-length

    def __repr__(self) -> str:
        return (
            f"Settings(transport={self.transport!r}, publish_host={self.publish_host!r}, "
            f"publish_port={self.publish_port})"
        )


def _get(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    return value if value else None  # empty is unset


def _int(environ: Mapping[str, str], name: str, default: int, lo: int, hi: int) -> int:
    text = _get(environ, name)
    if text is None:
        return default
    if _INT_RE.fullmatch(text) is None:
        raise StartupError(f"{name}: not_an_integer")
    value = int(text)
    if not lo <= value <= hi:
        raise StartupError(f"{name}: out_of_range ({lo} to {hi})")
    return value


def _seconds(environ: Mapping[str, str], name: str, default: float, lo: float, hi: float) -> float:
    text = _get(environ, name)
    if text is None:
        return default
    if _NUM_RE.fullmatch(text) is None:
        raise StartupError(f"{name}: not_a_number")
    value = float(text)
    if not math.isfinite(value) or not lo <= value <= hi:
        raise StartupError(f"{name}: out_of_range ({lo:g} to {hi:g})")
    return value


def _bool(environ: Mapping[str, str], name: str) -> bool:
    text = _get(environ, name)
    if text is None:
        return False
    if text == "true":
        return True
    if text == "false":
        return False
    raise StartupError(f"{name}: not_a_boolean (true or false)")


def is_loopback_host(host: str) -> bool:
    """True for ``localhost`` or a loopback IP address, with or without brackets."""
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    if h.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def _connector(environ: Mapping[str, str]) -> ConnectorConfig:
    # ConnectorConfig falls back to os.environ for empty fields, so a missing
    # value is rejected here and the injected mapping stays the only source.
    binary = _get(environ, "GS_S3270_BINARY")
    if binary is None:
        raise StartupError("GS_S3270_BINARY: missing")
    host = _get(environ, "GS_HOST")
    if host is None:
        raise StartupError("GS_HOST: missing")
    port = _int(environ, "GS_PORT", 23, 1, 65535)
    try:
        return ConnectorConfig(binary=binary, host=host, port=port)
    except ConfigurationError as exc:
        name = _CONNECTOR_PARAMS.get(exc.parameter_name or "", "GS_HOST")
        # The exception text can hold a value; only the parameter name is used.
        raise StartupError(f"{name}: missing or invalid") from None


def load_settings(environ: Mapping[str, str]) -> Settings:
    """Read the Publisher variables of Requirement 15.1 once from ``environ``."""
    connector = _connector(environ)

    transport = _get(environ, "GS_TRANSPORT") or "http"
    if transport not in ("http", "stdio"):
        raise StartupError("GS_TRANSPORT: must_be_http_or_stdio")

    publish_host = _get(environ, "GS_PUBLISH_HOST") or "127.0.0.1"
    publish_port = _int(environ, "GS_PUBLISH_PORT", 8080, 1, 65535)
    max_concurrency = _int(environ, "GS_MAX_CONCURRENCY", 1, 1, 64)
    call_timeout = _seconds(environ, "GS_CALL_TIMEOUT", 180.0, 1.0, 900.0)
    max_body_bytes = _int(environ, "GS_MAX_BODY_BYTES", 65536, 1024, 1048576)
    shutdown_grace = _seconds(environ, "GS_SHUTDOWN_GRACE", 10.0, 1.0, 120.0)
    auth_disabled = _bool(environ, "GS_AUTH_DISABLED")
    enable_docs = _bool(environ, "GS_ENABLE_DOCS")
    flows_dir_text = _get(environ, "GS_FLOWS_DIR")
    api_key = _get(environ, "GS_API_KEY")

    if transport == "http":
        if auth_disabled:
            if not is_loopback_host(publish_host):
                raise StartupError(
                    "GS_AUTH_DISABLED: requires_loopback GS_PUBLISH_HOST"
                )
        elif api_key is None or len(api_key) < _API_KEY_MIN:
            raise StartupError(
                f"GS_API_KEY: required_min_length_{_API_KEY_MIN}"
            )
    else:
        api_key = None  # stdio ignores the key (Requirement 13.10)

    return Settings(
        connector=connector,
        publish_host=publish_host,
        publish_port=publish_port,
        transport=transport,
        api_key=api_key,
        auth_disabled=auth_disabled,
        max_concurrency=max_concurrency,
        call_timeout=call_timeout,
        max_body_bytes=max_body_bytes,
        shutdown_grace=shutdown_grace,
        enable_docs=enable_docs,
        flows_dir=Path(flows_dir_text) if flows_dir_text else None,
        publish_flows=_get(environ, "GS_PUBLISH_FLOWS"),
    )


def parse_publish_list(text: str | None) -> tuple[str, ...] | None:
    """Parse ``GS_PUBLISH_FLOWS``. ``None`` means publish every Loaded_Flow.

    Checks run in this order and the first failure is reported: ``empty_item``,
    then ``duplicate_name``.  ``unknown_flow`` needs the Loaded_Flows and is
    checked by ``select_published``.
    """
    if not text:
        return None
    items = [item.strip() for item in text.split(",")]
    if any(not item for item in items):
        raise StartupError("GS_PUBLISH_FLOWS: empty_item")
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise StartupError(f"GS_PUBLISH_FLOWS: duplicate_name ({item})")
        seen.add(item)
    return tuple(items)
