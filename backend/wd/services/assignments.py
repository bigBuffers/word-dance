"""布置词汇 — words a guardian or the admin hands to a learner (API.md 124–129, migration 0022).

Who may assign (:func:`may_assign`): the admin to every learner account, a guardian to their own children. A list is typed
text; every token goes through the learner's own add path (``bank.add_one`` — normalise, resolve, a provisional word with its
lookup job for an unknown spelling), so an assigned word is simply a word in the learner's bank that an ``assignment_words``
row points at. A word the learner already knows (已掌握 / 已认识) is not assigned — their state is left alone.

How the words reach a day (:func:`take_for_batch`, called by ``batches.select_words``): of the learner's pending words, every
``today``-mode word, then ``spread``-mode words while the day's new-word quota lasts; a word still ``new`` becomes a ``new``
item, one already ``learning`` an ``extra`` item (practised once, its interval untouched — the grade rules of an extra item) or,
when it is due anyway, rides on its ``review`` item. Whatever they take is taken from the quota of ordinary new words.
:func:`apply_today` does the same for a ``today`` list created after the day's batch was built (appended ``extra`` items).
The 今日 list and the 磨耳朵 playlist put assigned items first (``batches.batch_items`` flags them ``assigned``).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Mapping, Sequence

from .. import db
from ..errors import ApiError
from . import bank, words

MODES = ("today", "spread")
MAX_WORDS = 50  # == bank.MAX_ADD_TOKENS: one list is one add request
MAX_TITLE_CHARS = 40
KNOWN_STATES = ("known", "mastered")
ASSIGNED_SQL = "EXISTS (SELECT 1 FROM assignment_words aw WHERE aw.push_item_id = pi.id AND aw.status = 'scheduled') AS assigned"


def _rows(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
    return [db.row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def _name(row: Mapping[str, Any]) -> str:
    return str(row.get("display_name") or row.get("username") or f"#{row['id']}")


# ------------------------------------------------------------------------------------------ who
def learners(conn: sqlite3.Connection, me: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The accounts ``me`` may assign to: the admin every learner account (their own included), a guardian their children."""
    if str(me.get("role")) == "admin":
        rows = _rows(conn, "SELECT id, username, display_name FROM users WHERE account_kind = 'learner' ORDER BY id = ?, id", (int(me["id"]),))  # the admin's own account last: the form opens on a pupil
    else:
        rows = _rows(conn, "SELECT id, username, display_name FROM users WHERE guardian_user_id = ? ORDER BY created_at, id", (int(me["id"]),))
    return [{"id": int(r["id"]), "name": _name(r)} for r in rows]


def may_assign(conn: sqlite3.Connection, me: Mapping[str, Any], learner_id: int) -> None:
    if not any(row["id"] == int(learner_id) for row in learners(conn, me)):
        raise ApiError("forbidden")


# ------------------------------------------------------------------------------------- creating
def _resolve_tokens(conn: sqlite3.Connection, learner_id: int, text: str, now_s: str, tz: str) -> list[dict[str, Any]]:
    """One row per typed token: ``{input, status, word_id, display, meaning}`` — status ``new`` (enters the bank now), ``studying``
    (already in the bank), ``pending_ai`` (an unknown spelling waiting for its lookup), ``known`` (已掌握 / 已认识: not assigned),
    ``duplicate``, ``invalid``, ``ambiguous``. Writes what ``bank.add_one`` writes; :func:`preview` rolls it back."""
    tokens = bank.split_tokens(text)
    if not tokens:
        raise ApiError("validation_error", details={"fields": {"text": "at least one word"}})
    if len(tokens) > MAX_WORDS:
        raise ApiError("too_many_words", details={"count": len(tokens), "max": MAX_WORDS})
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for tok in tokens:
        row: dict[str, Any] = {"input": tok, "status": "invalid", "word_id": None, "display": None, "meaning": None, "message": None}
        norm = words.normalise_input(tok)
        if not norm.ok:
            row["message"] = getattr(norm, "reason_zh", None)
            out.append(row)
            continue
        res = words.resolve(conn, norm.lemma, norm.display, norm.kind, learner_id, now=now_s)
        if res.ambiguous:
            row["status"] = "ambiguous"
            out.append(row)
            continue
        word = words.word_row(conn, int(res.word_id))
        word, _ = words.follow_merge(conn, word)
        wid = int(word["id"])
        row.update(word_id=wid, display=str(word.get("display") or word["lemma"]), meaning=words.short_meaning(word, words.content_meanings(conn, [word.get("active_content_id")]).get(int(word.get("active_content_id") or 0))))
        mine = bank.my_row(conn, learner_id, wid)
        if wid in seen:
            row["status"] = "duplicate"
        elif mine is not None and str(mine["state"]) in KNOWN_STATES:
            row["status"] = "known"
        elif mine is not None and str(mine["state"]) in bank.BANK_STATES:
            row["status"] = "studying"
        else:
            added = bank.add_resolved(conn, learner_id, wid, input_text=tok, note=None, study_today=False, now=now_s, tz=tz, resolved_via=str(res.via), origin="import", log_action="import")
            row["status"] = "pending_ai" if added.status == "pending_ai" else "new"
        if row["status"] in ("new", "studying", "pending_ai"):
            seen.add(wid)
        out.append(row)
    return out


