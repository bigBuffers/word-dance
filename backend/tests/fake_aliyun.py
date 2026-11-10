"""Fake Aliyun POP gateway for the SMS / DirectMail adapter tests (``wd.delivery.aliyun`` / ``sms`` / ``mailer``).

``transport(mode, calls=[...], secret=None)`` returns an ``httpx.MockTransport`` whose handler records every request — ``host``,
``method``, ``path``, ``params`` (the form body with ``Signature`` and ``AccessKeyId`` REMOVED), ``access_key_sha256`` /
``signature_sha256`` (SHA-256 fingerprints, never the values), the headers — and answers the documented envelopes
(``Code`` / ``Message`` / ``RequestId`` for Dypnsapi, ``EnvId`` / ``RequestId`` for Dm). With ``secret`` the handler recomputes the
V1 signature over the received parameters and answers ``SignatureDoesNotMatch`` (HTTP 400, the real gateway's shape — its
``Message`` echoes the server's StringToSign) when the adapter signed differently, which pins the signing end to end.

Modes (``mode=`` default, ``modes=`` consumed one request at a time, ``set_mode(transport, mode)`` later): ``ok`` · ``FREQUENCY_FAIL``
(HTTP 400, 频控校验未通过) · ``BUSINESS_LIMIT_CONTROL`` (HTTP 400, 触发号码天级流控) · ``MOBILE_NUMBER_ILLEGAL`` · ``ok_200_code``
(HTTP 200 with ``Code: FREQUENCY_FAIL`` — the other way a business refusal may arrive) · ``SignatureDoesNotMatch`` ·
``InvalidAccessKeyId.NotFound`` (HTTP 404) · ``InvalidMailAddress.NotFound`` (HTTP 404, DirectMail) · ``InvalidToAddress`` ·
``Throttling.User`` (HTTP 429) · ``http500`` (an HTML 500 page) · ``http404_text`` (the smoke mock's plain-text 404) ·
``http302`` (a redirect with an empty body) · ``http200_html`` (a captive-portal style HTML page behind a 200) ·
``network`` (raises ``httpx.ConnectError``) · ``timeout`` (raises ``httpx.ReadTimeout``). Stdlib + httpx; no sockets.

The ``SignatureDoesNotMatch`` answer carries the real gateway's shape: its ``Message`` ends with ``server string to sign is:`` and
the StringToSign recomputed over the received parameters — PhoneNumber / TemplateParam (the code) / ToAddress / TextBody included
— which is exactly what the adapter must cut before anything is logged.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import deque
from typing import Any, Iterable
from urllib.parse import parse_qsl

import httpx

MODES: tuple[str, ...] = (
    "ok",
    "FREQUENCY_FAIL",
    "BUSINESS_LIMIT_CONTROL",
    "MOBILE_NUMBER_ILLEGAL",
    "ok_200_code",
    "SignatureDoesNotMatch",
    "InvalidAccessKeyId.NotFound",
    "InvalidMailAddress.NotFound",
    "InvalidToAddress",
    "Throttling.User",
    "http500",
    "http404_text",
    "http302",
    "http200_html",
    "network",
    "timeout",
)
_ids = itertools.count(1)


def _request_id() -> str:
    return f"FAKE-{next(_ids):08d}-REQUEST-ID"


class FakeState:
    def __init__(self, mode: str, calls: list[dict[str, Any]] | None, modes: Iterable[str] | None, secret: str | None):
        self.mode = mode
        self.calls = calls
        self.modes: deque[str] = deque(modes or ())
        self.secret = secret
        self.count = 0

    def next_mode(self) -> str:
        self.count += 1
        return self.modes.popleft() if self.modes else self.mode


def _json(status: int, payload: dict, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers={"Content-Type": "application/json;charset=utf-8", **(headers or {})}, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _error(status: int, code: str, message: str, host: str) -> httpx.Response:
    return _json(status, {"RequestId": _request_id(), "HostId": host, "Code": code, "Message": message, "Recommend": f"https://api.aliyun.com/troubleshoot?q={code}", "Success": False})


def expected_signature(params: dict[str, str], secret: str) -> str:
    """The V1 signature the gateway computes over the received parameters (an independent copy of the documented algorithm)."""
    from wd.delivery import aliyun  # the algorithm under test; the test module pins it against a hand-computed vector

    return aliyun.sign_rpc_v1("POST", {k: v for k, v in params.items() if k != "Signature"}, params.get("AccessKeyId", ""), secret, now=_timestamp(params), nonce=params.get("SignatureNonce", ""))["Signature"]


def server_string_to_sign(params: dict[str, str]) -> str:
    """What the real gateway echoes in a ``SignatureDoesNotMatch`` Message: the StringToSign over every received parameter but the
    Signature — the recipient, the number, the code and the body travel in it, percent-encoded twice."""
    from wd.delivery import aliyun

    return aliyun.string_to_sign("POST", {k: v for k, v in params.items() if k != "Signature"})


def _timestamp(params: dict[str, str]):
    from datetime import datetime, timezone

    return datetime.strptime(params.get("Timestamp", "1970-01-01T00:00:00Z"), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def respond(params: dict[str, str], mode: str, host: str) -> httpx.Response:
    """The gateway's answer for one request under ``mode`` (raises the transport exceptions of ``network`` / ``timeout``)."""
    if mode == "network":
        raise httpx.ConnectError("[Errno 61] Connection refused")
    if mode == "timeout":
        raise httpx.ReadTimeout("The read operation timed out")
    if mode == "http500":
        return httpx.Response(500, headers={"Content-Type": "text/html"}, text="<html><body>Internal Server Error</body></html>")
    if mode == "http404_text":
        return httpx.Response(404, text=f"mock_http: no route for {host}/")
    if mode == "http302":
        return httpx.Response(302, headers={"Location": f"https://{host}/login"})
    if mode == "http200_html":
        return httpx.Response(200, headers={"Content-Type": "text/html"}, text="<html><body><h1>Sign in to the network</h1></body></html>")
    if mode == "FREQUENCY_FAIL":
        return _error(400, "FREQUENCY_FAIL", "频控校验未通过", host)
    if mode == "BUSINESS_LIMIT_CONTROL":
        return _error(400, "BUSINESS_LIMIT_CONTROL", "触发号码天级流控", host)
    if mode == "MOBILE_NUMBER_ILLEGAL":
        return _error(400, "MOBILE_NUMBER_ILLEGAL", f"手机号码格式错误: {params.get('PhoneNumber', '')}", host)
    if mode == "ok_200_code":
        return _json(200, {"RequestId": _request_id(), "Code": "FREQUENCY_FAIL", "Message": "频控校验未通过", "Success": False})
    if mode == "SignatureDoesNotMatch":
        return _error(400, "SignatureDoesNotMatch", "Specified signature is not matched with our calculation. server string to sign is:" + server_string_to_sign(params), host)
    if mode == "InvalidAccessKeyId.NotFound":
        return _error(404, "InvalidAccessKeyId.NotFound", "Specified access key is not found.", host)
    if mode == "InvalidMailAddress.NotFound":
        return _error(404, "InvalidMailAddress.NotFound", "发信地址未找到", host)
    if mode == "InvalidToAddress":
        return _error(400, "InvalidToAddress", "收信地址格式错误", host)
    if mode == "Throttling.User":
        return _error(429, "Throttling.User", "Request was denied due to user flow control.", host)
    if mode != "ok":
        return _error(400, "InvalidFakeMode", f"unknown fake mode {mode!r}", host)
    action = params.get("Action", "")
    if action == "SendSmsVerifyCode":
        rid = _request_id()
        return _json(200, {"Code": "OK", "Message": "成功", "Success": True, "RequestId": rid, "Model": {"VerifyCode": None, "RequestId": rid, "BizId": f"{next(_ids)}^0", "OutId": params.get("OutId")}, "AccessDeniedDetail": "无"})
    if action == "SingleSendMail":
        return _json(200, {"EnvId": f"env-{next(_ids)}", "RequestId": _request_id()})
    return _error(400, "InvalidAction.NotFound", f"Specified api is not found: {action}", host)


