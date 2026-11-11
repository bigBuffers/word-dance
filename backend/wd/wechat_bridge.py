"""The WeChat login bridge — tickets, pairing codes, poll cookie, ``mp_token`` and the request-context summaries behind API.md §3.3
endpoints 112–116 (docs/AUTH_SIGNUP_DESIGN.md §5.3; migration ``0020_wechat_tickets.sql``).

The constants and signatures here are binding for ``routers/auth_wechat.py`` and ``tests/unit/test_wechat_bridge.py``.

Mechanics:

* a **ticket** is :data:`TICKET_BYTES` random bytes as lower-case base32 without padding (26 chars, :data:`TICKET_RE`): the 小程序码
  scene, the poll path of 113 / 114 and the key of the row (``ticket_hash = sha256(ticket)``); it lives :data:`TICKET_TTL_S` (180 s);
* the **poll secret** travels in the HttpOnly cookie :data:`POLL_COOKIE` (``wd_wxt``; ``SameSite=Lax``, ``Secure`` like the session
  cookie, ``Path`` :data:`POLL_COOKIE_PATH`, ``Max-Age`` 180) and is stored as ``poll_hash = sha256(secret)`` — a poll without it is a 404
  identical to an unknown ticket;
* the **pairing code** (:data:`PAIR_CODE_LEN` digits, the mobile path: 「在微信里搜索小程序「单词之舞」，输入配对码」) is stored as
  ``pair_hash = HMAC-SHA256(WD_SECRET_KEY, "pair:" + code)`` and regenerated while a live (pending / scanned, unexpired) row has the same
  hash (:func:`unique_pairing_code` looks at live rows only); the hash stays on the row for its whole life — a mini program that paired
  by code names the code in its confirmation, and a second confirmation must find the finished row (409 ``wrong_state``, like the scene
  path) until the GC deletes it, so several rows may share a hash and endpoint 116 picks the one its ``mp_token`` verifies for;
* the **mp_token** proves a scan to endpoint 116 for :data:`MP_TOKEN_TTL_S` (300 s): ``f"{exp_unix}.{hmac_hex(WD_SECRET_KEY,
  f'mp:{ticket_id}:{openid}:{exp_unix}')}"`` — :func:`mp_token_verify` never raises: the head must be 1–12 ASCII digits and the
  comparison runs on bytes, so a full-width or otherwise non-ASCII token is simply False (401, never a 500);
* a confirmed / cancelled result is delivered by the poll (113) until ``expires_at`` + :data:`CONFIRM_GRACE_S` (60 s — a confirmation
  that landed a moment before expiry still reaches the next poll); past that the row is consumed unseen and the poll says ``expired``, so a
  captured ticket + poll cookie never mints a session later;
* the 小程序码 PNGs are cached per process (:class:`QrCache`, :data:`QR_CACHE_MAX` entries, expired entries evicted first);
* the confirmation page shows the initiating browser as :func:`web_ip_masked` (IPv4 with the last octet replaced by ``*``, IPv6 the
  first four groups + ``::*``) and :func:`web_ua_summary` (browser family Edge / Chrome / Firefox / Safari / WeChat / other + OS Windows
  / macOS / iOS / Android / Linux / other, e.g. ``Chrome · macOS``) — the User-Agent itself is stored truncated to :data:`WEB_UA_MAX`;
* rate limits (``security.rate_limit`` keys): ``wx_ticket:ip:<ip>:m`` :data:`TICKET_IP_MINUTE` / min and ``wx_ticket:ip:<ip>:h``
  :data:`TICKET_IP_HOUR` / h (112), ``wx_poll:ip:<ip>`` :data:`POLL_IP_MINUTE` / min (113 alone — 114, the 小程序码 picture, is not
  throttled: one image per ticket, bounded by ticket creation and served from the process cache), ``wx_scan:ip:<ip>``
  :data:`SCAN_IP_MINUTE` / min (115) and ``wx_confirm:ip:<ip>`` :data:`CONFIRM_IP_MINUTE` / min (116) — **flood brakes only**: in release
  every mini-program request reaches the server through the mainland relay host (deploy/relay/), whose single address is what
  ``deps.client_ip`` sees, so these two windows are site-wide caps and must stay wide; the brute-force brakes are per WeChat user —
  ``wx_scan:openid:<sha256(openid)[:32]>`` :data:`SCAN_OPENID_MINUTE` / min (115, after code2Session) and
  ``wx_confirm:openid:<sha256(openid)[:32]>`` :data:`CONFIRM_OPENID_MINUTE` / min (116, the ticket row's openid, counted before the
  ``mp_token`` is checked — :func:`openid_key`; the keys carry a hash so the openid never lands in ``auth_throttle``). The web windows are
  sized for a classroom behind one NAT (thirty sheets polling every 2 s);
* :func:`gc_tickets` runs from ``jobs.scheduler.hourly_gc`` next to ``family.gc_family_codes`` (rows expired or consumed more than a
  day ago — the ``login_codes`` rule); the one-time OAuth grants of ``wd.oauth_state`` are collected there too.

:func:`create_third_party_account` is re-exported from :mod:`wd.third_party` (the contract spells both ``wechat_bridge.…`` and
``third_party.…``); the account rules live there so QQ / Apple share them. Nothing but ids ever reaches a log line: no openid, no
ticket, no code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta

from . import db
from .clock import to_iso
from .config import Settings
from .third_party import create_third_party_account  # noqa: F401 — re-export (API.md §3.3 / PLAN §5.1 name)

log = logging.getLogger("wd.wechat_bridge")

TICKET_TTL_S = 180
TICKET_BYTES = 16  # → 26 base32 chars, lower-case, no padding
TICKET_RE = re.compile(r"^[a-z2-7]{26}$")
PAIR_CODE_LEN = 6
MP_TOKEN_TTL_S = 300
POLL_COOKIE = "wd_wxt"
POLL_COOKIE_PATH = "/api/auth/wechat/ticket"
QR_CACHE_MAX = 200
QR_CACHE_CONTROL = "private, max-age=180"  # endpoint 114
WEB_UA_MAX = 200  # wechat_tickets.web_ua is the User-Agent truncated to this
CONFIRM_GRACE_S = 60  # 113 delivers a confirmed / cancelled result until expires_at + this; later the row is consumed unseen (`expired`)
TICKET_IP_MINUTE = 30  # wx_ticket:ip:<ip>:m (112) — a classroom behind one NAT opening the sheet together
TICKET_IP_HOUR = 300  # wx_ticket:ip:<ip>:h (112) — every 3-minute refresh is a new ticket
POLL_IP_MINUTE = 1200  # wx_poll:ip (113 alone; 114 is not counted) — thirty sheets polling every 2 s behind one NAT
SCAN_IP_MINUTE = 600  # wx_scan:ip (115) — a flood brake only: behind the relay every mini-program request shares ONE client IP
SCAN_OPENID_MINUTE = 10  # wx_scan:openid (115, after code2Session) — the brute-force brake, per WeChat user
CONFIRM_IP_MINUTE = 600  # wx_confirm:ip (116) — a flood brake only, the relay's shared IP again
CONFIRM_OPENID_MINUTE = 20  # wx_confirm:openid (116, the ticket row's openid, counted before the token check) — per WeChat user
PAIR_HMAC_PREFIX = "pair:"  # pair_hash = HMAC(WD_SECRET_KEY, "pair:" + code)
MP_HMAC_PREFIX = "mp:"  # mp_token = f"{exp}.{HMAC(WD_SECRET_KEY, f'mp:{ticket_id}:{openid}:{exp}')}"
UA_BROWSERS: tuple[str, ...] = ("Edge", "Chrome", "Firefox", "Safari", "WeChat", "other")  # web_ua_summary vocabulary
UA_SYSTEMS: tuple[str, ...] = ("Windows", "macOS", "iOS", "Android", "Linux", "other")
LIVE_STATUSES: tuple[str, ...] = ("pending", "scanned")  # a live ticket (the scan finds it, the pairing code is reserved)
OPENID_KEY_HEX = 32  # wx_<scope>:openid:<sha256(openid)[:32]>
OPENID_KEY_SCOPES: tuple[str, ...] = ("scan", "confirm")  # openid_key(scope=…) → wx_scan:openid:… (115) / wx_confirm:openid:… (116)
MP_EXP_RE = re.compile(r"^[0-9]{1,12}$")  # the exp_unix head of an mp_token: ASCII digits only (str.isdigit accepts full-width digits)


def _hmac_hex(cfg: Settings, message: str) -> str:
    return hmac.new(cfg.secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def new_ticket() -> str:
    """A fresh ticket: :data:`TICKET_BYTES` random bytes, base32 lower-case without padding (26 chars matching :data:`TICKET_RE`)."""
    return base64.b32encode(secrets.token_bytes(TICKET_BYTES)).decode("ascii").lower().rstrip("=")


def ticket_hash(ticket: str) -> str:
    """``sha256(ticket)`` hex — ``wechat_tickets.ticket_hash``."""
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def new_poll_secret() -> str:
    """The random value of the ``wd_wxt`` cookie (urlsafe, ≥ 32 bytes of entropy)."""
    return secrets.token_urlsafe(32)


def poll_hash(secret: str) -> str:
    """``sha256(secret)`` hex — ``wechat_tickets.poll_hash``."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_pairing_code() -> str:
    """A random :data:`PAIR_CODE_LEN`-digit code (``secrets``-based, zero-padded)."""
    return f"{secrets.randbelow(10**PAIR_CODE_LEN):0{PAIR_CODE_LEN}d}"


