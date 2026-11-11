"""``/api/auth/qq/*``, ``/api/auth/apple/*`` and ``/api/auth/oauth/finish`` — API.md §3.3 endpoints 118–122 (slice 2-A,
docs/AUTH_SIGNUP_DESIGN.md §5.3): QQ 互联 web OAuth and Sign in with Apple (web redirect flow, ``response_mode=form_post``). The
callbacks only VERIFY the provider and hand the verified subject to endpoint 122 as a one-time grant; 122 — on the SPA's origin, in
the browser that started the flow — performs the login or the bind.

* ``GET /api/auth/qq/start?kind=login|bind&invite_code=&next=`` (118): QQ off (``app.state.qq is None``) → 409 ``provider_unconfigured``;
  ``kind=bind`` needs a session (``deps.require_not_child``, a child → 403 ``guardian_required``); ``qq_start:ip`` 10/min; a browser
  secret is drawn (``oauth_state.new_browser_secret``) and set as the HttpOnly cookie ``wd_oauth`` (``SameSite=Lax``, ``Secure`` like
  the session cookie, ``Path=/api/auth``, Max-Age 600) on the 302 to ``QQClient.authorize_url(oauth_state.sign(...))``; the state
  carries ``{kind, uid (bind), invite (login, optional), next, bh = sha256(secret)}``;
* ``GET /api/auth/qq/callback?code=&state=&msg=&usercancel=`` (119): ``qq_callback:ip`` 600/min (a flood brake — the relay collapses IPs); ``usercancel`` / no code → 302 ``/login``
  or ``/settings``; ``oauth_state.verify`` → ``QQClient.exchange`` → ``QQClient.openid`` (an unusable code → ``invalid_identity_token``,
  other failures → ``provider_error``) → ``oauth_state.issue_grant(provider='qq', subject=openid, kind, uid, invite, next, bh)`` — no
  identity is written and no account created here — → 302 ``{WD_PUBLIC_URL or request origin}/api/auth/oauth/finish?grant=…``; every
  ``ApiError`` on this GET becomes a 302 to ``/login?error=<code>`` (login) or ``/settings?error=<code>`` (bind) — the SPA maps the
  code with ``errorMessage``;
* ``GET /api/auth/apple/start?kind&invite_code&next`` (120): Apple off (``app.state.apple is None``) → 409; bind needs a session;
  ``apple_start:ip`` 10/min; the same cookie + ``bh``; a 32-hex ``nonce`` (``oauth_state.new_nonce``) goes into the state; 302 to
  ``delivery.apple.authorize_url``;
* ``POST /api/auth/apple/callback`` (121, ``application/x-www-form-urlencoded`` ``state``, ``id_token``, ``code``, ``user?``, ``error?``;
  CSRF-exempt by path — ``deps.CSRF_EXEMPT_PATHS``, the signed state is its defence; the body is parsed here without ``python-multipart``):
  ``apple_callback:ip`` 600/min; ``error=user_cancelled_authorize`` → 302 ``/login`` or ``/settings`` (the raw ``error`` value is never
  logged — only whether it was the cancel, or a 32-char ASCII excerpt); ``oauth_state.verify`` → ``delivery.apple.verify_id_token(token,
  keys=app.state.apple, client_ids=(cfg.apple_client_id, cfg.apple_app_id), now, nonce)`` (the fake audience while Apple is not
  configured; 401 ``invalid_identity_token`` → the error redirect) → ``sub`` → the grant (``provider='apple'``) → 302 to 122; the ``user``
  form field is ignored;
* ``GET /api/auth/oauth/finish?grant=`` (122): ``oauth_state.redeem_grant`` (its own ``BEGIN IMMEDIATE``: single use whatever happens
  next) → unknown / expired → 302 ``/login?error=invalid_grant``; the ``wd_oauth`` cookie must hash to the grant's ``bh`` — else 302
  ``/login?error=invalid_grant`` (bind: ``/settings?error=invalid_grant``) and NOTHING else happens (no session touched, nothing written):
  the grant, the callback URL and the state are worthless to a browser that did not start the flow; for ``kind=bind`` the browser's
  ``wd_session`` cookie must resolve to a live session of ``uid`` (the account that started the bind), else the same refusal. Then the
  unusable bcrypt hash of a possible new account is computed BEFORE the transaction (login only, when no live identity holds the
  subject) and ONE transaction runs ``third_party.third_party_login_or_bind`` (the §3.3 rules shared with the WeChat bridge) — login:
  ``security.gc_sessions``, this browser's previous session deleted (replaced, not left behind), ``create_session`` (a self session),
  ``UPDATE users SET last_login_at`` and the identity's ``last_login_at``, ``security.set_session_cookie``; bind: no new session — the
  browser keeps its own. The ``wd_oauth`` cookie is cleared (Max-Age 0). An ``ApiError`` of the helper (``identity_taken``,
  ``registration_closed``, ``invalid_invite``, ``password_required``, ``account_disabled``, ``setup_required``) → 302
  ``/login?error=<code>`` (login) / ``/settings?error=<code>`` (bind). 302 to ``next`` (default ``/``; a created account → ``/welcome``;
  bind → ``/settings?bound=<provider>``). Why the hop: the QQ / Apple callback may land on the FILED relay domain (DEPLOY §7.1) while
  the SPA lives on ``WD_PUBLIC_URL``; a cookie set there would not reach the SPA — and the ``wd_oauth`` cookie set by 118 / 120 is not
  visible there either, which is why the login / bind itself waits for 122. When both share the origin it is harmless.

Log events: ``qq_start`` / ``apple_start``, ``qq_verified`` / ``apple_verified`` (the provider vouched for a subject; kind), ``qq_login`` /
``qq_bound`` / ``apple_login`` / ``apple_bound`` (at 122: user id, ``created_account``), ``oauth_finish_refused`` (reason / code),
``qq_callback_refused`` / ``apple_callback_refused``, ``qq_provider_error`` / ``apple_provider_error`` (the provider's kind and short
code) — ids only, never an openid, a ``sub``, a code, a token, a state, a grant or the browser secret.
"""

