"""Word-bank services (WP3): the DESIGN §4 state machine, 待处理 flags, bulk add and import.

Contracts: DESIGN §4 (state machine table, action → ``review_logs.action`` mapping, context → ``origin`` mapping,
``restore``), DESIGN §5.3 (bulk add), DESIGN §7.1 (every transition is reported to ``stats_core.on_action`` — the single
``daily_stats`` writer), API.md 26/27/34–37/75 and TASKS §I (signatures of :func:`apply_action`, :func:`set_attention`,
:func:`add_custom_words`, :func:`import_rows`).

Every function takes an open ``sqlite3.Connection`` (``row_factory = sqlite3.Row``) and composes with a caller's
transaction through ``db.maybe_tx``. WP4's ``batches.append_to_today`` (``study_today`` extras, in-batch screen
verdicts) is imported inside :func:`_append_to_today` because ``batches`` imports this module.

This module also hosts the small helpers the WP3 routers share: query-model parsing, the per-user daily quotas kept in
``auth_throttle``, the user's timezone / settings row and the AI kill-switch check.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, ValidationError

from .. import db
from ..clock import UTC, day_start, local_date as clock_local_date, now_iso, parse_iso, to_iso
from ..errors import ApiError, pydantic_error_zh
from ..jobs import queue
from . import stats_core, words

log = logging.getLogger("wd.bank")

# ------------------------------------------------------------------------------------------ constants
BANK_STATES: tuple[str, ...] = ("new", "learning")
USER_STATES: tuple[str, ...] = ("new", "learning", "mastered", "known", "removed")
ORIGINS: tuple[str, ...] = ("browse", "custom", "screen", "push", "import")
LOG_CONTEXTS: tuple[str, ...] = ("today", "extra", "screen_page", "browse", "bank", "detail", "api", "consolidate", "onboarding")
MARK_ACTIONS: tuple[str, ...] = ("unfamiliar", "known", "mastered", "master", "remove", "reset", "restore", "add_custom", "import")
ADD_LIKE_ACTIONS: tuple[str, ...] = ("unfamiliar", "add_custom", "import")
WAITING_CONTEXTS: tuple[str, ...] = ("detail", "today", "extra")  # the user is looking at the word → content priority 10

PRIORITY_DEFAULT = 50
PRIORITY_READD = 80
PRIORITY_CUSTOM = 100
EASE_START = 2.5
EASE_MIN = 1.3
READD_EASE_DELTA = 0.2
RESTORE_WINDOW = timedelta(minutes=15)
CONTENT_PRIORITY_WAITING = 10
CONTENT_PRIORITY_BANK = 20

MAX_ADD_TOKENS = 50
MAX_NOTE_CHARS = 500
CUSTOM_DAILY_CAP = 200  # custom adds per user per day (DESIGN §10); imports share it
STUDY_TODAY_DAILY_CAP = 20  # `study_today` extras appended to today's batch per user per day (DESIGN §5.3)
IMPORT_MAX_ROWS = 2000
IMPORT_RESULT_ROWS = 200
CONTENT_REQUESTS_DAILY_CAP = 60
IMAGE_REFRESH_DAILY_CAP = 20
REPORTS_DAILY_CAP = 20
EXPORT_COLUMNS: tuple[str, ...] = (
    "word",
    "phonetic",
    "translation",
    "state",
    "origin",
    "note",
    "times_added",
    "added_at",
    "mastered_at",
    "ease",
    "interval_days",
    "repetitions",
    "lapses",
    "due_at",
)

ATTENTION_INVALID_MSG = "未识别为英文单词"  # DESIGN §5.2 step 4: an exact hit on a word Claude already rejected
DEFAULT_TIMEZONE = "Asia/Shanghai"
# The K-12 defaults of a settings row that does not exist yet — the same values as the user_settings DDL defaults
# (0011_primary_stage.sql: stages_json '["xs","zk"]', current_stage 1 = stage_to_index("xs")); test_bank_defaults binds the
# two so they cannot drift apart (PLAN §0 / SM D-4: what a child who taps "next" on the welcome page without choosing gets).
DEFAULT_STAGES: tuple[str, ...] = ("xs", "zk")
DEFAULT_CURRENT_STAGE = 1  # = schemas.stage_to_index("xs")

# DESIGN §4 "Context → origin" table (a row records how it FIRST entered the bank)
CONTEXT_ORIGIN: dict[str, str] = {
    "browse": "browse",
    "detail": "browse",
    "bank": "browse",
    "api": "browse",
    "consolidate": "browse",
    "today": "push",
    "extra": "push",
    "screen_page": "screen",
    "onboarding": "screen",
}

_SPLIT_RE = re.compile(r"[\n\r,;，；\t]+")
_SNAPSHOT_KEYS: tuple[str, ...] = (
    "state",
    "ease",
    "interval_days",
    "step",
    "repetitions",
    "lapses",
    "consecutive_good",
    "due_at",
    "last_graded_at",
    "mastered_at",
    "priority",
    "times_added",
)
_RESTORE_KEYS: tuple[str, ...] = (  # what mark:restore writes back (DESIGN §4): never priority / times_added / added_at
    "state",
    "ease",
    "interval_days",
    "step",
    "repetitions",
    "lapses",
    "consecutive_good",
    "due_at",
    "last_graded_at",
    "mastered_at",
)


# ------------------------------------------------------------------------------------------ small helpers
def coerce_now(now: datetime | str | None) -> tuple[datetime, str]:
    """``(aware UTC datetime, ISO string)`` from a datetime, an ISO string or None (system clock)."""
    if now is None:
        dt = parse_iso(now_iso())
    elif isinstance(now, datetime):
        dt = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        dt = dt.astimezone(UTC).replace(microsecond=0)
    else:
        dt = parse_iso(str(now))
    return dt, to_iso(dt)


def local_date_str(now: datetime, tz: str) -> str:
    return clock_local_date(now, tz).isoformat()


def origin_for_context(context: str | None) -> str:
    """DESIGN §4 context → ``user_words.origin`` for a row created by a ``mark`` / verdict (``api`` when omitted)."""
    return CONTEXT_ORIGIN.get(context or "api", "browse")


def _row(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> dict[str, Any] | None:
    r = conn.execute(sql, params).fetchone()
    return None if r is None else {k: r[k] for k in r.keys()}


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in conn.execute(sql, params).fetchall()]


def user_settings_row(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    """The ``user_settings`` row with the SCHEMA defaults filled in when the row does not exist yet."""
    row = _row(conn, "SELECT * FROM user_settings WHERE user_id = ?", (int(user_id),))
    base: dict[str, Any] = {
        "user_id": int(user_id),
        "timezone": DEFAULT_TIMEZONE,
        "push_time": "08:00",
        "push_enabled": 1,
        "daily_new_count": 10,
        "daily_screen_count": 15,
        "max_reviews": 60,
        "stages_json": json.dumps(list(DEFAULT_STAGES)),
        "current_stage": DEFAULT_CURRENT_STAGE,
    }
    if row:
        base.update(row)
    base["stages"] = known_stages(base.get("stages_json"), user_id=int(user_id))
    return base


def known_stages(stages_json: Any, *, user_id: int) -> list[str]:
    """The stage codes of a stored ``user_settings.stages_json`` this build knows (``words.STAGES`` = ``schemas.STAGE_ORDER``),
    in stored order; :data:`DEFAULT_STAGES` when none is known.

    A stored row that names no known stage code (a stage retired by a later schema, an older server reading a row a newer
    one wrote, a hand-edited value) falls back to the defaults, but says so — silently dropping codes is how a mislabelled
    stage goes unnoticed (PLAN R-1 / SM D-13 ③; PLAN §2.1). The one helper behind :func:`user_settings_row` (the study,
    screening and recommendation paths) and ``security.settings_row_to_dto`` (``GET /api/auth/me`` / ``GET /api/settings``),
    so the SPA boots on exactly the stages the server studies with instead of a 500 (impl-review final F2).
    """
    try:
        stages = json.loads(stages_json or "[]")
    except (TypeError, ValueError):
        stages = []
    known = [s for s in stages if s in words.STAGES] if isinstance(stages, list) else []
    if not known:
        log.warning(
            "stage_fallback: user %s stages_json %r has no known stage code; using %r",
            int(user_id),
            stages_json,
            list(DEFAULT_STAGES),
            extra={"event": "stage_fallback", "user_id": int(user_id)},
        )
    return known or list(DEFAULT_STAGES)


def current_stage_index(settings_row: Mapping[str, Any]) -> int:
    """The 主攻阶段 of a settings row as its 1..5 column index (``user_settings.current_stage``, API.md §9.1).

    ``None`` / a missing key → :data:`DEFAULT_CURRENT_STAGE`. Written as an explicit ``is None`` test rather than
    ``int(x or DEFAULT)`` on purpose: no stage index is 0 today, but a falsy index must never be silently replaced by the
    default should the numbering ever change again (PLAN R-1 / SM D-16). screen.py and batches.py call this for the
    ``learn_order.stage_distance_sql`` ordering.
    """
    cur = settings_row.get("current_stage")
    return DEFAULT_CURRENT_STAGE if cur is None else int(cur)


def user_timezone(conn: sqlite3.Connection, user_id: int) -> str:
    return str(user_settings_row(conn, user_id)["timezone"] or DEFAULT_TIMEZONE)


def my_row(conn: sqlite3.Connection, user_id: int, word_id: int) -> dict[str, Any] | None:
    return _row(conn, "SELECT * FROM user_words WHERE user_id = ? AND word_id = ?", (int(user_id), int(word_id)))


def visible_word(conn: sqlite3.Connection, me: Mapping[str, Any] | int, word_id: int) -> dict[str, Any]:
    """The ``words`` row for an explicit id (merges followed) or 404 ``word_not_found`` when it does not exist or is
    outside the API.md §1 visibility rule for ``me`` (a user dict from ``deps.current_user`` or a bare id; admins see all)."""
    row = words.word_row(conn, int(word_id))
    if row is None:
        raise ApiError("word_not_found")
    final, _ = words.follow_merge(conn, row)
    if isinstance(me, Mapping):
        if me.get("role") == "admin":
            return final
        uid = int(me["id"])
    else:
        uid = int(me)
    if not words.is_visible(conn, final, uid):
        raise ApiError("word_not_found")
    return final


def today_batch(conn: sqlite3.Connection, user_id: int, local_date: str) -> dict[str, Any] | None:
    return _row(conn, "SELECT * FROM push_batches WHERE user_id = ? AND local_date = ?", (int(user_id), local_date))


def open_batch_ids(conn: sqlite3.Connection, user_id: int, local_date: str) -> list[int]:
    """Batches that are still gradable (today's and yesterday's, DESIGN §6.3 late sessions)."""
    yesterday = (datetime.fromisoformat(local_date) - timedelta(days=1)).date().isoformat()
    return [int(r[0]) for r in conn.execute("SELECT id FROM push_batches WHERE user_id = ? AND local_date >= ?", (int(user_id), yesterday))]


def ai_enabled(conn: sqlite3.Connection, cfg: Any) -> bool:
    """The kill switch (CLAUDE_INTEGRATION §7): ``WD_AI_ENABLED`` and ``kv.claude.enabled``."""
    if cfg is not None and not getattr(cfg, "ai_enabled", True):
        return False
    return db.kv_get(conn, "claude.enabled") != "0"


def ai_paused_until(conn: sqlite3.Connection, now: str, *, cfg: Any = None, kind: str | None = None) -> str | None:
    """When AI may serve again, or None when it can right now (the user-facing gates: 生成例句, 立即整理, prefetch, batches).

    With ``cfg`` and ``kind`` the answer is CLAUDE_INTEGRATION §10's "any provider" rule (``failover.availability``):
    a paused CLI with a configured fallback that may serve ``kind`` is not a pause. Without them the legacy meaning
    applies: ``kv.claude.paused_until`` or the admin's global pause (``budget.paused_until``).
    """
    from ..ai import budget  # local import: services → ai must not become a module cycle at import time

    if cfg is not None and kind is not None:
        from ..ai import failover

        avail = failover.availability(conn, cfg, kind=kind, now=now)
        if avail.ok:
            return None
        if avail.resumes_at:
            return avail.resumes_at
        # not routable right now with no known end (e.g. openai_http mode and a kind outside WD_AI_FALLBACK_KINDS):
        # answer like claude_call's default deferral instead of pretending AI is available
        return budget.paused_until(conn, now) or to_iso(parse_iso(now) + timedelta(minutes=30))
    return budget.paused_until(conn, now)


def content_deferred_until(conn: sqlite3.Connection, word_id: int, *, now: str, cfg: Any = None) -> str | None:
    """API.md 24 ``deferred_until`` for a ``queued`` word: the live job's far-future ``run_after`` (budget deferral) or
    ``kv.claude.paused_until``; with the kill switch off entirely it is ``paused_until`` or None (``eta_s`` is null then too)."""
    if not ai_enabled(conn, cfg):
        return ai_paused_until(conn, now)
    return words.content_deferred_until(conn, int(word_id), now=now, cfg=cfg)


# ------------------------------------------------------------------------------------- query models
def query_model(model_cls: type[BaseModel], params: Mapping[str, Any], *, int_fields: Iterable[str] = ()) -> Any:
    """Validate query parameters against a frozen ``schemas`` model.

    Pydantic does not coerce ``"1"`` into ``Literal[0, 1]``, so the named ``int_fields`` are converted first; any
    validation problem becomes the API.md 400 ``validation_error`` envelope with ``details.fields``.
    """
    data: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        v: Any = value
        if key in int_fields and isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
            v = int(v.strip())
        data[key] = v
    try:
        return model_cls.model_validate(data)
    except ValidationError as e:
        fields: dict[str, str] = {}
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", ())) or "query"
            fields.setdefault(loc, pydantic_error_zh(err))
        raise ApiError("validation_error", details={"fields": fields}) from None


# ------------------------------------------------------------------------------------ daily quotas
def _day_window(now: str) -> tuple[str, int]:
    """UTC day window start and the seconds left until the next window."""
    start = now[:10] + "T00:00:00Z"
    next_day = parse_iso(start) + timedelta(days=1)
    return start, max(1, int((next_day - parse_iso(now)).total_seconds()))


def quota_used(conn: sqlite3.Connection, key: str, now: str) -> int:
    window, _ = _day_window(now)
    row = conn.execute("SELECT window_start, count FROM auth_throttle WHERE key = ?", (key,)).fetchone()
    if row is None or str(row[0]) != window:
        return 0
    return int(row[1])


def quota_consume(conn: sqlite3.Connection, key: str, amount: int, now: str) -> int:
    """Add ``amount`` to the key's counter for the current UTC day; returns the new count."""
    window, _ = _day_window(now)
    with db.maybe_tx(conn):
        used = quota_used(conn, key, now)
        new = used + max(0, int(amount))
        conn.execute(
            "INSERT INTO auth_throttle(key, window_start, count, blocked_until) VALUES (?, ?, ?, NULL) "
            "ON CONFLICT(key) DO UPDATE SET window_start = excluded.window_start, count = excluded.count, blocked_until = NULL",
            (key, window, new),
        )
    return new


