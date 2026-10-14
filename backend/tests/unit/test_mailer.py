"""delivery/mailer.py: configuration gate, MIME construction, the recording test double, failure mapping."""

from __future__ import annotations

import smtplib
from dataclasses import replace

import pytest

from wd.delivery import mailer as m
from wd.interfaces import Mailer


def test_unconfigured_returns_none(settings):
    assert m.SmtpMailer.from_settings(settings) is None
    assert m.mailer_from_settings(settings) is None
    assert m.SmtpMailer.from_settings(replace(settings, smtp_host="smtp.example.com")) is None  # from address missing


def test_build_message_is_multipart_alternative(settings):
    cfg = replace(settings, smtp_host="smtp.example.com", smtp_from="word-Dance <wd@example.com>", smtp_port=465, smtp_tls="ssl")
    mailer = m.SmtpMailer.from_settings(cfg)
    assert mailer is not None and isinstance(mailer, Mailer)
    msg = mailer.build_message("bob@example.com", "【word-Dance】今日词汇 10月14日", "复习 12 · 新词 10", "<p>复习 12</p>")
    assert msg["To"] == "bob@example.com" and msg["Subject"] == "【word-Dance】今日词汇 10月14日"
    assert msg.get_content_type() == "multipart/alternative"
    parts = {p.get_content_type(): p.get_content() for p in msg.iter_parts()}
    assert parts["text/plain"].strip() == "复习 12 · 新词 10" and "<p>" in parts["text/html"]
    plain = mailer.build_message("bob@example.com", "s", "t")
    assert plain.get_content_type() == "text/plain"


def test_invalid_tls_mode_rejected():
    with pytest.raises(ValueError):
        m.SmtpMailer("h", from_addr="a@b", tls="maybe")
    with pytest.raises(ValueError):
        m.SmtpMailer("", from_addr="a@b")


def test_send_maps_smtp_errors(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise smtplib.SMTPConnectError(421, b"busy")

    monkeypatch.setattr(m.smtplib, "SMTP", Boom)
    mailer = m.SmtpMailer("smtp.example.com", from_addr="wd@example.com", tls="starttls")
    with pytest.raises(m.MailerError):
        mailer.send("bob@example.com", "s", "t")


def test_send_uses_starttls_login_and_send_message(monkeypatch):
    calls: list[str] = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(f"connect {host}:{port}")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            calls.append("quit")

        def ehlo(self):
            calls.append("ehlo")

        def starttls(self, context=None):
            calls.append("starttls")

        def login(self, user, password):
            calls.append(f"login {user}")

        def send_message(self, msg, from_addr, to_addrs):
            calls.append(f"send {from_addr}->{to_addrs}")

    monkeypatch.setattr(m.smtplib, "SMTP", FakeSMTP)
    m.SmtpMailer("smtp.example.com", 587, "u", "p", "wd@example.com").send("bob@example.com", "s", "t")
    assert calls == ["connect smtp.example.com:587", "ehlo", "starttls", "ehlo", "login u", "send wd@example.com->['bob@example.com']", "quit"]


def test_recording_mailer():
    spy = m.RecordingMailer()
    spy.send("a@b", "s", "t", "<b>t</b>")
    assert spy.sent == [m.SentMail(to="a@b", subject="s", text="t", html="<b>t</b>")]
    spy.fail_with = "down"
    with pytest.raises(m.MailerError):
        spy.send("a@b", "s", "t")