from __future__ import annotations

import hmac
import logging
import re
import sqlite3
from typing import Any
from urllib.parse import parse_qs, urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from .. import db, oauth_state, security, third_party
from ..clock import to_iso
from ..config import Settings
from ..delivery import apple as apple_delivery
from ..delivery.apple import AppleError
from ..delivery.qq import QQError
from ..deps import SESSION_COOKIE, client_ip, current_user, get_db, hash_token, host_origin, require_not_child
from ..errors import ApiError

log = logging.getLogger("wd.routers.auth_oauth")

router = APIRouter()

# the redirect endpoints declare no Query length limits on purpose: a browser arriving with an odd value gets the error REDIRECT the SPA
# can show, never a JSON 400 — oauth_state.verify / redeem_grant / safe_next bound the lengths themselves (and the body limit applies)
START_IP_LIMIT = 10  # qq_start:ip / apple_start:ip, per minute
START_IP_WINDOW_S = 60
CALLBACK_IP_LIMIT = 600  # qq_callback:ip / apple_callback:ip, per minute — a flood brake only: behind the mainland relay every callback shares the
# relay's IP, so a tight window would be a site-wide cap; the signed state + the wd_oauth browser cookie + the 60 s grant are the real defences
CALLBACK_IP_WINDOW_S = 60
INVITE_MAX_LEN = 64  # an invite code is 19 chars (XXXX-XXXX-XXXX-XXXX); anything longer is not one
FINISH_PATH = "/api/auth/oauth/finish"
LOGIN_PATH = "/login"
SETTINGS_PATH = "/settings"
WELCOME_PATH = "/welcome"
APPLE_CANCELLED = "user_cancelled_authorize"  # Apple's `error` form field when the user dismissed the sheet
ERROR_EXCERPT_LEN = 32  # how much of an unexpected Apple `error` value reaches the log, ASCII-sanitised
_UNSAFE_LOG_CHARS = re.compile(r"[^A-Za-z0-9_.-]")


# -------------------------------------------------------------------------------------------- helpers
def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302)


def _spa_path(kind: str | None, *, error: str | None = None, **params: str) -> str:
    """``/login`` (login) or ``/settings`` (bind), with ``?error=<code>`` and any other parameter the SPA reads."""
    base = SETTINGS_PATH if kind == "bind" else LOGIN_PATH
    query = {k: v for k, v in ({"error": error, **params}).items() if v}
    return f"{base}?{urlencode(query)}" if query else base


