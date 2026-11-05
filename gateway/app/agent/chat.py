"""Small talk: a greeting, thanks, goodbye, "ok", "who are you", "help". Plain code, no model, no tool.

Why it exists: before this, "hi" reached the classify, which rightly found no request (zero parts), and the empty turn became
template 18, "I could not finish". A real user greets before asking. These messages now get a short friendly answer that
says what the agent can do.

The rule that keeps it safe: the WHOLE message must be small talk (full match, after removing punctuation, emoji, accents and
stretched letters). "hi my account was hacked" or "هاي فين طلبي" is not small talk: it goes to the classify as before, so a
safety message or a real request is never swallowed by a greeting.

The words an answer promises are only what the agent really does today (order status, return status, policy questions, a
person for the customer; today's shipments, delivery procedures, dispatch for the worker).

TODO(owner): the wording of every answer below (Arabic and English) is a DRAFT, and so is the list of greeting
  patterns. Correct the wording and add the ways your users really greet.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .state import Part, PartOutcome

_TASHKEEL = re.compile("[ً-ْـ]")                                  # Arabic diacritics and the tatweel stretch
_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
_PUNCT = re.compile(r"[^\w\s]")


def normalize(message: str) -> str:
    """Lower case, no accents, one alef, no punctuation or emoji, one space between words."""
    text = _TASHKEEL.sub("", message.casefold()).translate(_FOLD)
    return re.sub(r"\s+", " ", _PUNCT.sub(" ", text)).strip()


# kind -> {language: patterns}. Franco (Arabic in Latin letters) counts as Arabic.
PATTERNS: dict[str, dict[str, tuple[str, ...]]] = {
    "greeting": {
        "en": (r"h+i+( there)?", r"h+e+l+o+( there)?", r"h+e+y+( there)?", r"hiya", r"yo", r"greetings",
               r"good (morning|afternoon|evening|day)", r"how are you", r"how r u"),
        "ar": (r"ها+ي+", r"هل+ا+", r"ا+هل+ا+( وسهل+ا+| بيك| بيكي| بيكم| بك)?", r"ا+هل+ين", r"مرحب+ا+(ت+ين)?", r"يا هل+ا+",
               r"(ال)?سلام عليكم( ورحمه الله( وبركاته)?)?", r"سلام", r"صباح (الخير|النور|الفل|الورد)",
               r"مساء (الخير|النور|الفل)", r"ازي(ك|كي|كم)", r"عامل اي(ه)?", r"عاملين اي(ه)?", r"اخبارك اي(ه)?",
               r"اي(ه)? الاخبار", r"ahlan( bik| wa sahlan)?", r"salam( alaikum| aleikum)?", r"marhaba", r"ezay(ak|ek|kom)",
               r"sabah el (kheir|nour)", r"masa2? el (kheir|nour)"),
    },
    "thanks": {
        "en": (r"thank+s+( a lot| so much| very much)?", r"thank you( so much| very much)?", r"thx", r"ty", r"many thanks",
               r"cheers", r"(ok|okay|great|cool) thanks?"),
        "ar": (r"شكر+ا+( جزيل+ا+| ليك| لك| ليكي| ليكم| يا (باشا|بوت))?", r"الف شكر", r"متشكر(ه)?", r"تسلم( ايدك| ايديك)?",
               r"ميرسي", r"مرسي", r"(تمام|طيب|ماشي|اوك(ي)?) شكر+ا+", r"shokra+n+( ?gazeelan)?", r"merci", r"mersi"),
    },
    "bye": {
        "en": (r"bye( bye)?", r"good ?bye", r"see (you|ya)( later| soon)?", r"good night", r"take care", r"cya"),
        "ar": (r"مع السلام(ه)?", r"تصبح علي خير", r"الي اللقاء", r"باي( باي)?", r"يلا سلام", r"سلام يلا",
               r"ma3a? el salam(a|ah)", r"m3a el salama"),
    },
    "ack": {
        "en": (r"ok(ay)?", r"fine", r"great", r"cool", r"got it", r"alright"),
        "ar": (r"تمام", r"طيب", r"حاضر", r"ماشي", r"اوك(ي)?", r"اوكيه", r"كويس", r"حلو"),
    },
    "identity": {
        "en": (r"who are you", r"what are you", r"who is this", r"are you (a )?(bot|human|robot|real|ai|person)",
               r"what( is|s) your name"),
        "ar": (r"(انت|انتي) (مين|اي(ه)?|بوت|روبوت|انسان|حد|بني ادم)( يا .+)?", r"مين انت", r"اسمك اي(ه)?", r"اي(ه)? اسمك"),
    },
    "help": {
        "en": (r"help( me| please)?", r"i need help", r"can you help( me)?", r"what can you do", r"how (can|do) you help( me)?",
               r"what do you do"),
        "ar": (r"(تقدر|تعرف|بتعرف|ممكن) تعمل اي(ه)?", r"بتعمل اي(ه)?", r"(ممكن|تقدر) (تساعدني|تساعدنا)",
               r"(محتاج|عايز|عاوز|احتاج|اريد) مساعده", r"ساعدني", r"مساعده", r"(اي(ه)?) (الخدمات|اللي تقدر تعمله|اللي بتقدر تعمله)",
               r"msa3da", r"3ayez msa3da"),
    },
}
_COMPILED = [(kind, language, re.compile(p)) for kind, langs in PATTERNS.items() for language, ps in langs.items() for p in ps]

CAPABILITIES = {
    ("customer", "ar"): "أقدر أساعدك في: حالة طلبك، وحالة المرتجع، وأسئلة عن سياسات NovaCart، وأوصّلك بموظف خدمة العملاء. اكتب سؤالك.",
    ("customer", "en"): "I can help you with: your order status, your return status, questions about NovaCart policies, and passing you to a Customer Service agent. Just type your question.",
    ("worker", "ar"): "أقدر أساعدك في: شحناتك النهارده، وإجراءات التوصيل، وأوصّلك بالـ dispatch. اكتب سؤالك.",
    ("worker", "en"): "I can help you with: today's shipments, delivery procedures, and passing you to dispatch. Just type your question.",
}
LEAD = {
    "greeting": {"ar": "أهلًا بيك في NovaCart! ", "en": "Hello, welcome to NovaCart! "},
    "identity": {"ar": "أنا مساعد NovaCart الذكي (مش موظف). ", "en": "I am NovaCart's AI assistant (not a staff member). "},
    "help": {"ar": "أكيد! ", "en": "Of course! "},
    "unclear": {"ar": "مفهمتش طلبك بالظبط. ", "en": "I did not quite understand your request. "},
}
SHORT = {
    "thanks": {"ar": "العفو! لو محتاج أي حاجة تانية أنا موجود.", "en": "You're welcome! If you need anything else, I'm here."},
    "bye": {"ar": "مع السلامة! لو احتجت أي حاجة كلمني تاني.", "en": "Goodbye! If you need anything, just write to me again."},
    "ack": {"ar": "تمام. لو محتاج أي حاجة تانية اكتب لي.", "en": "Okay. If you need anything else, just write to me."},
    # a bare "2" with no list in memory (D65): not a failed attempt, the user is asked again
    "lost_context": {"ar": "مش فاكر القايمة اللي كنا بنتكلم عنها. اكتب رقم الطلب أو اسم المنتج.",
                     "en": "I do not have that list in front of me any more. Please send the order number or the product name."},
}


@dataclass(frozen=True)
class Talk:
    kind: str                     # greeting | thanks | bye | ack | identity | help | unclear
    language: str                 # ar | en


def match(message: str) -> Talk | None:
    """Small talk only when the WHOLE message is small talk. Anything else (even a greeting plus a request) is None."""
    text = normalize(message)
    if not text:
        return None
    for kind, language, pattern in _COMPILED:
        if pattern.fullmatch(text):
            return Talk(kind, language)
    return None


def answer(kind: str, role: str, language: str) -> str:
    """The words for one kind of small talk, for the role and the language."""
    if kind in SHORT:
        return SHORT[kind][language]
    return LEAD.get(kind, {}).get(language, "") + CAPABILITIES[(role, language)]


def part_for(talk: Talk, role: str) -> Part:
    """The single part of a small-talk turn: no intent, no tool, the words already decided (outcome kind "chat")."""
    return Part(index=0, safety="SAFE", needs_explanation=False,
                outcome=PartOutcome(kind="chat", text=answer(talk.kind, role, talk.language)))
