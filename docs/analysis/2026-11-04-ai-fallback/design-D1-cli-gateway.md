# Design D1 — CLI gateway failover: keep `claude -p` as the only transport, reach a domestic model through a second wrapper, fail over automatically

Date 2026-11-04 · Repo `/Users/sqin/word-dance` @ 9ab13a5 (read-only; nothing modified) · Fact base: `scratchpad/fallback/facts/*.md` + `scratchpad/fallback/verify/*.md` (verifications override digests; cited as `(slice:Fn)` / `(verify-slice:Fn)` / `file:line`).

Owner question (binding): 「如果 Claude 无法使用，评估匹配国内最优的免费模型做一个备选；当 Claude 不成功，直接用备选方案」. Anthropic policy/licensing is out of scope by the owner's instruction; the one documentation sentence that matters is *reported* in §2.6 and not analysed.

Orientation taken: the smallest change that is still automatic. The existing runner (`backend/wd/ai/runner.py:383-495`) stays the only transport. The fallback model is reached through a **second wrapper script** that exports `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` + the model-slot variables + the structured-output / thinking / traffic switches, under a **separate, login-free `CLAUDE_CONFIG_DIR`**. Two shapes: **A0** (manual switch, zero code, usable today) and **A1** (provider slots + the contract §F11 state machine inside `runner`/`common`/`budget`, so failover and fail-back are automatic). Everything below the CLI stays byte-identical, so `tests/fake_claude.py` keeps covering both slots.

---

## 0. Pitch

**After day 1 (no code, ≈1–2 h plus account sign-up, ≈¥0 spent):** a BigModel account with a standard API key (phone number only; 实名 is needed only to recharge — zhipu:F9), a `$WD_DATA_DIR/bin/claude-fallback` wrapper (§2.2) and a scratch-data-dir `wd claude-check` that proves whether the installed `claude` 2.1.292 can talk to `https://open.bigmodel.cn/api/anthropic` at all. The probe's exact-match answer is the go/no-go for enum/array handling; its raw log answers the four open questions nobody could verify without a key (managed-settings fetch, `structured_output` presence, `modelUsage`/`total_cost_usd` for an unknown id, whether `CLAUDE_CODE_EXTRA_BODY` turns thinking off). If Claude dies before the code lands, the owner flips four `.env` lines (§4.1) and restarts — a 2-minute manual failover instead of today's "pause 30 min, retry, pause again" loop that ran for 6+ hours on 2026-11-02/03 (contract:F16, verify-contract:F11).

**After week 1 (A1 MVP, ≈5.5 person-days):** `WD_AI_PROVIDER=auto`. When a Claude call fails with a hard trigger (auth — including the managed-settings string of the live outage — spawn error, 403/region, billing/usage-limit strings) the *same claimed job group* is re-run on the fallback immediately, the primary is paused 30 min, every later claim goes to the fallback (batch 5, concurrency 1, timeouts ×1.5), the housekeeping loop re-probes Claude every 30 min (doubling to 2 h) and flips back on the first success. Soft failures (2 timeouts, 3 overloaded/network in a row) switch too. Learners never see `503 ai_disabled` while any provider is healthy; the admin sees a banner, a 来源 column in the ledger and an `ai_failover` / `ai_failback` event pair. Fallback calls are priced in CNY from the envelope's token counts (the CLI's USD estimate is 0/unknown for foreign ids), provenance is recorded per call (`ai_calls.provider`, migration 0010) and per card (`word_contents.model` = the vendor id).

**After week 3 (complete, ≈9.5 person-days cumulative):** admin segmented control (Claude / 备用 / 自动), health card for the fallback, per-provider hourly cap and price table, fallback quality pause (3 consecutive invalid outputs), `wd ai-check --provider fallback` in `install.sh`, the eval harness run with `--paired` against the 48 Sonnet rows so the owner knows the free model's item pass rate before trusting it with learner-facing content, an admin filter to regenerate non-Claude cards when Claude is back, and the smoke test exercising the switch with two fake wrappers. The paid step-up (百炼 `qwen3.7-flash`, ≈¥15/month) is a second wrapper file and three `.env` lines away.

**Kill criterion for D1 (decided in the first 10 minutes of day 1):** if `wd claude-check` under the fallback wrapper fails with "Your organization requires remote managed settings to load" or "This machine's managed settings require a first-party login" even with an empty `CLAUDE_CONFIG_DIR` and `ANTHROPIC_AUTH_TOKEN` set, the CLI-as-gateway route is blocked by the Enterprise profile (`forceLoginMethod`/`forceLoginOrgUUID` "cannot coexist" with a token — verify-contract omission 5) and the fallback must be an HTTP adapter (design D2); nothing in A1 is wasted except the wrapper.

---

## 1. Fallback model choice

### 1.1 Ranked table (workload: ≈2k input + ≈4k output tokens per 10-word content call, 25–100 content calls/day, ≤10 consolidations, ≤40 SVG, 150 lookups/month; prices CNY per 1M tokens as read 2026-11-04)

