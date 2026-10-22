"""② Identity: verify the website's JWT locally with the backend's public key (D24).

Identity comes ONLY from the token (D1). The LLM never sees subject_id / token (D2).
JWKS refresh rules (D88): refresh only on an unknown kid, at most once per JWKS_MIN_REFRESH_S,
one fetch at a time (single-flight), keep the old keys if the fetch fails.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from .config import settings


@dataclass(frozen=True)
class Identity:
    subject_id: str      # customer_id or worker_id — code only, never sent to the LLM
    role: str            # "customer" | "worker"
    session_id: str      # login session id (chat boundary, D65)
    token: str           # forwarded to the backend as-is (D20: never stored)


class AuthError(Exception):
    """401 for the website. Sign-in problems are handled outside the Gateway (D29)."""


class JwksCache:
    def __init__(self, url: str, http: httpx.AsyncClient | None = None):
        self.url = url
        self.http = http
        self.keys: dict[str, object] = {}
        self.last_fetch = 0.0
        self._lock = asyncio.Lock()

    async def _fetch(self) -> None:
        async with self._lock:  # single-flight
            if time.monotonic() - self.last_fetch < settings.jwks_min_refresh_s and self.keys:
                return
            self.last_fetch = time.monotonic()
            client = self.http or httpx.AsyncClient(timeout=2.0)
            try:
                resp = await client.get(self.url)
                resp.raise_for_status()
                self.keys = {k["kid"]: RSAAlgorithm.from_jwk(json.dumps(k)) for k in resp.json()["keys"]}
            except (httpx.HTTPError, KeyError, ValueError):
                pass  # keep the last keys (D88)
            finally:
                if self.http is None:
                    await client.aclose()

    async def key_for(self, kid: str):
        if kid not in self.keys:
            await self._fetch()
        return self.keys.get(kid)


async def verify_token(token: str, jwks: JwksCache) -> Identity:
    try:
        kid = jwt.get_unverified_header(token).get("kid", "")
    except jwt.PyJWTError as exc:
        raise AuthError("malformed token") from exc
    key = await jwks.key_for(kid)
    if key is None:
        raise AuthError("unknown signing key")
    try:
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=settings.jwt_issuer,
                            leeway=settings.jwt_leeway_s)
    except jwt.PyJWTError as exc:
        raise AuthError("invalid token") from exc
    if claims.get("role") not in ("customer", "worker"):
        raise AuthError("unknown role")
    return Identity(subject_id=claims["sub"], role=claims["role"], session_id=claims["sid"], token=token)
