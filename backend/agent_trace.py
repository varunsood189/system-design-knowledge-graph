"""Structured agent trace (Session 5 style)."""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    kind: Literal["llm_call", "tool_call", "agent_done"]
    turn: int
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read: int | None = None
    cache_create: int | None = None
    dialect: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: str | None = None
    text: str | None = None
    payload: dict[str, Any] | None = None


class AgentTrace(BaseModel):
    goal: str
    events: list[TraceEvent] = Field(default_factory=list)
    started_at: float = Field(default_factory=time.time)

    def add(self, **kwargs: Any) -> None:
        self.events.append(TraceEvent(**kwargs))

    def summary(self) -> dict[str, Any]:
        llm_calls = [e for e in self.events if e.kind == "llm_call"]
        tool_calls = [e for e in self.events if e.kind == "tool_call"]
        return {
            "llm_turns": len(llm_calls),
            "tool_calls": len(tool_calls),
            "total_in_tokens": sum(e.input_tokens or 0 for e in llm_calls),
            "total_out_tokens": sum(e.output_tokens or 0 for e in llm_calls),
            "cache_reads": sum(e.cache_read or 0 for e in llm_calls),
            "wall_clock_s": round(time.time() - self.started_at, 2),
        }
