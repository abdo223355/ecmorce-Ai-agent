"""Policy RAG: chunking, embeddings, the pgvector store, ingestion and retrieval.

What the agent tools call (implemented by retrieve.search):
    async def policy_search(query: str, english_query: str | None = None) -> ToolResult     # customers
    async def procedure_search(query: str, english_query: str | None = None) -> ToolResult  # workers

query is the scrubbed user text and drives the meaning search. english_query is the English search query
that classify produces and drives the keyword search. The audience is set by the Gateway from the token's
role (main.BoundTools), never by the agent.

ToolResult.data is a list of chunks: {doc_id, version, section, part, title, text, score, vector_score, cited}.
ToolResult.details["mode"] tells how they were found: hybrid, vector_only, keyword_only or no_retrieval.

Rules (docs/design/Phase4_Step4_RAG.md, D94):
- Only ACTIVE versions, filtered by audience, plus the customer allow-list (POL-SPC-001).
- pgvector lives in the Gateway database; when the embedding provider is down we fall back to keywords.
- top-k is 5, with at most one extra agentic round and at most 8 chunks per request.
- Questions are scrubbed before embedding, and internal-only documents are never indexed.
"""
