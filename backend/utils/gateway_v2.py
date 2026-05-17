"""Thin client for LLM Gateway V2 (/v1/chat) — Session 5 style."""

from __future__ import annotations

import os
from typing import Any

import httpx


class GatewayV2Client:
    """POST /v1/chat with optional cache_system, reasoning, and response_format."""

    def __init__(self, base_url: str | None = None, timeout: float = 600.0) -> None:
        url = base_url or os.getenv("LLM_BASE_URL") or "http://127.0.0.1:8100"
        self.base_url = url.rstrip("/")
        self.timeout = timeout

    def chat(
        self,
        *,
        messages: list[dict[str, Any]] | None = None,
        prompt: str | None = None,
        system: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        max_tokens: int = 8192,
        temperature: float = 0.35,
        cache_system: bool | None = None,
        reasoning: str | None = None,
        response_format: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": messages,
            "prompt": prompt,
            "system": system,
            "model": model,
            "provider": provider,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
            "cache_system": cache_system,
            "reasoning": reasoning,
            "response_format": response_format,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        body = {k: v for k, v in body.items() if v is not None}
        with httpx.Client(timeout=self.timeout) as client:
            r = client.post(f"{self.base_url}/v1/chat", json=body)
            r.raise_for_status()
            return r.json()
