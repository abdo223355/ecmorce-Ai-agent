# Problems we found, and what we changed

This file is the short, honest version of `PROGRESS.md`: each problem the project met after the first working
version, how it was found, what was changed, and the numbers before and after. Nothing here is a claim that the agent
is finished. The last section lists what is still weak.

How the numbers were produced (all re-runnable, all through the real `/chat` and the real models):

| Script | What it measures |
|---|---|
| `gateway/evals/quality_eval.py` | 52 natural messages (greetings, typed order numbers, free text, safety, out of scope). The acceptable answers were written down before each run. |
| `gateway/evals/stability_eval.py [N] [parallel]` | the same messages sent N times, to see which answers are not stable. |
| `gateway/evals/classify_eval.py [passes] [held]` | 72 messages with the expected intent and safety; plus 18 held-out messages written after the prompt was tuned. |

The first lesson: **a green test suite did not mean the agent was useful.** 344 to 391 tests with fake models passed
while "hi" answered "I could not finish". The tests proved the machinery; only natural messages through the real
system showed the quality problem.

---

## 1. "hi" got "I could not finish" (quality 45%)

- **Found by:** a first run of 51 natural messages: 23 acceptable = 45%. A greeting, thanks, goodbye, "who are you"
  and "help" all ended in the generic failure text.
- **Cause:** the classifier found no request in a greeting (zero parts) and an empty turn became template 18.
- **Changed:** small talk is answered by plain code (`gateway/app/agent/chat.py`), no model call. The whole message must
  be small talk: "hi my account was hacked" is not, so a safety message that starts like a greeting still goes to the
  classifier. A model answer with zero parts now gives a friendly "I did not understand" with what the agent can do.
- **After:** greetings 13/13 (were 0/13), "who are you / help" 4/4 (were 0/4); overall 40/51 = 78%.

## 2. A typed order number was not understood

- **Found by:** the same evaluation: "where is order NC-100010" ended in the "could not understand" template.
- **Cause:** the ingress scrub (design D107) was not built, so `/chat` sent an empty order-reference map and the safety
  check rejected the model's reference.
- **Changed:** `gateway/app/scrub.py` replaces a typed order number by a placeholder (`{order_ref_1}`) before the agent
  sees it; only the code keeps the real id. The classifier prompt tells the model about the placeholder.
- **After:** typed order number 3/3 (was 0/3). One of the test orders belongs to another customer; the right answer there
  is "not found" (template 14), and the evaluation now checks that case separately instead of counting it as a failure.
- **Still open:** the rest of the scrub (phones, emails, card numbers, addresses).

## 3. Some intents had no plan, so the user got "could not finish"

- **Found by:** messages such as "can I return this?", "can I cancel after shipping?", "the customer is not answering".
- **Cause:** return, exchange and cancellation eligibility (C2, C5, C9), a missing order (C11) and two worker problems
  (W6, W7) had no row in the plan table. The eligibility check itself is code that is not built yet.
- **Changed:** these intents now hand off honestly to a person (customer: template 5; worker: template 6, reason
  `PENDING_OWNER`, no invented priority). The agent does not guess a yes or a no. A test pins that every intent of both
  roles has a row.
- **After:** 87% -> 92% right after the change. The evaluation was then corrected in two places, openly: cancellation
  after shipping now belongs to an "eligibility" group where the honest handoff is the right answer, and a clarifying
  question counts as acceptable for "the address is wrong". With those, 96%. So part of that gain is a changed
  expectation, not only a better agent.

## 4. Slow and failing model calls

- **Hidden reasoning** made some models slow. It is switched off for classify and reply (reasoning "none").
- **Measured wrongly at first:** whole-request times taken with Python against `localhost` on Windows included about
  2 s of IPv6 fallback; with `127.0.0.1` the real whole-request p50 is about 1.3 to 2 s. The early numbers were corrected.
- **Time limits changed from measurements (not by feel):** the reply cap went from 2.0 s to 2.5 s after 30 calls showed
  p95 2.37 s; the classify cap from 1.0 s to 3.0 s because no model had p95 under 1 s in the container.
- **One retry after a timeout:** a call that times out is tried once more while the request still has time. First
  attempts are classify 2.4 s and reply 2.0 s, chosen just above p95 of the successful calls (classify p50 1.27 / p95 2.34,
  reply p50 1.24 / p95 2.12). Worst case 7.6 s inside the 8 s budget (pinned by a test).
