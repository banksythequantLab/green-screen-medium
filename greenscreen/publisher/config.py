"""Publisher settings: environment parsing only (no I/O, no session, no port).

Every ``StartupError`` message holds a variable name and a rule name, never a
value of any variable.  ``parse_bindings`` is added by a later task.
"""
from __future__ import annotations

import dataclasses
import ipaddress
import math
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from greenscreen.connector.config import ConnectorConfig
from greenscreen.connector.exceptions import ConfigurationError
from greenscreen.flow import Flow, FlowInputError
from greenscreen.flow.inputs import prepare_inputs
from greenscreen.flow.model import InputSpec
from greenscreen.publisher.vault import BoundValues

__all__ = [
    "StartupError",
    "Settings",
    "load_settings",
    "parse_publish_list",
    "parse_bindings",
    "is_loopback_host",
    "AskSettings",
    "REASONING_EFFORTS",
    "is_ask_loopback_host",
]

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
    enable_console: bool = False
    ask: AskSettings | None = None

    def __repr__(self) -> str:
        return (
            f"Settings(transport={self.transport!r}, publish_host={self.publish_host!r}, "
            f"publish_port={self.publish_port})"
        )


_ASK_LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})
_MODEL_RE = re.compile(r"[A-Za-z0-9._:/@-]{1,100}")
_KEY_RE = re.compile(r"[\x21-\x7e]{1,512}")  # printable ASCII, no space
_URL_CHARS_RE = re.compile(r"[\x21-\x7e]+")
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high")


def is_ask_loopback_host(host: str) -> bool:
    """True only for ``127.0.0.1``, ``::1`` and ``localhost`` (brackets stripped)."""
    h = host.strip()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h.lower() in _ASK_LOOPBACK


@dataclass(frozen=True, slots=True)
class AskSettings:
    base_url: str  # no trailing slash; the adapter appends /chat/completions
    model: str
    llm_api_key: str | None = field(repr=False)
    reasoning_effort: str | None  # one of REASONING_EFFORTS or None; not secret
    max_tool_calls: int
    max_turns: int
    timeout_seconds: float
    model_timeout_seconds: float
    flows: tuple[str, ...] | None
    max_question_chars: int
    max_answer_chars: int
    max_result_chars: int
    daily_limit: int

    def __repr__(self) -> str:
        return "AskSettings(configured)"  # no URL, no model, no key, no effort


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
    enable_console = _bool(environ, "GS_ENABLE_CONSOLE")
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

    enable_ask = _bool(environ, "GS_ENABLE_ASK")  # always parsed
    ask = _load_ask(environ) if enable_ask and transport == "http" else None

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
        enable_console=enable_console,
        ask=ask,
    )


def _load_base_url(environ: Mapping[str, str]) -> tuple[str, bool]:
    """Validate ``GS_LLM_BASE_URL``. Returns the rebuilt URL and whether the host is loopback."""
    name = "GS_LLM_BASE_URL"
    text = _get(environ, name)
    if text is None:
        raise StartupError(f"{name}: missing")
    if _URL_CHARS_RE.fullmatch(text) is None:
        raise StartupError(f"{name}: not_a_url")
    try:
        parts = urlsplit(text)
        parts.port  # noqa: B018 - raises ValueError for a bad port
        host = parts.hostname
    except ValueError:
        raise StartupError(f"{name}: not_a_url") from None
    if parts.scheme not in ("http", "https") or not host:
        raise StartupError(f"{name}: not_a_url")
    if "@" in parts.netloc:
        raise StartupError(f"{name}: credentials_in_url")
    if "?" in text or "#" in text:
        raise StartupError(f"{name}: query_in_url")
    loopback = is_ask_loopback_host(host)
    if parts.scheme == "http" and not loopback:
        raise StartupError(f"{name}: https_required")
    return f"{parts.scheme}://{parts.netloc}{parts.path.rstrip('/')}", loopback


