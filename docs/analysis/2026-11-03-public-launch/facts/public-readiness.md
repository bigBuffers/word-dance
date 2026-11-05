# Fact slice: public-readiness (38 findings)

## Summary

word-Dance is engineered as a small-group self-hosted tool (DESIGN §9 literally sizes the image-report threshold for "a 1–5-user deployment"), and the code reflects that everywhere: one uvicorn worker on one SQLite file with an in-process scheduler/worker lease, a single global Claude budget ($3/day, $40/month, 60 calls/hour) shared by every user, images on local disk, and a Claude CLI authenticated by the operator's personal OAuth login. The security baseline for what exists is genuinely solid (CSP/HSTS, HttpOnly+Lax cookies with a custom CSRF header, bcrypt-12, persistent per-IP/per-user throttles and lockout, 1 MiB body cap, DNS-pinned SSRF guards for images and webhooks, regex-locked /media paths, sanitised SVG, masked config), but several things a public service needs are absent: no CAPTCHA or e-mail verification at registration, no password-reset flow, no 2FA, no admin audit trail beyond journald lines, username/e-mail enumeration at register, and - critically - the per-IP throttles trust only a proxy on 127.0.0.1, so behind any cloud load balancer or CDN every visitor shares one IP and the 5-registrations-per-hour limit becomes site-wide. Cost exposure is capped by construction, but the cap is global: any enthusiastic or hostile cohort can exhaust the day's AI budget in about an hour via the uncapped "mark unfamiliar"/batch-mark path (content jobs are enqueued per marked word with no daily quota), the nightly per-user consolidation alone costs about $0.05 per active user, and hitting $3 daily for ~13 days trips the $40 monthly cap, after which AI is deferred for everyone until the 1st; a hostile user can also churn shared images for all users via 换一张/report (threshold 1). Operationally there is no alerting, error tracking, metrics, log-retention policy, off-site backup automation, or scheduled image pruning; restore and most upgrades require stopping the service; and every AI feature depends on a human re-running `claude` login as the service user whenever the OAuth token lapses (on the Mac it additionally depends on a hand-started SSH SOCKS tunnel and a keychain shim). deploy/install.sh and the defaults are hard-wired to user sqin under /home, GNU/Linux coreutils, systemd and apt; Docker is declared unsupported because of the OAuth credential files, which API-key auth (already passed through by the runner but never exercised in this repo) would remove. Legally the UI ships attribution and a 关于与数据来源 section, export/delete/report flows exist, but there is no terms-of-service, privacy policy, cookie/consent notice, age gate (the audience includes 中考 students), or any licence/consent statement for user-contributed words, even though those words, plus up to 120 chars of users' private notes, are sent to Anthropic and kept in raw claude-logs for 14 days. The "expand the word library" loop works entirely on Claude's verdict (is_english + safe_for_sharing flip is_public=1 with no human approval), there is no admin tool to unpublish, merge, delete or ban a word, invalid strings persist forever, ECDICT-backed words become public instantly without validation, and contributions never flow back into the repo seed. For an iOS client the relevant facts are: cookie-only sessions (no bearer tokens), a mandatory `X-WD-Request: 1` header on non-GET calls, Origin-less requests accepted, cookie-gated /media URLs, and no APNs/device-token concept.

## Findings

### [public-readiness-1] (high) (a) registration & verification

- CLAIM: Registration defaults to invite mode but can be switched to open; the very first registrant becomes admin in any mode without a code, e-mail is optional and is only shape-checked, and nothing AI-related (custom adds, lookups, content requests, marks) requires a verified e-mail or even completed onboarding.
- EVIDENCE: backend/wd/config.py:36,78,321; backend/wd/routers/auth.py:79-117 (bootstrap 89-91, invite 96-98); backend/wd/schemas.py:179-231 (email optional 183, _clean_email 223-231); verified e-mail is required only for the e-mail channel: backend/wd/routers/settings.py:101-105,151-152, backend/wd/services/batches.py:1014, backend/wd/delivery/email.py:280,297; require_onboarded is used only by today/history routers: backend/wd/routers/today.py:27-73, backend/wd/routers/history.py:29-72; bank/words routers use current_user only: backend/wd/routers/bank.py:93-109, backend/wd/routers/words.py:233-334
- IMPLICATION: In open mode a throwaway account with no e-mail can start spending the shared Claude budget within seconds of registering; an iOS sign-up flow would inherit the same gap unless the server adds verification/CAPTCHA.

### [public-readiness-2] (high) (a) anti-abuse controls absent

- CLAIM: There is no CAPTCHA, no disposable-e-mail check, no e-mail verification at sign-up, and registration leaks account existence via 409 username_taken / email_taken (login itself is constant-time).
- EVIDENCE: grep for captcha|turnstile|hcaptcha|disposable over backend/wd and frontend/src returns nothing (2026-11-03); backend/wd/routers/auth.py:99-102,113-114 (enumeration), backend/wd/security.py:103-122 (dummy-hash constant-time login); only throttle is 5 registrations/hour/IP: backend/wd/security.py:73, backend/wd/routers/auth.py:84
- IMPLICATION: Open registration on the public internet relies on a per-IP throttle alone; bot sign-ups are limited only by IP diversity.

### [public-readiness-3] (high) (a) per-IP throttles behind a load balancer

