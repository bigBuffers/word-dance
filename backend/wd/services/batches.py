"""Daily batches (WP4): composition, publication, grading and the today/batch DTOs.

Contracts: DESIGN §6.3 (composition steps 1–9, ``interleave`` / ``spread_similar`` pinned by
``tests/fixtures/batch_order.json``, stale and superseded items, late sessions, word uniqueness per
``(batch_id, word_id, kind)``),
DESIGN §7 (final vs intermediate grades), API.md §7 (endpoints 43–47, 50) and endpoint 74 (``push_now``), TASKS §I.

Every function takes an open ``sqlite3.Connection`` (``row_factory = sqlite3.Row``) and composes with a caller's
transaction through ``db.maybe_tx`` (``build_batch`` runs under one ``BEGIN IMMEDIATE``; ``UNIQUE(user_id,
local_date)`` is the idempotency guarantee). Grades inside a batch go through WP3's state machine
(``bank.apply_action`` for ``master``, ``screen.apply_verdict`` for 推荐词 verdicts) and ``stats_core.on_action``;
the SRS itself is the pure ``services/srs.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Sequence

from .. import db
from ..clock import day_start, local_date as clock_local_date, parse_iso, to_iso
from ..errors import ApiError
from ..jobs import queue
from . import assignments, bank, learn_order, screen, srs, stats, stats_core, suggestions, words

log = logging.getLogger("wd.batches")

STUDY_KINDS: tuple[str, ...] = ("review", "new", "extra")
ALL_KINDS: tuple[str, ...] = ("review", "new", "screen", "extra")
GRADES_FOR_KIND: dict[str, tuple[str, ...]] = {
    "review": ("again", "hard", "good", "master", "skip"),
    "new": ("again", "hard", "good", "master", "skip"),
    "extra": ("again", "hard", "good", "master", "skip"),
    "screen": ("known", "unfamiliar", "skip"),
}
MAX_EXTRA_ROUNDS = 3
BUILDING_TIMEOUT = timedelta(hours=2)
CONTENT_PRIORITY_BATCH = 20
DELIVERY_PRIORITY = 20
SIMILAR_PREFIX = 4
SIMILAR_WINDOW = 3
STUBBORN_TIMES_ADDED = 3

_COUNT_COLUMN = {"review": "review_count", "new": "new_count", "screen": "screen_count", "extra": "extra_count"}
# DESIGN §6.3 superseded items: a study row of batch ``pb`` whose word has a review/new/extra row in a NEWER batch of the
# same user (yesterday's leftover re-selected into today's batch). Aliases ``pi`` (push_items) / ``pb`` (push_batches)
# are those of the two item queries below; the newest row is the single gradable one, older ungraded copies are hidden.
_SUPERSEDED_SQL = (
    "EXISTS(SELECT 1 FROM push_items pj JOIN push_batches pbj ON pbj.id = pj.batch_id WHERE pbj.user_id = pb.user_id "
    "AND pbj.local_date > pb.local_date AND pj.word_id = pi.word_id AND pj.kind IN ('review','new','extra')) AS superseded"
)
# DESIGN §6.3 step 4: 0 for the 主攻阶段, then higher stages, then lower, NULL stage_min last (learn_order.stage_distance_sql),
# then the learning order — the derived words.learn_rank with the frequency tail (learn_order.ORDER_SQL; API.md 31): the
# 推荐词 of select_words / add_more follow exactly the order the 筛词 page serves
_SCREEN_ORDER = f"{learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL}"
_NEWS_ORDER = "(uw.times_added >= 3) DESC, uw.priority DESC, uw.added_at ASC, uw.id ASC"


# ------------------------------------------------------------------------------------------- types
@dataclass
class Batch:
    """A ``push_batches`` row plus what the caller of :func:`build_batch` / :func:`add_more` needs to know."""

    id: int
    user_id: int
    local_date: str
    timezone: str
    status: str
    trigger: str
    review_count: int
    new_count: int
    screen_count: int
    extra_count: int
    deferred_reviews: int
    extra_rounds: int
    built_at: str
    ready_at: str | None
    published_at: str | None
    completed_at: str | None
    email_status: str
    webhook_status: str
    created: bool = False  # True when this call inserted the row
    added: int = 0  # items appended by add_more

    @classmethod
    def from_row(cls, row: Mapping[str, Any], *, created: bool = False, added: int = 0) -> "Batch":
        return cls(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            local_date=str(row["local_date"]),
            timezone=str(row["timezone"]),
            status=str(row["status"]),
            trigger=str(row["trigger"]),
            review_count=int(row.get("review_count") or 0),
            new_count=int(row.get("new_count") or 0),
            screen_count=int(row.get("screen_count") or 0),
            extra_count=int(row.get("extra_count") or 0),
            deferred_reviews=int(row.get("deferred_reviews") or 0),
            extra_rounds=int(row.get("extra_rounds") or 0),
            built_at=str(row["built_at"]),
            ready_at=row.get("ready_at"),
            published_at=row.get("published_at"),
            completed_at=row.get("completed_at"),
            email_status=str(row.get("email_status") or "none"),
            webhook_status=str(row.get("webhook_status") or "none"),
            created=created,
            added=added,
        )


@dataclass
class Selection:
    """DESIGN §6.3 steps 2–4 for one user and local date (rows carry ``word_id``, ``lemma`` and, for bank rows, ``uw_id``)."""

    reviews: list[dict[str, Any]]
    deferred: int
    news: list[dict[str, Any]]
    screens: list[dict[str, Any]]
    # 布置词汇 (services/assignments.py): assigned words the learner is already studying and that are not due today — one
    # `extra` item each. Assigned rows of every list carry ``aw_ids``, the assignment_words rows the new item answers.
    extras: list[dict[str, Any]] = field(default_factory=list)

    def word_ids(self) -> list[int]:
        out: list[int] = []
        for row in [*self.reviews, *self.news, *self.extras, *self.screens]:
            wid = int(row["word_id"])
            if wid not in out:
                out.append(wid)
        return out


# ------------------------------------------------------------------------------------- pure order
def interleave(reviews: Sequence[Any], news: Sequence[Any]) -> list[Any]:
    """DESIGN §6.3: ``k = ceil(len(reviews) / len(news))`` reviews then one new, the remainder appended in order."""
    reviews = list(reviews)
    news = list(news)
    if not reviews or not news:
        return reviews + news  # the other list unchanged
    k = math.ceil(len(reviews) / len(news))
    out: list[Any] = []
    i = j = 0
    while i < len(reviews) and j < len(news):
        for _ in range(k):
            if i < len(reviews):
                out.append(reviews[i])
                i += 1
        out.append(news[j])
        j += 1
    out.extend(reviews[i:])
    out.extend(news[j:])
    return out


def similar(a: str, b: str) -> bool:
    """Two lemmas are similar when both have ≥ 4 letters and share their first 4 letters (DESIGN §6.3)."""
    return len(a) >= SIMILAR_PREFIX and len(b) >= SIMILAR_PREFIX and a[:SIMILAR_PREFIX] == b[:SIMILAR_PREFIX]


def spread_similar(seq: Sequence[Any], key: Callable[[Any], str] | None = None) -> list[Any]:
    """DESIGN §6.3 single stable left-to-right pass (the literal reading pinned by ``batch_order.json``).

    For each position ``i`` whose item is similar to one of the three items before it, the item moves to the
    first later index ``j`` of the resulting sequence where none of the three predecessors is similar (the items
    in between shift one place left); when no such ``j`` exists it stays. The item shifted into position ``i`` is
    not re-examined. ``key`` maps an item to its lemma (identity by default).
    """
    k = key or (lambda x: x)
    items = list(seq)
    n = len(items)
    i = 0
    while i < n:
        it = items[i]
        lemma = k(it)
        if any(similar(lemma, k(items[p])) for p in range(max(0, i - SIMILAR_WINDOW), i)):
            for j in range(i + 1, n):
                preds = []
                for p in range(j - SIMILAR_WINDOW, j):
                    if p < 0:
                        continue
                    preds.append(items[p + 1] if p >= i else items[p])  # the resulting sequence after the move
                if not any(similar(lemma, k(x)) for x in preds):
                    del items[i]
                    items.insert(j, it)
                    break
        i += 1
    return items


# ------------------------------------------------------------------------------------------ helpers
def _row(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> dict[str, Any] | None:
    r = conn.execute(sql, params).fetchone()
    return None if r is None else {k: r[k] for k in r.keys()}


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in conn.execute(sql, params).fetchall()]


def _date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def day_end_iso(local_date: str | date, tz: str) -> str:
    """UTC instant of the end of ``local_date`` in ``tz`` (= ``day_start(local_date + 1)``)."""
    return to_iso(day_start(_date(local_date) + timedelta(days=1), tz))


def batch_row(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    return _row(conn, "SELECT * FROM push_batches WHERE id = ?", (int(batch_id),))


def user_batch(conn: sqlite3.Connection, user_id: int, batch_id: int) -> dict[str, Any]:
    """The user's own batch or 404 ``batch_not_found`` (foreign ids never 403, API.md §1.1)."""
    row = batch_row(conn, batch_id)
    if row is None or int(row["user_id"]) != int(user_id):
        raise ApiError("batch_not_found", details={"batch_id": int(batch_id)})
    return row


