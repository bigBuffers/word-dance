# Verification report — slice "deploy" (word-Dance quick-deploy + mobile research)

Date 2026-11-04 · checkout `/Users/sqin/word-dance` @ `9ab13a5` (main) · digest verified: `scratchpad/quick/facts/deploy.md`

Method: adversarial re-execution. Every `wd` command ran against throwaway data dirs under
`scratchpad/quick/verify-deploy/` (`dataA`, `dataB`, `dataC`, `dataD`, `dataE`) with `WD_WORKER_ENABLED=0`, `WD_DEV=1`
where noted, `WD_CLAUDE_BIN` = `backend/tests/fake_claude.py` (servers) or `/nonexistent/claude` (missing-binary
tests). HTTP behaviour was exercised on my own `wd serve` instances on **:8021** (trusted proxy) and **:8060**
(untrusted; ports 8022–8024/8031 were held by other sessions' scratch servers — one early battery hit a foreign
instance on 8022 and was discarded and re-run on 8060). The live Mac data dir and port 8000 were only read (`.env`
non-secret keys, `ls`, `du`); the live DB facts come from the read-only copy `scratchpad/quick/live-copy.db`
(copied once more into scratch and opened with `?immutable=1`). The real `claude` was never run; no tracked file
was modified (`git status` unchanged). All processes I started were stopped (`lsof` on :8021/:8060 → 0 listeners).

Verdict summary: F1 confirmed · F2 confirmed · F3 confirmed (nuance) · F5 confirmed · F6 confirmed · F8 confirmed
(documentary + app side; no tunnel run) · F9 confirmed · F11 confirmed (one count corrected) · F12 confirmed ·
F15 confirmed (measurements reproduced; Linux RAM behaviour not measurable here).

---

## F1 — install.sh prerequisites, Node 18 in Ubuntu apt, Caddy 2.6.2 from universe

**Verdict: confirmed.**

Ran / read:

- `deploy/install.sh` read in full. Preflight `:45-53`: python ≥ 3.12 + `import venv, ensurepip, sqlite3, zoneinfo`,
  `node --version | grep -Eq '^v(2[2-9]|[3-9][0-9])'`, `command -v claude` (else exit 1), GNU `df --output=avail -m /home`,
  `frontend/package-lock.json`, `sudo -n true` (else only WARN and systemd steps are printed). Installs it performs:
  pip (`:62-64`), `npm ci`/`npm run build` (`:72`), and only with a proxy flag `apt-get install -y -qq caddy` (`:168`) /
  nginx+certbot (`:171`). `git` at `:71` (falls back to a timestamp), `openssl` `:82`, `ip -4 route`/`hostname -I` `:94-95`,
  `mv -T` `:136,138`, `sed -i` `:82,89`, `curl` `:181-182`. Nothing installs python, node, git, curl, openssl or claude.
- Executed the preflight under `--dry-run` with `WD_UNIT_FILE=/nonexistent` and a scratch `WD_DATA_DIR`
  (read-only step; the scratch dir stayed empty):
  - PATH without `claude` → `claude CLI not found in PATH for sqin (expected /home/sqin/.local/bin/claude)`, exit 1.
  - PATH with a stub `node` printing `v18.19.1` → `Node >= 22 required`, exit 1.
  - PATH with a stub `claude` (`exit 0`) → passes `:49`, then dies at `:50` on BSD `df`
    (`[: : integer expression expected` / `need > 2 GB free on /home`, exit 1) — GNU coreutils is a hard dependency.
- Web (2026-11-04): https://packages.ubuntu.com/noble/nodejs → `18.19.1+dfsg-6ubuntu5` **[universe]**;
  https://packages.ubuntu.com/noble/caddy → `2.6.2-6ubuntu0.24.04.3 [security] [universe]`;
  NodeSource wiki (Repository-Manual-Installation) → key `https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key`
  into `/etc/apt/keyrings/nodesource.gpg`, source `deb [signed-by=…] https://deb.nodesource.com/node_22.x nodistro main`
  (the wiki now shows the deb822 form: `URIs: https://deb.nodesource.com/node_${NODE_MAJOR}.x/ Suites: nodistro
  Components: main`), then `apt-get install -y nodejs`; https://code.claude.com/docs/en/setup → "Hardware: 4 GB+ RAM",
  native installer `curl -fsSL https://claude.ai/install.sh | bash` (launcher `~/.local/bin/claude`, auto-updates),
  apt repo `deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main`.

