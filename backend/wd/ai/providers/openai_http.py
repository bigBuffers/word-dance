"""OpenAI-format HTTP adapter — the ``fallback`` provider (AI_FALLBACK_MODEL §4.1–§4.2, CLAUDE_INTEGRATION §10).

The second implementation of the ``run_claude`` seam. One ``POST {base_url}/chat/completions`` per call:

* the system prompt carries the compact JSON schema (``json_object`` mode — Zhipu / DeepSeek / generic) or the request
  carries ``response_format.json_schema`` built by :func:`strict_schema` (百炼); the five schema files stay untouched;
* the vendor's thinking switch comes from :func:`thinking_fields`; ``temperature`` is never sent;
* the answer is validated with ``jsonschema`` (Draft 2020-12) against the ORIGINAL schema; one repair round re-asks with
  the validator's messages; ``finish_reason`` ``length`` / ``content_filter`` and unparseable text are per-call ``error``
  results (never a switch trigger, AI_FALLBACK_MODEL §4.2);
* HTTP failures map onto the ledger's status vocabulary with the CLAUDE_INTEGRATION §10 error prefixes (``balance:`` ``quota:`` ``network:``
  ``not_found:`` ``content_filter:`` ``truncated:`` ``invalid_json:`` ``schema:``) that ``ai/failover.py`` reads; a
  ``Retry-After`` of at most :data:`RETRY_AFTER_MAX_S` is honoured once inline; Zhipu's own ``finish_reason`` values are
  read as well (``sensitive`` → ``content_filter:``, ``network_error`` → ``network:`` with status ``overloaded``);
* ``timeout_s`` is the budget of the WHOLE call, not of one request: round 0, the inline retry and the repair round are
  each bounded by what is left of it (the connect phase by :data:`CONNECT_TIMEOUT_S`, never more than the remaining), the
  retry and the repair round are issued only when at least :data:`MIN_REMAINING_S` would be left for them, otherwise the
  row finishes as ``timeout`` — one call never outlives its kind's timeout by more than the connect overhead, so a claimed
  group stays inside the 15-minute stale sweep (AI_FALLBACK_MODEL §4.2);
* the ledger row exists **before** the request (``provider='fallback'``, ``reserved_usd`` 0 — the free tier reserves
  nothing, a paid price table is charged post hoc through ``cost_usd``) and is finished on every path — an unexpected
  exception inside the request loop becomes a per-call ``error`` (``internal: …``) rather than a row stuck in
  ``running`` — with the tokens, the HTTP status as ``exit_code``, the model the vendor reports and the price-table
  cost; the raw exchange goes through :func:`wd.ai.runner.save_raw` (response bodies only — never the request, never
  the key).
"""

from __future__ import annotations

import copy
import json
import logging
import re
import sqlite3
import stat
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import httpx
import jsonschema

from ... import __version__
from ...clock import now_iso, parse_iso, to_iso, zone
from ...config import Settings
from ...interfaces import ClaudeResult
from .. import budget, ledger, runner
from . import FALLBACK

log = logging.getLogger("wd.ai.openai_http")

#: per-kind ``max_tokens`` when ``WD_AI_FALLBACK_MAX_OUTPUT_TOKENS`` is 0 (AI_FALLBACK_MODEL §2.1: lookup 8192, consolidate 12288, content 8192).
#: A 20-string lookup group (``queue.limit_for``) answers 13 fields per item ≈ 3,700 output tokens at the 2.55 bytes/token calibration:
#: 4096 left no headroom and a verbose model hit ``finish_reason=length`` (``truncated:`` — a per-call error that bisects the group).
DEFAULT_MAX_TOKENS: dict[str, int] = {"content": 8192, "lookup": 8192, "consolidate": 12288, "svg": 4096, "probe": 512}
CONNECT_TIMEOUT_S = 20.0
#: ``timeout_s`` bounds the whole call (AI_FALLBACK_MODEL §4.2, CLAUDE_INTEGRATION §10.3): the inline retry and the repair round
#: are issued only when at least this many seconds of the budget would be left for them (retry: ``wait + MIN_REMAINING_S <= remaining``)
MIN_REMAINING_S = 15.0
RETRY_AFTER_MAX_S = 10.0  # AI_FALLBACK_MODEL §4.2: a short ``Retry-After`` is slept through once inside the adapter; longer ones defer the job
BODY_EXCERPT_CHARS = 300
CLASSIFY_CHARS = 4000
MAX_SCHEMA_ERRORS = 5
VENDOR_TZ = "Asia/Shanghai"  # Zhipu's 1308 message carries a naive Beijing-time instant
DIALECT_HOSTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("zhipu", ("bigmodel.cn", "z.ai")),
    ("bailian", ("aliyuncs.com", "dashscope")),
    ("deepseek", ("deepseek.com",)),
)
JSON_OBJECT_SUFFIX = (
    "\n\nOutput format: respond with ONE JSON object only — no markdown code fences, no commentary — "
    "that conforms exactly to this JSON Schema:\n"
)
JSON_SCHEMA_SUFFIX = "\n\nRespond with one JSON object that conforms to the provided JSON schema."
REPAIR_PREFIX = "Your JSON failed validation against the schema: "
REPAIR_SUFFIX = ". Return the complete corrected JSON object only."

