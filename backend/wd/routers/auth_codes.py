"""Sign-in by verification code — API.md §3.1 endpoints 79–84, 90, 91 (slice 1-A, docs/AUTH_SIGNUP_DESIGN.md §5.2–§5.3).

* ``GET /api/auth/captcha`` (79): the self-hosted image captcha (``wd.captcha``), 60/h per client IP.
* ``POST /api/auth/code`` (80): send a ``login`` / ``reset_password`` code to a phone (``app.state.sms``) or an e-mail
  (``app.state.mailer``). Order: consent → target normalisation → channel availability → ``setup_required`` → captcha
  (``WD_CAPTCHA=on`` and no session) → the §1 send throttles → the site-wide SMS caps (``sms_budget.reserve_sms`` INSIDE the
  transaction that writes the ``login_codes`` row) → the send OUTSIDE any transaction (a failed send voids the row). The answer
  is the same 202 for known and unknown targets; a ``reset_password`` code is only issued for a target that belongs to an account,
  and a cap or a provider failure on that send is still 202 (:func:`issue_and_send_silently`: the code is voided, the event logged).
* ``POST /api/auth/code/login`` (81): the §1 code-check windows (:func:`code_check_gate`: ``code_check:ip`` 60/h, ``code_check:target``
  20/h — READ before the code is looked at, COUNTED on a failed check only, the ``login:ip`` rule), ``security.verify_login_code``
  outside the route's transaction (a wrong guess stays counted), then ONE ``BEGIN IMMEDIATE`` consumes the code and logs in / creates
  the account / issues the stale-phone challenge. Never ``register:ip``, ``login:ip`` or the lockout; 403 ``setup_required`` while
  ``users`` is empty (the first account is a username + password, API.md 2), 403 ``password_required`` for an admin.
* ``POST /api/auth/challenge/email|confirm|dispute`` (82–84): the stale-phone second factor — a ``login_codes`` row with
  ``purpose='challenge'`` names the old account; 83 takes its password or an e-mail code, 84 disputes the binding and creates a new
  account for the number (``system_events('phone_disputed')``, a notice mail to the old account's verified e-mail).
* ``POST /api/auth/password/forgot|reset`` (90, 91): a ``reset_password`` code to the identifier's phone, else its verified e-mail
  (ALWAYS 202 — an unknown identifier, an exhausted target window, a site-wide cap and a provider failure all look alike; only the
  IP window, counted exactly once per request, and the captcha answer 4xx), then the new password — every session revoked,
  ``system_events('password_reset')``.

The shared machinery (:func:`send_throttles`, :func:`issue_and_send`, :func:`mail_for`, :func:`verify_code_checked`) is also what
``routers/account.py`` uses for endpoints 9, 10, 85, 86 and 88. Phone numbers, e-mails and codes never reach a log line or a
``system_events`` detail (``security.mask_phone`` / ``mask_email`` where a mask is shown at all; a mailer failure is logged by its
class only).
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

from fastapi import APIRouter, Depends, Request, Response

from .. import captcha, db, security, sms_budget
from ..ai.common import system_event
from ..clock import parse_iso, to_iso
from ..config import Settings
from ..delivery.mailer import MailerError
from ..delivery.sms import TEMPLATE_BY_PURPOSE, SmsError
from ..deps import SESSION_COOKIE, client_ip, get_db, hash_token
from ..errors import ApiError
from ..schemas import (
    AuthResponse,
    CaptchaChallenge,
    CaptchaToken,
    ChallengeConfirmRequest,
    ChallengeDisputeRequest,
    ChallengeEmailRequest,
    CodeLoginRequest,
    CodeLoginResponse,
    CodeSendRequest,
    CodeSendResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from .auth import _auth_payload, _issue_session, resolve_identifier

log = logging.getLogger("wd.routers.auth_codes")

router = APIRouter()

CODE_MINUTES = security.LOGIN_CODE_TTL_S // 60  # the `min` of the SMS template and the mail texts name the same number
CODE_SEND_IP_WINDOW_S = 3600  # WD_CODE_IP_HOURLY sends per client IP per hour (code_send:ip:<ip>)
DISPUTE_NOTICE_SUBJECT = "【word-Dance】手机号绑定变更"
MAIL_SUBJECTS: dict[str, str] = {
    "login": "【word-Dance】登录验证码",
    "reset_password": "【word-Dance】重置密码验证码",
    "reauth": "【word-Dance】身份确认验证码",
    "bind_email": "【word-Dance】邮箱验证码",
}
SENT: dict[str, Any] = {"sent": True, "expires_in_s": security.LOGIN_CODE_TTL_S}  # CodeSendResponse — identical for every outcome
#: send failures a reset flow (80 ``reset_password``, 90) swallows: the answer must not tell a registered target from an unknown one
SILENT_SEND_ERRORS = frozenset({"sms_budget_exhausted", "rate_limited", "invalid_phone", "sms_send_failed", "email_send_failed"})


# ------------------------------------------------------------------------------------- shared machinery
def sms_sender(request: Request) -> Any | None:
    """``app.state.sms`` — None while ``WD_SMS_PROVIDER=off`` and no test double is installed (409 ``sms_unconfigured``)."""
    return getattr(request.app.state, "sms", None)


def mailer_of(request: Request) -> Any | None:
    return getattr(request.app.state, "mailer", None)


def mail_for(purpose: str, code: str) -> tuple[str, str]:
    """Subject and body of a verification-code e-mail (10 分钟; the code is the only secret in the text)."""
    subject = MAIL_SUBJECTS.get(purpose, MAIL_SUBJECTS["login"])
    if purpose == "reset_password":
        text = f"你的 word-Dance 重置密码验证码是：{code}\n\n验证码 {CODE_MINUTES} 分钟内有效。\n如果这不是你的操作，请忽略本邮件，你的密码不会改变。"
    elif purpose == "reauth":
        text = f"你的 word-Dance 身份确认验证码是：{code}\n\n验证码 {CODE_MINUTES} 分钟内有效，请在「设置 → 账号」中填写。\n如果这不是你的操作，请尽快修改密码。"
    elif purpose == "bind_email":
        text = f"你的 word-Dance 邮箱验证码是：{code}\n\n验证码 {CODE_MINUTES} 分钟内有效，请在「设置 → 账号」中填写。\n如果这不是你的操作，请忽略本邮件。"
    else:
        text = f"你的 word-Dance 登录验证码是：{code}\n\n验证码 {CODE_MINUTES} 分钟内有效，请在登录页填写。\n如果这不是你的操作，请忽略本邮件。"
    return subject, text


def normalise_target(channel: str, target: str) -> str:
    """A phone becomes E.164 (400 ``invalid_phone`` otherwise); an e-mail is already NFKC / stripped / lower-cased by the schema."""
    if channel == "phone":
        e164 = security.normalize_phone(target)
        if e164 is None:
            raise ApiError("invalid_phone")
        return e164
    return target


def users_exist(conn: sqlite3.Connection) -> bool:
    return int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]) > 0


def account_for_target(conn: sqlite3.Connection, channel: str, target: str) -> dict[str, Any] | None:
    """The account a code target belongs to: the live phone identity's user, or the user whose **verified** e-mail it is."""
    if channel == "phone":
        identity = security.identity_by_subject(conn, "phone", target)
        return security.load_user(conn, int(identity["user_id"])) if identity is not None else None
    return security.row_dict(conn.execute("SELECT * FROM users WHERE email = ? AND email_verified_at IS NOT NULL", (target,)).fetchone())