def pair_hash(cfg: Settings, code: str) -> str:
    """``HMAC-SHA256(WD_SECRET_KEY, "pair:" + code)`` hex — ``wechat_tickets.pair_hash`` while the ticket is live."""
    return _hmac_hex(cfg, PAIR_HMAC_PREFIX + code)


def unique_pairing_code(conn: sqlite3.Connection, cfg: Settings, now: datetime) -> tuple[str, str]:
    """``(code, pair_hash)`` of a pairing code no live ticket (pending / scanned, ``expires_at > now``) currently uses — regenerated on a
    collision (endpoint 112). Called inside the ticket's ``BEGIN IMMEDIATE`` so two concurrent tickets cannot pick the same code."""
    now_iso = to_iso(now)
    while True:
        code = new_pairing_code()
        h = pair_hash(cfg, code)
        taken = conn.execute(
            "SELECT 1 FROM wechat_tickets WHERE pair_hash = ? AND status IN ('pending','scanned') AND expires_at > ?",
            (h, now_iso),
        ).fetchone()
        if taken is None:
            return code, h


def openid_key(openid: str, scope: str = "scan") -> str:
    """The ``wx_<scope>:openid:<…>`` throttle key of an openid (``scope`` ∈ :data:`OPENID_KEY_SCOPES`: ``scan`` for 115, ``confirm`` for
    116) — a hash prefix, so the pseudonymous id itself never lands in ``auth_throttle``."""
    if scope not in OPENID_KEY_SCOPES:
        raise ValueError(f"unknown openid key scope {scope!r}")
    return f"wx_{scope}:openid:{hashlib.sha256(openid.encode('utf-8')).hexdigest()[:OPENID_KEY_HEX]}"


