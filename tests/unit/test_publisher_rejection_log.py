"""One Call_Log_Record per rejection before a session opens (Requirements 8.9, 8.10, 19.11)."""
from __future__ import annotations

import asyncio
import json
import logging

import httpx2
import pytest
from mcp import Client

from greenscreen.publisher.calls import CallService, Limiter
from greenscreen.publisher.config import load_settings
from greenscreen.publisher.mcp_server import build_mcp_server
from greenscreen.publisher.registry import build_registry
from greenscreen.publisher.rest import build_rest
from greenscreen.publisher.vault import BoundValues
from greenscreen.recognizer import load_bundled_signatures
from tests.flow_support import FakeClock
from tests.publisher_support import MINI, FakeHost, mini_states

PROBE = "PRB7Q2XZ"
LIMIT = 2048
ALLOWED = {"call_id", "flow", "transport", "outcome", "duration_ms"}
ENV = {
    "GS_S3270_BINARY": "s3270",
    "GS_HOST": "host.invalid",
    "GS_API_KEY": "k" * 16,
    "GS_MAX_BODY_BYTES": str(LIMIT),
}
_STANDARD = set(logging.LogRecord("n", 0, "p", 0, "m", (), None).__dict__) | {"message", "asctime"}
JSON_HDR = {"content-type": "application/json"}


class Stack:
    def __init__(self) -> None:
        self.host = FakeHost(mini_states())
        self.limiter = Limiter(1)
        self.registry = build_registry({"mini": (MINI, "test")}, BoundValues(), 30.0)
        self.service = CallService(
            self.registry, BoundValues(), load_bundled_signatures(), self.limiter, self.host,
            clock=FakeClock(),
        )

        async def mcp(scope, receive, send):  # pragma: no cover
            raise AssertionError

        self.app = build_rest(self.service, self.registry, load_settings(ENV), mcp)

    def rest(self, method, path, **kw):
        async def go():
            transport = httpx2.ASGITransport(app=self.app)
            async with httpx2.AsyncClient(transport=transport, base_url="http://test") as c:
                return await c.request(method, path, **kw)

        return asyncio.run(go())


def call_records(caplog):
    return [
        r for r in caplog.records
        if r.name == "greenscreen.publisher" and r.getMessage() == "call finished"
    ]


def extras(record):
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD}


def assert_one_rejection(caplog, outcome, *, flow="mini", transport="rest"):
    records = call_records(caplog)
    assert len(records) == 1
    fields = extras(records[0])
    assert set(fields) == ALLOWED
    assert fields["outcome"] == outcome
    assert fields["flow"] == flow and fields["transport"] == transport
    assert isinstance(fields["duration_ms"], int)
    assert PROBE not in json.dumps({k: str(v) for k, v in fields.items()})
    assert PROBE not in caplog.text


@pytest.fixture(autouse=True)
def _info(caplog):
    caplog.set_level(logging.INFO, logger="greenscreen.publisher")


def test_wrong_media_type(caplog):
    s = Stack()
    r = s.rest("POST", "/flows/mini", content=json.dumps({"userid": PROBE}),
               headers={"content-type": "text/plain"})
    assert r.status_code == 400
    assert_one_rejection(caplog, "request_invalid")


@pytest.mark.parametrize(
    "body",
    [
        b'{"userid": "' + PROBE.encode(),  # malformed
        b'{"userid": "A", "userid": "' + PROBE.encode() + b'"}',  # duplicate key
        b'{"count": NaN, "userid": "' + PROBE.encode() + b'"}',  # non-finite number
        b'["' + PROBE.encode() + b'"]',  # not an object
    ],
    ids=["malformed", "duplicate_key", "nan", "array"],
)
def test_bad_json_bodies(caplog, body):
    s = Stack()
    r = s.rest("POST", "/flows/mini", content=body, headers=JSON_HDR)
    assert r.status_code == 400
    assert_one_rejection(caplog, "request_invalid")
    assert s.host.factory_calls == 0


def test_oversize_with_content_length(caplog):
    s = Stack()
    r = s.rest("POST", "/flows/mini", content=json.dumps({"userid": PROBE * 400}), headers=JSON_HDR)
    assert r.status_code == 413
    assert_one_rejection(caplog, "request_too_large")


def test_oversize_chunked(caplog):
    s = Stack()

    async def chunks():
        for _ in range(20):
            yield b" " * 512

    r = s.rest("POST", "/flows/mini", content=chunks(), headers=JSON_HDR)
    assert r.status_code == 413
    assert_one_rejection(caplog, "request_too_large")


def test_unknown_flow_logs_unknown(caplog):
    s = Stack()
    r = s.rest("POST", "/flows/no-such-flow", content=json.dumps({"userid": PROBE}), headers=JSON_HDR)
    assert r.status_code == 404
    assert_one_rejection(caplog, "unknown_flow", flow="unknown")


def test_input_invalid_over_rest(caplog):
    s = Stack()
    r = s.rest("POST", "/flows/mini", content=json.dumps({"userid": PROBE * 4}), headers=JSON_HDR)
    assert r.status_code == 422
    assert_one_rejection(caplog, "input_invalid")
    assert s.host.factory_calls == 0


def test_input_invalid_over_mcp(caplog):
    s = Stack()
    server = build_mcp_server(s.service, s.registry)

    async def go():
        async with Client(server, mode="auto") as c:
            return await c.call_tool("mini", {"userid": PROBE * 4})

    res = asyncio.run(go())
    assert res.is_error
    assert_one_rejection(caplog, "input_invalid", transport="mcp")


def test_busy(caplog):
    s = Stack()
    assert s.limiter.try_acquire()
    r = s.rest("POST", "/flows/mini", content=json.dumps({"userid": PROBE}), headers=JSON_HDR)
    assert r.status_code == 429
    assert_one_rejection(caplog, "busy")
    assert s.host.factory_calls == 0


def test_shutting_down(caplog):
    s = Stack()
    s.service.begin_shutdown()
    r = s.rest("POST", "/flows/mini", content=json.dumps({"userid": PROBE}), headers=JSON_HDR)
    assert r.status_code == 503
    assert_one_rejection(caplog, "shutting_down")


def test_requests_that_are_not_calls_write_no_call_record(caplog):
    # An Auth_Guard rejection is covered by the stack test of task 5.5.
    s = Stack()
    assert s.rest("GET", "/health").status_code == 200
    assert s.rest("GET", "/no/such/path").status_code == 400
    assert s.rest("GET", "/flows/mini").status_code == 400  # wrong method, not a Call
    assert call_records(caplog) == []
