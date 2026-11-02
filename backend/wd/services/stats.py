"""Read-only statistics (WP4): streak, history days, heatmap, past batches and ``GET /api/stats``.

``daily_stats`` is written only by ``stats_core.on_action`` (DESIGN §7.1); this module reads it. The streak rule is
DESIGN §7: consecutive ``daily_stats`` days with ``graded ≥ 1`` ending today or yesterday (screening alone does
not count). ``DayStats.offline`` (API.md §9.1): a local day without a batch that overlaps a recorded
``system_events('downtime', {"from", "to"})`` gap written by the scheduler.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Sequence

from ..clock import day_start, local_date as clock_local_date, parse_iso
from ..schemas import STAGE_NAMES_ZH, STAGE_ORDER, stage_to_index
from . import bank, batches, srs, words

HEATMAP_DAYS = 84
STUBBORN_LIMIT = 20
HISTORY_MAX_DAYS = 370
STAT_COLUMNS: tuple[str, ...] = ("graded", "again", "hard", "good", "mastered", "known", "screened", "added", "study_ms")


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] | Mapping[str, Any] = ()) -> list[dict[str, Any]]:
    return [{k: r[k] for k in r.keys()} for r in conn.execute(sql, params).fetchall()]


# -------------------------------------------------------------------------------------------- streak
def streak(conn: sqlite3.Connection, user_id: int, today: date) -> tuple[int, int]:
    """``(streak_days, longest_streak)``: runs of consecutive days with ``graded ≥ 1``; the current run must end today or yesterday."""
    days = sorted(
        {date.fromisoformat(str(r[0])) for r in conn.execute("SELECT local_date FROM daily_stats WHERE user_id = ? AND graded >= 1", (int(user_id),))}
    )
    if not days:
        return 0, 0
    day_set = set(days)
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    anchor = today if today in day_set else (today - timedelta(days=1) if (today - timedelta(days=1)) in day_set else None)
    current = 0
    while anchor is not None and anchor in day_set:
        current += 1
        anchor -= timedelta(days=1)
    return current, longest


# ------------------------------------------------------------------------------------------ downtime
def downtime_windows(conn: sqlite3.Connection) -> list[tuple[datetime, datetime]]:
    """``(from, to)`` of every ``system_events`` row of kind ``downtime`` (DESIGN §6.4)."""
    out: list[tuple[datetime, datetime]] = []
    for (detail,) in conn.execute("SELECT detail_json FROM system_events WHERE kind = 'downtime' ORDER BY id"):
        try:
            d = json.loads(detail or "{}")
        except ValueError:
            continue
        if not isinstance(d, dict) or not d.get("from") or not d.get("to"):
            continue
        try:
            out.append((parse_iso(str(d["from"])), parse_iso(str(d["to"]))))
        except ValueError:
            continue
    return out


def is_offline(d: date, tz: str, windows: Sequence[tuple[datetime, datetime]]) -> bool:
    """API.md §9.1: ``from ≤ day_start(d+1) AND to ≥ day_start(d)`` for some recorded gap."""
    start = day_start(d, tz)
    end = day_start(d + timedelta(days=1), tz)
    return any(frm <= end and to >= start for frm, to in windows)


# ------------------------------------------------------------------------------------------- history
def history(conn: sqlite3.Connection, user_id: int, from_date: date, to_date: date, now: datetime | str | None, *, cfg: Any = None) -> dict[str, Any]:
    """API.md 48 ``HistoryResponse``: one ``DayStats`` per local day of the range (ascending), streaks."""
    now_dt, _ = bank.coerce_now(now)
    uid = int(user_id)
    tz = bank.user_timezone(conn, uid)
    today = clock_local_date(now_dt, tz)
    stats_by_day = {str(r["local_date"]): r for r in _rows(conn, "SELECT * FROM daily_stats WHERE user_id = ? AND local_date BETWEEN ? AND ?", (uid, from_date.isoformat(), to_date.isoformat()))}
    batches_by_day = {str(r["local_date"]): r for r in _rows(conn, "SELECT * FROM push_batches WHERE user_id = ? AND local_date BETWEEN ? AND ?", (uid, from_date.isoformat(), to_date.isoformat()))}
    windows = downtime_windows(conn)
    days: list[dict[str, Any]] = []
    d = from_date
    while d <= to_date:
        key = d.isoformat()
        st = stats_by_day.get(key, {})
        b = batches_by_day.get(key)
        total = done = None
        if b is not None:
            total, done = batches.batch_progress(conn, uid, int(b["id"]))
        days.append(
            {
                "date": key,
                "graded": int(st.get("graded") or 0),
                "again": int(st.get("again") or 0),
                "hard": int(st.get("hard") or 0),
                "good": int(st.get("good") or 0),
                "mastered": int(st.get("mastered") or 0),
                "known": int(st.get("known") or 0),
                "screened": int(st.get("screened") or 0),
                "added": int(st.get("added") or 0),
                "study_minutes": srs.rnd(int(st.get("study_ms") or 0) / 60000),
                "batch_id": None if b is None else int(b["id"]),
                "batch_total": total,
                "batch_done": done,
                "offline": b is None and bool(windows) and is_offline(d, tz, windows),
            }
        )
        d += timedelta(days=1)
    streak_days, longest = streak(conn, uid, today)
    return {"days": days, "streak_days": streak_days, "longest_streak": longest}


def heatmap(conn: sqlite3.Connection, user_id: int, today: date, days: int = HEATMAP_DAYS) -> list[dict[str, Any]]:
    """``Stats.heatmap``: the last ``days`` local days (ascending) with ``graded`` and ``goal_met``.

    ``goal_met`` is the API.md §9.1 predicate shared with ``TodayResponse.goal_met`` / ``complete_session``
    (``completed_at`` set, or every non-stale study item final — ``batches.goal_met`` over ``visible_items``), so a
    card marked 已掌握 from the 词库 page (stale, hidden) never leaves the heat strip disagreeing with the 今日 page.
    """
    uid = int(user_id)
    start = today - timedelta(days=days - 1)
    graded = {str(r[0]): int(r[1]) for r in conn.execute("SELECT local_date, graded FROM daily_stats WHERE user_id = ? AND local_date BETWEEN ? AND ?", (uid, start.isoformat(), today.isoformat()))}
    met: dict[str, bool] = {}
    for r in _rows(
        conn,
        "SELECT id, local_date, completed_at FROM push_batches WHERE user_id = ? AND local_date BETWEEN ? AND ?",
        (uid, start.isoformat(), today.isoformat()),
    ):
        met[str(r["local_date"])] = r["completed_at"] is not None or batches.goal_met(batches.visible_items(conn, uid, int(r["id"])))
    out = []
    d = start
    while d <= today:
        key = d.isoformat()
        out.append({"date": key, "graded": graded.get(key, 0), "goal_met": met.get(key, False)})
        d += timedelta(days=1)
    return out


# ------------------------------------------------------------------------------------------- batches
def batch_summaries(conn: sqlite3.Connection, user_id: int, page: int, page_size: int, now: datetime | str | None, *, cfg: Any = None) -> dict[str, Any]:
    """API.md 49 ``Page<BatchSummary>``: the user's batches, newest first, with stale-aware counts."""
    _, now_s = bank.coerce_now(now)
    uid = int(user_id)
    total = int(conn.execute("SELECT COUNT(*) FROM push_batches WHERE user_id = ?", (uid,)).fetchone()[0])
    rows = _rows(
        conn,
        "SELECT * FROM push_batches WHERE user_id = ? ORDER BY local_date DESC, id DESC LIMIT ? OFFSET ?",
        (uid, int(page_size), (int(page) - 1) * int(page_size)),
    )
    items = []
    for b in rows:
        visible = batches.visible_items(conn, uid, int(b["id"]))
        items.append(
            {
                "id": int(b["id"]),
                "local_date": str(b["local_date"]),
                "status": str(b["status"]),
                "trigger": str(b["trigger"]),
                "counts": batches.today_counts(conn, b, visible, now=now_s, cfg=cfg),
                "published_at": b.get("published_at"),
                "completed_at": b.get("completed_at"),
            }
        )
    return {"items": items, "page": int(page), "page_size": int(page_size), "total": total}