# AI_FALLBACK_MODEL §4.2 classification table (case-insensitive). The quoted numbers are Zhipu business codes as they appear in JSON bodies.
BALANCE_RE = re.compile(r'insufficient balance|余额不足|欠费|arrearage|insufficient_quota|"1113"', re.IGNORECASE)
QUOTA_RE = re.compile(r'allocationquota|free.?tier|quota exceeded|使用上限|"1308"', re.IGNORECASE)
FILTER_RE = re.compile(r'data_inspection|content_filter|contentfilter|inappropriate|"1301"|敏感|不安全', re.IGNORECASE)
#: "the model does not exist" in its vendor spellings (Zhipu 1211, OpenAI ``model_not_found`` / "The model `x` does not exist",
#: DashScope / DeepSeek "Model not exist"); anchored to the word *model* so a 400 about some other parameter stays ``http_400``
NOT_FOUND_RE = re.compile(r'"1211"|model[_ ]not[_ ]found|模型不存在|no such model|\bmodel\b[^"\n]{0,40}?(?:does )?not exist', re.IGNORECASE)
#: auth wording for an error envelope that arrived with HTTP 200 (Zhipu 1000–1004, OpenAI ``invalid_api_key``)
UNAUTHORIZED_RE = re.compile(r'"100[0-4]"|invalid[_ ]api[_ ]key|incorrect api key|令牌已过期|身份验证失败|authentication (?:failed|error)|unauthorized', re.IGNORECASE)
FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
LOCAL_STAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?")
OFFSET_RE = re.compile(r"(?:[zZ]|[+-]\d{2}:?\d{2})$")
TRUNCATION_REASONS = ("length", "max_tokens")
FILTER_REASONS = ("content_filter", "refusal", "sensitive")  # ``sensitive``: Zhipu's 安全审核拦截 — the answer was blocked by the safety filter
#: Zhipu's ``network_error`` (模型推理异常 reported as a finish reason behind an HTTP 200): a vendor-side failure, classified ``network:`` /
#: ``overloaded`` so the network streak and the defer path apply instead of a never-trigger per-call error (CLAUDE_INTEGRATION §10.3)
VENDOR_FAILURE_REASONS = ("network_error",)

#: test hook: returns the ``httpx.Client`` for a given total timeout (seconds); None = a real client, ``trust_env=False``.
#: The client's own timeout is the whole budget; every request additionally carries the budget still left as its per-request timeout.
CLIENT_FACTORY: Callable[[float], httpx.Client] | None = None
#: test hook for the ``Retry-After`` pause
SLEEP: Callable[[float], None] = time.sleep
#: test hook for the monotonic clock the call's deadline and ``duration_ms`` are measured with
CLOCK: Callable[[], float] = time.perf_counter


# ------------------------------------------------------------------------------------- request shaping
def _host_matches(host: str, needle: str) -> bool:
    if "." in needle:
        return host == needle or host.endswith("." + needle)
    return needle in host


def resolve_dialect(cfg: Settings) -> str:
    """``WD_AI_FALLBACK_DIALECT`` when explicit, else by host: bigmodel.cn / z.ai → zhipu; aliyuncs.com / dashscope → bailian;
    deepseek.com → deepseek; anything else → generic."""
    explicit = str(getattr(cfg, "ai_fallback_dialect", "auto") or "auto")
    if explicit != "auto":
        return explicit
    host = (urlsplit(str(getattr(cfg, "ai_fallback_base_url", "") or "")).hostname or "").lower()
    for dialect, needles in DIALECT_HOSTS:
        if any(_host_matches(host, n) for n in needles):
            return dialect
    return "generic"


def json_mode_for(cfg: Settings, dialect: str) -> str:
    """``WD_AI_FALLBACK_JSON_MODE`` when explicit; else 百炼 speaks strict ``json_schema``, everyone else ``json_object``."""
    explicit = str(getattr(cfg, "ai_fallback_json_mode", "auto") or "auto")
    if explicit != "auto":
        return explicit
    return "json_schema" if dialect == "bailian" else "json_object"


