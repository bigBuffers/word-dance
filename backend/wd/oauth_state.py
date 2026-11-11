"""Signed OAuth ``state``, the browser-binding cookie and the one-time cross-origin grant of the QQ / Apple flows (API.md §3.3
endpoints 118–122; docs/AUTH_SIGNUP_DESIGN.md §5.3).

Slice 2-A: the constants and signatures here are what ``routers/auth_oauth.py``, ``routers/auth_fake.py`` and
``tests/unit/test_oauth_state.py`` build against.

* **browser secret** (:func:`new_browser_secret` / :func:`browser_hash`): endpoints 118 / 120 draw 32 random urlsafe bytes, set them as
  the HttpOnly cookie :data:`OAUTH_COOKIE` (``wd_oauth``; ``SameSite=Lax``, ``Secure`` like the session cookie, ``Path`` :data:`OAUTH_COOKIE_PATH`,
  Max-Age :data:`OAUTH_COOKIE_TTL_S`) on the 302 to the provider and put ``sha256(secret)`` into the signed state as ``bh``. The callback
  copies ``bh`` into the grant and endpoint 122 — served on the SPA origin like 118 / 120 — refuses a grant whose ``bh`` is not the hash
  of the ``wd_oauth`` cookie the browser presents: the state, the callback URL and the grant are therefore useless to any browser but
  the one that started the flow (no login CSRF, no bind-state fixation, no session swap). The cookie never identifies a user.
* **state** (:func:`sign` / :func:`verify`): ``f"{exp}.{b64url(json)}.{hmac_hex(WD_SECRET_KEY, f'{provider}:{exp}.{b64url}')}"``, valid
  :data:`STATE_TTL_S` (10 minutes). The payload is ``{kind, uid (bind only), invite (login, optional), next (a same-origin path starting
  with "/" else "/"), bh, nonce (Apple)}``; the provider name is part of the signed string, so a QQ state cannot be replayed at the
  Apple callback. Any failure (shape, a non-ASCII or oversized part, signature, expiry, provider) → ``ApiError('invalid_identity_token')``
  — never a ``ValueError`` / ``TypeError`` out of a crafted query string — and the callback turns it into a 302 to
  ``/login?error=invalid_identity_token`` (login) or ``/settings?error=…`` (bind). The state is the CSRF defence of the callbacks (121
  is exempt from the header rule, ``deps.CSRF_EXEMPT_PATHS``); the browser binding above is what makes the RESULT the browser's own.
* **grant** (:func:`issue_grant` / :func:`redeem_grant`): the QQ / Apple callback may land on the FILED relay domain while the SPA lives
  on ``WD_PUBLIC_URL``; a cookie set there would not reach the SPA, so the verified result crosses origins as a one-time grant — 32
  random urlsafe bytes, :data:`GRANT_TTL_S` (60 s), single use, stored in ``kv`` as ``kv["oauth_grant:<exp iso>:<sha256(grant)>"] = json
  {provider, subject, kind, uid (bind only), invite, next, bh, nonce (Apple)}`` and deleted inside the same ``BEGIN IMMEDIATE`` that
  reads it. The callback writes NOTHING but the grant: ``subject`` is the openid / Apple ``sub`` the provider vouched for, and endpoint
  122 — after the cookie check, and for a bind after checking that the browser's session belongs to ``uid`` — runs the shared
  ``third_party.third_party_login_or_bind`` rules, then issues the session (login) or keeps the browser's own one (bind) and 302s to
  ``next`` / ``/welcome`` / ``/settings?bound=<provider>``. When callback and SPA share the origin the hop is harmless.
* :func:`gc_grants` deletes expired grants by the expiry embedded in the key (``DELETE FROM kv WHERE key LIKE 'oauth_grant:%' AND
  substr(key, 13, 20) < ?``) from ``jobs.scheduler.hourly_gc``.

Nothing but ids ever reaches a log line: no state, no grant, no nonce, no browser secret.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from . import db, rsa_verify
from .clock import to_iso
from .config import Settings
from .errors import ApiError

log = logging.getLogger("wd.oauth_state")

STATE_TTL_S = 600
GRANT_TTL_S = 60
GRANT_BYTES = 32
GRANT_KEY_PREFIX = "oauth_grant:"  # kv key: oauth_grant:<exp iso, 20 chars>:<sha256 hex of the grant>
GRANT_KEY_EXPIRY_START = len(GRANT_KEY_PREFIX) + 1  # 13 — the 1-based `substr` position of the embedded expiry in the kv key
GRANT_KEY_EXPIRY_LEN = 20  # len("2026-11-11T12:00:00Z")
NONCE_HEX_LEN = 32  # the Apple nonce in the state (16 random bytes as hex)
STATE_KINDS: tuple[str, ...] = ("login", "bind")
GRANT_PROVIDERS: tuple[str, ...] = ("qq", "apple")  # the providers whose results travel as a grant
NEXT_MAX_LEN = 512  # a `next` longer than this is not a path of this SPA
STATE_MAX_LEN = 4096  # the longest state `verify` will even look at (a payload is a handful of short fields)
OAUTH_COOKIE = "wd_oauth"  # the browser secret of a QQ / Apple flow (HttpOnly, SameSite=Lax, Secure like the session cookie)
OAUTH_COOKIE_PATH = "/api/auth"  # covers 118 / 120 (set) and 122 (checked), nothing the SPA's own requests need
OAUTH_COOKIE_TTL_S = STATE_TTL_S  # the cookie lives exactly as long as the state it is bound to
BROWSER_SECRET_BYTES = 32
_EXP_RE = re.compile(r"^[0-9]{1,12}$")  # the ASCII digits of a unix timestamp — `str.isdigit()` would admit '²' or '١', which `int()` rejects or misreads


def b64url_encode(data: bytes) -> str:
    """Base64url without padding (the JWT / state alphabet)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    """Inverse of :func:`b64url_encode`; padding restored; ``ValueError`` on a malformed string (the strict ``rsa_verify`` decoder)."""
    if not isinstance(text, str) or text != text.strip():
        raise ValueError("malformed base64url")
    return rsa_verify.b64url_decode(text)


