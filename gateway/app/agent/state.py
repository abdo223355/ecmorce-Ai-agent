"""The state the agent's nodes fill in while one request runs.

Only the dynamic fields live here. What is fixed before the agent starts (role, message, chat id, deadline,
order refs) is in AgentContext, which nodes read but cannot change. The rule for the split: if no node writes
a field during the request, it belongs in the context, not here.

The state never holds the token or any credential, a denial counter, or raw backend data.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..tools import ToolResult
from . import AgentResult

# The only two verdicts a part can get. P1 sends the request down the P1 path; SAFE means no danger found.
Safety = Literal["SAFE", "P1"]

# What kind of P1 a part is (his decision, night 70; the design does not name them).
# takeover (account takeover) and exposure (data exposure) block the session's data (CP-44); danger (physical danger)
# gets the emergency line and the SAFE handoff without blocking data (N1). A P1 with no flag is treated as the
# stricter case.
P1Flag = Literal["takeover", "exposure", "danger"]
NO_DATA_FLAGS = frozenset({"takeover", "exposure"})

# Priority scale fixed by the design.
Priority = Literal["P1", "P2", "P3", "P4"]

# The seven handoff reason codes, plus PENDING_OWNER, which the design allows as an interim code.
HandoffReason = Literal["BKD", "POL", "AUTH", "INFO", "SCOPE", "SAFE", "CMP", "PENDING_OWNER"]


class Intent(BaseModel):
    """What the user wants in one part of the message. The id is always there."""

    id: str                                                  # e.g. "C2"
    # argument name -> value, e.g. {"order_ref": "order_ref_1"}; a list for fields like requested_fields
    arguments: dict[str, str | list[str]] = Field(default_factory=dict)


class Section(BaseModel):
    """One retrieved policy section the reply may use. The citation is kept apart from the text so code can check
    and count it (D66 check 2) without reading it back out of the model's words."""

    model_config = ConfigDict(frozen=True)

    cited: str                                                   # "doc_id §section@version", e.g. "POL-RET-001 §2@2.1"
    text: str                                                    # the section itself (policy text, not personal data)


class PartOutcome(BaseModel):
    """What the plan decided for one part. A template and a handoff can go together (template 11 + BKD/P3)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["template", "reply", "clarify", "handoff", "chat"]
    # kind "template": the template to render. kind "reply": the FALLBACK template if the reply fails (None if none).
    # kind "chat": small talk (agent/chat.py): `text` holds the finished words, no template, no tool, no model.
    template_id: int | None = Field(default=None, ge=1, le=19)
    # kind "reply" after the reply node ran: the words for this part, with typed placeholders like {order_id}.
    text: str | None = None
    # Real values, rendered by code into the template or the final reply. NEVER shown to the LLM (D60-A1).
    render_values: dict[str, str] = Field(default_factory=dict)
    # What the reply LLM may see: non-personal facts, and typed placeholder names ("{customer_phone}") for every
    # personal value, number and date. Empty unless a builder fills it on purpose.
    llm_facts: dict[str, str] = Field(default_factory=dict)
    # Policy sections the reply may use (at most 8 per request, D94). Kept after the reply for the D66 validator.
    sections: list[Section] = Field(default_factory=list)
    # Sections the reply says it used, checked by code against `sections`. Becomes Segment.cited.
    cited: list[str] = Field(default_factory=list)
    reason: str | None = None                                   # clarify reason, e.g. "missing_order_id"
    handoff_reason: HandoffReason | None = None
    priority: Priority | None = None


class Part(BaseModel):
    """One part of the user's message. Classify judges safety and escalation for every part, but only parts it
    recognised carry an intent, so a dangerous part with no known intent is still stored and still seen."""

    index: int
    safety: Safety                                           # required: classify judges every part
    escalation_flags: list[str] = Field(default_factory=list)
    p1_flag: P1Flag | None = None                            # which kind of P1, when classify says so
    intent: Intent | None = None                             # None when no known intent matched this part
    # Whether this part needs the reply LLM (a "why" or policy question). True is the safe default: if classify
    # forgets to set it, the part goes to the reply LLM and never takes the template fast path.
    needs_explanation: bool = True
    outcome: PartOutcome | None = None                       # written by the plan; None until it has run


class PartSummary(BaseModel):
    """What the human learns about one part. Labels and outcomes only: no user text, no real values."""

    model_config = ConfigDict(frozen=True)

    part_index: int
    intent: str | None                                       # the intent id, e.g. "C2"
    label: str | None                                        # the catalog label, e.g. "Return eligibility"
    outcome: str                                             # a fixed word, e.g. "answered", "information_unavailable"
    clue: str | None = None                                  # a product clue only (D61), checked to be short and plain
    p1_flag: P1Flag | None = None


class HandoffSummary(BaseModel):
    """The neutral summary for the human, built by code from the parts (D62, PRC-HOF-001 §3). Never user text."""

    model_config = ConfigDict(frozen=True)

    parts: list[PartSummary]
    error_codes: list[str] = Field(default_factory=list)     # "tool:status:reason" for every tool call that failed
    policies: list[str] = Field(default_factory=list)        # "doc_id §section@version" the replies cited
    verified_order_ids: list[str] = Field(default_factory=list)   # ids a tool confirmed are the user's own (audit #22)
    order_number_mentioned_unverified: bool = False          # an order number was mentioned but not confirmed


class Handoff(BaseModel):
    """The final handoff of the turn, one per turn. 9 (Milestone 2) turns it into a ticket."""

    model_config = ConfigDict(frozen=True)

    reason: HandoffReason
    priority: Priority | None                                # None while the owner has not answered the priority question
    acknowledgement_template: int = Field(ge=1, le=19)       # 5 customer, 6 worker, 8 P1: shown once for the whole turn
    block_session_data: bool                                 # CP-44 flag for 11 to apply, only for takeover or exposure
    summary: HandoffSummary


class ToolRecord(BaseModel):
    """One tool call and what came back. Kept in a list so two calls to the same tool don't overwrite each other."""

    tool: str
    argument: str | None = None
    result: ToolResult


