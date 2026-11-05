"""Node 7: assemble. Code only. Builds the AgentResult that goes back to the Gateway, from what the nodes left in the state.

One segment per answered part, in written order (D30), then the handoff of the turn if there is one:
- outcome kind "template": a template segment (the template to render, with its render_values);
- kind "reply" with the reply's words: a "text" segment (the words keep their placeholders, the part's template stays
  as the FALLBACK, the citations the reply used); a reply that never got words falls back to its template, else 18;
- kind "clarify" with its question: a "clarify" segment (a question, not an answer: 11 can store a pending question
  and the validator does not look for claims in it); a clarify part that was deferred has no text and no segment;
- kind "handoff": no segment of its own, the turn's acknowledgement covers it.
The acknowledgement (5, 6 or 8) is one turn-level segment: first for a P1 (the emergency line comes before anything),
else last. A part that has an intent but no outcome (the plan has no row for it yet) gets template 18 as a safe interim, EXCEPT
when the turn was stopped by a P1: then the parts the plan never ran say nothing and only the emergency acknowledgement goes.
If nothing at all would be sent, one template 18 is sent so the user never gets silence.

Never in the result: llm_facts, retrieved section texts, raw tool results, or the message (those stay inside the agent).
Never raises, never changes the state it reads, deterministic.
"""
from __future__ import annotations

import json
import logging

from . import AgentContext, AgentResult, Segment
from .state import AgentState, Part, PartOutcome

log = logging.getLogger("gateway.agent.assemble")

COULD_NOT_FINISH = 18         # D68 18: "I couldn't finish this part right now"
ACK_BEFORE = -1               # part_index of a P1 acknowledgement: it comes first


def _template(part: Part, o: PartOutcome) -> Segment | None:
    return Segment(part.index, "template", template_id=o.template_id, render_values=dict(o.render_values))


def _reply(part: Part, o: PartOutcome) -> Segment | None:
    if o.text:
        return Segment(part.index, "text", template_id=o.template_id, text=o.text,
                       render_values=dict(o.render_values), cited=list(o.cited))
    if o.template_id is not None:                                  # the reply never got words: its own template
        return Segment(part.index, "template", template_id=o.template_id, render_values=dict(o.render_values))
    return Segment(part.index, "template", template_id=COULD_NOT_FINISH)


def _clarify(part: Part, o: PartOutcome) -> Segment | None:
    if not o.text:
        return None                                                # deferred: asked in a later turn
    return Segment(part.index, "clarify", text=o.text, render_values=dict(o.render_values))


def _chat(part: Part, o: PartOutcome) -> Segment | None:
    # finished words from code (agent/chat.py, or a code-built list with {placeholders} and their render_values)
    return Segment(part.index, "text", text=o.text, render_values=dict(o.render_values), cited=list(o.cited))


def _none(part: Part, o: PartOutcome) -> Segment | None:
    return None


BUILDERS = {"template": _template, "reply": _reply, "clarify": _clarify, "handoff": _none, "chat": _chat}


def _segment_for(part: Part, stopped_by_p1: bool) -> Segment | None:
    if part.outcome is None:
        if stopped_by_p1:
            return None                      # a P1 stops every part: the plan never ran, so these say nothing (D37, CP-44)
        # An intent the plan has no row for yet gets the safe interim; a part with no intent says nothing.
        return Segment(part.index, "template", template_id=COULD_NOT_FINISH) if part.intent is not None else None
    return BUILDERS[part.outcome.kind](part, part.outcome)


def assemble_node(state: AgentState, ctx: AgentContext) -> dict:
    stopped = state.safety_flag == "P1"
    segments = sorted((s for s in (_segment_for(p, stopped) for p in state.parts) if s is not None),
                      key=lambda s: s.part_index)
    handoff = state.handoff
    if handoff is not None:
        ack = Segment(ACK_BEFORE if handoff.acknowledgement_template == 8 else len(state.parts), "template",
                      template_id=handoff.acknowledgement_template)
        segments = [ack] + segments if handoff.acknowledgement_template == 8 else segments + [ack]
    if not segments:                                               # never send silence
        segments = [Segment(0, "template", template_id=COULD_NOT_FINISH)]
        log.warning(json.dumps({"node": "assemble", "empty_result": True}))
    result = AgentResult(segments=segments,
                         handoff_reason=handoff.reason if handoff else None,
                         priority=handoff.priority if handoff else None,
                         block_session_data=handoff.block_session_data if handoff else False,
                         handoff_summary=handoff.summary.model_dump(mode="json") if handoff else None,
                         telemetry=dict(state.telemetry),
                         memory={"pending": state.pending} if state.pending else {})
    log.info(json.dumps({"node": "assemble", "segments": [(s.part_index, s.kind, s.template_id) for s in segments],
                         "handoff": result.handoff_reason}))
    return {"result": result}
