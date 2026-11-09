"""Record the demo's answers from the RUNNING system (docker compose up). Run: python ui/demo/record.py

It logs in as the demo accounts (the public demo password from backend/SEED_SCENARIOS.md), sends each question through the
real /chat, and saves the Gateway's results to ui/demo/recordings.json. Re-run it after a change in the answers, or after
re-seeding the data: the window dates in the answers (returns, exchanges) depend on the day the data was seeded.

An answer of template 18 ("could not finish") is a provider timeout, not a result worth showing, so it is tried again.
"""
from __future__ import annotations

import datetime
import json
import time
import urllib.request
from pathlib import Path

BACKEND, GATEWAY = "http://127.0.0.1:8000", "http://127.0.0.1:8080"
DEMO_PASSWORD = "NovaCart#2026"
OUT = Path(__file__).resolve().parent / "recordings.json"
RETRIES = 5

# (account, group, question). The account decides which orders an answer is about; "common" is shared by the same role.
CASES = [
    ("c-100005", "cancel", "ينفع ألغي NC-100014؟"),
    ("c-100005", "cancel", "ينفع ألغي NC-100015؟"),
    ("c-100005", "cancel", "ينفع ألغي NC-100012؟"),
    ("c-100005", "cancel", "can I cancel order NC-100014?"),
    ("c-100005", "cancel", "can I cancel order NC-100015?"),
    ("c-100005", "return", "ينفع أرجّع NC-100014؟"),
    ("c-100001", "return", "ينفع أرجّع NC-100001؟"),
    ("c-100001", "return", "can I return order NC-100001?"),
    ("c-100001", "exchange", "ينفع أبدّل NC-100001؟"),
    ("c-100001", "exchange", "can I exchange order NC-100001?"),
    ("c-100003", "return", "ينفع أرجّع NC-100007؟"),
    ("c-100006", "returns", "حالة المرتجع بتاعي إيه؟"),
    ("c-100009", "clarify", "عايز أرجّع السامسونج"),
    ("c-100010", "orders", "فين طلبي؟"),
    ("c-100005", "common", "مرحبا"),
    ("c-100005", "common", "ما هي سياسة الاسترجاع؟"),
    ("c-100005", "common", "حد دخل على حسابي من غير علمي"),
    ("c-100005", "common", "عايز أكلّم موظف"),
    ("w-2001", "worker", "شحناتي النهارده"),
    ("w-2001", "worker", "إيه الإجراء لو العميل مش موجود؟"),
]


def post(url: str, body: dict, token: str | None = None) -> dict:
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    request = urllib.request.Request(url, json.dumps(body).encode("utf-8"), headers)
    return json.load(urllib.request.urlopen(request, timeout=40))


def main() -> None:
    sessions: dict[str, dict] = {}
    items = []
    for account, group, message in CASES:
        if account not in sessions:
            sessions[account] = post(f"{BACKEND}/auth/login", {"username": account, "password": DEMO_PASSWORD})
        for attempt in range(1, RETRIES + 1):
            result = post(f"{GATEWAY}/chat", {"message": message}, sessions[account]["access_token"])["result"]
            if result["segments"][0].get("template_id") != 18:
                break
            time.sleep(2)
        else:
            raise SystemExit(f"no usable answer for {account}: {message}")
        items.append({"account": account, "role": sessions[account]["role"], "group": group,
                      "message": message, "result": result})
        print(account, "|", message, "|", [s["kind"] for s in result["segments"]], flush=True)
    doc = {"recorded_on": datetime.date.today().isoformat(), "items": items}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print("saved", len(items), "->", OUT)


if __name__ == "__main__":
    main()
