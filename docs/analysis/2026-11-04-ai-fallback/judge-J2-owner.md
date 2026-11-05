# Judge J2 — owner effort & operability lens — word-Dance Claude fallback plans D1 / D2 / D3

Date 2026-11-04 · Repo `/Users/sqin/word-dance` @ 9ab13a5 (read-only; nothing tracked modified; `/Users/sqin/word-dance-data` read only) · Judge scratch: `scratchpad/fallback/judge-J2-*` · Lens: a solo part-time developer who wants automatic failover working soon with the least fragility.

## 0. What this judge verified beyond reading

| check | result | consequence |
|---|---|---|
| Who reads the pause keys (`grep paused_until\|ai_enabled\|claude.available` over routers/services/jobs/diag/budget) | `routers/words.py:324`, `routers/bank.py:150`, `jobs/scheduler.py:252`, `services/batches.py:384,498` call `bank.ai_paused_until`; `admin_ops.py:363` calls `budget.paused_until`; direct kv reads only in `services/words.py:422`, `services/bank.py:229`, `budget.py:124`, `diag.py:86-89`, `admin_ops.py:196` (`claude.available`), writes in `admin_ops.py:327/331` | D1's "gates need no edit — they already call the helpers" is **correct**; D3's 2–3 h gate rewrite is over-scoped (helpers + 4 direct sites suffice) |
| `backend/requirements.txt` vs `requirements-dev.txt`; `deploy/install.sh:63` | `httpx==0.28.*` runtime; `jsonschema` only in `requirements-dev.txt:3`; install.sh installs only `requirements.txt` | D2's runtime `jsonschema` validation would `ImportError` on the VPS unless the requirement is added (D3 adds it; D2 does not) |
| `grep -ci json backend/wd/ai/prompts/*.txt` | content 1 · lookup 0 · consolidate 1 · svg 0 | D2's "1/0/1/0" (kind order) is right |
| Live `.env` (`/Users/sqin/word-dance-data/.env:66-72`) | `WD_AI_MODEL="sonnet"`, `WD_AI_FALLBACK_MODEL=""`, `WD_AI_BATCH_SIZE="10"`, `WD_AI_CONCURRENCY="1"` | D2's "value empty → no action on rename" is right; concurrency 1 makes the per-slot semaphore safely deferrable |
| Live wrapper `bin/claude-wrapper` | exports USER/LOGNAME/TMPDIR + privoxy `127.0.0.1:8118`, exec `/opt/homebrew/bin/claude` | D1's fallback wrapper mirrors it correctly (unsets proxies); the primary's Mac path depends on an ssh/SOCKS tunnel |
| `common.claude_call` (`common.py:133-184`), `probe._attempt` (`probe.py:73-88`) | reserve → `run_claude`; probe passes `tier=`, `fallback_on_usage_error=False` | all three hook the right seam |
| `runner.py` | `AUTH_RE/BUDGET_RE/OVERLOADED_RE/USAGE_ERROR_RE` at :71-74, `build_argv` :124, `parse_and_classify` :229, `def run_claude` :383 | D3's ":388-495" is off by five lines (trivial) |
| `db.py:163` `sorted(d.glob("*.sql"))`; migrations dir = 0001, 0008, 0009 | — | 0010 is free for all three |
| `common.py:32-36` | `OVERLOAD_STREAK_KEY="claude.overloaded_streak"`, 6 → 15 min, `AUTH_PAUSE` 30 min | D1/D2/D3 quote today's rule correctly |
| `docs/analysis/2026-11-04-library-curation/judgements.txt:23,81,89` | prior synthesis already chose `WD_AI_PROVIDER=openai_http` + eval harness + `ai_calls.provider` | D2's enum compatibility claim holds; D2 is also the continuation of last week's decision |
| `config.py:113/355` `WD_SVG_VIA_CLAUDE`, `:338-341` `WD_AI_TIMEOUT_*_SEC` | exist | D1's manual A0 recipe uses real keys |
| `frontend/src/i18n/zh.ts:97` `provider: '来源'` | exists (image providers) | D1's label note is right |
| **`scripts/eval_provider.py` (2,085 lines) + `scripts/mock_provider_server.py` (439 lines)** — untracked in the working tree | `--dry-run --per-stage 2` → exit 0, F3-style size table (`judge-J2-dry/dry-run.json`); mock on 127.0.0.1:8765 + `--format openai --strategy json_object --kinds content,lookup --per-stage 1 --batch-size 4` → `scorecard.md` with the F17 gates, `calls.jsonl`, `items.jsonl`, `raw/` (`judge-J2-mock/run/`); supports `--format openai|anthropic|claude_cli`, `--vendor zhipu|bailian|deepseek|ark|siliconflow|modelscope`, `--thinking off`, `--tool-choice forced|auto|any`, `--anthropic-output-field`, `--wrapper`/`--claude-config-dir`, `--paired`, `--compare`, `--gates` | **The harness every plan budgets 6–12 h to build already exists and works offline.** The day-1 go/no-go needs only a key |

