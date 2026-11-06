"""The learning-order SQL against its Python twin (docs/analysis/2026-11-06-learn-order/DESIGN.md §4.1 items 11–12, §2.3).

On the seeded mini seed — filled inside the test with ``rank_rows(*load_inputs(conn))`` + ``UPDATE`` (what ``recompute`` writes; lane B's
half is not imported) — every ORDER BY site returns exactly ``reference_order(...)``, the stored column sorted in Python: 词库 全部 and each
stage tab (``routers/vocab.py``), the ``difficulty`` sort, 筛词 over the ``alice`` stage set (``services/screen.py``), 推荐词
(``services/batches.py``) and the admin 预生成 candidates (``ai/prewarm.py``) — before the fill (every ``learn_rank`` NULL: the fail-soft
pre-0014 order inside each stage-distance group) and after it. Plus the two grep pins: no ``hash(`` in ``learn_order.py``, the literal
``frq IS NULL`` only there, and ``_STAGE_DISTANCE`` gone from ``backend/wd`` (M4 unification)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from reference_order import order_key, reference_order
from wd import db, schemas
from wd.ai import prewarm
from wd.routers import vocab
from wd.schemas import STAGE_ORDER, stage_to_index
from wd.services import bank, batches, learn_order, screen
from wd.services.learn_order import load_inputs, rank_rows

WD_DIR = Path(__file__).resolve().parents[2] / "wd"  # backend/wd
ME = {"id": 1, "role": "user"}  # routers/vocab.py: a plain user's visibility rule (is_public OR own OR in the bank) — no own words here
TODAY = "2026-10-14"
PREWARM_WHERE = (
    "w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.content_state IN ('none','failed') AND {stage} "
    "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.dedupe_key = 'content:' || w.id AND j.status IN ('queued','running'))"
)


# ------------------------------------------------------------------------------------------- helpers
def fill_ranks(conn: sqlite3.Connection) -> dict[int, int | None]:
    """``learn_rank := rank_rows(*load_inputs(conn))`` for every row — the write ``learn_order.recompute`` performs, done here so the
    differential never depends on lane B's half."""
    result = rank_rows(*load_inputs(conn))
    with db.tx(conn):
        conn.executemany("UPDATE words SET learn_rank = ? WHERE id = ?", [(rank, wid) for wid, rank in result.ranks.items()])
    return result.ranks


def make_user(conn: sqlite3.Connection, username: str, *, stages: list[str], current_stage: int, daily_screen_count: int = 50) -> int:
    cur = conn.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES (?, 'x', 'done')", (username,))
    uid = int(cur.lastrowid)
    conn.execute(
        "INSERT INTO user_settings(user_id, stages_json, current_stage, daily_screen_count) VALUES (?, ?, ?, ?)",
        (uid, json.dumps(stages), current_stage, daily_screen_count),
    )
    return uid


def vocab_form(conn: sqlite3.Connection, *, stage: str = "all", sort: str = "freq") -> tuple[list[str], str, dict, int]:
    """``(lemmas, where, params, cur)`` of endpoint 20 composed from the router's own pieces, exactly as ``vocab()`` does."""
    q = schemas.VocabQuery(stage=stage, sort=sort)
    where, params = vocab.vocab_filters(ME, q, with_letter_and_q=True)
    params["cur"] = learn_order.default_cur(q.stage)
    lemmas = [r[0] for r in conn.execute(f"SELECT w.lemma {vocab._FROM} WHERE {where} ORDER BY {vocab._order_sql(sort)}", params)]
    return lemmas, where, params, params["cur"]


def difficulty_reference(conn: sqlite3.Connection, where: str, params: dict) -> list[str]:
    """Python twin of the ``difficulty`` sort: ``COALESCE(difficulty + 1, stage_min, 6)`` then ``ORDER_SQL`` (``order_key`` without a cur)."""
    rows = conn.execute(f"SELECT w.lemma, w.stage_min, w.learn_rank, w.frq, w.difficulty FROM words w WHERE {where}", params).fetchall()
    tier = lambda r: (r["difficulty"] + 1) if r["difficulty"] is not None else (r["stage_min"] if r["stage_min"] is not None else 6)
    return [r["lemma"] for r in sorted(rows, key=lambda r: (tier(r), order_key(r, None)))]


