"""The code that plan rows refer to by name: selectors (pick a value from earlier results) and builders (turn the
final data into render values and LLM facts). Importing this module registers them.

Every builder returns two things (D60-A1): render_values, the real values that only code renders, and llm_facts,
what the reply LLM may see. In llm_facts a personal value (names, phones, addresses, COD, order and shipment ids,
return ids), a number or a date appears only as a typed placeholder such as "{order_id}", never as the value.
Placeholder KEY NAMES are provisional: the template wording and its keys are owned by 11 (Milestone 2). The values
come only from validated tool views, never from the user's text or from the LLM.
"""
from __future__ import annotations

from typing import Any

from ..schemas import BackendReturn, BackendReturnRow, OrderSummaryView, OrderView, TodayView
from ..tools import ToolResult
from .plan_spec import Built, NeedsClarification, ReadyOutcome, StepEnv, builder, selector
from .state import PartOutcome, Section

MAX_FAN_OUT = 5          # at most this many order_details calls for one part (the recent-orders list is short)
MAX_SECTIONS = 8         # at most this many policy sections per request (D94)


def _ok_data(value: Any) -> Any:
    return value.data if isinstance(value, ToolResult) and value.ok else None


def _recent_orders(env: StepEnv) -> list:
    data = _ok_data(env.results.get("recent"))
    return data if isinstance(data, list) else []


# ---- selectors ----
@selector("match_item_clue")
def match_item_clue(env: StepEnv) -> str | None:
    """The one recent order whose product names contain the clue. None when there is none or more than one."""
    clue = env.intent.arguments.get("item_clue")
    if not isinstance(clue, str) or not clue.strip():
        return None
    needle = clue.strip().casefold()
    hits = [o for o in _recent_orders(env) if any(needle in name.casefold() for name in o.product_names)]
    return hits[0].order_id if len(hits) == 1 else None


@selector("only_order")
def only_order(env: StepEnv) -> str | None:
    """The customer's only recent order. None when there are none or several (the user must choose)."""
    orders = _recent_orders(env)
    return orders[0].order_id if len(orders) == 1 else None


@selector("recent_order_ids")
def recent_order_ids(env: StepEnv) -> list[str]:
    return [o.order_id for o in _recent_orders(env)][:MAX_FAN_OUT]


# ---- builders ----
def _order_views(env: StepEnv) -> list[OrderView]:
    """Every OrderView the steps produced: one from `order`, or several from the fan-out `orders`."""
    views = []
    single = _ok_data(env.results.get("order"))
    if isinstance(single, OrderView):
        views.append(single)
    for result in env.results.get("orders", []):
        data = _ok_data(result)
        if isinstance(data, OrderView):
            views.append(data)
    return views


@builder("order_status")
def order_status(env: StepEnv) -> Built | None:
    views = _order_views(env)
    if not views:
        return None
    order = views[0]
    return Built(
        render_values={"order_id": order.order_id, "order_status": order.status,
                       "order_date": order.order_date.date().isoformat(), "last_updated": order.last_updated.isoformat()},
        llm_facts={"order_status": order.status, "order_id": "{order_id}", "order_date": "{order_date}",
                   "last_updated": "{last_updated}"})


ON_THE_WAY = ("Shipped", "Out for Delivery")     # the statuses that mean "on its way to the customer"
MAX_LISTED = 5
# TODO(owner): the wording of this list is a DRAFT. Only placeholders for real values (D60-A1): the
#   code fills them in, the model never sees them. No delivery time is promised.
_ON_THE_WAY_TEXT = {
    "ar": ("عندك {count} طلبات في الطريق:\n{lines}\n\nلو قصدك طلب تاني اكتب رقمه.",
           "- {{o{i}_product}}: {{o{i}_status}}، آخر تحديث {{o{i}_updated}} ({{o{i}_id}})"),
    "en": ("You have {count} orders on the way:\n{lines}\n\nIf you meant a different order, send its number.",
           "- {{o{i}_product}}: {{o{i}_status}}, last updated {{o{i}_updated}} ({{o{i}_id}})"),
}


