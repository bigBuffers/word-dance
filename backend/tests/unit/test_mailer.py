"""delivery/mailer.py: configuration gate, MIME construction, the recording test double, failure mapping, the WD_MAIL_PROVIDER
dispatch and the Aliyun DirectMail mailer (SingleSendMail through tests/fake_aliyun.py)."""

from __future__ import annotations

import smtplib
from dataclasses import replace

import httpx
import pytest

import fake_aliyun
from wd.delivery import aliyun
from wd.delivery import mailer as m
from wd.interfaces import Mailer


def test_unconfigured_returns_none(settings):
    assert m.SmtpMailer.from_settings(settings) is None
    assert m.mailer_from_settings(settings) is None
    assert m.SmtpMailer.from_settings(replace(settings, smtp_host="smtp.example.com")) is None  # from address missing
    assert m.AliyunDirectMailer.from_settings(settings) is None  # provider smtp
    assert m.mailer_from_settings(replace(settings, mail_provider="aliyun_dm")) is None  # no key
    assert m.SmtpMailer.from_settings(replace(settings, mail_provider="aliyun_dm", smtp_host="smtp.example.com", smtp_from="wd@example.com")) is None  # the other provider is selected


@pytest.fixture
def dm_cfg(settings, tmp_path):
    secret = tmp_path / "aliyun.secret"
    secret.write_text("testsecret\n", encoding="utf-8")
    secret.chmod(0o600)
    return replace(settings, mail_provider="aliyun_dm", aliyun_access_key_id="testid", aliyun_access_key_secret_file=str(secret), smtp_from="word-Dance <noreply@mail.example.com>")


def test_directmail_dispatch_and_request_shape(dm_cfg, monkeypatch):
    assert dm_cfg.email_configured
    mailer = m.mailer_from_settings(dm_cfg)
    assert isinstance(mailer, m.AliyunDirectMailer) and isinstance(mailer, Mailer) and mailer.configured
    assert mailer.account_name == "noreply@mail.example.com" and mailer.from_alias == "word-Dance"
    # FromAlias: 「长度小于 15 个字符」 — a 15-character display name is cut to 14
    long_alias = m.AliyunDirectMailer(replace(dm_cfg, smtp_from="word-Dance 单词之舞 <noreply@mail.example.com>")).from_alias
    assert long_alias == "word-Dance 单词之" and len(long_alias) == m.DM_FROM_ALIAS_MAX == 14
    calls: list[dict] = []
    transport = fake_aliyun.transport("ok", calls=calls, secret="testsecret")
    monkeypatch.setattr(aliyun, "CLIENT_FACTORY", lambda: httpx.Client(transport=transport))
    mailer.send("bob@example.com", "【word-Dance】邮箱验证码" + "x" * 200, "你的验证码是 123456", "<p>123456</p>")
    assert len(calls) == 1 and calls[0]["host"] == "dm.aliyuncs.com" and calls[0]["query"] == ""
    p = calls[0]["params"]
    assert p["Action"] == "SingleSendMail" and p["Version"] == "2015-11-23"
    assert p["AccountName"] == "noreply@mail.example.com" and p["AddressType"] == "1" and p["ReplyToAddress"] == "false" and p["ToAddress"] == "bob@example.com"
    assert len(p["Subject"]) == 100 and p["TextBody"] == "你的验证码是 123456" and p["HtmlBody"] == "<p>123456</p>" and p["FromAlias"] == "word-Dance"
    plain = m.AliyunDirectMailer(replace(dm_cfg, smtp_from="noreply@mail.example.com")).params("a@b.c", "s", "t")
    assert "HtmlBody" not in plain and "FromAlias" not in plain
    with pytest.raises(ValueError):
        m.AliyunDirectMailer(replace(dm_cfg, smtp_from="not an address"))
    # every refusal is a MailerError without the recipient; the provider's code and kind are in the message for the log line
    fake_aliyun.set_mode(transport, "InvalidMailAddress.NotFound")
    with pytest.raises(m.MailerError) as e:
        mailer.send("bob@example.com", "s", "t")
    assert "InvalidMailAddress.NotFound" in str(e.value) and "config" in str(e.value) and "bob@example.com" not in str(e.value)
    assert (e.value.code, e.value.kind, e.value.failure_class) == ("InvalidMailAddress.NotFound", "config", "InvalidMailAddress.NotFound (config)")
    # SignatureDoesNotMatch: the gateway echoes the whole signed request (ToAddress, Subject, TextBody with the code) in its Message —
    # the MailerError carries the code, the kind and the request id only, never the recipient (plain or percent-encoded) or the code
    fake_aliyun.set_mode(transport, "SignatureDoesNotMatch")
    with pytest.raises(m.MailerError) as e:
        mailer.send("bob@example.com", "【word-Dance】邮箱验证码", "你的验证码是 123456", "<p>123456</p>")
    text = str(e.value)
    assert text.startswith("DirectMail send failed: SignatureDoesNotMatch (config), request FAKE-")
    assert "bob@example.com" not in text and "bob%40example.com" not in text and "bob%2540example.com" not in text and "123456" not in text and "server string to sign" not in text
    assert e.value.failure_class == "SignatureDoesNotMatch (config)"
    fake_aliyun.set_mode(transport, "network")
    with pytest.raises(m.MailerError) as e:
        mailer.send("bob@example.com", "s", "t")
    assert e.value.code == "Network.ConnectError" and e.value.kind == "temporary" and "bob@example.com" not in str(e.value)


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
    with pytest.raises(m.MailerError) as e:
        mailer.send("bob@example.com", "s", "t")
    assert (e.value.code, e.value.kind, e.value.failure_class) == ("SMTPConnectError", "smtp", "SMTPConnectError (smtp)")
    assert str(e.value).startswith("SMTP send failed: SMTPConnectError: ") and "bob@example.com" not in str(e.value)

    class Refused:
        def __init__(self, *a, **k):
            raise smtplib.SMTPRecipientsRefused({"bob@example.com": (550, b"no such user")})

    monkeypatch.setattr(m.smtplib, "SMTP", Refused)
    with pytest.raises(m.MailerError) as e:
        mailer.send("bob@example.com", "s", "t")
    assert "bob@example.com" not in str(e.value) and "b***@example.com" in str(e.value)  # the server's text named the recipient: masked


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
    with pytest.raises(m.MailerError) as e:
        spy.send("a@b", "s", "t")
    assert e.value.code is None and e.value.kind is None and e.value.failure_class == "MailerError"
