"""The ``ai_calls`` ledger (CLAUDE_INTEGRATION §1.2, §7, SCHEMA.sql §8).

One row per ``claude`` spawn, **inserted before the subprocess starts** (``status='running'`` with the
``reserved_usd`` estimate) and finished afterwards with status, cost, tokens, model and the raw-log path — a
killed or crashed call is therefore never invisible spend. ``cost_usd`` is recorded even when the call failed.

The aggregate queries used by :mod:`wd.ai.budget` (daily / monthly / SVG / prewarm spend, hourly call count)
and by the admin ledger views (API.md 54/64) live here as well, so every reader sums the same columns.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Sequence

from ..clock import now_iso
from ..db import maybe_tx

KINDS: tuple[str, ...] = ("content", "lookup", "consolidate", "svg", "probe")
STATUSES: tuple[str, ...] = ("running", "success", "error", "timeout", "invalid_output", "budget", "auth", "overloaded", "spawn_error")
ERROR_MAX_CHARS = 1000
PHOTO_PROVIDERS_SQL = "('wikimedia','openverse','pixabay','pexels')"


def insert_call(
    conn: sqlite3.Connection,
    *,
    kind: str,
    model_requested: str,
    flag_tier: int,
    word_count: int,
    job_ids: Sequence[int],
    max_budget_usd: float,
    reserved_usd: float,
    now: str | None = None,
) -> int:
    """Insert the ``running`` ledger row (THE row that exists before the spawn) and return its id."""
    if kind not in KINDS:
        raise ValueError(f"unknown ai_calls.kind {kind!r}")
    now = now or now_iso()
    with maybe_tx(conn):
        cur = conn.execute(
            "INSERT INTO ai_calls(kind, status, model_requested, flag_tier, word_count, job_ids_json, max_budget_usd, reserved_usd, started_at) "
            "VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?)",
            (
                kind,
                model_requested,
                int(flag_tier),
                int(word_count),
                json.dumps([int(j) for j in job_ids]),
                float(max_budget_usd),
                float(reserved_usd),
                now,
            ),
        )
        return int(cur.lastrowid)


def finish_call(
    conn: sqlite3.Connection,
    call_id: int,
    *,
    status: str,
    cost_usd: float = 0.0,
    duration_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_create_tokens: int | None = None,
    model_used: str | None = None,
    session_id: str | None = None,
    exit_code: int | None = None,
    error: str | None = None,
    stdout_path: str | None = None,
    now: str | None = None,
) -> None:
    """Record the outcome of a spawn on its ledger row (the reservation is released: the row is no longer ``running``)."""
    if status not in STATUSES or status == "running":
        raise ValueError(f"invalid final ai_calls.status {status!r}")
    now = now or now_iso()
    with maybe_tx(conn):
        conn.execute(
            "UPDATE ai_calls SET status=?, cost_usd=?, duration_ms=?, input_tokens=?, output_tokens=?, cache_read_tokens=?, "
            "cache_create_tokens=?, model_used=?, session_id=?, exit_code=?, error=?, stdout_path=?, finished_at=? WHERE id=?",
            (
                status,
                float(cost_usd or 0.0),
                duration_ms,
                input_tokens,
                output_tokens,
                cache_read_tokens,
                cache_create_tokens,
                model_used,
                session_id,
                exit_code,
                None if error is None else str(error)[:ERROR_MAX_CHARS],
                stdout_path,
                now,
                int(call_id),
            ),
        )


def set_status(conn: sqlite3.Connection, call_id: int, status: str, *, error: str | None = None) -> None:
    """Re-classify a finished call (``success`` → ``invalid_output`` when every item failed post-validation, §3)."""
    if status not in STATUSES:
        raise ValueError(f"invalid ai_calls.status {status!r}")
    with maybe_tx(conn):
        if error is None:
            conn.execute("UPDATE ai_calls SET status=? WHERE id=?", (status, int(call_id)))
        else:
            conn.execute("UPDATE ai_calls SET status=?, error=? WHERE id=?", (status, str(error)[:ERROR_MAX_CHARS], int(call_id)))


def get_call(conn: sqlite3.Connection, call_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM ai_calls WHERE id = ?", (int(call_id),)).fetchone()
    return None if row is None else {k: row[k] for k in row.keys()}


# ------------------------------------------------------------------------------------------- aggregates
def sum_cost(conn: sqlite3.Connection, since: str, until: str, *, kind: str | None = None) -> float:
    """``SUM(cost_usd)`` of the calls started in ``[since, until)`` (every status: failures cost money too)."""
    if kind is None:
        row = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls WHERE started_at >= ? AND started_at < ?", (since, until)).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls WHERE started_at >= ? AND started_at < ? AND kind = ?", (since, until, kind)
        ).fetchone()
    return float(row[0] or 0.0)


def reserved_running(conn: sqlite3.Connection, *, kind: str | None = None) -> float:
    """``SUM(reserved_usd)`` of the calls still ``running`` (the reservation half of ``spent_today``, §7)."""
    if kind is None:
        row = conn.execute("SELECT COALESCE(SUM(reserved_usd), 0) FROM ai_calls WHERE status = 'running'").fetchone()
    else:
        row = conn.execute("SELECT COALESCE(SUM(reserved_usd), 0) FROM ai_calls WHERE status = 'running' AND kind = ?", (kind,)).fetchone()
    return float(row[0] or 0.0)


def count_started(conn: sqlite3.Connection, since: str, until: str | None = None) -> int:
    if until is None:
        row = conn.execute("SELECT COUNT(*) FROM ai_calls WHERE started_at >= ?", (since,)).fetchone()
    else:
        row = conn.execute("SELECT COUNT(*) FROM ai_calls WHERE started_at >= ? AND started_at < ?", (since, until)).fetchone()
    return int(row[0] or 0)


def prewarm_cost(conn: sqlite3.Connection, since: str, until: str) -> float:
    """Spend of the calls that served priority-≥ 90 (prewarm) jobs in ``[since, until)``, running reservations included.

    ``ai_calls`` has no priority column; the job ids of a call are joined back to ``jobs`` through ``json_each``.
    """
    row = conn.execute(
        "SELECT COALESCE(SUM(CASE WHEN c.status = 'running' THEN c.reserved_usd ELSE c.cost_usd END), 0) FROM ai_calls c "
        "WHERE c.started_at >= ? AND c.started_at < ? AND EXISTS ("
        "  SELECT 1 FROM json_each(c.job_ids_json) je JOIN jobs j ON j.id = je.value WHERE j.priority >= 90)",
        (since, until),
    ).fetchone()
    return float(row[0] or 0.0)


def avg_cost_per_word(conn: sqlite3.Connection, since: str, until: str) -> float | None:
    """Average cost per word of the successful content calls in ``[since, until)`` (admin overview; None without data)."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0), COALESCE(SUM(word_count), 0) FROM ai_calls "
        "WHERE kind = 'content' AND status = 'success' AND started_at >= ? AND started_at < ?",
        (since, until),
    ).fetchone()
    cost, words = float(row[0] or 0.0), int(row[1] or 0)
    if words <= 0:
        return None
    return round(cost / words, 6)


