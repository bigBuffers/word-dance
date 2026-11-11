"""Third-party identities shared by the WeChat bridge, QQ login and Sign in with Apple (API.md §3.3; docs/AUTH_SIGNUP_DESIGN.md §5.2 /
§5.3, slice 2-A) — the one place the three providers resolve an identity to an account, so they cannot drift.

The signatures and docstrings here are binding for ``routers/auth_wechat.py`` (116), ``routers/auth_oauth.py`` (119 / 121 — it only CALLS
these helpers and never edits this module), ``routers/account.py`` (117 / 89) and ``security.user_dto_for``.

* :data:`PROVIDERS` are the ``identities.provider`` values of this slice (the 0018 CHECK list already allows them; ``subject`` = the
  mini-program openid / the QQ openid / the Apple ``sub`` — pseudonymous ids shown to nobody).
* :func:`providers_of` feeds ``User.providers`` (``security.user_dto(row, *, phone=None, providers=(), now=None)`` emits the sorted
  list; ``user_dto_for`` fills it with ONE extra SELECT; ``admin_user_dto`` passes it through).
* :func:`ways_in` is the ``last_login_method`` rule of endpoint 117 (unbinding must leave ≥ 2 ways in; the existing 6 / 87 checks stay
  as they are): a password (``password_set_at``), a live phone identity, a verified e-mail, each third-party identity.
* :func:`create_third_party_account` mirrors ``auth_codes.create_code_account`` (which stays untouched) for an openid / sub:
  ``users_exist`` else 403 ``setup_required``; ``closed`` → 403 ``registration_closed``; ``invite`` → the ticket's / state's code must
  consume (``security.consume_invite``) else 403 ``invalid_invite``; ``open`` / ``verified`` consume a given code; placeholder username,
  ``password_set_at NULL``, ``display_name NULL``, ``account_kind 'learner'``, the identity row with ``verified_at = last_login_at = now``,
  ``UPDATE users SET last_login_at``; the bcrypt ``password_hash`` (``security.unusable_password_hash()``) is computed by the caller
  BEFORE the transaction.
* :func:`third_party_login_or_bind` is the endpoint-116 rule set used by 116 (WeChat), 119 (QQ) and 121 (Apple) inside the caller's
  ``BEGIN IMMEDIATE``: login — an existing identity → its account (admin → 403 ``password_required``, ``is_active = 0`` → 403
  ``account_disabled``), none → a new account; bind — the subject bound to another live account → 409 ``identity_taken``, bound to
  ``bind_user_id`` → idempotent, else ``INSERT identities(user_id, provider, subject, verified_at, last_login_at, created_at)``
  (``ux_identities_user_provider`` makes a second identity of the same provider on one account 409 ``identity_taken``;
  ``sqlite3.IntegrityError`` → 409 ``identity_taken``). Every ``identity_taken`` raised here carries the provider's wording
  (:data:`IDENTITY_TAKEN_ZH`: 「该微信已绑定其他账号」 / 「该 QQ 已绑定其他账号」 / 「该 Apple 账号已绑定其他账号」 — the catalogue's
  default is the phone sentence of endpoints 86 / 100) through :func:`identity_taken_error`, which the routers use for the
  ``IntegrityError`` they map themselves.
* :func:`third_party_only` is the endpoint-89 rule (``routers/account.save_profile``): a third-party-only account — no live phone
  identity, no verified e-mail, ``password_set_at IS NULL`` and at least one third-party identity — must set a password at step 0
  (400 ``validation_error``, ``details.fields.password`` = :data:`THIRD_PARTY_PASSWORD_ZH`).

This module imports ``security`` (``create_user`` / ``placeholder_username`` / ``consume_invite`` / ``identity_by_subject``); ``security``
imports it lazily inside ``user_dto_for``. Nothing but ids ever reaches a log line: no openid, no ``sub``.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Any, Callable, Mapping

from . import security
from .clock import to_iso
from .config import Settings
from .errors import ApiError

log = logging.getLogger("wd.third_party")

PROVIDERS: tuple[str, ...] = ("wechat_mini", "qq", "apple")  # == typing.get_args(schemas.ThirdPartyProvider)
THIRD_PARTY_PASSWORD_ZH = "用微信 / QQ / Apple 登录的账号请设置一个密码，修改资料或注销时用它验证身份"  # endpoint 89, details.fields.password
#: the 409 ``identity_taken`` message per provider (errors.CATALOGUE's default names a phone number — wrong for a WeChat / QQ / Apple identity)
IDENTITY_TAKEN_ZH: dict[str, str] = {"wechat_mini": "该微信已绑定其他账号", "qq": "该 QQ 已绑定其他账号", "apple": "该 Apple 账号已绑定其他账号"}
KINDS: tuple[str, ...] = ("login", "bind")  # third_party_login_or_bind(kind=…)
_PROVIDER_MARKS = ",".join("?" * len(PROVIDERS))


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown third-party provider {provider!r}")


def identity_taken_error(provider: str) -> ApiError:
    """``ApiError("identity_taken")`` with the provider's wording (:data:`IDENTITY_TAKEN_ZH`) — raised here and by the routers that map a
    ``sqlite3.IntegrityError`` of their own (116, 119, 121); an unknown provider keeps the catalogue text."""
    message = IDENTITY_TAKEN_ZH.get(provider)
    return ApiError("identity_taken", message_zh=message) if message else ApiError("identity_taken")


def _column(row: Mapping[str, Any], key: str) -> Any:
    """``row[key]`` or None — a ``sqlite3.Row`` raises IndexError and a dict KeyError for a column the row does not carry."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _has_live_phone(conn: sqlite3.Connection, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM identities WHERE user_id = ? AND provider = 'phone' AND disputed_at IS NULL", (int(user_id),)).fetchone() is not None


