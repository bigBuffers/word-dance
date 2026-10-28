"""/api/bank* (WP3, API.md 33–38, 75): listing + counts, bulk add statuses, add-word, PATCH note/attention,
accept-suggestion, consolidate-now, import round trips (JSON incl. the review_logs reduction, CSV)."""

from __future__ import annotations

import csv
import io
import json
import secrets

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token
from wd.services import batches

FAR = "2030-01-01T00:00:00Z"
TZ = "Asia/Shanghai"
EXPORT_COLUMNS = ["word", "phonetic", "translation", "state", "origin", "note", "times_added", "added_at", "mastered_at", "ease", "interval_days", "repetitions", "lapses", "due_at"]


# -------------------------------------------------------------------------------------------- helpers
def make_user(settings, username: str, *, role: str = "user") -> tuple[int, str]:
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            cur = conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done')", (username, role))
            uid = int(cur.lastrowid)
            conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
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


def qrow(settings, sql: str, params=()) -> dict | None:
    conn = db.connect(settings.db_path)
    try:
        return db.row_to_dict(conn.execute(sql, params).fetchone())
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


def export_json(settings, user_id: int, *, review_logs: int = 0) -> dict:
    """The endpoint-11 JSON shape built straight from the tables (the export route is WP2's)."""
    rows = qrows(
        settings,
        "SELECT w.lemma AS word, w.phonetic, w.translation, uw.state, uw.origin, uw.note, uw.times_added, uw.added_at, uw.mastered_at, uw.ease, "
        "uw.interval_days, uw.repetitions, uw.lapses, uw.due_at FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? ORDER BY uw.id",
        (user_id,),
    )
    logs = [{"created_at": "2026-10-01T00:00:00Z", "word": rows[i % len(rows)]["word"] if rows else "x", "action": "good", "context": "today", "prev_state": "learning", "new_state": "learning", "prev_interval": 3, "new_interval": 8} for i in range(review_logs)]
    return {"version": 1, "exported_at": "2026-10-14T00:00:00Z", "username": "alice", "words": rows, "review_logs": logs}


def install_fake_batches(monkeypatch) -> list:
    """Records the ``batches.append_to_today`` calls the bank makes (a minimal stand-in for WP4's implementation)."""
    calls: list = []

    def append_to_today(conn, user_id, word_id, kind, now):
        calls.append((user_id, word_id, kind))
        batch = conn.execute("SELECT id FROM push_batches WHERE user_id = ? AND local_date = '2026-10-14'", (user_id,)).fetchone()
        if batch is None:
            return None
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM push_items WHERE batch_id = ?", (batch[0],)).fetchone()[0]
        return int(conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, ?, ?)", (batch[0], word_id, kind, pos)).lastrowid)

    monkeypatch.setattr(batches, "append_to_today", append_to_today)
    return calls


@pytest.fixture
def alice(client: TestClient, settings) -> int:
    uid, token = make_user(settings, "alice")
    as_user(client, token)
    return uid


