# Judge J3 — lens: fallback output quality, provider terms and cost

Date 2026-11-04 · Repo `/Users/sqin/word-dance` @ 9ab13a5 (read-only; nothing modified, real `claude` never run, no money spent) · Inputs: `facts/*.md` + `verify/*.md` (verifications override digests), the three plans, `harness-report.md`, read-only `scratchpad/quick/live-copy.db`.

## 0. What I re-verified myself before scoring (beyond the fact base)

| check | result | bears on |
|---|---|---|
| readers of `kv.claude.paused_until` / `claude.available` | `routers/words.py:324`, `routers/bank.py:150`, `jobs/scheduler.py:252`, `services/batches.py:384,498` go through `bank.ai_paused_until` (`services/bank.py:228-229`, direct kv read); `admin_ops.py:363` through `budget.paused_until`; `services/words.py:422`, `diag.py:86-89`, `admin_ops.py:196,327-331` read kv directly | D1's "gates need no edit, they call the helpers" holds **only** because D1 also rewrites `bank.ai_paused_until`, `words.content_deferred_until`, `diag`, and the admin pause route — it does list those (§2.3) |
| `backend/requirements.txt` | `pydantic`, `httpx==0.28.*`; **no `jsonschema`** (only `backend/requirements-dev.txt:3`); `deploy/install.sh:63` installs only `backend/requirements.txt` | D2's runtime `jsonschema` use would ImportError on the VPS (D3 adds the dependency, D1 does not need it at runtime) |
| `grep -ci json backend/wd/ai/prompts/*.txt` | consolidate 1 · content 1 · lookup 0 · svg 0 | D2's "1/0/1/0 (content,lookup,consolidate,svg)" is right; json_object vendors need the word "json" → the adapter must append it for lookup/svg |
| `config.py` keys | `WD_AI_TIMEOUT_{CONTENT,LOOKUP,CONSOLIDATE,SVG}_SEC` (`:338-341`), `WD_SVG_VIA_CLAUDE` (`:355`), no `WD_AI_PROVIDER`/`WD_AI_CHAIN` today | D1's A0 `.env` recipe is valid; D2/D3 introduce fresh keys |
| `frontend/src/i18n/zh.ts:97` | `provider: '来源'` exists (image providers) | D1's UI note correct |
| `common.py:32-36` | `OVERLOAD_STREAK_KEY = "claude.overloaded_streak"`, `AUTH_PAUSE = 30 min`, `OVERLOAD_PAUSE_AFTER = 6` | all three plans' "today" columns correct |
| live ledger (read-only copy) | call 33 `auth` 18:43:40Z … call 47 `auth` 02:26:20Z; call 48 `success` 02:56:21Z, `claude-sonnet-5-5`, **$0.0586 for 10 words (3,893 out tokens)**; call 49 (5 words) $0.0262 | replay tables in D2/D3 are accurate; regenerating a fallback card on Claude costs ≈ $0.006/word, not $0.005 |
| `word_contents` schema | `version` per word, `status IN ('active','superseded','rejected')`, unique active per word; `store_content(force=…)` supersedes | the "regenerate non-Claude cards" action in all three plans is feasible with `force:1`; it also changes examples a learner has already reviewed |
| `lookup.py` docstring + `_flag_invalid` (`:367-390`) | `is_english=false`/`kind='invalid'` → `is_valid_english=0, is_public=0, content_state='failed'` + bank rows flagged 「未识别为英文单词」; a validated headword with a different lemma → **merge** of the learner's word (7-day undo) | lookup is **not** "low blast radius": a weak model's false negative or wrong lemma mutates learner data (see blind spot B2) |
| `consolidate.py:263-305, 381-425` | `fill_data` auto-writes empty fields of non-seed words (undoable); `invalid_word` directly sets `is_valid_english=0,is_public=0` on user words; other verdicts are suggestions | consolidate on a weaker model has two direct mutations none of the plans guard provider-aware (B3) |
| `svg.py:131-142` | rejected SVG → `mark_failed`, never retried | all three correctly exclude svg |
| live `.env` | `WD_AI_FALLBACK_MODEL=""` | D2's rename guard is safe on the Mac |
| `scripts/eval_provider.py`, `scripts/mock_provider_server.py` | **already exist** (untracked, 2,085 + 439 lines, mock-verified across openai/anthropic/claude_cli transports, 15 error modes, `--paired`, scorecard + gates) | all three plans budget 6–12 h to *build* it |

