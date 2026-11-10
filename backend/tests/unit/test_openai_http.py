"""ai/providers/openai_http.py against tests/fake_openai.py through ``httpx.MockTransport`` (never a socket): the request
shape per dialect, the ledger row before the request and its bookkeeping afterwards, every fake mode's classification,
the ≤ 10 s ``Retry-After`` inline retry, the one repair round, ``timeout_s`` as the budget of the whole call (per-request
bounds from a fake clock, the budget-aware retry and repair round), ``strict_schema`` / ``price_cost_usd`` / ``api_key`` /
``classify_http`` / ``extract_json`` tables, key hygiene (the bearer token pinned by its SHA-256 fingerprint) and the probe
round trip (CLAUDE_INTEGRATION §10)."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import stat
import sys
import time
from collections import deque
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

TESTS_DIR = Path(__file__).resolve().parents[1]
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

import fake_openai  # noqa: E402

from wd import __version__  # noqa: E402
from wd.ai import budget, consolidate, content, ledger, lookup, runner  # noqa: E402
from wd.ai.probe import EXPECTED, PROBE_PROMPT, PROBE_SYSTEM_PROMPT  # noqa: E402
from wd.ai.providers import CLAUDE, FALLBACK, PROVIDERS, openai_http  # noqa: E402
from wd.clock import parse_iso  # noqa: E402

NOW = "2026-10-14T00:00:00Z"
KEY = "sk-fallback-secret-9f8e7d6c"
BASE = "https://mock.example/v4"
MODEL = "glm-4.7-flash"
STRINGS = ["went", "ice cream", "GDP"]


def sha(token: str) -> str:
    """The fingerprint ``fake_openai`` records for a bearer token (``auth_sha256``) — the tests never compare the token itself."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
LOOKUP_SYSTEM = runner.load_prompt("lookup_system")
LOOKUP_PROMPT = lookup.build_user_prompt(STRINGS)
WORDS = [
    {"word": "abandon", "dictionary_hint": "vt. 放弃, 抛弃", "pos_hint": "v:96", "stages": ["高中", "四级"]},
    {"word": "GDP", "dictionary_hint": "国内生产总值", "pos_hint": "", "stages": [], "kind": "abbreviation"},
]
#: kind → (system prompt, user prompt, schema name, item count)
PROMPTS = {
    "content": (runner.load_prompt("content_system"), content.build_user_prompt(WORDS), "content_v1", 2),
    "lookup": (LOOKUP_SYSTEM, LOOKUP_PROMPT, "lookup_v1", 3),
    "consolidate": (
        runner.load_prompt("consolidate_system"),
        consolidate.build_user_prompt(["go", "abandon"], [{"id": 1001, "input": "went", "headword": "go"}, {"id": 1002, "input": "abandon", "headword": "abandon"}]),
        "consolidate_v1",
        2,
    ),
    "svg": (runner.load_prompt("svg_system"), 'Draw an illustration for the word "apple".', "svg_v1", 1),
    "probe": (PROBE_SYSTEM_PROMPT, PROBE_PROMPT, "probe_v1", 1),
}


# ------------------------------------------------------------------------------------------- fixtures
@pytest.fixture
def cfg(settings):
    return replace(settings, ai_fallback_kind="openai_http", ai_fallback_base_url=BASE, ai_fallback_model=MODEL, ai_fallback_api_key=KEY, ai_provider="auto")


@pytest.fixture(autouse=True)
def _no_sockets_no_sleep(monkeypatch):
    """A forgotten CLIENT_FACTORY must fail loudly instead of opening a socket; a sleep must be asked for explicitly.
    ``pytest.fail`` raises a BaseException, so the adapter's own safety net (``except Exception`` → a per-call ``error``)
    cannot swallow either."""

    def refuse(timeout_s):
        pytest.fail("CLIENT_FACTORY was not installed by the test")

    def no_sleep(seconds):
        pytest.fail(f"unexpected sleep({seconds})")

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", refuse)
    monkeypatch.setattr(openai_http, "SLEEP", no_sleep)


@pytest.fixture
def install(monkeypatch):
    """``install(mode, modes=None) -> (calls, responses, timeouts, transport)``: CLIENT_FACTORY → a fake_openai transport;
    every request body (with the per-request ``timeout`` the adapter asked for), every response JSON and every client-level
    timeout are recorded."""

    def _install(mode: str = "ok", *, modes=None):
        calls: list[dict] = []
        responses: list[dict] = []
        timeouts: list[float] = []
        inner = fake_openai.transport(mode, calls=calls, modes=modes)

        def handler(request: httpx.Request) -> httpx.Response:
            resp = inner.handler(request)
            try:
                responses.append(json.loads(resp.content.decode("utf-8")))
            except ValueError:
                responses.append({})
            return resp

        def factory(timeout_s: float) -> httpx.Client:
            timeouts.append(timeout_s)
            return httpx.Client(transport=httpx.MockTransport(handler), timeout=timeout_s)

        monkeypatch.setattr(openai_http, "CLIENT_FACTORY", factory)
        return calls, responses, timeouts, inner

    return _install


class FakeClock:
    """A monotonic clock the tests move by hand: installed as ``openai_http.CLOCK``; ``sleep`` (installed as ``SLEEP``) and the
    slow transport of the ``slow`` fixture advance it, so a 90-second round costs no wall time."""

    def __init__(self, start: float = 1000.0):
        self.t = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(float(seconds))
        self.t += float(seconds)


@pytest.fixture
def slow(install, monkeypatch):
    """``slow(mode, durations=(), modes=None) -> (clock, calls)``: a fake_openai transport whose n-th request takes ``durations[n]``
    seconds of a :class:`FakeClock` (0 once the list is exhausted); the clock is installed as CLOCK and its ``sleep`` as SLEEP."""

    def _slow(mode: str = "ok", *, durations=(), modes=None):
        clock = FakeClock()
        monkeypatch.setattr(openai_http, "CLOCK", clock)
        monkeypatch.setattr(openai_http, "SLEEP", clock.sleep)
        calls, _, _, inner = install(mode, modes=modes)
        pending = deque(float(d) for d in durations)

        def handler(request: httpx.Request) -> httpx.Response:
            clock.t += pending.popleft() if pending else 0.0  # the request takes this long (the fake records the bound it was given)
            return inner.handler(request)

        monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(handler), timeout=t))
        return clock, calls

    return _slow


def run(conn, cfg, *, kind="lookup", timeout_s=180, job_ids=(1, 2), call_id=None, system=None, prompt=None, schema=None, word_count=None):
    sys_default, user_default, schema_default, n = PROMPTS[kind]
    return openai_http.run_openai(
        conn,
        kind=kind,
        system_prompt=sys_default if system is None else system,
        user_prompt=user_default if prompt is None else prompt,
        schema=runner.load_schema(schema_default if schema is None else schema),
        timeout_s=timeout_s,
        word_count=n if word_count is None else word_count,
        job_ids=list(job_ids),
        cfg=cfg,
        now=NOW,
        call_id=call_id,
    )


# ------------------------------------------------------------------------------------------- constants
def test_provider_constants():
    assert CLAUDE == "claude" and FALLBACK == "fallback" and PROVIDERS == ("claude", "fallback")
    assert PROVIDERS == ledger.PROVIDERS == budget.PROVIDERS
    assert openai_http.DEFAULT_MAX_TOKENS == {"content": 8192, "lookup": 8192, "consolidate": 12288, "svg": 4096, "probe": 512}
    assert openai_http.DEFAULT_MAX_TOKENS["lookup"] >= 2 * 3700  # a 20-string lookup answer is ≈ 3,700 tokens: 4096 left no headroom (review)


# ------------------------------------------------------------------------------------- request shape
def test_request_shape_generic_json_object(conn, cfg, install):
    calls, responses, timeouts, _ = install("ok")
    result = run(conn, cfg)
    assert result.ok and result.status == "success" and result.provider == "fallback" and result.error is None
    assert [it["input"] for it in result.structured["items"]] == STRINGS
    assert result.model_used == MODEL and result.cost_usd == 0.0 and timeouts == [180.0]
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == BASE + "/chat/completions"
    assert call["auth_scheme"] == "Bearer" and call["auth_sha256"] == sha(KEY) and "authorization" not in call["headers"]
    assert call["headers"]["user-agent"] == f"word-dance/{__version__}" and call["headers"]["content-type"] == "application/json"
    assert call["timeout"]["connect"] == 20.0 and 179.0 < call["timeout"]["read"] <= 180.0  # bounded by what is left of the 180 s budget
    body = call["json"]
    assert body["model"] == MODEL and body["stream"] is False and body["max_tokens"] == 8192 and "temperature" not in body
    assert body["response_format"] == {"type": "json_object"}
    assert "thinking" not in body and "enable_thinking" not in body  # mock.example → generic dialect
    system, user = body["messages"]
    assert system["role"] == "system" and user == {"role": "user", "content": LOOKUP_PROMPT}
    schema = runner.load_schema("lookup_v1")
    assert system["content"] == LOOKUP_SYSTEM + openai_http.JSON_OBJECT_SUFFIX + runner.schema_arg(schema)
    assert "JSON" in system["content"] and runner.schema_arg(schema) in system["content"]
    assert set(body) == {"model", "messages", "stream", "max_tokens", "response_format"}


