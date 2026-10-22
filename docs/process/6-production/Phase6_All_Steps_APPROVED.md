# Phase 6 - Production / MLOps - كل الـ steps والقرارات المقترحة

Adaptive AI Gateway - NovaCart - القرارات D130-D160 - APPROVED 2026-10-21

القاعدة: التعلم الأول والـ portfolio تاني، ومن غير تعقيد شركات كبيرة مالوش لازمة. أي رقم مكتوب جنبه design choice يبقى اقتراح مني، مش من السياسات.

الجهاز اللي هنشتغل عليه: لابتوب i7، و16 GB RAM، ومن غير GPU. يعني مفيش LLM محلي، والـ LLM هيفضل عن طريق OpenRouter.

اللي Phase 6 بتعمله في الشغل الحقيقي: بتاخد التصميم وتخليه نظام ينفع يتشغّل في مكان معروف، وتعرف تراقبه، وتنزّل عليه نسخ جديدة بأمان، وترجع لنسخة قديمة لو حاجة باظت، وتعرف تتصرف وقت المشكلة. من غيرها هيبقى عندك تصميم كويس وكود شغال على جهازك بس، ومحدش يعرف هو شغال صح ولا لأ.

---

## Step 1 - Deployment topology و environments

الـ step دي بتجاوب على 4 أسئلة: النظام هيشتغل فين؟ كام نسخة منه؟ مين يكلم مين؟ والإعدادات والأسرار متخزنة فين؟

### D130 - النظام هيشتغل فين
- الخيارات:
  - (أ) Kubernetes: بيكبّر النظام لوحده، وبيصلّح نفسه. بس معقد جداً على مشروع شخص واحد، وتقيل على 16 GB.
  - (ب) Docker Compose على جهاز واحد. **(المقترح)**
  - (ج) cloud managed services (DB وRedis جاهزين): أسهل في التشغيل، بس بفلوس، والجزء التعليمي بيقل.
- المقترح:
  - Docker Compose: على اللابتوب للـ dev، وعلى VM واحدة صغيرة لو حبيت تعمل demo أونلاين.
  - هنشغّل 2 Gateway instances ورا nginx، علشان نثبت إن الـ Gateway stateless (D11).
- اللي هنخسره: الـ auto-scaling والـ self-healing الكاملين. هنعوّض جزء منهم بالـ restart policy والـ healthchecks (D154).
- ليه: Kubernetes مش هيعلمك حاجة عن الـ AI Gateway نفسه، والـ Compose بيوضّح كل container بيعمل إيه.

### D131 - الـ environments
- dev:
  - اللابتوب، مع mocks لكل الأنظمة اللي برّه: الـ backend، والـ Ticketing، والـ website.
  - الـ LLM: يا mock، يا OpenRouter بموديل رخيص.
- staging:
  - نفس الـ Compose بإعدادات زي الـ prod، بيتشغّل في الـ CI.
  - corpus وهمي، وvendors وهمية.
- demo (اختياري):
  - VM واحدة، وبيانات وهمية بس (synthetic).
  - ASSUMPTION: الـ demo مش NovaCart الحقيقية، فمفيش بيانات عملاء حقيقيين. علشان كده blocker 7 ما بيمنعهاش.
  - النزول الحقيقي لعملاء حقيقيين يفضل واقف لحد ما blockers 1-8 يتقفلوا (D119).

### D132 - الـ containers
- image واحدة للـ Gateway وللـ Worker، لأنهم نفس الكود، بس كل واحد بيشتغل بأمر مختلف.
- الـ versions متثبتة (pinned)، والـ container بيشتغل من غير root.
- كل container ليه endpoints للصحة:
  - liveness: هل الـ process عايش؟
  - readiness: هل جاهز ياخد طلبات؟ يعني الـ DB والـ Redis متوصلين.
