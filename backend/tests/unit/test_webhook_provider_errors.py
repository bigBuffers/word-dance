"""delivery/webhook.safe_post reads the provider's own error inside a 2xx (DESIGN §6.5, API.md 17): 企业微信 / 飞书 / Server酱 / Bark
answer 200 with an error body when the key is wrong, which used to count as a delivery (a false 「测试成功」 and a `sent` batch)."""

from __future__ import annotations

import json

import httpx
import pytest

from wd.delivery import webhook

PUBLIC_IP = "93.184.216.34"  # a public address: 203.0.113.0/24 (TEST-NET-3) is reserved and fails the SSRF guard


def _client(status: int, body, *, content_type: str = "application/json"):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return httpx.Response(status, content=payload if isinstance(payload, bytes) else payload.encode("utf-8"), headers={"content-type": content_type})

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


@pytest.fixture(autouse=True)
def pinned_dns(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhook, "resolve_host", lambda host: [PUBLIC_IP])


@pytest.mark.parametrize(
    "fmt, body, expected",
    [
        ("wecom", {"errcode": 93000, "errmsg": "invalid webhook url, hint: [1699999999]"}, "HTTP 200 but wecom errcode 93000: invalid webhook url, hint: [1699999999]"),
        ("feishu", {"code": 19001, "msg": "param invalid: incoming webhook access token invalid"}, "HTTP 200 but feishu code 19001: param invalid: incoming webhook access token invalid"),
        ("feishu", {"StatusCode": 19021, "StatusMessage": "Bot Not Enabled"}, "HTTP 200 but feishu StatusCode 19021: Bot Not Enabled"),
        ("serverchan", {"code": 40001, "message": "bad sendkey"}, "HTTP 200 but serverchan code 40001: bad sendkey"),
        ("bark", {"code": 400, "message": "device token is empty"}, "HTTP 200 but bark code 400: device token is empty"),
        ("bark", {"code": "400"}, "HTTP 200 but bark code 400"),
    ],
)
def test_provider_refusals_inside_a_200_are_errors(fmt, body, expected):
    status, error, reason = webhook.safe_post("https://hooks.example.com/x", {"a": 1}, client=_client(200, body), fmt=fmt)
    assert (status, error, reason) == (200, expected, "http_error")


@pytest.mark.parametrize(
    "fmt, body",
    [
        ("wecom", {"errcode": 0, "errmsg": "ok"}),
        ("feishu", {"code": 0, "msg": "success", "data": {}}),
        ("feishu", {"StatusCode": 0, "StatusMessage": "success"}),
        ("serverchan", {"code": 0, "message": "", "data": {"pushid": "1"}}),
        ("bark", {"code": 200, "message": "success", "timestamp": 1}),
        ("generic", {"errcode": 93000}),  # the operator's own endpoint owes nothing but a 2xx
        ("wecom", "ok"),  # a non-JSON 2xx passes
        ("bark", [1, 2]),  # an unexpected shape passes
        ("wecom", {"errcode": True}),  # booleans are not codes
    ],
)
def test_successes_and_unreadable_bodies_pass(fmt, body):
    content_type = "application/json" if not isinstance(body, str) else "text/plain"
    status, error, reason = webhook.safe_post("https://hooks.example.com/x", {"a": 1}, client=_client(200, body, content_type=content_type), fmt=fmt)
    assert (status, error, reason) == (200, None, None)


def test_messages_are_truncated_and_a_plain_http_error_is_unchanged():
    long = {"errcode": 1, "errmsg": "x" * 500}
    status, error, _ = webhook.safe_post("https://hooks.example.com/x", {}, client=_client(200, long), fmt="wecom")
    assert status == 200 and error == "HTTP 200 but wecom errcode 1: " + "x" * webhook.PROVIDER_MESSAGE_MAX
    status, error, reason = webhook.safe_post("https://hooks.example.com/x", {}, client=_client(500, {"errcode": 0}), fmt="wecom")
    assert (status, error, reason) == (500, "HTTP 500", "http_error")


def test_send_test_webhook_reports_the_provider_refusal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(webhook, "CLIENT_FACTORY", lambda: _client(200, {"errcode": 93000, "errmsg": "invalid webhook url"}))
    result = webhook.send_test_webhook({"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=bad", "webhook_format": "wecom"})
    assert result["ok"] is False and result["http_status"] == 200 and result["reason"] == "http_error" and result["error"].startswith("HTTP 200 but wecom errcode 93000")
