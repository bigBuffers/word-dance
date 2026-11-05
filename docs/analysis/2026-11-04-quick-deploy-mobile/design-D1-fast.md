# Design D1 — "fastest credible path": word-Dance for a circle of ≤ 10 invited friends

Date 2026-11-04 · repo `/Users/sqin/word-dance` @ main `9ab13a5` · owner: solo part-time, Mac (macOS 26.7.1, Apple Silicon, node 22.23.4, python 3.12, no Xcode, no JDK/Android SDK), mainland China, api.anthropic.com reachable only through a hand-started SOCKS tunnel.

How to read citations: `(deploy:F5)` = finding F5 of the research digest `facts/deploy.md`; `(v-deploy:F5)` = the verifier's verdict on it in `verify/deploy.md`; `(v-security:O1)` = omission/new finding 1 of `verify/security.md`. Verify files override digests where they differ. `file:line` refers to the checkout at `9ab13a5`. Policy / model-licensing / credential-choice questions are deferred by owner direction and are not analysed; only technical facts about the `claude -p` runner are stated, and the plan stays credential-neutral.

Placeholders used below: `DOMAIN` (e.g. `wd.example.com`), `VPS_IP`, `YOU@example.com` (contact e-mail for the Wikimedia User-Agent), `<friend>`.

---

## 0. One-paragraph pitch

**Day 1** (one evening, ≈ 3–4 h hands-on): word-Dance runs on a ¥42/month Tencent Lighthouse box in Tokyo (Ubuntu 24.04, Caddy TLS at `https://DOMAIN`), installed by the repo's own `deploy/install.sh --with-caddy` as user `sqin` so that not one default path or message has to change. The Mac's database (admin `sqin`, 52 user_words, 48 contents, 31 images, 5.6 MB) is copied in **before** the first install run, so the first-registrant-becomes-admin window never opens and your own study history carries over. AI is switched off (`WD_AI_ENABLED="0"`) until `wd claude-check` passes with whatever credential you choose; the spend caps are raised to $6/day and $100/month before anyone is invited; each friend gets one single-use, 14-day invite code; the first backups are already being pulled to your Mac overnight. **Day 3**: three to ten friends have logged in from Safari or their phone's own browser, have the site on their home screen, and get the daily 今日词汇 reminder through Bark (iPhone) or Server酱 → WeChat (everyone else, HarmonyOS NEXT included); the top 2,000 words of their stage are prewarmed, so 筛词/词库 open instantly. **Day 14**: zero code was shipped before the first invite; two or three small, evidence-triggered patches have gone out through the normal `git pull && deploy/install.sh` path (manifest/icons for a proper home-screen icon, a 「在浏览器打开」 hint for links opened inside WeChat, the webhook body check that makes 企业微信/飞书/Server酱³ truthful); registration is `closed`; and you have the usage numbers (who opens /today after the reminder, which phones, which reminder channel works) that decide whether the Capacitor remote-shell app (≈ 6 person-days, TestFlight-internal + sideloaded APK, no backend change) is worth starting — or not.

---

## 1. Goals and explicit non-goals

**Goals**
1. Friends can register and log in within 1–3 calendar days of you starting (target: day 2), on mainland-China phones, over plain HTTPS.
2. No code change before the first invite. Every known sharp edge is closed by configuration or procedure, not by hiding it (security digest summary: "Nothing in the code must change before inviting ≤ 10 trusted friends").
3. Do not break anything: the Mac instance stays intact as the rollback for two weeks; the VPS runs the same commit, the same schema (1/8/9) and the same seed hash, so no migration and no re-import happen at cutover (deploy:F11, v-deploy:F11).
4. Mobile = the existing SPA as a home-screen web app; reminders through the webhook channels that already exist (Bark, Server酱); apps only when evidence says so.
5. Backups off the box from day 1; the owner spends ≤ 10 minutes a day in week 1.

**Non-goals (for this plan)**
- Public launch, strangers, ToS/privacy pages, 备案 of any kind, domestic app-store listings, HarmonyOS native app.
- Web Push, APNs/FCM, service worker, offline mode.
- Any policy or credential analysis (Anthropic region/OAuth rules, domestic-model replacement, the curated-mode plan in `docs/WORD_LIBRARY_CURATION.md`): deferred by owner direction. The plan assumes the existing `claude -p` runner with a credential the owner chooses and gives the wiring for every credential type.
- Hardening beyond what a 10-friend circle needs (per-user AI quota, TOTP, audit trail, password reset by e-mail).

---

## 2. Phases, day by day

Time budget summary: Day 0 ≈ 0.5 h · Day 1 ≈ 3–4 h hands-on (+ waits) · Day 2 ≈ 1.5–2 h · Day 3 ≈ 1 h · Days 4–7 ≈ 10 min/day (+ 1.5 h if the icon patch is triggered) · Days 8–14 ≈ 10 min/day (+ 0.5–1.5 person-days of triggered patches). Mandatory owner time through day 14 ≈ 1.3 person-days; with every optional patch ≈ 3 person-days.

### Day 0 — tonight, decisions and purchases (≈ 30–45 min, nothing installed yet)

| # | What | How | Time | Done when |
|---|---|---|---|---|
| 0.1 | Take the defaults in §7 or change them | Read §7; the only ones that block tomorrow are region, plan, domain/DNS, service user | 10 min | You can name DOMAIN, region, plan |
| 0.2 | Buy the domain | **If you already own a domain**: use a subdomain (`wd.<yours>`), skip registration. **Else default**: Porkbun, pay with Alipay (hosting:F14; v-hosting:F14: `.com` $11.81 reg = renew; `.top` $1.63 first year / $4.63 renewal) — instant, no 实名. Alternative: Alibaba 万网 `.com` ¥85/¥95 with the 实名 template (hosting:F14) — can cost 1–2 working days of review (hosting rec 2), which breaks the 1–3-day goal. | 10 min | Domain in your account |
| 0.3 | Choose the DNS host | Default: DNSPod free (fast from the mainland; account 实名 already exists; **TTL floor 600 s**, v-hosting:O2) — add the domain as a non-Tencent domain and set Porkbun's nameservers to DNSPod's (v-hosting:F13). Alternative: Cloudflare **DNS-only** (grey cloud, 60 s TTL non-Enterprise; never orange-cloud mainland users, hosting:F17). Do **not** use Alibaba/DNSPod URL forwarding (备案-gated, hosting:F12). | 10 min | NS delegated; no records yet |
| 0.4 | Buy the VPS | Tencent Cloud 中国站 → 轻量应用服务器 (Lighthouse) → region **Tokyo** (fallback Singapore, same price) → bundle **2 vCPU / 4 GB / 60 GB / 30 Mbps / 1.5 TB ≈ ¥42/month** (hosting:F4 default pick; v-hosting:F4: official $6.00; first-year new-user promos have been ¥199/年 for this shape, v-hosting:O6 — check the 活动 page) → image **Ubuntu 24.04 LTS** (hosting:F7; if only 22.04 is offered, see Day 1 note) → key-pair login. Lighthouse 防火墙: leave only SSH (22) open for now; 80/443 are opened in step 1.8. | 10 min | Instance running, public IP known |
| 0.5 | Ask the friends two questions in WeChat | 「你的手机是 iPhone 还是安卓？安卓的话是华为（鸿蒙 NEXT 吗）、小米、OPPO、vivo、荣耀？」 and 「每天的提醒你想收在微信里，还是 iPhone 用 Bark 通知？」 — decides the prewarm stage, the reminder channel and whether the Android app question ever comes up (android:F6, ios rec 7) | 5 min | Answers for ≥ half the circle |
| 0.6 | Prepare the Mac | Nothing to run yet. Make sure you can `ssh sqin@VPS_IP` tomorrow (your public key is in the Lighthouse key pair). Note: your Mac is set to sleep after 1 idle minute (v-deploy:O5) — irrelevant for the VPS plan, relevant for the backup pull (Day 1 step 1.12). | 5 min | — |

### Day 1 — build (≈ 3–4 h hands-on; friends can log in tonight if DNS cooperates)

**1.1 VPS first login: service user `sqin`, sudo, SSH keys, firewall closed (10 min).** Log in as the image's default user (`ubuntu` on Tencent's Ubuntu images; `root` on some). Using the literal user name `sqin` means zero edits to `.env` defaults, unit files or operator messages (deploy:F3, v-deploy:F3).

```bash
sudo adduser --disabled-password --gecos "" sqin && sudo usermod -aG sudo sqin
echo 'sqin ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/sqin && sudo chmod 440 /etc/sudoers.d/sqin   # install.sh needs `sudo -n` (deploy/install.sh:53)
sudo install -d -m 700 -o sqin -g sqin /home/sqin/.ssh
sudo cp ~/.ssh/authorized_keys /home/sqin/.ssh/ && sudo chown sqin:sqin /home/sqin/.ssh/authorized_keys && sudo chmod 600 /home/sqin/.ssh/authorized_keys
sudo apt-get update && sudo apt-get install -y ufw
sudo ufw allow OpenSSH && sudo ufw --force enable          # 80/443 stay closed until step 1.8
```
Now `ssh sqin@VPS_IP` from the Mac, then disable password login: `sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config; grep -rl PasswordAuthentication /etc/ssh/sshd_config.d/ | xargs -r sudo sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/'; sudo sshd -T | grep -i passwordauth; sudo systemctl restart ssh`. Done when: `ssh sqin@VPS_IP sudo -n true` prints nothing and exits 0.

**1.2 Reachability test — do this before spending another minute (5 min).** From the VPS as `sqin`:
```bash
curl -sS -o /dev/null -w 'api %{http_code}\n'      https://api.anthropic.com/v1/models     # expect 401 (reachable, no key); 403 = region/network block
curl -sS -o /dev/null -w 'platform %{http_code}\n' https://platform.claude.com/           # expect 200/302, not 403 (OAuth token exchange host, v-clivps:O6)
curl -sS -o /dev/null -w 'downloads %{http_code}\n' https://downloads.claude.ai/claude-code-releases/latest   # 200
curl -sS -o /dev/null -w 'github %{http_code}\n'   https://github.com/                     # 200 (clone, ECDICT release)
curl -sS -o /dev/null -w 'wikimedia %{http_code}\n' https://commons.wikimedia.org/w/api.php  # photo provider reachability (security:F10)
```
Facts: Japan and Singapore are on Anthropic's supported list, Hong Kong IPs get `403 Request not allowed` (hosting:F1–F2, v-hosting:F1–F2); from the owner's own network both `api.anthropic.com` and `platform.claude.com` answer 403 directly (v-clivps:O6). Geo-IP of Tencent Tokyo/Singapore ranges resolves to JP/SG (v-hosting:O4). Done when: `api 401`, `platform 200|302`. If you see 403: destroy the instance, re-create in Singapore, repeat (≈ 15 min lost, nothing else built yet).

