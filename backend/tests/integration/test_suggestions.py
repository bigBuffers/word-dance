"""/api/suggestions* (WP3, API.md 39–42): inbox listing, accept (repoint with SRS preserved + push_items rewrite; merge
keeping the higher-repetition row and setting the other to removed), reject, undo of auto rows within 7 days."""

from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token

FAR = "2030-01-01T00:00:00Z"


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


def uw_row(settings, user_id: int, word_id: int) -> dict | None:
    return qrow(settings, "SELECT * FROM user_words WHERE user_id = ? AND word_id = ?", (user_id, word_id))


def suggest(settings, user_id: int, type_: str, *, user_word_id: int | None, target_word_id: int | None, payload: dict, status: str = "open", expires_at: str | None = "2026-11-13T00:00:00Z", undo: dict | None = None) -> int:
    return run(
        settings,
        "INSERT INTO bank_suggestions(user_id, type, user_word_id, target_word_id, payload_json, status, undo_json, expires_at, created_at) VALUES (?,?,?,?,?,?,?,?,'2026-10-13T18:30:00Z')",
        (user_id, type_, user_word_id, target_word_id, json.dumps(payload, ensure_ascii=False), status, None if undo is None else json.dumps(undo), expires_at),
    )


@pytest.fixture
def alice(client: TestClient, settings) -> int:
    uid, token = make_user(settings, "alice")
    as_user(client, token)
    return uid


def add_provisional(client: TestClient, text: str) -> int:
    r = client.post("/api/bank/add", json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["word"]["id"]


# --------------------------------------------------------------------------------------------- listing
def test_list_open_and_all(client: TestClient, settings, alice):
    prov = add_provisional(client, "abandonned")
    uw = uw_row(settings, alice, prov)
    abandon = word_id(settings, "abandon")
    s_open = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=abandon, payload={"from": "abandonned", "to": "abandon", "note_zh": "看起来是拼写错误", "confidence": 0.93, "extra": "dropped"})
    s_old = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=abandon, payload={}, expires_at="2026-10-13T00:00:00Z")  # timed out
    s_auto = suggest(settings, alice, "lemmatize", user_word_id=uw["id"], target_word_id=abandon, payload={"from": "abandonned", "to": "abandon"}, status="auto", expires_at="2026-10-20T00:00:00Z", undo={"prev_word_id": prov})
    suggest(settings, alice, "confusable_group", user_word_id=None, target_word_id=None, payload={"group": ["abandon", "abundant"]}, status="accepted", expires_at=None)
    s_rej = suggest(settings, alice, "merge_duplicate", user_word_id=uw["id"], target_word_id=abandon, payload={}, status="rejected")
    bob, _ = make_user(settings, "bob")
    suggest(settings, bob, "fix_spelling", user_word_id=None, target_word_id=abandon, payload={})
    r = client.get("/api/suggestions")
    assert r.status_code == 200, r.text
    b = r.json()
    assert [s["id"] for s in b["items"]] == [s_open] and b["open_count"] == 1
    s = b["items"][0]
    assert s["type"] == "fix_spelling" and s["status"] == "open" and s["target"]["lemma"] == "abandon"
    assert s["user_word"]["lemma"] == "abandonned" and s["user_word"]["mine"]["id"] == uw["id"] and s["user_word"]["is_valid_english"] is None
    assert s["payload"] == {"from": "abandonned", "to": "abandon", "note_zh": "看起来是拼写错误", "confidence": 0.93, "group": None, "fields": None}
    assert s["expires_at"] == "2026-11-13T00:00:00Z" and s["resolved_at"] is None and s["created_at"] == "2026-10-13T18:30:00Z"
    all_ = client.get("/api/suggestions?status=all").json()
    assert sorted(x["id"] for x in all_["items"]) == sorted([s_open, s_old, s_auto, s_rej]) and all_["open_count"] == 1  # confusable groups and other users never appear
    by_id = {x["id"]: x["status"] for x in all_["items"]}
    assert by_id == {s_open: "open", s_old: "expired", s_auto: "auto", s_rej: "rejected"}  # a timed-out open row never advertises 接受
    assert client.get("/api/suggestions?status=bogus").status_code == 400
    assert client.get("/api/suggestions?status=open&x=1").status_code == 400


