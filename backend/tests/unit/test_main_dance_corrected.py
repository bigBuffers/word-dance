"""main.startup → dance.backfill_corrected (docs/WORD_DANCE_DESIGN.md §13, releases/2026-11-word-dance-p3b.md §4): the first start after
migration 0017 fills `word_dances.corrected` for every stored row, a second start fills nothing, and a failure never fails the startup.
Sibling of test_main_learn_order.py."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from wd import dance, db
from wd.main import create_app
from wd.seed import import_seed

MINI_SEED = Path(__file__).resolve().parents[1] / "fixtures" / "mini_seed.jsonl"
SPEC = '{"version": 1, "letters": %s, "stress": 0, "marks": {"double": [], "silent": []}, "semantic": null, "source": "claude"}'


def _stored(conn, lemma: str, letters: str) -> None:
    word_id = conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0]
    dance_id = conn.execute(
        "INSERT INTO word_dances(word_id, status, spec_json, model, prompt_version, created_at) VALUES (?, 'active', ?, 'm', 'dance-v1', '2026-11-08T06:00:00Z')",
        (word_id, SPEC % letters),
    ).lastrowid
    conn.execute("UPDATE words SET active_dance_id = ?, dance_state = 'ready' WHERE id = ?", (dance_id, word_id))


def test_startup_fills_corrected_once_and_never_fails(settings, frozen_clock, caplog, monkeypatch):
    conn = db.connect(settings.db_path)
    try:
        db.run_migrations(conn)
        import_seed(conn, str(MINI_SEED))
        with db.tx(conn):
            _stored(conn, "happy", '["hap", "py"]')  # the rule cut: confirmed
            _stored(conn, "apple", '["a", "pple"]')  # not the rule cut (ap·ple): corrected
            conn.execute("UPDATE word_dances SET corrected = NULL")  # the state 0017 leaves behind
    finally:
        conn.close()

    with caplog.at_level(logging.INFO, logger="wd.main"):
        with TestClient(create_app(settings, clock=frozen_clock, configure_logs=False)) as c:
            assert c.get("/api/health").status_code == 200
    hits = [r for r in caplog.records if "word_dances.corrected backfilled for 2 row(s)" in r.getMessage()]
    assert len(hits) == 1 and getattr(hits[0], "event", None) == "dance_corrected_backfill"
    conn = db.connect(settings.db_path)
    try:
        rows = {r[0]: r[1] for r in conn.execute("SELECT w.lemma, d.corrected FROM word_dances d JOIN words w ON w.id = d.word_id")}
        assert rows == {"happy": 0, "apple": 1}
        apple = dict(conn.execute("SELECT * FROM words WHERE lemma = 'apple'").fetchone())
        assert dance.spec_for_word(conn, apple)["letters"] == ["a", "pple"]  # the model's correction keeps serving
        happy = dict(conn.execute("SELECT * FROM words WHERE lemma = 'happy'").fetchone())
        assert dance.spec_for_word(conn, happy)["letters"] == ["hap", "py"] and dance.spec_for_word(conn, happy)["source"] == "claude"
    finally:
        conn.close()

    # a second start: nothing left to fill, no log line
    caplog.clear()
    frozen_clock.advance(hours=1)
    with caplog.at_level(logging.INFO, logger="wd.main"):
        with TestClient(create_app(settings, clock=frozen_clock, configure_logs=False)) as c:
            assert c.get("/api/health").status_code == 200
    assert not any("word_dances.corrected backfill" in r.getMessage() for r in caplog.records)  # neither a fill nor a failure

    # a failing backfill is logged and the service still starts
    def boom(_conn):
        raise RuntimeError("no shape fits")

    monkeypatch.setattr(dance, "backfill_corrected", boom)
    with caplog.at_level(logging.ERROR, logger="wd.main"):
        with TestClient(create_app(settings, clock=frozen_clock, configure_logs=False)) as c:
            assert c.get("/api/health").status_code == 200
    assert any("word_dances.corrected backfill failed" in r.getMessage() for r in caplog.records)