def _kind_of(payload: dict[str, Any]) -> str:
    kind = payload.get("kind")
    if kind not in oauth_state.STATE_KINDS:
        raise ApiError("invalid_identity_token")
    return str(kind)


def _peek_kind(cfg: Settings, provider: str, state: str | None, now) -> str:
    """The kind of a state that verifies, else ``login`` — only to pick the page a cancel or an early error returns to."""
    if not state:
        return "login"
    try:
        return _kind_of(oauth_state.verify(cfg, provider, state, now))
    except ApiError:
        return "login"


def _ascii_excerpt(text: str) -> str:
    """At most :data:`ERROR_EXCERPT_LEN` chars of an attacker-controlled value with everything outside ``[A-Za-z0-9_.-]`` replaced — what a
    log line may carry."""
    return _UNSAFE_LOG_CHARS.sub("_", text)[:ERROR_EXCERPT_LEN]


def _set_oauth_cookie(request: Request, response: Response, secret: str, cfg: Settings) -> None:
    """The ``wd_oauth`` browser secret of this flow on the 302 of 118 / 120 (the SPA origin — the same origin 122 is served on)."""
    response.set_cookie(
        key=oauth_state.OAUTH_COOKIE,
        value=secret,
        max_age=oauth_state.OAUTH_COOKIE_TTL_S,
        path=oauth_state.OAUTH_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=security.cookie_secure(request, cfg),
    )


def _clear_oauth_cookie(request: Request, response: Response, cfg: Settings) -> None:
    response.delete_cookie(key=oauth_state.OAUTH_COOKIE, path=oauth_state.OAUTH_COOKIE_PATH, httponly=True, samesite="lax", secure=security.cookie_secure(request, cfg))


def _start(request: Request, conn: sqlite3.Connection, *, provider: str, client: object | None, kind: str, invite_code: str | None, next_: str | None) -> tuple[dict[str, Any], str]:
    """Endpoints 118 / 120 up to the state payload: the provider must be on, a bind needs a non-child session, the per-IP window, the
    browser secret. Returns ``(payload, secret)`` — the payload carries ``bh = sha256(secret)``, the secret becomes the ``wd_oauth`` cookie."""
    now = request.app.state.clock.now_utc()
    if client is None:
        raise ApiError("provider_unconfigured")
    if kind not in oauth_state.STATE_KINDS:
        raise ApiError("validation_error", details={"fields": {"kind": "取值无效"}})
    payload: dict[str, Any] = {"kind": kind, "next": oauth_state.safe_next(next_)}
    if kind == "bind":
        user = require_not_child(current_user(request, conn))
        payload["uid"] = int(user["id"])
    else:
        invite = (invite_code or "").strip()
        if invite:
            payload["invite"] = invite[:INVITE_MAX_LEN]
    security.rate_limit(conn, f"{provider}_start:ip:{client_ip(request)}", limit=START_IP_LIMIT, window_s=START_IP_WINDOW_S, now=now)
    secret = oauth_state.new_browser_secret()
    payload["bh"] = oauth_state.browser_hash(secret)
    return payload, secret


def _finish_url(request: Request, cfg: Settings, grant: str) -> str:
    """The 302 target of a callback: endpoint 122 on the SPA's origin (``WD_PUBLIC_URL``), else on the request's own origin."""
    base = cfg.public_url.rstrip("/") if cfg.public_url else (host_origin(request.url.scheme, request.headers, cfg) or "")
    return f"{base}{FINISH_PATH}?{urlencode({'grant': grant})}"


