"""⑤ Business Rules, built one policy at a time. Pure code: no model, no network, no clock unless a rule needs the date.

Each module holds the rules of ONE policy document as structured values, each with the document, section and version it
comes from, and one function that turns a validated order (never the user's words) into a Verdict. When a fact the rule
needs is not in the data the agent receives, the verdict is "review" (a person decides): the code never guesses (D44).

Done: cancellation (POL-CAN-001 v2.0). Not yet: return (POL-RET-001), exchange (POL-EXC-001).
"""
