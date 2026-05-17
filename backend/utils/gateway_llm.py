"""Load llm_gatewayV2.LLM client (same as agent5.py)."""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _find_gateway_v2_dir() -> Path:
    candidates = [
        PROJECT_ROOT / "llm_gatewayV2",
        PROJECT_ROOT.parent / "llm_gatewayV2",
    ]
    candidates.extend(sorted(PROJECT_ROOT.parent.glob("*/llm_gatewayV2")))
    for path in candidates:
        if (path / "client.py").is_file():
            return path.resolve()
    raise FileNotFoundError(
        "llm_gatewayV2 not found. Expected sibling folder with client.py "
        "(sibling llm_gatewayV2/ folder with client.py)."
    )


@lru_cache(maxsize=1)
def get_llm_class() -> type:
    gw_dir = _find_gateway_v2_dir()
    path_str = str(gw_dir)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)
    from client import LLM  # noqa: E402

    return LLM


def create_llm() -> Any:
    """LLM client pointed at LLM_BASE_URL / port 8100."""
    base = (os.getenv("LLM_BASE_URL") or os.getenv("LLM_GATEWAY_V2_URL") or "http://127.0.0.1:8100").rstrip("/")
    timeout = float(os.getenv("LLM_GATEWAY_TIMEOUT", "600"))
    return get_llm_class()(base_url=base, timeout=timeout)
