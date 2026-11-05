"""Node 3: plan. Runs the fixed tool plan of each part's intent. Code calls the tools, never the model (D37 step 3).

The pieces:
- plan_spec.py: the data (PlanSpec rows, steps, argument sources).      - plan_rows.py: the rows.
- plan_outcomes.py: OutcomeMapper (tool status -> decision).             - plan_registry.py: selectors and builders.
- RequestCache (here): one tool call per (tool, arguments) in a request, shared by all parts, and the record of calls.
- PlanExecutor (here): runs ONE part's plan. plan_node (here): runs every part with an intent, in parallel.

The node never raises: a tool that raises becomes `unavailable`. It does not render templates, it only chooses them.
No message text is logged (D108), only intent ids, outcomes and statuses.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from ..tools import ToolResult
from . import AgentContext, Tools
from .plan_outcomes import OutcomeMapper
from .plan_rows import PLANS
from .plan_spec import (BUILDERS, SELECTORS, FanOutStep, NeedsClarification, PlanSpec, ReadyOutcome, StepEnv,
                        ToolStep)
from .state import AgentState, Part, PartOutcome, ToolRecord

log = logging.getLogger("gateway.agent.plan")

# The only tools a plan row may name in this slice. A name outside the set is a bug in a row, not something to call.
ALLOWED_TOOLS = frozenset({"my_recent_orders", "my_returns", "order_details", "my_shipments_today", "shipment_details",
                           "policy_search", "procedure_search"})


def _plain(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _one(value: Any) -> str:
    text = ",".join(map(str, value)) if isinstance(value, list) else str(value)
    # A long value (the user's whole message in a policy search) is kept as a short digest, so the record never
    # carries a copy of the message and the key stays small. Equal texts still give equal keys.
    return text if len(text) <= 64 else "sha1:" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _argument_key(kwargs: dict[str, Any]) -> str | None:
    """A stable text for the arguments of one call: it identifies the call and is stored in ToolRecord.argument."""
    return "|".join(_one(v) for _, v in sorted(kwargs.items())) or None


class RequestCache:
    """One call per (tool, arguments) in a request. A second part asking the same thing shares the first answer."""

    def __init__(self, tools: Tools):
        self._tools = tools
        self._tasks: dict[tuple, asyncio.Task] = {}
        self.records: list[ToolRecord] = []

    async def call(self, tool: str, kwargs: dict[str, Any]) -> ToolResult:
        if tool not in ALLOWED_TOOLS:
            return ToolResult("unavailable", reason="tool_not_allowed")
        kwargs = {k: _plain(v) for k, v in kwargs.items()}
        key = (tool, _argument_key(kwargs))
        if key not in self._tasks:
            self._tasks[key] = asyncio.ensure_future(self._invoke(tool, kwargs, key[1]))
        return await self._tasks[key]

    async def _invoke(self, tool: str, kwargs: dict[str, Any], argument: str | None) -> ToolResult:
        try:
            result = await getattr(self._tools, tool)(**kwargs)
        except Exception as e:                                        # a tool must not raise; if it does, be safe
            log.warning(json.dumps({"node": "plan", "tool": tool, "error": type(e).__name__}))
            result = ToolResult("unavailable", reason="tool_exception")
        self.records.append(ToolRecord(tool=tool, argument=argument, result=result))
        return result


class PlanExecutor:
    def __init__(self, ctx: AgentContext, cache: RequestCache, english_query: str | None = None):
        self._ctx, self._cache, self._english_query = ctx, cache, english_query

    async def run(self, part: Part) -> PartOutcome | None:
        """The outcome for one part, or None when the intent has no row in the table yet."""
        spec = PLANS[self._ctx.role].get(part.intent.id) if part.intent else None
        if spec is None:
            return None
        branch = next((b for b in spec.branches if all(self._has(part, name) for name in b.requires)), None)
        if branch is None:
            return PartOutcome(kind="clarify", reason="missing_argument")
        if branch.outcome is not None:                                # no tool needed: the row already says the answer
            return branch.outcome
        env = StepEnv(self._ctx, part.intent, english_query=self._english_query)
        mapper = OutcomeMapper(self._ctx.role, spec.on_status)
        for step in branch.steps:
            outcome = await (self._fan_out if isinstance(step, FanOutStep) else self._single)(step, env, mapper, spec)
            if outcome is not None:
                return outcome
        return self._finish(spec, part, env, branch.builder or spec.builder)

    def _has(self, part: Part, name: str) -> bool:
        """Is the argument there? An order ref that is not in the per-request map counts as absent, so the plan falls
        through to the next branch (the recent orders) instead of asking with nothing to show."""
        value = part.intent.arguments.get(name)
        if value in (None, "", []):
            return False
        return value in self._ctx.order_refs if name == "order_ref" else True

    async def _single(self, step: ToolStep, env: StepEnv, mapper: OutcomeMapper, spec: PlanSpec) -> PartOutcome | None:
        kwargs = {name: source.resolve(env) for name, source in step.args}
        missing = next((name for name, value in kwargs.items() if value is None), None)
        if missing is not None:                                       # for example no single order matches the clue
            return PartOutcome(kind="clarify", reason=f"missing_{missing}")
        result = await self._cache.call(step.tool, kwargs)
        env.results[step.name] = result
        return mapper.map(result)

    async def _fan_out(self, step: FanOutStep, env: StepEnv, mapper: OutcomeMapper, spec: PlanSpec) -> PartOutcome | None:
        values = SELECTORS[step.over](env)
        if not values:                                                # nothing to look through: not found
            return self._not_found(spec)
        results = await asyncio.gather(*(self._cache.call(step.tool, {step.arg: v}) for v in values))
        env.results[step.name] = list(results)
        if any(r.ok for r in results):                                # one found order is enough to look at
            return None
        return mapper.map(results[0])

    @staticmethod
    def _not_found(spec: PlanSpec) -> PartOutcome:
        if spec.not_found_outcome is not None:
            return spec.not_found_outcome
        if spec.not_found_template is None:
            return PartOutcome(kind="clarify", reason="nothing_found")
        return PartOutcome(kind="template", template_id=spec.not_found_template)

    def _finish(self, spec: PlanSpec, part: Part, env: StepEnv, builder: str | None) -> PartOutcome:
        if builder is None:                                           # no template for this intent: the reply writes it
            return PartOutcome(kind="reply", template_id=spec.template_id)
        try:
            built = BUILDERS[builder](env)
        except NeedsClarification as e:
            return PartOutcome(kind="clarify", reason=e.reason)
        except ReadyOutcome as e:
            return e.outcome
        if built is None:
            return self._not_found(spec)
        # A part that asks "why" needs the reply LLM even when a template exists (D73). The template stays on the
        # outcome as the fallback if the reply fails validation or runs out of time (D30, D66, D75).
        if part.needs_explanation or spec.template_id is None:
            return PartOutcome(kind="reply", template_id=spec.template_id, render_values=built.render_values,
                               llm_facts=built.llm_facts, sections=list(built.sections))
        return PartOutcome(kind="template", template_id=spec.template_id, render_values=built.render_values)


async def plan_node(state: AgentState, ctx: AgentContext, tools: Tools) -> dict:
    cache = RequestCache(tools)
    executor = PlanExecutor(ctx, cache, state.english_query)
    outcomes = await asyncio.gather(*(executor.run(p) for p in state.parts))
    parts = [p.model_copy(update={"outcome": o}) if o is not None else p for p, o in zip(state.parts, outcomes)]
    update: dict[str, Any] = {"parts": parts, "tool_results": state.tool_results + cache.records}
    log.info(json.dumps({"node": "plan", "parts": [
        {"intent": p.intent.id, "outcome": o.kind, "template": o.template_id, "reason": o.reason}
        for p, o in zip(state.parts, outcomes) if p.intent and o], "calls": len(cache.records)}))
    return update
