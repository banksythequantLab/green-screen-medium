"""The Ask service: eligibility, the in-process MCP port, limits, trace, route glue.

Everything the HTTP route and ``app.py`` need from Ask lives here. The agent
loop (``agent.py``) knows none of it: it receives a ``ToolPort`` and plain data.

Nothing here logs a question, an answer, a model message, an argument, a tool
result or an exception text. The only record written is ``ask finished``.
"""

from __future__ import annotations

import logging
import math
import re
import secrets
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, time as day_time, timedelta, timezone
from typing import Any

import anyio
from mcp import Client

from greenscreen.publisher.ask.agent import (
    Limits,
    ModelStep,
    Progress,
    ToolInfo,
    ToolResult,
    ToolStep,
    ToolsStep,
    run_question,
)
from greenscreen.publisher.ask.codes import (
    ASK_ERROR_CODES,
    ASK_HTTP_STATUS,
    ASK_MESSAGES,
)
from greenscreen.publisher.calls import ERROR_CODES, HTTP_STATUS, MESSAGES
from greenscreen.publisher.config import AskSettings, StartupError
from greenscreen.publisher.registry import Registry

__all__ = [
    "TOOL_TAIL",
    "HINTS",
    "AskPlan",
    "plan_ask",
    "McpToolPort",
    "DailyBudget",
    "AskReply",
    "AskCall",
    "AskService",
    "SystemClock",
    "project_result",
    "project_trace",
    "ask_openapi",
    "validate_question",
]

_LOG = logging.getLogger("greenscreen.publisher")
RECORD_TEXT = "ask finished"

ABORT_WAIT = 5.0  # ConnectorSession.abort: proc.wait(5)
WORKER_GRACE = 5.0  # calls._WORKER_GRACE
# CallService._teardown awaits the abort and then the worker, one after the other.
TOOL_TAIL = ABORT_WAIT + WORKER_GRACE  # 10.0 (Decision 23)

CANCEL_SLOP = 0.5  # late expiry of a model turn
OVERHEAD = 2.0  # Overhead_Allowance
WORST_CASE_LIMIT = 98.0  # Tunnel_Limit 100 less a margin of 2

# rule -> Fixed_Hint; a rule without an entry has no hint. Each hint names one setting, no value.
HINTS: dict[str, str] = {
    "call_too_long": "lower GS_CALL_TIMEOUT",
    "worst_case_too_long": "lower GS_ASK_TIMEOUT_SECONDS",
}

_NAME_RE = re.compile(r"[a-zA-Z0-9_-]{1,64}")

# --- eligibility ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AskPlan:
    eligible: frozenset[str]
    worst_case: Mapping[str, float]  # Tool_Worst_Case per eligible name
    worst_case_seconds: float  # T + CANCEL_SLOP + OVERHEAD
    largest_tool_seconds: float  # max of worst_case.values()


def _tag(rule: str) -> str:
    """``rule`` with its Fixed_Hint when it has one."""
    return rule + (": " + HINTS[rule] if rule in HINTS else "")


def _hint_suffix(rule: str) -> str:
    return ": " + HINTS[rule] if rule in HINTS else ""


def _rule(name: str, published: Any, ask: AskSettings) -> str | None:
    """The first failing rule for one Flow, in the order of Requirement 1.14."""
    if not _NAME_RE.fullmatch(name):
        return "name_not_allowed"
    if any(spec.secret for spec in published.decl.inputs):
        return "has_secret_input"
    need = published.deadline + TOOL_TAIL + 2 * ask.model_timeout_seconds
    if need > ask.timeout_seconds:
        return "call_too_long"
    return None