## 1. Scores (0–10 per criterion; total /60)

| criterion | D1 CLI gateway | D2 OpenAI adapter | D3 Anthropic adapter |
|---|---|---|---|
| factual_correctness | 7 | 8 | 8 |
| failover_robustness | 5 | 8 | 8 |
| fallback_quality_and_terms | 6 | 8 | 7 |
| effort_and_operability | 6 | 7 | 5 |
| cost_and_budget_control | 6 | 9 | 8 |
| future_proofing | 4 | 7 | 9 |
| **total** | **34** | **47** | **45** |

### 1.1 Why — D1 (34)

* **Factual 7.** Dense, mostly correct citations; the live-outage replay and the kv/gate inventory check out. Deductions: it states as satisfied what is undocumented (GLM-4.7-Flash "reachable in Anthropic Messages format with client tools"), asserts the `StructuredOutput` tool path "remains" under `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1` although the binary scan found no evidence for it on the top-level `-p` path, and budgets 8 h to write a harness that exists (§3 below).
* **Failover 5.** The state machine is sound (F11 reuse, provider-scoped pauses via `budget.paused_until(provider)`, delegating helpers, immediate retry, cooldown doubling, both-down banner). The transport is the problem: the fallback shares the **same binary**, the same `~/.claude*` host, the same anthropic.com side-traffic and the same managed-settings machinery that produced the outage; a broken/updated CLI kills both slots at once (not called out); classification depends on how the CLI renders gateway bodies (unverifiable without a key); exit-0-without-request (#43607) burns retries; one fallback slot only, so Zhipu peak throttling leaves nothing automatic.
* **Quality & terms 6.** Model ranking and terms work are right (free GLM-4.7-Flash primary; 百炼 qwen3.7-flash step-up with no-training pay-as-you-go; DeepSeek third for thinking/training/outages; ModelScope out for 非商业化; Ark out for mainland-only licence; Z.ai noted). But the free model is driven through an **unforced synthetic tool call on an undocumented endpoint with client-side CLI retries and no reliable thinking switch** — the weakest of the three paths for `validate_item` pass likelihood. Credit for the most conservative kind gating (lookup+consolidate first, content only after the eval, svg never) and for keeping the key out of the Python process.
* **Effort/operability 6.** A0 today (0.25 d) is genuinely the fastest manual switch and T0–T5 are good tests with a 10-minute kill criterion; MVP 5.5 d is the shortest. Against it: a 17-variable wrapper env, CLI version floors, config-dir hygiene, proxies, and debugging through CLI stderr; if T0 fails the CLI-slot runner work is wasted.
* **Cost 6.** App-side CNY pricing from envelope tokens, `COST_SCALE` reservations, `BUDGET_FLAG` for the NaN refusal, cap 40/h, prewarm "size by limit" are all right, but thinking cannot be reliably switched off from the CLI, so the ¥15/month step-up figure is not controllable on this transport (D1 admits it and gates on T2); prewarm is not excluded from the free slot by default.
* **Future 4.** Anthropic documents the route as unsupported (reported, not analysed); request shape can change with any release; no path to a Console key other than the CLI itself; single slot; per-kind model "later". D1's own exit is D2.

### 1.2 Why — D2 (47)

* **Factual 8.** The most careful use of the verification reports (workspace host, thinking defaults, 1308, Z.ai enum gap, strict-schema model list, DeepSeek forced-tool rule, `.env` state). Two concrete gaps: `jsonschema` is a dev-only dependency and D2's file list never touches `backend/requirements.txt` (install.sh installs only that file); the harness is budgeted as new.
* **Failover 8.** Owns the transport: no CLI, no anthropic.com traffic, no managed settings on the fallback path; documented json_object mode; explicit `thinking:{type:"disabled"}`; code-first classification with the real Chinese bodies; `retry_at` for 1308/Retry-After; one in-adapter retry on short Retry-After so a job/probe collision is not an overload; prewarm excluded; sticky state; one `availability()` helper plus a grep test forbidding new direct kv reads; flap guard. Deductions: the second leg is complete-cut only (MVP has one fallback → both-down during Zhipu peak throttling), and the hard-trigger table pauses billing for 30 min like auth (should be operator-length).
* **Quality & terms 8.** Same model choice as D1/D3 but the **only fully documented path for the free model**: OpenAI endpoint + `json_object` + schema in the system message + `jsonschema` on the *original* schema before the lax pydantic mirrors + one repair + thinking off; strict `json_schema` for qwen3.7-flash. Terms matrix complete (BigModel training clause, Z.ai, Token/Coding plan prohibition, Ark 「仅在中国大陆地区」 and 「直接或间接获得收益」, ModelScope 非商业化, privacy-text line). Provenance: provider column, `model_used` defaulting to the vendor id, 7-day share tile, regenerate action, per-block label hook. Deduction: content is in `WD_AI_FALLBACK_KINDS` by default (gated only by the pre-flip L2 run), consolidate's direct mutations are not provider-aware (B3), notes-in-prompt privacy not handled (B1).
* **Effort/operability 7.** 7 d MVP (≈2 part-time weeks) before automatic failover; day 0 is one curl + regex patch + optional A0; clean operator surface (`.env` keys, `wd ai-check`, 来源 column, banner); one double (`fake_openai`) serves unit tests, smoke and the CI mock.
* **Cost 9.** Free slot est 0/cost 0; priced legs from `usage` × CNY table (tiers + peak windows in the complete cut); per-slot hourly cap; `ai_budget_overrun`; `fallback_cny_month`; **prewarm excluded from the free slot by default**; 用完即停 advice; small balances; `max_tokens` as the hard cap; thinking explicitly off so ¥15/month is actually achievable.
* **Future 7.** Every domestic vendor has an OpenAI-format endpoint (some only that); dialect table + `generic`; model id is config; nightly probe catches retirement; `FALLBACK2`. Cannot talk to an Anthropic Console key without a second adapter (+2–3 d per contract:F9).

### 1.3 Why — D3 (45)

* **Factual 8.** Most complete capability table and the only plan that catches the `requirements.txt` dependency, `count_tokens`, `HEAD /api/hello`, Ark's `output_format`, Moonshot's missing named-tool choice and 百炼's `output_config` 400 on deepseek-v4.1-flash. Deductions: harness budgeted as new (12 h) and "drops `--format openai`" (the existing harness has it and it is the documented path to compare against); "After week 1 (MVP, ≈10 person-days …)" is internally inconsistent for a part-time solo developer.
* **Failover 8.** Strongest machine: ordered N-slot chain with rotation (an expired primary pause lets a real call fail back), single-writer rule, bounded in-call capability downgrade with `caps_learned`, `quota_window` hard trigger with `until`, per-provider semaphore in the MVP, `earliest_available_at` for ETAs, every gate site enumerated incl. diag/health, `ai_fallback_unavailable`. Deduction: the free primary fallback depends on two undocumented facts (GLM-4.7-Flash served on `/api/anthropic`; `tool_use` emission) — mitigated by the day-1 curl and 百炼 as the alternative first leg, but the alternative is paid.
* **Quality & terms 7.** Terms coverage equals D2 plus the `WD_AI_ARK_ACK_TERMS` guard, the non-commercial admin banner for ModelScope and Kimi's education-advice carve-out. Quality path for the free model is weaker than D2 (D3 itself: "the only real loss is Zhipu's documented json_object mode"); the promotion bar "T2 ≥ 8/10 items" from one call is statistically thin; content on the fallback from day 1; prewarm not excluded (advice only).
* **Effort/operability 5.** ≈10 d MVP (3–5 part-time weeks) is the longest time-to-automatic-failover; 13 presets and a strategy ladder are more surface than a 10-friend app needs; on the plus side the day-1 curl set (T1 tool/auto/output_config variants, T3 error-envelope pinning, T4 VPS) is the most decisive of the three, and presets make adding a slot one key.
* **Cost 8.** Per-slot pricing with tiers/peak, `WD_CNY_PER_USD`, hourly caps, 24-h billing pauses, Batch option; thinking off. Deductions: prewarm not excluded from the free slot by default; Batch at 50 % applies to 百炼 (Zhipu Batch needs 实名 and free-model coverage is unknown).
* **Future 9.** One adapter for all Anthropic-format domestic endpoints and a future Console key; chain; presets; learned caps; `model_seen` to detect silent auto-routing after a retirement.

## 2. Direct answers under this lens

### 2.1 Is GLM-4.7-Flash good enough for Chinese learners, and which jobs should never go to it?

* No public evidence exists on the app's actual task (zh glosses + English examples with the headword rule): GLM-4.7-Flash is absent from LMArena-zh and SuperCLUE; its big sibling GLM-4.7 sits at 1495 vs Claude Sonnet 5.5 1545 (verify-alibaba:F10). The published structured-output studies say schema validity is easy and semantic accuracy is the gap (others:F15). So the decision must come from `scripts/eval_provider.py --paired` (48 Sonnet rows as the human baseline), not from boards. The harness exists; the first real call is `--kinds probe`, the second is the paired json_object run (¥0, 10–15 min at 1 in-flight).
* Predicates a 30B-A3B model is most likely to fail: headword (or inflection / ≥4-letter prefix) in ≥3 of ≤4 examples; `meaning_zh` CJK + ≤120; integer `difficulty`; verbatim `word`. D2's `jsonschema`-first validation is what keeps `difficulty: true` from becoming stored "1" (verify-contract omission 1).
* Routing verdict: **never** `generate_svg` (a rejected drawing is permanent, `image_state='failed'`); **never** prewarm (priority ≥90) on the free tier (912–1,824 calls at 1 in-flight, windowed caps unknown, `$`-stop never fires at cost 0); **gate** `generate_content` behind item pass ≥95 % / headword ≥97 %; **gate** `lookup_word` behind a per-class check (is_english false-negative ≤2 % on valid words, merge precision 100 % on the 40-case set) because its verdicts mutate learner data (B2); `consolidate_bank` is acceptable with the suggestion safety net but its two direct mutations should be downgraded to suggestions when the verdict came from a fallback (B3).

### 2.2 Free-tier concurrency and caps vs the workload and the 912-call prewarm

Steady state (≤10 friends: 25–100 content calls + a few lookups + ≤10 consolidations/day) fits one in-flight request at ≈25–45 s per 5-word call. The prewarm does not: ≈1,824 five-word calls ≈ 25–30 h serialised, inside unknown windowed caps (code 1308) and 15:00–23:00 throttling. D2's default (`WD_AI_FALLBACK_PREWARM=0`) is the right answer; the seed fill waits for Claude or runs on 百炼 for ≈¥3.3.

### 2.3 Commercial-use and training terms for a friends-circle service

| provider | commercial use of a free/paid API in your own app | training on prompts | 实名 | verdict |
|---|---|---|---|---|
| Zhipu BigModel standard key | integrating into your own product for end users is explicitly not resale; commercial use of the *free* model is grey → stay invite-only, non-monetised | anonymised training allowed, **no API opt-out** | not to call ("目前"), yes to recharge/Batch | primary free fallback; notes caveat B1 |
| Z.ai | same model family; Singapore entity | **no training, no storage** | — | preferred if a no-training promise matters; `glm-4.7-flash` presence on api.z.ai unverified (one call) |
| 百炼 pay-as-you-go | allowed | not trained without authorisation (§6.2.5) | mandatory | step-up; **never** Token Plan / Coding Plan (backend use forbidden, training authorised) |
| ModelScope API-Inference | officially 非商业化、非盈利 | — | Alibaba binding + 实名 | dev/eval reference only |
| Volcengine Ark | licence 「仅在中国大陆地区」; any 直接或间接获得收益 needs written permission | no training by default | yes | out while hosted in Tokyo |
| DeepSeek | allowed, global platform | training by default with opt-out (second-hand) | to top up | third option only |

### 2.4 Overseas (Tokyo) access

`open.bigmodel.cn` and the 百炼 Beijing endpoint answered unauthenticated probes from a US exit (both behind Alibaba GA); Tokyo itself is untested → every plan's VPS curl must run before go-live; keep base URL per slot configurable (Z.ai / 百炼 `ap-northeast-1` as alternates); adapters must run `trust_env=False` so the Mac's privoxy (for anthropic.com) never routes domestic traffic through a US exit.

### 2.5 Cost ceilings and throttling behaviour

Free slot: ¥0 with the per-slot hourly cap as the only volume guard (60/h ≫ need). Step-up: ¥15/month (qwen3.7-flash, thinking off, ≤32K tier) — measure `completion_tokens ≈ visible JSON` once before trusting it; the 30k-token consolidate prompt sits just under the ≤32K tier. When the free tier throttles (1302/1305/1308): defer with `Retry-After`/`next_flush_time`, 3 in a row → switch to the paid leg if configured, else both-down banner and 503 as today. Keep vendor balances ≤ ¥100 as the hard stop; enable 用完即停 on every 百炼 model you do not intend to pay for.

### 2.6 Provenance and regeneration policy

`ai_calls.provider` (migration 0010) + `model_requested` (vendor id) + `word_contents.model` already answer "who wrote this card". Default: keep fallback cards, show the 7-day fallback share to the admin, offer 「重新生成非 Claude 内容」 (`force:1`, ≈$0.006/word measured), and — missing in all plans — re-enqueue words that **died on the fallback** after fail-back (B6). Learner-facing: today's 「由 AI 生成」 notice covers both; a per-block model chip is the curation plan's item.

### 2.7 Privacy of prompts

Prompts carry dictionary fields, user-typed word strings (≤48 chars) and — only in consolidate — the learner's ≤120-char sanitised 备注. Under BigModel's clause that note text may be used for anonymised training with no opt-out; see B1.

## 3. Factual errors (plan sentence → contradicting evidence)

1. **D1 §1.2:** "It is the only model that satisfies all four hard constraints at once: … (c) reachable in Anthropic Messages format with client tools, which is what Claude Code's `--json-schema` actually requires" — verify-others omission 6: "the only official Anthropic page lists no models … 'GLM-4.7-Flash reachable at /api/anthropic' is an inference from the generic endpoint — plausible but undocumented"; verify-zhipu omission 4: `thinking`/`anthropic-beta`/`output_config` handling "undocumented and could not be probed without a key". D1's own risk 2 contradicts §1.2.
2. **D1 §2.2 wrapper comment and §2.11 #1:** "`CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1 # … the StructuredOutput tool path remains`" / "Neutralised for the request shape" — verify-zhipu:F7: "a tool-based fallback for the **top-level** `-p --json-schema` path is not evidenced by strings in this build; the 'unsupported' latch is"; verify-others open question 1 lists exactly this as untested. Unverified assumption presented as a neutralisation (T0 would test it, but the plan's architecture rests on it).
3. **D1 §1.1 row 1:** "Zhipu's own API offers only `json_object` and `tool_choice=auto` (zhipu:F5) — exactly what the CLI's tool path needs" — zhipu:F5 documents the **OpenAI** endpoint; the CLI needs `tools`/`tool_use` on the **Anthropic** endpoint, whose parameter support Zhipu does not publish (verify-zhipu:F6/omission 4).
4. **D1 §2.3 (8 h), D2 §2.11 (6 h, "new"), D3 §2.10 (12 h, "new") and D3 §4.3 "`--format openai` is dropped (no OpenAI adapter exists…)":** `scripts/eval_provider.py` and `scripts/mock_provider_server.py` already exist in the working tree (`git status`: untracked; harness-report.md: 2,085 + 439 lines, F17 flags, `--format openai|anthropic|claude_cli`, 15 mock modes, scorecard/gates verified against the mock on 2026-11-04). The remaining work is adoption and the first real runs, ≈0.5 d, not 6–12 h of construction; dropping `--format openai` would remove the only documented structured mode of the free model from the comparison.
5. **D2 §2.2 step 9 / §2.3:** "`jsonschema.Draft202012Validator(ORIGINAL …)`" at runtime with "`jsonschema` 4.26 (already in the venv)" and no `requirements.txt` row in §2.11 — `backend/requirements.txt` lists `pydantic`, `httpx` only; `jsonschema` is in `backend/requirements-dev.txt:3`; `deploy/install.sh:63` runs `pip install -r backend/requirements.txt` only → the adapter would ImportError on the VPS. (D3 §2.10 adds `jsonschema>=4.26` to `backend/requirements.txt`; graft it.)
6. **D1 §4.1 step 1:** "no 实名 needed to call (zhipu:F9; do 实名 only when recharging)" — verify-zhipu:F9/omission 5: the FAQ says "目前 … 并不强制要求", the privacy policy reserves 实名 for "API Key 等功能", Batch requires it, a Jan-2026 third-party post says the free API 需实名 — current practice, not a guarantee (D2/D3 recommend doing 实名 now).
7. **D3 §0 pitch:** "After week 1 (MVP, ≈10 person-days of work, so realistically week 2 for a part-time solo developer)" — 10 focused person-days for a part-time solo developer is 3–5 calendar weeks; the plan's own §7 (9–11 d MVP, 16 d complete) contradicts the week-1/week-3 framing.
8. **All three, cost of regeneration "≈$0.005/word":** the live row 48 (10 words, 3,893 output tokens) cost $0.0586 → ≈$0.006/word; immaterial, but the figure is measurable from the ledger and should be quoted from it.

## 4. Grafts (best concrete ideas from the non-winning plans, to apply on the D2 base)

From D3:
1. Keep `slots(cfg)` as an **ordered list with rotation** from day 1 (D2 already has `slots()`), so the paid step-up is a third slot and a later `anthropic_http` adapter is a slot *kind* — no redeploy; expose `WD_AI_CHAIN` only when the second leg ships.
2. `failover.record_failure` as the **single writer** of pauses/streaks/events; `handle_failure` only moves jobs (the immediate retry means the last result may be from another provider).
3. **Billing/config failures pause 24 h** (operator action), not 30 min; `quota_window` (Zhipu 1308 `next_flush_time`, ModelScope daily reset) as a **hard** trigger with an `until` instant — in the MVP, not the complete cut.
4. Add `jsonschema>=4.26,<5` to `backend/requirements.txt` and import it eagerly at start-up.
5. Preset flags `mainland_only_terms` (Ark) and `non_commercial` (ModelScope) that refuse to load / show an admin banner — the terms matrix becomes enforceable config, not a doc paragraph.
6. Record the response `model` as `ai.<p>.model_seen` to catch silent auto-routing after a free-model retirement.
7. Day-1 test T3: pin the vendor's error strings with a bogus key and a bogus model id (1211) before writing the classifier table; T1 variants (forced tool / auto / output_config) if the Anthropic path is ever used.
8. Two bars: promotion (schema ≥98 %, items ≥95 %, headword ≥97 %) and emergency-only (schema ≥95 %, items ≥85 %) — keep the slot in the chain but never first.
9. Use ModelScope `DeepSeek-V4.1-Flash` **only** as the free quality reference in the paired eval (dev, ≤200 calls/day), never in the production chain.

From D1:
10. **A0 today**: `bin/claude-fallback` + scratch-`WD_DATA_DIR` `wd claude-check` as the manual bridge until the adapter ships; T0 also answers the `forceLoginMethod` question for free and tells whether the CLI route is ever reusable.
11. Default `WD_AI_FALLBACK_KINDS=lookup,consolidate` **until the content gate passes** (D2 defaults to including content).
12. Provenance rule: `word_contents.model = model_requested` for non-Claude providers (never a gateway's echoed name); `FAKE_CLAUDE_MODEL` so provenance is testable per slot.
13. Cooldown doubling on a re-failover within 60 min (anti-flap) in the MVP; fallback hourly cap below the global 60 to leave headroom for probes and the immediate retry.
14. Keep the vendor key in a 0600 file read by the adapter (D2's `_API_KEY_FILE`), so it never appears in `GET /api/admin/config`, logs or a child environment.

## 5. Blind spots (none of the three covers)

* **B1 — learner notes leave the building.** `consolidate` is the only prompt carrying user-authored prose (≤120-char sanitised 备注, `consolidate.py:64-66,126-128`). On BigModel that text may be used for anonymised training with no API opt-out. No plan offers a per-slot `send_notes` switch (strip notes when the slot is not no-training), routes consolidate only to no-training slots (Z.ai/百炼), or tells the ten friends in the privacy text that 备注 may be processed by a domestic vendor.
* **B2 — lookup is a data-mutating job.** `is_english=false`/`kind='invalid'` from the fallback sets `is_valid_english=0, is_public=0, content_state='failed'` and flags the learner's bank rows; a validated-but-different lemma **merges** the learner's word (`lookup.py` docstring steps 1/3, `_flag_invalid` `:367-390`). All three call it low-risk and route it from day 1; the eval's blended "agreement ≥90 %" hides false negatives — a per-class gate is needed and a "fallback verdicts become suggestions only" mode would be safer.
* **B3 — consolidate's direct writes are not provider-aware.** `fill_data` auto-writes empty fields (undoable) and `invalid_word` directly flips `is_valid_english/is_public` on user words (`consolidate.py:263-305, 417-419`); nobody proposes downgrading these to suggestions when `result.provider != 'claude'`.
* **B4 — peak hours are study hours.** Zhipu's reported throttling window (15:00–23:00 CST) coincides with when friends add words and request content; every plan schedules *batch* work at night but none adds a time-of-day rule (prefer the paid leg 18:00–23:00) or measures peak-hour latency in the eval.
* **B5 — the free tier's windowed caps are unknown and unmeasured.** Code 1308 proves daily/periodic caps exist; no plan reads the console limits into config, caps *fallback calls per day*, or budgets probes + immediate retries + the nightly consolidation against the window.
* **B6 — words that die on the fallback stay dead.** Content filter 1301 on sensitive-but-legitimate English words, or three `invalid_output` strikes, end with `content_state='failed'`; all plans add a filter to regenerate *successful* fallback cards but none re-enqueues *failed-on-fallback* words after fail-back.
* **B7 — regeneration changes cards mid-review.** `store_content(force)` supersedes the active version; a learner who studied the fallback card sees different examples after regeneration. No plan decides whether to regenerate only unseen words or to keep the studied version.
* **B8 — the Z.ai no-training option is unproven for the free model.** `glm-4.7-flash` is missing from Z.ai's OpenAPI enum; the owner decision "BigModel vs Z.ai" cannot be taken until one call on `api.z.ai` confirms the model (D3 flags it; nobody puts it in day 0).

## 6. Recommendation

Base plan: **D2** (OpenAI-compatible HTTP adapter behind `runner.run_claude` + sticky provider failover), 47/60. D3 (45) loses on time-to-value and bets the free model on Zhipu's undocumented Anthropic path; D1 (34) stacks unverifiable CLI behaviours on an unverified gateway and keeps the fallback tied to the same binary, anthropic.com traffic and Enterprise managed settings that caused the outage.

Synthesised architecture: D2 adapter + D2 failover, grafting D3's ordered slot list with rotation, single-writer rule, 24-h billing/config pauses, `quota_window` hard trigger (1308/Retry-After) in the MVP, `jsonschema` in `backend/requirements.txt`, terms flags on presets, `model_seen`; and D1's A0 wrapper + scratch `wd claude-check` as today's bridge, default `WD_AI_FALLBACK_KINDS=lookup,consolidate` until the content gate passes, provenance from `model_requested`. Use the existing `scripts/eval_provider.py`; do not rebuild it.

Models per job kind: content / lookup / consolidate → **GLM-4.7-Flash** on BigModel's OpenAI endpoint (`json_object` + schema in system prompt + `jsonschema` on the original schema + one repair, `thinking:{type:"disabled"}`, batch 5, concurrency 1, timeouts ×1.5); step-up slot → **百炼 `qwen3.7-flash`** pay-as-you-go (strict `json_schema`, `enable_thinking:false`, ≈¥15/month) when GLM is paused/throttled, and optionally 18:00–23:00 CST; svg → never on a fallback; prewarm (priority ≥90) → never on the free slot; probe → every slot. ModelScope only as the eval's free quality reference; Ark/Kimi/MiniMax/SiliconFlow-8B not in the chain.

Failover rules: hard (auth incl. the managed-settings string, 403/region, 402/billing, spawn/config, quota_window) → pause that slot 30 min (billing/config 24 h), switch sticky, retry the same claimed group once; soft (3 overloaded/5xx, 2 network, 2 timeouts) → switch; never on `invalid_output`/content filter; fallback invalid streak 3 → 30-min quality pause; fail-back only via `probe.check` every 30 min or a real primary success; manual pause global; user gates = any provider available.

Scope: Day 0 (0.5 d): Zhipu standard key + console concurrency page, harness `--kinds probe` then `--paired` json_object (¥0), regex patch, A0 probe on a scratch `WD_DATA_DIR`, VPS curl. MVP 7–8 d: adapter (zhipu/bailian/generic dialects), failover, migration 0010, gates, probe/`ai-check`, admin fields, `fake_openai`, tests, requirements. Complete +4 d: second leg, admin override/health/share tile, regenerate-non-Claude + re-enqueue-failed-on-fallback, provider-aware lookup/consolidate mutations, smoke, docs.

First live tests: L1 probe exact match; L2 paired 50-word scorecard (schema ≥98 %, items ≥95 %, headword ≥97 %, lookup agreement ≥90 % with is_english false-negative ≤2 %); L3 thinking on/off token check; L4 unauthenticated POST from Tokyo; L5 failover drill with the fake auth wrapper.

Owner decisions: BigModel vs Z.ai (no-training; free model presence on api.z.ai to be confirmed); step-up vendor (百炼 account + 实名 vs GLM-4.7-FlashX on the same key); whether learner 备注 may be sent to BigModel or consolidate stays on no-training slots; content on the fallback before/after the eval; keep vs regenerate fallback cards; budget-cap failover off; 实名 now.


## 7. Recommendation as returned in the structured output (<= 2500 chars)

Base: D2 (OpenAI-compatible HTTP adapter behind runner.run_claude + sticky failover), 47/60. D3 (45) ships later, bets the free model on Zhipu's undocumented Anthropic path; D1 (34) stacks unverifiable CLI behaviours on an unverified gateway and keeps the fallback tied to the binary that caused the outage.

Synthesis: D2 adapter + failover, grafting from D3 an ordered slot list with rotation, single-writer record_failure, 24-h billing/config pauses, quota_window hard trigger (Zhipu 1308/Retry-After), jsonschema in backend/requirements.txt; from D1 the A0 wrapper + scratch wd claude-check as today's bridge and WD_AI_FALLBACK_KINDS=lookup,consolidate until the content gate passes. Reuse the existing eval harness.

Models per job: content/lookup/consolidate -> GLM-4.7-Flash via BigModel OpenAI API (json_object + schema in prompt + jsonschema on the original schema + 1 repair, thinking off, batch 5, concurrency 1, timeouts x1.5); step-up -> Bailian qwen3.7-flash pay-as-you-go (strict json_schema, thinking off, ~CNY15/month) when GLM is paused/throttled; svg and prewarm never on the free slot. ModelScope only as the eval's free reference.

Failover: hard (auth incl. managed-settings string, 403, 402, spawn/config, quota_window) -> pause slot 30 min (billing/config 24 h), switch sticky, retry the same claimed group once; soft (3 overloaded/5xx, 2 network, 2 timeouts) -> switch; never on invalid_output/content filter; fallback invalid streak 3 -> 30-min quality pause; fail-back only via probe.check every 30 min or a real primary success; user gates = any provider available.

Scope: Day 0 (0.5 d): Zhipu key, harness probe then --paired json_object run, regex patch, A0 probe on a scratch WD_DATA_DIR, VPS curl. MVP 7-8 d: adapter, failover, migration 0010, gates, probe/ai-check, admin fields, fake_openai, tests. Complete +4 d: second leg, admin override/health/share tile, regenerate-non-Claude + re-enqueue failed-on-fallback, provider-aware lookup/consolidate writes.

First live tests: L1 probe exact match; L2 paired 50-word scorecard (schema>=98%, items>=95%, headword>=97%, lookup agreement>=90%, is_english false-negative<=2%); L3 thinking on/off tokens; L4 POST from Tokyo; L5 failover drill with the fake auth wrapper.

Owner decisions: BigModel vs Z.ai; step-up vendor (Bailian + shiming vs GLM-4.7-FlashX); may learner notes go to BigModel; content on fallback before/after eval; keep vs regenerate fallback cards; budget-cap failover off; shiming now.
