"""A pending clarification, and the user's short answer to it ("2", "التاني", "the second", a product name).

After a list of choices ("which order?", "which return?") the agent keeps ONE small card in memory (app/memory.py): the
intent that asked, the reason, the round, and the choices (label + real id). When the next message is only a bare reference
to one of them, the CODE picks it and continues the intent: no model call. Anything else is a new request.

Pure functions, no I/O. The words of the lost-context answer live in chat.py.
Design: D61 (shown-list mapping, pending clarification), D65 (a bare reference with no memory is not a failed attempt).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .chat import normalize

# Reasons that can be answered by picking from a list, and which argument the pick fills.
RESOLVABLE = {"missing_order_id": "order_ref", "which_return": "return_id"}
ORDER_REF_PREFIX = "order_ref_c"             # the Gateway maps order_ref_c1, order_ref_c2 ... to the real ids of the choices

_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_ORDINALS = {
    1: ("الاول", "الاولي", "اول", "اولها", "الاول ده", "اول واحد", "first", "the first", "1st", "first one", "the first one"),
    2: ("التاني", "التانيه", "تاني", "تانيها", "التاني ده", "second", "the second", "2nd", "second one", "the second one"),
    3: ("التالت", "التالته", "تالت", "تالتها", "third", "the third", "3rd", "third one", "the third one"),
    4: ("الرابع", "الرابعه", "رابع", "fourth", "the fourth", "4th"),
    5: ("الخامس", "الخامسه", "خامس", "fifth", "the fifth", "5th"),
}
_WORD_TO_NUMBER = {w: n for n, words in _ORDINALS.items() for w in words}
_NUMBER = re.compile(r"(?:رقم |number |no |n )?(\d{1,2})")


def _text(message: str) -> str:
    return normalize(message.translate(_ARABIC_DIGITS))


def bare_number(message: str) -> int | None:
    """The 1-based position the message points at when it is ONLY a number or an ordinal word, else None."""
    text = _text(message)
    if m := _NUMBER.fullmatch(text):
        return int(m.group(1))
    return _WORD_TO_NUMBER.get(text)


def _product(label: str) -> str:
    return _text(label.split("·")[0])


@dataclass(frozen=True)
class Choice:
    label: str
    ref: str


def choices_of(pending: dict) -> tuple[Choice, ...]:
    return tuple(Choice(c["label"], c["ref"]) for c in pending.get("choices", []))


def pick(message: str, pending: dict) -> int | None:
    """The 0-based index of the choice the message selects, or None (a new request, or an out-of-range number).
    A product name counts only when it is in the message and exactly one choice has it, in a short message."""
    choices = choices_of(pending)
    number = bare_number(message)
    if number is not None:
        return number - 1 if 1 <= number <= len(choices) else None
    text = _text(message)
    if not text or len(text.split()) > 8:
        return None
    hits = [i for i, c in enumerate(choices) if _product(c.label) and _product(c.label) in text]
    return hits[0] if len(hits) == 1 else None


def card_from(intent_id: str, reason: str, round_: int, choices: list[dict]) -> dict:
    """The card the clarify node leaves for the Gateway to store. Labels and ids only, never message text (D64)."""
    return {"intent": intent_id, "reason": reason, "round": round_,
            "choices": [{"label": c["label"], "ref": c["ref"]} for c in choices]}


def order_refs_for(pending: dict | None) -> dict[str, str]:
    """For a pending "which order": {order_ref_c1: real id, ...}, so the plan can resolve the pick like any order ref."""
    if not pending or pending.get("reason") != "missing_order_id":
        return {}
    return {f"{ORDER_REF_PREFIX}{i}": c.ref for i, c in enumerate(choices_of(pending), start=1)}


def arguments_for(pending: dict, index: int) -> dict[str, str]:
    """The intent argument that the picked choice fills."""
    argument = RESOLVABLE[pending["reason"]]
    if argument == "order_ref":
        return {"order_ref": f"{ORDER_REF_PREFIX}{index + 1}"}
    return {"return_id": choices_of(pending)[index].ref}


def valid(card: object) -> bool:
    """Is this a card this code wrote? Anything else read from memory is thrown away (a missing or odd card = fresh start)."""
    if not isinstance(card, dict) or card.get("reason") not in RESOLVABLE or not isinstance(card.get("intent"), str):
        return False
    choices = card.get("choices")
    return (isinstance(card.get("round"), int) and isinstance(choices, list) and 0 < len(choices) <= 10
            and all(isinstance(c, dict) and isinstance(c.get("label"), str) and isinstance(c.get("ref"), str) for c in choices))
