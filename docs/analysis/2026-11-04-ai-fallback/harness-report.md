# Eval harness (contract §F17) — implementation report

Date 2026-11-04 · Repo `/Users/sqin/word-dance` @ `9ab13a5` (no tracked file modified; `git status` shows only the two new untracked scripts plus the pre-existing untracked docs) · Scratch `…/scratchpad/fallback/harness-runs/` (all run outputs) · Mock port 8765 (started for the verification, stopped afterwards) · The real `claude`, `/Users/sqin/word-dance-data` and port 8000 were never touched (the harness opens the DB copy `mode=ro` and the data-dir path appears in neither script).

Deliverables

| file | lines | role |
|---|---|---|
| `/Users/sqin/word-dance/scripts/eval_provider.py` | 2,085 | the harness (F17 CLI, three transports, validation chain, scorecard, compare) |
| `/Users/sqin/word-dance/scripts/mock_provider_server.py` | 439 | stdlib mock provider (OpenAI + Anthropic shapes, 15 modes, importable `respond()` / `transport()`) |
| `…/scratchpad/fallback/harness-runs/` | — | 31 run directories (219 `raw/<n>.json`), logs, `summ.py`, `cli-wrappers/`, `prices-flashx.json` |

Both files pass `.venv/bin/python -m py_compile`. Stdlib + `httpx 0.28.1` + `jsonschema 4.26.0` (imported lazily with a clear error) + `pydantic 2.14.2` through `wd.ai.models`; Python 3.12.16 (`.venv`).

---

## 1. Usage

```
PY=/Users/sqin/word-dance/.venv/bin/python
DB=/private/tmp/claude-501/-Users-sqin-word-dance/729429d5-a7a1-4def-84e7-dc3ba571c437/scratchpad/quick/live-copy.db   # or $WD_DATA_DIR/word-dance.db

# prompt-size table only (no network; renders the real prompts under <out>/prompts/)
$PY scripts/eval_provider.py --db $DB --dry-run --paired --kinds content,lookup,consolidate,svg,probe --out ~/eval/dry

# mock (CI): start, run, assert GO on the structural gates (exit 0), stop
$PY scripts/mock_provider_server.py --port 8765 &
$PY scripts/eval_provider.py --db $DB --mock http://127.0.0.1:8765/v1 --format openai --strategy json_object --paired --gates structural --out ~/eval/mock-ok
MOCK_MODE=429 … or per request: --mock-mode 429 | zh_401 | truncated | slow:3 …

# merge scorecards
$PY scripts/eval_provider.py --compare ~/eval/run-a ~/eval/run-b
```

Flags (all in `--help`): `--db · --format openai|anthropic|claude_cli · --base-url · --mock URL · --mock-mode · --api-key-env NAME · --model · --strategy json_schema|json_object|tool|cli · --kinds · --per-stage 10 · --extra phrases=3,abbreviation=3,proper_noun=2 · --words a,b · --paired · --batch-size 10 · --lookup-batch-size 20 · --lookup-set FILE · --consolidate synth:80|user:<name> · --consolidate-headwords 300 · --svg-count 5 · --max-output-tokens 8192 · --consolidate-max-output-tokens 12288 · --max-tokens-field · --timeout-scale 1.0 · --concurrency 1 · --repair 1 · --price-json · --cny-per-usd 7.0 · --vendor zhipu|bailian|deepseek|siliconflow|modelscope|ark|generic · --thinking off|on|default · --temperature · --extra-body JSON · --tool-choice forced|auto|any · --no-strict · --anthropic-strict · --anthropic-output-field output_config|output_format|none · --auth-header both|x-api-key|bearer · --trust-env · --wrapper · --tier · --claude-config-dir · --seed · --gates all|structural · --label · --out · --dry-run · --compare DIR…`