# ------------------------------------------------------------------------------------------- accept
def test_accept_lemmatize_repoints_and_keeps_srs(client: TestClient, settings, alice):
    prov = add_provisional(client, "abandonning")
    abandon = word_id(settings, "abandon")
    uw = uw_row(settings, alice, prov)
    run(settings, "UPDATE user_words SET state = 'learning', ease = 2.3, interval_days = 8, repetitions = 4, due_at = '2026-10-20T16:00:00Z' WHERE id = ?", (uw["id"],))
    batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    item = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, 'review', 0)", (batch, prov, uw["id"]))
    old_batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-01', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    old_item = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position, result) VALUES (?, ?, ?, 'review', 0, 'good')", (old_batch, prov, uw["id"]))
    sid = suggest(settings, alice, "lemmatize", user_word_id=uw["id"], target_word_id=abandon, payload={"from": "abandonning", "to": "abandon"})
    r = client.post(f"/api/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["applied"] is True and res["removed_word_id"] is None and res["mine"]["word_id"] == abandon and res["message_zh"] == "已合并到 “abandon”"
    row = qrow(settings, "SELECT * FROM user_words WHERE id = ?", (uw["id"],))
    assert (row["word_id"], row["state"], row["ease"], row["interval_days"], row["repetitions"], row["due_at"]) == (abandon, "learning", 2.3, 8, 4, "2026-10-20T16:00:00Z")
    assert uw_row(settings, alice, prov) is None and q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,)) == 1
    assert qrow(settings, "SELECT word_id, user_word_id FROM push_items WHERE id = ?", (item,)) == {"word_id": abandon, "user_word_id": uw["id"]}  # open batch rewritten
    assert qrow(settings, "SELECT word_id FROM push_items WHERE id = ?", (old_item,))["word_id"] == prov  # history untouched
    assert qrow(settings, "SELECT status, resolved_at FROM bank_suggestions WHERE id = ?", (sid,)) == {"status": "accepted", "resolved_at": "2026-10-14T00:00:00Z"}
    log = qrows(settings, "SELECT * FROM review_logs WHERE user_id = ? AND action = 'consolidate'", (alice,))
    assert len(log) == 1 and log[0]["context"] == "consolidate" and log[0]["word_id"] == abandon and log[0]["user_word_id"] == uw["id"]
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND payload_json LIKE ?", (f'%"word_id":{abandon}%',)) == 1  # the validated target wants content
    r = client.post(f"/api/suggestions/{sid}/accept")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_resolved"
    assert client.get("/api/suggestions?status=all").json()["items"][0]["user_word"]["lemma"] == "abandon"