- **What the measurement showed:** with 4 requests in parallel, many calls timed out twice; with one request at a time
  only 1 did and 7 were saved by the retry. Most of the earlier timeouts came from the load of the measuring script.
- **After:** whole path 93.8% (4 parallel) -> 96.9% (one at a time, 5 runs of each message).

## 5. Written answers thrown away without a reason

- **Found by:** policy questions sometimes ended in "could not finish" although the model had answered.
- **Cause:** the reply check refuses an empty answer, an unknown placeholder, a citation it was not given, or a policy
  answer with no citation, and it did not record which.
- **Changed:** the reason word (`empty_text`, `foreign_placeholder`, `cites_unknown_section`, `no_citation`) is logged
  and kept in the telemetry. Never the message text.
- **What it showed:** my first guess ("mostly missing citations") was only partly right; time was the bigger cause.

## 6. The classifier prompt was two sentences

- **Found by:** a new classification test (72 messages, expected intents decided first). The old prompt got 137/144 =
  95.1%; every miss was a worker boundary: "the customer is not answering" filed as dispatch instead of a delivery
  issue, a procedure question filed as a delivery issue, "the address is wrong" filed as shipment details.
- **Changed:** the prompt now says what each field means, when a message is P1 (account takeover, data exposure,
  physical danger), that unused fields stay empty, and how close intents differ (a question about a rule vs a request
  to act vs an eligibility question; a delivery problem vs damaged goods vs asking for dispatch).
- **After:** 142/142 answered = 100% on the same set. Because the prompt was tuned on those misses, 18 new messages
  written afterwards were run 3 times: 54/54. Small sets: this means "no problem found", not "perfect". Classify
  latency did not change (p50 1.29 s vs 1.27 s).

## 7. The screen showed raw codes

- **Found by:** looking at the chat screen after the agent fixes above. The order-status answer read
  "... is: Processing. Last updated: 2026-10-22T08:09:29+03:00." (an English code and a raw ISO date, jumbled by the
  right-to-left text).
- **Changed:** `ui/novacart_ui/texts.py` now shows a status as a word (Arabic draft wording) and a date as
  "22 Oct 2026 at 08:09" / "22 أكتوبر 2026 الساعة 08:09". A value it does not recognise is shown unchanged, never guessed.
- **After:** checked on the real screen with a test account; 51 ui tests pass (2 new).

## 8. "Return status" said "not found" although the customer had returns

- **Found by:** the owner looked at the database: the test customer has 22 orders and 2 returns, yet the "return status"
  button answered "not found". Earlier I had called that answer "arguably right" without checking the data: that was wrong.
- **Cause:** with no order number the agent looked only through the five newest orders. The two returns belong to older
  orders. The backend had no endpoint that lists a customer's returns.
- **Changed (owner approved the backend change):** a sixth read-only endpoint, `GET /customer/returns` (the caller's own
  returns, newest first, at most 20, no internal fields), a gateway tool `my_returns`, and the "return status" plan now
  reads that list in one call instead of walking five orders. With two returns it asks which one, with the list.
- **After:** the test customer asking by return number gets the right status (Refunded, Received); "my return status"
  asks which of the two. 3 new backend tests (own returns only, newest first, token required) and 10 gateway tests changed
  or added. Quality set: 51/52.
- **Design note:** the original design had five data endpoints (D25); this is a sixth, added because the answer could not
  be right without it.

## 9. "Where is my order?" asked a question nobody could answer

- **Found by:** the owner's demo account has 22 orders, so "where is my order?" always answered "which order?". And
  the agent cannot continue after a list of choices (typing "2" is not understood: there is no conversation memory yet),
  so the question was a dead end.
- **Changed (the owner chose this option out of three):** with no order number and no product word, the agent reads the
  recent-orders list it already fetched (no extra backend call). One order on the way -> its status. Several -> a short
  list with each status and last update, no question. None on the way -> the only recent order if there is exactly one,
  else it asks for the number. "On the way" means the statuses Shipped and Out for Delivery. The recent-orders limit went
  from 5 to 10. Real values are placeholders filled by code (the model never sees them); the list wording is a draft.
- **After:** the demo account gets its three orders on the way in 0.1 s (no model call); 52/52 on the quality set in the last
  run (single runs vary by a point or two). 8 new gateway tests, 1 new ui test.

## 10. The agent could not understand "2" after its own list