Outputs under `--out`: `scorecard.md` + `scorecard.json` (one table per kind, go/no-go lines, verdict), `calls.jsonl` (one row per request: provider, host, model, kind, strategy, batch size, latency, timeout, http status, exception, status, reason, finish_reason, tokens, cost CNY/USD, CLI cost estimate, fenced flag, repair flags, error excerpt, `Retry-After`, raw path), `items.jsonl` (one row per expected item: key, verdict, reasons, item JSON, the paired Sonnet item under `--paired`), `raw/<n>.json` (sanitised request — no auth headers — plus response), `prompts/` (dry run), `wd-data/claude-cwd` (empty cwd for the CLI spawn). Exit code 0 = GO, 2 = NO-GO.

Side-by-side review of fallback vs Sonnet content: `jq -c 'select(.paired) | {key, passed, reasons, new: .item.meaning_zh, sonnet: .paired.meaning_zh}' items.jsonl`.

## 2. Design decisions (and deliberate deviations)

1. **Production code is the oracle, imported read-only.** Prompts: `content.prompt_entry/build_user_prompt`, `lookup.build_user_prompt`, `consolidate.prompt_item/fit_prompt/select_items/bank_headwords/last_run_started/input_display`, `svg.prompt_for`, `probe.PROBE_PROMPT/PROBE_SYSTEM_PROMPT/EXPECTED`, `runner.load_prompt/load_schema/schema_arg/fold_system_prompt/build_argv/claude_env/parse_and_classify`; timeouts and per-kind `--max-budget-usd` from `budget.timeout_for/budget_for` with a `Settings.from_env` built from an explicit dict whose data dir is `<out>/wd-data` (contract:F1, verify-contract F17). Nothing that writes (`apply_item`, `store_content`, `activate_svg`, `probe.check`) is called.
2. **Validation order follows the verifier's finding on lax coercion** (verify-contract, omission 1): `jsonschema.Draft202012Validator` on the **original** on-disk schema first (per-item errors attributed through `absolute_path`), then the pydantic mirror per item (`models.ContentItem/LookupItem/ConsolidateItem`, output mirrors for svg/probe), then the kind-specific post-validation with the real functions: `content.validate_item(item, word, words.forms_of(conn, id), last_attempt=False)` (contract:F4), `words.validate_headword` for lookup headwords, `common.validate_target` for consolidate targets, `images.clean_svg` (the sanitiser behind `activate_svg`), exact equality with `probe.EXPECTED`.
3. **Schemas are transformed only at call time** (tests forbid touching the files — contract:F18(5)): `additionalProperties:false` on every object for `json_schema`/`tool` (OpenAI strict rule; 百炼's Anthropic `output_config` requires it — alibaba verify F3/F4); `--anthropic-strict` additionally moves `maxItems` and `minItems>1` into descriptions (Anthropic-proper limits, contract:F2). `json_object` sends no schema field but appends the compact schema to the system prompt with the word "JSON" (DeepSeek/百炼 requirement, contract:F2); on the Anthropic format `json_object` is prompt-only.
4. **Tool strategy**: `submit` function/tool with the transformed schema; `tool_choice` forced by default, `--tool-choice auto` (+ an instruction sentence) for Zhipu, whose API supports `auto` only (zhipu:F5), `any` for Kimi. DeepSeek needs thinking off before a forced tool (bytedance verify F4) — `--thinking off` is the default.
5. **Thinking is switched off by default through vendor presets** (`--vendor`): `thinking:{type:disabled}` for Zhipu/DeepSeek/Ark, `enable_thinking:false` for 百炼 compatible-mode/SiliconFlow/ModelScope, `thinking:{type:disabled}` on every Anthropic-format endpoint (百炼 lists qwen3.7-flash as thinking-ON by default and bills thinking as output — alibaba verify omission 1). `--extra-body` merges any vendor-specific field; `--thinking default` sends nothing.
6. **Status mapping** (the §6.3 vocabulary, closing the regex gaps listed in contract:F6.6/F11): exceptions → `timeout` (Read/Connect/Pool timeouts) or `overloaded` (`network:<Exc>`); 401 → `auth/unauthorized`; 402 or `insufficient balance|余额不足|欠费|Arrearage|1113` on 400/402/403/429 → `auth/balance`; 403 → `auth/forbidden` (or `auth/quota` for `AllocationQuota|free tier|1308`); 404 → `spawn_error` (model id / path); 429 → `overloaded/rate_limit` (or `windowed_cap` for Zhipu 1308); 5xx/529 → `overloaded`; 400 with `data_inspection|content_filter|1301|敏感` → `error/content_filter`, other 400 → `error/bad_request`; 200 with `finish_reason length|max_tokens` → `invalid_output/truncated`; empty content → `invalid_output/empty_content`; unparsable → `invalid_output/invalid_json`; schema/mirror failures → `invalid_output/schema|mirror`. The CLI path takes `runner.parse_and_classify`'s status verbatim.
7. **Repair** (`--repair 1`): one fresh single-turn re-ask whose user prompt carries the original prompt, the previous attempt and the validator's messages; triggered for `invalid_json`, `schema`, `mirror`, `empty_content`, never for truncation (F8: `length` is `invalid_output`, not retried) or transport errors. *Deviation* from a multi-turn tool replay: simpler and identical across the three transports; counted separately (`repairs / repairs_succeeded`, `is_repair`, `repair_of`).
8. **Metrics and gates are F17's**: schema-valid rate (per call), mirror-valid rate (per present item), item pass rate, reason histogram, headword-present rate per example, usable-example histogram, zh CJK ratio, en ASCII ratio, field lengths p50/p95/max vs soft caps 80/160/60/30 and the hard caps 120/200/100/60, latency p50/p95/max vs the kind's timeout, tokens, cost (CNY from `--price-json`, USD at `--cny-per-usd`; the CLI's `total_cost_usd` kept separately because it is a client-side estimate with `costBasis` unknown for foreign ids — others-and-cli:F11), invalid/fenced/empty/truncated counts, HTTP→status histogram, lookup agreement per field (is_english, kind, headword set, suggestion), invalid detection, headword accepted by `validate_headword`, consolidate coverage / unknown-id / downgraded-target / confusable-group / difficulty-tag validity, SVG sanitiser pass rate and size. Gates: schema ≥ 98 %, items ≥ 95 %, headword ≥ 97 %, ≥ 3 examples ≥ 95 %, p95 ≤ 0.6 × timeout, truncation 0, lookup agreement ≥ 90 %; `--gates structural` drops the agreement gate (for the mock, whose lookup answers are deliberately naive).
9. **Lookup set**: 40 built-in strings (inflections, misspellings, phrases, abbreviations, proper nouns, gibberish, an injection sentence, spelling variants) with accepted-answer sets; every string passes `words.normalise_input`. *Deviation*: no CJK strings — `normalise_input` rejects them (`REASON_NOT_ENGLISH`), so they can never reach the lookup job.
10. **Sampling**: seeded (`--seed`) random per stage among `is_public=1 AND is_valid_english=1 AND merged_into_word_id IS NULL AND content_state IN ('none','failed')`, plain words per stage without repeats, extras by kind; `--paired` adds the 48 words with active Claude content (their stored item travels into `items.jsonl` as `paired`); `--words` adds explicit lemmas. Consolidate `synth:<n>` builds `prompt_item` rows from seed words (one in three typed as a real `word_forms` inflection, one in four with a note) plus a `bank_headwords` list; `user:<name>` uses the production selection (`select_items` since the user's last finished run).
11. **Safety**: DB via `sqlite3.connect("file:…?mode=ro", uri=True)` + `PRAGMA query_only=1`, one connection shared behind an `RLock`; `--db` is required unless `WD_DATA_DIR` is exported; keys only through `--api-key-env` (never printed, never in `raw/`); `httpx` runs with `trust_env=False` unless `--trust-env` (the shell's `HTTP(S)_PROXY` would route domestic endpoints through the US exit); `claude_cli` requires `--wrapper`, refuses anything that resolves into `/opt/homebrew/bin/claude`, `/Caskroom/claude-code/` or `/usr/local/bin/claude`, runs with the production env allow-list (`runner.claude_env`) plus a login-free `CLAUDE_CONFIG_DIR` under `--out` (contract:F6.5), passes the key as `ANTHROPIC_AUTH_TOKEN` (already in `PASSTHROUGH_ENV`) and the base URL as `ANTHROPIC_BASE_URL`, uses `--model <vendor id>` in the exact `build_argv` argv, kills the process group on timeout exactly like the runner.
12. `--compare` prints a Markdown table of the key metrics across run directories (reads each `scorecard.json`) rather than writing a merged file.

## 3. Mock server

`scripts/mock_provider_server.py` binds 127.0.0.1 only. Endpoints `POST /v1/chat/completions`, `POST /v1/messages`, `POST /anthropic/v1/messages`, `GET /health`, `GET /v1/models`. The kind is inferred from the schema carried by the request (`response_format.json_schema`, `tools[0]`, `output_config.format` / `output_format`) and otherwise from the prompt text; items come from `backend/tests/fake_claude.py` (`structured_output`, `content_item`, `lookup_item`, `consolidate_item`, `svg_output`, `PROBE_ANSWER`) for the words / strings / ids parsed from the prompt's `<items>` block. OpenAI responses carry `usage.prompt_tokens/completion_tokens`, `finish_reason` (`stop` · `tool_calls` · `length`), `tool_calls[0].function.arguments` when tools were sent; Anthropic responses carry `usage.input_tokens/output_tokens`, `stop_reason` (`end_turn` · `tool_use` · `max_tokens`), a `tool_use` block with `input` when tools were sent (a text block instead under `invalid_json`/`fenced_json`/`truncated`/`empty_content`, i.e. "the model did not call the tool"). Modes by `X-Mock-Mode` header, then `MOCK_MODE`, then `--mode`: `ok · fenced_json · invalid_json · schema_mismatch · partial · truncated · empty_content · slow:<s> · 401 · zh_401 · 402 · 403 · 429 (+Retry-After: 2) · 503 · content_filter (400 data_inspection_failed)`, with vendor-shaped bodies (OpenAI `invalid_api_key`, Zhipu `令牌已过期或验证不正确` and code 1302, DeepSeek `Insufficient Balance`, 百炼 `invalid api-key` `authentication_error`, Anthropic `{"type":"error",…}` envelopes). `respond()` is pure and `transport()` wraps it as an `httpx.MockTransport` for unit tests.

## 4. What ran, exactly, and the results

Database: the read-only copy `scratchpad/quick/live-copy.db` (9,162 words; 48 with active Sonnet content; user `sqin` with 13 bank rows). Mock: `mock_provider_server.py --port 8765 --quiet` (log `harness-runs/mock-8765.log`).

**Dry run** (`--dry-run --paired --kinds content,lookup,consolidate,svg,probe`, `harness-runs/dry-run/`): 96 sampled words (zk 10, gk 10, cet4 10, cet6 10, phrase 3, abbreviation 3, proper_noun 2, paired 48) → 10 content calls (system 2,993 B, user avg/max 1,549/1,756 B, schema 1,740 B, folded ≤ 4,794 B, tier-0 argv ≤ 6,651 B, ≈2.2k prompt tokens, 8,192 max tokens, 180 s), 2 lookup calls (1,809 / 296–301 / 1,814 B, 120 s), 1 consolidate call (80 items + 300 headwords: user 13,591 B, folded 15,641 B, ≈5.7k tokens, 12,288 max tokens, 240 s), 5 svg calls (788 / 123–202 / 212 B, 120 s), 1 probe (183 / 149 / 320 B, 60 s) — consistent with the F3 measurements.

**Ok mode, six format × strategy runs** (same 96-word sample, `--paired`, all five kinds; `harness-runs/ok-<format>-<strategy>/`), final code:

| run | content schema / items / headword / ≥3 ex | lookup schema / items / agreement | consolidate schema / items / coverage | svg schema / items / sanitiser | probe | verdict (`--gates all`) |
|---|---|---|---|---|---|---|
| openai json_object | 100 % / 96/96 / 100 % of 384 examples / 100 % | 100 % / 40/40 / 76.0 % | 100 % / 80/80 / 100 % | 100 % / 5/5 / 100 % | exact | NO-GO (agreement only) |
| openai json_schema | same | same | same | same | exact | NO-GO (agreement only) |
| openai tool (forced, `finish_reason=tool_calls`) | same | same | same | same | exact | NO-GO (agreement only) |
| anthropic json_object | same | same | same | same | exact | NO-GO (agreement only) |
| anthropic json_schema `--anthropic-strict` (`output_config.format`) | same | same | same | same | exact | NO-GO (agreement only) |
| anthropic tool via `/anthropic/v1/messages` (`stop_reason=tool_use`) | same | same | same | same | exact | NO-GO (agreement only) |
| openai json_object `--gates structural --concurrency 3` | same | same | same | same | exact | **GO, exit 0** |

Every call was schema-valid against the original schema, mirror-valid, 0 truncation, 0 fenced, 0 repairs; latency p95 0.3–4.4 ms. The 76 % lookup agreement is the mock's naive dictionary (everything `is_english=true`, headword = input lower-cased, no suggestions: is_english 28/33, kind 24/30, headword 21/28, suggested 0/5) and is exactly what the agreement gate is meant to catch; the structural gates pass. The sampled content items use the fake's fixed sentences, so the CJK ratio of zh fields is 68 % (short mixed strings), lengths p95 27/56/20/19 vs caps 80/160/60/30.

**Error modes, one run each** (4-word sample, kinds content,lookup,svg → 4 requests; `harness-runs/err-<mode>/`; "→" is the harness status/reason written to `calls.jsonl`):

| mode (format) | observed | → status / reason | repair |
|---|---|---|---|
| fenced_json (openai) | HTTP 200, ```json fence | success; `fenced_json_calls` 1/2/1 | — |
| invalid_json (anthropic) | 200, garbage text | invalid_output / invalid_json | re-asked once, still invalid → `repaired_ok=false` |
| schema_mismatch (openai json_schema) | 200, required key missing | invalid_output / schema (items: `schema: 'meaning_zh' is a required property`) | re-asked once, still invalid |
| partial (anthropic tool) | 200, last item missing | success; items 3/4 and 38/40 with reason `missing` (content pass 75 % → gate fails) | — |
| truncated (openai) | 200, `finish_reason=length` | invalid_output / truncated; `truncated_calls` 1/2/1, truncation gate fails | none by design |
| slow:3 with `--timeout-scale 0.01` (anthropic) | no response within 1.8 / 1.2 / 1.2 s | timeout / ReadTimeout (latency 1,803 / 1,204 / 1,203 ms) | — |
| 401 (openai `invalid_api_key`) | 401 | auth / unauthorized | — |
| zh_401 (anthropic, `令牌已过期或验证不正确`, via `/anthropic` prefix) | 401 | auth / unauthorized | — |
| 402 (openai `Insufficient Balance`) | 402 | auth / balance | — |
| 403 (anthropic, 百炼 `invalid api-key` body) | 403 | auth / forbidden | — |
| 429 (openai, Zhipu code 1302) | 429, `Retry-After: 2` | overloaded / rate_limit; `retry_after=2` recorded | — |
| 503 (anthropic `overloaded_error`) | 503 | overloaded / http_503 | — |
| content_filter (openai `data_inspection_failed`) | 400 | error / content_filter | — |
| empty_content (anthropic) | 200, empty text | invalid_output / empty_content | re-asked once, still empty |

**claude_cli path** through wrapper scripts that exec `backend/tests/fake_claude.py -I` (`harness-runs/cli-wrappers/fake-<mode>.sh`; the real binary was never run):

| wrapper mode | kinds | result |
|---|---|---|
| ok (`--price-json prices-flashx.json`) | content (9 words), lookup ×2, consolidate (80), svg, probe | 100 % schema / items on every kind; argv = production tier-0 argv (`-p … --output-format json --json-schema … --tools "" --no-session-persistence --model sonnet --max-budget-usd 0.25`), child env keys exactly `CLAUDE_CONFIG_DIR HOME LANG LC_ALL NO_COLOR PATH TERM TZ`, cwd `<out>/wd-data/claude-cwd`; cost CNY from the price file (¥0.0089 content) next to the CLI's own `total_cost_usd` estimate ($0.036) |
| auth | content, probe | auth (`Not logged in. Please run claude login`) |
| overloaded | content, probe | overloaded (`API overloaded (529)`) |
| budget | content, probe | budget / `error_max_budget_usd` |
| invalid_json | content, probe | error (`unparseable stdout`, as `parse_and_classify` says) |
| timeout, `--timeout-scale 0.03` | probe | timeout after 2 s, process group killed, no stray `fake_claude` process |
| usage_error, `--tier 1` | probe | error (`unknown option '--system-prompt'`) — the harness does not re-run tier 0 (production does; see limitations) |

**Refusals** (all before any network/spawn): `--wrapper /opt/homebrew/bin/claude` → "refusing to run /opt/homebrew/Caskroom/claude-code/2.1.292/claude"; `--format claude_cli` without `--wrapper`; no `--db` and no `WD_DATA_DIR`; a real `--base-url` without `--api-key-env`; an empty key variable. `pgrep` confirmed no `claude`/`fake_claude` processes afterwards.

**Other paths**: `--consolidate user:sqin --words "abandon,ability,take off" --per-stage 0 --price-json … --cny-per-usd 7.2` → 3 real pending bank rows (ids 42/48/51, 13 headwords, 605-byte prompt) and 2 explicit words, GO, cost ¥0.0031 / $0.0004 for the content call. `--compare` over eight directories prints the merged table (in `harness-runs/`, see the run logs). The DB copy's mtime and the zero-byte `-wal` are unchanged.

## 5. Known limitations

1. **No real provider was called** (no key, no spend). Vendor-specific request quirks are therefore unverified: whether Zhipu rejects `strict:true` inside a function (use `--no-strict`), the exact `enable_thinking` placement on 百炼's compatible mode (the preset follows the docs; `--extra-body` overrides), Ark's `output_format` shape (`--anthropic-output-field output_format`), SiliconFlow's free-model coverage on `/v1/messages`, and whether `glm-4.7-flash` is served on `/api/anthropic` at all (others-and-cli verify omission 6). The first real call should be `--kinds probe`.
2. The mock's items are the test double's fixed sentences: it proves plumbing, schema handling and status mapping, not model quality; its lookup answers fail the agreement gate by design (76 %), hence `--gates structural` for CI.
3. Repair is a single-turn re-ask, not a multi-turn tool replay; the CLI path does not reproduce the runner's tier-1 → tier-0 retry on `usage_error` (run `--tier 0`, the verified tier, unless testing tier 1 on purpose).
4. The harness never applies handler side effects, so it cannot measure outcomes that depend on DB state changes (merges, suggestions); it measures what the handlers would accept. Content items are validated with `last_attempt=False` (≥ 3 examples), the stricter branch.
5. Cost needs a price file; it has no peak/off-peak schedule (pass the applicable DeepSeek price), and the CLI's `total_cost_usd` is reported only as the client-side estimate it is. Token estimates in `--dry-run` are byte heuristics (≈3 B/token prompts, ≈2.6 B/token outputs, F3 calibration).
6. One SQLite connection shared behind a lock: fine for `--concurrency ≤ 3`; the free tiers want 1 anyway. The p95 gate scales with `--timeout-scale` (a 1.5× scale loosens the gate proportionally — compare runs with the same scale).
7. `jsonschema` validates with Draft 2020-12 while the CLI validates with draft-07; identical for the keyword subset the five schemas use.
8. The SVG sanitiser needs `defusedxml` (present in the venv); without it svg items are reported, not scored.

## 6. Commands for the owner (real keys; nothing else changes)

Keys go into the environment, never on the command line. Costs: a full `--paired` run is ≈ 18 requests (10 content + 2 lookup + 1 consolidate + 5 svg) ≈ 60k output tokens — ¥0 on GLM-4.7-Flash, ≈ ¥0.2 on GLM-4.7-FlashX, ≈ ¥0.05 on qwen3.7-flash; at one in-flight request on the free tier expect 10–15 minutes.

```bash
cd /Users/sqin/word-dance
PY=.venv/bin/python
DB=/private/tmp/claude-501/-Users-sqin-word-dance/729429d5-a7a1-4def-84e7-dc3ba571c437/scratchpad/quick/live-copy.db   # a copy; $WD_DATA_DIR/word-dance.db is also fine (read-only open)
mkdir -p ~/eval/prices
echo '{"input": 0.5, "output": 3.0, "cache_read": 0.1}' > ~/eval/prices/glm-4.7-flashx.json      # 元/百万 tokens, docs.bigmodel.cn pricing 2026-11-04
echo '{"input": 0.2, "output": 0.8}'                    > ~/eval/prices/qwen3.7-flash.json        # ≤32K input tier, help.aliyun.com model-pricing 2026-11-04
echo '{"input": 0.8, "output": 2.7}'                    > ~/eval/prices/qwen3.8-flash.json

# ---- Zhipu GLM-4.7-Flash (free; OpenAI-compatible; json_object is its only structured mode; tool_choice auto only)
export ZHIPU_API_KEY='…'
$PY scripts/eval_provider.py --db $DB --format openai --base-url https://open.bigmodel.cn/api/paas/v4 --model glm-4.7-flash \
    --vendor zhipu --api-key-env ZHIPU_API_KEY --kinds probe --out ~/eval/zhipu-probe              # first: auth + model id + schema handling, ~0 tokens
$PY scripts/eval_provider.py --db $DB --format openai --base-url https://open.bigmodel.cn/api/paas/v4 --model glm-4.7-flash \
    --strategy json_object --vendor zhipu --api-key-env ZHIPU_API_KEY --paired --batch-size 5 --timeout-scale 1.5 --concurrency 1 \
    --out ~/eval/zhipu-glm47flash-json_object
$PY scripts/eval_provider.py --db $DB --format openai --base-url https://open.bigmodel.cn/api/paas/v4 --model glm-4.7-flash \
    --strategy tool --tool-choice auto --no-strict --vendor zhipu --api-key-env ZHIPU_API_KEY --paired --batch-size 5 --timeout-scale 1.5 \
    --out ~/eval/zhipu-glm47flash-tool
# Anthropic-format endpoint of the same key (model coverage undocumented → probe first)
$PY scripts/eval_provider.py --db $DB --format anthropic --base-url https://open.bigmodel.cn/api/anthropic --model glm-4.7-flash \
    --strategy tool --tool-choice auto --vendor zhipu --api-key-env ZHIPU_API_KEY --kinds probe --out ~/eval/zhipu-anthropic-probe
# paid step-up on the same account (¥0.5/¥3 per 1M): higher concurrency tier, same prompts
$PY scripts/eval_provider.py --db $DB --format openai --base-url https://open.bigmodel.cn/api/paas/v4 --model glm-4.7-flashx \
    --strategy json_object --vendor zhipu --api-key-env ZHIPU_API_KEY --paired --batch-size 10 --price-json ~/eval/prices/glm-4.7-flashx.json \
    --out ~/eval/zhipu-glm47flashx-json_object

# ---- 百炼 qwen3.7-flash (pay-as-you-go key; strict json_schema; thinking must be off → --vendor bailian)
export BAILIAN_API_KEY='…'
$PY scripts/eval_provider.py --db $DB --format openai --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3.7-flash \
    --vendor bailian --api-key-env BAILIAN_API_KEY --kinds probe --out ~/eval/bailian-probe
$PY scripts/eval_provider.py --db $DB --format openai --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3.7-flash \
    --strategy json_schema --vendor bailian --api-key-env BAILIAN_API_KEY --paired --price-json ~/eval/prices/qwen3.7-flash.json \
    --out ~/eval/bailian-qwen37flash-json_schema
# the same through 百炼's Anthropic-format endpoint (workspace host; the legacy dashscope host is feature-frozen since 2026-09-30)
$PY scripts/eval_provider.py --db $DB --format anthropic --base-url https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/apps/anthropic --model qwen3.7-flash \
    --strategy json_schema --vendor bailian --api-key-env BAILIAN_API_KEY --paired --price-json ~/eval/prices/qwen3.7-flash.json \
    --out ~/eval/bailian-qwen37flash-anthropic
# quality step-up
$PY scripts/eval_provider.py --db $DB --format openai --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3.8-flash \
    --strategy json_schema --vendor bailian --api-key-env BAILIAN_API_KEY --paired --price-json ~/eval/prices/qwen3.8-flash.json \
    --out ~/eval/bailian-qwen38flash-json_schema

# ---- decide
$PY scripts/eval_provider.py --compare ~/eval/zhipu-glm47flash-json_object ~/eval/zhipu-glm47flash-tool ~/eval/zhipu-glm47flashx-json_object \
    ~/eval/bailian-qwen37flash-json_schema ~/eval/bailian-qwen37flash-anthropic ~/eval/bailian-qwen38flash-json_schema
jq -c 'select(.paired) | {key, passed, reasons, new: .item.meaning_zh, sonnet: .paired.meaning_zh}' ~/eval/zhipu-glm47flash-json_object/items.jsonl | head -48
```

Optional, only after the Enterprise managed-settings question is settled (`forceLoginMethod` blocks token auth — verify-contract omission 5): the CLI route with a wrapper that execs the real binary. The harness builds the exact production argv and passes `--model <vendor id>`; the wrapper must export the Claude Code switches the runner's allow-list drops:

```bash
cat > ~/eval/bin/claude-zhipu <<'EOF'
#!/bin/sh
export ANTHROPIC_DEFAULT_SONNET_MODEL=glm-4.7-flash ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-4.7-flash ANTHROPIC_DEFAULT_OPUS_MODEL=glm-4.7-flash
export CLAUDE_CODE_DISABLE_STRUCTURED_OUTPUTS=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1
export MAX_THINKING_TOKENS=0 CLAUDE_CODE_MAX_CONTEXT_TOKENS=200000 API_TIMEOUT_MS=600000
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
exec /opt/homebrew/bin/claude "$@"
EOF
chmod +x ~/eval/bin/claude-zhipu
$PY scripts/eval_provider.py --db $DB --format claude_cli --wrapper ~/eval/bin/claude-zhipu --base-url https://open.bigmodel.cn/api/anthropic \
    --model glm-4.7-flash --api-key-env ZHIPU_API_KEY --kinds probe --out ~/eval/zhipu-cli-probe
```
(`ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` are injected by the harness through the runner's pass-through list; the wrapper runs under a fresh `CLAUDE_CONFIG_DIR` beneath `--out`, so no saved login is involved. Expect `total_cost_usd` 0/unknown for the GLM id; the price file is the real cost.)

Mock CI recipe: `$PY scripts/mock_provider_server.py --port 8765 & $PY scripts/eval_provider.py --db $DB --mock http://127.0.0.1:8765/v1 --paired --gates structural --out /tmp/eval-ci && echo GO; kill %1` (exit 0 ⇔ 100 % structural pass).
