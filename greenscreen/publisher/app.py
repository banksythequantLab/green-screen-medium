"""Application wiring: ``prepare`` (startup checks) and ``build_app`` (the ASGI stack).

Day-one slice (task 3.3): no auth layer, crash guard, OpenAPI or bindings yet; those
are added by tasks 5.1 to 5.5. No environment variable or option selects a session
factory: tests inject one through ``build_app(session_factory=...)`` (Requirement 19.1).
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp

from greenscreen.publisher.calls import CallService, ConnectorSession, Limiter, SessionFactory
from greenscreen.publisher.config import Settings, StartupError, load_settings, parse_publish_list
from greenscreen.publisher.mcp_server import build_manager, build_mcp_server
from greenscreen.publisher.registry import (
    Registry,
    build_registry,
    load_flows,
    load_startup_signatures,
    select_published,
)
from greenscreen.publisher.rest import build_rest
from greenscreen.publisher.vault import BoundValues

__all__ = [
    "Prepared",
    "PublisherApp",
    "prepare",
    "build_app",
    "limit_third_party_loggers",
    "StartupError",
]

_THIRD_PARTY_LOGGERS = ("uvicorn", "starlette", "mcp", "anyio", "httpx2", "httpcore2", "asyncio")


@dataclass(frozen=True, slots=True)
class Prepared:
    settings: Settings
    registry: Registry  # Published_Flows only
    bound: BoundValues
    signatures: Sequence[Any]
    loaded_count: int  # Loaded_Flows, for "published N of M"


@dataclass(frozen=True, slots=True)
class PublisherApp:
    asgi: Any
    service: CallService
    server: Server

    def lifespan(self) -> contextlib.AbstractAsyncContextManager[None]:
        return self._lifespan()

    # Set by build_app through object.__setattr__-free closure: see _make_lifespan.
    _lifespan: Callable[[], contextlib.AbstractAsyncContextManager[None]]


def prepare(environ: Mapping[str, str]) -> Prepared:
    """All startup checks, in order. Opens no port and no session."""
    settings = load_settings(environ)
    loaded = load_flows(settings.flows_dir)
    published = select_published(loaded, parse_publish_list(settings.publish_flows))
    signatures = load_startup_signatures()
    bound = BoundValues()  # parse_bindings arrives with task 5.4
    registry = build_registry(published, bound, settings.call_timeout)
    return Prepared(settings, registry, bound, signatures, len(loaded))


def limit_third_party_loggers() -> None:
    """Keep third-party DEBUG records (which can quote frames) from being emitted."""
    for name in _THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(name)
        if logger.getEffectiveLevel() < logging.INFO:
            logger.setLevel(logging.INFO)


def build_app(
    prepared: Prepared,
    *,
    session_factory: SessionFactory | None = None,
    clock: Any = None,
    poll_interval: float = 0.1,
) -> PublisherApp:
    settings = prepared.settings
    limit_third_party_loggers()
    factory: SessionFactory = session_factory or (lambda: ConnectorSession(settings.connector))
    service = CallService(
        prepared.registry,
        prepared.bound,
        prepared.signatures,
        Limiter(settings.max_concurrency),
        factory,
        call_timeout=settings.call_timeout,
        shutdown_grace=settings.shutdown_grace,
        clock=clock,
        poll_interval=poll_interval,
    )
    server = build_mcp_server(service, prepared.registry)
    manager = build_manager(server, settings)

    @contextlib.asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        async with manager.run():
            try:
                yield
            finally:
                await service.drain(settings.shutdown_grace)

    @contextlib.asynccontextmanager
    async def app_lifespan(_app: Any) -> AsyncIterator[None]:
        async with lifespan():
            yield

    asgi = build_rest(
        service,
        prepared.registry,
        settings,
        StreamableHTTPASGIApp(manager),
        lifespan=app_lifespan,
    )
    return PublisherApp(asgi=asgi, service=service, server=server, _lifespan=lifespan)