def safe_next(value: str | None) -> str:
    """The ``next`` a start endpoint may carry into the state: a same-origin path starting with a single ``/`` (no ``//``, no scheme, no
    ``\\``) is kept, anything else becomes ``/``."""
    if not isinstance(value, str) or not value or len(value) > NEXT_MAX_LEN:
        return "/"
    if not value.startswith("/") or value.startswith("//") or "\\" in value or ":" in value.split("?", 1)[0].split("#", 1)[0]:
        return "/"  # `//evil`, `/\\evil` and `/x:y` are the spellings browsers turn into another origin or scheme
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F or ch.isspace() for ch in value):
        return "/"  # no control characters, no whitespace (header injection, broken redirects)
    return value


def new_nonce() -> str:
    """:data:`NONCE_HEX_LEN` hex chars for the Apple ``nonce`` (also stored in the state payload)."""
    return secrets.token_hex(NONCE_HEX_LEN // 2)


def new_browser_secret() -> str:
    """The ``wd_oauth`` cookie value of one QQ / Apple flow: :data:`BROWSER_SECRET_BYTES` random bytes, urlsafe (43 chars, no padding)."""
    return secrets.token_urlsafe(BROWSER_SECRET_BYTES)


def browser_hash(secret: str) -> str:
    """``sha256(secret)`` hex — what the signed state and the grant carry as ``bh`` (the raw secret lives only in the browser's cookie)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def grant_hash(grant: str) -> str:
    """``sha256(grant)`` hex — the last segment of the ``kv`` key (the raw grant is never stored)."""
    return hashlib.sha256(grant.encode("utf-8")).hexdigest()


def _state_mac(cfg: Settings, provider: str, exp: int, body: str) -> str:
    return hmac.new(cfg.secret_key.encode("utf-8"), f"{provider}:{exp}.{body}".encode("utf-8"), hashlib.sha256).hexdigest()


def sign(cfg: Settings, provider: str, payload: dict[str, Any], now: datetime) -> str:
    """The signed state for ``provider`` (``'qq'`` / ``'apple'``): ``f"{exp}.{b64url(json)}.{hmac_hex}"`` with ``exp = int(now) +
    STATE_TTL_S`` and the HMAC over ``f'{provider}:{exp}.{b64url}'`` keyed by ``WD_SECRET_KEY`` (``json`` with sorted keys, compact)."""
    exp = int(now.timestamp()) + STATE_TTL_S
    body = b64url_encode(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8"))
    return f"{exp}.{body}.{_state_mac(cfg, provider, exp, body)}"


def verify(cfg: Settings, provider: str, state: str, now: datetime) -> dict[str, Any]:
    """The payload of a state :func:`sign` produced for ``provider`` that has not expired; ``ApiError('invalid_identity_token')`` on any
    failure (an ASCII string of at most :data:`STATE_MAX_LEN` chars, three dotted parts, an ``exp`` of 1–12 ASCII digits, a constant-time
    HMAC compare on bytes, ``exp > now``, a valid JSON object). A genuine state is ASCII by construction (digits, the base64url alphabet,
    hex), so nothing a browser legitimately carries is refused by the character checks; whatever else arrives — full-width digits, a
    non-ASCII hex char, an oversized part — is refused here and never surfaces as a ``ValueError`` / ``TypeError`` (an HTTP 500) out
    of the public callbacks."""
    if not isinstance(state, str) or not state or len(state) > STATE_MAX_LEN or not state.isascii():
        raise ApiError("invalid_identity_token")
    parts = state.split(".")
    if len(parts) != 3:
        raise ApiError("invalid_identity_token")
    exp_text, body, mac = parts
    if not _EXP_RE.fullmatch(exp_text) or not body or not mac:
        raise ApiError("invalid_identity_token")
    try:
        exp = int(exp_text)
        expected = _state_mac(cfg, provider, exp, body)
        if not hmac.compare_digest(mac.encode("ascii"), expected.encode("ascii")):
            raise ApiError("invalid_identity_token")
        if exp <= int(now.timestamp()):
            raise ApiError("invalid_identity_token")
        payload = json.loads(b64url_decode(body).decode("utf-8"))
    except ApiError:
        raise
    except (ValueError, TypeError, UnicodeError, binascii.Error) as e:  # a malformed part of any kind: refused, never a traceback
        raise ApiError("invalid_identity_token") from e
    if not isinstance(payload, dict):
        raise ApiError("invalid_identity_token")
    return payload


def issue_grant(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    provider: str,
    subject: str,
    kind: str,
    uid: int | None,
    invite: str | None,
    next: str,
    bh: str,
    now: datetime,
    nonce: str | None = None,
) -> str:
    """Write ``kv["oauth_grant:<exp iso>:<sha256(grant)>"] = json {provider, subject, kind, uid (bind only), invite, next, bh, nonce (when
    given)}`` (``exp = now + GRANT_TTL_S``) and return the raw grant (:data:`GRANT_BYTES` urlsafe random bytes) the callback puts into
    the 302 to endpoint 122. The callback has verified the provider by now (``subject`` = the openid / Apple ``sub``) but written
    nothing else: the login / bind itself happens at 122, for the browser whose ``wd_oauth`` cookie hashes to ``bh`` (and, for a bind,
    whose session belongs to ``uid``). Called inside the caller's transaction (``db.maybe_tx``)."""
    if provider not in GRANT_PROVIDERS:
        raise ValueError(f"unknown grant provider {provider!r}")
    if kind not in STATE_KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    if kind == "bind" and uid is None:
        raise ValueError("a bind grant needs uid")
    grant = secrets.token_urlsafe(GRANT_BYTES)
    exp_iso = to_iso(now + timedelta(seconds=GRANT_TTL_S))
    key = f"{GRANT_KEY_PREFIX}{exp_iso}:{grant_hash(grant)}"
    payload: dict[str, Any] = {
        "provider": provider,
        "subject": str(subject),
        "kind": kind,
        "invite": invite if kind == "login" and invite else None,
        "next": safe_next(next),
        "bh": str(bh),
    }
    if kind == "bind":
        payload["uid"] = int(uid)  # type: ignore[arg-type]  # checked above
    if nonce is not None:
        payload["nonce"] = str(nonce)
    value = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    with db.maybe_tx(conn):
        db.kv_set(conn, key, value, now=to_iso(now))
    return grant


def redeem_grant(conn: sqlite3.Connection, grant: str, now: datetime) -> dict[str, Any] | None:
    """The payload of a live grant, deleting its ``kv`` row in the same ``BEGIN IMMEDIATE`` (single use); None when the grant is unknown,
    already used or its embedded expiry has passed (endpoint 122 → 302 ``/login?error=invalid_grant``)."""
    if not isinstance(grant, str) or not grant or len(grant) > 128:
        return None
    suffix = ":" + grant_hash(grant)
    with db.maybe_tx(conn):
        rows = conn.execute("SELECT key, value FROM kv WHERE key LIKE ? AND key LIKE ?", (GRANT_KEY_PREFIX + "%", "%" + suffix)).fetchall()
        if not rows:
            return None
        row = rows[0]
        conn.execute("DELETE FROM kv WHERE key = ?", (str(row["key"]),))  # single use, whatever happens next
        key = str(row["key"])
        exp_iso = key[GRANT_KEY_EXPIRY_START - 1 : GRANT_KEY_EXPIRY_START - 1 + GRANT_KEY_EXPIRY_LEN]
        if exp_iso <= to_iso(now):
            return None
        try:
            payload = json.loads(str(row["value"]))
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None


def gc_grants(conn: sqlite3.Connection, now: datetime) -> int:
    """``DELETE FROM kv WHERE key LIKE 'oauth_grant:%' AND substr(key, 13, 20) < ?`` with ``now`` as ISO; returns the count (hourly GC)."""
    with db.maybe_tx(conn):
        cur = conn.execute(
            f"DELETE FROM kv WHERE key LIKE ? AND substr(key, {GRANT_KEY_EXPIRY_START}, {GRANT_KEY_EXPIRY_LEN}) < ?",
            (GRANT_KEY_PREFIX + "%", to_iso(now)),
        )
    return int(cur.rowcount)


__all__ = [
    "BROWSER_SECRET_BYTES",
    "GRANT_BYTES",
    "GRANT_KEY_EXPIRY_LEN",
    "GRANT_KEY_EXPIRY_START",
    "GRANT_KEY_PREFIX",
    "GRANT_PROVIDERS",
    "GRANT_TTL_S",
    "NEXT_MAX_LEN",
    "NONCE_HEX_LEN",
    "OAUTH_COOKIE",
    "OAUTH_COOKIE_PATH",
    "OAUTH_COOKIE_TTL_S",
    "STATE_KINDS",
    "STATE_MAX_LEN",
    "STATE_TTL_S",
    "b64url_decode",
    "b64url_encode",
    "browser_hash",
    "gc_grants",
    "grant_hash",
    "issue_grant",
    "new_browser_secret",
    "new_nonce",
    "redeem_grant",
    "safe_next",
    "sign",
    "verify",
]
