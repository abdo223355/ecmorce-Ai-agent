"""The supervisor's decision and the small routing functions of the graph. Plain functions of the state; no model.

`decide_next` is the heart of the supervisor. Rules it follows:
  - The fixed order is classify, then safety_gate. If classify failed, no plan runs and no tool is called (D37, step 2).
  - A P1 part goes to handoff before any backend call, with no plan, reply or clarify.
  - After the planner: reply, then clarify, then handoff, then assemble; a stage is skipped when the state does not need it.
  - clarify can turn an outcome into a handoff (third round), so handoff is checked after clarify, not before.
  - Each worker adds its name to `stages_done`, and a worker that already ran is never chosen again (no loops).

The supervisor never calls a model (D36, D39): the role was fixed by the router from the verified token, and the next
worker is chosen by this function from what the state already holds.
"""
from __future__ import annotations

from langgraph.graph import END

from .state import AgentState

# The workers that run after the planner, in order. Each runs only when the state needs it.
AFTER_PLAN = ("reply", "clarify", "handoff")


def _needs(stage: str, state: AgentState) -> bool:
    outcomes = [p.outcome for p in state.parts if p.outcome is not None]
    if stage == "reply":
        return any(o.kind == "reply" for o in outcomes)
    if stage == "clarify":
        return any(o.kind == "clarify" for o in outcomes)
    if stage == "handoff":
        return state.safety_flag == "P1" or any(o.handoff_reason is not None for o in outcomes)
    return True


def _worker(stage: str) -> str:
    return "planner" if stage == "planner" else f"worker_{stage}"


def decide_next(state: AgentState) -> str:
    """The next node for this request, or END. Called by the supervisor after every worker."""
    done = set(state.stages_done)
    if "classify" not in done:
        return _worker("classify")
    if "safety_gate" not in done:
        return _worker("safety_gate")
    if not state.classify_ok:                                            # no plan, no tools on this path (D37 step 2)
        if "classify_failed" not in done:
            return _worker("classify_failed")
    elif state.safety_flag != "P1":                                      # a P1 skips the plan and everything before the handoff
        if "planner" not in done:
            return _worker("planner")
        for stage in AFTER_PLAN[:-1]:                                    # reply, then clarify
            if stage not in done and _needs(stage, state):
                return _worker(stage)
    if "handoff" not in done and _needs("handoff", state):
        return _worker("handoff")
    if "assemble" not in done:
        return _worker("assemble")
    return END


def route_from_supervisor(state: AgentState) -> str:
    """The conditional edge out of the supervisor: the node it chose (always set by the supervisor)."""
    return state.next_stage or END


def route_by_agent(state: AgentState) -> str:
    """The conditional edge out of the router: the role it wrote."""
    return state.agent or END