- **Found by:** a question like "which return?" shows a numbered list, but typing "2" was not understood: the agent kept no
  memory of the conversation between messages. The list was a dead end.
- **Changed (design D61 to D65, first slice only):** a small card in Redis per chat (key = a hash of owner + login
  session, 30 minutes from the last turn, never message text, names, phones or tokens). Today it holds only the pending
  question: the intent, the reason, the round, and the shown choices (label + real id). The next message is checked by
  code: if it is only "2", "التاني", "the second" or a product name that exactly one choice has, the agent
  continues the saved intent with the chosen id (no model call, about 0.05 s). Anything else is a new request and the old
  card is dropped. A bare "2" with nothing in memory (a new login, an expired or replaced card) gets "I do not have that
  list any more" and is not counted as a failed attempt. Redis down or slow means a fresh start, never an error. The number
  of times the same question was asked is now counted across turns, so the 3-round limit works.
- **After:** two real turns on the demo account: "return status" lists the two returns, "2" answers with the status of the
  second one in 0.05 s; a new login or an unrelated question in between makes "2" a lost-context answer. 58 new tests.
- **Not in this slice:** cards of the last turns, the code-built summary for "why?" follow-ups, deleting the card at logout
  (it expires by itself).

## 11. "Can I cancel?" was always passed to a person

- **Found by:** the demo account's buttons: five of nine ended with a person, and cancellation was one of the cases that
  could be decided by code from the policy (POL-CAN-001 v2.0, which says Pending and Confirmed orders can be cancelled,
  Packed, Shipped and Out for Delivery cannot, Delivered is a return, and Processing always needs a Customer Service review).
- **Changed:** the first piece of the business rules (design box 5), `gateway/app/rules/cancellation.py`: the policy table as
  structured values with its section and version, and a pure function from the validated order (never the customer's
  words) to a verdict. The answer is chosen by code (no model call), with typed placeholders for the values and the policy
  section cited. The agent only explains: it never cancels (policy section 1). A verdict that needs a person (Processing, a
  custom-made item, a pre-order, a gift card, Failed Delivery, an unknown status) says why and then hands off. With no order
  number it asks which order, and the answer "2" is understood (memory).
- **What the data cannot show, so it is a review and not a guess:** the 4-hour window (the order endpoint does not give
  `processing_started_at`, and there is no packing time), the release date of a pre-order, whether production or a gift card
  code has started or been issued.
- **After:** all nine statuses of the demo account's orders checked live; the Pending order that has a pre-order item goes to a
  person (the flag is in the data), the Processing one gets the review words and the acknowledgement, the Shipped one the
  refusal-at-the-door words. Quality set: 53/54 in the run before the last expectation fix. 33 new tests.
- **Two corrections made in this step:** the review texts repeated "I passed it to an agent" right before the
  acknowledgement said the same, so the repeat was removed; and the evaluation's expectations were updated (a cancellation
  question with no number now asks which order; an order in Processing correctly ends with a handoff).
- **Still to do:** none of the three: returns are point 12 and exchanges point 13.

## 12. "Can I return this?" was always passed to a person

- **Found by:** the same demo-account buttons. Return eligibility (POL-RET-001 v2.1) is mostly arithmetic on the delivery
  date and the item's category and flags, so code can decide it.
- **Changed:** `gateway/app/rules/returns.py`: the policy as structured values (30 days; 15 for electronics; 30 for a
  defective or wrong item in any returnable category; gift cards never; custom-made and Final Sale only if defective; the
  holiday extension to 2027-01-31, the longer window winning) and a pure function from the validated order to a verdict per
  item. The window counts the Cairo calendar day of delivery and ends at 23:59 Cairo time on the last day. The condition of
  the item (unused, unopened, sealed) and whether it is defective are things the data cannot show, so they are told to the
  customer as the policy's condition and are not decided. An order with several items gets one line per item (no question
  that could be a dead end), or only the item the customer named. An order not yet delivered is told it cannot be returned
  yet and pointed at cancellation; Failed Delivery, a missing delivery date and an unknown category go to a person. With no
  order number the agent asks which order, listing only the DELIVERED orders, and "2" is understood.
- **After:** the demo account's seven delivered orders checked live against today's date: electronics inside 15 days (with the
  defect date), beauty (sealed), a home item three days from its last day, an electronics item at day 22 (only if defective),
  expired items (with "only Customer Service can grant an exception"), a Final Sale router, a three-item order, and a shipped
  order (not delivered yet). 45 new tests, including the edges: day 30 and day 31, electronics day 15 and 16, the Cairo day
  of a late-evening delivery, and the holiday window.
