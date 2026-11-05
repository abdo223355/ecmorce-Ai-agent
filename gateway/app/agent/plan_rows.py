"""The plan table: one row per intent (slice 1 tools: C1, C3, W1, W2, W3; slice 2 handoff-only: C6, C7, C10, C12,
W4, W5, W9, plus C8 and C13). Adding an intent is adding a row.

Each row says what an intent does (A6/A7). Notes for review:
  - Check every branch: which arguments must be present, and what happens when they are missing.
  - C1 with no order number and no clue succeeds only when the customer has exactly one order; with more it asks
    "which order". This is a design decision and can be changed.
  - W3 always asks for scheduled_delivery_date next to the status, and the status is always present in the view.
  - Template numbers come from D68 (1 order status, 2 return status, 3 worker shipments, 14 not found, 11 unavailable).
"""
from __future__ import annotations

from . import plan_registry  # noqa: F401  (registers the selectors and builders the rows refer to)
from .plan_spec import (Branch, Const, FanOutStep, FromArg, FromCtx, FromEnv, FromRef, FromResult, PlanSpec,
                        ToolStep, args)
from .state import PartOutcome

_RECENT = ToolStep("recent", "my_recent_orders")

ROWS: tuple[PlanSpec, ...] = (
    # C1 order status: with a reference, straight to the order; else find it by a clue; else the only order.
    PlanSpec("customer", "C1",
             branches=(
                 Branch(("order_ref",), (ToolStep("order", "order_details", args(order_id=FromRef("order_ref"))),)),
                 Branch(("item_clue",), (_RECENT, ToolStep("order", "order_details",
                                                           args(order_id=FromResult("match_item_clue"))))),
                 # No number, no clue: look at the recent list alone. One order on the way -> its status, several -> a
                 # short list (no question: a typed "2" is not understood yet), none -> the only order, else ask.
                 Branch((), (_RECENT,), builder="orders_on_the_way"),
             ),
             builder="order_status", template_id=1, not_found_template=14),

    # C3 return status: with an order reference, that order; else the customer's own list of returns (one call, newest
    # first), so an old return is found even when the newest orders have none (night 123).
    PlanSpec("customer", "C3",
             branches=(
                 Branch(("order_ref",), (ToolStep("order", "order_details", args(order_id=FromRef("order_ref"))),)),
                 Branch((), (ToolStep("returns", "my_returns"),)),
             ),
             builder="return_status", template_id=2, not_found_template=14),

    # W1 today's shipments: the query type classify found, else the plain list.
    PlanSpec("worker", "W1",
             branches=(Branch((), (ToolStep("today", "my_shipments_today",
                                            args(query=FromArg("query_type", default="list"))),)),),
             builder="today_shipments", template_id=3),

    # W2 shipment details: the fields classify found. No template for this: the data goes to the reply.
    PlanSpec("worker", "W2",
             branches=(Branch(("shipment_id",), (ToolStep("shipment", "shipment_details",
                                                          args(shipment_id=FromArg("shipment_id"),
                                                               requested_fields=FromArg("requested_fields",
                                                                                        default=()))),)),)),

    # C2 return eligibility (POL-RET-001): the order from a reference, a product clue, or the only DELIVERED order; with several
    # delivered orders the agent asks which one (only delivered orders are listed). ⑤ decides, the words are code-chosen.
    PlanSpec("customer", "C2",
             branches=(
                 Branch(("order_ref",), (ToolStep("order", "order_details", args(order_id=FromRef("order_ref"))),)),
                 Branch(("item_clue",), (_RECENT, ToolStep("order", "order_details",
                                                           args(order_id=FromResult("match_item_clue"))))),
                 Branch((), (_RECENT, ToolStep("order", "order_details", args(order_id=FromResult("only_delivered_order"))))),
             ),
             builder="return_eligibility", not_found_template=14),

    # C5 exchange eligibility (POL-EXC-001): like C2 (a reference, a product clue, or the only DELIVERED order, else which order).
    PlanSpec("customer", "C5",
             branches=(
                 Branch(("order_ref",), (ToolStep("order", "order_details", args(order_id=FromRef("order_ref"))),)),
                 Branch(("item_clue",), (_RECENT, ToolStep("order", "order_details",
                                                           args(order_id=FromResult("match_item_clue"))))),
                 Branch((), (_RECENT, ToolStep("order", "order_details", args(order_id=FromResult("only_delivered_order"))))),
             ),
             builder="exchange_eligibility", not_found_template=14),

    # C9 cancellation eligibility (POL-CAN-001): the order comes from a reference, a product clue, or the only order; with several
    # orders the agent asks which one (the answer "2" is understood, see memory). ⑤ decides, the words are code-chosen.
    PlanSpec("customer", "C9",
             branches=(
                 Branch(("order_ref",), (ToolStep("order", "order_details", args(order_id=FromRef("order_ref"))),)),
                 Branch(("item_clue",), (_RECENT, ToolStep("order", "order_details",
                                                           args(order_id=FromResult("match_item_clue"))))),
                 Branch((), (_RECENT, ToolStep("order", "order_details", args(order_id=FromResult("only_order"))))),
             ),
             builder="cancellation", not_found_template=14),

    # W3 shipment status or scheduled date: the status is always in the view; the date is a field.
    PlanSpec("worker", "W3",
             branches=(Branch(("shipment_id",), (ToolStep("shipment", "shipment_details",
                                                          args(shipment_id=FromArg("shipment_id"),
                                                               requested_fields=Const(("scheduled_delivery_date",)))),)),)),
)

