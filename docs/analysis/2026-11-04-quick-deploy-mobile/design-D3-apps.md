# Design D3 — "apps on purpose": web circle in 3 days, iOS (TestFlight internal) + Android (APK) shells by day 14

Date 2026-11-04 · word-Dance `main` @ 9ab13a5 · owner: solo, part-time, mainland China, Mac (macOS 26.7.1, Apple Silicon, node 22.23.4, no Xcode, no JDK/SDK, api.anthropic.com only through a hand-started SOCKS tunnel fronted by privoxy on 127.0.0.1:8118).

Fact base: the ten `facts/*.md` digests and ten `verify/*.md` reports of 2026-11-04; every element below cites them as `(slice:Fn)`, `(slice verify Fn / omission n)` or `file:line`. Deliberate deviations from a fact-base recommendation are marked **[deviation]** and collected in §10.1.

Parameters used throughout (set them in D1 below; they are the only substitutions in this plan):

| Symbol | Meaning | Example used in commands |
|---|---|---|
| `DOMAIN` | the public hostname (apex or sub-domain; must be the final, non-redirecting origin — see §5.3) | `wd.example.com` |
| `VPS_IP` | the Lighthouse public IPv4 | `43.0.0.10` |
| `APP_ID` | reverse-DNS app id = iOS bundle id = Android `applicationId` (cannot change later) | `com.example.worddance` |
| service user / data dir / checkout on the VPS | fixed to the repo defaults so nothing in `.env` needs editing (deploy:F3) | `sqin` / `/home/sqin/word-dance-data` / `/home/sqin/word-dance` |

Policy, model-licensing and "which credential" questions are deferred by the owner and are not analysed here; the `claude -p` runner stays, the credential is the owner's choice, and only technical facts about credentials are stated (§2.2 task 2.2.1, §7 D3).

---

## 0. One-paragraph pitch

**Day 1:** word-Dance runs on a Tencent Lighthouse box in Tokyo behind Caddy TLS at `https://DOMAIN`, with the Mac's database (1 admin, 52 user_words, 48 contents, 31 images) carried over, invite-only registration, nightly backups pulled to the Mac, and the manifest/icons that make it an installable home-screen app on iPhone and Android; AI may still be switched off while the credential is wired. **Day 3:** `wd claude-check` passes with the credential you chose, caps are set (daily $6 / monthly $100), the top-1,000 words of the friends' stages are pre-generated, reminders work through Bark (iPhone) and Server酱 (everyone with WeChat), and the first two or three friends are registered with single-use invite codes and the zh-CN onboarding message; the Apple Developer enrolment (¥688, 1–3 days) and the Xcode / Android SDK downloads were started on day 0 and are finishing in the background. **Day 14:** the same website, unchanged on the server, is also installed as a Capacitor 8.6 "remote shell" app — iOS via a review-free TestFlight *internal* group (friends added as App Store Connect users), Android via a signed APK served from `https://DOMAIN/dl/` — giving the friends on iPhone and non-Huawei Android a real app icon, a daily on-device reminder at their push time without any relay, and (Android) pronunciation through a native TTS plugin; HarmonyOS NEXT friends stay on the web app with a Server酱 reminder. Total owner effort: ≈ 3 person-days for the web circle (day 0–7), ≈ 2 more for the week-2 hardening patches, ≈ 6 for both apps; running cost ≈ ¥42/month VPS + ¥688/year Apple + whatever the chosen AI credential bills (≈ $25–60/month at API list prices for 10 friends).

---

## 1. Goals and explicit non-goals

**Goals**
1. A public HTTPS deployment reachable from mainland phones within one calendar day, serving ≤ 10 invited friends, with the Mac retired as a server (deploy:F9, hosting:F17).
2. Zero required backend changes before inviting: every "must" is configuration or procedure (security summary, F1–F6).
3. Home-screen installability on iPhone Safari and Android browsers plus a WeChat hand-off hint, because invites travel in WeChat (pwa:F2, F9; ios:F16).
4. A daily reminder for every friend from day 3 through the channels the code already has (Bark, Server酱 Turbo/³) (reminders:F4–F6).
5. iOS and Android apps built as Capacitor 8.6 remote shells (`server.url = https://DOMAIN`) — zero backend change, website deploys are app updates (capacitor:F1, F20; captool:F9) — distributed review-free (TestFlight internal, APK sideload) (ios:F4, F22; android:F15).
6. Sequencing in which the apps never delay the web launch: every app task is on the Mac or at Apple/Google, never on the VPS critical path.

**Non-goals (this round)**
- App Store or domestic-store listings, external TestFlight links, Beta App Review (ios:F19–F20; android:F14).
- Web Push, APNs/FCM, a service worker, offline mode (reminders:F13–F14; android:F11; pwa:F6/A5).
- Hong Kong or mainland hosting, Cloudflare Tunnel/Mac hosting, Tailscale (hosting:F2, F17, F18).
- Per-user AI quotas, 2FA, password reset by e-mail, ToS pages, word-curation tooling (security gap table rows 9, 4, 11, 14, 15).
- A native HarmonyOS (ArkTS) app (android:F5, rec 8).
- Any change to how `claude -p` is authenticated beyond config-only wiring (clivps:F9).

---

## 2. Phases as day-by-day tasks

Format per task: **what** / how (commands, keys, paths, UI) / time / done-criterion. Days are calendar days from D0 = 2026-11-04 (Wed); D3 = Sat 11-07, D7 = Wed 11-11, D14 = Wed 11-18. "Mac" tasks run on the owner's laptop, "VPS" tasks over SSH. App-track tasks are in §5; the ones that must *start* early (because of waits) are listed here as `[app]`.

### Phase 0 — D0 (evening, ≈ 1.5 h): decisions, purchases, long downloads started

