"""FastAPI dependencies (Phase 0, frozen contract — TASKS.md P0 step 4).

* :func:`get_db` — one connection per request (closed afterwards).
* :func:`current_user` — the session cookie ``wd_session`` → ``sessions`` row (``token_hash = sha256(cookie)``),
  401 ``unauthorized`` / 403 ``account_disabled``; slides the expiry at most once per day and never SHORTENS it
  (``expires_at = max(current, now + WD_SESSION_DAYS)`` — the 90-day child-device session of API.md 107 keeps its horizon, slice 1-B;
  the middleware re-sends the cookie with the seconds left, ``request.state.reissue_session_max_age_s``); on a non-GET request
  also counts DESIGN §10's per-user mutation throttle (``security.throttle_mutation``, 300/min → 429 ``rate_limited``). The user dict
  carries the session's ``actor_user_id`` (``session_actor_user_id``: the guardian who switched this device into a child account,
  API.md 104) and its 家长门 stamp (``session_gate_at``, API.md 102 / 105) next to ``session_token_hash``.
* :func:`require_onboarded` (409 ``onboarding_required``), :func:`require_admin` (403 ``forbidden``); slice 1-B (API.md §1):
  :func:`require_not_child` (403 ``guardian_required`` for a child account on the restriction list), :func:`require_guardian`
  (the ``G`` column: a guardian in its own session, else 403 ``forbidden``) and :func:`require_gate` (``G+gate``: the session's
  家长门 stamp younger than 10 minutes, else 403 ``guardian_gate_required``).
* :func:`csrf_guard` — API.md §1: every non-GET ``/api/*`` request carries ``X-WD-Request: 1`` and, when an
  ``Origin`` header is present, it equals the request's own Host-derived origin or the origin of
  ``WD_PUBLIC_URL`` (plus ``http://localhost:5173`` under ``WD_DEV=1``). The same check runs globally in
  ``main.py``'s middleware; the dependency exists for explicit wiring and tests.
* :func:`client_ip` — the connecting peer; behind a trusted proxy (``WD_TRUST_PROXY=1``) the address the proxy
  appended to ``X-Forwarded-For`` (resolved by uvicorn's ``ProxyHeadersMiddleware``; fallback: the LAST hop), never the
  client-supplied first hop, which would let anyone rotate past the per-IP throttles.
* :func:`visible_word_sql` — the API.md §1 / DESIGN §5.2 word visibility predicate as a reusable SQL fragment.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import timedelta
from typing import Any, Iterator, Mapping

from fastapi import Depends, Request

from . import db
from .clock import Clock, parse_iso, to_iso
from .config import Settings
from .errors import ApiError

SESSION_COOKIE = "wd_session"
CSRF_HEADER = "x-wd-request"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
DEV_ORIGIN = "http://localhost:5173"
# the peers `wd serve` trusts for X-Forwarded-* (uvicorn `forwarded_allow_ips="127.0.0.1"`, DEPLOY §3)
TRUSTED_PROXY_PEERS: tuple[str, ...] = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
USER_COLUMNS = (
    "id",
    "username",
    "email",
    "email_verified_at",
    "display_name",
    "password_hash",
    "role",
    "is_active",
    "onboarding_state",
    "created_at",
    "updated_at",
    "last_login_at",
    "password_set_at",  # 0018 (docs/AUTH_SIGNUP_DESIGN.md §5.1): User.has_password and the password-or-code dispatch of endpoints 7 / 8
    "account_kind",
    "guardian_user_id",
    "age_band",
    "age_declared_at",
    "guardian_consent_at",  # 1-B
    "profile_prompted_at",  # 0019 (1-B): the legacy prompt's snooze — User.needs_profile_prompt
)


def hash_token(token: str) -> str:
    """hex sha256 of the opaque cookie value (the raw token is never stored — SCHEMA `sessions`)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """One connection for this request; ``check_same_thread=False`` because FastAPI runs sync dependencies and
    endpoints on arbitrary threadpool threads sequentially (see ``db.connect``)."""
    conn = db.connect(request.app.state.settings.db_path, check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()


# ----------------------------------------------------------------------------------- client / csrf
def client_ip(request: Request) -> str:
    """The client address the throttles (``login:ip:*``, ``register:ip:*``) and ``sessions.ip`` are keyed on.

    ``wd serve`` runs uvicorn with ``proxy_headers=WD_TRUST_PROXY, forwarded_allow_ips="127.0.0.1"`` (DEPLOY §3), whose
    ``ProxyHeadersMiddleware`` already rewrites ``request.client`` to the right-most ``X-Forwarded-For`` hop that is not a
    trusted proxy — i.e. the ``$remote_addr`` nginx appends (``$proxy_add_x_forwarded_for``) or the client IP Caddy sets.
    So the peer address is the answer. Only when that middleware did not run (another ASGI runner, tests) and the peer
    *is* the local proxy, the LAST hop of the header is taken as a fallback — never the first one, which is whatever the
    client itself sent and would let an attacker rotate past every per-IP limit.
    """
    cfg: Settings = request.app.state.settings
    peer = request.client.host if request.client else ""
    if cfg.trust_proxy and peer in TRUSTED_PROXY_PEERS:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            last = xff.rsplit(",", 1)[-1].strip()
            if last:
                return last
    return peer or "0.0.0.0"


def host_origin(scheme: str, headers: Mapping[str, str], cfg: Settings) -> str | None:
    """``scheme://host`` of the request itself (scheme from ``X-Forwarded-Proto`` when ``WD_TRUST_PROXY=1``)."""
    host = headers.get("host")
    if not host:
        return None
    if cfg.trust_proxy:
        proto = headers.get("x-forwarded-proto")
        if proto:
            scheme = proto.split(",")[0].strip().lower() or scheme
    return f"{scheme.lower()}://{host.strip().lower()}"


def csrf_violation(method: str, scheme: str, headers: Mapping[str, str], cfg: Settings) -> str | None:
    """Reason the request fails the CSRF rule, or None when it passes (pure; shared by middleware and dependency).

    ``headers`` must be a lower-case-keyed mapping (``Request.headers`` is case-insensitive already).
    """
    if method.upper() in SAFE_METHODS:
        return None
    if headers.get(CSRF_HEADER, "").strip() != "1":
        return "missing X-WD-Request header"
    origin = headers.get("origin")
    if not origin:
        return None  # no Origin header (same-origin fetch in some browsers, curl): SameSite=Lax + the custom header suffice
    origin = origin.strip().lower().rstrip("/")
    if origin == "null":
        return "Origin null"
    allowed = {o for o in (host_origin(scheme, headers, cfg), cfg.public_origin) if o}
    if cfg.dev:
        allowed.add(DEV_ORIGIN)
    return None if origin in allowed else "Origin mismatch"


def csrf_guard(request: Request) -> None:
    """Dependency form of the CSRF rule (403 ``csrf_rejected``)."""
    if not request.url.path.startswith("/api/"):
        return
    reason = csrf_violation(request.method, request.url.scheme, request.headers, request.app.state.settings)
    if reason:
        raise ApiError("csrf_rejected", details={"reason": reason})


# ------------------------------------------------------------------------------------------ users
def current_user(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    """The logged-in user as a dict (``USER_COLUMNS`` + ``session_token_hash``); 401 / 403 otherwise."""
    cfg: Settings = request.app.state.settings
    clock: Clock = request.app.state.clock
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError("unauthorized")
    token_hash = hash_token(token)
    now_dt = clock.now_utc()
    now = to_iso(now_dt)
    row = conn.execute(
        "SELECT u.*, s.expires_at AS session_expires_at, s.last_seen_at AS session_last_seen_at, "
        "s.actor_user_id AS session_actor_user_id, s.guardian_gate_at AS session_gate_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
        (token_hash,),
    ).fetchone()
    if row is None:
        raise ApiError("unauthorized")
    if str(row["session_expires_at"]) <= now:
        with db.maybe_tx(conn):
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        raise ApiError("unauthorized")
    if not int(row["is_active"]):
        raise ApiError("account_disabled")
    if str(row["session_last_seen_at"]) < to_iso(now_dt - timedelta(days=1)):  # sliding expiry, once per day
        # never shortened: a 90-day child-device session (API.md 107) keeps its horizon until the slide would pass it; a 30-day
        # session slides exactly as before
        expires = max(parse_iso(str(row["session_expires_at"])), now_dt + timedelta(days=cfg.session_days))
        with db.maybe_tx(conn):
            conn.execute("UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE token_hash = ?", (now, to_iso(expires), token_hash))
        # the browser drops the cookie Max-Age seconds after the Set-Cookie it last saw, whatever the row says: have the
        # middleware re-send it with the seconds left on the row (main.WdMiddleware reads scope["state"], the dict behind request.state)
        request.state.reissue_session_token = token
        request.state.reissue_session_max_age_s = max(1, int((expires - now_dt).total_seconds()))
    user = {k: row[k] for k in USER_COLUMNS}
    user["session_token_hash"] = token_hash
    user["session_actor_user_id"] = row["session_actor_user_id"]
    user["session_gate_at"] = row["session_gate_at"]
    request.state.user_id = user["id"]
    if request.method.upper() not in SAFE_METHODS:  # DESIGN §10 "mutations 300/min per user" — one place for every authenticated route
        from . import security  # security imports this module (SESSION_COOKIE, hash_token), so resolve the cycle at call time

        security.throttle_mutation(conn, int(user["id"]), now_dt)
    return user


def require_onboarded(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["onboarding_state"] != "done":
        raise ApiError("onboarding_required", details={"onboarding_state": user["onboarding_state"]})
    return user


def require_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    if user["role"] != "admin":
        raise ApiError("forbidden")
    return user


def require_not_child(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """The child restriction list (API.md §1, slice 1-B): a child account (``guardian_user_id`` set) gets 403 ``guardian_required`` on the
    account / identity endpoints whatever the session type — its guardian does these things in 「我的孩子」."""
    if user.get("guardian_user_id") is not None:
        raise ApiError("guardian_required")
    return user


def require_guardian(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    """The ``G`` auth column (API.md §1): an account with ``account_kind='guardian'`` acting in its OWN session (``actor_user_id`` NULL) —
    a switched child session and every non-guardian get 403 ``forbidden``."""
    if user.get("account_kind") != "guardian" or user.get("session_actor_user_id") is not None:
        raise ApiError("forbidden")
    return user


def require_gate(request: Request, user: dict[str, Any] = Depends(require_guardian)) -> dict[str, Any]:
    """``G+gate``: the session's 家长门 stamp (``sessions.guardian_gate_at``, endpoints 102 / 105) not older than 10 minutes, else 403
    ``guardian_gate_required`` (the SPA opens the gate dialog and retries)."""
    from . import family  # family imports security, which imports this module: resolve the cycle at call time

    if family.gate_until(user, request.app.state.clock.now_utc()) is None:
        raise ApiError("guardian_gate_required")
    return user


def is_admin(me: Mapping[str, Any] | None) -> bool:
    return bool(me) and me.get("role") == "admin"


# ------------------------------------------------------------------------------------- visibility
def visible_word_sql(me: Mapping[str, Any] | int | None, *, alias: str = "words", param: str = "me") -> str:
    """The word visibility predicate (API.md §1, DESIGN §5.2) for ``alias`` (default ``words``).

    ``me`` is the user dict from :func:`current_user` (admins see every word → ``1=1``) or a bare user id.
    The fragment binds the named parameter ``:me`` (rename with ``param``) — bind it with
    ``{"me": user_id}``; it is referenced twice, so use named parameters in the surrounding statement.
    """
    if isinstance(me, Mapping) and is_admin(me):
        return "1=1"
    if me is None:
        return f"{alias}.is_public = 1"
    p = ":" + param
    return (
        f"({alias}.is_public = 1 OR {alias}.created_by_user_id = {p} "
        f"OR EXISTS (SELECT 1 FROM user_words uw_vis WHERE uw_vis.user_id = {p} AND uw_vis.word_id = {alias}.id))"
    )


def user_id_of(me: Mapping[str, Any] | int) -> int:
    return int(me["id"]) if isinstance(me, Mapping) else int(me)
