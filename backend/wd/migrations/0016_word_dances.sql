-- 0016_word_dances.sql — 单词之舞 P2 (docs/WORD_DANCE_DESIGN.md §4.3 / §6, docs/releases/2026-11-word-dance-p2.md): the new job type
-- `generate_dance` and ai_calls kind `dance`, the `word_dances` table that stores Claude's per-word DanceSpec (chunks confirmed or
-- corrected, the one semantic primitive), and the two words columns that point at the active row.
--
-- SQLite cannot ALTER a CHECK list, so `jobs` and `ai_calls` are REBUILT (the 0011 / 0013 recipe: create _new → copy every row →
-- drop → rename → re-create the indexes). Both tables are small (a few thousand rows) and nothing references them by foreign key
-- (ai_calls.job_ids_json is JSON, kv / system_events mention ids as data); v_bank joins user_words / words only. This is therefore a
-- STOP-FIRST migration like 0011 / 0013 (never `deploy/install.sh --no-restart`; on the Mac `launchctl kickstart -k` applies it at
-- the next start, before the workers run). The runner wraps the file in BEGIN IMMEDIATE with foreign_keys=OFF and records
-- schema_migrations(16, 'word_dances') itself (SCHEMA.sql §1) — nothing else belongs here. docs/SCHEMA.sql stays the 0001
-- baseline byte for byte (test_db.py); the registry tests read the jobs.type CHECK list from the newest file that creates `jobs`.
--
-- Rollback = the pre-migrate snapshot (`wd restore backups/pre-migrate-15-to-16.db.gz`) together with `git checkout`: the old code
-- would still work on the new tables (it never writes the new type / kind), but the release note keeps code and database together.

-- 1. jobs: + 'generate_dance' (20 words per claim, CLAUDE_INTEGRATION §6.1 / §6.2)
CREATE TABLE jobs_new (
  id           INTEGER PRIMARY KEY,
  type         TEXT NOT NULL CHECK (type IN ('generate_content','lookup_word','consolidate_bank','generate_svg','fetch_image','send_email','send_webhook','prewarm_plan','generate_dance')),
  payload_json TEXT NOT NULL DEFAULT '{}',
  dedupe_key   TEXT,
  priority     INTEGER NOT NULL DEFAULT 50,
  status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','done','dead','cancelled')),
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3,
  run_after    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  locked_at    TEXT,
  locked_by    TEXT,
  last_error   TEXT,
  result_json  TEXT,
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  finished_at  TEXT
);
INSERT INTO jobs_new(id, type, payload_json, dedupe_key, priority, status, attempts, max_attempts, run_after, locked_at, locked_by, last_error, result_json, created_at, updated_at, finished_at)
  SELECT id, type, payload_json, dedupe_key, priority, status, attempts, max_attempts, run_after, locked_at, locked_by, last_error, result_json, created_at, updated_at, finished_at FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE UNIQUE INDEX ux_jobs_dedupe_live ON jobs(dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('queued','running');
CREATE INDEX        ix_jobs_claim       ON jobs(status, type, run_after, priority, id);
CREATE INDEX        ix_jobs_updated     ON jobs(status, updated_at);

-- 2. ai_calls: + kind 'dance' (the 0010 provider column becomes a regular column of the rebuilt table)
CREATE TABLE ai_calls_new (
  id                 INTEGER PRIMARY KEY,
  kind               TEXT NOT NULL CHECK (kind IN ('content','lookup','consolidate','svg','probe','dance')),
  status             TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','success','error','timeout','invalid_output','budget','auth','overloaded','spawn_error')),
  model_requested    TEXT NOT NULL,
  model_used         TEXT,
  flag_tier          INTEGER NOT NULL DEFAULT 0,
  word_count         INTEGER NOT NULL DEFAULT 0,
  job_ids_json       TEXT NOT NULL DEFAULT '[]',
  max_budget_usd     REAL NOT NULL,
  reserved_usd       REAL NOT NULL DEFAULT 0,
  cost_usd           REAL NOT NULL DEFAULT 0,
  duration_ms        INTEGER,
  input_tokens       INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_create_tokens INTEGER,
  session_id         TEXT,
  exit_code          INTEGER,
  error              TEXT,
  stdout_path        TEXT,
  started_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  finished_at        TEXT,
  provider           TEXT NOT NULL DEFAULT 'claude' CHECK (provider IN ('claude','fallback'))
);
INSERT INTO ai_calls_new(id, kind, status, model_requested, model_used, flag_tier, word_count, job_ids_json, max_budget_usd, reserved_usd, cost_usd, duration_ms, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, session_id, exit_code, error, stdout_path, started_at, finished_at, provider)
  SELECT id, kind, status, model_requested, model_used, flag_tier, word_count, job_ids_json, max_budget_usd, reserved_usd, cost_usd, duration_ms, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, session_id, exit_code, error, stdout_path, started_at, finished_at, provider FROM ai_calls;
DROP TABLE ai_calls;
ALTER TABLE ai_calls_new RENAME TO ai_calls;
CREATE INDEX ix_ai_calls_started          ON ai_calls(started_at);
CREATE INDEX ix_ai_calls_status           ON ai_calls(status, started_at);
CREATE INDEX ix_ai_calls_provider_started ON ai_calls(provider, started_at);

-- 3. word_dances: one active DanceSpec per word (the word_images pattern — superseded rows stay for history)
CREATE TABLE word_dances (
  id             INTEGER PRIMARY KEY,
  word_id        INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
  status         TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded')),
  spec_json      TEXT NOT NULL,                              -- API.md §9 DanceSpec with source 'claude' (letters, stress, marks, semantic)
  model          TEXT,                                       -- ai_calls.model_used
  prompt_version TEXT,                                       -- ai.dance.DANCE_PROMPT_VERSION ('dance-v1')
  reason         TEXT,                                       -- the model's short justification (≤ 12 Chinese characters), for the human review of the assignments
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX        ix_word_dances_word   ON word_dances(word_id, status);
CREATE UNIQUE INDEX ux_word_dances_active ON word_dances(word_id) WHERE status = 'active';

-- 4. words: the pointer and the state (none = never asked · queued · ready · failed), the image_state precedent
ALTER TABLE words ADD COLUMN active_dance_id INTEGER;
ALTER TABLE words ADD COLUMN dance_state TEXT NOT NULL DEFAULT 'none' CHECK (dance_state IN ('none','queued','ready','failed'));