def check_daily_quota(conn: sqlite3.Connection, key: str, limit: int, *, now: str, amount: int = 1) -> None:
    """429 ``rate_limited`` (with ``retry_after_s``) unless ``amount`` more units fit under ``limit`` today; consumes them."""
    used = quota_used(conn, key, now)
    if used + amount > limit:
        _, retry = _day_window(now)
        raise ApiError("rate_limited", details={"retry_after_s": retry, "limit": limit})
    quota_consume(conn, key, amount, now)


# ------------------------------------------------------------------------------------- result types
@dataclass
class ActionResult:
    """Outcome of :func:`apply_action` (API.md 26 ``MarkResponse`` fields + what callers need to build their DTOs)."""

    word_id: int
    state: str | None
    mine: dict[str, Any] | None
    status: str  # added | readded | exists | noop | restored
    created: bool = False
    prev_state: str | None = None
    user_word_id: int | None = None
    log_id: int | None = None
    content_job_id: int | None = None
    is_valid_english: int | None = None

    def response(self) -> dict[str, Any]:
        return {"word_id": self.word_id, "state": self.state, "mine": self.mine, "status": self.status}


@dataclass
class AddResult:
    """One ``AddResult`` of API.md §9 (``results[]`` of endpoints 34/35/75)."""

    input: str
    status: str  # added | readded | exists | pending_ai | ambiguous | invalid
    word: dict[str, Any] | None = None
    mine: dict[str, Any] | None = None
    resolved_via: str | None = None
    lemma_note_zh: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    message: str | None = None
    added_to_today: bool = False
    word_id: int | None = None
    created: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "status": self.status,
            "word": self.word,
            "mine": self.mine,
            "resolved_via": self.resolved_via,
            "lemma_note_zh": self.lemma_note_zh,
            "candidates": self.candidates,
            "error": self.error,
            "message": self.message,
            "added_to_today": self.added_to_today,
        }


