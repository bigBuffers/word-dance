-- ============================================================================
-- word-Dance — SQLite schema  (== backend/wd/migrations/0001_init.sql)
-- SQLite 3.45.1 (Python stdlib sqlite3 on the target box). Directly executable:
--     python3 -c "import sqlite3;sqlite3.connect(':memory:').executescript(open('SCHEMA.sql').read())"
--
-- Conventions
--   * timestamps: TEXT, UTC ISO-8601 'YYYY-MM-DDTHH:MM:SSZ' (lexicographically sortable)
--   * local dates: TEXT 'YYYY-MM-DD' in the user's IANA timezone
--   * booleans: INTEGER 0/1 with CHECK
--   * JSON: TEXT (validated in Python)
--   * every connection sets: PRAGMA journal_mode=WAL; synchronous=NORMAL; foreign_keys=ON;
--     busy_timeout=5000; temp_store=MEMORY; cache_size=-20000  (done in wd/db.py, not here —
--     journal_mode is persistent in the file, the others are per connection)
--   * writes run under BEGIN IMMEDIATE (wd/db.py tx()) and retry SQLITE_BUSY 3x
--   * connections are opened with sqlite3.connect(path, autocommit=True) (Python 3.12 API): the module never opens
--     implicit transactions, so conn.executescript() does NOT issue an implicit COMMIT and a migration file really runs
--     inside the runner's explicit BEGIN IMMEDIATE … COMMIT (verified: in legacy mode executescript commits first and
--     the atomicity guarantee silently fails). tx() and run_migrations() issue BEGIN IMMEDIATE / COMMIT / ROLLBACK themselves.
--   * NOW() is spelled out as strftime(...) because SQLite has no custom default functions
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. System tables
-- ---------------------------------------------------------------------------
-- Migration bookkeeping rule (binding for db.run_migrations() and every NNNN_*.sql file, TASKS P0 step 4):
--   * pending = files backend/wd/migrations/NNNN_*.sql whose NNNN is NOT in schema_migrations
--   * the RUNNER applies each pending file inside ONE `BEGIN IMMEDIATE` transaction (explicit BEGIN on an
--     autocommit=True connection, then conn.executescript(file)) and, in that same transaction, executes
--     INSERT INTO schema_migrations(version, name) VALUES (NNNN, '<name>'); a failing file ROLLBACKs both
--   * migration files therefore NEVER insert into schema_migrations themselves (this file included — see §10)
--   * the RUNNER also owns foreign-key enforcement: `PRAGMA foreign_keys=OFF` BEFORE the BEGIN (inside a transaction the
--     PRAGMA is a silent no-op), `PRAGMA foreign_key_check` before the bookkeeping row (any violation fails the file),
--     `PRAGMA foreign_keys=ON` again afterwards. This is SQLite's own recipe for the table rebuild a CHECK-list change
--     needs (CREATE new → INSERT … SELECT → DROP old → RENAME): with enforcement on, DROP TABLE of a parent would
--     cascade-delete every child row and be committed as applied. Files must not toggle PRAGMA foreign_keys themselves,
--     must delete child rows explicitly when they delete parents (no ON DELETE actions run during a migration), and
--     PRAGMA defer_foreign_keys / rename-first orderings are NOT alternatives (tests/unit/test_db.py)
--   * later files (0008_fk_child_indexes.sql, …) are additive; this file stays the complete baseline schema
CREATE TABLE schema_migrations (
  version    INTEGER PRIMARY KEY,                       -- NNNN from the file name NNNN_name.sql (written by the runner)
  name       TEXT    NOT NULL,
  applied_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- small runtime flags: seed_version, seed_imported_at, last_tick_at, worker_lease (JSON {instance, expires_at}),
-- claude.flag_tier ('0'|'1'), claude.available, claude.paused_until, claude.enabled, maintenance.last_date,
-- consolidate:<user_id>:last_date (local date of the last nightly consolidate_bank enqueue — the "already ran today" guard),
-- prewarm:<plan_id>:spent (USD spent by generate_content jobs carrying that plan_id), backup.last (JSON),
-- public_url_guess ('http://<first non-loopback IPv4>:<WD_PORT>', computed at startup; used by e-mail/webhook links when WD_PUBLIC_URL is empty — DESIGN §6.5) …
CREATE TABLE kv (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
) WITHOUT ROWID;

-- operator-visible events (admin page): downtime, budget_daily, budget_monthly, budget_svg, claude_auth, provider_blocked,
-- content_anomaly, seed_imported, migration, backup_failed …
-- downtime detail_json is {"from": <kv.last_tick_at>, "to": <now>} (UTC); DayStats.offline is derived from these bounds (API.md §9.1)
CREATE TABLE system_events (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_system_events_created ON system_events(created_at);

-- ---------------------------------------------------------------------------
-- 2. Identity, sessions, settings
-- ---------------------------------------------------------------------------
CREATE TABLE users (
  id                INTEGER PRIMARY KEY,
  username          TEXT NOT NULL COLLATE NOCASE,       -- 2–32 chars, ^[A-Za-z0-9_一-龥]+$ (validated in Python)
  email             TEXT COLLATE NOCASE,                -- optional; needed only for the e-mail channel
  email_verified_at TEXT,                               -- set by POST /api/account/email/verify
  display_name      TEXT,                               -- 昵称 (≤ 32), defaults to username in the API
  password_hash     TEXT NOT NULL,                      -- bcrypt "$2b$12$…" (password 8–64 chars)
  role              TEXT NOT NULL DEFAULT 'user'    CHECK (role IN ('user','admin')),
  is_active         INTEGER NOT NULL DEFAULT 1      CHECK (is_active IN (0,1)),
  onboarding_state  TEXT NOT NULL DEFAULT 'pending' CHECK (onboarding_state IN ('pending','screen','done')),
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  last_login_at     TEXT
);
CREATE UNIQUE INDEX ux_users_username ON users(username);
CREATE UNIQUE INDEX ux_users_email    ON users(email) WHERE email IS NOT NULL;

CREATE TABLE sessions (
  token_hash   TEXT PRIMARY KEY,                        -- hex sha256 of the opaque cookie value (raw token never stored)
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  expires_at   TEXT NOT NULL,                           -- created + 30 d; slid forward at most once per day
  last_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  user_agent   TEXT,                                    -- truncated to 200 chars
  ip           TEXT
) WITHOUT ROWID;
CREATE INDEX ix_sessions_user    ON sessions(user_id);
CREATE INDEX ix_sessions_expires ON sessions(expires_at);

-- invite codes are shown once and stored hashed; consumed atomically:
--   UPDATE invite_codes SET uses = uses + 1 WHERE code_hash = ? AND uses < max_uses
--     AND (expires_at IS NULL OR expires_at > now)   -- must change exactly 1 row
CREATE TABLE invite_codes (
  id         INTEGER PRIMARY KEY,
  code_hash  TEXT NOT NULL UNIQUE,                      -- hex sha256 of the code
  created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
  max_uses   INTEGER NOT NULL DEFAULT 1 CHECK (max_uses >= 1),
  uses       INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT,                                      -- NULL = never
  note       TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- persistent throttle / lockout counters (survive restarts)
-- key examples: 'login:ip:1.2.3.4' | 'login:user:alice' | 'register:ip:1.2.3.4' | 'custom:user:7' | 'report:user:7'
--               'refresh:user:7' | 'content_req:user:7' | 'mutate:user:7' | 'email_code:user:7'
--               'pwcheck:user:7' (password re-checks before change-password / delete-account, 10 per 15 min, cleared by a correct password)
--               'study_today:user:7' (bank adds appended to today's batch, 20/day — DESIGN §5.3)
CREATE TABLE auth_throttle (
  key           TEXT PRIMARY KEY,
  window_start  TEXT NOT NULL,                          -- start of the current window (UTC)
  count         INTEGER NOT NULL DEFAULT 0,
  blocked_until TEXT                                    -- lockout end (UTC); NULL = not blocked
) WITHOUT ROWID;

-- 6-digit e-mail verification codes (hashed), 15-minute expiry, max 5 attempts
CREATE TABLE email_codes (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  email      TEXT NOT NULL,
  code_hash  TEXT NOT NULL,                             -- hex HMAC-SHA256(key = WD_SECRET_KEY, msg = code || ':' || user_id) — a 6-digit code must not be brute-forceable from a DB dump
  expires_at TEXT NOT NULL,
  attempts   INTEGER NOT NULL DEFAULT 0,
  used_at    TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_email_codes_user ON email_codes(user_id, created_at);

-- one row per user, created in the same transaction as the user row
CREATE TABLE user_settings (
  user_id            INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  timezone           TEXT    NOT NULL DEFAULT 'Asia/Shanghai',   -- validated against zoneinfo.available_timezones()
  push_time          TEXT    NOT NULL DEFAULT '08:00' CHECK (push_time GLOB '[01][0-9]:[0-5][0-9]' OR push_time GLOB '2[0-3]:[0-5][0-9]'),  -- 00:00–23:59 only (matches API.md 15's regex; '25:00' is rejected by the DB too)
  push_enabled       INTEGER NOT NULL DEFAULT 1  CHECK (push_enabled IN (0,1)),
  daily_new_count    INTEGER NOT NULL DEFAULT 10 CHECK (daily_new_count BETWEEN 0 AND 50),
  daily_screen_count INTEGER NOT NULL DEFAULT 15 CHECK (daily_screen_count BETWEEN 0 AND 50),
  max_reviews        INTEGER NOT NULL DEFAULT 60 CHECK (max_reviews BETWEEN 0 AND 300),
  stages_json        TEXT    NOT NULL DEFAULT '["cet4","cet6"]',  -- 目标阶段: non-empty subset of zk/gk/cet4/cet6 (set by onboarding)
  current_stage      INTEGER NOT NULL DEFAULT 3  CHECK (current_stage BETWEEN 1 AND 4),  -- 主攻阶段 1=zk 2=gk 3=cet4 4=cet6; on the wire it is the Stage string ('cet4'), mapped by the server (API.md §9.1)
  show_images        INTEGER NOT NULL DEFAULT 1  CHECK (show_images IN (0,1)),
  zh_examples        TEXT    NOT NULL DEFAULT 'tap' CHECK (zh_examples IN ('tap','always')),
  auto_pronounce     INTEGER NOT NULL DEFAULT 1  CHECK (auto_pronounce IN (0,1)),
  accent             TEXT    NOT NULL DEFAULT 'en-US' CHECK (accent IN ('en-US','en-GB')),
  email_enabled      INTEGER NOT NULL DEFAULT 0  CHECK (email_enabled IN (0,1)),
  webhook_enabled    INTEGER NOT NULL DEFAULT 0  CHECK (webhook_enabled IN (0,1)),
  webhook_url        TEXT,                                        -- https only; passes the SSRF host check
  webhook_format     TEXT    NOT NULL DEFAULT 'generic' CHECK (webhook_format IN ('generic','wecom','feishu','serverchan','bark')),
  next_push_at       TEXT,                                        -- UTC instant of the next push (clock.compute_next_push); set at REGISTRATION from the defaults
                                                                  -- (same transaction as this row, API.md 2) and recomputed by onboarding / PUT /api/settings / publish — never NULL for an active user
  updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_user_settings_next_push ON user_settings(next_push_at);

-- ---------------------------------------------------------------------------
-- 3. Vocabulary (shared by all users)
-- ---------------------------------------------------------------------------
CREATE TABLE words (
  id                  INTEGER PRIMARY KEY,
  lemma               TEXT NOT NULL,                    -- normalised key: NFKC, lower-case, single spaces, ASCII ' - .
  display             TEXT NOT NULL,                    -- display form, keeps casing ('China', 'NASA', 'a.m.', 'ice cream')
  kind                TEXT NOT NULL DEFAULT 'word' CHECK (kind IN ('word','phrase','abbreviation','proper_noun')),
  phonetic            TEXT,                             -- 'ə'bændən' (seed: ә→ə, :→ː normalised)
  translation         TEXT,                             -- zh lines joined by '\n' (seed translation[])
  definition          TEXT,                             -- en lines joined by '\n' (seed definition[])
  pos                 TEXT,                             -- ECDICT pos distribution 'n:4/v:96'
  collins             INTEGER,                          -- 0–5
  oxford              INTEGER,                          -- 0/1 (Oxford 3000)
  exam_tags           TEXT,                             -- 'ky toefl ielts gre' (space-joined seed exam_tags[])
  bnc                 INTEGER,                          -- BNC rank; 0/NULL = unknown
  frq                 INTEGER,                          -- COCA-ish rank; 0/NULL = unknown (sorted last)
  exchange_json       TEXT,                             -- seed exchange{} as JSON object ({"p":"went","d":"gone",…})
  stage_zk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_zk   IN (0,1)),  -- 初中 (中考表 ∪ ECDICT zk)
  stage_gk            INTEGER NOT NULL DEFAULT 0 CHECK (stage_gk   IN (0,1)),  -- 高中 (Highschool ∪ gk)
  stage_cet4          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet4 IN (0,1)),  -- 四级
  stage_cet6          INTEGER NOT NULL DEFAULT 0 CHECK (stage_cet6 IN (0,1)),  -- 六级 (cumulative: includes most CET-4)
  stage_min           INTEGER CHECK (stage_min BETWEEN 1 AND 4),  -- lowest stage 1=zk 2=gk 3=cet4 4=cet6; NULL = outside the 4 lists.
                                                                  -- 仅本阶段新增 filter == stage_min = <stage index> (cet6: 3,694 words)
  cet6_star           INTEGER NOT NULL DEFAULT 0 CHECK (cet6_star IN (0,1)),   -- starred CET-6 word: 1,714 seed words carry the star (of the 1,721-word starred list; 7 entries match no seed lemma)
  sources             TEXT,                             -- provenance, e.g. 'cet4 cet46 ecdict gk zk'
  ecdict_id           INTEGER,                          -- stardict.id
  source              TEXT NOT NULL CHECK (source IN ('seed','ecdict','claude','user')),  -- where dictionary fields came from
  is_public           INTEGER NOT NULL DEFAULT 1 CHECK (is_public IN (0,1)),   -- 0 = unvalidated/unsafe user word. VISIBILITY RULE (API.md §1, DESIGN §5.2), applied by every
                                                                               -- word-reading route: is_public=1 OR created_by_user_id=:me OR EXISTS(user_words uw WHERE uw.user_id=:me AND uw.word_id=words.id); admins see all
  is_valid_english    INTEGER CHECK (is_valid_english IN (0,1)),  -- NULL = not yet checked; set by lookup_word / seed import
  safe_for_sharing    INTEGER CHECK (safe_for_sharing IN (0,1)),  -- NULL = not yet checked; Claude verdict (no personal names etc.)
  difficulty          INTEGER CHECK (difficulty BETWEEN 1 AND 5), -- 1 初中 … 4 六级, 5 beyond
  merged_into_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,  -- consolidation merged this row into another
  created_by_user_id  INTEGER REFERENCES users(id) ON DELETE SET NULL,
  active_content_id   INTEGER,                          -- logical FK → word_contents.id (no constraint: avoids a cycle)
  active_image_id     INTEGER,                          -- logical FK → word_images.id (NULL ⇒ template card is served)
  content_state       TEXT NOT NULL DEFAULT 'none' CHECK (content_state IN ('none','queued','ready','failed')),
  image_state         TEXT NOT NULL DEFAULT 'none' CHECK (image_state  IN ('none','queued','ready','failed')),
  created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX ux_words_lemma      ON words(lemma);
CREATE INDEX        ix_words_frq        ON words(frq);
CREATE INDEX        ix_words_stage_min  ON words(stage_min, frq);
CREATE INDEX        ix_words_content    ON words(content_state);
CREATE INDEX        ix_words_created_by ON words(created_by_user_id) WHERE created_by_user_id IS NOT NULL;
CREATE INDEX        ix_words_public     ON words(is_public, is_valid_english);

-- inflection → lemma index, built from exchange codes p d i 3 s r t at seed import (never 0/1/f/b/z),
-- extended by lookup_word/consolidation ('alt'). Rules enforced by the importer:
--   * empty-string forms are skipped (11 in the seed)
--   * a form that is itself a words.lemma is NEVER inserted (388 in the seed: data, better, running, clothes …)
--   * ambiguous forms get one row per lemma — PK (form, word_id). FACTS §4b counts 47 ambiguous forms in the raw
--     exchange data; after dropping empty strings and headword-forms 28 remain in the seed (bases→base/basis, axes→ax/axe/axis …);
--     acceptance pins only `bases` → 2 lemmas
CREATE TABLE word_forms (
  form     TEXT NOT NULL,                               -- normalised like words.lemma
  word_id  INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  kind     TEXT NOT NULL CHECK (kind IN ('p','d','i','3','s','r','t','alt')),  -- ECDICT codes; 'alt' = Claude/suffix rule
  PRIMARY KEY (form, word_id)
) WITHOUT ROWID;
CREATE INDEX ix_word_forms_word ON word_forms(word_id);

-- ---------------------------------------------------------------------------
-- 4. Generated learning content and images (shared, versioned)
-- ---------------------------------------------------------------------------
CREATE TABLE word_contents (
  id             INTEGER PRIMARY KEY,
  word_id        INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  version        INTEGER NOT NULL,                      -- 1, 2, … per word
  prompt_version TEXT    NOT NULL,                      -- 'content-v1'
  model          TEXT    NOT NULL,                      -- canonical model from modelUsage, e.g. 'claude-sonnet-5-5'
  content_json   TEXT    NOT NULL,                      -- validated Content object (API.md → Content)
  status         TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','rejected')),
  cost_usd       REAL,                                  -- share of the call cost (total_cost_usd / words in the call)
  ai_call_id     INTEGER,                               -- logical FK → ai_calls.id
  created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX ux_word_contents_version ON word_contents(word_id, version);
CREATE UNIQUE INDEX ux_word_contents_active  ON word_contents(word_id) WHERE status = 'active';

CREATE TABLE word_images (
  id               INTEGER PRIMARY KEY,
  word_id          INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  provider         TEXT NOT NULL CHECK (provider IN ('wikimedia','openverse','pixabay','pexels','claude_svg')),
  provider_ref     TEXT,                                -- Commons pageid / Openverse id / provider photo id
  query            TEXT,                                -- image keyword that produced it
  source_url       TEXT,                                -- URL that was downloaded (NULL for generated)
  landing_url      TEXT,                                -- attribution link (descriptionurl / foreign_landing_url)
  title            TEXT,
  creator          TEXT,
  creator_url      TEXT,
  license          TEXT,                                -- 'CC BY 2.0' | 'CC0' | 'Public domain' | 'Pixabay License' | 'generated'
  license_url      TEXT,
  attribution_text TEXT,                                -- ready-to-display line
  alt_zh           TEXT,                                -- Chinese alt text (content.image_alt_zh or Claude svg alt_zh)
  width            INTEGER,
  height           INTEGER,
  file_path        TEXT NOT NULL,                       -- relative to DATA_DIR/images, e.g. 'ab/ab12….jpg' or '.svg'
  file_bytes       INTEGER NOT NULL,
  sha256           TEXT NOT NULL,                       -- of the stored (re-encoded) file; same sha may serve several words
  mime             TEXT NOT NULL CHECK (mime IN ('image/jpeg','image/svg+xml')),
  score            REAL,                                -- selection score (debugging)
  status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','rejected')),
  created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX        ix_word_images_word   ON word_images(word_id, status);
CREATE INDEX        ix_word_images_sha    ON word_images(sha256);
CREATE UNIQUE INDEX ux_word_images_active ON word_images(word_id) WHERE status = 'active';

-- ---------------------------------------------------------------------------
-- 5. Personal word bank (生词库) and learning history
--    生词库 == user_words.state IN ('new','learning'); other states are kept for history / re-add detection.
-- ---------------------------------------------------------------------------
CREATE TABLE user_words (
  id                INTEGER PRIMARY KEY,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  word_id           INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  state             TEXT NOT NULL CHECK (state IN ('new','learning','mastered','known','removed')),
  origin            TEXT NOT NULL CHECK (origin IN ('browse','custom','screen','push','import')),  -- how it first entered
  priority          INTEGER NOT NULL DEFAULT 50,        -- new-word ordering: custom 100 · re-add 80 · default 50
  note              TEXT,                               -- user note ≤ 500 chars (context where the word was met)
  input_text        TEXT,                               -- raw text the user typed (custom adds)
  needs_attention   INTEGER NOT NULL DEFAULT 0 CHECK (needs_attention IN (0,1)),  -- Claude: not English / unresolved. Cleared by PATCH /api/bank/{id} {attention:'keep'}
                                                        -- (API.md 36) or by lookup_word resolving; {attention:'retry'} keeps it 1 with attention_msg NULL until the job resolves
  attention_msg     TEXT,                               -- zh message shown in the bank; NULL while a retried lookup is pending (badge 重新校验中)
                                                        -- UI states (FRONTEND §4 AttentionBadge): needs_attention=1 & msg → ⚠ msg + 修改/保留/删除(/重试);
                                                        -- needs_attention=1 & NULL msg → 重新校验中; 0 & words.is_valid_english NULL → 待校验; 0 & is_valid_english=0 → 仅收藏 (never pushed)
  suggested_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,  -- 'did you mean' target (typo correction, never auto-applied)
  -- WD-SRS state (DESIGN.md §7)
  ease              REAL    NOT NULL DEFAULT 2.5,
  interval_days     INTEGER NOT NULL DEFAULT 0,         -- 0 before the first graduation
  step              INTEGER NOT NULL DEFAULT 0 CHECK (step IN (0,1)),  -- 1 = waiting on the 10-minute learning/relearning step
  repetitions       INTEGER NOT NULL DEFAULT 0,
  lapses            INTEGER NOT NULL DEFAULT 0,
  consecutive_good  INTEGER NOT NULL DEFAULT 0,
  due_at            TEXT,                               -- UTC; NULL while state='new' or out of the bank
  last_graded_at    TEXT,
  times_pushed      INTEGER NOT NULL DEFAULT 0,
  times_added       INTEGER NOT NULL DEFAULT 1,         -- incremented on every re-add (顽固词 when ≥ 3)
  added_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),  -- last time it entered the bank
  first_added_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  mastered_at       TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX ux_user_words           ON user_words(user_id, word_id);
CREATE INDEX        ix_user_words_due       ON user_words(user_id, state, due_at);
CREATE INDEX        ix_user_words_new       ON user_words(user_id, state, priority, added_at);
CREATE INDEX        ix_user_words_word      ON user_words(word_id);
CREATE INDEX        ix_user_words_attention ON user_words(user_id) WHERE needs_attention = 1;

-- append-only log of every grading / marking action; powers history, stats and idempotent grading.
-- API action → log action mapping (DESIGN §4): grades again/hard/good/master/skip as is; mark:unfamiliar → 'unfamiliar'
-- ('readd' when the row comes from mastered/known/removed); mark:known → 'known'; mark:mastered → 'master'; mark:remove → 'remove';
-- mark:reset → 'reset'; mark:restore → 'restore'; bulk/single custom add → 'add_custom'; POST /api/bank/import → 'import';
-- accept-suggestion → 'remove' + 'add_custom'; lookup/consolidation repoint/merge → 'consolidate'; note edit → 'note';
-- PATCH /api/bank/{id} {attention:'keep'|'retry'} → 'attention' (result_json = {"decision":"keep"|"retry"}).
-- context: 'today'/'extra' = study cards and in-batch 推荐词 (endpoint 45) · 'screen_page'/'onboarding' = 筛词 verdicts (32) ·
-- 'browse'/'detail'/'bank' = mark from those pages · 'api' = DEFAULT when the client omits `context` (and for /bank/add, add-word, import) ·
-- 'consolidate' = lookup_word / consolidate_bank / suggestion accept-undo writes. context → user_words.origin mapping: DESIGN §4.
CREATE TABLE review_logs (
  id              INTEGER PRIMARY KEY,
  user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  word_id         INTEGER NOT NULL,
  user_word_id    INTEGER,
  batch_id        INTEGER,
  push_item_id    INTEGER,
  client_event_id TEXT,                                 -- UUID from the client; duplicate → original outcome is returned
  action          TEXT NOT NULL CHECK (action IN ('again','hard','good','master','skip','known','unfamiliar',
                                                   'remove','readd','reset','restore','add_custom','import','consolidate','note','attention')),
  context         TEXT NOT NULL CHECK (context IN ('today','extra','screen_page','browse','bank','detail','api','consolidate','onboarding')),
  prev_state      TEXT, new_state TEXT,
  prev_interval   INTEGER, new_interval INTEGER,
  prev_ease       REAL,    new_ease REAL,
  prev_srs_json   TEXT,                                 -- full prior snapshot {state, ease, interval_days, step, repetitions, lapses, consecutive_good,
                                                        --   due_at, last_graded_at, mastered_at, priority, times_added}; written on EVERY 'master' and 'known'
                                                        --   transition; consumed verbatim by mark:restore (DESIGN §4) within its 15-minute window.
                                                        --   mark:restore also undoes an 'unfamiliar' log row with prev_state IS NULL (a ∅ → new row that was never
                                                        --   graded): that row is deleted again (the 筛词/词库 撤销 of a 不熟悉, DESIGN §4)
  elapsed_ms      INTEGER,
  result_json     TEXT,                                 -- stored GradeResponse/ScreenResponse for idempotent replays
  local_date      TEXT NOT NULL,                        -- user's local date of the action
  created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX ux_review_logs_event ON review_logs(user_id, client_event_id) WHERE client_event_id IS NOT NULL;
CREATE INDEX        ix_review_logs_user_date ON review_logs(user_id, local_date);
CREATE INDEX        ix_review_logs_user_word ON review_logs(user_id, word_id, created_at);

-- per-day aggregates (heatmap, streak, history list); upserted on every action by the ONE function
-- wd/services/stats_core.on_action (Phase-0 module, delta table in DESIGN §7.1) — WP3 (marks, verdicts, adds, import) and
-- WP4 (grades) both call it; nobody else writes this table
CREATE TABLE daily_stats (
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  local_date TEXT    NOT NULL,
  graded     INTEGER NOT NULL DEFAULT 0,                -- again+hard+good+master on review/new/extra cards, intermediate (10-minute step) grades included (streak basis)
  again      INTEGER NOT NULL DEFAULT 0,
  hard       INTEGER NOT NULL DEFAULT 0,
  good       INTEGER NOT NULL DEFAULT 0,
  mastered   INTEGER NOT NULL DEFAULT 0,                -- decremented again by mark:restore (and `graded` too when the undone 'master' was a study-card grade)
  known      INTEGER NOT NULL DEFAULT 0,                -- 认识 verdicts / marks (new_state 'known'); decremented by mark:restore of such a 'known' log
  screened   INTEGER NOT NULL DEFAULT 0,                -- screening verdicts known + unfamiliar (contexts screen_page/onboarding, or a kind='screen' push item); decremented by mark:restore of one
  added      INTEGER NOT NULL DEFAULT 0,                -- words entering the bank that day (unfamiliar from ∅, readd, add_custom, import); decremented by mark:restore of a ∅ → new 'unfamiliar'
  study_ms   INTEGER NOT NULL DEFAULT 0,                -- sum(min(elapsed_ms, 60000))
  PRIMARY KEY (user_id, local_date)
) WITHOUT ROWID;

-- ---------------------------------------------------------------------------
-- 6. Daily push
-- ---------------------------------------------------------------------------
CREATE TABLE push_batches (
  id               INTEGER PRIMARY KEY,
  user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  local_date       TEXT NOT NULL,                       -- 'YYYY-MM-DD' in `timezone`
  timezone         TEXT NOT NULL,                       -- snapshot of the user's tz when built
  status           TEXT NOT NULL DEFAULT 'building' CHECK (status IN ('building','ready','published')),
  trigger          TEXT NOT NULL CHECK (trigger IN ('scheduled','manual','catchup','admin')),
  review_count     INTEGER NOT NULL DEFAULT 0,
  new_count        INTEGER NOT NULL DEFAULT 0,
  screen_count     INTEGER NOT NULL DEFAULT 0,
  extra_count      INTEGER NOT NULL DEFAULT 0,
  deferred_reviews INTEGER NOT NULL DEFAULT 0,          -- due reviews beyond max_reviews (shown as 顺延)
  extra_rounds     INTEGER NOT NULL DEFAULT 0,          -- 再来一组 presses (max 3)
  settings_json    TEXT NOT NULL DEFAULT '{}',          -- snapshot of the settings used
  built_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  ready_at         TEXT,                                -- all content present (or 2 h timeout)
  published_at     TEXT,                                -- push_time reached (or catch-up)
  completed_at     TEXT,                                -- user finished every non-screen item
  email_status     TEXT NOT NULL DEFAULT 'none' CHECK (email_status   IN ('none','queued','sent','failed','skipped')),
  webhook_status   TEXT NOT NULL DEFAULT 'none' CHECK (webhook_status IN ('none','queued','sent','failed','skipped')),
  delivery_error   TEXT
);
CREATE UNIQUE INDEX ux_push_batches_user_date ON push_batches(user_id, local_date);   -- THE idempotency guarantee
CREATE INDEX        ix_push_batches_status    ON push_batches(status);

-- A word appears at most once per KIND in a batch: a 推荐词 (kind='screen') graded `unfamiliar` inside the batch keeps its
-- screen row (result='unfamiliar') and gets a SECOND row kind='new' (the study card) appended — hence UNIQUE(batch_id, word_id, kind).
-- At most one gradable study row (review/new/extra) per word per batch is enforced in services/batches.append_to_today
-- (it skips words already present as review/new/extra; a word present only as 'screen' gets its study row).
-- Stale rows (DESIGN §6.3): an UNGRADED review/new/extra row whose user_words.state is no longer new/learning, an ungraded
-- screen row whose word now has a user_words row, or any row whose word has merged_into_word_id set, is hidden from
-- TodayResponse.items/counts and grading it returns 409 invalid_transition; consolidation repoints rewrite word_id for open batches.
CREATE TABLE push_items (
  id           INTEGER PRIMARY KEY,
  batch_id     INTEGER NOT NULL REFERENCES push_batches(id) ON DELETE CASCADE,
  word_id      INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  user_word_id INTEGER REFERENCES user_words(id) ON DELETE SET NULL,  -- NULL for kind='screen' until acted on
  kind         TEXT NOT NULL CHECK (kind IN ('review','new','screen','extra')),
  position     INTEGER NOT NULL,                        -- study order within the batch
  result       TEXT CHECK (result IN ('again','hard','good','master','known','unfamiliar')),  -- written ONLY by a FINAL grade (DESIGN §7): `master`, a screen verdict known/unfamiliar,
                                                        -- or an again/hard/good that leaves user_words.step = 0 (graduated / review). An INTERMEDIATE grade (the card
                                                        -- enters or repeats the 10-minute learning step, GradeResponse.requeue_at set) writes review_logs + daily_stats
                                                        -- only and leaves result/graded_at NULL, so the item stays ungraded (counts.done, goal_met, completed_at and
                                                        -- item_already_graded all key off `result IS NOT NULL`). skip is never final. Cleared again by mark:restore.
                                                        -- 'again' is therefore never stored here (it always sets step = 1); it survives in review_logs.
  graded_at    TEXT,
  skip_count   INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX ux_push_items_batch_word_kind ON push_items(batch_id, word_id, kind);
CREATE INDEX        ix_push_items_batch      ON push_items(batch_id, position);

-- ---------------------------------------------------------------------------
-- 7. Consolidation (整理) runs and the 整理建议 inbox
-- ---------------------------------------------------------------------------
CREATE TABLE consolidation_runs (
  id             INTEGER PRIMARY KEY,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  trigger        TEXT NOT NULL CHECK (trigger IN ('nightly','manual','admin')),
  status         TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','done','failed','skipped')),
  words_examined INTEGER NOT NULL DEFAULT 0,
  auto_applied   INTEGER NOT NULL DEFAULT 0,
  suggestions    INTEGER NOT NULL DEFAULT 0,
  ai_call_id     INTEGER,                               -- logical FK → ai_calls.id
  summary_json   TEXT NOT NULL DEFAULT '{}',
  started_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  finished_at    TEXT
);
CREATE INDEX ix_consolidation_runs_user ON consolidation_runs(user_id, started_at);

CREATE TABLE bank_suggestions (
  id             INTEGER PRIMARY KEY,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  run_id         INTEGER REFERENCES consolidation_runs(id) ON DELETE SET NULL,
  type           TEXT NOT NULL CHECK (type IN ('fix_spelling','lemmatize','merge_duplicate','invalid_word','split_phrase','confusable_group','fill_data','difficulty')),
  user_word_id   INTEGER REFERENCES user_words(id) ON DELETE CASCADE,   -- the bank row concerned (NULL for confusable_group)
  target_word_id INTEGER REFERENCES words(id) ON DELETE SET NULL,       -- proposed target (lemma / correct spelling / duplicate)
  payload_json   TEXT NOT NULL,                         -- {"from":"abandonned","to":"abandon","note_zh":"看起来是拼写错误","confidence":0.93,"group":[…]}
  status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','accepted','rejected','expired','auto','undone')),
  undo_json      TEXT,                                  -- for status='auto': prior state needed by POST /suggestions/{id}/undo
  expires_at     TEXT,                                  -- open: created + 30 d ; auto: created + 7 d (undo window)
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  resolved_at    TEXT
);
CREATE INDEX ix_bank_suggestions_user ON bank_suggestions(user_id, status, created_at);

-- ---------------------------------------------------------------------------
-- 8. Jobs, AI ledger, provider quotas, reports
-- ---------------------------------------------------------------------------
-- Durable queue. Dedupe keys: 'content:<word_id>' | 'lookup:<word_id>' | 'consolidate:<user_id>:<YYYY-MM-DD>' |
--   'svg:<word_id>' | 'image:<word_id>' | 'email:<batch_id>' | 'email:test:<user_id>' | 'webhook:<batch_id>' | 'prewarm:<plan_id>'
--   Variants with their own live key (they must not fold into the base job): 'content:<word_id>:r<n>' (forced regenerate, payload
--   {"force":true}, n = 1 + the number of earlier ':r%' keys) · 'image:<word_id>:r<n>' (a fetch requested while 'image:<word_id>' is
--   already running — the follow-up runs behind it; a still-queued follow-up is reused) · 'svg:<word_id>:req' (an explicitly requested
--   Claude SVG — admin / `wd fetch-image --provider claude_svg` — with payload flag "requested": it draws even over an active photo,
--   whereas the fallback 'svg:<word_id>' job is skipped once a photo landed)
-- Priorities (lower runs first): 10 user waiting · 20 bank word / today's batch · 30 lookahead (= the 03:30 maintenance prefetch of
--   tomorrow's batches, DESIGN §6.4 `maintenance.prefetch`) · 50 nightly consolidation · 90 prewarm
-- Payloads (CLAUDE_INTEGRATION §6.1): generate_content {"word_id":123,"group_size"?:5,"force"?:true,"plan_id"?:"<uuid>"} ·
--   lookup_word {"word_id":456} · consolidate_bank {"user_id":7,"trigger":"nightly"|"manual"|"admin"} · generate_svg {"word_id":123,"requested"?:true} ·
--   fetch_image {"word_id":1,"exclude"?:[…],"provider"?:"…","query"?:"…"} · send_email/send_webhook {"batch_id":9} for a published batch ·
--   send_email {"user_id":7,"test":true} for POST /api/settings/email/test (no batch; dedupe 'email:test:<user_id>'; subject 【word-Dance】测试邮件,
--   body = the user's next_push_at rendered in their timezone + the public URL, API.md 18) ·
--   prewarm_plan {"plan_id":"<uuid>","stage":"cet4","limit":500,"max_budget_usd":2.0}
-- enqueue() upserts on the LIVE key; a 'done' job is never re-run (callers use {"force":true} with a fresh key suffix ':r<n>').
-- SQLite accepts the UPSERT against the partial unique index ONLY when the conflict target repeats the index predicate
-- verbatim (verified on 3.45.1; plain ON CONFLICT(dedupe_key) fails with "does not match any PRIMARY KEY or UNIQUE constraint"):
--   INSERT INTO jobs(type, payload_json, dedupe_key, priority, run_after, max_attempts) VALUES (?,?,?,?,?,?)
--   ON CONFLICT(dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('queued','running')
--   DO UPDATE SET priority = min(priority, excluded.priority), run_after = min(run_after, excluded.run_after),
--                 updated_at = excluded.updated_at
--   RETURNING id;                        -- queue.enqueue returns the (possibly pre-existing) live job id
CREATE TABLE jobs (
  id           INTEGER PRIMARY KEY,
  type         TEXT NOT NULL CHECK (type IN ('generate_content','lookup_word','consolidate_bank','generate_svg','fetch_image','send_email','send_webhook','prewarm_plan')),
  payload_json TEXT NOT NULL DEFAULT '{}',              -- see the payload catalogue above
  dedupe_key   TEXT,
  priority     INTEGER NOT NULL DEFAULT 50,
  status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','dead','cancelled')),
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  run_after    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),   -- backoff / debounce / budget deferral
  locked_at    TEXT,
  locked_by    TEXT,                                    -- '<worker>:<boot_id>' e.g. 'claude-1:7f3a…'
  last_error   TEXT,
  result_json  TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  finished_at  TEXT
);
CREATE UNIQUE INDEX ux_jobs_dedupe_live ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('queued','running');
CREATE INDEX        ix_jobs_claim       ON jobs(status, type, run_after, priority, id);
CREATE INDEX        ix_jobs_updated     ON jobs(status, updated_at);

-- one row per `claude` spawn; INSERTED BEFORE the subprocess starts (status 'running') and updated afterwards,
-- so a killed or crashed call is never invisible spend
CREATE TABLE ai_calls (
  id                 INTEGER PRIMARY KEY,
  kind               TEXT NOT NULL CHECK (kind IN ('content','lookup','consolidate','svg','probe')),
  status             TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','error','timeout','invalid_output','budget','auth','overloaded','spawn_error')),
  model_requested    TEXT NOT NULL,                     -- 'sonnet'
  model_used         TEXT,                              -- first key of result.modelUsage, e.g. 'claude-sonnet-5-5'
  flag_tier          INTEGER NOT NULL DEFAULT 0,        -- 0 verified flags only · 1 hardened flags (CLAUDE_INTEGRATION.md §2)
  word_count         INTEGER NOT NULL DEFAULT 0,
  job_ids_json       TEXT NOT NULL DEFAULT '[]',
  max_budget_usd     REAL NOT NULL,
  reserved_usd       REAL NOT NULL DEFAULT 0,           -- estimate reserved against the daily cap before the call
  cost_usd           REAL NOT NULL DEFAULT 0,           -- result.total_cost_usd (recorded even on failure when parseable)
  duration_ms        INTEGER,
  input_tokens       INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_create_tokens INTEGER,
  session_id         TEXT,
  exit_code          INTEGER,
  error              TEXT,                              -- truncated stderr / classification detail (≤ 1000 chars)
  stdout_path        TEXT,                              -- claude-logs/YYYY-MM-DD/<id>.json (kept 14 days)
  started_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  finished_at        TEXT
);
CREATE INDEX ix_ai_calls_started ON ai_calls(started_at);
CREATE INDEX ix_ai_calls_status  ON ai_calls(status, started_at);

-- image provider quota counters per window, persisted across restarts
CREATE TABLE provider_usage (
  provider     TEXT NOT NULL,                           -- 'wikimedia' | 'openverse' | 'pixabay' | 'pexels'
  window       TEXT NOT NULL CHECK (window IN ('minute','day')),
  window_start TEXT NOT NULL,                           -- 'YYYY-MM-DDTHH:MM' (minute) or 'YYYY-MM-DD' (day), UTC
  count        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (provider, window, window_start)
) WITHOUT ROWID;

CREATE TABLE provider_state (
  provider           TEXT PRIMARY KEY,
  cooldown_until     TEXT,                              -- set on HTTP 429/5xx; provider skipped until then
  last_ok_at         TEXT,
  last_error         TEXT,
  consecutive_errors INTEGER NOT NULL DEFAULT 0,
  updated_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
) WITHOUT ROWID;

-- user reports: bad examples / inappropriate image / wrong dictionary data
CREATE TABLE content_reports (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  target      TEXT NOT NULL CHECK (target IN ('content','image','dictionary')),
  reason      TEXT NOT NULL CHECK (reason IN ('wrong_meaning','unnatural_example','bad_translation','irrelevant_image','inappropriate_image','other')),
  note        TEXT,                                     -- ≤ 300 chars
  image_id    INTEGER,                                  -- the image that was active when reported (logical FK)
  content_id  INTEGER,                                  -- the content version that was active (logical FK)
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
  resolution  TEXT,                                     -- 'regenerated' | 'image_replaced' | 'dismissed' | free text
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  resolved_at TEXT
);
CREATE INDEX ix_content_reports_status ON content_reports(status, created_at);

-- ---------------------------------------------------------------------------
-- 9. Convenience view (per-user join: the user's own user_words row grants visibility, so no is_public filter is needed here —
--    a private provisional word shared by two holders is listed for both; a third user never has a row and never sees it)
-- ---------------------------------------------------------------------------
CREATE VIEW v_bank AS
SELECT uw.*, w.lemma, w.display, w.kind, w.phonetic, w.translation, w.stage_min, w.content_state, w.image_state,
       w.is_public, w.is_valid_english
FROM user_words uw JOIN words w ON w.id = uw.word_id
WHERE uw.state IN ('new','learning');

-- ---------------------------------------------------------------------------
-- 10. Bookkeeping for this migration
--     The schema_migrations row (1, 'init') is inserted by db.run_migrations() in the same BEGIN IMMEDIATE transaction that
--     executes this file (rule at the top of §1). Migration files never self-register — a self-insert here would collide
--     with the runner's insert on every fresh install.
-- ---------------------------------------------------------------------------
INSERT INTO kv(key, value) VALUES ('schema.created_at', strftime('%Y-%m-%dT%H:%M:%SZ','now'));
