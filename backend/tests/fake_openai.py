"""Fake OpenAI-format ``chat/completions`` endpoint for the fallback adapter's tests (CLAUDE_INTEGRATION §8 / §10).

``transport(mode, calls=[...])`` returns an ``httpx.MockTransport`` whose handler records every request (``url``,
``headers`` without ``Authorization``, the JSON body, ``auth_scheme``, ``auth_sha256`` — the SHA-256 hex digest of the bearer
token, a non-secret fingerprint that pins which credential was sent while the token itself never lands in the record — and
``timeout``, the per-request timeout the client asked for as ``httpx.Timeout.as_dict()``) and answers real chat-completions envelopes
(``choices[0].message.content``, ``finish_reason``, ``usage`` with ``prompt_tokens`` ≈ bytes/3 and ``completion_tokens``
≈ bytes/2.6, ``model`` echoed). The items are built from the prompt's ``<items>`` block by the item builders of
``fake_claude.py`` (same directory), so a fake Claude answer and a fake fallback answer are the same objects for the same
prompt; the kind comes from the schema embedded in the system prompt (``json_object`` mode) or from
``response_format.json_schema.schema``.

Modes (``mode=`` default, ``modes=`` a sequence consumed one request at a time, ``set_mode(transport, mode)`` later):
``ok`` · ``fenced_json`` · ``invalid_json`` · ``schema_mismatch`` (one required key dropped from every item, also on the
repair round) · ``repairable`` (the first answer drops a key, the repair answer is valid) · ``partial`` · ``truncated``
(``finish_reason: length``) · ``empty_content`` · ``sensitive`` (Zhipu ``finish_reason: sensitive`` — blocked by the safety
filter, empty content) · ``network_error`` (Zhipu ``finish_reason: network_error`` — 模型推理异常 behind an HTTP 200) · ``401`` ·
``zh_401`` (Zhipu ``令牌已过期或验证不正确``) · ``402`` · ``403`` ·
``404`` · ``404_model`` (HTTP 400, Zhipu 1211) · ``429`` (``Retry-After: 2``, Zhipu 1302) · ``429_long`` (``Retry-After: 120``)
· ``1308`` (429 with code 1308, ``next_flush_time`` and a ``Retry-After: 1`` the adapter must ignore) · ``503`` ·
``content_filter`` (400 ``data_inspection_failed``) ·
``network`` (raises ``httpx.ConnectError``) · ``timeout`` (raises ``httpx.ReadTimeout``). Stdlib + httpx; no sockets.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any, Iterable

import httpx

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fake_claude as fc  # noqa: E402  (backend/tests/fake_claude.py — stdlib only)

MODES: tuple[str, ...] = (
    "ok",
    "fenced_json",
    "invalid_json",
    "schema_mismatch",
    "repairable",
    "partial",
    "truncated",
    "empty_content",
    "sensitive",
    "network_error",
    "401",
    "zh_401",
    "402",
    "403",
    "404",
    "404_model",
    "429",
    "429_long",
    "1308",
    "503",
    "content_filter",
    "network",
    "timeout",
)
PROMPT_BYTES_PER_TOKEN = 3.0
OUTPUT_BYTES_PER_TOKEN = 2.6
SCHEMA_MARKER = "conforms exactly to this JSON Schema:\n"
REPAIR_MARKER = "Your JSON failed validation"
NEXT_FLUSH_LOCAL = "2026-10-14 10:00:00"  # Beijing time in the Zhipu 1308 wording (= 2026-10-14T02:00:00Z)
DEFAULT_MODEL = "fake-flash"
_ids = itertools.count(1)


class FakeState:
    """Per-transport mode state: a default ``mode`` and an optional queue of per-request ``modes``."""

    def __init__(self, mode: str, calls: list[dict[str, Any]] | None, modes: Iterable[str] | None):
        self.mode = mode
        self.calls = calls
        self.modes: deque[str] = deque(modes or ())
        self.count = 0

    def next_mode(self) -> str:
        self.count += 1
        return self.modes.popleft() if self.modes else self.mode


def transport(mode: str = "ok", *, calls: list[dict[str, Any]] | None = None, modes: Iterable[str] | None = None) -> httpx.MockTransport:
    """An ``httpx.MockTransport`` answering in ``mode`` (or the next of ``modes``); each request is appended to ``calls``."""
    state = FakeState(mode, calls, modes)

    def handler(request: httpx.Request) -> httpx.Response:
        raw = request.content or b"{}"
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {}
        if calls is not None:
            auth = request.headers.get("authorization") or ""
            scheme, _, token = auth.partition(" ")
            calls.append(
                {
                    "url": str(request.url),
                    "headers": {k.lower(): v for k, v in request.headers.items() if k.lower() != "authorization"},
                    "json": body,
                    "auth_scheme": scheme or None,
                    "auth_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest() if token else None,  # never the token itself
                    "timeout": request.extensions.get("timeout"),
                }
            )
        if request.method != "POST" or not request.url.path.endswith("/chat/completions"):
            return _json(404, {"error": {"message": f"no route for {request.method} {request.url.path}", "type": "not_found"}})
        return respond(body, state.next_mode())

    t = httpx.MockTransport(handler)
    t.fake = state  # type: ignore[attr-defined]
    return t


def set_mode(t: httpx.MockTransport, mode: str) -> None:
    """Switch a transport's default mode (and drop any queued ``modes``)."""
    state: FakeState = t.fake  # type: ignore[attr-defined]
    state.mode = mode
    state.modes.clear()


