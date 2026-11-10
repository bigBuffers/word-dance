"""Aliyun POP RPC transport shared by the SMS sender (Dypnsapi 2017-05-25 ``SendSmsVerifyCode``, ``delivery/sms.py``) and the
DirectMail mailer (Dm 2015-11-23 ``SingleSendMail``, ``delivery/mailer.py``) — docs/AUTH_SIGNUP_DESIGN.md §5.4, DEPLOY §4
``WD_ALIYUN_ACCESS_KEY_ID`` / ``WD_ALIYUN_ACCESS_KEY_SECRET_FILE``.

Signature V1 (HMAC-SHA1 — the official SDKs' default, accepted by both gateways): every parameter except ``Signature`` is
percent-encoded per RFC 3986 (``A-Za-z0-9-_.~`` kept, space → ``%20``, ``*`` → ``%2A``), sorted by key into
``k1=v1&k2=v2…``, ``StringToSign = METHOD&%2F&encode(canonical)``, ``Signature = Base64(HMAC-SHA1(AccessKeySecret + "&",
StringToSign))``; the common parameters are ``Format=JSON``, ``SignatureMethod=HMAC-SHA1``, ``SignatureVersion=1.0``,
``SignatureNonce`` (uuid4), ``Timestamp`` (UTC ``%Y-%m-%dT%H:%M:%SZ``) and ``AccessKeyId``. Everything travels in the
``application/x-www-form-urlencoded`` body of a POST to ``https://<host>/`` — never in the URL, so the phone number, the plaintext
code and the key id cannot land in an ``httpx`` request log line (``logging_setup`` also silences that logger).

:func:`post` parses the JSON body on every status: a business refusal arrives as HTTP 400 *or* as HTTP 200 with ``Code != "OK"``
depending on the product, so the ``Code`` field decides; success is a 2xx whose body is a JSON object — a non-JSON answer (the
smoke mock's 404 text, a gateway 5xx page, an HTML page behind a 200, a 3xx) is an :class:`AliyunError` of kind ``temporary``.
The secret is read from the 0600 file at call time, never cached on the module, and scrubbed from every message; the gateway's
``Message`` is cut before the ``server string to sign is:`` echo (``SignatureDoesNotMatch`` repeats the whole signed request —
phone number, recipient, code and body) and capped at 200 characters; :func:`classify` maps a provider code to the closed
vocabulary ``rate_limited`` / ``invalid_target`` / ``config`` / ``temporary`` the senders turn into API errors. ``CLIENT_FACTORY``
is the test hook (``tests/fake_aliyun.py`` builds an ``httpx.MockTransport``); the real client runs with ``trust_env=False`` and a
10 s budget.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

import httpx

from .. import __version__
from ..config import Settings

log = logging.getLogger("wd.delivery.aliyun")

SMS_HOST = "dypnsapi.aliyuncs.com"  # 号码认证 (Dypnsapi 2017-05-25): one public endpoint for every region
DM_HOST = "dm.aliyuncs.com"  # DirectMail (Dm 2015-11-23), cn-hangzhou
TIMEOUT_S = 10.0  # the whole call (the webhook precedent); a code send runs inside the request thread
CONNECT_TIMEOUT_S = 5.0
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MESSAGE_MAX = 200  # the gateway's Message, after the StringToSign echo is cut: enough for the human-readable sentence
STRING_TO_SIGN_ECHO = "server string to sign is"  # SignatureDoesNotMatch appends the whole signed request after this
KINDS: tuple[str, ...] = ("rate_limited", "invalid_target", "config", "temporary")  # classify() vocabulary; sms.SmsError.kind

#: test hook: a factory returning the ``httpx.Client`` :func:`post` uses (None = a real client, ``trust_env=False``)
CLIENT_FACTORY: Callable[[], httpx.Client] | None = None

# provider codes (Dypnsapi + Dm + the POP gateway), matched case-insensitively on the last dotted segment — Aliyun spells the same
# refusal `FREQUENCY_FAIL`, `biz.FREQUENCY` and `isv.BUSINESS_LIMIT_CONTROL` across its pages, so suffixes are what we compare
_RATE_LIMITED_TOKENS = ("frequency", "limit_control", "qps_limit", "limitexceeded", "throttling", "invalidsendsms", "invalidquota")
_RATE_LIMITED_PREFIXES = ("interval",)
_INVALID_TARGET = ("mobile_number_illegal", "invalidtoaddress", "invalidreceivername")  # the NUMBER / ADDRESS is wrong — nothing else
_CONFIG = (
    "function_not_opened",
    "product_unsubscribe",
    "product_un_subscript",  # the other spelling on the shared SMS error-code page
    "out_of_service",
    "amount_not_enough",
    "invalid_parameters",  # a request parameter (SignName / TemplateCode / TemplateParam / ValidTime), never the number: that is MOBILE_NUMBER_ILLEGAL
    "invalid_json_param",
    "sms_signature_illegal",  # WD_ALIYUN_SMS_SIGN_NAME is not a signature of this account
    "sms_template_illegal",
    "template_params_illegal",
    "template_missing_parameters",
    "account_not_exists",
    "account_abnormal",
    "security_frozen_account",
    "ram_permission_deny",
    "deny_ip_range",
    "sms_test_number_limit",  # a test-mode account may only send to its bound test numbers
    "invalidaccesskeyid",
    "signaturedoesnotmatch",
    "invalidtimestamp",
    "forbidden",
    "invalidmailaddress",
    "invalidmailaddressstatus",
    "invalidsendmail",
    "invalidsubject",
    "invalidfromalias",
    "missingparameter",
    "invalidparameter",
    "unsupportedparameter",
    "missingcredentials",
    "invalidaction",
    "invalidversion",
)


class AliyunError(Exception):
    """A refused or failed call: ``code`` (the provider's ``Code``, or ``Network.<Exception>`` / ``HTTP_<status>``), the scrubbed
    ``message``, ``request_id`` / ``http_status`` when the gateway answered, and ``kind`` from :func:`classify`."""

    def __init__(self, code: str, message: str, *, request_id: str | None = None, http_status: int | None = None, retry_after_s: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.request_id = request_id
        self.http_status = http_status
        self.retry_after_s = retry_after_s

    @property
    def kind(self) -> str:
        return classify(self.code)


def percent_encode(value: Any) -> str:
    """RFC 3986 encoding as the Aliyun signature wants it: unreserved ``A-Za-z0-9-_.~`` kept, ``*`` → ``%2A``, space → ``%20``."""
    return quote(_stringify(value), safe="-_.~").replace("*", "%2A")


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def canonical_query(params: Mapping[str, Any]) -> str:
    """``k1=v1&k2=v2…`` over every parameter except ``Signature``, sorted by key, both sides percent-encoded."""
    return "&".join(f"{percent_encode(k)}={percent_encode(v)}" for k, v in sorted(params.items()) if k != "Signature")


def string_to_sign(method: str, params: Mapping[str, Any]) -> str:
    return f"{method.upper()}&{percent_encode('/')}&{percent_encode(canonical_query(params))}"


def sign_rpc_v1(method: str, params: Mapping[str, Any], access_key_id: str, secret: str, *, now: datetime, nonce: str) -> dict[str, str]:
    """The API parameters plus the V1 common parameters and the ``Signature`` — ready to be sent as the form body."""
    out: dict[str, str] = {k: _stringify(v) for k, v in params.items() if k != "Signature"}
    out.update(
        {
            "Format": "JSON",
            "SignatureMethod": "HMAC-SHA1",
            "SignatureVersion": "1.0",
            "SignatureNonce": nonce,
            "Timestamp": now.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT),
            "AccessKeyId": access_key_id,
        }
    )
    digest = hmac.new((secret + "&").encode("utf-8"), string_to_sign(method, out).encode("utf-8"), hashlib.sha1).digest()
    out["Signature"] = base64.b64encode(digest).decode("ascii")
    return out


def read_secret(cfg: Settings) -> str | None:
    """The first line of ``WD_ALIYUN_ACCESS_KEY_SECRET_FILE`` (``utf-8-sig``), read at call time; None when unset, unreadable or
    empty (a warning names the problem class only). Mirrors ``ai/providers/openai_http.api_key``: group/other-readable → chmod hint."""
    path_text = str(getattr(cfg, "aliyun_access_key_secret_file", "") or "").strip()
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            log.warning("WD_ALIYUN_ACCESS_KEY_SECRET_FILE is readable by group/others (mode %o); chmod 600 it", mode)
        with path.open(encoding="utf-8-sig") as f:
            secret = f.readline().strip()
    except OSError as e:
        log.warning("WD_ALIYUN_ACCESS_KEY_SECRET_FILE unreadable: %s", e.__class__.__name__, extra={"event": "aliyun_secret_unreadable"})
        return None
    if not secret or not secret.isascii() or not secret.isprintable():
        log.warning("WD_ALIYUN_ACCESS_KEY_SECRET_FILE holds no printable ASCII secret on its first line", extra={"event": "aliyun_secret_unreadable"})
        return None
    return secret


def classify(code: str) -> str:
    """The closed vocabulary for a provider ``Code`` (:data:`KINDS`): ``rate_limited`` (FREQUENCY_FAIL / biz.FREQUENCY / Interval* /
    BUSINESS_LIMIT_CONTROL / QPS_LIMIT / Throttling* / LimitExceeded* / InvalidQuota), ``invalid_target`` (MOBILE_NUMBER_ILLEGAL /
    InvalidToAddress* / InvalidReceiverName* — the number or address itself), ``config`` (FUNCTION_NOT_OPENED /
    isv.PRODUCT_UNSUBSCRIBE / OUT_OF_SERVICE / AMOUNT_NOT_ENOUGH / INVALID_PARAMETERS / isv.SMS_SIGNATURE_ILLEGAL /
    isv.SMS_TEMPLATE_ILLEGAL / isv.TEMPLATE_PARAMS_ILLEGAL / isp.RAM_PERMISSION_DENY / isv.ACCOUNT_* / InvalidAccessKeyId* /
    SignatureDoesNotMatch / InvalidTimeStamp* / Forbidden* / InvalidMailAddress* / Missing- / InvalidParameter …), else
    ``temporary`` (5xx, network, timeout, an unknown code — the blacklist codes included: a retry later costs nothing)."""
    c = (code or "").strip()
    cl = c.lower()
    head = cl.split(".", 1)[0]
    tail = cl.rsplit(".", 1)[-1]
    if any(token in cl for token in _RATE_LIMITED_TOKENS) or tail.startswith(_RATE_LIMITED_PREFIXES) or head.startswith(("throttling", "limitexceeded", *_RATE_LIMITED_PREFIXES)):
        return "rate_limited"
    if tail in _INVALID_TARGET or head in _INVALID_TARGET:
        return "invalid_target"
    if tail in _CONFIG or head in _CONFIG or head.startswith(("invalidaccesskeyid", "forbidden", "invalidmailaddress", "invalidtimestamp")):
        return "config"
    return "temporary"


def scrub(text: str, *secrets_: str | None) -> str:
    """``text`` with every non-empty secret replaced by ``***`` (the key id and the secret; callers may add a recipient)."""
    for s in secrets_:
        if s and text:
            text = text.replace(s, "***")
    return text


def gateway_message(message: str, code: str) -> str:
    """The gateway's ``Message`` fit for a log line: cut before the ``server string to sign is:`` echo (``SignatureDoesNotMatch``
    repeats every signed parameter — PhoneNumber, ToAddress, TemplateParam with the code, TextBody), the code itself when nothing
    readable is left, and at most :data:`MESSAGE_MAX` characters. The ``RequestId`` is kept separately for the console search."""
    head = message.split(STRING_TO_SIGN_ECHO, 1)[0].rstrip(" :.") if message else ""
    return (head or code)[:MESSAGE_MAX]


def _client(timeout_s: float) -> httpx.Client:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY()
    return httpx.Client(trust_env=False, timeout=httpx.Timeout(float(timeout_s), connect=min(CONNECT_TIMEOUT_S, float(timeout_s))))


def post(host: str, params: Mapping[str, Any], cfg: Settings, *, timeout_s: float = TIMEOUT_S, now: datetime | None = None) -> dict[str, Any]:
    """One signed ``POST https://<host>/`` with ``params`` in the form body; returns the JSON body (a dict) on success.

    Success = a 2xx status whose body is a JSON object with no ``Code`` or ``Code == "OK"`` (DirectMail answers ``{EnvId, RequestId}``,
    the SMS API ``{Code: "OK", …}``). Everything else raises :class:`AliyunError` with the provider's ``Code`` / ``Message`` /
    ``RequestId`` (``HTTP_<status>`` for a body without a code — a 3xx, an HTML page behind a 200 or a 5xx —, ``Network.<Exception>``
    for a transport failure); the secret never appears in it and the ``Message`` is cut by :func:`gateway_message`.
    """
    secret = read_secret(cfg)
    key_id = str(getattr(cfg, "aliyun_access_key_id", "") or "").strip()
    if not key_id or not secret:
        raise AliyunError("MissingCredentials", "WD_ALIYUN_ACCESS_KEY_ID / WD_ALIYUN_ACCESS_KEY_SECRET_FILE are not configured or unreadable")
    signed = sign_rpc_v1("POST", params, key_id, secret, now=now or datetime.now(timezone.utc), nonce=uuid.uuid4().hex)
    client = _client(timeout_s)
    try:
        response = client.post(
            f"https://{host}/",
            data=signed,
            headers={"User-Agent": f"word-Dance/{__version__}", "Accept": "application/json"},
        )
    except (httpx.HTTPError, httpx.InvalidURL, OSError) as e:
        name = e.__class__.__name__
        raise AliyunError(f"Network.{name}", scrub(f"{name}: {str(e)[:MESSAGE_MAX]}", secret, key_id)) from e
    finally:
        client.close()
    text = response.text
    try:
        data = response.json()
    except ValueError:
        data = None
    is_object = isinstance(data, dict)
    if not is_object:
        data = {}
    code = str(data.get("Code") or "")
    request_id = data.get("RequestId")
    status = response.status_code
    if status >= 400 or (code and code.upper() != "OK") or not (200 <= status < 300) or not is_object:
        # a refusal (its Code decides), or an answer that is not a success: a 3xx, a 2xx without a JSON object (an HTML page from a
        # middlebox) — treating those as sent would log `sms_sent` / `email_sent` for a code nobody receives
        if data.get("Message"):
            message = gateway_message(str(data["Message"]), code)
        elif is_object:
            message = f"HTTP {status}"
        else:
            message = f"HTTP {status} without a JSON object body" + (f": {text[:MESSAGE_MAX]}" if text.strip() else "")
        raise AliyunError(
            code or f"HTTP_{status}",
            scrub(message, secret, key_id),
            request_id=str(request_id) if request_id else None,
            http_status=status,
        )
    return data


__all__ = [
    "AliyunError",
    "CLIENT_FACTORY",
    "DM_HOST",
    "KINDS",
    "MESSAGE_MAX",
    "SMS_HOST",
    "TIMEOUT_S",
    "canonical_query",
    "classify",
    "gateway_message",
    "percent_encode",
    "post",
    "read_secret",
    "scrub",
    "sign_rpc_v1",
    "string_to_sign",
]
