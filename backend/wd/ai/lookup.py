"""``lookup_word`` handler (CLAUDE_INTEGRATION §5.3, §6.1, §6.5) — validation / normalisation of user-added words.

Up to 20 provisional words per call (claimed together thanks to the 20-second debounce). Per returned item, one
transaction per word (:func:`apply_item`):

1. ``is_english=false`` / ``kind='invalid'`` → ``is_valid_english=0, is_public=0, content_state='failed'``; every bank
   row flagged 「未识别为英文单词：…」, a resolvable ``suggested_correction`` becomes ``suggested_word_id`` + 「是否改为 “…”？」
   (never auto-applied).
2. a headword that fails :func:`wd.services.words.validate_headword` → the row is kept as typed, dictionary fields
   filled, and an open ``fix_spelling`` suggestion is stored per holder (the proposal is visible only as a suggestion;
   ``target_word_id`` is set when the proposal resolves through DESIGN §5.2 steps 1–3 to another existing word, so the
   inbox shows that word's brief — otherwise it stays NULL and the accept path resolves ``payload.to``).
3. a validated headword with a different lemma → **merge** into the existing target — an exact headword or the unique
   ``word_forms`` target of the lemma (DESIGN §5.2 steps 1–2: ``children`` is a form of ``child``, never a new
   headword) — (holders repointed with their SRS state, duplicate holders' rows set to ``removed`` — never deleted —,
   ``word_forms(alt)``, ``merged_into_word_id``, the source word's content job cancelled, open-batch ``push_items``
   rewritten, 7-day ``auto`` undo rows; a holder who has the target only as ``mastered`` / ``known`` / ``removed`` while
   the typed word is in the bank gets the held row re-added per DESIGN §4 before the typed row is parked — the entry
   never leaves 生词库); an ambiguous form (``axes`` → ax / axe / axis) is handled like step 2; a **rename** of the
   provisional row only when the lemma is neither a headword nor a known form (DESIGN §3.2 guard).
4. NULL/empty dictionary fields filled, ``is_valid_english=1``, ``is_public = safe_for_sharing`` (also for a merge
   target that was itself still unvalidated); a resolvable ``suggested_correction`` → ``suggested_word_id`` +
   「是否改为 “…”？」 on the typed string's own bank rows (the rows a merge repointed), nothing else changed.
5. ``generate_content`` (priority 10) enqueued once for the final word when it lacks content — the single content
   trigger for custom words; pending attention flags cleared.

A job that ends ``dead`` leaves the word unvalidated and flags its bank rows with 「暂时无法校验，请稍后重试或检查拼写」
(UI buttons 修改 / 重试 / 保留 / 删除, API.md 36); while AI is disabled the Claude worker applies the same flag to the
rows behind every queued lookup (:func:`flag_queued_lookups`) and the jobs wait untouched.

A local write failure (``sqlite3.Error`` inside :func:`apply_item`) is not a model miss: that job alone fails with
``apply failed: …`` (§6.3 backoff → dead, the same flag on dead — exactly like consolidate) and the group's call is never
re-classified ``invalid_output`` because of it; only genuine misses (no item for the string) count as the answer's
post-validation failure and, on the fallback, its quality streak (§10.4).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .. import db
from ..clock import parse_iso, to_iso
from ..interfaces import Job
from ..jobs import queue
from ..jobs.registry import JobContext, register
from ..services import bank, ecdict, words
from . import common, ledger, models, runner

log = logging.getLogger("wd.ai.lookup")

KIND = "lookup"
CONTENT_PRIORITY = 10
MSG_INVALID = "未识别为英文单词"
MSG_SUGGEST = "是否改为 “{display}”？"
MSG_DEAD = "暂时无法校验，请稍后重试或检查拼写"
FIX_SPELLING_CONFIDENCE = 0.5
OPEN_EXPIRES = timedelta(days=30)
AUTO_EXPIRES = timedelta(days=7)
NOTE_MAX = 120
FIELD_MAX = 200
ITEM_KINDS: tuple[str, ...] = ("word", "phrase", "abbreviation", "proper_noun")


def build_user_prompt(strings: list[str]) -> str:
    """CLAUDE_INTEGRATION §5.3 user prompt: raw strings only, no user identifiers."""
    return "Look up these strings typed by learners.\n<items>\n" + json.dumps({"items": strings}, ensure_ascii=False) + "\n</items>"


# ------------------------------------------------------------------------------------- helpers
def holders(conn: sqlite3.Connection, word_id: int) -> list[dict[str, Any]]:
    """Every ``user_words`` row on the word (any state), oldest first."""
    return bank._rows(conn, "SELECT * FROM user_words WHERE word_id = ? ORDER BY id", (int(word_id),))


def bank_holders(conn: sqlite3.Connection, word_id: int) -> list[dict[str, Any]]:
    return [h for h in holders(conn, word_id) if h["state"] in bank.BANK_STATES]


def resolve_existing(conn: sqlite3.Connection, text: str, *, created_by: int | None, now: str) -> dict[str, Any] | None:
    """DESIGN §5.2 steps 1–3 (exact → unique form → ECDICT) for a Claude-proposed correction; never creates a provisional
    row. An ambiguous form (``axes`` → ax / axe / axis) ends the chain with None exactly as :func:`wd.services.words.resolve`
    does — the ECDICT step must not turn it into a headword (DESIGN §3.2)."""
    norm = words.normalise_input(text or "")
    if not norm.ok:
        return None
    assert isinstance(norm, words.Normalised)
    row = words.word_by_lemma(conn, norm.lemma)
    if row is not None:
        final, _ = words.follow_merge(conn, row)
        return final
    res = words._resolve_forms(conn, norm.lemma, created_by or 0)
    if res is not None:
        return None if res.word_id is None else words.word_row(conn, int(res.word_id))
    if ecdict.lookup(norm.lemma) is not None:
        res = words._resolve_ecdict(conn, norm.lemma, created_by, now)  # type: ignore[arg-type]
        if res is not None and res.word_id is not None:
            return words.word_row(conn, int(res.word_id))
    return None


def repoint_push_items(conn: sqlite3.Connection, user_id: int, from_word: int, to_word: int, to_user_word_id: int | None, local_date: str) -> None:
    """DESIGN §6.3: ``push_items.word_id`` W → L in the user's open batches (ungraded duplicates dropped, history kept)."""
    ids = bank.open_batch_ids(conn, user_id, local_date)
    if not ids or from_word == to_word:
        return
    marks = ",".join("?" * len(ids))
    dup = "EXISTS (SELECT 1 FROM push_items p2 WHERE p2.batch_id = push_items.batch_id AND p2.word_id = ? AND p2.kind = push_items.kind)"
    conn.execute(f"DELETE FROM push_items WHERE word_id = ? AND result IS NULL AND batch_id IN ({marks}) AND {dup}", (int(from_word), *ids, int(to_word)))
    conn.execute(
        f"UPDATE push_items SET word_id = ?, user_word_id = COALESCE(?, user_word_id) WHERE word_id = ? AND batch_id IN ({marks}) AND NOT {dup}",
        (int(to_word), to_user_word_id, int(from_word), *ids, int(to_word)),
    )


