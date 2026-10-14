"""smtplib implementation of :class:`wd.interfaces.Mailer` (Phase 0; DESIGN §6.5, DEPLOY §4 SMTP variables).

``SmtpMailer.from_settings(cfg)`` returns None while the channel is unconfigured (host + from-address
required); callers answer 409 ``smtp_unconfigured`` in that case. ``RecordingMailer`` is the spy used
by tests (WP4 delivery tests assert on ``.sent``).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from ..config import Settings
from ..interfaces import Mailer

log = logging.getLogger("wd.delivery.mailer")


class MailerError(RuntimeError):
    """Sending failed (connection, authentication, recipient refused …); the job layer retries."""


@dataclass
class SentMail:
    to: str
    subject: str
    text: str
    html: str | None = None


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
        if not cfg.email_configured:
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
            raise MailerError(f"SMTP send to {to} failed: {e}") from e
        log.info("e-mail sent", extra={"event": "email_sent"})


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
    """The production mailer, or None when SMTP is not configured."""
    return SmtpMailer.from_settings(cfg)


__all__ = ["Mailer", "MailerError", "SentMail", "SmtpMailer", "RecordingMailer", "mailer_from_settings"]
