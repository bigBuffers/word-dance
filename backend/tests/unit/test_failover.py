"""ai/failover.py: provider choice per mode, the §4.2 failure → action table (hard / soft / never triggers), per-provider
pauses and streaks, the compare-and-swap flip of ``kv.ai.active_provider``, fail-back through a success or a probe, the
admin pause / resume and the best-effort webhook notifications (AI_FALLBACK_MODEL §4.1–§4.3); slice 2 (CLAUDE_INTEGRATION
§10.4–§10.6): content on the fallback by default, the claim size while the fallback takes content (``group_cap`` /
``claim_limit``), the fallback's quality streak and the fail-back requeue of the jobs that died during the outage; the
review follow-ups: the quality pause tag (``ai.fallback.pause_reason``) and what lifts it, the three tails of the quality
notification, a clean quality count per episode, the no-flip requeue keyed on the claude pause start, the episode
bookkeeping ending with a fail-back / the resume / ``reconcile_mode``, and revived jobs batching without a ``group_size``."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest

from wd import db
from wd.ai import budget, failover, ledger
from wd.clock import parse_iso, to_iso
from wd.delivery import webhook
from wd.interfaces import ClaudeResult
from wd.jobs import queue

NOW = "2026-10-14T00:00:00Z"  # 08:00 Asia/Shanghai
PUBLIC_IP = "93.184.216.34"
HOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test"


# -------------------------------------------------------------------------------------------- helpers
def auto_cfg(settings, **over):
    base = dict(ai_provider="auto", ai_fallback_kind="openai_http", ai_fallback_base_url="https://mock.example/v4", ai_fallback_model="glm-4.7-flash", ai_fallback_api_key="k")
    base.update(over)
    return replace(settings, **base)


def res(status: str, error: str | None = None, *, provider: str = "claude", call_id: int = 0, ok: bool = False) -> ClaudeResult:
    return ClaudeResult(ok=ok, status=status, structured=None, cost_usd=0, call_id=call_id, model_used=None, error=error, provider=provider)


def rf(conn, cfg, *, provider: str, result: ClaudeResult, kind: str, now: str, priority: int = 20, **kw) -> failover.Decision:
    """``record_failure`` for an ordinary (non-prewarm) group: ``priority`` is a required keyword there."""
    return failover.record_failure(conn, cfg, provider=provider, result=result, kind=kind, now=now, priority=priority, **kw)


def events(conn, kind: str) -> list[dict]:
    return [json.loads(r[0]) for r in conn.execute("SELECT detail_json FROM system_events WHERE kind = ? ORDER BY id", (kind,))]


def kv(conn, key: str) -> str | None:
    return db.kv_get(conn, key)


def plus(minutes: float) -> str:
    return to_iso(parse_iso(NOW) + timedelta(minutes=minutes))


def park(conn, type_: str, key: str, until: str, *, now: str = NOW) -> int:
    """A queued job of ``type_`` deferred to ``until`` the way ``claude_call`` / ``handle_failure`` park a group."""
    job_id = queue.enqueue(conn, type_, {"k": key}, dedupe_key=key, priority=20, now=now)
    queue.defer(conn, [job_id], until, now=now)
    return job_id


def run_after(conn, job_id: int) -> str:
    return str(queue.get_job(conn, job_id).run_after)


def make_admin(conn, username="root", *, url=HOOK_URL, fmt="wecom", enabled=1, role="admin") -> int:
    uid = int(conn.execute("INSERT INTO users(username, password_hash, role, onboarding_state) VALUES (?, 'x', ?, 'done')", (username, role)).lastrowid)
    conn.execute(
        "INSERT INTO user_settings(user_id, next_push_at, webhook_enabled, webhook_url, webhook_format) VALUES (?, '2026-10-15T00:00:00Z', ?, ?, ?)",
        (uid, enabled, url, fmt),
    )
    return uid


class Captured:
    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"errcode": 0})

    def install(self, monkeypatch) -> "Captured":
        transport = httpx.MockTransport(self.handler)
        monkeypatch.setattr(failover, "WEBHOOK_CLIENT_FACTORY", lambda: httpx.Client(transport=transport, follow_redirects=False))
        monkeypatch.setattr(webhook, "resolve_host", lambda host: [PUBLIC_IP])  # the SSRF pin without DNS
        return self

    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture(autouse=True)
def _no_client_hook(monkeypatch):
    monkeypatch.setattr(failover, "WEBHOOK_CLIENT_FACTORY", None)


# ------------------------------------------------------------------------------------- basics / state
def test_mode_active_provider_and_banner(conn, settings):
    assert failover.mode(settings) == "claude_cli"
    assert failover.mode(auto_cfg(settings)) == "auto"
    assert failover.mode(auto_cfg(settings, ai_provider="openai_http")) == "openai_http"
    assert failover.active_provider(conn) == "claude"
    db.kv_set(conn, "ai.active_provider", "garbage")
    assert failover.active_provider(conn) == "claude"
    db.kv_set(conn, "ai.active_provider", "fallback")
    assert failover.active_provider(conn) == "fallback"
    assert failover.AUTH_BANNER_ZH == "Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录"
    assert failover.banner_for("auth") == failover.AUTH_BANNER_ZH and failover.banner_for("???") == failover.AUTH_BANNER_ZH
    assert failover.banner_for("balance") == failover.BALANCE_BANNER_ZH and "充值" in failover.BALANCE_BANNER_ZH
    assert failover.banner_for("spawn_error") == failover.SPAWN_BANNER_ZH == failover.banner_for("not_found") and "WD_CLAUDE_BIN" in failover.SPAWN_BANNER_ZH
    assert failover.banner_for("quota") == failover.QUOTA_BANNER_ZH
    assert failover.set_fallback_paused_until is not None
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)
    assert budget.provider_paused_until(conn, "fallback", NOW) == plus(10)
    failover.set_fallback_paused_until(conn, None, now=NOW)
    assert budget.provider_paused_until(conn, "fallback", NOW) is None


def test_classify_and_prefixes():
    assert failover.classify(res("auth")) == ("hard", "auth")
    assert failover.classify(res("spawn_error", "exit 127: not found")) == ("hard", "spawn_error")
    assert failover.classify(res("auth", "balance: HTTP 402: insufficient balance")) == ("hard", "balance")
    assert failover.classify(res("overloaded", "quota: HTTP 429: 1308 retry_at=2026-10-14T01:00:00Z")) == ("hard", "quota")
    assert failover.classify(res("spawn_error", "not_found: HTTP 404: model not found")) == ("hard", "not_found")
    assert failover.classify(res("overloaded", "API Error: 529 overloaded")) == ("soft", "overloaded")
    assert failover.classify(res("overloaded", "network: ConnectError: fetch failed ECONNREFUSED")) == ("soft", "network")
    assert failover.classify(res("timeout", "timeout after 120s: ReadTimeout")) == ("soft", "timeout")
    for status, error in (("budget", None), ("invalid_output", None), ("error", "content_filter: HTTP 400: data_inspection_failed"), ("error", "truncated: finish_reason=length"), ("error", "schema: items is a required property"), ("error", "invalid_json: no object")):
        assert failover.classify(res(status, error)) == ("never", None), (status, error)
    assert failover.classify(res("success", ok=True)) == ("never", None)
    assert failover.error_prefix("exit 1: boom") is None and failover.error_prefix(None) is None
    assert failover.retry_at_from_error("quota: ... retry_at=2026-10-14T01:30:00Z", NOW) == "2026-10-14T01:30:00Z"
    assert failover.retry_at_from_error("quota: ... retry_at=2026-10-14T09:30:00+08:00", NOW) == "2026-10-14T01:30:00Z"
    assert failover.retry_at_from_error("quota: ... retry_at=2026-10-13T01:30:00Z", NOW) is None  # in the past
    assert failover.retry_at_from_error("quota: no window", NOW) is None


def test_fallback_eligible_rules(conn, settings):
    cfg = auto_cfg(settings)
    assert failover.fallback_eligible(conn, settings, kind="lookup", priority=20, now=NOW) == (False, None)  # not configured
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=NOW) == (True, None)
    assert failover.fallback_eligible(conn, cfg, kind="consolidate", priority=20, now=NOW) == (True, None)
    assert failover.fallback_eligible(conn, cfg, kind="content", priority=20, now=NOW) == (True, None)  # in the default WD_AI_FALLBACK_KINDS since slice 2
    assert failover.fallback_eligible(conn, auto_cfg(settings, ai_fallback_kinds=("lookup", "consolidate")), kind="content", priority=20, now=NOW) == (False, None)  # removed by the operator
    assert failover.fallback_eligible(conn, cfg, kind="svg", priority=20, now=NOW) == (False, None)  # never
    assert failover.fallback_eligible(conn, cfg, kind="probe", priority=20, now=NOW) == (True, None)  # a probe always
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=90, now=NOW) == (False, None)  # prewarm needs the flag
    assert failover.fallback_eligible(conn, cfg, kind="content", priority=90, now=NOW) == (False, None)  # … for content too
    assert failover.fallback_eligible(conn, auto_cfg(settings, ai_fallback_prewarm=True), kind="lookup", priority=90, now=NOW) == (True, None)
    assert failover.fallback_eligible(conn, auto_cfg(settings, ai_fallback_kinds=("content", "lookup")), kind="consolidate", priority=20, now=NOW) == (False, None)
    failover.set_fallback_paused_until(conn, plus(20), now=NOW)
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=NOW) == (False, plus(20))
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=plus(21)) == (True, None)  # the pause elapsed
    db.kv_set(conn, "ai.fallback.available", "0")
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=plus(21)) == (False, None)  # until a probe succeeds
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=NOW) == (False, plus(20))


# ------------------------------------------------------------------------------------------- choose
def test_choose_claude_cli_mode(conn, settings):
    assert failover.choose(conn, settings, kind="lookup", priority=20, now=NOW) == ("claude", None)
    budget.set_paused_until(conn, plus(30), now=NOW)
    assert failover.choose(conn, settings, kind="lookup", priority=20, now=NOW) == (None, plus(30))
    assert failover.choose(conn, settings, kind="lookup", priority=20, now=plus(31)) == ("claude", None)
    failover.set_fallback_paused_until(conn, None, now=NOW)
    db.kv_set(conn, "claude.enabled", "0")
    assert failover.choose(conn, settings, kind="lookup", priority=20, now=NOW) == (None, plus(30))  # kill switch: now + 30 min
    db.kv_set(conn, "claude.enabled", "1")
    budget.set_paused_until(conn, None)
    failover.set_manual_pause(conn, plus(60), now=NOW)
    assert failover.choose(conn, settings, kind="lookup", priority=20, now=NOW) == (None, plus(60))  # the admin's global pause
    assert failover.choose(conn, auto_cfg(settings), kind="lookup", priority=20, now=NOW) == (None, plus(60))  # … holds every mode


def test_choose_openai_http_mode(conn, settings):
    cfg = auto_cfg(settings, ai_provider="openai_http")
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("fallback", None)
    assert failover.choose(conn, cfg, kind="content", priority=20, now=NOW) == ("fallback", None)  # routable by default (slice 2)
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == (None, None)  # never routable, nothing scheduled
    assert failover.choose(conn, auto_cfg(settings, ai_provider="openai_http", ai_fallback_kinds=("lookup", "consolidate")), kind="content", priority=20, now=NOW) == (None, None)
    budget.set_paused_until(conn, plus(30), now=NOW)  # a claude pause is irrelevant here
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("fallback", None)
    failover.set_fallback_paused_until(conn, plus(15), now=NOW)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, plus(15))


def test_choose_auto_mode_every_branch(conn, settings):
    cfg = auto_cfg(settings)
    # active == claude
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("claude", None)
    assert failover.choose(conn, cfg, kind="content", priority=20, now=NOW) == ("claude", None)
    budget.set_paused_until(conn, plus(30), now=NOW)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("fallback", None)  # claude paused → fallback
    assert failover.choose(conn, cfg, kind="content", priority=20, now=NOW) == ("fallback", None)  # content is routable by default (slice 2)
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == (None, plus(30))  # svg is never routable: it waits for the CLI
    cli_content = auto_cfg(settings, ai_fallback_kinds=("lookup", "consolidate"))
    assert failover.choose(conn, cli_content, kind="content", priority=20, now=NOW) == (None, plus(30))  # content removed from the kinds
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, plus(10))  # both paused: the earlier of the two
    assert failover.choose(conn, cfg, kind="content", priority=20, now=NOW) == (None, plus(10))  # … content too
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == (None, plus(30))  # svg stays on the claude pause
    assert failover.choose(conn, cfg, kind="lookup", priority=95, now=NOW) == (None, plus(30))  # a prewarm group may not use the fallback
    assert failover.choose(conn, cfg, kind="content", priority=90, now=NOW) == (None, plus(30))  # nor a prewarm content group
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=plus(11)) == ("fallback", None)  # the fallback pause elapsed: the group runs there
    # active == fallback
    db.kv_set(conn, "ai.active_provider", "fallback")
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, plus(10))  # earliest of the two
    budget.set_paused_until(conn, None)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("claude", None)  # fallback paused, claude free
    failover.set_fallback_paused_until(conn, None, now=NOW)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("fallback", None)  # sticky
    assert failover.choose(conn, cfg, kind="content", priority=20, now=NOW) == ("fallback", None)  # content follows the sticky state
    assert failover.choose(conn, cli_content, kind="content", priority=20, now=NOW) == ("claude", None)  # … unless removed from the kinds
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == ("claude", None)  # svg stays on claude
    budget.set_paused_until(conn, plus(30), now=NOW)
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == (None, plus(30))
    assert failover.choose(conn, cli_content, kind="content", priority=20, now=NOW) == (None, plus(30))
    db.kv_set(conn, "ai.fallback.available", "0")
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, plus(30))  # unavailable fallback, paused claude
    budget.set_paused_until(conn, None)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("claude", None)  # unavailable fallback, claude free → claude
    db.kv_delete(conn, "ai.fallback.available")
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("claude", None)  # paused fallback, claude free → claude


def test_availability_reasons(conn, settings):
    cfg = auto_cfg(settings)
    a = failover.availability(conn, cfg, kind="lookup", now=NOW)
    assert (a.ok, a.provider, a.resumes_at, a.active, a.reason) == (True, "claude", None, "claude", "ok")
    db.kv_set(conn, "claude.enabled", "0")
    a = failover.availability(conn, cfg, kind="lookup", now=NOW)
    assert (a.ok, a.provider, a.resumes_at, a.reason) == (False, None, plus(30), "disabled")
    db.kv_set(conn, "claude.enabled", "1")
    failover.set_manual_pause(conn, plus(60), now=NOW)
    a = failover.availability(conn, cfg, kind="lookup", now=NOW)
    assert (a.ok, a.reason, a.global_paused_until, a.resumes_at) == (False, "paused", plus(60), plus(60))
    failover.clear_pauses(conn, now=NOW)
    budget.set_paused_until(conn, plus(30), now=NOW)
    a = failover.availability(conn, cfg, kind="svg", now=NOW)  # never routable to the fallback
    assert (a.ok, a.reason, a.claude_paused_until, a.resumes_at) == (False, "claude_paused_no_fallback", plus(30), plus(30))
    a = failover.availability(conn, cfg, kind="content", now=NOW)  # routable by default since slice 2: the content gates report available
    assert (a.ok, a.provider, a.active, a.reason, a.resumes_at) == (True, "fallback", "claude", "ok", None)
    assert failover.availability(conn, auto_cfg(settings, ai_fallback_kinds=("lookup", "consolidate")), kind="content", now=NOW).reason == "claude_paused_no_fallback"
    assert failover.availability(conn, cfg, kind="content", now=NOW, priority=90).reason == "claude_paused_no_fallback"  # a prewarm group waits for the CLI
    assert failover.availability(conn, cfg, kind="lookup", now=NOW).ok is True
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)
    a = failover.availability(conn, cfg, kind="lookup", now=NOW)
    assert (a.ok, a.reason, a.fallback_paused_until, a.resumes_at) == (False, "both_paused", plus(10), plus(10))  # the earlier pause
    assert failover.availability(conn, cfg, kind="content", now=NOW).resumes_at == plus(10)  # content too
    assert failover.availability(conn, cfg, kind="svg", now=NOW).resumes_at == plus(30)  # svg waits for the CLI
    assert failover.availability(conn, settings, kind="lookup", now=NOW).reason == "claude_paused"
    http = auto_cfg(settings, ai_provider="openai_http")
    assert failover.availability(conn, http, kind="lookup", now=NOW).reason == "fallback_paused"
    failover.set_fallback_paused_until(conn, None, now=NOW)
    assert failover.availability(conn, http, kind="svg", now=NOW).reason == "fallback_unavailable"
    assert failover.availability(conn, http, kind="content", now=NOW).provider == "fallback"
    assert failover.availability(conn, cfg, kind="lookup", now=NOW, priority=95).ok is False  # prewarm may not use the fallback


# ------------------------------------------------------------------------------------ hard triggers
def test_hard_failure_on_claude_switches_in_auto_mode(conn, settings):
    cfg = auto_cfg(settings)
    call_id = ledger.insert_call(conn, kind="lookup", model_requested="sonnet", flag_tier=0, word_count=3, job_ids=[1, 2], max_budget_usd=0.15, reserved_usd=0.01, now=NOW)
    d = rf(conn, cfg, provider="claude", result=res("auth", "Your organization requires remote managed settings to load", call_id=call_id), kind="lookup", now=NOW)
    assert d == failover.Decision("switch", plus(30), "fallback", "ai_failover")
    assert kv(conn, "claude.paused_until") == plus(30)
    assert kv(conn, "claude.available") is None  # only spawn_error marks the binary unusable
    assert kv(conn, "ai.active_provider") == "fallback"
    assert kv(conn, "ai.failover.since") == NOW and kv(conn, "ai.failover.reason") == "auth"
    assert kv(conn, "ai.failover.trigger_call_id") == str(call_id)
    assert kv(conn, "ai.failover.next_probe_at") == plus(30) and kv(conn, "ai.failover.probe_failures") == "0"
    auth = events(conn, "claude_auth")
    assert auth == [{"status": "auth", "error": "Your organization requires remote managed settings to load", "paused_until": plus(30), "banner_zh": failover.AUTH_BANNER_ZH}]
    fo = events(conn, "ai_failover")
    assert len(fo) == 1 and fo[0]["from"] == "claude" and fo[0]["to"] == "fallback" and fo[0]["reason"] == "auth"
    assert fo[0]["trigger_call_id"] == call_id and fo[0]["kind"] == "lookup"
    assert budget.can_spend(conn, "lookup", 1, 20, NOW, cfg=cfg) == (False, plus(30))  # the legacy claude reader
    assert budget.can_spend(conn, "lookup", 1, 20, NOW, cfg=cfg, provider="fallback") == (True, None)
    assert failover.choose(conn, cfg, kind="consolidate", priority=20, now=NOW) == ("fallback", None)
    assert failover.choose(conn, cfg, kind="content", priority=20, now=NOW) == ("fallback", None)  # content moves over too (slice 2)
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == (None, plus(30))


def test_spawn_error_marks_claude_unavailable_and_content_failure_still_switches(conn, settings):
    # content removed from WD_AI_FALLBACK_KINDS: no rerun there, but the outage is recorded, the probe scheduled, the other kinds moved
    cli_content = auto_cfg(settings, ai_fallback_kinds=("lookup", "consolidate"))
    d = rf(conn, cli_content, provider="claude", result=res("spawn_error", "exit 127: claude: command not found"), kind="content", now=NOW)
    assert d == failover.Decision("switch", plus(30), None, "ai_failover")
    assert kv(conn, "claude.available") == "0" and kv(conn, "claude.paused_until") == plus(30)
    assert kv(conn, "ai.active_provider") == "fallback"
    assert events(conn, "claude_auth")[0]["status"] == "spawn_error" and events(conn, "claude_auth")[0]["banner_zh"] == failover.SPAWN_BANNER_ZH
    assert failover.choose(conn, cli_content, kind="lookup", priority=20, now=NOW) == ("fallback", None)
    assert failover.choose(conn, cli_content, kind="content", priority=20, now=NOW) == (None, plus(30))
    # with the default kinds the same failure also names the fallback for the content group itself (already switched: no second event)
    d = rf(conn, auto_cfg(settings), provider="claude", result=res("spawn_error", "exit 127: claude: command not found"), kind="content", now=plus(1))
    assert d == failover.Decision("switch", plus(31), "fallback", None)
    assert len(events(conn, "ai_failover")) == 1 and kv(conn, "claude.paused_until") == plus(31)


def test_claude_auth_event_deduped_within_30_minutes(conn, settings):
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(5))
    assert len(events(conn, "claude_auth")) == 1
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(31))
    assert len(events(conn, "claude_auth")) == 2
    assert len(events(conn, "ai_failover")) == 1  # the flip happened once


def test_claude_cli_mode_pauses_but_never_switches(conn, settings):
    d = rf(conn, settings, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    assert d == failover.Decision("pause", plus(30), None, None)
    assert kv(conn, "claude.paused_until") == plus(30) and kv(conn, "ai.active_provider") is None
    assert events(conn, "ai_failover") == [] and len(events(conn, "claude_auth")) == 1
    assert budget.paused_until(conn, NOW) == plus(30)


def test_hard_failure_without_a_usable_fallback_only_pauses_and_alerts(conn, settings, monkeypatch):
    captured = Captured().install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False)
    make_admin(conn, "root", fmt="generic")
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)
    d = rf(conn, live, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    assert d == failover.Decision("pause", plus(30), None, None)
    assert kv(conn, "ai.active_provider") is None and events(conn, "ai_failover") == [] and len(events(conn, "claude_auth")) == 1
    assert len(captured.requests) == 1 and kv(conn, "ai.notify.both_paused.last_at") == NOW  # nobody is left: the §4.5 alert
    body = captured.bodies()[0]
    assert body["type"] == "ai_both_paused" and body["title"] == "word-Dance：AI 暂时不可用"
    assert "08:30" in body["body"] and "08:10" in body["body"] and "auth：not logged in" in body["body"]
    # a fallback marked unavailable (not_found / spawn_error earlier, its cooldown over) is down too
    db.kv_delete(conn, "ai.notify.both_paused.last_at")
    db.kv_set(conn, "ai.fallback.available", "0")
    d = rf(conn, live, provider="claude", result=res("spawn_error", "exit 127: claude: command not found"), kind="consolidate", now=plus(61))
    assert d == failover.Decision("pause", plus(91), None, None)
    assert len(captured.requests) == 2 and "备用模型不可用（等待探测恢复）" in captured.bodies()[1]["body"] and "09:31" in captured.bodies()[1]["body"]
    # a soft threshold does not pause claude, so it is not "both down" (the handler backs the group off as today)
    db.kv_delete(conn, "ai.notify.both_paused.last_at")
    for _ in range(3):
        d = rf(conn, live, provider="claude", result=res("overloaded", "529"), kind="lookup", now=plus(61))
    assert d == failover.Decision("none", None, None, None) and len(captured.requests) == 2
    # … but the six-streak pause with a paused fallback is
    db.kv_delete(conn, "ai.fallback.available")
    failover.set_fallback_paused_until(conn, plus(120), now=plus(61))
    for _ in range(3):
        d = rf(conn, live, provider="claude", result=res("overloaded", "529"), kind="lookup", now=plus(62))
    assert d == failover.Decision("pause", plus(77), None, None) and len(captured.requests) == 3
    assert captured.bodies()[2]["type"] == "ai_both_paused" and "overloaded" in captured.bodies()[2]["body"]

# ------------------------------------------------------------------------------------ soft triggers
def test_overloaded_streak_switches_after_three_and_pauses_after_six(conn, settings):
    cfg = auto_cfg(settings)
    for i in (1, 2):
        d = rf(conn, cfg, provider="claude", result=res("overloaded", "API Error: 529 overloaded"), kind="lookup", now=NOW)
        assert d == failover.Decision("none", None, None, None)
        assert kv(conn, "claude.overloaded_streak") == str(i)
    d = rf(conn, cfg, provider="claude", result=res("overloaded", "API Error: 529 overloaded"), kind="lookup", now=NOW)
    assert d == failover.Decision("switch", None, "fallback", "ai_failover")
    assert kv(conn, "claude.paused_until") is None  # a soft trigger does not pause
    assert kv(conn, "ai.active_provider") == "fallback" and kv(conn, "ai.failover.reason") == "overloaded"
    for _ in (4, 5):
        d = rf(conn, cfg, provider="claude", result=res("overloaded", "529"), kind="lookup", now=NOW)
        assert (d.action, d.retry_provider, d.event) == ("switch", "fallback", None)  # already switched: the group still reruns there
    d = rf(conn, cfg, provider="claude", result=res("overloaded", "529"), kind="lookup", now=NOW)
    assert d == failover.Decision("switch", plus(15), "fallback", None)
    assert kv(conn, "claude.overloaded_streak") == "0" and kv(conn, "claude.paused_until") == plus(15)
    assert events(conn, "claude_overloaded") == [{"paused_until": plus(15), "consecutive": 6}]
    assert len(events(conn, "ai_failover")) == 1


def test_timeout_and_network_streaks_are_separate(conn, settings):
    cfg = auto_cfg(settings)
    assert rf(conn, cfg, provider="claude", result=res("timeout", "timeout after 120s"), kind="lookup", now=NOW).action == "none"
    assert rf(conn, cfg, provider="claude", result=res("overloaded", "network: fetch failed ECONNREFUSED"), kind="lookup", now=NOW).action == "none"
    assert (kv(conn, "ai.claude.streak.timeout"), kv(conn, "ai.claude.streak.network"), kv(conn, "claude.overloaded_streak")) == ("1", "1", None)
    d = rf(conn, cfg, provider="claude", result=res("overloaded", "network: fetch failed ECONNREFUSED"), kind="consolidate", now=NOW)
    assert d == failover.Decision("switch", None, "fallback", "ai_failover") and kv(conn, "ai.failover.reason") == "network"
    db.kv_set(conn, "ai.active_provider", "claude")  # pretend it failed back; the timeout streak keeps counting
    d = rf(conn, cfg, provider="claude", result=res("timeout", "timeout after 120s"), kind="lookup", now=NOW)
    assert d == failover.Decision("switch", None, "fallback", "ai_failover") and kv(conn, "ai.failover.reason") == "timeout"
    # higher thresholds are honoured
    strict = auto_cfg(settings, ai_failover_timeout_after=5)
    db.kv_set(conn, "ai.active_provider", "claude")
    assert rf(conn, strict, provider="claude", result=res("timeout"), kind="lookup", now=NOW).action == "none"
    assert kv(conn, "ai.claude.streak.timeout") == "3"


def test_soft_streak_in_claude_cli_mode_keeps_todays_behaviour(conn, settings):
    for i in range(1, 6):
        d = rf(conn, settings, provider="claude", result=res("overloaded", "529"), kind="content", now=NOW)
        assert d == failover.Decision("none", None, None, None) and kv(conn, "claude.overloaded_streak") == str(i)
    d = rf(conn, settings, provider="claude", result=res("overloaded", "529"), kind="content", now=NOW)
    assert d == failover.Decision("pause", plus(15), None, None)
    assert kv(conn, "claude.overloaded_streak") == "0" and len(events(conn, "claude_overloaded")) == 1
    assert kv(conn, "ai.active_provider") is None


def test_never_triggers_change_nothing(conn, settings):
    cfg = auto_cfg(settings)
    before = conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall()
    quality = (("invalid_output", None), ("error", "content_filter: HTTP 400: data_inspection_failed"), ("error", "truncated: finish_reason=length"), ("error", "schema: 2 errors"))
    for status, error in (("budget", "max budget exceeded"), ("error", "exit 1: boom"), ("success", None), *quality):
        d = rf(conn, cfg, provider="claude", result=res(status, error, ok=status == "success"), kind="lookup", now=NOW)
        assert d == failover.Decision("none", None, None, None), (status, error)
    # on the fallback the quality misses count a streak (test_fallback_quality_streak_… below); everything else changes nothing there either
    for status, error in (("budget", "max budget exceeded"), ("error", "exit 1: boom"), ("success", None)):
        d = rf(conn, cfg, provider="fallback", result=res(status, error, provider="fallback", ok=status == "success"), kind="lookup", now=NOW)
        assert d == failover.Decision("none", None, None, None), (status, error)
    assert conn.execute("SELECT key, value FROM kv ORDER BY key").fetchall() == before
    assert conn.execute("SELECT COUNT(*) FROM system_events WHERE kind != 'migration'").fetchone()[0] == 0  # 0011 leaves a migration trace (PLAN §2.2)


# --------------------------------------------------------------------------------- the fallback side
def test_fallback_hard_failure_pauses_it_and_retries_on_claude_only_when_claude_is_free(conn, settings):
    cfg = auto_cfg(settings)
    db.kv_set(conn, "ai.active_provider", "fallback")
    d = rf(conn, cfg, provider="fallback", result=res("auth", "unauthorized HTTP 401: {\"error\":{\"code\":\"1002\"}}", provider="fallback", call_id=5), kind="lookup", now=NOW)
    assert d == failover.Decision("pause", plus(30), "claude", None)
    assert kv(conn, "ai.fallback.paused_until") == plus(30) and kv(conn, "claude.paused_until") is None
    assert kv(conn, "ai.active_provider") == "fallback"  # no flip: a successful claude call flips back
    paused = events(conn, "ai_fallback_paused")
    assert paused == [{"status": "auth", "error": "unauthorized HTTP 401: {\"error\":{\"code\":\"1002\"}}", "paused_until": plus(30), "reason": "auth"}]
    assert events(conn, "claude_auth") == []  # the claude banner is never written for the fallback
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("claude", None)
    # claude paused too → nothing to retry on
    budget.set_paused_until(conn, plus(20), now=NOW)
    d = rf(conn, cfg, provider="fallback", result=res("auth", "HTTP 401", provider="fallback"), kind="lookup", now=plus(1))
    assert d == failover.Decision("pause", plus(31), None, None)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=plus(1)) == (None, plus(20))


def test_fallback_soft_threshold_names_claude_and_six_overloads_pause_it(conn, settings):
    cfg = auto_cfg(settings)
    db.kv_set(conn, "ai.active_provider", "fallback")
    for i in (1, 2):
        d = rf(conn, cfg, provider="fallback", result=res("overloaded", "rate_limit HTTP 429", provider="fallback"), kind="lookup", now=NOW)
        assert d == failover.Decision("none", None, None, None) and kv(conn, "ai.fallback.streak.overloaded") == str(i)
    d = rf(conn, cfg, provider="fallback", result=res("overloaded", "rate_limit HTTP 429", provider="fallback"), kind="lookup", now=NOW)
    assert d == failover.Decision("none", None, "claude", None)
    assert kv(conn, "claude.overloaded_streak") is None  # the streaks are per provider
    for _ in (4, 5):
        rf(conn, cfg, provider="fallback", result=res("overloaded", "429", provider="fallback"), kind="lookup", now=NOW)
    d = rf(conn, cfg, provider="fallback", result=res("overloaded", "429", provider="fallback"), kind="lookup", now=NOW)
    assert d == failover.Decision("pause", plus(15), "claude", None)
    assert kv(conn, "ai.fallback.streak.overloaded") == "0" and kv(conn, "ai.fallback.paused_until") == plus(15)
    assert events(conn, "ai_fallback_paused")[-1]["consecutive"] == 6 and events(conn, "claude_overloaded") == []


def test_openai_http_mode_only_pauses_the_fallback(conn, settings):
    cfg = auto_cfg(settings, ai_provider="openai_http")
    d = rf(conn, cfg, provider="fallback", result=res("auth", "HTTP 401", provider="fallback"), kind="lookup", now=NOW)
    assert d == failover.Decision("pause", plus(30), None, None)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, plus(30))
    for _ in range(2):
        d = rf(conn, cfg, provider="fallback", result=res("timeout", "timeout after 180s", provider="fallback"), kind="lookup", now=NOW)
    assert d == failover.Decision("none", None, None, None) and kv(conn, "ai.fallback.streak.timeout") == "2"


def test_balance_pauses_24_hours_and_quota_honours_retry_at(conn, settings):
    cfg = auto_cfg(settings)
    d = rf(conn, cfg, provider="claude", result=res("auth", "balance: API Error: 402 insufficient balance"), kind="lookup", now=NOW)
    assert d == failover.Decision("switch", plus(24 * 60), "fallback", "ai_failover")
    assert kv(conn, "claude.paused_until") == plus(24 * 60) and kv(conn, "ai.failover.reason") == "balance"
    assert events(conn, "claude_auth")[0]["error"].startswith("balance:") and events(conn, "claude_auth")[0]["banner_zh"] == failover.BALANCE_BANNER_ZH
    d = rf(conn, cfg, provider="fallback", result=res("overloaded", "quota: HTTP 429: {\"code\":\"1308\"} retry_at=2026-10-14T01:30:00Z", provider="fallback"), kind="lookup", now=NOW)
    assert d.action == "pause" and d.paused_until == "2026-10-14T01:30:00Z" and d.retry_provider is None  # claude is paused for balance
    assert kv(conn, "ai.fallback.paused_until") == "2026-10-14T01:30:00Z"
    d = rf(conn, cfg, provider="fallback", result=res("overloaded", "quota: HTTP 429 window exceeded", provider="fallback"), kind="lookup", now=plus(5))
    assert d.paused_until == plus(35)  # no window given → the cooldown
    d = rf(conn, cfg, provider="fallback", result=res("auth", "balance: HTTP 402: arrearage", provider="fallback"), kind="lookup", now=plus(5))
    assert d.paused_until == plus(5 + 24 * 60)


def test_not_found_marks_the_fallback_unavailable_until_a_success(conn, settings):
    cfg = auto_cfg(settings)
    db.kv_set(conn, "ai.active_provider", "fallback")
    d = rf(conn, cfg, provider="fallback", result=res("spawn_error", "not_found: HTTP 404: model not found (1211)", provider="fallback"), kind="lookup", now=NOW)
    assert d == failover.Decision("pause", plus(30), "claude", None)
    assert kv(conn, "ai.fallback.available") == "0" and kv(conn, "ai.fallback.paused_until") == plus(30)
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=plus(31)) == (False, None)  # still off after the pause
    assert failover.record_success(conn, cfg, provider="fallback", kind="probe", model_used="glm-4.7-flash", now=plus(40)) is False
    assert kv(conn, "ai.fallback.available") == "1" and kv(conn, "ai.fallback.model_seen") == "glm-4.7-flash"
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=plus(40)) == (True, None)
    # a configuration failure reported as spawn_error without the prefix marks it too
    d = rf(conn, cfg, provider="fallback", result=res("spawn_error", "fallback not configured (api key)", provider="fallback"), kind="lookup", now=plus(40))
    assert kv(conn, "ai.fallback.available") == "0" and d.paused_until == plus(70)


# ------------------------------------------------------------------------------------- CAS / failback
def test_cas_flips_once_and_both_callers_get_the_retry(conn, settings, connect):
    cfg = auto_cfg(settings)
    other = connect()
    try:
        d1 = rf(conn, cfg, provider="claude", result=res("auth", "not logged in", call_id=1), kind="lookup", now=NOW)
        d2 = rf(other, cfg, provider="claude", result=res("auth", "not logged in", call_id=2), kind="consolidate", now=NOW)
    finally:
        other.close()
    assert d1 == failover.Decision("switch", plus(30), "fallback", "ai_failover")
    assert d2 == failover.Decision("switch", plus(30), "fallback", None)
    assert len(events(conn, "ai_failover")) == 1 and kv(conn, "ai.failover.trigger_call_id") == "1"
    assert kv(conn, "ai.active_provider") == "fallback"
    # the primitive itself: absent → claude, garbage counts as claude, a lost race is reported
    db.kv_delete(conn, "ai.active_provider")
    assert failover._cas_active(conn, "claude", "fallback", now=NOW) is True
    assert failover._cas_active(conn, "claude", "fallback", now=NOW) is False
    assert failover._cas_active(conn, "fallback", "claude", now=NOW) is True
    db.kv_set(conn, "ai.active_provider", "???")
    assert failover._cas_active(conn, "claude", "fallback", now=NOW) is True and kv(conn, "ai.active_provider") == "fallback"
    db.kv_delete(conn, "ai.active_provider")
    assert failover._cas_active(conn, "fallback", "claude", now=NOW) is False


def test_record_success_on_claude_fails_back_with_outage_minutes(conn, settings):
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in", call_id=3), kind="lookup", now=NOW)
    db.kv_set(conn, "claude.overloaded_streak", "2")
    db.kv_set(conn, "ai.claude.streak.timeout", "1")
    assert failover.record_success(conn, cfg, provider="fallback", kind="lookup", model_used="glm-4.7-flash-250914", now=plus(10)) is False
    assert kv(conn, "ai.active_provider") == "fallback" and kv(conn, "ai.fallback.model_seen") == "glm-4.7-flash-250914"
    assert kv(conn, "claude.overloaded_streak") == "2"  # a fallback success resets the fallback's streaks only
    assert failover.record_success(conn, cfg, provider="claude", kind="consolidate", model_used="claude-sonnet-4-5", now=plus(45), call_id=9) is True
    assert kv(conn, "ai.active_provider") == "claude" and kv(conn, "claude.paused_until") is None
    assert kv(conn, "claude.overloaded_streak") == "0" and kv(conn, "ai.claude.streak.timeout") == "0"
    assert kv(conn, "ai.failover.next_probe_at") is None and kv(conn, "ai.failover.probe_failures") is None
    fb = events(conn, "ai_failback")
    assert len(fb) == 1 and fb[0]["outage_min"] == 45 and fb[0]["call_id"] == 9 and fb[0]["probe_call_ids"] == [] and fb[0]["kind"] == "consolidate"
    assert failover.record_success(conn, cfg, provider="claude", kind="lookup", model_used=None, now=plus(46)) is False  # idempotent
    assert len(events(conn, "ai_failback")) == 1
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=plus(46)) == ("claude", None)


def test_record_success_lifts_an_unavailable_mark_and_resets_only_counting_streaks(conn, settings):
    cfg = auto_cfg(settings)
    db.kv_set(conn, "claude.available", "0")
    assert failover.record_success(conn, settings, provider="claude", kind="lookup", model_used="sonnet", now=NOW) is False
    assert kv(conn, "claude.available") == "1" and kv(conn, "claude.overloaded_streak") is None  # nothing was counting
    assert kv(conn, "ai.active_provider") is None
    assert failover.record_success(conn, cfg, provider="nonsense", kind="lookup", model_used=None, now=NOW) is False


# ---------------------------------------------------------------------------------------- maybe_probe
def test_maybe_probe_timing_backoff_and_failback(conn, settings):
    cfg = auto_cfg(settings)
    calls: list[str] = []

    def probe(ok: bool):
        def run():
            calls.append("probe")
            return SimpleNamespace(ok=ok, model_used="claude-sonnet-4-5", call_ids=[11, 12], error=None if ok else "tier 1: auth; tier 0: auth")

        return run

    assert failover.maybe_probe(conn, cfg, now=NOW, probe_claude=probe(True), force=True) is None  # active == claude
    assert failover.maybe_probe(conn, settings, now=NOW, probe_claude=probe(True), force=True) is None  # mode claude_cli
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    assert kv(conn, "ai.failover.next_probe_at") == plus(30)
    assert failover.maybe_probe(conn, cfg, now=plus(29), probe_claude=probe(False)) is None  # not due yet
    assert calls == []
    assert failover.maybe_probe(conn, cfg, now=plus(30), probe_claude=probe(False)) == "probe_failed"
    assert calls == ["probe"] and kv(conn, "ai.failover.probe_failures") == "1" and kv(conn, "ai.failover.next_probe_at") == plus(60)
    assert kv(conn, "ai.failover.last_probe_at") == plus(30) and kv(conn, "ai.active_provider") == "fallback"
    assert failover.maybe_probe(conn, cfg, now=plus(34), probe_claude=probe(False), force=True) is None  # within the grace of the last start
    assert failover.maybe_probe(conn, cfg, now=plus(35), probe_claude=probe(False), force=True) == "probe_failed"  # force ignores the schedule
    assert kv(conn, "ai.failover.probe_failures") == "2" and kv(conn, "ai.failover.next_probe_at") == plus(65)
    db.kv_set(conn, "ai.failover.probe_failures", "11")
    assert failover.maybe_probe(conn, cfg, now=plus(65), probe_claude=probe(False)) == "probe_failed"
    assert kv(conn, "ai.failover.probe_failures") == "12" and kv(conn, "ai.failover.next_probe_at") == plus(65 + 60)  # ×2 from 12 on
    db.kv_set(conn, "claude.enabled", "0")
    assert failover.maybe_probe(conn, cfg, now=plus(200), probe_claude=probe(True)) is None  # never under the kill switch
    db.kv_set(conn, "claude.enabled", "1")
    failover.set_manual_pause(conn, plus(300), now=plus(200))
    assert failover.maybe_probe(conn, cfg, now=plus(200), probe_claude=probe(True)) is None  # nor under the admin's pause
    db.kv_delete(conn, "ai.paused_until")
    assert failover.maybe_probe(conn, cfg, now=plus(200), probe_claude=probe(True)) == "failback"
    assert kv(conn, "ai.active_provider") == "claude" and kv(conn, "claude.paused_until") is None
    fb = events(conn, "ai_failback")
    assert len(fb) == 1 and fb[0]["probe_call_ids"] == [11, 12] and fb[0]["outage_min"] == 200 and fb[0]["kind"] == "probe"
    for key in ("ai.failover.next_probe_at", "ai.failover.probe_failures", "ai.failover.last_probe_at"):
        assert kv(conn, key) is None, key
    assert failover.maybe_probe(conn, cfg, now=plus(201), probe_claude=probe(True), force=True) is None  # back on claude: nothing to do


def test_maybe_probe_treats_a_raising_probe_as_failed_and_probes_a_paused_claude(conn, settings):
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    assert kv(conn, "claude.paused_until") == plus(30)

    def boom():
        raise OSError("claude binary vanished")

    assert failover.maybe_probe(conn, cfg, now=plus(1), probe_claude=boom, force=True) == "probe_failed"  # paused for auth: still probed
    assert kv(conn, "ai.failover.probe_failures") == "1" and kv(conn, "ai.failover.next_probe_at") == plus(31)
    db.kv_delete(conn, "ai.failover.next_probe_at")  # a restored backup without a schedule: due at once
    assert failover.maybe_probe(conn, cfg, now=plus(2), probe_claude=lambda: SimpleNamespace(ok=False, model_used=None, call_ids=[])) == "probe_failed"
    assert kv(conn, "ai.failover.probe_failures") == "2"


# ---------------------------------------------------------------------------------------------- admin
def test_manual_pause_and_clear_pauses(conn, settings):
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    rf(conn, cfg, provider="fallback", result=res("auth", "HTTP 401", provider="fallback"), kind="lookup", now=NOW)
    db.kv_set(conn, "claude.overloaded_streak", "4")
    db.kv_set(conn, "ai.fallback.streak.timeout", "1")
    db.kv_set(conn, "claude.enabled", "0")
    db.kv_set(conn, "ai.fallback.available", "0")  # a failed fallback probe during a vendor hiccup
    db.kv_set(conn, "claude.available", "1")  # the install probe passed: resume must not touch that
    failover.set_manual_pause(conn, plus(24 * 60), now=NOW)
    assert kv(conn, "ai.paused_until") == plus(24 * 60)
    assert budget.paused_until(conn, NOW) == plus(24 * 60)  # the legacy reader sees the global pause
    assert budget.can_spend(conn, "lookup", 1, 20, NOW, cfg=cfg, provider="fallback")[0] is False
    s = budget.spend_summary(conn, cfg, NOW)
    assert (s["paused_until"], s["manual_paused_until"], s["fallback_available"]) == (plus(24 * 60), plus(24 * 60), False)
    # groups parked at each pause instant, plus schedules that are none of failover's business
    at_global = park(conn, "generate_content", "content:1", plus(24 * 60))
    at_claude = park(conn, "lookup_word", "lookup:a", plus(30))
    at_fallback = park(conn, "consolidate_bank", "consolidate:1", plus(30))  # the fallback cooldown ends at the same instant here
    backoff = park(conn, "generate_content", "content:2", plus(2))  # an ordinary backoff / overload step
    budget_wait = park(conn, "generate_svg", "svg:1", budget.next_day_resume(NOW, cfg.tz))  # a budget deferral
    io_job = park(conn, "send_webhook", "webhook:1", plus(30))  # not an AI job
    running = park(conn, "lookup_word", "lookup:b", plus(30))
    conn.execute("UPDATE jobs SET status = 'running', locked_at = ?, locked_by = 'claude-1:x' WHERE id = ?", (NOW, running))
    with db.tx(conn):  # the router resumes inside its own transaction
        failover.clear_pauses(conn, now=plus(1))
    for key in ("ai.paused_until", "claude.paused_until", "ai.fallback.paused_until", "ai.failover.next_probe_at", "ai.failover.probe_failures", "ai.failover.last_probe_at"):
        assert kv(conn, key) is None, key
    assert kv(conn, "ai.active_provider") == "claude" and kv(conn, "claude.enabled") == "1"
    assert kv(conn, "claude.overloaded_streak") == "0" and kv(conn, "ai.fallback.streak.timeout") == "0"
    assert kv(conn, "ai.fallback.available") is None and kv(conn, "claude.available") == "1"  # the '0' mark is deleted, never set to '1'
    assert failover.fallback_eligible(conn, cfg, kind="lookup", priority=20, now=plus(1)) == (True, None)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=plus(1)) == ("claude", None)
    assert failover.availability(conn, cfg, kind="lookup", now=plus(1)).ok is True
    s = budget.spend_summary(conn, cfg, plus(1))
    assert (s["paused_until"], s["manual_paused_until"], s["fallback_available"]) == (None, None, None)
    # the parked groups run now; every other schedule keeps its run_after
    assert run_after(conn, at_global) == run_after(conn, at_claude) == run_after(conn, at_fallback) == plus(1)
    assert run_after(conn, backoff) == plus(2) and run_after(conn, budget_wait) == budget.next_day_resume(NOW, cfg.tz)
    assert run_after(conn, io_job) == plus(30) and run_after(conn, running) == plus(30)
    assert queue.get_job(conn, running).status == "running"
    # a '0' mark for the CLI (spawn_error earlier) goes the same way; an expired pause releases nothing
    db.kv_set(conn, "claude.available", "0")
    budget.set_paused_until(conn, plus(5), now=NOW)
    stale = park(conn, "lookup_word", "lookup:c", plus(5))
    failover.clear_pauses(conn, now=plus(6))
    assert kv(conn, "claude.available") is None and run_after(conn, stale) == plus(5)


def test_spend_summary_tells_the_manual_pause_from_the_automatic_one(conn, settings):
    cfg = auto_cfg(settings)
    s = budget.spend_summary(conn, cfg, NOW)
    assert s["manual_paused_until"] is None and s["fallback_available"] is None  # never probed
    for key in ("enabled", "paused_until", "flag_tier", "active_provider", "fallback_configured", "fallback_paused_until", "fallback_calls_today", "today_usd", "month_usd", "daily_budget_usd", "monthly_budget_usd", "svg_today_usd", "svg_daily_budget_usd", "calls_today", "avg_cost_per_word_7d", "last_error"):
        assert key in s, key
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)  # the CLI's automatic pause, fallback active
    s = budget.spend_summary(conn, cfg, NOW)
    assert (s["paused_until"], s["manual_paused_until"], s["active_provider"]) == (plus(30), None, "fallback")
    failover.set_manual_pause(conn, plus(10), now=NOW)
    s = budget.spend_summary(conn, cfg, NOW)
    assert (s["paused_until"], s["manual_paused_until"]) == (plus(30), plus(10))  # the legacy field keeps the later instant
    assert budget.spend_summary(conn, cfg, plus(11))["manual_paused_until"] is None  # elapsed
    db.kv_set(conn, "ai.fallback.available", "1")
    assert budget.spend_summary(conn, cfg, NOW)["fallback_available"] is True
    db.kv_set(conn, "ai.fallback.available", "0")
    assert budget.spend_summary(conn, cfg, NOW)["fallback_available"] is False
    assert budget.fallback_available(conn) is False


# ------------------------------------------------------------------------- a success lifts the pause
def test_success_lifts_the_providers_pause_in_every_mode_and_releases_the_parked_jobs(conn, settings):
    # claude_cli (the default): 402 → 24 h pause; the operator tops up and runs `wd claude-check` (a probe success)
    d = rf(conn, settings, provider="claude", result=res("auth", "balance: API Error: 402 insufficient balance"), kind="content", now=NOW)
    assert d == failover.Decision("pause", plus(24 * 60), None, None) and kv(conn, "ai.active_provider") is None
    content = park(conn, "generate_content", "content:1", plus(24 * 60))  # handle_failure parks the group at the pause end
    lookup = park(conn, "lookup_word", "lookup:a", plus(24 * 60))  # claude_call parks a refused group at resumes_at
    backoff = park(conn, "generate_content", "content:2", plus(10))
    assert failover.choose(conn, settings, kind="lookup", priority=20, now=plus(60)) == (None, plus(24 * 60))
    assert failover.record_success(conn, settings, provider="claude", kind="probe", model_used="sonnet", now=plus(60), probe_call_ids=[3]) is False  # no fail-back to report
    assert kv(conn, "claude.paused_until") is None and kv(conn, "ai.active_provider") is None and events(conn, "ai_failback") == []
    assert failover.choose(conn, settings, kind="lookup", priority=20, now=plus(60)) == ("claude", None)
    assert budget.can_spend(conn, "content", 1, 20, plus(60), cfg=settings) == (True, None)
    assert run_after(conn, content) == run_after(conn, lookup) == plus(60) and run_after(conn, backoff) == plus(10)
    # an ordinary call is proof as well; the manual (global) pause is the admin's and stays
    budget.set_paused_until(conn, plus(90), now=plus(61))
    failover.set_manual_pause(conn, plus(120), now=plus(61))
    assert failover.record_success(conn, settings, provider="claude", kind="lookup", model_used="sonnet", now=plus(62)) is False
    assert kv(conn, "claude.paused_until") is None and kv(conn, "ai.paused_until") == plus(120)
    # the fallback's own pause goes the same way on a fallback success (openai_http mode: a probe after the key was fixed)
    http = auto_cfg(settings, ai_provider="openai_http")
    rf(conn, http, provider="fallback", result=res("spawn_error", "not_found: HTTP 404: model not found", provider="fallback"), kind="lookup", now=plus(200))
    assert kv(conn, "ai.fallback.paused_until") == plus(230) and kv(conn, "ai.fallback.available") == "0"
    parked = park(conn, "consolidate_bank", "consolidate:1", plus(230))
    assert failover.record_success(conn, http, provider="fallback", kind="probe", model_used="glm-4.7-flash", now=plus(201)) is False
    assert kv(conn, "ai.fallback.paused_until") is None and kv(conn, "ai.fallback.available") == "1"
    assert failover.choose(conn, http, kind="lookup", priority=20, now=plus(201)) == ("fallback", None)
    assert run_after(conn, parked) == plus(201)


def test_failback_releases_the_jobs_parked_at_the_claude_pause(conn, settings):
    cfg = auto_cfg(settings)
    d = rf(conn, cfg, provider="claude", result=res("auth", "balance: API Error: 402 insufficient balance"), kind="content", now=NOW)
    assert d.action == "switch" and kv(conn, "ai.active_provider") == "fallback" and kv(conn, "claude.paused_until") == plus(24 * 60)
    content = park(conn, "generate_content", "content:1", plus(24 * 60))  # a content group parked at the CLI pause (a prewarm group, or content removed from the kinds)
    prewarm = park(conn, "prewarm_plan", "prewarm:1", plus(24 * 60))
    backoff = park(conn, "lookup_word", "lookup:a", plus(2))  # a lookup that failed on the fallback: its own backoff
    assert failover.record_success(conn, cfg, provider="claude", kind="probe", model_used="sonnet", now=plus(60), probe_call_ids=[5]) is True
    assert kv(conn, "ai.active_provider") == "claude" and kv(conn, "claude.paused_until") is None
    assert events(conn, "ai_failback")[0]["probe_call_ids"] == [5]
    assert run_after(conn, content) == run_after(conn, prewarm) == plus(60) and run_after(conn, backoff) == plus(2)
    assert failover.choose(conn, cfg, kind="content", priority=20, now=plus(60)) == ("claude", None)
    # nothing is left at that instant (and None / '' horizons are ignored): a second lift releases nothing, a second success is no fail-back
    assert failover._release_parked(conn, (plus(24 * 60), None, ""), now=plus(61)) == 0
    assert failover.record_success(conn, cfg, provider="claude", kind="lookup", model_used="sonnet", now=plus(61)) is False


# --------------------------------------------------------------------------------------- notifications
def test_notify_skipped_without_admin_webhook_and_under_smoke_mock(conn, settings, monkeypatch):
    captured = Captured().install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False)
    failover.notify(conn, live, "failover", {"reason": "auth"}, now=NOW)  # no admin at all
    make_admin(conn, "viewer", role="user")  # an ordinary user's webhook does not count
    make_admin(conn, "quiet", enabled=0)  # an admin with the channel off
    make_admin(conn, "blank", url="")
    failover.notify(conn, live, "failover", {"reason": "auth"}, now=NOW)
    assert captured.requests == [] and kv(conn, "ai.notify.failover.last_at") is None
    make_admin(conn, "root")
    failover.notify(conn, auto_cfg(settings), "failover", {"reason": "auth"}, now=NOW)  # WD_SMOKE_MOCK_HTTP=1 in the test env
    assert captured.requests == [] and kv(conn, "ai.notify.failover.last_at") is None


def test_failover_and_failback_notify_admins_once_per_hour(conn, settings, monkeypatch):
    captured = Captured().install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False)
    make_admin(conn, "root", fmt="wecom")
    make_admin(conn, "second", url="https://open.feishu.cn/open-apis/bot/v2/hook/abc", fmt="feishu")
    d = rf(conn, live, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    assert d.event == "ai_failover"
    assert len(captured.requests) == 2 and kv(conn, "ai.notify.failover.last_at") == NOW
    assert all(r.headers["Host"] in ("qyapi.weixin.qq.com", "open.feishu.cn") for r in captured.requests)
    wecom, feishu = captured.bodies()
    assert wecom["msgtype"] == "text" and "已切换到备用模型" in wecom["text"]["content"] and "glm-4.7-flash" in wecom["text"]["content"]
    assert feishu["msg_type"] == "text" and "auth" in feishu["content"]["text"]
    # a second switch within the hour is not re-sent (fail back, then fail over again); every send goes to both admins
    assert failover.record_success(conn, live, provider="claude", kind="lookup", model_used="sonnet", now=plus(10)) is True
    assert len(captured.requests) == 4 and kv(conn, "ai.notify.failback.last_at") == plus(10)
    assert "已切回 Claude" in captured.bodies()[2]["text"]["content"] and "10 分钟" in captured.bodies()[2]["text"]["content"]
    rf(conn, live, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(40))
    assert len(captured.requests) == 4
    failover.record_success(conn, live, provider="claude", kind="lookup", model_used="sonnet", now=plus(50))
    assert len(captured.requests) == 4
    rf(conn, live, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(61))
    assert len(captured.requests) == 6  # both admins again after the hour
    assert len(events(conn, "ai_failover")) == 3  # events are never deduped, only notifications


def test_both_providers_down_notifies_and_failures_in_notify_are_swallowed(conn, settings, monkeypatch):
    captured = Captured(status=500).install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False)
    make_admin(conn, "root", fmt="generic")
    rf(conn, live, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    assert len(captured.requests) == 1  # HTTP 500 from the endpoint is reported, not raised
    d = rf(conn, live, provider="fallback", result=res("auth", "HTTP 401", provider="fallback"), kind="lookup", now=plus(1))
    assert d == failover.Decision("pause", plus(31), None, None)
    assert len(captured.requests) == 2
    body = captured.bodies()[1]
    assert body["type"] == "ai_both_paused" and body["title"] == "word-Dance：AI 暂时不可用" and body["url"] is None and body["date"] == "2026-10-14"
    assert "08:30" in body["body"] and "08:31" in body["body"]  # local (Asia/Shanghai) clock times
    assert kv(conn, "ai.notify.both_paused.last_at") == plus(1)

    def explode(*a, **k):
        raise RuntimeError("webhook module broke")

    monkeypatch.setattr(webhook, "safe_post", explode)
    db.kv_delete(conn, "ai.notify.failback.last_at")
    assert failover.record_success(conn, live, provider="claude", kind="lookup", model_used="sonnet", now=plus(2)) is True  # still fails back
    assert kv(conn, "ai.active_provider") == "claude" and len(events(conn, "ai_failback")) == 1


def test_notification_text_shapes(settings):
    cfg = auto_cfg(settings)
    title, body = failover.notification_text("failover", {"reason": "balance", "error": "402 insufficient balance"}, cfg)
    assert title == "word-Dance：AI 已切换到备用模型" and "balance" in body and "30 分钟" in body
    _, body = failover.notification_text("failover", {"reason": "balance", "error": "balance: API Error: 402 insufficient balance"}, cfg)
    assert "（balance：API Error: 402 insufficient balance）" in body and "balance: " not in body  # the prefix is named once
    _, body = failover.notification_text("failover", {"reason": "network", "error": "network: ConnectError: fetch failed"}, cfg)
    assert "（network：ConnectError: fetch failed）" in body
    _, body = failover.notification_text("failover", {"reason": "auth", "error": "exit 1: not logged in"}, cfg)
    assert "（auth：exit 1: not logged in）" in body  # an unknown prefix is kept
    _, body = failover.notification_text("both_paused", {"reason": "auth", "claude_paused_until": plus(30), "fallback_paused_until": None, "fallback_unavailable": True}, cfg)
    assert "Claude 暂停至 10-14 08:30" in body and "备用模型不可用（等待探测恢复）" in body
    _, body = failover.notification_text("both_paused", {"reason": "auth", "claude_paused_until": plus(30), "fallback_paused_until": plus(40)}, cfg)
    assert "备用模型暂停至 10-14 08:40" in body
    title, body = failover.notification_text("failback", {"outage_min": None}, cfg)
    assert title == "word-Dance：AI 已切回 Claude" and body == "Claude 已恢复，已切回主模型。"
    title, body = failover.notification_text("other", {"x": 1}, cfg)
    assert title == "word-Dance：AI other" and body == '{"x": 1}'


# ------------------------------------------------------------------------------------ review follow-ups
def test_priority_is_required_and_gates_the_prewarm_rerun(conn, settings):
    cfg = auto_cfg(settings)
    with pytest.raises(TypeError):
        failover.record_failure(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)  # type: ignore[call-arg]
    assert kv(conn, "claude.paused_until") is None  # nothing happened
    d = rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW, priority=90)
    assert d == failover.Decision("switch", plus(30), None, "ai_failover")  # the outage switches; a prewarm group reruns only with the flag
    d = rf(conn, auto_cfg(settings, ai_fallback_prewarm=True), provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW, priority=90)
    assert d == failover.Decision("switch", plus(30), "fallback", None)
    d = rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW, priority=89)
    assert d.retry_provider == "fallback"


def test_soft_threshold_on_a_non_routable_kind_does_not_flip(conn, settings, monkeypatch):
    """Content removed from ``WD_AI_FALLBACK_KINDS`` (the operator keeps example generation on the CLI): a content streak
    must not flip — the next content success would fail back and the providers would flap."""
    captured = Captured().install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False, ai_fallback_kinds=("lookup", "consolidate"))
    make_admin(conn, "root")
    for i in (1, 2, 3):
        d = rf(conn, live, provider="claude", result=res("overloaded", "529"), kind="content", now=NOW)
        assert d == failover.Decision("none", None, None, None) and kv(conn, "claude.overloaded_streak") == str(i)
    assert kv(conn, "ai.active_provider") is None and events(conn, "ai_failover") == [] and captured.requests == []
    # the next content success has nothing to fail back from: no flapping between the providers
    assert failover.record_success(conn, live, provider="claude", kind="content", model_used="sonnet", now=plus(1)) is False
    assert events(conn, "ai_failback") == [] and captured.requests == [] and kv(conn, "claude.overloaded_streak") == "0"
    for _ in (1, 2):
        rf(conn, live, provider="claude", result=res("overloaded", "529"), kind="content", now=plus(2))
    d = rf(conn, live, provider="claude", result=res("overloaded", "529"), kind="lookup", now=plus(2))  # the streak reached on a routable kind switches
    assert d == failover.Decision("switch", None, "fallback", "ai_failover") and kv(conn, "ai.failover.reason") == "overloaded"
    assert len(events(conn, "ai_failover")) == 1 and len(captured.requests) == 1
    # a hard trigger on content still switches (the CLI as such is down) — the widened rule is kept for hard triggers
    db.kv_set(conn, "ai.active_provider", "claude")
    d = rf(conn, live, provider="claude", result=res("auth", "not logged in"), kind="content", now=plus(3))
    assert d == failover.Decision("switch", plus(33), None, "ai_failover") and len(events(conn, "ai_failover")) == 2


def test_soft_threshold_on_content_flips_by_default(conn, settings):
    """Slice 2: content is routable by default, so a content streak switches (and reruns the group there) like any other kind."""
    cfg = auto_cfg(settings)
    for _ in (1, 2):
        assert rf(conn, cfg, provider="claude", result=res("overloaded", "529"), kind="content", now=NOW).action == "none"
    d = rf(conn, cfg, provider="claude", result=res("overloaded", "529"), kind="content", now=NOW)
    assert d == failover.Decision("switch", None, "fallback", "ai_failover")
    assert kv(conn, "ai.active_provider") == "fallback" and kv(conn, "ai.failover.reason") == "overloaded" and events(conn, "ai_failover")[0]["kind"] == "content"
    assert rf(conn, cfg, provider="claude", result=res("overloaded", "529"), kind="content", now=NOW, priority=90).retry_provider is None  # a prewarm group still waits


def test_forced_probes_from_sibling_workers_run_once(conn, settings, connect):
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    calls: list[str] = []

    def probe():
        calls.append("probe")
        return SimpleNamespace(ok=False, model_used=None, call_ids=[])

    other = connect()
    try:
        assert failover.maybe_probe(conn, cfg, now=plus(5), probe_claude=probe, force=True) == "probe_failed"  # worker 1's start-up probe
        assert failover.maybe_probe(other, cfg, now=plus(5), probe_claude=probe, force=True) is None  # worker 2 and 3 see it running / just run
        assert failover.maybe_probe(other, cfg, now=plus(9), probe_claude=probe, force=True) is None
    finally:
        other.close()
    assert calls == ["probe"] and kv(conn, "ai.failover.probe_failures") == "1" and kv(conn, "ai.failover.next_probe_at") == plus(35)
    assert kv(conn, "ai.failover.last_probe_at") == plus(5)
    assert failover.maybe_probe(conn, cfg, now=plus(10), probe_claude=probe, force=True) == "probe_failed"  # five minutes on: a real restart probes again
    assert calls == ["probe", "probe"] and kv(conn, "ai.failover.probe_failures") == "2"
    db.kv_set(conn, "ai.failover.last_probe_at", "garbage")
    assert failover.maybe_probe(conn, cfg, now=plus(11), probe_claude=probe, force=True) == "probe_failed"  # garbage counts as no start


def test_probe_success_after_a_concurrent_failback_reports_nothing(conn, settings):
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)

    def probe():
        # a successful claude call on another worker flips back while the probe is still running
        assert failover.record_success(conn, cfg, provider="claude", kind="lookup", model_used="sonnet", now=plus(31), call_id=4) is True
        return SimpleNamespace(ok=True, model_used="sonnet", call_ids=[7])

    assert failover.maybe_probe(conn, cfg, now=plus(30), probe_claude=probe) is None
    fb = events(conn, "ai_failback")
    assert len(fb) == 1 and fb[0]["call_id"] == 4 and kv(conn, "ai.active_provider") == "claude"
    for key in ("ai.failover.next_probe_at", "ai.failover.probe_failures", "ai.failover.last_probe_at"):
        assert kv(conn, key) is None, key  # the claim this call made does not outlive the fail-back


def test_notify_is_skipped_inside_an_open_transaction(conn, settings, monkeypatch, caplog):
    captured = Captured().install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False)
    make_admin(conn, "root")
    with caplog.at_level("WARNING", logger="wd.ai.failover"):
        with db.tx(conn):
            d = rf(conn, live, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    assert d.event == "ai_failover" and kv(conn, "ai.active_provider") == "fallback"  # the state change is not affected
    assert captured.requests == [] and kv(conn, "ai.notify.failover.last_at") is None  # nothing posted under the write lock
    assert any("skipped inside an open transaction" in r.getMessage() for r in caplog.records)
    assert failover.record_success(conn, live, provider="claude", kind="lookup", model_used="sonnet", now=plus(5)) is True
    assert len(captured.requests) == 1 and json.loads(captured.requests[0].content)["text"]["content"].count("Claude 已恢复") == 1


def test_garbage_counters_count_as_zero(conn, settings):
    cfg = auto_cfg(settings)
    assert (failover._int(None), failover._int("7"), failover._int(" 3 ", 9), failover._int("x", 9), failover._int("")) == (0, 7, 3, 9, 0)
    db.kv_set(conn, "claude.overloaded_streak", "many")
    assert rf(conn, cfg, provider="claude", result=res("overloaded", "529"), kind="lookup", now=NOW).action == "none"
    assert kv(conn, "claude.overloaded_streak") == "1"
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    db.kv_set(conn, "ai.failover.probe_failures", "")
    assert failover.maybe_probe(conn, cfg, now=plus(30), probe_claude=lambda: SimpleNamespace(ok=False, model_used=None, call_ids=[])) == "probe_failed"
    assert kv(conn, "ai.failover.probe_failures") == "1"


# ------------------------------------------------------------------------- claim size while the fallback takes content (slice 2)
def content_job(conn, key: int, *, priority: int = 20, run_after: str | None = None, now: str = NOW) -> int:
    return queue.enqueue(conn, "generate_content", {"word_id": key}, dedupe_key=f"content:{key}", priority=priority, run_after=run_after, now=now)


def test_group_cap_is_the_fallback_content_batch(settings):
    """AI_FALLBACK_MODEL §4.2 "切换期间：例句批大小 5": the fallback takes content in groups of min(WD_AI_BATCH_SIZE, WD_AI_FALLBACK_BATCH_SIZE)."""
    cfg = auto_cfg(settings)
    assert failover.group_cap(cfg, "content", "fallback") == 5  # min(10, 5)
    assert failover.group_cap(auto_cfg(settings, ai_batch_size=3), "content", "fallback") == 3  # the CLI batch is the ceiling
    assert failover.group_cap(auto_cfg(settings, ai_fallback_batch_size=8), "content", "fallback") == 8
    assert failover.group_cap(auto_cfg(settings, ai_fallback_batch_size=12, ai_batch_size=12), "content", "fallback") == 12
    assert failover.group_cap(auto_cfg(settings, ai_fallback_batch_size=1), "content", "fallback") == 1
    assert failover.group_cap(cfg, "content", "claude") is None  # the CLI keeps WD_AI_BATCH_SIZE
    assert failover.group_cap(cfg, "lookup", "fallback") is None  # lookups keep their 20
    assert failover.group_cap(cfg, "consolidate", "fallback") is None and failover.group_cap(cfg, "svg", "fallback") is None


def test_claim_limit_shrinks_content_claims_while_the_fallback_takes_them(conn, settings):
    """CLAUDE_INTEGRATION §10.5: ``worker.process_next`` claims through ``failover.claim_limit`` — ``queue.limit_for`` unless the
    provider that would take the head content group now is the fallback, then ``group_cap``."""
    cfg = auto_cfg(settings)
    content_job(conn, 1)
    assert failover.claim_limit(conn, settings, "generate_content", now=NOW) == 10  # claude_cli: queue.limit_for
    assert failover.claim_limit(conn, cfg, "generate_content", now=NOW) == 10  # auto, claude active and free
    db.kv_set(conn, "ai.active_provider", "fallback")
    budget.set_paused_until(conn, plus(30), now=NOW)
    assert failover.claim_limit(conn, cfg, "generate_content", now=NOW) == 5  # the head group would run on the fallback
    assert failover.claim_limit(conn, auto_cfg(settings, ai_fallback_batch_size=3), "generate_content", now=NOW) == 3
    assert failover.claim_limit(conn, auto_cfg(settings, ai_batch_size=4), "generate_content", now=NOW) == 4  # min with the CLI batch
    assert failover.claim_limit(conn, cfg, "lookup_word", now=NOW) == 20  # the other types keep their claim size
    assert failover.claim_limit(conn, cfg, "consolidate_bank", now=NOW) == 1 and failover.claim_limit(conn, cfg, "generate_svg", now=NOW) == 1
    assert failover.claim_limit(conn, auto_cfg(settings, ai_provider="openai_http"), "generate_content", now=NOW) == 5  # openai_http: always the fallback
    # a prewarm head (priority ≥ 90) may not use the fallback without WD_AI_FALLBACK_PREWARM: the plain limit (the group is deferred later)
    conn.execute("UPDATE jobs SET priority = 90")
    assert failover.claim_limit(conn, cfg, "generate_content", now=NOW) == 10
    assert failover.claim_limit(conn, auto_cfg(settings, ai_fallback_prewarm=True), "generate_content", now=NOW) == 5
    # the head is the first RUNNABLE content job in queue order: a p20 job ahead of the p90 one decides, a job scheduled later does not
    content_job(conn, 2, run_after=plus(5))
    assert failover.claim_limit(conn, cfg, "generate_content", now=NOW) == 10
    assert failover.claim_limit(conn, cfg, "generate_content", now=plus(5)) == 5
    # no queued content job at all: priority 20 is assumed (the claim that follows finds nothing anyway)
    conn.execute("DELETE FROM jobs")
    assert failover.claim_limit(conn, cfg, "generate_content", now=NOW) == 5
    # content removed from the kinds, or the fallback paused: the CLI (or nobody) takes the head group → the plain limit
    assert failover.claim_limit(conn, auto_cfg(settings, ai_fallback_kinds=("lookup", "consolidate")), "generate_content", now=NOW) == 10
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)
    assert failover.claim_limit(conn, cfg, "generate_content", now=NOW) == 10
    assert failover.claim_limit(conn, cfg, "generate_content", now=plus(11)) == 5  # the fallback pause elapsed


# ----------------------------------------------------------------------------------- fallback quality streak (slice 2)
def test_is_quality_failure():
    """§4.2 row ``invalid_output`` / 内容过滤: an answer that arrived but was unusable — never a switch trigger."""
    assert failover.is_quality_failure(res("invalid_output", None, provider="fallback"))
    assert failover.is_quality_failure(res("invalid_output", "word mismatch", provider="claude"))  # the status decides; the provider is record_failure's business
    for error in ("schema: items is a required property", "content_filter: HTTP 400: data_inspection_failed", "truncated: finish_reason=length", "invalid_json: no object"):
        assert failover.is_quality_failure(res("error", error, provider="fallback")), error
        assert failover.classify(res("error", error, provider="fallback")) == ("never", None), error
    for result in (res("error", "exit 1: boom"), res("error", "network: ConnectError"), res("overloaded", "HTTP 429"), res("timeout", "timeout after 180s"), res("budget", None), res("auth", "HTTP 401"), res("success", None, ok=True)):
        assert not failover.is_quality_failure(result), result


def test_fallback_quality_streak_pauses_the_fallback_after_three_unusable_answers(conn, settings, monkeypatch):
    captured = Captured().install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False)
    make_admin(conn, "root")
    db.kv_set(conn, "ai.active_provider", "fallback")
    budget.set_paused_until(conn, plus(30), now=NOW)  # the CLI is down: the fallback carries the content jobs
    miss = "schema: items[0]: 'meaning_zh' is a required property"
    for i in (1, 2):
        d = rf(conn, live, provider="fallback", result=res("error", miss, provider="fallback", call_id=i), kind="content", now=NOW)
        assert d == failover.Decision("none", None, None, None)
        assert kv(conn, "ai.fallback.streak.invalid") == str(i) and kv(conn, "ai.fallback.paused_until") is None
    d = rf(conn, live, provider="fallback", result=res("error", miss, provider="fallback", call_id=3), kind="content", now=NOW)
    assert d == failover.Decision("pause", plus(30), None, None)  # the cooldown; an invalid group is never rerun on the other provider
    assert kv(conn, "ai.fallback.paused_until") == plus(30) and kv(conn, "ai.fallback.streak.invalid") == "0"
    assert kv(conn, "ai.active_provider") == "fallback" and kv(conn, "claude.paused_until") == plus(30)  # no flip, nothing written for claude
    quality = events(conn, "ai_fallback_quality")
    assert quality == [{"consecutive": 3, "kind": "content", "status": "error", "error": miss, "call_id": 3, "paused_until": plus(30), "model_seen": None}]
    assert events(conn, "ai_fallback_paused") == [] and events(conn, "ai_failover") == [] and events(conn, "claude_auth") == []
    assert failover.choose(conn, live, kind="content", priority=20, now=NOW) == (None, plus(30))  # both paused now
    assert failover.choose(conn, live, kind="content", priority=20, now=plus(31)) == ("fallback", None)  # the quality pause elapses like any pause
    # the admins hear about it (once per hour), with Claude's state in the body
    assert len(captured.requests) == 1 and kv(conn, "ai.notify.fallback_quality.last_at") == NOW
    text = captured.bodies()[0]["text"]["content"]
    assert "备用模型输出异常" in text and "glm-4.7-flash 连续 3 次" in text and "Claude 暂停至 10-14 08:30" in text
    # the error is cut at 300 characters in the event; the model actually answering is remembered when known
    db.kv_set(conn, "ai.fallback.model_seen", "glm-4.7-flash-250914")
    for i in (4, 5, 6):
        d = rf(conn, live, provider="fallback", result=res("error", "truncated: " + "x" * 400, provider="fallback", call_id=i), kind="lookup", now=plus(40))
    assert d.action == "pause" and d.paused_until == plus(70) and len(captured.requests) == 1  # deduped within the hour
    last = events(conn, "ai_fallback_quality")[-1]
    assert len(last["error"]) == 300 and last["model_seen"] == "glm-4.7-flash-250914" and last["kind"] == "lookup"


def test_quality_streak_counting_rules(conn, settings):
    cfg = auto_cfg(settings)
    schema_miss = res("error", "schema: 2 errors", provider="fallback")
    # invalid_output (the handler rejected every item) and content_filter: count; overloaded / budget / a plain error do not touch the streak
    assert rf(conn, cfg, provider="fallback", result=res("invalid_output", "word mismatch", provider="fallback"), kind="lookup", now=NOW).action == "none"
    assert kv(conn, "ai.fallback.streak.invalid") == "1"
    assert rf(conn, cfg, provider="fallback", result=res("error", "content_filter: HTTP 400: data_inspection_failed", provider="fallback"), kind="content", now=NOW).action == "none"
    assert kv(conn, "ai.fallback.streak.invalid") == "2"
    assert rf(conn, cfg, provider="fallback", result=res("overloaded", "HTTP 429", provider="fallback"), kind="content", now=NOW).action == "none"
    assert rf(conn, cfg, provider="fallback", result=res("budget", "max budget", provider="fallback"), kind="content", now=NOW).action == "none"
    assert rf(conn, cfg, provider="fallback", result=res("error", "exit 1: boom", provider="fallback"), kind="content", now=NOW).action == "none"
    assert kv(conn, "ai.fallback.streak.invalid") == "2" and kv(conn, "ai.fallback.streak.overloaded") == "1"
    # the same results on claude never count — in every mode
    for result in (res("invalid_output"), res("error", "schema: 2 errors"), res("error", "truncated: finish_reason=length"), res("error", "content_filter: x")):
        assert rf(conn, cfg, provider="claude", result=result, kind="content", now=NOW) == failover.Decision("none", None, None, None)
        assert rf(conn, settings, provider="claude", result=result, kind="content", now=NOW) == failover.Decision("none", None, None, None)
    assert kv(conn, "ai.fallback.streak.invalid") == "2" and events(conn, "ai_fallback_quality") == []
    # an HTTP-ok fallback answer does NOT reset it (the handler may still reject every item) …
    assert failover.record_success(conn, cfg, provider="fallback", kind="content", model_used="glm-4.7-flash", now=NOW) is False
    assert kv(conn, "ai.fallback.streak.invalid") == "2" and kv(conn, "ai.fallback.streak.overloaded") == "0"
    # … an applied fallback group does; claude's applied groups are no business of the fallback's streak
    failover.record_quality_success(conn, provider="claude", now=NOW)
    assert kv(conn, "ai.fallback.streak.invalid") == "2"
    failover.record_quality_success(conn, provider="fallback", now=NOW)
    assert kv(conn, "ai.fallback.streak.invalid") == "0"
    assert rf(conn, cfg, provider="fallback", result=schema_miss, kind="content", now=NOW).action == "none" and kv(conn, "ai.fallback.streak.invalid") == "1"
    # the admin's resume resets it too …
    failover.clear_pauses(conn, now=NOW)
    assert kv(conn, "ai.fallback.streak.invalid") == "0"
    for _ in range(3):
        d = rf(conn, cfg, provider="fallback", result=schema_miss, kind="content", now=plus(1))
    assert d.action == "pause" and kv(conn, "ai.fallback.paused_until") == plus(31)
    # … and the quality pause is lifted like any fallback pause: a fallback success (a probe after the vendor fixed the model) or the resume
    assert failover.record_success(conn, cfg, provider="fallback", kind="probe", model_used="glm-4.7-flash", now=plus(2)) is False
    assert kv(conn, "ai.fallback.paused_until") is None and failover.choose(conn, cfg, kind="content", priority=20, now=plus(2)) == ("claude", None)
    # a counting streak in openai_http mode pauses the only provider there is
    http = auto_cfg(settings, ai_provider="openai_http")
    for _ in range(3):
        d = rf(conn, http, provider="fallback", result=schema_miss, kind="content", now=plus(3))
    assert d == failover.Decision("pause", plus(33), None, None) and failover.choose(conn, http, kind="content", priority=20, now=plus(3)) == (None, plus(33))


def test_notification_text_for_the_quality_pause(settings):
    cfg = auto_cfg(settings)
    detail = {"consecutive": 3, "kind": "content", "status": "error", "error": "schema: items[0]: 'meaning_zh' is a required property", "paused_until": plus(30), "claude_paused_until": None}
    title, body = failover.notification_text("fallback_quality", detail, cfg)
    assert title == "word-Dance：备用模型输出异常，已暂停"
    assert body == "备用模型 glm-4.7-flash 连续 3 次返回无效结果（content：schema: items[0]: 'meaning_zh' is a required property），已暂停至 10-14 08:30。Claude 正常，任务已切回 Claude。"
    _, body = failover.notification_text("fallback_quality", {**detail, "claude_paused_until": plus(45)}, cfg)
    assert body.endswith("已暂停至 10-14 08:30。Claude 暂停至 10-14 08:45，任务排队等待。")
    _, body = failover.notification_text("fallback_quality", {**detail, "error": "content_filter: " + "x" * 200}, cfg)
    assert "（content：content_filter: " + "x" * 144 + "）" in body  # the error keeps its prefix (it is the information) and is cut at 160 characters
    # openai_http: the CLI is never spawned, so the jobs wait for the fallback whatever Claude's state
    _, body = failover.notification_text("fallback_quality", detail, auto_cfg(settings, ai_provider="openai_http"))
    assert body.endswith("已暂停至 10-14 08:30。当前为仅备用模式，任务排队等待备用模型恢复。")
    # an expired claude pause is not a healthy Claude: while the sticky state still names the fallback, or after a failed
    # probe (claude.available '0'), the body says so instead of 「Claude 正常」; a claude pause still wins over that
    unknown = "Claude 状态未知（上次探测或调用失败），任务将先尝试 Claude，失败则排队等待。"
    assert failover.notification_text("fallback_quality", {**detail, "active": "fallback", "claude_available": None}, cfg)[1].endswith(unknown)
    assert failover.notification_text("fallback_quality", {**detail, "active": "claude", "claude_available": "0"}, cfg)[1].endswith(unknown)
    assert failover.notification_text("fallback_quality", {**detail, "active": "claude", "claude_available": "1"}, cfg)[1].endswith("Claude 正常，任务已切回 Claude。")
    assert failover.notification_text("fallback_quality", {**detail, "active": "fallback", "claude_paused_until": plus(45)}, cfg)[1].endswith("Claude 暂停至 10-14 08:45，任务排队等待。")
    assert failover.notification_text("fallback_quality", {**detail, "active": "fallback"}, auto_cfg(settings, ai_provider="openai_http"))[1].endswith("当前为仅备用模式，任务排队等待备用模型恢复。")


# ------------------------------------------------------------------------------------ fail-back requeue (slice 2, §4.5 死词)
def dead_job(conn, type_: str, key: str, finished_at: str, *, now: str = NOW) -> int:
    """A job that went ``dead`` at ``finished_at`` (three attempts, bisected down to a group of 2)."""
    job_id = queue.enqueue(conn, type_, {"k": key}, dedupe_key=key, priority=20, now=now)
    conn.execute(
        "UPDATE jobs SET status = 'dead', attempts = 3, finished_at = ?, last_error = 'error: schema: x', payload_json = json_set(payload_json, '$.group_size', 2) WHERE id = ?",
        (finished_at, job_id),
    )
    return job_id


def test_failback_requeues_the_content_and_lookup_jobs_that_died_during_the_outage(conn, settings):
    """§10.6: the casualties of the outage come back queued without a ``group_size`` (they batch like fresh claims), a dead
    row whose key is live again is no candidate wherever it sorts, and the fail-back ends the episode bookkeeping."""
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in", call_id=3), kind="lookup", now=NOW)
    assert kv(conn, "ai.failover.since") == NOW
    held_first = dead_job(conn, "lookup_word", "lookup:held", NOW)  # the earliest row of all, its key live again: not a candidate
    live_first = queue.enqueue(conn, "lookup_word", {"k": "lookup:held"}, dedupe_key="lookup:held", priority=20, now=plus(1))
    before = dead_job(conn, "generate_content", "content:old", plus(-5))  # died before the outage: the nightly requeue's business
    c1 = dead_job(conn, "generate_content", "content:1", NOW)  # finished_at == since counts
    c2 = dead_job(conn, "generate_content", "content:2", plus(10))
    lk = dead_job(conn, "lookup_word", "lookup:a", plus(12))
    svg = dead_job(conn, "generate_svg", "svg:1", plus(12))  # not a fail-back type
    held = dead_job(conn, "generate_content", "content:3", plus(15))
    live = queue.enqueue(conn, "generate_content", {"k": "content:3"}, dedupe_key="content:3", priority=20, now=plus(16))  # the key is live again: the dead row is skipped
    done = queue.enqueue(conn, "generate_content", {"k": "content:4"}, dedupe_key="content:4", priority=20, now=NOW)
    queue.finish(conn, done, {"ok": 1}, now=plus(20))
    assert failover.record_success(conn, cfg, provider="claude", kind="probe", model_used="sonnet", now=plus(31), probe_call_ids=[7]) is True
    fb = events(conn, "ai_failback")
    assert len(fb) == 1 and fb[0]["requeued_dead"] == 3 and fb[0]["since"] == NOW and fb[0]["probe_call_ids"] == [7]
    assert kv(conn, "ai.active_provider") == "claude" and kv(conn, "claude.paused_until") is None
    for key in (*failover.FAILOVER_KEYS, *failover.PROBE_KEYS):
        assert kv(conn, key) is None, key  # the episode is over: since / reason / trigger go with the probe schedule (the detail kept since)
    for job_id in (c1, c2, lk):
        job = queue.get_job(conn, job_id)
        assert (job.status, job.attempts, job.run_after, job.finished_at, job.locked_by) == ("queued", 0, plus(31), None, None), job_id
        assert "group_size" not in job.payload, job_id  # the bisection mark (2) went too: the revived jobs batch like fresh claims
    for job_id in (before, svg, held, held_first):
        assert queue.get_job(conn, job_id).status == "dead", job_id
    assert queue.get_job(conn, live).status == "queued" and queue.get_job(conn, live_first).status == "queued" and queue.get_job(conn, done).status == "done"
    # a later outage without casualties: the detail says 0, the bookkeeping ends again
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(40))
    assert kv(conn, "ai.failover.since") == plus(40)
    assert failover.record_success(conn, cfg, provider="claude", kind="lookup", model_used="sonnet", now=plus(50)) is True
    assert events(conn, "ai_failback")[1]["requeued_dead"] == 0 and kv(conn, "ai.failover.since") is None


def test_clear_pauses_requeues_the_outage_dead_jobs_only_when_the_fallback_was_active(conn, settings):
    cfg = auto_cfg(settings)
    # no outage: the admin's resume leaves dead jobs to the nightly requeue
    stale = dead_job(conn, "generate_content", "content:stale", NOW)
    failover.clear_pauses(conn, now=plus(1))
    assert queue.get_job(conn, stale).status == "dead"
    # an outage with the fallback active: the resume requeues what died since it began (the claude_resumed event stays the router's)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(2))
    died = dead_job(conn, "lookup_word", "lookup:x", plus(3))
    with db.tx(conn):  # the router resumes inside its own transaction
        failover.clear_pauses(conn, now=plus(5))
    job = queue.get_job(conn, died)
    assert (job.status, job.attempts, job.run_after) == ("queued", 0, plus(5)) and "group_size" not in job.payload
    assert queue.get_job(conn, stale).status == "dead"  # died before ai.failover.since
    assert kv(conn, "ai.active_provider") == "claude" and events(conn, "ai_failback") == []
    for key in (*failover.FAILOVER_KEYS, *failover.PROBE_KEYS, failover.KV_FALLBACK_PAUSE_REASON):
        assert kv(conn, key) is None, key  # the resume ends the episode bookkeeping like a fail-back



# --------------------------------------------------------------------------- review follow-ups (slice 2 fixes A1–A6)
def strike(conn, cfg, n: int, *, now: str, kind: str = "content") -> failover.Decision:
    """``n`` unusable fallback answers in a row (the adapter's ``schema:`` miss); returns the last Decision."""
    d = failover.Decision("none", None, None, None)
    for _ in range(n):
        d = rf(conn, cfg, provider="fallback", result=res("error", "schema: 2 errors", provider="fallback"), kind=kind, now=now)
    return d


def test_quality_pause_survives_an_ordinary_fallback_success_and_is_lifted_by_a_probe_an_applied_group_or_the_resume(conn, settings):
    """§10.4: the third strike tags its pause ``ai.fallback.pause_reason='quality'``. An in-flight sibling's HTTP-ok call
    (``WD_AI_CONCURRENCY > 1``) is no proof of quality — its items may still be rejected whole — so it must not undo the
    pause seconds after the strike; a fallback probe, an applied fallback group or the admin's resume lifts it. A hard
    or six-overload pause written afterwards carries no tag and is lifted by any fallback success, as before."""
    cfg = auto_cfg(settings)
    d = strike(conn, cfg, 3, now=NOW)
    assert d == failover.Decision("pause", plus(30), None, None)
    assert kv(conn, "ai.fallback.paused_until") == plus(30) and kv(conn, failover.KV_FALLBACK_PAUSE_REASON) == "quality" and kv(conn, "ai.fallback.streak.invalid") == "0"
    db.kv_set(conn, "ai.fallback.streak.timeout", "1")
    db.kv_set(conn, "ai.fallback.available", "0")
    parked = park(conn, "generate_content", "content:parked", plus(30))
    # the sibling's ordinary success: the pause, its tag and the parked job stay …
    assert failover.record_success(conn, cfg, provider="fallback", kind="content", model_used="glm-4.7-flash-250914", now=plus(1), call_id=4) is False
    assert kv(conn, "ai.fallback.paused_until") == plus(30) and kv(conn, failover.KV_FALLBACK_PAUSE_REASON) == "quality" and run_after(conn, parked) == plus(30)
    assert failover.choose(conn, cfg, kind="content", priority=20, now=plus(1)) == ("claude", None)  # claude is free: content goes there meanwhile
    # … while the rest of a success still happens: its soft streaks end, the '0' mark is lifted, the model is remembered
    assert kv(conn, "ai.fallback.streak.timeout") == "0" and kv(conn, "ai.fallback.available") == "1" and kv(conn, "ai.fallback.model_seen") == "glm-4.7-flash-250914"
    failover.record_quality_success(conn, provider="claude", now=plus(1))  # an applied claude group is no business of the fallback's
    assert kv(conn, "ai.fallback.paused_until") == plus(30)
    failover.record_quality_success(conn, provider="fallback", now=plus(2))  # an applied fallback group lifts it and releases the parked job
    assert kv(conn, "ai.fallback.paused_until") is None and kv(conn, failover.KV_FALLBACK_PAUSE_REASON) is None and run_after(conn, parked) == plus(2)
    assert failover.choose(conn, cfg, kind="content", priority=20, now=plus(2)) == ("claude", None)
    # a probe lifts it
    strike(conn, cfg, 3, now=plus(3))
    assert kv(conn, failover.KV_FALLBACK_PAUSE_REASON) == "quality"
    assert failover.record_success(conn, cfg, provider="fallback", kind="probe", model_used="glm-4.7-flash", now=plus(4)) is False
    assert kv(conn, "ai.fallback.paused_until") is None and kv(conn, failover.KV_FALLBACK_PAUSE_REASON) is None
    # the admin's resume lifts it
    strike(conn, cfg, 3, now=plus(5))
    failover.clear_pauses(conn, now=plus(6))
    assert kv(conn, "ai.fallback.paused_until") is None and kv(conn, failover.KV_FALLBACK_PAUSE_REASON) is None and kv(conn, "ai.fallback.streak.invalid") == "0"
    # a hard pause written over a quality pause is an ordinary pause again (no tag): any fallback success lifts it
    strike(conn, cfg, 3, now=plus(7))
    d = rf(conn, cfg, provider="fallback", result=res("spawn_error", "not_found: HTTP 404: model not found", provider="fallback"), kind="lookup", now=plus(8))
    assert d.action == "pause" and kv(conn, "ai.fallback.paused_until") == plus(38) and kv(conn, failover.KV_FALLBACK_PAUSE_REASON) is None
    assert failover.record_success(conn, cfg, provider="fallback", kind="lookup", model_used="glm-4.7-flash", now=plus(9)) is False
    assert kv(conn, "ai.fallback.paused_until") is None
    # … and so is the six-overload pause
    strike(conn, cfg, 3, now=plus(10))
    db.kv_set(conn, "ai.fallback.streak.overloaded", "5")
    d = rf(conn, cfg, provider="fallback", result=res("overloaded", "HTTP 429", provider="fallback"), kind="content", now=plus(11))
    assert d.action == "pause" and d.paused_until == plus(26) and kv(conn, failover.KV_FALLBACK_PAUSE_REASON) is None
    assert failover.record_success(conn, cfg, provider="fallback", kind="content", model_used="glm-4.7-flash", now=plus(12)) is False
    assert kv(conn, "ai.fallback.paused_until") is None
    failover.record_quality_success(conn, provider="fallback", now=plus(13))  # nothing counting and no quality pause: a no-op
    assert kv(conn, failover.KV_FALLBACK_PAUSE_REASON) is None and kv(conn, "ai.fallback.paused_until") is None


def test_quality_notification_names_claudes_state_end_to_end(conn, settings, monkeypatch):
    """§4.5: the ``fallback_quality`` webhook's tail is read from the state after the strike — the sticky provider and
    ``claude.available`` next to the claude pause — so an expired pause with no proven fail-back never reads 「Claude 正常」."""
    captured = Captured().install(monkeypatch)
    live = auto_cfg(settings, smoke_mock_http=False)
    make_admin(conn, "root")
    unknown = "Claude 状态未知（上次探测或调用失败），任务将先尝试 Claude，失败则排队等待。"

    def third_strike(now: str) -> str:
        db.kv_delete(conn, "ai.notify.fallback_quality.last_at")  # the hourly dedupe is not under test here
        assert strike(conn, live, 3, now=now).action == "pause"
        return captured.bodies()[-1]["text"]["content"]

    db.kv_set(conn, "ai.active_provider", "fallback")  # the claude pause expired, no probe succeeded yet
    assert third_strike(NOW).endswith(unknown)
    db.kv_set(conn, "ai.active_provider", "claude")
    db.kv_set(conn, "claude.available", "0")  # claude active again on paper, but its last probe failed
    assert third_strike(plus(1)).endswith(unknown)
    budget.set_paused_until(conn, plus(45), now=plus(2))  # a claude pause: the queue waits (unchanged)
    assert third_strike(plus(2)).endswith("Claude 暂停至 10-14 08:45，任务排队等待。")
    budget.set_paused_until(conn, None)
    db.kv_delete(conn, "claude.available")
    assert third_strike(plus(3)).endswith("Claude 正常，任务已切回 Claude。")
    assert len(captured.requests) == 4 and all("备用模型输出异常" in b["text"]["content"] for b in captured.bodies())


def test_a_new_failover_episode_starts_with_a_clean_quality_count(conn, settings):
    """§10.4 (R2-3): the claude → fallback flip zeroes a stale ``ai.fallback.streak.invalid`` (strikes of a no-flip bridge
    or of an earlier episode), so the next outage cannot pause the fallback on its first miss; a flip another thread won
    first and a count that was not counting write nothing."""
    cfg = auto_cfg(settings)
    strike(conn, cfg, 2, now=NOW)
    assert kv(conn, "ai.fallback.streak.invalid") == "2"
    d = rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(1))
    assert d.action == "switch" and d.event == "ai_failover" and kv(conn, "ai.active_provider") == "fallback"
    assert kv(conn, "ai.fallback.streak.invalid") == "0"
    d = strike(conn, cfg, 1, now=plus(2))
    assert d == failover.Decision("none", None, None, None) and kv(conn, "ai.fallback.streak.invalid") == "1"  # the episode's first miss only counts
    assert kv(conn, "ai.fallback.paused_until") is None and events(conn, "ai_fallback_quality") == []
    # a hard failure that finds the state already flipped (another thread won the CAS) leaves the count alone
    db.kv_set(conn, "ai.fallback.streak.invalid", "2")
    d = rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(3))
    assert (d.action, d.event) == ("switch", None) and kv(conn, "ai.fallback.streak.invalid") == "2"
    # a count that is not counting is not written by the next flip either
    assert failover.record_success(conn, cfg, provider="claude", kind="probe", model_used="sonnet", now=plus(31)) is True
    db.kv_delete(conn, "ai.fallback.streak.invalid")
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(40))
    assert kv(conn, "ai.active_provider") == "fallback" and kv(conn, "ai.fallback.streak.invalid") is None