def _log_consolidate(conn, user_id, word_id, row, prev_state, new_state, *, today, now) -> int:
    new_row = bank._row(conn, "SELECT * FROM user_words WHERE id = ?", (row["id"],))
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


def has_open_suggestion(conn: sqlite3.Connection, user_word_id: int, type_: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM bank_suggestions WHERE user_word_id = ? AND type = ? AND status = 'open'", (int(user_word_id), type_)).fetchone()
        is not None
    )


def insert_suggestion(
    conn: sqlite3.Connection,
    *,
    user_id: int,
    type_: str,
    user_word_id: int | None,
    target_word_id: int | None,
    payload: Mapping[str, Any],
    status: str,
    now: str,
    run_id: int | None = None,
    undo: Mapping[str, Any] | None = None,
) -> int:
    expires = None
    if status == "open":
        expires = to_iso(parse_iso(now) + OPEN_EXPIRES)
    elif status == "auto":
        expires = to_iso(parse_iso(now) + AUTO_EXPIRES)
    cur = conn.execute(
        "INSERT INTO bank_suggestions(user_id, run_id, type, user_word_id, target_word_id, payload_json, status, undo_json, expires_at, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            int(user_id),
            run_id,
            type_,
            user_word_id,
            target_word_id,
            json.dumps(dict(payload), ensure_ascii=False),
            status,
            None if undo is None else json.dumps(dict(undo), ensure_ascii=False),
            expires,
            now,
        ),
    )
    return int(cur.lastrowid)


