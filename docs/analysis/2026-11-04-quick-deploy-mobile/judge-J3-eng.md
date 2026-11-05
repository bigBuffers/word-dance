# Judge J3 — engineering correctness and operational risk

Date 2026-11-04 · repo `/Users/sqin/word-dance` @ `9ab13a5` · plans judged: `design-D1-fast.md`, `design-D2-solid.md`, `design-D3-apps.md` · fact base: the ten `facts/*.md` digests and ten `verify/*.md` reports (verify overrides digest).

Method. Every command, `.env` key, header/cookie/CSRF claim, cost figure, Capacitor mechanic and migration step in the three plans was checked against the fact base and, where cheap, against the checkout (read-only): `deploy/install.sh`, `deploy/env.example`, `deploy/Caddyfile.example`, `deploy/word-dance-backup.timer`, `backend/wd/cli.py`, `backend/wd/diag.py`, `backend/wd/security.py` (`cmd_create_admin`, `USERNAME_RE`), `backend/wd/ai/prewarm.py`, `backend/wd/ai/budget.py`, `backend/wd/config.py`, `backend/wd/services/batches.py`, `backend/wd/routers/admin_ops.py`, `docs/SCHEMA.sql`, `docs/ops.md`, `docs/API.md`, the Mac's `~/Library/LaunchAgents`. The plans' SQL was executed against a throwaway copy of `scratchpad/quick/live-copy.db` (copy deleted afterwards). Nothing under `/Users/sqin/word-dance-data`, port 8000 or the real `claude` was touched; no server, build or install was run.

## 1. Scores (0–10 per criterion, total of 60)

| Criterion | D1-fast | D2-solid | D3-apps |
|---|---|---|---|
| speed_to_first_friend | 9 | 7 | 7 |
| factual_correctness | 7 | 8 | 7 |
| completeness_both_platforms | 7 | 7 | 9 |
| owner_effort_realism | 8 | 7 | 4 |
| friend_experience | 6 | 8 | 8 |
| risk_and_maintenance | 7 | 8 | 5 |
| **total** | **44** | **45** | **40** |

Rationale in one line each.
- D1: friends on Day 2 with zero code; break-glass admin and the sharp-edge table are the best operational idea of the round; but it ships no icon/no WeChat handoff before inviting and carries the most small command/fact errors (5).
- D2: the most correct and the only plan whose service tells the owner when something is wrong (watch cron → Bark/Server酱, external monitor, console snapshot); costs one extra calendar day before the first friend and ≈ 3 person-days in week 1.
- D3: the most complete (web + iOS + Android with every verifier correction applied) but ≈ 11 person-days in 14 calendar days for a part-time solo owner, no alerting, more moving parts; two wrong SQL/column names and two shell slips.