@dataclass
class ImportResult:
    results: list[AddResult]
    rows: int
    skipped: int
    pending_ai_created: int = 0

    def as_dict(self) -> dict[str, Any]:
        d = summarise(self.results)
        d["results"] = [r.as_dict() for r in self.results[:IMPORT_RESULT_ROWS]]
        d["rows"] = self.rows
        d["skipped"] = self.skipped
        return d


def summarise(results: Iterable[AddResult]) -> dict[str, Any]:
    """The ``AddResponse`` counters (``results`` filled by the caller)."""
    counts = {"added": 0, "readded": 0, "exists": 0, "pending_ai": 0, "ambiguous": 0, "invalid": 0}
    for r in results:
        if r.status in counts:
            counts[r.status] += 1
    return {"results": [], **counts}


# ---------------------------------------------------------------------------------------- logging
def srs_snapshot(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """The ``prev_srs_json`` object (SCHEMA ``review_logs``): ``state`` is None for a row that did not exist (∅)."""
    if row is None:
        return {"state": None}
    return {k: row.get(k) for k in _SNAPSHOT_KEYS}


def write_log(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    word_id: int,
    action: str,
    context: str,
    local_date: str,
    now: str,
    user_word_id: int | None = None,
    prev_row: Mapping[str, Any] | None = None,
    new_row: Mapping[str, Any] | None = None,
    prev_state: str | None = None,
    new_state: str | None = None,
    batch_id: int | None = None,
    push_item_id: int | None = None,
    client_event_id: str | None = None,
    elapsed_ms: int | None = None,
    prev_srs_json: Mapping[str, Any] | None = None,
    result_json: Mapping[str, Any] | None = None,
) -> int:
    """Append one ``review_logs`` row (the interval/ease columns come from ``prev_row`` / ``new_row`` when given)."""
    if context not in LOG_CONTEXTS:
        raise ValueError(f"unknown review_logs.context {context!r}")
    cur = conn.execute(
        "INSERT INTO review_logs(user_id, word_id, user_word_id, batch_id, push_item_id, client_event_id, action, context, "
        "prev_state, new_state, prev_interval, new_interval, prev_ease, new_ease, prev_srs_json, elapsed_ms, result_json, local_date, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            int(user_id),
            int(word_id),
            user_word_id,
            batch_id,
            push_item_id,
            client_event_id,
            action,
            context,
            prev_state,
            new_state,
            None if prev_row is None else prev_row.get("interval_days"),
            None if new_row is None else new_row.get("interval_days"),
            None if prev_row is None else prev_row.get("ease"),
            None if new_row is None else new_row.get("ease"),
            None if prev_srs_json is None else json.dumps(prev_srs_json, ensure_ascii=False),
            elapsed_ms,
            None if result_json is None else json.dumps(result_json, ensure_ascii=False),
            local_date,
            now,
        ),
    )
    return int(cur.lastrowid)


def push_item_row(conn: sqlite3.Connection, push_item_id: int | None) -> dict[str, Any] | None:
    if push_item_id is None:
        return None
    return _row(conn, "SELECT * FROM push_items WHERE id = ?", (int(push_item_id),))


def expire_open_suggestions(conn: sqlite3.Connection, user_word_id: int, now: str) -> int:
    cur = conn.execute(
        "UPDATE bank_suggestions SET status = 'expired', resolved_at = ? WHERE user_word_id = ? AND status = 'open'",
        (now, int(user_word_id)),
    )
    return int(cur.rowcount)


def clear_attention(conn: sqlite3.Connection, user_word_id: int, now: str) -> None:
    """Reset the 待处理 columns of a row (API.md 36 ``keep`` / endpoint 37 / a repoint onto another word): they describe
    the string the row carried, not the one it carries now."""
    conn.execute(
        "UPDATE user_words SET needs_attention = 0, attention_msg = NULL, suggested_word_id = NULL, updated_at = ? WHERE id = ?",
        (now, int(user_word_id)),
    )


def enqueue_content_if_needed(conn: sqlite3.Connection, word: Mapping[str, Any], *, priority: int, now: str) -> int | None:
    """``generate_content`` for a VALIDATED word lacking content (DESIGN §4 / CLAUDE_INTEGRATION §6.1 enqueue rule).

    Never for ``is_valid_english IS NULL`` (``lookup_word`` is a provisional word's single content trigger) nor for
    ``is_valid_english = 0`` or merged words. Sets ``words.content_state = 'queued'``.
    """
    if word.get("is_valid_english") != 1 or word.get("merged_into_word_id") is not None:
        return None
    if (word.get("content_state") or "none") not in ("none", "failed"):
        return None
    wid = int(word["id"])
    job_id = queue.enqueue(conn, "generate_content", {"word_id": wid}, dedupe_key=f"content:{wid}", priority=int(priority), now=now)
    conn.execute("UPDATE words SET content_state = 'queued', updated_at = ? WHERE id = ?", (now, wid))
    return job_id


def _uw_dict(conn: sqlite3.Connection, user_word_id: int, user_id: int) -> dict[str, Any] | None:
    row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (int(user_word_id),))
    return None if row is None else words.user_word_dict(conn, row, user_id)


def _stats(
    conn: sqlite3.Connection,
    user_id: int,
    local_date: str,
    *,
    action: str,
    context: str,
    new_state: str | None,
    item_kind: str | None,
    elapsed_ms: int | None = None,
    prev_state: str | None = None,
    undone: Mapping[str, Any] | None = None,
) -> None:
    stats_core.on_action(
        conn,
        user_id,
        local_date,
        action=action,
        context=context,
        new_state=new_state,
        item_kind=item_kind,
        elapsed_ms=elapsed_ms,
        prev_state=prev_state,
        undone=undone,
    )


