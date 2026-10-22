"""Data class for one indexed piece of a policy (D47). Pure data: no database, no embedding here."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    doc_id: str                  # POL-RET-001
    doc_title: str               # "Return Policy"
    version: str                 # "2.1"
    status: str                  # ACTIVE | SUPERSEDED | DRAFT  (only ACTIVE is retrieved, D47)
    audience: tuple[str, ...]    # subset of ("customers", "delivery_workers"); () = neither named
    section: str                 # "2"
    title: str                   # "Return Window"
    text: str                    # the section itself: what is shown and cited
    context_before: str = ""     # overlap from the previous piece: used ONLY for the embedding
    part: int = 1                # 1, 2, ... when one section was split because it was too long
    source_file: str = ""

    @property
    def cited(self) -> str:
        """Citation string for AgentResult.cited and the D66 check 2: 'doc_id §section@version'."""
        return f"{self.doc_id} §{self.section}@{self.version}"

    @property
    def embed_text(self) -> str:
        """What gets embedded: context header + overlap + the section text."""
        head = f"{self.doc_title} — §{self.section} {self.title}"
        return "\n".join(p for p in (head, self.context_before, self.text) if p)