def test_lifting_a_claude_pause_without_a_flip_requeues_the_casualties_since_the_pause_started(conn, settings, caplog):
    """§10.6 (R2-5): the fallback can serve while ``ai.active_provider`` is still claude (claude failed hard while the
    fallback was paused — no CAS, no ``since``; its pause then elapsed), so what died on it is an outage casualty too: in
    mode ``auto`` the first claude success lifts the pause AND requeues what died since the pause row's ``updated_at``
    (``ai_failback_requeue`` logged, no event, no fail-back reported)."""
    cfg = auto_cfg(settings)
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)  # the fallback is paused when the CLI dies: no switch
    before = dead_job(conn, "generate_content", "content:before", plus(0.5))  # died before the claude pause started
    d = rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="content", now=plus(1))
    assert d == failover.Decision("pause", plus(31), None, None) and kv(conn, "ai.active_provider") is None and kv(conn, "ai.failover.since") is None
    assert conn.execute("SELECT updated_at FROM kv WHERE key = 'claude.paused_until'").fetchone()[0] == plus(1)  # the pause start the requeue is keyed on
    assert failover.choose(conn, cfg, kind="content", priority=20, now=plus(11)) == ("fallback", None)  # the fallback bridges the claude pause without a flip
    c1 = dead_job(conn, "generate_content", "content:1", plus(1))  # finished_at == the pause start counts
    c2 = dead_job(conn, "generate_content", "content:2", plus(12))
    lk = dead_job(conn, "lookup_word", "lookup:a", plus(20))
    svg = dead_job(conn, "generate_svg", "svg:1", plus(20))  # not a fail-back type
    held = dead_job(conn, "generate_content", "content:3", plus(21))
    live = queue.enqueue(conn, "generate_content", {"k": "content:3"}, dedupe_key="content:3", priority=20, now=plus(22))
    with caplog.at_level(logging.INFO, logger="wd.ai.failover"):
        assert failover.record_success(conn, cfg, provider="claude", kind="lookup", model_used="sonnet", now=plus(32)) is False  # the CLI is back: nothing to fail back from
    assert kv(conn, "claude.paused_until") is None and events(conn, "ai_failback") == [] and kv(conn, "ai.active_provider") is None
    assert [getattr(r, "event", None) for r in caplog.records].count("ai_failback_requeue") == 1
    for job_id in (c1, c2, lk):
        job = queue.get_job(conn, job_id)
        assert (job.status, job.attempts, job.run_after, job.finished_at) == ("queued", 0, plus(32), None) and "group_size" not in job.payload, job_id
    for job_id in (before, svg, held):
        assert queue.get_job(conn, job_id).status == "dead", job_id
    assert queue.get_job(conn, live).status == "queued"
    # no pause left to lift: a second success requeues nothing more
    late = dead_job(conn, "generate_content", "content:late", plus(33))
    assert failover.record_success(conn, cfg, provider="claude", kind="lookup", model_used="sonnet", now=plus(34)) is False
    assert queue.get_job(conn, late).status == "dead"