# ------------------------------------------------------------------------------------ state machine
def apply_action(
    conn: sqlite3.Connection,
    user_id: int,
    word_id: int,
    action: str,
    *,
    origin: str,
    context: str,
    note: str | None = None,
    input_text: str | None = None,
    now: datetime | str | None,
    tz: str,
    batch_id: int | None = None,
    push_item_id: int | None = None,
    client_event_id: str | None = None,
    elapsed_ms: int | None = None,
) -> ActionResult:
    """The DESIGN §4 state machine for one ``(user, word)``; one transaction, one ``review_logs`` row, ``daily_stats``.

    ``action`` is an API.md 26 ``MarkAction`` (``unfamiliar`` / ``known`` / ``mastered`` (alias ``master``) /
    ``remove`` / ``reset`` / ``restore``) or one of the add variants ``add_custom`` / ``import`` — the same ∅→``new``
    transition as ``unfamiliar`` logged under that action (DESIGN §4 mapping; a re-add is always logged ``readd``).
    ``origin`` is used only when a row is created (the router derives it from ``context`` with
    :func:`origin_for_context`; adds pass ``custom`` / ``import``). ``push_item_id`` / ``batch_id`` are recorded on
    the log row (WP4 passes them for in-batch grades); ``push_items.result`` itself is written by the grader
    (WP4) — ``restore`` clears it. Raises ``ApiError('invalid_transition')`` / ``ApiError('undo_expired')`` /
    ``ApiError('word_not_found')``.
    """
    if action not in MARK_ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    if action == "master":
        action = "mastered"
    if origin not in ORIGINS:
        raise ValueError(f"unknown origin {origin!r}")
    if context not in LOG_CONTEXTS:
        raise ValueError(f"unknown context {context!r}")
    now_dt, now_s = coerce_now(now)
    today = local_date_str(now_dt, tz)
    if note is not None:
        note = note.strip()[:MAX_NOTE_CHARS] or None

    with db.maybe_tx(conn):
        word = words.word_row(conn, int(word_id))
        if word is None:
            raise ApiError("word_not_found")
        word, _ = words.follow_merge(conn, word)
        wid = int(word["id"])
        row = my_row(conn, user_id, wid)
        prev_state = None if row is None else str(row["state"])
        item = push_item_row(conn, push_item_id)
        item_kind = None if item is None else str(item["kind"])
        if item is not None and batch_id is None:
            batch_id = int(item["batch_id"])
        common = dict(user_id=int(user_id), word_id=wid, context=context, local_date=today, now=now_s, batch_id=batch_id, push_item_id=push_item_id, client_event_id=client_event_id, elapsed_ms=elapsed_ms)

        if action in ADD_LIKE_ACTIONS:
            return _apply_unfamiliar(conn, user_id, word, row, action, origin, context, note, input_text, now_s, today, item_kind, common)
        if action == "known":
            return _apply_known(conn, user_id, word, row, now_s, today, item_kind, origin, common)
        if action == "mastered":
            return _apply_mastered(conn, user_id, word, row, now_s, today, item_kind, origin, common)
        if action == "remove":
            return _apply_remove(conn, user_id, word, row, now_s, today, common)
        if action == "reset":
            return _apply_reset(conn, user_id, word, row, now_s, today, common)
        return _apply_restore(conn, user_id, word, row, now_dt, now_s, today, tz, common)


def _insert_row(
    conn: sqlite3.Connection,
    user_id: int,
    word: Mapping[str, Any],
    *,
    state: str,
    origin: str,
    priority: int,
    note: str | None,
    input_text: str | None,
    now: str,
    needs_attention: int = 0,
    attention_msg: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO user_words(user_id, word_id, state, origin, priority, note, input_text, needs_attention, attention_msg, "
        "ease, interval_days, step, repetitions, lapses, consecutive_good, due_at, last_graded_at, times_pushed, times_added, "
        "added_at, first_added_at, mastered_at, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, NULL, NULL, 0, 1, ?, ?, NULL, ?, ?)",
        (int(user_id), int(word["id"]), state, origin, int(priority), note, input_text, int(needs_attention), attention_msg, EASE_START, now, now, now, now),
    )
    return int(cur.lastrowid)


def _apply_unfamiliar(conn, user_id, word, row, action, origin, context, note, input_text, now, today, item_kind, common) -> ActionResult:
    wid = int(word["id"])
    log_action = "unfamiliar" if action == "unfamiliar" else action
    if row is None:  # ∅ → new
        priority = PRIORITY_CUSTOM if origin == "custom" else PRIORITY_DEFAULT
        needs_attention, msg = 0, None
        if word.get("is_valid_english") == 0:  # a string someone added and Claude rejected (DESIGN §5.2 step 4)
            needs_attention, msg = 1, ATTENTION_INVALID_MSG
        uw_id = _insert_row(conn, user_id, word, state="new", origin=origin, priority=priority, note=note, input_text=input_text, now=now, needs_attention=needs_attention, attention_msg=msg)
        new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (uw_id,))
        log_id = write_log(conn, action=log_action, user_word_id=uw_id, prev_row=None, new_row=new_row, prev_state=None, new_state="new", **common)
        _stats(conn, user_id, today, action=log_action, context=context, new_state="new", item_kind=item_kind, prev_state=None)
        job_id = enqueue_content_if_needed(conn, word, priority=CONTENT_PRIORITY_WAITING if context in WAITING_CONTEXTS else CONTENT_PRIORITY_BANK, now=now)
        return ActionResult(wid, "new", words.user_word_dict(conn, new_row, user_id), "added", created=True, prev_state=None, user_word_id=uw_id, log_id=log_id, content_job_id=job_id, is_valid_english=word.get("is_valid_english"))

    state = str(row["state"])
    if state in BANK_STATES:  # idempotent
        if note is not None:
            conn.execute("UPDATE user_words SET note = ?, updated_at = ? WHERE id = ?", (note, now, row["id"]))
        log_id = None
        if action == "unfamiliar":  # DESIGN §4: logged (prev_state set ⇒ stats nothing, never undoable)
            log_id = write_log(conn, action="unfamiliar", user_word_id=int(row["id"]), prev_row=row, new_row=row, prev_state=state, new_state=state, **common)
            _stats(conn, user_id, today, action="unfamiliar", context=context, new_state=state, item_kind=item_kind, prev_state=state)
        return ActionResult(wid, state, _uw_dict(conn, int(row["id"]), user_id), "exists", prev_state=state, user_word_id=int(row["id"]), log_id=log_id, is_valid_english=word.get("is_valid_english"))

    # mastered / known / removed → new : deliberate re-add
    conn.execute(
        "UPDATE user_words SET state = 'new', times_added = times_added + 1, priority = ?, added_at = ?, step = 0, interval_days = 0, "
        "due_at = NULL, consecutive_good = 0, ease = CASE WHEN state = 'mastered' THEN MAX(?, ROUND(ease - ?, 2)) ELSE ease END, "
        "mastered_at = NULL, note = COALESCE(?, note), input_text = COALESCE(?, input_text), updated_at = ? WHERE id = ?",
        (PRIORITY_READD, now, EASE_MIN, READD_EASE_DELTA, note, input_text, now, row["id"]),
    )
    new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
    log_id = write_log(conn, action="readd", user_word_id=int(row["id"]), prev_row=row, new_row=new_row, prev_state=state, new_state="new", **common)
    _stats(conn, user_id, today, action="readd", context=context, new_state="new", item_kind=item_kind, prev_state=state)
    job_id = enqueue_content_if_needed(conn, word, priority=CONTENT_PRIORITY_WAITING if context in WAITING_CONTEXTS else CONTENT_PRIORITY_BANK, now=now)
    return ActionResult(wid, "new", words.user_word_dict(conn, new_row, user_id), "readded", prev_state=state, user_word_id=int(row["id"]), log_id=log_id, content_job_id=job_id, is_valid_english=word.get("is_valid_english"))