def screen_pool(stages: list[str]) -> str:
    """The WHERE of ``screen._candidate_sql`` (the 筛词 pool) for ``reference_order``: its body without ``FROM words w WHERE``."""
    return screen._candidate_sql(stages).split(" WHERE ", 1)[1]


def every_site(conn: sqlite3.Connection, alice: int, pupil: int, id_lemma: dict[int, str]) -> dict[str, tuple[list[str], list[str]]]:
    """``name → (SQL order, reference order)`` for every ORDER BY site of DESIGN §2.3 in one database state."""
    out: dict[str, tuple[list[str], list[str]]] = {}
    # 1 词库 — 全部 (cur 1 → the 小学 course first, 课标外 last) and each stage tab with its own index as cur (G6)
    lemmas, where, params, cur = vocab_form(conn)
    out["vocab all"] = (lemmas, reference_order(conn, where, cur=cur, params=params))
    for stage in STAGE_ORDER:
        lemmas, where, params, cur = vocab_form(conn, stage=stage)
        assert cur == stage_to_index(stage)
        out[f"vocab {stage}"] = (lemmas, reference_order(conn, where, cur=cur, params=params))
    lemmas, where, params, _ = vocab_form(conn, sort="difficulty")
    out["vocab difficulty"] = (lemmas, difficulty_reference(conn, where, params))
    # 2 筛词 — alice's set (cet4+cet6, 主攻 cet6) through the service, the explicit 初中 filter, and the pupil (xs+zk+gk, 主攻 xs)
    items, remaining = screen.screen_next(conn, alice, "auto", 500)
    got = [i["word"]["lemma"] for i in items]
    assert remaining == len(got) > 1
    out["screen alice auto"] = (got, reference_order(conn, screen_pool(["cet4", "cet6"]), cur=5, params={"me": alice}))
    items, _ = screen.screen_next(conn, alice, "zk", 500)
    out["screen alice zk"] = ([i["word"]["lemma"] for i in items], reference_order(conn, screen_pool(["zk"]), cur=2, params={"me": alice}))
    items, _ = screen.screen_next(conn, pupil, "auto", 500)
    out["screen pupil auto"] = ([i["word"]["lemma"] for i in items], reference_order(conn, screen_pool(["xs", "zk", "gk"]), cur=1, params={"me": pupil}))
    # 3 推荐词 — select_words' screens for alice (capped by daily_screen_count, 50 = the DDL maximum) open the 筛词 order
    sel = batches.select_words(conn, alice, bank.user_settings_row(conn, alice), TODAY)
    got = [str(s["lemma"]) for s in sel.screens]
    want = out["screen alice auto"][1]
    assert len(got) == min(50, len(want)) > 1
    out["batches screens alice"] = (got, want[: len(got)])
    # 4 prewarm — every stage and `all` (cur = the stage's index, 1 for all)
    for stage in prewarm.STAGES:
        got = [id_lemma[i] for i in prewarm.candidates(conn, stage, 10_000)]
        want = reference_order(conn, PREWARM_WHERE.format(stage=prewarm._stage_sql(stage)), cur=learn_order.default_cur(stage))
        out[f"prewarm {stage}"] = (got, want)
    return out


