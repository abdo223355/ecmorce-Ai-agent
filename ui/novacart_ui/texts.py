"""Turn the Gateway's answer into words the user reads.

The Gateway returns a template id and render values (or a model text with typed placeholders such as {order_id}).
Substituting real values into text is the render step of 11 (Milestone 2, D66). Until 11 exists, this file does it for
the screen.

TODO(owner): every wording below is a PROVISIONAL DRAFT, for the screen only. The final D68 template
  texts belong to 11. Read them, correct the wording, and say which ones are wrong. Rules kept on purpose: no promised
  times, no money amounts, no business rule that is not in docs/design.
"""
from __future__ import annotations

import re
from datetime import datetime

from .api import ChatReply, SegmentView

ARABIC = re.compile(r"[؀-ۿ]")
PLACEHOLDER = re.compile(r"\{([a-z_0-9]+)\}")

# template id -> {"ar": ..., "en": ...}. The ids and meanings are D68 as the agent uses them.
TEXTS: dict[int, dict[str, str]] = {
    1: {"ar": "طلبك {order_id} حالته: {order_status}. آخر تحديث: {last_updated}.",
        "en": "Your order {order_id} is: {order_status}. Last updated: {last_updated}."},
    2: {"ar": "المرتجع {return_id} ({item}) حالته: {return_status}. آخر تحديث: {last_updated}.",
        "en": "Your return {return_id} ({item}) is: {return_status}. Last updated: {last_updated}."},
    3: {"ar": "شحناتك النهارده ({date}): {count}\n{rows_text}",
        "en": "Your shipments today ({date}): {count}\n{rows_text}"},
    5: {"ar": "حوّلت طلبك لموظف خدمة العملاء، وهيتواصل معاك.",
        "en": "I passed your request to a customer service agent, who will contact you."},
    6: {"ar": "بلّغت الـ dispatch وخدمة العملاء بطلبك.",
        "en": "I notified dispatch and customer service about your request."},
    8: {"ar": "ده موضوع أمان وبياخد أولوية. حوّلتك لفريقنا فورًا، ومش هعرض أي بيانات حساب دلوقتي.",
        "en": "This is a safety matter and gets priority. I passed it to our team right away, and I will not show any account data now."},
    9: {"ar": "الموضوع ده برا اللي أقدر أساعد فيه هنا.",
        "en": "That topic is outside what I can help with here."},
    10: {"ar": "مش بقدر أنفّذ الإجراء ده بنفسي دلوقتي. حوّلتك لموظف.",
         "en": "I can't carry out that action myself right now. I passed you to an agent."},
    11: {"ar": "المعلومة دي مش متاحة دلوقتي. حوّلتها لفريق الدعم.",
         "en": "That information is not available right now. I passed it to the support team."},
    12: {"ar": "السياسة مش واضحة في الحالة دي، فحوّلتك لموظف يأكدلك.",
         "en": "The policy is not clear for this case, so I passed you to an agent to confirm."},
    14: {"ar": "مش لاقي الطلب ده في حسابك. اتأكد من الرقم وجرّب تاني.",
         "en": "I can't find that order in your account. Check the number and try again."},
    15: {"ar": "مقدرتش أفهم رسالتك. ممكن تعيد صياغتها، أو تختار من الأزرار اللي تحت.",
         "en": "I could not understand your message. Please rephrase it, or pick one of the buttons below."},
    16: {"ar": "مش مسموح لك بالبيانات دي.",
         "en": "You are not allowed to see that data."},
    17: {"ar": "مش لاقي الشحنة دي ضمن شحناتك.",
         "en": "I can't find that shipment among yours."},
    18: {"ar": "مقدرتش أكمل الطلب ده. جرّب تاني، أو اطلب موظف.",
         "en": "I could not finish this request. Try again, or ask for an agent."},
}
UNKNOWN_TEMPLATE = {"ar": "(قالب رقم {n} لسه من غير نص)", "en": "(template {n} has no text yet)"}


def detect_language(message: str) -> str:
    """The language of the user's last message: Arabic if it has Arabic letters, else English."""
    return "ar" if ARABIC.search(message) else "en"


# ---- how raw values are shown (the screen shows words and dates, not codes) ----
# TODO(owner): the Arabic words for the statuses are a DRAFT. Status names come from the backend models.
STATUS_AR = {
    "Pending": "قيد الانتظار", "Confirmed": "تم التأكيد", "Processing": "قيد التجهيز", "Packed": "تم التغليف",
    "Shipped": "تم الشحن", "Out for Delivery": "خرج للتوصيل", "Delivered": "تم التسليم",
    "Failed Delivery": "فشل التوصيل", "Cancelled": "ملغي",
    "Requested": "تم طلب الإرجاع", "Approved": "تمت الموافقة", "Rejected": "مرفوض", "Picked Up": "تم الاستلام من العميل",
    "Received": "وصل للمخزن", "Refunded": "تم رد المبلغ",
}
MONTHS_AR = ("يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
STATUS_KEYS = {"order_status", "return_status"}
MOMENT_KEYS = {"last_updated"}                     # an ISO date-time (the backend already gives Cairo time)
DAY_KEYS = {"order_date", "date"}                  # an ISO date


def present(key: str, value, language: str):
    """A raw value as the user should read it. Anything it does not recognise is returned unchanged (never guessed)."""
    if not isinstance(value, str):
        return value
    if (key in STATUS_KEYS or key.endswith("_status")) and language == "ar":
        return STATUS_AR.get(value, value)
    if key in MOMENT_KEYS or key in DAY_KEYS or key.endswith(("_updated", "_date")):
        try:
            when = datetime.fromisoformat(value)
        except ValueError:
            return value
        month = (MONTHS_AR if language == "ar" else MONTHS_EN)[when.month - 1]
        day = f"{when.day} {month} {when.year}"
        if key in DAY_KEYS or key.endswith("_date") or len(value) <= 10:                 # a date with no time of day shows the day only
            return day
        return f"{day} الساعة {when:%H:%M}" if language == "ar" else f"{day} at {when:%H:%M}"
    return value


def fill(text: str, values: dict) -> str:
    """Put real values into {placeholders}. A key with no value stays as it is (never guessed). A value with line
    breaks keeps them as markdown line breaks and sits between blank lines, so a list never swallows the words after it."""
    def pick(m: re.Match) -> str:
        value = values.get(m.group(1))
        if value is None:
            return m.group(0)
        text = str(value)
        return "\n\n" + text.replace("\n", "  \n") + "\n\n" if "\n" in text else text
    return PLACEHOLDER.sub(pick, text)


def _template_text(template_id: int | None, language: str) -> str:
    if template_id in TEXTS:
        return TEXTS[template_id][language]
    return UNKNOWN_TEMPLATE[language].format(n=template_id)


def render_segment(segment: SegmentView, language: str) -> str:
    if segment.kind == "template" or not segment.text:
        base = _template_text(segment.template_id, language)        # a "text" segment with no text falls back to its template
    else:
        base = segment.text
    shown = {k: present(k, v, language) for k, v in segment.render_values.items()}
    return fill(base, shown).strip()


def render_reply(reply: ChatReply, language: str) -> str:
    """All the segments in written order, one paragraph each."""
    ordered = sorted(reply.segments, key=lambda s: s.part_index)
    return "\n\n".join(render_segment(s, language) for s in ordered)
