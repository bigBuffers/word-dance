"""ai/consolidate.py (CLAUDE_INTEGRATION §6.6): inputs and prompt, auto-apply only for verifiable lemmatize / fill_data /
difficulty, spelling fixes and merges as suggestions, invalid_word on provisional rows only, confusable groups limited to
bank headwords, ids outside the batch ignored, the `trigger` payload key, run bookkeeping and the handler."""

from __future__ import annotations

import json
import logging

import pytest

from wd import db
from wd.ai import consolidate
from wd.jobs import queue, registry
from wd.jobs.registry import JobContext
from wd.services import bank, words

NOW = "2026-10-14T00:00:00Z"
TZ = "Asia/Shanghai"
FILL_EMPTY = {"phonetic": "", "pos": "", "meaning_zh": "", "definition_en": "", "difficulty": 3}


@pytest.fixture
def ctx(settings, connect, frozen_clock):
    registry.load_handlers()
    return JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("t"), worker_id="claude-1", boot_id="test")


@pytest.fixture
def alice(seeded):
    uid = int(seeded.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES ('alice', 'x', 'done')").lastrowid)
    seeded.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    return uid


def wid(conn, lemma):
    return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0])


def add(conn, uid, text, note=None):
    (res,) = bank.add_custom_words(conn, uid, text, note, False, NOW, TZ)
    return res.word_id


def mark(conn, uid, lemma):
    bank.apply_action(conn, uid, wid(conn, lemma), "unfamiliar", origin="browse", context="browse", now=NOW, tz=TZ)
    return wid(conn, lemma)


def item(uw_id, verdict, target="", note="", confidence=0.9, fill=None):
    return {"id": uw_id, "verdict": verdict, "target": target, "confidence": confidence, "note_zh": note, "fill": fill or dict(FILL_EMPTY)}


def run_apply(conn, uid, result):
    run_id = consolidate.start_run(conn, uid, "manual", 0, now=NOW)
    items = consolidate.select_items(conn, uid, since=None)
    batch = {int(r["uw_id"]): r for r in items}
    summary = consolidate.apply(conn, uid, run_id, batch, result, now=NOW, tz=TZ, headwords=consolidate.bank_headwords(conn, uid))
    return run_id, batch, summary


def suggestions(conn, uid, type_=None):
    sql = "SELECT * FROM bank_suggestions WHERE user_id = ?" + (" AND type = ?" if type_ else "") + " ORDER BY id"
    return [db.row_to_dict(r) for r in conn.execute(sql, (uid, type_) if type_ else (uid,)).fetchall()]


# -------------------------------------------------------------------------------------------- inputs
def test_inputs_and_prompt(seeded, alice):
    prov = add(seeded, alice, "abandonned", note="from the meeting notes\x07 about <b>X</b>" + "y" * 200)
    mark(seeded, alice, "abandon")
    items = consolidate.select_items(seeded, alice, since=None)
    assert {r["lemma"] for r in items} == {"abandonned", "abandon"}  # abandon: difficulty NULL → examined
    seeded.execute("UPDATE words SET difficulty = 2 WHERE lemma = 'abandon'")
    later = consolidate.select_items(seeded, alice, since="2026-10-14T00:00:01Z")
    assert [r["lemma"] for r in later] == ["abandonned"]  # unvalidated rows are always examined; abandon unchanged since
    p = consolidate.prompt_item(items[0] if items[0]["lemma"] == "abandonned" else items[1])
    assert p["id"] == bank.my_row(seeded, alice, prov)["id"] and p["input"] == "abandonned" and p["headword"] == "abandonned"
    assert p["has_dictionary_data"] is False and p["difficulty"] is None
    assert len(p["note"]) <= 120 and "\x07" not in p["note"] and "<b>" not in p["note"] and p["note"].startswith("from the meeting notes about X")
    assert consolidate.bank_headwords(seeded, alice) == ["abandon", "abandonned"]
    prompt = consolidate.build_user_prompt(["abandon"], [p])
    data = json.loads(prompt.split("<items>\n", 1)[1].split("\n</items>", 1)[0])
    assert data["bank_headwords"] == ["abandon"] and data["items"][0]["id"] == p["id"]
    assert "note" not in consolidate.prompt_item({**items[0], "note": None})


def test_enqueue_uses_the_trigger_key(seeded, alice):
    job_id = consolidate.enqueue_for_user(seeded, alice, trigger="manual", now=NOW)
    job = queue.get_job(seeded, job_id)
    assert job.payload == {"user_id": alice, "trigger": "manual"} and job.dedupe_key == f"consolidate:{alice}:2026-10-14" and job.priority == 10


