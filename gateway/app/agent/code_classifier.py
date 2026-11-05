"""Code fast path for classify: a short, plain message is classified by code and the LLM is not called.

The rules (decided with the project owner, docs/PROGRESS.md night 35 to 39):
1. The code path decides only four intents: C1 order status, C3 return status, C6 talk to a human (customer),
   W1 today's shipments (worker). Everything else goes to the LLM.
2. The WHOLE message must match one pattern from start to end. Extra words, no match, or two matching intents
   all mean "not simple": the LLM decides. Because the match is anchored and the patterns are tiny, a message
   with a danger word or a second request cannot match, so the P1 / escalation words always reach the LLM.
3. A reference in the message ({order_ref_1}) must exist in the per-request map, else the LLM decides.
4. A match gives a SAFE part with needs_explanation False and no english_query: the fast path (D73).

This class never decides safety P1 and never raises: anything unexpected is "no match".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import AgentContext
from .state import Intent, Part

# One optional order reference as the ingress writes it: {order_ref_1} (the braces are optional here).
_REF = r"(?P<ref>\{?order_ref_\d+\}?)"


@dataclass(frozen=True)
class PatternRule:
    intent_id: str
    role: str
    regexes: tuple[re.Pattern, ...]

    def match(self, text: str) -> re.Match | None:
        for regex in self.regexes:
            if m := regex.fullmatch(text):
                return m
        return None


def _rule(intent_id: str, role: str, *alternatives: str) -> PatternRule:
    # One compiled regex per wording, so each may use the named group "ref" on its own.
    return PatternRule(intent_id, role, tuple(re.compile(a, re.IGNORECASE) for a in alternatives))


# The code-path patterns (A5). This is a small starting set that can be extended.
#   - Each pattern must match the WHOLE message (no extra words), so write the common phrasings exactly.
#   - Add Arabic and Franco-Arabic (Arabizi) wordings per intent, and test each pattern on real messages from the L1 set.
#   - Never put a safety or complaint word inside a pattern (hacking, theft, complaint): those messages must reach the LLM.
#   - Use _REF when the pattern accepts an order number; leave it out otherwise.
RULES: tuple[PatternRule, ...] = (
    _rule("C1", "customer",
          rf"(?:where is|track|status of) (?:my )?order(?: {_REF})?",
          rf"order status(?: {_REF})?",
          rf"فين (?:ال)?طلبي(?: {_REF})?",
          rf"حالة (?:ال)?طلب(?: {_REF})?",
          rf"(?:feen|fein) (?:el)?talabi(?: {_REF})?"),
    _rule("C3", "customer",
          r"(?:return status|status of my return)",
          r"حالة (?:ال)?مرتجع",
          r"(?:7alet|halet) (?:el)?mortaga3"),
    _rule("C6", "customer",
          r"(?:i want to |can i |let me )?(?:talk|speak) to (?:a )?(?:human|agent|person)",
          r"(?:عايز|عاوز|اريد|أريد|ممكن) (?:اكلم|أكلم|اتكلم مع|أتكلم مع) (?:موظف|حد|شخص)",
          r"كلمني (?:موظف|حد)",
          r"3ayez (?:akalem|akallem) (?:mowazaf|hadd)"),
    _rule("W1", "worker",
          r"(?:my )?shipments(?: today)?",
          r"what (?:shipments )?do i have today",
          r"شحناتي(?: النهارده| النهاردة| اليوم)?",
          r"(?:eh|ايه) شحناتي(?: النهارده)?",
          r"shahnati(?: el ?nharda)?"),
)

_PUNCT = re.compile(r"[\s.!?؟,،;:]+")
_EDGE = re.compile(r"^[\s.!?؟,،;:]+|[\s.!?؟,،;:]+$")


class CodeClassifier:
    def __init__(self, rules: tuple[PatternRule, ...] = RULES):
        self._rules = rules

    @staticmethod
    def normalize(message: str) -> str:
        """Lower-case, drop light punctuation at the edges, collapse spaces. Nothing else is changed."""
        return _PUNCT.sub(" ", _EDGE.sub("", message.casefold())).strip()

    def classify(self, ctx: AgentContext) -> list[Part] | None:
        """One SAFE part for a message that matches exactly one rule of the role, else None (the LLM decides)."""
        text = self.normalize(ctx.message)
        hits = [(rule, m) for rule in self._rules if rule.role == ctx.role and (m := rule.match(text))]
        if len(hits) != 1:                                    # no match, or two intents: not simple
            return None
        rule, m = hits[0]
        arguments: dict[str, str | list[str]] = {}
        ref = m.groupdict().get("ref")
        if ref:
            key = ref.strip("{}")
            if key not in ctx.order_refs:                     # rule 3: a reference must exist in the map
                return None
            arguments["order_ref"] = key
        return [Part(index=0, safety="SAFE", intent=Intent(id=rule.intent_id, arguments=arguments),
                     needs_explanation=False)]