def session_user_id(request: Request, conn: sqlite3.Connection, now: datetime) -> int | None:
    """The active account behind a valid ``wd_session`` cookie — without the side effects of ``deps.current_user`` (no sliding
    expiry, no mutation count): the captcha gate of 80 / 90 skips logged-in users."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires_at > ? AND u.is_active = 1",
        (hash_token(token), to_iso(now)),
    ).fetchone()
    return int(row[0]) if row is not None else None


def captcha_gate(request: Request, conn: sqlite3.Connection, cfg: Settings, token: CaptchaToken | None, now: datetime) -> None:
    """``WD_CAPTCHA=on`` and no session: a public code send needs a captcha token (400 ``captcha_required`` / ``invalid_captcha``)."""
    if cfg.captcha != "on" or session_user_id(request, conn, now) is not None:
        return
    if token is None:
        raise ApiError("captcha_required")
    captcha.verify(conn, cfg.secret_key, token, now)


def send_throttles(conn: sqlite3.Connection, cfg: Settings, *, channel: str, target: str, ip: str, now: datetime, silent_target: bool = False, count_ip: bool = True) -> bool:
    """The §1 send throttles, in this order: per target ``code_send:target:<t>:m|h|d`` (1/min, 5/h, 10/day), per client IP
    ``code_send:ip:<ip>`` (``WD_CODE_IP_HOURLY`` per hour), for phones per 7-digit prefix ``code_send:prefix:<p>`` (5/h). Over a
    limit → 429 ``rate_limited``; with ``silent_target`` the target and prefix windows return False instead (endpoint 90 answers
    202 whatever the target's state — only the IP window may refuse). Every window that is checked is also counted — except the IP
    window with ``count_ip=False``: endpoint 90 counts it itself BEFORE resolving the identifier (so an unknown identifier counts
    too) and must not count it a second time for a known one, or the count would tell the two apart (and halve the budget)."""
    target_keys = [(f"code_send:target:{target}:{suffix}", limit, window) for (limit, window), suffix in zip(security.CODE_SEND_TARGET_LIMITS, security.CODE_SEND_TARGET_SUFFIXES)]
    for key, limit, window in target_keys:
        retry = security.throttle_hit(conn, key, limit=limit, window_s=window, now=now)
        if retry is not None:
            if silent_target:
                return False
            raise ApiError("rate_limited", details={"retry_after_s": retry})
    if count_ip:
        security.rate_limit(conn, f"code_send:ip:{ip}", limit=cfg.code_ip_hourly, window_s=CODE_SEND_IP_WINDOW_S, now=now)
    if channel == "phone":
        retry = security.throttle_hit(conn, f"code_send:prefix:{security.phone_prefix(target)}", limit=security.CODE_SEND_PREFIX_LIMIT, window_s=security.CODE_SEND_PREFIX_WINDOW_S, now=now)
        if retry is not None:
            if silent_target:
                return False
            raise ApiError("rate_limited", details={"retry_after_s": retry})
    return True


def issue_and_send(
    request: Request,
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    channel: str,
    target: str,
    purpose: str,
    user_id: int | None,
    ip: str,
    now: datetime,
    new_account: bool = False,
    issuer: Callable[[sqlite3.Connection], str] | None = None,
    voider: Callable[[sqlite3.Connection], None] | None = None,
) -> None:
    """Write the ``login_codes`` row and deliver the code.

    Phone: ``sms_budget.reserve_sms`` (503 ``sms_budget_exhausted``; ``new_account`` = a ``login`` send to a number without an
    account, refused from 70 % of the day cap) and ``security.issue_login_code`` share ONE transaction, the budget events run after
    the commit and the provider call happens outside any transaction. E-mail: the row in its own transaction, then the mail. A
    failed send voids the row: a provider rate limit → 429 ``rate_limited`` (``retry_after_s``), a number the provider refuses →
    400 ``invalid_phone``, anything else → 503 ``sms_send_failed`` / ``email_send_failed``. Only the failure kind is logged.

    ``issuer`` / ``voider`` (slice 1-B, the claim code of endpoint 108): on the phone channel ``issuer(conn)`` replaces
    ``security.issue_login_code`` inside the reservation transaction (it returns the code to send — a ``family_codes`` row instead of a
    ``login_codes`` row) and ``voider(conn)`` replaces ``void_login_codes`` after a failed send; the SMS caps, the template of ``purpose``
    and the failure semantics stay. The e-mail channel has no such rows: passing either hook there is a ``ValueError``.
    """
    if channel == "phone":
        sender = sms_sender(request)
        if sender is None:
            raise ApiError("sms_unconfigured")
        with db.tx(conn):
            sms_budget.reserve_sms(conn, cfg, now, new_account=new_account)
            if issuer is not None:
                code = issuer(conn)
            else:
                code = security.issue_login_code(conn, channel="phone", target=target, purpose=purpose, user_id=user_id, ip=ip, secret_key=cfg.secret_key, now=now)
        sms_budget.sms_events(conn, cfg, now)
        try:
            sender.send_code(target, code, TEMPLATE_BY_PURPOSE[purpose], minutes=CODE_MINUTES)
        except SmsError as e:
            if voider is not None:
                voider(conn)
            else:
                security.void_login_codes(conn, channel="phone", target=target, purpose=purpose, now=now)
            log.warning("sms code not sent: %s", e.kind, extra={"event": "sms_code_failed", "user_id": user_id})
            if e.kind == "rate_limited":
                raise ApiError("rate_limited", details={"retry_after_s": int(e.retry_after_s or 60)}) from e
            if e.kind == "invalid_target":
                raise ApiError("invalid_phone") from e
            raise ApiError("sms_send_failed") from e
        log.info("sms code sent (%s)", purpose, extra={"event": "sms_code_sent", "user_id": user_id})
        return
    if issuer is not None or voider is not None:
        raise ValueError("issue_and_send: issuer / voider hooks are for the phone channel only")
    mailer = mailer_of(request)
    if mailer is None:
        raise ApiError("smtp_unconfigured")
    code = security.issue_login_code(conn, channel="email", target=target, purpose=purpose, user_id=user_id, ip=ip, secret_key=cfg.secret_key, now=now)
    subject, text = mail_for(purpose, code)
    try:
        mailer.send(target, subject, text)
    except MailerError as e:
        security.void_login_codes(conn, channel="email", target=target, purpose=purpose, now=now)
        # the failure class only (provider code + kind, or the exception class): a gateway message may echo the recipient and the body
        log.warning("e-mail code not sent: %s", e.failure_class, extra={"event": "email_code_failed", "user_id": user_id})
        raise ApiError("email_send_failed") from e
    log.info("e-mail code sent (%s)", purpose, extra={"event": "email_code_sent", "user_id": user_id})


def issue_and_send_silently(
    request: Request,
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    channel: str,
    target: str,
    purpose: str,
    user_id: int | None,
    ip: str,
    now: datetime,
) -> bool:
    """:func:`issue_and_send` for a send whose answer must not depend on whether the target has an account (80 ``reset_password``,
    90): a site-wide cap or a provider failure (:data:`SILENT_SEND_ERRORS`) is swallowed — the code row is already voided and the
    failure logged (``sms_code_failed`` / ``email_code_failed`` / the budget events) — and the caller answers the same 202 it gives
    an unknown target. Anything else (a misconfigured channel) still raises. Returns whether the code went out."""
    try:
        issue_and_send(request, conn, cfg, channel=channel, target=target, purpose=purpose, user_id=user_id, ip=ip, now=now)
    except ApiError as e:
        if e.code not in SILENT_SEND_ERRORS:
            raise
        log.info("code send suppressed (%s): %s", purpose, e.code, extra={"event": "code_send_suppressed", "user_id": user_id})
        return False
    return True


# ---------------------------------------------------------------------------------------- code checks
def code_check_gate(conn: sqlite3.Connection, *, ip: str, targets: Iterable[str] = (), now: datetime) -> None:
    """The §1 code-check windows READ before a code is looked at: ``code_check:ip:<ip>`` (60/h) and ``code_check:target:<t>`` (20/h)
    answer 429 ``rate_limited`` while they sit at their limit. They count FAILED checks only (:func:`code_check_failed`) — the
    ``login:ip`` rule of endpoint 3: a learner's correct code never spends their own window, so a stranger who knows a number
    needs 20 wrong guesses, not 20 requests, to pause its code logins for an hour."""
    keys = [(f"code_check:ip:{ip}", security.CODE_CHECK_IP_LIMIT, security.CODE_CHECK_IP_WINDOW_S)]
    keys += [(f"code_check:target:{t}", security.CODE_CHECK_TARGET_LIMIT, security.CODE_CHECK_TARGET_WINDOW_S) for t in targets]
    for key, limit, window in keys:
        retry = security.throttle_check(conn, key, limit=limit, window_s=window, now=now)
        if retry is not None:
            raise ApiError("rate_limited", details={"retry_after_s": retry})


def code_check_failed(conn: sqlite3.Connection, *, ip: str, targets: Iterable[str] = (), now: datetime) -> None:
    """Count one failed code check on the IP window and on each target window (the windows :func:`code_check_gate` reads)."""
    security.throttle_hit(conn, f"code_check:ip:{ip}", limit=security.CODE_CHECK_IP_LIMIT, window_s=security.CODE_CHECK_IP_WINDOW_S, now=now)
    for t in targets:
        security.throttle_hit(conn, f"code_check:target:{t}", limit=security.CODE_CHECK_TARGET_LIMIT, window_s=security.CODE_CHECK_TARGET_WINDOW_S, now=now)


def verify_code_checked(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    channel: str | None,
    target: str | None,
    purpose: str,
    code: str,
    ip: str,
    now: datetime,
    user_id: int | None = None,
    throttle_targets: Iterable[str] | None = None,
) -> int:
    """``security.verify_login_code`` behind the code-check windows: the gate first (429 before the code is looked at), the check
    outside any transaction (its attempt count commits on its own), and a failed check (400 ``invalid_code``) counted on the IP
    window and the target windows — ``throttle_targets`` names them (default: the code's own ``target``; none for a target-less
    lookup). Endpoints 10, 81, 83, 86, 88 and 91 verify through here."""
    targets = tuple(throttle_targets) if throttle_targets is not None else ((target,) if target else ())
    code_check_gate(conn, ip=ip, targets=targets, now=now)
    try:
        return security.verify_login_code(conn, channel=channel, target=target, purpose=purpose, code=code, secret_key=cfg.secret_key, now=now, user_id=user_id)
    except ApiError as e:
        if e.code == "invalid_code":
            code_check_failed(conn, ip=ip, targets=targets, now=now)
        raise


def create_code_account(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    channel: str,
    target: str,
    invite_code: str | None,
    password_hash: str,
    now: datetime,
) -> int:
    """The new-account branch of endpoints 81 / 84, inside the caller's ``BEGIN IMMEDIATE``: the registration mode (``closed`` → 403
    ``registration_closed``; ``invite`` → ``invite_code`` required and consumed, else 403 ``invalid_invite``; ``open`` / ``verified`` →
    consumed when given), then ``security.create_user`` with a placeholder username, the unusable ``password_hash`` the caller
    computed before the lock, ``password_set_at NULL`` and — for the e-mail channel — the address set and verified (an UNVERIFIED
    holder of that address loses it first, so ``ux_users_email`` cannot fire), plus the phone identity for the phone channel
    (``verified_at = last_login_at = now``). Returns the new user id; a racing duplicate surfaces as ``sqlite3.IntegrityError``."""
    mode = cfg.registration_mode
    if mode == "closed":
        raise ApiError("registration_closed")
    if mode == "invite":
        if not invite_code or not security.consume_invite(conn, invite_code, now):
            raise ApiError("invalid_invite")
    elif invite_code and not security.consume_invite(conn, invite_code, now):
        raise ApiError("invalid_invite")
    now_iso = to_iso(now)
    email = target if channel == "email" else None
    if email is not None:
        released = conn.execute("UPDATE users SET email = NULL, updated_at = ? WHERE email = ? AND email_verified_at IS NULL", (now_iso, email)).rowcount
        if released:
            log.info("unverified e-mail released to its verifier", extra={"event": "email_released"})
    user_id = security.create_user(
        conn,
        username=security.placeholder_username(conn),
        password_hash=password_hash,
        now=now,
        role="user",
        display_name=None,
        email=email,
        password_set_at=None,
        email_verified_at=now_iso if email is not None else None,
    )
    if channel == "phone":
        conn.execute(
            "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, 'phone', ?, ?, ?, ?)",
            (user_id, target, now_iso, now_iso, now_iso),
        )
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, user_id))
    return user_id


def identity_is_stale(identity: dict[str, Any], cfg: Settings, now: datetime) -> bool:
    """The stale-phone rule: the identity's last code login (its binding while none) is ``WD_PHONE_STALE_DAYS`` or more ago."""
    reference = identity.get("last_login_at") or identity.get("verified_at")
    if not reference:
        return False
    return parse_iso(str(reference)) + timedelta(days=int(cfg.phone_stale_days)) <= now


