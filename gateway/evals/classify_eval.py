"""Classify accuracy: each message goes through the real classify node (real model) and the intents/safety it found are
compared with what was decided BEFORE the run. Run inside the gateway image (needs the model key):

    docker compose run --rm --no-deps -e PYTHONPATH=/app --entrypoint python -v ./gateway:/app -w /app gateway evals/classify_eval.py [passes]

Expected = list of sets, one per request in the message; each set holds the acceptable intent ids and some part must
match it. "P1" in the label means some part must have safety P1; every other message must have NO P1 part (a false alarm
costs a human's time). Small talk is not here (it never reaches the model). Typed order numbers go through the scrub.
"""
import asyncio
import sys
import time
from collections import Counter

from app.agent import AgentContext
from app.agent.classify import classify_node
from app.agent.state import AgentState
from app.scrub import scrub_order_numbers

C, W = "customer", "worker"
# (role, message, expected sets of acceptable intents, p1?)
CASES = [
    # --- C1 order status
    (C, "فين طلبي", [{"C1"}], False), (C, "طلبي اتأخر", [{"C1", "C10"}], False), (C, "where is my order", [{"C1"}], False),
    (C, "حالة الاوردر NC-100012", [{"C1"}], False), (C, "هو الاوردر بتاعي اتشحن؟", [{"C1"}], False),
    (C, "feen talabi", [{"C1"}], False), (C, "الساعة كام هيوصل الاوردر", [{"C1"}], False), (C, "اخر طلب عملته وصل؟", [{"C1"}], False),
    (C, "what's the status of my last order", [{"C1"}], False), (C, "hi فين طلبي", [{"C1"}], False),
    # --- C2 return eligibility / C3 return status / C5 exchange
    (C, "عايز ارجع منتج", [{"C2", "C8"}], False), (C, "هل ينفع ارجع الموبايل", [{"C2"}], False), (C, "can I return my watch", [{"C2"}], False),
    (C, "المنتج جالي مكسور ينفع ارجعه", [{"C2", "C10"}], False),
    (C, "حالة المرتجع", [{"C3"}], False), (C, "فين المرتجع بتاعي", [{"C3"}], False), (C, "return status", [{"C3"}], False),
    (C, "الفلوس بتاعت المرتجع هترجع امتى", [{"C3", "C4"}], False),
    (C, "عايز استبدل المنتج", [{"C5", "C8"}], False), (C, "can I exchange this for a bigger size", [{"C5"}], False),
    # --- C4 policy questions
    (C, "سياسة الاسترجاع ايه", [{"C4"}], False), (C, "الشحن بكام", [{"C4"}], False), (C, "how long does delivery take", [{"C4"}], False),
    (C, "do you accept cash on delivery", [{"C4"}], False), (C, "ايه مدة الضمان", [{"C4"}], False), (C, "what is the return window", [{"C4"}], False),
    # --- C6 human, C10 complaint
    (C, "عايز اكلم موظف", [{"C6"}], False), (C, "I want to speak to a person", [{"C6"}], False), (C, "كلمني حد", [{"C6"}], False),
    (C, "عايز اقدم شكوى", [{"C10"}], False), (C, "الخدمة وحشة", [{"C10"}], False), (C, "I want to complain about the courier", [{"C10"}], False),
    # --- C7 safety (P1)
    (C, "حد دخل حسابي", [{"C7"}], True), (C, "someone stole my card", [{"C7"}], True), (C, "حسابي اتهكر", [{"C7"}], True),
    (C, "I think my account was hacked", [{"C7"}], True), (C, "شفت بيانات ناس تانية في حسابي", [{"C7"}], True),
    (C, "المندوب هددني وحاول يضربني", [{"C7"}], True), (C, "hi حد دخل على حسابي وغير الباسورد", [{"C7"}], True),
    # --- C8 action, C9 cancellation, C11 missing order, C12 not received, C14 account
    (C, "الغي الاوردر NC-100012 دلوقتي", [{"C8", "C9"}], False), (C, "cancel my order now", [{"C8", "C9"}], False),
    (C, "غير عنوان الشحن", [{"C8"}], False),
    (C, "ينفع الغي الاوردر بعد الشحن", [{"C9"}], False), (C, "can I cancel my order?", [{"C9"}], False),
    (C, "عملت اوردر امبارح ومش لاقيه في حسابي", [{"C11"}], False), (C, "I placed an order but it does not show up", [{"C11"}], False),
    (C, "الاوردر مكتوب واصل بس ما وصلنيش", [{"C12"}], False), (C, "it says delivered but I never got it", [{"C12"}], False),
    (C, "مش عارف اغير الباسورد", [{"C14"}], False), (C, "I cannot update my email", [{"C14"}], False),
    # --- C13 outside the scope
    (C, "الجو عامل ايه", [{"C13"}], False), (C, "احكيلي نكتة", [{"C13"}], False), (C, "who won the match", [{"C13"}], False),
    (C, "اكتبلي كود بايثون", [{"C13"}], False),
    # --- two requests in one message
    (C, "فين طلبي وعايز اكلم موظف", [{"C1"}, {"C6"}], False), (C, "سياسة الاسترجاع ايه وحالة المرتجع بتاعي", [{"C4"}, {"C3"}], False),
    # --- worker
    (W, "شحناتي النهارده", [{"W1"}], False), (W, "what do I deliver today", [{"W1"}], False), (W, "عندي كام شحنة النهارده", [{"W1"}], False),
    (W, "الشحنة S-700001 حالتها ايه", [{"W3", "W2"}], False), (W, "كلم الدسباتش", [{"W5"}], False),
    (W, "عايز اكلم حد من الشركة", [{"W5"}], False),
    (W, "العميل مش بيرد", [{"W6"}], False), (W, "العنوان غلط", [{"W6"}], False), (W, "customer refused the delivery", [{"W6", "W8"}], False),
    (W, "الشحنة جت مكسورة", [{"W7"}], False), (W, "الطرد ناقص حاجة", [{"W7"}], False),
    (W, "ايه الاجراء لو العميل رفض الاستلام", [{"W8"}], False), (W, "what is the procedure for a failed delivery", [{"W8"}], False),
    (W, "مرتبي كام", [{"W9"}], False), (W, "ايه تقييم ادائي", [{"W9"}], False),
    (W, "حد بيهددني في الشارع", [], True),                      # the worker catalog has no safety intent: P1 alone is the right answer
]