def _master_row(conn, user_id, row, *, log_action: str, now: str, today: str, item_kind: str | None, context: str, common) -> ActionResult:
    """``new``/``learning`` → ``mastered`` (DESIGN §4): snapshot first, then freeze the row."""
    snapshot = srs_snapshot(row)
    conn.execute("UPDATE user_words SET state = 'mastered', mastered_at = ?, due_at = NULL, updated_at = ? WHERE id = ?", (now, now, row["id"]))
    expire_open_suggestions(conn, int(row["id"]), now)
    new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
    log_id = write_log(conn, action=log_action, user_word_id=int(row["id"]), prev_row=row, new_row=new_row, prev_state=str(row["state"]), new_state="mastered", prev_srs_json=snapshot, **common)
    _stats(conn, user_id, today, action=log_action, context=context, new_state="mastered", item_kind=item_kind, prev_state=str(row["state"]), elapsed_ms=common.get("elapsed_ms"))
    return ActionResult(int(row["word_id"]), "mastered", words.user_word_dict(conn, new_row, user_id), "added", prev_state=str(row["state"]), user_word_id=int(row["id"]), log_id=log_id)


def _apply_known(conn, user_id, word, row, now, today, item_kind, origin, common) -> ActionResult:
    wid = int(word["id"])
    context = common["context"]
    if row is None:  # ∅ → known
        uw_id = _insert_row(conn, user_id, word, state="known", origin=origin, priority=PRIORITY_DEFAULT, note=None, input_text=None, now=now)
        new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (uw_id,))
        log_id = write_log(conn, action="known", user_word_id=uw_id, prev_row=None, new_row=new_row, prev_state=None, new_state="known", prev_srs_json=srs_snapshot(None), **common)
        _stats(conn, user_id, today, action="known", context=context, new_state="known", item_kind=item_kind, prev_state=None)
        return ActionResult(wid, "known", words.user_word_dict(conn, new_row, user_id), "added", created=True, user_word_id=uw_id, log_id=log_id, is_valid_english=word.get("is_valid_english"))
    state = str(row["state"])
    if state in BANK_STATES:  # synonym of mastered when already in the bank
        return _master_row(conn, user_id, row, log_action="known", now=now, today=today, item_kind=item_kind, context=context, common=common)
    if state in ("mastered", "known"):
        return ActionResult(wid, state, _uw_dict(conn, int(row["id"]), user_id), "noop", prev_state=state, user_word_id=int(row["id"]))
    # removed → known (the word was dropped without claiming mastery; the user now says 认识)
    snapshot = srs_snapshot(row)
    conn.execute("UPDATE user_words SET state = 'known', due_at = NULL, updated_at = ? WHERE id = ?", (now, row["id"]))
    new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
    log_id = write_log(conn, action="known", user_word_id=int(row["id"]), prev_row=row, new_row=new_row, prev_state=state, new_state="known", prev_srs_json=snapshot, **common)
    _stats(conn, user_id, today, action="known", context=context, new_state="known", item_kind=item_kind, prev_state=state)
    return ActionResult(wid, "known", words.user_word_dict(conn, new_row, user_id), "added", prev_state=state, user_word_id=int(row["id"]), log_id=log_id)


def _apply_mastered(conn, user_id, word, row, now, today, item_kind, origin, common) -> ActionResult:
    wid = int(word["id"])
    context = common["context"]
    if row is None:  # ∅ → known ("treated as known, never studied"; logged and counted as the known transition it is)
        return _apply_known(conn, user_id, word, None, now, today, item_kind, origin, common)
    state = str(row["state"])
    if state in BANK_STATES:
        return _master_row(conn, user_id, row, log_action="master", now=now, today=today, item_kind=item_kind, context=context, common=common)
    if state in ("mastered", "known"):
        return ActionResult(wid, state, _uw_dict(conn, int(row["id"]), user_id), "noop", prev_state=state, user_word_id=int(row["id"]))
    # removed → mastered
    snapshot = srs_snapshot(row)
    conn.execute("UPDATE user_words SET state = 'mastered', mastered_at = ?, due_at = NULL, updated_at = ? WHERE id = ?", (now, now, row["id"]))
    new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
    log_id = write_log(conn, action="master", user_word_id=int(row["id"]), prev_row=row, new_row=new_row, prev_state=state, new_state="mastered", prev_srs_json=snapshot, **common)
    _stats(conn, user_id, today, action="master", context=context, new_state="mastered", item_kind=item_kind, prev_state=state, elapsed_ms=common.get("elapsed_ms"))
    return ActionResult(wid, "mastered", words.user_word_dict(conn, new_row, user_id), "added", prev_state=state, user_word_id=int(row["id"]), log_id=log_id)


def _apply_remove(conn, user_id, word, row, now, today, common) -> ActionResult:
    wid = int(word["id"])
    if row is None:
        raise ApiError("invalid_transition", details={"from": None, "action": "remove"})
    state = str(row["state"])
    if state == "removed":
        return ActionResult(wid, state, _uw_dict(conn, int(row["id"]), user_id), "noop", prev_state=state, user_word_id=int(row["id"]))
    conn.execute("UPDATE user_words SET state = 'removed', due_at = NULL, updated_at = ? WHERE id = ?", (now, row["id"]))
    expire_open_suggestions(conn, int(row["id"]), now)
    new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
    log_id = write_log(conn, action="remove", user_word_id=int(row["id"]), prev_row=row, new_row=new_row, prev_state=state, new_state="removed", **common)
    _stats(conn, user_id, today, action="remove", context=common["context"], new_state="removed", item_kind=None, prev_state=state)
    return ActionResult(wid, "removed", words.user_word_dict(conn, new_row, user_id), "added", prev_state=state, user_word_id=int(row["id"]), log_id=log_id)


def _apply_reset(conn, user_id, word, row, now, today, common) -> ActionResult:
    wid = int(word["id"])
    if row is None:
        raise ApiError("invalid_transition", details={"from": None, "action": "reset"})
    state = str(row["state"])
    if state == "new":
        return ActionResult(wid, state, _uw_dict(conn, int(row["id"]), user_id), "noop", prev_state=state, user_word_id=int(row["id"]))
    if state != "learning":
        raise ApiError("invalid_transition", details={"from": state, "action": "reset"})
    conn.execute(
        "UPDATE user_words SET state = 'new', ease = ?, interval_days = 0, step = 0, repetitions = 0, lapses = 0, consecutive_good = 0, "
        "due_at = NULL, last_graded_at = NULL, updated_at = ? WHERE id = ?",
        (EASE_START, now, row["id"]),
    )
    new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
    log_id = write_log(conn, action="reset", user_word_id=int(row["id"]), prev_row=row, new_row=new_row, prev_state=state, new_state="new", **common)
    _stats(conn, user_id, today, action="reset", context=common["context"], new_state="new", item_kind=None, prev_state=state)
    return ActionResult(wid, "new", words.user_word_dict(conn, new_row, user_id), "added", prev_state=state, user_word_id=int(row["id"]), log_id=log_id)


# -------------------------------------------------------------------------------------------- restore
def latest_transition_log(conn: sqlite3.Connection, user_id: int, word_id: int) -> dict[str, Any] | None:
    """The user's most recent ``review_logs`` row on the word, ignoring the non-transition ``note``/``attention`` rows."""
    return _row(
        conn,
        "SELECT * FROM review_logs WHERE user_id = ? AND word_id = ? AND action NOT IN ('note', 'attention') ORDER BY created_at DESC, id DESC LIMIT 1",
        (int(user_id), int(word_id)),
    )


def _undo_expired(reason: str, **details: Any) -> ApiError:
    return ApiError("undo_expired", details={"reason": reason, **details})


