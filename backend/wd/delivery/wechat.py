"""WeChat mini-program bridge — the provider adapter (API.md §3.3 endpoints 112–116; docs/AUTH_SIGNUP_DESIGN.md §5.3), the WeChat twin
of ``delivery/sms.py`` + ``delivery/aliyun.py``.

The names, signatures and docstrings here are what ``routers/auth_wechat.py``, ``wd/wechat_bridge.py`` and the tests build against.

* :class:`WechatClient` is the Protocol the routers call through ``app.state.wechat`` (built by :func:`wechat_client_from_settings`,
  None while the bridge is off → 409 ``provider_unconfigured``): ``code2session(js_code) -> openid`` and
  ``qr_png(scene, *, page, env_version) -> bytes``.
* :class:`WechatError` carries a ``kind`` from :data:`KINDS`: ``invalid_code`` (errcode 40029 / 40163 / 40226 — the ``js_code`` is bad,
  used or blocked → endpoint 115 answers 400 ``validation_error`` on ``fields.js_code``), ``config`` (40013 / 40125 — a wrong appid /
  secret → 502 ``provider_error`` and a log line the operator can act on), ``temporary`` (network, 5xx, -1 系统繁忙 → 502
  ``provider_error``). The provider's ``errcode`` goes to the log, never to the client.
* :class:`WechatApiClient` is the real client over ``httpx`` (:data:`TIMEOUT_S` 5 s, ``trust_env=False``):
  ``GET /sns/jscode2session?appid&secret&js_code&grant_type=authorization_code`` (the ``session_key`` and ``unionid`` in the answer
  are discarded — never logged, never stored), the stable access token ``POST /cgi-bin/stable_token {"grant_type":"client_credential",
  "appid","secret"}`` cached in memory until :data:`TOKEN_REFRESH_MARGIN_S` before ``expires_in``, and
  ``POST /wxa/getwxacodeunlimit?access_token=… {"scene","page","check_path":false,"env_version"}`` (a JSON body back means an error;
  :data:`TOKEN_EXPIRED_ERRCODES` 40001 / 42001 invalidate the cached token and retry once; the picture — WeChat serves it as JPEG — is
  re-encoded to PNG through Pillow, so endpoint 114 always answers ``image/png`` and a non-image answer is a ``temporary`` failure). The
  AppSecret is the first line of ``WD_WECHAT_SECRET_FILE``, read at call time by :func:`read_secret` (the ``aliyun.read_secret`` rules),
  never cached on the module and scrubbed from every message; a group / other-readable file is warned about ONCE per process and path
  (:data:`_MODE_WARNED`), not on every scan, token refresh and picture — ``config.py`` already says it at startup.
* :class:`FakeWechatClient` (``WD_AUTH_FAKE_PROVIDERS=1``, dev only — ``make smoke`` and a developer's browser): ``code2session`` → ``"wx_"
  + js_code`` (a code starting with ``bad`` → ``WechatError('invalid_code')``, ``down`` → ``'temporary'``); ``qr_png`` → a 300×300 PNG drawn
  with Pillow showing the scene text, so a developer can read the ticket off the "QR" (``fail_qr_with`` makes it raise instead — the
  114 → 502 path of the tests).

Nothing but ids ever reaches a log line: no openid, no ``js_code``, no ``session_key``, no secret.
"""

from __future__ import annotations

import io
import logging
import stat
import time
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

import httpx

from .. import __version__
from ..config import Settings

log = logging.getLogger("wd.delivery.wechat")

WECHAT_API = "https://api.weixin.qq.com"
TIMEOUT_S = 5.0  # the whole call (a scan runs inside the mini program's request; the 小程序码 inside the browser's)
CONNECT_TIMEOUT_S = 5.0
TOKEN_REFRESH_MARGIN_S = 300  # the stable access token is refreshed this long before its `expires_in`
DEFAULT_TOKEN_TTL_S = 7200  # WeChat's documented expires_in when the answer carries none
MESSAGE_MAX = 200  # the provider's errmsg in a WechatError / log line
KINDS: tuple[str, ...] = ("invalid_code", "config", "temporary")  # WechatError.kind
INVALID_CODE_ERRCODES: frozenset[int] = frozenset({40029, 40163, 40226})  # js_code invalid / already used / blocked (高风险用户)
CONFIG_ERRCODES: frozenset[int] = frozenset({40013, 40125})  # invalid appid / invalid secret
TOKEN_EXPIRED_ERRCODES: frozenset[int] = frozenset({40001, 42001})  # the cached access token is invalid / expired: refresh once and retry
FAKE_OPENID_PREFIX = "wx_"  # FakeWechatClient.code2session(js_code) == "wx_" + js_code
FAKE_QR_SIZE = 300  # FakeWechatClient.qr_png draws a FAKE_QR_SIZE × FAKE_QR_SIZE PNG
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: test hook: a factory returning the ``httpx.Client`` the real client uses (None = a real client, ``trust_env=False``)
CLIENT_FACTORY: Callable[[], httpx.Client] | None = None
#: the secret-file paths whose loose mode was already warned about in this process (``read_secret`` runs on every call)
_MODE_WARNED: set[str] = set()


