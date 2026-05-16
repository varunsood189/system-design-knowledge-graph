"""Multi-step ingest pipeline: extract → concepts → relationships → graph → recommendations."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

from backend.agents import concept_agent, recommendation_agent, relationship_agent
from backend.extractor import extract_article
from backend.graph_manager import GraphManager
from backend.models import GraphStats, IngestResponse, PipelineStepEvent, PipelineTrace


def _event(
    step: str,
    status: str,
    message: str,
    *,
    elapsed_ms: float | None = None,
    detail: dict | None = None,
) -> PipelineStepEvent:
    return PipelineStepEvent(
        step=step,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        message=message,
        elapsed_ms=elapsed_ms,
        detail=detail,
    )


def ingest_url_events(
    url: str, graph: GraphManager | None = None
) -> Iterator[PipelineStepEvent]:
    """Yield progress events, then a final 'done' event with full IngestResponse in detail."""
    gm = graph or GraphManager()
    trace = PipelineTrace()

    try:
        yield _event(
            "extract",
            "running",
            "Step 1/5: Downloading and extracting article text (trafilatura, no LLM)…",
        )
        t0 = time.perf_counter()
        article = extract_article(url)
        trace.extract_ms = (time.perf_counter() - t0) * 1000
        excerpt = article.text[:500] + ("…" if len(article.text) > 500 else "")
        yield _event(
            "extract",
            "done",
            f"Extracted «{article.title}» ({len(article.text)} chars)",
            elapsed_ms=trace.extract_ms,
            detail={
                "title": article.title,
                "url": article.url,
                "excerpt": excerpt,
                "char_count": len(article.text),
            },
        )

        graph_summary = gm.summary()

        yield _event(
            "concepts",
            "running",
            "Step 2/5: LLM call #1 — extracting system-design concepts from the article…",
        )
        t1 = time.perf_counter()
        concepts = concept_agent.extract_concepts(article, graph_summary)
        trace.concepts_ms = (time.perf_counter() - t1) * 1000
        yield _event(
            "concepts",
            "done",
            f"Found {len(concepts.concepts)} concepts (confidence {concepts.confidence:.0%})",
            elapsed_ms=trace.concepts_ms,
            detail={
                "concept_count": len(concepts.concepts),
                "confidence": concepts.confidence,
                "reasoning_preview": concepts.reasoning[:400],
                "self_check": concepts.self_check,
                "names": [c.name for c in concepts.concepts],
            },
        )

        yield _event(
            "relationships",
            "running",
            "Step 3/5: LLM call #2 — inferring prerequisites and relationships…",
        )
        t2 = time.perf_counter()
        relationships = relationship_agent.extract_relationships(
            article, concepts, graph_summary
        )
        trace.relationships_ms = (time.perf_counter() - t2) * 1000
        yield _event(
            "relationships",
            "done",
            f"Inferred {len(relationships.relationships)} relationships",
            elapsed_ms=trace.relationships_ms,
            detail={
                "relationship_count": len(relationships.relationships),
                "confidence": relationships.confidence,
                "reasoning_preview": relationships.reasoning[:400],
            },
        )

        yield _event(
            "graph",
            "running",
            "Step 4/5: Merging into persistent knowledge graph (data/graph.json)…",
        )
        t3 = time.perf_counter()
        gm.merge_concepts(concepts.concepts, article.url)
        gm.merge_relationships(relationships.relationships)
        gm.register_article(article.url, article.title, len(concepts.concepts))
        snapshot = gm.persist()
        trace.graph_ms = (time.perf_counter() - t3) * 1000
        yield _event(
            "graph",
            "done",
            f"Graph saved: {len(snapshot.nodes)} concepts, {len(snapshot.edges)} edges total",
            elapsed_ms=trace.graph_ms,
            detail={
                "node_count": len(snapshot.nodes),
                "edge_count": len(snapshot.edges),
            },
        )

        focal = gm.focal_concept(concepts.concepts)
        neighbors = gm.subgraph_neighbors(focal)

        yield _event(
            "recommendations",
            "running",
            f"Step 5/5: LLM call #3 — learning path for «{focal}»…",
        )
        t4 = time.perf_counter()
        recommendations = recommendation_agent.generate_recommendations(
            focal_concept=focal,
            concepts=concepts.concepts,
            graph_summary=gm.summary(),
            subgraph_neighbors=neighbors,
        )
        trace.recommendations_ms = (time.perf_counter() - t4) * 1000
        yield _event(
            "recommendations",
            "done",
            "Recommendations ready",
            elapsed_ms=trace.recommendations_ms,
            detail={
                "focal_concept": recommendations.focal_concept,
                "prerequisites": recommendations.prerequisites,
                "learn_next": recommendations.learn_next,
            },
        )

        mermaid_focal = gm.to_mermaid(focal)
        mermaid_full = gm.to_full_mermaid()
        stats = GraphStats(
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
        )
        response = IngestResponse(
            article=article,
            concepts=concepts,
            relationships=relationships,
            recommendations=recommendations,
            graph=snapshot,
            graph_stats=stats,
            mermaid=mermaid_focal,
            trace=trace,
        )
        yield _event(
            "done",
            "done",
            "Pipeline complete",
            detail={
                "result": json.loads(response.model_dump_json()),
                "mermaid_full": mermaid_full,
            },
        )
    except Exception as exc:
        yield _event("error", "error", str(exc))


def ingest_url(url: str, graph: GraphManager | None = None) -> IngestResponse:
    """Run full pipeline and return final response (non-streaming)."""
    result: IngestResponse | None = None
    for event in ingest_url_events(url, graph):
        if event.step == "done" and event.detail and "result" in event.detail:
            result = IngestResponse.model_validate(event.detail["result"])
        if event.step == "error":
            raise ValueError(event.message)
    if result is None:
        raise RuntimeError("Pipeline finished without a result")
    return result