def _grant_for(request: Request, conn: sqlite3.Connection, *, provider: str, subject: str, payload: dict[str, Any], now) -> str:
    """The shared tail of 119 / 121: the verified ``subject`` and the state's fields become the one-time grant 122 redeems — nothing
    else is written here (the login / bind happens at 122, where the browser's cookie and session can be checked)."""
    cfg: Settings = request.app.state.settings
    kind = _kind_of(payload)
    bh = payload.get("bh")
    if not isinstance(bh, str) or not bh:
        raise ApiError("invalid_identity_token")  # a state without the browser binding (never minted by this code) is not ours to finish
    uid: int | None = None
    invite: str | None = None
    if kind == "bind":
        raw_uid = payload.get("uid")
        if not isinstance(raw_uid, int) or isinstance(raw_uid, bool):
            raise ApiError("invalid_identity_token")
        uid = raw_uid
    else:
        raw_invite = payload.get("invite")
        invite = raw_invite if isinstance(raw_invite, str) and raw_invite else None
    nonce = payload.get("nonce") if isinstance(payload.get("nonce"), str) else None
    with db.tx(conn):
        grant = oauth_state.issue_grant(
            conn,
            cfg,
            provider=provider,
            subject=subject,
            kind=kind,
            uid=uid,
            invite=invite,
            next=oauth_state.safe_next(payload.get("next")),
            bh=bh,
            now=now,
            nonce=nonce,
        )
    log.info("%s verified a subject", provider, extra={"event": f"{provider}_verified", "kind": kind, "user_id": uid})
    return grant


