"""The site-wide SMS budget (docs/AUTH_SIGNUP_DESIGN.md §5.4 item 7; API.md 80 / 85 / 90, 54 ``AdminOverview.sms``; DEPLOY §4
``WD_SMS_DAILY_CAP`` / ``WD_SMS_HOURLY_CAP``).

Counters are kv rows — ``sms.sent.<YYYY-MM-DD>`` (the ``WD_TZ`` day) and ``sms.sent.<YYYY-MM-DDTHH>`` (the UTC hour) — because
``auth_throttle`` windows are reaped after a day and the day counter must also feed the admin overview; the hourly GC deletes
counters older than two days. :func:`reserve_sms` is called INSIDE the transaction that writes the ``login_codes`` row, so a send
that never gets its row never counts, and two concurrent requests respect the caps together; it counts send REQUESTS, not provider
receipts (a refused request still spent the attempt — the design's 计发送请求). The hour cap and the day cap answer 503
``sms_budget_exhausted`` with ``details.retry_after_s`` (the next hour / the next ``WD_TZ`` day); a send for a NEW account
(``purpose = 'login'`` to a number with no live identity) additionally stops at :data:`REGISTRATION_SHARE` of the day cap, so the
last 30 % is kept for people who already have an account (``registration_open`` in the overview). Which cap refused is logged
(event ``sms_budget_refused``, ``scope`` hour / day / registration) but NOT returned: a ``registration`` scope in the public answer
would spell out that the number has no account. After the transaction committed,
:func:`sms_events` writes ``system_events`` ``sms_budget_50`` / ``_80`` / ``_100`` once per day (``budget.event_once``) and tells
the admins' webhooks at 80 % and 100 % through :func:`wd.notify.notify_admins`.
"""

from __future__ import annotations

import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from . import db
from .ai import budget
from .clock import local_date, parse_iso, to_iso
from .config import Settings
from .errors import ApiError
from .notify import notify_admins

log = logging.getLogger("wd.sms_budget")

KV_PREFIX = "sms.sent."
REGISTRATION_SHARE = 0.7  # new-account sends stop here; logins through an existing identity go on to 100 %
THRESHOLDS: tuple[int, ...] = (50, 80, 100)
EVENT_KINDS: dict[int, str] = {50: "sms_budget_50", 80: "sms_budget_80", 100: "sms_budget_100"}
NOTIFY_FROM_PERCENT = 80
NOTIFY_TITLE_ZH = "短信额度提醒"


def day_key(now: datetime, tz: str) -> str:
    """``sms.sent.<YYYY-MM-DD>`` of the ``tz`` local day containing ``now``."""
    return f"{KV_PREFIX}{local_date(now, tz).isoformat()}"


def hour_key(now: datetime) -> str:
    """``sms.sent.<YYYY-MM-DDTHH>`` of the UTC hour containing ``now``."""
    return f"{KV_PREFIX}{now.astimezone(timezone.utc).strftime('%Y-%m-%dT%H')}"


def _count(conn: sqlite3.Connection, key: str) -> int:
    try:
        return int(db.kv_get(conn, key, "0") or 0)
    except (TypeError, ValueError):
        return 0


def seconds_to_next_hour(now: datetime) -> int:
    now = now.astimezone(timezone.utc)
    nxt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(1, int(math.ceil((nxt - now).total_seconds())))


def seconds_to_next_day(now: datetime, tz: str) -> int:
    _start, next_start = budget.day_window(to_iso(now), tz)
    return max(1, int(math.ceil((parse_iso(next_start) - now.astimezone(timezone.utc)).total_seconds())))


def registration_open(sent_today: int, daily_cap: int) -> bool:
    return daily_cap > 0 and sent_today < REGISTRATION_SHARE * daily_cap


def sms_usage(conn: sqlite3.Connection, cfg: Settings, now: datetime) -> dict[str, Any]:
    """API.md 54 ``AdminOverview.sms``: the counters against the caps and whether new-account sends are still open."""
    sent_today = _count(conn, day_key(now, cfg.tz))
    return {
        "provider": cfg.sms_provider,
        "sent_today": sent_today,
        "daily_cap": int(cfg.sms_daily_cap),
        "sent_hour": _count(conn, hour_key(now)),
        "hourly_cap": int(cfg.sms_hourly_cap),
        "registration_open": registration_open(sent_today, int(cfg.sms_daily_cap)),
    }