@pytest.mark.parametrize(
    "dialect,thinking,rf_type,extra",
    [
        ("zhipu", "off", "json_object", {"thinking": {"type": "disabled"}}),
        ("zhipu", "on", "json_object", {"thinking": {"type": "enabled"}}),
        ("zhipu", "default", "json_object", {}),
        ("deepseek", "off", "json_object", {"thinking": {"type": "disabled"}}),
        ("bailian", "off", "json_schema", {"enable_thinking": False}),
        ("bailian", "on", "json_schema", {"enable_thinking": True}),
        ("bailian", "default", "json_schema", {}),
        ("generic", "off", "json_object", {}),
        ("generic", "on", "json_object", {}),
    ],
)
def test_request_shape_per_dialect(conn, cfg, install, dialect, thinking, rf_type, extra):
    calls, _, _, _ = install("ok")
    result = run(conn, replace(cfg, ai_fallback_dialect=dialect, ai_fallback_thinking=thinking))
    assert result.ok
    body = calls[0]["json"]
    assert body["response_format"]["type"] == rf_type
    for k in ("thinking", "enable_thinking"):
        assert body.get(k) == extra.get(k)
    system = body["messages"][0]["content"]
    schema = runner.load_schema("lookup_v1")
    if rf_type == "json_schema":
        js = body["response_format"]["json_schema"]
        assert js["name"] == "lookup_v1" and js["strict"] is True
        assert js["schema"] == openai_http.strict_schema(schema) and js["schema"]["additionalProperties"] is False
        assert system == LOOKUP_SYSTEM + openai_http.JSON_SCHEMA_SUFFIX and "JSON" in system and runner.schema_arg(schema) not in system
    else:
        assert system.endswith(runner.schema_arg(schema))


def test_explicit_json_mode_overrides_the_dialect_default(conn, cfg, install):
    calls, _, _, _ = install("ok")
    assert run(conn, replace(cfg, ai_fallback_dialect="zhipu", ai_fallback_json_mode="json_schema")).ok
    assert run(conn, replace(cfg, ai_fallback_dialect="bailian", ai_fallback_json_mode="json_object")).ok
    assert [c["json"]["response_format"]["type"] for c in calls] == ["json_schema", "json_object"]


@pytest.mark.parametrize("kind", list(PROMPTS))
def test_max_tokens_table_and_override_for_every_kind(conn, cfg, install, kind):
    calls, _, _, _ = install("ok")
    result = run(conn, cfg, kind=kind)
    assert result.ok, result.error
    assert calls[-1]["json"]["max_tokens"] == openai_http.DEFAULT_MAX_TOKENS[kind]
    assert calls[-1]["json"]["response_format"] == {"type": "json_object"}
    if kind in ("content", "lookup", "consolidate"):
        assert len(result.structured["items"]) == PROMPTS[kind][3]
    assert run(conn, replace(cfg, ai_fallback_max_output_tokens=2048), kind=kind).ok
    assert calls[-1]["json"]["max_tokens"] == 2048
    row = ledger.get_call(conn, result.call_id)
    assert row["kind"] == kind and row["max_budget_usd"] == budget.budget_for(cfg, kind) and row["provider"] == "fallback"


def test_base_url_variants(conn, cfg, install):
    calls, _, _, _ = install("ok")
    assert run(conn, replace(cfg, ai_fallback_base_url=BASE + "/chat/completions")).ok
    assert run(conn, replace(cfg, ai_fallback_base_url=BASE + "/")).ok
    assert [c["url"] for c in calls] == [BASE + "/chat/completions"] * 2
    assert openai_http.endpoint_url("https://open.bigmodel.cn/api/paas/v4") == "https://open.bigmodel.cn/api/paas/v4/chat/completions"


def test_resolve_dialect_and_json_mode(cfg):
    by_host = {
        "https://open.bigmodel.cn/api/paas/v4": "zhipu",
        "https://api.z.ai/api/paas/v4": "zhipu",
        "https://dashscope.aliyuncs.com/compatible-mode/v1": "bailian",
        "https://ws-123.cn-beijing.maas.aliyuncs.com/v1": "bailian",
        "https://dashscope-intl.example.com/v1": "bailian",
        "https://api.deepseek.com": "deepseek",
        "https://mock.example/v4": "generic",
        "https://xyz.ai/v1": "generic",
        "": "generic",
    }
    for url, dialect in by_host.items():
        assert openai_http.resolve_dialect(replace(cfg, ai_fallback_base_url=url)) == dialect, url
    assert openai_http.resolve_dialect(replace(cfg, ai_fallback_base_url="https://open.bigmodel.cn/api/paas/v4", ai_fallback_dialect="generic")) == "generic"
    assert [openai_http.json_mode_for(cfg, d) for d in ("zhipu", "deepseek", "generic", "bailian")] == ["json_object", "json_object", "json_object", "json_schema"]
    assert openai_http.json_mode_for(replace(cfg, ai_fallback_json_mode="json_object"), "bailian") == "json_object"
    assert openai_http.json_mode_for(replace(cfg, ai_fallback_json_mode="json_schema"), "zhipu") == "json_schema"


def test_thinking_fields_table():
    tf = openai_http.thinking_fields
    assert tf("zhipu", "off") == tf("deepseek", "off") == {"thinking": {"type": "disabled"}}
    assert tf("zhipu", "on") == tf("deepseek", "on") == {"thinking": {"type": "enabled"}}
    assert tf("bailian", "off") == {"enable_thinking": False} and tf("bailian", "on") == {"enable_thinking": True}
    assert tf("generic", "off") == tf("generic", "on") == {} and all(tf(d, "default") == {} for d in ("zhipu", "bailian", "deepseek", "generic"))


def test_compose_system_carries_the_schema_and_the_word_json():
    schema = runner.load_schema("probe_v1")
    obj = openai_http.compose_system("SYS", schema, "json_object")
    assert obj.startswith("SYS\n\nOutput format: respond with ONE JSON object only") and obj.endswith(runner.schema_arg(schema)) and "JSON" in obj
    js = openai_http.compose_system("SYS", schema, "json_schema")
    assert js == "SYS\n\nRespond with one JSON object that conforms to the provided JSON schema."
    assert openai_http.compose_system("", schema, "json_object").startswith("\n\nOutput format")


# ---------------------------------------------------------------------------------------------- ledger
def test_ledger_row_exists_before_the_request_and_is_finished_after(conn, cfg, install, monkeypatch):
    calls, responses, _, inner = install("ok")
    seen: list[dict] = []

    def handler(request):
        row = conn.execute("SELECT status, provider, reserved_usd, model_requested, max_budget_usd, flag_tier, job_ids_json, finished_at, word_count FROM ai_calls ORDER BY id DESC LIMIT 1").fetchone()
        seen.append({k: row[k] for k in row.keys()})
        return inner.handler(request)

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(handler), timeout=t))
    result = run(conn, cfg)
    assert result.ok
    assert seen == [{"status": "running", "provider": "fallback", "reserved_usd": 0.0, "model_requested": MODEL, "max_budget_usd": 0.15, "flag_tier": 0, "job_ids_json": "[1, 2]", "finished_at": None, "word_count": 3}]
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "success" and row["provider"] == "fallback" and row["exit_code"] == 200 and row["model_used"] == MODEL
    assert row["input_tokens"] > 0 and row["output_tokens"] > 0 and row["cache_read_tokens"] == 0 and row["cache_create_tokens"] is None
    assert row["cost_usd"] == 0.0 and row["duration_ms"] is not None and row["started_at"] == NOW and row["finished_at"] == NOW and row["error"] is None
    raw = cfg.data_dir / row["stdout_path"]
    assert raw.is_file() and raw.parent.name == "2026-10-14" and stat.S_IMODE(raw.stat().st_mode) == 0o600
    saved = json.loads(raw.read_text(encoding="utf-8"))
    assert saved["argv"] == ["openai_http", BASE + "/chat/completions", MODEL] and saved["exit_code"] == 200 and saved["stderr"] == ""
    assert json.loads(saved["stdout"])["choices"][0]["message"]["content"] == json.dumps(result.structured, ensure_ascii=False)
    assert KEY not in raw.read_text(encoding="utf-8")
    assert ledger.call_dto(row)["provider"] == "fallback"


