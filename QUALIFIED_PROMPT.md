# Qualified engineering prompt (orchestrator + agents)

Use this document as the combined prompt specification for the System Design Knowledge Graph assignment.

## Orchestrator rules

1. **STEP 0 (tool):** Fetch article with trafilatura; truncate to 8000 chars.
2. **STEP 1 (LLM):** Concept extraction — use `prompts/concept_extraction.txt`; validate `ConceptExtractionResult`.
3. **STEP 2 (tool):** Load `graph_summary` from persisted graph.
4. **STEP 3 (LLM):** Relationship reasoning — use `prompts/relationship_reasoning.txt`; validate `RelationshipExtractionResult`.
5. **STEP 4 (tool):** Merge nodes/edges into NetworkX; save `data/graph.json`.
6. **STEP 5 (LLM):** Recommendations — use `prompts/recommendations.txt`; validate `RecommendationResult`.

On Pydantic validation failure: retry LLM once with error details (max 2 retries).

## LLM integration

- Use `backend/utils/llm.py`: `generate_json(prompt, user_content)`.
- **Option A:** `GEMINI_API_KEY` + `GEMINI_MODEL` (direct Gemini SDK).
- **Option B:** `LLM_BASE_URL` + Gateway V2 (`LLM_GATEWAY_API=v2`, default) — `/v1/chat` with `cache_system`, `reasoning=off`, strict JSON schema; see README diagrams.
- **Option C:** `LLM_GATEWAY_API=v1` for legacy gateway on port 8099.
- Validate all responses with Pydantic (`reasoning`, `confidence`, `self_check`, `reasoning_types`).

## Agent prompts

See:
- [prompts/concept_extraction.txt](prompts/concept_extraction.txt)
- [prompts/relationship_reasoning.txt](prompts/relationship_reasoning.txt)
- [prompts/recommendations.txt](prompts/recommendations.txt)

Each prompt enforces PHASE_1_INPUT → PHASE_2_REASON → PHASE_3_OUTPUT, structured JSON only, self-checks, fallbacks (`status: partial|failed`), and reasoning type tags.
