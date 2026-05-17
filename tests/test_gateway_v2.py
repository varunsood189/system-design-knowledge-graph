"""Gateway V2 client wiring (no live gateway required)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.utils import llm
from backend.utils.gateway_v2 import GatewayV2Client


def test_gateway_v2_client_parses_parsed_field():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "provider": "gemini",
        "model": "test",
        "parsed": {"reasoning": "ok", "confidence": 1.0, "status": "ok", "concepts": []},
        "text": "",
    }
    with patch("httpx.Client") as client_cls:
        client_cls.return_value.__enter__.return_value.post.return_value = mock_response
        reply = GatewayV2Client(base_url="http://test:8100").chat(
            messages=[{"role": "user", "content": "{}"}],
            system="sys",
        )
    assert reply["parsed"]["status"] == "ok"


def test_generate_gateway_v2_uses_structured_output(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8100")
    monkeypatch.setenv("LLM_GATEWAY_API", "v2")

    fake_reply = {
        "parsed": {
            "reasoning": "step",
            "confidence": 0.9,
            "status": "ok",
            "concepts": [],
        },
        "text": "",
    }

    with patch.object(GatewayV2Client, "chat", return_value=fake_reply) as chat:
        raw = llm.generate_json("prompt", '{"x": 1}', schema={"type": "object"})
        data = json.loads(raw)
        assert data["status"] == "ok"
        assert chat.call_args.kwargs["cache_system"] is True
        assert chat.call_args.kwargs["reasoning"] == "off"
        rf = chat.call_args.kwargs["response_format"]
        assert rf["type"] == "json_schema"
        assert rf["strict"] is True


def test_create_llm_uses_gateway_client(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8100")
    from backend.utils.gateway_llm import create_llm

    client = create_llm()
    assert client.base_url == "http://127.0.0.1:8100"


def test_backend_name_gateway_v2(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8100")
    monkeypatch.setenv("LLM_GATEWAY_API", "v2")
    assert llm.backend_name() == "gateway-v2"


def test_backend_name_gateway_v1(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8099")
    monkeypatch.setenv("LLM_GATEWAY_API", "v1")
    assert llm.backend_name() == "gateway-v1"