def _has_verified_email(row: Mapping[str, Any]) -> bool:
    return _column(row, "email_verified_at") is not None and bool(_column(row, "email"))


def providers_of(conn: sqlite3.Connection, user_id: int) -> list[str]:
    """The live (``disputed_at IS NULL``) identities of ``user_id`` whose provider is in :data:`PROVIDERS`, sorted — ``User.providers``."""
    rows = conn.execute(
        f"SELECT provider FROM identities WHERE user_id = ? AND disputed_at IS NULL AND provider IN ({_PROVIDER_MARKS}) ORDER BY provider",
        (int(user_id), *PROVIDERS),
    ).fetchall()
    return sorted(str(r[0]) for r in rows)


def ways_in(conn: sqlite3.Connection, user_row: Mapping[str, Any]) -> int:
    """How many ways this account can sign in: 1 for a password (``password_set_at IS NOT NULL``), 1 for a live phone identity, 1 for a
    verified e-mail (``email_verified_at``), 1 per live third-party identity — the ``last_login_method`` rule of endpoint 117 (the fresh
    row is re-read inside the transaction by the caller)."""
    uid = int(user_row["id"])
    ways = 0
    if _column(user_row, "password_set_at") is not None:
        ways += 1
    if _has_live_phone(conn, uid):
        ways += 1
    if _has_verified_email(user_row):
        ways += 1
    return ways + len(providers_of(conn, uid))


def third_party_only(conn: sqlite3.Connection, user_row: Mapping[str, Any]) -> bool:
    """Endpoint 89's rule: no live phone identity, no verified e-mail, ``password_set_at IS NULL`` and at least one third-party identity —
    such an account must send ``password`` at step 0 (the SPA mirrors the predicate from ``User`` fields)."""
    if _column(user_row, "password_set_at") is not None or _has_verified_email(user_row):
        return False
    uid = int(user_row["id"])
    if _has_live_phone(conn, uid):
        return False
    return bool(providers_of(conn, uid))


