"""SMS verification codes (API.md 80 / 85 / 90; docs/AUTH_SIGNUP_DESIGN.md §5.4) — the phone twin of ``delivery/mailer.py``.

* :class:`SmsSender` is the Protocol the routers call through ``app.state.sms`` (built by :func:`sms_sender_from_settings`, None
  while ``WD_SMS_PROVIDER=off`` → 409 ``sms_unconfigured``): ``send_code(to_e164, code, template, *, minutes)`` raises
  :class:`SmsError` with a ``kind`` from ``delivery.aliyun.KINDS`` — ``rate_limited`` (the provider's own frequency / daily
  controls; the route answers 429 ``rate_limited`` with ``retry_after_s``), ``invalid_target`` (400 ``invalid_phone``),
  ``config`` / ``temporary`` (503 ``sms_send_failed``).
* :class:`AliyunVerifySender` is 阿里云号码认证 ``SendSmsVerifyCode`` with the system signature (``WD_ALIYUN_SMS_SIGN_NAME``) and
  the gifted templates (:data:`TEMPLATE_BY_PURPOSE`): the code is OURS (``TemplateParam {"code": …, "min": …}``, so the provider
  never checks it — ``login_codes`` does), ``ValidTime`` matches the code's 10 minutes, ``Interval=60`` mirrors the per-target
  1/min throttle. Nothing but the masked number ever reaches a log line.
* :class:`RecordingSmsSender` is the test double (``.sent``, ``.fail_with``), installed as ``app.state.sms`` like ``RecordingMailer``.

Sending is synchronous inside the request (no job type: ``jobs.type`` is a frozen CHECK list) and never under a transaction.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, NamedTuple, Protocol, runtime_checkable

from ..clock import day_start, local_date
from ..config import Settings
from . import aliyun

log = logging.getLogger("wd.delivery.sms")

#: the gifted 号码认证 templates by code purpose (docs/AUTH_SIGNUP_EVIDENCE.md R3-12): 登录/注册 · 修改绑定手机号 · 重置密码 · 绑定新手机号 · 验证绑定手机号
TEMPLATE_BY_PURPOSE: dict[str, str] = {"login": "100001", "rebind_phone": "100002", "reset_password": "100003", "bind_phone": "100004", "reauth": "100005"}
INTERVAL_S = 60  # the provider's same-number interval control — equals the local code_send:target 1/min window
FREQUENCY_RETRY_S = 60  # retry hint for a frequency refusal (FREQUENCY_FAIL / Interval*)
THROTTLING_RETRY_S = 5  # retry hint for the gateway's QPS / flow control (Throttling.* / *QPS_LIMIT): it clears within seconds
_DAY_LIMIT_TOKENS = ("business_limit_control", "day_limit_control", "month_limit_control")  # the number's daily / monthly quota
_THROTTLING_TOKENS = ("throttling", "qps_limit")
KINDS = aliyun.KINDS

#: test hook: the clock the retry hints are computed against
CLOCK: Callable[[], datetime] = lambda: datetime.now(timezone.utc)  # noqa: E731


class SmsError(Exception):
    """A send the provider refused or that failed on the way: ``kind`` ∈ :data:`KINDS`, ``retry_after_s`` for ``rate_limited``,
    ``code`` = the provider's ``Code`` when it answered. The message never contains the full number or the code."""

    def __init__(self, kind: str, message: str, *, retry_after_s: int | None = None, code: str | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown SmsError kind {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.retry_after_s = retry_after_s
        self.code = code


@runtime_checkable
class SmsSender(Protocol):
    """Sends one verification code; raises :class:`SmsError` on failure."""

    def send_code(self, to_e164: str, code: str, template: str, *, minutes: int) -> None: ...


class SentSms(NamedTuple):
    to: str
    code: str
    template: str
    minutes: int


def mainland_digits(to_e164: str) -> str | None:
    """``+8613800138000`` → ``13800138000`` (the ``PhoneNumber`` parameter); None unless it is a mainland mobile number
    (another country code behind the ``+`` is refused even when its digits happen to look like one)."""
    raw = (to_e164 or "").strip()
    if raw.startswith("+") and not raw.startswith("+86"):
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits if len(digits) == 11 and digits.startswith("1") else None


def mask(to_e164: str) -> str:
    digits = mainland_digits(to_e164) or re.sub(r"\D", "", to_e164 or "")
    return f"{digits[:3]}****{digits[-4:]}" if len(digits) >= 7 else "****"


def retry_after_for(code: str, kind: str, now: datetime, *, tz: str = "Asia/Shanghai") -> int | None:
    """``rate_limited`` hints (``details.retry_after_s`` of the 429): a frequency refusal (FREQUENCY_FAIL / Interval*) →
    :data:`FREQUENCY_RETRY_S`; the number's daily / monthly quota (BUSINESS_LIMIT_CONTROL 「触发号码天级流控」, *DAY_LIMIT_CONTROL,
    *MONTH_LIMIT_CONTROL) → the seconds to the next ``tz`` (``WD_TZ``) day — the provider's day, and every earlier retry would only
    spend our own caps (a refused request counts, API.md 80); the gateway's QPS / flow control (Throttling.*, *QPS_LIMIT) →
    :data:`THROTTLING_RETRY_S`; any other limit → the next full hour (our hourly budget window turns then too). None for the other
    kinds."""
    if kind != "rate_limited":
        return None
    cl = (code or "").lower()
    if "frequency" in cl or cl.split(".", 1)[0].startswith("interval") or cl.rsplit(".", 1)[-1].startswith("interval"):
        return FREQUENCY_RETRY_S
    if any(token in cl for token in _THROTTLING_TOKENS):
        return THROTTLING_RETRY_S
    now = now.astimezone(timezone.utc)
    if any(token in cl for token in _DAY_LIMIT_TOKENS):
        next_day = day_start(local_date(now, tz) + timedelta(days=1), tz)
        return max(1, int((next_day - now).total_seconds()))
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return max(1, int((next_hour - now).total_seconds()))


class AliyunVerifySender:
    """阿里云号码认证 ``SendSmsVerifyCode`` (Dypnsapi 2017-05-25, host ``dypnsapi.aliyuncs.com``) with the system signature."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.last_result: dict[str, Any] | None = None  # the provider's Code / Message / RequestId / BizId of the last call (``wd sms-probe`` prints it)

    @classmethod
    def from_settings(cls, cfg: Settings) -> "AliyunVerifySender | None":
        if cfg.sms_provider != "aliyun_verify":
            return None
        if not (cfg.aliyun_access_key_id and cfg.aliyun_access_key_secret_file and cfg.aliyun_sms_sign_name):
            return None  # Settings.from_env refuses this combination; a hand-built Settings gets None like the mailer
        return cls(cfg)

    @property
    def configured(self) -> bool:
        return True

    def send_code(self, to_e164: str, code: str, template: str, *, minutes: int) -> None:
        digits = mainland_digits(to_e164)
        if digits is None:
            raise SmsError("invalid_target", "not a mainland mobile number")
        out_id = secrets.token_hex(8)  # echoed by the provider: correlates our log line with the console without the number
        params = {
            "Action": "SendSmsVerifyCode",
            "Version": "2017-05-25",
            "PhoneNumber": digits,
            "CountryCode": "86",
            "SignName": self.cfg.aliyun_sms_sign_name,
            "TemplateCode": template,
            "TemplateParam": json.dumps({"code": code, "min": str(int(minutes))}, separators=(",", ":")),
            "ValidTime": str(int(minutes) * 60),
            "Interval": str(INTERVAL_S),
            "ReturnVerifyCode": "false",
            "OutId": out_id,
        }
        now = CLOCK()
        try:
            data = aliyun.post(aliyun.SMS_HOST, params, self.cfg, now=now)
        except aliyun.AliyunError as e:
            message = e.message.replace(digits, mask(to_e164)).replace(code, "******")
            self.last_result = {"Code": e.code, "Message": message, "RequestId": e.request_id}
            log.warning("sms send refused: %s (%s), out_id %s", e.code, e.kind, out_id, extra={"event": "sms_send_failed", "provider": "aliyun_verify"})
            raise SmsError(e.kind, f"{e.code}: {message}", retry_after_s=retry_after_for(e.code, e.kind, now, tz=self.cfg.tz), code=e.code) from e
        model = data.get("Model") if isinstance(data.get("Model"), dict) else {}
        self.last_result = {"Code": data.get("Code"), "Message": data.get("Message"), "RequestId": data.get("RequestId"), "BizId": model.get("BizId")}
        log.info("sms code sent, out_id %s", out_id, extra={"event": "sms_sent", "provider": "aliyun_verify"})


class RecordingSmsSender:
    """Test double: records every code; ``fail_with`` (an :class:`SmsError`) makes ``send_code`` raise it."""

    def __init__(self) -> None:
        self.sent: list[SentSms] = []
        self.fail_with: SmsError | None = None

    @property
    def configured(self) -> bool:
        return True

    def send_code(self, to_e164: str, code: str, template: str, *, minutes: int) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append(SentSms(to=to_e164, code=code, template=template, minutes=minutes))


def sms_sender_from_settings(cfg: Settings) -> SmsSender | None:
    """The production sender for ``WD_SMS_PROVIDER``, or None while it is ``off`` (``ServerFlags.sms_enabled`` false)."""
    if cfg.sms_provider == "aliyun_verify":
        return AliyunVerifySender.from_settings(cfg)
    return None


__all__ = [
    "AliyunVerifySender",
    "CLOCK",
    "INTERVAL_S",
    "KINDS",
    "RecordingSmsSender",
    "SentSms",
    "SmsError",
    "SmsSender",
    "TEMPLATE_BY_PURPOSE",
    "THROTTLING_RETRY_S",
    "mainland_digits",
    "mask",
    "retry_after_for",
    "sms_sender_from_settings",
]