### What was verified as correct in all three (so the synthesis can keep it)
- Data migration: stop the Mac agent → `VACUUM INTO` → tar `images/` (28 shard dirs) → scp into a 0700 data dir **before** `install.sh` → `migrate` 0 pending, `import-seed` no-op, `create-admin --if-none` no-op (deploy:F5/F11, v-deploy:F5/F11; `install.sh:57` keeps an existing dir). The carried-over `kv.claude.paused_until` is in the past (verified on the copy: `2026-11-03T02:56:20Z`).
- `install.sh` flags `--with-caddy DOMAIN --with-ecdict --contact-email --dry-run` exist (`deploy/install.sh:14-26`); `.env` validator and `WD_*`-only rule (`:109-115`); proxy trio written on every `--with-caddy` run; Caddyfile re-rendered only with the flag (`:167-170`).
- `.env` keys used by the plans all exist in `deploy/env.example` with the defaults the plans assume (`WD_AI_ENABLED` 1, `WD_AI_DAILY_BUDGET_USD` 3.00, `WD_AI_MONTHLY_BUDGET_USD` 40.00, `WD_AI_PREWARM_DAILY_BUDGET_USD` 1.00, `WD_AI_HOURLY_CALL_CAP` 60, `WD_AI_SVG_DAILY_BUDGET_USD` 0.50, `WD_DEV` 0, `WD_PIXABAY_KEY` at line 105, `WD_AI_MODEL` sonnet). `WD_AI_HOURLY_CALL_CAP` accepts 1–100000 (`config.py:349`), so 120 is legal.
- Header/cookie/CSRF: `WD_TRUST_PROXY=1` + `WD_PUBLIC_URL=https://DOMAIN` + `WD_HOST=127.0.0.1` behind same-host Caddy; HSTS on `/api/health` and `Secure` on the cookie follow from the https public URL alone, so D1's "HSTS on /api/health proves the cookie path" is right and the `sessions.ip` check is the proxy-trust proof (v-security:F6, v-deploy:F6).
- AI caps 6/100, hard ceiling $180, realistic $25–60; prewarm $0.0059/word measured (+10 %); per-plan `limit ≤ 2000`, `max_budget_usd ≤ 50`; prewarm gate `spent_today < 50 % of daily` (security:F8/F11, v-security:O5).
- Hosting: ¥42 ≈ $6.00 2c4g Tokyo, Porkbun `.com` $11.81, DNSPod free TTL floor 600 s, Cloudflare DNS-only 60 s, Lighthouse IP swap once per instance (hosting:F4/F14, v-hosting:F4/F14/O1/O2).
- Capacitor: M1 remote shell = zero backend change (v-capacitor:F1 live matrix); bridge origin-exact on Android (v-capacitor:O1); exact 8.6.0 pin ≥ 8.5.1 for CVE-2026-103922 (v-captool:O1); `webDir/index.html` still required on iOS (v-captool:O5); local-notification re-arm drops `allowWhileIdle` after the first fire → cancel+schedule on every launch/resume (v-captool:F10 corr. 1); `schedule()` opens the Alarms & reminders screen unless `isExactNotification:false` or `USE_EXACT_ALARM` (corr. 2); `ITSAppUsesNonExemptEncryption=NO`, all-territory availability, "TestFlight Internal Only", Marketing-role ASC users, 90-day expiry (v-ios:F7/O1–O4). All three plans state these correctly.
- Credential wiring: allow-list `runner.py:49-62`; wrapper for `CLAUDE_CODE_OAUTH_TOKEN`/`DISABLE_AUTOUPDATER`; drop-in `EnvironmentFile=` for `ANTHROPIC_*`; `wd claude-check` as the acceptance test; model pin `claude-sonnet-5-5` (clivps:F7/F9/F10, v-clivps:F9). `cmd_create_admin` without `--if-none` creates an admin even when users exist and validates `^[A-Za-z0-9_一-龥]{2,32}$` (`security.py:734-766`, `schemas.py:52`) — D1's break-glass admin works as written.
- `wd stats`, `wd check providers`, `wd check db --db`, `wd push-now`, `wd invite`, `wd set-password` all exist (`cli.py:47-55`, `diag.py:257`); `POST /api/admin/push/run` is API.md endpoint 74; `push_now` has no lease/service guard, so D1's `wd push-now sqin` beside the live service is a normal concurrent SQLite write (D2's preference for the endpoint is fine but not required).
- The Mac has two agents, `com.word-dance.server` (PID 1204) and `com.word-dance.backup` (loaded); only D1 boots out both.

## 2. Factual errors (plan sentence → contradicting evidence)

Shared by all three plans
1. **D1 §2 2.3 / D2 §2 3.6 / D3 §2 3.2** — `sqlite3 … "select user_id, ip … from sessions order by id desc limit N"`. `sessions` is `WITHOUT ROWID` with primary key `token_hash` and has no `id` column (`docs/SCHEMA.sql:87-95`); executed on a copy of `live-copy.db` → `Error: no such column: id`. Fix: `order by created_at desc` (returns `1|127.0.0.1|2026-11-02T07:46:21Z` on the copy).

