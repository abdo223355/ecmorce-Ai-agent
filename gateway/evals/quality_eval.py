"""Re-evaluation of the agent with natural messages, through the real /chat. For each message: what the user got, and
whether that is an acceptable answer for that kind of message (a judgement written down BELOW, before the run)."""
import json, statistics, sys, time, urllib.request
from collections import defaultdict

BACKEND, GATEWAY = "http://127.0.0.1:8000", "http://127.0.0.1:8080"
DEMO_PASSWORD = "NovaCart#2026"      # the documented demo password of the seed accounts (backend/SEED_SCENARIOS.md)


def post(url, body, token=None):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def token(user):
    return post(f"{BACKEND}/auth/login", {"username": user, "password": DEMO_PASSWORD})["access_token"]


def label(seg):
    return "text" if seg["kind"] == "text" else ("clarify" if seg["kind"] == "clarify" else f"t{seg['template_id']}")


# category -> (acceptable labels, messages). "text" = the model wrote words, "clarify" = a question, tN = template N.
CUSTOMER = {
    "greeting / thanks / bye": ({"text"}, ["hi", "هاي", "اهلا", "السلام عليكم", "صباح الخير", "ازيك", "شكرا", "شكراً ليك", "تمام", "مع السلامة"]),
    "who are you / what can you do": ({"text"}, ["إنت مين؟", "تقدر تعمل ايه؟", "help", "محتاج مساعدة"]),
    "order status (no number)": ({"text", "clarify", "t1"}, ["فين طلبي؟", "طلبي اتأخر", "اخر طلب عملته وصل؟", "where is my order", "what's the status of my last order", "حالة الاوردر ايه"]),
    "order status (number typed)": ({"text", "t1"}, ["فين طلب NC-100013", "حالة الاوردر NC-100012", "where is order NC-100014"]),
    "order of someone else (honest no)": ({"t14"}, ["فين طلب NC-100010"]),   # NC-100010 belongs to C-100004
    "returns": ({"text", "clarify", "t2", "t5", "t10", "t12"}, ["حالة المرتجع", "عايز ارجع منتج", "هل ينفع ارجع الموبايل؟", "how do I return an item"]),
    "policy questions": ({"text", "t12"}, ["سياسة الاسترجاع ايه", "الشحن بكام", "how long does delivery take", "do you accept cash on delivery"]),
    "cancellation question with no number (asks which order)": ({"clarify"}, ["ينفع الغي الاوردر بعد الشحن"]),
    "cancellation with a number": ({"text", "t5"}, ["ينفع الغي الطلب NC-100013؟", "can I cancel order NC-100014"]),
    "wants a person / complains": ({"t5"}, ["عايز اكلم موظف", "عايز اقدم شكوى", "الخدمة وحشة", "I want to speak to a person"]),
    "safety": ({"t8"}, ["حد دخل حسابي", "someone stole my card"]),
    "outside the scope": ({"t9"}, ["الجو عامل ايه", "احكيلي نكتة", "who won the match"]),
}
WORKER = {
    "greeting / thanks": ({"text"}, ["hi", "اهلا", "شكرا"]),
    "today's shipments": ({"t3", "text"}, ["شحناتي النهارده", "عندي كام شحنة النهارده", "what do I deliver today"]),
    "wants dispatch": ({"t6"}, ["كلم الدسباتش", "عايز اكلم حد من الشركة"]),
    "delivery problem": ({"t6", "text", "t5", "clarify"}, ["العميل مش بيرد", "العنوان غلط"]),
}


def run(user, groups):
    tok, rows = token(user), []
    for category, (ok, messages) in groups.items():
        for m in messages:
            t0 = time.perf_counter()
            try:
                r = post(f"{GATEWAY}/chat", {"message": m}, tok)["result"]
                got = "+".join(label(s) for s in r["segments"])
                good = all(label(s) in ok for s in r["segments"])
            except Exception as e:                                       # noqa: BLE001
                got, good = f"ERROR {type(e).__name__}", False
            rows.append((user, category, m, got, good, time.perf_counter() - t0))
            print(f"{'OK ' if good else 'BAD'} {category[:26]:26} {m[:34]:34} -> {got}", flush=True)
    return rows


def main():
    rows = run("c-100005", CUSTOMER) + run("w-2001", WORKER)
    by = defaultdict(list)
    for r in rows:
        by[(r[0], r[1])].append(r)
    print("\n=== per category (acceptable / total)")
    for (user, cat), rs in by.items():
        print(f"{user:9} {cat:32} {sum(r[4] for r in rs)}/{len(rs)}")
    total_ok = sum(r[4] for r in rows)
    print(f"\nTOTAL acceptable: {total_ok}/{len(rows)} = {total_ok/len(rows):.0%}   p50 time {statistics.median(r[5] for r in rows):.2f}s")
    print("\n=== what the user got when it was NOT acceptable (count by outcome)")
    bad = defaultdict(int)
    for r in rows:
        if not r[4]:
            bad[r[3]] += 1
    print(dict(sorted(bad.items(), key=lambda kv: -kv[1])))
    json.dump([dict(user=r[0], category=r[1], message=r[2], got=r[3], ok=r[4]) for r in rows], open("quality_eval.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
