"""``/api/auth/wechat/*`` — API.md §3.3 endpoints 112–116 (slice 2-A, docs/AUTH_SIGNUP_DESIGN.md §5.3): the WeChat mini-program login
bridge — ticket + 小程序码 + 6-digit pairing code on the web, scan / confirm in the mini program, the web poll becomes the session (login) or
the binding (bind). The mechanics (hashes, cookie, pairing code, ``mp_token``, the ip / UA summaries, the QR cache) live in
``wd.wechat_bridge``; the account rules shared with QQ / Apple in ``wd.third_party``; the provider adapter in ``wd.delivery.wechat``
(``app.state.wechat``, None while the bridge is off → 409 ``provider_unconfigured`` on every route here).

* ``POST /api/auth/wechat/ticket`` (112, ``–`` login / ``U`` bind — a child → 403 ``guardian_required`` via ``deps.require_not_child``):
  ``WechatTicketRequest`` → 201 ``WechatTicket`` + ``Set-Cookie wd_wxt`` (``wechat_bridge.POLL_COOKIE``: HttpOnly, SameSite=Lax, ``Secure``
  like the session cookie, ``Path=/api/auth/wechat/ticket``, Max-Age 180); ``wx_ticket:ip`` 30/min and 300/h; a given ``invite_code`` is
  validated read-only (``security.invite_valid``, 403 ``invalid_invite``) and consumed at the confirmation; ``closed`` mode still issues
  login tickets (an existing binding may sign in; a NEW account is refused at 116); ``kind='login'`` with a session is allowed.
* ``GET /api/auth/wechat/ticket/{ticket}`` (113, the poll cookie): 200 ``WechatTicketStatus`` (201 when the confirmation created the
  account); 404 unless the row exists, ``poll_hash`` matches and the row is not consumed; a pending / scanned ticket past ``expires_at``
  → ``{status:'expired'}``; a confirmed / cancelled result is delivered until ``expires_at`` + ``wechat_bridge.CONFIRM_GRACE_S`` (60 s) —
  later the row is consumed unseen and the answer is ``{status:'expired'}`` (a captured ticket + cookie never mints a session a day later);
  a confirmed login ticket issues the session in ONE transaction (``security.gc_sessions`` / the browser's previous ``wd_session`` deleted,
  like the OAuth finish / ``create_session`` / ``last_login_at`` of the user and the identity / status → consumed) and clears the poll
  cookie; a login account disabled between the confirmation and the poll → the row is consumed and committed FIRST, then 403
  ``account_disabled`` (the SPA stops polling; the next poll is a 404); a confirmed bind ticket answers the bound account (``settings``
  null, ``created`` false); ``cancelled`` is reported once and consumed too. ``wx_poll:ip`` 1200/min (113 alone).
* ``GET /api/auth/wechat/ticket/{ticket}/qr`` (114): the 小程序码 PNG (``WechatClient.qr_png``, ``wechat_bridge.QrCache`` on
  ``app.state.wechat_qr_cache``, ``Cache-Control: private, max-age=180`` — the ``/api`` middleware's ``no-store`` wins today); 404 under the
  113 rules (and for an expired ticket); 502 ``provider_error`` when WeChat fails — the SPA shows the pairing code alone. No throttle of
  its own: one picture per ticket, bounded by 112's windows and served from the cache (a 429 here would hide the picture for good).
* ``POST /api/auth/wechat/scan`` (115, the mini program): ``WechatScanRequest`` → ``WechatScanInfo`` — ``wx_scan:ip`` 600/min (a flood
  brake only: behind the mainland relay every mini-program request shares the relay's IP) → provider check → ``code2session``
  (``WechatError('invalid_code')`` → 400 ``validation_error`` ``fields.js_code`` 「微信登录凭证无效，请重试」, other failures → 502) →
  ``wx_scan:openid`` 10/min (the brute-force brake, per WeChat user) → the live ticket by ``ticket_hash`` or ``pair_hash`` (404 otherwise;
  ``scanned`` by ANOTHER openid → 409 ``invalid_transition`` ``reason:'scanned_elsewhere'``, the same openid may re-scan) → status
  ``scanned``.
* ``POST /api/auth/wechat/confirm`` (116, the mini program): ``WechatConfirmRequest`` → ``WechatConfirmResult`` — ``wx_confirm:ip``
  600/min (the relay's shared IP again) → the rows named by ``ticket`` (the 26-char scene, or the 6-digit pairing code the scan used — a
  mini program that paired by code never sees the scene; the hash stays on the row whatever its status, so a finished ticket is still
  found and a second confirmation answers 409 ``wrong_state`` on both paths; several rows may share a re-drawn code and the one the
  ``mp_token`` verifies for is taken) → 404 when none → ``wx_confirm:openid`` 20/min on the newest scanned row's openid (counted before the
  token check — the brute-force brake, per WeChat user) → ``wechat_bridge.mp_token_verify`` (401 ``invalid_identity_token``) → the row
  must be unexpired (404) and ``scanned`` (409 ``invalid_transition`` ``reason:'wrong_state'``); ``accept=false`` → ``cancelled``;
  ``accept=true`` → ``security.unusable_password_hash()`` BEFORE the transaction when a login ticket's openid has no identity, then
  ``third_party.third_party_login_or_bind`` (409 ``identity_taken`` carries the provider wording 「该微信已绑定其他账号」,
  ``third_party.IDENTITY_TAKEN_ZH``) and status ``confirmed``. The mini program never receives a session.

Log events: ``wx_ticket_created`` (kind, ids), ``wx_scanned`` (ticket id, kind), ``wx_confirmed`` / ``wx_cancelled`` (ticket id, kind,
created_account), ``wx_login`` (user_id, created_account) / ``wx_bound``, ``wx_result_expired`` (a result nobody polled within the grace),
``wx_login_refused`` (the account disabled before the poll) — never an openid, a ticket, a code or a token.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from .. import db, security, third_party, wechat_bridge as bridge
from ..clock import parse_iso, to_iso
from ..config import Settings
from ..delivery.wechat import WechatClient, WechatError
from ..deps import SESSION_COOKIE, client_ip, current_user, get_db, hash_token, require_not_child
from ..errors import ApiError
from ..schemas import WechatConfirmRequest, WechatConfirmResult, WechatScanInfo, WechatScanRequest, WechatTicket, WechatTicketRequest, WechatTicketStatus
from .auth import _auth_payload, _issue_session

log = logging.getLogger("wd.routers.auth_wechat")

router = APIRouter()

JS_CODE_INVALID_ZH = "微信登录凭证无效，请重试"  # 115: WeChat refused the js_code (40029 / 40163 / 40226) → details.fields.js_code
MINUTE_S, HOUR_S = 60, 3600
PAIRING_CODE_RE = re.compile(r"^[0-9]{6}$")  # 116 `ticket` may be the pairing code the scan used instead of the scene
PAIR_CANDIDATES = 8  # 116 by pairing code: how many rows sharing the hash are considered (a finished ticket's code re-drawn by live ones)


# -------------------------------------------------------------------------------------------- helpers
def _wechat(request: Request) -> WechatClient:
    """``app.state.wechat`` — None while the bridge is off (409 ``provider_unconfigured``, every route of this module)."""
    client = getattr(request.app.state, "wechat", None)
    if client is None:
        raise ApiError("provider_unconfigured")
    return client


def _qr_cache(request: Request) -> bridge.QrCache:
    cache = getattr(request.app.state, "wechat_qr_cache", None)
    if cache is None:
        cache = bridge.QrCache()
        request.app.state.wechat_qr_cache = cache
    return cache


def _set_poll_cookie(request: Request, response: Response, secret: str, cfg: Settings) -> None:
    response.set_cookie(
        key=bridge.POLL_COOKIE,
        value=secret,
        max_age=bridge.TICKET_TTL_S,
        path=bridge.POLL_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=security.cookie_secure(request, cfg),
    )


def _clear_poll_cookie(request: Request, response: Response, cfg: Settings) -> None:
    response.delete_cookie(key=bridge.POLL_COOKIE, path=bridge.POLL_COOKIE_PATH, httponly=True, samesite="lax", secure=security.cookie_secure(request, cfg))


def _poll_row(request: Request, conn: sqlite3.Connection, ticket: str) -> dict[str, Any]:
    """The 113 / 114 lookup: the row by ``ticket_hash`` whose ``poll_hash`` matches the ``wd_wxt`` cookie and that is not consumed — 404
    ``not_found`` otherwise, identical whether the ticket never existed, was consumed or the cookie is wrong (no existence leak)."""
    secret = request.cookies.get(bridge.POLL_COOKIE)
    if not secret or not bridge.TICKET_RE.match(ticket):
        raise ApiError("not_found")
    row = security.row_dict(conn.execute("SELECT * FROM wechat_tickets WHERE ticket_hash = ?", (bridge.ticket_hash(ticket),)).fetchone())
    if row is None or row["poll_hash"] != bridge.poll_hash(secret) or row["status"] == "consumed":
        raise ApiError("not_found")
    return row


def _expired(row: dict[str, Any], now_iso: str) -> bool:
    return str(row["expires_at"]) <= now_iso


def _past_grace(row: dict[str, Any], now: datetime) -> bool:
    """True once ``expires_at`` + ``CONFIRM_GRACE_S`` has passed — a confirmed / cancelled result the poll (113) no longer delivers."""
    return parse_iso(str(row["expires_at"])) + timedelta(seconds=bridge.CONFIRM_GRACE_S) <= now


def _seconds_left(row: dict[str, Any], now: datetime) -> int:
    return max(0, int((parse_iso(str(row["expires_at"])) - now).total_seconds()))


def _consume(conn: sqlite3.Connection, row: dict[str, Any], now_iso: str, *, from_status: str) -> None:
    """status → consumed inside the caller's transaction; a concurrent poll that got there first makes this one a 404 (the result was
    delivered exactly once)."""
    updated = conn.execute(
        "UPDATE wechat_tickets SET status = 'consumed', consumed_at = ? WHERE id = ? AND status = ?",
        (now_iso, row["id"], from_status),
    ).rowcount
    if updated != 1:
        raise ApiError("not_found")


def _status(status: str, *, user: dict[str, Any] | None = None, settings: dict[str, Any] | None = None, created: bool | None = None) -> dict[str, Any]:
    return {"status": status, "user": user, "settings": settings, "created": created}


def _confirm_candidates(conn: sqlite3.Connection, cfg: Settings, ticket: str) -> list[dict[str, Any]]:
    """The 116 lookup, newest first: by ``ticket_hash`` for the 26-char scene (one row), by ``pair_hash`` for the 6-digit pairing code the
    scan used — whatever the rows' status: the hash stays on a row until the GC deletes it, so a second confirmation finds the finished
    ticket (409 ``wrong_state``) on both paths, and a code a finished ticket still holds may have been re-drawn by a live one (up to
    :data:`PAIR_CANDIDATES` rows; the caller takes the one the ``mp_token`` verifies for). Anything else finds nothing."""
    value = ticket.strip()
    if bridge.TICKET_RE.match(value):
        row = security.row_dict(conn.execute("SELECT * FROM wechat_tickets WHERE ticket_hash = ?", (bridge.ticket_hash(value),)).fetchone())
        return [row] if row is not None else []
    if PAIRING_CODE_RE.match(value):
        cur = conn.execute("SELECT * FROM wechat_tickets WHERE pair_hash = ? ORDER BY id DESC LIMIT ?", (bridge.pair_hash(cfg, value), PAIR_CANDIDATES))
        return [r for r in (security.row_dict(x) for x in cur.fetchall()) if r is not None]
    return []


# ------------------------------------------------------------------------------------------------- 112
@router.post("/api/auth/wechat/ticket", status_code=201, response_model=WechatTicket)
def create_ticket(body: WechatTicketRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    security.rate_limit(conn, f"wx_ticket:ip:{ip}:m", limit=bridge.TICKET_IP_MINUTE, window_s=MINUTE_S, now=now)
    security.rate_limit(conn, f"wx_ticket:ip:{ip}:h", limit=bridge.TICKET_IP_HOUR, window_s=HOUR_S, now=now)
    _wechat(request)
    bind_user_id: int | None = None
    if body.kind == "bind":
        me = require_not_child(current_user(request, conn))  # 401 without a session, 403 guardian_required for a child
        bind_user_id = int(me["id"])
    invite_code: str | None = None
    if body.kind == "login" and body.invite_code:
        # read-only here (the confirmation consumes it, 116): a dead code is refused before the learner opens WeChat
        if not security.invite_valid(conn, body.invite_code, now):
            raise ApiError("invalid_invite")
        invite_code = security.normalise_invite_code(body.invite_code)
    ticket = bridge.new_ticket()
    poll_secret = bridge.new_poll_secret()
    user_agent = (request.headers.get("user-agent") or "")[: bridge.WEB_UA_MAX] or None
    with db.tx(conn):
        pairing_code, pair_hash = bridge.unique_pairing_code(conn, cfg, now)  # inside the lock: two concurrent tickets cannot share a code
        cur = conn.execute(
            "INSERT INTO wechat_tickets(ticket_hash, pair_hash, poll_hash, kind, status, bind_user_id, invite_code, web_ip, web_ua, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)",
            (bridge.ticket_hash(ticket), pair_hash, bridge.poll_hash(poll_secret), body.kind, bind_user_id, invite_code, ip, user_agent, now_iso, to_iso(now + timedelta(seconds=bridge.TICKET_TTL_S))),
        )
        ticket_id = int(cur.lastrowid)
    _set_poll_cookie(request, response, poll_secret, cfg)
    log.info("wechat ticket created", extra={"event": "wx_ticket_created", "kind": body.kind, "ticket_id": ticket_id, "user_id": bind_user_id})
    return {"ticket": ticket, "pairing_code": pairing_code, "expires_in_s": bridge.TICKET_TTL_S, "qr_url": f"/api/auth/wechat/ticket/{ticket}/qr"}


# ------------------------------------------------------------------------------------------------- 113
@router.get("/api/auth/wechat/ticket/{ticket}", response_model=WechatTicketStatus)
def poll_ticket(ticket: str, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    security.rate_limit(conn, f"wx_poll:ip:{ip}", limit=bridge.POLL_IP_MINUTE, window_s=MINUTE_S, now=now)
    _wechat(request)
    row = _poll_row(request, conn, ticket)
    status = str(row["status"])
    if status in bridge.LIVE_STATUSES:
        if _expired(row, now_iso):
            return _status("expired")  # the SPA shows 刷新; the row stays for the GC (nothing to consume)
        return _status(status)
    if _past_grace(row, now):
        # confirmed / cancelled but nobody polled within expires_at + 60 s: the result is void — consumed unseen, never deliverable later
        with db.tx(conn):
            _consume(conn, row, now_iso, from_status=status)
        log.info("wechat ticket result expired undelivered", extra={"event": "wx_result_expired", "ticket_id": row["id"], "kind": row["kind"], "status": status})
        return _status("expired")
    if status == "cancelled":
        with db.tx(conn):
            _consume(conn, row, now_iso, from_status="cancelled")
        _clear_poll_cookie(request, response, cfg)
        log.info("wechat ticket cancellation delivered", extra={"event": "wx_cancel_delivered", "ticket_id": row["id"], "kind": row["kind"]})
        return _status("cancelled")
    # confirmed — within the ticket's lifetime by the 116 rule; a poll that lands a moment after expires_at (≤ 60 s) still gets its result
    if row["kind"] == "bind":
        with db.tx(conn):
            _consume(conn, row, now_iso, from_status="confirmed")
        _clear_poll_cookie(request, response, cfg)
        binder = security.load_user(conn, int(row["bind_user_id"])) if row["bind_user_id"] is not None else None
        if binder is None:  # pragma: no cover - bind_user_id cascades with its user, so the row would be gone
            raise ApiError("not_found")
        log.info("wechat identity bound", extra={"event": "wx_bound", "ticket_id": row["id"], "user_id": int(binder["id"])})
        return _status("confirmed", user=security.user_dto_for(conn, binder, now=now), settings=None, created=False)
    if row["user_id"] is None:  # the account vanished between the confirmation and this poll (ON DELETE SET NULL)
        with db.tx(conn):
            _consume(conn, row, now_iso, from_status="confirmed")
        _clear_poll_cookie(request, response, cfg)
        raise ApiError("not_found")
    user_id = int(row["user_id"])
    created = bool(int(row["created_account"]))
    previous = request.cookies.get(SESSION_COOKIE)
    with db.tx(conn):
        _consume(conn, row, now_iso, from_status="confirmed")
        user = security.load_user(conn, user_id)
        active = user is not None and bool(int(user["is_active"]))
        if active:
            security.gc_sessions(conn, now_iso)
            if previous:  # this browser's own session (a login ticket from a signed-in tab) is replaced, not left behind — the 122 rule
                security.delete_session(conn, hash_token(previous))
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, user_id))
            conn.execute("UPDATE identities SET last_login_at = ? WHERE user_id = ? AND provider = 'wechat_mini' AND disputed_at IS NULL", (now_iso, user_id))
            _issue_session(request, response, conn, user_id, now)  # the learner's / guardian's WD_SESSION_DAYS, a self session
    if user is None:  # pragma: no cover - read a moment ago under the same lock as the confirmation
        raise ApiError("not_found")
    if not active:
        # disabled between the confirmation and the poll: the consume is COMMITTED first, so the next poll is a 404 and the result can
        # never be delivered later; no session was issued
        log.info("wechat login refused: account disabled", extra={"event": "wx_login_refused", "ticket_id": row["id"], "user_id": user_id})
        raise ApiError("account_disabled")
    _clear_poll_cookie(request, response, cfg)
    if created:
        response.status_code = 201
    # `created` is a reserved LogRecord attribute: never a log extra
    log.info("wechat login", extra={"event": "wx_login", "ticket_id": row["id"], "user_id": user_id, "created_account": created})
    payload = _auth_payload(conn, user_id, now=now)
    return _status("confirmed", user=payload["user"], settings=payload["settings"], created=created)


# ------------------------------------------------------------------------------------------------- 114
@router.get("/api/auth/wechat/ticket/{ticket}/qr")
def ticket_qr(ticket: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    # no window of its own: one picture per ticket (112's windows bound it) and the cache answers the browser's retries — a 429 here
    # would hide the picture for the rest of the ticket's life
    client = _wechat(request)
    row = _poll_row(request, conn, ticket)
    if _expired(row, now_iso):
        raise ApiError("not_found")
    cache = _qr_cache(request)
    th = str(row["ticket_hash"])
    png = cache.get(th, now_iso)
    if png is None:
        try:
            png = client.qr_png(ticket, page=cfg.wechat_page, env_version=cfg.wechat_env)
        except WechatError as e:
            log.warning("wechat 小程序码 unavailable: %s (errcode %s)", e.kind, e.code, extra={"event": "wx_qr_failed", "ticket_id": row["id"], "kind": e.kind, "errcode": e.code})
            raise ApiError("provider_error") from e
        cache.put(th, png, str(row["expires_at"]), now_iso)
    return Response(content=png, media_type="image/png", headers={"Cache-Control": bridge.QR_CACHE_CONTROL})


# ------------------------------------------------------------------------------------------------- 115
@router.post("/api/auth/wechat/scan", response_model=WechatScanInfo)
def scan(body: WechatScanRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    security.rate_limit(conn, f"wx_scan:ip:{ip}", limit=bridge.SCAN_IP_MINUTE, window_s=MINUTE_S, now=now)
    client = _wechat(request)
    try:
        openid = client.code2session(body.js_code)
    except WechatError as e:
        if e.kind == "invalid_code":
            raise ApiError("validation_error", message_zh=JS_CODE_INVALID_ZH, details={"fields": {"js_code": JS_CODE_INVALID_ZH}}) from e
        log.warning("wechat code2session unavailable: %s (errcode %s)", e.kind, e.code, extra={"event": "wx_scan_failed", "kind": e.kind, "errcode": e.code})
        raise ApiError("provider_error") from e
    security.rate_limit(conn, bridge.openid_key(openid), limit=bridge.SCAN_OPENID_MINUTE, window_s=MINUTE_S, now=now)
    if body.ticket is not None:
        where, key = "ticket_hash = ?", bridge.ticket_hash(body.ticket)
    else:
        where, key = "pair_hash = ?", bridge.pair_hash(cfg, str(body.pairing_code))
    with db.tx(conn):
        row = security.row_dict(
            conn.execute(f"SELECT * FROM wechat_tickets WHERE {where} AND status IN ('pending','scanned') AND expires_at > ?", (key, now_iso)).fetchone()
        )
        if row is None:
            raise ApiError("not_found")  # unknown, expired, consumed, confirmed or cancelled: the mini program says 二维码已过期
        if row["status"] == "scanned" and row["openid"] != openid:
            raise ApiError("invalid_transition", details={"reason": "scanned_elsewhere"})
        conn.execute("UPDATE wechat_tickets SET status = 'scanned', openid = ?, scanned_at = ? WHERE id = ?", (openid, now_iso, row["id"]))
    identity = security.identity_by_subject(conn, "wechat_mini", openid)
    bind_display_name: str | None = None
    if row["kind"] == "login":
        if identity is not None:
            account = "bound"
        elif cfg.registration_mode == "closed":
            account = "closed"
        else:
            account = "new"
    else:
        binder = security.load_user(conn, int(row["bind_user_id"])) if row["bind_user_id"] is not None else None
        if binder is None:  # pragma: no cover - the row cascades with its binder
            raise ApiError("not_found")
        bind_display_name = str(binder["display_name"] or binder["username"])
        if identity is None:
            account = "new"
        elif int(identity["user_id"]) == int(binder["id"]):
            account = "self"
        else:
            account = "other"
    exp_unix = int(now.timestamp()) + bridge.MP_TOKEN_TTL_S
    log.info("wechat ticket scanned", extra={"event": "wx_scanned", "ticket_id": row["id"], "kind": row["kind"], "account": account})
    return {
        "mp_token": bridge.mp_token_sign(cfg, ticket_id=int(row["id"]), openid=openid, exp_unix=exp_unix),
        "kind": row["kind"],
        "account": account,
        "bind_display_name": bind_display_name,
        "web_ip_masked": bridge.web_ip_masked(str(row["web_ip"] or "")),
        "web_ua_summary": bridge.web_ua_summary(row["web_ua"]),
        "created_at": row["created_at"],
        "expires_in_s": _seconds_left(row, now),
    }


# ------------------------------------------------------------------------------------------------- 116
@router.post("/api/auth/wechat/confirm", response_model=WechatConfirmResult)
def confirm(body: WechatConfirmRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    security.rate_limit(conn, f"wx_confirm:ip:{ip}", limit=bridge.CONFIRM_IP_MINUTE, window_s=MINUTE_S, now=now)  # a flood brake: the relay's one IP
    _wechat(request)
    candidates = _confirm_candidates(conn, cfg, body.ticket)
    if not candidates:
        raise ApiError("not_found")
    scanned = [r for r in candidates if r["openid"] is not None]
    if not scanned:
        raise ApiError("invalid_identity_token")  # nobody scanned this ticket yet: no proof can exist
    # the brute-force brake is per WeChat user: every attempt naming this scan counts against its openid, valid token or not
    security.rate_limit(conn, bridge.openid_key(str(scanned[0]["openid"]), scope="confirm"), limit=bridge.CONFIRM_OPENID_MINUTE, window_s=MINUTE_S, now=now)
    row = next((r for r in scanned if bridge.mp_token_verify(cfg, body.mp_token, ticket_id=int(r["id"]), openid=str(r["openid"]), now=now)), None)
    if row is None:
        raise ApiError("invalid_identity_token")  # not this ticket's scan proof, or older than 5 minutes
    if _expired(row, now_iso):
        raise ApiError("not_found")
    if row["status"] != "scanned":
        raise ApiError("invalid_transition", details={"reason": "wrong_state"})  # confirmed / cancelled / consumed: the same answer on both paths
    openid = str(row["openid"])
    if not body.accept:
        with db.tx(conn):
            updated = conn.execute("UPDATE wechat_tickets SET status = 'cancelled' WHERE id = ? AND status = 'scanned' AND openid = ?", (row["id"], openid)).rowcount
            if updated != 1:
                raise ApiError("invalid_transition", details={"reason": "wrong_state"})
        log.info("wechat ticket cancelled in the mini program", extra={"event": "wx_cancelled", "ticket_id": row["id"], "kind": row["kind"]})
        return {"status": "cancelled", "created": False}
    kind = str(row["kind"])
    # bcrypt work before the write lock — only a login ticket whose openid has no account needs the unusable hash
    unusable = security.unusable_password_hash() if kind == "login" and security.identity_by_subject(conn, "wechat_mini", openid) is None else None
    try:
        with db.tx(conn):
            fresh = security.row_dict(conn.execute("SELECT * FROM wechat_tickets WHERE id = ?", (row["id"],)).fetchone())
            if fresh is None or _expired(fresh, now_iso):
                raise ApiError("not_found")
            if fresh["status"] != "scanned" or fresh["openid"] != openid:
                raise ApiError("invalid_transition", details={"reason": "wrong_state"})  # confirmed / cancelled meanwhile, or re-scanned by another openid
            user_id, created = third_party.third_party_login_or_bind(
                conn,
                cfg,
                provider="wechat_mini",
                subject=openid,
                kind=kind,
                bind_user_id=int(fresh["bind_user_id"]) if fresh["bind_user_id"] is not None else None,
                invite_code=fresh["invite_code"],
                password_hash_factory=lambda: unusable or security.unusable_password_hash(),
                now=now,
            )
            conn.execute(
                "UPDATE wechat_tickets SET status = 'confirmed', confirmed_at = ?, user_id = ?, created_account = ? WHERE id = ?",
                (now_iso, user_id, 1 if created else 0, row["id"]),
            )
    except sqlite3.IntegrityError as e:  # a racing confirmation of the same openid (the helper converts the ones it sees)
        raise third_party.identity_taken_error("wechat_mini") from e
    log.info("wechat ticket confirmed", extra={"event": "wx_confirmed", "ticket_id": row["id"], "kind": kind, "created_account": created, "user_id": user_id})
    return {"status": "confirmed", "created": created}
