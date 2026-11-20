"""Screening (筛词 / 推荐词) services (WP3): candidates and verdicts.

Contracts: API.md 31/32 (``GET /api/screen/next``, ``POST /api/screen/verdict``), DESIGN §6.3 step 4 (candidate order:
``stage_distance`` from the 主攻阶段 — ``learn_order.stage_distance_sql``, NULL ``stage_min`` last — then the learning order
``learn_order.ORDER_SQL``: the derived ``words.learn_rank`` with the frequency tail), DESIGN §4 (verdict → state machine through
:func:`wd.services.bank.apply_action`), DESIGN §6.3 (an in-batch ``unfamiliar`` keeps the ``screen`` push row and —
while TODAY's new-word quota has room — appends a second ``kind='new'`` row through WP4's ``batches.append_to_today``;
``added_to_today:false`` when there is no batch today or the word is already in it). The room/duplicate checks run on
the batch the append writes to (today's), also for a 推荐词 graded in yesterday's still-open batch. ``today`` carries
the ``TodayCounts`` of today's batch whenever one exists (the 筛词 page shows 「已加入生词库，明天开始学」 from it).

:func:`study_item_dict` builds the API.md ``StudyItem`` for a ``push_items`` row from the WP1 word helpers so the
``ScreenResponse.study_item`` (and WP4's ``GradeResponse.study_item``) need nothing beyond this package.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from .. import dance, db
from ..errors import ApiError
from ..schemas import stage_to_index
from . import bank, learn_order, words

log = logging.getLogger("wd.screen")

VERDICTS: tuple[str, ...] = ("known", "unfamiliar", "skip")
SCREEN_CONTEXTS: tuple[str, ...] = ("screen_page", "onboarding", "today", "extra")
STUDY_KINDS: tuple[str, ...] = ("review", "new", "extra")


def _stage_scope(conn: sqlite3.Connection, user_id: int, stage: str) -> tuple[list[str], int]:
    """``(stages, current_stage_index)`` for the filter: ``auto`` = the user's 目标阶段 with the 主攻阶段 first."""
    s = bank.user_settings_row(conn, user_id)
    if stage == "auto":
        stages = list(s["stages"])
        return stages, bank.current_stage_index(s)
    if stage not in words.STAGES:
        raise ApiError("validation_error", details={"fields": {"stage": "unknown stage"}})
    return [stage], stage_to_index(stage)


def _candidate_sql(stages: list[str]) -> str:
    flags = " OR ".join(f"w.stage_{s} = 1" for s in stages) or "0"
    return (
        "FROM words w WHERE w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL "
        f"AND ({flags}) AND NOT EXISTS (SELECT 1 FROM user_words uw WHERE uw.user_id = :me AND uw.word_id = w.id)"
    )


def screen_next(conn: sqlite3.Connection, user_id: int, stage: str, count: int) -> tuple[list[dict[str, Any]], int]:
    """API.md 31: unseen stage words ordered as DESIGN §6.3 step 4; ``remaining`` = total unseen for the filter. Read-only."""
    stages, cur = _stage_scope(conn, user_id, stage)
    body = _candidate_sql(stages)
    params = {"me": int(user_id), "cur": cur}
    remaining = int(conn.execute(f"SELECT COUNT(*) {body}", params).fetchone()[0])
    rows = conn.execute(
        f"SELECT w.* {body} ORDER BY {learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL} LIMIT :limit",
        {**params, "limit": max(1, int(count))},
    ).fetchall()
    items = []
    for r in rows:
        d = {k: r[k] for k in r.keys()}
        d["my_state"] = None
        items.append({"word": words.word_brief(conn, d, user_id), "phonetic": d.get("phonetic") or None})
    return items, remaining


