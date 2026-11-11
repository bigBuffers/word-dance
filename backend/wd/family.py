"""Guardian + child accounts — the shared machinery of slice 1-B (docs/AUTH_SIGNUP_DESIGN.md §5.1 「家长 + 孩子」, §5.2 「切换与边界」 /
「未成年人」 / 「存量账号」; API.md §3.2, endpoints 94–111; migration 0019).

* **Constants**: the design's numbers live here, not in ``Settings`` (1-B adds no environment variable): a child's device session
  :data:`CHILD_SESSION_DAYS` (90), the 家长门 stamp :data:`GATE_TTL_S` (10 min), :data:`MAX_CHILDREN` (10) per guardian, the 8-digit
  child login code (:data:`CHILD_CODE_LEN`, :data:`FAMILY_CODE_TTL_S`), the claim code's :data:`FAMILY_CODE_MAX_ATTEMPTS` (5), the
  ``child_code:user:<child id>`` (5/h) and failures-only ``child_login:ip:<ip>`` (10/h) windows and the legacy prompt's 30-day snooze.
* **家长 PIN**: :func:`pin_problem` (6 digits, no repeats, no straight runs), :func:`hash_pin` / :func:`verify_pin` — bcrypt through
  ``security.hash_password`` / ``verify_password`` (a NULL hash takes the dummy path and fails in constant time).
* **Readiness** (the two-factor rule for guardians, enforced where it matters — creating / switching into / issuing codes for children,
  the 独立 flow): :func:`guardian_ready` / :func:`require_ready` (409 ``guardian_factors_required`` with ``details.missing``).
* **Children**: :func:`children_of` / :func:`child_of` (404 ``not_found`` unless mine), :func:`child_dto` (API.md §9 ``ChildAccount``),
  :func:`create_child` (``security.create_user`` with the child columns in ONE INSERT), :func:`delete_user_rows` (the cascade + the
  private-word rule + job cancellation that ``routers/account.delete_account`` ran inline; endpoints 8 and 97 share it).
* **The 家长门** (:func:`gate_check`, endpoints 102 / 105): exactly one of PIN / password / ``reauth`` code, behind the lockout key
  ``gate:user:<guardian id>`` with the LOGIN cadence (``security.lock_seconds_for``: 10 failures → 15 min, doubling every 5 more, max 24 h,
  streak reset after 24 h) — keyed per guardian, not per IP, because the guesser sits on the guardian's own device. Checked FIRST (423
  ``account_locked``); a wrong PIN → 401 ``invalid_pin``, a wrong password → 401 ``invalid_credentials`` (its own ``pwcheck`` budget), a
  wrong code → 400 ``invalid_code``; every failure counts, a success clears the key. Call it OUTSIDE any transaction. :func:`stamp_gate`
  writes ``sessions.guardian_gate_at``; :func:`gate_until` reads it back for the DTOs (a guardian in a self session only).
* **Family codes** (``family_codes``, 0019): ``code_hash = hex HMAC-SHA256(WD_SECRET_KEY, "<code>:<kind>:<target or ''>")``
  (:func:`family_code_hash`). ``child_login`` rows (:func:`issue_child_code` / :func:`consume_child_code`) are looked up by hash alone —
  8 digits, 10 minutes, one live code per child, single use, the per-IP failure window of endpoint 107 is the brute-force bound.
  ``claim_guardian`` rows (:func:`issue_claim_code` / :func:`verify_claim_code`) follow the ``security.verify_login_code`` pattern: the
  newest live row of (user, target), an atomic attempt count, burnt after 5 wrong guesses, verified outside the caller's transaction and
  consumed inside it (:func:`mark_family_code_used`). :func:`void_family_codes` / :func:`gc_family_codes` (the hourly GC, the login_codes rule).

Codes, PINs, phone numbers and tokens never reach a log line or a ``system_events`` detail (ids only). This module never imports a
router module; ``deps`` imports it lazily (``security`` imports ``deps``).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import re
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Mapping

from . import db, security
from .clock import local_date, parse_iso, to_iso
from .config import Settings
from .errors import ApiError
from .services import stats

log = logging.getLogger("wd.family")

# ------------------------------------------------------------------------------------ constants
CHILD_SESSION_DAYS = 90  # a child's own device signed in with a login code (endpoint 107); WD_SESSION_DAYS stays the guardian's / learner's
GATE_TTL_S = 600  # the 家长门 stamp on the guardian's session (endpoints 102 / 105) is good for 10 minutes
MAX_CHILDREN = 10  # children per guardian (409 invalid_transition, reason too_many_children)
CHILD_CODE_LEN = 8  # digits of a child login code (endpoint 99)
FAMILY_CODE_TTL_S = 600  # child login codes and claim codes: 10 minutes
FAMILY_CODE_MAX_ATTEMPTS = 5  # wrong guesses that burn a claim code (endpoint 109)
CHILD_CODE_ISSUE_LIMIT, CHILD_CODE_ISSUE_WINDOW_S = 5, 3600  # child_code:user:<child id>
CHILD_LOGIN_IP_LIMIT, CHILD_LOGIN_IP_WINDOW_S = 10, 3600  # child_login:ip:<ip>, failures only
PROFILE_PROMPT_SNOOZE_DAYS = security.PROFILE_PROMPT_SNOOZE_DAYS  # 30 — the legacy prompt (endpoint 111); the source lives in security for user_dto
PIN_RE = re.compile(r"^\d{6}$", re.ASCII)  # ASCII digits only: the schema pattern (a Unicode-aware `\d`) lets full-width digits through
PIN_LENGTH_ZH = "家长 PIN 为 6 位数字"
PIN_PATTERN_ZH = "PIN 不能是连号或重复数字"
JOB_KEY_PREFIXES = ("lookup", "content", "image", "svg", "dance")  # live jobs cancelled with an orphaned private word (routers/account.py's list)
FAMILY_CODE_KINDS = ("child_login", "claim_guardian")  # family_codes.kind CHECK (0019)


# ------------------------------------------------------------------------------------------ PIN
def pin_problem(pin: str) -> str | None:
    """The zh reason a 家长 PIN is refused, or None: not 6 digits; all one digit (``111111``); a straight run up or down (``123456``,
    ``654321``, ``901234``) — the guesses a child tries first."""
    if not PIN_RE.match(pin or ""):
        return PIN_LENGTH_ZH
    digits = [int(ch) for ch in pin]
    if len(set(digits)) == 1:
        return PIN_PATTERN_ZH
    steps = {(b - a) % 10 for a, b in zip(digits, digits[1:])}
    if steps == {1} or steps == {9}:
        return PIN_PATTERN_ZH
    return None


def hash_pin(pin: str) -> str:
    """bcrypt like a password (``security.hash_password``) — the PIN is a secret the guardian types on the child's device."""
    return security.hash_password(pin)


