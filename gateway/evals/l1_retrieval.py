"""L1 retrieval eval (D114) and the score-gate sweep.

    python -m evals.l1_retrieval                          # tuning split: metrics + sweep -> proposed gate
    python -m evals.l1_retrieval --held-out --gate 0.62   # held-out: confirm ONE fixed gate, once, no sweep

D114:
- correct document in the top 5 >= 90% of non-BLOCKED questions (soft);
- a document closed for the role / SUPERSEDED / DRAFT as main evidence = 0 (hard);
- score gate: sweep candidate gates on the tuning split, pick the one with the most correct answers + correct
  abstentions, confirm once on the held-out, never tune on it.

Per question, with gate g on the best cosine of the vector search:
- answerable = at least one expected document is indexed and visible for that role;
- answerable and best >= g and an expected doc in the top 5  -> correct answer
- answerable and best <  g                                    -> wrong abstention (a human gets a question we could answer)
- not answerable and best < g                                 -> correct abstention
- everything else                                             -> wrong answer
The questions are English (EVL-RAG-001), so they are passed as both query and english_query (hybrid), as
classify would do for an English message. Document level only: sections are not scored here.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.backend_client import Deadline
from app.rag import retrieve
from app.rag.embeddings import get_embedder
from app.rag.store import PolicyStore

DATA = Path(__file__).parent / "data" / "l1_evl_rag_001.json"
AUDIENCE = {"customer": "customers", "worker": "delivery_workers"}


@dataclass
class Row:
    id: str
    category: str
    blocked: bool
    answerable: bool
    top_docs: list[str]
    best: float | None
    hit5: bool
    top1_visible: bool


def visible(doc_id: str, user: str, docs: dict[str, tuple[str, ...]]) -> bool:
    if doc_id not in docs:
        return False
    if user == "customer":
        return "customers" in docs[doc_id] or doc_id in retrieve.CUSTOMER_ALLOW_LIST
    return "delivery_workers" in docs[doc_id]


async def collect(questions: list[dict]) -> list[Row]:
    retrieve.SCORE_GATE = None                       # measure raw results; the gate is applied afterwards
    rows = []
    async with PolicyStore(statement_timeout_ms=10_000) as store:
        docs = await store.active_docs()
        embedder = get_embedder()
        for q in questions:
            r = await retrieve.search(q["question"], AUDIENCE[q["user"]], Deadline(30.0), store, embedder,
                                      english_query=q["question"])
            top = [d["doc_id"] for d in (r.data or [])]
            rows.append(Row(q["id"], q["category"], q["blocked"],
                            any(visible(d, q["user"], docs) for d in q["expected_docs"]),
                            top, (r.details or {}).get("best_cosine"),
                            any(d in q["expected_docs"] for d in top),
                            not top or visible(top[0], q["user"], docs)))
    return rows


def judge(rows: list[Row], gate: float) -> Counter:
    c = Counter()
    for r in rows:
        passes = r.best is not None and r.best >= gate
        if r.answerable and passes and r.hit5:
            c["correct_answer"] += 1
        elif r.answerable and not passes:
            c["wrong_abstention"] += 1
        elif not r.answerable and not passes:
            c["correct_abstention"] += 1
        else:
            c["wrong_answer"] += 1
    return c


def sweep(rows: list[Row]) -> list[tuple[float, Counter]]:
    bests = sorted({round(r.best, 3) for r in rows if r.best is not None})
    candidates = [0.0] + bests                      # 0.0 = no gate; each best score = "everything below it abstains"
    return [(g, judge(rows, g)) for g in candidates]


def report(rows: list[Row], title: str) -> None:
    ans = [r for r in rows if r.answerable]
    nb = [r for r in ans if not r.blocked]
    print(f"\n== {title}: {len(rows)} questions | answerable {len(ans)} | not answerable {len(rows) - len(ans)}")
    print(f"   hit@5 (no gate): all answerable {sum(r.hit5 for r in ans)}/{len(ans)} = {sum(r.hit5 for r in ans) / max(len(ans), 1):.0%}"
          f" | non-BLOCKED {sum(r.hit5 for r in nb)}/{len(nb)} = {sum(r.hit5 for r in nb) / max(len(nb), 1):.0%}   (D114 soft: >= 90%)")
    print(f"   top-1 document closed for the role: {sum(not r.top1_visible for r in rows)}   (D114 hard: must be 0)")
    for cat in sorted({r.category for r in ans}):
        g = [r for r in ans if r.category == cat]
        print(f"   {cat:28s} hit@5 {sum(r.hit5 for r in g)}/{len(g)}")
    misses = [r for r in ans if not r.hit5]
    if misses:
        print("   misses:", ", ".join(f"{r.id}->{(r.top_docs or ['-'])[0]}" for r in misses))
    no = [r for r in rows if not r.answerable]
    if no:
        print("   not answerable (expected docs not visible for the role) -> best cosine, top-1 doc:")
        for r in no:
            print(f"     {r.id} {r.category:24s} best {r.best}  top-1 {(r.top_docs or ['-'])[0]}")
    no_vec = [r.id for r in rows if r.best is None]
    if no_vec:
        print("   no vector result (embedding failed -> keyword_only / no_retrieval):", ", ".join(no_vec))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--held-out", action="store_true", help="confirm a fixed gate on the held-out split (no sweep)")
    ap.add_argument("--gate", type=float, help="the gate to confirm (required with --held-out)")
    args = ap.parse_args()
    if args.held_out and args.gate is None:
        print("--held-out needs --gate: the held-out confirms a gate chosen on tuning, it never chooses one")
        return 2
    split = "held_out" if args.held_out else "tuning"
    questions = [q for q in json.loads(DATA.read_text(encoding="utf-8"))["questions"] if q["split"] == split]
    rows = asyncio.run(collect(questions))
    report(rows, split)
    if args.held_out:
        print(f"\n   gate {args.gate}: {dict(judge(rows, args.gate))}")
        return 0
    results = sweep(rows)
    best_gate, best_c = max(results, key=lambda gc: (gc[1]["correct_answer"] + gc[1]["correct_abstention"],
                                                     gc[1]["correct_answer"]))
    print("\n   gate   correct_ans  correct_abst  wrong_ans  wrong_abst")
    for g, c in results:
        mark = "  <- chosen" if g == best_gate else ""
        if g == 0.0 or g == best_gate or results.index((g, c)) % 8 == 0:
            print(f"   {g:5.3f}  {c['correct_answer']:11d}  {c['correct_abstention']:12d}  {c['wrong_answer']:9d}"
                  f"  {c['wrong_abstention']:10d}{mark}")
    print(f"\n   proposed gate (tuning only): {best_gate}  ->  {dict(best_c)}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(main())
