"""``/api/settings*`` — API.md endpoints 14–18, DESIGN §6.1 (WP2).

``PUT /api/settings`` merges the partial body into the stored row and validates the *merged* result
(``current_stage ∈ stages``, webhook URL policy, e-mail prerequisites), then recomputes ``next_push_at``.
``POST /api/settings/webhook/test`` calls WP4's ``delivery.webhook.send_test_webhook`` synchronously;
``POST /api/settings/email/test`` enqueues ``send_email {"user_id", "test": true}``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import zoneinfo
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from .. import db, security
from ..clock import to_iso
from ..delivery import webhook as webhook_delivery
from ..deps import current_user, get_db
from ..errors import ApiError
from ..jobs import queue
from ..schemas import EmailTestResponse
from ..schemas import Settings as SettingsDTO
from ..schemas import SettingsUpdateRequest, TimezonesResponse, WebhookTestResponse, index_to_stage, stage_to_index

log = logging.getLogger("wd.routers.settings")

router = APIRouter()

# API.md 16: curated 30 zones, Asia/Shanghai first
CURATED_TIMEZONES: tuple[str, ...] = (
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Taipei",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Asia/Kolkata",
    "Asia/Bangkok",
    "Asia/Jakarta",
    "Asia/Manila",
    "Asia/Kuala_Lumpur",
    "Asia/Dubai",
    "Asia/Karachi",
    "Australia/Sydney",
    "Australia/Perth",
    "Pacific/Auckland",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Moscow",
    "Europe/Istanbul",
    "Africa/Cairo",
    "Africa/Johannesburg",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Toronto",
    "America/Sao_Paulo",
)
_NOT_ZONES = frozenset({"Factory", "localtime"})

SCALAR_COLUMNS = ("timezone", "push_time", "daily_new_count", "daily_screen_count", "max_reviews", "zh_examples", "accent", "webhook_format")


def _field_error(field: str, message_zh: str) -> ApiError:
    return ApiError("validation_error", message_zh=message_zh, details={"fields": {field: message_zh}})


@router.get("/api/settings", response_model=SettingsDTO)
def get_settings(user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    return security.settings_dto(conn, int(user["id"]))


@router.put("/api/settings", response_model=SettingsDTO)
def update_settings(body: SettingsUpdateRequest, request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    # an explicit JSON null means "clear" only for the nullable webhook_url; on every other (NOT NULL) field it is "no change"
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "webhook_url"}
    with db.tx(conn):
        current = security.load_settings_row(conn, int(user["id"]))
        if current is None:  # pragma: no cover - created with the user
            raise ApiError("not_found")
        stages = list(changes["stages"]) if "stages" in changes else list(json.loads(current["stages_json"]))
        current_stage = changes.get("current_stage") or index_to_stage(int(current["current_stage"]))
        if current_stage not in stages:
            raise _field_error("current_stage", "主攻阶段必须包含在目标阶段中")

        webhook_enabled = bool(changes["webhook_enabled"]) if "webhook_enabled" in changes else bool(int(current["webhook_enabled"]))
        webhook_url = changes["webhook_url"] if "webhook_url" in changes else current["webhook_url"]
        if webhook_url is not None and not security.is_safe_https_url(webhook_url):
            raise _field_error("webhook_url", "Webhook 地址必须是 https 公网地址")
        if webhook_enabled and not webhook_url:
            raise ApiError("webhook_unconfigured")

        if changes.get("email_enabled"):
            if user["email_verified_at"] is None:
                raise ApiError("email_not_verified")
            if getattr(request.app.state, "mailer", None) is None:
                raise ApiError("smtp_unconfigured")

        timezone_ = changes.get("timezone") or current["timezone"]
        push_time = changes.get("push_time") or current["push_time"]
        assignments: dict[str, Any] = {key: changes[key] for key in SCALAR_COLUMNS if key in changes}
        for key in security.SETTINGS_BOOL_COLUMNS:
            if key in changes:
                assignments[key] = 1 if changes[key] else 0
        if "stages" in changes:
            assignments["stages_json"] = security.stages_json(stages)
        if "current_stage" in changes:
            assignments["current_stage"] = stage_to_index(current_stage)
        if "webhook_url" in changes:
            assignments["webhook_url"] = webhook_url
        assignments["next_push_at"] = security.next_push_iso(now, timezone_, push_time)
        assignments["updated_at"] = to_iso(now)
        sets = ", ".join(f"{k} = ?" for k in assignments)
        conn.execute(f"UPDATE user_settings SET {sets} WHERE user_id = ?", [*assignments.values(), user["id"]])
    log.info("settings updated", extra={"event": "settings_update", "user_id": user["id"], "fields": sorted(changes)})
    return security.settings_dto(conn, int(user["id"]))


@router.get("/api/settings/timezones", response_model=TimezonesResponse)
def timezones(all_zones: bool = Query(False, alias="all"), user: dict[str, Any] = Depends(current_user)):
    available = zoneinfo.available_timezones()
    if all_zones:
        rest = sorted(z for z in available if z not in _NOT_ZONES and z != CURATED_TIMEZONES[0])
        return {"items": [CURATED_TIMEZONES[0], *rest]}
    return {"items": [z for z in CURATED_TIMEZONES if z in available]}


@router.post("/api/settings/webhook/test", response_model=WebhookTestResponse)
def test_webhook(request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """API.md 17: one synchronous test send through WP4's ``delivery.webhook.send_test_webhook(settings_row)``."""
    now = request.app.state.clock.now_utc()
    row = security.load_settings_row(conn, int(user["id"]))
    if row is None or not int(row["webhook_enabled"]) or not row["webhook_url"]:
        raise ApiError("webhook_unconfigured")
    security.rate_limit(conn, f"webhook_test:user:{user['id']}", limit=security.TEST_SEND_LIMIT, window_s=security.TEST_SEND_WINDOW_S, now=now)
    result = webhook_delivery.send_test_webhook(row)
    return {"ok": bool(result.get("ok")), "http_status": result.get("http_status"), "error": result.get("error")}


@router.post("/api/settings/email/test", status_code=202, response_model=EmailTestResponse)
def test_email(request: Request, user: dict[str, Any] = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    now = request.app.state.clock.now_utc()
    if user["email_verified_at"] is None or not user["email"]:
        raise ApiError("email_not_verified")
    if getattr(request.app.state, "mailer", None) is None:
        raise ApiError("smtp_unconfigured")
    security.rate_limit(conn, f"email_test:user:{user['id']}", limit=security.TEST_SEND_LIMIT, window_s=security.TEST_SEND_WINDOW_S, now=now)
    queue.enqueue(conn, "send_email", {"user_id": int(user["id"]), "test": True}, dedupe_key=f"email:test:{user['id']}", priority=10, now=to_iso(now))
    return {"queued": True}