def thinking_fields(dialect: str, thinking: str) -> dict[str, Any]:
    """The vendor's extended-thinking switch (AI_FALLBACK_MODEL §4.3): Zhipu / DeepSeek ``thinking.type``, 百炼 ``enable_thinking``; ``default`` sends nothing."""
    if thinking == "off":
        if dialect in ("zhipu", "deepseek"):
            return {"thinking": {"type": "disabled"}}
        if dialect == "bailian":
            return {"enable_thinking": False}
        return {}
    if thinking == "on":
        if dialect in ("zhipu", "deepseek"):
            return {"thinking": {"type": "enabled"}}
        if dialect == "bailian":
            return {"enable_thinking": True}
        return {}
    return {}


def strict_schema(schema: dict) -> dict:
    """A deep copy for OpenAI strict mode: every object node gets ``additionalProperties: false`` and ``required`` = all of its
    property names (the schema files are frozen — ``tests/test_claude_fixtures`` asserts them verbatim)."""

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        out = {k: walk(v) for k, v in node.items()}
        if out.get("type") == "object":
            props = out.get("properties") if isinstance(out.get("properties"), dict) else {}
            out["additionalProperties"] = False
            out["required"] = list(props.keys())
        return out

    return walk(copy.deepcopy(schema))


def compose_system(system_prompt: str, schema: dict, json_mode: str) -> str:
    """The system message: the production prompt plus the output-format instruction. ``json_object`` embeds the compact
    schema (and the word JSON, which OpenAI-style ``json_object`` requires in the prompt); ``json_schema`` only points at it."""
    base = system_prompt or ""
    if json_mode == "json_schema":
        return base + JSON_SCHEMA_SUFFIX
    return base + JSON_OBJECT_SUFFIX + runner.schema_arg(schema)


def endpoint_url(base_url: str) -> str:
    """``{base_url}/chat/completions`` unless the configured URL already is the completions endpoint."""
    base = (base_url or "").strip().rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def build_body(cfg: Settings, *, kind: str, schema: dict, messages: list[dict[str, Any]], dialect: str, json_mode: str) -> dict[str, Any]:
    """The chat-completions request body (CLAUDE_INTEGRATION §10). No ``temperature``; ``stream`` false."""
    override = int(getattr(cfg, "ai_fallback_max_output_tokens", 0) or 0)
    body: dict[str, Any] = {
        "model": cfg.ai_fallback_model,
        "messages": messages,
        "stream": False,
        "max_tokens": override or DEFAULT_MAX_TOKENS.get(kind, DEFAULT_MAX_TOKENS["content"]),
    }
    if json_mode == "json_schema":
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": f"{kind}_v1", "schema": strict_schema(schema), "strict": True}}
    else:
        body["response_format"] = {"type": "json_object"}
    body.update(thinking_fields(dialect, str(getattr(cfg, "ai_fallback_thinking", "off") or "off")))
    return body


def api_key(cfg: Settings) -> str | None:
    """``WD_AI_FALLBACK_API_KEY``, else the first line of ``WD_AI_FALLBACK_API_KEY_FILE`` (a 0600 file; a UTF-8 BOM is
    tolerated) stripped; None when neither yields a non-empty value. The value is never logged — only the file's path and
    mode are. :func:`run_openai` additionally refuses a key that is not printable ASCII (a BOM or a full-width character
    in the environment value) before any request, since such a key cannot travel in an HTTP header."""
    direct = str(getattr(cfg, "ai_fallback_api_key", "") or "").strip()
    if direct:
        return direct
    path_text = str(getattr(cfg, "ai_fallback_api_key_file", "") or "").strip()
    if not path_text:
        return None
    path = Path(path_text).expanduser()
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            log.warning("fallback key file %s is readable by group/others (mode %o); chmod 600 it", path, mode)
        with path.open("r", encoding="utf-8-sig") as f:
            first = f.readline()
    except OSError as e:
        log.warning("fallback key file %s could not be read: %s", path, e.__class__.__name__)
        return None
    key = first.strip()
    return key or None


# ------------------------------------------------------------------------------------------ parsing
def extract_json(text: str | None) -> tuple[dict | None, str]:
    """``(object, "")`` from the model's visible text — ``` fences stripped, then the outermost ``{…}`` — or ``(None, reason)``."""
    if text is None:
        return None, "no text"
    s = str(text).strip()
    if not s:
        return None, "empty content"
    m = FENCE_RE.search(s)
    if m:
        s = m.group(1).strip()
    obj, err = _loads_object(s)
    if obj is not None or err.startswith("JSON is a"):
        return obj, err
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        return _loads_object(s[start : end + 1])
    return None, "no JSON object found"