def create_third_party_account(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    provider: str,
    subject: str,
    invite_code: str | None,
    password_hash: str,
    now: datetime,
) -> int:
    """Create the learner account an openid / sub signs in with for the first time (inside the caller's ``BEGIN IMMEDIATE``) and return its
    id — the ``auth_codes.create_code_account`` rules (module docstring); ``password_hash`` is the pre-computed unusable bcrypt hash.
    Raises ``ApiError`` ``setup_required`` / ``registration_closed`` / ``invalid_invite``."""
    _check_provider(provider)
    if int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]) == 0:
        raise ApiError("setup_required")  # never an admin from a third party: the first account is a username + password (API.md 2)
    mode = cfg.registration_mode
    if mode == "closed":
        raise ApiError("registration_closed")
    if mode == "invite":
        if not invite_code or not security.consume_invite(conn, invite_code, now):
            raise ApiError("invalid_invite")
    elif invite_code and not security.consume_invite(conn, invite_code, now):
        raise ApiError("invalid_invite")
    now_iso = to_iso(now)
    user_id = security.create_user(
        conn,
        username=security.placeholder_username(conn),
        password_hash=password_hash,
        now=now,
        role="user",
        display_name=None,
        email=None,
        password_set_at=None,
    )
    conn.execute(
        "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, provider, subject, now_iso, now_iso, now_iso),
    )
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now_iso, user_id))
    log.info("third-party account created", extra={"event": "third_party_account_created", "provider": provider, "user_id": user_id})
    return user_id


def third_party_login_or_bind(
    conn: sqlite3.Connection,
    cfg: Settings,
    *,
    provider: str,
    subject: str,
    kind: str,
    bind_user_id: int | None,
    invite_code: str | None,
    password_hash_factory: Callable[[], str],
    now: datetime,
) -> tuple[int, bool]:
    """Resolve a verified third-party ``subject`` to an account inside the caller's ``BEGIN IMMEDIATE`` and return ``(user_id, created)``.

    ``kind`` is ``'login'`` or ``'bind'`` (``bind_user_id`` = the web session's user for ``bind``). Login: an existing live identity → its
    account (admin → 403 ``password_required``; disabled → 403 ``account_disabled``; the identity's and the user's ``last_login_at`` are
    refreshed by the session issuer, not here); none → :func:`create_third_party_account` with ``password_hash_factory()`` — callers
    that can afford it compute the bcrypt hash BEFORE the transaction and pass ``lambda: hash``; ``created`` is True then. Bind: the
    module docstring's ``identity_taken`` / idempotent / INSERT rules; ``created`` is False. ``sqlite3.IntegrityError`` → 409
    ``identity_taken``. Used by endpoints 116, 119 and 121.
    """
    _check_provider(provider)
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    identity = security.identity_by_subject(conn, provider, subject)
    if kind == "login":
        if identity is not None:
            user = security.load_user(conn, int(identity["user_id"]))
            if user is None:  # pragma: no cover - identities cascade with their user
                raise ApiError("internal_error")
            if user["role"] == "admin":
                raise ApiError("password_required")  # admins sign in with a password only (the endpoint-81 rule)
            if not int(user["is_active"]):
                raise ApiError("account_disabled")
            return int(user["id"]), False
        try:
            user_id = create_third_party_account(conn, cfg, provider=provider, subject=subject, invite_code=invite_code, password_hash=password_hash_factory(), now=now)
        except sqlite3.IntegrityError as e:  # a racing confirmation created the account for this subject first (ux_identities_live)
            raise identity_taken_error(provider) from e
        return user_id, True
    if bind_user_id is None:
        raise ValueError("kind='bind' needs bind_user_id")
    uid = int(bind_user_id)
    if identity is not None:
        if int(identity["user_id"]) == uid:
            return uid, False  # already bound to this account: idempotent
        raise identity_taken_error(provider)
    now_iso = to_iso(now)
    try:
        conn.execute(
            "INSERT INTO identities(user_id, provider, subject, verified_at, last_login_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, provider, subject, now_iso, now_iso, now_iso),
        )
    except sqlite3.IntegrityError as e:  # ux_identities_user_provider (a second identity of this provider on the account) or a racing bind of the subject
        raise identity_taken_error(provider) from e
    return uid, False


__all__ = [
    "IDENTITY_TAKEN_ZH",
    "KINDS",
    "PROVIDERS",
    "THIRD_PARTY_PASSWORD_ZH",
    "create_third_party_account",
    "identity_taken_error",
    "providers_of",
    "third_party_login_or_bind",
    "third_party_only",
    "ways_in",
]
