"""Stability: every message of quality_eval is sent N times through the real /chat (WORKERS at a time, default 4). Shows, per message,
what the user got each time. A message is STABLE when all N answers are acceptable (same rule as quality_eval)."""
import sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import quality_eval as q

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 4        # requests at the same time


def one(job):
    user, tok, category, ok, m = job
    try:
        r = q.post(f"{q.GATEWAY}/chat", {"message": m}, tok)["result"]
        got = "+".join(q.label(s) for s in r["segments"])
        good = all(q.label(s) in ok for s in r["segments"])
    except Exception as e:                                       # noqa: BLE001
        got, good = f"ERROR {type(e).__name__}", False
    return user, category, m, got, good


def main():
    jobs = []
    for user, groups in (("c-100005", q.CUSTOMER), ("w-2001", q.WORKER)):
        tok = q.token(user)
        for category, (ok, messages) in groups.items():
            jobs += [(user, tok, category, ok, m) for m in messages for _ in range(N)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(one, jobs))
    per = {}
    for user, category, m, got, good in results:
        per.setdefault((user, category, m), []).append((got, good))
    unstable = 0
    for (user, category, m), rs in per.items():
        good = sum(g for _, g in rs)
        if good != len(rs):
            unstable += 1
            print(f"{good}/{len(rs)}  {user} {m[:36]:36} {dict(Counter(got for got, _ in rs))}")
    total = sum(g for *_, g in results)
    print(f"\nmessages {len(per)} x {N} = {len(results)} requests in {time.perf_counter()-t0:.0f}s")
    print(f"acceptable answers: {total}/{len(results)} = {total/len(results):.1%}; messages not 100% stable: {unstable}/{len(per)}")


if __name__ == "__main__":
    main()
