"""LLM agent: contextual learning recommendations."""

from pathlib import Path

from backend.models import Concept, RecommendationResult
from backend.utils import llm
from backend.utils.parser import call_with_retry

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_prompt() -> str:
    return (_PROMPTS_DIR / "recommendations.txt").read_text(encoding="utf-8")


def generate_recommendations(
    *,
    focal_concept: str,
    concepts: list[Concept],
    graph_summary: str,
    subgraph_neighbors: list[str],
) -> RecommendationResult:
    payload = {
        "focal_concept": focal_concept,
        "concepts_from_article": [c.model_dump() for c in concepts],
        "graph_summary": graph_summary,
        "subgraph_neighbors": subgraph_neighbors,
    }
    result = call_with_retry(
        call_llm=llm.generate_json,
        prompt_template=_load_prompt(),
        payload=payload,
        model=RecommendationResult,
    )
    if not result.focal_concept:
        result.focal_concept = focal_concept
    return result