- CLAIM: X-Forwarded-For is honoured only when WD_TRUST_PROXY=1 AND the TCP peer is 127.0.0.1/::1 (uvicorn forwarded_allow_ips is hard-coded to 127.0.0.1); behind a cloud LB, CDN or any proxy on another host every visitor is keyed on the LB's IP, so the 5 registrations/hour and 20 logins/10 min limits (and sessions.ip) become site-wide.
- EVIDENCE: backend/wd/deps.py:37,78-96; backend/wd/cli.py:147-148; backend/wd/security.py:72-73; backend/wd/routers/auth.py:84,125; docs/DEPLOY.md §7 (lines 360-386) only documents a same-host Caddy/nginx
- IMPLICATION: A public deployment must terminate TLS on the same host (Caddy on 127.0.0.1) or change forwarded_allow_ips/TRUSTED_PROXY_PEERS; otherwise registration locks for everyone after five sign-ups per hour and the login lockout can be triggered for all users at once.

### [public-readiness-4] (high) (a) per-user daily caps

- CLAIM: Per-user caps are: custom adds 200/day (counted per token, shared with imports), 50 tokens per add call, study-today extras 20, content requests 60/day, image refresh 20/day, reports 20/day, consolidate-now once per 60 min, and 300 mutations/min for every authenticated non-GET; the quota day is UTC while the AI budget day is WD_TZ.
- EVIDENCE: backend/wd/services/bank.py:57-65,267-302; backend/wd/routers/bank.py:103-105,123,140-168,182-186; backend/wd/routers/words.py:271,296,326; backend/wd/deps.py:177-180 + backend/wd/security.py:77,371-373; budget day: backend/wd/ai/budget.py:74-77
- IMPLICATION: The caps exist and are persisted in auth_throttle, but they are tuned for a handful of users; a cohort of N users can lawfully add 200N provisional words/day.

### [public-readiness-5] (high) (a) uncapped AI trigger via marks

- CLAIM: Marking a validated word unfamiliar (POST /api/words/{id}/mark, batch-mark up to 100 ids per request, screening, re-adds) enqueues generate_content for every such word lacking content with no per-user daily quota - only the 300 mutations/min throttle - so one user can enqueue thousands of content jobs per minute; the 60/day content-request cap covers only the explicit request endpoint.
- EVIDENCE: backend/wd/services/bank.py:618,641 (enqueue_content_if_needed inside _apply_unfamiliar) and 465-479; backend/wd/routers/words.py:114-136 (batch-mark), backend/wd/schemas.py:669-670 (max 100 items); all callers: backend/wd/services/batches.py:360,639, backend/wd/ai/lookup.py:487, backend/wd/jobs/scheduler.py:289, backend/wd/services/suggestions.py:196,227,409
- IMPLICATION: Cost is still bounded by the global caps, but a single account can burn the whole day's shared budget in about an hour and starve everyone else's content.

### [public-readiness-6] (high) (a) global budget arithmetic

- CLAIM: Global guards are WD_AI_DAILY_BUDGET_USD=3.00, MONTHLY=40.00, HOURLY_CALL_CAP=60 (all call kinds), prewarm $1, SVG $0.50, per-call caps 0.25/0.15/0.40/0.10; at the measured $0.04 per 10-word content call that is about 750 words/day and the hourly cap allows about $2.4/hour, so sustained demand reaches the daily cap in ~75 minutes and $3/day for ~13 days trips the monthly cap, after which every AI job is deferred to 00:05 on the 1st of next month.
- EVIDENCE: backend/wd/config.py:99-107; backend/wd/ai/budget.py:29-35 (estimates), 187-235 (can_spend order: kill switch, pause, hourly, monthly, daily, prewarm, svg), 100-105 (next_month_resume); backend/wd/ai/ledger.py:142-147 (hourly count covers all kinds); docs/CLAUDE_INTEGRATION.md §7 (lines 395-414, measured $0.004/word)
- IMPLICATION: Spend exposure is capped by construction (good), but service quality is not: for a public cohort the owner must either raise caps (and pay) or add per-user AI quotas, otherwise abuse or popularity degrades AI for all users for the rest of the month.

### [public-readiness-7] (high) (a) per-user nightly cost scales linearly

- CLAIM: Every active, onboarded user whose bank changed gets a nightly consolidate_bank job at 02:30 local (estimate $0.05, per-call cap $0.40, up to 80 items + full headword list ≤96 KB prompt), so N active users cost ≈ N×$0.05/night before any content: ~60 active users would consume the entire $3 daily cap by themselves.
- EVIDENCE: backend/wd/jobs/scheduler.py:194-239 (nightly_consolidation, priority 50); backend/wd/ai/budget.py:32; backend/wd/config.py:101; backend/wd/ai/consolidate.py:46,57; a user can also trigger it manually once/hour: backend/wd/routers/bank.py:140-168
- IMPLICATION: The consolidation feature as designed does not scale to a public user base under the default budget; it needs per-user frequency limits or a much larger budget.

### [public-readiness-8] (high) (a) custom-add → lookup cost path

- CLAIM: Each unknown string creates a private provisional word and a debounced lookup_word job (20 s, batched 20 per claude call, est $0.004+$0.002×n); a validated word then gets generate_content at priority 10, the same priority as explicit user requests and ahead of batch (20) and prefetch (30); 200 adds/day/user therefore cost up to ≈$0.44 (lookups) + ≈$0.80 (content) per user per day.
- EVIDENCE: backend/wd/services/words.py:51-52,599-604,688-708; backend/wd/jobs/queue.py:38-44; backend/wd/ai/budget.py:29-35; backend/wd/ai/lookup.py:487 (CONTENT_PRIORITY); priorities: backend/wd/services/bank.py:54-55, backend/wd/jobs/scheduler.py:54
- IMPLICATION: Three or four heavy word-adders saturate the default daily budget; the ordering also lets custom-word content jump ahead of the shared daily batches.

