"""Gemini JSON planner — chooses tool_name + tool_args (Assignment 4 / ownership demo style)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from backend.json_util import dumps_json

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"


class PlannerStep(BaseModel):
    reasoning: str = ""
    tool_name: str
    tool_args: dict[str, Any] = Field(default_factory=dict)
    done: bool = False


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}


def call_gemini_planner(
    api_key: str,
    history: list[dict[str, str]],
    query: str,
    *,
    allowed_tools: list[str],
    model: str | None = None,
) -> PlannerStep:
    """Return structured planner step (reasoning, tool_name, tool_args)."""
    model_name = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
    logger.info(
        "Gemini planner request model=%s history_len=%d allowed_tools=%s",
        model_name,
        len(history),
        allowed_tools,
    )
    logger.debug("Gemini planner query: %s", query[:500])
    prompt = "\n".join(
        [
            "You are the orchestrator for a system-design knowledge graph ingest pipeline.",
            "Return JSON only with keys: reasoning, tool_name, tool_args, done (boolean).",
            "Include exactly one tool per response unless done=true.",
            f"Allowed tool_name values: {', '.join(allowed_tools)}, finish",
            "When all pipeline steps succeeded, set tool_name=finish and done=true.",
            "",
            "Typical order: extract_article_tool → get_graph_summary → extract_concepts "
            "→ extract_relationships → merge_graph → generate_recommendations",
            "",
            "ALL_PAST_INTERACTIONS:",
            dumps_json(history),
            "",
            "CURRENT_QUERY:",
            query,
        ]
    )
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent?key={quote(api_key)}"
    )
    req = Request(
        url=url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(
            {
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.1,
                    "responseMimeType": "application/json",
                },
            }
        ).encode("utf-8"),
    )
    try:
        with urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.error("Gemini HTTP request failed: %s", exc, exc_info=True)
        raise

    text = (
        payload.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "{}")
    )
    if not text or text.strip() == "{}":
        logger.warning("Gemini returned empty planner text; raw keys=%s", list(payload.keys()))

    data = extract_json_object(text)
    step = PlannerStep.model_validate(
        {
            "reasoning": data.get("reasoning", ""),
            "tool_name": data.get("tool_name", ""),
            "tool_args": data.get("tool_args") or {},
            "done": bool(data.get("done", False)),
        }
    )
    logger.info(
        "Gemini planner response tool=%s done=%s",
        step.tool_name,
        step.done,
    )
    return step
