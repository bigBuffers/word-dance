"""jobs/queue.py: UPSERT dedupe, head-of-queue across types, group claims, backoff/dead, defer, bisection, stale sweep, cancel, run_once."""

from __future__ import annotations

import json
import logging
import threading

import pytest

from wd import db
from wd.jobs import queue, registry
from wd.jobs.registry import JobContext

NOW = "2026-10-14T08:00:00Z"
LATER = "2026-10-14T08:05:00Z"


def job_row(conn, job_id):
    return db.row_to_dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def test_enqueue_upserts_on_the_live_key(conn):
    a = queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", priority=20, run_after="2026-10-14T09:00:00Z", now=NOW)
    b = queue.enqueue(conn, "generate_content", {"word_id": 1, "force": True}, dedupe_key="content:1", priority=10, run_after="2026-10-14T08:30:00Z", now=LATER)
    assert a == b
    row = job_row(conn, a)
    assert row["priority"] == 10 and row["run_after"] == "2026-10-14T08:30:00Z" and row["updated_at"] == LATER
    assert json.loads(row["payload_json"]) == {"word_id": 1}  # the payload of the live job is kept
    c = queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", priority=50, run_after="2026-10-14T10:00:00Z", now=NOW)
    assert c == a and job_row(conn, a)["priority"] == 10  # min() keeps the lower priority / earlier run_after
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_done_jobs_do_not_conflict_and_null_keys_never_dedupe(conn):
    a = queue.enqueue(conn, "lookup_word", {"word_id": 5}, dedupe_key="lookup:5", now=NOW)
    queue.finish(conn, a, {"ok": True}, now=NOW)
    b = queue.enqueue(conn, "lookup_word", {"word_id": 5}, dedupe_key="lookup:5", now=NOW)
    assert b != a
    x = queue.enqueue(conn, "send_webhook", {"batch_id": 1}, dedupe_key=None, now=NOW)
    y = queue.enqueue(conn, "send_webhook", {"batch_id": 1}, dedupe_key=None, now=NOW)
    assert x != y


def test_enqueue_rejects_unknown_type(conn):
    with pytest.raises(ValueError):
        queue.enqueue(conn, "make_coffee", {}, dedupe_key=None)


def test_head_type_orders_by_priority_across_types(conn):
    for i in range(30):
        queue.enqueue(conn, "generate_content", {"word_id": i}, dedupe_key=f"content:{i}", priority=90, now=NOW)
    queue.enqueue(conn, "lookup_word", {"word_id": 99}, dedupe_key="lookup:99", priority=10, now=NOW)
    assert queue.head_type(conn, queue.CLAUDE_TYPES, NOW) == "lookup_word"
    assert queue.head_type(conn, ("generate_content",), NOW) == "generate_content"
    assert queue.head_type(conn, ("fetch_image",), NOW) is None
    queue.enqueue(conn, "fetch_image", {"word_id": 1}, dedupe_key="image:1", priority=10, run_after="2026-10-14T09:00:00Z", now=NOW)
    assert queue.head_type(conn, ("fetch_image",), NOW) is None  # not runnable yet
    assert queue.head_type(conn, ("fetch_image",), "2026-10-14T09:00:00Z") == "fetch_image"


def test_claim_batch_takes_up_to_limit_in_order_and_increments_attempts(conn):
    ids = [queue.enqueue(conn, "generate_content", {"word_id": i}, dedupe_key=f"content:{i}", priority=20, now=NOW) for i in range(12)]
    queue.enqueue(conn, "generate_content", {"word_id": 100}, dedupe_key="content:100", priority=10, now=NOW)  # head
    jobs = queue.claim_batch(conn, "generate_content", 10, "claude-1:boot", now=NOW)
    assert len(jobs) == 10
    assert jobs[0].payload["word_id"] == 100  # priority 10 first, then ids in order
    assert [j.payload["word_id"] for j in jobs[1:]] == list(range(9))
    assert all(j.status == "running" and j.attempts == 1 and j.locked_by == "claude-1:boot" and j.locked_at == NOW for j in jobs)
    rest = queue.claim_batch(conn, "generate_content", 10, "claude-1:boot", now=NOW)
    assert [j.payload["word_id"] for j in rest] == [9, 10, 11]
    assert queue.claim_batch(conn, "generate_content", 10, "claude-1:boot", now=NOW) == []
    assert len(ids) == 12