def _apply_restore(conn, user_id, word, row, now_dt, now_s, today, tz, common) -> ActionResult:
    """DESIGN §4 ``restore``: undo the most recent ``master``/``known`` (snapshot back) or ∅→``unfamiliar`` (row deleted)."""
    wid = int(word["id"])
    undone = latest_transition_log(conn, user_id, wid)
    if undone is None:
        raise _undo_expired("no_transition")
    if parse_iso(str(undone["created_at"])) < now_dt - RESTORE_WINDOW:
        raise _undo_expired("window", undone_at=undone["created_at"])
    if row is None:
        raise _undo_expired("row_gone")
    item = push_item_row(conn, undone.get("push_item_id"))
    item_kind = None if item is None else str(item["kind"])
    undone_info = {
        "action": undone["action"],
        "new_state": undone["new_state"],
        "prev_state": undone["prev_state"],
        "context": undone["context"],
        "item_kind": item_kind,
    }
    state = str(row["state"])
    action = str(undone["action"])

    if action in ("master", "known"):
        if state != undone["new_state"] or state not in ("mastered", "known"):
            raise _undo_expired("state_changed", state=state)
        try:
            snapshot = json.loads(undone["prev_srs_json"] or "{}")
        except ValueError:
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        if snapshot.get("state") is None:  # a ∅-origin known row: delete it again
            conn.execute("DELETE FROM user_words WHERE id = ?", (row["id"],))
            new_state, mine, uw_id = None, None, None
        else:
            values = {k: row.get(k) for k in _RESTORE_KEYS}
            values.update({k: snapshot[k] for k in _RESTORE_KEYS if k in snapshot})
            if values["state"] not in USER_STATES:
                raise _undo_expired("bad_snapshot")
            conn.execute(
                "UPDATE user_words SET state = :state, ease = :ease, interval_days = :interval_days, step = :step, repetitions = :repetitions, "
                "lapses = :lapses, consecutive_good = :consecutive_good, due_at = :due_at, last_graded_at = :last_graded_at, "
                "mastered_at = :mastered_at, updated_at = :now WHERE id = :id",
                {**values, "now": now_s, "id": row["id"]},
            )
            new_state = str(values["state"])
            uw_id = int(row["id"])
            mine = _uw_dict(conn, uw_id, user_id)
        if item is not None:
            conn.execute("UPDATE push_items SET result = NULL, graded_at = NULL WHERE id = ?", (item["id"],))
        log_id = write_log(conn, action="restore", user_word_id=uw_id, prev_row=row, new_row=None if mine is None else _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],)), prev_state=state, new_state=new_state, **{**common, "push_item_id": undone.get("push_item_id"), "batch_id": undone.get("batch_id")})
        _stats(conn, user_id, today, action="restore", context=common["context"], new_state=new_state, item_kind=item_kind, undone=undone_info)
        return ActionResult(wid, new_state, mine, "restored", prev_state=state, user_word_id=uw_id, log_id=log_id)

    if action == "unfamiliar" and undone["prev_state"] is None:
        if state != "new" or int(row["repetitions"] or 0) != 0:
            raise _undo_expired("graded_since", state=state)
        conn.execute("DELETE FROM user_words WHERE id = ?", (row["id"],))
        if item is not None:  # the screen push item that produced the row
            conn.execute("UPDATE push_items SET result = NULL, graded_at = NULL, user_word_id = NULL WHERE id = ?", (item["id"],))
        open_ids = open_batch_ids(conn, user_id, today)
        if open_ids:
            marks = ",".join("?" * len(open_ids))
            conn.execute(
                f"DELETE FROM push_items WHERE word_id = ? AND kind = 'new' AND result IS NULL AND batch_id IN ({marks})",
                (wid, *open_ids),
            )
        log_id = write_log(conn, action="restore", user_word_id=None, prev_row=row, new_row=None, prev_state="new", new_state=None, **{**common, "push_item_id": undone.get("push_item_id"), "batch_id": undone.get("batch_id")})
        _stats(conn, user_id, today, action="restore", context=common["context"], new_state=None, item_kind=item_kind, undone=undone_info)
        return ActionResult(wid, None, None, "restored", prev_state="new", user_word_id=None, log_id=log_id)

    raise _undo_expired("not_undoable", action=action)


# ------------------------------------------------------------------------------------- 待处理 flags
def set_attention(conn: sqlite3.Connection, user_id: int, word_id: int, decision: str, now: datetime | str | None) -> dict[str, Any]:
    """``PATCH /api/bank/{id} {attention: 'keep' | 'retry'}`` (API.md 36, CLAUDE_INTEGRATION §6.5); returns the ``UserWord``.

    ``retry`` only while ``words.is_valid_english IS NULL`` (409 ``invalid_transition`` otherwise): one live
    ``lookup_word`` job through the UPSERT (``lookup:<id>``, priority 10, ``run_after = now``), ``attention_msg = NULL``,
    ``needs_attention`` stays 1 (badge 重新校验中). ``keep`` clears the flag (仅收藏 for ``is_valid_english = 0``);
    on an unflagged row it is a 200 no-op. Both log ``review_logs.action = 'attention'``.
    """
    if decision not in ("keep", "retry"):
        raise ValueError(f"unknown attention decision {decision!r}")
    now_dt, now_s = coerce_now(now)
    with db.maybe_tx(conn):
        word = words.word_row(conn, int(word_id))
        if word is None:
            raise ApiError("word_not_found")
        word, _ = words.follow_merge(conn, word)
        row = my_row(conn, user_id, int(word["id"]))
        if row is None:
            raise ApiError("word_not_found")
        today = local_date_str(now_dt, user_timezone(conn, user_id))
        if decision == "retry":
            if word.get("is_valid_english") is not None:
                raise ApiError("invalid_transition", details={"from": "validated", "action": "retry"})
            words.enqueue_lookup(conn, int(word["id"]), now_s, delay_s=0)
            conn.execute("UPDATE user_words SET needs_attention = 1, attention_msg = NULL, updated_at = ? WHERE id = ?", (now_s, row["id"]))
        else:
            if not int(row.get("needs_attention") or 0):
                return words.user_word_dict(conn, _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],)), user_id)
            conn.execute(
                "UPDATE user_words SET needs_attention = 0, attention_msg = NULL, suggested_word_id = NULL, updated_at = ? WHERE id = ?",
                (now_s, row["id"]),
            )
        write_log(
            conn,
            user_id=int(user_id),
            word_id=int(word["id"]),
            action="attention",
            context="api",
            local_date=today,
            now=now_s,
            user_word_id=int(row["id"]),
            prev_row=row,
            new_row=row,
            prev_state=str(row["state"]),
            new_state=str(row["state"]),
            result_json={"decision": decision},
        )
        _stats(conn, user_id, today, action="attention", context="api", new_state=str(row["state"]), item_kind=None, prev_state=str(row["state"]))
        return words.user_word_dict(conn, _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],)), user_id)


def update_note(conn: sqlite3.Connection, user_id: int, word_id: int, note: str | None, now: datetime | str | None) -> dict[str, Any]:
    """``PATCH /api/bank/{id} {note}`` — the private 备注 (log ``note``)."""
    now_dt, now_s = coerce_now(now)
    note = None if note is None else (note.strip()[:MAX_NOTE_CHARS] or None)
    with db.maybe_tx(conn):
        row = my_row(conn, user_id, int(word_id))
        if row is None:
            raise ApiError("word_not_found")
        conn.execute("UPDATE user_words SET note = ?, updated_at = ? WHERE id = ?", (note, now_s, row["id"]))
        today = local_date_str(now_dt, user_timezone(conn, user_id))
        write_log(conn, user_id=int(user_id), word_id=int(word_id), action="note", context="api", local_date=today, now=now_s, user_word_id=int(row["id"]), prev_row=row, new_row=row, prev_state=str(row["state"]), new_state=str(row["state"]))
        return words.user_word_dict(conn, _row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],)), user_id)


