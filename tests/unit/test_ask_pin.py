"""Pins on the undeclared ``httpx2`` dependency and the in-process MCP client (spec ask, task 2.11).

``httpx2`` is not in ``pyproject.toml``: it arrives as a runtime requirement of ``mcp``
(Decision 6). These tests fail loudly if that stops being true, or if a call the adapter
relies on changes. No real network; keys are generated per test.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.metadata
import inspect
import json
import logging
import re
import secrets
from pathlib import Path

import httpx2
import pytest
from mcp import Client

from greenscreen.publisher.ask.openai_compat import OpenAIAdapter
from greenscreen.publisher.mcp_server import build_mcp_server
from greenscreen.publisher.calls import CallService, Limiter
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.vault import BoundValues
from greenscreen.recognizer import load_bundled_signatures
from tests.ask_support import AskFakeClock, ask_post, build_ask_app, no_network  # noqa: F401  (autouse)
from tests.flow_support import FakeClock
from tests.publisher_support import MINI, FakeHost, mini_states

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "greenscreen"
MODES = ["legacy", "auto"]


# --------------------------------------------------------------------------
# httpx2 pins
# --------------------------------------------------------------------------

def test_mcp_requires_httpx2_without_an_extra_marker():
    requirements = [r for r in (importlib.metadata.requires("mcp") or []) if re.match(r"httpx2\b", r, re.I)]
    assert len(requirements) == 1, requirements
    spec, _, marker = requirements[0].partition(";")
    assert "extra" not in marker.lower(), requirements[0]
    assert spec.strip().lower().startswith("httpx2")


def test_httpx2_has_what_the_adapter_uses():
    for name in ("AsyncClient", "Timeout", "MockTransport", "HTTPError", "StreamError", "AsyncByteStream"):
        assert hasattr(httpx2, name), name


def test_async_client_accepts_the_adapter_keywords():
    parameters = inspect.signature(httpx2.AsyncClient.__init__).parameters
    for name in ("trust_env", "follow_redirects", "transport", "verify", "timeout"):
        assert name in parameters, name
    assert parameters["follow_redirects"].default is False  # the adapter still passes it explicitly


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_only_openai_compat_imports_httpx2():
    importers = sorted(
        path.relative_to(ROOT).as_posix()
        for path in PACKAGE.rglob("*.py")
        if _imported_roots(path) & {"httpx2", "httpcore2"}
    )
    assert importers == ["greenscreen/publisher/ask/openai_compat.py"]


def test_the_import_scan_sees_an_import(tmp_path):
    """Self-check of the scan: a source that imports httpx2 is found, one that does not is not."""
    yes = tmp_path / "yes.py"
    yes.write_text("import os\nfrom httpx2 import AsyncClient\n", encoding="utf-8")
    also = tmp_path / "also.py"
    also.write_text("import httpcore2.sub\n", encoding="utf-8")
    no = tmp_path / "no.py"
    no.write_text('NAME = "httpx2"  # a logger name only\n', encoding="utf-8")
    assert "httpx2" in _imported_roots(yes)
    assert "httpcore2" in _imported_roots(also)
    assert not (_imported_roots(no) & {"httpx2", "httpcore2"})


# --------------------------------------------------------------------------
# In-process MCP client smoke
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mode", MODES)
def test_list_tools_and_call_tool_through_client_with_cache_none(mode):
    registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
    host = FakeHost(mini_states())
    service = CallService(registry, BoundValues(), load_bundled_signatures(), Limiter(1), host, clock=FakeClock())
    server = build_mcp_server(service, registry, transport="ask")
    userid = secrets.token_hex(4)

    async def go():
        async with Client(server, cache=None, mode=mode) as client:
            listed = await client.list_tools()
            again = await client.list_tools()  # cache=None: a second listing is a second request
            result = await client.call_tool("mini", {"userid": userid})
            return listed, again, result

    listed, again, result = asyncio.run(go())
    assert [t.name for t in listed.tools] == ["mini"] == [t.name for t in again.tools]
    assert result.is_error is False
    assert result.structured_content["flow"] == "mini"
    assert set(result.structured_content["outputs"]) == {"RELEASE"}
    assert host.created == 1 and host.closed == 1


# --------------------------------------------------------------------------
# A question with the real adapter writes no httpx2 or httpcore2 record
# --------------------------------------------------------------------------

class _RealAdapterPerTurn:
    """What ``build_app(model_adapter=...)`` accepts: it wraps a double in ``nullcontext``,
    so this double opens a real ``OpenAIAdapter`` over a ``MockTransport`` for each turn."""

    def __init__(self, handler, key: str) -> None:
        self._handler = handler
        self._key = key

    async def complete(self, messages, tools, *, timeout_seconds):
        adapter = OpenAIAdapter(
            "http://127.0.0.1:11434/v1", "fake-model", self._key, transport=httpx2.MockTransport(self._handler)
        )
        async with adapter as opened:
            return await opened.complete(messages, tools, timeout_seconds=timeout_seconds)


def test_a_question_with_the_real_adapter_writes_no_httpx2_or_httpcore2_record(caplog):
    model_key = secrets.token_urlsafe(16)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": "Done."}, "finish_reason": "stop"}]}
        )

    clock = AskFakeClock()
    app = build_ask_app(adapter=_RealAdapterPerTurn(handler, model_key), clock=clock)

    async def go():
        async with app.app.lifespan():
            return await ask_post(app, "What is the release?")

    with caplog.at_level(logging.DEBUG):
        logging.getLogger().setLevel(logging.DEBUG)
        reply = asyncio.run(go())
    assert reply.status == 200, reply.raw[:200]
    assert json.loads(reply.raw)["answer"] == "Done."
    assert len(requests) == 1  # the real adapter did make its request
    names = sorted({r.name for r in caplog.records})
    offenders = [r.name for r in caplog.records if r.name.split(".")[0] in {"httpx2", "httpcore2"}]
    assert offenders == [], names
    assert model_key not in "\n".join(r.getMessage() for r in caplog.records)
