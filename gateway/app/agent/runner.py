"""run_agent: the entry the Gateway calls for every chat turn. It runs the top-level graph: the router (code, from the
verified token's role) picks the agent, and that agent's supervisor runs its workers (graph.py).

A role with no agent is rejected by the router with AgentRejected, never guessed and never sent to the other agent
(D36, D39). The model is not involved in any routing decision.
"""
from __future__ import annotations

from . import AgentContext, AgentResult, Tools
from .graph import AgentRuntime, build_system
from .state import AgentState

_SYSTEM = None                       # the compiled top-level graph, built on first use (compiling is cheap, not free)
RECURSION_LIMIT = 60                 # a request takes about 20 graph steps; the limit only catches a runaway loop


def system():
    global _SYSTEM
    if _SYSTEM is None:
        _SYSTEM = build_system()
    return _SYSTEM


async def run_agent(ctx: AgentContext, tools: Tools) -> AgentResult:
    out = await system().ainvoke(AgentState(), context=AgentRuntime(ctx, tools), config={"recursion_limit": RECURSION_LIMIT})
    return out["result"]
