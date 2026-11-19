"""The OpenAPI document with Ask on and off (spec ask, task 2.13).

Requirement 2, criterion 8; Requirement 1, criterion 13; Requirement 9, criterion 4.
Keys and Bound_Values are generated at run time and never written anywhere.
"""
from __future__ import annotations

import asyncio
import json

from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator

from greenscreen.publisher.app import prepare
from greenscreen.publisher.ask.codes import ASK_HTTP_STATUS
from greenscreen.publisher.registry import build_schemas
from greenscreen.publisher.rest import _package_version, build_openapi
from tests.ask_support import (
    _BOUND_VARIABLE,
    ASK_ENV,
    BOUND_PASSWORD,
    FLOW,
    _PLACEHOLDER_KEY,
    build_ask_app,
    no_network,  # noqa: F401  (autouse)
)
from tests.console_support import call_scope

MAX_Q = 321
MAX_A = 777
LIMITS = {"GS_ASK_MAX_QUESTION_CHARS": str(MAX_Q), "GS_ASK_MAX_ANSWER_CHARS": str(MAX_A)}


def fetch(app, *, key: str | None = None) -> tuple[int, bytes]:
    """GET /openapi.json through the whole ASGI stack."""
    headers = {"X-API-Key": key if key is not None else app.api_key}
    status, _, body = asyncio.run(call_scope(app.app.asgi, "GET", "/openapi.json", headers))
    return status, body


def served(env: dict | None = None) -> tuple[dict, bytes, object]:
    app = build_ask_app(env)
    status, raw = fetch(app)
    assert status == 200
    return json.loads(raw), raw, app


def prepared_for(env: dict):
    merged = {**ASK_ENV, _BOUND_VARIABLE: BOUND_PASSWORD, **env, "GS_API_KEY": _PLACEHOLDER_KEY}
    return prepare(merged)


# --------------------------------------------------------------------------
# Ask on
# --------------------------------------------------------------------------

def test_the_path_and_the_three_schemas_are_listed():
    doc, _, app = served(LIMITS)
    operation = doc["paths"]["/ask"]["post"]
    assert set(doc["paths"]["/ask"]) == {"post"}
    assert operation["operationId"] == "ask"
    assert isinstance(operation["summary"], str) and operation["summary"]
    flow_security = doc["paths"][f"/flows/{FLOW}"]["post"]["security"]
    assert operation["security"] == flow_security == [{"ApiKeyAuth": []}, {"BearerAuth": []}]
    schemas = doc["components"]["schemas"]
    assert {"ErrorBody", "AskResponse", "AskTrace", "AskErrorBody"} <= set(schemas)
    for name in ("AskResponse", "AskTrace", "AskErrorBody"):
        Draft202012Validator.check_schema(schemas[name])
    assert set(schemas["AskResponse"]["properties"]) == {"answer", "truncated", "trace"}
    assert schemas["AskResponse"]["required"] == ["answer", "truncated", "trace"]
    assert schemas["AskErrorBody"]["properties"]["error"]["required"] == ["code", "message"]


def test_the_request_schema_uses_the_configured_limits():
    doc, _, _ = served(LIMITS)
    request = doc["paths"]["/ask"]["post"]["requestBody"]
    assert request["required"] is True
    assert request["content"]["application/json"]["schema"] == {
        "type": "object",
        "properties": {"question": {"type": "string", "minLength": 1, "maxLength": MAX_Q}},
        "required": ["question"],
        "additionalProperties": False,
    }
    assert doc["components"]["schemas"]["AskResponse"]["properties"]["answer"]["maxLength"] == MAX_A


