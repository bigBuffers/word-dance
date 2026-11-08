"""0016_word_dances.sql (docs/WORD_DANCE_DESIGN.md §6, releases/2026-11-word-dance-p2.md): `jobs` and `ai_calls` are rebuilt with
the new type / kind in their CHECK lists and every row, index and column survives; `word_dances` appears with its unique active
index; `words` gains `active_dance_id` / `dance_state`. The file is a stop-first rebuild like 0011 / 0013."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db
from wd.jobs import queue, registry


def _database_at_0015(settings, tmp_path: Path) -> sqlite3.Connection:
    older = tmp_path / "older"
    older.mkdir()
    for f in db.list_migration_files():
        if f.version < 16:
            shutil.copy(f.path, older / f.path.name)
    c = db.connect(settings.db_path)
    applied = db.run_migrations(c, migrations_dir=older).applied
    assert applied and applied[-1][0] == 15
    with db.tx(c):
        c.execute("INSERT INTO words(id, lemma, display, source, phonetic) VALUES (1, 'apple', 'apple', 'seed', '''æpl')")
        c.execute("INSERT INTO words(id, lemma, display, source, phonetic) VALUES (2, 'up', 'up', 'seed', 'ʌp')")
        c.execute(
            "INSERT INTO jobs(id, type, payload_json, dedupe_key, priority, status, attempts, max_attempts, run_after, locked_at, locked_by, last_error, result_json, created_at, updated_at, finished_at) "
            "VALUES (7, 'generate_svg', '{\"word_id\": 1}', 'svg:1', 20, 'done', 1, 3, '2026-11-01T00:00:00Z', NULL, NULL, NULL, '{\"image_id\": 3}', '2026-11-01T00:00:00Z', '2026-11-01T00:01:00Z', '2026-11-01T00:01:00Z')"
        )
        c.execute("INSERT INTO jobs(id, type, payload_json, dedupe_key, priority, status) VALUES (8, 'fetch_image', '{\"word_id\": 2}', 'image:2', 50, 'queued')")
        c.execute(
            "INSERT INTO ai_calls(id, kind, status, model_requested, model_used, flag_tier, word_count, job_ids_json, max_budget_usd, reserved_usd, cost_usd, duration_ms, started_at, finished_at, provider) "
            "VALUES (11, 'svg', 'success', 'sonnet', 'claude-sonnet-5-5', 0, 1, '[7]', 0.1, 0.03, 0.0124, 9000, '2026-11-01T00:00:00Z', '2026-11-01T00:00:09Z', 'claude')"
        )
        c.execute("INSERT INTO ai_calls(id, kind, status, model_requested, max_budget_usd, provider) VALUES (12, 'content', 'running', 'sonnet', 0.25, 'fallback')")
    return c


def test_0016_rebuilds_jobs_and_ai_calls_keeping_rows_and_adds_word_dances(settings, tmp_path: Path):
    c = _database_at_0015(settings, tmp_path)
    try:
        before_jobs = [tuple(r) for r in c.execute("SELECT * FROM jobs ORDER BY id")]
        before_calls = [tuple(r) for r in c.execute("SELECT * FROM ai_calls ORDER BY id")]
        before_jobs_cols = [r["name"] for r in c.execute("PRAGMA table_info(jobs)")]
        before_calls_cols = [r["name"] for r in c.execute("PRAGMA table_info(ai_calls)")]
        before_words_cols = [r["name"] for r in c.execute("PRAGMA table_info(words)")]
        before_tables = set(db.table_names(c))
        with pytest.raises(sqlite3.IntegrityError):  # the v15 CHECK lists have no dance yet
            c.execute("INSERT INTO jobs(type, payload_json) VALUES ('generate_dance', '{}')")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO ai_calls(kind, model_requested, max_budget_usd) VALUES ('dance', 'sonnet', 0.25)")

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert (16, "word_dances") in result.applied and db.current_version(c) >= 16
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert set(db.table_names(c)) == before_tables | {"word_dances"}
        # rebuilt in place: same columns in the same order, every row intact, ids preserved
        assert [r["name"] for r in c.execute("PRAGMA table_info(jobs)")] == before_jobs_cols
        assert [r["name"] for r in c.execute("PRAGMA table_info(ai_calls)")] == before_calls_cols
        assert [tuple(r) for r in c.execute("SELECT * FROM jobs ORDER BY id")] == before_jobs
        assert [tuple(r) for r in c.execute("SELECT * FROM ai_calls ORDER BY id")] == before_calls
        indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name IN ('jobs', 'ai_calls', 'word_dances')")}
        assert {"ux_jobs_dedupe_live", "ix_jobs_claim", "ix_jobs_updated", "ix_ai_calls_started", "ix_ai_calls_status", "ix_ai_calls_provider_started", "ix_word_dances_word", "ux_word_dances_active"} <= indexes
        # the CHECK lists now admit the new type / kind and still reject strangers
        c.execute("INSERT INTO jobs(type, payload_json, dedupe_key) VALUES ('generate_dance', '{\"word_id\": 2}', 'dance:2')")
        c.execute("INSERT INTO ai_calls(kind, model_requested, max_budget_usd) VALUES ('dance', 'sonnet', 0.25)")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO jobs(type, payload_json) VALUES ('generate_dance2', '{}')")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO ai_calls(kind, model_requested, max_budget_usd) VALUES ('tango', 'sonnet', 0.25)")
        # the live dedupe index still works on the rebuilt table (queue.enqueue's UPSERT target)
        jid = queue.enqueue(c, "generate_dance", {"word_id": 1}, dedupe_key="dance:1", priority=50, now="2026-11-08T00:00:00Z")
        assert queue.enqueue(c, "generate_dance", {"word_id": 1}, dedupe_key="dance:1", priority=10, now="2026-11-08T00:00:00Z") == jid
        assert c.execute("SELECT priority FROM jobs WHERE id = ?", (jid,)).fetchone()[0] == 10
        # words: the two new columns, appended with their defaults
        assert [r["name"] for r in c.execute("PRAGMA table_info(words)")] == [*before_words_cols, "active_dance_id", "dance_state"]
        assert [tuple(r) for r in c.execute("SELECT active_dance_id, dance_state FROM words ORDER BY id")] == [(None, "none"), (None, "none")]
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            c.execute("UPDATE words SET dance_state = 'dancing' WHERE id = 1")
        # word_dances: one active row per word; the columns the handler writes
        assert [r["name"] for r in c.execute("PRAGMA table_info(word_dances)")] == ["id", "word_id", "status", "spec_json", "model", "prompt_version", "reason", "created_at"]
        c.execute("INSERT INTO word_dances(word_id, status, spec_json) VALUES (1, 'active', '{}')")
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO word_dances(word_id, status, spec_json) VALUES (1, 'active', '{}')")
        c.execute("INSERT INTO word_dances(word_id, status, spec_json) VALUES (1, 'superseded', '{}')")
        with pytest.raises(sqlite3.IntegrityError):  # a child of words
            c.execute("INSERT INTO word_dances(word_id, status, spec_json) VALUES (999, 'active', '{}')")
        assert c.execute("PRAGMA foreign_key_check").fetchall() == [] and c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.run_migrations(c).applied == []  # idempotent
        assert set(registry.JOB_TYPES) == {"generate_content", "lookup_word", "consolidate_bank", "generate_svg", "fetch_image", "send_email", "send_webhook", "prewarm_plan", "generate_dance"}
    finally:
        c.close()


def test_0016_is_a_rebuild_without_pragma_or_commit():
    """Like 0011 / 0013: creates the _new tables, copies, drops, renames, re-creates the indexes; never toggles foreign_keys and never
    ends the transaction itself (the runner owns both, SCHEMA.sql §1)."""
    text = (db.MIGRATIONS_DIR / "0016_word_dances.sql").read_text(encoding="utf-8")
    statements = [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("--")]
    joined = "\n".join(statements).upper()
    assert "PRAGMA" not in joined and "COMMIT" not in joined and "ROLLBACK" not in joined
    assert joined.count("CREATE TABLE JOBS_NEW") == 1 and joined.count("CREATE TABLE AI_CALLS_NEW") == 1 and joined.count("CREATE TABLE WORD_DANCES") == 1
    assert joined.count("DROP TABLE") == 2 and joined.count("RENAME TO") == 2
    assert sum(1 for s in statements if s.startswith("ALTER TABLE words ADD COLUMN")) == 2
