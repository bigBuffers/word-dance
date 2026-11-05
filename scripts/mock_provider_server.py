#!/usr/bin/env python3
"""Mock OpenAI-format / Anthropic-format model provider for ``scripts/eval_provider.py`` (stdlib only, no network).

It answers the three endpoints a fallback adapter talks to, with the real response shapes (``usage``,
``finish_reason`` / ``stop_reason``, ``tool_calls`` / ``tool_use`` blocks) and builds schema-valid items for the
words, strings and ids it finds in the prompt's ``<items>`` block by importing the item builders of
``backend/tests/fake_claude.py`` (``content_item`` · ``lookup_item`` · ``consolidate_item`` · ``svg_output`` ·
``PROBE_ANSWER``). It binds 127.0.0.1 only and never reads the ``Authorization`` / ``x-api-key`` values.

Endpoints
    POST /v1/chat/completions          OpenAI chat-completions shape (``response_format`` and ``tools`` accepted)
    POST /v1/messages                  Anthropic Messages shape (``tools`` → ``tool_use`` block, ``output_config`` accepted)
    POST /anthropic/v1/messages        the same handler under the ``/anthropic`` prefix (Zhipu / DeepSeek style base URLs)
    GET  /health · GET /v1/models      liveness and a model list

Modes (header ``X-Mock-Mode: <mode>`` per request, else env ``MOCK_MODE``, else ``--mode``; default ``ok``)
    ok              schema-valid JSON for every requested item (HTTP 200)
    fenced_json     the same JSON wrapped in a ```json fence with prose around it
    invalid_json    HTTP 200 whose content is not JSON
    schema_mismatch one required key dropped from every item (``fake_claude.REQUIRED_DROP``)
    partial         the last requested item is missing
    truncated       the JSON cut at 60 % with ``finish_reason: length`` / ``stop_reason: max_tokens``
    empty_content   HTTP 200 with an empty ``content`` (DeepSeek json_object blank-output behaviour)
    slow:<s>        sleep ``s`` seconds, then answer like ``ok`` (use with ``--timeout-scale`` to exercise timeouts)
    401 · zh_401    authentication failures (OpenAI/Anthropic envelope · Zhipu's Chinese ``令牌已过期或验证不正确`` body)
    402             ``Insufficient Balance`` (DeepSeek wording)
    403             ``Request not allowed`` / 百炼-style ``authentication_error`` body
    429             rate limit with ``Retry-After: 2`` (Zhipu code 1302 wording)
    503             server overloaded
    content_filter  HTTP 400 ``data_inspection_failed`` (DashScope wording)

Invocation (no Makefile target on purpose — the files are untracked)
    /Users/sqin/word-dance/.venv/bin/python /Users/sqin/word-dance/scripts/mock_provider_server.py --port 8765
    MOCK_MODE=429 /Users/sqin/word-dance/.venv/bin/python /Users/sqin/word-dance/scripts/mock_provider_server.py --port 8766
    curl -s http://127.0.0.1:8765/health

The same handler is importable for unit tests::

    from mock_provider_server import respond, transport   # transport() returns an httpx.MockTransport
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TESTS_DIR = HERE.parent / "backend" / "tests"
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import fake_claude as fc  # noqa: E402  (backend/tests/fake_claude.py — stdlib only)

MODES: tuple[str, ...] = (
    "ok",
    "fenced_json",
    "invalid_json",
    "schema_mismatch",
    "partial",
    "truncated",
    "empty_content",
    "slow",
    "401",
    "zh_401",
    "402",
    "403",
    "429",
    "503",
    "content_filter",
)
FAKE_PASSTHROUGH_MODES = {"partial", "schema_mismatch", "invalid_word"}
PROMPT_BYTES_PER_TOKEN = 3.0
OUTPUT_BYTES_PER_TOKEN = 2.6
DEFAULT_MODEL_IDS = ("mock-flash", "glm-4.7-flash", "qwen3.7-flash")
_counter_lock = threading.Lock()
_counter = [0]


def _next_id() -> int:
    with _counter_lock:
        _counter[0] += 1
        return _counter[0]


# ------------------------------------------------------------------------------------------- request parsing
def _text_of(content: Any) -> str:
    """A message/system ``content`` as text: a string, or the concatenated ``text`` of a list of parts/blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                out.append(part["text"])
            elif isinstance(part, str):
                out.append(part)
        return "\n".join(out)
    return ""