D1-fast
2. **§2 1.3** "If the image was Ubuntu 22.04 … run install.sh with `PY=python3.12` (install.sh uses `$PY`, deploy/install.sh:12)". `deploy/install.sh:12` is the unconditional assignment `PY=python3` (not `${PY:-python3}`); an exported `PY` is overwritten and the preflight at `:45` still asserts on the system `python3`. On 22.04 the operator must make `python3` resolve to 3.12 (e.g. `update-alternatives`/a shim first on PATH) or edit the script.
3. **§2 1.7** "`wd check providers` — this answers early whether Wikimedia/Openverse are reachable from Tokyo". `backend/wd/diag.py:123-136` only reads `provider_state` rows; it makes no network request. After the Mac copy those rows are the Mac's (`openverse cooldown_until 2026-11-03T19:41:36Z … ReadTimeout`, `wikimedia … 2026-11-03T19:46:36Z … SSL: UNEXPECTED_EOF`, queried on the copy), already expired, so the check prints `ok` with stale `last_error` text. Reachability needs the Day-0 curl (D2/D3) or a real fetch (add two words, then read `provider_state`/概览 — D2 §2 2.3).
4. **§2 2.2** "Throughput: 300–600 words/h … ≈ 300 effective because the fan-out is one 10-word group per 2 min". `backend/wd/ai/prewarm.py:29-31,151`: each pass enqueues `PASS_MULTIPLIER × ai_batch_size` = 5 × 10 = 50 words, deferred 2 min (1,500 words/h of fan-out); the binding limit is `WD_AI_HOURLY_CALL_CAP` 60 → 600 words/h (security:F11); at cap 120 the single worker's 30–31 s per 10-word call (security:F9) binds at ≈ 115 calls/h. 300 words/h is not what the code at 9ab13a5 does.
5. **§2 Days 4–7** `journalctl … grep -E '"event":"(budget|claude_auth|claude_unavailable|downtime|lease_lost)'`. Budget refusals are logged as `"event":"ai_deferred"` (`backend/wd/ai/common.py:169`); `budget_daily/monthly/svg` exist only as `system_events` kinds (`budget.py:40-42`), so the `budget` alternative never matches a journal line (the other four do: `common.py:278`, `probe.py:150`, `scheduler.py:400`, `lease.py:124`). Minor.
6. **§3 iPhone row** "Data export … can hang the standalone window on iOS 18.4+ (WebKit 290847)". The bug names iOS 18.4 (title) and iOS 16.7.10 (body), status NEW with no fix reported (v-pwa:F8); "18.4+" is an extrapolation. Minor.
7. **§5** "8.0–8.5.0 carry the critical proxy-path CVE". v-captool:O1: affected 8.0.0–8.3.4, 8.3.5–8.4.2, 8.5.0; 8.4.3 is patched. Imprecise, safe (the pin ≥ 8.5.1 is right). Minor.

D2-solid
8. **§2 3.5** "概览 shows `jobs.queued` draining at ≈ 6 calls/10 min". At `WD_AI_HOURLY_CALL_CAP=60` the ceiling is 10 calls/10 min; the prewarm fan-out (5 calls per 2 min) exceeds it, so the cap binds. Minor arithmetic.
9. **§2 4.2** watch cron lists `provider_blocked` among `system_events` kinds. No code path writes that kind (`grep -rn provider_blocked backend/wd` → nothing; it appears only in the `docs/SCHEMA.sql:56` comment); the term never matches. Harmless.
10. **§0 pitch** "Day 3 … has the AI caps raised to 6 USD/day and 100 USD/month" while §2 1.6 sets them on Day 1. Internal inconsistency only.
11. **§2 3.3** "the pwa verifier read the WWDC transcript as ambiguous". v-pwa:F8 concluded the opposite: the cookie-copy sentence is macOS-Dock-specific and "one extra login on iPhone is the expected default"; the Safari 17.2 claim (ios:F17) was not re-verified by any verifier. The hedge "at most one extra login" stands. Minor mis-citation.
12. **§5** "never 8.4.x/8.5.0". 8.4.3 is a patched release (v-captool:O1). Over-broad, safe. Minor.