Notes (not contradicting the claim): (a) the preflight accepts any `v22.x`, but `frontend/package.json` `engines.node`
is `>=22.12` (Vite 8) — NodeSource 22.x is 22.2x so fine, see omission 4; (b) Ubuntu's nodejs is in *universe*, not
main (still 18.19.1); (c) the Claude Code setup page now lists "Location: Anthropic supported countries" under system
requirements (policy question out of scope per owner).

## F2 — service runs without a working claude; check/claude-check exit codes; 30-min pause; WD_AI_ENABLED=0

**Verdict: confirmed** (every part re-executed).

- `dataA`, `WD_CLAUDE_BIN=/nonexistent/claude`: `wd migrate` → `applied 0001_init.sql / 0008 / 0009`, exit 0.
  `wd check claude` → `[FAIL] claude … executable: NO … probe: available=never probed`, **exit 1**.
  `wd claude-check` → `claude spawn failed: [Errno 2] …` ×2, `claude check FAILED: tier 1: FileNotFoundError …;
  tier 0: … (cost $0.0000)`, `WARN: … run \`claude\` once as sqin …`, **exit 2**; DB after:
  `ai_calls` = `probe|spawn_error|0.0` ×2, `kv.claude.available=0`, `system_events` = `claude_unavailable`.
- `wd serve` (:8021, fake claude, empty frontend dir): startup log shows migrations, `WD_WORKER_ENABLED=0`, "ready";
  no `ai_calls` row until a job ran (startup touches no binary). `GET /api/health` → 200
  `{"status":"ok","registration_mode":"invite","needs_setup":true}`; `GET /` → **503** (前端尚未构建 page).
- Job path, executed: logged in as a user, `POST /api/bank/add {"text":…}` → `status:"pending_ai"`, job
  `lookup_word queued` (20-s debounce; pulled forward in the scratch DB), then `wd worker-once` with
  `WD_CLAUDE_BIN=/nonexistent/claude` →
  `lookup_word: claude spawn_error — AI paused until 2026-11-04T12:16:10Z` (now was 11:46:10 → **30 min**);
  `kv.claude.paused_until=2026-11-04T12:16:10Z`, `kv.claude.available=0`;
  `system_events` = `claude_auth {"banner_zh": "Claude CLI 未登录，请以 sqin 身份运行 claude 完成登录", "error":
  "FileNotFoundError…", "paused_until": …, "status": "spawn_error"}`; job `queued attempts=0 run_after=12:16:10`
  (deferred, **not dead**); `ai_calls` += `lookup|spawn_error|0.0`.
- `WD_AI_ENABLED=0` (pause cleared, job due): `wd worker-once` → job re-deferred to `run_after=12:17:00`
  (= now + 30 min, `budget.DISABLED_WAIT`), `dead_count=0`. The 30-s gate of the in-process Claude worker
  (`worker.py:46,249-258`) is covered by `tests/integration/test_worker.py::test_claude_worker_idles_while_ai_is_disabled`
  and `…::test_disabled_ai_flags_queued_lookups_as_unverifiable_and_resumes_cleanly` — both **passed**
  (`3 passed, 10 deselected in 121 s` together with `test_overloaded_and_auth_outcomes_defer_and_pause`);
  `tests/unit/test_runner.py::test_spawn_error_when_the_binary_is_missing` passed.
- Code: `runner.py:444-451` (OSError → `spawn_error`), `common.py:36-37,264-279` (`AUTH_PAUSE=30 min`, `claude_auth`
  event, `claude.available=0`, `queue.defer`), `probe.py:142-151,184-201`, `budget.py:39,114-119,206-207`,
  `main.py:473-492`, `install.sh:48-49` (preflight refusal, executed in F1) and `:143` (`|| echo "WARN: claude check failed …"`).

