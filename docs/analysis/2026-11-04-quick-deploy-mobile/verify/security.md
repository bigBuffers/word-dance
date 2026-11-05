# Verification — slice "security" (word-Dance @ 9ab13a5, 2026-11-04)

Method: adversarial re-check by execution. Code read at the cited lines; `backend/tests/integration/test_auth.py` (24 passed), `test_deps.py` (4 passed), `unit/test_scheduler.py -k hourly_gc` (2 passed), `unit/test_security.py -k "lock or throttle"` (17 passed); four throwaway `wd serve` instances (ports 8031/8022/8023/8024, data dirs under `scratchpad/quick/verify-security/data{A,B,C,D}`, `WD_CLAUDE_BIN=backend/tests/fake_claude.py`, `WD_WORKER_ENABLED=0`) driven with curl; `wd` CLI runs against `dataE`; read-only queries on `scratchpad/quick/live-copy.db`; one WebFetch of the Caddy docs. Nothing under `/Users/sqin/word-dance-data`, port 8000, the real `claude` or tracked files was touched; all four servers were killed afterwards (port 8021 was already held by another slice's `wd serve`, PID 24108 — not mine, left alone; my A instance moved to 8031).

Verdict summary: F3 confirmed · F4 **corrected** (sqlite3 CLI needs `.timeout`) · F5 confirmed · F6 confirmed · F7 **corrected** (the SQL cancel recipe fails as written) · F8 confirmed (mechanics; demand model is a projection) · F10 confirmed · F11 confirmed · F2 confirmed · F15 confirmed.

---

## F3 — bootstrap admin window — **confirmed**

What I ran (server A, `WD_REGISTRATION_MODE=closed`, empty users table):

```
curl http://127.0.0.1:8031/api/health
  → {"status":"ok","version":"0.1.0","registration_mode":"closed","needs_setup":true,...}
curl -H 'X-WD-Request: 1' -H 'Content-Type: application/json' -d '{"username":"alice","password":"correct-horse-9"}' .../api/auth/register
  → 201 {"user":{"id":1,"username":"alice",...,"role":"admin","onboarding_state":"pending",...}}      (no invite code, mode closed)
curl .../api/health → needs_setup:false
register bob (closed, no invite) → 403 {"error":{"code":"registration_closed"}}
later: wd invite --uses 1 --days 1 on dataA, register bob WITH the valid code under closed → 403 (closed refuses invites too)
```

CLI path (fresh `dataE`, `wd migrate` only):

```
wd create-admin --if-none                      → "no admin configured (WD_ADMIN_USERNAME unset): the first account registered on the site becomes admin", exit 0, users 0
WD_ADMIN_USERNAME=boss WD_ADMIN_PASSWORD=… wd create-admin --if-none → "wd: password taken from $WD_ADMIN_PASSWORD" / "created admin boss (id 1)", exit 0
again                                          → "users already exist; nothing to do", exit 0
WD_ADMIN_PASSWORD=password wd create-admin     → "wd: weak password: 该密码过于常见，请换一个", exit 2
```

Code: `auth.py:88-98` (`bootstrap` decided inside `db.tx`, `closed`/`invite` checks only in the `else` branch), `health.py:42`, `security.py:734-766`. install.sh order verified by `grep -n`: `create-admin --if-none` at :144, unit (re)start at :158, Caddy install/config at :168-170; `.env` is sourced (`set -a; . "$DATA/.env"`) before step 6 so `WD_ADMIN_*` reach the CLI. live-copy.db `users`: `1|sqin|admin|1|2026-11-02T07:46:21Z` (one admin). Note for the ops text: every registration POST — including the 403s — counts toward the 5/h/IP budget (see omission 1).

## F4 — username lockout — **corrected** (one detail; everything else confirmed by execution)

Live (server A): 10× `{"username":" ALICE ","password":"wrong-password-1"}` → `401 ×10`; DB row `login:user:alice|10|2026-11-04T11:56:53Z` (15 min after the 10th failure at 11:41:53). Correct password while locked → `HTTP/1.1 423 Locked`, `retry-after: 900`, `{"code":"account_locked","details":{"retry_after_s":900}}`. Three more wrong attempts → `423 423 423`; row unchanged (`count` still 10, same `blocked_until`) — attempts during a lock are not counted (`auth.py:126` runs before `:130`). Then, with the server running:

```
sqlite3 -cmd ".timeout 5000" dataA/word-dance.db "DELETE FROM auth_throttle WHERE key = 'login:user:alice';"   → exit 0
login alice/correct → 200
```

Schedule, driven with a controlled clock through `security.record_login_failure` (scratch script): locks at failure #10 900 s, #15 1800, #20 3600, #25 7200, #30 14400, #35 28800, #40 57600, #45 86400, #50/#55 86400 (`lock_seconds_for` identical); key for `" Alice "` is `login:user:alice`; 9 failures then a 10th at +24 h 1 s → `count` restarts at 1, no lock (the 24 h reset is measured from `window_start` = first failure of the streak, as the digest body says). `wd unlock` → `invalid choice: 'unlock'`; `grep -rn unlock backend/wd` → nothing. Unit tests `test_security.py -k "lock or throttle"` 17 passed; `test_auth.py::test_login_lockout_persists_across_app_instances` passed.

**Correction.** "safe while the service runs (WAL, busy_timeout 5000)" holds for the app side only. The `sqlite3` shell has no busy handler by default: with a write transaction in flight (Python `BEGIN IMMEDIATE` held 4 s on a WAL db)

```
sqlite3 busy.db "DELETE FROM auth_throttle WHERE key='login:user:alice';"   → "Error: stepping, database is locked (5)", exit 5, row NOT deleted (0.014 s)
sqlite3 -cmd ".timeout 5000" busy.db "DELETE …"                             → exit 0 after 3.0 s (waited for the holder)
```

So the unlock one-liner must be `sqlite3 -cmd ".timeout 5000" …` (or `.timeout 5000` inside the shell); a collision is rare but the failure is silent-ish (non-zero exit, nothing deleted). The Python fallback is fine as written: `sqlite3.connect(…)` defaults to `timeout=5.0`. Also worth telling the operator: 423 responses still consume the per-IP login budget (A: `login:ip:127.0.0.1|15` after 15 POSTs, four of them 423) — `rate_limit` at `auth.py:125` precedes `check_lockout` at `:126`.

## F5 — per-IP login/registration throttles — **confirmed**

Server B (`WD_REGISTRATION_MODE=open`, `WD_TRUST_PROXY` unset):

```
registrations friend1..friend6 from 127.0.0.1 → 201 201 201 201 201 429 ; friend7 → 429, retry-after: 3599, details.retry_after_s 3599
20× login ghost<i> (each with a spoofed "X-Forwarded-For: 203.0.113.<i>") → 401 ×20
login friend1 with the CORRECT password → 429, retry-after: 597, {"code":"rate_limited","details":{"retry_after_s":597}}
auth_throttle: login:ip:127.0.0.1|20, register:ip:127.0.0.1|5 ; sessions.ip = 127.0.0.1 for every session   (XFF ignored → site-wide keys)
```

Server C (`WD_TRUST_PROXY=1`, peer 127.0.0.1): logins with `X-Forwarded-For: 10.9.9.9, 203.0.113.1|2` → keys `login:ip:203.0.113.1|1`, `login:ip:203.0.113.2|1` (last hop, not the client-chosen first hop); registration with `X-Forwarded-For: 198.51.100.7` → `register:ip:198.51.100.7|1`, `sessions.ip 198.51.100.7`. `test_deps.py::test_rotating_first_hops_do_not_bypass_the_per_ip_throttles` passed. Constants `security.py:72-73`; `grep -n "LOGIN_IP\|REGISTER_IP\|RATE\|THROTTLE" backend/wd/config.py deploy/env.example` → nothing (no env knob). `cli.py:146-148` `proxy_headers=cfg.trust_proxy, forwarded_allow_ips="127.0.0.1"`; `deps.py:78-96` fallback uses the LAST hop only when the peer is loopback. Arithmetic in the claim holds given these constants. Addendum: failed registrations (403) and 423s count too (omissions 1–2).

## F6 — Secure cookie / HSTS preconditions behind Caddy — **confirmed**

Server C (`WD_TRUST_PROXY=1`, plain http from 127.0.0.1):

```
register with "X-Forwarded-Proto: https" → 201; set-cookie: wd_session=…; HttpOnly; Max-Age=2592000; Path=/; SameSite=lax; Secure
                                               strict-transport-security: max-age=31536000; includeSubDomains
login without X-Forwarded-Proto          → 200; set-cookie … SameSite=lax   (no Secure, no HSTS header)
login with "X-Forwarded-Proto: http"     → 200; no Secure, no HSTS
```

Server D (`WD_PUBLIC_URL=https://words.example.test`, no trust proxy, plain http): register → `Secure` cookie + HSTS; even `GET /api/health` carries `strict-transport-security: max-age=31536000; includeSubDomains` (plus CSP, `X-Frame-Options: DENY`, `Cache-Control: no-store`), so the digest's `curl -si …/api/health | grep -i strict-transport` check is valid. CSRF Origin set on D: `Origin: https://words.example.test` → 200, `Origin: http://127.0.0.1:8024` (Host-derived) → 200, `Origin: https://evil.example` → 403; POST without `X-WD-Request` → 403 `csrf_rejected`.

"Raw header trusted without a peer check": `security.py:220-223` and `main.py:159` read `x-forwarded-proto` whenever `cfg.trust_proxy`; uvicorn 0.54.0 `ProxyHeadersMiddleware` (source read from the venv) rewrites `scope["scheme"]/["client"]` only for peers in `forwarded_allow_ips` and never strips the headers — so for a non-loopback peer the app would still honour a spoofed header (harmless for the attacker, breaks nothing but their own cookie; still a reason to keep `WD_HOST=127.0.0.1`). Not executed with a non-loopback peer (would require binding beyond loopback). `install.sh:117` writes `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://$DOMAIN"`, `WD_TRUST_PROXY="1"` in proxy mode; `Caddyfile.example` = `encode zstd gzip / request_body max_size 2MB / reverse_proxy 127.0.0.1:8000`.

Caddy docs (WebFetch https://caddyserver.com/docs/caddyfile/directives/reverse_proxy, 2026-11-04, section "Headers › Defaults"): "It sets or augments the X-Forwarded-For header field." / "It sets the X-Forwarded-Proto header field." / "It sets the X-Forwarded-Host header field." / "For these X-Forwarded-* headers, by default, the proxy will ignore their values from incoming requests, to prevent spoofing." — matches the digest's quote.

## F7 — quotas, the unquota'd mark path, mass-mark worst case — **corrected** (the SQL recipe; the rest confirmed)

Quota constants `bank.py:54-65` (`CUSTOM_DAILY_CAP 200`, `STUDY_TODAY_DAILY_CAP 20`, `CONTENT_REQUESTS_DAILY_CAP 60`, `IMAGE_REFRESH_DAILY_CAP 20`, `REPORTS_DAILY_CAP 20`), `security.py:77` (`MUTATION_LIMIT 300/60 s`, counted once per non-GET in `deps.current_user`), `check_daily_quota` call sites: only `routers/bank.py:105,123` and `routers/words.py:271,296,326` — none on mark/batch-mark. `schemas.py:670` `items … max_length=100`. Queue order `queue.py:139,154` `ORDER BY priority, run_after, id`.

Executed on server A (alice, seeded 9,162 words, worker off):

```
3× POST /api/words/batch-mark with 100 ids each (action unfamiliar) → 200/200/200 in 0.024/0.017/0.017 s, updated 100 each, 0 errors
jobs: generate_content|20|queued|300 ; words content_state=queued 300 ; auth_throttle: mutate:user:1|3 ; no quota key written
POST /api/words/301/mark {"action":"unfamiliar","context":"detail"} → 200 → one priority-10 job; claim order head = job 301 (prio 10), then job 1 (prio 20)
```

So 9,114 words = 92 requests ≈ 2 s of wall time, 92 of the 300 mutations/min; 912 ten-word calls, 15.2 h at 60 calls/h; $41–50 at $0.0045–0.0055/word (see omission 5 for the measured top end). Admin pause is 24 h fixed (`admin_ops.py:35 MANUAL_PAUSE = timedelta(hours=24)`).

**Correction — the digest's cancel recipe fails as written.** `UPDATE jobs SET status='cancelled', finished_at=strftime(...), updated_at=finished_at, …` → `Error: stepping, NOT NULL constraint failed: jobs.updated_at (19)`: in SQLite a SET expression sees the row's OLD values, so `updated_at=finished_at` copies the pre-update `finished_at` (NULL for a queued job). Working version (verified while the server ran, `-cmd ".timeout 5000"`):

```
UPDATE jobs SET status='cancelled', finished_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now'), locked_at=NULL, locked_by=NULL
  WHERE type='generate_content' AND status='queued' AND priority>=20;              → cancelled 300
UPDATE words SET content_state='none' WHERE content_state='queued' AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.dedupe_key='content:'||words.id AND j.status IN ('queued','running'));   → words reset 300
```

After it: the priority-10 job survived (`queued|10|1`); alice re-marking two cancelled words → `exists`, still 0 new jobs (her bank rows are idempotent); another user marking word 1 (server C: dan) → a fresh `generate_content` job despite the cancelled row (`ux_jobs_dedupe_live` covers only queued/running — `SCHEMA.sql:503`); alice's explicit `POST /api/words/5/content/request` → 202, job 302 at priority 10, `content_req:user:1|1`. See omission 3 for what the recipe does not clear.

## F8 — global budget mechanics and 10-friend arithmetic — **confirmed** (mechanics/capacity); the demand model is a projection I could not check

`budget.can_spend` (`budget.py:187-235`) order read verbatim: `ai_enabled` (kill switch, `WD_AI_ENABLED` + `kv.claude.enabled`) → `paused_until` → `calls_last_hour >= ai_hourly_call_cap` (`ledger.count_started`: every `ai_calls` row of any kind/status started in the last 60 min) → monthly (`spent_month + est > cap`) → daily (`spent_today = SUM(cost_usd) of the WD_TZ day + SUM(reserved_usd) of running calls`, `budget.py:133-150`) → prewarm gates for priority ≥ 90 (`today >= 0.5 × daily`, `prewarm_spent_today >= WD_AI_PREWARM_DAILY_BUDGET_USD`) → svg sub-cap (`svg_spent_today >= cap`, inside the daily cap). Estimates `content (0.005, 0.0045)/word`. Deferral targets: `next_day_resume` = next local day 00:05 (`RESUME_MINUTE = 5`), `next_month_resume` = 1st of next month 00:05, `next_hour_resume` = next hour boundary + 1 min; `common.py:155-167` `queue.defer`s the whole group, never fails it; events `budget_daily/monthly/svg` via `event_once` since `day_begin`; `errors.py:53` `budget_exhausted → 409`; `zh.ts:18,39` fixed 「今日 AI 额度已用完，例句将在明天补齐」. Defaults `config.py:103-107`: daily 3.00, monthly 40.00, prewarm 1.00, hourly 60, svg 0.50; `WD_TZ` default Asia/Shanghai. Capacity arithmetic holds (600 words/h × $0.0045–0.0055 = $2.70–3.30/h). Batch defaults `bank.py:169-171` / `SCHEMA.sql:144-146`: `daily_new_count 10`, `daily_screen_count 15`, `max_reviews 60`; `batches.py:639` enqueues content for every push item at `CONTENT_PRIORITY_BATCH = 20`. Ledger (live-copy.db): 10-word content calls $0.0477/$0.0586/$0.0577 ($0.00477–0.00586/word, 30–31 s), 5-word $0.0258–0.0272, 1-word $0.0088–0.0180, 33 SVG avg $0.01236, consolidations $0.0156–0.0239 — so the $0.0045–0.0055 band undershoots the measured top end slightly (omission 5). The "$0.6–2.5/day settling to $0.5–1.5" demand figures are assumptions (overlap, custom-word rate) that no artefact can confirm; the recommendation to raise the monthly cap follows from the mechanics regardless.

## F10 — photo providers dead on the owner's network — **confirmed**

live-copy.db: `word_images` → `claude_svg|active|30`, `wikimedia|active|1`; `words` → `image_state=failed & content_state=ready: 17`, `ready/ready: 31`; `jobs` → `fetch_image|done|48`, every `result_json` = `{"detail": "no acceptable photo from any provider", "status": "failed"[, "svg_job_id": N]}` (33 with an SVG follow-up, 15 without); `generate_svg|done|33`; `provider_state`: `openverse … ReadTimeout: The read operation timed out … 3 consecutive, 2026-11-03T19:31:36Z` and `wikimedia … ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1011) … last_ok_at 2026-11-02T08:13:44Z`. SVG unit cost $0.01236 avg (33 calls) → $0.50 ≈ 40 cards. Code: `handler.py:102-103` `_svg_allowed = allow_svg and svg_via_claude and priority < 90 and ai_enabled and svg cap > 0`; `:198-206` only when no active image and `service.word_is_studied` (`service.py:223-234`: bank row new/learning or an open batch of the last two local days). Cause remains inferred from the error strings (Wikimedia did answer once on 11-02).

## F11 — prewarm counts, costs, gating — **confirmed**

live-copy.db (public, valid, unmerged, `content_state IN ('none','failed')`, using the stage flags prewarm uses): zk 2,099/2,099 · gk 3,829/3,829 · cet4 4,674/4,722 · cet6 7,624/7,671 · all (`stage_min IS NOT NULL`) 9,114/9,162; by `stage_min` band 2,099 / 1,792 / 1,577 (1,529 missing) / 3,694; cumulative 2,099 / 3,891 / 5,420 / 9,114. Costs at $0.0045–0.0055: 9.45–11.54 / 17.51–21.40 / 24.39–29.81 / 41.01–50.13 — arithmetic checks. `prewarm.py:29-33` `PRIORITY 90`, `PASS_MULTIPLIER 5`, `PASS_INTERVAL 2 min`; `:42-53` candidates most-frequent first, skipping live dedupe keys; `schemas.py:1320-1323` `limit 1–2000`, `max_budget_usd 0.1–50`; `admin_ops.py:354-365` `require_admin`, refused when AI off/paused; gates `budget.py:223-228`. Restart requirement: the worker's `JobContext.cfg` is the `Settings` object built at startup (`main.py:389`), and `budget.can_spend(cfg=None)` falls back to `Settings.from_env()` of the running process — a cap change in `.env` needs a restart. Batch flow: `prebuild_hours` default 3 (`config.py`), items enqueued at priority 20 (`batches.py:45,639`), ≤ 10 new + 15 screen per user by default. Upper-bound note: at the measured $0.0059/word the full seed is ≈ $54 (omission 5).

## F2 — unauthenticated surface — **confirmed**

Introspection (FastAPI 0.143.5 mounts routers lazily, so I walked `wd.main.ROUTERS[*].router.routes`): 75 method×path routes; `Counter({'current_user': 41, 'current_user,require_admin': 21, 'current_user,require_onboarded': 9, 'NONE': 4})`; NONE = `GET /api/health`, `POST /api/auth/register`, `POST /api/auth/login`, `GET /media/images/{path:path}`; `/media/card/{word_id}.svg` depends on `current_user`. HTTP: `/api/docs` → 200 on A (`WD_DEV=1`), 404 for `/api/docs` and `/api/openapi.json` on C (no `WD_DEV`); `/media/images/../../etc/passwd` (path-as-is) → 404, `/media/images/zz/notahash.jpg` → 404, a well-formed `ab/<64 hex>.jpg` without cookie → 401, with cookie → 404 (no file), `/media/card/1.svg` without cookie → 401; POST without `X-WD-Request` → 403 `csrf_rejected`. `media.py:38-48` matches (regex first, `current_user(request, conn)` inside the handler); `main.py:529-531` docs only when `cfg.dev`; SPA route `main.py:242-268` refuses `api*`/`media*`.

## F15 — hourly GC exists — **confirmed**

`scheduler.py:169-190` `hourly_gc`: `DELETE FROM sessions WHERE expires_at <= now`; `DELETE FROM auth_throttle WHERE (blocked_until IS NULL OR blocked_until <= now) AND window_start < now − 1 day`; stale-job sweep; stale-suggestion expiry; `kv maintenance.hourly_at` (`KV_HOURLY`, `:60`); called from `run_tick` (`:416`). `pytest backend/tests/unit/test_scheduler.py -k hourly_gc` → 2 passed (asserts expired session and old `login:ip:*` rows deleted, a still-locked `login:user:bob` kept, once per hour). live-copy.db `kv`: `maintenance.hourly_at|2026-11-04T10:25:02Z`. The digest's correction of C5 / auth-contract-15 stands.

---

## Omissions / new findings

1. **Failed registrations spend the 5/h/IP budget.** `security.rate_limit(register:ip:…)` (`auth.py:84`) runs before the mode/invite checks (`:94-98`), so a 403 (`registration_closed`, `invalid_invite`) counts like a 201. Verified on A: `register:ip:127.0.0.1|3` after one 201 and two 403s. For the invite evening this means a friend mistyping a code a few times can 429 the whole Wi-Fi for an hour — tell friends to paste codes, or pre-create accounts.
2. **Locked-out attempts spend the 20/10 min IP budget.** `rate_limit(login:ip)` (`:125`) precedes `check_lockout` (`:126`); verified on A: `login:ip:127.0.0.1|15` after 15 POSTs of which four were 423. A friend hammering a locked account also consumes the NAT's shared login allowance.
3. **The mass-mark flood also drives images, and the cancel recipe does not clear them.** Every finished content job enqueues `fetch_image` at the inherited priority (`ai/content.py:329 → :244-250`, skipped only when `image_state='ready'`), and batch-marked words are "studied" (`user_words.state='new'`, `images/service.py:223-234`), so with photo providers failing each one ends in a Claude SVG until the $0.50/day sub-cap (`handler.py:198-206`), through the single IoWorker and against the Openverse 160/day and Wikimedia 2,000/day quotas (`config.py` defaults). The recipe cancels `generate_content` rows only; extend its `WHERE type IN ('generate_content','fetch_image','generate_svg')` (and reset `words.image_state` likewise) if the flood has already produced content.
4. **What happens after the cancel recipe** (verified on A/C): the flooder's bank rows stay `content_state='none'` and their own re-mark is idempotent (no re-enqueue), so content for those words returns only via the daily batch build (priority 20, ≤ 25 words/user/day), prefetch (30, ≤ 50/user), another user's first mark (fresh job despite the cancelled row), or an explicit `content/request` (priority 10, 60/day). Nothing is stranded, but the flooded user sees dictionary-only cards for words never studied.
5. **Measured cost per word sits slightly above the band used for every estimate.** The three 10-word content calls in the ledger cost $0.00477, $0.00586 and $0.00577 per word (ids 14/48/67); at $0.0059 the full seed is ≈ $53.8 (zk ≈ $12.4) rather than $50.1/$11.5, and the code's own reservation (0.005 + 0.0045×10 = $0.05 per call) implies $45.6 for 912 calls. Budget the monthly cap with ~10 % headroom over the digest's figures.
6. **Nightly consolidation is bounded and does not amplify a flood.** `ai/consolidate.py:46,77-88` takes at most `MAX_ITEMS = 80` changed bank rows per call (headwords ≤ 2,000, prompt ≤ 96 KB) and the scheduler enqueues one `consolidate_bank` per user per local day (`scheduler.py:194-220`, kv guard), each capped by `WD_AI_BUDGET_CONSOLIDATE = 0.40`. So the worst case per flooded user is one ≤ $0.40 call per night, not a bank-sized bill — a fact the digest's F7/F8 do not state.

Operational corrections to carry into the launch checklist: `sqlite3 -cmd ".timeout 5000" …` for the unlock (F4); the fixed two-statement cancel recipe above (F7).