def plan_ask(registry: Registry, ask: AskSettings) -> AskPlan:
    """Pick the offerable Flows or raise ``StartupError`` (names and rules only)."""
    if ask.flows is not None:
        for name in ask.flows:  # list order; the first problem wins
            if name not in registry:
                raise StartupError(f"GS_ASK_FLOWS: not_published ({name})")
            rule = _rule(name, registry[name], ask)
            if rule is not None:
                raise StartupError(f"GS_ASK_FLOWS: {rule} ({name}{_hint_suffix(rule)})")
        names = list(ask.flows)
    else:
        skipped: set[str] = set()
        names = []
        for name, published in registry.items():
            rule = _rule(name, published, ask)
            if rule is None:
                names.append(name)
            else:
                skipped.add(rule)
        if not names:
            raise StartupError(
                "GS_ENABLE_ASK: no_offerable_tools (" + ", ".join(_tag(r) for r in sorted(skipped)) + ")"
            )
    worst = {name: registry[name].deadline + TOOL_TAIL for name in names}
    total = ask.timeout_seconds + CANCEL_SLOP + OVERHEAD
    if total > WORST_CASE_LIMIT:
        raise StartupError(
            f"GS_ASK_TIMEOUT_SECONDS: worst_case_too_long ({HINTS['worst_case_too_long']})"
        )
    return AskPlan(frozenset(names), worst, total, max(worst.values()))


# --- the in-process MCP port ------------------------------------------------------


class McpToolPort:
    """Turns the SDK's types into plain data, so nothing past here knows the SDK."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def list_tools(self) -> list[ToolInfo]:
        result = await self._client.list_tools()
        tools: list[ToolInfo] = []
        for tool in result.tools:
            schema = dict(tool.input_schema)
            props = schema.get("properties", {})
            values = props.values() if isinstance(props, dict) else ()
            secret = any(isinstance(p, dict) and p.get("writeOnly") is True for p in values)
            tools.append(ToolInfo(tool.name, tool.description or "", schema, secret=secret))
        return tools

    async def call(self, name: str, arguments: dict) -> ToolResult:
        res = None
        failed = False
        try:
            res = await self._client.call_tool(name, arguments)
        except Exception:  # a protocol failure, not a tool error; no text is kept
            failed = True
        if failed or res is None or not isinstance(res.structured_content, dict):
            return ToolResult("internal_error", None)
        body = res.structured_content
        if not res.is_error:
            good = isinstance(body.get("flow"), str) and isinstance(body.get("outputs"), dict)
            return ToolResult("ok", body) if good else ToolResult("internal_error", None)
        err = body.get("error")
        code = err.get("code") if isinstance(err, dict) else None
        return ToolResult(code if code in ERROR_CODES else "internal_error", body)


# --- clocks and the daily budget -----------------------------------------------------


class SystemClock:
    """The agent's clock: ``monotonic()`` and an async ``sleep()``."""

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await anyio.sleep(seconds)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DailyBudget:
    """Questions per UTC day, in memory. Event-loop confined, no await inside."""

    def __init__(self, limit: int, utcnow: Callable[[], datetime] = _utc_now) -> None:
        self._limit = limit
        self._utcnow = utcnow
        self._day = None
        self._count = 0

    def take(self) -> int | None:
        """``None`` when taken; else the seconds until 00:00 UTC (1 to 86 400)."""
        now = self._utcnow()
        if now.date() != self._day:
            self._day, self._count = now.date(), 0
        if self._count >= self._limit:
            midnight = datetime.combine(
                now.date() + timedelta(days=1), day_time.min, tzinfo=timezone.utc
            )
            return max(1, min(86400, math.ceil((midnight - now).total_seconds())))
        self._count += 1
        return None


# --- the trace -------------------------------------------------------------------------

_AUDIT_TYPES: dict[str, tuple[type, ...]] = {
    "step_index": (int,),
    "kind": (str,),
    "phase": (str,),
    "iteration": (int, type(None)),
    "signature": (str, type(None)),
    "status": (str,),
    "duration_seconds": (int, float),
}


def _typed(value: Any, types: tuple[type, ...]) -> bool:
    if isinstance(value, bool) or not isinstance(value, types):
        return False
    return not (isinstance(value, float) and not math.isfinite(value))


def _project_audit(items: Any) -> list[dict]:
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if all(k in item and _typed(item[k], t) for k, t in _AUDIT_TYPES.items()):
            out.append({k: item[k] for k in _AUDIT_TYPES})
    return out


