"""Admin notifications over the admins' own webhooks — the general form of ``ai/failover.notify`` (docs/AUTH_SIGNUP_DESIGN.md §5.4
item 7: the SMS budget at 80 % / 100 %; anything operational that is not AI-specific).

:func:`notify_admins` posts ``title_zh`` / ``body_zh`` to every active admin with ``user_settings.webhook_enabled = 1`` and a URL
(:data:`ADMIN_WEBHOOKS_SQL`, the same rows ``failover.notify`` reads), at most once per ``kind`` per ``dedupe_s`` (kv
``notify.<kind>.last_at``, claimed BEFORE sending so a failing endpoint is not retried every minute). It is skipped entirely under
``WD_SMOKE_MOCK_HTTP`` and inside an open transaction on ``conn`` (a 10-second webhook timeout per admin must never run under
``BEGIN IMMEDIATE`` — call it after the commit), and every exception is swallowed: a failed notification never changes the
outcome it reports. Requests go through ``delivery.webhook.safe_post`` (SSRF rules, DNS pin, 10 s); tests inject a client through
:data:`WEBHOOK_CLIENT_FACTORY`. ``ai/failover.notify`` keeps its own ``ai.notify.*`` keys and ``ai_`` payload types untouched.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Callable

import httpx

from . import db
from .clock import parse_iso, to_iso
from .config import Settings

log = logging.getLogger("wd.notify")

#: mirrors ``wd.ai.failover.ADMIN_WEBHOOKS_SQL`` (tests pin the equality) without importing the AI package into the auth routes
ADMIN_WEBHOOKS_SQL = (
    "SELECT s.webhook_url AS webhook_url, s.webhook_format AS webhook_format FROM users u JOIN user_settings s ON s.user_id = u.id "
    "WHERE u.role = 'admin' AND u.is_active = 1 AND s.webhook_enabled = 1 AND s.webhook_url IS NOT NULL AND s.webhook_url != '' ORDER BY u.id"
)
DEDUPE_S = 3600
KV_PREFIX = "notify."

#: test hook: a factory returning the ``httpx.Client`` the posts go through (None = ``delivery.webhook``'s own client)
WEBHOOK_CLIENT_FACTORY: Callable[[], httpx.Client] | None = None


def dedupe_key(kind: str) -> str:
    return f"{KV_PREFIX}{kind}.last_at"


def _within(last: str | None, window_s: int, now: str) -> bool:
    if not last:
        return False
    try:
        return parse_iso(last) + timedelta(seconds=window_s) > parse_iso(now)
    except (ValueError, TypeError):
        return False


def notify_admins(conn: sqlite3.Connection, cfg: Settings, kind: str, title_zh: str, body_zh: str, *, now: str | datetime, dedupe_s: int = DEDUPE_S) -> int:
    """Best effort: post ``kind`` to every admin webhook; returns the number of webhooks that accepted it (0 when skipped or deduped)."""
    now_s = to_iso(now) if isinstance(now, datetime) else str(now)
    sent = 0
    try:
        if bool(getattr(cfg, "smoke_mock_http", False)):
            return 0
        if conn.in_transaction:
            log.warning("admin notification %s skipped inside an open transaction", kind, extra={"event": "notify_skipped"})
            return 0
        rows = conn.execute(ADMIN_WEBHOOKS_SQL).fetchall()
        if not rows:
            return 0
        key = dedupe_key(kind)
        if _within(db.kv_get(conn, key), int(dedupe_s), now_s):
            return 0
        with db.maybe_tx(conn):
            db.kv_set(conn, key, now_s, now=now_s)
        from .delivery import webhook as webhook_mod  # lazy: the delivery package pulls in the job registry

        for row in rows:
            url = str(row["webhook_url"])
            fmt = str(row["webhook_format"] or "generic")
            if fmt not in webhook_mod.FORMATS:
                fmt = "generic"
            payload = webhook_mod.build_payload(fmt, title_zh, body_zh, url=None, date=now_s[:10], type_=kind)
            client = WEBHOOK_CLIENT_FACTORY() if WEBHOOK_CLIENT_FACTORY is not None else None
            try:
                status, error, _reason = webhook_mod.safe_post(url, payload, client=client, fmt=fmt)
            finally:
                if client is not None:
                    client.close()
            if error is None:
                sent += 1
                log.info("admin notification %s sent", kind, extra={"event": "notify_sent", "status": status})
            else:
                log.warning("admin notification %s failed: %s", kind, error, extra={"event": "notify_failed"})
    except Exception:  # noqa: BLE001 — best effort by contract
        log.warning("admin notification %s failed", kind, exc_info=True, extra={"event": "notify_failed"})
    return sent


__all__ = ["ADMIN_WEBHOOKS_SQL", "DEDUPE_S", "WEBHOOK_CLIENT_FACTORY", "dedupe_key", "notify_admins"]