def verify_pin(pin: str, pin_hash: str | None) -> bool:
    """True iff ``pin`` matches ``pin_hash``; a NULL hash (no PIN set) still costs one bcrypt check and is always False."""
    return security.verify_password(pin or "", pin_hash)


# -------------------------------------------------------------------------------------- predicates
def is_child(user: Mapping[str, Any]) -> bool:
    """``users.guardian_user_id IS NOT NULL`` — a child account (``User.is_child``)."""
    return user.get("guardian_user_id") is not None


def is_guardian(user: Mapping[str, Any]) -> bool:
    return user.get("account_kind") == "guardian"


def guardian_ready(conn: sqlite3.Connection, user: Mapping[str, Any]) -> dict[str, Any]:
    """The two-factor rule (AUTH_SIGNUP_DESIGN §5.1): a live phone identity AND a second factor (a password or a verified e-mail).

    Returns ``{"phone": bool, "second_factor": bool, "ready": bool, "missing": [...]}`` — ``missing`` names ``phone`` and / or
    ``second_factor`` in that order (``ChildrenResponse.missing``)."""
    phone = security.phone_identity(conn, int(user["id"])) is not None
    second = user.get("password_set_at") is not None or user.get("email_verified_at") is not None
    missing = [name for name, ok in (("phone", phone), ("second_factor", second)) if not ok]
    return {"phone": phone, "second_factor": second, "ready": not missing, "missing": missing}