**1.3 Prerequisites that install.sh does not install (20–30 min).** (deploy:F1, v-deploy:F1: python3.12-venv, Node ≥ 22 — Ubuntu's apt node is 18.19 — git, curl, openssl, GNU `df`, a `claude` on PATH, > 2 GB free on `/home`.)
```bash
sudo apt-get install -y git curl ca-certificates gnupg openssl python3 python3-venv python3.12-venv sqlite3
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update && sudo apt-get install -y nodejs && node --version        # v22.2x (Vite 8 needs >= 22.12, v-deploy:O4)
python3 -c 'import sys,venv,ensurepip,sqlite3,zoneinfo; print(sys.version)'   # 3.12.x
sudo timedatectl set-timezone Asia/Shanghai                                    # cosmetic: journal timestamps; the app uses WD_TZ anyway
# claude CLI as the SERVICE user, pinned to the stable channel (2.1.311 on 2026-11-04), native launcher at ~/.local/bin/claude =
# the repo's default WD_CLAUDE_BIN/WD_CLAUDE_PATH, so nothing in .env needs editing (clivps:F1, v-clivps:F1)
curl -fsSL https://claude.ai/install.sh | bash -s 2.1.311
echo 'export DISABLE_AUTOUPDATER=1' >> ~/.profile && . ~/.profile && command -v claude && claude --version   # ~/.local/bin on PATH after re-login (Ubuntu ~/.profile)
```
Notes: the installer refuses `sudo` but not plain root — never install or log in as root, credentials would land in `/root` (v-clivps:O5, deploy:F3). The pinned install still downloads the latest build first (v-clivps:F1). `DISABLE_AUTOUPDATER` here covers your interactive runs; the service's child gets it from the wrapper in step 1.10 (clivps:F2, F9). Alternative apt route (`/usr/bin/claude`, no auto-update) works too but changes the path the wrapper execs. If the image was Ubuntu 22.04: `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt-get install -y python3.12 python3.12-venv` and run install.sh with `PY=python3.12` (hosting:F7; install.sh uses `$PY`, deploy/install.sh:12). Done when: `node --version` ≥ 22.12, `claude --version` prints `2.1.311`.

**1.4 Data cutover from the Mac (15 min; Mac side).** Final consistent copy with the Mac service stopped (deploy:F11 step 0). Both launchd agents are stopped so the 03:30 Mac backup does not keep "running" a dead instance.
```bash
launchctl bootout gui/$(id -u)/com.word-dance.server
launchctl bootout gui/$(id -u)/com.word-dance.backup
sqlite3 /Users/sqin/word-dance-data/word-dance.db "VACUUM INTO '/Users/sqin/wd-migrate.db'"    # one file, no -wal/-shm; integrity preserved
tar -C /Users/sqin/word-dance-data -czf /Users/sqin/wd-images.tgz images                         # 216 KB, 28 shard dirs (v-deploy:F11)
ssh sqin@VPS_IP 'install -d -m 0700 /home/sqin/word-dance-data'
scp /Users/sqin/wd-migrate.db sqin@VPS_IP:/home/sqin/word-dance-data/word-dance.db
scp /Users/sqin/wd-images.tgz sqin@VPS_IP:/home/sqin/
ssh sqin@VPS_IP 'tar -C /home/sqin/word-dance-data -xzf /home/sqin/wd-images.tgz && chmod 600 /home/sqin/word-dance-data/word-dance.db && rm /home/sqin/wd-images.tgz && ls -la /home/sqin/word-dance-data'
```
Do **not** copy the Mac `.env` (Mac-specific `WD_CLAUDE_BIN` wrapper, `WD_CLAUDE_PATH`, `WD_LOG_FILE`; `WD_SECRET_KEY` only protects unexpired e-mail codes — deploy:F11). Why before install: step 2 of install.sh keeps an existing data dir, `wd migrate` reports 0 pending (schema 1/8/9 == HEAD), `import-seed` is a no-op (seed hash == `kv.seed_version`), and `create-admin --if-none` says "users already exist" — the admin-bootstrap race is closed by construction (deploy:F5, F11; v-deploy:F5, F11). Carried-over kv to know: `claude.available=1/flag_tier=1/version=2.1.292` (stale; install's claude-check resets it), `claude.paused_until` (past), `worker_lease` (expires ≤ 90 s), `public_url_guess` (rewritten at start). Keep the Mac data dir untouched for 14 days as the rollback. Done when: `ls -la` on the VPS shows `word-dance.db` (0600, ~5.6 MB) and `images/`.

**1.5 Checkout (5 min).** Repo remote is `git@github.com:bigBuffers/word-dance.git`. If it is public: `git clone https://github.com/bigBuffers/word-dance.git /home/sqin/word-Dance`. If private: on the VPS `ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519 && cat ~/.ssh/id_ed25519.pub`, add it on GitHub → repo → Settings → Deploy keys (read-only), then `git clone git@github.com:bigBuffers/word-dance.git /home/sqin/word-Dance`. Then `cd /home/sqin/word-Dance && git checkout 9ab13a5` (or stay on `main` if nothing newer was pushed). The two untracked docs on the Mac are irrelevant. Done when: `git -C /home/sqin/word-Dance rev-parse --short HEAD` prints `9ab13a5`.

**1.6 Rehearse, then install (15–25 min; `npm ci` dominates).** As `sqin`, no `WD_DATA_DIR` export needed (user name matches the default).
```bash
cd /home/sqin/word-Dance
deploy/install.sh --with-caddy DOMAIN --with-ecdict --contact-email YOU@example.com --dry-run    # preflight must pass; prints every step with "+" (deploy:F20)
deploy/install.sh --with-caddy DOMAIN --with-ecdict --contact-email YOU@example.com
```
What it does (deploy:F4, F13, F17): venv + pip (26 manylinux wheels, no compiler, v-deploy:F15); `npm ci` + `vite build` into `frontend-releases/<sha>.new` (≈ 200 MB peak, seconds); `.env` created once from `deploy/env.example` with `WD_SECRET_KEY`, `WD_CLAUDE_BIN=$(command -v claude)`, `WD_DATA_DIR`, `WD_CONTACT_EMAIL`, and the proxy trio `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://DOMAIN"`, `WD_TRUST_PROXY="1"`; ECDICT (216 MB download → 851 MB `stardict.db`, `WD_ECDICT_DB_PATH` written); snapshot published; `wd migrate` → `0 pending`; `import-seed` → up to date; `wd claude-check` → **WARN** (no credential yet — expected, non-fatal; deploy:F2); `create-admin --if-none` → "users already exist"; units rendered with `User=sqin`, enabled, started; Caddy 2.6.2 from Ubuntu universe installed, Caddyfile written, reloaded (cert pending until DNS). Done when: the script ends with the health JSON from `127.0.0.1:8000` showing `"needs_setup":false`.

**1.7 `.env` edits and restart (5 min).** Quoting rule: every line `KEY="value"` (deploy/env.example:4-10; install.sh validates and aborts otherwise).
```bash
E=/home/sqin/word-dance-data/.env
sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="0"|' $E                       # deploy first; flip to "1" in step 1.10 after claude-check passes (deploy:F2)
sed -i 's|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="6.00"|' $E   # security:F8 recommendation for 10 friends
sed -i 's|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="100.00"|' $E   # default $40 would trip in weeks 2–4 and show "明天补齐" for weeks (security:F8, F17)
sed -i 's|^WD_AI_MODEL=.*|WD_AI_MODEL="claude-sonnet-5-5"|' $E            # pin the model the content was verified under (clivps:F7, v-clivps:F7)
grep -nE '^WD_(HOST|PUBLIC_URL|TRUST_PROXY|REGISTRATION_MODE|AI_ENABLED|AI_DAILY_BUDGET_USD|AI_MONTHLY_BUDGET_USD|AI_SVG_DAILY_BUDGET_USD|AI_HOURLY_CALL_CAP|AI_MODEL|ECDICT_DB_PATH|DEV)=' $E
sudo systemctl restart word-dance && sleep 3 && curl -fsS http://127.0.0.1:8000/api/health
```
Expect: `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://DOMAIN"`, `WD_TRUST_PROXY="1"`, `WD_REGISTRATION_MODE="invite"`, `WD_DEV="0"`, `WD_AI_SVG_DAILY_BUDGET_USD="0.50"` (keep; revisit at 48 h, §7 D8), `WD_AI_HOURLY_CALL_CAP="60"`. Done when: health shows `"registration_mode":"invite","needs_setup":false`. Also run `/home/sqin/word-Dance/.venv/bin/wd stats` (1 user, 9162 words, 52 bank rows) and `wd check providers` — this answers early whether Wikimedia/Openverse are reachable from Tokyo (on the Mac they were not: SSL EOF / timeouts, security:F10, v-security:F10).

**1.8 DNS, firewall, TLS, phone test (10–30 min incl. propagation).**
```bash
# DNSPod / Cloudflare: A record  DOMAIN -> VPS_IP, TTL 600 (DNSPod free floor) or 300/60 (Cloudflare DNS-only); no proxy/CDN
sudo ufw allow 80,443/tcp          # and open 80 + 443 in the Lighthouse console firewall
sudo systemctl reload caddy && sleep 30
curl -sSI https://DOMAIN/api/health | head -5           # HTTP/2 200 + strict-transport-security (security:F6)
journalctl -u caddy -n 20 --no-pager | grep -i certificate
```
Then on your own phone over **mobile data** (not Wi-Fi, so you see what friends see): open `https://DOMAIN`, log in as `sqin`, open 管理 → 概览. Done when: `https://DOMAIN/api/health` answers 200 **with** `strict-transport-security` and 管理 loads. HSTS and the cookie's `Secure` flag are set under the same condition (`X-Forwarded-Proto: https` from Caddy under `WD_TRUST_PROXY=1`, or an https `WD_PUBLIC_URL`; security:F6, v-security:F6), so the header on `/api/health` proves the cookie path too; the `sessions.ip` check in step 2.3 proves the client-IP half of the proxy contract. Do not test with wrong passwords from your own IP: each one counts toward the 10-failure username lock and the 20/10 min IP window (v-security:F4, F5).

**1.9 Invites (5 min) and an optional break-glass admin (2 min).** One single-use code per friend, 14 days, named, so the admin page shows who used what and a leaked code is worth one account (security:F12, F14; v-deploy:F12). Codes print **once** on stdout.
```bash
WD=/home/sqin/word-Dance/.venv/bin/wd
for n in 小王 小李 小张; do printf '%s: ' "$n"; $WD invite --uses 1 --days 14 --note "$n"; done 2>/dev/null > ~/invites.txt; cat ~/invites.txt   # delete the file after sending
# optional: a second admin with an unguessable name, so a friend's typos locking "sqin" (10 wrong = 15 min, no unlock command) never locks you out of 管理
WD_ADMIN_USERNAME=ops_7f3a9 WD_ADMIN_PASSWORD='<long unique password>' $WD create-admin      # no --if-none: creates a second admin even though users exist (backend/wd/security.py:738-764); username = 2–32 letters/digits/underscores/CJK, no hyphen
```
The 5 registrations/hour/IP throttle counts **failed** attempts too (403 `invalid_invite` included, v-security:O1), so the onboarding message (§6) tells friends to paste the code; if ≥ 6 friends sit on one Wi-Fi (your living room), stagger by an hour or use mobile data (security:F5).

**1.10 Claude credential wiring — owner's choice, config only (15–30 min; may slip to Day 2).** The runner forwards only an allow-list to the child (`backend/wd/ai/runner.py:49-62`: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, proxies, `SSL_CERT_*`, `CLAUDE_CONFIG_DIR`, `XDG_*`), `.env` may hold only `WD_*` lines, and systemd drop-ins survive install.sh re-renders (clivps:F9, v-clivps:F9). Standard home for CLI-only variables = a wrapper, exactly like the Mac (clivps rec 2):
```bash
install -d -m 0700 /home/sqin/word-dance-data/bin
cat > /home/sqin/word-dance-data/bin/claude-wrapper <<'EOF'
#!/bin/sh
# CLI-only environment for the claude child spawned by wd (runner forwards only its allow-list). Never put a proxy in the unit: it breaks image downloads.
export DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
# exactly ONE credential family, or none to use the login stored under /home/sqin/.claude/.credentials.json:
# export CLAUDE_CODE_OAUTH_TOKEN="$(cat /home/sqin/word-dance-data/oauth.token)"       # from `claude setup-token` (must be here: the runner strips CLAUDE_CODE_*)
# export ANTHROPIC_API_KEY="$(cat /home/sqin/word-dance-data/anthropic.key)"
# export ANTHROPIC_AUTH_TOKEN="$(cat /home/sqin/word-dance-data/gateway.token)" ANTHROPIC_BASE_URL=https://gateway.example.com
# HTTP CONNECT proxy for the CLI only, if ever needed (SOCKS is not supported by the CLI): export HTTPS_PROXY=http://127.0.0.1:8118 NO_PROXY=localhost,127.0.0.1
exec /home/sqin/.local/bin/claude "$@"
EOF
chmod 700 /home/sqin/word-dance-data/bin/claude-wrapper
sed -i 's|^WD_CLAUDE_BIN=.*|WD_CLAUDE_BIN="/home/sqin/word-dance-data/bin/claude-wrapper"|' /home/sqin/word-dance-data/.env
```
Per credential type (clivps step list A–E; mechanics only):
- **A. Login stored on disk**: `claude auth login` as `sqin` over SSH → copy the printed URL to your Mac browser → paste the code at `Paste code here` → `claude auth status --text` (exit 0). Credentials land in `/home/sqin/.claude/.credentials.json` (0600); the unit's `HOME=/home/sqin` and the missing `ProtectHome` are what make the service read it (clivps:F3; `deploy/word-dance.service:15,33-34`). Needs `platform.claude.com` reachable from the VPS (v-clivps:O6). Logins expire (3-day warning, then `Login expired`), re-login is the same command (ops.md §6 row 1).
- **B. `claude setup-token`** (run on any machine with a browser): store the token in `/home/sqin/word-dance-data/oauth.token` (0600) and uncomment the wrapper line; a drop-in `Environment=` would silently do nothing (clivps:F9 experiment).
- **C. `ANTHROPIC_API_KEY`**: wrapper line, **or** `sudo systemctl edit --drop-in=claude word-dance.service` with `[Service]\nEnvironmentFile=-/home/sqin/word-dance-data/claude.env` and a 0600 `claude.env` containing `ANTHROPIC_API_KEY=...` (plain KEY=value, systemd syntax). `--bare` becomes usable via `WD_AI_EXTRA_ARGS="--bare"` with a key, never with A/B (clivps:F5).
- **D. Bearer gateway**: `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL` (either place). **E. `apiKeyHelper`**: `/etc/claude-code/managed-settings.json` or `WD_AI_EXTRA_ARGS="--settings /path"` (tier 1's `--restricted` ignores `~/.claude/settings.json`, clivps:F2).

Technical facts to weigh (recorded, not judged): (i) the live Mac ledger holds 15 calls in 8 h killed by an Enterprise login's **fail-closed server-managed-settings fetch** (`Your organization requires remote managed settings to load…`), each misclassified as `auth` → 30-minute global pause + the 「Claude CLI 未登录」 banner; with such a login every spawn needs a live round trip to `api.anthropic.com` before the model call (v-clivps:O1); (ii) HK IPs get 403 (hosting:F2); (iii) subscription usage-limit messages (`You've hit your session/weekly limit`) are classified as plain `error` → per-job backoff → dead (v-clivps:O2); (iv) `API Error: 403 Request not allowed` and connection errors are also plain `error`, no pause, no banner (clivps:F11); (v) `--bare` is not yet the `-p` default (clivps:F5).

Prove the whole chain, then enable:
```bash
/home/sqin/word-Dance/.venv/bin/wd claude-check      # expect: claude check OK: tier 1, cost $0.00xx, ... model claude-sonnet-5-5, claude 2.1.311 (≤ $0.05; clivps:F10)
sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="1"|' /home/sqin/word-dance-data/.env && sudo systemctl restart word-dance
journalctl -u word-dance -o cat --since '5 min ago' | grep -E 'claude_(call|auth|spawn)' | tail
```
If 管理 → 概览 shows 已暂停 (stale `claude.paused_until` or a failed first call): 管理 → AI → 恢复 AI. Done when: claude-check exits 0 and the first real job (e.g. add one custom word in 生词库) produces a `claude_call` with `status success`.

**1.11 Your own home-screen test (10 min; decides the week-1 icon patch).** On your iPhone in Safari: 分享 → 添加到主屏幕 → 添加; open it from the home screen. Record: (a) does it open standalone (no Safari chrome) — expected yes on iOS 26/27 by default (ios:F14, v-ios:F14); (b) the icon — Safari 26 accepts SVG icons and the page ships `<link rel="icon" href="/favicon.svg">`, so it may already be the blue "W"; if it is a page screenshot, the 1-hour PNG patch (§4, W1) is triggered (pwa:F2, F5); (c) whether you had to log in again inside the home-screen app — the WWDC23 cookie-copy statement is macOS-specific, so expect one extra login (v-pwa:F8), while the Safari 17.2 notes claim cookies are copied on iOS (ios:F17); your phone settles it and the §6 message is worded for either; (d) tap 发音 on a card and check auto-pronounce after the first tap (pwa:F8). If you also have an Android phone at hand: vendor browser → 添加到桌面, note icon/name (android:F10).

**1.12 Backups off the box, from the Mac (15 min).** The VPS timer already runs `wd backup --keep-daily 14 --keep-weekly 8` at 03:30 Asia/Shanghai (`deploy/word-dance-backup.timer:5-7`, deploy:F14). Pull them to the Mac with a launchd agent (macOS `rsync` is openrsync, protocol-compatible, deploy:F14):
```bash
mkdir -p /Users/sqin/word-dance-vps-backups /Users/sqin/Library/Logs/word-dance
cat > ~/Library/LaunchAgents/com.word-dance.vps-backup-pull.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.word-dance.vps-backup-pull</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/rsync</string><string>-a</string><string>--delete</string>
    <string>sqin@VPS_IP:/home/sqin/word-dance-data/backups/</string>
    <string>/Users/sqin/word-dance-vps-backups/</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/sqin/Library/Logs/word-dance/vps-backup-pull.log</string>
  <key>StandardErrorPath</key><string>/Users/sqin/Library/Logs/word-dance/vps-backup-pull.log</string>
</dict></plist>
EOF
ssh sqin@VPS_IP true                                   # accept the host key once, interactively
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.vps-backup-pull.plist
sleep 5; ls -la /Users/sqin/word-dance-vps-backups/    # empty until the first 03:30 run; RunAtLoad re-pulls at every login
```
`RunAtLoad` matters because the Mac sleeps after one idle minute (v-deploy:O5): a missed 04:30 fires at the next wake, and every login re-syncs. Also copy the VPS `.env` once into your password manager (`ops.md` §2: it is not in `backups/`). Done when: after Day 2's 03:30 the Mac folder holds `word-dance-2026110x-03xx.db.gz`.

**Evening of Day 1 (5 min): latency check from the mainland.** From your phone on each carrier you can reach (mobile data; home Wi-Fi), at ≈ 21:00: open the site twice, then on the Mac `ping -c 20 VPS_IP` and `curl -o /dev/null -s -w 'connect %{time_connect}s total %{time_total}s\n' https://DOMAIN/api/health` ×3. Tokyo expectations: 45–120 ms, Telecom evening variance (hosting:F21); if loss > 5 % or the site feels slow at 21:00, rebuild in Singapore (same price, ≈ 1 h redo of 1.3–1.8 with the snapshot; hosting rec 7). Tencent itself disclaims cross-border quality on every overseas bundle (v-hosting:O3) — the measurement is the real gate.

### Day 2 — reminders, prewarm, pilot friends (≈ 1.5–2 h)

**2.1 Reminder dry run on your own devices (20 min).** `WD_PUBLIC_URL` is set (every digest links `https://DOMAIN/today`, reminders:F11). Only two channels are offered in week 1, because both report failures truthfully (HTTP 400 on a bad key): **Bark** for iPhones and **Server酱 Turbo** for everyone with WeChat (reminders:F3–F5). 企业微信, 飞书 and Server酱³ answer HTTP 200 with an error body, which the app shows as 「测试成功」 and records as `sent` (reminders:F3, v-reminders:F3, O1–O2) — hold them until the week-2 patch, or accept them only after the friend has physically received a test.
- Bark (your iPhone): App Store → Bark (free) → copy `https://api.day.app/<key>` → word-Dance 我的 → 推送设置 → switch on 「Webhook 推送」 → 「Webhook 地址（https）」 paste → 「格式」 Bark → 「发送测试」 → notification arrives (reminders:F4). The test text carries no URL; the first real digest does.
- Server酱 Turbo (your WeChat): `sct.ftqq.com` → 微信扫码登录 → copy SendKey → address `https://sctapi.ftqq.com/<SendKey>.send` → 格式 「Server酱」 → 发送测试 → the 「方糖」服务号 shows the title (free tier: 5 messages/day, title-only card; the body is on the detail page; link opens in WeChat's browser = one more login) (reminders:F5).
- One real digest with the deep link: `/home/sqin/word-Dance/.venv/bin/wd push-now sqin` builds and publishes **your** batch now (side effect on your own day only) and enqueues the webhook (reminders:F15); tap the link on the phone and confirm `/today` opens. One 发送测试 per 10 minutes per user (reminders:F1).

**2.2 Prewarm the friends' stage(s) overnight (15 min of attention + 3–7 h wall).** Not a blocker — the daily batch builds content for its ≤ 25 words up to 3 h before each push time anyway (security:F11) — but it makes 筛词/词库 instant and shifts spend to one controlled evening. Costs: top 1,000–2,000 words of one stage $4.5–12 (zk alone 2,099 words ≈ $9.5–12.4; v-security:O5 says budget +10 % over the digest); everything (9,114 words) $41–54. Throughput: 300–600 words/h (security:F11 says 600 at 60 calls/h; the curation analysis measured ≈ 300 effective because the fan-out is one 10-word group per 2 min; memory note 2026-11-04).
```bash
E=/home/sqin/word-dance-data/.env   # temporary caps for the prewarm window (security:F11); settings are read at process start → restart
sed -i 's|^WD_AI_PREWARM_DAILY_BUDGET_USD=.*|WD_AI_PREWARM_DAILY_BUDGET_USD="20.00"|; s|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="40.00"|; s|^WD_AI_HOURLY_CALL_CAP=.*|WD_AI_HOURLY_CALL_CAP="120"|' $E
sudo systemctl restart word-dance
# 管理 → AI → 预生成: stage = the friends' main stage (zk / gk / cet4 / cet6), limit 2000, max_budget_usd 12  (admin-only, refused while AI is paused)
# next morning: restore
sed -i 's|^WD_AI_PREWARM_DAILY_BUDGET_USD=.*|WD_AI_PREWARM_DAILY_BUDGET_USD="1.00"|; s|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="6.00"|; s|^WD_AI_HOURLY_CALL_CAP=.*|WD_AI_HOURLY_CALL_CAP="60"|' $E
sudo systemctl restart word-dance
```
Prewarmed words never trigger SVG cards (security:F10, F11). Done when: 管理 → 概览 shows `jobs.queued` back near 0 and 本月花费 ≈ the expected amount.

**2.3 Pilot: 2–3 friends (30 min of chat).** Send §6 with their personal code to one iPhone friend and one domestic-Android friend first. Watch them land (as `sqin` on the VPS): `sqlite3 -cmd ".timeout 5000" /home/sqin/word-dance-data/word-dance.db "select user_id, ip, user_agent, created_at from sessions order by id desc limit 5;"` — real client IPs prove `WD_TRUST_PROXY=1` works (security rec 3); `127.0.0.1` everywhere would mean every friend shares one throttle bucket (security:F5-iv). Ask each: standalone? icon? 发音 works? reminder test received?

**2.4 Restore drill (5 min, VPS)** — ops.md §2 monthly drill, once now so you know it works: `D=/home/sqin/word-dance-data; L=$(ls -t $D/backups/word-dance-*.db.gz | head -1); gunzip -c "$L" > $D/tmp/drill.db && /home/sqin/word-Dance/.venv/bin/wd check db --db $D/tmp/drill.db && rm $D/tmp/drill.db`. Check the Mac pull log too.

### Day 3 — the rest of the circle (≈ 1 h)

- Send the remaining codes (stagger if several friends share a Wi-Fi; codes expire day 15).
- 管理 → 用户与邀请: everyone registered? Unused codes? Any 「禁用」 needed?
- 管理 → 概览: 今日花费 / 本月花费 vs caps, 队列, provider cooldowns, events (`budget_*`, `claude_auth`, `claude_unavailable`, `image_rejected`), `last_backup`, disk.
- Decide the SVG question at 48 h (§7 D8): if the overview's image mix is mostly `with_claude_svg`/`card_only` and `wd check providers` fails from Tokyo as it did on the Mac, choose between `WD_AI_SVG_DAILY_BUDGET_USD="1.00"` (≈ 80 cards/day, +≤ $30/month) and `"0"` (text cards, zero SVG spend) (security:F8, F10); photos working → leave 0.50.

### Days 4–7 — watch list (≈ 10 min/day) and the one optional week-1 patch

Daily (ops.md §1): `systemctl is-active word-dance caddy`; `journalctl -u word-dance --since today -p warning`; `journalctl -u word-dance -o cat --since today | grep -E '"event":"(budget|claude_auth|claude_unavailable|downtime|lease_lost)'`; 管理 → 概览 (spend, queue, 已暂停, provider quotas, `last_backup`); `ls -t /Users/sqin/word-dance-vps-backups | head -1` on the Mac. Weekly: `systemctl list-timers word-dance-backup.timer`; `df -h /home`; `journalctl -u caddy --since '-7d' | grep -i -E 'certificate|error'`; 21:00 latency spot check; count reminder taps: `journalctl -u word-dance -o cat --since '-7d' | grep -c '"path":"/api/today'` (rough engagement signal).

Known sharp edges and the exact move for each (keep this list next to you):
| Symptom | Fact | Move |
|---|---|---|
| A friend: 「登录失败次数过多，请 N 分钟后再试」 | 10 wrong passwords lock the **username** 15 min, doubling every 5 more, max 24 h; no `wd unlock` (security:F4) | `sqlite3 -cmd ".timeout 5000" /home/sqin/word-dance-data/word-dance.db "DELETE FROM auth_throttle WHERE key='login:user:<username lower-case>';"` while the service runs — the `.timeout` is mandatory, the bare `sqlite3` shell fails silently on a busy WAL (v-security:F4) |
| 429 on register/login for a whole household | 5 registrations/h and 20 logins/10 min per IP, failures and 423s included (v-security:O1–O2) | wait ≤ 1 h / 10 min, or mobile data; verify `sessions.ip` is not `127.0.0.1` |
| Forgotten password | no self-service reset (security:F16) | 管理 → 用户与邀请 → 重置密码 (revokes sessions) or `wd set-password <user>` |
| Banner 「Claude CLI 未登录」, `claude_auth` events every 30 min | login expired **or** a network/policy-fetch blip classified as auth (v-clivps:O1) | `wd claude-check` first; if it passes, 管理 → AI → 恢复 AI and watch; if it fails with a login string, repeat step 1.10 A/B; the banner text names `sqin` and "login" regardless of the real cause |
| Cards say 「今日 AI 额度已用完，例句将在明天补齐」 | daily/monthly/hourly deferral all use the same "tomorrow" copy (security:F17) | check 概览 which cap; monthly → raise `WD_AI_MONTHLY_BUDGET_USD` + restart; hourly → wait for the hour |
| Queue suddenly hundreds of `generate_content` jobs | one account can batch-mark the whole seed; no per-user quota (security:F7) | 管理 → AI → 暂停 AI (24 h, everyone), then the two-statement cancel recipe from v-security:F7 (the digest's version fails on `updated_at`); extend `type IN ('generate_content','fetch_image','generate_svg')` if images were already enqueued (v-security:O3) |
| Many text-only / SVG cards | providers unreachable (security:F10) | SVG cap decision (Day 3); optional `WD_PIXABAY_KEY`/`WD_PEXELS_KEY` (both empty on the Mac today) |
| Site 503 「前端尚未构建」 after an upgrade | snapshot pruned while the old process still served it (v-pwa:O3) | `sudo systemctl restart word-dance` |
| Site unreachable from the mainland only | GFW event on the IP (hosting:F20) | Lighthouse console → 更换公网 IP (**once per instance lifetime**, 3/day/region, v-hosting:O1) → update the A record (TTL 600 → ≤ 10 min); second event → rebuild from a Lighthouse snapshot as a new instance |

**W1 (optional, ≈ 1.5 h incl. deploy; trigger = your Day-1 icon/name test or a friend's complaint)** — manifest + PNG icons + `<link>`s, §4. Ship it with `cd /home/sqin/word-Dance && git pull && deploy/install.sh` (no `--with-caddy` on upgrades, deploy:F4; downtime ≈ seconds, deploy:F13).

### Days 8–14 — triggered patches, close registration, decide the app question

- **Patches (§4 "week 2"), only those triggered**: webhook body check (any friend wants 企业微信/飞书/Server酱³); `InstallHint` + WeChat/QQ detection (friends keep opening the link inside WeChat and never find 添加到主屏幕); `/assets/*` 404 + `no-cache` for root files (bundle with either). Deploy path as W1; afterwards `readlink /home/sqin/word-dance-data/frontend` must name the snapshot install.sh printed, and the unit must have restarted (ops.md §6 last row).
- **Close registration** once everyone is in: `sed -i 's|^WD_REGISTRATION_MODE=.*|WD_REGISTRATION_MODE="closed"|' /home/sqin/word-dance-data/.env && sudo systemctl restart word-dance` (security:F14). Re-open to `invite` for a late friend.
- **Mac**: keep the old data dir until day 14, then either delete it or keep it as a cold copy; the Mac launchd agents stay booted out (do not run two instances of one user's data).
- **Decide the app route with numbers** (§5 triggers): active friends per device class, `/api/today` opens after push time, reminder channel complaints, HarmonyOS NEXT count. Default outcome for a 10-friend circle: stay on the web app another month (reminders rec 3: "observe, do not build").
- **Month-end**: 本月花费 vs the $100 cap; realistic $25–60 (security:F8); adjust caps; check the Lighthouse traffic counter (1.5 TB is > 100× need, hosting:F4).

Rollback at any point in the 14 days: Mac `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.server.plist` brings the old instance back on the LAN; to carry the friends' data back, `wd restore` the newest pulled `.db.gz` into the Mac data dir (same commit, same schema; ops.md §3).

---

## 3. Mobile route per device class (home-screen web app first)

Common to all: the site is `https://DOMAIN`; login = username + password (8–64 chars, not the username, not a common word), optional e-mail, 邀请码 field on the register page (`frontend/src/i18n/zh.ts:22`); the session cookie lasts 30 days and slides daily (security:F1); every browser/app context has its own cookie jar, so WeChat's built-in browser, the home-screen app and Safari each ask once; 10 wrong passwords lock the username for 15 min (security:F4); password resets go through the owner (security:F16). The onboarding wizard asks 目标阶段 / 主攻阶段 / 每日推送时间 / 时区（自动检测） (`zh.ts:26`).

| Device class | Install (what the friend does) | Daily reminder | Pronunciation (发音) | Login notes |
|---|---|---|---|---|
| **iPhone, Safari** (iOS 16.4–27) | Open the link in Safari → 分享 → 添加到主屏幕 → 添加. iOS 26/27 opens every Home-Screen site as a web app by default, "zero requirements for installability" (ios:F14, v-ios:F14, O5); iOS ≤ 18 does the same via the existing `apple-mobile-web-app-capable` meta (pwa:F1). Icon: SVG favicon may already be used on 26+; the PNG patch (§4 W1) guarantees it everywhere (pwa:F2, F7). | **Bark** (App Store, free): paste `https://api.day.app/<key>` as Webhook 地址, 格式 Bark; lock-screen push via APNs, tap opens `/today` in the default browser (reminders:F4). Alternative: Server酱 Turbo → WeChat. | Web Speech works (Samantha/Daniel voices); auto-pronounce of the first card may wait for the first tap in Safari (pwa:F8); follows the ring/silent switch (capacitor:F12). | Expect one extra login inside the home-screen app (v-pwa:F8); the Safari 17.2 notes say the cookie is copied (ios:F17) — either way one tap. Data export (`<a download>`) can hang the standalone window on iOS 18.4+ (WebKit 290847, pwa:F8) → export from Safari, not from the home-screen app. |
| **iPhone, link opened inside WeChat** | WeChat's WKWebView has no 添加到主屏幕: tap 「···」 → 「在Safari中打开」 first (ios:F16, pwa:F9); a 「非微信官方网页」 interstitial may appear → 继续访问. Then as above. | Server酱 Turbo → WeChat (works where the friend already is); or Bark once in Safari. | Inside WeChat's WebView: unverified (android open q6) → use Safari. | WeChat's browser is a separate cookie jar: logging in there does not log in Safari (reminders:F5). |
| **Android with Google services** (global ROM / Pixel / Samsung, or a domestic phone with Google services switched on) | Chrome → ⋮ → 添加到主屏幕 (installs from the menu without a service worker since Chrome 108, pwa:F7); today this is a shortcut, a real WebAPK "安装应用" entry needs the manifest + 192/512 icons patch (android:F8–F9). Samsung Internet similar. | Server酱 Turbo → WeChat (default); Server酱³ app after the week-2 body-check (system push via vendor/FCM channels, reminders:F6); ntfy Play build with the generic format + template URL (reminders:F9). Web Push: not built (android:F11). | Chrome bridges to the system TTS engine; needs an English voice (Google TTS present on GMS phones) (android:F13). | Same as web. From 2027 Google's developer verification affects sideloaded APKs on these phones, not the web app (android:F1–F3). |
| **GMS-less domestic Android** (Xiaomi HyperOS, OPPO ColorOS, vivo OriginOS, Honor MagicOS — the mainland default) | Phone's own browser (小米/OPPO/vivo/荣耀浏览器) or 夸克/QQ浏览器 → menu → 添加到桌面 (a launcher shortcut that opens the browser; standalone/manifest behaviour undocumented for every domestic browser, android:F10). If the link came from WeChat: 「···」 → 「在浏览器打开」. | **Server酱 Turbo → WeChat** (zero code, every phone with WeChat; title-only card, link opens in WeChat's browser) (reminders:F5). Real system notification: Server酱³ app (小米/华为/荣耀/vivo/OPPO push channels) — offer after the week-2 patch or verify by receipt (v-reminders:F6). ntfy F-Droid build works but needs a foreground service + battery whitelist (reminders:F9). | Chromium-based vendor browsers "likely" bridge to the system TTS — untested; English voice availability on 小米/OPPO/vivo engines unknown (android:F13, open q2); UC Browser lacks speechSynthesis, QQ Browser has it (v-captool:F15 caniuse rows). If 发音 is grey: try QQ浏览器/Chrome or the vendor browser. | Same as web. |
| **HarmonyOS 4.x Huawei** (phones not upgraded to 5) | 华为浏览器 → ∷ → 添加至桌面 (PWA-capable sites became a 快应用 shortcut on ≤ 5.0/EMUI, android:F7); AOSP-based, APKs install (android:F5). | Server酱 Turbo → WeChat; Server酱³ later. | Untested (Huawei engine) — device test (android:F13). | Same as web. |
| **HarmonyOS NEXT** (HarmonyOS 5/6/7 — every Huawei phone since late 2024) | 华为浏览器 → ∷ → 添加至桌面 (max 10 shortcuts, plain shortcut, no documented manifest/standalone support, android:F7). No APK runtime; the AppGallery container 卓易通 can install some APKs but is untested for notifications/TTS (v-android:O1). Web-only class. | Server酱 Turbo → WeChat (native WeChat on AppGallery); 企业微信/飞书 bots after the week-2 patch (both have NEXT builds, reminders:F7–F8). | ArkWeb implements SpeechSynthesis outside 坚盾守护 mode — inferred from Huawei's docs, untested (android:F7, v-android:F7). | Same as web. |

Device-test checklist for the pilot friends (fills the unknowns above; android rec 3): shortcut opens chrome-less? login cookie survives relaunch? 发音 speaks en-US/en-GB? reminder test received? (Record per browser in `docs/qa-frontend.md` when the W2 patch lands.)

---

## 4. Code changes (minimal), with triggers

**Before inviting: none.** Every must-item is configuration or procedure (security gap table rows 1–5; §2 Day 1).

**Week 1 (optional, evidence-triggered)**
| Id | File(s) | Change | Hours | Trigger |
|---|---|---|---|---|
| W1 | `frontend/public/manifest.webmanifest` (new), `frontend/public/icons/*.png` + `apple-touch-icon.png` (new, ≈ 40 KB via the verified `sips` recipe pwa:A3, v-pwa:F5), `frontend/index.html` (+3 lines after line 13: `mobile-web-app-capable`, `<link rel="manifest">`, `<link rel="apple-touch-icon">`, pwa:A2) | Installability surface for a real icon/name on iOS ≤ 18 and every Android browser; `start_url:"/today"`, `scope:"/"`, `display:"standalone"` (pwa:A1, F11). No CSP change (pwa:F3). Regression: `npm run lint && npm run typecheck && npm test && npm run build` (pwa:F10) | 1 h + 0.5 h deploy/QA | Day-1 test shows a screenshot icon or a wrong name; or Android friends get a generic icon |

**Week 2 (triggered)**
| Id | File(s) | Change | Hours | Trigger |
|---|---|---|---|---|
| W2a | `backend/wd/delivery/webhook.py` (`safe_post`/`send_batch_webhook`, `:252-254`, `:332-336`), tests in `backend/tests/integration/test_delivery.py` | Parse the JSON body for `wecom`/`feishu`/`serverchan`: `errcode != 0` / `code != 0` → `WebhookError` (retries work, 测试成功 becomes truthful), store the vendor code in `delivery_error`; `wecom` → `msgtype: markdown` (4,096 B; the real digest is 1,982–2,061 B against a 2,048 B text cap) or truncate; put the URL into the test message; optionally Bark `group`/`isArchive` (reminders rec 2, v-reminders:F2, F3, O1–O2) | 6–8 h (≈ 1 person-day) | A friend wants 企业微信 / 飞书 / Server酱³ |
| W2b | `frontend/src/utils/platform.ts` (new), `frontend/src/components/layout/InstallHint.tsx` (new), `AppLayout.tsx` (render on `/today`), `SettingsPage.tsx` (「添加到主屏幕」 row), `src/i18n/zh.ts` + `docs/FRONTEND.md` §8 mirrored line-for-line (pwa:F10), tests | Detect `MicroMessenger` / QQ UA → non-dismissible 「微信内无法添加到主屏幕：点击右上角「⋯」，选择「在浏览器打开」」; iOS/Android channels → dismissible instructions (pwa:A6, F9) | 3–4 h | Friends keep using the site inside WeChat / cannot find 添加到主屏幕 |
| W2c | `backend/wd/main.py` `_mount_spa` (`:252-260`), `backend/tests/integration/test_health.py`, `docs/DEPLOY.md` §4 sentence | `Cache-Control: no-cache` for `index.html`, `manifest.webmanifest` (and `sw.js`/`registerSW.js` if ever added); 404 instead of `index.html` 200 for missing `/assets/*` (pwa:A4, F4; v-pwa:O1–O2: the literal `/index.html` is 1-h cacheable and `FileResponse` never answers 304) | 1 h | Bundle with W1 or W2b |

**Later (not for the circle unless something bites)**
| Id | Change | Days | Fact |
|---|---|---|---|
| L1 | Show the real `deferred_until` date instead of 「明天补齐」 | 0.2 | security:F17 |
| L2 | `wd unlock <username>` command | 0.2 | security:F4 |
| L3 | Login/register throttles: do not count successes / 423s; key by account | 0.5 | security:F5, v-security:O1–O2 |
| L4 | Runner classifier: `403 Request not allowed`, policy-fetch string, usage-limit strings → distinct classes with short retry; credential-neutral banner text | 0.5 | clivps:F11, v-clivps:O1–O2 |
| L5 | `PASSTHROUGH_ENV` += `CLAUDE_CODE_OAUTH_TOKEN`, `DISABLE_AUTOUPDATER`, `NODE_EXTRA_CA_CERTS` (+ test) | 0.5 | clivps rec 5 |
| L6 | Per-user AI quota on mark-triggered content + admin "cancel this user's queue" | 2–3 | security:F7 |
| L7 | Standalone export fallback (`exportAccount()` → `navigator.share` / clipboard) | 0.25 | pwa:F8, v-pwa:O5 |
| L8 | Top safe-area padding on `.page`/`.auth` (needed by the Capacitor shell; zero visual change in browsers) | 0.5 | capacitor:F10, v-capacitor:F10 |
| L9 | `useSpeech` native branch → TTS plugin when running inside the shell | 0.5–1 | capacitor:F12, captool:F15 |
| L10 | `ntfy` webhook format (table-rebuild migration 0010 + 8 enum sites) | 1 | v-android:O5 |
| L11 | Generalise `sqin`/`/home/sqin` defaults and messages | 1–2 | deploy:F3 (moot while the user is `sqin`) |

---

## 5. App routes (later, evidence-triggered): Capacitor 8 remote shell, iOS via TestFlight-internal, Android via sideloaded APK

**Mode**: M1 remote shell — `server.url = "https://DOMAIN"`; the WebView's document origin **is** the API origin, so the HttpOnly `SameSite=Lax` cookie, the CSRF Origin rule, cookie-gated `/media` and the CSP all work with **zero backend change**; a website deploy is the app update (capacitor:F1, F20; v-capacitor:F1 reproduced live: Origin == site → 201 with `Secure; SameSite=lax; HttpOnly`; `capacitor://localhost` / `https://localhost` → 403). Ionic documents `server.url` as "not intended for production" (capacitor:F6, captool:F5); for TestFlight **internal** testing and APK sideload nobody reviews the build, so this is an accepted, documented risk; App Store 4.2 would apply only to a storefront or an external TestFlight group (capacitor:F21, ios:F19–F20). Bridge mechanics are verified in the 8.6.0 sources on both platforms (captool:F6–F8, v-capacitor:F4); on Android the bridge is scoped to the exact origin of `server.url`, so `DOMAIN` must be the canonical, non-redirecting origin (v-capacitor:O1, v-captool:O6). Pin `@capacitor/*` ≥ 8.5.1 — 8.0–8.5.0 carry the critical proxy-path CVE-2026-103922 fixed on 2026-08-31 (v-captool:O1); stay on 8.6.x (Capacitor 9 needs Node 24; GA targeted end of November; captool:F1, F3).

**Tooling to install on the Mac (sizes, order)** (captool checklist; ios:F11):
1. Apple Developer Program enrolment via the Apple Developer app (v11.1.1 needs macOS 26.0+ — the Mac qualifies): 身份证 + selfie (CFCA), legal name = seller name, ¥688/yr auto-renewing, Alipay/WeChat Pay/card, never Apple Account balance; confirmation typically 1–3 days, outliers weeks on name mismatches (ios:F1–F3, v-ios:F1–F2, O6). Start it a week before you intend to build.
2. Xcode 27.2 from the Mac App Store: 3.12 GB download, macOS 26.6+ (met), ≈ 9–12 GB installed (derived); `sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept && xcodebuild -runFirstLaunch`; iOS simulator runtime (≈ 7.9 GB) optional if you test on a real iPhone (captool:F21, ios:F11). Every upload to App Store Connect must be built with the iOS 26 SDK since 2026-04-28 and the iOS 27 SDK from April 2027 — Xcode 27.2 satisfies both (ios:F12).
3. Android, CLI-only: `brew install --cask temurin@21 android-commandlinetools`; `export JAVA_HOME=$(/usr/libexec/java_home -v 21) ANDROID_HOME=/opt/homebrew/share/android-commandlinetools`; `sdkmanager --licenses && sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"` (≈ 0.5–1 GB + ≈ 1 GB Gradle/Maven cache). Or Android Studio 2026.2.2 (1.5 GB dmg + SDK, bundled JDK). Capacitor 8 pins AGP 8.13.0, Gradle 8.14.3, compile/target SDK 36, minSdk 24, Java 21 (captool:F2, F22). Gradle's first run pulls from dl.google.com/Maven Central: route it through the existing SOCKS→HTTP proxy (`~/.gradle/gradle.properties` `systemProp.https.proxyHost/Port`) or Aliyun mirrors (capacitor:F16).
4. Node stays 22.23.4; no CocoaPods (SPM default; trunk goes read-only 2026-12-02 anyway) (captool:F4, F24).
Total ≈ 15 GB of downloads, ≈ 30 GB on disk, half a day of installing if the network cooperates (captool checklist).

**Project (`mobile/`, kept out of `frontend/`)** (capacitor rec 2): `npm i @capacitor/core@8 @capacitor/cli@8 @capacitor/ios@8 @capacitor/android@8 @capacitor/app@8 @capacitor/local-notifications@8 @capacitor-community/text-to-speech@8 && npm i -D @capacitor/assets`; `npx cap init word-Dance <appId> --web-dir web` (appId = reverse-DNS of a domain you control; it cannot change later). `web/index.html` = the offline/retry page in zh (`server.errorPath: 'index.html'`, capacitor:F8; the iOS shell aborts without a local `webDir/index.html` even with `server.url`, v-captool:O5). `capacitor.config.ts`: `server.url: 'https://DOMAIN'`, `cleartext: false`, `allowNavigation: []` (attribution links open the system browser, capacitor:F7), `appendUserAgent: 'word-Dance-App'`, `ios.limitsNavigationsToAppBoundDomains: false` (true would kill the bridge, capacitor:F6), `android.minWebViewVersion: 108` (`dvh`/`color-mix`/`<dialog>` floor, capacitor:F13), `plugins.SystemBars: { insetsHandling: 'native', initialViewportFitValueHint: 'cover' }` (the verifier's recommendation over the digest's `css`: avoids the first-paint jump on WebView ≥ 140 and is the Capacitor 9 default, v-capacitor:O4, v-captool:F14), `plugins.LocalNotifications: { smallIcon: 'ic_stat_worddance', iconColor: '#3b5bdb', presentationOptions: ['banner','sound','list'] }`. Icons/splash from `frontend/public/favicon.svg` with `@capacitor/assets` (capacitor:F17). `npx cap add ios && npx cap add android && npx cap sync`.

**Web-side adapter in `frontend/` (≈ 1 d incl. tests; capacitor rec 5)**: `src/native/capacitor.ts` with `isNative()`, `syncDailyReminder(settings)` (cancel + `schedule({ id: 1, schedule: { on: { hour, minute }, allowWhileIdle: true } })` converted from `settings.push_time`/`timezone` to device wall time), `requestReminderPermission()` from the 每日推送 switch gesture, `installNativeHandlers(navigate)` (Android back button → `history.back()` or `App.minimizeApp()`, notification tap → `/today`; the tap is retained until a listener exists, so cold starts work, v-capacitor:O3). Android specifics: pass `isExactNotification: false` for the no-permission variant, otherwise `schedule()` itself bounces the user to the "Alarms & reminders" settings screen on Android 12+ (v-captool:F10 correction 2); the plugin's re-arm after the first fire drops `allowWhileIdle`/`RTC_WAKEUP`, so re-run `syncDailyReminder` on every app launch/resume (v-captool:F10 correction 1); request `POST_NOTIFICATIONS` from a gesture (captool:F11); for sideload you may declare `USE_EXACT_ALARM` (captool:F11). Hide the export anchors when native (downloads do nothing in either WebView, capacitor:F13) — or L7.

**Local notifications vs. the server channels**: the local reminder is only a nudge ("今日词汇已准备好") that opens `/today`; it cannot contain the day's words (reminders:F12). Keep Bark/Server酱 as the content channel; the app adds a relay-free nudge and an app icon.

**TTS**: iOS WKWebView keeps Web Speech synthesis and, per the WebKit source chain, should speak the first card without a tap in the shell (capacitor:F12, v-capacitor:F12 — inference, verify on device). Android System WebView ships with `--disable-speech-synthesis-api`, so the Android app has **no pronunciation** without the plugin branch (L9) — mandatory for the Android build in this plan, not optional (v-capacitor:F12, android:F13). Domestic phones may lack an English voice (`openInstall()` hint).

**CSS**: `.page`/`.auth` have no top safe-area padding; in the shell titles sit under the status bar / Dynamic Island and under Android ≥ Chromium-140 edge-to-edge (L8, 0.5 d; capacitor:F10).

**iOS distribution**: App Store Connect → New App (zh-Hans primary, leave availability at all 175 territories — mainland Apple IDs can only install TestFlight builds of apps available in their storefront, v-ios:F7, O2; never "Removed from Sale"); `Info.plist` `ITSAppUsesNonExemptEncryption = NO` (otherwise every build stalls on "Missing Compliance", v-ios:O1); Xcode → Archive → Distribute → **TestFlight Internal Only** (can never be added to an external group; a Beta-App-Review rejection would kill the build for everyone, v-ios:O3); internal group → add each friend as an App Store Connect user with the **Marketing** role and access limited to this app (50 users on an individual account; invitations expire in 3 days; the invite e-mail becomes the tester's Apple Account, v-ios:O4); friends install TestFlight (China App Store, iOS 16+), accept, install (ios:F4, F6–F7, F22). Builds expire after **90 days** — calendar a re-upload every ≤ 80 days (ios:F6). Never external TestFlight for this shell (ios:F5, F19–F20).

**Android distribution**: `keytool -genkeypair -v -keystore ~/secure/word-dance-release.jks -alias worddance -keyalg RSA -keysize 2048 -validity 10000` (back it up: losing it means a new package for updates); `signingConfigs.release` + `keystore.properties` (gitignored); monotonic `versionCode`; `cd android && ./gradlew assembleRelease`; serve the APK from Caddy — add before `reverse_proxy` in `/etc/caddy/Caddyfile`: `handle_path /dl/* { root * /srv/dl; file_server }` (the SPA catch-all would answer `index.html` for `/dl/...`, capacitor:F19); zh install note per brand (allow the source app, dismiss the 风险 scan, Xiaomi 纯净模式 single-install authorisation, autostart/省电 whitelist for the reminder, android:F15, captool:F13). Reaches GMS, GMS-less and HarmonyOS 4.x phones; never HarmonyOS NEXT (卓易通 untested). From 2027, GMS-certified phones need the free limited-distribution account (50 devices, QR handshake, no ID) or the 24-h advanced flow for unverified APKs; GMS-less phones are exempt (android:F1–F4, v-android:F3–F4).

**Estimated person-days**: toolchain 0.5 + skeleton/icons 0.3 + first device runs 0.5 + web adapter 1 + safe-area 0.5 + TTS branch 0.75 + iOS release 0.5 + Android release 0.5 + device matrix/buffer 1 ≈ **5.5–6.5 person-days (≈ 6)**, plus external waits (enrolment 1–3 days, downloads 2–6 h, TestFlight processing minutes). iOS-first ≈ 3 d, Android increment ≈ 1.5–2 d (capacitor summary 7; captool rec 1–6; v-capacitor:F22 notes these are estimates).

**Triggers that justify starting** (decide at day 28 with the §2 numbers): (a) ≥ 3 iPhone friends still active **and** either Bark/Server酱 reminders are judged insufficient (missed days despite reminders) or they explicitly ask for an app badge/icon; (b) ≥ 2 Android friends for whom no zero-code reminder works (no WeChat-based channel acceptable, Server酱³ failing on their ROM) — that is the Android APK's unique gain (local notifications without a relay); (c) the web app has been stable for 2 weeks and you have ≈ 6 person-days + ¥688. HarmonyOS NEXT friends never justify it (web-only regardless). If none fires, re-evaluate monthly; the money and time stay unspent.

---

## 6. zh-CN onboarding message for friends (paste into WeChat; replace the two ⟨⟩ fields)

```
嗨，我做了一个每天背几个英语单词的小工具 word-Dance，邀请你一起用（只有几个朋友在用，是内测）。

网址：https://⟨DOMAIN⟩
你的邀请码：⟨XXXX-XXXX-XXXX-XXXX⟩（只能用一次，14 天内有效，请复制粘贴，不要手打）

一、注册（2 分钟）
1. 重要：不要在微信里直接打开。iPhone 请点右上角「···」→「在 Safari 中打开」；安卓请点「···」→「在浏览器打开」。微信里打开的页面没法添加到桌面，还会多登录一次。
2. 点「去注册」，填用户名、密码（至少 8 位，别用太常见的）、邀请码。邮箱可以不填。
3. 按提示选「目标阶段」「主攻阶段」「每日推送时间」，时区点「自动检测」就行。
   提示：同一个 Wi-Fi 一小时内最多注册 5 个账号（输错邀请码也算次数），如果提示「稍后再试」，换成手机流量或者等一小时。

二、添加到桌面（像 App 一样打开）
- iPhone：Safari 底部「分享」按钮 → 「添加到主屏幕」 → 「添加」。以后从桌面图标进，第一次可能要再登录一次。
- 安卓（小米/OPPO/vivo/荣耀自带浏览器、Chrome、QQ浏览器）：浏览器菜单 → 「添加到桌面」或「添加到主屏幕」。
- 华为（鸿蒙）：华为浏览器右下角「∷」 → 「添加至桌面」。

三、每天的提醒（二选一，1 分钟）
- iPhone 推荐 Bark：App Store 装免费的 Bark → 打开复制那串 https://api.day.app/… 的地址 → 回到 word-Dance「我的」→「推送设置」→ 打开「Webhook 推送」→ 粘贴到「Webhook 地址」→「格式」选 Bark →「发送测试」，手机收到通知就成了。
- 任何手机用微信：浏览器打开 sct.ftqq.com → 微信扫码登录 → 复制 SendKey → 回到 word-Dance「我的」→「推送设置」→ 打开「Webhook 推送」→ 地址填 https://sctapi.ftqq.com/你的SendKey.send →「格式」选 Server酱 →「发送测试」，微信里的「方糖」服务号会收到一条消息（免费版每天 5 条，够用）。
提醒会在你设的「每日推送时间」到，点开就进入今日词汇。暂时先别用「企业微信机器人」和「飞书机器人」，下周修好一个小问题再开放。

四、几件要知道的事
- 密码连输错 10 次会锁 15 分钟，再错会锁更久；忘了密码直接找我重置。
- 单词卡上的「发音」第一次可能要先点一下才出声；如果按钮是灰的，换个浏览器（iPhone 用 Safari，安卓优先用系统自带浏览器或 Chrome/QQ浏览器）。
- 图片是大家共用的：「换一张」和「不合适」会换掉所有人看到的那张图，所以别随手点着玩。
- 你标记的单词和你写的短备注会发给 AI 服务来生成例句；不想保留随时可以在「我的」里导出或删除账号。
- 这是内测，哪里卡住、哪里看不懂直接微信我，我每天都会看一眼后台。
```

If any friend is a minor, add one line for the parent: 「如果是给孩子用，请家长看一下上面第四条再帮忙注册。」 (security open question).

---

## 7. Decisions only the owner can make (recommended default in bold)

| # | Decision | Options | Default and why |
|---|---|---|---|
| D1 | VPS region | Tokyo / Singapore (Hong Kong excluded: 403 from api.anthropic.com, hosting:F2) | **Tokyo**; swap to Singapore if the Day-1 `curl` shows 403 or the 21:00 test shows > 5 % loss (hosting rec 7). Same price either way. |
| D2 | Lighthouse bundle | 2c2g ¥33 vs 2c4g ¥42 | **2c4g**: headroom for `npm ci`/`vite build` on the box and the CLI's stated 4 GB (deploy:F1, F15); check the first-year 活动 price (v-hosting:O6). |
| D3 | Domain and DNS | subdomain of a domain you own / Porkbun + Alipay (no 实名, instant) / Alibaba–Tencent `.com` ¥85 (实名, possible 1–2 day review); DNS at DNSPod free (TTL 600) or Cloudflare DNS-only (60 s) | **Existing domain if any, else Porkbun `.com` $11.81; DNS at DNSPod** (mainland-fast, Tencent console you are in anyway). Cloudflare DNS-only if you want 60 s TTL for re-IP events. Never the Cloudflare proxy for mainland users (hosting:F17). |
| D4 | Service user on the VPS | `sqin` / other | **`sqin`** — zero edits to defaults, units, messages (deploy:F3). |
| D5 | Credential for the `claude -p` runner | A login on disk / B setup-token / C API key / D gateway / E apiKeyHelper (clivps step list) | **Owner's call (deferred policy)**; wiring for each is in §2 step 1.10; whichever it is, keep it in the wrapper or the drop-in, never in `.env` or the unit. Technical facts in step 1.10 apply. |
| D6 | Carry over the Mac database (admin `sqin`, 52 user_words, 48 contents, 30 SVGs) | copy before install (zero work, closes the admin race) / fresh DB + `create-admin` (lose your bank unless export→import) | **Copy**. The curation analysis recommends regenerating the 48 Enterprise-seat contents (docs/WORD_LIBRARY_CURATION.md §0.4) — a policy point deferred by your direction; technically a later 0.5-h SQL/regenerate task either way. |
| D7 | ECDICT on the box | `--with-ecdict` (+1 GB, 216 MB download) / without | **Yes**: custom words become public dictionary entries instantly without a Claude lookup; saves lookup calls (deploy:F17; curation memory). |
| D8 | AI caps and the SVG sub-cap | daily 6 / monthly 100 / hourly 60 (security:F8); SVG 0.50 (default) / 1.00 / 0 | **6 / 100 / 60 before the first invite; SVG decided at 48 h** from the overview's image mix and `wd check providers` from Tokyo (security:F10). Hard ceiling with these caps $180/month; realistic $25–60. |
| D9 | Prewarm | none / top 1,000–2,000 of the friends' main stage (≈ $5–12) / all 9,114 words ($41–54) | **Top 2,000 of the main stage on night 2** if AI is live; full seed only if friends span all four stages (security:F11, v-security:O5). |
| D10 | Invite policy | one single-use 14-day code per friend / one shared 10-use code; `closed` afterwards | **Per-friend codes, then `closed`** (security:F14; attribution in 用户与邀请; a leaked code costs one account). |
| D11 | Reminder channels in week 1 | Bark + Server酱 Turbo only / also 企业微信、飞书、Server酱³ | **Bark + Server酱 Turbo** until W2a ships; the others only after a friend physically receives the test (v-reminders:F3, O1–O2). |
| D12 | Break-glass second admin | yes / no | **Yes** (2 min): anyone who knows your username can lock it for 15 min–24 h and there is no unlock command (security:F4). |
| D13 | Start Apple enrolment (¥688) now | now / when a §5 trigger fires | **Wait**; the enrolment takes 1–3 days, not weeks, so there is no need to pre-pay before evidence (ios:F3). |
| D14 | Any minor in the circle | yes / no | If yes, add the parent line to §6 (no age gate exists). |
| D15 | Mac instance | decommission after 14 days / keep as dev only | **Keep the data dir 14 days as rollback, agents stay booted out**; `make dev` for development is unaffected. |

---

## 8. Risks and mitigations (top 8)

| # | Risk | Likelihood / impact | Mitigation (already in the plan) |
|---|---|---|---|
| R1 | The VPS cannot reach `api.anthropic.com` / `platform.claude.com` (403) or is slow from the mainland | Low in Tokyo/Singapore, confirmed in HK (hosting:F2); impact: no AI at all / unusable site | Step 1.2 `curl` before anything else; 21:00 latency test; Singapore rebuild ≈ 1 h; the site runs on dictionary data without AI (deploy:F2) |
| R2 | Credential fragility: login expiry, fail-closed managed-settings fetch, usage limits, 403 — all surface as 30-min pauses or dead jobs, with a banner that always says "re-login as sqin" | Medium (15 such calls already in the Mac ledger, v-clivps:O1); impact: cards without examples, misleading remedy | Wrapper + pinned CLI + model pin; `wd claude-check` as the only conclusive test; watch `claude_auth`/`claude_unavailable` events daily; 管理 → AI → 恢复 AI; re-login procedure; L4 later |
| R3 | GFW event on the IP or evening packet loss | Low–medium per year (hosting:F20); impact: hours of unreachability | TTL 600; Lighthouse in-place IP swap (once per instance) + snapshot rebuild runbook (v-hosting:O1); no proxy software on the box; Singapore swap |
| R4 | AI spend: the default month cap trips and every friend reads 「明天补齐」 for weeks; or one friend bulk-marks the seed | Medium / medium (security:F7–F8, F17) | Caps 6/100 before invites; weekly 本月花费 check; pause + the corrected two-statement cancel recipe (v-security:F7); nightly consolidation is bounded (v-security:O6) |
| R5 | Per-IP throttles bite a household: 5 registrations/h (failures count), 20 logins/10 min (423s count) | Medium on invite night / low afterwards (v-security:O1–O2) | Per-friend codes, "paste, don't type", stagger or mobile data; `sessions.ip` check proves the proxy trust; L3 later |
| R6 | Admin username locked by a friend's typos; no unlock | Low / high (security:F4) | Break-glass admin (D12); `sqlite3 -cmd ".timeout 5000"` one-liner (v-security:F4) |
| R7 | Reminder false success on 企业微信/飞书/Server酱³ (HTTP 200 + error body → 「测试成功」, `sent`, no trace anywhere) | Certain if offered (v-reminders:F3, O1–O2) | Week 1: Bark + Server酱 Turbo only; others after W2a or physical receipt |
| R8 | Photo providers unreachable → SVG budget burn or text-only cards | Medium (Mac evidence, security:F10; Tokyo unknown) | `wd check providers` on Day 1; 48-h image-mix review; SVG cap 1.00 / 0; optional Pixabay/Pexels keys |

Also tracked: backup pull depends on the Mac waking (RunAtLoad + calendar; weekly check; Lighthouse snapshots as a second copy if the console offers free quota — not verified here); upgrade hygiene (snapshot pruned while serving → 503, restart; never run `install.sh` on the Mac, deploy:F20); Capacitor-specific risks live in §5.

---

## 9. Costs (USD 1 = CNY 6.684, hosting slice rate)

**One-time**
| Item | CNY | USD | Source |
|---|---|---|---|
| Domain, first year: Porkbun `.com` (or `.top` $1.63 first year / $4.63 renewal); Alibaba `.com` ¥85 | ≈ ¥79 (`.com`) | $11.81 | v-hosting:F14 |
| Prewarm top 2,000 words of one stage (optional) | ¥60–80 | $9–12 | security:F11, v-security:O5 |
| Full-seed prewarm (only if chosen) | ¥275–360 | $41–54 | security:F11, v-security:O5 |
| Owner time through day 14 | ≈ 1.3 person-days mandatory, ≈ 3 with every optional patch | — | §2 |
| If the app route starts: Apple Developer Program ¥688/yr; Xcode/Android tooling ¥0 (≈ 15 GB downloads); ≈ 6 person-days | ¥688 | $99 | ios:F1, §5 |

**Monthly, steady state**
| Item | CNY | USD | Source |
|---|---|---|---|
| Tencent Lighthouse Tokyo 2c4g (list; first-year promos ¥199/年 have existed) | ¥42 (¥33 for 2c2g) | $6.00–6.30 | hosting:F4, v-hosting:F4, O6 |
| AI spend for 10 friends, realistic (hard ceiling with the recommended caps $180) | ¥170–400 | $25–60 (cap $100 = ¥670) | security:F8 |
| Bark, Server酱 Turbo free tier, DNSPod free, Caddy TLS | ¥0 | $0 | reminders:F4–F5 |
| Optional: Server酱 paid (if a friend needs > 5 msgs/day) | ¥39/yr | — | reminders:F5 |
| Total | **≈ ¥210–450/month** | **≈ $31–67/month** | — |

Traffic: the 1.5 TB package is > 100× the need; overage would be $0.13/GB in Tokyo (hosting:F4).

---

## 10. Explicitly skipped items and why

| Skipped | Why |
|---|---|
| Variant B (keep the Mac, Cloudflare Tunnel / Quick Tunnel / ssh -R / frp) | Free, but the Mac sleeps after 1 idle minute, the app dies at logout, AI hangs on a hand-started SOCKS tunnel, backups stay on the laptop; Cloudflare's free edge has no mainland PoPs, 40 KB/s-class reports and periodic IP blocks; a named tunnel needs the zone on Cloudflare DNS (deploy:F9, hosting:F17, v-deploy:O5, v-hosting:O5). The VPS costs 2–3 h more once and removes every one of these. |
| Hong Kong hosting, Alibaba SAS, Vultr/DO/Hetzner, Cloudflare proxy, Tailscale | HK = 403 from Anthropic; the others cost the same or more with worse mainland routes; Tailscale is absent from the CN App Store (hosting:F2, F9–F11, F17–F18). |
| Web Push | 6–10 person-days of backend + SW; reaches only Home-Screen iPhones and GMS Android; dead on GMS-less mainland Android; Bark/Server酱 cover the same need for ¥0 (reminders:F13, android:F11). |
| APNs/FCM native push | A consequence of shipping an app, not a faster reminder; FCM unusable on mainland phones (reminders:F14). |
| Service worker (vite-plugin-pwa) | +338 lock packages, a version-skew window per deploy, only buys the Android install prompt and an instant shell; iPhone gains nothing (pwa:F6, F12). |
| Pre-created accounts for friends | Avoids the 5/h throttle but means the owner sets and transmits passwords; per-friend codes + "paste" is enough for 10 people (security gap row 7). |
| E-mail channel / SMTP | Needs a relay and deliverability work to QQ/163 mailboxes; nobody asked; Bark/Server酱 are faster (reminders:F10). |
| 企业微信 / 飞书 / Server酱³ in week 1 | False 「测试成功」 and silent `sent` until W2a (reminders:F3, v-reminders:O1). |
| `ntfy` as a first-class format | A table-rebuild migration + 8 enum sites ≈ 1 day; the template-URL trick works today with the `generic` format (reminders:F9, v-android:O5). |
| Per-user AI quota, `wd unlock`, login-throttle rework, TOTP, audit trail, password reset by e-mail, ToS/privacy pages, word-curation tools | Later-tier for a trusted circle (security gap table rows 6–16); procedures cover them for 10 friends. |
| Curated-mode policy switch (`WD_AI_POLICY=curated`), domestic-model adapter, content-pack CLI | The `docs/WORD_LIBRARY_CURATION.md` programme (35–45 person-days) answers a public-launch question the owner has deferred; this plan does not depend on it. |
| Capacitor M2 (bundled dist) / M3 (bearer token), external TestFlight, App Store, domestic Android stores, HarmonyOS native app, TWA/Bubblewrap, PWABuilder, Tauri, Expo | M2/M3 need backend work and per-change rebuilds; external TestFlight/App Store expose the shell to 4.2 review; stores need 备案 + 软著 and mostly exclude individuals; the rest add toolchains without a gain (capacitor:F2–F3, F22; ios:F19–F20; android:F14; captool:F17–F20). |
| Generalising `sqin` paths/messages, configurable `forwarded_allow_ips`, `WD_CLAUDE_PATH` first-run rewrite | Moot while the VPS user is `sqin` and Caddy is on the same host (deploy:F3, F6). |
| `--effort low` / `--bare` cost tuning | Content quality was verified at the default effort; `--bare` only with a static key; not needed for 10 friends (clivps:F5, F7). |
| Running `deploy/install.sh` or its tests on the Mac | Linux-only by design (deploy:F20, v-pwa:O4). |

---

## Appendix — consistency notes against the fact base (where this plan deliberately deviates)

1. **Invite shape**: deploy:F12 suggests one 10-use/14-day code, security:F14 one 1-use/7-day code per friend; this plan uses one 1-use **14-day** code per friend (attribution + leak containment, but enough slack for slow friends).
2. **Prewarm is not a gate**: security's gap table lists prewarm as "should-before-invite"; here it runs on night 2 if AI is live and never blocks the first invite, because the daily batch builds its ≤ 25 words at batch time anyway (security:F11).
3. **`WD_AI_ENABLED="0"` on day 1 regardless** of whether a credential is ready (deploy:F2 proposes it only "if deferring credentials"): it keeps the first hours free of 30-minute pause churn and the misleading banner while DNS/TLS settle.
4. **TTL**: hosting recommends TTL 300 at DNSPod/Alibaba; the free tiers floor at 600 s (v-hosting:O2), so 600 at DNSPod or 60–300 at Cloudflare DNS-only.
5. **Domain default** is Porkbun (speed, no 实名 review) rather than the domestic registrar the hosting slice lists first; both are in the fact base.
6. **PWA work is split and triggered** (W1 icons in week 1 only if the Day-1 test shows a screenshot icon; `InstallHint`/WeChat detection in week 2) instead of the slice's R1–R6 package before friends arrive (pwa recommendations).
7. **SVG cap decision deferred 48 h** (security:F8 asks to decide before inviting): the deciding fact — provider reachability from Tokyo — is only observable on the box.
8. **Android TTS plugin is mandatory** for the Android app (capacitor:F12 calls it optional): an English-vocabulary app with a grey 发音 button is not shippable to friends.
9. **`insetsHandling: 'native'` + `initialViewportFitValueHint: 'cover'`** instead of the digest's `'css'` (v-capacitor:O4, v-captool:F14).
10. **Carrying the Mac DB as-is** (including the 48 contents / 30 SVGs) is the technical default here; `docs/WORD_LIBRARY_CURATION.md` recommends regenerating them — a policy point the owner deferred; flagged as decision D6, not resolved.
