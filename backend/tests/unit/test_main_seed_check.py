"""main.seed_check (PLAN R-9 / §4.7): the lifespan's seed step compares kv.seed_version with the content sha256, imports when
they differ, and never fails startup — a corrupt archive or an importer exception is logged, recorded as
system_events('seed_import_failed') and the service continues with the vocabulary it has; the normal path leaves no event."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from wd import db, main, seed
from wd.seed import seed_digest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MINI_SEED = FIXTURES / "mini_seed.jsonl"
BAD_GZIP_SEED = FIXTURES / "seed_v2" / "bad.jsonl.gz"


def failures(conn) -> list[dict]:
    return [json.loads(r[0]) for r in conn.execute("SELECT detail_json FROM system_events WHERE kind = 'seed_import_failed' ORDER BY id")]


def kinds(conn) -> list[str]:
    return [str(r[0]) for r in conn.execute("SELECT kind FROM system_events WHERE kind != 'migration' ORDER BY id")]


def test_normal_path_imports_once_and_writes_no_failure_event(conn, settings):
    main.seed_check(conn, settings)  # WD_SEED_PATH = the mini seed in the test env
    assert db.kv_get(conn, "seed_version") == seed_digest(MINI_SEED)
    assert conn.execute("SELECT COUNT(*) FROM words").fetchone()[0] == 62
    assert kinds(conn) == ["seed_imported"]
    main.seed_check(conn, settings)  # same content → nothing happens
    assert kinds(conn) == ["seed_imported"]


def test_missing_file_is_a_warning_only(conn, settings, caplog):
    caplog.set_level(logging.WARNING, logger="wd.main")
    main.seed_check(conn, replace(settings, seed_path=settings.data_dir / "nope.jsonl.gz"))
    assert db.kv_get(conn, "seed_version") is None and kinds(conn) == []
    assert any("does not exist" in r.getMessage() for r in caplog.records)


def test_corrupt_gzip_records_a_failure_event_and_returns(conn, settings, caplog):
    caplog.set_level(logging.ERROR, logger="wd.main")
    db.kv_set(conn, "seed_version", "previous")
    main.seed_check(conn, replace(settings, seed_path=BAD_GZIP_SEED))  # returns instead of raising
    assert db.kv_get(conn, "seed_version") == "previous"  # unchanged: the next start retries
    assert conn.execute("SELECT COUNT(*) FROM words").fetchone()[0] == 0 and not conn.in_transaction
    fails = failures(conn)
    assert len(fails) == 1 and fails[0]["file"] == "bad.jsonl.gz" and fails[0]["error"].startswith("EOFError:")
    assert kinds(conn) == ["seed_import_failed"]
    errors = [r for r in caplog.records if r.levelno == logging.ERROR and getattr(r, "event", None) == "seed_import_failed"]
    assert len(errors) == 1 and errors[0].exc_info is not None  # logged with the traceback


def test_importer_exception_is_caught_after_its_own_rollback(conn, settings, monkeypatch):
    seed.import_seed(conn, str(MINI_SEED))
    before = db.kv_get(conn, "seed_version")
    changed = settings.data_dir / "changed.jsonl"
    changed.write_text(MINI_SEED.read_text(encoding="utf-8") + json.dumps({"word": "zebra", "stages": ["xs"]}) + "\n", encoding="utf-8")

    def boom(*a, **k):
        raise RuntimeError("forms exploded")

    monkeypatch.setattr(seed, "_rebuild_forms", boom)
    main.seed_check(conn, replace(settings, seed_path=changed))
    assert db.kv_get(conn, "seed_version") == before and not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM words WHERE lemma = 'zebra'").fetchone()[0] == 0  # the importer's transaction rolled back
    fails = failures(conn)
    assert len(fails) == 1 and fails[0] == {"file": "changed.jsonl", "error": "RuntimeError: forms exploded"}
    monkeypatch.undo()
    main.seed_check(conn, replace(settings, seed_path=changed))  # the next start succeeds
    assert db.kv_get(conn, "seed_version") == seed_digest(changed) and conn.execute("SELECT COUNT(*) FROM words WHERE lemma = 'zebra'").fetchone()[0] == 1
    assert kinds(conn) == ["seed_imported", "seed_import_failed", "seed_imported"]


def test_failure_error_text_is_capped(conn, settings, monkeypatch):
    monkeypatch.setattr(main, "seed_digest", lambda path: (_ for _ in ()).throw(ValueError("x" * 2000)))
    main.seed_check(conn, settings)
    (fail,) = failures(conn)
    assert len(fail["error"]) == 500 and fail["error"].startswith("ValueError: xxx")


def test_app_startup_survives_a_corrupt_seed(settings, frozen_clock):
    """The lifespan runs seed_check: with a corrupt WD_SEED_PATH the API still comes up (no restart loop)."""
    from fastapi.testclient import TestClient

    from wd.main import create_app

    cfg = replace(settings, seed_path=BAD_GZIP_SEED)
    with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:
        assert c.get("/api/health").status_code == 200
    conn = db.connect(settings.db_path)
    try:
        assert kinds(conn) == ["seed_import_failed"] and db.kv_get(conn, "seed_version") is None
    finally:
        conn.close()


@pytest.mark.parametrize("name", ["sha256_file"])
def test_main_no_longer_hashes_the_file_itself(name):
    assert not hasattr(main, name)  # the content digest lives in wd.seed (one definition of "seed version")