def test_a_reserved_call_id_is_reused(conn, cfg, install):
    calls, _, _, _ = install("ok")
    reservation = budget.reserve(conn, kind="lookup", word_count=3, priority=20, now=NOW, cfg=cfg, flag_tier=0, job_ids=[7], provider="fallback")
    assert reservation.ok and reservation.reserved_usd == 0.0
    result = run(conn, cfg, call_id=reservation.call_id)
    assert result.ok and result.call_id == reservation.call_id
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
    row = ledger.get_call(conn, reservation.call_id)
    assert row["status"] == "success" and row["provider"] == "fallback" and json.loads(row["job_ids_json"]) == [7] and row["model_requested"] == MODEL
    assert budget.calls_last_hour(conn, NOW, "fallback") == 1 and budget.calls_last_hour(conn, NOW, "claude") == 0


# ------------------------------------------------------------------------------------------------ modes
@pytest.mark.parametrize(
    "mode,status,prefix,ok,http",
    [
        ("ok", "success", None, True, 200),
        ("fenced_json", "success", None, True, 200),
        ("partial", "success", None, True, 200),
        ("repairable", "success", None, True, 200),
        ("invalid_json", "error", "invalid_json:", False, 200),
        ("schema_mismatch", "error", "schema:", False, 200),
        ("truncated", "error", "truncated: finish_reason=length", False, 200),
        ("empty_content", "error", "invalid_json: empty content", False, 200),
        ("sensitive", "error", "content_filter: finish_reason=sensitive", False, 200),
        ("network_error", "overloaded", "network: finish_reason=network_error", False, 200),
        ("401", "auth", "unauthorized HTTP 401:", False, 401),
        ("zh_401", "auth", "unauthorized HTTP 401:", False, 401),
        ("402", "auth", "balance: HTTP 402:", False, 402),
        ("403", "auth", "forbidden HTTP 403:", False, 403),
        ("404", "spawn_error", "not_found: HTTP 404:", False, 404),
        ("404_model", "spawn_error", "not_found: HTTP 400:", False, 400),
        ("429_long", "overloaded", "rate_limit HTTP 429:", False, 429),
        ("1308", "overloaded", "quota: retry_at=2026-10-14T02:00:00Z HTTP 429:", False, 429),
        ("503", "overloaded", "http_503 HTTP 503:", False, 503),
        ("content_filter", "error", "content_filter: HTTP 400:", False, 400),
        ("network", "overloaded", "network: ConnectError:", False, None),
        ("timeout", "timeout", "timeout after 180s: ReadTimeout", False, None),
    ],
)
def test_every_mode_is_classified(conn, cfg, install, mode, status, prefix, ok, http):
    calls, _, _, _ = install(mode)
    result = run(conn, cfg)
    assert result.status == status and result.ok is ok and result.provider == "fallback"
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == status and row["provider"] == "fallback" and row["exit_code"] == http and row["finished_at"] == NOW
    if prefix is None:
        assert result.error is None and row["error"] is None and result.structured is not None
    else:
        assert result.error.startswith(prefix), result.error
        assert row["error"] == result.error
    expected_calls = 2 if mode in ("repairable", "schema_mismatch") else 1
    assert len(calls) == expected_calls
    if mode == "partial":
        assert [it["input"] for it in result.structured["items"]] == STRINGS[:-1]  # the handler decides `partial`
    if mode in ("fenced_json", "ok", "repairable"):
        assert [it["input"] for it in result.structured["items"]] == STRINGS
    if mode in ("network", "timeout"):
        assert row["input_tokens"] is None and row["model_used"] is None and row["stdout_path"]
    if mode == "1308":
        assert "使用上限" in result.error and len(result.error) < 500
    if mode == "zh_401":
        assert "令牌已过期" in result.error
    if mode == "truncated":
        assert row["output_tokens"] > 0 and row["model_used"] == MODEL  # tokens of a failed call are still recorded
    if mode in ("sensitive", "network_error"):  # Zhipu's own finish reasons behind a 200: the exact error text is the failover contract
        assert result.error == prefix and row["model_used"] == MODEL and row["input_tokens"] > 0 and row["stdout_path"]


def test_zhipu_finish_reasons_sensitive_and_network_error():
    """Zhipu's chat-completions ``finish_reason`` vocabulary beyond OpenAI's (review): ``sensitive`` (安全审核拦截) is a content
    filter — the ``content_filter:`` prefix, not ``invalid_json: empty content`` and a pointless bisection — and ``network_error``
    (模型推理异常 behind a 200) is a vendor failure that must reach the network streak / defer path as ``overloaded``."""
    ct = openai_http._choice_text
    assert ct({"choices": [{"finish_reason": "sensitive", "message": {"role": "assistant", "content": ""}}]}) == (None, "content_filter: finish_reason=sensitive")
    assert ct({"choices": [{"finish_reason": "network_error", "message": {"role": "assistant", "content": ""}}]}) == (None, "network: finish_reason=network_error")
    assert ct({"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}]}) == ("{}", None)
    assert openai_http.FILTER_REASONS == ("content_filter", "refusal", "sensitive") and openai_http.VENDOR_FAILURE_REASONS == ("network_error",)


def test_unknown_statuses_and_non_json_bodies(conn, cfg, monkeypatch):
    answers = iter([httpx.Response(418, text="I'm a teapot"), httpx.Response(200, text="<html>gateway</html>"), httpx.Response(200, json={"choices": []})])
    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(lambda r: next(answers)), timeout=t))
    r1, r2, r3 = run(conn, cfg), run(conn, cfg), run(conn, cfg)
    assert (r1.status, r1.error) == ("error", "http_418 HTTP 418: I'm a teapot")
    assert (r2.status, r2.error) == ("error", "invalid_json: HTTP 200 with a non-JSON body")
    assert (r3.status, r3.error) == ("error", "invalid_json: no choices in the response")
    assert [ledger.get_call(conn, r.call_id)["exit_code"] for r in (r1, r2, r3)] == [418, 200, 200]


def test_an_error_envelope_behind_http_200_is_classified_like_its_status(conn, cfg, monkeypatch):
    """A gateway that wraps a vendor error in a 200 must still produce the prefixes `failover` reads (§10.3, defence in depth)."""
    bodies = [
        {"error": {"code": "1113", "message": "您的账户已欠费，请充值后重试"}},
        {"error": {"code": "1002", "message": "令牌已过期或验证不正确"}},
        {"error": {"code": "1308", "message": "已达到 1000 次 的使用上限", "next_flush_time": "2026-10-14 10:00:00"}},
        {"error": {"status": 503, "message": "upstream overloaded"}},
        {"error": {"code": "1211", "message": "模型不存在，请检查模型代码。"}},
        {"error": "Insufficient Balance"},
        {"error": {"message": "Invalid value for max_tokens"}},
        {"error": {"code": "1301", "message": "系统检测到输入或生成内容可能包含不安全或敏感内容"}},
    ]
    answers = iter(httpx.Response(200, json=b) for b in bodies)
    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(lambda r: next(answers)), timeout=t))
    results = [run(conn, cfg) for _ in bodies]
    assert [(r.status, r.error.split(" HTTP ")[0]) for r in results] == [
        ("auth", "balance:"),
        ("auth", "unauthorized"),
        ("overloaded", "quota: retry_at=2026-10-14T02:00:00Z"),
        ("overloaded", "http_503"),
        ("spawn_error", "not_found:"),
        ("auth", "balance:"),
        ("error", "http_400"),
        ("error", "content_filter:"),
    ]
    assert all(" HTTP 200: " in r.error and not r.ok and r.structured is None for r in results)  # the wire status stays visible
    rows = [ledger.get_call(conn, r.call_id) for r in results]
    assert all(row["exit_code"] == 200 and row["finished_at"] == NOW and row["error"] == r.error for row, r in zip(rows, results))
    assert "欠费" in results[0].error
    # the synthesised status
    es = openai_http.envelope_status
    assert es({"status": 429}, "") == 429 and es({"http_status": "402"}, "") == 402 and es({"status_code": 500}, "") == 500 and es({"code": 503}, "") == 503
    assert es({"code": "1113"}, '{"error":{"code":"1113"}}') == 400 and es({"code": "1002"}, '{"error":{"code":"1002"}}') == 401
    assert es({"code": "invalid_api_key"}, '{"error":{"code":"invalid_api_key"}}') == 401 and es({}, "quota exceeded") == 429 and es("x", "") == 400 and es(None, "") == 400
    assert es({"code": 200}, "") == 400 and es({"status": True}, "") == 400


