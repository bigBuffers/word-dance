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
| Frontend | React 19.3 + TypeScript 5.9 + Vite 8.3 + `react-router` **7.x** (pinned `^7`, never 8), plain CSS with custom properties, Simplified-Chinese UI. Built to `frontend/dist`, served by FastAPI. |
| AI | `claude -p … --output-format json --json-schema … --tools "" --no-session-persistence --model sonnet --max-budget-usd …` (the FACTS §3 verified invocation) + an install-probed hardening tier (`--system-prompt --restricted --strict-mcp-config --disable-slash-commands`) that is auto-disabled on a usage error. Per-word jobs batched 10 per call; content cached globally per word; per-call, daily and monthly caps with deferral; measured cost $0.004/word. |
| Images | **Wikimedia Commons primary** (≤1 req/s, descriptive UA) → Openverse secondary (15/min, 160/day persisted counters; anonymous limits are 20/min, 200/day) → optional keyed Pixabay/Pexels → **Claude-drawn sanitised SVG concept card (default ON, `WD_SVG_VIA_CLAUDE=1`, only for words a user actually studies, never for prewarm, bounded by `WD_AI_SVG_DAILY_BUDGET_USD=0.50` ≈ 18 cards/day at the measured $0.028)** → deterministic template SVG card rendered on the fly (text-only, never fails). Several candidates fetched and ranked; users can request 换一张. All photos downloaded, re-encoded, served locally. The admin overview splits words into photo / claude_svg / card-only so the photo hit rate is visible. |
| Scheduling | 60-s tick thread. One `push_batches` row per (user, local date) enforced by `UNIQUE`. Built up to `WD_PREBUILD_HOURS=3` before the user's push time but never before 00:00 of the batch's own local day, published at push time (in-app always; e-mail / 企业微信 / 飞书 / Server酱 / Bark webhooks best-effort). Items whose state changed between build and study are hidden (§6.3). Downtime catch-up builds only the current local day. |
| Learning | Bank states `new → learning → mastered` (+ `known`, `removed`); WD-SRS: one 10-minute learning step, SM-2 style expanding intervals (1 → 3 → 8 → 20 → 51 → 133 → 180 d), relearning after a lapse, overdue credit, deterministic ±5 % fuzz, mastery *suggested* at interval ≥ 30 d and 3 consecutive 记住了 — the user always confirms 已掌握. |
| Data | Reuses the verified seed: `scratchpad/seed/vocab.jsonl` (9,162 words) gzipped into `data/seed/vocab.jsonl.gz` and the verified `scratchpad/seedbuild/build_seed.py` copied to `scripts/build_seed.py`. |
| Onboarding | First login: choose 目标阶段 (multi-select of 初中/高中/四级/六级), 主攻阶段, 推送时间, 时区, then a 20–30-word 筛词. Recommendation order derives from this; nothing is hard-coded to a single stage. |
| Deploy | `deploy/install.sh` (idempotent) → venv, `npm ci && npm run build`, data dir, `.env`, migrate + seed, `claude` probe, systemd unit + backup timer. Optional Caddy/nginx for HTTPS. |

### 0.1 Requirement → mechanism map (all 7 are MUST-HAVE, none narrowed)