# -------------------------------------------------------------------------------------- study items
def study_item_dict(conn: sqlite3.Connection, user_id: int, item_id: int, *, now: str, cfg: Any = None) -> dict[str, Any] | None:
    """API.md ``StudyItem`` for ``push_items.id`` (None when the row does not exist)."""
    item = bank.push_item_row(conn, item_id)
    if item is None:
        return None
    word = words.word_row(conn, int(item["word_id"]))
    if word is None:
        return None
    wid = int(word["id"])
    mine = words.my_user_word(conn, wid, user_id)
    brief = words.word_brief(conn, {**word, "my_state": None if mine is None else mine["state"]}, user_id)
    word_dto = {
        **brief,
        "definition": word.get("definition") or None,
        "translation": word.get("translation") or None,
        "pos": word.get("pos") or None,
        "forms": words.forms_of(conn, wid),
        "confusables": words.confusables_for(conn, user_id, str(word["lemma"])),
        "dance": dance.spec_for_word(conn, word),
    }
    requeue_at = None
    if mine is not None and int(mine["srs"]["step"]) == 1 and mine["srs"]["due_at"] and str(mine["srs"]["due_at"]) > now:
        requeue_at = str(mine["srs"]["due_at"])
    content_state = word.get("content_state") or "none"
    return {
        "item_id": int(item["id"]),
        "kind": item["kind"],
        "position": int(item["position"]),
        "result": item.get("result"),
        "skip_count": int(item.get("skip_count") or 0),
        "requeue_at": requeue_at,
        "word": word_dto,
        "mine": mine,
        "content": words.active_content(conn, word),
        "content_state": content_state,
        "content_deferred_until": bank.content_deferred_until(conn, wid, now=now, cfg=cfg) if content_state == "queued" else None,
        "image": words.image_meta_for(conn, wid),
    }


def has_study_row(conn: sqlite3.Connection, batch_id: int, word_id: int) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM push_items WHERE batch_id = ? AND word_id = ? AND kind IN ('review','new','extra') LIMIT 1",
            (int(batch_id), int(word_id)),
        ).fetchone()
        is not None
    )


def new_quota_room(conn: sqlite3.Connection, batch_id: int, daily_new_count: int) -> bool:
    """DESIGN §6.3: ``new_done + new_remaining < daily_new_count`` (every ``kind='new'`` row of the batch counts)."""
    n = int(conn.execute("SELECT COUNT(*) FROM push_items WHERE batch_id = ? AND kind = 'new'", (int(batch_id),)).fetchone()[0])
    return n < int(daily_new_count)


def today_counts_for(conn: sqlite3.Connection, user_id: int, batch: dict[str, Any], *, now: str, cfg: Any = None) -> dict[str, Any]:
    """``TodayCounts`` of ``batch`` over its non-stale items (``batches`` imports this module, hence the late import)."""
    from . import batches

    return batches.today_counts(conn, batch, batches.visible_items(conn, user_id, int(batch["id"])), now=now, cfg=cfg)


# ``ImageMeta`` fields that did not exist when older responses were stored whole in ``review_logs.result_json``, with what they
# mean for a picture of that time: the three of migration 0021 (记忆图卡) — every picture stored before it was a photo, an
# online drawing or the template card, none of them a card with a word layer and a hook
STORED_IMAGE_DEFAULTS: dict[str, Any] = {"word_layer": False, "dancing": False, "hook_zh": None, "note_zh": None}  # dancing: 跳动图卡 release


def upgrade_stored(data: dict[str, Any]) -> dict[str, Any]:
    """Bring a response snapshot read back from ``review_logs.result_json`` up to today's DTO, in place (``ScreenResponse``
    here, ``GradeResponse`` in ``batches._stored_grade``).

    The snapshot is the whole response as the build of its day wrote it, and its ``study_item.image`` is an ``ImageMeta``: one
    stored before the 记忆图卡 release has no ``word_layer`` / ``hook_zh`` / ``note_zh``. The response models take no defaults
    (API.md §9 is the contract, and a default would hide a real omission in ``image_meta``), so without this the replay of a
    不熟悉 that was committed before the deploy and never acknowledged — the tablet asleep, the request in flight at the
    restart — fails response validation: a 500 the client treats as transient and re-sends for ever. Only missing keys are
    filled; a snapshot of today is answered as stored. The other direction has no fix here: a response stored by this build
    carries the three keys, and the build before it (``extra='forbid'``) answers its replay 500 until this one is back
    (docs/ops.md §4)."""
    item = data.get("study_item")
    image = item.get("image") if isinstance(item, dict) else None
    if isinstance(image, dict):
        for key, value in STORED_IMAGE_DEFAULTS.items():
            image.setdefault(key, value)
    return data


def _stored_response(conn: sqlite3.Connection, user_id: int, client_event_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT result_json FROM review_logs WHERE user_id = ? AND client_event_id = ?",
        (int(user_id), client_event_id),
    ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row[0]) if row[0] else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {"word_id": None, "verdict": None, "mine": None, "added_to_today": False, "study_item": None, "today": None}
    upgrade_stored(data)
    data["duplicate"] = True
    return data