def _loads_object(s: str) -> tuple[dict | None, str]:
    try:
        obj = json.loads(s)
    except ValueError as e:
        return None, f"invalid JSON: {e}"[:200]
    if isinstance(obj, dict):
        return obj, ""
    return None, f"JSON is a {type(obj).__name__}, not an object"


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def usage_tokens(usage: Any) -> dict[str, int | None]:
    """``{input_tokens, output_tokens, cache_read_tokens}`` from an OpenAI ``usage`` block (``prompt_tokens`` /
    ``completion_tokens`` / ``prompt_tokens_details.cached_tokens`` or DeepSeek's ``prompt_cache_hit_tokens``); a dict
    already in that shape passes through."""
    u = usage if isinstance(usage, Mapping) else {}
    details = u.get("prompt_tokens_details") if isinstance(u.get("prompt_tokens_details"), Mapping) else {}
    cached = details.get("cached_tokens")
    if cached is None:
        cached = u.get("prompt_cache_hit_tokens", u.get("cache_read_tokens"))
    return {
        "input_tokens": _int(u.get("prompt_tokens", u.get("input_tokens"))),
        "output_tokens": _int(u.get("completion_tokens", u.get("output_tokens"))),
        "cache_read_tokens": _int(cached),
    }


def _add_usage(total: dict[str, int | None], usage: Any) -> None:
    for k, v in usage_tokens(usage).items():
        if v is not None:
            total[k] = int(total.get(k) or 0) + v


def price_table(cfg: Settings) -> dict[str, float]:
    """``WD_AI_FALLBACK_PRICE_JSON`` parsed: ``{"input": CNY/1M, "output": CNY/1M, "cache_read"?: CNY/1M}``; ``{}`` = free."""
    raw = str(getattr(cfg, "ai_fallback_price_json", "") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): float(v) for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0}


def price_cost_usd(cfg: Settings, usage: Any) -> float:
    """CNY price table × tokens / 1e6 / ``WD_AI_CNY_PER_USD``; 0.0 without a table (the free tier). Cached prompt tokens
    are billed at ``cache_read`` when that price exists, the rest of the prompt at ``input``."""
    table = price_table(cfg)
    if not table:
        return 0.0
    t = usage_tokens(usage)
    prompt = int(t["input_tokens"] or 0)
    completion = int(t["output_tokens"] or 0)
    cached = min(int(t["cache_read_tokens"] or 0), prompt)
    if "cache_read" in table and cached:
        cny = (prompt - cached) * table.get("input", 0.0) + cached * table["cache_read"]
    else:
        cny = prompt * table.get("input", 0.0)
    cny += completion * table.get("output", 0.0)
    rate = float(getattr(cfg, "ai_cny_per_usd", 7.2) or 7.2)
    return round(cny / 1e6 / rate, 6)