class AgentState(BaseModel):
    """Filled in by the nodes as the request moves along."""

    # Written by classify. classify_ok defaults to False so a node that crashed or never ran
    # leaves the safe value, and the edge after classify falls to the code classifier.
    classify_ok: bool = False
    parts: list[Part] = Field(default_factory=list)
    english_query: str | None = None

    # Written by the safety gate and the plan.
    safety_flag: Safety | None = None                         # overall verdict; None until the safety gate has run
    tool_results: list[ToolRecord] = Field(default_factory=list)
    cited_docs: list[str] = Field(default_factory=list)       # "doc_id §section@version"
    clarify_question: str | None = None
    handoff_reason: HandoffReason | None = None
    priority: Priority | None = None
    handoff: Handoff | None = None                            # written by the handoff node: the final handoff of the turn
    result: AgentResult | None = None                         # written by the assemble node: what goes back to the Gateway

    # The multi-agent pattern. The router writes which agent runs; the supervisor writes which worker goes next; every
    # worker adds its stage to stages_done so the supervisor can tell what already ran (no loops).
    agent: str | None = None
    next_stage: str | None = None
    stages_done: list[str] = Field(default_factory=list)
    # The template choice lives in each Part.outcome (parts can differ); this holds values for the reply text.
    placeholders: dict[str, str] = Field(default_factory=dict)

    # Written by the reply node.
    reply_text: str | None = None

    # What the nodes measured (status and time of each model call, never text): node name -> its entry. Each node
    # adds its own entry through add_telemetry; assemble copies it into AgentResult.telemetry.
    telemetry: dict[str, dict] = Field(default_factory=dict)

    # Written by the clarify node: the card of a list it showed, for the Gateway to keep (assemble copies it).
    pending: dict | None = None

    # Derived from `parts`, so there is no second copy that could disagree with it.
    @property
    def any_p1(self) -> bool:
        """True if any part was judged P1."""
        return any(part.safety == "P1" for part in self.parts)

    @property
    def has_escalation(self) -> bool:
        """True if any part carries an escalation flag."""
        return any(part.escalation_flags for part in self.parts)

    @property
    def is_unclassified(self) -> bool:
        """Classify worked but no part has a known intent (this also covers an empty parts list)."""
        return self.classify_ok and all(part.intent is None for part in self.parts)

    def result_for(self, tool: str, argument: str | None = None) -> ToolResult | None:
        """The result of one specific tool call, or None if it has not been made."""
        for record in self.tool_results:
            if record.tool == tool and record.argument == argument:
                return record.result
        return None


def add_telemetry(state: AgentState, node: str, **entry) -> dict:
    """The state update that adds one node's entry next to the entries already there (a node returns this)."""
    return {"telemetry": {**state.telemetry, node: entry}}