def test_the_no_flip_requeue_needs_mode_auto_and_a_configured_fallback(conn, settings):
    """Outside mode ``auto`` (or without a fallback) nothing could have bridged the pause: a lifted claude pause leaves
    the dead jobs to the nightly requeue, as before."""
    rf(conn, settings, provider="claude", result=res("auth", "not logged in"), kind="content", now=plus(1))  # claude_cli
    died = dead_job(conn, "generate_content", "content:cli", plus(5))
    assert failover.record_success(conn, settings, provider="claude", kind="lookup", model_used="sonnet", now=plus(40)) is False
    assert queue.get_job(conn, died).status == "dead" and kv(conn, "claude.paused_until") is None
    cfg = replace(settings, ai_provider="auto")  # auto without a configured fallback
    assert cfg.fallback_configured is False
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="content", now=plus(41))
    died2 = dead_job(conn, "generate_content", "content:nofb", plus(45))
    assert failover.record_success(conn, cfg, provider="claude", kind="lookup", model_used="sonnet", now=plus(80)) is False
    assert queue.get_job(conn, died2).status == "dead" and events(conn, "ai_failback") == []


def test_reconcile_mode_ends_a_stale_episode_outside_mode_auto(conn, settings, caplog):
    """§10.6 (R2-7): a start in ``claude_cli`` / ``openai_http`` with ``ai.active_provider='fallback'`` left by an earlier
    ``auto`` tour resets the state and drops the episode keys (log event ``ai_failover_reconciled``) — no requeue, no
    event — so the first claude success in the new mode cannot "fail back" and revive jobs that died on their merits."""
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in", call_id=3), kind="lookup", now=NOW)
    assert failover.reconcile_mode(conn, cfg, now=plus(1)) is False  # mode auto: the episode is live, the probe is the way back
    assert kv(conn, "ai.active_provider") == "fallback" and kv(conn, "ai.failover.since") == NOW
    died = dead_job(conn, "generate_content", "content:merit", plus(60))  # dies on the CLI on its own merits after the mode change
    with caplog.at_level(logging.INFO, logger="wd.ai.failover"):
        assert failover.reconcile_mode(conn, settings, now=plus(61)) is True  # a restart in mode claude_cli
    assert [getattr(r, "event", None) for r in caplog.records].count("ai_failover_reconciled") == 1
    assert kv(conn, "ai.active_provider") == "claude"
    for key in (*failover.FAILOVER_KEYS, *failover.PROBE_KEYS):
        assert kv(conn, key) is None, key
    assert kv(conn, "claude.paused_until") == plus(30)  # the pause itself is not the reconcile's business
    assert queue.get_job(conn, died).status == "dead" and events(conn, "ai_failback") == [] and len(events(conn, "ai_failover")) == 1
    assert failover.reconcile_mode(conn, settings, now=plus(62)) is False  # nothing left to do
    # the first claude success in the new mode is an ordinary success, not a fail-back from the stale state
    assert failover.record_success(conn, settings, provider="claude", kind="content", model_used="sonnet", now=plus(63)) is False
    assert events(conn, "ai_failback") == [] and queue.get_job(conn, died).status == "dead"
    # openai_http reconciles the same way
    db.kv_set(conn, "ai.active_provider", "fallback")
    db.kv_set(conn, "ai.failover.since", plus(64))
    assert failover.reconcile_mode(conn, auto_cfg(settings, ai_provider="openai_http"), now=plus(65)) is True
    assert kv(conn, "ai.active_provider") == "claude" and kv(conn, "ai.failover.since") is None