def prompts_of(body: dict, fmt: str) -> tuple[str, str]:
    """``(system_text, user_text)`` of an OpenAI or Anthropic request body."""
    if fmt == "anthropic":
        system = _text_of(body.get("system"))
        users = [_text_of(m.get("content")) for m in body.get("messages", []) if isinstance(m, dict) and m.get("role") == "user"]
        return system, "\n".join(users)
    systems, users = [], []
    for m in body.get("messages", []):
        if not isinstance(m, dict):
            continue
        if m.get("role") in ("system", "developer"):
            systems.append(_text_of(m.get("content")))
        elif m.get("role") == "user":
            users.append(_text_of(m.get("content")))
    return "\n".join(systems), "\n".join(users)


def schema_of(body: dict, fmt: str) -> dict | None:
    """The JSON schema the client asked for, wherever the format carries it (None in json_object / prompt-only mode)."""
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        t = tools[0] if isinstance(tools[0], dict) else {}
        if fmt == "anthropic":
            s = t.get("input_schema")
        else:
            s = (t.get("function") or {}).get("parameters") if isinstance(t.get("function"), dict) else None
        if isinstance(s, dict):
            return s
    if fmt == "anthropic":
        for key in ("output_config", "output_format"):
            cfg = body.get(key)
            if isinstance(cfg, dict):
                f = cfg.get("format") if isinstance(cfg.get("format"), dict) else cfg
                if isinstance(f, dict) and isinstance(f.get("schema"), dict):
                    return f["schema"]
    rf = body.get("response_format")
    if isinstance(rf, dict) and rf.get("type") == "json_schema":
        js = rf.get("json_schema")
        if isinstance(js, dict) and isinstance(js.get("schema"), dict):
            return js["schema"]
    return None


def infer_kind(body: dict, fmt: str, system: str, user: str) -> str:
    schema = schema_of(body, fmt)
    if schema is not None:
        return fc.infer_kind(schema)
    text = user or ""
    if "Generate study content" in text:
        return "content"
    if "Look up these strings" in text:
        return "lookup"
    if "Examine this learner's word bank" in text:
        return "consolidate"
    if "Draw an illustration for the word" in text:
        return "svg"
    if "echo set to the exact text word-dance" in text:
        return "probe"
    # json_object mode embeds the schema in the system prompt: look there last
    m = re.search(r"\{.*\}", system or "", re.DOTALL)
    if m:
        try:
            return fc.infer_kind(json.loads(m.group(0)))
        except ValueError:
            pass
    return "content"


def wants_tool(body: dict, fmt: str) -> tuple[bool, str]:
    """Whether the client asked for a tool call and the tool's name."""
    tools = body.get("tools")
    if not (isinstance(tools, list) and tools and isinstance(tools[0], dict)):
        return False, ""
    if fmt == "anthropic":
        return True, str(tools[0].get("name") or "submit")
    fn = tools[0].get("function") if isinstance(tools[0].get("function"), dict) else {}
    return True, str(fn.get("name") or "submit")


def parse_mode(headers: dict[str, str], default_mode: str) -> tuple[str, float]:
    """``(mode, slow_seconds)`` from ``X-Mock-Mode`` / ``MOCK_MODE`` / the server default."""
    raw = ""
    for k, v in headers.items():
        if k.lower() == "x-mock-mode":
            raw = v.strip()
            break
    raw = raw or os.environ.get("MOCK_MODE", "").strip() or default_mode
    if raw.startswith("slow"):
        try:
            secs = float(raw.split(":", 1)[1]) if ":" in raw else 5.0
        except ValueError:
            secs = 5.0
        return "slow", secs
    return raw, 0.0


# ------------------------------------------------------------------------------------------- content building
def build_output(kind: str, user: str, mode: str) -> tuple[dict, int]:
    fake_mode = mode if mode in FAKE_PASSTHROUGH_MODES else "ok"
    return fc.structured_output(kind, user, fake_mode)


def render_text(obj: dict, mode: str) -> tuple[str, bool]:
    """``(text, truncated)`` — how the model's visible text looks under ``mode``."""
    text = json.dumps(obj, ensure_ascii=False)
    if mode == "fenced_json":
        return "Here is the result you asked for:\n```json\n" + json.dumps(obj, ensure_ascii=False, indent=1) + "\n```\nLet me know if you need changes.", False
    if mode == "invalid_json":
        return "this is not json {{{ garbage", False
    if mode == "truncated":
        return text[: max(10, int(len(text) * 0.6))], True
    if mode == "empty_content":
        return "", False
    return text, False


def _tokens(text: str, per: float) -> int:
    return int(math.ceil(len(text.encode("utf-8")) / per)) if text else 0


