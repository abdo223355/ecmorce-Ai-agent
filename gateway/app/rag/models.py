"""The Chunk dataclass: one indexed piece of a policy. Plain data, no database and no embedding logic."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    doc_id: str                  # POL-RET-001
    doc_title: str               # "Return Policy"
    version: str                 # "2.1"
    status: str                  # ACTIVE | SUPERSEDED | DRAFT (only ACTIVE is ever retrieved)
    audience: tuple[str, ...]    # subset of ("customers", "delivery_workers"); () means neither is named
    section: str                 # "2"
    title: str                   # "Return Window"
    text: str                    # the section itself: this is what gets shown and cited
    context_before: str = ""     # a bit of the previous section; only used when embedding
    part: int = 1                # 1, 2, ... when a long section was split
    source_file: str = ""

    @property
    def cited(self) -> str:
        """The citation the agent returns and the validator checks: 'doc_id §section@version'."""
        return f"{self.doc_id} §{self.section}@{self.version}"

    @property
    def embed_text(self) -> str:
        """The text we embed: a short header, the overlap from the previous section, then the section."""
        head = f"{self.doc_title} — §{self.section} {self.title}"
        return "\n".join(p for p in (head, self.context_before, self.text) if p)