def test_failback_requeue_stops_at_its_limit_and_warns(conn, settings, monkeypatch, caplog):
    """§10.6 (R2-1): the fail-back revives at most ``FAILBACK_REQUEUE_LIMIT`` casualties (the oldest first); reaching the
    limit is logged (``ai_failback_requeue_limit``) and the rest waits for the nightly — under the limit nothing is logged."""
    cfg = auto_cfg(settings)
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=NOW)
    casualties = [dead_job(conn, "generate_content", f"content:{i}", plus(1 + i)) for i in range(3)]
    monkeypatch.setattr(failover, "FAILBACK_REQUEUE_LIMIT", 2)
    with caplog.at_level(logging.INFO, logger="wd.ai.failover"):
        assert failover.record_success(conn, cfg, provider="claude", kind="probe", model_used="sonnet", now=plus(31), probe_call_ids=[7]) is True
    assert events(conn, "ai_failback")[0]["requeued_dead"] == 2
    assert [queue.get_job(conn, j).status for j in casualties] == ["queued", "queued", "dead"]
    assert [getattr(r, "event", None) for r in caplog.records].count("ai_failback_requeue_limit") == 1
    caplog.clear()
    rf(conn, cfg, provider="claude", result=res("auth", "not logged in"), kind="lookup", now=plus(40))
    dead_job(conn, "generate_content", "content:one", plus(41))
    with caplog.at_level(logging.INFO, logger="wd.ai.failover"):
        assert failover.record_success(conn, cfg, provider="claude", kind="probe", model_used="sonnet", now=plus(71)) is True
    assert events(conn, "ai_failback")[1]["requeued_dead"] == 1
    assert not [r for r in caplog.records if getattr(r, "event", None) == "ai_failback_requeue_limit"]


