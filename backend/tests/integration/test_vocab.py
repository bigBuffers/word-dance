"""GET /api/stages, /api/vocab, /api/vocab/letters (WP3, API.md 19–21) on the mini seed through the HTTP layer."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token

FAR = "2030-01-01T00:00:00Z"
FULL_SEED_DB = os.environ.get("WD_FULL_SEED_DB")  # read at collection time: the test_env fixture strips WD_* variables


# -------------------------------------------------------------------------------------------- helpers
def make_user(settings, username: str, *, role: str = "user") -> tuple[int, str]:
    """users + user_settings + sessions rows (WP2's auth routes are not part of this package); returns (id, cookie)."""
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


def run(settings, sql: str, params=()):
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            conn.execute(sql, params)
    finally:
        conn.close()


@pytest.fixture
def alice(client: TestClient, settings) -> int:
    uid, token = make_user(settings, "alice")
    as_user(client, token)
    return uid


# --------------------------------------------------------------------------------------------- stages
def test_stages_totals_and_progress(client: TestClient, settings, alice):
    r = client.get("/api/stages")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [i["stage"] for i in items] == ["zk", "gk", "cet4", "cet6"] and [i["index"] for i in items] == [1, 2, 3, 4]
    assert [i["name_zh"] for i in items] == ["初中", "高中", "四级", "六级"]
    for i in items:
        assert i["total"] == q1(settings, f"SELECT COUNT(*) FROM words WHERE stage_{i['stage']} = 1 AND is_public = 1 AND merged_into_word_id IS NULL")
        assert i["new_only_total"] == q1(settings, "SELECT COUNT(*) FROM words WHERE stage_min = ? AND is_public = 1", (i["index"],))
        assert i["unseen"] == i["total"] and i["unfamiliar"] == i["known"] == i["mastered"] == 0
    cet6 = items[3]
    assert cet6["new_only_total"] == 3  # absorption, axe, ought to
    abandon = q1(settings, "SELECT id FROM words WHERE lemma = 'abandon'")
    assert client.post(f"/api/words/{abandon}/mark", json={"action": "unfamiliar"}).status_code == 200
    cet6 = client.get("/api/stages").json()["items"][3]
    assert (cet6["unfamiliar"], cet6["unseen"]) == (1, cet6["total"] - 1)


def test_requires_login(client: TestClient):
    assert client.get("/api/stages").status_code == 401
    assert client.get("/api/vocab").status_code == 401


# ---------------------------------------------------------------------------------------------- vocab
def test_vocab_default_is_everything_sorted_by_frequency(client: TestClient, settings, alice):
    r = client.get("/api/vocab")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 60 and body["page"] == 1 and body["page_size"] == 50 and len(body["items"]) == 50
    lemmas = [i["lemma"] for i in body["items"]]
    assert lemmas[0] == "be"  # frq 2
    frqs = [i["frq"] for i in body["items"] if i["frq"]]
    assert frqs == sorted(frqs)
    page2 = client.get("/api/vocab?page=2").json()
    assert len(page2["items"]) == 10 and page2["items"][-1]["frq"] is None  # NULL/0 frequency sorts last
    assert set(body["items"][0]) == {
        "id", "lemma", "display", "kind", "phonetic", "translation_short", "stages", "stage_min", "cet6_star", "frq", "collins", "oxford",
        "difficulty", "is_public", "is_valid_english", "my_state", "content_state", "image_state",
    }


def test_vocab_stage_and_new_only(client: TestClient, settings, alice):
    assert client.get("/api/vocab?stage=cet6").json()["total"] == q1(settings, "SELECT COUNT(*) FROM words WHERE stage_cet6 = 1")
    r = client.get("/api/vocab?stage=cet6&new_only=1")
    assert r.status_code == 200 and r.json()["total"] == 3
    assert sorted(i["lemma"] for i in r.json()["items"]) == ["absorption", "axe", "ought to"]
    assert all(i["stage_min"] == 4 for i in r.json()["items"])
    r = client.get("/api/vocab?new_only=1")  # needs a stage
    assert r.status_code == 400 and r.json()["error"]["code"] == "validation_error"
    assert client.get("/api/vocab?stage=cet6&new_only=0").json()["total"] == q1(settings, "SELECT COUNT(*) FROM words WHERE stage_cet6 = 1")


def test_vocab_search_prefix_forms_and_chinese(client: TestClient, settings, alice):
    found = [i["lemma"] for i in client.get("/api/vocab?q=aband").json()["items"]]
    assert found == ["abandon"]
    found = [i["lemma"] for i in client.get("/api/vocab?q=abandoned").json()["items"]]
    assert found == ["abandon"]  # via word_forms
    found = [i["lemma"] for i in client.get("/api/vocab?q=went").json()["items"]]
    assert found == ["go"]
    found = [i["lemma"] for i in client.get("/api/vocab?q=放弃").json()["items"]]
    assert "abandon" in found
    assert client.get("/api/vocab?q=zzzzz").json()["total"] == 0
    assert client.get("/api/vocab?q=" + "a" * 65).status_code == 400
    r = client.get("/api/vocab?q=100%25")  # a stray % never becomes a wildcard
    assert r.status_code == 200 and r.json()["total"] == 0


def test_vocab_status_filters(client: TestClient, settings, alice):
    ids = {l: q1(settings, "SELECT id FROM words WHERE lemma = ?", (l,)) for l in ("abandon", "apple", "bank", "glass")}
    client.post(f"/api/words/{ids['abandon']}/mark", json={"action": "unfamiliar"})
    client.post(f"/api/words/{ids['apple']}/mark", json={"action": "known"})
    client.post(f"/api/words/{ids['bank']}/mark", json={"action": "unfamiliar"})
    client.post(f"/api/words/{ids['bank']}/mark", json={"action": "mastered"})
    client.post(f"/api/words/{ids['glass']}/mark", json={"action": "unfamiliar"})
    client.post(f"/api/words/{ids['glass']}/mark", json={"action": "remove"})
    get = lambda status: {i["lemma"]: i["my_state"] for i in client.get(f"/api/vocab?status={status}&page_size=100").json()["items"]}
    assert get("unfamiliar") == {"abandon": "new"}
    assert get("known") == {"apple": "known"}
    assert get("mastered") == {"bank": "mastered"}
    unmarked = get("unmarked")
    assert len(unmarked) == 57 and unmarked["glass"] == "removed" and "abandon" not in unmarked
    assert client.get("/api/vocab?status=all&page_size=100").json()["total"] == 60
    assert client.get("/api/vocab?status=bogus").status_code == 400


def test_vocab_sort_alpha_and_difficulty(client: TestClient, settings, alice):
    alpha = [i["lemma"] for i in client.get("/api/vocab?sort=alpha&page_size=100").json()["items"]]
    assert alpha == sorted(alpha) and alpha[0] == "a"
    # difficulty: COALESCE(difficulty, stage_min, 5) — a cet6-only word with difficulty 1 sorts before a stage_min-2 word with NULL difficulty
    run(settings, "UPDATE words SET difficulty = 1 WHERE lemma = 'absorption'")
    order = [i["lemma"] for i in client.get("/api/vocab?sort=difficulty&page_size=100").json()["items"]]
    assert order.index("absorption") < order.index("abandon") < order.index("absolutely")  # 1 < stage_min 2 < stage_min 3
    assert order[-1] == "ought to" or order[-3:] == sorted(order[-3:], key=lambda l: l)  # stage_min 4 group, NULL frq last
    again = [i["lemma"] for i in client.get("/api/vocab?sort=difficulty&page_size=100").json()["items"]]
    assert again == order  # deterministic
    zk = [i for i in client.get("/api/vocab?sort=difficulty&stage=zk&page_size=100").json()["items"]]
    keys = [(i["difficulty"] or i["stage_min"] or 5, i["frq"] is None or i["frq"] == 0, i["frq"] or 0, i["lemma"]) for i in zk]
    assert keys == sorted(keys)


def test_vocab_letter_filter_and_letters_endpoint(client: TestClient, settings, alice):
    a = client.get("/api/vocab?letter=a&page_size=100").json()
    assert a["total"] == q1(settings, "SELECT COUNT(*) FROM words WHERE lemma >= 'a' AND lemma < 'b'")
    assert all(i["lemma"].startswith("a") for i in a["items"])
    assert client.get("/api/vocab?letter=A").status_code == 400
    letters = client.get("/api/vocab/letters").json()["items"]
    assert [l["letter"] for l in letters] == list("abcdefghijklmnopqrstuvwxyz")
    counts = {l["letter"]: l["count"] for l in letters}
    assert counts["a"] == a["total"] and counts["z"] == 0 and sum(counts.values()) == 60
    cet6 = {l["letter"]: l["count"] for l in client.get("/api/vocab/letters?stage=cet6&new_only=1").json()["items"]}
    assert cet6 == {**{ch: 0 for ch in "abcdefghijklmnopqrstuvwxyz"}, "a": 2, "o": 1}
    # letters ignores letter/q: the counts cover the whole filter
    assert client.get("/api/vocab/letters?letter=b&q=zzz").json()["items"] == letters


def test_vocab_pagination_bounds_and_unknown_params(client: TestClient, alice):
    assert client.get("/api/vocab?page=0").status_code == 400
    assert client.get("/api/vocab?page_size=101").status_code == 400
    r = client.get("/api/vocab?bogus=1")
    assert r.status_code == 400 and "bogus" in r.json()["error"]["details"]["fields"]
    assert client.get("/api/vocab?page=9&page_size=10").json()["items"] == []


def test_vocab_never_lists_merged_or_invisible_words_and_never_enqueues(client: TestClient, settings, alice):
    bob, bob_token = make_user(settings, "bob")
    as_user(client, bob_token)
    r = client.post("/api/bank/add", json={"text": "zzqx"})
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "pending_ai"
    assert any(i["lemma"] == "zzqx" for i in client.get("/api/vocab?q=zzqx").json()["items"])  # the creator sees it
    as_user(client, next(t for _, t in [make_user(settings, "alice2")]))
    assert client.get("/api/vocab?q=zzqx").json()["total"] == 0  # a third user does not
    run(settings, "UPDATE words SET merged_into_word_id = (SELECT id FROM words WHERE lemma = 'abandon') WHERE lemma = 'abolish'")
    assert client.get("/api/vocab?q=abolish").json()["total"] == 0
    jobs_before = q1(settings, "SELECT COUNT(*) FROM jobs")
    client.get("/api/vocab?stage=cet4&page_size=100")
    client.get("/api/vocab/letters")
    client.get("/api/stages")
    assert q1(settings, "SELECT COUNT(*) FROM jobs") == jobs_before  # browsing never enqueues


def test_admin_sees_private_words(client: TestClient, settings, alice):
    r = client.post("/api/bank/add", json={"text": "zzqx"})
    assert r.status_code == 200
    _, admin_token = make_user(settings, "root", role="admin")
    as_user(client, admin_token)
    assert client.get("/api/vocab?q=zzqx").json()["total"] == 1


# ------------------------------------------------------------------------------------------ full seed
@pytest.mark.full_seed
def test_cet6_new_only_on_the_full_seed(settings, frozen_clock):
    """``stage=cet6&new_only=1`` → 3,694 (the CET-6 increment) and the sort/filter performance on 9,162 words."""
    from dataclasses import replace

    from wd.main import create_app

    assert FULL_SEED_DB, "WD_FULL_SEED_DB must point at a database with the full seed imported"
    src = Path(FULL_SEED_DB)
    dst = settings.data_dir / "full.db"
    shutil.copy(src, dst)
    seed_gz = Path(__file__).resolve().parents[3] / "data" / "seed" / "vocab.jsonl.gz"
    cfg = replace(settings, db_path=dst, seed_path=seed_gz)
    with TestClient(create_app(cfg, clock=frozen_clock, configure_logs=False)) as c:
        c.headers["X-WD-Request"] = "1"
        _, token = make_user(cfg, "full")
        as_user(c, token)
        r = c.get("/api/vocab?stage=cet6&new_only=1")
        assert r.status_code == 200 and r.json()["total"] == 3694
        assert c.get("/api/vocab?stage=cet6").json()["total"] == 7671
        assert c.get("/api/stages").json()["items"][3]["new_only_total"] == 3694
        import time

        t = time.perf_counter()
        for _ in range(5):
            assert c.get("/api/vocab?stage=cet6&sort=difficulty&page=41").status_code == 200
        assert (time.perf_counter() - t) / 5 < 0.5