## 1. Scores (0–10 per criterion; total /60)

| plan | factual | failover robustness | fallback quality & terms | effort & operability | cost & budget | future-proofing | **total** |
|---|---|---|---|---|---|---|---|
| D1 CLI gateway | 6 | 6 | 7 | 5 | 7 | 4 | **35** |
| D2 OpenAI adapter | 7 | 8 | 8 | 8 | 8 | 7 | **46** |
| D3 Anthropic adapter | 8 | 8 | 7 | 5 | 8 | 9 | **45** |

### Why, under the lens

**D1 (CLI gateway).** The smallest diff, and the only plan with a credible *manual* switch today (A0: wrapper + four `.env` lines + restart) and a crisp kill criterion (T0). But "working soon with the least fragility" fails on fragility: the owner must keep ~20 wrapper env switches, a CLI version floor (≥2.1.288 for `CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS`), `DISABLE_AUTOUPDATER=1` (so security updates become a manual chore), an empty `CLAUDE_CONFIG_DIR` whose effect on the macOS Keychain login is unknown, an unverified `CLAUDE_CODE_EXTRA_BODY` thinking hack, a NaN-cost refusal toggle, a provenance rule that distrusts `modelUsage`, and the documented fact that Anthropic does not support this routing (reported only) — i.e. the request shape may change with any release (2.1.287/288/305 already gated behaviours within months). The fallback shares the binary, Node runtime and login-session environment with the primary, so every CLI-local failure the live history already showed ("Not logged in" from missing USER/LOGNAME/TMPDIR, managed-settings fetch) takes both legs down. Its MVP is automatic, but its own hour table sums to 52 h (6.5 d), not the 44 h/5.5 d headline, and the content eval is a complete-cut item. Diagnosis from the admin page: banner + 来源 column + provider endpoint in the MVP; the segmented control only in the complete cut.

**D2 (OpenAI adapter).** One adapter, three dialects (zhipu/bailian/generic), the free model's one documented JSON mode plus explicit `thinking:{type:"disabled"}`, `jsonschema` on the original schema before the lax pydantic mirrors (closes verify-contract omission 1), a single `availability()` helper plus a grep-test that forbids new direct `claude.paused_until` reads, prewarm excluded from the free leg by default, the live outage replayed minute by minute, and an L1–L6 test ladder that uses the production adapter (`wd worker-once` on a scratch DB) as the gate before `auto`. Nothing on the fallback path depends on the next Claude Code release. Weak points: one leg in the MVP (a Zhipu peak throttle → both down → 503 until the step-up lands in the complete cut), the segmented control and the provider probe button deferred to the complete cut (for a solo operator the manual override is the most-used control), and the missing `jsonschema` runtime requirement. 7 person-days is honest; ≈2 calendar weeks is not (3–4 part-time weeks).