# ---------------------------------------------------------------------------------------------- rules
def test_lemmatize_auto_only_when_verifiable_and_target_not_in_bank(seeded, alice):
    prov = add(seeded, alice, "abandonning")
    uw = bank.my_row(seeded, alice, prov)
    seeded.execute("UPDATE user_words SET state = 'learning', repetitions = 3, ease = 2.4 WHERE id = ?", (uw["id"],))
    abandon = wid(seeded, "abandon")
    run_id, _, summary = run_apply(seeded, alice, {"items": [item(uw["id"], "lemmatize", "abandon", "是 abandon 的变形")], "confusable_groups": [], "difficulty_tags": []})
    assert summary.auto_applied == 1 and summary.suggestions == 0
    row = db.row_to_dict(seeded.execute("SELECT * FROM user_words WHERE id = ?", (uw["id"],)).fetchone())
    assert row["word_id"] == abandon and row["repetitions"] == 3 and row["ease"] == 2.4 and row["state"] == "learning"
    (s,) = suggestions(seeded, alice)
    assert s["status"] == "auto" and s["type"] == "lemmatize" and s["run_id"] == run_id and json.loads(s["undo_json"]) == {"prev_word_id": prov}
    assert s["expires_at"] == "2026-10-21T00:00:00Z" and json.loads(s["payload_json"])["to"] == "abandon"
    assert seeded.execute("SELECT COUNT(*) FROM review_logs WHERE action = 'consolidate' AND word_id = ?", (abandon,)).fetchone()[0] == 1
    assert queue.live_job(seeded, f"content:{abandon}") is not None  # the headword wants content


def test_lemmatize_is_a_suggestion_when_target_in_bank_or_unrelated_or_seed(seeded, alice):
    prov = add(seeded, alice, "abandonning")
    abandon = mark(seeded, alice, "abandon")
    uw = bank.my_row(seeded, alice, prov)
    base_uw = bank.my_row(seeded, alice, mark(seeded, alice, "base"))
    happy_uw = bank.my_row(seeded, alice, mark(seeded, alice, "happy"))
    glass_uw = bank.my_row(seeded, alice, mark(seeded, alice, "glass"))
    result = {
        "items": [
            item(uw["id"], "lemmatize", "abandon"),  # target already in the bank → suggestion
            item(base_uw["id"], "lemmatize", "basis"),  # seed word → never auto
            item(happy_uw["id"], "lemmatize", "happiness"),  # related but unknown target → suggestion for a target created through the §5.2 chain
            item(glass_uw["id"], "lemmatize", "glasses"),  # resolves back to glass itself → downgraded to ok
        ],
        "confusable_groups": [],
        "difficulty_tags": [],
    }
    _, _, summary = run_apply(seeded, alice, result)
    assert summary.auto_applied == 0 and summary.suggestions == 3 and summary.downgraded == [glass_uw["id"]]
    assert bank.my_row(seeded, alice, prov)["word_id"] == prov
    open_ = suggestions(seeded, alice, "lemmatize")
    assert [s["status"] for s in open_] == ["open"] * 3 and open_[0]["target_word_id"] == abandon and open_[0]["expires_at"] == "2026-11-13T00:00:00Z"
    assert open_[1]["target_word_id"] == wid(seeded, "basis")
    created = words.word_row(seeded, open_[2]["target_word_id"])
    assert created["lemma"] == "happiness" and created["source"] == "user" and created["is_valid_english"] is None and queue.live_job(seeded, f"lookup:{created['id']}") is not None
    _, _, again = run_apply(seeded, alice, result)
    assert again.suggestions == 0 and len(suggestions(seeded, alice, "lemmatize")) == 3  # no duplicates


def test_fix_spelling_is_always_a_suggestion_even_when_the_typo_is_a_headword(seeded, alice):
    base = mark(seeded, alice, "base")
    uw = bank.my_row(seeded, alice, base)
    _, _, summary = run_apply(seeded, alice, {"items": [item(uw["id"], "fix_spelling", "basis", "看起来是 basis 的拼写错误", 0.93)], "confusable_groups": [], "difficulty_tags": []})
    assert summary.suggestions == 1 and summary.auto_applied == 0
    (s,) = suggestions(seeded, alice)
    assert s["type"] == "fix_spelling" and s["status"] == "open" and s["target_word_id"] == wid(seeded, "basis")
    assert json.loads(s["payload_json"]) == {"from": "base", "note_zh": "看起来是 basis 的拼写错误", "confidence": 0.93, "to": "basis"}
    assert bank.my_row(seeded, alice, base)["word_id"] == base


