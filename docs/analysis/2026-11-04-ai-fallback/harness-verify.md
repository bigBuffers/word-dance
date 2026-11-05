# Eval-harness verification — independent re-run of `scripts/eval_provider.py` + `scripts/mock_provider_server.py`

Date 2026-11-04 · Repo `/Users/sqin/word-dance` @ `9ab13a5` · Verifier scratch `scratchpad/fallback/harness-verify/` (126 entries, 6.1 MB; every command's log is next to its output dir) · Mock on **127.0.0.1:8770** (pid 43997, 252 requests served, stopped at the end; port free, no stray `mock_provider_server`/`fake_claude`/`eval_provider` processes) · Python `.venv` 3.12.16, httpx 0.28.1, jsonschema 4.26.0, pydantic 2.14.2, defusedxml 0.7.1.

Hard rules kept: the real `claude` was never run (all `claude_cli` runs go through the pre-existing `harness-runs/cli-wrappers/fake-*.sh`, all seven of which `exec` `backend/tests/fake_claude.py -I` and none mentions the Homebrew binary); no money; `/Users/sqin/word-dance-data` never opened (all 55 `scorecard.json` files carry `meta.db = …/scratchpad/quick/live-copy.db`; 0 outputs mention the live path; every run used `env -u WD_DATA_DIR` plus `--db`); tracked files untouched (`git status --short` before and after shows only the six pre-existing untracked entries, `git diff --stat` empty).

**Verdict: pass_with_fixes.** The harness does what `harness-report.md` says on every point I could execute; two small `claude_cli` path-handling defects were found and fixed in the untracked script (§5); the remaining findings are recommendations, not blockers.

---

## 1. Safety properties (read in the code, then observed)

| property | code | observed |
|---|---|---|
| DB opened read-only | `eval_provider.py:305-313` `sqlite3.connect("file:…?mode=ro", uri=True)` + `PRAGMA query_only = 1`; one connection behind `DB_LOCK` (`:316`); the helpers it calls (`words.word_row/forms_of/validate_headword`, `common.validate_target`, `consolidate.select_items/bank_headwords/last_run_started`, `svg.prompt_for`) contain no write statements; a write attempt would raise under `query_only` anyway | `live-copy.db` sha256 `8441ba61…480371` identical before and after 55 runs, mtime unchanged (19:07:39), `-wal` still 0 B. The `-shm` file's mtime moves (23:52) because the copy is in WAL mode and SQLite maps the shared-memory index even for `mode=ro` readers — no content effect. |
| no default to the live Mac data dir | `resolve_db` (`:1955-1961`) needs `--db`, else `$WD_DATA_DIR/word-dance.db` only when that variable is exported (per F17 spec), else exits "never guesses the live data dir"; `grep word-dance-data` over both scripts → 0 hits; `Settings.from_env` gets an explicit dict whose `WD_DATA_DIR` is `<out>/wd-data` (`:1980-1991`), so a shell export cannot leak into `cfg` | `refuse/no-db`: exit 1 with that message. The live `word-dance.db` mtime does move (23:53:26) — that is the owner's running app (pid 1204 listening on :8000), not the harness. |
| API key only from an env var, never logged | `:2009-2017` (`os.environ.get(args.api_key_env)`; empty/unset → exit; `--mock` → literal `mock-key`; real `--base-url` without `--api-key-env` → exit); headers built at `:729-733` / `:799-807`; `raw.request` strips `authorization`/`x-api-key` (`:694`); `raw/*.json` record `env_keys` only for the CLI path; `calls.jsonl` carries at most 300 chars of the provider's error body | runs with `EVAL_HTTP_KEY=sk-verify-HTTPSECRET-987654` (openai + anthropic) and `EVAL_CLI_KEY=sk-verify-SECRET-123456` (CLI wrapper): `grep -rl` over all outputs, logs and the mock log → **0** hits; `refuse/empty-key-var`, `refuse/unset-key-var`, `refuse/real-url-no-key` all exit 1 before any network. |
| `claude_cli` refuses without an explicit `--wrapper`, and refuses the binary | `parse_args` `:1927-1939`: no wrapper → `ap.error`; `os.path.realpath(wrapper)` against `HOMEBREW_CLAUDE_MARKERS` (`:117`); non-executable → error | `refuse/no-wrapper` exit 2; `--wrapper /opt/homebrew/bin/claude` → "refusing to run /opt/homebrew/Caskroom/claude-code/2.1.292/claude" (also with the relative spelling `./claude` from `/opt/homebrew/bin`, after my fix); `/etc/hosts` → "not executable". `pgrep` never showed a `claude` process. Caveat (by design, not fixable here): a *wrapper* that execs the real binary is allowed — that is the owner's documented optional route; the guard can only inspect the wrapper path. |
| mock binds loopback only, never reads auth values | `mock_provider_server.py:426` `ThreadingHTTPServer(("127.0.0.1", port))`; `parse_mode` (`:189-203`) reads only `x-mock-mode`; access line prints method/path/mode/status (`:406`); default access log silenced (`:414`) | `lsof`: `127.0.0.1:8770 (LISTEN)`; `curl http://192.168.1.250:8770/health` → connection refused; mock log has 0 `Bearer`/secret strings. |
| proxy bypass | `httpx.Client(trust_env=False)` unless `--trust-env` (`:661`) | this shell exports `HTTP_PROXY`/`HTTPS_PROXY`; all mock calls went direct. |
| nothing written outside `--out` | `out.mkdir`, `<out>/wd-data/claude-cwd`, `<out>/claude-config`, `raw/`, `prompts/` | `find` for stray `wd-data`/`claude-config` under the repo → none; refusal runs created only their `--out` skeleton. |

`py_compile` of both files: OK before and after the fix.

## 2. What ran (commands are in each `*.log`; outputs under `harness-verify/<name>/`)

* **Dry run** ×2: defaults + `--paired` (96 words → 19 requests, matches the report's table byte-for-byte: content system 2,993 B / user avg 1,549 max 1,756 / schema 1,740 / folded ≤ 4,794 / argv ≤ 6,651 / ≈2.2k tokens; lookup 1,809 / 296–301; consolidate 13,591 B user, 15,641 folded, ≈5.7k tokens; svg 788 / 123–202; probe 183 / 149) and `--per-stage 2` (16 words → 2 content calls). 38 prompt files rendered.
* **Ok mode, `--per-stage 2`, kinds content,lookup,consolidate,svg,probe** (16 words: zk/gk/cet4/cet6 ×2 + phrase 3, abbreviation 3, proper_noun 2 → 2 content + 2 lookup + 1 consolidate + 5 svg + 1 probe = 11 requests): openai json_object · openai json_schema · openai tool (forced) · anthropic tool (`/v1/messages`) · anthropic json_schema `--anthropic-strict` (`/anthropic/v1/messages`, `output_config.format`) · anthropic json_object; plus openai json_object `--gates structural`, openai json_object `--paired` (content only, 64 words), openai tool `--tool-choice auto --no-strict --vendor zhipu`, anthropic tool `--concurrency 3`, two key-leak runs (`--vendor bailian` / `--vendor zhipu`), and one regression run after the fix.
* **Error modes**: all 14 mock modes, most in both formats (29 runs, 4 requests each: content ×1, lookup ×2, svg ×1), plus ECONNREFUSED (closed port 8779), an unknown mode, and `--repair 0`.
* **`claude_cli`** through the fake wrappers: ok (content + probe, with `--base-url`, `--api-key-env`, `--model glm-4.7-flash`, FlashX price file), auth, overloaded, budget, invalid_json, usage_error (`--tier 1`), timeout (`--timeout-scale 0.03`), and the two relative-path cases before/after the fix.
* **Other paths**: `--consolidate user:sqin --words "abandon,ability,take off,notaword123" --per-stage 0 --price-json … --cny-per-usd 7.2`; `--kinds consolidate --consolidate synth:5 --consolidate-headwords 20`; `--kinds probe`; a custom `--lookup-set` containing a CJK string; `--compare` over seven directories.
* **In-process unit check** (`classify_unit.py`, `-I`): 22 `classify_transport` cases the mock cannot emit (404, 403+1308, 403 AllocationQuota, 403 "Request not allowed", 429+1308, bare 429, 429+余额不足, 400+欠费/1113, 400+1301 敏感, plain 400, 401, 402, 500/502/529, 418, ConnectError, ReadTimeout, ConnectTimeout, 200 non-JSON, CLI auth, 200 ok), 11 `output_object` cases (length/max_tokens → truncated, content_filter, tool dict/str, empty/None → empty_content, garbage/list → invalid_json, fenced/prose → success+fenced), `transform_schema` on the five real schemas in both dialects (`check_schema` passes; `additionalProperties:false` on every object: 3/2/4/1/1; `anthropic_strict` removes every `maxItems` and the one `minItems 2`; the on-disk schema object is untouched), and the order-of-validation sanity check (`difficulty: true` → jsonschema 9 errors, pydantic mirror accepts). **All 33 + 10 cases pass.**

## 3. Numbers

### 3.1 Ok mode (`--per-stage 2`; latency is the mock's)

| run | gates → verdict / exit | content schema · items · headword · ≥3 ex · p95 | lookup schema · items · agreement · p95 | consolidate schema · items · coverage · p95 | svg schema · items · sanitiser · p95 | probe |
|---|---|---|---|---|---|---|
| openai json_object | all → NO-GO / 2 | 100 % · 16/16 · 100 % of 64 ex · 100 % · 2.4 ms | 100 % · 40/40 · **76.0 %** · 0.6 ms | 100 % · 80/80 · 100 % · 0.9 ms | 100 % · 5/5 · 100 % · 0.6 ms | exact |
| openai json_schema (strict) | all → NO-GO / 2 | 100 % · 16/16 · 100 % · 100 % · 2.0 ms | 100 % · 40/40 · 76.0 % · 0.5 ms | 100 % · 80/80 · 100 % · 0.8 ms | 100 % · 5/5 · 100 % · 0.5 ms | exact |
| openai tool (forced, `finish_reason=tool_calls`) | all → NO-GO / 2 | 100 % · 16/16 · 100 % · 100 % · 2.2 ms | 100 % · 40/40 · 76.0 % · 0.6 ms | 100 % · 80/80 · 100 % · 0.9 ms | 100 % · 5/5 · 100 % · 0.5 ms | exact |
| anthropic tool (`stop_reason=tool_use`) | all → NO-GO / 2 | 100 % · 16/16 · 100 % · 100 % · 2.1 ms | 100 % · 40/40 · 76.0 % · 0.6 ms | 100 % · 80/80 · 100 % · 0.9 ms | 100 % · 5/5 · 100 % · 0.4 ms | exact |
| anthropic json_schema `--anthropic-strict` | all → NO-GO / 2 | 100 % · 16/16 · 100 % · 100 % · 2.1 ms | 100 % · 40/40 · 76.0 % · 0.5 ms | 100 % · 80/80 · 100 % · 0.9 ms | 100 % · 5/5 · 100 % · 0.5 ms | exact |
| anthropic json_object | all → NO-GO / 2 | 100 % · 16/16 · 100 % · 100 % · 2.0 ms | 100 % · 40/40 · 76.0 % · 0.6 ms | 100 % · 80/80 · 100 % · 0.9 ms | 100 % · 5/5 · 100 % · 0.5 ms | exact |
| openai json_object `--gates structural` | structural → **GO / 0** | same | same | same | same | exact |
| openai json_object `--paired` (content only) | structural → GO / 0 | 100 % · **64/64** (48 paired rows carry the Sonnet item) · 100 % · 100 % · 1.9 ms | — | — | — | — |
| openai tool `--tool-choice auto --no-strict --vendor zhipu` | structural → GO / 0 | 100 % · 16/16 | 100 % · 40/40 | — | — | — |
| anthropic tool `--concurrency 3` | structural → GO / 0 | 100 % · 16/16 · p95 3.7 ms | 100 % · 40/40 · 4.3 ms | 100 % · 80/80 · 1.3 ms | 100 % · 5/5 · 5.0 ms | exact |
| regression after fix (openai json_schema, per-stage 1) | structural → GO / 0 | 100 % · 4/4 | 100 % · 40/40 | 100 % · 80/80 | 100 % · 1/1 | exact |

Every run: 0 truncated, 0 fenced, 0 invalid-JSON, 0 empty, 0 repairs; `mirror_valid_rate` 100 %. The lookup agreement is always 76.0 % (is_english 28/33, kind 24/30, headword 21/28, suggested 0/5) — the mock's naive dictionary, exactly as the report says, and the only failing gate. openai json_object detail: content tokens in/out mean 2,102 / 2,872; field-length p95 meaning_zh 33 · meaning_en 62 · mnemonic 26 · alt 25 (caps 80/160/60/30); zh CJK ratio 67.6 % (the fake's mixed strings); usable-example histogram {4: 16}; consolidate prompt 300 headwords / 80 items / 13,591 B; svg 279–285 B, sanitiser 5/5.

Request shapes checked in `raw/1.json`: openai json_object `response_format {type: json_object}` + schema appended to the system prompt with the word "JSON"; json_schema `{name: content_v1, strict: true, schema: …additionalProperties:false…}`; tool `tool_choice {type: function, function: {name: submit}}` (or `"auto"` + the instruction sentence under `--tool-choice auto`, and no `strict` key under `--no-strict`); anthropic tool `tool_choice {type: tool, name: submit}` with `system` as a top-level string and `anthropic-version: 2023-06-01`; anthropic json_schema `output_config.format.schema` with every `maxItems` folded into descriptions ("(at most 12 items)"); vendor presets `enable_thinking: false` (bailian/openai) and `thinking: {type: disabled}` (zhipu/anthropic) present in the bodies.

### 3.2 Error modes (status / reason written to `calls.jsonl`; "repair" = one re-ask)

| mock mode | openai format | anthropic format | items passed | intended? |
|---|---|---|---|---|
| fenced_json | 200 → **success**, `fenced` ×4 | 200 → success, `fenced` ×4 | 45/45 | yes (counted, not failed) |
| invalid_json | 200 (tool, `tool_calls` with garbage args) → invalid_output / invalid_json; repair ran, still invalid → `repaired_ok=false` | 200 (text block instead of `tool_use`) → invalid_output / invalid_json; repair same | 0/45 | yes |
| schema_mismatch | 200 (json_schema) → invalid_output / schema (`'meaning_zh' is a required property`, `mirror`); repair ran | 200 (tool) → same | 0/45 | yes; `--repair 0` → no second call |
| partial | 200 → success; content 3/4, lookup 38/40 missing → content gate 75 % | same | 42/45 | yes |
| truncated | 200 `finish_reason=length` → invalid_output / truncated, no repair | 200 `stop_reason=max_tokens` (tool) → same | 0/45 | yes (F8) |
| empty_content | 200 → invalid_output / empty_content; repair ran | same | 0/45 | yes |
| slow:3 + `--timeout-scale 0.01` | — | ReadTimeout at 1.8/1.2/1.2 s → timeout / ReadTimeout | 0/45 | yes |
| 401 | auth / unauthorized | — | 0/45 | yes |
| zh_401 (令牌已过期或验证不正确) | auth / unauthorized | auth / unauthorized (via `/anthropic` prefix) | 0/45 | yes (by HTTP status) |
| 402 Insufficient Balance | auth / balance | auth / balance | 0/45 | yes |
| 403 | auth / forbidden ("Request not allowed") | auth / forbidden (百炼 `invalid api-key`) | 0/45 | yes |
| 429 (+`Retry-After: 2`) | overloaded / rate_limit, `retry_after=2` | same | 0/45 | yes |
| 503 | overloaded / http_503 | overloaded / http_503 | 0/45 | yes |
| content_filter (400 data_inspection_failed) | error / content_filter | error / content_filter | 0/45 | yes |
| unknown mode (mock 400) | error / bad_request | — | 0/45 | yes |
| ECONNREFUSED (port 8779) | overloaded / network:ConnectError (no crash) | — | 0/45 | acceptable (see §6) |

### 3.3 `claude_cli` through the fake wrappers

| wrapper | result | notes |
|---|---|---|
| ok (content ×4 words + probe; `--model glm-4.7-flash`, `--base-url http://127.0.0.1:8770/anthropic`, key via env) | success 4/4 and 1/1; `argv[0]` = the wrapper, `--model glm-4.7-flash` in the exact `build_argv` argv; child env keys exactly `ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDE_CONFIG_DIR HOME LANG LC_ALL NO_COLOR PATH TERM TZ`; cwd `<out>/wd-data/claude-cwd`; cost ¥0.003961 (FlashX price file) next to the CLI estimate $0.016; `model_used claude-sonnet-fake` (from the fake's `modelUsage`) | 0 key hits in outputs |
| auth | auth ("Not logged in. Please run claude login") | |
| overloaded | overloaded ("API overloaded (529)") | |
| budget | budget / error_max_budget_usd ("Max budget of $0.05 exceeded") | |
| invalid_json | error ("unparseable stdout") | as `parse_and_classify` says |
| usage_error (`--tier 1`) | error ("unknown option '--system-prompt'") | no tier-0 re-run (documented) |
| timeout (`--timeout-scale 0.03`) | timeout / TimeoutExpired after 1,807 ms, "killed process group 44243"; no stray `fake_claude` | |

### 3.4 Other paths

`user:sqin` consolidate: 3 real pending bank rows, 13 headwords, 605-B prompt, coverage 100 %, cost ¥0.0014; `--words`: `abandon`, `ability` found, `take off` and `notaword123` reported "not in the database; skipped"; content ¥0.0031 / $0.0004 at 7.2 CNY/USD (matches the report). `synth:5` consolidate GO; `--kinds probe` alone GO; custom lookup set: the CJK string is rejected with `normalise_input`'s reason (请输入英文单词) and skipped, no crash. `--compare` prints the merged table (`compare.md`).

## 4. Discrepancies against `harness-report.md`

None material. Every claim I could execute reproduced: refusals, status mapping (14 modes), ok-mode 100 % structural pass, GO/exit 0 under `--gates structural`, 76.0 % mock agreement, user-consolidate figures, dry-run sizes, key handling, loopback bind. Two wording nits: (a) §5.8 says svg items are "reported, not scored" without `defusedxml` — in fact `validate_svg` leaves `clean_ok=None`, so svg items can never pass and the kind is NO-GO (moot: defusedxml 0.7.1 is in the venv); (b) §4 says the DB copy's mtime is unchanged — true for the `.db` and `-wal`, but the `-shm` is touched by read-only WAL readers (harmless).

## 5. Defects found and fixed (in the untracked `scripts/eval_provider.py` only; diff in `harness-verify/fix.diff`, pre-fix copy kept)

1. **Relative `--wrapper` path spawned from the wrong directory.** `os.access(wrapper, X_OK)` ran in the harness cwd, but the child is spawned with `cwd=<out>/wd-data/claude-cwd`, so `--wrapper ./fake-ok.sh` ended as `spawn_error` "FileNotFoundError: './fake-ok.sh'" (`cli-relwrap` before the fix). Fix at `:1931-1932`: `args.wrapper = os.path.abspath(os.path.expanduser(args.wrapper))` before the realpath/marker and executable checks. After: success; the Homebrew refusal still fires for `./claude` from `/opt/homebrew/bin`.
2. **Relative `--claude-config-dir` handed to the child as a relative string.** The directory was created relative to the harness cwd while `CLAUDE_CONFIG_DIR=rel-config` would be resolved by the child against its own cwd (a different, login-free but wrong directory). Fix at `:2029`: `.resolve()`. Verified with a wrapper that echoes the variable: the child now sees the absolute path.

Both files still `py_compile`; the post-fix regression run is GO.

## 6. Issues and recommendations (not fixed — behaviour changes or beyond "small")

1. **No retry/backoff for 429 / 5xx / timeouts.** A transient 429 (Zhipu's one in-flight request and peak-hour throttling, zhipu digest) fails the whole batch and all its items ("call overloaded"), so on the free tier an availability hiccup reads as a quality failure. Before the first real run add `--retry N` honouring `Retry-After` (recorded already) with exponential backoff, or be prepared to re-run and compare `status_histogram`.
2. **An unexpected exception inside `Runner.run_one` aborts the run without a scorecard** (`pool.map` propagates; `raw/` files of finished calls survive). Wrapping `run_one` to record an `error/harness_exception` outcome would make a 10–15-minute free-tier run robust.
3. `ConnectError`/ENOTFOUND are reported as `overloaded/network:<Exc>` because the ledger vocabulary has no network status; fine for the eval, but when the classifier is ported into production F11 wants a separate `NETWORK` soft trigger (contract:F11).
4. `price_for` keys by the provider-reported `model_used`; a vendor that echoes a differently-cased id with a per-model price file yields a silent cost 0 — use the flat `{"input","output"}` form (as the report's commands do).
5. `resolve_db` honours an exported `WD_DATA_DIR` (F17 spec). It is read-only and the Mac's interactive shell does not export it (verified here), but the owner should keep passing `--db` explicitly as the report's commands do.
6. The `--wrapper` guard cannot tell whether a wrapper execs the real binary (the owner's optional CLI route needs exactly that); the harness itself never spawns anything without an explicit `--wrapper`.

## 7. Cleanup

Mock pid 43997 terminated (`kill`, exited), `lsof -iTCP:8770` empty, `pgrep mock_provider_server|fake_claude|eval_provider` empty; port 8000 (owner's app, pid 1204) untouched; `git status --short` unchanged (six untracked entries only); DB copy checksum unchanged. All verifier artefacts are under `scratchpad/fallback/harness-verify/` (`numbers.md` holds the machine-extracted tables, `classify_unit.py/.log` the in-process cases, `fix.diff` + `eval_provider.py.before-fix` the change).