D3-apps
13. **§2 2.4** `select name, cooldown_until, last_error from provider_state`. The column is `provider` (`docs/SCHEMA.sql:542-549`); executed on the copy → `Error: no such column: name`.
14. **§2 1.3** `exec $SHELL -l && claude --version`. `exec` replaces the shell; the `&& claude --version` never runs after a successful exec (it runs only if exec fails). `claude --version` must be typed in the new login shell.
15. **§2 1.8** the pull agent writes `StandardOutPath`/`StandardErrorPath` to `/Users/sqin/word-dance-vps-backups/pull.log`, inside the `rsync -a --delete` destination; `--delete` removes every file absent from `backups/` on the box, so the log is deleted on each run and its content lost.
16. **§2 0.6** "Apple's store CDN normally serves the mainland directly, so no proxy". Not in the fact base; the ios and captool slices list the Xcode download time over the owner's proxy-dependent network as an open question. Unsupported assumption (the fallback — EAS cloud builds — is at least named).

Not errors, but deviations the synthesis should keep in view: D2/D3 leave the Mac's `com.word-dance.backup` agent loaded (it keeps running `wd backup` nightly on the frozen DB — harmless, but `kv.backup.last` would mislead if the Mac is ever brought back); D2/D3 run the prewarm window (daily cap temporarily $40) on Day 3 while the first friends are already active, so a mass-mark accident that day can spend up to $40 (D1 runs it on night 2 before any friend).

## 3. Grafts — best concrete ideas from the non-winning plans

From D1-fast
- **Break-glass second admin** (`WD_ADMIN_USERNAME=<unguessable> WD_ADMIN_PASSWORD=… wd create-admin`, no `--if-none`): verified to work; the only mitigation in the round for "a friend's typos lock `sqin` for 15 min–24 h and there is no `wd unlock`".
- **Pilot friends on Day 2** with zero code: none of the pre-invite patches is a prerequisite (iOS 26 opens standalone without a manifest; the WeChat handoff can be text for 2–3 pilots).
- **Stop both Mac launchd agents** (server and backup) before the `VACUUM INTO`.
- **`RunAtLoad` on the backup-pull agent** and an interactive `ssh … true` first — the Mac sleeps after 1 idle minute (v-deploy:O5), so a missed 04:30 run fires at the next login.
- **The sharp-edge table** (symptom → fact → exact move) with the corrected `sqlite3 -cmd ".timeout 5000"` unlock and the corrected two-statement cancel recipe; fold it into the ops notes.
- **`WD_AI_ENABLED="0"` on Day 1 regardless** of credential readiness (no 30-min pause churn while DNS/TLS settle) and the 48-h SVG decision rule — but decide it from a real fetch/概览 image mix, not from `wd check providers`.
- **Prewarm before any friend is active** (night 2), with `max_budget_usd` sized to the measured $0.0059/word.
- Decision D13 "do not pre-pay ¥688 before evidence" as the default, with the enrolment lead time (1–3 days) as the reason it can wait.

