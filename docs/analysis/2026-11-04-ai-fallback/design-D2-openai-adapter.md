# Design D2 — "Own the transport": an OpenAI-compatible HTTP adapter behind `runner.run_claude` plus automatic provider failover

Date 2026-11-04 · Repo `/Users/sqin/word-dance` @ `9ab13a5` (read-only; nothing modified) · Owner question (binding): 「如果 Claude 无法使用，评估匹配国内最优的免费模型做一个备选；当 Claude 不成功，直接用备选方案」.
Fact base: digests `facts/{contract,zhipu,alibaba,bytedance-deepseek,others-and-cli}.md` and verification reports `verify/*.md` (verifications override digests). Citations: `(slice:Fn)` = digest finding, `(verify slice:Fn)` = verification report, `file:line` = repo @ 9ab13a5, URLs as given in the fact base. Anthropic policy/licensing is out of scope and not analysed; one sentence from Anthropic's docs is reported verbatim where the fact base requires it.

Scope of this design: (1) the best FREE domestic fallback model plus a paid-but-almost-free step-up; (2) automatic failover: when the Claude path fails, the same job runs on the fallback immediately, and the app fails back when Claude recovers. The transport for the fallback is an HTTP adapter speaking the OpenAI chat-completions format, owned by the app (no `claude` binary, no Anthropic-format gateway tricks on the fallback path).

---

## 0. Pitch

**After day 1 (≈2 hours, zero code in the repo):** the owner has a Zhipu BigModel standard API key (no Coding Plan, no 实名 needed to call — `目前调用 API 并不强制要求实名认证`, verify zhipu:F9), has sent the app's real 10-word content prompt (`scratchpad/fallback/measure/content_user_prompt_cet4_top10.txt`, 6.3 KB) to `glm-4.7-flash` with `response_format:{type:json_object}` and `thinking:{type:disabled}`, and knows three numbers: does the JSON validate against `content_v1.json`, how many of the 10 items pass `content.validate_item`, how long it took (expect 40–60 s). The console rate-limit page has told them the real concurrency for the free model. If Claude is down *today*, a manual stop-gap exists (§4, "A0 wrapper") — it is not the design, only a switch the admin flips by hand.

**After week 1 (≈3 developer-days of the 7-day MVP):** `backend/wd/ai/providers/openai_http.py`, `ai/failover.py` and migration `0010_ai_provider.sql` are merged behind `WD_AI_PROVIDER=auto`; the existing `fake_claude.py` in `auth` mode plus the new `tests/fake_openai.py` prove end to end that a managed-settings failure (the exact string in `ai_calls` 33–47) flips `kv.ai.active_provider` to `fallback`, that the *same claimed group* is answered by the fallback in the same handler pass, that the ledger row carries `provider='fallback'` and `word_contents.model='glm-4.7-flash'`, and that a successful recovery probe flips back. `wd ai-check --provider fallback` validates the real key against `probe_v1` for ¥0.

**After week 3 (MVP complete and live, complete cut started):** the Tokyo VPS runs with `WD_AI_PROVIDER=auto`, `WD_AI_FALLBACK_MODEL=glm-4.7-flash`, batch 5, concurrency 1, SVG and prewarm excluded from the fallback. The admin AI tab shows 「当前来源」, the failover banner, a 来源 column in the ledger, and a provider segmented control (auto / 仅 Claude / 仅备用). The eval scorecard (50 words, 2 lookups, 1 consolidation) exists for GLM-4.7-Flash and for the step-up `qwen3.7-flash` (百炼 pay-as-you-go, ≈¥15/month at 100 content calls/day), so the decision "free is good enough" vs "pay ¥15" is made from the app's own `validate_item` pass rate, not from leaderboards. A six-hour Claude outage like 2026-11-02/03 costs the learners nothing: lookups keep answering, content keeps generating, and the ledger says which model wrote what.

---

## 1. Fallback model choice

Workload used for every cost figure (task brief + contract:F3): ≈2k input + ≈4k output tokens per 10-word content call, 25–100 content calls/day, 150 lookups/month, ≤10 consolidations/day (typical prompt 5 KB, worst 56.5 KB ≈ 17k tokens), ≤40 SVG/day, one-time seed prewarm 912 calls; CNY per 1M tokens, list prices read 2026-11-04.

### 1.1 Ranked table

| # | Model · provider | Cost/month at the workload | Free-tier limits | Structured-output mode this design uses | Context / max out | Endpoint format | Terms / data policy | Overseas (Tokyo) access | Quality evidence | Stability |
|---|---|---|---|---|---|---|---|---|---|---|
| **1 (primary fallback)** | **GLM-4.7-Flash** · Zhipu BigModel `https://open.bigmodel.cn/api/paas/v4` (international twin `api.z.ai/api/paas/v4`) | **¥0** (price list `免费 / 免费`, verify zhipu:F1); no token cap; "free until replaced" — terms allow ending free services, historical cadence ≈12 months with auto-routing (zhipu:F2) | concurrency-based, numbers console-only; third parties report **1 in-flight request**, peak-hour throttling; windowed caps surface as code 1308/HTTP 429; 1302 account limit, 1305 platform overload (verify zhipu:F3, omission 2) | `json_object` + schema pasted into the system message + `jsonschema` on the original schema + one repair re-ask; `thinking:{type:"disabled"}` (4.7 series defaults ON; `tool_choice` is `auto`-only, no `json_schema`) (verify zhipu:F5) | 200K / 128K | OpenAI chat-completions (also `/api/anthropic`, undocumented model list) | standard API: integrating into your own product for your end users is explicitly allowed; commercial use of the free model is grey → stay invite-only/non-commercial; mainland privacy policy allows **anonymised training with no API opt-out**; Z.ai promises no training/no storage (verify zhipu:F10) | reachable from a US exit in 1.3 s (Alibaba GA front), terms contemplate overseas use; no geo-block found (verify zhipu:F12) | 30B-A3B; BFCL v3 74.6; τ²-Bench 79.5; **absent from LMArena-zh and SuperCLUE**; no app-task score → eval harness decides (zhipu:F13, others:F15) | **weak point**: documented platform-level throttling, June-2026 multi-day 429/1305 incident (Coding-Plan subscribers), Nov-2026 nightly gateway failures (free Start Plan), no status page (verify zhipu:F14) |
| **2 (step-up)** | **qwen3.7-flash** · 阿里云百炼 pay-as-you-go, Beijing workspace host `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` (legacy `dashscope.aliyuncs.com` frozen since 2026-09-30, verify alibaba:F4) | **≈¥15/month** at 100 content calls/day **only with thinking disabled** (0.2/0.8 ≤32K tier; verify alibaba:F11); `qwen3.8-flash` ≈¥54; seed prewarm ≈¥3.3 | one-time 1,000,000 tokens per model, 90 days, Beijing only, 实名 required; `用完即停` **off by default** (silent billing after the grant) (verify alibaba:F1) | `response_format:{type:"json_schema", strict:true}` (supported exactly on the Qwen3.7/3.8 Flash/Plus/Max series) + `enable_thinking:false` + the same validation/repair (verify alibaba:F3) | 1M / 131K | OpenAI-compatible (+ Anthropic `/apps/anthropic` with `output_config`) | pay-as-you-go inputs **not trained on** (服务协议 §6.2.5); Token Plan / Coding Plan forbid backend use and authorise training → never use them (verify alibaba:F7); 实名 + Alibaba Cloud account | Beijing endpoint answers from overseas (401, not geo-blocked); region keys siloed; Tokyo region exists at Beijing prices but without free quota (verify alibaba:F6) | no public LMArena/SuperCLUE score for 3.7-flash; sibling Qwen3.8-Flash SuperCLUE 66.4 (third-party compilation, weak); strict schema removes the structural failure class entirely | SLA 99.9 % on both hosts; 30,000 RPM / 5M TPM; retirements with ≥3-month notice; no 2026 outage advisory found (alibaba:F12) |
| 3 | deepseek-flash (DeepSeek-V4.1-Flash-1017) · DeepSeek | ¥54 off-peak / ¥108 peak (thinking off) | none (no free tier, no sign-up credit; 实名 to top up) | `json_object`, or forced strict tool `tool_choice:{type:function}` **only with `thinking:{type:disabled}`** (forced tools 400 in thinking mode); `output_config.format` ignored on its Anthropic path (verify bytedance:F4) | 1M / 384K | OpenAI + Anthropic | ToS defers to privacy policy: training by default with opt-out; single global platform, PayPal/cards (bytedance:F5) | best Tokyo fit (global platform) | LMArena-zh #30 1523 (vs Claude Sonnet 5.5 1545) — strongest cheap model | **19th major outage of 2026 on 2026-11-03** (bytedance:F19) |
| 4 | GLM-4.7-FlashX / GLM-5.3-Flash · Zhipu (same key as #1) | ¥26–55 / ¥29–58 | — | FlashX: as #1 but paid tier concurrency; 5.3-Flash: **forced thinking, cannot be disabled** → output cost unpredictable | 200K / 1M | as #1 | as #1 | as #1 | GLM-5.3-Flash LMArena-zh #20 1530 (best "Flash" on both zh boards) | as #1 (same platform) |
| 5 | Doubao-Seed-2.1-lite · Volcengine Ark (2.0-mini ¥25) | ¥37 | one-time per-model quota, activity-dependent (verify bytedance:F7) | `json_schema strict` (beta); `thinking:disabled`; **default `max_tokens` 4k → must set ≥8k** (verify bytedance:F8) | 1M / 256K | OpenAI + Messages API | platform terms grant use **「仅在中国大陆地区」** and require written permission for any 「直接或间接获得收益」; no training by default (verify bytedance:F10) | outside the licence wording from Tokyo → BytePlus ModelArk (USD, separate account) instead | SuperCLUE 2026-07: Doubao-Seed-2.1-pro 65.95 (lite unscored) | consumer-app outages; API undocumented |
| 6 | DeepSeek-V4.1-Flash / GLM-5.2 / Qwen3.5-397B · ModelScope API-Inference | ¥0 | 2,000 calls/day/account, **≈200/day per model**, single concurrency, reset 00:00 UTC+8, quotas cut without notice (verify alibaba:F8) | `json_object` (OpenAI endpoint) | model-dependent | OpenAI (+ Beta `/v1/messages`) | officially **「非商业化，非盈利」**, for 体验/测试, no SLA; Alibaba Cloud binding + 实名 | reachable | highest free quality (LMArena-zh 1523–1525) | model list churns (Kimi-K2, Qwen3-235B gone); Beta Anthropic mode |
| 7 | Qwen3-8B · SiliconFlow free tier | ¥0 | fixed RPM/TPM (console-only); 实名 unlocks all free models (verify others:F4) | `json_object` only | 32K-class | OpenAI + `/v1/messages` | no training, no long-term storage (privacy policy 2026-07-30) | reachable; optional IP whitelist | IFEval 83–85, BFCL 60–68 — a different class from the ≥30B Flash models (others:F15) | free set rotates |
| 8 | MiniMax-M3 (¥113) · Kimi K3.1 Pro (¥894, thinking always on, effort default `max`) | too expensive or unpredictable for this job | — | forced tool / Anthropic `output_config` | 1M | both | Kimi licenses inputs for 模型服务优化 | — | Kimi best quality | — |
| — | Baidu ERNIE-Speed/Lite (retired 2026-06-09), Tencent hunyuan-lite (retired 2026-06-22), iFlytek Spark Lite (8K/4K, QPS≈2, no tool calling) | — | — | — | — | — | — | — | — | not viable (verify others:F1–F3) |

### 1.2 Decision

**Primary fallback = Zhipu GLM-4.7-Flash on BigModel's OpenAI-compatible endpoint.** It is the only capable, currently free, commercially usable (standard-API) domestic model with a documented thinking switch and 200K context, it needs no 实名 to start, and its stability problems are exactly what the failover machinery already handles (defer/backoff/provider pause/second leg). Its weakness — `json_object` with no server-side schema enforcement — is covered three times: the schema is pasted into the system message, the adapter validates against the **original** schema with `jsonschema` 4.26 and re-asks once with the validator's messages, and the handlers' `validate_item`/`apply_item` gates stay as they are. BigModel over Z.ai by default (支付宝/微信, mainland latency, `glm-4.7-flash` **not** in Z.ai's OpenAPI model enum, verify zhipu omission 6); Z.ai if the owner wants the no-training promise (§6).

