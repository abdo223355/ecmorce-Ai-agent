"""The ready-made options on the chat screen: one button per common problem, per role. A button sends its message
exactly as if the user had typed it, so the Gateway classifies it like any other message (no shortcut around the agent).

TODO(owner): the choice of options and their wording are a DRAFT. Each one points at an intent the agent
  already understands (the intent id is in the comment). Add, remove or rename them, then say which ones you want.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuickOption:
    label: str                # what the button says
    message: str              # what is sent to the agent
    intent: str               # the intent it is meant to reach (documentation and tests, never sent)


CUSTOMER_OPTIONS = (
    QuickOption("فين طلبي؟", "فين طلبي؟", "C1"),
    QuickOption("الأوردر اتأخر", "طلبي اتأخر، فين وصل؟", "C1"),
    QuickOption("حالة المرتجع", "حالة المرتجع بتاعي إيه؟", "C3"),
    QuickOption("أقدر أرجّع منتج؟", "أقدر أرجّع المنتج اللي طلبته؟", "C2"),
    QuickOption("سياسة الاسترجاع", "ما هي سياسة الاسترجاع؟", "C4"),
    QuickOption("الطلب وصل ومستلمتوش", "الطلب بيقول اتسلّم بس أنا مستلمتوش", "C12"),
    QuickOption("عايز أقدّم شكوى", "عايز أقدّم شكوى على طلبي", "C10"),
    QuickOption("كلّم موظف", "عايز أكلّم موظف", "C6"),
    QuickOption("مشكلة أمان في حسابي", "حد دخل على حسابي من غير علمي", "C7"),
)

WORKER_OPTIONS = (
    QuickOption("شحنات النهارده", "شحناتي النهارده", "W1"),
    QuickOption("مشكلة في التسليم", "عندي مشكلة في تسليم شحنة", "W6"),
    QuickOption("شحنة تالفة أو ناقصة", "الشحنة وصلتني تالفة", "W7"),
    QuickOption("كلّم الـ dispatch", "عايز أكلّم الـ dispatch", "W5"),
    QuickOption("سؤال عن الإجراءات", "إيه الإجراء لو العميل مش موجود؟", "W8"),
)

OPTIONS = {"customer": CUSTOMER_OPTIONS, "worker": WORKER_OPTIONS}


def options_for(role: str) -> tuple[QuickOption, ...]:
    """The buttons of a role. An unknown role gets none (the Gateway would reject it anyway, D36)."""
    return OPTIONS.get(role, ())