**D3 (Anthropic adapter).** The most complete design: N-slot chain, capability presets for 13 vendors, bounded in-call downgrade with learned caps, single-writer failover, 1308/billing horizons in the MVP, richest admin MVP (segmented control, probe dropdown, providers list), `jsonschema` as a runtime dependency, terms guardrails in config. But for this owner it is the wrong size: 86 h/≈10 person-days (4–5 part-time weeks) before anything is automatic, dynamic `WD_AI_<SLOT>_*` parsing inside a frozen `Settings`, a `providers/claude_cli.py` move in the MVP, presets whose Zhipu cells are "unknown → learned at runtime", and — decisive for the owner's *free* requirement — the free primary fallback is bet on an undocumented path (`glm-4.7-flash` on `/api/anthropic` emitting `tool_use`; verify-others omission 6, verify-zhipu omission 4). If day-1 T1 fails, D3's first leg becomes paid 百炼, because it builds no OpenAI adapter; D2 keeps the free model on its documented endpoint.

**MVP automatic?** All three MVPs are genuinely automatic (switch + immediate retry + probe-based fail-back). None is penalised on that criterion; D1 is penalised because its automation is conditional on T0 and on a transport Anthropic says it does not support.

## 2. Factual errors (plan sentence → contradicting evidence)

**D1**
1. §2.3 / §7: "Totals: **MVP ≈ 44 h ≈ 5.5 person-days; complete ≈ 76 h ≈ 9.5 person-days**". The §2.3 table's M rows sum to 6+8+4+4+2+2+0.5+1.5+2+0.5+1.5+1.5+2+1.5+10+3+2 = **52 h (≈6.5 d)** and the C rows to 31.5 h → **≈83.5 h (≈10.4 d)** complete (design-D1-cli-gateway.md lines 138–157). The headline that carries the pitch is understated by ≈15 %.
2. §2.2 wrapper comment "drop output_config.format + its beta header (CLI >= 2.1.288); **the StructuredOutput tool path remains**" and §1.1 "Claude Code's injected `StructuredOutput` tool call (unforced)". verify-zhipu:F7 (byte scan of the installed 2.1.292 binary): "a tool-based fallback for the **top-level** `-p --json-schema` path is not evidenced by strings in this build; the 'unsupported' latch is" — the docs describe the tool (verify-others:F9), so the fact base is in conflict; D1 cites verify-zhipu:F7 yet presents the mechanism as settled instead of making "structured_output present with the switch set" an explicit T0 pass condition.
3. §2.10 replay: "`probe.check(primary)` = one tier-1 + one tier-0 probe call (≈2 ledger rows, kind `probe`, ≤ $0.10 cap, actual ≈$0.004)" during the managed-settings outage. A probe that fails `auth` records cost 0 (live `ai_calls` 33–47 all `cost_usd` 0; verify-contract:F6 "success without `total_cost_usd` → cost 0.0"); the probe times given (19:43, 20:43, 22:43) also do not follow the plan's own §3.3 rule `PROBE_EVERY_MIN × 2^failures` from 19:13 (→ 20:13, 22:13). Minor.
4. §4.1: "no 实名 needed to call (zhipu:F9; do 实名 only when recharging)". verify-zhipu:F9/omission 5: the FAQ says "目前", the privacy policy reserves 实名 for "API Key 等功能", Batch requires it — D2 and D3 carry the caveat, D1 drops it. Minor.

**D2**
1. §2.3 "validate(kind, obj) runs `jsonschema.Draft202012Validator(load_schema(name))` on the **original** schema" (production code path), but neither §2.10 (deploy) nor §2.11 (file list) adds `jsonschema` to `backend/requirements.txt`; it exists only in `backend/requirements-dev.txt:3`, and `deploy/install.sh:63` runs `pip install -r backend/requirements.txt` only → the adapter raises `ImportError` on a fresh VPS install. (D3 §2.10 adds `jsonschema>=4.26,<5`.)
2. §0 / §7: "After week 1 (≈3 developer-days of the 7-day MVP)" and "MVP … ≈ 2 weeks" calendar for a part-time solo developer: 7 person-days at 2–3 days/week is 3–4 weeks. Calendar optimism rather than a false fact, but it is the number the owner will plan around.

