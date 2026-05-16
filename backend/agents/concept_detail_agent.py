"""On-demand concept definition enrichment."""

from pathlib import Path

from backend.graph_manager import GraphManager
from backend.models import ConceptDetail, ConceptDetailResult
from backend.utils import llm
from backend.utils.parser import call_with_retry

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def enrich_definition(name: str, graph: GraphManager) -> ConceptDetail:
    detail = graph.get_concept_detail(name)
    if detail.definition.strip():
        return detail

    template = (_PROMPTS_DIR / "concept_detail.txt").read_text(encoding="utf-8")
    payload = {
        "concept_name": name,
        "graph_context": graph.summary(max_nodes=15),
        "evidence": [q.model_dump() for q in detail.evidence_quotes],
        "neighbors": [n.model_dump() for n in detail.neighbors[:8]],
    }
    result = call_with_retry(
        call_llm=llm.generate_json,
        prompt_template=template,
        payload=payload,
        model=ConceptDetailResult,
    )
    graph.set_definition(name, result.definition)
    graph.persist()
    return graph.get_concept_detail(name)
