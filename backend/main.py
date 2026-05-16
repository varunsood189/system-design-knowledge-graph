"""FastAPI application for System Design Knowledge Graph."""

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.agents import concept_detail_agent
from backend.graph_manager import GraphManager
from backend.models import (
    ConceptDetail,
    GraphSnapshot,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    IngestedArticle,
    SourceGraphView,
)
from backend.orchestrator import ingest_url, ingest_url_events
from backend.utils import llm

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

app = FastAPI(
    title="System Design Knowledge Graph",
    description="AI-powered evolving knowledge graph for system design learning",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_graph = GraphManager()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        llm_configured=llm.is_configured(),
        llm_backend=llm.backend_name(),
    )


@app.post("/ingest", response_model=IngestResponse)
def ingest(body: IngestRequest) -> IngestResponse:
    if not llm.is_configured():
        raise HTTPException(
            status_code=503,
            detail="LLM not configured. Set GEMINI_API_KEY or LLM_BASE_URL in .env",
        )
    try:
        return ingest_url(body.url, graph=_graph)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/graph", response_model=GraphSnapshot)
def get_graph() -> GraphSnapshot:
    return _graph.snapshot()


@app.get("/graph/mermaid")
def get_mermaid(focal: str | None = None) -> dict[str, str]:
    name = focal or "System Design"
    if _graph.graph.number_of_nodes() > 0 and focal is None:
        name = max(
            _graph.graph.nodes,
            key=lambda k: _graph.graph.nodes[k].get("importance_score", 0),
        )
        name = _graph.graph.nodes[name].get("name", name)
    return {"mermaid": _graph.to_mermaid(name)}


@app.get("/articles", response_model=list[IngestedArticle])
def list_articles() -> list[IngestedArticle]:
    """Previously ingested blog URLs / papers."""
    return _graph.list_articles()


@app.get("/concepts", response_model=list[str])
def list_concepts() -> list[str]:
    return _graph.list_concept_names()


@app.get("/concepts/{name}", response_model=ConceptDetail)
def get_concept(name: str) -> ConceptDetail:
    try:
        return _graph.get_concept_detail(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/concepts/{name}/enrich", response_model=ConceptDetail)
def enrich_concept(name: str) -> ConceptDetail:
    if not llm.is_configured():
        raise HTTPException(status_code=503, detail="LLM not configured")
    try:
        return concept_detail_agent.enrich_definition(name, _graph)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/graph/source", response_model=SourceGraphView)
def graph_by_source(url: str) -> SourceGraphView:
    """Concepts and subgraph from one ingested article."""
    view = _graph.source_view(url)
    if not view.concepts:
        raise HTTPException(status_code=404, detail="No concepts found for this source URL")
    return view


@app.get("/graph/mermaid/full")
def get_full_mermaid() -> dict[str, str]:
    """Full persisted knowledge graph (all ingested articles combined)."""
    return {
        "mermaid": _graph.to_full_mermaid(),
        "node_count": _graph.graph.number_of_nodes(),
        "edge_count": _graph.graph.number_of_edges(),
    }


@app.post("/ingest/stream")
def ingest_stream(body: IngestRequest) -> StreamingResponse:
    """Server-Sent Events: live step progress during the 30–60s pipeline."""
    if not llm.is_configured():
        raise HTTPException(
            status_code=503,
            detail="LLM not configured. Set GEMINI_API_KEY or LLM_BASE_URL in .env",
        )

    def event_generator():
        try:
            for event in ingest_url_events(body.url, graph=_graph):
                yield f"data: {event.model_dump_json()}\n\n"
        except Exception as exc:
            err = json.dumps({"step": "error", "status": "error", "message": str(exc)})
            yield f"data: {err}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")
