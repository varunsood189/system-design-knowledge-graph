"""Gemini client with optional LLM Gateway fallback."""

import json
import os
import re
from typing import Any
from urllib.parse import quote

import google.generativeai as genai
import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gemini-2.5-flash-lite"
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def is_configured() -> bool:
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        return True
    return bool((os.getenv("LLM_BASE_URL") or "").strip())


def backend_name() -> str:
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        return "gemini"
    if (os.getenv("LLM_BASE_URL") or "").strip():
        return "gateway"
    return "none"


def _strip_json_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_json_dict(text: str) -> dict[str, Any]:
    t = _strip_json_fence(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", t)
        if not match:
            raise ValueError(f"No JSON object in model output: {t[:200]!r}") from None
        return json.loads(match.group(0))


def configure_gemini() -> str:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    genai.configure(api_key=api_key)
    return os.getenv("GEMINI_MODEL", DEFAULT_MODEL)


def _generate_gemini(prompt: str, user_content: str, schema_hint: str | None = None) -> str:
    model_name = configure_gemini()
    system = prompt.strip()
    if schema_hint:
        system = f"{system}\n\n{schema_hint}"
    full_prompt = f"{system}\n\n---\n\n{user_content.strip()}"

    model = genai.GenerativeModel(
        model_name=model_name,
        generation_config=genai.GenerationConfig(
            response_mime_type="application/json",
            temperature=0.35,
        ),
    )
    response = model.generate_content(full_prompt)
    if not response.text:
        raise RuntimeError("Gemini returned an empty response")
    return response.text


def _generate_gateway(prompt: str, user_content: str, schema: dict[str, Any] | None = None) -> str:
    base = (os.getenv("LLM_BASE_URL") or "http://127.0.0.1:8100").rstrip("/")
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL)
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    messages = [
        {"role": "system", "content": prompt.strip()},
        {"role": "user", "content": user_content.strip()},
    ]
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.35,
    }
    if schema:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "Response", "strict": True, "schema": schema},
        }

    with httpx.Client(timeout=120.0) as client:
        r = client.post(f"{base}/v1/chat/completions", headers=headers, json=body)
        r.raise_for_status()
        data = r.json()

    if isinstance(data.get("parsed"), dict):
        return json.dumps(data["parsed"])

    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Gateway returned no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    parsed = message.get("parsed")
    if isinstance(parsed, dict):
        return json.dumps(parsed)
    raise RuntimeError("Gateway response missing JSON content")


def generate_json(
    prompt_template: str,
    user_content: str,
    *,
    schema: dict[str, Any] | None = None,
) -> str:
    """
    Call Gemini (preferred) or LLM Gateway and return raw JSON text.
    """
    if (os.getenv("GEMINI_API_KEY") or "").strip():
        schema_hint = None
        if schema:
            schema_hint = (
                "Respond with one JSON object only matching this schema:\n"
                + json.dumps(schema, ensure_ascii=False)
            )
        return _generate_gemini(prompt_template, user_content, schema_hint)

    if (os.getenv("LLM_BASE_URL") or "").strip():
        return _generate_gateway(prompt_template, user_content, schema)

    raise RuntimeError(
        "No LLM configured. Set GEMINI_API_KEY or LLM_BASE_URL in .env"
    )


def generate_json_with_schema(
    prompt_template: str,
    payload: dict[str, Any],
    schema_model: type,
) -> str:
    user_content = json.dumps(payload, indent=2, ensure_ascii=False)
    schema = schema_model.model_json_schema()
    return generate_json(prompt_template, user_content, schema=schema)
