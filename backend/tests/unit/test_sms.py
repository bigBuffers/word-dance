"""delivery/sms.py: the Aliyun SendSmsVerifyCode request shape, the SmsError mapping with retry hints, the recording double, the
factory, nothing but the masked number in logs."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

import fake_aliyun
from wd.delivery import aliyun, sms
from wd.interfaces import Mailer

NOW = datetime(2026, 10, 14, 0, 12, 30, tzinfo=timezone.utc)  # 08:12:30 in Asia/Shanghai (the test env's WD_TZ)
PHONE = "+8613800138000"
TO_NEXT_HOUR = 47 * 60 + 30
TO_NEXT_DAY = 15 * 3600 + 47 * 60 + 30  # the next Asia/Shanghai midnight, 2026-10-14T16:00:00Z


@pytest.fixture(autouse=True)
def _no_sockets_fixed_clock(monkeypatch):
    def refuse():
        pytest.fail("aliyun.CLIENT_FACTORY was not installed by the test")

    monkeypatch.setattr(aliyun, "CLIENT_FACTORY", refuse)
    monkeypatch.setattr(sms, "CLOCK", lambda: NOW)


@pytest.fixture
def cfg(settings, tmp_path):
    secret = tmp_path / "aliyun.secret"
    secret.write_text("testsecret\n", encoding="utf-8")
    secret.chmod(0o600)
    return replace(settings, sms_provider="aliyun_verify", aliyun_access_key_id="testid", aliyun_access_key_secret_file=str(secret), aliyun_sms_sign_name="速通互联验证码")


@pytest.fixture
def install(monkeypatch):
    def _install(mode: str = "ok", *, modes=None):
        calls: list[dict] = []
        transport = fake_aliyun.transport(mode, calls=calls, modes=modes, secret="testsecret")
        monkeypatch.setattr(aliyun, "CLIENT_FACTORY", lambda: httpx.Client(transport=transport))
        return calls, transport

    return _install


def test_factory_and_protocol(settings, cfg):
    assert sms.sms_sender_from_settings(settings) is None  # WD_SMS_PROVIDER=off in the test env
    sender = sms.sms_sender_from_settings(cfg)
    assert isinstance(sender, sms.AliyunVerifySender) and isinstance(sender, sms.SmsSender) and sender.configured
    assert not isinstance(sender, Mailer)
    assert sms.AliyunVerifySender.from_settings(replace(cfg, aliyun_sms_sign_name="")) is None  # a hand-built incomplete Settings → None like the mailer
    assert isinstance(sms.RecordingSmsSender(), sms.SmsSender)
    assert sms.TEMPLATE_BY_PURPOSE == {"login": "100001", "rebind_phone": "100002", "reset_password": "100003", "bind_phone": "100004", "reauth": "100005"}
    assert sms.mainland_digits(PHONE) == "13800138000" and sms.mainland_digits("13800138000") == "13800138000" and sms.mainland_digits("+15551234567") is None
    assert sms.mask(PHONE) == "138****8000"
    with pytest.raises(ValueError):
        sms.SmsError("weird", "x")


def test_send_code_request_shape(cfg, install, caplog):
    calls, _ = install("ok")
    sender = sms.AliyunVerifySender(cfg)
    with caplog.at_level(logging.INFO, logger="wd.delivery.sms"):
        sender.send_code(PHONE, "123456", "100001", minutes=10)
    assert len(calls) == 1
    p = calls[0]["params"]
    assert calls[0]["host"] == aliyun.SMS_HOST == "dypnsapi.aliyuncs.com" and calls[0]["query"] == ""
    assert p["Action"] == "SendSmsVerifyCode" and p["Version"] == "2017-05-25"
    assert p["PhoneNumber"] == "13800138000" and p["CountryCode"] == "86" and p["SignName"] == "速通互联验证码" and p["TemplateCode"] == "100001"
    assert json.loads(p["TemplateParam"]) == {"code": "123456", "min": "10"}
    assert (p["ValidTime"], p["Interval"], p["ReturnVerifyCode"]) == ("600", "60", "false") and len(p["OutId"]) == 16
    assert sender.last_result["Code"] == "OK" and sender.last_result["RequestId"].startswith("FAKE-") and sender.last_result["BizId"]
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "sms code sent" in joined and "13800138000" not in joined and "123456" not in joined
    assert any(getattr(r, "event", None) == "sms_sent" and getattr(r, "provider", None) == "aliyun_verify" for r in caplog.records)
    with pytest.raises(sms.SmsError) as e:
        sender.send_code("+15551234567", "123456", "100001", minutes=10)
    assert e.value.kind == "invalid_target" and len(calls) == 1  # refused before any request


@pytest.mark.parametrize(
    "mode,kind,retry",
    [
        ("FREQUENCY_FAIL", "rate_limited", 60),
        ("BUSINESS_LIMIT_CONTROL", "rate_limited", TO_NEXT_DAY),  # 触发号码天级流控: the number's quota for the WD_TZ day
        ("Throttling.User", "rate_limited", 5),  # the gateway's flow control clears within seconds
        ("ok_200_code", "rate_limited", 60),
        ("MOBILE_NUMBER_ILLEGAL", "invalid_target", None),
        ("SignatureDoesNotMatch", "config", None),
        ("InvalidAccessKeyId.NotFound", "config", None),
        ("http500", "temporary", None),
        ("http404_text", "temporary", None),
        ("network", "temporary", None),
        ("timeout", "temporary", None),
    ],
)
def test_send_code_maps_refusals_to_sms_errors(cfg, install, caplog, mode, kind, retry):
    install(mode)
    sender = sms.AliyunVerifySender(cfg)
    with caplog.at_level(logging.WARNING, logger="wd.delivery.sms"):
        with pytest.raises(sms.SmsError) as e:
            sender.send_code(PHONE, "123456", "100003", minutes=10)
    assert e.value.kind == kind and e.value.retry_after_s == retry
    text = str(e.value) + " ".join(r.getMessage() for r in caplog.records)
    assert "13800138000" not in text and "123456" not in text and "testsecret" not in text  # MOBILE_NUMBER_ILLEGAL echoes the number: masked
    if mode == "MOBILE_NUMBER_ILLEGAL":
        assert "138****8000" in str(e.value)
    assert any(getattr(r, "event", None) == "sms_send_failed" for r in caplog.records)
    if mode not in ("network", "timeout", "http500", "http404_text"):
        assert e.value.code and sender.last_result["Code"] == e.value.code


def test_retry_after_for():
    """The 429 hint by refusal class: frequency 60 s; the number's daily / monthly quota → the next WD_TZ day (an earlier retry would
    only spend our own caps); the gateway's QPS / flow control → seconds; any other limit → the next full hour."""
    assert sms.retry_after_for("FREQUENCY_FAIL", "rate_limited", NOW) == 60
    assert sms.retry_after_for("Interval.TooShort", "rate_limited", NOW) == 60
    assert sms.retry_after_for("isv.BUSINESS_LIMIT_CONTROL", "rate_limited", NOW) == TO_NEXT_DAY
    assert sms.retry_after_for("isv.DAY_LIMIT_CONTROL", "rate_limited", NOW) == sms.retry_after_for("isv.MONTH_LIMIT_CONTROL", "rate_limited", NOW) == TO_NEXT_DAY
    assert sms.retry_after_for("BUSINESS_LIMIT_CONTROL", "rate_limited", NOW, tz="UTC") == 86400 - 12 * 60 - 30  # the provider's day is WD_TZ's
    assert sms.retry_after_for("BUSINESS_LIMIT_CONTROL", "rate_limited", datetime(2026, 10, 14, 15, 59, 59, tzinfo=timezone.utc)) == 1  # 23:59:59 in Shanghai
    assert sms.retry_after_for("Throttling.User", "rate_limited", NOW) == sms.retry_after_for("isp.QPS_LIMIT", "rate_limited", NOW) == sms.THROTTLING_RETRY_S == 5
    assert sms.retry_after_for("InvalidQuota", "rate_limited", NOW) == TO_NEXT_HOUR  # another limit: the next full hour (our hourly window turns then too)
    assert sms.retry_after_for("LimitExceeded.SmsCode", "rate_limited", datetime(2026, 10, 14, 0, 59, 59, tzinfo=timezone.utc)) == 1
    assert sms.retry_after_for("MOBILE_NUMBER_ILLEGAL", "invalid_target", NOW) is None


