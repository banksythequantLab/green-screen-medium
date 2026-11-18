"""The CLI never runs uvicorn below INFO (task 6.1 finding from 5.2).

``Config(log_level="trace")`` overrides the logger clamp and logs the ASGI scope
(path and query string), so the level is a fixed constant and no environment
variable can lower it.
"""
from __future__ import annotations

import logging

import pytest

pytest.importorskip("uvicorn")

from greenscreen.publisher import cli  # noqa: E402


async def _app(scope, receive, send):  # pragma: no cover - never served
    return None


def test_uvicorn_config_is_pinned_at_info(monkeypatch):
    for name in ("GS_LOG_LEVEL", "LOG_LEVEL", "UVICORN_LOG_LEVEL"):
        monkeypatch.setenv(name, "trace")
    config = cli.build_uvicorn_config(_app, "127.0.0.1", 8080, 10.0)
    assert cli.UVICORN_LOG_LEVEL == "info"
    assert config.log_level == "info"
    assert config.log_config is None
    assert config.access_log is False
    assert config.timeout_graceful_shutdown == 10
    assert logging.getLogger("uvicorn.error").level >= logging.INFO
