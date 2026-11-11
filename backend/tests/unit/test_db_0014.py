"""0014_learn_rank.sql (docs/analysis/2026-11-06-learn-order/DESIGN.md §2.2, §4.1 items 19–20): one nullable INTEGER column
appended to words without a rebuild — existing rows NULL, no index, table set / v_bank / row counts unchanged, the pre-0014
explicit-column INSERTs still work, idempotent, the fresh path — and the fail-soft order: with NULL keys every list site serves
exactly the pre-0014 frequency order inside each stage-distance group, and after a fill a NULL-ed row sorts after every ranked
row of its group (the sites' ORDER BY is lane C's; the contract is DESIGN §2.3)."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from wd import db, seed
from wd.ai import prewarm
from wd.schemas import STAGE_ORDER, stage_to_index
from wd.services import batches, learn_order, screen, words

from test_db import EXPECTED_TABLES  # sibling module (pytest prepend import mode, like test_db_0013)

MINI_SEED = Path(__file__).resolve().parents[1] / "fixtures" / "mini_seed.jsonl"
NULL_DISTANCE = 2 * len(STAGE_ORDER) + 1  # DESIGN §1.3 M4: a NULL stage_min sorts beyond every stage (11)


def _schema_dir_up_to(tmp_path: Path, last_version: int) -> Path:
    d = tmp_path / f"upto{last_version}"
    d.mkdir()
    for mf in db.list_migration_files():
        if mf.version <= last_version:
            shutil.copy(mf.path, d / mf.path.name)
    return d


def _old_insert_word_sql() -> str:
    """``words._INSERT_WORD_SQL`` as the pre-0014 code wrote it: the same column list minus ``learn_rank``."""
    cols = [c for c in words._INSERT_WORD_COLUMNS if c != "learn_rank"]
    return f"INSERT INTO words({', '.join(cols)}, created_at, updated_at) VALUES ({', '.join(':' + c for c in cols)}, :now, :now) ON CONFLICT(lemma) DO NOTHING"


def _ecdict_like_row(lemma: str, frq: int | None) -> dict:
    return {**words._word_defaults(), "lemma": lemma, "display": lemma, "kind": "word", "frq": frq, "source": "ecdict", "is_public": 1, "is_valid_english": 1, "safe_for_sharing": 1, "now": "2026-11-06T00:00:00Z"}


# ----------------------------------------------------------------------------------------- 19 the upgrade
def test_upgrade_0014_adds_a_nullable_column_without_rebuild(settings, tmp_path: Path):
    c = db.connect(settings.db_path)
    try:
        result = db.run_migrations(c, migrations_dir=_schema_dir_up_to(tmp_path, 13))
        assert result.applied[-1] == (13, "word_forms_alias") and db.current_version(c) == 13
        # rows written by the pre-0014 statements (the seed UPSERT names its columns; the resolver's INSERT without learn_rank)
        now = "2026-11-06T00:00:00Z"
        rows = [seed.seed_row({"word": "go", "frq": 35, "stages": ["xs", "zk"]}, now), seed.seed_row({"word": "a.m.", "stages": ["zk"]}, now)]
        c.executemany(seed._UPSERT_SQL, rows)
        c.execute(_old_insert_word_sql(), _ecdict_like_row("ubiquitous", 9000))
        c.execute("INSERT INTO users(id, username, password_hash) VALUES (1, 'alice', '$2b$12$x')")
        c.execute("INSERT INTO user_settings(user_id, next_push_at) VALUES (1, '2026-11-07T00:00:00Z')")
        c.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (1, (SELECT id FROM words WHERE lemma = 'go'), 'new', 'browse')")
        before_tables = set(db.table_names(c))
        before_cols = [r["name"] for r in c.execute("PRAGMA table_info(words)")]
        before_indexes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'words'")}
        before_counts = {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in before_tables}
        before_bank = c.execute("SELECT COUNT(*) FROM v_bank").fetchone()[0]
        before_words = [tuple(r) for r in c.execute("SELECT * FROM words ORDER BY id")]
        assert "learn_rank" not in before_cols and before_bank == 1

        result = db.run_migrations(c)  # the same call as `wd migrate` / the service startup

        assert result.applied[0] == (14, "learn_rank") and db.current_version(c) >= 14  # later additive files (0015 …) ride along
        assert not c.in_transaction and c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        cols = {r["name"]: r for r in c.execute("PRAGMA table_info(words)")}
        assert [r["name"] for r in c.execute("PRAGMA table_info(words)")] == [*before_cols, "learn_rank", "active_dance_id", "dance_state"]  # appended (0014, then 0016), nothing else moved
        col = cols["learn_rank"]
        assert (col["type"], col["notnull"], col["dflt_value"], col["pk"]) == ("INTEGER", 0, None, 0)
        assert c.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL").fetchone()[0] == 0  # NULL = not computed yet
        assert [tuple(r)[: len(before_cols)] for r in c.execute("SELECT * FROM words ORDER BY id")] == before_words  # every value survived
        assert {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'words'")} == before_indexes
        assert "ix_words_learn_rank" not in before_indexes
        assert set(db.table_names(c)) == before_tables | {"word_dances", "identities", "login_codes", "family_codes", "wechat_tickets"} == EXPECTED_TABLES  # 0016 adds word_dances, 0018 identities / login_codes, 0019 family_codes, 0020 wechat_tickets on the way
        assert db.view_names(c) == ["v_bank"] and c.execute("SELECT COUNT(*) FROM v_bank").fetchone()[0] == before_bank
        assert {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in before_tables if t != "schema_migrations"} == {t: n for t, n in before_counts.items() if t != "schema_migrations"}
        last = c.execute("SELECT kind FROM system_events ORDER BY id DESC LIMIT 1").fetchone()
        assert last is None or last[0] != "learn_order_recomputed"  # the migration computes nothing: the service start / `wd learn-order` fills
        # the old explicit-column statements still succeed (a rolled-back server keeps writing); the new one too
        c.executemany(seed._UPSERT_SQL, [seed.seed_row({"word": "cat", "frq": 1775, "stages": ["xs", "zk"]}, now)])
        c.execute(_old_insert_word_sql(), _ecdict_like_row("oldstyle", 100))
        c.execute(words._INSERT_WORD_SQL, {**_ecdict_like_row("newstyle", 100), "learn_rank": 10000})
        assert c.execute("SELECT learn_rank FROM words WHERE lemma = 'oldstyle'").fetchone()[0] is None
        assert c.execute("SELECT learn_rank FROM words WHERE lemma = 'newstyle'").fetchone()[0] == 10000
        c.execute("UPDATE words SET learn_rank = NULL WHERE lemma = 'newstyle'")  # NULL is a legal state
        assert db.run_migrations(c).applied == []  # idempotent
    finally:
        c.close()


def test_fresh_database_has_the_learn_rank_column(conn):
    assert (14, "learn_rank") in [(r[0], r[1]) for r in conn.execute("SELECT version, name FROM schema_migrations")]
    assert db.current_version(conn) >= learn_order.LEARN_ORDER_FROM_VERSION == 14
    col = next(r for r in conn.execute("PRAGMA table_info(words)") if r["name"] == "learn_rank")
    assert (col["type"], col["notnull"], col["dflt_value"]) == ("INTEGER", 0, None)
    conn.execute("INSERT INTO words(lemma, display, source, learn_rank) VALUES ('go', 'go', 'seed', 3500)")
    conn.execute("INSERT INTO words(lemma, display, source) VALUES ('tv', 'TV', 'seed')")
    assert [tuple(r) for r in conn.execute("SELECT lemma, learn_rank FROM words ORDER BY lemma")] == [("go", 3500), ("tv", None)]
    assert db.view_names(conn) == ["v_bank"] and "learn_rank" not in (conn.execute("SELECT sql FROM sqlite_master WHERE name = 'v_bank'").fetchone()[0])


# -------------------------------------------------------------------------------------- 20 the fail-soft order
def frq_key(row: sqlite3.Row) -> tuple:
    """The pre-0014 ``ORDER BY (frq IS NULL OR frq = 0), frq, lemma`` as Python (SQLite sorts NULL before 0 inside the unknown bucket)."""
    frq = row["frq"]
    return (frq is None or frq == 0, frq is not None, frq or 0, row["lemma"])


def distance(stage_min: int | None, cur: int) -> int:
    """DESIGN §1.3 M4 written out (not the module's twin: the test computes its expectation on its own)."""
    if stage_min is None:
        return NULL_DISTANCE
    if stage_min == cur:
        return 0
    return 2 * (stage_min - cur) - 1 if stage_min > cur else 2 * (cur - stage_min)


def expected(conn: sqlite3.Connection, where: str, params: dict, *, cur: int | None) -> list[str]:
    rows = conn.execute(f"SELECT lemma, frq, stage_min FROM words w WHERE {where}", params).fetchall()
    key = (lambda r: (distance(r["stage_min"], cur), *frq_key(r))) if cur is not None else frq_key
    return [str(r["lemma"]) for r in sorted(rows, key=key)]


def make_user(conn: sqlite3.Connection, stages_json: str, current_stage: int) -> int:
    cur = conn.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES ('pupil-db', 'x', 'done')")
    uid = int(cur.lastrowid)
    conn.execute("INSERT INTO user_settings(user_id, next_push_at, stages_json, current_stage, daily_screen_count) VALUES (?, '2026-11-07T00:00:00Z', ?, ?, 50)", (uid, stages_json, current_stage))
    return uid


def test_null_ranks_fall_back_to_the_pre_0014_order(seeded):
    """Migrated, unfilled: the column is there (the import hook ranked the rows — NULL them) and every site's order is exactly the
    frequency order inside its stage-distance group — the moment between `wd migrate` and the first fill serves today's lists."""
    conn = seeded
    conn.execute("UPDATE words SET learn_rank = NULL")
    xs = stage_to_index("xs")
    # 筛词: distance from the 主攻 stage first, then the frequency order
    uid = make_user(conn, '["xs","zk","gk"]', xs)
    items, remaining = screen.screen_next(conn, uid, "auto", 100)
    candidates = "w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND (w.stage_xs = 1 OR w.stage_zk = 1 OR w.stage_gk = 1)"
    assert [i["word"]["lemma"] for i in items] == expected(conn, candidates, {}, cur=xs) and remaining == len(items) > 30
    items, _ = screen.screen_next(conn, uid, "zk", 100)
    assert [i["word"]["lemma"] for i in items] == expected(conn, "w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.stage_zk = 1", {}, cur=stage_to_index("zk"))
    # 每日推荐词 (the selection's screens)
    settings_row = {"timezone": "Asia/Shanghai", "max_reviews": 0, "daily_new_count": 0, "daily_screen_count": 50, "stages": ["xs", "zk", "gk"], "current_stage": xs}
    screens = [str(s["lemma"]) for s in batches.select_words(conn, uid, settings_row, "2026-11-06").screens]
    assert screens == expected(conn, candidates, {}, cur=xs)[:50]
    # admin 预生成 candidates of one stage (a single distance group)
    ids = prewarm.candidates(conn, "xs", 100)
    lemmas = {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, lemma FROM words")}
    assert [lemmas[i] for i in ids] == expected(conn, "w.stage_xs = 1 AND w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.content_state IN ('none','failed')", {}, cur=None)
    # the ORDER_SQL fragment itself over 全部 with the 小学-first prefix (cur = 1 ≡ COALESCE(stage_min, 6) ascending): 课标外 last
    order = f"{learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL}"
    got = [str(r[0]) for r in conn.execute(f"SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.merged_into_word_id IS NULL ORDER BY {order}", {"cur": learn_order.default_cur("all")})]
    assert got == expected(conn, "w.is_public = 1 AND w.merged_into_word_id IS NULL", {}, cur=1) and got[-1] == "bookshelf"


def test_vocab_tab_with_null_ranks_is_the_frequency_order(client, settings, seeded):
    """GET /api/vocab?stage=xs on the unfilled column: one distance group, the pre-0014 frequency order."""
    conn = seeded
    conn.execute("UPDATE words SET learn_rank = NULL")
    client.post("/api/auth/register", json={"username": "pupil", "password": "Passw0rd!xyz"})
    r = client.get("/api/vocab?stage=xs&page_size=100")
    assert r.status_code == 200, r.text
    assert [i["lemma"] for i in r.json()["items"]] == expected(conn, "w.stage_xs = 1 AND w.is_public = 1 AND w.merged_into_word_id IS NULL", {}, cur=None)
    assert "learn_rank" not in r.json()["items"][0]  # the key is never exposed (WordBrief unchanged)


def test_null_rank_sorts_after_every_ranked_row_of_its_group_at_the_sites(client, settings, seeded):
    """DESIGN §2.3 (lane C's ORDER BY sites): the 全部 tab groups by the 小学-first stage distance, and after a fill a NULL-ed key
    sends the row behind every ranked row of its distance group — at 词库, 筛词, 推荐词 and prewarm alike."""
    conn = seeded
    assert conn.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NULL").fetchone()[0] == 0  # the import hook filled the column
    client.post("/api/auth/register", json={"username": "pupil", "password": "Passw0rd!xyz"})
    body = client.get("/api/vocab?page_size=100").json()
    visible = "w.is_public = 1 AND w.merged_into_word_id IS NULL"
    ranked = [str(r[0]) for r in conn.execute(f"SELECT w.lemma FROM words w WHERE {visible} ORDER BY {learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL}", {"cur": 1})]
    assert [i["lemma"] for i in body["items"]] == ranked and ranked[-1] == "bookshelf"  # 全部: 小学 course first, 课标外 last
    # go is the first 初中新增 word (natively ranked); without its key it drops behind every ranked 初中新增 word, before the 小学 ones
    conn.execute("UPDATE words SET learn_rank = NULL WHERE lemma = 'go'")
    zk = stage_to_index("zk")
    tab = [i["lemma"] for i in client.get("/api/vocab?stage=zk&page_size=100").json()["items"]]
    own = [l for l in tab if conn.execute("SELECT stage_min FROM words WHERE lemma = ?", (l,)).fetchone()[0] == zk]
    assert own[-1] == "go" and own[0] != "go" and tab.index("go") < tab.index("take")  # last of its group (distance 0), before the 小学 words (distance 2)
    uid = make_user(conn, '["zk"]', zk)
    items, _ = screen.screen_next(conn, uid, "auto", 100)
    lemmas = [i["word"]["lemma"] for i in items]
    assert [l for l in lemmas if conn.execute("SELECT stage_min FROM words WHERE lemma = ?", (l,)).fetchone()[0] == zk][-1] == "go"
    settings_row = {"timezone": "Asia/Shanghai", "max_reviews": 0, "daily_new_count": 0, "daily_screen_count": 100, "stages": ["zk"], "current_stage": zk}
    screens = [str(s["lemma"]) for s in batches.select_words(conn, uid, settings_row, "2026-11-06").screens]
    assert screens == lemmas
    ids = prewarm.candidates(conn, "zk", 100)
    names = {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, lemma FROM words")}
    assert [names[i] for i in ids] == lemmas
    with pytest.raises(ValueError):
        prewarm.candidates(conn, "cet9", 1)