def test_recording_sender():
    spy = sms.RecordingSmsSender()
    spy.send_code(PHONE, "654321", "100004", minutes=10)
    assert spy.sent == [sms.SentSms(to=PHONE, code="654321", template="100004", minutes=10)]
    assert spy.sent[0].code == "654321" and spy.sent[0].template == "100004"
    spy.fail_with = sms.SmsError("rate_limited", "FREQUENCY_FAIL: 频控校验未通过", retry_after_s=60, code="FREQUENCY_FAIL")
    with pytest.raises(sms.SmsError) as e:
        spy.send_code(PHONE, "1", "100001", minutes=10)
    assert e.value.kind == "rate_limited" and e.value.retry_after_s == 60 and len(spy.sent) == 1


def test_app_state_sms_is_none_in_the_test_env(app):
    assert app.state.sms is None and app.state.mailer is None


def test_under_the_smoke_mock_the_default_client_gets_a_404_text_and_the_send_is_temporary(cfg, mock_http, monkeypatch):
    """WD_SMOKE_MOCK_HTTP installs a MockTransport on every default httpx.Client: an unrouted host answers a plain-text 404, which the
    adapter must classify as `temporary` (503 sms_send_failed at the route) — never a crash, never a secret in the message."""
    monkeypatch.setattr(aliyun, "CLIENT_FACTORY", None)  # the real `_client()` path: trust_env=False, the process-wide mock transport
    sender = sms.AliyunVerifySender(cfg)
    with pytest.raises(sms.SmsError) as e:
        sender.send_code(PHONE, "123456", "100001", minutes=10)
    assert e.value.kind == "temporary" and e.value.retry_after_s is None and e.value.code == "HTTP_404"
    assert "mock_http: no route for dypnsapi.aliyuncs.com" in str(e.value) and "testsecret" not in str(e.value) and "13800138000" not in str(e.value)
    assert len(mock_http.calls_to("dypnsapi.aliyuncs.com")) == 1 and mock_http.calls[0].method == "POST" and not mock_http.calls[0].url.query