def test_accept_merge_keeps_the_row_with_more_repetitions(client: TestClient, settings, alice):
    prov = add_provisional(client, "abandonning")
    abandon = word_id(settings, "abandon")
    client.post(f"/api/words/{abandon}/mark", json={"action": "unfamiliar"})
    typo = uw_row(settings, alice, prov)
    real = uw_row(settings, alice, abandon)
    run(settings, "UPDATE user_words SET state = 'learning', repetitions = 5, ease = 2.2, interval_days = 12, due_at = '2026-10-22T16:00:00Z' WHERE id = ?", (typo["id"],))
    run(settings, "UPDATE user_words SET state = 'learning', repetitions = 1, ease = 2.5, interval_days = 1, due_at = '2026-10-15T16:00:00Z' WHERE id = ?", (real["id"],))
    other = suggest(settings, alice, "fix_spelling", user_word_id=real["id"], target_word_id=abandon, payload={})  # another open suggestion on the losing row
    kept_open = suggest(settings, alice, "split_phrase", user_word_id=typo["id"], target_word_id=abandon, payload={})  # on the winner: untouched
    batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    item_typo = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, 'review', 0)", (batch, prov, typo["id"]))
    item_real = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, 'review', 1)", (batch, abandon, real["id"]))
    graded_extra = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position, result) VALUES (?, ?, ?, 'extra', 2, 'good')", (batch, prov, typo["id"]))  # no collision → repointed
    run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, 'new', 3)", (batch, abandon, real["id"]))
    graded_dup = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position, result) VALUES (?, ?, ?, 'new', 4, 'good')", (batch, prov, typo["id"]))  # graded + collides → stays
    sid = suggest(settings, alice, "merge_duplicate", user_word_id=typo["id"], target_word_id=abandon, payload={"from": "abandonning", "to": "abandon"})
    before = q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,))
    r = client.post(f"/api/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["mine"]["id"] == typo["id"] and res["mine"]["word_id"] == abandon and res["mine"]["srs"]["repetitions"] == 5 and res["mine"]["srs"]["ease"] == 2.2
    assert res["removed_word_id"] == prov
    assert q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,)) == before  # never deleted
    loser = qrow(settings, "SELECT * FROM user_words WHERE id = ?", (real["id"],))
    assert loser["state"] == "removed" and loser["word_id"] == prov  # parked on the typo, out of the bank
    winner = qrow(settings, "SELECT * FROM user_words WHERE id = ?", (typo["id"],))
    assert winner["word_id"] == abandon and winner["state"] == "learning" and winner["interval_days"] == 12
    assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (other,))["status"] == "expired"
    assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (kept_open,))["status"] == "open"
    assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (sid,))["status"] == "accepted"
    logs = qrows(settings, "SELECT * FROM review_logs WHERE user_id = ? AND action = 'consolidate' ORDER BY id", (alice,))
    assert [(l["user_word_id"], l["new_state"]) for l in logs] == [(typo["id"], "learning"), (real["id"], "removed")]
    # push items: the ungraded duplicate (batch, abandon, review) row is dropped and the survivor points at the winner;
    # a graded row without a collision is repointed; a graded row that would collide stays on the typo (history is never deleted)
    items = {i["id"]: i for i in qrows(settings, "SELECT id, word_id, user_word_id, kind, result FROM push_items WHERE batch_id = ?", (batch,))}
    reviews = [i for i in items.values() if i["kind"] == "review"]
    assert len(reviews) == 1 and reviews[0]["word_id"] == abandon and reviews[0]["user_word_id"] == typo["id"] and reviews[0]["id"] in (item_typo, item_real)
    assert items[graded_extra]["word_id"] == abandon and items[graded_extra]["result"] == "good"
    assert items[graded_dup]["word_id"] == prov and items[graded_dup]["result"] == "good"
    assert len(items) == 4
    assert [i["lemma"] for i in client.get("/api/bank").json()["items"]] == ["abandon"]
    assert client.get("/api/bank").json()["counts"]["removed"] == 1


def test_accept_merge_where_the_target_row_wins(client: TestClient, settings, alice):
    prov = add_provisional(client, "abandonning")
    abandon = word_id(settings, "abandon")
    client.post(f"/api/words/{abandon}/mark", json={"action": "unfamiliar"})
    typo = uw_row(settings, alice, prov)
    real = uw_row(settings, alice, abandon)
    run(settings, "UPDATE user_words SET state = 'learning', repetitions = 9 WHERE id = ?", (real["id"],))
    sid = suggest(settings, alice, "merge_duplicate", user_word_id=typo["id"], target_word_id=abandon, payload={})
    res = client.post(f"/api/suggestions/{sid}/accept").json()["result"]
    assert res["mine"]["id"] == real["id"] and res["removed_word_id"] == prov
    assert qrow(settings, "SELECT state, word_id FROM user_words WHERE id = ?", (typo["id"],)) == {"state": "removed", "word_id": prov}
    assert qrow(settings, "SELECT state, word_id, repetitions FROM user_words WHERE id = ?", (real["id"],)) == {"state": "learning", "word_id": abandon, "repetitions": 9}


