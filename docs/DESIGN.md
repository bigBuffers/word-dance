# word-Dance — Final Design (synthesised)

Status: FINAL · 2026-10-14 · target `/home/sqin/word-Dance` (empty) · all facts from `scratchpad/FACTS.md` (verified on this machine).

This document is the architecture reference. The other six documents are contracts an implementation agent builds against:

| File | Contract |
|---|---|
| `SCHEMA.sql` | complete SQLite DDL (= `backend/wd/migrations/0001_init.sql`), directly executable |
| `API.md` | every HTTP endpoint + shared TypeScript DTOs (= `frontend/src/api/types.ts`) |
| `CLAUDE_INTEGRATION.md` | exact `claude` CLI invocation, prompts, `--json-schema` payloads, batching, caps, failure handling, consolidation spec |
| `FRONTEND.md` | routes, pages (zh-CN), components, state, interactions, responsive rules, i18n strings |
| `DEPLOY.md` | install script, systemd units, env vars, data dir, backups, logs, reverse proxy, dev workflow |
| `TASKS.md` | work packages with exact file ownership, dependencies, acceptance criteria |

Synthesis basis: candidate **A** (overall winner, pragmatic MVP) is the skeleton; from **B** we graft the learning layer (WD-SRS with learning steps, 筛词 screening + 推荐词, bank-wide 整理 with a suggestion inbox, binding zh-CN glossary, `client_event_id` idempotent grading, lookup preview, user-facing 换一张); from **C** we graft the robustness layer (custom-word privacy staging, `word_forms` headword guard, atomic `UPDATE … RETURNING` claims, persisted provider quotas and auth throttles, budget reservation + hourly call cap, install-time `claude` probe, template SVG rendered on the fly, independent backup timer with `VACUUM INTO` + `integrity_check`, measured cost model). Section 13 lists how every judge `must_fix` item is resolved.

---

## 0. Executive summary

| Aspect | Decision |
|---|---|
| Shape | ONE Python process (FastAPI API + static SPA + scheduler thread + Claude worker thread + I/O worker thread) + ONE SQLite file + ONE data directory outside the repo, managed by ONE systemd **system** unit running as `sqin` (the user whose `claude` CLI is authenticated). |
| Backend | Python 3.12 · FastAPI 0.143 · uvicorn 0.54 (`workers=1`, enforced) · stdlib `sqlite3` (SQLite 3.45.1, WAL) with hand-written SQL and numbered `.sql` migrations · Pydantic v2 · `bcrypt` 5 · `httpx` 0.28 · `Pillow` 12 · `defusedxml`. No ORM, no Redis, no Celery, no APScheduler, no Docker. |
| Frontend | React 19.3 + TypeScript 5.9 + Vite 8.3 + `react-router` **7.x** (pinned `^7`, never 8), plain CSS with custom properties, Simplified-Chinese UI. Served by FastAPI from `WD_FRONTEND_DIST`: `frontend/dist` in development, for the installed service the versioned snapshot `$WD_DATA_DIR/frontend → frontend-releases/<sha>` that install.sh publishes atomically (DEPLOY §1). |
| AI | `claude -p … --output-format json --json-schema … --tools "" --no-session-persistence --model sonnet --max-budget-usd …` (the FACTS §3 verified invocation) + an install-probed hardening tier (`--system-prompt --restricted --strict-mcp-config --disable-slash-commands`) that is auto-disabled on a usage error. Per-word jobs batched 10 per call; content cached globally per word; per-call, daily and monthly caps with deferral; measured cost $0.004/word. |
| Images | **Wikimedia Commons primary** (≤1 req/s, descriptive UA) → Openverse secondary (15/min, 160/day persisted counters; anonymous limits are 20/min, 200/day) → optional keyed Pixabay/Pexels → **Claude-drawn sanitised SVG concept card (default ON, `WD_SVG_VIA_CLAUDE=1`, only for words a user actually studies, never for prewarm, bounded by `WD_AI_SVG_DAILY_BUDGET_USD=0.50` ≈ 35–40 cards/day at the measured $0.0124 per call — $0.0140 per delivered card, 11.8 % of calls rejected by the sanitiser, 34 calls measured 2026-11-05)** → deterministic template SVG card rendered on the fly (text-only, never fails). Several candidates fetched and ranked; users can request 换一张. All photos downloaded, re-encoded, served locally. The admin overview splits words into photo / claude_svg / card-only so the photo hit rate is visible. |
| Scheduling | 60-s tick thread. One `push_batches` row per (user, local date) enforced by `UNIQUE`. Built up to `WD_PREBUILD_HOURS=3` before the user's push time but never before 00:00 of the batch's own local day, published at push time (in-app always; e-mail / 企业微信 / 飞书 / Server酱 / Bark webhooks best-effort). Items whose state changed between build and study are hidden (§6.3). Downtime catch-up builds only the current local day. |
| Learning | Bank states `new → learning → mastered` (+ `known`, `removed`); WD-SRS: one 10-minute learning step, SM-2 style expanding intervals (1 → 3 → 8 → 20 → 51 → 133 → 180 d), relearning after a lapse, overdue credit, deterministic ±5 % fuzz, mastery *suggested* at interval ≥ 30 d and 3 consecutive 记住了 — the user always confirms 已掌握. |
| Data | The seed `data/seed/vocab.jsonl.gz` is built by `backend/wd/seedbuild/` (`make seed`; entry `scripts/build_seed.py`) from ECDICT dictionary fields plus the official head-word lists in `data/lists/` (MOE 2022 Level 2/3 + appendix, Shanghai 2020 junior, senior 2020/2025); record and per-stage counts live in `data/seed/stats.json` (never copied into prose or tests), `data/seed/DIFF.md` records what moved against the previous seed (§3.2). |
| Onboarding | First login: choose 目标阶段 (multi-select of 小学/初中/高中/四级/六级; default 小学 + 初中, 主攻 小学), 主攻阶段, 推送时间, 时区, then a 20–30-word 筛词. Recommendation order derives from this; nothing is hard-coded to a single stage. |
| Deploy | `deploy/install.sh` (idempotent) → venv, `npm ci && npm run build` into a versioned snapshot in the data dir (published atomically after the stop), data dir, `.env`, migrate + seed, `claude` probe, systemd unit + backup timer. Optional Caddy/nginx for HTTPS. |

### 0.1 Requirement → mechanism map (all 7 are MUST-HAVE, none narrowed)

| # | Requirement (brief) | Mechanism |
|---|---|---|
| 1 | Ubuntu server, web front-end, accounts with login | systemd unit on this box; FastAPI serves the React SPA; server-side cookie sessions; bcrypt passwords; invite/open/closed registration (§10, DEPLOY.md) |
| 2 | System pushes/offers the COMPLETE 小学 / 初中 / 高中 / CET-4 / CET-6 vocabulary | `words` table seeded from the official head-word lists with per-stage flags (record counts: `data/seed/stats.json`); 词库 browser with 全部 + five stage tabs, 仅本阶段新增 filter, A–Z, search; daily 推荐词 (screening cards) appended to every push; 筛词 page for rapid triage (§3, §6, FRONTEND.md) |
| 3 | Mark a single word 不熟悉 → personal 生词库 | `POST /api/words/{id}/mark {action:"unfamiliar"}` from any list/card → `user_words.state='new'` (§4) |
| 4 | Backend uses **Claude Code** to consolidate/update the bank and pushes a daily batch per user settings | `claude -p` jobs: `lookup_word` (validate/normalise/fill user-added words), `consolidate_bank` (nightly bank-wide 整理: lemmatise, merge duplicates, spot misspellings, fill fields, tag difficulty → 整理建议 inbox), `generate_content` (examples, collocations, mnemonic, image keywords); scheduler builds and publishes one batch per user per day according to `user_settings` (§5, §6, CLAUDE_INTEGRATION.md) |
| 5 | User adds own words anytime (also outside the five official lists) | `POST /api/bank/add` (bulk paste), `POST /api/bank/add-word` and `POST /api/bank/import` (re-import of an export); normalisation → ECDICT inflection table → optional full `stardict.db` → private provisional word + Claude lookup (visible to every user who holds it); `study_today` appends an already-validated word to today's batch, a provisional one joins the first batch after validation (§5) |
| 6 | Confirm mastered → removed from the bank | `action:"mastered"` (study card 已掌握, bank list, detail page) → `state='mastered'`, kept as history, excluded from pushes; 8-second 撤销 toast calls `action:"restore"`, which puts the exact prior SRS snapshot back within 15 minutes (a mis-tap costs nothing); a later deliberate re-add from the 已掌握 list is `action:"unfamiliar"` (§4) |
| 7 | Pushed words carry authentic idiomatic examples + an image | `word_contents.content_json.examples[]` (3–4 en/zh pairs, registers varied) + `word_images`: a photo with attribution (Wikimedia → Openverse → optional keyed providers) or, when no acceptable photo exists, a Claude-drawn SVG concept card (default on, budgeted); only when both fail or the SVG budget is spent does the text-only template card stand in, and the operator sees that share in the admin overview. Every pushed word is studyable immediately with ECDICT data + card while Claude content is pending (§6.5, §9) |

### 0.2 Design principles

1. **One process, one file, one unit.** Scheduler and job queue live inside the API process (SQLite `jobs` table). `uvicorn` runs exactly one worker process; `main.py` refuses otherwise; a `kv.worker_lease` guards against an accidental second `wd serve`.
2. **Plain SQL over ORM.** Every table and query is visible in `migrations/*.sql` and `services/*.py`.
3. **Idempotency by constraint.** One batch per (user, day), one `user_words` row per (user, word), one live job per `dedupe_key`, one grade per `client_event_id` — all `UNIQUE` indexes.
4. **Bounded AI cost by construction.** Content generated once per word for all users, batched 10/call, per-call `--max-budget-usd`, reservation against daily/monthly caps before every call, hourly call cap, kill switch, deferral instead of failure.
5. **Never-empty fallbacks.** A word without Claude content shows its ECDICT entry; a word without a photo gets the template card; the daily push never blocks on external services.
6. **Shared data is validated data.** User-typed strings become visible to other users only after Claude validates them as real English and safe to share; every Claude-proposed headword passes the same deterministic validator as user input.
7. **Threads, not async.** Synchronous FastAPI endpoints (thread pool), `subprocess.Popen` + `communicate(timeout=…)` for `claude` (so the whole process group can be killed on timeout, CLAUDE_INTEGRATION §1.2), sync `httpx.Client`.

### 0.3 Binding zh-CN glossary (UI copy must use these exact terms)

| Concept | UI term | Code identifier |
|---|---|---|
| Personal word bank | 生词库 | `bank`, `user_words` (never 单词本) |
| Mark as unfamiliar (button verb) | 不熟悉 / 标为不熟悉 | `unfamiliar` |
| Mastered (removes from bank) | 已掌握 | `mastered` |
| Removed without mastery | 移除 | `removed` |
| Screened as known | 认识 | `known` |
| Grade again / hard / good | 不熟悉 / 模糊 / 记住了 | `again` / `hard` / `good` |
| Skip | 跳过 | `skip` |
| Review / new item | 复习 / 新词 | `review` / `new` |
| Screening card in today's push | 推荐词 | `screen` |
| Screening page | 筛词 | `/screen` |
| Extra round | 再来一组 | `extra` |
| Stages | 小学 / 初中 / 高中 / 四级 / 六级 | `xs` / `zk` / `gk` / `cet4` / `cet6` (stage index 1–5; `schemas.STAGE_ORDER` / `STAGE_INDEX`, index = position + 1) |
| Outside every official list | 课标外 | `stage_min IS NULL` (`zh.stages.outside`; visible only in 全部 and search) |
| Today's push | 今日词汇 (nav: 今日) | `today` |
| Consolidation | 整理 ; inbox 整理建议 | `consolidate`, `bank_suggestions` |
| Custom word | 自添生词 | `custom` |
| Pending AI validation | 待校验 | `needs_attention=0, is_valid_english IS NULL` |
| Not recognised / could not validate (buttons 修改 · 保留 · 删除 · 重试) | 未识别 / 暂时无法校验 | `needs_attention=1, attention_msg NOT NULL` |
| Re-validation in progress (after 重试) | 重新校验中 | `needs_attention=1, attention_msg IS NULL` |
| Kept although not recognised (collected, never pushed) | 仅收藏 | `needs_attention=0, is_valid_english=0` |
| Finish yesterday's open batch | 继续昨天的学习 | `TodayResponse.previous_open_batch` |
| Example sentence / image / pronunciation | 例句 / 配图 / 发音 | |
| Streak | 连续学习 N 天 | `streak_days` |

Copywriting rules: short friendly sentences, full-width punctuation in Chinese copy, buttons are verbs (开始学习 / 显示释义 / 标为不熟悉), every empty state carries one action, error toasts give cause + action (「网络开小差了，请稍后重试」), raw error codes never shown to non-admins, the English headword is never translated in UI chrome.

---

## 1. Tech stack (all versions verified installable from this box on 2026-10-14)

### 1.1 Backend

| Component | Pin | Why |
|---|---|---|
| Python | 3.12.3 (system) + venv | PEP 668 blocks `pip --user`; `python3 -m venv` verified. Stdlib covers `sqlite3` (3.45.1: `RETURNING`, partial indexes, `VACUUM INTO`), `zoneinfo`, `smtplib`, `subprocess`, `threading`, `hashlib`, `secrets`. |
| FastAPI | `fastapi==0.143.*` | Pydantic validation, OpenAPI, sync endpoints in a thread pool (SQLite-friendly). |
| uvicorn | `uvicorn[standard]==0.54.*` | `workers=1`, `--limit-concurrency 200`. |
| Pydantic | v2 (bundled) | request/response DTOs = `wd/schemas.py`. |
| bcrypt | `bcrypt==5.*` | passwords 8–64 chars (5.x rejects > 72 bytes; UTF-8 length checked). |
| httpx | `httpx==0.28.*` | sync client for Wikimedia/Openverse/webhooks/SMTP-less; `MockTransport` in tests; `sni_hostname` extension for DNS-pinned downloads. |
| Pillow | `Pillow==12.*` | verify/decode/re-encode JPEG, strip metadata. |
| defusedxml | `defusedxml==0.7.*` | parse Claude SVG safely before allow-listing. |
| pytest | `pytest==9.*` | tests. |
| Scheduler/queue | none (own 60-s tick thread; SQLite `jobs` table) | restart-safe because state lives in SQLite. |

Not chosen: Node backend (`node:sqlite` experimental warning; `better-sqlite3` native build), SQLAlchemy/Alembic, APScheduler, Tailwind/TanStack/zustand (needless surface), Docker for the app (`claude` credentials live in `/home/sqin/.claude*` and must be used as `sqin`), `--bare` (disables OAuth), FTS5 (unicode61 does not match inside CJK tokens; `LIKE` on 9k rows is < 10 ms).

### 1.2 Frontend

| Component | Pin | Notes |
|---|---|---|
| React / react-dom | `19.3.x` | |
| react-router | **`^7.18`** (`react-router@7`) | npm `latest` is 8.4.0 and requires React ≥ 19.2.7 — an unpinned install breaks; pin `^7`. Library (declarative) mode, no loaders/actions. |
| Vite | `8.3.x` | Node 22.22 verified. |
| @vitejs/plugin-react | `^6.1` | 6.x requires Vite 8. |
| TypeScript | `~5.9` | npm `latest` is 7.0.2 (new native compiler) — pin 5.9. |
| Styling | plain CSS, custom properties, mobile-first, `prefers-color-scheme` | no CSS framework, no CDN/web fonts (works on an intranet). |
| State | `AuthContext` + per-page hooks + a 60-line fetch wrapper | only global state is "who am I", settings, toasts, and the in-session study queue (reducer). |
| TTS | Web Speech API | free, client-side. |
| Tests | `tsc --noEmit`, `vite build`, `vitest` 5 (jsdom) for pure helpers | |

### 1.3 Repository tooling

`Makefile`: `setup` (venv + npm ci), `dev` (uvicorn --reload + vite), `build`, `test` (pytest + tsc + vitest + vite build), `smoke` (end-to-end with fake claude), `seed` (rebuild seed from ECDICT), `install` (deploy/install.sh). `ruff` optional.

---

## 2. Repository layout and data directory

