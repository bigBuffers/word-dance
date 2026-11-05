# Fact slice: deploy — fastest verified deployment path for <= 10 invited users (2026-11-04)

Scope: word-Dance @ git main 9ab13a5, `/Users/sqin/word-dance`. Two variants: (A) fresh Ubuntu 24.04 VPS with `deploy/install.sh --with-caddy`, (B) the Mac kept as the server behind a tunnel. Policy / model-licensing questions are out of scope by owner decision; only technical reachability is noted. Every code claim cites `file:line` of the checkout; web claims cite URL + access date (all accessed 2026-11-04). Behaviour marked **[verified on scratch]** was reproduced on throwaway instances (ports 8021/8022, scratch data dirs, `WD_CLAUDE_BIN=/nonexistent/claude`, `WD_WORKER_ENABLED=0`; both deleted afterwards). Nothing touched the live data dir or port 8000.

## Summary

1. `deploy/install.sh` is a sound, idempotent Ubuntu installer, but it installs nothing system-level itself: python3.12 + venv, Node >= 22 (Ubuntu 24.04's apt ships nodejs 18.19.1, so NodeSource is needed), git, curl, openssl, passwordless `sudo -n`, and a `claude` binary on PATH are hard prerequisites; Caddy comes from Ubuntu universe (2.6.2) via `apt-get` inside the script.
2. The script and the defaults assume user `sqin` under `/home`; on a VPS user named otherwise, `WD_DATA_DIR` must be exported for install.sh and for every later `wd` command, `WD_CLAUDE_PATH` must be fixed by hand, the script must not run as root, and operator messages will still say "sqin".
3. The service starts fine without a usable `claude` binary (SPA/API/dictionary data work; `wd claude-check` exits 2 at $0; a job attempt pauses AI for 30 min and flags `claude_auth`), but the install.sh preflight refuses to run without `command -v claude`; a stub on PATH or installing the CLI first are the two ways past it.
4. Admin bootstrap: the first registrant becomes admin in any mode without an invite; exporting `WD_ADMIN_*` before a first `install.sh` run does NOT work (the freshly copied `.env` template clobbers them when sourced). Create the admin with `wd create-admin` after install and before DNS/ports open, or migrate the Mac DB first (it already holds admin `sqin`, which disables the bootstrap rule entirely).
5. Data migration from the Mac is a same-commit copy: DB (schema 1/8/9 == HEAD, seed hash == `kv.seed_version`, so no migration and no re-import), plus `images/` (216 KB); never `.env`. Copying before the first install run is the cleanest; `wd restore` while stopped is the alternative.
6. Proxy semantics are identical for Caddy-on-VPS and cloudflared-on-Mac: the TCP peer is 127.0.0.1, uvicorn's ProxyHeadersMiddleware takes the right-most untrusted `X-Forwarded-For` hop and the scheme from `X-Forwarded-Proto`; with `WD_TRUST_PROXY=1` cookies are `Secure`, HSTS is sent and the CSRF Host-origin check matches an https Origin. Without `WD_TRUST_PROXY=1` every visitor shares IP 127.0.0.1 (5 registrations/h for the whole circle) and, with an empty `WD_PUBLIC_URL`, every POST fails CSRF.
7. Variant B works technically (cloudflared keeps the Host header and Cloudflare sets XFF/X-Forwarded-Proto), but inherits the laptop's sleep/logout/Wi-Fi and the hand-started SOCKS tunnel for AI; it is a demo bridge, not a service.
8. Recommended default: Variant A on a 2 vCPU / 2-4 GB Tokyo or Singapore box, `--with-caddy`, Mac DB copied in before the first run, invite mode, one 10-use invite code. Hands-on time ~2-3.5 h the first time; VPS $8.5-24/month (hosting slice numbers).

## Findings

### F1 (high) install.sh prerequisites the script does not install
- Claim: Preflight hard-requires: `python3` >= 3.12 importing `venv, ensurepip, sqlite3, zoneinfo` (Ubuntu package `python3.12-venv`), `node` >= 22 (grep on `node --version`), a `claude` on PATH, > 2048 MB free on `/home` (GNU `df --output`), `frontend/package-lock.json`, and it needs `git` (release tag via `git rev-parse`, falls back to a timestamp), `npm`, `curl` (health loop, ECDICT download), `openssl` (secret), GNU `sed -i`, `mv -T`, `ip -4 route`/`hostname -I`, `systemctl`, and passwordless `sudo -n` (without it the systemd/Caddy steps are only printed). Caddy itself is installed by the script with `apt-get install -y -qq caddy` from Ubuntu universe.
- Evidence: `deploy/install.sh:45-53` (preflight), `:61-64` (venv + pip), `:71-72` (`npm ci && npm run build --outDir $DATA/frontend-releases/<sha>.new`), `:82` (`openssl rand -hex 32`), `:94-95` (`ip route`/`hostname -I`), `:136-138` (`mv -T`), `:150-159` (systemd), `:168-170` (caddy apt + Caddyfile + reload), `:181` (curl health). `deploy/fetch_ecdict.sh:31,33` (curl, sha256sum). Ubuntu 24.04 apt versions: nodejs `18.19.1+dfsg-6ubuntu5` (https://packages.ubuntu.com/noble/nodejs, 2026-11-04) and caddy `2.6.2-6ubuntu0.24.04.3` in universe (https://packages.ubuntu.com/noble/caddy, 2026-11-04). NodeSource manual repo: key `https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key` -> `/etc/apt/keyrings/nodesource.gpg`, source `deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main`, then `apt-get update && apt-get install -y nodejs` (https://github.com/nodesource/distributions/wiki/Repository-Manual-Installation, 2026-11-04). Claude Code native installer: `curl -fsSL https://claude.ai/install.sh | bash`, launcher at `~/.local/bin/claude`; apt repository alternative `deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main`; stated hardware requirement "4 GB+ RAM" (https://code.claude.com/docs/en/setup, 2026-11-04).
- Implication: Budget 20-30 min of apt work before the script; `--dry-run` also runs the preflight, so even a rehearsal needs node, python and a `claude` on PATH. Prefer NodeSource (binary at `/usr/bin/node`, on the unit's PATH) over nvm (not on the unit's or the claude child's PATH).
- Confidence: high.

### F2 (high) The service runs without a `claude` binary; only the preflight refuses
- Claim: `wd serve` startup touches no claude binary (migrate -> seed check -> `kv.public_url_guess` -> workers), so the site serves the SPA, API and dictionary data without credentials. `wd check claude` fails without spending (exit 1); `wd claude-check` spawns the path in `WD_CLAUDE_BIN`, classifies `FileNotFoundError` as `spawn_error`, writes two `ai_calls` rows at $0.0000, sets `kv.claude.available=0`, logs `claude_unavailable` and exits 2; install.sh treats that as a WARN and continues. A real job hitting a missing or unauthenticated binary pauses AI for 30 min (`kv.claude.paused_until`), writes a `claude_auth` event with the banner text and defers the jobs; it repeats every 30 min. `WD_AI_ENABLED="0"` is the cleaner "deploy first" switch: the Claude worker's gate sleeps 30 s and flags queued lookups 暂时无法校验, `budget.check` defers content jobs 30 min at a time, nothing is marked dead. The install.sh preflight, however, exits 1 unless `command -v claude` succeeds; the repo's own tests satisfy it with a stub `claude` script (`exit 0`) on PATH.
- Evidence: `backend/wd/main.py:473-492` (startup), `:230-268` (503 page until the SPA exists); `backend/wd/ai/probe.py:142-151,184-202`; `backend/wd/ai/runner.py:440-452` (OSError -> `spawn_error`); `backend/wd/ai/common.py:36-37,265-279` (`AUTH_PAUSE = 30 min`, `claude_auth`, `kv.claude.available=0`); `backend/wd/jobs/worker.py:46,249-260` (`DISABLED_WAIT_S = 30.0`, gate); `backend/wd/ai/budget.py:39,114-119,206-207` (`DISABLED_WAIT = 30 min`); `deploy/install.sh:48-49,143`; `backend/tests/unit/test_deploy_files.py:59-79` (fake `claude` on PATH). **[verified on scratch]**: `wd migrate` applied 0001/0008/0009; `wd check claude` -> `[FAIL] claude ... executable: NO`, exit 1; `wd claude-check` -> `claude check FAILED ... (cost $0.0000)`, exit 2, `ai_calls` = 2 x `probe/spawn_error/0.0`, `kv.claude.available='0'`, `system_events = [('claude_unavailable',)]`; server then answered `GET /api/health` 200 (`needs_setup:true`) and `GET /` 503.
- Implication: "Deploy first, add credentials later" is feasible: install with the real CLI present but not logged in (or a stub), set `WD_AI_ENABLED="0"` until `wd claude-check` passes, then flip it and restart. If a stub was used, correct `WD_CLAUDE_BIN` in `.env` afterwards (install.sh writes `command -v claude` into it once).
- Confidence: high.

### F3 (high) `/home/sqin` and user `sqin` are baked into defaults, units and messages
- Claim: Defaults: `DEFAULT_DATA_DIR=/home/sqin/word-dance-data`, `claude_bin=/home/sqin/.local/bin/claude`, `claude_path=/home/sqin/.local/bin:/usr/local/bin:/usr/bin:/bin`, `claude_home` falls back to `$HOME` then `/home/sqin`; the CLI's dotenv loader looks in `$WD_DATA_DIR` or `/home/sqin/word-dance-data`; install.sh defaults `DATA` the same way, sets `RUN_USER=$(id -un)`, rewrites `WD_CLAUDE_BIN` from `command -v claude` but never `WD_CLAUDE_PATH`; the unit renders `User=__USER__`, `HOME=/home/__USER__`, `PATH=/home/__USER__/.local/bin:...`. Messages name `sqin` literally (auth banner, probe hint, `wd check claude` hint, install.sh preflight). Consequences for a VPS user `wd`: (i) `WD_DATA_DIR=/home/wd/word-dance-data` must be exported for install.sh (otherwise `install -d /home/sqin/...` fails with EACCES under `/home`, which is root-owned) and for every later `wd` command (ops.md's `~/.profile` export); (ii) set `WD_CLAUDE_PATH="/home/wd/.local/bin:/usr/local/bin:/usr/bin:/bin"` by hand; (iii) never run the script as root: `id -un`=root renders `HOME=/home/root` (root's home is `/root`) and the claude credentials lookup breaks; (iv) the `claude` login must be done as that same user because the unit's `HOME` decides which `~/.claude/.credentials.json` the child sees.
- Evidence: `backend/wd/config.py:32,85-88,170,265`; `backend/wd/cli.py:63,70`; `deploy/install.sh:8,11,49,82`; `deploy/env.example:15,53-56`; `deploy/word-dance.service:11,14-16,33-34`; `backend/wd/ai/runner.py:158-174` (child env = allow-list, HOME from service env); `backend/wd/ai/common.py:37`; `backend/wd/ai/probe.py:200`; `backend/wd/diag.py:99`; `docs/ops.md:144-190` (§5 profile export). Credentials location on Linux `~/.claude/.credentials.json` (0600): https://code.claude.com/docs/en/authentication (2026-11-04). Prior slice `public-readiness-25` agrees.
- Implication: Either create a user literally named `sqin` on the VPS (zero edits) or budget 10 min of `.env`/profile edits and accept "sqin" in messages.
- Confidence: high.

### F4 (high) Exactly which `.env` lines install.sh writes, and when
- Claim: On first creation only (file absent): copies `deploy/env.example` and rewrites `WD_SECRET_KEY` (openssl), `WD_CLAUDE_BIN` (`command -v claude`), `WD_DATA_DIR`, `WD_CONTACT_EMAIL` (prompted on a TTY unless `--contact-email`/`WD_CONTACT_EMAIL`), mode 0600. On EVERY run with `--with-caddy|--with-nginx`: `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://DOMAIN"`, `WD_TRUST_PROXY="1"`. Without a proxy flag, only while `WD_PUBLIC_URL` is empty: `http://<default-route IP>:<WD_PORT>`. `WD_FRONTEND_DIST` is filled once with `$DATA/frontend` when empty or missing. `fetch_ecdict.sh` writes `WD_ECDICT_DB_PATH`. Never touched: `WD_REGISTRATION_MODE` (template default `invite`), all budgets, `WD_ADMIN_*`, `WD_CLAUDE_PATH`, `WD_COOKIE_SECURE` (`auto`), SMTP, `WD_TZ`. Every non-comment line must match `^WD_[A-Z0-9_]+=("[^"$`\\]*"|'[^']*')$` or the script aborts, so non-`WD_` variables (an API key, a proxy for the claude child) cannot live in `.env`.
- Evidence: `deploy/install.sh:75-84,88-98,101-105,109-114`; `deploy/fetch_ecdict.sh:56-62`; `deploy/env.example:19-33,41,125-127`; `docs/DEPLOY.md` §4 table (`:296-346`).
- Implication: After the first run the operator still edits by hand: `WD_CLAUDE_PATH` (non-sqin user), optionally `WD_AI_ENABLED`, `WD_ADMIN_*` (then blank the password), budgets. An upgrade run should omit `--with-caddy` unless the Caddyfile is meant to be rewritten (the three proxy keys persist in `.env`).
- Confidence: high.

### F5 (high) Admin bootstrap: order matters, and exporting `WD_ADMIN_*` before a first install run does not work
- Claim: `POST /api/auth/register` grants `admin` to the very first user in any registration mode without an invite; `GET /api/health` advertises `needs_setup:true` while `users` is empty and the login page says 「尚无账号，首个注册的账号将成为管理员」. `wd create-admin --if-none` (install.sh step 6) uses `WD_ADMIN_USERNAME`/`WD_ADMIN_PASSWORD` when present, otherwise prints a hint and exits 0. On a FIRST run the script copies the template (both keys `""`) and sources it with `set -a; . .env`, which overwrites any exported values with empty strings, so the subsequent `create-admin --if-none` only prints the hint. Running the CLI yourself afterwards works: exported variables win over `.env` (`load_dotenv(override=False)`), or set the two keys in `.env` and run `wd create-admin --if-none`, then blank the password. If the Mac DB is restored/copied first, `users` already holds admin `sqin`, the bootstrap rule never fires and `create-admin --if-none` is a no-op.
- Evidence: `backend/wd/routers/auth.py:84-98`; `backend/wd/routers/health.py:32,42`; `frontend/src/i18n/zh.ts:24`; `backend/wd/security.py:734-766` (`cmd_create_admin`), `:703-731` (`_cli_password`, non-interactive needs the env var); `deploy/install.sh:80-82,114,144`; `backend/wd/cli.py:70`. **[verified on scratch]**: `export WD_ADMIN_USERNAME=exported-admin; set -a; . <template>; set +a` -> `WD_ADMIN_USERNAME=[]`; `wd create-admin --if-none` without the variables -> hint, exit 0; with them exported -> `created admin owner (id 1)`, health flipped `needs_setup:false`; a second call -> `users already exist; nothing to do`.
- Implication: Runbook order: install -> `wd create-admin` (or copy the Mac DB before install) -> only then DNS + open 80/443. The exposure window is small anyway: Caddy answers only the configured hostname, so an IP-only visitor never reaches the app before DNS resolves, but the ufw ordering makes it zero.
- Confidence: high.

### F6 (high) What the app sees behind a trusted local proxy (shared by A and B)
- Claim: `wd serve` runs uvicorn with `proxy_headers=WD_TRUST_PROXY, forwarded_allow_ips="127.0.0.1"`. uvicorn 0.54's `ProxyHeadersMiddleware` acts only when the TCP peer is trusted, then sets `scope["scheme"]` from `X-Forwarded-Proto` (http/https only) and `scope["client"]` to the right-most `X-Forwarded-For` entry that is not itself trusted. `deps.client_ip` (login/register throttles, `sessions.ip`) returns that peer; its own fallback also takes the LAST hop. `host_origin` substitutes `X-Forwarded-Proto` for the scheme only when `WD_TRUST_PROXY=1`; the CSRF rule accepts Origin == Host-derived origin or == origin of `WD_PUBLIC_URL`. `cookie_secure` is true when `WD_PUBLIC_URL` is https, the request scheme is https, or (trusted) `X-Forwarded-Proto: https`; HSTS is added under the same conditions.
- Evidence: `backend/wd/cli.py:140-151`; `.venv/lib/python3.12/site-packages/uvicorn/middleware/proxy_headers.py:33-60,171-186`; `backend/wd/deps.py:37,78-96,99-108,111-129`; `backend/wd/security.py:213-226`; `backend/wd/main.py:159,171-172`. **[verified on scratch, port 8022]** with `WD_TRUST_PROXY=1`, `WD_PUBLIC_URL=""`: `X-Forwarded-For: 203.0.113.9` + `X-Forwarded-Proto: https` + `Host: words.example.com` + `Origin: https://words.example.com` -> 201/200, `Set-Cookie ... Secure`, `strict-transport-security` present, `sessions.ip = 203.0.113.9`; `X-Forwarded-For: 1.2.3.4, 203.0.113.9` -> `sessions.ip = 203.0.113.9`; no proxy headers -> `sessions.ip = 127.0.0.1`, no `Secure`, no HSTS; https Origin WITHOUT `X-Forwarded-Proto` -> 403 `csrf_rejected` "Origin mismatch". With `WD_TRUST_PROXY=0`, `WD_PUBLIC_URL=https://words.example.com`: XFF ignored (`sessions.ip = 127.0.0.1`), cookie `Secure` + HSTS from the public URL, foreign Origin -> 403.
- Implication: Behind any local proxy set BOTH `WD_TRUST_PROXY="1"` and `WD_PUBLIC_URL="https://DOMAIN"`. Without trust, the whole circle shares one IP against the 5/h register and 20/10 min login throttles (`security.py:72-73`); without either, browser POSTs fail CSRF.
- Confidence: high.

### F7 (high) Caddy on the VPS supplies exactly the headers the app expects
- Claim: Caddy's `reverse_proxy` passes incoming headers through unchanged, including `Host`, except that it "sets or augments the X-Forwarded-For header field", "sets the X-Forwarded-Proto header field" and "sets the X-Forwarded-Host header field", and "by default, the proxy will ignore their values from incoming requests, to prevent spoofing" (no `trusted_proxies` in `Caddyfile.example`). The shipped Caddyfile binds the domain, enables zstd/gzip, caps bodies at 2 MB and proxies to `127.0.0.1:8000`; `WD_HOST=127.0.0.1` keeps :8000 off the public interface. Caddy obtains the certificate automatically once the A record resolves and 80/443 are reachable; `systemctl reload caddy` forces a retry.
- Evidence: https://caddyserver.com/docs/caddyfile/directives/reverse_proxy (Defaults section, 2026-11-04); `deploy/Caddyfile.example:2-5`; `deploy/install.sh:89,168-170`; `docs/DEPLOY.md:360-386` (§7). Ubuntu universe caddy 2.6.2 (F1) supports all three directives.
- Implication: With `--with-caddy` the app receives client IP = Caddy-appended hop, scheme https, Host = domain: F6's good path. Firewall: `ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable`, plus the provider's security group; never expose 8000.
- Confidence: high (docs + code); cert-retry timing medium.

### F8 (high) Cloudflare Tunnel on the Mac: headers, Host and the service URL
- Claim: Cloudflare's edge sends `CF-Connecting-IP`; `X-Forwarded-For` "has an identical value to the CF-Connecting-IP header" when absent, otherwise Cloudflare "will append the IP address of the HTTP proxy connecting to Cloudflare to the header"; `X-Forwarded-Proto` "will be set to the protocol the client used (http or https)" and "If the client set a different value, it will be overwritten". cloudflared keeps the incoming `Host` unless `httpHostHeader` is configured (default `""`): source `if o.hostHeader != "" { req.Header.Set("X-Forwarded-Host", req.Host); req.Host = o.hostHeader }`. cloudflared runs on the Mac and connects to the origin from 127.0.0.1, so uvicorn trusts it; with `WD_TRUST_PROXY=1` the app sees client IP = visitor (right-most XFF hop), scheme https (Secure cookie, HSTS), `Host: DOMAIN`, and the CSRF Host-origin check matches the browser's https Origin even before `WD_PUBLIC_URL` is set. `WD_PUBLIC_URL` must still be `https://DOMAIN` (e-mail/webhook links otherwise fall back to `kv.public_url_guess`, a LAN IP). The ingress service must be `http://127.0.0.1:8000`, not `http://localhost:8000`: `forwarded_allow_ips` is the IPv4 literal only, and `WD_HOST=0.0.0.0` listens on IPv4. Cloudflare's 125 s origin timeout (error 524) is irrelevant because Claude calls run in background workers, never inside a request. `sudo cloudflared service install` registers a launch daemon that starts at boot (logs `/Library/Logs/com.cloudflare.cloudflared.{out,err}.log`); without sudo it is a login-time launch agent.
- Evidence: https://developers.cloudflare.com/fundamentals/reference/http-headers/ (2026-11-04); https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/cloudflared-parameters/origin-parameters/ (httpHostHeader default `""`, 2026-11-04); https://raw.githubusercontent.com/cloudflare/cloudflared/master/ingress/origin_proxy.go (`httpService.RoundTrip`, 2026-11-04); https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/local-management/as-a-service/macos/ (2026-11-04); https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-524/ (125 s, 2026-11-04); `backend/wd/cli.py:147-148`; `backend/wd/deps.py:37,90-95`; `backend/wd/delivery/email.py:61-65`; current Mac `.env` (read-only): `WD_HOST="0.0.0.0"`, `WD_TRUST_PROXY="0"`, `WD_PUBLIC_URL=""`.
- Implication: Variant B needs exactly two `.env` edits (`WD_TRUST_PROXY="1"`, `WD_PUBLIC_URL="https://DOMAIN"`) and a `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`; a domain on Cloudflare DNS is required for a named tunnel (a `*.trycloudflare.com` quick tunnel changes URL each run and has no account).
- Confidence: high for header/Host facts; mainland reachability of Cloudflare's edge is deferred to the hosting slice.

### F9 (high) Variant B inherits the laptop's failure modes
- Claim: The Mac service is a launchd agent in the GUI session (`RunAtLoad`, `KeepAlive` on failure, `ExitTimeOut 300`): it stops at logout and during sleep; `cloudflared` as a launch daemon survives a reboot but the app does not come back until someone logs in; api.anthropic.com answers 403 from this network, so AI depends on a hand-started SSH SOCKS tunnel exported only inside `bin/claude-wrapper` (when it is down only AI jobs fail: 30-min pauses, `claude_auth` banner); the nightly backup lives on the same disk; the LAN IP changes and `WD_PUBLIC_URL` was left empty for that reason. Nothing in the code mitigates host sleep: a `wd serve` that stalls > 90 s simply loses and re-acquires the worker lease.
- Evidence: `~/Library/LaunchAgents/com.word-dance.server.plist` (read 2026-11-04: `RunAtLoad`, `KeepAlive SuccessfulExit=false`, `ThrottleInterval 5`, `ExitTimeOut 300`, env `WD_DATA_DIR`, no proxy); memory notes `macos-local-install.md` and `claude-cli-macos-needs-login-env.md` (2026-11-02); `backend/wd/jobs/lease.py:32-33` (TTL 90 s, renew 30 s); `docs/ops.md:206`.
- Implication: B is acceptable for a same-day demo to friends with `caffeinate -s` / `pmset -a sleep 0` and the lid open; it is not a 24x7 service and still needs a domain on Cloudflare.
- Confidence: high.

### F10 (medium) `ssh -R` / frp instead of Cloudflare
- Claim: `ssh -R 8000:127.0.0.1:8000 vps` plus Caddy on the VPS (`reverse_proxy 127.0.0.1:8000`) reproduces Variant A's header semantics: Caddy terminates TLS and sets XFF/X-Forwarded-Proto, sshd delivers the bytes to the Mac's ssh client, which connects to 127.0.0.1:8000, so the trusted-peer rule holds. frp's HTTP proxy type adds `X-Forwarded-For` "enabled by default"; its TCP type can only pass the client IP via Proxy Protocol (`transport.proxyProtocolVersion = "v2"`), which uvicorn does not parse, so use `type = http(s)` terminated at frps or put Caddy in front. Both need a VPS, keep-alive/autossh supervision, and still leave the app on the laptop.
- Evidence: Caddy defaults (F7); `backend/wd/deps.py:37,90-95`; https://gofrp.org/en/docs/features/common/realip/ (2026-11-04).
- Implication: Once a VPS exists, Variant A dominates; the ssh/frp route is only for keeping the Mac's claude login while renting the smallest box.
- Confidence: medium (frp header behaviour from docs only; not exercised).

### F11 (high) Data migration from the Mac: what, when, compatibility
- Claim: Copy (1) the database as a single consistent file: a `wd backup` gzip (VACUUM INTO + integrity_check; the nightly file `backups/word-dance-20261104-0330.db.gz`, 1.9 MB, already exists) or, for a final cutover after stopping the Mac agent, `sqlite3 word-dance.db "VACUUM INTO '/path/copy.db'"`; (2) `images/` (216 KB, 30 shard dirs) with `rsync -a`; (3) NOT `.env` (Mac-specific `WD_DATA_DIR`, `WD_CLAUDE_BIN` wrapper, `WD_CLAUDE_PATH=/opt/homebrew/...`, `WD_LOG_FILE`; `WD_SECRET_KEY` only protects unexpired e-mail codes). Compatibility: the live DB's `schema_migrations` = (1 init, 8 fk_child_indexes, 9 strip_phonetic_delimiters) which is exactly HEAD's `backend/wd/migrations/` set, so `wd migrate` reports 0 pending; `kv.seed_version = a68127812a43c4...` equals `sha256(data/seed/vocab.jsonl.gz)` at HEAD, so neither install.sh's `import-seed` nor the startup seed check re-imports; `users` holds admin `sqin` (F5). Carried-over kv to know about: `worker_lease` (expires <= 90 s after the copy; `wd restore` refuses while it looks live, so stop the Mac agent first or wait 2 min), `public_url_guess` (rewritten at every start), `claude.available=1 / flag_tier=1 / version=2.1.292` (stale: the VPS believes claude works until the first call or `wd claude-check`), `claude.paused_until` (past), `backup.last` (stale name). Timing: (i) before the first install.sh run: create `$WD_DATA_DIR` 0700, place `word-dance.db` and `images/`, run the script (step 2 `install -d` keeps the directory, migrate/import-seed/create-admin are all no-ops); (ii) after: `sudo systemctl stop word-dance && wd restore <file.db.gz> --yes && sudo systemctl start word-dance` (restore gunzips next to the target, integrity-checks, checkpoints, keeps a `.bak-<ts>` hard link, swaps atomically). Frontend snapshot/symlink and seed import happen automatically in install.sh; images are re-fetched if missing.
- Evidence: live copy `.../scratchpad/quick/live-copy.db` queried 2026-11-04 (`schema_migrations`, `kv`, `users`, journal_mode wal); `ls backend/wd/migrations/` (0001, 0008, 0009); `shasum -a 256 data/seed/vocab.jsonl.gz`; `backend/wd/main.py:303-315` (seed_check), `:473-492`; `backend/wd/seed.py:248-287` (idempotent, `kv.seed_version`); `backend/wd/backup.py:444-531` (restore; refusals `:463-468`), `:310,321`; `backend/wd/jobs/lease.py:47-63`; `deploy/install.sh:57,140-144`; `docs/ops.md:67-88` (§3); Mac data dir listing (read-only, 2026-11-04): `images` 216K, `backups` 5.4M, `frontend -> frontend-releases/9ab13a5`.
- Implication: Copy-before-install removes the admin-bootstrap race and the restore refusals; budget 20-30 min including the scp.
- Confidence: high.

### F12 (high) Invite flow for the circle
- Claim: `wd invite --uses N --days D --note TEXT`: N in 1-100 (default 1), D in 1-365 or absent (never expires); the code is printed once on stdout (metadata on stderr), format `XXXX-XXXX-XXXX-XXXX` over a 32-character alphabet without 0/O/1/I (80 bits), stored as sha256 only, consumed atomically with `uses < max_uses AND not expired`. Admins can also create and list codes in the UI (管理 -> 邀请码; `POST/GET /api/admin/invites`). Registration is throttled 5/h per client IP and login 20/10 min per IP; the first account needs no code.
- Evidence: `backend/wd/security.py:64-66,72-73,377-419,817-834,858-862`; `backend/wd/routers/admin_users.py:122-140`; `frontend/src/api/endpoints.ts:515-518`; `backend/wd/routers/auth.py:84,96-98`. **[verified on scratch]**: `wd invite --uses 5 --days 7 --note friends` -> stdout `C7AJ-XARC-XN69-PXFV`, stderr `invite created: uses 5, expires 2026-11-11T11:22:01Z`; registration with that code -> 201.
- Implication: One `wd invite --uses 10 --days 14` covers the circle; if several friends register from one NAT (office/dorm) within an hour the 5/h limit bites, so stagger or raise it in code.
- Confidence: high.

### F13 (high) Upgrades and downtime
- Claim: `cd <repo> && git pull && deploy/install.sh` (no proxy flag needed on upgrades) upgrades pip/npm deps, builds the SPA into `frontend-releases/<sha>.new` BEFORE stopping, stops the unit, publishes the snapshot with one atomic rename (two newest kept), runs `wd migrate` (pre-migrate gzip first), `import-seed` (no-op unless the seed changed), restarts; downtime ~ migration time + 3 s. Without passwordless sudo the old process keeps serving and the script says so. The script follows the installed unit's data dir when `WD_DATA_DIR` is unset and refuses a differing value without `--move-data`.
- Evidence: `deploy/install.sh:30-41,70-72,117-141,150-159,178-186`; `docs/ops.md:90-142` (§4); `docs/DEPLOY.md:410-414` (§10).
- Implication: Routine upgrade is one command and < 1 min of downtime; schedule outside push times.
- Confidence: high.

### F14 (high) Backups and pulling them to the Mac
- Claim: `word-dance-backup.timer` runs `wd backup --keep-daily 14 --keep-weekly 8` at 03:30 Asia/Shanghai (+<= 10 min jitter, `Persistent=true`); output `backups/word-dance-YYYYMMDD-HHMM.db.gz` 0600 under the 0700 data dir; images excluded unless `--with-images`; `.env` excluded; `kv.backup.last` shown in admin health. Off-box copy from the Mac: `rsync -a --delete wd@VPS:/home/wd/word-dance-data/backups/ ~/word-dance-vps-backups/` (macOS ships openrsync 29-protocol compatible with GNU rsync; `scp -r` also works) scheduled by a Mac launchd agent or cron; the SSH login must be the service user because of the 0700 directory.
- Evidence: `deploy/word-dance-backup.timer:5-7`; `deploy/word-dance-backup.service:6-10`; `backend/wd/backup.py:1-25,248-280`; `docs/ops.md:26-65` (§2, rsync at 51-55); `which rsync` -> `/usr/bin/rsync` (openrsync, protocol 29) on the Mac.
- Implication: Add the Mac-side pull (or any object-store copy) on day 1; test one `wd restore` into `$DATA/tmp` per ops.md §2.
- Confidence: high.

### F15 (medium) Build footprint on the VPS; swap
- Claim: Measured on the Mac (arm64, warm cache): `vite build` 0.52 s wall, peak RSS 201 MB, 117 modules, 704 KB output; `frontend/node_modules` is 109 MB, so `npm ci` (download + extract) and `pip install` (manylinux wheels for bcrypt/Pillow/pydantic-core; no compiler needed) dominate the first run. The Claude Code docs state 4 GB+ RAM as the CLI requirement, which the short `-p` calls exercise far less than an interactive session but which argues for a 2-4 GB box.
- Evidence: `/usr/bin/time -l npm run build -- --outDir <scratch>` (2026-11-04); `du -sh frontend/node_modules`; `backend/requirements.txt`; https://code.claude.com/docs/en/setup (system requirements, 2026-11-04).
- Implication: 2 GB RAM is comfortable; on a 1 GB plan add a 2 GB swapfile before `install.sh` (`fallocate -l 2G /swapfile; chmod 600; mkswap; swapon; fstab`). Expect `npm ci` to take 1-3 min on a small VPS.
- Confidence: medium (Mac is not the VPS).

### F16 (high) AI budget defaults relevant to 10 users (security slice owns the policy)
- Claim: Defaults in `.env`/config: `WD_AI_DAILY_BUDGET_USD=3.00`, `WD_AI_MONTHLY_BUDGET_USD=40.00`, `WD_AI_PREWARM_DAILY_BUDGET_USD=1.00`, `WD_AI_HOURLY_CALL_CAP=60`, `WD_AI_SVG_DAILY_BUDGET_USD=0.50`, per-call caps 0.25/0.15/0.40/0.10; there is no per-user quota; `WD_AI_ENABLED=0` and `kv.claude.enabled` are the kill switches.
- Evidence: `backend/wd/config.py:99-107`; `deploy/env.example:72-83`; `backend/wd/ai/budget.py:114-119,206-216`.
- Implication: Leave defaults for the circle; note that one enthusiastic user can consume the shared daily cap (prior slice `public-readiness-5`).
- Confidence: high.

### F17 (high) Optional ECDICT
- Claim: `--with-ecdict` (or `deploy/fetch_ecdict.sh $DATA`) downloads the pinned 216 MB GitHub release zip, verifies sha256, extracts `stardict.db` (851 MB) with `python3 -m zipfile`, needs > 1.1 GB free in `$DATA`, writes `WD_ECDICT_DB_PATH` into `.env` (restart needed); idempotent when present; not included in backups. Without it, words outside the seed are validated by a Claude lookup instead of instantly.
- Evidence: `deploy/fetch_ecdict.sh:12-24,44-66`; `deploy/install.sh:146`; `docs/ops.md:212-218` (§7).
- Implication: Worth enabling on a 25+ GB disk (saves lookup calls); it adds ~1 GB and a few minutes.
- Confidence: high (download reachability from the VPS not verified).

### F18 (high) Installing and logging in the claude CLI on a headless VPS (mechanics only)
- Claim: Native installer puts a launcher at `~/.local/bin/claude` (symlink into `~/.local/share/claude/versions/`) and "automatically update[s] in the background"; the apt repository (`downloads.claude.ai/claude-code/apt/stable`) does not auto-update and upgrades through apt. Login on a machine without a browser: run `claude`, press `c` to copy the login URL, open it elsewhere, paste the code back at `Paste code here if prompted`; credentials land in `~/.claude/.credentials.json` (0600) of the user who ran it; an expiring login warns 3 days ahead and then fails every request until `/login`. `claude setup-token` yields a one-year `CLAUDE_CODE_OAUTH_TOKEN`, which the runner's allow-list does NOT pass through (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `HTTP(S)_PROXY`, `NO_PROXY`, `SSL_CERT_*` are). Because install.sh's `.env` validator rejects non-`WD_` lines, any such variable for the claude child must come from a systemd drop-in (`Environment=`) or a wrapper script like the Mac's.
- Evidence: https://code.claude.com/docs/en/setup and https://code.claude.com/docs/en/authentication (2026-11-04); `backend/wd/ai/runner.py:49-62,158-174`; `deploy/install.sh:110-113`; `deploy/word-dance.service:14-16`.
- Implication: Install the CLI as the service user, prefer the apt channel (or `DISABLE_AUTOUPDATER` in that user's `~/.claude/settings.json`) so the binary under the service does not change silently; run `wd claude-check` (<= $0.05) after login. Whether this login may back the service at all is the deferred policy question.
- Confidence: high for mechanics.

### F19 (low) Reachability of api.anthropic.com from a Singapore/Tokyo VPS
- Claim: Not verifiable from here (this network gets 403 without the SOCKS tunnel). A VPS in a supported country normally reaches the endpoint directly; a quick technical check once the box exists is `curl -sS -o /dev/null -w '%{http_code}\n' https://api.anthropic.com/v1/models` (expect 401 "no key", not 403), then `wd claude-check`.
- Evidence: memory note `macos-local-install.md` (403 from the owner's network); prior slice `china-compliance-hosting-25/30` (HK refused; SG/JP in the supported list).
- Implication: Pick the provider/region first, test with curl before paying for a year; numbers belong to the hosting slice.
- Confidence: low (unverified from this machine).

### F20 (high) install.sh must never be run on the Mac, and `--dry-run` is a useful rehearsal on the VPS
- Claim: The script is Linux-only (systemd, GNU `df --output`, `sed -i`, `mv -T`, `ip route`); the repo's deploy tests fail on macOS by design. On the VPS, `deploy/install.sh --with-caddy DOMAIN --dry-run` prints every mutating step with `+` and changes nothing, but the read-only preflight still runs (node, python, claude on PATH).
- Evidence: memory note `macos-local-install.md`; `deploy/install.sh:28,43-53,179`; `docs/qa.md:19`.
- Implication: Rehearse with `--dry-run` after the prerequisites are in place; keep the Mac deployment as the launchd stand-in only.
- Confidence: high.

## Variant A — fresh Ubuntu 24.04 VPS, `deploy/install.sh --with-caddy DOMAIN [--with-ecdict]`

Assumptions: provider box 2 vCPU / 2-4 GB / 25+ GB disk in Tokyo or Singapore; you log in as `root` (Alibaba/Tencent images) or `ubuntu` (AWS/Hetzner images); service user `wd`; domain `words.example.com` already registered; checkout `/home/wd/word-dance`; data `/home/wd/word-dance-data`. Replace names as needed. If you name the user `sqin`, skip the `WD_DATA_DIR`/`WD_CLAUDE_PATH` edits.

Step 0 (owner's laptop, 10 min) — prepare the data to carry over.
```bash
# stop the Mac service for a clean final copy (otherwise use the nightly backups/word-dance-YYYYMMDD-0330.db.gz)
launchctl bootout gui/$(id -u)/com.word-dance.server
sqlite3 /Users/sqin/word-dance-data/word-dance.db "VACUUM INTO '/Users/sqin/wd-migrate.db'"   # consistent single-file copy, no -wal/-shm
tar -C /Users/sqin/word-dance-data -czf /Users/sqin/wd-images.tgz images                        # 216 KB
# (restart the Mac service later if you still want it: launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist)
```
Do NOT copy `.env`.

Step 1 (VPS as root, 10 min) — user, sudo, firewall closed except SSH.
```bash
adduser --disabled-password --gecos "" wd && usermod -aG sudo wd
echo 'wd ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/wd && chmod 440 /etc/sudoers.d/wd   # install.sh needs `sudo -n`
mkdir -p /home/wd/.ssh && cp ~/.ssh/authorized_keys /home/wd/.ssh/ && chown -R wd:wd /home/wd/.ssh && chmod 700 /home/wd/.ssh
apt-get update && apt-get install -y ufw
ufw allow OpenSSH && ufw --force enable          # 80/443 stay closed until the admin exists (F5)
```
Also close everything but 22 in the provider's security group for now.

Step 2 (as `wd`, 15-25 min) — prerequisites install.sh does not provide (F1), swap (F15).
```bash
sudo apt-get install -y git curl ca-certificates gnupg openssl python3 python3-venv python3.12-venv sqlite3
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update && sudo apt-get install -y nodejs && node --version      # must print v22.x (apt's own nodejs is 18.19)
python3 -c 'import sys,venv,ensurepip,sqlite3,zoneinfo; print(sys.version)'   # >= 3.12
# swap only on a 1 GB plan:
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
# claude CLI as the SERVICE user (F18); apt channel = no silent auto-updates
sudo curl -fsSL https://downloads.claude.ai/keys/claude-code.asc -o /etc/apt/keyrings/claude-code.asc
echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main" | sudo tee /etc/apt/sources.list.d/claude-code.list
sudo apt-get update && sudo apt-get install -y claude-code && command -v claude && claude --version
#   (alternative: curl -fsSL https://claude.ai/install.sh | bash  -> ~/.local/bin/claude; then re-login the shell so ~/.local/bin is on PATH)
curl -sS -o /dev/null -w '%{http_code}\n' https://api.anthropic.com/v1/models   # technical reachability: expect 401, not 403 (F19)
```
Decide now whether to log in (`claude`, copy URL with `c`, paste the code) or defer credentials (then plan on `WD_AI_ENABLED="0"`, F2).

Step 3 (as `wd`, 5 min) — checkout and pre-placed data (F11, option i).
```bash
git clone https://github.com/bigBuffers/word-dance.git /home/wd/word-dance && cd /home/wd/word-dance && git checkout 9ab13a5   # or main
install -d -m 0700 /home/wd/word-dance-data
# from the laptop:  scp /Users/sqin/wd-migrate.db wd@VPS:/home/wd/word-dance-data/word-dance.db ; scp /Users/sqin/wd-images.tgz wd@VPS:/home/wd/
tar -C /home/wd/word-dance-data -xzf /home/wd/wd-images.tgz && chmod 600 /home/wd/word-dance-data/word-dance.db && rm /home/wd/wd-images.tgz
echo 'export WD_DATA_DIR="/home/wd/word-dance-data"' >> ~/.profile && export WD_DATA_DIR=/home/wd/word-dance-data   # every `wd` command needs it (F3)
```

Step 4 (as `wd`, 10-20 min; `npm ci` dominates) — rehearse, then install.
```bash
cd /home/wd/word-dance
deploy/install.sh --with-caddy words.example.com --contact-email you@example.com --dry-run      # prints the plan; preflight must pass
deploy/install.sh --with-caddy words.example.com --contact-email you@example.com [--with-ecdict]
```
What happens: venv + pip; SPA built into `frontend-releases/<sha>.new`; `.env` created (keys rewritten: `WD_SECRET_KEY`, `WD_CLAUDE_BIN`, `WD_DATA_DIR`, `WD_CONTACT_EMAIL`; proxy keys `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://words.example.com"`, `WD_TRUST_PROXY="1"`; `WD_FRONTEND_DIST="/home/wd/word-dance-data/frontend"`); snapshot published; `wd migrate` -> `0 pending` (copied DB) or 0001/0008/0009 (fresh); `import-seed` no-op or ~0.2 s; `wd claude-check` (<= $0.05, WARN if not logged in); `create-admin --if-none` -> "users already exist" (copied DB) or the hint; units rendered with `User=wd`, enabled, started; Caddy installed, Caddyfile written, reloaded (cert pending until DNS); health printed from 127.0.0.1:8000.

Step 5 (as `wd`, 5 min) — hand edits to `.env` (quoting rule: `KEY="value"`), then restart.
```bash
E=/home/wd/word-dance-data/.env
sed -i 's|^WD_CLAUDE_PATH=.*|WD_CLAUDE_PATH="/home/wd/.local/bin:/usr/local/bin:/usr/bin:/bin"|' $E   # non-sqin user (F3)
grep -n '^WD_REGISTRATION_MODE=' $E          # keep "invite"
# deferring credentials?  sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="0"|' $E   (F2)
# fresh DB only (no Mac copy): create the admin BEFORE DNS (F5)
WD_ADMIN_USERNAME=owner WD_ADMIN_PASSWORD='<strong password>' /home/wd/word-dance/.venv/bin/wd create-admin --if-none
sudo systemctl restart word-dance && curl -fsS http://127.0.0.1:8000/api/health     # needs_setup must be false now
```

Step 6 (DNS + TLS, 10-30 min including propagation).
```bash
# registrar: A record words.example.com -> VPS IPv4 (AAAA if you have v6), TTL 300
sudo ufw allow 80,443/tcp            # and open 80/443 in the provider's security group
sudo systemctl reload caddy && sleep 20 && curl -sSI https://words.example.com/api/health | head -3   # 200 + strict-transport-security
journalctl -u caddy -n 20 --no-pager  # "certificate obtained successfully"
```
Phone test: register page shows the invite field (not 「尚无账号…」), log in as the admin, 管理 page loads.

Step 7 (invites, 2 min).
```bash
/home/wd/word-dance/.venv/bin/wd invite --uses 10 --days 14 --note "friends"   # code printed once; or 管理 -> 邀请码
```

Step 8 (credentials later, 5 min) — if deferred: `claude` login as `wd`, `wd claude-check`, set `WD_AI_ENABLED="1"`, `sudo systemctl restart word-dance`, un-pause in 管理 if `claude.paused_until` is set.

Step 9 (backups off-box, 10 min) — on the Mac: `rsync -a --delete wd@VPS:/home/wd/word-dance-data/backups/ ~/word-dance-vps-backups/` in a launchd agent or cron at 04:30; verify one snapshot per ops.md §2.

Upgrades later: `cd /home/wd/word-dance && git pull && deploy/install.sh` (downtime ~ seconds; F13).

Time: first-timer total ~2-3.5 h (steps 1-7), ~1 h when repeated. Cost: VPS $8.5 (Tencent Lighthouse SG/Tokyo) to $24 (Lightsail) per month, domain ~$10-15/year (hosting slice figures).

## Variant B — keep the Mac, expose it through a tunnel (evaluated against the code; nothing installed)

B1. Cloudflare Tunnel (recommended form of B). Requires the domain's DNS on Cloudflare.
```bash
brew install cloudflared
cloudflared tunnel login && cloudflared tunnel create word-dance        # ~/.cloudflared/<UUID>.json
cat > ~/.cloudflared/config.yml <<'EOF'
tunnel: <UUID>
credentials-file: /Users/sqin/.cloudflared/<UUID>.json
ingress:
  - hostname: words.example.com
    service: http://127.0.0.1:8000        # not localhost (F8)
  - service: http_status:404
EOF
cloudflared tunnel route dns word-dance words.example.com
sudo cloudflared service install          # launch daemon, starts at boot (F8)
# .env (two edits) + restart the app agent:
sed -i '' 's|^WD_TRUST_PROXY=.*|WD_TRUST_PROXY="1"|; s|^WD_PUBLIC_URL=.*|WD_PUBLIC_URL="https://words.example.com"|' /Users/sqin/word-dance-data/.env
launchctl kickstart -k gui/$(id -u)/com.word-dance.server
```
What the code sees (F6, F8): TCP peer 127.0.0.1 -> trusted; `X-Forwarded-For` = visitor IP (Cloudflare appends it; right-most untrusted hop wins, spoofed first hops ignored); `X-Forwarded-Proto: https` -> `request.url.scheme=https`, cookie `Secure`, HSTS; `Host: words.example.com` preserved -> CSRF Host-origin == browser Origin; `WD_PUBLIC_URL` https -> also accepted origin and e-mail link base. Keep `WD_HOST="0.0.0.0"` (LAN access continues) or set `127.0.0.1` to limit the app to the tunnel.
What breaks or stays fragile (F9): launchd agent dies at logout and during sleep (`caffeinate -s`/`pmset`), the Mac must be logged in after a reboot, AI depends on the hand-started SOCKS tunnel, backups stay on the laptop, no uptime guarantee; a Cloudflare 524 would only occur if a request exceeded 125 s (none do). Time ~1-1.5 h. Cost: $0 beyond the domain.

B2. `ssh -R` / frp to a tiny VPS (F10): `autossh -M 0 -N -R 127.0.0.1:8000:127.0.0.1:8000 wd@VPS` plus Caddy on the VPS (`words.example.com { reverse_proxy 127.0.0.1:8000 }`); header semantics identical to Variant A; same two `.env` edits on the Mac. Needs the VPS anyway, so A wins unless the goal is to keep the Mac's claude login.

## Comparison

| | A: Ubuntu VPS + Caddy | B: Mac + Cloudflare Tunnel |
|---|---|---|
| Hands-on setup | ~2-3.5 h first time (prereqs, install.sh, DNS/TLS, data copy) | ~1-1.5 h (cloudflared, DNS, 2 `.env` keys) |
| Monthly cost (placeholders) | VPS $8.5-24 + domain ~$1 | domain ~$1; electricity; laptop tied up |
| Reliability | systemd restart, nightly timer, no sleep; cert auto-renewed by Caddy | laptop sleep/logout/Wi-Fi; app agent needs a login session; manual SOCKS tunnel for AI |
| Mainland reachability | depends on region/IP (hosting slice) | Cloudflare edge from the mainland (hosting slice) |
| Risk | hard-coded `sqin` paths, admin-bootstrap ordering, VPS egress to api.anthropic.com unverified | not a 24x7 host; two environments to keep in sync; Mac LAN exposure unchanged |
| Data continuity | copy DB + images once; backups pulled to the Mac | nothing to move; backups local only |

Recommended default: Variant A (Tokyo or Singapore, 2 vCPU / 2-4 GB, `--with-caddy`, Mac DB copied in before the first run, invite mode, one 10-use code). Use B only as a same-evening bridge while the VPS is being set up, with the lid open.

## Recommendations (effort)

1. Provision Variant A per the runbook: 0.5 person-day including the data copy and phone verification. Do it as user `sqin` to avoid the F3 edits, or as `wd` with the two `sed` lines.
2. Copy the Mac DB before the first `install.sh` run (F11): 20-30 min; it also removes the admin-bootstrap race (F5).
3. Keep `WD_AI_ENABLED="0"` until `wd claude-check` passes on the VPS, then flip it (F2): 10 min. Whether to log the CLI in there at all is the deferred policy decision.
4. Install the claude CLI from the apt `stable` channel (or disable auto-update) so the binary under systemd does not change silently (F18): 5 min.
5. Add the Mac-side `rsync` of `backups/` (F14) and run one restore drill: 30 min.
6. Code follow-ups, not blocking: generalise the `sqin`/`/home/sqin` defaults and messages (F3; 1-2 days per prior slice), make `forwarded_allow_ips` configurable (F6; 0.5 day), raise or key the 5/h registration throttle for shared NATs (F12; 0.5 day), add `WD_CLAUDE_PATH` to install.sh's first-run rewrites (0.5 h).
7. If B is used even briefly: `sudo cloudflared service install`, `caffeinate -s`, and remove the tunnel route when A is live so cookies/HSTS are not split across two origins: 1 h.

## Open questions

1. Does the chosen VPS region/provider reach api.anthropic.com (401 not 403), Wikimedia Commons and Openverse directly? Not testable from this network (F19).
2. VPS login user: `sqin` (zero edits) or another name (F3 edits)? Will the box be root-only on first login (Alibaba/Tencent) so Step 1 is needed?
3. Is the domain's DNS at a registrar that allows a 300 s TTL A record, and (for B) is it on Cloudflare DNS?
4. Will several friends register from one NAT within an hour (5/h register throttle, F12)?
5. Should the Mac's 48 contents / 31 images be carried over or regenerated? (Policy on their origin is deferred; technically the copy is trivial, F11.)
6. ECDICT on the VPS (`--with-ecdict`, +1 GB) yes/no?
7. Caddy 2.6.2 from Ubuntu universe vs Caddy's own apt repo (newer TLS defaults) — both work with the shipped Caddyfile; preference?
8. Mainland latency/blocking figures for Tokyo vs Singapore vs Cloudflare edge — hosting slice.
9. The claude login on the VPS expires and warns 3 days ahead (F18); who watches the admin banner / `claude_auth` events for a 10-person circle?