def _load_reasoning_effort(environ: Mapping[str, str]) -> str | None:
    text = _get(environ, "GS_LLM_REASONING_EFFORT")
    if text is None:
        return None
    if text not in REASONING_EFFORTS:  # exact, case-sensitive, no trimming
        raise StartupError(
            f"GS_LLM_REASONING_EFFORT: not_allowed ({', '.join(REASONING_EFFORTS)})"
        )
    return text


def _load_ask(environ: Mapping[str, str]) -> AskSettings:
    """Read the Ask variables in the fixed order of the design. Values never reach a message."""
    base_url, loopback = _load_base_url(environ)

    model = _get(environ, "GS_LLM_MODEL")
    if model is None:
        raise StartupError("GS_LLM_MODEL: missing")
    if _MODEL_RE.fullmatch(model) is None:
        raise StartupError("GS_LLM_MODEL: invalid_model_name")

    key = _get(environ, "GS_LLM_API_KEY")
    if key is None:
        if not loopback:
            raise StartupError("GS_LLM_API_KEY: missing")
    elif _KEY_RE.fullmatch(key) is None:
        raise StartupError("GS_LLM_API_KEY: invalid_key")

    effort = _load_reasoning_effort(environ)

    max_tool_calls = _int(environ, "GS_ASK_MAX_TOOL_CALLS", 6, 1, 20)
    max_turns = _int(environ, "GS_ASK_MAX_TURNS", 8, 1, 30)
    timeout = _seconds(environ, "GS_ASK_TIMEOUT_SECONDS", 90.0, 20.0, 95.0)
    model_timeout = _seconds(environ, "GS_ASK_MODEL_TIMEOUT_SECONDS", 25.0, 1.0, 60.0)
    max_question = _int(environ, "GS_ASK_MAX_QUESTION_CHARS", 500, 1, 2000)
    max_answer = _int(environ, "GS_ASK_MAX_ANSWER_CHARS", 2000, 100, 20000)
    max_result = _int(environ, "GS_ASK_MAX_RESULT_CHARS", 4000, 200, 20000)
    daily = _int(environ, "GS_ASK_DAILY_LIMIT", 100, 1, 100000)
    if 2 * model_timeout > timeout:
        raise StartupError("GS_ASK_MODEL_TIMEOUT_SECONDS: model_timeout_too_long")
    flows = _parse_name_list(_get(environ, "GS_ASK_FLOWS"), "GS_ASK_FLOWS")

    return AskSettings(
        base_url=base_url,
        model=model,
        llm_api_key=key,
        reasoning_effort=effort,
        max_tool_calls=max_tool_calls,
        max_turns=max_turns,
        timeout_seconds=timeout,
        model_timeout_seconds=model_timeout,
        flows=flows,
        max_question_chars=max_question,
        max_answer_chars=max_answer,
        max_result_chars=max_result,
        daily_limit=daily,
    )


def _parse_name_list(text: str | None, variable: str) -> tuple[str, ...] | None:
    """Shared comma-list parser: ``empty_item``, then ``duplicate_name``."""
    if not text:
        return None
    items = [item.strip() for item in text.split(",")]
    if any(not item for item in items):
        raise StartupError(f"{variable}: empty_item")
    seen: set[str] = set()
    for item in items:
        if item in seen:
            raise StartupError(f"{variable}: duplicate_name ({item})")
        seen.add(item)
    return tuple(items)


def parse_publish_list(text: str | None) -> tuple[str, ...] | None:
    """Parse ``GS_PUBLISH_FLOWS``. ``None`` means publish every Loaded_Flow.

    Checks run in this order and the first failure is reported: ``empty_item``,
    then ``duplicate_name``.  ``unknown_flow`` needs the Loaded_Flows and is
    checked by ``select_published``.
    """
    return _parse_name_list(text, "GS_PUBLISH_FLOWS")


