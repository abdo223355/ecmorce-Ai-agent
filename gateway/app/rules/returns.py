"""Return eligibility: POL-RET-001 v2.1 (ACTIVE, effective 2026-09-01), sections 2, 3, 5, 9 and 11.

In V1 this is READ-ONLY guidance: the agent says whether an item can be returned and never creates or approves a return
(section 1). The verdict comes from the order the backend gives (status, delivered_at, the item's category and flags),
never from the customer's words. Two things the data cannot show are told to the customer as the policy's CONDITION and
never decided here: the condition of the item (unused, unopened, sealed) and whether it is defective or wrong.

Rules as structured values:
- the window: 30 days (standard goods and beauty) or 15 days (electronics), counted from the CAIRO calendar day of
  delivered_at; day 1 is the day after delivery; the last day ends at 23:59 Cairo time (section 2);
- defective or wrong item: 30 days in any returnable category (section 5), evidence required;
- not returnable for change of mind: gift cards and digital goods (no exception), custom-made and Final Sale / Clearance
  (exception: defective, section 2);
- the order must be Delivered and delivered_at must be present (section 3); Pending to Out for Delivery are cancellation
  cases (POL-CAN-001); Failed Delivery goes to Customer Service;
- holiday extension: delivered 2026-11-15 to 2026-12-31 may be returned until 2027-01-31, and the longer window applies (section 9).

A category this code does not know is a review (a person decides), never a guess.

REVIEWED: the project owner confirmed the rules below on 2026-11-04, including: a Cancelled order cannot be returned, the holiday
window also applies to the defective window, an unknown category is a review, and small appliances in the category "home"
are treated as ordinary home goods until the backend has a subcategory (read from his answer "ok").
TODO(owner): the wording of the answers is still a DRAFT (Arabic and English).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..schemas import BackendItem, OrderView

DOC, VERSION = "POL-RET-001", "2.1"
CAIRO = ZoneInfo("Africa/Cairo")

STANDARD_DAYS, ELECTRONICS_DAYS, DEFECT_DAYS = 30, 15, 30
HOLIDAY_FIRST, HOLIDAY_LAST, HOLIDAY_RETURN_UNTIL = date(2026, 11, 15), date(2026, 12, 31), date(2027, 1, 31)

# category -> (window days, condition word). The category names are the backend's (backend/novacart_backend/seed.py).
CATEGORY_RULE: dict[str, tuple[int, str]] = {
    "apparel": (STANDARD_DAYS, "standard"), "home": (STANDARD_DAYS, "standard"), "books": (STANDARD_DAYS, "standard"),
    "toys": (STANDARD_DAYS, "standard"), "accessories": (STANDARD_DAYS, "standard"),
    "electronics": (ELECTRONICS_DAYS, "electronics"),
    "beauty": (STANDARD_DAYS, "beauty"),
}
NOT_RETURNABLE = frozenset({"gift_card", "digital"})                 # "No exceptions"
EXCLUDED_LABELS = frozenset({"final_sale", "clearance"})            # not returnable unless defective or wrong
SECOND_KEY = "defect"                                              # the second date placeholder of a line is i{n}_defect_date
BEFORE_DELIVERY = frozenset({"Pending", "Confirmed", "Processing", "Packed", "Shipped", "Out for Delivery", "Cancelled"})


def cairo_today() -> date:
    return datetime.now(CAIRO).date()


@dataclass(frozen=True)
class ItemVerdict:
    name: str
    kind: str          # eligible | defective_only | expired | not_returnable | review
    reason: str        # standard | electronics | beauty | custom_made | final_sale | electronics_window | gift_card | unknown_category
    last_day: date | None           # the last day to ask for a return (a change of mind, or a defect for defective_only / expired)
    defect_last_day: date | None    # the last day for a defective or wrong item (30 days, holiday-extended)

    @property
    def second_day(self) -> date | None:
        return self.defect_last_day


@dataclass(frozen=True)
class OrderVerdict:
    kind: str          # items | not_delivered | review
    reason: str        # Delivered | the status | delivered_without_date | unknown_status
    delivered_date: date | None
    items: tuple[ItemVerdict, ...]
    sections: tuple[str, ...]       # the document sections the answer used, e.g. ("§2", "§5")

    @property
    def cited(self) -> list[str]:
        return [f"{DOC} {s}@{VERSION}" for s in self.sections]


def delivered_day(delivered_at: datetime) -> date:
    """The Cairo calendar day of delivery. A time with no zone is taken as Cairo time."""
    return (delivered_at.astimezone(CAIRO) if delivered_at.tzinfo else delivered_at).date()


def window_end(delivered: date, days: int) -> date:
    """The last day (it ends 23:59 Cairo) of a window: the day of delivery plus `days`; the holiday window wins if longer."""
    end = delivered + timedelta(days=days)
    if HOLIDAY_FIRST <= delivered <= HOLIDAY_LAST:
        end = max(end, HOLIDAY_RETURN_UNTIL)
    return end


def check_item(item: BackendItem, delivered: date, today: date) -> ItemVerdict:
    defect_end = window_end(delivered, DEFECT_DAYS)
    if item.category in NOT_RETURNABLE:
        return ItemVerdict(item.name, "not_returnable", item.category, None, None)
    rule = CATEGORY_RULE.get(item.category)
    if rule is None:
        return ItemVerdict(item.name, "review", "unknown_category", None, None)
    days, condition = rule
    if item.custom_made or item.sale_label in EXCLUDED_LABELS:
        reason = "custom_made" if item.custom_made else "final_sale"
        if today <= defect_end:
            return ItemVerdict(item.name, "defective_only", reason, defect_end, defect_end)
        return ItemVerdict(item.name, "expired", reason, defect_end, defect_end)
    end = window_end(delivered, days)
    if today <= end:
        return ItemVerdict(item.name, "eligible", condition, end, defect_end)
    if today <= defect_end:                                           # electronics after day 15: only a defective or wrong item
        return ItemVerdict(item.name, "defective_only", "electronics_window", defect_end, defect_end)
    return ItemVerdict(item.name, "expired", condition, max(end, defect_end), defect_end)


def check_return(order: OrderView, item_clue: str | None = None, today: date | None = None) -> OrderVerdict:
    """The verdict for ONE validated order. `item_clue` (a product word) narrows it to the one item that has it."""
    today = today or cairo_today()
    if order.status in BEFORE_DELIVERY:
        return OrderVerdict("not_delivered", order.status, None, (), ("§3",))
    if order.status != "Delivered":                                   # Failed Delivery, a returned order, anything new
        return OrderVerdict("review", order.status, None, (), ("§3",))
    if order.delivered_at is None:                                    # §3.2: never estimate the date
        return OrderVerdict("review", "delivered_without_date", None, (), ("§3",))
    delivered = delivered_day(order.delivered_at)
    items = list(order.items)
    if item_clue and item_clue.strip():
        hits = [i for i in items if item_clue.strip().casefold() in i.name.casefold()]
        if len(hits) == 1:
            items = hits
    verdicts = tuple(check_item(i, delivered, today) for i in items)
    sections = ["§2"]
    if any(v.kind == "defective_only" or (v.kind == "eligible" and v.reason == "electronics") for v in verdicts):
        sections.append("§5")
    if HOLIDAY_FIRST <= delivered <= HOLIDAY_LAST:
        sections.append("§9")
    return OrderVerdict("items", "Delivered", delivered, verdicts, tuple(sections))


# ---- the words (a draft; placeholders only, the code fills the values; no promised time) ----
HEADER = {
    "items": {"ar": "طلبك {order_id} اتسلّم يوم {delivered_date}. بالنسبة للإرجاع:",
              "en": "Your order {order_id} was delivered on {delivered_date}. About returning it:"},
    "not_delivered": {"ar": "طلبك {order_id} ({order_status}) لسه ما اتسلّمش، فمينفعش يتّرجع دلوقتي. لو عايز تلغيه اسألني عن الإلغاء.",
                      "en": "Your order {order_id} ({order_status}) has not been delivered yet, so it cannot be returned now. To cancel it, ask me about cancellation."},
    "review": {"ar": "طلبك {order_id} ({order_status}) محتاج موظف خدمة العملاء يراجعه، وبيتحوّل ليه.",
               "en": "Your order {order_id} ({order_status}) needs a Customer Service agent to review it, and it is being passed on."},
    "review_date": {"ar": "طلبك {order_id} اتسلّم، بس تاريخ التسليم مش واضح في بياناتي، فموظف هيراجعه.",
                    "en": "Your order {order_id} was delivered, but the delivery date is not clear in my data, so an agent will review it."},
}
LINE = {
    ("eligible", "standard"): {
        "ar": "- {{i{i}_name}}: ممكن يتّرجع لحد {{i{i}_end_date}}، بشرط يكون غير مستخدم وبعبوته الأصلية والتاجز.",
        "en": "- {{i{i}_name}}: it can be returned until {{i{i}_end_date}}, if it is unused, in its original packaging and with tags."},
    ("eligible", "electronics"): {
        "ar": "- {{i{i}_name}}: الإلكترونيات ليها {{electronics_days}} يوم، يعني لحد {{i{i}_end_date}}، بشرط يكون غير مفتوح. ولو معيب أو غلط ممكن لحد {{i{i}_defect_date}}.",
        "en": "- {{i{i}_name}}: electronics have {{electronics_days}} days, until {{i{i}_end_date}}, if it is unopened. If it is defective or the wrong item, until {{i{i}_defect_date}}."},
    ("eligible", "beauty"): {
        "ar": "- {{i{i}_name}}: ممكن يتّرجع لحد {{i{i}_end_date}}، بشرط يكون مختوم وغير مفتوح.",
        "en": "- {{i{i}_name}}: it can be returned until {{i{i}_end_date}}, if it is sealed and unopened."},
    ("defective_only", "*"): {
        "ar": "- {{i{i}_name}}: مش بيتّرجع بسبب تغيير الرأي. بيتّرجع بس لو معيب أو غلط، لحد {{i{i}_end_date}}، ومحتاج رقم الطلب واسم المنتج وصورتين واضحتين ووصف مختصر.",
        "en": "- {{i{i}_name}}: it cannot be returned for a change of mind. It can be returned only if it is defective or the wrong item, until {{i{i}_end_date}}, with the order number, the item name, at least two clear photos and a short description."},
    ("expired", "*"): {
        "ar": "- {{i{i}_name}}: فات ميعاد الإرجاع (كان لحد {{i{i}_end_date}}). طلب الاستثناء بيقرره موظف خدمة العملاء بس.",
        "en": "- {{i{i}_name}}: the return period is over (it was until {{i{i}_end_date}}). Only a Customer Service agent can grant an exception."},
    ("not_returnable", "*"): {
        "ar": "- {{i{i}_name}}: بطاقات الهدية والمنتجات الرقمية مش بتتّرجع.",
        "en": "- {{i{i}_name}}: gift cards and digital goods cannot be returned."},
    ("review", "*"): {
        "ar": "- {{i{i}_name}}: مش قادر أحدد من بياناتي، فموظف هيراجعه.",
        "en": "- {{i{i}_name}}: I cannot tell from my data, so an agent will review it."},
}
FOOTER = {"ar": "الإرجاع بيتم عن طريق خدمة العملاء: اكتب \"كلّم موظف\" وأنا أحوّلك.",
          "en": "A return is handled by Customer Service: say \"talk to an agent\" and I will pass you on."}


def line_for(verdict: ItemVerdict, language: str) -> str:
    entry = LINE.get((verdict.kind, verdict.reason)) or LINE[(verdict.kind, "*")]
    return entry[language]


def needs_person(verdict: OrderVerdict) -> bool:
    return verdict.kind == "review" or any(v.kind == "review" for v in verdict.items)
