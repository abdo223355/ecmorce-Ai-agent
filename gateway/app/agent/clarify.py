"""Node 6: clarify. Code only: no tool, no model. When the plan could not go on, ask the user ONE question.

It reads three things and nothing else: each part's outcome (the plan marked some parts kind "clarify" with a reason),
the tool_results the plan already fetched (for the list the user chooses from), and the context (the message for the
language, the role, and clarify_round). It never calls a tool: every backend call happens in the plan.

Decisions taken with him (nights 81, 83, 84):
- the question is in Arabic by default (Franco/Arabizi counts as Arabic); English only for a message with no Arabic
  letter and plain English words;
- the list holds at most 5 choices, newest first (the same 5 the plan looked at);
- one question per turn: the earliest part that needs one is asked, the others wait ("then I will ask about the rest");
- after 3 rounds with no result the node stops asking and the part becomes a handoff PENDING_OWNER (priority None until
  the owner answers, D70); node 5 then adds the acknowledgement and the summary.

The question text holds placeholders only ({choices_text}); the real labels sit in render_values and code renders them.
Never raises, never changes the state it reads, no message text in the log (D108).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from ..schemas import BackendReturnRow, OrderSummaryView, OrderView
from . import AgentContext
from . import pending as pend
from .state import AgentState, Part, PartOutcome, ToolRecord

log = logging.getLogger("gateway.agent.clarify")

MAX_ROUNDS = 3        # after this many rounds the node hands off instead of asking again
DELIVERED_ONLY_INTENTS = frozenset({"C2", "C5"})   # a return or an exchange is only possible for a delivered order
MAX_CHOICES = 5       # the list shown to the user, same as the plan's fan-out (backend returns newest first)


# ---------- the choices the user picks from ----------
@dataclass(frozen=True)
class Choice:
    label: str                       # what the user sees, e.g. "Silver Watch · 2026-10-18"
    ref: str                         # the real id behind it; stays in code (the memory card will keep it, D61)


class ChoiceSource(Protocol):
    def build(self, records: list[ToolRecord]) -> tuple[Choice, ...]: ...


class RecentOrdersChoices:
    """The user's recent orders, from the my_recent_orders result the plan already fetched."""

    def build(self, records: list[ToolRecord]) -> tuple[Choice, ...]:
        for r in records:
            if r.tool == "my_recent_orders" and r.result.ok and isinstance(r.result.data, list):
                return tuple(Choice(f"{', '.join(o.product_names[:2])} · {o.order_date.date().isoformat()}", o.order_id)
                             for o in r.result.data[:MAX_CHOICES] if isinstance(o, OrderSummaryView))
        return ()


def _delivered_only(records: list[ToolRecord]) -> tuple[Choice, ...]:
    """The recent DELIVERED orders, for a question about a return or an exchange (nothing else can be returned)."""
    for r in records:
        if r.tool == "my_recent_orders" and r.result.ok and isinstance(r.result.data, list):
            delivered = [o for o in r.result.data if isinstance(o, OrderSummaryView) and o.status == "Delivered"]
            return tuple(Choice(f"{', '.join(o.product_names[:2])} · {o.order_date.date().isoformat()}", o.order_id)
                         for o in delivered[:MAX_CHOICES])
    return ()


class ReturnChoices:
    """The user's returns, from the results the plan already fetched: the my_returns list, or the returns inside order_details."""

    def build(self, records: list[ToolRecord]) -> tuple[Choice, ...]:
        seen: dict[str, Choice] = {}
        for r in records:
            if r.tool == "my_returns" and r.result.ok and isinstance(r.result.data, list):
                for ret in r.result.data:
                    if isinstance(ret, BackendReturnRow):
                        seen.setdefault(ret.return_id, Choice(f"{ret.item or 'Return'} · {ret.created_at.date().isoformat()}",
                                                              ret.return_id))
            if r.tool == "order_details" and r.result.ok and isinstance(r.result.data, OrderView):
                for ret in r.result.data.returns:
                    seen.setdefault(ret.return_id, Choice(f"{ret.item or 'Return'} · {ret.created_at.date().isoformat()}",
                                                          ret.return_id))
        return tuple(seen.values())[:MAX_CHOICES]


CHOICE_SOURCES: dict[str, ChoiceSource] = {"missing_order_id": RecentOrdersChoices(), "which_return": ReturnChoices()}


# ---------- the language ----------
class LanguageDetector:
    """'en' only for a message with no Arabic letter, no Franco marker and at least one plain English word."""

    ENGLISH = frozenset("where what my the is order orders return status shipment shipments why how can i want to a of for "
                        "and please track human talk today late when did it was are you me".split())
    FRANCO = frozenset("feen fein talab talabi 3ayez 3ayz ayez ana el mortaga3 mortaga 7alet halet shahnati ezay eh leh "
                       "lesa ya fi men ma3a".split())
    _ARABIC = re.compile(r"[؀-ۿ]")

    def detect(self, message: str) -> str:
        if self._ARABIC.search(message):
            return "ar"
        words = re.findall(r"[a-z0-9']+", message.casefold())
        if any(w in self.FRANCO for w in words):
            return "ar"                                           # Franco is treated as Arabic (his decision)
        return "en" if any(w in self.ENGLISH for w in words) else "ar"