def _user_dates(conn: sqlite3.Connection, user_id: int, now_dt: datetime) -> tuple[dict[str, Any], str, str, str]:
    """``(settings_row, tz, today, yesterday)`` for the user at ``now``."""
    s = bank.user_settings_row(conn, user_id)
    tz = str(s["timezone"] or bank.DEFAULT_TIMEZONE)
    today = clock_local_date(now_dt, tz)
    return s, tz, today.isoformat(), (today - timedelta(days=1)).isoformat()


# --------------------------------------------------------------------------------------- selection
def _stage_flags(stages: Iterable[str]) -> str:
    flags = " OR ".join(f"w.stage_{s} = 1" for s in stages if s in words.STAGES)
    return f"({flags})" if flags else "0"


def select_words(conn: sqlite3.Connection, user_id: int, settings_row: Mapping[str, Any], local_date: str | date) -> Selection:
    """DESIGN §6.3 steps 2–4, read-only: due reviews (capped), new words, 推荐词 for ``local_date``."""
    tz = str(settings_row["timezone"] or bank.DEFAULT_TIMEZONE)
    today_end = day_end_iso(local_date, tz)
    uid = int(user_id)
    max_reviews = max(0, int(settings_row.get("max_reviews") or 0))
    daily_new = max(0, int(settings_row.get("daily_new_count") or 0))
    daily_screen = max(0, int(settings_row.get("daily_screen_count") or 0))

    due_total = int(
        conn.execute(
            "SELECT COUNT(*) FROM user_words WHERE user_id = ? AND state = 'learning' AND due_at IS NOT NULL AND due_at < ?",
            (uid, today_end),
        ).fetchone()[0]
    )
    reviews = _rows(
        conn,
        "SELECT uw.id AS uw_id, uw.word_id, w.lemma FROM user_words uw JOIN words w ON w.id = uw.word_id "
        "WHERE uw.user_id = ? AND uw.state = 'learning' AND uw.due_at IS NOT NULL AND uw.due_at < ? "
        "ORDER BY uw.due_at ASC, uw.id ASC LIMIT ?",
        (uid, today_end, max_reviews),
    )
    news = _rows(
        conn,
        "SELECT uw.id AS uw_id, uw.word_id, w.lemma FROM user_words uw JOIN words w ON w.id = uw.word_id "
        "WHERE uw.user_id = ? AND uw.state = 'new' AND uw.needs_attention = 0 AND w.is_valid_english = 1 "
        f"AND w.merged_into_word_id IS NULL ORDER BY {_NEWS_ORDER} LIMIT ?",
        (uid, daily_new),
    )
    # assigned words come first and take the day's new-word quota (a `today` list may exceed it; then no ordinary new word is added)
    extras: list[dict[str, Any]] = []
    taken = assignments.take_for_batch(conn, uid, daily_new)
    if taken:
        by_word = {int(t["word_id"]): t for t in taken}
        for r in reviews:
            if int(r["word_id"]) in by_word:
                r["aw_ids"] = by_word[int(r["word_id"])]["aw_ids"]
        due = {int(r["word_id"]) for r in reviews}
        as_row = lambda t: {"uw_id": t["uw_id"], "word_id": t["word_id"], "lemma": t["lemma"], "aw_ids": t["aw_ids"]}  # noqa: E731
        extras = [as_row(t) for t in taken if t["state"] == "learning" and int(t["word_id"]) not in due]
        news = [as_row(t) for t in taken if t["state"] == "new"] + [n for n in news if int(n["word_id"]) not in by_word][: max(0, daily_new - len(taken))]
    stages = list(settings_row.get("stages") or bank.DEFAULT_STAGES)
    screens = _rows(
        conn,
        "SELECT w.id AS word_id, w.lemma FROM words w WHERE w.is_public = 1 AND w.merged_into_word_id IS NULL AND w.is_valid_english = 1 "
        f"AND {_stage_flags(stages)} AND NOT EXISTS (SELECT 1 FROM user_words uw WHERE uw.user_id = :me AND uw.word_id = w.id) "
        f"ORDER BY {_SCREEN_ORDER} LIMIT :limit",
        {"me": uid, "cur": bank.current_stage_index(settings_row), "limit": daily_screen},
    )
    return Selection(reviews=reviews, deferred=max(0, due_total - len(reviews)), news=news, screens=screens, extras=extras)


def preview_selection(conn: sqlite3.Connection, user_id: int, local_date: str | date, now: datetime | str | None = None) -> list[int]:
    """TASKS §I: the word ids ``build_batch`` would pick for ``local_date`` — READ-ONLY (no INSERT/UPDATE/enqueue).

    Used by the 03:30 maintenance prefetch (DESIGN §6.4) with the user's *current* settings; ``now`` is accepted
    for signature stability and not needed (the selection depends on ``local_date`` only).
    """
    s = bank.user_settings_row(conn, user_id)
    return select_words(conn, user_id, s, local_date).word_ids()


def order_items(selection: Selection) -> tuple[list[tuple[str, dict[str, Any]]], bool]:
    """Step 5: ``core = spread_similar(interleave(reviews, news))``; cold start puts the 推荐词 first."""
    reviews = [("review", r) for r in selection.reviews]
    news = [("new", r) for r in selection.news] + [("extra", r) for r in selection.extras]
    screens = [("screen", r) for r in selection.screens]
    core = spread_similar(interleave(reviews, news), key=lambda t: str(t[1]["lemma"]))
    cold_start = not core
    ordered = screens + core if cold_start else core + screens
    return ordered, cold_start