**D3**
1. §2.13 replay: "15 probes … ≈15 × $0.004 = $0.06 of Claude probes". Fourteen of them fail with the managed-settings `auth` error and cost 0 (live rows 33–47, `cost_usd` 0); only the successful probe costs ≈$0.004.
2. §8.3 "in the real outage doubling would have failed back at ≈06:15Z instead of ≈03:15Z" contradicts the plan's own §2.13 timeline, where the first successful probe under its 30/60-min cadence is at 03:45Z (recovery 02:56Z, probe 02:45Z failed).
3. §2.1 "`wd.ai.runner.run_claude` (`runner.py:388-495`)": `def run_claude` is at `runner.py:383` (grep; contract digest and verifier cite 383-495). Trivial.
4. §0 "After week 1 (MVP, ≈10 person-days of work, so realistically week 2 for a part-time solo developer)": 10 person-days part-time is 4–5 weeks, not week 2.
5. §1.2 row 13 (Anthropic Console: Haiku $1/$5, Sonnet 5.5 $2/$10, "Haiku 4.5: omit `thinking` = off") is cited to the claude-api skill and was **not re-verified** here (Anthropic questions deferred by the owner); treat as unverified, not wrong.

## 3. Grafts (concrete ideas from D1 and D3 to carry into the D2 base)

From D3:
1. `jsonschema>=4.26,<5` in `backend/requirements.txt` (D3 §2.10/§2.12) — without it D2 does not run in production.
2. Single-writer rule: `failover.record_failure` owns pauses/streaks/events; `handle_failure` only moves jobs (D3 §2.5, deviation 5) — removes the "which provider's result am I handling" ambiguity after an immediate retry.
3. Zhipu 1308 `quota_window` as a hard trigger paused until `next_flush_time`, and billing/config failures paused 24 h with `available=0` (D3 §3) — in the MVP, so a dead key or an empty balance is not re-hit every 30 minutes.
4. Fail back also on a successful ordinary primary call, not only on the probe (D3 §2.5 `record_success`).
5. Promote the admin segmented control (auto / 仅 Claude / 仅备用) and a provider-aware 探测 button into the MVP (D3 §2.9) — the override is the owner's one manual lever.
6. Preset flags `mainland_only_terms` / `non_commercial` that refuse to load without an acknowledgement or show a banner note (D3 §2.3) — cheap insurance against a later config mistake (Ark from Tokyo, ModelScope in production).
7. Two quality bars — default-fallback vs emergency-only (D3 §4.3) — so a middling scorecard still yields a usable last-resort slot.
8. Record the probe's `model_seen` (D3 §2.4) to notice silent auto-routing when GLM-4.7-Flash is retired.

From D1:
9. Day-0 diagnostic T0: the A0 wrapper + `wd claude-check` against a **scratch** `WD_DATA_DIR` to learn whether Enterprise `forceLoginMethod` blocks token auth and what `modelUsage`/`total_cost_usd` say for an unknown id (D1 §4.1), and the documented 2-minute manual emergency switch (four `.env` lines + restart, with its caveat list: USD caps blind, `WD_SVG_VIA_CLAUDE=0`, batch 5) for the weeks before the MVP ships.
10. Gate `content` behind the scorecard; allow `lookup,consolidate` from day one (`WD_AI_FALLBACK_KINDS=lookup,consolidate`) because their validators make a wrong answer cheap (D1 §1.3).
11. Change only the helpers (`bank.ai_paused_until`, `budget.paused_until`, `services/words.py:422`, `diag.py:86-89`, `admin_ops.py:196`) — verified: the six router/service gates already call them — and keep D2's grep-test forbidding new direct `claude.paused_until` reads.
12. New `fake_claude.py` modes for the primary path (`managed_settings` with the live string, `region_403`, `network`, `rate_429`, `zh_auth`, `structured_retries`) and a `FAKE_CLAUDE_MODEL` knob (D1 §2.3) — D2's drill L5 needs exactly the first one.
13. Key in a 0600 file outside the Python environment and `.env` (D1 §2.4) — make D2's `WD_AI_FALLBACK_API_KEY_FILE` the default on the VPS so the key never reaches `GET /api/admin/config` or logs.
14. The live-outage replay table (D1 §2.10 / D2 §2.12) as the acceptance script of the integration drill.

