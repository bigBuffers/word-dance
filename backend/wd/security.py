"""Accounts and security primitives (WP2 — DESIGN §4 onboarding gate, §6.1–6.2, §10; API.md §3–4; SCHEMA §2).

* **Passwords**: bcrypt cost :data:`BCRYPT_ROUNDS` (12), 8–64 chars, not equal to the username, not in the shipped
  1k common-password list (``data/common_passwords.txt``); unknown users are verified against a dummy hash of
  the same cost so login timing does not reveal whether a username exists.
* **Sessions**: ``secrets.token_urlsafe(32)`` in cookie ``wd_session`` (``HttpOnly; SameSite=Lax; Path=/;
  Max-Age=WD_SESSION_DAYS``, ``Secure`` per ``WD_COOKIE_SECURE`` / https), DB stores ``sha256(token)``
  (``deps.hash_token``), at most :data:`MAX_SESSIONS_PER_USER` per user, expired rows GC'd on login
  (:func:`gc_sessions` is also callable from the hourly scheduler GC).
* **Throttle / lockout** (persistent ``auth_throttle`` rows): fixed windows (:func:`rate_limit`; :func:`throttle_check` reads a
  window without counting — the failures-only ``login:ip`` rule) and the login lockout schedule — 10 failures per identifier
  **and client IP** (``login:user:<identifier>:<ip>`` with the identifier in its canonical form, :func:`canonical_identifier`:
  E.164 for a phone, NFKC lower-case for an e-mail, lower-case for a username — docs/AUTH_SIGNUP_DESIGN.md §5.3: a stranger cannot
  lock a name from elsewhere, another spelling of the same number is the same key; ``wd unlock`` clears every IP) → 15 min,
  doubling every further 5 failures, max 24 h, reset on success.
  :func:`verify_account_password` gives the password re-checks of API.md 7–8 their own budget (10 per 15 min per
  user) and :func:`throttle_mutation` is DESIGN §10's 300 mutations/min per user (called from ``deps.current_user``).
* **Invite codes**: shown once, stored as ``sha256``; consumed atomically with the SCHEMA.sql UPDATE.
* **Verification codes** (``login_codes``, AUTH_SIGNUP_DESIGN §5.1 / API.md §3.1): 6 digits, :data:`LOGIN_CODE_TTL_S` (10 min),
  :data:`LOGIN_CODE_MAX_ATTEMPTS` (5), ``code_hash = HMAC-SHA256(WD_SECRET_KEY, code:channel:target:purpose)``; a new code voids
  the older unused codes of its (channel, target, purpose); :func:`verify_login_code` only checks — the lookup, the compare and the
  attempt count share one ``BEGIN IMMEDIATE`` of their own, so concurrent wrong guesses cannot exceed the 5 — and the caller consumes
  the row with :func:`mark_login_code_used` inside its own ``BEGIN IMMEDIATE``.
  The stale-phone challenge token (§5.3) lives in the same table as ``purpose = 'challenge'``. The pre-0018 ``email_codes`` table
  stays in the schema but is no longer written or read: the e-mail binding code of API.md 9 / 10 is a ``purpose = 'bind_email'`` row.
* **Identities** (``identities``): :func:`phone_identity` / :func:`identity_by_subject` read the live (undisputed) rows; phone numbers
  are E.164 through :func:`normalize_phone` and shown masked (:func:`mask_phone`, :func:`mask_email`) — never logged.
* :func:`is_safe_https_url`: the webhook host check (https, no raw IPs, no local names).
* Row → DTO helpers (:func:`user_dto` / :func:`user_dto_for` with ``has_password`` / ``phone_masked`` / ``needs_profile`` / ``age_band`` and,
  slice 1-B, ``account_kind`` / ``is_child`` / ``needs_profile_prompt`` — the last one needs ``now`` for the 30-day snooze of the legacy
  prompt, API.md §9.1) and :func:`create_user` (user + ``user_settings`` with ``next_push_at`` from the defaults, inside the caller's
  ``BEGIN IMMEDIATE``; the child columns of ``wd.family.create_child`` join the same INSERT; :func:`placeholder_username` +
  :func:`unusable_password_hash` for a code-created account) shared by the routers.
* CLI ``create-admin | set-password | promote | demote | invite | unlock | sms-probe`` (:func:`register_cli`, DEPLOY §9).
"""

from __future__ import annotations

import argparse
import functools
import getpass
import hashlib
import hmac
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import bcrypt
from fastapi import Request, Response

from . import db
from .clock import SYSTEM_CLOCK, compute_next_push, parse_iso, to_iso
from .config import ConfigError, Settings, ensure_dirs
from .deps import SESSION_COOKIE, hash_token
from .errors import ApiError
from .schemas import USERNAME_RE, index_to_stage
from .services import bank

log = logging.getLogger("wd.security")

# ------------------------------------------------------------------------------------ constants
BCRYPT_ROUNDS = 12  # DESIGN §10 "bcrypt cost 12"; tests lower it (hashes verify at their own embedded cost)
BCRYPT_MAX_BYTES = 72  # bcrypt's input limit: bcrypt 5 raises instead of truncating silently, so we truncate here
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 64
COMMON_PASSWORDS_PATH = Path(__file__).resolve().parent / "data" / "common_passwords.txt"

MAX_SESSIONS_PER_USER = 20

INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # unambiguous upper-case letters + digits (matches ^[A-Z0-9-]{10,}$)
INVITE_GROUPS = 4
INVITE_GROUP_LEN = 4

# verification codes — docs/AUTH_SIGNUP_DESIGN.md §5.1 / §5.3, API.md §3.1 (endpoints 9, 80–91)
LOGIN_CODE_TTL_S = 600  # every channel and purpose: 10 minutes (the SMS template's `min` and the mail text name the same number)
LOGIN_CODE_MAX_ATTEMPTS = 5  # wrong guesses that burn a code
LOGIN_CODE_CHANNELS = ("phone", "email")  # login_codes.channel CHECK (0018)
LOGIN_CODE_PURPOSES = ("login", "reset_password", "bind_phone", "bind_email", "rebind_phone", "reauth", "challenge")  # login_codes.purpose CHECK
CHALLENGE_TTL_S = LOGIN_CODE_TTL_S  # the stale-phone challenge token (purpose 'challenge')
CODE_SEND_TARGET_LIMITS = ((1, 60), (5, 3600), (10, 86400))  # per target: keys code_send:target:<t>:m / :h / :d
CODE_SEND_TARGET_SUFFIXES = ("m", "h", "d")
CODE_SEND_PREFIX_LIMIT, CODE_SEND_PREFIX_WINDOW_S = 5, 3600  # per 7-digit mainland prefix (号段): code_send:prefix:<1380013>
CODE_CHECK_TARGET_LIMIT, CODE_CHECK_TARGET_WINDOW_S = 20, 3600  # code verifications per target: code_check:target:<t>
CODE_CHECK_IP_LIMIT, CODE_CHECK_IP_WINDOW_S = 60, 3600  # code verifications per client IP: code_check:ip:<ip>
CAPTCHA_IP_LIMIT, CAPTCHA_IP_WINDOW_S = 60, 3600  # GET /api/auth/captcha per client IP: captcha:ip:<ip>
PLACEHOLDER_USERNAME_RE = re.compile(r"^u_[a-z2-7]{8}$")  # the username a code-created account gets until endpoint 89 (User.needs_profile)
PLACEHOLDER_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"  # lower-case base32: satisfies schemas.USERNAME_RE, distinct from the invite alphabet
PHONE_RE = re.compile(r"^(?:\+?86)?(1\d{10})$")  # a mainland mobile number after the separators are dropped (+86 / 86 optional)
PROFILE_PROMPT_SNOOZE_DAYS = 30  # the legacy 「补充信息」 prompt (API.md 110 / 111, slice 1-B): skipped → shown again after 30 days (wd.family re-exports it)
ACCOUNT_KINDS = ("learner", "guardian")  # users.account_kind CHECK (0018)

