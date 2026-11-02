"""整理建议 inbox services (WP3): listing, accept / reject / undo (API.md 39–42, CLAUDE_INTEGRATION §6.6, DESIGN §5.4).

Rows are written by WP5's ``consolidate_bank`` / ``lookup_word`` handlers; this module applies the user's decision:

* **accept** of ``fix_spelling`` / ``lemmatize`` / ``merge_duplicate`` / ``split_phrase`` → repoint the bank row to
  ``target_word_id`` with its SRS state preserved; when the user holds both words **in the bank** the row with more
  ``repetitions`` (ties: older ``first_added_at``) stays and the other becomes ``state='removed'`` (never deleted — rows
  are history), with ``review_logs(action='consolidate', context='consolidate')``, its open suggestions expired and its
  ``push_items`` in open batches rewritten to the kept word (duplicates per ``(batch_id, word_id, kind)`` dropped —
  DESIGN §6.3). When the user holds the target only as ``mastered`` / ``known`` / ``removed`` that row re-enters the bank
  per DESIGN §4 (``readd``: ``times_added+1``, priority 80, ease penalty from ``mastered``) and the source row is parked
  as ``removed`` — an accepted merge always leaves the word in 生词库. The row that ends up on the target has its 待处理
  columns (``needs_attention`` / ``attention_msg`` / ``suggested_word_id``) cleared: they described the replaced string.
  A ``fix_spelling`` stored without ``target_word_id`` (``lookup_word`` step 2) resolves ``payload.to`` through DESIGN
  §5.2 at accept time (an unknown spelling becomes a provisional word + ``lookup_word`` job, exactly like typing it).
  ``invalid_word`` → the row becomes ``removed``.
* **reject** → ``rejected``.
* **undo** (``status='auto'`` within ``expires_at``) → ``undo_json`` is applied: ``{"prev_word_id": W}`` repoints the row
  back (and rewrites open-batch ``push_items``); when W was tombstoned by a ``lookup_word`` merge
  (``merged_into_word_id`` set) it is restored first as a standalone private word (flag cleared, its ``alt`` form on
  the target dropped) so the entry is studied again instead of hiding behind a merged word;
  ``{"word_id": id, "fields": {col: old}}`` restores ``words`` columns (``fill_data`` / ``difficulty``). Status → ``undone``.

Open rows past ``expires_at`` are reported as ``expired`` (and resolved so on accept/reject) even before the nightly
sweep; ``confusable_group`` rows are never listed (they feed the 易混 chips through ``words.confusables_for``).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any, Mapping

from .. import db
from ..errors import ApiError
from . import bank, words

log = logging.getLogger("wd.suggestions")

PAYLOAD_KEYS: tuple[str, ...] = ("from", "to", "note_zh", "confidence", "group", "fields")
REPOINT_TYPES: tuple[str, ...] = ("fix_spelling", "lemmatize", "merge_duplicate", "split_phrase")
RESTORABLE_WORD_COLUMNS: tuple[str, ...] = ("phonetic", "translation", "definition", "pos", "difficulty", "kind", "source")
LISTED_STATUSES_ALL: tuple[str, ...] = ("open", "accepted", "rejected", "expired", "undone")

MSG_ACCEPTED_REPOINT = "已合并到 “{to}”"
MSG_ACCEPTED_REMOVED = "已从生词库移除"
MSG_ACCEPTED = "已应用"
MSG_REJECTED = "已忽略"
MSG_UNDONE = "已撤销"


# ----------------------------------------------------------------------------------------- listing
def _payload(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in PAYLOAD_KEYS if k in data}


def suggestion_dict(conn: sqlite3.Connection, row: Mapping[str, Any], user_id: int) -> dict[str, Any]:
    """API.md ``Suggestion`` from a ``bank_suggestions`` row."""
    user_word = None
    if row.get("user_word_id") is not None:
        uw = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (int(row["user_word_id"]),))
        if uw is not None:
            w = words.word_row(conn, int(uw["word_id"]))
            if w is not None:
                user_word = {**words.word_brief(conn, {**w, "my_state": uw["state"]}, user_id), "mine": words.user_word_dict(conn, uw, user_id)}
    target = None
    if row.get("target_word_id") is not None:
        t = words.word_row(conn, int(row["target_word_id"]))
        if t is not None:
            target = words.word_brief(conn, t, user_id)
    return {
        "id": int(row["id"]),
        "type": row["type"],
        "status": row["status"],
        "user_word": user_word,
        "target": target,
        "payload": _payload(row.get("payload_json")),
        "created_at": row["created_at"],
        "expires_at": row.get("expires_at"),
        "resolved_at": row.get("resolved_at"),
    }


def open_count(conn: sqlite3.Connection, user_id: int, now: str) -> int:
    """``Counters.suggestions_open`` / ``TodayResponse.suggestions_open``: open rows that have not timed out."""
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM bank_suggestions WHERE user_id = ? AND status = 'open' AND type != 'confusable_group' "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (int(user_id), now),
        ).fetchone()[0]
    )


def list_suggestions(conn: sqlite3.Connection, user_id: int, status: str, *, now: datetime | str | None) -> tuple[list[dict[str, Any]], int]:
    """API.md 39: ``open`` = live open rows; ``all`` adds ``auto`` within its undo window, accepted, rejected, expired, undone."""
    _, now_s = bank.coerce_now(now)
    if status == "open":
        where = "status = 'open' AND (expires_at IS NULL OR expires_at > :now)"
    else:
        where = "(status IN ('open','accepted','rejected','expired','undone') OR (status = 'auto' AND (expires_at IS NULL OR expires_at > :now)))"
    rows = bank._rows(
        conn,
        f"SELECT * FROM bank_suggestions WHERE user_id = :me AND type != 'confusable_group' AND {where} ORDER BY created_at DESC, id DESC",
        {"me": int(user_id), "now": now_s},
    )
    items = []
    for r in rows:
        if _timed_out(r, now_s):  # not swept yet: never advertise 接受 for it (open_count excludes it as well)
            r = {**r, "status": "expired"}
        items.append(suggestion_dict(conn, r, user_id))
    return items, open_count(conn, user_id, now_s)


def _timed_out(row: Mapping[str, Any], now_s: str) -> bool:
    return row["status"] == "open" and bool(row.get("expires_at")) and str(row["expires_at"]) <= now_s


# -------------------------------------------------------------------------------- repoint / merge
def _repoint_push_items(conn: sqlite3.Connection, user_id: int, from_word: int, to_word: int, to_user_word_id: int | None, local_date: str) -> None:
    """DESIGN §6.3: ``push_items.word_id`` W → L in the user's open batches.

    A row that would duplicate ``(batch_id, word_id, kind)`` is dropped when it is still ungraded; a graded one is history
    and stays on W (never deleted, never made to collide).
    """
    ids = bank.open_batch_ids(conn, user_id, local_date)
    if not ids or from_word == to_word:
        return
    marks = ",".join("?" * len(ids))
    dup = "EXISTS (SELECT 1 FROM push_items p2 WHERE p2.batch_id = push_items.batch_id AND p2.word_id = ? AND p2.kind = push_items.kind)"
    conn.execute(
        f"DELETE FROM push_items WHERE word_id = ? AND result IS NULL AND batch_id IN ({marks}) AND {dup}",
        (int(from_word), *ids, int(to_word)),
    )
    conn.execute(
        f"UPDATE push_items SET word_id = ?, user_word_id = COALESCE(?, user_word_id) WHERE word_id = ? AND batch_id IN ({marks}) AND NOT {dup}",
        (int(to_word), to_user_word_id, int(from_word), *ids, int(to_word)),
    )


def _log_consolidate(conn, user_id, word_id, row, new_row, prev_state, new_state, today, now):
    return bank.write_log(
        conn,
        user_id=int(user_id),
        word_id=int(word_id),
        action="consolidate",
        context="consolidate",
        local_date=today,
        now=now,
        user_word_id=int(row["id"]),
        prev_row=row,
        new_row=new_row,
        prev_state=prev_state,
        new_state=new_state,
    )


def _swap_word_ids(conn: sqlite3.Connection, winner_id: int, loser_id: int, target: int, source: int) -> None:
    """Winner row → ``target``, loser row → ``source`` under ``UNIQUE(user_id, word_id)`` (FK checks deferred to COMMIT)."""
    conn.execute("PRAGMA defer_foreign_keys = ON")
    conn.execute("UPDATE user_words SET word_id = ? WHERE id = ?", (-int(loser_id), int(loser_id)))
    conn.execute("UPDATE user_words SET word_id = ? WHERE id = ?", (int(target), int(winner_id)))
    conn.execute("UPDATE user_words SET word_id = ? WHERE id = ?", (int(source), int(loser_id)))


def repoint_or_merge(conn: sqlite3.Connection, user_id: int, row: Mapping[str, Any], target_word_id: int, *, now: str, today: str) -> tuple[dict[str, Any] | None, int | None]:
    """Move the bank row ``row`` (word W) onto ``target_word_id`` (L) per CLAUDE_INTEGRATION §6.6.

    Returns ``(mine, removed_word_id)``: the ``UserWord`` that now carries the bank entry and the word whose row was
    set to ``removed`` (None when no second row existed).
    """
    source = int(row["word_id"])
    target_row = words.word_row(conn, int(target_word_id))
    if target_row is None:
        raise ApiError("word_not_found")
    target_row, _ = words.follow_merge(conn, target_row)
    target = int(target_row["id"])
    if target == source:
        return words.user_word_dict(conn, bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],)), user_id), None
    other = bank.my_row(conn, user_id, target)
    if other is None:  # simple repoint, SRS preserved
        conn.execute("UPDATE user_words SET word_id = ?, updated_at = ? WHERE id = ?", (target, now, row["id"]))
        _reset_attention(conn, int(row["id"]), target_row, now)
        new_row = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
        _log_consolidate(conn, user_id, target, row, new_row, str(row["state"]), str(row["state"]), today, now)
        _repoint_push_items(conn, user_id, source, target, int(row["id"]), today)
        if str(row["state"]) in bank.BANK_STATES:
            bank.enqueue_content_if_needed(conn, target_row, priority=bank.CONTENT_PRIORITY_BANK, now=now)
        return words.user_word_dict(conn, new_row, user_id), None

    if str(other["state"]) not in bank.BANK_STATES:  # held as mastered / known / removed: no live SRS state to contest
        return _readd_held_target(conn, user_id, row, other, target_row, now=now, today=today)

    # both words in the bank: the row with more repetitions keeps its SRS state (ties: the older first_added_at, then id)
    def rank(r: Mapping[str, Any]) -> tuple[int, str, int]:
        return (-int(r.get("repetitions") or 0), str(r.get("first_added_at") or ""), int(r["id"]))

    winner, loser = sorted((dict(row), dict(other)), key=rank)
    winner_word_before = int(winner["word_id"])
    if winner["id"] == row["id"]:  # W's row wins → it takes L; L's row is parked on W and removed
        _swap_word_ids(conn, int(winner["id"]), int(loser["id"]), target, source)
        _reset_attention(conn, int(winner["id"]), target_row, now)  # its flags described W, which it no longer carries
    conn.execute("UPDATE user_words SET state = 'removed', due_at = NULL, updated_at = ? WHERE id = ?", (now, loser["id"]))
    bank.expire_open_suggestions(conn, int(loser["id"]), now)
    winner_after = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (winner["id"],))
    loser_after = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (loser["id"],))
    assert winner_after is not None and loser_after is not None
    if winner_word_before != target:
        _log_consolidate(conn, user_id, target, winner, winner_after, str(winner["state"]), str(winner["state"]), today, now)
    _log_consolidate(conn, user_id, int(loser_after["word_id"]), loser, loser_after, str(loser["state"]), "removed", today, now)
    bank._stats(conn, user_id, today, action="consolidate", context="consolidate", new_state="removed", item_kind=None, prev_state=str(loser["state"]))
    _repoint_push_items(conn, user_id, source, target, int(winner["id"]), today)
    conn.execute(
        "UPDATE push_items SET user_word_id = ? WHERE user_word_id = ? AND result IS NULL AND batch_id IN "
        "(SELECT id FROM push_batches WHERE user_id = ?)",
        (int(winner["id"]), int(loser["id"]), int(user_id)),
    )
    if str(winner_after["state"]) in bank.BANK_STATES:
        bank.enqueue_content_if_needed(conn, target_row, priority=bank.CONTENT_PRIORITY_BANK, now=now)
    return words.user_word_dict(conn, winner_after, user_id), int(loser_after["word_id"])


def _reset_attention(conn: sqlite3.Connection, user_word_id: int, target_row: Mapping[str, Any], now: str) -> None:
    """The 待处理 columns describe the string a row carries: cleared on the row that now holds the target (as API.md 36
    ``keep`` / endpoint 37 do), re-flagged only when the target itself is a word Claude rejected (DESIGN §5.2 step 4)."""
    bank.clear_attention(conn, user_word_id, now)
    if target_row.get("is_valid_english") == 0:
        conn.execute("UPDATE user_words SET needs_attention = 1, attention_msg = ? WHERE id = ?", (bank.ATTENTION_INVALID_MSG, int(user_word_id)))


def _readd_held_target(conn: sqlite3.Connection, user_id: int, row: Mapping[str, Any], other: Mapping[str, Any], target_row: Mapping[str, Any], *, now: str, today: str) -> tuple[dict[str, Any] | None, int | None]:
    """The user holds the target outside the bank (``mastered`` / ``known`` / ``removed``): the bank entry must survive
    the merge, so the held row re-enters per DESIGN §4 (``readd``: ``times_added+1``, priority 80, ``step=0``, ease
    penalty from ``mastered``, ``review_logs.action='readd'``, content enqueued) and the source row is parked as
    ``removed`` — a repetitions contest against a row with no live SRS state would drop the word the user just added."""
    source, target = int(row["word_id"]), int(target_row["id"])
    origin = str(row.get("origin") or "browse")
    bank.apply_action(
        conn,
        user_id,
        target,
        "unfamiliar",
        origin=origin if origin in bank.ORIGINS else "browse",
        context="consolidate",
        note=row.get("note"),
        input_text=row.get("input_text"),
        now=now,
        tz=bank.user_timezone(conn, user_id),
    )
    conn.execute("UPDATE user_words SET state = 'removed', due_at = NULL, updated_at = ? WHERE id = ?", (now, row["id"]))
    bank.expire_open_suggestions(conn, int(row["id"]), now)
    parked = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
    _log_consolidate(conn, user_id, source, row, parked, str(row["state"]), "removed", today, now)
    bank._stats(conn, user_id, today, action="consolidate", context="consolidate", new_state="removed", item_kind=None, prev_state=str(row["state"]))
    _repoint_push_items(conn, user_id, source, target, int(other["id"]), today)
    conn.execute(
        "UPDATE push_items SET user_word_id = ? WHERE user_word_id = ? AND result IS NULL AND batch_id IN "
        "(SELECT id FROM push_batches WHERE user_id = ?)",
        (int(other["id"]), int(row["id"]), int(user_id)),
    )
    kept = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (other["id"],))
    assert kept is not None
    return words.user_word_dict(conn, kept, user_id), source


# ------------------------------------------------------------------------------------------ decisions
def _load(conn: sqlite3.Connection, user_id: int, suggestion_id: int) -> dict[str, Any]:
    row = bank._row(conn, "SELECT * FROM bank_suggestions WHERE id = ?", (int(suggestion_id),))
    if row is None or int(row["user_id"]) != int(user_id):
        raise ApiError("not_found")
    return row


def _resolve(conn: sqlite3.Connection, suggestion_id: int, status: str, now: str) -> None:
    conn.execute("UPDATE bank_suggestions SET status = ?, resolved_at = ? WHERE id = ?", (status, now, int(suggestion_id)))


def _result(applied: bool, mine: dict[str, Any] | None, removed_word_id: int | None, message_zh: str) -> dict[str, Any]:
    return {"applied": applied, "mine": mine, "removed_word_id": removed_word_id, "message_zh": message_zh}


def apply_suggestion(conn: sqlite3.Connection, user_id: int, suggestion_id: int, decision: str, *, now: datetime | str | None = None) -> dict[str, Any]:
    """Apply ``accept`` / ``reject`` / ``undo`` to one suggestion (API.md 40–42); returns the ``SuggestionResult`` dict.

    409 ``already_resolved`` when the row is not in the state the decision needs; 409 ``undo_expired`` for an ``auto`` row
    past its 7-day window; 404 ``not_found`` for another user's row.
    """
    if decision not in ("accept", "reject", "undo"):
        raise ValueError(f"unknown decision {decision!r}")
    now_dt, now_s = bank.coerce_now(now)
    row = _load(conn, user_id, suggestion_id)
    if decision in ("accept", "reject") and _timed_out(row, now_s):
        with db.maybe_tx(conn):  # the timeout is recorded even though the request itself is refused
            _resolve(conn, int(row["id"]), "expired", now_s)
        raise ApiError("already_resolved", details={"status": "expired"})
    with db.maybe_tx(conn):
        row = _load(conn, user_id, suggestion_id)
        tz = bank.user_timezone(conn, user_id)
        today = bank.local_date_str(now_dt, tz)
        uw = None if row.get("user_word_id") is None else bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (int(row["user_word_id"]),))
        mine_now = None if uw is None else words.user_word_dict(conn, uw, user_id)

        if decision == "reject":
            if row["status"] != "open":
                raise ApiError("already_resolved", details={"status": row["status"]})
            _resolve(conn, int(row["id"]), "rejected", now_s)
            return _result(False, mine_now, None, MSG_REJECTED)

        if decision == "accept":
            if row["status"] != "open":
                raise ApiError("already_resolved", details={"status": row["status"]})
            return _accept(conn, user_id, row, uw, now_s, today)

        # undo
        if row["status"] != "auto":
            raise ApiError("already_resolved", details={"status": row["status"]})
        if row.get("expires_at") and str(row["expires_at"]) <= now_s:
            raise ApiError("undo_expired", details={"expires_at": row["expires_at"]})
        return _undo(conn, user_id, row, uw, now_s, today)


def _resolve_payload_target(conn: sqlite3.Connection, user_id: int, row: Mapping[str, Any], now: str) -> int | None:
    """``target_word_id`` for a repoint suggestion stored without one (``lookup_word`` step 2 keeps the proposal in
    ``payload.to`` only): the DESIGN §5.2 chain the user's own 添加 would run — exact → form → ECDICT → a provisional
    private word plus its debounced ``lookup_word`` job. None when the text does not normalise or is ambiguous."""
    to = _payload(row.get("payload_json")).get("to")
    norm = words.normalise_input(str(to or ""))
    if not norm.ok:
        return None
    assert isinstance(norm, words.Normalised)
    res = words.resolve(conn, norm.lemma, norm.display, norm.kind, user_id, now=now)
    if res.ambiguous or res.word_id is None:
        return None
    return int(res.word_id)


def _accept(conn, user_id, row, uw, now, today) -> dict[str, Any]:
    kind = str(row["type"])
    if kind in REPOINT_TYPES:
        if uw is None:
            raise ApiError("invalid_transition", details={"from": None, "action": "accept"})
        if str(uw["state"]) not in bank.BANK_STATES:
            raise ApiError("invalid_transition", details={"from": uw["state"], "action": "accept"})
        target_id = row.get("target_word_id")
        if target_id is None:
            target_id = _resolve_payload_target(conn, user_id, row, now)
            if target_id is None or target_id == int(uw["word_id"]):
                raise ApiError("invalid_transition", details={"from": None, "action": "accept", "reason": "no_target"})
            target_row = words.word_row(conn, target_id)
            if target_row is not None and target_row.get("is_valid_english") == 0:
                raise ApiError("invalid_transition", details={"from": None, "action": "accept", "reason": "invalid_target"})
            conn.execute("UPDATE bank_suggestions SET target_word_id = ? WHERE id = ?", (int(target_id), int(row["id"])))
        mine, removed = repoint_or_merge(conn, user_id, uw, int(target_id), now=now, today=today)
        _resolve(conn, int(row["id"]), "accepted", now)
        target = words.word_row(conn, int(target_id))
        to = str(target["display"]) if target else ""
        return _result(True, mine, removed, MSG_ACCEPTED_REPOINT.format(to=to))
    if kind == "invalid_word":
        if uw is None:
            raise ApiError("invalid_transition", details={"from": None, "action": "accept"})
        tz = bank.user_timezone(conn, user_id)
        try:
            r = bank.apply_action(conn, user_id, int(uw["word_id"]), "remove", origin="browse", context="consolidate", now=now, tz=tz)
            mine = r.mine
        except ApiError as e:
            if e.code != "invalid_transition":
                raise
            mine = words.user_word_dict(conn, uw, user_id)
        _resolve(conn, int(row["id"]), "accepted", now)
        return _result(True, mine, int(uw["word_id"]), MSG_ACCEPTED_REMOVED)
    # fill_data / difficulty / confusable_group are auto-applied by the handler; an open one just closes
    _resolve(conn, int(row["id"]), "accepted", now)
    return _result(True, None if uw is None else words.user_word_dict(conn, uw, user_id), None, MSG_ACCEPTED)


def _undo(conn, user_id, row, uw, now, today) -> dict[str, Any]:
    try:
        undo = json.loads(row.get("undo_json") or "{}")
    except ValueError:
        undo = {}
    if not isinstance(undo, dict):
        undo = {}
    mine = None if uw is None else words.user_word_dict(conn, uw, user_id)
    prev_word_id = undo.get("prev_word_id")
    if prev_word_id is not None and uw is not None:
        prev = int(prev_word_id)
        current = int(uw["word_id"])
        if prev != current:
            prev_row = words.word_row(conn, prev)
            if prev_row is None:
                raise ApiError("invalid_transition", details={"from": current, "action": "undo", "reason": "prev_word_missing"})
            if bank.my_row(conn, user_id, prev) is not None:
                raise ApiError("invalid_transition", details={"from": current, "action": "undo", "reason": "prev_word_held"})
            if prev_row.get("merged_into_word_id") is not None:
                prev_row = _unmerge_word(conn, prev_row, now)
            conn.execute("UPDATE user_words SET word_id = ?, updated_at = ? WHERE id = ?", (prev, now, uw["id"]))
            new_row = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (uw["id"],))
            _log_consolidate(conn, user_id, prev, uw, new_row, str(uw["state"]), str(uw["state"]), today, now)
            _repoint_push_items(conn, user_id, current, prev, int(uw["id"]), today)
            if str(uw["state"]) in bank.BANK_STATES:  # the merge cancelled W's content job; the restored entry is studied again
                bank.enqueue_content_if_needed(conn, prev_row, priority=bank.CONTENT_PRIORITY_BANK, now=now)
            mine = words.user_word_dict(conn, new_row, user_id)
    fields = undo.get("fields")
    if isinstance(fields, dict) and fields:
        wid = undo.get("word_id") or row.get("target_word_id") or (None if uw is None else uw["word_id"])
        if wid is not None and words.word_row(conn, int(wid)) is not None:
            allowed = {k: v for k, v in fields.items() if k in RESTORABLE_WORD_COLUMNS}
            if allowed:
                sets = ", ".join(f"{k} = :{k}" for k in allowed)
                conn.execute(f"UPDATE words SET {sets}, updated_at = :now WHERE id = :id", {**allowed, "now": now, "id": int(wid)})
    _resolve(conn, int(row["id"]), "undone", now)
    return _result(True, mine, None, MSG_UNDONE)


def _unmerge_word(conn: sqlite3.Connection, word: Mapping[str, Any], now: str) -> dict[str, Any]:
    """Restore a word ``lookup_word.merge_into`` tombstoned (CLAUDE_INTEGRATION §6.5 step 3) as a standalone private word.

    A bank row must never sit on a word with ``merged_into_word_id`` set: the batch builder skips it, detail/mark follow
    the merge and a later mark creates a second row on the target. ``is_public=0`` / ``is_valid_english=1`` stay as the
    merge left them; the ``alt`` form the merge inserted (W.lemma → L) goes, since no ``word_forms.form`` may equal the
    lemma of a live headword (DESIGN §3) — other holders' rows stay on L and undo later as a plain repoint.
    """
    wid, target = int(word["id"]), int(word["merged_into_word_id"])
    conn.execute("UPDATE words SET merged_into_word_id = NULL, updated_at = ? WHERE id = ?", (now, wid))
    conn.execute("DELETE FROM word_forms WHERE form = ? AND word_id = ? AND kind = 'alt'", (str(word["lemma"]), target))
    restored = words.word_row(conn, wid)
    assert restored is not None
    return restored


__all__ = ["apply_suggestion", "list_suggestions", "open_count", "repoint_or_merge", "suggestion_dict"]