_BIND_PREFIX = "GS_BIND_"
_INT_TEXT_RE = re.compile(r"-?[0-9]+")


@dataclass(frozen=True, slots=True)
class _OneInput:
    """Stands in for a ``Flow`` in ``prepare_inputs``, which reads only ``inputs``."""

    inputs: tuple[InputSpec, ...]


def _norm(name: str) -> str:
    return name.upper().replace("-", "_")


def _store_value(
    environ: Mapping[str, str],
    variable: str,
    spec: InputSpec,
    store: dict[str, dict[str, str | int]],
    flow_name: str,
) -> str | None:
    """Parse and validate one Bound_Value into ``store``. Returns an error text or ``None``.

    The value is never put into the returned text or an exception.
    """
    text = environ[variable]
    parsed: str | int
    if spec.type == "int":
        if _INT_TEXT_RE.fullmatch(text) is None or len(text) > spec.max_length:
            return f"{variable}: value_invalid"
        try:
            parsed = int(text)
        except ValueError:
            return f"{variable}: value_invalid"
    else:
        parsed = text
    rule: str | None = None
    try:
        prepare_inputs(
            _OneInput((dataclasses.replace(spec, required=True),)),  # type: ignore[arg-type]
            {spec.name: parsed},
        )
    except FlowInputError as exc:
        rule = str(exc).rsplit(" violates ", 1)[-1]
    if rule is not None:
        return f"{variable}: {rule}"
    store.setdefault(flow_name, {})[spec.name] = parsed
    return None


def _bind_error(
    environ: Mapping[str, str],
    loaded: Mapping[str, Flow],
    published: Collection[str],
    store: dict[str, dict[str, str | int]],
) -> str | None:
    names = sorted(n for n, v in environ.items() if n.startswith(_BIND_PREFIX) and v != "")
    if not names:
        return None

    split: list[tuple[str, str, str]] = []
    for name in names:
        rest = name[len(_BIND_PREFIX):]
        i = rest.find("__")
        if i <= 0 or rest[i + 2:] == "":
            return f"{name}: name_format"
        split.append((name, rest[:i], rest[i + 2:]))

    for flow_name in loaded:
        if flow_name in published:
            norm = _norm(flow_name)
            if "__" in norm or norm.endswith("_"):
                return f"{flow_name}: ambiguous_name"

    for name, flow_part, input_part in split:
        flows = [f for f in loaded.values() if _norm(f.name) == flow_part]
        if not flows:
            return f"{name}: unknown_flow"
        if len(flows) > 1:
            return f"{_BIND_PREFIX}{flow_part}__: ambiguous_name"
        flow = flows[0]
        if flow.name not in published:
            return f"{name}: flow_not_published"
        specs = [s for s in flow.inputs if _norm(s.name) == input_part]
        if not specs:
            return f"{name}: unknown_input"
        if len(specs) > 1:
            return f"{_BIND_PREFIX}{flow_part}__{input_part}: ambiguous_name"
        spec = specs[0]
        error = _store_value(environ, name, spec, store, flow.name)
        if error is not None:
            return error
    return None


def parse_bindings(
    environ: Mapping[str, str],
    loaded: Mapping[str, Flow],
    published: Collection[str],
) -> BoundValues:
    """Parse the ``GS_BIND_<flow>__<input>`` variables (Requirement 22).

    ``loaded`` holds every Loaded_Flow, ``published`` the names the Publish_List
    selected. Every ``StartupError`` names a variable, family or Flow and a rule,
    never a value, and is raised with no value left in this frame.
    """
    store: dict[str, dict[str, str | int]] = {}
    error = _bind_error(environ, loaded, published, store)
    if error is not None:
        for inner in store.values():
            inner.clear()
        store.clear()
        environ = {}  # drop the reference to the environment mapping before raising
        raise StartupError(error) from None
    return BoundValues(store)
