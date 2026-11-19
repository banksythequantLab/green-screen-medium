"""The model adapter interface: one async method, plain data in and out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    id: str
    name: str
    arguments_text: str


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """One model reply: a final answer, or tool calls. No field for reasoning."""

    answer: str | None
    tool_calls: tuple[ToolCallRequest, ...]


class ModelError(Exception):
    """A model turn failed. ``kind`` is the only content: no message, no cause text."""

    KINDS = ("unreachable", "refused", "unusable", "busy")

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


class ModelAdapter(Protocol):
    async def complete(
        self,
        messages: list[dict],
        tools: list[dict],
        *,
        timeout_seconds: float,
    ) -> ModelTurn: ...