def preview(conn: sqlite3.Connection, me: Mapping[str, Any], learner_id: int, text: str, now: datetime | str | None) -> list[dict[str, Any]]:
    """What :func:`create` would do with ``text``, without doing it: the same code under a savepoint that is rolled back."""
    may_assign(conn, me, learner_id)
    _, now_s = bank.coerce_now(now)
    conn.execute("SAVEPOINT assign_preview")
    try:
        return _resolve_tokens(conn, int(learner_id), text, now_s, bank.user_timezone(conn, int(learner_id)))
    finally:
        conn.execute("ROLLBACK TO assign_preview")
        conn.execute("RELEASE assign_preview")


def create(conn: sqlite3.Connection, me: Mapping[str, Any], learner_id: int, text: str, mode: str, title: str | None, now: datetime | str | None) -> dict[str, Any]:
    """A new list for ``learner_id``; returns ``{assignment: detail, results: rows of the typed tokens}``. A ``today`` list is put
    into today's batch at once when the learner already has one."""
    if mode not in MODES:
        raise ApiError("validation_error", details={"fields": {"mode": "today or spread"}})
    may_assign(conn, me, learner_id)
    _, now_s = bank.coerce_now(now)
    lid = int(learner_id)
    with db.maybe_tx(conn):
        results = _resolve_tokens(conn, lid, text, now_s, bank.user_timezone(conn, lid))
        chosen = [r for r in results if r["status"] in ("new", "studying", "pending_ai")]
        if not chosen:
            raise ApiError("validation_error", details={"fields": {"text": "no word can be assigned"}, "results": results})
        aid = int(
            conn.execute(
                "INSERT INTO assignments(assigner_id, learner_id, title, mode, created_at) VALUES (?, ?, ?, ?, ?)",
                (int(me["id"]), lid, " ".join(str(title or "").split())[:MAX_TITLE_CHARS], mode, now_s),
            ).lastrowid
        )
        conn.executemany("INSERT INTO assignment_words(assignment_id, word_id, position) VALUES (?, ?, ?)", [(aid, int(r["word_id"]), i) for i, r in enumerate(chosen)])
        if mode == "today":
            apply_today(conn, lid, now)
        return {"assignment": detail(conn, me, aid), "results": results}


# ------------------------------------------------------------------------------- reaching a day
def _pending(conn: sqlite3.Connection, learner_id: int) -> list[dict[str, Any]]:
    return _rows(
        conn,
        "SELECT aw.id AS aw_id, aw.word_id, a.mode, w.lemma, uw.id AS uw_id, uw.state FROM assignment_words aw "
        "JOIN assignments a ON a.id = aw.assignment_id JOIN words w ON w.id = aw.word_id "
        "LEFT JOIN user_words uw ON uw.user_id = a.learner_id AND uw.word_id = aw.word_id "
        "WHERE a.learner_id = ? AND aw.status = 'pending' AND w.merged_into_word_id IS NULL AND w.is_valid_english = 1 "
        "AND uw.state IN ('new','learning') AND uw.needs_attention = 0 ORDER BY a.id, aw.position, aw.id",
        (int(learner_id),),
    )


def take_for_batch(conn: sqlite3.Connection, learner_id: int, daily_new: int) -> list[dict[str, Any]]:
    """The pending words the learner's next batch takes, in list order, one row per word (``aw_ids`` = every pending row of that
    word): all ``today`` words, then ``spread`` words while ``daily_new`` lasts."""
    taken: dict[int, dict[str, Any]] = {}
    for row in _pending(conn, learner_id):
        wid = int(row["word_id"])
        if wid in taken:
            taken[wid]["aw_ids"].append(int(row["aw_id"]))
        elif row["mode"] == "today" or len(taken) < daily_new:
            taken[wid] = {**row, "aw_ids": [int(row["aw_id"])]}
    return list(taken.values())


def mark_scheduled(conn: sqlite3.Connection, aw_ids: Sequence[int], push_item_id: int, local_date: str) -> None:
    conn.executemany("UPDATE assignment_words SET status = 'scheduled', push_item_id = ?, scheduled_date = ? WHERE id = ? AND status = 'pending'", [(int(push_item_id), local_date, int(a)) for a in aw_ids])


def apply_today(conn: sqlite3.Connection, learner_id: int, now: datetime | str | None) -> int:
    """Put the learner's pending ``today`` words into today's batch when it exists (an ``extra`` item each, or the study item the
    word already has there); returns how many were scheduled. Without a batch they wait for ``build_batch``."""
    from . import batches  # local import: batches imports this module

    now_dt, now_s = bank.coerce_now(now)
    lid = int(learner_id)
    today = bank.local_date_str(now_dt, bank.user_timezone(conn, lid))
    batch = bank.today_batch(conn, lid, today)
    if batch is None:
        return 0
    done = 0
    for row in take_for_batch(conn, lid, 0):
        item = conn.execute("SELECT id FROM push_items WHERE batch_id = ? AND word_id = ? AND kind IN ('review','new','extra')", (int(batch["id"]), int(row["word_id"]))).fetchone()
        item_id = int(item[0]) if item is not None else batches.append_item(conn, batch, lid, int(row["word_id"]), "extra", now_s)
        if item_id is not None:
            mark_scheduled(conn, row["aw_ids"], item_id, today)
            done += 1
    return done