def openai_success(body: dict, mode: str, kind: str, system: str, user: str) -> tuple[int, dict[str, str], bytes]:
    obj, _n = build_output(kind, user, mode)
    text, truncated = render_text(obj, mode)
    use_tool, tool_name = wants_tool(body, "openai")
    message: dict[str, Any] = {"role": "assistant", "content": None if use_tool else text}
    finish = "stop"
    if use_tool:
        message["tool_calls"] = [{"id": f"call_mock_{_next_id()}", "type": "function", "function": {"name": tool_name, "arguments": text}}]
        finish = "tool_calls"
    if truncated:
        finish = "length"
    prompt_tokens = _tokens(system + user, PROMPT_BYTES_PER_TOKEN) + 20
    completion_tokens = _tokens(text, OUTPUT_BYTES_PER_TOKEN)
    envelope = {
        "id": f"chatcmpl-mock-{_next_id()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": str(body.get("model") or DEFAULT_MODEL_IDS[0]),
        "choices": [{"index": 0, "message": message, "finish_reason": finish, "logprobs": None}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "prompt_tokens_details": {"cached_tokens": 0},
        },
        "mock": {"mode": mode, "kind": kind},
    }
    return 200, {"Content-Type": "application/json"}, json.dumps(envelope, ensure_ascii=False).encode("utf-8")


def anthropic_success(body: dict, mode: str, kind: str, system: str, user: str) -> tuple[int, dict[str, str], bytes]:
    obj, _n = build_output(kind, user, mode)
    text, truncated = render_text(obj, mode)
    use_tool, tool_name = wants_tool(body, "anthropic")
    blocks: list[dict[str, Any]]
    stop = "end_turn"
    if use_tool and mode not in ("invalid_json", "fenced_json", "truncated", "empty_content"):
        blocks = [{"type": "tool_use", "id": f"toolu_mock_{_next_id()}", "name": tool_name, "input": obj}]
        stop = "tool_use"
    else:
        blocks = [{"type": "text", "text": text}] if text else []
    if truncated:
        stop = "max_tokens"
    input_tokens = _tokens(system + user, PROMPT_BYTES_PER_TOKEN) + 20
    output_tokens = _tokens(text, OUTPUT_BYTES_PER_TOKEN)
    envelope = {
        "id": f"msg_mock_{_next_id()}",
        "type": "message",
        "role": "assistant",
        "model": str(body.get("model") or DEFAULT_MODEL_IDS[0]),
        "content": blocks,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        "mock": {"mode": mode, "kind": kind},
    }
    return 200, {"Content-Type": "application/json"}, json.dumps(envelope, ensure_ascii=False).encode("utf-8")


# ------------------------------------------------------------------------------------------- error bodies
def error_response(mode: str, fmt: str) -> tuple[int, dict[str, str], bytes] | None:
    """Real-world shaped error bodies per mode (None when ``mode`` is not an error mode)."""
    headers = {"Content-Type": "application/json"}
    anth = fmt == "anthropic"

    def a(status: int, etype: str, message: str) -> tuple[int, dict[str, str], bytes]:
        return status, headers, json.dumps({"type": "error", "error": {"type": etype, "message": message}}, ensure_ascii=False).encode("utf-8")

    def o(status: int, payload: dict) -> tuple[int, dict[str, str], bytes]:
        return status, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")

    if mode == "401":
        if anth:
            return a(401, "authentication_error", "invalid x-api-key")
        return o(401, {"error": {"message": "Incorrect API key provided: sk-mock****. You can find your API key in the console.", "type": "invalid_request_error", "param": None, "code": "invalid_api_key"}})
    if mode == "zh_401":
        if anth:
            return o(401, {"error": {"message": "令牌已过期或验证不正确", "type": "401"}})
        return o(401, {"error": {"code": "401", "message": "令牌已过期或验证不正确"}})
    if mode == "402":
        if anth:
            return a(402, "invalid_request_error", "Insufficient Balance")
        return o(402, {"error": {"message": "Insufficient Balance", "type": "unknown_error", "param": None, "code": "invalid_request_error"}})
    if mode == "403":
        if anth:
            return o(403, {"message": "invalid api-key", "type": "authentication_error", "param": None, "code": None})
        return o(403, {"error": {"code": "AccessDenied", "message": "Request not allowed", "type": "forbidden"}})
    if mode == "429":
        headers = {**headers, "Retry-After": "2"}
        if anth:
            return 429, headers, json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "您的账户已达到速率限制，请您控制请求频率"}}, ensure_ascii=False).encode("utf-8")
        return 429, headers, json.dumps({"error": {"code": "1302", "message": "您的账户已达到速率限制，请您控制请求频率"}}, ensure_ascii=False).encode("utf-8")
    if mode == "503":
        if anth:
            return a(503, "overloaded_error", "Overloaded")
        return o(503, {"error": {"message": "The server is overloaded, please try again later", "type": "server_error", "code": "server_overloaded"}})
    if mode == "content_filter":
        if anth:
            return a(400, "invalid_request_error", "Output data may contain inappropriate content. (data_inspection_failed)")
        return o(400, {"error": {"code": "data_inspection_failed", "message": "Output data may contain inappropriate content.", "type": "data_inspection_failed", "param": None}})
    return None