def test_claim_batch_honours_group_size(conn):
    for i in range(6):
        queue.enqueue(conn, "generate_content", {"word_id": i, "group_size": 2}, dedupe_key=f"content:{i}", priority=20, now=NOW)
    for i in range(6, 10):
        queue.enqueue(conn, "generate_content", {"word_id": i}, dedupe_key=f"content:{i}", priority=20, now=NOW)
    jobs = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert [j.payload["word_id"] for j in jobs] == [0, 1]  # head says group_size 2 → n = 2
    jobs = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert [j.payload["word_id"] for j in jobs] == [2, 3]
    jobs = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert [j.payload["word_id"] for j in jobs] == [4, 5]
    jobs = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert [j.payload["word_id"] for j in jobs] == [6, 7, 8, 9]  # no group_size → full limit


def test_claim_is_atomic_under_concurrency(connect, conn):
    for i in range(40):
        queue.enqueue(conn, "lookup_word", {"word_id": i}, dedupe_key=f"lookup:{i}", now=NOW)
    claimed: list[int] = []
    lock = threading.Lock()

    def worker(name: str) -> None:
        c = connect()
        try:
            while True:
                jobs = queue.claim_batch(c, "lookup_word", 7, name, now=NOW)
                if not jobs:
                    return
                with lock:
                    claimed.extend(j.id for j in jobs)
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(claimed) == sorted(set(claimed)) and len(claimed) == 40


def test_finish_fail_backoff_and_dead(conn):
    job_id = queue.enqueue(conn, "lookup_word", {"word_id": 1}, dedupe_key="lookup:1", max_attempts=3, now=NOW)
    (job,) = queue.claim_batch(conn, "lookup_word", 20, "w", now=NOW)
    assert queue.fail(conn, job.id, "boom 1", now=NOW) == "queued"
    row = job_row(conn, job_id)
    assert row["run_after"] == "2026-10-14T08:02:00Z" and row["last_error"] == "boom 1" and row["locked_by"] is None
    assert queue.claim_batch(conn, "lookup_word", 20, "w", now=NOW) == []  # backing off
    (job,) = queue.claim_batch(conn, "lookup_word", 20, "w", now="2026-10-14T08:02:00Z")
    assert job.attempts == 2
    assert queue.fail(conn, job.id, "boom 2", now="2026-10-14T08:02:00Z") == "queued"
    assert job_row(conn, job_id)["run_after"] == "2026-10-14T08:12:00Z"
    (job,) = queue.claim_batch(conn, "lookup_word", 20, "w", now="2026-10-14T08:12:00Z")
    assert job.attempts == 3
    assert queue.fail(conn, job.id, "boom 3", now="2026-10-14T08:12:00Z") == "dead"
    row = job_row(conn, job_id)
    assert row["status"] == "dead" and row["finished_at"] == "2026-10-14T08:12:00Z"
    other = queue.enqueue(conn, "lookup_word", {"word_id": 2}, dedupe_key="lookup:2", now=NOW)
    (job,) = queue.claim_batch(conn, "lookup_word", 20, "w", now=NOW)
    queue.finish(conn, job.id, {"applied": 1}, now=LATER)
    row = job_row(conn, other)
    assert row["status"] == "done" and json.loads(row["result_json"]) == {"applied": 1} and row["finished_at"] == LATER and row["locked_by"] is None


def test_backoff_table():
    assert [queue.backoff_minutes(n) for n in (1, 2, 3, 4, 9)] == [2, 10, 60, 60, 60]