| # | Requirement (brief) | Mechanism |
|---|---|---|
| 1 | Ubuntu server, web front-end, accounts with login | systemd unit on this box; FastAPI serves the React SPA; server-side cookie sessions; bcrypt passwords; invite/open/closed registration (§10, DEPLOY.md) |
| 2 | System pushes/offers the COMPLETE 初中 / 高中 / CET-4 / CET-6 vocabulary | `words` table seeded with 9,162 words and per-stage flags; 词库 browser with 全部 + four stage tabs, 仅本阶段新增 filter, A–Z, search; daily 推荐词 (screening cards) appended to every push; 筛词 page for rapid triage (§3, §6, FRONTEND.md) |
| 3 | Mark a single word 不熟悉 → personal 生词库 | `POST /api/words/{id}/mark {action:"unfamiliar"}` from any list/card → `user_words.state='new'` (§4) |
| 4 | Backend uses **Claude Code** to consolidate/update the bank and pushes a daily batch per user settings | `claude -p` jobs: `lookup_word` (validate/normalise/fill user-added words), `consolidate_bank` (nightly bank-wide 整理: lemmatise, merge duplicates, spot misspellings, fill fields, tag difficulty → 整理建议 inbox), `generate_content` (examples, collocations, mnemonic, image keywords); scheduler builds and publishes one batch per user per day according to `user_settings` (§5, §6, CLAUDE_INTEGRATION.md) |
| 5 | User adds own words anytime (also outside the 4 lists) | `POST /api/bank/add` (bulk paste), `POST /api/bank/add-word` and `POST /api/bank/import` (re-import of an export); normalisation → ECDICT inflection table → optional full `stardict.db` → private provisional word + Claude lookup (visible to every user who holds it); `study_today` appends an already-validated word to today's batch, a provisional one joins the first batch after validation (§5) |
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
| Stages | 初中 / 高中 / 四级 / 六级 | `zk` / `gk` / `cet4` / `cet6` (stage index 1–4) |
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
│   │   ├── routers/   health(P0, implemented) auth account onboarding settings vocab words screen bank suggestions today history media admin_users admin_ops admin_reports
│   │   ├── services/  stats_core(P0: daily_stats.on_action, §7.1) words ecdict bank srs batches screen stats suggestions
│   │   ├── jobs/      queue.py registry.py worker.py scheduler.py
│   │   ├── ai/        runner.py budget.py content.py lookup.py consolidate.py svg.py prewarm.py probe.py prompts/*.txt schemas/*.json   # prewarm.py = the prewarm_plan handler
│   │   ├── images/    providers/{base,wikimedia,openverse,pixabay,pexels}.py select.py fetch.py store.py quota.py card_svg.py sanitize_svg.py handler.py
│   │   ├── delivery/  mailer.py email.py webhook.py templates/daily_email.html daily_email.txt
│   │   ├── seed.py  backup.py
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
claude-cwd/                      EMPTY dir used as cwd for `claude -p`
claude-logs/YYYY-MM-DD/<call_id>.json   raw CLI stdout/stderr, kept 14 days, 0600
backups/word-dance-YYYYMMDD-HHMM.db.gz  nightly (timer) + pre-migrate-<version>.db.gz
tmp/                             downloads in flight
```

`git pull && deploy/install.sh` never touches the data directory.

**Seed location.** The compact seed ships in the repository at `data/seed/vocab.jsonl.gz`, *outside* the `wd` package. Its path is a config value, `WD_SEED_PATH`, defaulting to `Path(wd.__file__).parents[2] / 'data' / 'seed' / 'vocab.jsonl.gz'` (the repo root resolved from the installed package — correct for the `pip install -e backend` layout install.sh uses). `wd import-seed --file` defaults to it, and the lifespan's seed check compares `kv.seed_version` with the sha256 of the file at `WD_SEED_PATH` (import when they differ, warn-and-continue when the file is missing). A non-editable install must set `WD_SEED_PATH` explicitly (DEPLOY §4).

---

## 3. Data model (full DDL in `SCHEMA.sql`)

Conventions: timestamps are UTC ISO-8601 `YYYY-MM-DDTHH:MM:SSZ` (SQL default `strftime('%Y-%m-%dT%H:%M:%SZ','now')`, Python `clock.now_iso()`), local dates `YYYY-MM-DD` in the user's IANA timezone, booleans `INTEGER 0/1` with `CHECK`, JSON in `TEXT`. Per-connection PRAGMAs: `journal_mode=WAL, synchronous=NORMAL, foreign_keys=ON, busy_timeout=5000, temp_store=MEMORY, cache_size=-20000`. Connections are opened with `sqlite3.connect(path, autocommit=True)` (Python 3.12 API: the module never starts implicit transactions, so `executescript()` cannot sneak in an implicit `COMMIT`); `db.tx()` and `run_migrations()` issue explicit `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK`; `SQLITE_BUSY` retried 3× (50/100/200 ms). One connection per request/job (never shared across threads).

### 3.1 Table groups and rationale

| Group | Tables | Rationale |
|---|---|---|
| System | `schema_migrations`, `kv`, `system_events` | migrations bookkeeping (rows written by `db.run_migrations()` only — never by a migration file; SCHEMA.sql §1); runtime flags (`seed_version`, `worker_lease`, `claude.paused_until`, `claude.flag_tier`, `last_tick_at`, `maintenance.last_date`, `consolidate:<user_id>:last_date`, `prewarm:<plan_id>:spent`); operator-visible events (downtime with `{from,to}` bounds, budget, auth failures). |
| Identity | `users`, `sessions`, `invite_codes`, `auth_throttle`, `email_codes`, `user_settings` | server-side sessions (hashed tokens); invite codes hashed with uses/expiry; **persistent** login throttling (survives restarts); 6-digit e-mail verification codes; one settings row per user created in the same transaction as the user. `user_settings.next_push_at` (UTC, indexed) lets the tick select due users. |
| Vocabulary (shared) | `words`, `word_forms` | one row per normalised `lemma`; stage flags `stage_zk/gk/cet4/cet6` (cumulative as in the sources) + `stage_min` (1–4, lowest stage; `NULL` = outside the four lists) which gives the 仅本阶段新增 filter for free (`stage_min = 4` is the 3,694-word CET-6 increment); `kind` (word/phrase/abbreviation/proper_noun) keeps acronym casing; `is_public`/`is_valid_english`/`safe_for_sharing` gate user-added words; `merged_into_word_id` for consolidation merges. `word_forms` is keyed `(form, word_id)` so ambiguous forms are representable (FACTS §4b counts 47 in the raw exchange data; after dropping the 11 empty strings and the headword-forms, 28 remain in the seed — e.g. bases→base/basis, axes→ax/axe/axis; acceptance pins only `bases` → 2); forms that are themselves headwords (388, e.g. data, better, running, clothes) are never inserted — the headword guard of the seed import and of `words.add_form`. The one deliberate exception is a `lookup_word` **merge** (CLAUDE_INTEGRATION §6.5 step 3): it records `W.lemma → L` as an `alt` form while the merged-away row `W` keeps its lemma with `merged_into_word_id = L`; resolution is unaffected (the exact step already follows the merge), so on a live database the invariant reads `word_forms wf JOIN words w ON w.lemma = wf.form AND w.merged_into_word_id IS NULL` = 0 (the WP1 acceptance query without that predicate holds on a fresh import). |
| Generated (shared) | `word_contents`, `word_images` | versioned per word; exactly one `active` row each; `words.active_content_id/active_image_id` are logical pointers (no FK cycle). Content is **never per user**. |
| Per-user learning | `user_words`, `review_logs`, `daily_stats` | one row per (user, word) ever touched; SRS fields on the row; `review_logs` is the append-only history with `client_event_id` idempotency and a `prev_srs_json` snapshot on every `master`/`known` transition (what `restore` puts back); `daily_stats` powers heatmap/streak cheaply. |
| Daily push | `push_batches`, `push_items` | `UNIQUE(user_id, local_date)` is THE idempotency guarantee; items carry `kind` review/new/screen/extra and are unique per `(batch_id, word_id, kind)` — a 推荐词 graded 不熟悉 inside the batch keeps its `screen` row and gains a `new` row (§6.3). |
| Consolidation | `consolidation_runs`, `bank_suggestions` | audit of nightly 整理 and the user-facing 整理建议 inbox (open/accepted/rejected/expired/auto with 7-day 撤销). |
| Jobs & accounting | `jobs`, `ai_calls`, `provider_usage`, `provider_state`, `content_reports` | durable queue with dedupe keys and `UPDATE … RETURNING` claims; one ledger row per `claude` spawn (inserted *before* the spawn); provider quota counters per minute/day window persisted; user reports for content/image/dictionary problems. |

### 3.2 Seed record → `words` mapping (record format of `data/seed/vocab.jsonl.gz`, verified)

| Seed field | `words` column | Note |
|---|---|---|
| `word` | `display`; `lemma = normalise(word)` | keeps ECDICT casing (`China`, `a.m.`, `ice cream`) |
| `phonetic` | `phonetic` | already `ә→ə`, `:→ː` normalised by the builder |
| `translation[]` | `translation` (`'\n'.join`) | zh lines |
| `definition[]` | `definition` (`'\n'.join`) | en lines |
| `pos`, `collins`, `oxford`, `bnc`, `frq` | same names | `0`/`null` frequency = unknown (sorted last) |
| `stages[]` | `stage_zk/gk/cet4/cet6`, `stage_min` | `stage_min` = index of the first element (1 zk, 2 gk, 3 cet4, 4 cet6) |
| `exam_tags[]` | `exam_tags` (space-joined) | ky/toefl/ielts/gre |
| `exchange{}` | `exchange_json`; rows in `word_forms` | only codes `p d i 3 s r t`; ignore `0 1` (lemma pointers) and the undocumented duplicates `f b z` (plural/comparative/superlative copies) |
| `sources[]`, `ecdict_id`, `cet6_star` | `sources`, `ecdict_id`, `cet6_star` | provenance; `cet6_star` is set on the **1,714** seed words that carry the star (the starred list has 1,721 entries — `stats.json.syllabus_sizes.cet6star` — 7 of which match no seed lemma; the importer copies the record flag and never reads the list) |
| — | `kind` | derived: contains space → `phrase`; matches `^[A-Z]{2,6}$` or contains `.` → `abbreviation`; first letter upper-case → `proper_noun`; else `word` |
| — | `source='seed'`, `is_public=1`, `is_valid_english=1`, `safe_for_sharing=1` | seed words are trusted |

Measured counts (acceptance numbers): 9,162 words; per stage zk 2,099 · gk 3,829 · cet4 4,722 · cet6 7,671; `stage_min` distribution 2,099 / 1,792 / 1,577 / 3,694 (`stats.json`; FACTS §4b prints gk 1,793 — `stats.json` is authoritative); 13 multi-word, 141 capitalised; one syllabus miss (`instalation`, a typo in the CET_4+6 list). `word_forms` after guards ≈ 14,100 rows.

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
| `stages_json` | 目标阶段 | from onboarding (multi) | non-empty subset of zk/gk/cet4/cet6 |
| `current_stage` | 主攻阶段 | from onboarding | stored 1–4, `Stage` string on the wire (API.md §9.1); 推荐词 ordering starts here and moves outward |
| `show_images`, `zh_examples` (`tap`/`always`), `auto_pronounce`, `accent` (`en-US`/`en-GB`) | 学习设置 | 1, `tap`, 1, `en-US` | |
| `email_enabled` | 邮件推送 | 0 | requires verified e-mail + server SMTP |
| `webhook_enabled`, `webhook_url`, `webhook_format` | Webhook 推送 | 0, –, `generic` | `generic`/`wecom`/`feishu`/`serverchan`/`bark`; https + SSRF check |
| `next_push_at` | (read-only 下次推送) | computed | UTC; recomputed on save and after each publish by the pure `clock.compute_next_push()` |

### 6.2 Onboarding (first login)

`users.onboarding_state ∈ 'pending' | 'screen' | 'done'`. Registration (API.md 2) already inserts the `user_settings` row **with `next_push_at` computed from the defaults** (`Asia/Shanghai`, `08:00`) in the same transaction, so the tick's `WHERE next_push_at <= …` never silently skips a user. `/welcome` step 1 (`POST /api/onboarding`): 目标阶段 multi-select (default pre-checked by self-description buttons: 初中生 → zk · 高中生 → zk+gk · 大学生 → gk+cet4+cet6 · 职场人士 → cet4+cet6), 主攻阶段, 推送时间, 时区 (auto-detected via `Intl.DateTimeFormat().resolvedOptions().timeZone`) → state `screen`, `next_push_at` recomputed. Step 2: 筛词 of 20–30 words from `current_stage` (`GET /api/screen/next`); skippable. `POST /api/onboarding/complete` sets `done` **only from `screen`** (409 `invalid_transition` from `pending`; idempotent from `done`), so no client path reaches `done` without step 1. **Gate**: until `done`, the SPA redirects `/`, `/today`, `/study`, `/history` and `/history/:batchId` to `/welcome` (`RequireOnboarded`, FRONTEND §2) and the API answers 409 `onboarding_required` on the `O` endpoints (`/api/today*`, `/api/history*`, `/api/batches/*`, `/api/stats`); browsing 词库, the 生词库, 筛词, word pages and 设置 work before onboarding (their endpoints are `U`) — one rule in DESIGN, API.md §1 and FRONTEND §2. The default stage range and recommendation order therefore always derive from the user's own choice.

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
             ORDER BY stage_distance(w.stage_min, current_stage) ASC,          # 0 for the 主攻阶段, then higher stages, then lower
                      (w.frq IS NULL OR w.frq=0) ASC, w.frq ASC, w.lemma ASC
             LIMIT daily_screen_count
             where stage_distance(s, cur) = 0 if s==cur, 2*(s-cur)-1 if s>cur, 2*(cur-s) if s<cur
5. core = spread_similar(interleave(reviews, news))               # both defined below; pinned by tests/fixtures/batch_order.json
   cold_start = not core ; ordered = screens + core if cold_start else core + screens
6. INSERT push_items(position = index, kind per source, user_word_id for review/new)
7. UPDATE push_batches SET review_count, new_count, screen_count, deferred_reviews
8. UPDATE user_words SET times_pushed+=1 for review ∪ new                 # once per batch the word is placed in (§6.4 guarantees a batch is built on its own local day)
9. For each word in the batch with content_state IN ('none','failed') AND is_valid_english = 1: enqueue generate_content (priority 20);
   lacking an image: fetch_image is enqueued by the content handler        # never for is_valid_english IS NULL (none can be in the batch after step 3)
```

**`interleave(reviews, news)`** (deterministic, pure): if either list is empty return the other unchanged; else `k = ceil(len(reviews) / len(news))`; emit `k` reviews then 1 new, repeat; when one list runs out append the rest of the other in order. 26 reviews + 10 news → `k = 3` → `R R R N` × 8 (24 R, 8 N) then `R R N N` — the "3R,1N pattern" pinned in WP4. **`spread_similar(seq)`**: single stable left-to-right pass; two items are *similar* when both lemmas have ≥ 4 letters and share their first 4 letters (shorter lemmas are never similar); for each position `i`, if item `i` is similar to any item at `i-3..i-1`, move it to the first later position `j > i` where it is similar to no item at `j-3..j-1` (shifting the items in between one place left); if no such `j` exists leave it where it is. Both functions and the pinned 26R/10N expectation live in `tests/fixtures/batch_order.json`.

The builder never waits on Claude or image providers. `finalize_building()` (tick) flips `building → ready` when nothing more is coming for the batch's words: no item has `content_state='queued'` with a live content job due before the day's end, and (images on) no item has `image_state='queued'` (a fetch in flight) — a word with `image_state='none'` (prefetched or old content; no image job will ever run for it) never holds the batch —, **or immediately when nothing can be generated for it anyway**: AI disabled (`WD_AI_ENABLED=0` / `kv.claude.enabled='0'`), paused (`kv.claude.paused_until > now`), or every live content job of the batch's words has `run_after ≥ day_start(local_date+1)` (budget/monthly deferral, CLAUDE_INTEGRATION §7) — or after 2 h at the latest. `ready` therefore means "nothing more is coming today", never "everything has content"; the UI never waits for it: items render with ECDICT data + template card + 「例句生成中…」 and poll `GET /api/words/{id}/content` every 5 s (max 24 polls) unless `deferred_until` is set (then 「今日 AI 额度已用完，例句将在明天补齐」, no polling — API.md 24).

Ungraded `new`/`learning` items remain due and reappear tomorrow; ungraded `screen` words are simply re-selected. **Late sessions**: yesterday's batch stays gradable (API.md 45) while it has ungraded `review`/`new`/`extra` items; `GET /api/today` reports it as `previous_open_batch` and the 今日 page offers 「继续昨天的学习（还剩 N 个）」 → `/study?batch=<id>` with the grade bar (`Batch.gradable=true`); older batches are replay-only. `POST /api/today/more {source:'new'|'screen', count}` appends `extra` items (3 rounds/day) to any existing batch of the day, including one still `building` (appending never waits for content; 409 `batch_not_ready` only when no batch exists yet). **Word uniqueness inside a batch** is per `(batch_id, word_id, kind)` (SCHEMA): a screening verdict `unfamiliar` on a 推荐词 inside the batch keeps the `screen` row (`result='unfamiliar'`) and, while `new_done + new_remaining < daily_new_count`, `append_to_today(kind='new')` adds a second row for the same word at the end of the queue (`ScreenResponse.study_item` / `GradeResponse.study_item`); otherwise the word waits for tomorrow (toast 「已加入生词库，明天开始学」). `append_to_today` (also used by `study_today` extras and `/today/more`) never creates a second gradable row: words already present as `review`/`new`/`extra` are skipped; a word present only as `screen` gets its study row.

**Stale items.** A batch may be built up to `WD_PREBUILD_HOURS` before study and the user (or the 02:30 consolidation) may change state in between. Rules, applied by `today_response` and `grade_item` (API.md 43/45): an **ungraded** `review`/`new`/`extra` item whose `user_words.state` is no longer `new`/`learning` (mastered, removed, reset-then-removed …), an ungraded `screen` item whose word now has a `user_words` row (marked in 词库 during the day), and any item whose word has `merged_into_word_id IS NOT NULL` are hidden from `items` and excluded from every `counts` field; grading a hidden item returns 409 `invalid_transition`; graded items are history and always stay. `restore` makes a hidden item visible again by clearing its result and state. Consolidation/lookup repoints (`user_words.word_id` W → L) also run `UPDATE push_items SET word_id = L WHERE word_id = W AND batch_id IN (open batches of that user)` so the card shows the merged headword (`user_word_id` is unchanged because the row itself was repointed).

### 6.4 Scheduler tick (`jobs/scheduler.py`, every `WD_TICK_SECONDS=60`)

```
tick(now):
  for s in user_settings JOIN users(is_active=1, onboarding_state='done')
           WHERE push_enabled=1 AND next_push_at <= now + WD_PREBUILD_HOURS:
      tz = ZoneInfo(s.timezone)
      target_date = max(local_date(s.next_push_at, tz), local_date(now, tz))      # never build a past day
      build_from = max(s.next_push_at - WD_PREBUILD_HOURS, day_start(target_date, tz))   # a batch is ALWAYS built on its own local day
      if now >= build_from:                                                             # push 01:00 → window shrinks to 00:00–01:00, never 22:00 the evening before
          batch = build_batch(user, target_date, trigger = 'scheduled' if now < s.next_push_at else 'catchup')   # no-op if it exists
      if now >= s.next_push_at:
          if publish_batch(batch):                 # UPDATE … SET status='published' WHERE status != 'published' → rowcount gates delivery
              enqueue send_email / send_webhook (dedupe 'email:<id>' / 'webhook:<id>') unless stale (> 6 h late → status 'skipped')
          UPDATE user_settings SET next_push_at = compute_next_push(now, tz, push_time) WHERE user_id=? AND next_push_at = s.next_push_at
  finalize_building()
  hourly: delete expired sessions, prune auth_throttle, requeue stale running jobs (boot_id sweep)
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

Idempotency: `UNIQUE(user_id, local_date)` + the conditional `UPDATE` on publish + delivery dedupe keys + the `WHERE next_push_at = ?` guard + the per-user `consolidate:*:last_date` guard. The `build_from` clamp means a push time shortly after midnight gets a shorter prebuild window (built from 00:00 local) instead of being built the previous evening while the user may still be studying today's batch — so items graded late in the evening can never sit in tomorrow's batch as stale `review`/`new` rows and `times_pushed` is never double-counted. Catch-up after downtime builds today's batch only; missed days are not back-filled (their reviews are simply more overdue and come first). Changing `push_time`/`timezone` recomputes `next_push_at`; if the new time already passed today and no batch exists, the next tick builds it (no duplicates). `POST /api/today/build` calls the same `build_batch(trigger='manual')`; the tick later only publishes it. The downtime event's `{from, to}` bounds define `DayStats.offline` (API.md §9.1): a local day with no batch that overlaps a recorded gap.

### 6.5 Delivery channels (best-effort; the in-app page is the source of truth)

* **In-app** (always): `/today`; a dot on the 今日 tab while ungraded items exist.
* **Public URL for links** (`delivery.public_url()`): delivery jobs run inside the scheduler with no HTTP request, so nothing can be derived from a `Host` header. Rule: `WD_PUBLIC_URL` when set (install.sh writes the LAN URL `http://<first LAN IP>:<WD_PORT>` into it when no reverse proxy is configured, and `https://<domain>` with one — DEPLOY §2/§4) → else `kv.public_url_guess` (`http://<first non-loopback IPv4 of the host>:<WD_PORT>`, computed by `main.py` at startup, the Python equivalent of `hostname -I | awk '{print $1}'`) → else **no link**: the e-mail button and the webhook `url` field are omitted and the text says 「请在浏览器中打开 word-Dance」.
* **E-mail** (`send_email` job): requires `WD_SMTP_HOST`, `users.email_verified_at` and `email_enabled`. Subject `【word-Dance】今日词汇 10月14日 · 复习 12 · 新词 10`, first 10 words (word, phonetic, meaning_zh, first example en/zh), button → `<public_url>/today` (omitted when no public URL is known), text alternative, no images. STARTTLS/SSL/none; retries 1 min / 10 min / 60 min; `push_batches.email_status`. The 发送测试邮件 button enqueues `send_email {"user_id", "test": true}` (dedupe `email:test:<user_id>`, subject `【word-Dance】测试邮件`, body = the user's next push time in their timezone + the link; API.md 18).
* **Webhook** (`send_webhook` job): `POST webhook_url` with 10 s timeout, no redirects, SSRF guard (https, public IP, DNS-pinned). Formats: `generic` JSON `{type, date, title, body, counts, words:[{word, phonetic, meaning_zh}], url}` (`url: null` when no public URL is known); `wecom` `{"msgtype":"text","text":{"content":…}}`; `feishu` `{"msg_type":"text","content":{"text":…}}`; `serverchan` `{"title":…,"desp":…}`; `bark` `{"title":…,"body":…,"url":…}` (`url` key omitted when unknown). 发送测试 button in settings (1 per 10 min).

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

`on_action(conn, user_id, local_date, *, action, context, new_state, item_kind, elapsed_ms, undone=None)` upserts the `(user_id, local_date)` row (`INSERT … ON CONFLICT DO UPDATE`). Called by WP3 (`bank.apply_action`, `apply_verdict`, `add_custom_words`, `import_rows`, suggestions) and WP4 (`grade_item`) right after the `review_logs` row is written; `local_date` is the user's local date of the action. `screening` below = `context IN ('screen_page','onboarding')` or `item_kind = 'screen'`; `card` = `item_kind IN ('review','new','extra')`.

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
* Jobs: `generate_content` (≤ 10 words/call — `WD_AI_BATCH_SIZE` is clamped to 1–12 because `content_v1.json` has `maxItems: 12`; priority 10/20/30/90), `lookup_word` (≤ 20 strings/call), `consolidate_bank` (1 user/call), `generate_svg` (default on, only for words a user studies, own daily sub-cap), `prewarm_plan` (admin, budgeted; fans out in passes of `5 × WD_AI_BATCH_SIZE` with `plan_id` on each content job). Per-word dedupe keys; the worker always takes the **head job across all Claude job types** (`ORDER BY priority, run_after, id`) so a user's priority-10 lookup is never queued behind hundreds of priority-20/90 content jobs; batching at claim time; bisection 10 → 5 → 3 → 2 → 1 on `--max-budget-usd` stops or a second group failure; `auth` failures pause AI 30 min with an admin banner.
* Budget: measured $0.040 per 10-word call ($0.004/word; whole seed ≈ $37). Defaults: per call 0.25 (content) / 0.15 (lookup) / 0.40 (consolidate) / 0.10 (svg) / 0.05 (probe); daily `WD_AI_DAILY_BUDGET_USD=3.00`, monthly `40.00`, prewarm sub-cap `1.00/day`, SVG sub-cap `WD_AI_SVG_DAILY_BUDGET_USD=0.50/day` (≈ 18 cards at the measured $0.028, counted inside the daily cap); reservation `est = 0.005 + 0.0045 × words` before each call; hourly call cap 60; kill switch; caps defer (`run_after` = next `WD_TZ` day 00:05), never fail.
* Content triggers only: a validated word enters a bank, a word is selected for a batch/prefetch, an explicit per-user request (60/day), `lookup_word` validating a custom word, or an admin action. Words with `is_valid_english IS NULL` are skipped by every enqueue site and dropped by the content handler. Browsing never spends money.

---

## 9. Image pipeline (`images/`)

```
fetch_image(word, exclude=()):                                   # IoWorker, one job at a time
  keywords = (content.image_keywords[:3] if content else []) or [lemma]
  for kw in keywords:
      for provider in chain (default: wikimedia, openverse[, pixabay, pexels if keyed]):
          if job.priority >= 90 and provider is openverse: continue      # prewarm never spends Openverse quota
          if not quota.allow(provider): continue                         # minute/day counters + cooldown, persisted
          cands = provider.search(kw, limit=10) ; quota.record(provider)
          for best in select.rank(cands, kw, exclude)[:3]:               # several candidates, ranked
              img = fetch.download_and_store(best)                       # SSRF-safe, pinned DNS, Pillow re-encode
              if img: activate(img); return
  if WD_SVG_VIA_CLAUDE (default 1) and job.priority < 90                      # never for prewarm
     and word_is_studied(word):                                                # EXISTS user_words(state IN ('new','learning')) OR EXISTS push_items for an open batch
      enqueue generate_svg(word_id, priority = job.priority)                   # budgeted by WD_AI_SVG_DAILY_BUDGET_USD (CLAUDE_INTEGRATION §7), sanitised (§6.7)
  words.image_state = 'failed'                                                 # → the template card is served now; the SVG replaces it when it lands
```

* **Wikimedia Commons (primary)**: `action=query&generator=search&gsrsearch=<kw> filetype:bitmap&gsrnamespace=6&gsrlimit=10&prop=imageinfo&iiprop=url|extmetadata|size|mime&iiurlwidth=800&format=json` — **no `formatversion=2`**: the provider parses the legacy shape the verified fixture `probe/wm.json` has (`query.pages` is an object keyed by pageid; each page has `title`, `pageid`, `imageinfo[0].{thumburl, thumbwidth, thumbheight, url, descriptionurl, extmetadata{…}}`; `batchcomplete`/`continue` ignored). Header `User-Agent: word-Dance/<ver> (self-hosted vocabulary trainer; +<WD_PUBLIC_URL>; <WD_CONTACT_EMAIL>)`. Download `thumburl` (≤ 800 px), never the original `url`. Hosts: the API answers from `commons.wikimedia.org`; **thumbnails are served from `thumb.wikimedia.org`** (verified in the fixture, e.g. `https://thumb.wikimedia.org/wikipedia/commons/thumb/1/15/Red_Apple.jpg/960px-Red_Apple.jpg?utm_source=…`), originals from `upload.wikimedia.org`; both `thumburl` and `url` may carry a `?utm_source=…&utm_campaign=…&utm_content=…` query string, which the provider **strips** (any `utm_*` parameter) before the URL is used as `source_url`, excluded, or compared — the download itself goes through `fetch.safe_download` like any other https URL (no host allow-list for images, only the SSRF rules). Politeness ≤ 1 req/s (process-wide lock), soft day limit 2000, 429/503 → cooldown 15 min. Licence allow-list: `LicenseShortName` starting `CC0`, `Public domain`, `PD`, `CC BY`, `CC BY-SA` (no NC/ND).
* **Openverse (secondary)**: `GET https://api.openverse.org/v1/images/?q=<kw>&page_size=20&license_type=commercial&mature=false`; anonymous limits measured 20/min burst, 200/day → enforce `WD_OPENVERSE_MINUTE_LIMIT=15`, `WD_OPENVERSE_DAILY_LIMIT=160` in `provider_usage` (window `minute`/`day`, UTC); 429 → cooldown `Retry-After` or 10 min. Download `url` (full image) only — **never** the `thumbnail` on `api.openverse.org` (it spends API quota). Optional registered app (`WD_OPENVERSE_CLIENT_ID/SECRET`) raises limits. Licence allow-list `cc0, pdm, by, by-sa`.
* **Selection** (`select.rank`): hard rejects — `mature`, non-empty `unstable__sensitivity`, Commons `Restrictions`, licence not allowed, mime not jpeg/png/webp, `width < 400 or height < 300`, aspect outside 0.6–2.2, title/tags/categories matching `\b(map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document|nude|nudity|sex|porn|gore|blood|weapon|gun|corpse)\b`, excluded ids/sha. Score: +1 per keyword token in title/tags (max +3), licence cc0/pd +3 / by +2 / by-sa +1, aspect 1.2–1.8 +1, width ≥ 800 +1, Commons `Assessments` featured/quality/valued +2, filename-like titles (`IMG_`, `DSC`, years) −1, already used sha −2. Minimum score 1.
* **Download** (`fetch.safe_download`): `https` only; resolve all A/AAAA; reject loopback, 10/8, 172.16/12, 192.168/16, 169.254/16, 100.64/10, 224/4, 0/8, `::1`, `fc00::/7`, `fe80::/10`; connect to the validated IP with `Host` header and `extensions={'sni_hostname': host}` (DNS pinning); ≤ 3 redirects each re-validated; `Content-Type image/*`; stream ≤ `WD_IMAGE_MAX_BYTES=8_000_000`; magic bytes JPEG/PNG/WebP; Pillow `MAX_IMAGE_PIXELS=40_000_000`, `verify()`, reopen, `exif_transpose`, RGB, long edge ≤ 800, JPEG q82 progressive, no EXIF/ICC; `sha256` of the re-encoded bytes → `images/<2hex>/<sha>.jpg` (0600); same sha reused across words. Insert `word_images(status='active')`, previous active → `superseded`, `words.active_image_id`, `image_state='ready'`.
* **Template card** (`card_svg.render(word, content)`): deterministic 800×500 SVG from DB data (pastel gradient from `hash(lemma)`, headword 72 px, phonetic, first `meaning_zh`/translation line, first example, small mark), XML-escaped, served at `GET /media/card/{word_id}.svg` with an in-memory LRU(2000) keyed by `(word_id, active_content_id)`. No file, no network, no Claude — every word always has an image URL.
* **Claude SVG** (`WD_SVG_VIA_CLAUDE=1` by default; `0` turns it off): the FACTS §4 last resort before the text-only card. Enqueued only when every photo provider failed for a word that a user actually studies (in a bank or an open batch) at priority < 90 — never for prewarm — and spent under `WD_AI_SVG_DAILY_BUDGET_USD=0.50` (≈ 18 cards/day at the measured $0.028; `system_events('budget_svg')` once per day when hit, jobs deferred to the next `WD_TZ` day while the template card is served). Schema `{svg, alt_zh}`, `--max-budget-usd 0.10`; sanitised with `defusedxml` + element/attribute allow-list (drop `on*`, `href`, `xlink:href`, `style` with `url(`, `<script>`, `<image>`, `<foreignObject>`, `<use>`, entities; size ≤ 60 KB; enforce `viewBox`); stored as `.svg`, served with `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'`, `nosniff`; the UI always embeds via `<img>`. The admin overview reports `with_photo` / `with_claude_svg` / `card_only` and `svg_today_usd` vs the sub-cap, so the operator sees the photo hit rate and can raise the SVG budget (DEPLOY §11).
* **User controls**: `POST /api/words/{id}/image/refresh` (换一张, 20/day/user) enqueues `fetch_image` with `exclude = current provider_refs + shas` at priority 10; `POST /api/words/{id}/report {target:'image'}` (不合适) marks the active image `rejected` and triggers a refresh immediately (threshold 1 — a 1–5-user deployment cannot wait for three flags).
* **Attribution**: `attribution_text` = `"{title}" · {creator} · {license}` (Openverse's own `attribution` sentence when present; Commons `Artist` HTML stripped), `landing_url`, `license_url`; caption under every picture `图片：{title} · {creator} · {license} ↗`; generated images show `AI 生成示意图` / `系统生成卡片`. `ATTRIBUTION.md` (repository root, linked from the README) documents provider terms; the in-app 关于与数据来源 section of 设置 shows the fixed source lines of FRONTEND §5.8 (dictionary, word lists, image sources, AI notice) rather than rendering the Markdown file (P0_STATUS §3 item 27).

---

## 10. Security and privacy

| Area | Measures |
|---|---|
| Registration | `WD_REGISTRATION_MODE=invite` (default) / `open` / `closed`; invite codes stored as `sha256` in `invite_codes` with `max_uses`/`expires_at`, consumed atomically (`UPDATE … SET uses=uses+1 WHERE uses<max_uses AND (expires_at IS NULL OR expires_at>now)` must affect 1 row); created by `wd invite` or the admin page (shown once). **Bootstrap**: while `users` is empty, `POST /api/auth/register` accepts the registration in any mode without an invite code and makes that user `admin` (count check + insert inside one `BEGIN IMMEDIATE`, so two racing first registrations yield exactly one admin); `GET /api/health.needs_setup=true` lets the login page say 「尚无账号，首个注册的账号将成为管理员」. `wd create-admin --if-none` remains the unattended alternative (`WD_ADMIN_USERNAME/PASSWORD`). |
| Passwords | bcrypt cost 12, 8–64 chars, not equal to the username, not in a shipped 1k common-password list; constant-time verify with a dummy hash for unknown users; password change deletes other sessions. |
| Sessions | `secrets.token_urlsafe(32)` in cookie `wd_session` (`HttpOnly; SameSite=Lax; Path=/; Max-Age=2592000`; `Secure` when `WD_PUBLIC_URL` is https or `WD_COOKIE_SECURE=1`); DB stores `sha256(token)`; sliding expiry once per day; max 20 sessions/user; GC hourly. |
| CSRF | SameSite=Lax + mandatory header `X-WD-Request: 1` on every non-GET `/api/*` + `Origin`, when present, must equal the request's own Host-derived origin or the origin of `WD_PUBLIC_URL` (`http://localhost:5173` in dev) — API.md §1; no CORS middleware. |
| Throttling | `auth_throttle` table (persistent): login 20/10 min per IP; 10 failures per username → lock 15 min doubling per further 5 failures (max 24 h), reset on success; register 5/h per IP; custom adds 200/day; content requests 60/day; image refresh 20/day; reports 20/day; mutations 300/min per user (every authenticated non-GET request, counted in `deps.current_user`); password re-checks for change-password / delete-account 10 per 15 min per user, cleared by a correct password (a stolen session cookie must not allow online guessing — the login lockout covers `/api/auth/login` only). Client IP from `X-Forwarded-For` only when `WD_TRUST_PROXY=1`. |
| Authorisation | two roles; ownership enforced in SQL (`user_id = :me`); private words visible only through the §5.2 visibility rule (creator, any holder of a `user_words` row, admins); a foreign id yields 404 (no existence leak); the last active admin cannot be disabled/demoted/deleted (409 `last_admin`). |
| Headers | `Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`, HSTS when https, `Cache-Control: no-store` on all `/api` JSON. Body limit 1 MB. |
| Prompt injection | user strings reach Claude only as JSON string values inside a labelled data block after the charset/length rules of §5.1 (≤ 48 chars, letters/space/`'`/`-`/`.`), plus — in the per-user consolidation prompt only — a ≤ 120-char sanitised note; `--tools ""`, empty cwd, no session persistence (and `--restricted --strict-mcp-config` when probed OK); schema-constrained output; server post-validation (word must match request, examples must contain the headword/form, length caps, CJK/ASCII checks, no URLs/HTML); any Claude-proposed headword that would mutate shared rows passes the deterministic validator + relatedness rule; typo corrections never auto-applied; Claude cannot address rows outside the batch it was given; output rendered as text by React. |
| SSRF | §9 guard for image downloads and user webhooks (https only, public IPs on every hop, DNS pinning, ≤ 3 redirects, byte/pixel caps, magic bytes, re-encode; webhooks additionally deny `localhost`, `.local`, `.internal`, raw IPs, 10 s timeout, no redirects). Provider API hosts are constants. |
| SVG | sanitiser allow-list, `<img>` embedding only, sandboxing CSP on `/media`. Template card escapes all text. |
| Subprocess | argv list, fixed binary path, allow-listed env, empty cwd, `stdin=DEVNULL`, timeout + process-group kill, stdout/stderr caps (10 MB). |
| Files | `UMask=0077`; data dir 0700; DB/WAL/`.env`/images/backups 0600; secrets only in `.env`; `GET /api/admin/config` masks them; logs never contain passwords, tokens or prompts (word lists only at DEBUG). |
| Privacy | personal data = username, optional e-mail, display name, learning history, notes; user-added words private until validated; export (`GET /api/account/export`), re-import (`POST /api/bank/import`) and self-service deletion (`DELETE /api/account` with password, cascades; shared provisional words survive while another user holds them); no third-party analytics; images self-hosted (providers never see end-user IPs); Claude never receives usernames or e-mails, and a user's private 备注 never reaches the shared content prompt (§5.3) — shared `word_contents` can therefore never echo another user's note. |

---

## 11. Deployment overview (details in `DEPLOY.md`)

* `deploy/install.sh` (idempotent, run as `sqin`, `sudo -n` only for systemd/proxy files): preflight → venv + pip → `npm ci && npm run build` → data dir + `.env` (secrets generated; every value double-quoted; `bash -n` check before sourcing) → **stop the unit if it is running** (unless `--no-restart`, so a non-additive migration never runs under a live old process) → `wd migrate && wd import-seed` (seed from `WD_SEED_PATH`) → `wd claude-check` (records the flag tier, ≤ $0.05) → `wd create-admin --if-none` → install `word-dance.service` + `word-dance-backup.timer` → start → health check → prints `http://<LAN-ip>:8000` (default bind `WD_HOST=0.0.0.0`; that URL is also written to `WD_PUBLIC_URL` for delivery links) or the https URL when `--with-caddy DOMAIN`/`--with-nginx DOMAIN` set `WD_HOST=127.0.0.1`, `WD_PUBLIC_URL`, `WD_TRUST_PROXY=1`.
* systemd **system** unit `User=sqin Group=sqin`, `EnvironmentFile=/home/sqin/word-dance-data/.env`, `Environment=HOME=/home/sqin PATH=/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin`, `TimeoutStopSec=300` (≥ the longest AI timeout 240 s + grace), `KillMode=mixed`, `UMask=0077`, `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`; **no `ProtectHome`** (OAuth credentials in `/home/sqin/.claude*`; Linger is off so a user unit is not an option).
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
| 1 | Reuse the verified seed and builder; measured counts | `scripts/build_seed.py` copied verbatim; `data/seed/vocab.jsonl.gz` from the verified file; importer consumes the exact record format; acceptance pins 9,162 / 2,099 / 3,829 / 4,722 / 7,671 / 3,694 (§3.2, TASKS WP1) |
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

08:00 Asia/Shanghai, user `bob` (目标阶段 四级+六级, 主攻 四级, 10 new, 15 推荐词, 60 reviews, images on, 企业微信 webhook on). 05:00 tick (`next_push_at − 3 h`): `build_batch` → 12 reviews due, 4 `new` from the bank, 15 推荐词 (unseen CET-4 words by frequency). 3 of the 31 words lack content → `generate_content` ×3 (priority 20) → one `claude -p` call (≈ $0.02) → content stored → `fetch_image` ×3 → IoWorker fetches 3 photos from Wikimedia Commons (≈ 10 s). 05:02 `finalize_building` → `ready`. 08:00 tick: `publish_batch` → `send_webhook` job → 企业微信 text「word-Dance 今日词汇 10月14日 · 复习 12 · 新词 4 · 推荐 15 …」. 08:20 bob opens `/today`, studies 16 cards in 7 minutes (2 不熟悉 → re-queued after 10 min; 1 已掌握 with the 8-s 撤销 toast — he taps it, `restore` puts the card's 51-day interval back untouched), screens 15 推荐词 (4 不熟悉 → 2 get a second `kind='new'` row appended to today's queue, 2 wait for tomorrow), adds "ubiquitous, GDP" from a report with 今天就学 → neither string is in the 9,162-word seed, so without `WD_ECDICT_DB_PATH` both are provisional (`pending_ai`, badge 待校验; with the optional full ECDICT, `ubiquitous` would resolve instantly and be appended as 加练 right away) → one `lookup_word` call 20 s later validates both (`GDP` → abbreviation), `generate_content` + `fetch_image` follow within a minute (no photo for the abstract `ubiquitous` → Claude SVG concept card), and both appear as 新词 in tomorrow's batch. 02:30 next night: `consolidate_bank` finds that bob's bank has both `analysis` and `analyses`, proposes 「“analyses” 是 “analysis” 的复数，合并？」 in 整理建议.

*End of DESIGN.md.*
