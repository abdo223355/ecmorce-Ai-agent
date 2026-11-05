"""The data side of Node 3 (plan): what one intent's plan looks like. No tool is called in this file.

A PlanSpec is one row of the plan table. It is frozen data, shared by every request:
- branches: ordered alternatives. The first branch whose `requires` arguments are all present is the one used.
  (C1 with an order reference takes one branch; C1 with only an item clue takes another.)
- a branch is a tuple of steps run in order. A step is a ToolStep (one tool call) or a FanOutStep (the same tool
  over a list taken from an earlier step, run in parallel).
- every argument of a step comes from an ArgSource: the intent's arguments, a real id behind an order ref, an
  earlier result through a named selector, or a constant. The LLM never sees a real id.
- what to do when the steps are done: a builder (name) that turns the data into render values and LLM facts, the template for
  the fast path, and the template for "nothing found".
- on_status: only what differs from the shared default status table (plan_outcomes.py).

Selectors and builders are code, kept in two small registries and referred to by name from the rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol

from . import AgentContext
from .state import Intent, PartOutcome, Section

Role = Literal["customer", "worker"]


@dataclass
class StepEnv:
    """What an ArgSource, a selector or a builder may read for one part. Built fresh for every part."""

    ctx: AgentContext
    intent: Intent
    results: dict[str, Any] = field(default_factory=dict)    # step name -> ToolResult, or list[ToolResult] (fan-out)
    english_query: str | None = None                        # classify's English search query (state, read-only here)


@dataclass(frozen=True)
class Built:
    """What a builder returns: real values for code to render, and the safe version the LLM may see."""
    render_values: dict[str, str]
    llm_facts: dict[str, str]
    sections: tuple[Section, ...] = ()                       # retrieved policy sections, for intents answered by RAG


class NeedsClarification(Exception):
    """A builder found the data but cannot choose (for example two returns match): ask the user."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class ReadyOutcome(Exception):
    """A builder has a finished answer of its own (for example a code-built list): the plan uses it as it is."""

    def __init__(self, outcome: PartOutcome):
        super().__init__("ready_outcome")
        self.outcome = outcome


# ---- registries: code that rows refer to by name ----
SELECTORS: dict[str, Callable[[StepEnv], Any]] = {}                     # env -> value (or list, or None)
BUILDERS: dict[str, Callable[[StepEnv], Built | None]] = {}              # env -> Built, None = not found


def selector(name: str):
    def register(fn):
        SELECTORS[name] = fn
        return fn
    return register


def builder(name: str):
    def register(fn):
        BUILDERS[name] = fn
        return fn
    return register


# ---- where an argument comes from ----
class ArgSource(Protocol):
    def resolve(self, env: StepEnv) -> Any | None: ...      # None means "missing"


@dataclass(frozen=True)
class FromArg:
    """The value classify extracted, or a default when classify gave none."""
    name: str
    default: Any = None

    def resolve(self, env: StepEnv) -> Any | None:
        value = env.intent.arguments.get(self.name)
        return value if value not in (None, "", []) else self.default


@dataclass(frozen=True)
class FromRef:
    """The REAL id behind an order ref such as order_ref_1. Only the code ever holds the real id."""
    name: str

    def resolve(self, env: StepEnv) -> Any | None:
        ref = env.intent.arguments.get(self.name)
        return env.ctx.order_refs.get(ref) if isinstance(ref, str) else None


@dataclass(frozen=True)
class FromCtx:
    """A read-only field of the request context. Only the scrubbed message is allowed: no identity, no chat id."""
    name: str

    def resolve(self, env: StepEnv) -> Any | None:
        if self.name != "message":
            raise ValueError("only the message may be read from the context")
        return env.ctx.message


@dataclass(frozen=True)
class FromEnv:
    """A value classify left in the state for the plan. Only english_query. `default` is used when it is empty."""
    name: str
    default: Any = None

    def resolve(self, env: StepEnv) -> Any | None:
        if self.name != "english_query":
            raise ValueError("only english_query may be read from the state")
        return env.english_query or self.default


@dataclass(frozen=True)
class FromResult:
    """A value picked from earlier results by a named selector (for example the order that matches a clue)."""
    selector: str

    def resolve(self, env: StepEnv) -> Any | None:
        return SELECTORS[self.selector](env)


@dataclass(frozen=True)
class Const:
    value: Any

    def resolve(self, env: StepEnv) -> Any | None:
        return self.value


# ---- steps ----
@dataclass(frozen=True)
class ToolStep:
    name: str                                          # the key under which the result is kept in StepEnv.results
    tool: str
    args: tuple[tuple[str, ArgSource], ...] = ()


@dataclass(frozen=True)
class FanOutStep:
    """The same tool once per value of a list, in parallel. `over` is a selector that returns the list."""
    name: str
    tool: str
    over: str
    arg: str                                           # the tool parameter that receives each value


Step = ToolStep | FanOutStep


@dataclass(frozen=True)
class Branch:
    requires: tuple[str, ...]                          # names that must be present in Intent.arguments
    steps: tuple[Step, ...] = ()
    outcome: PartOutcome | None = None                 # a fixed answer with no tool call (handoff-only intents)
    builder: str | None = None                         # this branch's own builder (wins over the row's builder)


def args(**sources: ArgSource) -> tuple[tuple[str, ArgSource], ...]:
    return tuple(sources.items())


@dataclass(frozen=True)
class PlanSpec:
    role: Role
    intent_id: str
    branches: tuple[Branch, ...]
    builder: str | None = None                         # None: the data goes to the reply LLM as it is
    template_id: int | None = None                     # fast-path template when the part needs no explanation
    not_found_template: int | None = None              # when the builder finds nothing
    not_found_outcome: PartOutcome | None = None       # a fuller "found nothing" answer (template + handoff); wins
    on_status: dict[tuple[str, str | None], PartOutcome] = field(default_factory=dict)