**0.1 Decide the parameters** — fill §7 D1–D5 (domain, region, credential path, DB carry-over, friends' stages). 15 min. Done: `DOMAIN`, `APP_ID`, region written down.

**0.2 Buy the domain** — Porkbun `.com` $11.81/yr via Alipay (hosting verify F14) **[deviation: hosting default was an Alibaba `.com` with 实名]** — reason: no 1–2 day 实名 review, and DNS can go to Cloudflare DNS-only with a 60 s TTL instead of the 600 s floor of DNSPod/Alibaba free tiers (hosting verify omission 2). Point the domain's nameservers at a free Cloudflare zone, **grey cloud (DNS only), never proxied** (hosting:F17). 20 min. Done: `dig NS DOMAIN` shows Cloudflare nameservers (propagation ≤ 24 h, usually < 1 h). Alternative if you prefer a domestic console: Alibaba `.com` ¥85 + Alibaba DNS, TTL 600 s (hosting:F14, verify omission 2).

**0.3 Buy the VPS** — Tencent Cloud 中国站 → 轻量应用服务器 → 东京, Ubuntu 24.04 image (verify in the console: hosting:F7), 2 vCPU/4 GB/60 GB/1.5 TB bundle ≈ ¥42/month (intl list $6.00; check the 活动 page — first-year ¥199/year promos exist; hosting:F4, verify omission 6); bind your SSH public key; Lighthouse firewall: allow 22 (your IP if possible), keep 80/443 **closed** for now. 20 min. Done: `ssh ubuntu@VPS_IP` works.

**0.4 First reachability test from the box** (decides the region before anything else is installed; hosting:F2, F19; clivps:F8, verify omission 6):
```bash
for u in https://api.anthropic.com/v1/models https://platform.claude.com/ https://downloads.claude.ai/claude-code-releases/latest \
         https://commons.wikimedia.org/ https://api.openverse.org/v1/images/?q=apple https://sctapi.ftqq.com/ https://api.day.app/ https://github.com/; do
  printf '%-60s %s\n' "$u" "$(curl -sS -o /dev/null -m 10 -w '%{http_code}' "$u")"; done
```
Expected: `api.anthropic.com` → **401** (reachable, no key; 403 = region/network block), `platform.claude.com` → 200/302 (not 403), downloads → 200, Wikimedia/Openverse → 200 (photo providers were dead from the Mac's network: security:F10), Server酱/Bark hosts → any 2xx/4xx. 5 min. Done: no 403/timeouts. If `api.anthropic.com` answers 403, rebuild the instance in 新加坡 (same price) before continuing (hosting:F2; Singapore has the leyline confirmation).

**0.5 `[app]` Start the Apple Developer Program enrolment** on the Mac in the Apple Developer app (macOS 26.0+ met; ios:F2): legal name exactly as on the 身份证, CFCA ID + selfie, pay ¥688/year with Alipay/WeChat Pay/card bound to the Apple Account (not Apple Account balance; ios:F1); keep the same device for the whole flow. 30–45 min, then 1–3 days wait (ios:F3). Done: "membership confirmation" e-mail (contact Apple if none within 24 h of purchase).

**0.6 `[app]` Start the Xcode 27.2 download** from the Mac App Store (3.12 GB; needs macOS 26.6+, met; ios:F11). Apple's store CDN normally serves the mainland directly, so no proxy; let it run overnight. Do **not** download the iOS simulator runtime (≈ 7.9 GB; captool:F21) — tests run on real phones. Done: Xcode.app present (install continues in 5.x).

**0.7 Poll the friends (one WeChat message, 5 min):** phone model + OS version (iOS ≥ 16 for TestFlight, ios:F6; Huawei: HarmonyOS 4.x vs NEXT, android:F5), which exam stage they study (zk/gk/cet4/cet6 — decides the prewarm bill, security:F11), whether they will accept an App Store Connect invitation later (ios:F4), and the e-mail of their Apple Account (ios verify omission 4). Done: a 10-row table.

### Phase 1 — D1 (≈ 4 h): the site is live, data migrated, admin exists, backups on

**1.1 Mac: freeze and export the live data** (deploy:F11, verify F11):
```bash
launchctl bootout gui/$(id -u)/com.word-dance.server            # stop the Mac service (leave it stopped: two instances would diverge)
sqlite3 /Users/sqin/word-dance-data/word-dance.db "VACUUM INTO '/Users/sqin/wd-migrate.db'"   # consistent single file, no -wal/-shm
tar -C /Users/sqin/word-dance-data -czf /Users/sqin/wd-images.tgz images                        # 216 KB, 28 shard dirs
```
Never copy `.env` (Mac-specific `WD_CLAUDE_BIN` wrapper, `WD_CLAUDE_PATH`, `WD_LOG_FILE`; `WD_SECRET_KEY` only protects unexpired e-mail codes). 10 min. Done: both files exist; `launchctl list | grep word-dance.server` → nothing.

**1.2 VPS as `ubuntu`/`root`: service user `sqin`, sudo, firewall** (deploy Variant A step 1; user name `sqin` avoids every `.env`/unit edit: deploy:F3):
```bash
sudo adduser --disabled-password --gecos "" sqin && sudo usermod -aG sudo sqin
echo 'sqin ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/sqin && sudo chmod 440 /etc/sudoers.d/sqin   # install.sh needs sudo -n
sudo install -d -m 700 -o sqin -g sqin /home/sqin/.ssh && sudo cp ~/.ssh/authorized_keys /home/sqin/.ssh/ && sudo chown sqin:sqin /home/sqin/.ssh/authorized_keys
sudo apt-get update && sudo apt-get install -y ufw && sudo ufw allow OpenSSH && sudo ufw --force enable   # 80/443 stay closed until the admin exists
```
10 min. Done: `ssh sqin@VPS_IP sudo -n true` prints nothing.

**1.3 VPS as `sqin`: prerequisites install.sh does not install** (deploy:F1, F15, verify F1 + omission 4):
```bash
sudo apt-get install -y git curl ca-certificates gnupg openssl python3 python3-venv python3.12-venv sqlite3 rsync
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update && sudo apt-get install -y nodejs && node --version      # must be v22.12+ (Vite 8 engines); apt's own nodejs is 18.19
python3 -c 'import sys,venv,ensurepip,sqlite3,zoneinfo; print(sys.version)'   # >= 3.12
```
Then the Claude CLI **as `sqin`, never via sudo** (clivps:F1, verify F1 nuance), pinned to the stable channel so the binary under systemd does not change silently (clivps:F2) **[deviation: deploy slice suggested the apt channel]** — the native launcher at `~/.local/bin/claude` matches the repo default `WD_CLAUDE_BIN=/home/sqin/.local/bin/claude` (`backend/wd/config.py:85`), so no `.env` edit:
```bash
curl -fsSL https://claude.ai/install.sh | bash -s stable          # launcher ~/.local/bin/claude -> ~/.local/share/claude/versions/2.1.311
exec $SHELL -l && claude --version                                # re-login so ~/.local/bin is on PATH (install.sh preflight needs `command -v claude`)
```
15–25 min. Done: `node --version`, `python3 --version`, `claude --version` all print.

**1.4 VPS: checkout + pre-placed data** (deploy:F11 option i — copying *before* the first install closes the admin-bootstrap race and makes `migrate`/`import-seed`/`create-admin` no-ops: deploy:F5, security:F3):
```bash
git clone https://github.com/bigBuffers/word-dance.git /home/sqin/word-dance   # private repo: add a deploy key first, or rsync the Mac checkout without node_modules/.venv
cd /home/sqin/word-dance && git checkout main
install -d -m 0700 /home/sqin/word-dance-data
# from the Mac:
#   scp /Users/sqin/wd-migrate.db sqin@VPS_IP:/home/sqin/word-dance-data/word-dance.db
#   scp /Users/sqin/wd-images.tgz sqin@VPS_IP:/home/sqin/
tar -C /home/sqin/word-dance-data -xzf /home/sqin/wd-images.tgz && chmod 600 /home/sqin/word-dance-data/word-dance.db && rm /home/sqin/wd-images.tgz
```
10 min. Done: `sqlite3 /home/sqin/word-dance-data/word-dance.db "select username, role from users"` → `sqin|admin`; `ls /home/sqin/word-dance-data/images | wc -l` → 28.

**1.5 VPS: rehearse, then install with Caddy and ECDICT** (deploy:F4, F17, F20; `--with-ecdict` chosen **[deviation: deploy left it an open question]** — 60 GB disk has room and real-word custom adds then publish without an AI lookup, memory note):
```bash
cd /home/sqin/word-dance
deploy/install.sh --with-caddy DOMAIN --with-ecdict --contact-email you@example.com --dry-run   # preflight must pass; prints every step with '+'
deploy/install.sh --with-caddy DOMAIN --with-ecdict --contact-email you@example.com
```
What it does: venv + pip (manylinux wheels, no compiler), `npm ci && vite build` into `frontend-releases/<sha>`, `.env` created once with `WD_SECRET_KEY`, `WD_CLAUDE_BIN`, `WD_DATA_DIR`, `WD_CONTACT_EMAIL`, and the proxy trio `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://DOMAIN"`, `WD_TRUST_PROXY="1"` (deploy:F4, F6; security:F6); `wd migrate` → 0 pending; `import-seed` → up to date; `wd claude-check` → WARN (not logged in yet — non-fatal, deploy:F2); `create-admin --if-none` → "users already exist"; units rendered with `User=sqin`; Caddy 2.6.2 installed, `/etc/caddy/Caddyfile` written for `DOMAIN`; ECDICT 216 MB download → 851 MB `stardict.db`, `WD_ECDICT_DB_PATH` written. 15–25 min (npm ci dominates). Done: `curl -fsS http://127.0.0.1:8000/api/health` → `{"status":"ok", ..., "registration_mode":"invite","needs_setup":false}`.

**1.6 VPS: `.env` hand edits + restart** (quoting rule `KEY="value"`, `WD_*` lines only — install.sh aborts otherwise: deploy:F4, clivps:F9):
```bash
E=/home/sqin/word-dance-data/.env
sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="0"|' $E                       # site serves SPA/API/dictionary without AI; flipped in 2.2 (deploy:F2)
sed -i 's|^WD_AI_MODEL=.*|WD_AI_MODEL="claude-sonnet-5-5"|' $E          # pin what the content was verified on (clivps:F7)
sed -i 's|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="6.00"|; s|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="100.00"|; s|^WD_AI_SVG_DAILY_BUDGET_USD=.*|WD_AI_SVG_DAILY_BUDGET_USD="1.00"|' $E   # security:F8 (+10 % headroom, verify omission 5)
grep -nE '^WD_(REGISTRATION_MODE|PUBLIC_URL|TRUST_PROXY|HOST|AI_ENABLED|AI_MODEL)=' $E   # invite / https://DOMAIN / 1 / 127.0.0.1 / 0 / claude-sonnet-5-5
sudo systemctl restart word-dance && curl -fsS http://127.0.0.1:8000/api/health
```
5 min. Done: health OK; `journalctl -u word-dance -n 30 -o cat` shows "ready", no tracebacks.

**1.7 DNS + TLS + open the door** (deploy Variant A step 6; security:F6):
```bash
# Cloudflare DNS (grey cloud): A  DOMAIN -> VPS_IP, TTL Auto (300 s) or 60 s. No AAAA unless the box has v6. No www record (origin pinning, §5.3).
sudo ufw allow 80,443/tcp            # and open 80/443 in the Lighthouse console firewall
sudo systemctl reload caddy && sleep 20 && curl -sSI https://DOMAIN/api/health | grep -iE 'HTTP/|strict-transport'
journalctl -u caddy -n 20 --no-pager | grep -i certificate
```
10–30 min incl. propagation. Done: `HTTP/2 200` + `strict-transport-security`; phone (mobile data) opens `https://DOMAIN`, the register page shows the invite-code field (not 「尚无账号…」), you log in as `sqin` with the Mac password, 管理 loads.

**1.8 Mac: pull backups off-box nightly** (deploy:F14; `docs/ops.md` §2). The VPS timer runs `wd backup --keep-daily 14 --keep-weekly 8` at 03:30 Asia/Shanghai; pull at 07:30 (launchd runs a missed calendar job at the next wake):
```bash
mkdir -p ~/word-dance-vps-backups && cat > ~/Library/LaunchAgents/com.word-dance.vps-backup-pull.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.word-dance.vps-backup-pull</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/rsync</string><string>-a</string><string>--delete</string>
    <string>sqin@VPS_IP:/home/sqin/word-dance-data/backups/</string>
    <string>/Users/sqin/word-dance-vps-backups/</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/sqin/word-dance-vps-backups/pull.log</string>
  <key>StandardErrorPath</key><string>/Users/sqin/word-dance-vps-backups/pull.log</string>
</dict></plist>
EOF
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.vps-backup-pull.plist
launchctl kickstart gui/$(id -u)/com.word-dance.vps-backup-pull && ls ~/word-dance-vps-backups/
```
Also copy `/home/sqin/word-dance-data/.env` once into your password manager (ops.md §2). 15 min. Done: at least one `word-dance-*.db.gz` on the Mac after D2 07:30; restore drill (`gunzip -c … > /tmp/check.db` + `PRAGMA integrity_check`, ops.md §2) passes once.

**1.9 Mac (parallel, while 1.5 runs): home-screen icons + manifest + links, commit, redeploy** — pwa A1–A3, R1–R2, 1 h. The five `sips` commands (verified byte-identical: pwa verify F5) produce `frontend/public/icons/icon-{192,512}.png`, `icon-maskable-{192,512}.png`, `frontend/public/apple-touch-icon.png` (opaque 180 px, iPhone-critical) from `favicon.svg` + the full-bleed `icon-maskable.svg`; add `frontend/public/manifest.webmanifest` exactly as pwa A1 (`start_url: "/today"`, `scope: "/"`, `display: "standalone"`, icons 192/512 + maskable); insert after `frontend/index.html:13`:
```html
    <meta name="mobile-web-app-capable" content="yes" />
    <link rel="manifest" href="/manifest.webmanifest" />
    <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
```
`cd frontend && npm run lint && npm run typecheck && npm test && npm run build` (≈ 15 s; pwa:F10), commit, push; on the VPS `cd /home/sqin/word-dance && git pull && deploy/install.sh` (no `--with-caddy` on upgrades: deploy:F4, F13; downtime ≈ seconds). Done: `curl -sI https://DOMAIN/manifest.webmanifest` → `application/manifest+json`; iPhone Safari 分享 → 添加到主屏幕 shows the blue "W" icon; Android Chrome ⋮ shows 安装应用/添加到主屏幕 (pwa:F7; android:F8).

**1.10 Evening latency check from your own phone** (hosting rec 7): at ~21:00 on mobile data and home Wi-Fi, `ping VPS_IP` for 60 s and open the site. 5 min. Done: loss ≤ 5 %, pages load < 2 s; otherwise rebuild in Singapore on D2 (same price; ≈ 1 h redo of 1.3–1.7 from a snapshot).

### Phase 2 — D2 (≈ 3.5 h): AI on, caps, prewarm, reminders dry-run, WeChat hint

**2.1 Credential wiring (config only, credential-neutral)** — clivps:F9 step list; the runner forwards only `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, proxies, `SSL_CERT_*`, `CLAUDE_CONFIG_DIR`, `XDG_*` (`backend/wd/ai/runner.py:49-62`); everything else (`CLAUDE_CODE_OAUTH_TOKEN`, `DISABLE_AUTOUPDATER`, a proxy for the CLI only) must come from a wrapper named by `WD_CLAUDE_BIN`. Create the wrapper regardless of the credential (it also pins against background updates, clivps:F2):
```bash
install -d -m 0700 /home/sqin/word-dance-data/bin && cat > /home/sqin/word-dance-data/bin/claude-wrapper <<'EOF'
#!/bin/sh
export DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
# exactly one credential line, or none to use the login stored under $HOME/.claude/.credentials.json (0600):
# export CLAUDE_CODE_OAUTH_TOKEN="$(cat /home/sqin/word-dance-data/oauth.token)"
# export ANTHROPIC_API_KEY="$(cat /home/sqin/word-dance-data/anthropic.key)"
# export ANTHROPIC_AUTH_TOKEN="$(cat /home/sqin/word-dance-data/gateway.token)" ANTHROPIC_BASE_URL=https://gateway.example.com
# egress proxy for the CLI only (HTTP CONNECT; the CLI does not support SOCKS): export HTTPS_PROXY=http://127.0.0.1:8118 NO_PROXY=localhost,127.0.0.1
exec /home/sqin/.local/bin/claude "$@"
EOF
chmod 0700 /home/sqin/word-dance-data/bin/claude-wrapper
sed -i 's|^WD_CLAUDE_BIN=.*|WD_CLAUDE_BIN="/home/sqin/word-dance-data/bin/claude-wrapper"|' /home/sqin/word-dance-data/.env
```
Per credential type (clivps step list A–E): **A** stored login — `claude auth login` as `sqin`, copy the printed URL into the Mac's browser (the Mac browser must reach `claude.ai`/`platform.claude.com`, i.e. through the Mac's proxy: clivps verify omission 6), paste the code at `Paste code here`, `claude auth status --text` → exit 0; it expires and then every call fails with `Login expired · Please run /login` (30-min pauses + banner) until repeated as the same user. **B** `claude setup-token` → one-year token in `oauth.token` (0600), exported by the wrapper only. **C** `ANTHROPIC_API_KEY` → wrapper line or a `claude.env` + systemd drop-in (`sudo systemctl edit --drop-in=claude word-dance.service` → `EnvironmentFile=-/home/sqin/word-dance-data/claude.env`). **D** bearer gateway (`ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_BASE_URL`). **E** `apiKeyHelper` via `/etc/claude-code/managed-settings.json` or `WD_AI_EXTRA_ARGS="--settings /path.json"` (survives tier-1 `--restricted`). Technical facts recorded for the decision (no recommendation): the login used on the Mac enforced a fail-closed server-managed-settings fetch — 15 calls between 2026-11-02T18:43Z and 11-03T02:26Z died with "Your organization requires remote managed settings to load, but they could not be loaded", each misfiled as `auth` → 14 `claude_auth` events and 30-minute global pauses, and with that login every spawn needs a live round-trip to `api.anthropic.com` before the model call (clivps verify omission 1); Hong Kong datacentre IPs and this Mac's network get `403 Request not allowed` from both `api.anthropic.com` and `platform.claude.com` (hosting:F2; clivps verify omission 6); `--bare` will become the `-p` default in a future release and never reads OAuth credentials (clivps:F5). 20 min + the login round-trip. Done: `cd /home/sqin/word-dance && WD_DATA_DIR=/home/sqin/word-dance-data .venv/bin/wd claude-check` → `claude check OK: tier 1, cost $0.00xx, … model claude-sonnet-5-5, claude 2.1.311`, exit 0 (clivps:F10).

**2.2 Flip AI on** — `sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="1"|' /home/sqin/word-dance-data/.env && sudo systemctl restart word-dance`; if the copied DB carried a past `kv.claude.paused_until`, 管理 → AI → 恢复 (deploy:F11; ops.md §6). Watch `journalctl -u word-dance -o cat | grep -E '"event":"claude_'` for the first `claude_call`. 5 min. Done: first `lookup`/`content` call `success` in 管理 → 概览.

**2.3 Prewarm the friends' stages** (security:F11; ≈ $5.9 per 1,000 words at the measured $0.0059/word, verify omission 5; whole zk ≈ $12.4, whole seed ≈ $54). Temporarily raise the gates, restart, run plans, restore:
```bash
E=/home/sqin/word-dance-data/.env
sed -i 's|^WD_AI_PREWARM_DAILY_BUDGET_USD=.*|WD_AI_PREWARM_DAILY_BUDGET_USD="20.00"|; s|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="40.00"|; s|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="150.00"|; s|^WD_AI_HOURLY_CALL_CAP=.*|WD_AI_HOURLY_CALL_CAP="120"|' $E
sudo systemctl restart word-dance
# 管理 → AI → 预生成: stage = the polled stage(s), limit 1000 (or 2000), max_budget_usd 15 → runs 1.7–3.4 h per 1,000–2,000 words at 60 calls/h, half at 120
# afterwards (same evening or D3 morning):
sed -i 's|^WD_AI_PREWARM_DAILY_BUDGET_USD=.*|WD_AI_PREWARM_DAILY_BUDGET_USD="1.00"|; s|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="6.00"|; s|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="100.00"|; s|^WD_AI_HOURLY_CALL_CAP=.*|WD_AI_HOURLY_CALL_CAP="60"|' $E
sudo systemctl restart word-dance
```
15 min of attention. Done: 概览 shows `words.with_content` ≥ 1,000 for the stage; `budget_*` events absent.

**2.4 Photo-provider check → SVG cap** (security:F10): after prewarm, `sqlite3 -cmd ".timeout 5000" /home/sqin/word-dance-data/word-dance.db "select provider, status, count(*) from word_images group by 1,2; select name, cooldown_until, last_error from provider_state"`. If Wikimedia/Openverse work from Tokyo, keep `WD_AI_SVG_DAILY_BUDGET_USD="1.00"` (≈ 80 SVG cards/day); if they also fail there, register a free Pixabay key (`WD_PIXABAY_KEY`, `deploy/env.example:105`) on D4 and keep the SVG cap. 10 min. Done: decision noted in ops notes.

**2.5 Reminder dry-run on your own devices** (reminders rec 1, F4–F6, F15 — the channels have never fired on this instance; `WD_PUBLIC_URL` is now set so links point at `https://DOMAIN/today`, reminders:F11): on your iPhone install **Bark** (App Store, free), copy `https://api.day.app/<key>`, in word-Dance 我的 → 推送设置 → Webhook 推送 on → Webhook 地址 → 格式 `Bark` → 发送测试 (1 per 10 min) → a lock-screen notification arrives. On WeChat: `sct.ftqq.com` → 微信扫码登录 → SendKey → URL `https://sctapi.ftqq.com/<SendKey>.send` → 格式 `Server酱` → 发送测试 → a 方糖 service-account message arrives (free tier 5/day; card shows the title only). Note: 企业微信/飞书/Server酱³ answer HTTP 200 for a bad key and the UI would show 「测试成功」 anyway — do not offer them to friends until the week-2 patch (reminders:F3, verify omission 1). 30 min. Done: both notifications received on real devices; `GET /api/admin/jobs?type=send_webhook` empty (test sends are synchronous).

**2.6 Mac: InstallHint + WeChat hand-off + backend one-liners** (pwa A4, A6/R3–R4; 4–5 h; may spill to D3 morning): `src/utils/platform.ts` (UA detection: `MicroMessenger`, `\bQQ\/\d`, iOS, Android, `display-mode: standalone`), `src/components/layout/InstallHint.tsx` mounted on `/today` (WeChat/QQ card non-dismissible with 「微信内无法添加到主屏幕：点击右上角「⋯」，选择「在浏览器打开」」; iOS/Android cards dismissible 14 days via `useLocalPref`), a 「添加到主屏幕」 row in 我的, the `zh.install` block added **identically** to `src/i18n/zh.ts` (after `history:`, before `settings:` at `:74`) and `docs/FRONTEND.md` §8 (before `:275`) — `zh.test.ts` diffs them line for line (pwa:F10); unit tests with UA fixtures. Backend: in `backend/wd/main.py` `_mount_spa` answer `ApiError("not_found")` for any `assets/*` path that is not a file and `Cache-Control: no-cache` for `manifest.webmanifest`, `index.html` (literal path is 1 h cacheable today: pwa verify omission 1) and `sw.js`/`registerSW.js`; extend `test_health.py::test_spa_serves_built_files_with_cache_policy`. Gate: `npm run lint && npm run typecheck && npm test && npm run build` + `.venv/bin/pytest -q backend/tests/integration/test_health.py backend/tests/unit/test_docs_contract.py`. Deploy with `git pull && deploy/install.sh`. Done: opening `https://DOMAIN/today` inside WeChat shows the hand-off card; in Safari a dismissible 添加到主屏幕 card.

### Phase 3 — D3 (Sat, ≈ 2 h): first friends

**3.1 Invite codes** — one single-use code per friend, 7 days, note = name (security:F14) **[deviation: deploy slice proposed one 10-use/14-day code]** — reason: traceability and a code that dies after use; cost is zero:
```bash
cd /home/sqin/word-dance && for f in 小明 小红 阿强; do WD_DATA_DIR=/home/sqin/word-dance-data .venv/bin/wd invite --uses 1 --days 7 --note "$f"; done   # code printed once on stdout (XXXX-XXXX-XXXX-XXXX)
```
or 管理 → 邀请码 (deploy:F12). 5 min. Done: codes pasted into the per-friend messages.

**3.2 Send the onboarding message (§6) to 2–3 friends first**, each with their code, and schedule registrations so no more than 5 happen from one Wi-Fi within an hour — failed code entries also count (security:F5, verify omission 1); on launch night 10 friends × 2 devices fit the 20-logins/10-min window exactly, so one device each. 30 min incl. hand-holding. Done: each friend has logged in, finished 欢迎/onboarding (stage, push time), appears in 管理 → 用户, and `sqlite3 -cmd ".timeout 5000" … "select ip from sessions order by id desc limit 3"` shows **real client IPs** (proves `WD_TRUST_PROXY`; security rec 3).

**3.3 Per-friend reminder channel** (reminders matrix): iPhone → Bark (10 min each, `url` tap opens the default browser at `/today`); Android/HarmonyOS/anyone who prefers WeChat → Server酱 Turbo (10 min; WeChat card title-only, detail on tap); Android friends who want a real system notification → Server酱³ app (sc3 URL `https://<uid>.push.ft07.com/send/<key>.send`, same `Server酱` format; vendor push channels 小米/华为/荣耀/vivo/OPPO; verify receipt by phone because the test button cannot tell: reminders verify omission 1). 10–15 min per friend. Done: the friend confirms the test message on their phone; next morning's digest (push time + prebuild ≤ 3 h, reminders:F1) arrives.

**3.4 Watch the first evening**: 概览 (today_usd, queued/dead jobs, provider cooldowns, events), `journalctl -u word-dance -o cat | grep -E '"status":5|"event":"(budget|claude_auth|claude_unavailable)'`. 10 min.

### Phase 4 — D4–D7 (≈ 30 min/day): the rest of the circle + first-week watch list

**4.1 Invite the remaining friends** (same procedure; 2–3 per day keeps registrations under the per-IP limits and support manageable).

**4.2 First-week watch list** (daily, 10–15 min; security rec 3; deploy:F14; reminders:F15):

| Check | How | Act when |
|---|---|---|
| Spend and queue | 管理 → 概览: `ai.today_usd`, `month_usd`, `svg`, `jobs.queued/running/dead` | today > $4 before noon → look for a mass-mark flood (security:F7; cancel recipe with the corrected two statements, security verify F7); dead > 0 → 管理 → 任务 → 重试 |
| AI health | events `claude_auth`, `claude_unavailable`, `budget_*`; banner 「Claude CLI 未登录」 | pause/banner → check the credential path (2.1) rather than "re-login" blindly; `wd claude-check` is the test |
| Deliveries | `GET /api/admin/jobs?type=send_webhook` (`last_error`), ask friends on day 1 | a friend reports nothing arrived → their relay key; WeCom/Feishu/sc3 false-success is invisible until the week-2 patch |
| Photos vs SVG | 概览 `words.with_photo / with_claude_svg / card_only`, `provider_state` cooldowns | mostly SVG/text → Pixabay key or raise the SVG cap (ops.md §6) |
| Lockouts / throttles | `select key, count, blocked_until from auth_throttle` | a locked friend → `sqlite3 -cmd ".timeout 5000" …/word-dance.db "DELETE FROM auth_throttle WHERE key='login:user:<name>'"` (security verify F4); forgotten password → 管理 → 用户 → 重置密码 (security:F16) |
| Backups | `systemctl status word-dance-backup.timer`; `ls ~/word-dance-vps-backups/` on the Mac | missing file → `journalctl -u word-dance-backup`; `system_events backup_failed` |
| TLS / uptime | `curl -sSI https://DOMAIN/api/health`; `journalctl -u caddy -n 5` | 5xx → `systemctl status word-dance`; `downtime` event in 概览 |
| Disk / memory | `df -h /home`, `free -m` | < 5 GB free → prune `frontend-releases`, old `pre-migrate-*.db.gz` |
| Mainland reachability | your evening ping/curl (1.10) once more on D4 and D7 | loss > 5 % → Singapore rebuild; GFW event → Lighthouse IP swap (once per instance, hosting verify omission 1) + DNS update |

**4.3 End of week 1**: `WD_REGISTRATION_MODE="closed"` once everyone is in (+ restart; security:F14); write the D1–D7 learnings (latency, photo providers, credential incidents) into `docs/ops.md`.

### Phase 5 — week 2 (D8–D14, ≈ 2 person-days): hardening patches that friends will notice

Ordered by friend impact; each is a small, tested change (details in §4):
1. Webhook body check + WeCom markdown + URL in the test message (1 pd) — then 企业微信/飞书/Server酱³ may be offered.
2. Standalone/native export fallback (0.25 pd) — iPhone home-screen users hit WebKit bug 290847 otherwise (pwa:F8).
3. Real `deferred_until` date instead of 「明天」 (0.2 pd; security:F17).
4. Classifier + credential-neutral banner (0.5 pd; clivps:F11, verify omissions 1–2) — stops one network blip from pausing AI for 30 minutes with a misleading message.
5. Optional `wd unlock <username>` (0.2 pd) and the login-throttle fix (0.5 pd; security gap 7).

The app track (§5) runs in parallel from D0; its first friend-visible artefacts land D10–D14.

**Effort totals.** Web circle, D0–D7: ≈ 22 h ≈ **3.0 person-days** (owner, first time). Week-2 hardening: ≈ 2.0–2.25 person-days. Apps: ≈ **6 person-days** (range 5–7.5, §5.7), spread over D0–D14 and gated by Apple's 1–3-day enrolment and the downloads, never by the VPS.

---

## 3. Mobile route per device class

Legend: **Install** = how the friend gets an icon · **Reminder** = the daily nudge · **Pronunciation** · **Login** · **App gain** = what the §5 app adds over the home-screen web app.

| Device class | Install (web, from D1) | Reminder (from D3) | Pronunciation | Login | App gain (D10–D14) |
|---|---|---|---|---|---|
| **iPhone, Safari** (iOS 26 ≈ 75 % of CN iOS traffic, iOS 18 ≈ 16 %; ios:F21) | Open `https://DOMAIN` in Safari → log in → 分享 → 添加到主屏幕; opens as a standalone web app by default on iOS 26, via the existing Apple metas on ≤ 25 (pwa:F7, ios:F14). Cookies incl. login are copied at add-time on ≥ 17.2 per ios:F17; the pwa verifier expects one extra login — either way the 30-day sliding session then keeps them in (pwa:F8). | **Bark** (App Store, free): paste `https://api.day.app/<key>`, 格式 Bark; true lock-screen push via APNs; tap opens the default browser at `/today` (reminders:F4). WeChat users may use Server酱 instead. | Web Speech works; the first card after a cold launch may stay silent until the first tap (pwa:F8). | Username + password; invite code once; 10 wrong passwords → 15-min lock (security:F4). | TestFlight app: on-device daily reminder without a relay (iOS repeating calendar trigger, capacitor:F14), auto-pronounce without the first tap (inferred from WebKit source, capacitor verify F12), silent-switch bypass via the TTS plugin, icon/launch without the Safari ritual. Costs: ASC invitation, 90-day re-installs, export via fallback. |
| **iPhone inside WeChat** | WeChat's WebView cannot add to Home Screen → right-top「···」→「在Safari中打开」(ios:F16); the InstallHint card says so (2.6). WeChat may show a 「非微信官方网页」 interstitial for a new domain — test with one friend. | as above | as above (inside WeChat's WebView: untested) | as above; WeChat's WebView has its own cookie jar → log in again there or, better, never use the site inside WeChat | as above |
| **GMS Android** (global ROM / Pixel / Samsung, or Google services switched on + proxy; android:F17) | Chrome ⋮ → 安装应用 → real WebAPK once the manifest exists (android:F8–F9; no service worker needed, prompt may not auto-appear, pwa:F7). | Server酱 Turbo (WeChat) or ntfy Play build (FCM) via the `generic` format + template URL (reminders:F9); Web Push not built. | Chrome bridges to the system TTS engine; needs an English voice installed (android:F13). | same | APK: on-device reminder, TTS via plugin, no browser chrome. 2026: plain sideload; 2027: register a free limited-distribution account (≤ 50 devices) or the friend uses the 24-h "advanced flow" (android:F1–F3, verify F3). |
| **GMS-less domestic Android** (Xiaomi HyperOS / OPPO ColorOS / vivo OriginOS / Honor MagicOS — the mainland default) | Vendor browser menu → 添加到桌面 / 添加至桌面 creates a launcher shortcut that opens the browser; standalone display is undocumented for every vendor browser (android:F10); Chrome, if present, adds a badged shortcut, not a WebAPK (android:F9). | **Server酱 Turbo → WeChat** (title-only card, tap opens WeChat's browser) by default; **Server酱³ app** for a real system notification through 小米/华为/荣耀/vivo/OPPO push channels (reminders:F5–F6). No Web Push possible (android:F11). | Chromium-based vendor browsers very likely bridge to the system TTS, untested; English voice availability per OEM engine untested (android:F13, open q 2). | same | **APK is the biggest win here**: a real app icon and standalone window, an on-device reminder at push time (exact alarm, §5.4), pronunciation via the TTS plugin (the shell's WebView has no Web Speech at all, captool:F15) — provided the friend allows the "unknown source", dismisses the 风险 scan / 纯净模式 prompt once (android:F15) and whitelists autostart/battery on Xiaomi/Huawei (captool:F13). |
| **HarmonyOS 4.x Huawei** (not upgraded to 5) | Huawei Browser ∷ → 添加至桌面 (PWA-capable sites get a 快应用 shortcut; android:F7). | Server酱 Turbo → WeChat; or the APK's local notification. | Huawei browser/engine untested. | same | APK installs (AOSP layer present; android:F5) with Huawei 纯净模式 friction; shrinking class. |
| **HarmonyOS NEXT (5/6/7)** — every Huawei phone launched since late 2024 | Huawei Browser ∷ → 添加至桌面 (max 10 shortcuts; no manifest/standalone documented; android:F7). | Server酱 Turbo → WeChat (native WeChat exists on NEXT); 企业微信/飞书 have NEXT builds but wait for the week-2 patch (reminders matrix). | ArkWeb implements Web Speech outside 坚盾守护 mode (inferred; android verify F7) — test on the friend's phone. | same | **No APK natively** (android:F5). Optional experiment only: AppGallery's **卓易通** (Droi, Android-16 container on HarmonyOS 5–7) can install local APKs via its 文件管理 with whitelist restrictions; notifications/background alarms/TTS inside the container are untested (android verify F5 / omission 1) — try with one willing friend, never promise it. |

Honest summary: for iPhone friends the app is a convenience (reminder without Bark, nicer launch); for domestic-Android friends it is a real upgrade (reminder, pronunciation, standalone window); for HarmonyOS NEXT friends it changes nothing.

---

## 4. Code changes (minimal)

All copy goes into `frontend/src/i18n/zh.ts` and is mirrored line-for-line in `docs/FRONTEND.md` §8 (`zh.test.ts:67-80`, `zh.contract.test.ts:61-83`; pwa:F10); no CJK in `.tsx` outside `src/i18n`; the glossary forbids 单词本 (use 生词库). Regression gate for every frontend change: `npm run lint && npm run typecheck && npm test && npm run build`; backend: targeted pytest files.

### 4.1 Before inviting (D1–D3) — web, ≈ 6 h

| # | File | Change | Hours | Why |
|---|---|---|---|---|
| W1 | `frontend/public/manifest.webmanifest` (new), `frontend/public/icons/icon-{192,512}.png`, `icon-maskable-{192,512}.png`, `frontend/public/apple-touch-icon.png`, `frontend/public/icon-maskable.svg` (new) | pwa A1 JSON (`id "/"`, `start_url "/today"`, `scope "/"`, `display standalone`, `theme_color/background_color #ffffff`, icons incl. `purpose: maskable`); PNGs via the five verified `sips` commands (≈ 40 KB total) | 1.0 | Android install criteria need 192 + 512 PNGs; iOS uses `apple-touch-icon` first (pwa:F5, F7; android:F8) |
| W2 | `frontend/index.html:13` (+3 lines) | `<meta name="mobile-web-app-capable">`, `<link rel="manifest">`, `<link rel="apple-touch-icon">`; keep lines 7–14 | 0.1 | pwa A2 |
| W3 | `frontend/src/utils/platform.ts` (new, +tests), `frontend/src/components/layout/InstallHint.tsx` (new, +tests), `AppLayout.tsx` (mount above `<Outlet/>` on `/today` only), `SettingsPage.tsx` (「添加到主屏幕」 row + Sheet), `src/i18n/zh.ts:73` + `docs/FRONTEND.md:274` (`install:` block, pwa A6 copy) | UA channels `standalone / wechat / qq / ios / android / desktop`; WeChat/QQ card non-dismissible; 14-day dismissal via `useLocalPref`; no `beforeinstallprompt` dependency (manual instructions when it never fires; pwa verify omission 6); hidden when `Capacitor.isNativePlatform()` (after A1 below) | 3–4 | pwa:F9, R4 — the mainland-critical piece |
| W4 | `backend/wd/main.py` `_mount_spa` (`:252-260`), `backend/tests/integration/test_health.py:185-203`, `docs/DEPLOY.md` §4 `WD_FRONTEND_DIST` row | `assets/*` that is not a file → `ApiError("not_found")` (never `index.html` 200); `Cache-Control: no-cache` for `manifest.webmanifest`, `index.html` literal path, `sw.js`, `registerSW.js` | 1.0 | pwa A4, F4, verify omission 1 |

### 4.2 Week 2 (D8–D14) — ≈ 2.0–2.25 person-days

| # | File | Change | Hours | Why |
|---|---|---|---|---|
| H1 | `backend/wd/delivery/webhook.py:224-254` (`safe_post`), `:267-303` (`build_payload`), `:342-353` (`send_test_webhook`), `backend/tests/integration/test_delivery.py` | Parse the JSON body for `wecom` (`errcode`), `feishu` (`code`) and `serverchan` (`code` — Turbo success `0`, sc3 `{"error":…,"code":10003}` on bad key) and raise `WebhookError` so retries run and the test button is truthful; store the vendor code in `delivery_error`; `wecom` → `msgtype: markdown` (4,096 B, `[打开 word-Dance](url)`) or truncate the text to 2,048 B (the real digest measures 1,982–2,061 B); put the `url` into the test message; keep the Server酱 title ≤ 32 chars only after a real-key test | 8 | reminders:F3, F7, rec 2; verify omissions 1–2, 4 |
| H2 | `frontend/src/pages/SettingsPage.tsx:597-602`, `src/api/endpoints.ts:391-394` (reuse `exportAccount`), `zh.ts` copy | When `isStandaloneDisplay()`: `fetch` → `File` → `navigator.share({files})` when `canShare`, else copy to clipboard; when `Capacitor.isNativePlatform()`: hide the anchors and show 「请在浏览器中打开本站导出数据」 (v1), `@capacitor/filesystem` + `@capacitor/share` later | 2 | pwa:F8 (WebKit 290847), capacitor:F13, captool:F23 |
| H3 | `frontend/src/i18n/zh.ts:18,39`, `WordDetailPage.tsx:91,137-153,223-228,349` (+FRONTEND.md mirror) | Render the real `deferred_until` / `details.resumes_at` date instead of the fixed 「例句将在明天补齐」 | 1.5 | security:F17 |
| H4 | `backend/wd/ai/runner.py:71-74,229-285` (classifier), `backend/wd/ai/common.py:37` (banner), `backend/wd/ai/probe.py:200`, `backend/wd/diag.py:99`, `deploy/install.sh:143`, `backend/tests/unit/test_runner.py` | New class for "remote managed settings could not be loaded" / `403 Request not allowed` / `ECONNREFUSED|ENOTFOUND` / `hit your .* limit` with a short retry (≤ 5 min) instead of the 30-min `auth` pause; `auth` banner text credential-neutral (no "以 sqin 身份") | 4 | clivps:F11, verify omissions 1–2 |
| H5 | `backend/wd/security.py` (+ `cli.py` registry) | `wd unlock <username>` = `clear_login_failures` (optional; the SQL with `-cmd ".timeout 5000"` works meanwhile) | 1.5 | security:F4, verify F4 |
| H6 | `backend/wd/routers/auth.py:125`, `security.py:72-73` | Do not count successful logins toward `login:ip`; or key by account | 4 | security gap 7 (A8) |
| H7 | `.env` only | `WD_REGISTRATION_MODE="closed"`; `WD_PIXABAY_KEY` if photos miss | 0.2 | security:F14, F10 |

### 4.3 App track (frontend side, behind feature detection; D3–D8) — ≈ 1.75 person-days of the §5 total

| # | File | Change | Hours |
|---|---|---|---|
| A1 | `frontend/package.json` | add exact pins `@capacitor/core@8.6.0`, `@capacitor/app@8.1.2`, `@capacitor/local-notifications@8.3.1`, `@capacitor-community/text-to-speech@8.0.2` (web implementations exist; `Capacitor.getPlatform()==='web'` gates everything off in browsers; capacitor:F5, verify F5). Same majors as `mobile/` (version coupling, captool:F8) | 0.5 |
| A2 | `frontend/src/native/capacitor.ts` (new, +tests) | `isNative()`, `toDeviceWallTime(pushTime, tz)`, `requestReminderPermission()`, `syncDailyReminder(settings)` = cancel id 1 + `schedule({on:{hour,minute}, allowWhileIdle:true, extra:{route:'/today'}})` (exact by default, see §5.4), `installNativeHandlers(navigate)` = Android back button (`canGoBack ? history.back() : App.minimizeApp()`), `localNotificationActionPerformed` → `navigate(extra.route)` (retained until a listener exists: capacitor verify omission 3), `appStateChange` → re-run `syncDailyReminder` on every resume (re-arm fix: captool verify F10 correction 1) | 5 |
| A3 | `frontend/src/auth/AuthContext.tsx:81` | effect: `syncDailyReminder(state.settings)` on `push_enabled/push_time/timezone` change and on mount | 0.5 |
| A4 | `frontend/src/pages/SettingsPage.tsx:275` (`PushSection`) | when native: call `requestReminderPermission()` inside the switch gesture before `save({push_enabled})`; show a 「本机提醒」 status line (granted / denied / inexact warning from `ScheduleResult.warning`) | 1.5 |
| A5 | `frontend/src/hooks/useSpeech.ts:11-45`, `SpeakButton.tsx:24-35` | native branch: `speechSupported()` true when `Capacitor.isPluginAvailable('TextToSpeech')`; `speak()` → `TextToSpeech.speak({text, lang: accent, rate, category:'playback'})`; on Android check `getSupportedLanguages()` for `en` once and offer `openInstall()` with a hint 「请先安装英语语音包」 | 4 |
| A6 | `frontend/src/styles/global.css:150` (`.page`), `frontend/src/pages/LoginPage.css:7` (`.auth`), `StudyPage.css:5`, `ScreenRunPage.css:5` | add `var(--safe-top)` to top padding; re-derive the two `100dvh - var(--safe-top)` rules; zero change in browsers (insets are 0) | 2 (incl. device check) |
| A7 | `frontend/src/i18n/zh.ts` + `docs/FRONTEND.md` §8 | `native:` block (`reminderBody: '今日词汇已准备好，点开复习'`, `reminderStatus…`, `exportInBrowser`, `ttsInstall`) | 0.5 |

### 4.4 Later (not scheduled)
Per-user AI quota + admin "cancel this user's queue" (2–3 pd; security:F7), `ntfy` format (1 pd incl. migration 0010 table rebuild; android verify omission 5), Universal Links / App Links so a relay reminder opens the app (0.5 pd + AASA route; reminders:F11), `vite-plugin-pwa` service worker (4–6 h; pwa R7), admin TOTP, password reset by e-mail, generalising the `sqin` defaults (1–2 pd; moot with user `sqin`), `@capacitor/filesystem`+`share` export (0.5 pd), Capacitor 9 migration (Node 24; captool:F1/F3).

---

## 5. iOS app route and Android app route (Capacitor 8.6 remote shell)

### 5.1 Why this shape, and what it is not
`server.url = https://DOMAIN` makes the WebView's document origin equal the API origin, so the `wd_session` cookie is first-party and persistent (default `WKWebsiteDataStore`, Android `CookieManager`), the CSRF Origin rule passes exactly as in Safari/Chrome, `<img src="/media/…">` loads with the cookie, and a website deploy is the app update — proven live with the curl matrix (capacitor:F1, verify F1 B1; captool:F9). The bridge is injected into the remote page on both platforms (iOS `WKUserScript` at document start; Android `WebViewCompat.addDocumentStartJavaScript` scoped to the `server.url` origin, HTML-proxy fallback only below WebView ≈ 86; capacitor:F4, verify F4; captool verify omission 4). Ionic documents `server.url` as "not intended for use in production" and App Review 4.2 would apply to a storefront submission — irrelevant for TestFlight *internal* testing and APK sideload, which have no reviewer (capacitor:F6, F21; ios:F19–F20, verify omission 3). If a storefront is ever wanted, the bundled-dist design from `docs/PUBLIC_LAUNCH_AND_IOS.md` §4 replaces it; the bridge, icons, projects and CSS fix carry over.

### 5.2 Tooling to install on the Mac (order, sizes, proxy needs)

| Order | Item | Size / time | Proxy? | Check |
|---|---|---|---|---|
| D0 | Xcode 27.2 (Mac App Store; macOS 26.6+ met) | 3.12 GB download, ≈ 9–12 GB installed (ios:F11, captool:F21) | normally no (Apple CDN serves the mainland) | after install: `sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept && xcodebuild -runFirstLaunch && xcodebuild -version` → `Xcode 27.2` |
| D0 | Apple Developer enrolment (¥688/yr) | 1–3 days wait (ios:F3) | the Developer app needs claude-free Apple services only | membership e-mail; App Store Connect opens |
| D1 | JDK 21 + Android command-line tools (no Android Studio; Capacitor's library targets Java 21, capacitor:F16) | `brew install --cask temurin@21 android-commandlinetools` ≈ 0.5–1 GB; `sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"` ≈ 1–2 GB; Gradle 8.14.3 + Maven cache ≈ 1 GB (captool table) | **yes** for `dl.google.com` / Maven: `export HTTPS_PROXY=http://127.0.0.1:8118` for brew/sdkmanager (`sdkmanager --proxy=http --proxy_host=127.0.0.1 --proxy_port=8118 …`) and `~/.gradle/gradle.properties` with `systemProp.https.proxyHost=127.0.0.1` / `systemProp.https.proxyPort=8118` (or Aliyun mirrors `https://maven.aliyun.com/repository/google` and `/public` in `android/build.gradle`) | `java -version` → 21; `sdkmanager --list_installed` shows platform 36 + build-tools 36.0.0; `export JAVA_HOME=$(/usr/libexec/java_home -v 21) ANDROID_HOME=/opt/homebrew/share/android-commandlinetools` in `~/.zprofile` |
| — | Node | keep 22.23.4 (Capacitor 8 needs ≥ 22; 9 needs 24) | — | `node -v` |
| — | CocoaPods | **not needed** (SPM default; trunk read-only from 2026-12-02 anyway; captool:F4) | — | — |
| — | iOS simulator runtime | skip (≈ 7.9 GB); test on your iPhone (iOS 17+ for Xcode 27.2 debugging, ios:F11) | — | — |
| D1 | One domestic Android phone (yours or a friend's) with developer options + USB debugging | — | — | `adb devices` |

Disk: ≈ 15 GB downloads without the simulator, ≈ 15–20 GB installed; 830 GiB free.

### 5.3 Project skeleton and config (`mobile/` in the repo; D3, ≈ 0.5 pd)
```bash
mkdir -p /Users/sqin/word-dance/mobile && cd /Users/sqin/word-dance/mobile && npm init -y
npm i -E @capacitor/core@8.6.0 @capacitor/cli@8.6.0 @capacitor/ios@8.6.0 @capacitor/android@8.6.0 \
         @capacitor/app@8.1.2 @capacitor/local-notifications@8.3.1 @capacitor-community/text-to-speech@8.0.2
npm i -D -E @capacitor/assets@4.0.0
npx cap init word-Dance APP_ID --web-dir web
mkdir -p web assets && cp ../frontend/public/favicon.svg assets/logo.svg
```
Pin: **8.6.0 exactly, never below 8.5.1** — GHSA-rvm3-566m-v7fv / CVE-2026-103922 (CVSS 9.3) let a frame navigation to `/_capacitor_http_interceptor_` load remote content at the app origin; fixed in 8.4.3/8.5.1, present in 8.6.0 (captool verify omission 1). Stay on 8.x until Node 24 is installed (Capacitor 9 GA targeted end-Nov 2026; captool:F1/F3).

`web/index.html` = the offline page (zh: 「无法连接 word-Dance，请检查网络后重试」 + a button `location.href='https://DOMAIN/'`); it is **required** even for a remote shell — iOS aborts at launch without `webDir/index.html` (captool verify omission 5) — and doubles as `server.errorPath` (capacitor:F8).

`mobile/capacitor.config.ts`:
```ts
import type { CapacitorConfig } from '@capacitor/cli';
const SITE = 'https://DOMAIN';                 // canonical, non-redirecting origin == WD_PUBLIC_URL (origin pinning: the Android bridge is origin-exact)
const config: CapacitorConfig = {
  appId: 'APP_ID', appName: 'word-Dance', webDir: 'web',
  backgroundColor: '#ffffff', appendUserAgent: 'word-Dance-App/1', loggingBehavior: 'production',
  server: { url: SITE, cleartext: false, errorPath: 'index.html' },          // allowNavigation stays []: attribution links open the system browser (capacitor:F7)
  ios: { contentInset: 'never', limitsNavigationsToAppBoundDomains: false, allowsLinkPreview: false },   // true would need WKAppBoundDomains (capacitor:F6)
  android: { allowMixedContent: false, webContentsDebuggingEnabled: false, minWebViewVersion: 108 },     // dvh/color-mix/<dialog> floor (capacitor:F13)
  plugins: {
    SystemBars: { insetsHandling: 'native', initialViewportFitValueHint: 'cover' },   // see note
    LocalNotifications: { smallIcon: 'ic_stat_worddance', iconColor: '#3b5bdb', presentationOptions: ['banner', 'sound', 'list'] },
  },
};
export default config;
```
Note on `SystemBars` **[deviation: capacitor digest used `insetsHandling: 'css'`]**: the Capacitor docs mark `native` as recommended and Capacitor 9 makes it the default; on WebView < 140 it pads the WebView natively and zeroes `env()`, on ≥ 140 it honours `viewport-fit=cover` so the site's existing `env()` CSS applies (captool verify F14); `initialViewportFitValueHint: 'cover'` avoids the first-paint jump (capacitor verify omission 4). Edge-to-edge itself is enforced for targetSdk 36 (captool:F14), hence CSS A6.

Origin pinning checklist: Caddy serves exactly one host block for `DOMAIN` (no `www`, no apex→sub redirect); `WD_PUBLIC_URL="https://DOMAIN"`; the QA step asserts `window.Capacitor.isNativePlatform() === true` on Android — a redirect to another host silently yields a page without the bridge and even opens the system browser (capacitor verify omission 1; captool verify omission 6).

Then:
```bash
npx cap add ios && npx cap add android && npx cap sync
npx @capacitor/assets generate --iconBackgroundColor '#3b5bdb' --iconBackgroundColorDark '#3b5bdb' --splashBackgroundColor '#ffffff' --splashBackgroundColorDark '#121620'
# hand-draw android/app/src/main/res/drawable/ic_stat_worddance.xml (white "W" silhouette from favicon.svg's path) for the notification small icon (capacitor:F17)
```
Android manifest additions (`android/app/src/main/AndroidManifest.xml`): `<uses-permission android:name="android.permission.USE_EXACT_ALARM" />` (§5.4). `.gitignore`: `mobile/ios/App/App.xcodeproj/xcuserdata`, `mobile/android/.gradle`, `mobile/android/app/build`, `mobile/android/keystore.properties`, `*.jks`. `install.sh` builds only `frontend/`, so `mobile/` is inert on the server.

### 5.4 Local notifications — the daily reminder
- Data: `settings.push_time` (HH:MM), `settings.timezone`, `settings.push_enabled` (default 1) from `GET /api/settings` (capacitor:F14). Body fixed at schedule time (the day's words are not known yet): 「今日词汇已准备好，点开复习」; tap → `/today`.
- **iOS**: one `UNCalendarNotificationTrigger(dateMatching: {hour, minute}, repeats: true)` in device wall time (plugin `LocalNotificationsPlugin.swift:553-598`), one of ≤ 64 pending requests, fires after app kills and reboots; permission prompt from the 每日推送 switch gesture (`requestPermissions()`), foreground presentation via `presentationOptions` (capacitor:F14; captool:F10, F12).
- **Android — exact vs inexact decision (default: exact, no Settings detour)**: the plugin's `on` schedule is exact only if `canScheduleExactAlarms()`; `SCHEDULE_EXACT_ALARM` is denied by default on Android 14+ for new installs, and with the default `isExactNotification: true` `schedule()` **opens the "Alarms & reminders" Settings screen itself** (captool verify F10 correction 2). Because the APK is sideloaded (no Play policy), declare `USE_EXACT_ALARM` in the shell manifest — granted automatically, not revocable, so `canScheduleExactAlarms()` is true on 13+ and the first schedule uses `setExactAndAllowWhileIdle` (captool:F11) **[deviation: capacitor digest proposed asking the user to flip the toggle]**. Android 12 pre-grants `SCHEDULE_EXACT_ALARM`. Fallback remains inexact (≤ 1 h late) and is reported in `ScheduleResult.warning`.
- **Re-arm on launch (mandatory)**: after the first fire the plugin re-arms with plain `setExact(RTC)` / `set(RTC)` — no wake-up, no allow-while-idle — so from day 2 a dozing phone delays the reminder to its next maintenance window (captool verify F10 correction 1). Fix: `syncDailyReminder()` (cancel + schedule) on every launch and `appStateChange → isActive` (A2), which restores the exact-while-idle path daily for anyone who opens the app; plus `POST_NOTIFICATIONS` requested from the switch gesture (Android 13+ notifications are off by default; captool:F11).
- OEM killers: Xiaomi 自启动 + 省电策略「无限制」, Huawei/Honor 应用启动管理 手动管理, OPPO/vivo 后台运行 allowed — one line each in the APK install note (captool:F13; android:F15). Server-side relays (Bark/Server酱) stay configured as the backup channel; both fire if both are on — tell friends to pick one.

### 5.5 TTS, back button, export, dark mode
- **TTS**: Android System WebView ships with `disable-speech-synthesis-api` → `window.speechSynthesis` undefined → the SPA shows the disabled 发音 button (capacitor:F12, verify F12). The Android app therefore **must** include `@capacitor-community/text-to-speech` (A5) to be at least as good as a browser; on domestic ROMs the system engine may lack an English voice → `getSupportedLanguages()` check + `openInstall()` hint. iOS: WKWebView keeps Web Speech synthesis and — inferred from WebKit source — allows the auto-pronounce effect without a first tap (capacitor verify F12); routing iOS through the same plugin with `category: 'playback'` gives one code path and speech despite the silent switch **[deviation: capacitor digest left iOS on Web Speech]** — see D11.
- **Back button**: `@capacitor/app` listener (A2); without it the root back press is swallowed (capacitor:F15); compatible with Android 16 predictive back.
- **Export**: `<a download>` does nothing in either WebView (no `DownloadListener`/`WKDownloadDelegate`; capacitor:F13) → H2 hides it natively with the browser hint; `<input type=file>` import works.
- **Dark mode / status bar**: nothing to do — iOS `.default` status-bar style follows the system scheme; the Android template theme is `DayNight` and `prefers-color-scheme` follows it (capacitor:F10, verify omission 6).

### 5.6 Distribution

**iOS — TestFlight Internal Only, friends as App Store Connect users** (ios:F4, F22; verify F4, omissions 1–4):
1. App Store Connect → Users and Access → + : friend's name + the e-mail of **their Apple Account** (the invitation binds to that account; redemption code otherwise), role **Marketing**, Apps: word-Dance only; they must accept within 3 days; an individual account may add 50 users. Their name/e-mail is visible to you; your legal name is visible to them as the developer (ios:F2).
2. Apps → New App: iOS, name word-Dance, primary language 简体中文, bundle id `APP_ID`, SKU. **Leave Pricing & Availability at all 175 territories incl. China mainland and never set "Removed from Sale"** — mainland installs are reported to fail otherwise (ios verify F7 correction); nothing ties an ICP number to TestFlight (ios:F8) — confirm on day 1 that the ICP field does not block saving.
3. Xcode (`npx cap open ios`): Signing & Capabilities → your Team, automatic signing; General → Deployment target **17.0** (16.0 if the poll found an iOS 16 phone; TestFlight itself needs 16+, ios:F6, F21), Display name word-Dance, Version 1.0.0, Build 1 (bump every upload); Info → `ITSAppUsesNonExemptEncryption` = `NO` (otherwise every build stalls at "Missing Compliance"; ios verify omission 1). Product → Archive → Distribute App → **TestFlight Internal Only** → Upload (or `xcodebuild -project ios/App/App.xcodeproj -scheme App -configuration Release -destination 'generic/platform=iOS' -archivePath build/App.xcarchive archive` + `xcodebuild -exportArchive … -exportOptionsPlist` with `method app-store-connect`, `destination upload` and — if `xcodebuild -help` lists it for your Xcode — `testFlightInternalTestingOnly true`; otherwise tick "TestFlight Internal Only" in the Organizer; captool:F21).
4. TestFlight tab → Internal Testing → group 「朋友」 → add the testers → the build appears 5–30 min after processing, no Beta App Review ("Ready to Submit — can be distributed to internal testers"; ios verify F4). **Never add the build to an external group even to try**: a Beta App Review rejection kills the build for everyone (ios verify omission 3).
5. Friend: install **TestFlight** from the CN App Store (iOS 16+), open the invitation e-mail / redeem code with the invited Apple Account, install word-Dance, log in once (own cookie jar; capacitor:F9).
6. Routine: calendar entry to **re-upload every ≤ 80 days** (bump Build, archive, upload ≈ 30 min; an expired build no longer opens, ios:F6); re-archive with the current Xcode before each April (iOS 27 SDK rule from April 2027; ios:F12); keep the Apple Developer app installed for renewal/identity re-verification (ios verify omission 6). Fallback for a friend who refuses an ASC account: Ad Hoc (UDID, `.ipa` + manifest over the same Caddy, yearly renewal; ios:F9).

**Android — signed APK on the same Caddy** (capacitor:F19; captool:F22; android:F15):
```bash
keytool -genkeypair -v -keystore ~/secure/word-dance-release.jks -alias worddance -keyalg RSA -keysize 2048 -validity 10000   # back up the .jks + passwords: losing it = everyone reinstalls
cat > mobile/android/keystore.properties <<'EOF'
storeFile=/Users/sqin/secure/word-dance-release.jks
storePassword=<...>
keyAlias=worddance
keyPassword=<...>
EOF
# android/app/build.gradle: read keystore.properties, add signingConfigs.release { storeFile file(...) ... } and buildTypes.release { signingConfig signingConfigs.release }
# versionCode = 202611101 (YYYYMMDDn, strictly increasing), versionName "1.0.0"
cd mobile/android && ./gradlew assembleRelease && apksigner verify --print-certs app/build/outputs/apk/release/app-release.apk
scp app/build/outputs/apk/release/app-release.apk sqin@VPS_IP:/srv/word-dance-dl/word-dance-1.0.0.apk
```
On the VPS, once (install.sh's `--with-caddy` would rewrite the file — pass that flag never again; deploy:F4):
```bash
sudo install -d -m 0755 -o sqin -g sqin /srv/word-dance-dl
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
DOMAIN {
    encode zstd gzip
    request_body { max_size 2MB }
    handle_path /dl/* {
        root * /srv/word-dance-dl
        header /*.apk Content-Type application/vnd.android.package-archive
        file_server
    }
    handle {
        reverse_proxy 127.0.0.1:8000
    }
}
EOF
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
curl -sI https://DOMAIN/dl/word-dance-1.0.0.apk | head -3     # 200, correct Content-Type
```
Friends download `https://DOMAIN/dl/word-dance-1.0.0.apk` in their browser, allow the browser/file manager as an install source, dismiss the 风险/纯净模式 prompt once (Xiaomi: 授权单次安装 or 关闭纯净模式; vivo: 设置 → 安全与隐私 → 更多安全设置 → 应用安装; OPPO ColorOS 12+: 设置 → 密码与安全 → 系统安全 → 外部来源应用; Huawei/Honor: 设置 → 系统和更新 → 纯净模式 → 退出; android:F15). Updates: a new APK only when the shell changes (plugins/Capacitor); website changes need nothing; keep `APP_ID` and the signing key stable, `versionCode` monotonic. 2027: register the free limited-distribution account and enrol the GMS-phone friends' devices (≤ 50, QR handshake on the phone; android verify F3) — GMS-less and Huawei phones are outside the verifier regime (android verify F4). HarmonyOS NEXT: web only; 卓易通 is an experiment (§3).

### 5.7 Estimates and the trigger

| Step | Person-days | Calendar |
|---|---|---|
| Toolchain (Xcode, JDK, SDK, proxies) | 0.5 (2–6 h wall) | D0–D2 |
| Skeleton + config + icons/splash + keystore | 0.5 | D3 |
| Web-side bridge A1–A4, A7 (+ tests) | 1.0 | D3–D5 |
| TTS branch A5 | 0.5 | D5 |
| CSS safe-top A6 (+ device check) | 0.5 | D5 |
| First device runs + QA matrix (your iPhone: cookie persistence across kill/relaunch, reminder at push time, silent switch, links open Safari, airplane mode → error page → retry, keyboard on login/bank-add, dark mode; one domestic Android: `window.Capacitor.isNativePlatform()`, POST_NOTIFICATIONS prompt, exact alarm granted, reminder after reboot, autostart/battery, edge-to-edge top bar, back gesture, TTS English voice; capacitor rec 4) | 1.0 | D6–D8 |
| iOS release (ASC app, archive, upload, group, testers) | 0.5 + waits | D9–D10 |
| Android release (signing, gradle, Caddy `/dl`, zh install note) | 0.5 | D9–D10 |
| Buffer, docs (`docs/ops.md`: 80-day routine, versionCode, keystore backup, Capacitor 9 note) | 0.5 | D11–D14 |
| **Total** | **≈ 6.0 (5–7.5)** | first friends on TestFlight/APK D10–D14 |

Trigger that justifies starting: the owner's explicit decision (apps on purpose) plus two technical facts — the web deployment is unaffected (all app work is on the Mac/Apple/Google), and the shell needs no backend change, so nothing built now is wasted. The reminders slice recommended observing a month before building (reminders rec 3–4) **[deviation]** — overridden by the owner's direction; the only cost of starting now is the ¥688 and ≈ 6 person-days. Start the enrolment and downloads on D0 regardless; start writing code only after the first friends are live (D3), so the web launch is never delayed. If Xcode cannot be downloaded in reasonable time, the Expo/EAS cloud-build route (15 iOS builds/month free; captool:F20) is the fallback — not planned.

---

## 6. zh-CN onboarding message for friends

> 你好！邀请你试用我自己做的背单词小应用 **word-Dance**（每天几个词，稳稳记住）。只给几位朋友用，不公开。
>
> **1. 注册与登录**
> - 网址：https://DOMAIN
> - 请在 **Safari / 系统浏览器** 中打开（微信里点右上角「···」→「在浏览器打开」），不要在微信内注册。
> - 注册时填写邀请码：**XXXX-XXXX-XXXX-XXXX**（只能用一次，7 天内有效；请复制粘贴，输错 5 次会被限制 1 小时）。
> - 注册后按提示选目标阶段（中考/高考/四级/六级）和每日推送时间。
>
> **2. 添加到桌面（像 App 一样打开）**
> - iPhone：Safari 里先登录，再点底部「分享」→「添加到主屏幕」。
> - 安卓（小米/OPPO/vivo/荣耀）：浏览器菜单 →「添加到桌面」。
> - 华为：华为浏览器 ∷ →「添加至桌面」。
> - 以后从桌面图标进入即可，一般 30 天内不用重复登录。
>
> **3. 每日提醒（二选一，在「我的 → 推送设置」里填）**
> - iPhone：安装 App Store 里的 **Bark**（免费），复制它给你的地址（https://api.day.app/xxxx），粘贴到「Webhook 地址」，格式选 **Bark**，打开「Webhook 推送」，点「发送测试」。
> - 用微信收提醒：打开 sct.ftqq.com 微信扫码登录，复制 SendKey，把 `https://sctapi.ftqq.com/你的SendKey.send` 粘贴到「Webhook 地址」，格式选 **Server酱**，点「发送测试」。
> - 收到测试消息请告诉我一声；第二天推送时间前后会收到当天词汇。
>
> **4. 几件要知道的事**
> - 密码连错 10 次会锁 15 分钟；忘记密码直接找我重置。
> - 单词的例句和配图由 AI 服务生成，可能偶尔有错或延迟，可以点「举报」；「换一张」和「举报」会影响所有人看到的那张图。
> - 你添加的单词和备注会发给 AI 服务处理；「我的 → 账号」里随时可以导出或删除自己的数据。
> - 每天的 AI 额度有限，偶尔会显示「例句将稍后补齐」，第二天自动补上。
> - 华为鸿蒙 NEXT 的手机只能用网页版（上面第 2 步），其它都一样。
>
> **5. 两周后**会有 iPhone（TestFlight 内测）和安卓（安装包）版本，带本机提醒和发音；到时我会把 TestFlight 邀请邮件 / 安装包链接发给你（iPhone 的朋友请告诉我你 Apple 账号的邮箱）。
>
> 有任何问题随时找我。

Per-friend variants: replace the code; for a known HarmonyOS NEXT phone drop §5's Android line; for a friend who already uses 企业微信/飞书, add those channels only after week 2.

---

## 7. Decisions only the owner can make (recommended default in bold)

| # | Decision | Default and why |
|---|---|---|
| D1 | Domain + registrar + DNS | **Porkbun `.com` ($11.81/yr, Alipay) with Cloudflare DNS-only (TTL 60–300 s)**; alternative Alibaba `.com` ¥85 + Alibaba DNS (实名 1–2 days, TTL ≥ 600 s). `APP_ID` = reverse of it; cannot change later. |
| D2 | Region | **Tokyo**, Singapore if D0 curl shows 403 or D1 evening loss > 5 % (hosting table; identical price). |
| D3 | Credential path for `claude -p` (A stored login / B setup-token / C API key / D gateway / E apiKeyHelper) | Your call; wiring is config-only (§2.2). Technical facts to weigh: fail-closed managed-settings fetch recorded on the Mac's login; expiry/re-login needs the same Unix user + `HOME`; `--bare` future default ignores OAuth; 403 regions block login and refresh hosts too. |
| D4 | Carry the Mac DB over as-is (incl. the 48 contents / 31 images) or regenerate those | **Copy as-is** (closes the admin-bootstrap race, keeps your bank); regenerating the 48 words later costs < $1 via 管理 → 重新生成 if you decide so (origin question deferred by you). |
| D5 | Friends' stages → prewarm scope | **Top 1,000 words of each polled stage** (≈ $6 each); whole stage(s) if budget allows (zk ≈ $12, all ≈ $54). |
| D6 | AI caps / acceptable monthly spend | **daily 6 / monthly 100 / SVG 1.0 / hourly 60** (hard ceiling ≈ $180, realistic $25–60). |
| D7 | Invite shape | **One single-use 7-day code per friend**; `closed` mode after everyone is in. |
| D8 | Default reminder channel per friend | **Bark for iPhone, Server酱 Turbo (WeChat) for everyone else**; Server酱³ for Android friends who want a system notification; 企业微信/飞书 after H1. |
| D9 | App track timing | **Enrol + downloads on D0, code from D3, release D9–D14**; do nothing on the VPS for it. |
| D10 | TestFlight tester model | **Internal group, friends as Marketing-role ASC users** (your legal name visible to them, their e-mails visible to you); Ad Hoc only for refusers; never external. |
| D11 | Android exact alarms via `USE_EXACT_ALARM`; TTS plugin also on iOS | **Yes / yes** (no Settings detour; one speech code path; iOS then speaks despite the silent switch — say no if you prefer Web Speech behaviour). |
| D12 | iOS deployment target | **17.0**, 16.0 if the poll finds an iOS 16 phone. |
| D13 | ECDICT on the VPS | **Yes** (`--with-ecdict`, +1 GB; custom real words publish instantly). |
| D14 | Keep the Mac service stopped | **Yes** (data stays as rollback for a week; two live instances would diverge and double AI jobs). |
| D15 | Any minor among the friends | If yes, add a parental-consent sentence to §6 (no age gate exists; security open q). |

---

## 8. Risks and mitigations (top 8)

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| 1 | The VPS region cannot reach `api.anthropic.com`/`platform.claude.com` (403) or the chosen credential fails headlessly | medium / AI off, site still works | D0 curl gate before any install; Singapore rebuild; HTTP CONNECT (not SOCKS) proxy in the wrapper only; `WD_AI_ENABLED="0"` keeps the circle usable on dictionary data (deploy:F2); `wd claude-check` as the only acceptance test (clivps:F10) |
| 2 | Mainland reachability: evening loss, GFW IP event | medium / outage hours–day | measure at 21:00 before inviting; Lighthouse IP swap (once per instance) + 60 s DNS; snapshot-rebuild runbook; never proxy through Cloudflare (hosting:F17, F20, verify omission 1) |
| 3 | AI pauses with a misleading banner (managed-settings fetch, login expiry, usage limits, 403) | high on some credential paths / friends see 「例句生成中」 for hours | H4 classifier + neutral banner in week 2; watch `claude_auth` events daily; the relay reminders and batches work without AI |
| 4 | Reminder "false success" (WeCom/Feishu/Server酱³ answer HTTP 200 on error) → silent non-delivery | high if offered / friend never gets the digest | offer only Bark/Server酱 Turbo until H1; confirm receipt by phone; `GET /api/admin/jobs?type=send_webhook` |
| 5 | Registration/login throttles and lockouts on launch night (5/h/IP incl. failed codes; 20 logins/10 min; 10 failures → 15-min lock) | medium / angry friend | stagger invites, paste codes, one device each; unlock SQL with `.timeout 5000`; admin password reset |
| 6 | Monthly AI cap trips → every card says 「明天」 for weeks; or one friend's bulk mark floods the queue | medium / confusing | caps 6/100 (+10 % headroom); H3 date copy; daily 概览; corrected cancel recipe; 24-h pause |
| 7 | App track specifics: Ionic calls `server.url` unsupported; site↔shell plugin coupling; Android bridge origin-exact; TestFlight territory/outage coupling; 90-day expiry; keystore loss | medium / app-only failures, web unaffected | exact 8.6.0 pin; feature-detect plugins; canonical origin + QA assertion; availability left at all territories, "Internal Only" builds, web app as fallback; 80-day calendar; keystore + passwords backed up twice |
| 8 | Toolchain downloads stall on the proxy-dependent network; Gradle cannot reach dl.google.com | medium / app track slips, web unaffected | Xcode via the App Store CDN; Aliyun Maven mirrors or `gradle.properties` proxy; Android Studio from the China mirror if the CLI tools fail; EAS cloud builds as the iOS fallback (captool:F20) |

Also standing: the admin password is the single key (no 2FA) — long, unique, admin login only from your devices (security:F13); backups are only as good as the Mac pull — check weekly.

---

## 9. Costs

| Item | One-time | Monthly | Notes |
|---|---|---|---|
| Tencent Lighthouse Tokyo 2c4g/60 GB/1.5 TB | — | ≈ ¥42 (≈ $6.3; intl list $6.00) | first-year promos ¥199/yr seen (hosting:F4, verify omission 6); Singapore same price |
| Domain | ¥79 ($11.81 Porkbun `.com`) or ¥85 Alibaba | ≈ ¥7/mo amortised | `.top` $1.63 first year / $4.63 renewal if you want cheaper |
| Cloudflare DNS-only zone | ¥0 | ¥0 | |
| Apple Developer Program | ¥688/yr ($99) | ≈ ¥57/mo amortised | auto-renewing subscription on the Apple Account (ios verify omission 6) |
| Android keystore, limited-distribution account (2027), Capacitor, plugins | ¥0 | ¥0 | |
| Toolchain downloads | ¥0 (≈ 15 GB) | — | time, not money |
| Bark, Server酱 Turbo | ¥0 | ¥0 | Server酱 ¥39/yr per friend only if > 5 messages/day; Server酱³ free during its test period |
| Pixabay/Pexels keys | ¥0 | ¥0 | if photo providers miss |
| AI usage (whatever the chosen credential bills) | prewarm $6–12 per stage top 1,000–2,000 words; whole seed ≈ $54 | realistic $25–60 (≈ ¥170–400), hard cap $100 (≈ ¥670) with D6 caps | security:F8–F9, verify omission 5; $0.0059/word measured |
| **Year 1 total excluding AI** | ≈ ¥770 (domain + Apple) | ≈ ¥500 (VPS) | ≈ ¥1,300 ≈ $190 |
| **Year 1 AI at API list prices** | ≈ ¥60–400 prewarm | ≈ ¥170–400 | ≈ ¥2,100–5,200 ≈ $310–780 if billed per token; different if the chosen credential is a flat plan |

---

## 10. Explicitly skipped items and why

- **Cloudflare Tunnel / keeping the Mac as the server**: no mainland PoPs on the free plan, 40 KB/s-class reports, block waves; the Mac sleeps after one idle minute and its AI depends on a hand-started tunnel (hosting:F17; deploy:F9, verify omission 5). Not even as a demo bridge — the VPS is live on D1.
- **Hong Kong VPS**: 403 from api.anthropic.com (hosting:F2). **Tailscale**: not in the CN App Store (hosting:F18). **frp / ssh -R**: pointless once a VPS exists (deploy:F10).
- **App Store listing, external TestFlight, domestic Android stores**: 4.2 exposure for a remote shell, Beta App Review kills a rejected build, stores need APP备案 + mainland hosting, Xiaomi closed to individuals, OPPO invite-only pilot (ios:F19–F20, verify omission 3; android verify F14).
- **Web Push**: 6–10 person-days, iPhone-only reach in practice, dead on GMS-less Android (reminders:F13; android:F11). **APNs/FCM native**: 5–8 backend days, FCM useless on mainland phones (reminders:F14).
- **Service worker (`vite-plugin-pwa`)**: buys only the Android Chrome prompt and an instant shell at +338 packages; iOS gains nothing; it also interacts with the Android injection path (pwa:F6–F7; captool:F5).
- **Bundled-dist or bearer-token Capacitor modes**: 7–11 person-days with backend changes; only needed for a storefront (capacitor:F2–F3, F22).
- **Native HarmonyOS app**: new ArkTS codebase, DevEco Studio, same 备案 problem (android rec 8).
- **`ntfy` first-class format**: 1 person-day incl. a `user_settings` table rebuild; the template-URL trick works today for anyone who wants ntfy (reminders:F9; android verify omission 5).
- **企业微信/飞书 bots before H1**: 2,048-byte WeCom cap and HTTP-200 errors would silently drop digests (reminders:F3, F7).
- **E-mail channel / SMTP**: deliverability work for a mainland audience; only if a friend has no WeChat and no iPhone (reminders:F10).
- **Generalising the `sqin` defaults, `forwarded_allow_ips` setting**: moot with the service user named `sqin` and same-host Caddy (deploy:F3, F6).
- **Per-user AI quota, admin TOTP, password reset by e-mail, ToS pages, word-curation tooling**: later tiers for a trusted circle (security gap table).
- **Capacitor 9 now**: needs Node 24 and is pre-GA; one migration later (captool:F1, F3). **Android Studio, iOS simulator runtime, CocoaPods**: not needed for building and testing on real phones (captool table, F4).
- **Ad Hoc iOS distribution**: strictly worse than internal TestFlight; kept only as the per-friend exception (ios:F9).

### 10.1 Deviations from fact-base recommendations (summary)
1. Domain/DNS: Porkbun + Cloudflare DNS-only instead of the hosting default Alibaba `.com` + domestic DNS — speed (no 实名 review) and a 60 s TTL for the re-IP runbook; both options are within the hosting slice's table.
2. Claude CLI: native installer pinned to `stable` + wrapper `DISABLE_AUTOUPDATER=1` (clivps rec 2–3) instead of the deploy slice's apt channel — keeps the repo's default `WD_CLAUDE_BIN` path with user `sqin`.
3. ECDICT enabled (deploy slice left it open) — disk is plentiful, real custom words publish without an AI lookup.
4. Invites: per-friend single-use 7-day codes (security:F14) rather than the deploy slice's one 10-use code.
5. `plugins.SystemBars.insetsHandling: 'native'` + `initialViewportFitValueHint: 'cover'` instead of the capacitor digest's `'css'` default (captool verify F14, capacitor verify omission 4).
6. Android exact alarms through `USE_EXACT_ALARM` in the shell manifest plus re-arm on launch (captool:F11, verify F10) instead of asking the user to flip "Alarms & reminders".
7. TTS plugin on iOS as well as Android (capacitor digest kept iOS on Web Speech) — one code path, silent-switch bypass; owner may revert (D11).
8. Start the app track now in parallel (owner direction) although the reminders slice advised a month of observation first; the ios slice's older "bundled Vite build + CapacitorHttp + signed media" route is superseded by the capacitor/captool M1 remote shell.