```
word-Dance/
├── README.md  LICENSE(MIT)  ATTRIBUTION.md  Makefile  .gitignore  .editorconfig        # the env template is deploy/env.example (no root .env.example)
├── backend/
│   ├── pyproject.toml                 # project "word-dance", package "wd", console script "wd"
│   ├── requirements.txt  requirements-dev.txt
│   ├── wd/
│   │   ├── __init__.py  main.py  config.py  db.py  errors.py  deps.py  schemas.py  interfaces.py  clock.py  security.py  cli.py  diag.py
│   │   │                                  # cli.py itself implements `serve`, `migrate`, `version`; other commands register from CLI_MODULES (TASKS P0)
│   │   ├── migrations/0001_init.sql   # == SCHEMA.sql
│   │   ├── routers/   health(P0, implemented) auth account onboarding settings vocab words screen bank suggestions today history media audio admin_users admin_ops admin_reports
│   │   ├── services/  stats_core(P0: daily_stats.on_action, §7.1) words ecdict bank srs batches screen stats suggestions
│   │   ├── jobs/      queue.py registry.py worker.py scheduler.py
│   │   ├── ai/        runner.py budget.py content.py lookup.py consolidate.py svg.py prewarm.py probe.py prompts/*.txt schemas/*.json   # prewarm.py = the prewarm_plan handler
│   │   ├── images/    providers/{base,wikimedia,openverse,pixabay,pexels}.py select.py fetch.py store.py quota.py card_svg.py sanitize_svg.py handler.py
│   │   ├── delivery/  mailer.py email.py webhook.py templates/daily_email.html daily_email.txt
│   │   ├── seed.py  backup.py  audio.py   # audio.py = server-side pronunciation clips (§9 「Pronunciation clips」)
│   └── tests/  conftest.py fake_claude.py fixtures/ unit/ integration/
├── frontend/   package.json package-lock.json (committed: install.sh runs `npm ci`) vite.config.ts tsconfig.json index.html src/…   (see FRONTEND.md)
├── data/
│   ├── seed/vocab.jsonl.gz  stats.json  ATTRIBUTION.md      # verified seed, gzipped (≈1.2 MB)
│   └── licenses/ECDICT-LICENSE                               # MIT text
├── scripts/  build_seed.py (verified builder, verbatim)  smoke.py  dev.sh
├── deploy/   install.sh  word-dance.service  word-dance-backup.service  word-dance-backup.timer  env.example  Caddyfile.example  nginx.conf.example
└── docs/     DESIGN.md API.md CLAUDE_INTEGRATION.md FRONTEND.md DEPLOY.md TASKS.md SCHEMA.sql ops.md qa.md qa-frontend.md qa-study.md
```

Data directory `WD_DATA_DIR=/home/sqin/word-dance-data` (outside the git checkout, mode 0700, owned by `sqin`):

```
word-dance.db (+ -wal, -shm)     SQLite (0600)
.env                             secrets & config (0600) — EnvironmentFile of the unit
images/<2hex>/<sha256>.jpg       re-encoded photos (≤ 800 px) ; .svg for sanitised Claude SVG
audio/<2hex>/<sha256>.m4a|.mp3   cached pronunciation clips (GET /media/audio, §9 「Pronunciation clips」; capped by WD_AUDIO_CACHE_MB) — a cache, safe to delete; under WD_AUDIO_PROVIDER=cache the read-only mirror of another host's clips (deleting it = `missing` until the next sync)
claude-cwd/                      EMPTY dir used as cwd for `claude -p`
claude-logs/YYYY-MM-DD/<call_id>.json   raw CLI stdout/stderr, kept 14 days, 0600
backups/word-dance-YYYYMMDD-HHMM.db.gz  nightly (timer) + pre-migrate-<version>.db.gz
tmp/                             downloads in flight
frontend -> frontend-releases/<sha>     symlink to the live SPA snapshot (WD_FRONTEND_DIST), swapped atomically by install.sh after the stop; resolved by `wd serve` at startup
frontend-releases/<sha>/         built SPA snapshots (index.html, assets/), one per deployed commit, the two newest kept
```

`git pull && deploy/install.sh` never touches the data directory.

**Seed location.** The compact seed ships in the repository at `data/seed/vocab.jsonl.gz`, *outside* the `wd` package. Its path is a config value, `WD_SEED_PATH`, defaulting to `Path(wd.__file__).parents[2] / 'data' / 'seed' / 'vocab.jsonl.gz'` (the repo root resolved from the installed package — correct for the `pip install -e backend` layout install.sh uses). `wd import-seed --file` defaults to it, and the lifespan's seed check (`main.seed_check`) compares `kv.seed_version` with the sha256 of the **decompressed content** of the file at `WD_SEED_PATH` (`seed.seed_digest`; import when they differ, warn-and-continue when the file is missing — a `.gz` re-packed by another gzip is still up to date, while migration 0011's `DELETE FROM kv WHERE key='seed_version'` forces exactly one import). The check never fails startup: an import error is logged with its traceback, recorded as `system_events('seed_import_failed')` for the admin page, and the service starts on the vocabulary it already holds (WORD_LIBRARY_CURATION §1.2). A non-editable install must set `WD_SEED_PATH` explicitly (DEPLOY §4).

---

## 3. Data model (full DDL in `SCHEMA.sql`)

Conventions: timestamps are UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` (SQL default `strftime('%Y-%m-%dT%H:%M:%SZ','now')`, Python `clock.now_iso()`), local dates `YYYY-MM-DD` in the user's IANA timezone, booleans `INTEGER 0/1` with `CHECK`, JSON in `TEXT`. Per-connection PRAGMAs: `journal_mode=WAL, synchronous=NORMAL, foreign_keys=ON, busy_timeout=5000, temp_store=MEMORY, cache_size=-20000`. Connections are opened with `sqlite3.connect(path, autocommit=True)` (Python 3.12 API: the module never starts implicit transactions, so `executescript()` cannot sneak in an implicit `COMMIT`); `db.tx()` and `run_migrations()` issue explicit `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`; `SQLITE_BUSY` retried 3× (50/100/200 ms). One connection per request/job (never shared across threads).

### 3.1 Table groups and rationale

| Group | Tables | Rationale |
|---|---|---|
| System | `schema_migrations`, `kv`, `system_events` | migrations bookkeeping (rows written by `db.run_migrations()` only — never by a migration file; SCHEMA.sql §1); runtime flags (`seed_version` = sha256 of the decompressed seed content, `seed_imported_at`, `worker_lease`, `claude.paused_until`, `claude.flag_tier`, `last_tick_at`, `maintenance.last_date`, `consolidate:<user_id>:last_date`, `prewarm:<plan_id>:spent`); operator-visible events (downtime with `{from,to}` bounds, budget, auth failures, `seed_imported` / `seed_import_failed`, and `migration` traces a migration file leaves behind — 0011 writes one). |
| Identity | `users`, `sessions`, `invite_codes`, `auth_throttle`, `identities`, `login_codes`, `email_codes`, `user_settings` | server-side sessions (hashed tokens); invite codes hashed with uses/expiry; **persistent** login throttling (survives restarts); 6-digit phone / e-mail verification codes and the stale-phone challenge token (`login_codes`, 0018 — `email_codes` is the pre-0018 table, kept but no longer written); phone bindings with disputed rows (`identities`, 0018); one settings row per user created in the same transaction as the user. `user_settings.next_push_at` (UTC, indexed) lets the tick select due users. |
| Vocabulary (shared) | `words`, `word_forms` | one row per normalised `lemma`; stage flags `stage_xs/zk/gk/cet4/cet6` (cumulative on the national chain by construction — xs ⊆ zk, every 小学 word is a 初中 word too —, zk ⊄ gk by design — the senior lists drop everyday junior words —, CET flags cumulative as in their sources) + `stage_min` (1–5, lowest stage; `NULL` = outside the official lists: a 课标外 dictionary word, visible only in 全部 and search, never selected for 筛词/推荐词) which gives the 仅本阶段新增 filter for free (`stage_min = 5` is the CET-6 increment; per-stage counts are `data/seed/stats.json.per_stage` / `first_stage`); `wd check db` asserts `stage_min` = index of the lowest flag and xs ⊆ zk (`diag.STAGE_INVARIANTS`; `scripts/rehearse_migration.py` runs the same SQL after a migration); `kind` (word/phrase/abbreviation/proper_noun) keeps acronym casing; `is_public`/`is_valid_english`/`safe_for_sharing` gate user-added words; `merged_into_word_id` for consolidation merges. `word_forms` is keyed `(form, word_id)` so ambiguous forms are representable (FACTS §4b counts 47 in the raw exchange data; after dropping the 11 empty strings and the headword-forms, 28 remain in the seed — e.g. bases→base/basis, axes→ax/axe/axis; acceptance pins only `bases` → 2); forms that are themselves headwords (388, e.g. data, better, running, clothes) are never inserted — the headword guard of the seed import and of `words.add_form`. `kind` is an ECDICT exchange code `p d i 3 s r t`, `alt` (a `lookup_word` merge / the suffix rule) or, since migration 0013, `alias`: an official list's spelling of a headword (`data/lists/aliases.tsv` — `Mr` → `mr.`, `PE` → `p.e.`, `hot-dog` → `hot dog`) written by the seed import from the record's `aliases[]` so that lookup and search resolve the official spelling before falling back to ECDICT (whose undotted `Mr` is something else); the headword guard applies to alias rows as well. The one deliberate exception is a `lookup_word` **merge** (CLAUDE_INTEGRATION §6.5 step 3): it records `W.lemma → L` as an `alt` form while the merged-away row `W` keeps its lemma with `merged_into_word_id = L`; resolution is unaffected (the exact step already follows the merge), so on a live database the invariant reads `word_forms wf JOIN words w ON w.lemma = wf.form AND w.merged_into_word_id IS NULL` = 0 (the WP1 acceptance query without that predicate holds on a fresh import). |
| Generated (shared) | `word_contents`, `word_images`, `word_dances` | versioned per word; exactly one `active` row each; `words.active_content_id/active_image_id` are logical pointers (no FK cycle). Content is **never per user**. |
| Per-user learning | `user_words`, `review_logs`, `daily_stats` | one row per (user, word) ever touched; SRS fields on the row; `review_logs` is the append-only history with `client_event_id` idempotency and a `prev_srs_json` snapshot on every `master`/`known` transition (what `restore` puts back); `daily_stats` powers heatmap/streak cheaply. |
| Daily push | `push_batches`, `push_items` | `UNIQUE(user_id, local_date)` is THE idempotency guarantee; items carry `kind` review/new/screen/extra and are unique per `(batch_id, word_id, kind)` — a 推荐词 graded 不熟悉 inside the batch keeps its `screen` row and gains a `new` row (§6.3). |
| Consolidation | `consolidation_runs`, `bank_suggestions` | audit of nightly 整理 and the user-facing 整理建议 inbox (open/accepted/rejected/expired/auto with 7-day 撤销). |
| Jobs & accounting | `jobs`, `ai_calls`, `provider_usage`, `provider_state`, `content_reports` | durable queue with dedupe keys and `UPDATE … RETURNING` claims; one ledger row per `claude` spawn (inserted *before* the spawn); provider quota counters per minute/day window persisted; user reports for content/image/dictionary problems. |

**Current schema, and where the stage model stops.** `SCHEMA.sql` is the 0001 baseline byte for byte (`test_db.py`); the current schema = 0001 + 0008 + 0009 + 0010 + 0011 + 0012 + 0013 + 0014 + 0015 + 0016 + 0017 + 0018 + 0019 (`words.learn_rank`, `user_settings.dance_mode`; 0016 rebuilds `jobs` / `ai_calls` for `generate_dance` / kind `dance`, adds `word_dances` and `words.active_dance_id` / `dance_state`; 0017 adds the nullable `word_dances.corrected` flag, docs/WORD_DANCE_DESIGN.md §13; 0018 adds `identities`, `login_codes`, the nullable `users.password_set_at` (backfilled to `created_at`) / `account_kind` / `guardian_user_id` / `age_band` / `age_declared_at` / `age_declared_ip` / `guardian_consent_at` / `guardian_pin_hash` and `sessions.actor_user_id` — slice 1-A of docs/AUTH_SIGNUP_DESIGN.md §5.1; 0019 adds `family_codes` (child login codes and claim codes, HMAC-hashed), `users.profile_prompted_at` and `sessions.guardian_gate_at` — slice 1-B, docs/releases/2026-11-auth-signup-1b.md). The current DDL of `words` and `user_settings` is the header of `backend/wd/migrations/0011_primary_stage.sql` (five flags, `stage_min` / `current_stage` 1..5, defaults `'["xs","zk"]'` / `1`), `word_forms` is `0013_word_forms_alias.sql`, the four `word_images` columns `prompt_version` / `model` / `text_free` / `eval_json` are `0012_word_images_meta.sql`; no `SCHEMA_CURRENT.sql` is kept (one more DDL copy is one more drift point, and `sqlite_master` is always there). Stages are an **enum** (`schemas.STAGE_ORDER`, index = position + 1) with one flag column per stage, not data: there is no `stage_defs` / `word_stage_tags` table, no per-user 上海/全国 scheme, no 拓展 (textbook) layer and no province dimension. Everything a richer model needs is already kept in `words.sources` (the provenance tokens of §3.2), so the target model — *stages as data*: `stage_defs(code, name_zh, position)`, `word_stage_tags(word_id, stage_code, source_token)`, `user_settings.scheme` — is reachable by one later migration that backfills the tag table from the tokens with a single SQL statement (≈ 11–14 person-days end to end). It is triggered by any of: ① the product decides on a per-user 上海/全国 scheme; ② a cleanly licensed textbook word list asks for a 拓展 layer (a sixth "stage" that is not a stage); ③ a third stage has to be added — a flag column plus a rebuild migration per stage stops scaling there. Until then adding a stage means `STAGE_ORDER` + `STAGE_INDEX`, one rebuild migration like 0011, `types.ts` / `API.md §9` / `StageChips`, and the seed builder's manifest.

### 3.2 Seed record → `words` mapping (record format **v2** of `data/seed/vocab.jsonl.gz`; v1 files without `lemma` / `seed_v` / `aliases` import unchanged)

| Seed field | `words` column | Note |
|---|---|---|
| `word` | `display`; `lemma = normalise(word)` | keeps ECDICT casing (`China`, `a.m.`, `ice cream`); `data/lists/overrides.tsv` may change the display (`e-mail`) |
| `lemma` | — (checked) | the builder's lemma; the importer recomputes `normalise(word)`, counts a disagreement (`SeedStats.lemma_mismatch`) and keeps its own value |
| `phonetic` | `phonetic` | already `ә→ə`, `:→ː` normalised by the builder |
| `translation[]` | `translation` (`'\n'.join`) | zh lines |
| `definition[]` | `definition` (`'\n'.join`) | en lines |
| `pos`, `collins`, `oxford`, `bnc`, `frq` | same names | `0`/`null` frequency = unknown; `frq` (else `bnc`) feeds the derived `learn_rank` (row below) and is only the tie-break tail of every list (`learn_order.FRQ_TAIL`) |
| `stages[]` | `stage_xs/zk/gk/cet4/cet6`, `stage_min` | codes in `schemas.STAGE_ORDER` order, one flag per code; `stage_min = min(stage_to_index(code))` (1 xs … 5 cet6), `NULL` for an empty list (课标外); an unknown code is counted (`SeedStats.unknown_stage_codes`, one WARNING, repeated in `system_events('seed_imported')`), never fatal — the hard gate is the builder, so an older server can read a newer seed |
| `exam_tags[]` | `exam_tags` (space-joined) | ky/toefl/ielts/gre |
| `exchange{}` | `exchange_json`; rows in `word_forms` | only codes `p d i 3 s r t`; ignore `0 1` (lemma pointers) and the undocumented duplicates `f b z` (plural/comparative/superlative copies) |
| `sources[]`, `ecdict_id`, `cet6_star` | `sources` (space-joined, sorted), `ecdict_id`, `cet6_star` | provenance tokens — table below; `cet6_star` is copied from the record (the builder sets it from the starred CET-6 list when that optional input is present and otherwise keeps the previous seed's value; the importer never reads a list) |
| `aliases[]` | rows in `word_forms` with `kind='alias'` | only on records whose official spelling differs from the lemma (`data/lists/aliases.tsv`, e.g. `["mr"]` for `mr.`); headword guard as for exchange forms |
| — | `learn_rank` | DERIVED, not in the seed: `services/learn_order.py` ranks every row from `lemma` / `pos` (through `dominant_pos`) / `frq` / `bnc` / `sources` / `stage_min` / `word_forms` as a group computation per `(stage_min, closed)` (policy `LEARN_ORDER_VERSION`, docs/analysis/2026-11-06-learn-order/DESIGN.md §1); recomputed inside every import, at every service start, nightly and by `wd learn-order` (migration 0014); a seed change may re-rank the frequency-less / dealt words of the touched stages, `updated_at` never moves; NULL = not computed yet and sorts last in its stage-distance group (the pre-0014 frequency order) |
| `variant_of`, `seed_v` | — | a parenthesised variant's headword (`color` → `colour`) and the record format (`2`); informational, ignored by the importer |
| — | `kind` | derived: contains space → `phrase`; matches `^[A-Z]{2,6}$` or contains `.` → `abbreviation`; first letter upper-case → `proper_noun`; else `word` |
| — | `source='seed'`, `is_public=1`, `is_valid_english=1`, `safe_for_sharing=1` | seed words are trusted |

`words.sources` tokens (the only provenance record; `data/seed/ATTRIBUTION.md` §5 carries the same table, `stats.json.tokens` the counts):

| Token | Meaning (source file in `data/lists/`) | Grants |
|---|---|---|
| `ecdict` | ECDICT carries any exam tag for the word | — |
| `cet4` / `cet6` / `cet46` | membership in the mahavivo CET lists (optional builder input; existing rows keep their flags when the lists are absent) | cet4 / cet6 |
| `moe22:l2` / `moe22:l3` / `moe22:app` | MOE 2022 Level 2 / Level 3 / appendix (`moe-2022-*`) | xs / zk / per appendix group (数词·月份·星期 → xs+zk; 地理名称·缩写·节日·地名景点·其他专有名词 → zk; 不规则动词 none) |
| `shmeea20` / `shmeea20:app` / `shmeea20:phr` | Shanghai 2020 junior words / appendix / phrases (`kind='phrase'`) | zk |
| `hs20:0\|1\|2` / `hs25:0\|1\|2` | senior 2020 / 2025 revision, star level (0 none, 1 ★, 2 ★★; `hs25` is `provisional`) | gk |
| `inherit:be` / `inherit:have` / `inherit:do` | a person form inherits its base verb's stages (`manifest.inherit_stages`: `am, is, are, does`) | the base verb's stages |
| `legacy:zk` / `legacy:gk` | the word carried `stage_zk` / `stage_gk` in the 75df534 seed (old 中考 list ∪ ECDICT zk / old Highschool list ∪ ECDICT gk); kept as evidence and as the candidate set of a future 拓展 layer | — |

The bare `zk` / `gk` tokens of the previous seed no longer exist (renamed `legacy:*`); the two national-name appendices of the senior standards and the Shanghai forms table are archived with `policy: reference` and grant nothing.

**Acceptance numbers are never copied into prose or tests**: `data/seed/stats.json` (v2 — `total_words`, `per_stage`, `first_stage`, `only_stage`, `per_kind`, `stageless`, `tokens`, `lists[]`, `content_sha256`, …) is the single source. `test_seed.py`'s `@full_seed` gate, TASKS WP1's acceptance block, API.md and the README read it; `data/seed/DIFF.md` (written by `scripts/seed_diff.py` during `make seed`) lists what moved against the previous seed and fails the build when a lemma disappears or xs ⊄ zk. Invariants the gate asserts on the imported database: `stage_min` = index of the lowest flag; xs ⊆ zk; no bare `zk` / `gk` token; the `word_forms` headword guard (`JOIN words ON lemma = form` = 0); every `aliases[]` entry present as a `kind='alias'` row. (The 75df534 seed measured 9,162 words — zk 2,099 · gk 3,829 · cet4 4,722 · cet6 7,671 — and ≈ 14,100 `word_forms` rows; history, not acceptance constants.)

### 3.3 Size

~9.2k `words` (~5 MB with definitions), ~14k `word_forms`, per word one `word_contents` (~1.5 KB) and one `word_images` file (50–120 KB JPEG). Realistic first year (a few thousand words with content) ≈ 300 MB. 92 GB free.

---

## 4. Word-bank lifecycle and state machine

States of `user_words.state`: `∅` (no row) · `new` (marked 不熟悉, never graded) · `learning` (graded ≥ 1 time; SRS active, includes review and relearning phases) · `mastered` (user confirmed 已掌握 → out of the bank) · `known` (user said 认识 to a word that never entered the bank) · `removed` (deleted without claiming mastery). **生词库 = `state IN ('new','learning')`.**

| From | Action | To | Effects |
|---|---|---|---|
| ∅ | `unfamiliar` (from any page; `origin` from the context → origin table below) | `new` | row created with `origin`, `priority` (custom 100 · readd 80 · else 50), `added_at=first_added_at=now`, SRS defaults (`ease 2.5, interval 0, step 0, due_at NULL`); `generate_content` enqueued (priority 10 if the user is waiting, else 20) **only when `words.is_valid_english = 1`** — a provisional word (`is_valid_english IS NULL`) gets no content job here: `lookup_word` is its single content trigger (§5.2, CLAUDE_INTEGRATION §6.5) |
| ∅ | `known` (screen / browse) | `known` | excluded from 推荐词 until the user re-marks it `unfamiliar` |
| ∅ | `mastered` | `known` | treated as known (never studied) |
| ∅ | `remove`/`reset` | — | 409 `invalid_transition` |
| `new` | grade `again`/`hard`/`good` | `learning` | SRS §7; `review_logs` row; `daily_stats` |
| `new`/`learning` | `mastered` (已掌握 button / grade `master`) | `mastered` | `prev_srs_json` snapshot written to the log row first; `mastered_at=now`, `due_at=NULL`, SRS frozen for stats, open suggestions on the row → `expired`, `daily_stats.mastered+=1` |
| `new`/`learning` | `remove` | `removed` | hidden from the bank |
| `new`/`learning` | `known` | `mastered` | synonym when already in the bank (same effects as the row above, logged as `known`) |
| `new`/`learning` | `unfamiliar` | same | idempotent → `status:"exists"` (note updated if given) |
| `learning` | `reset` | `new` | SRS fields to defaults; history kept |
| `mastered`/`known`/`removed` | `unfamiliar` (deliberate re-add from the 已掌握/已认识/已移除 lists, 词库 or a card) | `new` | **re-add**: `times_added+=1`, `priority=80`, `added_at=now`, `step=0, interval=0, due_at=NULL, consecutive_good=0`; `ease = max(1.3, ease-0.2)` when coming from `mastered` (a forgotten "mastered" word grows intervals more slowly), unchanged from `known`/`removed`; `mastered_at=NULL`; logged as `readd` |
| `mastered`/`known` | `restore` (**undo**, the 8-second 撤销 toast on cards, the 5-second one on 词库 rows / 筛词 verdicts) | the state in the snapshot (`new` or `learning`; `∅`-origin `known` rows are deleted) | allowed only when the user's most recent `review_logs` row for this word is `master`/`known` and younger than **15 minutes**, else 409 `undo_expired`. Writes `prev_srs_json` back **verbatim** (state, ease, interval_days, step, repetitions, lapses, consecutive_good, due_at, last_graded_at, mastered_at); `times_added`, `priority`, `ease` and `added_at` untouched (not a re-add, no 顽固词 progress); the push item that produced the transition (study card **or** 推荐词) gets `result=NULL, graded_at=NULL` (gradable again); `daily_stats`: `mastered-=1` when the undone row's `new_state` was `mastered` (and `graded-=1` when it was a study-card grade), `known-=1` when it was `known`, `screened-=1` when it was a screening verdict (§7.1); expired suggestions stay expired; logged as `restore` |
| `new` (created from ∅ by `unfamiliar`, never graded) | `restore` (**undo** of a 不熟悉 verdict / inline toggle) | ∅ (row deleted) | allowed only when the most recent `review_logs` row for this word is `unfamiliar` with `prev_state IS NULL`, younger than **15 minutes**, and the row is still `new` with `repetitions = 0`; deletes the row (the word is a 推荐词 candidate again), clears `result`/`graded_at` on the screen push item that produced it, deletes an ungraded `kind='new'` row appended for the word in an open batch, `daily_stats.added-=1` (and `screened-=1` for a screening verdict); a `generate_content` job already enqueued is left alone (content is global); logged as `restore`. An idempotent `unfamiliar` (`status:"exists"`) or a `readd` is never undone this way |
| `mastered` | `known`/`mastered` | `mastered` | no-op 200 |
| `known` | `mastered` | `known` | no-op 200 |
| `mastered`/`known` | `remove` | `removed` | hides from the 已掌握/已认识 lists |
| `removed` | `remove` | `removed` | no-op |
| any | `restore` without an eligible `master`/`known`/∅→`unfamiliar` log row within 15 minutes | — | 409 `undo_expired` |

Every transition writes one `review_logs` row. **API action → `review_logs.action` mapping** (the CHECK list in SCHEMA.sql is exactly this set):

| Caller | `review_logs.action` |
|---|---|
| grade `again` / `hard` / `good` / `master` / `skip` (endpoint 45) | same name |
| `mark {action:"unfamiliar"}` from `∅` / idempotent on `new`+`learning` | `unfamiliar` |
| `mark {action:"unfamiliar"}` from `mastered`/`known`/`removed` | `readd` |
| `mark {action:"known"}`, screen verdict `known` | `known` |
| `mark {action:"mastered"}` | `master` |
| `mark {action:"remove"}` | `remove` |
| `mark {action:"reset"}` | `reset` |
| `mark {action:"restore"}` | `restore` |
| `POST /api/bank/add`, `/api/bank/add-word` (new rows) | `add_custom` (re-adds log `readd`) |
| `POST /api/bank/import` | `import` |
| `POST /api/bank/{id}/accept-suggestion` | `remove` (flagged row) + `add_custom` (target row) |
| `lookup_word` merge, consolidation repoint / merge (incl. the losing row → `removed`), suggestion accept/undo that repoints | `consolidate` |
| `lookup_word` merge / accepted consolidation merge whose target the user holds only as `mastered`/`known`/`removed` while the source row is in the bank: the held row re-enters the bank (`times_added+1`, priority 80, ease penalty from `mastered` — the re-add row above; CLAUDE_INTEGRATION §6.5 step 3, §6.6) and the source row is parked as `removed` | `readd` (held row, `context='consolidate'`) + `consolidate` (source row → `removed`) |
| `PATCH /api/bank/{id} {note}` | `note` |
| `PATCH /api/bank/{id} {attention:'keep'\|'retry'}` (保留 / 重试 on a 待处理 row, API.md 36) | `attention` (`result_json={"decision":…}`) |

**Context → `origin` mapping** (a `user_words` row is created only by `unfamiliar`, `known`, `add_custom`, `import`; `origin` records how it *first* entered and is never changed by a re-add). `review_logs.context` is what the client sent, or `'api'` when omitted:

| Caller / `context` | `user_words.origin` |
|---|---|
| `mark` with `context` `browse`, `detail`, `bank`, or omitted (`api`) | `browse` |
| `mark` with `context` `today` · endpoint 45 grades and in-batch 推荐词 verdicts (`context` `today`/`extra`) | `push` |
| endpoint 32 verdicts (`context` `screen_page` / `onboarding`) · `mark` with `context` `screen_page` | `screen` |
| `POST /api/bank/add`, `/api/bank/add-word`, `/api/bank/{id}/accept-suggestion` (target row) | `custom` |
| `POST /api/bank/import` | `import` |

(`detail` is a log context, not an origin — the §0.1 table's "detail" button writes origin `browse`.)

The mastery decision is always the user's; the SRS only *suggests* (§7). UI: when `mastery_suggested` is true the 已掌握 button is primary with a 建议 badge and acts immediately with an 8-second 撤销 toast (calls `mark {action:"restore"}`); when not suggested, a confirmation sheet appears first («确定已掌握？该词将移出生词库，随时可在「已掌握」中恢复。» — that later 恢复 is the deliberate `unfamiliar` re-add).

Re-marking a mastered word is deliberate and cheap: history preserved, the bank row shows 「第 N 次加入」, the card back shows 「上次掌握于 3月12日」; words with `times_added ≥ 3` sort first among the day's new words (顽固词) and the history page lists them under 反复遗忘.

---

## 5. Custom words: normalisation, lemma resolution, privacy

### 5.1 Normalisation (`services/words.normalise_input(text) -> Normalised | Invalid`)

1. `unicodedata.normalize('NFKC')`; map `’ ‘ ʼ` → `'`, `– —` → `-`; collapse whitespace; strip surrounding punctuation `,;:!?"()[]{}<>` (not `.`, which may be part of an abbreviation); trim.
2. Reject (`invalid_word`, zh reason) if: empty; > 48 chars; > 4 space-separated tokens (phrases like `ice cream`, `ought to`, `take off` are fine); any char outside `[A-Za-z' .-]`; a token that is only `' - .`; a `.` inside a token longer than 6 chars (`a.m.`, `e.g.`, `etc.` pass; `example.com` fails); starts with `-` or `'`.
3. Casing: a single token matching `^[A-Z]{2,6}$` keeps upper case (`CPU`, `GDP`, `NASA`) and `kind='abbreviation'`; otherwise `display` keeps the user's first-letter casing only if the token is capitalised (proper-noun hint) and `lemma = lower(normalised)`.
4. The same rules run client-side for the live preview; the server is authoritative.