# ------------------------------------------------------------------------------------------ bulk add
def split_tokens(text: str) -> list[str]:
    """DESIGN §5.3: split on ``\\n , ; ， ； \\t`` (never on spaces), drop empties, keep order."""
    return [t.strip() for t in _SPLIT_RE.split(text or "") if t and t.strip()]


def _append_to_today(conn: sqlite3.Connection, user_id: int, word_id: int, kind: str, now: str) -> int | None:
    """WP4's ``batches.append_to_today`` — the new ``push_items`` row id, or None (``added_to_today:false``) when there
    is no batch today / the word is already in it. Imported here because ``batches`` imports this module."""
    from . import batches

    try:
        result = batches.append_to_today(conn, int(user_id), int(word_id), kind, now)
    except ApiError:
        raise
    except Exception:  # noqa: BLE001 - a batch problem must never fail the add itself
        log.exception("append_to_today failed for user %s word %s", user_id, word_id)
        return None
    return int(result) if result is not None else None


def add_one(
    conn: sqlite3.Connection,
    user_id: int,
    text: str,
    *,
    note: str | None,
    study_today: bool,
    now: str,
    tz: str,
    origin: str = "custom",
    log_action: str = "add_custom",
    context: str = "api",
) -> AddResult:
    """Normalise → resolve → add one custom word (DESIGN §5.2/§5.3); the per-item ``AddResult``."""
    norm = words.normalise_input(text)
    if not norm.ok:
        assert isinstance(norm, words.Invalid)
        return AddResult(input=text, status="invalid", error=norm.reason_zh)
    assert isinstance(norm, words.Normalised)
    res = words.resolve(conn, norm.lemma, norm.display, norm.kind, user_id, now=now)
    if res.ambiguous:
        return AddResult(input=text, status="ambiguous", candidates=res.candidates)
    assert res.word_id is not None
    return add_resolved(conn, user_id, int(res.word_id), input_text=text, note=note, study_today=study_today, now=now, tz=tz, resolved_via=str(res.via), lemma_note_zh=res.lemma_note_zh, origin=origin, log_action=log_action, context=context)


def add_resolved(
    conn: sqlite3.Connection,
    user_id: int,
    word_id: int,
    *,
    input_text: str,
    note: str | None,
    study_today: bool,
    now: str,
    tz: str,
    resolved_via: str = "exact",
    lemma_note_zh: str | None = None,
    origin: str = "custom",
    log_action: str = "add_custom",
    context: str = "api",
) -> AddResult:
    """Add a resolved word id (endpoint 35 / the tail of :func:`add_one`)."""
    r = apply_action(conn, user_id, word_id, log_action, origin=origin, context=context, note=note, input_text=input_text, now=now, tz=tz)
    word = words.word_row(conn, r.word_id)
    assert word is not None
    brief = words.word_brief(conn, {**word, "my_state": r.state}, user_id)
    if r.status == "exists":
        status = "exists"
    elif word.get("is_valid_english") is None:  # 待校验 until lookup_word clears it (DESIGN §5.3 pending_ai)
        status = "pending_ai"
    else:
        status = "readded" if r.status == "readded" else "added"
    # `resolved_via` is the resolution's own `via` ('provisional' exactly when resolve() created the row); an exact hit
    # on another holder's still-unvalidated word is 'exact' even though this user's bank row is new
    via = resolved_via if resolved_via in ("exact", "form", "ecdict", "provisional") else "exact"
    message = (r.mine or {}).get("attention_msg") if r.mine else None
    out = AddResult(input=input_text, status=status, word=brief, mine=r.mine, resolved_via=via, lemma_note_zh=lemma_note_zh, message=message, word_id=r.word_id, created=r.created)
    if study_today and status in ("added", "readded") and word.get("is_valid_english") == 1:
        key = study_today_key(user_id)
        if quota_used(conn, key, now) < STUDY_TODAY_DAILY_CAP:  # DESIGN §5.3 cap 20/day; the word itself is added regardless
            if _append_to_today(conn, user_id, r.word_id, "extra", now) is not None:
                quota_consume(conn, key, 1, now)
                out.added_to_today = True
    return out


def study_today_key(user_id: int) -> str:
    """``auth_throttle`` key counting the day's ``study_today`` appends (never ``push_items.kind='extra'`` rows: 再来一组 writes those too)."""
    return f"study_today:user:{int(user_id)}"


def add_custom_words(
    conn: sqlite3.Connection,
    user_id: int,
    text: str,
    note: str | None,
    study_today: bool,
    now: datetime | str | None,
    tz: str,
) -> list[AddResult]:
    """``POST /api/bank/add`` (API.md 34, DESIGN §5.3): ≤ 50 tokens, de-duplicated by lemma, one ``AddResult`` each.

    Raises ``ApiError('too_many_words')``. Quotas (200 adds/day) are checked by the router.
    """
    _, now_s = coerce_now(now)
    tokens = split_tokens(text)
    if len(tokens) > MAX_ADD_TOKENS:
        raise ApiError("too_many_words", details={"count": len(tokens), "max": MAX_ADD_TOKENS})
    results: list[AddResult] = []
    seen: set[str] = set()
    with db.maybe_tx(conn):
        for tok in tokens:
            norm = words.normalise_input(tok)
            if norm.ok:
                assert isinstance(norm, words.Normalised)
                if norm.lemma in seen:
                    continue
                seen.add(norm.lemma)
            results.append(add_one(conn, user_id, tok, note=note, study_today=study_today, now=now_s, tz=tz))
    return results


# --------------------------------------------------------------------------------------------- import
def _import_too_large(rows: int, reason: str) -> ApiError:
    return ApiError("import_too_large", details={"rows": rows, "reason": reason})


def parse_import(fmt: str, data: str) -> list[dict[str, Any]]:
    """Rows of an endpoint-11 export (CSV verbatim, or JSON ``{version, words}`` — a ``review_logs`` key is ignored)."""
    if fmt == "json":
        try:
            parsed = json.loads(data)
        except ValueError:
            raise _import_too_large(0, "invalid_json") from None
        rows_in = parsed.get("words") if isinstance(parsed, dict) else None
        if not isinstance(rows_in, list):
            raise _import_too_large(0, "missing_words")
        rows = [r for r in rows_in if isinstance(r, dict)]
        if len(rows) != len(rows_in):
            raise _import_too_large(len(rows_in), "bad_rows")
        return rows
    if fmt == "csv":
        try:
            reader = csv.DictReader(io.StringIO(data.lstrip("﻿")))
            rows = list(reader)
        except csv.Error:
            raise _import_too_large(0, "invalid_csv") from None
        if reader.fieldnames is None or "word" not in [f.strip().lower() for f in reader.fieldnames]:
            raise _import_too_large(len(rows), "missing_word_column")
        return [{(k or "").strip().lower(): v for k, v in r.items()} for r in rows]
    raise _import_too_large(0, "unknown_format")


def _clean_int(v: Any, lo: int = 0, hi: int = 1_000_000) -> int | None:
    if v is None or v == "":
        return None
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _clean_float(v: Any, lo: float, hi: float) -> float | None:
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if lo <= f <= hi else None


def _clean_iso(v: Any) -> str | None:
    if v is None or v == "":
        return None
    try:
        return to_iso(parse_iso(str(v)))
    except (TypeError, ValueError):
        return None