## F3 — user `sqin` / `/home/sqin` baked into defaults, units and messages

**Verdict: confirmed** (one nuance on how often `WD_DATA_DIR` must be exported for install.sh).

- `grep -rn sqin backend/wd deploy` → 16 non-comment hits: `config.py:32,85,87,170,328,330`, `cli.py:63`,
  `runner.py:162`, `diag.py:99`, `probe.py:200`, `common.py:37`, `install.sh:8,49`, `env.example:15,53,56`.
- Messages executed: `wd claude-check` printed `run \`claude\` once as sqin to log in`; the `claude_auth` event carried
  `请以 sqin 身份运行 claude 完成登录` (F2 run).
- `install.sh:82` rewrites `WD_SECRET_KEY`, `WD_CLAUDE_BIN` (= `command -v claude`), `WD_DATA_DIR`, `WD_CONTACT_EMAIL`
  only — never `WD_CLAUDE_PATH` (confirmed by reading the whole script).
- Root case executed: rendering `deploy/word-dance.service` with `__USER__=root` gives `User=root`,
  `Environment=HOME=/home/root`, `Environment=PATH=/home/root/.local/bin:…` — root's real home is `/root`, so the
  claude child (`runner.py:162` takes `HOME` from the service env) would look for credentials in the wrong place.
- Credentials location: https://code.claude.com/docs/en/authentication — "On Linux, credentials are stored in
  `~/.claude/.credentials.json` with file mode 0600" → the login must happen as the unit's `User=`.
- Nuance: `install.sh:10,34-36` follows the installed unit's `EnvironmentFile=` when `WD_DATA_DIR` is unset, so the
  export is mandatory for the **first** install.sh run (default `/home/sqin/word-dance-data`, `install -d` under
  root-owned `/home` fails) and for **every `wd` CLI command** (`cli.py:63`); later install.sh runs work without it
  (an export that matches the unit is accepted, a differing one is refused with exit 2).

## F5 — first registrant is admin; `WD_ADMIN_*` export before a first install.sh run is clobbered

**Verdict: confirmed** (all parts executed).

- `bash -c 'export WD_ADMIN_USERNAME=exported-admin WD_ADMIN_PASSWORD=…; set -a; . deploy/env.example; set +a; echo …'`
  → `WD_ADMIN_USERNAME=[] WD_ADMIN_PASSWORD=[]` (template lines 126-127 are `""`; `install.sh:114` sources the file
  this way after copying it at `:80`).
- `wd create-admin --if-none` (dataA, no `.env`, variables unset, stdin not a TTY) →
  `no admin configured (WD_ADMIN_USERNAME unset): the first account registered on the site becomes admin`, exit 0.
  With `WD_ADMIN_USERNAME=owner WD_ADMIN_PASSWORD=…` exported → `wd: password taken from $WD_ADMIN_PASSWORD` /
  `created admin owner (id 1)`, exit 0; second call → `users already exist; nothing to do`, exit 0.
- `dataD`: `.env` containing `WD_ADMIN_USERNAME=""`/`WD_ADMIN_PASSWORD=""` + the two variables exported →
  `created admin owner2 (id 1)` — exported values win (`cli.py:70` `load_dotenv(..., override=False)`).
- HTTP (:8021, `WD_REGISTRATION_MODE=invite`): first `POST /api/auth/register` without a code → **201**,
  `"role":"admin"`; `/api/health` flipped to `needs_setup:false`; second registrant without a code → 403
  `invalid_invite`. Code `auth.py:88-98` (`bootstrap = COUNT(*)==0 → role admin`), `health.py:32,42`.
- Copied Mac DB: `users` = `1|sqin|admin` (live copy and after the F11 restore), so `COUNT(*)==0` is never true and
  `create-admin --if-none` is a no-op. Tests passed: `test_register_first_user_is_admin_with_defaults_and_cookie`,
  `test_invite_mode_bootstrap_then_codes`, `test_closed_mode_only_allows_the_bootstrap_registration`,
  `test_concurrent_first_registrations_yield_exactly_one_admin`.

