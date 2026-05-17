"""Agent orchestrator flags and MCP tool smoke tests."""

import json
from unittest.mock import patch

from backend.agent_loop import agent_orchestrator_available
from backend.llm_planner import PlannerStep, extract_json_object
from backend.models import ExtractedArticle


def test_agent_mode_requires_gemini_key(monkeypatch):
    monkeypatch.setenv("USE_AGENT_ORCHESTRATOR", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert agent_orchestrator_available() is True

    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert agent_orchestrator_available() is False


def test_extract_json_object_from_fence():
    raw = '```json\n{"tool_name": "extract_article_tool", "tool_args": {}}\n```'
    data = extract_json_object(raw)
    assert data["tool_name"] == "extract_article_tool"


def test_planner_step_model():
    step = PlannerStep.model_validate(
        {"reasoning": "fetch", "tool_name": "extract_article_tool", "tool_args": {"url": "http://x"}}
    )
    assert step.tool_name == "extract_article_tool"


def test_mcp_extract_article_tool():
    import mcp_server as srv

    article = ExtractedArticle(
        url="https://example.com/post",
        title="Test Post",
        text="Kafka partitions and replication.",
    )
    with patch("mcp_server.extract_article", return_value=article):
        raw = srv.extract_article_tool("https://example.com/post")
    data = json.loads(raw)
    assert data["status"] == "ok"
    assert data["char_count"] == len(article.text)
