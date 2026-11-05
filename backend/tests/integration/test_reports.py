"""Admin content reports (API.md 70–71): admin guard, listing/pagination/shape, resolve with refetch_image
(active image rejected + fetch_image excluding it), regenerate (content:<id>:r<n>), dismiss, 404/400."""

from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token
from wd.images import store
from wd.schemas import Report

NOW = "2026-10-14T00:00:00Z"  # frozen clock


def make_user(conn, username: str, role: str = "user") -> tuple[int, str]:
    uid = conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done') RETURNING id", (username, role)).fetchone()[0]
    conn.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, '2027-01-01T00:00:00Z')", (hash_token(token), uid))
    return uid, token


def insert_word(conn, lemma: str, **cols) -> int:
    row = {"lemma": lemma, "display": lemma, "source": "seed", "is_public": 1, "is_valid_english": 1, "translation": "vt. 放弃, 抛弃\nn. 放纵", "stage_gk": 1, "stage_cet4": 1, "stage_min": 3, "frq": 1234, "collins": 3, "oxford": 1}  # stage_min 3 = gk (xs=1 … cet6=5)
    row.update(cols)
    # the client fixture's lifespan imports the mini seed (WP1), which already holds `abandon`/`apple`; the tests
    # assert exactly these columns (stages, frq, oxford …), so replace any seeded row (children cascade)
    conn.execute("DELETE FROM words WHERE lemma = ?", (lemma,))
    return conn.execute(f"INSERT INTO words({','.join(row)}) VALUES ({','.join('?' * len(row))}) RETURNING id", list(row.values())).fetchone()[0]


def insert_report(conn, user_id: int, word_id: int, *, target="image", reason="irrelevant_image", status="open", created_at="2026-10-13T10:00:00Z", note=None) -> int:
    return conn.execute(
        "INSERT INTO content_reports(user_id, word_id, target, reason, note, status, created_at) VALUES (?,?,?,?,?,?,?) RETURNING id",
        (user_id, word_id, target, reason, note, status, created_at),
    ).fetchone()[0]


@pytest.fixture
def dbconn(client: TestClient, settings):
    c = db.connect(settings.db_path)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def admin(client: TestClient, dbconn):
    uid, token = make_user(dbconn, "root", role="admin")
    client.cookies.set("wd_session", token)
    return uid


def test_reports_require_an_admin(client: TestClient, dbconn):
    assert client.get("/api/admin/reports").status_code == 401
    _, token = make_user(dbconn, "alice")
    client.cookies.set("wd_session", token)
    r = client.get("/api/admin/reports")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    assert client.post("/api/admin/reports/1", json={"status": "dismissed"}).status_code == 403


def test_list_reports_pagination_and_shape(client: TestClient, dbconn, admin):
    alice, _ = make_user(dbconn, "alice")
    w1, w2 = insert_word(dbconn, "abandon"), insert_word(dbconn, "apple", kind="word", is_valid_english=None, is_public=0, source="user")
    dbconn.execute("INSERT INTO user_words(user_id, word_id, state, origin) VALUES (?, ?, 'learning', 'browse')", (admin, w1))
    r1 = insert_report(dbconn, alice, w1, created_at="2026-10-13T10:00:00Z", note="配图无关")
    r2 = insert_report(dbconn, alice, w2, target="content", reason="unnatural_example", created_at="2026-10-13T11:00:00Z")
    insert_report(dbconn, alice, w1, target="dictionary", reason="wrong_meaning", status="resolved")
    r = client.get("/api/admin/reports")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 2 and body["page"] == 1 and body["page_size"] == 50 and [x["id"] for x in body["items"]] == [r2, r1]  # newest first
    for item in body["items"]:
        Report.model_validate(item)
    first = body["items"][1]
    assert first["user"] == {"id": alice, "username": "alice"} and first["target"] == "image" and first["reason"] == "irrelevant_image"
    assert first["note"] == "配图无关" and first["status"] == "open" and first["resolution"] is None and first["resolved_at"] is None
    word = first["word"]
    assert word["id"] == w1 and word["lemma"] == "abandon" and word["translation_short"] == "vt. 放弃, 抛弃" and word["stages"] == ["gk", "cet4"]
    assert word["stage_min"] == 3 and word["frq"] == 1234 and word["oxford"] is True and word["my_state"] == "learning" and word["is_valid_english"] is True
    assert body["items"][0]["word"]["is_valid_english"] is None and body["items"][0]["word"]["is_public"] is False and body["items"][0]["word"]["my_state"] is None
    r = client.get("/api/admin/reports", params={"page_size": 1, "page": 2})
    assert r.json()["total"] == 2 and [x["id"] for x in r.json()["items"]] == [r1]
    assert client.get("/api/admin/reports", params={"status": "resolved"}).json()["total"] == 1
    assert client.get("/api/admin/reports", params={"status": "dismissed"}).json()["total"] == 0
    assert client.get("/api/admin/reports", params={"status": "bogus"}).status_code == 400
    assert client.get("/api/admin/reports", params={"status": "bogus"}).json()["error"]["code"] == "validation_error"
    assert client.get("/api/admin/reports", params={"page_size": 101}).status_code == 400
    assert client.get("/api/admin/reports", params={"unknown": 1}).status_code == 400