## 4. Blind spots (none of the three plans covers)

1. **The eval harness and mock server already exist** (`scripts/eval_provider.py` 2,085 lines, `scripts/mock_provider_server.py` 439 lines, untracked; `git status` in the brief lists them). Verified today: `--dry-run` renders the production prompts (exit 0) and a run against the mock writes a scorecard with the F17 go/no-go gates. The harness already speaks `openai`, `anthropic` and `claude_cli --wrapper`, knows the zhipu/bailian/deepseek/ark/siliconflow/modelscope vendors, and has `--thinking off`, `--tool-choice`, `--anthropic-output-field`, `--paired`, `--compare`. All three plans budget 6–12 h to build it and none uses it for the day-1 tests; D1's T1–T3 curl/worker-once recipe and D3's four hand-written curl calls are what the harness does in one command.
2. **No owner notification.** None of the plans wires `ai_failover` / `ai_failback` / both-down to any outbound channel, although `backend/wd/delivery/webhook.py` already delivers to wecom/feishu/serverchan/bark with SSRF-safe posting. A part-time operator does not watch the admin page; the live outage ran 8 h unnoticed, and under any of these designs Claude could stay broken for weeks while the free model quietly serves. ≈0.5 d: enqueue a `send_webhook` job from the failover writer (dedup 1/h) plus a daily "备用模型已运行 N 天" reminder.
3. **Common-mode failure of a CLI-based fallback.** None classifies the live failure causes into CLI-local (Keychain/login-session env → "Not logged in", managed-settings fetch, binary/Node/PATH, auto-update) versus upstream (403 region block, 529). A fallback that re-uses the `claude` binary (D1) shares every CLI-local cause, and on macOS `CLAUDE_CONFIG_DIR` isolation may not hide the Keychain login at all; only an HTTP transport is immune, and neither D2 nor D3 states this as the reason to prefer it.
4. **Interim automation for the 3–5 part-time weeks before any MVP lands.** The bytedance digest's 0.5-day "smart primary wrapper" (the `WD_CLAUDE_BIN` script re-execs `claude` with the fallback env when the first run exits with a hard error) is discussed by none of the plans, even to reject it. Verdict: reject for content (provenance = gateway echo, USD caps blind, no sticky state or fail-back), tolerable only as a lookup/consolidate stop-gap if Claude dies again before the MVP.
5. **The recovery probe stalls the only worker thread.** `probe.check` runs tier 1 then tier 0 (each ≤60 s) inside housekeeping, so with `WD_AI_CONCURRENCY=1` the fallback queue freezes up to ~2 min every 30 min during an outage. D2 notes the stall; nobody pins the probe to one tier (or `flag_tier`) during failover.
6. **No partial automatic step is sequenced.** All three plan "week 1 / week 3" milestones that assume full-time work. A 1–1.5 d first slice — regex patch, provider-scoped pause, `ai.paused_until` for the manual pause, the admin override endpoint and the webhook event — already breaks the 30-min pause loop and gives the owner a button before any adapter exists; none of the plans offers it.
7. **No quality-drift alarm.** Fallback share and `invalid_output` rate exist only as complete-cut tiles (D2/D3); no threshold turns into an event, so a degrading free model is noticed only by learners.

