"""``daily_stats`` writer (Phase 0, frozen contract — DESIGN §7.1, TASKS §I).

:func:`on_action` is the ONLY code that writes ``daily_stats``. WP3 (marks, verdicts, adds, import,
suggestions) and WP4 (grades) call it right after writing the ``review_logs`` row; WP4's
``services/stats.py`` only reads the table.

Delta table (DESIGN §7.1; *screening* = ``context IN ('screen_page','onboarding')`` or
``item_kind = 'screen'``; *card* = ``item_kind IN ('review','new','extra')``):

===========================================================  =====================================================
action                                                       deltas
===========================================================  =====================================================
``again`` / ``hard`` / ``good`` (card, intermediate incl.)   graded+1, <action>+1, study_ms += min(elapsed, 60000)
``master`` (card grade)                                      graded+1, mastered+1, study_ms as above
``master`` (mark) · ``known`` with new_state ``mastered``    mastered+1
``known`` with new_state ``known``                           known+1; screened+1 when screening
``unfamiliar`` with prev_state NULL · ``readd`` ·
``add_custom`` · ``import``                                  added+1; screened+1 when screening (``unfamiliar`` only)
idempotent ``unfamiliar`` · ``skip`` · ``remove`` ·
``reset`` · ``consolidate`` · ``note`` · ``attention``       nothing
``restore``                                                  exact reverse of the ``undone`` row's deltas (never < 0)
===========================================================  =====================================================

The idempotent-``unfamiliar`` case is recognised through the optional keyword ``prev_state`` (the
``review_logs.prev_state`` of the row just written): ``None`` = the row was created (added+1), a
state = ``status:"exists"`` (nothing). It extends the §I signature backwards-compatibly.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping

from ..db import maybe_tx

CARD_KINDS = ("review", "new", "extra")
SCREEN_CONTEXTS = ("screen_page", "onboarding")
GRADE_ACTIONS = ("again", "hard", "good")
COLUMNS = ("graded", "again", "hard", "good", "mastered", "known", "screened", "added", "study_ms")
STUDY_MS_CAP = 60_000

_UPSERT = (
    "INSERT INTO daily_stats(user_id, local_date, graded, again, hard, good, mastered, known, screened, added, study_ms) "
    "VALUES (:user_id, :local_date, MAX(0, :graded), MAX(0, :again), MAX(0, :hard), MAX(0, :good), MAX(0, :mastered), "
    "MAX(0, :known), MAX(0, :screened), MAX(0, :added), MAX(0, :study_ms)) "
    "ON CONFLICT(user_id, local_date) DO UPDATE SET "
    "graded = MAX(0, daily_stats.graded + :graded), again = MAX(0, daily_stats.again + :again), "
    "hard = MAX(0, daily_stats.hard + :hard), good = MAX(0, daily_stats.good + :good), "
    "mastered = MAX(0, daily_stats.mastered + :mastered), known = MAX(0, daily_stats.known + :known), "
    "screened = MAX(0, daily_stats.screened + :screened), added = MAX(0, daily_stats.added + :added), "
    "study_ms = MAX(0, daily_stats.study_ms + :study_ms)"
)


def is_screening(context: str | None, item_kind: str | None) -> bool:
    return context in SCREEN_CONTEXTS or item_kind == "screen"


def _study_ms(elapsed_ms: int | None) -> int:
    return min(max(int(elapsed_ms or 0), 0), STUDY_MS_CAP)


def deltas_for(
    *,
    action: str,
    context: str,
    new_state: str | None,
    item_kind: str | None,
    elapsed_ms: int | None,
    prev_state: str | None = None,
    undone: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """Pure part of :func:`on_action`: the column deltas for one logged action (all zero = nothing to write)."""
    d = dict.fromkeys(COLUMNS, 0)
    screening = is_screening(context, item_kind)

    if action in GRADE_ACTIONS:
        if item_kind != "screen":  # grades exist only on study cards (screen items take verdicts)
            d["graded"] += 1
            d[action] += 1
            d["study_ms"] += _study_ms(elapsed_ms)
    elif action == "master":
        d["mastered"] += 1
        if item_kind in CARD_KINDS:  # the 已掌握 grade on a study card
            d["graded"] += 1
            d["study_ms"] += _study_ms(elapsed_ms)
    elif action == "known":
        if new_state == "mastered":  # bank synonym: 认识 on a word already in the bank
            d["mastered"] += 1
        else:
            d["known"] += 1
            if screening:
                d["screened"] += 1
    elif action == "unfamiliar":
        if prev_state is None:  # ∅ → new (row created); an idempotent `exists` carries the old state
            d["added"] += 1
            if screening:
                d["screened"] += 1
    elif action in ("readd", "add_custom", "import"):
        d["added"] += 1
    elif action == "restore":
        _reverse(d, undone or {})
    # skip / remove / reset / consolidate / note / attention / idempotent unfamiliar → nothing
    return d


def _reverse(d: dict[str, int], u: Mapping[str, Any]) -> None:
    """Reverse the deltas of the ``review_logs`` row being undone (``undone`` = that row as a mapping).

    Keys read: ``action``, ``new_state``, ``prev_state``, ``context`` and — when the caller resolved it from
    ``push_items`` — ``item_kind`` (the kind of the push item that produced the transition).
    """
    action = u.get("action")
    new_state = u.get("new_state")
    context = u.get("context")
    item_kind = u.get("item_kind")
    if action in ("master", "known"):
        if new_state == "mastered" or action == "master":
            d["mastered"] -= 1
            if action == "master" and item_kind in CARD_KINDS:
                d["graded"] -= 1
        else:
            d["known"] -= 1
        if is_screening(context, item_kind):
            d["screened"] -= 1
    elif action == "unfamiliar" and u.get("prev_state") is None:
        d["added"] -= 1
        if is_screening(context, item_kind):
            d["screened"] -= 1
    # anything else is not undoable (DESIGN §4) → no stats change


def on_action(
    conn: sqlite3.Connection,
    user_id: int,
    local_date: str,
    *,
    action: str,
    context: str,
    new_state: str | None,
    item_kind: str | None,
    elapsed_ms: int | None,
    undone: Mapping[str, Any] | None = None,
    prev_state: str | None = None,
) -> dict[str, int]:
    """Upsert the ``(user_id, local_date)`` row with the DESIGN §7.1 deltas; counters never go below 0.

    ``undone`` is the ``review_logs`` row being reversed (``action='restore'`` only). Returns the deltas
    that were applied (all zero when the action changes nothing — then no row is created either).
    Joins the caller's open transaction when there is one.
    """
    d = deltas_for(
        action=action,
        context=context,
        new_state=new_state,
        item_kind=item_kind,
        elapsed_ms=elapsed_ms,
        prev_state=prev_state,
        undone=undone,
    )
    if not any(d.values()):
        return d
    params = {"user_id": user_id, "local_date": local_date, **d}
    with maybe_tx(conn):
        conn.execute(_UPSERT, params)
    return d
