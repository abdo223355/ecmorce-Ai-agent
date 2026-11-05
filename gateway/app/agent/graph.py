"""The multi-agent graph, in the pattern's own terms. One top-level graph and one graph per agent.

    top level:   router --(role from the verified token)--> customer_agent  |  delivery_agent  --> END

    inside an agent:   supervisor <-> worker_classify, worker_safety_gate, planner, worker_reply, worker_clarify,
                                      worker_handoff, worker_classify_failed, worker_assemble
        START -> supervisor; every worker hands control back to the supervisor; the supervisor picks the next worker
        (edges.decide_next) or ends the run.

- router: code. It reads the role from the verified token (through the AgentContext) and writes `agent`; a role with no
  agent is rejected (D36, D39). It never reads the message.
- supervisor: code, deterministic, no model. It decides which worker goes next from what the state holds.
- planner: the plan node (a fixed intent -> plan table run by code, D37).
- workers: the other stage nodes, each with one job. (A "worker" here is a node of the pattern; the delivery worker is a
  user role, whose agent is `delivery_agent`.)

The request-bound things (the AgentContext and the Tools object) travel in the graph's runtime context, read-only; the
state holds only what the nodes write. The nodes themselves are plain functions in their own files.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from . import AgentContext, AgentRejected, Tools
from .assemble import assemble_node
from .classify import classify_node
from .classify_failed import classify_failed_node
from .clarify import clarify_node
from .edges import decide_next, route_by_agent, route_from_supervisor
from .handoff import handoff_node
from .plan import plan_node
from .reply import reply_node
from .safety_gate import safety_gate_node
from .spec import AGENTS, AgentSpec
from .state import AgentState


@dataclass(frozen=True)
class AgentRuntime:
    """What one request brings to the graph. Read-only for every node."""

    ctx: AgentContext
    tools: Tools


# Each entry: stage name -> how to call the plain node function from the graph.
async def _classify(state, runtime): return await classify_node(state, runtime.context.ctx)
def _gate(state, runtime): return safety_gate_node(state)
async def _plan(state, runtime): return await plan_node(state, runtime.context.ctx, runtime.context.tools)
async def _reply(state, runtime): return await reply_node(state, runtime.context.ctx)
def _clarify(state, runtime): return clarify_node(state, runtime.context.ctx)
def _handoff(state, runtime): return handoff_node(state, runtime.context.ctx)
def _classify_failed(state, runtime): return classify_failed_node(state, runtime.context.ctx)
def _assemble(state, runtime): return assemble_node(state, runtime.context.ctx)

# stage -> (graph node id, function). The planner keeps its own name; the others are workers.
STAGES = {"classify": ("worker_classify", _classify), "safety_gate": ("worker_safety_gate", _gate), "planner": ("planner", _plan),
          "reply": ("worker_reply", _reply), "clarify": ("worker_clarify", _clarify), "handoff": ("worker_handoff", _handoff),
          "classify_failed": ("worker_classify_failed", _classify_failed), "assemble": ("worker_assemble", _assemble)}


def _tracked(stage: str, fn):
    """Run the node and record its stage, so the supervisor can tell what already ran."""
    async def run(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
        update = fn(state, runtime)
        if inspect.isawaitable(update):
            update = await update
        return {**(update or {}), "stages_done": state.stages_done + [stage]}
    run.__name__ = STAGES[stage][0]
    return run


def _supervisor(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    return {"next_stage": decide_next(state)}


def _router(state: AgentState, runtime: Runtime[AgentRuntime]) -> dict:
    role = runtime.context.ctx.role
    if role not in AGENTS:
        raise AgentRejected(role)                                     # D36: any other role gets no agent
    return {"agent": role}


def build_agent_graph(spec: AgentSpec):
    """The graph of ONE agent: a supervisor and its workers. Both agents are built from the same workers."""
    g = StateGraph(AgentState, context_schema=AgentRuntime)
    g.add_node("supervisor", _supervisor)
    for stage, (node_id, fn) in STAGES.items():
        g.add_node(node_id, _tracked(stage, fn))
        g.add_edge(node_id, "supervisor")                              # every worker reports back to the supervisor
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route_from_supervisor, [node_id for node_id, _ in STAGES.values()] + [END])
    return g.compile(name=spec.node_name)


def build_system():
    """The top-level graph: the router and the two agent graphs as nodes."""
    g = StateGraph(AgentState, context_schema=AgentRuntime)
    g.add_node("router", _router)
    for spec in AGENTS.values():
        g.add_node(spec.node_name, build_agent_graph(spec))
        g.add_edge(spec.node_name, END)
    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_by_agent, {spec.role: spec.node_name for spec in AGENTS.values()})
    return g.compile(name="agent_system")
