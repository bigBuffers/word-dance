"""``generate_svg`` handler (CLAUDE_INTEGRATION §5.5, §6.1, §6.7, §7 SVG sub-cap).

One word per call. The job is enqueued by WP6's ``fetch_image`` only for studied words at priority < 90; the
budget reservation applies the SVG daily sub-cap (``WD_AI_SVG_DAILY_BUDGET_USD``, counted inside the daily cap).
A returned SVG goes through WP6's ``images.activate_svg`` (defusedxml parse + allow-lists + re-serialisation, late
import); a rejected SVG leaves ``image_state='failed'`` so the template card keeps being served and is never retried
automatically.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Mapping

from .. import db
from ..interfaces import Job
from ..jobs import queue
from ..jobs.registry import JobContext, register
from ..services import bank, words
from . import common, runner
from .content import dictionary_hint

log = logging.getLogger("wd.ai.svg")

KIND = "svg"
CONCEPT_MAX = 60
MEANING_MAX = 60


def _active_content(conn: sqlite3.Connection, word: Mapping[str, Any]) -> dict[str, Any] | None:
    return words.active_content(conn, word)


def build_user_prompt(display: str, meaning: str, concept: str) -> str:
    """CLAUDE_INTEGRATION §5.5: ``Draw an illustration for the word "abandon" (v. 放弃；抛弃). Concept: 被遗弃在雪地里的汽车。``"""
    meaning = (meaning or "").strip()[:MEANING_MAX]
    concept = (concept or "").strip().rstrip("。")[:CONCEPT_MAX]
    head = f'Draw an illustration for the word "{display}"' + (f" ({meaning})" if meaning else "") + "."
    return head + (f" Concept: {concept}。" if concept else "")


def prompt_for(conn: sqlite3.Connection, word: Mapping[str, Any]) -> str:
    content = _active_content(conn, word) or {}
    meaning = str(content.get("meaning_zh") or dictionary_hint(word.get("translation")) or "")
    concept = str(content.get("image_alt_zh") or meaning)
    return build_user_prompt(str(word["display"]), meaning, concept)


def _has_active_image(conn: sqlite3.Connection, word_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM words w JOIN word_images wi ON wi.id = w.active_image_id WHERE w.id = ? AND wi.status = 'active'", (int(word_id),)
    ).fetchone()
    return row is not None


def mark_failed(conn: sqlite3.Connection, word_id: int, *, now: str) -> None:
    """``image_state='failed'`` (the template card is served) unless a photo/SVG is already active."""
    with db.maybe_tx(conn):
        if not _has_active_image(conn, word_id):
            conn.execute("UPDATE words SET image_state = 'failed', updated_at = ? WHERE id = ?", (now, int(word_id)))


def _on_dead(now: str) -> common.OnDead:
    def on_dead(conn: sqlite3.Connection, job: Job) -> None:
        wid = common.payload_int(job, "word_id")
        if wid is not None:
            mark_failed(conn, wid, now=now)

    return on_dead


def _skip(conn: sqlite3.Connection, job: Job, word_id: int | None, reason: str, *, now: str) -> None:
    if word_id is not None:
        mark_failed(conn, word_id, now=now)
    queue.finish(conn, job.id, {"skipped": reason}, now=now)


@register("generate_svg")
def handle_generate_svg(ctx: JobContext, jobs: list[Job]) -> None:
    conn = ctx.db()
    try:
        cfg = ctx.cfg
        for job in jobs:
            now = ctx.now()
            wid = common.payload_int(job, "word_id")
            word = None if wid is None else words.word_row(conn, wid)
            if word is None:
                queue.finish(conn, job.id, {"skipped": "missing_word"}, now=now)
                continue
            if not cfg.images_enabled or not cfg.svg_via_claude:
                _skip(conn, job, wid, "svg_disabled", now=now)
                continue
            if cfg.ai_svg_daily_budget_usd <= 0:
                _skip(conn, job, wid, "svg_budget_disabled", now=now)
                continue
            activate = bank.late_import("wd.images", "activate_svg")
            if activate is None:
                _skip(conn, job, wid, "images_module_missing", now=now)
                continue
            result = common.claude_call(
                ctx,
                conn,
                kind=KIND,
                jobs=[job],
                system_prompt=runner.load_prompt("svg_system"),
                user_prompt=prompt_for(conn, word),
                schema=runner.load_schema("svg_v1"),
                word_count=1,
                now=now,
            )
            if result is None:
                continue
            if not result.ok:
                common.handle_failure(ctx, conn, [job], result, now=now, on_dead=_on_dead(now))
                continue
            common.record_success(conn, now=now)
            structured = result.structured or {}
            svg = structured.get("svg")
            alt = structured.get("alt_zh") if isinstance(structured.get("alt_zh"), str) else None
            try:
                if not isinstance(svg, str) or not svg.strip():
                    raise ValueError("response carries no svg string")
                image_id = activate(conn, cfg, wid, svg, alt, now=now)
            except ValueError as e:  # images.sanitize_svg.SvgRejected is a ValueError
                mark_failed(conn, wid, now=now)
                queue.finish(conn, job.id, {"rejected": str(e)[:300], "cost_usd": round(result.cost_usd, 6)}, now=now)
                ctx.log.warning("generate_svg: SVG for word %s rejected: %s", word["lemma"], e, extra={"job_id": job.id, "job_type": job.type, "event": "svg_rejected"})
                continue
            queue.finish(conn, job.id, {"image_id": int(image_id), "cost_usd": round(result.cost_usd, 6)}, now=now)
            ctx.log.info("generate_svg: word %s → image %s", word["lemma"], image_id, extra={"job_id": job.id, "job_type": job.type, "cost_usd": result.cost_usd, "event": "svg_ready"})
    finally:
        conn.close()


__all__ = ["build_user_prompt", "handle_generate_svg", "mark_failed", "prompt_for"]
