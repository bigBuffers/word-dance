"""The :class:`wd.interfaces.Mailer` implementations (Phase 0; DESIGN §6.5, DEPLOY §4 ``WD_MAIL_PROVIDER`` / SMTP / ``WD_ALIYUN_*``).

:func:`mailer_from_settings` is the single factory (``main.create_app`` → ``app.state.mailer``, ``delivery.email.get_mailer``):
``WD_MAIL_PROVIDER=smtp`` → :class:`SmtpMailer` (host + from-address required), ``aliyun_dm`` → :class:`AliyunDirectMailer`
(DirectMail ``SingleSendMail`` with the ``WD_ALIYUN_*`` key; ``WD_SMTP_FROM`` is the sender — docs/AUTH_SIGNUP_DESIGN.md §5.4),
None while ``cfg.email_configured`` is false; callers answer 409 ``smtp_unconfigured`` in that case. Every implementation raises
:class:`MailerError` — its ``code`` / ``kind`` / ``failure_class`` name the failure without the recipient or the body, which is all a
log line may carry — and logs nothing but ``email_sent``. ``RecordingMailer`` is the spy used by tests (``.sent``, ``.fail_with``).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from ..config import Settings
from ..interfaces import Mailer
from . import aliyun

DM_SUBJECT_MAX = 100  # the classic SingleSendMail limit (the newer page says 256; stay under both)
DM_FROM_ALIAS_MAX = 14  # SingleSendMail: FromAlias 「长度小于 15 个字符」 — strictly fewer than 15

log = logging.getLogger("wd.delivery.mailer")


class MailerError(RuntimeError):
    """Sending failed (connection, authentication, recipient refused …); the job layer retries.

    ``code`` / ``kind`` name the failure class without the recipient, the subject or the body — DirectMail: the provider's ``Code``
    and its ``aliyun.classify`` kind; SMTP: the ``smtplib`` exception class — and :attr:`failure_class` renders them for a log line.
    """

    def __init__(self, message: str, *, code: str | None = None, kind: str | None = None):
        super().__init__(message)
        self.code = code
        self.kind = kind

    @property
    def failure_class(self) -> str:
        """``<code> (<kind>)``, the one of them that is known, else the exception class — never a recipient, a code or a body."""
        if self.code and self.kind:
            return f"{self.code} ({self.kind})"
        return self.code or self.kind or self.__class__.__name__


@dataclass
class SentMail:
    to: str
    subject: str
    text: str
    html: str | None = None


def _mask_email(email: str) -> str:
    """``alice@qq.com`` → ``a***@qq.com`` (the ``security.mask_email`` shape; local so this module stays free of the account layer)."""
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else f"{local[:1]}***"


class SmtpMailer:
    """Sends ``multipart/alternative`` (text + optional HTML) through SMTP with STARTTLS / implicit TLS / plain."""

    def __init__(
        self,
        host: str,
        port: int = 587,
        user: str = "",
        password: str = "",
        from_addr: str = "",
        tls: str = "starttls",
        timeout: float = 20.0,
    ):
        if tls not in ("starttls", "ssl", "none"):
            raise ValueError(f"tls must be starttls, ssl or none, got {tls!r}")
        if not host or not from_addr:
            raise ValueError("SmtpMailer needs a host and a from address")
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.tls = tls
        self.timeout = timeout

    @classmethod
    def from_settings(cls, cfg: Settings) -> "SmtpMailer | None":
        if cfg.mail_provider != "smtp" or not cfg.email_configured:
            return None
        return cls(cfg.smtp_host, cfg.smtp_port, cfg.smtp_user, cfg.smtp_password, cfg.smtp_from, cfg.smtp_tls)

    @property
    def configured(self) -> bool:
        return True

    def build_message(self, to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=self.from_addr.rsplit("@", 1)[-1] if "@" in self.from_addr else None)
        msg.set_content(text, charset="utf-8")
        if html:
            msg.add_alternative(html, subtype="html", charset="utf-8")
        return msg

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        msg = self.build_message(to, subject, text, html)
        context = ssl.create_default_context()
        try:
            if self.tls == "ssl":
                client: smtplib.SMTP = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout, context=context)
            else:
                client = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
            with client:
                client.ehlo()
                if self.tls == "starttls":
                    client.starttls(context=context)
                    client.ehlo()
                if self.user:
                    client.login(self.user, self.password)
                client.send_message(msg, from_addr=self.from_addr, to_addrs=[to])
        except (smtplib.SMTPException, OSError) as e:
            # the server's text may name the recipient (SMTPRecipientsRefused lists the addresses): masked, and cut short
            text = str(e).replace(to, _mask_email(to))[:200]
            raise MailerError(f"SMTP send failed: {e.__class__.__name__}: {text}", code=e.__class__.__name__, kind="smtp") from e
        log.info("e-mail sent", extra={"event": "email_sent"})


class AliyunDirectMailer:
    """Aliyun DirectMail ``SingleSendMail`` (Dm 2015-11-23, ``dm.aliyuncs.com``): ``AccountName`` = the address part of
    ``WD_SMTP_FROM`` (the 发信地址 configured in the console), ``FromAlias`` = its display-name part when given, ``AddressType=1``,
    ``ReplyToAddress=false``, ``Subject`` ≤ 100 characters, ``TextBody`` + ``HtmlBody`` when given. Every failure is a
    :class:`MailerError` built from the provider's ``Code``, its kind and the ``RequestId`` only — never the gateway's ``Message``,
    which on ``SignatureDoesNotMatch`` echoes the whole signed request (recipient, subject and body included); the key is read from
    the 0600 file at call time. ``FromAlias`` is cut to :data:`DM_FROM_ALIAS_MAX` (the console refuses 15 and more)."""

    def __init__(self, cfg: Settings):
        self.cfg = cfg
        alias, address = parseaddr(cfg.smtp_from or "")
        if not address or "@" not in address:
            raise ValueError("AliyunDirectMailer needs WD_SMTP_FROM with an address")
        self.account_name = address
        self.from_alias = alias.strip()[:DM_FROM_ALIAS_MAX]

    @classmethod
    def from_settings(cls, cfg: Settings) -> "AliyunDirectMailer | None":
        if cfg.mail_provider != "aliyun_dm" or not cfg.email_configured:
            return None
        return cls(cfg)

    @property
    def configured(self) -> bool:
        return True

    def params(self, to: str, subject: str, text: str, html: str | None = None) -> dict[str, str]:
        p = {
            "Action": "SingleSendMail",
            "Version": "2015-11-23",
            "AccountName": self.account_name,
            "AddressType": "1",
            "ReplyToAddress": "false",
            "ToAddress": to,
            "Subject": subject[:DM_SUBJECT_MAX],
            "TextBody": text,
        }
        if html:
            p["HtmlBody"] = html
        if self.from_alias:
            p["FromAlias"] = self.from_alias
        return p

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        try:
            aliyun.post(aliyun.DM_HOST, self.params(to, subject, text, html), self.cfg)
        except aliyun.AliyunError as e:
            raise MailerError(f"DirectMail send failed: {e.code} ({e.kind}), request {e.request_id or '-'}", code=e.code, kind=e.kind) from e
        log.info("e-mail sent", extra={"event": "email_sent", "provider": "aliyun_dm"})


class RecordingMailer:
    """Test double: records every message; ``fail_with`` makes ``send`` raise :class:`MailerError`."""

    def __init__(self) -> None:
        self.sent: list[SentMail] = []
        self.fail_with: str | None = None

    @property
    def configured(self) -> bool:
        return True

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> None:
        if self.fail_with:
            raise MailerError(self.fail_with)
        self.sent.append(SentMail(to=to, subject=subject, text=text, html=html))


def mailer_from_settings(cfg: Settings) -> Mailer | None:
    """The production mailer for ``WD_MAIL_PROVIDER``, or None when that provider is not configured (``cfg.email_configured``)."""
    if cfg.mail_provider == "aliyun_dm":
        return AliyunDirectMailer.from_settings(cfg)
    return SmtpMailer.from_settings(cfg)


__all__ = ["Mailer", "MailerError", "SentMail", "SmtpMailer", "AliyunDirectMailer", "RecordingMailer", "mailer_from_settings"]