**Step-up = 百炼 `qwen3.7-flash` (pay-as-you-go, thinking off, strict `json_schema`), one-line upgrade to `qwen3.8-flash`.** Cheapest paid model that removes the structural-failure class (strict schema on the OpenAI path), 1M context, rate limits three orders of magnitude above the workload, pay-as-you-go data not trained on, 99.9 % SLA, and a *different* platform from Zhipu so a Zhipu-wide throttle does not take both legs down. Price is not a differentiator below the Plus tier (alibaba:F11); DeepSeek-flash loses on outage record and 4–7× price, Doubao on the mainland-only licence wording for a Tokyo server, GLM-5.3-Flash on forced thinking. Same-key alternative when the owner refuses a second account: GLM-4.7-FlashX (§6).

The step-up is wired as an optional **second leg** (`WD_AI_FALLBACK2_*`, complete cut): free first, paid only when the free leg is paused or throttled, so the normal month still costs ≈¥0.

### 1.3 Job kinds → models

| Job kind | Claude (primary) | Fallback leg 1 (GLM-4.7-Flash) | Step-up / leg 2 (qwen3.7-flash) | Notes |
|---|---|---|---|---|
| `generate_content` (users' marks, admin regenerate) | yes, batch 10 | yes, **batch 5**, `max_tokens` 8192, timeout 180 s × 1.5 | yes, batch 10 (strict schema, fast) | headword-in-example rule is the predicate weaker models fail most (contract:F4) → eval gate |
| `generate_content` from a **prewarm plan** (priority ≥ 90) | yes | **no by default** (`WD_AI_FALLBACK_PREWARM=0`): 912 calls at 1 concurrency on a throttled free tier is 15–30 h and `kv prewarm:*:spent` never grows at cost 0 (contract:F12) | yes if the owner wants the fill now (≈¥3.3) | prewarm jobs defer to the primary's resume instead |
| `lookup_word` (user adds a word; latency-sensitive) | yes, 20 strings | yes, 20 strings, `max_tokens` 4096 | yes | `lookup_system.txt` contains no "JSON" → the adapter appends the json_object instruction (DeepSeek/百炼 require the word; verify alibaba:F3) |
| `consolidate_bank` (nightly + 立即整理) | yes | yes (200K ≫ 17k-token worst case), `max_tokens` 12288 | yes | the apply rules already downgrade unsafe suggestions to `ok` (`consolidate.py:402-408`) |
| `generate_svg` | yes | **no** (`svg` not in `WD_AI_FALLBACK_KINDS`): a rejected SVG leaves `image_state='failed'` and is never retried (`svg.py:131-142`) — permanent damage from a weaker drawer | no | SVG jobs simply defer while failover is active; photos keep coming from Wikimedia/Openverse |
| `probe` | tiered CLI probe (`probe.check`) | one tier-less `probe_v1` call (`wd ai-check --provider fallback`) | same | exact-match answer is the cheapest enum/array go/no-go |

---

## 2. Architecture

### 2.1 Where it hooks in (verified seam)

The real seam is the **function** `wd.ai.runner.run_claude` (`runner.py:383-495`): `common.claude_call` (`common.py:133-184`) calls it after `budget.reserve`; `probe._attempt` (`probe.py:73-88`) calls it with CLI-only kwargs `tier=` / `fallback_on_usage_error=`; the `ClaudeRunner` protocol / `runner.Runner` class is never instantiated (verify contract:F1). Handlers consume `ok/status/structured/cost_usd/model_used/call_id/error` and rebuild `ClaudeResult` by keyword (`content.py:443`, `lookup.py:574`) → new fields get defaults; no handler changes are needed. Statuses stay the fixed set `ledger.STATUSES` (`ledger.py:21`; CHECK at `0001_init.sql`/`SCHEMA.sql:512`); provenance of content needs no schema change (`word_contents.model` ← `result.model_used`, `content.py:423`, `:213-218`); the ledger gets one additive column.

Design rule: **everything provider-specific lives below `run_claude`; everything failover-specific lives in `ai/failover.py` and is called only from `common.claude_call`, `common.handle_failure`, the gates and the worker housekeeping.**

### 2.2 Request/response flow for a Claude failure (exact sequence)

Example: `generate_content`, 10 claimed jobs, `WD_AI_PROVIDER=auto`, primary = Claude CLI, fallback = GLM-4.7-Flash.

1. `worker.process_next` claims the head group with `queue.limit_for('generate_content', cfg, provider=failover.active(conn))` — 10 while `kv.ai.active_provider='claude'` (`queue.py:38-44`, `worker.py:88`).
2. `content.handle_generate_content` → `common.claude_call(kind='content', jobs, system_prompt, user_prompt, schema, word_count=10)`.
3. `failover.choose(conn, cfg, now, kind='content', priority)` → `Choice(slot=claude)` (kill switch on, no global pause, `claude.paused_until` not in the future, override absent).
4. `budget.reserve(..., provider='claude')` → `can_spend` (kill switch → global manual pause `ai.paused_until` → slot pause → global hourly cap → slot hourly cap → monthly/daily USD caps) → inserts the `running` ledger row **with `provider='claude'`** (`ledger.insert_call`, `ledger.py:26-57`).
5. `runner.run_claude(..., provider='claude', call_id)` → unchanged CLI path (`build_argv` … `Popen` … `parse_and_classify`) → stderr carries `Your organization requires remote managed settings to load, but they could not be loaded. Run \`claude auth login\` …` → `AUTH_RE` (today via `log ?in`; now also the explicit `managed settings` alternative) → `Parsed(status='auth', reason='auth')` → `_finish` writes the ledger row (`status='auth'`, 18 s) → `ClaudeResult(ok=False, status='auth', provider='claude')`.
6. Back in `claude_call`: `failover.record_failure(conn, cfg, slot=claude, result)` → hard trigger → inside one `BEGIN IMMEDIATE`: `claude.paused_until = now+30 min` (same key and length as today, `common.py:36,264-267`), `claude.overloaded_streak` left alone, `ai.active_provider='fallback'`, `ai.failover.since=now`, `ai.failover.reason='auth'`, `ai.failover.trigger_call_id=<id>`, `ai.failover.next_probe_at=now+30 min`, `system_events('ai_failover', {from:'claude', to:'fallback', reason:'auth', error:<300 chars>, trigger_call_id, banner_zh})`, plus today's `event_once('claude_auth', …)` (30-min dedupe, unchanged kind so the existing tests and runbook still match) → returns `switch_to='fallback'`.
7. `claude_call` loops **without releasing the claim**: `failover.choose(exclude={'claude'})` → `fallback` (kind `content` ∈ `WD_AI_FALLBACK_KINDS`, priority < 90 or `WD_AI_FALLBACK_PREWARM=1`, slot not paused) → `budget.reserve(provider='fallback')` → a second ledger row (`provider='fallback'`, `model_requested='glm-4.7-flash'`, `reserved_usd=0` because the slot's price table is empty, `flag_tier=0`) → `run_claude(provider='fallback')` dispatches to `providers.openai_http.run(...)`.
8. `openai_http.run` builds the request (§2.3): `POST https://open.bigmodel.cn/api/paas/v4/chat/completions`, `Authorization: Bearer <key>`, body `{model:'glm-4.7-flash', messages:[{role:'system', content:<content_system.txt + "\n\nRespond with a single JSON object that validates against this JSON Schema (no prose, no code fences):\n" + compact schema>}, {role:'user', content:<user prompt verbatim incl. <items>…</items>>}], response_format:{type:'json_object'}, thinking:{type:'disabled'}, max_tokens:8192, stream:false}` — `httpx.Client(trust_env=False, timeout=Timeout(connect=10, read=270, write=30, pool=10))` (the Mac's privoxy proxy must never be inherited: it lives only in the CLI wrapper, `/Users/sqin/word-dance-data/bin/claude-wrapper`).
9. Response 200: `choices[0].message.content` → `extract_json` (strip ``` fences, outermost `{…}`) → `jsonschema.Draft202012Validator(ORIGINAL content_v1).iter_errors` → zero errors → `Parsed(status='success', structured=obj, model_used=body.model or slot.model, tokens from usage.prompt_tokens/completion_tokens/prompt_tokens_details.cached_tokens, cost_usd=pricing.cost(usage)=0.0)`; `save_raw` writes `claude-logs/YYYY-MM-DD/<call_id>.json` with the request (key redacted, prompts ≤20k chars) and the response. On validation errors: one repair turn (same messages + the assistant's answer + a user message listing ≤5 validator errors with JSON paths, "return the corrected complete JSON object only") inside the same ledger row; still invalid → `invalid_output`; `finish_reason=='length'` → `invalid_output` at once (never a silent truncation).
10. `_finish` writes the fallback row (`status='success'`, tokens, `model_used='glm-4.7-flash'`, `stdout_path`) → `ClaudeResult(ok=True, provider='fallback', model_used='glm-4.7-flash', cost_usd=0.0)` → `failover.record_success(slot=fallback)` resets the fallback's streaks → returned to the handler, which proceeds exactly as today: `models.valid_items` → `validate_item` → `store_content(model='glm-4.7-flash')` → `queue.finish`.
11. Every later group skips step 5: `choose` returns `fallback` directly; `limit_for` now claims 5 content jobs per group. User-facing gates (`routers/words.py:324`, `routers/bank.py:150`, …) ask `failover.availability()` and keep answering because *a* provider is available; the admin overview shows `banner_zh` 「Claude 暂不可用，已自动切换到备用模型 glm-4.7-flash（自 02:43 起，每 30 分钟自动探测恢复）」.
12. Recovery: `ClaudeWorker.housekeeping` (every `SWEEP_INTERVAL_S=300` s, `worker.py:48,190-203,263-272`) → `failover.maybe_probe`: when `active!='claude'` and `now ≥ ai.failover.next_probe_at` → `probe.check(conn, cfg)` (today's tiered CLI probe, ≤2 `ai_calls` rows of kind `probe`, ≤$0.05 only when it actually succeeds). Success → `ai.active_provider='claude'`, delete `claude.paused_until`, clear the failover keys, `system_events('ai_failback', {outage_min, probe_call_id})`; failure → `next_probe_at += 30 min` (constant cadence; §8 explains why not doubling) and an hourly-deduped `ai_failover_probe_failed` event. The admin 探测 button (`admin_ops.py:336-350`) forces the same check.

The flow for a **soft** trigger is identical except that step 6 only bumps a provider-scoped streak (`ai.claude.streak.timeout|network`, or today's `claude.overloaded_streak` for overloads) and returns `None` until the threshold is crossed (§3); the handler then runs `handle_failure` as today (defer/backoff), and the switch + immediate retry happens on the call that crosses the threshold.

### 2.3 The adapter: `backend/wd/ai/providers/openai_http.py`

**Strategy per provider** (`providers/dialects.py`, selected by `WD_AI_FALLBACK_DIALECT=auto|zhipu|bailian|deepseek|ark|generic`; `auto` maps the base-URL host):

| dialect | JSON mode | thinking off | extras | documented error vocabulary (classification keys first) |
|---|---|---|---|---|
| `zhipu` (open.bigmodel.cn, api.z.ai) | `response_format:{type:json_object}` + schema in system message (`json_schema` absent from both OpenAPI specs; `tool_choice` auto-only — verify zhipu:F5) | `thinking:{type:"disabled"}` (GLM-5.3/5.3-Flash refuse → config error at start-up if such a model is configured) | `max_tokens` ≥1024 per docs; temperature left default (eval tests 0.7) | `error.code` **1000/1001/1003** → auth · **1113** (429 欠费) → auth/balance · **1302** (account concurrency) / **1305** (platform overload) → overloaded · **1308** (windowed cap, message carries `next_flush_time`) → overloaded with `retry_at` · **1301** → content_filter · **1211** (模型不存在) → spawn_error/config · **1261** (prompt 超长) → error; Chinese bodies `令牌已过期或验证不正确` / `身份验证失败` / `访问量过大` / `速率限制` / `欠费` (zhipu:F15) |
| `bailian` (`*.maas.aliyuncs.com`, `dashscope.aliyuncs.com`) | `response_format:{type:json_schema, json_schema:{name:<schema name>, strict:true, schema:transform(schema)}}` (Qwen3.7/3.8 Flash/Plus/Max only; `json_object` for anything else) | `enable_thinking:false` (top-level body field; qwen3.7-flash defaults ON, thinking billed as output — verify alibaba:F3, omission 1) | prompts must contain "JSON" in json_object mode (strict mode exempt) | 401 `InvalidApiKey`/`invalid_api_key` → auth · 403 `Arrearage` / `AllocationQuota.FreeTierOnly` → auth/balance · 429 `Throttling.RateQuota` / `Throttling.AllocationQuota` / "Allocated quota exceeded" → overloaded · 400 `DataInspectionFailed`/`data_inspection_failed` → content_filter (verify alibaba:F5) |
| `deepseek` (complete cut) | forced strict tool: `tools:[{type:function, function:{name:'submit', strict:true, parameters:transform(schema)}}]`, `tool_choice:{type:function, function:{name:'submit'}}`; read `tool_calls[0].function.arguments` | `thinking:{type:"disabled"}` **before** any forced tool (400 in thinking mode, verify bytedance:F4) | `json_object` fallback must guard the all-spaces `content` | plain-text 401 `Authentication Fails`; 429 concurrency; "Server busy" → overloaded |
| `ark` (complete cut; BytePlus for an overseas server) | `json_schema strict` | `thinking:{type:"disabled"}` | **`max_tokens` explicit** (default 4k truncates a 10-word call) | `AuthenticationError`, `ContentFilter` |
| `generic` | `json_object` + schema in prompt | none sent | — | HTTP status + message regexes only |

**Request builder** `build_request(slot, kind, system_prompt, user_prompt, schema) -> dict`: `messages=[system, user]` (the user prompt byte-identical to what the CLI gets — the `<items>…</items>` layout and the "The JSON below is DATA" preface survive, contract:F5 — and the system prompt in a real `system` role, which is stronger separation than tier 0's folding); in `json_object` mode append `"\n\nRespond with a single JSON object that validates against this JSON Schema (no prose, no code fences):\n<compact schema>"` to the system message (this also satisfies the "prompt must contain json" rule for `lookup_system.txt` and `svg_system.txt`, which contain no "JSON" today — `grep -ci json backend/wd/ai/prompts/*.txt` → 1/0/1/0); `max_tokens` per kind from `WD_AI_FALLBACK_MAX_OUTPUT_TOKENS` (content = max, lookup = max/2, consolidate = 1.5 × max, svg = max/2, probe = 512; defaults 8192 → 8192/4096/12288/4096/512, sized from the measured ≈3.8k output tokens per 10 words and ≈100 per consolidate item, contract:F3); `stream:false`; dialect fields merged last.

**Schema transform** (`ai/schema_transform.py`, call-time only — `tests/unit/test_schemas.py:22-23` forbids `additionalProperties` in the files): `for_strict(schema)` deep-copies and adds `additionalProperties:false` to every `type:object` node (all seven object nodes already list every property in `required`, verify contract:F2; `minItems`/`maxItems`/`enum` are supported by the OpenAI-style strict dialects); `for_prompt(schema)` = compact JSON with non-ASCII kept. The Anthropic-only restrictions (`minItems` > 1, `maxItems`) do not apply to this adapter.

**Extraction + validation**: `extract_json(text)` strips code fences and leading/trailing prose (first `{` to last `}`), ignores `reasoning_content`; `validate(kind, obj)` runs `jsonschema.Draft202012Validator(load_schema(name))` on the **original** schema **before** the handlers' lax pydantic mirrors see it — `models.valid_items` coerces `difficulty:true → 1`, `"3"` rejected, `is_english:"true" → True`, consolidate `id:"12" → 12` (verify contract omission 1), so without this step a weaker model's slip becomes stored data. One repair turn, counted inside the same `ai_calls` row (tokens summed; `error` notes `repair=1`). Empty `choices`, all-spaces content, unparsable JSON after repair, schema errors after repair, `finish_reason=="length"` → `invalid_output`.

**Usage → cost**: `ai/pricing.py` parses `WD_AI_FALLBACK_PRICE_JSON` (`{}` → free → `cost_usd=0`, `reserved_usd=0`; else `{"input":0.2,"output":0.8,"cached_input":0.04}` CNY per 1M; complete cut adds `tiers` by input size and `peak`/`off_peak` windows for DeepSeek) and `WD_AI_CNY_PER_USD` (default 7.2) → `cost_usd` written like today (`ledger.finish_call`), so `spent_today/spent_month`, `avg_cost_per_word_7d` (now filtered to `provider='claude'`) and the daily/monthly caps keep meaning. Tokens: `usage.prompt_tokens` → `input_tokens`, `completion_tokens` → `output_tokens`, `prompt_tokens_details.cached_tokens` (or DeepSeek `prompt_cache_hit_tokens`) → `cache_read_tokens`. The CLI's `--max-budget-usd` has no HTTP equivalent; `max_tokens` is the hard cap and a paid call whose priced cost exceeds `budget_for(cfg, kind)` is still stored (the output is valid) with an hourly-deduped `system_events('ai_budget_overrun')`.

**HTTP / body → status mapping** (`classify(raw) -> Parsed(status, reason, retry_at)`; order: dialect `error.code`/`error.type` table → HTTP status → message regex incl. Chinese → default):

| condition | status (fixed CHECK set) | `reason` (error prefix, drives failover) |
|---|---|---|
| 401; 403 with auth type/message (`invalid api-key`, `authentication_error`, `Token is invalid`, `身份验证失败`, `令牌已过期`, `Authentication Fails`) | `auth` | `auth` |
| 402; Zhipu 1113; 百炼 `Arrearage`, `AllocationQuota.FreeTierOnly`; `insufficient balance|余额不足|欠费|quota exhausted` | `auth` | `balance` (operator action; the §3 table pauses the provider like `auth`) |
| 429 (any), Zhipu 1302/1305/1308, 百炼 `Throttling.*`, `rate limit|too many requests|访问量过大|速率限制`; 500/502/503/504/529 | `overloaded` | `rate_limit` / `platform_overload` / `window_cap` (+ `retry_at` from `Retry-After` or `next_flush_time`) / `server_error` |
| `httpx.ConnectError`, DNS failure, `RemoteProtocolError`, TLS errors | `overloaded` | `network` (separate streak counter) |
| `httpx.ReadTimeout` / `WriteTimeout` | `timeout` | `timeout` |
| 400 content safety (Zhipu 1301, 百炼 `DataInspectionFailed`, Ark `ContentFilter`, DeepSeek "Content Exists Risk") | `error` | `content_filter` (never a trigger; backoff → bisect isolates the word, `common.py:234-247`) |
| 400 other (`1261` prompt too long, bad parameter), 413, 422 | `error` | `bad_request` |
| 404 / Zhipu 1211 / "model not found|模型不存在"; missing base URL or key at start-up | `spawn_error` | `config` (pauses the provider + `ai.fallback.available=0`, mirroring today's missing-binary semantics) |
| unparsable / schema-invalid after repair / `finish_reason=length` / empty content | `invalid_output` | `unparseable` / `schema` / `truncated` / `empty` |
| 200 + valid | `success` | — |

Optional in-adapter retry: one sleep-and-retry when a 429 carries `Retry-After ≤ WD_AI_FALLBACK_RETRY_AFTER_MAX_S` (default 10 s), to stop a single-concurrency collision between a job and a probe from counting as an overload streak.

**Concurrency / timeouts / batch**: `timeout_s × slot.timeout_scale` (1.5 → content 270 s, lookup 180 s, consolidate 360 s; a 96–122 tok/s model needs ≈40–60 s for 4k tokens, zhipu:F4); per-slot `threading.BoundedSemaphore(slot.concurrency)` around the HTTP call (complete cut — the Mac `.env` and the VPS recipe run `WD_AI_CONCURRENCY=1`, so the MVP is safe without it); claim size from `slot.batch_size` (5) through `queue.limit_for`.

### 2.4 Failover state machine (`backend/wd/ai/failover.py`) — F11 reused, with the changes listed in §8

Reuse (contract:F11): sticky `kv.ai.active_provider`, provider-scoped pauses, hard vs soft triggers, 30-min recovery probe through `probe.check`, immediate retry of the same claimed group, "any provider available" user gate, banner texts. Changes: constant probe cadence (no doubling), `retry_at` honoured, network counted separately but stored as `overloaded`, balance/quota exhaustion = `auth`-class with a reason (the CHECK is fixed), prewarm excluded by default, `WD_AI_PROVIDER` enum made D3-compatible.

API (all functions take `conn`, `cfg`, `now`; kv writes inside `db.maybe_tx`):

* `slots(cfg) -> list[Slot]` (in `providers/__init__.py`): `[Slot('claude', 'claude_cli', model=cfg.ai_model, batch=cfg.ai_batch_size, …), Slot('fallback', 'openai_http', …)]` (+ `fallback2` in the complete cut); `WD_AI_PROVIDER=claude_cli` → only the first, `openai_http` → only the fallback(s), `auto` → all.
* `active(conn) -> str` — `ai.provider_override` if set, else `kv.ai.active_provider` (default `'claude'`).
* `choose(conn, cfg, now, *, kind, priority, exclude=()) -> Choice(slot|None, resumes_at)` — the active slot if usable, else the next usable slot in order; "usable" = configured ∧ kind allowed (`probe` always; `WD_AI_FALLBACK_KINDS` otherwise) ∧ (priority < 90 ∨ `WD_AI_FALLBACK_PREWARM=1` ∨ slot is `claude`) ∧ not paused ∧ `available != '0'` ∧ not excluded. When the active slot is `fallback` and `claude` would be chosen only because the fallback is paused, do **not** silently fail back — the recovery probe owns fail-back (`WD_AI_FAILBACK=auto`); `claude` is chosen only if it is not paused (i.e. the pause elapsed), which is today's behaviour.
* `record_failure(conn, cfg, slot, result, now) -> str|None` — applies the §3 table for that slot (pause, streak, events) and returns the slot to switch to (or `None`).
* `record_success(conn, slot, now)` — resets that slot's streaks (keeps `common.record_success` semantics for `claude.overloaded_streak`).
* `maybe_probe(conn, cfg, now)` — §2.2 step 12; also runs the **fallback's** nightly `probe_v1` (complete cut: `ai_fallback_unavailable` event on 1211/404 so a retired model is noticed before Claude fails).
* `availability(conn, cfg, now) -> Availability(enabled, any_available, active, resumes_at, banner_zh)` — the single helper every gate uses; `any_available` = kill switch on ∧ no global manual pause ∧ at least one usable slot for the gate's kind; `resumes_at` = earliest of the relevant pauses (replaces `claude.paused_until` in `content_deferred_until`, `services/words.py:417-422`).
* `banner_zh(state)`: failover active → 「Claude 暂不可用，已自动切换到备用模型 {model}（自 {since} 起，每 {n} 分钟自动探测恢复）」; primary down, no fallback configured/usable → today's `AUTH_BANNER_ZH` (`common.py:37`); both down → 「AI 暂时不可用（主模型与备用模型均失败），任务已排队等待」; fallback quality pause → 「备用模型连续输出无效，已暂停 30 分钟」; balance → 「备用模型账户余额不足，请充值后点击探测」.
* `override(conn, mode, by, now)` (complete cut, `POST /api/admin/ai/provider`).

### 2.5 New config keys (frozen `Settings`, `config.py:84-108`, `from_env` `:328-351`; defaults = today's behaviour)

| key | default | meaning |
|---|---|---|
| `WD_AI_PROVIDER` | `claude_cli` | `claude_cli` = today; `openai_http` = fallback only (no binary needed; install preflight skips `claude`); `auto` = primary with automatic failover. Superset of the D3 enum (`claude_cli|openai_http|none`); `none` stays reserved for the parked curated programme. |
| `WD_AI_CLI_FALLBACK_MODEL` | `""` | **renamed** from `WD_AI_FALLBACK_MODEL` (the CLI's Claude-only `--fallback-model`, `runner.py:145-146`). `from_env` raises `ConfigError("WD_AI_FALLBACK_MODEL now names the fallback provider's model; move the CLI value to WD_AI_CLI_FALLBACK_MODEL")` when the old key is non-empty while `WD_AI_FALLBACK_KIND=none`. The Mac `.env` carries the key (value per `env.example` = empty) → no action. |
| `WD_AI_FALLBACK_KIND` | `none` | `none` \| `openai_http` |
| `WD_AI_FALLBACK_BASE_URL` | `""` | e.g. `https://open.bigmodel.cn/api/paas/v4` (the adapter appends `/chat/completions`) |
| `WD_AI_FALLBACK_API_KEY` | `""` | added to `SECRET_KEYS` (`config.py:44-53`, masked in `GET /api/admin/config`); `WD_AI_FALLBACK_API_KEY_FILE` alternative (0600 file) for the systemd drop-in pattern |
| `WD_AI_FALLBACK_MODEL` | `""` | vendor model id, e.g. `glm-4.7-flash` (written to `ai_calls.model_requested`; `model_used` from the response, defaulting to this id so `word_contents.model` is never `sonnet` for a fallback card) |
| `WD_AI_FALLBACK_DIALECT` | `auto` | `auto` \| `zhipu` \| `bailian` \| `deepseek` \| `ark` \| `generic` |
| `WD_AI_FALLBACK_JSON_MODE` | `auto` | `auto` (dialect default: zhipu → `json_object`, bailian/ark → `json_schema`, deepseek → `tool`) \| `json_object` \| `json_schema` \| `tool` |
| `WD_AI_FALLBACK_THINKING` | `off` | `off` sends the dialect's disable field; `default` sends nothing |
| `WD_AI_FALLBACK_TEMPERATURE` | `""` | empty = vendor default |
| `WD_AI_FALLBACK_MAX_OUTPUT_TOKENS` | `8192` | content cap; per-kind multipliers in code (§2.3) |
| `WD_AI_FALLBACK_BATCH_SIZE` | `5` | content claim size while the fallback is active (clamped 1–12) |
| `WD_AI_FALLBACK_CONCURRENCY` | `1` | per-slot semaphore (complete cut) |
| `WD_AI_FALLBACK_TIMEOUT_SCALE` | `1.5` | × `budget.timeout_for` |
| `WD_AI_FALLBACK_HOURLY_CALL_CAP` | `60` | per-slot cap, checked in addition to the global `WD_AI_HOURLY_CALL_CAP` |
| `WD_AI_FALLBACK_KINDS` | `content,lookup,consolidate` | `svg` opt-in after the eval |
| `WD_AI_FALLBACK_PREWARM` | `0` | priority-≥90 content jobs may use the fallback |
| `WD_AI_FALLBACK_PRICE_JSON` | `{}` | CNY per 1M tokens; `{}` = free |
| `WD_AI_CNY_PER_USD` | `7.2` | |
| `WD_AI_FALLBACK_PROXY` | `""` | explicit proxy URL for the adapter only; env proxies are never inherited (`trust_env=False`) |
| `WD_AI_FALLBACK_RETRY_AFTER_MAX_S` | `10` | in-adapter single retry on short `Retry-After` |
| `WD_AI_FAILOVER_COOLDOWN_MIN` | `30` | provider pause after a hard trigger (= today's `AUTH_PAUSE`) |
| `WD_AI_FAILOVER_PROBE_EVERY_MIN` | `30` | recovery probe cadence (constant) |
| `WD_AI_FAILOVER_OVERLOADED_AFTER` / `_TIMEOUT_AFTER` / `_NETWORK_AFTER` | `3` / `2` / `2` | consecutive soft failures on the active slot before switching |
| `WD_AI_FAILOVER_ON_BUDGET_CAP` | `0` | `1` = daily/monthly cap exhaustion on Claude runs the group on a **free** fallback instead of deferring |
| `WD_AI_FAILBACK` | `auto` | `manual` = never flip back without the admin |
| `WD_AI_FALLBACK2_*` (complete cut) | — | same keys for the paid second leg |

Validation at start-up: `auto`/`openai_http` require `KIND=openai_http` with base URL, key and model; `zhipu` dialect + a `glm-5.3*` model + `THINKING=off` is a `ConfigError` (cannot be disabled, verify zhipu:F5).

### 2.6 kv keys

| key | written by | meaning |
|---|---|---|
| `ai.active_provider` | `failover.record_failure` / `maybe_probe` | `claude` \| `fallback` (\| `fallback2`); default `claude` |
| `ai.failover.since` / `ai.failover.reason` / `ai.failover.trigger_call_id` / `ai.failover.next_probe_at` | same | outage bookkeeping; cleared on fail-back |
| `claude.paused_until` | unchanged key, **now the primary's** automatic pause (read by 10 call sites and 10 test files — kept on purpose, contract:F18) | |
| `claude.overloaded_streak`, `claude.available`, `claude.flag_tier`, `claude.last_probe_at`, `claude.version`, `claude.enabled` | unchanged | primary's streak / CLI availability / tier / kill switch (global) |
| `ai.claude.streak.timeout` / `ai.claude.streak.network` | `record_failure` | new soft streaks of the primary |
| `ai.fallback.paused_until` / `ai.fallback.available` / `ai.fallback.last_probe_at` / `ai.fallback.streak.{overloaded,timeout,network,invalid_output}` | `record_failure`, `probe.check(provider='fallback')` | fallback's state |
| `ai.paused_until` | `POST /api/admin/ai/pause` | **global manual pause** (24 h, `MANUAL_PAUSE`, `admin_ops.py:35`); resume deletes it and both automatic pauses |
| `ai.provider_override` | `POST /api/admin/ai/provider` (complete cut) | `claude` \| `fallback` \| absent (= auto) |

### 2.7 Migration `backend/wd/migrations/0010_ai_provider.sql`

```sql
-- 0010_ai_provider.sql — provenance of AI calls by provider slot (CLAUDE_INTEGRATION §10).
-- Purely additive (ALTER TABLE ADD COLUMN + one index), safe under `deploy/install.sh --no-restart` (DEPLOY §10),
-- like 0008/0009. docs/SCHEMA.sql stays byte-identical to 0001 (tests/unit/test_db.py:362-366); the column is
-- documented in CLAUDE_INTEGRATION.md §10. The runner records schema_migrations(10, 'ai_provider') itself.
ALTER TABLE ai_calls ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude';
CREATE INDEX IF NOT EXISTS ix_ai_calls_provider ON ai_calls(provider, started_at);
```

`db.run_migrations` applies `sorted(glob('*.sql'))` (`db.py:161-163`), so the number is free; D3's parked `0010_curation_columns.sql` (which also listed `ai_calls.provider`) becomes `0011_…` without that column when the curated programme resumes. `model_requested` keeps the vendor id (`glm-4.7-flash`) and, for the primary, today's alias (`sonnet` on all 68 live rows — verify contract:F10).

### 2.8 Admin API / UI

* `AdminOverviewAi` (`schemas.py:1110-1122`, inline mirror `types.ts:188-190`, filled by `budget.spend_summary` `budget.py:289-309`): `+ active_provider: 'claude'|'fallback'`, `+ fallback_configured: bool`, `+ fallback_model: str|null`, `+ failover_since: str|null`, `+ failover_reason: str|null`, `+ next_probe_at: str|null`, `+ fallback_calls_today: int`, `+ banner_zh: str|null`; `avg_cost_per_word_7d` becomes Claude-only. Complete cut: `+ fallback_content_share_7d` (`COUNT(*) FILTER (WHERE model NOT LIKE 'claude-%')` over `word_contents` of the window) and `+ fallback_cny_month`.
* `AiCall` (`schemas.py:1280-1293`, `types.ts:207-210`, `ledger.call_dto` `ledger.py:187-204`): `+ provider`.
* `AdminHealth.claude_bin` (`schemas.py:1162-1194`, `admin_ops.py:193-199`) gets a sibling `fallback: {kind, model, base_url_host, ok, last_probe_at} | null` (complete cut).
* `ProbeResponse` `+ provider`; `POST /api/admin/ai/probe` takes an optional body `{provider: 'claude'|'fallback'}` (MVP: backend; UI button in the complete cut).
* `POST /api/admin/ai/pause` writes `ai.paused_until` (global); `{paused:false}` deletes `ai.paused_until`, `claude.paused_until`, `ai.fallback.paused_until` and sets `claude.enabled=1` as today (`admin_ops.py:314-333`).
* New `POST /api/admin/ai/provider {mode: 'auto'|'claude'|'fallback'}` → `ai.provider_override` + `system_events('ai_provider_override', {by, mode})` (complete cut).
* Frontend (`AdminPage.tsx` AI tab `:705-790`, overview `:242-272`, `zh.ts` admin block): a 「当前来源」 tile (`active_provider` + `fallback_model`), the banner line under the pause button, a 「来源」 column in the ledger table (MVP, display only); segmented control auto/仅 Claude/仅备用 and a 「探测备用」 button (complete cut). `scripts/check_contract.py` audits `schemas.py ↔ types.ts` field by field → both move in the same commit.
* `GET /api/admin/config` masks `WD_AI_FALLBACK_API_KEY` via `SECRET_KEYS`.

### 2.9 Test doubles and test files

* **`backend/tests/fake_openai.py`** (stdlib + importable handler): `handle(request) -> response` usable as `httpx.MockTransport(handle)` (the `smoke_mock.MockHttp` pattern, `smoke_mock.py:79-103`) **and** as `python -I tests/fake_openai.py --port 8787` (stdlib `http.server`) for `scripts/smoke.py`, `scripts/dev.sh` and the eval mock. It serves `/v1/chat/completions` (OpenAI envelope with `usage`; `model` echoed) and reuses the item builders of `fake_claude.py` (`content_item` :170, `lookup_item` :204, `consolidate_item` :242, `svg_output` :255-262, probe answer). Modes via `X-Fake-Mode` header or `FAKE_OPENAI_MODE` env: `ok · fenced_json · invalid_json · schema_mismatch · partial · truncated (finish_reason=length) · slow:<s> · 401 · zh_401 (令牌已过期或验证不正确) · 1113 · 402 · 403_arrearage · 429 (+Retry-After) · 1302 · 1305 · 1308 (next_flush_time) · 503 · content_filter (1301 / DataInspectionFailed) · model_not_found (1211/404) · empty_content · reasoning_leak (reasoning_content + fenced JSON) · strict_echo (asserts `response_format.json_schema.strict` and `additionalProperties:false` present)`.
* **New unit tests**: `tests/unit/test_openai_http.py` (request shape per dialect incl. thinking-off fields and the json_object instruction; `extract_json`; classification table — one row per mode above, asserting status + reason + `retry_at`; repair loop happy/unhappy; truncation; pricing incl. free → 0 and CNY→USD; `save_raw` redaction), `tests/unit/test_schema_transform.py` (every `tests/fixtures/claude_*_ok.json` still validates against `for_strict(schema)`; no file under `ai/schemas` changed), `tests/unit/test_failover.py` (state machine with a fake run function: hard trigger → switch + same-group retry; soft streaks; `retry_at` deferral; probe success → fail-back; `availability()` matrix; prewarm exclusion; kinds filter; override).
* **Edited tests**: `test_runner.py` (dispatch by `provider`; CLI path byte-identical), `test_budget.py` (per-slot hourly cap; `reserved_usd=0` for free slots; `ON_BUDGET_CAP`), `test_config.py` (new keys, rename `ConfigError`, dialect validation), `test_db.py` (0010 applies; `SCHEMA.sql` still identical to 0001), `test_deploy_files.py:253` (dry run still prints `/.venv/bin/wd claude-check`, plus the new `ai-check` line), `test_worker.py:280-298` (unchanged assertions under `claude_cli`; new `auto` case: `auth` wrapper + fake_openai → jobs `done`, `ai_calls.provider` = `claude`,`fallback`, `word_contents.model='glm-fake'`; probe `ok` wrapper → fail-back), `test_admin_ops.py` (new fields; pause writes `ai.paused_until`), `test_schemas.py` (transform never touches the files), frontend `zh.test.ts` / `zh.contract.test.ts`, `scripts/check_contract.py` green.
* **Smoke** (`scripts/smoke.py`, env at `:176-186`, drain `:264`): a `--with-fallback` step starts `fake_openai.py`, exports `WD_AI_PROVIDER=auto` + fallback keys, swaps `WD_CLAUDE_BIN` to a `fake_claude.py` wrapper in `auth` mode (the `make_wrapper` pattern, `test_runner.py:33-46`), drains, asserts `ai_calls.provider='fallback'` and the content/lookup rows, then restores the `ok` wrapper and asserts the fail-back event after a forced probe.

### 2.10 Deploy / install / dev changes

* `deploy/env.example:53-85`: rename `WD_AI_FALLBACK_MODEL` → `WD_AI_CLI_FALLBACK_MODEL`; add the `WD_AI_FALLBACK_*` / `WD_AI_FAILOVER_*` block with the GLM defaults commented in.
* `deploy/install.sh:48-49`: the `claude` preflight becomes `if [ "${WD_AI_PROVIDER:-claude_cli}" != openai_http ]`; `:142-143` keeps `wd claude-check` (pinned by the dry-run test) and adds `[ "${WD_AI_FALLBACK_KIND:-none}" = none ] || run "$REPO/.venv/bin/wd" ai-check --provider fallback || echo "WARN: fallback check failed"`.
* `deploy/word-dance.service:33-34`: comment only (ProtectHome stays unset while the CLI is the primary; an `openai_http`-only server may set it).
* Secrets: `.env` is already 0600; alternatively `/etc/systemd/system/word-dance.service.d/secrets.conf` with `Environment=WD_AI_FALLBACK_API_KEY=…` (the memory's drop-in pattern). Outbound: the VPS must reach `open.bigmodel.cn:443` (and `*.maas.aliyuncs.com:443` for the step-up) directly; no proxy. On the Mac the privoxy proxy stays in the CLI wrapper only.
* `scripts/dev.sh:25-29`: `WD_DEV_FAKE_FALLBACK=1` starts `fake_openai.py` and exports the `auto` configuration.
* `wd ai-check [--provider claude|fallback|all]` (`probe.register_cli`, `cli.py` COMMAND_OWNERS); `wd claude-check` stays as the alias for `--provider claude`; `wd check claude` → `wd check ai` (diag).
* Docs: `CLAUDE_INTEGRATION.md` §1 (provider slots), §3 (new regexes + HTTP table), §7 (per-slot caps), new §10 (adapter + failover + kv + 0010 column); `DEPLOY.md` §4 keys + runbook row; `ops.md:196` runbook row becomes "Claude down → nothing to do: failover active (banner); check 管理 → AI 来源; fix the login when convenient; the probe fails back automatically"; `API.md` 54/55/64–66 + the new endpoint.

### 2.11 File-level change list (hours; M = MVP, C = complete cut)

| file | function / area | change | h | cut |
|---|---|---|---|---|
| `backend/wd/ai/providers/__init__.py` (new) | `Slot`, `slots(cfg)`, `get(cfg, name)` | provider slot model from `Settings` | 1.5 | M |
| `backend/wd/ai/providers/openai_http.py` (new) | `build_request`, `call`, `extract_json`, `validate`, `repair`, `classify`, `run` | the adapter (§2.3), `httpx.Client(trust_env=False)`, `TRANSPORT_FACTORY` hook for `MockTransport` | 8 | M |
| `backend/wd/ai/providers/dialects.py` (new) | `DIALECTS`, `detect(base_url)` | zhipu / bailian / generic tables | 2 | M |
| same | | deepseek / ark + `tool` strategy | 3 | C |
| `backend/wd/ai/schema_transform.py` (new) | `for_strict`, `for_prompt` | call-time transform | 1 | M |
| `backend/wd/ai/pricing.py` (new) | `Pricing.parse`, `cost_usd` | flat CNY table → USD | 1.5 | M |
| same | | tiers + peak/off-peak windows | (in C row above) | C |
| `backend/wd/ai/failover.py` (new) | §2.4 API | state machine, availability, banner, probe scheduling | 5 | M |
| same | `override`, flap guard, `ON_BUDGET_CAP`, `ai_budget_overrun` | | 1.5 | C |
| `backend/wd/migrations/0010_ai_provider.sql` (new) | | §2.7 | 0.5 | M |
| `backend/wd/interfaces.py:83-93` | `ClaudeResult` | `+ provider='claude'`, `+ model_requested=None`, `+ retry_at=None` (defaults at the end) | 0.25 | M |
| `backend/wd/ai/runner.py` | `run_claude(…, provider=None)`, `Parsed(+provider, +reason, +retry_at)`, `_finish`, `AUTH_RE`/`OVERLOADED_RE`/new `REGION_RE`/`NETWORK_RE`/`USAGE_LIMIT_RE`, log `extra` | dispatch to the adapter when the slot kind is `openai_http`; CLI path otherwise byte-identical; regex gaps closed (`managed settings`, `\b403\b|forbidden|request not allowed`, `\b402\b|insufficient balance|余额不足|令牌已过期|token expired|Token is invalid|身份验证失败`, `usage limit|plan limit|enforced_spend_limit_reached|credit balance`, `\b429\b`, `ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN|Unable to connect|Can't reach the API|Connection refused|fetch failed|socket hang up|malformed response \(HTTP 200\)|certificate`) | 1 | M |
| `backend/wd/ai/providers/claude_cli.py` (new) | move `build_argv/claude_env/parse_and_classify/_spawn` | mechanical move; `runner` re-exports every name in `__all__` (`runner.py:535-556`) so 18 test files keep importing from `runner` | 2 | C |
| `backend/wd/ai/common.py:133-184` | `claude_call` | slot loop: choose → reserve(provider) → run → `record_failure` → immediate retry on the returned slot; defer to `earliest_resume` | 2 | M |
| `backend/wd/ai/common.py:203-282` | `record_success`, `handle_failure` | provider-scoped pauses via `failover`; `retry_at` deferral; defer target = earliest resume across slots; `AUTH_BANNER_ZH` → `failover.banner_zh` | 1.5 | M |
| `backend/wd/ai/budget.py` | `estimate(kind, words, pricing=None)`, `can_spend(…, provider)`, `reserve(…, provider, pricing)`, `paused_until` (primary), `spend_summary` | per-slot hourly cap + pause; `reserved_usd=0` for free slots; overview fields | 2 | M |
| `backend/wd/ai/ledger.py` | `insert_call(provider=)`, `count_started(provider=)`, `sum_cost(provider=)`, `avg_cost_per_word(provider='claude')`, `call_dto` | provider column everywhere | 1.5 | M |
| `backend/wd/config.py` | fields, `from_env`, `SECRET_KEYS`, validation | §2.5 keys, rename guard | 2 | M |
| `backend/wd/ai/probe.py` | `check(conn, cfg, provider='claude')`, `cmd_ai_check`, `register_cli` | tier-less fallback probe writing `ai.fallback.*`; `claude-check` alias | 1.5 | M |
| same | nightly fallback probe + `ai_fallback_unavailable` | | 1.5 | C |
| `backend/wd/jobs/worker.py:88,263-272` + `jobs/queue.py:38-44` | `process_next`, `ClaudeWorker.housekeeping`, `limit_for(type, cfg, provider)` | claim size by active slot; `failover.maybe_probe` every sweep | 1.5 | M |
| gates: `routers/words.py:324`, `routers/bank.py:150`, `services/bank.py:221-237`, `jobs/scheduler.py:252`, `services/batches.py:384,498`, `services/words.py:417-422`, `diag.py:78-104`, `routers/admin_ops.py:196,363` | | all read `failover.availability()` / `earliest_resume()`; the two `ai_enabled` implementations stay (kill switch is global) | 3 | M |
| `ai/content.py:392-460`, `lookup.py:552-579`, `consolidate.py:500-531`, `svg.py:109-144` | handlers | no logic change; add `provider` to the log `extra` | 0.5 | M |
| `routers/admin_ops.py` + `schemas.py` + `frontend/src/api/types.ts` + `scripts/check_contract.py` | overview/ledger fields, probe body | §2.8 MVP subset | 2.5 | M |
| same | `POST /api/admin/ai/provider`, health `fallback`, ledger filter, segmented control, 探测备用 button, `zh.ts` | | 5 | C |
| `frontend/src/pages/AdminPage.tsx`, `frontend/src/i18n/zh.ts` | AI tab / overview | 来源 tile, banner, 来源 column (display only) | 1.5 | M |
| `deploy/env.example`, `deploy/install.sh`, `deploy/word-dance.service` comment, `docs/CLAUDE_INTEGRATION.md` §10 (short) | | §2.10 minimum | 1.5 | M |
| `deploy/install.sh` preflight conditional, `scripts/dev.sh`, `docs/DEPLOY.md`, `docs/ops.md`, `docs/API.md`, `CLAUDE_INTEGRATION` §1/§3/§7 | | runbooks + full docs | 4 | C |
| `backend/tests/fake_openai.py` (new) | | §2.9 | 3 | M |
| `tests/unit/test_openai_http.py`, `test_failover.py`, `test_schema_transform.py` (new) | | §2.9 | 5 | M |
| existing tests (§2.9 list) | | edits + new cases | 5 | M |
| live tests + `.env` flip on the VPS (operator time) | | §4 | 2 | M |
| `scripts/eval_provider.py`, `scripts/mock_provider_server.py` (new; the latter is a thin `main()` over `fake_openai`) | | eval harness + scorecard (§4.3), runs for GLM and qwen | 6 | C |
| `scripts/smoke.py` | `--with-fallback` step | | 2 | C |
| `providers` semaphore + `WD_AI_FALLBACK2_*` second leg + `retry_at` plumbing for 1308 | | | 3.5 | C |
| `routers/admin_ops.py` + `content.py` | `POST /api/admin/content/regenerate-fallback {limit}` (enqueues `generate_content {force:1}` for words whose active content model is not `claude-%`), per-block model label hook (D3) | | 3 | C |
| frontend tests + contract audit for the complete UI | | | 1 | C |

Totals: **MVP ≈ 57 h ≈ 7 person-days**; complete cut adds ≈ 33 h ≈ 4 person-days → **≈ 11 person-days**.

### 2.12 The live-ledger outage replayed with this design (UTC; CST = +8 h)

Source: `scratchpad/quick/live-copy.db` (read-only copy): `ai_calls` 33–47 all `auth` with the managed-settings string, 18–20 s each, cost 0; `system_events` 4–17 (14 `claude_auth`); `kv.claude.paused_until=2026-11-03T02:56:20Z`; call 48 succeeded at 02:56:21Z after the owner fixed the login (verify contract:F11, F16).

| time | today (what the ledger shows) | with D2 (`WD_AI_PROVIDER=auto`, fallback GLM-4.7-Flash) |
|---|---|---|
| 2026-11-02 18:43:40Z (02:43 CST) | call 33 `consolidate` → `auth` after 18.5 s; `claude.paused_until=19:13:40Z`; event 4 `claude_auth` 「Claude CLI 未登录…」; job deferred 30 min | same call 33 fails (18 s) → hard trigger: `claude.paused_until=19:13:58Z`, `ai.active_provider=fallback`, `ai_failover` + `claude_auth` events, `next_probe_at=19:13:58Z`; **the same consolidate job is retried immediately**: call 33b `provider=fallback`, ≈5 KB prompt, ≈1.5k output tokens, ≈25 s → `success`, consolidation applied; banner on the admin page: 「Claude 暂不可用，已自动切换到备用模型 glm-4.7-flash（自 02:43 起，每 30 分钟自动探测恢复）」 |
| 18:44–19:13Z | nothing runs (pause) | later consolidate jobs (calls 34/35 in reality) run on the fallback at their `run_after`; user lookups answered in ≈20–30 s; content requests accepted (gates see `any_available=true`) |
| 19:13:58Z + ≤5 min (sweep) | — | `maybe_probe` → `probe.check` tier 1 → managed-settings failure (18 s), tier 0 → same (18 s) → `claude.available=0`, `next_probe_at=19:43:58Z`, hourly-deduped `ai_failover_probe_failed` |
| 19:15:55Z, 19:48:33Z | calls 34, 35 `consolidate` → `auth`, pause renewed to 20:18Z, events 5, 6 | Claude is not touched by jobs (only by the probe); the two consolidations complete on the fallback |
| 20:23:37Z … 02:26:20Z | calls 36–47 (`content`, nightly prefetch) → `auth` every ≈32 min, 12 more pauses, events 7–17; **zero content produced for 8 h 13 min**; every 立即整理 / content request → 503 `ai_disabled` 「AI 功能当前不可用」 | all 12 content groups run on the fallback within minutes of their `run_after` (batch 5 → ≈24 calls, ≈45 s each at 1 concurrency); `word_contents.model='glm-4.7-flash'` on those cards; probes at 20:14, 20:44, …, 02:14, 02:44 fail (0 cost) |
| ≈02:30–02:56Z | owner fixes the login; pause expires 02:56:20Z; call 48 succeeds 02:56:21Z | the first probe after the fix (≤30 min later, e.g. 02:44Z or 03:14Z) succeeds → `ai.active_provider=claude`, `claude.paused_until` deleted, `ai_failback {outage_min≈480, probe_call_id}`; banner clears; batch size back to 10; the fallback-generated cards stay (regenerate later via the complete-cut action, ≈$0.005/word) |
| cost | $0 (but no output) | $0 on the fallback; one successful probe ≤$0.05 |

---

## 3. Failure → action table

Legend: **hard** = pause the failing slot `WD_AI_FAILOVER_COOLDOWN_MIN` (30), switch the sticky active slot, event, **retry the same claimed group at once** on the next usable slot; **soft** = provider-scoped streak, the group is deferred/backed off as today until the streak threshold, then hard; **never** = job-level handling only. "P" = primary (Claude CLI), "F" = fallback (HTTP). Fail-back rule for every row: the primary comes back only through a successful `probe.check` (every 30 min, or the admin button), never by elapsed time alone; `WD_AI_FAILBACK=manual` disables the automatic flip.

| signal (status · reason / regex class) | P: trigger | F: trigger | cooldown / deferral | budget & hourly cap (free F) | concurrency · timeout · batch | provenance | banner / event |
|---|---|---|---|---|---|---|---|
| `auth` · `AUTH_RE` incl. **`managed settings`**, `not logged in`, `401`, `credential`, `令牌已过期`, `身份验证失败`, `Token is invalid`, usage-limit phrases | **hard** | **hard** (F paused 30 min; if P also paused → jobs defer to the earliest resume) | slot pause 30 min; probe every 30 min | the failed call is counted in both hourly caps; cost 0 | — | ledger row `status=auth`, `provider` | `claude_auth` (P, 30-min dedupe, unchanged kind) / `ai_fallback_auth` (F); banner per §2.4 |
| `auth` · `balance` (`402`, Zhipu 1113, 百炼 `Arrearage`/`FreeTierOnly`, `余额不足|欠费`) | hard | hard | slot pause 30 min, probe cadence as above (a probe against an empty balance costs nothing) | — | — | `error` prefixed `balance:` | 「备用模型账户余额不足，请充值后点击探测」 |
| `auth`-class · `REGION_RE` (`\b403\b|forbidden|request not allowed`) | hard (the Mac's tunnel-less 403; HK IPs) | F: 403 is auth/balance by body, else `error` | as auth | — | — | | |
| `spawn_error` · binary missing (P) / `config` (F: 404, 1211, missing key/URL) | hard + `claude.available=0` | hard + `ai.fallback.available=0` (stays 0 until a successful `ai-check --provider fallback`) | 30 min | — | — | | `claude_unavailable` / `ai_fallback_unavailable` |
| `overloaded` · `rate_limit` (429, 1302, `Throttling.*`), `platform_overload` (1305, 5xx, 529), `server_error` | **soft**: defer `2 min × attempts` (today), streak → P pause 15 min at 6 (today, kept); **switch at `OVERLOADED_AFTER=3`** | soft: defer `retry_at` if given else `2 min × attempts`; at 3 → switch (to P only if P is not paused, else to leg 2 / wait); at 6 → F pause 15 min | `Retry-After ≤ 10 s` → one in-adapter retry first | counted; cost 0 | F keeps concurrency 1 | | `claude_overloaded` (P, today) / `ai_fallback_overloaded` |
| `overloaded` · `window_cap` (Zhipu 1308 with `next_flush_time`) | — | **defer the group to `next_flush_time`**, pause F until then (no streak), switch immediately if P is usable | until the window resets | — | — | | 「备用模型额度窗口已满，{time} 恢复」 |
| `overloaded` · `network` (`NETWORK_RE` on P; connect/DNS/TLS errors on F) | soft: defer 2 min; **switch at `NETWORK_AFTER=2`** | soft, same threshold | — | — | — | `error` prefixed `network:` | |
| `timeout` | soft: backoff, bisect on the 2nd (today); **switch at `TIMEOUT_AFTER=2`** consecutive | soft, same | — | — | F timeout = kind timeout × 1.5 (content 270 s) | | |
| `budget` (CLI `--max-budget-usd` stop) | **never** (bisect, today) | n/a (no HTTP equivalent; priced overrun → `ai_budget_overrun` event, output kept) | — | — | — | | |
| `can_spend` refused: daily/monthly/prewarm/svg USD cap | **never** unless `WD_AI_FAILOVER_ON_BUDGET_CAP=1` → the group runs on a **free** slot (its hourly cap still applies) | caps apply identically (Claude-priced estimate, "stop" semantics) | defer to 00:05 / 1st (today) | free slot: `reserved_usd=0`, `cost_usd=0` → `spent_today` unchanged | | | `budget_daily` etc. (today) |
| `can_spend` refused: hourly cap (global 60/h or slot cap) | never | never (if the other slot has headroom, `choose` uses it) | next hour boundary + 1 min | the probe and the immediate retry both count | | | |
| `invalid_output` (schema/unparseable/truncated/empty after repair; handlers' all-items-failed reclassification `content.py:440-444`) | **never** (backoff → bisect → dead, today) | never, but a streak of **3** → F quality pause 30 min + `ai_fallback_quality` event | — | — | truncation → raise `WD_AI_FALLBACK_MAX_OUTPUT_TOKENS` or lower batch | | 「备用模型连续输出无效，已暂停 30 分钟」 |
| `error` · `content_filter` (1301, `DataInspectionFailed`) | never | **never** (bisection isolates the word; after 3 attempts the job dies alone) | — | — | — | `error` prefixed `content_filter:` | |
| `error` · other (`bad_request`, E2BIG argv, kernel errors) | never | never | backoff 2/10/60 min (today) | — | — | | |
| `success` | resets P streaks (`claude.overloaded_streak`, `ai.claude.streak.*`) | resets F streaks | — | priced cost recorded (0 for free) | — | `ai_calls.provider`, `model_used`; `word_contents.model` = vendor id | fail-back only via probe |
| recovery probe succeeds while `active=fallback` | → `active=claude`, pause cleared | — | — | ≤$0.05 once | — | `probe` rows carry `provider=claude` | `ai_failback {outage_min}` |
| flap guard (complete cut): a hard trigger on P within 15 min of a fail-back | hard again, but the next probe interval doubles (max 2 h) for this outage | — | | | | | |

Batch size, concurrency and timeouts while the fallback is active: content claim 5 (`WD_AI_FALLBACK_BATCH_SIZE`), lookup 20, consolidate/svg 1; in-flight 1 (`WD_AI_FALLBACK_CONCURRENCY`); timeouts × 1.5. Provenance in every case: `ai_calls.provider` + `model_requested` (vendor id) + `model_used` (response `model`), `word_contents.model`, `consolidation_runs.ai_call_id` → provider via join.

---

## 4. Rollout

### 4.1 Today (zero code, ≈2 h)

1. Register on open.bigmodel.cn (mainland phone), create a **standard** API key (not Coding Plan — those keys are a different product and 「自建应用」 must use the standard API, zhipu:F11/F17). Do personal 实名 now (支付宝 face, instant): calling is 实名-free "目前", recharging and Batch are not (verify zhipu:F9).
2. Read `bigmodel.cn/usercenter/proj-mgmt/rate-limits` for `glm-4.7-flash` (the only place the concurrency number exists).
3. One `curl` with the real prompt: system = `backend/wd/ai/prompts/content_system.txt` + the json_object instruction + compact `content_v1.json`; user = `scratchpad/fallback/measure/content_user_prompt_cet4_top10.txt`; `response_format:{type:json_object}`, `thinking:{type:disabled}`, `max_tokens:8192`. Validate the body with `.venv/bin/python -c "import json,jsonschema; …"` against `content_v1.json`, count items that pass `content.validate_item` (importable without a DB, verify contract:F4), note `usage` and latency. Repeat once with thinking left on. Cost ¥0.
4. Apply the regex patch (`runner.py:71-74`: `managed settings`, `\b403\b|forbidden|request not allowed`, `\b402\b|余额不足|令牌已过期|token expired|Token is invalid|身份验证失败`, usage-limit phrases, `\b429\b`, `NETWORK_RE`) — 0.25 d, independent of everything else, makes the current pause path at least recognise the region block and Chinese bodies.
5. **Optional manual stop-gap if Claude is down right now (A0, not the design):** a second wrapper `$WD_DATA_DIR/bin/claude-fallback` exporting `ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic`, `ANTHROPIC_AUTH_TOKEN=<key>`, `ANTHROPIC_DEFAULT_SONNET_MODEL=ANTHROPIC_DEFAULT_HAIKU_MODEL=ANTHROPIC_DEFAULT_OPUS_MODEL=glm-4.7-flash`, `CLAUDE_CONFIG_DIR=$WD_DATA_DIR/claude-fallback-config` (empty, login-free), `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1` (CLI ≥ 2.1.288; the Mac has 2.1.292), `MAX_THINKING_TOKENS=0`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_AUTOUPDATER=1`, no proxy; `.env`: `WD_CLAUDE_BIN=<wrapper>`, `WD_AI_MODEL=glm-4.7-flash`, `WD_AI_FALLBACK_MODEL=""`; verify first with `WD_DATA_DIR=<scratch> wd claude-check` (decides also whether Enterprise `forceLoginMethod` managed settings block token auth — "cannot coexist", verify contract omission 5). Known costs of this path: `total_cost_usd` is a client-side estimate with `costBasis unknown` → USD caps blind; structured output rides on an unforced synthetic tool call; the vendor may default thinking ON. Anthropic's docs state they do not support routing Claude Code to non-Claude models through any gateway (reported, not analysed). Flip back by hand.

### 4.2 This week (MVP, 7 person-days; order of work)

Day 1–2 adapter + dialects + transform + pricing + `fake_openai` + unit tests → Day 3 `failover.py`, `claude_call` loop, `handle_failure` scoping, budget/ledger, migration → Day 4 gates, probe/`ai-check`, config, admin fields, frontend display → Day 5 integration tests, env/docs minimum, smoke run with fakes → then the live tests below → flip `WD_AI_PROVIDER=auto` on the VPS with `WD_AI_FALLBACK_KIND=openai_http`, `WD_AI_FALLBACK_BASE_URL=https://open.bigmodel.cn/api/paas/v4`, `WD_AI_FALLBACK_MODEL=glm-4.7-flash`, defaults elsewhere.

**Live tests to run first with a real key (and their cost):**

| # | test | expect | cost |
|---|---|---|---|
| L1 | `WD_DATA_DIR=<scratch> wd ai-check --provider fallback` | `probe_v1` exact match (integer + string enum, bounded array) → `ai.fallback.available=1` | ¥0 |
| L2 | eval harness (or, before it exists, the MVP adapter through `wd worker-once` on a scratch DB seeded with 50 words: 10 per stage + 10 phrases/abbreviations) against GLM-4.7-Flash: 5 content calls (batch 10) + 2 lookup calls (40 strings incl. misspellings/CJK/gibberish) + 1 synthetic consolidation (15 items) | scorecard §4.3 | ¥0 (≈10 min at 1 concurrency) |
| L3 | same with thinking left on and with `temperature 0.7` | pick the better configuration; confirm `usage.completion_tokens ≈ visible JSON` with thinking off | ¥0 |
| L4 | from the Tokyo VPS: unauthenticated `POST https://open.bigmodel.cn/api/paas/v4/chat/completions` → 401 JSON; then L1 and L2 from the VPS | reachability + latency (expect +50–100 ms RTT) | ¥0 |
| L5 | failover drill on the VPS stack: `WD_CLAUDE_BIN` → a wrapper that prints the managed-settings string and exits 1 (never the real `claude`); enqueue 10 content jobs + 1 lookup; watch `ai_calls.provider`, `kv.ai.active_provider`, the banner; restore the real wrapper; click 探测 | switch within one handler pass, fail-back on the probe | ¥0 + one real probe ≤ $0.05 |
| L6 | soak: one night with `auto` on; compare `ai_calls` by provider and `word_contents.model` | no unexpected fallback calls while Claude is healthy | ¥0 |
| L7 (step-up, when wanted) | open 百炼 (实名), enable `用完即停` on qwen3.7-flash, run L1/L2 against `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` with `json_schema strict` + `enable_thinking:false` | scorecard; confirm no reasoning tokens billed | inside the 1M free grant (≈35k tokens); ≈¥0.1 otherwise |

### 4.3 Go/no-go thresholds (eval harness, F17 metrics reused; the harness drives the production adapter, §8)

Per kind and overall: schema-valid ≥ 98 % after ≤ 1 repair; **item pass (`validate_item`, `last_attempt=False`) ≥ 95 %**; headword present in ≥ 97 % of examples; ≥ 3 usable examples in ≥ 95 % of items; CJK present in 100 % of zh fields; p95 latency ≤ 0.6 × (kind timeout × 1.5) (content ≤ 162 s); truncation 0; repair rate ≤ 10 %; lookup agreement with the expected answers ≥ 90 % (is_english, kind, headword, suggestion); consolidate unknown-id rate 0, downgraded-target rate ≤ 10 %, confusable groups all valid. **Go** → enable `auto` with batch 5. **Middle band** (item pass 85–95 %, everything else green) → enable, keep batch 5, configure the step-up as leg 2 (complete cut) or switch `FALLBACK_MODEL` to it when the ledger shows > 15 % `invalid_output`/`partial` on the fallback over a week. **No-go** (< 85 % item pass, or truncation/latency red) → the step-up becomes the primary fallback; GLM-4.7-Flash stays for lookups only (`WD_AI_FALLBACK_KINDS=lookup`).

### 4.4 Later (complete cut, ≈4 person-days)

Eval harness + scorecards for GLM-4.7-Flash and qwen3.7-flash (and DeepSeek-flash if the owner wants a Tokyo-native leg); admin provider control + health + ledger filter; second leg + semaphore + 1308 `retry_at`; smoke step; regenerate-non-Claude action + per-block model label (D3); runbooks (`ops.md`, `DEPLOY.md`), `CLAUDE_INTEGRATION.md` §10; `providers/claude_cli.py` move; flap guard; `ON_BUDGET_CAP` option. Re-check Zhipu's release log twice a year for the free model's successor and the BigModel privacy policy at each re-read.

---

## 5. Risks (top 8) and mitigations

1. **GLM-4.7-Flash produces JSON that is valid but semantically off** (no server-side schema; headword-in-example, length floors, integer enums). Mitigation: schema in the prompt + `jsonschema` on the original schema + one repair re-ask + the unchanged handler gates; eval go/no-go before `auto`; `invalid_output` streak of 3 pauses the fallback; step-up with strict schema one `.env` line away.
2. **Zhipu throttling and single concurrency** (1302/1305/1308, peak hours, June/Nov incidents). Mitigation: concurrency 1, batch 5, `Retry-After`/`next_flush_time` honoured, provider-scoped streaks and pause, optional paid leg 2 on a different platform, prewarm excluded from the fallback.
3. **Free model retired or auto-routed** (≈12-month cadence; terms allow ending free services). Mitigation: model id is config; nightly fallback probe raises `ai_fallback_unavailable` on 1211/404; `spawn_error/config` pauses the slot instead of burning retries; the release log is a twice-yearly checklist item.
4. **Thinking silently on** (default ON on GLM-4.7 and qwen3.7-flash; billed as output; latency). Mitigation: explicit `thinking:{type:disabled}` / `enable_thinking:false` per dialect; `ConfigError` for models that cannot disable it (GLM-5.3*); L3 asserts `completion_tokens ≈ visible JSON`; timeout scale 1.5.
5. **Classifier gaps on either path** (today 403/402/429/Chinese bodies all land in `error` → backoff → bisect → dead; a vendor auth error would otherwise pause *all* AI). Mitigation: code/type-first mapping, Chinese regexes, provider-scoped pauses, a unit table built from the real captured bodies (`令牌已过期或验证不正确`, `身份验证失败。`, `invalid api-key`, `Token is invalid.`, `Authentication Fails (governor)`).
6. **Gate regressions** — 9 call sites and two `ai_enabled` implementations read `claude.paused_until`; missing one leaves lookups, the nightly consolidation, batch building, content ETA or health saying "AI unavailable" while the fallback works. Mitigation: one `failover.availability()` helper, a grep-based unit test that forbids new direct reads of `claude.paused_until` outside `budget`/`failover`, an integration test exercising every gate during failover.
7. **Budget blindness and surprise bills.** Free calls cost 0 (caps cannot bind), paid legs are priced from `usage` × a table the owner maintains; 百炼's `用完即停` is off by default and `延期免停` off for new accounts (verify alibaba omission 4). Mitigation: per-slot hourly cap, `ai_budget_overrun` event, `fallback_cny_month` tile, keep vendor balances small (≤ ¥100), enable `用完即停` on every 百炼 model not meant to be paid.
8. **Terms and data policy.** BigModel may train on anonymised prompts (vocabulary words + ≤120-char sanitised notes; no PII by construction, contract:F5); the free model's commercial use is grey; Ark's licence is mainland-only; Token/Coding plans forbid backends. Mitigation: standard API only, invite-only and non-monetised while on the free tier, a line in the privacy text, Z.ai or 百炼 pay-as-you-go when a no-training promise is required; never route learner names/emails into prompts (the builders already don't).

(Also tracked, below the top 8: provider flapping during partial outages → sticky state, thresholds, flap guard; cross-border degradation Tokyo → Alibaba GA → network streak + configurable base URL/second leg; content-filter 1301 on English vocabulary → per-call `error`, bisection isolates the word, never a trigger; the housekeeping probe blocks the single Claude worker thread ≤ 2 min every 30 min during an outage → acceptable, documented.)

---

## 6. Decisions only the owner can make (with the default this design assumes)

1. **Zhipu region**: BigModel (支付宝/微信, mainland latency, anonymised-training clause) vs Z.ai (no training/no storage, USD card without 3DS, free model's presence on the API unverified). **Default: BigModel**; prompts carry no PII.
2. **Step-up provider**: 百炼 qwen3.7-flash (new Alibaba Cloud account + 实名, strict schema, ¥15/month, no training) vs GLM-4.7-FlashX on the same Zhipu key (¥26–55, same platform risk) vs DeepSeek-flash (Tokyo-native, ¥54–108, outage-prone). **Default: 百炼 qwen3.7-flash as leg 2**, configured only after the eval or the first throttled week.
3. **Fallback kinds**: include `consolidate` (bank edits, with the downgrade-to-`ok` safety net)? include `svg`? **Default: content, lookup, consolidate; no svg.**
4. **Prewarm on the fallback** (`WD_AI_FALLBACK_PREWARM`): **default 0** — the seed fill waits for Claude or runs on the paid leg (≈¥3.3) by explicit choice.
5. **Budget-cap failover** (`WD_AI_FAILOVER_ON_BUDGET_CAP`): turns the USD caps from "stop" into "degrade to the free model". **Default 0.**
6. **Fallback-generated content**: keep forever with a 「备用模型生成」 label (D3 per-block label) or regenerate with Claude when it returns (≈$0.005/word)? **Default: keep; add the admin regenerate action in the complete cut; label when D3's per-block labels land.**
7. **Fail-back granularity**: first successful probe (default) vs N consecutive; constant 30-min cadence (default) vs doubling.
8. **Manual pause semantics**: the admin 暂停 button pauses everything (`ai.paused_until`, default) vs only Claude.
9. **实名 timing on Zhipu**: now (default; instant, removes a "目前" policy risk) vs when recharging.
10. **Where the key lives**: `.env` (0600, default) vs systemd drop-in.

---

## 7. Effort summary

| cut | content | person-days | calendar for a solo part-time developer |
|---|---|---|---|
| Day-1 actions | account, key, curl go/no-go, console limits, regex patch (0.25 d), optional A0 stop-gap | 0.3 | today |
| **MVP** | adapter (zhipu/bailian/generic dialects, json_object + json_schema), transform, pricing, `fake_openai`, failover state machine, `claude_call` loop, provider-scoped pauses, budget/ledger scoping, migration 0010, gates → `availability()`, probe/`ai-check`, config + rename, admin fields + display, tests, env/docs minimum, live tests L1–L6 | **7** | ≈ 2 weeks |
| **Complete** | + `claude_cli` move, `tool` strategy + deepseek/ark, second leg + semaphore + 1308 `retry_at`, admin override/health/filter/UI, nightly fallback probe, eval harness + mock + scorecards (GLM, qwen), smoke step, regenerate-non-Claude action + label hook, runbooks/docs, flap guard, `ON_BUDGET_CAP`, frontend tests | **11** (= 7 + 4) | ≈ 3–4 weeks |

Justification against the fact base: the contract digest priced Option B at 8–10 d *including* failover, admin surface, tests, smoke and docs, and listed the eval harness (1.5–2 d) and the regenerate action (0.5 d) separately → 10–12.5 d for the same scope as this complete cut (11 d). The bytedance slice's ≈2-day transport estimate matches this design's transport rows (`openai_http` 8 h + dialects 2 h + transform 1 h + pricing 1.5 h + `fake_openai` 3 h ≈ 2 d); the other ≈5 MVP days are the failover machine, provider scoping of budget/ledger/pauses, the gate rewrite, config and tests — the parts that make "直接用备选方案" automatic rather than a transport. D3's 5 d "provider-agnostic runner + adapter" is the MVP minus failover/gates/admin, consistent with 7 d here. The MVP deliberately keeps the CLI code inside `runner.py` (no move) to avoid touching the 18 test files that import from it.

---

## 8. Deviations from the fact-base recommendations (deliberate)

1. **Transport first, not the CLI-slot path.** The contract digest's sequence (A0 today → A1 CLI-slot failover ≈4–5 d → B later) and the alibaba slice's "wire the CLI path first, adapter second" are not followed: the fallback never goes through the `claude` binary, because on that path cost is a client-side estimate with `costBasis unknown`, structured output is an unforced synthetic tool call, unknown model ids receive adaptive thinking the CLI cannot switch off, and the CLI keeps anthropic.com dependencies (contract:F6, verify bytedance:F21/omissions 1–4). A0 survives only as a hand-flipped stop-gap in §4.1.
2. **Primary fallback = Zhipu GLM-4.7-Flash (free)**, not the alibaba slice's #1 (百炼 qwen3.7-flash) nor the bytedance slice's #1 (DeepSeek-flash): the owner asked for the best *free* model; the paid ones become the step-up / second leg. The others-and-cli slice's R1 (GLM-4.7-Flash free default) is followed, but on the OpenAI endpoint rather than `/api/anthropic` (undocumented model list, verify others:F6).
3. **ModelScope is excluded from the automatic chain** despite the best free quality (「非商业化，非盈利」, ≈200 calls/day per model, model churn, Alibaba binding) — the alibaba slice already demoted it to tier 3; here it is not wired at all (configurable later through the `generic` dialect).
4. **Failover table changes vs F11**: constant 30-min probe cadence instead of doubling to 4 h (a failed probe costs nothing and fail-back latency matters more than 48 idle spawns/day; a flap guard doubles only after a flap); Zhipu 1308 / `Retry-After` honoured as defer-until (`retry_at`); network errors counted in their own streak but stored as `overloaded` (the CHECK is fixed); balance/quota exhaustion mapped to `auth` with `reason=balance` instead of a new status; prewarm excluded from the fallback by default (new); SVG excluded (same as F11).
5. **Naming**: `WD_AI_PROVIDER=claude_cli|openai_http|auto` (compatible with D3's enum) instead of F11's `claude|fallback|auto`; the slot names in kv stay `claude`/`fallback`. Migration is `0010_ai_provider.sql`; D3's parked `0010_curation_columns.sql` renumbers to 0011 and drops `ai_calls.provider`.
6. **MVP keeps the CLI code in `runner.py`** (dispatch only); the `providers/claude_cli.py` move is in the complete cut (the contract's F8 file list has the move up front).
7. **Eval harness drives the production adapter** (`providers.openai_http.run`) instead of F17's own `call()` per format, and the CI mock is the same file as the test double (`fake_openai.py`) — less code, higher fidelity; F17's metrics and thresholds are kept.
8. **Per-dialect JSON mode defaults** (`json_object` for Zhipu, strict `json_schema` for 百炼/Ark, forced strict tool for DeepSeek with thinking off) instead of F11's single `json_object` default; the eval can still override per slot.
9. **Manual admin pause becomes global** (`ai.paused_until`) and resume clears all automatic pauses — F11 proposed the key; the resume semantics are an addition so that the one button the owner knows still stops and restarts everything.
10. **Zhipu quality numbers from SuperCLUE are not used** for the decision (third-party compilation, cross-edition, verify alibaba:F10); LMArena-zh plus the app's own `validate_item` scorecard are the only quality signals relied on.