# --------------------------------------------------------------------------------------------- stats
def stage_infos(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    """``StageInfo`` rows (the same numbers as ``GET /api/stages``, API.md 19)."""
    uid = int(user_id)
    out = []
    for stage in STAGE_ORDER:
        idx = stage_to_index(stage)
        r = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(w.stage_min = :idx), 0), COALESCE(SUM(uw.state IN ('new','learning')), 0), "
            "COALESCE(SUM(uw.state = 'known'), 0), COALESCE(SUM(uw.state = 'mastered'), 0), COALESCE(SUM(uw.id IS NULL), 0) "
            "FROM words w LEFT JOIN user_words uw ON uw.word_id = w.id AND uw.user_id = :me "
            f"WHERE w.stage_{stage} = 1 AND w.is_public = 1 AND w.merged_into_word_id IS NULL",
            {"idx": idx, "me": uid},
        ).fetchone()
        out.append(
            {
                "stage": stage,
                "index": idx,
                "name_zh": STAGE_NAMES_ZH[stage],
                "total": int(r[0]),
                "new_only_total": int(r[1]),
                "unfamiliar": int(r[2]),
                "known": int(r[3]),
                "mastered": int(r[4]),
                "unseen": int(r[5]),
            }
        )
    return out


def stubborn_words(conn: sqlite3.Connection, user_id: int, limit: int = STUBBORN_LIMIT) -> list[dict[str, Any]]:
    """``Stats.stubborn``: 反复遗忘 — rows with ``times_added ≥ 3`` (most re-added first), as ``WordBrief``."""
    rows = conn.execute(
        "SELECT w.*, uw.state AS my_state FROM user_words uw JOIN words w ON w.id = uw.word_id "
        "WHERE uw.user_id = ? AND uw.times_added >= ? ORDER BY uw.times_added DESC, uw.added_at DESC, uw.id DESC LIMIT ?",
        (int(user_id), batches.STUBBORN_TIMES_ADDED, int(limit)),
    ).fetchall()
    return words.word_briefs(conn, rows, int(user_id))


