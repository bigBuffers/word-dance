-- 0019_family.sql — guardian + child accounts (docs/AUTH_SIGNUP_DESIGN.md §5.1 「家长 + 孩子」 / §5.2 「切换与边界」; docs/releases/2026-11-auth-signup-1b.md;
-- API.md §3.2, endpoints 94–111): the `family_codes` table (the 8-digit one-time login codes of a child's own device, endpoints 99 / 107,
-- and the claim codes of 「这是孩子的账号」, endpoints 108 / 109), `sessions.guardian_gate_at` (the 家长门 stamp of endpoints 102 / 105,
-- valid 10 minutes) and `users.profile_prompted_at` (the legacy 「补充信息」 prompt was skipped at this time, endpoint 111; re-shown
-- 30 days later). The columns 1-A reserved — `users.account_kind` / `guardian_user_id` / `guardian_consent_at` / `guardian_pin_hash`
-- and `sessions.actor_user_id` (0018) — start being written by this slice; nothing about them changes here.
--
-- Additive only, the 0012 / 0014 / 0015 / 0017 / 0018 precedent: two ADD COLUMNs, one CREATE TABLE, three CREATE INDEXes — no table
-- rebuild, no DROP / RENAME, no CHECK-list change, no data step. No view, trigger or foreign key reads the new columns, so the file is
-- safe under `deploy/install.sh --no-restart` (DEPLOY §10) and a plain `launchctl kickstart -k` on the Mac. SQLite's ADD COLUMN cannot
-- take a `(strftime(...))` default, so both timestamp columns are nullable TEXT (NULL = never skipped / never passed). The runner wraps
-- this file in BEGIN IMMEDIATE and records schema_migrations(19, 'family') itself (SCHEMA.sql §1) — nothing else belongs here.
-- docs/SCHEMA.sql stays the 0001 baseline byte for byte (test_db.py). Rollback = `git checkout` alone: the old code never reads
-- `family_codes`, `guardian_gate_at` or `profile_prompted_at`, and its INSERTs name their columns (security.create_user /
-- create_session), so the table and the columns stay in place unharmed.
--
-- Table notes (the SCHEMA.sql-style comments live here because the baseline file is frozen):
--   family_codes — `kind = 'child_login'`: the code a guardian generated for a child's own device (endpoint 99; `user_id` = the child,
--                  `target` NULL); looked up by `code_hash` alone at endpoint 107 (a miss finds no row, so `attempts` stays 0 and the
--                  per-IP failure window of 107 is the brute-force bound). `kind = 'claim_guardian'`: the code 「这是孩子的账号」 sent
--                  to the guardian's phone (endpoint 108; `user_id` = the account that asked to become a child, `target` = that phone
--                  in E.164); checked like a login code (5 wrong guesses burn it, endpoint 109). A new code voids the older unused
--                  rows of its (kind, user_id[, target]); expired rows and used rows older than a day are GC'd hourly (login_codes rule).
--                  `code_hash = hex HMAC-SHA256(WD_SECRET_KEY, "<code>:<kind>:<target or ''>")` — the code itself is never stored or logged.
ALTER TABLE users ADD COLUMN profile_prompted_at TEXT;                                       -- 1-B: the legacy 「补充信息」 prompt was skipped at this time (endpoint 111; re-shown 30 days later); NULL = never skipped
ALTER TABLE sessions ADD COLUMN guardian_gate_at TEXT;                                       -- 1-B: the guardian passed the 家长门 in this session at this time (endpoint 102 / 105; valid 10 minutes); NULL = not passed
CREATE TABLE family_codes (
  id          INTEGER PRIMARY KEY,
  kind        TEXT NOT NULL CHECK (kind IN ('child_login','claim_guardian')),
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,   -- child_login: the child the code signs in; claim_guardian: the account that asked to become a child
  target      TEXT,                                                       -- claim_guardian: the guardian's phone (E.164); child_login: NULL
  code_hash   TEXT NOT NULL,                                              -- hex HMAC-SHA256(WD_SECRET_KEY, "<code>:<kind>:<target or ''>") — child_login rows are looked up by this hash
  expires_at  TEXT NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0,                                 -- claim_guardian: wrong guesses (5 burn the code); child_login: unused (a miss finds no row)
  used_at     TEXT,
  ip          TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_family_codes_hash ON family_codes(code_hash);
CREATE INDEX ix_family_codes_user ON family_codes(user_id, kind, used_at);
CREATE INDEX ix_family_codes_expires ON family_codes(expires_at);
