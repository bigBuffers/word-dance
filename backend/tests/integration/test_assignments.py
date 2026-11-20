"""布置词汇 (API.md 124–129, migration 0022): who may assign, the preview that writes nothing, a `today` list before and after the
day's batch exists, a `spread` list taking the daily quota, assigned items first on the 今日 list and in 磨耳朵, progress and withdraw."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from test_today_flow import START, as_user, grade, make_user, mark, q1, qrows, run, word_id


@pytest.fixture
def people(client: TestClient, settings, frozen_clock) -> dict:
    frozen_clock.set(START)
    teacher, t_tok = make_user(settings, "teacher")
    run(settings, "UPDATE users SET role = 'admin' WHERE id = ?", (teacher,))
    kid, k_tok = make_user(settings, "kid", daily_new_count=3, daily_screen_count=0, max_reviews=60)
    other, o_tok = make_user(settings, "other")
    return {"teacher": teacher, "t": t_tok, "kid": kid, "k": k_tok, "other": other, "o": o_tok}


def assign(client: TestClient, learner: int, text: str, mode: str = "today", status: int = 201, **extra) -> dict:
    r = client.post("/api/assignments", json={"learner_id": learner, "text": "\n".join(text.split()), "mode": mode, **extra})  # one word per line (bank.split_tokens: lines and commas, a phrase keeps its spaces)
    assert r.status_code == status, r.text
    return r.json()


def test_only_the_admin_or_the_guardian_may_assign(client: TestClient, settings, people):
    as_user(client, people["o"])  # an ordinary learner: nobody to assign to
    assert client.get("/api/assign/learners").json() == {"items": []}
    assert client.post("/api/assign/preview", json={"learner_id": people["kid"], "text": "apple"}).status_code == 403
    assign(client, people["kid"], "apple", status=403)
    as_user(client, people["t"])
    listed = client.get("/api/assign/learners").json()["items"]
    assert [(row["id"], row["name"]) for row in listed] == [(people["kid"], "kid"), (people["other"], "other"), (people["teacher"], "teacher")]  # the admin's own account last
    # a guardian sees and reaches only their own children
    run(settings, "UPDATE users SET account_kind = 'guardian' WHERE id = ?", (people["other"],))
    run(settings, "UPDATE users SET guardian_user_id = ? WHERE id = ?", (people["other"], people["kid"]))
    as_user(client, people["o"])
    assert client.get("/api/assign/learners").json() == {"items": [{"id": people["kid"], "name": "kid"}]}
    made = assign(client, people["kid"], "apple")
    assign(client, people["teacher"], "apple", status=403)
    # a list is its assigner's: another non-admin user gets 404, the admin reads it
    kid_id = made["assignment"]["id"]
    as_user(client, people["k"])
    assert client.get(f"/api/assignments/{kid_id}").status_code == 404 and client.post(f"/api/assignments/{kid_id}/withdraw").status_code == 404
    as_user(client, people["t"])
    assert client.get(f"/api/assignments/{kid_id}").status_code == 200 and client.get("/api/assignments").json() == {"items": []}


def test_preview_tells_what_would_happen_and_writes_nothing(client: TestClient, settings, people):
    as_user(client, people["k"])
    mark(client, word_id(settings, "cat"), context="browse")
    mark(client, word_id(settings, "dog"), "known", context="browse")
    before = {t: q1(settings, f"SELECT COUNT(*) FROM {t}") for t in ("words", "user_words", "review_logs", "jobs", "assignments", "assignment_words")}
    as_user(client, people["t"])
    r = client.post("/api/assign/preview", json={"learner_id": people["kid"], "text": "apple, cat，dog\napple\n123, zzyzxq"})
    assert r.status_code == 200, r.text
    rows = r.json()["items"]
    assert [(i["input"], i["status"]) for i in rows] == [("apple", "new"), ("cat", "studying"), ("dog", "known"), ("apple", "duplicate"), ("123", "invalid"), ("zzyzxq", "pending_ai")]
    assert rows[0]["word_id"] == word_id(settings, "apple") and rows[0]["display"] == "apple" and rows[0]["meaning"]
    assert before == {t: q1(settings, f"SELECT COUNT(*) FROM {t}") for t in before}
    assert client.post("/api/assign/preview", json={"learner_id": people["kid"], "text": " , "}).status_code == 400
    assert client.post("/api/assign/preview", json={"learner_id": people["kid"], "text": ",".join(f"w{i}" for i in range(51))}).json()["error"]["code"] == "too_many_words"


def test_a_today_list_made_before_the_batch_exceeds_the_quota_and_comes_first(client: TestClient, settings, frozen_clock, people):
    as_user(client, people["k"])
    for lemma in ("teacher", "water"):
        mark(client, word_id(settings, lemma), context="browse")  # the learner's own new words
    as_user(client, people["t"])
    made = assign(client, people["kid"], "apple bank cat dog", title="  第三单元  ")
    a = made["assignment"]
    assert (a["title"], a["mode"], a["learner"], a["counts"]) == ("第三单元", "today", {"id": people["kid"], "name": "kid"}, {"total": 4, "pending": 4, "scheduled": 0, "done": 0, "withdrawn": 0})
    assert [w["display"] for w in a["words"]] == ["apple", "bank", "cat", "dog"] and all(w["status"] == "pending" and w["learner_state"] == "new" for w in a["words"])
    assert q1(settings, "SELECT COUNT(*) FROM user_words WHERE user_id = ? AND origin = 'import'", (people["kid"],)) == 4
    as_user(client, people["k"])
    today = client.post("/api/today/build").json()
    items = today["batch"]["items"]
    # four assigned words although the quota is three; no ordinary new word joins them that day
    assert [(i["word"]["lemma"], i["kind"]) for i in items] == [("apple", "new"), ("bank", "new"), ("cat", "new"), ("dog", "new")]
    assert today["batch"]["assigned_item_ids"] == [i["item_id"] for i in items] and today["batch"]["counts"]["new"] == 4
    playlist = client.get("/api/today/playlist").json()["items"]
    assert [(p["display"], p["assigned"]) for p in playlist] == [("apple", True), ("bank", True), ("cat", True), ("dog", True)]
    # the assigner sees the day, then the grade and the skip
    grade(client, items[0]["item_id"], "master")
    grade(client, items[1]["item_id"], "skip")
    as_user(client, people["t"])
    seen = client.get(f"/api/assignments/{a['id']}").json()
    assert seen["counts"] == {"total": 4, "pending": 0, "scheduled": 4, "done": 1, "withdrawn": 0}
    assert [(w["display"], w["status"], w["scheduled_date"], w["kind"], w["result"], w["skip_count"]) for w in seen["words"][:2]] == [("apple", "scheduled", "2026-10-14", "new", "master", 0), ("bank", "scheduled", "2026-10-14", "new", None, 1)]
    assert client.get("/api/assignments").json()["items"][0]["counts"]["done"] == 1
    assert client.get("/api/assignments", params={"learner_id": people["other"]}).json() == {"items": []}
    # nothing is pending any more: a withdraw changes nothing
    assert client.post(f"/api/assignments/{a['id']}/withdraw").json()["counts"]["withdrawn"] == 0
    # the next day the learner's own words get their turn
    frozen_clock.set(START + timedelta(days=1))
    as_user(client, people["k"])
    tomorrow = client.post("/api/today/build").json()
    assert {i["word"]["lemma"] for i in tomorrow["batch"]["items"] if i["kind"] == "new"} >= {"teacher", "water"} and tomorrow["batch"]["assigned_item_ids"] == []


def test_a_today_list_made_after_the_batch_is_appended_and_a_word_being_studied_is_practised_once(client: TestClient, settings, frozen_clock, people):
    as_user(client, people["k"])
    for lemma in ("teacher", "water", "house"):
        mark(client, word_id(settings, lemma), context="browse")
    first = client.post("/api/today/build").json()["batch"]["items"]
    by = {i["word"]["lemma"]: i for i in first}
    grade(client, by["teacher"]["item_id"], "good")  # teacher is learning now; house and water are still new items of the day
    as_user(client, people["t"])
    a = assign(client, people["kid"], "apple teacher house")["assignment"]
    assert a["counts"] == {"total": 3, "pending": 0, "scheduled": 3, "done": 0, "withdrawn": 0}  # teacher rides on the item it already has (its `good` was an intermediate grade)
    assert [(w["display"], w["kind"]) for w in a["words"]] == [("apple", "extra"), ("teacher", "new"), ("house", "new")]
    as_user(client, people["k"])
    today = client.get("/api/today").json()["batch"]
    open_items = [(i["word"]["lemma"], i["kind"]) for i in today["items"] if i["result"] is None]
    assert set(open_items[:3]) == {("teacher", "new"), ("house", "new"), ("apple", "extra")} and open_items[3:] == [("water", "new")]  # assigned first, then the rest
    assert len(today["assigned_item_ids"]) == 3 and today["counts"]["extra"] == 1
    assert [p["display"] for p in client.get("/api/today/playlist").json()["items"] if p["assigned"]] == [p["display"] for p in client.get("/api/today/playlist").json()["items"]][:3]
    # a second list with the same word does not add a second card
    as_user(client, people["t"])
    again = assign(client, people["kid"], "apple")["assignment"]
    assert again["counts"]["scheduled"] == 1 and q1(settings, "SELECT COUNT(*) FROM push_items pi JOIN words w ON w.id = pi.word_id WHERE w.lemma = 'apple'") == 1
    # a word already studied on an earlier day is practised once as `extra` in the next batch
    frozen_clock.set(START + timedelta(days=1))
    later = assign(client, people["kid"], "teacher", mode="spread")["assignment"]
    assert later["counts"]["pending"] == 1
    as_user(client, people["k"])
    kinds = {i["word"]["lemma"]: i["kind"] for i in client.post("/api/today/build").json()["batch"]["items"]}
    assert kinds["teacher"] in ("review", "extra")
    assert q1(settings, "SELECT status FROM assignment_words WHERE assignment_id = ?", (later["id"],)) == "scheduled"


def test_a_spread_list_takes_the_daily_quota_and_can_be_withdrawn(client: TestClient, settings, frozen_clock, people):
    as_user(client, people["k"])
    mark(client, word_id(settings, "teacher"), context="browse")
    client.post("/api/today/build")  # today's batch exists: a spread list starts tomorrow
    as_user(client, people["t"])
    a = assign(client, people["kid"], "apple bank cat dog glass", mode="spread")["assignment"]
    assert a["counts"]["pending"] == 5
    frozen_clock.set(START + timedelta(days=1))
    as_user(client, people["k"])
    day2 = client.post("/api/today/build").json()["batch"]
    assert [i["word"]["lemma"] for i in day2["items"] if i["kind"] == "new"] == ["apple", "bank", "cat"] and len(day2["assigned_item_ids"]) == 3
    as_user(client, people["t"])
    left = client.post(f"/api/assignments/{a['id']}/withdraw").json()
    assert left["counts"] == {"total": 5, "pending": 0, "scheduled": 3, "done": 0, "withdrawn": 2}
    assert [w["status"] for w in left["words"]] == ["scheduled", "scheduled", "scheduled", "withdrawn", "withdrawn"]
    frozen_clock.set(START + timedelta(days=2))
    as_user(client, people["k"])
    day3 = client.post("/api/today/build").json()["batch"]
    assert day3["assigned_item_ids"] == []
    # the withdrawn words stay ordinary new words of the learner's bank
    assert {r["state"] for r in qrows(settings, "SELECT uw.state FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? AND w.lemma IN ('dog','glass')", (people["kid"],))} <= {"new", "learning"}


def test_a_list_without_any_assignable_word_is_refused_and_known_words_are_left_alone(client: TestClient, settings, people):
    as_user(client, people["k"])
    mark(client, word_id(settings, "dog"), "known", context="browse")
    as_user(client, people["t"])
    r = client.post("/api/assignments", json={"learner_id": people["kid"], "text": "dog, 123", "mode": "today"})
    assert r.status_code == 400 and q1(settings, "SELECT COUNT(*) FROM assignments") == 0
    assert client.post("/api/assignments", json={"learner_id": people["kid"], "text": "apple", "mode": "weekly"}).status_code in (400, 422)
    made = assign(client, people["kid"], "dog apple")
    assert [(i["input"], i["status"]) for i in made["results"]] == [("dog", "known"), ("apple", "new")] and made["assignment"]["counts"]["total"] == 1
    assert q1(settings, "SELECT state FROM user_words uw JOIN words w ON w.id = uw.word_id WHERE uw.user_id = ? AND w.lemma = 'dog'", (people["kid"],)) == "known"