def _session_user_id(conn: sqlite3.Connection, token: str | None, now_iso: str) -> int | None:
    """The account behind a live ``wd_session`` cookie value, or None (no cookie, unknown, expired) — endpoint 122's bind check, without
    the side effects of ``deps.current_user`` (no slide, no mutation throttle, no 401)."""
    if not token:
        return None
    row = conn.execute("SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (hash_token(token),)).fetchone()
    if row is None or str(row["expires_at"]) <= now_iso:
        return None
    return int(row["user_id"])


async def urlencoded_form(request: Request) -> dict[str, str]:
    """The ``application/x-www-form-urlencoded`` body of endpoint 121 as ``{field: first value}`` — Apple's ``form_post`` is plain
    urlencoded, so no ``python-multipart`` dependency is needed (the body limit of ``main.WdMiddleware`` applies)."""
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return {k: v[0] for k, v in parse_qs(text, keep_blank_values=True).items() if v}


# -------------------------------------------------------------------------------------------- 118 / 119
@router.get("/api/auth/qq/start", response_class=RedirectResponse, status_code=302)
def qq_start(
    request: Request,
    kind: str = Query("login"),
    invite_code: str | None = Query(None),
    next_: str | None = Query(None, alias="next"),
    conn: sqlite3.Connection = Depends(get_db),
):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    qq = getattr(request.app.state, "qq", None)
    payload, secret = _start(request, conn, provider="qq", client=qq, kind=kind, invite_code=invite_code, next_=next_)
    state = oauth_state.sign(cfg, "qq", payload, now)
    log.info("qq start", extra={"event": "qq_start", "kind": payload["kind"], "user_id": payload.get("uid")})
    response = _redirect(qq.authorize_url(state))  # type: ignore[union-attr]  # _start refused a None client
    _set_oauth_cookie(request, response, secret, cfg)
    return response


@router.get("/api/auth/qq/callback", response_class=RedirectResponse, status_code=302)
def qq_callback(
    request: Request,
    code: str | None = Query(None),
    state: str | None = Query(None),
    msg: str | None = Query(None),  # QQ's human-readable reason on a refusal: never shown, never logged
    usercancel: str | None = Query(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    qq = getattr(request.app.state, "qq", None)
    kind = _peek_kind(cfg, "qq", state, now)
    try:
        security.rate_limit(conn, f"qq_callback:ip:{client_ip(request)}", limit=CALLBACK_IP_LIMIT, window_s=CALLBACK_IP_WINDOW_S, now=now)
        if usercancel or not code:
            log.info("qq callback without a code", extra={"event": "qq_cancelled", "kind": kind})
            return _redirect(_spa_path(kind))
        if qq is None:
            raise ApiError("provider_unconfigured")
        payload = oauth_state.verify(cfg, "qq", state or "", now)
        kind = _kind_of(payload)
        try:
            openid = qq.openid(qq.exchange(code))
        except QQError as e:
            log.warning("qq exchange failed: %s (%s)", e.kind, e.code or "-", extra={"event": "qq_provider_error", "kind": e.kind})
            raise ApiError("invalid_identity_token" if e.kind == "invalid_code" else "provider_error") from e
        grant = _grant_for(request, conn, provider="qq", subject=openid, payload=payload, now=now)
        return _redirect(_finish_url(request, cfg, grant))
    except ApiError as e:
        log.info("qq callback refused: %s", e.code, extra={"event": "qq_callback_refused", "code": e.code, "kind": kind})
        return _redirect(_spa_path(kind, error=e.code))


# -------------------------------------------------------------------------------------------- 120 / 121
@router.get("/api/auth/apple/start", response_class=RedirectResponse, status_code=302)
def apple_start(
    request: Request,
    kind: str = Query("login"),
    invite_code: str | None = Query(None),
    next_: str | None = Query(None, alias="next"),
    conn: sqlite3.Connection = Depends(get_db),
):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    apple = getattr(request.app.state, "apple", None)
    payload, secret = _start(request, conn, provider="apple", client=apple, kind=kind, invite_code=invite_code, next_=next_)
    nonce = oauth_state.new_nonce()
    payload["nonce"] = nonce
    state = oauth_state.sign(cfg, "apple", payload, now)
    log.info("apple start", extra={"event": "apple_start", "kind": payload["kind"], "user_id": payload.get("uid")})
    response = _redirect(apple_delivery.authorize_url(cfg, state, nonce))
    _set_oauth_cookie(request, response, secret, cfg)
    return response


@router.post("/api/auth/apple/callback", response_class=RedirectResponse, status_code=302)
def apple_callback(request: Request, form: dict[str, str] = Depends(urlencoded_form), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    apple = getattr(request.app.state, "apple", None)
    state = form.get("state")
    kind = _peek_kind(cfg, "apple", state, now)
    try:
        security.rate_limit(conn, f"apple_callback:ip:{client_ip(request)}", limit=CALLBACK_IP_LIMIT, window_s=CALLBACK_IP_WINDOW_S, now=now)
        error = (form.get("error") or "").strip()
        if error:
            cancelled = error == APPLE_CANCELLED
            # the value is attacker-controlled on a public, CSRF-exempt POST: the log sees the closed vocabulary or a sanitised excerpt
            log.info(
                "apple callback with error: %s",
                "cancelled" if cancelled else f"other ({_ascii_excerpt(error)})",
                extra={"event": "apple_cancelled" if cancelled else "apple_error", "kind": kind, "cancelled": cancelled},
            )
            return _redirect(_spa_path(kind) if cancelled else _spa_path(kind, error="provider_error"))
        if apple is None:
            raise ApiError("provider_unconfigured")
        payload = oauth_state.verify(cfg, "apple", state or "", now)
        kind = _kind_of(payload)
        nonce = payload.get("nonce")
        id_token = form.get("id_token")
        if not isinstance(nonce, str) or not nonce or not id_token:
            raise ApiError("invalid_identity_token")
        # the Services ID (and the iOS bundle id once the plugin exists); an unconfigured instance only ever sees the fake consent page's tokens
        client_ids = (cfg.apple_client_id, cfg.apple_app_id) if cfg.apple_configured else (apple_delivery.FAKE_AUDIENCE,)
        try:
            claims = apple_delivery.verify_id_token(id_token, keys=apple, client_ids=client_ids, now=now, nonce=nonce)
        except AppleError as e:
            log.warning("apple id_token refused: %s (%s)", e.kind, e.code or "-", extra={"event": "apple_provider_error", "kind": e.kind})
            raise ApiError("invalid_identity_token" if e.kind == "invalid_token" else "provider_error") from e
        grant = _grant_for(request, conn, provider="apple", subject=str(claims["sub"]), payload=payload, now=now)
        return _redirect(_finish_url(request, cfg, grant))
    except ApiError as e:
        log.info("apple callback refused: %s", e.code, extra={"event": "apple_callback_refused", "code": e.code, "kind": kind})
        return _redirect(_spa_path(kind, error=e.code))


# -------------------------------------------------------------------------------------------- 122
@router.get("/api/auth/oauth/finish", response_class=RedirectResponse, status_code=302)
def oauth_finish(request: Request, grant: str | None = Query(None), conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)

    def refused(page: str, code: str, reason: str) -> RedirectResponse:
        log.info("oauth finish refused: %s", reason, extra={"event": "oauth_finish_refused", "code": code, "reason": reason, "kind": page})
        return _redirect(_spa_path(page, error=code))

    payload = oauth_state.redeem_grant(conn, grant or "", now)  # its own BEGIN IMMEDIATE: the grant is spent whatever happens next
    if payload is None:
        return refused("login", "invalid_grant", "no_live_grant")
    kind = payload.get("kind")
    page = "bind" if kind == "bind" else "login"
    provider = payload.get("provider")
    subject = payload.get("subject")
    bh = payload.get("bh")
    if kind not in oauth_state.STATE_KINDS or provider not in oauth_state.GRANT_PROVIDERS or not isinstance(subject, str) or not subject or not isinstance(bh, str) or not bh:
        return refused(page, "invalid_grant", "malformed_grant")
    secret = request.cookies.get(oauth_state.OAUTH_COOKIE)
    if not secret or not hmac.compare_digest(oauth_state.browser_hash(secret).encode("ascii"), bh.encode("ascii")):
        # not the browser that called /start: the result is nobody else's to collect — no session touched, nothing written, cookie left alone
        return refused(page, "invalid_grant", "browser_mismatch")
    uid: int | None = None
    if kind == "bind":
        raw_uid = payload.get("uid")
        if not isinstance(raw_uid, int) or isinstance(raw_uid, bool):
            return refused(page, "invalid_grant", "malformed_grant")
        uid = raw_uid
        if _session_user_id(conn, request.cookies.get(SESSION_COOKIE), now_iso) != uid:
            return refused(page, "invalid_grant", "session_mismatch")  # the binder's own session must still be in this browser
        user = security.load_user(conn, uid)
        if user is None:
            return refused(page, "invalid_grant", "account_gone")
        if not int(user["is_active"]):
            return refused(page, "account_disabled", "account_disabled")
        if user.get("guardian_user_id") is not None:
            return refused(page, "guardian_required", "child_account")  # became a child since /start (the §1 restriction list)
    raw_invite = payload.get("invite")
    invite = raw_invite if isinstance(raw_invite, str) and raw_invite else None
    unusable = security.unusable_password_hash() if kind == "login" and security.identity_by_subject(conn, str(provider), subject) is None else None
    factory = (lambda: unusable) if unusable is not None else security.unusable_password_hash  # a race that made the account meanwhile wastes one hash, never the lock
    token: str | None = None
    try:
        with db.tx(conn):
            user_id, created = third_party.third_party_login_or_bind(
                conn,
                cfg,
                provider=str(provider),
                subject=subject,
                kind=str(kind),
                bind_user_id=uid,
                invite_code=invite,
                password_hash_factory=factory,
                now=now,
            )
            if kind == "login":
                security.gc_sessions(conn, now_iso)
                previous = request.cookies.get(SESSION_COOKIE)
                if previous:  # this browser's own session (a login from a signed-in tab) is replaced, not left behind until it expires
                    security.delete_session(conn, hash_token(previous))
                token = security.create_session(conn, int(user_id), now, session_days=cfg.session_days, user_agent=request.headers.get("user-agent"), ip=client_ip(request))
                conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, int(user_id)))
                conn.execute("UPDATE identities SET last_login_at = ? WHERE user_id = ? AND provider = ? AND disputed_at IS NULL", (now_iso, int(user_id), provider))
    except ApiError as e:
        response = refused(page, e.code, e.code)
        _clear_oauth_cookie(request, response, cfg)  # the flow this browser started is over, whatever the outcome
        return response
    if kind == "bind":
        target = _spa_path("bind", bound=str(provider))
    elif created:
        target = WELCOME_PATH
    else:
        target = oauth_state.safe_next(payload.get("next"))
    response = _redirect(target)
    if token is not None:
        security.set_session_cookie(response, token, cfg, secure=security.cookie_secure(request, cfg))
    _clear_oauth_cookie(request, response, cfg)
    event = f"{provider}_bound" if kind == "bind" else f"{provider}_login"
    log.info("%s", event.replace("_", " "), extra={"event": event, "user_id": int(user_id), "created_account": bool(created), "provider": provider})
    return response