# DESIGN §10 "Throttling"
LOGIN_IP_LIMIT, LOGIN_IP_WINDOW_S = 20, 600
REGISTER_IP_LIMIT, REGISTER_IP_WINDOW_S = 5, 3600
EMAIL_CODE_LIMIT, EMAIL_CODE_WINDOW_S = 3, 3600
TEST_SEND_LIMIT, TEST_SEND_WINDOW_S = 1, 600  # webhook / e-mail test sends: 1 per 10 min
PASSWORD_CHECK_LIMIT, PASSWORD_CHECK_WINDOW_S = 10, 900  # re-checks of the account password (API.md 7–8), per user
MUTATION_LIMIT, MUTATION_WINDOW_S = 300, 60  # every authenticated non-GET request, per user
LOCKOUT_AFTER = 10
LOCKOUT_STEP = 5
LOCKOUT_BASE_S = 15 * 60
LOCKOUT_MAX_S = 24 * 3600
LOCKOUT_RESET_S = 24 * 3600  # a failure streak older than this (and not locked) starts over

DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_PUSH_TIME = "08:00"

SETTINGS_BOOL_COLUMNS = ("push_enabled", "show_images", "auto_pronounce", "email_enabled", "webhook_enabled")

_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home", ".arpa", ".test", ".example", ".invalid", ".intranet", ".corp")
_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


# ------------------------------------------------------------------------------------ passwords
def _password_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """bcrypt ``$2b$<rounds>$…`` at :data:`BCRYPT_ROUNDS`."""
    return bcrypt.hashpw(_password_bytes(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


_DUMMY_HASHES: dict[int, str] = {}


def dummy_hash() -> str:
    """A hash of a random secret at the current cost — verified against for unknown usernames (constant work)."""
    h = _DUMMY_HASHES.get(BCRYPT_ROUNDS)
    if h is None:
        h = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")
        _DUMMY_HASHES[BCRYPT_ROUNDS] = h
    return h


def verify_password(password: str, password_hash: str | None) -> bool:
    """True iff ``password`` matches ``password_hash``; ``None`` (unknown user) still costs one bcrypt check."""
    target = password_hash if password_hash else dummy_hash()
    try:
        ok = bcrypt.checkpw(_password_bytes(password), target.encode("ascii"))
    except ValueError:  # malformed stored hash
        ok = False
    return bool(ok) and password_hash is not None


@functools.lru_cache(maxsize=1)
def common_passwords() -> frozenset[str]:
    """The shipped list, lower-case (blank lines and ``#`` comments ignored)."""
    entries: set[str] = set()
    with COMMON_PASSWORDS_PATH.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip().lower()
            if s and not s.startswith("#"):
                entries.add(s)
    return frozenset(entries)


def password_problem(password: str, username: str | None = None) -> str | None:
    """The zh reason a password is refused (DESIGN §10 rule set), or None when it is acceptable."""
    if len(password) < PASSWORD_MIN_LEN:
        return f"密码至少 {PASSWORD_MIN_LEN} 位"
    if len(password) > PASSWORD_MAX_LEN:
        return f"密码不超过 {PASSWORD_MAX_LEN} 个字符"
    if username and password.strip().lower() == username.strip().lower():
        return "密码不能与用户名相同"
    if password.lower() in common_passwords():
        return "该密码过于常见，请换一个"
    return None


def check_password(password: str, username: str | None = None) -> None:
    """Raise 400 ``weak_password`` (``details.reason``) when the policy refuses ``password``."""
    problem = password_problem(password, username)
    if problem:
        raise ApiError("weak_password", details={"reason": problem})


# ------------------------------------------------------------------------------------- sessions
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def _trim_sessions(conn: sqlite3.Connection, user_id: int) -> None:
    """Make room for one more session: drop the oldest rows beyond :data:`MAX_SESSIONS_PER_USER` − 1."""
    count = int(conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (user_id,)).fetchone()[0])
    excess = count - (MAX_SESSIONS_PER_USER - 1)
    if excess > 0:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash IN ("
            "SELECT token_hash FROM sessions WHERE user_id = ? ORDER BY last_seen_at, created_at, token_hash LIMIT ?)",
            (user_id, excess),
        )


def create_session(
    conn: sqlite3.Connection,
    user_id: int,
    now: datetime,
    *,
    session_days: int,
    user_agent: str | None = None,
    ip: str | None = None,
    actor_user_id: int | None = None,
) -> str:
    """Insert a fresh session row (a new token every time — no fixation) and return the raw cookie value.

    ``actor_user_id`` (0018, slice 1-B) names the guardian who issued a child's session; None = the user logged in themselves.
    """
    token = new_session_token()
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        _trim_sessions(conn, user_id)
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, created_at, expires_at, last_seen_at, user_agent, ip, actor_user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (hash_token(token), user_id, now_iso, to_iso(now + timedelta(days=session_days)), now_iso, (user_agent or "")[:200] or None, ip, actor_user_id),
        )
    return token


def delete_session(conn: sqlite3.Connection, token_hash: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))


def delete_sessions(conn: sqlite3.Connection, user_id: int, *, keep_token_hash: str | None = None) -> int:
    """Revoke the user's sessions (all of them, or all but ``keep_token_hash``); returns rows deleted."""
    if keep_token_hash is None:
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    else:
        cur = conn.execute("DELETE FROM sessions WHERE user_id = ? AND token_hash != ?", (user_id, keep_token_hash))
    return cur.rowcount


def gc_sessions(conn: sqlite3.Connection, now: str) -> int:
    """Delete expired sessions (``now`` ISO); called on login and usable from the scheduler's hourly GC."""
    return conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,)).rowcount


def cookie_secure(request: Request, cfg: Settings) -> bool:
    """``WD_COOKIE_SECURE``: ``1`` forces, ``0`` disables, ``auto`` = https ``WD_PUBLIC_URL`` or an https request
    (direct, or ``X-Forwarded-Proto: https`` behind a trusted proxy — DEPLOY §7)."""
    if cfg.cookie_secure == "1":
        return True
    if cfg.cookie_secure == "0":
        return False
    if cfg.public_url_is_https or request.url.scheme == "https":
        return True
    if cfg.trust_proxy:
        proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if proto == "https":
            return True
    return False


