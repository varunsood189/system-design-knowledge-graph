"""
MCP server for knowledge-graph ingest tools (Session 5 / agent5 style).

Launched as a subprocess by backend/agent_loop.py over stdio.
Set GRAPH_PATH to the same JSON file as the FastAPI GraphManager.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from mcp.server.fastmcp import FastMCP

from backend.agents import concept_agent, recommendation_agent, relationship_agent
from backend.extractor import extract_article
from backend.graph_manager import DEFAULT_GRAPH_PATH, GraphManager
from backend.models import (
    ConceptExtractionResult,
    GraphStats,
    IngestResponse,
    PipelineTrace,
    RelationshipExtractionResult,
)

mcp = FastMCP("knowledge-graph-server")
logger = logging.getLogger("mcp_server")

_state: dict[str, Any] = {
    "article": None,
    "concepts": None,
    "relationships": None,
    "recommendations": None,
    "snapshot": None,
    "trace": PipelineTrace(),
}


def _graph() -> GraphManager:
    path = os.getenv("GRAPH_PATH", str(DEFAULT_GRAPH_PATH))
    return GraphManager(path=Path(path))


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


def _err(message: str) -> str:
    return json.dumps({"status": "error", "message": message}, ensure_ascii=False)


@mcp.tool()
def extract_article_tool(url: str) -> str:
    """Download and extract article text from a blog URL (trafilatura). Call first."""
    logger.info("extract_article_tool url=%s", url)
    try:
        article = extract_article(url)
        _state["article"] = article
        _state["concepts"] = None
        _state["relationships"] = None
        _state["recommendations"] = None
        _state["snapshot"] = None
        excerpt = article.text[:500] + ("…" if len(article.text) > 500 else "")
        logger.info("extract_article_tool ok title=%s chars=%d", article.title, len(article.text))
        return _ok(
            {
                "title": article.title,
                "url": article.url,
                "char_count": len(article.text),
                "excerpt": excerpt,
            }
        )
    except Exception as exc:
        logger.error("extract_article_tool failed: %s", exc, exc_info=True)
        return _err(str(exc))


@mcp.tool()
def get_graph_summary() -> str:
    """Return a short summary of the persisted knowledge graph."""
    logger.info("get_graph_summary")
    try:
        return _ok({"summary": _graph().summary()})
    except Exception as exc:
        logger.error("get_graph_summary failed: %s", exc, exc_info=True)
        return _err(str(exc))


@mcp.tool()
def extract_concepts() -> str:
    """Run LLM concept extraction on the extracted article. Requires extract_article_tool first."""
    logger.info("extract_concepts")
    article = _state.get("article")
    if article is None:
        logger.warning("extract_concepts called without article")
        return _err("Call extract_article_tool before extract_concepts")
    try:
        gm = _graph()
        concepts = concept_agent.extract_concepts(article, gm.summary())
        _state["concepts"] = concepts
        logger.info("extract_concepts ok count=%d", len(concepts.concepts))
        return _ok(
            {
                "concept_count": len(concepts.concepts),
                "confidence": concepts.confidence,
                "names": [c.name for c in concepts.concepts],
                "reasoning_preview": concepts.reasoning[:400],
            }
        )
    except Exception as exc:
        logger.error("extract_concepts failed: %s", exc, exc_info=True)
        return _err(str(exc))


@mcp.tool()
def extract_relationships() -> str:
    """Run LLM relationship inference. Requires extract_concepts first."""
    logger.info("extract_relationships")
    article = _state.get("article")
    concepts: ConceptExtractionResult | None = _state.get("concepts")
    if article is None or concepts is None:
        logger.warning("extract_relationships missing prerequisites")
        return _err("Call extract_article_tool and extract_concepts before extract_relationships")
    try:
        gm = _graph()
        relationships = relationship_agent.extract_relationships(
            article, concepts, gm.summary()
        )
        _state["relationships"] = relationships
        logger.info("extract_relationships ok count=%d", len(relationships.relationships))
        return _ok(
            {
                "relationship_count": len(relationships.relationships),
                "confidence": relationships.confidence,
                "reasoning_preview": relationships.reasoning[:400],
            }
        )
    except Exception as exc:
        logger.error("extract_relationships failed: %s", exc, exc_info=True)
        return _err(str(exc))


@mcp.tool()
def merge_graph() -> str:
    """Merge concepts and relationships into graph.json. Requires extract_relationships first."""
    logger.info("merge_graph")
    article = _state.get("article")
    concepts: ConceptExtractionResult | None = _state.get("concepts")
    relationships: RelationshipExtractionResult | None = _state.get("relationships")
    if article is None or concepts is None or relationships is None:
        return _err("Complete extract_concepts and extract_relationships before merge_graph")
    try:
        gm = _graph()
        gm.merge_concepts(concepts.concepts, article.url)
        gm.merge_relationships(relationships.relationships)
        gm.register_article(article.url, article.title, len(concepts.concepts))
        snapshot = gm.persist()
        _state["snapshot"] = snapshot
        logger.info("merge_graph ok nodes=%d edges=%d", len(snapshot.nodes), len(snapshot.edges))
        return _ok(
            {
                "node_count": len(snapshot.nodes),
                "edge_count": len(snapshot.edges),
            }
        )
    except Exception as exc:
        logger.error("merge_graph failed: %s", exc, exc_info=True)
        return _err(str(exc))


@mcp.tool()
def generate_recommendations() -> str:
    """Run LLM learning-path recommendations. Requires merge_graph first."""
    logger.info("generate_recommendations")
    article = _state.get("article")
    concepts: ConceptExtractionResult | None = _state.get("concepts")
    if article is None or concepts is None or _state.get("snapshot") is None:
        return _err("Call merge_graph before generate_recommendations")
    try:
        gm = _graph()
        focal = gm.focal_concept(concepts.concepts)
        neighbors = gm.subgraph_neighbors(focal)
        recommendations = recommendation_agent.generate_recommendations(
            focal_concept=focal,
            concepts=concepts.concepts,
            graph_summary=gm.summary(),
            subgraph_neighbors=neighbors,
        )
        _state["recommendations"] = recommendations
        logger.info("generate_recommendations ok focal=%s", recommendations.focal_concept)
        return _ok(
            {
                "focal_concept": recommendations.focal_concept,
                "prerequisites": recommendations.prerequisites,
                "learn_next": recommendations.learn_next,
            }
        )
    except Exception as exc:
        logger.error("generate_recommendations failed: %s", exc, exc_info=True)
        return _err(str(exc))


@mcp.tool()
def get_ingest_result() -> str:
    """Return the full ingest payload after all prior tools succeeded."""
    logger.info("get_ingest_result")
    article = _state.get("article")
    concepts = _state.get("concepts")
    relationships = _state.get("relationships")
    recommendations = _state.get("recommendations")
    snapshot = _state.get("snapshot")
    if not all([article, concepts, relationships, recommendations, snapshot]):
        logger.warning("get_ingest_result pipeline incomplete")
        return _err(
            "Pipeline incomplete. Required order: extract_article_tool → get_graph_summary "
            "→ extract_concepts → extract_relationships → merge_graph → generate_recommendations"
        )
    gm = _graph()
    focal = gm.focal_concept(concepts.concepts)
    response = IngestResponse(
        article=article,
        concepts=concepts,
        relationships=relationships,
        recommendations=recommendations,
        graph=snapshot,
        graph_stats=GraphStats(
            node_count=len(snapshot.nodes),
            edge_count=len(snapshot.edges),
        ),
        mermaid=gm.to_mermaid(focal),
        trace=_state.get("trace") or PipelineTrace(),
    )
    return _ok(
        {
            "result": json.loads(response.model_dump_json()),
            "mermaid_full": gm.to_full_mermaid(),
        }
    )


if __name__ == "__main__":
    from backend.logging_setup import configure_logging

    configure_logging()
    logger.info("MCP server starting (stdio)")
    mcp.run(transport="stdio")
