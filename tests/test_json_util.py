"""JSON serialization helpers for fastmcp Pydantic tool outputs."""

import json

from backend.agent_loop import _coerce_mcp_payload, _tool_result_payload
from backend.json_util import dumps_json, to_json_safe, unwrap_mcp_payload


class _FakeToolOutput:
    """Mimics fastmcp extract_article_toolOutput."""

    def model_dump(self, mode: str = "json") -> dict:
        return {
            "status": "ok",
            "result": json.dumps(
                {
                    "status": "ok",
                    "title": "Shopify Guide",
                    "url": "https://example.com",
                    "char_count": 8015,
                    "excerpt": "For every initiative…",
                }
            ),
        }


def test_unwrap_mcp_payload_nested_result_string():
    wrapped = {
        "status": "ok",
        "result": '{"status": "ok", "concept_count": 9, "confidence": 0.9}',
    }
    inner = unwrap_mcp_payload(wrapped)
    assert inner["concept_count"] == 9
    assert inner["status"] == "ok"
    assert "result" not in inner or not isinstance(inner.get("result"), str)


def test_coerce_mcp_payload_fastmcp_style():
    payload = _coerce_mcp_payload(_FakeToolOutput())
    assert payload["char_count"] == 8015
    assert payload["title"] == "Shopify Guide"


def test_tool_result_payload_pydantic_nested():
    class FakeResult:
        is_error = False
        data = _FakeToolOutput()

    payload = _tool_result_payload(FakeResult())
    assert payload["char_count"] == 8015


def test_unwrap_get_ingest_result_shape():
    ingest_inner = {"article": {"url": "https://x", "title": "T", "text": "body"}}
    wrapped = {
        "status": "ok",
        "result": json.dumps(
            {
                "status": "ok",
                "result": ingest_inner,
                "mermaid_full": "graph TD",
            }
        ),
    }
    detail = unwrap_mcp_payload(wrapped)
    assert detail["mermaid_full"] == "graph TD"
    assert detail["result"]["article"]["url"] == "https://x"


def test_to_json_safe_pydantic_like():
    safe = to_json_safe(_FakeToolOutput())
    assert "result" in safe
    dumps_json(safe)


def test_dumps_json_nested_output():
    payload = {"status": "ok", "data": _FakeToolOutput()}
    text = dumps_json(payload)
    parsed = json.loads(text)
    assert "result" in parsed["data"]
