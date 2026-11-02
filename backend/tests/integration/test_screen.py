"""GET /api/screen/next and POST /api/screen/verdict (WP3, API.md 31–32), incl. the in-batch verdict path of
services.screen.apply_verdict with a local stand-in for WP4's batches.append_to_today."""

from __future__ import annotations

import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from wd import db
from wd.deps import hash_token
from wd.services import batches

FAR = "2030-01-01T00:00:00Z"
TZ = "Asia/Shanghai"


# -------------------------------------------------------------------------------------------- helpers
def make_user(settings, username: str, *, role: str = "user", **cols) -> tuple[int, str]:
    conn = db.connect(settings.db_path)
    try:
        with db.tx(conn):
            cur = conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done')", (username, role))
            uid = int(cur.lastrowid)
            names = ["user_id", *cols]
            conn.execute(f"INSERT INTO user_settings({', '.join(names)}) VALUES ({', '.join('?' * len(names))})", (uid, *cols.values()))
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)", (hash_token(token), uid, FAR))
        return uid, token
    finally:
        conn.close()


def as_user(client: TestClient, token: str) -> None:
    client.cookies.set("wd_session", token)


def session_for(settings, user_id: int) -> str:
    """A fresh session cookie for an existing user."""
    conn = db.connect(settings.db_path)
    try:
        token = secrets.token_urlsafe(32)
        with db.tx(conn):
            conn.execute("INSERT INTO sessions(token_hash, user_id, expires_at) VALUES (?, ?, ?)", (hash_token(token), user_id, FAR))
        return token
    finally:
        conn.close()


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