### 5.2 Resolution (`services/words.resolve(conn, key, display, kind, user_id) -> Resolution` — `key`/`display`/`kind` come from `normalise_input`; signature frozen in TASKS §I), first hit wins

1. **exact** — `words WHERE lemma = :key` (follow `merged_into_word_id`). Because headword-forms were never inserted into `word_forms`, `data`, `better`, `running`, `clothes` resolve to themselves here.
2. **form** — `word_forms WHERE form = :key`: exactly one lemma → that word with `lemma_note_zh` («已归为原形 go（过去式）»); several lemmas (the 28 ambiguous forms of the seed) → `via='ambiguous'` with `candidates` — the word is **not** added; the client shows the candidates as chips and commits with `POST /api/bank/add-word {word_id}`. Never pick by frequency silently.
3. **ecdict** — only if `WD_ECDICT_DB_PATH` points at a `stardict.db`: `SELECT … FROM stardict WHERE word = :key COLLATE NOCASE`. If the row's `exchange` has `0:<lemma>` **and** the row carries no stage tag **and** its `frq` is 0/NULL while the lemma row has a tag or `frq > 0`, insert/lookup the lemma (`source='ecdict'`) and add `word_forms(key → lemma)`; otherwise insert the row itself. ECDICT rows are dictionary data, so they are created with `is_public=1, is_valid_english=1` — except rows whose only translation starts with `[网络]` (network slang of doubtful validity), which are created with **`is_public=0`**, `is_valid_english=NULL`, `safe_for_sharing=NULL`, `created_by_user_id=me` and get `lookup_word` enqueued exactly like a provisional word (they become public only when the lookup passes, through the same rule as step 4); a NULL phonetic alone is filled by the nightly `fill_data` and does not block validity.
4. **provisional** — insert `words(lemma, display, kind, source='user', is_public=0, is_valid_english=NULL, safe_for_sharing=NULL, created_by_user_id=me, stage_min=NULL)` and enqueue `lookup_word` (`dedupe 'lookup:<word_id>'`, priority 10, `run_after = now + 20 s` so several pasted words share one call — the worker batches up to 20 lookups per `claude` invocation). The bank row exists immediately with badge **待校验**. **No `generate_content` is enqueued for a provisional word** — `lookup_word` enqueues it once the word is validated (CLAUDE_INTEGRATION §6.5), so gibberish never costs a content call and content is never attached to a row that lookup then merges away. If the exact-match step 1 hits a word with `is_valid_english = 0` (a string someone already added and Claude rejected), the bank row is created at once with `needs_attention=1`, `attention_msg='未识别为英文单词'` (a typo correction, if any, is re-proposed by the nightly consolidation); status `added`, no job enqueued (the word is visible to the new holder through the visibility rule below).

