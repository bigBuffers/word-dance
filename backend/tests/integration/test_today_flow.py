"""/api/today* (WP4, API.md 43–47) through the TestClient with a frozen clock: build → intermediate and final grades →
duplicates → skip → master + restore → in-batch 推荐词 → stale items → /more rounds → late sessions → confusables."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token

UTC = timezone.utc
TZ = "Asia/Shanghai"
FAR = "2030-01-01T00:00:00Z"
START = datetime(2026, 10, 14, 1, 0, tzinfo=UTC)  # 09:00 Shanghai → local date 2026-10-14


# -------------------------------------------------------------------------------------------- helpers
def make_user(settings, username: str, *, onboarding: str = "done", **cols) -> tuple[int, str]:
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            cur = conn.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES (?, 'x', ?)", (username, onboarding))
            uid = int(cur.lastrowid)
            cols.setdefault("next_push_at", "2026-10-15T00:00:00Z")
            names = ["user_id", *cols]
            conn.execute(f"INSERT INTO user_settings({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", (uid, *cols.values()))
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)", (hash_token(token), uid, FAR))
        return uid, token
    finally:
        conn.close()


def as_user(client: TestClient, token: str) -> None:
    client.cookies.set("wd_session", token)


def q1(settings, sql: str, params=()):
    conn = db.connect(settings.db_path)
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def qrows(settings, sql: str, params=()) -> list[dict]:
    conn = db.connect(settings.db_path)
    try:
        return [db.row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def run(settings, sql: str, params=()) -> int:
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            return int(conn.execute(sql, params).lastrowid or 0)
    finally:
        conn.close()


def word_id(settings, lemma: str) -> int:
    return int(q1(settings, "SELECT id FROM words WHERE lemma = ?", (lemma,)))


def mark(client: TestClient, wid: int, action: str = "unfamiliar", **extra) -> dict:
    r = client.post(f"/api/words/{wid}/mark", json={"action": action, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def grade(client: TestClient, item_id: int, g: str, *, status: int = 200, event: str | None = None, elapsed_ms: int | None = 1500) -> dict:
    body: dict = {"client_event_id": event or str(uuid.uuid4()), "grade": g}
    if elapsed_ms is not None:
        body["elapsed_ms"] = elapsed_ms
    r = client.post(f"/api/today/items/{item_id}/grade", json=body)
    assert r.status_code == status, r.text
    return r.json()


def items_by_kind(today: dict, kind: str) -> list[dict]:
    return [i for i in today["batch"]["items"] if i["kind"] == kind]


def row_counts(settings) -> dict[str, int]:
    return {t: q1(settings, f"SELECT COUNT(*) FROM {t}") for t in ("push_batches", "push_items", "jobs", "review_logs", "daily_stats", "user_words")}


@pytest.fixture
def alice(client: TestClient, settings, frozen_clock) -> int:
    frozen_clock.set(START)
    uid, token = make_user(settings, "alice", daily_new_count=3, daily_screen_count=2, max_reviews=60)
    as_user(client, token)
    return uid


# ------------------------------------------------------------------------------------------- gate etc.
def test_today_requires_onboarding_and_never_builds(client: TestClient, settings, frozen_clock):
    frozen_clock.set(START)
    _, pending = make_user(settings, "pending", onboarding="screen")
    as_user(client, pending)
    r = client.get("/api/today")
    assert r.status_code == 409 and r.json()["error"]["code"] == "onboarding_required"
    assert client.get("/api/history?from=2026-10-01&to=2026-10-14").status_code == 409
    assert client.get("/api/stats").status_code == 409
    _, token = make_user(settings, "done")
    as_user(client, token)
    before = row_counts(settings)
    r = client.get("/api/today")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "none" and body["batch"] is None and body["can_build_now"] is True and body["added"] is None
    assert body["local_date"] == "2026-10-14" and body["push_time"] == "08:00" and body["next_push_at"] == "2026-10-15T00:00:00Z"
    assert body["previous_open_batch"] is None and body["suggestions_open"] == 0 and body["streak_days"] == 0 and body["goal_met"] is False
    assert row_counts(settings) == before
    assert client.post("/api/today/more", json={"source": "new"}).status_code == 409
    assert client.post("/api/today/more", json={"source": "new"}).json()["error"]["code"] == "batch_not_ready"
    assert client.post("/api/today/complete").status_code == 409


# ------------------------------------------------------------------------------------------- the flow
def test_today_flow_intermediate_final_duplicate_skip_master_restore_screen_complete(client: TestClient, settings, frozen_clock, alice):
    ids = {l: word_id(settings, l) for l in ("apple", "bank", "cat")}
    for wid in ids.values():
        mark(client, wid, context="browse")
    r = client.post("/api/today/build")
    assert r.status_code == 200, r.text
    today = r.json()
    assert today["status"] == "building" and today["can_build_now"] is False and today["batch"]["gradable"] is True
    counts = today["batch"]["counts"]
    assert (counts["total"], counts["new"], counts["screen"], counts["done"], counts["pending_content"], counts["deferred_reviews"]) == (5, 3, 2, 0, 5, 0)
    assert [i["kind"] for i in today["batch"]["items"]] == ["new", "new", "new", "screen", "screen"]
    assert all(i["result"] is None and i["requeue_at"] is None and i["image"]["kind"] == "card" for i in today["batch"]["items"])
    assert today["batch"]["trigger"] == "manual" and today["batch"]["can_request_more"] is True
    again = client.post("/api/today/build").json()
    assert again["batch"]["id"] == today["batch"]["id"] and q1(settings, "SELECT COUNT(*) FROM push_batches") == 1
    news = items_by_kind(today, "new")
    first, second, third = news

    # intermediate grade: the card enters the 10-minute step
    g1 = grade(client, first["item_id"], "good")
    assert g1["item"] == {"item_id": first["item_id"], "result": None, "skip_count": 0, "requeue_at": "2026-10-14T01:10:00Z"}
    assert g1["next_due_zh"] == "10 分钟后" and g1["mastery_suggested"] is False and g1["duplicate"] is False and g1["study_item"] is None
    assert g1["mine"]["state"] == "learning" and g1["mine"]["srs"]["step"] == 1 and g1["mine"]["srs"]["repetitions"] == 1
    assert g1["today"]["done"] == 0 and g1["today"]["new_done"] == 0
    assert qrows(settings, "SELECT result, graded_at FROM push_items WHERE id = ?", (first["item_id"],))[0] == {"result": None, "graded_at": None}
    listed = client.get("/api/today").json()
    item_now = next(i for i in listed["batch"]["items"] if i["item_id"] == first["item_id"])
    assert item_now["result"] is None and item_now["requeue_at"] == "2026-10-14T01:10:00Z"
    stats = qrows(settings, "SELECT graded, good, study_ms FROM daily_stats WHERE user_id = ?", (alice,))[0]
    assert (stats["graded"], stats["good"], stats["study_ms"]) == (1, 1, 1500)

    # 10 minutes later: the second good graduates (200, not 409)
    frozen_clock.advance(minutes=10)
    g2 = grade(client, first["item_id"], "good")
    assert g2["item"]["result"] == "good" and g2["item"]["requeue_at"] is None and g2["next_due_zh"] == "明天"
    assert g2["mine"]["srs"]["interval_days"] == 1 and g2["mine"]["srs"]["step"] == 0 and g2["mine"]["srs"]["due_at"] == "2026-10-14T16:00:00Z"
    assert g2["today"]["done"] == 1 and g2["today"]["new_done"] == 1
    assert q1(settings, "SELECT result FROM push_items WHERE id = ?", (first["item_id"],)) == "good"
    listed = client.get("/api/today").json()
    item_now = next(i for i in listed["batch"]["items"] if i["item_id"] == first["item_id"])
    assert item_now["result"] == "good" and item_now["requeue_at"] is None

    # duplicate client_event_id → stored outcome; another event on a final item → 409
    event = str(uuid.uuid4())
    g3 = grade(client, second["item_id"], "hard", event=event)
    assert g3["item"]["result"] is None and g3["item"]["requeue_at"] == "2026-10-14T01:20:00Z"
    dup = grade(client, second["item_id"], "hard", event=event)
    assert dup["duplicate"] is True and {k: v for k, v in dup.items() if k != "duplicate"} == {k: v for k, v in g3.items() if k != "duplicate"}
    assert q1(settings, "SELECT COUNT(*) FROM review_logs WHERE client_event_id = ?", (event,)) == 1
    r = client.post(f"/api/today/items/{first['item_id']}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": "good"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "item_already_graded"
    r = client.post(f"/api/today/items/{first['item_id']}/grade", json={"client_event_id": "not-a-uuid", "grade": "good"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"
    r = client.post(f"/api/today/items/{second['item_id']}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": "known"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_grade"

    # skip moves the card behind the other ungraded cards and is never final
    s = grade(client, second["item_id"], "skip")
    assert s["item"] == {"item_id": second["item_id"], "result": None, "skip_count": 1, "requeue_at": "2026-10-14T01:20:00Z"} and s["next_due_zh"] == "已跳过"
    order = [i["item_id"] for i in client.get("/api/today").json()["batch"]["items"]]
    assert order.index(second["item_id"]) > order.index(third["item_id"]) and order[-1] == first["item_id"]  # graded last

    # master → mastered; the 8-second 撤销 → restore puts the snapshot back and the item is gradable again
    m = grade(client, third["item_id"], "master", elapsed_ms=4000)
    assert m["item"]["result"] == "master" and m["next_due_zh"] == "已掌握" and m["mine"]["state"] == "mastered" and m["today"]["done"] == 2
    assert q1(settings, "SELECT state FROM user_words WHERE user_id = ? AND word_id = ?", (alice, ids["cat"])) == "mastered"
    frozen_clock.advance(seconds=3)
    rs = mark(client, ids["cat"], "restore", context="today")
    assert rs["status"] == "restored" and rs["state"] == "new" and rs["mine"]["srs"]["repetitions"] == 0
    assert qrows(settings, "SELECT result, graded_at FROM push_items WHERE id = ?", (third["item_id"],))[0] == {"result": None, "graded_at": None}
    listed = client.get("/api/today").json()
    assert listed["batch"]["counts"]["done"] == 1 and next(i for i in listed["batch"]["items"] if i["item_id"] == third["item_id"])["result"] is None
    ds = qrows(settings, "SELECT graded, mastered FROM daily_stats WHERE user_id = ?", (alice,))[0]
    assert (ds["graded"], ds["mastered"]) == (3, 0)  # good, good, hard remain; the master grade was reversed
    m2 = grade(client, third["item_id"], "master", elapsed_ms=4000)
    assert m2["item"]["result"] == "master" and m2["today"]["done"] == 2

    # in-batch 推荐词: quota exhausted (3 new rows already) → no study row, next_due_zh 明天
    scr1, scr2 = items_by_kind(today, "screen")
    v1 = grade(client, scr1["item_id"], "unfamiliar", elapsed_ms=None)
    assert v1["item"]["result"] == "unfamiliar" and v1["study_item"] is None and v1["next_due_zh"] == "明天" and v1["mine"]["state"] == "new" and v1["mine"]["origin"] == "push"
    assert q1(settings, "SELECT COUNT(*) FROM push_items WHERE batch_id = ? AND word_id = ?", (today["batch"]["id"], scr1["word"]["id"])) == 1
    run(settings, "UPDATE user_settings SET daily_new_count = 10 WHERE user_id = ?", (alice,))
    v2 = grade(client, scr2["item_id"], "unfamiliar", elapsed_ms=None)
    assert v2["item"]["result"] == "unfamiliar" and v2["study_item"] is not None and v2["next_due_zh"] == "今天"
    si = v2["study_item"]
    assert si["kind"] == "new" and si["word"]["id"] == scr2["word"]["id"] and si["result"] is None and si["mine"]["state"] == "new"
    rows = qrows(settings, "SELECT kind, result FROM push_items WHERE batch_id = ? AND word_id = ? ORDER BY position", (today["batch"]["id"], scr2["word"]["id"]))
    assert rows == [{"kind": "screen", "result": "unfamiliar"}, {"kind": "new", "result": None}]
    assert v2["today"]["screen_done"] == 2 and v2["today"]["new"] == 4
    dupv = grade(client, scr2["item_id"], "unfamiliar", elapsed_ms=None, status=409)
    assert dupv["error"]["code"] == "item_already_graded"

    # finish: remaining study cards → complete → goal_met
    frozen_clock.advance(minutes=10)
    g4 = grade(client, second["item_id"], "good")
    assert g4["item"]["result"] == "good"
    g5 = grade(client, si["item_id"], "good")
    assert g5["item"]["result"] is None and g5["today"]["done"] == 5  # first, second, third, scr1, scr2 are final; the appended card is in its step
    frozen_clock.advance(minutes=10)
    assert grade(client, si["item_id"], "good")["item"]["result"] == "good"
    summary = client.post("/api/today/complete").json()["summary"]
    assert summary["goal_met"] is True and summary["mastered"] == 1 and summary["unfamiliar"] == 2 and summary["good"] >= 4 and summary["streak_days"] == 1
    final = client.get("/api/today").json()
    assert final["goal_met"] is True and final["batch"]["completed_at"] is not None and final["batch"]["counts"]["done"] == final["batch"]["counts"]["total"]
    assert final["streak_days"] == 1


def test_again_then_left_alone_is_still_listed_tomorrow(client: TestClient, settings, frozen_clock, alice):
    w = word_id(settings, "apple")
    mark(client, w)
    today = client.post("/api/today/build").json()
    (card,) = items_by_kind(today, "new")
    g = grade(client, card["item_id"], "again")
    assert g["item"]["result"] is None and g["mine"]["srs"]["step"] == 1 and g["next_due_zh"] == "10 分钟后"
    assert q1(settings, "SELECT result FROM push_items WHERE id = ?", (card["item_id"],)) is None
    frozen_clock.advance(days=1)  # 09:00 the next day
    nxt = client.get("/api/today").json()
    assert nxt["status"] == "none" and nxt["previous_open_batch"] == {"id": today["batch"]["id"], "local_date": "2026-10-14", "remaining": 1}
    built = client.post("/api/today/build").json()
    review = items_by_kind(built, "review")
    assert [i["word"]["id"] for i in review] == [w] and review[0]["mine"]["srs"]["step"] == 1  # still due: due_at = +10 min < day end
    assert built["previous_open_batch"]["remaining"] == 1


def test_stale_items_are_hidden_and_refuse_grades_until_restored(client: TestClient, settings, frozen_clock, alice):
    ids = {l: word_id(settings, l) for l in ("apple", "bank", "cat")}
    for wid in ids.values():
        mark(client, wid)
    run(settings, "UPDATE user_settings SET daily_screen_count = 1 WHERE user_id = ?", (alice,))
    today = client.post("/api/today/build").json()
    assert today["batch"]["counts"]["total"] == 4
    apple_item = next(i for i in today["batch"]["items"] if i["word"]["id"] == ids["apple"])
    mark(client, ids["apple"], "mastered", context="bank")  # marked from a page before studying → stale
    listed = client.get("/api/today").json()
    assert ids["apple"] not in [i["word"]["id"] for i in listed["batch"]["items"]]
    assert listed["batch"]["counts"]["total"] == 3 and listed["batch"]["counts"]["new"] == 2
    r = client.post(f"/api/today/items/{apple_item['item_id']}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": "good"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    frozen_clock.advance(seconds=5)
    assert mark(client, ids["apple"], "restore", context="bank")["state"] == "new"
    listed = client.get("/api/today").json()
    assert ids["apple"] in [i["word"]["id"] for i in listed["batch"]["items"]] and listed["batch"]["counts"]["total"] == 4
    assert grade(client, apple_item["item_id"], "master")["item"]["result"] == "master"
    # a merged word is hidden (consolidation repoint pending), a screen word marked in the 词库 is hidden
    run(settings, "UPDATE words SET merged_into_word_id = ? WHERE id = ?", (ids["cat"], ids["bank"]))
    screen_item = items_by_kind(today, "screen")[0]
    mark(client, screen_item["word"]["id"], "known", context="browse")
    listed = client.get("/api/today").json()
    visible = [i["word"]["id"] for i in listed["batch"]["items"]]
    assert ids["bank"] not in visible and screen_item["word"]["id"] not in visible and listed["batch"]["counts"]["total"] == 2
    bank_item = next(i for i in today["batch"]["items"] if i["word"]["id"] == ids["bank"])
    assert client.post(f"/api/today/items/{bank_item['item_id']}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": "good"}).status_code == 409
    assert client.post(f"/api/today/items/{screen_item['item_id']}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": "unfamiliar"}).status_code == 409
    # graded items are history and always stay
    assert apple_item["item_id"] in [i["item_id"] for i in listed["batch"]["items"]]


def test_more_rounds_building_batch_and_no_duplicates(client: TestClient, settings, frozen_clock, alice):
    run(settings, "UPDATE user_settings SET daily_new_count = 1, daily_screen_count = 1 WHERE user_id = ?", (alice,))
    for lemma in ("apple", "bank", "cat", "dog", "glass"):
        mark(client, word_id(settings, lemma))
    today = client.post("/api/today/build").json()
    assert today["status"] == "building" and today["batch"]["counts"]["new"] == 1
    r1 = client.post("/api/today/more", json={"source": "new", "count": 2})
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["added"] == 2 and b1["batch"]["extra_rounds"] == 1 and b1["batch"]["counts"]["extra"] == 2 and b1["status"] == "building"
    r2 = client.post("/api/today/more", json={"source": "screen"}).json()
    assert r2["added"] == 10 and r2["batch"]["counts"]["screen"] == 11 and r2["batch"]["extra_rounds"] == 2
    r3 = client.post("/api/today/more", json={"source": "new", "count": 20}).json()
    assert r3["added"] == 2 and r3["batch"]["extra_rounds"] == 3 and r3["batch"]["can_request_more"] is False
    r4 = client.post("/api/today/more", json={"source": "new"})
    assert r4.status_code == 429 and r4.json()["error"]["code"] == "rate_limited" and r4.headers.get("Retry-After")
    study_words = [i["word"]["id"] for i in r3["batch"]["items"] if i["kind"] in ("review", "new", "extra")]
    assert len(study_words) == len(set(study_words)) == 5  # every bank word exactly once as new/extra
    all_words = [(i["word"]["id"], i["kind"]) for i in r3["batch"]["items"]]
    assert len(all_words) == len(set(all_words))
    assert client.post("/api/today/more", json={"source": "bogus"}).status_code == 400


def test_late_session_yesterdays_batch_is_gradable_older_is_not(client: TestClient, settings, frozen_clock, alice):
    for lemma in ("apple", "bank"):
        mark(client, word_id(settings, lemma))
    today = client.post("/api/today/build").json()
    bid = today["batch"]["id"]
    first, second = items_by_kind(today, "new")
    assert grade(client, first["item_id"], "master")["item"]["result"] == "master"
    frozen_clock.set(datetime(2026, 10, 14, 16, 30, tzinfo=UTC))  # 00:30 the next local day
    t = client.get("/api/today").json()
    assert t["status"] == "none" and t["local_date"] == "2026-10-15"
    assert t["previous_open_batch"] == {"id": bid, "local_date": "2026-10-14", "remaining": 1}
    y = client.get(f"/api/batches/{bid}").json()
    assert y["batch"]["gradable"] is True and y["local_date"] == "2026-10-14" and y["batch"]["can_request_more"] is False and y["status"] == "building"
    g = grade(client, second["item_id"], "good")
    assert g["item"]["result"] is None and g["item"]["requeue_at"] == "2026-10-14T16:40:00Z"
    frozen_clock.advance(minutes=10)
    assert grade(client, second["item_id"], "good")["item"]["result"] == "good"
    assert client.get("/api/today").json()["previous_open_batch"] is None
    y2 = client.get(f"/api/batches/{bid}").json()
    assert y2["batch"]["gradable"] is False and y2["goal_met"] is True  # nothing left to grade
    # two days later: replay only
    frozen_clock.set(datetime(2026, 10, 16, 1, 0, tzinfo=UTC))
    old = client.get(f"/api/batches/{bid}").json()
    assert old["batch"]["gradable"] is False
    mark(client, word_id(settings, "cat"))
    run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) SELECT ?, word_id, id, 'new', 9 FROM user_words WHERE user_id = ? AND word_id = ?", (bid, alice, word_id(settings, "cat")))
    item = q1(settings, "SELECT id FROM push_items WHERE batch_id = ? AND position = 9", (bid,))
    r = client.post(f"/api/today/items/{item}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": "good"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "batch_not_found"
    assert client.get(f"/api/batches/{bid}").json()["batch"]["gradable"] is False
    # someone else's batch → 404, unknown → 404
    _, bob = make_user(settings, "bob")
    as_user(client, bob)
    assert client.get(f"/api/batches/{bid}").status_code == 404
    assert client.get("/api/batches/999").status_code == 404


def test_confusables_and_suggestions_open_on_today(client: TestClient, settings, frozen_clock, alice):
    w = word_id(settings, "absorb")
    mark(client, w)
    run(settings, "UPDATE user_settings SET daily_screen_count = 0 WHERE user_id = ?", (alice,))
    run(
        settings,
        "INSERT INTO bank_suggestions(user_id, type, status, payload_json) VALUES (?, 'confusable_group', 'accepted', ?)",
        (alice, json.dumps({"group": ["absorb", "absurd", "abstract"]})),
    )
    run(
        settings,
        "INSERT INTO bank_suggestions(user_id, type, status, payload_json, expires_at) VALUES (?, 'fix_spelling', 'open', ?, '2026-11-13T00:00:00Z')",
        (alice, json.dumps({"from": "absorb", "to": "absorbs", "note_zh": "x"})),
    )
    today = client.post("/api/today/build").json()
    (card,) = items_by_kind(today, "new")
    assert card["word"]["confusables"] == ["absurd", "abstract"] and card["word"]["forms"] == ["absorbed", "absorbing", "absorbs"]
    assert today["suggestions_open"] == 1
    detail = client.get(f"/api/words/{w}").json()
    assert detail["word"]["confusables"] == card["word"]["confusables"]