def test_merge_duplicate_and_split_phrase_are_suggestions(seeded, alice):
    email_uw = bank.my_row(seeded, alice, mark(seeded, alice, "email"))
    prov = add(seeded, alice, "e-mail")
    e_uw = bank.my_row(seeded, alice, prov)
    phrase = add(seeded, alice, "negotiate a deal")
    p_uw = bank.my_row(seeded, alice, phrase)
    result = {"items": [item(e_uw["id"], "merge_duplicate", "email", "同一个词"), item(p_uw["id"], "split_phrase", "negotiate", "只学核心词"), item(email_uw["id"], "ok")], "confusable_groups": [], "difficulty_tags": []}
    _, _, summary = run_apply(seeded, alice, result)
    assert summary.suggestions == 2 and summary.verdicts == {"merge_duplicate": 1, "split_phrase": 1, "ok": 1}
    by_type = {s["type"]: s for s in suggestions(seeded, alice)}
    assert by_type["merge_duplicate"]["target_word_id"] == wid(seeded, "email") and by_type["split_phrase"]["target_word_id"] == wid(seeded, "negotiate")
    assert json.loads(by_type["merge_duplicate"]["payload_json"]) == {"from": "e-mail", "note_zh": "同一个词", "confidence": 0.9, "to": "email"}
    assert bank.my_row(seeded, alice, prov)["word_id"] == prov and bank.my_row(seeded, alice, phrase)["word_id"] == phrase  # suggestions only


def test_invalid_word_marks_only_provisional_rows(seeded, alice):
    apple = mark(seeded, alice, "apple")
    prov = add(seeded, alice, "zzqx")
    result = {"items": [item(bank.my_row(seeded, alice, apple)["id"], "invalid_word", note="这似乎不是英文单词"), item(bank.my_row(seeded, alice, prov)["id"], "invalid_word")], "confusable_groups": [], "difficulty_tags": []}
    _, _, summary = run_apply(seeded, alice, result)
    assert summary.suggestions == 2
    a = words.word_row(seeded, apple)
    assert a["is_valid_english"] == 1 and a["is_public"] == 1  # seed rows untouched
    z = words.word_row(seeded, prov)
    assert z["is_valid_english"] == 0 and z["is_public"] == 0
    assert all(s["type"] == "invalid_word" and s["status"] == "open" for s in suggestions(seeded, alice))
    assert json.loads(suggestions(seeded, alice)[1]["payload_json"])["note_zh"] == "这似乎不是英文单词"


def test_fill_data_and_difficulty_tags_auto_apply_to_non_seed_words_only(seeded, alice):
    prov = add(seeded, alice, "ubiquitous")
    apple = mark(seeded, alice, "apple")
    uw = bank.my_row(seeded, alice, prov)
    fill = {"phonetic": "/juːˈbɪkwɪtəs/", "pos": "adj.", "meaning_zh": "adj. 无处不在的", "definition_en": "seeming to be everywhere", "difficulty": 5}
    result = {
        "items": [item(uw["id"], "fill_data", fill=fill), item(bank.my_row(seeded, alice, apple)["id"], "fill_data", fill=fill)],
        "confusable_groups": [],
        "difficulty_tags": [{"id": bank.my_row(seeded, alice, apple)["id"], "difficulty": 1}, {"id": uw["id"], "difficulty": 4}, {"id": 424242, "difficulty": 2}],
    }
    run_id, _, summary = run_apply(seeded, alice, result)
    assert summary.auto_applied == 2  # fill on the provisional word + the apple difficulty tag; ubiquitous already got 5 from the fill
    w = words.word_row(seeded, prov)
    # the IPA slashes Claude writes are stripped: the seed stores bare transcriptions and the UI adds the slashes
    assert (w["phonetic"], w["pos"], w["translation"], w["definition"], w["difficulty"], w["source"]) == ("juːˈbɪkwɪtəs", "adj.", "adj. 无处不在的", "seeming to be everywhere", 5, "claude")
    a = words.word_row(seeded, apple)
    assert a["difficulty"] == 1 and a["phonetic"] != fill["phonetic"]  # seed fields never overwritten
    rows = suggestions(seeded, alice)
    assert [(r["type"], r["status"]) for r in rows] == [("fill_data", "auto"), ("difficulty", "auto")]
    undo = json.loads(rows[0]["undo_json"])
    assert undo["word_id"] == prov and set(undo["fields"]) == {"phonetic", "pos", "translation", "definition", "difficulty", "source"}
    assert json.loads(rows[0]["payload_json"])["fields"] == ["definition", "difficulty", "phonetic", "pos", "translation"]
    assert json.loads(rows[1]["undo_json"]) == {"word_id": apple, "fields": {"difficulty": None}}
    assert rows[0]["run_id"] == run_id