# -------------------------------------------------------------------------------------- reading
def _mine(conn: sqlite3.Connection, me: Mapping[str, Any], assignment_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT a.*, u.username, u.display_name FROM assignments a JOIN users u ON u.id = a.learner_id WHERE a.id = ?", (int(assignment_id),)).fetchone()
    if row is None or (int(row["assigner_id"]) != int(me["id"]) and str(me.get("role")) != "admin"):
        raise ApiError("not_found")
    return db.row_to_dict(row)


def _summary(a: Mapping[str, Any], counts: Mapping[str, int]) -> dict[str, Any]:
    return {
        "id": int(a["id"]),
        "learner": {"id": int(a["learner_id"]), "name": _name({"id": a["learner_id"], "username": a.get("username"), "display_name": a.get("display_name")})},
        "title": str(a["title"] or ""),
        "mode": str(a["mode"]),
        "created_at": str(a["created_at"]),
        "counts": {k: int(counts.get(k, 0)) for k in ("total", "pending", "scheduled", "done", "withdrawn")},
    }


def _counts(conn: sqlite3.Connection, assignment_id: int) -> dict[str, int]:
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(aw.status = 'pending') AS pending, SUM(aw.status = 'scheduled') AS scheduled, SUM(aw.status = 'withdrawn') AS withdrawn, "
        "SUM(aw.status = 'scheduled' AND pi.result IS NOT NULL) AS done FROM assignment_words aw LEFT JOIN push_items pi ON pi.id = aw.push_item_id WHERE aw.assignment_id = ?",
        (int(assignment_id),),
    ).fetchone()
    return {k: int(row[k] or 0) for k in row.keys()}


def list_mine(conn: sqlite3.Connection, me: Mapping[str, Any], learner_id: int | None = None) -> list[dict[str, Any]]:
    """The lists ``me`` handed out, newest first (optionally one learner's)."""
    sql = "SELECT a.*, u.username, u.display_name FROM assignments a JOIN users u ON u.id = a.learner_id WHERE a.assigner_id = ?"
    params: list[Any] = [int(me["id"])]
    if learner_id is not None:
        sql += " AND a.learner_id = ?"
        params.append(int(learner_id))
    return [_summary(a, _counts(conn, int(a["id"]))) for a in _rows(conn, sql + " ORDER BY a.id DESC LIMIT 100", params)]


def detail(conn: sqlite3.Connection, me: Mapping[str, Any], assignment_id: int) -> dict[str, Any]:
    a = _mine(conn, me, assignment_id)
    rows = _rows(
        conn,
        "SELECT aw.id, aw.word_id, aw.status, aw.scheduled_date, w.lemma, w.display, w.translation, w.pos, w.active_content_id, w.is_valid_english, "
        "pi.kind, pi.result, pi.skip_count, pi.graded_at, uw.state AS learner_state FROM assignment_words aw JOIN words w ON w.id = aw.word_id "
        "LEFT JOIN push_items pi ON pi.id = aw.push_item_id LEFT JOIN user_words uw ON uw.user_id = ? AND uw.word_id = aw.word_id "
        "WHERE aw.assignment_id = ? ORDER BY aw.position, aw.id",
        (int(a["learner_id"]), int(a["id"])),
    )
    meanings = words.content_meanings(conn, [r["active_content_id"] for r in rows])
    out = _summary(a, _counts(conn, int(a["id"])))
    out["words"] = [
        {
            "word_id": int(r["word_id"]),
            "display": str(r["display"] or r["lemma"]),
            "meaning": words.short_meaning(r, meanings.get(int(r["active_content_id"] or 0))),
            "status": str(r["status"]),
            "scheduled_date": r["scheduled_date"],
            "kind": r["kind"],
            "result": r["result"],
            "skip_count": int(r["skip_count"] or 0),
            "graded_at": r["graded_at"],
            "learner_state": r["learner_state"],
            "waiting_lookup": r["is_valid_english"] is None,
        }
        for r in rows
    ]
    return out


def withdraw(conn: sqlite3.Connection, me: Mapping[str, Any], assignment_id: int) -> dict[str, Any]:
    """Take back every word of the list that has not reached a batch yet; scheduled words stay as they are."""
    a = _mine(conn, me, assignment_id)
    with db.maybe_tx(conn):
        conn.execute("UPDATE assignment_words SET status = 'withdrawn' WHERE assignment_id = ? AND status = 'pending'", (int(a["id"]),))
    return detail(conn, me, assignment_id)


__all__ = ["ASSIGNED_SQL", "MAX_WORDS", "MODES", "apply_today", "create", "detail", "learners", "list_mine", "mark_scheduled", "may_assign", "preview", "take_for_batch", "withdraw"]
