"""LLM agent: infer relationships between concepts."""

from pathlib import Path

from backend.models import ConceptExtractionResult, ExtractedArticle, RelationshipExtractionResult
from backend.utils import llm
from backend.utils.parser import call_with_retry

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_prompt() -> str:
    return (_PROMPTS_DIR / "relationship_reasoning.txt").read_text(encoding="utf-8")


def extract_relationships(
    article: ExtractedArticle,
    concepts: ConceptExtractionResult,
    graph_summary: str,
) -> RelationshipExtractionResult:
    excerpt = article.text[:3000]
    payload = {
        "article_url": article.url,
        "article_excerpt": excerpt,
        "concepts": [c.model_dump() for c in concepts.concepts],
        "existing_graph_summary": graph_summary,
    }
    return call_with_retry(
        call_llm=llm.generate_json,
        prompt_template=_load_prompt(),
        payload=payload,
        model=RelationshipExtractionResult,
    )