## 5. Recommendation

BASE: D2 (OpenAI-chat adapter + sticky failover): the free model's only documented structured mode (Zhipu json_object, thinking off), no CLI quirks on the fallback path, automatic in ≈7 person-days. D1 inherits every CLI quirk and a kill criterion; D3 needs 10 d first.

ARCH: run_claude façade → claude_cli | openai_http (zhipu/bailian dialects; jsonschema on the ORIGINAL schema, one repair, CNY→USD pricing; jsonschema into requirements.txt); failover.py = single writer of the active provider, provider-scoped pauses, streaks, probe schedule, availability(); budget/ledger/probe take provider; migration 0010 ai_calls.provider; change only the pause helpers; admin MVP = banner, 来源 tile/column, auto/Claude/备用 control, provider probe; failover events → existing webhook delivery.

MODELS: lookup, consolidate → GLM-4.7-Flash (BigModel; batch 5, concurrency 1, timeouts ×1.5) from day 1; content → same after scorecard GO (item pass ≥95 %, headword ≥97 %, p95 ≤162 s), else 百炼 qwen3.7-flash (strict json_schema, enable_thinking=false, ≈¥15/mo) as leg 2; svg none; prewarm never on the free leg.

RULES: hard = auth (incl. managed-settings string), 403, 402/billing, spawn/config, 1308 → pause that provider (30 min; 24 h billing/config; 1308 to next_flush_time), switch sticky, retry the same claimed group once; soft = 3 overloaded / 2 timeouts / 2 network; never = invalid_output, error, content_filter, budget; 3 invalid on fallback → 30-min quality pause; probe every 30 min (60 after 6 h), fail back on first probe or primary success; learner gates = any provider available.

SCOPE: MVP ≈7.5 person-days (≈3–4 part-time weeks): regex patch → adapter+fake_openai → failover/budget/ledger/0010 → helpers/probe/admin/webhook → tests → live; complete +4 d (leg 2, semaphore, regenerate filter, smoke).

TESTS: (0) Zhipu standard key + the EXISTING scripts/eval_provider.py --format openai --vendor zhipu --model glm-4.7-flash --strategy json_object --thinking off --paired, Mac then VPS (¥0) — decides content; (1) wd ai-check --provider fallback; (2) drill: fake_claude auth wrapper + real adapter → auth/success rows, ai_failover, probe → ai_failback; (3) one-night soak; optional D1 A0 claude-check (forceLoginMethod).

DECISIONS: BigModel vs Z.ai; 实名 now; open 百炼 only for leg 2 (用完即停 on); content on free model after GO; prewarm/svg off on fallback; budget-cap failover off; keep fallback cards + regenerate filter; manual pause global; key in 0600 file; webhook channel.


## 6. Evidence index

- Fact base: `scratchpad/fallback/facts/*.md`, `scratchpad/fallback/verify/*.md` (verifications override digests).
- Plans: `design-D1-cli-gateway.md`, `design-D2-openai-adapter.md`, `design-D3-anthropic-adapter.md`.
- Judge runs: `judge-J2-dry/` (harness `--dry-run`, exit 0), `judge-J2-mock/` (mock server log + `run/scorecard.md`, `calls.jsonl`, `items.jsonl`), `judge-J2-rec.txt` (recommendation, ≤2,500 chars).
- Repo greps quoted in §0 (read-only): `backend/wd/{routers,services,jobs,ai}`, `backend/requirements*.txt`, `deploy/install.sh:63`, `backend/wd/db.py:163`, `backend/wd/ai/common.py:32-36`, `backend/wd/ai/runner.py:71-74,124,229,383`, `frontend/src/i18n/zh.ts:97`, `docs/analysis/2026-11-04-library-curation/judgements.txt`.
- Live data (read-only): `/Users/sqin/word-dance-data/.env:66-72`, `/Users/sqin/word-dance-data/bin/claude-wrapper`.
