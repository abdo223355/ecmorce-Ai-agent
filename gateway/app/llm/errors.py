"""Maps provider failures to LLMResult statuses in ONE table, so adding a case is one line."""
from __future__ import annotations

from . import LLMResult, LLMStatus

# HTTP status code -> (LLMResult.status, reason)
HTTP_ERRORS: dict[int, tuple[LLMStatus, str]] = {
    408: ("timeout", "provider_timeout"),
    429: ("rate_limited", "rate_limited"),
    401: ("unavailable", "auth_failed"),       # bad / missing key: config problem, not the user's
    402: ("unavailable", "no_credit"),
    403: ("unavailable", "auth_failed"),
}


def from_http_status(code: int, latency_s: float) -> LLMResult:
    status, reason = HTTP_ERRORS.get(code, ("unavailable", f"http_{code}"))
    return LLMResult(status, reason=reason, details={"http_status": code, "latency_s": round(latency_s, 3)})


def failure(status: LLMStatus, reason: str, latency_s: float = 0.0) -> LLMResult:
    return LLMResult(status, reason=reason, details={"latency_s": round(latency_s, 3)})