def project_result(code: str, body: Any) -> dict | None:
    """Allow-list projection of one tool result (Requirement 9, criterion 4).

    Keeps named members of a declared type only. ``summary``, ``content`` and any
    unknown member never pass. A rejected call, or a result without a body, is ``None``.
    """
    if code == "rejected" or not isinstance(body, dict):
        return None
    if code == "ok":
        out: dict[str, Any] = {}
        if isinstance(body.get("flow"), str):
            out["flow"] = body["flow"]
        outputs = body.get("outputs")
        if isinstance(outputs, dict):
            out["outputs"] = {
                k: v
                for k, v in outputs.items()
                if isinstance(k, str) and _typed(v, (str, int))
            }
        if isinstance(body.get("audit"), list):
            out["audit"] = _project_audit(body["audit"])
        return out
    error = body.get("error")
    if not isinstance(error, dict):
        return None
    kept: dict[str, Any] = {}
    for key in ("code", "message", "kind"):
        if isinstance(error.get(key), str):
            kept[key] = error[key]
    if _typed(error.get("step_index"), (int,)):
        kept["step_index"] = error["step_index"]
    expected = error.get("expected")
    if isinstance(expected, list) and all(isinstance(e, str) for e in expected):
        kept["expected"] = list(expected)
    if isinstance(error.get("audit"), list):
        kept["audit"] = _project_audit(error["audit"])
    return {"error": kept}


def _ms(seconds: float) -> int:
    return max(0, int(round(seconds * 1000)))


def project_trace(prog: Progress, elapsed_ms: int) -> dict:
    """The Trace: four members, no counts of audit steps or screens (Decision 21)."""
    steps: list[dict] = []
    for step in prog.steps:
        if isinstance(step, ToolsStep):
            steps.append({"type": "tools", "offered": list(step.offered)})
        elif isinstance(step, ModelStep):
            steps.append(
                {
                    "type": "model",
                    "turn": step.turn,
                    "outcome": step.outcome,
                    "tool_calls": step.tool_calls,
                    "duration_ms": _ms(step.seconds),
                }
            )
        elif isinstance(step, ToolStep):
            item: dict[str, Any] = {
                "type": "tool",
                "turn": step.turn,
                "id": step.id,
                "tool": step.tool,
                "arguments": step.arguments,
                "ok": step.ok,
                "code": step.code,
            }
            if step.reason is not None:
                item["reason"] = step.reason
            item["result"] = project_result(step.code, step.body)
            item["duration_ms"] = _ms(step.seconds)
            if step.repeats:
                item["repeats"] = step.repeats
            steps.append(item)
    return {
        "model_turns": prog.turns,
        "tool_calls": prog.tool_calls,
        "elapsed_ms": max(0, int(elapsed_ms)),
        "steps": steps,
    }


# --- the question ----------------------------------------------------------------------


def validate_question(payload: Any, max_chars: int) -> str | None:
    """The trimmed question, or ``None`` (Requirement 2, criteria 3 and 4)."""
    if not isinstance(payload, dict) or set(payload) != {"question"}:
        return None
    text = payload["question"]
    if not isinstance(text, str):
        return None
    for ch in text:  # raw text first: strip() would hide control characters at the edges
        if ch not in "\n\t" and unicodedata.category(ch) == "Cc":
            return None
    text = text.strip()
    if text == "" or len(text) > max_chars:
        return None
    return text


# --- replies and the service -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AskReply:
    status: int
    body: dict
    headers: dict = field(default_factory=dict)


def _error_reply(code: str, trace: dict | None = None, headers: dict | None = None) -> AskReply:
    if code in ASK_ERROR_CODES:
        status, message = ASK_HTTP_STATUS[code], ASK_MESSAGES[code]
    else:
        status, message = HTTP_STATUS[code], MESSAGES[code]
    error: dict[str, Any] = {"code": code, "message": message}
    if trace is not None:
        error["trace"] = trace
    return AskReply(status, {"error": error}, dict(headers or {}))


_STOP_CODES = ASK_ERROR_CODES | {"busy", "shutting_down", "internal_error"}


