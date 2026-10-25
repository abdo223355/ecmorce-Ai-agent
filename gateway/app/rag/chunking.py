"""Chunking rule (D47): one chunk per numbered policy section, plus a small overlap.

Input is the text of ONE policy PDF as `pdftotext -layout` prints it (tables keep their row order). Pure functions,
no file or network access, so they are easy to test. Reading the PDF is ingest.py's job.

Known limits (to handle in ingest / later):
- Tables come out of the PDF as scrambled text; a table stays inside its section, but its cells are not aligned.
- Glossary "one chunk per row" (D47) needs real table extraction; here the Glossary is chunked like any section.
"""
from __future__ import annotations

import re

from .models import Chunk

# TODO(عبدالرحمن): قاعدة الـ overlap. دي بتاعتك: الوحدة (جمل ولا كلمات) والحد الأقصى.
#   Hint: الأقسام عندنا قصيرة (الوسيط ~41 كلمة)، فأي رقم كبير بيبقى نص القسم تكرار.
#   الـ overlap بيدخل في نص الـ embedding بس (context_before)، مش في النص اللي بيتعرض ويتستشهد بيه.
OVERLAP_MAX_WORDS = 15      # PROPOSAL: آخر جملة من القطعة اللي قبل، بحد أقصى 15 كلمة

# PROPOSAL (not in the design): safety cap. The longest section measured is ~308 words.
MAX_WORDS = 400

# DECISION (عبدالرحمن): a section longer than MAX_WORDS is cut with a SLIDING WINDOW (not at paragraphs).
# TODO(عبدالرحمن): حجم التداخل بين نافذتين. PROPOSAL: 50 كلمة (~12% من النافذة).
#   التداخل هنا جوه نفس القسم، فالاستشهاد بـ § مش بيتأثر، ويقدر يبقى أكبر من الـ 15 كلمة بتوع context_before.
WINDOW_OVERLAP_WORDS = 50

# TODO(عبدالرحمن): الأقسام القصيرة جداً (< 25 كلمة، 51 من 200): ندمجها مع اللي قبلها ولا نسيبها؟
#   دلوقتي مش بندمج (الاستشهاد بـ § يفضل دقيق). لو قررت تدمج، التعديل في chunk_document.

_HEADER = re.compile(r"^NovaCart Document (\S+) - Version (\S+) - Status: (\S+)")
_HEADING = re.compile(r"^(\d{1,2})\.\s+([A-Z][^\n]{1,100})$")
_EMBEDDED_NUMBER = re.compile(r"\s\d{1,2}\.\s")       # "1. Purpose 2. Terms" = a table-of-contents line
_NOISE_PREFIXES = ("NOVACART - SYNTHETIC", "NovaCart |")
_PAGE = re.compile(r"^Page \d+$")


def parse_header(lines: list[str]) -> dict:
    """doc_id, version, status from the 'NovaCart Document X - Version Y - Status: Z' line,
    title from the line above it, audience tags from the metadata block."""
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
    """Look for the audience names in the metadata block (between 'Document Metadata' and 'Table of Contents').
    Works on both plain and -layout text, where the label / value columns come out in a different order."""
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
    """Drop the repeated page banner, page footer and page numbers; squeeze the wide gaps -layout leaves."""
    return [re.sub(r"[ \t]{2,}", " ", l).strip() for l in lines
            if not l.startswith(_NOISE_PREFIXES) and not _PAGE.match(l.strip())]


def _headings(lines: list[str]) -> list[tuple[int, str, str]]:
    """(line index, number, title) of the real section headings: the longest run 1, 2, 3, ... of whole-line
    headings. This skips the table of contents and numbered steps inside a section."""
    runs: list[list[tuple[int, str, str]]] = []
    for i, line in enumerate(lines):
        m = _HEADING.match(line.strip())
        # a heading is a short title: a numbered STEP is a sentence that ends with a period
        if not m or _EMBEDDED_NUMBER.search(m.group(2)) or m.group(2).rstrip().endswith((".", ";", ":")):
            continue
        num, title = int(m.group(1)), m.group(2).strip()
        if num == 1:
            runs.append([(i, "1", title)])
            continue
        # continue the most recent run that is waiting for this number
        for run in reversed(runs):
            if int(run[-1][1]) == num - 1:
                run.append((i, str(num), title))
                break
    return max(runs, key=lambda r: (len(r), r[0][0])) if runs else []


def _sentences_tail(text: str, max_words: int) -> str:
    """Last sentence of `text`, cut to its last `max_words` words. "" when the text does not end with a
    sentence (e.g. it ends with a table row): overlap from a table row would be noise."""
    if not re.search(r"[.!?][\"')]*$", text.strip()):
        return ""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    if not sentences:
        return ""
    return " ".join(sentences[-1].split()[-max_words:])


def _sliding_window(text: str) -> list[str]:
    """Cut a section longer than MAX_WORDS into windows of MAX_WORDS words that move by
    (MAX_WORDS - WINDOW_OVERLAP_WORDS) words, so neighbouring windows share WINDOW_OVERLAP_WORDS words.
    Slices the original string between word positions, so line breaks (table rows) are kept."""
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
            # part 1 borrows the last sentence of the previous section; later windows already overlap in their text
            context = _sentences_tail(previous, OVERLAP_MAX_WORDS) if part == 1 else ""
            chunks.append(Chunk(section=num, title=title, text=piece, part=part, context_before=context,
                                source_file=source_file, **header))
        previous = piece
    return chunks
