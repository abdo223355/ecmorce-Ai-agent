# Phase 5 - Step 8: Exit checklist

Adaptive AI Gateway - NovaCart - القرارات المقترحة D126-D129

دي آخر step في Phase 5. مفيهاش تصميم جديد. بتتأكد إن كل حاجة اتقفلت، وبتحدد كل حاجة هتروح لمين في الـ phases اللي جاية.

---

## D126 - شروط خروج Phase 5
- Steps 1-7 مقفولين، وكل step عدّت على مراجعة مستقلة واتعملت تصليحاتها.
- كل خطر في الـ register ليه حالة واحدة من الأربعة دول:
  1. designed: اتصمم، وهيتأكد في Phase 6 أو Phase 8.
  2. accepted: اتقبل، ومعاه علامة بتكشفه، وميعاد يتراجع فيه.
  3. open-owner: مستني قرار أو توقيع من الـ owner.
  4. open-phase: هيتقفل في phase محددة.
- مفيش خطر Tier A مالوش owner وstep أو phase بتقفله.
- كل رقم اتكتب في Phase 5 متعلّم عليه design choice أو قيمة مبدئية.
- أسئلة الـ owner متجمعة في مكان واحد (D125).

## D127 - Register v4 (الحالة في آخر Phase 5)
- designed، ويتأكد في load test الـ Phase 6:
  - R1: LLM 429.
  - R2: backend بطيء.
  - R3 وR3b: الـ Ticketing.
  - R4: السلسلة.
  - R6: الـ DB وقعت.
  - R8: الـ p95.
  - R9: الـ Worker والـ Sweeper.
  - R12: ضغط على الـ DB.
  - T5a وT5b: spam والـ tokens المزيفة.
- designed، ويتأكد في evals الـ Phase 8:
  - T1: injection.
  - T2: enumeration.
  - T4: سياسة غلط توصل للعملاء. الخطر اللي فاضل: conflicts ما اتربطتش ببعض.
  - R10: جودة رد الـ LLM نزلت.
  - T7: insider.
- accepted:
  - R7: الـ embedding وقع.
  - R5: Redis، وده بعد الـ load test بس.
  - العناوين اللي الـ PII detector ما لقطهاش.
- open-owner:
  - T3: ليستة الـ P1 لسه ما اتوقعتش من Security & AI Governance.
  - T6: الـ vendors لسه ما اتوافقش عليهم (blocker 7).
- R11 (التغييرات والمفاتيح والوقت):
  - الـ release gate اتصمم.
  - الـ rollback هيتعمل في Phase 6.
  - حالات التواريخ هتتختبر في Phase 8.

## D128 - اللي بيتسلم لكل phase
### Phase 6 - Production / MLOps
- تشغيل الـ load test (D98)، وتحديد حجم Redis والطابور وسرعة الـ Worker.
- بناء الـ monitors والـ alerts (D117، D85).
- الـ runbooks والـ on-call (D124).
- الـ flags:
  - النزول على مراحل.
  - الـ kill switch.
  - الـ code-only.
- الـ release pipeline والـ rollback (D122).
- الـ secret manager، والتشفير، والـ backups، والـ retention (D110، D109).

### Phase 7 - Implementation
- الـ resilience:
  - الـ circuit breakers.
  - الـ retries.
  - ميزانية الوقت لكل خطوة.
  - الـ dynamic timeout.
  - الـ rate limits.
  - الـ outbox P1 lane.
- الـ PII detector:
  - الـ order-ref map.
  - placeholders للي المستخدم كتبه، بأسماء خاصة بيها.
  - التنضيف عند الـ ingress.
- حماية رفع السياسات (D99-D102):
  - range check.
  - مطابقة الـ PDF.
  - المقارنة بالنسخة اللي فاتت.
  - maker-checker.
  - flag الـ under review.
  - الـ conflict links.
- الـ model adapter module (D100).
- ملخص الـ handoff بيتبني بالكود (D123).

### Phase 8 - Testing & Evaluation
- مجموعات الاختبار والحدود (D112-D118 وتصليحاتها).
- حالات P1 لكل نوع × كل لغة.
- حالات PII وover-mask.
- حالات تواريخ وأوقات (R11).
- تجارب D78 بالحدود بتاعتها.

## D129 - اللي فاضل قبل ما نقول Phase 5 خلصت
- مراجعة Step 7 تخلص، ونعمل تصليحاتها.
- مراجعة نهائية واحدة على Phase 5 كلها (cross-step)، زي اللي اتعملت لـ Phase 3 × 4. بتدوّر على تناقض بين الـ steps.
- بعدها نعلن: Phase 5 CLOSED، ونبدأ Phase 6.

---

## المطلوب
موافق على D126-D129؟ ولا تغيّر أي سطر؟