# -------------------------------------------------------------------------------------------- verdicts
def apply_verdict(
    conn: sqlite3.Connection,
    user_id: int,
    word_id: int,
    verdict: str,
    *,
    client_event_id: str,
    context: str | None,
    push_item_id: int | None,
    now: datetime | str | None,
    tz: str,
    cfg: Any = None,
) -> dict[str, Any]:
    """API.md 32 ``ScreenResponse`` for a 认识 / 不熟悉 / 跳过 verdict (筛词 page, onboarding, or a 推荐词 inside a batch).

    ``context`` defaults to ``screen_page``; in-batch calls (WP4's ``grade_item``) pass ``today``/``extra`` and the
    ``push_item_id`` of the ``kind='screen'`` row, whose ``result``/``graded_at``/``user_word_id`` this function writes
    (a screen verdict is always final, DESIGN §7). A duplicate ``client_event_id`` returns the stored response with
    ``duplicate:true``.
    """
    if verdict not in VERDICTS:
        raise ApiError("validation_error", details={"fields": {"verdict": "unknown verdict"}})
    ctx = context or "screen_page"
    if ctx not in SCREEN_CONTEXTS:
        raise ApiError("validation_error", details={"fields": {"context": "unknown context"}})
    now_dt, now_s = bank.coerce_now(now)
    stored = _stored_response(conn, user_id, client_event_id)
    if stored is not None:
        return stored

    with db.maybe_tx(conn):
        word = words.word_row(conn, int(word_id))
        if word is None:
            raise ApiError("word_not_found")
        word, _ = words.follow_merge(conn, word)
        wid = int(word["id"])
        item = bank.push_item_row(conn, push_item_id)
        if item is not None and str(item["kind"]) != "screen":
            raise ApiError("invalid_transition", details={"from": item["kind"], "action": verdict})
        origin = bank.origin_for_context(ctx)
        today = bank.local_date_str(now_dt, tz)
        response: dict[str, Any] = {"word_id": wid, "verdict": verdict, "mine": None, "added_to_today": False, "study_item": None, "today": None, "duplicate": False}

        if verdict == "skip":
            if item is not None:
                conn.execute("UPDATE push_items SET skip_count = skip_count + 1 WHERE id = ?", (item["id"],))
            response["mine"] = words.my_user_word(conn, wid, user_id)
            bank.write_log(
                conn,
                user_id=int(user_id),
                word_id=wid,
                action="skip",
                context=ctx,
                local_date=today,
                now=now_s,
                batch_id=None if item is None else int(item["batch_id"]),
                push_item_id=None if item is None else int(item["id"]),
                client_event_id=client_event_id,
                prev_state=None if response["mine"] is None else response["mine"]["state"],
                new_state=None if response["mine"] is None else response["mine"]["state"],
                result_json=response,
            )
            return response

        r = bank.apply_action(
            conn,
            user_id,
            wid,
            verdict,
            origin=origin,
            context=ctx,
            now=now_dt,
            tz=tz,
            batch_id=None if item is None else int(item["batch_id"]),
            push_item_id=None if item is None else int(item["id"]),
            client_event_id=client_event_id,
        )
        response["mine"] = r.mine
        if item is not None:
            conn.execute(
                "UPDATE push_items SET result = ?, graded_at = ?, user_word_id = COALESCE(?, user_word_id) WHERE id = ?",
                (verdict, now_s, r.user_word_id, item["id"]),
            )
        # the study row always lands in TODAY's batch (batches.append_to_today), so room and duplicates are checked there —
        # the in-batch item itself may belong to yesterday's still-gradable batch (继续昨天的学习)
        today_batch = bank.today_batch(conn, user_id, today)
        if verdict == "unfamiliar" and r.status in ("added", "readded") and word.get("is_valid_english") == 1:
            if today_batch is not None and not has_study_row(conn, int(today_batch["id"]), wid):
                settings = bank.user_settings_row(conn, user_id)
                if new_quota_room(conn, int(today_batch["id"]), int(settings["daily_new_count"])):
                    new_item_id = bank._append_to_today(conn, user_id, wid, "new", now_s)
                    if new_item_id is not None:
                        response["added_to_today"] = True
                        response["study_item"] = study_item_dict(conn, user_id, new_item_id, now=now_s, cfg=cfg)
        if today_batch is not None:
            response["today"] = today_counts_for(conn, user_id, today_batch, now=now_s, cfg=cfg)
        if r.log_id is not None:
            conn.execute("UPDATE review_logs SET result_json = ? WHERE id = ?", (json.dumps(response, ensure_ascii=False), r.log_id))
        return response


__all__ = ["apply_verdict", "has_study_row", "new_quota_room", "screen_next", "study_item_dict", "today_counts_for", "upgrade_stored"]