class AskService:
    """Ask_Gate, Daily_Budget, the question run and the Ask_Record."""

    def __init__(
        self,
        *,
        ask: AskSettings,
        plan: AskPlan,
        server: Any,
        open_adapter: Callable[[], Any],
        closing: Callable[[], bool],
        clock: Any = None,
        utcnow: Callable[[], datetime] | None = None,
    ) -> None:
        self._ask = ask
        self._plan = plan
        self._server = server
        self._open_adapter = open_adapter  # returns an async context manager
        self._closing = closing
        self._clock = clock if clock is not None else SystemClock()
        self._budget = DailyBudget(ask.daily_limit, utcnow or _utc_now)
        self._in_use = False  # the Ask_Gate
        self._limits = Limits(
            max_turns=ask.max_turns,
            max_tool_calls=ask.max_tool_calls,
            model_timeout=ask.model_timeout_seconds,
            max_answer=ask.max_answer_chars,
            max_result=ask.max_result_chars,
        )

    @property
    def max_question_chars(self) -> int:
        return self._ask.max_question_chars

    @property
    def max_answer_chars(self) -> int:
        return self._ask.max_answer_chars

    def begin(self) -> "AskCall":
        return AskCall(self, self._clock.monotonic(), secrets.token_hex(8))

    # -- used by AskCall ------------------------------------------------------------

    async def _run(self, question: str, prog: Progress, end: float) -> None:
        async with self._open_adapter() as adapter:
            async with Client(self._server, cache=None) as client:
                await run_question(
                    question,
                    port=McpToolPort(client),
                    adapter=adapter,
                    lim=self._limits,
                    clock=self._clock,
                    closing=self._closing,
                    allowed=self._plan.eligible,
                    worst=dict(self._plan.worst_case),
                    end=end,
                    prog=prog,
                )


class AskCall:
    """One request that reached the Ask route handler (after the key check)."""

    def __init__(self, service: AskService, start: float, ask_id: str) -> None:
        self._svc = service
        self._start = start
        self.ask_id = ask_id
        self._done = False
        self._holding = False

    def _record(self, outcome: str, prog: Progress | None) -> None:
        """The one Ask_Record; fixed text, counts and times only."""
        if self._done:
            return
        self._done = True
        extra: dict[str, Any] = {
            "ask_id": self.ask_id,
            "outcome": outcome,
            "model_turns": prog.turns if prog else 0,
            "tool_calls": prog.tool_calls if prog else 0,
            "duration_ms": _ms(self._svc._clock.monotonic() - self._start),
            "model_ms": _ms(prog.model_seconds) if prog else 0,
        }
        if prog is not None and prog.truncated:
            extra["truncated"] = True
        _LOG.info(RECORD_TEXT, extra=extra)

    def reject(self, code: str) -> AskReply:
        """Reject before the question: ``request_invalid`` or ``request_too_large``."""
        try:
            return _error_reply(code)
        finally:
            self._record(code, None)

    async def answer(self, payload: Any) -> AskReply:
        svc = self._svc
        prog = Progress()
        outcome = "internal_error"
        try:
            reply, outcome = await self._answer(payload, prog)
            return reply
        except Exception:  # no text of the exception is kept
            outcome = "internal_error"
            return _error_reply("internal_error", self._trace(prog))
        except BaseException:  # cancellation: record it, then let it go on
            outcome = "shutting_down" if svc._closing() else "internal_error"
            raise
        finally:
            if self._holding:
                self._holding = False
                svc._in_use = False  # the Ask_Gate is released before the record
            self._record(outcome, prog)

    def _trace(self, prog: Progress) -> dict:
        return project_trace(prog, _ms(self._svc._clock.monotonic() - self._start))

    async def _answer(self, payload: Any, prog: Progress) -> tuple[AskReply, str]:
        svc = self._svc
        question = validate_question(payload, svc.max_question_chars)
        if question is None:
            return _error_reply("question_invalid"), "question_invalid"
        if svc._closing():
            return _error_reply("shutting_down"), "shutting_down"
        if svc._in_use:
            return _error_reply("busy", headers={"Retry-After": "1"}), "busy"
        svc._in_use = True  # no await between the test and the set
        self._holding = True
        wait = svc._budget.take()
        if wait is not None:
            reply = _error_reply("daily_limit", headers={"Retry-After": str(wait)})
            return reply, "daily_limit"  # the gate is released by the caller's finally
        end = self._start + svc._ask.timeout_seconds
        await svc._run(question, prog, end)
        return self._finish(prog)

    def _finish(self, prog: Progress) -> tuple[AskReply, str]:
        trace = self._trace(prog)
        code = prog.stop_code
        if code is None and prog.answer is not None:
            body = {"answer": prog.answer, "truncated": bool(prog.truncated), "trace": trace}
            return AskReply(200, body), "ok"
        if code not in _STOP_CODES:
            code = "internal_error"
        headers = {"Retry-After": "1"} if code == "busy" else None
        return _error_reply(code, trace, headers), code


# --- OpenAPI ---------------------------------------------------------------------------

