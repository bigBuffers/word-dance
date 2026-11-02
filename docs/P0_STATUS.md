# Phase 0 — verification status

Verified on 2026-10-14 from `/home/sqin/word-Dance` (Ubuntu 24.04, Python 3.12, Node 22.22 / npm 10.9) by the P0
integrator after the three concurrent P0 agents (backend, frontend, repo/data) finished. Every acceptance command of
`docs/TASKS.md` → "P0 — Phase 0 → Acceptance" passes; the contract cross-checks of TASKS §I, API.md §2/§9 and FRONTEND §1/§8
pass. Two changes were made during verification (section 4). Everything else in this document is information the
implementers of WP1–WP9 need: where Phase 0 extended or pinned down the contracts, and which conventions `main.py`,
`cli.py`, `conftest.py` and the frontend scaffold expect from later packages.

`WD_DATA_DIR` for the runs below was a fresh temporary directory (`<scratchpad>/p0-verify-data`); `.venv` is the venv created
by `make setup`. Inside a Claude Code session the variable `CLAUDECODE=1` is inherited by every child process — see item 3.

## 1. Acceptance commands and results

| # | Command (from TASKS P0 "Acceptance") | Result |
|---|---|---|
| 1 | `WD_DATA_DIR=$V .venv/bin/wd migrate && .venv/bin/wd version` | **PASS** — `applied 0001_init.sql`, `schema version 1`, `wd 0.1.0`; sqlite: **25 tables**, **1 view** (`v_bank`), `schema_migrations == [(1,'init')]` written by the runner; `kv.schema.created_at` set |
| 1b | `WD_DATA_DIR=$V .venv/bin/wd migrate` (second run) | **PASS** — `0 pending`, exit 0 (files do not self-register); `--dry-run` also prints `0 pending` |
| 2 | `.venv/bin/pytest -q backend/tests` | **PASS** — **181 passed** (16 test files; the verifier added one assertion to `test_cli.py::test_migrate_twice`), 1 harmless `StarletteDeprecationWarning` (starlette 1.8 prefers `httpx2`); green both with `env -u CLAUDECODE` and with the inherited `CLAUDECODE=1` (conftest strips it for the spawned fake) |
| 3 | `$PY -I backend/tests/fake_claude.py -p 'x' --output-format json --json-schema "<probe schema>" --tools "" --no-session-persistence --model sonnet --max-budget-usd 0.05 </dev/null \| python3 -c "…assert structured_output == probe object"` | **PASS** when run from a normal shell (`env -u CLAUDECODE …` inside Claude Code): envelope `type:result subtype:success`, `structured_output == {"ok":true,"echo":"word-dance","level":2,"mode":"b","tags":["probe"]}`, `total_cost_usd 0.004`. With `CLAUDECODE=1` inherited the fake exits 3 (`contract violation: CLAUDECODE is set`) — **that exit is mandated by CLAUDE_INTEGRATION §8** (it is how the runner's env allow-list is tested), so the acceptance line must be run outside a nested Claude Code session or with `env -u CLAUDECODE` |
| 4 | `$PY -c "import wd.jobs.registry as r; r.load_handlers()"` | **PASS** — the eight not-yet-existing handler modules are logged as "not available yet" and returned as skipped; no exception |
| 5 | `.venv/bin/uvicorn wd.main:create_app --factory --port 8765 & curl -fsS localhost:8765/api/health` | **PASS** — `200 {"status":"ok","version":"0.1.0","registration_mode":"invite","needs_setup":true,"time":"…Z"}` with `X-Request-Id`, CSP, `nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`, `Permissions-Policy`, `Cache-Control: no-store`. Also verified: `GET /` → 200 `frontend/dist/index.html` (`no-cache`, `lang="zh-CN"`), `GET /today` → SPA fallback 200, `GET /assets/index-*.js` → `public, max-age=31536000, immutable`, `GET /api/nope` → 404 JSON envelope, `POST /api/health` without `X-WD-Request` → 403. Server stopped with SIGTERM, clean shutdown. `wd serve` (DEPLOY §3 entrypoint, port 8767) verified the same way: JSON log lines, `kv.worker_lease` taken at start and released at stop, `kv.public_url_guess = http://<non-loopback IPv4>:8767` |
| 6 | `cd frontend && npm ci && npm run typecheck && npm run build && npm test` | **PASS** — npm ci 98 packages / 0 vulnerabilities; `tsc --noEmit` clean for `tsconfig.json` and `tsconfig.node.json`; build: `dist/index.html` + `dist/assets` (main chunk 286 kB / 93.5 kB gzip, 17 lazy page chunks); vitest 5: 9 files, 48 tests passed |
| 7 | `cmp docs/SCHEMA.sql backend/wd/migrations/0001_init.sql` | **PASS** — identical |
| 8 | `zcat data/seed/vocab.jsonl.gz \| wc -l` | **PASS** — 9162 |
| + | `make test` (DEPLOY §8) | **PASS** — pytest + `npm run typecheck && npm test && npm run build`, 10 s wall |
| + | `cmp docs/<f> <scratchpad>/design/final/<f>` for the six docs + `SCHEMA.sql` | **PASS** — all byte-identical (this file, `P0_STATUS.md`, is the only addition to `docs/`) |

## 2. Contract cross-checks

* **API.md §2 ↔ `frontend/src/api/endpoints.ts`**: all 75 catalogue rows present exactly once as `// #N METHOD /path` + one
  exported wrapper each; a script comparing `(N, method, path)` triples found **0 mismatches**. `endpoints.test.ts` pins
  the same invariant plus the real fetch method/URL of 15 representative wrappers.
* **API.md §2 ↔ `backend/wd/schemas.py`**: `ENDPOINT_MODELS` maps 72 endpoints to `(RequestModel | None, ResponseModel)`;
  the three without an entry have no JSON body by contract (4 `POST /api/auth/logout` → 204, 52/53 media bytes). All
  **153** Pydantic models are `extra='forbid'`; `Settings.current_stage` is `Literal['zk','gk','cet4','cet6']` (the `Stage`
  string, API.md §9.1); `stage_to_index`/`index_to_stage`/`STAGE_NAMES_ZH` exist.
* **API.md §9 ↔ `frontend/src/api/types.ts`**: `diff <(sed -n 235,444p docs/API.md) <(tail -n +5 types.ts)` → identical.
* **TASKS §I signatures** (inspected in source): `interfaces.py` — `Clock` (defined in `clock.py`, re-exported), `Mailer`,
  `ImageProvider` (+ `name`), `Candidate` (all 15 fields in order), `ClaudeRunner.run(conn, *, kind, system_prompt,
  user_prompt, schema, max_budget_usd, timeout_s, word_count, job_ids)`, `ClaudeResult`, `Handler`, plus `ProviderError`,
  `Job` (dataclass of a `jobs` row, `Job.from_row`, `.group_size`) and `BackgroundThread`. `jobs/queue.py` — `enqueue`,
  `head_type`, `claim_batch`, `finish`, `fail`, `defer`, `requeue_group`, `requeue_stale`, `cancel`, `run_once` with the
  §I positional/keyword parameters (extensions in §3). `jobs/registry.py` — `register`, `load_handlers`, `HANDLER_MODULES`
  (identical tuple), `registered_types`, `JobContext`. `services/stats_core.on_action(conn, user_id, local_date, *, action,
  context, new_state, item_kind, elapsed_ms, undone=None)` (+ `prev_state`). `clock.py` — `local_date`, `day_start`,
  `compute_next_push`, `now_iso`, `Clock`.
* **FRONTEND §1 directories**: `src/{api,auth,i18n,hooks,components/ui,components/word,pages,styles}` exist with the P0
  files; `components/layout/AppLayout.tsx` exists as a P0 stub (WP7 replaces it). `tsconfig.json` has `strict` and
  `noUncheckedIndexedAccess`; `vite.config.ts` proxies `/api` and `/media` to `http://127.0.0.1:8000`, `outDir: 'dist'`.
* **FRONTEND §8 ↔ `src/i18n/zh.ts`**: both transpiled and flattened — **391/391** §8 keys present with identical values
  (functions compared by source and by sample application); **3 extra keys**, each inline-commented `P0 addition`:
  `common.backToToday` (`回到今日`), `word.speak` (`发音`), `word.speechUnsupported` (`当前浏览器不支持语音`). `grep -rn '[一-龥]'
  src --include=*.tsx` outside `i18n/` → nothing; the forbidden glossary term appears nowhere in the repo.
* **Fixtures**: `mini_seed.jsonl` has 60 records incl. `abandon apple run running go child data better base basis a.m.
  "ice cream" China TV AIDS`; `GDP`/`NASA` absent as required. `claude_*_ok.json`, `openverse_search.json`,
  `wikimedia_search.json` (legacy `query.pages` object shape), `srs_trajectory.json`, `batch_order.json` all parse and are
  exercised by `tests/unit/test_claude_fixtures.py`.

## 3. Deviations from / extensions of the contract documents (implementers must read)

Everything below is additive or keyword-only; nothing in TASKS §I was renamed or removed. The integrator folds the
ratified items into the design documents in "contract change" commits. **Ratified on 2026-11-02 (`fix(docs)`)**: item 1 →
TASKS P0 step 4 (`run_migrations` signature); item 3 → API.md §1.1 (`method_not_allowed` 405, `payload_too_large` 413);
item 4 → TASKS §I + DESIGN §7.1 (`on_action` `prev_state`, return value, `undone.item_kind`); item 8 → DEPLOY §4
(`WD_FRONTEND_DIST`); item 9 → DEPLOY §3 (`access_log=False`, `os.umask`); item 16 → FRONTEND §8 (the three keys);
item 23 → DEPLOY §8 / ops.md §8 / qa-study.md (Vite binds `localhost`; `--host` for LAN devices).
`backend/tests/unit/test_docs_contract.py` and `frontend/src/i18n/zh.contract.test.ts` keep those documents aligned
with the code. The remaining items stay documented here only.

### Backend (`backend/wd`)

1. **`db.run_migrations(conn, *, pre_hook=None, migrations_dir=None, dry_run=False) -> MigrationResult`** — the connection
   is the first positional argument (TASKS §P0 step 4 only named `pre_hook`). It refuses a connection that is already inside
   a transaction and a migration file that `COMMIT`s itself. `db.connect(path, *, timeout=5.0, check_same_thread=True)`;
   `deps.get_db` passes `check_same_thread=False` (FastAPI runs a sync dependency and its endpoint on different threadpool
   threads sequentially; `sqlite3.threadsafety == 3`). Job and CLI code keep the default. `db.tx()` is the explicit
   `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK` context manager with 3 busy retries; `db.maybe_tx()` joins an open transaction —
   queue and stats helpers use it, so they compose inside a caller's transaction. `kv_get/kv_set/kv_delete` present.
2. **`wd migrate` chmods `word-dance.db` (and `-wal`/`-shm` when present) to 0600 after running** (verifier change, §4):
   DEPLOY §1 only guarantees 0600 through the units' `UMask` and `wd serve`'s `os.umask(0o077)`, but install.sh runs
   `wd migrate` from a plain shell. WP9's install.sh may additionally `umask 077`; it no longer has to.
3. **CSRF** (API.md §1) is enforced globally by `main.py`'s ASGI middleware for every non-GET `/api/*` request
   (`X-WD-Request: 1` and `Origin ∈ {Host-derived origin, origin of WD_PUBLIC_URL, http://localhost:5173 when WD_DEV=1}`);
   `deps.csrf_guard` is the same check as a dependency. Transport-level error codes **`payload_too_large` (413)** and
   **`method_not_allowed` (405)** were added to `errors.CATALOGUE` (API.md §1.1 lists no transport codes). 422 → 400
   `validation_error` with `details.fields`.
4. **`stats_core.on_action`** gained keyword `prev_state: str | None = None` and returns the applied delta dict. WP3 must
   pass `prev_state=<review_logs.prev_state>` for `unfamiliar` (`None` = row created → `added += 1`; a state = idempotent →
   nothing). For `restore`, `undone` must contain `action`, `new_state`, `prev_state`, `context` **and `item_kind`**
   (the `push_items.kind` of `push_item_id`) so the `graded -= 1` (study-card master) and `screened -= 1` (`kind='screen'`)
   reversals fire. `study_ms` is never reversed; counters are clamped at 0 in SQL. `stats_core` is the only writer of
   `daily_stats`.
5. **`jobs/queue.py` extensions**: every state function takes keyword `now: str | None` (ISO, for frozen-clock tests);
   `requeue_group(..., *, error=None, now=None)`; return values: `fail → 'queued' | 'dead'`, `defer`/`requeue_group`/`cancel`
   `→ int` rows touched, `requeue_stale → int`. `enqueue` validates `type` against `registry.JOB_TYPES` (the `jobs.type`
   CHECK list) and adds `created_at/updated_at` to the SCHEMA UPSERT's VALUES so one clock is used. `defer` and
   `requeue_group(consume_attempt=False)` give the claim's attempt back; `requeue_group(consume_attempt=True)` kills members
   at `attempts >= max_attempts` and backs the rest off. `run_once` fails jobs that have no handler or that a handler left
   `running`, so a drain always terminates. Helpers: `limit_for(type, cfg)` (content → `WD_AI_BATCH_SIZE`, lookup → 20,
   else 1), `backoff_minutes`, `get_job`, `live_job(conn, dedupe_key)`, `STALE_LOCK_MINUTES`.
6. **`jobs/registry.py`**: `JobContext(db, cfg, clock, enqueue, log, worker_id='once', boot_id='')` where **`db` is a
   connection factory** (`ctx.db()` → one connection per job run) and `enqueue` is `queue.enqueue` (call as
   `ctx.enqueue(conn, type, payload, dedupe_key=...)`); `ctx.now()`, `ctx.locked_by` (`'<worker>:<boot_id>'`),
   `ctx.for_worker(worker_id)`. `load_handlers()` returns the list of skipped modules and tolerates **only**
   `ModuleNotFoundError` for the handler module itself or a parent package — any other import error propagates.
   `register()` rejects a type outside `JOB_TYPES`; `get_handler`, `reset()` (tests) exist.
7. **`main.py` lifespan conventions**: `ensure_dirs → run_migrations(pre_hook=wd.backup.snapshot_before_migrate (late
   import; warn when absent)) → seed check (sha256 of WD_SEED_PATH vs kv.seed_version → wd.seed.import_seed(conn, path,
   force=False), late import; warn-and-continue while module or file is missing; kv.seed_version set defensively after import)
   → kv.public_url_guess → registry.load_handlers() → background threads when WD_WORKER_ENABLED`. Threads come from
   `THREAD_CLASSES = (wd.jobs.worker.ClaudeWorker × WD_AI_CONCURRENCY as claude-N, wd.jobs.worker.IoWorker as io-1,
   wd.jobs.scheduler.Scheduler as scheduler)`, constructed as `Cls(ctx.for_worker(worker_id))` and driven via
   `start()/stop()/join(timeout)` (`interfaces.BackgroundThread`). **Lease**: `kv.worker_lease` TTL 90 s renewed every 30 s
   by `wd/jobs/lease.py` (`acquire/renew/release/is_live`, `LeaseKeeper`); a second instance logs a warning and serves
   requests only while `main.LeaseWaiter` retries the lease every 30 s (a crash-restarted service takes over once the
   stale lease expires); stale `running` jobs are swept when the lease is taken; `workers != 1` (WEB_CONCURRENCY or `--workers`) raises
   `SystemExit`. `create_app(settings=None, *, clock=None, configure_logs=True)`; `app.state.mailer` is
   `delivery.mailer.mailer_from_settings(cfg)` (`SmtpMailer` or `RecordingMailer`). **`wd worker-once`, `wd tick`,
   `wd restore` must use `wd.jobs.lease.is_live(conn, now_iso)` for the DEPLOY §9 exit-2 refusal** (`cli.LEASE_HINT`).
8. **SPA serving**: `GET /{path:path}` catch-all after the routers serves `frontend/dist` (**new optional variable
   `WD_FRONTEND_DIST`**, default `<repo>/frontend/dist`, not in the DEPLOY §4 table — exists so tests can point at a temp
   dist); `/assets/*` immutable, `index.html` `no-cache`, path-traversal check, a 503 "前端尚未构建" page while dist is
   missing, JSON 404 envelopes for unknown `/api` and `/media` paths.
9. **`cli.py`**: `register_cli(sub)` contract = add sub-parsers with `p.set_defaults(func=handler)` where `handler(args) ->
   int | None`. Commands of absent modules are stubs that swallow any arguments and exit 2 with "not implemented"
   (`COMMAND_OWNERS` = DEPLOY §9 bracketed list). `$WD_DATA_DIR/.env` is loaded with python-dotenv (never overriding the
   real environment). `wd serve` = the DEPLOY §3 `uvicorn.run(...)` **plus `access_log=False`** (the middleware emits the one
   JSON request line, DEPLOY §6) and `os.umask(0o077)`.
10. **`config.Settings`**: frozen dataclass with every DEPLOY §4 variable; `WD_AI_BATCH_SIZE` clamped 1–12 and
    `WD_AI_CONCURRENCY` 1–3 with a warning, other out-of-range values raise `ConfigError`; `WD_TZ` validated with
    `zoneinfo`; an empty `WD_SECRET_KEY` becomes a random per-process key **with a warning** (install.sh always sets it);
    keyed providers are appended to `WD_IMAGE_PROVIDERS`; `entries()` implements `GET /api/admin/config` with secrets
    masked; `env_sources` records which keys came from the environment. `logging_setup.py` (extra module): JSON-lines
    formatter, ring buffer for `wd logs`, `configure_logging(cfg)`.
11. **`schemas.py` naming**: models mirror the TS interface names, request bodies are `<Endpoint>Request`, query models
    `VocabQuery, BankQuery, ScreenNextQuery, SuggestionsQuery, HistoryQuery, PageQuery, Admin*Query`; `client_event_id` is
    validated as a UUID string. **`schemas.Settings` (user-settings DTO) and `config.Settings` (runtime config) share a
    class name across modules** — alias one of them when importing both.
12. **`deps.visible_word_sql(me, *, alias='words', param='me')`** binds the named parameter `:me` twice; surrounding
    statements must use named-parameter style (or rename via `param=`). Admin users get `1=1`. `current_user` /
    `require_onboarded` / `require_admin` / `client_ip` / `csrf_guard` / `get_settings` / `get_clock` exist as
    dependencies; `hash_token` is the session-token hash.
13. **`tests/fake_claude.py`**: stdlib-only, **must stay executable** (`chmod 755`, shebang `#!/usr/bin/env python3`) because
    `make dev`/DEPLOY §8 set `WD_CLAUDE_BIN` to it and WP5's runner spawns `cfg.claude_bin` directly. It exits 3 whenever
    `CLAUDECODE` is in its environment (CLAUDE_INTEGRATION §8) — WP5's `claude_env()` must build the child env from the
    §1.3 allow-list, and anyone running the fake by hand inside Claude Code uses `env -u CLAUDECODE`. `budget` mode reports
    the passed `--max-budget-usd` (0.25 when absent) as `total_cost_usd`; unknown flags such as `--effort low` are ignored;
    `usage_error` rejects only tier-1 flags. `tests/fixtures/claude_schemas.json` holds the verbatim §2/§4 schemas
    (`probe_v1/content_v1/lookup_v1/consolidate_v1/svg_v1`) — **WP5's `ai/schemas/*.json` must be byte-equal** (or the
    integrator removes the copy once the real files exist).
