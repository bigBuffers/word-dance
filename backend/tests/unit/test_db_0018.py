"""0018_auth_identities.sql (docs/AUTH_SIGNUP_DESIGN.md §5.1, releases/2026-11-auth-signup-1a.md): the `identities` and `login_codes`
tables, eight nullable / defaulted columns on `users` (password_set_at backfilled with created_at — every pre-0018 account registered
with a real password), `sessions.actor_user_id`, the partial unique indexes of the live bindings, the cascades. `email_codes` stays
(stop-write only). Additive like 0012 / 0014 / 0015 / 0017 — statement shape pinned."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

USERS_0018_COLUMNS = ("password_set_at", "account_kind", "guardian_user_id", "age_band", "age_declared_at", "age_declared_ip", "guardian_consent_at", "guardian_pin_hash")
ALLOWED_PREFIXES = ("ALTER TABLE users ADD COLUMN ", "ALTER TABLE sessions ADD COLUMN ", "CREATE TABLE ", "CREATE INDEX ", "CREATE UNIQUE INDEX ")
BACKFILL = "UPDATE users SET password_set_at = created_at"


def _database_at_0017(settings, tmp_path: Path) -> sqlite3.Connection:
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 18:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    applied = db.run_migrations(c, migrations_dir=older).applied
    assert applied and applied[-1][0] == 17
    with db.tx(c):
        c.execute(
            "INSERT INTO users(id, username, email, email_verified_at, display_name, password_hash, role, created_at, updated_at, last_login_at) "
            "VALUES (1, 'alice', 'alice@example.com', '2026-10-02T00:00:00Z', '小张', '$2b$04$alice', 'admin', '2026-10-01T08:00:00Z', '2026-10-01T08:00:00Z', '2026-10-13T00:00:00Z')"
        )
        c.execute("INSERT INTO users(id, username, password_hash, created_at, updated_at) VALUES (2, 'bob', '$2b$04$bob', '2026-10-05T09:30:00Z', '2026-10-05T09:30:00Z')")
        c.executemany("INSERT INTO user_settings(user_id, next_push_at, updated_at) VALUES (?, '2026-10-15T00:00:00Z', '2026-10-01T08:00:00Z')", [(1,), (2,)])
        # the pre-0018 session INSERT (security.create_session names exactly these seven columns)
        c.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip) VALUES ('t1', 1, '2026-10-13T00:00:00Z', '2026-11-12T00:00:00Z', '2026-10-13T00:00:00Z', 'UA', '10.0.0.9')"
        )
        c.execute("INSERT INTO email_codes(user_id, email, code_hash, expires_at) VALUES (1, 'alice@example.com', 'h', '2026-10-14T00:15:00Z')")
    return c


def test_0018_adds_identities_login_codes_and_the_account_columns(settings, tmp_path: Path):
    c = _database_at_0017(settings, tmp_path)
    try:
        before_users_cols = [r["name"] for r in c.execute("PRAGMA table_info(users)")]
        before_sessions_cols = [r["name"] for r in c.execute("PRAGMA table_info(sessions)")]
        before_users = [tuple(r) for r in c.execute("SELECT * FROM users ORDER BY id")]
        before_sessions = [tuple(r) for r in c.execute("SELECT * FROM sessions")]
        before_tables = set(db.table_names(c))
        assert "password_set_at" not in before_users_cols and "identities" not in before_tables

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (18, "auth_identities") in result.applied and db.current_version(c) >= 18
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # columns appended in file order, nothing else moved
        assert [r["name"] for r in c.execute("PRAGMA table_info(users)")] == [*before_users_cols, *USERS_0018_COLUMNS, "profile_prompted_at"]  # 0019 rides along
        assert [r["name"] for r in c.execute("PRAGMA table_info(sessions)")] == [*before_sessions_cols, "actor_user_id", "guardian_gate_at"]
        kinds = {r["name"]: r for r in c.execute("PRAGMA table_info(users)")}
        assert (kinds["account_kind"]["notnull"], kinds["account_kind"]["dflt_value"]) == (1, "'learner'")
        assert all(kinds[col]["notnull"] == 0 and kinds[col]["dflt_value"] is None for col in USERS_0018_COLUMNS if col != "account_kind")
        # every pre-existing value survived; the backfill and the defaults
        assert [tuple(r)[: len(before_users_cols)] for r in c.execute("SELECT * FROM users ORDER BY id")] == before_users
        assert [tuple(r)[: len(before_sessions_cols)] for r in c.execute("SELECT * FROM sessions")] == before_sessions
        rows = {r["id"]: r for r in c.execute("SELECT * FROM users")}
        assert rows[1]["password_set_at"] == "2026-10-01T08:00:00Z" and rows[2]["password_set_at"] == "2026-10-05T09:30:00Z"  # == created_at
        assert all(r["account_kind"] == "learner" and r["age_band"] is None and r["guardian_user_id"] is None for r in rows.values())
        assert c.execute("SELECT actor_user_id FROM sessions").fetchone()[0] is None
        # the two tables and their indexes; email_codes stays with its row
        assert set(db.table_names(c)) == before_tables | {"identities", "login_codes", "family_codes", "wechat_tickets"}  # 0019 and 0020 ride along
        assert c.execute("SELECT COUNT(*) FROM email_codes").fetchone()[0] == 1

        def indexes(table: str) -> set[str]:
            return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = ? AND name NOT LIKE 'sqlite_autoindex%'", (table,))}

        assert {"ux_identities_live", "ux_identities_user_provider", "ix_identities_user"} <= indexes("identities")
        assert {"ix_login_codes_live", "ix_login_codes_user", "ix_login_codes_expires"} <= indexes("login_codes")
        assert "ix_sessions_actor" in indexes("sessions")
        # the old INSERT shapes still work (a rolled-back binary keeps writing them) and leave the DDL defaults
        c.execute("INSERT INTO users(username, password_hash) VALUES ('carol', '$2b$04$carol')")
        carol = c.execute("SELECT * FROM users WHERE username = 'carol'").fetchone()
        assert carol["password_set_at"] is None and carol["account_kind"] == "learner"
        c.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip) VALUES ('t2', 2, '2026-10-14T00:00:00Z', '2026-11-13T00:00:00Z', '2026-10-14T00:00:00Z', NULL, NULL)")
        assert c.execute("SELECT actor_user_id FROM sessions WHERE token_hash = 't2'").fetchone()[0] is None
        # CHECKs
        for stmt in (
            "UPDATE users SET account_kind = 'teacher' WHERE id = 1",
            "UPDATE users SET age_band = 'kid' WHERE id = 1",
            "INSERT INTO identities(user_id, provider, subject) VALUES (1, 'sms', '+8613800138000')",
            "INSERT INTO login_codes(channel, target, purpose, code_hash, expires_at) VALUES ('fax', 'x', 'login', 'h', '2026-10-14T00:10:00Z')",
            "INSERT INTO login_codes(channel, target, purpose, code_hash, expires_at) VALUES ('phone', '+8613800138000', 'dance', 'h', '2026-10-14T00:10:00Z')",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                c.execute(stmt)
        c.execute("UPDATE users SET account_kind = 'guardian', age_band = 'adult', age_declared_at = '2026-10-14T00:00:00Z', age_declared_ip = '10.0.0.9' WHERE id = 1")
        # foreign keys: unknown users are refused, a guardian cannot be deleted while a child points at it (RESTRICT)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            c.execute("INSERT INTO identities(user_id, provider, subject) VALUES (999, 'phone', '+8613800138009')")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            c.execute("UPDATE users SET guardian_user_id = 999 WHERE id = 2")
        c.execute("UPDATE users SET guardian_user_id = 1 WHERE id = 2")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            c.execute("DELETE FROM users WHERE id = 1")
        c.execute("UPDATE users SET guardian_user_id = NULL WHERE id = 2")
        # one live row per (provider, subject) and per (user_id, provider); a disputed row frees both
        c.execute("INSERT INTO identities(id, user_id, provider, subject, verified_at, last_login_at) VALUES (1, 1, 'phone', '+8613800138000', '2026-10-02T00:00:00Z', '2026-10-13T00:00:00Z')")
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            c.execute("INSERT INTO identities(user_id, provider, subject) VALUES (2, 'phone', '+8613800138000')")  # the same number for bob
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            c.execute("INSERT INTO identities(user_id, provider, subject) VALUES (1, 'phone', '+8613800138001')")  # a second live phone for alice
        c.execute("UPDATE identities SET disputed_at = '2026-10-14T00:00:00Z' WHERE id = 1")
        c.execute("INSERT INTO identities(id, user_id, provider, subject) VALUES (2, 2, 'phone', '+8613800138000')")  # bob now holds the number
        c.execute("INSERT INTO identities(id, user_id, provider, subject) VALUES (3, 1, 'phone', '+8613800138001')")  # alice may bind another one
        row = c.execute("SELECT * FROM identities WHERE id = 2").fetchone()
        assert row["verified_at"] and row["created_at"] and row["meta_json"] == "{}" and row["last_login_at"] is None and row["disputed_at"] is None
        # cascades with foreign keys ON: deleting bob removes his identity and his codes; alice's rows stay
        c.execute("INSERT INTO login_codes(channel, target, purpose, user_id, code_hash, expires_at, ip) VALUES ('phone', '+8613800138000', 'reauth', 2, 'h', '2026-10-14T00:10:00Z', '10.0.0.9')")
        c.execute("INSERT INTO login_codes(channel, target, purpose, code_hash, expires_at) VALUES ('email', 'x@example.com', 'login', 'h', '2026-10-14T00:10:00Z')")
        c.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, actor_user_id) VALUES ('t3', 2, '2026-10-14T00:00:00Z', '2026-11-13T00:00:00Z', '2026-10-14T00:00:00Z', 1)")
        c.execute("DELETE FROM users WHERE id = 2")
        assert [r[0] for r in c.execute("SELECT id FROM identities ORDER BY id")] == [1, 3]
        assert [r[0] for r in c.execute("SELECT user_id FROM login_codes")] == [None]  # the user-less login code stays
        assert [r[0] for r in c.execute("SELECT token_hash FROM sessions ORDER BY token_hash")] == ["t1"]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_0018_is_additive_without_pragma_commit_or_inserts():
    """ADD COLUMN / CREATE TABLE / CREATE [UNIQUE] INDEX plus the one `password_set_at` backfill — no DROP / RENAME, no PRAGMA, no
    COMMIT, no INSERT (schema_migrations is the runner's), so the file is `--no-restart` safe (DEPLOY §5/§10)."""
    text = (db.MIGRATIONS_DIR / "0018_auth_identities.sql").read_text(encoding="utf-8")
    sql = "\n".join(line.split("--", 1)[0] for line in text.splitlines())  # the comments are prose; only the statements are pinned
    statements = [" ".join(s.split()) for s in sql.split(";") if s.strip()]
    assert len(statements) == 19  # 8 + 1 (users) · 1 + 1 (sessions) · 1 + 3 (identities) · 1 + 3 (login_codes)
    assert [s for s in statements if s.startswith("UPDATE ")] == [BACKFILL]
    assert all(s.startswith(ALLOWED_PREFIXES) or s == BACKFILL for s in statements), [s for s in statements if not s.startswith(ALLOWED_PREFIXES)]
    assert [s.split()[5] for s in statements if s.startswith("ALTER TABLE users ADD COLUMN ")] == list(USERS_0018_COLUMNS)
    assert sum(s.startswith("CREATE TABLE ") for s in statements) == 2 and sum(s.startswith("CREATE UNIQUE INDEX ") for s in statements) == 2
    upper = sql.upper()
    for forbidden in ("DROP ", "RENAME", "PRAGMA", "COMMIT", "ROLLBACK", "INSERT INTO"):
        assert forbidden not in upper, forbidden
    assert not any(s.upper().startswith(("DELETE", "INSERT", "REPLACE")) for s in statements)  # `ON DELETE …` inside the FK clauses is the only DELETE
    assert (18, "auth_identities") in [(f.version, f.name) for f in db.list_migration_files()]