# ---- slice 2: handoff-only intents. No tool is called; the row holds the answer. ----
# Priority None means the owner's question is still open (D70); a priority is never invented.
#   - C12: never argue and never compute eligibility (POL-SPC-001 section 6); it is not P1.
#   - W4: template 16 (not your shipment) vs 17 (field not allowed); the choice should be reviewed.
#   - W9 and template 9 are an interpretation (the generic version of D31) and need the owner's confirmation.
_ACK_CUSTOMER = 5     # D68 5: handoff acknowledgement, customer (no reply time promised for PENDING_OWNER)
_ACK_WORKER = 6       # D68 6: handoff acknowledgement, worker

HANDOFF_ROWS: tuple[PlanSpec, ...] = (
    PlanSpec("customer", "C6", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=_ACK_CUSTOMER, handoff_reason="PENDING_OWNER")),)),
    # C7 is stopped by the safety gate before the plan runs; this row is the backup if the plan is ever called alone.
    PlanSpec("customer", "C7", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=8, handoff_reason="SAFE", priority="P1")),)),
    PlanSpec("customer", "C10", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=_ACK_CUSTOMER, handoff_reason="CMP")),)),
    PlanSpec("customer", "C12", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=_ACK_CUSTOMER, handoff_reason="PENDING_OWNER")),)),
    # C8 action outside V1: template 10 explains what V1 can do, and SCOPE / P4 is mandatory (POL-AGE-001 §2).
    PlanSpec("customer", "C8", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=10, handoff_reason="SCOPE", priority="P4")),)),
    # C13 topic outside scope: a neutral reply, no handoff (D31). Template 9 is our reading of D68 (interpretation).
    PlanSpec("customer", "C13", branches=(Branch((), outcome=PartOutcome(kind="template", template_id=9)),)),
    # W4: a neutral denial, no handoff (D35). Asked for fields -> 17; named a shipment -> 16; else 17.
    PlanSpec("worker", "W4", branches=(
        Branch(("requested_fields",), outcome=PartOutcome(kind="template", template_id=17)),
        Branch(("shipment_id",), outcome=PartOutcome(kind="template", template_id=16)),
        Branch((), outcome=PartOutcome(kind="template", template_id=17)),
    )),
    # W5: the handoff to Dispatch needs the ticket routing field (go-live blocker 8), not built.
    PlanSpec("worker", "W5", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=_ACK_WORKER, handoff_reason="PENDING_OWNER")),)),
    # Eligibility (C2 return, C5 exchange, C9 cancel) is decided by CODE (check_eligibility, infrastructure 5), which is not built
    # yet. Until it exists the agent does not guess a yes or a no: an honest handoff to a person (PENDING_OWNER, no priority).
    # (Superseded: C2, C5 and C9 now use a tool step plus a builder; see the rows above.)
    # C11 missing order: no tool can find an order that is not in the customer's list, so a person looks into it.
    PlanSpec("customer", "C11", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=_ACK_CUSTOMER, handoff_reason="PENDING_OWNER")),)),
    # W6 delivery issue and W7 shipment issue (damage, missing, mismatch): Dispatch decides, same routing gap as W5.
    PlanSpec("worker", "W6", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=_ACK_WORKER, handoff_reason="PENDING_OWNER")),)),
    PlanSpec("worker", "W7", branches=(Branch((), outcome=PartOutcome(
        kind="template", template_id=_ACK_WORKER, handoff_reason="PENDING_OWNER")),)),
    # W9: a neutral reply, no handoff. Template 9 is our reading of "the worker version of D31" (interpretation).
    PlanSpec("worker", "W9", branches=(Branch((), outcome=PartOutcome(kind="template", template_id=9)),)),
)

# ---- slice 3: intents answered from the policy documents (RAG). The query is the scrubbed message itself (the text
# the early embedding already used) plus classify's English query. Hits go to the reply with their citations; no hits
# means the policy is silent: template 12 and a POL handoff (POL-AIS-001 §3), never an answer from nothing.
# Open points for the owner:
#   - The priority of the POL handoff for C4 and W8 is not stated in the design (None here); only C14 is P3.
#   - Template 12 for workers is an interpretation (the generic "policy not confirmed" wording).
#   - C14 rests on POL-ACC-001, which is UNVERIFIED until corpus documents 04 to 10 are added.
def _search(tool: str) -> ToolStep:
    return ToolStep("policy", tool, args(query=FromCtx("message"), english_query=FromEnv("english_query", default="")))


_POLICY_SILENT = PartOutcome(kind="template", template_id=12, handoff_reason="POL")
_POLICY_SILENT_P3 = PartOutcome(kind="template", template_id=12, handoff_reason="POL", priority="P3")

RAG_ROWS: tuple[PlanSpec, ...] = (
    PlanSpec("customer", "C4", branches=(Branch((), (_search("policy_search"),)),),
             builder="policy_sections", not_found_outcome=_POLICY_SILENT),
    PlanSpec("worker", "W8", branches=(Branch((), (_search("procedure_search"),)),),
             builder="policy_sections", not_found_outcome=_POLICY_SILENT),
    PlanSpec("customer", "C14", branches=(Branch((), (_search("policy_search"),)),),
             builder="policy_sections", not_found_outcome=_POLICY_SILENT_P3),
)

PLANS: dict[str, dict[str, PlanSpec]] = {"customer": {}, "worker": {}}
for _row in ROWS + HANDOFF_ROWS + RAG_ROWS:
    PLANS[_row.role][_row.intent_id] = _row
