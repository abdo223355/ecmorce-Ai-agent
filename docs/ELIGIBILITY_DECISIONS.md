# Eligibility decisions (cancellation, return, exchange)

The three eligibility checks are code in `gateway/app/rules/` (one module per policy): `cancellation.py` (POL-CAN-001 v2.0),
`returns.py` (POL-RET-001 v2.1) and `exchange.py` (POL-EXC-001 v1.1). The policy PDFs are synthetic documents of this fictional
company. Where a PDF is silent or can be read two ways, the project owner delegated the call to the coding assistant
(Claude Code), acting as the company owner (2026-11-04). Those decisions are listed here so nobody mistakes them for
official policy. Each one is a few lines in the named module and can be reversed there.

Confirmed by the project owner against the PDF (2026-11-04): all the cancellation rules, and the return rules as listed in
`returns.py`.

## Decisions taken under delegation, where the policy is silent

| # | Decision | Where | Why it is a decision |
|---|---|---|---|
| 1 | A wrong item (a different product than ordered) in **beauty** or **custom-made** is exchanged free within 30 days. Gift cards and digital goods are never exchanged. | `exchange.py`, `check_item` | POL-EXC-001 section 3 says these categories are "not exchangeable"; section 6 says a wrong item delivered is exchangeable within 30 days with no category exception. |
| 2 | For a Final Sale / Clearance item, a **defective** one is exchanged within the general 14 days and a **wrong** one within 30 days. | `exchange.py` | The PDF gives a time only for wrong items (30 days) and for defective electronics (30 days). |
| 3 | The holiday window (to 2027-01-15 for exchange, to 2027-01-31 for return) is applied as "the longer window wins" to **every** window of the order, including the 30-day defective and wrong-item windows. | `returns.py`, `exchange.py`, `window_end` | The PDFs extend "the window"; the design (audit #3) says the longer window applies. |
| 4 | A **Cancelled** order is "not delivered", so it cannot be returned or exchanged. | `returns.py`, `exchange.py`, `BEFORE_DELIVERY` | Both policies require the status Delivered. |
| 5 | An **unknown category**, a missing `delivered_at` and a status the code does not know go to a person. | all three | The code never guesses (design D44). |
| 6 | **Small appliances** in the backend category `home` (for example an air fryer) are treated as ordinary home goods (30-day return, 14-day exchange). | `returns.py`, `exchange.py` | The policies treat "electronics and small appliances" alike, but the data has no subcategory. The backend owner should add one. |
| 7 | An exchange request past its window points the customer to the return question. | `exchange.py` | The policy's own example says a return may still be possible. |
| 8 | A pending cancellation of an order with a custom-made item, a pre-order or a gift card goes to a person. | `cancellation.py` | Production start, release date and code issue are not in the data. |

## What the code never decides (told to the customer as the policy's condition)

- The condition of the item (unused, unopened, sealed) and whether it is defective or wrong.
- The stock of an exchange variant, and an earlier exchange on the same order line.
- Exceptions: only Customer Service grants them.
- The 4-hour cancellation window of a Processing order (the order endpoint does not give `processing_started_at`; the policy
  sends Processing requests to Customer Service anyway).

## Still a draft

The Arabic and English wording of all the answers is a draft that the project owner is still reviewing.