### [public-readiness-9] (high) (a) shared images can be churned by any user

- CLAIM: Images are per word, not per user; 换一张 (20/day/user) replaces the picture every other user sees, and a single report with target=image rejects the active image immediately and refetches (threshold 1, explicitly chosen for a 1–5-user deployment); Openverse's 160/day quota is shared globally.
- EVIDENCE: backend/wd/routers/words.py:259-301; backend/wd/images/service.py:186-211; docs/DESIGN.md §9 'User controls' bullet ('threshold 1 — a 1–5-user deployment cannot wait for three flags'); quotas backend/wd/config.py:116-119, backend/wd/images/quota.py:37-47
- IMPLICATION: At public scale one hostile account can degrade shared content for everyone and drain provider quotas; a vote threshold / per-user image preferences would be needed.

### [public-readiness-10] (high) (b) HTTP security headers and cookies

- CLAIM: Every response gets CSP (default-src 'self', style-src 'unsafe-inline', frame-ancestors 'none'), nosniff, Referrer-Policy same-origin, X-Frame-Options DENY, Permissions-Policy, Cache-Control no-store on /api, and HSTS (no preload) when the request or WD_PUBLIC_URL is https; the session cookie is HttpOnly, SameSite=Lax, Path=/, Max-Age 30 days with sliding renewal once per day, Secure only when WD_PUBLIC_URL is https / X-Forwarded-Proto https behind a trusted proxy / WD_COOKIE_SECURE=1; at most 20 sessions per user; tokens stored as sha256.
- EVIDENCE: backend/wd/main.py:93-103,163-178; backend/wd/security.py:62,158-192,213-242; backend/wd/deps.py:54-56,142-181; backend/wd/config.py:78,322
- IMPLICATION: Baseline is adequate for public exposure provided WD_PUBLIC_URL is set to https (otherwise cookies silently go non-Secure); an iOS client must persist and send the wd_session cookie itself (no bearer/JWT alternative exists).

### [public-readiness-11] (high) (b) CSRF model and native clients

- CLAIM: Every non-GET /api request must carry X-WD-Request: 1; when an Origin header is present it must equal the Host-derived origin or WD_PUBLIC_URL's origin (plus localhost:5173 in dev); a request without Origin is accepted; there is no CORS middleware and no Authorization/Bearer handling anywhere.
- EVIDENCE: backend/wd/deps.py:32-35,99-139; backend/wd/main.py:188-192; grep for authorization|bearer in backend/wd/deps.py and routers returns nothing; frontend/src/api/client.ts:3-4,27
- IMPLICATION: A native iOS app works today by sending the cookie plus the header with no Origin; a separate web origin (e.g. a CDN-hosted SPA) would be blocked unless it matches WD_PUBLIC_URL.

### [public-readiness-12] (high) (b) authentication hardening gaps

- CLAIM: Passwords are bcrypt cost 12, 8–64 chars, not the username, not in a 1k common list; login is throttled 20/10 min per IP with a persistent per-username lockout (10 failures → 15 min, doubling every 5, max 24 h); but there is no password-reset / forgot-password flow for users (only admin reset via POST /api/admin/users/{id} or the CLI), no 2FA/TOTP, and a role change does not revoke existing sessions (only deactivation does).
- EVIDENCE: backend/wd/security.py:56-60,72-82,137-147,304-335; backend/wd/routers/auth.py:120-142; grep for forgot|reset.password|totp|2fa over backend/wd, frontend/src, docs/API.md: only docs/API.md:118 (admin reset); backend/wd/routers/admin_users.py:82-119 (sessions deleted only when deactivating, 112-113); backend/wd/security.py:769-784 (wd set-password)
- IMPLICATION: Strangers who forget their password have no self-service path; the admin account that controls spend and users is protected by a password alone.

### [public-readiness-13] (high) (b) body limits, SSRF, path traversal, SVG

- CLAIM: Request bodies are capped at WD_MAX_BODY_BYTES=1 MiB both by Content-Length pre-check and a streaming receive wrapper (Caddy example caps at 2 MB); image downloads and webhooks are https-only, refuse IP literals/credentials/non-443, resolve all A/AAAA records and reject any private/loopback/link-local/CGNAT/NAT64/mapped address, pin the connection to the validated IP with Host+SNI, follow ≤3 re-validated redirects (webhooks: none, 10 s), cap bytes at 8 MB and Pillow pixels at 40 MP, verify magic bytes and re-encode to JPEG; /media/images paths must match ^[0-9a-f]{2}/[0-9a-f]{64}\.(jpg|svg)$ before the session is checked, the SPA fallback resolves and confines paths, SVGs are served with a sandboxing CSP and sanitised with an allow-list.
- EVIDENCE: backend/wd/main.py:184-211,246-251; backend/wd/config.py:79,323; deploy/Caddyfile.example:4; backend/wd/images/fetch.py:85-171,194-268; backend/wd/delivery/webhook.py:1-3,36-39,83-165,224-245; backend/wd/security.py:489-525; backend/wd/routers/media.py:26-57; backend/wd/images/store.py:41-65 (0600, atomic, sha-deduped)
- IMPLICATION: These surfaces are ready for public exposure as written; no action needed beyond keeping the reverse-proxy limits aligned.

### [public-readiness-14] (high) (b) admin bootstrap and audit

