"""main.startup → learn_order.ensure_current (docs/analysis/2026-11-06-learn-order/DESIGN.md §2.4 "service start", §4.1 item 21):
a freshly migrated database whose seed was imported before 0014 gets every stage word ranked at the first start, a second start
writes no row and no event, and a policy failure never fails the startup (``learn_order_failed``, the lists serve the fail-soft
order). Sibling of test_main_seed_check.py."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from wd import db
from wd.main import create_app
from wd.seed import import_seed
from wd.services import learn_order

MINI_SEED = Path(__file__).resolve().parents[1] / "fixtures" / "mini_seed.jsonl"


def kinds(conn) -> list[str]:
    return [str(r[0]) for r in conn.execute("SELECT kind FROM system_events WHERE kind != 'migration' ORDER BY id")]


def snapshot(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT id, learn_rank, updated_at FROM words ORDER BY id")]


def test_startup_fills_ranks_after_the_migration_and_is_a_noop_afterwards(settings, frozen_clock, monkeypatch):
    # the live case: schema 14 applied, the seed imported earlier (same digest, so seed_check is a no-op), the column still empty
    conn = db.connect(settings.db_path)
    try:
        db.run_migrations(conn)
        import_seed(conn, str(MINI_SEED))
        conn.execute("UPDATE words SET learn_rank = NULL")
        conn.execute("DELETE FROM kv WHERE key LIKE 'learn_order.%'")
    finally:
        conn.close()

    with TestClient(create_app(settings, clock=frozen_clock, configure_logs=False)) as c:
        assert c.get("/api/health").status_code == 200
    conn = db.connect(settings.db_path)
    try:
        assert learn_order.unranked_stage_words(conn) == 0
        assert conn.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NULL").fetchone()[0] == 0
        assert db.kv_get(conn, learn_order.KV_VERSION) == learn_order.LEARN_ORDER_VERSION
        assert db.kv_get(conn, learn_order.KV_AT) == "2026-10-14T00:00:00Z"  # the app clock (FrozenClock), not the wall clock
        assert db.kv_get(conn, learn_order.KV_SEED) == db.kv_get(conn, "seed_version")
        assert kinds(conn) == ["seed_imported", "learn_order_recomputed"]
        detail = json.loads(conn.execute("SELECT detail_json FROM system_events WHERE kind = 'learn_order_recomputed'").fetchone()[0])
        assert detail["trigger"] == "startup" and detail["changed"] == 62 and detail["version"] == "lo-1"
        assert learn_order.is_current(conn) == (True, "ok") and learn_order.stale_count(conn) == 0
        first = snapshot(conn)
    finally:
        conn.close()

    # a second start: the compare finds nothing to write — no row, no event
    frozen_clock.advance(hours=1)
    with TestClient(create_app(settings, clock=frozen_clock, configure_logs=False)) as c:
        assert c.get("/api/health").status_code == 200
    conn = db.connect(settings.db_path)
    try:
        assert snapshot(conn) == first and kinds(conn) == ["seed_imported", "learn_order_recomputed"]
        assert db.kv_get(conn, learn_order.KV_AT) == "2026-10-14T01:00:00Z"  # the compare ran (its instant moved)
    finally:
        conn.close()

    # a policy failure never fails the startup: the lists serve the stored keys
    def boom(rows, forms):
        raise RuntimeError("policy exploded")

    monkeypatch.setattr(learn_order, "rank_rows", boom)
    with TestClient(create_app(settings, clock=frozen_clock, configure_logs=False)) as c:
        assert c.get("/api/health").status_code == 200
    conn = db.connect(settings.db_path)
    try:
        assert kinds(conn) == ["seed_imported", "learn_order_recomputed", "learn_order_failed"]
        fail = json.loads(conn.execute("SELECT detail_json FROM system_events WHERE kind = 'learn_order_failed'").fetchone()[0])
        assert fail == {"trigger": "startup", "error": "RuntimeError: policy exploded"}
        assert snapshot(conn) == first  # untouched
    finally:
        conn.close()


def test_startup_on_an_empty_vocabulary_writes_no_event(settings, frozen_clock):
    """No seed file → nothing to rank; the startup step is silent (no learn_order_recomputed, no failure)."""
    from dataclasses import replace

    cfg = replace(settings, seed_path=settings.data_dir / "nope.jsonl.gz")
    with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:
        assert c.get("/api/health").status_code == 200
    conn = db.connect(settings.db_path)
    try:
        assert kinds(conn) == [] and db.kv_get(conn, learn_order.KV_VERSION) == learn_order.LEARN_ORDER_VERSION
    finally:
        conn.close()