def set_dead_attention(conn: sqlite3.Connection, word_id: int, *, now: str) -> int:
    """The 「暂时无法校验」 flag on the bank rows of a word that could not be validated (dead job / AI off)."""
    with db.maybe_tx(conn):
        cur = conn.execute(
            "UPDATE user_words SET needs_attention = 1, attention_msg = ?, updated_at = ? "
            "WHERE word_id = ? AND state IN ('new','learning') "
            "AND EXISTS (SELECT 1 FROM words w WHERE w.id = user_words.word_id AND w.is_valid_english IS NULL)",
            (MSG_DEAD, now, int(word_id)),
        )
        return int(cur.rowcount)


def flag_queued_lookups(conn: sqlite3.Connection, *, now: str) -> int:
    """§6.5 while AI is disabled: the bank rows behind every queued ``lookup_word`` job get 「暂时无法校验」, so the learner
    sees the 修改 / 重试 / 保留 / 删除 buttons instead of an endless 待校验 badge. The jobs stay untouched and run when AI
    resumes (step 5 then clears the flag, or the handler re-flags it). Idempotent; returns the rows flagged. Rows already
    carrying a message keep it; a 重新校验中 row (``attention_msg`` NULL) gets the message back."""
    with db.maybe_tx(conn):
        cur = conn.execute(
            "UPDATE user_words SET needs_attention = 1, attention_msg = ?, updated_at = ? "
            "WHERE state IN ('new','learning') AND (needs_attention = 0 OR attention_msg IS NULL) "
            "AND word_id IN (SELECT json_extract(payload_json, '$.word_id') FROM jobs WHERE type = 'lookup_word' AND status = 'queued') "
            "AND EXISTS (SELECT 1 FROM words w WHERE w.id = user_words.word_id AND w.is_valid_english IS NULL)",
            (MSG_DEAD, now),
        )
        return int(cur.rowcount)


