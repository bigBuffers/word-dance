"""Image service functions used by the word routes (WP3) and the admin endpoints (TASKS §I, WP6).

* :func:`image_meta` — the API.md ``ImageMeta`` for a word; falls back to the template card (never None).
* :func:`reject_active_image` — report flow (API.md 28): active image → ``rejected``, ``fetch_image`` enqueued with
  the rejected image excluded; returns the job id.
* :func:`request_refresh` — 换一张 (API.md 29): ``fetch_image`` with ``exclude`` = the current image's ref/sha.
* :func:`admin_refetch` — API.md 69 (``provider`` / ``query`` overrides).
* :func:`word_is_studied` — DESIGN §9: in a bank (``new``/``learning``) or in an open batch.
* :func:`retry_if_failed` / :func:`retry_failed_studied` — the failed-image retry rules of DESIGN §9 (PLAN §5.1 C7,
  D-images-13): a word whose chain failed is fetched again only while somebody studies it, at most every
  :data:`RETRY_MIN_AGE_H` hours and :data:`RETRY_MAX_AUTO_30D` times per 30 days (the ``retry: true`` payload flag is
  the counter), never for a function word (``style.skip_image``) and never over a live ``fetch_image`` job. The nightly
  03:30 maintenance (``scheduler.maintenance``) and ``wd images-retry`` call :func:`retry_failed_studied` with the
  :data:`RETRY_NIGHTLY_LIMIT` cap; the live counter-example that motivated it: 17 of the 18 failed words were being
  studied and would never have been fetched again, most of them never having reached a provider (cooldown).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any, Mapping

from ..clock import now_iso, parse_iso, to_iso
from ..db import maybe_tx
from ..jobs import queue
from . import style
from .store import attribution_line

CARD_WIDTH, CARD_HEIGHT = 800, 500
FETCH_DEDUPE = "image:{word_id}"
FETCH_FOLLOWUP_DEDUPE = "image:{word_id}:r{n}"  # a request that arrives while the live job is already running
OPEN_BATCH_DAYS = 2

# PLAN §5.1 C7 retry rules (D-images-13)
RETRY_MIN_AGE_H = 6  # provider cooldowns last 10–15 min; six hours is ample and keeps a word from hammering a dead chain
RETRY_MAX_AUTO_30D = 3  # automatic (payload retry:true) attempts per word per 30 days — a manual 换一张 / admin refetch is not counted
RETRY_NIGHTLY_LIMIT = 50  # like PREFETCH_LIMIT: one night's worth of IoWorker work
RETRY_NIGHTLY_PRIORITY = 30  # same lane as the prefetch content jobs (below bank p20, above prewarm p90)


def card_meta(word_id: int) -> dict[str, Any]:
    """The template-card ``ImageMeta`` (API.md §9.1): ``{id:null, url:'/media/card/<id>.svg', kind:'card', …}``."""
    return {
        "id": None,
        "url": f"/media/card/{int(word_id)}.svg",
        "kind": "card",
        "provider": "card_svg",
        "mime": "image/svg+xml",
        "width": CARD_WIDTH,
        "height": CARD_HEIGHT,
        "alt_zh": None,
        "attribution": None,
    }


def active_image_row(conn: sqlite3.Connection, word_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT wi.* FROM words w JOIN word_images wi ON wi.id = w.active_image_id WHERE w.id = ? AND wi.status = 'active'",
        (int(word_id),),
    ).fetchone()


def image_meta(conn: sqlite3.Connection, word_id: int) -> dict[str, Any]:
    """``ImageMeta`` for the word's active photo / Claude SVG, else the card fallback (card URL obeys the visibility
    rule through the media route, so this function itself needs no user)."""
    row = active_image_row(conn, word_id)
    if row is None:
        return card_meta(word_id)
    provider = str(row["provider"])
    is_svg = provider == "claude_svg"
    attribution = None
    if not is_svg:
        attribution = {
            "title": row["title"],
            "creator": row["creator"],
            "creator_url": row["creator_url"],
            "license": row["license"] or "unknown",
            "license_url": row["license_url"],
            "landing_url": row["landing_url"],
            "text": row["attribution_text"] or attribution_line(row["title"], row["creator"], row["license"]),
        }
    return {
        "id": int(row["id"]),
        "url": f"/media/images/{row['file_path']}",
        "kind": "svg" if is_svg else "photo",
        "provider": provider,
        "mime": row["mime"],
        "width": row["width"],
        "height": row["height"],
        "alt_zh": row["alt_zh"],
        "attribution": attribution,
    }


def exclude_for(conn: sqlite3.Connection, word_id: int, *, statuses: tuple[str, ...] = ("active", "rejected")) -> list[str]:
    """Provider refs and sha256 values of this word's images in ``statuses`` (the ``fetch_image.exclude`` payload)."""
    rows = conn.execute(
        f"SELECT provider_ref, sha256 FROM word_images WHERE word_id = ? AND status IN ({','.join('?' * len(statuses))}) ORDER BY id",
        (int(word_id), *statuses),
    ).fetchall()
    out: list[str] = []
    for ref, sha in rows:
        for value in (ref, sha):
            if value and str(value) not in out:
                out.append(str(value))
    return out


