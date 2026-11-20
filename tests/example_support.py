"""A publisher over the six bundled Published_Tools, for the ``x-ask-example`` tests.

Spec polish, task 6.2; task 7.2 reuses it. ``ASK_ENV`` publishes one Flow
(``tk5-system-info``), so this module builds its own environment: ``GS_PUBLISH_FLOWS`` is
the six names and the ``userid`` and ``password`` of each are bound. The bound values are
generated at run time, never real, never printed, never written anywhere.

    ``SIX``                   the six Flow names, in the order of the bundled files
    ``six_tool_environment``  the whole environment dict (for ``prepare``)
    ``six_tool_document``     ``(document, app)``: ``/openapi.json`` as served, and the AskApp
"""
from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Mapping

from tests.ask_support import _BOUND_VARIABLE, _PLACEHOLDER_KEY, ASK_ENV, AskApp, build_ask_app
from tests.console_support import call_scope

SIX: tuple[str, ...] = (
    "tk5-system-info",
    "tk5-time",
    "tk5-list-datasets",
    "tk5-dataset-info",
    "tk5-library-members",
    "tk5-job-status",
)

# One pair for the process: 8 hex characters each, the Input maximum.
_USERID = "u" + secrets.token_hex(3)
_PASSWORD = secrets.token_hex(4)


def _stem(name: str) -> str:
    return "GS_BIND_" + name.upper().replace("-", "_")


def six_tool_overrides(env: Mapping[str, str] | None) -> dict[str, str]:
    bound: dict[str, str] = {}
    for name in SIX:
        bound[f"{_stem(name)}__USERID"] = _USERID
        bound[f"{_stem(name)}__PASSWORD"] = _PASSWORD
    return {"GS_PUBLISH_FLOWS": ",".join(SIX), **bound, **(env or {})}


def six_tool_environment(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment ``build_ask_app`` hands to ``prepare`` for the six tools."""
    return {
        **ASK_ENV,
        _BOUND_VARIABLE: _PASSWORD,
        **six_tool_overrides(env),
        "GS_API_KEY": _PLACEHOLDER_KEY,
    }


def fetch_document(app: AskApp) -> tuple[int, bytes]:
    """GET /openapi.json through the whole ASGI stack."""
    headers = {"X-API-Key": app.api_key}
    status, _, body = asyncio.run(call_scope(app.app.asgi, "GET", "/openapi.json", headers))
    return status, body


def six_tool_document(env: Mapping[str, str] | None = None) -> tuple[dict, AskApp]:
    """The served ``/openapi.json`` and the app, with the six tools published.

    ``env`` is merged over the six-tool environment (``GS_ENABLE_ASK``, ``GS_ASK_FLOWS``).
    """
    app = build_ask_app(six_tool_overrides(env))
    status, raw = fetch_document(app)
    assert status == 200
    return json.loads(raw), app