From D3-apps
- **The whole §5 app track as the Phase-5 recipe**: exact `8.6.0` pins, canonical non-redirecting `server.url` + the Android `window.Capacitor.isNativePlatform()` QA assertion, `webDir/index.html` offline page, `insetsHandling:'native'` + `initialViewportFitValueHint:'cover'`, `USE_EXACT_ALARM` in the shell manifest + `syncDailyReminder` on every launch/resume, `isExactNotification` semantics, TTS plugin mandatory on Android, `ITSAppUsesNonExemptEncryption=NO`, all-territory availability, "Internal Only" uploads, Marketing-role ASC users, 80-day re-upload calendar, Caddy `/dl` with `handle_path` + `handle { reverse_proxy }`, keystore + `versionCode` custody, 2027 limited-distribution enrolment for GMS phones only.
- **Day-0 parallelism for the long waits** (Apple enrolment, Xcode/SDK downloads) that never touch the VPS critical path — adopt only once the owner has decided to spend the ¥688.
- **Poll the friends on Day 0** for device class, iOS version, exam stage and (later) Apple-Account e-mail; it sizes the prewarm and decides the app order.
- **Android APK before iOS** as the app order: it is the real upgrade for GMS-less domestic phones (TTS + relay-free reminder) and needs no Apple wait.
- The H4 classifier/credential-neutral banner patch scheduled, not merely listed, when the credential is a claude.ai login (15 misfiled failures already in the live ledger, v-clivps:O1).
- The onboarding message's 鸿蒙 NEXT sentence and the explicit "pick one reminder channel" note.

From D2-solid (if D2 is not the base, these are mandatory grafts)
- Watch cron (fixed: drop `provider_blocked`), external uptime monitor, Lighthouse console snapshot, restore drill, `.env` into the password manager, the Day-5/6 webhook patch before offering 企业微信/飞书/Server酱³, the deferral-date copy patch, "always restart after `install.sh`" (pruned-snapshot 503, v-pwa:O3).

## 4. Blind spots — covered by none of the three plans