def _word_exists(conn: sqlite3.Connection, word_id: int) -> bool:
    return conn.execute("SELECT 1 FROM words WHERE id = ?", (int(word_id),)).fetchone() is not None


def merge_fetch_payloads(existing: dict[str, Any], requested: dict[str, Any]) -> dict[str, Any]:
    """The payload a live ``fetch_image`` job must carry to honour a later request for the same word: the union of
    both ``exclude`` lists and the latest ``provider`` / ``query`` override (a request without one keeps the job's)."""
    merged = dict(existing)
    exclude = [str(x) for x in (existing.get("exclude") or []) if x]
    for x in requested.get("exclude") or []:
        if x and str(x) not in exclude:
            exclude.append(str(x))
    if exclude:
        merged["exclude"] = exclude
    for key in ("provider", "query"):
        if requested.get(key):
            merged[key] = requested[key]
    return merged


def _fold_into_live(conn: sqlite3.Connection, job_id: int, payload: dict[str, Any], now: str) -> bool:
    """Make the live job ``job_id`` carry ``payload`` as well (``queue.enqueue``'s UPSERT only folds priority and
    ``run_after``). False when the job is already ``running`` without it — its handler has read the old payload — so
    the caller must queue a follow-up instead of claiming this fetch will honour the request."""
    row = conn.execute("SELECT status, payload_json FROM jobs WHERE id = ?", (int(job_id),)).fetchone()
    if row is None:
        return True
    try:
        existing = json.loads(row["payload_json"] or "{}")
    except ValueError:
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    merged = merge_fetch_payloads(existing, payload)
    if merged == existing:
        return True  # nothing new to ask for (e.g. a second 换一张 excluding the same current image)
    if row["status"] != "queued":
        return False
    conn.execute("UPDATE jobs SET payload_json = ?, updated_at = ? WHERE id = ? AND status = 'queued'", (queue.dump_payload(merged), now, int(job_id)))
    return True


def _enqueue_followup(conn: sqlite3.Connection, word_id: int, payload: dict[str, Any], priority: int, now: str) -> int:
    """``image:<word_id>:r<n>`` behind a running ``image:<word_id>`` job (the IoWorker is single-threaded, so it simply
    runs next); a follow-up still ``queued`` is reused like the primary key, a fresh ``n`` is taken otherwise."""
    pattern = FETCH_FOLLOWUP_DEDUPE.format(word_id=int(word_id), n="%")
    live = conn.execute(
        "SELECT dedupe_key FROM jobs WHERE type = 'fetch_image' AND dedupe_key LIKE ? AND status IN ('queued', 'running') ORDER BY id DESC LIMIT 1",
        (pattern,),
    ).fetchone()
    if live is not None:
        job_id = queue.enqueue(conn, "fetch_image", payload, dedupe_key=str(live[0]), priority=int(priority), now=now)
        if _fold_into_live(conn, job_id, payload, now):
            return job_id
    n = 1 + int(conn.execute("SELECT COUNT(*) FROM jobs WHERE dedupe_key LIKE ?", (pattern,)).fetchone()[0])
    return queue.enqueue(conn, "fetch_image", payload, dedupe_key=FETCH_FOLLOWUP_DEDUPE.format(word_id=int(word_id), n=n), priority=int(priority), now=now)


def enqueue_fetch(
    conn: sqlite3.Connection,
    word_id: int,
    *,
    exclude: list[str] | None = None,
    provider: str | None = None,
    query: str | None = None,
    priority: int = 10,
    now: str | None = None,
    retry: bool = False,
) -> int:
    """``fetch_image {word_id, exclude?, provider?, query?, retry?}`` on the live key ``image:<word_id>`` + ``image_state='queued'``.

    A request that meets a live job for the word is merged into it (``exclude`` union, latest ``provider`` / ``query``)
    while that job is still ``queued``; when it is already ``running`` with an older payload, a follow-up job runs after
    it — so a 换一张 ``exclude`` or an API.md 69 override is never silently dropped by the dedupe UPSERT. ``retry=True``
    marks an automatic retry (``payload.retry = true``, counted by :func:`auto_retries_30d`); the handler ignores the key."""
    now = now or now_iso()
    payload: dict[str, Any] = {"word_id": int(word_id)}
    if exclude:
        payload["exclude"] = list(exclude)
    if provider:
        payload["provider"] = provider
    if query:
        payload["query"] = query
    if retry:
        payload["retry"] = True
    with maybe_tx(conn):  # BEGIN IMMEDIATE: the read-merge-write below cannot interleave with a claim
        job_id = queue.enqueue(conn, "fetch_image", payload, dedupe_key=FETCH_DEDUPE.format(word_id=int(word_id)), priority=int(priority), now=now)
        if not _fold_into_live(conn, job_id, payload, now):
            job_id = _enqueue_followup(conn, word_id, payload, priority, now)
        conn.execute("UPDATE words SET image_state = 'queued', updated_at = ? WHERE id = ?", (now, int(word_id)))
    return job_id