def verdict(client: TestClient, word_id: int, v: str, **extra) -> dict:
    body = {"client_event_id": str(uuid.uuid4()), "word_id": word_id, "verdict": v, **extra}
    r = client.post("/api/screen/verdict", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def install_fake_batches(monkeypatch) -> list:
    """A stand-in for WP4's ``batches.append_to_today``: appends a row of ``kind`` at the end of today's batch unless a
    review/new/extra row for the word exists (TASKS §I contract)."""
    calls: list = []

    def append_to_today(conn, user_id, word_id, kind, now):
        calls.append((user_id, word_id, kind))
        from wd.services import bank

        batch = bank.today_batch(conn, user_id, bank.local_date_str(bank.coerce_now(now)[0], TZ))
        if batch is None:
            return None
        if conn.execute("SELECT 1 FROM push_items WHERE batch_id = ? AND word_id = ? AND kind IN ('review','new','extra')", (batch["id"], word_id)).fetchone():
            return None
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM push_items WHERE batch_id = ?", (batch["id"],)).fetchone()[0]
        uw = conn.execute("SELECT id FROM user_words WHERE user_id = ? AND word_id = ?", (user_id, word_id)).fetchone()
        cur = conn.execute(
            "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, ?, ?)",
            (batch["id"], word_id, None if uw is None else uw[0], kind, pos),
        )
        return int(cur.lastrowid)

    monkeypatch.setattr(batches, "append_to_today", append_to_today)
    return calls


@pytest.fixture
def alice(client: TestClient, settings) -> int:
    uid, token = make_user(settings, "alice", stages_json='["cet4","cet6"]', current_stage=4, daily_new_count=10)
    as_user(client, token)
    return uid


# ------------------------------------------------------------------------------------------------ next
def test_next_order_and_remaining(client: TestClient, settings, alice):
    r = client.get("/api/screen/next?stage=auto&count=5")
    assert r.status_code == 200, r.text
    b = r.json()
    total = q1(settings, "SELECT COUNT(*) FROM words WHERE (stage_cet4 = 1 OR stage_cet6 = 1) AND is_public = 1 AND is_valid_english = 1")
    assert b["remaining"] == total and len(b["items"]) == 5
    lemmas = [i["word"]["lemma"] for i in b["items"]]
    # 主攻阶段 cet6 first (stage_min 4 = absorption / axe / ought to by frequency), then stage 3, then stage 2 …
    assert lemmas[:3] == ["absorption", "axe", "ought to"]
    assert all(i["word"]["my_state"] is None for i in b["items"]) and b["items"][0]["phonetic"] == b["items"][0]["word"]["phonetic"]
    r = client.get("/api/screen/next?stage=zk&count=3").json()
    assert [i["word"]["lemma"] for i in r["items"]] == ["be", "a", "go"]  # stage zk (stage_min 1): by frequency 2, 5, 35
    assert r["remaining"] == q1(settings, "SELECT COUNT(*) FROM words WHERE stage_zk = 1")
    assert client.get("/api/screen/next?count=0").status_code == 400
    assert client.get("/api/screen/next?stage=xx").status_code == 400
    assert q1(settings, "SELECT COUNT(*) FROM jobs") == 0  # no side effects


def test_next_default_count_and_default_settings(client: TestClient, settings):
    uid, token = make_user(settings, "nosettings")
    run(settings, "DELETE FROM user_settings WHERE user_id = ?", (uid,))
    as_user(client, token)
    r = client.get("/api/screen/next")
    assert r.status_code == 200 and len(r.json()["items"]) == 1  # defaults: count 1, stages cet4+cet6, current cet4


def test_next_excludes_bank_known_mastered_removed_and_private_words(client: TestClient, settings, alice):
    ids = {l: word_id(settings, l) for l in ("absorption", "axe", "ought to", "abandon")}
    client.post(f"/api/words/{ids['absorption']}/mark", json={"action": "unfamiliar"})
    client.post(f"/api/words/{ids['axe']}/mark", json={"action": "known"})
    client.post(f"/api/words/{ids['ought to']}/mark", json={"action": "unfamiliar"})
    client.post(f"/api/words/{ids['ought to']}/mark", json={"action": "mastered"})
    client.post(f"/api/words/{ids['abandon']}/mark", json={"action": "unfamiliar"})
    client.post(f"/api/words/{ids['abandon']}/mark", json={"action": "remove"})
    bob, bob_token = make_user(settings, "bob")
    as_user(client, bob_token)
    client.post("/api/bank/add", json={"text": "zzqx"})
    run(settings, "UPDATE words SET stage_cet6 = 1, stage_min = 4 WHERE lemma = 'zzqx'")  # even with a stage flag a private word never screens
    _, carol_token = make_user(settings, "carol")
    as_user(client, carol_token)
    assert "zzqx" not in [i["word"]["lemma"] for i in client.get("/api/screen/next?stage=auto&count=50").json()["items"]]
    as_user(client, session_for(settings, alice))
    lemmas = [i["word"]["lemma"] for i in client.get("/api/screen/next?stage=auto&count=50").json()["items"]]
    assert not {"absorption", "axe", "ought to", "abandon", "zzqx"} & set(lemmas)
    total = q1(settings, "SELECT COUNT(*) FROM words WHERE (stage_cet4 = 1 OR stage_cet6 = 1) AND is_public = 1 AND is_valid_english = 1")
    assert client.get("/api/screen/next?stage=auto&count=1").json()["remaining"] == total - 4 == len(lemmas) + 3


# ---------------------------------------------------------------------------------------------- verdicts
def test_verdicts_on_the_screen_page(client: TestClient, settings, alice):
    w_unf, w_known, w_skip = (word_id(settings, l) for l in ("absorption", "axe", "ought to"))
    r = verdict(client, w_unf, "unfamiliar")
    assert r["verdict"] == "unfamiliar" and r["mine"]["state"] == "new" and r["mine"]["origin"] == "screen" and r["added_to_today"] is False
    assert r["study_item"] is None and r["today"] is None and r["duplicate"] is False
    r = verdict(client, w_known, "known", context="onboarding")
    assert r["mine"]["state"] == "known" and r["mine"]["origin"] == "screen"
    r = verdict(client, w_skip, "skip")
    assert r["mine"] is None
    assert q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,)) == 2
    logs = qrows(settings, "SELECT action, context, client_event_id FROM review_logs WHERE user_id = ? ORDER BY id", (alice,))
    assert [(l["action"], l["context"]) for l in logs] == [("unfamiliar", "screen_page"), ("known", "onboarding"), ("skip", "screen_page")]
    assert all(l["client_event_id"] for l in logs)
    stats = qrows(settings, "SELECT * FROM daily_stats WHERE user_id = ?", (alice,))[0]
    assert (stats["added"], stats["known"], stats["screened"]) == (1, 1, 2)
    assert q1(settings, "SELECT COUNT(*) FROM jobs WHERE type = 'generate_content'") == 1  # the unfamiliar validated word wants content
    remaining = client.get("/api/screen/next?stage=auto&count=1").json()["remaining"]
    assert remaining == q1(settings, "SELECT COUNT(*) FROM words WHERE (stage_cet4 = 1 OR stage_cet6 = 1) AND is_public = 1") - 2


