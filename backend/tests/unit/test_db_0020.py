"""0020_wechat_tickets.sql (docs/AUTH_SIGNUP_DESIGN.md §5.3, releases/2026-11-auth-third-party.md, slice 2-A): the `wechat_tickets` table
of the WeChat login bridge (API.md §3.3 endpoints 112–116). Additive like 0012 / 0014 / 0015 / 0017 / 0018 / 0019 — one table, two indexes,
no ADD COLUMN, no data step; statement shape pinned."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db

ALLOWED_PREFIXES = ("CREATE TABLE ", "CREATE INDEX ")
INDEXES_0020 = {"ix_wechat_tickets_pair", "ix_wechat_tickets_expires"}
COLUMNS_0020 = [
    "id", "ticket_hash", "pair_hash", "poll_hash", "kind", "status", "bind_user_id", "invite_code", "openid", "user_id", "created_account",
    "web_ip", "web_ua", "created_at", "expires_at", "scanned_at", "confirmed_at", "consumed_at",
]


def _database_at_0019(settings, tmp_path: Path) -> sqlite3.Connection:
    """A migrated-to-0019 database with an admin (alice), a learner with a phone identity (bob), a guardian's child (carol) and two sessions
    — the rows the live Mac holds when the file runs."""
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 20:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    applied = db.run_migrations(c, migrations_dir=older).applied
    assert applied and applied[-1][0] == 19
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
        c.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip, actor_user_id) VALUES ('t1', 1, '2026-10-13T00:00:00Z', '2026-11-12T00:00:00Z', '2026-10-13T00:00:00Z', 'UA', '10.0.0.9', NULL)"
        )
        c.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip, actor_user_id) VALUES ('t2', 3, '2026-10-13T00:00:00Z', '2026-11-12T00:00:00Z', '2026-10-13T00:00:00Z', 'UA', '10.0.0.9', 2)"
        )
        c.execute("INSERT INTO identities(user_id, provider, subject, verified_at) VALUES (2, 'phone', '+8613800138000', '2026-10-05T09:30:00Z')")
        c.execute("INSERT INTO family_codes(kind, user_id, code_hash, expires_at) VALUES ('child_login', 3, 'h', '2026-10-14T00:10:00Z')")
    return c


def test_0020_adds_wechat_tickets(settings, tmp_path: Path):
    c = _database_at_0019(settings, tmp_path)
    try:
        before_tables = set(db.table_names(c))
        before_users = [tuple(r) for r in c.execute("SELECT * FROM users ORDER BY id")]
        before_users_cols = [r["name"] for r in c.execute("PRAGMA table_info(users)")]
        before_sessions = [tuple(r) for r in c.execute("SELECT * FROM sessions ORDER BY token_hash")]
        before_identities = [tuple(r) for r in c.execute("SELECT * FROM identities ORDER BY id")]
        before_counts = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in before_tables}
        assert "wechat_tickets" not in before_tables

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (20, "wechat_tickets") in result.applied and db.current_version(c) >= 20
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # exactly one table gained, empty, with its two indexes; nothing else moved
        assert set(db.table_names(c)) == before_tables | {"wechat_tickets"}
        assert c.execute("SELECT COUNT(*) FROM wechat_tickets").fetchone()[0] == 0
        indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'wechat_tickets' AND name NOT LIKE 'sqlite_autoindex%'")}
        assert indexes == INDEXES_0020
        pair_sql = c.execute("SELECT sql FROM sqlite_master WHERE name = 'ix_wechat_tickets_pair'").fetchone()[0]
        assert "WHERE pair_hash IS NOT NULL" in pair_sql  # partial: only live tickets hold a pairing code
        assert [r["name"] for r in c.execute("PRAGMA table_info(users)")] == before_users_cols  # no ADD COLUMN anywhere
        assert [tuple(r) for r in c.execute("SELECT * FROM users ORDER BY id")] == before_users
        assert [tuple(r) for r in c.execute("SELECT * FROM sessions ORDER BY token_hash")] == before_sessions
        assert [tuple(r) for r in c.execute("SELECT * FROM identities ORDER BY id")] == before_identities
        assert {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in before_tables if t != "schema_migrations"} == {t: n for t, n in before_counts.items() if t != "schema_migrations"}
        # the columns in file order with their constraints
        cols = {r["name"]: r for r in c.execute("PRAGMA table_info(wechat_tickets)")}
        assert list(cols) == COLUMNS_0020
        assert (cols["status"]["notnull"], cols["status"]["dflt_value"]) == (1, "'pending'")
        assert (cols["created_account"]["notnull"], cols["created_account"]["dflt_value"]) == (1, "0")
        assert cols["ticket_hash"]["notnull"] == 1 and cols["poll_hash"]["notnull"] == 1 and cols["kind"]["notnull"] == 1
        assert cols["created_at"]["notnull"] == 1 and cols["expires_at"]["notnull"] == 1
        assert all(cols[n]["notnull"] == 0 for n in ("pair_hash", "bind_user_id", "invite_code", "openid", "user_id", "web_ip", "web_ua", "scanned_at", "confirmed_at", "consumed_at"))
        # a pending login ticket and a bind ticket of bob
        c.execute(
            "INSERT INTO wechat_tickets(ticket_hash, pair_hash, poll_hash, kind, web_ip, web_ua, created_at, expires_at) "
            "VALUES ('th1', 'ph1', 'po1', 'login', '203.0.113.7', 'UA', '2026-10-14T00:00:00Z', '2026-10-14T00:03:00Z')"
        )
        c.execute(
            "INSERT INTO wechat_tickets(ticket_hash, pair_hash, poll_hash, kind, bind_user_id, created_at, expires_at) "
            "VALUES ('th2', 'ph2', 'po2', 'bind', 2, '2026-10-14T00:00:00Z', '2026-10-14T00:03:00Z')"
        )
        row = c.execute("SELECT * FROM wechat_tickets WHERE id = 1").fetchone()
        assert (row["status"], row["created_account"], row["openid"], row["user_id"], row["scanned_at"], row["consumed_at"]) == ("pending", 0, None, None, None, None)
        # the CHECKs, the UNIQUE ticket hash and the FKs
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("INSERT INTO wechat_tickets(ticket_hash, poll_hash, kind, created_at, expires_at) VALUES ('th3', 'po3', 'pair', '2026-10-14T00:00:00Z', '2026-10-14T00:03:00Z')")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("UPDATE wechat_tickets SET status = 'expired' WHERE id = 1")  # `expired` is computed from expires_at, never stored
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            c.execute("INSERT INTO wechat_tickets(ticket_hash, poll_hash, kind, created_at, expires_at) VALUES ('th1', 'po3', 'login', '2026-10-14T00:00:00Z', '2026-10-14T00:03:00Z')")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            c.execute("INSERT INTO wechat_tickets(ticket_hash, poll_hash, kind, bind_user_id, created_at, expires_at) VALUES ('th4', 'po4', 'bind', 999, '2026-10-14T00:00:00Z', '2026-10-14T00:03:00Z')")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            c.execute("UPDATE wechat_tickets SET user_id = 999 WHERE id = 1")
        for status in ("scanned", "confirmed", "cancelled", "consumed"):
            c.execute("UPDATE wechat_tickets SET status = ? WHERE id = 1", (status,))
        # the confirmation resolved the login ticket to alice; deleting her SET NULLs it, deleting bob (the binder) CASCADEs his bind ticket
        c.execute("UPDATE wechat_tickets SET status = 'confirmed', user_id = 1, created_account = 1, confirmed_at = '2026-10-14T00:01:00Z', pair_hash = NULL WHERE id = 1")
        c.execute("DELETE FROM users WHERE id = 1")
        assert c.execute("SELECT user_id, status FROM wechat_tickets WHERE id = 1").fetchone()[:] == (None, "confirmed")
        c.execute("DELETE FROM users WHERE id = 3")  # the child first (guardian_user_id is ON DELETE RESTRICT)
        c.execute("DELETE FROM users WHERE id = 2")
        assert [r[0] for r in c.execute("SELECT id FROM wechat_tickets ORDER BY id")] == [1]
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_0020_is_additive_without_data_steps():
    """One CREATE TABLE and two CREATE INDEXes — no ADD COLUMN, no DROP / RENAME, no PRAGMA, no COMMIT, no UPDATE / INSERT / DELETE
    (schema_migrations is the runner's), so the file is `--no-restart` safe (DEPLOY §5/§10)."""
    text = (db.MIGRATIONS_DIR / "0020_wechat_tickets.sql").read_text(encoding="utf-8")
    sql = "\n".join(line.split("--", 1)[0] for line in text.splitlines())  # the comments are prose; only the statements are pinned
    statements = [" ".join(s.split()) for s in sql.split(";") if s.strip()]
    assert len(statements) == 3  # 1 table + 2 indexes
    assert all(s.startswith(ALLOWED_PREFIXES) for s in statements), [s for s in statements if not s.startswith(ALLOWED_PREFIXES)]
    assert statements[0].startswith("CREATE TABLE wechat_tickets (")
    assert sum(s.startswith("CREATE INDEX ") for s in statements) == 2
    assert {s.split()[2] for s in statements if s.startswith("CREATE INDEX ")} == INDEXES_0020
    upper = sql.upper()
    for forbidden in ("DROP ", "RENAME", "PRAGMA", "COMMIT", "ROLLBACK", "INSERT INTO", "UPDATE ", "ALTER TABLE", "CREATE UNIQUE"):
        assert forbidden not in upper, forbidden
    assert not any(s.upper().startswith(("DELETE", "INSERT", "REPLACE", "UPDATE")) for s in statements)  # `ON DELETE …` inside the FK clauses is the only DELETE
    assert (20, "wechat_tickets") in [(f.version, f.name) for f in db.list_migration_files()]