def reject_active_image(conn: sqlite3.Connection, word_id: int, *, reason: str, priority: int = 10, now: str | None = None) -> int | None:
    """Mark the active image ``rejected``, record the event, enqueue ``fetch_image`` excluding it; returns the job id
    (None when the word does not exist)."""
    now = now or now_iso()
    with maybe_tx(conn):
        if not _word_exists(conn, word_id):
            return None
        row = active_image_row(conn, word_id)
        if row is not None:
            conn.execute("UPDATE word_images SET status = 'rejected' WHERE id = ?", (int(row["id"]),))
            conn.execute("UPDATE words SET active_image_id = NULL, updated_at = ? WHERE id = ?", (now, int(word_id)))
            conn.execute(
                "INSERT INTO system_events(kind, detail_json, created_at) VALUES ('image_rejected', ?, ?)",
                (json.dumps({"word_id": int(word_id), "image_id": int(row["id"]), "provider": row["provider"], "reason": reason[:200]}, ensure_ascii=False), now),
            )
        exclude = exclude_for(conn, word_id)
        return enqueue_fetch(conn, word_id, exclude=exclude, priority=priority, now=now)


def request_refresh(conn: sqlite3.Connection, word_id: int, *, priority: int = 10, now: str | None = None) -> int | None:
    """换一张 (API.md 29): keep the current image until a replacement lands; exclude it (and every rejected one)."""
    now = now or now_iso()
    with maybe_tx(conn):
        if not _word_exists(conn, word_id):
            return None
        return enqueue_fetch(conn, word_id, exclude=exclude_for(conn, word_id), priority=priority, now=now)


def admin_refetch(conn: sqlite3.Connection, word_id: int, *, provider: str | None = None, query: str | None = None, priority: int = 10, now: str | None = None) -> int | None:
    """API.md 69: a new image, optionally from one provider (``claude_svg`` goes straight to ``generate_svg``) or for a custom query."""
    now = now or now_iso()
    with maybe_tx(conn):
        if not _word_exists(conn, word_id):
            return None
        return enqueue_fetch(conn, word_id, exclude=exclude_for(conn, word_id), provider=provider, query=(query or "").strip() or None, priority=priority, now=now)


def word_is_studied(conn: sqlite3.Connection, word_id: int, now: str | None = None) -> bool:
    """DESIGN §9: ``EXISTS user_words(state IN ('new','learning')) OR EXISTS push_items of an open batch`` (a batch of
    the last two local days that is not completed)."""
    now = now or now_iso()
    min_date = to_iso(parse_iso(now) - timedelta(days=OPEN_BATCH_DAYS))[:10]
    row = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM user_words WHERE word_id = :wid AND state IN ('new','learning')) "
        "OR EXISTS(SELECT 1 FROM push_items pi JOIN push_batches pb ON pb.id = pi.batch_id "
        "          WHERE pi.word_id = :wid AND pb.completed_at IS NULL AND pb.local_date >= :min_date)",
        {"wid": int(word_id), "min_date": min_date},
    ).fetchone()
    return bool(row[0])


# ------------------------------------------------------------------------------ failed-image retries (PLAN §5.1 C7)
def _fetch_keys(word_id: int) -> tuple[str, str]:
    """The live key and the follow-up LIKE pattern of a word's ``fetch_image`` jobs."""
    return FETCH_DEDUPE.format(word_id=int(word_id)), FETCH_FOLLOWUP_DEDUPE.format(word_id=int(word_id), n="%")


def _live_fetch_exists(conn: sqlite3.Connection, word_id: int) -> bool:
    key, pattern = _fetch_keys(word_id)
    row = conn.execute(
        "SELECT 1 FROM jobs WHERE type = 'fetch_image' AND status IN ('queued','running') AND (dedupe_key = ? OR dedupe_key LIKE ?) LIMIT 1",
        (key, pattern),
    ).fetchone()
    return row is not None


