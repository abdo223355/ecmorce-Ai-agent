"""Minimal ingress scrub (D107, first slice): a typed order number never reaches the model.

"where is order NC-100010" becomes "where is order {order_ref_1}" and the map {"order_ref_1": "NC-100010"} goes to
AgentContext.order_refs. Only the code holds the real id (D58, D60-A1). The same number twice gets the same ref.

Not covered yet (Milestone 2, the rest of D107): phone numbers, emails, card numbers, addresses.
"""
from __future__ import annotations

import re

# POL-AGV-001 §2: "NC-" followed by digits (6 in our backend). "NC 100010" and "nc100010" are accepted as typed by people.
ORDER_NUMBER = re.compile(r"(?<![A-Za-z0-9])NC[-\s]?(\d{6})(?!\d)", re.IGNORECASE)
MAX_REFS = 5                                  # more distinct numbers than this: the rest stay as plain text for the model


def scrub_order_numbers(message: str) -> tuple[str, dict[str, str]]:
    """The message with each order number replaced by {order_ref_N}, and the map ref -> real id (upper case, NC-dddddd)."""
    refs: dict[str, str] = {}
    by_id: dict[str, str] = {}

    def replace(m: re.Match) -> str:
        real = f"NC-{m.group(1)}"
        if real not in by_id:
            if len(by_id) >= MAX_REFS:
                return "{order_ref_overflow}"                 # not in the map: the classify rejects it and the user is asked again
            by_id[real] = f"order_ref_{len(by_id) + 1}"
            refs[by_id[real]] = real
        return "{" + by_id[real] + "}"

    return ORDER_NUMBER.sub(replace, message), refs
