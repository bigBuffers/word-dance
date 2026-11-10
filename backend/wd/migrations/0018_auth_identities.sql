-- 0018_auth_identities.sql — sign-in by verification code (docs/AUTH_SIGNUP_DESIGN.md §5.1 / §5.2; docs/releases/2026-11-auth-signup-1a.md;
-- API.md §3.1, endpoints 79–93): the `identities` table (a phone number — later a WeChat / QQ / Apple subject — bound to an account), the
-- `login_codes` table (every verification code of every channel and purpose; `email_codes` is no longer written but stays), eight
-- nullable / defaulted columns on `users` (password_set_at, written by 1-A; `age_band` / `age_declared_at` / `age_declared_ip`,
-- written by 1-A's profile step, endpoint 89; `account_kind` and the guardian columns `guardian_user_id` / `guardian_consent_at` /
-- `guardian_pin_hash`, which wait for slice 1-B) and `sessions.actor_user_id` (1-B: the guardian who issued a child session;
-- NULL = self login).
--
-- Additive only, the 0012 / 0014 / 0015 / 0017 precedent: ADD COLUMN, CREATE TABLE, CREATE INDEX and ONE data step — no table rebuild,
-- no DROP / RENAME, no CHECK-list change. v_bank names its columns explicitly (0011) and no view, trigger or foreign key reads the
-- other columns of users / sessions, so the file is safe under `deploy/install.sh --no-restart` (DEPLOY §10) and a plain
-- `launchctl kickstart -k` on the Mac. SQLite's ADD COLUMN cannot take a `(strftime(...))` default, so the new timestamp columns are
-- nullable TEXT; `password_set_at` is backfilled with `created_at` right here (every pre-0018 account registered with a real
-- password — the single UPDATE changes no row count, so the rehearsal's bookkeeping check holds). The runner wraps this file in
-- BEGIN IMMEDIATE and records schema_migrations(18, 'auth_identities') itself (SCHEMA.sql §1) — nothing else belongs here.
-- docs/SCHEMA.sql stays the 0001 baseline byte for byte (test_db.py). Rollback = `git checkout` alone: the old code's INSERTs name
-- their columns (security.create_user / create_session) and never read the new columns or tables, which stay in place unharmed.
--
-- Table notes (the SCHEMA.sql-style comments live here because the baseline file is frozen):
--   identities   — one live row per (provider, subject): `ux_identities_live` (partial, disputed_at IS NULL — the ux_users_email
--                  precedent) and one live row per (user_id, provider): `ux_identities_user_provider` (one phone per account).
--                  `last_login_at` is written only by code logins through the identity (the stale-phone rule, WD_PHONE_STALE_DAYS);
--                  `disputed_at` is set when the number's new owner answered 「不是我的账号」 — the row stops counting and the admin
--                  may restore it (endpoints 92 / 93). `subject`: phone = E.164 (+8613800138000); apple = sub; wechat_mini / qq = openid.
--   login_codes  — `code_hash = hex HMAC-SHA256(WD_SECRET_KEY, "<code>:<channel>:<target>:<purpose>")`; 10-minute expiry, 5 attempts,
--                  a new code voids the older unused rows of the same (channel, target, purpose); `purpose = 'challenge'` rows hold the
--                  stale-phone challenge token (the HMAC of the token); expired rows and used rows older than a day are GC'd hourly.
--                  `user_id` is required for bind_* / rebind_phone / reauth / challenge and NULL for login / reset_password.
ALTER TABLE users ADD COLUMN password_set_at TEXT;                                           -- NULL = no usable password (code-created account); backfilled below
ALTER TABLE users ADD COLUMN account_kind TEXT NOT NULL DEFAULT 'learner' CHECK (account_kind IN ('learner','guardian'));
ALTER TABLE users ADD COLUMN guardian_user_id INTEGER REFERENCES users(id) ON DELETE RESTRICT;   -- 1-B: child → guardian
ALTER TABLE users ADD COLUMN age_band TEXT CHECK (age_band IN ('u14','14plus','adult'));          -- self-declared, never verified
ALTER TABLE users ADD COLUMN age_declared_at TEXT;
ALTER TABLE users ADD COLUMN age_declared_ip TEXT;
ALTER TABLE users ADD COLUMN guardian_consent_at TEXT;                                       -- 1-B
ALTER TABLE users ADD COLUMN guardian_pin_hash TEXT;                                         -- 1-B
UPDATE users SET password_set_at = created_at;                                               -- every pre-0018 account has a real password
ALTER TABLE sessions ADD COLUMN actor_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;    -- 1-B: the guardian who issued a child session; NULL = self login
CREATE INDEX ix_sessions_actor ON sessions(actor_user_id) WHERE actor_user_id IS NOT NULL;
CREATE TABLE identities (
  id            INTEGER PRIMARY KEY,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider      TEXT NOT NULL CHECK (provider IN ('phone','wechat_mini','qq','apple')),
  subject       TEXT NOT NULL,                                           -- phone: E.164 (+8613800138000); apple: sub; wechat_mini/qq: openid
  verified_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  last_login_at TEXT,                                                    -- updated only by code logins through this identity (stale-phone rule)
  disputed_at   TEXT,                                                    -- set when the number's new owner registered ("不是我的账号"); the row stops counting
  meta_json     TEXT NOT NULL DEFAULT '{}',
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE UNIQUE INDEX ux_identities_live ON identities(provider, subject) WHERE disputed_at IS NULL;
CREATE UNIQUE INDEX ux_identities_user_provider ON identities(user_id, provider) WHERE disputed_at IS NULL;   -- one live phone per account
CREATE INDEX ix_identities_user ON identities(user_id);
CREATE TABLE login_codes (
  id          INTEGER PRIMARY KEY,
  channel     TEXT NOT NULL CHECK (channel IN ('phone','email')),
  target      TEXT NOT NULL,                                             -- E.164 or normalised e-mail
  purpose     TEXT NOT NULL CHECK (purpose IN ('login','reset_password','bind_phone','bind_email','rebind_phone','reauth','challenge')),
  user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,            -- required for bind_*/rebind_phone/reauth/challenge, NULL for login/reset_password
  code_hash   TEXT NOT NULL,                                             -- hex HMAC-SHA256(WD_SECRET_KEY, "<code>:<channel>:<target>:<purpose>")
  expires_at  TEXT NOT NULL,
  attempts    INTEGER NOT NULL DEFAULT 0,
  used_at     TEXT,
  ip          TEXT,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX ix_login_codes_live ON login_codes(channel, target, purpose, used_at);
CREATE INDEX ix_login_codes_user ON login_codes(user_id);
CREATE INDEX ix_login_codes_expires ON login_codes(expires_at);