def test_duplicate_client_event_id_returns_the_stored_response(client: TestClient, settings, alice):
    w = word_id(settings, "absorption")
    event = str(uuid.uuid4())
    first = client.post("/api/screen/verdict", json={"client_event_id": event, "word_id": w, "verdict": "unfamiliar"}).json()
    again = client.post("/api/screen/verdict", json={"client_event_id": event, "word_id": w, "verdict": "unfamiliar"}).json()
    assert again["duplicate"] is True and {k: v for k, v in again.items() if k != "duplicate"} == {k: v for k, v in first.items() if k != "duplicate"}
    assert q1(settings, "SELECT COUNT(*) FROM review_logs WHERE user_id = ?", (alice,)) == 1
    assert client.post("/api/screen/verdict", json={"client_event_id": "nope", "word_id": w, "verdict": "known"}).status_code == 400
    assert client.post("/api/screen/verdict", json={"client_event_id": str(uuid.uuid4()), "word_id": 999999, "verdict": "known"}).status_code == 404


def test_restore_of_a_screen_known_puts_the_word_back_into_next(client: TestClient, settings, alice, frozen_clock):
    w = word_id(settings, "absorption")
    verdict(client, w, "known")
    assert "absorption" not in [i["word"]["lemma"] for i in client.get("/api/screen/next?count=3").json()["items"]]
    frozen_clock.advance(seconds=4)
    r = client.post(f"/api/words/{w}/mark", json={"action": "restore", "context": "screen_page"})
    assert r.status_code == 200 and r.json()["state"] is None
    assert [i["word"]["lemma"] for i in client.get("/api/screen/next?count=3").json()["items"]][0] == "absorption"
    stats = qrows(settings, "SELECT * FROM daily_stats WHERE user_id = ?", (alice,))[0]
    assert (stats["known"], stats["screened"]) == (0, 0)


def test_screen_page_unfamiliar_appends_to_today_when_a_batch_exists(client: TestClient, settings, alice, monkeypatch):
    calls = install_fake_batches(monkeypatch)
    w = word_id(settings, "absorption")
    assert verdict(client, w, "unfamiliar")["added_to_today"] is False  # no batch today
    assert calls == []
    batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'ready', 'manual')", (alice,))
    w2 = word_id(settings, "axe")
    r = verdict(client, w2, "unfamiliar")
    assert r["added_to_today"] is True and r["study_item"]["kind"] == "new" and r["study_item"]["word"]["lemma"] == "axe"
    assert r["study_item"]["mine"]["state"] == "new" and r["study_item"]["result"] is None and r["study_item"]["image"]["kind"] == "card"
    assert calls == [(alice, w2, "new")]
    assert q1(settings, "SELECT COUNT(*) FROM push_items WHERE batch_id = ? AND word_id = ? AND kind = 'new'", (batch, w2)) == 1
    # quota exhausted → no study row; `today` still carries today's counts so the page can say 「明天开始学」
    run(settings, "UPDATE user_settings SET daily_new_count = 1 WHERE user_id = ?", (alice,))
    r = verdict(client, word_id(settings, "ought to"), "unfamiliar")
    assert r["added_to_today"] is False and r["study_item"] is None and len(calls) == 1
    assert r["today"]["new"] == 1 and r["today"]["total"] == 1


def test_screen_page_verdict_carries_todays_counts_when_a_batch_exists(client: TestClient, settings, alice):
    """ScreenResponse.today (API.md 32): null without a batch today (test_verdicts_on_the_screen_page), otherwise the
    TodayCounts of today's batch — the 筛词 page picks 「已加入生词库，明天开始学」 from it when the word did not fit."""
    run(settings, "UPDATE user_settings SET daily_new_count = 1 WHERE user_id = ?", (alice,))
    run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    r1 = verdict(client, word_id(settings, "absorption"), "unfamiliar")  # the real batches.append_to_today
    assert r1["added_to_today"] is True and r1["study_item"]["kind"] == "new" and r1["today"]["new"] == 1 and r1["today"]["total"] == 1
    r2 = verdict(client, word_id(settings, "axe"), "unfamiliar")  # quota full → tomorrow
    assert r2["added_to_today"] is False and r2["study_item"] is None and r2["today"]["new"] == 1 and r2["mine"]["state"] == "new"
    r3 = verdict(client, word_id(settings, "ought to"), "known")
    assert r3["mine"]["state"] == "known" and r3["today"]["new"] == 1
    assert q1(settings, "SELECT COUNT(*) FROM push_items") == 1
    # the stored duplicate replay carries the same counts
    event = str(uuid.uuid4())
    first = client.post("/api/screen/verdict", json={"client_event_id": event, "word_id": word_id(settings, "abandon"), "verdict": "unfamiliar"}).json()
    again = client.post("/api/screen/verdict", json={"client_event_id": event, "word_id": word_id(settings, "abandon"), "verdict": "unfamiliar"}).json()
    assert again["duplicate"] is True and again["today"] == first["today"] and first["today"]["new"] == 1