## F6 — proxy semantics behind a trusted local proxy (uvicorn 0.54, WD_TRUST_PROXY 1/0)

**Verdict: confirmed** (re-executed on my own instances; results identical to the digest's).

- `uvicorn 0.54.0` (`.venv`); `proxy_headers.py:35-61` acts only when the peer is trusted, sets `scope["scheme"]`
  from `X-Forwarded-Proto` (`http/https/ws/wss`) and `scope["client"]` via `get_trusted_client_address`
  (`:169-187`, iterates the XFF list **in reverse**, first untrusted host wins). `cli.py:147-148`
  (`proxy_headers=cfg.trust_proxy, forwarded_allow_ips="127.0.0.1"`), `deps.py:37,78-96,99-129`,
  `security.py:72-73,213-226`, `main.py:159,171-172`.
- :8021, `WD_TRUST_PROXY=1`, `WD_PUBLIC_URL=""`:
  `X-Forwarded-For: 1.2.3.4, 203.0.113.9` + `X-Forwarded-Proto: https` + `Host/Origin words.example.com` →
  201, `set-cookie: … SameSite=lax; Secure`, `strict-transport-security: max-age=31536000; includeSubDomains`,
  `sessions.ip = 203.0.113.9`, throttle key `register:ip:203.0.113.9` (spoofed first hop ignored);
  no proxy headers → 201, cookie without `Secure`, no HSTS, `sessions.ip = 127.0.0.1`;
  https `Origin` **without** `X-Forwarded-Proto` → 403 `csrf_rejected` `"reason":"Origin mismatch"`;
  missing `X-WD-Request` → 403 `"missing X-WD-Request header"`.
- :8060, `WD_TRUST_PROXY=0`, `WD_PUBLIC_URL=""`: XFF+XFP+https Origin → 403 Origin mismatch; http Origin → 201 with
  `sessions.ip = 127.0.0.1` and `register:ip:127.0.0.1` (XFF ignored, no `Secure`).
  `WD_PUBLIC_URL=https://words.example.com`: https Origin → 201 with `Secure` + HSTS (from the public URL),
  `sessions.ip` still `127.0.0.1`; foreign Origin → 403.
- Throttles under trust: 6th registration attempt from one XFF IP → 429 `retry_after_s: 3599`; 21st login from one
  IP → 429 (see omission 1 for the 423 seen earlier). `tests/integration/test_deps.py` (4 tests incl.
  `test_client_ip_is_the_proxy_appended_hop_never_the_first`, `test_rotating_first_hops_do_not_bypass_the_per_ip_throttles`)
  passed.

## F8 — Cloudflare Tunnel on the Mac satisfies the proxy contract

**Verdict: confirmed** for the documented header/Host behaviour and for the app-side contract (executed in F6);
the tunnel itself was **not** run — `cloudflared` is not installed on this Mac (`which cloudflared` → not found,
no `/Library/LaunchDaemons/com.cloudflare.*`), so end-to-end remains documentary.

- https://developers.cloudflare.com/fundamentals/reference/http-headers/ (2026-11-04): XFF — "If there was no
  existing X-Forwarded-For header … identical value to the CF-Connecting-IP header"; otherwise "Cloudflare will
  append the IP address of the HTTP proxy connecting to Cloudflare to the header". X-Forwarded-Proto — "set to the
  protocol the client used (http or https)… If the client set a different value, it will be overwritten."
- cloudflared origin parameters page: `httpHostHeader` default `""` ("Sets the HTTP Host header on requests sent to
  the local service"); `connectTimeout` default `30s`.
- `ingress/origin_proxy.go` `httpService.RoundTrip`: `if o.hostHeader != "" { req.Header.Set("X-Forwarded-Host",
  req.Host); req.Host = o.hostHeader }` — Host preserved by default; cloudflared sets no XFF/XFP of its own (they
  come from the edge, consistent with the claim).
- Mac `.env` (read-only): `WD_HOST="0.0.0.0"`, `WD_TRUST_PROXY="0"`, `WD_PUBLIC_URL=""` — as claimed.
  `delivery/email.py:60-66` falls back to `kv.public_url_guess` (live value `http://10.23.147.103:8000`).
- Nuance on "must be http://127.0.0.1:8000, not localhost": `socket.create_server(("0.0.0.0",0)).family` = AF_INET
  (IPv4 only) and `getaddrinfo("localhost")` = `['127.0.0.1','::1']`, so a Go dialer given `localhost` gets
  ECONNREFUSED on `::1` and falls back to `127.0.0.1`, which uvicorn trusts — `localhost` would work in practice;
  `127.0.0.1` is still the right setting (a dual-stack bind would make a `::1` peer untrusted, since
  `forwarded_allow_ips` is the IPv4 literal only).

## F9 — keeping the Mac inherits the laptop's failure modes

**Verdict: confirmed.**

- `~/Library/LaunchAgents/com.word-dance.server.plist` (read): `RunAtLoad` true, `KeepAlive {SuccessfulExit=false}`
  (restart only after a failure), `ThrottleInterval 5`, `ExitTimeOut 300`, env `WD_DATA_DIR/HOME/PATH/LANG`, no
  proxy; `launchctl list` → `1204 0 com.word-dance.server` (GUI session agent).
- `pmset -g`: **`sleep 1`** (minute) "(sleep prevented by caffeinate, powerd)" — the only inhibitor was a transient
  `caffeinate -i -t 300` from a shell session; `hibernatemode 3`. Without a caffeinate the laptop sleeps after one
  idle minute.
- Memory notes `macos-local-install.md` / `claude-cli-macos-needs-login-env.md` and
  `/Users/sqin/word-dance-data/bin/claude-wrapper` (read): `HTTP_PROXY/HTTPS_PROXY=http://127.0.0.1:8118` exported
  only inside the wrapper (privoxy → hand-started SSH SOCKS tunnel), "api.anthropic.com answers 403 … from this
  network". Live DB shows the consequence: 8 consecutive `claude_auth` events 2026-11-02 22:09 → 2026-11-03 02:26
  (30-min cadence) and 19 `auth` ai_calls.
- Backups local: `backups/` 5.4 MB, three nightly `.db.gz` on the same disk.
- Code: `lease.py:32-33` (TTL 90 s, renew 30 s); `grep -rniE "caffeinate|pmset|IOPMAssertion|wake|hibernat"
  backend/wd` → no matches; the scheduler only *detects* a gap (`scheduler.py:19,386` → `downtime` event when the
  tick gap exceeds 10 min); `ops.md:206` describes lease loss/re-acquire.

## F11 — Mac data migrates as a same-commit copy; restore refusals

**Verdict: confirmed**, with one count corrected: `images/` contains **28** shard directories (`ls | wc -l` = 28;
the directory's link count of 30 is 28 + `.` + `..`), size 216 KB as claimed.

- Live copy: `schema_migrations` = `(1,init) (8,fk_child_indexes) (9,strip_phonetic_delimiters)`;
  `ls backend/wd/migrations` = `0001_init.sql 0008_fk_child_indexes.sql 0009_strip_phonetic_delimiters.sql`;
  `kv.seed_version = a68127812a43c47ff011828b7894b789ba0fcf69cc8e76f1ec6c2356e81a3336` =
  `shasum -a 256 data/seed/vocab.jsonl.gz`; `users` = `1|sqin|admin|2026-11-02T07:46:21Z`; counts words 9162,
  word_contents 48, word_images 31, jobs 132, ai_calls 68, invite_codes 0.
- Executed on `dataE` (copy of the live copy): `wd migrate` → `0 pending / schema version 9`; `wd import-seed` →
  `seed up to date (sha256 a68127812a43…)`; `wd backup` → `word-dance-20261104-1946.db.gz (1916667 bytes)`;
  with `kv.worker_lease.expires_at = now+60 s` → `wd restore <gz> --yes` → `word-dance.service is running — watch
  journalctl …`, **exit 2**; lease expired → `restored … / previous database kept at word-dance.db.bak-20261104-194637`,
  exit 0; afterwards `users:sqin/admin`, `migrations:1,8,9`.
- Carried-over kv seen in the live copy: `claude.available=1`, `claude.flag_tier=1`, `claude.version=2.1.292`,
  `claude.paused_until=2026-11-03T02:56:20Z` (past), `backup.last`, `public_url_guess=http://10.23.147.103:8000`,
  `worker_lease {"instance": "M0VD9WMGGQ:1204:…"}`. Code `backup.py:444-531` (refusals `:463-468`; the
  `systemctl is-active` refusal applies only on the VPS), `lease.py:47-63`, `main.py:303-315`, `seed.py:248-287`,
  `install.sh:57,140-144`. Mac data dir: `frontend -> frontend-releases/9ab13a5`, `.env` 0600 (not to be copied:
  it holds `WD_CLAUDE_BIN=…/bin/claude-wrapper`, `WD_CLAUDE_PATH=/opt/homebrew/bin:…`, `WD_LOG_FILE=…`).

## F12 — invite codes, admin endpoint, registration/login throttles

**Verdict: confirmed.**

- `wd invite --uses 5 --days 7 --note friends` → stdout `UJCQ-5NXU-24G9-ZM3Y`, stderr `invite created: uses 5,
  expires 2026-11-11T11:38:42Z`; `invite_codes` row stores `code_hash` (sha256 hex) only; registration with the code
  → 201 and `uses=1`. Bounds executed: `--uses 0|101` → exit 2 `--uses must be between 1 and 100`; `--days 0|366` →
  exit 2 `--days must be between 1 and 365`; `--uses 100 --days 365` ok; defaults `uses 1, expires never`.
- 2000 generated codes: 16 symbols over the 32-char alphabet (no `0 O 1 I` found) → 80 bits
  (`security.py:64-66,377-379`); `consume_invite` is one `UPDATE … WHERE uses < max_uses AND (expires_at IS NULL OR
  expires_at > ?)` with `rowcount == 1` (`:411-419`).
- Admin HTTP (:8021): `POST /api/admin/invites {"max_uses":10,"expires_in_days":14,"note":"friends-ui"}` → 201
  `{"id":4,"code":"6K4T-6MXX-5QMR-Y67H",…}`; `GET /api/admin/invites` lists them; as a non-admin → 403 `forbidden`.
  `schemas.py:1237-1240` (`InviteCreateRequest` ge=1 le=100 / 1..365); `frontend/src/api/endpoints.ts:515-518`.
- Throttles: 5 attempts/h per IP — 6th → 429 `retry_after_s 3599` (`security.py:73`, `auth.py:84`); login
  20/10 min per IP — 21st → 429 (`security.py:72`). Tests `test_register_ip_throttle_5_per_hour`,
  `test_login_ip_throttle_20_per_10_minutes`, `test_login_lockout_persists_across_app_instances` passed.

## F15 — build footprint, pip without a compiler, RAM sizing

**Verdict: confirmed** for everything measurable here; the RAM sizing (2 GB comfortable / 1 GB + 2 GB swap) is a
judgement that was not measured on Linux (only the Vite build's peak RSS was measured; `npm ci` peak was not).

- `/usr/bin/time -l npm run build --silent -- --outDir <scratch> --emptyOutDir` (node v22.23.4, npm 10.9.9, warm
  `node_modules/.vite` cache) → `0.40 real 0.33 user 0.16 sys`, `maximum resident set size 202407936` (≈ 202 MB),
  Vite "built in 128ms", output `704K` (`index-CsasxgTd.js` 302.86 kB / 99.61 kB gzip); `du -sh node_modules` = 109M.
  Checkout untouched (`git status` unchanged; `frontend/dist` not written).
- `pip download --only-binary=:all: --platform manylinux2014_x86_64 --platform manylinux_2_17_x86_64 --platform
  manylinux_2_28_x86_64 --python-version 3.12 --implementation cp --abi cp312 -r backend/requirements.txt` →
  **26 wheels, 0 sdists** (bcrypt, pillow, pydantic_core, uvloop, httptools, watchfiles, websockets, …), 17 MB —
  no compiler needed on x86_64 Linux (aarch64 not checked).
- https://code.claude.com/docs/en/setup → "Hardware: 4 GB+ RAM, x64 or ARM64 processor".

---

## Omissions / new findings

1. **Per-username login lockout (HTTP 423) — not in the digest.** `security.py:78-82,298-308`, `errors.py:61`:
   after 10 failed logins for a username the account is locked for 15 min, doubling every 5 further failures up to
   24 h, persisted in `auth_throttle` (`login:user:<name>`) — independent of the client IP. Executed: 21 bad logins
   for `owner` from one IP gave `401 ×10, 423 ×10, 429` (the IP limit only bit at the 21st). Consequence: anyone who
   knows a username (the admin's, say) can lock it out remotely; for the circle it is a support question ("locked
   for 15 min"). Evidence: run on :8021 2026-11-04 11:38 UTC; `tests/integration/test_auth.py::test_login_lockout_persists_across_app_instances`.
2. **The 5/h registration throttle is charged before the invite code is checked.** `auth.py:84` (`rate_limit`)
   precedes `:96-98` (`consume_invite`). Executed: five `403 invalid_invite` attempts from one IP, then `429
   retry_after_s 3599`. Five mistyped codes from one friend (or from one NAT, or from the whole circle when
   `WD_TRUST_PROXY=0` makes everyone `127.0.0.1`) burn the hour; the digest counts only successful registrations.
3. **install.sh's free-space gate is on `/home`, not on `$WD_DATA_DIR`, and needs GNU `df`.** `install.sh:50`
   `df --output=avail -m /home`: a VPS whose data lives on another mount (e.g. `/data`) still needs > 2 GB free on
   `/home`, and a missing `/home` fails the preflight. Executed on macOS: BSD `df` → `integer expression expected`
   → exit 1 (same line).
4. **Node gate mismatch.** `install.sh:47` accepts any `v22.*`, while `frontend/package.json` `engines.node` is
   `>=22.12` (Vite 8). NodeSource `node_22.x` ships 22.2x (the Mac has 22.23.4), so the runbook is fine, but a
   distro/nvm 22.0–22.11 would pass the preflight and fail in `npm ci`/`vite build`.
5. **Variant B starts from zero on this Mac and the box is set to sleep after one minute.** `which cloudflared` →
   not found, no cloudflared LaunchDaemon; `pmset -g` → `sleep 1` (minute), currently prevented only by a transient
   `caffeinate -i -t 300`. B needs `sudo pmset -c sleep 0` (or a permanent `caffeinate -s`) *before* the tunnel work,
   otherwise the first idle minute takes the service down; the digest mentions caffeinate but not the 1-minute setting.
6. **`localhost` vs `127.0.0.1` for any local proxy (nuance to F8).** With `WD_HOST=0.0.0.0` the app listens on
   IPv4 only (`socket.create_server(("0.0.0.0",0)).family == AF_INET`), so a proxy dialing `localhost`
   (`['127.0.0.1','::1']`) falls back to 127.0.0.1 and is trusted; the brittle case is only a dual-stack bind
   (`::`), where a `::1` peer is not in uvicorn's `forwarded_allow_ips="127.0.0.1"` (`deps.TRUSTED_PROXY_PEERS`
   lists `::1` only for the no-middleware fallback) and every visitor would become `::1`. Keep `127.0.0.1` in the
   ingress and keep `WD_HOST` IPv4.

Method notes: ports 8022–8024/8031 were occupied by other sessions' `wd serve` scratch instances during this run;
the untrusted-proxy battery was therefore executed on :8060 after the 8022 attempt was discarded. Scratch artefacts
left for inspection under `scratchpad/quick/verify-deploy/` (`dataA`–`dataE`, `serverB.log`, `serverC-*.log`,
`frontend-build/`, `wheels/`, `build-time.txt`). No process of mine is still running.
