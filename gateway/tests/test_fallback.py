"""The static text for a handoff that could not be recorded: right facts, no invented number, no promise."""
import re

import pytest

from app.agent import AgentResult, Segment
from app.events import build_event
from app.fallback import Phones, detect_language, static_fallback
from app.handoffs import COULD_NOT_FINISH, keep_the_promise, without_promise

NONE = Phones()
ALL = Phones("CS-LINE", "EMERGENCY-LINE", "DISPATCH-LINE")
CASES = [("customer", False), ("customer", True), ("worker", False), ("worker", True)]


@pytest.mark.parametrize("role,p1", CASES)
@pytest.mark.parametrize("language", ["ar", "en"])
def test_every_case_in_both_languages_has_a_text_and_never_a_made_up_number(role, p1, language):
    text = static_fallback(role, p1, language, NONE)
    assert text and "{" not in text and "None" not in text
    assert not re.search(r"\d{5,}", text)                      # no phone-like number appears when none is configured
    assert not re.search(r"\+\d|\(\d{2,}\)", text)


@pytest.mark.parametrize("role,p1,key,line", [("customer", False, "customer_service", "CS-LINE"), ("customer", True, "emergency", "EMERGENCY-LINE"),
                                              ("worker", False, "dispatch", "DISPATCH-LINE"), ("worker", True, "emergency", "EMERGENCY-LINE")])
@pytest.mark.parametrize("language", ["ar", "en"])
def test_the_right_configured_number_is_used_when_it_is_set(role, p1, key, line, language):
    assert line in static_fallback(role, p1, language, ALL)
    others = {"CS-LINE", "EMERGENCY-LINE", "DISPATCH-LINE"} - {line}
    if not (role == "worker" and p1):                           # a worker's P1 gives the emergency line AND the dispatch line (POL-BUS-001 §4)
        assert not any(o in static_fallback(role, p1, language, ALL) for o in others)
    assert "DISPATCH-LINE" in static_fallback("worker", True, language, ALL)


def test_the_hours_are_the_ones_of_pol_bus_001_v1_2():
    customer_en, worker_en = static_fallback("customer", False, "en", NONE), static_fallback("worker", False, "en", NONE)
    for fact in ("Saturday to Thursday 09:00 to 21:00", "Friday 13:00 to 19:00", "official public holidays 11:00 to 17:00", "Cairo time"):
        assert fact in customer_en
    for fact in ("Saturday to Thursday 08:00 to 22:00", "Friday 12:00 to 20:00", "only P1 cases are handled"):
        assert fact in worker_en
    customer_ar, worker_ar = static_fallback("customer", False, "ar", NONE), static_fallback("worker", False, "ar", NONE)
    for fact in ("من 9 ص لـ 9 م", "من 1 م لـ 7 م", "من 11 ص لـ 5 م", "بتوقيت القاهرة"):
        assert fact in customer_ar
    for fact in ("من 8 ص لـ 10 م", "من 12 ظ لـ 8 م", "حالات P1 بس"):
        assert fact in worker_ar


def test_the_emergency_line_is_said_to_be_open_all_day():
    assert "24" in static_fallback("customer", True, "ar", NONE) and "24/7" in static_fallback("customer", True, "en", NONE)


def test_no_text_promises_that_anything_was_registered_or_that_someone_will_reply():
    for role, p1 in CASES:
        for language in ("ar", "en"):
            text = static_fallback(role, p1, language, ALL).lower()
            assert not any(w in text for w in ("registered", "will contact", "will call", "we will", "هيتواصل", "هنرد", "اتسجّل", "حوّلتك", "حوّلت"))


def test_the_language_follows_the_letters_of_the_message_and_defaults_to_english():
    assert detect_language("حد دخل على حسابي") == "ar" and detect_language("someone hacked my account") == "en" and detect_language("") == "en"


# ---------- wired into the promise ----------
class Failing:
    async def create(self, row):
        raise RuntimeError("database down")


def handed(priority, reason="SAFE") -> AgentResult:
    return AgentResult(segments=[Segment(0, "template", template_id=8)], handoff_reason=reason, priority=priority,
                       handoff_summary={"parts": []}, telemetry={"classify": {"path": "llm", "status": "ok"}})


def test_a_failed_write_gives_the_static_text_of_the_users_role_and_language():
    import asyncio
    out = asyncio.run(keep_the_promise(Failing(), "customer", "C-1", handed("P1"), "حد دخل على حسابي"))
    assert out.segments[0].kind == "text" and out.segments[0].template_id == COULD_NOT_FINISH
    assert out.segments[0].text == static_fallback("customer", True, "ar", Phones())
    out = asyncio.run(keep_the_promise(Failing(), "worker", "W-1", handed("P3", "POL"), "I have a problem delivering"))
    assert out.segments[0].text == static_fallback("worker", False, "en", Phones())


def test_the_configured_numbers_reach_the_text(monkeypatch):
    import dataclasses

    import app.handoffs as h
    monkeypatch.setattr(h, "settings", dataclasses.replace(h.settings, emergency_phone="EMERGENCY-LINE"))
    assert "EMERGENCY-LINE" in without_promise(handed("P1"), "customer", "en", h.configured_phones()).segments[0].text


def test_the_event_of_such_a_turn_still_counts_as_template_18():
    out = without_promise(handed("P1"), "customer", "ar", NONE)
    assert build_event("customer", out, 1.0)["outcomes"] == [{"kind": "text", "template_id": COULD_NOT_FINISH}]