def test_content_parts_refusal_and_deepseek_cache_field(conn, cfg, monkeypatch):
    def envelope(message, usage, finish="stop"):
        return {"model": "vendor-model-x", "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": usage}

    answers = iter(
        [
            httpx.Response(200, json=envelope({"role": "assistant", "content": [{"type": "text", "text": json.dumps(EXPECTED)}]}, {"prompt_tokens": 120, "completion_tokens": 30, "prompt_cache_hit_tokens": 100})),
            httpx.Response(200, json=envelope({"role": "assistant", "content": None, "refusal": "I cannot help with that"}, {"prompt_tokens": 5, "completion_tokens": 1})),
            httpx.Response(200, json=envelope({"role": "assistant", "content": "{}"}, {"prompt_tokens": 5, "completion_tokens": 1, "prompt_tokens_details": {"cached_tokens": 4}}, finish="content_filter")),
        ]
    )
    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(lambda r: next(answers)), timeout=t))
    ok = run(conn, cfg, kind="probe")
    assert ok.ok and ok.structured == EXPECTED and ok.model_used == "vendor-model-x"
    row = ledger.get_call(conn, ok.call_id)
    assert (row["input_tokens"], row["output_tokens"], row["cache_read_tokens"], row["model_used"]) == (120, 30, 100, "vendor-model-x")
    refusal = run(conn, cfg, kind="probe")
    assert refusal.status == "error" and refusal.error == "content_filter: I cannot help with that"
    filtered = run(conn, cfg, kind="probe")
    assert filtered.status == "error" and filtered.error == "content_filter: finish_reason=content_filter"
    assert ledger.get_call(conn, filtered.call_id)["cache_read_tokens"] == 4


# ------------------------------------------------------------------------------------------ retry-after
def test_retry_after_within_ten_seconds_is_retried_once_inline(conn, cfg, install, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(openai_http, "SLEEP", slept.append)
    calls, _, _, _ = install("ok", modes=["429", "ok"])
    result = run(conn, cfg)
    assert result.ok and len(calls) == 2 and slept == [2.0]
    assert calls[0]["json"] == calls[1]["json"]  # the very same request again
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "success" and row["exit_code"] == 200
    # a persistent 429: one retry, then `overloaded` (the job backs off / failover counts the streak)
    slept.clear()
    calls, _, _, _ = install("429")
    result = run(conn, cfg)
    assert result.status == "overloaded" and result.error.startswith("rate_limit HTTP 429:") and len(calls) == 2 and slept == [2.0]
    assert ledger.get_call(conn, result.call_id)["exit_code"] == 429


def test_a_plain_429_without_retry_after_is_retried_on_the_backoff(conn, cfg, install, monkeypatch):
    """Zhipu 1305 「访问量过大」 carries no Retry-After and clears within seconds: 2 / 4 / 8 s inside the call's budget, the same
    request each time; a persistent one is `overloaded` after the third retry (the job backs off, the streak counts)."""
    slept: list[float] = []
    monkeypatch.setattr(openai_http, "SLEEP", slept.append)
    calls, _, _, _ = install("ok", modes=["1305", "1305", "ok"])
    result = run(conn, cfg)
    assert result.ok and len(calls) == 3 and slept == [2.0, 4.0]
    assert calls[0]["json"] == calls[1]["json"] == calls[2]["json"]
    assert conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1 and ledger.get_call(conn, result.call_id)["status"] == "success"
    slept.clear()
    calls, _, _, _ = install("1305")
    result = run(conn, cfg)
    assert result.status == "overloaded" and "1305" in result.error and len(calls) == 4 and slept == [2.0, 4.0, 8.0]
    assert ledger.get_call(conn, result.call_id)["exit_code"] == 429
    # the header wins when there is one: Retry-After: 2 → one retry, no backoff schedule (see the test above); Retry-After: 120 → none (below)
    slept.clear()
    calls, _, _, _ = install("ok", modes=["1305", "429_long", "ok"])  # a long Retry-After on a retry ends the schedule: the job defers for it
    result = run(conn, cfg)
    assert result.status == "overloaded" and "1305" in result.error and len(calls) == 2 and slept == [2.0]


def test_long_retry_after_is_not_slept_through(conn, cfg, install):
    calls, _, _, _ = install("429_long")  # SLEEP would raise (autouse fixture)
    result = run(conn, cfg)
    assert result.status == "overloaded" and len(calls) == 1 and "1305" in result.error
    assert openai_http._retry_after_seconds("120") == 120.0 and openai_http._retry_after_seconds("2") == 2.0
    assert openai_http._retry_after_seconds(None) is None and openai_http._retry_after_seconds("soon") is None
    assert openai_http._retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0  # a past HTTP-date → no wait


def test_hard_429_bodies_are_not_retried_inline(conn, cfg, install, monkeypatch):
    """A 429 whose body is a windowed quota (1308) or an account in arrears (1113) cannot clear within seconds: no sleep, one
    request, and the classification the failover reads (SLEEP would raise — autouse fixture)."""
    calls, _, _, _ = install("ok", modes=["1308", "ok"])  # the fake's 1308 carries Retry-After: 1
    result = run(conn, cfg)
    assert result.status == "overloaded" and result.error.startswith("quota: retry_at=2026-10-14T02:00:00Z HTTP 429:") and len(calls) == 1
    assert ledger.get_call(conn, result.call_id)["exit_code"] == 429
    requests: list[httpx.Request] = []

    def arrears(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {"code": "1113", "message": "您的账户已欠费，请充值后重试"}}, headers={"Retry-After": "2"})

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(arrears), timeout=t))
    result = run(conn, cfg)
    assert result.status == "auth" and result.error.startswith("balance: HTTP 429:") and len(requests) == 1
    # the decision itself
    ex = openai_http._Exchange
    assert openai_http.inline_retry_after(ex(status_code=429, text='{"error":{"code":"1302"}}', headers={"retry-after": "2"})) == 2.0
    assert openai_http.inline_retry_after(ex(status_code=429, text='{"error":{"code":"1302"}}', headers={"retry-after": "11"})) is None
    assert openai_http.inline_retry_after(ex(status_code=429, text='{"error":{"code":"1302"}}', headers={})) is None
    assert openai_http.inline_retry_after(ex(status_code=429, text='{"error":{"code":"1113"}}', headers={"retry-after": "1"})) is None
    assert openai_http.inline_retry_after(ex(status_code=429, text='{"error":{"code":"1308"}}', headers={"retry-after": "1"})) is None
    assert openai_http.inline_retry_after(ex(status_code=429, text='{"next_flush_time":"2026-10-14 10:00:00"}', headers={"retry-after": "1"})) is None
    assert openai_http.inline_retry_after(ex(status_code=429, text="quota exceeded", headers={"retry-after": "1"})) is None
    assert openai_http.inline_retry_after(ex(status_code=503, text="", headers={"retry-after": "1"})) is None


# -------------------------------------------------------------------------------------------- deadline
def test_timeout_s_is_the_budget_of_the_whole_call_not_of_each_request(conn, cfg, slow):
    """(review, major) The client used to carry ``timeout_s`` per request, so round 0 + the repair round could run ~2× the kind's
    timeout and push a claimed group past the 15-minute stale sweep. Now ``deadline = start + timeout_s`` bounds every request
    (connect stays 20 s but never more than the remaining) and the repair round is issued only with ≥ MIN_REMAINING_S left."""
    assert openai_http.MIN_REMAINING_S == 15.0
    # a 60 s first round of a 100 s budget answers off-schema: the repair round gets the 40 s left, connect stays 20 s
    clock, calls = slow("repairable", durations=[60, 10])
    result = run(conn, cfg, timeout_s=100)
    assert result.ok and len(calls) == 2 and clock.slept == []
    assert calls[0]["timeout"] == {"connect": 20.0, "read": 100.0, "write": 100.0, "pool": 100.0}
    assert calls[1]["timeout"] == {"connect": 20.0, "read": 40.0, "write": 40.0, "pool": 40.0}
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "success" and row["duration_ms"] == 70_000
    # a 90 s first round: 10 s left < MIN_REMAINING_S → no second request; the row finishes as `timeout` (the timeout streak, not a never-trigger `schema:`)
    clock, calls = slow("schema_mismatch", durations=[90])
    result = run(conn, cfg, timeout_s=100)
    assert result.status == "timeout" and not result.ok and result.structured is None and result.provider == "fallback"
    assert result.error == "timeout after 100s: repair round skipped (deadline)"
    assert len(calls) == 1 and clock.slept == [] and clock() == 1090.0  # the call ended 10 s inside its budget
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "timeout" and row["error"] == result.error and row["finished_at"] == NOW and row["duration_ms"] == 90_000
    assert row["exit_code"] == 200 and row["input_tokens"] > 0 and row["model_used"] == MODEL and row["stdout_path"]  # round 0's bookkeeping is kept
    assert conn.execute("SELECT COUNT(*) FROM ai_calls WHERE status='running'").fetchone()[0] == 0
    # the boundary: exactly MIN_REMAINING_S left → the repair round runs, bounded by those 15 s (connect capped at the remaining, not 20)
    clock, calls = slow("repairable", durations=[85, 1])
    result = run(conn, cfg, timeout_s=100)
    assert result.ok and len(calls) == 2 and calls[1]["timeout"] == {"connect": 15.0, "read": 15.0, "write": 15.0, "pool": 15.0}
    assert ledger.get_call(conn, result.call_id)["duration_ms"] == 86_000
    # the repair request itself times out inside its reduced bound: `timeout`, with the whole call's budget in the message, row finished
    clock, calls = slow("ok", modes=["schema_mismatch", "timeout"], durations=[60, 40])
    result = run(conn, cfg, timeout_s=100)
    assert result.status == "timeout" and result.error == "timeout after 100s: ReadTimeout" and len(calls) == 2
    assert calls[1]["timeout"]["read"] == 40.0 and clock() == 1100.0
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "timeout" and row["finished_at"] == NOW and row["exit_code"] is None and row["duration_ms"] == 100_000
    assert conn.execute("SELECT COUNT(*) FROM ai_calls WHERE status='running'").fetchone()[0] == 0
    # a budget below MIN_REMAINING_S never gets a repair round, a valid first answer never needs one
    clock, calls = slow("schema_mismatch", durations=[1])
    assert run(conn, cfg, timeout_s=10).error == "timeout after 10s: repair round skipped (deadline)" and len(calls) == 1
    clock, calls = slow("ok", durations=[99])
    assert run(conn, cfg, timeout_s=100).ok and len(calls) == 1


