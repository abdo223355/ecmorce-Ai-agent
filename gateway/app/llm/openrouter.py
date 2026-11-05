"""OpenRouter adapter. One HTTP call per generate() and no retry: the fallback chain does the retrying."""
from __future__ import annotations

import asyncio
import time

import httpx
from pydantic import BaseModel

from ..config import settings
from . import LLMAdapter, LLMResult
from .errors import failure, from_http_status


# D111: only endpoints that do not keep or train on the prompt. OpenRouter fields (provider selection docs):
# data_collection "deny" = providers that do not collect user data; zdr true = only Zero Data Retention endpoints.
# A model with no such endpoint fails instead of being served by one that retains data.
NO_RETENTION = {"data_collection": "deny", "zdr": True}


class OpenRouterAdapter(LLMAdapter):
    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None, client: httpx.AsyncClient | None = None):
        self._model = model or settings.llm_model
        self._api_key = api_key or settings.openrouter_api_key
        self._base_url = (base_url or settings.llm_base_url).rstrip("/")
        # httpx has its own 5 s default timeout, which would cut calls before our deadline. Turn it off.
        self._client = client or httpx.AsyncClient(timeout=None)

    async def generate(self, prompt: str, schema: type[BaseModel], timeout_s: float,
                       system: str | None = None, max_tokens: int | None = None,
                       reasoning_effort: str | None = None) -> LLMResult:
        if not self._api_key or not self._model:
            return failure("unavailable", "llm_not_configured")

        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {
            "model": self._model,
            "messages": messages,
            "provider": NO_RETENTION,
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": schema.__name__, "strict": True,
                                                "schema": schema.model_json_schema()}},
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if reasoning_effort is not None:
            body["reasoning"] = {"effort": reasoning_effort}
        start = time.monotonic()
        try:
            # One deadline for the whole call: connect, send, wait and read.
            resp = await asyncio.wait_for(
                self._client.post(f"{self._base_url}/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {self._api_key}"}),
                timeout=timeout_s)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            return failure("timeout", "deadline_exceeded", time.monotonic() - start)
        except httpx.HTTPError:
            return failure("unavailable", "network_error", time.monotonic() - start)

        latency = time.monotonic() - start
        if resp.status_code != 200:
            return from_http_status(resp.status_code, latency)
        return self._parse(resp, schema, latency)

    @staticmethod
    def _parse(resp: httpx.Response, schema: type[BaseModel], latency_s: float) -> LLMResult:
        try:
            payload = resp.json()
            if payload["choices"][0].get("finish_reason") == "length":    # cut by max_tokens: never use half an answer
                return failure("bad_output", "truncated", latency_s)
            content = payload["choices"][0]["message"]["content"]
            data = schema.model_validate_json(content)
        except (ValueError, KeyError, IndexError, TypeError):   # pydantic's ValidationError is a ValueError
            return failure("bad_output", "invalid_json_or_schema", latency_s)
        usage = payload.get("usage") or {}
        return LLMResult("ok", data=data, details={
            "latency_s": round(latency_s, 3),
            "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens")})
