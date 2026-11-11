"""QQ 互联 (website OAuth 2.0) — the provider adapter of API.md §3.3 endpoints 118 / 119 (docs/AUTH_SIGNUP_DESIGN.md §5.3).

Slice 2-A: the names, signatures and docstrings here are what ``routers/auth_oauth.py`` and the tests build against.

* :class:`QQClient` is the Protocol the router calls through ``app.state.qq`` (built by :func:`qq_client_from_settings`, None while QQ
  login is off → 409 ``provider_unconfigured``): ``authorize_url(state)`` (the 302 target of 118), ``exchange(code) -> access_token``
  and ``openid(access_token) -> openid`` (119).
* :class:`QQError` carries a ``kind`` from :data:`KINDS`: ``invalid_code`` (the authorization code is unknown, used or expired, or the
  access token it produced is refused — the callback sends the browser back to the login page with ``?error=invalid_identity_token``),
  ``config`` (a wrong appid / key / redirect_uri → 502 ``provider_error`` and an actionable log line), ``temporary`` (network / 5xx /
  an unknown code → 502 ``provider_error``); :func:`classify` maps QQ 互联's numeric 公共返回码 to that vocabulary.
* :class:`QQApiClient` is the real client over ``httpx`` (:data:`TIMEOUT_S` 5 s, ``trust_env=False``): ``GET /oauth2.0/token?grant_type=
  authorization_code&client_id&client_secret&code&redirect_uri&fmt=json`` and ``GET /oauth2.0/me?access_token=…&fmt=json`` (the
  ``unionid`` is not requested) with the legacy ``callback( {...} );`` JSONP wrapper parsed as a fallback should ``fmt=json`` ever be
  ignored. The APP Key is the first line of ``WD_QQ_KEY_FILE`` (:func:`read_key`, the ``aliyun.read_secret`` rules), never cached on the
  module and scrubbed from every message.
* :class:`FakeQQClient` (``WD_AUTH_FAKE_PROVIDERS=1``, dev only): ``authorize_url`` → the fake consent page ``/api/auth/fake/qq?state=…``,
  ``exchange("qq-code-<x>")`` → ``"qq-token-<x>"``, ``openid("qq-token-<x>")`` → ``"qq_<x>"``; a code / token starting with ``bad`` →
  :class:`QQError`.

Nothing but ids ever reaches a log line: no openid, no code, no token, no key.
"""

from __future__ import annotations

import json
import logging
import re
import stat
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import parse_qs, quote, urlencode

import httpx

from .. import __version__
from ..config import Settings

log = logging.getLogger("wd.delivery.qq")

QQ_GRAPH = "https://graph.qq.com"
QQ_AUTHORIZE_URL = QQ_GRAPH + "/oauth2.0/authorize"
QQ_TOKEN_URL = QQ_GRAPH + "/oauth2.0/token"
QQ_ME_URL = QQ_GRAPH + "/oauth2.0/me"
QQ_SCOPE = "get_user_info"
TIMEOUT_S = 5.0
CONNECT_TIMEOUT_S = 5.0
KINDS: tuple[str, ...] = ("invalid_code", "config", "temporary")  # QQError.kind
FAKE_CONSENT_PATH = "/api/auth/fake/qq"  # routers/auth_fake.py (dev only)
FAKE_CODE_PREFIX = "qq-code-"  # FakeQQClient.exchange("qq-code-<x>") → "qq-token-<x>"
FAKE_TOKEN_PREFIX = "qq-token-"  # FakeQQClient.openid("qq-token-<x>") → "qq_<x>"
FAKE_OPENID_PREFIX = "qq_"
FAKE_BAD_PREFIX = "bad"  # a fake code / token starting with this → QQError('invalid_code'); "down" → 'temporary'
FAKE_DOWN_PREFIX = "down"
MESSAGE_MAX = 200
# QQ 互联 公共返回码 (wiki.connect.qq.com): the codes that mean "this code / token is not usable" (the user retries the login), the codes that
# mean "the application is misconfigured" (appid / key / redirect_uri — fix .env); everything else is temporary like aliyun.classify's rule:
# a retry later costs nothing
_INVALID_CODE_CODES = frozenset({"100013", "100014", "100015", "100016", "100019", "100020", "100021"})
_CONFIG_CODES = frozenset({"100001", "100002", "100003", "100004", "100005", "100006", "100007", "100008", "100009", "100010", "100031"})
_JSONP_RE = re.compile(r"^\s*callback\s*\(\s*(\{.*\})\s*\)\s*;?\s*$", re.DOTALL)

#: test hook: a factory returning the ``httpx.Client`` the real client uses (None = a real client, ``trust_env=False``)
CLIENT_FACTORY: Callable[[], httpx.Client] | None = None


