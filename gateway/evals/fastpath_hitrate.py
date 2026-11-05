"""Measure the classify code fast path on evals/data/fastpath_messages_draft.json (no model call).

Run from gateway/:  python -m evals.fastpath_hitrate
Shows: hit rate on messages that should match, wrong matches (must be 0), and every miss so the patterns can be widened.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.agent import AgentContext
from app.agent.code_classifier import CodeClassifier

DATA = Path(__file__).parent / "data" / "fastpath_messages_draft.json"


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    refs = data["order_refs_used_when_measuring"]
    cc = CodeClassifier()
    hit = miss = wrong = leaked = 0
    should, shouldnt = 0, 0
    for m in data["messages"]:
        ctx = AgentContext(role=m["role"], message=m["message"], chat_id="x",
                           deadline_at=time.monotonic() + 8, order_refs=refs)
        parts = cc.classify(ctx)
        got = parts[0].intent.id if parts else None
        if m["expected"] is None:
            shouldnt += 1
            leaked += got is not None
            if got is not None:
                print(f"LEAK   {m['id']}: {m['message']!r} matched {got} (must go to the LLM)")
        else:
            should += 1
            if got == m["expected"]:
                hit += 1
            elif got is None:
                miss += 1
                print(f"miss   {m['id']}: {m['message']!r} (wanted {m['expected']})")
            else:
                wrong += 1
                print(f"WRONG  {m['id']}: {m['message']!r} matched {got}, wanted {m['expected']}")
    print(f"\nshould match: {hit}/{should} hit ({hit / should:.0%}), {miss} missed, {wrong} wrong intent")
    print(f"must not match: {leaked}/{shouldnt} leaked")


if __name__ == "__main__":
    main()