# --------------------------------------------------------------------------------------- merge
def merge_into(conn: sqlite3.Connection, source: Mapping[str, Any], target: Mapping[str, Any], *, note_zh: str, now: str) -> dict[str, Any]:
    """§6.5 step 3 (target exists): repoint every holder of W onto L, park duplicates as ``removed``, mark W merged.

    A holder whose L row is outside the bank (``mastered`` / ``known`` / ``removed``) while the W row is in it has L
    re-added first per DESIGN §4 (``readd``: ``times_added+1``, priority 80, ease penalty from ``mastered``,
    ``review_logs.action='readd'``, content enqueued) — parking W against a row with no live SRS state would make the
    word the user just added vanish from 生词库 (the same rule as ``suggestions.repoint_or_merge``).
    """
    w_id, l_id = int(source["id"]), int(target["id"])
    for row in holders(conn, w_id):
        uid = int(row["user_id"])
        today = bank.local_date_str(parse_iso(now), bank.user_timezone(conn, uid))
        other = bank.my_row(conn, uid, l_id)
        if other is None:
            conn.execute("UPDATE user_words SET word_id = ?, updated_at = ? WHERE id = ?", (l_id, now, row["id"]))
            _log_consolidate(conn, uid, l_id, row, str(row["state"]), str(row["state"]), today=today, now=now)
            insert_suggestion(
                conn,
                user_id=uid,
                type_="lemmatize",
                user_word_id=int(row["id"]),
                target_word_id=l_id,
                payload={"from": source["display"], "to": target["display"], "note_zh": note_zh},
                status="auto",
                now=now,
                undo={"prev_word_id": w_id},
            )
            repoint_push_items(conn, uid, w_id, l_id, int(row["id"]), today)
        else:
            if str(row["state"]) in bank.BANK_STATES and str(other["state"]) not in bank.BANK_STATES:
                # the holder has L only as mastered / known / removed: re-add it (DESIGN §4) before parking W, and write
                # the 7-day 「已自动整理」 row on the row that now carries the entry
                bank.apply_action(
                    conn,
                    uid,
                    l_id,
                    "unfamiliar",
                    origin=str(row["origin"]),
                    context="consolidate",
                    note=row.get("note"),
                    input_text=row.get("input_text"),
                    now=now,
                    tz=bank.user_timezone(conn, uid),
                )
                insert_suggestion(
                    conn,
                    user_id=uid,
                    type_="lemmatize",
                    user_word_id=int(other["id"]),
                    target_word_id=l_id,
                    payload={"from": source["display"], "to": target["display"], "note_zh": note_zh},
                    status="auto",
                    now=now,
                    undo={"prev_word_id": w_id},
                )
            if str(row["state"]) != "removed":
                conn.execute("UPDATE user_words SET state = 'removed', due_at = NULL, updated_at = ? WHERE id = ?", (now, row["id"]))
                _log_consolidate(conn, uid, w_id, row, str(row["state"]), "removed", today=today, now=now)
            bank.expire_open_suggestions(conn, int(row["id"]), now)
            repoint_push_items(conn, uid, w_id, l_id, int(other["id"]), today)
    conn.execute("INSERT OR IGNORE INTO word_forms(form, word_id, kind) VALUES (?, ?, 'alt')", (source["lemma"], l_id))
    conn.execute(
        "UPDATE words SET merged_into_word_id = ?, is_public = 0, is_valid_english = 1, updated_at = ? WHERE id = ?",
        (l_id, now, w_id),
    )
    live = queue.live_job(conn, f"content:{w_id}")
    if live is not None:
        queue.cancel(conn, [live.id], now=now)
    refreshed = words.word_row(conn, l_id)
    assert refreshed is not None
    return refreshed


def headword_target(conn: sqlite3.Connection, lemma: str, *, created_by: int | None) -> tuple[dict[str, Any] | None, bool, str | None]:
    """§6.5 step 3 "target exists" = DESIGN §5.2 steps 1–2 for the validated headword: the exact ``words`` row (merges
    followed) or the unique ``word_forms`` target of the lemma. Returns ``(row, ambiguous, lemma_note_zh)``;
    ``(None, True, None)`` when the lemma is an ambiguous form (``axes`` → ax / axe / axis), ``(None, False, None)``
    when it is unknown. Never creates rows (the ECDICT step is not run here)."""
    row = words.word_by_lemma(conn, lemma)
    if row is not None:
        final, _ = words.follow_merge(conn, row)
        return final, False, None
    res = words._resolve_forms(conn, lemma, int(created_by or 0))
    if res is None:
        return None, False, None
    if res.ambiguous or res.word_id is None:
        return None, True, None
    return words.word_row(conn, int(res.word_id)), False, res.lemma_note_zh


