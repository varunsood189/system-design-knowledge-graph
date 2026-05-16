"""Smoke tests without LLM calls."""

from backend.graph_manager import GraphManager
from backend.models import Concept, Relationship
from backend.utils import llm
from backend.utils.parser import safe_parse_json


def test_safe_parse_json():
    raw = '{"reasoning": "step 1", "confidence": 0.9, "status": "ok", "concepts": []}'
    data = safe_parse_json(raw)
    assert data["status"] == "ok"


def test_graph_merge(tmp_path):
    gm = GraphManager(path=tmp_path / "graph.json")
    initial_nodes = gm.graph.number_of_nodes()
    gm.merge_concepts(
        [
            Concept(
                name="Kafka",
                category="queue",
                difficulty="intermediate",
                importance_score=0.9,
                evidence_span="Kafka partitions",
            )
        ],
        "https://example.com/kafka",
    )
    gm.merge_relationships(
        [
            Relationship(
                source="Partitions",
                target="Kafka",
                relation_type="part_of",
                confidence=0.8,
            )
        ],
    )
    snap = gm.snapshot()
    assert len(snap.nodes) >= initial_nodes + 1
    assert gm.to_mermaid("Kafka").startswith("graph")


def test_llm_backend_name_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert llm.backend_name() == "none"