**Visibility rule (the one definition; API.md §1 restates it verbatim):** a `words` row is visible to user `me` iff `is_public = 1 OR created_by_user_id = me OR EXISTS (SELECT 1 FROM user_words uw WHERE uw.user_id = me AND uw.word_id = words.id)`; admins see every row. It is applied by vocab/letters, lookup, detail, content, image, card (`/media/card`), screen and today routes; the bank list needs no filter (the user's own row is the grant). Consequences: two users adding the same unknown string share one provisional row (UNIQUE lemma) and **both** see it — detail page, content poll and card image all work for both — while a third user does not see it in search/lookup/推荐词; a word Claude rejected (`is_valid_english=0`, private forever) stays visible to everyone who holds it. A private word becomes public only when `lookup_word` returns `is_english=true` **and** `safe_for_sharing=true` (CLAUDE_INTEGRATION §5). Account deletion deletes a private word only when no other `user_words` row references it (API.md endpoint 8).

### 5.3 Bulk add (`POST /api/bank/add`)

Split `text` on `\n , ; ， ； \t` (never on spaces), cap 50 tokens per call, 200 custom adds/day/user; dedupe within the request by `lemma`; per item `status ∈ added | readded | exists | pending_ai | ambiguous | invalid`. `study_today=true` appends words resolved via `exact`/`form`/`ecdict` (i.e. `is_valid_english = 1`) to today's batch as `kind='extra'` (cap 20/day; a word already present as `review`/`new`/`extra` is skipped, one present only as `screen` gets its study row) so a word met at work can be studied the same day; a provisional word (`pending_ai`) cannot be studied before validation — it joins the first batch built after `lookup_word` clears it (`added_to_today:false`, toast 「已加入生词库，明天开始学」). `note` (≤ 500) is stored on the row and is **private**: it is never sent to the shared `generate_content` prompt (whose output is visible to every user once the word is public); its first 120 sanitised chars are passed only to the per-user `consolidate_bank` prompt, whose verdicts are private suggestions (CLAUDE_INTEGRATION §5.2, §5.4).

### 5.4 Consolidation (整合与更新) — two Claude jobs, specified in `CLAUDE_INTEGRATION.md`

* `lookup_word` (minutes after an add): validates provisional words, fills `phonetic/translation/definition/pos/difficulty/kind`, proposes a canonical headword and, for misspellings, a `suggested_correction`. Application rules: a proposed headword mutates shared data only if it passes the deterministic validator (same charset/length/token rules as user input **and** relatedness: equals the input, or the input is in the target's `word_forms`, or they share the first 3 letters) — otherwise it is stored as a suggestion. Typo corrections are **never** auto-applied: they set `suggested_word_id` and the bank row shows 「是否改为 “receive”？」 with a 替换 button. `is_english=false` → `needs_attention=1`, 「未识别为英文单词」 with 修改 / 保留 / 删除; a lookup that could not run (dead job, AI off) → 「暂时无法校验」 with 修改 / 重试 / 保留 / 删除. The buttons are defined once (API.md 36): **修改** = client-side `mark {action:'remove'}` + `/bank/add?prefill=<input_text>`; **保留** = `PATCH {attention:'keep'}` → clears the flag; for an `is_valid_english=0` word this means 仅收藏 — the row stays in the bank list with a 仅收藏 chip but §6.3 step 3 never pushes it and no content is generated; **重试** (only while `is_valid_english IS NULL`) = `PATCH {attention:'retry'}` → re-enqueues `lookup_word` once (dedupe `lookup:<id>`, priority 10), badge 重新校验中 until it resolves; **删除** = `mark {action:'remove'}`; **替换** = `POST /api/bank/{id}/accept-suggestion`. 保留 and 重试 log `review_logs.action='attention'`.
* `consolidate_bank` (nightly per user 02:30 local, or on demand): examines the **whole** bank (≤ 80 changed/unvalidated items per run plus the full headword list for duplicate detection) and returns verdicts `ok | lemmatize | merge_duplicate | fix_spelling | invalid_word | split_phrase | fill_data`, `confusable_groups`, `difficulty_tags`. Auto-applied (status `auto`, 7-day 撤销): `fill_data` for NULL fields of non-seed words, `difficulty` when NULL, and `lemmatize` **only** when the target exists in `words`, the input is a known inflection of it (in `word_forms` or passes the suffix rules) and the target is not already in the user's bank. Everything else (spelling fixes even when the typo is itself an ECDICT headword, merges of two bank entries, invalid words, phrase splits) becomes an open suggestion in 整理建议 with accept/reject; suggestions expire after 30 days. Confusable groups are stored and shown as 「易混：abundant」 chips.

---

## 6. Daily push (每日推送)

### 6.1 Per-user settings (`user_settings`)

| Column | UI label | Default | Range |
|---|---|---|---|
| `timezone` | 时区 | `Asia/Shanghai` | `zoneinfo.available_timezones()` |
| `push_time` | 推送时间 | `08:00` | `HH:MM` |
| `push_enabled` | 每日推送 | 1 | scheduled build/publish; `GET /today` + 立即生成 still work when 0 |
| `daily_new_count` | 每日新词 | 10 | 0–50 |
| `daily_screen_count` | 每日推荐词 | 15 | 0–50 (0 disables 推荐词) |
| `max_reviews` | 每日最多复习 | 60 | 0–300 (overflow is deferred, shown as 顺延 N 个) |
| `stages_json` | 目标阶段 | from onboarding (multi); DDL default `'["xs","zk"]'` = `bank.DEFAULT_STAGES` (pinned to the DDL by `test_bank_defaults.py`) | non-empty subset of xs/zk/gk/cet4/cet6; unknown codes are filtered at read time and an all-unknown row falls back to the default with a `stage_fallback` warning (`bank.user_settings_row`); `wd check db` lists such rows (`stages_json_known`) |
| `current_stage` | 主攻阶段 | from onboarding; DDL default `1` (xs) = `bank.DEFAULT_CURRENT_STAGE` | stored 1–5 (1 xs … 5 cet6; migration 0011 renumbered the stored 1–4 to 2–5), `Stage` string on the wire (API.md §9.1); 推荐词 ordering starts here and moves outward (`bank.current_stage_index`: `None` → the default, never `int(x or …)`) |
| `show_images`, `zh_examples` (`tap`/`always`), `auto_pronounce`, `accent` (`en-US`/`en-GB`) | 学习设置 | 1, `tap`, 1, `en-US` | |
| `dance_mode` | 单词之舞 | `full` | `full` / `form_only` / `off` (migration 0015, additive); `full` = the spelling + stress dances plus the semantic dance at the reveal (P2), `form_only` = the spelling + stress dances only, `off` renders the plain headword (docs/WORD_DANCE_DESIGN.md §6.3 / §11, `backend/wd/dance.py`) |
| `email_enabled` | 邮件推送 | 0 | requires verified e-mail + server SMTP |
| `webhook_enabled`, `webhook_url`, `webhook_format` | Webhook 推送 | 0, –, `generic` | `generic`/`wecom`/`feishu`/`serverchan`/`bark`; https + SSRF check |
| `next_push_at` | (read-only 下次推送) | computed | UTC; recomputed on save and after each publish by the pure `clock.compute_next_push()` |

### 6.2 Onboarding (first login)

`users.onboarding_state ∈ 'pending' | 'screen' | 'done'`. Registration (API.md 2) already inserts the `user_settings` row **with `next_push_at` computed from the defaults** (`Asia/Shanghai`, `08:00`) in the same transaction, so the tick's `WHERE next_push_at <= …` never silently skips a user. `/welcome` step 1 (`POST /api/onboarding`): 目标阶段 multi-select (default pre-checked by self-description buttons: 小学生 → xs (主攻 xs) · 初中生 → xs+zk (主攻 zk) · 高中生 → zk+gk · 大学生 → gk+cet4+cet6 · 职场人士 → cet4+cet6; before a button is pressed the form shows `DEFAULT_PRESET` = 小学 + 初中 / 主攻 小学, the mirror of the `user_settings` DDL default and `bank.DEFAULT_*`), 主攻阶段, 推送时间, 时区 (auto-detected via `Intl.DateTimeFormat().resolvedOptions().timeZone`) → state `screen`, `next_push_at` recomputed. Step 2: 筛词 of 20–30 words from `current_stage` (`GET /api/screen/next`); skippable. `POST /api/onboarding/complete` sets `done` **only from `screen`** (409 `invalid_transition` from `pending`; idempotent from `done`), so no client path reaches `done` without step 1. **Gate**: until `done`, the SPA redirects `/`, `/today`, `/study`, `/history` and `/history/:batchId` to `/welcome` (`RequireOnboarded`, FRONTEND §2) and the API answers 409 `onboarding_required` on the `O` endpoints (`/api/today*`, `/api/history*`, `/api/batches/*`, `/api/stats`); browsing 词库, the 生词库, 筛词, word pages and 设置 work before onboarding (their endpoints are `U`) — one rule in DESIGN, API.md §1 and FRONTEND §2. The default stage range and recommendation order therefore always derive from the user's own choice; inside a stage-distance group the order is the derived learning order `learn_rank` (§3.2), not adult corpus frequency.

### 6.3 Batch composition (`services/batches.build_batch(conn, user_id, local_date, trigger)`), one `BEGIN IMMEDIATE`

```
1. INSERT INTO push_batches(user_id, local_date, timezone, status='building', trigger)
   ON CONFLICT(user_id, local_date) DO NOTHING → if nothing inserted: return existing batch (idempotent)
2. today_end = day_start(local_date + 1, tz)                      # UTC instant
   reviews = user_words WHERE user_id=? AND state='learning' AND due_at < today_end
             ORDER BY due_at ASC, id ASC LIMIT max_reviews        # most overdue first
   deferred = count(due) - len(reviews)                           # shown as 顺延
3. news    = user_words uw JOIN words w WHERE uw.user_id=? AND uw.state='new' AND uw.needs_attention=0
             AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL      # provisional (待校验) words wait for lookup_word
             ORDER BY (times_added >= 3) DESC, priority DESC, added_at ASC, id ASC LIMIT daily_new_count
4. screens = words w WHERE w.is_public=1 AND w.merged_into_word_id IS NULL AND w.is_valid_english=1
             AND (stage flag for any stage in stages_json)
             AND NOT EXISTS (user_words for this user and word)
             ORDER BY stage_distance(w.stage_min, current_stage) ASC,          # 0 for the 主攻阶段, then higher stages, then lower, 课标外 last
                      w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma
                      # = learn_order.ORDER_SQL — learn_rank is the derived learning order (§3.2); frq is only the fail-soft tail
             LIMIT daily_screen_count
             where stage_distance(s, cur) = 0 if s==cur, 2*(s-cur)-1 if s>cur, 2*(cur-s) if s<cur,
                   11 if s is NULL (learn_order.stage_distance_sql(): a row with stage flags but no stage_min sorts LAST, never first)
5. core = spread_similar(interleave(reviews, news))               # both defined below; pinned by tests/fixtures/batch_order.json
   cold_start = not core ; ordered = screens + core if cold_start else core + screens
6. INSERT push_items(position = index, kind per source, user_word_id for review/new)
7. UPDATE push_batches SET review_count, new_count, screen_count, deferred_reviews
8. UPDATE user_words SET times_pushed+=1 for review ∪ new                 # once per batch the word is placed in (§6.4 guarantees a batch is built on its own local day)
9. For each word in the batch with content_state IN ('none','failed') AND is_valid_english = 1: enqueue generate_content (priority 20);
   lacking an image: fetch_image is enqueued by the content handler        # never for is_valid_english IS NULL (none can be in the batch after step 3)
```

`push_batches.settings_json` is a write-only snapshot of the settings the batch was built with (the `stages` codes and the `current_stage` integer, `batches.py`). Snapshots written before migration 0011 keep the **old** integer index in `current_stage` (1 = zk … 4 = cet6): nothing reads it back and the `stages` codes beside it are unambiguous, so 0011 does not rewrite them (PLAN §2.1).

**`interleave(reviews, news)`** (deterministic, pure): if either list is empty return the other unchanged; else `k = ceil(len(reviews) / len(news))`; emit `k` reviews then 1 new, repeat; when one list runs out append the rest of the other in order. 26 reviews + 10 news → `k = 3` → `R R R N` × 8 (24 R, 8 N) then `R R N N` — the "3R,1N pattern" pinned in WP4. **`spread_similar(seq)`**: single stable left-to-right pass; two items are *similar* when both lemmas have ≥ 4 letters and share their first 4 letters (shorter lemmas are never similar); for each position `i`, if item `i` is similar to any item at `i-3..i-1`, move it to the first later position `j > i` where it is similar to no item at `j-3..j-1` (shifting the items in between one place left); if no such `j` exists leave it where it is. Both functions and the pinned 26R/10N expectation live in `tests/fixtures/batch_order.json`.

The builder never waits on Claude or image providers. `finalize_building()` (tick) flips `building → ready` when nothing more is coming for the batch's words: no item has `content_state='queued'` with a live content job due before the day's end, and (images on) no item has `image_state='queued'` (a fetch in flight) — a word with `image_state='none'` (prefetched or old content; no image job will ever run for it) never holds the batch —, **or immediately when nothing can be generated for it anyway**: AI disabled (`WD_AI_ENABLED=0` / `kv.claude.enabled='0'`), paused (`kv.claude.paused_until > now`), or every live content job of the batch's words has `run_after ≥ day_start(local_date+1)` (budget/monthly deferral, CLAUDE_INTEGRATION §7) — or after 2 h at the latest. `ready` therefore means "nothing more is coming today", never "everything has content"; the UI never waits for it: items render with ECDICT data + template card + 「例句生成中…」 and poll `GET /api/words/{id}/content` every 5 s (max 24 polls) unless `deferred_until` is set (then 「今日 AI 额度已用完，例句将在明天补齐」, no polling — API.md 24).

Ungraded `new`/`learning` items remain due and reappear tomorrow; ungraded `screen` words are simply re-selected. **Late sessions**: yesterday's batch stays gradable (API.md 45) while it has ungraded `review`/`new`/`extra` items; `GET /api/today` reports it as `previous_open_batch` and the 今日 page offers 「继续昨天的学习（还剩 N 个）」 → `/study?batch=<id>` with the grade bar (`Batch.gradable=true`); older batches are replay-only. `POST /api/today/more {source:'new'|'screen', count}` appends `extra` items (3 rounds/day) to any existing batch of the day, including one still `building` (appending never waits for content; 409 `batch_not_ready` only when no batch exists yet). **Word uniqueness inside a batch** is per `(batch_id, word_id, kind)` (SCHEMA): a screening verdict `unfamiliar` on a 推荐词 inside the batch keeps the `screen` row (`result='unfamiliar'`) and, while `new_done + new_remaining < daily_new_count`, `append_to_today(kind='new')` adds a second row for the same word at the end of the queue (`ScreenResponse.study_item` / `GradeResponse.study_item`); otherwise the word waits for tomorrow (toast 「已加入生词库，明天开始学」). `append_to_today` (also used by `study_today` extras and `/today/more`) never creates a second gradable row: words already present as `review`/`new`/`extra` are skipped; a word present only as `screen` gets its study row.

**Stale items.** A batch may be built up to `WD_PREBUILD_HOURS` before study and the user (or the 02:30 consolidation) may change state in between. Rules, applied by `today_response` and `grade_item` (API.md 43/45): an **ungraded** `review`/`new`/`extra` item whose `user_words.state` is no longer `new`/`learning` (mastered, removed, reset-then-removed …), an ungraded `screen` item whose word now has a `user_words` row (marked in 词库 during the day), and any item whose word has `merged_into_word_id IS NOT NULL` are hidden from `items` and excluded from every `counts` field; grading a hidden item returns 409 `invalid_transition`; graded items are history and always stay. `restore` makes a hidden item visible again by clearing its result and state. **Superseded items.** Because ungraded `new`/`learning` items reappear tomorrow (above), after a skipped day the same word has an ungraded study row in yesterday's batch *and* in today's. The **newest row is the only gradable one**: an ungraded `review`/`new`/`extra` item whose word has a `review`/`new`/`extra` row in a newer batch of the user is *superseded* and treated exactly like a stale item — hidden from `items` and every `counts` field (so `previous_open_batch.remaining`, `Batch.gradable`, `DayStats.batch_total`/`batch_done` and the heatmap of the older day cover only the words today did not re-select), 409 `invalid_transition` (`details.reason:'superseded_item'`) when graded. One word is thus one gradable card per day and the §7 trajectory (1 → 3 → 8 …) can never skip a step through a same-day double grade; `times_pushed` still counts every batch the word was placed in (step 8). Consolidation/lookup repoints (`user_words.word_id` W → L) also run `UPDATE push_items SET word_id = L WHERE word_id = W AND batch_id IN (open batches of that user)` so the card shows the merged headword (`user_word_id` is unchanged because the row itself was repointed).

### 6.4 Scheduler tick (`jobs/scheduler.py`, every `WD_TICK_SECONDS=60`)

```
tick(now):
  for s in user_settings JOIN users(is_active=1, onboarding_state='done')
           WHERE push_enabled=1 AND next_push_at <= now + WD_PREBUILD_HOURS:
      tz = ZoneInfo(s.timezone)
      target_date = max(local_date(s.next_push_at, tz), local_date(now, tz))      # never build a past day
      build_from = max(s.next_push_at - WD_PREBUILD_HOURS, day_start(target_date, tz))   # a batch is ALWAYS built on its own local day
      if target_date > local_date(s.next_push_at, tz) and now < push_instant(target_date, tz, push_time):   # back after an outage, before today's push
          UPDATE user_settings SET next_push_at = push_instant(target_date, tz, push_time) WHERE user_id=? AND next_push_at = s.next_push_at
          s.next_push_at = push_instant(...); recompute build_from        # re-anchor: built in the normal window, published + delivered at push time
      if now >= build_from:                                                             # push 01:00 → window shrinks to 00:00–01:00, never 22:00 the evening before
          batch = build_batch(user, target_date, trigger = 'scheduled' if now < s.next_push_at else 'catchup')   # no-op if it exists
      if now >= s.next_push_at:
          if publish_batch(batch):                 # UPDATE … SET status='published' WHERE status != 'published' → rowcount gates delivery
              enqueue send_email / send_webhook (dedupe 'email:<id>' / 'webhook:<id>') unless stale (> 6 h late → status 'skipped')
          UPDATE user_settings SET next_push_at = compute_next_push(now, tz, push_time) WHERE user_id=? AND next_push_at = s.next_push_at
  finalize_building()
  hourly: delete expired sessions, prune auth_throttle, requeue stale running jobs (boot_id sweep), open bank_suggestions past expires_at → 'expired' (all users)
  daily at 02:30 (per user local): for each user whose local time is ≥ 02:30 AND kv['consolidate:<user_id>:last_date'] != local_date:
      set kv['consolidate:<user_id>:last_date'] = local_date (same transaction) and, if the bank has rows changed since the last run
      or with is_valid_english IS NULL / difficulty IS NULL, enqueue consolidate_bank {"user_id", "trigger":"nightly"}
      (dedupe 'consolidate:<user_id>:<local_date>', priority 50)       # the kv guard stops the 60-s tick from re-enqueuing once the job is done
  daily at 03:30 WD_TZ (kv maintenance.last_date guard): maintenance (maintenance.prefetch() — below —, requeue dead content/lookup jobs once,
      prune claude-logs > 14 d, PRAGMA optimize, wal_checkpoint)
  kv.last_tick_at = now ; on startup, if now - kv.last_tick_at > 10 min: system_events('downtime', {"from": kv.last_tick_at, "to": now})
```

**Prefetch (the only producer of priority-30 "lookahead" jobs; FACTS §4b cost model):**

```
batches.preview_selection(conn, user_id, local_date) -> list[word_id]:
    §6.3 steps 2–4 executed READ-ONLY (no INSERT, no times_pushed, no job) for `local_date` with the user's current settings
    — the review/new/screen words tomorrow's build_batch would pick if nothing changes; today_end = day_start(local_date+1)

maintenance.prefetch(conn, now):                                     # part of the 03:30 WD_TZ maintenance
    if not ai_enabled() or kv.claude.paused_until > now: return      # nothing would run anyway
    spent, cap = budget.spent_today(), WD_AI_DAILY_BUDGET_USD
    if spent >= 0.5 * cap: return                                    # leave at least half the day's budget to real users
    for s in user_settings JOIN users(is_active=1, onboarding_state='done') WHERE push_enabled=1:
        tomorrow = local_date(s.next_push_at, ZoneInfo(s.timezone))  # the date of the user's next push
        words = [w for w in preview_selection(conn, s.user_id, tomorrow)
                 if w.content_state IN ('none','failed') AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL][:50]
        for w in words: enqueue generate_content {"word_id": w.id} (dedupe 'content:<id>', priority 30)
                        # the UPSERT keeps a lower priority if a user is already waiting; images follow from the content handler
```

Cap: 50 words/user/night (≈ $0.20 at the measured $0.004/word), on top of the daily/monthly/hourly guards that every job passes at claim time (`budget.can_spend` defers, never fails). A word prefetched tonight simply has `content_state='ready'` when `build_batch` runs 3 h before the push, so step 9 enqueues nothing for it. (Phase-0 interface: `preview_selection` in TASKS §I, owner WP4.)

Idempotency: `UNIQUE(user_id, local_date)` + the conditional `UPDATE` on publish + delivery dedupe keys + the `WHERE next_push_at = ?` guard + the per-user `consolidate:*:last_date` guard. The `build_from` clamp means a push time shortly after midnight gets a shorter prebuild window (built from 00:00 local) instead of being built the previous evening while the user may still be studying today's batch — so items graded late in the evening can never sit in tomorrow's batch as stale `review`/`new` rows and `times_pushed` is never double-counted. Catch-up after downtime builds today's batch only; missed days are not back-filled (their reviews are simply more overdue and come first). When the service returns on a later local day *before* that day's push time, `next_push_at` is re-anchored to that instant (guarded `UPDATE`), so today's batch is built in its normal window and published with its deliveries at push time; a return *after* today's push time publishes at once (`trigger='catchup'`, deliveries `skipped` when the missed push is > 6 h old). Changing `push_time`/`timezone` recomputes `next_push_at`; if the new time already passed today and no batch exists, the next tick builds it (no duplicates). `POST /api/today/build` calls the same `build_batch(trigger='manual')`; the tick later only publishes it. The downtime event's `{from, to}` bounds define `DayStats.offline` (API.md §9.1): a local day with no batch that overlaps a recorded gap.

### 6.5 Delivery channels (best-effort; the in-app page is the source of truth)

* **In-app** (always): `/today`; a dot on the 今日 tab while ungraded items exist.
* **Public URL for links** (`delivery.public_url()`): delivery jobs run inside the scheduler with no HTTP request, so nothing can be derived from a `Host` header. Rule: `WD_PUBLIC_URL` when set (install.sh writes the LAN URL `http://<first LAN IP>:<WD_PORT>` into it when no reverse proxy is configured, and `https://<domain>` with one — DEPLOY §2/§4) → else `kv.public_url_guess` (`http://<first non-loopback IPv4 of the host>:<WD_PORT>`, computed by `main.py` at startup, the Python equivalent of `hostname -I | awk '{print $1}'`) → else **no link**: the e-mail button and the webhook `url` field are omitted and the text says 「请在浏览器中打开 word-Dance」.
* **E-mail** (`send_email` job): requires `WD_SMTP_HOST`, `users.email_verified_at` and `email_enabled`. Subject `【word-Dance】今日词汇 10月14日 · 复习 12 · 新词 10`, first 10 words (word, phonetic, meaning_zh, first example en/zh), button → `<public_url>/today` (omitted when no public URL is known), text alternative, no images. STARTTLS/SSL/none; retries 1 min / 10 min / 60 min; `push_batches.email_status`. The 发送测试邮件 button enqueues `send_email {"user_id", "test": true}` (dedupe `email:test:<user_id>`, subject `【word-Dance】测试邮件`, body = the user's next push time in their timezone + the link; API.md 18).
* **Webhook** (`send_webhook` job): `POST webhook_url` with 10 s timeout, no redirects, SSRF guard (https, public IP, DNS-pinned). Formats: `generic` JSON `{type, date, title, body, counts, words:[{word, phonetic, meaning_zh}], url}` (`url: null` when no public URL is known); `wecom` `{"msgtype":"text","text":{"content":…}}`; `feishu` `{"msg_type":"text","content":{"text":…}}`; `serverchan` `{"title":…,"desp":…}`; `bark` `{"title":…,"body":…,"url":…}` (`url` key omitted when unknown). 发送测试 button in settings (1 per 10 min); its response carries the English diagnostic `error` for the admin ledger and a closed-set `reason` (`dns_failed` / `host_not_public` / `connect_failed` / `timeout` / `tls_failed` / `http_error` / `invalid_url`, API.md 17) that the UI turns into zh cause + action copy.

---

## 7. WD-SRS (services/srs.py — pure functions, table-tested, constants in one place)

```python
EASE_START, EASE_MIN, EASE_MAX = 2.5, 1.3, 3.0
LEARNING_STEP_MIN = 10          # one intra-session re-check, then graduate
GRADUATING_INTERVAL = 1         # days
HARD_FACTOR, HARD_EASE_DELTA = 1.2, -0.15
AGAIN_EASE_DELTA, LAPSE_FACTOR = -0.20, 0.5
EASE_RECOVERY_EVERY, EASE_RECOVERY_DELTA = 3, +0.05
MAX_INTERVAL = 180
FUZZ_PCT, FUZZ_MIN_INTERVAL = 0.05, 3
MASTERY_MIN_INTERVAL, MASTERY_MIN_CONSEC = 30, 3
```

State per `user_words` row: `ease`, `interval_days` (int; 0 before the first graduation), `step` (0 = review phase, 1 = waiting on the 10-minute step), `repetitions`, `lapses`, `consecutive_good`, `due_at` (UTC), `last_graded_at`.

```python
def grade(uw_id, s, g, now, tz, today):            # g ∈ again|hard|good ; master/skip handled by the state machine
    if s.step == 1 or s.state == 'new':             # learning or relearning step
        if g == 'again':  s.step, s.consecutive_good, s.due_at = 1, 0, now + 10min
        elif g == 'hard': s.step, s.due_at = 1, now + 10min                    # repeat the step
        elif s.step == 1:                                                      # good on the step → graduate
            s.interval_days = 1 if s.interval_days == 0 else max(1, rnd(s.interval_days * LAPSE_FACTOR))
            s.step, s.due_at = 0, day_start(today + s.interval_days, tz); s.consecutive_good += 1
        else:             s.step, s.due_at = 1, now + 10min                    # first exposure graded good → step
    else:                                           # review phase
        elapsed = (today - local_date(s.due_at, tz)).days ; delay = max(0, elapsed)   # overdue credit
        if g == 'again':
            s.lapses += 1; s.ease = q2(s.ease + AGAIN_EASE_DELTA); s.consecutive_good = 0
            s.step, s.due_at = 1, now + 10min                                  # relearning; interval_days kept for the ×0.5 rule
        elif g == 'hard':
            s.ease = q2(s.ease + HARD_EASE_DELTA); s.consecutive_good = 0
            s.interval_days = clamp(fuzz(uw_id, s.repetitions, max(s.interval_days + 1, rnd((s.interval_days + delay/4) * HARD_FACTOR))))
            s.due_at = day_start(today + s.interval_days, tz)
        else:
            s.consecutive_good += 1
            if s.consecutive_good % EASE_RECOVERY_EVERY == 0: s.ease = q2(s.ease + EASE_RECOVERY_DELTA)
            s.interval_days = clamp(fuzz(uw_id, s.repetitions, rnd((s.interval_days + delay/2) * s.ease)))
            s.due_at = day_start(today + s.interval_days, tz)
    s.repetitions += 1; s.last_graded_at = now; s.state = 'learning'
    return s, requeue_min(10 if s.step == 1 else None), mastery_suggested(s), humanize(s)

def fuzz(uw_id, reps, iv):  return iv if iv < FUZZ_MIN_INTERVAL else max(1, rnd(iv * (1 + ((zlib.crc32(f"{uw_id}:{reps}".encode()) % 101)/100 - 0.5) * 2 * FUZZ_PCT)))
def rnd(x):   return int(math.floor(x + 0.5))      # half-up (Python round() is banker's)
def q2(e):    return round(min(EASE_MAX, max(EASE_MIN, e)), 2)
def clamp(i): return int(min(MAX_INTERVAL, max(1, i)))
def mastery_suggested(s): return s.step == 0 and s.interval_days >= MASTERY_MIN_INTERVAL and s.consecutive_good >= MASTERY_MIN_CONSEC
```

Pinned trajectory (fuzz disabled, always 记住了): new → 10-min step → 1 d → 3 → 8 → 20 → 51 (mastery suggested here) → 133 → 180 (cap). Lapse at 20: ease 2.55 → 2.35, relearn in session, back at 10 d. `tests/fixtures/srs_trajectory.json` pins this table **and the `humanize` strings for every step** and is consumed by both `tests/unit/test_srs.py` and the frontend `utils/srsPreview.ts` test, so the card's 「下次：记住了 → 3 天后」 preview matches the server byte-for-byte.

```python
def humanize(s) -> str:                      # == GradeResponse.next_due_zh; the client mirror is utils/srsPreview.ts
    if s.step == 1:              return '10 分钟后'
    if s.interval_days == 1:     return '明天'
    if s.interval_days < 60:     return f'{s.interval_days} 天后'          # 2–59
    return f'约 {rnd(s.interval_days / 30)} 个月后'                         # ≥ 60: 60→2, 133→4, 180→6
# master → '已掌握' ; skip → '已跳过' ; screen unfamiliar without a same-day study row → '明天'  (set by grade_item, not by humanize)
```

Study day = the **calendar date in the user's timezone** (no 04:00 rollover). "Due today" ⇔ `state='learning' AND due_at < day_start(today+1)`. `requeue_min=10` tells the client to re-insert the card ≥ 10 cards later (or at the end); on reload the server still lists the item as remaining because `due_at < today_end`.

Grade → effect on push items: `again/hard/good` → SRS; `master` → `mastered`; `skip` → `skip_count+1`, moves to the end, not final; screen `known`/`unfamiliar` → state machine. **Final vs intermediate.** A grade is **final** iff it is `master`, a screen verdict (`known`/`unfamiliar`), or an `again`/`hard`/`good` that leaves `user_words.step == 0` (the card graduated from the step or was graded in the review phase). Only a final grade writes `push_items.result` (= the grade) and `graded_at`. An **intermediate** grade — one that leaves `step == 1` (`again` always; `hard` on a `new`/step card; `good` on a card's first exposure) — applies the SRS, writes its `review_logs` row (with `client_event_id`) and `daily_stats`, and returns `requeue_at` with `item.result = null`; the item stays ungraded (`result IS NULL`), so the same item is graded again later in the session with a fresh `client_event_id` and that second grade succeeds (200). `TodayCounts.done`, `goal_met`, `completed_at` and `item_already_graded` all key off `result IS NOT NULL`. A grade carries a client-generated `client_event_id` (UUID): a duplicate id returns the stored outcome (200, `duplicate:true`); a *different* event on an item whose `result IS NOT NULL` → 409 `item_already_graded` (skip excepted). A card left in the step at the end of the day is simply still due tomorrow (`due_at = now + 10 min < today_end`).

Streak: `daily_stats.graded ≥ 1` on review/new/extra cards (screening alone does not count); `streak_days` computed from consecutive `daily_stats` rows ending today or yesterday.

### 7.1 `daily_stats` deltas — `services/stats_core.on_action` (Phase 0, the single writer)

`on_action(conn, user_id, local_date, *, action, context, new_state, item_kind, elapsed_ms, undone=None, prev_state=None) -> dict[str, int]` (returns the applied deltas; `prev_state` = the action's `review_logs.prev_state`; `undone` = the reversed `review_logs` row plus `item_kind` resolved from `push_items`) upserts the `(user_id, local_date)` row (`INSERT … ON CONFLICT DO UPDATE`). Called by WP3 (`bank.apply_action`, `apply_verdict`, `add_custom_words`, `import_rows`, suggestions) and WP4 (`grade_item`) right after the `review_logs` row is written; `local_date` is the user's local date of the action. `screening` below = `context IN ('screen_page','onboarding')` or `item_kind = 'screen'`; `card` = `item_kind IN ('review','new','extra')`.

| `action` | deltas |
|---|---|
| `again` / `hard` / `good` (card; intermediate grades included) | `graded+1`, `<action>+1`, `study_ms += min(elapsed_ms or 0, 60000)` |
| `master` (card grade) | `graded+1`, `mastered+1`, `study_ms` as above |
| `master` (mark from a page) · `known` with `new_state='mastered'` (bank synonym) | `mastered+1` |
| `known` with `new_state='known'` | `known+1`; `screened+1` when screening |
| `unfamiliar` with `prev_state IS NULL` (row created) · `readd` · `add_custom` · `import` | `added+1`; `screened+1` when screening (`unfamiliar` only) |
| `unfamiliar` idempotent (`status exists`) · `skip` · `remove` · `reset` · `consolidate` · `note` · `attention` | nothing |
| `restore` | the exact reverse of the `undone` log row's deltas: `master`/`known` → `mastered-1` (+ `graded-1` when it was a card grade) or `known-1`, `screened-1` when it was screening; ∅→`unfamiliar` → `added-1` (+ `screened-1` when screening). Never below 0. |

`study_ms` feeds `DayStats.study_minutes` (= `study_ms / 60000`, rounded). Nothing else writes `daily_stats`; the heatmap, streak and history endpoints (WP4 `services/stats.py`) only read it.

---

## 8. Claude Code integration (summary; full spec in `CLAUDE_INTEGRATION.md`)

* Single runner `ai/runner.run_claude(kind, system_prompt, user_prompt, schema, max_budget_usd, timeout_s)`: argv list (no shell), `stdin=DEVNULL` (the probe shows a 3-s stall and a warning without it), `cwd = DATA_DIR/claude-cwd` (empty), env built from an allow-list (`HOME=/home/sqin`, `PATH` incl. `/home/sqin/.local/bin`, `LANG=C.UTF-8`, `TERM=dumb`, `NO_COLOR=1`, pass-through of `CLAUDE_CONFIG_DIR`, `ANTHROPIC_*`, proxy vars; **never** `CLAUDECODE`), `start_new_session=True` + `os.killpg` on timeout, `ai_calls` ledger row inserted *before* the spawn and updated after (cost recorded even on failure), raw stdout/stderr kept 14 days.
* Flag tiers: tier 0 = the verified FACTS §3 flags; tier 1 adds `--system-prompt`, `--restricted`, `--strict-mcp-config`, `--disable-slash-commands`. `wd claude-check` (install + admin button, ≤ $0.05) probes tier 1 then tier 0 and records `kv.claude.flag_tier`; the runner uses the recorded tier, folding the system prompt into the user prompt under tier 0. `--bare` is never used; `--fallback-model` is off by default (content is cached forever; quality verified only with sonnet).
* Jobs: `generate_content` (≤ 10 words/call — `WD_AI_BATCH_SIZE` is clamped to 1–12 because `content_v1.json` has `maxItems: 12`; priority 10/20/30/90), `lookup_word` (≤ 20 strings/call), `consolidate_bank` (1 user/call), `generate_svg` (default on, only for words a user studies, own daily sub-cap), `prewarm_plan` (admin, budgeted; fans out in passes of `5 × WD_AI_BATCH_SIZE` with `plan_id` on each content job). Per-word dedupe keys; the worker always takes the **head job across all Claude job types** (`ORDER BY priority, run_after, id`) so a user's priority-10 lookup is never queued behind hundreds of priority-20/90 content jobs; batching at claim time; bisection 10 → 5 → 3 → 2 → 1 on `--max-budget-usd` stops or a second group failure; `auth` failures pause AI 30 min with an admin banner. `generate_dance` (≤ 20 words/call, kind `dance`, sub-cap `WD_AI_DANCE_DAILY_BUDGET_USD`; stores the 单词之舞 spec in `word_dances`, served ahead of the rule spec — docs/WORD_DANCE_DESIGN.md §6, CLAUDE_INTEGRATION §6.8).
* Budget: measured $0.040 per 10-word call ($0.004/word; whole seed ≈ $37). Defaults: per call 0.25 (content) / 0.15 (lookup) / 0.40 (consolidate) / 0.10 (svg) / 0.25 (dance) / 0.05 (probe); daily `WD_AI_DAILY_BUDGET_USD=3.00`, monthly `40.00`, prewarm sub-cap `1.00/day`, dance sub-cap `WD_AI_DANCE_DAILY_BUDGET_USD=0.50/day` (≈ 140 words at `ESTIMATES['dance']` = 0.01 + 0.003/word; `0` queues no annotation), SVG sub-cap `WD_AI_SVG_DAILY_BUDGET_USD=0.50/day` (≈ 35–40 cards at the measured $0.0124 per call / $0.0140 per delivered card, counted inside the daily cap; `budget.ESTIMATES['svg']` stays at the conservative 0.03 reservation); reservation `est = 0.005 + 0.0045 × words` before each call; hourly call cap 60; kill switch; caps defer (`run_after` = next `WD_TZ` day 00:05), never fail.
* Prompts: `content_system.txt` is `content-v2` (audience 小学 → 职场; 小学 and 初中 example rules — short present-tense school/home sentences for 小学 words, school and everyday register for 初中; image keywords = the scene of example 1; `EXAMPLE_EN_MIN` 10; rule 8 keeps the 1–5 difficulty scale 1 = 小学/初中 basic … 5 beyond CET-6, stored unchanged — `vocab.py` sorts by `COALESCE(difficulty + 1, stage_min, 6)` since 小学 took index 1), `svg_system.txt` is `svg-v2` (§9). Cards generated under `content-v1` are not regenerated; the admin's 重新生成 does it per word.
* Content triggers only: a validated word enters a bank (capped per learner: `WD_AI_USER_DAILY_WORDS` = 80 words per account per UTC day, `0` = unlimited — beyond it the mark still adds the word but enqueues nothing and the word stays on dictionary data until the next day), a word is selected for a batch/prefetch, an explicit per-user request (60/day, sharing that per-account counter → 429 `rate_limited` once it is used up; both counted only when the job is really enqueued), `lookup_word` validating a custom word (the content job counts for the word's creator; the lookup call itself does not), or an admin action. Words with `is_valid_english IS NULL` are skipped by every enqueue site and dropped by the content handler. Browsing never spends money.

---

## 9. Image pipeline (`images/`)

```
fetch_image(word, exclude=(), provider=None, query=None):             # IoWorker, one job at a time (PLAN §5.1 C5–C8)
  if style.skip_image(word) and not (provider or query):              # function-word gate: dominant pos ∈ FUNCTION_POS {i,c,d,p,a,u,t}
      words.image_state = 'failed'; return skipped("function word: card only")   # no request, no SVG job — the template card IS the picture
  keywords, dropped = clean_keywords(content.image_keywords[:3] or [lemma], lemma, allow_lemma=style.allows_bare_lemma(word))
      # select.is_blocked(kw, allow=select.keyword_tokens(lemma), style): UNSAFE always; KID_UNSAFE in the kid style;
      # NON_PHOTO unless every hit is a token of the word itself ("world map" survives for `map`); an admin `query`
      # dropped by the same rules is logged `query_ignored` (API still 202); adverbs never fall back to the bare lemma
  style_ = style.style_for(word, cfg)                                 # 'kid' iff stage_code(stage_min) ∈ WD_IMAGE_KID_STAGES (default empty → always 'neutral')
  rounds = ((kid, chain − pexels), (neutral, chain)) if style_ == 'kid' and provider is None else ((style_, [provider] or chain),)
  for round_style, names in rounds:
    for kw in keywords:
      for provider in names:                                           # default chain: wikimedia, openverse[, pixabay, pexels if keyed]
          if job.priority >= 90 and provider in PREWARM_SKIP_PROVIDERS: continue   # prewarm never spends openverse / pixabay / pexels quota
          if not quota.allow(provider): continue                         # minute/day counters + cooldown, persisted
          cands = provider.search(kw, limit=10, style=round_style) ; quota.record(provider)
          for best in select.rank(cands, kw, exclude, allow=…, style=round_style)[:3]:   # several candidates, ranked (Selection below)
              img = fetch.download_and_store(best)                       # SSRF-safe, pinned DNS, Pillow re-encode
              if img: activate(img); return
  if word.active_image_id is not NULL:                                         # a 换一张 that found nothing new: the current image is kept
      words.image_state = 'ready'; return                                      # never a Claude SVG over a photo (§0.1 row 7) — nothing enqueued, nothing spent
  if WD_SVG_VIA_CLAUDE (default 1) and job.priority < 90                      # never for prewarm
     and word_is_studied(word):                                                # EXISTS user_words(state IN ('new','learning')) OR EXISTS push_items for an open batch
      enqueue generate_svg(word_id, priority = job.priority)                   # budgeted by WD_AI_SVG_DAILY_BUDGET_USD (CLAUDE_INTEGRATION §7); svg_system v2, text-free by code (§6.7);
                                                                               #   the handler re-checks and finishes `skipped` when an image landed before it ran
  words.image_state = 'failed'                                                 # → the template card is served now; the SVG replaces it when it lands

retry_failed_studied(now):                                           # scheduler.maintenance, 03:30 WD_TZ, after prefetch; by hand: wd images-retry [--limit N] [--dry-run]
  for word in words a user studies (bank new/learning or an open batch) with image_state = 'failed' for ≥ 6 h,
      fewer than 3 automatic retries in the last 30 days, oldest failure first, at most 50 per night:
      enqueue fetch_image(word_id, retry=True) at priority 30          # payload.retry marks the attempt; function words are never selected (card only by design)
```

* **Wikimedia Commons (primary)**: `action=query&generator=search&gsrsearch=<kw> filetype:bitmap&gsrnamespace=6&gsrlimit=10&prop=imageinfo&iiprop=url|extmetadata|size|mime|thumbmime&iiurlwidth=800&maxlag=5&format=json` — **no `formatversion=2`**: the provider parses the legacy shape the verified fixture `probe/wm.json` has (`query.pages` is an object keyed by pageid; each page has `title`, `pageid`, `imageinfo[0].{thumburl, thumbwidth, thumbheight, url, descriptionurl, extmetadata{…}}`; `batchcomplete`/`continue` ignored). Header `User-Agent: word-Dance/<ver> (self-hosted vocabulary trainer; +<WD_PUBLIC_URL>; <WD_CONTACT_EMAIL>)`. Download `thumburl` (≤ 800 px), never the original `url`. Hosts: the API answers from `commons.wikimedia.org`; **thumbnails are served from `thumb.wikimedia.org`** (verified in the fixture, e.g. `https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Red_Apple.jpg/960px-Red_Apple.jpg?utm_source=…`), originals from `upload.wikimedia.org`; both `thumburl` and `url` may carry a `?utm_source=…&utm_campaign=…&utm_content=…` query string, which the provider **strips** (any `utm_*` parameter) before the URL is used as `source_url`, excluded, or compared — the download itself goes through `fetch.safe_download` like any other https URL (no host allow-list for images, only the SSRF rules). Politeness ≤ 1 req/s (process-wide lock), soft day limit 2000, 429/503 → cooldown 15 min. Licence allow-list: `LicenseShortName` starting `CC0`, `Public domain`, `PD`, `CC BY`, `CC BY-SA` (no NC/ND). Style parameters (PLAN §5.1 C8): the neutral round searches `filetype:bitmap`, the kid round `filetype:drawing`; a candidate's mime is the thumbnail's (`thumbmime`), so a drawing's PNG thumbnail passes the jpeg/png/webp gate; `maxlag=5` makes a lagging replica answer with a `maxlag` error body, mapped to `ProviderError(status=503, retry_after_s = Retry-After or 30)` → cooldown instead of a parse failure.
* **Openverse (secondary)**: `GET https://api.openverse.org/v1/images/?q=<kw>&page_size=10&license_type=commercial&mature=false` (`page_size` = the request limit; the kid round adds `category=illustration`); anonymous limits measured 20/min burst, 200/day → enforce `WD_OPENVERSE_MINUTE_LIMIT=15`, `WD_OPENVERSE_DAILY_LIMIT=160` in `provider_usage` (window `minute`/`day`, UTC); 429 → cooldown `Retry-After` or 10 min. Download `url` (full image) only — **never** the `thumbnail` on `api.openverse.org` (it spends API quota). Optional registered app (`WD_OPENVERSE_CLIENT_ID/SECRET`) raises the limits (anonymous 200/day → 10,000/day) — register it before the 小学 rollout. Licence allow-list `cc0, pdm, by, by-sa`; the response's `category` is kept for scoring.
* **Pixabay / Pexels (optional, keyed)**: Pixabay adds `image_type=illustration` in the kid round; its terms forbid bulk or systematic downloading, so the chain fetches one word at a time on demand and prewarm (`priority ≥ 90`) skips `PREWARM_SKIP_PROVIDERS = (openverse, pixabay, pexels)`. Pexels has no illustration filter and is never part of the kid round.
* **Styles and rounds** (`images/style.py`): `style_for(word, cfg)` is `kid` iff `stage_code(word.stage_min)` (an index → `schemas.index_to_stage`, out of range → `None`) is in `WD_IMAGE_KID_STAGES` — stage codes, default **empty = off**; `zk` is never in the default; the live instance sets `xs` (2026-11-06, confirmed by the owner on the first 100 pre-drawn 小学 cards). A kid word gets two rounds — illustration-first over every provider but Pexels in the child picture-book style, then the ordinary photo round; everything else is one neutral round. `skip_image(word)` (dominant `pos` ∈ `FUNCTION_POS = {i, c, d, p, a, u, t}`: prepositions, conjunctions, determiners, pronouns, articles, interjections (`u` is `int.` in `pos.ts` / ECDICT), the infinitive marker) means card only — no provider request, no SVG job, `image_state='failed'` with `detail "function word: card only"`; an explicit admin `provider` / `query` overrides the gate. `allows_bare_lemma` is false for the same set plus adverbs (`r`), so an adverb without usable keywords is not searched by its bare lemma.
* **Retry of failed words** (`images/service.py`): `retry_failed_studied` runs in the 03:30 `WD_TZ` maintenance tick after prefetch and re-enqueues `fetch_image` (priority `RETRY_NIGHTLY_PRIORITY = 30`, `payload.retry = true`) for words a user studies whose `image_state` has been `failed` for ≥ `RETRY_MIN_AGE_H = 6`, at most `RETRY_MAX_AUTO_30D = 3` automatic attempts per 30 days and `RETRY_NIGHTLY_LIMIT = 50` per night (`TickResult.image_retries`); `wd images-retry [--limit N] [--dry-run]` runs the same selection by hand. Immediate retries when a failed word enters a bank or a batch are deferred to a later small commit (PLAN R-16).
* **Selection** (`select.rank(cands, keyword, exclude, *, allow, style)`): hard rejects — `mature`, non-empty `unstable__sensitivity`, Commons `Restrictions`, licence not allowed, mime not jpeg/png/webp, `width < 400 or height < 300` (not relaxed for the kid round), aspect outside 0.6–2.2, excluded ids/sha, and three word lists applied to title/tags/categories (and, through `select.is_blocked`, to the search keywords themselves): `UNSAFE_RE` `\b(nude|nudity|sex|porn|gore|blood|weapon|gun|corpse)\b` always; `KID_UNSAFE_RE` `\b(beer|wine|alcohol|cigarettes?|smoking|horror|zombies?|skulls?|knife|knives|bikini|lingerie)\b` in the kid style; `NON_PHOTO_RE` `\b(map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document)\b` unless every hit is a token of the query itself (`allow = select.keyword_tokens(lemma)`: the word *map* may search and keep "world map"; an admin `query` is exempt the same way). Score: +1 per keyword token in title/tags (max +3), +1 when the description / object name carries one (max +1), licence cc0/pd +3 / by +2 / by-sa +1, aspect 1.2–1.8 +1, `aspect < 1.0` −1, width ≥ 800 +1, Commons `Assessments` featured/quality/valued +2, provider `category` / `type` matching the round's target +1 (illustration/vector in the kid round, photograph/photo in the neutral one) and the opposite −1, `PEOPLE_RE` (portrait, selfie, faces …) −2 in the kid round and 0 otherwise, `TEXTY_RE` (sign, caption, label, typography …) −1, filename-like titles (`IMG_`, `DSC`, years) −1, already used sha −2. Minimum score 1 (`MIN_SCORE`).
* **Download** (`fetch.safe_download`): `https` only; resolve all A/AAAA; reject loopback, 10/8, 172.16/12, 192.168/16, 169.254/16, 100.64/10, 224/4, 0/8, `::1`, `fc00::/7`, `fe80::/10`; connect to the validated IP with `Host` header and `extensions={'sni_hostname': host}` (DNS pinning); ≤ 3 redirects each re-validated; `Content-Type image/*`; stream ≤ `WD_IMAGE_MAX_BYTES=8_000_000`; magic bytes JPEG/PNG/WebP; Pillow `MAX_IMAGE_PIXELS=40_000_000`, `verify()`, reopen, `exif_transpose`, RGB, long edge ≤ 800, JPEG q82 progressive, no EXIF/ICC; `sha256` of the re-encoded bytes → `images/<2hex>/<sha>.jpg` (0600); same sha reused across words. Insert `word_images(status='active')`, previous active → `superseded`, `words.active_image_id`, `image_state='ready'`.
* **Template card** (`card_svg.render(word, content)`): deterministic 800×500 SVG from DB data (pastel gradient from `hash(lemma)`, headword 72 px, phonetic, first `meaning_zh`/translation line, first example, small mark), XML-escaped, served at `GET /media/card/{word_id}.svg` with an in-memory LRU(2000) keyed by `(word_id, active_content_id, updated_at)` (a changed row — the K-12 seed import's `sources` rename moved `updated_at` on ≈ 4,357 rows — re-renders once; `images/card_svg.py`). No file, no network, no Claude — every word always has an image URL.
* **Claude SVG** (`WD_SVG_VIA_CLAUDE=1` by default; `0` turns it off): the FACTS §4 last resort before the text-only card, never a replacement for a photo. Enqueued only when every photo provider failed for a word that has no active image (a 换一张 that finds nothing new keeps the photo) and that a user actually studies (in a bank or an open batch) at priority < 90 — never for prewarm; the handler skips a job whose word gained an image before it ran (`result_json {"skipped":"photo_active"}`, no call), and only an explicit admin request (API.md 69 `provider:"claude_svg"`) draws over an active photo — and spent under `WD_AI_SVG_DAILY_BUDGET_USD=0.50` (≈ 35–40 cards/day at the measured $0.0124 per call, $0.0140 per delivered card; `system_events('budget_svg')` once per day when hit, jobs deferred to the next `WD_TZ` day while the template card is served). Schema `{svg, alt_zh}`, `--max-budget-usd 0.10`; system prompt `svg-v2` (CLAUDE_INTEGRATION §5.5: one central subject, flat colours, **no text of any kind**, the scene of example sentence 1 and the 联想 hook taken from the word's content, a Style line — `kid` picture-book or `neutral` flat educational, `images/style.py`); sanitised with `defusedxml` + element/attribute allow-list (drop `on*`, `href`, `xlink:href`, `style` with `url(`, `<script>`, `<image>`, `<foreignObject>`, `<use>`, entities; a bare `&` is repaired before parsing; `clean(allow_text=False)` drops every `<text>` / `<tspan>` subtree, so text-freeness is guaranteed by code rather than by the prompt; `with_label` inserts `<desc id="aigc-label">AI-generated illustration · word-Dance · <model> · <date></desc>` as the implicit AIGC mark; size ≤ 60 KB; enforce `viewBox`); the row records `prompt_version='svg-v2'`, `model` and `text_free=1` (migration 0012 — the 30 SVGs drawn before it keep `text_free=0`, `prompt_version NULL` and are not redrawn); stored as `.svg`, served with `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'`, `nosniff`; the UI always embeds via `<img>`. The admin overview reports `with_photo` / `with_claude_svg` / `card_only` and `svg_today_usd` vs the sub-cap, so the operator sees the photo hit rate and can raise the SVG budget (DEPLOY §11).
* **User controls**: `POST /api/words/{id}/image/refresh` (换一张, 20/day/user) enqueues `fetch_image` with `exclude = current provider_refs + shas` at priority 10 (the current image stays until a replacement lands and is kept when no provider has anything new; a request that meets a live `fetch_image` job for the word is merged into it — `exclude` union, latest `provider`/`query` — or, when that job is already running, queued behind it as `image:<id>:r<n>`, so no request is lost to the dedupe key); `POST /api/words/{id}/report {target:'image'}` (不合适) marks the active image `rejected` and triggers a refresh immediately (threshold 1 — a 1–5-user deployment cannot wait for three flags).
* **Attribution**: `attribution_text` = `"{title}" · {creator} · {license}` (Openverse's own `attribution` sentence when present; Commons `Artist` HTML stripped), `landing_url`, `license_url`; caption under every picture `图片：{title} · {creator} · {license} ↗`; generated images show `AI 生成示意图` / `系统生成卡片`. `ATTRIBUTION.md` (repository root, linked from the README) documents provider terms; the in-app 关于与数据来源 section of 设置 shows the fixed source lines of FRONTEND §5.8 (dictionary, word lists, image sources, AI notice) rather than rendering the Markdown file (P0_STATUS §3 item 27).

---

* **Pronunciation clips** (`audio.py`, `routers/audio.py`, API.md 76 `GET /media/audio?text&accent`): the fallback for a device without an English voice — Android's WebView has no `speechSynthesis`, the Android compatibility container of HarmonyOS NEXT has no TTS engine the shell's plugin can reach, many domestic ROMs have no English voice. The client (FRONTEND §6.4) speaks with the browser or the shell's TTS first and asks the server only when those cannot; `ServerFlags.audio` says whether the server has a provider at all. One clip per (provider, voice, accent, text) is synthesised once and cached under `audio/<2hex>/<sha256>` (0600, atomic rename; the cache is capped by `WD_AUDIO_CACHE_MB`, default 256 MB — beyond it the least recently played clips are removed, a served clip being touched): `WD_AUDIO_PROVIDER=say` runs macOS `/usr/bin/say -v <voice> -o clip.aiff` with the text on **stdin** (never an argument) and `/usr/bin/afconvert -f m4af -d aac -b 48000` (≈ 8 KB per word; `say`'s own m4a carries 30 KB of container overhead), both with an allow-listed environment, cwd `/`, a 30 s timeout and a process-group kill; the voice is `WD_AUDIO_SAY_VOICE` or the best installed one of a preference list per accent (Premium > Enhanced > compact) — and because `say` exits 0 for a name it cannot resolve and silently substitutes a fixed voice, every candidate is probed once per process against that fallback (`say_resolves`), an unresolvable override being a 503 `failed` rather than a cache of clips in the wrong voice; `youdao` fetches `https://dict.youdao.com/dictvoice?audio=<text>&type=2|1` (mp3, opt-in: every uncached text goes to Youdao, with a neutral `User-Agent`, no proxy from the environment, 10 s, ≤ 2 MB); `bailian` (slice server-audio-2 — the licensed voice for a public deployment, since the macOS `say` voices are personal and non-commercial) posts the text to 阿里云百炼's synchronous TTS API (`WD_BAILIAN_TTS_URL`, model `WD_BAILIAN_TTS_MODEL`, the accent's voice of `WD_BAILIAN_TTS_VOICES`; the bearer key is the first line of the 0600 `WD_BAILIAN_API_KEY_FILE`, read at call time) and fetches the pre-signed OSS URL of the answer over https with a **separate anonymous** client — the key never reaches OSS — (mp3 24 kHz, ≤ 4 MB, 15 s each; 429 / 5xx → `busy`, 4xx and malformed answers → `failed` with the provider's `code` and 80 chars of its `message`, never the key or the signed URL); the voice is part of the clip key and the model + voices of `audio_key`; consecutive requests are paced 0.4 s apart (≤ 150 of the documented 180 RPM); `cache` is read-only: it serves the `say` clips another host synthesised — the same content-addressed names, that host's voices from `WD_AUDIO_CACHE_VOICES` — and answers 503 `{reason:"missing"}` for a text without a clip — no budget spent, event `audio_clip_missing` at INFO; the client then speaks it with the device's own voice for that one text if it has one, the shell shows the clip as missing until the next sync (the loop `wd audio-texts` → `wd audio-prewarm --texts` → `rsync` is in ops.md §5; nothing on that host touches, prunes or caps the mirror); `auto` is `say` on a host with `/usr/bin/say`, else `off`. Text rule: 1–300 chars, Latin letters / digits / spaces / the punctuation of an English sentence (straight and typographic quotes, dashes, ellipsis, `$ % & @ /`), no leading hyphen (400 otherwise). Synthesis runs in two semaphore slots (8 s wait → 503 `busy`; at most six requests wait at all, so a burst cannot pin the threadpool); a user's cache misses are limited to 60 per minute (`auth_throttle` key `audio:user:<id>`, 429); hits cost nothing. `Cache-Control: private, max-age=604800`, `Accept-Ranges` (the client plays the URL in an `<audio>` element) — the route lives under `/media/` because the `/api/*` middleware stamps `no-store`. The failure log carries the text's length, the text itself only at DEBUG. At startup `audio.warm_up_async` resolves the voices on a daemon thread (the listing and the probes, 1–3 s) so the first tap never pays for them; `wd audio-prewarm` (DEPLOY §9) synthesises the clips of the study path ahead of time (headwords with content or in a bank and their example sentences, in learning order — anything else is made at the tap; two `say` processes at a time, so a live service keeps its own two slots) and `wd audio-voices` prints the installed voices of the preference lists (tier, whether `say` resolves them) and the voice each accent gets; the running total behind the cap is re-counted from disk every `SCAN_INTERVAL_S` (5 min) when a clip is added — the walk tolerates clips vanishing under it —, so another process adding or removing clips never skews the pruning. `ServerFlags.audio_key` (`voice_key`: provider + `WD_AUDIO_SAY_VOICE` + the resolved voice per accent — for `cache` the two voices of `WD_AUDIO_CACHE_VOICES` —, 8 hex chars, empty without a provider) rides on every clip URL as `v`, so a switched voice is a new URL for the browser's HTTP cache.

## 10. Security and privacy

| Area | Measures |
|---|---|
| Registration | `WD_REGISTRATION_MODE=invite` (default) / `open` / `closed`; invite codes stored as `sha256` in `invite_codes` with `max_uses`/`expires_at`, consumed atomically (`UPDATE … SET uses=uses+1 WHERE uses<max_uses AND (expires_at IS NULL OR expires_at>now)` must affect 1 row); created by `wd invite` or the admin page (shown once). **Bootstrap**: while `users` is empty, `POST /api/auth/register` accepts the registration in any mode without an invite code and makes that user `admin` (count check + insert inside one `BEGIN IMMEDIATE`, so two racing first registrations yield exactly one admin); `GET /api/health.needs_setup=true` lets the login page say 「尚无账号，首个注册的账号将成为管理员」. `wd create-admin --if-none` remains the unattended alternative (`WD_ADMIN_USERNAME/PASSWORD`). Mode `verified` (slice 1-A, docs/AUTH_SIGNUP_DESIGN.md §5.2): accounts are created by a phone / e-mail verification code (API.md 80 / 81) with a placeholder username (`u_` + 8 chars), an unusable bcrypt hash (`password_set_at NULL` → `User.has_password` false) and a first-time profile step (89: nickname, age band, optional username + password); `POST /api/auth/register` answers 403 `verification_required` after the bootstrap; an invite code is **optional** on the code path in `open` / `verified` (consumed when given) and required in `invite`. The bootstrap stays a username + password in every mode: a code sign-in on an empty site is 403 `setup_required`, a code login never yields an admin (403 `password_required` — admins sign in with their password only), and promoting an account without a password is 409 `admin_needs_password` (API 57, `wd promote`). |
| Identity | `identities` holds the phone bindings — one live `(provider, subject)` (`ux_identities_live` where `disputed_at IS NULL`) and one live phone per account; `login_codes` holds every verification code as `HMAC-SHA256(WD_SECRET_KEY, code:channel:target:purpose)` (6 digits, 10 minutes, 5 attempts; a new code voids the older unused ones of its triple; verified **outside** the transaction that consumes it, so a wrong guess stays counted; expired rows GC'd hourly, used rows kept a day) and the stale-phone challenge token (`purpose='challenge'`). Numbers are stored as E.164 and shown only masked (`138****8000`). A code-created account's unusable hash keeps a password login against it a plain 401 with constant bcrypt work. A phone identity unused for `WD_PHONE_STALE_DAYS` (`identities.last_login_at`, the binding time while null — never the sliding sessions) gets a second factor at the next code login: the account's password or an e-mail code to its verified address (API.md 82–83), or 「不是我的」 disputes the binding (84: `disputed_at`, a new account for the number, `system_events('phone_disputed')`, a notice mail to the old account; admins list and restore disputed bindings, 92 / 93). Re-authentication for change-password / delete / unbind takes a `reauth` code (85) when the account has no password; an unbind or an e-mail change may never leave an account with neither a password nor a verified channel (409 `last_login_method`). **Family (slice 1-B, docs/AUTH_SIGNUP_DESIGN.md §5.1)**: a guardian (`users.account_kind='guardian'`) must hold a live phone AND a password or a verified e-mail before it creates, switches into or issues codes for children (API.md 95, 99–101, 104: 409 `guardian_factors_required`; 6 / 87 refuse to remove a factor while children exist); a child is a `users` row with `guardian_user_id` (ON DELETE RESTRICT — a guardian is deleted only after its children were set free or deleted, API.md 8), `age_band`, the declaration stamps and `guardian_consent_at`, created by the guardian (95) or claimed from an existing account by a code to the guardian's phone (108 / 109); `family_codes` (0019) holds the 8-digit one-time child login codes (`child_login`, looked up by hash, 10 minutes, one live per child, single use) and the 6-digit claim codes (`claim_guardian`, 5 attempts) as `HMAC-SHA256(WD_SECRET_KEY, code:kind:target)`, GC'd like `login_codes`; the 6-digit 家长 PIN is a bcrypt hash in `users.guardian_pin_hash` (never all one digit or a straight run). **Third-party identities (slice 2-A, API.md §3.3)**: a WeChat mini-program openid, a QQ openid or an Apple `sub` is an `identities` row too (`provider ∈ {wechat_mini, qq, apple}`, `subject` = the pseudonymous id — shown to nobody, never logged, never in a `system_events` detail or an `auth_throttle` key: the per-openid scan window hashes it) under the same two partial unique indexes (one live account per openid, one identity per provider per account); the WeChat bridge keeps its tickets in `wechat_tickets` (0020) as hashes only (`ticket_hash` = sha256 of the 小程序码 scene, `poll_hash` = sha256 of the browser's `wd_wxt` cookie, `pair_hash` = HMAC of the 6-digit pairing code, kept for the row's life so a repeated confirmation answers 409 `wrong_state`; 180 s, GC'd a day after expiry / consumption) and proves a scan to the confirmation with `mp_token` = HMAC(WD_SECRET_KEY, `mp:<ticket id>:<openid>:<exp>`), 5 minutes; the QQ / Apple results cross origins through a one-time grant in `kv` (60 s, single use). WeChat / QQ / Apple are never a re-authentication factor: a third-party-only account sets a password at `/welcome` step 0 (API.md 89), unbinding (117) keeps ≥ 2 ways in (`third_party.ways_in`), and an admin never signs in through them (`password_required`). |
| Passwords | bcrypt cost 12, 8–64 chars, not equal to the username, not in a shipped 1k common-password list; constant-time verify with a dummy hash for unknown users; password change deletes other sessions; forgot / reset (API.md 90 / 91) sends a code to the bound phone, else the verified e-mail — always 202 — and a reset revokes every session (`system_events('password_reset')`). |
| Sessions | `secrets.token_urlsafe(32)` in cookie `wd_session` (`HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000`; `Secure` when `WD_PUBLIC_URL` is https or `WD_COOKIE_SECURE=1`); DB stores `sha256(token)`; sliding expiry once per day, and the slide never **shortens** a session (`expires_at = max(current, now + WD_SESSION_DAYS)`, the re-sent cookie carrying the seconds left — slice 1-B); max 20 sessions/user; GC hourly. Slice 1-B: `sessions.actor_user_id` names the guardian who switched a shared device into a child's account (API.md 104 — a fresh child token, the guardian's session on that device deleted, other devices untouched; `GET /api/auth/me` returns it as `session.guardian` so the SPA offers 「切回家长」, 105); `sessions.guardian_gate_at` records when the guardian passed the 家长门 in that session (102 / 105; good for 10 minutes, once per sitting — never per request); a child's own device signed in by a login code (107) gets a 90-day session (`Max-Age=7776000`), revocable by the guardian (98) and by a password change (96). |
| CSRF | SameSite=Lax + mandatory header `X-WD-Request: 1` on every non-GET `/api/*` + `Origin`, when present, must equal the request's own Host-derived origin or the origin of `WD_PUBLIC_URL` (`http://localhost:5173` in dev) — API.md §1; no CORS middleware. |
| Throttling | `auth_throttle` table (persistent): login 20/10 min per IP counting **failures only** (`login:ip:<ip>`, checked before the password, counted on the failure path — a shared Wi-Fi of real users is never throttled); 10 failures per identifier **and client IP** → lock 15 min doubling per further 5 failures (max 24 h), reset on success (`login:user:<identifier>:<ip>` with the identifier canonicalised — E.164 phone / NFKC lower-case e-mail / lower-case username, so respelling a number opens no fresh bucket: a stranger's guesses cannot lock the owner out; `wd unlock <identifier>` clears every IP's row); register 5/h per IP (the username + password form only — the code sign-in never counts it); verification-code sends per target `code_send:target:<E.164|email>` 1/min, 5/h, 10/day (shared by every purpose and endpoint except 9, which keeps only `email_code:user:<id>` 3/h), per IP `WD_CODE_IP_HOURLY`/h, per 7-digit mainland prefix 5/h, code checks 20/h per target and 60/h per IP (failed checks only, read before the code is looked at), captcha challenges 60/h per IP, and the site-wide SMS caps `WD_SMS_HOURLY_CAP` / `WD_SMS_DAILY_CAP` (kv counters, 503 `sms_budget_exhausted`; sends that would create an account stop at 70 % of the day cap; `sms_budget_50/80/100` events + the admins' webhooks at 80 % and 100 %); the self-hosted image captcha (`WD_CAPTCHA=on`) in front of the public code sends when no session exists; learner-triggered content generation `WD_AI_USER_DAILY_WORDS` words per user per UTC day (`ai:user:<id>`, 80; the 不熟悉 marks and endpoint 30 share it); custom adds 200/day; content requests 60/day; image refresh 20/day; reports 20/day; pronunciation cache misses 60/min per user (`GET /media/audio`, the one throttled GET besides the captcha); mutations 300/min per user (every authenticated non-GET request, counted in `deps.current_user`); password / `reauth`-code re-checks for change-password / delete-account / unbind-phone 10 per 15 min per user, cleared by a correct factor (a stolen session cookie must not allow online guessing — the login lockout covers `/api/auth/login` only). Client IP from `X-Forwarded-For` only when `WD_TRUST_PROXY=1`. |
| Authorisation | two roles; ownership enforced in SQL (`user_id = :me`); private words visible only through the §5.2 visibility rule (creator, any holder of a `user_words` row, admins); a foreign id yields 404 (no existence leak); the last active admin cannot be disabled/demoted/deleted (409 `last_admin`). Slice 1-B (API.md §1 / §3.2): the `G` column — a guardian acting in its **own** session (`actor_user_id IS NULL`) — guards `/api/guardian/*` and the switch (104), `G+gate` additionally needs the session's 家长门 stamp younger than 10 minutes (403 `guardian_gate_required`); a child account (`guardian_user_id` set) gets 403 `guardian_required` on the account / identity endpoints 6–10, 85–89, 104, 108–111 whatever its session and never satisfies `G` — learning, settings, the bank, export / import, words and screening stay open to it; another guardian's child is a 404 like any foreign id; the 家长门 factors (PIN / password / `reauth` code) share the lockout key `gate:user:<guardian id>` with the login cadence (keyed per guardian, not per IP — the guesser sits on the guardian's own device). |
| Headers | `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, HSTS when https, `Cache-Control: no-store` on all `/api` JSON. Body limit 1 MB. Pronunciation clips play as a same-origin media URL (`default-src 'self'` covers it; no `media-src` / `blob:` is opened). |
| Prompt injection | user strings reach Claude only as JSON string values inside a labelled data block after the charset/length rules of §5.1 (≤ 48 chars, letters/space/`'`/`-`/`.`), plus — in the per-user consolidation prompt only — a ≤ 120-char sanitised note; `--tools ""`, empty cwd, no session persistence (and `--restricted --strict-mcp-config` when probed OK); schema-constrained output; server post-validation (word must match request, examples must contain the headword/form, length caps, CJK/ASCII checks, no URLs/HTML); any Claude-proposed headword that would mutate shared rows passes the deterministic validator + relatedness rule; typo corrections never auto-applied; Claude cannot address rows outside the batch it was given; output rendered as text by React. |
| SSRF | §9 guard for image downloads and user webhooks (https only, public IPs on every hop, DNS pinning, ≤ 3 redirects, byte/pixel caps, magic bytes, re-encode; webhooks additionally deny `localhost`, `.local`, `.internal`, raw IPs, 10 s timeout, no redirects). Provider API hosts are constants. The opt-in Youdao pronunciation provider (§9) is a fixed https host too: it receives each uncached text with a neutral `User-Agent` (no operator e-mail or URL), no redirects, no proxy from the environment, 10 s timeout, 2 MB cap. |
| SVG | sanitiser allow-list, `<img>` embedding only, sandboxing CSP on `/media`. Template card escapes all text. |
| Subprocess | Claude CLI: argv list, fixed binary path, allow-listed env, empty cwd, `stdin=DEVNULL`, timeout + process-group kill, stdout/stderr caps (10 MB). `say` / `afconvert` (§9 pronunciation clips): argv list, fixed paths, allow-listed env (`PATH`, `LANG`, `HOME`, `TMPDIR`), cwd `/`, the text on **stdin** (never argv), 30 s timeout + process-group kill, stdout discarded, a 300-char stderr excerpt in the error. |
| Files | `UMask=0077`; data dir 0700; DB/WAL/`.env`/images/backups 0600; secrets only in `.env`; `GET /api/admin/config` masks them; logs never contain passwords, tokens or prompts (word lists only at DEBUG; a failed pronunciation is logged with the text's length, the text at DEBUG); phone numbers, e-mail addresses and verification codes never appear in a log line or a `system_events` detail (`user_id`s and masks only; the Aliyun key is read from a 0600 file at call time and scrubbed from error messages). Pronunciation clips: 0600 files in 0700 `audio/<2hex>/`, the cache capped by `WD_AUDIO_CACHE_MB`. |
| Privacy | personal data = username, optional e-mail, display name, learning history, notes, and since slice 1-A an optional phone number (E.164 in `identities.subject`, returned only masked as `138****8000`, deleted with the account) and a self-declared age band (`users.age_band` with `age_declared_at` / `age_declared_ip`, never verified; under-14 accounts exist only through a guardian — slice 1-B — and hold no phone or e-mail: a legacy account claimed as such loses its own with the claim, API.md 109); the sign-up consent (用户协议 / 隐私政策, `frontend/public/legal/`) is required before a login code is sent; user-added words private until validated; export (`GET /api/account/export`), re-import (`POST /api/bank/import`) and self-service deletion (`DELETE /api/account` with password, cascades; shared provisional words survive while another user holds them); no third-party analytics; images self-hosted (providers never see end-user IPs); Claude never receives usernames or e-mails, and a user's private 备注 never reaches the shared content prompt (§5.3) — shared `word_contents` can therefore never echo another user's note. **Children's data (slice 1-B)**: an under-14 account exists only under a guardian — created by the guardian (API.md 95) with `age_declared_at` / `age_declared_ip` / `guardian_consent_at` stamped at creation (the guardian's consent is the creation itself), or attached to the guardian by a claim the guardian confirms with a code to their own phone (108 / 109, `guardian_consent_at` stamped, `system_events('account_claimed')`); a child carries no e-mail and no phone of its own until 独立; the guardian sees progress figures only (`ChildAccount`: bank size, streak, last login, signed-in devices — never the child's notes or words) and can rename, re-password, sign out, delete (97, the full cascade) or set free the child (101 独立 at 14+: own phone + password, irreversible); deleting a guardian frees the children that hold their own phone and deletes the rest with it (8 `delete_children`, `system_events('guardian_deleted')`); child login codes and claim codes are stored hashed and never logged; the legacy 「补充信息」 prompt (110 / 111) records a self-declaration only, never a verification. **Third-party sign-in (slice 2-A)**: the only personal datum a WeChat / QQ / Apple sign-in adds is the provider's pseudonymous id in `identities.subject` (openid / `sub`), returned to nobody — `User.providers` lists provider names only — and deleted with the account or by 117; nothing else the provider offers is requested or kept (no nickname, no avatar, no `unionid` / `session_key`, Apple's name / e-mail form field is ignored). The mini program's confirmation page sees the initiating browser only as a masked IP (`203.0.113.*`) and a browser / OS summary (`Chrome · macOS`), never the account; the pairing code and ticket travel in clear only between the browser and the person holding the phone. The openid is never written to a log line (ids only). **Cloud pronunciation (`WD_AUDIO_PROVIDER=bailian`)**: the texts sent to 阿里云百炼 are the English headwords, phrases and example sentences of the shared library a learner taps — never a username, a note or anything personal (the text rule of endpoint 76 admits only Latin letters, digits and English punctuation, and the request carries no user id); the API key lives in a 0600 file read at call time and reaches only the 百炼 endpoint (the clip download from OSS is anonymous), and the synthesis log carries the text's length, the text itself at DEBUG. |

---

## 11. Deployment overview (details in `DEPLOY.md`)

* `deploy/install.sh` (idempotent, run as `sqin`, `sudo -n` only for systemd/proxy files): preflight → venv + pip → `npm ci && npm run build -- --outDir $WD_DATA_DIR/frontend-releases/<sha>.new` (a versioned snapshot in the data dir, never `<repo>/frontend/dist`, so builds in the checkout cannot touch the live UI) → data dir (`WD_DATA_DIR`, else the directory in the installed unit's `EnvironmentFile=`, else the default — a `WD_DATA_DIR` that differs from the unit's is refused unless `--move-data`, DEPLOY §2) + `.env` (secrets generated; every value double-quoted; an empty `WD_FRONTEND_DIST` filled with `$WD_DATA_DIR/frontend`; `bash -n` check before sourcing) → **stop the unit if it is running** (unless `--no-restart` or without passwordless sudo (DEPLOY §2) — the script then warns that the old version keeps serving instead of stopping it, so only additive migrations may be pending; otherwise a non-additive migration never runs under a live old process) → publish the snapshot (`<sha>.new` → `<sha>`, the `frontend` symlink replaced with one atomic rename, the two newest snapshots kept — DEPLOY §1/§10) → `wd migrate && wd import-seed` (seed from `WD_SEED_PATH`) → `wd claude-check` (records the flag tier, ≤ $0.05) → `wd create-admin --if-none` → install `word-dance.service` + `word-dance-backup.timer` → start → health check → prints `http://<LAN-ip>:8000` (default bind `WD_HOST=0.0.0.0`; that URL is also written to `WD_PUBLIC_URL` for delivery links) or the https URL when `--with-caddy DOMAIN`/`--with-nginx DOMAIN` set `WD_HOST=127.0.0.1`, `WD_PUBLIC_URL`, `WD_TRUST_PROXY=1`.
* systemd **system** unit `User=sqin` (no `Group=`: the user's primary group), `EnvironmentFile=/home/sqin/word-dance-data/.env` (the line install.sh reads the data directory back from), `Environment=HOME=/home/sqin PATH=/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin`, `TimeoutStopSec=300` (≥ the longest AI timeout 240 s + grace), `KillMode=mixed`, `UMask=0077`, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`; **no `ProtectHome`** (OAuth credentials in `/home/sqin/.claude*`; Linger is off so a user unit is not an option).
* Backups: `word-dance-backup.timer` (`OnCalendar=*-*-* 03:30:00 Asia/Shanghai`, `Persistent=true`) runs `wd backup --keep-daily 14 --keep-weekly 8` independently of the app (`VACUUM INTO` → `integrity_check` on the copy → gzip → retention 14 daily / 8 weekly); `wd migrate` (implemented in `cli.py`, calling `db.run_migrations()` with the late-imported `wd.backup.snapshot_before_migrate` hook) takes `pre-migrate-<from>-to-<to>.db.gz` first; `wd restore <file>` refuses while the service runs.
* One operational timezone `WD_TZ=Asia/Shanghai` for budget days, maintenance hour, backup time and admin views; each user's own IANA timezone drives pushes.
* Logs: JSON lines to journald; optional `WD_LOG_FILE`; `claude-logs/` raw CLI output 14 days.

---

## 12. Testing strategy (details per WP in `TASKS.md`)

* **Unit (pytest, no network, no real claude)**: normalisation table (≥ 60 inputs incl. `a.m.`, `e.g.`, `ice cream`, `CPU`, `放弃`, 5-token sentence), resolution chain with a 60-word mini seed (`went→go`, `children→child`, `data→data`, `bases→ambiguous`), state machine (every row of §4 incl. `restore` within/after the 15-min window for `master`/`known`/∅→`unfamiliar`, the action→log mapping and the context→origin mapping; `stats_core.on_action` deltas of §7.1 incl. the restore reversals), SRS trajectory fixture (+ `humanize` strings) + property tests (interval never decreases on good, never > 180, ease bounds), final-vs-intermediate grades (second grade on a requeued item → 200; `done`/`goal_met` only on `result IS NOT NULL`), batch builder (caps, ordering, `interleave`/`spread_similar` against `batch_order.json`, cold start, idempotency, concurrency, stale-item hiding, screen→new second row, `/more` on a `building` batch, `finalize_building` → `ready` at once when AI is paused), scheduler with a frozen clock (prebuild, `build_from` clamp with push 01:00, publish once, catch-up, stale e-mail skip, DST zone, one consolidation enqueue per user-day, downtime `{from,to}`, `maintenance.prefetch` = read-only preview + ≤ 50 priority-30 jobs per user, skipped at ≥ 50 % spend), db (`autocommit=True` + explicit `BEGIN IMMEDIATE`: a migration file with a syntax error leaves no `schema_migrations` row and no partial table), registry (after `load_handlers()` every `jobs.type` CHECK value has a handler), queue (atomic claim with 4 threads, dedupe upsert, backoff, stale sweep, head-of-queue across job types), budget (caps, reservation, SVG and prewarm sub-caps, deferral timestamps in `WD_TZ`), runner argv/env/parsing with `fake_claude.py` modes (`ok | invalid_json | schema_mismatch | budget | timeout | auth | partial | invalid_word | overloaded`), post-validation, consolidation apply rules (auto vs suggestion), image selection/quota/SSRF (`127.0.0.1`, `10.0.0.1`, `169.254.169.254`, `::1`, IP literal, redirect to private host), Pillow normalisation, SVG sanitiser, template card determinism, e-mail/webhook rendering + idempotency.
* **Integration (FastAPI TestClient, temp data dir, mini seed, `httpx.MockTransport` providers, fake claude, worker driven synchronously)**: auth flows (incl. bootstrap registration on an empty `users` table), CSRF, onboarding gate, vocab filters/search, bank add statuses, import of an export file, today flow (build → grade sequence incl. 10-min step → requeue → complete; idempotent `client_event_id`; in-batch screen verdict → second `new` row; master → `restore` puts the snapshot back), suggestions accept/reject/undo, admin guards, visibility (two holders of one provisional word both see detail/content/card, a third user gets 404), account deletion cascade (shared provisional word kept).
* **Frontend**: `tsc --noEmit` strict, `vite build`, `vitest` for `normalizeInput`, `srsPreview` (consumes `srs_trajectory.json`), `highlight`, `queue` reducer, `api/client` error mapping.
* **Smoke (`scripts/smoke.py`)**: boots a throwaway instance with fake claude and mocked providers and walks health (`needs_setup`) → first registration without invite (admin) → invite → second user → onboarding → browse → mark → bulk add (`abandoned, children\nubiquitous, bases`) → worker-once → content/image ready → build today → grade all kinds incl. an in-batch 推荐词 不熟悉 → master → restore → master → re-add → export → import → history/stats → admin overview → logout.
* **Manual acceptance on this box**: `wd claude-check` (≤ $0.05), one real 10-word `generate_content` (≈ $0.04), one real Wikimedia + one Openverse fetch, webhook test, phone layout at 360 px, dark mode, keyboard-only session, TTS in Chrome/Edge/Safari.

---

## 13. Decision log — how every judge `must_fix` is resolved

| # | Must-fix | Resolution (section) |
|---|---|---|
| 1 | Reuse the verified seed and builder; measured counts | Historical: `scripts/build_seed.py` was copied verbatim and acceptance pinned 9,162 / 2,099 / 3,829 / 4,722 / 7,671 / 3,694. Since the K-12 release (`docs/releases/2026-11-k12-stages.md`) the builder is the `backend/wd/seedbuild/` package fed by the official head-word lists in `data/lists/`, and every acceptance number is read from `data/seed/stats.json` (§3.2, TASKS WP1) |
| 2 | Image provider order and limits per FACTS §4b | Wikimedia primary ≤ 1 req/s + UA; Openverse 15/min, 160/day persisted; never the Openverse thumbnail; ranked candidates; 换一张; Claude SVG last resort on by default (budgeted, studied words only); template card when everything else fails; photo/svg/card shares in the admin overview; local re-encode (§9) |
| 3 | Onboarding with stage choice, push time, timezone, short 筛词 | §6.2; no hard-coded stage; recommendation order from `current_stage`; gate covers 今日/学习/记录 only |
| 4 | User-added words private until validated | `is_public=0` until `is_english && safe_for_sharing`; one visibility rule (creator ∪ holders ∪ admins) applied by every word route (§5.2, API.md §1) |
| 5 | Bank-wide 整合与更新 with confirmable suggestions; auto-apply only existence-checked lemma fixes | `consolidate_bank` nightly over the whole bank; auto-apply limited to fill_data/difficulty/verifiable lemmatize; spelling fixes & merges are suggestions (§5.4, CLAUDE_INTEGRATION.md 6) |
| 6 | Claude invocation anchored to the verified command; probe extra flags; ledger before spawn; killpg; no `--bare`; no Docker | §8, CLAUDE_INTEGRATION.md 1–3 |
| 7 | Lemma resolution respects empty forms, headword guard, ambiguity | `word_forms` PK `(form, word_id)`, guards at import, `via='ambiguous'` with candidates (§3.1, §5.2) |
| 8 | Bounded spend with measured costs; bisection; reservation; kill switch | §8; CLAUDE_INTEGRATION.md 7 |
| 9 | Daily push channels incl. 企业微信/飞书/Server酱/Bark; one batch per day; catch-up today only | §6.4–6.5 |
| 10 | Every pushed word studyable while content pending; builder never waits | §6.3 |
| 11 | Vocabulary browsing: 全部 + stages, 新增 filter, prefix + form search, LIKE Chinese search, A–Z, state filter, pagination, no paid side effects | API.md `GET /api/vocab`; `stage_min` filter; browsing enqueues nothing |
| 12 | `GET /today` side-effect free; bind default consistent with printed URL; system unit `User=sqin`, no ProtectHome | §6.4, §11 |
| 13 | Phase 0 pins current versions (react-router ^7, uvicorn 0.54, Pillow 12, bcrypt 5, plugin-react 6, TS 5.9) | §1 |
| 14 | `--json-schema` uses only probe-validated keywords; server post-validates | CLAUDE_INTEGRATION.md 2 & 4 — the install probe schema now exercises `enum` too, so every keyword the production schemas use is validated by `wd claude-check` before the tier is recorded |
| 15 | Grading idempotency | `client_event_id` partial unique index (§7) |
| 16 | Normalisation accepts `.` in short tokens and ≤ 4-word phrases | §5.1 |
| 17 | Fallback model default off | §8 |
| 18 | Calendar local date for the study day (no rollover ambiguity) | §7 |
| 19 | Single-process invariant; batch creation under `BEGIN IMMEDIATE` with `UNIQUE` as the sole guarantee | §0.2, §6.3 |
| 20 | Data dir and `.env` outside the checkout, 0700/0600; install re-runnable | §2, §11 |
| 21 | Independent backup timer, pre-migrate snapshot, `integrity_check` | §11 |
| 22 | Persistent login throttling | `auth_throttle` (§10) |
| 23 | SSRF guard with DNS pinning etc. | §9, §10 |
| 24 | One operational timezone `WD_TZ` | §11 |
| 25 | Hashed invite codes with uses/expiry | §10 |
| 26 | mahavivo lists used as membership facts only; ECDICT MIT text shipped | no bare-word list files are shipped; `data/licenses/ECDICT-LICENSE`; `ATTRIBUTION.md` |
| 27 | `TimeoutStopSec` ≥ longest AI timeout | 300 s (§11) |
| 28 | Per-call budget overrun → bisection; `Cache-Control: no-store`; `--limit-concurrency` | §8, §10, §1.1 |

---

## 14. Example day (walk-through)

08:00 Asia/Shanghai, user `bob` (目标阶段 四级+六级, 主攻 四级, 10 new, 15 推荐词, 60 reviews, images on, 企业微信 webhook on). 05:00 tick (`next_push_at − 3 h`): `build_batch` → 12 reviews due, 4 `new` from the bank, 15 推荐词 (unseen CET-4 words in learning order, §6.3 step 4). 3 of the 31 words lack content → `generate_content` ×3 (priority 20) → one `claude -p` call (≈ $0.02) → content stored → `fetch_image` ×3 → IoWorker fetches 3 photos from Wikimedia Commons (≈ 10 s). 05:02 `finalize_building` → `ready`. 08:00 tick: `publish_batch` → `send_webhook` job → 企业微信 text「word-Dance 今日词汇 10月14日 · 复习 12 · 新词 4 · 推荐 15 …」. 08:20 bob opens `/today`, studies 16 cards in 7 minutes (2 不熟悉 → re-queued after 10 min; 1 已掌握 with the 8-s 撤销 toast — he taps it, `restore` puts the card's 51-day interval back untouched), screens 15 推荐词 (4 不熟悉 → 2 get a second `kind='new'` row appended to today's queue, 2 wait for tomorrow), adds "ubiquitous, GDP" from a report with 今天就学 → neither string is in the seed, so without `WD_ECDICT_DB_PATH` both are provisional (`pending_ai`, badge 待校验; with the optional full ECDICT, `ubiquitous` would resolve instantly and be appended as 加练 right away) → one `lookup_word` call 20 s later validates both (`GDP` → abbreviation), `generate_content` + `fetch_image` follow within a minute (no photo for the abstract `ubiquitous` → Claude SVG concept card), and both appear as 新词 in tomorrow's batch. 02:30 next night: `consolidate_bank` finds that bob's bank has both `analysis` and `analyses`, proposes 「“analyses” 是 “analysis” 的复数，合并？」 in 整理建议.

*End of DESIGN.md.*