14. **`conftest.py`**: per-test temp `WD_DATA_DIR` with the test env (worker off, fake claude, open registration, fixed
    secret, mini seed, `WD_SMOKE_MOCK_HTTP=1`, `CLAUDECODE` removed); `client` runs the lifespan and presets
    `X-WD-Request: 1` (`raw_client` does not); **`seeded` imports the mini seed through `wd.seed.import_seed` and skips while
    WP1 is absent** (no duplicate importer in P0); `mock_http` installs an `httpx.MockTransport` as the default transport of
    every `httpx.Client`, matching on the Host header first (DNS-pinned IP URLs still hit) and ignoring query strings;
    the `full_seed` marker auto-skips unless `WD_FULL_SEED_DB` is set; `FrozenClock` and `login()` helpers exist.
15. **Fixture readings**: `batch_order.json` pins `spread_similar` under the literal DESIGN §6.3 reading (single
    left-to-right pass; an item is moved to the first later index whose three predecessors are not similar; the item shifted
    into position *i* is not re-examined) with the algorithm text embedded; `srs_trajectory.json` pins the 8-step trajectory,
    the lapse case (20 → again → 10 d, ease 2.55 → 2.35) and the `humanize` thresholds, mastery suggested from step 5;
    `claude_content_ok.json` reuses the 10 real batch10 probe items plus `valid/image_alt_zh/difficulty`;
    `claude_lookup_ok.json` uses `went / recieve / take off / <injection> / GDP`.