def require_ready(conn: sqlite3.Connection, user: Mapping[str, Any]) -> None:
    """409 ``guardian_factors_required`` (``details.missing``) unless :func:`guardian_ready` — endpoints 95, 99, 100, 101, 104."""
    ready = guardian_ready(conn, user)
    if not ready["ready"]:
        raise ApiError("guardian_factors_required", details={"missing": ready["missing"]})


# ---------------------------------------------------------------------------------------- children
def children_of(conn: sqlite3.Connection, guardian_id: int) -> list[dict[str, Any]]:
    """The guardian's children (``users`` rows) by creation."""
    rows = conn.execute("SELECT * FROM users WHERE guardian_user_id = ? ORDER BY created_at, id", (int(guardian_id),)).fetchall()
    return [security.row_dict(r) or {} for r in rows]


def child_of(conn: sqlite3.Connection, guardian_id: int, child_id: int) -> dict[str, Any]:
    """The child row when it belongs to ``guardian_id``; 404 ``not_found`` otherwise (another guardian's child, a learner, nobody)."""
    row = security.row_dict(conn.execute("SELECT * FROM users WHERE id = ? AND guardian_user_id = ?", (int(child_id), int(guardian_id))).fetchone())
    if row is None:
        raise ApiError("not_found", details={"child_id": int(child_id)})
    return row