- الـ mocks: كل واحد container لوحده.
  - Flask backend.
  - Ticketing، وليه أوضاع: 4xx، و5xx، وبطيء.
  - website.
  - LLM، وليه أوضاع: 429، وبطيء، ورد بايظ.
- Redis وPostgreSQL (معاه pgvector) من images رسمية.

### D133 - الـ config والـ secrets
- الـ config اللي بيغيّر سلوك النظام بيتحفظ كـ files في الـ git، وكل file ليه version id:
  - ليستة الـ P1.
  - الـ templates.
  - الـ thresholds.
  - اسم الموديل والـ route.
- الإعدادات اللي بتختلف من environment للتاني: environment variables.
- الـ secrets (مفاتيح الـ API، وباسورد الـ DB):
  - في الـ dev: ملف .env عمره ما يتعمله commit.
  - في الـ demo: Docker secrets (design choice).
  - ده التطبيق البسيط لـ "secret manager" اللي في D110.
- الـ CI فيه secret scanning، علشان لو مفتاح اتعمله commit بالغلط، يتمسك.

### D134 - الـ network والـ edge
- nginx قدام الـ Gateway، وبيعمل 3 حاجات:
  - load balancer.
  - TLS (في الـ demo: Let's Encrypt).
  - rate limit عند الـ edge (T5b).
- البورت الوحيد المفتوح للخارج هو بورت nginx.
- Redis وPostgreSQL على network داخلية بس.

---

## Step 2 - Release pipeline (CI/CD)

في الشغل الحقيقي، الـ step دي بتضمن إن أي تغيير يعدّي على نفس البوابة قبل ما يوصل للمستخدم: يتبني، ويتختبر، ويتراجع، وينزل، ولو باظ نرجع. من غيرها، كل deploy يبقى مخاطرة.

### D135 - الـ CI
- GitHub Actions.
- مع كل PR بيتعمل:
  - lint.
  - type check.
  - unit tests.
  - build للـ image.
  - secret scan.
  - dependency scan.
- ليه GitHub Actions: مجاني للـ repos العامة، وبيظهر في الـ portfolio.

### D136 - الـ eval gate جوه الـ CI
- مع كل PR:
  - الفحوصات اللي بالكود بس (deterministic).
  - مجموعة صغيرة من L3 (smoke)، بموديل رخيص أو بالـ mock.
- قبل أي release (tag):
  - eval كامل (D80): L1 وL2 وL3، وكل حالة 3 مرات (D113).
  - الحدود بتاعة Step 6 في Phase 5.
- حد للتكلفة في كل تشغيل للـ eval. الرقم بتحدده إنت، لأنها فلوسك (design choice).
- لو أي hard gate فشلت، الـ release يقف.

### D137 - الـ versioning
- كل حاجة بتغيّر سلوك النظام ليها version:
  - الكود: git tag، بنظام semver.
  - الـ prompts: files ليها id.
  - الموديل والـ route.
  - ليستة الـ P1.
  - الـ templates.
  - الـ config.
- كل رد بيتسجل في الـ audit ومعاه الـ versions دي (D77)، فلو حاجة باظت نعرف أنهي نسخة السبب.

### D138 - الـ flags
- table في الـ Gateway DB، ومعاها cache محلي قصير (من المراجعة النهائية لـ Phase 5، تصليح 7).
- الـ flags:
  - ai_enabled: ده الـ kill switch.
  - rollout_percent: لكل role لوحده.
  - code_only_mode.
  - shadow_mode.
- الـ ops بس هما اللي يغيّروها، من CLI أو من الـ CS Console، وكل تغيير بيتسجل في الـ audit وبيطلّع alert.
- لو الـ flags ما اتقريتش = AI off.

### D139 - الـ migrations
- Alembic.
- طريقة expand / contract: نضيف الأول، ونشيل في release بعدها. علشان الـ schema تفضل شغالة مع النسخة اللي قبلها لمدة release واحد (D122).
- الـ migration بتشتغل كـ job لوحدها قبل الـ deploy.

### D140 - الـ deploy والـ rollback
- الـ deploy:
  1. نجيب الـ image الجديدة بالـ tag.
  2. نشغّل الـ migration.
  3. نعيد تشغيل الـ Gateway instances واحد ورا التاني (rolling)، علشان الخدمة ما تقفش.
- الـ rollback: نرجع للـ tag اللي قبله. ده ممكن لأن الـ schema متوافقة.
- السياسات مش بترجع لنسخة قديمة. بتستخدم الـ hold بتاع D99.
- طريق طوارئ لليستة الـ P1:
  - L3 + مجموعات الـ P1 بس.
  - مراحل نزول أسرع.
  - توقيع Security & AI Governance.

---

## Step 3 - Observability

في الشغل الحقيقي، الـ observability هي إنك تعرف من برّه النظام إيه اللي بيحصل جواه: هل هو شغال؟ بطيء فين؟ بيغلط فين؟ بيصرف قد إيه؟ من غيرها هتعرف إن فيه مشكلة لما العملاء يشتكوا.

### D141 - الـ stack
- الخيارات:
  - (أ) Prometheus + Grafana + Loki، كلهم open source وبيشتغلوا في Compose. **(المقترح)**
  - (ب) خدمة مدفوعة (Datadog وأمثالها): سهلة، بس بفلوس، والتعلم أقل.
  - (ج) OpenTelemetry كامل بالـ traces (Tempo): تعليمي، بس تقيل.
- المقترح: (أ)، والوقت اللي كل خطوة بتاخده بيتقاس كـ metrics (histograms) بدل الـ distributed tracing. الـ OpenTelemetry ممكن نضيفه في Phase 9 لو احتجناه.

### D142 - الـ logs
- JSON، وكل سطر فيه request_id والـ versions.
- مفيش PII ولا نص رسايل (D108).
- بتطلع على stdout، والـ Loki بيجمعها.

### D143 - الـ metrics
الحاجات اللي محتاجينها من Phase 5:
- p95 لكل خطوة، وللطلب كله (D91، D98).
- نسبة فشل D66، وحالة كل circuit، وهل الـ Degraded شغال (D85، D117).
- طول الطابور، وأقدم تذكرة PENDING (والـ P1 لوحدها)، وعدد الـ FAILED (D87).
- نسبة الـ tokens المزيفة، وعدد مرات الـ JWKS refresh، والطلبات اللي اتمنعت بسبب الـ rate limit.
- ذاكرة Redis والـ evictions، ووقت الانتظار على الـ DB pool.
- نسبة الإخفاء الزيادة (over-mask)، والـ false P1 كل أسبوع.
- التكلفة في اليوم.

### D144 - مراقبة الـ LLM وتكلفته
- كل نداء للـ LLM بيتسجل في table عندنا، وفيه:
  - الموديل.
  - الـ route.
  - الـ tokens.
  - الوقت.
  - التكلفة.
  - الـ versions.
  - هل D66 عدّت ولا لأ.
- من غير نص الرسايل.
- الخيارات:
  - (أ) table عندنا، وGrafana بتعرضها. **(المقترح)**: بسيط، وبيعلّمك إيه اللي بيتقاس فعلاً.
  - (ب) Langfuse self-hosted: أداة جاهزة كويسة، بس محتاجة services زيادة. ممكن نضيفها بعدين.

### D145 - الـ dashboards
- 3 dashboards بس:
  1. Health: الـ latency، والأخطاء، والـ circuits، والـ Degraded.
  2. AI quality: D66، والـ P1، والـ PII، والتكلفة.
  3. Queue / Outbox: الطابور، وأقدم PENDING، والـ FAILED، والـ Worker.

### D146 - الـ alerts
- Grafana alerting بيبعت على قناة واحدة (Telegram أو email)، لأنك شغال لوحدك.
- نوعين:
  - فوري: أي حاجة ليها علاقة بالـ P1، أو PII، أو الـ circuit اتفتح، أو الـ Worker وقع.
  - ملخص يومي: الباقي.
- كل alert فيه لينك للـ runbook بتاعه (D124).
- الـ Worker بيتراقب من برّه (D87): لو الـ metrics بتاعته وقفت، ده لوحده بيطلّع alert (dead man's switch).

---

## Step 4 - تشغيل الـ load test

في الشغل الحقيقي، الـ load test بيأكد الأرقام اللي خمّناها، وبيوري النظام هيقع فين قبل ما الناس تشوفه بيقع. كل الأرقام المبدئية في Phase 5 بتتراجع هنا.

### D147 - الأداة
- الخيارات:
  - (أ) Locust: Python زي باقي المشروع. **(المقترح)**
  - (ب) k6: JavaScript، وأسرع.
- المقترح: Locust، علشان لغة واحدة في المشروع كله.

### D148 - الـ mocks في الـ load test
- عمرنا ما بنكلم vendor حقيقي في الـ load test، علشان التكلفة وعلشان T6.
- الـ mock LLM نقدر نتحكم فيه: الوقت اللي بياخده، ونسبة الـ 429، ونسبة الردود البايظة (R10).
- الـ mock Ticketing نقدر نتحكم فيه: بطيء، أو 5xx، أو 4xx (R3، R3b).

### D149 - فين وقد إيه
- اللابتوب ما يقدرش يحاكي 1,000 لـ 2,000 مستخدم وكل الـ services شغالة عليه. ده كلام صريح، مش تقصير.
- السيناريو العادي (20 لـ 50 مستخدم) بيتشغّل كامل على اللابتوب.
- سيناريو الذروة:
  - إما على VM مؤقتة لساعات قليلة.
  - أو بحجم أصغر بنسبة مكتوبة، ونكتب جنب النتيجة إنها اتعملت بحجم أصغر (ASSUMPTION).
- سيناريوهات D98 كلها اتعملت، ومعاها polling ورا نفس الـ IP، والـ code-only.

### D150 - اللي بيطلع من الـ load test
تقرير sizing فيه:
- حجم ذاكرة Redis.
- حجم الطابور.
- سرعة الـ Worker.
- أحجام الـ DB pools.
- مراجعة أرقام الـ Degraded والـ circuits.
- قرار قبول R5.
- النتايج بتتسجل كدليل للـ go / no-go (D119).

---

## Step 5 - Operations

في الشغل الحقيقي، الـ operations هي إيه اللي بيحصل بعد النزول: مين بيصحى لو حاجة وقعت، وبيعمل إيه، وإزاي نرجّع الداتا لو ضاعت. الفكرة إن التصرف يبقى مكتوب، مش ارتجال.

### D151 - الـ runbooks
- files في الـ repo، في folder اسمه runbooks.
- واحد لكل بند في D124.
- كل runbook فيه:
  - العلامة اللي بتكشف المشكلة.
  - نتأكد منها إزاي.
  - نعمل إيه.
  - نرجع إزاي.
  - مين المسؤول.

### D152 - الـ on-call
- إنت الـ on-call، لأنك شخص واحد.
- اللي بيصحّيك: الـ alerts الفورية بس (D146).
- باقي الـ alerts في الملخص اليومي.
- في الـ demo: الـ on-call في ساعات محددة بتحددها إنت، وده مكتوب في الـ README.

### D153 - الـ backups
- pg_dump للـ Gateway DB كل يوم، متشفر، ومتخزن برّه الجهاز.
- ملفات الـ PDF بتاعة السياسات بيتعملها backup برضه (D23).
- تجربة restore قبل كل release مهم، وبتتسجل كدليل.
- الـ RPO والـ RTO الحقيقيين بيحددهم الـ owner (D125). في الـ demo: RPO 24 ساعة، وRTO ساعة (design choice، للتعلم بس).

### D154 - صحة النظام الأساسية
- restart policy (unless-stopped) للـ Gateway وللـ Worker، ومعاهم healthchecks. ده بيقفل "إعادة تشغيل الـ Worker لوحده" (R9).
- مزامنة الوقت (NTP) على الـ host نفسه (D89).
- الـ edge rate limit من nginx (D134).

---

## Step 6 - LLMOps

في الشغل الحقيقي، الـ LLMOps بيعامل الـ prompts والموديل كأنهم كود: ليهم versions، وبيتختبروا، وبيتراقبوا بعد النزول. ده لأن الـ provider ممكن يغيّر الموديل من غير ما يقولك، فالجودة تنزل وإنت مش واخد بالك.

### D155 - مكان الـ prompts والموديل
- في الـ git، كـ files ليها ids، ومفيش أداة registry منفصلة.
- أي تغيير بيعدّي على PR وعلى الـ release gate (D122).
- ليه: بسيط، وكل التاريخ موجود في الـ git.

### D156 - evals بتشتغل لوحدها بشكل دوري
- كل ليلة: canary صغير، حوالي 20 حالة (design choice)، علشان نلحق لو الـ provider غيّر الموديل (R10).
- كل أسبوع: L3 كامل.
- مع أي تغيير: الـ eval الكامل.
- التكلفة ليها حد بتحدده إنت (D136).

### D157 - مراقبة الجودة والـ feedback
- إشارات الـ production كل أسبوع:
  - فشل D66.
  - نسبة الـ handoff لكل intent.
  - الـ false P1.
  - الـ over-mask.
- مراجعة عينة صغيرة من المحادثات المتنضفة بس، وبمدة احتفاظ يحددها الـ owner (D109).
- زرار feedback للعميل (👍/👎) محتاج اتفاق مع صاحب الـ website. ده سؤال للـ owner، وما يتعملش من غيره.
- أي غلطة حقيقية بتتحول لحالة اختبار جديدة.

### D158 - الـ re-index للسياسات
- لما سياسة تتفعّل: الـ Worker بيعمل embedding لأجزائها (D49)، وحالة الـ indexing بتبان.
- لو غيّرنا موديل الـ embedding:
  - نعمل re-index كامل في index جديد.
  - نشغّل L1 عليه.
  - نبدّل للـ index الجديد مرة واحدة (blue / green).
  - القديم يفضل موجود لحد ما نتأكد.

### D159 - التحكم في التكلفة
- حد يومي للتكلفة بيطلّع alert. الرقم بتحدده إنت (design choice).
- الحدود اللي موجودة من قبل: tokens لكل جلسة (D59)، والـ rate limits (D86).
- لو التكلفة عدّت الحد، الـ alert بيطلع والقرار ليك: تفضل كده، ولا تحوّل لـ code_only_mode مؤقت.

---

## Step 7 - Exit checklist

### D160 - شروط خروج Phase 6
- كل بنود التسليم بتاعة D128 ليها قرار هنا.
- الـ Ticketing contract tests (blockers 1، 2، 8) مكتوبة كخطة، وبتتشغل على الـ mock دلوقتي، وعلى الـ Ticketing الحقيقي لما يبقى موجود.
- كل رقم مكتوب جنبه design choice.
- مراجعة مستقلة لكل Phase 6، وبعدها مراجعة نهائية بتدوّر على تناقض بين الـ steps.
- بعدها Phase 7: Implementation.

---

## أسئلة ليك (إنت هنا الـ owner بتاع الـ demo)
1. حد التكلفة في كل تشغيل eval، وفي اليوم.
2. هل هتعمل demo أونلاين على VM، ولا لوكال بس.
3. قناة الـ alerts: Telegram ولا email.

## أسئلة للـ owner الحقيقي (بتتضاف لـ D125)
1. زرار الـ feedback في الـ website.
2. مدة الاحتفاظ بعينات المراجعة.

## المطلوب
موافق على D130-D160؟ ولا تغيّر أي سطر؟ ولو حابب، نمشي step step بأسئلة زي ما كنا بنعمل.