def reserve_sms(conn: sqlite3.Connection, cfg: Settings, now: datetime, *, new_account: bool) -> None:
    """Count one phone-code send against the hour and day caps, or raise 503 ``sms_budget_exhausted`` (``details.retry_after_s``).

    Call it inside the transaction that writes the code row (``db.maybe_tx`` joins it). ``new_account`` = a ``login`` send to a
    number without a live identity: refused from :data:`REGISTRATION_SHARE` of the day cap on. A cap of 0 is "already reached".
    """
    hk, dk = hour_key(now), day_key(now, cfg.tz)
    with db.maybe_tx(conn):
        sent_hour, sent_today = _count(conn, hk), _count(conn, dk)
        if sent_hour >= int(cfg.sms_hourly_cap):
            raise _exhausted("hour", seconds_to_next_hour(now), sent_hour=sent_hour, sent_today=sent_today)
        if sent_today >= int(cfg.sms_daily_cap):
            raise _exhausted("day", seconds_to_next_day(now, cfg.tz), sent_hour=sent_hour, sent_today=sent_today)
        if new_account and not registration_open(sent_today, int(cfg.sms_daily_cap)):
            raise _exhausted("registration", seconds_to_next_day(now, cfg.tz), sent_hour=sent_hour, sent_today=sent_today)
        now_s = to_iso(now)
        db.kv_set(conn, hk, str(sent_hour + 1), now=now_s)
        db.kv_set(conn, dk, str(sent_today + 1), now=now_s)


def _exhausted(scope: str, retry_after_s: int, *, sent_hour: int, sent_today: int) -> ApiError:
    """The 503 for a refused send: ``retry_after_s`` only in the answer — the scope stays in the log (a public ``registration`` would
    tell the caller the number has no account, AUTH_SIGNUP_DESIGN §5.6 invariant 8)."""
    log.info("sms send refused by the %s cap (%d this hour, %d today)", scope, sent_hour, sent_today, extra={"event": "sms_budget_refused", "scope": scope})
    return ApiError("sms_budget_exhausted", details={"retry_after_s": int(retry_after_s)})


def _body_zh(percent: int, usage: dict[str, Any]) -> str:
    head = f"今日短信验证码已发送 {usage['sent_today']} / {usage['daily_cap']} 条（{percent}%），本小时 {usage['sent_hour']} / {usage['hourly_cap']} 条。"
    if percent >= 100:
        return head + "手机验证码已停发，次日 0 点恢复；学习者可改用邮箱验证码或密码登录。"
    if percent >= 80:
        return head + "新手机号的注册验证码已暂停（超过 70%），已有账号仍可登录；到 100% 后手机验证码停发。"
    return head + "超过 70% 后新手机号的注册验证码将暂停。"


def sms_events(conn: sqlite3.Connection, cfg: Settings, now: datetime) -> list[str]:
    """After the send transaction committed: write ``sms_budget_50`` / ``_80`` / ``_100`` once per ``WD_TZ`` day for every threshold
    the day counter has crossed, and notify the admins at 80 % and 100 % (:func:`notify_admins`, 「短信额度提醒」). Returns the
    event kinds written now. Never raises."""
    written: list[str] = []
    try:
        cap = int(cfg.sms_daily_cap)
        if cap <= 0:
            return written
        usage = sms_usage(conn, cfg, now)
        percent = usage["sent_today"] * 100 / cap
        now_s = to_iso(now)
        day_start, _ = budget.day_window(now_s, cfg.tz)
        for threshold in THRESHOLDS:
            if percent < threshold:
                continue
            kind = EVENT_KINDS[threshold]
            detail = {"percent": threshold, "sent_today": usage["sent_today"], "daily_cap": cap, "sent_hour": usage["sent_hour"], "hourly_cap": usage["hourly_cap"], "registration_open": usage["registration_open"]}
            if budget.event_once(conn, kind, day_start, detail, now=now_s):
                written.append(kind)
                log.warning("sms budget at %d%%: %d / %d today", threshold, usage["sent_today"], cap, extra={"event": kind})
                if threshold >= NOTIFY_FROM_PERCENT:
                    notify_admins(conn, cfg, kind, NOTIFY_TITLE_ZH, _body_zh(threshold, usage), now=now_s)
    except Exception:  # noqa: BLE001 — bookkeeping after the send must never fail the request
        log.warning("sms budget events failed", exc_info=True, extra={"event": "sms_budget_events_failed"})
    return written


__all__ = [
    "EVENT_KINDS",
    "KV_PREFIX",
    "NOTIFY_TITLE_ZH",
    "REGISTRATION_SHARE",
    "THRESHOLDS",
    "day_key",
    "hour_key",
    "registration_open",
    "reserve_sms",
    "seconds_to_next_day",
    "seconds_to_next_hour",
    "sms_events",
    "sms_usage",
]
