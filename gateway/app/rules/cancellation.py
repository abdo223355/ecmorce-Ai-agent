"""Cancellation eligibility: POL-CAN-001 v2.0 (ACTIVE, effective 2026-03-01), sections 2 to 4.

In V1 this is READ-ONLY guidance: the agent says whether the order can be cancelled and never cancels (section 1).
The decision depends on the order status the backend gives (never on the customer's description, section 1), and on the
item flags for the exceptions of section 4.

What the code cannot know, so it asks a person (kind "review"), never guesses:
- Processing: section 2 says "Requires Customer Service review", and the 4-hour window needs processing_started_at and
  packing_started_at, which the order endpoint does not give. Section 7: Processing requests always need a review.
- custom-made items (not cancellable once production has started), pre-orders (until 3 days before the release date) and
  gift cards (not after the code is issued): the production, release and code facts are not in the data.
- Failed Delivery and any status this code does not know.

REVIEWED: the project owner confirmed the rules (STATUS_RULE and the section 4 exceptions) against the PDF on 2026-11-04.
TODO(owner): the wording below is still a DRAFT. Review it.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..schemas import OrderView

DOC, VERSION = "POL-CAN-001", "2.0"
PROCESSING_WINDOW_HOURS = 4                      # section 3: from processing_started_at (shown in the review text only)

# order status -> (kind, section). kinds: "eligible", "not_eligible", "review", "return_instead", "already_cancelled"
STATUS_RULE: dict[str, tuple[str, str]] = {
    "Pending": ("eligible", "§2"),               # "Yes. No conditions. Item-level (partial) cancellation allowed."
    "Confirmed": ("eligible", "§2"),
    "Processing": ("review", "§2"),              # conditional, always a Customer Service review (§2, §7)
    "Packed": ("not_eligible", "§2"),            # "No. Order is physically prepared. Customer may refuse the delivery or use POL-RET-001"
    "Shipped": ("not_eligible", "§2"),
    "Out for Delivery": ("not_eligible", "§2"),
    "Delivered": ("return_instead", "§2"),       # "not a cancellation case": return (POL-RET-001) or exchange (POL-EXC-001)
    "Cancelled": ("already_cancelled", "§2"),    # "Not applicable. Order already cancelled."
    "Failed Delivery": ("review", "§2"),         # "Not applicable. Handled by Customer Service"
}
CANCELLABLE_STATUSES = ("Pending", "Confirmed", "Processing")      # where the §4 exceptions can still matter


@dataclass(frozen=True)
class Verdict:
    kind: str                     # eligible | not_eligible | review | return_instead | already_cancelled
    reason: str                   # a fixed word: the status, or custom_made / pre_order / gift_card / unknown_status
    cited: str                    # "POL-CAN-001 §2@2.0"


def _cite(section: str) -> str:
    return f"{DOC} {section}@{VERSION}"


def check_cancellation(order: OrderView) -> Verdict:
    """The verdict for ONE validated order. No customer text goes in."""
    rule = STATUS_RULE.get(order.status)
    if rule is None:
        return Verdict("review", "unknown_status", _cite("§2"))
    kind, section = rule
    if order.status in CANCELLABLE_STATUSES:
        for item in order.items:                      # §4: special items cannot be judged from our data
            if item.custom_made:
                return Verdict("review", "custom_made", _cite("§4"))
            if item.pre_order:
                return Verdict("review", "pre_order", _cite("§4"))
            if item.category == "gift_card":
                return Verdict("review", "gift_card", _cite("§4"))
    return Verdict(kind, order.status, _cite(section))


# ---- the words (a draft; placeholders only, the code fills the values; no promised time) ----
TEXTS: dict[tuple[str, str], str] = {
    ("eligible", "ar"): "طلبك {order_id} ({order_status}) ينفع يتلغى، كله أو منتج منه بس. الإلغاء بيتم عن طريق خدمة العملاء: اكتب \"كلّم موظف\" وأنا أحوّلك.",
    ("eligible", "en"): "Your order {order_id} ({order_status}) can be cancelled, either all of it or a single item. Cancellation is handled by Customer Service: say \"talk to an agent\" and I will pass you on.",
    ("not_eligible", "ar"): "طلبك {order_id} ({order_status}) اتجهّز فمينفعش يتلغى دلوقتي. عندك اختياران: ترفض الاستلام عند الباب، أو ترجّعه بعد التسليم حسب سياسة الإرجاع.",
    ("not_eligible", "en"): "Your order {order_id} ({order_status}) is already prepared, so it can no longer be cancelled. You have two options: refuse the delivery at the door, or return it after delivery under the return policy.",
    ("return_instead", "ar"): "طلبك {order_id} اتسلّم خلاص، فمفيش إلغاء. اسألني عن الإرجاع أو الاستبدال لو عايز.",
    ("return_instead", "en"): "Your order {order_id} was already delivered, so it cannot be cancelled. Ask me about a return or an exchange if you like.",
    ("already_cancelled", "ar"): "طلبك {order_id} متلغي بالفعل.",
    ("already_cancelled", "en"): "Your order {order_id} is already cancelled.",
    ("review_processing", "ar"): "طلبك {order_id} ({order_status}) بيتجهّز دلوقتي. الإلغاء في الحالة دي ممكن بس في أول {window_hours} ساعات من بدء التجهيز، وموظف خدمة العملاء هو اللي بيقرر.",
    ("review_processing", "en"): "Your order {order_id} ({order_status}) is being prepared. In this state it can be cancelled only within the first {window_hours} hours of processing, and a Customer Service agent decides.",
    ("review_special", "ar"): "طلبك {order_id} فيه منتج مخصوص أو حجز مسبق أو بطاقة هدية، والإلغاء في الحالات دي له شروط خاصة وموظف خدمة العملاء هو اللي بيراجعه.",
    ("review_special", "en"): "Your order {order_id} has a custom-made item, a pre-order or a gift card. Cancelling those has special conditions, and a Customer Service agent reviews it.",
    ("review_other", "ar"): "طلبك {order_id} ({order_status}) محتاج موظف خدمة العملاء يراجعه، وبيتحوّل ليه.",
    ("review_other", "en"): "Your order {order_id} ({order_status}) needs a Customer Service agent to review it, and it is being passed on.",
}


def text_key(verdict: Verdict) -> str:
    if verdict.kind != "review":
        return verdict.kind
    if verdict.reason == "Processing":
        return "review_processing"
    if verdict.reason in ("custom_made", "pre_order", "gift_card"):
        return "review_special"
    return "review_other"