def test_the_limits_follow_the_settings():
    doc, _, _ = served({"GS_ASK_MAX_QUESTION_CHARS": "40", "GS_ASK_MAX_ANSWER_CHARS": "150"})
    schema = doc["paths"]["/ask"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    assert schema["properties"]["question"]["maxLength"] == 40
    assert doc["components"]["schemas"]["AskResponse"]["properties"]["answer"]["maxLength"] == 150


def test_one_response_entry_per_status_of_the_ask_codes():
    doc, _, _ = served(LIMITS)
    responses = doc["paths"]["/ask"]["post"]["responses"]
    assert "200" in responses
    for code, status in ASK_HTTP_STATUS.items():
        entry = responses[str(status)]
        assert code in entry["description"], (code, status)
        assert entry["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/AskErrorBody"}
    assert responses["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AskResponse"
    }
    for status in {str(s) for s in ASK_HTTP_STATUS.values()}:
        assert status in responses
    for code in ("unauthorized", "request_invalid", "request_too_large", "busy", "shutting_down", "internal_error"):
        assert any(code in r.get("description", "") for r in responses.values()), code


def test_every_ref_resolves_inside_the_document():
    doc, _, _ = served(LIMITS)
    text = json.dumps(doc)
    for name in ("AskResponse", "AskTrace", "AskErrorBody", "ErrorBody"):
        assert name in doc["components"]["schemas"]
    for ref in {part.split('"')[0] for part in text.split('"$ref": "')[1:]}:
        assert ref.startswith("#/components/schemas/")
        assert ref.rsplit("/", 1)[1] in doc["components"]["schemas"], ref


def test_the_audit_item_schema_equals_the_one_of_the_registry():
    doc, _, _ = served(LIMITS)
    flow = prepared_for({}).registry[FLOW].flow
    reference = build_schemas(flow)[2]["properties"]["audit"]
    trace = doc["components"]["schemas"]["AskTrace"]
    tool_step = next(
        option for option in trace["properties"]["steps"]["items"]["oneOf"]
        if option["properties"]["type"] == {"const": "tool"}
    )
    result = next(o for o in tool_step["properties"]["result"]["oneOf"] if o.get("type") == "object")
    assert result["properties"]["audit"] == reference
    assert result["properties"]["error"]["properties"]["audit"] == reference


def test_the_trace_schema_types_expected_as_a_list_of_strings():
    """Requirement 9.4: ``expected`` is the list the call service returns (``list(exc.expected)``)."""
    doc, _, _ = served(LIMITS)
    trace = doc["components"]["schemas"]["AskTrace"]
    tool_step = next(
        option for option in trace["properties"]["steps"]["items"]["oneOf"]
        if option["properties"]["type"] == {"const": "tool"}
    )
    result = next(o for o in tool_step["properties"]["result"]["oneOf"] if o.get("type") == "object")
    assert result["properties"]["error"]["properties"]["expected"] == {
        "type": "array", "items": {"type": "string"},
    }


def test_the_document_holds_no_setting_value():
    doc, raw, app = served(LIMITS)
    text = raw.decode("utf-8")
    for value in (app.api_key, BOUND_PASSWORD, "fake-model", "11434", "127.0.0.1", "GS_LLM", "GS_ASK_"):
        assert value not in text, value


def test_the_document_needs_the_key():
    app = build_ask_app()
    status, body = fetch(app, key="wrong-" + app.api_key)
    assert status == 401
    assert "/ask" not in body.decode("utf-8")


# --------------------------------------------------------------------------
# Ask off and the difference Ask makes
# --------------------------------------------------------------------------

def off_env() -> dict:
    return {"GS_ENABLE_ASK": "false"}


def test_with_ask_off_the_document_is_byte_for_byte_the_one_of_today():
    doc, raw, _ = served(off_env())
    prepared = prepared_for(off_env())
    expected = build_openapi(prepared.registry, _package_version())  # no ``ask`` argument: today's call
    assert doc == expected
    assert raw == JSONResponse(expected).body
    assert "/ask" not in doc["paths"]
    assert set(doc["components"]["schemas"]) == {"ErrorBody"}


def test_ask_only_adds_the_path_and_the_three_schemas():
    on, _, _ = served(LIMITS)
    off, _, _ = served(off_env())
    on["paths"].pop("/ask")
    for name in ("AskResponse", "AskTrace", "AskErrorBody"):
        on["components"]["schemas"].pop(name)
    assert on == off