# ------------------------------------------------------------------------------------------- item 11
def test_sql_order_equals_python_order(seeded):
    conn = seeded
    alice = make_user(conn, "alice", stages=["cet4", "cet6"], current_stage=5)
    pupil = make_user(conn, "pupil", stages=["xs", "zk", "gk"], current_stage=1)
    id_lemma = {int(r[0]): str(r[1]) for r in conn.execute("SELECT id, lemma FROM words")}
    n = len(id_lemma)
    # a few difficulty values so the COALESCE prefix of the difficulty sort has every branch (Claude's 1–5 scale, PLAN R-2)
    some = [r[0] for r in conn.execute("SELECT id FROM words ORDER BY id LIMIT 3")]
    conn.execute("UPDATE words SET difficulty = 1 WHERE id = ?", (some[0],))
    conn.execute("UPDATE words SET difficulty = 5 WHERE id = ?", (some[1],))
    conn.execute("UPDATE words SET content_state = 'ready' WHERE id = ?", (some[2],))  # one prewarm candidate less
    # --- the fail-soft state: every learn_rank NULL (0014 applied, nothing computed yet — the import's own recompute is undone here so
    # the test owns both states) — the pre-0014 frequency order inside each stage-distance group
    with db.tx(conn):
        conn.execute("UPDATE words SET learn_rank = NULL")
    assert conn.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NULL").fetchone()[0] == n
    before = every_site(conn, alice, pupil, id_lemma)
    for name, (got, want) in before.items():
        assert got == want, name
        assert len(got) > 1, name
    # --- the filled state
    ranks = fill_ranks(conn)
    assert len(ranks) == n and conn.execute("SELECT COUNT(*) FROM words WHERE learn_rank IS NULL").fetchone()[0] == sum(r is None for r in ranks.values())
    after = every_site(conn, alice, pupil, id_lemma)
    assert after.keys() == before.keys()
    for name, (got, want) in after.items():
        assert got == want, name
        if not name.startswith("batches"):  # the capped 推荐词 probe truncates two different orders; every other site lists its whole pool
            assert sorted(got) == sorted(before[name][0]), name  # the same pool, only its order moved
    assert after["vocab all"][0] != before["vocab all"][0]  # the fill is not a no-op on the mini seed (closed words leave the head)
    # NULL-ing one stored key puts that row after every ranked row of its stage-distance group, by the frequency tail (R4)
    head = after["vocab all"][0][0]
    with db.tx(conn):
        conn.execute("UPDATE words SET learn_rank = NULL WHERE lemma = ?", (head,))
    lemmas, where, params, cur = vocab_form(conn)
    assert lemmas == reference_order(conn, where, cur=cur, params=params) and lemmas[0] != head
    stage_min = conn.execute("SELECT stage_min FROM words WHERE lemma = ?", (head,)).fetchone()[0]
    group = [r[0] for r in conn.execute("SELECT lemma FROM words WHERE stage_min IS ? AND is_public = 1 AND merged_into_word_id IS NULL", (stage_min,))]
    assert lemmas.index(head) == max(lemmas.index(l) for l in group)  # last of its group


# ------------------------------------------------------------------------------------------- item 12
def test_no_salted_hash_and_one_frq_fragment():
    files = sorted(p for p in WD_DIR.rglob("*") if p.is_file() and p.suffix in {".py", ".sql"} and "__pycache__" not in p.parts)
    assert len(files) > 20
    module = WD_DIR / "services" / "learn_order.py"
    assert module in files
    assert "hash(" not in module.read_text(encoding="utf-8")  # the key is a group computation, never a salted hash (DESIGN §2.1)
    texts = {p.relative_to(WD_DIR).as_posix(): p.read_text(encoding="utf-8") for p in files}
    assert {rel for rel, text in texts.items() if "frq IS NULL" in text} == {"services/learn_order.py"}  # one frequency fragment (FRQ_TAIL)
    assert [rel for rel, text in texts.items() if "_STAGE_DISTANCE" in text] == []  # M4 unification: stage_distance_sql() is the one copy
    for rel in ("routers/vocab.py", "services/screen.py", "services/batches.py", "ai/prewarm.py"):
        assert "learn_order.stage_distance_sql()" in texts[rel] and "learn_order.ORDER_SQL" in texts[rel], rel
    assert "learn_order.FRQ_TAIL" in texts["routers/words.py"] and "learn_order.ORDER_SQL" not in texts["routers/words.py"]  # the autocomplete exception