def mp_token_sign(cfg: Settings, *, ticket_id: int, openid: str, exp_unix: int) -> str:
    """``f"{exp_unix}.{hmac_hex(WD_SECRET_KEY, f'mp:{ticket_id}:{openid}:{exp_unix}')}"`` — the scan proof endpoint 115 hands the mini
    program (``exp_unix`` = now + :data:`MP_TOKEN_TTL_S`)."""
    exp = int(exp_unix)
    return f"{exp}.{_hmac_hex(cfg, f'{MP_HMAC_PREFIX}{int(ticket_id)}:{openid}:{exp}')}"


def mp_token_verify(cfg: Settings, token: str, *, ticket_id: int, openid: str, now: datetime) -> bool:
    """True when ``token`` was signed by :func:`mp_token_sign` for exactly this ticket row and openid and its ``exp_unix`` is still in the
    future (constant-time compare; a malformed token is False, never an exception) — endpoint 116's 401 ``invalid_identity_token`` rule."""
    head, sep, sig = (token or "").strip().partition(".")
    if not sep or not sig or not MP_EXP_RE.match(head):  # ASCII digits only: int("１２３") would parse full-width digits
        return False
    try:
        exp_unix = int(head)
        if exp_unix <= int(now.timestamp()):
            return False
        expected = mp_token_sign(cfg, ticket_id=ticket_id, openid=openid, exp_unix=exp_unix)
        # bytes, not str: compare_digest raises TypeError for a non-ASCII str (a full-width hex digit in the signature)
        return hmac.compare_digest(expected.encode("utf-8"), f"{head}.{sig}".encode("utf-8"))
    except (TypeError, ValueError, UnicodeError):
        return False