# ----------------------------------------------------------------------------------------- building
def build_batch(conn: sqlite3.Connection, user_id: int, local_date: str | date, trigger: str, now: datetime | str | None) -> Batch:
    """DESIGN §6.3 steps 1–9 under one ``BEGIN IMMEDIATE``; returns the existing batch unchanged when one exists.

    ``trigger`` ∈ scheduled | manual | catchup | admin. ``news`` are limited to validated words
    (``is_valid_english = 1``, no 待处理 flag, not merged); content is enqueued (priority 20) only for validated
    words lacking content. Never waits on Claude or image providers.
    """
    if trigger not in ("scheduled", "manual", "catchup", "admin"):
        raise ValueError(f"unknown trigger {trigger!r}")
    now_dt, now_s = bank.coerce_now(now)
    ld = _date(local_date).isoformat()
    uid = int(user_id)
    with db.maybe_tx(conn):
        s = bank.user_settings_row(conn, uid)
        tz = str(s["timezone"] or bank.DEFAULT_TIMEZONE)
        settings_snapshot = {k: s.get(k) for k in ("timezone", "push_time", "daily_new_count", "daily_screen_count", "max_reviews", "stages", "current_stage")}
        cur = conn.execute(
            "INSERT INTO push_batches(user_id, local_date, timezone, status, trigger, settings_json, built_at) "
            "VALUES (?, ?, ?, 'building', ?, ?, ?) ON CONFLICT(user_id, local_date) DO NOTHING",
            (uid, ld, tz, trigger, json.dumps(settings_snapshot, ensure_ascii=False, sort_keys=True), now_s),
        )
        if cur.rowcount == 0:
            existing = bank.today_batch(conn, uid, ld)
            assert existing is not None
            return Batch.from_row(existing, created=False)
        batch_id = int(cur.lastrowid)

        selection = select_words(conn, uid, s, ld)
        ordered, _cold = order_items(selection)
        for position, (kind, row) in enumerate(ordered):
            item_id = conn.execute(
                "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, ?, ?)",
                (batch_id, int(row["word_id"]), row.get("uw_id"), kind, position),
            ).lastrowid
            if row.get("aw_ids"):
                assignments.mark_scheduled(conn, row["aw_ids"], int(item_id), ld)
        conn.execute(
            "UPDATE push_batches SET review_count = ?, new_count = ?, screen_count = ?, extra_count = ?, deferred_reviews = ? WHERE id = ?",
            (len(selection.reviews), len(selection.news), len(selection.screens), len(selection.extras), selection.deferred, batch_id),
        )
        uw_ids = [int(r["uw_id"]) for r in [*selection.reviews, *selection.news, *selection.extras] if r.get("uw_id") is not None]
        if uw_ids:
            marks = ",".join("?" * len(uw_ids))
            conn.execute(f"UPDATE user_words SET times_pushed = times_pushed + 1, updated_at = ? WHERE id IN ({marks})", (now_s, *uw_ids))
        _enqueue_content_for(conn, selection.word_ids(), now_s)
        row = batch_row(conn, batch_id)
        assert row is not None
        log.info(
            "batch built",
            extra={"event": "batch_built", "user_id": uid, "batch_id": batch_id, "trigger": trigger, "local_date": ld},
        )
        return Batch.from_row(row, created=True)


def _enqueue_content_for(conn: sqlite3.Connection, word_ids: Sequence[int], now_s: str, *, priority: int = CONTENT_PRIORITY_BATCH) -> int:
    """Step 9: ``generate_content`` for validated words lacking content (never for ``is_valid_english IS NULL``)."""
    enqueued = 0
    for start in range(0, len(word_ids), 500):
        chunk = [int(w) for w in word_ids[start : start + 500]]
        if not chunk:
            continue
        marks = ",".join("?" * len(chunk))
        for word in _rows(conn, f"SELECT id, is_valid_english, merged_into_word_id, content_state FROM words WHERE id IN ({marks})", chunk):
            if bank.enqueue_content_if_needed(conn, word, priority=priority, now=now_s) is not None:
                enqueued += 1
    return enqueued


def publish_batch(conn: sqlite3.Connection, batch_id: int, now: datetime | str | None) -> bool:
    """Conditional ``UPDATE … SET status = 'published' WHERE status != 'published'``; True exactly once per batch."""
    _, now_s = bank.coerce_now(now)
    with db.maybe_tx(conn):
        cur = conn.execute(
            "UPDATE push_batches SET status = 'published', published_at = ?, ready_at = COALESCE(ready_at, ?) WHERE id = ? AND status != 'published'",
            (now_s, now_s, int(batch_id)),
        )
        return cur.rowcount == 1


def finalize_building(conn: sqlite3.Connection, now: datetime | str | None, *, cfg: Any = None) -> int:
    """Flip ``building → ready`` (DESIGN §6.3): when nothing more is coming today for the batch's words, or after 2 h.

    Nothing is coming when AI is disabled/paused, when no word of the batch has a live ``generate_content`` job
    runnable before the end of its local day (budget/monthly deferrals), and no image fetch is in flight.
    Returns the number of batches flipped.
    """
    now_dt, now_s = bank.coerce_now(now)
    ai_on = bank.ai_enabled(conn, cfg) and bank.ai_paused_until(conn, now_s, cfg=cfg, kind="content") is None
    images_on = bool(getattr(cfg, "images_enabled", True)) if cfg is not None else True
    flipped = 0
    for b in _rows(conn, "SELECT * FROM push_batches WHERE status = 'building' ORDER BY id"):
        ready = parse_iso(str(b["built_at"])) <= now_dt - BUILDING_TIMEOUT or not ai_on
        if not ready:
            ready = not _something_coming(conn, b, images_on=images_on)
        if ready:
            with db.maybe_tx(conn):
                cur = conn.execute(
                    "UPDATE push_batches SET status = 'ready', ready_at = COALESCE(ready_at, ?) WHERE id = ? AND status = 'building'",
                    (now_s, b["id"]),
                )
            flipped += int(cur.rowcount)
    return flipped


def _something_coming(conn: sqlite3.Connection, batch: Mapping[str, Any], *, images_on: bool) -> bool:
    day_end = day_end_iso(str(batch["local_date"]), str(batch["timezone"]))
    for w in _rows(
        conn,
        "SELECT DISTINCT w.id, w.content_state, w.image_state FROM push_items pi JOIN words w ON w.id = pi.word_id WHERE pi.batch_id = ?",
        (batch["id"],),
    ):
        if w["content_state"] == "queued":
            job = queue.live_job(conn, f"content:{int(w['id'])}")
            if job is not None and str(job.run_after) < day_end:
                return True
        if images_on and w["image_state"] == "queued":
            return True
    return False