def test_accept_invalid_word_removes_the_row(client: TestClient, settings, alice):
    prov = add_provisional(client, "qwzx")
    uw = uw_row(settings, alice, prov)
    sid = suggest(settings, alice, "invalid_word", user_word_id=uw["id"], target_word_id=None, payload={"note_zh": "这似乎不是英文单词"})
    res = client.post(f"/api/suggestions/{sid}/accept").json()["result"]
    assert res["applied"] is True and res["removed_word_id"] == prov and res["mine"]["state"] == "removed" and res["message_zh"] == "已从生词库移除"
    assert qrows(settings, "SELECT action FROM review_logs WHERE user_id = ? ORDER BY id", (alice,))[-1]["action"] == "remove"
    assert client.get("/api/suggestions").json()["open_count"] == 0


def test_reject_and_errors(client: TestClient, settings, alice):
    prov = add_provisional(client, "abandonning")
    uw = uw_row(settings, alice, prov)
    sid = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=word_id(settings, "abandon"), payload={})
    r = client.post(f"/api/suggestions/{sid}/reject")
    assert r.status_code == 200 and r.json() == {}
    assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (sid,))["status"] == "rejected"
    assert uw_row(settings, alice, prov)["word_id"] == prov  # nothing changed
    r = client.post(f"/api/suggestions/{sid}/reject")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_resolved"
    assert client.post(f"/api/suggestions/{sid}/accept").status_code == 409
    assert client.post("/api/suggestions/999/accept").status_code == 404
    bob, _ = make_user(settings, "bob")
    foreign = suggest(settings, bob, "fix_spelling", user_word_id=None, target_word_id=word_id(settings, "abandon"), payload={})
    assert client.post(f"/api/suggestions/{foreign}/accept").status_code == 404  # never 403
    # a timed-out open suggestion cannot be accepted
    stale = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=word_id(settings, "abandon"), payload={}, expires_at="2026-10-13T00:00:00Z")
    r = client.post(f"/api/suggestions/{stale}/accept")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_resolved"
    assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (stale,))["status"] == "expired"
    # … nor rejected: it is recorded as expired either way
    stale = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=word_id(settings, "abandon"), payload={}, expires_at="2026-10-13T00:00:00Z")
    r = client.post(f"/api/suggestions/{stale}/reject")
    assert r.status_code == 409 and r.json()["error"] == {"code": "already_resolved", "message": "该建议已处理", "details": {"status": "expired"}}
    assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (stale,))["status"] == "expired"


def test_accept_fix_spelling_without_a_target_resolves_the_proposal(client: TestClient, settings, alice):
    """lookup_word step 2 stores `fix_spelling` with target_word_id NULL and the headword in payload.to: accept resolves it
    like the user's own add — an unknown spelling becomes a provisional word with one lookup job and the row moves onto it."""
    from wd.ai import lookup
    from wd.services import words

    prov = add_provisional(client, "aquire")
    uw = uw_row(settings, alice, prov)
    item = {"input": "aquire", "is_english": True, "kind": "word", "headword": "acquire", "form_note_zh": "", "phonetic": "", "pos": "v.", "meaning_zh": "获得", "definition_en": "to get", "difficulty": 2, "suggested_correction": "", "safe_for_sharing": True, "note_zh": "看起来是 acquire 的拼写错误"}
    conn = db.connect(settings.db_path)
    try:
        out = lookup.apply_item(conn, words.word_row(conn, prov), item, now="2026-10-14T00:00:00Z")  # 'aqu' vs 'acq': validate_headword rejects → step 2
    finally:
        conn.close()
    assert out["outcome"] == "kept" and out["suggestions"] == 1
    listed = client.get("/api/suggestions").json()
    (s,) = listed["items"]
    assert s["type"] == "fix_spelling" and s["target"] is None and s["payload"]["to"] == "acquire" and listed["open_count"] == 1
    r = client.post(f"/api/suggestions/{s['id']}/accept")
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    acquire = word_id(settings, "acquire")
    assert res["applied"] is True and res["mine"]["id"] == uw["id"] and res["mine"]["word_id"] == acquire and res["message_zh"] == "已合并到 “acquire”"
    w = qrow(settings, "SELECT * FROM words WHERE id = ?", (acquire,))
    assert (w["source"], w["is_public"], w["is_valid_english"], w["created_by_user_id"]) == ("user", 0, None, alice)  # provisional, exactly like typing it
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'lookup_word' AND dedupe_key = ? AND status = 'queued'", (f"lookup:{acquire}",)) == 1
    assert qrow(settings, "SELECT status, target_word_id FROM bank_suggestions WHERE id = ?", (s["id"],)) == {"status": "accepted", "target_word_id": acquire}
    assert client.get("/api/suggestions").json()["open_count"] == 0
    assert [i["lemma"] for i in client.get("/api/bank").json()["items"]] == ["acquire"]
    assert client.get(f"/api/words/{acquire}").json()["mine"]["id"] == uw["id"]


