"""Rate limits for /chat, for a Gateway that is open to the public (a model key is spent on every request).

Two limits, both checked AFTER the token is verified, so an anonymous caller cannot use up anybody's allowance:
- per account: at most `per_minute` requests in any 60 seconds (a sliding window);
- one cap for the whole Gateway: at most `per_day` requests per UTC day.

A request that is refused is not counted. A limit of 0 switches that limit off, and both default to 0 (the local stack
is not limited). The counters live in memory: a restart resets them, so the hard stop against a runaway bill is the
spending cap on the model key itself. This is a first line of defence, not the last.
"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable

WINDOW_S = 60.0


class RateLimiter:
    def __init__(self, per_minute: int = 0, per_day: int = 0, clock: Callable[[], float] = time.time):
        self.per_minute, self.per_day, self._clock = per_minute, per_day, clock
        self._recent: dict[str, deque[float]] = {}
        self._day: str | None = None
        self._day_count = 0

    def _today(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=timezone.utc).date().isoformat()

    def check(self, subject: str) -> str | None:
        """Count one request for `subject`. None = allowed; "minute" or "day" = refused (and not counted)."""
        now = self._clock()
        today = self._today()
        if today != self._day:                                     # a new day starts a new count
            self._day, self._day_count = today, 0
        if self.per_day and self._day_count >= self.per_day:
            return "day"
        recent = self._recent.setdefault(subject, deque())
        while recent and now - recent[0] >= WINDOW_S:
            recent.popleft()
        if self.per_minute and len(recent) >= self.per_minute:
            return "minute"
        recent.append(now)
        self._day_count += 1
        self._forget_idle(now)
        return None

    def _forget_idle(self, now: float) -> None:
        """Keep the table small: drop accounts whose window is empty."""
        if len(self._recent) < 1000:
            return
        for subject in [s for s, q in self._recent.items() if not q or now - q[-1] >= WINDOW_S]:
            del self._recent[subject]