def rename_word(conn: sqlite3.Connection, word: Mapping[str, Any], norm: words.Normalised, *, now: str) -> dict[str, Any] | None:
    """§6.5 step 3 (no target): the provisional row becomes the headword; the typed string stays reachable as a form.

    Headword guard (DESIGN §3.2, the mirror of :func:`wd.services.words.add_form`): a lemma that is a ``word_forms`` row
    of another live word is never made a headword — it would shadow that word's form resolution for every user — so
    nothing is changed and None is returned (the caller falls back to step 2). Form rows pointing at the word itself
    are dropped: a headword is never its own form."""
    wid = int(word["id"])
    own_form_rows: list[int] = []
    for (holder_id,) in conn.execute("SELECT word_id FROM word_forms WHERE form = ?", (norm.lemma,)).fetchall():
        holder = words.word_row(conn, int(holder_id))
        final = words.follow_merge(conn, holder)[0] if holder is not None else None
        if final is not None and int(final["id"]) != wid:
            log.warning("lookup: %r is a form of %r; not renaming %r onto it", norm.lemma, final["lemma"], word["lemma"])
            return None
        own_form_rows.append(int(holder_id))
    conn.execute(
        "UPDATE words SET lemma = ?, display = ?, kind = ?, updated_at = ? WHERE id = ?",
        (norm.lemma, norm.display, norm.kind, now, wid),
    )
    if own_form_rows:
        conn.execute(f"DELETE FROM word_forms WHERE form = ? AND word_id IN ({','.join('?' * len(own_form_rows))})", (norm.lemma, *own_form_rows))
    conn.execute("INSERT OR IGNORE INTO word_forms(form, word_id, kind) VALUES (?, ?, 'alt')", (word["lemma"], wid))
    refreshed = words.word_row(conn, wid)
    assert refreshed is not None
    return refreshed


# ---------------------------------------------------------------------------------------- apply
def _text(item: Mapping[str, Any], key: str, max_len: int = FIELD_MAX) -> str:
    return common.clean_text(item.get(key), max_len=max_len) or ""


def fill_fields(conn: sqlite3.Connection, word: Mapping[str, Any], item: Mapping[str, Any], *, now: str, own_row: bool) -> list[str]:
    """§6.5 step 4: fill NULL/empty dictionary fields, validate the word, apply the sharing verdict; returns the columns set.

    ``is_public = safe_for_sharing`` (and ``source='claude'``) apply whenever this item is the one validating the row:
    its own word, or a merge target that was still unvalidated (``is_valid_english != 1``) — otherwise a word Claude
    vouched for would stay private for ever, since the target's own lookup job is then skipped as ``already_validated``.
    A merge into an already public seed/ECDICT headword never touches its ``is_public`` or ``kind``."""
    sets: dict[str, Any] = {}
    meaning_zh = _text(item, "meaning_zh")
    if not word.get("translation") and meaning_zh and common.has_cjk(meaning_zh):
        sets["translation"] = meaning_zh
    definition = _text(item, "definition_en")
    if not word.get("definition") and definition:
        sets["definition"] = definition
    phonetic = common.clean_phonetic(item.get("phonetic"), max_len=60) or ""
    if not word.get("phonetic") and phonetic:
        sets["phonetic"] = phonetic
    pos = _text(item, "pos", 40)
    if not word.get("pos") and pos:
        sets["pos"] = pos
    difficulty = item.get("difficulty")
    if word.get("difficulty") is None and isinstance(difficulty, int) and not isinstance(difficulty, bool) and 1 <= difficulty <= 5:
        sets["difficulty"] = int(difficulty)
    kind = item.get("kind")
    if own_row and word.get("kind") == "word" and isinstance(kind, str) and kind in ITEM_KINDS and kind != "word":
        sets["kind"] = kind
    safe = 1 if item.get("safe_for_sharing") is True else 0
    sets["is_valid_english"] = 1
    sets["safe_for_sharing"] = safe
    validating = own_row or word.get("is_valid_english") != 1
    if validating:
        sets["is_public"] = safe
        if word.get("source") == "user":
            sets["source"] = "claude"
    assignments = ", ".join(f"{k} = :{k}" for k in sets)
    conn.execute(f"UPDATE words SET {assignments}, updated_at = :now WHERE id = :id", {**sets, "now": now, "id": int(word["id"])})
    return sorted(sets)


