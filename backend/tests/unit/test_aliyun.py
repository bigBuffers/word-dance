"""delivery/aliyun.py: the V1 signature against a hand-computed vector, the form-body POST, JSON on every status, the Code
classification, secret scrubbing, the smoke mock's 404 text, no sockets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
import pytest

import fake_aliyun
from wd.delivery import aliyun

NOW = datetime(2026, 10, 14, 0, 0, 0, tzinfo=timezone.utc)
PARAMS = {"Action": "SendSmsVerifyCode", "Version": "2017-05-25", "PhoneNumber": "13800138000", "TemplateParam": '{"code":"123456","min":"10"}', "SignName": "速通互联验证码"}
# computed once by hand from the documented algorithm (help.aliyun.com RPC signature V1) for PARAMS, key id `testid`, secret
# `testsecret`, nonce `nonce-1`, timestamp 2026-10-14T00:00:00Z — the canonical string and the Base64 HMAC-SHA1 over it
KNOWN_STRING_TO_SIGN = (
    "POST&%2F&AccessKeyId%3Dtestid%26Action%3DSendSmsVerifyCode%26Format%3DJSON%26PhoneNumber%3D13800138000"
    "%26SignName%3D%25E9%2580%259F%25E9%2580%259A%25E4%25BA%2592%25E8%2581%2594%25E9%25AA%258C%25E8%25AF%2581%25E7%25A0%2581"
    "%26SignatureMethod%3DHMAC-SHA1%26SignatureNonce%3Dnonce-1%26SignatureVersion%3D1.0"
    "%26TemplateParam%3D%257B%2522code%2522%253A%2522123456%2522%252C%2522min%2522%253A%252210%2522%257D"
    "%26Timestamp%3D2026-10-14T00%253A00%253A00Z%26Version%3D2017-05-25"
)
KNOWN_SIGNATURE = "+hiTLAS9ZyNVKab7jBStEEPu3mg="


@pytest.fixture(autouse=True)
def _no_sockets(monkeypatch):
    def refuse():
        pytest.fail("aliyun.CLIENT_FACTORY was not installed by the test")

    monkeypatch.setattr(aliyun, "CLIENT_FACTORY", refuse)


@pytest.fixture
def cfg(settings, tmp_path):
    secret = tmp_path / "aliyun.secret"
    secret.write_text("testsecret\n", encoding="utf-8")
    secret.chmod(0o600)
    return replace(settings, sms_provider="aliyun_verify", aliyun_access_key_id="testid", aliyun_access_key_secret_file=str(secret), aliyun_sms_sign_name="速通互联验证码")


@pytest.fixture
def install(monkeypatch):
    def _install(mode: str = "ok", *, modes=None, secret: str | None = "testsecret"):
        calls: list[dict] = []
        transport = fake_aliyun.transport(mode, calls=calls, modes=modes, secret=secret)
        monkeypatch.setattr(aliyun, "CLIENT_FACTORY", lambda: httpx.Client(transport=transport))
        return calls, transport

    return _install


# ------------------------------------------------------------------------------------------ signing
def test_percent_encoding_is_rfc3986_with_the_aliyun_twists():
    assert aliyun.percent_encode("a b*c~d/e+f=g&h") == "a%20b%2Ac~d%2Fe%2Bf%3Dg%26h"
    assert aliyun.percent_encode("A-Z_0.9") == "A-Z_0.9" and aliyun.percent_encode(True) == "true" and aliyun.percent_encode(600) == "600"
    assert aliyun.percent_encode("验证码") == "%E9%AA%8C%E8%AF%81%E7%A0%81"


def test_sign_rpc_v1_matches_the_hand_computed_vector():
    signed = aliyun.sign_rpc_v1("POST", PARAMS, "testid", "testsecret", now=NOW, nonce="nonce-1")
    assert aliyun.string_to_sign("POST", signed) == KNOWN_STRING_TO_SIGN
    assert signed["Signature"] == KNOWN_SIGNATURE
    # the documented recipe, spelled out independently: sorted RFC-3986 pairs → METHOD&%2F&encode(canonical) → Base64(HMAC-SHA1(secret + "&"))
    pairs = sorted((k, v) for k, v in signed.items() if k != "Signature")
    canonical = "&".join(f"{quote(k, safe='~')}={quote(v, safe='~').replace('*', '%2A')}" for k, v in pairs)
    sts = "POST&" + quote("/", safe="~") + "&" + quote(canonical, safe="~")
    assert sts == KNOWN_STRING_TO_SIGN
    assert base64.b64encode(hmac.new(b"testsecret&", sts.encode("utf-8"), hashlib.sha1).digest()).decode() == KNOWN_SIGNATURE
    assert {signed["Format"], signed["SignatureMethod"], signed["SignatureVersion"], signed["SignatureNonce"], signed["Timestamp"], signed["AccessKeyId"]} == {"JSON", "HMAC-SHA1", "1.0", "nonce-1", "2026-10-14T00:00:00Z", "testid"}
    assert aliyun.sign_rpc_v1("POST", PARAMS, "testid", "other", now=NOW, nonce="nonce-1")["Signature"] != KNOWN_SIGNATURE
    assert aliyun.sign_rpc_v1("GET", PARAMS, "testid", "testsecret", now=NOW, nonce="nonce-1")["Signature"] != KNOWN_SIGNATURE
    assert aliyun.sign_rpc_v1("POST", {**PARAMS, "Signature": "stale"}, "testid", "testsecret", now=NOW, nonce="nonce-1")["Signature"] == KNOWN_SIGNATURE  # a stale Signature input is ignored


# -------------------------------------------------------------------------------------------- post
def test_post_sends_everything_in_the_form_body_and_returns_the_json(cfg, install):
    calls, _ = install("ok")
    data = aliyun.post(aliyun.SMS_HOST, PARAMS, cfg, now=NOW)
    assert data["Code"] == "OK" and data["Model"]["BizId"] and data["RequestId"].startswith("FAKE-")
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "POST" and call["host"] == "dypnsapi.aliyuncs.com" and call["path"] == "/" and call["query"] == ""  # nothing in the URL
    assert call["params"]["PhoneNumber"] == "13800138000" and call["params"]["SignName"] == "速通互联验证码" and call["params"]["Format"] == "JSON"
    assert call["params"]["Timestamp"] == "2026-10-14T00:00:00Z" and len(call["params"]["SignatureNonce"]) == 32
    assert call["access_key_sha256"] == hashlib.sha256(b"testid").hexdigest() and call["signature_sha256"]
    assert call["headers"]["content-type"] == "application/x-www-form-urlencoded" and call["headers"]["user-agent"].startswith("word-Dance/")
    # the fake verified the signature with the shared secret: a wrong secret file is refused as SignatureDoesNotMatch (config)
    bad = replace(cfg, aliyun_access_key_secret_file=str(__import__("pathlib").Path(cfg.aliyun_access_key_secret_file).with_name("other")))
    __import__("pathlib").Path(bad.aliyun_access_key_secret_file).write_text("wrong\n", encoding="utf-8")
    with pytest.raises(aliyun.AliyunError) as e:
        aliyun.post(aliyun.SMS_HOST, PARAMS, bad, now=NOW)
    assert e.value.code == "SignatureDoesNotMatch" and e.value.kind == "config" and e.value.http_status == 400 and e.value.request_id.startswith("FAKE-")
    # the gateway's Message echoes the whole signed request after `server string to sign is:` — cut before anything is logged
    assert e.value.message == "Specified signature is not matched with our calculation" and len(e.value.message) <= aliyun.MESSAGE_MAX
    assert "server string to sign" not in str(e.value) and "13800138000" not in str(e.value) and "123456" not in str(e.value) and "%2522" not in str(e.value)


def test_gateway_message_cuts_the_string_to_sign_echo_and_caps_the_length():
    echo = "Specified signature is not matched with our calculation. server string to sign is:POST&%2F&AccessKeyId%3Dtestid%26PhoneNumber%3D13800138000"
    assert aliyun.gateway_message(echo, "SignatureDoesNotMatch") == "Specified signature is not matched with our calculation"
    assert aliyun.gateway_message("server string to sign is:POST&%2F&…", "SignatureDoesNotMatch") == "SignatureDoesNotMatch"  # nothing readable left: the code
    assert aliyun.gateway_message("", "FREQUENCY_FAIL") == "FREQUENCY_FAIL"
    assert aliyun.gateway_message("x" * 500, "C") == "x" * aliyun.MESSAGE_MAX and aliyun.MESSAGE_MAX == 200
    assert aliyun.gateway_message("频控校验未通过", "FREQUENCY_FAIL") == "频控校验未通过"
    assert aliyun.scrub("key testid secret testsecret", "testsecret", "testid", None, "") == "key *** secret ***"


def test_post_directmail_success_has_no_code_field(cfg, install):
    install("ok")
    data = aliyun.post(aliyun.DM_HOST, {"Action": "SingleSendMail", "Version": "2015-11-23", "AccountName": "wd@example.com", "ToAddress": "a@b.c", "Subject": "s", "TextBody": "t"}, cfg)
    assert data["EnvId"].startswith("env-") and "Code" not in data


@pytest.mark.parametrize(
    "mode,code,kind,status",
    [
        ("FREQUENCY_FAIL", "FREQUENCY_FAIL", "rate_limited", 400),
        ("BUSINESS_LIMIT_CONTROL", "BUSINESS_LIMIT_CONTROL", "rate_limited", 400),
        ("MOBILE_NUMBER_ILLEGAL", "MOBILE_NUMBER_ILLEGAL", "invalid_target", 400),
        ("ok_200_code", "FREQUENCY_FAIL", "rate_limited", 200),  # a business refusal behind HTTP 200: the Code decides
        ("InvalidAccessKeyId.NotFound", "InvalidAccessKeyId.NotFound", "config", 404),
        ("InvalidMailAddress.NotFound", "InvalidMailAddress.NotFound", "config", 404),
        ("InvalidToAddress", "InvalidToAddress", "invalid_target", 400),
        ("Throttling.User", "Throttling.User", "rate_limited", 429),
        ("http500", "HTTP_500", "temporary", 500),
        ("http404_text", "HTTP_404", "temporary", 404),  # the smoke mock's answer for an unrouted host
        ("http302", "HTTP_302", "temporary", 302),  # a redirect is not a success: nothing was sent
        ("http200_html", "HTTP_200", "temporary", 200),  # a captive portal / middlebox page behind a 200: not a JSON object, not a success
    ],
)
def test_post_raises_a_classified_error_on_every_refusal_shape(cfg, install, mode, code, kind, status):
    install(mode, secret=None)
    with pytest.raises(aliyun.AliyunError) as e:
        aliyun.post(aliyun.SMS_HOST, PARAMS, cfg)
    assert (e.value.code, e.value.kind, e.value.http_status) == (code, kind, status)
    assert "testsecret" not in str(e.value) and "testid" not in str(e.value)
    if mode == "http404_text":
        assert "mock_http: no route" in e.value.message
    if mode in ("http302", "http200_html"):
        assert e.value.message.startswith(f"HTTP {status} without a JSON object body")
    if mode == "http200_html":
        assert "Sign in to the network" in e.value.message


@pytest.mark.parametrize("mode,exc", [("network", "ConnectError"), ("timeout", "ReadTimeout")])
def test_post_maps_transport_failures_to_temporary(cfg, install, mode, exc):
    install(mode, secret=None)
    with pytest.raises(aliyun.AliyunError) as e:
        aliyun.post(aliyun.SMS_HOST, PARAMS, cfg)
    assert e.value.code == f"Network.{exc}" and e.value.kind == "temporary" and e.value.http_status is None


def test_post_without_credentials_is_a_config_error_before_any_request(settings, install):
    calls, _ = install("ok")
    with pytest.raises(aliyun.AliyunError) as e:
        aliyun.post(aliyun.SMS_HOST, PARAMS, settings)
    assert e.value.code == "MissingCredentials" and e.value.kind == "config" and calls == []


def test_read_secret_first_line_warns_on_loose_mode_and_refuses_garbage(cfg, tmp_path, caplog):
    assert aliyun.read_secret(cfg) == "testsecret"
    loose = tmp_path / "loose"
    loose.write_text("﻿secret-with-bom\nsecond line\n", encoding="utf-8")
    loose.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="wd.delivery.aliyun"):
        assert aliyun.read_secret(replace(cfg, aliyun_access_key_secret_file=str(loose))) == "secret-with-bom"
    assert any("chmod 600" in r.getMessage() for r in caplog.records) and not any("secret-with-bom" in r.getMessage() for r in caplog.records)
    assert aliyun.read_secret(replace(cfg, aliyun_access_key_secret_file=str(tmp_path / "missing"))) is None
    blank = tmp_path / "blank"
    blank.write_text("\n", encoding="utf-8")
    assert aliyun.read_secret(replace(cfg, aliyun_access_key_secret_file=str(blank))) is None
    assert aliyun.read_secret(replace(cfg, aliyun_access_key_secret_file="")) is None


@pytest.mark.parametrize(
    "code,kind",
    [
        ("FREQUENCY_FAIL", "rate_limited"),
        ("biz.FREQUENCY", "rate_limited"),
        ("isv.BUSINESS_LIMIT_CONTROL", "rate_limited"),
        ("Interval.TooShort", "rate_limited"),
        ("Throttling.User", "rate_limited"),
        ("isp.QPS_LIMIT", "rate_limited"),
        ("LimitExceeded.SmsCode", "rate_limited"),
        ("InvalidQuota", "rate_limited"),
        ("InvalidSendSms", "rate_limited"),
        ("MOBILE_NUMBER_ILLEGAL", "invalid_target"),
        ("isv.MOBILE_NUMBER_ILLEGAL", "invalid_target"),
        ("InvalidToAddress.Spam", "invalid_target"),
        ("InvalidReceiverName", "invalid_target"),
        ("INVALID_PARAMETERS", "config"),  # a request parameter (SignName / TemplateCode / TemplateParam), never the number → 503, not 400 invalid_phone
        ("isv.INVALID_PARAMETERS", "config"),
        ("isv.INVALID_JSON_PARAM", "config"),
        ("isv.SMS_SIGNATURE_ILLEGAL", "config"),  # the day-0 misconfiguration: WD_ALIYUN_SMS_SIGN_NAME is not this account's signature
        ("isv.SMS_TEMPLATE_ILLEGAL", "config"),
        ("isv.TEMPLATE_PARAMS_ILLEGAL", "config"),
        ("isv.TEMPLATE_MISSING_PARAMETERS", "config"),
        ("isp.RAM_PERMISSION_DENY", "config"),
        ("isv.ACCOUNT_NOT_EXISTS", "config"),
        ("isv.ACCOUNT_ABNORMAL", "config"),
        ("isv.SECURITY_FROZEN_ACCOUNT", "config"),
        ("isv.PRODUCT_UN_SUBSCRIPT", "config"),
        ("isv.DENY_IP_RANGE", "config"),
        ("isv.SMS_TEST_NUMBER_LIMIT", "config"),
        ("isv.BLACK_KEY_CONTROL_LIMIT", "temporary"),  # the blacklist codes stay `temporary`: 503, a later retry costs nothing
        ("isv.MOBILE_IN_BLACK", "temporary"),
        ("FUNCTION_NOT_OPENED", "config"),
        ("isv.PRODUCT_UNSUBSCRIBE", "config"),
        ("isv.OUT_OF_SERVICE", "config"),
        ("isv.AMOUNT_NOT_ENOUGH", "config"),
        ("InvalidAccessKeyId.NotFound", "config"),
        ("SignatureDoesNotMatch", "config"),
        ("InvalidTimeStamp.Expired", "config"),
        ("Forbidden.RAM", "config"),
        ("InvalidMailAddress.NotFound", "config"),
        ("InvalidMailAddressStatus.Malformed", "config"),
        ("MissingParameter", "config"),
        ("InvalidParameter", "config"),
        ("MissingCredentials", "config"),
        ("isp.SYSTEM_ERROR", "temporary"),
        ("ServiceUnavailable", "temporary"),
        ("SignatureNonceUsed", "temporary"),
        ("HTTP_502", "temporary"),
        ("Network.ConnectError", "temporary"),
        ("", "temporary"),
    ],
)
def test_classify_table(code, kind):
    assert aliyun.classify(code) == kind and kind in aliyun.KINDS
