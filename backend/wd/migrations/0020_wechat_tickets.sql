-- 0020_wechat_tickets.sql — the WeChat login bridge (docs/AUTH_SIGNUP_DESIGN.md §5.3 「微信、QQ、Apple」; docs/releases/2026-11-auth-third-party.md;
-- API.md §3.3, endpoints 112–116, slice 2-A): the `wechat_tickets` table — one row per 小程序码 / pairing-code ticket a browser opened
-- (endpoint 112), scanned in the mini program (115), confirmed or cancelled there (116) and consumed by the web poll (113) that turns it
-- into a session or a binding. The identities the bridge writes are ordinary `identities` rows (`provider = 'wechat_mini'`, `subject` =
-- the openid — the 0018 CHECK list already allows `wechat_mini` / `qq` / `apple`), so nothing about `identities` changes here; QQ / Apple
-- (118–122) keep their one-time grants in `kv` (`oauth_grant:<exp iso>:<sha256 hex>`) and need no table.
--
-- Additive only, the 0012 / 0014 / 0015 / 0017 / 0018 / 0019 precedent: one CREATE TABLE and two CREATE INDEXes — no ADD COLUMN, no table
-- rebuild, no DROP / RENAME, no CHECK-list change, no data step. No view, trigger or foreign key reads the new table, so the file is safe
-- under `deploy/install.sh --no-restart` (DEPLOY §10) and a plain `launchctl kickstart -k` on the Mac. The runner wraps this file in
-- BEGIN IMMEDIATE and records schema_migrations(20, 'wechat_tickets') itself (SCHEMA.sql §1) — nothing else belongs here.
-- docs/SCHEMA.sql stays the 0001 baseline byte for byte (test_db.py). Rollback = `git checkout` alone: the old code never reads
-- `wechat_tickets`, which stays in place unharmed (its rows are worthless after three minutes anyway).
--
-- Table notes (the SCHEMA.sql-style comments live here because the baseline file is frozen):
--   wechat_tickets — the ticket itself (26 base32 chars, the scene of the 小程序码 and the poll path) is never stored: `ticket_hash` is its
--                    sha256; `poll_hash` is the sha256 of the poll secret the initiating browser holds in the HttpOnly cookie `wd_wxt`
--                    (a poll without it is a 404 identical to an unknown ticket); `pair_hash` is HMAC-SHA256(WD_SECRET_KEY, "pair:<6
--                    digits>") of the pairing code typed into the mini program and stays on the row for its life (a consumed row still answers a second confirm with 409 wrong_state), so the code
--                    can be handed out again. `status`: pending → scanned (115) → confirmed | cancelled (116) → consumed (113 delivered the
--                    result once); `kind = 'bind'` rows carry the web session's user in `bind_user_id` (fixed at creation); `kind = 'login'`
--                    rows in `invite` mode carry the code validated at creation and consumed at the confirmation; `openid` is written by the
--                    scan and `user_id` / `created_account` by the confirmation. `web_ip` / `web_ua` (the User-Agent cut to 200 chars) are
--                    shown to the scanner only masked / summarised. Tickets live 180 s; rows expired or consumed more than a day ago are
--                    GC'd hourly (the login_codes rule — a consumed row stays a day as the audit trail of a login / binding).
CREATE TABLE wechat_tickets (
  id              INTEGER PRIMARY KEY,
  ticket_hash     TEXT NOT NULL UNIQUE,                 -- sha256 hex of the 26-char ticket (the 小程序码 scene)
  pair_hash       TEXT,                                 -- HMAC-SHA256(WD_SECRET_KEY, "pair:<6 digits>") hex of the pairing code, kept for the row's life (the GC deletes the row)
  poll_hash       TEXT NOT NULL,                        -- sha256 hex of the poll secret (the initiating browser's HttpOnly cookie wd_wxt)
  kind            TEXT NOT NULL CHECK (kind IN ('login','bind')),
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','scanned','confirmed','consumed','cancelled')),
  bind_user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- kind=bind: the web session's user, fixed at creation
  invite_code     TEXT,                                 -- kind=login in invite mode: validated at creation, consumed at confirm
  openid          TEXT,                                 -- set by the scan (115)
  user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,  -- the account the confirmation resolved to
  created_account INTEGER NOT NULL DEFAULT 0,           -- 1 when the confirmation created the account
  web_ip          TEXT,
  web_ua          TEXT,
  created_at      TEXT NOT NULL,
  expires_at      TEXT NOT NULL,
  scanned_at      TEXT,
  confirmed_at    TEXT,
  consumed_at     TEXT
);
CREATE INDEX ix_wechat_tickets_pair ON wechat_tickets(pair_hash) WHERE pair_hash IS NOT NULL;
CREATE INDEX ix_wechat_tickets_expires ON wechat_tickets(expires_at);