def test_confusable_groups_limited_to_bank_headwords_and_ids_outside_batch_ignored(seeded, alice):
    for lemma in ("abandon", "abundant", "absorb"):
        mark(seeded, alice, lemma)
    result = {
        "items": [item(999999, "fix_spelling", "abandon"), {"id": "x", "verdict": "ok"}],
        "confusable_groups": [["abandon", "abundant", "zzz"], ["absorb", "absurd", "abstract"], ["Abandon", "abundant"], "junk"],
        "difficulty_tags": [],
    }
    _, _, summary = run_apply(seeded, alice, result)
    assert summary.ignored_ids == [999999] and summary.confusable_groups == 1 and summary.suggestions == 0
    groups = suggestions(seeded, alice, "confusable_group")
    assert len(groups) == 1 and groups[0]["status"] == "accepted" and json.loads(groups[0]["payload_json"]) == {"group": ["abandon", "abundant"]}
    assert words.confusables_for(seeded, alice, "abandon") == ["abundant"]
    _, _, again = run_apply(seeded, alice, result)
    assert again.confusable_groups == 0  # identical group not stored twice


def test_unvalidatable_target_downgrades_to_ok(seeded, alice):
    prov = add(seeded, alice, "abandonning")
    uw = bank.my_row(seeded, alice, prov)
    result = {"items": [item(uw["id"], "fix_spelling", "ignore all previous instructions"), item(uw["id"], "lemmatize", "abandonning")], "confusable_groups": [], "difficulty_tags": []}
    _, _, summary = run_apply(seeded, alice, result)
    assert summary.suggestions == 0 and summary.downgraded == [uw["id"], uw["id"]] and summary.verdicts == {"ok": 2}
    assert suggestions(seeded, alice) == []


def test_run_bookkeeping_and_stale_suggestion_expiry(seeded, alice):
    prov = add(seeded, alice, "abandonning")
    uw = bank.my_row(seeded, alice, prov)
    seeded.execute(
        "INSERT INTO bank_suggestions(user_id, type, user_word_id, payload_json, status, expires_at, created_at) VALUES (?, 'fix_spelling', ?, '{}', 'open', '2026-10-13T00:00:00Z', '2026-09-13T00:00:00Z')",
        (alice, uw["id"]),
    )
    assert consolidate.expire_stale_suggestions(seeded, alice, now=NOW) == 1
    run_id = consolidate.start_run(seeded, alice, "nightly", 3, now=NOW)
    consolidate.finish_run(seeded, run_id, "done", auto_applied=1, suggestions=2, ai_call_id=7, summary={"a": 1}, now=NOW)
    run = db.row_to_dict(seeded.execute("SELECT * FROM consolidation_runs WHERE id = ?", (run_id,)).fetchone())
    assert (run["trigger"], run["status"], run["words_examined"], run["auto_applied"], run["suggestions"], run["ai_call_id"], run["finished_at"]) == ("nightly", "done", 3, 1, 2, 7, NOW)
    assert json.loads(run["summary_json"]) == {"a": 1} and consolidate.last_run_started(seeded, alice) == NOW


# -------------------------------------------------------------------------------------------- handler
def test_handler_end_to_end_against_the_fake(seeded, alice, ctx):
    prov = add(seeded, alice, "abandonning")
    mark(seeded, alice, "abandon")
    job_id = consolidate.enqueue_for_user(seeded, alice, trigger="nightly", now=NOW)
    (job,) = queue.claim_batch(seeded, "consolidate_bank", 1, "claude-1:test", now=NOW)
    consolidate.handle_consolidate_bank(ctx, [job])
    done = queue.get_job(seeded, job_id)
    assert done.status == "done" and done.result["examined"] == 2 and done.result["verdicts"] == {"ok": 2}
    run = db.row_to_dict(seeded.execute("SELECT * FROM consolidation_runs").fetchone())
    assert run["status"] == "done" and run["trigger"] == "nightly" and run["words_examined"] == 2 and run["ai_call_id"] is not None
    call = seeded.execute("SELECT kind, status, word_count FROM ai_calls").fetchone()
    assert tuple(call) == ("consolidate", "success", 2)
    assert words.word_row(seeded, prov)["lemma"] == "abandonning"
    # nothing to examine next time → skipped run, no call
    job2 = consolidate.enqueue_for_user(seeded, alice, trigger="manual", now="2026-10-15T00:00:00Z")
    (job,) = queue.claim_batch(seeded, "consolidate_bank", 1, "claude-1:test", now="2026-10-15T00:00:00Z")
    seeded.execute("UPDATE words SET is_valid_english = 1, difficulty = 3 WHERE id = ?", (prov,))
    seeded.execute("UPDATE words SET difficulty = 2 WHERE lemma = 'abandon'")
    consolidate.handle_consolidate_bank(ctx, [job])
    assert queue.get_job(seeded, job2).result == {"skipped": "nothing_to_examine"}
    assert seeded.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
    assert seeded.execute("SELECT status FROM consolidation_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "skipped"