# ---------------------------------------------------------------------------------- items & counts
def hide_stale(items: Iterable[Mapping[str, Any]], states: Mapping[int, str | None]) -> list[dict[str, Any]]:
    """DESIGN §6.3 stale-item rule, shared by :func:`today_response` and :func:`grade_item`.

    ``items`` are ``push_items`` rows (``kind``, ``result``, ``word_id``; optionally ``merged_into_word_id`` and the
    ``superseded`` flag :func:`batch_items` computes); ``states`` maps ``word_id`` → the user's ``user_words.state``
    (absent = no row). Hidden: an ungraded review/new/extra item whose row is no longer ``new``/``learning``, an
    ungraded review/new/extra item that is *superseded* (the same word has a study row in a newer batch of the user —
    yesterday's leftover re-selected into today's batch is studied once, in today's batch), an ungraded screen item
    whose word now has a row, and any item whose word was merged. Graded items always stay.
    """
    out: list[dict[str, Any]] = []
    for raw in items:
        it = raw if isinstance(raw, dict) else {k: raw[k] for k in raw.keys()}
        if it.get("merged_into_word_id") is not None:
            continue
        if it.get("result") is None:
            wid = int(it["word_id"])
            state = states.get(wid)
            if it["kind"] in STUDY_KINDS and (state not in bank.BANK_STATES or it.get("superseded")):
                continue
            if it["kind"] == "screen" and wid in states and state is not None:
                continue
        out.append(it)
    return out


def batch_items(conn: sqlite3.Connection, user_id: int, batch_id: int) -> tuple[list[dict[str, Any]], dict[int, str | None]]:
    """All ``push_items`` of a batch (joined with the word's merge/content state and the ``superseded`` flag) and the
    user's word states."""
    rows = _rows(
        conn,
        f"SELECT pi.*, w.merged_into_word_id, w.content_state, uw.state AS uw_state, {_SUPERSEDED_SQL}, {assignments.ASSIGNED_SQL} FROM push_items pi "
        "JOIN push_batches pb ON pb.id = pi.batch_id JOIN words w ON w.id = pi.word_id "
        "LEFT JOIN user_words uw ON uw.user_id = ? AND uw.word_id = pi.word_id "
        "WHERE pi.batch_id = ? ORDER BY pi.position, pi.id",
        (int(user_id), int(batch_id)),
    )
    states: dict[int, str | None] = {int(r["word_id"]): r["uw_state"] for r in rows if r["uw_state"] is not None}
    return rows, states


def visible_items(conn: sqlite3.Connection, user_id: int, batch_id: int) -> list[dict[str, Any]]:
    rows, states = batch_items(conn, user_id, batch_id)
    return hide_stale(rows, states)


def _order_key(item: Mapping[str, Any]) -> tuple[int, int, int, int]:
    """``Batch.items``: ungraded first (skipped after unskipped), then graded; inside each group the assigned items (布置词汇)
    first, then by position."""
    graded = 0 if item.get("result") is None else 1
    skipped = int(item.get("skip_count") or 0) if not graded else 0
    return (graded, 1 if skipped else 0, 0 if item.get("assigned") else 1, int(item["position"]))


def remaining_count(items: Iterable[Mapping[str, Any]]) -> int:
    """Ungraded review/new/extra items (``PreviousOpenBatch.remaining``)."""
    return sum(1 for it in items if it["kind"] in STUDY_KINDS and it.get("result") is None)


def goal_met(items: Sequence[Mapping[str, Any]]) -> bool:
    """API.md §9.1: every non-stale review/new/extra item has ``result IS NOT NULL`` (a screen-only batch counts its 推荐词)."""
    study = [it for it in items if it["kind"] in STUDY_KINDS]
    if study:
        return all(it.get("result") is not None for it in study)
    return bool(items) and all(it.get("result") is not None for it in items)


def today_counts(conn: sqlite3.Connection, batch: Mapping[str, Any], items: Sequence[Mapping[str, Any]], *, now: str, cfg: Any = None) -> dict[str, Any]:
    """``TodayCounts`` over the non-stale ``items`` ("done" = ``result IS NOT NULL``; the 10-minute step is not done)."""
    counts = {"total": len(items), "done": sum(1 for it in items if it.get("result") is not None)}
    for kind in ALL_KINDS:
        of_kind = [it for it in items if it["kind"] == kind]
        counts[kind] = len(of_kind)
        counts[f"{kind}_done"] = sum(1 for it in of_kind if it.get("result") is not None)
    counts["pending_content"] = pending_content(conn, batch, items, now=now, cfg=cfg)
    counts["deferred_reviews"] = int(batch.get("deferred_reviews") or 0)
    return counts


def pending_content(conn: sqlite3.Connection, batch: Mapping[str, Any], items: Sequence[Mapping[str, Any]], *, now: str, cfg: Any = None) -> int:
    """Items whose word is ``queued`` with a live content job runnable before the end of the batch's day (API.md 43)."""
    if not bank.ai_enabled(conn, cfg) or bank.ai_paused_until(conn, now, cfg=cfg, kind="content") is not None:
        return 0
    day_end = day_end_iso(str(batch["local_date"]), str(batch["timezone"]))
    runnable: dict[int, bool] = {}
    pending = 0
    for it in items:
        if it.get("content_state") != "queued":
            continue
        wid = int(it["word_id"])
        if wid not in runnable:
            job = queue.live_job(conn, f"content:{wid}")
            runnable[wid] = job is not None and str(job.run_after) <= day_end
        if runnable[wid]:
            pending += 1
    return pending


def batch_progress(conn: sqlite3.Connection, user_id: int, batch_id: int) -> tuple[int, int]:
    """``(total, done)`` over the batch's non-stale items (``DayStats.batch_total`` / ``batch_done``)."""
    items = visible_items(conn, user_id, batch_id)
    return len(items), sum(1 for it in items if it.get("result") is not None)


# ----------------------------------------------------------------------------------- today DTO
def previous_open_batch(conn: sqlite3.Connection, user_id: int, yesterday: str) -> dict[str, Any] | None:
    """API.md 43: yesterday's batch while it has ungraded, non-stale review/new/extra items.

    Leftovers that today's batch re-selected are superseded (hidden by :func:`hide_stale`), so ``remaining`` counts
    only the words the user can still study in yesterday's batch alone.
    """
    row = bank.today_batch(conn, user_id, yesterday)
    if row is None:
        return None
    remaining = remaining_count(visible_items(conn, user_id, int(row["id"])))
    if remaining <= 0:
        return None
    return {"id": int(row["id"]), "local_date": str(row["local_date"]), "remaining": remaining}


