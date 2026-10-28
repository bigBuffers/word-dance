"""services/bank (WP3) on the mini seed: every row of the DESIGN §4 state machine, the §4 action mapping, restore,
attention flags, bulk add statuses and import — directly against the service functions (no HTTP)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from wd import db
from wd.errors import ApiError
from wd.services import bank, words
from wd.services.bank import apply_action, origin_for_context

UTC = timezone.utc
TZ = "Asia/Shanghai"
NOW = datetime(2026, 10, 14, 8, 0, 0, tzinfo=UTC)  # 16:00 in Asia/Shanghai → local date 2026-10-14
TODAY = "2026-10-14"


# ------------------------------------------------------------------------------------------- helpers
def make_user(conn: sqlite3.Connection, username: str, role: str = "user") -> int:
    cur = conn.execute("INSERT INTO users(username, password_hash, role) VALUES (?, 'x', ?)", (username, role))
    uid = int(cur.lastrowid)
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    return uid


def wid(conn: sqlite3.Connection, lemma: str) -> int:
    return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0])


def uw(conn: sqlite3.Connection, user_id: int, word_id: int) -> dict | None:
    return db.row_to_dict(conn.execute("SELECT * FROM user_words WHERE user_id = ? AND word_id = ?", (user_id, word_id)).fetchone())


def logs(conn: sqlite3.Connection, user_id: int, word_id: int) -> list[dict]:
    return [db.row_to_dict(r) for r in conn.execute("SELECT * FROM review_logs WHERE user_id = ? AND word_id = ? ORDER BY id", (user_id, word_id))]


def stats(conn: sqlite3.Connection, user_id: int, local_date: str = TODAY) -> dict:
    row = db.row_to_dict(conn.execute("SELECT * FROM daily_stats WHERE user_id = ? AND local_date = ?", (user_id, local_date)).fetchone())
    return row or {k: 0 for k in ("graded", "again", "hard", "good", "mastered", "known", "screened", "added", "study_ms")}


def jobs(conn: sqlite3.Connection, type_: str | None = None) -> list[dict]:
    sql = "SELECT * FROM jobs" + (" WHERE type = ?" if type_ else "") + " ORDER BY id"
    return [db.row_to_dict(r) for r in conn.execute(sql, (type_,) if type_ else ()).fetchall()]


def act(conn, user_id, word_id, action, *, context="api", now=NOW, origin=None, **kw):
    return apply_action(conn, user_id, word_id, action, origin=origin or origin_for_context(context), context=context, now=now, tz=TZ, **kw)


def make_batch(conn: sqlite3.Connection, user_id: int, local_date: str = TODAY) -> int:
    cur = conn.execute(
        "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, ?, ?, 'published', 'manual')",
        (user_id, local_date, TZ),
    )
    return int(cur.lastrowid)


def make_item(conn: sqlite3.Connection, batch_id: int, word_id: int, kind: str, position: int = 0, user_word_id: int | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, ?, ?)",
        (batch_id, word_id, user_word_id, kind, position),
    )
    return int(cur.lastrowid)


@pytest.fixture
def user(seeded: sqlite3.Connection) -> int:
    return make_user(seeded, "alice")


# ------------------------------------------------------------------------------- context → origin
@pytest.mark.parametrize(
    "context,origin",
    [("browse", "browse"), ("detail", "browse"), ("bank", "browse"), ("api", "browse"), (None, "browse"), ("today", "push"), ("extra", "push"), ("screen_page", "screen"), ("onboarding", "screen")],
)
def test_context_to_origin_mapping(context, origin):
    assert origin_for_context(context) == origin


# ---------------------------------------------------------------------------------- ∅ transitions
def test_unfamiliar_from_nothing_creates_a_new_row_and_enqueues_content(seeded, user):
    w = wid(seeded, "abandon")
    r = act(seeded, user, w, "unfamiliar", context="browse")
    assert (r.status, r.state, r.created) == ("added", "new", True)
    row = uw(seeded, user, w)
    assert row["origin"] == "browse" and row["priority"] == 50 and row["times_added"] == 1
    assert (row["ease"], row["interval_days"], row["step"], row["due_at"]) == (2.5, 0, 0, None)
    assert row["added_at"] == row["first_added_at"] == "2026-10-14T08:00:00Z"
    (log,) = logs(seeded, user, w)
    assert (log["action"], log["context"], log["prev_state"], log["new_state"], log["local_date"]) == ("unfamiliar", "browse", None, "new", TODAY)
    assert stats(seeded, user)["added"] == 1 and stats(seeded, user)["screened"] == 0
    (job,) = jobs(seeded, "generate_content")
    assert (job["dedupe_key"], job["priority"], json.loads(job["payload_json"])) == (f"content:{w}", 20, {"word_id": w})
    assert seeded.execute("SELECT content_state FROM words WHERE id = ?", (w,)).fetchone()[0] == "queued"
    assert r.mine["state"] == "new" and r.mine["srs"]["mastery_suggested"] is False


def test_unfamiliar_from_detail_or_today_is_priority_10_and_origin_push_for_today(seeded, user):
    w1, w2 = wid(seeded, "apple"), wid(seeded, "bank")
    act(seeded, user, w1, "unfamiliar", context="detail")
    act(seeded, user, w2, "unfamiliar", context="today")
    assert [j["priority"] for j in jobs(seeded, "generate_content")] == [10, 10]
    assert uw(seeded, user, w1)["origin"] == "browse" and uw(seeded, user, w2)["origin"] == "push"


def test_unfamiliar_screen_page_counts_screened_and_origin_screen(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar", context="screen_page")
    assert uw(seeded, user, w)["origin"] == "screen"
    assert (stats(seeded, user)["added"], stats(seeded, user)["screened"]) == (1, 1)


def test_unfamiliar_is_idempotent_and_updates_the_note(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    r = act(seeded, user, w, "unfamiliar", note="met at work")
    assert r.status == "exists" and r.state == "new" and r.created is False
    assert uw(seeded, user, w)["note"] == "met at work"
    rows = logs(seeded, user, w)
    assert [l["action"] for l in rows] == ["unfamiliar", "unfamiliar"] and rows[1]["prev_state"] == "new"
    assert stats(seeded, user)["added"] == 1  # nothing counted twice
    assert len(jobs(seeded, "generate_content")) == 1


def test_known_from_nothing_creates_a_known_row(seeded, user):
    w = wid(seeded, "abandon")
    r = act(seeded, user, w, "known", context="screen_page")
    assert (r.status, r.state) == ("added", "known")
    row = uw(seeded, user, w)
    assert row["origin"] == "screen" and row["state"] == "known"
    (log,) = logs(seeded, user, w)
    assert log["action"] == "known" and json.loads(log["prev_srs_json"]) == {"state": None}
    assert (stats(seeded, user)["known"], stats(seeded, user)["screened"]) == (1, 1)
    assert jobs(seeded) == []  # known never spends


def test_mastered_from_nothing_is_treated_as_known(seeded, user):
    w = wid(seeded, "abandon")
    r = act(seeded, user, w, "mastered", context="browse")
    assert r.state == "known" and uw(seeded, user, w)["state"] == "known"
    assert stats(seeded, user)["known"] == 1 and stats(seeded, user)["mastered"] == 0


@pytest.mark.parametrize("action", ["remove", "reset"])
def test_remove_and_reset_from_nothing_are_invalid(seeded, user, action):
    with pytest.raises(ApiError) as e:
        act(seeded, user, wid(seeded, "abandon"), action)
    assert e.value.code == "invalid_transition" and e.value.details["action"] == action


def test_unknown_word_is_404(seeded, user):
    with pytest.raises(ApiError) as e:
        act(seeded, user, 999_999, "unfamiliar")
    assert e.value.code == "word_not_found"


# -------------------------------------------------------------------------------- bank transitions
def test_new_to_mastered_snapshots_and_freezes_the_row(seeded, user):
    w = wid(seeded, "abandon")
    r0 = act(seeded, user, w, "unfamiliar")
    seeded.execute("INSERT INTO bank_suggestions(user_id, type, user_word_id, payload_json, status) VALUES (?, 'fix_spelling', ?, '{}', 'open')", (user, r0.user_word_id))
    r = act(seeded, user, w, "mastered", context="detail")
    assert (r.status, r.state) == ("added", "mastered")
    row = uw(seeded, user, w)
    assert row["mastered_at"] == "2026-10-14T08:00:00Z" and row["due_at"] is None
    log = logs(seeded, user, w)[-1]
    assert (log["action"], log["prev_state"], log["new_state"]) == ("master", "new", "mastered")
    snap = json.loads(log["prev_srs_json"])
    assert snap["state"] == "new" and snap["ease"] == 2.5 and snap["times_added"] == 1
    assert seeded.execute("SELECT status FROM bank_suggestions WHERE user_word_id = ?", (r0.user_word_id,)).fetchone()[0] == "expired"
    assert stats(seeded, user)["mastered"] == 1 and stats(seeded, user)["graded"] == 0


def test_known_on_a_bank_word_is_the_mastered_synonym(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    r = act(seeded, user, w, "known", context="browse")
    assert r.state == "mastered"
    log = logs(seeded, user, w)[-1]
    assert (log["action"], log["new_state"]) == ("known", "mastered") and log["prev_srs_json"] is not None
    assert stats(seeded, user)["mastered"] == 1 and stats(seeded, user)["known"] == 0


def test_remove_reset_rows(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    assert act(seeded, user, w, "reset").status == "noop"  # new → reset: nothing to reset
    seeded.execute("UPDATE user_words SET state = 'learning', ease = 2.3, interval_days = 8, step = 0, repetitions = 4, lapses = 1, consecutive_good = 2, due_at = '2026-10-20T00:00:00Z', last_graded_at = '2026-10-12T00:00:00Z' WHERE user_id = ? AND word_id = ?", (user, w))
    r = act(seeded, user, w, "reset")
    row = uw(seeded, user, w)
    assert r.state == "new" and (row["ease"], row["interval_days"], row["repetitions"], row["lapses"], row["due_at"], row["last_graded_at"]) == (2.5, 0, 0, 0, None, None)
    assert logs(seeded, user, w)[-1]["action"] == "reset"
    r = act(seeded, user, w, "remove")
    assert r.state == "removed" and logs(seeded, user, w)[-1]["action"] == "remove"
    assert act(seeded, user, w, "remove").status == "noop"
    with pytest.raises(ApiError) as e:
        act(seeded, user, w, "reset")
    assert e.value.code == "invalid_transition" and e.value.details == {"from": "removed", "action": "reset"}
    assert stats(seeded, user)["added"] == 1  # remove / reset change nothing


def test_readd_from_mastered_lowers_ease_and_logs_readd(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    seeded.execute("UPDATE user_words SET state = 'learning', ease = 2.6, interval_days = 51, step = 0, repetitions = 6, consecutive_good = 3, due_at = '2026-12-01T00:00:00Z' WHERE user_id = ? AND word_id = ?", (user, w))
    act(seeded, user, w, "mastered")
    seeded.execute("DELETE FROM jobs")
    seeded.execute("UPDATE words SET content_state = 'failed' WHERE id = ?", (w,))  # the earlier content job died
    r = act(seeded, user, w, "unfamiliar", context="bank")
    assert (r.status, r.state) == ("readded", "new")
    row = uw(seeded, user, w)
    assert row["ease"] == 2.4 and row["priority"] == 80 and row["times_added"] == 2
    assert (row["step"], row["interval_days"], row["due_at"], row["consecutive_good"], row["mastered_at"]) == (0, 0, None, 0, None)
    assert row["repetitions"] == 6 and row["origin"] == "browse"  # history kept, origin never changes
    assert logs(seeded, user, w)[-1]["action"] == "readd"
    assert stats(seeded, user)["added"] == 2
    assert [j["type"] for j in jobs(seeded)] == ["generate_content"]  # a validated word re-entering the bank wants content


def test_readd_from_known_or_removed_keeps_ease(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "known")
    r = act(seeded, user, w, "unfamiliar")
    assert r.status == "readded" and uw(seeded, user, w)["ease"] == 2.5 and uw(seeded, user, w)["times_added"] == 2
    act(seeded, user, w, "remove")
    r = act(seeded, user, w, "unfamiliar")
    assert r.status == "readded" and uw(seeded, user, w)["times_added"] == 3 and uw(seeded, user, w)["ease"] == 2.5


def test_ease_floor_on_readd(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    seeded.execute("UPDATE user_words SET ease = 1.4 WHERE user_id = ? AND word_id = ?", (user, w))
    act(seeded, user, w, "mastered")
    act(seeded, user, w, "unfamiliar")
    assert uw(seeded, user, w)["ease"] == 1.3


def test_noop_rows(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    act(seeded, user, w, "mastered")
    n = len(logs(seeded, user, w))
    assert act(seeded, user, w, "mastered").status == "noop"
    assert act(seeded, user, w, "known").status == "noop"
    assert len(logs(seeded, user, w)) == n  # no-ops write nothing
    w2 = wid(seeded, "apple")
    act(seeded, user, w2, "known")
    assert act(seeded, user, w2, "mastered").status == "noop" and uw(seeded, user, w2)["state"] == "known"
    assert act(seeded, user, w2, "remove").state == "removed"
    assert act(seeded, user, w, "remove").state == "removed"


def test_master_alias_and_card_grade_counts_graded(seeded, user):
    w = wid(seeded, "abandon")
    r0 = act(seeded, user, w, "unfamiliar")
    batch = make_batch(seeded, user)
    item = make_item(seeded, batch, w, "new", user_word_id=r0.user_word_id)
    r = act(seeded, user, w, "master", context="today", push_item_id=item, elapsed_ms=4000)
    assert r.state == "mastered"
    log = logs(seeded, user, w)[-1]
    assert (log["action"], log["push_item_id"], log["batch_id"], log["elapsed_ms"]) == ("master", item, batch, 4000)
    s = stats(seeded, user)
    assert (s["mastered"], s["graded"], s["study_ms"]) == (1, 1, 4000)


# ------------------------------------------------------------------------------------------ restore
def test_restore_of_master_puts_the_snapshot_back(seeded, user):
    w = wid(seeded, "abandon")
    r0 = act(seeded, user, w, "unfamiliar", now=NOW - timedelta(days=60))
    seeded.execute(
        "UPDATE user_words SET state = 'learning', ease = 2.6, interval_days = 51, step = 0, repetitions = 6, lapses = 1, consecutive_good = 3, "
        "due_at = '2026-12-04T16:00:00Z', last_graded_at = '2026-10-14T06:00:00Z', priority = 50, times_added = 1 WHERE id = ?",
        (r0.user_word_id,),
    )
    batch = make_batch(seeded, user)
    item = make_item(seeded, batch, w, "review", user_word_id=r0.user_word_id)
    act(seeded, user, w, "master", context="today", push_item_id=item, elapsed_ms=2500)
    seeded.execute("UPDATE push_items SET result = 'master', graded_at = ? WHERE id = ?", ("2026-10-14T08:00:00Z", item))  # the grader (WP4) stores the final grade
    assert stats(seeded, user)["mastered"] == 1 and stats(seeded, user)["graded"] == 1

    r = act(seeded, user, w, "restore", context="today", now=NOW + timedelta(seconds=2))
    assert (r.status, r.state) == ("restored", "learning")
    row = uw(seeded, user, w)
    assert (row["state"], row["ease"], row["interval_days"], row["step"], row["repetitions"], row["lapses"], row["consecutive_good"]) == ("learning", 2.6, 51, 0, 6, 1, 3)
    assert row["due_at"] == "2026-12-04T16:00:00Z" and row["last_graded_at"] == "2026-10-14T06:00:00Z" and row["mastered_at"] is None
    assert row["times_added"] == 1 and row["priority"] == 50
    assert tuple(seeded.execute("SELECT result, graded_at FROM push_items WHERE id = ?", (item,)).fetchone()) == (None, None)
    assert stats(seeded, user)["mastered"] == 0 and stats(seeded, user)["graded"] == 0
    log = logs(seeded, user, w)[-1]
    assert (log["action"], log["prev_state"], log["new_state"], log["push_item_id"]) == ("restore", "mastered", "learning", item)
    assert r.mine["srs"]["mastery_suggested"] is True


def test_restore_window_and_eligibility(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar", now=NOW - timedelta(days=1))
    seeded.execute("UPDATE user_words SET state = 'learning', repetitions = 2 WHERE user_id = ? AND word_id = ?", (user, w))
    act(seeded, user, w, "mastered")
    with pytest.raises(ApiError) as e:
        act(seeded, user, w, "restore", now=NOW + timedelta(minutes=16))
    assert e.value.code == "undo_expired"
    # inside the window it works
    assert act(seeded, user, w, "restore", now=NOW + timedelta(minutes=14)).state == "learning"
    # a word that was never mastered/known/added → undo_expired
    w2 = wid(seeded, "apple")
    with pytest.raises(ApiError) as e:
        act(seeded, user, w2, "restore")
    assert e.value.code == "undo_expired"
    # a learning word with only grade history → undo_expired
    with pytest.raises(ApiError) as e:
        act(seeded, user, w, "restore", now=NOW + timedelta(minutes=14, seconds=1))
    assert e.value.code == "undo_expired"


def test_a_later_unfamiliar_from_the_mastered_list_is_a_readd_not_a_restore(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    act(seeded, user, w, "mastered")
    r = act(seeded, user, w, "unfamiliar", context="bank", now=NOW + timedelta(seconds=5))
    assert r.status == "readded" and uw(seeded, user, w)["times_added"] == 2
    with pytest.raises(ApiError):  # the readd is not undoable
        act(seeded, user, w, "restore", now=NOW + timedelta(seconds=6))


def test_restore_of_a_screen_known_deletes_the_row(seeded, user):
    w = wid(seeded, "abandon")
    batch = make_batch(seeded, user)
    item = make_item(seeded, batch, w, "screen")
    r = act(seeded, user, w, "known", context="today", push_item_id=item)
    seeded.execute("UPDATE push_items SET result = 'known', graded_at = ?, user_word_id = ? WHERE id = ?", ("2026-10-14T08:00:00Z", r.user_word_id, item))
    assert (stats(seeded, user)["known"], stats(seeded, user)["screened"]) == (1, 1)
    r = act(seeded, user, w, "restore", context="today", now=NOW + timedelta(seconds=3))
    assert (r.status, r.state, r.mine) == ("restored", None, None)
    assert uw(seeded, user, w) is None
    assert tuple(seeded.execute("SELECT result, graded_at FROM push_items WHERE id = ?", (item,)).fetchone()) == (None, None)
    assert (stats(seeded, user)["known"], stats(seeded, user)["screened"]) == (0, 0)
    assert logs(seeded, user, w)[-1]["new_state"] is None


def test_restore_of_a_screen_page_known_without_a_batch(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "known", context="screen_page")
    act(seeded, user, w, "restore", context="screen_page", now=NOW + timedelta(seconds=3))
    assert uw(seeded, user, w) is None and stats(seeded, user)["known"] == 0 and stats(seeded, user)["screened"] == 0


def test_restore_of_a_screen_unfamiliar_deletes_row_and_appended_new_item(seeded, user):
    w = wid(seeded, "abandon")
    batch = make_batch(seeded, user)
    screen_item = make_item(seeded, batch, w, "screen", position=3)
    r = act(seeded, user, w, "unfamiliar", context="today", push_item_id=screen_item)
    seeded.execute("UPDATE push_items SET result = 'unfamiliar', graded_at = ?, user_word_id = ? WHERE id = ?", ("2026-10-14T08:00:00Z", r.user_word_id, screen_item))
    new_item = make_item(seeded, batch, w, "new", position=9, user_word_id=r.user_word_id)  # append_to_today's second row
    assert (stats(seeded, user)["added"], stats(seeded, user)["screened"]) == (1, 1)
    r = act(seeded, user, w, "restore", context="today", now=NOW + timedelta(seconds=10))
    assert r.status == "restored" and r.state is None
    assert uw(seeded, user, w) is None
    assert seeded.execute("SELECT COUNT(*) FROM push_items WHERE id = ?", (new_item,)).fetchone()[0] == 0
    assert tuple(seeded.execute("SELECT result, graded_at FROM push_items WHERE id = ?", (screen_item,)).fetchone()) == (None, None)
    assert (stats(seeded, user)["added"], stats(seeded, user)["screened"]) == (0, 0)
    assert len(jobs(seeded, "generate_content")) == 1  # the content job is left alone (content is global)


def test_restore_after_a_grade_or_idempotent_unfamiliar_is_refused(seeded, user):
    w = wid(seeded, "abandon")
    r0 = act(seeded, user, w, "unfamiliar", context="screen_page")
    # a `good` grade (WP4) on the new row: repetitions 1 + its log row
    seeded.execute("UPDATE user_words SET state = 'learning', repetitions = 1, step = 1 WHERE id = ?", (r0.user_word_id,))
    bank.write_log(seeded, user_id=user, word_id=w, action="good", context="today", local_date=TODAY, now="2026-10-14T08:00:05Z", user_word_id=r0.user_word_id, prev_state="new", new_state="learning")
    with pytest.raises(ApiError) as e:
        act(seeded, user, w, "restore", now=NOW + timedelta(seconds=10))
    assert e.value.code == "undo_expired"
    # an idempotent unfamiliar (status exists) is never undoable
    w2 = wid(seeded, "apple")
    act(seeded, user, w2, "unfamiliar")
    act(seeded, user, w2, "unfamiliar", now=NOW + timedelta(seconds=1))
    with pytest.raises(ApiError) as e:
        act(seeded, user, w2, "restore", now=NOW + timedelta(seconds=2))
    assert e.value.code == "undo_expired"
    assert uw(seeded, user, w2)["state"] == "new"


def test_restore_ignores_note_and_attention_rows_when_finding_the_transition(seeded, user):
    w = wid(seeded, "abandon")
    act(seeded, user, w, "unfamiliar")
    act(seeded, user, w, "mastered")
    bank.write_log(seeded, user_id=user, word_id=w, action="note", context="api", local_date=TODAY, now="2026-10-14T08:00:01Z", prev_state="mastered", new_state="mastered")
    assert act(seeded, user, w, "restore", now=NOW + timedelta(seconds=5)).state == "new"


# ---------------------------------------------------------------------------------------- attention
def test_attention_retry_and_keep(seeded, user):
    bob = make_user(seeded, "bob")
    res = words.resolve(seeded, "zzqx", "zzqx", "word", user)
    w = res.word_id
    act(seeded, user, w, "add_custom", origin="custom", input_text="zzqx")
    act(seeded, bob, w, "add_custom", origin="custom", input_text="zzqx")
    # the debounced lookup job dies (3 failed attempts) → the handler flags both holders
    seeded.execute("UPDATE jobs SET status = 'dead' WHERE dedupe_key = ?", (f"lookup:{w}",))
    seeded.execute("UPDATE user_words SET needs_attention = 1, attention_msg = '暂时无法校验，请稍后重试或检查拼写' WHERE word_id = ?", (w,))
    assert bank.attention_count(seeded, user) == 1

    mine = bank.set_attention(seeded, user, w, "retry", NOW)
    live = [j for j in jobs(seeded, "lookup_word") if j["status"] in ("queued", "running")]
    assert len(live) == 1 and live[0]["dedupe_key"] == f"lookup:{w}" and live[0]["priority"] == 10 and live[0]["run_after"] == "2026-10-14T08:00:00Z"
    assert mine["needs_attention"] is True and mine["attention_msg"] is None
    assert bank.attention_count(seeded, user) == 1  # counters.attention unchanged
    bank.set_attention(seeded, bob, w, "retry", NOW)  # a second holder retrying adds no job
    assert len([j for j in jobs(seeded, "lookup_word") if j["status"] in ("queued", "running")]) == 1
    log = logs(seeded, user, w)[-1]
    assert log["action"] == "attention" and json.loads(log["result_json"]) == {"decision": "retry"}

    # retry on a validated word → 409
    with pytest.raises(ApiError) as e:
        bank.set_attention(seeded, user, wid(seeded, "abandon"), "retry", NOW)
    assert e.value.code == "word_not_found"  # not even in the bank
    act(seeded, user, wid(seeded, "abandon"), "unfamiliar")
    with pytest.raises(ApiError) as e:
        bank.set_attention(seeded, user, wid(seeded, "abandon"), "retry", NOW)
    assert e.value.code == "invalid_transition"

    # keep on an is_valid_english = 0 word → 仅收藏
    seeded.execute("UPDATE words SET is_valid_english = 0, is_public = 0 WHERE id = ?", (w,))
    seeded.execute("UPDATE user_words SET needs_attention = 1, attention_msg = '未识别为英文单词：…' WHERE word_id = ? AND user_id = ?", (w, user))
    with pytest.raises(ApiError) as e:
        bank.set_attention(seeded, user, w, "retry", NOW)
    assert e.value.code == "invalid_transition"
    mine = bank.set_attention(seeded, user, w, "keep", NOW)
    assert mine["needs_attention"] is False and mine["attention_msg"] is None and mine["state"] == "new"
    assert bank.attention_count(seeded, user) == 0
    assert json.loads(logs(seeded, user, w)[-1]["result_json"]) == {"decision": "keep"}
    assert bank.set_attention(seeded, user, w, "keep", NOW)["needs_attention"] is False  # noop
    assert stats(seeded, user)["added"] == 2  # attention never touches daily_stats


def test_exact_hit_on_a_rejected_word_flags_the_new_row(seeded, user):
    res = words.resolve(seeded, "zzqx", "zzqx", "word", user)
    seeded.execute("UPDATE words SET is_valid_english = 0, is_public = 0 WHERE id = ?", (res.word_id,))
    seeded.execute("DELETE FROM jobs")
    bob = make_user(seeded, "bob")
    results = bank.add_custom_words(seeded, bob, "zzqx", None, False, NOW, TZ)
    (r,) = results
    assert r.status == "added" and r.mine["needs_attention"] is True and r.mine["attention_msg"] == "未识别为英文单词"
    assert jobs(seeded) == []  # no job for an already-rejected string


# ------------------------------------------------------------------------------------------ bulk add
def test_bulk_add_statuses(seeded, user):
    act(seeded, user, wid(seeded, "abandon"), "unfamiliar")
    seeded.execute("DELETE FROM jobs")
    results = bank.add_custom_words(seeded, user, "abandoned, children\nubiquitous；bases\tabc123", "ctx", False, NOW, TZ)
    by_input = {r.input: r for r in results}
    assert [r.status for r in results] == ["exists", "added", "pending_ai", "ambiguous", "invalid"]
    assert by_input["abandoned"].word["lemma"] == "abandon" and by_input["abandoned"].resolved_via == "form"
    assert by_input["children"].word["lemma"] == "child" and by_input["children"].lemma_note_zh == "已归为原形 child（复数）"
    assert by_input["children"].mine["origin"] == "custom" and by_input["children"].mine["priority"] == 100 and by_input["children"].mine["note"] == "ctx"
    assert by_input["ubiquitous"].resolved_via == "provisional" and by_input["ubiquitous"].word["is_valid_english"] is None
    assert [c["lemma"] for c in by_input["bases"].candidates] == ["base", "basis"] and by_input["bases"].word is None
    assert by_input["abc123"].error == "只能包含英文字母、空格、连字符、撇号和缩写点"
    summary = bank.summarise(results)
    assert (summary["exists"], summary["added"], summary["pending_ai"], summary["ambiguous"], summary["invalid"]) == (1, 1, 1, 1, 1)
    # jobs: one content job for the validated add, one debounced lookup for the provisional word, none else
    js = jobs(seeded)
    types = sorted(j["type"] for j in js)
    assert types == ["generate_content", "lookup_word"]
    lookup = next(j for j in js if j["type"] == "lookup_word")
    prov = by_input["ubiquitous"].word["id"]
    assert lookup["dedupe_key"] == f"lookup:{prov}" and lookup["priority"] == 10
    assert lookup["run_after"] >= "2026-10-14T08:00:15Z"  # ≈ now + 20 s (the resolver's clock)
    assert not any(j["type"] == "generate_content" and json.loads(j["payload_json"])["word_id"] == prov for j in js)
    (log,) = logs(seeded, user, wid(seeded, "child"))
    assert log["action"] == "add_custom" and log["context"] == "api"
    assert stats(seeded, user)["added"] == 3  # abandon + child + ubiquitous


def test_bulk_add_dedupes_within_the_request_and_caps_tokens(seeded, user):
    results = bank.add_custom_words(seeded, user, "apple, Apple ,apples", None, False, NOW, TZ)
    assert [r.input for r in results] == ["apple", "apples"] and results[1].status == "exists"
    with pytest.raises(ApiError) as e:
        bank.add_custom_words(seeded, user, ",".join(f"w{i}" for i in range(51)), None, False, NOW, TZ)
    assert e.value.code == "too_many_words"


def test_study_today_uses_append_to_today_only_for_validated_words(seeded, user, monkeypatch):
    from wd.services import batches

    calls: list[tuple] = []

    def append_to_today(conn, user_id, word_id, kind, now):
        calls.append((user_id, word_id, kind))
        return 4242

    monkeypatch.setattr(batches, "append_to_today", append_to_today)
    results = bank.add_custom_words(seeded, user, "abandon, ubiquitous", None, True, NOW, TZ)
    assert [r.status for r in results] == ["added", "pending_ai"]
    assert results[0].added_to_today is True and results[1].added_to_today is False
    assert calls == [(user, wid(seeded, "abandon"), "extra")]


def test_study_today_without_a_batch_today_is_false(seeded, user):
    """The real WP4 append_to_today: no push batch for the user today → nothing appended, added_to_today false."""
    results = bank.add_custom_words(seeded, user, "abandon", None, True, NOW, TZ)
    assert results[0].status == "added" and results[0].added_to_today is False
    assert seeded.execute("SELECT COUNT(*) FROM push_items").fetchone()[0] == 0


# -------------------------------------------------------------------------------------------- import
def _export_rows() -> list[dict]:
    return [
        {"word": "abandon", "phonetic": None, "translation": None, "state": "learning", "origin": "browse", "note": "n1", "times_added": 2, "added_at": "2026-09-01T00:00:00Z", "mastered_at": None, "ease": 2.35, "interval_days": 10, "repetitions": 7, "lapses": 1, "due_at": "2026-10-20T16:00:00Z"},
        {"word": "apple", "state": "mastered", "origin": "custom", "note": None, "times_added": 1, "added_at": "2026-08-01T00:00:00Z", "mastered_at": "2026-09-15T00:00:00Z", "ease": 2.7, "interval_days": 60, "repetitions": 9, "lapses": 0, "due_at": None},
        {"word": "children", "state": "new", "origin": "screen"},
        {"word": "bank", "state": "known"},
        {"word": "ubiquitous", "state": "learning", "ease": 2.5, "interval_days": 3, "due_at": "2026-10-16T16:00:00Z"},
        {"word": "bases", "state": "new"},
        {"word": "abc123", "state": "new"},
        {"word": "glass", "state": "learning"},  # learning without SRS → starts as new
    ]


def test_import_json_rows(seeded, user):
    data = json.dumps({"version": 1, "exported_at": "x", "username": "alice", "words": _export_rows(), "review_logs": [{"created_at": "x", "word": "abandon", "action": "good", "context": "today"}]})
    res = bank.import_rows(seeded, user, "json", data, NOW, TZ)
    assert res.rows == 8 and [r.status for r in res.results] == ["added", "added", "added", "added", "pending_ai", "ambiguous", "invalid", "added"]
    assert res.skipped == 2 and res.pending_ai_created == 1
    ab = uw(seeded, user, wid(seeded, "abandon"))
    assert (ab["state"], ab["origin"], ab["ease"], ab["interval_days"], ab["repetitions"], ab["lapses"], ab["due_at"], ab["note"], ab["times_added"], ab["added_at"]) == (
        "learning", "import", 2.35, 10, 7, 1, "2026-10-20T16:00:00Z", "n1", 2, "2026-09-01T00:00:00Z")
    ap = uw(seeded, user, wid(seeded, "apple"))
    assert (ap["state"], ap["mastered_at"], ap["origin"]) == ("mastered", "2026-09-15T00:00:00Z", "import")
    assert uw(seeded, user, wid(seeded, "child"))["state"] == "new" and uw(seeded, user, wid(seeded, "bank"))["state"] == "known"
    gl = uw(seeded, user, wid(seeded, "glass"))
    assert gl["state"] == "new" and gl["due_at"] is None
    assert all(l["action"] == "import" and l["context"] == "api" for l in seeded.execute("SELECT action, context FROM review_logs WHERE user_id = ?", (user,)).fetchall() for l in [dict(l)])
    assert seeded.execute("SELECT COUNT(*) FROM review_logs WHERE user_id = ? AND action = 'import'", (user,)).fetchone()[0] == 6
    assert stats(seeded, user)["added"] == 6
    assert [j["type"] for j in jobs(seeded)] == ["lookup_word"]  # imports never mass-enqueue content; only the provisional word's lookup
    # an existing row is never overwritten
    res2 = bank.import_rows(seeded, user, "json", data, NOW, TZ)
    assert [r.status for r in res2.results][:2] == ["exists", "exists"] and uw(seeded, user, wid(seeded, "abandon"))["ease"] == 2.35
    d = res2.as_dict()
    assert d["rows"] == 8 and d["exists"] == 6 and len(d["results"]) == 8


def test_import_csv_and_limits(seeded, user):
    import csv
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(bank.EXPORT_COLUMNS))
    w.writeheader()
    for row in _export_rows():
        w.writerow({k: row.get(k) for k in bank.EXPORT_COLUMNS})
    res = bank.import_rows(seeded, user, "csv", buf.getvalue(), NOW, TZ)
    assert res.rows == 8 and uw(seeded, user, wid(seeded, "abandon"))["interval_days"] == 10
    with pytest.raises(ApiError) as e:
        bank.import_rows(seeded, make_user(seeded, "carol"), "json", json.dumps({"version": 1, "words": [{"word": f"w{i}", "state": "new"} for i in range(2001)]}), NOW, TZ)
    assert e.value.code == "import_too_large" and e.value.details["rows"] == 2001
    with pytest.raises(ApiError) as e:
        bank.import_rows(seeded, user, "json", "not json", NOW, TZ)
    assert e.value.code == "import_too_large"
    with pytest.raises(ApiError):
        bank.import_rows(seeded, user, "csv", "nope,header\n1,2\n", NOW, TZ)


# --------------------------------------------------------------------------------------------- quotas
def test_daily_quota_counts_within_the_utc_day(seeded, user):
    key = f"custom:user:{user}"
    now = "2026-10-14T23:59:00Z"
    bank.check_daily_quota(seeded, key, 3, now=now, amount=2)
    assert bank.quota_used(seeded, key, now) == 2
    with pytest.raises(ApiError) as e:
        bank.check_daily_quota(seeded, key, 3, now=now, amount=2)
    assert e.value.code == "rate_limited" and e.value.details["retry_after_s"] == 60
    bank.check_daily_quota(seeded, key, 3, now="2026-10-15T00:00:00Z", amount=3)  # a new window
    assert bank.quota_used(seeded, key, "2026-10-15T00:00:00Z") == 3


def test_bank_counts(seeded, user):
    for lemma, action in (("abandon", "unfamiliar"), ("apple", "unfamiliar"), ("bank", "known")):
        act(seeded, user, wid(seeded, lemma), action)
    act(seeded, user, wid(seeded, "apple"), "mastered")
    seeded.execute("UPDATE user_words SET state = 'learning', due_at = '2026-10-14T20:00:00Z' WHERE user_id = ? AND word_id = ?", (user, wid(seeded, "abandon")))
    c = bank.bank_counts(seeded, user, now=NOW, tz=TZ)
    assert c == {"new": 0, "learning": 1, "mastered": 1, "known": 1, "removed": 0, "attention": 0, "due_today": 0}  # 20:00Z is already tomorrow in Shanghai
    seeded.execute("UPDATE user_words SET due_at = '2026-10-14T12:00:00Z' WHERE user_id = ? AND word_id = ?", (user, wid(seeded, "abandon")))
    assert bank.bank_counts(seeded, user, now=NOW, tz=TZ)["due_today"] == 1