def child_dto(conn: sqlite3.Connection, row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """API.md §9 ``ChildAccount``: ``username`` is None while the placeholder pattern matches, ``bank_size`` / ``streak_days`` are the
    ``AdminUser`` figures (``services.stats.streak`` on the child's local date), ``sessions`` counts the child's live sessions whatever
    their ``actor_user_id``."""
    child_id = int(row["id"])
    username = str(row["username"])
    identity = security.phone_identity(conn, child_id)
    tz_row = conn.execute("SELECT timezone FROM user_settings WHERE user_id = ?", (child_id,)).fetchone()
    tz = str(tz_row[0]) if tz_row and tz_row[0] else security.DEFAULT_TIMEZONE
    bank_size = int(conn.execute("SELECT COUNT(*) FROM user_words WHERE user_id = ? AND state IN ('new','learning')", (child_id,)).fetchone()[0])
    sessions = int(conn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ? AND expires_at > ?", (child_id, to_iso(now))).fetchone()[0])
    return {
        "id": child_id,
        "display_name": row["display_name"] or username,
        "username": None if security.PLACEHOLDER_USERNAME_RE.match(username) else username,
        "has_password": row.get("password_set_at") is not None,
        "phone_masked": security.mask_phone(str(identity["subject"])) if identity else None,
        "age_band": row.get("age_band"),
        "onboarding_state": row["onboarding_state"],
        "created_at": row["created_at"],
        "last_login_at": row.get("last_login_at"),
        "bank_size": bank_size,
        "streak_days": int(stats.streak(conn, child_id, local_date(now, tz))[0]),
        "sessions": sessions,
    }


def create_child(
    conn: sqlite3.Connection,
    *,
    guardian_id: int,
    display_name: str,
    username: str,
    password_hash: str,
    password_set_at: str | None,
    now: datetime,
    ip: str | None,
) -> int:
    """A child account (endpoint 95) inside the caller's ``BEGIN IMMEDIATE``: ``security.create_user`` with the child columns in the one
    INSERT — ``account_kind='learner'``, ``guardian_user_id``, ``age_band='u14'``, the declaration stamps and ``guardian_consent_at`` =
    now (the guardian's consent is the creation itself, AUTH_SIGNUP_DESIGN §5.2). ``username`` is the placeholder or the simple login the
    guardian chose; ``password_hash`` is pre-computed (the unusable hash without a password, ``password_set_at`` None then)."""
    now_iso = to_iso(now)
    return security.create_user(
        conn,
        username=username,
        password_hash=password_hash,
        now=now,
        role="user",
        display_name=display_name,
        email=None,
        password_set_at=password_set_at,
        account_kind="learner",
        guardian_user_id=int(guardian_id),
        age_band="u14",
        age_declared_at=now_iso,
        age_declared_ip=ip,
        guardian_consent_at=now_iso,
    )


def delete_user_rows(conn: sqlite3.Connection, user_id: int, now_iso: str) -> int:
    """Delete an account inside the caller's transaction (endpoints 8 and 97): ``DELETE FROM users`` (ON DELETE CASCADE / SET NULL do the
    rest — sessions, identities, login_codes, family_codes, the bank …), then the private-word rule: a private word the user created is
    deleted only when no other user's ``user_words`` row references it, and the live jobs of such an orphan are cancelled first. Returns
    the number of private words deleted. A guardian with children still attached fails on ``guardian_user_id``'s ON DELETE RESTRICT —
    the caller frees or deletes them first (endpoint 8 ``delete_children``)."""
    uid = int(user_id)
    private_words = [int(r[0]) for r in conn.execute("SELECT id FROM words WHERE created_by_user_id = ? AND is_public = 0", (uid,))]
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    orphaned = [wid for wid in private_words if int(conn.execute("SELECT COUNT(*) FROM user_words WHERE word_id = ?", (wid,)).fetchone()[0]) == 0]
    if orphaned:
        keys = [f"{prefix}:{wid}" for wid in orphaned for prefix in JOB_KEY_PREFIXES]
        conn.execute(
            f"UPDATE jobs SET status = 'cancelled', updated_at = ?, finished_at = ? WHERE status IN ('queued','running') AND dedupe_key IN ({','.join('?' * len(keys))})",
            [now_iso, now_iso, *keys],
        )
        conn.execute(f"DELETE FROM words WHERE id IN ({','.join('?' * len(orphaned))})", orphaned)
    return len(orphaned)


# ---------------------------------------------------------------------------------- the 家长门 lockout
def gate_key(guardian_id: int) -> str:
    return f"gate:user:{int(guardian_id)}"


def _throttle_row(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    return conn.execute("SELECT key, window_start, count, blocked_until FROM auth_throttle WHERE key = ?", (key,)).fetchone()


def gate_locked(conn: sqlite3.Connection, guardian_id: int, now: datetime) -> int | None:
    """Seconds until the guardian's gate lockout ends, or None while it is not locked."""
    row = _throttle_row(conn, gate_key(guardian_id))
    if row is None or not row["blocked_until"]:
        return None
    until = parse_iso(str(row["blocked_until"]))
    if until <= now:
        return None
    return max(1, math.ceil((until - now).total_seconds()))


def gate_failure(conn: sqlite3.Connection, guardian_id: int, now: datetime) -> int | None:
    """Count one failed 家长门 attempt (``security.record_login_failure`` keyed per guardian); returns the lockout seconds when this
    failure starts a lock (the login cadence: 10 → 15 min, doubling every 5 more, max 24 h; a streak older than 24 h starts over)."""
    key = gate_key(guardian_id)
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        row = _throttle_row(conn, key)
        count = 0
        window_start = now_iso
        if row is not None:
            stale = parse_iso(str(row["window_start"])) + timedelta(seconds=security.LOCKOUT_RESET_S) <= now
            locked = bool(row["blocked_until"]) and parse_iso(str(row["blocked_until"])) > now
            if not stale or locked:
                count = int(row["count"])
                window_start = str(row["window_start"])
        count += 1
        lock_s = security.lock_seconds_for(count)
        blocked_until = to_iso(now + timedelta(seconds=lock_s)) if lock_s else None
        conn.execute(
            "INSERT INTO auth_throttle(key, window_start, count, blocked_until) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET window_start = excluded.window_start, count = excluded.count, blocked_until = excluded.blocked_until",
            (key, window_start, count, blocked_until),
        )
    if lock_s:
        log.warning("guardian gate lockout after %d failures: %d s", count, lock_s, extra={"event": "gate_lockout", "user_id": int(guardian_id)})
    return lock_s


def gate_cleared(conn: sqlite3.Connection, guardian_id: int) -> None:
    """A passed 家长门 forgets the failure streak."""
    with db.maybe_tx(conn):
        conn.execute("DELETE FROM auth_throttle WHERE key = ?", (gate_key(guardian_id),))


def gate_check(
    conn: sqlite3.Connection,
    guardian: Mapping[str, Any],
    *,
    pin: str | None,
    password: str | None,
    code: str | None,
    now: datetime,
    cfg: Settings,
    ip: str | None = None,
) -> int | None:
    """The 家长门 (API.md §3.2, endpoints 102 / 105): exactly one of ``pin`` / ``password`` / ``code`` (the schemas enforce it; a caller
    passing none raises 400 here too). Call it OUTSIDE any transaction — every failure is committed before the error is raised.

    Order: the gate lockout (423 ``account_locked`` ``details.retry_after_s``) → ``pin``: :func:`verify_pin` against the guardian's
    ``guardian_pin_hash`` (read fresh from ``users``; a missing PIN takes the dummy path) → wrong → :func:`gate_failure` + 401
    ``invalid_pin``; ``password``: an account without a password → 400 ``validation_error`` ``fields.password``, else
    ``security.verify_account_password`` (its ``pwcheck:user:<id>`` budget → 429; wrong → counted here too + 401 ``invalid_credentials``);
    ``code``: the guardian's newest live ``reauth`` code whatever its channel (``security.verify_login_code`` with ``target=None``; wrong →
    counted + 400 ``invalid_code`` — the code-check windows are not used here, the gate lockout is the bound). A success clears the
    streak and returns the ``login_codes`` row id to consume inside the caller's transaction (None for the PIN / password paths).
    """
    gid = int(guardian["id"])
    remaining = gate_locked(conn, gid, now)
    if remaining is not None:
        raise ApiError("account_locked", details={"retry_after_s": remaining})
    if sum(x is not None for x in (pin, password, code)) != 1:
        raise ApiError("validation_error", message_zh="PIN、密码和验证码必须且只能提供一个", details={"fields": {"body": "PIN、密码和验证码必须且只能提供一个"}})
    row_id: int | None = None
    if pin is not None:
        stored = conn.execute("SELECT guardian_pin_hash FROM users WHERE id = ?", (gid,)).fetchone()
        if not verify_pin(pin, stored[0] if stored is not None else None):
            gate_failure(conn, gid, now)
            log.info("guardian gate refused a PIN", extra={"event": "gate_failed", "user_id": gid, "factor": "pin"})
            raise ApiError("invalid_pin")
    elif password is not None:
        if guardian.get("password_set_at") is None:
            raise ApiError("validation_error", message_zh="账号没有密码，请用 PIN 或验证码", details={"fields": {"password": "账号没有密码，请用 PIN 或验证码"}})
        try:
            security.verify_account_password(conn, guardian, password, now=now)
        except ApiError as e:
            if e.code == "invalid_credentials":
                gate_failure(conn, gid, now)
                log.info("guardian gate refused a password", extra={"event": "gate_failed", "user_id": gid, "factor": "password"})
            raise
    else:
        try:
            row_id = security.verify_login_code(conn, channel=None, target=None, purpose="reauth", code=str(code), secret_key=cfg.secret_key, now=now, user_id=gid)
        except ApiError as e:
            if e.code == "invalid_code":
                gate_failure(conn, gid, now)
                log.info("guardian gate refused a code", extra={"event": "gate_failed", "user_id": gid, "factor": "code"})
            raise
    gate_cleared(conn, gid)
    return row_id


def stamp_gate(conn: sqlite3.Connection, token_hash: str, now: datetime) -> None:
    """Record that this session passed the 家长门 now (``sessions.guardian_gate_at``, good for :data:`GATE_TTL_S`)."""
    conn.execute("UPDATE sessions SET guardian_gate_at = ? WHERE token_hash = ?", (to_iso(now), token_hash))


def gate_until(user: Mapping[str, Any], now: datetime) -> str | None:
    """``sessions.guardian_gate_at + GATE_TTL_S`` as ISO while it lies in the future and the user is a guardian in a self session
    (``session_actor_user_id`` None) — ``SessionInfo.gate_until`` / ``ChildrenResponse.gate_until``; None otherwise."""
    stamp = user.get("session_gate_at")
    if not stamp or not is_guardian(user) or user.get("session_actor_user_id") is not None:
        return None
    until = parse_iso(str(stamp)) + timedelta(seconds=GATE_TTL_S)
    return to_iso(until) if until > now else None


# ------------------------------------------------------------------------------------- family codes
def family_code_hash(secret_key: str, code: str, kind: str, target: str | None) -> str:
    """hex HMAC-SHA256(key = WD_SECRET_KEY, msg = ``code:kind:target``) — ``family_codes.code_hash`` (0019; an empty target for child codes)."""
    return hmac.new(secret_key.encode("utf-8"), f"{code}:{kind}:{target or ''}".encode("utf-8"), hashlib.sha256).hexdigest()


def _live_hash_exists(conn: sqlite3.Connection, code_hash: str, now_iso: str) -> bool:
    return conn.execute("SELECT 1 FROM family_codes WHERE code_hash = ? AND used_at IS NULL AND expires_at > ?", (code_hash, now_iso)).fetchone() is not None


def issue_child_code(conn: sqlite3.Connection, *, child_id: int, ip: str | None, secret_key: str, now: datetime) -> str:
    """A fresh 8-digit one-time login code for the child's own device (endpoint 99), returned once for the guardian's screen.

    The child's older unused ``child_login`` rows are voided (one live code per child); the code is regenerated while a live row shares
    its hash — endpoint 107 looks the row up by hash alone, so two live codes must never collide. Runs in its own transaction unless the
    caller holds one; expires after :data:`FAMILY_CODE_TTL_S`. Never stored or logged in clear."""
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        conn.execute("UPDATE family_codes SET used_at = ? WHERE kind = 'child_login' AND user_id = ? AND used_at IS NULL", (now_iso, int(child_id)))
        while True:
            code = f"{secrets.randbelow(10**CHILD_CODE_LEN):0{CHILD_CODE_LEN}d}"
            code_hash = family_code_hash(secret_key, code, "child_login", None)
            if not _live_hash_exists(conn, code_hash, now_iso):
                break
        conn.execute(
            "INSERT INTO family_codes(kind, user_id, target, code_hash, expires_at, attempts, used_at, ip, created_at) VALUES ('child_login', ?, NULL, ?, ?, 0, NULL, ?, ?)",
            (int(child_id), code_hash, to_iso(now + timedelta(seconds=FAMILY_CODE_TTL_S)), ip, now_iso),
        )
    return code


def consume_child_code(conn: sqlite3.Connection, *, code: str, secret_key: str, now: datetime) -> dict[str, Any] | None:
    """Inside the caller's transaction (endpoint 107): the live ``child_login`` row whose hash matches ``code`` is marked used and returned
    (``user_id`` = the child); None when no live row matches — a wrong, expired or already used code (the caller counts the miss on its
    per-IP window)."""
    now_iso = to_iso(now)
    code_hash = family_code_hash(secret_key, (code or "").strip(), "child_login", None)
    row = conn.execute(
        "SELECT * FROM family_codes WHERE kind = 'child_login' AND code_hash = ? AND used_at IS NULL AND expires_at > ? ORDER BY id DESC LIMIT 1",
        (code_hash, now_iso),
    ).fetchone()
    if row is None:
        return None
    if conn.execute("UPDATE family_codes SET used_at = ? WHERE id = ? AND used_at IS NULL", (now_iso, row["id"])).rowcount != 1:
        return None  # a concurrent request spent it first
    result = security.row_dict(row) or {}
    result["used_at"] = now_iso
    return result


def issue_claim_code(conn: sqlite3.Connection, *, user_id: int, target: str, ip: str | None, secret_key: str, now: datetime) -> str:
    """A fresh 6-digit claim code for 「这是孩子的账号」 (endpoint 108): ``user_id`` = the account that asked to become a child, ``target`` =
    the guardian's phone (E.164, the number the SMS goes to). Every older unused claim row of the user is voided, whatever its target —
    one live claim at a time, so two overlapping claims of the same account cannot both succeed."""
    now_iso = to_iso(now)
    code = f"{secrets.randbelow(1_000_000):06d}"
    with db.maybe_tx(conn):
        conn.execute(
            "UPDATE family_codes SET used_at = ? WHERE kind = 'claim_guardian' AND user_id = ? AND used_at IS NULL",
            (now_iso, int(user_id)),
        )
        conn.execute(
            "INSERT INTO family_codes(kind, user_id, target, code_hash, expires_at, attempts, used_at, ip, created_at) VALUES ('claim_guardian', ?, ?, ?, ?, 0, NULL, ?, ?)",
            (int(user_id), target, family_code_hash(secret_key, code, "claim_guardian", target), to_iso(now + timedelta(seconds=FAMILY_CODE_TTL_S)), ip, now_iso),
        )
    return code


def verify_claim_code(conn: sqlite3.Connection, *, user_id: int, target: str, code: str, secret_key: str, now: datetime) -> int:
    """Check a claim code against the newest live ``claim_guardian`` row of (``user_id``, ``target``) and return that row's id.

    The ``security.verify_login_code`` pattern: lookup, compare and attempt count in ONE ``BEGIN IMMEDIATE`` of their own (a wrong guess
    counts whatever the caller does next; the row is burnt at :data:`FAMILY_CODE_MAX_ATTEMPTS` in the same statement), 400 ``invalid_code``
    with ``details.attempts_left`` raised AFTER the commit (``attempts_left: 0`` when no live row exists / it expired / its budget is
    spent). Call it OUTSIDE any transaction; the caller consumes the row with :func:`mark_family_code_used` inside its own.
    """
    now_iso = to_iso(now)
    cleaned = (code or "").strip()
    verified: int | None = None
    left = 0
    with db.maybe_tx(conn):
        row = conn.execute(
            "SELECT * FROM family_codes WHERE kind = 'claim_guardian' AND user_id = ? AND target = ? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
            (int(user_id), target),
        ).fetchone()
        if row is not None and str(row["expires_at"]) > now_iso and int(row["attempts"]) < FAMILY_CODE_MAX_ATTEMPTS:
            expected = family_code_hash(secret_key, cleaned, "claim_guardian", target)
            if hmac.compare_digest(str(row["code_hash"]), expected):
                verified = int(row["id"])
            else:
                counted = conn.execute(
                    "UPDATE family_codes SET attempts = attempts + 1, used_at = CASE WHEN attempts + 1 >= ? THEN ? ELSE used_at END "
                    "WHERE id = ? AND used_at IS NULL RETURNING attempts",
                    (FAMILY_CODE_MAX_ATTEMPTS, now_iso, row["id"]),
                ).fetchone()
                left = max(0, FAMILY_CODE_MAX_ATTEMPTS - int(counted[0])) if counted is not None else 0
    if verified is None:
        raise ApiError("invalid_code", details={"attempts_left": left})
    return verified


def mark_family_code_used(conn: sqlite3.Connection, row_id: int, now: datetime) -> bool:
    """Consume a verified family code inside the caller's transaction; False when it was used meanwhile (a concurrent request won)."""
    return conn.execute("UPDATE family_codes SET used_at = ? WHERE id = ? AND used_at IS NULL", (to_iso(now), int(row_id))).rowcount == 1


def void_family_codes(conn: sqlite3.Connection, *, kind: str, user_id: int, now: datetime) -> int:
    """Mark the user's live codes of ``kind`` used (a failed send, a child set free, a deleted guardian …); returns rows voided."""
    if kind not in FAMILY_CODE_KINDS:
        raise ValueError(f"invalid family code kind {kind!r}")
    with db.maybe_tx(conn):
        cur = conn.execute("UPDATE family_codes SET used_at = ? WHERE kind = ? AND user_id = ? AND used_at IS NULL", (to_iso(now), kind, int(user_id)))
    return int(cur.rowcount)


def gc_family_codes(conn: sqlite3.Connection, now: datetime) -> int:
    """The hourly GC (``jobs/scheduler.hourly_gc``), the login_codes rule: an unused code goes when it expires, a used one is kept a day as
    the audit trail of a child login / a claim; returns rows deleted."""
    now_iso = to_iso(now)
    with db.maybe_tx(conn):
        cur = conn.execute(
            "DELETE FROM family_codes WHERE (used_at IS NULL AND expires_at <= ?) OR (used_at IS NOT NULL AND used_at <= ?)",
            (now_iso, to_iso(now - timedelta(days=1))),
        )
    return int(cur.rowcount)
