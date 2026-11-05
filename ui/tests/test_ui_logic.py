"""Tests of the screen's logic: the API client (with a fake HTTP transport), the text rendering and the options.
They run without Streamlit and without the stack: python -m pytest -q  (from ui/)."""
import json

import httpx
import pytest

from novacart_ui.api import (ChatReply, LoginFailed, NovaCartApi, SegmentView, ServiceUnavailable, SessionExpired,
                             UserSession)
from novacart_ui.options import CUSTOMER_OPTIONS, WORKER_OPTIONS, options_for
from novacart_ui.texts import TEXTS, detect_language, fill, render_reply, render_segment


def api_with(handler) -> NovaCartApi:
    return NovaCartApi("http://backend", "http://gateway", httpx.Client(transport=httpx.MockTransport(handler)))


def seg(part_index=0, kind="template", template_id=1, text=None, values=None):
    return SegmentView(part_index, kind, template_id, text, values or {})


# ---------- api ----------
def test_login_returns_the_token_and_the_role():
    api = api_with(lambda r: httpx.Response(200, json={"access_token": "T", "role": "worker"}))
    assert api.login("w-2001", "x") == UserSession("T", "worker")


def test_login_with_wrong_credentials_is_login_failed():
    with pytest.raises(LoginFailed):
        api_with(lambda r: httpx.Response(401, json={"error": "invalid_credentials"})).login("a", "b")


def test_a_backend_that_does_not_answer_is_service_unavailable():
    def down(request):
        raise httpx.ConnectError("no route")
    with pytest.raises(ServiceUnavailable):
        api_with(down).login("a", "b")


RESULT = {"status": "ok", "result": {"segments": [{"part_index": 0, "kind": "template", "template_id": 1, "text": None,
                                                    "render_values": {"order_id": "NC-1"}, "cited": []}],
                                     "handoff_reason": None, "priority": None, "block_session_data": False,
                                     "handoff_summary": None}}


def test_chat_sends_the_token_as_a_bearer_header_and_the_message_only():
    seen = {}

    def handler(request):
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json=RESULT)
    reply = api_with(handler).chat(UserSession("T", "customer"), "فين طلبي؟")
    assert seen["auth"] == "Bearer T" and seen["body"] == {"message": "فين طلبي؟"}      # no identity field of ours
    assert reply.segments[0].render_values == {"order_id": "NC-1"} and reply.raw == RESULT["result"]


def test_an_expired_token_is_session_expired_and_other_errors_are_unavailable():
    with pytest.raises(SessionExpired):
        api_with(lambda r: httpx.Response(401)).chat(UserSession("T", "customer"), "hi")
    for status in (403, 500):
        with pytest.raises(ServiceUnavailable):
            api_with(lambda r, s=status: httpx.Response(s)).chat(UserSession("T", "customer"), "hi")


# ---------- texts ----------
def test_language_follows_the_letters_of_the_message():
    assert detect_language("فين طلبي؟") == "ar" and detect_language("where is my order") == "en"


def test_fill_puts_known_values_and_leaves_unknown_placeholders_alone():
    assert fill("Order {order_id} is {status}", {"order_id": "NC-1"}) == "Order NC-1 is {status}"


def test_fill_keeps_line_breaks_of_a_value_as_markdown_breaks_between_blank_lines():
    assert fill("Q\n{rows}\nEnd", {"rows": "a\nb"}) == "Q\n\n\na  \nb\n\n\nEnd"


def test_a_list_value_does_not_swallow_the_words_after_it():
    out = render_segment(seg(kind="clarify", template_id=None, text="Which?\n{choices_text}\nSend the number.",
                             values={"choices_text": "1) A\n2) B"}), "en")
    assert "\n\nSend the number." in out


def test_a_template_segment_renders_its_text_with_the_real_values():
    out = render_segment(seg(template_id=1, values={"order_id": "NC-1", "order_status": "Shipped", "last_updated": "2026-10-19"}), "en")
    assert out == "Your order NC-1 is: Shipped. Last updated: 19 Oct 2026."


def test_a_text_segment_uses_its_words_and_a_text_segment_without_words_falls_back_to_its_template():
    assert render_segment(seg(kind="text", template_id=None, text="Hello {name}", values={"name": "Sam"}), "en") == "Hello Sam"
    assert render_segment(seg(kind="text", template_id=15, text=None), "ar") == TEXTS[15]["ar"]


def test_an_unknown_template_id_is_shown_as_such_never_empty():
    assert "99" in render_segment(seg(template_id=99), "en")


def test_every_template_text_exists_in_both_languages():
    assert all(set(t) == {"ar", "en"} and t["ar"] and t["en"] for t in TEXTS.values())


def test_the_segments_are_joined_in_written_order_with_the_p1_acknowledgement_first():
    reply = ChatReply([seg(1, template_id=18), seg(-1, template_id=8)], "SAFE", "P1", 0.1, {})
    out = render_reply(reply, "en")
    assert out.index("safety") < out.index("could not finish")


