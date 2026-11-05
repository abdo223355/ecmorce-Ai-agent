"""The two agents of V1 (D9, D36, D39): a Customer agent (C1 to C14) and a Worker agent (W1 to W9).

An AgentSpec is the whole identity of one agent as frozen data: its role, the intents it understands, the plan table it
runs, the tools it may use and its acknowledgement template. The nodes are shared functions; what makes the two agents
different is this data and the graph built from it (graph.py).

The router between the agents is NOT here and is not an LLM: the role comes from the verified token and the code picks
the agent (runner.py). Any other role gets no agent and is rejected (D36).
"""
from __future__ import annotations

from dataclasses import dataclass

from .classify import CUSTOMER, WORKER, IntentCatalog, RoleSetup, SETUPS
from .plan import ALLOWED_TOOLS
from .plan_rows import PLANS
from .plan_spec import PlanSpec


@dataclass(frozen=True)
class AgentSpec:
    role: str
    classify: RoleSetup                       # the intents of this agent and the strict schema the model answers in
    plans: dict[str, PlanSpec]                # intent id -> its plan (the plan node's table for this role)
    tools: frozenset[str]                     # the tools this agent may call (the plan allow-list for its role)
    acknowledgement_template: int             # D68 5 (customer) or 6 (worker)
    node_name: str                            # this agent's node in the top-level graph (the router sends the request there)

    @property
    def catalog(self) -> IntentCatalog:
        return self.classify.catalog

    @property
    def planned_intents(self) -> frozenset[str]:
        return frozenset(self.plans)


_CUSTOMER_TOOLS = frozenset({"my_recent_orders", "my_returns", "order_details", "policy_search"})
_WORKER_TOOLS = frozenset({"my_shipments_today", "shipment_details", "procedure_search"})

CUSTOMER_AGENT = AgentSpec("customer", SETUPS["customer"], PLANS["customer"], _CUSTOMER_TOOLS, 5, "customer_agent")
# The role is called "worker" (a delivery worker); its node is "delivery_agent" so it is not confused with the pattern's workers.
WORKER_AGENT = AgentSpec("worker", SETUPS["worker"], PLANS["worker"], _WORKER_TOOLS, 6, "delivery_agent")

# The only agents. A role that is not here has no agent (D36).
AGENTS: dict[str, AgentSpec] = {spec.role: spec for spec in (CUSTOMER_AGENT, WORKER_AGENT)}

assert ALLOWED_TOOLS >= (_CUSTOMER_TOOLS | _WORKER_TOOLS)               # the plan allow-list covers both agents
assert CUSTOMER.role == "customer" and WORKER.role == "worker"