# ------------------------------------------------------------------------------------------- dispatcher
def respond(method: str, path: str, headers: dict[str, str], raw_body: bytes, default_mode: str = "ok") -> tuple[int, dict[str, str], bytes]:
    """Pure dispatcher: ``(status, headers, body)`` for one request — used by the HTTP server and by :func:`transport`."""
    path = path.split("?", 1)[0]
    if method == "GET" and path == "/health":
        return 200, {"Content-Type": "application/json"}, json.dumps({"ok": True, "default_mode": default_mode, "modes": list(MODES)}).encode("utf-8")
    if method == "GET" and path.endswith("/v1/models"):
        data = [{"id": m, "object": "model", "owned_by": "mock"} for m in DEFAULT_MODEL_IDS]
        return 200, {"Content-Type": "application/json"}, json.dumps({"object": "list", "data": data}).encode("utf-8")
    if method != "POST":
        return 405, {"Content-Type": "application/json"}, b'{"error":{"message":"method not allowed"}}'
    if path.endswith("/chat/completions"):
        fmt = "openai"
    elif path.endswith("/v1/messages") or path.endswith("/messages"):
        fmt = "anthropic"
    else:
        return 404, {"Content-Type": "application/json"}, json.dumps({"error": {"message": f"no route for {path}", "type": "not_found"}}).encode("utf-8")
    try:
        body = json.loads(raw_body.decode("utf-8") or "{}")
        if not isinstance(body, dict):
            raise ValueError("body is not an object")
    except (ValueError, UnicodeDecodeError) as e:
        return 400, {"Content-Type": "application/json"}, json.dumps({"error": {"message": f"invalid JSON body: {e}", "type": "invalid_request_error"}}).encode("utf-8")
    mode, slow_s = parse_mode(headers, default_mode)
    if mode == "slow":
        time.sleep(slow_s)
        mode = "ok"
    err = error_response(mode, fmt)
    if err is not None:
        return err
    if mode not in MODES and mode != "invalid_word":
        return 400, {"Content-Type": "application/json"}, json.dumps({"error": {"message": f"unknown mock mode {mode!r}", "type": "invalid_request_error"}}).encode("utf-8")
    system, user = prompts_of(body, fmt)
    kind = infer_kind(body, fmt, system, user)
    if fmt == "anthropic":
        return anthropic_success(body, mode, kind, system, user)
    return openai_success(body, mode, kind, system, user)


def transport(default_mode: str = "ok"):
    """An ``httpx.MockTransport`` over :func:`respond` for unit tests (httpx imported lazily)."""
    import httpx

    def handler(request: "httpx.Request") -> "httpx.Response":
        status, headers, body = respond(request.method, request.url.path, dict(request.headers), request.content, default_mode)
        return httpx.Response(status, headers=headers, content=body)

    return httpx.MockTransport(handler)


# ------------------------------------------------------------------------------------------- HTTP server
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "word-dance-mock/1"
    default_mode = "ok"
    quiet = False

    def _send(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        hdrs = {k: v for k, v in self.headers.items()}
        status, headers, body = respond(self.command, self.path, hdrs, raw, self.default_mode)
        self._send(status, headers, body)
        if not self.quiet:
            mode, _ = parse_mode(hdrs, self.default_mode)
            print(f"mock {self.command} {self.path} mode={mode} -> {status} ({len(body)} B)", file=sys.stderr, flush=True)

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def log_message(self, fmt: str, *args: Any) -> None:  # silence the default access log
        return


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mock OpenAI/Anthropic-format provider for scripts/eval_provider.py (binds 127.0.0.1 only).")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--mode", default=os.environ.get("MOCK_MODE", "ok"), help="default mode when no X-Mock-Mode header is sent (env MOCK_MODE)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    Handler.default_mode = args.mode
    Handler.quiet = args.quiet
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"mock provider listening on http://127.0.0.1:{args.port} (default mode {args.mode!r}); endpoints: /v1/chat/completions /v1/messages /anthropic/v1/messages", file=sys.stderr, flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