def overview(conn: sqlite3.Connection, user_id: int, now: datetime | str | None, *, cfg: Any = None) -> dict[str, Any]:
    """API.md 51 ``Stats``."""
    now_dt, _ = bank.coerce_now(now)
    uid = int(user_id)
    tz = bank.user_timezone(conn, uid)
    today = clock_local_date(now_dt, tz)
    streak_days, longest = streak(conn, uid, today)
    today_batch = bank.today_batch(conn, uid, today.isoformat())
    today_stat = None
    if today_batch is not None:
        total, done = batches.batch_progress(conn, uid, int(today_batch["id"]))
        today_stat = {"done": done, "total": total}
    total_graded = int(conn.execute("SELECT COALESCE(SUM(graded), 0) FROM daily_stats WHERE user_id = ?", (uid,)).fetchone()[0])
    total_mastered = int(conn.execute("SELECT COUNT(*) FROM user_words WHERE user_id = ? AND state = 'mastered'", (uid,)).fetchone()[0])
    custom_words = int(conn.execute("SELECT COUNT(*) FROM user_words WHERE user_id = ? AND origin = 'custom'", (uid,)).fetchone()[0])
    return {
        "bank": bank.bank_counts(conn, uid, now=now_dt, tz=tz),
        "stages": stage_infos(conn, uid),
        "custom_words": custom_words,
        "streak_days": streak_days,
        "longest_streak": longest,
        "today": today_stat,
        "total_graded": total_graded,
        "total_mastered": total_mastered,
        "heatmap": heatmap(conn, uid, today),
        "stubborn": stubborn_words(conn, uid),
    }


__all__ = [
    "HEATMAP_DAYS",
    "HISTORY_MAX_DAYS",
    "batch_summaries",
    "downtime_windows",
    "heatmap",
    "history",
    "is_offline",
    "overview",
    "stage_infos",
    "streak",
    "stubborn_words",
]