# ----------------------------------------------------------------------------------- classification
def _instant(value: Any) -> str | None:
    """A vendor-supplied instant (epoch seconds/ms, ISO with offset, or a naive Beijing-time stamp) as UTC ISO, else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        secs = float(value)
        if secs > 1e11:
            secs /= 1000.0
        try:
            return to_iso(datetime.fromtimestamp(secs, tz=timezone.utc))
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if re.fullmatch(r"\d{10,13}(?:\.\d+)?", s):
        return _instant(float(s))
    if OFFSET_RE.search(s):
        try:
            return to_iso(parse_iso(s))
        except ValueError:
            return None
    m = LOCAL_STAMP_RE.search(s)
    if not m:
        return None
    stamp = m.group(0).replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            naive = datetime.strptime(stamp, fmt)
        except ValueError:
            continue
        return to_iso(naive.replace(tzinfo=zone(VENDOR_TZ)))
    return None


def _find_key(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for v in node:
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


def retry_at_from_body(body_text: str) -> str | None:
    """When a windowed cap resets (Zhipu 1308: ``next_flush_time`` as a field or inside the message), as UTC ISO; else None."""
    text = body_text or ""
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    value = _find_key(data, "next_flush_time")
    if value is not None:
        iso = _instant(value)
        if iso:
            return iso
    if "next_flush_time" in text or QUOTA_RE.search(text):
        m = LOCAL_STAMP_RE.search(text)
        if m:
            return _instant(m.group(0))
    return None


def classify_http(status_code: int, body_text: str, headers: Mapping[str, str] | None = None) -> tuple[str, str, str | None]:
    """``(ledger status, error prefix or reason, retry_at_iso)`` for a non-200 answer (AI_FALLBACK_MODEL §4.2, CLAUDE_INTEGRATION §10).

    Prefix reasons end with ``:`` (``balance:`` ``quota:`` ``not_found:`` ``content_filter:``) and start the ledger error
    text so ``failover`` can read them; plain reasons (``unauthorized`` ``forbidden`` ``rate_limit`` ``http_503``) are
    informational. ``headers`` is accepted for symmetry with the transport (``Retry-After`` is handled by the inline retry).
    """
    code = int(status_code)
    text = (body_text or "")[:CLASSIFY_CHARS]
    if code == 401:
        return "auth", "unauthorized", None
    if code == 402 or BALANCE_RE.search(text):
        return "auth", "balance:", None
    if code == 403:
        if QUOTA_RE.search(text):
            return "auth", "quota:", retry_at_from_body(text)
        return "auth", "forbidden", None
    if code == 404 or (code == 400 and NOT_FOUND_RE.search(text)):
        return "spawn_error", "not_found:", None
    if code == 429:
        if QUOTA_RE.search(text) or "next_flush_time" in text:
            return "overloaded", "quota:", retry_at_from_body(text)
        return "overloaded", "rate_limit", None
    if code in (500, 502, 503, 504, 529):
        return "overloaded", f"http_{code}", None
    if code == 400 and FILTER_RE.search(text):
        return "error", "content_filter:", None
    return "error", f"http_{code}", None


def classify_exception(exc: BaseException, timeout_s: float) -> tuple[str, str]:
    """Transport failures (CLAUDE_INTEGRATION §10.3): ``httpx.TimeoutException`` → ``timeout``; every other ``httpx.HTTPError`` /
    ``OSError`` (connection refused / reset, DNS, TLS — and a malformed base URL, ``UnsupportedProtocol`` / ``InvalidURL``,
    whose message names the cause) → ``overloaded`` with the ``network:`` prefix (its own failover streak)."""
    name = exc.__class__.__name__
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", f"timeout after {_seconds(timeout_s)}s: {name}"
    return "overloaded", f"network: {name}: {str(exc)[:200]}"


def envelope_status(err: Any, body_text: str) -> int:
    """The HTTP status an ``{"error": …}`` envelope stands for when the gateway answered **200** (defence in depth — Zhipu's
    OpenAI path uses real status codes): an explicit ``status`` / ``http_status`` / ``status_code``, a ``code`` that is
    itself an HTTP status, else 401 for auth wording, 429 for quota wording and 400 otherwise; :func:`classify_http` then
    applies the body patterns (``balance:`` ``quota:`` ``not_found:`` ``content_filter:``) exactly as for a real status."""
    fields = err if isinstance(err, Mapping) else {}
    for name in ("status", "http_status", "status_code", "code"):
        code = _int(fields.get(name))
        if code is not None and 400 <= code <= 599:
            return code
    text = (body_text or "")[:CLASSIFY_CHARS]
    if UNAUTHORIZED_RE.search(text):
        return 401
    if QUOTA_RE.search(text) or "next_flush_time" in text:
        return 429
    return 400


def _seconds(value: float) -> str:
    return f"{float(value):g}"


def compose_error(reason: str, retry_at: str | None, status_code: int, body_text: str) -> str:
    """``<prefix>[ retry_at=<ISO>] HTTP <code>: <first 300 chars of the body>``."""
    head = reason + (f" retry_at={retry_at}" if retry_at else "")
    excerpt = " ".join((body_text or "").split())[:BODY_EXCERPT_CHARS]
    return f"{head} HTTP {status_code}: {excerpt}"


def schema_errors(schema_or_validator: Any, obj: Any) -> list[str]:
    """Draft 2020-12 validation messages as ``path: message`` (``/items/0: 'headword' is a required property``), sorted by path."""
    validator = schema_or_validator if hasattr(schema_or_validator, "iter_errors") else jsonschema.Draft202012Validator(schema_or_validator)
    errors = sorted(validator.iter_errors(obj), key=lambda e: [str(p) for p in e.absolute_path])
    out: list[str] = []
    for e in errors:
        path = "/" + "/".join(str(p) for p in e.absolute_path) if len(e.absolute_path) else "<root>"
        out.append(f"{path}: {e.message[:160]}")
    return out


def repair_prompt(errors: list[str]) -> str:
    """The one repair round's user message (AI_FALLBACK_MODEL §4.1: one repair round): up to five validator messages, then the instruction."""
    return REPAIR_PREFIX + "; ".join(errors[:MAX_SCHEMA_ERRORS]) + REPAIR_SUFFIX


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    s = str(value).strip()
    try:
        return max(0.0, float(s))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _scrub(text: str, key: str | None) -> str:
    return text.replace(key, "***") if key and text else text


# -------------------------------------------------------------------------------------------- transport
@dataclass
class _Exchange:
    """One HTTP round trip (the final one when ``Retry-After`` was honoured)."""

    status_code: int | None = None
    text: str = ""
    data: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    exc: BaseException | None = None


def request_timeout(remaining: float) -> httpx.Timeout:
    """The per-request ``httpx.Timeout`` for ``remaining`` seconds of the call's budget: every phase is bounded by the remaining
    budget, the connect phase additionally by :data:`CONNECT_TIMEOUT_S` (never more than the remaining)."""
    left = max(float(remaining), 0.0)
    return httpx.Timeout(left, connect=min(CONNECT_TIMEOUT_S, left))


