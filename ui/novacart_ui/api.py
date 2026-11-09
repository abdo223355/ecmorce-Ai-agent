"""The only code that talks to the NovaCart backend (login) and to the Gateway (/chat). Plain functions of HTTP, no Streamlit.

The UI never sees the model, never calls the agent directly and never keeps the password: login returns a token, the
token goes to /chat as a Bearer header, and the Gateway decides everything from it (D1).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

CHAT_TIMEOUT_S = 15.0         # the Gateway's own budget is 8 s; this only stops the page from waiting forever


class LoginFailed(Exception):
    """Wrong username or password."""


class SessionExpired(Exception):
    """The token was rejected (it lives 30 minutes): the user has to log in again."""


class RateLimited(Exception):
    """The Gateway refused the request because a usage limit was reached. `reason` is "minute" (too fast) or "day" (the
    daily cap of a public deployment)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ServiceUnavailable(Exception):
    """The backend or the Gateway did not answer, or answered with an error the user cannot fix."""


@dataclass(frozen=True)
class UserSession:
    token: str
    role: str                 # "customer" or "worker", as the backend says


@dataclass(frozen=True)
class SegmentView:
    part_index: int
    kind: str                 # template | text | clarify
    template_id: int | None
    text: str | None
    render_values: dict
    cited: list = field(default_factory=list)


@dataclass(frozen=True)
class ChatReply:
    segments: list[SegmentView]
    handoff_reason: str | None
    priority: str | None
    elapsed_s: float
    raw: dict                 # the whole result as the Gateway sent it (for the developer view)


class NovaCartApi:
    def __init__(self, backend_url: str, gateway_url: str, client: httpx.Client | None = None):
        self._backend, self._gateway = backend_url.rstrip("/"), gateway_url.rstrip("/")
        self._client = client or httpx.Client(timeout=CHAT_TIMEOUT_S)

    def login(self, username: str, password: str) -> UserSession:
        try:
            r = self._client.post(f"{self._backend}/auth/login", json={"username": username, "password": password})
        except httpx.HTTPError:
            raise ServiceUnavailable("backend") from None
        if r.status_code == 401:
            raise LoginFailed()
        if r.status_code != 200:
            raise ServiceUnavailable("backend")
        body = r.json()
        return UserSession(token=body["access_token"], role=body["role"])

    def chat(self, session: UserSession, message: str) -> ChatReply:
        start = time.monotonic()
        try:
            r = self._client.post(f"{self._gateway}/chat", json={"message": message},
                                  headers={"Authorization": f"Bearer {session.token}"})
        except httpx.HTTPError:
            raise ServiceUnavailable("gateway") from None
        if r.status_code == 401:
            raise SessionExpired()
        if r.status_code == 429:
            try:
                reason = r.json().get("detail")
            except ValueError:
                reason = None
            raise RateLimited("day" if reason == "day" else "minute")
        if r.status_code != 200:
            raise ServiceUnavailable(f"gateway {r.status_code}")
        result = r.json()["result"]
        segments = [SegmentView(s["part_index"], s["kind"], s.get("template_id"), s.get("text"),
                                s.get("render_values") or {}, s.get("cited") or []) for s in result["segments"]]
        return ChatReply(segments, result.get("handoff_reason"), result.get("priority"),
                         time.monotonic() - start, result)
