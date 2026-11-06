"""services/batches.py (WP4) on the mini seed: ordering helpers pinned by batch_order.json, build_batch (caps, ordering,
cold start, idempotency under concurrency, provisional exclusion, content enqueue), preview_selection, append_to_today,
add_more, hide_stale, publish/finalize, and the grade_item edge cases — directly against the service (no HTTP)."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from reference_order import reference_order
from wd import db
from wd.errors import ApiError
from wd.jobs import queue
from wd.services import bank, batches, screen

UTC = timezone.utc
TZ = "Asia/Shanghai"
NOW = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)  # 09:00 Shanghai → local date 2026-10-14
TODAY = "2026-10-14"
FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "batch_order.json").read_text(encoding="utf-8"))

# mini-seed lemmas whose first four letters are all distinct (so spread_similar leaves the interleave pattern alone)
DISTINCT = [
    "ability", "apple", "bank", "base", "better", "book", "cat", "child", "China", "clothes", "computer", "decide", "dog", "email",
    "glass", "good", "happy", "house", "mountain", "person", "receive", "study", "take", "teacher", "water", "abandon", "abnormal",
    "aboard", "abolish", "abrupt", "absence", "absolute", "abstract", "absurd", "abundant", "analysis", "basis", "data", "negotiate",
]


# ------------------------------------------------------------------------------------------- helpers
def make_user(conn: sqlite3.Connection, username: str = "alice", **cols) -> int:
    cur = conn.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES (?, 'x', 'done')", (username,))
    uid = int(cur.lastrowid)
    cols.setdefault("next_push_at", "2026-10-15T00:00:00Z")
    names = ["user_id", *cols]
    conn.execute(f"INSERT INTO user_settings({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", (uid, *cols.values()))
    return uid


def wid(conn: sqlite3.Connection, lemma: str) -> int:
    return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma.lower(),)).fetchone()[0])


def mark(conn, uid, lemma, action="unfamiliar", *, now=NOW, context="browse"):
    return bank.apply_action(conn, uid, wid(conn, lemma), action, origin=bank.origin_for_context(context), context=context, now=now, tz=TZ)


def make_learning(conn, uid, lemma, *, due_at: str, interval=3, ease=2.5, now=NOW) -> int:
    mark(conn, uid, lemma, now=now - timedelta(days=5))
    conn.execute(
        "UPDATE user_words SET state = 'learning', due_at = ?, interval_days = ?, ease = ?, repetitions = 2, step = 0 WHERE user_id = ? AND word_id = ?",
        (due_at, interval, ease, uid, wid(conn, lemma)),
    )
    return int(conn.execute("SELECT id FROM user_words WHERE user_id = ? AND word_id = ?", (uid, wid(conn, lemma))).fetchone()[0])


def items_of(conn, batch_id) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT pi.*, w.lemma FROM push_items pi JOIN words w ON w.id = pi.word_id WHERE batch_id = ? ORDER BY position", (batch_id,))]


def count(conn, sql, params=()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


# the 推荐词 pool of the `user` fixture (目标 cet4+cet6): the screens WHERE of batches.select_words / add_more
SCREEN_POOL = (
    "is_public = 1 AND merged_into_word_id IS NULL AND is_valid_english = 1 AND (stage_cet4 = 1 OR stage_cet6 = 1) "
    "AND NOT EXISTS (SELECT 1 FROM user_words uw WHERE uw.user_id = :me AND uw.word_id = w.id)"
)


def screen_order(conn, user: int) -> list[str]:
    """The 推荐词 order of the fixture's CET-4 learner: 主攻阶段 cet4 (stage index 4) first, then the learning order of the stored
    learn_rank with the frequency tail (DESIGN §6.3 step 4) — read from the column, never a lemma list of the seed."""
    return reference_order(conn, SCREEN_POOL, cur=4, params={"me": user})


@pytest.fixture
def user(seeded):
    # the K-12 DDL defaults (0011: xs+zk, 主攻 xs) would pick 小学 words as 推荐词; these ordering tests pin the CET-4 learner they
    # were written for explicitly (stage index 4 = cet4 since the renumbering)
    return make_user(seeded, stages_json='["cet4","cet6"]', current_stage=4)


# ------------------------------------------------------------------------------------- pure ordering
@pytest.mark.parametrize("case", FIXTURE["interleave"], ids=[c["note"] for c in FIXTURE["interleave"]])
def test_interleave_fixture(case):
    assert batches.interleave(case["reviews"], case["news"]) == case["expected"]


@pytest.mark.parametrize("case", FIXTURE["spread_similar"], ids=[c["note"] for c in FIXTURE["spread_similar"]])
def test_spread_similar_fixture(case):
    assert batches.spread_similar(case["input"]) == case["expected"]


def test_interleave_26_10_is_rrrn_times_8_then_rrnn():
    out = batches.interleave([f"R{i}" for i in range(1, 27)], [f"N{i}" for i in range(1, 11)])
    pattern = "".join(x[0] for x in out)
    assert pattern == "RRRN" * 8 + "RRNN"


def test_spread_similar_moves_abandon_away_from_abandoned_like_prefixes():
    out = batches.spread_similar(["abandoned", "abandon", "apple", "bank", "cat"])
    assert out.index("abandon") - out.index("abandoned") >= 3
    assert sorted(out) == sorted(["abandoned", "abandon", "apple", "bank", "cat"])
    with_key = batches.spread_similar([{"lemma": "abandoned"}, {"lemma": "abandon"}, {"lemma": "apple"}, {"lemma": "bank"}, {"lemma": "cat"}], key=lambda d: d["lemma"])
    assert [d["lemma"] for d in with_key] == out
    assert batches.similar("abandon", "abandoned") and not batches.similar("go", "goal") and not batches.similar("base", "basis")


# ------------------------------------------------------------------------------------------ building
def test_build_batch_caps_ordering_and_counts(seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET max_reviews = 2, daily_new_count = 3, daily_screen_count = 2 WHERE user_id = ?", (user,))
    # 4 due reviews (most overdue first), one not yet due
    make_learning(conn, user, "apple", due_at="2026-10-12T16:00:00Z")
    make_learning(conn, user, "bank", due_at="2026-10-10T16:00:00Z")
    make_learning(conn, user, "book", due_at="2026-10-13T16:00:00Z")
    make_learning(conn, user, "cat", due_at="2026-10-14T10:00:00Z")  # later today → due (< day end 16:00Z)
    make_learning(conn, user, "dog", due_at="2026-10-14T16:00:00Z")  # tomorrow → not due
    # 4 new words: a stubborn one (times_added 3) first, then priority desc, then added_at asc
    mark(conn, user, "glass", now=NOW - timedelta(hours=4))
    mark(conn, user, "house", now=NOW - timedelta(hours=3))
    mark(conn, user, "happy", now=NOW - timedelta(hours=2))
    mark(conn, user, "water", now=NOW - timedelta(hours=1))
    conn.execute("UPDATE user_words SET times_added = 3 WHERE user_id = ? AND word_id = ?", (user, wid(conn, "water")))
    conn.execute("UPDATE user_words SET priority = 100 WHERE user_id = ? AND word_id = ?", (user, wid(conn, "happy")))
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert b.created and b.status == "building" and b.trigger == "manual" and b.timezone == TZ
    assert (b.review_count, b.new_count, b.screen_count, b.deferred_reviews) == (2, 3, 2, 2)
    rows = items_of(conn, b.id)
    reviews = [r["lemma"] for r in rows if r["kind"] == "review"]
    news = [r["lemma"] for r in rows if r["kind"] == "new"]
    screens = [r["lemma"] for r in rows if r["kind"] == "screen"]
    assert reviews == ["bank", "apple"]  # most overdue first, capped at 2
    assert news == ["water", "happy", "glass"]  # stubborn, then priority 100, then oldest added_at
    assert screens == screen_order(conn, user)[:2]  # 主攻阶段 cet4 (stage_min 4) first, then the learning order (the stored learn_rank)
    assert [r["kind"] for r in rows][:5] == ["review", "new", "review", "new", "new"]  # k = ceil(2/3) = 1 → R N R N, then the rest
    assert [r["position"] for r in rows] == list(range(len(rows)))
    assert all(r["user_word_id"] is not None for r in rows if r["kind"] != "screen") and all(r["user_word_id"] is None for r in rows if r["kind"] == "screen")
    pushed = {r[0]: r[1] for r in conn.execute("SELECT w.lemma, uw.times_pushed FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ?", (user,))}
    assert pushed["bank"] == pushed["apple"] == pushed["water"] == 1 and pushed["book"] == pushed["dog"] == 0
    snapshot = json.loads(conn.execute("SELECT settings_json FROM push_batches WHERE id = ?", (b.id,)).fetchone()[0])
    assert snapshot["max_reviews"] == 2 and snapshot["daily_new_count"] == 3


def test_build_batch_interleave_pattern_on_real_rows(seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET max_reviews = 60, daily_new_count = 10, daily_screen_count = 0 WHERE user_id = ?", (user,))
    for i, lemma in enumerate(DISTINCT[:26]):
        make_learning(conn, user, lemma, due_at=f"2026-10-{10 + i % 4:02d}T16:00:00Z")
    for i, lemma in enumerate(DISTINCT[26:36]):
        mark(conn, user, lemma, now=NOW - timedelta(hours=10 - i))
    b = batches.build_batch(conn, user, TODAY, "scheduled", NOW)
    pattern = "".join("R" if r["kind"] == "review" else "N" for r in items_of(conn, b.id))
    assert pattern == "RRRN" * 8 + "RRNN"
    assert (b.review_count, b.new_count, b.screen_count) == (26, 10, 0)


def test_build_batch_cold_start_puts_screens_first(seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 3 WHERE user_id = ?", (user,))
    b = batches.build_batch(conn, user, TODAY, "scheduled", NOW)
    rows = items_of(conn, b.id)
    assert [r["kind"] for r in rows] == ["screen", "screen", "screen"] and (b.review_count, b.new_count) == (0, 0)
    # with a core the 推荐词 come after it
    make_user(conn, "bob")
    bob = 2
    conn.execute("UPDATE user_settings SET daily_screen_count = 2 WHERE user_id = ?", (bob,))
    mark(conn, bob, "apple")
    b2 = batches.build_batch(conn, bob, TODAY, "scheduled", NOW)
    assert [r["kind"] for r in items_of(conn, b2.id)] == ["new", "screen", "screen"]


def test_build_batch_is_idempotent_and_concurrent_builders_get_one_batch(settings, seeded, user):
    conn = seeded
    mark(conn, user, "apple")
    first = batches.build_batch(conn, user, TODAY, "manual", NOW)
    again = batches.build_batch(conn, user, TODAY, "scheduled", NOW + timedelta(hours=1))
    assert again.id == first.id and again.created is False and again.trigger == "manual"
    assert count(conn, "SELECT COUNT(*) FROM push_batches WHERE user_id = ?", (user,)) == 1
    # two threads, two connections, a fresh date
    results: list[batches.Batch] = []
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def worker():
        c = db.connect(settings.db_path)
        try:
            start.wait()
            results.append(batches.build_batch(c, user, "2026-10-15", "scheduled", NOW + timedelta(days=1)))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        finally:
            c.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors and len(results) == 2
    assert results[0].id == results[1].id and sum(1 for r in results if r.created) == 1
    assert count(conn, "SELECT COUNT(*) FROM push_batches WHERE user_id = ? AND local_date = '2026-10-15'", (user,)) == 1
    assert count(conn, "SELECT COUNT(*) FROM push_items WHERE batch_id = ?", (results[0].id,)) == count(conn, "SELECT COUNT(DISTINCT word_id || kind) FROM push_items WHERE batch_id = ?", (results[0].id,))


def test_provisional_and_flagged_bank_words_are_excluded_from_news(seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 0 WHERE user_id = ?", (user,))
    conn.execute(
        "INSERT INTO words(lemma, display, kind, source, is_public, is_valid_english, safe_for_sharing, created_by_user_id) VALUES ('zzqx', 'zzqx', 'word', 'user', 0, NULL, NULL, ?)",
        (user,),
    )
    conn.execute(
        "INSERT INTO words(lemma, display, kind, source, is_public, is_valid_english, safe_for_sharing, created_by_user_id) VALUES ('qqzz', 'qqzz', 'word', 'user', 0, 0, 0, ?)",
        (user,),
    )
    for lemma in ("zzqx", "qqzz", "apple", "bank"):
        mark(conn, user, lemma)
    conn.execute("UPDATE user_words SET needs_attention = 1, attention_msg = '未识别为英文单词' WHERE user_id = ? AND word_id = ?", (user, wid(conn, "bank")))
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert [r["lemma"] for r in items_of(conn, b.id)] == ["apple"]
    assert b.new_count == 1


def test_content_enqueued_only_for_validated_words_lacking_content(seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 2 WHERE user_id = ?", (user,))
    mark(conn, user, "apple")  # the mark itself enqueued content:apple (priority 20)
    conn.execute("DELETE FROM jobs")
    conn.execute("UPDATE words SET content_state = 'none' WHERE lemma = 'apple'")
    s1, s2 = screen_order(conn, user)[:2]  # today's two 推荐词 (daily_screen_count 2)
    conn.execute("UPDATE words SET content_state = 'ready' WHERE lemma = ?", (s1,))  # screen word with content
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    lemmas = {r["lemma"] for r in items_of(conn, b.id)}
    assert lemmas == {"apple", s1, s2}
    jobs = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT dedupe_key, priority, status FROM jobs WHERE type = 'generate_content'")}
    assert jobs == {f"content:{wid(conn, 'apple')}": (20, "queued"), f"content:{wid(conn, s2)}": (20, "queued")}
    assert conn.execute("SELECT content_state FROM words WHERE lemma = 'apple'").fetchone()[0] == "queued"
    assert conn.execute("SELECT content_state FROM words WHERE lemma = ?", (s1,)).fetchone()[0] == "ready"
    # no fetch_image / other job types are created by the builder
    assert count(conn, "SELECT COUNT(*) FROM jobs WHERE type != 'generate_content'") == 0


def test_preview_selection_is_read_only_and_matches_the_build(seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 3, daily_new_count = 2 WHERE user_id = ?", (user,))
    mark(conn, user, "apple")
    mark(conn, user, "bank")
    mark(conn, user, "cat")
    conn.execute("DELETE FROM jobs")
    before = {t: count(conn, f"SELECT COUNT(*) FROM {t}") for t in ("push_batches", "push_items", "jobs", "user_words", "review_logs", "daily_stats")}
    pushed_before = conn.execute("SELECT SUM(times_pushed) FROM user_words").fetchone()[0]
    ids = batches.preview_selection(conn, user, TODAY, NOW)
    assert len(ids) == 5 and len(set(ids)) == 5
    after = {t: count(conn, f"SELECT COUNT(*) FROM {t}") for t in before}
    assert after == before and conn.execute("SELECT SUM(times_pushed) FROM user_words").fetchone()[0] == pushed_before
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert sorted(ids) == sorted(r["word_id"] for r in items_of(conn, b.id))


def test_today_response_without_a_batch_creates_nothing(settings, seeded, user):
    conn = seeded
    mark(conn, user, "apple")
    before = [count(conn, f"SELECT COUNT(*) FROM {t}") for t in ("push_batches", "push_items", "jobs")]
    r = batches.today_response(conn, user, NOW, cfg=settings)
    assert r["status"] == "none" and r["batch"] is None and r["can_build_now"] is True and r["previous_open_batch"] is None
    assert r["local_date"] == TODAY and r["push_time"] == "08:00" and r["next_push_at"] == "2026-10-15T00:00:00Z"
    assert [count(conn, f"SELECT COUNT(*) FROM {t}") for t in ("push_batches", "push_items", "jobs")] == before


# ---------------------------------------------------------------------------------------- appending
def test_append_to_today_rules(settings, seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 2, daily_new_count = 1 WHERE user_id = ?", (user,))
    mark(conn, user, "apple")
    assert batches.append_to_today(conn, user, wid(conn, "apple"), "extra", NOW) is None  # no batch today
    s1, s2 = screen_order(conn, user)[:2]  # today's two 推荐词
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert [r["lemma"] for r in items_of(conn, b.id)] == ["apple", s1, s2]
    assert batches.append_to_today(conn, user, wid(conn, "apple"), "extra", NOW) is None  # already present as `new`
    mark(conn, user, "bank")
    item = batches.append_to_today(conn, user, wid(conn, "bank"), "extra", NOW)
    assert item is not None
    rows = items_of(conn, b.id)
    assert rows[-1]["lemma"] == "bank" and rows[-1]["kind"] == "extra" and rows[-1]["position"] == 3 and rows[-1]["user_word_id"] is not None
    assert batches.append_to_today(conn, user, wid(conn, "bank"), "new", NOW) is None  # one study row per word
    # a word present only as `screen` gets its study row (the in-batch 推荐词 不熟悉 path)
    mark(conn, user, s2, context="today")
    new_item = batches.append_to_today(conn, user, wid(conn, s2), "new", NOW)
    assert new_item is not None and count(conn, "SELECT COUNT(*) FROM push_items WHERE batch_id = ? AND word_id = ?", (b.id, wid(conn, s2))) == 2
    row = conn.execute("SELECT extra_count, new_count FROM push_batches WHERE id = ?", (b.id,)).fetchone()
    assert (row[0], row[1]) == (1, 2)
    assert conn.execute("SELECT times_pushed FROM user_words WHERE user_id = ? AND word_id = ?", (user, wid(conn, "bank"))).fetchone()[0] == 1
    # a word without a bank row cannot get a study row; a screen row needs a word the user has not marked
    assert batches.append_to_today(conn, user, wid(conn, "dog"), "extra", NOW) is None
    assert batches.append_to_today(conn, user, wid(conn, "dog"), "screen", NOW) is not None
    assert batches.append_to_today(conn, user, wid(conn, "dog"), "screen", NOW) is None
    with pytest.raises(ValueError):
        batches.append_to_today(conn, user, wid(conn, "dog"), "bogus", NOW)


def test_add_more_rounds_sources_and_rate_limit(settings, seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 1, daily_new_count = 1 WHERE user_id = ?", (user,))
    for lemma in ("apple", "bank", "cat", "dog"):
        mark(conn, user, lemma)
    pool = screen_order(conn, user)  # after the four marks: the 推荐词 pool of the CET-4 learner in learning order
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert [r["lemma"] for r in items_of(conn, b.id)] == ["apple", pool[0]]
    r1 = batches.add_more(conn, user, b.id, "new", 2, NOW)
    assert r1.added == 2 and r1.extra_rounds == 1
    lemmas = [r["lemma"] for r in items_of(conn, b.id)]
    assert lemmas == ["apple", pool[0], "bank", "cat"] and all(r["kind"] == "extra" for r in items_of(conn, b.id)[2:])
    r2 = batches.add_more(conn, user, b.id, "new", 10, NOW)
    assert r2.added == 1 and r2.extra_rounds == 2  # only `dog` is left; apple/bank/cat never duplicated
    r3 = batches.add_more(conn, user, b.id, "screen", 2, NOW)
    assert r3.added == 2 and r3.extra_rounds == 3
    screens = [r["lemma"] for r in items_of(conn, b.id) if r["kind"] == "screen"]
    assert screens == pool[:3]  # add_more continues the same order; the existing screen word is not repeated
    with pytest.raises(ApiError) as e:
        batches.add_more(conn, user, b.id, "new", 1, NOW)
    assert e.value.code == "rate_limited" and e.value.details["retry_after_s"] > 0
    assert conn.execute("SELECT extra_count, screen_count, extra_rounds FROM push_batches WHERE id = ?", (b.id,)).fetchone()[:] == (3, 3, 3)
    # a round that adds nothing is not consumed
    make_user(conn, "bob")
    conn.execute("UPDATE user_settings SET daily_screen_count = 0, daily_new_count = 10 WHERE user_id = 2")
    b2 = batches.build_batch(conn, 2, TODAY, "manual", NOW)
    assert batches.add_more(conn, 2, b2.id, "new", 5, NOW).added == 0
    assert conn.execute("SELECT extra_rounds FROM push_batches WHERE id = ?", (b2.id,)).fetchone()[0] == 0
    with pytest.raises(ApiError) as e:
        batches.add_more(conn, 2, b.id, "new", 1, NOW)  # someone else's batch
    assert e.value.code == "batch_not_found"


# ---------------------------------------------------------------------------------------- stale rule
def test_hide_stale_rule():
    items = [
        {"id": 1, "kind": "review", "result": None, "word_id": 1},
        {"id": 2, "kind": "new", "result": None, "word_id": 2},
        {"id": 3, "kind": "extra", "result": None, "word_id": 3},
        {"id": 4, "kind": "new", "result": "good", "word_id": 4},  # graded → stays even though mastered since
        {"id": 5, "kind": "screen", "result": None, "word_id": 5},  # word marked meanwhile → hidden
        {"id": 6, "kind": "screen", "result": None, "word_id": 6},  # untouched → visible
        {"id": 7, "kind": "screen", "result": "unfamiliar", "word_id": 7},  # graded → stays
        {"id": 8, "kind": "review", "result": None, "word_id": 8, "merged_into_word_id": 99},  # merged → hidden
        {"id": 9, "kind": "new", "result": None, "word_id": 9},  # row deleted (restore) → hidden
        {"id": 10, "kind": "new", "result": None, "word_id": 10, "superseded": 1},  # re-selected into a newer batch → hidden
        {"id": 11, "kind": "review", "result": "good", "word_id": 11, "superseded": 1},  # graded → history, stays
        {"id": 12, "kind": "extra", "result": None, "word_id": 12, "superseded": 0},  # flag false → visible
    ]
    states = {1: "learning", 2: "mastered", 3: "removed", 4: "mastered", 5: "new", 7: "new", 8: "learning", 10: "new", 11: "learning", 12: "new"}
    assert [it["id"] for it in batches.hide_stale(items, states)] == [1, 4, 6, 7, 11, 12]


def test_superseded_review_card_is_graded_once_per_day(settings, seeded, user):
    """A mature review left ungraded yesterday and re-selected today: today's row is the only gradable one, so the
    interval grows once (8 d → ~21 d), never twice the same day; yesterday's copy answers 409 superseded_item."""
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 0 WHERE user_id = ?", (user,))
    yesterday_now = NOW - timedelta(days=1)
    make_learning(conn, user, "apple", due_at="2026-10-12T16:00:00Z", interval=8)  # due on 2026-10-13 local
    b1 = batches.build_batch(conn, user, "2026-10-13", "scheduled", yesterday_now)
    (y_item,) = items_of(conn, b1.id)
    assert y_item["kind"] == "review" and y_item["result"] is None
    assert batches.previous_open_batch(conn, user, "2026-10-13") == {"id": b1.id, "local_date": "2026-10-13", "remaining": 1}
    b2 = batches.build_batch(conn, user, TODAY, "scheduled", NOW)
    (t_item,) = items_of(conn, b2.id)
    assert t_item["kind"] == "review" and t_item["word_id"] == y_item["word_id"]
    # the newer row supersedes the older one everywhere: previous_open_batch, Batch.gradable, counts, progress
    assert batches.previous_open_batch(conn, user, "2026-10-13") is None
    assert batches.visible_items(conn, user, b1.id) == [] and batches.batch_progress(conn, user, b1.id) == (0, 0)
    assert batches.today_response(conn, user, NOW, batch_id=b1.id, cfg=settings)["batch"]["gradable"] is False
    with pytest.raises(ApiError) as e:
        batches.grade_item(conn, user, y_item["id"], "good", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)
    assert e.value.code == "invalid_transition" and e.value.details["reason"] == "superseded_item"
    r = batches.grade_item(conn, user, t_item["id"], "good", client_event_id=str(uuid.uuid4()), elapsed_ms=2000, now=NOW, cfg=settings)
    iv = r["mine"]["srs"]["interval_days"]
    assert r["item"]["result"] == "good" and 20 <= iv <= 22 and r["mine"]["srs"]["consecutive_good"] == 1  # (8 + 1/2) × 2.5 ± 5 %
    with pytest.raises(ApiError) as e:  # still no second exposure through yesterday's copy
        batches.grade_item(conn, user, y_item["id"], "good", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW + timedelta(minutes=1), cfg=settings)
    assert e.value.code == "invalid_transition"
    assert count(conn, "SELECT COUNT(*) FROM review_logs WHERE user_id = ? AND action = 'good'", (user,)) == 1
    assert conn.execute("SELECT interval_days FROM user_words WHERE user_id = ? AND word_id = ?", (user, y_item["word_id"])).fetchone()[0] == iv