def test_in_batch_verdict_on_yesterdays_batch_checks_todays_quota(client: TestClient, settings, alice):
    """继续昨天的学习: a 推荐词 graded unfamiliar in yesterday's still-open batch is appended to TODAY's batch only while
    today's new-word quota has room (the append always lands in today's batch) — never past daily_new_count."""
    from wd.services import screen

    run(settings, "UPDATE user_settings SET daily_new_count = 3 WHERE user_id = ?", (alice,))
    w_yday, w_more = word_id(settings, "absorption"), word_id(settings, "ought to")
    yday = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-13', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    item = run(settings, "INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 0)", (yday, w_yday))
    item_more = run(settings, "INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 1)", (yday, w_more))
    today = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    for pos, lemma in enumerate(("abandon", "axe", "base")):  # today's batch already holds 3/3 new words
        wid = word_id(settings, lemma)
        client.post(f"/api/words/{wid}/mark", json={"action": "unfamiliar", "context": "bank"})
        uw = q1(settings, "SELECT id FROM user_words WHERE user_id = ? AND word_id = ?", (alice, wid))
        run(settings, "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, 'new', ?)", (today, wid, uw, pos))
    conn = db.connect(settings.db_path)
    try:
        r = screen.apply_verdict(conn, alice, w_yday, "unfamiliar", client_event_id=str(uuid.uuid4()), context="today", push_item_id=item, now="2026-10-14T12:00:00Z", tz=TZ)
        assert r["mine"]["state"] == "new" and r["added_to_today"] is False and r["study_item"] is None
        assert r["today"]["new"] == 3  # today's counts: the batch the word did not fit into
        assert conn.execute("SELECT COUNT(*) FROM push_items WHERE batch_id = ? AND kind = 'new'", (today,)).fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM push_items WHERE batch_id = ?", (yday,)).fetchone()[0] == 2  # nothing appended to yesterday either
        assert conn.execute("SELECT result FROM push_items WHERE id = ?", (item,)).fetchone()[0] == "unfamiliar"
        # mirror: room in today's batch → the study row joins TODAY's batch, not yesterday's
        conn.execute("UPDATE user_settings SET daily_new_count = 5 WHERE user_id = ?", (alice,))
        r2 = screen.apply_verdict(conn, alice, w_more, "unfamiliar", client_event_id=str(uuid.uuid4()), context="today", push_item_id=item_more, now="2026-10-14T12:00:05Z", tz=TZ)
        assert r2["added_to_today"] is True and r2["study_item"]["kind"] == "new" and r2["today"]["new"] == 4
        assert conn.execute("SELECT batch_id FROM push_items WHERE id = ?", (r2["study_item"]["item_id"],)).fetchone()[0] == today
    finally:
        conn.close()