# ----------------------------------------------------------------------------------------------- list
def test_bank_list_counts_filters_and_sorts(client: TestClient, settings, alice, frozen_clock):
    r = client.get("/api/bank")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "page": 1, "page_size": 50, "total": 0, "counts": {"new": 0, "learning": 0, "mastered": 0, "known": 0, "removed": 0, "attention": 0, "due_today": 0}}
    ids = {l: word_id(settings, l) for l in ("abandon", "apple", "bank", "glass", "child")}
    for l in ("abandon", "apple", "bank", "glass"):
        frozen_clock.advance(seconds=1)
        assert client.post(f"/api/words/{ids[l]}/mark", json={"action": "unfamiliar", "context": "browse"}).status_code == 200
    client.post(f"/api/words/{ids['child']}/mark", json={"action": "known"})
    client.post(f"/api/words/{ids['bank']}/mark", json={"action": "mastered"})
    client.post(f"/api/words/{ids['glass']}/mark", json={"action": "remove"})
    run(settings, "UPDATE user_words SET state = 'learning', ease = 2.1, due_at = '2026-10-14T10:00:00Z', interval_days = 3 WHERE user_id = ? AND word_id = ?", (alice, ids["apple"]))
    run(settings, "UPDATE user_words SET needs_attention = 1, attention_msg = 'x' WHERE user_id = ? AND word_id = ?", (alice, ids["abandon"]))
    b = client.get("/api/bank").json()
    assert [i["lemma"] for i in b["items"]] == ["apple", "abandon"]  # active = new+learning, newest first
    assert b["counts"] == {"new": 1, "learning": 1, "mastered": 1, "known": 1, "removed": 1, "attention": 1, "due_today": 1}
    item = b["items"][0]
    assert item["mine"]["state"] == "learning" and item["my_state"] == "learning" and item["mine"]["srs"]["ease"] == 2.1
    assert set(item) - {"mine"} == set(client.get("/api/vocab?page_size=1").json()["items"][0])
    get = lambda **params: [i["lemma"] for i in client.get("/api/bank", params=params).json()["items"]]
    assert get(state="new") == ["abandon"] and get(state="learning") == ["apple"] and get(state="mastered") == ["bank"]
    assert get(state="known") == ["child"] and get(state="removed") == ["glass"] and get(state="attention") == ["abandon"]
    assert get(sort="alpha") == ["abandon", "apple"] and get(sort="due") == ["apple", "abandon"] and get(sort="ease") == ["apple", "abandon"]
    run(settings, "UPDATE user_words SET times_added = 3 WHERE user_id = ? AND word_id = ?", (alice, ids["abandon"]))
    assert get(sort="times_added") == ["abandon", "apple"]
    assert get(q="ab") == ["abandon"] and get(q="苹果") == ["apple"] and get(q="zz") == []
    assert get(origin="browse") == ["apple", "abandon"] and get(origin="custom") == []
    assert client.get("/api/bank?state=bogus").status_code == 400
    assert client.get("/api/bank?page=2").json()["items"] == []
    assert client.get("/api/bank").json()["total"] == 2


