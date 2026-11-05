"""③ Short-term memory (D61, first slice): one small card per chat in Redis.

Today the card holds only the pending clarification (see agent/pending.py). It never holds message text, names, phones,
addresses, identity or tokens (D64). The key is a hash of the chat id (owner + login session, D65), so a Redis key does not
show an owner id. The card lives 30 minutes from the last turn (D95) and a new login is a new chat, so it never outlasts
the login session.

Redis being down, slow or full is NOT an error for the user: every method answers "no memory" and the chat starts fresh
(D65). Nothing here raises.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging

log = logging.getLogger("gateway.memory")

TTL_S = 30 * 60                      # D95: 30 minutes, reset on each turn
OP_TIMEOUT_S = 0.25                  # a memory call must never eat the request budget


def key_for(chat_id: str) -> str:
    return "mem:" + hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:32]


class MemoryStore:
    """Redis-backed. `url` empty means memory is switched off (every read is None, every write is dropped)."""

    def __init__(self, url: str, ttl_s: int = TTL_S, client=None):
        self._url, self._ttl, self._client = url, ttl_s, client

    def _redis(self):
        if self._client is None and self._url:
            from redis import asyncio as aioredis          # here, not at the top: the Gateway still starts without the library
            self._client = aioredis.from_url(self._url, socket_timeout=OP_TIMEOUT_S, socket_connect_timeout=OP_TIMEOUT_S)
        return self._client

    async def get(self, chat_id: str) -> dict | None:
        """The stored card, or None (nothing stored, Redis trouble, or a value that is not JSON)."""
        try:
            client = self._redis()
            if client is None:
                return None
            raw = await asyncio.wait_for(client.get(key_for(chat_id)), OP_TIMEOUT_S * 2)
            return json.loads(raw) if raw else None
        except Exception as e:                                # noqa: BLE001  memory must never break a request
            log.warning(json.dumps({"event": "memory_get_failed", "error": type(e).__name__}))
            return None

    async def put(self, chat_id: str, card: dict | None) -> None:
        """Store the card (TTL reset), or delete it when `card` is None."""
        try:
            client = self._redis()
            if client is None:
                return
            if card is None:
                await asyncio.wait_for(client.delete(key_for(chat_id)), OP_TIMEOUT_S * 2)
            else:
                await asyncio.wait_for(client.set(key_for(chat_id), json.dumps(card, ensure_ascii=False), ex=self._ttl),
                                       OP_TIMEOUT_S * 2)
        except Exception as e:                                # noqa: BLE001
            log.warning(json.dumps({"event": "memory_put_failed", "error": type(e).__name__}))

    async def aclose(self) -> None:
        try:
            if self._client is not None:
                await self._client.aclose()
        except Exception:                                     # noqa: BLE001
            pass