### Frontend (`frontend/`)

16. **`zh.ts` = FRONTEND §8 plus three keys** (`common.backToToday`, `word.speak`, `word.speechUnsupported`, see §2) that
    §2/§4/§6.3 of FRONTEND require but §8 lacks — to be ratified in FRONTEND §8 by the contract-change commit. §8 had no copy
    for a learning word that is due now/overdue/today (StateBadge omitted the due suffix then; `study.nextDue.today` /
    `overdue` were added and ratified by the fix(frontend) commit) and has none for `WordKind`
    (`phrase/abbreviation/proper_noun`; no WordKind badge is rendered, so no key is needed).
17. **`components/layout/AppLayout.tsx` (+ `.css`) is a P0 stub in WP7's directory** because frozen `routes.tsx` mounts
    `<AppLayout/>` as the layout route of every authenticated page. WP7 replaces the file keeping the export name `AppLayout`
    and the inner `<Suspense>`, sets `--tabbar-h` on phones so toasts clear the TabBar, and may hide the shell on `/study`.
18. **`routes.tsx` guards**: `RequireAuth` (→ `/login?next=`), `RequireOnboarded` (only on `/`, `/today`, `/study`,
    `/history`, `/history/:batchId`), `RequireAdmin` (→ `/today` + toast) as specified, plus `RequireGuest` (`/login`,
    `/register` → same-origin `next` or `/today`) and `RequireNotOnboarded` (`/welcome` → `/today` when done) implementing
    the guest / not-onboarded rows of FRONTEND §2. `routePaths` builders are exported.
