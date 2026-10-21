#!/usr/bin/env python3
"""End-to-end smoke test — `make smoke` (DEPLOY §8, DESIGN §12, TASKS WP9 acceptance).

Boots a throwaway word-Dance instance and walks the whole product once against the real HTTP API:

    health needs_setup:true → register alice (no invite code → admin) → needs_setup:false → invite → register bob
    → onboarding (gate 409 before completion) → stages → vocab → mark → bank/add "abandoned, children\\nubiquitous；bases"
    → worker-once (lookup → content → image) → content + image ready (image/jpeg, svg or card) → today/build → tick
    → grade every kind incl. an in-batch screen 不熟悉 (second row) → master → restore (snapshot back) → master again
    → re-add via unfamiliar (times_added 2) → export → import into bob → history/stats → admin overview
    (today_usd > 0 with the fake; with_photo + with_claude_svg + card_only == with_content) → logout → 401

Instance: a temporary data directory, port 8010, the fake `claude` (backend/tests/fake_claude.py), mocked image
providers (WD_SMOKE_MOCK_HTTP=1), registration open, worker threads OFF — the queue is drained deterministically
with `wd worker-once` and the scheduler is driven with `wd tick --once`, which both refuse to run next to a live
worker lease (DEPLOY §9), hence WD_WORKER_ENABLED=0. Nothing touches /home/sqin/word-dance-data.

Exit 0 when every step passes. On failure: the failing step, the last response and the server-log tail are printed,
the data directory is kept for inspection and the exit code is 1. Options: --port, --data-dir, --keep, --seed.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
FAKE_CLAUDE = BACKEND / "tests" / "fake_claude.py"
UTC = timezone.utc

USERNAME_A, USERNAME_B = "alice", "bob"
PASSWORD = "Smoke-Passw0rd!"
BANK_ADD_TEXT = "abandoned, children\nubiquitous；bases"


class SmokeFailure(Exception):
    def __init__(self, step: str, detail: str):
        super().__init__(f"{step}: {detail}")
        self.step = step
        self.detail = detail


def expect(condition: bool, detail: str) -> None:
    if not condition:
        raise AssertionError(detail)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def parse_iso(value: str) -> datetime:
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


# ------------------------------------------------------------------------------------------- HTTP
class Api:
    """A logged-in actor: one cookie jar, `X-WD-Request: 1` preset, status assertions with readable failures."""

    def __init__(self, base_url: str, name: str, *, csrf_header: bool = True, timeout: float = 30.0):
        import httpx

        headers = {"X-WD-Request": "1"} if csrf_header else {}
        self.name = name
        self.client = httpx.Client(base_url=base_url, headers=headers, timeout=timeout, follow_redirects=False)
        self.last: Any = None

    def close(self) -> None:
        self.client.close()

    def raw(self, method: str, path: str, **kw: Any):
        r = self.client.request(method, path, **kw)
        self.last = r
        return r

    def call(self, method: str, path: str, *, expect_status: int | tuple[int, ...] = 200, **kw: Any) -> Any:
        r = self.raw(method, path, **kw)
        allowed = expect_status if isinstance(expect_status, tuple) else (expect_status,)
        if r.status_code not in allowed:
            raise AssertionError(f"{self.name}: {method} {path} → {r.status_code} (expected {allowed}): {r.text[:600]}")
        if r.status_code == 204 or not r.content:
            return None
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            return r.json()
        return r

    def get(self, path: str, **kw: Any) -> Any:
        return self.call("GET", path, **kw)

    def post(self, path: str, body: dict | None = None, **kw: Any) -> Any:
        return self.call("POST", path, json=body, **kw)

    def error_code(self) -> str | None:
        try:
            return self.last.json()["error"]["code"]
        except Exception:
            return None


# ------------------------------------------------------------------------------------------ runner
class Smoke:
    def __init__(self, args: argparse.Namespace):
        self.port: int = args.port
        self.host = "127.0.0.1"
        self.base_url = f"http://{self.host}:{self.port}"
        self.keep: bool = args.keep
        self.python: str = args.python
        self.verbose: bool = args.verbose
        self.startup_timeout: float = args.startup_timeout
        self.data_dir = Path(args.data_dir).resolve() if args.data_dir else Path(tempfile.mkdtemp(prefix="wd-smoke-"))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.data_dir, 0o700)
        self.log_path = self.data_dir / "smoke-server.log"
        self.server: subprocess.Popen | None = None
        self.steps: list[str] = []
        self.started = time.monotonic()
        self.env = self._build_env(args.seed)

    # ---------------------------------------------------------------- environment / processes
    def _build_env(self, seed: str | None) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("WD_") and k not in ("CLAUDECODE", "FAKE_CLAUDE_MODE", "WEB_CONCURRENCY")}
        env["PYTHONPATH"] = str(BACKEND) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONUNBUFFERED"] = "1"
        env.update(
            {
                "WD_DATA_DIR": str(self.data_dir),
                "WD_HOST": self.host,
                "WD_PORT": str(self.port),
                "WD_PUBLIC_URL": "",
                "WD_REGISTRATION_MODE": "open",
                "WD_SECRET_KEY": secrets.token_hex(32),
                "WD_CLAUDE_BIN": str(FAKE_CLAUDE),
                "WD_CLAUDE_CWD": str(self.data_dir / "claude-cwd"),
                "WD_SMOKE_MOCK_HTTP": "1",
                "WD_WORKER_ENABLED": "0",
                "WD_DEV": "1",
                "WD_TZ": "Asia/Shanghai",
                "WD_LOG_FORMAT": "text",
                "WD_LOG_LEVEL": "INFO",
                "WD_CONTACT_EMAIL": "smoke@localhost",
                "WD_AI_ENABLED": "1",
                "WD_IMAGES_ENABLED": "1",
            }
        )
        if seed:
            env["WD_SEED_PATH"] = str(Path(seed).resolve())
        return env

    def cli(self, *args: str, check: bool = True, timeout: float = 300) -> subprocess.CompletedProcess[str]:
        cmd = [self.python, "-m", "wd.cli", *args]
        cp = subprocess.run(cmd, env=self.env, cwd=str(REPO), capture_output=True, text=True, timeout=timeout)
        if self.verbose:
            print(f"    $ wd {' '.join(args)} → {cp.returncode}\n{cp.stdout.strip()}\n{cp.stderr.strip()}".rstrip())
        if check and cp.returncode != 0:
            raise AssertionError(f"wd {' '.join(args)} exited {cp.returncode}\nstdout: {cp.stdout[-800:]}\nstderr: {cp.stderr[-800:]}")
        return cp

    def start_server(self) -> None:
        if not port_is_free(self.host, self.port):
            raise SmokeFailure("start", f"port {self.port} is busy — pass --port")
        log = self.log_path.open("ab")
        self.server = subprocess.Popen(
            [self.python, "-m", "wd.cli", "serve"],
            env=self.env,
            cwd=str(REPO),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        log.close()
        deadline = time.monotonic() + self.startup_timeout
        import httpx

        while time.monotonic() < deadline:
            if self.server.poll() is not None:
                raise SmokeFailure("start", f"server exited with {self.server.returncode} during startup\n{self.log_tail()}")
            try:
                r = httpx.get(f"{self.base_url}/api/health", timeout=2.0)
                if r.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise SmokeFailure("start", f"server did not answer /api/health within {self.startup_timeout:.0f}s\n{self.log_tail()}")

    def stop_server(self) -> None:
        if self.server is None or self.server.poll() is not None:
            return
        try:
            os.killpg(self.server.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            os.killpg(self.server.pid, signal.SIGKILL)
            self.server.wait(timeout=10)

    def log_tail(self, lines: int = 40) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "(no server log)"
        return "--- server log tail ---\n" + "\n".join(text[-lines:])

    # ---------------------------------------------------------------------------- bookkeeping
    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        t0 = time.monotonic()
        try:
            yield
        except SmokeFailure:
            raise
        except Exception as e:  # AssertionError, httpx errors, KeyError on an unexpected shape …
            raise SmokeFailure(name, f"{type(e).__name__}: {e}") from e
        self.steps.append(name)
        print(f"  ok  {name} ({time.monotonic() - t0:.1f}s)")

    # ---------------------------------------------------------------------------- job draining
    def drain(self, admin: Api, *, max_rounds: int = 10, max_wait_s: float = 60.0) -> None:
        """`wd worker-once` until no queued job is runnable; waits for debounced jobs (lookup_word run_after ≈ +20 s)."""
        for _ in range(max_rounds):
            self.cli("worker-once")
            queued = admin.get("/api/admin/jobs", params={"status": "queued", "page_size": 100})["items"]
            running = admin.get("/api/admin/jobs", params={"status": "running", "page_size": 100})["items"]
            expect(not running, f"jobs still running after worker-once: {[(j['id'], j['type']) for j in running]}")
            if not queued:
                dead = admin.get("/api/admin/jobs", params={"status": "dead", "page_size": 100})["items"]
                expect(not dead, "dead jobs after the drain: " + "; ".join(f"#{j['id']} {j['type']}: {j.get('last_error')}" for j in dead))
                return
            soonest = min(parse_iso(j["run_after"]) for j in queued)
            wait = (soonest - utcnow()).total_seconds()
            expect(wait <= max_wait_s, f"{len(queued)} job(s) deferred {wait:.0f}s into the future: {[(j['type'], j['run_after']) for j in queued][:5]}")
            time.sleep(max(0.5, wait + 0.5))
        raise AssertionError(f"queue did not drain after {max_rounds} rounds")

    def cleanup(self, success: bool) -> None:
        self.stop_server()
        if success and not self.keep:
            shutil.rmtree(self.data_dir, ignore_errors=True)
        else:
            print(f"data dir kept: {self.data_dir} (server log: {self.log_path})")


# ---------------------------------------------------------------------------------------- scenario
def run_scenario(s: Smoke) -> None:
    alice = Api(s.base_url, USERNAME_A)
    bob = Api(s.base_url, USERNAME_B)
    anon = Api(s.base_url, "anon", csrf_header=False)
    ids: dict[str, Any] = {}

    with s.step("health: needs_setup true on an empty server"):
        h = anon.get("/api/health")
        expect(h["status"] == "ok" and h["needs_setup"] is True, f"unexpected health {h}")
        expect(h["registration_mode"] == "open", f"registration_mode {h['registration_mode']}")
        expect("X-Request-Id" in anon.last.headers and anon.last.headers.get("cache-control") == "no-store", "missing API headers")

    with s.step("csrf: POST without X-WD-Request is rejected"):
        anon.post("/api/auth/logout", expect_status=403)
        expect(anon.error_code() == "csrf_rejected", f"code {anon.error_code()}")

    with s.step("register alice without an invite code → admin"):
        r = alice.post("/api/auth/register", {"username": USERNAME_A, "password": PASSWORD, "display_name": "Alice"}, expect_status=201)
        expect(r["user"]["role"] == "admin" and r["user"]["onboarding_state"] == "pending", f"user {r['user']}")
        expect(r["settings"]["next_push_at"] is not None, "next_push_at must be set at registration")
        ids["alice"] = r["user"]["id"]

    with s.step("health: needs_setup false afterwards; /me carries counters"):
        expect(anon.get("/api/health")["needs_setup"] is False, "needs_setup still true")
        me = alice.get("/api/auth/me")
        expect(me["server"]["needs_setup"] is False and me["user"]["username"] == USERNAME_A, f"me {me['user']}")
        expect({"suggestions_open", "attention"} <= set(me["counters"]), f"counters {me['counters']}")

    with s.step("admin creates an invite code"):
        inv = alice.post("/api/admin/invites", {"max_uses": 1, "expires_in_days": 7, "note": "smoke"}, expect_status=201)
        expect(isinstance(inv["code"], str) and len(inv["code"]) >= 8, f"invite {inv}")
        ids["invite"] = inv["code"]
        listed = alice.get("/api/admin/invites")["items"]
        expect(any(i["id"] == inv["id"] for i in listed), "invite not listed")

    with s.step("register bob (with the invite code) → ordinary user"):
        r = bob.post("/api/auth/register", {"username": USERNAME_B, "password": PASSWORD, "invite_code": ids["invite"]}, expect_status=201)
        expect(r["user"]["role"] == "user", f"bob role {r['user']['role']}")
        ids["bob"] = r["user"]["id"]
        bob.post("/api/admin/invites", {"max_uses": 1}, expect_status=403)
        expect(bob.error_code() == "forbidden", f"code {bob.error_code()}")

    onboarding = {"stages": ["cet4", "cet6"], "current_stage": "cet4", "timezone": "Asia/Shanghai", "push_time": "08:00"}
    with s.step("onboarding gate: /api/today is 409 until completion; vocab/bank work before it"):
        alice.get("/api/today", expect_status=409)
        expect(alice.error_code() == "onboarding_required", f"code {alice.error_code()}")
        alice.post("/api/onboarding/complete", expect_status=409)
        expect(alice.error_code() == "invalid_transition", f"code {alice.error_code()}")
        alice.get("/api/vocab", params={"page_size": 1})
        alice.get("/api/bank")

    with s.step("onboarding step 1 + complete for alice and bob (idempotent)"):
        for actor in (alice, bob):
            r = actor.post("/api/onboarding", onboarding)
            expect(r["onboarding_state"] == "screen" and r["settings"]["current_stage"] == "cet4", f"onboarding {r}")
            expect(r["settings"]["stages"] == ["cet4", "cet6"], f"stages {r['settings']['stages']}")
            expect(actor.post("/api/onboarding/complete")["onboarding_state"] == "done", "not done")
            expect(actor.post("/api/onboarding/complete")["onboarding_state"] == "done", "complete not idempotent")
        expect(alice.get("/api/auth/me")["user"]["onboarding_state"] == "done", "me.onboarding_state")

    with s.step("stages + vocab browsing + search + letters"):
        stages = alice.get("/api/stages")["items"]
        expect([x["stage"] for x in stages] == ["zk", "gk", "cet4", "cet6"], f"stages {stages}")
        expect(all(x["total"] > 0 for x in stages), "empty stage totals — seed not imported?")
        page = alice.get("/api/vocab", params={"stage": "cet4", "page_size": 30, "sort": "freq"})
        expect(page["total"] > 100 and len(page["items"]) == 30, f"vocab page {page['total']}")
        ids["vocab"] = [w for w in page["items"] if w["kind"] == "word" and w["my_state"] is None and w["lemma"] != "abandon"]
        found = alice.get("/api/vocab", params={"q": "aband", "page_size": 10})["items"]
        expect(any(w["lemma"] == "abandon" for w in found), "q=aband did not find abandon")
        letters = alice.get("/api/vocab/letters", params={"stage": "cet4"})["items"]
        expect(len(letters) >= 20 and all("letter" in x and "count" in x for x in letters), f"letters {letters[:3]}")
        expect(alice.get("/api/lookup", params={"q": "children"})["via"] == "form", "lookup children should resolve via a form")

    with s.step("mark: abandon + 4 vocabulary words unfamiliar, one known (no job side effects for browsing)"):
        detail = alice.get("/api/words/abandon")
        ids["abandon"] = detail["word"]["id"]
        expect(detail["word"]["lemma"] == "abandon" and detail["image"]["url"], f"detail {detail['word']}")
        r = alice.post(f"/api/words/{ids['abandon']}/mark", {"action": "unfamiliar", "context": "browse"})
        expect(r["status"] == "added" and r["state"] == "new" and r["mine"]["origin"] == "browse" and r["mine"]["times_added"] == 1, f"mark {r}")
        ids["marked"] = []
        for w in ids["vocab"][:4]:
            r = alice.post(f"/api/words/{w['id']}/mark", {"action": "unfamiliar", "context": "browse"})
            expect(r["status"] == "added", f"mark {w['lemma']} → {r['status']}")
            ids["marked"].append(w["id"])
        known_word = ids["vocab"][4]
        r = alice.post(f"/api/words/{known_word['id']}/mark", {"action": "known", "context": "browse"})
        expect(r["state"] == "known", f"known → {r}")
        ids["known"] = known_word["id"]
        again = alice.post(f"/api/words/{ids['abandon']}/mark", {"action": "unfamiliar"})
        expect(again["status"] == "exists", f"idempotent unfamiliar → {again['status']}")

    with s.step('bank/add "abandoned, children\\nubiquitous；bases" → exists / added / pending_ai / ambiguous'):
        r = alice.post("/api/bank/add", {"text": BANK_ADD_TEXT})
        statuses = [x["status"] for x in r["results"]]
        expect(statuses == ["exists", "added", "pending_ai", "ambiguous"], f"statuses {statuses}: {r}")
        expect((r["exists"], r["added"], r["pending_ai"], r["ambiguous"], r["invalid"]) == (1, 1, 1, 1, 0), f"counts {r}")
        children, ubiquitous, bases = r["results"][1], r["results"][2], r["results"][3]
        expect(children["word"]["lemma"] == "child" and children["resolved_via"] == "form", f"children → {children['word']}")
        expect(ubiquitous["word"]["is_valid_english"] is None and ubiquitous["word"]["is_public"] is False, f"ubiquitous → {ubiquitous['word']}")
        expect({c["lemma"] for c in bases["candidates"]} == {"base", "basis"}, f"bases candidates {bases['candidates']}")
        ids["child"] = children["word"]["id"]
        ids["ubiquitous"] = ubiquitous["word"]["id"]
        base = next(c for c in bases["candidates"] if c["lemma"] == "base")
        r = alice.post("/api/bank/add-word", {"word_id": base["id"]}, expect_status=(200, 201))
        expect(r["status"] in ("added", "readded"), f"add-word base → {r['status']}")
        ids["base"] = base["id"]
        bank = alice.get("/api/bank")
        expect(bank["counts"]["new"] >= 8, f"bank counts {bank['counts']}")
        expect(alice.get("/api/auth/me")["counters"]["attention"] == 0, "no attention flag expected yet")

    with s.step("jobs: lookup_word for ubiquitous is debounced ≈ 20 s; no content job for a provisional word"):
        jobs = alice.get("/api/admin/jobs", params={"type": "lookup_word", "page_size": 50})["items"]
        mine = [j for j in jobs if j["payload"].get("word_id") == ids["ubiquitous"]]
        expect(len(mine) == 1 and mine[0]["status"] == "queued", f"lookup jobs {mine}")
        expect(mine[0]["dedupe_key"] == f"lookup:{ids['ubiquitous']}", f"dedupe {mine[0]['dedupe_key']}")
        content_jobs = alice.get("/api/admin/jobs", params={"type": "generate_content", "page_size": 100})["items"]
        expect(not any(j["payload"].get("word_id") == ids["ubiquitous"] for j in content_jobs), "content job for an unvalidated word")
        # visibility rule (API.md §1): the holder sees the private provisional word, another user gets 404 (never 403)
        alice.get(f"/api/words/{ids['ubiquitous']}")
        bob.get(f"/api/words/{ids['ubiquitous']}", expect_status=404)
        expect(bob.error_code() == "word_not_found", f"visibility code {bob.error_code()}")
        bob.get(f"/media/card/{ids['ubiquitous']}.svg", expect_status=404)
        expect(not any(w["id"] == ids["ubiquitous"] for w in bob.get("/api/vocab", params={"q": "ubiq", "page_size": 10})["items"]), "private word listed for another user")

    with s.step("worker-once: drain lookup → content → image (fake claude, mocked providers)"):
        s.drain(alice)
        w = alice.get(f"/api/words/{ids['ubiquitous']}")["word"]
        expect(w["is_valid_english"] is True, f"ubiquitous after lookup: {w}")

    with s.step("content + image ready for abandon and ubiquitous (image/jpeg, svg or card)"):
        for key in ("abandon", "ubiquitous"):
            c = alice.get(f"/api/words/{ids[key]}/content")
            expect(c["state"] == "ready" and c["content"] is not None, f"{key} content {c['state']}")
            expect(len(c["content"]["examples"]) >= 3 and c["content"]["word"], f"{key} examples {c['content']}")
            img = alice.get(f"/api/words/{ids[key]}/image")
            expect(img["kind"] in ("photo", "svg", "card") and img["url"].startswith("/media/"), f"{key} image {img}")
            body = alice.get(img["url"])
            ctype = body.headers.get("content-type", "")
            expect(ctype.startswith(("image/jpeg", "image/svg+xml")), f"{key} media content-type {ctype}")
            if img["kind"] == "photo":
                expect(ctype.startswith("image/jpeg") and img["attribution"] is not None and img["attribution"]["text"], f"photo attribution {img}")
            card = alice.get(f"/media/card/{ids[key]}.svg")
            expect(card.headers.get("content-type", "").startswith("image/svg+xml"), "card content-type")
            expect("default-src 'none'" in card.headers.get("content-security-policy", ""), "card CSP")

    with s.step("today/build → batch with new + screen items; GET /api/today has no side effects"):
        today = alice.post("/api/today/build")
        expect(today["status"] in ("building", "ready", "published") and today["batch"] is not None, f"today {today['status']}")
        batch = today["batch"]
        kinds = {i["kind"] for i in batch["items"]}
        expect(batch["counts"]["new"] >= 5 and batch["counts"]["screen"] > 0, f"counts {batch['counts']}")
        expect(kinds <= {"review", "new", "screen", "extra"} and {"new", "screen"} <= kinds, f"kinds {kinds}")
        ids["batch"] = batch["id"]
        ids["local_date"] = today["local_date"]
        twice = alice.get("/api/today")
        expect(twice["batch"]["id"] == batch["id"] and len(twice["batch"]["items"]) == len(batch["items"]), "GET /api/today changed the batch")
        expect(alice.post("/api/today/build")["batch"]["id"] == batch["id"], "build not idempotent")

    with s.step("drain batch content + tick → status ready, pending_content 0, every item has content"):
        s.drain(alice)
        s.cli("tick", "--once")
        today = alice.get("/api/today")
        expect(today["status"] in ("ready", "published"), f"status {today['status']} after tick")
        batch = today["batch"]
        expect(batch["counts"]["pending_content"] == 0, f"pending_content {batch['counts']['pending_content']}")
        expect(all(i["content_state"] in ("ready", "failed") for i in batch["items"]), "items without content")
        expect(all(i["image"]["kind"] in ("photo", "svg", "card") for i in batch["items"]), "items without image meta")
        ids["items"] = batch["items"]

    def item_of(kind: str, used: set[int]) -> dict:
        for i in ids["items"]:
            if i["kind"] == kind and i["result"] is None and i["item_id"] not in used:
                used.add(i["item_id"])
                return i
        raise AssertionError(f"no ungraded {kind} item left")

    used: set[int] = set()

    def grade(item: dict, g: str, *, expect_status: int | tuple[int, ...] = 200) -> Any:
        return alice.post(f"/api/today/items/{item['item_id']}/grade", {"client_event_id": str(uuid.uuid4()), "grade": g, "elapsed_ms": 1500}, expect_status=expect_status)

    with s.step("grade new: good (intermediate, requeue) → good (final) → duplicate event replays"):
        a = item_of("new", used)
        r = grade(a, "good")
        expect(r["item"]["result"] is None and r["item"]["requeue_at"] is not None, f"first good should be intermediate: {r['item']}")
        expect(r["next_due_zh"] == "10 分钟后" and r["mine"]["state"] == "learning", f"intermediate {r['next_due_zh']} {r['mine']['state']}")
        done_before = r["today"]["new_done"]
        event = str(uuid.uuid4())
        r2 = alice.post(f"/api/today/items/{a['item_id']}/grade", {"client_event_id": event, "grade": "good"})
        expect(r2["item"]["result"] == "good" and r2["item"]["requeue_at"] is None, f"second good should graduate: {r2['item']}")
        expect(r2["next_due_zh"] == "明天" and r2["mine"]["srs"]["interval_days"] == 1, f"graduated {r2['next_due_zh']} {r2['mine']['srs']}")
        expect(r2["today"]["new_done"] == done_before + 1 and r2["duplicate"] is False, f"new_done {r2['today']}")
        r3 = alice.post(f"/api/today/items/{a['item_id']}/grade", {"client_event_id": event, "grade": "good"})
        expect(r3["duplicate"] is True and r3["item"]["result"] == "good", f"duplicate replay {r3}")
        grade(a, "good", expect_status=409)
        expect(alice.error_code() == "item_already_graded", f"code {alice.error_code()}")

    with s.step("grade new: again → hard → good (relearning step) and skip; invalid grade → 400"):
        b = item_of("new", used)
        expect(grade(b, "again")["item"]["result"] is None, "again must be intermediate")
        expect(grade(b, "hard")["item"]["result"] is None, "hard on the step must be intermediate")
        r = grade(b, "good")
        expect(r["item"]["result"] == "good" and r["mine"]["srs"]["interval_days"] == 1, f"graduation after again/hard: {r['item']} {r['mine']['srs']}")
        c = item_of("new", used)
        r = grade(c, "skip")
        expect(r["next_due_zh"] == "已跳过" and r["item"]["skip_count"] == 1 and r["item"]["result"] is None, f"skip {r}")
        grade(c, "known", expect_status=400)
        expect(alice.error_code() == "invalid_grade", f"code {alice.error_code()}")

    with s.step("grade screen: in-batch 不熟悉 (second row), 认识, skip; 409 on a second verdict"):
        s1 = item_of("screen", used)
        r = grade(s1, "unfamiliar")
        expect(r["item"]["result"] == "unfamiliar" and r["mine"]["state"] == "new" and r["mine"]["origin"] == "push", f"screen unfamiliar {r['item']} {r['mine']}")
        if r["study_item"] is not None:
            si = r["study_item"]
            expect(si["kind"] == "new" and si["word"]["id"] == s1["word"]["id"], f"study_item {si['kind']} {si['word']['id']}")
            today = alice.get("/api/today")["batch"]
            rows = [i for i in today["items"] if i["word"]["id"] == s1["word"]["id"]]
            expect({i["kind"] for i in rows} == {"screen", "new"}, f"rows for the word: {[i['kind'] for i in rows]}")
            ids["appended"] = si
        else:
            expect(r["next_due_zh"] == "明天", f"no study_item but next_due_zh {r['next_due_zh']}")
        s2 = item_of("screen", used)
        r = grade(s2, "known")
        expect(r["item"]["result"] == "known" and r["mine"]["state"] == "known", f"screen known {r['item']} {r['mine']}")
        grade(s2, "known", expect_status=409)
        expect(alice.error_code() == "item_already_graded", f"code {alice.error_code()}")
        s3 = item_of("screen", used)
        expect(grade(s3, "skip")["next_due_zh"] == "已跳过", "screen skip")
        grade(s3, "good", expect_status=400)
        expect(alice.error_code() == "invalid_grade", f"code {alice.error_code()}")
        if "appended" in ids:
            r = alice.post(f"/api/today/items/{ids['appended']['item_id']}/grade", {"client_event_id": str(uuid.uuid4()), "grade": "good"})
            expect(r["item"]["result"] is None and r["item"]["requeue_at"], f"appended card first good {r['item']}")

    with s.step("master → restore puts the snapshot back → master again → re-add via unfamiliar (times_added 2)"):
        d = item_of("new", used)
        wid = d["word"]["id"]
        r = grade(d, "master")
        expect(r["item"]["result"] == "master" and r["mine"]["state"] == "mastered" and r["next_due_zh"] == "已掌握", f"master {r['item']} {r['mine']['state']}")
        expect(r["mine"]["mastered_at"] is not None, "mastered_at missing")
        new_done = r["today"]["new_done"]
        restored = alice.post(f"/api/words/{wid}/mark", {"action": "restore", "context": "today"})
        expect(restored["status"] == "restored" and restored["state"] == "new", f"restore {restored['status']} {restored['state']}")
        srs = restored["mine"]["srs"]
        expect(srs["repetitions"] == 0 and srs["interval_days"] == 0 and srs["step"] == 0 and abs(srs["ease"] - 2.5) < 1e-9, f"snapshot not restored: {srs}")
        expect(restored["mine"]["times_added"] == 1 and restored["mine"]["mastered_at"] is None, f"restore changed times_added/mastered_at: {restored['mine']}")
        today = alice.get("/api/today")["batch"]
        row = next(i for i in today["items"] if i["item_id"] == d["item_id"])
        expect(row["result"] is None and today["counts"]["new_done"] == new_done - 1, f"item not gradable again: {row['result']} {today['counts']}")
        r = grade(d, "master")
        expect(r["mine"]["state"] == "mastered", "second master")
        again = alice.post(f"/api/words/{wid}/mark", {"action": "restore"})
        expect(again["status"] == "restored", "second restore within the window")
        r = grade(d, "master")
        expect(r["mine"]["state"] == "mastered", "third master")
        readded = alice.post(f"/api/words/{wid}/mark", {"action": "unfamiliar", "context": "bank"})
        expect(readded["status"] == "readded" and readded["state"] == "new", f"re-add {readded['status']} {readded['state']}")
        expect(readded["mine"]["times_added"] == 2 and readded["mine"]["priority"] == 80, f"re-add counters {readded['mine']}")
        expect(abs(readded["mine"]["srs"]["ease"] - 2.3) < 1e-9, f"re-add from mastered must lower ease to 2.3: {readded['mine']['srs']}")
        alice.post(f"/api/words/{wid}/mark", {"action": "restore"}, expect_status=409)  # a re-add is not undoable
        expect(alice.error_code() == "undo_expired", f"code {alice.error_code()}")
        ids["readded"] = wid

    with s.step("screen page: verdict known → restore deletes the row again"):
        nxt = alice.get("/api/screen/next", params={"stage": "auto", "count": 5})
        expect(len(nxt["items"]) >= 1 and nxt["remaining"] >= 1, f"screen/next {nxt['remaining']}")
        sw = nxt["items"][0]["word"]
        r = alice.post("/api/screen/verdict", {"client_event_id": str(uuid.uuid4()), "word_id": sw["id"], "verdict": "known", "context": "screen_page"})
        expect(r["verdict"] == "known" and r["mine"]["state"] == "known" and r["duplicate"] is False, f"verdict {r}")
        r = alice.post(f"/api/words/{sw['id']}/mark", {"action": "restore", "context": "screen_page"})
        expect(r["status"] == "restored" and r["state"] is None and r["mine"] is None, f"restore of a ∅-origin known: {r}")
        expect(any(i["word"]["id"] == sw["id"] for i in alice.get("/api/screen/next", params={"stage": "auto", "count": 50})["items"]), "word not a candidate again")

    with s.step("today/more + complete (session summary)"):
        more = alice.post("/api/today/more", {"source": "new", "count": 5})
        expect(isinstance(more["added"], int) and more["batch"]["id"] == ids["batch"], f"more {more.get('added')}")
        more = alice.post("/api/today/more", {"source": "screen", "count": 3})
        expect(isinstance(more["added"], int), "more screen")
        summary = alice.post("/api/today/complete")["summary"]
        expect(summary["local_date"] == ids["local_date"] and summary["mastered"] >= 1 and summary["known"] >= 1 and summary["unfamiliar"] >= 1, f"summary {summary}")

    with s.step("export json + csv (alice) → import into bob"):
        exp = alice.get("/api/account/export", params={"format": "json"})
        if not isinstance(exp, dict):
            exp = json.loads(exp.text)
        expect(exp["version"] == 1 and exp["username"] == USERNAME_A and len(exp["words"]) >= 8, f"export {len(exp.get('words', []))} words")
        expect(isinstance(exp.get("review_logs"), list) and len(exp["review_logs"]) >= 1, "export without review_logs")
        fields = {"word", "phonetic", "translation", "state", "origin", "note", "times_added", "added_at", "mastered_at", "ease", "interval_days", "repetitions", "lapses", "due_at"}
        expect(fields <= set(exp["words"][0]), f"export fields {sorted(exp['words'][0])}")
        reduced = json.dumps({"version": exp["version"], "words": exp["words"]}, ensure_ascii=False)
        imp = bob.post("/api/bank/import", {"format": "json", "data": reduced})
        expect(imp["rows"] == len(exp["words"]) and imp["added"] >= 1, f"import {imp['rows']} rows, added {imp['added']}")
        bbank = bob.get("/api/bank")
        expect(bbank["total"] >= 1 and all(i["mine"]["origin"] == "import" for i in bbank["items"]), f"bob bank {bbank['counts']}")
        csv_text = alice.get("/api/account/export", params={"format": "csv"})
        csv_body = csv_text if isinstance(csv_text, str) else csv_text.text
        expect(csv_body.splitlines()[0].startswith("word,phonetic,translation,state,origin,note,times_added"), f"csv header {csv_body.splitlines()[0]}")
        imp2 = bob.post("/api/bank/import", {"format": "csv", "data": csv_body})
        expect(imp2["rows"] == len(exp["words"]) and imp2["exists"] >= 1, f"csv re-import {imp2}")
        bob.post("/api/bank/import", {"format": "json", "data": "not json at all"}, expect_status=400)
        expect(bob.error_code() == "import_too_large", f"code {bob.error_code()}")

    with s.step("history / batches / stats"):
        day = datetime.strptime(ids["local_date"], "%Y-%m-%d")
        hist = alice.get("/api/history", params={"from": (day - timedelta(days=7)).strftime("%Y-%m-%d"), "to": ids["local_date"]})
        today_row = next((d for d in hist["days"] if d["date"] == ids["local_date"]), None)
        expect(today_row is not None and today_row["graded"] >= 1 and today_row["batch_id"] == ids["batch"], f"history today {today_row}")
        expect(hist["streak_days"] >= 1 and hist["longest_streak"] >= 1, f"streak {hist['streak_days']}")
        batches = alice.get("/api/history/batches")
        expect(batches["total"] >= 1 and batches["items"][0]["id"] == ids["batch"], f"batches {batches['total']}")
        one = alice.get(f"/api/batches/{ids['batch']}")
        expect(one["batch"]["id"] == ids["batch"] and one["batch"]["gradable"] is True, "batch replay")
        bob.get(f"/api/batches/{ids['batch']}", expect_status=404)
        stats = alice.get("/api/stats")
        expect(len(stats["stages"]) == 4 and len(stats["heatmap"]) == 84, f"stats shape {len(stats['stages'])} {len(stats['heatmap'])}")
        expect(stats["total_graded"] >= 1 and stats["total_mastered"] >= 1 and stats["streak_days"] >= 1, f"stats {stats['total_graded']} {stats['total_mastered']}")
        expect(stats["bank"]["new"] + stats["bank"]["learning"] >= 1, f"bank {stats['bank']}")

    with s.step("admin overview: today_usd > 0 with the fake; image tiles sum to with_content; no dead jobs"):
        ov = alice.get("/api/admin/overview")
        expect(ov["ai"]["today_usd"] > 0 and ov["ai"]["calls_today"] >= 1, f"ai {ov['ai']}")
        w = ov["words"]
        expect(w["with_photo"] + w["with_claude_svg"] + w["card_only"] == w["with_content"], f"image tiles {w}")
        expect(w["with_content"] >= 2 and w["user_added"] >= 1, f"words {w}")
        expect(ov["jobs"]["dead"] == 0 and ov["jobs"]["running"] == 0, f"jobs {ov['jobs']}")
        expect(ov["users"]["total"] == 2 and ov["bank_entries"] >= 1 and ov["batches_today"] >= 1, f"overview {ov['users']} {ov['bank_entries']}")
        health = alice.get("/api/admin/health")
        expect(health["db_ok"] is True and health["migrations_version"] >= 1 and health["seed_version"], f"admin health {health}")
        cfg = alice.get("/api/admin/config")["entries"]
        secret = next(e for e in cfg if e["key"] == "WD_SECRET_KEY")
        expect(secret["value"] == "***" and secret["source"] == "env", f"secret entry {secret}")
        calls = alice.get("/api/admin/ai/calls")
        expect(calls["total"] >= 1 and calls["today_usd"] > 0, f"calls {calls['total']}")
        users = alice.get("/api/admin/users")
        expect(users["total"] == 2, f"users {users['total']}")
        alice.get("/api/admin/events")
        bob.get("/api/admin/overview", expect_status=403)

    with s.step("logout → 401"):
        alice.post("/api/auth/logout", expect_status=204)
        alice.get("/api/auth/me", expect_status=401)
        expect(alice.error_code() == "unauthorized", f"code {alice.error_code()}")
        bob.post("/api/auth/logout", expect_status=204)

    with s.step("data dir hygiene: database 0600 under wd serve"):
        mode = os.stat(s.data_dir / "word-dance.db").st_mode & 0o777
        expect(mode == 0o600, f"word-dance.db mode {oct(mode)}")

    for actor in (alice, bob, anon):
        actor.close()


# -------------------------------------------------------------------------------------------- main
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="word-Dance end-to-end smoke test against a throwaway instance (fake claude, mocked providers)")
    p.add_argument("--port", type=int, default=8010, help="port of the throwaway instance (default 8010)")
    p.add_argument("--data-dir", default=None, help="data directory to use (default: a fresh temporary directory)")
    p.add_argument("--keep", action="store_true", help="keep the data directory after a successful run")
    p.add_argument("--seed", default=None, help="WD_SEED_PATH override (default: the shipped data/seed/vocab.jsonl.gz)")
    p.add_argument("--startup-timeout", type=float, default=180.0, help="seconds to wait for /api/health (the first start imports the seed)")
    p.add_argument("--python", default=sys.executable, help="interpreter for `wd serve` / `wd worker-once` (default: this one)")
    p.add_argument("-v", "--verbose", action="store_true", help="print every CLI invocation")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        import httpx  # noqa: F401
    except ImportError:
        print("smoke: httpx is required (it is pinned in backend/requirements.txt — run with .venv/bin/python)", file=sys.stderr)
        return 2
    if not FAKE_CLAUDE.is_file():
        print(f"smoke: {FAKE_CLAUDE} missing", file=sys.stderr)
        return 2
    s = Smoke(args)
    print(f"smoke: data dir {s.data_dir}, port {s.port}, fake claude, mocked providers, registration open")
    ok = False
    try:
        with s.step("start `wd serve` (worker threads off) and wait for /api/health"):
            s.start_server()
        run_scenario(s)
        ok = True
    except SmokeFailure as e:
        print(f"\nFAIL {e.step}\n  {e.detail}", file=sys.stderr)
        print(s.log_tail(), file=sys.stderr)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
    finally:
        s.cleanup(ok)
    if ok:
        print(f"\nSMOKE PASSED — {len(s.steps)} steps in {time.monotonic() - s.started:.0f}s")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