def web_ip_masked(ip: str) -> str:
    """``203.0.113.7`` → ``203.0.113.*``; an IPv6 address → its first four groups + ``::*``; anything else → ``*``."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return "*"
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv4Address):
        return ".".join(str(addr).split(".")[:3]) + ".*"
    groups = addr.exploded.split(":")[:4]
    return ":".join(g.lstrip("0") or "0" for g in groups) + "::*"


def web_ua_summary(user_agent: str | None) -> str:
    """``<browser> · <OS>`` from a User-Agent (:data:`UA_BROWSERS` / :data:`UA_SYSTEMS` vocabulary; Edge before Chrome, Chrome before
    Safari, WeChat's ``MicroMessenger`` wins; iOS before macOS), e.g. ``Chrome · macOS``; ``other · other`` for an empty or unknown string."""
    low = (user_agent or "").lower()
    if "micromessenger" in low:
        browser = "WeChat"
    elif "edg/" in low or "edge/" in low or "edga/" in low or "edgios/" in low:
        browser = "Edge"
    elif "chrome/" in low or "crios/" in low or "chromium/" in low:
        browser = "Chrome"
    elif "firefox/" in low or "fxios/" in low:
        browser = "Firefox"
    elif "safari/" in low:
        browser = "Safari"
    else:
        browser = "other"
    if "windows" in low:
        system = "Windows"
    elif "iphone" in low or "ipad" in low or "ipod" in low:
        system = "iOS"
    elif "mac os x" in low or "macintosh" in low:
        system = "macOS"
    elif "android" in low:
        system = "Android"
    elif "linux" in low:
        system = "Linux"
    else:
        system = "other"
    return f"{browser} · {system}"


class QrCache:
    """Process-local ``{ticket_hash: (png, expires_at)}`` for endpoint 114, capped at :data:`QR_CACHE_MAX` entries: expired entries are
    evicted first, then the oldest, so a burst of tickets never grows it unbounded. ``expires_at`` is the ticket's ISO expiry. Guarded by a
    lock: FastAPI runs the sync route on threadpool threads."""

    def __init__(self, max_entries: int = QR_CACHE_MAX) -> None:
        self.max_entries = max_entries
        self._entries: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def get(self, ticket_hash: str, now: str) -> bytes | None:
        """The cached PNG while its ticket has not expired (``expires_at > now``), else None (and the entry is dropped)."""
        with self._lock:
            entry = self._entries.get(ticket_hash)
            if entry is None:
                return None
            png, expires_at = entry
            if expires_at <= now:
                self._entries.pop(ticket_hash, None)
                return None
            return png

    def put(self, ticket_hash: str, png: bytes, expires_at: str, now: str) -> None:
        """Store a PNG, evicting expired entries first and then the oldest beyond ``max_entries``."""
        with self._lock:
            for key in [k for k, (_, exp) in self._entries.items() if exp <= now]:
                del self._entries[key]
            self._entries.pop(ticket_hash, None)
            while self._entries and len(self._entries) >= max(1, int(self.max_entries)):
                self._entries.pop(next(iter(self._entries)))  # insertion order = oldest first
            self._entries[ticket_hash] = (png, expires_at)

    def __len__(self) -> int:
        return len(self._entries)


def gc_tickets(conn: sqlite3.Connection, now: datetime) -> int:
    """Delete ``wechat_tickets`` rows with ``expires_at <= now − 1 day`` or ``consumed_at <= now − 1 day`` (the ``login_codes`` rule: a used
    row stays a day as the audit trail) and return the count; called from ``jobs.scheduler.hourly_gc`` next to ``family.gc_family_codes``."""
    cutoff = to_iso(now - timedelta(days=1))
    with db.maybe_tx(conn):
        cur = conn.execute("DELETE FROM wechat_tickets WHERE expires_at <= ? OR (consumed_at IS NOT NULL AND consumed_at <= ?)", (cutoff, cutoff))
    return int(cur.rowcount)


__all__ = [
    "CONFIRM_GRACE_S",
    "CONFIRM_IP_MINUTE",
    "CONFIRM_OPENID_MINUTE",
    "LIVE_STATUSES",
    "MP_EXP_RE",
    "MP_HMAC_PREFIX",
    "MP_TOKEN_TTL_S",
    "OPENID_KEY_SCOPES",
    "PAIR_CODE_LEN",
    "PAIR_HMAC_PREFIX",
    "POLL_COOKIE",
    "POLL_COOKIE_PATH",
    "POLL_IP_MINUTE",
    "QR_CACHE_CONTROL",
    "QR_CACHE_MAX",
    "QrCache",
    "SCAN_IP_MINUTE",
    "SCAN_OPENID_MINUTE",
    "TICKET_BYTES",
    "TICKET_IP_HOUR",
    "TICKET_IP_MINUTE",
    "TICKET_RE",
    "TICKET_TTL_S",
    "UA_BROWSERS",
    "UA_SYSTEMS",
    "WEB_UA_MAX",
    "create_third_party_account",
    "gc_tickets",
    "mp_token_sign",
    "mp_token_verify",
    "new_pairing_code",
    "new_poll_secret",
    "new_ticket",
    "openid_key",
    "pair_hash",
    "poll_hash",
    "ticket_hash",
    "unique_pairing_code",
    "web_ip_masked",
    "web_ua_summary",
]