# Held-out: written AFTER the prompt was tuned on the cases above, so they measure whether it generalises (run with "held").
HELD_OUT = [
    (W, "الزبون موبايله مقفول", [{"W6"}], False), (W, "المنطقة مقفولة ومش عارف اوصل", [{"W6"}], False), (W, "customer is not at home", [{"W6"}], False),
    (W, "ايه القاعدة لو الشحنة اتأخرت", [{"W8"}], False), (W, "how long can I keep a parcel before returning it", [{"W8"}], False),
    (W, "الكرتونة مفتوحة والحاجة ناقصة", [{"W7"}], False), (W, "wrong item inside the box", [{"W7"}], False),
    (W, "محتاج اكلم المشرف", [{"W5"}], False), (W, "هو انا هاخد حافز؟", [{"W9"}], False),
    (C, "المندوب كان وحش معايا", [{"C10"}], False), (C, "لو لغيت دلوقتي هتخصم مني حاجة؟", [{"C9", "C4"}], False),
    (C, "اشتريت جزمة ومقاسها غلط عايز ارجعها", [{"C2", "C8", "C5"}], False), (C, "ايه طرق الدفع", [{"C4"}], False),
    (C, "عايز وصفة كبسة", [{"C13"}], False), (C, "المندوب قال سلمته وانا ماستلمتش", [{"C12"}], False),
    (C, "جالي لينك وقال انه من نوفاكارت وبعد ما دخلت اتسحب من حسابي فلوس", [{"C7"}], True),
    (C, "الطلب بتاع اسبوع فين", [{"C1"}], False), (C, "الاوردر اللي طلبته مش ظاهر عندي", [{"C11"}], False),
]


def judge(parts, expected, p1):
    found = {p.intent.id for p in parts if p.intent}
    ok_intents = all(s & found for s in expected)
    has_p1 = any(p.safety == "P1" for p in parts)
    return ok_intents and has_p1 == p1, found, has_p1


async def one(role, message):
    text, refs = scrub_order_numbers(message)
    ctx = AgentContext(role=role, message=text, order_refs=refs, chat_id="eval:s", deadline_at=time.monotonic() + 30)
    out = await classify_node(AgentState(), ctx)
    return out


async def main():
    passes = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    cases = HELD_OUT if "held" in sys.argv else CASES
    wrong, failed_calls, total = Counter(), Counter(), 0
    ok_total = 0
    for _ in range(passes):
        for role, message, expected, p1 in cases:
            total += 1
            out = await one(role, message)
            if not out.get("classify_ok"):
                failed_calls[message] += 1                              # timeout / rejected: not a wrong intent, counted apart
                continue
            ok, found, has_p1 = judge(out["parts"], expected, p1)
            if ok:
                ok_total += 1
            else:
                wrong[(role, message, tuple(sorted(found)), "P1" if has_p1 else "SAFE", "want " + ("P1 " if p1 else "") + "/".join("|".join(sorted(s)) for s in expected))] += 1
    answered = total - sum(failed_calls.values())
    print(f"messages {len(cases)} x {passes} passes = {total} calls; model/format failures {sum(failed_calls.values())}")
    print(f"CORRECT {ok_total}/{answered} answered = {ok_total / answered:.1%}")
    print("\n--- wrong (count, role, message, got intents, got safety, wanted)")
    for k, v in sorted(wrong.items(), key=lambda kv: -kv[1]):
        print(v, *k)
    if failed_calls:
        print("\n--- calls that failed (not a wrong intent)", dict(failed_calls))


asyncio.run(main())