# ---------- the wording ----------
class QuestionBook:
    """The question texts: (reason, language, with a list or not) -> text. Drafts: he and Customer Operations review them."""

    TEXTS: dict[tuple[str, str, bool], str] = {
        ("missing_order_id", "ar", True): "أنهي طلب تقصد؟\n{choices_text}\nاكتب رقم الطلب أو اسم المنتج.",
        ("missing_order_id", "ar", False): "ممكن تكتب رقم الطلب أو اسم المنتج؟",
        ("missing_order_id", "en", True): "Which order do you mean?\n{choices_text}\nSend the order number or the product name.",
        ("missing_order_id", "en", False): "Could you send the order number or the product name?",
        ("which_return", "ar", True): "عندك أكتر من مرتجع، أنهي واحد؟\n{choices_text}",
        ("which_return", "ar", False): "ممكن تكتب رقم المرتجع؟",
        ("which_return", "en", True): "You have more than one return. Which one?\n{choices_text}",
        ("which_return", "en", False): "Could you send the return number?",
        ("missing_shipment_id", "ar", False): "ممكن تكتب رقم الشحنة؟",
        ("missing_shipment_id", "en", False): "Could you send the shipment number?",
        ("invalid_format", "ar", False): "الرقم اللي كتبته مش بالشكل الصح. اكتبه تاني من فضلك.",
        ("invalid_format", "en", False): "That number is not in the right format. Please send it again.",
        ("nothing_found", "ar", False): "مش لاقي حاجة مطابقة. ممكن توضح أكتر؟",
        ("nothing_found", "en", False): "I could not find a match. Could you tell me more?",
        ("generic", "ar", False): "ممكن توضّح طلبك أكتر؟",
        ("generic", "en", False): "Could you tell me a bit more about what you need?",
    }
    MORE = {"ar": "\nوبعدها هسألك عن باقي طلباتك.", "en": "\nThen I will ask about the rest."}

    def text(self, reason: str | None, language: str, has_choices: bool) -> str:
        for key in ((reason, language, has_choices), (reason, language, False)):
            if key in self.TEXTS:
                return self.TEXTS[key]
        return self.TEXTS[("generic", language, False)]            # an unknown reason must never break the node


# ---------- the decision ----------
@dataclass(frozen=True)
class ClarifyDecision:
    handoff: bool
    part: Part | None = None                                       # the part to ask about (None when handing off)


class ClarifyPlanner:
    """Decides what to do. It writes no words: the round limit and the one-question rule live here only."""

    @staticmethod
    def decide(asks: list[Part], clarify_round: int) -> ClarifyDecision:
        if clarify_round >= MAX_ROUNDS:
            return ClarifyDecision(handoff=True)
        return ClarifyDecision(handoff=False, part=min(asks, key=lambda p: p.index))


DETECTOR = LanguageDetector()
QUESTION_BOOK = QuestionBook()


def _round_of(ctx: AgentContext, part: Part) -> int:
    """How many times THIS question was already asked: from the card of the previous turn when it is the same question,
    else from the context (0 until the Gateway says otherwise)."""
    card = ctx.pending
    if card and part.intent is not None and card.get("intent") == part.intent.id and card.get("reason") == part.outcome.reason:
        return int(card.get("round", 0))
    return ctx.clarify_round


def _numbered(choices: tuple[Choice, ...]) -> str:
    return "\n".join(f"{i}) {c.label}" for i, c in enumerate(choices, start=1))


def clarify_node(state: AgentState, ctx: AgentContext, *, book: QuestionBook = QUESTION_BOOK,
                 detector: LanguageDetector = DETECTOR,
                 sources: dict[str, ChoiceSource] = CHOICE_SOURCES) -> dict:
    asks = [p for p in state.parts if p.outcome is not None and p.outcome.kind == "clarify"]
    if not asks:
        return {}                                                   # nothing to clarify: the node adds nothing
    first = min(asks, key=lambda p: p.index)                        # the part ClarifyPlanner will ask about
    round_ = _round_of(ctx, first)
    decision = ClarifyPlanner.decide(asks, round_)
    if decision.handoff:                                            # the third round ended without a result
        handed = PartOutcome(kind="handoff", handoff_reason="PENDING_OWNER", reason="clarify_limit")
        log.info(json.dumps({"node": "clarify", "decision": "handoff", "round": round_}))
        return {"parts": [p.model_copy(update={"outcome": handed}) if p in asks else p for p in state.parts]}

    part = decision.part
    reason = part.outcome.reason
    source = sources.get(reason or "")
    if source is None:
        choices = ()
    elif isinstance(source, RecentOrdersChoices) and part.intent is not None and part.intent.id in DELIVERED_ONLY_INTENTS:
        choices = _delivered_only(state.tool_results)
    else:
        choices = source.build(state.tool_results)
    language = detector.detect(ctx.message)
    text = book.text(reason, language, bool(choices))
    if len(asks) > 1:
        text += book.MORE[language]                                 # one question now, the rest after
    values = {"choices_text": _numbered(choices)} if choices else {}
    asked = part.outcome.model_copy(update={"text": text, "render_values": values})
    log.info(json.dumps({"node": "clarify", "decision": "ask", "reason": reason, "language": language,
                         "choices": len(choices), "deferred": len(asks) - 1, "round": round_}))
    update = {"parts": [p.model_copy(update={"outcome": asked}) if p is part else p for p in state.parts],
              "clarify_question": text}
    if choices and reason in pend.RESOLVABLE and part.intent is not None:
        # A list was shown: leave a card so the user's "2" in the next turn is understood (kept by the Gateway, D61).
        update["pending"] = pend.card_from(part.intent.id, reason, round_ + 1,
                                           [{"label": c.label, "ref": c.ref} for c in choices])
    return update