def _summary_values(order) -> tuple[dict[str, str], dict[str, str]]:
    """Template 1 values from an order summary: the same keys the order_status builder gives."""
    render = {"order_id": order.order_id, "order_status": order.status,
              "order_date": order.order_date.date().isoformat(), "last_updated": order.last_updated.isoformat()}
    facts = {"order_status": order.status, "order_id": "{order_id}", "order_date": "{order_date}",
             "last_updated": "{last_updated}"}
    return render, facts


@builder("orders_on_the_way")
def orders_on_the_way(env: StepEnv) -> Built | None:
    """C1 with no order number and no item clue, from the recent-orders list alone (no order_details call):
    one order on the way -> its status; several -> a short list with no question (a typed "2" is not understood yet,
    there is no memory); none on the way -> the only recent order if there is exactly one, else ask for the number."""
    recent = [o for o in _recent_orders(env) if isinstance(o, OrderSummaryView)]
    active = [o for o in recent if o.status in ON_THE_WAY]
    if len(active) == 1:
        return Built(*_summary_values(active[0]))
    if not active:
        if len(recent) == 1:
            return Built(*_summary_values(recent[0]))
        raise NeedsClarification("missing_order_id")
    from .clarify import LanguageDetector                    # here, not at the top: keeps the import graph light
    language = LanguageDetector().detect(env.ctx.message)
    shown = active[:MAX_LISTED]
    head, line = _ON_THE_WAY_TEXT[language]
    values = {"count": str(len(active))}
    for i, o in enumerate(shown, 1):
        values.update({f"o{i}_id": o.order_id, f"o{i}_product": ", ".join(o.product_names[:2]) or o.order_id,
                       f"o{i}_status": o.status, f"o{i}_updated": o.last_updated.isoformat()})
    text = head.format(count="{count}", lines="\n".join(line.format(i=i) for i in range(1, len(shown) + 1)))
    raise ReadyOutcome(PartOutcome(kind="chat", text=text, render_values=values))


@selector("only_delivered_order")
def only_delivered_order(env: StepEnv) -> str | None:
    """For a return: the only DELIVERED order among the recent ones (None when there are none or several: the user chooses)."""
    delivered = [o for o in _recent_orders(env) if isinstance(o, OrderSummaryView) and o.status == "Delivered"]
    return delivered[0].order_id if len(delivered) == 1 else None


def _eligibility_answer(env: StepEnv, rules, check, extra: dict[str, str]) -> Built | None:
    """The shared body of the return and the exchange answers. ⑤ (app/rules/) decides from the validated order. Every item of the
    order gets its own line (no question to answer in a dead end), or only the item the user named. Code-chosen words, typed
    placeholders (the real values only in render_values), the policy sections cited; a verdict that needs a person hands off."""
    from .clarify import LanguageDetector
    views = _order_views(env)
    if not views:
        return None
    order = views[0]
    clue = env.intent.arguments.get("item_clue")
    verdict = check(order, clue if isinstance(clue, str) else None)
    language = LanguageDetector().detect(env.ctx.message)
    values = {"order_id": order.order_id, "order_status": order.status, **extra}
    if verdict.kind == "items":
        values["delivered_date"] = verdict.delivered_date.isoformat()
        lines = []
        for n, v in enumerate(verdict.items[:MAX_LISTED], 1):
            values[f"i{n}_name"] = v.name
            if v.last_day:
                values[f"i{n}_end_date"] = v.last_day.isoformat()
            if v.second_day:
                values[f"i{n}_{rules.SECOND_KEY}_date"] = v.second_day.isoformat()
            lines.append(rules.line_for(v, language).format(i=n))
        parts = [rules.HEADER["items"][language], "\n".join(lines)]
        if getattr(rules, "mentions_conditions", lambda _v: False)(verdict):
            parts.append(rules.CONDITIONS[language])
        text = "\n\n".join(parts + [rules.FOOTER[language]])
    else:
        key = "review_date" if verdict.reason == "delivered_without_date" else verdict.kind
        text = rules.HEADER[key][language]
    handoff = {"handoff_reason": "PENDING_OWNER"} if rules.needs_person(verdict) else {}
    raise ReadyOutcome(PartOutcome(kind="chat", text=text, render_values=values, cited=verdict.cited, **handoff))