def _flag_invalid(conn: sqlite3.Connection, word: Mapping[str, Any], item: Mapping[str, Any], *, now: str) -> int | None:
    wid = int(word["id"])
    note = _text(item, "note_zh", NOTE_MAX)
    safe = 1 if item.get("safe_for_sharing") is True else 0
    conn.execute(
        "UPDATE words SET is_valid_english = 0, is_public = 0, safe_for_sharing = ?, content_state = 'failed', updated_at = ? WHERE id = ?",
        (safe, now, wid),
    )
    note = note.rstrip("。．.；;，, ")  # Claude's note_zh usually ends with 。 — never produce 「…。；是否改为…」
    msg = MSG_INVALID + (f"：{note}" if note else "")
    suggested: dict[str, Any] | None = None
    correction = _text(item, "suggested_correction", 48)
    if correction:
        suggested = resolve_existing(conn, correction, created_by=word.get("created_by_user_id"), now=now)
        if suggested is not None and int(suggested["id"]) == wid:
            suggested = None
    if suggested is not None:
        msg = f"{msg}；{MSG_SUGGEST.format(display=suggested['display'])}"
    conn.execute(
        "UPDATE user_words SET needs_attention = 1, attention_msg = ?, suggested_word_id = ?, updated_at = ? WHERE word_id = ? AND state IN ('new','learning')",
        (msg, None if suggested is None else int(suggested["id"]), now, wid),
    )
    return None if suggested is None else int(suggested["id"])


def _suggest_fix_spelling(conn: sqlite3.Connection, word: Mapping[str, Any], proposed: str, item: Mapping[str, Any], *, now: str) -> int:
    """Step 2: one open ``fix_spelling`` per bank holder. ``target_word_id`` is the existing word the proposal resolves to
    (DESIGN §5.2 steps 1–3, never the word itself) so the inbox shows its brief; unresolved, it stays NULL and the accept
    path resolves ``payload.to`` (API.md 40)."""
    count = 0
    note = _text(item, "note_zh", NOTE_MAX) or _text(item, "form_note_zh", NOTE_MAX)
    target = resolve_existing(conn, proposed, created_by=word.get("created_by_user_id"), now=now)
    target_id = None if target is None or int(target["id"]) == int(word["id"]) else int(target["id"])
    for row in bank_holders(conn, int(word["id"])):
        if has_open_suggestion(conn, int(row["id"]), "fix_spelling"):
            continue
        insert_suggestion(
            conn,
            user_id=int(row["user_id"]),
            type_="fix_spelling",
            user_word_id=int(row["id"]),
            target_word_id=target_id,
            payload={"from": word["display"], "to": proposed, "note_zh": note, "confidence": FIX_SPELLING_CONFIDENCE},
            status="open",
            now=now,
        )
        count += 1
    return count


def _apply_correction(conn: sqlite3.Connection, final: Mapping[str, Any], source_id: int, item: Mapping[str, Any], *, row_ids: Sequence[int], now: str) -> int | None:
    """Step 4 ``suggested_correction``: a ``did-you-mean`` target on the typed string's own bank rows (``row_ids`` — after a
    merge these are the rows repointed onto L, never L's other holders, who did not mistype anything), nothing else changed."""
    correction = _text(item, "suggested_correction", 48)
    if not correction or not row_ids:
        return None
    suggested = resolve_existing(conn, correction, created_by=final.get("created_by_user_id"), now=now)
    if suggested is None or int(suggested["id"]) in (int(final["id"]), source_id):
        return None
    marks = ",".join("?" * len(row_ids))
    conn.execute(
        f"UPDATE user_words SET suggested_word_id = ?, needs_attention = 1, attention_msg = ?, updated_at = ? "
        f"WHERE id IN ({marks}) AND word_id = ? AND state IN ('new','learning')",
        (int(suggested["id"]), MSG_SUGGEST.format(display=suggested["display"]), now, *[int(i) for i in row_ids], int(final["id"])),
    )
    return int(suggested["id"])


def _clear_pending(conn: sqlite3.Connection, word_id: int, *, now: str) -> None:
    """Step 5: nothing is pending any more for the holders without a did-you-mean target."""
    conn.execute(
        "UPDATE user_words SET needs_attention = 0, attention_msg = NULL, updated_at = ? "
        "WHERE word_id = ? AND needs_attention = 1 AND suggested_word_id IS NULL",
        (now, int(word_id)),
    )