# ------------------------------------------------------------------------------------------------ add
def test_bulk_add_statuses_over_http(client: TestClient, settings, alice, frozen_clock):
    client.post(f"/api/words/{word_id(settings, 'abandon')}/mark", json={"action": "unfamiliar"})
    r = client.post("/api/bank/add", json={"text": "abandoned, children\nubiquitous；bases\tabc123", "note": "from work"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert [x["status"] for x in b["results"]] == ["exists", "added", "pending_ai", "ambiguous", "invalid"]
    assert (b["added"], b["readded"], b["exists"], b["pending_ai"], b["ambiguous"], b["invalid"]) == (1, 0, 1, 1, 1, 1)
    res = {x["input"]: x for x in b["results"]}
    assert res["children"]["word"]["lemma"] == "child" and res["children"]["lemma_note_zh"] == "已归为原形 child（复数）" and res["children"]["resolved_via"] == "form"
    assert res["children"]["mine"]["origin"] == "custom" and res["children"]["mine"]["note"] == "from work" and res["children"]["mine"]["input_text"] == "children"
    assert res["ubiquitous"]["resolved_via"] == "provisional" and res["ubiquitous"]["word"]["is_valid_english"] is None and res["ubiquitous"]["word"]["is_public"] is False
    assert [c["lemma"] for c in res["bases"]["candidates"]] == ["base", "basis"]
    assert res["abc123"]["error"] and res["abc123"]["word"] is None
    assert all(x["added_to_today"] is False for x in b["results"])
    prov = res["ubiquitous"]["word"]["id"]
    job = qrow(settings, "SELECT * FROM jobs WHERE type = 'lookup_word'")
    assert job["dedupe_key"] == f"lookup:{prov}" and job["priority"] == 10
    # the WP1 resolver debounces on the system clock (its frozen signature carries no clock): run_after ≈ real now + 20 s
    from datetime import datetime, timezone

    from wd.clock import parse_iso

    delay = (parse_iso(job["run_after"]) - datetime.now(timezone.utc)).total_seconds()
    assert 10 <= delay <= 25
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND payload_json LIKE ?", (f'%"word_id":{prov}%',)) == 0
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content'") == 2  # abandon (mark) + child
    assert client.get("/api/bank").json()["counts"]["new"] == 3
    r = client.post("/api/bank/add", json={"text": ",".join(f"w{i}" for i in range(51))})
    assert r.status_code == 400 and r.json()["error"]["code"] == "too_many_words"
    assert client.post("/api/bank/add", json={"text": ""}).status_code == 400
    assert client.post("/api/bank/add", json={"text": "a" * 4001}).status_code == 400


def test_bulk_add_daily_quota(client: TestClient, settings, alice):
    run(settings, "INSERT INTO auth_throttle(key, window_start, count) VALUES (?, '2026-10-14T00:00:00Z', 199)", (f"custom:user:{alice}",))
    assert client.post("/api/bank/add", json={"text": "abandon"}).status_code == 200
    r = client.post("/api/bank/add", json={"text": "apple"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and "Retry-After" in r.headers


def test_study_today_appends_extra_only_for_validated_words(client: TestClient, settings, alice, monkeypatch):
    calls = install_fake_batches(monkeypatch)
    run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'building', 'manual')", (alice,))
    r = client.post("/api/bank/add", json={"text": "abandon, ubiquitous, bases", "study_today": True}).json()
    res = {x["input"]: x for x in r["results"]}
    assert res["abandon"]["added_to_today"] is True and res["ubiquitous"]["status"] == "pending_ai" and res["ubiquitous"]["added_to_today"] is False
    assert res["bases"]["added_to_today"] is False
    assert calls == [(alice, word_id(settings, "abandon"), "extra")]
    assert q1(settings, "SELECT kind FROM push_items") == "extra"


def test_add_word_by_id(client: TestClient, settings, alice, monkeypatch):
    base = word_id(settings, "base")
    r = client.post("/api/bank/add-word", json={"word_id": base, "note": "n"})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "added" and r.json()["mine"]["note"] == "n" and r.json()["mine"]["origin"] == "custom" and r.json()["input"] == "base"
    r = client.post("/api/bank/add-word", json={"word_id": base})
    assert r.status_code == 200 and r.json()["status"] == "exists"
    client.post(f"/api/words/{base}/mark", json={"action": "mastered"})
    r = client.post("/api/bank/add-word", json={"word_id": base})
    assert r.status_code == 201 and r.json()["status"] == "readded" and r.json()["mine"]["times_added"] == 2
    assert client.post("/api/bank/add-word", json={"word_id": 999999}).status_code == 404
    bob, bob_token = make_user(settings, "bob")
    as_user(client, bob_token)
    prov = client.post("/api/bank/add", json={"text": "zzqx"}).json()["results"][0]["word"]["id"]
    _, carol_token = make_user(settings, "carol")
    as_user(client, carol_token)
    assert client.post("/api/bank/add-word", json={"word_id": prov}).status_code == 404  # invisible to a non-holder


# ---------------------------------------------------------------------------------------------- patch
def test_patch_note(client: TestClient, settings, alice):
    w = word_id(settings, "abandon")
    client.post(f"/api/words/{w}/mark", json={"action": "unfamiliar"})
    r = client.patch(f"/api/bank/{w}", json={"note": "  remember this  "})
    assert r.status_code == 200 and r.json()["note"] == "remember this"
    assert client.patch(f"/api/bank/{w}", json={"note": None}).json()["note"] is None
    assert q1(settings, "SELECT COUNT(*) FROM review_logs WHERE user_id = ? AND action = 'note'", (alice,)) == 2
    assert client.patch(f"/api/bank/{w}", json={}).status_code == 400
    assert client.patch(f"/api/bank/{word_id(settings, 'apple')}", json={"note": "x"}).status_code == 404  # not in the bank
    assert client.patch(f"/api/bank/{w}", json={"note": "x" * 501}).status_code == 400


def test_patch_attention_retry_and_keep(client: TestClient, settings, alice):
    bob, bob_token = make_user(settings, "bob")
    prov = client.post("/api/bank/add", json={"text": "zzqx"}).json()["results"][0]["word"]["id"]
    as_user(client, bob_token)
    client.post("/api/bank/add", json={"text": "zzqx"})
    run(settings, "UPDATE jobs SET status = 'dead' WHERE dedupe_key = ?", (f"lookup:{prov}",))
    run(settings, "UPDATE user_words SET needs_attention = 1, attention_msg = '暂时无法校验，请稍后重试或检查拼写' WHERE word_id = ?", (prov,))
    _, alice_token = (alice, next(t for _, t in [make_user(settings, "alice-2")]))
    conn = db.connect(settings.db_path)
    try:
        token = secrets.token_urlsafe(32)
        with db.tx(conn):
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)", (hash_token(token), alice, FAR))
    finally:
        conn.close()
    as_user(client, token)
    assert client.get("/api/bank").json()["counts"]["attention"] == 1
    assert [i["lemma"] for i in client.get("/api/bank?state=attention").json()["items"]] == ["zzqx"]
    r = client.patch(f"/api/bank/{prov}", json={"attention": "retry"})
    assert r.status_code == 200, r.text
    assert r.json()["needs_attention"] is True and r.json()["attention_msg"] is None
    live = qrows(settings, "SELECT * FROM jobs WHERE type = 'lookup_word' AND status IN ('queued','running')")
    assert len(live) == 1 and live[0]["dedupe_key"] == f"lookup:{prov}" and live[0]["run_after"] == "2026-10-14T00:00:00Z"
    assert client.get("/api/bank").json()["counts"]["attention"] == 1
    as_user(client, bob_token)
    client.patch(f"/api/bank/{prov}", json={"attention": "retry"})
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'lookup_word' AND status IN ('queued','running')") == 1
    # retry on a validated word → 409 invalid_transition
    as_user(client, token)
    w = word_id(settings, "abandon")
    client.post(f"/api/words/{w}/mark", json={"action": "unfamiliar"})
    r = client.patch(f"/api/bank/{w}", json={"attention": "retry"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    # keep on an is_valid_english=0 word → 仅收藏: flag cleared, stays in the active list
    run(settings, "UPDATE words SET is_valid_english = 0, is_public = 0, content_state = 'failed' WHERE id = ?", (prov,))
    run(settings, "UPDATE user_words SET needs_attention = 1, attention_msg = '未识别为英文单词：无此词' WHERE word_id = ? AND user_id = ?", (prov, alice))
    r = client.patch(f"/api/bank/{prov}", json={"attention": "keep"})
    assert r.status_code == 200 and r.json()["needs_attention"] is False and r.json()["attention_msg"] is None and r.json()["state"] == "new"
    assert client.get("/api/bank").json()["counts"]["attention"] == 0
    assert "zzqx" in [i["lemma"] for i in client.get("/api/bank?state=active").json()["items"]]
    item = next(i for i in client.get("/api/bank").json()["items"] if i["lemma"] == "zzqx")
    assert item["is_valid_english"] is False and item["mine"]["needs_attention"] is False  # the client derives the 仅收藏 chip from this
    assert qrows(settings, "SELECT action, result_json FROM review_logs WHERE user_id = ? AND word_id = ? AND action = 'attention'", (alice, prov)) == [
        {"action": "attention", "result_json": '{"decision": "retry"}'},
        {"action": "attention", "result_json": '{"decision": "keep"}'},
    ]
    # never selected by build_batch: DESIGN §6.3 step 3 requires is_valid_english = 1
    assert q1(settings, "SELECT COUNT(*) FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? AND uw.state = 'new' AND uw.needs_attention = 0 AND w.is_valid_english = 1", (alice,)) == 1
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND payload_json LIKE ?", (f'%"word_id":{prov}%',)) == 0
    assert client.patch(f"/api/bank/{prov}", json={"attention": "retry"}).status_code == 409
    assert client.patch(f"/api/bank/{prov}", json={"attention": "nope"}).status_code == 400


# ------------------------------------------------------------------------------------ accept-suggestion
def test_accept_suggestion_replaces_the_flagged_word(client: TestClient, settings, alice):
    prov = client.post("/api/bank/add", json={"text": "recieve", "note": "typo note"}).json()["results"][0]["word"]["id"]
    receive = word_id(settings, "receive")
    r = client.post(f"/api/bank/{prov}/accept-suggestion")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    run(settings, "UPDATE user_words SET needs_attention = 1, attention_msg = '是否改为 “receive”？', suggested_word_id = ? WHERE word_id = ? AND user_id = ?", (receive, prov, alice))
    item = client.get("/api/bank?state=attention").json()["items"][0]
    assert item["mine"]["suggested_word"]["lemma"] == "receive"
    r = client.post(f"/api/bank/{prov}/accept-suggestion")
    assert r.status_code == 200, r.text
    assert r.json()["removed_word_id"] == prov and r.json()["mine"]["word_id"] == receive and r.json()["mine"]["origin"] == "custom"
    assert r.json()["mine"]["note"] == "typo note" and r.json()["mine"]["input_text"] == "recieve"
    old = qrow(settings, "SELECT * FROM user_words WHERE user_id = ? AND word_id = ?", (alice, prov))
    assert old["state"] == "removed" and old["suggested_word_id"] is None and old["needs_attention"] == 0
    logs = [l["action"] for l in qrows(settings, "SELECT action FROM review_logs WHERE user_id = ? ORDER BY id", (alice,))]
    assert logs == ["add_custom", "add_custom", "remove"]
    assert client.get("/api/bank").json()["counts"] == {"new": 1, "learning": 0, "mastered": 0, "known": 0, "removed": 1, "attention": 0, "due_today": 0}
    assert client.post(f"/api/bank/{word_id(settings, 'apple')}/accept-suggestion").status_code == 404


# ------------------------------------------------------------------------------------------ consolidate
def test_consolidate_now(client: TestClient, settings, alice):
    r = client.post("/api/bank/consolidate")
    assert r.status_code == 202, r.text
    job = qrow(settings, "SELECT * FROM jobs WHERE id = ?", (r.json()["job_id"],))
    assert job["type"] == "consolidate_bank" and job["priority"] == 10 and job["dedupe_key"] == f"consolidate:{alice}:2026-10-14"
    assert json.loads(job["payload_json"]) == {"user_id": alice, "trigger": "manual"}
    assert client.post("/api/bank/consolidate").json()["job_id"] == job["id"]  # folded into the live job
    run(settings, "INSERT INTO consolidation_runs(user_id, trigger, status, started_at) VALUES (?, 'manual', 'done', '2026-10-13T23:30:00Z')", (alice,))
    r = client.post("/api/bank/consolidate")
    assert r.status_code == 429 and r.json()["error"]["details"]["retry_after_s"] == 1800
    run(settings, "INSERT INTO kv(key, value) VALUES ('claude.enabled', '0')")
    r = client.post("/api/bank/consolidate")
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_disabled"


# ------------------------------------------------------------------------------------------------ import
def _seed_alice_bank(client: TestClient, settings, alice: int) -> None:
    for l in ("abandon", "apple", "child", "glass"):
        client.post(f"/api/words/{word_id(settings, l)}/mark", json={"action": "unfamiliar", "note": f"note {l}"})
    run(settings, "UPDATE user_words SET state = 'learning', ease = 2.35, interval_days = 10, repetitions = 7, lapses = 1, due_at = '2026-10-20T16:00:00Z', times_added = 2 WHERE user_id = ? AND word_id = ?", (alice, word_id(settings, "abandon")))
    client.post(f"/api/words/{word_id(settings, 'apple')}/mark", json={"action": "mastered"})
    client.post(f"/api/words/{word_id(settings, 'bank')}/mark", json={"action": "known"})
    client.post(f"/api/words/{word_id(settings, 'glass')}/mark", json={"action": "remove"})
    client.post("/api/bank/add", json={"text": "zzqx"})  # a provisional word in the export


def test_import_json_round_trip_into_a_fresh_account(client: TestClient, settings, alice):
    _seed_alice_bank(client, settings, alice)
    export = export_json(settings, alice, review_logs=3)
    assert len(export["words"]) == 6 and export["review_logs"]
    _, bob_token = make_user(settings, "bob")
    as_user(client, bob_token)
    r = client.post("/api/bank/import", json={"format": "json", "data": json.dumps(export)})  # the review_logs key is ignored
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["rows"] == 6 and b["skipped"] == 0 and b["added"] == 5 and b["pending_ai"] == 1 and len(b["results"]) == 6
    bob = q1(settings, "SELECT id FROM users WHERE username = 'bob'")
    ab = qrow(settings, "SELECT uw.* FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? AND w.lemma = 'abandon'", (bob,))
    assert (ab["state"], ab["origin"], ab["ease"], ab["interval_days"], ab["repetitions"], ab["lapses"], ab["due_at"], ab["note"], ab["times_added"], ab["input_text"]) == (
        "learning", "import", 2.35, 10, 7, 1, "2026-10-20T16:00:00Z", "note abandon", 2, "abandon")
    ap = qrow(settings, "SELECT uw.* FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? AND w.lemma = 'apple'", (bob,))
    assert ap["state"] == "mastered" and ap["mastered_at"] == "2026-10-14T00:00:00Z"
    states = {r["input"]: r["mine"]["state"] for r in b["results"] if r["mine"]}
    assert states == {"abandon": "learning", "apple": "mastered", "bank": "known", "child": "new", "glass": "removed", "zzqx": "new"}
    assert {r["input"]: r["status"] for r in b["results"]}["zzqx"] == "pending_ai"
    assert q1(settings, "SELECT COUNT(*) FROM review_logs WHERE user_id = ? AND action = 'import' AND context = 'api'", (bob,)) == 6
    assert qrow(settings, "SELECT * FROM daily_stats WHERE user_id = ?", (bob,))["added"] == 6
    assert client.get("/api/bank").json()["counts"] == {"new": 2, "learning": 1, "mastered": 1, "known": 1, "removed": 1, "attention": 0, "due_today": 0}
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'lookup_word' AND status = 'queued'") == 1  # the shared provisional word's job (UPSERT)
    # re-importing the same file changes nothing
    r = client.post("/api/bank/import", json={"format": "json", "data": json.dumps({"version": 1, "words": export["words"]})}).json()
    assert r["exists"] == 6 and r["skipped"] == 6
    # 2,001 rows → 400 import_too_large
    big = {"version": 1, "words": [{"word": f"w{i}", "state": "new"} for i in range(2001)]}
    r = client.post("/api/bank/import", json={"format": "json", "data": json.dumps(big)})
    assert r.status_code == 400 and r.json()["error"]["code"] == "import_too_large" and r.json()["error"]["details"]["rows"] == 2001
    r = client.post("/api/bank/import", json={"format": "json", "data": "{not json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "import_too_large"
    assert client.post("/api/bank/import", json={"format": "xml", "data": "x"}).status_code == 400


def test_import_csv_round_trip(client: TestClient, settings, alice):
    _seed_alice_bank(client, settings, alice)
    rows = export_json(settings, alice)["words"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    w.writeheader()
    for row in rows:
        w.writerow({k: ("" if row.get(k) is None else row[k]) for k in EXPORT_COLUMNS})
    _, bob_token = make_user(settings, "bob")
    as_user(client, bob_token)
    r = client.post("/api/bank/import", json={"format": "csv", "data": buf.getvalue()})
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == 6 and r.json()["added"] == 5 and r.json()["pending_ai"] == 1
    bob = q1(settings, "SELECT id FROM users WHERE username = 'bob'")
    ab = qrow(settings, "SELECT uw.* FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? AND w.lemma = 'abandon'", (bob,))
    assert (ab["state"], ab["ease"], ab["interval_days"], ab["due_at"], ab["times_added"]) == ("learning", 2.35, 10, "2026-10-20T16:00:00Z", 2)


def test_import_round_trip_with_history_needs_the_client_side_reduction(client: TestClient, settings, alice):
    """1,500 bank rows + 40,000 review_logs: the full export is > 1 MB (413 at the body limit); {version, words} is < 1 MB."""
    conn = db.connect(settings.db_path)
    try:
        seed = [str(r[0]) for r in conn.execute("SELECT lemma FROM words WHERE is_valid_english = 1 ORDER BY id")]
    finally:
        conn.close()
    import itertools

    synthetic = ("zq" + "".join(t) for t in itertools.product("abcdefghij", repeat=4))  # letters only: digits are invalid input
    words_ = seed + [next(synthetic) for _ in range(1500 - len(seed))]
    rows = [{"word": w, "phonetic": None, "translation": None, "state": "learning" if i % 2 else "new", "origin": "custom", "note": None, "times_added": 1,
             "added_at": "2026-01-01T00:00:00Z", "mastered_at": None, "ease": 2.5, "interval_days": 3, "repetitions": 2, "lapses": 0, "due_at": "2026-10-16T16:00:00Z"} for i, w in enumerate(words_)]
    logs = [{"created_at": "2026-10-01T00:00:00Z", "word": words_[i % 1500], "action": "good", "context": "today", "prev_state": "learning", "new_state": "learning", "prev_interval": 3, "new_interval": 8} for i in range(40_000)]
    full = json.dumps({"version": 1, "exported_at": "x", "username": "alice", "words": rows, "review_logs": logs})
    assert len(full.encode()) > 1_048_576
    r = client.post("/api/bank/import", content=json.dumps({"format": "json", "data": full}), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    reduced = json.dumps({"version": 1, "words": rows})  # what endpoints.importPayloadFromJsonExport sends
    assert len(reduced.encode()) < 1_048_576
    r = client.post("/api/bank/import", json={"format": "json", "data": reduced})
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == 1500 and r.json()["added"] + r.json()["pending_ai"] == 1500 and len(r.json()["results"]) == 200
    assert q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ? AND origin = 'import'", (alice,)) == 1500
    assert q1(settings, "SELECT COUNT(*) FROM words WHERE source = 'user'") == 1500 - len(seed)
    # 1,440 provisional words were created → the day's custom-add budget (200) is spent; a new day frees it again
    small = json.dumps({"version": 1, "words": [{"word": "zqzzzz", "state": "new"}], "review_logs": logs[:5]})
    r = client.post("/api/bank/import", json={"format": "json", "data": small})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    run(settings, "DELETE FROM auth_throttle")
    # a small file that still carries review_logs is accepted as is (the key is ignored)
    assert client.post("/api/bank/import", json={"format": "json", "data": small}).json()["rows"] == 1


def test_import_quota(client: TestClient, settings, alice):
    run(settings, "INSERT INTO auth_throttle(key, window_start, count) VALUES (?, '2026-10-14T00:00:00Z', 200)", (f"custom:user:{alice}",))
    r = client.post("/api/bank/import", json={"format": "json", "data": json.dumps({"version": 1, "words": [{"word": "abandon", "state": "new"}]})})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
