"""REST front end: routes only (task 3.1).

Auth, the crash guard, replaced framework handlers and the OpenAPI document are
added by tasks 5.1 to 5.3. Nothing here puts a submitted value in a response, a log
record or an exception message.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.routing import Route

from greenscreen.publisher.calls import (
    HTTP_STATUS,
    RESPONSE_HEADERS,
    CallOutcome,
    CallService,
    error_body,
)
from greenscreen.publisher.config import Settings
from greenscreen.publisher.console import HEADERS, Asset
from greenscreen.publisher.registry import PublishedFlow, Registry
from greenscreen.publisher.vault import SecretBox

if TYPE_CHECKING:  # the Ask package is imported only when Ask is on
    from greenscreen.publisher.ask.service import AskReply, AskService

__all__ = ["build_rest", "build_openapi", "read_json", "CrashGuard"]

_LOG = logging.getLogger("greenscreen.publisher")
CRASH_LOG_TEXT = "unhandled error in a request"


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


def _ask_reply(reply: "AskReply") -> JSONResponse:
    return JSONResponse(reply.body, status_code=reply.status, headers=dict(reply.headers))


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


class CrashGuard:
    """Outermost pure ASGI layer (Requirement 6.10).

    Starlette's ``ServerErrorMiddleware`` sends the replaced handler's response and
    then re-raises, so the HTTP server would log a traceback with the exception text.
    This layer swallows that re-raise, logs a fixed text (no ``exc_info``) and, when no
    response has started, sends the ``internal_error`` body. ``BaseException`` that is
    not an ``Exception`` (cancellation) passes through.
    """

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False
        finished = False

        async def tracking(message: dict) -> None:
            nonlocal started, finished
            if message["type"] == "http.response.start":
                started = True
            elif message["type"] == "http.response.body" and not message.get("more_body"):
                finished = True
            await send(message)

        try:
            await self.app(scope, receive, tracking)
        except Exception:
            failed = True
        else:
            failed = False
        if not failed:
            return
        _LOG.error(CRASH_LOG_TEXT)
        if not started:
            await _internal_error_response()(scope, receive, send)
        elif not finished:
            try:
                await send({"type": "http.response.body", "body": b""})
            except Exception:
                pass


def _internal_error_response() -> JSONResponse:
    return JSONResponse(
        error_body("internal_error"),
        status_code=HTTP_STATUS["internal_error"],
        headers={"Cache-Control": "no-store"},
    )


_ERROR_BODY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "step_index": {"type": "integer"},
                "kind": {"type": "string"},
                "expected": {"type": ["string", "null"]},
                "summary": {"type": "object"},
                "audit": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["code", "message"],
        }
    },
    "required": ["error"],
    "additionalProperties": False,
}


def _package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("greenscreen-connector")
        except PackageNotFoundError:
            return "0.0.0"
    except Exception:  # pragma: no cover - metadata is optional
        return "0.0.0"


def build_openapi(registry: Registry, version: str, ask: "AskService | None" = None) -> dict:
    """The OpenAPI 3.1 document of the Published_Flows (Requirement 12).

    Pure function of the registry. Embedded schemas are the registry's own objects, so
    they equal the Schema_Generator output. Holds no value, default or example.
    With ``ask`` set, ``/ask`` and its three schemas are added; with ``None`` the
    document is exactly the one without Ask.
    """
    by_status: dict[int, list[str]] = {}
    for code, status in HTTP_STATUS.items():
        by_status.setdefault(status, []).append(code)

    error_responses: dict[str, dict] = {}
    for status in sorted(by_status):
        codes = ", ".join(sorted(by_status[status]))
        error_responses[str(status)] = {
            "description": f"Error. Error codes with this status: {codes}.",
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/ErrorBody"}}
            },
        }

    security = [{"ApiKeyAuth": []}, {"BearerAuth": []}]
    paths: dict[str, dict] = {}
    for name, published in registry.items():
        responses: dict[str, dict] = {
            "200": {
                "description": "The flow finished.",
                "content": {"application/json": {"schema": published.success_schema}},
            }
        }
        responses.update(error_responses)
        paths[f"/flows/{name}"] = {
            "post": {
                "operationId": name,
                "summary": published.summary,
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": published.input_schema}},
                },
                "responses": responses,
                "security": security,
            }
        }
    paths["/health"] = {
        "get": {
            "operationId": "health",
            "summary": "Liveness and the number of published flows.",
            "responses": {
                "200": {
                    "description": "The publisher is running.",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "flows": {"type": "integer"},
                                },
                                "required": ["status", "flows"],
                                "additionalProperties": False,
                            }
                        }
                    },
                }
            },
            "security": [],
        }
    }
    schemas: dict[str, dict] = {"ErrorBody": _ERROR_BODY_SCHEMA}
    if ask is not None:
        from greenscreen.publisher.ask.service import ask_openapi

        path_item, ask_schemas = ask_openapi(ask.max_question_chars, ask.max_answer_chars)
        paths["/ask"] = path_item
        schemas.update(ask_schemas)
    return {
        "openapi": "3.1.0",
        "info": {"title": "Green Screen Medium publisher", "version": version},
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            },
        },
    }


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


def _serve(asset: Asset) -> Callable:
    """Handler for one console asset: cached bytes, fixed headers, no request access."""

    async def serve() -> Response:
        return Response(asset.body, media_type=asset.media_type, headers=HEADERS)

    return serve


def build_rest(
    service: CallService,
    registry: Registry,
    settings: Settings,
    mcp_asgi: Callable,
    *,
    lifespan: Any = None,
    console: Sequence[Asset] = (),
    ask: "AskService | None" = None,
) -> FastAPI:
    """The FastAPI application: Flow route, ``/health`` and the ``/mcp`` route."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(_NoStore)
    limit = settings.max_body_bytes

    # Every default error handler is replaced (Requirement 6.9). The validation
    # handler matters most: the default 422 echoes the submitted value.
    async def request_invalid_handler(request: Request, exc: Exception) -> JSONResponse:
        return _response(_outcome("request_invalid"))

    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _internal_error_response()

    app.add_exception_handler(RequestValidationError, request_invalid_handler)
    app.add_exception_handler(StarletteHTTPException, request_invalid_handler)
    app.add_exception_handler(Exception, internal_error_handler)

    @app.post("/flows/{name}", response_model=None)
    async def run_flow_route(name: str, request: Request) -> JSONResponse:
        started = time.monotonic()
        pre = service.precheck(name, "rest")  # logs its own rejections
        if isinstance(pre, CallOutcome):
            return _response(pre)
        published: PublishedFlow = pre
        flow_name = published.flow.name
        if not _is_json_media_type(request.headers.get("content-type")):
            service.log_rejection(flow_name, "rest", "request_invalid", started)
            return _response(_outcome("request_invalid"))
        box = await read_json(request, limit)
        if isinstance(box, CallOutcome):
            service.log_rejection(flow_name, "rest", box.code, started)
            return _response(box)
        return _response(await service.execute(published, box, "rest"))

    if ask is not None:

        @app.post("/ask", response_model=None)
        async def ask_route(request: Request) -> JSONResponse:
            call = ask.begin()
            if not _is_json_media_type(request.headers.get("content-type")):
                return _ask_reply(call.reject("request_invalid"))
            box = await read_json(request, limit)
            if isinstance(box, CallOutcome):
                return _ask_reply(call.reject(box.code))
            try:
                payload = dict(box.mapping())
            finally:
                box.clear()
            return _ask_reply(await call.answer(payload))

    @app.get("/health", response_model=None)
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "flows": len(registry)})

    document = build_openapi(registry, _package_version(), ask)

    @app.get("/openapi.json", response_model=None)
    async def openapi_json() -> JSONResponse:
        return JSONResponse(document)

    if settings.enable_docs:

        @app.get("/docs", response_model=None)
        async def docs() -> HTMLResponse:
            return get_swagger_ui_html(
                openapi_url="/openapi.json", title="Green Screen Medium publisher"
            )

    for asset in console:
        app.add_api_route(
            asset.path,
            _serve(asset),
            methods=["GET"],
            include_in_schema=False,
            response_model=None,
        )

    # Wrapped in an object so Starlette treats it as a raw ASGI app for every method,
    # also when ``mcp_asgi`` is a plain function.
    app.router.routes.append(Route("/mcp", _Asgi(mcp_asgi)))
    return app
