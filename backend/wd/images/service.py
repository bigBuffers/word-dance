"""Image service functions used by the word routes (WP3) and the admin endpoints (TASKS §I, WP6).

* :func:`image_meta` — the API.md ``ImageMeta`` for a word; falls back to the template card (never None).
* :func:`reject_active_image` — report flow (API.md 28): active image → ``rejected``, ``fetch_image`` enqueued with
  the rejected image excluded; returns the job id.
* :func:`request_refresh` — 换一张 (API.md 29): ``fetch_image`` with ``exclude`` = the current image's ref/sha.
* :func:`admin_refetch` — API.md 69 (``provider`` / ``query`` overrides).
* :func:`word_is_studied` — DESIGN §9: in a bank (``new``/``learning``) or in an open batch.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import timedelta
from typing import Any

from ..clock import now_iso, parse_iso, to_iso
from ..db import maybe_tx
from ..jobs import queue
from .store import attribution_line

CARD_WIDTH, CARD_HEIGHT = 800, 500
FETCH_DEDUPE = "image:{word_id}"
OPEN_BATCH_DAYS = 2


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


def enqueue_fetch(
    conn: sqlite3.Connection,
    word_id: int,
    *,
    exclude: list[str] | None = None,
    provider: str | None = None,
    query: str | None = None,
    priority: int = 10,
    now: str | None = None,
) -> int:
    """``fetch_image {word_id, exclude?, provider?, query?}`` on the live key ``image:<word_id>`` + ``image_state='queued'``."""
    now = now or now_iso()
    payload: dict[str, Any] = {"word_id": int(word_id)}
    if exclude:
        payload["exclude"] = list(exclude)
    if provider:
        payload["provider"] = provider
    if query:
        payload["query"] = query
    with maybe_tx(conn):
        job_id = queue.enqueue(conn, "fetch_image", payload, dedupe_key=FETCH_DEDUPE.format(word_id=int(word_id)), priority=int(priority), now=now)
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
