"""Exchange eligibility: POL-EXC-001 v1.1 (ACTIVE, effective 2026-09-01), sections 2, 3, 4, 6 and 8.

In V1 this is READ-ONLY guidance: the agent says whether an item can be exchanged and never creates an exchange (section 1).
An exchange is NOT a return: it ends with a replacement item, a return ends with a refund. The verdict comes from the order the
backend gives (status, delivered_at, the item's category and flags), never from the customer's words.

Rules as structured values:
- the order must be Delivered with delivered_at present (section 2.1); the request within 14 calendar days of delivery (2.2),
  counted like the return window: the CAIRO calendar day of delivered_at plus 14, the last day ends 23:59 Cairo;
- electronics and small appliances are not exchangeable, except a defective item replaced like-for-like within 30 days if there
  is stock, otherwise a return (sections 3 and 6);
- beauty, perishable, gift cards and custom-made items are not exchangeable for a size, colour or variant (section 3), BUT a WRONG
  item delivered in beauty or custom-made is still exchanged within 30 days (section 6 makes no category exception). This is a
  DECISION TAKEN BY CLAUDE as the policy owner (delegated by him, 2026-11-04): sections 3 and 6 can be read both ways. Gift cards
  stay not exchangeable (a digital code);
- Final Sale / Clearance: only a defective or wrong item (section 3);
- a WRONG item delivered: exchange for the correct item within 30 days, free of charge (section 6);
- holiday orders (delivered 2026-11-15 to 2026-12-31): the window is extended to 2027-01-15, and the longer window applies
  (section 6, and the design's audit #3).

What the data cannot show, so the answer says it as the policy's CONDITION and never decides it: that the replacement is the
same product in another size, colour or variant (section 2.3), that the item is unused with tags (2.4), that the replacement is in
stock (2.5; section 8: a stock gap goes to a person), that this order line has no earlier exchange (2.6), and whether an item is
defective or wrong. A category this code does not know is a review.

KNOWN DATA GAP: the backend category "home" can hold small appliances (for example an air fryer) that the policy treats like
electronics. The category alone cannot tell them apart, so they are treated as ordinary home goods here (as in returns.py). The
owner of the backend should add a subcategory or a flag.

DECISIONS: the project owner delegated the open questions to the coding assistant acting as the policy owner (2026-11-04). They are listed in
docs/ELIGIBILITY_DECISIONS.md (a wrong item in beauty or custom-made is exchanged within 30 days; the Final Sale windows; the holiday
window applies to every window; a Cancelled order cannot be exchanged; small appliances in "home" are ordinary home goods).
TODO(owner): the wording of the answers is still a DRAFT (Arabic and English).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from ..schemas import BackendItem, OrderView
from .returns import BEFORE_DELIVERY, HOLIDAY_FIRST, HOLIDAY_LAST, cairo_today, delivered_day

DOC, VERSION = "POL-EXC-001", "1.1"
EXCHANGE_DAYS, WRONG_OR_DEFECT_DAYS, WAITING_LIST_DAYS = 14, 30, 7
HOLIDAY_EXCHANGE_UNTIL = date(2027, 1, 15)
SECOND_KEY = "wrong"                                           # the second date placeholder of a line is i{n}_wrong_date

STANDARD = frozenset({"apparel", "home", "books", "toys", "accessories"})
GIFT_CARDS = frozenset({"gift_card", "digital"})
EXCLUDED_LABELS = frozenset({"final_sale", "clearance"})


@dataclass(frozen=True)
class ItemVerdict:
    name: str
    kind: str          # eligible | wrong_item_only | defective_only | not_exchangeable | expired | review
    reason: str        # standard | electronics | final_sale | beauty | gift_card | custom_made | unknown_category
    last_day: date | None          # the last day that applies to this line
    second_day: date | None        # eligible and Final Sale: the last day for a WRONG item (30 days)


@dataclass(frozen=True)
class OrderVerdict:
    kind: str          # items | not_delivered | review
    reason: str
    delivered_date: date | None
    items: tuple[ItemVerdict, ...]
    sections: tuple[str, ...]

    @property
    def cited(self) -> list[str]:
        return [f"{DOC} {s}@{VERSION}" for s in self.sections]


def window_end(delivered: date, days: int) -> date:
    """Last day of a window (ends 23:59 Cairo); a holiday order gets the longer of this and 2027-01-15."""
    end = delivered + timedelta(days=days)
    if HOLIDAY_FIRST <= delivered <= HOLIDAY_LAST:
        end = max(end, HOLIDAY_EXCHANGE_UNTIL)
    return end


def check_item(item: BackendItem, delivered: date, today: date) -> ItemVerdict:
    general_end, wrong_end = window_end(delivered, EXCHANGE_DAYS), window_end(delivered, WRONG_OR_DEFECT_DAYS)
    if item.category in GIFT_CARDS:
        return ItemVerdict(item.name, "not_exchangeable", item.category, None, None)
    if item.category == "beauty" or item.custom_made:               # no size/colour exchange, but a WRONG item: 30 days (decision)
        reason = "custom_made" if item.custom_made else "beauty"
        if today <= wrong_end:
            return ItemVerdict(item.name, "wrong_item_only", reason, wrong_end, None)
        return ItemVerdict(item.name, "expired", reason, wrong_end, None)
    if item.category == "electronics":                              # only a defective item like-for-like, or a wrong one: 30 days
        if today <= wrong_end:
            return ItemVerdict(item.name, "defective_only", "electronics", wrong_end, None)
        return ItemVerdict(item.name, "expired", "electronics", wrong_end, None)
    if item.category not in STANDARD:
        return ItemVerdict(item.name, "review", "unknown_category", None, None)
    if item.sale_label in EXCLUDED_LABELS:                          # only a defective or wrong item
        if today <= general_end:
            return ItemVerdict(item.name, "defective_only", "final_sale", general_end, wrong_end)
        if today <= wrong_end:
            return ItemVerdict(item.name, "wrong_item_only", "final_sale", wrong_end, None)
        return ItemVerdict(item.name, "expired", "final_sale", wrong_end, None)
    if today <= general_end:
        return ItemVerdict(item.name, "eligible", "standard", general_end, wrong_end)
    if today <= wrong_end:                                          # past 14 days: only a wrong item is still exchanged
        return ItemVerdict(item.name, "wrong_item_only", "standard", wrong_end, None)
    return ItemVerdict(item.name, "expired", "standard", wrong_end, None)


def check_exchange(order: OrderView, item_clue: str | None = None, today: date | None = None) -> OrderVerdict:
    """The verdict for ONE validated order. `item_clue` narrows it to the one item that has that word."""
    today = today or cairo_today()
    if order.status in BEFORE_DELIVERY:
        return OrderVerdict("not_delivered", order.status, None, (), ("§2",))
    if order.status != "Delivered":
        return OrderVerdict("review", order.status, None, (), ("§2",))
    if order.delivered_at is None:
        return OrderVerdict("review", "delivered_without_date", None, (), ("§2",))
    delivered = delivered_day(order.delivered_at)
    items = list(order.items)
    if item_clue and item_clue.strip():
        hits = [i for i in items if item_clue.strip().casefold() in i.name.casefold()]
        if len(hits) == 1:
            items = hits
    verdicts = tuple(check_item(i, delivered, today) for i in items)
    sections = ["§2"]
    if any(v.reason in ("electronics", "final_sale", "beauty", "custom_made") or v.kind in ("not_exchangeable", "wrong_item_only") for v in verdicts):
        sections.append("§3")
    if any(v.kind in ("wrong_item_only", "defective_only") or (v.kind == "eligible") for v in verdicts):
        sections.append("§6")
    if any(v.kind in ("eligible", "defective_only") for v in verdicts):
        sections.append("§4")
    return OrderVerdict("items", "Delivered", delivered, verdicts, tuple(dict.fromkeys(sections)))


# ---- the words (a draft; placeholders only, the code fills the values; no promised time or amount) ----
HEADER = {
    "items": {"ar": "طلبك {order_id} اتسلّم يوم {delivered_date}. بالنسبة للاستبدال (ده غير الإرجاع: الاستبدال بيخلص بمنتج بديل):",
              "en": "Your order {order_id} was delivered on {delivered_date}. About an exchange (this is not a return: an exchange ends with a replacement item):"},
    "not_delivered": {"ar": "طلبك {order_id} ({order_status}) لسه ما اتسلّمش، فمينفعش يتبدّل دلوقتي.",
                      "en": "Your order {order_id} ({order_status}) has not been delivered yet, so it cannot be exchanged now."},
    "review": {"ar": "طلبك {order_id} ({order_status}) محتاج موظف خدمة العملاء يراجعه، وبيتحوّل ليه.",
               "en": "Your order {order_id} ({order_status}) needs a Customer Service agent to review it, and it is being passed on."},
    "review_date": {"ar": "طلبك {order_id} اتسلّم، بس تاريخ التسليم مش واضح في بياناتي، فموظف هيراجعه.",
                    "en": "Your order {order_id} was delivered, but the delivery date is not clear in my data, so an agent will review it."},
}
LINE = {
    ("eligible", "*"): {
        "ar": "- {{i{i}_name}}: ممكن يتبدّل بنفس المنتج بمقاس أو لون تاني لحد {{i{i}_end_date}}، بشرط يكون غير مستخدم وبعبوته الأصلية والتاجز. ولو اتسلّمت لك حاجة غلط، لحد {{i{i}_wrong_date}}.",
        "en": "- {{i{i}_name}}: it can be exchanged for the same product in another size or colour until {{i{i}_end_date}}, if it is unused, in its original packaging and with tags. If you were sent the wrong item, until {{i{i}_wrong_date}}."},
    ("wrong_item_only", "*"): {
        "ar": "- {{i{i}_name}}: فات ميعاد الاستبدال العادي. لو اتسلّمت لك حاجة غلط ممكن تتبدّل من غير تكلفة لحد {{i{i}_end_date}}. ولو عايز ترجّعه اسألني عن الإرجاع.",
        "en": "- {{i{i}_name}}: the normal exchange period is over. If you were sent the wrong item it can be exchanged free of charge until {{i{i}_end_date}}. If you want to return it, ask me about a return."},
    ("defective_only", "electronics"): {
        "ar": "- {{i{i}_name}}: الإلكترونيات مش بتتبدّل إلا لو معيبة (بنفس المنتج) أو اتسلّمت غلط، لحد {{i{i}_end_date}}، ولو في مخزون. وغير كده بتتّرجع.",
        "en": "- {{i{i}_name}}: electronics are exchanged only if defective (for the same product) or sent by mistake, until {{i{i}_end_date}}, if there is stock. Otherwise it is returned."},
    ("defective_only", "final_sale"): {
        "ar": "- {{i{i}_name}}: تخفيضات نهائية، فمش بيتبدّل إلا لو معيب أو غلط. المعيب لحد {{i{i}_end_date}}، والغلط لحد {{i{i}_wrong_date}}.",
        "en": "- {{i{i}_name}}: a final-sale item is exchanged only if defective or wrong. A defective one until {{i{i}_end_date}}, a wrong one until {{i{i}_wrong_date}}."},
    ("wrong_item_only", "beauty"): {
        "ar": "- {{i{i}_name}}: مستحضرات التجميل مش بتتبدّل بمقاس أو لون تاني. لو اتسلّمت لك حاجة غلط ممكن تتبدّل من غير تكلفة لحد {{i{i}_end_date}}.",
        "en": "- {{i{i}_name}}: beauty products are not exchanged for another size or colour. If you were sent the wrong item it can be exchanged free of charge until {{i{i}_end_date}}."},
    ("wrong_item_only", "custom_made"): {
        "ar": "- {{i{i}_name}}: المنتج المخصوص مش بيتبدّل بمقاس أو لون تاني. لو اتسلّمت لك حاجة غلط ممكن تتبدّل من غير تكلفة لحد {{i{i}_end_date}}.",
        "en": "- {{i{i}_name}}: a custom-made item is not exchanged for another size or colour. If you were sent the wrong item it can be exchanged free of charge until {{i{i}_end_date}}."},
    ("not_exchangeable", "*"): {
        "ar": "- {{i{i}_name}}: بطاقات الهدية والمنتجات الرقمية مش بتتبدّل.",
        "en": "- {{i{i}_name}}: gift cards and digital goods cannot be exchanged."},
    ("expired", "*"): {
        "ar": "- {{i{i}_name}}: فات ميعاد الاستبدال (كان لحد {{i{i}_end_date}}). ممكن لسه ينفع إرجاع، اسألني عنه. وأي استثناء بيقرره موظف خدمة العملاء بس.",
        "en": "- {{i{i}_name}}: the exchange period is over (it was until {{i{i}_end_date}}). A return may still be possible, ask me about it. Only a Customer Service agent can grant an exception."},
    ("review", "*"): {
        "ar": "- {{i{i}_name}}: مش قادر أحدد من بياناتي، فموظف هيراجعه.",
        "en": "- {{i{i}_name}}: I cannot tell from my data, so an agent will review it."},
}
# Said once when an exchange is possible (sections 2.5, 3 and 4): stock, the price difference, what if it is unavailable.
CONDITIONS = {
    "ar": "الاستبدال بيتم لو المتغير المطلوب متاح وقت التنفيذ. لو أغلى بتدفع الفرق، ولو أرخص الفرق بيتردّ رصيد في المتجر مش كاش. ولو مش متاح تختار متغير تاني، أو تنضم لقايمة انتظار لحد {waiting_days} أيام، أو تحوّله لإرجاع.",
    "en": "An exchange goes ahead if the requested variant is in stock when it is processed. If it costs more you pay the difference; if it costs less the difference is given as store credit, not cash. If it is unavailable you can choose another variant, join a waiting list for up to {waiting_days} days, or turn it into a return.",
}
FOOTER = {"ar": "الاستبدال بيتم عن طريق خدمة العملاء: اكتب \"كلّم موظف\" وأنا أحوّلك.",
          "en": "An exchange is handled by Customer Service: say \"talk to an agent\" and I will pass you on."}


def line_for(verdict: ItemVerdict, language: str) -> str:
    entry = LINE.get((verdict.kind, verdict.reason)) or LINE[(verdict.kind, "*")]
    return entry[language]


def needs_person(verdict: OrderVerdict) -> bool:
    return verdict.kind == "review" or any(v.kind == "review" for v in verdict.items)


def mentions_conditions(verdict: OrderVerdict) -> bool:
    """Say the stock / price / unavailable text only when at least one line is an exchange that can go ahead."""
    return any(v.kind in ("eligible", "defective_only", "wrong_item_only") for v in verdict.items)