def _post_once(client: httpx.Client, url: str, headers: dict[str, str], body: dict[str, Any], *, deadline: float) -> _Exchange:
    try:
        resp = client.post(url, json=body, headers=headers, timeout=request_timeout(deadline - CLOCK()))
    except (httpx.HTTPError, httpx.InvalidURL, OSError) as e:
        return _Exchange(exc=e)
    text = resp.text
    try:
        data = resp.json()
    except ValueError:
        data = None
    return _Exchange(status_code=resp.status_code, text=text, data=data, headers={k.lower(): v for k, v in resp.headers.items()})


def inline_retry_after(ex: _Exchange) -> float | None:
    """Seconds to sleep before the one inline retry (AI_FALLBACK_MODEL §4.2): a 429 with ``Retry-After`` ≤ :data:`RETRY_AFTER_MAX_S`
    whose body is a plain rate limit. None for a longer wait, and for a body that cannot clear within seconds — an
    account in arrears (Zhipu 1113 / ``insufficient_quota``) or a windowed cap (1308 / ``next_flush_time``), which
    :func:`classify_http` turns into ``balance:`` / ``quota:`` and ``failover`` pauses."""
    if ex.status_code != 429:
        return None
    text = (ex.text or "")[:CLASSIFY_CHARS]
    if BALANCE_RE.search(text) or QUOTA_RE.search(text) or "next_flush_time" in text:
        return None
    wait = _retry_after_seconds(ex.headers.get("retry-after"))
    return wait if wait is not None and wait <= RETRY_AFTER_MAX_S else None


def _post(client: httpx.Client, url: str, headers: dict[str, str], body: dict[str, Any], *, deadline: float, may_retry: bool, call_id: int) -> tuple[_Exchange, bool]:
    """POST once within the budget left before ``deadline`` (a :data:`CLOCK` instant); when :func:`inline_retry_after` allows it
    and the wait plus :data:`MIN_REMAINING_S` still fit into that budget, sleep and POST the same request once more. Otherwise
    the 429 keeps its classification (``overloaded`` / ``rate_limit``: the job backs off, the streak counts)."""
    ex = _post_once(client, url, headers, body, deadline=deadline)
    wait = inline_retry_after(ex) if may_retry else None
    if wait is None:
        return ex, False
    remaining = deadline - CLOCK()
    if wait + MIN_REMAINING_S > remaining:
        log.info(
            "fallback call %s rate limited; a Retry-After of %ss does not fit the %ss left of the call's budget — not retried inline",
            call_id,
            _seconds(wait),
            _seconds(max(remaining, 0.0)),
            extra={"event": "fallback_call"},
        )
        return ex, False
    log.info("fallback call %s rate limited; retrying once after %ss", call_id, _seconds(wait), extra={"event": "fallback_call"})
    SLEEP(wait)
    return _post_once(client, url, headers, body, deadline=deadline), True


def _choice_text(data: dict) -> tuple[str | None, str | None]:
    """``(visible text, error)`` of ``choices[0]`` (CLAUDE_INTEGRATION §10): truncation and refusals are errors, a vendor-side failure
    reported as a finish reason (Zhipu ``network_error``) is ``network:``, content parts are joined."""
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    if not choices or not isinstance(choices[0], dict):
        return None, "invalid_json: no choices in the response"
    choice = choices[0]
    finish = str(choice["finish_reason"]) if choice.get("finish_reason") is not None else None
    if finish in TRUNCATION_REASONS:
        return None, f"truncated: finish_reason={finish}"
    if finish in FILTER_REASONS:
        return None, f"content_filter: finish_reason={finish}"
    if finish in VENDOR_FAILURE_REASONS:
        return None, f"network: finish_reason={finish}"
    msg = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    refusal = msg.get("refusal")
    if isinstance(refusal, str) and refusal.strip():
        return None, "content_filter: " + refusal.strip()[:200]
    content = msg.get("content")
    if isinstance(content, list):
        content = "\n".join(p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str))
    return (content if isinstance(content, str) else ""), None


@dataclass
class _Outcome:
    status: str
    error: str | None = None
    structured: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status == "success"


def _client(timeout_s: float) -> httpx.Client:
    if CLIENT_FACTORY is not None:
        return CLIENT_FACTORY(float(timeout_s))
    return httpx.Client(trust_env=False, timeout=httpx.Timeout(float(timeout_s), connect=CONNECT_TIMEOUT_S))