def import_row(conn: sqlite3.Connection, user_id: int, raw: Mapping[str, Any], *, now: str, tz: str, today: str) -> AddResult:
    """Import one exported row with ``origin='import'`` (API.md 75); an existing row is never overwritten."""
    text = str(raw.get("word") or "").strip()
    norm = words.normalise_input(text)
    if not norm.ok:
        assert isinstance(norm, words.Invalid)
        return AddResult(input=text, status="invalid", error=norm.reason_zh)
    assert isinstance(norm, words.Normalised)
    res = words.resolve(conn, norm.lemma, norm.display, norm.kind, user_id, now=now)
    if res.ambiguous:
        return AddResult(input=text, status="ambiguous", candidates=res.candidates)
    assert res.word_id is not None
    word = words.word_row(conn, int(res.word_id))
    assert word is not None
    wid = int(word["id"])
    existing = my_row(conn, user_id, wid)
    if existing is not None:
        brief = words.word_brief(conn, {**word, "my_state": existing["state"]}, user_id)
        return AddResult(input=text, status="exists", word=brief, mine=words.user_word_dict(conn, existing, user_id), resolved_via=str(res.via), lemma_note_zh=res.lemma_note_zh, word_id=wid)

    state = str(raw.get("state") or "new")
    if state not in USER_STATES:
        state = "new"
    note = (str(raw.get("note")) if raw.get("note") not in (None, "") else None)
    note = None if note is None else note.strip()[:MAX_NOTE_CHARS] or None
    times_added = _clean_int(raw.get("times_added"), 1, 10_000) or 1
    added_at = _clean_iso(raw.get("added_at")) or now
    mastered_at = _clean_iso(raw.get("mastered_at"))
    ease = _clean_float(raw.get("ease"), EASE_MIN, 3.0)
    interval_days = _clean_int(raw.get("interval_days"), 0, 180)
    repetitions = _clean_int(raw.get("repetitions"), 0, 100_000)
    lapses = _clean_int(raw.get("lapses"), 0, 100_000)
    due_at = _clean_iso(raw.get("due_at"))
    srs = {"ease": EASE_START, "interval_days": 0, "repetitions": 0, "lapses": 0, "due_at": None}
    if state == "learning":
        if ease is not None and interval_days is not None and due_at is not None:
            srs = {"ease": ease, "interval_days": interval_days, "repetitions": repetitions or 0, "lapses": lapses or 0, "due_at": due_at}
        else:
            state = "new"
    elif state in ("mastered", "known", "removed"):
        srs = {"ease": ease if ease is not None else EASE_START, "interval_days": interval_days or 0, "repetitions": repetitions or 0, "lapses": lapses or 0, "due_at": None}
    if state != "mastered":
        mastered_at = None
    elif mastered_at is None:
        mastered_at = now
    needs_attention, msg = (1, ATTENTION_INVALID_MSG) if word.get("is_valid_english") == 0 else (0, None)
    cur = conn.execute(
        "INSERT INTO user_words(user_id, word_id, state, origin, priority, note, input_text, needs_attention, attention_msg, "
        "ease, interval_days, step, repetitions, lapses, consecutive_good, due_at, last_graded_at, times_pushed, times_added, "
        "added_at, first_added_at, mastered_at, created_at, updated_at) "
        "VALUES (?, ?, ?, 'import', ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, ?, NULL, 0, ?, ?, ?, ?, ?, ?)",
        (int(user_id), wid, state, PRIORITY_DEFAULT, note, text, needs_attention, msg, srs["ease"], srs["interval_days"], srs["repetitions"], srs["lapses"], srs["due_at"], times_added, added_at, added_at, mastered_at, now, now),
    )
    uw_id = int(cur.lastrowid)
    new_row = _row(conn, "SELECT * FROM user_words WHERE id = ?", (uw_id,))
    write_log(conn, user_id=int(user_id), word_id=wid, action="import", context="api", local_date=today, now=now, user_word_id=uw_id, prev_row=None, new_row=new_row, prev_state=None, new_state=state)
    _stats(conn, user_id, today, action="import", context="api", new_state=state, item_kind=None, prev_state=None)
    # No generate_content here: an import may carry 2,000 words that will not be studied for months; build_batch (step 9)
    # and the nightly prefetch enqueue content when a word is actually selected. Provisional words got lookup_word in resolve().
    created_provisional = res.created and word.get("is_valid_english") is None
    status = "pending_ai" if word.get("is_valid_english") is None else "added"
    via = "provisional" if created_provisional else str(res.via)
    brief = words.word_brief(conn, {**word, "my_state": state}, user_id)
    return AddResult(input=text, status=status, word=brief, mine=words.user_word_dict(conn, new_row, user_id), resolved_via=via, lemma_note_zh=res.lemma_note_zh, message=msg, word_id=wid, created=True)


def import_rows(conn: sqlite3.Connection, user_id: int, fmt: str, data: str, now: datetime | str | None, tz: str) -> ImportResult:
    """``POST /api/bank/import`` (API.md 75): ≤ 2,000 rows else 400 ``import_too_large``; one transaction."""
    now_dt, now_s = coerce_now(now)
    rows = parse_import(fmt, data)
    if len(rows) > IMPORT_MAX_ROWS:
        raise _import_too_large(len(rows), "too_many_rows")
    today = local_date_str(now_dt, tz)
    results: list[AddResult] = []
    with db.maybe_tx(conn):
        for raw in rows:
            results.append(import_row(conn, user_id, raw, now=now_s, tz=tz, today=today))
    skipped = sum(1 for r in results if r.status in ("exists", "invalid", "ambiguous"))
    pending = sum(1 for r in results if r.status == "pending_ai")
    return ImportResult(results=results, rows=len(rows), skipped=skipped, pending_ai_created=pending)


# ------------------------------------------------------------------------------------ bank listing
def bank_counts(conn: sqlite3.Connection, user_id: int, *, now: datetime | str | None, tz: str) -> dict[str, int]:
    """API.md ``BankCounts`` (``due_today`` = learning rows due before the end of the user's local day)."""
    now_dt, _ = coerce_now(now)
    today = clock_local_date(now_dt, tz)
    today_end = to_iso(day_start(today + timedelta(days=1), tz))
    r = conn.execute(
        "SELECT COALESCE(SUM(state = 'new'), 0), COALESCE(SUM(state = 'learning'), 0), COALESCE(SUM(state = 'mastered'), 0), "
        "COALESCE(SUM(state = 'known'), 0), COALESCE(SUM(state = 'removed'), 0), "
        "COALESCE(SUM(state IN ('new','learning') AND needs_attention = 1), 0), "
        "COALESCE(SUM(state = 'learning' AND due_at IS NOT NULL AND due_at < ?), 0) FROM user_words WHERE user_id = ?",
        (today_end, int(user_id)),
    ).fetchone()
    keys = ("new", "learning", "mastered", "known", "removed", "attention", "due_today")
    return {k: int(r[i] or 0) for i, k in enumerate(keys)}


def attention_count(conn: sqlite3.Connection, user_id: int) -> int:
    """``Counters.attention`` (API.md 5): bank rows with ``needs_attention = 1``."""
    return int(conn.execute("SELECT COUNT(*) FROM user_words WHERE user_id = ? AND state IN ('new','learning') AND needs_attention = 1", (int(user_id),)).fetchone()[0])


__all__ = [
    "ActionResult",
    "AddResult",
    "ImportResult",
    "add_custom_words",
    "add_one",
    "add_resolved",
    "ai_enabled",
    "ai_paused_until",
    "apply_action",
    "attention_count",
    "bank_counts",
    "check_daily_quota",
    "clear_attention",
    "coerce_now",
    "enqueue_content_if_needed",
    "expire_open_suggestions",
    "import_rows",
    "latest_transition_log",
    "local_date_str",
    "my_row",
    "open_batch_ids",
    "origin_for_context",
    "parse_import",
    "push_item_row",
    "query_model",
    "quota_consume",
    "quota_used",
    "set_attention",
    "split_tokens",
    "srs_snapshot",
    "study_today_key",
    "summarise",
    "today_batch",
    "update_note",
    "user_settings_row",
    "user_timezone",
    "write_log",
]