def apply_item(conn: sqlite3.Connection, word: Mapping[str, Any], item: Mapping[str, Any], *, now: str) -> dict[str, Any]:
    """Apply one lookup item to ``word`` in one transaction (§6.5); returns ``{outcome, word_id, …}``."""
    with db.maybe_tx(conn):
        fresh = words.word_row(conn, int(word["id"]))
        if fresh is None:
            return {"outcome": "missing", "word_id": int(word["id"])}
        if fresh.get("merged_into_word_id") is not None:
            return {"outcome": "merged_already", "word_id": int(fresh["merged_into_word_id"])}
        wid = int(fresh["id"])
        if item.get("is_english") is not True or item.get("kind") == "invalid":
            suggested = _flag_invalid(conn, fresh, item, now=now)
            return {"outcome": "invalid", "word_id": wid, "suggested_word_id": suggested}
        own_rows = [int(r["id"]) for r in holders(conn, wid)]  # the typed string's bank rows — what a merge repoints
        headword = item.get("headword") if isinstance(item.get("headword"), str) else ""
        norm = common.validate_target(conn, headword, str(fresh["lemma"]))
        final: dict[str, Any] = fresh
        outcome = "filled"
        detail: dict[str, Any] = {}
        if norm is None:
            proposed = common.clean_text(headword, max_len=48) or ""
            if proposed and proposed.lower() != str(fresh["lemma"]):
                detail["suggestions"] = _suggest_fix_spelling(conn, fresh, proposed, item, now=now)
                outcome = "kept"
        elif norm.lemma != str(fresh["lemma"]):
            target, ambiguous, form_note = headword_target(conn, norm.lemma, created_by=fresh.get("created_by_user_id"))
            renamed: dict[str, Any] | None = None
            if target is not None and int(target["id"]) != wid:
                final = merge_into(conn, fresh, target, note_zh=_text(item, "form_note_zh", NOTE_MAX) or form_note or "", now=now)
                outcome = "merged"
            else:
                if not ambiguous:
                    renamed = rename_word(conn, fresh, norm, now=now)
                if renamed is None:
                    # an ambiguous form (axes → ax / axe / axis) or a form of another live word never becomes a headword: step 2
                    detail["suggestions"] = _suggest_fix_spelling(conn, fresh, norm.display, item, now=now)
                    outcome = "kept"
                else:
                    final = renamed
                    outcome = "renamed"
        own_row = int(final["id"]) == wid
        filled = fill_fields(conn, final, item, now=now, own_row=own_row)
        final = words.word_row(conn, int(final["id"])) or final
        suggested = _apply_correction(conn, final, wid, item, row_ids=own_rows, now=now)
        job_id = bank.enqueue_content_if_needed(conn, final, priority=CONTENT_PRIORITY, now=now)
        _clear_pending(conn, int(final["id"]), now=now)
        if not own_row:
            _clear_pending(conn, wid, now=now)
        return {"outcome": outcome, "word_id": int(final["id"]), "filled": filled, "content_job_id": job_id, "suggested_word_id": suggested, **detail}


# -------------------------------------------------------------------------------------- handler
def _on_dead(now: str) -> common.OnDead:
    def on_dead(conn: sqlite3.Connection, job: Job) -> None:
        wid = common.payload_int(job, "word_id")
        if wid is not None:
            set_dead_attention(conn, wid, now=now)

    return on_dead


def select_jobs(conn: sqlite3.Connection, jobs: list[Job], *, now: str) -> list[tuple[Job, dict[str, Any]]]:
    todo: list[tuple[Job, dict[str, Any]]] = []
    for job in jobs:
        wid = common.payload_int(job, "word_id")
        word = None if wid is None else words.word_row(conn, wid)
        if word is None:
            queue.finish(conn, job.id, {"skipped": "missing_word"}, now=now)
            continue
        if word.get("merged_into_word_id") is not None:
            queue.finish(conn, job.id, {"skipped": "merged"}, now=now)
            continue
        if word.get("is_valid_english") is not None:
            queue.finish(conn, job.id, {"skipped": "already_validated"}, now=now)
            continue
        todo.append((job, word))
    return todo


