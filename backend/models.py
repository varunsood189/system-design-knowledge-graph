"""Pydantic schemas for APIs and LLM structured responses."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Concept(BaseModel):
    name: str
    category: Literal["database", "queue", "cache", "pattern", "infra", "other"] = "other"
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    importance_score: float = Field(ge=0, le=1, default=0.5)
    evidence_span: str = ""
    definition: str = Field(
        default="",
        description="1–3 sentence system-design definition grounded in the article",
    )


class Relationship(BaseModel):
    source: str
    target: str
    relation_type: Literal["prerequisite", "depends_on", "related_to", "part_of"] = "related_to"
    confidence: float = Field(ge=0, le=1, default=0.7)


class ConceptExtractionResult(BaseModel):
    reasoning: str
    reasoning_types: list[Literal["extraction", "deduction", "lookup"]] = Field(
        default_factory=list
    )
    self_check: str
    confidence: float = Field(ge=0, le=1)
    status: Literal["ok", "partial", "failed"] = "ok"
    concepts: list[Concept] = Field(default_factory=list, max_length=15)


class RelationshipExtractionResult(BaseModel):
    reasoning: str
    reasoning_types: list[Literal["extraction", "deduction", "lookup"]] = Field(
        default_factory=list
    )
    self_check: str
    confidence: float = Field(ge=0, le=1)
    status: Literal["ok", "partial", "failed"] = "ok"
    relationships: list[Relationship] = Field(default_factory=list)


class RecommendationResult(BaseModel):
    focal_concept: str
    prerequisites: list[str] = Field(default_factory=list)
    learn_next: list[str] = Field(default_factory=list)
    nearby_concepts: list[str] = Field(default_factory=list)
    reasoning: str
    reasoning_types: list[Literal["extraction", "deduction", "lookup"]] = Field(
        default_factory=list
    )
    self_check: str
    confidence: float = Field(ge=0, le=1)
    status: Literal["ok", "partial", "failed"] = "ok"


class ExtractedArticle(BaseModel):
    url: str
    title: str
    text: str


class EvidenceQuote(BaseModel):
    url: str
    text: str


class IngestedArticle(BaseModel):
    url: str
    title: str
    ingested_at: str
    concept_count: int = 0


class GraphNode(BaseModel):
    name: str
    category: str = "other"
    difficulty: str = "intermediate"
    importance_score: float = 0.5
    sources: list[str] = Field(default_factory=list)
    definition: str = ""
    evidence_quotes: list[EvidenceQuote] = Field(default_factory=list)


class ConceptNeighbor(BaseModel):
    name: str
    relation_type: str
    direction: Literal["incoming", "outgoing"]


class ConceptDetailResult(BaseModel):
    reasoning: str
    reasoning_types: list[Literal["extraction", "deduction", "lookup"]] = Field(
        default_factory=list
    )
    self_check: str
    confidence: float = Field(ge=0, le=1)
    name: str
    definition: str


class ConceptDetail(BaseModel):
    name: str
    category: str
    difficulty: str
    importance_score: float
    definition: str
    sources: list[str]
    evidence_quotes: list[EvidenceQuote]
    prerequisites: list[str] = Field(default_factory=list)
    dependents: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    neighbors: list[ConceptNeighbor] = Field(default_factory=list)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    confidence: float = 0.7


class SourceGraphView(BaseModel):
    article: IngestedArticle | None = None
    concepts: list[GraphNode]
    edges: list[GraphEdge]
    mermaid: str


class GraphSnapshot(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class GraphStats(BaseModel):
    node_count: int
    edge_count: int


class PipelineTrace(BaseModel):
    extract_ms: float | None = None
    concepts_ms: float | None = None
    relationships_ms: float | None = None
    graph_ms: float | None = None
    recommendations_ms: float | None = None


class PipelineStepEvent(BaseModel):
    """Progress event streamed during ingest (SSE)."""

    step: Literal[
        "extract",
        "concepts",
        "relationships",
        "graph",
        "recommendations",
        "agent_log",
        "done",
        "error",
    ]
    status: Literal["running", "done", "error"]
    message: str
    elapsed_ms: float | None = None
    detail: dict[str, Any] | None = None


class IngestRequest(BaseModel):
    url: str = Field(..., min_length=4)


class IngestResponse(BaseModel):
    article: ExtractedArticle
    concepts: ConceptExtractionResult
    relationships: RelationshipExtractionResult
    recommendations: RecommendationResult
    graph: GraphSnapshot
    graph_stats: GraphStats
    mermaid: str = ""
    trace: PipelineTrace = Field(default_factory=PipelineTrace)


class HealthResponse(BaseModel):
    llm_configured: bool
    llm_backend: str
    orchestrator_mode: str = "agent"


class ErrorResponse(BaseModel):
    detail: str
    status: Literal["failed"] = "failed"