def test_defer_consumes_no_attempt(conn):
    a = queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", now=NOW)
    b = queue.enqueue(conn, "generate_content", {"word_id": 2}, dedupe_key="content:2", now=NOW)
    jobs = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert [j.attempts for j in jobs] == [1, 1]
    assert queue.defer(conn, [a, b], "2026-10-15T00:05:00Z", now=NOW) == 2
    for job_id in (a, b):
        row = job_row(conn, job_id)
        assert row["status"] == "queued" and row["attempts"] == 0 and row["run_after"] == "2026-10-15T00:05:00Z" and row["locked_by"] is None
    # deferring an already-queued job only moves run_after later, never earlier
    assert queue.defer(conn, [a], "2026-10-14T12:00:00Z", now=NOW) == 1
    assert job_row(conn, a)["run_after"] == "2026-10-15T00:05:00Z"
    assert queue.defer(conn, [], LATER) == 0


def test_requeue_group_bisection_without_attempt(conn):
    ids = [queue.enqueue(conn, "generate_content", {"word_id": i}, dedupe_key=f"content:{i}", now=NOW) for i in range(10)]
    jobs = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert len(jobs) == 10
    assert queue.requeue_group(conn, [j.id for j in jobs], 5, consume_attempt=False, error="budget", now=NOW) == 10
    for job_id in ids:
        row = job_row(conn, job_id)
        assert row["status"] == "queued" and row["attempts"] == 0 and row["run_after"] == NOW
        assert json.loads(row["payload_json"])["group_size"] == 5 and row["last_error"] == "budget"
    first = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert len(first) == 5  # 10 → 5
    queue.requeue_group(conn, [j.id for j in first], 3, consume_attempt=False, now=NOW)
    assert len(queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)) == 3  # 5 → 3


def test_requeue_group_with_attempt_backs_off_and_kills_exhausted(conn):
    a = queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", max_attempts=1, now=NOW)
    b = queue.enqueue(conn, "generate_content", {"word_id": 2}, dedupe_key="content:2", max_attempts=3, now=NOW)
    jobs = queue.claim_batch(conn, "generate_content", 10, "w", now=NOW)
    assert len(jobs) == 2
    queue.requeue_group(conn, [a, b], 1, consume_attempt=True, error="second failure", now=NOW)
    ra, rb = job_row(conn, a), job_row(conn, b)
    assert ra["status"] == "dead" and ra["attempts"] == 1 and ra["last_error"] == "second failure"
    assert rb["status"] == "queued" and rb["attempts"] == 1 and rb["run_after"] == "2026-10-14T08:02:00Z" and json.loads(rb["payload_json"])["group_size"] == 1


def test_requeue_stale(conn):
    a = queue.enqueue(conn, "fetch_image", {"word_id": 1}, dedupe_key="image:1", now=NOW)
    b = queue.enqueue(conn, "fetch_image", {"word_id": 2}, dedupe_key="image:2", now=NOW)
    c = queue.enqueue(conn, "fetch_image", {"word_id": 3}, dedupe_key="image:3", run_after="2026-10-14T06:00:00Z", now=NOW)
    (jc,) = queue.claim_batch(conn, "fetch_image", 1, "io-1:mine", now="2026-10-14T07:00:00Z")  # only c is runnable at 07:00 → locked 60 min before NOW
    (ja,) = queue.claim_batch(conn, "fetch_image", 1, "io-1:mine", now=NOW)
    (jb,) = queue.claim_batch(conn, "fetch_image", 1, "io-1:other", now=NOW)
    assert {ja.id, jb.id, jc.id} == {a, b, c}
    assert queue.requeue_stale(conn, "mine", now=NOW) == 2
    assert job_row(conn, a)["status"] == "running"  # ours and fresh
    assert job_row(conn, b)["status"] == "queued" and job_row(conn, b)["locked_by"] is None  # foreign boot
    assert job_row(conn, c)["status"] == "queued"  # ours but stale