1. **Permanent `NOPASSWD:ALL` sudo on the service user.** All three create `sqin ALL=(ALL) NOPASSWD:ALL` and run `wd serve` as that same user; a code-execution bug in the app (or in the `claude` child) is root. `install.sh` needs `sudo -n` only for `tee` into `/etc/systemd/system`, `systemctl`, `apt-get caddy`, `/etc/caddy/Caddyfile` (`deploy/install.sh:150-170`); a sudoers rule limited to those commands, or re-enabling NOPASSWD only for upgrade runs, costs 10 minutes.
2. **Unattended SSH for the Mac-side backup pull.** launchd has no agent, no TTY: the pull needs a passphrase-less key (or `IdentityFile` in `~/.ssh/config`) and a host key already accepted for the *exact* host string used in the plist (D2 pulls by hostname after the owner only ssh'd by IP; D3 never does the interactive first ssh). A prompt turns into a silent nightly failure.
3. **`images/` is not backed up.** `wd backup` excludes images unless `--with-images` (deploy:F14) and no plan rsyncs `images/`; with photo providers dead, 30 of 31 images are Claude SVGs that cost AI calls to regenerate after a restore (security:F10). Add `--with-images` to the timer's command or `images/` to the pull.
4. **Recoverability without the owner at a keyboard is self-expiry only.** Username lock ≤ 24 h, AI pause 30 min, daily cap 00:05, monthly cap the 1st; D2's cron only notifies. A one-line cron as `sqin` that deletes `auth_throttle` rows whose `blocked_until` is more than N minutes in the future (or `wd unlock` on a schedule) and an auto-resume of a stale `claude.paused_until` when `wd claude-check` passes would let the circle self-heal; the break-glass admin (D1) protects only the owner's own access.
5. **Secrets typed inline** (`WD_ADMIN_PASSWORD='…' wd create-admin`, `printf 'https://api.day.app/<key>' > watch.url`) land in `~/.bash_history`; `wd create-admin --username <u>` prompts when stdin is a TTY (`security.py:703-731`) — use the prompt or `HISTCONTROL=ignorespace`.
6. **Reboot and OS-patch behaviour never rehearsed.** Ubuntu 24.04 ships `unattended-upgrades`; nobody runs `sudo reboot` once to confirm `word-dance.service`, the timer and Caddy come back (units are enabled by `install.sh:157`, so they should — but the pinned `claude` launcher, the wrapper path and ufw rules are worth one reboot test before friends depend on it).
7. **Caddy ACME account e-mail.** The shipped Caddyfile sets no global `email`; Let's Encrypt works without one, but the ZeroSSL fallback issuer in Caddy 2.6 needs an e-mail for EAB and logs errors otherwise — one `{ email you@example.com }` global block makes the fallback real.
8. **Prewarm window vs. friends.** Raising the daily cap to $40 while friends are active (D2/D3 Day 3) removes the mass-mark guard for that day; schedule prewarm nights before the circle is in (D1) or keep the hourly cap at 60 as the runaway brake during the window.
9. **The copied `provider_state` rows and `kv.claude.*` are the Mac's.** Only the stale `paused_until` is called out; `wd check providers` and the admin page will show the Mac's last errors until the first real fetch on the VPS (bears on blind spot 3 and D1 error 3).

## 5. Recommendation (synthesis)

Base: D2-solid — most factually correct and the only plan that stays observable and recoverable while the owner is offline (alerting cron, uptime monitor, snapshot, drill). Pull D1's speed into it, bolt D3's app track on as a gated phase, and fix the shared `sessions ORDER BY id` bug (use `created_at`) and D3's `provider_state.name` (column is `provider`).

Phase 0 "Buy & gate" (D0, 1 h): Porkbun domain via Alipay; DNSPod (TTL 600) or Cloudflare DNS-only (60 s); Lighthouse Tokyo 2c4g Ubuntu 24.04; curl gate (api.anthropic.com 401 not 403, platform.claude.com not 403, photo providers); poll friends (device, stage). Apple enrolment/Xcode only if the owner accepts the ¥688 before evidence.

Phase 1 "Live" (D1, 3–4 h): user sqin; CLI pinned 2.1.311; stop BOTH Mac agents; VACUUM INTO + images copied before `install.sh --with-caddy --with-ecdict`; `.env`: AI off, model pin, caps 6/100, SVG 0.50; DNS/TLS/HSTS; break-glass admin; backup pull (RunAtLoad, dedicated key, host key pre-accepted, log outside the rsync target); 21:00 latency test, Singapore if loss > 5 %.

Phase 2 "AI on + pilots" (D2, 2–3 h): wrapper + chosen credential + `wd claude-check` → AI on; provider check by a real fetch; Bark + Server酱 Turbo dry runs + one digest via `/api/admin/push/run`; prewarm top 1,000–2,000 of the pilots' stage overnight under temporary caps; 2–3 pilot friends that evening (single-use 14-day codes).

Phase 3 "Polish" (D3–D4, 6–8 h): manifest/icons/links, `_mount_spa` no-cache/404, InstallHint + WeChat handoff; caps restored; watch cron + uptime monitor; staggered invites; restore drill; sudoers narrowed.

Phase 4 "Hardening" (D5–D14, 1.5–2 pd): webhook body check + WeCom markdown + URL in test, then 企业微信/飞书/Server酱³; deferral-date copy; export fallback; classifier + neutral banner if the credential is a claude.ai login; `wd unlock`; `closed` on D14.

Phase 5 "Apps on purpose" (D8–D28, ≈ 6 pd, gated on the D14 numbers): D3 §5 verbatim; Android APK first (the real gain for GMS-less friends), iOS TestFlight-internal second; HarmonyOS NEXT stays web.

Mobile route: iPhone → Safari home screen + Bark; in WeChat → handoff; GMS Android → Chrome install + Server酱; GMS-less Android → vendor-browser shortcut + Server酱 Turbo, Server酱³ after Phase 4, then APK; HarmonyOS 4.x → web + Server酱; HarmonyOS NEXT → web only.

Decisions: D0 region; D1 Tokyo→Singapore; D2 credential + 48-h SVG cap; D4 channels after the patch; D14 close registration + app go/no-go; D30 caps + Capacitor 9.