def test_resolve_with_refetch_image_rejects_the_active_image_and_enqueues_excluding_it(client: TestClient, dbconn, settings, admin):
    alice, _ = make_user(dbconn, "alice")
    wid = insert_word(dbconn, "abandon")
    stored = store.write_bytes(settings, b"\xff\xd8\xff" + b"x" * 50, "jpg")
    image_id = store.activate(dbconn, wid, provider="wikimedia", ref="7823406", file_path=stored.file_path, file_bytes=stored.file_bytes, sha256=stored.sha256, mime="image/jpeg", license="CC BY 2.0", now=NOW)
    rid = insert_report(dbconn, alice, wid)
    r = client.post(f"/api/admin/reports/{rid}", json={"status": "resolved", "refetch_image": True})
    assert r.status_code == 200, r.text
    body = r.json()
    Report.model_validate(body)
    assert body["status"] == "resolved" and body["resolution"] == "image_replaced" and body["resolved_at"] == NOW
    assert body["word"]["image_state"] == "queued"
    assert dbconn.execute("SELECT status FROM word_images WHERE id=?", (image_id,)).fetchone()[0] == "rejected"
    assert tuple(dbconn.execute("SELECT active_image_id, image_state FROM words WHERE id=?", (wid,)).fetchone()) == (None, "queued")
    jobs = [db.row_to_dict(j) for j in dbconn.execute("SELECT * FROM jobs WHERE type='fetch_image'")]
    assert len(jobs) == 1 and jobs[0]["priority"] == 10 and jobs[0]["dedupe_key"] == f"image:{wid}"
    assert set(json.loads(jobs[0]["payload_json"])["exclude"]) == {"7823406", stored.sha256}
    assert dbconn.execute("SELECT COUNT(*) FROM system_events WHERE kind='image_rejected'").fetchone()[0] == 1
    assert client.get("/api/admin/reports").json()["total"] == 0
    assert client.get("/api/admin/reports", params={"status": "resolved"}).json()["items"][0]["id"] == rid


def test_resolve_with_regenerate_enqueues_forced_content_with_a_fresh_key(client: TestClient, dbconn, admin):
    alice, _ = make_user(dbconn, "alice")
    wid = insert_word(dbconn, "abandon")
    r1 = insert_report(dbconn, alice, wid, target="content", reason="unnatural_example")
    r2 = insert_report(dbconn, alice, wid, target="content", reason="bad_translation")
    body = client.post(f"/api/admin/reports/{r1}", json={"status": "resolved", "regenerate": True}).json()
    assert body["resolution"] == "regenerated"
    jobs = [db.row_to_dict(j) for j in dbconn.execute("SELECT * FROM jobs WHERE type='generate_content' ORDER BY id")]
    assert len(jobs) == 1 and jobs[0]["dedupe_key"] == f"content:{wid}:r1" and jobs[0]["priority"] == 10
    assert json.loads(jobs[0]["payload_json"]) == {"word_id": wid, "force": True}
    body = client.post(f"/api/admin/reports/{r2}", json={"status": "resolved", "regenerate": True, "refetch_image": True}).json()
    assert body["resolution"] == "regenerated+image_replaced"  # no active image → still a fetch_image job, so the image part counts
    jobs = [db.row_to_dict(j) for j in dbconn.execute("SELECT * FROM jobs WHERE type='generate_content' ORDER BY id")]
    assert [j["dedupe_key"] for j in jobs] == [f"content:{wid}:r1", f"content:{wid}:r2"]
    # an unvalidated word never gets a content job
    provisional = insert_word(dbconn, "zzqx", is_valid_english=None, is_public=0, source="user")
    r3 = insert_report(dbconn, alice, provisional, target="content", reason="other")
    body = client.post(f"/api/admin/reports/{r3}", json={"status": "resolved", "regenerate": True}).json()
    assert body["resolution"] == "resolved"
    assert dbconn.execute("SELECT COUNT(*) FROM jobs WHERE type='generate_content'").fetchone()[0] == 2


def test_dismiss_and_errors(client: TestClient, dbconn, admin):
    alice, _ = make_user(dbconn, "alice")
    wid = insert_word(dbconn, "abandon")
    rid = insert_report(dbconn, alice, wid)
    body = client.post(f"/api/admin/reports/{rid}", json={"status": "dismissed", "regenerate": True, "refetch_image": True}).json()
    assert body["status"] == "dismissed" and body["resolution"] == "dismissed" and body["resolved_at"] == NOW
    assert dbconn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0  # dismissing never enqueues anything
    assert client.get("/api/admin/reports", params={"status": "dismissed"}).json()["total"] == 1
    r = client.post("/api/admin/reports/999999", json={"status": "dismissed"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.post(f"/api/admin/reports/{rid}", json={"status": "open"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"
    assert client.post(f"/api/admin/reports/{rid}", json={"status": "resolved", "extra": 1}).status_code == 400
    assert client.post(f"/api/admin/reports/{rid}", json={}).status_code == 400
