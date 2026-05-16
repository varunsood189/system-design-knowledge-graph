"""NetworkX knowledge graph with JSON persistence."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import networkx as nx

from backend.models import (
    Concept,
    ConceptDetail,
    ConceptNeighbor,
    EvidenceQuote,
    GraphEdge,
    GraphNode,
    GraphSnapshot,
    IngestedArticle,
    Relationship,
    SourceGraphView,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GRAPH_PATH = PROJECT_ROOT / "data" / "graph.json"


def _normalize(name: str) -> str:
    return " ".join(name.strip().split())


class GraphManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_GRAPH_PATH
        self.graph = nx.DiGraph()
        self.articles: list[dict] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._save()
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.articles = list(raw.get("articles", []))
        self.graph = nx.DiGraph()
        for node in raw.get("nodes", []):
            key = _normalize(node["name"])
            evidence_raw = node.get("evidence_quotes") or []
            quotes = [
                EvidenceQuote(url=q["url"], text=q["text"])
                if isinstance(q, dict)
                else EvidenceQuote(url="", text=str(q))
                for q in evidence_raw
            ]
            self.graph.add_node(
                key,
                name=node.get("name", key),
                category=node.get("category", "other"),
                difficulty=node.get("difficulty", "intermediate"),
                importance_score=float(node.get("importance_score", 0.5)),
                sources=list(node.get("sources", [])),
                definition=node.get("definition", "") or "",
                evidence_quotes=[q.model_dump() for q in quotes],
            )
        for edge in raw.get("edges", []):
            src = _normalize(edge["source"])
            tgt = _normalize(edge["target"])
            for key, label in ((src, edge["source"]), (tgt, edge["target"])):
                if key not in self.graph:
                    self.graph.add_node(key, name=label, sources=[], definition="", evidence_quotes=[])
            if src in self.graph and tgt in self.graph:
                rel = edge.get("relation_type", "related_to")
                if self.graph.has_edge(src, tgt):
                    existing = self.graph[src][tgt].get("relation_type")
                    if existing == rel:
                        continue
                self.graph.add_edge(
                    src,
                    tgt,
                    relation_type=rel,
                    confidence=float(edge.get("confidence", 0.7)),
                )
        if not self.articles:
            self._backfill_articles_from_nodes()

    def _backfill_articles_from_nodes(self) -> None:
        """Build article list from node sources when migrating old graph.json files."""
        seen: set[str] = set()
        for _, data in self.graph.nodes(data=True):
            for url in data.get("sources") or []:
                if url and url not in seen and "example.com/seed" not in url:
                    seen.add(url)
                    self.articles.append(
                        {
                            "url": url,
                            "title": urlparse(url).netloc or url,
                            "ingested_at": "",
                            "concept_count": sum(
                                1
                                for _, d in self.graph.nodes(data=True)
                                if url in (d.get("sources") or [])
                            ),
                        }
                    )

    def _save(self) -> None:
        payload = {
            "articles": self.articles,
            "nodes": [n.model_dump() for n in self.snapshot().nodes],
            "edges": [e.model_dump() for e in self.snapshot().edges],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register_article(self, url: str, title: str, concept_count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for art in self.articles:
            if art.get("url") == url:
                art["title"] = title
                art["ingested_at"] = now
                art["concept_count"] = concept_count
                return
        self.articles.append(
            {
                "url": url,
                "title": title,
                "ingested_at": now,
                "concept_count": concept_count,
            }
        )

    def list_articles(self) -> list[IngestedArticle]:
        out: list[IngestedArticle] = []
        for art in sorted(self.articles, key=lambda a: a.get("ingested_at", ""), reverse=True):
            out.append(
                IngestedArticle(
                    url=art["url"],
                    title=art.get("title") or art["url"],
                    ingested_at=art.get("ingested_at", ""),
                    concept_count=int(art.get("concept_count", 0)),
                )
            )
        return out

    def _article_label(self, url: str) -> str:
        for art in self.articles:
            if art.get("url") == url:
                return art.get("title") or url
        parsed = urlparse(url)
        return parsed.netloc or url

    def summary(self, max_nodes: int = 30) -> str:
        if self.graph.number_of_nodes() == 0:
            return "The knowledge graph is empty."
        nodes = sorted(
            self.graph.nodes(data=True),
            key=lambda item: item[1].get("importance_score", 0),
            reverse=True,
        )[:max_nodes]
        lines = [
            f"Graph: {self.graph.number_of_nodes()} concepts, "
            f"{self.graph.number_of_edges()} relationships."
        ]
        for key, data in nodes:
            sources = data.get("sources") or []
            lines.append(
                f"- {data.get('name', key)} ({data.get('category', 'other')}) "
                f"importance={data.get('importance_score', 0.5):.2f} "
                f"sources={len(sources)}"
            )
        return "\n".join(lines)

    def merge_concepts(self, concepts: list[Concept], source_url: str) -> None:
        for concept in concepts:
            key = _normalize(concept.name)
            quote = EvidenceQuote(url=source_url, text=concept.evidence_span or "")
            if key in self.graph:
                node = self.graph.nodes[key]
                node["importance_score"] = max(
                    float(node.get("importance_score", 0)),
                    concept.importance_score,
                )
                if concept.category:
                    node["category"] = concept.category
                if concept.difficulty:
                    node["difficulty"] = concept.difficulty
                if concept.definition.strip():
                    node["definition"] = concept.definition.strip()
                sources = set(node.get("sources") or [])
                sources.add(source_url)
                node["sources"] = list(sources)
                quotes = list(node.get("evidence_quotes") or [])
                if concept.evidence_span:
                    quotes.append(quote.model_dump())
                node["evidence_quotes"] = quotes[-5:]
            else:
                self.graph.add_node(
                    key,
                    name=concept.name,
                    category=concept.category,
                    difficulty=concept.difficulty,
                    importance_score=concept.importance_score,
                    sources=[source_url],
                    definition=concept.definition.strip(),
                    evidence_quotes=[quote.model_dump()] if concept.evidence_span else [],
                )

    def set_definition(self, name: str, definition: str) -> None:
        key = _normalize(name)
        if key in self.graph:
            self.graph.nodes[key]["definition"] = definition.strip()

    def merge_relationships(self, relationships: list[Relationship]) -> None:
        for rel in relationships:
            src = _normalize(rel.source)
            tgt = _normalize(rel.target)
            if src not in self.graph:
                self.graph.add_node(src, name=rel.source, sources=[], definition="", evidence_quotes=[])
            if tgt not in self.graph:
                self.graph.add_node(tgt, name=rel.target, sources=[], definition="", evidence_quotes=[])
            self.graph.add_edge(
                src,
                tgt,
                relation_type=rel.relation_type,
                confidence=rel.confidence,
            )

    def persist(self) -> GraphSnapshot:
        snap = self.snapshot()
        self._save()
        return snap

    def snapshot(self) -> GraphSnapshot:
        nodes = []
        for key, data in self.graph.nodes(data=True):
            quotes_raw = data.get("evidence_quotes") or []
            quotes = [
                EvidenceQuote(**q) if isinstance(q, dict) else EvidenceQuote(url="", text=str(q))
                for q in quotes_raw
            ]
            nodes.append(
                GraphNode(
                    name=data.get("name", key),
                    category=data.get("category", "other"),
                    difficulty=data.get("difficulty", "intermediate"),
                    importance_score=float(data.get("importance_score", 0.5)),
                    sources=list(data.get("sources") or []),
                    definition=data.get("definition", "") or "",
                    evidence_quotes=quotes,
                )
            )
        edges = [
            GraphEdge(
                source=self.graph.nodes[src].get("name", src),
                target=self.graph.nodes[tgt].get("name", tgt),
                relation_type=data.get("relation_type", "related_to"),
                confidence=float(data.get("confidence", 0.7)),
            )
            for src, tgt, data in self.graph.edges(data=True)
        ]
        return GraphSnapshot(nodes=nodes, edges=edges)

    def list_concept_names(self) -> list[str]:
        return sorted(
            [self.graph.nodes[k].get("name", k) for k in self.graph.nodes],
            key=str.lower,
        )

    def get_concept_detail(self, name: str) -> ConceptDetail:
        key = _normalize(name)
        if key not in self.graph:
            raise ValueError(f"Concept not found: {name}")
        data = self.graph.nodes[key]
        quotes_raw = data.get("evidence_quotes") or []
        quotes = [
            EvidenceQuote(**q) if isinstance(q, dict) else EvidenceQuote(url="", text=str(q))
            for q in quotes_raw
        ]

        prerequisites: list[str] = []
        dependents: list[str] = []
        related: list[str] = []
        neighbors: list[ConceptNeighbor] = []

        for src, tgt, edge_data in self.graph.edges(data=True):
            rel = edge_data.get("relation_type", "related_to")
            if tgt == key and rel in ("prerequisite", "depends_on"):
                prerequisites.append(self.graph.nodes[src].get("name", src))
            elif src == key and rel in ("prerequisite", "depends_on"):
                dependents.append(self.graph.nodes[tgt].get("name", tgt))
            elif src == key or tgt == key:
                other = tgt if src == key else src
                related.append(self.graph.nodes[other].get("name", other))
            if src == key:
                neighbors.append(
                    ConceptNeighbor(
                        name=self.graph.nodes[tgt].get("name", tgt),
                        relation_type=rel,
                        direction="outgoing",
                    )
                )
            if tgt == key:
                neighbors.append(
                    ConceptNeighbor(
                        name=self.graph.nodes[src].get("name", src),
                        relation_type=rel,
                        direction="incoming",
                    )
                )

        return ConceptDetail(
            name=data.get("name", key),
            category=data.get("category", "other"),
            difficulty=data.get("difficulty", "intermediate"),
            importance_score=float(data.get("importance_score", 0.5)),
            definition=data.get("definition", "") or "",
            sources=list(data.get("sources") or []),
            evidence_quotes=quotes,
            prerequisites=sorted(set(prerequisites)),
            dependents=sorted(set(dependents)),
            related=sorted(set(related))[:10],
            neighbors=neighbors[:15],
        )

    def source_view(self, source_url: str) -> SourceGraphView:
        article_meta = None
        for art in self.articles:
            if art.get("url") == source_url:
                article_meta = IngestedArticle(
                    url=art["url"],
                    title=art.get("title") or art["url"],
                    ingested_at=art.get("ingested_at", ""),
                    concept_count=int(art.get("concept_count", 0)),
                )
                break

        snap = self.snapshot()
        concept_nodes = [n for n in snap.nodes if source_url in n.sources]
        keys = {_normalize(n.name) for n in concept_nodes}
        concept_edges = [
            e
            for e in snap.edges
            if _normalize(e.source) in keys and _normalize(e.target) in keys
        ]
        focal = (
            max(concept_nodes, key=lambda n: n.importance_score).name
            if concept_nodes
            else ""
        )
        mermaid = self.to_mermaid_for_nodes(keys, focal) if keys else "graph LR\n  empty[No concepts for this source]"

        return SourceGraphView(
            article=article_meta,
            concepts=concept_nodes,
            edges=concept_edges,
            mermaid=mermaid,
        )

    def to_mermaid_for_nodes(self, node_keys: set[str], focal: str = "") -> str:
        if not node_keys:
            return "graph LR\n  empty[Empty]"

        sub_nodes = set(node_keys)
        if focal:
            fk = _normalize(focal)
            if fk in self.graph:
                undirected = self.graph.to_undirected()
                sub_nodes = set(nx.ego_graph(undirected, fk, radius=1).nodes()) & node_keys
                if not sub_nodes:
                    sub_nodes = set(node_keys)

        def safe_id(n: str) -> str:
            return "".join(c if c.isalnum() else "_" for c in n)[:40]

        lines = ["graph LR"]
        id_map = {n: safe_id(n) for n in sub_nodes}
        for n in sub_nodes:
            label = self.graph.nodes[n].get("name", n)
            lines.append(f'  {id_map[n]}["{label}"]')
        for src, tgt, data in self.graph.edges(data=True):
            if src in sub_nodes and tgt in sub_nodes:
                rel = data.get("relation_type", "related_to")
                lines.append(f"  {id_map[src]} -->|{rel}| {id_map[tgt]}")
        return "\n".join(lines)

    def focal_concept(self, concepts: list[Concept]) -> str:
        if not concepts:
            if self.graph.number_of_nodes() == 0:
                return "System Design"
            key = max(
                self.graph.nodes,
                key=lambda k: self.graph.nodes[k].get("importance_score", 0),
            )
            return self.graph.nodes[key].get("name", key)
        best = max(concepts, key=lambda c: c.importance_score)
        return best.name

    def subgraph_neighbors(self, focal: str, radius: int = 2, max_nodes: int = 12) -> list[str]:
        key = _normalize(focal)
        if key not in self.graph:
            return []
        nodes = set(nx.ego_graph(self.graph.to_undirected(), key, radius=radius).nodes())
        nodes.discard(key)
        ordered = sorted(
            nodes,
            key=lambda n: self.graph.nodes[n].get("importance_score", 0),
            reverse=True,
        )
        return [self.graph.nodes[n].get("name", n) for n in ordered[:max_nodes]]

    def to_mermaid(self, focal: str, max_nodes: int = 12) -> str:
        key = _normalize(focal)
        if key not in self.graph:
            return "graph LR\n  empty[No graph data yet]"

        undirected = self.graph.to_undirected()
        if key in undirected:
            sub_nodes = set(nx.ego_graph(undirected, key, radius=2).nodes())
        else:
            sub_nodes = set(list(self.graph.nodes())[:max_nodes])

        if len(sub_nodes) > max_nodes:
            sub_nodes = set(sorted(sub_nodes, key=lambda n: undirected.degree(n), reverse=True)[:max_nodes])
            sub_nodes.add(key)

        return self.to_mermaid_for_nodes(sub_nodes, focal)

    def to_full_mermaid(self, max_nodes: int = 35) -> str:
        if self.graph.number_of_nodes() == 0:
            return "graph LR\n  empty[No concepts yet — ingest a blog URL]"

        ranked = sorted(
            self.graph.nodes,
            key=lambda k: self.graph.nodes[k].get("importance_score", 0),
            reverse=True,
        )[:max_nodes]
        sub_nodes: set[str] = set(ranked)

        for src, tgt in list(self.graph.edges()):
            if len(sub_nodes) >= max_nodes:
                break
            if src in sub_nodes or tgt in sub_nodes:
                sub_nodes.add(src)
                sub_nodes.add(tgt)

        if len(sub_nodes) > max_nodes:
            sub_nodes = set(
                sorted(
                    sub_nodes,
                    key=lambda n: self.graph.nodes[n].get("importance_score", 0),
                    reverse=True,
                )[:max_nodes]
            )

        lines = self.to_mermaid_for_nodes(sub_nodes).split("\n")
        omitted = self.graph.number_of_nodes() - len(sub_nodes)
        if omitted > 0:
            lines.append(f'  more["+{omitted} more in graph.json"]')
        return "\n".join(lines)