def transport(mode: str = "ok", *, calls: list[dict[str, Any]] | None = None, modes: Iterable[str] | None = None, secret: str | None = None) -> httpx.MockTransport:
    """An ``httpx.MockTransport`` answering in ``mode`` (or the next of ``modes``); each request is appended to ``calls`` with the
    credentials reduced to fingerprints; with ``secret`` a wrongly signed request gets ``SignatureDoesNotMatch``."""
    state = FakeState(mode, calls, modes, secret)

    def handler(request: httpx.Request) -> httpx.Response:
        host = (request.headers.get("host") or request.url.host or "").split(":")[0].lower()
        body = request.content.decode("utf-8") if request.content else ""
        params = {k: v for k, v in parse_qsl(body, keep_blank_values=True)}
        if calls is not None:
            calls.append(
                {
                    "host": host,
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query, "ascii") if request.url.query else "",
                    "params": {k: v for k, v in params.items() if k not in ("Signature", "AccessKeyId")},
                    "access_key_sha256": hashlib.sha256(params["AccessKeyId"].encode("utf-8")).hexdigest() if params.get("AccessKeyId") else None,
                    "signature_sha256": hashlib.sha256(params["Signature"].encode("utf-8")).hexdigest() if params.get("Signature") else None,
                    "headers": {k.lower(): v for k, v in request.headers.items()},
                }
            )
        if request.method != "POST":
            return _error(405, "MethodNotAllowed", f"{request.method} is not allowed", host)
        if state.secret is not None and params.get("Signature") != expected_signature(params, state.secret):
            return respond(params, "SignatureDoesNotMatch", host)
        return respond(params, state.next_mode(), host)

    t = httpx.MockTransport(handler)
    t.fake = state  # type: ignore[attr-defined]
    return t


def set_mode(t: httpx.MockTransport, mode: str) -> None:
    state: FakeState = t.fake  # type: ignore[attr-defined]
    state.mode = mode
    state.modes.clear()


__all__ = ["MODES", "FakeState", "expected_signature", "respond", "server_string_to_sign", "set_mode", "transport"]