19. **`api/client.ts`**: booleans in query strings serialise as `1/0`; 204/empty → `undefined`; non-envelope errors get a
    status-derived code (401 `unauthorized`, 403 `forbidden`, 404 `not_found`, 429 `rate_limited`, 5xx `internal_error`);
    `errorMessage()` prefers `zh.errors` by code, then the server's `message_zh`, then `zh.errors.server`; `auth:expired`
    is dispatched only for a 401 whose code is `unauthorized` (never for `invalid_credentials`).
20. **`api/endpoints.ts`**: one wrapper per catalogue entry, GET wrappers take a trailing `AbortSignal`; #11 is
    `exportAccount(format) → text` plus `exportAccountUrl(format)`; #52/#53 are URL builders `mediaImageUrl(path)` /
    `cardUrl(wordId)`; `importPayloadFromJsonExport(text)` implements the API.md 11/75 `{version, words}` reduction.
    Request/response shapes that API.md defines only in prose live in `endpoints.ts` so `types.ts` stays frozen.
21. **`auth/AuthContext.tsx`**: FRONTEND §3 surface plus `register()`, `applySession()`, `refreshHealth()` and `health`
    (the public `GET /api/health` flags for the login/register pages); `refreshCounters()` is the same `/me` request as
    `refresh()` (API.md 5).
