"""The static text a user gets when the Gateway could NOT record a handoff (the design's "static fallback", Phase 3: local
config, no dependency on the AI or the database). It tells the user where to go themselves, never that something was
"registered" (D14), and it promises no reply time (POL-BUS-001 section 3).

Every fact in it comes from the ACTIVE policy POL-BUS-001 v1.2, or from the owner's config:
- service hours, Cairo time (section 1): Saturday to Thursday 09:00 to 21:00, Friday 13:00 to 19:00, official public holidays 11:00 to 17:00;
- Dispatch hotline hours (section 5): 08:00 to 22:00 Saturday to Thursday, 12:00 to 20:00 Friday; outside them only P1 cases;
- the emergency line works 24/7 (section 3); an injury or threat during delivery uses the emergency line AND the Dispatch hotline (section 4).
The PHONE NUMBERS are in no document. They come from CS_PHONE, EMERGENCY_PHONE and DISPATCH_PHONE; a number that is not set
is left out of the sentence, never made up.

TODO(owner): the wording of the four texts (in both languages) is a DRAFT. Correct it. If POL-BUS-001 changes
  its hours, change the lines marked HOURS here (a test pins them to the values above).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

ARABIC = re.compile(r"[؀-ۿ]")


@dataclass(frozen=True)
class Phones:
    customer_service: str = ""
    emergency: str = ""
    dispatch: str = ""


def detect_language(message: str) -> str:
    """Arabic if the user's message has Arabic letters, else English. The message itself is never kept."""
    return "ar" if ARABIC.search(message) else "en"


def _on(phone: str, language: str) -> str:
    if not phone:
        return ""
    return f" على {phone}" if language == "ar" else f" on {phone}"


def static_fallback(role: str, p1: bool, language: str, phones: Phones) -> str:
    """The text for (role, P1 or not, language). Pure."""
    ar = language == "ar"
    cs, emergency, dispatch = (_on(p, language) for p in (phones.customer_service, phones.emergency, phones.dispatch))
    if role == "worker" and p1:
        return (f"ده موضوع أمان ومقدرتش أسجّله دلوقتي. اتصل فورًا بخط الطوارئ{emergency} (شغّال 24 ساعة) وبخط الـ dispatch{dispatch}." if ar else
                f"This is a safety matter and I could not record it now. Call the emergency line{emergency} (open 24/7) and the dispatch hotline{dispatch} right away.")
    if p1:
        return (f"ده موضوع أمان ومقدرتش أسجّله دلوقتي. اتصل فورًا بخط الطوارئ{emergency}، وهو شغّال 24 ساعة." if ar else
                f"This is a safety matter and I could not record it now. Call the emergency line{emergency} right away; it is open 24/7.")
    if role == "worker":
        return (f"مقدرتش أسجّل بلاغك دلوقتي. من فضلك كلّم الـ dispatch مباشرة{dispatch}. ساعات الـ dispatch بتوقيت القاهرة: "          # HOURS
                "السبت إلى الخميس من 8 ص لـ 10 م، والجمعة من 12 ظ لـ 8 م. برا الساعات دي بيتم التعامل مع حالات P1 بس." if ar else
                f"I could not record your report now. Please call the dispatch hotline directly{dispatch}. Dispatch hours, Cairo time: "
                "Saturday to Thursday 08:00 to 22:00, Friday 12:00 to 20:00. Outside those hours only P1 cases are handled.")     # HOURS
    return (f"مقدرتش أسجّل طلبك لخدمة العملاء دلوقتي. من فضلك تواصل معاهم مباشرة{cs}. ساعات العمل بتوقيت القاهرة: "                 # HOURS
            "السبت إلى الخميس من 9 ص لـ 9 م، والجمعة من 1 م لـ 7 م، والإجازات الرسمية من 11 ص لـ 5 م." if ar else
            f"I could not pass your request to Customer Service now. Please contact them directly{cs}. Service hours, Cairo time: "
            "Saturday to Thursday 09:00 to 21:00, Friday 13:00 to 19:00, official public holidays 11:00 to 17:00.")           # HOURS
