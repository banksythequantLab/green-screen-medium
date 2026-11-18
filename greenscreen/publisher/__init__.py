"""Publisher: every Flow as an MCP tool and a REST endpoint.

This module imports none of ``mcp``, ``fastapi``, ``starlette`` or ``uvicorn`` at
import time. The public names are exported lazily (PEP 562).
"""
from __future__ import annotations

from typing import Any

__all__ = ["build_app", "prepare", "Settings", "StartupError"]

_LAZY = {
    "build_app": "greenscreen.publisher.app",
    "prepare": "greenscreen.publisher.app",
    "Settings": "greenscreen.publisher.config",
    "StartupError": "greenscreen.publisher.config",
}


def __getattr__(name: str) -> Any:
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    return getattr(importlib.import_module(module), name)
