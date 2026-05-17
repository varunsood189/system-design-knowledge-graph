"""Ingest entrypoint — LLM orchestrator only (no fixed Python step pipeline)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator

from backend.agent_loop import agent_orchestrator_available, agent_orchestrator_error
from backend.agent_orchestrator import ingest_url_agent_events_async
from backend.graph_manager import GraphManager
from backend.models import IngestResponse, PipelineStepEvent


def _require_agent() -> None:
    if not agent_orchestrator_available():
        raise RuntimeError(agent_orchestrator_error())


async def ingest_url_events_async(
    url: str,
    graph: GraphManager | None = None,
) -> AsyncIterator[PipelineStepEvent]:
    _require_agent()
    async for event in ingest_url_agent_events_async(url, graph):
        yield event


def ingest_url_events(
    url: str,
    graph: GraphManager | None = None,
) -> Iterator[PipelineStepEvent]:
    _require_agent()

    async def _collect() -> list[PipelineStepEvent]:
        events: list[PipelineStepEvent] = []
        async for ev in ingest_url_events_async(url, graph):
            events.append(ev)
        return events

    for ev in asyncio.run(_collect()):
        yield ev


def ingest_url(url: str, graph: GraphManager | None = None) -> IngestResponse:
    result: IngestResponse | None = None
    for event in ingest_url_events(url, graph):
        if event.step == "done" and event.detail and "result" in event.detail:
            result = IngestResponse.model_validate(event.detail["result"])
        if event.step == "error":
            raise ValueError(event.message)
    if result is None:
        raise RuntimeError("Ingest finished without a result")
    return result
