"""Rate limits of /chat: per account per minute, one cap per day for the whole Gateway, refused requests are not counted."""
import pytest
from fastapi import HTTPException

from app import main
from app.ratelimit import RateLimiter, WINDOW_S


class Clock:
    def __init__(self, now: float = 1_800_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def test_a_limit_of_zero_means_off():
    limiter = RateLimiter(0, 0, Clock())
    assert all(limiter.check("c-1") is None for _ in range(500))


def test_the_per_minute_limit_is_per_account():
    clock = Clock()
    limiter = RateLimiter(3, 0, clock)
    assert [limiter.check("c-1") for _ in range(4)] == [None, None, None, "minute"]
    assert limiter.check("c-2") is None                               # another account is not affected


def test_the_minute_window_slides():
    clock = Clock()
    limiter = RateLimiter(2, 0, clock)
    assert limiter.check("c-1") is None and limiter.check("c-1") is None and limiter.check("c-1") == "minute"
    clock.now += WINDOW_S                                              # a minute later the first two have left the window
    assert limiter.check("c-1") is None


def test_the_daily_cap_is_shared_by_every_account_and_resets_on_a_new_day():
    clock = Clock()
    limiter = RateLimiter(0, 3, clock)
    assert [limiter.check(f"c-{i}") for i in range(4)] == [None, None, None, "day"]
    clock.now += 86_400                                                # the next UTC day
    assert limiter.check("c-0") is None


def test_a_refused_request_is_not_counted():
    clock = Clock()
    limiter = RateLimiter(1, 2, clock)
    assert limiter.check("c-1") is None
    assert [limiter.check("c-1") for _ in range(5)] == ["minute"] * 5   # these must not use up the daily cap
    assert limiter.check("c-2") is None                                 # the second and last request of the day
    assert limiter.check("c-3") == "day"


def test_the_idle_table_does_not_grow_without_limit():
    clock = Clock()
    limiter = RateLimiter(5, 0, clock)
    for i in range(1500):
        limiter.check(f"c-{i}")
    clock.now += 2 * WINDOW_S
    limiter.check("late")
    assert len(limiter._recent) < 1500


def test_the_endpoint_helper_answers_429_and_says_which_limit(monkeypatch):
    monkeypatch.setattr(main.app.state, "limiter", RateLimiter(1, 0, Clock()), raising=False)
    main.enforce_rate_limit("c-1")                                      # the first one passes
    with pytest.raises(HTTPException) as refused:
        main.enforce_rate_limit("c-1")
    assert refused.value.status_code == 429 and refused.value.detail == "minute"
    assert refused.value.headers["Retry-After"] == "60"


def test_the_endpoint_helper_does_nothing_when_no_limiter_is_set(monkeypatch):
    monkeypatch.delattr(main.app.state, "limiter", raising=False)
    main.enforce_rate_limit("c-1")