# ------------------------------------------------------------------------------------------------- run
def run_openai(
    conn: sqlite3.Connection,
    *,
    kind: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    timeout_s: int | float,
    word_count: int,
    job_ids: list[int],
    cfg: Settings,
    now: str | None = None,
    call_id: int | None = None,
) -> ClaudeResult:
    """One fallback call (AI_FALLBACK_MODEL §4.1, CLAUDE_INTEGRATION §10): ledger row first, the request, classification, one repair round, bookkeeping on every path.

    ``call_id`` is the ledger row of a prior :func:`wd.ai.budget.reserve` (``provider='fallback'``); otherwise the row is
    inserted here — still before the request. The returned ``ClaudeResult`` carries ``provider='fallback'`` and the CLAUDE_INTEGRATION §10 error
    prefixes; the handlers consume it exactly like a CLI result.

    ``timeout_s`` is the budget of the whole call — round 0, the inline ``Retry-After`` retry and the repair round together
    (AI_FALLBACK_MODEL §4.2): every request is bounded by the budget left (:func:`request_timeout`), the retry and the repair
    round are issued only when :data:`MIN_REMAINING_S` would remain for them, and a slow round 0 that answered off-schema
    finishes the row as ``timeout`` (``timeout after <timeout_s>s: repair round skipped (deadline)``) — the timeout streak,
    not a never-trigger ``schema:`` error. A request that times out inside its bound is ``timeout`` as before.
    """
    now = now or now_iso()
    model = str(cfg.ai_fallback_model or "").strip()
    if call_id is None:
        call_id = ledger.insert_call(
            conn,
            kind=kind,
            model_requested=model,
            flag_tier=0,
            word_count=word_count,
            job_ids=job_ids,
            max_budget_usd=budget.budget_for(cfg, kind),
            reserved_usd=budget.estimate(kind, word_count, FALLBACK),
            now=now,
            provider=FALLBACK,
        )
    started = CLOCK()
    deadline = started + float(timeout_s)  # the whole call's budget: every request below is bounded by what is left of it
    usage_total: dict[str, int | None] = {}
    base_url = str(cfg.ai_fallback_base_url or "").strip().rstrip("/")
    key = api_key(cfg)
    missing = [name for name, present in (("base_url", bool(base_url)), ("model", bool(model)), ("api_key", bool(key))) if not present]
    if missing:
        what: str | None = ", ".join(missing) + " missing"
    elif key and not (key.isascii() and key.isprintable()):
        what = "api_key is not printable ASCII"  # a BOM / full-width character / control character cannot travel in the Authorization header
    else:
        what = None
    if what:
        outcome = _Outcome("spawn_error", f"not_found: fallback not configured ({what})")
        return _finish(conn, cfg, call_id, outcome, kind=kind, started=started, now=now, usage=usage_total, model_used=None, http_status=None, stdout_path=None)

    dialect = resolve_dialect(cfg)
    json_mode = json_mode_for(cfg, dialect)
    url = endpoint_url(base_url)
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": f"word-dance/{__version__}"}
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": compose_system(system_prompt, schema, json_mode)},
        {"role": "user", "content": user_prompt},
    ]
    body = build_body(cfg, kind=kind, schema=schema, messages=messages, dialect=dialect, json_mode=json_mode)
    validator = jsonschema.Draft202012Validator(schema)
    texts: list[str] = []
    http_status: int | None = None
    model_used: str | None = None
    retried = False
    outcome = _Outcome("error", "invalid_json: no response")
    client: httpx.Client | None = None
    try:
        client = _client(timeout_s)  # inside the net: building a client loads the CA bundle, which can fail on a broken install
        for round_no in (0, 1):
            ex, did_retry = _post(client, url, headers, body, deadline=deadline, may_retry=not retried, call_id=call_id)
            retried = retried or did_retry
            http_status = ex.status_code
            if ex.text:
                texts.append(_scrub(ex.text, key))
            if ex.exc is not None:
                status, error = classify_exception(ex.exc, timeout_s)
                outcome = _Outcome(status, _scrub(error, key))
                break
            if ex.status_code != 200:
                status, reason, retry_at = classify_http(ex.status_code, ex.text, ex.headers)
                outcome = _Outcome(status, _scrub(compose_error(reason, retry_at, ex.status_code, ex.text), key))
                break
            data = ex.data
            if not isinstance(data, dict):
                outcome = _Outcome("error", "invalid_json: HTTP 200 with a non-JSON body")
                break
            if not data.get("choices") and data.get("error"):  # a vendor error envelope behind a 200 (a gateway quirk): classify it as the status it stands for
                status, reason, retry_at = classify_http(envelope_status(data["error"], ex.text), ex.text, ex.headers)
                outcome = _Outcome(status, _scrub(compose_error(reason, retry_at, ex.status_code, ex.text), key))
                break
            _add_usage(usage_total, data.get("usage"))
            if data.get("model"):
                model_used = str(data["model"])
            text, error = _choice_text(data)
            if error is not None:
                outcome = _Outcome("overloaded" if error.startswith("network:") else "error", error)  # Zhipu network_error → the network streak / defer path
                break
            obj, reason = extract_json(text)
            if obj is None:
                outcome = _Outcome("error", f"invalid_json: {reason}")
                break
            errors = schema_errors(validator, obj)
            if not errors:
                outcome = _Outcome("success", None, obj)
                break
            if round_no == 0:
                remaining = deadline - CLOCK()
                if remaining < MIN_REMAINING_S:  # the repair round needs a real request's worth of budget: a slow round 0 ends the call as a timeout
                    log.info(
                        "fallback call %s answered off-schema with %ss of its %ss budget left; repair round skipped (%s)",
                        call_id,
                        _seconds(max(remaining, 0.0)),
                        _seconds(timeout_s),
                        errors[0][:160],
                        extra={"event": "fallback_call"},
                    )
                    outcome = _Outcome("timeout", f"timeout after {_seconds(timeout_s)}s: repair round skipped (deadline)")
                    break
                log.info("fallback call %s answered off-schema; one repair round (%s)", call_id, errors[0][:160], extra={"event": "fallback_call"})
                messages = [*messages, {"role": "assistant", "content": text}, {"role": "user", "content": repair_prompt(errors)}]
                body = {**body, "messages": messages}
                continue
            more = f" (+{len(errors) - MAX_SCHEMA_ERRORS} more)" if len(errors) > MAX_SCHEMA_ERRORS else ""
            outcome = _Outcome("error", "schema: " + "; ".join(errors[:MAX_SCHEMA_ERRORS]) + more)
    except sqlite3.Error:
        raise
    except Exception as e:  # noqa: BLE001 — step 10 of the contract: every path finishes the row; a defect here is a per-call `error`, never a row left `running`
        outcome = _Outcome("error", _scrub(f"internal: {e.__class__.__name__}: {str(e)[:200]}", key))
        log.error(
            "fallback call %s crashed inside the adapter: %s\n%s",
            call_id,
            outcome.error,
            _scrub("".join(traceback.format_exception(type(e), e, e.__traceback__)), key),  # scrubbed by hand instead of exc_info: the formatted exception could echo a header
            extra={"event": "fallback_call", "provider": FALLBACK},
        )
    finally:
        if client is not None:
            client.close()
    stdout_path = runner.save_raw(cfg, call_id, ["openai_http", url, model], "\n\n--- repair round ---\n\n".join(texts), "", http_status, now)
    if outcome.ok and not model_used:
        model_used = model
    return _finish(conn, cfg, call_id, outcome, kind=kind, started=started, now=now, usage=usage_total, model_used=model_used, http_status=http_status, stdout_path=stdout_path)


