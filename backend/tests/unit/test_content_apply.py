"""ai/content.py application rules (CLAUDE_INTEGRATION §6.4) on the mini seed: unmatched words, example filtering,
retry on too few examples, the seed anomaly, valid=false on a custom word, versioning, the single image job, skipping
unvalidated words without a call, the model fallback and the prewarm plan accounting."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest

from wd import db
from wd.ai import common, content, runner
from wd.interfaces import ClaudeResult, Job
from wd.jobs import queue, registry
from wd.jobs.registry import JobContext
from wd.services import bank, words

NOW = "2026-10-14T00:00:00Z"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ITEMS = {it["word"]: it for it in json.loads((FIXTURES / "claude_content_ok.json").read_text(encoding="utf-8"))["structured_output"]["items"]}


@pytest.fixture
def ctx(settings, connect, frozen_clock):
    return JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("t"), worker_id="claude-1", boot_id="test")


@pytest.fixture
def alice(seeded):
    cur = seeded.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES ('alice', 'x', 'done')")
    uid = int(cur.lastrowid)
    seeded.execute("INSERT INTO user_settings(user_id) VALUES (?)", (uid,))
    return uid


def wid(conn, lemma):
    return int(conn.execute("SELECT id FROM words WHERE lemma = ?", (lemma,)).fetchone()[0])


def word(conn, word_id):
    return words.word_row(conn, word_id)


def make_job(conn, word_id, *, priority=20, extra=None, max_attempts=3, claim=True) -> Job:
    queue.enqueue(conn, "generate_content", {"word_id": word_id, **(extra or {})}, dedupe_key=f"content:{word_id}", priority=priority, max_attempts=max_attempts, now=NOW)
    if claim:
        (job,) = queue.claim_batch(conn, "generate_content", 1, "claude-1:test", now=NOW)
        return job
    return queue.live_job(conn, f"content:{word_id}")


def apply(ctx, conn, job, w, item, **over):
    return content.apply_item(ctx, conn, job, w, item, model=over.pop("model", "claude-sonnet-fake"), cost_share=over.pop("cost_share", 0.004), call_id=over.pop("call_id", None), now=NOW)


# ------------------------------------------------------------------------------------------ apply_item
def test_word_mismatch_is_unmatched(ctx, seeded):
    w = word(seeded, wid(seeded, "abandon"))
    job = make_job(seeded, w["id"])
    assert apply(ctx, seeded, job, w, ITEMS["ability"]).status == "unmatched"
    assert apply(ctx, seeded, job, w, None).status == "unmatched"
    assert seeded.execute("SELECT COUNT(*) FROM word_contents").fetchone()[0] == 0


def test_example_without_the_headword_is_dropped_and_the_rest_stored(ctx, seeded):
    w = word(seeded, wid(seeded, "abandon"))
    item = json.loads(json.dumps(ITEMS["abandon"]))
    item["examples"].append({"en": "The cat sat quietly on the warm mat all afternoon long.", "zh": "猫整个下午安静地坐在温暖的垫子上。"})
    job = make_job(seeded, w["id"])
    applied = apply(ctx, seeded, job, w, item)
    assert applied.status == "stored" and applied.version == 1
    stored = json.loads(seeded.execute("SELECT content_json FROM word_contents WHERE id = ?", (applied.content_id,)).fetchone()[0])
    assert len(stored["examples"]) == 3 and all("abandon" in ex["en"].lower() for ex in stored["examples"])
    assert set(stored) == {"word", "valid", "meaning_zh", "meaning_en", "examples", "collocations", "mnemonic_zh", "image_keywords", "image_alt_zh", "difficulty", "version", "prompt_version", "model", "created_at"}
    assert stored["prompt_version"] == "content-v1" and stored["model"] == "claude-sonnet-fake" and stored["created_at"] == NOW
    row = word(seeded, w["id"])
    assert row["content_state"] == "ready" and row["active_content_id"] == applied.content_id and row["difficulty"] == 2  # NULL → filled from the item


def test_fewer_than_three_examples_means_retry_except_on_the_last_attempt(ctx, seeded):
    w = word(seeded, wid(seeded, "ability"))
    item = json.loads(json.dumps(ITEMS["ability"]))
    item["examples"] = item["examples"][:2]
    job = make_job(seeded, w["id"])
    applied = apply(ctx, seeded, job, w, item)
    assert applied.status == "retry" and "need 3" in applied.detail
    last = replace(job, attempts=3)
    assert apply(ctx, seeded, last, w, item).status == "stored"  # ≥ 2 on the last attempt
    assert len(json.loads(seeded.execute("SELECT content_json FROM word_contents").fetchone()[0])["examples"]) == 2


def test_valid_false_on_a_seed_word_is_an_anomaly_then_failed(ctx, seeded):
    w = word(seeded, wid(seeded, "apple"))
    job = make_job(seeded, w["id"])
    item = {**ITEMS["abandon"], "word": "apple", "valid": False, "meaning_zh": "这不是单词"}
    assert apply(ctx, seeded, job, w, item).status == "anomaly"
    content.handle_anomaly(ctx, seeded, job, w, now=NOW)
    j = queue.get_job(seeded, job.id)
    assert j.status == "queued" and j.payload["group_size"] == 1 and j.payload["anomaly"] == 1 and j.attempts == 1
    assert seeded.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'content_anomaly'").fetchone()[0] == 1
    assert word(seeded, w["id"])["content_state"] == "none"  # nothing stored, not failed yet
    (job2,) = queue.claim_batch(seeded, "generate_content", 10, "claude-1:test", now="2026-10-14T00:03:00Z")
    content.handle_anomaly(ctx, seeded, job2, w, now=NOW)
    assert queue.get_job(seeded, job.id).status == "done" and word(seeded, w["id"])["content_state"] == "failed"
    assert seeded.execute("SELECT COUNT(*) FROM system_events WHERE kind = 'content_anomaly'").fetchone()[0] == 2


def test_valid_false_on_a_public_custom_word_rejects_and_hides_it(ctx, seeded, alice):
    bob = int(seeded.execute("INSERT INTO users(username, password_hash) VALUES ('bob', 'x')").lastrowid)
    carol = int(seeded.execute("INSERT INTO users(username, password_hash) VALUES ('carol', 'x')").lastrowid)
    bank.add_custom_words(seeded, alice, "zzqx", None, False, NOW, "Asia/Shanghai")
    bank.add_custom_words(seeded, bob, "zzqx", None, False, NOW, "Asia/Shanghai")
    w_id = wid(seeded, "zzqx")
    seeded.execute("UPDATE words SET is_valid_english = 1, is_public = 1, source = 'claude' WHERE id = ?", (w_id,))  # as if lookup had validated it
    uw_alice = bank.my_row(seeded, alice, w_id)
    seeded.execute(
        "INSERT INTO bank_suggestions(user_id, type, user_word_id, target_word_id, payload_json, status) VALUES (?, 'fix_spelling', ?, ?, '{}', 'open')",
        (alice, uw_alice["id"], w_id),
    )
    assert words.is_visible(seeded, w_id, carol)
    w = word(seeded, w_id)
    job = make_job(seeded, w_id)
    applied = apply(ctx, seeded, job, w, {**ITEMS["abandon"], "word": "zzqx", "valid": False, "meaning_zh": "这不是一个英文单词"})
    assert applied.status == "rejected"
    row = word(seeded, w_id)
    assert (row["is_valid_english"], row["is_public"], row["content_state"]) == (0, 0, "failed")
    assert seeded.execute("SELECT status FROM bank_suggestions WHERE target_word_id = ?", (w_id,)).fetchone()[0] == "expired"
    for uid in (alice, bob):
        r = bank.my_row(seeded, uid, w_id)
        assert r["needs_attention"] == 1 and r["attention_msg"] == "这不是一个英文单词"
        assert words.is_visible(seeded, w_id, uid)  # holders keep seeing it
    assert not words.is_visible(seeded, w_id, carol)  # a third user no longer does
    assert seeded.execute("SELECT COUNT(*) FROM word_contents").fetchone()[0] == 0


def test_versions_increment_and_supersede(ctx, seeded):
    w = word(seeded, wid(seeded, "abandon"))
    job = make_job(seeded, w["id"])
    first = apply(ctx, seeded, job, w, ITEMS["abandon"])
    queue.finish(seeded, job.id, now=NOW)
    forced = make_job(seeded, w["id"], extra={"force": True})
    second = apply(ctx, seeded, forced, word(seeded, w["id"]), {**ITEMS["abandon"], "difficulty": 4})
    assert (first.version, second.version) == (1, 2)
    rows = {r[0]: r[1] for r in seeded.execute("SELECT version, status FROM word_contents WHERE word_id = ?", (w["id"],))}
    assert rows == {1: "superseded", 2: "active"}
    row = word(seeded, w["id"])
    assert row["active_content_id"] == second.content_id and row["difficulty"] == 4  # force refreshes the difficulty
    assert words.active_content(seeded, row)["version"] == 2


def test_image_job_enqueued_once_with_the_inherited_priority(ctx, seeded):
    w = word(seeded, wid(seeded, "abandon"))
    job = make_job(seeded, w["id"], priority=10)
    apply(ctx, seeded, job, w, ITEMS["abandon"])
    live = queue.live_job(seeded, f"image:{w['id']}")
    assert live is not None and live.payload == {"word_id": w["id"]} and live.priority == 10
    assert word(seeded, w["id"])["image_state"] == "queued"
    queue.finish(seeded, job.id, now=NOW)
    forced = make_job(seeded, w["id"], extra={"force": True}, priority=20)
    apply(ctx, seeded, forced, word(seeded, w["id"]), ITEMS["abandon"])
    assert seeded.execute("SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image'").fetchone()[0] == 1  # UPSERT on the live key
    # a word with a ready image gets no image job; images disabled → none either
    seeded.execute("UPDATE words SET image_state = 'ready' WHERE id = ?", (w["id"],))
    assert content.enqueue_image(ctx, seeded, word(seeded, w["id"]), priority=20, now=NOW) is None
    off = replace(ctx, cfg=replace(ctx.cfg, images_enabled=False))
    seeded.execute("UPDATE words SET image_state = 'none' WHERE id = ?", (w["id"],))
    assert content.enqueue_image(off, seeded, word(seeded, w["id"]), priority=20, now=NOW) is None


def test_plan_id_credits_the_prewarm_spend(ctx, seeded):
    w = word(seeded, wid(seeded, "abandon"))
    job = make_job(seeded, w["id"], priority=90, extra={"plan_id": "plan-1"})
    apply(ctx, seeded, job, w, ITEMS["abandon"], cost_share=0.004)
    assert float(db.kv_get(seeded, "prewarm:plan-1:spent")) == pytest.approx(0.004)
    assert content.credit_plan(seeded, "plan-1", 0.006, now=NOW) == pytest.approx(0.01)
    assert seeded.execute("SELECT cost_usd FROM word_contents").fetchone()[0] == pytest.approx(0.004)


def test_validate_item_sanitises_and_rejects():
    w = {"id": 1, "lemma": "abandon", "display": "abandon"}
    base = json.loads(json.dumps(ITEMS["abandon"]))
    base["meaning_en"] = "to leave <b>completely</b>\x07"
    base["collocations"] = ["abandon ship", "x" * 61, "abandon ship", "a", "b", "c"]
    base["image_keywords"] = ["Abandoned House", "map of nowhere", "abandoned house", "bad$keyword", "street"]
    base["mnemonic_zh"] = "联" * 150
    cleaned, reason = content.validate_item(base, w, ["abandoned", "abandoning"], last_attempt=False)
    assert reason == "" and cleaned["meaning_en"] == "to leave completely"
    assert cleaned["collocations"] == ["abandon ship", "a", "b", "c"]
    assert cleaned["image_keywords"] == ["abandoned house", "street"] and len(cleaned["mnemonic_zh"]) == 100
    blocked = {**base, "image_keywords": ["nude scene", "weapon"]}
    assert content.validate_item(blocked, w, [], last_attempt=False)[0]["image_keywords"] == ["abandon"]
    assert content.validate_item({**base, "meaning_zh": "see https://evil.example"}, w, [], last_attempt=False) == (None, "invalid: meaning_zh")
    assert content.validate_item({**base, "meaning_zh": "no cjk here"}, w, [], last_attempt=False)[1] == "invalid: meaning_zh"
    assert content.validate_item({**base, "difficulty": 9}, w, [], last_attempt=False)[1] == "invalid: difficulty"
    assert content.validate_item({**base, "word": "Abandon"}, w, [], last_attempt=False)[1] == ""  # case-insensitive match
    assert content.validate_item({**base, "word": "abandoned"}, w, [], last_attempt=False)[1] == "unmatched"
    assert content.contains_headword("She abandoned the car.", "abandon", "abandon", []) and not content.contains_headword("A plain sentence.", "abandon", "abandon", [])
    assert content.contains_headword("The children went home.", "go", "go", ["went"]) and not content.contains_headword("Gone with the wind.", "go", "go", [])


def test_prompt_shape_carries_dictionary_data_only(seeded):
    w = word(seeded, wid(seeded, "GDP")) if seeded.execute("SELECT 1 FROM words WHERE lemma = 'gdp'").fetchone() else None
    entry = content.prompt_entry(word(seeded, wid(seeded, "go")))
    assert entry == {"word": "go", "dictionary_hint": content.dictionary_hint(word(seeded, wid(seeded, "go"))["translation"]), "pos_hint": "v:100", "stages": ["初中", "高中", "四级"]}
    assert len(entry["dictionary_hint"]) <= 60 and "\n" not in entry["dictionary_hint"]
    abbr = content.prompt_entry({"display": "TV", "translation": "n. 电视", "pos": None, "kind": "abbreviation", "stage_zk": 1, "stage_gk": 0, "stage_cet4": 0, "stage_cet6": 0})
    assert abbr["kind"] == "abbreviation" and abbr["pos_hint"] == ""
    prompt = content.build_user_prompt([entry, abbr])
    assert prompt.startswith("Generate study content for the following English words.") and prompt.endswith("Return one item per word, in this order.")
    data = json.loads(prompt.split("<items>\n", 1)[1].split("\n</items>", 1)[0])
    assert data["audience"].startswith("Chinese learners") and [x["word"] for x in data["words"]] == ["go", "TV"]
    assert "note" not in json.dumps(data) and w is None


# ------------------------------------------------------------------------------------------- handler
def test_unvalidated_word_job_is_skipped_without_a_call(ctx, seeded, alice):
    bank.add_custom_words(seeded, alice, "zzqx", None, False, NOW, "Asia/Shanghai")
    prov = wid(seeded, "zzqx")
    seeded.execute("DELETE FROM jobs")  # drop the lookup job; enqueue a content job by hand (no enqueue site would)
    job = make_job(seeded, prov)
    rejected = int(seeded.execute("INSERT INTO words(lemma, display, source, is_public, is_valid_english) VALUES ('zzbad', 'zzbad', 'user', 0, 0) RETURNING id").fetchone()[0])
    job2 = make_job(seeded, rejected)
    registry.load_handlers()
    content.handle_generate_content(ctx, [job, job2])
    assert queue.get_job(seeded, job.id).result == {"skipped": "unvalidated"} and queue.get_job(seeded, job.id).status == "done"
    assert queue.get_job(seeded, job2.id).result == {"skipped": "invalid_word"}
    assert seeded.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0


def test_model_column_falls_back_to_model_requested_when_model_usage_is_absent(ctx, seeded, monkeypatch):
    w = word(seeded, wid(seeded, "abandon"))
    job = make_job(seeded, w["id"])

    def fake_call(c, conn, **kw):
        call_id = c and 1
        return ClaudeResult(ok=True, status="success", structured={"items": [ITEMS["abandon"]]}, cost_usd=0.004, call_id=call_id, model_used=None, error=None)

    monkeypatch.setattr(common, "claude_call", fake_call)
    content.handle_generate_content(ctx, [job])
    assert queue.get_job(seeded, job.id).status == "done"
    assert seeded.execute("SELECT model, ai_call_id FROM word_contents").fetchone()[0] == ctx.cfg.ai_model == "sonnet"


def test_handler_skips_ready_words_and_applies_partial_results(ctx, seeded, monkeypatch):
    abandon = word(seeded, wid(seeded, "abandon"))
    ready = make_job(seeded, abandon["id"])
    apply(ctx, seeded, ready, abandon, ITEMS["abandon"])
    queue.finish(seeded, ready.id, now=NOW)
    again = make_job(seeded, abandon["id"], claim=False)
    ability = make_job(seeded, wid(seeded, "ability"), claim=False)
    absence = make_job(seeded, wid(seeded, "absence"), claim=False)
    jobs = queue.claim_batch(seeded, "generate_content", 10, "claude-1:test", now=NOW)
    assert {j.id for j in jobs} == {again.id, ability.id, absence.id}

    def fake_call(c, conn, **kw):
        assert [e["word"] for e in json.loads(kw["user_prompt"].split("<items>\n", 1)[1].split("\n</items>", 1)[0])["words"]] == ["ability", "absence"]
        return ClaudeResult(ok=True, status="success", structured={"items": [ITEMS["ability"]]}, cost_usd=0.008, call_id=1, model_used="m", error=None)

    monkeypatch.setattr(common, "claude_call", fake_call)
    content.handle_generate_content(ctx, jobs)
    assert queue.get_job(seeded, again.id).result == {"skipped": "already_ready"}
    assert queue.get_job(seeded, ability.id).status == "done" and word(seeded, wid(seeded, "ability"))["content_state"] == "ready"
    missing = queue.get_job(seeded, absence.id)
    assert missing.status == "queued" and missing.attempts == 1 and "partial" in missing.last_error  # retried alone later, the others unaffected


def test_every_item_failing_is_invalid_output_with_backoff(ctx, seeded, monkeypatch):
    ids = [wid(seeded, l) for l in ("abandon", "ability")]
    for i in ids:
        make_job(seeded, i, claim=False)
    jobs = queue.claim_batch(seeded, "generate_content", 10, "claude-1:test", now=NOW)
    call_ids: list[int] = []

    def fake_call(c, conn, **kw):
        from wd.ai import ledger

        cid = ledger.insert_call(conn, kind="content", model_requested="sonnet", flag_tier=0, word_count=2, job_ids=[j.id for j in jobs], max_budget_usd=0.25, reserved_usd=0.014, now=NOW)
        ledger.finish_call(conn, cid, status="success", cost_usd=0.008, now=NOW)
        call_ids.append(cid)
        bad = {k: v for k, v in ITEMS["abandon"].items() if k != "meaning_zh"}  # schema_mismatch: a required key missing
        return ClaudeResult(ok=True, status="success", structured={"items": [bad, {**ITEMS["ability"], "difficulty": 0}]}, cost_usd=0.008, call_id=cid, model_used="m", error=None)

    monkeypatch.setattr(common, "claude_call", fake_call)
    content.handle_generate_content(ctx, jobs)
    assert seeded.execute("SELECT status FROM ai_calls WHERE id = ?", (call_ids[0],)).fetchone()[0] == "invalid_output"
    for j in jobs:
        row = queue.get_job(seeded, j.id)
        assert row.status == "queued" and row.attempts == 1 and row.run_after == "2026-10-14T00:02:00Z" and "invalid_output" in row.last_error
