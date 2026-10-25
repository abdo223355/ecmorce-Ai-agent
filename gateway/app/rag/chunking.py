"""Chunking: one chunk per numbered policy section, with a small overlap.

The input is the text of one policy PDF as `pdftotext -layout` prints it (tables keep their row order).
Everything here is a pure function with no file or network access, which keeps it easy to test.
Reading the PDF itself is ingest.py's job.

Known limits:
- Tables come out of the PDF as loose text. A table stays inside its section, but its cells are not aligned.
- The glossary should be one chunk per row (D47). That needs real table extraction, so for now it is
  chunked like any other document.
"""
from __future__ import annotations

import re

from .models import Chunk

# How much of the previous section is borrowed as context. One sentence, capped at 15 words: sections are
# short (median around 45 words), so a bigger overlap would mostly repeat the section itself. It is only used
# when embedding (context_before), never in the text we show or cite.
OVERLAP_MAX_WORDS = 15

# Sections longer than this are split. The longest one in the corpus is about 308 words, so it never triggers today.
MAX_WORDS = 400

# A split section is cut with a sliding window: each window is MAX_WORDS long and shares this many words
# with the next one. The windows are all the same section, so the citation does not change.
WINDOW_OVERLAP_WORDS = 50

# Very short sections (under about 25 words) are kept as their own chunks and not merged into the previous
# one, so that a citation still points at the exact section.

_HEADER = re.compile(r"^NovaCart Document (\S+) - Version (\S+) - Status: (\S+)")
_HEADING = re.compile(r"^(\d{1,2})\.\s+([A-Z][^\n]{1,100})$")
_EMBEDDED_NUMBER = re.compile(r"\s\d{1,2}\.\s")       # "1. Purpose 2. Terms" is a table-of-contents line
_NOISE_PREFIXES = ("NOVACART - SYNTHETIC", "NovaCart |")
_PAGE = re.compile(r"^Page \d+$")


def parse_header(lines: list[str]) -> dict:
    """Read doc id, version and status from the 'NovaCart Document X - Version Y - Status: Z' line,
    the title from the line above it, and the audience from the metadata block."""
    for i, line in enumerate(lines):
        m = _HEADER.match(line.strip())
        if m:
            break
    else:
        raise ValueError("no 'NovaCart Document ... Status:' header line")
    doc_id, version, status = m.groups()
    title = next((lines[j].strip() for j in range(i - 1, -1, -1)
                  if lines[j].strip() and not lines[j].startswith(_NOISE_PREFIXES)), "")
    return {"doc_id": doc_id, "version": version, "status": status, "doc_title": title,
            "audience": _audience(lines)}


def _audience(lines: list[str]) -> tuple[str, ...]:
    """Find the audience names in the metadata block, between 'Document Metadata' and 'Table of Contents'.
    Plain and -layout text print the label and value columns in a different order, so we search the whole
    block for the names instead of relying on position."""
    start = next((i for i, l in enumerate(lines) if l.strip().startswith("Document Metadata")), None)
    if start is None:
        return ()
    end = next((i for i in range(start, len(lines)) if lines[i].strip().startswith("Table of Contents")), len(lines))
    block = "\n".join(lines[start:end])
    tags = []
    if re.search(r"\bCustomers\b", block):
        tags.append("customers")
    if re.search(r"\bDelivery Workers\b", block):
        tags.append("delivery_workers")
    return tuple(tags)


def _clean(lines: list[str]) -> list[str]:
    """Drop the page banner, the footer and page numbers that repeat on every page, and squeeze the wide
    gaps that -layout leaves between table columns."""
    return [re.sub(r"[ \t]{2,}", " ", l).strip() for l in lines
            if not l.startswith(_NOISE_PREFIXES) and not _PAGE.match(l.strip())]


def _headings(lines: list[str]) -> list[tuple[int, str, str]]:
    """Find the real section headings as (line index, number, title).

    Numbered lines show up in three places: the table of contents, the section headings, and numbered steps
    inside a section. The headings are the longest run of 1, 2, 3, ... made of whole-line titles, which
    skips the other two.
    """
    runs: list[list[tuple[int, str, str]]] = []
    for i, line in enumerate(lines):
        m = _HEADING.match(line.strip())
        # A heading is a short title. A numbered step is a sentence that ends with a period.
        if not m or _EMBEDDED_NUMBER.search(m.group(2)) or m.group(2).rstrip().endswith((".", ";", ":")):
            continue
        num, title = int(m.group(1)), m.group(2).strip()
        if num == 1:
            runs.append([(i, "1", title)])
            continue
        # extend the most recent run that is waiting for this number
        for run in reversed(runs):
            if int(run[-1][1]) == num - 1:
                run.append((i, str(num), title))
                break
    return max(runs, key=lambda r: (len(r), r[0][0])) if runs else []


def _sentences_tail(text: str, max_words: int) -> str:
    """The last sentence of `text`, cut to its last `max_words` words.

    Returns "" when the text does not end in a sentence (it ends with a table row, say), because
    borrowing a table row as context would just add noise.
    """
    if not re.search(r"[.!?][\"')]*$", text.strip()):
        return ""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    if not sentences:
        return ""
    return " ".join(sentences[-1].split()[-max_words:])


def _sliding_window(text: str) -> list[str]:
    """Cut a section longer than MAX_WORDS into windows of MAX_WORDS words.

    Each window starts MAX_WORDS - WINDOW_OVERLAP_WORDS words after the previous one, so neighbours share
    WINDOW_OVERLAP_WORDS words. It slices the original string between word positions, which keeps line
    breaks (and so table rows) intact.
    """
    words = list(re.finditer(r"\S+", text))
    if len(words) <= MAX_WORDS:
        return [text]
    step = MAX_WORDS - WINDOW_OVERLAP_WORDS
    if step <= 0:
        raise ValueError("WINDOW_OVERLAP_WORDS must be smaller than MAX_WORDS")
    pieces, start = [], 0
    while True:
        end = min(start + MAX_WORDS, len(words))
        pieces.append(text[words[start].start():words[end - 1].end()])
        if end == len(words):
            return pieces
        start += step


def chunk_document(text: str, source_file: str = "") -> list[Chunk]:
    lines = text.split("\n")
    header = parse_header(lines)
    body = _clean(lines)
    heads = _headings(body)
    chunks: list[Chunk] = []
    previous = ""
    for k, (idx, num, title) in enumerate(heads):
        end = heads[k + 1][0] if k + 1 < len(heads) else len(body)
        section_text = re.sub(r"\n{3,}", "\n\n", "\n".join(body[idx + 1:end])).strip()
        if not section_text:
            continue
        for part, piece in enumerate(_sliding_window(section_text), start=1):
            # The first window borrows the last sentence of the previous section.
            # Later windows already overlap with their neighbour in their own text.
            context = _sentences_tail(previous, OVERLAP_MAX_WORDS) if part == 1 else ""
            chunks.append(Chunk(section=num, title=title, text=piece, part=part, context_before=context,
                                source_file=source_file, **header))
        previous = piece
    return chunks
