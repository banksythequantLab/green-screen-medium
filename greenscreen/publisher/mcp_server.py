"""The MCP front end: one tool per Published_Flow on the low-level ``Server``.

Arguments are never looked at by the SDK (low-level ``Server``) and every
``Exception`` is caught in the call handler, so no argument value reaches the
SDK error path (Requirements 4.6, 14.6, 14.10).
"""
from __future__ import annotations

import json
from importlib import metadata
from typing import Any

import anyio
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp_types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    TextContent,
    Tool,
)

from greenscreen.publisher.calls import CallOutcome, CallService, error_body
from greenscreen.publisher.config import Settings
from greenscreen.publisher.registry import Registry
from greenscreen.publisher.vault import SecretBox

__all__ = ["build_mcp_server", "build_manager", "run_stdio"]

SERVER_NAME = "greenscreen-publisher"


def _version() -> str:
    try:
        return metadata.version("greenscreen-connector")
    except Exception:
        return "0.1.0"


def _result(outcome: CallOutcome) -> CallToolResult:
    """One text block and ``structuredContent`` holding the same JSON."""
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(outcome.body))],
        structured_content=outcome.body,
        is_error=outcome.code != "ok",
    )


def build_mcp_server(service: CallService, registry: Registry) -> Server:
    """Low-level Server with ``tools/list`` and ``tools/call`` only (Requirement 14.8)."""
    tools = ListToolsResult(
        tools=[
            Tool(
                name=name,
                description=published.summary,
                input_schema=published.input_schema,
                output_schema=published.success_schema,
            )
            for name, published in registry.items()
        ]
    )

    async def on_list_tools(ctx: Any, params: Any) -> ListToolsResult:
        return tools

    async def on_call_tool(ctx: Any, params: CallToolRequestParams) -> CallToolResult:
        try:
            found = service.precheck(params.name, "mcp")
            if isinstance(found, CallOutcome):
                outcome = found
            else:
                outcome = await service.execute(
                    found, SecretBox.adopt(params.arguments or {}), "mcp"
                )
        except Exception:
            outcome = CallOutcome("internal_error", error_body("internal_error"))
        return _result(outcome)

    return Server(
        SERVER_NAME,
        version=_version(),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def build_manager(server: Server, settings: Settings) -> StreamableHTTPSessionManager:
    """Stateless, JSON responses. The Publisher does its own Host rule (Requirement 13.7)."""
    return StreamableHTTPSessionManager(
        server,
        json_response=True,
        stateless=True,
        security_settings=None,
        max_request_body_size=settings.max_body_bytes,
    )


async def run_stdio(
    server: Server,
    service: CallService,
    *,
    grace: float,
    stdin: Any = None,
    stdout: Any = None,
) -> None:
    """Serve over stdio until the input ends, then drain the service.

    ``cli`` passes the duplicated streams (Requirement 14.11); with none given the
    SDK defaults are used.
    """
    try:
        async with stdio_server(stdin=stdin, stdout=stdout) as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        with anyio.CancelScope(shield=True):
            await service.drain(grace)