def test_retry_after_is_slept_through_only_when_the_budget_still_has_room(conn, cfg, slow):
    """The inline retry needs ``wait + MIN_REMAINING_S <= remaining``; otherwise the 429 keeps its classification (no sleep, no request)."""
    clock, calls = slow("ok", modes=["429", "ok"], durations=[84])  # 16 s left < 2 + 15
    result = run(conn, cfg, timeout_s=100)
    assert result.status == "overloaded" and result.error.startswith("rate_limit HTTP 429:") and len(calls) == 1 and clock.slept == []
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "overloaded" and row["exit_code"] == 429 and row["finished_at"] == NOW and row["duration_ms"] == 84_000
    clock, calls = slow("ok", modes=["429", "ok"], durations=[83, 1])  # 17 s left = 2 + 15: slept through, the retry bounded by the 15 s then left
    result = run(conn, cfg, timeout_s=100)
    assert result.ok and len(calls) == 2 and clock.slept == [2.0]
    assert calls[1]["timeout"] == {"connect": 15.0, "read": 15.0, "write": 15.0, "pool": 15.0} and calls[0]["json"] == calls[1]["json"]
    assert ledger.get_call(conn, result.call_id)["duration_ms"] == 86_000


def test_a_slow_first_round_ends_the_call_inside_its_budget_in_real_time(conn, cfg, install, monkeypatch):
    """The default clock end to end: a transport that really takes 0.25 s per request and always answers off-schema. With a 1 s
    budget the old adapter made two requests (≈ 0.5 s, `schema:`); now the repair round is skipped and the call returns well
    inside the budget with its row finished."""
    calls, _, _, inner = install("schema_mismatch")

    def slow_handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.25)
        return inner.handler(request)

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(slow_handler), timeout=t))
    t0 = time.perf_counter()
    result = run(conn, cfg, timeout_s=1)
    elapsed = time.perf_counter() - t0
    assert result.status == "timeout" and result.error == "timeout after 1s: repair round skipped (deadline)" and len(calls) == 1
    assert elapsed < 1.0, elapsed
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "timeout" and row["finished_at"] == NOW and 240 <= row["duration_ms"] < 1000
    bound = calls[0]["timeout"]
    assert 0.9 < bound["read"] <= 1.0 and bound["connect"] == bound["read"] == bound["write"] == bound["pool"]  # connect ≤ the remaining budget


def test_request_timeout_table():
    rt = openai_http.request_timeout
    assert rt(180) == httpx.Timeout(180.0, connect=20.0) and rt(40.0) == httpx.Timeout(40.0, connect=20.0)
    assert rt(12.5) == httpx.Timeout(12.5, connect=12.5) and rt(0) == httpx.Timeout(0.0, connect=0.0) and rt(-3) == httpx.Timeout(0.0, connect=0.0)
    assert rt(20.0).as_dict() == {"connect": 20.0, "read": 20.0, "write": 20.0, "pool": 20.0}


# ---------------------------------------------------------------------------------------- repair round
def test_repair_round_succeeds_on_repairable_and_sums_the_tokens(conn, cfg, install):
    calls, responses, _, _ = install("repairable")
    result = run(conn, cfg)
    assert result.ok and [it["input"] for it in result.structured["items"]] == STRINGS and len(calls) == 2
    first, second = calls[0]["json"], calls[1]["json"]
    assert len(first["messages"]) == 2 and len(second["messages"]) == 4
    assert second["messages"][:2] == first["messages"]
    assert second["messages"][2] == {"role": "assistant", "content": responses[0]["choices"][0]["message"]["content"]}
    repair = second["messages"][3]
    assert repair["role"] == "user" and repair["content"].startswith("Your JSON failed validation against the schema: ")
    assert "/items/0: 'headword' is a required property" in repair["content"] and repair["content"].endswith(". Return the complete corrected JSON object only.")
    assert repair["content"].count("required property") <= 5
    assert {k: v for k, v in second.items() if k != "messages"} == {k: v for k, v in first.items() if k != "messages"}
    row = ledger.get_call(conn, result.call_id)
    assert row["input_tokens"] == sum(r["usage"]["prompt_tokens"] for r in responses) and row["output_tokens"] == sum(r["usage"]["completion_tokens"] for r in responses)
    assert row["status"] == "success" and conn.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 1
    saved = json.loads((cfg.data_dir / row["stdout_path"]).read_text(encoding="utf-8"))
    assert saved["argv"] == ["openai_http", BASE + "/chat/completions", MODEL]  # §10.2: the argv slot is fixed; the repair round shows in the body
    first_body, second_body = saved["stdout"].split("\n\n--- repair round ---\n\n")
    assert json.loads(first_body)["choices"][0]["message"]["content"] == responses[0]["choices"][0]["message"]["content"]
    assert json.loads(json.loads(second_body)["choices"][0]["message"]["content"]) == result.structured


def test_repair_round_fails_with_schema_prefix_on_schema_mismatch(conn, cfg, install):
    calls, _, _, _ = install("schema_mismatch")
    result = run(conn, cfg)
    assert result.status == "error" and not result.ok and len(calls) == 2
    assert result.error.startswith("schema: /items/0: 'headword' is a required property; /items/1:")
    assert len(result.error) <= 1000 and ledger.get_call(conn, result.call_id)["error"] == result.error
    # invalid JSON is not repaired: the model did not even answer in JSON
    calls, _, _, _ = install("invalid_json")
    assert run(conn, cfg).status == "error" and len(calls) == 1


def test_schema_errors_and_repair_prompt_formatting():
    schema = runner.load_schema("probe_v1")
    errors = openai_http.schema_errors(schema, {"ok": "yes", "echo": "word-dance", "level": 9, "mode": "b", "tags": []})
    assert errors[0].startswith("/level: 9 is not one of [1, 2, 3]") and any(e.startswith("/ok:") for e in errors) and any(e.startswith("/tags:") for e in errors)
    assert openai_http.schema_errors(schema, 42) == ["<root>: 42 is not of type 'object'"]
    assert openai_http.schema_errors(schema, EXPECTED) == []
    prompt = openai_http.repair_prompt([f"/items/{i}: bad" for i in range(8)])
    assert prompt.count("bad") == 5 and prompt.startswith("Your JSON failed validation against the schema: /items/0: bad; ")


