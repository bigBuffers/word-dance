"""``generate_svg`` handler (CLAUDE_INTEGRATION §5.5, §6.1, §6.7, §7 SVG sub-cap).

One word per call. The job is enqueued by WP6's ``fetch_image`` only for studied words at priority < 90 that have
no image; the budget reservation applies the SVG daily sub-cap (``WD_AI_SVG_DAILY_BUDGET_USD``, counted inside the
daily cap). The SVG is the DESIGN §9 last resort before the template card, never a replacement for a photo: a
fallback job whose word gained an image meanwhile (a later 换一张 / report / admin refetch, or the job sat deferred
under the sub-cap) finishes ``{"skipped": "photo_active"}`` — checked before the call and again before activation.
Only an explicit admin request (payload ``requested: true``, API.md 69) draws over an active photo.

The user prompt (:func:`build_user_prompt`, v2 — PLAN §5.1 C3 / §5.2) carries the sense the picture must show: the
``image_alt_zh`` scene, example sentence 1 and the 「联想：」 memory hook of the active content, plus a Style line chosen
per word by ``images.style.style_for`` (``WD_IMAGE_KID_STAGES``); the system prompt forbids any text in the picture.
A returned SVG goes through WP6's ``images.activate_svg`` (defusedxml parse + allow-lists + re-serialisation with
``allow_text=False`` and the ``<desc id="aigc-label">`` marker), which records ``prompt_version`` (:data:`SVG_PROMPT_VERSION`),
``model`` (``result.model_used``) and ``text_free = 1`` on the ``word_images`` row; a rejected SVG leaves
``image_state='failed'`` so the template card keeps being served, and the word is retried through the failed-image
retry rules of DESIGN §9 (PLAN §5.1 C7: nightly ``retry_failed_studied`` / ``wd images-retry``), never by this handler.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any, Mapping

from .. import db
from ..config import Settings
from ..images import activate_svg
from ..images import style as image_style
from ..images.sanitize_svg import count_bare_ampersands
from ..interfaces import Job
from ..jobs import queue
from ..jobs.registry import JobContext, register
from ..services import words
from . import common, runner
from .content import dictionary_hint

log = logging.getLogger("wd.ai.svg")

KIND = "svg"
CONCEPT_MAX = 60
MEANING_MAX = 60
EXAMPLE_MAX = 120
HOOK_MAX = 60
HOOK_PREFIXES = ("联想：", "联想:")  # content_system rule 5: a playful association starts with 「联想：」
# the first full stop of a hook: 「。」, or an ASCII period that ends a sentence (followed by whitespace or the end and not
# preceded by a capital) — a decimal point (3.5 米) or an abbreviation (U.S.) is not the end of the association
HOOK_STOP_RE = re.compile(r"。|(?<![A-Z])\.(?=\s|$)")
SVG_PROMPT_VERSION = "svg-v2"  # written to word_images.prompt_version (0012); bump together with svg_system.txt
STYLE_TEXT: dict[str, str] = {
    image_style.STYLE_KID: "child-friendly picture-book style for 6–11-year-olds: bright warm colours, rounded shapes, friendly simple characters, everyday school, home and playground scenes familiar to a child in China.",
    image_style.STYLE_NEUTRAL: "clean flat educational illustration for teenagers and adults: calm colours, clear geometry, realistic proportions.",
}


def _active_content(conn: sqlite3.Connection, word: Mapping[str, Any]) -> dict[str, Any] | None:
    return words.active_content(conn, word)


def build_user_prompt(display: str, meaning: str, concept: str, *, example: str = "", hook: str = "", style: str = image_style.STYLE_NEUTRAL) -> str:
    """CLAUDE_INTEGRATION §5.5 user prompt (v2)::

        Draw an illustration for the word "abandon" (v. 放弃；抛弃). Scene: 被遗弃在雪地里的汽车。 Example sentence: "They had to
        abandon the car in the snow." Memory hook: 一辆车被丢在雪地里 Style: clean flat educational illustration …

    The ``for the word "…"`` fragment is a contract (``tests/fake_claude.py`` reads the word from it); an empty example
    or hook drops its segment; ``style`` is one of ``images.style.STYLES`` (an unknown value falls back to neutral).
    """
    meaning = " ".join((meaning or "").split())[:MEANING_MAX]
    concept = " ".join((concept or "").split()).rstrip("。")[:CONCEPT_MAX]
    example = " ".join((example or "").split())[:EXAMPLE_MAX].replace('"', "'")
    hook = " ".join((hook or "").split())[:HOOK_MAX]
    parts = [f'Draw an illustration for the word "{display}"' + (f" ({meaning})" if meaning else "") + "."]
    if concept:
        parts.append(f"Scene: {concept}。")
    if example:
        parts.append(f'Example sentence: "{example}"')
    if hook:
        parts.append(f"Memory hook: {hook}")
    parts.append(f"Style: {STYLE_TEXT.get(style, STYLE_TEXT[image_style.STYLE_NEUTRAL])}")
    return " ".join(parts)


def hook_from(mnemonic: str | None) -> str:
    """The concrete association of a ``mnemonic_zh`` that starts with 「联想：」 — prefix removed, cut at the first full
    stop (:data:`HOOK_STOP_RE`), at most :data:`HOOK_MAX` characters; ``""`` for a morphology tip (rule 5) or no mnemonic."""
    text = " ".join((mnemonic or "").split())
    for prefix in HOOK_PREFIXES:
        if text.startswith(prefix):
            body = HOOK_STOP_RE.split(text[len(prefix) :].strip(), maxsplit=1)[0]
            return body.strip()[:HOOK_MAX]
    return ""


def prompt_for(conn: sqlite3.Connection, word: Mapping[str, Any], *, cfg: Settings) -> str:
    """The v2 user prompt for ``word`` from its active content (scene = ``image_alt_zh``, example 1, hook) and the style
    ``images.style.style_for`` picks from ``cfg.image_kid_stages``. ``cfg`` is required (PLAN §5.1 C3, images SYNTHESIS
    §3.1.2): an optional default would let a caller that forgot it draw every word in the neutral style unnoticed."""
    content = _active_content(conn, word) or {}
    meaning = str(content.get("meaning_zh") or dictionary_hint(word.get("translation")) or "")
    concept = str(content.get("image_alt_zh") or meaning)
    examples = content.get("examples") or []
    first = examples[0] if examples and isinstance(examples[0], dict) else {}
    example = str(first.get("en") or "")
    picked = image_style.style_for(word, cfg)
    return build_user_prompt(str(word["display"]), meaning, concept, example=example, hook=hook_from(content.get("mnemonic_zh")), style=picked)


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
            requested = job.payload.get("requested") is True
            if not requested and _has_active_image(conn, wid):
                # DESIGN §9: a fallback SVG only stands in while the word has no image; one landed since this job was
                # enqueued, so keep it (image_state stays 'ready') and spend nothing.
                queue.finish(conn, job.id, {"skipped": "photo_active"}, now=now)
                ctx.log.info("generate_svg: word %s already has an image; skipped", word["lemma"], extra={"job_id": job.id, "job_type": job.type, "event": "svg_skipped"})
                continue
            result = common.claude_call(
                ctx,
                conn,
                kind=KIND,
                jobs=[job],
                system_prompt=runner.load_prompt("svg_system"),
                user_prompt=prompt_for(conn, word, cfg=cfg),
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
            if not requested and _has_active_image(conn, wid):
                # a photo landed during the call (up to 120 s): the drawing must not supersede it
                queue.finish(conn, job.id, {"skipped": "photo_active", "cost_usd": round(result.cost_usd, 6)}, now=now)
                ctx.log.info("generate_svg: a photo for word %s landed during the call; SVG discarded", word["lemma"], extra={"job_id": job.id, "job_type": job.type, "cost_usd": result.cost_usd, "event": "svg_skipped"})
                continue
            structured = result.structured or {}
            svg = structured.get("svg")
            alt = structured.get("alt_zh") if isinstance(structured.get("alt_zh"), str) else None
            try:
                if not isinstance(svg, str) or not svg.strip():
                    raise ValueError("response carries no svg string")
                repairs = count_bare_ampersands(svg)  # the sanitiser's own CDATA-aware count, not a plain BARE_AMP_RE.findall
                image_id = activate_svg(conn, cfg, wid, svg, alt, now=now, model=result.model_used, prompt_version=SVG_PROMPT_VERSION)
            except ValueError as e:  # images.sanitize_svg.SvgRejected is a ValueError
                mark_failed(conn, wid, now=now)
                queue.finish(conn, job.id, {"rejected": str(e)[:300], "cost_usd": round(result.cost_usd, 6)}, now=now)
                ctx.log.warning("generate_svg: SVG for word %s rejected: %s", word["lemma"], e, extra={"job_id": job.id, "job_type": job.type, "event": "svg_rejected"})
                continue
            if repairs:
                # the sanitiser rewrote these to &amp; (CLAUDE_INTEGRATION §6.7); logged only for a drawing that was accepted, so
                # the event counts delivered pictures the prompt's `&amp;` rule failed on — a rejected SVG logs svg_rejected alone
                ctx.log.info("generate_svg: %d bare ampersand(s) repaired for word %s", repairs, word["lemma"], extra={"job_id": job.id, "job_type": job.type, "repairs": repairs, "event": "svg_repaired"})
            queue.finish(conn, job.id, {"image_id": int(image_id), "cost_usd": round(result.cost_usd, 6)}, now=now)
            ctx.log.info("generate_svg: word %s → image %s", word["lemma"], image_id, extra={"job_id": job.id, "job_type": job.type, "cost_usd": result.cost_usd, "event": "svg_ready"})
    finally:
        conn.close()


__all__ = ["HOOK_STOP_RE", "SVG_PROMPT_VERSION", "STYLE_TEXT", "build_user_prompt", "handle_generate_svg", "hook_from", "mark_failed", "prompt_for"]
