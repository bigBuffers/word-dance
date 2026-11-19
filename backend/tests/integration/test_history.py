"""/api/history, /api/history/batches, /api/batches/{id}, /api/stats (WP4, API.md 48–51): day aggregates from
daily_stats, offline days from the scheduler's downtime events, heatmap, streaks, stubborn words, range validation."""

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
FAR = "2030-01-01T00:00:00Z"
START = datetime(2026, 10, 10, 1, 0, tzinfo=UTC)  # 09:00 Shanghai 2026-10-10


def make_user(settings, username: str, **cols) -> tuple[int, str]:
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            uid = int(conn.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES (?, 'x', 'done')", (username,)).lastrowid)
            cols.setdefault("next_push_at", "2026-10-11T00:00:00Z")
            names = ["user_id", *cols]
            conn.execute(f"INSERT INTO user_settings({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", (uid, *cols.values()))
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)", (hash_token(token), uid, FAR))
        return uid, token
    finally:
        conn.close()


def run(settings, sql: str, params=()) -> None:
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            conn.execute(sql, params)
    finally:
        conn.close()


def word_id(settings, lemma: str) -> int:
    conn = db.connect(settings.db_path)
    try:
        return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0])
    finally:
        conn.close()


def grade_all_new(client: TestClient, today: dict, g: str = "good") -> None:
    for item in today["batch"]["items"]:
        if item["kind"] in ("review", "new", "extra"):
            r = client.post(f"/api/today/items/{item['item_id']}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": g, "elapsed_ms": 30_000})
            assert r.status_code == 200, r.text


@pytest.fixture
def alice(client: TestClient, settings, frozen_clock) -> int:
    frozen_clock.set(START)
    uid, token = make_user(settings, "alice", daily_new_count=5, daily_screen_count=0)
    client.cookies.set("wd_session", token)
    return uid


def test_history_days_streak_heatmap_batches_and_stats(client: TestClient, settings, frozen_clock, alice):
    # day 1 (10-10): two words mastered through the cards; day 2 (10-11): one card graded good (step) ; day 3: nothing; day 4 (10-13): build only
    for lemma in ("apple", "bank"):
        assert client.post(f"/api/words/{word_id(settings, lemma)}/mark", json={"action": "unfamiliar"}).status_code == 200
    d1 = client.post("/api/today/build").json()
    grade_all_new(client, d1, "master")
    assert client.post("/api/today/complete").json()["summary"]["goal_met"] is True
    frozen_clock.advance(days=1)
    assert client.post(f"/api/words/{word_id(settings, 'cat')}/mark", json={"action": "unfamiliar"}).status_code == 200
    d2 = client.post("/api/today/build").json()
    grade_all_new(client, d2, "good")  # intermediate: graded counts, batch not complete
    frozen_clock.advance(days=3)  # 10-14 with a gap on 10-12 and 10-13
    assert client.post(f"/api/words/{word_id(settings, 'dog')}/mark", json={"action": "unfamiliar"}).status_code == 200
    d4 = client.post("/api/today/build").json()
    # a downtime gap over 10-12 (no batch) and into 10-13 09:00 local; 10-13 has no batch either
    run(settings, "INSERT INTO system_events(kind, detail_json) VALUES ('downtime', ?)", (json.dumps({"from": "2026-10-11T20:00:00Z", "to": "2026-10-13T01:00:00Z"}),))
    r = client.get("/api/history?from=2026-10-09&to=2026-10-14")
    assert r.status_code == 200, r.text
    body = r.json()
    days = {d["date"]: d for d in body["days"]}
    assert list(days) == ["2026-10-09", "2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14"]
    assert (days["2026-10-10"]["graded"], days["2026-10-10"]["mastered"], days["2026-10-10"]["added"], days["2026-10-10"]["study_minutes"]) == (2, 2, 2, 1)
    assert (days["2026-10-10"]["batch_id"], days["2026-10-10"]["batch_total"], days["2026-10-10"]["batch_done"]) == (d1["batch"]["id"], 2, 2)
    # `cat` (the only card of 10-11, still in its step) was re-selected into 10-14's batch as a review: its 10-11 copy is
    # superseded (DESIGN §6.3) and no longer counted there — the card moved to today, where it is the single gradable row
    assert (days["2026-10-11"]["graded"], days["2026-10-11"]["good"], days["2026-10-11"]["batch_done"], days["2026-10-11"]["batch_total"]) == (1, 1, 0, 0)
    assert days["2026-10-11"]["batch_id"] == d2["batch"]["id"]  # apple/bank are mastered → no reviews; `cat` is the only (new) card, still in its step
    assert [i["word"]["id"] for i in d4["batch"]["items"] if i["kind"] == "review"] == [word_id(settings, "cat")]
    assert days["2026-10-12"]["batch_id"] is None and days["2026-10-12"]["offline"] is True
    assert days["2026-10-13"]["batch_id"] is None and days["2026-10-13"]["offline"] is True
    assert days["2026-10-11"]["offline"] is False and days["2026-10-14"]["offline"] is False and days["2026-10-09"]["offline"] is False
    assert days["2026-10-14"]["batch_id"] == d4["batch"]["id"] and days["2026-10-14"]["graded"] == 0
    assert body["streak_days"] == 0 and body["longest_streak"] == 2  # 10-10 + 10-11; today/yesterday have no grades
    # stats
    run(settings, "UPDATE user_words SET times_added = 3 WHERE user_id = ? AND word_id = ?", (alice, word_id(settings, "apple")))
    s = client.get("/api/stats").json()
    assert s["bank"]["mastered"] == 2 and s["bank"]["new"] >= 1 and s["total_mastered"] == 2 and s["total_graded"] == 3
    assert s["streak_days"] == 0 and s["longest_streak"] == 2 and s["custom_words"] == 0
    assert s["today"] == {"done": 0, "total": d4["batch"]["counts"]["total"]}
    assert [w["lemma"] for w in s["stubborn"]] == ["apple"]
    assert len(s["heatmap"]) == 84 and s["heatmap"][-1]["date"] == "2026-10-14"
    heat = {h["date"]: h for h in s["heatmap"]}
    assert heat["2026-10-10"] == {"date": "2026-10-10", "graded": 2, "goal_met": True} and heat["2026-10-11"]["goal_met"] is False and heat["2026-10-11"]["graded"] == 1
    assert {st["stage"] for st in s["stages"]} == {"xs", "zk", "gk", "cet4", "cet6"} and all(st["total"] > 0 for st in s["stages"])
    # today's grade makes the streak 1 (ends today)
    grade_all_new(client, d4, "good")
    assert client.get("/api/stats").json()["streak_days"] == 1
    # batches page, newest first
    p = client.get("/api/history/batches?page=1&page_size=2").json()
    assert p["total"] == 3 and p["page_size"] == 2 and [b["local_date"] for b in p["items"]] == ["2026-10-14", "2026-10-11"]
    assert p["items"][1]["counts"]["done"] == 0 and p["items"][1]["status"] == "building" and p["items"][1]["completed_at"] is None
    p2 = client.get("/api/history/batches?page=2&page_size=2").json()
    assert [b["local_date"] for b in p2["items"]] == ["2026-10-10"] and p2["items"][0]["completed_at"] is not None and p2["items"][0]["counts"]["done"] == 2
    one = client.get(f"/api/batches/{d1['batch']['id']}").json()
    assert one["batch"]["gradable"] is False and one["batch"]["counts"]["done"] == 2 and one["local_date"] == "2026-10-10"