# ------------------------------------------------------------------------------------------ mode split
def test_choose_split_mode_sends_the_learners_work_to_the_fallback_and_the_operators_to_claude(conn, settings):
    cfg = auto_cfg(settings, ai_provider="split")
    assert failover.mode(cfg) == "split"
    assert failover.realtime(cfg, kind="lookup", priority=20) and failover.realtime(cfg, kind="content", priority=20) and failover.realtime(cfg, kind="consolidate", priority=20)
    assert not failover.realtime(cfg, kind="content", priority=90) and not failover.realtime(cfg, kind="svg", priority=20) and not failover.realtime(cfg, kind="dance", priority=20)
    assert failover.realtime(auto_cfg(settings, ai_provider="split", ai_fallback_prewarm=True), kind="content", priority=90)
    assert not failover.realtime(auto_cfg(settings, ai_provider="split", ai_fallback_kinds=("lookup", "consolidate")), kind="content", priority=20)
    for kind in ("lookup", "content", "consolidate"):
        assert failover.choose(conn, cfg, kind=kind, priority=20, now=NOW) == ("fallback", None)
    for kind, priority in (("content", 90), ("lookup", 95), ("svg", 20), ("dance", 20)):
        assert failover.choose(conn, cfg, kind=kind, priority=priority, now=NOW) == ("claude", None)  # the operator's work
    assert failover.choose(conn, auto_cfg(settings, ai_provider="split", ai_fallback_prewarm=True), kind="content", priority=90, now=NOW) == ("fallback", None)
    assert failover.choose(conn, auto_cfg(settings, ai_provider="split", ai_fallback_kinds=("lookup", "consolidate")), kind="content", priority=20, now=NOW) == ("claude", None)
    budget.set_paused_until(conn, plus(30), now=NOW)  # claude paused: the learners are unaffected, the operator's work waits
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("fallback", None)
    assert failover.choose(conn, cfg, kind="content", priority=90, now=NOW) == (None, plus(30))
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == (None, plus(30))
    budget.set_paused_until(conn, None)
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)  # fallback paused: the learners wait for IT, never claude
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, plus(10))
    assert failover.choose(conn, cfg, kind="content", priority=20, now=NOW) == (None, plus(10))
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == ("claude", None)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=plus(11)) == ("fallback", None)
    failover.set_fallback_paused_until(conn, None, now=NOW)
    db.kv_set(conn, "ai.fallback.available", "0")
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, None)  # unavailable: nothing scheduled, re-deferred every 30 min
    db.kv_delete(conn, "ai.fallback.available")
    db.kv_set(conn, "ai.active_provider", "fallback")  # a stale sticky state from an `auto` tour changes nothing …
    assert failover.choose(conn, cfg, kind="svg", priority=20, now=NOW) == ("claude", None)
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("fallback", None)
    assert failover.reconcile_mode(conn, cfg, now=NOW) is True and failover.active_provider(conn) == "claude"  # … and the start-up hook clears it
    assert failover.maybe_probe(conn, cfg, now=NOW, probe_claude=lambda: pytest.fail("no fail-back probes in mode split")) is None


