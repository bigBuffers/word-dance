"""GET /api/lookup and /api/words/* (WP3, API.md 22–30): detail/redirect/ambiguous, content + deferral, image, mark incl.
restore over HTTP with a frozen clock, batch-mark, report, image refresh, content request, and the visibility rule."""

from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from wd import db, images
from wd.ai import budget
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


def run(settings, sql: str, params=()) -> int:
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            return int(conn.execute(sql, params).lastrowid or 0)
    finally:
        conn.close()


def word_id(settings, lemma: str) -> int:
    return int(q1(settings, "SELECT id FROM words WHERE lemma = ?", (lemma,)))


@pytest.fixture
def alice(client: TestClient, settings) -> int:
    uid, token = make_user(settings, "alice")
    as_user(client, token)
    return uid


# --------------------------------------------------------------------------------------------- lookup
def test_lookup_preview_shapes(client: TestClient, settings, alice):
    r = client.get("/api/lookup", params={"q": "went"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert (b["valid"], b["via"], b["normalized"], b["match"]["lemma"], b["lemma_note_zh"], b["mine"]) == (True, "form", "went", "go", "已归为原形 go（过去式）", None)
    b = client.get("/api/lookup", params={"q": " Abandon "}).json()
    assert b["via"] == "exact" and b["match"]["lemma"] == "abandon" and b["normalized"] == "abandon"
    assert b["suggestions"] == [] or all(s["lemma"].startswith("abandon") and s["lemma"] != "abandon" for s in b["suggestions"])
    b = client.get("/api/lookup", params={"q": "ab"}).json()
    assert b["via"] == "none" and b["match"] is None and 1 <= len(b["suggestions"]) <= 5
    assert all(s["lemma"].startswith("ab") for s in b["suggestions"])
    frqs = [s["frq"] for s in b["suggestions"]]
    assert frqs == sorted(frqs)
    b = client.get("/api/lookup", params={"q": "bases"}).json()
    assert b["via"] == "ambiguous" and [c["lemma"] for c in b["candidates"]] == ["base", "basis"]
    b = client.get("/api/lookup", params={"q": "放弃"}).json()
    assert (b["valid"], b["via"], b["reason_zh"], b["normalized"]) == (False, "invalid", "请输入英文单词", None)
    b = client.get("/api/lookup", params={"q": "lookup"}).json()
    assert b["valid"] is True and b["via"] == "none"
    assert client.get("/api/lookup").status_code == 400
    assert q1(settings, "SELECT COUNT(*) FROM words") == 62 and q1(settings, "SELECT COUNT(*) FROM jobs") == 0  # nothing created (62 = mini seed v2 records, PLAN §6 S2)
    client.post(f"/api/words/{word_id(settings, 'go')}/mark", json={"action": "unfamiliar"})
    assert client.get("/api/lookup", params={"q": "went"}).json()["mine"]["state"] == "new"


def test_words_lookup_path_is_a_normal_lemma_lookup(client: TestClient, alice):
    r = client.get("/api/words/lookup")
    assert r.status_code == 404 and r.json()["error"]["code"] == "word_not_found"
    assert client.get("/api/words/batch-mark").status_code == 404


# --------------------------------------------------------------------------------------------- detail
def test_detail_by_id_lemma_form_and_ambiguous(client: TestClient, settings, alice):
    go = word_id(settings, "go")
    r = client.get(f"/api/words/{go}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["word"]["lemma"] == "go" and d["redirected_from"] is None and d["mine"] is None and d["history"] == []
    assert d["image"] == {"id": None, "url": f"/media/card/{go}.svg", "kind": "card", "provider": "card_svg", "mime": "image/svg+xml", "width": 800, "height": 500, "alt_zh": None, "attribution": None}
    assert d["content"] is None and d["content_state"] == "none" and d["content_deferred_until"] is None
    assert {"form": "went", "kind": "p"} in d["word"]["forms"] and d["word"]["confusables"] == [] and d["word"]["source"] == "seed"
    r = client.get("/api/words/went")
    assert r.status_code == 200 and r.json()["word"]["lemma"] == "go" and r.json()["redirected_from"] == "went"
    assert client.get("/api/words/Children").json()["word"]["lemma"] == "child"
    assert client.get("/api/words/data").json()["word"]["lemma"] == "data"
    r = client.get("/api/words/bases")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ambiguous_form"
    assert [c["lemma"] for c in r.json()["error"]["details"]["candidates"]] == ["base", "basis"]
    assert client.get("/api/words/nosuchword").status_code == 404
    assert client.get("/api/words/999999").status_code == 404
    assert client.get("/api/words/%E6%94%BE%E5%BC%83").status_code == 404
    # merged words redirect
    run(settings, "UPDATE words SET merged_into_word_id = ? WHERE lemma = 'abolish'", (go,))
    r = client.get("/api/words/abolish")
    assert r.json()["word"]["lemma"] == "go" and r.json()["redirected_from"] == "abolish"


def test_detail_carries_mine_and_history(client: TestClient, settings, alice):
    w = word_id(settings, "abandon")
    client.post(f"/api/words/{w}/mark", json={"action": "unfamiliar", "context": "detail", "note": "hi"})
    d = client.get(f"/api/words/{w}").json()
    assert d["mine"]["state"] == "new" and d["mine"]["note"] == "hi" and d["word"]["my_state"] == "new"
    assert [h["action"] for h in d["history"]] == ["unfamiliar"] and d["history"][0]["context"] == "detail"
    assert d["content_state"] == "queued"  # content was enqueued by the add


# ---------------------------------------------------------------------------------- content / deferral
def test_content_states_eta_and_deferral(client: TestClient, settings, alice, frozen_clock):
    w = word_id(settings, "abandon")
    r = client.get(f"/api/words/{w}/content")
    assert r.json() == {"state": "none", "content": None, "eta_s": None, "deferred_until": None}
    client.post(f"/api/words/{w}/mark", json={"action": "unfamiliar"})
    r = client.get(f"/api/words/{w}/content").json()
    assert r["state"] == "queued" and r["eta_s"] == 30 and r["deferred_until"] is None
    # a second queued job ahead (lower priority number) pushes the eta
    other = word_id(settings, "apple")
    run(settings, "INSERT INTO jobs(type, payload_json, dedupe_key, priority, run_after) VALUES ('generate_content', ?, ?, 5, '2026-10-14T00:00:00Z')", (json.dumps({"word_id": other}), f"content:{other}"))
    assert client.get(f"/api/words/{w}/content").json()["eta_s"] == 60
    # deferred to tomorrow 00:05 (budget): state queued, eta null, deferred_until == run_after
    run(settings, "UPDATE jobs SET run_after = '2026-10-14T16:05:00Z' WHERE dedupe_key = ?", (f"content:{w}",))
    r = client.get(f"/api/words/{w}/content").json()
    assert (r["state"], r["eta_s"], r["deferred_until"]) == ("queued", None, "2026-10-14T16:05:00Z")
    assert client.get(f"/api/words/{w}").json()["content_deferred_until"] == "2026-10-14T16:05:00Z"
    # the same value appears on a StudyItem built for a push item of that word
    from wd.services import screen

    batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'ready', 'manual')", (alice,))
    item = run(settings, "INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'new', 0)", (batch, w))
    conn = db.connect(settings.db_path)
    try:
        si = screen.study_item_dict(conn, alice, item, now="2026-10-14T00:00:00Z")
    finally:
        conn.close()
    assert si["content_deferred_until"] == "2026-10-14T16:05:00Z" and si["content_state"] == "queued" and si["kind"] == "new"
    # paused AI → deferred_until = paused_until
    run(settings, "UPDATE jobs SET run_after = '2026-10-14T00:00:00Z' WHERE dedupe_key = ?", (f"content:{w}",))
    run(settings, "INSERT INTO kv(key, value) VALUES ('claude.paused_until', '2026-10-14T00:30:00Z')")
    assert client.get(f"/api/words/{w}/content").json()["deferred_until"] == "2026-10-14T00:30:00Z"
    run(settings, "DELETE FROM kv WHERE key = 'claude.paused_until'")
    # kill switch off entirely: queued, eta null, deferred null (the client treats it like a deferral)
    run(settings, "INSERT INTO kv(key, value) VALUES ('claude.enabled', '0')")
    assert client.get(f"/api/words/{w}/content").json() == {"state": "queued", "content": None, "eta_s": None, "deferred_until": None}
    run(settings, "DELETE FROM kv WHERE key = 'claude.enabled'")
    # ready content is returned as is
    content = {
        "word": "abandon", "valid": True, "meaning_zh": "放弃", "meaning_en": "to leave", "examples": [{"en": "They abandon the plan.", "zh": "他们放弃了计划。"}],
        "collocations": ["abandon hope"], "mnemonic_zh": "a+band+on", "image_keywords": ["abandoned house"], "image_alt_zh": "废弃的房子", "difficulty": 3,
        "version": 1, "prompt_version": "content-v1", "model": "claude-sonnet-fake", "created_at": "2026-10-14T00:00:00Z",
    }
    cid = run(settings, "INSERT INTO word_contents(word_id, version, prompt_version, model, content_json) VALUES (?, 1, 'content-v1', 'm', ?)", (w, json.dumps(content, ensure_ascii=False)))
    run(settings, "UPDATE words SET active_content_id = ?, content_state = 'ready' WHERE id = ?", (cid, w))
    r = client.get(f"/api/words/{w}/content").json()
    assert r["state"] == "ready" and r["content"]["meaning_zh"] == "放弃" and r["eta_s"] is None


def test_image_endpoint_card_fallback_and_photo(client: TestClient, settings, alice):
    w = word_id(settings, "apple")
    r = client.get(f"/api/words/{w}/image")
    assert r.status_code == 200 and r.json()["kind"] == "card" and r.json()["url"] == f"/media/card/{w}.svg"
    iid = run(settings, "INSERT INTO word_images(word_id, provider, provider_ref, title, creator, license, file_path, file_bytes, sha256, mime, width, height, attribution_text) VALUES (?, 'wikimedia', 'p1', 'Red Apple', 'Someone', 'CC BY-SA 4.0', 'ab/abcd.jpg', 1000, 'abcd', 'image/jpeg', 800, 600, '\"Red Apple\" · Someone · CC BY-SA 4.0')", (w,))
    run(settings, "UPDATE words SET active_image_id = ?, image_state = 'ready' WHERE id = ?", (iid, w))
    r = client.get(f"/api/words/{w}/image").json()
    assert (r["id"], r["kind"], r["provider"], r["url"], r["attribution"]["license"]) == (iid, "photo", "wikimedia", "/media/images/ab/abcd.jpg", "CC BY-SA 4.0")


# ----------------------------------------------------------------------------------------------- mark
def test_mark_flow_and_restore_over_http(client: TestClient, settings, alice, frozen_clock):
    w = word_id(settings, "abandon")
    r = client.post(f"/api/words/{w}/mark", json={"action": "unfamiliar", "context": "browse"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "added" and r.json()["state"] == "new" and r.json()["mine"]["origin"] == "browse" and r.json()["word_id"] == w
    assert client.post(f"/api/words/{w}/mark", json={"action": "unfamiliar"}).json()["status"] == "exists"
    frozen_clock.advance(seconds=5)
    r = client.post(f"/api/words/{w}/mark", json={"action": "mastered", "context": "bank"}).json()
    assert r["state"] == "mastered" and r["mine"]["mastered_at"] == "2026-10-14T00:00:05Z"
    frozen_clock.advance(seconds=3)
    r = client.post(f"/api/words/{w}/mark", json={"action": "restore", "context": "bank"})
    assert r.status_code == 200 and r.json()["status"] == "restored" and r.json()["state"] == "new"
    client.post(f"/api/words/{w}/mark", json={"action": "mastered"})
    frozen_clock.advance(minutes=16)
    r = client.post(f"/api/words/{w}/mark", json={"action": "restore"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "undo_expired"
    r = client.post(f"/api/words/{word_id(settings, 'apple')}/mark", json={"action": "remove"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition" and r.json()["error"]["details"]["action"] == "remove"
    assert client.post(f"/api/words/{w}/mark", json={"action": "bogus"}).status_code == 400
    assert client.post(f"/api/words/{w}/mark", json={"action": "unfamiliar", "context": "onboarding"}).status_code == 400  # not a mark context
    assert client.post(f"/api/words/999999/mark", json={"action": "unfamiliar"}).status_code == 404
    # restore of a ∅→known deletes the row → state/mine null
    w2 = word_id(settings, "bank")
    client.post(f"/api/words/{w2}/mark", json={"action": "known", "context": "screen_page"})
    r = client.post(f"/api/words/{w2}/mark", json={"action": "restore", "context": "screen_page"}).json()
    assert r == {"word_id": w2, "state": None, "mine": None, "status": "restored"}
    assert client.get(f"/api/words/{w2}").json()["mine"] is None


def test_batch_mark(client: TestClient, settings, alice):
    ids = [word_id(settings, l) for l in ("abandon", "apple", "bank")]
    client.post(f"/api/words/{ids[2]}/mark", json={"action": "mastered"})  # ∅ → known
    body = {"items": [{"word_id": ids[0], "action": "unfamiliar"}, {"word_id": ids[1], "action": "known"}, {"word_id": ids[2], "action": "known"}, {"word_id": 999999, "action": "known"}]}
    r = client.post("/api/words/batch-mark", json=body)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["updated"] == 2
    assert b["results"][0] == {"word_id": ids[0], "ok": True, "state": "new", "error": None}
    assert b["results"][1]["state"] == "known"
    assert b["results"][2] == {"word_id": ids[2], "ok": True, "state": "known", "error": None}  # noop
    assert b["results"][3] == {"word_id": 999999, "ok": False, "state": None, "error": "word_not_found"}
    assert q1(settings, "SELECT origin FROM user_words WHERE user_id = ? AND word_id = ?", (alice, ids[0])) == "browse"
    assert client.post("/api/words/batch-mark", json={"items": []}).status_code == 400
    assert client.post("/api/words/batch-mark", json={"items": [{"word_id": ids[0], "action": "mastered"}]}).status_code == 400
    assert client.post("/api/words/batch-mark", json={"items": [{"word_id": ids[0], "action": "known"}] * 101}).status_code == 400


# --------------------------------------------------------------------------------------------- report
def test_report_content_and_image(client: TestClient, settings, alice):
    w = word_id(settings, "apple")
    r = client.post(f"/api/words/{w}/report", json={"target": "content", "reason": "wrong_meaning", "note": "x"})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    row = qrow(settings, "SELECT * FROM content_reports WHERE id = ?", (rid,))
    assert (row["user_id"], row["word_id"], row["target"], row["reason"], row["status"], row["image_id"]) == (alice, w, "content", "wrong_meaning", "open", None)
    assert q1(settings, "SELECT COUNT(*) FROM jobs") == 0
    iid = run(settings, "INSERT INTO word_images(word_id, provider, provider_ref, file_path, file_bytes, sha256, mime) VALUES (?, 'openverse', 'ov-1', 'ab/abcd.jpg', 10, 'sha-1', 'image/jpeg')", (w,))
    run(settings, "UPDATE words SET active_image_id = ?, image_state = 'ready' WHERE id = ?", (iid, w))
    r = client.post(f"/api/words/{w}/report", json={"target": "image", "reason": "irrelevant_image"})
    assert r.status_code == 201
    assert q1(settings, "SELECT status FROM word_images WHERE id = ?", (iid,)) == "rejected"  # WP6's reject_active_image
    assert q1(settings, "SELECT COUNT(*) FROM system_events WHERE kind = 'image_rejected'") == 1
    job = qrow(settings, "SELECT * FROM jobs WHERE type = 'fetch_image'")
    assert job["priority"] == 10 and job["dedupe_key"] == f"image:{w}" and json.loads(job["payload_json"]) == {"word_id": w, "exclude": ["ov-1", "sha-1"]}
    assert qrow(settings, "SELECT * FROM words WHERE id = ?", (w,))["image_state"] == "queued"
    assert client.post(f"/api/words/{w}/report", json={"target": "image", "reason": "nope"}).status_code == 400
    assert client.post(f"/api/words/{w}/report", json={"target": "content", "reason": "other", "note": "x" * 301}).status_code == 400


def test_report_delegates_the_image_change_to_wp6(client: TestClient, settings, alice, monkeypatch):
    w = word_id(settings, "apple")
    iid = run(settings, "INSERT INTO word_images(word_id, provider, provider_ref, file_path, file_bytes, sha256, mime) VALUES (?, 'openverse', 'ov-1', 'ab/abcd.jpg', 10, 'sha-1', 'image/jpeg')", (w,))
    run(settings, "UPDATE words SET active_image_id = ?, image_state = 'ready' WHERE id = ?", (iid, w))
    seen = []
    monkeypatch.setattr(images, "reject_active_image", lambda conn, word_id, *, reason, priority=10, now=None: seen.append((word_id, reason, priority)) or 7)
    assert client.post(f"/api/words/{w}/report", json={"target": "image", "reason": "inappropriate_image"}).status_code == 201
    assert seen == [(w, "inappropriate_image", 10)]
    assert q1(settings, "SELECT status FROM word_images WHERE id = ?", (iid,)) == "active"  # WP6 owns the change


def test_report_quota(client: TestClient, settings, alice):
    w = word_id(settings, "apple")
    for _ in range(20):
        assert client.post(f"/api/words/{w}/report", json={"target": "dictionary", "reason": "other"}).status_code == 201
    r = client.post(f"/api/words/{w}/report", json={"target": "dictionary", "reason": "other"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited" and r.headers["Retry-After"].isdigit()


# ------------------------------------------------------------------------------------- image refresh
def test_image_refresh(client: TestClient, settings, alice):
    w = word_id(settings, "apple")
    iid = run(settings, "INSERT INTO word_images(word_id, provider, provider_ref, file_path, file_bytes, sha256, mime) VALUES (?, 'wikimedia', '123', 'ab/abcd.jpg', 10, 'sha-a', 'image/jpeg')", (w,))
    run(settings, "UPDATE words SET active_image_id = ?, image_state = 'ready' WHERE id = ?", (iid, w))
    r = client.post(f"/api/words/{w}/image/refresh")
    assert r.status_code == 202, r.text
    assert r.json()["image_state"] == "queued"
    job = qrow(settings, "SELECT * FROM jobs WHERE id = ?", (r.json()["job_id"],))
    assert job["type"] == "fetch_image" and job["priority"] == 10 and json.loads(job["payload_json"]) == {"word_id": w, "exclude": ["123", "sha-a"]}
    assert q1(settings, "SELECT image_state FROM words WHERE id = ?", (w,)) == "queued"
    assert client.post(f"/api/words/{w}/image/refresh").json()["job_id"] == job["id"]  # UPSERT: one live job
    assert client.post("/api/words/999999/image/refresh").status_code == 404


# ------------------------------------------------------------------------------------ content request
def test_content_request_flow(client: TestClient, settings, alice, monkeypatch):
    w = word_id(settings, "apple")
    r = client.post(f"/api/words/{w}/content/request")
    assert r.status_code == 202, r.text
    assert r.json()["state"] == "queued" and r.json()["job_id"]
    job = qrow(settings, "SELECT * FROM jobs WHERE id = ?", (r.json()["job_id"],))
    assert job["type"] == "generate_content" and job["priority"] == 10 and job["dedupe_key"] == f"content:{w}"
    r = client.post(f"/api/words/{w}/content/request")
    assert r.status_code == 200 and r.json() == {"job_id": job["id"], "state": "queued"}  # no-op
    run(settings, "UPDATE words SET content_state = 'ready' WHERE id = ?", (w,))
    run(settings, "UPDATE jobs SET status = 'done' WHERE id = ?", (job["id"],))
    assert client.post(f"/api/words/{w}/content/request").json() == {"job_id": None, "state": "ready"}
    # provisional → 409
    r = client.post("/api/bank/add", json={"text": "zzqx"})
    prov = r.json()["results"][0]["word"]["id"]
    r = client.post(f"/api/words/{prov}/content/request")
    assert r.status_code == 409 and r.json()["error"]["code"] == "invalid_transition"
    # budget (WP5) says no → 409 budget_exhausted
    w2 = word_id(settings, "bank")
    seen: list[tuple] = []

    def refuse(conn, kind, word_count, priority, now, *, cfg=None, provider="claude"):
        seen.append((kind, word_count, priority, now, provider))  # §10: the route names the provider failover chose
        return False, "2026-10-14T16:05:00Z"

    monkeypatch.setattr(budget, "can_spend", refuse)
    r = client.post(f"/api/words/{w2}/content/request")
    assert r.status_code == 409 and r.json()["error"]["code"] == "budget_exhausted" and r.json()["error"]["details"]["resumes_at"] == "2026-10-14T16:05:00Z"
    assert seen == [("content", 1, 10, "2026-10-14T00:00:00Z", "claude")]  # the frozen clock as an ISO string (WP5 accepts str | datetime); claude_cli mode → the CLI
    monkeypatch.setattr(budget, "can_spend", lambda conn, kind, word_count, priority, now, cfg=None, provider="claude": (True, None))
    assert client.post(f"/api/words/{w2}/content/request").status_code == 202
    # kill switch → 503
    w3 = word_id(settings, "glass")
    run(settings, "INSERT INTO kv(key, value) VALUES ('claude.enabled', '0')")
    r = client.post(f"/api/words/{w3}/content/request")
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_disabled"


def test_content_request_quota(client: TestClient, settings, alice):
    conn = db.connect(settings.db_path)
    try:
        ids = [int(r[0]) for r in conn.execute("SELECT id FROM words WHERE is_valid_english = 1 ORDER BY id LIMIT 60")]
    finally:
        conn.close()
    for w in ids:
        assert client.post(f"/api/words/{w}/content/request").status_code == 202
    run(settings, "UPDATE words SET content_state = 'none'")
    run(settings, "UPDATE jobs SET status = 'cancelled'")
    r = client.post(f"/api/words/{ids[0]}/content/request")
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


# ------------------------------------------------------------------------------------------ visibility
def test_visibility_rule_for_a_shared_provisional_word(client: TestClient, settings, alice):
    bob_id, bob = make_user(settings, "bob")
    carol_id, carol = make_user(settings, "carol")
    r = client.post("/api/bank/add", json={"text": "zzqx"})
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "pending_ai"
    wid = r.json()["results"][0]["word"]["id"]
    as_user(client, bob)
    r = client.post("/api/bank/add", json={"text": "zzqx"})
    assert r.json()["results"][0]["status"] == "pending_ai" and r.json()["results"][0]["word"]["id"] == wid  # one shared row
    assert q1(settings, "SELECT COUNT(*) FROM words WHERE lemma = 'zzqx'") == 1
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'lookup_word'") == 1  # UPSERT: one lookup job
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content'") == 0  # never for a provisional word
    for token in (bob, next(t for _, t in [(alice, client.cookies.get("wd_session"))])):
        pass
    for who in (bob,):
        as_user(client, who)
        assert client.get(f"/api/words/{wid}").status_code == 200
        assert client.get(f"/api/words/{wid}/content").status_code == 200
        assert client.get(f"/api/words/{wid}/image").status_code == 200
        assert any(i["lemma"] == "zzqx" for i in client.get("/api/bank").json()["items"])
        assert client.get("/api/lookup", params={"q": "zzqx"}).json()["via"] == "exact"
    as_user(client, carol)
    for path in (f"/api/words/{wid}", f"/api/words/{wid}/content", f"/api/words/{wid}/image", "/api/words/zzqx"):
        r = client.get(path)
        assert r.status_code == 404 and r.json()["error"]["code"] == "word_not_found", path
    assert client.get("/api/vocab?q=zzqx").json()["total"] == 0
    assert client.get("/api/lookup", params={"q": "zzqx"}).json()["via"] == "none"
    assert not any(i["word"]["lemma"] == "zzqx" for i in client.get("/api/screen/next?stage=auto&count=50").json()["items"])
    assert client.post(f"/api/words/{wid}/mark", json={"action": "unfamiliar"}).status_code == 404
    assert client.post(f"/api/words/{wid}/content/request").status_code == 404
    assert client.post(f"/api/words/{wid}/image/refresh").status_code == 404
    # once carol adds the same string she holds a row and sees it too
    assert client.post("/api/bank/add", json={"text": "ZZQX"}).json()["results"][0]["word"]["id"] == wid
    assert client.get(f"/api/words/{wid}").status_code == 200


def test_csrf_still_applies_to_word_mutations(raw_client: TestClient, settings):
    uid, token = make_user(settings, "alice")
    as_user(raw_client, token)
    r = raw_client.post("/api/words/1/mark", json={"action": "unfamiliar"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_rejected"