def today_response(
    conn: sqlite3.Connection,
    user_id: int,
    now: datetime | str | None,
    batch_id: int | None = None,
    *,
    cfg: Any = None,
    added: int | None = None,
) -> dict[str, Any]:
    """API.md ``TodayResponse`` for today's batch (``batch_id`` None) or a given batch (endpoint 50). Side-effect free.

    Stale items are hidden from ``items`` and every ``counts`` field; ``Batch.gradable`` is true for today's batch
    and for yesterday's while it has ungraded study items; ``previous_open_batch`` and ``suggestions_open`` are
    filled; ``StudyItem.word.confusables`` / ``content_deferred_until`` come from WP3's ``study_item_dict``.
    """
    now_dt, now_s = bank.coerce_now(now)
    uid = int(user_id)
    s, tz, today, yesterday = _user_dates(conn, uid, now_dt)
    if batch_id is None:
        batch = bank.today_batch(conn, uid, today)
    else:
        batch = user_batch(conn, uid, batch_id)
    streak_days, _longest = stats.streak(conn, uid, _date(today))
    base: dict[str, Any] = {
        "status": "none",
        "local_date": today,
        "push_time": str(s.get("push_time") or "08:00"),
        "next_push_at": s.get("next_push_at"),
        "can_build_now": batch is None,
        "batch": None,
        "streak_days": streak_days,
        "goal_met": False,
        "added": added,
        "previous_open_batch": previous_open_batch(conn, uid, yesterday),
        "suggestions_open": suggestions.open_count(conn, uid, now_s),
    }
    if batch is None:
        return base
    items = visible_items(conn, uid, int(batch["id"]))
    counts = today_counts(conn, batch, items, now=now_s, cfg=cfg)
    gradable = batch["local_date"] == today or (batch["local_date"] == yesterday and remaining_count(items) > 0)
    dtos = []
    for it in sorted(items, key=_order_key):
        dto = screen.study_item_dict(conn, uid, int(it["id"]), now=now_s, cfg=cfg)
        if dto is not None:
            dtos.append(dto)
    base.update(
        {
            "status": str(batch["status"]),
            "local_date": str(batch["local_date"]),
            "can_build_now": False,
            "goal_met": goal_met(items),
            "batch": {
                "id": int(batch["id"]),
                "local_date": str(batch["local_date"]),
                "timezone": str(batch["timezone"]),
                "status": str(batch["status"]),
                "trigger": str(batch["trigger"]),
                "gradable": bool(gradable),
                "counts": counts,
                "items": dtos,
                "assigned_item_ids": [int(it["id"]) for it in sorted(items, key=_order_key) if it.get("assigned") and it["kind"] in STUDY_KINDS],
                "extra_rounds": int(batch.get("extra_rounds") or 0),
                "can_request_more": batch["local_date"] == today and int(batch.get("extra_rounds") or 0) < MAX_EXTRA_ROUNDS,
                "built_at": str(batch["built_at"]),
                "published_at": batch.get("published_at"),
                "completed_at": batch.get("completed_at"),
            },
        }
    )
    return base


