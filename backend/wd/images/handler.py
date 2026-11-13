"""``fetch_image`` job handler (DESIGN §9 pseudo-code) and the ``wd fetch-image`` / ``wd images-prune`` / ``wd images-retry`` /
``wd images-import`` commands.

    fetch_image {word_id, exclude?: [str], provider?: str, query?: str, retry?: true, requested?: true}      (IoWorker, one job at a time)
      the active image is a 记忆图卡 (memo.is_memo) and the job is not an admin's explicit one (requested, or a provider / query
          override — API.md 69) → nothing is searched: result {"skipped": "memory_card"}, image_state back to 'ready'. A reviewed
          card is never traded for a stock picture by 换一张, a retry or a content re-generation (docs/MEMORY_CARDS_DESIGN.md §3.6).
          A learner's 不合适 on a card queues no fetch at all (it is only recorded, API.md 28); the admin's resolution of that
          report with refetch_image (API.md 71) rejects the card first, so the fetch it queues finds no card and is not held
          back; `wd fetch-image` is the operator's own decision
      function word (style.skip_image: dominant pos ∈ {prep, conj, det, pron, art, int, inf}) and no admin provider/query
          → no provider request, no SVG (PLAN §5.1 C5): image_state = 'failed', result skipped "function word: card only";
            an image that is already active (an earlier photo, an admin-requested SVG) is kept and image_state stays 'ready',
            result skipped "function word: current image kept" — the gate never contradicts a live active_image_id
      style = style.style_for(word, cfg)                      (kid iff the word's stage code ∈ WD_IMAGE_KID_STAGES; default: never)
      keywords = clean_keywords(query) or clean_keywords(content.image_keywords[:3]) — the lemma's own tokens pass the
          non-photo blocklist; an admin query dropped by the shape rule / blocklist is logged (query_ignored) and the
          content keywords are used; [lemma] only when style.allows_bare_lemma (never for an adverb or a function word)
      rounds = (kid, chain minus pexels), (neutral, chain)  when style is kid and no admin provider; else one round
      for round in rounds: for kw in keywords: for provider in chain
          (skip Openverse / Pixabay / Pexels at priority ≥ 90 — PREWARM_SKIP_PROVIDERS; skip when quota.allow is False):
          cands = provider.search(kw, 10, style=round); quota.record(provider)   (any provider failure is counted and skipped)
          for best in select.rank(cands, kw, exclude, allow=tokens(kw), style=round)[:3]:
              img = fetch.download_and_store(best) → activate → done
      all failed, image still active (换一张 found nothing new) → kept, image_state = 'ready' — never an SVG over a photo
      all failed, no image → generate_svg enqueued when WD_SVG_VIA_CLAUDE=1, priority < 90 and the word is studied;
                             words.image_state = 'failed' (the template card is served; the SVG replaces it when it lands)
      a failed word is fetched again by the retry rules (service.retry_failed_studied: nightly, ≥ 6 h apart, ≤ 3 per
          30 days, only while studied — the job then carries retry: true, which this handler ignores) or, after a provider
          outage, by the operator's library-wide sweep `wd images-retry --since ISO` (service.retry_failed_since: every
          failed word whose only attempt since then found no photo, at priority 90 — Wikimedia only, no SVG, no retry flag)

``wd images-import DIR --manifest FILE [--dry-run] [--only LEMMA …]`` is how 记忆图卡 enter (docs/MEMORY_CARDS_DESIGN.md §3.5): the
cards are drawn and reviewed offline in ``studio/`` — no job, no provider, no Claude call here. ``FILE`` is
``{"prompt_version": "memo-1", "model": "…", "cards": {"<lemma>": {"alt_zh", "hook_zh", "note_zh"}}}`` and the picture of a lemma is
``DIR/<lemma>.svg`` (the lemma as ``words.lemma`` stores it — lower-case, single spaces — with the spaces written ``_``; two keys that
name one word make the manifest unusable). Word by word: the lemma must be a public, unmerged word; ``store.prepare_memo`` cleans the
file (``effects=True``) and checks the card structure and the captions; a card that is already the word's active picture is
``unchanged`` (its captions are still brought up to the manifest's, and its file is written back when ``images/`` lost it); a card an
admin took down after a report (the very picture, ``rejected`` — ``store.retired_memo``) stays down, verdict ``retired``, unless the
lemma is named with ``--only``; anything else is activated by ``store.store_memo`` — the very text that was checked and compared, not
cleaned a second time — and the old picture becomes ``superseded`` and keeps its file. A card that cannot be stored (disk full, the
database locked beyond the retries) is that card's ``rejected: could not store``; the run goes on. It always ends with ``imported /
unchanged / rejected`` and every reason, exit 1 when anything was rejected; ``--dry-run`` validates everything and writes nothing.
``wd images-import --undo FILE`` is the rollback: for every lemma of the manifest whose active picture is a memory card,
``store.undo_memo`` supersedes it and puts the word back on what it showed when the card arrived — its newest earlier picture that is
no card, unless a report had taken that one down; then, and when no earlier file is left, the template card (``image_state`` ``failed``
when the word's fetch chain had run before, else ``none``). A word whose card an admin took down is ``kept`` as it is.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shlex
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Iterable

from .. import db
from ..clock import SYSTEM_CLOCK, now_iso, parse_iso, to_iso
from ..config import ConfigError, Settings, ensure_dirs
from ..interfaces import ImageProvider, Job, ProviderError
from ..jobs import queue
from ..jobs.registry import JobContext, register
from . import fetch, memo, providers, quota, sanitize_svg, select, service, store, style

log = logging.getLogger("wd.images")

SEARCH_LIMIT = 10
CANDIDATES_PER_SEARCH = 3
MAX_KEYWORDS = 3
KEYWORD_RE = re.compile(r"^[A-Za-z][A-Za-z ,'-]{1,40}$")
COOLDOWN_STATUSES = (429, 500, 502, 503, 504)
# Never spent at prewarm priority (≥ 90): Openverse's anonymous daily quota and the keyed providers' terms (Pixabay forbids
# systematic mass downloads) are for words somebody is about to study, not for a speculative warm-up (PLAN §5.1 C8).
PREWARM_SKIP_PROVIDERS: tuple[str, ...] = ("openverse", "pixabay", "pexels")
PREWARM_PRIORITY = 90
KID_ROUND_EXCLUDED_PROVIDERS: tuple[str, ...] = ("pexels",)  # no illustration filter
QUERY_IGNORED_PREFIX = "query ignored (shape/blocklist)"

STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_SVG_QUEUED = "svg_queued"
SKIPPED_MEMORY_CARD = service.SKIPPED_MEMORY_CARD  # result_json {"skipped": "memory_card"}: a fetch that left a 记忆图卡 in place (docs/MEMORY_CARDS_DESIGN.md §3.6); service.chain_was_tried reads it back
MEMO_FROM_VERSION = 21  # migration 0021: word_images.hook_zh / note_zh


@dataclass
class FetchOutcome:
    status: str
    image_id: int | None = None
    provider: str | None = None
    ref: str | None = None
    query: str | None = None
    svg_job_id: int | None = None
    attribution: str | None = None
    landing_url: str | None = None
    file_path: str | None = None
    detail: str = ""

    def as_result(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


def clean_keywords(values: Iterable[Any], lemma: str, *, allow_lemma: bool = True) -> tuple[list[str], list[str]]:
    """``(kept, dropped)``: the keywords that pass the shape rule and the blocklist (lower-cased, de-duplicated, at most
    :data:`MAX_KEYWORDS`) and the ones that did not. The lemma's own tokens are allowed through the non-photo list, so the
    card for ``map`` may search "world map" while "bar chart" for ``apple`` is dropped (PLAN §5.1 C5). When nothing is
    kept, ``kept`` is ``[lemma]`` if ``allow_lemma`` (``style.allows_bare_lemma``: not for adverbs and function words) else
    ``[]`` — the caller then skips the provider rounds."""
    kept: list[str] = []
    dropped: list[str] = []
    allow = select.keyword_tokens(lemma)
    for v in values:
        if not isinstance(v, str):
            continue
        kw = " ".join(v.strip().split())
        if not KEYWORD_RE.match(kw) or select.is_blocked(kw, allow=allow):
            dropped.append(kw)
            continue
        kw = kw.lower()
        if kw not in kept and len(kept) < MAX_KEYWORDS:
            kept.append(kw)
    if not kept and allow_lemma:
        kept = [lemma]
    return kept, dropped


def _load_content(conn: sqlite3.Connection, content_id: int | None) -> dict[str, Any] | None:
    if content_id is None:
        return None
    row = conn.execute("SELECT content_json FROM word_contents WHERE id = ? AND status = 'active'", (int(content_id),)).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _used_refs(conn: sqlite3.Connection, word_id: int) -> set[str]:
    rows = conn.execute(
        "SELECT provider, provider_ref FROM word_images WHERE status = 'active' AND provider_ref IS NOT NULL AND word_id != ?",
        (int(word_id),),
    ).fetchall()
    return {f"{p}:{r}" for p, r in rows}


def _svg_allowed(cfg: Settings, priority: int, allow_svg: bool) -> bool:
    """The automatic SVG card after every photo source failed: a learner-time fetch (priority < 90) — never in AI mode ``split``,
    where a learner's action queues no Claude work (the template card serves; the admin's explicit `claude_svg` request bypasses this)."""
    return bool(
        allow_svg
        and cfg.svg_via_claude
        and priority < PREWARM_PRIORITY
        and cfg.ai_enabled
        and cfg.ai_svg_daily_budget_usd > 0
        and str(getattr(cfg, "ai_provider", "") or "") != "split"
    )


def _with_prefix(prefix: str, detail: str) -> str:
    """``detail`` behind the ``query ignored`` prefix when there is one (``"query ignored (…); no acceptable photo …"``)."""
    if not prefix:
        return detail
    return f"{prefix}; {detail}" if detail else prefix


def search_rounds(cfg: Settings, style_: str, provider: str | None) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """The ``(style, provider names)`` rounds of one fetch (PLAN §5.1 C8): an explicit admin provider is one round in the
    word's style; a ``kid`` word tries the illustration round over the chain without Pexels (no illustration filter) and
    then the ordinary photo round; everything else is the single neutral round of the default chain."""
    names: tuple[str, ...] = (provider,) if provider else tuple(cfg.image_providers)
    if style_ == style.STYLE_KID and not provider:
        kid_names = tuple(p for p in cfg.image_providers if p not in KID_ROUND_EXCLUDED_PROVIDERS)
        return ((style.STYLE_KID, kid_names), (style.STYLE_NEUTRAL, names))
    return ((style_, names),)


def _search_round(
    ctx: JobContext,
    conn: sqlite3.Connection,
    word_id: int,
    chain: list[ImageProvider],
    keywords: list[str],
    *,
    round_style: str,
    priority: int,
    excluded: set[str],
    used_refs: set[str],
    alt_zh: str | None,
    now: str,
) -> FetchOutcome | None:
    """One round of the DESIGN §9 loop (every keyword × every provider in ``chain``, in that order); the ``ready`` outcome
    of the first acceptable, downloadable candidate, or None when the round found nothing. Provider trouble is counted on
    the provider (quota / cooldown / error) and never raises."""
    cfg = ctx.cfg
    for kw in keywords:
        allow = select.keyword_tokens(kw)
        for p in chain:
            if int(priority) >= PREWARM_PRIORITY and p.name in PREWARM_SKIP_PROVIDERS:
                continue  # prewarm never spends the quota-bound / keyed providers
            blocked = quota.check(conn, p.name, cfg, now)
            if blocked:
                log.info("provider %s skipped (%s)", p.name, blocked, extra={"provider": p.name, "event": "provider_skipped"})
                continue
            try:
                cands = p.search(kw, SEARCH_LIMIT, style=round_style)
            except ProviderError as e:
                quota.record(conn, p.name, now)
                if e.status is None or e.status in COOLDOWN_STATUSES:
                    until = quota.cooldown(conn, p.name, now, quota.cooldown_seconds(p.name, e), str(e))
                    log.warning("provider %s failed (%s); cooldown until %s", p.name, e, until, extra={"provider": p.name, "event": "provider_cooldown"})
                else:
                    quota.mark_error(conn, p.name, now, str(e))
                    log.warning("provider %s failed: %s", p.name, e, extra={"provider": p.name, "event": "provider_error"})
                continue
            except Exception as e:  # noqa: BLE001 — a response the parser chokes on is provider trouble, not a job crash
                quota.record(conn, p.name, now)  # the request was made: it must count against the quota
                quota.mark_error(conn, p.name, now, f"{e.__class__.__name__}: {e}"[:500])
                log.exception("provider %s crashed on %r; trying the next one", p.name, kw, extra={"provider": p.name, "event": "provider_error"})
                continue
            quota.record(conn, p.name, now)
            quota.mark_ok(conn, p.name, now)
            for best in select.rank(cands, kw, excluded, used_refs=used_refs, allow=allow, style=round_style)[:CANDIDATES_PER_SEARCH]:
                stored = fetch.download_and_store(best, cfg)
                if stored is None or stored.sha256 in excluded:
                    continue
                image_id = store.activate_candidate(conn, word_id, best, stored, query=kw, alt_zh=alt_zh, score=best.extra.get("score"), now=now)
                return FetchOutcome(
                    STATUS_READY,
                    image_id=image_id,
                    provider=best.provider,
                    ref=best.ref,
                    query=kw,
                    attribution=store.attribution_line(best.title, best.creator, best.license, sentence=best.extra.get("attribution") if best.provider == "openverse" else None),
                    landing_url=best.landing_url or None,
                    file_path=stored.file_path,
                )
    return None


def fetch_for_word(
    ctx: JobContext,
    conn: sqlite3.Connection,
    word_id: int,
    *,
    exclude: Iterable[str] = (),
    provider: str | None = None,
    query: str | None = None,
    priority: int = 20,
    allow_svg: bool = True,
    now: str | None = None,
) -> FetchOutcome:
    """Run the DESIGN §9 chain for one word and activate the first acceptable photo. Never raises for provider trouble."""
    cfg = ctx.cfg
    now = now or ctx.now()
    row = conn.execute(
        "SELECT id, lemma, display, kind, pos, stage_min, image_state, active_image_id, active_content_id FROM words WHERE id = ?",
        (int(word_id),),
    ).fetchone()
    if row is None:
        return FetchOutcome(STATUS_SKIPPED, detail="word not found")
    word: dict[str, Any] = {k: row[k] for k in row.keys()}  # a Mapping for images.style (sqlite3.Row has no .get)
    if not cfg.images_enabled:
        return FetchOutcome(STATUS_SKIPPED, detail="images disabled")
    lemma = str(word["lemma"])
    style_ = style.style_for(word, cfg)
    explicit = bool(provider) or bool(query and query.strip())
    if not explicit and style.skip_image(word):
        # PLAN §5.1 C5 / D-images-9: a preposition, conjunction, determiner … has no picture worth a request or an SVG
        # call; the template card is the design. An admin override (provider / query) is an explicit decision and wins.
        # An image that is already active (an admin-requested SVG, a photo fetched before the gate existed — `despite`
        # on the live DB) is kept and the state goes back to `ready` (enqueue_fetch set `queued`), exactly like the chain
        # tail below: `failed` beside a live active_image_id would under-count in diag and never heal, because the
        # nightly retry skips function words (impl-review S5b F-1).
        has_active = service.active_image_row(conn, word_id) is not None
        store.set_image_state(conn, word_id, STATUS_READY if has_active else STATUS_FAILED, now=now)
        return FetchOutcome(STATUS_SKIPPED, detail="function word: current image kept" if has_active else "function word: card only")
    content = _load_content(conn, word["active_content_id"])
    alt_zh = None
    if content and isinstance(content.get("image_alt_zh"), str):
        alt_zh = content["image_alt_zh"].strip()[:200] or None
    detail_prefix = ""
    keywords: list[str] = []
    if query and query.strip():
        keywords, dropped = clean_keywords([query], lemma, allow_lemma=False)
        if dropped:
            # API.md 69 stays a 202: the override is reported, not refused — the content keywords are used instead
            log.warning("admin query ignored for word %d: %r", int(word_id), dropped[0], extra={"event": "query_ignored", "word_id": int(word_id)})
            detail_prefix = QUERY_IGNORED_PREFIX
    if not keywords:
        keywords, _ = clean_keywords((content or {}).get("image_keywords") or [], lemma, allow_lemma=style.allows_bare_lemma(word))

    if provider == "claude_svg":
        if not cfg.ai_enabled:
            return FetchOutcome(STATUS_SKIPPED, detail=_with_prefix(detail_prefix, "AI disabled; no SVG job"))
        # An explicit request (API.md 69, `wd fetch-image --provider claude_svg`) draws even over an active photo, so it
        # carries `requested` on its own live key: folded into a fallback `svg:<id>` job it would keep that job's payload
        # (the dedupe UPSERT never rewrites payload_json) and the handler would skip it as soon as a photo is active.
        svg_job = ctx.enqueue(conn, "generate_svg", {"word_id": int(word_id), "requested": True}, dedupe_key=f"svg:{int(word_id)}:req", priority=int(priority), now=now)
        return FetchOutcome(STATUS_SVG_QUEUED, svg_job_id=svg_job, detail=_with_prefix(detail_prefix, "generate_svg enqueued on request"))

    excluded = {str(x) for x in exclude if x} | set(service.exclude_for(conn, word_id, statuses=("rejected",)))
    used_refs = _used_refs(conn, word_id)
    if keywords:  # an adverb without a usable content keyword searches nothing (no bare lemma) and goes straight to the SVG / card rule
        for round_style, names in search_rounds(cfg, style_, provider):
            if not names:
                continue  # a kid round over a Pexels-only chain: build_chain(cfg, ()) would fall back to the whole default chain
            try:
                chain = providers.build_chain(cfg, names)
            except ValueError as e:
                return FetchOutcome(STATUS_SKIPPED, detail=_with_prefix(detail_prefix, str(e)))
            outcome = _search_round(
                ctx, conn, word_id, chain, keywords, round_style=round_style, priority=int(priority), excluded=excluded, used_refs=used_refs, alt_zh=alt_zh, now=now
            )
            if outcome is not None:
                outcome.detail = _with_prefix(detail_prefix, outcome.detail)
                return outcome
    else:
        log.info("word %d: no usable image keyword and no bare-lemma search (pos %s); no provider request", int(word_id), word["pos"], extra={"event": "image_no_keywords"})

    # DESIGN §9 / §0.1 row 7: the Claude SVG stands in only when NO acceptable photo exists. A 换一张 that finds nothing
    # new keeps the current image — it is never traded for a drawing, and the SVG sub-cap is not spent on a word that
    # already has a picture. (The report flow is unaffected: reject_active_image clears active_image_id first.)
    has_active = service.active_image_row(conn, word_id) is not None
    svg_job_id = None
    if not has_active and _svg_allowed(cfg, int(priority), allow_svg) and service.word_is_studied(conn, word_id, now):
        svg_job_id = ctx.enqueue(conn, "generate_svg", {"word_id": int(word_id)}, dedupe_key=f"svg:{int(word_id)}", priority=int(priority), now=now)
    store.set_image_state(conn, word_id, STATUS_READY if has_active else STATUS_FAILED, now=now)
    return FetchOutcome(
        STATUS_FAILED, svg_job_id=svg_job_id, detail=_with_prefix(detail_prefix, "no acceptable photo from any provider" + (" (current image kept)" if has_active else ""))
    )


def explicit_request(payload: dict[str, Any]) -> bool:
    """Is this ``fetch_image`` payload an admin's explicit decision about the word's picture? ``requested: true`` (API.md 69,
    ``service.admin_refetch``) or a ``provider`` / ``query`` override — the same notion that lets a function word be fetched.
    Only such a job may replace a 记忆图卡."""
    provider, query = payload.get("provider"), payload.get("query")
    return payload.get("requested") is True or (isinstance(provider, str) and bool(provider)) or (isinstance(query, str) and bool(query.strip()))


@register("fetch_image")
def handle_fetch_image(ctx: JobContext, jobs: list[Job]) -> None:
    """Handler contract: every job ends ``done`` (``result_json`` = :class:`FetchOutcome`, or ``{"skipped": "memory_card"}`` for a
    job that left a 记忆图卡 in place — the ``generate_svg`` spelling of a skip) or ``fail``ed."""
    for job in jobs:
        conn = ctx.db()
        try:
            payload = job.payload or {}
            try:
                word_id = int(payload["word_id"])
            except (KeyError, TypeError, ValueError):
                queue.fail(conn, job.id, "fetch_image: payload has no word_id", now=ctx.now())
                continue
            raw_exclude = payload.get("exclude") or []
            exclude = [str(x) for x in raw_exclude if isinstance(x, (str, int))] if isinstance(raw_exclude, list) else []
            provider = payload.get("provider") if isinstance(payload.get("provider"), str) else None
            query = payload.get("query") if isinstance(payload.get("query"), str) else None
            try:
                # docs/MEMORY_CARDS_DESIGN.md §3.6: a 换一张 from a client that still shows the button, an automatic retry, a
                # content job's fetch — none of them may trade a reviewed 记忆图卡 for whatever the providers return
                keep_card = not explicit_request(payload) and memo.is_memo(service.active_image_row(conn, word_id))
                outcome = None if keep_card else fetch_for_word(ctx, conn, word_id, exclude=exclude, provider=provider, query=query, priority=job.priority, now=ctx.now())
            except Exception as e:  # noqa: BLE001 — a provider/DB hiccup must not take the IoWorker down
                log.exception("fetch_image job %d crashed", job.id, extra={"job_id": job.id, "job_type": job.type})
                if queue.fail(conn, job.id, f"{e.__class__.__name__}: {e}"[:1000], now=ctx.now()) == "dead":
                    # enqueue_fetch set `queued`; a job that dies on its last attempt must not leave the word there for ever —
                    # nothing else resets it (the nightly retry selects `failed`, requeue_dead_once revives only content/lookup
                    # jobs). Like ai.svg.mark_failed: `failed` so the C7 retry rules pick the word up, or back to `ready` when
                    # an image is active (PLAN §5.1 C7; impl-review final M-3)
                    has_active = service.active_image_row(conn, word_id) is not None
                    store.set_image_state(conn, word_id, STATUS_READY if has_active else STATUS_FAILED, now=ctx.now())
                continue
            if outcome is None:
                # the card stays active; enqueue_fetch wrote `queued`, so the state goes back to `ready` like on every kept image
                store.set_image_state(conn, word_id, STATUS_READY, now=ctx.now())
                queue.finish(conn, job.id, {"skipped": SKIPPED_MEMORY_CARD}, now=ctx.now())
                log.info("fetch_image skipped for word %d (memory card kept)", word_id, extra={"job_id": job.id, "job_type": job.type, "event": "image_skipped"})
                continue
            queue.finish(conn, job.id, outcome.as_result(), now=ctx.now())
            log.info(
                "fetch_image %s for word %d (%s)", outcome.status, word_id, outcome.detail or outcome.provider,
                extra={"job_id": job.id, "job_type": job.type, "provider": outcome.provider, "event": f"image_{outcome.status}"},
            )
        finally:
            conn.close()


# --------------------------------------------------------------------------------------------- CLI
def _settings() -> Settings | None:
    try:
        return Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        return None


def resolve_word_id(conn: sqlite3.Connection, text: str) -> int | None:
    """A numeric id, else the lemma (lower-case, single spaces; ``merged_into_word_id`` followed), else a display match."""
    t = text.strip()
    if t.isdigit():
        row = conn.execute("SELECT id, merged_into_word_id FROM words WHERE id = ?", (int(t),)).fetchone()
    else:
        key = " ".join(t.lower().split())
        row = conn.execute("SELECT id, merged_into_word_id FROM words WHERE lemma = ?", (key,)).fetchone()
        if row is None:
            row = conn.execute("SELECT id, merged_into_word_id FROM words WHERE display = ? COLLATE NOCASE ORDER BY id LIMIT 1", (t,)).fetchone()
    if row is None:
        return None
    return int(row["merged_into_word_id"] or row["id"])


def cmd_fetch_image(args: argparse.Namespace) -> int:
    cfg = _settings()
    if cfg is None:
        return 2
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    try:
        word_id = resolve_word_id(conn, args.word)
        if word_id is None:
            print(f"wd fetch-image: word {args.word!r} not found", file=sys.stderr)
            return 1
        ctx = JobContext(db=lambda: db.connect(cfg.db_path), cfg=cfg, clock=SYSTEM_CLOCK, enqueue=queue.enqueue, log=log, worker_id="cli")
        outcome = fetch_for_word(ctx, conn, word_id, provider=args.provider, query=args.query, priority=args.priority, allow_svg=not args.no_svg)
        row = conn.execute("SELECT lemma, display FROM words WHERE id = ?", (word_id,)).fetchone()
        print(f"word: {row['display']} (id {word_id})")
        print(f"status: {outcome.status}")
        if outcome.status == STATUS_READY:
            print(f"provider: {outcome.provider} ref {outcome.ref} (query {outcome.query!r})")
            print(f"attribution: {outcome.attribution}")
            if outcome.landing_url:
                print(f"source: {outcome.landing_url}")
            print(f"file: {cfg.images_dir / outcome.file_path}")
            meta = service.image_meta(conn, word_id)
            print(f"url: {meta['url']} ({meta['width']}×{meta['height']}, {meta['mime']})")
            return 0
        if outcome.detail:
            print(f"detail: {outcome.detail}")
        if outcome.svg_job_id:
            print(f"generate_svg job: {outcome.svg_job_id}")
        # exit 1 only when the chain was run and found nothing; a skip (function word, images disabled) is the design's answer
        return 0 if outcome.status in (STATUS_SVG_QUEUED, STATUS_SKIPPED) else 1
    finally:
        conn.close()


def prune_unused(conn: sqlite3.Connection, cfg: Settings, unused_days: int, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """``wd images-prune``: drop the image rows of words in no bank and no batch for ``unused_days`` days (and older
    than that), reset those words to the card, then delete every stored file no row references any more."""
    now = now or now_iso()
    cutoff = to_iso(parse_iso(now) - timedelta(days=max(0, int(unused_days))))
    cutoff_date = cutoff[:10]
    word_ids = [
        int(r[0])
        for r in conn.execute(
            "SELECT DISTINCT wi.word_id FROM word_images wi JOIN words w ON w.id = wi.word_id "
            "WHERE wi.created_at < :cutoff "
            "  AND NOT EXISTS (SELECT 1 FROM user_words uw WHERE uw.word_id = wi.word_id AND uw.state IN ('new','learning')) "
            "  AND NOT EXISTS (SELECT 1 FROM push_items pi JOIN push_batches pb ON pb.id = pi.batch_id "
            "                  WHERE pi.word_id = wi.word_id AND pb.local_date >= :cutoff_date) "
            "  AND NOT EXISTS (SELECT 1 FROM word_images wi2 WHERE wi2.word_id = wi.word_id AND wi2.created_at >= :cutoff)",
            {"cutoff": cutoff, "cutoff_date": cutoff_date},
        )
    ]
    placeholders = ",".join("?" * len(word_ids))
    rows_doomed = int(conn.execute(f"SELECT COUNT(*) FROM word_images WHERE word_id IN ({placeholders})", word_ids).fetchone()[0]) if word_ids else 0
    # files referenced by a row of any word that is NOT pruned must stay (a sha may serve several words)
    if word_ids:
        keep = {str(r[0]) for r in conn.execute(f"SELECT DISTINCT file_path FROM word_images WHERE word_id NOT IN ({placeholders})", word_ids)}
    else:
        keep = store.referenced_files(conn)
    if word_ids and not dry_run:
        with db.tx(conn):
            for wid in word_ids:
                conn.execute("DELETE FROM word_images WHERE word_id = ?", (wid,))
                conn.execute("UPDATE words SET active_image_id = NULL, image_state = 'none', updated_at = ? WHERE id = ?", (now, wid))
    rows_deleted = rows_doomed
    orphans = [p for p in store.list_files(cfg) if p not in keep]
    removed = store.remove_files(cfg, orphans, dry_run=dry_run)
    return {"words": len(word_ids), "rows": rows_deleted, "files": len(removed), "removed": removed, "dry_run": dry_run}


def cmd_images_prune(args: argparse.Namespace) -> int:
    cfg = _settings()
    if cfg is None:
        return 2
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    try:
        result = prune_unused(conn, cfg, args.unused_days, dry_run=args.dry_run)
    finally:
        conn.close()
    verb = "would remove" if result["dry_run"] else "removed"
    print(f"images-prune: {result['words']} word(s) unused for {args.unused_days} day(s); {verb} {result['rows']} image row(s) and {result['files']} file(s)")
    return 0


def cmd_images_retry(args: argparse.Namespace) -> int:
    """``wd images-retry [--limit N] [--dry-run] [--since ISO]``: the nightly failed-image sweep by hand, or with ``--since``
    the library-wide provider-outage sweep (DEPLOY §9); prints the words."""
    cfg = _settings()
    if cfg is None:
        return 2
    since: str | None = None
    if args.since is not None:
        try:
            since = to_iso(parse_iso(args.since))
        except (TypeError, ValueError):
            print(f"images-retry: --since wants an ISO-8601 instant such as 2026-11-11T12:00:00Z, not {args.since!r}")
            return 2
    ensure_dirs(cfg)
    if not cfg.images_enabled:
        print("images-retry: images are disabled (WD_IMAGES_ENABLED=0); nothing to requeue")
        return 0
    conn = db.connect(cfg.db_path)
    try:
        if since is not None:
            word_ids = service.retry_failed_since(conn, now_iso(), since=since, limit=args.limit, dry_run=args.dry_run)
        else:
            word_ids = service.retry_failed_studied(conn, now_iso(), limit=args.limit, priority=service.RETRY_NIGHTLY_PRIORITY, dry_run=args.dry_run)
        lemma_of = {int(r[0]): str(r[1]) for r in conn.execute(f"SELECT id, lemma FROM words WHERE id IN ({','.join('?' * len(word_ids))})", word_ids)} if word_ids else {}
        lemmas = [lemma_of.get(w, str(w)) for w in word_ids]  # in sweep order (oldest failure first), like the nightly run
    finally:
        conn.close()
    verb = "would requeue" if args.dry_run else "requeued"
    if since is not None:
        print(
            f"images-retry: {verb} {len(word_ids)} failed-image word(s) whose only fetch since {since} found no photo (limit {args.limit}; "
            f"priority {service.OUTAGE_SWEEP_PRIORITY} = Wikimedia only, no SVG, not an automatic retry; function words and words with a live fetch job excluded)"
        )
    else:
        print(
            f"images-retry: {verb} {len(word_ids)} failed-image word(s) being studied (limit {args.limit}; "
            f">= {service.RETRY_MIN_AGE_H} h since the last attempt, <= {service.RETRY_MAX_AUTO_30D} automatic retries per 30 days, function words excluded)"
        )
    for lemma in lemmas:
        print(f"  {lemma}")
    return 0


# ------------------------------------------------------------------- wd images-import (docs/MEMORY_CARDS_DESIGN.md §3.5)
class ManifestError(ValueError):
    """The manifest of ``wd images-import`` cannot be used at all (unreadable, not the documented shape) — exit 2, nothing done."""


def load_manifest(path: str | Path) -> dict[str, Any]:
    """``{"prompt_version", "model", "cards": {lemma: {"alt_zh"?, "hook_zh"?, "note_zh"?}}}`` read and shape-checked; the
    per-card content (lengths, the version label) is ``store.prepare_memo``'s to judge, card by card. Keys are matched to
    ``words.lemma`` in normalised form (:func:`normalise_lemma`), so two keys that differ only in case or spacing name ONE word:
    worked in turn they would import it twice — the last hook winning, a second file silently superseding the first — and such
    a manifest is refused whole. So is one that holds half a surrogate pair (``"\\ud83c"`` — legal JSON, not text): it can be
    written neither into a file nor into the database, and would end the real run with ``UnicodeEncodeError`` in the middle of
    a batch the dry run had passed."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except OSError as e:
        raise ManifestError(f"cannot read {path}: {e.strerror or e}") from e
    except UnicodeEncodeError as e:
        raise ManifestError(f"{path} holds a lone surrogate escape (\\ud800–\\udfff without its pair), which is not text that can be stored: {e.object[max(0, e.start - 12):e.end]!r}") from e
    except (UnicodeDecodeError, ValueError) as e:
        raise ManifestError(f"{path} is not UTF-8 JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("cards"), dict) or not data["cards"]:
        raise ManifestError(f'{path} must be {{"prompt_version": "memo-1", "model": "…", "cards": {{"<lemma>": {{…}}}}}} with at least one card')
    for key in ("prompt_version", "model"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ManifestError(f"{path}: {key!r} must be a non-empty string")
    seen: dict[str, str] = {}
    for lemma, card in data["cards"].items():
        if not isinstance(card, dict):
            raise ManifestError(f"{path}: cards[{lemma!r}] must be an object with alt_zh / hook_zh / note_zh")
        first = seen.setdefault(normalise_lemma(lemma), lemma)
        if first != lemma:
            raise ManifestError(f"{path}: cards[{first!r}] and cards[{lemma!r}] name the same word")
    return data


def manifest_lemmas(manifest: dict[str, Any], only: Iterable[str] | None) -> tuple[list[str], list[str]]:
    """``(the manifest keys to work on, the --only values the manifest does not have)``; without ``--only`` every key, in file order."""
    cards = manifest["cards"]
    if not only:
        return list(cards), []
    by_lemma = {normalise_lemma(key): key for key in cards}
    chosen: list[str] = []
    missing: list[str] = []
    for value in only:
        key = by_lemma.get(normalise_lemma(value))
        if key is None:
            missing.append(value)
        elif key not in chosen:
            chosen.append(key)
    return chosen, missing


def normalise_lemma(text: str) -> str:
    """A manifest key the way ``words.lemma`` is stored: lower-case, single spaces (``Ice  Cream`` → ``ice cream``)."""
    return " ".join(str(text).lower().split())


def card_file(directory: Path, key: str) -> Path | None:
    """``DIR/<lemma>.svg`` with the lemma's spaces written ``_``; None for a key that could name a file outside ``DIR``. The name
    is built from the lemma the key is looked up as, not from the key's spelling: ``Ice  Cream`` reads ``ice_cream.svg`` and
    ``Monday`` reads ``monday.svg`` on every file system, not only on the Mac's case-insensitive one."""
    name = normalise_lemma(key).replace(" ", "_")
    if not name or name.startswith(".") or "/" in name or "\\" in name or "\0" in name:
        return None
    return directory / f"{name}.svg"


def public_word(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    """The public, unmerged word a manifest key names (§3.5) — a private custom word or a merged duplicate never gets a card."""
    return conn.execute(
        "SELECT id, lemma, display FROM words WHERE lemma = ? AND is_public = 1 AND merged_into_word_id IS NULL", (normalise_lemma(key),)
    ).fetchone()


@dataclass
class ImportReport:
    imported: list[str]
    unchanged: list[str]
    rejected: list[tuple[str, str]]  # (lemma, every reason joined)
    recaptioned: list[str]  # among `unchanged`: the picture was the same, its captions were brought up to the manifest's
    restored: list[str] = field(default_factory=list)  # among `unchanged`: the card's file was missing from images/ and is written back (dry run: would be)
    retired: list[tuple[str, int]] = field(default_factory=list)  # (lemma, image id): this very card was taken down by an admin after a report — left down, not an error


def import_cards(conn: sqlite3.Connection, cfg: Settings, directory: Path, manifest: dict[str, Any], *, only: Iterable[str] | None = None, dry_run: bool = False, now: str | None = None) -> ImportReport:
    """The loop of ``wd images-import`` (module docstring): one verdict per manifest lemma, each card in its own transaction.
    ``dry_run`` runs every check — the word, the file, the sanitiser, the structure, the captions, the comparison with the
    active picture and with a card an admin took down — and writes nothing. A failure to store one card (``OSError``,
    ``sqlite3.Error``) is that card's verdict and never ends the run: the cards before it are committed and live, and the
    operator needs the summary to know which."""
    now = now or now_iso()
    report = ImportReport([], [], [], [])
    keys, missing = manifest_lemmas(manifest, only)
    for value in missing:
        report.rejected.append((value, "not in the manifest"))
    for key in keys:
        entry = manifest["cards"][key]
        word = public_word(conn, key)
        if word is None:
            report.rejected.append((key, "unknown lemma (no public, unmerged word)"))
            continue
        file = card_file(directory, key)
        if file is None or not file.is_file():
            report.rejected.append((key, f"no file {file or directory / (key.replace(' ', '_') + '.svg')}"))  # the path that was looked for
            continue
        try:
            if file.stat().st_size > sanitize_svg.MAX_BYTES:
                raise store.MemoRejected([f"the file is {file.stat().st_size} bytes, the sanitiser takes at most {sanitize_svg.MAX_BYTES}"])
            card = store.prepare_memo(
                file.read_text(encoding="utf-8"), str(word["display"]), alt_zh=entry.get("alt_zh"), hook_zh=entry.get("hook_zh"), note_zh=entry.get("note_zh"),
                model=manifest["model"], prompt_version=manifest["prompt_version"],
            )
        except (OSError, UnicodeDecodeError) as e:
            report.rejected.append((key, f"cannot read {file}: {e}"))
            continue
        except store.MemoRejected as e:
            report.rejected.append((key, "; ".join(e.problems)))
            continue
        word_id = int(word["id"])
        try:
            active = service.active_image_row(conn, word_id)
            on_disk = store.stored_memo(active, card)
            if on_disk is not None:  # the word's active picture is this very card
                restored = store.restore_memo_file(cfg, on_disk, dry_run=dry_run)  # "run the import again" is the repair for a card whose file images/ lost
                recaptioned = store.set_memo_captions(conn, int(active["id"]), card, dry_run=dry_run)  # a corrected hook must not need a redrawn picture to arrive
                report.unchanged.append(key)  # only now: a card whose file or captions could not be written is `rejected` below, never both
                if recaptioned:
                    report.recaptioned.append(key)
                if restored:
                    report.restored.append(key)
                continue
            # a learner's 不合适 only records a report; an admin who then resolved it with refetch_image took THIS picture down. A
            # whole-manifest run (the next batch's) must not bring it back as one more `imported` line — naming the word does
            retired = None if only else store.retired_memo(conn, word_id, card)
            if retired is not None:
                report.retired.append((key, int(retired["id"])))
                continue
            if not dry_run:
                store.store_memo(conn, cfg, word_id, card, now=now)  # the very text that was checked and compared: not cleaned a second time
        except (OSError, sqlite3.Error) as e:  # disk full, images/ not writable, the database locked beyond the BEGIN IMMEDIATE retries
            report.rejected.append((key, f"could not store: {e}"))
            continue
        report.imported.append(key)
    return report


@dataclass
class UndoReport:
    restored: list[tuple[str, str]]  # (lemma, what is active again: "<provider> image <id>")
    to_card: list[str]
    kept: list[str]  # the active picture is not a memory card: nothing to undo
    unknown: list[str]


def undo_cards(conn: sqlite3.Connection, cfg: Settings, manifest: dict[str, Any], *, only: Iterable[str] | None = None, dry_run: bool = False, now: str | None = None) -> UndoReport:
    """``wd images-import --undo FILE``: ``store.undo_memo`` for every lemma of the manifest (or of ``--only``). A word that goes
    back to the template card gets ``image_state = 'failed'`` when its fetch chain has run before (``service.chain_was_tried``) —
    the state it had before the card, and the only one the retry rules pick a studied word up from — and ``'none'`` otherwise."""
    now = now or now_iso()
    report = UndoReport([], [], [], [])
    keys, missing = manifest_lemmas(manifest, only)
    report.unknown.extend(missing)
    for key in keys:
        word = public_word(conn, key)
        if word is None:
            report.unknown.append(key)
            continue
        verdict, row = store.undo_memo(conn, cfg, int(word["id"]), now=now, dry_run=dry_run, tried=service.chain_was_tried(conn, int(word["id"])))
        if verdict == "restored" and row is not None:
            report.restored.append((key, f"{row['provider']} image {int(row['id'])}"))
        elif verdict == "card":
            report.to_card.append(key)
        else:
            report.kept.append(key)
    return report


def cmd_images_import(args: argparse.Namespace) -> int:
    """``wd images-import DIR --manifest FILE [--dry-run] [--only LEMMA …]`` · ``wd images-import --undo FILE [--dry-run] [--only LEMMA …]``."""
    if bool(args.undo) == bool(args.manifest) or (args.manifest and not args.dir) or (args.undo and args.dir):
        print("wd images-import: pass DIR --manifest FILE to import, or --undo FILE alone to roll an import back", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(args.undo or args.manifest)
    except ManifestError as e:
        print(f"wd images-import: {e}", file=sys.stderr)
        return 2
    directory = Path(args.dir).expanduser() if args.dir else Path()
    if args.manifest and not directory.is_dir():
        print(f"wd images-import: {directory} is not a directory", file=sys.stderr)
        return 2
    cfg = _settings()
    if cfg is None:
        return 2
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    try:
        version = db.current_version(conn)
        if version < MEMO_FROM_VERSION:
            print(f"wd images-import: schema version {version} has no word_images.hook_zh (migration {MEMO_FROM_VERSION:04d}) — run `wd migrate` first", file=sys.stderr)
            return 1
        would = "would be " if args.dry_run else ""
        if args.undo:
            undone = undo_cards(conn, cfg, manifest, only=args.only, dry_run=args.dry_run)
            for lemma, what in undone.restored:
                print(f"  undone     {lemma} → {what} {would}active again")
            for lemma in undone.to_card:
                print(f"  undone     {lemma} → {would}back on the template card (no earlier picture to restore)")
            for lemma in undone.kept:
                print(f"  kept       {lemma}: the active picture is not a memory card")
            for lemma in undone.unknown:
                print(f"  unknown    {lemma}: not in the manifest or no public, unmerged word")
            n = len(undone.restored) + len(undone.to_card)
            print(
                f"images-import --undo: {n} memory card(s) {would}superseded ({len(undone.restored)} word(s) back on the previous picture, "
                f"{len(undone.to_card)} on the template card), {len(undone.kept)} kept, {len(undone.unknown)} unknown" + (" — dry run, nothing written" if args.dry_run else "")
            )
            return 1 if undone.unknown else 0
        report = import_cards(conn, cfg, directory, manifest, only=args.only, dry_run=args.dry_run)
    finally:
        conn.close()
    for lemma in report.imported:
        print(f"  imported   {lemma}" if not args.dry_run else f"  ok         {lemma} (would be imported)")
    for lemma in report.unchanged:
        notes = [f"captions {would}updated"] if lemma in report.recaptioned else []
        if lemma in report.restored:
            notes.append("file missing from images/ — a real run restores it" if args.dry_run else "file restored")
        print(f"  unchanged  {lemma}" + (f" ({'; '.join(notes)})" if notes else ""))
    for lemma, image_id in report.retired:
        print(f"  retired    {lemma}: an admin took this very card down after a report (image {image_id}) — left as it is; pass --only {shlex.quote(lemma)} to bring it back")
    for lemma, reason in report.rejected:
        print(f"  rejected   {lemma}: {reason}")
    details = [f"{len(report.recaptioned)} with new captions"] if report.recaptioned else []
    if report.restored:
        details.append(f"{len(report.restored)} with a missing file" if args.dry_run else f"{len(report.restored)} with the file restored")
    unchanged = f" ({', '.join(details)})" if details else ""
    retired = f", {len(report.retired)} retired" if report.retired else ""  # not an error: the exit code stays the rejections'
    print(
        f"images-import: {len(report.imported)} {would}imported, {len(report.unchanged)} unchanged{unchanged}, {len(report.rejected)} rejected{retired} "
        f"({manifest['prompt_version']}, {manifest['model']})" + (" — dry run, nothing written" if args.dry_run else "")
    )
    return 1 if report.rejected else 0


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("fetch-image", help="fetch a photo for one word now and print the attribution (manual check; DEPLOY §9)")
    p.add_argument("word", help="lemma or word id")
    p.add_argument("--provider", choices=[*providers.PHOTO_PROVIDERS, "claude_svg"], default=None, help="use only this provider (also bypasses the function-word gate)")
    p.add_argument("--query", default=None, help="search keyword instead of the content image_keywords / lemma")
    p.add_argument("--priority", type=int, default=10, help=f"job priority semantics (>= {PREWARM_PRIORITY} skips {', '.join(PREWARM_SKIP_PROVIDERS)}); default 10")
    p.add_argument("--no-svg", action="store_true", help="never enqueue a generate_svg job when every provider fails")
    p.set_defaults(func=cmd_fetch_image)

    p = sub.add_parser("images-prune", help="delete cached image files of words in no bank and no batch for N days")
    p.add_argument("--unused-days", type=int, required=True, help="age threshold in days")
    p.add_argument("--dry-run", action="store_true", help="report only")
    p.set_defaults(func=cmd_images_prune)

    p = sub.add_parser("images-retry", help="requeue fetch_image for failed-image words somebody is studying (the nightly 03:30 sweep by hand); --since ISO: the library-wide sweep after a provider outage")
    p.add_argument("--limit", type=int, default=service.RETRY_NIGHTLY_LIMIT, help=f"at most N words per run (default {service.RETRY_NIGHTLY_LIMIT}; pass a larger one for --since)")
    p.add_argument("--dry-run", action="store_true", help="list the words without queueing anything")
    p.add_argument(
        "--since",
        metavar="ISO",
        default=None,
        help=(
            "provider-outage sweep instead of the nightly selection: every failed word, studied or not, whose ONLY fetch attempt at or after "
            f"this instant found no photo is queued once more at priority {PREWARM_PRIORITY} (Wikimedia only, no SVG, no retry flag); "
            "run it when Wikimedia is reachable again, out of cooldown and under its daily quota"
        ),
    )
    p.set_defaults(func=cmd_images_retry)

    p = sub.add_parser(
        "images-import",
        help="import 记忆图卡 made in studio/ (DIR/<lemma>.svg + a manifest): validate, sanitise, activate; --undo FILE puts the previous pictures back",
    )
    p.add_argument("dir", nargs="?", default=None, metavar="DIR", help="directory holding <lemma>.svg for every card of the manifest (spaces in a lemma written _)")
    p.add_argument("--manifest", metavar="FILE", default=None, help='JSON: {"prompt_version": "memo-1", "model": "…", "cards": {"<lemma>": {"alt_zh", "hook_zh", "note_zh"}}}')
    p.add_argument("--undo", metavar="FILE", default=None, help="roll back instead: every lemma of this manifest whose active picture is a memory card gets its previous picture (or the template card) back")
    p.add_argument("--dry-run", action="store_true", help="check everything, write nothing")
    p.add_argument("--only", nargs="+", metavar="LEMMA", default=None, help="work on these lemmas of the manifest only")
    p.set_defaults(func=cmd_images_import)
