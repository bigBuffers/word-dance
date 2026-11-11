"""0019_family.sql (docs/AUTH_SIGNUP_DESIGN.md §5.1–5.2, releases/2026-11-auth-signup-1b.md): the `family_codes` table (child login codes
and claim codes), `sessions.guardian_gate_at` (the 家长门 stamp) and `users.profile_prompted_at` (the legacy prompt's snooze). Additive
like 0012 / 0014 / 0015 / 0017 / 0018 — two ADD COLUMNs, one table, three indexes, no data step; statement shape pinned."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

ALLOWED_PREFIXES = ("ALTER TABLE users ADD COLUMN ", "ALTER TABLE sessions ADD COLUMN ", "CREATE TABLE ", "CREATE INDEX ")
INDEXES_0019 = {"ix_family_codes_hash", "ix_family_codes_user", "ix_family_codes_expires"}


def _database_at_0018(settings, tmp_path: Path) -> sqlite3.Connection:
    """A migrated-to-0018 database with a guardian-less learner (alice), a guardian (bob) with a child (carol) and two sessions —
    the rows the live Mac holds when the file runs."""
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 19:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    applied = db.run_migrations(c, migrations_dir=older).applied
    assert applied and applied[-1][0] == 18
    with db.tx(c):
        c.execute(
            "INSERT INTO users(id, username, email, email_verified_at, display_name, password_hash, password_set_at, role, created_at, updated_at, last_login_at) "
            "VALUES (1, 'alice', 'alice@example.com', '2026-10-02T00:00:00Z', '小张', '$2b$04$alice', '2026-10-01T08:00:00Z', 'admin', '2026-10-01T08:00:00Z', '2026-10-01T08:00:00Z', '2026-10-13T00:00:00Z')"
        )
        c.execute(
            "INSERT INTO users(id, username, password_hash, password_set_at, account_kind, age_band, age_declared_at, created_at, updated_at) "
            "VALUES (2, 'bob', '$2b$04$bob', '2026-10-05T09:30:00Z', 'guardian', 'adult', '2026-10-05T09:30:00Z', '2026-10-05T09:30:00Z', '2026-10-05T09:30:00Z')"
        )
        c.execute(
            "INSERT INTO users(id, username, password_hash, guardian_user_id, age_band, guardian_consent_at, created_at, updated_at) "
            "VALUES (3, 'u_carolxyz2', '$2b$04$carol', 2, 'u14', '2026-10-06T00:00:00Z', '2026-10-06T00:00:00Z', '2026-10-06T00:00:00Z')"
        )
        c.executemany("INSERT INTO user_settings(user_id, next_push_at, updated_at) VALUES (?, '2026-10-15T00:00:00Z', '2026-10-01T08:00:00Z')", [(1,), (2,), (3,)])
        # the 0018 session INSERT (security.create_session names exactly these eight columns)
        c.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip, actor_user_id) VALUES ('t1', 1, '2026-10-13T00:00:00Z', '2026-11-12T00:00:00Z', '2026-10-13T00:00:00Z', 'UA', '10.0.0.9', NULL)"
        )
        c.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip, actor_user_id) VALUES ('t2', 3, '2026-10-13T00:00:00Z', '2026-11-12T00:00:00Z', '2026-10-13T00:00:00Z', 'UA', '10.0.0.9', 2)"
        )
        c.execute("INSERT INTO identities(user_id, provider, subject, verified_at) VALUES (2, 'phone', '+8613800138000', '2026-10-05T09:30:00Z')")
    return c


def test_0019_adds_family_codes_and_the_two_columns(settings, tmp_path: Path):
    c = _database_at_0018(settings, tmp_path)
    try:
        before_users_cols = [r["name"] for r in c.execute("PRAGMA table_info(users)")]
        before_sessions_cols = [r["name"] for r in c.execute("PRAGMA table_info(sessions)")]
        before_users = [tuple(r) for r in c.execute("SELECT * FROM users ORDER BY id")]
        before_sessions = [tuple(r) for r in c.execute("SELECT * FROM sessions ORDER BY token_hash")]
        before_tables = set(db.table_names(c))
        assert "profile_prompted_at" not in before_users_cols and "guardian_gate_at" not in before_sessions_cols and "family_codes" not in before_tables

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (19, "family") in result.applied and db.current_version(c) >= 19
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # the two columns appended last, nullable, without a default; nothing else moved
        assert [r["name"] for r in c.execute("PRAGMA table_info(users)")] == [*before_users_cols, "profile_prompted_at"]
        assert [r["name"] for r in c.execute("PRAGMA table_info(sessions)")] == [*before_sessions_cols, "guardian_gate_at"]
        users_cols = {r["name"]: r for r in c.execute("PRAGMA table_info(users)")}
        sessions_cols = {r["name"]: r for r in c.execute("PRAGMA table_info(sessions)")}
        assert (users_cols["profile_prompted_at"]["type"], users_cols["profile_prompted_at"]["notnull"], users_cols["profile_prompted_at"]["dflt_value"]) == ("TEXT", 0, None)
        assert (sessions_cols["guardian_gate_at"]["type"], sessions_cols["guardian_gate_at"]["notnull"], sessions_cols["guardian_gate_at"]["dflt_value"]) == ("TEXT", 0, None)
        # every pre-existing value survived (no rebuild, no data step); the new columns are NULL everywhere
        assert [tuple(r)[: len(before_users_cols)] for r in c.execute("SELECT * FROM users ORDER BY id")] == before_users
        assert [tuple(r)[: len(before_sessions_cols)] for r in c.execute("SELECT * FROM sessions ORDER BY token_hash")] == before_sessions
        assert c.execute("SELECT COUNT(*) FROM users WHERE profile_prompted_at IS NOT NULL").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM sessions WHERE guardian_gate_at IS NOT NULL").fetchone()[0] == 0
        assert c.execute("SELECT guardian_user_id, account_kind FROM users WHERE id = 3").fetchone()[:] == (2, "learner")  # the 1-A columns untouched
        assert c.execute("SELECT actor_user_id FROM sessions WHERE token_hash = 't2'").fetchone()[0] == 2
        # the table, empty, with its three indexes
        assert set(db.table_names(c)) == before_tables | {"family_codes"}
        assert c.execute("SELECT COUNT(*) FROM family_codes").fetchone()[0] == 0
        indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'family_codes' AND name NOT LIKE 'sqlite_autoindex%'")}
        assert indexes == INDEXES_0019
        cols = {r["name"]: r for r in c.execute("PRAGMA table_info(family_codes)")}
        assert list(cols) == ["id", "kind", "user_id", "target", "code_hash", "expires_at", "attempts", "used_at", "ip", "created_at"]
        assert (cols["attempts"]["notnull"], cols["attempts"]["dflt_value"]) == (1, "0") and cols["target"]["notnull"] == 0 and cols["user_id"]["notnull"] == 1
        # the old INSERT shapes still work (a rolled-back binary keeps writing them) and leave the new columns NULL
        c.execute("INSERT INTO users(username, password_hash) VALUES ('dave', '$2b$04$dave')")
        assert c.execute("SELECT profile_prompted_at, account_kind FROM users WHERE username = 'dave'").fetchone()[:] == (None, "learner")
        c.execute("INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip, actor_user_id) VALUES ('t3', 2, '2026-10-14T00:00:00Z', '2026-11-13T00:00:00Z', '2026-10-14T00:00:00Z', NULL, NULL, NULL)")
        assert c.execute("SELECT guardian_gate_at FROM sessions WHERE token_hash = 't3'").fetchone()[0] is None
        # the CHECK and the FK
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("INSERT INTO family_codes(kind, user_id, code_hash, expires_at) VALUES ('join', 3, 'h', '2026-10-14T00:10:00Z')")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            c.execute("INSERT INTO family_codes(kind, user_id, code_hash, expires_at) VALUES ('child_login', 999, 'h', '2026-10-14T00:10:00Z')")
        c.execute("INSERT INTO family_codes(kind, user_id, code_hash, expires_at, ip) VALUES ('child_login', 3, 'h1', '2026-10-14T00:10:00Z', '10.0.0.9')")
        c.execute("INSERT INTO family_codes(kind, user_id, target, code_hash, expires_at) VALUES ('claim_guardian', 1, '+8613800138000', 'h2', '2026-10-14T00:10:00Z')")
        row = c.execute("SELECT * FROM family_codes WHERE id = 1").fetchone()
        assert row["attempts"] == 0 and row["used_at"] is None and row["target"] is None and row["created_at"]
        # the stamps are plain nullable timestamps
        c.execute("UPDATE sessions SET guardian_gate_at = '2026-10-14T00:05:00Z' WHERE token_hash = 't1'")
        c.execute("UPDATE users SET profile_prompted_at = '2026-10-14T00:05:00Z' WHERE id = 1")
        # cascades with foreign keys ON: deleting the child removes its codes and its sessions; alice's claim code stays
        c.execute("DELETE FROM users WHERE id = 3")
        assert [r[0] for r in c.execute("SELECT id FROM family_codes ORDER BY id")] == [2]
        assert [r[0] for r in c.execute("SELECT token_hash FROM sessions ORDER BY token_hash")] == ["t1", "t3"]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_0019_is_additive_without_data_steps():
    """Two ADD COLUMNs, one CREATE TABLE, three CREATE INDEXes — no DROP / RENAME, no PRAGMA, no COMMIT, no UPDATE / INSERT / DELETE
    (schema_migrations is the runner's), so the file is `--no-restart` safe (DEPLOY §5/§10)."""
    text = (db.MIGRATIONS_DIR / "0019_family.sql").read_text(encoding="utf-8")
    sql = "\n".join(line.split("--", 1)[0] for line in text.splitlines())  # the comments are prose; only the statements are pinned
    statements = [" ".join(s.split()) for s in sql.split(";") if s.strip()]
    assert len(statements) == 6  # 1 (users) · 1 (sessions) · 1 + 3 (family_codes)
    assert all(s.startswith(ALLOWED_PREFIXES) for s in statements), [s for s in statements if not s.startswith(ALLOWED_PREFIXES)]
    assert statements[0].startswith("ALTER TABLE users ADD COLUMN profile_prompted_at TEXT") and statements[1].startswith("ALTER TABLE sessions ADD COLUMN guardian_gate_at TEXT")
    assert sum(s.startswith("CREATE TABLE ") for s in statements) == 1 and sum(s.startswith("CREATE INDEX ") for s in statements) == 3
    assert {s.split()[2] for s in statements if s.startswith("CREATE INDEX ")} == INDEXES_0019
    upper = sql.upper()
    for forbidden in ("DROP ", "RENAME", "PRAGMA", "COMMIT", "ROLLBACK", "INSERT INTO", "UPDATE ", "CREATE UNIQUE"):
        assert forbidden not in upper, forbidden
    assert not any(s.upper().startswith(("DELETE", "INSERT", "REPLACE", "UPDATE")) for s in statements)  # `ON DELETE …` inside the FK clause is the only DELETE
    assert (19, "family") in [(f.version, f.name) for f in db.list_migration_files()]