def last_error(conn: sqlite3.Connection) -> str | None:
    """The error text of the most recent failed call (``AdminOverview.ai.last_error``)."""
    row = conn.execute(
        "SELECT error, status FROM ai_calls WHERE status NOT IN ('running', 'success') ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return str(row[0]) if row[0] else str(row[1])


def call_dto(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    """API.md ``AiCall`` from an ``ai_calls`` row."""
    r = row if isinstance(row, dict) else {k: row[k] for k in row.keys()}
    return {
        "id": int(r["id"]),
        "kind": r["kind"],
        "status": r["status"],
        "model_requested": r["model_requested"],
        "model_used": r.get("model_used"),
        "flag_tier": 1 if int(r.get("flag_tier") or 0) == 1 else 0,
        "word_count": int(r.get("word_count") or 0),
        "cost_usd": float(r.get("cost_usd") or 0.0),
        "duration_ms": r.get("duration_ms"),
        "input_tokens": r.get("input_tokens"),
        "output_tokens": r.get("output_tokens"),
        "error": r.get("error"),
        "started_at": r["started_at"],
    }


__all__ = [
    "KINDS",
    "STATUSES",
    "avg_cost_per_word",
    "call_dto",
    "count_started",
    "finish_call",
    "get_call",
    "insert_call",
    "last_error",
    "prewarm_cost",
    "reserved_running",
    "set_status",
    "sum_cost",
]
