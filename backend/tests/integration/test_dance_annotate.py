"""generate_dance end to end (docs/WORD_DANCE_DESIGN.md §6.2; CLAUDE_INTEGRATION §6.8): the bank enqueue rides along with the content
job, the worker annotates 20 words per call through the fake claude, the stored spec wins over the rule spec in the DTOs, a bad
answer falls back to the rule chunks, a missing item fails its job, and `wd dance-annotate` enqueues a stage."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from wd import dance as rules
from wd import db
from wd.ai import dance as handler
from wd.jobs import queue, registry, worker
from wd.jobs.registry import JobContext
from wd.services import bank, screen, words

NOW = "2026-10-14T00:00:00Z"


def _word(conn, lemma: str) -> dict:
    row = conn.execute("SELECT * FROM words WHERE lemma = ?", (lemma,)).fetchone()
    assert row is not None, lemma
    return dict(row)


@pytest.fixture
def user(seeded) -> int:
    return int(seeded.execute("INSERT INTO users(username, password_hash, onboarding_state) VALUES ('alice', 'x', 'done')").lastrowid)


@pytest.fixture
def ctx(settings, seeded, connect, frozen_clock):
    registry.load_handlers()
    return JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, worker_id="claude-1", boot_id="test")


def _enqueue(conn, lemma: str, *, priority: int = 20, force: bool = False) -> int | None:
    with db.tx(conn):
        return rules.enqueue_if_needed(conn, int(_word(conn, lemma)["id"]), priority=priority, now=NOW, force=force)


def test_enqueue_if_needed_gates_and_dedupes(seeded):
    conn = seeded
    # a validated word with a rule spec: one job, dance_state queued, the same job on a second call
    jid = _enqueue(conn, "abandon")
    assert jid is not None and _word(conn, "abandon")["dance_state"] == "queued"
    assert _enqueue(conn, "abandon") is None  # already queued
    # no spec: phrases / abbreviations with a dot / no phonetic
    for lemma in ("ice cream", "a.m.", "axe"):
        assert _enqueue(conn, lemma) is None and _word(conn, lemma)["dance_state"] == "none"
    # the content enqueue helper enqueues the dance job alongside
    with db.tx(conn):
        bank.enqueue_content_if_needed(conn, _word(conn, "happy"), priority=10, now=NOW)
    hid = _word(conn, "happy")["id"]
    job = conn.execute("SELECT type, priority, dedupe_key FROM jobs WHERE dedupe_key = ?", (f"dance:{hid}",)).fetchone()
    assert tuple(job) == ("generate_dance", 11, f"dance:{hid}")  # one notch below the content job it rides along with
    content_job = conn.execute("SELECT id, priority FROM jobs WHERE dedupe_key = ?", (f"content:{hid}",)).fetchone()
    assert content_job["priority"] == 10 and content_job["id"] < job_id_of(conn, f"dance:{hid}")  # content first in the head-of-queue race
    assert _word(conn, "happy")["dance_state"] == "queued"


def job_id_of(conn, dedupe_key: str) -> int:
    return int(conn.execute("SELECT id FROM jobs WHERE dedupe_key = ?", (dedupe_key,)).fetchone()[0])


def test_enqueue_gates_budget_stale_spec_and_dead_jobs(ctx, seeded, settings):
    conn = seeded
    wid = int(_word(conn, "happy")["id"])
    # the sub-cap at 0 switches the annotations off: nothing is queued (no job churn on every bank action)
    off = replace(settings, ai_dance_daily_budget_usd=0.0)
    with db.tx(conn):
        assert rules.enqueue_if_needed(conn, wid, priority=20, now=NOW, cfg=off) is None
        bank.enqueue_content_if_needed(conn, _word(conn, "happy"), priority=20, now=NOW, cfg=off)
    assert conn.execute("SELECT COUNT(*) FROM jobs WHERE type = 'generate_dance'").fetchone()[0] == 0 and _word(conn, "happy")["dance_state"] == "none"
    with db.tx(conn):  # undo the content enqueue above (a pending content job would defer the dance job below)
        conn.execute("DELETE FROM jobs WHERE dedupe_key = ?", (f"content:{wid}",))
        conn.execute("UPDATE words SET content_state = 'none' WHERE id = ?", (wid,))
    # a 'queued' word whose job died on the worker's crash path (no live job) is re-queued; one with a live job is not
    with db.tx(conn):
        conn.execute("UPDATE words SET dance_state = 'queued' WHERE id = ?", (wid,))
    assert _enqueue(conn, "happy") is not None
    assert _enqueue(conn, "happy") is None
    # annotate, then rename the display form: the stale spec no longer spells it → re-queued (and the rule spec serves meanwhile)
    worker.drain(ctx, ("generate_dance",))
    assert _word(conn, "happy")["dance_state"] == "ready" and _enqueue(conn, "happy") is None
    with db.tx(conn):
        conn.execute("UPDATE words SET display = 'Happy' WHERE id = ?", (wid,))
    happy = _word(conn, "happy")
    assert rules.active_spec(conn, happy) is None and rules.spec_for_word(conn, happy)["source"] == "rule"
    assert _enqueue(conn, "happy") is not None and _word(conn, "happy")["dance_state"] == "queued"


def test_handler_skips_merged_or_invalid_words_and_waits_for_pending_content(ctx, seeded):
    conn = seeded
    ids = {lemma: int(_word(conn, lemma)["id"]) for lemma in ("abandon", "happy", "apple")}
    for lemma in ids:
        assert _enqueue(conn, lemma) is not None
    with db.tx(conn):
        conn.execute("UPDATE words SET is_valid_english = 0 WHERE id = ?", (ids["abandon"],))  # rejected after the enqueue
        conn.execute("UPDATE words SET merged_into_word_id = ? WHERE id = ?", (ids["apple"], ids["happy"]))  # merged after the enqueue
        conn.execute("UPDATE words SET content_state = 'queued', active_content_id = NULL WHERE id = ?", (ids["apple"],))  # content on its way …
        queue.enqueue(conn, "generate_content", {"word_id": ids["apple"]}, dedupe_key=f"content:{ids['apple']}", priority=20, now=NOW)  # … with a live job
    worker.drain(ctx, ("generate_dance",))
    results = {r["dedupe_key"]: (r["status"], json.loads(r["result_json"] or "null"), r["run_after"]) for r in conn.execute("SELECT dedupe_key, status, result_json, run_after FROM jobs WHERE type = 'generate_dance'")}
    assert results[f"dance:{ids['abandon']}"][:2] == ("done", {"skipped": "invalid_word"})
    assert results[f"dance:{ids['happy']}"][:2] == ("done", {"skipped": "merged"})
    assert results[f"dance:{ids['apple']}"][0] == "queued" and results[f"dance:{ids['apple']}"][2] > NOW  # deferred, no attempt consumed
    apple_job = conn.execute("SELECT attempts, payload_json FROM jobs WHERE dedupe_key = ?", (f"dance:{ids['apple']}",)).fetchone()
    assert apple_job["attempts"] == 0 and json.loads(apple_job["payload_json"])["content_waits"] == 1  # the wait is counted …
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0  # nothing was spent on any of them
    assert {r[0] for r in conn.execute("SELECT dance_state FROM words WHERE id IN (?, ?)", (ids["abandon"], ids["happy"]))} == {"none"}
    assert _word(conn, "apple")["dance_state"] == "queued"
    # … and bounded: at MAX_CONTENT_WAITS the dictionary sense is judged even though the content job is still live
    with db.tx(conn):
        conn.execute("UPDATE jobs SET run_after = ?, payload_json = ? WHERE dedupe_key = ?", (NOW, json.dumps({"word_id": ids["apple"], "content_waits": handler.MAX_CONTENT_WAITS}), f"dance:{ids['apple']}"))
    worker.drain(ctx, ("generate_dance",))
    assert _word(conn, "apple")["dance_state"] == "ready"
    # a word stuck at content_state='queued' WITHOUT a live content job (a crash-dead content job) is not waited for at all
    cid = int(_word(conn, "computer")["id"])
    with db.tx(conn):
        conn.execute("UPDATE words SET content_state = 'queued', active_content_id = NULL WHERE id = ?", (cid,))
    assert _enqueue(conn, "computer") is not None
    worker.drain(ctx, ("generate_dance",))
    assert _word(conn, "computer")["dance_state"] == "ready"


def test_mark_failed_keeps_an_active_spec_ready():
    import sqlite3

    from wd import db as _db

    c = _db.connect(":memory:")
    try:
        _db.run_migrations(c)
        with _db.tx(c):
            c.execute("INSERT INTO words(id, lemma, display, source, phonetic, dance_state) VALUES (1, 'up', 'up', 'seed', 'ʌp', 'queued')")
            c.execute("INSERT INTO words(id, lemma, display, source, phonetic, dance_state) VALUES (2, 'in', 'in', 'seed', 'in', 'queued')")
            c.execute("INSERT INTO word_dances(id, word_id, status, spec_json) VALUES (7, 1, 'active', '{}')")
            c.execute("UPDATE words SET active_dance_id = 7 WHERE id = 1")
        rules.mark_failed(c, 1, now=NOW)
        rules.mark_failed(c, 2, now=NOW)
        assert [r[0] for r in c.execute("SELECT dance_state FROM words ORDER BY id")] == ["ready", "failed"]  # a dead forced re-annotation keeps its spec
        rules.mark_unattempted(c, 1, now=NOW)
        rules.mark_unattempted(c, 2, now=NOW)
        assert [r[0] for r in c.execute("SELECT dance_state FROM words ORDER BY id")] == ["ready", "none"]
    except sqlite3.Error:
        raise
    finally:
        c.close()


def test_worker_annotates_a_batch_and_the_stored_spec_wins(ctx, seeded, settings, user):
    conn = seeded
    for lemma in ("abandon", "happy", "apple", "computer", "water"):
        assert _enqueue(conn, lemma) is not None
    assert queue.limit_for("generate_dance", settings) == 20
    assert worker.drain(ctx, ("generate_dance",)) >= 1  # one claim of 5 jobs → one fake claude call
    rows = {r["lemma"]: dict(r) for r in conn.execute("SELECT lemma, dance_state, active_dance_id FROM words WHERE lemma IN ('abandon','happy','apple','computer','water')")}
    assert all(r["dance_state"] == "ready" and r["active_dance_id"] for r in rows.values()), rows
    call = conn.execute("SELECT kind, status, word_count, provider FROM ai_calls ORDER BY id DESC LIMIT 1").fetchone()
    assert tuple(call) == ("dance", "success", 5, "claude")
    # the stored spec: happy → wave (fake table), apple → none; chunks are the rule chunks, marks the rules', source claude
    happy = _word(conn, "happy")
    spec = rules.active_spec(conn, happy)
    assert spec is not None and spec["source"] == "claude" and spec["semantic"] == {"primitive": "wave", "params": {}}
    assert spec["letters"] == ["hap", "py"] and spec["stress"] == 0 and spec["marks"] == {"double": [[2, 3]], "silent": []}
    assert rules.active_spec(conn, _word(conn, "apple"))["semantic"] is None
    stored = conn.execute("SELECT status, model, prompt_version, reason FROM word_dances WHERE word_id = ?", (happy["id"],)).fetchone()
    assert tuple(stored)[:3] == ("active", "claude-sonnet-fake", handler.DANCE_PROMPT_VERSION) and stored["reason"]  # the fake's reason is kept for the review
    # the DTOs serve the stored spec (source claude) and fall back to the rules for a word without one
    detail = words.word_detail(conn, int(happy["id"]), user)
    assert detail["word"]["dance"] == spec
    assert words.word_detail(conn, int(_word(conn, "cat")["id"]), user)["word"]["dance"]["source"] == "rule"
    # a second annotation supersedes the first (force) and keeps exactly one active row
    assert _enqueue(conn, "happy") is None and _enqueue(conn, "happy", force=True) is not None
    worker.drain(ctx, ("generate_dance",))
    statuses = [r[0] for r in conn.execute("SELECT status FROM word_dances WHERE word_id = ? ORDER BY id", (happy["id"],))]
    assert statuses == ["superseded", "active"]
    # the study item carries the same spec (screen.study_item_dict goes through the same spec_for_word)
    batch = conn.execute("INSERT INTO push_batches(user_id, local_date, timezone, status, trigger) VALUES (?, '2026-10-14', 'Asia/Shanghai', 'published', 'manual')", (user,)).lastrowid
    item_id = conn.execute("INSERT INTO push_items(batch_id, word_id, kind, position) VALUES (?, ?, 'new', 0)", (batch, happy["id"])).lastrowid
    assert screen.study_item_dict(conn, user, int(item_id), now=NOW)["word"]["dance"]["source"] == "claude"


def test_build_spec_falls_back_to_the_rules_for_bad_chunks_and_rejects_nothing_valid():
    rule = rules.spec_for("happy", "'hæpi")
    good, corrected = handler.build_spec("happy", {"word": "happy", "letters": ["hap", "py"], "stress": 0, "primitive": "wave", "n": 0, "color": "", "reason": "x"}, rule)
    assert good["letters"] == ["hap", "py"] and good["semantic"] == {"primitive": "wave", "params": {}} and good["source"] == "claude" and corrected is False
    # chunks that do not spell the word → rule chunks AND rule stress (never Claude's index on the rule chunking); still stored
    bad, corrected = handler.build_spec("happy", {"word": "happy", "letters": ["ha", "ppy", "!"], "stress": 7, "primitive": "none", "n": 0, "color": "", "reason": "x"}, rule)
    assert bad["letters"] == ["hap", "py"] and bad["stress"] == 0 and bad["semantic"] is None and corrected is False
    bad2, corrected = handler.build_spec("happy", {"word": "happy", "letters": ["ha", "ppy", "!"], "stress": 1, "primitive": "none", "n": 0, "color": "", "reason": "x"}, rule)
    assert bad2["letters"] == ["hap", "py"] and bad2["stress"] == 0 and corrected is False  # the in-range 1 belonged to Claude's chunking
    # Claude's own chunking with an unusable stress (a 1-based index) → the rule chunks AND the rule stress, never a mix of the layers
    rule3 = rules.spec_for("abandon", "ə'bændən")
    mixed, corrected = handler.build_spec("abandon", {"word": "abandon", "letters": ["aban", "don"], "stress": 2, "primitive": "none", "n": 0, "color": "", "reason": "x"}, rule3)
    assert mixed["letters"] == ["a", "ban", "don"] and mixed["stress"] == 1 and corrected is False
    # a corrected split is kept when it spells the word
    fixed, corrected = handler.build_spec("happy", {"word": "happy", "letters": ["happ", "y"], "stress": 0, "primitive": "none", "n": 0, "color": "", "reason": "x"}, rule)
    assert fixed["letters"] == ["happ", "y"] and corrected is True
    # params: multiply without a usable n defaults to 3, color without a colour is no semantic at all
    three, _ = handler.build_spec("three", {"word": "three", "letters": ["three"], "stress": 0, "primitive": "multiply", "n": 0, "color": "", "reason": "x"}, rules.spec_for("three", "θriː"))
    assert three["semantic"] == {"primitive": "multiply", "params": {"n": 3}}
    red, _ = handler.build_spec("red", {"word": "red", "letters": ["red"], "stress": 0, "primitive": "color", "n": 0, "color": "", "reason": "x"}, rules.spec_for("red", "red"))
    assert red["semantic"] is None
    red2, _ = handler.build_spec("red", {"word": "red", "letters": ["red"], "stress": 0, "primitive": "color", "n": 0, "color": "red", "reason": "x"}, rules.spec_for("red", "red"))
    assert red2["semantic"] == {"primitive": "color", "params": {"color": "red"}}
    # the P3 primitives (library gaps of the 小学 review: jump, on) take no params; a stray n / color is dropped
    hop, _ = handler.build_spec("jump", {"word": "jump", "letters": ["jump"], "stress": 0, "primitive": "hop", "n": 2, "color": "red", "reason": "x"}, rules.spec_for("jump", "dʒʌmp"))
    assert hop["semantic"] == {"primitive": "hop", "params": {}}
    onto, _ = handler.build_spec("on", {"word": "on", "letters": ["on"], "stress": 0, "primitive": "onto", "n": 0, "color": "", "reason": "x"}, rules.spec_for("on", "ɔn"))
    assert onto["semantic"] == {"primitive": "onto", "params": {}} and onto["source"] == "claude"


def test_first_sense_and_prompt_entry(seeded):
    conn = seeded
    word = _word(conn, "abandon")
    assert handler.first_sense(word, {"meaning_zh": "v. 放弃；抛弃；n. 放纵"}) == "v. 放弃"
    assert handler.first_sense(word, None).startswith("vt. 放弃")  # the dictionary's first line
    # without content the dictionary line of the dominant part of speech wins over ECDICT's noun-first ordering
    fly = {"translation": "n. 苍蝇, 两翼昆虫, 飞行\nvi. 飞, 飞翔, 飘扬, 逃走\nvt. 飞, 飞越", "pos": "n:18/j:2/v:80"}
    assert handler.dominant_pos(fly["pos"]) == "v" and handler.dictionary_sense(fly) == "vi. 飞, 飞翔, 飘扬, 逃走" and handler.first_sense(fly, None) == "vi. 飞, 飞翔, 飘扬, 逃走"
    cold = {"translation": "n. 感冒, 寒冷\na. 寒冷的, 冷淡的, 冷静的\nadv. 完全地", "pos": "r:1/j:83/n:16"}
    assert handler.first_sense(cold, None) == "a. 寒冷的, 冷淡的, 冷静的"
    assert handler.first_sense({"translation": "n. 风筝", "pos": "n:100"}, None) == "n. 风筝"
    assert handler.first_sense({"translation": "n. 火\nvt. 点燃", "pos": ""}, None) == "n. 火" and handler.dominant_pos("") is None
    assert handler.first_sense({"translation": "", "pos": "v:100"}, None) == ""
    # the card's first sense ends at the next part-of-speech group as well as at ；
    assert handler.first_sense({}, {"meaning_zh": "n. 灯 adj. 轻的"}) == "n. 灯"
    assert handler.first_sense({}, {"meaning_zh": "v. 飞 n. 苍蝇"}) == "v. 飞"
    assert handler.first_sense({}, {"meaning_zh": "adj. 抽象的 n. 摘要;抽象画 v. 提取;摘要"}) == "adj. 抽象的"
    assert handler.first_sense({}, {"meaning_zh": "n. 苹果"}) == "n. 苹果"
    # month homographs: ECDICT's pos counts the lowercase corpus token, so the override keeps the month
    assert handler.first_sense({"lemma": "august", "translation": "n. 八月\na. 威严的, 令人敬畏的", "pos": "j:100"}, None) == "n. 八月"
    assert handler.first_sense({"lemma": "march", "translation": "n. 三月, 进行\nvi. 进军, 前进", "pos": "n:37/v:63"}, None) == "n. 三月"
    entry = handler.prompt_entry(conn, word, rules.spec_for("abandon", word["phonetic"]))
    assert entry["word"] == "abandon" and entry["rule_letters"] == ["a", "ban", "don"] and entry["rule_stress"] == 1 and entry["phonetic"] == word["phonetic"]
    prompt = handler.build_user_prompt([entry])
    assert "<items>" in prompt and json.loads(prompt.split("<items>")[1].split("</items>")[0])["words"][0]["word"] == "abandon"


def test_budget_disabled_skips_and_resets_the_state(ctx, seeded, settings):
    conn = seeded
    assert _enqueue(conn, "abandon") is not None  # queued while the cap was on …
    off = replace(ctx, cfg=replace(settings, ai_dance_daily_budget_usd=0.0))  # … then the operator switched it off
    worker.drain(off, ("generate_dance",))
    job = conn.execute("SELECT status, result_json FROM jobs WHERE dedupe_key = ?", (f"dance:{_word(conn, 'abandon')['id']}",)).fetchone()
    assert job["status"] == "done" and json.loads(job["result_json"]) == {"skipped": "dance_budget_disabled"}
    assert _word(conn, "abandon")["dance_state"] == "none"  # nothing attempted, nothing failed: annotated when the cap comes back
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0


def test_cli_dance_annotate_enqueues_a_stage(seeded, settings, monkeypatch, capsys):
    from wd import cli

    monkeypatch.setenv("WD_DATA_DIR", str(settings.data_dir))
    assert cli.main(["dance-annotate", "--stage", "cet4", "--limit", "3", "--priority", "40"]) == 0
    out = capsys.readouterr().out
    assert "dance-annotate:" in out and "enqueued" in out
    jobs = [tuple(r) for r in seeded.execute("SELECT type, priority FROM jobs WHERE type = 'generate_dance'")]
    assert jobs and all(j == ("generate_dance", 40) for j in jobs) and len(jobs) <= 3
    assert cli.main(["dance-annotate", "--word", "nosuchword"]) == 1
    monkeypatch.setenv("WD_AI_DANCE_DAILY_BUDGET_USD", "0")
    assert cli.main(["dance-annotate", "--word", "abandon"]) == 1 and "switched off" in capsys.readouterr().out
    monkeypatch.delenv("WD_AI_DANCE_DAILY_BUDGET_USD")
    assert cli.main(["dance-annotate", "--word", "abandon", "--dry-run"]) == 0 and "would consider abandon" in capsys.readouterr().out


def test_already_annotated_job_without_force_is_skipped(ctx, seeded):
    conn = seeded
    assert _enqueue(conn, "happy") is not None
    worker.drain(ctx, ("generate_dance",))
    happy = _word(conn, "happy")
    assert happy["dance_state"] == "ready" and rules.active_spec(conn, happy) is not None
    # enqueue_if_needed refuses a word with an active spec; a stale non-force job that reaches the worker anyway (enqueued directly)
    # finishes as skipped, restores the state and costs no call; the spec is untouched
    assert _enqueue(conn, "happy") is None
    with db.tx(conn):
        queue.enqueue(conn, rules.DANCE_JOB, {"word_id": int(happy["id"])}, dedupe_key=f"dance:{happy['id']}", priority=50, now=NOW)
        conn.execute("UPDATE words SET dance_state = 'queued' WHERE id = ?", (happy["id"],))
    worker.drain(ctx, ("generate_dance",))
    job = conn.execute("SELECT status, result_json FROM jobs WHERE dedupe_key = ? ORDER BY id DESC LIMIT 1", (f"dance:{happy['id']}",)).fetchone()
    assert job["status"] == "done" and json.loads(job["result_json"]) == {"skipped": "already"}
    assert _word(conn, "happy")["dance_state"] == "ready"
    assert conn.execute("SELECT COUNT(*) FROM word_dances WHERE word_id = ?", (happy["id"],)).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
