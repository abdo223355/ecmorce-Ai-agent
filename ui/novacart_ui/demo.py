"""Demo mode: answers RECORDED from the real system, so the chat screen can be shown on a free host with no backend,
no gateway, no database and no model key.

Nothing here talks to a service. The recordings (ui/demo/recordings.json) were made by sending real questions through the
real /chat with the demo accounts; each one keeps the Gateway's result exactly as it was sent, and the screen renders it with
the same code as the live screen (`render_reply`). A question that was not recorded gets an honest "not in this demo" answer.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .api import ChatReply, SegmentView

RECORDINGS = Path(__file__).resolve().parent.parent / "demo" / "recordings.json"

_DIACRITICS = re.compile("[ً-ْـ]")           # harakat and tatweel
_PUNCTUATION = re.compile(r"[?؟!.,،]")
_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي"})


def normalize(text: str) -> str:
    """Compare typed text with recorded text: case, punctuation, harakat and alef forms do not matter."""
    text = _DIACRITICS.sub("", text).translate(_ALEF)
    return " ".join(_PUNCTUATION.sub(" ", text).casefold().split())


@dataclass(frozen=True)
class Recording:
    account: str
    role: str                 # "customer" or "worker"
    group: str                # cancel, return, exchange, ... or "common" (any account of the same role may ask it)
    message: str
    result: dict              # the Gateway's result, as it was sent


class DemoStore:
    def __init__(self, items: list[Recording], recorded_on: str):
        self.items, self.recorded_on = items, recorded_on

    @classmethod
    def load(cls, path: Path = RECORDINGS) -> "DemoStore":
        doc = json.loads(path.read_text(encoding="utf-8"))
        items = [Recording(i["account"], i["role"], i["group"], i["message"], i["result"]) for i in doc["items"]]
        return cls(items, doc["recorded_on"])

    def accounts(self) -> list[tuple[str, str]]:
        """(account, role) in the order they were recorded; 'common' recordings do not make an account."""
        seen: dict[str, str] = {}
        for item in self.items:
            seen.setdefault(item.account, item.role)
        return list(seen.items())

    def _visible(self, account: str) -> list[Recording]:
        role = dict(self.accounts()).get(account)
        return [i for i in self.items if i.account == account or (i.group == "common" and i.role == role)]

    def suggestions(self, account: str) -> list[str]:
        """The questions that can be asked as this account, without repeats."""
        seen, out = set(), []
        for item in self._visible(account):
            if item.message not in seen:
                seen.add(item.message)
                out.append(item.message)
        return out

    def answer(self, account: str, message: str) -> ChatReply | None:
        """The recorded answer for this account, or None when the question was not recorded."""
        wanted = normalize(message)
        for item in self._visible(account):
            if normalize(item.message) == wanted:
                return reply_from(item.result)
        return None


def reply_from(result: dict) -> ChatReply:
    segments = [SegmentView(s["part_index"], s["kind"], s.get("template_id"), s.get("text"),
                            s.get("render_values") or {}, s.get("cited") or []) for s in result["segments"]]
    return ChatReply(segments, result.get("handoff_reason"), result.get("priority"), 0.0, result)