def last_fetch_finished_at(conn: sqlite3.Connection, word_id: int) -> str | None:
    """When the word's most recent ``fetch_image`` job ended (``finished_at``, else ``updated_at``), or None when it never had one."""
    key, pattern = _fetch_keys(word_id)
    row = conn.execute(
        "SELECT MAX(COALESCE(finished_at, updated_at)) FROM jobs WHERE type = 'fetch_image' AND status IN ('done','dead','cancelled') "
        "AND (dedupe_key = ? OR dedupe_key LIKE ?)",
        (key, pattern),
    ).fetchone()
    return str(row[0]) if row and row[0] else None


def auto_retries_30d(conn: sqlite3.Connection, word_id: int, now: str) -> int:
    """How many automatic retries (``payload.retry = true``, any status) the word got in the last 30 days."""
    since = to_iso(parse_iso(now) - timedelta(days=30))
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE type = 'fetch_image' AND json_extract(payload_json, '$.word_id') = ? "
        "AND json_extract(payload_json, '$.retry') = 1 AND created_at >= ?",
        (int(word_id), since),
    ).fetchone()
    return int(row[0])


def retry_due(conn: sqlite3.Connection, word: Mapping[str, Any], now: str) -> bool:
    """Is ``word`` (a row with ``id``, ``pos``, ``image_state``) due for an automatic fetch retry?

    ``image_state == 'failed'`` ∧ not a function word (the gate put it there on purpose) ∧ no live ``fetch_image`` job ∧ the
    last fetch ended ≥ :data:`RETRY_MIN_AGE_H` hours ago (or none is recorded) ∧ fewer than :data:`RETRY_MAX_AUTO_30D`
    automatic retries in 30 days."""
    if word.get("image_state") != "failed" or style.skip_image(word):
        return False
    word_id = int(word["id"])
    if _live_fetch_exists(conn, word_id):
        return False
    last = last_fetch_finished_at(conn, word_id)
    if last is not None and last > to_iso(parse_iso(now) - timedelta(hours=RETRY_MIN_AGE_H)):
        return False
    return auto_retries_30d(conn, word_id, now) < RETRY_MAX_AUTO_30D


def retry_if_failed(conn: sqlite3.Connection, word: Mapping[str, Any], *, priority: int, now: str) -> int | None:
    """Enqueue an automatic ``fetch_image`` retry for ``word`` when :func:`retry_due`; returns the job id or None.

    The hook for the moments a learner meets the word again (bank actions, batch building — R-16: wired after the
    integration); the nightly sweep is :func:`retry_failed_studied`."""
    if not retry_due(conn, word, now):
        return None
    return enqueue_fetch(conn, int(word["id"]), priority=int(priority), now=now, retry=True)


def retry_failed_studied(
    conn: sqlite3.Connection,
    now: str,
    *,
    limit: int = RETRY_NIGHTLY_LIMIT,
    priority: int = RETRY_NIGHTLY_PRIORITY,
    dry_run: bool = False,
) -> list[int]:
    """The nightly sweep: every ``failed`` word that is being studied (:func:`word_is_studied`) and :func:`retry_due`,
    oldest first (``words.updated_at``), at most ``limit`` of them; enqueued with ``priority`` unless ``dry_run``.
    Returns the word ids chosen (the dry run returns the same list without enqueueing)."""
    rows = conn.execute(
        "SELECT id, lemma, pos, image_state FROM words WHERE image_state = 'failed' AND merged_into_word_id IS NULL ORDER BY updated_at, id"
    ).fetchall()
    chosen: list[int] = []
    for row in rows:
        if len(chosen) >= max(0, int(limit)):
            break
        word = {k: row[k] for k in row.keys()}
        if style.skip_image(word):  # the gate's words stay on the card; cheap, so before the queries
            continue
        if not word_is_studied(conn, int(word["id"]), now) or not retry_due(conn, word, now):
            continue
        if not dry_run:
            enqueue_fetch(conn, int(word["id"]), priority=int(priority), now=now, retry=True)
        chosen.append(int(word["id"]))
    return chosen


def photo_mix(conn: sqlite3.Connection) -> dict[str, int]:
    """``with_photo`` / ``with_claude_svg`` / ``card_only`` for ``AdminOverview.words`` (API.md 54)."""
    row = conn.execute(
        "SELECT "
        " SUM(CASE WHEN wi.provider IN ('wikimedia','openverse','pixabay','pexels') THEN 1 ELSE 0 END) AS with_photo, "
        " SUM(CASE WHEN wi.provider = 'claude_svg' THEN 1 ELSE 0 END) AS with_claude_svg, "
        " SUM(CASE WHEN wi.id IS NULL AND w.content_state = 'ready' THEN 1 ELSE 0 END) AS card_only "
        "FROM words w LEFT JOIN word_images wi ON wi.id = w.active_image_id AND wi.status = 'active'"
    ).fetchone()
    return {"with_photo": int(row["with_photo"] or 0), "with_claude_svg": int(row["with_claude_svg"] or 0), "card_only": int(row["card_only"] or 0)}