| # | Model | Provider · endpoint the wrapper uses | Cost / month at the workload | Free-tier limits | Structured-output mode D1 uses | Context / max out | Endpoint format | Terms / data policy | Overseas access (Tokyo VPS) | Quality evidence | Stability |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **1 (primary fallback)** | **GLM-4.7-Flash** (`glm-4.7-flash`, 30B-A3B MoE) | Zhipu BigModel, `https://open.bigmodel.cn/api/anthropic` (mainland key) — region alternative Z.ai `https://api.z.ai/api/anthropic` | **¥0** (`免费/免费` on the price list; zhipu:F1, verify-zhipu:F1) | No token cap; per-account **concurrency** limit (console-only; third parties report 1 in-flight request, peak throttling); windowed caps surface as code 1308/HTTP 429; 1302/1305 = account/platform 429 (zhipu:F3, verify-zhipu:F3, omission 2) | Claude Code's injected `StructuredOutput` tool call (unforced) with `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1`; Zhipu's own API offers only `json_object` and `tool_choice=auto` (zhipu:F5) — exactly what the CLI's tool path needs | 200K / 128K out — the worst-case consolidate (≈17k prompt tokens, contract:F3) fits | Anthropic Messages with `tools`, `thinking` (GLM-4.7 series: togglable, default ON); "某些场景下…仍存在差异" (zhipu:F6) | Standard API; integrating into your own product for your end users is explicitly not resale (§3.7(7)); commercial use of *free* output is a grey zone, invite-only non-commercial use is fine; **BigModel privacy allows anonymised training with no API opt-out**; Z.ai promises no training / no storage (zhipu:F10, F11) | Reachable from a US egress (HTTP 401 in 1.3 s), Alibaba Global Accelerator anycast, no geo-fencing documented; terms contemplate overseas use (zhipu:F12, verify-zhipu:F12) | BFCL v3 74.6, τ²-Bench 79.5, IFBench 60.8; **no LMArena-zh / SuperCLUE entry; nothing published on zh explanatory writing** (zhipu:F13, others:F15) — the eval harness decides | Weakest point: documented platform-level throttling, a multi-day 429 incident (Coding Plan, June 2026), nightly gateway failures on a free quota (Nov 2026), no status page (verify-zhipu:F14) |
| **2 (paid step-up)** | **qwen3.7-flash** (`qwen3.7-flash`) | 阿里云百炼 pay-as-you-go, `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/apps/anthropic` (the legacy `dashscope.aliyuncs.com` host is feature-frozen since 2026-09-30 — verify-alibaba:F4) | **≈¥15/month** at 100 content calls/day **only with thinking disabled** (default ON, billed as output — verify-alibaba:F3/F11); first 1M tokens per model free for 90 days (≈167 content calls) | 30,000 RPM / 5,000,000 TPM (alibaba:F5); 实名 mandatory to open 百炼 | Same `StructuredOutput` tool path. (百炼's strict `output_config.format` exists but requires `additionalProperties:false`, which the on-disk schemas lack and tests forbid adding — alibaba:F4, contract:F18) | 1M / 131K out | Anthropic Messages incl. `output_config` (format/effort), `thinking enabled|disabled`, `tool_choice` auto/any/none/tool; no `/v1/models` (404, tolerated) | Pay-as-you-go inputs **not trained on** (服务协议 §6.2.5); Token Plan / Coding Plan forbid backend use and authorise training → never (alibaba:F7) | Beijing endpoint answers from a US egress (401 — reachable); regions siloed; a Tokyo region exists at Beijing prices under 全球 deployment but without free quota and 中国站 eligibility unverified (alibaba:F6) | No public LMArena/SuperCLUE score for 3.7-flash; sibling qwen3.8-flash 66.4 on a third-party SuperCLUE compilation (weak evidence — verify-alibaba omission 5) | Production-grade: no 2026 outage found, 3-month retirement notice for main-line models (alibaba:F12) |
| 3 | deepseek-flash (V4.1-Flash-1017) | DeepSeek `https://api.deepseek.com/anthropic` | ¥54 off-peak / ¥108 peak **plus reasoning tokens** (thinking default ON, effort high, no CLI lever — verify-bd omission 1) | none (no free tier, no sign-up credit) | `StructuredOutput` tool, necessarily unforced (forced `tool_choice` 400s in thinking mode — verify-bd:F4); `output_config.format` ignored | 1M / 384K | Anthropic Messages | Trains on inputs by default with opt-out (second-hand); single global platform, PayPal/cards (bd:F3, F5) | Best for an overseas server (global platform) | LMArena-zh 1523 (#30) (alibaba:F10) | 19 major outages in 2026 incl. 2026-11-03 (bd:F19) |
| 4 | GLM-5.3-Flash | Zhipu, same endpoint and key as #1 | ¥29–58 (+ forced thinking ×≈2) (zhipu:F16) | paid | `StructuredOutput` tool | 1M / 128K | as #1 | as #1 | as #1 | LMArena-zh 1530 (#20) — the best "Flash" on the Chinese board | as #1 |
| 5 | Doubao-Seed-2.1-lite | Volcengine Ark `https://ark.cn-beijing.volces.com/api/compatible` | ¥37 | one-time activity quota (unverified amount) | tool or `output_format json_schema` | 1M / 256K (default 4K; the CLI sends 32000) | Anthropic-compatible Messages | No training by default, **but the licence is "仅在中国大陆地区使用"** and any "直接或间接获得收益" needs written permission (verify-bd:F10) → excluded while the server is in Tokyo | contractually out | SuperCLUE 2.1-pro 65.95 | app-level outages only |
| 6 | Qwen3-8B | SiliconFlow `https://api.siliconflow.cn` (Anthropic path `/v1/messages`) | ¥0 | fixed per-model RPM/TPM (console), 实名 unlocks all free models | tool (an 8B model emitting a 10-item nested `tool_use` is the documented failure mode — others:F9) | 32K-class | Anthropic Messages (`/v1/messages`) | No training, no long-term storage (others:F4) | not tested | IFEval 83–85, BFCL 60–68 (others:F15) | 429 when throttled | 
| 7 | DeepSeek-V4.1-Flash / GLM-5.2 / Qwen3.5-397B | ModelScope API-Inference `https://api-inference.modelscope.cn` (Beta `/v1/messages`) | ¥0 | 2,000 calls/day/account, ≈200/day per model, concurrency 1, reset 00:00 UTC+8; Alibaba Cloud binding + 实名 | tool (Beta endpoint; `tools` support unverified) | 1M-class | OpenAI + Beta Anthropic | **officially 非商业化、非盈利**, quota cuts and model churn without notice (alibaba:F8, F9) | `.cn` loaded from a US egress | LMArena-zh 1523 / 1525 / 1496 — the strongest free engines by far | best-effort sandbox |
| — | Baidu ERNIE free tier · Tencent hunyuan-lite · iFlytek Spark Lite · Kimi K3.1 Pro · MiniMax | — | retired 2026-06 · retired 2026-06-22 · 8K/4K, QPS≈2, no tool calling · ≈¥894/month · no JSON mode on current models, `X-Api-Key`, forced thinking (others:F1–F3, bd:F11, F15, F17) | | | | | | | | not viable |

### 1.2 Choice and reasons

**Primary fallback = Zhipu GLM-4.7-Flash on `open.bigmodel.cn/api/anthropic`.** It is the only model that satisfies all four hard constraints at once: (a) permanently free in the sense that matters (no token cap, no trial period, replaced roughly yearly with automatic routing — zhipu:F2); (b) commercially usable under a standard API key (no Coding Plan trick, no "non-commercial sandbox"); (c) reachable in Anthropic Messages format **with client tools**, which is what Claude Code's `--json-schema` actually requires (others:F9, verify-zhipu:F7); (d) 200K context, so the nightly consolidate never needs a second model. It costs nothing to keep configured, so it can be the always-on safety net even if the owner later prefers the step-up for quality.

Its two real weaknesses are handled by design rather than by model choice: concurrency ≈1 and peak throttling → `WD_AI_FALLBACK_CONCURRENCY=1`, batch 5, 429/1302/1305/1308 treated as *defer* with the existing streak logic (§3); unknown quality on zh explanatory writing → the eval harness gate (§4.3) before `generate_content` is allowed on it; lookups and consolidation (short, structured, schema-checked) are allowed from day one.

**Step-up = 百炼 `qwen3.7-flash` (pay-as-you-go, workspace host).** At ≈¥0.0036 per content call it is cheaper than one Claude Sonnet *hour* per month, its inputs are not trained on, its rate limits are 500× the app's need, and it sits on the same Anthropic-format transport, so switching is one wrapper file plus `WD_AI_FALLBACK_MODEL`. The condition is that thinking is really off (default ON, billed as output): the step-up's go/no-go is the measured `usage.output_tokens ≈ visible JSON` in test T2 (§4.1). If the CLI cannot switch thinking off on this endpoint, the step-up becomes GLM-5.3-Flash on the *same Zhipu key* (¥29–58 + thinking, no second account) — see decision D3.

**DeepSeek-flash is third, not first** (deviating from the bytedance digest's R1): on the CLI route its thinking cannot be switched off (cost ×?), forced tool choice is unavailable in thinking mode, it trains on inputs by default, and it had its 19th outage of the year the day before this design. It becomes the better step-up only if hosting stays overseas permanently and the owner does not want an Alibaba Cloud account (decision D3).

**What is deliberately *not* in the automatic chain:** ModelScope (strongest free engines, but 非商业化/非盈利 terms, model churn and ≈200/day caps make it a dev/test sandbox — decision D7), SiliconFlow Qwen3-8B (7–9B models fail the 10-item nested tool call too often; kept as a documented *manual* emergency wrapper only), Ark (mainland-only licence while on a Tokyo VPS), Kimi (cost), MiniMax (no JSON mode, forced thinking).

### 1.3 Which job kinds go to which model

One model per slot (the CLI resolves the `sonnet` alias through the wrapper's `ANTHROPIC_DEFAULT_SONNET_MODEL`; a per-kind model override is a "later" item). Routing is therefore an **allow-list of kinds** per slot:

| Kind | Primary (Claude) | Fallback slot default (`WD_AI_FALLBACK_KINDS`) | Why |
|---|---|---|---|
| `lookup_word` (20 strings, ≈4 KB prompt, 2.6–3.2k out) | yes | **yes from day 1** | short, 13 required keys, `apply_item` validates everything (headword relatedness, CJK, enums); a wrong answer becomes a `fix_spelling` suggestion, not a stored error (contract:F4) |
| `consolidate_bank` (typical 5 KB, worst 56.5 KB ≈17k tokens) | yes | **yes from day 1** | needs ≥32K context (GLM-4.7-Flash 200K ✓); unknown ids ignored, targets re-validated, note ≤40 chars — low blast radius |
| `generate_content` (10 words, ≈3.8k out) | yes | **yes after the eval gate** (§4.3); until then `WD_AI_FALLBACK_KINDS=lookup,consolidate` | the headword-in-example rule and zh naturalness are where a 30B model is most likely to lose items; `validate_item` + bisect protect correctness, the eval protects quality |
| `generate_svg` | yes | **no (opt-in later)** | sanitiser rejects a bad SVG permanently (`image_state='failed'`, never retried — contract:F4); a weak model burns the photo fallback. Photos keep working without AI |
| `probe` | yes | yes (the fallback's own availability probe) | `probe_v1` exact match is the cheapest capability test |

While the fallback is active, kinds not in the allow-list simply defer until a provider that accepts them is available (same `queue.defer` path as a budget refusal), so nothing is lost — SVG cards are generated when Claude returns.

---

## 2. Architecture

### 2.1 Request/response flow for a Claude failure (A1, `WD_AI_PROVIDER=auto`)

```
worker.process_next ──► queue.claim_batch(limit_for(type, cfg, provider=failover.active(conn)))     # batch 10 on claude, 5 on fallback
      │
      ▼
handler (content/lookup/consolidate/svg) ──► common.claude_call(ctx, conn, kind=…, jobs=…)
      │
      ├─ 1. provider = failover.select(conn, cfg, kind, now)          # §2.1.1 selection rules; None ⇒ defer to earliest resume
      ├─ 2. budget.reserve(…, provider=provider)                       # kill switch → provider pause → provider hourly cap → USD caps (est 0 for a free slot)
      ├─ 3. runner.run_claude(…, slot=slots[provider])                  # argv: slot.bin, --model slot.model, no --fallback-model; env unchanged (the wrapper adds the rest)
      │        └─ parse_and_classify (+ new regexes) → ledger.finish_call(provider=…, cost from price table)
      ├─ 4. failover.record(conn, cfg, provider, result, now)           # streaks, hard/soft triggers, switch decision
      └─ 5. if result failed AND record() switched to the other provider AND that provider accepts `kind`:
                 ONE immediate retry of the same still-claimed group: back to step 2 with the new provider
                 (the first ledger row is finished as auth/…, the retry has its own row; jobs keep attempts unchanged)
      ▼
handler: result.ok → apply items (model = result.model_requested when provider != 'claude')
         result failed → common.handle_failure(ctx, conn, jobs, result)   # §6.3 table, pauses now provider-scoped
```

**2.1.1 Selection rules (`failover.select`)** — evaluated per call, state in `kv`:
1. `WD_AI_PROVIDER=claude` → `claude` only (today's behaviour, default). `fallback` → fallback only (manual A0-equivalent without editing `WD_CLAUDE_BIN`). `auto` → continue.
2. `kv.ai.provider_override` (admin segmented control) wins while set.
3. `active = kv.ai.active_provider` (default `claude`). If `active` is not paused and accepts `kind` → `active`.
4. Else if the *other* provider is configured, not paused and accepts `kind` → the other one. If the other is `fallback` this is a failover (record `ai.active_provider=fallback`, `ai.failover.*`, schedule the probe, emit `ai_failover`); if the other is `claude` while the fallback is paused, it is an opportunistic fail-back attempt: success flips `active=claude` (`ai_failback`), a hard failure re-pauses the primary with the cooldown doubled (§3).
5. Else → `None`: the caller defers the group to `min(primary.paused_until, fallback.paused_until)` exactly as today's refusal path (`common.py:166-170`).

Sticky, not per-call: one flip per outage, so latency never doubles on every failure and the ledger stays readable (contract:F11 argues the same).

**2.1.2 What the fallback spawn looks like.** `build_argv(cfg, tier, …, slot)` emits `[slot.bin, "-p", prompt, "--output-format", "json", "--json-schema", …, "--tools", "", "--no-session-persistence", "--model", slot.model, ("--max-budget-usd", …  unless slot.budget_flag is off)]` + tier-1 flags + `WD_AI_EXTRA_ARGS`; `--fallback-model` is never appended for the fallback slot (`runner.py:145-146`). `claude_env` is unchanged (`runner.py:158-174`): HOME/PATH/LANG/TZ plus the allow-list; the parent process carries **no** `ANTHROPIC_*` variables, so the primary spawn can never inherit the fallback key. Everything provider-specific lives in the wrapper file (§2.2), which is the one place the key is read.

### 2.2 The wrappers

**Primary (unchanged):** `~/word-dance-data/bin/claude-wrapper` (macOS: USER/LOGNAME/TMPDIR + privoxy proxy for api.anthropic.com; on the Tokyo VPS a plain `exec /home/sqin/.local/bin/claude "$@"`).

**Fallback wrapper `$WD_DATA_DIR/bin/claude-fallback`** (A0 and A1 use the same file; installed from `deploy/claude-fallback.sh.example`, mode 0700, owned by the service user):

```sh
#!/bin/sh
# claude-fallback — word-Dance: the same `claude` binary pointed at a domestic Anthropic-format endpoint.
# Referenced by WD_AI_FALLBACK_BIN (A1) or, for a manual switch, by WD_CLAUDE_BIN (A0). Never put the key in .env:
# the runner forwards ANTHROPIC_* from the parent environment (runner.py:54-56) and the primary spawn must not see it.
set -eu
DATA="${WD_FALLBACK_DATA_DIR:-/home/sqin/word-dance-data}"
REAL_CLAUDE="${WD_FALLBACK_REAL_CLAUDE:-/home/sqin/.local/bin/claude}"      # macOS: /opt/homebrew/bin/claude
MODEL="${WD_FALLBACK_MODEL:-glm-4.7-flash}"                                  # vendor id; must equal WD_AI_FALLBACK_MODEL in .env
export ANTHROPIC_BASE_URL="${WD_FALLBACK_BASE_URL:-https://open.bigmodel.cn/api/anthropic}"
export ANTHROPIC_AUTH_TOKEN="$(cat "$DATA/secrets/fallback.key")"             # 0600; Bearer form is what Zhipu/百炼/DeepSeek document
unset ANTHROPIC_API_KEY                                                      # one credential header only
export CLAUDE_CONFIG_DIR="$DATA/claude-fallback-config"                       # empty, login-free: no Enterprise profile → no remote managed-settings fetch
export ANTHROPIC_DEFAULT_SONNET_MODEL="$MODEL" ANTHROPIC_DEFAULT_OPUS_MODEL="$MODEL" ANTHROPIC_DEFAULT_HAIKU_MODEL="$MODEL"
export CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1    # drop output_config.format + its beta header (CLI >= 2.1.288); the StructuredOutput tool path remains
export MAX_THINKING_TOKENS=0                       # third-party upstream: omits the thinking field (vendor default then applies)
export CLAUDE_CODE_EXTRA_BODY='{"thinking":{"type":"disabled"}}'   # tested in T2; remove if the vendor 400s on it
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000 CLAUDE_CODE_MAX_CONTEXT_TOKENS="${WD_FALLBACK_CONTEXT_TOKENS:-200000}"
export API_TIMEOUT_MS=600000
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
export DISABLE_FEEDBACK_COMMAND=1 CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 CLAUDE_CODE_ATTRIBUTION_HEADER=0
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy                          # open.bigmodel.cn is reached directly (the privoxy tunnel is for anthropic.com only)
export USER="${USER:-$(id -un)}" LOGNAME="${LOGNAME:-$USER}" TMPDIR="${TMPDIR:-/tmp/}"   # macOS login-session vars (memory note)
exec "$REAL_CLAUDE" "$@"
```

Notes: (i) `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` is the documented second lever if `Extra inputs are not permitted` 400s persist (removes the format and task-budget fields but not effort — verify-others:F9); (ii) the `[1m]` suffix on the model id is *not* used (the CLI drops it when resolving, and `CLAUDE_CODE_MAX_CONTEXT_TOKENS` does the same job explicitly); (iii) `--tools ""` and the tier-1 flags come from the runner's argv, so the prompt-injection posture (contract:F5) is unchanged on the fallback; (iv) for the 百炼 step-up only three lines differ: `WD_FALLBACK_BASE_URL=https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic`, `WD_FALLBACK_MODEL=qwen3.7-flash`, `WD_FALLBACK_CONTEXT_TOKENS=1000000`, plus the key file; (v) a `claude-emergency-siliconflow` variant (`ANTHROPIC_BASE_URL=https://api.siliconflow.cn`, model `Qwen/Qwen3-8B`) can be kept on disk for a manual A0 switch but is never a slot.

### 2.3 File-level change list (A1; hours are solo-developer estimates incl. local test runs; M = MVP, C = complete)

| File | Function / area | Change | h |
|---|---|---|---|
| `backend/wd/ai/runner.py` | new `Slot` dataclass (`provider, bin, model, batch_size, concurrency, timeout_scale, budget_flag, kinds, price`) + `slots(cfg) -> dict[str, Slot]`; `build_argv(cfg, tier, …, slot=None)` (`slot.bin`, `--model slot.model`, `--max-budget-usd` only when `slot.budget_flag`, `--fallback-model` only for the primary — `runner.py:124-149`); `run_claude(…, provider="claude")` picks the slot, passes `provider`/`model_requested` to `ledger.insert_call`/`finish_call`, returns them on `ClaudeResult`; cost: `parsed.cost_usd = pricing(slot, parsed.tokens)` when `slot.price` is non-empty, else the envelope's `total_cost_usd` (primary) or 0; regexes: `AUTH_RE` += `\b402\b\|insufficient balance\|余额不足\|欠费\|令牌已过期\|token expired\|身份验证失败\|token is invalid\|invalid api-?key\|invalid access token\|usage limit\|plan limit\|enforced_spend_limit_reached\|credit balance\|remote managed settings\|first-party login`; new `REGION_RE = \b403\b\|forbidden\|request not allowed` (→ `auth` class); `OVERLOADED_RE` += `\b429\b\|quota exceeded\|allocationquota\|throttling\|访问量过大\|速率限制\|server busy`; new `NETWORK_RE = ENOTFOUND\|ECONNREFUSED\|ECONNRESET\|ETIMEDOUT\|EAI_AGAIN\|unable to connect\|can't reach the API\|connection refused\|fetch failed\|socket hang up\|malformed response \(HTTP 200\)\|certificate` (→ status `overloaded`, `error` text prefixed `network: ` so the failover keeps a separate streak — `ledger.STATUSES` is a fixed CHECK, contract:F18); subtype `error_max_structured_output_retries` → `invalid_output` (both providers; it *is* invalid output); `log.extra["provider"]` | 6 (M) |
| `backend/wd/ai/failover.py` (new, ≈300 lines) | `KEYS` (§2.5), `active(conn)`, `select(conn, cfg, kind, now) -> str \| None` (§2.1.1), `record(conn, cfg, provider, result, now) -> Decision` (streak bookkeeping, hard/soft triggers, switch + `ai_failover` event, cooldown doubling), `maybe_probe(conn, cfg, now)` (called from housekeeping; runs `probe.check(conn, cfg)` against the primary when `active == fallback and now >= next_probe_at`; success → `active=claude`, clear `claude.paused_until`, `ai_failback` event; failure → interval ×2 up to `WD_AI_FAILOVER_PROBE_MAX_MIN`), `any_provider_available(conn, cfg, now) -> str \| None` (earliest instant some provider is usable), `banner_zh(conn, cfg, now)` | 8 (M) |
| `backend/wd/ai/common.py` | `claude_call`: `provider = failover.select(...)` before `budget.reserve(..., provider=provider)`; after `run_claude`, `decision = failover.record(...)`; on `decision.switched_to` and the new provider accepting `kind`: re-reserve + re-run the same group once (attempts untouched; the deferred-refusal path unchanged); `handle_failure`: pauses become `budget.set_paused_until(conn, until, provider=result.provider)`, overload streak key per provider, `claude_auth` event only for the primary (fallback gets `ai_fallback_auth`); `record_success(conn, provider)`; `AUTH_BANNER_ZH` kept as the "primary down, no fallback" text, `banner_zh()` added (texts in §3.5) | 4 (M) |
| `backend/wd/ai/budget.py` | `paused_until(conn, now, provider=None)`: with `provider` → that slot's pause; with `None` → the **global** answer used by every UI gate = `max(ai.paused_until, min over configured providers)` (so the 12 existing readers keep their call shape but mean "no provider available"); `set_paused_until(conn, until, provider="claude")` (key `claude.paused_until` for the primary — unchanged key, `ai.fallback.paused_until` for the fallback); `can_spend(..., provider)` / `reserve(..., provider)`: kill switch → provider pause → `calls_last_hour(provider) >= slot cap` → USD caps with `estimate(kind, words, provider)` (0 when the slot's price table is empty, else Claude-estimate × `slot.cost_scale`) → prewarm/SVG sub-caps; `spend_summary` gains the §2.7 fields | 4 (M) |
| `backend/wd/ai/ledger.py` + `backend/wd/migrations/0010_ai_provider.sql` | `insert_call(..., provider="claude")`, `count_started(..., provider=None)`, `call_dto` adds `provider`; migration §2.6 | 2 (M) |
| `backend/wd/ai/probe.py` | `check(conn, cfg, provider="claude")`: for the fallback, record `ai.fallback.available` / `ai.fallback.last_probe_at`, never touch `claude.flag_tier` (the flag tier is a property of the shared binary); `cmd_claude_check --provider {claude,fallback}`; `register_cli` adds `ai-check` as an alias (`cli.py:49` `COMMAND_OWNERS` gains it) | 2 (C) |
| `backend/wd/config.py` | keys of §2.4; `WD_AI_FALLBACK_MODEL` renamed `WD_AI_CLI_FALLBACK_MODEL` (`config.py:91,334`), `ConfigError` when `WD_AI_FALLBACK_MODEL` is set while `WD_AI_FALLBACK_KIND=none` (the key changed meaning — nobody should silently keep a Claude-only chain there); `WD_AI_FALLBACK_BIN` required when `KIND=claude_cli` | 2 (M) |
| `backend/wd/interfaces.py` | `ClaudeResult` gains `provider: str = "claude"`, `model_requested: str \| None = None` (defaults at the end — `content.py:443` / `lookup.py:574` rebuild it by keyword, verify-contract:F1) | 0.5 (M) |
| `backend/wd/jobs/queue.py`, `backend/wd/jobs/worker.py` | `limit_for(type, cfg, provider="claude")` → `slot.batch_size` for content (`queue.py:38-44`); `process_next` passes `failover.active(conn)` (`worker.py:88`); `ClaudeWorker.housekeeping` (`worker.py:263-272`, every `SWEEP_INTERVAL_S` = 300 s) calls `failover.maybe_probe` | 1.5 (M) |
| `backend/wd/services/bank.py:228-230`, `backend/wd/services/words.py:422`, `backend/wd/diag.py:86-101`, `backend/wd/routers/admin_ops.py:314-333` | `bank.ai_paused_until` delegates to `budget.paused_until(conn, now)` (global meaning); `words.content_deferred_until` and `diag.check_claude` read through the helper instead of `kv.claude.paused_until` directly; the manual admin pause writes `ai.paused_until` (24 h, global) and resume clears both `ai.paused_until` and the two provider pauses; `diag` prints the fallback slot. The gates at `routers/words.py:324`, `routers/bank.py:150`, `jobs/scheduler.py:252`, `services/batches.py:384,498`, `services/bank.py:233-237`, `admin_ops.py:363` need **no edit** — they already call the helpers | 2 (M) |
| `backend/wd/ai/content.py:423` (+ grep `cfg.ai_model` in lookup/consolidate/svg) | provenance rule: `model = result.model_requested if result.provider != "claude" else (result.model_used or ctx.cfg.ai_model)` — never trust a gateway's `modelUsage` echo for a foreign provider (DeepSeek maps names, Zhipu's echo is undocumented — verify-contract:F6) | 0.5 (M) |
| `backend/wd/schemas.py`, `frontend/src/api/types.ts`, `scripts/check_contract.py` | `AiCall.provider`; `AdminOverviewAi` + `active_provider, fallback_configured, fallback_model, failover_since, failover_reason, next_probe_at, banner_zh` (M) and `fallback_calls_today, fallback_content_share_7d` (C); `AdminHealth.fallback` (C); `ProbeRequest {provider?}` / `ProbeResponse.provider` (C); `AiProviderRequest {mode}` (M) | 1.5 (M) + 1.5 (C) |
| `backend/wd/routers/admin_ops.py` | `POST /api/admin/ai/provider {mode: claude\|fallback\|auto}` → `kv.ai.provider_override` (+ `ai_provider_override` event) (M); probe route takes `{provider?}` with the same 1-min `PROBE_MIN_INTERVAL` per provider (C); overview/health plumbing | 1.5 (M) + 1 (C) |
| `frontend/src/pages/AdminPage.tsx` (AI tab, ~705-830), `frontend/src/i18n/zh.ts:87-98` | 来源 column in the ledger table + banner from `banner_zh` (M); segmented control Claude / 备用模型 / 自动 next to 暂停/探测, fallback health card, 备用模型占比 stat (C); zh strings | 2 (M) + 4 (C) |
| `backend/tests/fake_claude.py` | `FAKE_CLAUDE_MODEL` env (the `modelUsage` key, default `claude-sonnet-fake`) so provenance is testable per slot; new modes `region_403` ("API Error: 403 Request not allowed"), `balance_402`, `rate_429` ("API Error: 429 {\"error\":{\"code\":\"1302\"…}}"), `zh_auth` ("API Error: 401 令牌已过期或验证不正确"), `network` ("Can't reach the API server … (ENOTFOUND)"), `managed_settings` (the exact live string), `structured_retries` (envelope with subtype `error_max_structured_output_retries`) | 1.5 (M) |
| `backend/tests/unit/test_failover.py` (new), `test_runner.py`, `test_budget.py`, `test_config.py`, `test_db.py`, `test_claude_fixtures.py`; integration `test_worker.py`, `test_admin_ops.py`, `test_words_resolve.py`, `test_bank.py`; frontend `zh.test.ts`, `zh.contract.test.ts` | see §2.8 | 10 (M) + 3 (C) |
| `deploy/env.example`, `deploy/install.sh:48-49,142-143`, `deploy/claude-fallback.sh.example` (new), `deploy/word-dance.service` (comment), `scripts/dev.sh`, `scripts/smoke.py` | see §2.9 | 3 (M) + 2 (C) |
| `docs/CLAUDE_INTEGRATION.md` (§1.3, §3, §7, new §10 "Provider failover"), `docs/DEPLOY.md` §4 + runbook row 420, `docs/ops.md:196`, `docs/API.md` (54/55/64–66 + new endpoint) | | 2 (M) + 2 (C) |
| `scripts/eval_provider.py` (new; the contract §F17 harness restricted to `--format claude_cli`, i.e. it drives `runner.run_claude` with the real builders against a scratch DB copy through any wrapper) + `scorecard.md` | | 8 (C) |
| `backend/wd/ai/failover.py` quality pause, `WD_AI_FAILOVER_ON_BUDGET_CAP`, per-provider `threading.BoundedSemaphore` in the runner, per-kind model override, admin "regenerate non-Claude cards" filter (`word_contents.model NOT LIKE 'claude-%'`) | | 8 (C) |

Totals: **MVP ≈ 44 h ≈ 5.5 person-days; complete ≈ 76 h ≈ 9.5 person-days** (A0 alone: 0.25 d). The contract digest's "A1 ≈ 4–5 d" (contract:F7) excluded tests of the gate sites, the config rename and the admin plumbing; this list includes them.

### 2.4 New configuration keys (frozen `Settings`; defaults keep today's behaviour bit-for-bit until a slot is configured)

| Key | Default | Meaning / validation |
|---|---|---|
| `WD_AI_PROVIDER` | `claude` | `claude` = today; `fallback` = only the fallback slot (manual mode without touching `WD_CLAUDE_BIN`); `auto` = primary with automatic failover and fail-back |
| `WD_AI_FALLBACK_KIND` | `none` | `none` \| `claude_cli`. (D2 adds `anthropic_http`; the key is shared so the switch later is one value.) |
| `WD_AI_FALLBACK_BIN` | `""` | wrapper path; required (executable) when `KIND=claude_cli` |
| `WD_AI_FALLBACK_MODEL` | `""` | vendor model id sent as `--model` and used for provenance (`glm-4.7-flash`, `qwen3.7-flash`, …); must match the wrapper's `MODEL` |
| `WD_AI_CLI_FALLBACK_MODEL` | `""` | **renamed** from today's `WD_AI_FALLBACK_MODEL` (the CLI's Claude-only `--fallback-model` chain, `runner.py:145-146`); only ever applied to the primary slot |
| `WD_AI_FALLBACK_KINDS` | `lookup,consolidate` | kinds the fallback may serve; add `content` after the eval gate, `svg` opt-in |
| `WD_AI_FALLBACK_BATCH_SIZE` | `5` (1–12) | content claim size while the fallback is active |
| `WD_AI_FALLBACK_CONCURRENCY` | `1` (1–3) | per-provider in-flight cap (semaphore; C) |
| `WD_AI_FALLBACK_TIMEOUT_SCALE` | `1.5` (1.0–4.0) | multiplies `timeout_for(cfg, kind)` on the fallback (content 180 → 270 s) |
| `WD_AI_FALLBACK_HOURLY_CALL_CAP` | `40` (1–100000) | per-provider hourly cap (`calls_last_hour(provider)`); the primary keeps `WD_AI_HOURLY_CALL_CAP=60` |
| `WD_AI_FALLBACK_PRICE_JSON` | `{}` | CNY per 1M tokens `{"input":…,"output":…,"cache_read":…,"peak":{"input":…,"output":…,"hours":"09-12,14-18"}}`; empty = free (cost 0, reservations 0) |
| `WD_AI_CNY_PER_USD` | `7.2` | converts the price table into the ledger's USD column so the existing daily/monthly caps keep one unit |
| `WD_AI_FALLBACK_COST_SCALE` | `0.0` (0–1) | reservation estimate for the fallback as a fraction of the Claude estimate (`budget.ESTIMATES`); 0 for a free slot, ≈0.05 for qwen3.7-flash |
| `WD_AI_FALLBACK_BUDGET_FLAG` | `1` | pass `--max-budget-usd` to the fallback spawn; set `0` if T1 shows the CLI's "Session cost is not a number … refusing to continue under --max-budget-usd" refusal (verify-zhipu omission 3) |
| `WD_AI_FAILOVER_COOLDOWN_MIN` | `30` | primary pause after a hard trigger (same as today's `AUTH_PAUSE`); doubles on a re-failover within 1 h, cap 240 |
| `WD_AI_FAILOVER_PROBE_EVERY_MIN` / `WD_AI_FAILOVER_PROBE_MAX_MIN` | `30` / `120` | recovery-probe cadence while failed over (doubling); each probe is one `probe` ledger row, `--max-budget-usd 0.05` |
| `WD_AI_FAILOVER_OVERLOADED_AFTER` / `TIMEOUT_AFTER` / `NETWORK_AFTER` | `3` / `2` / `2` | consecutive soft failures on the primary before a switch |
| `WD_AI_FAILOVER_ON_BUDGET_CAP` | `0` | `1` = when Claude's daily/monthly USD cap refuses and the fallback is free, run the group on the fallback (decision D4) |
| `WD_AI_FAILBACK` | `auto` | `auto` = first successful probe flips back; `manual` = stay on the fallback until the admin presses Claude |
| `WD_AI_FALLBACK_QUALITY_PAUSE_AFTER` | `3` | consecutive `invalid_output` on the fallback → pause it 30 min + `ai_fallback_quality` event (C) |

The API key is **not** a `WD_*` key: it lives in `$WD_DATA_DIR/secrets/fallback.key` (0600), read only by the wrapper, so it never enters the Python process, `GET /api/admin/config`, logs or the primary's child environment. `SECRET_KEYS` (`config.py:44-53`) therefore needs no new entry.

### 2.5 kv keys

| Key | Meaning | Written by |
|---|---|---|
| `ai.active_provider` | `claude` \| `fallback` (default `claude`) | `failover.record` / `maybe_probe` / admin |
| `ai.failover.since`, `ai.failover.reason`, `ai.failover.trigger_call_id` | when/why the current failover started | `failover.record` |
| `ai.failover.next_probe_at`, `ai.failover.probe_failures`, `ai.failover.cooldown_min` | recovery schedule and doubling state | `failover.maybe_probe` / `record` |
| `claude.paused_until` | **the primary's** automatic pause (unchanged key; today's tests keep passing) | `budget.set_paused_until(provider="claude")` |
| `claude.overloaded_streak`, `ai.primary.streak.timeout`, `ai.primary.streak.network` | primary soft-failure streaks (`claude.overloaded_streak` is today's key, `common.py:32`) | `handle_failure` / `failover.record` |
| `ai.fallback.paused_until`, `ai.fallback.available`, `ai.fallback.last_probe_at`, `ai.fallback.overloaded_streak`, `ai.fallback.invalid_streak` | the fallback's own state | same functions with `provider="fallback"` |
| `ai.paused_until` | **manual** admin pause (global, 24 h) — moved off `claude.paused_until` so a hand pause stops both providers | `POST /api/admin/ai/pause` |
| `ai.provider_override` | admin segmented control (`claude` \| `fallback` \| empty) | `POST /api/admin/ai/provider` |
| `claude.enabled` / `claude.flag_tier` / `claude.available` / `claude.version` / `claude.last_probe_at` | unchanged meaning: kill switch (global), CLI flag tier (shared binary), primary availability, CLI version | as today |

### 2.6 Migration

`backend/wd/migrations/0010_ai_provider.sql` — purely additive, safe under `install.sh --no-restart` (same pattern as `0008_fk_child_indexes.sql:8-10`):

```sql
-- 0010_ai_provider.sql — which provider slot served an ai_calls row ('claude' = the Claude CLI, 'fallback' = the configured
-- fallback slot). Purely additive (safe under deploy/install.sh --no-restart). docs/SCHEMA.sql stays byte-identical to 0001
-- (tests/unit/test_db.py:362-366); the column is documented in CLAUDE_INTEGRATION §10.
ALTER TABLE ai_calls ADD COLUMN provider TEXT NOT NULL DEFAULT 'claude';
CREATE INDEX IF NOT EXISTS ix_ai_calls_provider_started ON ai_calls(provider, started_at);
```

Numbering: design D3 (`docs/analysis/2026-11-04-library-curation/design-D3-model-and-compliance.txt:167`) had pencilled `0010_curation_columns.sql` including `ai_calls.provider`; nothing of it exists in `backend/wd/migrations/` (only 0001, 0008, 0009). This design takes **0010** because it ships first; D3 renumbers to 0011 and drops its `ai_calls.provider` line. `model_requested` keeps the vendor model id (the alias `sonnet` for the primary, as today — all 68 live rows), `provider` answers "which slot", `word_contents.model` answers "which model wrote this card" (contract:F10). No CHECK is touched (`ai_calls.status` stays fixed; `system_events.kind` is free text, so `ai_failover` / `ai_failback` / `ai_fallback_auth` / `ai_fallback_quality` / `ai_provider_override` need no schema change).

### 2.7 Admin API / UI fields

| Surface | Field / route | Source | M/C |
|---|---|---|---|
| `AdminOverviewAi` (`schemas.py:1110-1122`, `budget.spend_summary`) | `active_provider: "claude"\|"fallback"`, `fallback_configured: bool`, `fallback_model: str\|null`, `failover_since`, `failover_reason`, `next_probe_at`, `banner_zh: str\|null` | `kv` via `failover.*` | M |
| | `fallback_calls_today: int`, `fallback_content_share_7d: float` (= `COUNT(*) FILTER (WHERE model NOT LIKE 'claude-%')/COUNT(*)` over `word_contents` created in 7 days) | ledger / `word_contents` | C |
| `AiCall` (`schemas.py:1280-1293`, `ledger.call_dto`) + `types.ts:207` | `provider: str` | column 0010 | M |
| `AdminHealth` (`schemas.py:1181-1190`, `admin_ops.py:193-199`) | `fallback: {kind, model, bin, ok: bool\|null, last_probe_at}\|null` next to `claude_bin` | cfg + `ai.fallback.*` | C |
| `POST /api/admin/ai/provider {mode: "claude"\|"fallback"\|"auto"}` → `{mode, active_provider}` | writes/clears `ai.provider_override`, event `ai_provider_override {by, mode}` | | M |
| `POST /api/admin/ai/probe {provider?: "claude"\|"fallback"}` (`admin_ops.py:336-350`), `ProbeResponse.provider` | `probe.check(conn, cfg, provider=…)`; the 1-min `PROBE_MIN_INTERVAL` is kept per provider (`claude.probe_started_at` / `ai.fallback.probe_started_at`) | | C |
| `POST /api/admin/ai/pause` (`admin_ops.py:314-333`) | pause writes `ai.paused_until` (global, `MANUAL_PAUSE` 24 h) instead of `claude.paused_until`; resume clears `ai.paused_until`, `claude.paused_until`, `ai.fallback.paused_until` and sets `claude.enabled=1` as today | | M |
| AdminPage AI tab (`AdminPage.tsx:705-830`) | banner line under the spend tiles; 来源 column in the ledger table (`labels.provider` exists for image providers — add `labels.aiProvider: '来源'`); segmented control 「Claude · 备用模型 · 自动」 beside 暂停/探测 (C); fallback health row 「备用模型」 (C); stat 「备用模型占比（7 日）」 (C) | | M/C |
| `frontend/src/i18n/zh.ts:88` | `probeFallback: '探测备用模型'`, `providerClaude: 'Claude'`, `providerFallback: '备用模型'`, `providerAuto: '自动切换'`, banner strings §3.5 | | M/C |
| `ServerFlags.ai_enabled` (`routers/auth.py:55`) | unchanged: it means "some provider may run" (kill switch only) — correct already | | — |

`scripts/check_contract.py` audits `schemas.py ↔ types.ts` field by field, so every row above lands in both files in the same commit.

### 2.8 Test doubles and test files

**Doubles.** `tests/fake_claude.py` stays the only double for both slots (the fallback is the same binary behind a different wrapper). Additions: `FAKE_CLAUDE_MODEL` (env, baked into the wrapper by `make_wrapper(dir, mode, model=…)` as `test_runner.py:33-46` already does for the mode) becomes the `modelUsage` key, and the seven new modes of §2.3. `tests/conftest.py` gains `fallback_cfg(primary_mode, fallback_mode)` → `replace(settings, claude_bin=<wrapper A>, ai_fallback_kind="claude_cli", ai_fallback_bin=<wrapper B>, ai_fallback_model="glm-fake", ai_provider="auto")`.

**Unit.**
- `test_failover.py` (new): selection table (modes × pauses × kinds allow-list); hard trigger → `active=fallback`, `claude.paused_until = now+30m`, `ai_failover` event with `trigger_call_id`, `next_probe_at`; immediate retry of the same group lands on wrapper B (assert `env.txt`/`cwd.txt` of wrapper B written, two ledger rows: `auth/claude` then `success/fallback`, jobs `done`, `attempts` unchanged); soft streaks (2 timeouts / 3 overloaded / 2 network) switch, a success resets; `maybe_probe` before/after `next_probe_at`, doubling and cap, fail-back clears the primary pause and emits `ai_failback {outage_min}`; opportunistic fail-back when the fallback is paused; cooldown doubling on re-failover within 1 h; `any_provider_available` with 0/1/2 providers paused; manual override; `WD_AI_PROVIDER=claude` ⇒ bit-identical to today (no kv writes under `ai.*`).
- `test_runner.py`: slot argv (`slot.bin`, `--model glm-fake`, no `--fallback-model`, `--max-budget-usd` present/absent by `budget_flag`); regex table for every new string (403 Request not allowed → auth-class, 402/余额不足 → auth, bare 429 → overloaded, 令牌已过期 without "401" → auth, Token is invalid → auth, ENOTFOUND → overloaded with `network:` prefix, the live managed-settings string → auth, `error_max_structured_output_retries` → invalid_output); cost from the price table (`{"input":0.2,"output":0.8}` × tokens ÷ 7.2) and 0 for `{}`; `ClaudeResult.provider/model_requested`.
- `test_budget.py`: provider-scoped `paused_until`, global `paused_until(None)` = max(manual, min(providers)); `calls_last_hour(provider)`; `estimate(..., provider)` 0 for a free slot; `reserve(provider="fallback")` ignores the primary's pause.
- `test_config.py`: defaults; rename; `ConfigError` on `WD_AI_FALLBACK_MODEL` + `KIND=none`, on missing/non-executable `WD_AI_FALLBACK_BIN`, on bad `PRICE_JSON`.
- `test_db.py`: migration 0010 applies on a 0009 DB, `provider` default `claude` on existing rows, `docs/SCHEMA.sql` still byte-identical to 0001.
- `test_claude_fixtures.py` / `test_schemas.py`: untouched (schema files unchanged).

**Integration.**
- `test_worker.py`: new test beside `:280-298`: primary wrapper in `managed_settings` mode + fallback `ok` → after one `drain`, both content jobs `done`, `word_contents.model == "glm-fake"`, `ai_calls` rows `(auth, claude)`, `(success, fallback)`, `kv.ai.active_provider == "fallback"`, exactly one `ai_failover` event; advance 31 min, swap the primary wrapper to `ok`, `drain` (housekeeping probe) → `ai_failback`, `active == claude`, next content call on wrapper A with batch 10. The existing `test_overloaded_and_auth_outcomes_defer_and_pause` stays green because `WD_AI_FALLBACK_KIND=none`.
- `test_words_resolve.py` / `test_bank.py`: `POST …/content-request` and consolidate route answer 2xx while `claude.paused_until` is in the future but the fallback is healthy; 503 `ai_disabled` when both are paused or `ai.paused_until` is set.
- `test_admin_ops.py`: provider endpoint + event; overview fields; manual pause writes `ai.paused_until`; resume clears all three keys.
- Frontend: `zh.test.ts` / `zh.contract.test.ts` for the new strings; `scripts/check_contract.py` green.

### 2.9 Deploy / install / dev

- `deploy/env.example:53-85`: the §2.4 keys with comments; `WD_AI_FALLBACK_MODEL` row rewritten (vendor id) and `WD_AI_CLI_FALLBACK_MODEL` added; a comment pointing at `bin/claude-fallback` and `secrets/fallback.key`.
- `deploy/claude-fallback.sh.example` (new): the §2.2 script; `install.sh` copies it to `$DATA/bin/claude-fallback` (0700) when absent, creates `$DATA/claude-fallback-config` (0700) and `$DATA/secrets` (0700), and prints "put the key in secrets/fallback.key" when the file is missing.
- `deploy/install.sh:48-49`: keep the `claude` preflight (the CLI is still the only transport); add `claude --version` ≥ 2.1.288 when `WD_AI_FALLBACK_KIND=claude_cli` (the structured-output switch exists from 2.1.288 — verify-others omission 4); `:142-143`: after `wd claude-check`, run `wd ai-check --provider fallback || echo WARN` when a slot is configured (C). `tests/unit/test_deploy_files.py:253` keeps expecting `/.venv/bin/wd claude-check`.
- `deploy/word-dance.service`: comment only — `ProtectHome` stays unset (the primary still needs `~/.claude`), the fallback config dir lives under the data dir.
- `scripts/dev.sh:25-29`: `WD_AI_FALLBACK_BIN` points at a second fake wrapper so `auto` mode is exercisable locally; `scripts/smoke.py` gains an optional `--failover` step (primary wrapper `auth`, fallback `ok`, assert content ready with the fake model id) (C).
- macOS/launchd (memory note "macOS local install layout"): nothing new; the wrapper reads `WD_FALLBACK_REAL_CLAUDE=/opt/homebrew/bin/claude` from its own header, not from the service environment.

### 2.10 The live-ledger outage (managed-settings failure) replayed under A1

Facts being replayed: `ai_calls` 33–47 (3 consolidate + 12 content) all `auth` with "Your organization requires remote managed settings to load, but they could not be loaded. Run `claude auth login` …", 14 `claude_auth` events at 30–65-min spacing from 2026-11-02 18:43 to 11-03 02:26 UTC, learners' content requests answered `503 ai_disabled` meanwhile (contract:F16, verify-contract:F11).

| t | Today (observed) | With A1 (`WD_AI_PROVIDER=auto`, GLM slot configured) |
|---|---|---|
| 18:43:40 | consolidate group fails `auth` (string matches `log ?in`); `claude.paused_until = 19:13`; `claude_auth` event; jobs deferred | same classification (now also an explicit `remote managed settings` match). `failover.record`: hard trigger → `claude.paused_until = 19:13`, `ai.active_provider = fallback`, `ai.failover.since/reason/trigger_call_id = 33`, `next_probe_at = 19:13`, event `ai_failover {from: claude, to: fallback, reason: auth, error: "Your organization requires…", trigger_call_id: 33, banner_zh}`. **Immediate retry**: `budget.reserve(provider=fallback)` (est 0, hourly 0/40), spawn `bin/claude-fallback` with the same consolidate prompt, timeout 240×1.5 = 360 s |
| 18:43:50 | — | fallback returns `success` in ≈8 s; `consolidate.apply` runs; ledger row 34 = `(success, fallback, model_requested glm-4.7-flash)`; `system_events` shows the banner 「Claude 暂不可用，已自动切换到备用模型 glm-4.7-flash（自 18:43 起，每 30 分钟自动探测恢复）」 |
| 18:44–19:13 | every claim sees `paused_until` → deferred to 19:13; a learner's content request → `503 ai_disabled`; batch builder treats AI as off | `queue.limit_for` → 5; `select` → `fallback` (sticky); content groups of 5 run on GLM (≈40–70 s each, concurrency 1); `bank.ai_paused_until` → `None` (fallback healthy) so content requests and consolidation stay `2xx`; batches keep waiting for content normally; `svg` jobs (not in `WD_AI_FALLBACK_KINDS`) defer to 19:13 |
| 19:13:40 | first retry after the pause → `auth` again → pause to 19:43, 2nd event (`event_once` 30-min window) | housekeeping tick ≥ 19:13 (5-min granularity → ≤ 19:18): `maybe_probe` → `probe.check(primary)` = one tier-1 + one tier-0 probe call (≈2 ledger rows, kind `probe`, ≤ $0.10 cap, actual ≈$0.004) → both `auth` → `probe_failures = 1`, `next_probe_at = 19:43 + jitter`, `claude_auth` event refreshed (still once per 30 min, banner unchanged). No job touched Claude |
| 19:43 → 02:26 | 13 more pause/retry cycles; 15 failed job calls; nothing produced for 6 h 40 min | probes at 19:43, 20:43 (interval doubled to 60), 22:43 (120, cap) → 3 more probe pairs; the fallback produced every lookup/consolidation/content requested meanwhile (if `content` is in the allow-list) — ledger shows 0 failed job calls after row 33 |
| recovery (owner re-authenticates or the Enterprise profile is fixed; earliest at the next probe, ≤ 2 h later) | the next retry after the pause succeeds; nothing records that an outage happened except the event trail | next probe → exact `probe_v1` match → `ai.active_provider = claude`, `claude.paused_until` cleared, `probe_failures = 0`, event `ai_failback {outage_min, probe_call_id}`, banner gone; next claim: batch 10 on Claude. Cards written by GLM keep `word_contents.model = glm-4.7-flash`; the admin filter (C) lists them for optional regeneration |
| failure during failover | — | if GLM answers 429/1305 at peak: `overloaded` on the fallback → defer 2 min × attempts, 6 in a row → `ai.fallback.paused_until = +15 min`; with the primary also paused, `select` → `None` → groups defer to the earlier of the two pauses; banner 「AI 暂时不可用（主模型与备用模型均失败），任务已排队等待」; learners see `503 ai_disabled` only in this window |

Net effect on the measured incident: 1 failed job call instead of 15, 4–5 probe pairs instead of 14 blind retries, zero learner-visible downtime while the free model is healthy, fail-back within ≤ 2 h of recovery (≤ 30 min in the first hour).

### 2.11 Every CLI caveat from the fact base and what D1 does with it

| # | Caveat (source) | Neutralised / accepted — how |
|---|---|---|
| 1 | `--json-schema` is a synthetic `StructuredOutput` **tool call** (not forced via `tool_choice`) plus an `output_config.format` beta that third-party upstreams reject (others:F9, verify-zhipu:F7) | **Neutralised** for the request shape: `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1` (CLI ≥ 2.1.288; Mac 2.1.292) in the wrapper, `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` as the second lever. **Accepted** for reliability: the tool is unforced, so a weak model may answer in text; the CLI retries client-side (each retry is an upstream round trip inside the timeout) → timeout ×1.5, batch 5; `error_max_structured_output_retries` → `invalid_output` (counts toward the quality pause, never a failover trigger); `success` without `structured_output` stays `error` (`runner.py:258-263`). The eval harness measures "structured_output present" per kind before content is allowed |
| 2 | Thinking cannot be switched off by a CLI flag; unknown ids get adaptive thinking; `MAX_THINKING_TOKENS=0` only omits the field, vendors then default ON (verify-alibaba omission 1, verify-bd omission 1) | **Attempted neutralisation**: `CLAUDE_CODE_EXTRA_BODY='{"thinking":{"type":"disabled"}}'` (documented "merge into the top level of every API request body"; merge order vs the CLI's own field unverified) + `MAX_THINKING_TOKENS=0` — T2 verifies by comparing `usage.output_tokens` with the visible JSON size. **Accepted** if it fails: on the free GLM slot thinking costs latency only (≈96–122 tok/s → still inside 270 s for 5–10 words); on a paid step-up the go/no-go is the measured token multiplier, and the blast radius is a small prepaid balance (¥50) plus the per-provider hourly cap |
| 3 | `total_cost_usd` is a client-side estimate; foreign ids → `costBasis: "unknown"` (≈0) so `--max-budget-usd` and the app's USD caps go blind; a non-numeric session cost makes the CLI refuse under `--max-budget-usd` (others:F11, verify-zhipu omission 3) | **Neutralised** in the app: `cost_usd` for the fallback = envelope `usage` tokens × `WD_AI_FALLBACK_PRICE_JSON` ÷ `WD_AI_CNY_PER_USD` (0 for a free slot); reservations use `WD_AI_FALLBACK_COST_SCALE`; per-provider hourly cap is the real rate guard on a free slot; `WD_AI_FALLBACK_BUDGET_FLAG=0` drops the flag if T1 shows the NaN refusal. Managed-scope `modelPricing` (prices a custom id inside the CLI, Managed only) is an optional later addition, not a dependency |
| 4 | Provenance: `model_used` = first `modelUsage` key, whatever the gateway echoes; alias `sonnet` is resolved client-side; `--model` overrides `ANTHROPIC_MODEL` (contract:F6.3, others:F8) | **Neutralised**: the slot's `--model` carries the vendor id, the wrapper also redirects the three alias slots (`ANTHROPIC_DEFAULT_*_MODEL`), `ai_calls.provider` + `model_requested` are the source of truth, `word_contents.model` takes `model_requested` for non-Claude providers (`content.py:423` rule) |
| 5 | Anthropic's documentation states it "doesn't support routing Claude Code to non-Claude models through any gateway" (https://code.claude.com/docs/en/llm-gateway, accessed 2026-11-04) — reported, not analysed, per the owner's instruction | **Accepted as an engineering risk**: the request shape may change with any CLI release → `DISABLE_AUTOUPDATER=1`, version pinned in `install.sh`, `kv.claude.version` on the health page, nightly fallback probe (C), and D2 (HTTP adapter) as the exit if a release breaks the route |
| 6 | Managed settings / `forceLoginMethod`: token auth "cannot coexist" with those managed settings; the live outage *is* a managed-settings fetch failure (verify-contract omission 5, contract:F6.5) | **Neutralised if T0 passes**: separate empty `CLAUDE_CONFIG_DIR` (no Enterprise profile → no org to fetch settings for) + `ANTHROPIC_AUTH_TOKEN` ("in non-interactive mode the key is always used"). **Kill criterion** if T0 fails with the managed-settings/first-party-login string: D1 is not viable, go to D2 |
| 7 | CLI version requirements (≥ 2.1.288 for the structured-output switch; 2.1.246 for `costBasis`; `API_TIMEOUT_MS=0` only ≥ 2.1.305) and unknown VPS version (verify-others omission 4) | **Neutralised**: install preflight checks `claude --version` ≥ 2.1.288 when a `claude_cli` slot is configured; `probe.record_version` already stores it; `diag` warns below the floor |
| 8 | Nonessential traffic to anthropic.com / GitHub (version checks, telemetry, fast-mode check, session-title model call, attribution block in the prompt) — none of the switches pass the runner's allow-list (others:F12) | **Neutralised in the wrapper**: `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_FEEDBACK_COMMAND=1 CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 CLAUDE_CODE_ATTRIBUTION_HEADER=0`; the `HEAD /api/hello` warm-up goes to the gateway (Zhipu answers 200, others 404 — harmless per the protocol page) |
| 9 | Unknown ids receive every current-Claude field (adaptive thinking, effort, `context_management`, mid-conversation `role:"system"`), `max_tokens` default 32000, context assumed 200K, `count_tokens` optional (contract:F6.4) | **Accepted with guards**: `CLAUDE_CODE_MAX_OUTPUT_TOKENS=16000`, `CLAUDE_CODE_MAX_CONTEXT_TOKENS` per model, `API_TIMEOUT_MS=600000`; 400-and-retry sequences are tolerated by the CLI itself and visible in the raw log (`save_raw`) — T1 inspects them |
| 10 | `--fallback-model` is Claude-only, same base URL, never fires on auth/rate-limit (others:F10); `WD_AI_FALLBACK_MODEL` already means that flag (contract:F6.7) | **Neutralised**: key renamed `WD_AI_CLI_FALLBACK_MODEL`, applied to the primary slot only; cross-provider failover lives in `failover.py` |
| 11 | Classifier gaps: 403/forbidden/"Request not allowed", 402/余额不足, bare 429, usage-limit strings, ENOTFOUND/ECONNREFUSED, Chinese auth bodies, "Token is invalid", "invalid api-key" (contract:F6.6, verify-others omission 3) | **Neutralised** by the regex patch (§2.3 runner row) — independent of everything else and worth shipping first (0.25 d) so even today's pause path recognises the region block |
| 12 | Credential header: `ANTHROPIC_AUTH_TOKEN` → `Authorization: Bearer`, `ANTHROPIC_API_KEY` → `x-api-key`; MiniMax wants `X-Api-Key` (contract:F7) | Bearer for Zhipu / 百炼 / DeepSeek (all documented); `ANTHROPIC_API_KEY` unset in the wrapper so only one header is sent; MiniMax is not in the chain |
| 13 | Silent exit-0 with no request for odd key prefixes (issue #43607), text-instead-of-tool_use from small models (#25857), markdown-wrapped JSON (#18536) (others:F9) | `--tools ""` means only the injected tool reaches the model (no tool flooding); exit-0-without-structured → `error` → backoff/bisect, never a trigger; the install probe catches a dead key immediately |
| 14 | Prompt-injection posture relies on `--tools ""`, `--restricted` etc. (contract:F5) | **Unchanged**: argv comes from the runner for both slots; the wrapper adds env only |

---

## 3. Failure → action table

Primary = Claude CLI slot, mode `auto`. "Switch" = `ai.active_provider=fallback`, `system_events('ai_failover')`, schedule the recovery probe, **retry the same still-claimed group once on the fallback immediately** (if the fallback accepts the kind). "Defer" = today's behaviour (`queue.defer` to a resume instant, no attempt consumed). Streak counters are per provider and reset on any success of that provider (`record_success(provider)`).

### 3.1 Signals on the **primary** (Claude)

| Signal — `parse_and_classify` + new regexes | Status in `ai_calls` | Trigger class | Today | With A1 (`auto`) | Cooldown / counter |
|---|---|---|---|---|---|
| `Not logged in`, `log ?in`, `authentication`, `unauthori[sz]ed`, `\b401\b`, `credential`, `invalid api key` | `auth` | **hard** | pause all AI 30 min + `claude_auth` event + defer | pause **primary** `COOLDOWN_MIN` (30), switch, retry group on fallback | cooldown ×2 if the primary already failed over within the last 60 min (cap 240 min) |
| the live managed-settings string (`remote managed settings`, `first-party login`) | `auth` | hard | same (matched only via `log ?in`) | same as auth, explicit match; `ai_failover.reason = "managed_settings"` | same |
| new `REGION_RE`: `\b403\b`, `forbidden`, `request not allowed` (what this network gets from api.anthropic.com without the tunnel) | `auth` | hard | `error` → backoff → bisect → dead (jobs die for a network policy!) | pause primary, switch, retry | same |
| billing/usage: `\b402\b`, `insufficient balance`, `余额不足`, `欠费`, `usage limit`, `plan limit`, `enforced_spend_limit_reached`, `credit balance` | `auth` | hard | `error` chain | pause primary, switch, retry; event detail says `reason: billing` | same |
| `spawn_error` (binary missing / EACCES) | `spawn_error` | hard | pause + `claude.available=0` | same + switch + retry | same |
| `overloaded`, `\b529\b`, `\b503\b`, `rate.?limit`, `too many requests`, new `\b429\b`, `server busy` | `overloaded` | **soft** | defer 2 min × attempts; 6 in a row → 15-min pause | defer as today **and** `claude.overloaded_streak ≥ OVERLOADED_AFTER (3)` → switch + retry; the 6-streak 15-min pause still applies to the primary | streak reset on success; the pause itself makes `select` prefer the fallback for its duration (rule 4) |
| new `NETWORK_RE` (`ENOTFOUND`, `ECONNREFUSED`, `ECONNRESET`, `ETIMEDOUT`, `EAI_AGAIN`, `Can't reach the API`, `Connection refused`, `fetch failed`, `socket hang up`, `malformed response (HTTP 200)`, `certificate`) | `overloaded` (error text `network: …`) | soft | `error` chain → jobs die on a DNS blip | defer 2 min; `ai.primary.streak.network ≥ NETWORK_AFTER (2)` → switch + retry | reset on success |
| `timeout` (killed process group) | `timeout` | soft | backoff; bisect on the 2nd | backoff as today; `ai.primary.streak.timeout ≥ TIMEOUT_AFTER (2)` → switch + retry (group unchanged; the fallback gets ×1.5 timeout) | reset on success |
| `budget` (CLI `--max-budget-usd` stop) | `budget` | never | bisect | unchanged | — |
| `can_spend` refused by daily/monthly USD cap | (no row) | never by default | defer to 00:05 / 1st | unchanged; `WD_AI_FAILOVER_ON_BUDGET_CAP=1` → run the group on a *free* fallback instead (its own caps apply; est 0 keeps the primary's caps intact) | — |
| `invalid_output` (handler: every item failed), `error` (other), `error_max_structured_output_retries` | `invalid_output` / `error` | **never** | backoff → bisect → dead | unchanged (a prompt/content problem would recur on the fallback) | counted per provider for the admin only |
| any `success` | `success` | — | ends the overload streak | resets all primary streaks; if this success was an opportunistic fail-back attempt (rule 4) → `active=claude`, `ai_failback` | — |

### 3.2 Signals on the **fallback** (same table applied with `provider=fallback`; nothing here ever flips `active_provider` by itself)

| Signal | Action | Cooldown |
|---|---|---|
| `auth` (401 `令牌已过期或验证不正确`, `身份验证失败`, `Token is invalid`, `invalid api-key`, code 1000/1001/1003), billing (`欠费` 1113, `Arrearage`, `AllocationQuota.FreeTierOnly` 403) | `ai.fallback.paused_until = +30 min`, `ai.fallback.available = 0`, event `ai_fallback_auth` (banner 「备用模型密钥无效/余额不足」); the group is deferred to `min(primary.paused_until, fallback.paused_until)`; if the primary is *not* paused the next `select` simply uses Claude | 30 min; the owner fixes the key/balance; the admin 探测备用模型 button clears it on success |
| `overloaded` (429 codes 1302 account / 1305 platform / 1308 windowed cap, `访问量过大`, `速率限制`, Allocated quota exceeded) | defer 2 min × attempts; `ai.fallback.overloaded_streak ≥ 6` → `ai.fallback.paused_until = +15 min` + event `ai_fallback_overloaded` | as today's table, provider-scoped |
| `timeout` | backoff; bisect on the 2nd (slower model: batch 5 and ×1.5 already applied) | — |
| `invalid_output` | backoff/bisect as today; `ai.fallback.invalid_streak ≥ QUALITY_PAUSE_AFTER (3)` → pause fallback 30 min + `ai_fallback_quality` (C) — protects the queue from a model that stopped emitting the tool call | 30 min |
| `spawn_error` (wrapper missing / not executable) | `ai.fallback.available = 0`, pause fallback 24 h, event; `diag` and the health card show it | until `wd ai-check --provider fallback` or restart |
| `success` | resets fallback streaks | — |

### 3.3 Fail-back rule

- While `active = fallback`: `ClaudeWorker.housekeeping` (every 300 s) runs `probe.check(primary)` when `now ≥ next_probe_at` (initially `since + PROBE_EVERY_MIN`); success → `active = claude`, clear `claude.paused_until`, `probe_failures = 0`, `ai_failback {outage_min, probe_call_id}`; failure → `next_probe_at = now + min(PROBE_EVERY_MIN × 2^failures, PROBE_MAX_MIN)`.
- Opportunistic fail-back (rule 4 of §2.1.1): when the fallback is paused and the primary pause has elapsed, a real job call tries Claude; success counts as recovery, a hard failure re-pauses it with the doubled cooldown. At most one failed Claude call per cooldown window.
- `WD_AI_FAILBACK=manual`: the probe still runs and records `claude.available=1`, but the flip waits for the admin (segmented control → Claude).
- Anti-flap: a re-failover within 60 min of a fail-back doubles `ai.failover.cooldown_min` (30 → 60 → 120 → 240) and starts the probe interval at the doubled value. First successful probe is enough to flip back (decision D6 offers "N successes" as the alternative).
- The admin 探测 claude button (`PROBE_MIN_INTERVAL` 1 min) forces the same check at any time.

### 3.4 Budget, hourly cap, concurrency, timeouts, batch size, provenance

| Aspect | Primary | Fallback (free GLM) | Fallback (paid step-up) |
|---|---|---|---|
| `can_spend` order | kill switch → `claude.paused_until` → `calls_last_hour('claude') ≥ 60` → monthly → daily → prewarm → svg | kill switch → `ai.fallback.paused_until` → `calls_last_hour('fallback') ≥ 40` → USD caps with est **0** (never bind) → prewarm/svg sub-caps (est 0 → never bind; prewarm plans must be sized by `limit`, contract:F12) | same with est = Claude estimate × `COST_SCALE` (≈0.05 for qwen3.7-flash → ≈$0.0025 per 10-word call) and `cost_usd` from the price table (peak/off-peak aware), so the owner's daily/monthly USD caps keep protecting paid spend |
| cost recorded | envelope `total_cost_usd` (as today) | 0 | tokens × CNY table ÷ `CNY_PER_USD`; `system_events('ai_cost_unknown')` once per day if the envelope carries no `usage` |
| `--max-budget-usd` | as today | passed (`BUDGET_FLAG=1`) — inert for an unpriced id; dropped if T1 shows the NaN refusal | same |
| concurrency | `WD_AI_CONCURRENCY` threads (1–3) | `WD_AI_FALLBACK_CONCURRENCY=1` semaphore (C; moot while the owner runs 1 thread) | per vendor limits (百炼 30k RPM → 1–3) |
| timeouts | content 180 / lookup 120 / consolidate 240 / svg 120 / probe 60 s | × 1.5 → 270 / 180 / 360 / 180 / 60 | × 1.0–1.5 |
| batch size | content 10, lookup 20 | content **5**, lookup 20 (a 20-string lookup is ≈3k output tokens, fine) | content 10 |
| retries of the same group on switch | — | one immediate retry, attempts unchanged, new ledger row | same |
| provenance | `ai_calls.provider='claude'`, `model_requested='sonnet'`, `model_used` from `modelUsage`; `word_contents.model = model_used` | `provider='fallback'`, `model_requested='glm-4.7-flash'`, `model_used` = gateway echo (informational); `word_contents.model = 'glm-4.7-flash'`; `prompt_version` stays `content-v1` so `select_jobs` never regenerates on its own (contract:F10) | same with `qwen3.7-flash` |
| logging | `claude_call` log `extra` gains `provider`; events `ai_failover`, `ai_failback`, `ai_fallback_auth`, `ai_fallback_overloaded`, `ai_fallback_quality`, `ai_provider_override`, `ai_cost_unknown` | | |

### 3.5 User-facing / admin banner texts (`failover.banner_zh`; surfaced in `system_events.detail.banner_zh` and `AdminOverviewAi.banner_zh`; learners never see provider names)

| State | Banner (zh) |
|---|---|
| failover active, fallback healthy | 「Claude 暂不可用，已自动切换到备用模型 {model}（自 {since 本地时间} 起，每 {n} 分钟自动探测恢复）」 |
| primary down, no fallback configured | today's `AUTH_BANNER_ZH` 「Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录」 |
| both paused | 「AI 暂时不可用（主模型与备用模型均失败），任务已排队等待，预计 {resume} 恢复」 |
| fallback key / balance problem | 「备用模型密钥无效或余额不足，请检查 secrets/fallback.key 与账户余额」 |
| fallback quality pause | 「备用模型连续输出无效，已暂停 30 分钟」 |
| manual override active | 「管理员已手动指定 {provider}」 |
| learner-facing (unchanged) | `503 ai_disabled` 「AI 功能当前不可用」 only when `any_provider_available` is None; `budget_exhausted` and the 「今日 AI 额度已用完」 card text as today |

---

## 4. Rollout

### 4.1 Today — zero code (≈1–2 h, ≈¥0)

1. **Accounts/keys.** Register on open.bigmodel.cn with the mainland phone; create a *standard* API key (not a Coding Plan key); no 实名 needed to call (zhipu:F9; do 实名 only when recharging). Write it to `~/word-dance-data/secrets/fallback.key` (dir 0700, file 0600). Optionally also open 百炼 (needs 实名), create a workspace in 华北2 and a key for the step-up tests (its 1M-token free grant makes the tests free; check whether the account was opened before 2025-09-08 — the grant may already have expired, verify-alibaba:F1).
2. **Wrapper.** Install `bin/claude-fallback` from §2.2 (`WD_FALLBACK_REAL_CLAUDE=/opt/homebrew/bin/claude` on the Mac, `/home/sqin/.local/bin/claude` on the VPS), `mkdir -m 700 claude-fallback-config`.
3. **Scratch data dir** — never the live one: `cp -R` the data dir's DB (or `VACUUM INTO`) into `scratchpad/fallback/livetest/`, point `WD_DATA_DIR` there, `WD_CLAUDE_BIN=<fallback wrapper>`, `WD_AI_MODEL=glm-4.7-flash`, `WD_AI_FALLBACK_MODEL=""`, `WD_AI_EXTRA_ARGS=""`.
4. **Live tests (order matters; each answers a blocking question):**

| Test | Command (scratch `WD_DATA_DIR`) | What to read in the raw log (`claude-logs/<day>/<id>.json`) | Go / no-go | Cost |
|---|---|---|---|---|
| **T0 managed settings + probe** | `wd claude-check` under the fallback wrapper | stderr for "remote managed settings" / "first-party login" (→ **D1 dead, go D2**); `structured_output == EXPECTED` (enum + array OK); `modelUsage` key (vendor id or something else?); `total_cost_usd` (0? absent? NaN refusal "Session cost is not a number"?); tier-1 vs tier-0 result; any 400-and-retry lines (`thinking`, `output_config`, `Unexpected role "system"`) | go = exit 0 and exact match at tier 1 or 0; record the modelUsage key and cost semantics for the runner tests | ¥0 (GLM); ≤ ¥0.01 (qwen) |
| **T1 one real content call** | enqueue 10 seed words (`wd worker-once` on the scratch DB with `WD_AI_BATCH_SIZE=10`) | latency vs 180 s; `usage.output_tokens` vs compact JSON bytes ÷ 2.55 (thinking share); `content_state='ready'` count after `validate_item`; stderr 400/retry sequences; `error_max_structured_output_retries`? | go = ≥ 8/10 ready, latency ≤ 120 s, no CLI refusal; else re-run with `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`, then `WD_AI_BATCH_SIZE=5` | ¥0 / ≈¥0.01 |
| **T2 thinking off** | same as T1 with and without `CLAUDE_CODE_EXTRA_BODY='{"thinking":{"type":"disabled"}}'` | `usage.output_tokens` difference; any 400 on the extra body | keep the line if tokens drop to ≈ JSON size and no 400; drop it otherwise. **Step-up go/no-go**: qwen3.7-flash only if thinking is really off (else GLM-5.3-Flash on the Zhipu key) | ¥0 / ≈¥0.02 |
| **T3 lookup + consolidate** | 20 realistic strings (incl. misspellings, CJK, gibberish) via the bank; one consolidation run | `apply_item` outcomes (headword relatedness, `fix_spelling` share), consolidate unknown-id / downgraded-target counts | go = lookup agreement ≥ 90 % on the 40-case built-in set (§4.3), consolidate applies without errors | ¥0 |
| **T4 reachability from Tokyo** | on the Lighthouse VPS: `curl -sS -X POST https://open.bigmodel.cn/api/anthropic/v1/messages -H 'content-type: application/json' -d '{}'` and the 百炼 workspace host | expect HTTP 401 JSON from both in < 2 s (reachable, not geo-blocked) | go = 401; no-go (timeout/reset) = use api.z.ai or Singapore 百炼 host | ¥0 |
| **T5 version floor** | `claude --version` on the VPS | ≥ 2.1.288 | else `npm`/cask upgrade before using `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS` | ¥0 |

5. **Manual failover procedure (until A1 ships)** — in `~/word-dance-data/.env`: `WD_CLAUDE_BIN=/…/bin/claude-fallback`, `WD_AI_MODEL=glm-4.7-flash`, `WD_AI_BATCH_SIZE=5`, `WD_AI_CONCURRENCY=1`, `WD_AI_TIMEOUT_CONTENT_SEC=270`, `WD_AI_TIMEOUT_CONSOLIDATE_SEC=360`, `WD_AI_FALLBACK_MODEL=""`; restart the service; `wd claude-check`; 管理 → AI 恢复 if paused. Reverse the lines to fail back. Caveats while in A0: the USD caps are blind (cost 0), the ledger shows `model_requested=glm-4.7-flash` (provenance is correct because `WD_AI_MODEL` carries the vendor id), SVG generation runs on GLM too (set `WD_SVG_VIA_CLAUDE=0` for the duration), and the 「未登录」 banner logic is unchanged.

### 4.2 This week (A1 MVP, 5.5 person-days) — ship order

1. Regex patch alone (0.25 d) — merge first, independent, immediately useful for the region block.
2. Config rename + slots + `failover.py` + budget/ledger scoping + migration 0010 + handler provenance rule (≈3 d), tests green with `WD_AI_FALLBACK_KIND=none` unchanged.
3. Admin MVP surface (provider endpoint, ledger column, banner) + deploy files + docs (≈1 d).
4. Integration tests, `wd claude-check` under both wrappers on a scratch dir, then enable on the live box: `WD_AI_PROVIDER=auto`, `WD_AI_FALLBACK_KIND=claude_cli`, `WD_AI_FALLBACK_BIN`, `WD_AI_FALLBACK_MODEL=glm-4.7-flash`, `WD_AI_FALLBACK_KINDS=lookup,consolidate` (content after §4.3).
5. First real failover drill: temporarily point the primary wrapper at a non-existent binary (spawn_error) for one `wd worker-once` on a scratch copy — observe the sequence of §2.10.

### 4.3 Eval gate before `content` joins `WD_AI_FALLBACK_KINDS` (eval harness, C; 1 d to build, ≈15 min per candidate to run)

`scripts/eval_provider.py --format claude_cli --bin <wrapper> --model <id> --kinds content,lookup,consolidate --per-stage 10 --extra phrases=3,abbreviation=3,proper_noun=2 --paired --batch-size 5 --out scratchpad/fallback/eval/<model>/` (the contract §F17 spec restricted to the CLI transport: it reuses the production builders, `jsonschema` 4.26 on the **original** schema first — the lax pydantic mirror would otherwise coerce `difficulty: true → 1` (verify-contract omission 1) — then `models.valid_items` + `content.validate_item` with `words.forms_of`, writes `scorecard.md`, `calls.jsonl`, `items.jsonl` with the paired Sonnet item for human spot checks).

Go/no-go thresholds (from contract:F17, adjusted for the ×1.5 timeout): structured_output present ≥ 98 % of calls · item pass (`validate_item`) ≥ 95 % · headword present in ≥ 97 % of examples · ≥ 3 usable examples in ≥ 95 % of items · zh fields CJK ratio ≥ 0.6 · p95 latency ≤ 0.6 × 270 s = 162 s · truncation/`error_max_structured_output_retries` = 0 · lookup agreement ≥ 90 % on the built-in 40-case set · consolidate unknown-id rate ≤ 2 % · plus a 20-item human spot check (naturalness of `meaning_zh` / `mnemonic_zh`, example correctness) scored ≥ 4/5 on average against the paired Sonnet rows. **Pass** → add `content`. **85–95 % item pass** → keep GLM for lookup/consolidate, route content to the step-up (decision D2). **< 85 %** → the free model is lookup/consolidate only; step-up required for content. Cost of one GLM run: ¥0; of one qwen3.7-flash run: ≈¥0.3 (or free within the 1M grant).

### 4.4 Later (weeks 2–3+, to "complete" ≈ 9.5 person-days cumulative)

Admin segmented control + health card + 7-day share; `wd ai-check --provider fallback` in `install.sh`; fallback quality pause; per-provider semaphore; `WD_AI_FAILOVER_ON_BUDGET_CAP`; smoke `--failover` step; "regenerate non-Claude cards" admin filter for the day Claude returns; per-kind model override (`WD_AI_FALLBACK_MODEL_BY_KIND` JSON) so consolidate can use a stronger paid model while content stays free; optional Managed-scope `modelPricing` file on the VPS if the owner wants `--max-budget-usd` to mean something on the fallback; the step-up wrapper (`bin/claude-fallback-qwen`) kept ready. If a CLI release breaks the request shape despite the pin, or T0 fails, D2 (Anthropic/OpenAI HTTP adapter behind the same `WD_AI_FALLBACK_KIND` key) replaces the transport without touching `failover.py`, the ledger column or the admin surface.

---

## 5. Risks (top 8) with mitigations

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| 1 | **T0 fails: the CLI insists on the Enterprise managed settings / first-party login even under an empty `CLAUDE_CONFIG_DIR` with a token** (verify-contract omission 5) | medium / fatal for D1 | Decided in 10 minutes on day 1 before any code; the kill criterion sends the work to D2 (HTTP adapter); `failover.py`, migration, admin surface and tests are transport-agnostic and survive |
| 2 | **GLM-4.7-Flash is not served on `/api/anthropic`, or rejects Claude Code's request fields** (free-model coverage of the Anthropic endpoint is undocumented — verify-others omission 6, verify-zhipu:F6) | medium / high | T0/T1 with the raw log; fallbacks in order: `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1` → `glm-4-flash-250414` (free, 128K/16K — enough for every kind incl. 80-item consolidate ≈8k out) → Z.ai `api.z.ai/api/anthropic` → step-up qwen3.7-flash (documented Claude Code support) |
| 3 | **Thinking cannot be switched off from the CLI** → latency on GLM, cost multiplier on a paid step-up (verify-alibaba omission 1) | medium / medium | `CLAUDE_CODE_EXTRA_BODY` test T2; batch 5 + ×1.5 timeouts absorb latency; paid step-up gated on measured tokens; prepaid balance ≤ ¥50 and per-provider hourly cap bound the damage; GLM-5.3-Flash (thinking forced but ¥0.8/¥2.8) as the priced alternative |
| 4 | **Unforced `StructuredOutput` tool + a 30B model → text answers, client retries, `error_max_structured_output_retries`, lost items on the headword rule** | medium / medium | Eval gate before content; `invalid_output` streak → quality pause; bisect isolates bad words; lookups/consolidate (short, schema-checked) first; the 48 Sonnet rows as the paired baseline |
| 5 | **Zhipu free-tier concurrency ≈1, peak throttling (1302/1305/1308), no status page** (verify-zhipu:F3, F14) | high / low-medium | concurrency 1, defer/backoff, 6-streak 15-min pause provider-scoped; schedule prewarm/consolidate 00:00–14:00 CST; never run the 912-call seed prewarm on the free tier without `limit` sizing (≈15–30 h at 40/h); paid step-up for bulk |
| 6 | **Anthropic does not support this routing; a CLI release changes the request shape or the StructuredOutput mechanics** (others:F9, F13 — reported only) | medium over months / high | `DISABLE_AUTOUPDATER=1`, version floor in `install.sh`, `kv.claude.version` on the health page, nightly fallback probe, raw logs kept 14 days; D2 is the designed exit and shares everything above the transport |
| 7 | **Cost blindness**: `total_cost_usd` 0/unknown, possible NaN refusal, 百炼's 用完即停 off by default (silent roll into pay-as-you-go), 欠费 → 403 `Arrearage` (verify-alibaba omission 4) | medium / low-medium | App-side CNY pricing + `COST_SCALE` reservations; `BUDGET_FLAG` toggle; enable 用完即停 per model during the grant; keep balances small; `Arrearage`/`AllocationQuota` map to the auth class (pause fallback, event) |
| 8 | **Flapping / partial outages** (Claude intermittently 529, probe succeeds then jobs fail) and **state drift** (kv keys edited by hand, manual override forgotten) | low-medium / medium | Sticky state, cooldown doubling, probe-based fail-back only, override visible in the banner and overview, `diag` prints every `ai.*` key, `WD_AI_FAILBACK=manual` for conservative operation |

Also tracked (not top-8): BigModel's anonymised-training clause (prompts are vocabulary and bank rows only; Z.ai or 百炼 if the owner wants a no-training guarantee — D1); free-model retirement on a ~12-month cadence (model id is config, release log twice a year, auto-routing history); the content-safety filter (code 1301) rejecting an English batch (per-item `error`, bisect isolates the word); Tokyo→mainland cross-border latency (T4).

---

## 6. Decisions only the owner can make (with the default this design assumes)

| # | Decision | Default |
|---|---|---|
| D1 | Zhipu region/account: **BigModel** (支付宝/微信, mainland latency, anonymised-training clause, 实名 only to recharge) vs **Z.ai** (no training / no storage, USD card without 3DS or PayPal, Singapore terms) | BigModel; switch = base URL + key file |
| D2 | Which kinds the *free* model may serve, and what to do if it scores 85–95 % on content | `lookup,consolidate` now; `content` after the eval passes; otherwise content → step-up |
| D3 | Step-up provider: **百炼 qwen3.7-flash** (≈¥15/mo, 实名, no training; thinking must be off) vs **DeepSeek-flash** (global platform, ¥54–108 + thinking, trains by default) vs **GLM-5.3-Flash on the same Zhipu key** (¥29–58 + forced thinking, zero new accounts) | 百炼 qwen3.7-flash if T2 shows thinking off; else GLM-5.3-Flash; DeepSeek only if hosting stays overseas long-term |
| D4 | Fail over to the free model when Claude's own USD caps are exhausted (`WD_AI_FAILOVER_ON_BUDGET_CAP`) — turns the caps from "stop" into "degrade" | off |
| D5 | Content written by the fallback: keep forever, or regenerate with Claude when it returns (≈$0.005/word), and whether cards show a 「备用模型生成」 label | keep; admin-only filter to regenerate selectively; no learner-facing label (the existing 「由 AI 生成」 notice covers both) |
| D6 | Fail-back granularity: first successful probe (fast) vs N consecutive successes (anti-flap) | first success + cooldown doubling |
| D7 | Use ModelScope's free DeepSeek-V4.1-Flash (strongest free engine, but 非商业化/非盈利 terms, ≈200/day, churn) as a third slot for an invite-only friends app | no (dev/test only) |
| D8 | Manual admin pause semantics: global (stops both providers) vs primary-only | global |
| D9 | Prepaid balance and 实名 timing on Zhipu/百炼 | ¥50 when the step-up is first needed; 实名 at that moment |
| D10 | Whether to deploy a Managed-scope `modelPricing` file on the VPS so the CLI itself prices the fallback id | no (app-side pricing covers CNY and peak/off-peak) |

---

## 7. Effort summary (person-days, solo part-time developer)

| Package | Person-days | Content |
|---|---|---|
| A0 manual switch (today) | 0.25 | wrapper, key file, scratch-dir tests T0–T5, runbook paragraph |
| Regex patch (ships alone) | 0.25 | `AUTH_RE`/`REGION_RE`/`OVERLOADED_RE`/`NETWORK_RE` + tests |
| A1 **MVP** | **5.5** (incl. the two above) | slots in `runner`, `failover.py`, `common`/`budget`/`ledger` provider scoping, migration 0010, config rename, handler provenance rule, gate helpers, provider endpoint + ledger column + banner, fake modes, unit + integration tests, env.example/install/docs |
| A1 **complete** | **9.5** cumulative (+4.0) | eval harness (CLI subset) and the content gate run, admin segmented control + health card + 7-day share, `wd ai-check --provider`, quality pause, semaphore, budget-cap failover, smoke step, regenerate filter, per-kind model override, doc polish |
| Not included | — | D2 HTTP adapter (contract:F8/F9 ≈ 8–10 d; only if T0 fails or the CLI route breaks), curation migration renumbering in D3 |

---

## 8. Deviations from the fact-base recommendations (deliberate)

1. **Transport.** contract R3 recommends Option B (OpenAI HTTP adapter, 8–10 d) as the automatic path and treats A1 as "only worth building if B is postponed"; the zhipu digest R2 prefers a Python shim over the `ANTHROPIC_BASE_URL` route. D1 deliberately keeps the CLI transport per the orientation ("smallest change that is still automatic"): 5.5 d to automatic failover, one test double, no new HTTP code; every contract degradation that argument rests on is itemised in §2.11 with its neutralisation, and D2 remains the exit.
2. **Free first.** The alibaba digest's R1 picks 百炼 qwen3.7-flash (paid) as fallback #1 and the bytedance digest's R1 picks DeepSeek-flash; the owner asked for the best *free* model first, so GLM-4.7-Flash is primary and qwen3.7-flash is the step-up, DeepSeek third (thinking uncontrollable on the CLI, outage record, training default).
3. **SiliconFlow Qwen3-8B excluded from the automatic chain** (others R1 lists it as the zero-cost emergency tier): 7–9B models' unforced-tool failure modes and `json_object`-only API make it a manual-wrapper option only.
4. **ModelScope excluded** despite having the strongest free engines (alibaba R7 agrees: tier-3 at most) — surfaced as owner decision D7.
5. **Recovery probe cap 2 h, not 4 h** (contract F11): fail-back promptness matters more to the owner than a few probe calls at ≈$0.004 each.
6. **Fallback hourly cap 40, not 60** (F11): a single-concurrency slot with ≈60-s calls cannot physically exceed ≈60/h; 40 leaves room for the immediate retry and the probes under the primary's 60.
7. **Network errors are not a new ledger status** (F11 lists a separate class): `ai_calls.status` is a fixed CHECK (contract:F18), so `NETWORK_RE` maps to `overloaded` with an `error` prefix and its own streak key.
8. **Immediate retry also on soft-trigger switches** (F11 retries only hard triggers): once the decision to switch is made, deferring the group that triggered it only delays a waiting learner by one backoff step for no benefit.
9. **No per-provider flag tier** (verify-contract omission 3 asks for a tier-less probe path for non-CLI providers): both slots are the same binary, so `kv.claude.flag_tier` is shared; the fallback probe writes only `ai.fallback.available/last_probe_at`.
10. **`error_max_structured_output_retries` → `invalid_output`** for both providers (today `error`, contract F6.2 notes the mismatch): it is invalid output by definition and should feed the quality counters, not the backoff-to-dead chain. "`success` without `structured_output`" stays `error` (unchanged).
11. **Manual pause moves to `ai.paused_until`** (global) — F11 proposes the same key; recorded here because it changes `admin_ops.py:327` and a test.
12. **Migration 0010 taken by this design** (`0010_ai_provider.sql`, one column + index); D3's `0010_curation_columns.sql` renumbers to 0011 and drops its `ai_calls.provider` line (verify-contract omission 6).
13. **No schema-file edits** (alibaba R4 suggests adding `additionalProperties:false`): `tests/unit/test_schemas.py:22-23` forbids it and the CLI tool path does not need it; a D2 adapter would transform at call time.
14. **Content allowed on the free model only after the eval gate** (the zhipu digest R5 and contract R2 want an eval but do not gate the kind list); lookups and consolidation are allowed from day one because their validators make a wrong answer cheap.
