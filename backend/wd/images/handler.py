"""``fetch_image`` job handler (DESIGN §9 pseudo-code) and the ``wd fetch-image`` / ``wd images-prune`` / ``wd images-retry`` commands.

    fetch_image {word_id, exclude?: [str], provider?: str, query?: str, retry?: true}      (IoWorker, one job at a time)
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
          30 days, only while studied — the job then carries retry: true, which this handler ignores)
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Iterable

from .. import db
from ..clock import SYSTEM_CLOCK, now_iso, parse_iso, to_iso
from ..config import ConfigError, Settings, ensure_dirs
from ..interfaces import ImageProvider, Job, ProviderError
from ..jobs import queue
from ..jobs.registry import JobContext, register
from . import fetch, providers, quota, select, service, store, style

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


@register("fetch_image")
def handle_fetch_image(ctx: JobContext, jobs: list[Job]) -> None:
    """Handler contract: every job ends ``done`` (``result_json`` = :class:`FetchOutcome`) or ``fail``ed."""
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
                outcome = fetch_for_word(ctx, conn, word_id, exclude=exclude, provider=provider, query=query, priority=job.priority, now=ctx.now())
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
    """``wd images-retry [--limit N] [--dry-run]``: the nightly failed-image sweep by hand (DEPLOY §9); prints the words."""
    cfg = _settings()
    if cfg is None:
        return 2
    ensure_dirs(cfg)
    if not cfg.images_enabled:
        print("images-retry: images are disabled (WD_IMAGES_ENABLED=0); nothing to requeue")
        return 0
    conn = db.connect(cfg.db_path)
    try:
        word_ids = service.retry_failed_studied(conn, now_iso(), limit=args.limit, priority=service.RETRY_NIGHTLY_PRIORITY, dry_run=args.dry_run)
        lemma_of = {int(r[0]): str(r[1]) for r in conn.execute(f"SELECT id, lemma FROM words WHERE id IN ({','.join('?' * len(word_ids))})", word_ids)} if word_ids else {}
        lemmas = [lemma_of.get(w, str(w)) for w in word_ids]  # in sweep order (oldest failure first), like the nightly run
    finally:
        conn.close()
    verb = "would requeue" if args.dry_run else "requeued"
    print(
        f"images-retry: {verb} {len(word_ids)} failed-image word(s) being studied (limit {args.limit}; "
        f">= {service.RETRY_MIN_AGE_H} h since the last attempt, <= {service.RETRY_MAX_AUTO_30D} automatic retries per 30 days, function words excluded)"
    )
    for lemma in lemmas:
        print(f"  {lemma}")
    return 0


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

    p = sub.add_parser("images-retry", help="requeue fetch_image for failed-image words somebody is studying (the nightly 03:30 sweep by hand)")
    p.add_argument("--limit", type=int, default=service.RETRY_NIGHTLY_LIMIT, help=f"at most N words per run (default {service.RETRY_NIGHTLY_LIMIT})")
    p.add_argument("--dry-run", action="store_true", help="list the words without queueing anything")
    p.set_defaults(func=cmd_images_retry)