# ------------------------------------------------------------------------------------- request parsing
def text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p["text"] if isinstance(p, dict) and isinstance(p.get("text"), str) else (p if isinstance(p, str) else "") for p in content)
    return ""


def prompts_of(body: dict) -> tuple[str, str]:
    """``(system text, user text)`` — several messages of a role are joined (the repair round adds a second user message)."""
    systems, users = [], []
    for m in body.get("messages", []) if isinstance(body.get("messages"), list) else []:
        if not isinstance(m, dict):
            continue
        if m.get("role") in ("system", "developer"):
            systems.append(text_of(m.get("content")))
        elif m.get("role") == "user":
            users.append(text_of(m.get("content")))
    return "\n".join(systems), "\n".join(users)


def schema_of(body: dict, system: str) -> dict | None:
    """The schema the client sent: ``response_format.json_schema.schema`` or the compact JSON after the system-prompt marker."""
    rf = body.get("response_format")
    if isinstance(rf, dict) and rf.get("type") == "json_schema":
        js = rf.get("json_schema")
        if isinstance(js, dict) and isinstance(js.get("schema"), dict):
            return js["schema"]
    if SCHEMA_MARKER in system:
        try:
            data = json.loads(system.split(SCHEMA_MARKER, 1)[1].strip())
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    m = re.search(r"\{.*\}", system, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except ValueError:
            pass
    return None


def infer_kind(body: dict, system: str, user: str) -> str:
    schema = schema_of(body, system)
    if schema is not None:
        return fc.infer_kind(schema)
    if "Look up these strings" in user:
        return "lookup"
    if "Examine this learner's word bank" in user:
        return "consolidate"
    if "Draw an illustration for the word" in user:
        return "svg"
    if "echo set to the exact text word-dance" in user:
        return "probe"
    return "content"


def is_repair(body: dict) -> bool:
    return any(isinstance(m, dict) and m.get("role") == "user" and REPAIR_MARKER in text_of(m.get("content")) for m in body.get("messages", []) or [])


# ------------------------------------------------------------------------------------- responses
def _json(status: int, payload: dict, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, headers={"Content-Type": "application/json", **(headers or {})}, content=json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def error_response(mode: str) -> httpx.Response | None:
    """Real-world shaped error bodies per mode; None when ``mode`` is a success mode."""
    if mode == "401":
        return _json(401, {"error": {"message": "Incorrect API key provided: sk-mock****. You can find your API key in the console.", "type": "invalid_request_error", "param": None, "code": "invalid_api_key"}})
    if mode == "zh_401":
        return _json(401, {"error": {"code": "1002", "message": "令牌已过期或验证不正确"}})
    if mode == "402":
        return _json(402, {"error": {"message": "Insufficient Balance", "type": "unknown_error", "param": None, "code": "invalid_request_error"}})
    if mode == "403":
        return _json(403, {"error": {"code": "AccessDenied", "message": "Request not allowed", "type": "forbidden"}})
    if mode == "404":
        return _json(404, {"error": {"message": "Not Found", "type": "invalid_request_error", "code": "not_found"}})
    if mode == "404_model":
        return _json(400, {"error": {"code": "1211", "message": "模型不存在，请检查模型代码。"}})
    if mode == "429":
        return _json(429, {"error": {"code": "1302", "message": "您的账户已达到速率限制，请您控制请求频率"}}, {"Retry-After": "2"})
    if mode == "429_long":
        return _json(429, {"error": {"code": "1305", "message": "该模型当前访问量过大，请稍后再试"}}, {"Retry-After": "120"})
    if mode == "1308":  # the short Retry-After must NOT be slept through: the window resets at next_flush_time, not in a second
        return _json(429, {"error": {"code": "1308", "message": f"已达到 1000 次 的使用上限。您的限额将在 {NEXT_FLUSH_LOCAL} 重置", "next_flush_time": NEXT_FLUSH_LOCAL}}, {"Retry-After": "1"})
    if mode == "503":
        return _json(503, {"error": {"message": "The server is overloaded, please try again later", "type": "server_error", "code": "server_overloaded"}})
    if mode == "content_filter":
        return _json(400, {"error": {"code": "data_inspection_failed", "message": "Output data may contain inappropriate content.", "type": "data_inspection_failed", "param": None}})
    return None


def render_text(obj: dict, mode: str) -> tuple[str, str]:
    """``(visible text, finish_reason)`` — how the model's answer looks under ``mode``."""
    text = json.dumps(obj, ensure_ascii=False)
    if mode == "fenced_json":
        return "Here is the result you asked for:\n```json\n" + json.dumps(obj, ensure_ascii=False, indent=1) + "\n```\nLet me know if you need changes.", "stop"
    if mode == "invalid_json":
        return "this is not json {{{ garbage", "stop"
    if mode == "truncated":
        return text[: max(10, int(len(text) * 0.6))], "length"
    if mode == "empty_content":
        return "", "stop"
    if mode == "sensitive":  # Zhipu: the answer was blocked by the safety filter (安全审核拦截); the content is empty or boilerplate
        return "", "sensitive"
    if mode == "network_error":  # Zhipu: 模型推理异常 reported as a finish reason behind an HTTP 200
        return "", "network_error"
    return text, "stop"


def _tokens(text: str, per: float) -> int:
    return int(math.ceil(len(text.encode("utf-8")) / per)) if text else 0


def success_response(body: dict, mode: str) -> httpx.Response:
    system, user = prompts_of(body)
    kind = infer_kind(body, system, user)
    if mode == "repairable":
        fake_mode = "ok" if is_repair(body) else "schema_mismatch"
    else:
        fake_mode = mode if mode in ("partial", "schema_mismatch", "invalid_word") else "ok"
    obj, _n = fc.structured_output(kind, user, fake_mode)
    text, finish = render_text(obj, mode)
    prompt_tokens = _tokens(system + user, PROMPT_BYTES_PER_TOKEN) + 20
    completion_tokens = _tokens(text, OUTPUT_BYTES_PER_TOKEN)
    envelope = {
        "id": f"chatcmpl-fake-{next(_ids)}",
        "object": "chat.completion",
        "created": 1760400000,
        "model": str(body.get("model") or DEFAULT_MODEL),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish, "logprobs": None}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
        "fake": {"mode": mode, "kind": kind},
    }
    return _json(200, envelope)


def respond(body: dict, mode: str) -> httpx.Response:
    """The answer for one request body under ``mode`` (raises the transport exceptions of ``network`` / ``timeout``)."""
    if mode == "network":
        raise httpx.ConnectError("[Errno 61] Connection refused")
    if mode == "timeout":
        raise httpx.ReadTimeout("The read operation timed out")
    err = error_response(mode)
    if err is not None:
        return err
    if mode not in MODES and mode != "invalid_word":
        return _json(400, {"error": {"message": f"unknown fake mode {mode!r}", "type": "invalid_request_error"}})
    return success_response(body, mode)


__all__ = ["MODES", "FakeState", "error_response", "infer_kind", "prompts_of", "respond", "schema_of", "set_mode", "success_response", "transport"]