# ---------- options ----------
def test_each_role_gets_its_own_buttons_and_an_unknown_role_gets_none():
    assert options_for("customer") is CUSTOMER_OPTIONS and options_for("worker") is WORKER_OPTIONS
    assert options_for("admin") == ()


def test_every_button_points_at_an_intent_of_its_own_role_and_labels_are_unique():
    assert all(o.intent.startswith("C") for o in CUSTOMER_OPTIONS) and all(o.intent.startswith("W") for o in WORKER_OPTIONS)
    for options in (CUSTOMER_OPTIONS, WORKER_OPTIONS):
        assert len({o.label for o in options}) == len(options) and all(o.message.strip() for o in options)


# ---------- admin metrics (pure, on a DataFrame) ----------
import pandas as pd

from novacart_ui.metrics import COLUMNS, handoffs_by_reason, node_latency, outcome_counts, status_counts, summary


def events(*rows) -> pd.DataFrame:
    base = {"ts": pd.Timestamp("2026-11-02"), "role": "customer", "classify_path": "llm", "classify_status": "ok",
            "classify_reason": None, "classify_latency_s": 1.0, "reply_status": None, "reply_reason": None,
            "reply_latency_s": None, "total_latency_s": 2.0, "outcomes": [{"kind": "text", "template_id": None}],
            "handoff_reason": None, "priority": None, "p1": False}
    return pd.DataFrame([{**base, **r} for r in rows], columns=COLUMNS)


def test_an_empty_table_gives_zeros_not_an_error():
    s = summary(events())
    assert s["requests"] == 0 and s["p95"] == 0.0 and s["failure_rate"] == 0.0
    assert node_latency(events()).loc["reply", "calls"] == 0


def test_summary_counts_failures_handoffs_p1_and_the_code_share():
    df = events({"total_latency_s": 1.0, "classify_path": "code"},
                {"total_latency_s": 3.0, "outcomes": [{"kind": "template", "template_id": 18}]},
                {"total_latency_s": 5.0, "outcomes": [{"kind": "template", "template_id": 8}], "handoff_reason": "SAFE",
                 "priority": "P1", "p1": True},
                {"total_latency_s": 3.0, "outcomes": [{"kind": "template", "template_id": 15}, {"kind": "text", "template_id": None}]})
    s = summary(df)
    assert s["requests"] == 4 and s["p50"] == 3.0 and s["max"] == 5.0
    assert s["failure_rate"] == 0.5 and s["handoffs"] == 1 and s["p1"] == 1 and s["code_share"] == 0.25


def test_node_latency_looks_only_at_model_calls_and_only_ok_calls_set_the_time():
    df = events({"classify_path": "code", "classify_latency_s": 0.0},
                {"classify_latency_s": 1.0, "reply_status": "ok", "reply_latency_s": 2.0},
                {"classify_latency_s": 3.0, "classify_status": "timeout", "reply_status": "timeout", "reply_latency_s": 2.5})
    t = node_latency(df)
    assert t.loc["classify", "calls"] == 2 and t.loc["classify", "ok"] == 1 and t.loc["classify", "max_s"] == 1.0
    assert t.loc["reply", "calls"] == 2 and t.loc["reply", "ok"] == 1 and t.loc["reply", "p50_s"] == 2.0


def test_status_outcome_and_handoff_breakdowns():
    df = events({"classify_status": "ok"}, {"classify_status": "rate_limited"}, {"classify_status": "rate_limited"},
                {"classify_path": "code"})
    assert status_counts(df, "classify").to_dict() == {"rate_limited": 2, "ok": 1}
    assert outcome_counts(events({"outcomes": [{"kind": "template", "template_id": 18}, {"kind": "clarify", "template_id": None}]},
                                 {"outcomes": [{"kind": "template", "template_id": 18}]})).to_dict() == {"template 18": 2, "clarify": 1}
    handed = handoffs_by_reason(events({"handoff_reason": "POL", "priority": "P3"}, {"handoff_reason": "POL", "priority": "P3"},
                                       {"handoff_reason": "SAFE", "priority": "P1"}, {}))
    assert handed.set_index(["handoff_reason", "priority"])["count"].to_dict() == {("POL", "P3"): 2, ("SAFE", "P1"): 1}


# ---------- lab ----------
import socket
import threading

from novacart_ui.lab import (SCENARIOS, SEED_ACCOUNTS, SEED_CUSTOMERS, SEED_WORKERS, backend_get, check_http, check_postgres,
                             check_redis, role_of, truth_paths)


def test_seed_accounts_and_the_role_taken_from_the_name():
    assert len(SEED_CUSTOMERS) == 10 and len(SEED_WORKERS) == 5 and SEED_ACCOUNTS[0] == "c-100001" and SEED_ACCOUNTS[-1] == "w-2005"
    assert role_of("w-2003") == "worker" and role_of("c-100003") == "customer"