- **Not decided by the code:** the item's condition, defects, stock, exceptions (only Customer Service grants those).

## 13. "Can I exchange this?" was always passed to a person

- **Found by:** the last of the three eligibility questions that code can decide (POL-EXC-001 v1.1).
- **Changed:** `gateway/app/rules/exchange.py`: 14 calendar days from the Cairo day of delivery for an ordinary exchange; a
  WRONG item delivered is exchanged free within 30 days; electronics are exchanged only if defective, like-for-like, within 30
  days; gift cards are never exchanged; beauty and custom-made are not exchanged for a size or colour but a WRONG item is exchanged
  within 30 days (a decision, see docs/ELIGIBILITY_DECISIONS.md); Final Sale only if defective or wrong; the holiday window to
  2027-01-15 with the longer window winning. Each item of the order gets a line. The answer says an exchange is not a return,
  and, when an exchange can go ahead, the policy's conditions: the variant must be in stock when it is processed (not in the
  data, so it is a condition), a price difference is paid or given as store credit, and what to do if the variant is
  unavailable (another variant, a waiting list of up to 7 days, or a return). A past-window item points at the return
  question. One shared builder now serves returns and exchanges.
- **After:** checked live on the demo account (a toy delivered two days ago is an eligible exchange until the 16th; electronics
  only if defective; beauty not exchangeable; a pan at day 27 only if the wrong item was sent; old orders expired) and in English.
  45 new tests. All three eligibility questions are now decided by code.
- **A data gap found and not hidden:** the policy treats "electronics and small appliances" alike, but the backend category
  "home" also holds small appliances (for example an air fryer). The category alone cannot tell them apart, so they are treated
  as ordinary home goods in both returns and exchanges. The backend owner should add a subcategory or a flag.

## 14. Security and operations (found by reviewing our own work)

- Several admin accounts (one per person, scrypt hashes, lock after 5 wrong passwords, idle logout) replaced a shared
  password; a least-privilege database role limits what the admin screens can read or change.
- Database owner passwords that were written in clear text in files were replaced by long random values in `.env`
  (not tracked); the compose file refuses to start without them. The old values were checked to be refused.
- `/dev/tools` is off by default. A handoff is written to the database before the user is told it was made; closing a
  case erases the stored ids.
- A static fallback text with the service hours and phone numbers (from `.env`, never invented) is used when a handoff
  cannot be recorded.

---

## 15. The test data went stale, and two of my test phrasings were wrong

- **Found by:** trying the system by hand on 2026-11-04. The seed was made on 2026-10-22, so "delivered 14 days ago" had
  become 27 days: every window-edge case (the 14/15/16-day electronics orders, the 29/30/31-day apparel orders) had moved,
  and the answers looked right but no longer sat on the edge they were built for.
- **Also found:** "I want to cancel NC-100014" is handed to a person, by design (it asks to ACT, intent C8), while "can I
  cancel NC-100014?" asks about eligibility and gets the answer. The example phrases given to the owner for testing used the first
  form, so they never reached the new cancellation answers.
- **Changed:** the data was re-seeded for the day (the seed is relative to "now"), the README now says to re-seed on a later
  day and gives the two commands, and it lists the phrasing difference with example questions.
- **After:** NC-100001 (electronics) is again on its edge: "15 days, until 2026-11-05, unopened; defective or wrong until
  2026-11-20".
- **Lesson:** edge-case test data should either be generated relative to the day it is used, or carry a visible "made on" date.

## Still weak (known, not fixed)

- Eligibility is built for cancellation, return and exchange. Gaps: small appliances in the "home" category, the item's condition,
  stock for exchanges and the 4-hour cancellation window are not in the data, so they are conditions or a review, never a guess.
- Only order numbers are scrubbed at ingress. The rest of the personal-data scrub and the final output validation
  are not built.
- Memory is only the first slice (a pending list). There are no cards of earlier turns yet, so a follow-up like "why?"
  about the last answer is not understood from memory.
- A known admin name can be locked for 15 minutes by 5 wrong tries; no TLS (local only).
- The quality sets are small (52 and 72 messages). More Franco, long, and three-requests-in-one messages are needed.
- About 3 to 4% of requests still fail on a model timeout or a refused reply.
- Several wordings (templates, small talk, fallback text) are drafts waiting for the owner's wording.
