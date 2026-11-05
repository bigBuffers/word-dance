# Design D3 — one Anthropic-format HTTP adapter + automatic provider failover for word-Dance

Date 2026-11-04 · Repo `/Users/sqin/word-dance` @ `9ab13a5` (read-only) · Fact base: `scratchpad/fallback/facts/*.md` + `verify/*.md` (verifications override digests) · Citations: `(slice:Fn)` = digest finding, `(verify-slice:Fn)` = verification, `file:line` = repo @ 9ab13a5, URLs as in the fact base.

Owner question (binding): 「如果 Claude 无法使用，评估匹配国内最优的免费模型做一个备选；当 Claude 不成功，直接用备选方案」. Anthropic policy/licensing is out of scope by the owner's decision; provider terms are in scope.

Orientation of this design: **one HTTP path for everything** — a single adapter that speaks the Anthropic Messages format (`system`, `messages`, `tools`/`tool_use`, `output_config.format` where supported, `usage.*` tokens 1:1 onto the ledger) and serves every domestic Anthropic-format endpoint today (Zhipu, 百炼 workspace host, DeepSeek, Moonshot, MiniMax, Qianfan, TokenHub, SiliconFlow `/v1/messages`, Ark `/api/compatible`, ModelScope beta) and, later, an Anthropic Console key — retiring the `claude` CLI dependency for the fallback path. Per-vendor differences live in a small capability table, not in code branches.

---

## 0. Pitch