def set_session_cookie(response: Response, token: str, cfg: Settings, *, secure: bool, max_age_s: int | None = None) -> None:
    """The ``wd_session`` cookie; ``max_age_s`` overrides ``WD_SESSION_DAYS`` — the 90-day child-device session of endpoint 107 and the
    sliding re-issue of ``main.WdMiddleware`` (the seconds left on a session the slide did not shorten, slice 1-B)."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=int(max_age_s) if max_age_s is not None else cfg.session_days * 86400,
        path="/",
        httponly=True,
        samesite="lax",
        secure=secure,
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(key=SESSION_COOKIE, path="/", httponly=True, samesite="lax", secure=secure)


# ------------------------------------------------------------------------------- throttle / lockout
def _throttle_row(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT key, window_start, count, blocked_until FROM auth_throttle WHERE key = ?", (key,)).fetchone()


def throttle_hit(conn: sqlite3.Connection, key: str, *, limit: int, window_s: int, now: datetime) -> int | None:
    """Count one attempt in the fixed window of ``key``.

    Returns ``None`` when the attempt is allowed (and counted), else the seconds until the window resets
    (the attempt is not counted). Rows persist, so limits survive restarts (DESIGN §10).
    """
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        row = _throttle_row(conn, key)
        if row is not None:
            window_start = parse_iso(str(row["window_start"]))
            window_end = window_start + timedelta(seconds=window_s)
            if window_end > now:
                if int(row["count"]) >= limit:
                    return max(1, math.ceil((window_end - now).total_seconds()))
                conn.execute("UPDATE auth_throttle SET count = count + 1 WHERE key = ?", (key,))
                return None
        conn.execute(
            "INSERT INTO auth_throttle(key, window_start, count, blocked_until) VALUES (?, ?, 1, NULL) "
            "ON CONFLICT(key) DO UPDATE SET window_start = excluded.window_start, count = 1, blocked_until = NULL",
            (key, now_iso),
        )
    return None


def rate_limit(conn: sqlite3.Connection, key: str, *, limit: int, window_s: int, now: datetime) -> None:
    """Raise 429 ``rate_limited`` (``details.retry_after_s``, ``Retry-After``) when ``key`` is over its limit."""
    retry = throttle_hit(conn, key, limit=limit, window_s=window_s, now=now)
    if retry is not None:
        raise ApiError("rate_limited", details={"retry_after_s": retry})


def throttle_check(conn: sqlite3.Connection, key: str, *, limit: int, window_s: int, now: datetime) -> int | None:
    """Like :func:`throttle_hit` but WITHOUT counting: the seconds until ``key``'s window resets while it sits at its limit, else None.

    The failures-only ``login:ip`` rule (API.md 3, AUTH_SIGNUP_DESIGN §5.3): check before verifying, count with :func:`throttle_hit`
    on the failure path only — a legitimate user's successful logins never spend the window.
    """
    row = _throttle_row(conn, key)
    if row is None:
        return None
    window_end = parse_iso(str(row["window_start"])) + timedelta(seconds=window_s)
    if window_end > now and int(row["count"]) >= limit:
        return max(1, math.ceil((window_end - now).total_seconds()))
    return None


def canonical_identifier(identifier: str) -> str:
    """The one spelling of a login identifier (API.md 3): a mainland mobile number in any accepted form → E.164 (:func:`normalize_phone`),
    an e-mail (contains ``@``) → NFKC, lower-cased, anything else (a username) → lower-cased — the three branches of
    ``routers/auth.resolve_identifier``, so the lockout bucket and ``wd unlock`` agree with the account lookup: 「138 0013 8000」,
    ``+8613800138000`` and ``8613800138000`` share one key, ``ｂob@Example.com`` and ``bob@example.com`` too. A digits-only
    username that reads as a phone number shares the bucket of that number (acceptable: the schema refuses new ones)."""
    ident = (identifier or "").strip()
    e164 = normalize_phone(ident)
    if e164 is not None:
        return e164
    if "@" in ident:
        return unicodedata.normalize("NFKC", ident).lower()
    return ident.lower()


def lockout_key(identifier: str, ip: str) -> str:
    """``login:user:<identifier>:<ip>`` — the lockout is per identifier (its canonical form, :func:`canonical_identifier`: E.164 phone /
    NFKC lower-case e-mail / lower-case username) *and* client IP (AUTH_SIGNUP_DESIGN §5.3, PUBLIC_LAUNCH A4): a stranger's guesses
    never lock the account's owner out, and respelling a phone number does not open a fresh bucket; ``wd unlock`` deletes every IP's
    row of an identifier."""
    return f"login:user:{canonical_identifier(identifier)}:{ip}"


def lockout_remaining(conn: sqlite3.Connection, identifier: str, now: datetime, *, ip: str) -> int | None:
    """Seconds until the (identifier, ip) lockout ends, or None when it is not locked."""
    row = _throttle_row(conn, lockout_key(identifier, ip))
    if row is None or not row["blocked_until"]:
        return None
    until = parse_iso(str(row["blocked_until"]))
    if until <= now:
        return None
    return max(1, math.ceil((until - now).total_seconds()))


def check_lockout(conn: sqlite3.Connection, identifier: str, now: datetime, *, ip: str) -> None:
    """Raise 423 ``account_locked`` (``details.retry_after_s``) while (identifier, ip) is locked."""
    remaining = lockout_remaining(conn, identifier, now, ip=ip)
    if remaining is not None:
        raise ApiError("account_locked", details={"retry_after_s": remaining})


def lock_seconds_for(failures: int) -> int | None:
    """Lockout applied by the ``failures``-th consecutive failure: 15 min at 10, doubling every 5 more, max 24 h."""
    if failures < LOCKOUT_AFTER or (failures - LOCKOUT_AFTER) % LOCKOUT_STEP:
        return None
    return min(LOCKOUT_BASE_S * 2 ** ((failures - LOCKOUT_AFTER) // LOCKOUT_STEP), LOCKOUT_MAX_S)


def record_login_failure(conn: sqlite3.Connection, identifier: str, now: datetime, *, ip: str) -> int | None:
    """Count a failed login for (identifier, ip); returns the lockout seconds when this failure starts a lock."""
    key = lockout_key(identifier, ip)
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        row = _throttle_row(conn, key)
        count = 0
        window_start = now_iso
        if row is not None:
            stale = parse_iso(str(row["window_start"])) + timedelta(seconds=LOCKOUT_RESET_S) <= now
            locked = bool(row["blocked_until"]) and parse_iso(str(row["blocked_until"])) > now
            if not stale or locked:
                count = int(row["count"])
                window_start = str(row["window_start"])
        count += 1
        lock_s = lock_seconds_for(count)
        blocked_until = to_iso(now + timedelta(seconds=lock_s)) if lock_s else None
        conn.execute(
            "INSERT INTO auth_throttle(key, window_start, count, blocked_until) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET window_start = excluded.window_start, count = excluded.count, blocked_until = excluded.blocked_until",
            (key, window_start, count, blocked_until),
        )
    if lock_s:
        log.warning("login lockout after %d failures: %d s", count, lock_s, extra={"event": "login_lockout"})  # the identifier may be a phone / e-mail: not logged
    return lock_s


def clear_login_failures(conn: sqlite3.Connection, identifier: str, *, ip: str) -> None:
    conn.execute("DELETE FROM auth_throttle WHERE key = ?", (lockout_key(identifier, ip),))


def unlock_identifier(conn: sqlite3.Connection, identifier: str) -> int:
    """Delete every lockout row of ``identifier`` (``login:user:<identifier>:<ip>`` for every IP, plus a pre-0018 row without the
    IP) — ``wd unlock``; the identifier is canonicalised like :func:`lockout_key`, so any spelling of the number / address the learner
    typed finds the rows; returns the rows removed."""
    ident = canonical_identifier(identifier)
    prefix = f"login:user:{ident}:"
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with db.maybe_tx(conn):
        cur = conn.execute("DELETE FROM auth_throttle WHERE key = ? OR key LIKE ? ESCAPE '\\'", (f"login:user:{ident}", escaped + "%"))
    return int(cur.rowcount)


def password_check_key(user_id: int) -> str:
    return f"pwcheck:user:{int(user_id)}"


def verify_account_password(conn: sqlite3.Connection, user: Mapping[str, Any], password: str, *, now: datetime) -> None:
    """Re-check the logged-in user's password before a sensitive action (API.md 7 change password, 8 delete account).

    The login lockout guards ``/api/auth/login`` only, so these checks get their own budget: more than
    :data:`PASSWORD_CHECK_LIMIT` attempts per :data:`PASSWORD_CHECK_WINDOW_S` per user → 429 ``rate_limited``
    (``details.retry_after_s``), which bounds online guessing with a stolen session cookie to a few attempts and
    keeps the single process from burning a bcrypt check per guess. A wrong password raises 401
    ``invalid_credentials`` and stays counted — call this **outside** any open transaction (like
    :func:`verify_login_code`) so the caller's rollback cannot undo the count; a correct password clears the counter,
    so a few typos never lock a legitimate user out of their own account page.
    """
    key = password_check_key(int(user["id"]))
    retry = throttle_hit(conn, key, limit=PASSWORD_CHECK_LIMIT, window_s=PASSWORD_CHECK_WINDOW_S, now=now)
    if retry is not None:
        log.warning("password re-check throttled for user %s", user["id"], extra={"event": "password_check_throttled", "user_id": user["id"]})
        raise ApiError("rate_limited", details={"retry_after_s": retry})
    if not verify_password(password, user["password_hash"]):
        raise ApiError("invalid_credentials")
    conn.execute("DELETE FROM auth_throttle WHERE key = ?", (key,))


def mutation_key(user_id: int) -> str:
    return f"mutate:user:{int(user_id)}"


def throttle_mutation(conn: sqlite3.Connection, user_id: int, now: datetime) -> None:
    """DESIGN §10 "mutations 300/min per user": count one authenticated non-GET request; 429 ``rate_limited`` over the limit."""
    rate_limit(conn, mutation_key(user_id), limit=MUTATION_LIMIT, window_s=MUTATION_WINDOW_S, now=now)


# --------------------------------------------------------------------------------- invite codes
def generate_invite_code() -> str:
    """``XXXX-XXXX-XXXX-XXXX`` over :data:`INVITE_ALPHABET` (80 bits), matching ``^[A-Z0-9-]{10,}$``."""
    return "-".join("".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_GROUP_LEN)) for _ in range(INVITE_GROUPS))


def normalise_invite_code(code: str) -> str:
    return re.sub(r"\s+", "", code or "").upper()


def hash_invite_code(code: str) -> str:
    return hashlib.sha256(normalise_invite_code(code).encode("ascii", "ignore")).hexdigest()


def create_invite(
    conn: sqlite3.Connection,
    *,
    created_by: int | None,
    max_uses: int = 1,
    expires_in_days: int | None = None,
    note: str | None = None,
    now: datetime,
) -> tuple[int, str, str | None]:
    """Insert a hashed invite; returns ``(id, code, expires_at)`` — the code is shown exactly once."""
    if max_uses < 1:
        raise ValueError("max_uses must be >= 1")
    code = generate_invite_code()
    expires_at = to_iso(now + timedelta(days=expires_in_days)) if expires_in_days else None
    cur = conn.execute(
        "INSERT INTO invite_codes(code_hash, created_by, max_uses, uses, expires_at, note, created_at) VALUES (?, ?, ?, 0, ?, ?, ?)",
        (hash_invite_code(code), created_by, max_uses, expires_at, (note or "").strip(), to_iso(now)),
    )
    return int(cur.lastrowid), code, expires_at


def consume_invite(conn: sqlite3.Connection, code: str, now: datetime) -> bool:
    """The SCHEMA.sql atomic consumption: exactly one row must change."""
    if not normalise_invite_code(code):
        return False
    cur = conn.execute(
        "UPDATE invite_codes SET uses = uses + 1 WHERE code_hash = ? AND uses < max_uses AND (expires_at IS NULL OR expires_at > ?)",
        (hash_invite_code(code), to_iso(now)),
    )
    return cur.rowcount == 1


def list_invites(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, max_uses, uses, expires_at, note, created_at, created_by FROM invite_codes ORDER BY id DESC").fetchall()
    return [
        {
            "id": int(r["id"]),
            "max_uses": int(r["max_uses"]),
            "uses": int(r["uses"]),
            "expires_at": r["expires_at"],
            "note": r["note"] or "",
            "created_at": r["created_at"],
            "created_by": int(r["created_by"]) if r["created_by"] is not None else None,
        }
        for r in rows
    ]


# ------------------------------------------------------------------- verification codes (login_codes, 0018)
def normalize_phone(raw: str) -> str | None:
    """A mainland mobile number as E.164 (``+86`` + 11 digits) from what the learner typed, or None.

    Spaces, dashes and parentheses are dropped; ``1xxxxxxxxxx``, ``+861…``, ``861…`` and ``00861…`` are accepted; anything else
    (a foreign number, 10 digits, a landline) is None → 400 ``invalid_phone`` at the endpoints (API.md 80).
    """
    s = re.sub(r"[\s\-()（）]", "", raw or "")
    if s.startswith("00"):
        s = "+" + s[2:]
    m = PHONE_RE.match(s)
    return f"+86{m.group(1)}" if m else None


def phone_prefix(e164: str) -> str:
    """The first 7 digits after ``+86`` (the 号段 of the per-prefix send throttle): ``+8613800138000`` → ``1380013``."""
    return e164[3:10] if e164.startswith("+86") else re.sub(r"\D", "", e164)[:7]


def mask_phone(e164: str) -> str:
    """``+8613800138000`` → ``138****8000`` (API.md §9 ``User.phone_masked``); shorter shapes keep their last four digits only."""
    digits = re.sub(r"\D", "", e164 or "")
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    if len(digits) >= 7:
        return f"{digits[:3]}****{digits[-4:]}"
    return "****" + digits[-4:] if digits else "****"


def mask_email(email: str) -> str:
    """``alice@qq.com`` → ``a***@qq.com`` (API.md §9 ``StaleChallenge.email_masked``)."""
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else f"{local[:1]}***"


def placeholder_username(conn: sqlite3.Connection) -> str:
    """``u_`` + 8 characters of ``a-z2-7`` for a code-created account (matches ``schemas.USERNAME_RE`` and
    :data:`PLACEHOLDER_USERNAME_RE`), regenerated while the name is taken; endpoint 89 lets the learner replace it once."""
    while True:
        name = "u_" + "".join(secrets.choice(PLACEHOLDER_ALPHABET) for _ in range(8))
        if not username_taken(conn, name):
            return name


def unusable_password_hash() -> str:
    """A bcrypt hash of a fresh random secret for an account without a password (``users.password_hash`` is NOT NULL):
    :func:`verify_password` never matches it and still pays one bcrypt check, so a password login against such an account
    is indistinguishable in timing from a wrong password. ``users.password_set_at`` stays NULL (``User.has_password`` false)."""
    return hash_password(secrets.token_urlsafe(32))


def login_code_hash(secret_key: str, code: str, channel: str, target: str, purpose: str) -> str:
    """hex HMAC-SHA256(key = WD_SECRET_KEY, msg = ``code:channel:target:purpose``) — ``login_codes.code_hash`` (0018)."""
    return hmac.new(secret_key.encode("utf-8"), f"{code}:{channel}:{target}:{purpose}".encode("utf-8"), hashlib.sha256).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _store_login_code(
    conn: sqlite3.Connection,
    *,
    channel: str,
    target: str,
    purpose: str,
    user_id: int | None,
    secret: str,
    ip: str | None,
    secret_key: str,
    now: datetime,
    ttl_s: int,
) -> int:
    """Drop the older unused rows of the (channel, target, purpose) triple and insert the new one; returns its id."""
    if channel not in LOGIN_CODE_CHANNELS:
        raise ValueError(f"invalid channel {channel!r}")
    if purpose not in LOGIN_CODE_PURPOSES:
        raise ValueError(f"invalid purpose {purpose!r}")
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        conn.execute("DELETE FROM login_codes WHERE channel = ? AND target = ? AND purpose = ? AND used_at IS NULL", (channel, target, purpose))
        cur = conn.execute(
            "INSERT INTO login_codes(channel, target, purpose, user_id, code_hash, expires_at, attempts, used_at, ip, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)",
            (channel, target, purpose, user_id, login_code_hash(secret_key, secret, channel, target, purpose), to_iso(now + timedelta(seconds=ttl_s)), ip, now_iso),
        )
    return int(cur.lastrowid)


def issue_login_code(
    conn: sqlite3.Connection,
    *,
    channel: str,
    target: str,
    purpose: str,
    user_id: int | None,
    ip: str | None,
    secret_key: str,
    now: datetime,
) -> str:
    """Create a fresh 6-digit code for ``(channel, target, purpose)`` and return it for sending.

    Older unused codes of the same triple are voided (the newest one is the only live one); the row carries ``user_id`` (required
    for bind_* / rebind_phone / reauth, the account for a reset or a challenge e-mail, None for a plain login send) and the
    requester's ``ip``. Runs in its own transaction unless the caller holds one (``db.maybe_tx``); expires after
    :data:`LOGIN_CODE_TTL_S`. The code itself is never stored or logged.
    """
    code = _new_code()
    _store_login_code(conn, channel=channel, target=target, purpose=purpose, user_id=user_id, secret=code, ip=ip, secret_key=secret_key, now=now, ttl_s=LOGIN_CODE_TTL_S)
    return code


def void_login_codes(conn: sqlite3.Connection, *, channel: str, target: str, purpose: str, now: datetime) -> int:
    """Mark the live codes of a triple used (a send that failed after the row was written — API.md 80); returns rows voided."""
    with db.maybe_tx(conn):
        cur = conn.execute(
            "UPDATE login_codes SET used_at = ? WHERE channel = ? AND target = ? AND purpose = ? AND used_at IS NULL",
            (to_iso(now), channel, target, purpose),
        )
    return int(cur.rowcount)


def _live_login_code(conn: sqlite3.Connection, *, channel: str | None, target: str | None, purpose: str, user_id: int | None) -> sqlite3.Row | None:
    if target is None:
        if user_id is None:
            raise ValueError("verify_login_code needs a target or a user_id")
        return conn.execute(
            "SELECT * FROM login_codes WHERE purpose = ? AND user_id = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
            (purpose, user_id),
        ).fetchone()
    sql = "SELECT * FROM login_codes WHERE channel = ? AND target = ? AND purpose = ? AND used_at IS NULL"
    params: list[Any] = [channel, target, purpose]
    if user_id is not None:
        sql += " AND user_id = ?"
        params.append(user_id)
    return conn.execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()


def verify_login_code(
    conn: sqlite3.Connection,
    *,
    channel: str | None,
    target: str | None,
    purpose: str,
    code: str,
    secret_key: str,
    now: datetime,
    user_id: int | None = None,
) -> int:
    """Check ``code`` against the newest live row of ``(channel, target, purpose)`` and return that row's id.

    ``user_id`` narrows the lookup when given (bind_* / rebind_phone / reauth rows belong to the session's user; a reset or
    challenge code to its account); with ``target=None`` the newest live row for ``(purpose, user_id)`` is used whatever its
    channel (endpoint 87: a ``reauth`` code went to the bound phone or the verified e-mail). Raises 400 ``invalid_code`` with
    ``details.attempts_left`` on a wrong code, or ``attempts_left: 0`` when no live code exists / it expired / its attempt budget
    is spent (the code is burnt after :data:`LOGIN_CODE_MAX_ATTEMPTS`).

    The code is **not** consumed here: the caller marks it used with :func:`mark_login_code_used` inside the transaction that
    applies the verified action (a login, a binding, a password), so "verified" and the write commit together (AUTH_SIGNUP_DESIGN
    §5.6 invariant 1). The lookup, the compare and the attempt count run inside ONE ``BEGIN IMMEDIATE`` of their own (``db.maybe_tx``),
    so concurrent wrong guesses are serialised and the 5-attempt budget holds under a flood; a burnt row (``attempts + 1 >=``
    :data:`LOGIN_CODE_MAX_ATTEMPTS`) gets its ``used_at`` in the same statement. Call this **outside** any open transaction: the
    bookkeeping is committed before the error is raised, so a wrong guess always counts whatever the caller does next.
    """
    now_iso = to_iso(now)
    cleaned = (code or "").strip()
    verified: int | None = None
    left = 0
    with db.maybe_tx(conn):
        row = _live_login_code(conn, channel=channel, target=target, purpose=purpose, user_id=user_id)
        if row is not None and str(row["expires_at"]) > now_iso and int(row["attempts"]) < LOGIN_CODE_MAX_ATTEMPTS:
            expected = login_code_hash(secret_key, cleaned, str(row["channel"]), str(row["target"]), purpose)
            if hmac.compare_digest(str(row["code_hash"]), expected):
                verified = int(row["id"])
            else:
                # one statement counts the guess and burns the row at the limit; RETURNING reads the count this guess produced
                counted = conn.execute(
                    "UPDATE login_codes SET attempts = attempts + 1, used_at = CASE WHEN attempts + 1 >= ? THEN ? ELSE used_at END "
                    "WHERE id = ? AND used_at IS NULL RETURNING attempts",
                    (LOGIN_CODE_MAX_ATTEMPTS, now_iso, row["id"]),
                ).fetchone()
                left = max(0, LOGIN_CODE_MAX_ATTEMPTS - int(counted[0])) if counted is not None else 0
    # raised AFTER the block committed: raising inside it would roll the count back
    if verified is None:
        raise ApiError("invalid_code", details={"attempts_left": left})
    return verified


def mark_login_code_used(conn: sqlite3.Connection, row_id: int, now: datetime) -> bool:
    """Consume a verified code inside the caller's transaction; False when it was used meanwhile (a concurrent request won)."""
    cur = conn.execute("UPDATE login_codes SET used_at = ? WHERE id = ? AND used_at IS NULL", (to_iso(now), row_id))
    return cur.rowcount == 1


