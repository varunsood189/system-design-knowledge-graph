"""JSON extraction and LLM call helpers with Pydantic validation retry."""

import json
import re
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def extract_json_object(text: str) -> dict[str, Any] | list[Any]:
    text = text.strip()
    if not text:
        raise ValueError("Empty model response")

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])

    raise ValueError("Could not parse JSON from model response")


def safe_parse_json(text: str) -> dict[str, Any]:
    data = extract_json_object(text)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object at the top level")
    return data


def validate_model(data: dict[str, Any], model: type[T]) -> T:
    return model.model_validate(data)


def call_with_retry(
    *,
    call_llm: Callable[[str, str], str],
    prompt_template: str,
    payload: dict[str, Any],
    model: type[T],
    max_retries: int = 2,
) -> T:
    """Call LLM, parse JSON, validate with Pydantic; retry with error details on failure."""
    user_content = json.dumps(payload, indent=2, ensure_ascii=False)
    last_error: str | None = None

    for attempt in range(max_retries + 1):
        prompt = prompt_template
        if attempt > 0 and last_error:
            prompt = (
                f"{prompt_template}\n\n"
                f"---\nVALIDATION ERROR (fix and return valid JSON only):\n{last_error}\n"
            )
        try:
            raw = call_llm(prompt, user_content)
            data = safe_parse_json(raw)
            return validate_model(data, model)
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            if attempt >= max_retries:
                raise ValueError(
                    f"LLM output failed validation after {max_retries + 1} attempts: {last_error}"
                ) from exc

    raise RuntimeError("unreachable")
