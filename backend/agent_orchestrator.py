"""LLM + MCP ingest orchestrator with live SSE agent logs."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

from backend.agent_loop import run_ingest_agent_stream
from backend.json_util import dumps_json, unwrap_mcp_payload
from backend.graph_manager import GraphManager
from backend.models import IngestResponse, PipelineStepEvent

logger = logging.getLogger(__name__)

_TOOL_TO_STEP: dict[str, str] = {
    "extract_article_tool": "extract",
    "get_graph_summary": "graph",
    "extract_concepts": "concepts",
    "extract_relationships": "relationships",
    "merge_graph": "graph",
    "generate_recommendations": "recommendations",
}


def _event(
    step: str,
    status: str,
    message: str,
    *,
    elapsed_ms: float | None = None,
    detail: dict[str, Any] | None = None,
) -> PipelineStepEvent:
    return PipelineStepEvent(
        step=step,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        message=message,
        elapsed_ms=elapsed_ms,
        detail=detail,
    )


def _format_llm_message(item: dict[str, Any]) -> str:
    tc = item.get("tool_calls") or []
    if tc:
        names = ", ".join(
            f"{t.get('name')}({json.dumps(t.get('arguments') or {})})" for t in tc
        )
        return f"Turn {item.get('turn')}: LLM chose tools → {names}"
    text = (item.get("text") or "").strip()
    if text:
        return f"Turn {item.get('turn')}: LLM replied (no tools) — {text[:200]}"
    return f"Turn {item.get('turn')}: LLM response ({item.get('provider')}/{item.get('model')})"


def _parse_tool_payload(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "error", "message": text[:300]}
    if isinstance(data, dict):
        return unwrap_mcp_payload(data)
    return {"status": "error", "message": str(data)[:300]}


def _tool_done_message(name: str, payload: dict[str, Any]) -> str:
    if payload.get("status") == "error":
        return f"{name} failed: {payload.get('message')}"
    if name == "extract_article_tool":
        return f"✓ {name}: «{payload.get('title', '')}» ({payload.get('char_count', 0)} chars)"
    if name == "extract_concepts":
        return f"✓ {name}: {payload.get('concept_count', 0)} concepts"
    if name == "extract_relationships":
        return f"✓ {name}: {payload.get('relationship_count', 0)} relationships"
    if name == "merge_graph":
        return f"✓ {name}: {payload.get('node_count', 0)} nodes, {payload.get('edge_count', 0)} edges"
    return f"✓ {name}: ok"


async def ingest_url_agent_events_async(
    url: str,
    graph: GraphManager | None = None,
) -> AsyncIterator[PipelineStepEvent]:
    gm = graph or GraphManager()
    logger.info("Agent orchestrator SSE start url=%s graph=%s", url, gm.path)

    yield _event(
        "agent_log",
        "running",
        "LLM orchestrator started — model will choose MCP tools each turn",
        detail={"mode": "agent", "url": url},
    )

    try:
        async for item in run_ingest_agent_stream(url, gm.path):
            kind = item.get("type")
            logger.debug("Agent stream event type=%s keys=%s", kind, list(item.keys()))

            if kind == "agent_start":
                yield _event(
                    "agent_log",
                    "running",
                    f"Goal: ingest {item.get('url')}",
                    detail=item,
                )
            elif kind == "tools_registered":
                yield _event(
                    "agent_log",
                    "done",
                    "MCP tools: " + ", ".join(item.get("tools") or []),
                    detail=item,
                )
            elif kind == "llm_turn":
                logger.info("SSE llm_turn turn=%s", item.get("turn"))
                yield _event(
                    "agent_log",
                    "running",
                    _format_llm_message(item),
                    detail=item,
                )
            elif kind == "tool_result":
                name = item.get("tool_name", "")
                raw = item.get("tool_result") or "{}"
                payload = _parse_tool_payload(raw if isinstance(raw, str) else dumps_json(raw))
                step = _TOOL_TO_STEP.get(name, "agent_log")
                status = "error" if payload.get("status") == "error" else "done"
                log_fn = logger.warning if status == "error" else logger.info
                log_fn("SSE tool_result tool=%s status=%s", name, status)
                yield _event(
                    "agent_log",
                    "done" if status == "done" else "error",
                    _tool_done_message(name, payload),
                    detail={
                        "turn": item.get("turn"),
                        "tool_name": name,
                        "tool_args": item.get("tool_args"),
                        "tool_payload": payload,
                    },
                )
                if status == "done" and step != "agent_log":
                    yield _event(step, "done", _tool_done_message(name, payload), detail=payload)
            elif kind == "agent_text":
                yield _event(
                    "agent_log",
                    "done",
                    f"Orchestrator text: {item.get('text', '')[:300]}",
                    detail=item,
                )
            elif kind == "complete":
                detail = unwrap_mcp_payload(item.get("detail") or {})
                result_data = detail.get("result")
                if isinstance(result_data, str):
                    try:
                        result_data = json.loads(result_data)
                    except json.JSONDecodeError as exc:
                        logger.error("complete detail.result is invalid JSON: %s", exc)
                        raise ValueError("Ingest complete event has invalid result JSON") from exc
                if result_data is None:
                    logger.error("complete event missing detail.result keys=%s", list(detail.keys()))
                    raise ValueError("Ingest complete event missing result")
                result = IngestResponse.model_validate(result_data)
                logger.info("SSE ingest complete article=%s", result.article.url)
                yield _event(
                    "done",
                    "done",
                    "Ingest complete",
                    detail={
                        "result": json.loads(result.model_dump_json()),
                        "mermaid_full": item["detail"].get("mermaid_full", ""),
                        "orchestrator_mode": "agent",
                        "agent_trace": item.get("agent_trace"),
                    },
                )
    except Exception as exc:
        logger.error("Agent orchestrator failed url=%s: %s", url, exc, exc_info=True)
        yield _event("error", "error", str(exc))


def ingest_url_agent_events(
    url: str,
    graph: GraphManager | None = None,
) -> Iterator[PipelineStepEvent]:
    """Sync wrapper for non-async callers."""
    import asyncio

    async def _collect() -> list[PipelineStepEvent]:
        out: list[PipelineStepEvent] = []
        async for ev in ingest_url_agent_events_async(url, graph):
            out.append(ev)
        return out

    for ev in asyncio.run(_collect()):
        yield ev