def test_cancel(conn):
    a = queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", now=NOW)
    b = queue.enqueue(conn, "generate_content", {"word_id": 2}, dedupe_key="content:2", now=NOW)
    queue.finish(conn, b, now=NOW)
    assert queue.cancel(conn, [a, b], now=NOW) == 1
    assert job_row(conn, a)["status"] == "cancelled" and job_row(conn, a)["finished_at"] == NOW
    assert job_row(conn, b)["status"] == "done"
    # a cancelled job frees the live key
    assert queue.enqueue(conn, "generate_content", {"word_id": 1}, dedupe_key="content:1", now=NOW) != a


def test_live_job_lookup(conn):
    assert queue.live_job(conn, "content:7") is None
    job_id = queue.enqueue(conn, "generate_content", {"word_id": 7}, dedupe_key="content:7", now=NOW)
    live = queue.live_job(conn, "content:7")
    assert live is not None and live.id == job_id and live.payload == {"word_id": 7}


def test_queue_functions_join_an_open_transaction(conn):
    with db.tx(conn):
        job_id = queue.enqueue(conn, "send_email", {"batch_id": 1}, dedupe_key="email:1", now=NOW)
        assert conn.in_transaction
        queue.finish(conn, job_id, now=NOW)
    assert job_row(conn, job_id)["status"] == "done"


# ------------------------------------------------------------------------------ run_once
@pytest.fixture
def ctx(settings, connect, frozen_clock):
    return JobContext(db=connect, cfg=settings, clock=frozen_clock, enqueue=queue.enqueue, log=logging.getLogger("test"), worker_id="once", boot_id="test")


@pytest.fixture(autouse=True)
def _clean_registry():
    saved = dict(registry._HANDLERS)
    registry.reset()
    yield
    registry.reset()
    registry._HANDLERS.update(saved)


def test_run_once_drains_with_registered_handler(conn, ctx, frozen_clock):
    now = ctx.now()
    seen: list[list[int]] = []

    @registry.register("send_webhook")
    def handle(c: JobContext, jobs):
        seen.append([j.id for j in jobs])
        cc = c.db()
        try:
            for j in jobs:
                queue.finish(cc, j.id, {"sent": True}, now=c.now())
        finally:
            cc.close()

    ids = [queue.enqueue(conn, "send_webhook", {"batch_id": i}, dedupe_key=f"webhook:{i}", now=now) for i in range(3)]
    assert queue.run_once(ctx) == 3
    assert seen == [[ids[0]], [ids[1]], [ids[2]]]  # limit 1 per claim for IO types
    assert all(job_row(conn, i)["status"] == "done" for i in ids)
    assert queue.run_once(ctx) == 0


def test_run_once_fails_jobs_without_handler_and_crashing_handlers(conn, ctx):
    now = ctx.now()
    orphan = queue.enqueue(conn, "fetch_image", {"word_id": 1}, dedupe_key="image:1", now=now)

    @registry.register("send_email")
    def crash(c: JobContext, jobs):
        raise RuntimeError("kaboom")

    @registry.register("send_webhook")
    def forgetful(c: JobContext, jobs):
        pass  # returns without finishing

    crashing = queue.enqueue(conn, "send_email", {"batch_id": 1}, dedupe_key="email:1", now=now)
    forgotten = queue.enqueue(conn, "send_webhook", {"batch_id": 1}, dedupe_key="webhook:1", now=now)
    assert queue.run_once(ctx) == 3
    assert job_row(conn, orphan)["status"] == "queued" and "no handler" in job_row(conn, orphan)["last_error"]
    assert "kaboom" in job_row(conn, crashing)["last_error"] and job_row(conn, crashing)["status"] == "queued"
    assert "without finishing" in job_row(conn, forgotten)["last_error"]
    assert all(job_row(conn, i)["run_after"] > now for i in (orphan, crashing, forgotten))  # backed off → the drain terminated


def test_limit_for(settings):
    assert queue.limit_for("generate_content", settings) == settings.ai_batch_size == 10
    assert queue.limit_for("lookup_word", settings) == 20
    for t in ("consolidate_bank", "generate_svg", "prewarm_plan", "fetch_image", "send_email", "send_webhook"):
        assert queue.limit_for(t, settings) == 1
