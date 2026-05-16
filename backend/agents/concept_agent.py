"""LLM agent: extract system design concepts from article text."""

from pathlib import Path

from backend.models import ConceptExtractionResult, ExtractedArticle
from backend.utils import llm
from backend.utils.parser import call_with_retry

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_prompt() -> str:
    return (_PROMPTS_DIR / "concept_extraction.txt").read_text(encoding="utf-8")


def extract_concepts(
    article: ExtractedArticle,
    graph_summary: str,
) -> ConceptExtractionResult:
    payload = {
        "article_url": article.url,
        "article_title": article.title,
        "article_text": article.text,
        "existing_graph_summary": graph_summary,
    }
    return call_with_retry(
        call_llm=llm.generate_json,
        prompt_template=_load_prompt(),
        payload=payload,
        model=ConceptExtractionResult,
    )
