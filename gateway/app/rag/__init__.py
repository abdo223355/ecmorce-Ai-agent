"""⑥ Policies / RAG — YOUR PART (عبدالرحمن).

Contract the agent tools expect (D43 tools 4 and C), changed with عبدالرحمن (option ب, 2026-10-25):
    async def policy_search(query: str, english_query: str | None = None) -> ToolResult     # customers
    async def procedure_search(query: str, english_query: str | None = None) -> ToolResult  # workers
query = scrubbed user text (meaning search); english_query = English search query from classify (keyword search).
The audience is bound by the Gateway from the token role (main.BoundTools), never chosen by the agent.
Implementation: retrieve.search(). ToolResult.data = list of chunks:
{doc_id, version, section, part, title, text, score, cited}; ToolResult.details["mode"] says how it was found
(hybrid / vector_only / keyword_only / no_retrieval).

Design rules (docs/design/Phase4_Step4_RAG.md, Phase 5 D94):
- Only ACTIVE versions; filter by Audience; customer allow-list POL-SPC-001 (D47, D47-a).
- pgvector inside the Gateway DB (D48); keyword-only fallback when the embedding provider is down (D49).
- top-k 5, at most 1 extra agentic round, at most 8 chunks per request; score gate chosen from evals (D94, D114).
- Questions are scrubbed before embedding (D72); never index internal-only documents (D105).
"""
