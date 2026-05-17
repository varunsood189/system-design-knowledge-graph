"""LLM planner + fastmcp tools (ownership-demo style)."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastmcp.client import Client

from backend.agent_trace import AgentTrace
from backend.json_util import dumps_json, to_json_safe, unwrap_mcp_payload
from backend.llm_planner import PlannerStep, call_gemini_planner
from backend.utils.llm import _env_bool

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER = PROJECT_ROOT / "mcp_server.py"

FINISH_TOOLS = frozenset({"finish", "ingest_complete", "done"})


def _use_agent_orchestrator() -> bool:
    raw = (os.getenv("USE_AGENT_ORCHESTRATOR") or "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


def agent_orchestrator_available() -> bool:
    if not _use_agent_orchestrator():
        return False
    return bool((os.getenv("GEMINI_API_KEY") or "").strip())


def agent_orchestrator_error() -> str:
    if not _use_agent_orchestrator():
        return "USE_AGENT_ORCHESTRATOR is disabled."
    return (
        "LLM orchestrator requires GEMINI_API_KEY in .env "
        "(Gemini JSON planner chooses each MCP tool)."
    )


def _coerce_mcp_payload(data: Any) -> dict[str, Any]:
    """Normalize fastmcp .data (str, dict, or *Output Pydantic models) to a dict."""
    safe = to_json_safe(data)
    if isinstance(safe, str):
        import json

        try:
            parsed = json.loads(safe)
            if isinstance(parsed, dict):
                logger.debug("MCP payload parsed from JSON string keys=%s", list(parsed.keys()))
                return parsed
        except json.JSONDecodeError:
            logger.warning("MCP payload is non-JSON string len=%d", len(safe))
            return {"status": "ok", "raw": safe}
        return {"status": "ok", "raw": safe}
    if isinstance(safe, dict):
        unwrapped = unwrap_mcp_payload(safe)
        if "status" in unwrapped:
            return unwrapped
        return {"status": "ok", **unwrapped}
    return {"status": "ok", "data": safe}


def _tool_result_payload(result: Any) -> dict[str, Any]:
    type_name = type(result).__name__
    if getattr(result, "is_error", False):
        msg = str(getattr(result, "content", result))
        logger.error("MCP tool returned error (%s): %s", type_name, msg[:500])
        return {"status": "error", "message": msg}

    data = getattr(result, "data", None)
    if data is not None:
        logger.debug("MCP result.data type=%s", type(data).__name__)
        return _coerce_mcp_payload(data)

    content = getattr(result, "content", None)
    if content is not None:
        logger.debug("MCP result.content type=%s", type(content).__name__)
        blocks: list[Any] = content if isinstance(content, list) else [content]
        texts: list[str] = []
        for block in blocks:
            if hasattr(block, "text"):
                texts.append(str(block.text))
            else:
                texts.append(str(block))
        combined = "\n".join(texts)
        if combined.strip():
            return _coerce_mcp_payload(combined)

    logger.warning("MCP result had no data/content (%s); returning empty ok", type_name)
    return {"status": "ok"}


async def run_planner_loop_stream(
    client: Client,
    url: str,
    tool_names: list[str],
    trace: AgentTrace,
    *,
    max_turns: int | None = None,
) -> AsyncIterator[dict[str, Any]]:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    if max_turns is None:
        max_turns = int(os.getenv("AGENT_MAX_TURNS", "12"))

    allowed = list(tool_names) + ["finish"]
    history: list[dict[str, str]] = []
    goal = f"Ingest engineering blog URL into the knowledge graph: {url}"

    logger.info(
        "Planner loop start url=%s max_turns=%d tools=%s",
        url,
        max_turns,
        ", ".join(tool_names),
    )

    for turn in range(1, max_turns + 1):
        query = (
            f"{goal} — Turn {turn}: choose the next MCP tool and tool_args. "
            "If the pipeline is complete, return tool_name=finish and done=true."
        )
        logger.info("─── turn %d: calling Gemini planner ───", turn)

        try:
            step: PlannerStep = await asyncio.to_thread(
                call_gemini_planner,
                api_key,
                history,
                query,
                allowed_tools=allowed,
            )
        except Exception as exc:
            logger.error("Gemini planner failed on turn %d: %s", turn, exc, exc_info=True)
            raise RuntimeError(f"Gemini planner failed: {exc}") from exc

        logger.info(
            "turn %d planner → tool=%s done=%s reasoning=%s",
            turn,
            step.tool_name,
            step.done,
            (step.reasoning or "")[:120],
        )
        if _env_bool("AGENT_DEBUG", False):
            logger.debug("turn %d tool_args=%s", turn, dumps_json(step.tool_args))

        trace.add(
            kind="llm_call",
            turn=turn,
            provider="gemini",
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            text=step.reasoning,
            payload={"tool_name": step.tool_name, "tool_args": step.tool_args, "done": step.done},
        )

        yield {
            "type": "llm_turn",
            "turn": turn,
            "provider": "gemini",
            "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
            "text": step.reasoning,
            "tool_calls": (
                [{"name": step.tool_name, "arguments": step.tool_args}]
                if step.tool_name and step.tool_name not in FINISH_TOOLS
                else []
            ),
            "planner": step.model_dump(),
        }

        if step.done or step.tool_name in FINISH_TOOLS:
            logger.info("turn %d: planner signaled finish (%s)", turn, step.tool_name)
            yield {"type": "agent_text", "turn": turn, "text": "INGEST_COMPLETE"}
            return

        tool_name = step.tool_name
        if tool_name not in tool_names:
            err = f"Unknown tool {tool_name!r}; allowed: {allowed}"
            logger.warning("turn %d: %s", turn, err)
            trace.add(kind="tool_call", turn=turn, tool_name=tool_name, tool_result=err)
            err_payload = {"status": "error", "message": err}
            yield {
                "type": "tool_result",
                "turn": turn,
                "tool_name": tool_name,
                "tool_args": step.tool_args,
                "tool_result": dumps_json(err_payload),
            }
            history.extend(
                [
                    {"role": "user", "content": query},
                    {"role": "assistant", "content": dumps_json(step.model_dump())},
                    {"role": "tool", "content": err},
                ]
            )
            continue

        args = dict(step.tool_args)
        if tool_name == "extract_article_tool" and "url" not in args:
            args["url"] = url

        logger.info("turn %d: MCP call %s args_keys=%s", turn, tool_name, list(args.keys()))

        try:
            result = await client.call_tool(tool_name, args, raise_on_error=False)
        except Exception as exc:
            logger.error(
                "turn %d: MCP call_tool(%s) raised: %s",
                turn,
                tool_name,
                exc,
                exc_info=True,
            )
            raise

        try:
            payload = _tool_result_payload(result)
            payload_json = dumps_json(payload)
        except Exception as exc:
            logger.error(
                "turn %d: failed to serialize MCP result for %s: %s (data_type=%s)",
                turn,
                tool_name,
                exc,
                type(getattr(result, "data", None)).__name__,
                exc_info=True,
            )
            raise RuntimeError(f"Could not serialize tool result for {tool_name}: {exc}") from exc

        status = payload.get("status", "ok")
        if status == "error":
            logger.warning(
                "turn %d: %s returned error: %s",
                turn,
                tool_name,
                payload.get("message", payload),
            )
        else:
            logger.info(
                "turn %d: %s ok payload_preview=%s",
                turn,
                tool_name,
                payload_json[:300],
            )

        trace.add(
            kind="tool_call",
            turn=turn,
            tool_name=tool_name,
            tool_args=args,
            tool_result=dumps_json(payload, max_len=4000),
        )

        yield {
            "type": "tool_result",
            "turn": turn,
            "tool_name": tool_name,
            "tool_args": args,
            "tool_result": payload_json,
        }

        history.extend(
            [
                {"role": "user", "content": query},
                {"role": "assistant", "content": dumps_json(step.model_dump())},
                {"role": "tool", "content": payload_json},
            ]
        )

    logger.error("Planner exceeded max_turns=%d for url=%s", max_turns, url)
    raise RuntimeError(f"Planner exceeded max_turns={max_turns}")


async def run_ingest_agent_stream(
    url: str,
    graph_path: Path,
) -> AsyncIterator[dict[str, Any]]:
    trace = AgentTrace(goal=f"Ingest: {url}")
    logger.info("Agent ingest start url=%s graph_path=%s", url, graph_path)
    yield {"type": "agent_start", "url": url, "goal": trace.goal}

    os.environ["GRAPH_PATH"] = str(graph_path)
    server_path = str(MCP_SERVER)
    logger.info("Connecting fastmcp client server=%s", server_path)

    try:
        async with Client(server_path) as client:
            tools = await client.list_tools()
            tool_names = [t.name for t in tools if t.name != "get_ingest_result"]
            logger.info("MCP connected tools=%s", ", ".join(tool_names))
            yield {"type": "tools_registered", "tools": tool_names}

            async for event in run_planner_loop_stream(client, url, tool_names, trace):
                yield event

            logger.info("Planner finished; calling get_ingest_result")
            final = await client.call_tool("get_ingest_result", {})
            if getattr(final, "is_error", False):
                msg = str(getattr(final, "content", final))
                logger.error("get_ingest_result error: %s", msg)
                raise RuntimeError(msg)

            detail: Any = getattr(final, "data", None)
            if detail is not None:
                detail = to_json_safe(detail)
            if isinstance(detail, str):
                import json

                detail = json.loads(detail)
            if not isinstance(detail, dict):
                detail = _tool_result_payload(final)
            else:
                detail = unwrap_mcp_payload(detail)

            if detail.get("status") == "error":
                msg = detail.get("message", "get_ingest_result failed")
                logger.error("get_ingest_result payload error: %s", msg)
                raise RuntimeError(msg)

            stats = {}
            if isinstance(detail.get("result"), dict):
                stats = detail["result"].get("graph_stats") or {}
            logger.info(
                "Ingest complete nodes=%s edges=%s",
                stats.get("node_count", "?"),
                stats.get("edge_count", "?"),
            )
            trace.add(kind="agent_done", turn=0, payload=trace.summary())
            yield {
                "type": "complete",
                "detail": detail,
                "agent_trace": trace.model_dump(),
            }
    except Exception as exc:
        logger.error("Agent ingest failed url=%s: %s", url, exc, exc_info=True)
        raise