class QQError(Exception):
    """A QQ 互联 call the provider refused or that failed on the way: ``kind`` ∈ :data:`KINDS`, ``code`` = the provider's ``error`` /
    ``code`` field when it answered (``None`` for a transport failure). The message never contains a code, a token, an openid or the key."""

    def __init__(self, kind: str, message: str, *, code: str | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown QQError kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.code = code


@runtime_checkable
class QQClient(Protocol):
    """What endpoints 118 / 119 need from QQ 互联; ``exchange`` / ``openid`` raise :class:`QQError` on failure."""

    def authorize_url(self, state: str) -> str:
        """The 302 target of endpoint 118 for this signed ``state`` (``response_type=code``, the registered ``redirect_uri``, :data:`QQ_SCOPE`)."""
        ...

    def exchange(self, code: str) -> str:
        """The callback's authorization ``code`` → an ``access_token``."""
        ...

    def openid(self, access_token: str) -> str:
        """``access_token`` → the application-scoped ``openid`` (the ``unionid`` is never requested)."""
        ...


def read_key(cfg: Settings) -> str | None:
    """The first line of ``WD_QQ_KEY_FILE`` (``utf-8-sig``), read at call time; None when unset, unreadable or not a printable ASCII
    line (a warning names the problem class only — the ``delivery.aliyun.read_secret`` rules)."""
    path_text = str(getattr(cfg, "qq_key_file", "") or "").strip()
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            log.warning("WD_QQ_KEY_FILE is readable by group/others (mode %o); chmod 600 it", mode)
        with path.open(encoding="utf-8-sig") as f:
            key = f.readline().strip()
    except OSError as e:
        log.warning("WD_QQ_KEY_FILE unreadable: %s", e.__class__.__name__, extra={"event": "qq_key_unreadable"})
        return None
    if not key or not key.isascii() or not key.isprintable():
        log.warning("WD_QQ_KEY_FILE holds no printable ASCII key on its first line", extra={"event": "qq_key_unreadable"})
        return None
    return key


def classify(code: str | None) -> str:
    """The :data:`KINDS` vocabulary for a QQ 互联 ``error`` code: ``invalid_code`` for an unusable authorization code / access token
    (100013–100016, 100019–100021), ``config`` for a wrong appid / key / redirect_uri (100001–100010, 100031), else ``temporary``."""
    c = str(code or "").strip()
    if c in _INVALID_CODE_CODES:
        return "invalid_code"
    if c in _CONFIG_CODES:
        return "config"
    return "temporary"


def parse_answer(text: str) -> dict[str, Any]:
    """The JSON object of a QQ 互联 answer: ``fmt=json`` gives plain JSON, the legacy ``/me`` answer is ``callback( {...} );`` (JSONP) and the
    legacy ``/token`` answer is ``access_token=…&expires_in=…`` (urlencoded, flattened to the first value). Anything else → ``{}``."""
    body = (text or "").strip()
    if not body:
        return {}
    try:
        data = json.loads(body)
        return data if isinstance(data, dict) else {}
    except ValueError:
        pass
    m = _JSONP_RE.match(body)
    if m:
        try:
            data = json.loads(m.group(1))
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    if "=" in body and "<" not in body:
        return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
    return {}


def _scrub(text: str, *secrets_: str | None) -> str:
    for secret in secrets_:
        if secret and text:
            text = text.replace(secret, "***")
    return text


def _client(timeout_s: float = TIMEOUT_S) -> httpx.Client:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    return httpx.Client(trust_env=False, timeout=httpx.Timeout(float(timeout_s), connect=min(CONNECT_TIMEOUT_S, float(timeout_s))))


class QQApiClient:
    """The real QQ 互联 client (``graph.qq.com``) for ``WD_QQ_APPID`` + ``WD_QQ_KEY_FILE`` + ``WD_QQ_CALLBACK_URL``."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg

    @classmethod
    def from_settings(cls, cfg: Settings) -> "QQApiClient | None":
        """The client when ``cfg.qq_configured``, else None (a hand-built Settings without the triple gets None like the mailer)."""
        if not cfg.qq_configured:
            return None
        return cls(cfg)

    @property
    def configured(self) -> bool:
        return True

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {"response_type": "code", "client_id": self.cfg.qq_appid, "redirect_uri": self.cfg.qq_callback_url, "state": state, "scope": QQ_SCOPE},
            quote_via=quote,
        )
        return f"{QQ_AUTHORIZE_URL}?{query}"

    def _get(self, url: str, params: dict[str, str], *, secrets_: tuple[str | None, ...]) -> dict[str, Any]:
        """One GET with the parameters in the query (QQ 互联 is GET-only); the parsed object, or :class:`QQError`. The key, the code and
        the token are scrubbed from every message."""
        client = _client()
        try:
            response = client.get(url, params=params, headers={"User-Agent": f"word-Dance/{__version__}", "Accept": "application/json"})
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as e:
            name = e.__class__.__name__
            raise QQError("temporary", _scrub(f"Network.{name}: {str(e)[:MESSAGE_MAX]}", *secrets_)) from e
        finally:
            client.close()
        data = parse_answer(response.text)
        error = data.get("error")
        if error is not None and str(error) not in ("", "0"):
            code = str(error)
            description = _scrub(str(data.get("error_description") or "")[:MESSAGE_MAX], *secrets_)
            raise QQError(classify(code), f"QQ error {code}: {description}", code=code)
        if response.status_code >= 400 or not data:
            raise QQError("temporary", f"HTTP {response.status_code} without a usable body", code=f"HTTP_{response.status_code}")
        return data

    def exchange(self, code: str) -> str:
        key = read_key(self.cfg)
        if not key:
            raise QQError("config", "WD_QQ_KEY_FILE is not configured or unreadable")
        data = self._get(
            QQ_TOKEN_URL,
            {"grant_type": "authorization_code", "client_id": self.cfg.qq_appid, "client_secret": key, "code": code, "redirect_uri": self.cfg.qq_callback_url, "fmt": "json"},
            secrets_=(key, code),
        )
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise QQError("temporary", "token answer without access_token")
        return token

    def openid(self, access_token: str) -> str:
        data = self._get(QQ_ME_URL, {"access_token": access_token, "fmt": "json"}, secrets_=(access_token,))
        openid = data.get("openid")
        if not isinstance(openid, str) or not openid:
            raise QQError("temporary", "me answer without openid")
        return openid


class FakeQQClient:
    """The dev / test double (``WD_AUTH_FAKE_PROVIDERS=1``; the integration tests install it as ``app.state.qq``): the consent page is
    ``routers/auth_fake.py``'s ``/api/auth/fake/qq``, codes / tokens / openids are derived from each other by prefix (see the module
    docstring), anything starting with ``bad`` raises :class:`QQError`. ``calls`` records every ``(method, argument)`` pair."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    @property
    def configured(self) -> bool:
        return True

    def authorize_url(self, state: str) -> str:
        self.calls.append(("authorize_url", state))
        return f"{FAKE_CONSENT_PATH}?{urlencode({'state': state})}"

    def exchange(self, code: str) -> str:
        self.calls.append(("exchange", code))
        if code.startswith(FAKE_DOWN_PREFIX):
            raise QQError("temporary", "fake QQ is down", code="HTTP_503")
        if code.startswith(FAKE_BAD_PREFIX) or not code.startswith(FAKE_CODE_PREFIX) or len(code) == len(FAKE_CODE_PREFIX):
            raise QQError("invalid_code", "fake QQ refused the code", code="100019")
        return FAKE_TOKEN_PREFIX + code[len(FAKE_CODE_PREFIX) :]

    def openid(self, access_token: str) -> str:
        self.calls.append(("openid", access_token))
        if access_token.startswith(FAKE_DOWN_PREFIX):
            raise QQError("temporary", "fake QQ is down", code="HTTP_503")
        if access_token.startswith(FAKE_BAD_PREFIX) or not access_token.startswith(FAKE_TOKEN_PREFIX) or len(access_token) == len(FAKE_TOKEN_PREFIX):
            raise QQError("invalid_code", "fake QQ refused the token", code="100016")
        return FAKE_OPENID_PREFIX + access_token[len(FAKE_TOKEN_PREFIX) :]