def test_accept_without_a_target_repoints_to_an_existing_headword_or_refuses(client: TestClient, settings, alice):
    prov = add_provisional(client, "abandonned")
    uw = uw_row(settings, alice, prov)
    abandon = word_id(settings, "abandon")
    sid = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=None, payload={"from": "abandonned", "to": "abandon"})
    res = client.post(f"/api/suggestions/{sid}/accept").json()["result"]
    assert res["mine"]["word_id"] == abandon and res["message_zh"] == "已合并到 “abandon”"
    assert qrow(settings, "SELECT target_word_id FROM bank_suggestions WHERE id = ?", (sid,))["target_word_id"] == abandon
    assert q1(settings, "SELECT COUNT(*) FROM words") == q1(settings, "SELECT COUNT(*) FROM words WHERE id <= ?", (prov,))  # nothing created
    # nothing resolvable → 409 invalid_transition and the row stays open (the user can still 保留)
    prov2 = add_provisional(client, "abstractify")
    uw2 = uw_row(settings, alice, prov2)
    for payload in ({"from": "abstractify"}, {"from": "abstractify", "to": "abc123"}):
        bad = suggest(settings, alice, "fix_spelling", user_word_id=uw2["id"], target_word_id=None, payload=payload)
        r = client.post(f"/api/suggestions/{bad}/accept")
        assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition" and r.json()["error"]["details"]["reason"] == "no_target"
        assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (bad,))["status"] == "open"
    assert uw_row(settings, alice, prov2)["word_id"] == prov2


def test_accept_clears_the_attention_flags_of_the_replaced_string(client: TestClient, settings, alice):
    """A flagged typo row (⚠ 「是否改为 “abandon”？」 + suggested_word_id) moves onto the corrected word: those columns described
    the typo — the corrected entry must not show ⚠/替换 (替换 would remove the corrected word) nor be kept out of batches."""
    prov = add_provisional(client, "abandonned")
    abandon = word_id(settings, "abandon")
    uw = uw_row(settings, alice, prov)
    run(settings, "UPDATE user_words SET needs_attention = 1, attention_msg = '未识别为英文单词：拼写错误；是否改为 “abandon”？', suggested_word_id = ? WHERE id = ?", (abandon, uw["id"]))
    assert client.get("/api/auth/me").json()["counters"]["attention"] == 1
    sid = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=abandon, payload={"from": "abandonned", "to": "abandon"})
    res = client.post(f"/api/suggestions/{sid}/accept").json()["result"]
    assert res["mine"]["word_id"] == abandon and res["mine"]["needs_attention"] is False and res["mine"]["attention_msg"] is None and res["mine"]["suggested_word"] is None
    assert client.get("/api/bank?state=attention").json()["items"] == [] and client.get("/api/auth/me").json()["counters"]["attention"] == 0
    r = client.post(f"/api/bank/{abandon}/accept-suggestion")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    assert uw_row(settings, alice, abandon)["state"] == "new"
    # merge branch: the flagged typo row wins (more repetitions) and takes the target — cleared there as well
    prov2 = add_provisional(client, "abolishs")
    abolish = word_id(settings, "abolish")
    client.post(f"/api/words/{abolish}/mark", json={"action": "unfamiliar"})
    typo = uw_row(settings, alice, prov2)
    run(settings, "UPDATE user_words SET state = 'learning', repetitions = 5, needs_attention = 1, attention_msg = '暂时无法校验，请稍后重试或检查拼写' WHERE id = ?", (typo["id"],))
    sid2 = suggest(settings, alice, "lemmatize", user_word_id=typo["id"], target_word_id=abolish, payload={"from": "abolishs", "to": "abolish"})
    res = client.post(f"/api/suggestions/{sid2}/accept").json()["result"]
    assert res["mine"]["id"] == typo["id"] and res["mine"]["word_id"] == abolish and res["mine"]["srs"]["repetitions"] == 5
    assert res["mine"]["needs_attention"] is False and res["mine"]["attention_msg"] is None
    assert client.get("/api/auth/me").json()["counters"]["attention"] == 0


