"""⑥ Policies / RAG — YOUR PART (عبدالرحمن).

Contract the agent tools expect (D43 tools 4 and C):
    async def policy_search(query: str, audience: "customer") -> ToolResult
    async def procedure_search(query: str, audience: "worker") -> ToolResult
ToolResult.data = list of chunks: {doc_id, version, section, text, score}

Design rules (docs/design/Phase4_Step4_RAG.md, Phase 5 D94):
- Only ACTIVE versions; filter by Audience; customer allow-list POL-SPC-001 (D47, D47-a).
- pgvector inside the Gateway DB (D48); keyword-only fallback when the embedding provider is down (D49).
- top-k 5, at most 1 extra agentic round, at most 8 chunks per request; score gate chosen from evals (D94, D114).
- Questions are scrubbed before embedding (D72); never index internal-only documents (D105).
"""
