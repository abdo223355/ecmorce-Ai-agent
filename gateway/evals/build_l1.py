"""Build the L1 retrieval set from EVL-RAG-001 and freeze its held-out split.

    python -m evals.build_l1 [--pdf PATH] [--force]

The held-out part is 20% of every category. It is fixed up front and never used for tuning.
The split rule is deterministic so anyone can rebuild the same one: inside each category, questions sorted
by id, every 5th (positions 5, 10, 15, ...) is held-out and the rest is the tuning split.

BLOCKED used to mean "the expected documents were missing from the project when the plan was written".
All of those documents are in the corpus now, so nothing is blocked (see BLOCKED_DOCS below).
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
# Seven documents were missing when the evaluation plan was written: POL-ESC-001, PRC-MIS-001, POL-COM-001,
# REF-OST-001, REF-RST-001, POL-ACC-001 and POL-IDV-001. They are all in the corpus now, so this is empty.
# A question whose expected documents the role can't see (POL-COM-001 is internal) is not blocked either:
# l1_retrieval.py counts it as "not answerable" and scores whether we abstain.
# Add a document id here again only if it goes missing from the corpus.
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