class WechatError(Exception):
    """A WeChat call the provider refused or that failed on the way: ``kind`` ∈ :data:`KINDS`, ``code`` = the provider's ``errcode``
    when it answered (``None`` for a transport failure). The message never contains the ``js_code``, an openid or the secret."""

    def __init__(self, kind: str, message: str, *, code: int | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown WechatError kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.code = code


@runtime_checkable
class WechatClient(Protocol):
    """What endpoints 114 / 115 need from WeChat; raises :class:`WechatError` on failure."""

    def code2session(self, js_code: str) -> str:
        """``wx.login`` ``js_code`` → the mini-program ``openid`` (the ``session_key`` / ``unionid`` are dropped)."""
        ...

    def qr_png(self, scene: str, *, page: str, env_version: str) -> bytes:
        """The 小程序码 PNG (``getwxacodeunlimit``) that opens ``page`` with ``scene`` in ``env_version`` (release / trial / develop)."""
        ...


def read_secret(cfg: Settings) -> str | None:
    """The first line of ``WD_WECHAT_SECRET_FILE`` (``utf-8-sig``), read at call time; None when unset, unreadable or not a printable
    ASCII line (a warning names the problem class only — the ``delivery.aliyun.read_secret`` rules)."""
    path_text = str(getattr(cfg, "wechat_secret_file", "") or "").strip()
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077 and str(path) not in _MODE_WARNED:  # once per process: the file is read on every scan / token refresh / picture
            _MODE_WARNED.add(str(path))
            log.warning("WD_WECHAT_SECRET_FILE is readable by group/others (mode %o); chmod 600 it", mode)
        with path.open(encoding="utf-8-sig") as f:
            secret = f.readline().strip()
    except OSError as e:
        log.warning("WD_WECHAT_SECRET_FILE unreadable: %s", e.__class__.__name__, extra={"event": "wechat_secret_unreadable"})
        return None
    if not secret or not secret.isascii() or not secret.isprintable():
        log.warning("WD_WECHAT_SECRET_FILE holds no printable ASCII secret on its first line", extra={"event": "wechat_secret_unreadable"})
        return None
    return secret


def classify(errcode: int | None) -> str:
    """The closed vocabulary for a WeChat ``errcode`` (:data:`KINDS`): :data:`INVALID_CODE_ERRCODES` → ``invalid_code``,
    :data:`CONFIG_ERRCODES` → ``config``, everything else (``-1`` 系统繁忙, an unknown code, no code at all) → ``temporary``."""
    if errcode in INVALID_CODE_ERRCODES:
        return "invalid_code"
    if errcode in CONFIG_ERRCODES:
        return "config"
    return "temporary"


def scrub(text: str, *secrets_: str | None) -> str:
    """``text`` with every non-empty secret replaced by ``***``."""
    for s in secrets_:
        if s and text:
            text = text.replace(s, "***")
    return text


def _client(timeout_s: float = TIMEOUT_S) -> httpx.Client:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    return httpx.Client(trust_env=False, timeout=httpx.Timeout(float(timeout_s), connect=min(CONNECT_TIMEOUT_S, float(timeout_s))))


def _json_object(response: httpx.Response) -> dict[str, Any] | None:
    """The body as a dict when it is a JSON object, else None (a picture, an HTML page, an empty body)."""
    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type and "text" not in content_type and response.content[:1] != b"{":
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _errcode(data: dict[str, Any]) -> int | None:
    """WeChat's ``errcode`` as an int (``0`` / absent = success → None)."""
    try:
        code = int(data.get("errcode") or 0)
    except (TypeError, ValueError):
        return None
    return code or None


def as_png(image: bytes) -> bytes:
    """``image`` unchanged when it already is a PNG, else re-encoded to PNG through Pillow (WeChat serves the 小程序码 as JPEG); a body that
    is not an image at all raises ``WechatError('temporary')``."""
    if image[: len(PNG_MAGIC)] == PNG_MAGIC:
        return image
    try:
        from PIL import Image, UnidentifiedImageError

        with Image.open(io.BytesIO(image)) as img:
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise WechatError("temporary", f"getwxacodeunlimit: the answer is not an image ({e.__class__.__name__})") from e
    return buf.getvalue()


class WechatApiClient:
    """The real mini-program API client (``api.weixin.qq.com``) for ``WD_WECHAT_APPID`` + ``WD_WECHAT_SECRET_FILE``."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self._token: str | None = None  # the stable access token …
        self._token_expires_at: float = 0.0  # … and the monotonic instant it must be refreshed by (expires_in − TOKEN_REFRESH_MARGIN_S)

    @classmethod
    def from_settings(cls, cfg: Settings) -> "WechatApiClient | None":
        """The client when ``cfg.wechat_configured``, else None (a hand-built Settings without the pair gets None like the mailer)."""
        if not cfg.wechat_configured:
            return None
        return cls(cfg)

    @property
    def configured(self) -> bool:
        return True

    # ------------------------------------------------------------------------------------ transport
    def _secret(self) -> str:
        secret = read_secret(self.cfg)
        if not secret:
            raise WechatError("config", "WD_WECHAT_SECRET_FILE is not configured or unreadable")
        return secret

    def _request(self, method: str, path: str, *, secret: str, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> httpx.Response:
        client = _client()
        try:
            return client.request(
                method,
                f"{WECHAT_API}{path}",
                params=params,
                json=json,
                headers={"User-Agent": f"word-Dance/{__version__}", "Accept": "application/json, image/*"},
            )
        except (httpx.HTTPError, httpx.InvalidURL, OSError) as e:
            name = e.__class__.__name__
            log.warning("wechat %s failed on the way: %s", path, name, extra={"event": "wechat_api_error", "call": path, "kind": "temporary"})
            raise WechatError("temporary", scrub(f"{path}: {name}: {str(e)[:MESSAGE_MAX]}", secret)) from e
        finally:
            client.close()

    def _refused(self, data: dict[str, Any], call: str, secret: str) -> WechatError:
        code = _errcode(data)
        kind = classify(code)
        errmsg = scrub(str(data.get("errmsg") or "")[:MESSAGE_MAX], secret)
        log.warning("wechat %s refused: errcode %s (%s)", call, code, kind, extra={"event": "wechat_api_error", "call": call, "errcode": code, "kind": kind})
        return WechatError(kind, f"{call}: errcode {code}: {errmsg}", code=code)

    # ------------------------------------------------------------------------------------- the calls
    def access_token(self, *, force: bool = False) -> str:
        """The cached stable access token, fetched / refreshed with ``POST /cgi-bin/stable_token`` when missing, within
        :data:`TOKEN_REFRESH_MARGIN_S` of its expiry or when ``force`` is set (after a 40001 / 42001). Raises :class:`WechatError`."""
        if not force and self._token and time.monotonic() < self._token_expires_at:
            return self._token
        secret = self._secret()
        response = self._request(
            "POST",
            "/cgi-bin/stable_token",
            secret=secret,
            json={"grant_type": "client_credential", "appid": self.cfg.wechat_appid, "secret": secret, "force_refresh": bool(force)},
        )
        data = _json_object(response)
        if data is None:
            raise WechatError("temporary", f"stable_token: HTTP {response.status_code} without a JSON object body")
        token = data.get("access_token")
        if _errcode(data) is not None or not token:
            raise self._refused(data, "stable_token", secret)
        try:
            expires_in = int(data.get("expires_in") or DEFAULT_TOKEN_TTL_S)
        except (TypeError, ValueError):
            expires_in = DEFAULT_TOKEN_TTL_S
        self._token = str(token)
        self._token_expires_at = time.monotonic() + max(60, expires_in - TOKEN_REFRESH_MARGIN_S)
        return self._token

    def code2session(self, js_code: str) -> str:
        secret = self._secret()
        response = self._request(
            "GET",
            "/sns/jscode2session",
            secret=secret,
            params={"appid": self.cfg.wechat_appid, "secret": secret, "js_code": js_code, "grant_type": "authorization_code"},
        )
        data = _json_object(response)
        if data is None:
            raise WechatError("temporary", f"jscode2session: HTTP {response.status_code} without a JSON object body")
        if _errcode(data) is not None:
            raise self._refused(data, "jscode2session", secret)
        openid = data.get("openid")
        if not openid:
            raise WechatError("temporary", "jscode2session: no openid in the answer")
        return str(openid)  # session_key / unionid are dropped right here

    def qr_png(self, scene: str, *, page: str, env_version: str) -> bytes:
        secret = self._secret()
        token = self.access_token()
        for attempt in (0, 1):
            response = self._request(
                "POST",
                "/wxa/getwxacodeunlimit",
                secret=secret,
                params={"access_token": token},
                json={"scene": scene, "page": page, "check_path": False, "env_version": env_version},
            )
            data = _json_object(response)
            if data is not None:  # a JSON body back means an error
                if _errcode(data) in TOKEN_EXPIRED_ERRCODES and attempt == 0:
                    token = self.access_token(force=True)
                    continue
                raise self._refused(data, "getwxacodeunlimit", secret)
            if response.status_code >= 400 or not response.content:
                raise WechatError("temporary", f"getwxacodeunlimit: HTTP {response.status_code}")
            return as_png(response.content)
        raise WechatError("temporary", "getwxacodeunlimit: the token refresh did not help")  # pragma: no cover - the loop raised or returned


def fake_qr_png(scene: str, *, page: str = "", env_version: str = "") -> bytes:
    """A :data:`FAKE_QR_SIZE` × :data:`FAKE_QR_SIZE` PNG with three finder-like squares and the scene text, so a developer can read the
    ticket off the dev "QR" (the fake has no WeChat to scan it anyway)."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (FAKE_QR_SIZE, FAKE_QR_SIZE), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((6, 6, FAKE_QR_SIZE - 7, FAKE_QR_SIZE - 7), outline="black", width=3)
    for x, y in ((20, 20), (FAKE_QR_SIZE - 64, 20), (20, FAKE_QR_SIZE - 64)):
        draw.rectangle((x, y, x + 44, y + 44), outline="black", width=6)
        draw.rectangle((x + 14, y + 14, x + 30, y + 30), fill="black")
    try:
        font = ImageFont.load_default(size=13)
    except TypeError:  # pragma: no cover - Pillow < 10.1 has no size parameter
        font = ImageFont.load_default()
    lines = ("FAKE WECHAT MINI-PROGRAM CODE", "scene:", scene[:13], scene[13:], f"page: {page}"[:40], f"env: {env_version}"[:40])
    for i, line in enumerate(lines):
        draw.text((80, 88 + i * 18), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeWechatClient:
    """The dev / test double (``WD_AUTH_FAKE_PROVIDERS=1``; the integration tests install it as ``app.state.wechat``): deterministic
    openids (``"wx_" + js_code``; a ``js_code`` starting with ``bad`` → ``WechatError('invalid_code')``, ``down`` → ``'temporary'``) and a
    Pillow-drawn PNG that prints the scene text. ``calls`` records every ``(method, argument)`` pair for assertions; ``fail_qr_with`` (a
    :class:`WechatError`) makes ``qr_png`` raise it."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_qr_with: WechatError | None = None

    @property
    def configured(self) -> bool:
        return True

    def code2session(self, js_code: str) -> str:
        self.calls.append(("code2session", js_code))
        if js_code.startswith("bad"):
            raise WechatError("invalid_code", "fake WeChat: invalid js_code", code=40029)
        if js_code.startswith("down"):
            raise WechatError("temporary", "fake WeChat: 系统繁忙", code=-1)
        return FAKE_OPENID_PREFIX + js_code

    def qr_png(self, scene: str, *, page: str, env_version: str) -> bytes:
        self.calls.append(("qr_png", scene))
        if self.fail_qr_with is not None:
            raise self.fail_qr_with
        return fake_qr_png(scene, page=page, env_version=env_version)


def wechat_client_from_settings(cfg: Settings) -> WechatClient | None:
    """``app.state.wechat``: the real client when ``cfg.wechat_configured``, the :class:`FakeWechatClient` when ``cfg.auth_fake_providers``
    (dev only), else None (``ServerFlags.wechat_enabled`` false, endpoints 112–116 answer 409 ``provider_unconfigured``)."""
    if cfg.wechat_configured:
        return WechatApiClient.from_settings(cfg)
    if cfg.auth_fake_providers:
        return FakeWechatClient()
    return None


__all__ = [
    "CLIENT_FACTORY",
    "CONFIG_ERRCODES",
    "DEFAULT_TOKEN_TTL_S",
    "FAKE_OPENID_PREFIX",
    "FAKE_QR_SIZE",
    "FakeWechatClient",
    "INVALID_CODE_ERRCODES",
    "KINDS",
    "MESSAGE_MAX",
    "PNG_MAGIC",
    "TIMEOUT_S",
    "TOKEN_EXPIRED_ERRCODES",
    "TOKEN_REFRESH_MARGIN_S",
    "WECHAT_API",
    "WechatApiClient",
    "WechatClient",
    "WechatError",
    "as_png",
    "classify",
    "fake_qr_png",
    "read_secret",
    "scrub",
    "wechat_client_from_settings",
]