@builder("return_eligibility")
def return_eligibility(env: StepEnv) -> Built | None:
    """C2: can this item be returned? POL-RET-001 (app/rules/returns.py)."""
    from ..rules import returns as rules
    return _eligibility_answer(env, rules, rules.check_return, {"electronics_days": str(rules.ELECTRONICS_DAYS)})


@builder("exchange_eligibility")
def exchange_eligibility(env: StepEnv) -> Built | None:
    """C5: can this item be exchanged? POL-EXC-001 (app/rules/exchange.py). An exchange is not a return, and the answer says so."""
    from ..rules import exchange as rules
    return _eligibility_answer(env, rules, rules.check_exchange, {"waiting_days": str(rules.WAITING_LIST_DAYS)})


@builder("cancellation")
def cancellation(env: StepEnv) -> Built | None:
    """C9: can this order be cancelled? ⑤ (app/rules/cancellation.py) decides from the validated order; the words are code-chosen
    (D66 style): a typed verdict, placeholders for the values, the policy section cited. A review verdict also hands off."""
    from ..rules import cancellation as rules
    from .clarify import LanguageDetector
    views = _order_views(env)
    if not views:
        return None
    order = views[0]
    verdict = rules.check_cancellation(order)
    language = LanguageDetector().detect(env.ctx.message)
    text = rules.TEXTS[(rules.text_key(verdict), language)]
    values = {"order_id": order.order_id, "order_status": order.status, "window_hours": str(rules.PROCESSING_WINDOW_HOURS)}
    handoff = {"handoff_reason": "PENDING_OWNER"} if verdict.kind == "review" else {}
    raise ReadyOutcome(PartOutcome(kind="chat", text=text, render_values=values, cited=[verdict.cited], **handoff))


@builder("return_status")
def return_status(env: StepEnv) -> Built | None:
    """The return the user means: the one with the given return id, or the only return there is."""
    wanted = env.intent.arguments.get("return_id")
    rows: list[BackendReturn | BackendReturnRow] = [r for view in _order_views(env) for r in view.returns]
    listed = _ok_data(env.results.get("returns"))                  # the customer's own list (C3 without an order reference)
    if isinstance(listed, list):
        rows += [r for r in listed if isinstance(r, BackendReturnRow)]
    found = [r for r in rows if not isinstance(wanted, str) or r.return_id.casefold() == wanted.casefold()]
    if not found:
        return None
    if len(found) > 1:
        raise NeedsClarification("which_return")
    r = found[0]
    return Built(
        render_values={"return_id": r.return_id, "return_status": r.status,
                       "last_updated": r.last_updated.isoformat(), "item": r.item or ""},
        llm_facts={"return_status": r.status, "return_id": "{return_id}", "last_updated": "{last_updated}",
                   "item": r.item or ""})


@builder("today_shipments")
def today_shipments(env: StepEnv) -> Built | None:
    view = _ok_data(env.results.get("today"))
    if not isinstance(view, TodayView):
        return None
    rows = "\n".join("; ".join(f"{k}: {v}" for k, v in row.items() if v is not None) for row in view.rows)
    return Built(
        render_values={"query": view.query, "date": view.date.isoformat(), "count": str(view.count), "rows_text": rows},
        llm_facts={"query": view.query, "date": "{date}", "count": "{count}", "rows_text": "{rows_text}"})


@builder("policy_sections")
def policy_sections(env: StepEnv) -> Built | None:
    """The retrieved policy sections for the reply (at most MAX_SECTIONS, D94). None when retrieval found nothing:
    the policy is silent, which is an answer of its own (template 12 and a POL handoff), never a guess."""
    chunks = _ok_data(env.results.get("policy"))
    if not isinstance(chunks, list):
        return None
    sections = tuple(Section(cited=c["cited"], text=c["text"]) for c in chunks[:MAX_SECTIONS]
                     if isinstance(c, dict) and c.get("cited") and c.get("text"))
    return Built(render_values={}, llm_facts={}, sections=sections) if sections else None