@register("lookup_word")
def handle_lookup_word(ctx: JobContext, jobs: list[Job]) -> None:
    conn = ctx.db()
    try:
        now = ctx.now()
        todo = select_jobs(conn, jobs, now=now)
        if not todo:
            return
        group = [j for j, _ in todo]
        strings = [str(word["display"]) for _, word in todo]
        on_dead = _on_dead(now)

        def on_disabled() -> None:
            for _, word in todo:
                set_dead_attention(conn, int(word["id"]), now=now)

        result = common.claude_call(
            ctx,
            conn,
            kind=KIND,
            jobs=group,
            system_prompt=runner.load_prompt("lookup_system"),
            user_prompt=build_user_prompt(strings),
            schema=runner.load_schema("lookup_v1"),
            word_count=len(todo),
            now=now,
            on_disabled=on_disabled,
        )
        if result is None:
            return
        if not result.ok:
            common.handle_failure(ctx, conn, group, result, now=now, on_dead=on_dead)
            return
        common.record_success(conn, now=now)
        index = common.item_index(models.valid_items(result.structured, models.LookupItem), "input")
        failures: list[tuple[Job, str]] = []  # genuine post-validation misses only (no item for the string)
        done = 0
        apply_errors = 0
        for job, word in todo:
            item = index.get(str(word["display"]).lower()) or index.get(str(word["lemma"]).lower())
            if item is None:
                failures.append((job, "no item for this string in the response"))
                continue
            try:
                outcome = apply_item(conn, word, item, now=now)
            except sqlite3.Error as e:
                # a local write failure, not a model miss (mirrors consolidate): this job backs off / dies on its own and
                # never feeds the group's re-classification or the fallback's quality streak (§6.5, §10.4)
                log.exception("lookup apply failed for word %s", word["lemma"], extra={"job_id": job.id, "job_type": job.type})
                common.fail_job(conn, job, f"apply failed: {e}", now=now, on_dead=on_dead)
                apply_errors += 1
                continue
            queue.finish(conn, job.id, outcome, now=now)
            done += 1
        if done:
            common.record_applied(conn, ctx.cfg, result, now=now)  # the answering provider's quality streak ends (§10.4)
        if failures and not done and not apply_errors:
            # every item failed post-validation → re-classified; on the fallback the rejected group counts its quality streak (§10.4)
            # (an item that reached apply_item was usable: a group with apply errors is never re-classified, its misses stay `partial`)
            ledger.set_status(conn, result.call_id, "invalid_output", error="; ".join(d for _, d in failures)[:1000])
            failed = type(result)(
                ok=False, status="invalid_output", structured=None, cost_usd=result.cost_usd, call_id=result.call_id, model_used=result.model_used, error=failures[0][1], provider=result.provider
            )
            common.record_invalid_output(conn, ctx.cfg, failed, kind=KIND, priority=min(j.priority for j in group), now=now)
            common.handle_failure(ctx, conn, [j for j, _ in failures], failed, now=now, on_dead=on_dead)
        else:
            for job, detail in failures:
                common.fail_job(conn, job, f"partial: {detail}", now=now, on_dead=on_dead)
        ctx.log.info("lookup_word: %d applied, %d failed, %d apply error(s) (call %s)", done, len(failures), apply_errors, result.call_id, extra={"job_type": "lookup_word", "cost_usd": result.cost_usd, "event": "lookup_applied"})
    finally:
        conn.close()


__all__ = [
    "MSG_DEAD",
    "MSG_INVALID",
    "MSG_SUGGEST",
    "apply_item",
    "build_user_prompt",
    "fill_fields",
    "flag_queued_lookups",
    "handle_lookup_word",
    "headword_target",
    "insert_suggestion",
    "merge_into",
    "rename_word",
    "repoint_push_items",
    "resolve_existing",
    "select_jobs",
    "set_dead_attention",
]