def test_availability_reasons_in_split_mode(conn, settings):
    cfg = auto_cfg(settings, ai_provider="split")
    a = failover.availability(conn, cfg, kind="lookup", now=NOW)
    assert (a.ok, a.provider, a.reason) == (True, "fallback", "ok")
    assert failover.availability(conn, cfg, kind="content", now=NOW, priority=90).provider == "claude"
    failover.set_fallback_paused_until(conn, plus(10), now=NOW)
    a = failover.availability(conn, cfg, kind="lookup", now=NOW)
    assert (a.ok, a.reason, a.fallback_paused_until, a.resumes_at) == (False, "fallback_paused", plus(10), plus(10))
    assert failover.availability(conn, cfg, kind="svg", now=NOW).ok is True  # claude is free: the operator's work runs
    failover.set_fallback_paused_until(conn, None, now=NOW)
    db.kv_set(conn, "ai.fallback.available", "0")
    assert failover.availability(conn, cfg, kind="lookup", now=NOW).reason == "fallback_unavailable"
    db.kv_delete(conn, "ai.fallback.available")
    budget.set_paused_until(conn, plus(30), now=NOW)
    assert failover.availability(conn, cfg, kind="lookup", now=NOW).ok is True  # the learners never notice a claude pause
    assert failover.availability(conn, cfg, kind="svg", now=NOW).reason == "claude_paused"
    assert failover.availability(conn, cfg, kind="content", now=NOW, priority=90).reason == "claude_paused"


