"""OpenAPI builder and docs page of the publisher (task 5.3). No live host."""
from __future__ import annotations

import asyncio
import json

import httpx2

from fastapi.openapi.models import OpenAPI

from greenscreen.publisher.calls import ERROR_CODES, HTTP_STATUS, CallService, Limiter
from greenscreen.publisher.config import load_settings
from greenscreen.publisher.registry import build_registry, build_schemas, load_flows, select_published
from greenscreen.publisher.rest import build_openapi, build_rest
from greenscreen.publisher.vault import BoundValues
from greenscreen.recognizer import load_bundled_signatures

from tests.flow_support import FakeClock
from tests.publisher_support import MINI

SIGS = load_bundled_signatures()
ENV = {"GS_S3270_BINARY": "s3270", "GS_HOST": "host.invalid", "GS_API_KEY": "k" * 16}


def _factory():  # pragma: no cover - never called
    raise AssertionError("session factory must not be called")


async def _dummy_mcp(scope, receive, send):  # pragma: no cover
    raise AssertionError("not exercised")


def _registry(names=None):
    loaded = load_flows(None)
    chosen = select_published(loaded, names)
    return build_registry(chosen, BoundValues(), 30.0)


def _app(registry, extra_env=None):
    service = CallService(registry, BoundValues(), SIGS, Limiter(1), _factory, clock=FakeClock())
    return build_rest(service, registry, load_settings({**ENV, **(extra_env or {})}), _dummy_mcp)


def _get(app, path):
    async def go():
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.get(path)

    return asyncio.run(go())


def test_bundled_document_is_valid_openapi_and_embeds_generator_schemas():
    registry = _registry()
    assert len(registry) == 8
    doc = build_openapi(registry, "1.2.3")
    OpenAPI.model_validate(doc)
    assert doc["openapi"] == "3.1.0"
    assert doc["info"]["version"] == "1.2.3"
    assert set(doc["paths"]) == {f"/flows/{n}" for n in registry} | {"/health"}
    for name, published in registry.items():
        op = doc["paths"][f"/flows/{name}"]["post"]
        inp, _out, suc = build_schemas(published.flow, published.bound_names)
        assert op["operationId"] == name
        assert op["summary"] == (published.flow.description or f"Run flow {name}.")
        assert op["requestBody"]["content"]["application/json"]["schema"] == inp
        assert op["responses"]["200"]["content"]["application/json"]["schema"] == suc


def test_error_responses_list_every_code_of_each_status():
    doc = build_openapi(_registry(), "1")
    op = next(iter(doc["paths"].values()))["post"]
    statuses = {str(s) for s in HTTP_STATUS.values()}
    assert set(op["responses"]) == statuses | {"200"}
    for status in statuses:
        text = op["responses"][status]["description"]
        for code, st in HTTP_STATUS.items():
            if str(st) == status:
                assert code in text
    assert set(HTTP_STATUS) == set(ERROR_CODES)


def test_security_entries():
    doc = build_openapi(_registry(), "1")
    schemes = doc["components"]["securitySchemes"]
    assert schemes["ApiKeyAuth"] == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    assert schemes["BearerAuth"] == {"type": "http", "scheme": "bearer"}
    for path, item in doc["paths"].items():
        if path == "/health":
            assert item["get"]["security"] == []
        else:
            assert item["post"]["security"] == [{"ApiKeyAuth": []}, {"BearerAuth": []}]


def test_no_path_for_loaded_flow_outside_registry():
    registry = _registry(("tk5-system-info",))
    doc = build_openapi(registry, "1")
    assert set(doc["paths"]) == {"/flows/tk5-system-info", "/health"}
    assert "tk5-logon" not in json.dumps(doc)


def test_document_has_no_cancelled_and_no_value_keywords():
    text = json.dumps(build_openapi(_registry(), "1"))
    assert "cancelled" not in text.lower()
    doc = json.loads(text)

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in ("default", "example", "examples", "const", "enum")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(doc["paths"])


def test_summary_falls_back_for_a_flow_without_description():
    registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
    doc = build_openapi(registry, "1")
    assert doc["paths"]["/flows/mini"]["post"]["summary"] == (
        MINI.description or "Run flow mini."
    )


def test_openapi_route_serves_document_and_no_docs_by_default():
    registry = _registry()
    app = _app(registry)
    resp = _get(app, "/openapi.json")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    OpenAPI.model_validate(resp.json())
    assert resp.json()["paths"].keys() == build_openapi(registry, resp.json()["info"]["version"])["paths"].keys()
    docs = _get(app, "/docs")
    assert docs.status_code == 400
    assert docs.json()["error"]["code"] == "request_invalid"


def test_docs_page_served_when_enabled():
    app = _app(_registry(), {"GS_ENABLE_DOCS": "true"})
    resp = _get(app, "/docs")
    assert resp.status_code == 200
    assert "/openapi.json" in resp.text