@pytest.mark.parametrize("held", ["mastered", "known", "removed"])
def test_accept_merge_readds_a_target_held_outside_the_bank(client: TestClient, settings, alice, held):
    """The user holds the target as mastered/known/removed and accepts a spelling fix of a fresh entry: the word must stay in
    生词库 — the held row re-enters per DESIGN §4 (readd) and the typo row is parked, instead of a repetitions contest that
    the row with no live SRS state wins and the entry silently disappearing."""
    abandon = word_id(settings, "abandon")
    if held == "known":
        client.post(f"/api/words/{abandon}/mark", json={"action": "known"})
    else:
        client.post(f"/api/words/{abandon}/mark", json={"action": "unfamiliar"})
        client.post(f"/api/words/{abandon}/mark", json={"action": "mastered" if held == "mastered" else "remove"})
    real = uw_row(settings, alice, abandon)
    assert real["state"] == held
    run(settings, "UPDATE user_words SET repetitions = 6, first_added_at = '2026-01-01T00:00:00Z' WHERE id = ?", (real["id"],))
    prov = add_provisional(client, "abandonned")
    typo = uw_row(settings, alice, prov)
    sid = suggest(settings, alice, "fix_spelling", user_word_id=typo["id"], target_word_id=abandon, payload={"from": "abandonned", "to": "abandon"})
    before = q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,))
    r = client.post(f"/api/suggestions/{sid}/accept")
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["applied"] is True and res["removed_word_id"] == prov and res["message_zh"] == "已合并到 “abandon”"
    assert res["mine"]["id"] == real["id"] and res["mine"]["word_id"] == abandon and res["mine"]["state"] == "new"
    assert res["mine"]["times_added"] == 2 and res["mine"]["priority"] == 80 and res["mine"]["input_text"] == "abandonned"
    kept = qrow(settings, "SELECT * FROM user_words WHERE id = ?", (real["id"],))
    assert (kept["state"], kept["step"], kept["due_at"], kept["mastered_at"], kept["ease"]) == ("new", 0, None, None, 2.3 if held == "mastered" else 2.5)
    assert qrow(settings, "SELECT state, word_id FROM user_words WHERE id = ?", (typo["id"],)) == {"state": "removed", "word_id": prov}
    assert q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,)) == before  # never deleted
    assert [i["lemma"] for i in client.get("/api/bank").json()["items"]] == ["abandon"]
    actions = [l["action"] for l in qrows(settings, "SELECT action FROM review_logs WHERE user_id = ? ORDER BY id", (alice,))]
    assert actions[-2:] == ["readd", "consolidate"]
    assert qrow(settings, "SELECT status FROM bank_suggestions WHERE id = ?", (sid,))["status"] == "accepted"
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND dedupe_key = ?", (f"content:{abandon}",)) == 1