- CLAIM: While the users table is empty anyone can register as admin (the unauthenticated /api/health advertises needs_setup=true); admin actions are not audited in the database except AI pause/resume (system_events with 'by'): user role/active/password changes and invite creation are only INFO log lines in journald, report resolutions carry no resolver id, and regenerate/refetch/prewarm/requeue write nothing.
- EVIDENCE: backend/wd/routers/auth.py:88-91; backend/wd/routers/health.py:24-44; backend/wd/routers/admin_ops.py:314-333 (events), 376-412 (no event); backend/wd/routers/admin_users.py:115-118,139; backend/wd/routers/admin_reports.py:71-98; docs/SCHEMA.sql:552-568 (content_reports has no resolved_by)
- IMPLICATION: On a fresh public VM the operator must register before DNS goes live (or use WD_ADMIN_USERNAME/PASSWORD with wd create-admin --if-none); accountability for moderation decisions requires a schema addition.

### [public-readiness-15] (high) (b) unthrottled read paths and 500 handling

- CLAIM: GET endpoints have no per-user or per-IP rate limit (the 300/min throttle counts only non-GET); GET /api/account/export builds the whole bank + 365 days of review logs in memory per request; the only global brake is uvicorn limit_concurrency=200 (503 beyond). Unhandled exceptions return a generic internal_error with only the request_id.
- EVIDENCE: backend/wd/deps.py:177-180; backend/wd/routers/account.py:174-201; backend/wd/cli.py:146; backend/wd/errors.py:216-220
- IMPLICATION: Read-heavy abuse (export/lookup/vocab search loops) can saturate the single process; a proxy-level rate limit is advisable.

### [public-readiness-16] (high) (b) personal data at rest and in transit to Anthropic

