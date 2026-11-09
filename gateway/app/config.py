"""Gateway settings (environment variables). Numbers are Phase 5 initial values (design choices)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    backend_url: str = os.getenv("BACKEND_URL", "http://backend:8000")
    jwks_url: str = os.getenv("JWKS_URL", "http://backend:8000/.well-known/jwks.json")
    jwt_issuer: str = os.getenv("JWT_ISSUER", "novacart-backend")
    jwt_leeway_s: int = int(os.getenv("JWT_LEEWAY_S", "30"))               # Step 2+3 fix 4
    jwks_min_refresh_s: int = int(os.getenv("JWKS_MIN_REFRESH_S", "60"))   # Step 2+3 fix 4
    request_budget_s: float = float(os.getenv("REQUEST_BUDGET_S", "8.0"))  # POL-BDR-001
    backend_attempt_timeout_s: float = float(os.getenv("BACKEND_ATTEMPT_TIMEOUT_S", "1.0"))  # fix 1
    backend_max_retries: int = 2                                           # POL-BDR-001
    backend_backoffs_s: tuple[float, ...] = (1.0, 2.0)                     # POL-BDR-001
    reserve_after_backend_s: float = 2.2   # reply 1.5 + margin 0.5 + validate 0.2 (fix 1)
    # LLM and embeddings. Per-node model names live in llm/models.py; the env vars below override them.
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "")   # one model for every node, handy for quick tests
    embed_model: str = os.getenv("EMBED_MODEL", "")   # overrides EMBEDDING_MODEL in llm/models.py
    embed_dimensions: int = int(os.getenv("EMBED_DIMENSIONS", "0"))   # 0 means use the default size
    # Policy store: the Gateway database, with its own statement timeout. 1000 ms is a starting value that
    # fits inside the 1.5 s backend + RAG window; adjust it after load testing.
    # The default host is 127.0.0.1 rather than localhost: on Windows localhost tries IPv6 first.
    gateway_database_url: str = os.getenv("GATEWAY_DATABASE_URL", "postgresql://gateway:gateway@127.0.0.1:5433/gateway")
    rag_statement_timeout_ms: int = int(os.getenv("RAG_STATEMENT_TIMEOUT_MS", "1000"))
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    recent_orders_limit: int = int(os.getenv("RECENT_ORDERS_LIMIT", "10"))
    # Short-term memory (D61): Redis. Empty = memory switched off (every chat starts fresh).
    redis_url: str = os.getenv("REDIS_URL", "")
    # Limits on /chat for a public deployment (0 = off). See app/ratelimit.py.
    rate_limit_per_min: int = int(os.getenv("RATE_LIMIT_PER_MIN", "0"))
    rate_limit_per_day: int = int(os.getenv("RATE_LIMIT_PER_DAY", "0"))
    # POL-DWA-001 §4 access window. TEMPORARY constant: in Milestone 2 ⑤ reads it as an ACTIVE
    # structured value (D13). Do not hard-code it anywhere else.
    worker_access_window_h: int = int(os.getenv("WORKER_ACCESS_WINDOW_H", "24"))
    # The phone numbers of the static fallback text (app/fallback.py). In NO document: set them in .env. Empty = left out.
    cs_phone: str = os.getenv("CS_PHONE", "")
    emergency_phone: str = os.getenv("EMERGENCY_PHONE", "")
    dispatch_phone: str = os.getenv("DISPATCH_PHONE", "")

    def model_for(self, node: str) -> str:
        """Model for a node: env LLM_MODEL_<NODE> > LLM_MODEL > llm/models.py. "" = not configured."""
        from .llm.models import MODELS
        return os.getenv(f"LLM_MODEL_{node.upper()}", "") or self.llm_model or MODELS.get(node, "")


settings = Settings()
