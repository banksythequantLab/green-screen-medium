"""Shared test helpers for the console tests (spec console, task 2.8).

Nothing here starts a subprocess, opens a socket or writes a file. The API key is
generated per call and never written anywhere. Helpers of ``tests/publisher_support.py``
and ``tests/property/_publisher_strategies.py`` are reused, not copied; use their
``LogCapture``, ``leak_forms`` and ``rest_client`` next to the ones below.

Contents
    ``ASSET_DIR``, ``ASSET_FILES``  the installed package directory and the six file names
    ``EXPECTED_PAIRS``              the six exempt ``(method, path)`` pairs, spelled out here
    ``build_console_app``           a ``ConsoleApp`` (app, key, host) over the Fake_Host
    ``call_scope``                  a raw ASGI request driver
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import greenscreen.publisher.console as _console_package
from greenscreen.publisher.app import PublisherApp, build_app, prepare
from tests.flow_support import FakeClock
from tests.publisher_support import FakeHost, system_info_states

FLOW = "tk5-system-info"

# The packaged assets, read from the installed package path (not from a copy).
ASSET_DIR: Path = Path(_console_package.__file__).resolve().parent
ASSET_FILES: tuple[str, ...] = (
    "index.html",
    "console.css",
    "console.js",
    "snippets.js",
    "codes.json",
    "favicon.svg",
)

# The six exact pairs the console exempts from the key check. Written out on purpose:
# a test that imported them from the package would not notice a change there.
EXPECTED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/"),
        ("GET", "/console/console.css"),
        ("GET", "/console/console.js"),
        ("GET", "/console/snippets.js"),
        ("GET", "/console/codes.json"),
        ("GET", "/console/favicon.svg"),
    }
)

BASE_ENV: dict[str, str] = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_PUBLISH_FLOWS": FLOW,
}

# ``prepare`` is called with this stand-in key so that its result can be cached. The
# generated key replaces it in the settings of each app (see ``build_console_app``).
_PLACEHOLDER_KEY = "k" * 16


@dataclass(frozen=True)
class ConsoleApp:
    """An app, the API key it accepts and the Fake_Host behind it."""

    app: PublisherApp
    api_key: str
    host: FakeHost


@functools.lru_cache(maxsize=16)
def _prepared(items: tuple[tuple[str, str], ...]):
    return prepare(dict(items))


def build_console_app(
    env: Mapping[str, str] | None = None, console: bool = True
) -> ConsoleApp:
    """Build the publisher app over a Fake_Host.

    ``env`` is merged over a minimal environment (one published Flow, no host data).
    ``console=True`` sets ``GS_ENABLE_CONSOLE=true``; ``False`` removes the variable, so
    an ``env`` that names it is overridden. ``GS_API_KEY`` is replaced by a key generated
    for this call and returned in the result; an ``env`` value for it is ignored.
    ``prepare`` runs once per distinct environment (``functools.lru_cache``). Its result
    is immutable, so each call builds a new app on a copy whose settings carry the
    generated key.
    """
    merged = {**BASE_ENV, **(env or {}), "GS_API_KEY": _PLACEHOLDER_KEY}
    if console:
        merged["GS_ENABLE_CONSOLE"] = "true"
    else:
        merged.pop("GS_ENABLE_CONSOLE", None)
    prepared = _prepared(tuple(sorted(merged.items())))
    api_key = secrets.token_urlsafe(24)  # runtime only, 32 printable characters
    settings = prepared.settings
    if settings.transport != "stdio":
        settings = dataclasses.replace(settings, api_key=api_key)
    prepared = dataclasses.replace(prepared, settings=settings)
    host = FakeHost(system_info_states())
    app = build_app(prepared, session_factory=host, clock=FakeClock(), poll_interval=0.01)
    return ConsoleApp(app, api_key, host)


def _header_list(headers: Mapping[str, str] | Sequence[tuple[Any, Any]] | None):
    if headers is None:
        return []
    pairs = headers.items() if isinstance(headers, Mapping) else headers
    out: list[tuple[bytes, bytes]] = []
    for name, value in pairs:
        n = name.encode("latin-1") if isinstance(name, str) else bytes(name)
        v = value.encode("latin-1") if isinstance(value, str) else bytes(value)
        out.append((n.lower(), v))
    return out


async def call_scope(
    asgi: Any,
    method: str,
    path: str,
    headers: Mapping[str, str] | Sequence[tuple[Any, Any]] | None = None,
    *,
    body: bytes = b"",
    timeout: float = 20.0,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    """Drive ``asgi`` with one raw HTTP scope and return ``(status, headers, body)``.

    ``path`` goes into ``scope["path"]`` exactly as given (and ``raw_path``, encoded),
    so the middleware sees the string a test generated, with no client-side
    normalisation. ``headers`` is a mapping or a sequence of pairs (str or bytes);
    names are lower-cased, repeats are kept. No ``Host`` header is added. Response
    header names are returned lower-case, in order.
    """
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    out: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        out.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "root_path": "",
        "headers": _header_list(headers),
        "server": ("test", 80),
        "client": ("127.0.0.1", 50000),
    }
    await asyncio.wait_for(asgi(scope, receive, send), timeout)
    start = next(m for m in out if m["type"] == "http.response.start")
    data = b"".join(m.get("body", b"") for m in out if m["type"] == "http.response.body")
    return start["status"], [(k.lower(), v) for k, v in start["headers"]], data
