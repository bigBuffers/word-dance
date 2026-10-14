"""Vocabulary browsing (WP3): ``GET /api/stages``, ``GET /api/vocab``, ``GET /api/vocab/letters`` (API.md 19–21).

Every query applies the API.md §1 visibility rule through ``deps.visible_word_sql`` and ``merged_into_word_id IS NULL``;
browsing never enqueues anything.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Request

from .. import schemas
from ..deps import current_user, get_db, visible_word_sql
from ..schemas import STAGE_NAMES_ZH, STAGE_ORDER, stage_to_index
from ..services import bank, words

router = APIRouter()

_ASCII_QUERY_RE = re.compile(r"^[A-Za-z' .\-]+$")
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _like_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _search_clause(q: str, params: dict[str, Any]) -> str | None:
    """ASCII → prefix on ``lemma`` plus ``word_forms.form``; anything else → ``translation LIKE``."""
    s = q.strip()
    if not s:
        return None
    if _ASCII_QUERY_RE.match(s):
        key = words.normalise_lemma(s) or ""
        if not key:
            return None
        params["q"] = key
        return (
            "((w.lemma >= :q AND w.lemma < :q || '~') OR EXISTS ("
            "SELECT 1 FROM word_forms wf WHERE wf.word_id = w.id AND wf.form >= :q AND wf.form < :q || '~'))"
        )
    params["like"] = "%" + _like_escape(s) + "%"
    return "w.translation LIKE :like ESCAPE '\\'"


def vocab_filters(me: dict[str, Any], q: schemas.VocabQuery, *, with_letter_and_q: bool) -> tuple[str, dict[str, Any]]:
    """``WHERE`` body (without the keyword) and the named parameters for endpoints 20/21."""
    where = [visible_word_sql(me, alias="w"), "w.merged_into_word_id IS NULL"]
    params: dict[str, Any] = {"me": int(me["id"])}
    if q.stage != "all":
        where.append(f"w.stage_{q.stage} = 1")
        if q.new_only == 1:
            where.append("w.stage_min = :stage_idx")
            params["stage_idx"] = stage_to_index(q.stage)
    if q.status == "unmarked":
        where.append("(uw.state IS NULL OR uw.state = 'removed')")
    elif q.status == "unfamiliar":
        where.append("uw.state IN ('new','learning')")
    elif q.status in ("known", "mastered"):
        where.append("uw.state = :status")
        params["status"] = q.status
    if with_letter_and_q:
        if q.letter:
            where.append("w.lemma >= :letter AND w.lemma < :letter || '~'")
            params["letter"] = q.letter
        if q.q:
            clause = _search_clause(q.q, params)
            if clause:
                where.append(clause)
    return " AND ".join(where), params


_ORDER = {
    "freq": "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma",
    "alpha": "w.lemma",
    "difficulty": "COALESCE(w.difficulty, w.stage_min, 5), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma",
}
_FROM = "FROM words w LEFT JOIN user_words uw ON uw.word_id = w.id AND uw.user_id = :me"


@router.get("/api/stages", response_model=schemas.StagesResponse)
def stages(me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    items = []
    for stage in STAGE_ORDER:
        idx = stage_to_index(stage)
        r = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(w.stage_min = :idx), 0), COALESCE(SUM(uw.state IN ('new','learning')), 0), "
            "COALESCE(SUM(uw.state = 'known'), 0), COALESCE(SUM(uw.state = 'mastered'), 0), COALESCE(SUM(uw.id IS NULL), 0) "
            f"{_FROM} WHERE w.stage_{stage} = 1 AND w.is_public = 1 AND w.merged_into_word_id IS NULL",
            {"idx": idx, "me": int(me["id"])},
        ).fetchone()
        items.append(
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
    return {"items": items}


@router.get("/api/vocab", response_model=schemas.Page[schemas.WordBrief])
def vocab(request: Request, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    q = bank.query_model(schemas.VocabQuery, request.query_params, int_fields=("new_only",))
    where, params = vocab_filters(me, q, with_letter_and_q=True)
    total = int(conn.execute(f"SELECT COUNT(*) {_FROM} WHERE {where}", params).fetchone()[0])
    rows = conn.execute(
        f"SELECT w.*, uw.state AS my_state {_FROM} WHERE {where} ORDER BY {_ORDER[q.sort]} LIMIT :limit OFFSET :offset",
        {**params, "limit": q.page_size, "offset": (q.page - 1) * q.page_size},
    ).fetchall()
    return {"items": words.word_briefs(conn, rows, int(me["id"])), "page": q.page, "page_size": q.page_size, "total": total}


@router.get("/api/vocab/letters", response_model=schemas.LettersResponse)
def letters(request: Request, me: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    q = bank.query_model(schemas.VocabQuery, request.query_params, int_fields=("new_only",))
    where, params = vocab_filters(me, q, with_letter_and_q=False)
    counts = {
        str(r[0]): int(r[1])
        for r in conn.execute(
            f"SELECT substr(w.lemma, 1, 1) AS letter, COUNT(*) {_FROM} WHERE {where} AND w.lemma >= 'a' AND w.lemma < '{{' GROUP BY letter",
            params,
        )
    }
    return {"items": [{"letter": ch, "count": counts.get(ch, 0)} for ch in LETTERS]}