def qq_client_from_settings(cfg: Settings) -> QQClient | None:
    """``app.state.qq``: the real client when ``cfg.qq_configured``, the :class:`FakeQQClient` when ``cfg.auth_fake_providers`` (dev only),
    else None (``ServerFlags.qq_enabled`` false, endpoints 118 / 119 answer 409 ``provider_unconfigured``)."""
    if cfg.qq_configured:
        return QQApiClient.from_settings(cfg)
    if cfg.auth_fake_providers:
        return FakeQQClient()
    return None


__all__ = [
    "CLIENT_FACTORY",
    "FAKE_BAD_PREFIX",
    "FAKE_CODE_PREFIX",
    "FAKE_CONSENT_PATH",
    "FAKE_DOWN_PREFIX",
    "FAKE_OPENID_PREFIX",
    "FAKE_TOKEN_PREFIX",
    "FakeQQClient",
    "KINDS",
    "MESSAGE_MAX",
    "QQ_AUTHORIZE_URL",
    "QQ_GRAPH",
    "QQ_ME_URL",
    "QQ_SCOPE",
    "QQ_TOKEN_URL",
    "QQApiClient",
    "QQClient",
    "QQError",
    "TIMEOUT_S",
    "classify",
    "parse_answer",
    "qq_client_from_settings",
    "read_key",
]