def load_login_code(conn: sqlite3.Connection, row_id: int) -> dict[str, Any] | None:
    return row_dict(conn.execute("SELECT * FROM login_codes WHERE id = ?", (row_id,)).fetchone())


def issue_challenge_token(conn: sqlite3.Connection, *, target: str, user_id: int, ip: str | None, secret_key: str, now: datetime) -> str:
    """The stale-phone challenge (AUTH_SIGNUP_DESIGN §5.3, API.md 81–84): a ``secrets.token_urlsafe(32)`` token stored as
    ``login_codes(channel='phone', target=<E.164>, purpose='challenge', user_id=<the account the number is bound to>)`` with
    ``code_hash = login_code_hash(token, 'phone', target, 'challenge')``, valid :data:`CHALLENGE_TTL_S`; an earlier live challenge
    for the same number is voided. Returns the token (never stored in clear)."""
    token = secrets.token_urlsafe(32)
    _store_login_code(conn, channel="phone", target=target, purpose="challenge", user_id=user_id, secret=token, ip=ip, secret_key=secret_key, now=now, ttl_s=CHALLENGE_TTL_S)
    return token


def verify_challenge_token(conn: sqlite3.Connection, *, token: str, secret_key: str, now: datetime) -> dict[str, Any]:
    """Resolve a challenge token to its live ``login_codes`` row (``id``, ``user_id``, ``target``, ``created_at`` …) or raise 400
    ``challenge_expired`` (unknown, expired or already used). The token is 256 bits, so the live challenge rows are simply scanned
    with a constant-time compare; the caller consumes the row with :func:`mark_login_code_used` inside its transaction."""
    now_iso = to_iso(now)
    rows = conn.execute(
        "SELECT * FROM login_codes WHERE purpose = 'challenge' AND used_at IS NULL AND expires_at > ? ORDER BY id DESC",
        (now_iso,),
    ).fetchall()
    cleaned = (token or "").strip()
    for row in rows:
        expected = login_code_hash(secret_key, cleaned, str(row["channel"]), str(row["target"]), "challenge")
        if hmac.compare_digest(str(row["code_hash"]), expected):
            return row_dict(row) or {}
    raise ApiError("challenge_expired")