def challenge_dto(user: dict[str, Any], token: str) -> dict[str, Any]:
    """API.md §9 ``StaleChallenge`` for the old account (nothing beyond a masked name / e-mail and the registration month leaves)."""
    can_password = user.get("password_set_at") is not None
    can_email = user.get("email_verified_at") is not None and bool(user.get("email"))
    name = str(user.get("display_name") or user.get("username") or "")
    return {
        "token": token,
        "display_name_masked": name[:1] + "＊＊",
        "since": str(user.get("created_at") or "")[:7],
        "can_password": can_password,
        "can_email": can_email,
        "email_masked": security.mask_email(str(user["email"])) if can_email else None,
    }


def _challenge_row(conn: sqlite3.Connection, cfg: Settings, token: str, now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """The live challenge row for ``token`` and the account it names (400 ``challenge_expired`` otherwise)."""
    row = security.verify_challenge_token(conn, token=token, secret_key=cfg.secret_key, now=now)
    user = security.load_user(conn, int(row["user_id"])) if row.get("user_id") is not None else None
    if user is None:
        raise ApiError("challenge_expired")
    return row, user


# ------------------------------------------------------------------------------------------------- 79
@router.get("/api/auth/captcha", response_model=CaptchaChallenge)
def get_captcha(request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    security.rate_limit(conn, f"captcha:ip:{client_ip(request)}", limit=security.CAPTCHA_IP_LIMIT, window_s=security.CAPTCHA_IP_WINDOW_S, now=now)
    payload, _answer = captcha.new_challenge(cfg.secret_key, now)
    return payload


# ------------------------------------------------------------------------------------------------- 80
@router.post("/api/auth/code", status_code=202, response_model=CodeSendResponse)
def send_code(body: CodeSendRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    ip = client_ip(request)
    if body.purpose == "login" and body.consent is not True:
        raise ApiError("consent_required")
    target = normalise_target(body.channel, body.target)
    if body.channel == "phone" and sms_sender(request) is None:
        raise ApiError("sms_unconfigured")
    if body.channel == "email" and mailer_of(request) is None:
        raise ApiError("smtp_unconfigured")
    if not users_exist(conn):
        raise ApiError("setup_required")
    captcha_gate(request, conn, cfg, body.captcha, now)
    send_throttles(conn, cfg, channel=body.channel, target=target, ip=ip, now=now)
    account = account_for_target(conn, body.channel, target)
    if body.purpose == "reset_password":
        if account is not None:  # nothing to reset otherwise: the same answer, no code issued (API.md 80)
            issue_and_send_silently(request, conn, cfg, channel=body.channel, target=target, purpose="reset_password", user_id=int(account["id"]), ip=ip, now=now)
        return dict(SENT)  # a cap or a provider failure on the send is still 202: the status must not tell a registered target apart
    issue_and_send(request, conn, cfg, channel=body.channel, target=target, purpose="login", user_id=None, ip=ip, now=now, new_account=account is None)
    return dict(SENT)


# ------------------------------------------------------------------------------------------------- 81
@router.post("/api/auth/code/login", response_model=CodeLoginResponse)
def code_login(body: CodeLoginRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    target = normalise_target(body.channel, body.target)
    # the code-check windows (read first, counted on a failure) and the check itself, outside any transaction: a wrong guess is
    # counted before the error is raised
    row_id = verify_code_checked(conn, cfg, channel=body.channel, target=target, purpose="login", code=body.code, ip=ip, now=now)
    # bcrypt work before the write lock — only a new account needs the unusable hash
    unusable = security.unusable_password_hash() if account_for_target(conn, body.channel, target) is None else None

    for attempt in (0, 1):
        try:
            with db.tx(conn):
                if not security.mark_login_code_used(conn, row_id, now):
                    raise ApiError("invalid_code", details={"attempts_left": 0})  # consumed by a concurrent request
                if not users_exist(conn):
                    raise ApiError("setup_required")  # never an admin from a code (API.md 2 bootstrap rule)
                identity = security.identity_by_subject(conn, "phone", target) if body.channel == "phone" else None
                user = security.load_user(conn, int(identity["user_id"])) if identity is not None else (None if body.channel == "phone" else account_for_target(conn, "email", target))
                if user is not None:
                    user_id = int(user["id"])
                    if user["role"] == "admin":
                        raise ApiError("password_required")
                    if not int(user["is_active"]):
                        raise ApiError("account_disabled")
                    if identity is not None and identity_is_stale(identity, cfg, now):
                        token = security.issue_challenge_token(conn, target=target, user_id=user_id, ip=ip, secret_key=cfg.secret_key, now=now)
                        challenge = challenge_dto(user, token)
                        if not (challenge["can_password"] or challenge["can_email"]):
                            log.warning("stale phone login has no second factor", extra={"event": "auth_stale_login_blocked", "user_id": user_id})
                        else:
                            log.info("stale phone login challenged", extra={"event": "auth_stale_login_challenged", "user_id": user_id})
                        return {"user": None, "settings": None, "created": False, "challenge": challenge}
                    if identity is not None:
                        conn.execute("UPDATE identities SET last_login_at = ? WHERE id = ?", (now_iso, identity["id"]))
                    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, user_id))
                    security.gc_sessions(conn, now_iso)
                    _issue_session(request, response, conn, user_id, now)
                    created = False
                else:
                    user_id = create_code_account(conn, cfg, channel=body.channel, target=target, invite_code=body.invite_code, password_hash=unusable or security.unusable_password_hash(), now=now)
                    _issue_session(request, response, conn, user_id, now)
                    created = True
            break
        except sqlite3.IntegrityError as e:  # a racing request created the account for this target first: run again as a login
            if attempt:
                raise ApiError("identity_taken") from e
            log.info("code login raced on account creation; retrying as a login", extra={"event": "code_login_retry"})
    # `created` is a reserved LogRecord attribute (logging raises KeyError on it, i.e. a 500 after the commit under WD_LOG_LEVEL=INFO)
    log.info("code login", extra={"event": "code_login", "user_id": user_id, "channel": body.channel, "created_account": created})
    if created:
        response.status_code = 201
    return {**_auth_payload(conn, user_id, now=now), "created": created, "challenge": None}


# ------------------------------------------------------------------------------------------------- 82
@router.post("/api/auth/challenge/email", status_code=202, response_model=CodeSendResponse)
def challenge_email(body: ChallengeEmailRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    ip = client_ip(request)
    _row, user = _challenge_row(conn, cfg, body.token, now)
    if user.get("email_verified_at") is None or not user.get("email"):
        raise ApiError("second_factor_required")
    if mailer_of(request) is None:
        raise ApiError("smtp_unconfigured")
    email = str(user["email"])
    send_throttles(conn, cfg, channel="email", target=email, ip=ip, now=now)
    issue_and_send(request, conn, cfg, channel="email", target=email, purpose="login", user_id=int(user["id"]), ip=ip, now=now)
    return dict(SENT)


# ------------------------------------------------------------------------------------------------- 83
@router.post("/api/auth/challenge/confirm", response_model=AuthResponse)
def challenge_confirm(body: ChallengeConfirmRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    ip = client_ip(request)
    code_check_gate(conn, ip=ip, now=now)
    try:
        row, user = _challenge_row(conn, cfg, body.token, now)
    except ApiError:
        code_check_failed(conn, ip=ip, now=now)  # a dead or forged token is a failed check of this IP too
        raise
    user_id = int(user["id"])
    code_row_id: int | None = None
    if body.password is not None:
        if user.get("password_set_at") is None:
            raise ApiError("second_factor_required")
        security.verify_account_password(conn, user, body.password, now=now)  # pwcheck:user:<id> budget, 401 on a wrong password; outside any transaction
    elif body.code is not None:
        if user.get("email_verified_at") is None or not user.get("email"):
            raise ApiError("second_factor_required")
        code_row_id = verify_code_checked(conn, cfg, channel="email", target=str(user["email"]), purpose="login", code=body.code, ip=ip, now=now, user_id=user_id)
    else:
        raise ApiError("second_factor_required")
    if user["role"] == "admin":
        raise ApiError("password_required")
    if not int(user["is_active"]):
        raise ApiError("account_disabled")
    with db.tx(conn):
        if not security.mark_login_code_used(conn, int(row["id"]), now):
            raise ApiError("challenge_expired")
        if code_row_id is not None and not security.mark_login_code_used(conn, code_row_id, now):
            raise ApiError("invalid_code", details={"attempts_left": 0})
        identity = security.identity_by_subject(conn, "phone", str(row["target"]))
        if identity is not None and int(identity["user_id"]) == user_id:
            conn.execute("UPDATE identities SET last_login_at = ? WHERE id = ?", (now_iso, identity["id"]))
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, user_id))
        security.gc_sessions(conn, now_iso)
        _issue_session(request, response, conn, user_id, now)
    log.info("stale phone login confirmed", extra={"event": "auth_stale_login_confirmed", "user_id": user_id})
    return _auth_payload(conn, user_id, now=now)


# ------------------------------------------------------------------------------------------------- 84
@router.post("/api/auth/challenge/dispute", status_code=201, response_model=AuthResponse)
def challenge_dispute(body: ChallengeDisputeRequest, request: Request, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    now_iso = to_iso(now)
    row, old_user = _challenge_row(conn, cfg, body.token, now)
    old_user_id = int(old_user["id"])
    target = str(row["target"])
    unusable = security.unusable_password_hash()  # bcrypt before the lock
    with db.tx(conn):
        if not security.mark_login_code_used(conn, int(row["id"]), now):
            raise ApiError("challenge_expired")
        identity = security.identity_by_subject(conn, "phone", target)
        if identity is None or int(identity["user_id"]) != old_user_id:
            raise ApiError("challenge_expired")  # the binding changed since the challenge was issued
        conn.execute("UPDATE identities SET disputed_at = ? WHERE id = ?", (now_iso, identity["id"]))
        new_user_id = create_code_account(conn, cfg, channel="phone", target=target, invite_code=body.invite_code, password_hash=unusable, now=now)
        system_event(conn, "phone_disputed", {"old_user_id": old_user_id, "new_user_id": new_user_id, "identity_id": int(identity["id"])}, now=now_iso)
        _issue_session(request, response, conn, new_user_id, now)
    log.info("phone binding disputed", extra={"event": "auth_phone_disputed", "user_id": new_user_id})
    mailer = mailer_of(request)
    if mailer is not None and old_user.get("email_verified_at") is not None and old_user.get("email"):
        text = f"你的手机号 {security.mask_phone(target)} 已被新的使用者注册；如非本人操作请联系管理员。\n\n你仍可用密码或邮箱验证码登录 word-Dance。"
        try:
            mailer.send(str(old_user["email"]), DISPUTE_NOTICE_SUBJECT, text)
        except MailerError:
            log.warning("dispute notice e-mail not sent", extra={"event": "phone_dispute_notice_failed", "user_id": old_user_id})
    return _auth_payload(conn, new_user_id, now=now)


# ------------------------------------------------------------------------------------------------- 90
def _reset_channel(request: Request, conn: sqlite3.Connection, user: dict[str, Any]) -> tuple[str, str] | None:
    """The channel a reset code goes to: the live phone identity when SMS is available, else the verified e-mail when a mailer is."""
    identity = security.phone_identity(conn, int(user["id"]))
    if identity is not None and sms_sender(request) is not None:
        return "phone", str(identity["subject"])
    if user.get("email_verified_at") is not None and user.get("email") and mailer_of(request) is not None:
        return "email", str(user["email"])
    return None


@router.post("/api/auth/password/forgot", status_code=202, response_model=CodeSendResponse)
def forgot_password(body: ForgotPasswordRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    ip = client_ip(request)
    captcha_gate(request, conn, cfg, body.captcha, now)
    # the IP window, counted exactly once per request — before the identifier is resolved, so an unknown one counts the same
    security.rate_limit(conn, f"code_send:ip:{ip}", limit=cfg.code_ip_hourly, window_s=CODE_SEND_IP_WINDOW_S, now=now)
    user = resolve_identifier(conn, body.identifier)
    route = _reset_channel(request, conn, user) if user is not None else None
    if user is None or route is None:
        return dict(SENT)  # unknown identifier or no verified channel: the same answer, nothing sent
    channel, target = route
    if not send_throttles(conn, cfg, channel=channel, target=target, ip=ip, now=now, silent_target=True, count_ip=False):
        return dict(SENT)  # the target's windows are exhausted: still 202
    issue_and_send_silently(request, conn, cfg, channel=channel, target=target, purpose="reset_password", user_id=int(user["id"]), ip=ip, now=now)
    return dict(SENT)  # a site-wide cap or a provider failure: still 202 (the admins see the budget events / the failure log)


# ------------------------------------------------------------------------------------------------- 91
@router.post("/api/auth/password/reset", status_code=204)
def reset_password(body: ResetPasswordRequest, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    cfg: Settings = request.app.state.settings
    now = request.app.state.clock.now_utc()
    ip = client_ip(request)
    code_check_gate(conn, ip=ip, now=now)
    user = resolve_identifier(conn, body.identifier)
    if user is None:
        code_check_failed(conn, ip=ip, now=now)  # an identifier without an account is a failed check like a wrong code
        raise ApiError("invalid_code", details={"attempts_left": 0})
    user_id = int(user["id"])
    # the newest live reset code of the account whatever its channel (target=None); outside any transaction; the IP window counts a failure
    row_id = verify_code_checked(conn, cfg, channel=None, target=None, purpose="reset_password", code=body.code, ip=ip, now=now, user_id=user_id, throttle_targets=())
    security.check_password(body.new_password, user["username"])
    new_hash = security.hash_password(body.new_password)  # bcrypt work before the write lock
    with db.tx(conn):
        if not security.mark_login_code_used(conn, row_id, now):
            raise ApiError("invalid_code", details={"attempts_left": 0})
        security.set_password(conn, user_id, new_hash, now, keep_token_hash=None)  # every session revoked, password_set_at stamped
        system_event(conn, "password_reset", {"user_id": user_id}, now=to_iso(now))
    log.info("password reset by code", extra={"event": "auth_password_reset", "user_id": user_id})
    return Response(status_code=204)