def test_split_mode_never_flips_or_reruns_but_alerts_when_both_are_down(conn, settings, monkeypatch):
    cfg = auto_cfg(settings, ai_provider="split", smoke_mock_http=False)  # the test env mocks providers, which also silences notify()
    make_admin(conn)
    hook = Captured().install(monkeypatch)
    d = rf(conn, cfg, provider="claude", result=res("auth", "managed settings", provider="claude"), kind="content", now=NOW, priority=90)
    assert d == failover.Decision("pause", plus(30), None, None)  # paused, no switch, no rerun on the fallback
    assert failover.active_provider(conn) == "claude" and kv(conn, "ai.failover.since") is None and events(conn, "ai_failover") == []
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == ("fallback", None)  # the learners are unaffected
    assert hook.requests == []  # the fallback is up: not "both down"
    d = rf(conn, cfg, provider="fallback", result=res("auth", "HTTP 401", provider="fallback"), kind="lookup", now=NOW)
    assert d == failover.Decision("pause", plus(30), None, None)  # paused, never rerun on claude
    assert failover.choose(conn, cfg, kind="lookup", priority=20, now=NOW) == (None, plus(30))
    assert len(hook.requests) == 1 and failover.active_provider(conn) == "claude"  # the learners' provider paused: one alert, still no flip
    body = hook.bodies()[0]
    assert "学习者的备用模型已暂停" in json.dumps(body, ensure_ascii=False) and "Claude 也暂停至" in json.dumps(body, ensure_ascii=False)
    for _ in range(3):
        d = rf(conn, cfg, provider="fallback", result=res("overloaded", "HTTP 429", provider="fallback"), kind="lookup", now=plus(31))
    assert d.retry_provider is None and kv(conn, "ai.fallback.streak.overloaded") == "3"  # a soft threshold names nobody either
    budget.set_paused_until(conn, None)
    failover.set_fallback_paused_until(conn, None, now=NOW)
    hook.requests.clear()
    db.kv_delete(conn, "ai.notify.fallback_paused.last_at")  # past the hourly dedup
    d = rf(conn, cfg, provider="fallback", result=res("auth", "HTTP 401", provider="fallback"), kind="lookup", now=plus(61))
    assert d.retry_provider is None and len(hook.requests) == 1  # claude is free, yet the learners' provider is down: the alert fires anyway, no rerun
    assert "Claude 侧的预热 / 配图 / 舞步标注不受影响" in json.dumps(hook.bodies()[0], ensure_ascii=False)
    title, text = failover.notification_text("fallback_quality", {"consecutive": 3, "kind": "content", "paused_until": plus(30), "error": "schema: x"}, cfg)
    assert "分流模式" in text and "切回" not in text and "不受影响" in text
    _, text = failover.notification_text("fallback_quality", {"consecutive": 3, "kind": "content", "paused_until": plus(30), "error": "schema: x", "claude_paused_until": plus(30)}, cfg)
    assert "Claude 也暂停至" in text
    _, text = failover.notification_text("fallback_paused", {"reason": "not_found", "status": "spawn_error", "error": "not_found: model", "fallback_paused_until": plus(30), "fallback_unavailable": True}, cfg)
    assert "已标记为不可用" in text and "wd ai-check --provider fallback" in text and "暂停至" not in text
    # a configuration failure (404 / unknown model) is a hard pause AND the '0' mark: the alert names the unavailable state
    db.kv_delete(conn, "ai.notify.fallback_paused.last_at")
    hook.requests.clear()
    d = rf(conn, cfg, provider="fallback", result=res("spawn_error", "not_found: model glm-x", provider="fallback"), kind="lookup", now=plus(120))
    assert d.action == "pause" and kv(conn, "ai.fallback.available") == "0" and len(hook.requests) == 1
    assert "已标记为不可用" in json.dumps(hook.bodies()[0], ensure_ascii=False)