# ------------------------------------------------------------------------------------ identities
def phone_identity(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    """The user's live (undisputed) phone identity row, or None."""
    return row_dict(conn.execute("SELECT * FROM identities WHERE user_id = ? AND provider = 'phone' AND disputed_at IS NULL", (user_id,)).fetchone())


def identity_by_subject(conn: sqlite3.Connection, provider: str, subject: str) -> dict[str, Any] | None:
    """The live (undisputed) identity row holding ``(provider, subject)`` — ``ux_identities_live`` makes it unique — or None."""
    return row_dict(conn.execute("SELECT * FROM identities WHERE provider = ? AND subject = ? AND disputed_at IS NULL", (provider, subject)).fetchone())


# ------------------------------------------------------------------------------- webhook host check
def is_safe_https_url(url: str) -> bool:
    """Webhook URL policy (DESIGN §9/§10): ``https`` only, a real DNS name (no IP literals, no ``localhost``,
    ``.local``, ``.internal`` …), no credentials in the URL.

    This is the save-time check; the sender (WP4 ``safe_post``) additionally pins DNS and refuses private
    addresses on every hop at send time, so a name resolving to a private range is still blocked.
    """
    if not url or len(url) > 2048:
        return False
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False
    if parts.scheme.lower() != "https" or not host:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    if port is not None and not 1 <= port <= 65535:
        return False
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return False  # raw IPv4/IPv6 literals are never allowed
    except ValueError:
        pass
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        return False
    if "." not in host or len(host) > 253:
        return False
    labels = host.split(".")
    if any(not _LABEL_RE.match(label) for label in labels):
        return False
    if labels[-1].isdigit():
        return False
    return True


# ------------------------------------------------------------------------- account rows and DTOs
def row_dict(row: sqlite3.Row | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row) if isinstance(row, Mapping) else {k: row[k] for k in row.keys()}


def load_user(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    return row_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def load_user_by_name(conn: sqlite3.Connection, username: str) -> dict[str, Any] | None:
    """``users.username`` is ``COLLATE NOCASE``, so the lookup is case-insensitive."""
    return row_dict(conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone())


def _column(row: Mapping[str, Any], key: str) -> Any:
    """``row[key]`` or None — a ``sqlite3.Row`` raises IndexError and a dict KeyError for a column the row does not carry."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def needs_profile_prompt(row: Mapping[str, Any], now: datetime | None) -> bool:
    """API.md §9.1 ``User.needs_profile_prompt`` (slice 1-B): a pre-1-A account that has not declared its kind / age band — ``age_band``
    NULL, not a code-created account still in its first-time setup (the placeholder username, ``needs_profile``), not a child — and was
    not snoozed in the last :data:`PROFILE_PROMPT_SNOOZE_DAYS` days (``profile_prompted_at``, endpoint 111). False without ``now``
    (a caller that does not render the prompt)."""
    if now is None or _column(row, "age_band") is not None or _column(row, "guardian_user_id") is not None:
        return False
    if PLACEHOLDER_USERNAME_RE.match(str(row["username"])):
        return False  # endpoint 89 (needs_profile) comes first
    prompted = _column(row, "profile_prompted_at")
    return prompted is None or parse_iso(str(prompted)) <= now - timedelta(days=PROFILE_PROMPT_SNOOZE_DAYS)


def user_dto(row: Mapping[str, Any], *, phone: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """API.md §9 ``User`` from a ``users`` row (``display_name`` defaults to the username).

    ``has_password`` = ``password_set_at IS NOT NULL`` (0018; false for a code-created account until endpoint 89 / 7 sets one),
    ``phone_masked`` = the live phone identity passed as ``phone`` (E.164; :func:`user_dto_for` looks it up), ``needs_profile`` =
    a code-created account (placeholder username) that has not declared its age band yet (endpoint 89), ``age_band`` as declared;
    slice 1-B: ``account_kind`` (``learner`` for a row without the column), ``is_child`` = ``guardian_user_id IS NOT NULL`` and
    ``needs_profile_prompt`` (:func:`needs_profile_prompt`; always False without ``now``).
    """
    username = row["username"]
    return {
        "id": int(row["id"]),
        "username": username,
        "display_name": row["display_name"] or username,
        "email": row["email"],
        "email_verified": row["email_verified_at"] is not None,
        "role": row["role"],
        "onboarding_state": row["onboarding_state"],
        "created_at": row["created_at"],
        "has_password": _column(row, "password_set_at") is not None,
        "phone_masked": mask_phone(phone) if phone else None,
        "needs_profile": _column(row, "age_band") is None and bool(PLACEHOLDER_USERNAME_RE.match(str(username))),
        "age_band": _column(row, "age_band"),
        "account_kind": _column(row, "account_kind") or "learner",
        "is_child": _column(row, "guardian_user_id") is not None,
        "needs_profile_prompt": needs_profile_prompt(row, now),
    }


def user_dto_for(conn: sqlite3.Connection, row: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """:func:`user_dto` with the live phone identity looked up (``phone_masked`` filled) — the form every ``{user}`` response uses;
    routers pass ``now`` so ``needs_profile_prompt`` is computed."""
    identity = phone_identity(conn, int(row["id"]))
    return user_dto(row, phone=str(identity["subject"]) if identity else None, now=now)


def admin_user_dto(row: Mapping[str, Any], *, bank_size: int, streak_days: int, phone: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """API.md §9 ``AdminUser``."""
    dto = user_dto(row, phone=phone, now=now)
    dto.update(
        {
            "is_active": bool(int(row["is_active"])),
            "last_login_at": row["last_login_at"],
            "bank_size": int(bank_size),
            "streak_days": int(streak_days),
        }
    )
    return dto


def load_settings_row(conn: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    return row_dict(conn.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,)).fetchone())


def settings_dto(conn: sqlite3.Connection, user_id: int) -> dict[str, Any]:
    """API.md §9 ``Settings`` (stage index → ``Stage`` string, 0/1 → bool, ``email_verified`` from ``users``)."""
    row = conn.execute(
        "SELECT s.*, u.email_verified_at FROM user_settings s JOIN users u ON u.id = s.user_id WHERE s.user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        raise ApiError("not_found", details={"user_settings": user_id})
    return settings_row_to_dto(row_dict(row) or {})


def settings_row_to_dto(row: Mapping[str, Any]) -> dict[str, Any]:
    # The unknown-code fallback the study paths already apply (bank.known_stages, PLAN §2.1): a stages_json naming no known
    # stage used to fail response validation here — 500 on /api/auth/me and /api/settings, so the SPA could not boot —
    # while /api/today kept working on the fallback; one helper keeps both views on the same stages (impl-review final F2).
    user_id = int(row.get("user_id") or 0)
    stages = bank.known_stages(row.get("stages_json"), user_id=user_id)
    try:
        current_stage = index_to_stage(int(row["current_stage"]))
    except (TypeError, ValueError):
        # an index this build does not know (the DDL CHECK forbids it today; an older server over a newer row could meet one):
        # the user's first target stage keeps `current_stage ∈ stages` true on the wire, and the same event names the row
        current_stage = stages[0]
        log.warning(
            "stage_fallback: user %s current_stage %r is not a known stage index; using %r",
            user_id,
            row.get("current_stage"),
            current_stage,
            extra={"event": "stage_fallback", "user_id": user_id},
        )
    return {
        "timezone": row["timezone"],
        "push_time": row["push_time"],
        "push_enabled": bool(int(row["push_enabled"])),
        "daily_new_count": int(row["daily_new_count"]),
        "daily_screen_count": int(row["daily_screen_count"]),
        "max_reviews": int(row["max_reviews"]),
        "stages": stages,
        "current_stage": current_stage,
        "show_images": bool(int(row["show_images"])),
        "zh_examples": row["zh_examples"],
        "auto_pronounce": bool(int(row["auto_pronounce"])),
        "accent": row["accent"],
        "dance_mode": row.get("dance_mode") or "full",  # 0015 column; the DDL default when a row predates the migration
        "email_enabled": bool(int(row["email_enabled"])),
        "webhook_enabled": bool(int(row["webhook_enabled"])),
        "webhook_url": row["webhook_url"],
        "webhook_format": row["webhook_format"],
        "next_push_at": row["next_push_at"],
        "email_verified": row.get("email_verified_at") is not None,
        "updated_at": row["updated_at"],
    }


def stages_json(stages: list[str]) -> str:
    """``user_settings.stages_json`` in the compact form of the DDL default (``'["xs","zk"]'``, 0011_primary_stage.sql)."""
    return json.dumps(list(stages), separators=(",", ":"))


def next_push_iso(now: datetime, tz: str, push_time: str) -> str:
    """``clock.compute_next_push`` as the stored ISO string (DESIGN §6.1 ``next_push_at``)."""
    return to_iso(compute_next_push(now, tz, push_time))


def username_taken(conn: sqlite3.Connection, username: str) -> bool:
    return conn.execute("SELECT 1 FROM users WHERE username = ?", (username.strip(),)).fetchone() is not None


def email_taken(conn: sqlite3.Connection, email: str, *, exclude_user_id: int | None = None) -> bool:
    if exclude_user_id is None:
        row = conn.execute("SELECT 1 FROM users WHERE email = ?", (email.strip(),)).fetchone()
    else:
        row = conn.execute("SELECT 1 FROM users WHERE email = ? AND id != ?", (email.strip(), exclude_user_id)).fetchone()
    return row is not None


def create_user(
    conn: sqlite3.Connection,
    *,
    username: str,
    password_hash: str,
    now: datetime,
    role: str = "user",
    display_name: str | None = None,
    email: str | None = None,
    password_set_at: str | None,
    email_verified_at: str | None = None,
    account_kind: str = "learner",
    guardian_user_id: int | None = None,
    age_band: str | None = None,
    age_declared_at: str | None = None,
    age_declared_ip: str | None = None,
    guardian_consent_at: str | None = None,
) -> int:
    """Insert ``users`` + ``user_settings`` (``next_push_at`` from the defaults ``Asia/Shanghai`` / ``08:00``).

    ``password_hash`` is pre-computed by the caller (:func:`hash_password`) so the bcrypt work never runs inside
    the write transaction; ``password_set_at`` is ``to_iso(now)`` for a password registration and None for a code-created
    account (``password_hash`` then holds :func:`unusable_password_hash`); ``email_verified_at`` is set when the e-mail itself
    was the verified channel (endpoint 81). The slice 1-B columns join the same INSERT: ``account_kind`` (``guardian`` for the account
    the claim flow creates, endpoint 109), and for a child (``wd.family.create_child``, endpoint 95) ``guardian_user_id``, ``age_band``,
    the declaration stamps and ``guardian_consent_at``. Runs inside the caller's transaction when one is open (registration does the
    bootstrap count check in the same ``BEGIN IMMEDIATE``), otherwise in its own. Uniqueness is pre-checked by
    callers; a racing duplicate surfaces as ``sqlite3.IntegrityError``.
    """
    if role not in ("user", "admin"):
        raise ValueError(f"invalid role {role!r}")
    if account_kind not in ACCOUNT_KINDS:
        raise ValueError(f"invalid account_kind {account_kind!r}")
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        cur = conn.execute(
            "INSERT INTO users(username, email, email_verified_at, display_name, password_hash, password_set_at, role, is_active, onboarding_state, created_at, updated_at, "
            "account_kind, guardian_user_id, age_band, age_declared_at, age_declared_ip, guardian_consent_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)",
            (username.strip(), email, email_verified_at, display_name, password_hash, password_set_at, role, now_iso, now_iso, account_kind, guardian_user_id, age_band, age_declared_at, age_declared_ip, guardian_consent_at),
        )
        user_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO user_settings(user_id, next_push_at, updated_at) VALUES (?, ?, ?)",
            (user_id, next_push_iso(now, DEFAULT_TIMEZONE, DEFAULT_PUSH_TIME), now_iso),
        )
    return user_id


def other_active_admins(conn: sqlite3.Connection, user_id: int) -> int:
    """Active admins other than ``user_id`` (the last-admin guard, DESIGN §10 "Authorisation")."""
    return int(conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1 AND id != ?", (user_id,)).fetchone()[0])


def is_last_active_admin(conn: sqlite3.Connection, user: Mapping[str, Any]) -> bool:
    return user["role"] == "admin" and bool(int(user["is_active"])) and other_active_admins(conn, int(user["id"])) == 0


def set_password(conn: sqlite3.Connection, user_id: int, password_hash: str, now: datetime, *, keep_token_hash: str | None = None) -> None:
    """Store a new (pre-computed) hash, stamp ``password_set_at`` (the account now has a usable password — ``User.has_password``)
    and revoke the user's sessions (all, or all but ``keep_token_hash``). The single password writer: endpoints 7 / 57 / 89 / 91,
    ``wd set-password``."""
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        conn.execute("UPDATE users SET password_hash = ?, password_set_at = ?, updated_at = ? WHERE id = ?", (password_hash, now_iso, now_iso, user_id))
        delete_sessions(conn, user_id, keep_token_hash=keep_token_hash)


# ------------------------------------------------------------------------------------------- CLI
def _cli_settings() -> Settings:
    try:
        return Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        raise SystemExit(2)


def _cli_conn(cfg: Settings) -> sqlite3.Connection:
    ensure_dirs(cfg)
    conn = db.connect(cfg.db_path)
    if db.current_version(conn) < 1:
        conn.close()
        print("wd: the database is not migrated yet — run `wd migrate` first", file=sys.stderr)
        raise SystemExit(2)
    return conn


def _cli_password(args: argparse.Namespace, cfg: Settings, *, username: str, default_env: str | None = None) -> str | None:
    """Password from ``--password-env VAR``, else from ``default_env`` when the command names one, else a prompt.

    Only ``create-admin`` passes ``default_env="WD_ADMIN_PASSWORD"`` (the unattended install.sh form). ``set-password``
    must never pick that variable up implicitly: the bootstrap secret commonly lingers in ``$WD_DATA_DIR/.env``
    (loaded into the environment by ``cli.main``), and silently copying the admin's password onto another user's
    account — with no prompt and exit 0 — is exactly what the operator does not expect from "(default: prompt)".
    """
    var = getattr(args, "password_env", None) or default_env
    password = ""
    if var:
        password = os.environ.get(var) or (cfg.admin_password if var == "WD_ADMIN_PASSWORD" else "")
    if password:
        print(f"wd: password taken from ${var}", file=sys.stderr)
    else:
        if not sys.stdin.isatty():
            source = f"set {var} (or pass --password-env VAR)" if var else "pass --password-env VAR"
            print(f"wd: no password: {source} when running non-interactively", file=sys.stderr)
            return None
        password = getpass.getpass(f"password for {username}: ")
        again = getpass.getpass("repeat password: ")
        if password != again:
            print("wd: passwords do not match", file=sys.stderr)
            return None
    problem = password_problem(password, username)
    if problem:
        print(f"wd: weak password: {problem}", file=sys.stderr)
        return None
    return password


def cmd_create_admin(args: argparse.Namespace) -> int:
    cfg = _cli_settings()
    conn = _cli_conn(cfg)
    try:
        if args.if_none and int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]) > 0:
            print("users already exist; nothing to do")
            return 0
        username = (args.username or cfg.admin_username or "").strip()
        if not username:
            if args.if_none:
                # unattended install.sh form without WD_ADMIN_USERNAME: not an error (DEPLOY §2) — the first
                # account registered through the web becomes admin without an invite code (API.md endpoint 2)
                print("no admin configured (WD_ADMIN_USERNAME unset): the first account registered on the site becomes admin")
                return 0
            print("wd create-admin: --username (or WD_ADMIN_USERNAME) is required", file=sys.stderr)
            return 2
        if not USERNAME_RE.match(username):
            print("wd create-admin: username must be 2–32 letters, digits, underscores or CJK characters", file=sys.stderr)
            return 2
        if username_taken(conn, username):
            print(f"wd create-admin: user {username!r} already exists (use `wd promote` or `wd set-password`)", file=sys.stderr)
            return 1
        password = _cli_password(args, cfg, username=username, default_env="WD_ADMIN_PASSWORD")
        if password is None:
            return 2
        now = SYSTEM_CLOCK.now_utc()
        password_hash = hash_password(password)
        with db.tx(conn):
            user_id = create_user(conn, username=username, password_hash=password_hash, now=now, role="admin", password_set_at=to_iso(now))
        print(f"created admin {username} (id {user_id})")
        return 0
    finally:
        conn.close()


def cmd_set_password(args: argparse.Namespace) -> int:
    cfg = _cli_settings()
    conn = _cli_conn(cfg)
    try:
        user = load_user_by_name(conn, args.username)
        if user is None:
            print(f"wd set-password: no such user {args.username!r}", file=sys.stderr)
            return 1
        password = _cli_password(args, cfg, username=user["username"])  # no default_env: prompt, or an explicit --password-env
        if password is None:
            return 2
        set_password(conn, int(user["id"]), hash_password(password), SYSTEM_CLOCK.now_utc())
        print(f"password updated for {user['username']}; all sessions revoked")
        return 0
    finally:
        conn.close()


def _cmd_role(args: argparse.Namespace, role: str) -> int:
    cfg = _cli_settings()
    conn = _cli_conn(cfg)
    try:
        user = load_user_by_name(conn, args.username)
        if user is None:
            print(f"wd {'promote' if role == 'admin' else 'demote'}: no such user {args.username!r}", file=sys.stderr)
            return 1
        if user["role"] == role:
            print(f"{user['username']} is already {role}")
            return 0
        if role == "admin" and _column(user, "password_set_at") is None:
            # the API 57 rule (API.md §1.1 admin_needs_password): admins sign in with a password only (endpoint 3; a code login
            # answers them 403 password_required), so an account without one would be an admin nobody can log in as
            print(f"wd promote: {user['username']} has no password (admin_needs_password): run `wd set-password {user['username']}` first", file=sys.stderr)
            return 1
        with db.tx(conn):
            if role == "user" and is_last_active_admin(conn, user):
                print(f"wd demote: {user['username']} is the last active admin", file=sys.stderr)
                return 1
            conn.execute("UPDATE users SET role = ?, updated_at = ? WHERE id = ?", (role, to_iso(SYSTEM_CLOCK.now_utc()), user["id"]))
        print(f"{user['username']} is now {role}")
        return 0
    finally:
        conn.close()


def cmd_promote(args: argparse.Namespace) -> int:
    return _cmd_role(args, "admin")


def cmd_demote(args: argparse.Namespace) -> int:
    return _cmd_role(args, "user")


def cmd_invite(args: argparse.Namespace) -> int:
    cfg = _cli_settings()
    conn = _cli_conn(cfg)
    try:
        if args.uses < 1 or args.uses > 100:
            print("wd invite: --uses must be between 1 and 100", file=sys.stderr)
            return 2
        if args.days is not None and not 1 <= args.days <= 365:
            print("wd invite: --days must be between 1 and 365", file=sys.stderr)
            return 2
        now = SYSTEM_CLOCK.now_utc()
        with db.tx(conn):
            _, code, expires_at = create_invite(conn, created_by=None, max_uses=args.uses, expires_in_days=args.days, note=args.note, now=now)
        print(code)  # stdout carries only the code (shown once); metadata goes to stderr
        print(f"invite created: uses {args.uses}, expires {expires_at or 'never'}", file=sys.stderr)
        return 0
    finally:
        conn.close()


def cmd_unlock(args: argparse.Namespace) -> int:
    """``wd unlock <identifier>``: clear the login lockout of a username / phone / e-mail for every client IP (DEPLOY §9, ops.md §6)."""
    cfg = _cli_settings()
    identifier = (args.identifier or "").strip()
    if not identifier:
        print("wd unlock: an identifier (username, phone or e-mail) is required", file=sys.stderr)
        return 2
    conn = _cli_conn(cfg)
    try:
        removed = unlock_identifier(conn, identifier)
        print(f"unlocked: {removed} lockout row(s) removed")  # the identifier is not echoed: it may be a phone number or an e-mail
        return 0
    finally:
        conn.close()


def cmd_sms_probe(args: argparse.Namespace) -> int:
    """``wd sms-probe <number>``: send ONE real login code (template 100001) through the configured SMS provider and print the
    provider's answer — the day-0 check of the Aliyun signature / template before the login page depends on it. Prints neither the
    code nor the full number; does not touch the database or the SMS budget counters. Exit 0 sent, 1 the provider refused, 2 usage."""
    from .delivery.sms import TEMPLATE_BY_PURPOSE, SmsError, sms_sender_from_settings  # lazy: the delivery package is not needed by the web routes' import of this module

    cfg = _cli_settings()
    e164 = normalize_phone(args.number or "")
    if e164 is None:
        print("wd sms-probe: not a mainland mobile number (expected +86 1xxxxxxxxxx)", file=sys.stderr)
        return 2
    if not cfg.sms_configured:
        print("wd sms-probe: WD_SMS_PROVIDER is off — set WD_SMS_PROVIDER=aliyun_verify with WD_ALIYUN_ACCESS_KEY_ID / WD_ALIYUN_ACCESS_KEY_SECRET_FILE / WD_ALIYUN_SMS_SIGN_NAME first (DEPLOY §4)", file=sys.stderr)
        return 2
    sender = sms_sender_from_settings(cfg)
    if sender is None:  # pragma: no cover - sms_configured guarantees a sender
        print("wd sms-probe: no SMS sender for the configured provider", file=sys.stderr)
        return 2
    template = TEMPLATE_BY_PURPOSE["login"]
    try:
        sender.send_code(e164, _new_code(), template, minutes=LOGIN_CODE_TTL_S // 60)
    except SmsError as e:
        print(f"wd sms-probe: {cfg.sms_provider} refused the send to {mask_phone(e164)} (template {template}): {e.kind}: {e}", file=sys.stderr)
        return 1
    result = getattr(sender, "last_result", None) or {}
    detail = " ".join(f"{k}={result[k]}" for k in ("Code", "Message", "RequestId", "BizId") if result.get(k))
    print(f"sms-probe: code sent to {mask_phone(e164)} via {cfg.sms_provider}, template {template}" + (f" — {detail}" if detail else ""))
    return 0


def register_cli(sub: argparse._SubParsersAction) -> None:
    """``wd create-admin | set-password | promote | demote | invite | unlock | sms-probe`` (DEPLOY §9, owner ``wd.security``)."""
    p = sub.add_parser("create-admin", help="create an admin account (unattended: WD_ADMIN_USERNAME / WD_ADMIN_PASSWORD)")
    p.add_argument("--if-none", action="store_true", help="do nothing when any user already exists")
    p.add_argument("--username", help="admin username (default: WD_ADMIN_USERNAME)")
    p.add_argument("--password-env", metavar="VAR", help="environment variable holding the password (default: WD_ADMIN_PASSWORD)")
    p.set_defaults(func=cmd_create_admin)

    p = sub.add_parser("set-password", help="set a user's password (revokes all sessions)")
    p.add_argument("username")
    p.add_argument("--password-env", metavar="VAR", help="environment variable holding the new password (default: prompt; required when non-interactive)")
    p.set_defaults(func=cmd_set_password)

    p = sub.add_parser("promote", help="make a user an admin (refuses an account without a password: admins sign in with one)")
    p.add_argument("username")
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("demote", help="make an admin a regular user (refuses the last active admin)")
    p.add_argument("username")
    p.set_defaults(func=cmd_demote)

    p = sub.add_parser("invite", help="create an invite code (printed once)")
    p.add_argument("--uses", type=int, default=1, help="max uses (1–100, default 1)")
    p.add_argument("--days", type=int, default=None, help="expires after N days (default: never)")
    p.add_argument("--note", default="", help="free-text note shown in the admin page")
    p.set_defaults(func=cmd_invite)

    p = sub.add_parser("unlock", help="clear the login lockout of a username / phone / e-mail for every client IP")
    p.add_argument("identifier", help="the username, phone number or e-mail the lockout was counted under")
    p.set_defaults(func=cmd_unlock)

    p = sub.add_parser("sms-probe", help="send one real login code through the configured SMS provider (day-0 check; prints the provider's answer)")
    p.add_argument("number", help="a mainland mobile number, e.g. +8613800138000")
    p.set_defaults(func=cmd_sms_probe)