# ----------------------------------------------------------------------------------------------- undo
def test_undo_of_an_auto_lemmatize_restores_prev_word_id(client: TestClient, settings, alice, frozen_clock):
    """The nightly consolidation repointed abandonning → abandon automatically; the user undoes within 7 days."""
    prov = add_provisional(client, "abandonning")
    abandon = word_id(settings, "abandon")
    uw = uw_row(settings, alice, prov)
    run(settings, "UPDATE user_words SET word_id = ?, state = 'learning', repetitions = 3 WHERE id = ?", (abandon, uw["id"]))
    old_batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    old_item = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position, result) VALUES (?, ?, ?, 'review', 0, 'good')", (old_batch, abandon, uw["id"]))
    batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-20', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    item = run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, 'review', 0)", (batch, abandon, uw["id"]))
    sid = suggest(settings, alice, "lemmatize", user_word_id=uw["id"], target_word_id=abandon, payload={"from": "abandonning", "to": "abandon"}, status="auto", expires_at="2026-10-20T18:30:00Z", undo={"prev_word_id": prov})
    assert [s["id"] for s in client.get("/api/suggestions?status=all").json()["items"]] == [sid]
    frozen_clock.advance(days=6)  # 2026-10-20: the batch of that day is open, the one of the 14th is history
    r = client.post(f"/api/suggestions/{sid}/undo")
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["applied"] is True and res["mine"]["word_id"] == prov and res["mine"]["srs"]["repetitions"] == 3 and res["message_zh"] == "已撤销"
    assert qrow(settings, "SELECT word_id FROM push_items WHERE id = ?", (item,))["word_id"] == prov
    assert qrow(settings, "SELECT word_id FROM push_items WHERE id = ?", (old_item,))["word_id"] == abandon
    assert qrow(settings, "SELECT status, resolved_at FROM bank_suggestions WHERE id = ?", (sid,)) == {"status": "undone", "resolved_at": "2026-10-20T00:00:00Z"}
    assert qrows(settings, "SELECT action, word_id FROM review_logs WHERE user_id = ? ORDER BY id", (alice,))[-1] == {"action": "consolidate", "word_id": prov}
    r = client.post(f"/api/suggestions/{sid}/undo")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_resolved"


def test_undo_of_a_lookup_merge_restores_the_merged_word(client: TestClient, settings, alice):
    """lookup_word merged the typo into the seed headword (merged_into_word_id set, 7-day auto undo): 撤销 must hand back a
    word that is studied, shown as the user's and markable — not a bank row parked on a tombstone."""
    from wd.ai import lookup
    from wd.services import bank, batches, words

    prov = add_provisional(client, "abandonning")
    abandon = word_id(settings, "abandon")
    uw = uw_row(settings, alice, prov)
    item = {"input": "abandonning", "is_english": True, "kind": "word", "headword": "abandon", "form_note_zh": "abandon 的现在分词", "phonetic": "", "pos": "v.", "meaning_zh": "放弃", "definition_en": "to leave", "difficulty": 2, "suggested_correction": "", "safe_for_sharing": True, "note_zh": ""}
    conn = db.connect(settings.db_path)
    try:
        out = lookup.apply_item(conn, words.word_row(conn, prov), item, now="2026-10-14T00:00:00Z")
    finally:
        conn.close()
    assert out["outcome"] == "merged" and out["word_id"] == abandon
    assert uw_row(settings, alice, abandon)["id"] == uw["id"] and qrow(settings, "SELECT merged_into_word_id FROM words WHERE id = ?", (prov,))["merged_into_word_id"] == abandon
    assert q1(settings, "SELECT COUNT(*) FROM word_forms WHERE form = 'abandonning' AND word_id = ?", (abandon,)) == 1
    (s,) = client.get("/api/suggestions?status=all").json()["items"]
    assert s["type"] == "lemmatize" and s["status"] == "auto"
    r = client.post(f"/api/suggestions/{s['id']}/undo")
    assert r.status_code == 200, r.text
    assert r.json()["result"]["mine"]["word_id"] == prov and r.json()["result"]["message_zh"] == "已撤销"
    w = qrow(settings, "SELECT * FROM words WHERE id = ?", (prov,))
    assert w["merged_into_word_id"] is None and w["is_public"] == 0 and w["is_valid_english"] == 1  # a standalone private word again
    assert q1(settings, "SELECT COUNT(*) FROM word_forms WHERE form = 'abandonning'") == 0  # no alt form may equal a live lemma
    detail = client.get(f"/api/words/{prov}").json()
    assert detail["word"]["id"] == prov and detail["mine"]["id"] == uw["id"]
    assert client.patch(f"/api/bank/{prov}", json={"note": "hello"}).status_code == 200
    r = client.post(f"/api/words/{prov}/mark", json={"action": "unfamiliar", "context": "bank"})
    assert r.status_code == 200 and r.json()["status"] == "exists" and q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,)) == 1
    assert [i["lemma"] for i in client.get("/api/bank").json()["items"]] == ["abandonning"]
    conn = db.connect(settings.db_path)
    try:
        sel = batches.select_words(conn, alice, bank.user_settings_row(conn, alice), "2026-10-14")
        assert [n["word_id"] for n in sel.news] == [prov]  # pushed again
    finally:
        conn.close()
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content' AND dedupe_key = ? AND status = 'queued'", (f"content:{prov}",)) == 1  # the merge had cancelled it


