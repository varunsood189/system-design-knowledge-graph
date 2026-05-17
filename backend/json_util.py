"""JSON helpers for MCP / Pydantic / fastmcp tool results."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any


def to_json_safe(obj: Any) -> Any:
    """Recursively convert values to JSON-serializable primitives."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_safe(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return to_json_safe(obj.model_dump(mode="json"))
        except TypeError:
            return to_json_safe(obj.model_dump())
    if is_dataclass(obj) and not isinstance(obj, type):
        return to_json_safe(asdict(obj))
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return to_json_safe(vars(obj))
    return str(obj)


def unwrap_mcp_payload(data: dict[str, Any]) -> dict[str, Any]:
    """
    Unwrap fastmcp tool outputs that nest JSON strings in a ``result`` field.

    MCP tools return ``json.dumps({"status": "ok", ...})``; fastmcp often exposes
    ``{"status": "ok", "result": "{\\"status\\": \\"ok\\", ...}"}``.
    """
    if not isinstance(data, dict):
        return data

    inner = data.get("result")
    if isinstance(inner, str):
        try:
            parsed = json.loads(inner)
        except json.JSONDecodeError:
            return data
        if isinstance(parsed, dict):
            merged = {k: v for k, v in data.items() if k != "result"}
            merged.update(parsed)
            return unwrap_mcp_payload(merged)

    return data


def dumps_json(obj: Any, *, indent: int | None = None, max_len: int | None = None) -> str:
    """json.dumps via to_json_safe; never raises TypeError."""
    text = json.dumps(
        to_json_safe(obj),
        ensure_ascii=False,
        indent=indent,
        default=str,
    )
    if max_len is not None and len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text