**After day 1 (no code, ≈3 h of the owner's time):** a standard Zhipu API key (phone registration, no 实名 to call — zhipu:F9) and the four decisive live calls run from the Mac and from the Tokyo VPS with plain `curl`: (a) the `probe_v1` prompt against `https://open.bigmodel.cn/api/anthropic/v1/messages` with `glm-4.7-flash`, `thinking:{type:"disabled"}` and one client tool — proves the free model is served on the Anthropic path and emits `tool_use` (both undocumented, verify-others:Omission 6); (b) the same with `output_config.format` to learn whether it 400s or is ignored; (c) one real 10-word `content_v1` prompt (`scratchpad/fallback/measure/content_user_prompt_cet4_top10.txt`) for latency/`usage`/validity; (d) the unauthenticated POST from the VPS for reachability. Cost ¥0. The owner knows the go/no-go of the free primary fallback before any code is written, and a one-line regex patch (`\b403\b|forbidden|request not allowed|\b429\b|令牌|身份验证失败|Token is invalid`, 0.25 d) makes today's pause path recognise the region block and Chinese auth bodies.

**After week 1 (MVP, ≈10 person-days of work, so realistically week 2 for a part-time solo developer):** `WD_AI_CHAIN="claude,zhipu"` on the VPS. When a Claude call fails hard (the managed-settings string, `Not logged in`, 403 region block, DNS, binary missing) the *same claimed job group* is re-run within seconds on `glm-4.7-flash` through the HTTP adapter; later claims go straight to Zhipu; a probe every 30 min brings Claude back automatically; the admin AI tab shows 「Claude 暂不可用，已自动切换到备用模型 glm-4.7-flash（自 … 起，每 30 分钟自动探测恢复）」, the ledger shows a 来源 column, every card made by the fallback carries `word_contents.model='glm-4.7-flash'`, and learners never see 「AI 功能当前不可用」 while any provider is healthy. The 6-hour loop of the 2026-11-02 outage (14 `claude_auth` events, 15 failed calls, nothing generated) becomes a 20-second blip.

**After week 3 (complete, ≈16 person-days cumulative):** the chain is `claude,zhipu,bailian` — 百炼 `qwen3.7-flash` (≈¥15/month at 100 content calls/day, strict `output_config.format` JSON Schema, 30,000 RPM) is the paid-but-almost-free step-up that also covers Zhipu's single-concurrency/peak-throttling weakness; `scripts/eval_provider.py` + `scripts/mock_provider_server.py` produce a scorecard per candidate with go/no-go thresholds; the admin tab has the provider switch (auto/claude/zhipu/bailian), the fallback content share, and a 「重新生成非 Claude 内容」 filter; the same adapter is verified against a mock Anthropic endpoint so that an Anthropic Console key would be a config change (`claude-haiku-4-5` / `claude-sonnet-5-5` with `output_config.format`) — the CLI is then needed only for the Enterprise login path.

---

## 1. Fallback model choice

### 1.1 Workload the costs are computed for

Per 10-word content call ≈2k input + ≈4k output tokens (contract:F3: 6.3 KB prompt ≈1.8–2.5k tokens, 3,761–3,893 measured output tokens); 100 content calls/day; +5 lookups (1.5k/1k), ≤10 consolidations (30–35k/4k; worst case 56.5 KB ≈17k prompt tokens → ≥32k context needed), ≤40 SVG (0.6k/1.5k); 30 days; thinking **off**; one-time seed prewarm 912 ten-word calls (1,824 at batch 5). All CNY prices are mainland list prices read on 2026-11-04.

### 1.2 Ranked table (Anthropic-format reachability is a hard requirement of this design)

| # | Model · provider · endpoint | Cost/month at the workload | Free-tier limits | Structured-output mode this adapter uses | Context / max out | Endpoint format | Terms / data policy | Overseas (Tokyo VPS) access | Quality evidence | Stability | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **1** | **GLM-4.7-Flash** · Zhipu BigModel · `https://open.bigmodel.cn/api/anthropic` + `/v1/messages` | **¥0** (price list 免费/免费, zhipu:F1) | No token cap; concurrency console-only, third parties report **1 in-flight request** and peak-hour throttling (verify-zhipu:F3); windowed caps exist in the error vocabulary (code 1308, verify-zhipu:Omission 2); 429 codes 1302/1305 | `tool_auto` (one client tool `submit_content`, `tool_choice:auto` + an instruction naming it) → downgrade `text_json`; forced `tool_choice:tool` tried once and remembered if it works. No `json_object` in the Anthropic format; `output_config` support unknown (verify-zhipu:Omission 4). `thinking:{type:"disabled"}` (GLM-4.7 series defaults ON, zhipu:F5) | 200K / 128K | Anthropic Messages (`Authorization: Bearer` per Zhipu's Claude Code doc; `x-api-key` also answered the probe) · `count_tokens` exists · `HEAD /api/hello` 200 (verify-others:F6) | Standard API key, no Coding Plan (zhipu:F6). No 实名 to call ("目前"), 实名 to recharge/Batch (verify-zhipu:F9). Mainland privacy policy allows anonymised data for model training, no API opt-out; **Z.ai** (`https://api.z.ai/api/anthropic`, same model, Singapore entity) promises no training/no storage (zhipu:F10, F8) | No geo-fencing found; answered from a US exit in 1.3 s; both hosts behind Alibaba GA; Tokyo not yet probed (verify-zhipu:F12) | 30B-A3B; BFCL v3 74.6, τ²-Bench 79.5, SWE-bench V 59.2 (zhipu:F13); **no zh-writing board entry**; GLM-4.7 (big sibling) LMArena zh 1495 vs Sonnet 5.5 1545 | Weakest point: platform-level throttling, multi-day 429/1305 incident (June 2026, Coding Plan), nightly gateway failures Nov 2026 (free Start Plan), no status page (verify-zhipu:F14); GLM-4.5-Flash retired 2026-01-30 with auto-routing (yearly cadence) | **PRIMARY FALLBACK** — content, lookup, consolidate; svg opt-in after the eval |
| **2** | **qwen3.7-flash** · 阿里云百炼 pay-as-you-go · `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/apps/anthropic` + `/v1/messages` (legacy `dashscope.aliyuncs.com` frozen since 2026-09-30, verify-alibaba:Omission 2) | **≈¥15** (0.2/0.8 per 1M at ≤32K input; ≈¥0.0036 per content call; prewarm ≈¥3.3) — valid **only with thinking disabled** (default ON, billed as output, verify-alibaba:F3/F11) | One-time 1,000,000 tokens per model, 90 days, Beijing only, 实名 required, 用完即停 **off by default** (silent billing after, verify-alibaba:F1); 30,000 RPM / 5M TPM (alibaba:F5) | `output_config.format` `{type:"json_schema", schema}` — **strict** on qwen3.8/3.7/glm/most deepseek (NOT deepseek-v4.1-flash → 400), `additionalProperties:false` required (verify-alibaba:F4); `thinking:{type:"disabled"}`; `output_config.effort` instead of `budget_tokens` | 1M / 131K | Anthropic Messages + platform extension `output_config`; `x-api-key` or Bearer; no `/v1/models` (404); 3600 s request timeout on the workspace host | 实名 + Aliyun account; §6.2.5 no training without authorisation on pay-as-you-go; **Token Plan / Coding Plan forbidden for backends and authorise training** (alibaba:F7) | Beijing endpoint answered from a US exit (401); no caller-IP clause; Tokyo region `ap-northeast-1` at Beijing prices under 全球 scope but separate key and no free quota; whether a 中国站 account may open it is unverified (verify-alibaba:F6) | No public score for 3.7-flash; qwen3.8-flash 66.4 on a third-party SuperCLUE compilation (weak evidence, verify-alibaba:F10); strict schema + `validate_item` buy reliability more cheaply than model size | No 2026 outage found; soft 429s recover in a minute; ≥3-month retirement notice; retired models stop (no reroute) (alibaba:F12) | **STEP-UP** (paid, almost free) — all kinds; becomes the fallback if GLM-4.7-Flash fails the eval; also the third leg of the chain |
| 3 | GLM-5.3-Flash · Zhipu, same key | ¥29–58 (0.8/2.8) but **thinking cannot be disabled** → output ×2 realistic (zhipu:F5, F16) | paid; same V0 concurrency tier | `tool_auto` → `text_json` (same unknowns as #1) | 1M / 128K | same as #1 | same as #1 | same as #1 | LMArena zh #20 **1530** (Sonnet 5.5 1545, verify-alibaba:F10) — best "Flash" on the zh board | same platform risk as #1 | Quality step-up **on the same key** (no second account); not the default step-up because it does not diversify the platform risk and thinking is forced |
| 4 | GLM-4.7-FlashX · Zhipu, same key | ¥26–55 (0.5/3) | paid | same as #1 | 200K / 128K | same | same | same | same class as #1 | same platform | "pay to escape the free concurrency" option only |
| 5 | deepseek-flash (V4.1-Flash-1017) · DeepSeek · `https://api.deepseek.com/anthropic` | ¥54 off-peak / ¥108 peak (1/4 vs 2/8); no free tier, no sign-up credit (bytedance-deepseek:F2, F3) | none; concurrency 2500 | forced `tool_choice:{type:"tool"}` **only with `thinking:{type:"disabled"}`** (400 in thinking mode); `output_config.format` ignored; `any` = `auto` (verify-bytedance:F4) | 1M / 384K | Anthropic Messages (Bearer or x-api-key); vendor id `deepseek-flash` accepted; unknown non-claude names → 400; 401 is plain text `Authentication Fails (governor)` | single global platform, PayPal/cards; privacy policy permits training with opt-out (second-hand quotes); 实名 to top up | Tokyo-friendly (global platform) | LMArena zh #30 1523; SuperCLUE 71.8 (third-party compilation) | **19th major outage of 2026 on 2026-11-03** (bytedance-deepseek:F19) | second paid option when a non-Alibaba, Tokyo-friendly leg is wanted |
| 6 | MiniMax-M3 · `https://api.minimax.cn/anthropic` (`X-Api-Key`) | ¥113 (2.1/8.4); M3.1-Flash ¥54 nominal but thinking forced | voucher activity-dependent; free 20 RPM | forced tool (`tool_choice` supported); no output format; thinking off by default on M3; temperature/top_p ignored (verify-bytedance:F15) | 1M | Anthropic Messages | 实名; region-bound keys (CN vs intl) | choose platform to match the server | IFBench 82.9 (vendor), LMArena zh 1472 | minute-scale error spikes Aug 2026 | reserve |
| 7 | Doubao-Seed-2.1-lite · Volcengine Ark · `https://ark.cn-beijing.volces.com/api/compatible` + `/v1/messages` | ¥37 (0.8/2.7); one-time free quota activity-dependent | — | top-level **`output_format:{type:"json_schema"}`** (Ark's own field name, not `output_config`), or named `tool_choice:tool`; `thinking:disabled`; **default max output 4k → set explicitly** (verify-bytedance:F8) | 1M / 256K | Anthropic Messages (x-api-key) | §3.1 authorises use **「仅在中国大陆地区」** and requires written permission for any 直接或间接获得收益 (verify-bytedance:F10) | outside the licence wording from Tokyo; BytePlus ModelArk is the compliant overseas sibling | SuperCLUE 2026-07 Doubao-2.1-pro 65.95 | app-level incidents only | excluded while the server is in Tokyo; preset kept for a mainland host |
| 8 | Kimi K3.1 Pro · Moonshot · `https://api.moonshot.cn/anthropic` | ≈¥894 (13/68) + reasoning tokens, thinking always on (effort `max` default) | ¥15 voucher not valid on K3/K3.1; Tier0 1 concurrency / 3 RPM until ¥50 (verify-bytedance:F12) | native `output_config.format` json_schema; `tool_choice` any/auto/none (no named tool) (verify-bytedance:F13) | 1M / 131K default out | Anthropic Messages (Bearer) | inputs/outputs licensed for 模型服务优化, no opt-out; "education" advice carve-out (bytedance-deepseek:F14) | no documented geo block | best Chinese instruction following (SuperCLUE 2026-07 70.68) | consumer-app outage 2026-07 | consolidate-only quality tier at most; not recommended |
| 9 | Qwen/Qwen3-8B · SiliconFlow · `https://api.siliconflow.cn` + `/v1/messages` (**not** `/anthropic`) | **¥0** (permanently free ≤9B set, rotates) | fixed RPM/TPM per free model (console-only); 实名 unlocks all free models; 401 body `{"code":30014,"message":"Token is invalid."}` (verify-others:F4) | forced tool (`tool_choice` Auto/Tool/None), `thinking: ThinkingDisabled`; no json_schema anywhere | ~32K / — | Anthropic Messages (Bearer) | privacy: no long-term storage, no training (2026-07-30 policy) | optional IP whitelist; no geo restriction documented | IFEval 83–85, BFCL 60–68 (Qwen3 report, 2025) — a different class from the ≥30B Flash models (others:F15) | free models answer `X-RateLimit-Remaining: 0` when throttled | emergency free tier for lookup/content (batch 5) only; same key escalates to paid DeepSeek-V4-Flash / GLM-5.3-Flash by changing the model id |
| 10 | DeepSeek-V4.1-Flash / GLM-5.2 / Qwen3.5-397B · ModelScope API-Inference · `https://api-inference.modelscope.cn` + `/v1/messages` (Beta) | ¥0 | 2,000 calls/day/account, ≈200/day per model, single concurrency, reset 00:00 UTC+8, quota headers `modelscope-ratelimit-*` (verify-alibaba:F8) | forced tool if the beta path supports `tools` (unverified) → `text_json` | model-dependent | Beta Anthropic path; token without `ms-`; **non-Anthropic error body** `{"detail":"Error code: 401 - …"}` | **officially 非商业化、非盈利**, not for online/SLA use; Alibaba Cloud binding + 实名 | `.cn` loaded from a US exit | strongest free quality (LMArena zh 1523/1525) | unannounced quota cuts, model churn (Kimi-K2, Qwen3-235B gone) | dev/test and paired-eval baseline only; never in the production chain |
| 11 | glm-5.3-flash / deepseek-v4.1-flash / hy3 · Tencent TokenHub · `https://tokenhub-intl.tencentmaas.com` (Singapore, 全球) or `https://tokenhub.tencentmaas.com` (广州) + `/v1/messages` | paid USD (Hy3 $0.132/$0.528; GLM-5.3 $1.4/$4.4); | 1M free tokens / 90 days once per model (promo to 2026-12-31) (verify-others:F3) | forced tool → `text_json` (output_config unknown) | model-dependent | Anthropic Messages (Bearer); Anthropic error envelope with `code:"401002"` | Tencent 实名; data processed in the PRC; no unauthorised use | the one domestic gateway with a scheduled Singapore endpoint — Tokyo-friendly | per hosted model | new platform (legacy Hunyuan shut 2026-09-30) | later option for the Tokyo box |
| 12 | third-party models · Baidu Qianfan · `https://qianfan.baidubce.com/anthropic` + `/v1/messages` | paid | none for text LLMs (free ERNIE tier retired 2026-06-09) | forced tool → `text_json` | model-dependent | Anthropic Messages (x-api-key); envelope `api_error` "Missing API key" (verify-others:Omission 1) | Baidu 实名 | unknown | per hosted model | — | later option |
| 13 | `claude-haiku-4-5` / `claude-sonnet-5-5` · Anthropic Console key · `https://api.anthropic.com` + `/v1/messages` | Haiku ≈$0.022/call → ≈$66/month; Sonnet 5.5 ≈$0.044/call → ≈$132/month (claude-api skill price table; today's measured CLI cost $0.040/call) | — | `output_config.format` json_schema (GA, no beta header); **forced `tool_choice` returns 400 on Sonnet 5.5 / Opus 5.5 / Fable 5.1**; Sonnet 5.5 cannot disable thinking → omit + `output_config.effort:"low"`; Haiku 4.5: omit `thinking` = off (claude-api skill) | 1M / 128K (Haiku 200K) | Anthropic Messages (`x-api-key` + `anthropic-version: 2023-06-01`); standard error types; `retry-after` | Anthropic's terms (policy deferred by the owner — not analysed here) | reachable from Tokyo | the quality bar itself | — | the eventual CLI-retirement path for the *primary*; verified against the mock only in this plan |
| — | Baidu ERNIE-Speed/Lite (retired 2026-06-09), Tencent hunyuan-lite (retired 2026-06-22), iFlytek Spark Lite (8K in / 4K out, QPS≈2, no tool calling, no Anthropic path) | — | — | — | — | — | — | — | — | — | not viable (others:F1–F3) |

### 1.3 Decision

* **Primary fallback = Zhipu GLM-4.7-Flash** on the standard-key Anthropic endpoint. It is the only *permanently free, commercial-grade, 200K-context, tool-calling* domestic model (contract brief (a); others:F6, R1; zhipu:Summary). Its two weaknesses — single-concurrency throttling and undocumented behaviour on `/api/anthropic` — are handled by the per-provider semaphore/batch/timeout settings and by the capability-downgrade logic, and are *measured* on day 1 before anyone depends on it.
* **Step-up = 百炼 `qwen3.7-flash`** (pay-as-you-go, workspace Anthropic host, strict `output_config.format`, thinking disabled). ≈¥15/month covers *all* jobs; 30,000 RPM removes the concurrency problem entirely; data is not trained on; it diversifies away from Zhipu's platform. It is the second leg of the automatic chain once the owner has done 实名 and created the workspace key (`claude → zhipu → bailian`), and it replaces GLM-4.7-Flash as the first leg if the eval scorecard says NO-GO (section 4.3).
* **Same-key alternative** when the owner does not want a second account: `WD_AI_ZHIPU_MODEL=glm-5.3-flash` (¥29–58/month, LMArena zh 1530, thinking forced) — a one-line change in the same slot.
* **Job routing on the fallback:** `content`, `lookup`, `consolidate` → fallback (all candidates have ≥128K context; worst-case consolidate needs ≥32k, contract:F3); `svg` → **not** routed to the fallback until the eval shows the sanitiser pass rate ≥90% (`WD_AI_ZHIPU_KINDS="content,lookup,consolidate"`); `probe` → every provider; SiliconFlow-class 32K models would be limited to `content,lookup` by their slot's `KINDS`.
* Z.ai vs BigModel: same model, same request shape; the owner picks by payment rail and data policy (section 6, D1).

### 1.4 What is lost versus the OpenAI-format adapter (D3 option B) and what is gained

| | OpenAI chat-completions adapter | **This Anthropic Messages adapter** |
|---|---|---|
| Zhipu structured output | `response_format:{type:"json_object"}` documented, `tool_choice` auto only (zhipu:F5) | **No `json_object` equivalent** → `tool_auto`/`text_json` + client validation; forced tool and `output_config` undocumented on `/api/anthropic` (verify-zhipu:Omission 4). *Loss: the one documented JSON mode of the free model; mitigated by the day-1 test and the downgrade ladder.* |
| DeepSeek | `json_object` + `strict` tool calls (beta) | forced tool only with thinking off (which we send anyway); `output_config.format` ignored. *Minor loss: no `strict` guarantee on arguments.* |
| 百炼 / Kimi / Ark strict schema | `response_format json_schema strict` | equivalent: `output_config.format` (百炼, Kimi) / `output_format` (Ark). *No loss.* |
| SiliconFlow | `json_object` on all LLMs | forced tool on `/v1/messages`. *No loss in practice.* |
| ModelScope | documented OpenAI endpoint | Beta Anthropic path with a non-Anthropic error body; tools/`output_config` unverified. *Loss: ModelScope becomes dev-only — acceptable, it is non-commercial anyway.* |
| iFlytek Spark, legacy Hunyuan | reachable | unreachable. *No loss: both unfit.* |
| OpenRouter / other aggregators | reachable | OpenRouter also has an Anthropic path; others vary. |
| Anthropic Console key (future) | needs a second adapter | **same adapter, same tests, same ledger** — Sonnet 5.5 / Haiku 4.5 with `output_config.format`. *Gain.* |
| Prompt layout / injection boundary | `messages=[system,user]` | real top-level `system` field; `<items>` block unchanged; no tools except our one `submit_*` tool. *Gain (contract:F5).* |
| Usage accounting | `prompt_tokens/completion_tokens` (+ vendor-specific cache fields) | `usage.input_tokens/output_tokens/cache_read_input_tokens/cache_creation_input_tokens` map **1:1** onto `ai_calls` columns the CLI envelope already uses (`runner.py:250-255`). *Gain.* |
| Error envelope | `{"error":{"code","message","type"}}`, vendor-specific | `{"type":"error","error":{"type":"authentication_error"\|"rate_limit_error"\|"overloaded_error"\|"api_error"\|"invalid_request_error"\|"permission_error"\|"billing_error"\|"not_found_error"}}` at Anthropic, 百炼, TokenHub, MiniMax, Qianfan, DeepSeek(JSON cases); Zhipu/SiliconFlow/ModelScope need dialect rules. *Mostly gain.* |
| `stop_reason` semantics | `finish_reason: length/stop/tool_calls/content_filter` | `max_tokens` / `end_turn` / `tool_use` / `refusal` — identical across vendors. *Gain.* |
| Rate-limit signalling | vendor headers | `retry-after` + `anthropic-ratelimit-*` where implemented; vendor codes otherwise. *Neutral.* |

Net: the only real loss is Zhipu's documented `json_object` mode. Everything else is neutral or a gain, and the gain that matters most for the owner — one adapter, one test double, one ledger model for domestic vendors *and* a future Console key — is why this design builds C instead of B (deviation 8.1).

---

## 2. Architecture

### 2.1 Module map (what exists, what is new)

The verified seam is the function `wd.ai.runner.run_claude` (`runner.py:388-495`), called by `common.claude_call` (`common.py:133-184`) and by `probe._attempt` with the CLI-only kwargs `tier=` / `fallback_on_usage_error=` (`probe.py:73-88`); the `ClaudeRunner` protocol / `runner.Runner` class is never instantiated (verify-contract:F1, Omission 3). Handlers consume `ok/status/structured/cost_usd/model_used/call_id/error` and two of them rebuild the dataclass by keyword (`content.py:443`, `lookup.py:574`) — new fields therefore get defaults at the end (contract:F18.4).

```
backend/wd/ai/
  runner.py            façade: run_claude(..., provider=None) → providers.get(name).run(...); keeps load_schema/load_prompt/
                       build_argv/claude_env/parse_and_classify/save_raw/prune_logs/Parsed exported (16–18 test files import them)
  providers/__init__.py  ProviderSpec, PRESETS (capability table §2.3), get(name), specs_from_settings(cfg), per-provider semaphores
  providers/base.py      Provider protocol (run / probe_mode / name)
  providers/claude_cli.py  today's run_claude body (Popen, killpg, save_raw, parse_and_classify) unchanged in behaviour
  providers/anthropic_http.py  the HTTP adapter (§2.4): build_request → post → parse → validate → repair → Parsed
  providers/schema_transform.py  for_dialect(schema, dialect) + validate_original(schema, obj)  (call-time only; files untouched, test_schemas.py:22-23)
  providers/pricing.py   cost_usd(spec, usage, now): CNY/USD tables per model, peak/off-peak, WD_CNY_PER_USD
  providers/errors.py    classify(status_code, headers, body, exc, dialect) → (status ∈ ledger.STATUSES, reason, retry_after_s, until)
  failover.py            the state machine (§2.5): select, record_failure, record_success, maybe_probe, any_provider_available,
                         earliest_available_at, banner_zh, override
  common.py              claude_call: select → reserve(provider) → run → on failure record_failure → immediate retry on the next
                         provider; handle_failure: job actions only, pauses read from failover (single writer)
  budget.py              provider-scoped paused_until / calls_last_hour / estimate / can_spend / reserve; spend_summary fields
  ledger.py              provider column; call_dto; aggregates with provider filters; fallback_content_share
  probe.py               check(conn, cfg, provider=None): CLI keeps the tier dance; HTTP providers one tier-less attempt
  models.py              unchanged (lax mirrors stay the second pass; jsonschema on the ORIGINAL schema runs first in the adapter)
backend/wd/migrations/0010_ai_provider.sql
backend/tests/fake_anthropic.py, scripts/mock_provider_server.py, scripts/eval_provider.py
```

### 2.2 Exact request/response flow for a Claude failure (chain `claude,zhipu`)

1. `ClaudeWorker.step` → `process_next` (`worker.py:80-93`) asks `failover.active_spec(conn, cfg, now)` and claims `queue.limit_for(job_type, cfg, batch_size=spec.batch_size)` jobs (today `limit_for` reads only `cfg.ai_batch_size`, `queue.py:38-44`). Active = `claude` → 10 content jobs.
2. The handler builds the prompts exactly as today (`content.py:404-416`) and calls `common.claude_call(ctx, conn, kind="content", jobs=…)`.
3. `claude_call` → `spec = failover.select(conn, cfg, kind, now)`: kill switch off? manual `kv.ai.paused_until` elapsed? `kv.ai.provider_override` absent → active provider `claude` (not paused, `available != 0`, kind allowed) → `spec(claude)`.
4. `budget.reserve(..., provider="claude", model_requested=cfg.ai_model)` → `can_spend` (kill switch · global pause · **provider** pause · **provider** hourly cap · monthly/daily caps with `estimate(kind, words, provider)` · prewarm/SVG sub-caps) → inserts the `running` row with `provider='claude'` (migration 0010).
5. `runner.run_claude(..., provider="claude", call_id=…)` → `providers.claude_cli.run` → `Popen` as today → the CLI exits 1 with `Your organization requires remote managed settings to load…` after ≈18 s (live calls 33–47). `parse_and_classify` → `status="auth"` (matched by `log ?in`), **new** `reason="auth"` (`AUTH_RE` extended; `REGION_RE`, `NETWORK_RE`, `BILLING_RE`, `USAGE_LIMIT_RE` added). `_finish` writes the row (`status=auth`, `provider=claude`).
6. `claude_call` → `decision = failover.record_failure(conn, cfg, "claude", result, now)`: hard trigger → `kv.claude.paused_until = now+30min` (the key keeps its name but now means *the Claude provider's* pause), `kv.ai.active_provider = "zhipu"`, `kv.ai.failover.{since, reason, from, trigger_call_id}`, `kv.ai.failover.next_probe_at = now+30min`, `system_events('ai_failover', {from:"claude", to:"zhipu", reason:"auth", error:…, trigger_call_id:33, banner_zh:…})`, `budget.event_once('claude_auth', …)` as today for the admin events list. Returns `Decision(switch_to=spec(zhipu), retry_now=True)`.
7. **Immediate retry of the same still-claimed group**: `budget.reserve(..., provider="zhipu", model_requested="glm-4.7-flash")` (reserved_usd 0 — free price table; zhipu hourly cap counted separately) → `runner.run_claude(..., provider="zhipu")` → `providers.anthropic_http.run`:
   1. acquire the `zhipu` semaphore (1 slot; wait ≤ timeout);
   2. `build_request(spec, kind, system_prompt, user_prompt, schema)` → `POST https://open.bigmodel.cn/api/anthropic/v1/messages`, headers `Authorization: Bearer <key>`, `anthropic-version: 2023-06-01`, `content-type: application/json`; body `{"model":"glm-4.7-flash","max_tokens":8192,"system":<content_system.txt>+"\n\nAnswer only by calling the tool submit_content exactly once.","messages":[{"role":"user","content":<user prompt with the <items> block>}],"thinking":{"type":"disabled"},"tools":[{"name":"submit_content","description":"Return the complete result.","input_schema":<content_v1 + additionalProperties:false>}],"tool_choice":{"type":"auto","disable_parallel_tool_use":true}}` (strategy `tool_auto`; `tool` if the learned caps say forced choice works);
   3. `httpx.Client(timeout=Timeout(connect=10, read=270, write=30, pool=10), trust_env=False)` — 180 s × `timeout_scale 1.5`; direct egress, never the Mac/VPS proxy meant for anthropic.com;
   4. response 200 → `content[]`: the `tool_use` block named `submit_content` → `.input`; else text blocks → fence-strip → outermost `{…}`; `stop_reason` checked (`max_tokens` → `invalid_output/truncated`, `refusal` → `error/content_filter`);
   5. `schema_transform.validate_original(content_v1, obj)` with `jsonschema.Draft202012Validator` **before** the pydantic mirrors (verify-contract:Omission 1: the mirrors coerce `true → 1`); on failure one repair round (§2.4) then `invalid_output/schema`;
   6. `usage.{input_tokens,output_tokens,cache_read_input_tokens,cache_creation_input_tokens}` → ledger columns; `model` → `model_used`; `id` → `session_id` (request id for support); `cost_usd = pricing.cost_usd(spec, usage, now)` = 0;
   7. `save_raw` stores `{request: {url, model, strategy, body_sha, body_excerpt}, response: body}` under `claude-logs/YYYY-MM-DD/<call_id>.json` — headers never written;
   8. semaphore released; `_finish` → `ClaudeResult(ok=True, status="success", structured=obj, cost_usd=0, call_id, model_used="glm-4.7-flash", error=None, provider="zhipu", model_requested="glm-4.7-flash", reason=None)`.
8. `claude_call` → `failover.record_success(conn, "zhipu", now)` (resets zhipu streaks) and returns the result; the handler applies items exactly as today; `content.py:423` becomes `model = result.model_used or result.model_requested or ctx.cfg.ai_model` so `word_contents.model='glm-4.7-flash'`.
9. If the fallback also fails on the immediate retry, `claude_call` returns the **fallback's** result; `common.handle_failure` applies the §6.3 table to it (defer 2 min × attempts for `overloaded`, backoff/bisect for `invalid_output`/`error`, …) reading pauses from `failover` (never setting them); at most one immediate retry per claim — no ping-pong.
10. Later claims: `select()` returns `zhipu` directly (sticky). Every 5 min `ClaudeWorker.housekeeping` (`worker.py:260-270`) calls `failover.maybe_probe`: when `now ≥ next_probe_at` it runs `probe.check(conn, cfg, provider="claude")` (one `ai_calls` row, kind `probe`, ≤$0.05, the only thing that touches Claude during the outage). Success → **fail back**: `kv.ai.active_provider` deleted, `claude.paused_until` cleared, `system_events('ai_failback', {outage_min, probe_call_id})`; failure → `next_probe_at = now + 30 min` (60 min after 6 h of outage). A *successful ordinary Claude call* (e.g. after its pause elapsed and zhipu was itself paused) also fails back.

User-facing gates during step 10: `routers/words.py:324-325`, `routers/bank.py:150`, `admin_ops.py:363`, `services/bank.py:221-237`, `services/words.py:415-424`, `services/batches.py:384,497-498`, `jobs/scheduler.py:252`, `diag.py:78-104`, `admin_ops.py:193-199` all ask `failover.any_provider_available(conn, cfg, now, kind=…)` / `failover.earliest_available_at(...)` instead of `kv.claude.paused_until` — otherwise the fallback stays invisible and learners keep getting 503 `ai_disabled` (verify-contract:Omission 2). `routers/auth.py:55` (`ServerFlags.ai_enabled`) keeps meaning "kill switch off".

### 2.3 Capability table (static presets in `providers/__init__.py`; every column overridable per slot)

| preset | base_url (+ `/v1/messages`) | auth header | default model | strategy order (first that the caps allow; 400 naming a field → next) | thinking | output-format field | forced `tool_choice:tool` | error dialect | conc. | batch | timeout × | max out | price (per 1M) | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `claude` (kind `claude_cli`) | — | — | `sonnet` | CLI `--json-schema` | CLI | — | — | CLI regexes | `WD_AI_CONCURRENCY` | `WD_AI_BATCH_SIZE` | 1.0 | CLI | CLI estimate | unchanged |
| `zhipu` | `https://open.bigmodel.cn/api/anthropic` | `Authorization: Bearer` | `glm-4.7-flash` | `tool` → `tool_auto` → `text_json` | `{type:"disabled"}` | unknown (`output_config` not attempted by default) | unknown → learned | `zhipu` (`error.type` numeric strings 1000/1001/1003/1113/1211/1301/1302/1305/1308, Chinese messages) | 1 | 5 | 1.5 | 8192 | 0 / 0 | `count_tokens` exists; GLM-5.3-Flash on the same preset: thinking cannot be disabled → `omit` |
| `zai` | `https://api.z.ai/api/anthropic` | Bearer | `glm-4.7-flash` (presence on api.z.ai unconfirmed, verify-zhipu:Omission 6) | same | same | same | same | `zhipu` | 1 | 5 | 1.5 | 8192 | 0 / 0 | no-training terms |
| `bailian` | `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/apps/anthropic` (owner fills the id; `ap-northeast-1` for Tokyo) | `x-api-key` | `qwen3.7-flash` | `output_config` (strict; **not** for `deepseek-v4.1-flash*`) → `tool` → `text_json` | `{type:"disabled"}` (default ON) | `output_config.format` | yes | `anthropic` + codes `Throttling.RateQuota`, `Throttling.AllocationQuota`, `Arrearage`, `AllocationQuota.FreeTierOnly`, `invalid api-key` | 3 | 10 | 1.0 | 8192 | ≤32K in 0.2 / 0.8; 32–256K 0.6 / 2.4 (CNY) | `output_config.effort` not `budget_tokens`; temperature ∈ [0,2) |
| `deepseek` | `https://api.deepseek.com/anthropic` | Bearer | `deepseek-flash` | `tool` (needs thinking off) → `text_json` | `{type:"disabled"}` | ignored | yes (thinking off) | `anthropic` + plain-text 401 `Authentication Fails (governor)` | 3 | 10 | 1.0 | 8192 | peak 2 / 8, off-peak 1 / 4 (Mon–Fri 09–12, 14–18 Beijing) | `max_tokens` may be raised by their compatibility handling |
| `moonshot` | `https://api.moonshot.cn/anthropic` | Bearer | `kimi-k3.1-pro` | `output_config` → `tool_auto` (`any`/`auto` only) → `text_json` | forced on → `output_config.effort:"low"` | `output_config.format` | no (no named tool) | `anthropic` (`incorrect_api_key_error`) | 1 (Tier0) | 10 | 1.5 | 16384 | 13 / 68 | consolidate only by default |
| `minimax` | `https://api.minimax.cn/anthropic` | `X-Api-Key` | `MiniMax-M3` | `tool` → `text_json` | `omit` (M3 default off; M3.1-Flash rejects `disabled`) | none | yes | `anthropic` | 3 | 10 | 1.0 | 8192 | 2.1 / 8.4 | temperature ignored |
| `ark` | `https://ark.cn-beijing.volces.com/api/compatible` | `x-api-key` | `doubao-seed-2-1-lite-260915` | `output_format` (top-level) → `tool` → `text_json` | `{type:"disabled"}` | `output_format` | yes (`any` best-effort) | `anthropic` (`AuthenticationError`) | 3 | 10 | 1.0 | 8192 (default 4k!) | 0.8 / 2.7 | preset flagged `mainland_only_terms=True` → refused at config load unless `WD_AI_ARK_ACK_TERMS=1` |
| `qianfan` | `https://qianfan.baidubce.com/anthropic` | `x-api-key` | (none) | `tool` → `text_json` | `{type:"disabled"}` | unknown | unknown | `anthropic` (`api_error` "Missing API key") | 3 | 10 | 1.0 | 8192 | per model | |
| `tokenhub` / `tokenhub_intl` | `https://tokenhub.tencentmaas.com` / `https://tokenhub-intl.tencentmaas.com` | Bearer | (none) | `tool` → `text_json` | `{type:"disabled"}` | unknown | unknown | `anthropic` (+ `code:"401002"`) | 3 | 10 | 1.0 | 8192 | per model (USD on intl) | `HEAD /api/hello` 404 — harmless |
| `siliconflow` | `https://api.siliconflow.cn` | Bearer | `Qwen/Qwen3-8B` | `tool` → `text_json` | `ThinkingDisabled` | none | yes | `siliconflow` (`{"code":30014,"message":"Token is invalid."}`, 403 实名, 429 "rate limiting") | 1 | 5 | 1.5 | 4096 | 0 / 0 (free set) | `KINDS=content,lookup` (32K-class context) |
| `modelscope` | `https://api-inference.modelscope.cn` | Bearer (no `ms-`) | `deepseek-ai/DeepSeek-V4.1-Flash` | `tool` → `text_json` | `{type:"disabled"}` | unknown | unknown | `modelscope` (`{"detail":"Error code: 401 - …"}`, 403 no key) | 1 | 5 | 1.5 | 8192 | 0 / 0 | reads `modelscope-ratelimit-*-remaining` into `kv.ai.modelscope.quota`; `KINDS=lookup,svg`; preset flagged `non_commercial=True` (admin banner note) |
| `anthropic` | `https://api.anthropic.com` | `x-api-key` | `claude-haiku-4-5` | `output_config` → (`tool` only for Haiku 4.5) | Sonnet 5.5/Opus 5.5: `omit` + `effort:"low"` (`disabled` → 400); Haiku 4.5: `omit` (= off) | `output_config.format` (GA, no beta) | Sonnet 5.5 / Opus 5.5 / Fable 5.1 → **400**; Haiku 4.5 yes | `anthropic` | 3 | 10 | 1.0 | 8192 | Haiku $1 / $5; Sonnet 5.5 $2 / $10; cache read ×0.1 | `retry-after` honoured; `anthropic-ratelimit-*` logged |

Schema dialects used by the strategies: `tool` → every object gets `additionalProperties:false`, all other keywords kept (advisory for non-strict vendors; valid for Haiku `strict:true`); `output_config` (Anthropic proper, 百炼, Kimi) → `additionalProperties:false` + **drop every `maxItems` and every `minItems > 1`** into the `description` (Anthropic supports `minItems` 0/1 only, contract:F2; 百炼 supports them but the same transform is harmless); `output_format` (Ark) → same as `tool`; `text_json` → the compact ORIGINAL schema is appended to the system prompt. Validation always runs against the **original** file schema.

### 2.4 The adapter in detail (`providers/anthropic_http.py`)

* **Request** — `system` is a top-level string (no tier-0 folding, no `‹items›` rewrite needed; `<items>` stays the only data block, contract:F5); `messages=[{"role":"user","content":user_prompt}]`; `max_tokens = min(spec.max_output_tokens, per-kind floor: content 8192, lookup 4096, consolidate 12288, svg 4096, probe 512)` (contract:F3 output sizes; never the vendor default — Ark's is 4k); `temperature` omitted (vendor default) unless `spec.temperature`; `thinking` per caps; `metadata`, `cache_control`, `anthropic-beta` never sent (vendors 400 on unknown betas; Anthropic's structured outputs need none).
* **Strategies** — `output_config`: `{"output_config":{"format":{"type":"json_schema","schema":T}}}` (+ `"effort"` when thinking is forced on); `output_format` (Ark): `{"output_format":{"type":"json_schema","schema":T}}`; `tool`: `tools=[{name:"submit_<kind>", description, input_schema:T}]`, `tool_choice={"type":"tool","name":"submit_<kind>"}`; `tool_auto`: same tool, `tool_choice={"type":"auto","disable_parallel_tool_use":true}` and the system prompt gains one line naming the tool; `text_json`: no tools, system prompt gains "Respond with exactly one JSON object matching this JSON Schema and nothing else (no markdown fences): <compact schema>". Vendors with `anthropic`-type forced-choice 400s (Sonnet 5.5) never get `tool`.
* **Capability downgrade (bounded)** — a 400 whose message names a field we control (`output_config`, `output_format`, `tool_choice`, `thinking`, `tools`, `disable_parallel_tool_use`, `Extra inputs`, `Unexpected`) triggers **one** retry inside the same call with the next strategy (or `thinking` omitted); the result is remembered in `kv.ai.<p>.caps_learned` (JSON: `{"output_config":false,"tool_forced":true,"thinking_disabled":false}`) so later calls skip the failing feature; the admin probe button and `wd ai-check --provider P --relearn` clear it. Other 400s are `error/bad_request` (no trigger).
* **Repair round** — when the parsed object fails the original schema (or no JSON was found) and the strategy is not strict `output_config`, one follow-up request in the same call: `messages += [assistant(content blocks as returned), user("The previous answer failed validation: <first 5 jsonschema messages>. Return the complete corrected result the same way.")]`; tokens are summed on the row, `error` notes `repaired=1`; still invalid → `invalid_output/schema`. `WD_AI_<P>_REPAIR=0` disables it (the free tier has latency to spare; the paid tier rarely needs it).
* **Classification** (`providers/errors.py`, status must stay inside `ledger.STATUSES`, `ledger.py:21`; the finer `reason` rides on `ClaudeResult.reason` and in `error` text):
  * `status ∈ ledger.STATUSES` (CHECK constraint fixed, `0001_init.sql:512`): `success · error · timeout · invalid_output · budget · auth · overloaded · spawn_error`.
  * `reason`: `auth · billing · region · config · network · rate_limit · quota_window · overloaded · content_filter · bad_request · truncated · unparseable · schema · timeout · local_concurrency`.
  * `budget` is **never** produced by the adapter (its handler action is bisection, meant for the CLI's `--max-budget-usd` stop); out-of-money cases are `auth/billing` (operator action), windowed quotas are `overloaded/quota_window` with an `until` instant.
* **Semaphore** — `providers.slot(spec)` = `threading.BoundedSemaphore(spec.concurrency)` per provider name, acquired around the HTTP request(s) only; acquisition timeout = the call timeout → `overloaded/local_concurrency` (defer) rather than piling onto a free tier.
* **Raw logs** — `save_raw(cfg, call_id, request_meta, stdout=json.dumps(response), stderr=error, exit_code=http_status)`; the body excerpt is capped at 20 KB; `Authorization`/`x-api-key` are never part of the payload (the existing `argv` field holds `["anthropic_http", spec.name, url, strategy]`).
* **Probe** — `probe.check(conn, cfg, provider=P)` for HTTP providers runs `_attempt` once with `tier="0"` semantics (no flags), expects the exact `EXPECTED` object (`probe.py:42,91-92`) and writes `kv.ai.P.available`, `kv.ai.P.last_probe_at`, `kv.ai.P.model_seen`; `record_version` stays CLI-only.

### 2.5 Failover state machine (`ai/failover.py`) — F11 adopted with four changes

Adopted from contract:F11: sticky `kv.ai.active_provider`, provider-scoped pauses with `kv.claude.paused_until` kept as the primary's key, hard/soft triggers, the recovery probe through `probe.check`, the immediate retry of the same claimed group, the "any provider available" user gate, the banner texts, `WD_AI_FAILOVER_*` thresholds. Changed (argued in §8): (1) an **ordered chain of N named slots** (`WD_AI_CHAIN`) instead of the `claude|fallback|auto` tri-state and a single `WD_AI_FALLBACK_*` block — the step-up is then a third slot, not a redeploy; (2) the recovery probe runs **every 30 min fixed (60 min after 6 h)** instead of doubling to a 4-h cap; (3) network errors classify as `overloaded/network` (defer path) instead of `error`; (4) `failover.record_failure` is the **single writer** of pauses/streaks/events — `handle_failure` only moves jobs.

```
select(conn, cfg, kind, now) -> ProviderSpec | None
  if not budget.ai_enabled: None                                   # kill switch (global, unchanged)
  if kv.ai.paused_until > now: None                                # manual admin pause (global, new key)
  order = [override] if kv.ai.provider_override else rotate(chain, start=kv.ai.active_provider or chain[0])
  return first p in order with kind in p.kinds and not paused(p) and kv.ai.p.available != '0'
  # rotate(): active first, then the rest of the chain in order, then the providers *before* the active one
  # (so an expired primary pause lets the primary be tried again — a success there fails back)

record_failure(conn, cfg, p, result, now) -> Decision(switch_to, retry_now)
  hard  (status auth|spawn_error, or reason in {auth, billing, region, config, quota_window}):
        pause(p, until = result.until or now+COOLDOWN(30 min); billing/config: +24 h, event ai_provider_paused)
        event ai_failover if p is chain[0] (plus claude_auth event_once for the existing banner/tests)
        return Decision(next_available(after p), retry_now=True)
  soft  (overloaded/rate_limit/network/timeout): streak[p][kind] += 1
        overloaded streak >= 6 → 15-min pause (today's rule, common.py:248-263, now per provider)
        streak >= WD_AI_FAILOVER_{OVERLOADED,TIMEOUT,NETWORK}_AFTER → pause(p, COOLDOWN) + switch + retry_now
        else Decision(None)
  quality (invalid_output): streak[p].invalid += 1; if p is a fallback and streak >= WD_AI_FALLBACK_INVALID_AFTER (3):
        pause(p, 30 min) + event ai_fallback_quality; never retry_now (the bisection path must run)
  never a trigger: error/bad_request, content_filter, budget, truncated, schema (bisection isolates the bad word)

record_success(conn, p, now): streaks[p] = 0; if p == chain[0] and kv.ai.active_provider set → fail_back(reason='primary_call_ok')

maybe_probe(conn, cfg, now)   # from ClaudeWorker.housekeeping every 5 min
  if WD_AI_FAILBACK == 'auto' and kv.ai.active_provider and not override and now >= kv.ai.failover.next_probe_at:
      r = probe.check(conn, cfg, provider=chain[0])
      ok → fail_back(reason='probe_ok')  (clears claude.paused_until, deletes ai.active_provider + ai.failover.*, event ai_failback)
      else next_probe_at = now + (30 min if outage < 6 h else 60 min); event ai_failover_probe (event_once 30 min)

any_provider_available(conn, cfg, now, kind='content') -> bool  == select(...) is not None
earliest_available_at(conn, cfg, now, kind) -> iso | None       # min pause expiry over the chain; drives queue.defer and ETAs
banner_zh(conn, cfg, now) -> str | None                          # texts in §3
```

Hysteresis: one flip per outage (sticky) — per-call alternation would double latency and make the ledger unreadable (contract:F11). After a fail-back a *hard* failure switches again immediately (one failed call is the cost); soft streaks restart at 0.

### 2.6 New config keys (frozen `Settings`, `config.py`; defaults = today's behaviour when unset)

| key | default | meaning |
|---|---|---|
| `WD_AI_CHAIN` | `claude` | ordered provider slots, comma-separated slot names `[a-z][a-z0-9_]*`. `claude` = today; `claude,zhipu` = automatic failover; `zhipu` = fallback only (no CLI needed); `claude,zhipu,bailian` = two-leg chain. The slot named `claude` is always the CLI provider configured by today's `WD_CLAUDE_*` / `WD_AI_MODEL` / `WD_AI_BATCH_SIZE` / `WD_AI_CONCURRENCY` keys. |
| `WD_AI_CLI_FALLBACK_MODEL` | `""` | **renamed** from `WD_AI_FALLBACK_MODEL` (`config.py:91,334`, `runner.py:145-146`, `env.example:62`, `DEPLOY.md:320`): the CLI's own Claude-only `--fallback-model` chain. The old name is accepted with a deprecation warning for one release (contract:F6.7, F18.1). |
| `WD_AI_<SLOT>_PRESET` | the slot name | capability-table row (§2.3) that fills every unset `_SLOT_` key; a `ConfigError` names unknown presets and slots without `_API_KEY`. |
| `WD_AI_<SLOT>_API_KEY` | — (required) | secret; `config.is_secret()` masks every `WD_AI_*_API_KEY` in `GET /api/admin/config` (extends the `SECRET_KEYS` frozenset at `config.py:44-53`) and logging. |
| `WD_AI_<SLOT>_MODEL` | preset | vendor model id (full id — it is what `ai_calls.model_requested` and `word_contents.model` record). |
| `WD_AI_<SLOT>_BASE_URL` | preset | override (Z.ai, 百炼 workspace/Tokyo host, TokenHub intl). |
| `WD_AI_<SLOT>_AUTH_HEADER` | preset | `bearer` or `x-api-key`. |
| `WD_AI_<SLOT>_JSON_MODE` | `""` = preset order | `output_config` / `output_format` / `tool` / `tool_auto` / `text_json`; a comma list fixes the downgrade order. |
| `WD_AI_<SLOT>_THINKING` | preset | `disabled` / `omit` / `effort_low`. |
| `WD_AI_<SLOT>_BATCH_SIZE` | preset (zhipu 5) | content words per claim while this provider is active (clamped 1–12 like `WD_AI_BATCH_SIZE`). |
| `WD_AI_<SLOT>_CONCURRENCY` | preset (zhipu 1) | in-flight requests to this provider across all worker threads (semaphore). |
| `WD_AI_<SLOT>_TIMEOUT_SCALE` | preset (zhipu 1.5) | multiplies `budget.timeout_for(cfg, kind)`. |
| `WD_AI_<SLOT>_MAX_OUTPUT_TOKENS` | preset (8192) | `max_tokens` ceiling (floors per kind apply). |
| `WD_AI_<SLOT>_HOURLY_CALL_CAP` | `60` | per-provider hourly cap (`ledger.count_started(..., provider=)`); the Claude slot keeps `WD_AI_HOURLY_CALL_CAP`. |
| `WD_AI_<SLOT>_KINDS` | preset (`content,lookup,consolidate`) | job kinds this provider may serve (`probe` always). |
| `WD_AI_<SLOT>_PRICE_JSON` | preset | `{"in":…, "out":…, "cache_read":…, "currency":"CNY"\|"USD", "peak":{…}}` per 1M tokens; `{}` = free. |
| `WD_AI_<SLOT>_PROXY` | `""` (direct) | explicit proxy URL for this provider only; the adapter runs with `trust_env=False`. |
| `WD_AI_<SLOT>_REPAIR` | `1` | repair rounds (0/1). |
| `WD_AI_<SLOT>_TEMPERATURE` | `""` | sent only when set. |
| `WD_CNY_PER_USD` | `7.2` | converts CNY price tables into the USD `cost_usd` the caps use. |
| `WD_AI_FAILOVER_COOLDOWN_MIN` | `30` | provider pause after a hard trigger / soft threshold. |
| `WD_AI_FAILOVER_PROBE_EVERY_MIN` | `30` | recovery-probe cadence (×2 after 6 h of outage, capped at 60). |
| `WD_AI_FAILOVER_OVERLOADED_AFTER` / `_TIMEOUT_AFTER` / `_NETWORK_AFTER` | `3` / `2` / `2` | consecutive soft failures before switching. |
| `WD_AI_FALLBACK_INVALID_AFTER` | `3` | consecutive `invalid_output` on a fallback → 30-min quality pause. |
| `WD_AI_FAILOVER_ON_BUDGET_CAP` | `0` | `1` = when Claude's daily/monthly cap refuses a group, run it on the next provider whose estimate is 0 (owner decision D4). |
| `WD_AI_FAILBACK` | `auto` | `manual` = never probe back; the admin switch does it. |
| `WD_AI_ARK_ACK_TERMS` | `0` | presets flagged `mainland_only_terms` refuse to load without it. |

Example VPS `.env` after week 1: `WD_AI_CHAIN="claude,zhipu"`, `WD_AI_ZHIPU_API_KEY="…"`; after week 3: `WD_AI_CHAIN="claude,zhipu,bailian"`, `WD_AI_BAILIAN_API_KEY="…"`, `WD_AI_BAILIAN_BASE_URL="https://llm-xxxx.cn-beijing.maas.aliyuncs.com/apps/anthropic"`.

### 2.7 kv keys

| key | written by | meaning |
|---|---|---|
| `ai.active_provider` | `failover.record_failure` / `fail_back` | current sticky provider; absent = `chain[0]` |
| `ai.failover.since` / `.reason` / `.from` / `.trigger_call_id` / `.next_probe_at` / `.probe_count` | failover | outage bookkeeping shown in the admin tab |
| `ai.provider_override` | `POST /api/admin/ai/provider` | `auto` (deleted) or a slot name |
| `ai.paused_until` | `POST /api/admin/ai/pause` | **manual global pause** (24 h as today, `admin_ops.py:312-333`); replaces the route's write to `claude.paused_until` |
| `claude.paused_until` | failover only | the **Claude provider's** automatic pause (key kept: 9–10 test files pin it) |
| `claude.available` / `claude.flag_tier` / `claude.last_probe_at` / `claude.version` / `claude.enabled` | probe / admin (unchanged) | CLI provider state; `claude.enabled` stays the global kill switch |
| `claude.overloaded_streak` | failover | Claude's overloaded streak (name kept; `test_worker.py:287`) |
| `ai.<p>.paused_until` / `.available` / `.last_probe_at` / `.model_seen` | failover / probe | per HTTP provider |
| `ai.<p>.streak.overloaded` / `.timeout` / `.network` / `.invalid` | failover | soft-trigger counters |
| `ai.<p>.caps_learned` | adapter | learned capability downgrades (JSON) |
| `ai.<p>.quota_reset_at` | adapter (Zhipu 1308 `next_flush_time`, ModelScope daily reset) | pause horizon |
| `ai.<p>.quota` | adapter (ModelScope headers) | `{requests_remaining, model_requests_remaining, seen_at}` |

`kv` is the free-form table (`0001_init.sql`, `SCHEMA.sql:50-54`) — no migration for these.

### 2.8 Migration `0010_ai_provider.sql` (additive, safe under `install.sh --no-restart`)

```sql
-- 0010_ai_provider.sql — which provider served an ai_calls row (CLAUDE_INTEGRATION §10). Purely additive (DEPLOY §10).
-- docs/SCHEMA.sql stays byte-identical to 0001 (tests/unit/test_db.py:362-366); the column is documented in §10.
ALTER TABLE ai_calls ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude';
CREATE INDEX IF NOT EXISTS ix_ai_calls_provider_started ON ai_calls(provider, started_at);
```

`model_requested` keeps the vendor model id (`glm-4.7-flash`, not an alias — the fallback slots always carry full ids; the CLI slot still writes `sonnet`, as the 68 live rows do, verify-contract:F10). No change to `ai_calls.status` (CHECK fixed), `jobs.type`, `system_events.kind` (free text), `word_contents.model` (already per row, `content.py:213-218`). Numbering: design-D3 of the curation plan reserved `0010_curation_columns.sql` including `ai_calls.provider` (`docs/analysis/2026-11-04-library-curation/design-D3-model-and-compliance.txt:167`); this work ships first as **0010**, the curation migration becomes **0011** and drops its `ai_calls.provider` line (`db.run_migrations` applies `sorted(d.glob("*.sql"))`, `db.py:161-163`, and records each file; gaps are fine, `0008_fk_child_indexes.sql:8-10`).

### 2.9 Admin API / UI fields (F13 adopted; `schemas.py` ↔ `types.ts` must move together — `scripts/check_contract.py`)

| surface | change |
|---|---|
| `AdminOverviewAi` (`schemas.py:1110-1122`, `types.ts:190-192`, `budget.spend_summary` `budget.py:289-309`) | + `chain: string[]`, `active_provider: string`, `override: string \| null`, `failover_since: string \| null`, `failover_reason: string \| null`, `next_probe_at: string \| null`, `banner_zh: string \| null`, `fallback_calls_today: int`, `fallback_content_share_7d: float \| null` (`COUNT(*) FILTER (WHERE model NOT LIKE 'claude-%') / COUNT(*)` over `word_contents` created in 7 d), `providers: [{name, kind, model, available: bool \| null, paused_until, last_probe_at, calls_today, hourly_call_cap, non_commercial: bool}]` |
| `AiCall` (`schemas.py:1280-1293`, `ledger.call_dto` `ledger.py:187-204`, `types.ts:207`) | + `provider: string` |
| `AdminHealth` (`schemas.py:1181-1194`, `admin_ops.py:193-199`) | `claude_bin` unchanged; + `ai_providers: [{name, kind, model, base_host, ok, last_probe_at}]` |
| `ProbeResponse` / `POST /api/admin/ai/probe` (`schemas.py:1311`, `admin_ops.py:336-350`) | body `{provider?: string}` (default `chain[0]`); response + `provider`; the 1/min guard becomes per provider (`kv.ai.<p>.probe_started_at`) |
| `POST /api/admin/ai/pause` (`admin_ops.py:312-333`) | writes/clears `kv.ai.paused_until` (global); resume also clears every provider pause, `ai.active_provider`, and `claude.enabled='1'` as today; events `claude_paused`/`claude_resumed` kept |
| **new** `POST /api/admin/ai/provider` `{mode: "auto" \| "<slot>"}` → `{mode, active_provider}` | sets/deletes `kv.ai.provider_override`; `system_events('ai_provider_override', {by, mode})`; API.md endpoint 66b |
| `GET /api/admin/config` (API.md 73) | masks `WD_AI_*_API_KEY` |
| frontend `AdminPage.tsx` AI tab (`:705-830`) | banner line from `ai.banner_zh` above the tiles; segmented control 自动 / claude / zhipu / bailian next to 暂停/探测 (`endpoints.adminAiProvider`); 探测 gets a provider dropdown; a 来源 (`provider`) column in the ledger table; a 「备用模型生成占比（7 日）」 tile; health card lists `ai_providers` |
| `zh.ts:87-95` | `probe: '探测'`, `provider: '当前模型来源'`, `providerAuto: '自动'`, `failoverActive: (m, since, n) => …`, `bothDown`, `fallbackQuality`, `fallbackShare7d: '备用模型生成占比（7 日）'`, `source: '来源'` |
| `ServerFlags.ai_enabled` (`routers/auth.py:55`) | unchanged (kill switch) |

### 2.10 File-level change list (hours; MVP rows marked ●, complete-phase rows ○)

| file | function / area | change | h |
|---|---|---|---|
| ● `backend/wd/ai/providers/__init__.py` (new) | `ProviderSpec`, `PRESETS`, `specs_from_settings`, `get`, `slot` | capability table §2.3, slot resolution, per-provider `BoundedSemaphore` registry | 4 |
| ● `backend/wd/ai/providers/base.py` (new) | `Provider` protocol | `run(conn, *, kind, system_prompt, user_prompt, schema, max_budget_usd, timeout_s, word_count, job_ids, cfg, now, call_id, tier=None, fallback_on_usage_error=True) -> ClaudeResult` | 0.5 |
| ● `backend/wd/ai/providers/claude_cli.py` (new) | `run` | today's `run_claude` body moved verbatim (Popen/killpg/save_raw/parse_and_classify/tier-1 usage-error retry) | 2 |
| ● `backend/wd/ai/providers/anthropic_http.py` (new) | `build_request`, `post`, `parse_response`, `extract_json`, `repair`, `run` | §2.4 | 10 |
| ● `backend/wd/ai/providers/schema_transform.py` (new) | `for_dialect`, `validate_original` | add `additionalProperties:false`; `output_config` dialect drops `maxItems`/`minItems>1` into descriptions; `jsonschema.Draft202012Validator` | 2 |
| ● `backend/wd/ai/providers/pricing.py` (new) | `cost_usd`, `PRICES` | CNY/USD tables incl. 百炼 tiers and DeepSeek peak schedule; `WD_CNY_PER_USD` | 2 |
| ● `backend/wd/ai/providers/errors.py` (new) | `classify` | status + reason + `retry_after_s` + `until` per dialect (§3) | 3 |
| ● `backend/wd/ai/runner.py` | `run_claude` (`:388-495`), module docstring | becomes the façade: `provider: str \| None` kw, dispatch; `AUTH_RE/OVERLOADED_RE` extended + `REGION_RE`, `NETWORK_RE`, `BILLING_RE`, `USAGE_LIMIT_RE`; `parse_and_classify` sets `Parsed.reason`; `save_raw` accepts `request_meta`; re-exports kept | 3 |
| ● `backend/wd/ai/failover.py` (new) | §2.5 | state machine, banner, gates | 6 |
| ● `backend/wd/ai/common.py` | `claude_call` (`:133-184`), `handle_failure` (`:210-282`), `record_success` (`:201-205`), `AUTH_BANNER_ZH` | provider selection + immediate retry; pauses/streaks read from failover; `banner_zh()`; `handle_failure` defers to `max(backoff, provider pause)` | 4 |
| ● `backend/wd/ai/budget.py` | `paused_until`, `set_paused_until`, `calls_last_hour`, `estimate`, `can_spend`, `reserve`, `spend_summary` | `provider` parameter everywhere; free provider → `estimate 0`; per-provider hourly cap; global manual pause key | 3 |
| ● `backend/wd/ai/ledger.py` | `insert_call`, `call_dto`, `count_started`, `sum_cost`, `last_error`, new `fallback_content_share` | `provider` column/filters | 2 |
| ● `backend/wd/ai/probe.py` | `check`, `_attempt`, `cmd_claude_check` | `provider=` kw; HTTP providers tier-less; `wd ai-check [--provider NAME\|all] [--relearn]` with `claude-check` alias (`cli.py:49` `COMMAND_OWNERS`) | 3 |
| ● `backend/wd/interfaces.py` | `ClaudeResult` (`:82-92`) | + `provider: str = "claude"`, `model_requested: str \| None = None`, `reason: str \| None = None` (defaults, at the end) | 0.5 |
| ● `backend/wd/config.py` | `Settings`, `from_env`, `SECRET_KEYS` → `is_secret()` | §2.6 keys, slot parsing, rename with deprecation, `ConfigError` texts | 4 |
| ● `backend/wd/ai/content.py:423`, `lookup.py`, `consolidate.py`, `svg.py` | provenance | `result.model_used or result.model_requested or cfg.ai_model`; `queue.finish` result gets `provider` | 1 |
| ● `backend/wd/jobs/queue.py:38-44` + `jobs/worker.py:80-93` | `limit_for`, `process_next` | claim size from the active provider | 1 |
| ● `backend/wd/jobs/worker.py:260-270` | `ClaudeWorker.housekeeping` | `failover.maybe_probe` | 0.5 |
| ● gates: `routers/words.py:324-325`, `routers/bank.py:150`, `routers/admin_ops.py:363`, `services/bank.py:221-237`, `services/words.py:415-424`, `services/batches.py:384,497-498`, `jobs/scheduler.py:252` | | `failover.any_provider_available` / `earliest_available_at` (keep the helper names `bank.ai_enabled`/`bank.ai_paused_until` as thin wrappers to limit churn) | 2 |
| ● `backend/wd/diag.py:78-104` | `check_claude` → `check_ai` (alias `claude`) | per-provider lines | 1 |
| ● `backend/wd/routers/admin_ops.py` | health `:193-199`, pause `:312-333`, probe `:336-350`, new `ai_provider` route, overview | §2.9 | 3 |
| ● `backend/wd/schemas.py` + `frontend/src/api/types.ts` | §2.9 models | fields | 1.5 |
| ● `backend/wd/migrations/0010_ai_provider.sql` (new) | | §2.8 | 0.5 |
| ● `frontend/src/pages/AdminPage.tsx`, `endpoints.ts`, `i18n/zh.ts` | AI tab | banner, 来源 column, provider control, probe dropdown | 4 |
| ● `backend/requirements.txt` | | `jsonschema>=4.26` becomes a runtime dependency (today only `requirements-dev.txt:3`) | 0.25 |
| ● `backend/tests/fake_anthropic.py` (new) | `handle`, `serve` | §2.11 | 4 |
| ● tests (§2.11) | | new + edits | 12 |
| ● `deploy/install.sh:48-49,142-143`, `deploy/env.example:53-85`, `scripts/dev.sh:25-29`, `scripts/smoke.py` | §2.12 | | 3 |
| ● docs: `CLAUDE_INTEGRATION.md` §1/§3/§7 + new §10, `DEPLOY.md` §4 + runbook `:420`, `ops.md:196`, `API.md` 54/55/64–66 + 66b, `SCHEMA.sql` comment-free (pinned) | | | 3 |
| ○ `scripts/eval_provider.py`, `scripts/mock_provider_server.py` (new) | F17 harness through the real adapter | §4.3 | 12 |
| ○ `backend/wd/ai/failover.py` | N-chain polish, `caps_learned` persistence, override UI states | | 4 |
| ○ `routers/admin_ops.py` + `AdminPage.tsx` | 「重新生成非 Claude 内容」 filter (`word_contents.model NOT LIKE 'claude-%'` → `regenerate` jobs, limit-sized) + fallback share tile | | 4 |
| ○ `providers/anthropic_http.py` | Anthropic-proper verification against the mock (`output_config`, `retry-after`, `anthropic-ratelimit-*`, `refusal`), optional Batch (`/v1/messages/batches`) for prewarm at 50 % | | 8 |
| ○ `deploy/word-dance.service` comment, `docs/ops.md` runbook rows for each provider | | | 2 |

### 2.11 Test doubles and test files

**`backend/tests/fake_anthropic.py`** (stdlib + `httpx` for the request/response types): `handle(request: httpx.Request) -> httpx.Response` and `serve(host, port)` (`http.server`). It reuses `fake_claude.py`'s item builders (`content_item`, `lookup_item`, `consolidate_item`, `svg_output`, `fake_claude.py:170-262`, importable — verify-contract:F17), infers the kind from the schema inside `tools[0].input_schema` / `output_config.format.schema` / `output_format.schema` / the system-prompt tail, reads the words from the `<items>` block, and answers in the shape the request asked for (`tool_use` block for `tool`/`tool_auto`, text block for `output_config`/`text_json`). Modes via `FAKE_ANTHROPIC_MODE` env or `X-Mock-Mode` header; dialect via `X-Mock-Dialect` (`anthropic` default, `zhipu`, `bailian`, `siliconflow`, `modelscope`, `tokenhub`):

`ok · ok_text · ok_fenced · tool_missing (text instead of tool_use) · invalid_json · schema_mismatch (difficulty "3") · bool_difficulty (true — must be rejected by jsonschema, not coerced) · partial · truncated (stop_reason max_tokens) · slow:<s> · 401 · zh_401 (令牌已过期或验证不正确, type "401") · zh_1000 (身份验证失败) · 402 · 403_arrearage · 403_region ("Request not allowed") · 404_model · 429 (+ Retry-After: 7) · zh_1302 · zh_1305 · zh_1308 (next_flush_time = now+40min) · 500 · 503 · 529 · content_filter_1301 · refusal · 400_output_config ("Extra inputs are not permitted: output_config") · 400_tool_choice · 400_thinking · empty_content · conn_reset · usage_missing`

Unit tests inject it through `httpx.MockTransport(fake_anthropic.handle)` (the `smoke_mock.py:85` pattern; the adapter takes an optional `transport`); smoke and the eval harness run it as a process (`scripts/mock_provider_server.py` imports `handle`). A second `fake_claude` wrapper in `auth` mode (`tests/unit/test_runner.py:33-46` `make_wrapper`) stays the primary-down double.

**New test files:** `tests/unit/test_anthropic_http.py` (request shapes per strategy/preset; classification table — every mode above → expected `(status, reason, trigger)`; downgrade ladder; repair; usage→ledger; cost; raw log has no key), `tests/unit/test_schema_transform.py` (dialects; the five fixtures `tests/fixtures/claude_*_ok.json` still validate against the original; `bool_difficulty` rejected), `tests/unit/test_pricing.py` (CNY tiers, peak window, free), `tests/unit/test_failover.py` (select rotation, hard/soft/quality decisions, probe cadence, fail-back, override, banners, both-down), `tests/integration/test_failover_worker.py` (chain `claude(auth wrapper),fake` → group re-run on the fake within the same drain; chain `claude` alone → today's pause; probe fail-back after `clock.advance(31 min)`; gates answer 200 while failed over).

**Edited:** `conftest.py` (settings with `ai_chain`), `test_runner.py` (provider kw; regex cases incl. `Request not allowed (403)`, `402 Insufficient Balance`, `ENOTFOUND`, `令牌已过期` without a code), `test_budget.py` (provider-scoped pause/hourly; free estimate 0), `test_config.py` (new keys, rename, `is_secret`), `test_db.py` (0010 applied; SCHEMA pin untouched), `test_deploy_files.py:253` (dry run prints `wd ai-check --provider all`), `test_worker.py:280-295` (single-provider pause path kept; new chain variant in the new file), `test_admin_ops.py` (overview/health fields, provider route, probe body, pause writes `ai.paused_until`), `test_schemas.py`, `test_api_schemas.py`, `test_cli.py` (alias), `test_bank.py`, `test_batches.py`, `test_words_resolve.py`, `test_scheduler.py` (gates), frontend `zh.test.ts`, `zh.contract.test.ts`; `scripts/check_contract.py` must stay green; `scripts/smoke.py` gains step 「failover: fake claude auth → mock provider」 (`smoke.py:176-186` env, `:414` drain).

### 2.12 Deploy / install / dev changes

* `deploy/install.sh:48-49`: the `command -v claude` abort applies only when `claude` ∈ `WD_AI_CHAIN` (read from the existing `.env` or the template; default chain contains it, so nothing changes for today's install); `:142-143` → `wd ai-check --provider all || echo "WARN: …"` (warn only, as today; `test_deploy_files.py:253` updated).
* `deploy/env.example:53-85`: rename `WD_AI_FALLBACK_MODEL` → `WD_AI_CLI_FALLBACK_MODEL`; new block 「备用模型（HTTP）」 with `WD_AI_CHAIN`, one commented `zhipu` slot and one commented `bailian` slot, the failover thresholds.
* `deploy/word-dance.service:33-34`: comment gains "with a chain that has no `claude` slot, `ProtectHome=read-only` is possible" (no change to the unit itself).
* `backend/requirements.txt`: `+ jsonschema>=4.26,<5`.
* `scripts/dev.sh:25-29`: optional `WD_AI_CHAIN="claude,fake"` with `WD_AI_FAKE_PRESET=anthropic`, `WD_AI_FAKE_BASE_URL=http://127.0.0.1:8011`, `WD_AI_FAKE_API_KEY=dev`, and `scripts/mock_provider_server.py` started alongside.
* VPS rollout: `git pull` → `install.sh --no-restart` (runs `wd migrate` → 0010) → edit `.env` (`WD_AI_CHAIN`, `WD_AI_ZHIPU_API_KEY`) → `sudo systemctl restart word-dance` → `wd ai-check --provider zhipu` (free) → admin tab shows the `zhipu` row `available=1`. Rollback = `WD_AI_CHAIN="claude"` + restart (the column stays, harmless).
* Runbook row (`ops.md:196`, `DEPLOY.md:420`): "Claude not logged in / token expired / managed settings unreachable → banner 「已自动切换到备用模型」, jobs keep flowing on `zhipu`; fix Claude at leisure (`sudo -iu sqin claude` login, or wait for the network); the 30-min probe fails back automatically; press 探测 claude to fail back now".

### 2.13 The live-ledger outage, minute by minute, with this design (chain `claude,zhipu`; UTC; CST = +8)

Real events: `ai_calls` 33–47 all `auth` with "Your organization requires remote managed settings to load…", 2026-11-02 18:43:40Z → 2026-11-03 02:26:20Z, 14 `claude_auth` events, `kv.claude.paused_until = 02:56:20Z`, first success 02:56:21Z (call 48). The jobs: 3 nightly `consolidate_bank` (18:43, 19:15, 19:48 — 02:43 CST onward), then 12 ten-word `generate_content` claims (prefetch/prewarm) every ≈30 min, nothing produced for 8 h 13 min.

| time (UTC) | today (observed) | with this design |
|---|---|---|
| 18:43:22 | worker claims consolidate for user A; CLI spawn | same claim (active = claude) |
| 18:43:40 | call 33 exits 1 after 18.4 s → `auth`; `claude.paused_until=19:13:40`; `claude_auth` event; job deferred to 19:13:40 | call 33 → `auth`; `record_failure`: Claude paused until 19:13:40, `ai.active_provider=zhipu`, `ai_failover` event, banner set; **immediate retry**: call 34 `provider=zhipu`, POST to open.bigmodel.cn |
| 18:44:15 | — | call 34 returns (≈35 s at ~100 tok/s for ≈2.5k output tokens of a 15-item consolidate); `consolidation_runs` done for user A; suggestions visible at breakfast |
| 18:44–18:46 | — | users B and C's consolidations claimed one after another (semaphore 1), both served by zhipu (calls 35, 36) |
| 18:48 | — | housekeeping tick: `next_probe_at` 19:13:40 not reached |
| 19:13:40 | consolidate retried on Claude → call 34 `auth` → paused until 19:45:55 (loop) | 19:15 housekeeping: probe call 37 on Claude (`kind=probe`, 18 s) → `auth` → `next_probe_at = 19:45`; `ai_failover_probe` event; Claude pause refreshed; **no job touches Claude** |
| 20:23 | content claim → call 36 `auth` | content claim of **5** words (zhipu batch) → zhipu, ≈25 s, 5 cards stored with `model='glm-4.7-flash'`; the plan's remaining words follow at ≈30 s intervals while the prewarm pass keeps enqueueing (hourly cap 60 on zhipu, prewarm `$`-stop never fires at cost 0 → the plan runs to its `limit`) |
| 19:45 · 20:15 · 20:45 · … · 02:45 | 13 more `auth` calls, one every ≈30 min, each wasting ≈18 s and an attempt | 15 probes (one each 30 min; after 6 h — from 00:43 — every 60 min: 00:45, 01:45, 02:45), ≈15 × $0.004 = $0.06 of Claude probes; all other work on zhipu |
| 02:26:20 | call 47 `auth`; pause until 02:56:20 | (no change) |
| 02:45 | — | probe → still `auth` → `next_probe_at = 03:45` |
| 02:56:21 | call 48 succeeds on Claude (the network to anthropic.com is back); backlog starts draining 8 h late | zhipu keeps serving; nothing queued is late |
| 03:45 | — | probe succeeds → **fail back**: `ai.active_provider` cleared, `claude.paused_until` cleared, `ai_failback {outage_min: 541, probe_call_id: …}`; next claims go to Claude (3 batches of 10); banner disappears |
| after | 48 words have content, 9,114 none | ≈120 fallback-made cards exist (`word_contents.model='glm-4.7-flash'`); the admin sees 「备用模型生成占比（7 日）」 and may queue 「重新生成非 Claude 内容」 (≈$0.005/word) or keep them |

If Zhipu had been throttled at 18:43 (1302): call 34 → `overloaded/rate_limit` → `handle_failure` defers the consolidate group 2 min (no attempt consumed) on the **zhipu** result; the next claim retries zhipu (active); three such in a row → zhipu paused 30 min and, with no third provider, `select()` → None → jobs defer to `earliest_available_at` (Claude's 19:13:40), banner 「AI 暂时不可用（主模型与备用模型均失败），任务已排队等待」, user routes answer 503 as today. With `bailian` as a third slot the group would instead have been re-run there.

---

## 3. Failure → action table

"switch" = `record_failure` pauses the provider for the cooldown, moves `ai.active_provider` to the next available slot, writes the event, and `claude_call` re-runs the **same claimed group once** on that slot immediately. "defer" = today's `queue.defer` (no attempt consumed). "backoff/bisect" = today's §6.3 path (`common.py:233-247`). Thresholds are the `WD_AI_FAILOVER_*` defaults.

| signal (source) | ledger status · reason | trigger | provider cooldown | job action (`handle_failure` on the last result) | banner / event |
|---|---|---|---|---|---|
| CLI `Not logged in` · `log ?in` · `authentication` · `unauthori[sz]ed` · `\b401\b` · `credential` · the managed-settings string · **new** `令牌已过期` · `身份验证失败` · `Token is invalid` · `invalid api-?key` · `incorrect_api_key` | `auth` · `auth` | **hard** | 30 min (`claude.paused_until` for the CLI slot) | retry on next slot; if none → defer to pause end (today) | `ai_failover` (+ `claude_auth` once/30 min as today); 「Claude 暂不可用，已自动切换到备用模型 {model}（自 {since} 起，每 30 分钟自动探测恢复）」 |
| HTTP 401 / envelope `authentication_error` / Zhipu type 1000·1001·1003 / SiliconFlow code 30014 / DeepSeek plain-text `Authentication Fails` / Qianfan `Missing API key` | `auth` · `auth` | hard | 30 min | same | same (from the fallback: `ai_provider_paused`) |
| HTTP 403 `permission_error` · `Request not allowed` · `forbidden` (region block from api.anthropic.com per `~/word-dance-data/bin/claude-wrapper`) · SiliconFlow 403 该模型需要实名认证 · **new CLI `REGION_RE`** | `auth` · `region` | hard | 30 min | same | event detail says `region`; banner adds 「（访问被拒绝/地区限制）」 |
| HTTP 402 `billing_error` · `insufficient balance` · `余额不足` · `欠费` · Zhipu 1113 (429 欠费) · 百炼 403 `Arrearage` · `AllocationQuota.FreeTierOnly` · CLI usage-limit phrases (`usage limit`, `plan limit`, `enforced_spend_limit_reached`, `credit balance`) **new `BILLING_RE`/`USAGE_LIMIT_RE`** | `auth` · `billing` | hard | **24 h** (operator action) | same | `ai_provider_paused {reason: billing}`; 「{provider} 余额不足/额度用尽，已暂停 24 小时」 |
| HTTP 404 `not_found_error` on `/v1/messages` · Zhipu 1211 模型不存在 · 400 naming an unknown `model` · misconfigured base URL (404 HTML) | `spawn_error` · `config` | hard | 24 h + `ai.<p>.available=0` | same | `ai_provider_paused {reason: config}`; `wd ai-check --provider P` to clear |
| CLI binary missing / `ENOENT` / `EACCES` (`runner.py:450`) | `spawn_error` · `config` | hard | 30 min + `claude.available=0` (today) | same | as today |
| HTTP 429 `rate_limit_error` · Zhipu 1302 (account concurrency) · 百炼 `Throttling.RateQuota` / `Requests rate limit exceeded` / `Allocated quota exceeded` / `Request rate increased too quickly` · SiliconFlow "rate limiting" · MiniMax/Kimi 429 · **CLI `\b429\b`** | `overloaded` · `rate_limit` | **soft** (3 in a row → switch) | after the 3rd: 30 min; after 6: 15 min (today's rule, per provider) | defer `max(2 min × attempts, Retry-After, anthropic-ratelimit-*-reset)` | `claude_overloaded`-style event per provider; banner only when switched |
| Zhipu 1308 「已达到 … 的使用上限。您的限额将在 {next_flush_time} 重置」 · ModelScope daily 429 (`modelscope-ratelimit-requests-remaining: 0`) | `overloaded` · `quota_window` | **hard** (retrying cannot help) | until `next_flush_time` (parsed; fallback 60 min; ModelScope: next 00:00 UTC+8) | retry on next slot | `ai_provider_paused {reason: quota_window, until}` |
| HTTP 500/502/504 `api_error` · 503 · 529 `overloaded_error` · Zhipu 1305 该模型当前访问量过大 · CLI `overloaded|529|503` | `overloaded` · `overloaded` | soft (3 → switch) | as rate_limit | defer 2 min × attempts | as above |
| connect/DNS/TLS/reset errors (`httpx.ConnectError`, `ConnectTimeout`, `RemoteProtocolError`, `ReadError`) · **CLI `NETWORK_RE`** (`ENOTFOUND|ECONNREFUSED|ECONNRESET|ETIMEDOUT|EAI_AGAIN|Can't reach the API|Connection refused|fetch failed|socket hang up|malformed response \(HTTP 200\)|certificate`) | `overloaded` · `network` | soft (2 → switch) | 30 min after the 2nd | defer 2 min × attempts | event detail `network`; banner adds 「（网络不可达）」 |
| read timeout (`httpx.ReadTimeout`) · CLI `communicate(timeout)` kill | `timeout` · `timeout` | soft (2 consecutive → switch) | 30 min after the 2nd | backoff, bisect on the 2nd (today) | — |
| local semaphore not acquired within the timeout (free tier saturated by our own threads) | `overloaded` · `local_concurrency` | none | — | defer 2 min | — |
| `stop_reason: refusal` · Zhipu 1301 content safety · 百炼 `data_inspection_failed` · Ark `ContentFilter` · DeepSeek content filter 400 | `error` · `content_filter` | **never** | — | backoff → bisect → the single offending word dies (`on_dead`: `content_state='failed'` / lookup 「暂时无法校验」) | — |
| other HTTP 400 `invalid_request_error` not naming a field we control · 413 | `error` · `bad_request` | never | — | backoff/bisect | `ai_fallback_quality` only if 3 in a row on a fallback |
| 400 naming `output_config`/`output_format`/`tool_choice`/`tools`/`thinking` ("Extra inputs are not permitted", "not supported for this model", "only type=enabled is allowed") | (internal) | — | — | **one in-call downgrade** to the next strategy / thinking omitted; result recorded in `ai.<p>.caps_learned`; if the downgraded request also fails → that failure's row | event `ai_caps_learned {provider, feature}` once |
| `stop_reason: max_tokens` (never silently truncated) | `invalid_output` · `truncated` | never (quality streak) | fallback: 3 → 30-min quality pause | backoff/bisect (smaller groups fix it) | 「备用模型连续输出无效，已暂停 30 分钟」 |
| no `tool_use` and no JSON object in text · JSON parse failure after the repair round | `invalid_output` · `unparseable` | quality streak | as above | backoff/bisect | as above |
| jsonschema failure against the **original** schema after the repair round (incl. `difficulty: true`, string enums, nested arrays) | `invalid_output` · `schema` | quality streak | as above | backoff/bisect | as above |
| handler post-validation fails for **every** item (`content.py:440-444`, `lookup.py:570-574`) | `invalid_output` (re-classified) | quality streak | as above | today's path | as above |
| CLI `--max-budget-usd` stop (`budget` subtype) | `budget` · — | never | — | bisection (today) — the adapter never produces `budget` | — |
| `can_spend` refused by the Claude slot's daily/monthly cap | (no call) | only with `WD_AI_FAILOVER_ON_BUDGET_CAP=1` → run the group on the next slot whose `estimate` is 0 | — | defer to 00:05 / the 1st (today) | `budget_daily`/`budget_monthly` events (today) |
| `can_spend` refused by a provider's hourly cap (free provider: `WD_AI_<P>_HOURLY_CALL_CAP=60`, counts the probe and immediate retries) | (no call) | none (not a failure) | — | defer to the next hour + 1 min; other providers unaffected | — |
| success on any provider | `success` | resets that provider's streaks; success on `chain[0]` while failed over → fail back | — | — | `ai_failback` |
| recovery probe success / failure | `success` / its status | fail back / reschedule 30 min (60 after 6 h) | — | — | `ai_failback` / `ai_failover_probe` (once/30 min) |

**Budget and caps on a free provider:** `estimate(kind, words, provider)` = 0 when the slot's price table is `{}` → reservations do not consume Claude's daily/monthly caps, `cost_usd` = 0, `avg_cost_per_word_7d` averages only priced calls (query filtered to `cost_usd > 0`), prewarm `kv prewarm:<plan>:spent` stays 0 → plans end only on `limit`/`no_candidates` (size them by `limit`; contract:F12). The per-provider hourly cap is the real volume guard (60/h = 1,440/day ≫ the ≤10-friends load; the one-time prewarm at batch 5 is ≈1,824 calls → ≈30 h serialised on Zhipu, run it at night, zhipu:F14). A **paid** fallback (百炼) is priced per token in CNY→USD, so the daily/monthly caps bind normally (¥15/month ≈ $2.1 against the $40 cap).

**Concurrency / timeouts / batch:** Claude `WD_AI_CONCURRENCY` (1–3 threads, `main.py:391`) unchanged; zhipu semaphore 1, 百炼 3; timeouts content 180→270 s, lookup 120→180 s, consolidate 240→360 s, svg 120→180 s, probe 60→90 s on `timeout_scale 1.5`; batch 5 on zhipu (≈2k output tokens ≈ 20–25 s per call at 96–122 tok/s, zhipu:F4), 10 on 百炼; lookup groups stay 20; the immediate retry sends the *already claimed* group (≤12 words — within `content_v1.maxItems`).

**Provenance:** `ai_calls.provider` + `model_requested` (vendor id) + `model_used` (response `model`) + `session_id` (vendor request id); `word_contents.model` = `result.model_used or result.model_requested`; `jobs.result_json.provider`; `consolidation_runs.ai_call_id` already links the run to the row; events `ai_failover` / `ai_failback` / `ai_failover_probe` / `ai_provider_paused` / `ai_fallback_quality` / `ai_provider_override` / `ai_caps_learned` in `system_events` (free-text `kind`).

**Banner texts** (`failover.banner_zh`, surfaced in `AdminOverviewAi.banner_zh` and in the triggering event's `detail.banner_zh`): failover active → 「Claude 暂不可用，已自动切换到备用模型 {model}（自 {since} 起，每 {n} 分钟自动探测恢复）」; primary down and no fallback configured → today's 「Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录」; both down → 「AI 暂时不可用（主模型与备用模型均失败），任务已排队等待」; fallback quality pause → 「备用模型连续输出无效，已暂停 30 分钟」; override → 「管理员已手动指定模型来源：{provider}」; non-commercial preset active → 「当前备用服务（{provider}）仅限非商业用途」.

---

## 4. Rollout

### 4.1 Today (zero code, ≈3 h)

1. **Accounts.** Register on `open.bigmodel.cn` with the mainland phone, create a *standard* API key (not a Coding Plan key — 标准 API Key / 套餐 Key 互不通用, verify-zhipu:F6); keep it in a 0600 file. Optionally do 实名 now (ID + 支付宝 face, "即时完成") since recharging later needs it. Do **not** open 百炼 yet: its 90-day free-token clock starts at opening (verify-alibaba:F1) — open it the day the `bailian` slot is deployed.
2. **Decisive live tests (cost ¥0, from the Mac first, then the same four from the Tokyo VPS):**
   * T1 probe/tool: `POST https://open.bigmodel.cn/api/anthropic/v1/messages` with `Authorization: Bearer`, `anthropic-version: 2023-06-01`, body `{model:"glm-4.7-flash", max_tokens:512, thinking:{type:"disabled"}, system:<PROBE_SYSTEM_PROMPT>, messages:[{role:"user", content:<PROBE_PROMPT>}], tools:[{name:"submit_probe", input_schema:<probe_v1 + additionalProperties:false>}], tool_choice:{type:"tool", name:"submit_probe"}}` → expect 200, a `tool_use` block, `input == {"ok":true,"echo":"word-dance","level":2,"mode":"b","tags":["probe"]}`, `usage` present, `model` = `glm-4.7-flash`. Variants: `tool_choice:{type:"auto"}` + instruction; no tools + `output_config.format`; record which 400s. (Answers: free model on the Anthropic path? forced tool? output_config? — verify-others:Omission 6, verify-zhipu:Omission 4.)
   * T2 content: the real `content_system.txt` + `scratchpad/fallback/measure/content_user_prompt_cet4_top10.txt` with the `content_v1` tool, `max_tokens 8192` → record latency, `usage.output_tokens`, `stop_reason`, and run `content.validate_item` offline on the 10 items (the verifier ran it without a DB).
   * T3 the Zhipu error envelope with a bogus key and with `model:"glm-4.7-flash-x"` (1211) to pin the dialect strings.
   * T4 from the VPS: `curl -X POST …/v1/messages` with no key → expect the 401 JSON in <1 s (reachability of `open.bigmodel.cn` and `api.z.ai` from Tokyo; zhipu:F12 Q6).
   Go/no-go for the primary fallback: T1 exact match with `tool` or `tool_auto`; T2 ≥ 8/10 items pass `validate_item` with ≥3 examples each; latency < 90 s. NO-GO → the `bailian` slot becomes the first leg (T1/T2 repeated against 百炼 with `output_config`; ≈¥0.1 or inside the free grant).
3. **Optional emergency measure, not the plan:** the manual A0 wrapper (`bin/claude-fallback` exporting `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CONFIG_DIR=<empty dir>`, `ANTHROPIC_DEFAULT_*_MODEL=glm-4.7-flash`, `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `DISABLE_AUTOUPDATER=1`, `MAX_THINKING_TOKENS=0`) run as `WD_CLAUDE_BIN=<wrapper> WD_AI_MODEL=glm-4.7-flash wd claude-check` against a **scratch `WD_DATA_DIR`** (never the live one, never the real `claude` from this plan's author). It tells the owner whether the CLI path is blocked by `forceLoginMethod` (verify-contract:Omission 5) and what `total_cost_usd`/`modelUsage` say for an unknown id. It is *not* needed by this design (the HTTP adapter bypasses the CLI, its managed-settings fetch, its cost blindness and its `StructuredOutput` uncertainties), so skip it unless Claude is down again before week 1 ships.
4. **Regex patch (0.25 d, independent):** extend `AUTH_RE`/`OVERLOADED_RE` and add `REGION_RE`/`NETWORK_RE`/`BILLING_RE`/`USAGE_LIMIT_RE` (`runner.py:71-74`) so the current pause path at least recognises the region block and Chinese auth bodies.

### 4.2 This week (MVP, ≈10 person-days — section 7)

Rows marked ● in §2.10, shipped behind `WD_AI_CHAIN` (default `claude` = no behaviour change). Order: providers package + adapter + fake (with unit tests) → runner façade + config + migration → failover + common/budget/ledger + gates (integration test) → probe/diag/cli → admin API + minimal UI → deploy files + docs → smoke. Deploy with `WD_AI_CHAIN="claude,zhipu"`, zhipu batch 5, concurrency 1, svg excluded, `WD_AI_FAILOVER_ON_BUDGET_CAP=0`.

**Live tests with a real key, in this order (each ≤ 5 min):** `wd ai-check --provider zhipu` (1 probe call, ¥0) → three user lookups incl. `recieve`/`GDP` with `WD_AI_CHAIN="zhipu"` on the Mac dev instance (fake data dir) → one 10-word `regenerate` → one `consolidate <username>` → then the failover drill: `WD_CLAUDE_BIN=<fake_claude auth wrapper>` + `WD_AI_CHAIN="claude,zhipu"`, enqueue 5 content jobs, `wd worker-once`, assert the ledger shows one `auth` row (claude) followed by one `success` row (zhipu) and the `ai_failover` event; advance the clock → probe → `ai_failback`. Total cost ¥0 (Zhipu free) + ≤$0.05 if the real Claude probe is exercised.

### 4.3 Later (complete, ≈16 person-days cumulative)

* `scripts/eval_provider.py` + `scripts/mock_provider_server.py` — F17 adopted, with two changes: the harness calls the **real adapter** (`providers.anthropic_http`) so the request bytes are production bytes, and `--format openai` is dropped (no OpenAI adapter exists; `claude_cli` stays for parity runs). Flags/metrics/outputs as in contract:F17; `--paired` reuses the 48 Sonnet rows as the human-review baseline.
* **Go/no-go thresholds (promote a provider to the default fallback):** schema-valid ≥ 98 %, item pass (`validate_item`) ≥ 95 %, headword present in ≥ 97 % of examples, ≥ 3 examples in ≥ 95 % of items, p95 latency ≤ 0.6 × the kind's (scaled) timeout, truncation 0, lookup agreement ≥ 90 %, consolidate unknown-id rate ≤ 2 %, SVG sanitiser pass ≥ 90 % (else `svg` stays excluded). **Emergency-only bar** (keep in the chain but never first): schema-valid ≥ 95 %, item pass ≥ 85 %. Below that → remove the slot.
* Run the harness against: `zhipu glm-4.7-flash` (tool / tool_auto / text_json; thinking off vs on), `bailian qwen3.7-flash` (output_config; ¥≈0.1 or inside the grant), `zhipu glm-5.3-flash` (≈¥0.5), optionally `modelscope DeepSeek-V4.1-Flash` as the free quality reference (dev only, 2,000/day), and `siliconflow Qwen/Qwen3-8B` (free). ≈10 min and ≤ ¥1 per candidate.
* Add the `bailian` slot (开通 百炼 → 实名 → workspace key → `WD_AI_CHAIN="claude,zhipu,bailian"`, turn on 用完即停 per model you do not intend to pay for, verify-alibaba:Omission 4), the admin 「重新生成非 Claude 内容」 filter, `caps_learned` persistence, the Anthropic-proper preset verified against the mock (and, only if the owner later has a Console key, one `wd ai-check --provider anthropic` ≈ $0.01), Batch for prewarm as an option.

---

## 5. Risks (top 8) and mitigations

| # | risk | likelihood / impact | mitigation |
|---|---|---|---|
| 1 | `glm-4.7-flash` is not served on `/api/anthropic`, or it answers with text instead of `tool_use`, or `thinking:disabled` is ignored on that path — none is documented (verify-zhipu:Omission 4, verify-others:Omission 6) | medium / high (the free primary fallback would not exist) | day-1 test T1/T2 before any code; strategy ladder `tool → tool_auto → text_json` with the bounded in-call downgrade; `bailian` becomes the first leg on NO-GO; `zai` preset as the second host of the same model |
| 2 | Zhipu free tier: 1 in-flight request, peak-hour throttling, windowed caps (1302/1305/1308), platform incidents, no status page (verify-zhipu:F3, F14) | high / medium | semaphore 1, batch 5, `Retry-After`/`next_flush_time` honoured, soft-trigger switch to the next slot, nightly scheduling of prewarm/consolidate (02:30 local already), `bailian` as the third leg (30,000 RPM) |
| 3 | Vendor 400s on request fields (thinking types, `output_config`, forced `tool_choice`, `disable_parallel_tool_use`) and undocumented drift of "Anthropic-compatible" endpoints | high / low–medium | capability table + one in-call downgrade + `caps_learned`; the fake covers the 400 shapes; `wd ai-check --provider P --relearn` after vendor changes; the eval harness re-run quarterly |
| 4 | Lax pydantic mirrors coerce `difficulty: true → 1`, `"true" → True` (verify-contract:Omission 1) — wrong data stored silently once the CLI's own schema validation is gone | certain without the fix / medium | `validate_original` (jsonschema 4.26, now a runtime dependency) runs before `models.valid_items` in the adapter; the fake's `bool_difficulty` mode pins it |
| 5 | Quality gap vs Sonnet: headword missing from examples, CJK/length rules, weaker mnemonics → more `retry`/`invalid_output`, dead jobs, lower-quality cards (contract:F4) | medium / medium | `validate_item` unchanged; quality streak pause; eval go/no-go bars; `word_contents.model` provenance + the 「重新生成非 Claude 内容」 filter; step-up to 百炼/GLM-5.3-Flash by config |
| 6 | Failover flapping, ping-pong retries, or "both down" leaving jobs stuck | low / medium | sticky state, one immediate retry per claim, per-provider cooldowns, fail-back only via probe or a real primary success, `earliest_available_at` deferral and the both-down banner, admin override |
| 7 | Budget blindness: a free provider costs $0 so the daily cap no longer limits volume, prewarm's `$` stop never fires; a paid provider's CNY bill is invisible if the price table is wrong | medium / low–medium | per-provider hourly cap, `limit`-sized prewarm plans, `WD_AI_FAILOVER_ON_BUDGET_CAP=0`, CNY→USD pricing into `cost_usd` with the vendor balance kept small (≤¥100) as the hard stop, 用完即停 on 百炼 |
| 8 | Terms/data: BigModel may train on anonymised prompts (no opt-out); 百炼 Token/Coding plans are forbidden for backends and train; Ark is mainland-only; ModelScope is non-commercial; keys in `.env` | low / medium | prompts carry only words, dictionary hints and ≤120-char sanitised notes (never learner identity, contract:F5); `zai` preset for a no-training guarantee; pay-as-you-go only on 百炼; `ark` refuses to load without `WD_AI_ARK_ACK_TERMS`; `modelscope` flagged non-commercial in the admin tab; `is_secret()` masking, raw logs without headers, 0600 `.env` |

Also watched: (9) Zhipu retires GLM-4.7-Flash with auto-routing to a successor — pin the id in config, the probe's `model_seen` reveals the reroute; (10) the Tokyo→Beijing path degrades — probe latency is in the ledger, `bailian` has a Tokyo host; (11) `WD_AI_FALLBACK_MODEL` rename breaks an existing `.env` — the old name is accepted with a warning for one release.

---

## 6. Decisions only the owner can make (with the default this design assumes)

| # | decision | default |
|---|---|---|
| D1 | BigModel (`open.bigmodel.cn`, 支付宝/微信, mainland latency, anonymised training allowed) vs Z.ai (`api.z.ai`, Singapore entity, no-training terms, card/PayPal without 3DS) for the same GLM-4.7-Flash | **BigModel**; switch = `WD_AI_ZHIPU_PRESET=zai` + its key |
| D2 | Step-up vendor: 百炼 `qwen3.7-flash` (new account, 实名, ¥15/month, strict schema, platform diversity) vs `glm-5.3-flash` on the Zhipu key (¥29–58, no new account, thinking forced) vs DeepSeek `deepseek-flash` (¥54–108, outage record) | **百炼 qwen3.7-flash** as a third slot |
| D3 | Chain order and automation: `claude,zhipu` (week 1) → `claude,zhipu,bailian`; or `claude,bailian,zhipu` (paid first for quality) | free first (`claude,zhipu,bailian`) |
| D4 | `WD_AI_FAILOVER_ON_BUDGET_CAP`: should Claude's daily/monthly cap degrade to the free provider instead of stopping? It changes the caps from "stop" to "degrade" | **0** (unchanged semantics) |
| D5 | Content generated by the fallback: keep forever; keep but regenerate with Claude when it returns (≈$0.005/word); show a per-card model label (the curation plan's per-block chip) | **keep**, regenerate on demand via the admin filter, no extra learner-facing label beyond today's 「例句…由 AI 生成」 note |
| D6 | Route `generate_svg` to the fallback (sanitiser protects; quality unknown) | **off** until the eval shows ≥ 90 % sanitiser pass |
| D7 | Fail-back granularity: first successful probe/primary call (one flip) vs N successes | **first success** |
| D8 | Probe cadence 30 min fixed (≤ $0.01/h on Claude) vs F11's doubling to 4 h | **30 min, 60 after 6 h** |
| D9 | 实名 timing: Zhipu now (needed to recharge, and FAQ says API 实名 is "目前" not required) and 百炼 at slot creation | **yes** |
| D10 | Migration numbering: `0010_ai_provider.sql` now, curation plan renumbers to 0011 | **yes** |
| D11 | Manual admin pause = global (`kv.ai.paused_until`) vs primary-only | **global** |
| D12 | Where the vendor key lives: `.env` (masked by `is_secret`) vs a separate 0600 file read at startup | **`.env`** |
| D13 | Whether to run the optional A0 CLI-wrapper probe today (answers the `forceLoginMethod` / unknown-model-cost questions; not needed by this design) | **skip** unless Claude is down before the MVP ships |

---

## 7. Effort summary (person-days; one person-day = 8 focused hours)

| phase | scope | days |
|---|---|---|
| Day 0 | accounts, four live tests, regex patch | 0.5 |
| **MVP** | providers package (`__init__`/`base`/`claude_cli`/`anthropic_http`/`schema_transform`/`pricing`/`errors`) 2.9 d · runner façade + interfaces + config + migration 1.0 d · failover + common/budget/ledger + gates + queue/worker 2.0 d · probe/diag/cli 0.4 d · admin API/schemas/types + minimal UI 1.1 d · `fake_anthropic` + tests 2.0 d · deploy/env/dev/smoke + docs 0.75 d · live tests and tuning 0.5 d | **≈ 10 (9–11)** |
| **Complete** | + eval harness and mock server 1.5 d · N-chain polish, `caps_learned`, override UI 0.5 d · regenerate filter + fallback-share tile 0.5 d · Anthropic-proper verification against the mock + optional Batch prewarm 1.0 d · 百炼 slot rollout and scorecards 0.5 d · runbooks/service comments 0.25 d · contingency for vendor surprises 1.5 d | **≈ 16 cumulative** |

For comparison, contract:F8/F9 estimated B (OpenAI adapter + failover + admin + tests) at 8–10 d and C at +2–3 d on top of B; building C *instead of* B lands at ≈10 d — inside that band — because the per-vendor capability work replaces the OpenAI dialect work (the ● rows of §2.10 sum to ≈86 h).

---

## 8. Deviations from the fact-base recommendations (deliberate)

1. **Anthropic-format adapter first, no OpenAI adapter** (contract:R3/R4 said "B then C"; alibaba:R2 and zhipu:R2 proposed OpenAI-compatible shims). Reason: the orientation — one adapter, one double, one ledger model for domestic vendors and a future Console key; the only real loss is Zhipu's documented `json_object` mode (§1.4), mitigated by the strategy ladder and measured on day 1.
2. **Ordered chain of named slots (`WD_AI_CHAIN`, `WD_AI_<SLOT>_*`, presets)** instead of F11's `WD_AI_PROVIDER=claude|fallback|auto` + one `WD_AI_FALLBACK_*` block. Reason: the step-up and a later Console key are additional slots, not redeploys; the state machine is the same.
3. **Recovery probe every 30 min fixed (60 min after 6 h)** instead of doubling to a 4-h cap (contract:F11). Reason: in the real outage doubling would have failed back at ≈06:15Z instead of ≈03:15Z for a saving of a few cents.
4. **Network errors classify as `overloaded/network`** (defer path) rather than `error` with a separate 2-min defer (contract:F11). Reason: identical job action, one code path, and `ledger.STATUSES` cannot grow.
5. **`failover.record_failure` is the single writer** of pauses, streaks and events; `handle_failure` only moves jobs (today it writes pauses itself, `common.py:264-279`). Reason: the immediate retry means the last result may belong to a different provider than the one that triggered the switch.
6. **Primary fallback = GLM-4.7-Flash** (agrees with others:R1 and zhipu); **step-up = 百炼 qwen3.7-flash** (alibaba:R1 wanted it as fallback #1; bytedance-deepseek:R1 wanted DeepSeek-flash #1). Reason: the owner asked for the best *free* model first; 百炼 is the cheapest reliable paid leg; DeepSeek's 2026 outage record and no free tier put it third.
7. **New `ClaudeResult` fields** (`provider`, `model_requested`, `reason`) and a `Parsed.reason` — F11 proposed reading everything from status + regex classes; the fine-grained reason is what lets `budget` keep meaning "CLI budget stop" and billing/quota cases pause for the right horizon.
8. **Raw `httpx` instead of the `anthropic` Python SDK** for the adapter (the claude-api skill's default is the SDK). Reason: the same request builder must emit vendor-specific fields (`output_format`, numeric Zhipu error types, Bearer vs x-api-key) and avoid SDK-added headers/betas that vendors reject; the Anthropic-proper preset can be swapped to the SDK later without touching the failover.
9. **`jsonschema` becomes a runtime dependency** and runs before the pydantic mirrors (contract:F17 had it only in the harness). Reason: verify-contract:Omission 1.
10. **Migration `0010_ai_provider.sql` now; the curation plan's `0010_curation_columns.sql` becomes 0011** without its `ai_calls.provider` line.
11. **Manual admin pause moves to a global key** (`kv.ai.paused_until`); `claude.paused_until` becomes the Claude provider's automatic pause (F11 proposed the same split; the route change is spelled out here).
12. **The eval harness calls the real adapter and drops `--format openai`** (contract:F17 had its own per-format `call()`).
13. **A0 (CLI wrapper pointed at a gateway) is optional and not on the critical path** (contract:R1 recommended it for today). Reason: the HTTP adapter removes every CLI-side uncertainty the wrapper would have had to test; the owner can still run it to answer the `forceLoginMethod` question.
14. **Repair round and in-call capability downgrade** are bounded to one each (F8 proposed one repair; the downgrade is new). Reason: free tiers have latency to spare but the queue, not the adapter, owns retries.