- CLAIM: sessions store client IP and User-Agent, auth_throttle keys embed IPs (GC'd hourly once windows finish), review_logs grow unboundedly, and user-typed words plus up to 120 sanitised chars of a user's private 备注 are sent to Claude in the per-user consolidation prompt; raw claude stdout/stderr (prompts included) are kept 0600 on disk for WD_AI_LOG_KEEP_DAYS=14.
- EVIDENCE: backend/wd/security.py:174-192; backend/wd/jobs/scheduler.py:169-190; docs/DESIGN.md §5.3 (line 300) and §10 'Prompt injection' row; docs/CLAUDE_INTEGRATION.md §9 (lines 422-427); backend/wd/ai/runner.py:289-338; backend/wd/config.py:108
- IMPLICATION: A privacy policy must disclose third-party (Anthropic) processing of contributed words and notes and the retention periods; none exists today.

### [public-readiness-17] (medium) (c) single-process invariant

- CLAIM: The app refuses more than one uvicorn worker, runs sync endpoints on Starlette's thread pool (anyio default limiter, 40 threads unless raised), opens a fresh SQLite connection with six PRAGMAs per request, uses one writer via BEGIN IMMEDIATE with busy_timeout 5 s and 50/100/200 ms retries, and every authenticated non-GET performs at least one write (throttle counter) plus once-daily session renewal; bcrypt-12 login/register work (~0.25 s CPU each) runs on those same threads.
- EVIDENCE: backend/wd/main.py:504-517; backend/wd/cli.py:140-151; backend/wd/deps.py:67-74,165-180; backend/wd/db.py:44-53,109-121; backend/wd/routers/auth.py:86,129; docs/DESIGN.md §0.2 item 7; versions from .venv on 2026-11-03: starlette 1.10.0, fastapi 0.143.5, uvicorn 0.54.0, SQLite 3.54.1
- IMPLICATION: Realistically this serves tens to a low few hundred concurrently active learners on one VM; HTTP capacity is not the first wall - the shared AI budget and the serial I/O worker are - but write contention and the 40-thread pool will show under login storms or bulk marking.

### [public-readiness-18] (high) (c) background work is serial and time-clustered

- CLAIM: Claude jobs run on WD_AI_CONCURRENCY (1–3) threads, each call ~24 s per 10 words and capped at 60 calls/hour globally; a single IoWorker thread handles all image fetches (Wikimedia gated to 1 req/s process-wide) AND all e-mail/webhook deliveries; the scheduler tick processes every due user sequentially in one thread and every user defaults to push_time 08:00 Asia/Shanghai with a 3-hour prebuild window.
- EVIDENCE: backend/wd/main.py:105-111,390-397; backend/wd/config.py:94,116; backend/wd/jobs/worker.py:243-278; backend/wd/images/providers/base.py:223-266; backend/wd/jobs/scheduler.py:102-166; docs/SCHEMA.sql:141-146; backend/wd/security.py:84-85; docs/CLAUDE_INTEGRATION.md §7
- IMPLICATION: With hundreds of users the 08:00 wave queues deliveries behind image fetches and content generation lags by hours; the architecture has no horizontal path for workers.

### [public-readiness-19] (high) (c) what blocks a second process or host

- CLAIM: A second wd serve can only be a request-serving replica on the SAME SQLite file (the kv.worker_lease, TTL 90 s, lets one instance own scheduler+workers; the other waits), which rules out a second host because SQLite over a network filesystem is unsafe; images are read from the local data dir by /media, and process-local state (Wikimedia RateGate, Openverse token cache, card SVG LRU, log ring) is not shared.
- EVIDENCE: backend/wd/jobs/lease.py:31-33,55-83; backend/wd/main.py:318-437; backend/wd/routers/media.py:43 + backend/wd/config.py:177; backend/wd/images/providers/base.py:253-266; backend/wd/images/providers/openverse.py:30-31; backend/wd/logging_setup.py:35; docs/DESIGN.md §0.2 item 1
- IMPLICATION: Scaling beyond one VM means replacing db.py/queue/lease with a server database and external lock/queue and moving images to object storage - a redesign of the persistence layer, not a config change.

### [public-readiness-20] (high) (d) monitoring and alerting

- CLAIM: Observability consists of the unauthenticated /api/health (DB ping, version, registration_mode, needs_setup), the admin overview/health pages (spend, queue, provider quotas, scheduler/worker liveness, claude availability, disk free, last_backup, last 24 h system_events) and JSON log lines in journald; there is no alerting, paging, metrics endpoint, uptime check or error tracker, and no journald retention setting in the units.
- EVIDENCE: backend/wd/routers/health.py:24-44; backend/wd/routers/admin_ops.py:99-204; backend/wd/logging_setup.py:75-95; deploy/word-dance.service:35-37 (no SystemMaxUse/LogRateLimit); grep for alert|sentry|pagerduty over backend/wd returns nothing; docs/ops.md §1 (lines 10-24)
- IMPLICATION: A 24x7 public service would fail silently (AI paused, backup failed, disk full) until the operator opens the admin page; external monitoring of /api/health and of system_events kinds must be added.

### [public-readiness-21] (high) (d) backups, off-site copies, restore drill

- CLAIM: Backups are a systemd timer at 03:30 Asia/Shanghai writing VACUUM INTO + integrity_check + gzip snapshots to the local data dir (14 daily + 8 weekly; pre-migrate snapshots never pruned; images excluded unless --with-images; .env excluded); off-site copying is a manual rsync suggestion and the monthly restore drill is a manual command; restore refuses to run while the service is up, so a real restore is a full outage; backup failure is recorded only in system_events and systemctl status.
- EVIDENCE: deploy/word-dance-backup.timer:5-7; deploy/word-dance-backup.service:10; backend/wd/backup.py:25,177-190,203-230,248-280,463-468; docs/ops.md §2 (lines 26-65, rsync 51-55, .env 57-58, drill 60-65), §3 (67-88); docs/DEPLOY.md §5 (lines 350-354)
- IMPLICATION: For strangers' data the owner needs automated off-site (ideally encrypted) copies including .env and the images dir, plus an alert on backup_failed.

### [public-readiness-22] (high) (d) upgrades and downtime

- CLAIM: deploy/install.sh builds the frontend on the production host (npm ci + vite build), stops the unit before wd migrate, publishes the SPA snapshot atomically and restarts; documented downtime is migration time + ~3 s (typically < 30 s), with --no-restart allowed only for purely additive migrations; TimeoutStopSec=300 lets an in-flight claude call finish.
- EVIDENCE: deploy/install.sh:70-72,119-129,134-141,158; deploy/word-dance.service:19-22; docs/DEPLOY.md §10 (lines 410-414); docs/ops.md §4 (lines 90-142)
- IMPLICATION: Zero-downtime deploys are not available; the build step needs Node, CPU and RAM on the serving VM.

### [public-readiness-23] (high) (d) disk growth

- CLAIM: Images are shared per word (not per user), re-encoded to ≤800 px JPEG of roughly 50–120 KB and deduplicated by sha, so the 9,162-word seed tops out around 0.5–1.1 GB plus user-added words; claude-logs are pruned after 14 days; backups keep 22 DB snapshots plus unpruned pre-migrate files; review_logs and system_events have no retention; wd images-prune exists only as a manual CLI (not in nightly maintenance, and without a lease guard).
- EVIDENCE: docs/DESIGN.md §3.3 (lines 211-213), §9 Download bullet; backend/wd/images/fetch.py:241-268; backend/wd/images/store.py:41-65; backend/wd/ai/runner.py:316-338; backend/wd/jobs/scheduler.py:333-382; backend/wd/images/handler.py:298-346; docs/ops.md:278-279; backend/wd/backup.py:203-230
- IMPLICATION: Per-user growth is small (KBs/day); disk risk comes from image volume and backups on a small VM disk - add a scheduled prune and a disk alert.

### [public-readiness-24] (high) (d) dependency on the operator's claude login

- CLAIM: Every AI call spawns the claude CLI with an allow-listed env whose HOME points at the service user's ~/.claude* OAuth credentials (the unit deliberately omits ProtectHome); an auth failure pauses AI for 30 minutes, writes system_events claude_auth with a banner that hard-codes 'sqin', and recovery is an interactive `claude` login as that user; nothing re-authenticates on restart, and the hourly/nightly jobs simply keep deferring. On the owner's Mac the CLI additionally needs a USER/LOGNAME/TMPDIR shim and an SSH SOCKS tunnel started by hand because api.anthropic.com returns 403 from that network.
- EVIDENCE: backend/wd/ai/runner.py:158-174; deploy/word-dance.service:15,33-34; backend/wd/ai/common.py:37,264-279; backend/wd/ai/probe.py:184-201; docs/ops.md:196; memory notes /Users/sqin/.claude/projects/-Users-sqin-word-dance/memory/macos-local-install.md and claude-cli-macos-needs-login-env.md (written 2026-11-02)
- IMPLICATION: A 24x7 public service cannot depend on a human re-login or a laptop tunnel; API-key auth (or a scheduled, monitored credential check) is a prerequisite, and the current Mac host is not a viable public server.

### [public-readiness-25] (high) (e) hard-coded user/paths in defaults and install.sh

- CLAIM: Defaults assume user sqin under /home: WD_DATA_DIR=/home/sqin/word-dance-data (config, CLI dotenv loader, install.sh, env.example), WD_CLAUDE_BIN=/home/sqin/.local/bin/claude and WD_CLAUDE_PATH=/home/sqin/.local/bin:... (install.sh rewrites WD_CLAUDE_BIN from `command -v claude` but never WD_CLAUDE_PATH), the unit sets HOME=/home/__USER__ and PATH=/home/__USER__/.local/bin:..., RUN_USER=$(id -un) makes whoever runs the script the service user, and the auth banner/CLI hints name sqin literally.
- EVIDENCE: backend/wd/config.py:32,85-87,328-330; backend/wd/cli.py:63; deploy/install.sh:8,11,48-49,82; deploy/env.example:15,53-56; deploy/word-dance.service:11,14-16; backend/wd/ai/common.py:37; backend/wd/ai/probe.py:200; backend/wd/security.py:746
- IMPLICATION: On a fresh VM with another user (e.g. ubuntu) the install works only if claude is on that user's PATH and node is reachable from the stale WD_CLAUDE_PATH; expect to edit .env by hand and to see 'sqin' in operator-facing messages.

### [public-readiness-26] (high) (e) Linux/Ubuntu-only tooling in install.sh

- CLAIM: install.sh requires python3 ≥3.12 with venv, Node ≥22 and npm (frontend is built on the box), a claude binary in PATH, GNU `df --output` on /home, GNU `sed -i`, `mv -T`, `ip -4 route`/`hostname -I`, passwordless `sudo -n`, systemd, and `apt-get` (+ certbot) for the proxy options; it prompts interactively for a contact e-mail on a TTY and refuses any .env line that is not WD_KEY="value". The repo's own tests for these files fail on macOS by design.
- EVIDENCE: deploy/install.sh:45-53,70-79,82,89,94-97,110-114,119-129,136-138,150-175; docs/DEPLOY.md:3 (facts: Ubuntu 24.04, systemd 255); memory note macos-local-install.md (test_deploy_files.py fails on the Mac)
- IMPLICATION: Portable to a fresh Ubuntu 24.04 VM with modest edits; not portable to other distros/macOS without a rewrite; CI-style builds and unattended provisioning need the interactive prompt and sudo assumptions removed.

### [public-readiness-27] (medium) (e) API-key auth and Docker feasibility

- CLAIM: The runner already passes ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL and proxy vars from the service environment to the CLI and classifies 'invalid api key' as an auth failure, but the repo states the invocation was verified only with OAuth and no API key, docs declare Docker 'explicitly unsupported' because credentials live in /home/sqin/.claude* and must run as sqin, and install.sh's .env validator rejects non-WD_ keys (so an API key must come via a systemd drop-in or container env). With API-key auth the credential-file blocker disappears; remaining Docker needs are node+claude in the image, a writable HOME for ~/.claude.json, the claude-cwd dir, a local (non-NFS) volume for SQLite/images, and losing the systemd hardening/`systemctl is-active` restore guard (harmless).
- EVIDENCE: backend/wd/ai/runner.py:49-62,71,158-174; docs/CLAUDE_INTEGRATION.md:3,86; docs/DESIGN.md:25,105; deploy/install.sh:110-114; backend/wd/backup.py:310-318,463-468; docs/DEPLOY.md:3
- IMPLICATION: Docker/cloud portability is plausible once an API key replaces the OAuth login, but it is an untested path in this codebase and needs a verification run of wd claude-check and a cost model on Console pricing.

### [public-readiness-28] (high) (e) macOS stand-in is not install.sh

- CLAIM: The current working deployment is on the owner's Mac via launchd agents, a hand-built frontend snapshot, a text log file, a claude shim and a manually started SSH SOCKS tunnel; WD_PUBLIC_URL is intentionally empty and the CLI needs WD_DATA_DIR exported because its default is the Linux path.
- EVIDENCE: memory note /Users/sqin/.claude/projects/-Users-sqin-word-dance/memory/macos-local-install.md (2026-11-02); backend/wd/cli.py:63
- IMPLICATION: Moving to a public server means re-provisioning from scratch with install.sh on Ubuntu (or a container), not migrating the Mac setup; only the data dir (DB, .env secrets, images) carries over.

### [public-readiness-29] (high) (f) what legal/product surfaces exist

- CLAIM: Present: MIT LICENSE; ATTRIBUTION.md covering ECDICT (MIT), syllabus lists, image providers (CC0/PD/BY/BY-SA only, BY-SA caveat), generated images and Claude terms; an in-app 关于与数据来源 section with version plus four fixed source lines; a per-image attribution caption linking to the source page; 「AI 生成」 labels; GET /api/account/export (CSV/JSON incl. notes and 365 days of review logs), POST /api/bank/import, DELETE /api/account with password (cascade, orphaned private words removed), per-word reports (20/day) with admin resolve, Claude's safe_for_sharing gate before a word is public, no third-party analytics, self-hosted images.
- EVIDENCE: LICENSE:1-21; ATTRIBUTION.md:3-5,36,54-66,72-79; frontend/src/pages/SettingsPage.tsx:677-690; frontend/src/i18n/zh.ts:54,74,86; frontend/src/components/study/WordImage.tsx:25-45; backend/wd/routers/account.py:44,89-114,174-201; backend/wd/routers/words.py:259-281; backend/wd/routers/admin_reports.py:57-98; backend/wd/ai/lookup.py:354-359; docs/DESIGN.md §10 Privacy row
- IMPLICATION: The data-rights plumbing (export/delete/report) is already there for a public service; what is missing is the policy layer around it.

### [public-readiness-30] (high) (f) what legal/product surfaces are absent

- CLAIM: Absent: terms of service, privacy policy, cookie/consent notice, any consent checkbox at registration, an age gate (the product targets 中考/高中 students, i.e. minors), a licence or contribution agreement for user-added words, disclosure that words and notes are processed by Anthropic, an imprint/contact beyond WD_CONTACT_EMAIL (used only in the Wikimedia User-Agent), a takedown process for images beyond the report button, and a data-retention statement; the SPA has no /terms, /privacy or /about route.
- EVIDENCE: grep over frontend/src/i18n/zh.ts for 条款|协议|隐私|年龄 returns nothing (2026-11-03); frontend/src/pages/RegisterPage.tsx:46-86,153-158 (no consent control); frontend/src/routes.tsx:63-98; README.md:3 (audience 学生与职场人士); backend/wd/images/providers/base.py:52-62; docs/SCHEMA.sql:166-207 (no licence/consent column on words)
- IMPLICATION: Before accepting strangers (and especially minors) the owner needs ToS/privacy pages, a consent step, and a stated licence for contributed words - also required if contributions are ever folded back into the repo seed.

### [public-readiness-31] (medium) (f) Anthropic account terms

- CLAIM: ATTRIBUTION.md states that Claude Code use is governed by the terms of the operator's own account (Consumer or Commercial Terms + Usage Policy); the repo verified the setup against an OAuth login with no API key, and the owner's current Mac login is recorded as a claude.ai enterprise login.
- EVIDENCE: ATTRIBUTION.md:61-66; docs/CLAUDE_INTEGRATION.md:3; memory note claude-cli-macos-needs-login-env.md (2026-11-02)
- IMPLICATION: Whether an individual/enterprise claude.ai login may be used to generate content for an unrelated public user base is an unresolved terms question that must be settled (likely by moving to an API key on an account the owner controls) before launch; this report does not draw a legal conclusion.

### [public-readiness-32] (high) (g) how a user word becomes public

- CLAIM: An unknown string is normalised (≤48 chars, ≤4 tokens, ASCII letters/space/'/-/.), resolved exact → word_forms → ECDICT → provisional; a provisional row is inserted private (is_public=0, is_valid_english=NULL, safe_for_sharing=NULL, created_by_user_id) under a global UNIQUE(lemma), so the same string from two users is one shared row visible to both; lookup_word then sets is_valid_english=1 and is_public = (safe_for_sharing is true), flips source to 'claude', merges inflections into existing headwords (merged row stays private with merged_into_word_id), renames only when the lemma is neither a headword nor a known form, never auto-applies typo corrections, and enqueues generate_content; invalid strings are set is_valid_english=0, is_public=0 permanently but remain in words and visible to their holders.
- EVIDENCE: backend/wd/services/words.py:154-180,578-596,688-708,724-747,779-800; backend/wd/ai/lookup.py:18-30,205-267,328-373,444-490; docs/SCHEMA.sql:191-197,204; docs/DESIGN.md §5.2 (lines 289-296)
- IMPLICATION: The only gate between a stranger's keyboard and the shared public vocabulary is Claude's is_english + safe_for_sharing verdict; there is no human approval step.

### [public-readiness-33] (high) (g) moderation and quality control available

- CLAIM: Quality controls are automated: Claude verdicts, the deterministic headword validator and relatedness rule, text post-validation (control chars/HTML stripped, URLs and <script rejected), ECDICT cross-checks, schema-constrained output, image blocklist/mature/sensitivity/licence filters; human controls are limited to resolving content_reports (regenerate / replace image / dismiss), admin regenerate/refetch per word, and a 'pending_validation' count in the overview - there is NO admin endpoint to unpublish (is_public=0), delete, merge, split, rename or ban a word, and no profanity/offensive-word list for text (only for image keywords/titles).
- EVIDENCE: backend/wd/ai/common.py:49-59,93-111; backend/wd/services/words.py:779-800; backend/wd/images/select.py:20-24,55-60; backend/wd/routers/admin_ops.py (routes 99-446: overview/health/jobs/ai/content prewarm/regenerate/refetch-image/events/config/push - no word edit), backend/wd/routers/admin_users.py, backend/wd/routers/admin_reports.py:71-98; backend/wd/routers/admin_ops.py:120,137
- IMPLICATION: At public scale the admin cannot correct a bad-but-'valid' public word or remove an offensive one without SQL; a word-curation admin API/UI is a prerequisite for crowd contributions.

### [public-readiness-34] (high) (g) what public scale changes in the loop

- CLAIM: (1) ECDICT-backed strings (when WD_ECDICT_DB_PATH is set) become public instantly with is_public=1 and no Claude check unless their only translation is [网络]; (2) a provisional row can be renamed by Claude's headword, mutating the shared words table; (3) duplicates are prevented only for exact lemmas - spelling variants rely on the validator's hyphen/space tolerance and per-user nightly merge suggestions, with no global dedupe pass or admin merge tool; (4) is_public flips back to 0 only when a later generate_content answers valid=false; (5) created_by_user_id is SET NULL on account deletion and public contributed words survive the contributor; (6) the shared library lives only in this deployment's SQLite - seed import is one-way and there is no export/sync of curated words back to data/seed.
- EVIDENCE: backend/wd/services/words.py:652-685 (ECDICT public insert 671-674); backend/wd/ai/lookup.py:470-480 (rename), 205-267 (merge); backend/wd/ai/common.py:93-111; docs/DESIGN.md §5.4 (lines 302-306); backend/wd/ai/content.py:256-263; docs/SCHEMA.sql:197; backend/wd/routers/account.py:99-110; backend/wd/seed.py (import only); backend/wd/routers/admin_ops.py:120,136 (user_added count)
- IMPLICATION: To realise 'the public improves the word library' the owner needs a curation workflow (review queue, merge/unpublish tools, provenance and licence per word) and an export path; otherwise growth is unreviewed and non-portable.

### [public-readiness-35] (high) (g) visibility enforcement

- CLAIM: The visibility predicate (is_public=1 OR created_by_user_id=me OR holder of a user_words row; admins see all) is applied in SQL by vocab/letters/lookup/detail/content/image/card/screen/today routes and returns 404 for invisible ids; the /api/stages counters and suggestions only count public words.
- EVIDENCE: backend/wd/deps.py:201-216; backend/wd/services/words.py:245-255,481-494; backend/wd/routers/words.py:66-110,170-186; backend/wd/routers/vocab.py:48-133; backend/wd/routers/media.py:51-57; backend/wd/services/bank.py:193-209
- IMPLICATION: Private/pending words do not leak to other users; an iOS client gets the same filtering for free since it is server-side.

### [public-readiness-36] (high) (a)/(d) deferral semantics under cap

- CLAIM: When any cap is hit the system defers rather than fails: queued jobs get run_after = next WD_TZ day 00:05 (or next hour / 1st of month), the content-request endpoint answers 409 budget_exhausted with resumes_at, auth/spawn errors pause AI 30 min, six consecutive overloads pause 15 min, and the admin pause button pauses 24 h; the kill switch idles the worker and flags pending lookups 「暂时无法校验」.
- EVIDENCE: backend/wd/ai/budget.py:88-110,187-235; backend/wd/ai/common.py:133-184,210-282; backend/wd/routers/words.py:324-329; backend/wd/routers/admin_ops.py:314-333; backend/wd/jobs/worker.py:249-261
- IMPLICATION: Abuse never produces a bill above the caps, but it does produce a shared outage of AI features that strangers will perceive as the product being broken.

### [public-readiness-37] (high) (b)/(e) secrets and config exposure

- CLAIM: Secrets live only in the 0600 .env (WD_SECRET_KEY is generated by install.sh and protects only e-mail codes; a missing key falls back to a per-process random value with a warning); GET /api/admin/config masks the six secret keys; WD_ADMIN_PASSWORD, if used for unattended bootstrap, lingers in .env unless removed; the data dir is 0700 and the serve process forces umask 0077.
- EVIDENCE: backend/wd/config.py:44-53,281-286,385-406; deploy/install.sh:82-83; deploy/env.example:125-127; backend/wd/security.py:703-731; backend/wd/cli.py:135; docs/ops.md §9 (lines 241-248)
- IMPLICATION: Acceptable for a single-host deployment; a secrets manager is not required, but the bootstrap password must be purged and .env must be in the off-site backup set.

### [public-readiness-38] (high) (c)/(iOS) auth and media for a native client

- CLAIM: There is one authentication mechanism: the wd_session cookie issued by /api/auth/register|login with a 30-day sliding lifetime and re-sent via Set-Cookie once per day; /media/images and /media/card require that cookie; there is no token endpoint, no refresh token, no device registration, and push delivery is e-mail/webhook only (no APNs).
- EVIDENCE: backend/wd/routers/auth.py:32-42; backend/wd/main.py:128-137,175-177; backend/wd/deps.py:142-181; backend/wd/routers/media.py:38-57; backend/wd/services/batches.py:1000-1026; backend/wd/jobs/queue.py:34 (IO types: fetch_image, send_email, send_webhook)
- IMPLICATION: An iOS app can reuse the cookie session with URLSession (store cookies, add X-WD-Request on writes, load images with the shared cookie jar), but native push notifications would require new server-side device-token and APNs delivery work.

## Open questions

- Which Anthropic account and auth mode will the public server use - the owner's current claude.ai (enterprise) OAuth login or an API key on an account the owner controls - and do that account's terms permit generating content for an unrelated public user base? (The repo has never exercised the API-key path; wd claude-check must be re-run with it.)
- Where will the VM live (mainland China vs abroad)? api.anthropic.com currently answers 403 from the owner's network and needs a hand-started SOCKS tunnel; a China-hosted public site also raises ICP-filing and generative-AI-content obligations that are outside the code and this slice.
- Will TLS terminate on the same host (Caddy on 127.0.0.1, as install.sh assumes) or behind a cloud LB/CDN? If the latter, forwarded_allow_ips/TRUSTED_PROXY_PEERS must be changed or every per-IP throttle becomes site-wide.
- How many users and what monthly AI spend is acceptable? With the defaults ($3/day, $40/month, 60 calls/hour) the service degrades for everyone once a few heavy users or ~60 nightly consolidations exist; should per-user AI quotas replace or supplement the global caps?
- Is a human approval step (review queue) wanted before a stranger's word becomes public, and who moderates reports and how quickly? Today Claude's safe_for_sharing verdict is the only gate and the admin has no unpublish/merge/delete tool.
- Will the full ECDICT be installed on the public server? If so, any of its 3.4M entries can be pulled into the public word list instantly without Claude validation.
- Which SMTP provider will back e-mail verification and the (currently non-existent) password-reset flow, and should registration require a verified e-mail or a CAPTCHA?
- Where do off-site backups go (and encrypted how), including .env and the images directory, and who runs the restore drill?
- Is the audience expected to include minors (中考 students)? That determines whether an age gate/parental consent and a tightened privacy policy are needed.
- Under what licence are user-contributed words accepted, and is folding them back into data/seed (the repo) a goal? Both need a consent/licence statement in the UI and a provenance column.
- Is a single-host deployment acceptable for the foreseeable horizon, or is multi-host scaling a requirement that would justify moving SQLite/images/queue to Postgres/object storage/external lock now?
- Should alerting be built in-app (e-mail/webhook to the admin on claude_auth, budget_*, backup_failed, downtime events) or provided by external uptime/log monitoring?