_AUDIT_ITEM_PROPS = {
    "step_index": {"type": "integer"},
    "kind": {"type": "string"},
    "phase": {"type": "string"},
    "iteration": {"type": ["integer", "null"]},
    "signature": {"type": ["string", "null"]},
    "status": {"type": "string"},
    "duration_seconds": {"type": "number"},
}


def _audit_array() -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {k: dict(v) for k, v in _AUDIT_ITEM_PROPS.items()},
            "additionalProperties": False,
            "required": list(_AUDIT_ITEM_PROPS),
        },
    }


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def ask_openapi(max_q: int, max_a: int) -> tuple[dict, dict]:
    """``(path_item, schemas)`` for ``/ask``. Holds no value of any setting but the limits."""
    result_schema = {
        "type": "object",
        "properties": {
            "flow": {"type": "string"},
            "outputs": {
                "type": "object",
                "additionalProperties": {"type": ["string", "integer"]},
            },
            "audit": _audit_array(),
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "step_index": {"type": "integer"},
                    "kind": {"type": "string"},
                    "expected": {"type": "array", "items": {"type": "string"}},
                    "audit": _audit_array(),
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }
    integer = {"type": "integer"}
    steps = {
        "type": "array",
        "items": {
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "tools"},
                        "offered": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["type", "offered"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "model"},
                        "turn": integer,
                        "outcome": {"enum": ["tool_calls", "answer"]},
                        "tool_calls": integer,
                        "duration_ms": integer,
                    },
                    "required": ["type", "turn", "outcome", "tool_calls", "duration_ms"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"const": "tool"},
                        "turn": integer,
                        "id": integer,
                        "tool": {"type": "string"},
                        "arguments": {"type": "object"},
                        "ok": {"type": "boolean"},
                        "code": {"type": "string"},
                        "reason": {"type": "string"},
                        "result": {"oneOf": [result_schema, {"type": "null"}]},
                        "duration_ms": integer,
                        "repeats": integer,
                    },
                    "required": [
                        "type", "turn", "id", "tool", "arguments", "ok", "code",
                        "result", "duration_ms",
                    ],
                    "additionalProperties": False,
                },
            ]
        },
    }
    schemas = {
        "AskTrace": {
            "type": "object",
            "properties": {
                "model_turns": integer,
                "tool_calls": integer,
                "elapsed_ms": integer,
                "steps": steps,
            },
            "required": ["model_turns", "tool_calls", "elapsed_ms", "steps"],
            "additionalProperties": False,
        },
        "AskResponse": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "maxLength": max_a},
                "truncated": {"type": "boolean"},
                "trace": _ref("AskTrace"),
            },
            "required": ["answer", "truncated", "trace"],
            "additionalProperties": False,
        },
        "AskErrorBody": {
            "type": "object",
            "properties": {
                "error": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "trace": _ref("AskTrace"),
                    },
                    "required": ["code", "message"],
                    "additionalProperties": False,
                }
            },
            "required": ["error"],
            "additionalProperties": False,
        },
    }
    by_status: dict[int, set[str]] = {}
    for code, status in ASK_HTTP_STATUS.items():
        by_status.setdefault(status, set()).add(code)
    for code in ("unauthorized", "request_invalid", "request_too_large", "busy",
                 "shutting_down", "internal_error"):
        by_status.setdefault(HTTP_STATUS[code], set()).add(code)
    responses: dict[str, dict] = {
        "200": {
            "description": "The question was answered.",
            "content": {"application/json": {"schema": _ref("AskResponse")}},
        }
    }
    for status in sorted(by_status):
        names = ", ".join(sorted(by_status[status]))
        responses[str(status)] = {
            "description": f"Error. Error codes with this status: {names}.",
            "content": {"application/json": {"schema": _ref("AskErrorBody")}},
        }
    path_item = {
        "post": {
            "operationId": "ask",
            "summary": "Ask a question in plain language; the answer comes with a trace.",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "question": {
                                    "type": "string",
                                    "minLength": 1,
                                    "maxLength": max_q,
                                }
                            },
                            "required": ["question"],
                            "additionalProperties": False,
                        }
                    }
                },
            },
            "responses": responses,
            "security": [{"ApiKeyAuth": []}, {"BearerAuth": []}],
        }
    }
    return path_item, schemas