def test_in_batch_verdicts_via_the_service(client: TestClient, settings, alice, monkeypatch):
    """What WP4's grade_item delegates: a 推荐词 graded inside the batch (push_item_id set)."""
    from wd.services import screen

    install_fake_batches(monkeypatch)
    w = word_id(settings, "absorption")
    w_known = word_id(settings, "axe")
    batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    item = run(settings, "INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 0)", (batch, w))
    item_known = run(settings, "INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 1)", (batch, w_known))
    conn = db.connect(settings.db_path)
    try:
        r = screen.apply_verdict(conn, alice, w, "unfamiliar", client_event_id=str(uuid.uuid4()), context="today", push_item_id=item, now="2026-10-14T01:00:00Z", tz=TZ)
        assert r["added_to_today"] is True and r["study_item"]["kind"] == "new" and r["study_item"]["item_id"] != item
        assert r["study_item"]["position"] == 2 and r["mine"]["origin"] == "push"
        rows = [dict(x) for x in conn.execute("SELECT kind, result, user_word_id FROM push_items WHERE batch_id = ? AND word_id = ? ORDER BY position", (batch, w))]
        assert rows == [{"kind": "screen", "result": "unfamiliar", "user_word_id": r["mine"]["id"]}, {"kind": "new", "result": None, "user_word_id": r["mine"]["id"]}]
        # a second unfamiliar on the same screen item (another event) → status exists, no second study row
        r2 = screen.apply_verdict(conn, alice, w, "unfamiliar", client_event_id=str(uuid.uuid4()), context="today", push_item_id=item, now="2026-10-14T01:00:05Z", tz=TZ)
        assert r2["added_to_today"] is False
        assert conn.execute("SELECT COUNT(*) FROM push_items WHERE batch_id = ? AND word_id = ?", (batch, w)).fetchone()[0] == 2
        rk = screen.apply_verdict(conn, alice, w_known, "known", client_event_id=str(uuid.uuid4()), context="today", push_item_id=item_known, now="2026-10-14T01:00:10Z", tz=TZ)
        assert rk["mine"]["state"] == "known" and rk["study_item"] is None
        assert conn.execute("SELECT result FROM push_items WHERE id = ?", (item_known,)).fetchone()[0] == "known"
        log = dict(conn.execute("SELECT * FROM review_logs WHERE user_id = ? AND word_id = ? AND action = 'known'", (alice, w_known)).fetchone())
        assert (log["push_item_id"], log["batch_id"], log["context"]) == (item_known, batch, "today")
        stats = dict(conn.execute("SELECT * FROM daily_stats WHERE user_id = ?", (alice,)).fetchone())
        assert (stats["added"], stats["known"], stats["screened"]) == (1, 1, 2)
        # skip inside the batch bumps skip_count only
        item_skip = conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 5)", (batch, word_id(settings, "ought to"))).lastrowid
        rs = screen.apply_verdict(conn, alice, word_id(settings, "ought to"), "skip", client_event_id=str(uuid.uuid4()), context="today", push_item_id=item_skip, now="2026-10-14T01:00:20Z", tz=TZ)
        assert rs["mine"] is None and tuple(conn.execute("SELECT skip_count, result FROM push_items WHERE id = ?", (item_skip,)).fetchone()) == (1, None)
        # a non-screen item is refused
        from wd.errors import ApiError

        card = conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'new', 6)", (batch, word_id(settings, "abandon"))).lastrowid
        with pytest.raises(ApiError) as e:
            screen.apply_verdict(conn, alice, word_id(settings, "abandon"), "known", client_event_id=str(uuid.uuid4()), context="today", push_item_id=card, now="2026-10-14T01:00:30Z", tz=TZ)
        assert e.value.code == "invalid_transition"
    finally:
        conn.close()
    # the HTTP restore of the in-batch unfamiliar removes the appended row and clears the screen item
    r = client.post(f"/api/words/{w}/mark", json={"action": "restore", "context": "today"})
    assert r.status_code == 409  # the idempotent `unfamiliar` (status exists) was the most recent log row → not undoable


def test_in_batch_unfamiliar_then_restore(client: TestClient, settings, alice, monkeypatch, frozen_clock):
    from wd.services import screen

    install_fake_batches(monkeypatch)
    w = word_id(settings, "absorption")
    batch = run(settings, "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (alice,))
    item = run(settings, "INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'screen', 0)", (batch, w))
    conn = db.connect(settings.db_path)
    try:
        r = screen.apply_verdict(conn, alice, w, "unfamiliar", client_event_id=str(uuid.uuid4()), context="today", push_item_id=item, now="2026-10-14T00:00:00Z", tz=TZ)
        new_item = r["study_item"]["item_id"]
    finally:
        conn.close()
    frozen_clock.advance(seconds=10)
    r = client.post(f"/api/words/{w}/mark", json={"action": "restore", "context": "today"})
    assert r.status_code == 200 and r.json()["state"] is None
    assert q1(settings, "SELECT COUNT(*) FROM push_items WHERE id = ?", (new_item,)) == 0
    assert qrows(settings, "SELECT result, graded_at, user_word_id FROM push_items WHERE id = ?", (item,))[0] == {"result": None, "graded_at": None, "user_word_id": None}
    stats = qrows(settings, "SELECT * FROM daily_stats WHERE user_id = ?", (alice,))[0]
    assert (stats["added"], stats["screened"]) == (0, 0)
    assert q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ?", (alice,)) == 0


def test_verdict_without_a_batch_today_never_appends(client: TestClient, settings, alice):
    """The real WP4 append_to_today with no batch for today → ``added_to_today:false`` and no ``study_item``."""
    r = verdict(client, word_id(settings, "absorption"), "unfamiliar")
    assert r["added_to_today"] is False and r["study_item"] is None and r["mine"]["state"] == "new"
    assert q1(settings, "SELECT COUNT(*) FROM push_items") == 0
