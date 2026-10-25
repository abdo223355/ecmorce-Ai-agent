"""Build the L1 retrieval set from EVL-RAG-001 and FREEZE its held-out split (D118: 20% of each layer, written
before tuning, never used for tuning).

    python -m evals.build_l1 [--pdf PATH] [--force]

Split rule (fixed, so anyone can rebuild the same split): inside each category, sorted by question id,
every 5th question (positions 5, 10, 15, ...) is held-out; the rest is the tuning split.
BLOCKED (Step 9): a question whose expected documents were missing from the project when the plan was written.
Those documents are now in the corpus, so the tag is kept as data and the decision is his (see docs/PROGRESS.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from pypdf import PdfReader

OUT = Path(__file__).parent / "data" / "l1_evl_rag_001.json"
DEFAULT_PDF = Path(__file__).resolve().parents[3] / "Rag_files" / "NovaCart_RAG_Corpus" / "Evaluation" / \
    "29_RAG_Evaluation_Set.pdf"
# BLOCKED (Step 9) was written when these 7 documents were missing from the project:
# POL-ESC-001, PRC-MIS-001, POL-COM-001, REF-OST-001, REF-RST-001, POL-ACC-001, POL-IDV-001.
# DECISION (عبدالرحمن, 2026-10-26): all 7 are in the corpus now, so nothing is BLOCKED. A question whose expected
# documents are not visible to its role (POL-COM-001 is internal-audience) is NOT blocked: l1_retrieval.py counts
# it as "not answerable" and scores abstention. Put a doc id here again only if it is missing from the corpus.
BLOCKED_DOCS: set[str] = set()
_DOC = re.compile(r"\b((?:POL|REF|PRC|GDL|EVL)-[A-Z]{3}-\d{3})\b")
_CATEGORY = re.compile(r"^\d\. (.+) Questions \(\d+\)$")


def parse(pdf: Path) -> list[dict]:
    lines = [l.strip() for p in PdfReader(str(pdf)).pages for l in p.extract_text().split("\n")]
    lines = [l for l in lines if l and not l.startswith(("NovaCart  |", "Page ", "NOVACART - SYNTHETIC"))]
    items, cur, category = [], None, None
    for i, line in enumerate(lines):
        m = _CATEGORY.match(line)
        if m:
            category, cur = m.group(1), None
            continue
        if re.fullmatch(r"Q\d{3}", line):
            cur = {"id": line, "category": category, "question": [], "user": None, "docs": []}
            items.append(cur)
            continue
        if cur is None:
            continue
        if cur["user"] is None:
            if line == "Customer":
                cur["user"] = "customer"
            elif line == "Delivery" and i + 1 < len(lines) and lines[i + 1] == "Worker":
                cur["user"] = "worker"
            else:
                cur["question"].append(line)
        else:
            cur["docs"] += _DOC.findall(line)
    out = []
    for it in items:
        docs = sorted(set(it["docs"]))
        out.append({"id": it["id"], "category": it["category"], "user": it["user"],
                    "question": " ".join(it["question"]), "expected_docs": docs,
                    "blocked": bool(docs) and set(docs) <= BLOCKED_DOCS})
    return out


def split(items: list[dict]) -> list[dict]:
    by_cat: dict[str, list[dict]] = {}
    for it in items:
        by_cat.setdefault(it["category"], []).append(it)
    for group in by_cat.values():
        for pos, it in enumerate(sorted(group, key=lambda x: x["id"]), start=1):
            it["split"] = "held_out" if pos % 5 == 0 else "tuning"
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", default=str(DEFAULT_PDF))
    ap.add_argument("--force", action="store_true", help="overwrite a frozen set (only if the source changed)")
    args = ap.parse_args()
    if OUT.exists() and not args.force:
        print(f"{OUT.name} is frozen; use --force only if EVL-RAG-001 itself changed")
        return 1
    items = split(parse(Path(args.pdf)))
    bad = [it["id"] for it in items if it["user"] is None or not it["question"]]
    if bad:
        print("could not parse:", bad)
        return 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": "EVL-RAG-001 v1.0", "frozen": str(date.today()),
                               "split_rule": "per category, sorted by id, every 5th = held_out",
                               "questions": items}, ensure_ascii=False, indent=1), encoding="utf-8")
    n_held = sum(it["split"] == "held_out" for it in items)
    print(f"{len(items)} questions -> {OUT} | tuning {len(items) - n_held}, held_out {n_held}, "
          f"blocked {sum(it['blocked'] for it in items)}, no expected doc {sum(not it['expected_docs'] for it in items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