22. **UI details**: `Button` variants `primary/secondary/ghost/danger` + tones `again/hard/good/screen`, 44 px tap targets
    (`sm` → 36 px only on hover+fine-pointer devices); `Sheet`/`ConfirmDialog` on native `<dialog>`; `Toast` ≤ 3 visible with
    `UNDO_LIST_MS=5000` / `UNDO_MASTER_MS=8000`; `Tabs` emits no `aria-controls` (pages add `role="tabpanel"` themselves);
    `tokens.css` = §6.3 block plus derived tokens and contrast-safe `--*-ink` text variants, dark palette under both
    `prefers-color-scheme` (guarded) and `[data-theme="dark"]`; `usePageTitle` added (not in the P0 hook list).
23. **Dev servers**: Vite binds `localhost`, which resolves to `::1` on this box — use `http://localhost:5173`, not
    `127.0.0.1:5173` (matches the backend's `WD_DEV` origin allowance). The proxy uses `changeOrigin: false` so the
    backend's Host-derived CSRF origin check passes. Vitest config lives in `vite.config.ts`; `npm run lint` runs
    `scripts/check-copy.mjs` (the §8 copy rules, also enforced by `zh.test.ts`).

### Repository / data

24. `data/seed/vocab.jsonl.gz` was built with `gzip -9 -n -c` (`-n` omits name/mtime so the archive — and the sha256 the
    lifespan stores as `kv.seed_version` — is reproducible); `make seed` uses `gzip -9 -n -k -f`. sha256
    `a68127812a43c47ff011828b7894b789ba0fcf69cc8e76f1ec6c2356e81a3336`, 9162 lines, byte-identical round trip.
25. `Makefile`: `help` is the default goal; `smoke` and `install` exit 2 with a hint until WP9 adds `scripts/smoke.py` /
    `deploy/install.sh`; `dev` is implemented inline from DEPLOY §8 and `exec`s `scripts/dev.sh` once it exists;
    `PYTHONPATH=<repo>/backend` is prefixed only on the pytest/smoke/dev recipes.
26. `.gitignore` carries the mandated list plus `.coverage.*`, `htmlcov/`, `coverage/`, `*.egg-info/`, `backend/build/`,
    `.dev-data/`, `data/seed/vocab.jsonl`, `.claude/settings.local.json`; `frontend/.gitignore` (`dist/`) duplicates the
    root rule harmlessly. `pip install -e backend` leaves `backend/word_dance.egg-info/` (ignored).
27. DESIGN §9 says the 关于 page renders `ATTRIBUTION.md`, while FRONTEND lists fixed contents for that section and API.md
    has no route for the file; root `ATTRIBUTION.md` currently describes the page as a summary. Decide in WP7/WP9 (a static
    route would be a backend contract change). External policy URLs in `ATTRIBUTION.md` were written from general knowledge,
    not fetched. **Resolved at integration (post-steps)**: the 关于与数据来源 section renders the fixed FRONTEND §5.8 lines
    (`zh.settings.sources`), `ATTRIBUTION.md` stays the repository-level document linked from the README, DESIGN §9 was
    reworded accordingly and no static route was added.

## 4. Changes made by the verifier

1. `backend/tests/fake_claude.py`: mode 644 → **755** (CLAUDE_INTEGRATION §8 "an executable Python script"; needed by
   `WD_CLAUDE_BIN` in `make dev`). Verified by executing it directly.
2. `backend/wd/cli.py`: `cmd_migrate` now calls `_restrict_db_mode(cfg.db_path)` after closing the connection (chmod 0600 of
   `word-dance.db`, `-wal`, `-shm` when present) — see §3 item 2; `backend/tests/unit/test_cli.py::test_migrate_twice`
   asserts the mode. Full suite re-run: 181 passed; a fresh `wd migrate` (and a fresh `wd migrate --dry-run`) under
   `umask 022` leaves `word-dance.db` at 0600.

## 5. Known warnings (not defects)

* `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead` — starlette
  1.8 / fastapi 0.143; harmless until the pins move. Filtered by `[tool.pytest.ini_options] filterwarnings` in
  `backend/pyproject.toml` (message match), so it no longer shows up in `make test`.
* `WD_SECRET_KEY is not set; using a random per-process key` on every CLI run without the variable — expected outside
  install.sh.
* `wd.backup` / `wd.seed` / handler modules / worker classes "not available yet" warnings at startup — the Phase-0 window
  by design; they disappear as WP1/WP4/WP5/WP6/WP9 land.

## 6. Re-running this verification

```
cd /home/sqin/word-Dance
V=$(mktemp -d); export WD_DATA_DIR=$V
.venv/bin/wd migrate && .venv/bin/wd version && .venv/bin/wd migrate
python3 -c "import sqlite3;c=sqlite3.connect('$V/word-dance.db');print(len(c.execute(\"select name from sqlite_master where type='table' and name not like 'sqlite_%'\").fetchall()), c.execute('select version,name from schema_migrations').fetchall())"
env -u CLAUDECODE .venv/bin/pytest -q backend/tests
env -u CLAUDECODE .venv/bin/python -I backend/tests/fake_claude.py -p x --output-format json --json-schema '{"type":"object","properties":{"echo":{"type":"string"}},"required":["echo"]}' --tools "" --no-session-persistence --model sonnet --max-budget-usd 0.05 </dev/null
.venv/bin/python -c "import wd.jobs.registry as r; r.load_handlers()"
(cd frontend && npm ci && npm run typecheck && npm run build && npm test)
env -u CLAUDECODE .venv/bin/uvicorn wd.main:create_app --factory --port 8765 & sleep 2; curl -fsS localhost:8765/api/health; curl -fsS -o /dev/null -w '%{http_code}\n' localhost:8765/; kill %1
cmp docs/SCHEMA.sql backend/wd/migrations/0001_init.sql && zcat data/seed/vocab.jsonl.gz | wc -l
```