def test_heatmap_goal_met_shares_the_stale_aware_predicate_of_today(client: TestClient, settings, frozen_clock, alice):
    """Two cards mastered in the session, the third marked 已掌握 from the 词库 page (stale, hidden) and no
    POST /today/complete: the heatmap (the 记录 page's calendar) must say what the 今日 page and DayStats say — the goal was met."""
    for lemma in ("apple", "bank", "cat"):
        assert client.post(f"/api/words/{word_id(settings, lemma)}/mark", json={"action": "unfamiliar"}).status_code == 200
    today = client.post("/api/today/build").json()
    cards = [i for i in today["batch"]["items"] if i["kind"] == "new"]
    assert len(cards) == 3
    for item in cards[:2]:
        r = client.post(f"/api/today/items/{item['item_id']}/grade", json={"client_event_id": str(uuid.uuid4()), "grade": "master", "elapsed_ms": 3000})
        assert r.status_code == 200, r.text
    assert client.post(f"/api/words/{cards[2]['word']['id']}/mark", json={"action": "mastered", "context": "bank"}).status_code == 200
    t = client.get("/api/today").json()
    assert t["goal_met"] is True and (t["batch"]["counts"]["done"], t["batch"]["counts"]["total"]) == (2, 2) and t["batch"]["completed_at"] is None
    s = client.get("/api/stats").json()
    assert s["heatmap"][-1]["date"] == "2026-10-10" and s["heatmap"][-1]["goal_met"] is True and s["today"] == {"done": 2, "total": 2}
    h = client.get("/api/history?from=2026-10-10&to=2026-10-10").json()["days"][0]
    assert (h["batch_done"], h["batch_total"]) == (2, 2)
    frozen_clock.advance(days=3)  # the cell stays lit later on, completed_at never having been written
    heat = {d["date"]: d for d in client.get("/api/stats").json()["heatmap"]}
    assert heat["2026-10-10"]["goal_met"] is True
    assert client.get(f"/api/batches/{today['batch']['id']}").json()["batch"]["completed_at"] is None


def test_history_range_validation(client: TestClient, settings, frozen_clock, alice):
    assert client.get("/api/history?from=2026-10-01&to=2025-09-01").status_code == 400
    assert client.get("/api/history?from=2025-01-01&to=2026-10-14").status_code == 400  # > 370 days
    assert client.get("/api/history?to=2026-10-14").status_code == 400
    assert client.get("/api/history?from=2026-13-01&to=2026-10-14").status_code == 400
    r = client.get("/api/history?from=2025-10-10&to=2026-10-14")  # exactly 370 days
    assert r.status_code == 200 and len(r.json()["days"]) == 370
    assert client.get("/api/history/batches?page=0").status_code == 400
    assert client.get("/api/history/batches").json() == {"items": [], "page": 1, "page_size": 50, "total": 0}


def test_streak_counts_consecutive_graded_days_ending_today_or_yesterday(client: TestClient, settings, frozen_clock, alice):
    for d in ("2026-10-07", "2026-10-08", "2026-10-09"):
        run(settings, "INSERT INTO daily_stats(user_id, local_date, graded) VALUES (?, ?, 3)", (alice, d))
    run(settings, "INSERT INTO daily_stats(user_id, local_date, graded, screened) VALUES (?, '2026-10-04', 0, 5)", (alice,))  # screening alone does not count
    s = client.get("/api/stats").json()
    assert s["streak_days"] == 3 and s["longest_streak"] == 3  # ends yesterday (10-09), today is 10-10
    frozen_clock.advance(days=1)
    assert client.get("/api/stats").json()["streak_days"] == 0  # gap of a full day
    h = client.get("/api/history?from=2026-10-01&to=2026-10-11").json()
    assert h["longest_streak"] == 3 and h["days"][3]["screened"] == 5 and h["days"][3]["graded"] == 0