# ------------------------------------------------------------------------------------------ strict schema
def test_strict_schema_adds_additional_properties_and_required_recursively_without_touching_the_source():
    for name, objects in (("lookup_v1", 2), ("consolidate_v1", 4), ("content_v1", 3), ("svg_v1", 1), ("probe_v1", 1)):
        original = json.loads((runner.SCHEMAS_DIR / f"{name}.json").read_text(encoding="utf-8"))
        before = json.dumps(original, sort_keys=True)
        strict = openai_http.strict_schema(original)
        assert json.dumps(original, sort_keys=True) == before and "additionalProperties" not in before
        seen = []

        def walk(node):
            if isinstance(node, list):
                for n in node:
                    walk(n)
            elif isinstance(node, dict):
                if node.get("type") == "object":
                    seen.append(node)
                    assert node["additionalProperties"] is False and node["required"] == list(node.get("properties", {}).keys())
                for v in node.values():
                    walk(v)

        walk(strict)
        assert len(seen) == objects, name
        assert strict is not original and strict != original
    strict = openai_http.strict_schema(runner.load_schema("consolidate_v1"))
    fill = strict["properties"]["items"]["items"]["properties"]["fill"]
    assert fill["additionalProperties"] is False and fill["required"] == ["phonetic", "pos", "meaning_zh", "definition_en", "difficulty"]
    assert strict["properties"]["confusable_groups"]["items"] == {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string"}}
    assert runner.load_schema("consolidate_v1") == json.loads((runner.SCHEMAS_DIR / "consolidate_v1.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------- pricing
def test_price_cost_usd_with_and_without_a_table(conn, cfg, install):
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert openai_http.price_cost_usd(cfg, usage) == 0.0 and openai_http.price_table(cfg) == {}
    priced = replace(cfg, ai_fallback_price_json='{"input": 0.2, "output": 0.8}')
    assert openai_http.price_cost_usd(priced, usage) == pytest.approx(1.0 / 7.2, abs=1e-6)
    assert openai_http.price_cost_usd(replace(priced, ai_cny_per_usd=8.0), usage) == pytest.approx(0.125)
    cached = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "prompt_tokens_details": {"cached_tokens": 500_000}}
    assert openai_http.price_cost_usd(priced, cached) == pytest.approx(1.0 / 7.2, abs=1e-6)  # no cache price → full input price
    with_cache = replace(cfg, ai_fallback_price_json='{"input": 0.2, "output": 0.8, "cache_read": 0.04}')
    assert openai_http.price_cost_usd(with_cache, cached) == pytest.approx(0.92 / 7.2, abs=1e-6)
    assert openai_http.price_cost_usd(with_cache, {"input_tokens": 1_000_000, "output_tokens": 0, "cache_read_tokens": 500_000}) == pytest.approx(0.12 / 7.2, abs=1e-6)
    assert openai_http.price_cost_usd(replace(cfg, ai_fallback_price_json="not json"), usage) == 0.0
    assert openai_http.price_cost_usd(priced, {}) == 0.0 and openai_http.price_cost_usd(priced, None) == 0.0
    # the ledger carries the post-hoc cost of a priced call (and it counts in spent_today), 0 on the free tier
    calls, responses, _, _ = install("ok")
    result = run(conn, priced)
    expected = openai_http.price_cost_usd(priced, responses[0]["usage"])
    assert result.ok and expected > 0 and result.cost_usd == pytest.approx(expected)
    assert ledger.get_call(conn, result.call_id)["cost_usd"] == pytest.approx(expected)
    assert budget.spent_today(conn, priced, NOW) == pytest.approx(expected)
    assert budget.estimate("lookup", 3, "fallback") == 0.0 and budget.estimate("lookup", 3) > 0


# ------------------------------------------------------------------------------------------------ key
def test_api_key_from_env_or_0600_file(cfg, tmp_path, caplog):
    assert openai_http.api_key(cfg) == KEY
    key_file = tmp_path / "fallback.key"
    key_file.write_text("sk-from-file-1234\n# the second line is ignored\n", encoding="utf-8")
    key_file.chmod(0o600)
    from_file = replace(cfg, ai_fallback_api_key="", ai_fallback_api_key_file=str(key_file))
    with caplog.at_level(logging.DEBUG, logger="wd.ai.openai_http"):
        assert openai_http.api_key(from_file) == "sk-from-file-1234"
    assert "sk-from-file-1234" not in caplog.text and "readable" not in caplog.text
    assert openai_http.api_key(replace(from_file, ai_fallback_api_key="  sk-direct  ")) == "sk-direct"  # the env value wins
    (tmp_path / "empty.key").write_text("\n\n", encoding="utf-8")
    assert openai_http.api_key(replace(from_file, ai_fallback_api_key_file=str(tmp_path / "empty.key"))) is None
    assert openai_http.api_key(replace(from_file, ai_fallback_api_key_file=str(tmp_path / "missing.key"))) is None
    assert openai_http.api_key(replace(from_file, ai_fallback_api_key_file="")) is None
    key_file.chmod(0o644)
    with caplog.at_level(logging.WARNING, logger="wd.ai.openai_http"):
        assert openai_http.api_key(from_file) == "sk-from-file-1234"
    assert "readable by group/others" in caplog.text and "sk-from-file-1234" not in caplog.text


def test_the_secret_never_appears_in_errors_logs_or_raw_files(conn, cfg, install, caplog, tmp_path):
    key_file = tmp_path / "k"
    key_file.write_text(KEY + "\n", encoding="utf-8")
    key_file.chmod(0o600)
    from_file = replace(cfg, ai_fallback_api_key="", ai_fallback_api_key_file=str(key_file))
    with caplog.at_level(logging.DEBUG, logger="wd.ai.openai_http"):
        calls, _, _, _ = install("401")
        failed = run(conn, from_file)
        calls2, _, _, _ = install("ok")
        fine = run(conn, from_file)
    assert failed.status == "auth" and fine.ok
    assert calls[0]["auth_scheme"] == "Bearer" and calls2[0]["auth_scheme"] == "Bearer"
    assert calls[0]["auth_sha256"] == calls2[0]["auth_sha256"] == sha(KEY)  # the file's first line, stripped — pinned by fingerprint, never by the token
    assert KEY not in json.dumps(calls + calls2)
    assert KEY not in failed.error and KEY not in caplog.text and "fallback lookup call" in caplog.text
    for r in (failed, fine):
        row = ledger.get_call(conn, r.call_id)
        assert KEY not in json.dumps(row) and KEY not in (cfg.data_dir / row["stdout_path"]).read_text(encoding="utf-8")
    assert not any("authorization" in c["headers"] for c in calls + calls2)
    # a vendor body that echoes the key is scrubbed before it reaches the ledger
    answers = iter([httpx.Response(400, json={"error": {"message": f"bad key {KEY}"}})])
    openai_http.CLIENT_FACTORY = lambda t: httpx.Client(transport=httpx.MockTransport(lambda r: next(answers)), timeout=t)
    echoed = run(conn, from_file)
    assert echoed.status == "error" and KEY not in echoed.error and "***" in echoed.error


def test_not_configured_is_a_spawn_error_without_a_request(conn, cfg, install):
    calls, _, _, _ = install("ok")
    for broken, what in ((replace(cfg, ai_fallback_model=""), "model"), (replace(cfg, ai_fallback_api_key=""), "api_key"), (replace(cfg, ai_fallback_base_url=""), "base_url")):
        result = run(conn, broken)
        assert result.status == "spawn_error" and not result.ok and result.provider == "fallback"
        assert result.error == f"not_found: fallback not configured ({what} missing)"
        row = ledger.get_call(conn, result.call_id)
        assert row["status"] == "spawn_error" and row["exit_code"] is None and row["stdout_path"] is None and row["provider"] == "fallback" and row["finished_at"] == NOW
    result = run(conn, replace(cfg, ai_fallback_model="", ai_fallback_api_key=""))
    assert result.error == "not_found: fallback not configured (model, api_key missing)"
    assert calls == []


def test_a_key_that_cannot_travel_in_a_header_is_refused_before_any_request(conn, cfg, install, tmp_path):
    """A UTF-8 BOM, a full-width or a control character in the key used to escape as UnicodeEncodeError / a protocol error
    and leave the row `running`; now it is a finished spawn_error like any other misconfiguration (no request is made)."""
    calls, _, _, _ = install("ok")
    for bad in ("﻿sk-x", "ｓk-x", "sk-\x01x", "sk-x\r\nX-Injected: 1"):
        result = run(conn, replace(cfg, ai_fallback_api_key=bad))
        assert result.status == "spawn_error" and not result.ok and result.provider == "fallback"
        assert result.error == "not_found: fallback not configured (api_key is not printable ASCII)"
        row = ledger.get_call(conn, result.call_id)
        assert row["status"] == "spawn_error" and row["finished_at"] == NOW and row["exit_code"] is None and row["stdout_path"] is None
        assert bad not in result.error
    assert calls == []
    assert conn.execute("SELECT COUNT(*) FROM ai_calls WHERE status='running'").fetchone()[0] == 0
    # a key FILE saved with a BOM (Windows editors) is read cleanly — the BOM never reaches the header
    key_file = tmp_path / "bom.key"
    key_file.write_bytes("﻿sk-from-bom-file\n".encode("utf-8"))
    key_file.chmod(0o600)
    from_file = replace(cfg, ai_fallback_api_key="", ai_fallback_api_key_file=str(key_file))
    assert openai_http.api_key(from_file) == "sk-from-bom-file"
    assert run(conn, from_file).ok and len(calls) == 1 and calls[0]["auth_scheme"] == "Bearer" and calls[0]["auth_sha256"] == sha("sk-from-bom-file")


def test_the_bearer_token_is_exactly_the_env_key_or_the_first_line_of_the_key_file(conn, cfg, install, tmp_path):
    """(review) The fake used to keep only the scheme word, so a wrong credential — the file's path, an unstripped line, a second
    line, the scrubbed value, the env key when the file was configured — passed every test. ``auth_sha256`` pins the exact token:
    the stripped env value, else the stripped first line of the key file; the token itself is never recorded."""
    calls, _, _, _ = install("ok")
    assert run(conn, replace(cfg, ai_fallback_api_key="  " + KEY + "\t\n")).ok
    assert calls[-1]["auth_scheme"] == "Bearer" and calls[-1]["auth_sha256"] == sha(KEY)
    key_file = tmp_path / "fallback.key"
    key_file.write_text("  sk-from-file-1234  \nsk-second-line-never-sent\n", encoding="utf-8")
    key_file.chmod(0o600)
    from_file = replace(cfg, ai_fallback_api_key="", ai_fallback_api_key_file=str(key_file))
    assert run(conn, from_file).ok
    assert calls[-1]["auth_sha256"] == sha("sk-from-file-1234")
    assert calls[-1]["auth_sha256"] not in {sha(str(key_file)), sha("  sk-from-file-1234  "), sha("sk-from-file-1234\n"), sha("sk-second-line-never-sent"), sha("***")}
    bom = tmp_path / "bom.key"
    bom.write_bytes("\ufeffsk-from-bom-file\r\n".encode("utf-8"))
    bom.chmod(0o600)
    assert run(conn, replace(from_file, ai_fallback_api_key_file=str(bom))).ok and calls[-1]["auth_sha256"] == sha("sk-from-bom-file")
    assert run(conn, replace(from_file, ai_fallback_api_key="sk-env-wins")).ok and calls[-1]["auth_sha256"] == sha("sk-env-wins")  # the env value wins over the file
    assert len(calls) == 4 and {c["auth_scheme"] for c in calls} == {"Bearer"}
    recorded = json.dumps(calls)
    assert all(secret not in recorded for secret in (KEY, "sk-from-file-1234", "sk-from-bom-file", "sk-env-wins", "sk-second-line-never-sent"))


def test_an_unexpected_exception_finishes_the_row_as_an_internal_error(conn, cfg, monkeypatch, caplog):
    """Step 10 of the contract: a defect inside the request loop (anything that is not an httpx / OS error) becomes a
    per-call `error` with a finished ledger row — never an exception out of run_openai and a row stuck in `running`.
    sqlite errors keep propagating."""

    def boom(request):
        raise RuntimeError(f"transport bug with the key {KEY} in the message")

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(boom), timeout=t))
    with caplog.at_level(logging.DEBUG, logger="wd.ai.openai_http"):
        result = run(conn, cfg)
    assert result.status == "error" and not result.ok and result.provider == "fallback" and result.structured is None
    assert result.error == "internal: RuntimeError: transport bug with the key *** in the message"
    row = ledger.get_call(conn, result.call_id)
    assert row["status"] == "error" and row["finished_at"] == NOW and row["exit_code"] is None and row["error"] == result.error and row["provider"] == "fallback"
    assert row["input_tokens"] is None and row["model_used"] is None and row["stdout_path"]
    assert conn.execute("SELECT COUNT(*) FROM ai_calls WHERE status='running'").fetchone()[0] == 0
    assert "crashed inside the adapter" in caplog.text and "RuntimeError" in caplog.text and "Traceback" in caplog.text
    assert KEY not in caplog.text and KEY not in (cfg.data_dir / row["stdout_path"]).read_text(encoding="utf-8")
    # a reserved row gets the same treatment
    reservation = budget.reserve(conn, kind="lookup", word_count=3, priority=20, now=NOW, cfg=cfg, flag_tier=0, job_ids=[9], provider="fallback")
    again = run(conn, cfg, call_id=reservation.call_id)
    assert again.status == "error" and ledger.get_call(conn, reservation.call_id)["finished_at"] == NOW
    # the client factory is inside the net as well (httpx.Client() loads the CA bundle — a broken install raises there)
    def no_ssl(timeout_s):
        raise FileNotFoundError(2, "No such file or directory", "/nonexistent/cacert.pem")

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", no_ssl)
    broken = run(conn, cfg)
    assert broken.status == "error" and broken.error.startswith("internal: FileNotFoundError: ") and ledger.get_call(conn, broken.call_id)["finished_at"] == NOW
    # sqlite trouble is not swallowed
    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", lambda t: httpx.Client(transport=httpx.MockTransport(boom), timeout=t))
    monkeypatch.setattr(openai_http, "_post", locked)
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        run(conn, cfg)