# ----------------------------------------------------------------------------------- appending
def _append_item(conn: sqlite3.Connection, batch: Mapping[str, Any], user_id: int, word_id: int, kind: str, now_s: str) -> int | None:
    """One ``push_items`` row at the end of ``batch`` (DESIGN §6.3 uniqueness rules); None when nothing was added."""
    if kind not in ALL_KINDS:
        raise ValueError(f"unknown item kind {kind!r}")
    bid, wid, uid = int(batch["id"]), int(word_id), int(user_id)
    word = words.word_row(conn, wid)
    if word is None or word.get("merged_into_word_id") is not None:
        return None
    uw = bank.my_row(conn, uid, wid)
    if kind in STUDY_KINDS:
        if uw is None or str(uw["state"]) not in bank.BANK_STATES:
            return None  # nothing to study: the row would be stale at once
        if screen.has_study_row(conn, bid, wid):
            return None  # one gradable row per word per batch
    else:
        if uw is not None:
            return None  # a 推荐词 is a word the user has not marked yet
        if conn.execute("SELECT 1 FROM push_items WHERE batch_id = ? AND word_id = ? AND kind = 'screen'", (bid, wid)).fetchone():
            return None
    position = int(conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM push_items WHERE batch_id = ?", (bid,)).fetchone()[0])
    cur = conn.execute(
        "INSERT INTO push_items(batch_id, word_id, user_word_id, kind, position) VALUES (?, ?, ?, ?, ?)",
        (bid, wid, None if uw is None else int(uw["id"]), kind, position),
    )
    item_id = int(cur.lastrowid)
    column = _COUNT_COLUMN[kind]
    conn.execute(f"UPDATE push_batches SET {column} = {column} + 1 WHERE id = ?", (bid,))
    if kind in STUDY_KINDS and uw is not None:
        conn.execute("UPDATE user_words SET times_pushed = times_pushed + 1, updated_at = ? WHERE id = ?", (now_s, uw["id"]))
    bank.enqueue_content_if_needed(conn, word, priority=CONTENT_PRIORITY_BATCH, now=now_s)
    return item_id


append_item = _append_item  # services/assignments.apply_today appends its `extra` items through the same rules


def append_to_today(conn: sqlite3.Connection, user_id: int, word_id: int, kind: str, now: datetime | str | None) -> int | None:
    """TASKS §I: append one ``kind`` row for ``word_id`` to the user's batch of the current local day.

    Used by WP3 (in-batch 推荐词 ``unfamiliar`` → ``kind='new'``, ``study_today`` → ``kind='extra'``) and by
    :func:`add_more`. Returns the new ``push_items.id``, or None when there is no batch today or the word already
    has a review/new/extra row (``UNIQUE(batch_id, word_id, kind)``; a word present only as ``screen`` gets its
    study row). Works on a ``building`` batch (appending never waits for content).
    """
    now_dt, now_s = bank.coerce_now(now)
    uid = int(user_id)
    with db.maybe_tx(conn):
        _s, _tz, today, _y = _user_dates(conn, uid, now_dt)
        batch = bank.today_batch(conn, uid, today)
        if batch is None:
            return None
        return _append_item(conn, batch, uid, word_id, kind, now_s)


def add_more(conn: sqlite3.Connection, user_id: int, batch_id: int, source: str, count: int, now: datetime | str | None) -> Batch:
    """API.md 46 再来一组: append up to ``count`` ``extra`` (source ``new``) or ``screen`` items to the batch.

    Works on any existing batch of the day (``building`` included); 429 ``rate_limited`` after
    :data:`MAX_EXTRA_ROUNDS` rounds (a round counts only when something was added). The caller answers 409
    ``batch_not_ready`` when no batch exists yet.
    """
    if source not in ("new", "screen"):
        raise ApiError("validation_error", details={"fields": {"source": "new or screen"}})
    now_dt, now_s = bank.coerce_now(now)
    uid = int(user_id)
    n = max(1, min(20, int(count)))
    with db.maybe_tx(conn):
        batch = user_batch(conn, uid, batch_id)
        bid = int(batch["id"])
        if int(batch.get("extra_rounds") or 0) >= MAX_EXTRA_ROUNDS:
            retry = max(1, int((parse_iso(day_end_iso(str(batch["local_date"]), str(batch["timezone"]))) - now_dt).total_seconds()))
            raise ApiError("rate_limited", details={"retry_after_s": retry, "limit": MAX_EXTRA_ROUNDS})
        s = bank.user_settings_row(conn, uid)
        if source == "new":
            candidates = _rows(
                conn,
                "SELECT uw.word_id FROM user_words uw JOIN words w ON w.id = uw.word_id "
                "WHERE uw.user_id = ? AND uw.state = 'new' AND uw.needs_attention = 0 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM push_items pi WHERE pi.batch_id = ? AND pi.word_id = uw.word_id AND pi.kind IN ('review','new','extra')) "
                f"ORDER BY {_NEWS_ORDER} LIMIT ?",
                (uid, bid, n),
            )
            kind = "extra"
        else:
            candidates = _rows(
                conn,
                "SELECT w.id AS word_id FROM words w WHERE w.is_public = 1 AND w.merged_into_word_id IS NULL AND w.is_valid_english = 1 "
                f"AND {_stage_flags(s.get('stages') or bank.DEFAULT_STAGES)} "
                "AND NOT EXISTS (SELECT 1 FROM user_words uw WHERE uw.user_id = :me AND uw.word_id = w.id) "
                "AND NOT EXISTS (SELECT 1 FROM push_items pi WHERE pi.batch_id = :bid AND pi.word_id = w.id) "
                f"ORDER BY {_SCREEN_ORDER} LIMIT :limit",
                {"me": uid, "bid": bid, "cur": bank.current_stage_index(s), "limit": n},
            )
            kind = "screen"
        added = 0
        for c in candidates:
            if _append_item(conn, batch, uid, int(c["word_id"]), kind, now_s) is not None:
                added += 1
        if added:
            conn.execute("UPDATE push_batches SET extra_rounds = extra_rounds + 1 WHERE id = ?", (bid,))
        row = batch_row(conn, bid)
        assert row is not None
        return Batch.from_row(row, added=added)


# ------------------------------------------------------------------------------------------ grading
def _stored_grade(conn: sqlite3.Connection, user_id: int, client_event_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT result_json FROM review_logs WHERE user_id = ? AND client_event_id = ?", (int(user_id), client_event_id)).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0]) if row[0] else None
    except ValueError:
        data = None
    if not isinstance(data, dict) or "item" not in data:
        data = {"item": None, "mine": None, "next_due_zh": "", "mastery_suggested": False, "today": None, "study_item": None}
    screen.upgrade_stored(data)  # a 推荐词 graded 不熟悉 before the 记忆图卡 release stored its study_item.image without the 0021 fields
    data["duplicate"] = True
    return data


def _store_result(conn: sqlite3.Connection, user_id: int, client_event_id: str, response: Mapping[str, Any]) -> None:
    conn.execute(
        "UPDATE review_logs SET result_json = ? WHERE user_id = ? AND client_event_id = ?",
        (json.dumps(response, ensure_ascii=False), int(user_id), client_event_id),
    )


def _requeue_at(uw: Mapping[str, Any] | None, now_s: str) -> str | None:
    if uw is None:
        return None
    if int(uw.get("step") or 0) == 1 and uw.get("due_at") and str(uw["due_at"]) > now_s:
        return str(uw["due_at"])
    return None


def grade_item(
    conn: sqlite3.Connection,
    user_id: int,
    item_id: int,
    grade: str,
    *,
    client_event_id: str,
    elapsed_ms: int | None,
    now: datetime | str | None,
    cfg: Any = None,
) -> dict[str, Any]:
    """API.md 45 ``GradeResponse`` for a card grade or an in-batch 推荐词 verdict.

    Idempotent on ``client_event_id`` (the stored outcome comes back with ``duplicate:true``). Items must belong
    to today's or yesterday's batch (404 ``batch_not_found`` otherwise); 400 ``invalid_grade`` for a grade the
    kind does not allow; 409 ``invalid_transition`` for a stale item (``reason:'stale_item'``) or for yesterday's
    ungraded copy of a word that today's batch re-selected (``reason:'superseded_item'``, DESIGN §6.3 — the word is
    graded once, in today's batch); 409 ``item_already_graded`` when a *different* event grades an item whose
    ``result IS NOT NULL`` (``skip`` exempt). Only a FINAL grade (``master``, a screen verdict, or an
    again/hard/good leaving ``step = 0``) writes ``push_items.result``; an intermediate grade returns
    ``requeue_at`` with ``result:null`` and leaves the item gradable (DESIGN §7).
    """
    now_dt, now_s = bank.coerce_now(now)
    uid = int(user_id)
    stored = _stored_grade(conn, uid, client_event_id)
    if stored is not None:
        return stored
    with db.maybe_tx(conn):
        s, tz, today, yesterday = _user_dates(conn, uid, now_dt)
        item = _row(
            conn,
            f"SELECT pi.*, pb.user_id AS batch_user_id, pb.local_date AS batch_local_date, {_SUPERSEDED_SQL} FROM push_items pi "
            "JOIN push_batches pb ON pb.id = pi.batch_id WHERE pi.id = ?",
            (int(item_id),),
        )
        if item is None or int(item["batch_user_id"]) != uid or item["batch_local_date"] not in (today, yesterday):
            raise ApiError("batch_not_found", details={"item_id": int(item_id)})
        kind = str(item["kind"])
        if grade not in GRADES_FOR_KIND.get(kind, ()):
            raise ApiError("invalid_grade", details={"kind": kind, "grade": grade})
        word = words.word_row(conn, int(item["word_id"]))
        uw = bank.my_row(conn, uid, int(item["word_id"]))
        if item.get("result") is None and _is_stale(kind, word, uw):
            raise ApiError(
                "invalid_transition",
                details={"reason": "stale_item", "item_id": int(item_id), "from": None if uw is None else uw["state"], "action": grade},
            )
        if item.get("result") is None and kind in STUDY_KINDS and item.get("superseded"):
            raise ApiError(
                "invalid_transition",
                details={"reason": "superseded_item", "item_id": int(item_id), "from": None if uw is None else uw["state"], "action": grade},
            )
        if item.get("result") is not None and grade != "skip":
            raise ApiError("item_already_graded", details={"item_id": int(item_id), "result": item["result"]})
        context = "extra" if kind == "extra" else "today"
        batch = batch_row(conn, int(item["batch_id"]))
        assert batch is not None
        common = dict(conn=conn, uid=uid, item=item, batch=batch, context=context, today=today, tz=tz, now_dt=now_dt, now_s=now_s, client_event_id=client_event_id, elapsed_ms=elapsed_ms, cfg=cfg)
        if grade == "skip":
            return _grade_skip(uw=uw, **common)
        if kind == "screen":
            return _grade_screen(grade, **common)
        assert uw is not None
        if grade == "master":
            return _grade_master(**common)
        return _grade_srs(grade, uw=uw, **common)


def _is_stale(kind: str, word: Mapping[str, Any] | None, uw: Mapping[str, Any] | None) -> bool:
    if word is None or word.get("merged_into_word_id") is not None:
        return True
    if kind in STUDY_KINDS:
        return uw is None or str(uw["state"]) not in bank.BANK_STATES
    return uw is not None  # an ungraded 推荐词 whose word was marked in the meantime


def _response(conn: sqlite3.Connection, uid: int, item_id: int, batch: Mapping[str, Any], *, mine: Any, next_due_zh: str, mastery_suggested: bool, now_s: str, cfg: Any, study_item: Any = None) -> dict[str, Any]:
    item = bank.push_item_row(conn, item_id)
    assert item is not None
    uw_row = bank.my_row(conn, uid, int(item["word_id"]))
    items = visible_items(conn, uid, int(batch["id"]))
    return {
        "item": {
            "item_id": int(item["id"]),
            "result": item.get("result"),
            "skip_count": int(item.get("skip_count") or 0),
            "requeue_at": None if item.get("result") is not None else _requeue_at(uw_row, now_s),
        },
        "mine": mine,
        "next_due_zh": next_due_zh,
        "mastery_suggested": bool(mastery_suggested),
        "today": today_counts(conn, batch, items, now=now_s, cfg=cfg),
        "duplicate": False,
        "study_item": study_item,
    }


def _grade_skip(*, conn, uid, item, batch, context, today, tz, now_dt, now_s, client_event_id, elapsed_ms, cfg, uw) -> dict[str, Any]:
    conn.execute("UPDATE push_items SET skip_count = skip_count + 1 WHERE id = ?", (item["id"],))
    state = None if uw is None else str(uw["state"])
    bank.write_log(
        conn,
        user_id=uid,
        word_id=int(item["word_id"]),
        action="skip",
        context=context,
        local_date=today,
        now=now_s,
        user_word_id=None if uw is None else int(uw["id"]),
        prev_row=uw,
        new_row=uw,
        prev_state=state,
        new_state=state,
        batch_id=int(item["batch_id"]),
        push_item_id=int(item["id"]),
        client_event_id=client_event_id,
        elapsed_ms=elapsed_ms,
    )
    stats_core.on_action(conn, uid, today, action="skip", context=context, new_state=state, item_kind=str(item["kind"]), elapsed_ms=elapsed_ms, prev_state=state)
    mine = None if uw is None else words.user_word_dict(conn, uw, uid)
    response = _response(conn, uid, int(item["id"]), batch, mine=mine, next_due_zh=srs.NEXT_DUE_SKIP, mastery_suggested=False, now_s=now_s, cfg=cfg)
    _store_result(conn, uid, client_event_id, response)
    return response


def _grade_screen(verdict: str, *, conn, uid, item, batch, context, today, tz, now_dt, now_s, client_event_id, elapsed_ms, cfg) -> dict[str, Any]:
    sr = screen.apply_verdict(
        conn,
        uid,
        int(item["word_id"]),
        verdict,
        client_event_id=client_event_id,
        context=context,
        push_item_id=int(item["id"]),
        now=now_dt,
        tz=tz,
        cfg=cfg,
    )
    if verdict == "known":
        next_due = srs.NEXT_DUE_KNOWN
    else:
        next_due = srs.NEXT_DUE_TODAY if sr.get("study_item") else srs.NEXT_DUE_TOMORROW
    response = _response(conn, uid, int(item["id"]), batch, mine=sr.get("mine"), next_due_zh=next_due, mastery_suggested=False, now_s=now_s, cfg=cfg, study_item=sr.get("study_item"))
    _store_result(conn, uid, client_event_id, response)
    return response


def _grade_master(*, conn, uid, item, batch, context, today, tz, now_dt, now_s, client_event_id, elapsed_ms, cfg) -> dict[str, Any]:
    r = bank.apply_action(
        conn,
        uid,
        int(item["word_id"]),
        "master",
        origin="push",
        context=context,
        now=now_dt,
        tz=tz,
        batch_id=int(item["batch_id"]),
        push_item_id=int(item["id"]),
        client_event_id=client_event_id,
        elapsed_ms=elapsed_ms,
    )
    conn.execute(
        "UPDATE push_items SET result = 'master', graded_at = ?, user_word_id = COALESCE(?, user_word_id) WHERE id = ?",
        (now_s, r.user_word_id, item["id"]),
    )
    response = _response(conn, uid, int(item["id"]), batch, mine=r.mine, next_due_zh=srs.NEXT_DUE_MASTER, mastery_suggested=False, now_s=now_s, cfg=cfg)
    _store_result(conn, uid, client_event_id, response)
    return response


def _grade_srs(grade: str, *, conn, uid, item, batch, context, today, tz, now_dt, now_s, client_event_id, elapsed_ms, cfg, uw) -> dict[str, Any]:
    state = srs.SrsState.from_row(uw)
    new_state, requeue_min, suggested, next_due = srs.grade(int(uw["id"]), state, grade, now_dt, tz, _date(today))
    final = requeue_min is None
    values = new_state.to_row()
    conn.execute(
        "UPDATE user_words SET state = :state, ease = :ease, interval_days = :interval_days, step = :step, repetitions = :repetitions, "
        "lapses = :lapses, consecutive_good = :consecutive_good, due_at = :due_at, last_graded_at = :last_graded_at, updated_at = :now WHERE id = :id",
        {**values, "now": now_s, "id": uw["id"]},
    )
    new_row = bank.my_row(conn, uid, int(item["word_id"]))
    assert new_row is not None
    bank.write_log(
        conn,
        user_id=uid,
        word_id=int(item["word_id"]),
        action=grade,
        context=context,
        local_date=today,
        now=now_s,
        user_word_id=int(uw["id"]),
        prev_row=uw,
        new_row=new_row,
        prev_state=str(uw["state"]),
        new_state="learning",
        batch_id=int(item["batch_id"]),
        push_item_id=int(item["id"]),
        client_event_id=client_event_id,
        elapsed_ms=elapsed_ms,
    )
    stats_core.on_action(conn, uid, today, action=grade, context=context, new_state="learning", item_kind=str(item["kind"]), elapsed_ms=elapsed_ms, prev_state=str(uw["state"]))
    if final:
        conn.execute("UPDATE push_items SET result = ?, graded_at = ?, user_word_id = ? WHERE id = ?", (grade, now_s, uw["id"], item["id"]))
    else:
        conn.execute("UPDATE push_items SET user_word_id = ? WHERE id = ?", (uw["id"], item["id"]))
    response = _response(conn, uid, int(item["id"]), batch, mine=words.user_word_dict(conn, new_row, uid), next_due_zh=next_due, mastery_suggested=suggested, now_s=now_s, cfg=cfg)
    _store_result(conn, uid, client_event_id, response)
    return response


# ----------------------------------------------------------------------------------- completion
def complete_session(conn: sqlite3.Connection, user_id: int, now: datetime | str | None, *, cfg: Any = None) -> dict[str, Any]:
    """API.md 47: ``SessionSummary`` for today's batch; sets ``completed_at`` once every non-stale study item is final."""
    now_dt, now_s = bank.coerce_now(now)
    uid = int(user_id)
    with db.maybe_tx(conn):
        s, tz, today, _y = _user_dates(conn, uid, now_dt)
        batch = bank.today_batch(conn, uid, today)
        if batch is None:
            raise ApiError("batch_not_ready")
        items = visible_items(conn, uid, int(batch["id"]))
        met = goal_met(items)
        if met and batch.get("completed_at") is None:
            conn.execute("UPDATE push_batches SET completed_at = ? WHERE id = ? AND completed_at IS NULL", (now_s, batch["id"]))
            batch = batch_row(conn, int(batch["id"])) or batch
        counts = today_counts(conn, batch, items, now=now_s, cfg=cfg)
        # grades are counted from the log (intermediate again/hard/good included, like daily_stats); the final outcomes
        # master / known / unfamiliar from the items themselves, so an undone 已掌握 (mark:restore) is not counted
        agg = conn.execute(
            "SELECT COALESCE(SUM(action = 'again'), 0), COALESCE(SUM(action = 'hard'), 0), COALESCE(SUM(action = 'good'), 0), "
            "COALESCE(SUM(CASE WHEN action IN ('again','hard','good','master') THEN MIN(COALESCE(elapsed_ms, 0), 60000) ELSE 0 END), 0) "
            "FROM review_logs WHERE user_id = ? AND batch_id = ?",
            (uid, batch["id"]),
        ).fetchone()
        outcomes = {r: sum(1 for it in items if it.get("result") == r) for r in ("master", "known", "unfamiliar")}
        streak_days, _longest = stats.streak(conn, uid, _date(today))
        return {
            "local_date": str(batch["local_date"]),
            "review": counts["review"],
            "new": counts["new"],
            "extra": counts["extra"],
            "screen": counts["screen"],
            "again": int(agg[0]),
            "hard": int(agg[1]),
            "good": int(agg[2]),
            "mastered": outcomes["master"],
            "known": outcomes["known"],
            "unfamiliar": outcomes["unfamiliar"],
            "study_minutes": srs.rnd(int(agg[3]) / 60000),
            "streak_days": streak_days,
            "goal_met": met,
            "next_push_at": s.get("next_push_at"),
            "can_request_more": int(batch.get("extra_rounds") or 0) < MAX_EXTRA_ROUNDS,
        }


# ------------------------------------------------------------------------------------- delivery
def enqueue_deliveries(conn: sqlite3.Connection, batch_id: int, now: datetime | str | None, *, stale: bool = False) -> dict[str, str]:
    """After a publish: ``send_email`` / ``send_webhook`` jobs (dedupe ``email:<id>`` / ``webhook:<id>``) for the
    channels the user enabled; ``stale=True`` (> 6 h late, DESIGN §6.4) marks them ``skipped`` instead."""
    _, now_s = bank.coerce_now(now)
    with db.maybe_tx(conn):
        row = _row(
            conn,
            "SELECT pb.id, pb.user_id, s.email_enabled, s.webhook_enabled, s.webhook_url, u.email, u.email_verified_at "
            "FROM push_batches pb JOIN users u ON u.id = pb.user_id LEFT JOIN user_settings s ON s.user_id = pb.user_id WHERE pb.id = ?",
            (int(batch_id),),
        )
        if row is None:
            raise ApiError("batch_not_found", details={"batch_id": int(batch_id)})
        statuses: dict[str, str] = {}
        email_wanted = bool(int(row.get("email_enabled") or 0)) and bool(row.get("email")) and row.get("email_verified_at") is not None
        webhook_wanted = bool(int(row.get("webhook_enabled") or 0)) and bool(row.get("webhook_url"))
        if email_wanted:
            if stale:
                statuses["email"] = "skipped"
            else:
                queue.enqueue(conn, "send_email", {"batch_id": int(batch_id)}, dedupe_key=f"email:{int(batch_id)}", priority=DELIVERY_PRIORITY, now=now_s)
                statuses["email"] = "queued"
        if webhook_wanted:
            if stale:
                statuses["webhook"] = "skipped"
            else:
                queue.enqueue(conn, "send_webhook", {"batch_id": int(batch_id)}, dedupe_key=f"webhook:{int(batch_id)}", priority=DELIVERY_PRIORITY, now=now_s)
                statuses["webhook"] = "queued"
        if "email" in statuses:
            conn.execute("UPDATE push_batches SET email_status = ? WHERE id = ?", (statuses["email"], int(batch_id)))
        if "webhook" in statuses:
            conn.execute("UPDATE push_batches SET webhook_status = ? WHERE id = ?", (statuses["webhook"], int(batch_id)))
        return statuses


def push_now(conn: sqlite3.Connection, user_id: int, now: datetime | str | None, *, trigger: str = "admin") -> tuple[int, str]:
    """API.md 74 helper (also ``wd push-now``): build today's batch if missing, publish it at once, enqueue deliveries.

    Returns ``(batch_id, status)``. ``user_settings.next_push_at`` is left alone: the scheduler's own push time
    simply finds the batch already published (``publish_batch`` returns False, no duplicate delivery).
    """
    now_dt, now_s = bank.coerce_now(now)
    uid = int(user_id)
    with db.maybe_tx(conn):
        _s, _tz, today, _y = _user_dates(conn, uid, now_dt)
        batch = build_batch(conn, uid, today, trigger, now_dt)
        if publish_batch(conn, batch.id, now_dt):
            enqueue_deliveries(conn, batch.id, now_dt)
        row = batch_row(conn, batch.id)
        assert row is not None
        return batch.id, str(row["status"])


# ------------------------------------------------------------------------------------------- CLI
def _cli_user(conn: sqlite3.Connection, username: str) -> dict[str, Any]:
    row = _row(conn, "SELECT * FROM users WHERE username = ?", (username.strip(),))
    if row is None:
        raise SystemExit(f"wd: no user named {username!r}")
    return row


def _cli_connect():
    from ..config import Settings, ensure_dirs

    cfg = Settings.from_env()
    ensure_dirs(cfg)
    return cfg, db.connect(cfg.db_path)


def cmd_build_batch(args: argparse.Namespace) -> int:
    from ..clock import SYSTEM_CLOCK

    cfg, conn = _cli_connect()
    try:
        user = _cli_user(conn, args.username)
        now = SYSTEM_CLOCK.now_utc()
        tz = bank.user_timezone(conn, int(user["id"]))
        local_date = args.date or clock_local_date(now, tz).isoformat()
        try:
            date.fromisoformat(local_date)
        except ValueError:
            print(f"wd build-batch: --date must be YYYY-MM-DD, got {local_date!r}", file=sys.stderr)
            return 2
        b = build_batch(conn, int(user["id"]), local_date, "manual", now)
        verb = "built" if b.created else "exists"
        print(f"batch {b.id} {verb} for {user['username']} on {b.local_date} ({b.timezone}): status {b.status}, review {b.review_count}, new {b.new_count}, screen {b.screen_count}, deferred {b.deferred_reviews}")
        return 0
    finally:
        conn.close()


def cmd_push_now(args: argparse.Namespace) -> int:
    from ..clock import SYSTEM_CLOCK

    cfg, conn = _cli_connect()
    try:
        user = _cli_user(conn, args.username)
        batch_id, status = push_now(conn, int(user["id"]), SYSTEM_CLOCK.now_utc(), trigger="admin")
        row = batch_row(conn, batch_id) or {}
        print(f"batch {batch_id} for {user['username']} ({row.get('local_date')}): status {status}, email {row.get('email_status')}, webhook {row.get('webhook_status')}")
        return 0
    finally:
        conn.close()


def register_cli(sub: argparse._SubParsersAction) -> None:
    """``wd build-batch <username> [--date YYYY-MM-DD]`` and ``wd push-now <username>`` (DEPLOY §9)."""
    p = sub.add_parser("build-batch", help="build a user's batch for a local date (default: today in the user's timezone)")
    p.add_argument("username")
    p.add_argument("--date", default=None, help="local date YYYY-MM-DD")
    p.set_defaults(func=cmd_build_batch)
    p = sub.add_parser("push-now", help="build (if missing) and publish a user's batch now; deliveries are enqueued")
    p.add_argument("username")
    p.set_defaults(func=cmd_push_now)


__all__ = [
    "ALL_KINDS",
    "Batch",
    "GRADES_FOR_KIND",
    "MAX_EXTRA_ROUNDS",
    "STUDY_KINDS",
    "Selection",
    "add_more",
    "append_to_today",
    "batch_items",
    "batch_progress",
    "batch_row",
    "build_batch",
    "complete_session",
    "day_end_iso",
    "enqueue_deliveries",
    "finalize_building",
    "goal_met",
    "grade_item",
    "hide_stale",
    "interleave",
    "order_items",
    "pending_content",
    "preview_selection",
    "previous_open_batch",
    "publish_batch",
    "push_now",
    "register_cli",
    "remaining_count",
    "select_words",
    "similar",
    "spread_similar",
    "today_counts",
    "today_response",
    "user_batch",
    "visible_items",
]