def test_every_scenario_uses_a_real_seed_account_and_has_words():
    assert all(s.account in SEED_ACCOUNTS and s.message.strip() and s.title.strip() for s in SCENARIOS)
    assert len({s.title for s in SCENARIOS}) == len(SCENARIOS)


def test_http_health_is_ok_only_on_200():
    ok = check_http("backend", "http://x/health", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    bad = check_http("gateway", "http://x/health", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    assert ok.ok and ok.detail == "200" and not bad.ok and "503" in bad.detail


def test_a_service_that_does_not_answer_is_a_red_result_not_a_crash():
    def down(request):
        raise httpx.ConnectError("no route")
    assert check_http("x", "http://x/health", httpx.Client(transport=httpx.MockTransport(down))).ok is False
    assert check_postgres("postgresql://u:p@127.0.0.1:1/db").ok is False
    assert check_redis("redis://127.0.0.1:1/0").ok is False


def test_redis_health_wants_a_pong():
    def serve(listener, reply):
        conn, _ = listener.accept()
        conn.recv(16)
        conn.sendall(reply)
        conn.close()
    for reply, expected in ((b"+PONG\r\n", True), (b"-ERR no\r\n", False)):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        threading.Thread(target=serve, args=(listener, reply), daemon=True).start()
        assert check_redis(f"redis://127.0.0.1:{listener.getsockname()[1]}/0").ok is expected
        listener.close()


def test_backend_get_sends_the_accounts_own_token_and_returns_status_and_body():
    seen = {}

    def handler(request):
        seen["auth"], seen["path"] = request.headers["authorization"], request.url.path
        return httpx.Response(404, json={"error": "not_found"})
    status, body = backend_get(httpx.Client(transport=httpx.MockTransport(handler)), "http://b/", "T", "/customer/orders/NC-1")
    assert (status, body) == (404, {"error": "not_found"}) and seen == {"auth": "Bearer T", "path": "/customer/orders/NC-1"}


def test_each_role_reads_its_own_endpoints():
    assert truth_paths("customer")["list"] == "/customer/orders/recent" and truth_paths("worker")["list"] == "/worker/shipments/today"


# ---------- raw values are shown as words and dates ----------
def test_present_turns_a_status_and_a_date_time_into_readable_text():
    from novacart_ui.texts import present
    assert present("order_status", "Processing", "ar") == "قيد التجهيز"
    assert present("order_status", "Processing", "en") == "Processing"                    # English keeps the backend word
    assert present("order_status", "Something New", "ar") == "Something New"             # unknown: unchanged, never guessed
    assert present("last_updated", "2026-10-22T08:09:29+03:00", "ar") == "22 أكتوبر 2026 الساعة 08:09"
    assert present("last_updated", "2026-10-22T08:09:29+03:00", "en") == "22 Oct 2026 at 08:09"
    assert present("order_date", "2026-10-20", "en") == "20 Oct 2026"
    assert present("last_updated", "not a date", "en") == "not a date" and present("count", "3", "ar") == "3"


def test_a_rendered_order_status_has_no_raw_iso_date():
    from novacart_ui.api import SegmentView
    from novacart_ui.texts import render_segment
    seg = SegmentView(part_index=0, kind="template", template_id=1, text=None, render_values={
        "order_id": "NC-100013", "order_status": "Processing", "last_updated": "2026-10-22T08:09:29+03:00"})
    text = render_segment(seg, "ar")
    assert "NC-100013" in text and "قيد التجهيز" in text and "T08:09" not in text and "+03:00" not in text


def test_a_code_built_list_shows_each_order_with_a_word_status_and_a_readable_date():
    from novacart_ui.api import SegmentView
    from novacart_ui.texts import render_segment
    text = "- {o1_product}: {o1_status}, last updated {o1_updated} ({o1_id})"
    seg = SegmentView(part_index=0, kind="text", template_id=None, text=text, render_values={
        "o1_product": "Watch", "o1_status": "Shipped", "o1_updated": "2026-10-22T08:09:29+03:00", "o1_id": "NC-100001"})
    assert render_segment(seg, "en") == "- Watch: Shipped, last updated 22 Oct 2026 at 08:09 (NC-100001)"
    assert "تم الشحن" in render_segment(seg, "ar") and "T08:09" not in render_segment(seg, "ar")


def test_a_return_answer_shows_readable_dates_for_every_date_placeholder():
    from novacart_ui.api import SegmentView
    from novacart_ui.texts import render_segment
    text = "{order_id} {delivered_date} - {i1_name}: {i1_end_date} / {i1_defect_date}"
    seg = SegmentView(part_index=0, kind="text", template_id=None, text=text, render_values={
        "order_id": "NC-1", "delivered_date": "2026-10-30", "i1_name": "Samsung", "i1_end_date": "2026-11-14", "i1_defect_date": "2026-11-29"})
    assert render_segment(seg, "en") == "NC-1 30 Oct 2026 - Samsung: 14 Nov 2026 / 29 Nov 2026"
    assert "14 نوفمبر 2026" in render_segment(seg, "ar") and "2026-11" not in render_segment(seg, "ar")