def test_undo_expired_and_not_auto(client: TestClient, settings, alice, frozen_clock):
    prov = add_provisional(client, "abandonning")
    abandon = word_id(settings, "abandon")
    uw = uw_row(settings, alice, prov)
    auto = suggest(settings, alice, "lemmatize", user_word_id=uw["id"], target_word_id=abandon, payload={}, status="auto", expires_at="2026-10-20T18:30:00Z", undo={"prev_word_id": prov})
    frozen_clock.advance(days=8)
    r = client.post(f"/api/suggestions/{auto}/undo")
    assert r.status_code == 409 and r.json()["error"]["code"] == "undo_expired"
    assert [s["id"] for s in client.get("/api/suggestions?status=all").json()["items"]] == []  # out of the window → not listed either
    open_ = suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=abandon, payload={})
    r = client.post(f"/api/suggestions/{open_}/undo")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_resolved"


def test_undo_of_fill_data_restores_fields_and_refuses_when_prev_word_is_held(client: TestClient, settings, alice):
    prov = add_provisional(client, "abandonning")
    abandon = word_id(settings, "abandon")
    uw = uw_row(settings, alice, prov)
    run(settings, "UPDATE words SET phonetic = 'new', difficulty = 4 WHERE id = ?", (prov,))
    fill = suggest(settings, alice, "fill_data", user_word_id=uw["id"], target_word_id=None, payload={"fields": ["phonetic", "difficulty"]}, status="auto", expires_at="2026-10-20T00:00:00Z", undo={"word_id": prov, "fields": {"phonetic": None, "difficulty": None, "lemma": "hacked"}})
    assert client.post(f"/api/suggestions/{fill}/undo").status_code == 200
    w = qrow(settings, "SELECT phonetic, difficulty, lemma FROM words WHERE id = ?", (prov,))
    assert w == {"phonetic": None, "difficulty": None, "lemma": "abandonning"}  # only the allow-listed columns move
    # a repoint undo when the user re-added the previous word → 409 invalid_transition
    run(settings, "UPDATE user_words SET word_id = ? WHERE id = ?", (abandon, uw["id"]))
    client.post("/api/bank/add", json={"text": "abandonning"})  # a fresh row for the typo again
    auto = suggest(settings, alice, "lemmatize", user_word_id=uw["id"], target_word_id=abandon, payload={}, status="auto", expires_at="2026-10-20T00:00:00Z", undo={"prev_word_id": prov})
    r = client.post(f"/api/suggestions/{auto}/undo")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"


def test_open_count_feeds_the_badge(client: TestClient, settings, alice):
    from wd.services import suggestions

    prov = add_provisional(client, "abandonning")
    uw = uw_row(settings, alice, prov)
    for _ in range(3):
        suggest(settings, alice, "fix_spelling", user_word_id=uw["id"], target_word_id=word_id(settings, "abandon"), payload={})
    suggest(settings, alice, "confusable_group", user_word_id=None, target_word_id=None, payload={"group": ["a", "b"]}, status="accepted")
    conn = db.connect(settings.db_path)
    try:
        assert suggestions.open_count(conn, alice, "2026-10-14T00:00:00Z") == 3
    finally:
        conn.close()
    assert client.get("/api/suggestions").json()["open_count"] == 3
