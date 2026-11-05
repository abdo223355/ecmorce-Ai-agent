"""Ingress scrub, first slice: a typed order number becomes {order_ref_N}; only the code keeps the real id."""
import pytest

from app.agent.classify import ClassifyPromptBuilder, CUSTOMER
from app.scrub import MAX_REFS, scrub_order_numbers


@pytest.mark.parametrize("message,text,refs", [
    ("where is order NC-100010", "where is order {order_ref_1}", {"order_ref_1": "NC-100010"}),
    ("فين طلب nc-100010؟", "فين طلب {order_ref_1}؟", {"order_ref_1": "NC-100010"}),
    ("طلب NC100012 وصل", "طلب {order_ref_1} وصل", {"order_ref_1": "NC-100012"}),
    ("order NC 100014 please", "order {order_ref_1} please", {"order_ref_1": "NC-100014"}),
    ("NC-100010 and NC-100011", "{order_ref_1} and {order_ref_2}", {"order_ref_1": "NC-100010", "order_ref_2": "NC-100011"}),
    ("NC-100010 then NC-100010 again", "{order_ref_1} then {order_ref_1} again", {"order_ref_1": "NC-100010"}),
])
def test_an_order_number_becomes_a_placeholder_and_the_real_id_stays_in_the_map(message, text, refs):
    assert scrub_order_numbers(message) == (text, refs)


@pytest.mark.parametrize("message", ["hi", "فين طلبي", "ANC-100010", "NC-12345", "NC-1000100", "code 123456", ""])
def test_a_message_without_an_order_number_is_not_touched(message):
    assert scrub_order_numbers(message) == (message, {})


def test_the_real_id_never_remains_in_the_text():
    text, refs = scrub_order_numbers("check NC-100010 and nc 100011 now")
    assert "100010" not in text and "100011" not in text and len(refs) == 2


def test_more_distinct_numbers_than_the_limit_are_not_all_mapped():
    message = " ".join(f"NC-10001{i}" for i in range(MAX_REFS + 1))
    text, refs = scrub_order_numbers(message)
    assert len(refs) == MAX_REFS and "{order_ref_overflow}" in text and "NC-" not in text


def test_the_classify_prompt_tells_the_model_about_the_placeholder():
    assert "{order_ref_1}" in ClassifyPromptBuilder.system(CUSTOMER)
