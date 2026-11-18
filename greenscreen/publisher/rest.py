"""REST front end: routes only (task 3.1).

Auth, the crash guard, replaced framework handlers and the OpenAPI document are
added by tasks 5.1 to 5.3. Nothing here puts a submitted value in a response, a log
record or an exception message.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.routing import Route

from greenscreen.publisher.calls import (
    HTTP_STATUS,
    RESPONSE_HEADERS,
    CallOutcome,
    CallService,
    error_body,
)
from greenscreen.publisher.config import Settings
from greenscreen.publisher.registry import PublishedFlow, Registry
from greenscreen.publisher.vault import SecretBox

__all__ = ["build_rest", "read_json"]


class _Reject(Exception):
    """Private marker raised by the JSON hooks. Carries nothing."""


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise _Reject
        out[key] = value
    return out


def _reject_constant(_name: str) -> Any:
    raise _Reject


def _outcome(code: str) -> CallOutcome:
    return CallOutcome(code, error_body(code))


def _response(outcome: CallOutcome) -> JSONResponse:
    status = 200 if outcome.code == "ok" else HTTP_STATUS[outcome.code]
    headers = dict(RESPONSE_HEADERS.get(outcome.code, {}))
    return JSONResponse(outcome.body, status_code=status, headers=headers)


def _is_json_media_type(value: str | None) -> bool:
    if value is None:
        return False
    return value.split(";", 1)[0].strip().lower() == "application/json"


async def read_json(request: Request, limit: int) -> SecretBox | CallOutcome:
    """Read the body (at most ``limit`` bytes) as a JSON object into a SecretBox.

    The outcome of a failure is built after the ``except`` block, so no exception
    (whose ``doc`` could hold the body) is alive in this frame.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        if not declared.isascii() or not declared.isdigit():
            return _outcome("request_invalid")
        if int(declared) > limit:
            return _outcome("request_too_large")

    buffer = bytearray()
    too_large = False
    try:
        async for chunk in request.stream():
            buffer += chunk
            if len(buffer) > limit:
                too_large = True
                break
        if too_large:
            return _outcome("request_too_large")

        invalid = False
        parsed: Any = None
        try:
            parsed = json.loads(
                bytes(buffer).decode("utf-8"),
                object_pairs_hook=_no_duplicates,
                parse_constant=_reject_constant,
            )
        except (_Reject, ValueError, RecursionError):
            invalid = True
        if invalid or not isinstance(parsed, dict):
            return _outcome("request_invalid")
        return SecretBox.adopt(parsed)
    finally:
        buffer.clear()


class _Asgi:
    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        await self.app(scope, receive, send)


class _NoStore:
    """Pure ASGI: add ``Cache-Control: no-store`` to every HTTP response."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def wrapped(message: dict) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not any(k.lower() == b"cache-control" for k, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped)


def build_rest(
    service: CallService,
    registry: Registry,
    settings: Settings,
    mcp_asgi: Callable,
    *,
    lifespan: Any = None,
) -> FastAPI:
    """The FastAPI application: Flow route, ``/health`` and the ``/mcp`` route."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(_NoStore)
    limit = settings.max_body_bytes

    @app.post("/flows/{name}", response_model=None)
    async def run_flow_route(name: str, request: Request) -> JSONResponse:
        pre = service.precheck(name, "rest")
        if isinstance(pre, CallOutcome):
            return _response(pre)
        published: PublishedFlow = pre
        if not _is_json_media_type(request.headers.get("content-type")):
            return _response(_outcome("request_invalid"))
        box = await read_json(request, limit)
        if isinstance(box, CallOutcome):
            return _response(box)
        return _response(await service.execute(published, box, "rest"))

    @app.get("/health", response_model=None)
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "flows": len(registry)})

    # Wrapped in an object so Starlette treats it as a raw ASGI app for every method,
    # also when ``mcp_asgi`` is a plain function.
    app.router.routes.append(Route("/mcp", _Asgi(mcp_asgi)))
    return app
