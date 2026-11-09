"""Demo mode: recorded answers, matched by a normalised question, rendered with the same code as the live screen."""
import re

import pytest

from novacart_ui.demo import RECORDINGS, DemoStore, normalize
from novacart_ui.texts import detect_language, render_reply

STORE = DemoStore.load()


def test_normalize_ignores_case_punctuation_harakat_and_alef_forms():
    assert normalize("ينفع ألغي NC-100014؟") == normalize("ينفع الغي nc-100014")
    assert normalize("Can I cancel order NC-100014?") == normalize("  can i cancel order nc-100014 ")
    assert normalize("أرجّع") == normalize("ارجع")


def test_the_recordings_cover_customers_and_a_worker():
    roles = dict(STORE.accounts())
    assert roles["c-100005"] == "customer" and roles["w-2001"] == "worker"
    assert len(STORE.items) >= 15


def test_a_recorded_question_gets_its_recorded_answer_even_when_typed_loosely():
    exact = STORE.answer("c-100005", "ينفع ألغي NC-100014؟")
    loose = STORE.answer("c-100005", "ينفع الغي nc-100014")
    assert exact is not None and loose is not None and exact.raw == loose.raw


def test_an_unrecorded_question_gets_no_answer_and_nothing_is_invented():
    assert STORE.answer("c-100005", "عايز أغيّر عنواني على كوكب المريخ") is None


def test_an_answer_belongs_to_the_account_that_was_recorded():
    assert STORE.answer("c-100001", "ينفع ألغي NC-100014؟") is None          # that order is c-100005's


def test_common_questions_are_shared_by_the_same_role_only():
    assert STORE.answer("c-100001", "مرحبا") is not None                      # a greeting, asked as another customer
    assert STORE.answer("w-2001", "مرحبا") is None                            # a worker's recordings are separate


def test_suggestions_have_no_repeats_and_all_have_an_answer():
    for account, _ in STORE.accounts():
        questions = STORE.suggestions(account)
        assert questions and len(questions) == len(set(questions))
        assert all(STORE.answer(account, q) is not None for q in questions)


@pytest.mark.parametrize("item", STORE.items, ids=lambda i: f"{i.account}-{i.message[:24]}")
def test_every_recording_renders_to_readable_text_without_leftover_placeholders(item):
    reply = STORE.answer(item.account, item.message)
    text = render_reply(reply, detect_language(item.message))
    assert text.strip()
    assert not re.search(r"\{[a-z0-9_]+\}", text), text


def test_the_recordings_hold_no_token_and_no_password():
    raw = RECORDINGS.read_text(encoding="utf-8")
    for forbidden in ("access_token", "Bearer ", "password", "NovaCart#2026"):
        assert forbidden not in raw