def _finish(
    conn: sqlite3.Connection,
    cfg: Settings,
    call_id: int,
    outcome: _Outcome,
    *,
    kind: str,
    started: float,
    now: str,
    usage: Mapping[str, Any],
    model_used: str | None,
    http_status: int | None,
    stdout_path: str | None,
) -> ClaudeResult:
    """Finish the ledger row (every path) and build the ``ClaudeResult``; the only log line of a call, never with headers."""
    tokens = usage_tokens(usage)
    cost = price_cost_usd(cfg, usage) if any(v for v in tokens.values()) else 0.0
    ledger.finish_call(
        conn,
        call_id,
        status=outcome.status,
        cost_usd=cost,
        duration_ms=int((CLOCK() - started) * 1000),
        input_tokens=tokens["input_tokens"],
        output_tokens=tokens["output_tokens"],
        cache_read_tokens=tokens["cache_read_tokens"],
        model_used=model_used,
        exit_code=http_status,
        error=outcome.error,
        stdout_path=stdout_path,
        now=now,
    )
    log.log(
        logging.INFO if outcome.ok else logging.WARNING,
        "fallback %s call %s → %s%s",
        kind,
        call_id,
        outcome.status,
        "" if outcome.ok else f": {outcome.error}",
        extra={"event": "fallback_call", "cost_usd": cost, "provider": FALLBACK},
    )
    return ClaudeResult(
        ok=outcome.ok,
        status=outcome.status,
        structured=outcome.structured,
        cost_usd=cost,
        call_id=int(call_id),
        model_used=model_used,
        error=outcome.error,
        provider=FALLBACK,
    )


__all__ = [
    "api_key",
    "BALANCE_RE",
    "build_body",
    "classify_exception",
    "classify_http",
    "CLIENT_FACTORY",
    "CLOCK",
    "compose_error",
    "compose_system",
    "CONNECT_TIMEOUT_S",
    "DEFAULT_MAX_TOKENS",
    "endpoint_url",
    "envelope_status",
    "extract_json",
    "FILTER_RE",
    "inline_retry_after",
    "json_mode_for",
    "MIN_REMAINING_S",
    "NOT_FOUND_RE",
    "price_cost_usd",
    "price_table",
    "QUOTA_RE",
    "repair_prompt",
    "request_timeout",
    "resolve_dialect",
    "RETRY_AFTER_MAX_S",
    "retry_at_from_body",
    "run_openai",
    "schema_errors",
    "SLEEP",
    "strict_schema",
    "thinking_fields",
    "UNAUTHORIZED_RE",
    "usage_tokens",
    "VENDOR_FAILURE_REASONS",
]