# ------------------------------------------------------------------------------------ publish/finalize
def test_publish_batch_is_conditional(seeded, user):
    conn = seeded
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert batches.publish_batch(conn, b.id, NOW) is True
    assert batches.publish_batch(conn, b.id, NOW + timedelta(minutes=1)) is False
    row = conn.execute("SELECT status, published_at, ready_at FROM push_batches WHERE id = ?", (b.id,)).fetchone()
    assert row[0] == "published" and row[1] == row[2] == "2026-10-14T01:00:00Z"
    assert batches.publish_batch(conn, 999, NOW) is False


def test_finalize_building_conditions(settings, seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 2 WHERE user_id = ?", (user,))
    mark(conn, user, "apple")
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert batches.finalize_building(conn, NOW + timedelta(minutes=1), cfg=settings) == 0  # content jobs runnable today
    items = batches.visible_items(conn, user, b.id)
    assert batches.pending_content(conn, batches.batch_row(conn, b.id), items, now="2026-10-14T01:01:00Z", cfg=settings) == 3
    # every live content job deferred past the day's end (budget deferral) → ready at once, pending_content 0
    conn.execute("UPDATE jobs SET run_after = '2026-10-14T16:05:00Z' WHERE type = 'generate_content'")
    assert batches.finalize_building(conn, NOW + timedelta(minutes=2), cfg=settings) == 1
    assert conn.execute("SELECT status, ready_at FROM push_batches WHERE id = ?", (b.id,)).fetchone()[:] == ("ready", "2026-10-14T01:02:00Z")
    assert batches.today_counts(conn, batches.batch_row(conn, b.id), items, now="2026-10-14T01:02:00Z", cfg=settings)["pending_content"] == 0
    # AI disabled through the kill switch → ready on the next pass
    make_user(conn, "bob")
    mark(conn, 2, "bank")
    b2 = batches.build_batch(conn, 2, TODAY, "manual", NOW)
    db.kv_set(conn, "claude.enabled", "0")
    assert batches.finalize_building(conn, NOW + timedelta(minutes=3), cfg=settings) == 1
    assert conn.execute("SELECT status FROM push_batches WHERE id = ?", (b2.id,)).fetchone()[0] == "ready"
    assert batches.today_counts(conn, batches.batch_row(conn, b2.id), batches.visible_items(conn, 2, b2.id), now="2026-10-14T01:03:00Z", cfg=settings)["pending_content"] == 0
    db.kv_delete(conn, "claude.enabled")
    # paused → ready too; otherwise the 2 h timeout
    make_user(conn, "carol")
    mark(conn, 3, "cat")
    b3 = batches.build_batch(conn, 3, TODAY, "manual", NOW)
    db.kv_set(conn, "claude.paused_until", "2026-10-14T05:00:00Z")
    assert batches.finalize_building(conn, NOW + timedelta(minutes=4), cfg=settings) == 1
    db.kv_delete(conn, "claude.paused_until")
    make_user(conn, "dave")
    mark(conn, 4, "dog")
    b4 = batches.build_batch(conn, 4, TODAY, "manual", NOW)
    assert batches.finalize_building(conn, NOW + timedelta(hours=1, minutes=59), cfg=settings) == 0
    assert batches.finalize_building(conn, NOW + timedelta(hours=2), cfg=settings) == 1
    assert conn.execute("SELECT status FROM push_batches WHERE id = ?", (b4.id,)).fetchone()[0] == "ready"
    # complete content → ready without waiting
    make_user(conn, "erin")
    mark(conn, 5, "glass")
    b5 = batches.build_batch(conn, 5, TODAY, "manual", NOW)
    conn.execute("UPDATE words SET content_state = 'ready' WHERE id IN (SELECT word_id FROM push_items WHERE batch_id = ?)", (b5.id,))
    conn.execute("UPDATE jobs SET status = 'done' WHERE type = 'generate_content'")
    assert batches.finalize_building(conn, NOW + timedelta(minutes=5), cfg=settings) == 1
    assert conn.execute("SELECT status FROM push_batches WHERE id = ?", (b5.id,)).fetchone()[0] == "ready"


# ------------------------------------------------------------------------------------------ grading
def test_grade_item_edge_cases(settings, seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 1 WHERE user_id = ?", (user,))
    mark(conn, user, "apple")
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    rows = items_of(conn, b.id)
    card = next(r for r in rows if r["kind"] == "new")
    scr = next(r for r in rows if r["kind"] == "screen")
    with pytest.raises(ApiError) as e:
        batches.grade_item(conn, user, card["id"], "known", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)
    assert e.value.code == "invalid_grade"
    with pytest.raises(ApiError) as e:
        batches.grade_item(conn, user, scr["id"], "good", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)
    assert e.value.code == "invalid_grade"
    with pytest.raises(ApiError) as e:
        batches.grade_item(conn, user, 9999, "good", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)
    assert e.value.code == "batch_not_found"
    # another user's item → 404, never 403
    bob = make_user(conn, "bob")
    with pytest.raises(ApiError) as e:
        batches.grade_item(conn, bob, card["id"], "good", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)
    assert e.value.code == "batch_not_found"
    # skip is never final and moves the item behind the unskipped ones
    event = str(uuid.uuid4())
    r = batches.grade_item(conn, user, card["id"], "skip", client_event_id=event, elapsed_ms=None, now=NOW, cfg=settings)
    assert r["item"] == {"item_id": card["id"], "result": None, "skip_count": 1, "requeue_at": None} and r["next_due_zh"] == "已跳过"
    assert r["today"]["done"] == 0 and r["duplicate"] is False
    dup = batches.grade_item(conn, user, card["id"], "skip", client_event_id=event, elapsed_ms=None, now=NOW, cfg=settings)
    assert dup["duplicate"] is True and dup["item"]["skip_count"] == 1
    assert count(conn, "SELECT COUNT(*) FROM review_logs WHERE action = 'skip'") == 1
    today = batches.today_response(conn, user, NOW, cfg=settings)
    assert [i["kind"] for i in today["batch"]["items"]] == ["screen", "new"]  # skipped after unskipped
    # final grade, then a different event → item_already_graded; skip still allowed
    r = batches.grade_item(conn, user, card["id"], "master", client_event_id=str(uuid.uuid4()), elapsed_ms=2000, now=NOW, cfg=settings)
    assert r["item"]["result"] == "master" and r["next_due_zh"] == "已掌握" and r["mine"]["state"] == "mastered" and r["today"]["done"] == 1
    with pytest.raises(ApiError) as e:
        batches.grade_item(conn, user, card["id"], "good", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)
    assert e.value.code == "item_already_graded"
    assert batches.grade_item(conn, user, card["id"], "skip", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)["item"]["skip_count"] == 2
    st = conn.execute("SELECT graded, mastered, study_ms FROM daily_stats WHERE user_id = ?", (user,)).fetchone()
    assert st[:] == (1, 1, 2000)
    # a two-day-old batch is not gradable → 404
    old = conn.execute("INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-12', ?, 'published', 'manual')", (user, TZ)).lastrowid
    mark(conn, user, "bank")
    old_item = conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'new', 0)", (old, wid(conn, "bank"))).lastrowid
    with pytest.raises(ApiError) as e:
        batches.grade_item(conn, user, old_item, "good", client_event_id=str(uuid.uuid4()), elapsed_ms=None, now=NOW, cfg=settings)
    assert e.value.code == "batch_not_found"


def test_complete_session_and_goal_met(settings, seeded, user):
    conn = seeded
    conn.execute("UPDATE user_settings SET daily_screen_count = 1 WHERE user_id = ?", (user,))
    with pytest.raises(ApiError) as e:
        batches.complete_session(conn, user, NOW, cfg=settings)
    assert e.value.code == "batch_not_ready"
    mark(conn, user, "apple")
    mark(conn, user, "bank")
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    rows = items_of(conn, b.id)
    s1 = batches.complete_session(conn, user, NOW, cfg=settings)
    assert s1["goal_met"] is False and conn.execute("SELECT completed_at FROM push_batches WHERE id = ?", (b.id,)).fetchone()[0] is None
    for r in rows:
        if r["kind"] == "new":
            batches.grade_item(conn, user, r["id"], "master", client_event_id=str(uuid.uuid4()), elapsed_ms=30_000, now=NOW, cfg=settings)
    s2 = batches.complete_session(conn, user, NOW + timedelta(minutes=5), cfg=settings)
    assert s2["goal_met"] is True and s2["mastered"] == 2 and s2["study_minutes"] == 1 and s2["new"] == 2 and s2["screen"] == 1
    assert s2["streak_days"] == 1 and s2["can_request_more"] is True and s2["next_push_at"] == "2026-10-15T00:00:00Z"
    assert conn.execute("SELECT completed_at FROM push_batches WHERE id = ?", (b.id,)).fetchone()[0] == "2026-10-14T01:05:00Z"
    s3 = batches.complete_session(conn, user, NOW + timedelta(minutes=9), cfg=settings)  # idempotent
    assert conn.execute("SELECT completed_at FROM push_batches WHERE id = ?", (b.id,)).fetchone()[0] == "2026-10-14T01:05:00Z" and s3["goal_met"]
    today = batches.today_response(conn, user, NOW + timedelta(minutes=10), cfg=settings)
    assert today["goal_met"] is True and today["batch"]["completed_at"] == "2026-10-14T01:05:00Z"


def test_push_now_builds_publishes_and_enqueues_deliveries(settings, seeded, user):
    conn = seeded
    conn.execute("UPDATE users SET email = 'a@example.com', email_verified_at = '2026-10-01T00:00:00Z' WHERE id = ?", (user,))
    conn.execute("UPDATE user_settings SET email_enabled = 1, webhook_enabled = 1, webhook_url = 'https://hooks.example.com/x' WHERE user_id = ?", (user,))
    mark(conn, user, "apple")
    batch_id, status = batches.push_now(conn, user, NOW)
    assert status == "published"
    row = conn.execute("SELECT trigger, email_status, webhook_status FROM push_batches WHERE id = ?", (batch_id,)).fetchone()
    assert row[:] == ("admin", "queued", "queued")
    keys = sorted(r[0] for r in conn.execute("SELECT dedupe_key FROM jobs WHERE type IN ('send_email','send_webhook')"))
    assert keys == [f"email:{batch_id}", f"webhook:{batch_id}"]
    again_id, again_status = batches.push_now(conn, user, NOW + timedelta(minutes=1))
    assert (again_id, again_status) == (batch_id, "published")
    assert count(conn, "SELECT COUNT(*) FROM jobs WHERE type IN ('send_email','send_webhook')") == 2  # no duplicate deliveries
    assert conn.execute("SELECT next_push_at FROM user_settings WHERE user_id = ?", (user,)).fetchone()[0] == "2026-10-15T00:00:00Z"


def test_enqueue_deliveries_respects_channels_and_stale(seeded, user):
    conn = seeded
    b = batches.build_batch(conn, user, TODAY, "manual", NOW)
    assert batches.enqueue_deliveries(conn, b.id, NOW) == {}  # nothing enabled → statuses stay 'none'
    conn.execute("UPDATE users SET email = 'a@example.com', email_verified_at = '2026-10-01T00:00:00Z' WHERE id = ?", (user,))
    conn.execute("UPDATE user_settings SET email_enabled = 1 WHERE user_id = ?", (user,))
    assert batches.enqueue_deliveries(conn, b.id, NOW, stale=True) == {"email": "skipped"}
    assert conn.execute("SELECT email_status, webhook_status FROM push_batches WHERE id = ?", (b.id,)).fetchone()[:] == ("skipped", "none")
    assert count(conn, "SELECT COUNT(*) FROM jobs WHERE type = 'send_email'") == 0