def test_default_client_does_not_trust_the_environment(conn, cfg, install, monkeypatch):
    calls, _, _, inner = install("ok")
    monkeypatch.setattr(openai_http, "CLIENT_FACTORY", None)
    captured: dict = {}
    real = httpx.Client

    def spy(**kwargs):
        captured.update(kwargs)
        return real(transport=inner, timeout=kwargs["timeout"])

    monkeypatch.setattr(openai_http.httpx, "Client", spy)
    assert run(conn, cfg, timeout_s=90).ok
    assert captured["trust_env"] is False and captured["timeout"] == httpx.Timeout(90.0, connect=20.0)
    assert calls[0]["timeout"]["connect"] == 20.0 and 89.0 < calls[0]["timeout"]["read"] <= 90.0  # the per-request bound rides on the client default


# -------------------------------------------------------------------------------------------- classify
@pytest.mark.parametrize(
    "code,body,expected",
    [
        (401, '{"error":{"message":"Incorrect API key"}}', ("auth", "unauthorized", None)),
        (401, '{"error":{"code":"1002","message":"令牌已过期或验证不正确"}}', ("auth", "unauthorized", None)),
        (402, "Insufficient Balance", ("auth", "balance:", None)),
        (429, '{"error":{"code":"1113","message":"您的账户已欠费，请充值后重试"}}', ("auth", "balance:", None)),
        (429, '{"error":{"type":"insufficient_quota","message":"You exceeded your current quota"}}', ("auth", "balance:", None)),
        (403, '{"code":"Arrearage","message":"Access denied, please make sure your account is in good standing."}', ("auth", "balance:", None)),
        (403, '{"error":{"message":"Request not allowed"}}', ("auth", "forbidden", None)),
        (403, '{"code":"AllocationQuota.FreeTierOnly","message":"Free tier only"}', ("auth", "quota:", None)),
        (404, "<html>Not Found</html>", ("spawn_error", "not_found:", None)),
        (400, '{"error":{"code":"1211","message":"模型不存在，请检查模型代码。"}}', ("spawn_error", "not_found:", None)),
        (400, '{"error":{"code":"model_not_found","message":"The model `x` does not exist"}}', ("spawn_error", "not_found:", None)),
        (400, '{"error":{"message":"The model \'glm-x\' does not exist or you do not have access to it."}}', ("spawn_error", "not_found:", None)),
        (400, '{"code":"InvalidParameter","message":"Model not exist."}', ("spawn_error", "not_found:", None)),  # DashScope / DeepSeek wording
        (400, '{"error":{"message":"The parameter `foo` does not exist"}}', ("error", "http_400", None)),  # not about the model: a per-request 400 must not disable the fallback
        (400, '{"error":{"message":"Tool `search` does not exist"},"model":"glm-4.7-flash"}', ("error", "http_400", None)),  # `model` as a JSON key does not count
        (429, '{"error":{"code":"1302","message":"您的账户已达到速率限制"}}', ("overloaded", "rate_limit", None)),
        (429, "Too Many Requests", ("overloaded", "rate_limit", None)),
        (429, '{"error":{"code":"1308","message":"已达到 1000 次 的使用上限。您的限额将在 2026-10-14 10:00:00 重置"}}', ("overloaded", "quota:", "2026-10-14T02:00:00Z")),
        (429, '{"error":{"code":"1308","message":"quota exceeded","next_flush_time":"2026-10-14T10:00:00+08:00"}}', ("overloaded", "quota:", "2026-10-14T02:00:00Z")),
        (429, '{"error":{"code":"1308","message":"quota exceeded"},"next_flush_time":%d}' % int(parse_iso("2026-10-14T02:00:00Z").timestamp()), ("overloaded", "quota:", "2026-10-14T02:00:00Z")),
        (429, '{"error":{"code":"1308","message":"quota exceeded"},"next_flush_time":%d}' % (int(parse_iso("2026-10-14T02:00:00Z").timestamp()) * 1000), ("overloaded", "quota:", "2026-10-14T02:00:00Z")),
        (429, '{"error":{"message":"Free tier limit reached"}}', ("overloaded", "quota:", None)),
        (500, "boom", ("overloaded", "http_500", None)),
        (502, "", ("overloaded", "http_502", None)),
        (503, '{"error":{"message":"overloaded"}}', ("overloaded", "http_503", None)),
        (504, "", ("overloaded", "http_504", None)),
        (529, "", ("overloaded", "http_529", None)),
        (400, '{"error":{"code":"data_inspection_failed","message":"Output data may contain inappropriate content."}}', ("error", "content_filter:", None)),
        (400, '{"error":{"code":"1301","message":"系统检测到输入或生成内容可能包含不安全或敏感内容"}}', ("error", "content_filter:", None)),
        (400, '{"error":{"message":"Invalid value for max_tokens"}}', ("error", "http_400", None)),
        (418, "I'm a teapot", ("error", "http_418", None)),
        (422, "", ("error", "http_422", None)),
    ],
)
def test_classify_http_table(code, body, expected):
    assert openai_http.classify_http(code, body, {}) == expected
    status, reason, retry_at = expected
    assert status in ledger.STATUSES and status != "running"
    error = openai_http.compose_error(reason, retry_at, code, body)
    assert error.startswith(reason) and f" HTTP {code}: " in error and len(error) <= len(reason) + 60 + 300
    if retry_at:
        assert f"retry_at={retry_at} HTTP" in error


def test_classify_exceptions():
    assert openai_http.classify_exception(httpx.ReadTimeout("x"), 180) == ("timeout", "timeout after 180s: ReadTimeout")
    assert openai_http.classify_exception(httpx.ConnectTimeout("x"), 90.0) == ("timeout", "timeout after 90s: ConnectTimeout")
    assert openai_http.classify_exception(httpx.ConnectError("[Errno 61] Connection refused"), 1) == ("overloaded", "network: ConnectError: [Errno 61] Connection refused")
    assert openai_http.classify_exception(httpx.RemoteProtocolError("peer closed"), 1)[0] == "overloaded"
    assert openai_http.classify_exception(OSError("tls"), 1) == ("overloaded", "network: OSError: tls")
    # §10.3: every other httpx.HTTPError is `network:` — including a malformed base URL, whose message names the cause
    assert openai_http.classify_exception(httpx.UnsupportedProtocol("Request URL is missing an 'http://' or 'https://' protocol."), 1) == (
        "overloaded",
        "network: UnsupportedProtocol: Request URL is missing an 'http://' or 'https://' protocol.",
    )
    assert openai_http.classify_exception(httpx.InvalidURL("Invalid port"), 1) == ("overloaded", "network: InvalidURL: Invalid port")


def test_retry_at_from_body_variants():
    assert openai_http.retry_at_from_body('{"next_flush_time":"2026-10-14 10:00"}') == "2026-10-14T02:00:00Z"
    assert openai_http.retry_at_from_body('{"error":{"code":"1308","message":"已达到 使用上限。您的限额将在 2026-10-14T10:00:00 重置"}}') == "2026-10-14T02:00:00Z"
    assert openai_http.retry_at_from_body('{"next_flush_time":"2026-10-14T02:00:00Z"}') == "2026-10-14T02:00:00Z"
    assert openai_http.retry_at_from_body('{"error":{"code":"1302","message":"rate limited at 2026-10-14 10:00:00"}}') is None  # not a quota window
    assert openai_http.retry_at_from_body('{"next_flush_time":"soon"}') is None and openai_http.retry_at_from_body("") is None


# --------------------------------------------------------------------------------------------- extract
def test_extract_json_variants():
    obj = {"items": [{"input": "a}b{", "n": 1}]}
    text = json.dumps(obj, ensure_ascii=False)
    assert openai_http.extract_json(text) == (obj, "")
    assert openai_http.extract_json("  \n" + text + "\n ") == (obj, "")
    assert openai_http.extract_json("```json\n" + json.dumps(obj, indent=2) + "\n```") == (obj, "")
    assert openai_http.extract_json("```\n" + text + "```") == (obj, "")
    assert openai_http.extract_json("Sure! Here you go:\n" + text + "\nAnything else?") == (obj, "")
    assert openai_http.extract_json("[1, 2]") == (None, "JSON is a list, not an object")
    assert openai_http.extract_json("42") == (None, "JSON is a int, not an object")
    assert openai_http.extract_json("this is not json {{{ garbage") == (None, "no JSON object found")
    bad = openai_http.extract_json('prose {"a": 1, "b": } more')
    assert bad[0] is None and bad[1].startswith("invalid JSON:")
    assert openai_http.extract_json("") == (None, "empty content") and openai_http.extract_json("   ") == (None, "empty content")
    assert openai_http.extract_json(None) == (None, "no text")
    assert openai_http.extract_json('{"zh": "中文", "nested": {"x": [1, {"y": "}"}]}}')[0] == {"zh": "中文", "nested": {"x": [1, {"y": "}"}]}}


def test_usage_tokens_shapes():
    assert openai_http.usage_tokens({"prompt_tokens": 10, "completion_tokens": 3, "prompt_tokens_details": {"cached_tokens": 4}}) == {"input_tokens": 10, "output_tokens": 3, "cache_read_tokens": 4}
    assert openai_http.usage_tokens({"prompt_tokens": "10", "completion_tokens": None, "prompt_cache_hit_tokens": 7}) == {"input_tokens": 10, "output_tokens": None, "cache_read_tokens": 7}
    assert openai_http.usage_tokens({"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 0}) == {"input_tokens": 1, "output_tokens": 2, "cache_read_tokens": 0}
    assert openai_http.usage_tokens(None) == openai_http.usage_tokens("x") == {"input_tokens": None, "output_tokens": None, "cache_read_tokens": None}


# ----------------------------------------------------------------------------------------------- probe
def test_probe_round_trip_returns_exactly_expected(conn, cfg, install):
    calls, _, _, _ = install("ok")
    result = run(conn, cfg, kind="probe", timeout_s=budget.timeout_for(cfg, "probe", "fallback"))
    assert result.ok and result.structured == EXPECTED and result.provider == "fallback" and result.model_used == MODEL
    body = calls[0]["json"]
    assert body["max_tokens"] == 512 and body["messages"][1]["content"] == PROBE_PROMPT and body["messages"][0]["content"].startswith(PROBE_SYSTEM_PROMPT)
    row = ledger.get_call(conn, result.call_id)
    assert row["kind"] == "probe" and row["max_budget_usd"] == 0.05 and row["reserved_usd"] == 0.0 and row["flag_tier"] == 0 and row["provider"] == "fallback"
    # the probe's exact-match requirement: a schema-valid but different answer is `ok` at the adapter and rejected by the probe
    answers = iter([httpx.Response(200, json={"model": MODEL, "choices": [{"message": {"content": json.dumps({**EXPECTED, "level": 3})}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})])
    openai_http.CLIENT_FACTORY = lambda t: httpx.Client(transport=httpx.MockTransport(lambda r: next(answers)), timeout=t)
    other = run(conn, cfg, kind="probe")
    assert other.ok and other.structured != EXPECTED


# ------------------------------------------------------------------------------------------------ fake
def test_fake_openai_records_requests_and_switches_modes():
    calls: list[dict] = []
    t = fake_openai.transport("ok", calls=calls, modes=["503"])
    client = httpx.Client(transport=t)
    body = {"model": "m", "messages": [{"role": "system", "content": openai_http.compose_system("S", runner.load_schema("probe_v1"), "json_object")}, {"role": "user", "content": PROBE_PROMPT}]}
    assert client.post(BASE + "/chat/completions", json=body, headers={"Authorization": "Bearer zzz"}).status_code == 503
    r = client.post(BASE + "/chat/completions", json=body, headers={"Authorization": "Bearer zzz"})
    assert r.status_code == 200 and json.loads(r.json()["choices"][0]["message"]["content"]) == EXPECTED and r.json()["model"] == "m"
    assert r.json()["usage"]["prompt_tokens"] > 20 and r.json()["usage"]["completion_tokens"] > 0
    fake_openai.set_mode(t, "401")
    assert client.post(BASE + "/chat/completions", json=body).status_code == 401
    assert client.post(BASE + "/v1/models", json={}).status_code == 404
    assert len(calls) == 4 and all("authorization" not in c["headers"] for c in calls) and calls[0]["auth_scheme"] == "Bearer" and calls[2]["auth_scheme"] is None
    assert calls[0]["auth_sha256"] == sha("zzz") and calls[2]["auth_sha256"] is None and "Bearer zzz" not in json.dumps(calls)
    assert calls[0]["timeout"] == {"connect": 5.0, "read": 5.0, "write": 5.0, "pool": 5.0}  # httpx's client default, recorded per request
    assert calls[0]["json"] == body and calls[0]["url"] == BASE + "/chat/completions"
    # the kind is read from a json_schema response_format as well
    strict = {"model": "m", "messages": [{"role": "system", "content": "S"}, {"role": "user", "content": LOOKUP_PROMPT}], "response_format": {"type": "json_schema", "json_schema": {"name": "lookup_v1", "schema": openai_http.strict_schema(runner.load_schema("lookup_v1")), "strict": True}}}
    fake_openai.set_mode(t, "ok")
    r = client.post(BASE + "/chat/completions", json=strict)
    assert [it["input"] for it in json.loads(r.json()["choices"][0]["message"]["content"])["items"]] == STRINGS
    for mode in fake_openai.MODES:
        if mode in ("network", "timeout"):
            with pytest.raises(httpx.HTTPError):
                fake_openai.respond(body, mode)
        else:
            assert isinstance(fake_openai.respond(body, mode), httpx.Response)
