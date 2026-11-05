# Design D2 — "solid small-circle service in about one week"

word-Dance @ main 9ab13a5 · written 2026-11-04 (Day 0 = tonight, Wednesday) · audience ≤ 10 invited friends on mainland-China phones · owner: solo part-time developer on a Mac (no Xcode, no JDK/Android SDK, api.anthropic.com only through a hand-started SOCKS tunnel).

Conventions. `words.example.com` stands for the domain you register on Day 0; `VPS_IP` for the Lighthouse public IPv4; the VPS service user is literally `sqin` (so the repo's baked-in `/home/sqin` defaults need no edits — deploy:F3). Citations: `(slice:Fn)` = fact digest finding, `(slice-verify:…)` = the adversarial verification report (corrections there override the digest). Policy/model-licensing/credential questions are deferred by owner decision; where a credential matters below, only the technical wiring is given and every path (stored login, setup-token, API key, bearer gateway, apiKeyHelper) is covered by the same mechanism (clivps:F9).

---

## 0. One-paragraph pitch

**Day 1 (Thu 11-05, ~3 h):** word-Dance runs 24×7 on a ¥42/month Tencent Lighthouse box in Tokyo behind Caddy TLS at `https://words.example.com`, with your Mac database (1 admin, 52 user_words, 48 contents, 31 images) copied in before the first `install.sh` run, invite-only registration, HSTS and Secure cookies verified by curl, nightly on-box backups, and AI switched off until the credential of your choice passes `wd claude-check` the next evening. The Mac leaves the serving path for good. **Day 3 (Sat 11-07):** the site installs to the home screen on iPhone and Android with a real icon and name (manifest + PNG icons), shows WeChat users the one-step 「在浏览器打开」 handoff, has the AI caps raised to 6 USD/day and 100 USD/month, the top words of your friends' stages pre-generated, a watch cron that pings your own phone when the service, the AI credential or a webhook misbehaves, and off-box backups pulled to the Mac; the first two or three friends register that evening with single-use invite codes and get their daily 今日词汇 reminder through Bark (iPhone) or Server酱 → WeChat (everything else). **Day 14 (Wed 11-18):** all friends are in, registration is `closed`, the webhook false-success bug and the WeCom 2048-byte cap are patched so 企业微信/飞书/Server酱³ can be offered too, deferral copy shows the real date instead of 「明天」, a restore drill and an external uptime monitor are in place, and you have two weeks of 概览 numbers (spend, queue, provider quotas, events) to decide whether phase 2 — a Capacitor remote-shell app via TestFlight-internal and a sideloaded APK, ≈ 6 person-days — is worth starting.

---

## 1. Goals and explicit non-goals

**Goals (binding for this plan)**
1. First friends on the public URL by Day 3, the whole circle by Day 4–7; nothing that surprises them in month 1 (reminders arrive, the icon exists, logins stick for 30 days, AI content does not silently stop, nobody is locked out without knowing why).
2. One server, no laptop in the path, in a country on Anthropic's supported list (Japan/Singapore; never Hong Kong, which answers 403 — hosting:F1/F2).
3. Data continuity from the Mac (same schema version 9, same seed hash → copy, no migration — deploy:F11).
4. The cheap, verified patches land inside week 1: manifest + icons + install hint + WeChat handoff (pwa:F2/F7/F9), `index.html`/`manifest`/`sw.js` cache headers and 404 for dead asset paths (pwa:F4, pwa-verify omissions 1–2), webhook body check + WeCom cap (reminders:F3/F7, reminders-verify omission 1), AI caps (security:F8), deferred-until copy (security:F17), off-box backups (deploy:F14), uptime/claude-auth watch (security gap 12, clivps-verify omission 1).
5. Mobile = home-screen web app + the reminder channels that already exist; the Capacitor remote-shell apps are phase 2 with exact prerequisites and a trigger, not a week-1 deliverable.

**Non-goals (deliberately out of scope)**
- Public launch items: ToS/privacy pages, admin TOTP, per-user AI quotas, password reset by e-mail, image vote thresholds, word-curation tooling, ICP/公安 filings, domestic store listings, App Store submission (docs/PUBLIC_LAUNCH_AND_IOS.md is not binding for a 10-friend circle).
- Any analysis of Anthropic policy, model licensing, or domestic-model replacement (owner direction). Technical facts only are noted where they change the runbook.
- Web Push, APNs/FCM, a service worker, a native `ntfy` format, Tailscale/Cloudflare Tunnel/frp (see §10).

---

## 2. Phases as day-by-day tasks

Time budget: Day 0 1 h · Day 1 3 h · Day 2 3 h · Day 3 6 h · Day 4 3 h · Day 5 3 h · Day 6 3 h · Day 7 2 h → ≈ 24 h ≈ 3 person-days for the first week; week 2 adds ≈ 1 person-day of optional patches (§4). Calendar: Day 0 = Wed 2026-11-04, Day 1 = Thu 11-05, Day 3 = Sat 11-07, Day 7 = Wed 11-11, Day 14 = Wed 11-18.

| Day | Theme | Hours | Done when |
|---|---|---|---|
| 0 (Wed eve) | Decide §7 defaults, buy domain + VPS, reachability test | 1 | `curl` from the VPS gives 401 (not 403) for api.anthropic.com and platform.claude.com |
| 1 (Thu eve) | Box prep, Mac data copy, `install.sh --with-caddy --with-ecdict`, DNS/TLS, `.env` caps | 3 | Phone opens `https://words.example.com`, you log in as `sqin`, 管理 loads, HSTS + `Secure` seen |
| 2 (Fri eve) | Credential wiring + `wd claude-check`, photo-provider check, backups off-box, console snapshot, start PWA patch | 3 | `claude check OK`, `WD_AI_ENABLED="1"`, Mac pulls `backups/`, manifest + icons committed |
| 3 (Sat) | Install hint + WeChat handoff, deploy, device checks, Bark/Server酱 dry runs, prewarm, invites to 2–3 friends | 6 | Two friends registered, installed to home screen, test reminder received |
| 4 (Sun) | Restore caps, watch cron, invite the rest (staggered), first 概览 review | 3 | All friends who answered have accounts; watch cron delivered one test ping |
| 5–6 (Mon–Tue eve) | Webhook hardening patch + tests + deploy; offer 企业微信/飞书/Server酱³ | 6 | Bogus WeCom key → 「测试失败」; real digest > 2 KB arrives in 企业微信 |
| 7 (Wed eve) | Deferred-until copy, restore drill, external uptime monitor, ops notes | 2 | Drill restored a snapshot into `$D/tmp`; monitor shows 7 days of green |
| 8–14 | Observe; `closed` registration on Day 14; week-2 patches as time allows | ~4 | 14-day 概览 numbers recorded for the phase-2 decision |

### Day 0 (tonight, ≈ 1 h) — decisions, purchases, the one test that decides the region

1. **Decide the §7 defaults** (5 min): user `sqin`, Tokyo, Porkbun domain + DNSPod DNS, ECDICT yes, caps 6/100, one single-use code per friend.
2. **Domain** (15 min): Porkbun `.com` 11.81 USD/yr, pay with Alipay (hosting-verify F14: Porkbun pricing API 2026-11-04 shows `com` registration = renewal = 11.81; Alipay listed under payment options). Cheaper alternatives: `.top` 1.63 first year / 4.63 renewal. Then either keep Porkbun DNS (zero extra setup) or set the nameservers to DNSPod (free; same Tencent account; fast resolution from the mainland; minimum TTL 600 s on the free tier — hosting-verify omission 2; needs the Tencent account 实名 you already have for Lighthouse — hosting:F13). Do this tonight so NS propagation is done before Day 1's TLS step. No ICP filing is required for an overseas host (hosting:F12).
3. **VPS** (20 min): Tencent Cloud 中国站 → 轻量应用服务器 → 东京 → Linux 2 vCPU / 4 GB / 60 GB / 30 Mbps / 1.5 TB bundle (standard ≈ ¥42/month; check the 活动 page for a first-year annual promo — hosting:F4, hosting-verify omission 6) → image **Ubuntu Server 24.04 LTS 64-bit** (verify it is offered; a 2025 post claimed otherwise — hosting:F7) → SSH key login. Lighthouse firewall: keep 22/80/443 (default), nothing else. Note `VPS_IP`. The public IP can be swapped in place exactly once per instance (hosting-verify omission 1) — your GFW escape hatch.
4. **Reachability test, before anything else** (5 min). Log in with the console's default user and run:
   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' https://api.anthropic.com/v1/models      # expect 401 (reachable, no key) — 403 means blocked region/IP
   curl -sS -o /dev/null -w '%{http_code}\n' https://platform.claude.com/              # expect 200/302, never 403 (OAuth login/refresh host — clivps-verify omission 6)
   curl -sI https://downloads.claude.ai/claude-code-releases/latest | head -1           # expect HTTP/2 200
   curl -sS -o /dev/null -w '%{http_code}\n' https://commons.wikimedia.org/w/api.php   # photos; the Mac's network could not reach this (security:F10)
   ```
   403 on the first two → destroy and rebuild in Singapore (same bundle price; hosting:F2 confirms SG). Done: all four answer as expected.
5. **DNS A record**: `words.example.com → VPS_IP`, TTL 600 (DNSPod free floor) — do it now; Caddy will pick it up on Day 1.

### Day 1 (Thu evening, ≈ 3 h) — the service goes live on the VPS, Mac data included

**1.1 Box preparation (as the console user, 10 min)** — deploy runbook Step 1 (deploy:F1/F3):
```bash
sudo adduser --disabled-password --gecos "" sqin && sudo usermod -aG sudo sqin
echo 'sqin ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/sqin && sudo chmod 440 /etc/sudoers.d/sqin   # install.sh needs sudo -n
sudo install -d -m 700 -o sqin -g sqin /home/sqin/.ssh && sudo cp ~/.ssh/authorized_keys /home/sqin/.ssh/ && sudo chown sqin:sqin /home/sqin/.ssh/authorized_keys
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config && sudo systemctl reload ssh
sudo apt-get update && sudo apt-get install -y ufw && sudo ufw allow OpenSSH && sudo ufw --force enable     # 80/443 stay closed until the DB with the admin is in place (deploy:F5)
```
Done: `ssh sqin@VPS_IP` works with your key; password login refused.

**1.2 Prerequisites install.sh does not install (as `sqin`, 20 min)** — deploy:F1, deploy-verify F1 (Ubuntu's apt node is 18.19; NodeSource 22.x ≥ 22.12 satisfies `frontend/package.json` engines):
```bash
sudo apt-get install -y git curl ca-certificates gnupg openssl python3 python3-venv python3.12-venv sqlite3
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | sudo gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | sudo tee /etc/apt/sources.list.d/nodesource.list
sudo apt-get update && sudo apt-get install -y nodejs && node --version          # v22.2x
python3 -c 'import sys,venv,ensurepip,sqlite3,zoneinfo; print(sys.version)'       # 3.12.x
# Claude Code CLI from the signed apt *stable* repo: one file /usr/bin/claude (2.1.311-1, 294 MB), no silent auto-update (clivps:F1/F2)
sudo curl -fsSL https://downloads.claude.ai/keys/claude-code.asc -o /etc/apt/keyrings/claude-code.asc
echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main" | sudo tee /etc/apt/sources.list.d/claude-code.list
sudo apt-get update && sudo apt-get install -y claude-code && claude --version    # 2.1.311 (Claude Code)
```
Done: `node`, `python3` ≥ 3.12 and `claude` all resolve on PATH (install.sh's preflight refuses otherwise — deploy:F2).

**1.3 Final copy of the Mac data (on the Mac, 10 min)** — deploy:F11, deploy-verify F11 (images = 28 shard dirs, 216 KB):
```bash
launchctl bootout gui/$(id -u)/com.word-dance.server              # stop the Mac service: clean copy, lease expires ≤ 90 s, and no second instance keeps spending AI
sqlite3 /Users/sqin/word-dance-data/word-dance.db "VACUUM INTO '/Users/sqin/wd-migrate.db'"
tar -C /Users/sqin/word-dance-data -czf /Users/sqin/wd-images.tgz images
scp /Users/sqin/wd-migrate.db sqin@VPS_IP:/home/sqin/word-dance.db
scp /Users/sqin/wd-images.tgz sqin@VPS_IP:/home/sqin/
```
Never copy `.env` (Mac-specific wrapper/paths; `WD_SECRET_KEY` only protects unexpired e-mail codes). Keep `/Users/sqin/word-dance-data` untouched for one week as the rollback copy; leave the launchd agent unloaded (the plist stays on disk).

**1.4 Checkout + pre-placed data (as `sqin`, 5 min)**:
```bash
git clone https://github.com/bigBuffers/word-dance.git /home/sqin/word-Dance && cd /home/sqin/word-Dance && git checkout main   # 9ab13a5 or later
install -d -m 0700 /home/sqin/word-dance-data
mv /home/sqin/word-dance.db /home/sqin/word-dance-data/word-dance.db && chmod 600 /home/sqin/word-dance-data/word-dance.db
tar -C /home/sqin/word-dance-data -xzf /home/sqin/wd-images.tgz && rm /home/sqin/wd-images.tgz
```
Because the DB already holds admin `sqin`, the first-registrant-becomes-admin rule can never fire (deploy:F5, security:F3) and `create-admin --if-none` is a no-op.

**1.5 Rehearse, then install (as `sqin`, 15–25 min; `npm ci` dominates)** — deploy Step 4, deploy:F4/F13/F17:
```bash
cd /home/sqin/word-Dance
deploy/install.sh --with-caddy words.example.com --with-ecdict --contact-email you@yourmail.example --dry-run   # preflight must pass; prints every step with '+'
deploy/install.sh --with-caddy words.example.com --with-ecdict --contact-email you@yourmail.example
```
What you will see: venv + pip (26 manylinux wheels, no compiler), SPA built into `frontend-releases/<sha>.new`, `.env` created once (`WD_SECRET_KEY`, `WD_CLAUDE_BIN="/usr/bin/claude"`, `WD_DATA_DIR`, `WD_CONTACT_EMAIL`, and the proxy trio `WD_HOST="127.0.0.1"`, `WD_PUBLIC_URL="https://words.example.com"`, `WD_TRUST_PROXY="1"`), snapshot published, `wd migrate` → `0 pending` (copied DB is already at schema 9), `import-seed` → `seed up to date`, ECDICT 216 MB download → `stardict.db` 851 MB + `WD_ECDICT_DB_PATH`, `wd claude-check` → **WARN** (no credential yet — expected), units `User=sqin` enabled and started, Caddy 2.6.2 installed with `deploy/Caddyfile.example` rendered, health printed from 127.0.0.1:8000.

**1.6 `.env` edits + restart (5 min)** — every line `KEY="value"` (install.sh's validator aborts otherwise — deploy:F4):
```bash
E=/home/sqin/word-dance-data/.env
sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="0"|' $E                                   # deploy first, credential tomorrow (deploy:F2): jobs queue, UI runs on dictionary data
sed -i 's|^WD_AI_MODEL=.*|WD_AI_MODEL="claude-sonnet-5-5"|' $E                        # pin what the content was verified on (clivps:F7)
sed -i 's|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="6.00"|' $E               # security:F8 (10 friends: defaults 3/40 trip in weeks 2–4)
sed -i 's|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="100.00"|' $E
sed -i 's|^WD_AI_SVG_DAILY_BUDGET_USD=.*|WD_AI_SVG_DAILY_BUDGET_USD="1.00"|' $E       # revisit on Day 2 once provider_state from Tokyo is known (security:F10)
grep -nE '^WD_(REGISTRATION_MODE|HOST|TRUST_PROXY|PUBLIC_URL|ECDICT_DB_PATH)=' $E       # invite / 127.0.0.1 / 1 / https://words.example.com / …/stardict.db
sudo systemctl restart word-dance && curl -fsS http://127.0.0.1:8000/api/health         # "needs_setup":false
```
Keep `WD_AI_HOURLY_CALL_CAP="60"` and `WD_AI_PREWARM_DAILY_BUDGET_USD="1.00"` (changed only temporarily on Day 3).

**1.7 Open the door: firewall + TLS (10–30 min incl. propagation)** — deploy:F7:
```bash
sudo ufw allow 80,443/tcp                                   # and 80/443 in the Lighthouse console firewall (default already open)
sudo systemctl reload caddy && sleep 20
curl -sSI https://words.example.com/api/health | grep -iE '^(HTTP|strict-transport)'   # HTTP/2 200 + strict-transport-security (security:F6)
journalctl -u caddy -n 20 --no-pager | grep -i certificate   # "certificate obtained successfully"
```
Then on your phone (cellular, not Wi-Fi): open `https://words.example.com` → the login page shows the invite field (not 「尚无账号…」) → log in as `sqin` with the Mac password → 管理 → 概览 loads; a login's `Set-Cookie` must carry `; Secure` (`curl -si -X POST … /api/auth/login` from the box with `-H 'X-WD-Request: 1'` shows it, or trust the HSTS header check above). Done: Day 1 complete; the service is public, invite-only, AI off.

**1.8 Copy `.env` to your password manager** (ops.md §2) — 2 min.

### Day 2 (Fri evening, ≈ 3 h) — credential wiring, photos, backups off-box, start of the PWA patch

**2.1 Credential wiring, credential-neutral (30–60 min)** — clivps:F9 (verified with the fake binary: the runner forwards only `ANTHROPIC_API_KEY/AUTH_TOKEN/BASE_URL`, proxies, `SSL_CERT_*`, `CLAUDE_CONFIG_DIR`, `XDG_*`; everything else must come from a wrapper). Create the wrapper now whichever path you pick — it also pins the binary against silent changes:
```bash
install -d -m 700 /home/sqin/word-dance-data/bin
cat > /home/sqin/word-dance-data/bin/claude-wrapper <<'EOF'
#!/bin/sh
# CLI-only environment (runner.py forwards only its allow-list). Never put proxies in the unit: the image pipeline's DNS-pinned TLS breaks.
export DISABLE_AUTOUPDATER=1 DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1
# exactly one credential line, or none to use the login stored under $HOME/.claude/.credentials.json:
# export CLAUDE_CODE_OAUTH_TOKEN="$(cat /home/sqin/word-dance-data/oauth.token)"          # from `claude setup-token` (one-year token)
# export ANTHROPIC_API_KEY="$(cat /home/sqin/word-dance-data/anthropic.key)"
# export ANTHROPIC_AUTH_TOKEN="$(cat /home/sqin/word-dance-data/gateway.token)" ANTHROPIC_BASE_URL=https://gateway.example.com
exec /usr/bin/claude "$@"
EOF
chmod 700 /home/sqin/word-dance-data/bin/claude-wrapper
sed -i 's|^WD_CLAUDE_BIN=.*|WD_CLAUDE_BIN="/home/sqin/word-dance-data/bin/claude-wrapper"|' /home/sqin/word-dance-data/.env
```
Per path (clivps step list A–E): **stored login** → `claude auth login` as `sqin` over SSH, press `c`/copy the printed URL, open it in a browser on the Mac (claude.ai/platform.claude.com answer 403 from your network without the tunnel — clivps-verify omission 6 — so the browser side goes through your existing proxy), paste the code at `Paste code here`, then `claude auth status --text` (exit 0). Run `claude` interactively once as `sqin` to pass the first-run onboarding and the 10-s connectivity check (clivps gotchas). **setup-token** → uncomment the `CLAUDE_CODE_OAUTH_TOKEN` line (a systemd `Environment=` would silently do nothing — clivps:F9). **API key / bearer** → either the wrapper line or `claude.env` + a drop-in (`sudo systemctl edit --drop-in=claude word-dance.service` → `[Service] EnvironmentFile=-/home/sqin/word-dance-data/claude.env`). **apiKeyHelper** → `/etc/claude-code/managed-settings.json` or `WD_AI_EXTRA_ARGS="--settings /home/sqin/word-dance-data/claude-settings.json"` (tier 1's `--restricted` ignores `~/.claude/settings.json`).

Two technical facts to know, stated neutrally: (a) if the chosen login belongs to an organisation that enforces fail-closed server-managed settings, every `claude -p` spawn needs a live round-trip to api.anthropic.com before the model call, and the live Mac ledger shows 15 such failures in 8 h (2026-11-02/03) each misfiled as `auth` → a 30-minute global pause plus the 「未登录」 banner (clivps-verify omission 1); (b) subscription usage-limit messages (`You've hit your … limit`) are classified as plain `error` today (clivps-verify omission 2). Both are covered by the Day-4 watch cron and the optional week-2 classifier patch (§4).

**2.2 Prove it and switch AI on (10 min)** — clivps:F10:
```bash
export WD_DATA_DIR=/home/sqin/word-dance-data
/home/sqin/word-Dance/.venv/bin/wd claude-check        # claude check OK: tier 1, cost $0.00xx, … model claude-sonnet-5-5, claude 2.1.311  (exit 0, ≤ $0.05)
sed -i 's|^WD_AI_ENABLED=.*|WD_AI_ENABLED="1"|' $WD_DATA_DIR/.env && sudo systemctl restart word-dance
journalctl -u word-dance -o cat -f | grep -E 'claude_(call|auth|spawn)|lease_acquired'   # watch the first real job
```
If the migrated kv still says `claude.paused_until` in the past, nothing to do; if 管理 shows 「已暂停」, click 恢复 AI (deploy:F11 — carried-over kv). Done: a custom word you add on your phone gets its content within ~1 minute.

**2.3 Photo providers from Tokyo (10 min)** — security:F10 (on the Mac's network Wikimedia failed with SSL EOF and Openverse timed out; 30 of 31 images are Claude SVGs). Add two words, open them, then 管理 → 概览 → 图片来源配额 (`provider_state`): if Wikimedia/Openverse show `last_ok` now, keep `WD_AI_SVG_DAILY_BUDGET_USD="1.00"`; if they still fail from Tokyo, either register `WD_PIXABAY_KEY`/`WD_PEXELS_KEY` (free keys, config only) or set the SVG cap to `"0"` for text-only cards — your call (§7).

**2.4 Backups off-box (20 min)** — deploy:F14, ops.md §2. The timer already runs nightly at 03:30 Asia/Shanghai on the box. Pull to the Mac with a launchd agent (macOS's openrsync is protocol-29 compatible; launchd runs a missed calendar job at the next wake, so a sleeping Mac just pulls later):
```bash
mkdir -p /Users/sqin/word-dance-vps-backups
cat > ~/Library/LaunchAgents/com.word-dance.backup-pull.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.word-dance.backup-pull</string>
  <key>ProgramArguments</key><array><string>/usr/bin/rsync</string><string>-a</string><string>--delete</string>
    <string>sqin@words.example.com:/home/sqin/word-dance-data/backups/</string><string>/Users/sqin/word-dance-vps-backups/</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardErrorPath</key><string>/Users/sqin/Library/Logs/word-dance/backup-pull.log</string>
</dict></plist>
EOF
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.word-dance.backup-pull.plist && launchctl kickstart gui/$(id -u)/com.word-dance.backup-pull
ls -la /Users/sqin/word-dance-vps-backups/      # the Day-1 nightly file (or run `wd backup` on the box first)
```
Also take a Lighthouse console snapshot of the instance now (quota/price per console) — the rollback for a bad upgrade or a GFW rebuild.

**2.5 Start the PWA surface (≈ 1.5 h, on the Mac, branch `feat/pwa-surface`)** — pwa A1–A4 (R1–R3), all verified: `sips` on this Mac renders SVG correctly (pwa:F5, byte-identical in verification); CSP needs no change (pwa:F3).
```bash
cd /Users/sqin/word-dance/frontend && mkdir -p public/icons
cat > public/icon-maskable.svg <<'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">
  <rect width="64" height="64" fill="#3b5bdb"/>
  <g transform="translate(12.8 12.8) scale(0.6)">
    <path d="M14 20l6 24h5l5-16 5 16h5l6-24h-5.5l-3.6 16-4.9-16h-4.2l-4.9 16-3.6-16z" fill="#ffffff"/>
  </g>
</svg>
EOF
sips -s format png -z 192 192 public/favicon.svg       --out public/icons/icon-192.png
sips -s format png -z 512 512 public/favicon.svg       --out public/icons/icon-512.png
sips -s format png -z 192 192 public/icon-maskable.svg --out public/icons/icon-maskable-192.png
sips -s format png -z 512 512 public/icon-maskable.svg --out public/icons/icon-maskable-512.png
sips -s format png -z 180 180 public/icon-maskable.svg --out public/apple-touch-icon.png        # opaque: iOS paints transparent corners black
```
`frontend/public/manifest.webmanifest` exactly as pwa A1 (`id "/"`, `start_url "/today"`, `scope "/"`, `display "standalone"`, `background_color`/`theme_color "#ffffff"`, `lang "zh-CN"`, the four icons, shortcuts 开始学习 `/study` and 生词库 `/bank`). `frontend/index.html` after line 13: `<meta name="mobile-web-app-capable" content="yes" />`, `<link rel="manifest" href="/manifest.webmanifest" />`, `<link rel="apple-touch-icon" href="/apple-touch-icon.png" />`. Backend `backend/wd/main.py` `_mount_spa` (pwa A4 + pwa-verify omissions 1–2): `no-cache` for `index.html`, `manifest.webmanifest`, `sw.js`, `registerSW.js`; `raise ApiError("not_found")` for any `assets/*` path that is not a file; two assertions in `backend/tests/integration/test_health.py::test_spa_serves_built_files_with_cache_policy`. Done: `npm run lint && npm run typecheck && npm test && npm run build` green; `.venv/bin/pytest -q backend/tests/integration/test_health.py` green; commit.

### Day 3 (Saturday, ≈ 6 h) — install hint, deploy, dry runs, prewarm, first friends

**3.1 Install hint + WeChat/QQ handoff (3–4 h)** — pwa A6/R4, pwa:F9 (WeChat's WebView offers no Add-to-Home-Screen; UA token `MicroMessenger`), ios:F16 (interstitial 「将要访问非微信官方网页」 possible). Files: `frontend/src/utils/platform.ts` (DOM-free: `isWeChat`, `isQQ`, `isIOS`, `isAndroid`, `installChannel`, `isStandaloneDisplay`), `frontend/src/components/layout/InstallHint.tsx` rendered by `AppLayout` above `<Outlet />` (`AppLayout.tsx:147`) only on `/today`, a 「添加到主屏幕」 row in `SettingsPage` 账号 section opening a `Sheet` with the same text, copy block `install: {…}` added **identically** to `src/i18n/zh.ts` (after `history:` at :72, before `settings:` at :74) and to `docs/FRONTEND.md` §8 (before :275) — the line-for-line mirror test (`zh.test.ts:67–80`) and the copy lint (CJK only under `src/i18n/`, forbidden term 单词本) are the constraints (pwa:F10). The WeChat/QQ card is non-dismissible; iOS/Android cards dismiss for 14 days via `useLocalPref('wd.installHintDismissedAt')`. No `beforeinstallprompt` dependency (no service worker → Chrome never fires it — pwa:F7, pwa-verify omission 6). Tests: `platform.test.ts` with six UA fixtures, `InstallHint.test.tsx` (channel → text, dismissal, hidden when `matchMedia` reports standalone). Done: gates green; PR merged to `main`.

**3.2 Deploy (10 min)** — deploy:F13 (build before stop, one atomic rename, downtime ≈ 3 s). Always restart; never two `--no-restart` runs in a row (the prune would delete the snapshot the running process is pinned to → whole-site 503 — pwa-verify omission 3):
```bash
ssh sqin@words.example.com 'cd /home/sqin/word-Dance && git pull && deploy/install.sh'     # no --with-caddy on upgrades (keeps the Caddyfile untouched — deploy:F4)
curl -sI https://words.example.com/manifest.webmanifest | grep -iE 'content-type|cache-control'   # application/manifest+json; no-cache
curl -s -o /dev/null -w '%{http_code}\n' https://words.example.com/assets/missing-deadbeef.js     # 404
```

**3.3 Device checks on your own phones (45 min)** — pwa R6, pwa:F8, ios:F14/F17: iPhone Safari → 分享 → 添加到主屏幕 → icon + name correct, opens standalone (iOS 26 default), login state carried over (WebKit says cookies are copied at add-time since 17.2 — ios:F17; the pwa verifier read the WWDC transcript as ambiguous, so expect at most one extra login), status bar OK in dark mode, first card's auto-pronounce silent until the first tap (pre-existing Safari rule), export button behaviour noted (WebKit 290847 — fallback patched in week 2), back navigation from 词详情 (if the edge-swipe does not work in standalone, add a 返回 control in week 2, 0.5 h). WeChat on the iPhone: open the URL from a chat → the handoff card appears → ··· → 在 Safari 中打开 works and no interstitial blocks the domain. Android (whatever you have): browser menu → 添加到桌面/安装应用 → icon + name; 发音 button speaks (system English voice present?).

**3.4 Reminder dry runs on your own devices (30 min)** — reminders:F4/F5/F15 (the channels have never run on this instance; `WD_PUBLIC_URL` is set so links are no longer the LAN guess — reminders:F11). iPhone: install Bark (App Store, free) → copy `https://api.day.app/<key>` → 设置 → Webhook 地址, 格式 Bark, 开启, 发送测试 → notification arrives (Bark reports bad keys as HTTP 400, so the green toast is truthful). WeChat: sct.ftqq.com → 微信扫码 → SendKey → `https://sctapi.ftqq.com/<SendKey>.send`, 格式 Server酱 → 发送测试 → the 「方糖」 服务号 message shows the title (free tier 5 messages/day, title-only card — reminders:F5). Then force one real digest for yourself to see the deep link and the Server酱 title handling (43–44 chars vs an undocumented 32-char limit — reminders-verify F2): from an admin session, `POST /api/admin/push/run {"user_id": 1}` (API.md endpoint 74 — builds and publishes *today's* batch inside the running service and enqueues the deliveries; side effect accepted for yourself only), e.g. with the browser dev tools or `curl -b <cookie> -H 'X-WD-Request: 1' -H 'Content-Type: application/json' -d '{"user_id":1}' https://words.example.com/api/admin/push/run`. (`wd push-now sqin` is the same operation from the CLI, but it runs next to the live service — the verifier only exercised it with the service stopped — so prefer the endpoint.) Done: both channels verified; note whether the Server酱 title was truncated/rejected (decides a 0.5 h fix in the Day-5 patch).

**3.5 Prewarm the friends' stages (15 min of attention; 2–4 h wall)** — security:F11, security-verify F11 (+10 % headroom, omission 5). Ask the friends their stage first (中考/高考/四级/六级). Temporarily raise the gates, restart, run plans from 管理 → AI → 预生成, then restore on Day 4:
```bash
E=/home/sqin/word-dance-data/.env
sed -i 's|^WD_AI_PREWARM_DAILY_BUDGET_USD=.*|WD_AI_PREWARM_DAILY_BUDGET_USD="20.00"|; s|^WD_AI_DAILY_BUDGET_USD=.*|WD_AI_DAILY_BUDGET_USD="40.00"|; s|^WD_AI_MONTHLY_BUDGET_USD=.*|WD_AI_MONTHLY_BUDGET_USD="150.00"|' $E
sudo systemctl restart word-dance
```
Plans: `stage=zk limit=2000 max_budget_usd=15` (≈ 2,000 most-frequent words ≈ 9–12 USD, ≈ 3.5 h at the 60 calls/h cap); add `gk limit=1000` (≈ 5–6 USD, 1.7 h) if any friend is 高考; `cet4`/`cet6` likewise. The prewarm gate also requires `spent_today < 50 %` of the daily cap, so with 40.00 at most ≈ 20 USD of prewarm runs per day — a second day covers zk+gk fully (3,891 words ≈ 19–24 USD). Prewarm never generates SVGs (security:F10 — SVG only for studied words). Done: 概览 shows `jobs.queued` draining at ≈ 6 calls/10 min and `today_usd` climbing as expected.

**3.6 Invites + onboarding message (30 min)** — deploy:F12, security:F14, security-verify omission 1 (the 5/h/IP registration throttle counts *failed* attempts, i.e. five mistyped codes from one Wi-Fi block the hour). One single-use code per friend, pasted, staggered:
```bash
for f in xiaoming xiaohong; do /home/sqin/word-Dance/.venv/bin/wd invite --uses 1 --days 7 --note "$f"; done   # code printed once (stdout); metadata on stderr
```
Send the §6 message with the URL and the friend's code to **two or three friends tonight** (one iPhone, one Android/HarmonyOS if possible). Stay reachable for 30 minutes: register → 欢迎 onboarding (stage, push time) → 添加到主屏幕 → Bark/Server酱 → 发送测试. Done: both show `sessions.ip` with a real client address (proves `WD_TRUST_PROXY` works — security:F5) in `sqlite3 -readonly -cmd ".timeout 5000" word-dance.db "select user_id, ip from sessions order by id desc limit 5"`.

### Day 4 (Sunday, ≈ 3 h) — caps back, watch cron, the rest of the circle

**4.1 Restore the caps once prewarm finished (5 min)**: `WD_AI_PREWARM_DAILY_BUDGET_USD="1.00"`, `WD_AI_DAILY_BUDGET_USD="6.00"`, `WD_AI_MONTHLY_BUDGET_USD="100.00"`, restart. Leftover prewarm plan jobs are harmless (they obey the gates).

**4.2 Watch cron on the box (45 min)** — turns `claude_auth`/budget/backup/downtime events, AI pauses, health failures and webhook `failed` rows into a push to *your own* Bark or Server酱 URL; no code change in the repo. The DB is 0600, so the cron runs as `sqin`; reads use `sqlite3 -readonly -cmd ".timeout 5000"` (security-verify F4: the CLI has no busy handler otherwise). Table/column names from `docs/SCHEMA.sql` (`system_events(kind, detail_json, created_at)`, `kv(key, value)`, `push_batches(webhook_status, published_at)`):
```bash
cat > /home/sqin/word-dance-data/bin/wd-watch.sh <<'EOF'
#!/bin/sh
# every 10 min via cron as sqin; notifies the owner's own Bark/Server酱 URL kept in $D/watch.url (0600)
D=/home/sqin/word-dance-data; DB=$D/word-dance.db; ST=$D/tmp/watch.last; NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
Q() { sqlite3 -readonly -cmd ".timeout 5000" "$DB" "$1" 2>/dev/null; }
m=""
curl -fsS -m 10 http://127.0.0.1:8000/api/health >/dev/null || m="$m health:DOWN;"
p=$(Q "select value from kv where key='claude.paused_until'"); [ -n "$p" ] && [ "$p" \> "$NOW" ] && m="$m ai_paused_until:$p;"
[ "$(Q "select value from kv where key='claude.available'")" = "0" ] && m="$m claude_unavailable;"
k=$(Q "select group_concat(distinct kind) from system_events where created_at > strftime('%Y-%m-%dT%H:%M:%SZ','now','-10 minutes') and kind in ('claude_auth','budget_daily','budget_monthly','budget_svg','backup_failed','downtime','provider_blocked')")
[ -n "$k" ] && m="$m events:$k;"
f=$(Q "select count(*) from push_batches where webhook_status='failed' and published_at > strftime('%Y-%m-%dT%H:%M:%SZ','now','-1 day')"); [ "${f:-0}" != "0" ] && m="$m webhook_failed_24h:$f;"
a=$(df --output=avail -m "$D" | tail -1); [ "${a:-99999}" -lt 2048 ] && m="$m disk_free_mb:$a;"
[ -z "$m" ] && { rm -f "$ST"; exit 0; }
[ -f "$ST" ] && [ "$(cat "$ST")" = "$m" ] && [ "$(( $(date +%s) - $(stat -c %Y "$ST") ))" -lt 21600 ] && exit 0   # same alert at most every 6 h
printf '%s' "$m" > "$ST"
curl -fsS -m 10 -H 'Content-Type: application/json' -d "{\"title\":\"word-Dance watch\",\"body\":\"$m\",\"desp\":\"$m\"}" "$(cat $D/watch.url)" >/dev/null
EOF
chmod 700 /home/sqin/word-dance-data/bin/wd-watch.sh
printf 'https://api.day.app/<your_bark_key>\n' > /home/sqin/word-dance-data/watch.url && chmod 600 /home/sqin/word-dance-data/watch.url   # or your sctapi URL
( crontab -l 2>/dev/null; echo '*/10 * * * * /home/sqin/word-dance-data/bin/wd-watch.sh' ) | crontab -
# test it once: temporarily break the health URL (e.g. port 8001 in a copy), or insert nothing and just run it: /home/sqin/word-dance-data/bin/wd-watch.sh; echo $?
```
(`body` is read by Bark, `desp` by Server酱; the other key is ignored.) Done: a forced failure produced one notification on your phone.

**4.3 Invite the rest (1 h, staggered across the day)**: one code each, at most four registrations per hour from any one Wi-Fi (security:F5), couples on the same router use cellular for the registration. Note each friend's device class (§3) in a private list — it decides the phase-2 trigger.

**4.4 First 概览 review (15 min)**: `today_usd`/`month_usd`, `jobs.queued/dead`, provider cooldowns, events in the last 24 h, `last_backup`. Write the numbers down (you will compare on Day 14).

### Days 5–6 (Mon–Tue evenings, ≈ 6 h) — webhook hardening, then open the other channels

**5.1 Patch (4–5 h, branch `fix/webhook-body-check`)** — reminders:F3 (verified live: WeCom answers HTTP 200 `errcode 93000`, Feishu HTTP 200 `code 19001` for bogus keys and the UI says 「测试成功」, the batch is marked `sent`), reminders-verify omission 1 (Server酱³ `https://<uid>.push.ft07.com/send/<key>.send` also answers HTTP 200 `{"error":"sendkey not found","code":10003}`), reminders:F7 (WeCom `text` ≤ 2048 UTF-8 bytes; the real digest measured 1,982–2,061 bytes → `45002` silently). Changes, all in `backend/wd/delivery/webhook.py` + tests:
- `safe_post` keeps the response body (first 1 KB) in `PostResult`; a new `vendor_error(fmt, body)` returns the error for `wecom` (`errcode != 0`), `feishu` (`code != 0`), `serverchan` (`code` present and `!= 0`, covering Turbo and ³); `send_batch_webhook` raises `WebhookError(f"{fmt} {code}: {msg}")` so retries run and `delivery_error` becomes truthful (reminders-verify omission 2); `send_test_webhook` returns `ok=False` with the vendor text → the SPA already renders `webhookFail(e)`.
- WeCom payload → `{"msgtype":"markdown","markdown":{"content": …}}` with the link as `[打开 word-Dance](url)` and the content truncated to 4,096 bytes on a line boundary (markdown cap — reminders:F7); Feishu stays `text` (20 KB).
- The test message carries the `/today` URL (today `url=None` at `webhook.py:351`), so the deep link is exercised before the first digest (reminders rec 2d); `docs/API.md` endpoint 17 sentence updated.
- Conditional (if Day 3 showed truncation/rejection): a Server酱-specific title ≤ 32 chars, e.g. `今日词汇 11月3日 · 复习10 新词3 推荐15` (0.5 h).
- Tests: extend `backend/tests/integration/test_delivery.py` (parametrised over `webhook.FORMATS`) with HTTP-200-error bodies per vendor and the 4,096-byte WeCom cut; `pytest -q backend/tests/integration/test_delivery.py backend/tests/unit/test_queue.py` (71 tests today) green.
Done: with a bogus WeCom URL the UI says 「测试失败：wecom 93000: …」; `push_batches.delivery_error` shows the vendor code.

**6.1 Deploy + open the channels (30 min)**: `git pull && deploy/install.sh`; then tell the 企业微信/飞书/Server酱³ users they can switch (§3). Verify one real 企业微信 digest > 2 KB arrives as markdown with a tappable link.

### Day 7 (Wed evening, ≈ 2 h) — deferral copy, drill, external monitor, notes

**7.1 Deferred-until copy (1.5 h)** — security:F17: `zh.study.contentDeferred` and `zh.errors.budgetExhausted` become functions of the ISO instant already present in `content_deferred_until` / `details.resumes_at` (hourly, next-day 00:05 or 1st-of-month 00:05 — security:F8), formatted in the user's timezone: 「AI 额度已用完，例句将在 11月5日 00:05 后补齐」; `WordDetailPage.tsx:487` passes the value; `docs/FRONTEND.md` §8 mirrored; a vitest case per deferral kind. Backend `errors.py:53` keeps its generic 409 text (the client formats). Deploy.

**7.2 Restore drill (15 min)** — ops.md §2: `D=/home/sqin/word-dance-data; L=$(ls -t $D/backups/word-dance-*.db.gz | head -1); gunzip -c "$L" > $D/tmp/drill.db && wd check db --db $D/tmp/drill.db && rm $D/tmp/drill.db`. Also open the newest file pulled to the Mac with `sqlite3` and count `users`.

**7.3 External uptime monitor (15 min)**: a free HTTP monitor (e.g. UptimeRobot free tier, 5-minute checks) on `https://words.example.com/api/health` expecting `"status":"ok"`, alert to your e-mail/Bark. It checks from overseas, so a green monitor plus a friend's 「打不开」 means a mainland path problem (GFW/ISP), not the box — the re-IP runbook (§8 risk 2) applies.

**7.4 Ops notes (15 min)**: append to a private `OPS-NOTES.md` on the Mac: VPS_IP, domain registrar, DNS console, the watch URL, the unlock SQL (`sqlite3 -cmd ".timeout 5000" /home/sqin/word-dance-data/word-dance.db "DELETE FROM auth_throttle WHERE key='login:user:<name>'"` — security-verify F4), the AI-pause SQL cancel recipe (security-verify F7, corrected form), the re-IP runbook, the 90-day/phase-2 trigger list.

### Days 8–14 — observe, close registration, optional week-2 patches

- Daily 2-minute look at 概览 (spend, queue, events) or just trust the watch cron.
- Day 14: `WD_REGISTRATION_MODE="closed"` + restart once everyone is in (security:F14). New friend later → `invite` again for an evening.
- Week-2 patches (§4) as evenings allow: export fallback for standalone iPhone, classifier/banner neutrality (only if your credential is a claude.ai login), `wd unlock`, 返回 control if the standalone back gesture failed.
- Record the Day-14 numbers: users active, `month_usd`, dead jobs, webhook `failed`, device classes, and every friend remark about reminders/pronunciation → the phase-2 decision (§5 trigger).

---

## 3. Mobile route per device class (what the friend does; what they get)

Summary table, then per-class notes. "Install" = get an icon that opens word-Dance; "Reminder" = daily 今日词汇 nudge at `push_time`; "TTS" = the 发音 button; "Login" = what the first session looks like.

| Device class | Install | Reminder (week 1 → after Day 6) | TTS | Login |
|---|---|---|---|---|
| iPhone, Safari | 分享 → 添加到主屏幕; opens as a web app by default on iOS 26 ("zero requirements" — pwa:F7/ios:F14); iOS 16.4–18 same via the existing Apple metas | **Bark** (App Store, free; APNs; HTTP 400 on bad key — reminders:F4) → tap opens the default browser at `/today` | Web Speech, pre-installed voices (Samantha/Daniel); first card needs one tap | Username + password once; cookie copied into the home-screen app on ≥ 17.2 (ios:F17) — at most one extra login; 30-day sliding session |
| iPhone, link opened in WeChat | WeChat WebView has no A2HS → hint card: 「右上角 ··· → 在 Safari 中打开」 (pwa:F9, ios:F16); possible 「非微信官方网页」 interstitial | Bark as above; Server酱 also works but lands in WeChat's browser (separate cookie jar) | as above once in Safari | WeChat's browser has its own cookie jar → log in again there or hand off to Safari |
| GMS Android (global ROM / Pixel / Samsung, or Google services enabled) | Chrome ⋮ → 安装应用 / 添加到主屏幕 → real WebAPK once the manifest ships (android:F8/F9); no automatic prompt (no SW) — the hint shows the steps | **Server酱 Turbo** → WeChat 服务号 (title-only card, 5/day free — reminders:F5), or ntfy Play build with the template URL (reminders:F9); Web Push is not built | Chrome bridges to the system TTS engine — needs an English voice installed (android:F13) | Username + password; WebAPK shares Chrome's cookies → no extra login |
| GMS-less domestic Android (Xiaomi HyperOS / OPPO ColorOS / vivo OriginOS / Honor MagicOS, default state) | Vendor browser menu → 添加到桌面 (a launcher shortcut; whether it honours `display: standalone` is undocumented — android:F10); sideloaded Chrome → shortcut only (android:F9) | Server酱 Turbo → WeChat (works everywhere WeChat is); from Day 6: **Server酱³ app** for a true system notification via 小米/华为/OPPO/vivo push channels (reminders:F6; needs the body-check patch because it answers HTTP 200 on error — reminders-verify omission 1) or 企业微信/飞书 bots | Chromium-based vendor browsers likely bridge to the system engine — untested; WeChat's XWeb unknown; say so in onboarding | Username + password in the browser; the shortcut opens the same browser profile → login persists |
| HarmonyOS 4.x (Huawei not upgraded to 5) | 华为浏览器 → 添加至桌面 (PWA-capable sites get a 快应用 shortcut — android:F7) | Server酱 → WeChat; Server酱³ lists 华为 push (reminders-verify F6) | Huawei engine untested | as above |
| HarmonyOS NEXT (5/6/7 — all Huawei phones since late 2024) | 华为浏览器 ∷ → 添加至桌面 (max 10 shortcuts; no manifest/standalone documented — android:F7); no APK path (卓易通 container untested — android-verify omission 1) | Server酱 → native WeChat on AppGallery; 企业微信 has a native NEXT build (reminders:F7) | ArkWeb implements Web Speech except in 坚盾守护 mode (inferred — android-verify F7); test on the friend's phone | Username + password in Huawei Browser |

Per-class notes that matter in month 1:
- **Everyone**: the session cookie is HttpOnly, 30 days sliding, max 20 sessions per user (security:F1); no self-service password reset — you reset from 管理 → 用户 → 重置密码 (security:F16); 10 wrong passwords lock the username 15 min (then 30, 60 … up to 24 h; security:F4); 换一张/举报 replaces a picture for **everyone** (security:F12).
- **Reminders**: a relay down for > 12 min at push time costs that day's reminder (two retries at +2/+10 min — reminders:F1); a publish > 6 h late is skipped; the message is the same digest on every channel (title + summary + ≤ 10 words + link). Until Day 6 only Bark and Server酱 Turbo are offered because they report failures truthfully (HTTP 400 — reminders:F3).
- **Pronunciation on Android**: if the 发音 button is greyed with 「当前浏览器不支持语音」, the friend is in a WebView (WeChat/QQ in-app) — open in the system browser; if it is enabled but silent, the phone lacks an English voice — install one from the system TTS settings (android:F13 open question; vendor-dependent).

---

## 4. Code changes (minimal), with hours

All changes keep the public API, `install.sh` and the schema untouched; the regression gate is `make test` (pytest + contract audit + tsc + vitest + vite build) and, for the backend one-liners, `pytest -q backend/tests/integration/test_health.py`.

**Before inviting (Days 2–3; ≈ 6.5–8.5 h)**

| # | File(s) | Change | Fact | Hours |
|---|---|---|---|---|
| B1 | `frontend/public/manifest.webmanifest`, `frontend/public/icons/*.png`, `frontend/public/apple-touch-icon.png`, `frontend/public/icon-maskable.svg`, `frontend/index.html` | Manifest (pwa A1), five `sips` PNGs (≈ 40 KB), `mobile-web-app-capable` meta + manifest + apple-touch-icon links (pwa A2) | pwa:F2/F5/F7/F11 | 1 |
| B2 | `backend/wd/main.py` `_mount_spa`, `backend/tests/integration/test_health.py`, `docs/DEPLOY.md` §4 sentence | `no-cache` for `index.html`/`manifest.webmanifest`/`sw.js`/`registerSW.js`; 404 for missing `assets/*` (today: `index.html` with 200 under a `.js` URL) | pwa:F4, pwa-verify omissions 1–2 | 1 |
| B3 | `frontend/src/utils/platform.ts` (+test), `frontend/src/components/layout/InstallHint.tsx` (+test), `AppLayout.tsx:147` mount, `SettingsPage.tsx` 账号 row + Sheet, `frontend/src/i18n/zh.ts` `install:{…}`, `docs/FRONTEND.md` §8 mirror | Channel detection (standalone/wechat/qq/ios/android/desktop), hint card on `/today`, WeChat/QQ non-dismissible handoff, 14-day dismissal for the rest | pwa:F8/F9/F10, ios:F16 | 3–4 |
| B4 | `.env` only | AI caps 6/100/SVG 1.0, model pin, prewarm temporary raise | security:F8/F11, clivps:F7 | 0.25 (config) |
| B5 | none (ops) | wrapper + pinned CLI, watch cron, backup pull, invites | clivps:F9, deploy:F12/F14 | counted in §2 |

**Week 1 tail / week 2 (Days 5–14; ≈ 9–11 h)**

| # | File(s) | Change | Fact | Hours |
|---|---|---|---|---|
| W1 | `backend/wd/delivery/webhook.py`, `backend/tests/integration/test_delivery.py`, `docs/API.md` (17) | Vendor body check (wecom/feishu/serverchan incl. ³) → `WebhookError` + truthful `delivery_error`; WeCom → markdown ≤ 4,096 B with a link; test message carries the URL; optional ≤ 32-char Server酱 title | reminders:F3/F5/F7, reminders-verify omissions 1–2, F2 | 4–5 |
| W2 | `frontend/src/i18n/zh.ts`, `WordDetailPage.tsx:487`, `docs/FRONTEND.md` §8, tests | Deferral copy shows the real resume instant (hour / next day / 1st of month) | security:F8/F17 | 1.5 |
| W3 | `SettingsPage.tsx:597–602` + small helper | Standalone-iPhone export fallback: `fetch` (`endpoints.exportAccount` already exists) → `navigator.share({files})` → clipboard; behind `isStandaloneDisplay()` | pwa:F8 (WebKit 290847 NEW), pwa-verify omission 5 | 1.5–2 |
| W4 | `backend/wd/ai/runner.py:71`, `backend/wd/ai/common.py:37`, `probe.py:200`, `diag.py:99`, `install.sh:143`, tests | **Only if the credential is a claude.ai login**: classify the fail-closed managed-settings string as a short-retry network class instead of `auth` (30-min pause), recognise `hit your … limit` as a limit class, credential-neutral banner/hints without "sqin" | clivps:F11, clivps-verify omissions 1–2 | 3–4 |
| W5 | `backend/wd/security.py` (+CLI), tests | `wd unlock <username>` (today: a one-line SQL with `.timeout`) | security:F4, security-verify F4 | 1 |
| W6 | `WordDetailPage.tsx`, `AddWordsPage.tsx` | 返回 control, only if the iOS standalone back gesture failed on Day 3 | pwa:F8 open question 3 | 0.5 |

**Later (not in month 1 unless a trigger fires)**: service worker via `vite-plugin-pwa@2.0.0` (+338 lock packages; buys only the Android prompt and a precached shell; needs B2 — pwa:F6/F12, 4–6 h); per-IP login/register throttle not counting successes or keyed per account (security A8, 0.5 d); per-user AI quota + admin "cancel this user's queue" (security A1/A2, 2–3 d); image vote threshold (1 d); password reset by e-mail (1–2 d + SMTP); native `ntfy` format (1 d — table-rebuild migration, android-verify F12); `CLAUDE_CODE_OAUTH_TOKEN`/`DISABLE_AUTOUPDATER` passthrough + `WD_ANTHROPIC_API_KEY` first-class key (clivps rec 5, 1–2 d); generalising the `sqin` paths (unneeded while the VPS user is `sqin`); Capacitor web-side adapter (§5).

---

## 5. iOS app route and Android app route (phase 2, Capacitor 8 remote shell)

**Why this shape.** Of the three Capacitor modes only the remote shell (`server.url = https://words.example.com`) needs **zero backend change**: the WebView's document origin is the API origin, so the HttpOnly `SameSite=Lax` cookie is first-party, the CSRF Origin rule passes, `<img src="/media/…">` loads — all reproduced live by curl in verification (capacitor:F1, capacitor-verify F1 B1). The bridge is injected into remote pages on both platforms (iOS `WKUserScript` at document start; Android `addDocumentStartJavaScript` scoped to the `server.url` origin — capacitor-verify F4). Ionic calls `server.url` "not intended for production" and App Review 4.2 would apply to a storefront build — irrelevant for TestFlight **internal** testing and APK sideload, which have no review (captool:F5, ios:F4/F19/F20).

**Trigger that justifies starting (evaluate on Day 30).** Start phase 2 only if all of: (a) the web service ran 14 days without an unplanned outage or re-IP event; (b) at least three friends say the relay reminder is not enough (WeChat title-only card ignored, Bark refused, or a GMS-less Android friend wants a system notification without Server酱³), **or** two or more Android friends have no usable pronunciation in their browser; (c) you have three free evenings plus one weekend day inside a two-week window; (d) the friends have told you their iOS versions (≥ 16 for TestFlight, ≥ 17 for Xcode 27.2 debugging of your own phone) and whether they will accept an App Store Connect invitation under their Apple Account e-mail. If (b) is false, phase 2 is not worth ¥688/yr plus 90-day re-uploads; keep the web app.

**Tooling to install on the Mac (order, sizes)** — captool checklist, ios:F11, capacitor:F16:
1. Apple Developer Program enrolment **first** (lead time 1–3 days, worst case weeks on a name mismatch — ios:F3): Apple Developer app 11.1.1 (needs macOS 26.0 — your 26.7.1 qualifies), legal name exactly as on the 身份证, CFCA ID + selfie, ¥688/yr auto-renewing, paid with Alipay/WeChat Pay/card bound to the Apple Account (never Apple Account balance — ios:F1/F2). Your legal name becomes the public seller name.
2. Xcode 27.2 from the Mac App Store: 3.12 GB download, macOS 26.6+ (met), ≈ 9–12 GB installed; `sudo xcode-select -s /Applications/Xcode.app && sudo xcodebuild -license accept && xcodebuild -runFirstLaunch`. iOS simulator runtime (≈ 7.9 GB) optional — test on your real iPhone (iOS 17+). Since 2026-04-28 every upload to App Store Connect must be built with the iOS 26 SDK or newer, from April 2027 iOS 27 — Xcode 27.2 satisfies both (ios:F12).
3. Android, CLI-only (Android Studio optional): `brew install --cask temurin@21 android-commandlinetools`; `export JAVA_HOME=$(/usr/libexec/java_home -v 21) ANDROID_HOME=/opt/homebrew/share/android-commandlinetools`; `sdkmanager --licenses && sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0"` (≈ 1 GB); Gradle 8.14.3 comes from the wrapper; route `~/.gradle/gradle.properties` `systemProp.https.proxyHost/Port` through your HTTP proxy or use Aliyun Maven mirrors (dl.google.com/Maven Central are slow or blocked from the mainland). Capacitor targets Java 21 (captool:F2).
4. No CocoaPods (SPM default — captool:F4). Node 22.23.4 is enough for Capacitor 8; **pin `@capacitor/*` 8.6.x** — never 8.4.x/8.5.0 (CVE-2026-103922, CVSS 9.3, fixed in 8.5.1: remote content could load at the app origin via the internal proxy path — captool-verify omission 1). Capacitor 9 (GA planned end of November 2026) needs Node 24 and Xcode 27 — if you start in December, start on 9 and `brew install node@24`.
Budget: ≈ 15 GB of downloads, ≈ 30 GB on disk, half a day of mostly waiting (2–6 h on your network).

**Project and config** (new top-level `mobile/`, ≈ 2 h):
```bash
mkdir mobile && cd mobile && npm init -y
npm i @capacitor/core@8 @capacitor/cli@8 @capacitor/ios@8 @capacitor/android@8 @capacitor/app@8 @capacitor/local-notifications@8 @capacitor-community/text-to-speech@8 && npm i -D @capacitor/assets
npx cap init word-Dance com.example.worddance --web-dir web       # appId = reverse-DNS of a domain you control; it cannot change later
mkdir web && printf '<!doctype html><meta charset="utf-8"><title>word-Dance</title><p>无法连接服务器。<button onclick="location.href=\x27https://words.example.com/\x27">重试</button></p>' > web/index.html   # required even for a remote shell: iOS aborts without webDir/index.html (captool-verify omission 5)
npx cap add ios && npx cap add android && npx cap sync
cp ../frontend/public/favicon.svg assets/logo.svg && npx @capacitor/assets generate --iconBackgroundColor '#3b5bdb' --iconBackgroundColorDark '#3b5bdb' --splashBackgroundColor '#ffffff' --splashBackgroundColorDark '#121620'
```
`capacitor.config.ts` (capacitor rec 2, with the verifier's corrections): `server.url: 'https://words.example.com'` — the **canonical, non-redirecting** origin (on Android the bridge is origin-exact; an apex→www or http→https redirect yields a page without `window.Capacitor` — capacitor-verify omission 1); `server.cleartext: false`; `server.errorPath: 'index.html'`; `allowNavigation` left empty (attribution links open the system browser — capacitor:F7); `appendUserAgent: 'word-Dance-App/1'`; `ios.limitsNavigationsToAppBoundDomains: false`; `android.minWebViewVersion: 108` (`dvh`/`color-mix`/`<dialog>` floor; older WebViews get the error page — capacitor:F13); `plugins.SystemBars: { insetsHandling: 'native', initialViewportFitValueHint: 'cover' }` (the Capacitor 9 default; avoids the first-paint jump on WebView ≥ 140 — capacitor-verify omission 4, captool-verify F14); `plugins.LocalNotifications: { smallIcon: 'ic_stat_worddance', iconColor: '#3b5bdb', presentationOptions: ['banner','sound','list'] }`; Info.plist `ITSAppUsesNonExemptEncryption = NO` (otherwise every 90-day re-upload stalls on "Missing Compliance" — ios-verify omission 1).

**Web-side adapter in `frontend/` (≈ 1 d incl. tests)** — capacitor rec 5 (code sketch there), gated by `Capacitor.isNativePlatform()` so browsers are unchanged: `src/native/capacitor.ts` with `syncDailyReminder(settings)` (cancel id 1, re-schedule `{ on: {hour, minute}, allowWhileIdle: true }` from `push_time` converted from `settings.timezone` to the device zone), `requestReminderPermission()` called inside the 每日推送 switch gesture, `installNativeHandlers(navigate)` (Android back button → `history.back()` or `minimizeApp`; notification tap → `/today`, the event is retained until the listener exists — capacitor-verify omission 3). Android specifics from verification: the plugin's daily re-arm drops `allowWhileIdle`/`RTC_WAKEUP` after the first fire, so also call `syncDailyReminder` on every app resume (`App.addListener('appStateChange')`) (captool-verify F10 corr. 1); pass `isExactNotification: false` for a no-permission inexact reminder (≤ 1 h late) **or** keep exact and declare `USE_EXACT_ALARM` in the shell manifest (allowed for sideload; avoids the Settings detour that `schedule()` otherwise triggers on Android 12+ — captool-verify F10 corr. 2; captool:F11). Request `POST_NOTIFICATIONS` from the gesture, never at launch. iOS: one repeating `UNCalendarNotificationTrigger`; the 64-pending ceiling is irrelevant (captool:F12).
**TTS**: Android System WebView exposes no `speechSynthesis` (Chromium `disable-speech-synthesis-api`, verified in source — capacitor-verify F12), so `useSpeech.ts` gets a native branch to `@capacitor-community/text-to-speech@8.0.2` (`speak({text, lang: accent, rate, category: 'playback'})`, `openInstall()` hint when no English voice) (0.5–1 d); iOS keeps Web Speech (WKWebView enables synthesis; the Capacitor config may even lift the first-tap rule — capacitor:F12 inference, device-test).
**Export**: hide the two export anchors when native or implement Filesystem + Share (0.5 d; neither WebView implements downloads — capacitor:F13). **CSS**: add `var(--safe-top)` to `.page` and `.auth` top padding (0.5 d incl. device check; zero effect in browsers — capacitor:F10). **Onboarding copy**: hide the 「添加到主屏幕」 hint when native.

**Distribution — iOS (TestFlight Internal Only, no review)** — ios:F4/F6/F22, ios-verify F7 and omissions 2–4: App Store Connect → New App (name word-Dance, your bundle id, primary language 简体中文), **leave availability at all 175 territories incl. China mainland** (TestFlight installs fail with "not available or doesn't exist" when the storefront is excluded or the app is Removed from Sale), never submit for review; Xcode → Product → Archive → Distribute → **TestFlight Internal Only**; TestFlight → Internal Testing group; each friend added under Users and Access with the **Marketing** role limited to this app (an individual account may add 50 users); the invitation goes to the e-mail you type, expires in 3 days, and must be accepted with the Apple Account that owns that e-mail; the friend installs TestFlight (CN App Store, iOS 16+) and accepts. Builds expire after 90 days → calendar entry to re-archive and upload every ≤ 80 days (bump `CURRENT_PROJECT_VERSION`). **Never** add the shell to an external group even "to try": a Beta App Review rejection kills the build for internal testers too (ios-verify omission 3). Ad Hoc (UDIDs, `itms-services` manifest on the https domain, yearly profiles) only for a friend who refuses an ASC invitation (ios:F9).

**Distribution — Android (signed APK from your own domain)** — capacitor:F19, android:F15/F16, android-verify F3/F5: `keytool -genkeypair -v -keystore ~/secure/word-dance-release.jks -alias worddance -keyalg RSA -keysize 2048 -validity 10000`; `android/keystore.properties` (gitignored) + `signingConfigs.release` in `android/app/build.gradle`; `versionCode` monotonic (`2026120101`), `versionName "1.0.0"`; `./gradlew assembleRelease` → `app/build/outputs/apk/release/app-release.apk` → `scp` to the VPS `/srv/wd-dl/word-dance-1.0.0.apk`; Caddy serves it **before** the proxy (the SPA fallback would otherwise answer `index.html`):
```
words.example.com {
    encode zstd gzip
    request_body { max_size 2MB }
    handle_path /dl/* { root * /srv/wd-dl
                        file_server }
    reverse_proxy 127.0.0.1:8000
}
```
(edit `/etc/caddy/Caddyfile` by hand; from then on run `install.sh` without `--with-caddy`, which would re-render the template — deploy:F4). Install note per brand (zh-CN, one page): allow the source app under 安装未知应用; Xiaomi 纯净模式 → 授权单次安装 or 关闭纯净模式; vivo 设置 → 安全与隐私 → 更多安全设置 → 应用安装 → 关闭「禁止安装恶意应用」; OPPO 设置 → 密码与安全 → 系统安全 → 外部来源应用; Huawei/Honor 设置 → 系统和更新 → 纯净模式 → 退出; MIUI/HyperOS 自启动 + 省电策略「无限制」 for the reminder (dontkillmyapp — captool:F13). HarmonyOS NEXT friends stay on the web app (no APK runtime; 卓易通 container untested). Before 2027 (Google developer verification goes global on certified devices): register a free limited-distribution account and enrol the GMS-phone friends' devices (≤ 50; the device itself generates the QR/link code — android-verify F3); GMS-less and Huawei phones are outside the regime (Google Help: AOSP/non-certified devices and GMS-unsupported regions exempt — android-verify F4). Keep the keystore and its passwords backed up — losing them means a new app id for updates.

**Estimated person-days (both platforms): ≈ 6 (range 5–7.5)** = toolchain attention 0.5 + skeleton/icons 0.3 + first device runs 0.5 + web adapter 1 + TTS plugin branch 0.75 + CSS safe-area 0.5 + export fallback 0.5 + iOS release 0.5 + Android release 0.5 + device matrix/buffer 1 (capacitor rec sums to ≈ 4.8 without TTS/export — capacitor-verify F22). iOS-first path ≈ 3 d, Android increment ≈ 1.5 d. External waits: enrolment 1–3 days, downloads 2–6 h, TestFlight processing 5–30 min per build. Recurring: ¥688/yr, one re-upload per ≤ 80 days (≈ 1 h), one Capacitor 9 migration (Node 24, SwiftUI entry point, iOS 16/minSdk 26 floors — captool:F3).

---

## 6. zh-CN onboarding message for friends

Main message (send with the URL and the friend's own invite code; ≈ 1 minute to read):

> 嗨，我自己做了个背单词的小工具 word-Dance，想请你试用（只请了不到十个朋友）。
>
> **网址**：https://words.example.com
> **你的邀请码**：XXXX-XXXX-XXXX-XXXX（只能用一次、7 天内有效，请复制粘贴，别手打）
>
> **怎么开始**
> 1. 用手机浏览器打开网址 → 注册（用户名 + 8 位以上密码，别用常见密码；可以不填邮箱）→ 按提示选阶段和每天的推送时间。
> 2. **放到桌面**：iPhone 请在 Safari 里点底部「分享」→「添加到主屏幕」；安卓在浏览器菜单里选「添加到桌面」或「安装应用」；华为浏览器点右上角「∷」→「添加至桌面」。如果你是在微信里点开的链接，先点右上角「···」→「在浏览器打开」，微信里面没法加到桌面。
> 3. **每日提醒**（可选，推荐）：
>    - iPhone：App Store 装免费的 **Bark**，打开后复制它给你的 `https://api.day.app/…` 地址 → word-Dance「我的」→「推送设置」→ 粘贴到「Webhook 地址」，格式选 **Bark**，打开「Webhook 推送」→ 点「发送测试」。
>    - 安卓 / 鸿蒙：用微信扫码登录 sct.ftqq.com（Server酱），复制 SendKey，把 `https://sctapi.ftqq.com/你的SendKey.send` 粘贴到「Webhook 地址」，格式选 **Server酱** → 「发送测试」。消息会发到微信里的「方糖」服务号，免费版每天 5 条够用。
> 4. **发音**：点单词旁边的小喇叭。安卓手机如果没声音，去系统「文字转语音」设置里装一个英文语音包；在微信内置浏览器里喇叭是灰的，请用系统浏览器打开。
>
> **几个要知道的事**
> - 密码连错 10 次会锁 15 分钟（自己会解开）；忘了密码直接找我重置。
> - 同一个 Wi-Fi 下一小时最多注册 5 次，邀请码粘错几次也算，所以请复制粘贴。
> - 单词卡片上的「换一张」和「举报」会影响所有人看到的图片，别随手点。
> - 例句、搭配、记忆提示是 AI 生成的，仅供参考；你添加的单词会发给 AI 服务处理。每天的 AI 额度用完时例句会延后补齐。
> - 「我的」→「账号」里随时可以导出或删除你的全部数据。
> - 这是我业余做的小东西，服务器在东京，偶尔抽风请直接微信我。

Short follow-up for friends who want 企业微信 / 飞书 / Server酱³ (send only after Day 6):

> 如果你平时用企业微信或飞书，也可以让提醒发到那边：建一个只有你的群 → 添加群机器人 → 复制 Webhook 地址 → 粘贴到「Webhook 地址」，格式选对应的机器人。安卓想要系统通知（不经过微信）的话，装 **Server酱³** App，把它给你的 `https://<数字>.push.ft07.com/send/…` 地址粘贴进去，格式同样选 Server酱。点「发送测试」确认收到。

---

## 7. Decisions only the owner can make (recommended default in bold)

1. Region: **Tokyo** vs Singapore — same bundle price; Tokyo has better east/north-China latency with China Telecom evening variance (hosting:F21). Measure on Day 3 evening from your phone (`ping`/open the site at 21:00); > 5 % loss → rebuild in Singapore (1 h with the snapshot).
2. VPS service user: **`sqin`** (zero edits; repo defaults, messages and the unit all assume it — deploy:F3) vs `wd` (10 min of `.env`/profile edits and "sqin" in messages).
3. Domain + DNS: **Porkbun `.com` 11.81 USD/yr via Alipay + DNSPod free DNS (TTL floor 600 s)** vs Alibaba 万网 `.com` ¥85/¥95 with mandatory 实名 (1–2 working days possible) vs Cloudflare DNS-only (60 s TTL, grey cloud only — never proxy mainland traffic — hosting:F14/F17, hosting-verify omission 2). Domain name itself: short, no history (WeChat interstitials follow domain reputation — ios:F16).
4. Credential for the `claude -p` runner: one of stored login / `setup-token` / API key / bearer gateway / apiKeyHelper (clivps step list A–E). **Default mechanism regardless of choice: the wrapper at `$WD_DATA_DIR/bin/claude-wrapper` with `DISABLE_AUTOUPDATER=1`, apt stable 2.1.311, `WD_AI_MODEL="claude-sonnet-5-5"`.** Technical consequences per choice are in §2 Day 2 and §8 risk 3; the choice itself is deferred.
5. Carry over the Mac DB (admin `sqin`, 52 user_words, 48 contents, 31 images): **yes** — it closes the admin-bootstrap window by construction (security:F3) and keeps your own bank. Whether the 48 contents are kept or regenerated is a deferred question; technically keeping them costs nothing.
6. Prewarm: which stages and how far — **top 2,000 of each stage the friends name (≈ 9–12 USD per stage), run on Day 3** vs nothing (friends then see 「例句生成中…」 on words nobody studied before — security:F11).
7. AI spend ceiling: **daily 6.00 / monthly 100.00 USD** (hard ceiling ≈ 180 USD/month, realistic 25–60 — security:F8) vs defaults 3/40 (the month cap trips in weeks 2–4 and defers all AI to the 1st).
8. SVG concept cards: **1.00 USD/day** if photos work from Tokyo, else keys (`WD_PIXABAY_KEY`/`WD_PEXELS_KEY`) or `0` for text-only cards (security:F10).
9. Invites: **one `--uses 1 --days 7` code per friend** vs one 10-use code (deploy:F12 suggests the latter; single-use codes bound the damage of a leaked chat message and make the 5/h throttle arithmetic per friend).
10. ECDICT on the VPS (+1 GB, instant validation of custom words, fewer Claude lookups): **yes** (deploy:F17).
11. E-mail channel (SMTP via your own QQ/163 mailbox): **no in month 1** (deliverability from an overseas IP unverified — reminders:F10).
12. Registration `closed` on Day 14: **yes**; reopen `invite` for an evening when a new friend joins.
13. Minors in the circle: if any friend is under 18, add one parental-consent sentence to the message (security open question); **your call**.
14. Phase 2 at all, and when: **decide on Day 30 against the §5 trigger**; if yes, enrol with Apple first (lead time), appId = reverse-DNS of your domain, and ask friends whether they accept an App Store Connect invitation.

---

## 8. Risks and mitigations (top 8)

1. **The chosen VPS IP is refused by api.anthropic.com / platform.claude.com (403)** — region filter is documented; HK is out; Tokyo/SG expected to pass but untested from the exact Lighthouse pool (hosting:F2/F19, hosting-verify omission 4). Mitigation: the Day-0 curl test before any other work; rebuild in Singapore on 403; never a Hong Kong box.
2. **GFW/ISP makes the site unreachable from the mainland (IP block, SNI reset, DNS pollution)** — rare for a private HTTPS site that carries no proxy traffic (hosting:F20). Mitigation: clean IP, no proxy software on the box, external monitor green + friend 「打不开」 = path problem; runbook: Lighthouse 更换公网IP (once per instance lifetime — hosting-verify omission 1) → update the A record (TTL 600 → ≤ 10 min) → `sudo systemctl reload caddy`; second event → rebuild from the console snapshot as a new instance (1 h).
3. **AI credential problems look like "not logged in" and pause everything for 30 minutes** — stored logins expire (3-day warning only interactive); a fail-closed managed-settings login needs a live round-trip per spawn and the live ledger already shows 15 misfiled failures (clivps-verify omission 1); usage-limit strings are plain `error` (omission 2); 403 or a missing key file are plain `error` with no banner (clivps:F11). Mitigation: watch cron (Day 4) pushes `claude_auth`/`claude_unavailable`/pauses to your phone; recovery recipe in ops.md §6 (`claude auth login` as `sqin` → `wd claude-check` → 恢复 AI); W4 patch in week 2 if the credential is a claude.ai login; friends still get dictionary cards and the daily batch while AI is paused (deploy:F2).
4. **Shared-NAT throttles and invite typos** — 5 registrations/h and 20 logins/10 min per IP, failed attempts and 423s count (security:F5, security-verify omissions 1–2); username lockout after 10 failures (security:F4). Mitigation: single-use codes pasted, staggered invites, cellular for couples, the `.timeout 5000` unlock SQL in your notes, 「10 次锁 15 分钟」 in the onboarding message.
5. **Monthly AI cap trips silently and friends read 「明天」 for weeks** (security:F8/F17). Mitigation: caps 6/100 from Day 1, prewarm under temporary caps only, W2 copy patch on Day 7, `budget_monthly` event in the watch cron, weekly 概览 look.
6. **Webhook false success** — WeCom/Feishu/Server酱³ answer HTTP 200 with an error body; the UI, the DB and the admin ledger all say "sent" and only the friend's phone knows (reminders:F3, reminders-verify omission 2). Mitigation: week 1 offers only Bark and Server酱 Turbo (HTTP 400 on failure); W1 patch Days 5–6 before the other channels are offered; the watch cron reports `failed` rows once the ledger is truthful.
7. **WeChat in-app browser traps** — no Add-to-Home-Screen, separate cookie jar, possible 「非微信官方网页」 interstitial or an outright domain block (pwa:F9, ios:F16). Mitigation: B3 handoff card, share the plain https URL, test the domain inside WeChat with yourself on Day 3 before inviting, keep the domain clean.
8. **Photo providers unreachable from the host → every studied word costs an SVG until the sub-cap, then text cards** (security:F10: Wikimedia SSL EOF and Openverse timeouts from the Mac's network; 30/31 images are SVGs). Mitigation: Day-0 curl to Wikimedia, Day-2 `provider_state` check, SVG cap set deliberately, keyed providers as the config-only fallback. Related month-1 surprise to pre-empt: an `install.sh` run without a restart twice in a row deletes the snapshot the running process serves → whole-site 503 (pwa-verify omission 3); always restart after upgrades.

---

## 9. Costs (USD 1 = CNY 6.684, hosting slice rate of 2026-11-04)

**One-time**
| Item | CNY | USD | Note |
|---|---|---|---|
| Domain `.com` (Porkbun, Alipay) | ≈ ¥79 | 11.81 | renewal identical; `.top` 1.63 first year / 4.63 renewal (hosting-verify F14) |
| Prewarm top 2,000 words of one stage | ≈ ¥60–85 | 9–12.5 | per stage; zk+gk ≈ 19–24 USD; all 9,114 words ≈ 45–54 USD (security:F11, verify omission 5) |
| Apple Developer Program (phase 2 only) | ¥688/yr | 99 | auto-renewing App Store subscription (ios:F1) |
| Xcode / Android tools | ¥0 | 0 | ≈ 15 GB downloads |

**Monthly**
| Item | CNY | USD | Note |
|---|---|---|---|
| Tencent Lighthouse Tokyo 2 vCPU/4 GB/60 GB/30 Mbps/1.5 TB | ≈ ¥42 (first-year promos ≈ ¥199/yr seen for this bundle shape) | ≈ 6.3 (intl list 6.00) | overage 0.13 USD/GB Tokyo — irrelevant at this scale (hosting:F4/F22) |
| AI spend, 10 friends, after prewarm | ≈ ¥170–400 | 25–60 realistic | hard ceiling 180 USD at caps 6/100 (security:F8) |
| Bark, Server酱 Turbo free tier, ntfy.sh, UptimeRobot free | ¥0 | 0 | Server酱 paid 8 CNY/月 or 39 CNY/yr only if a friend needs > 5 msgs/day (reminders:F5) |
| Domain amortised | ≈ ¥7 | 1 | |
| **Total month 1** | **≈ ¥300–560** | **≈ 45–85** | VPS + domain + prewarm + AI |
| **Steady state** | **≈ ¥220–450** | **≈ 32–67** | VPS + AI; + ¥57/month if phase 2 (Apple) |

Not costed: your time (≈ 3 person-days week 1, ≈ 1 person-day week 2, ≈ 6 person-days phase 2), electricity for the Mac (no longer in the path).

---

## 10. Explicitly skipped items and why

| Skipped | Why |
|---|---|
| Variant B — keep the Mac behind a Cloudflare Tunnel | Free plan has no mainland PoPs; 80–300 ms, 40 KB/s-class reports, block waves; laptop sleeps after 1 min idle and needs a login session; AI depends on the hand-started SOCKS tunnel (hosting:F17, deploy:F9, deploy-verify omission 5). Only ever a one-evening demo bridge. |
| Tailscale / frp | Tailscale is not on the CN App Store and has no mainland DERP (hosting:F18); frp needs a VPS anyway (hosting:F19). |
| Hong Kong hosting | Best latency, but 403 from api.anthropic.com (hosting:F2). |
| Service worker (`vite-plugin-pwa`) | iPhone gains nothing (iOS 26 has zero installability requirements); Android gets only the automatic prompt and a precached shell at +338 lock packages and a version-skew window (pwa:F6/F7/F12). Revisit if Android friends ask for an 「安装」 button. |
| Web Push | 6–10 person-days (table rebuild, VAPID, pywebpush deps); reaches only Home-Screen iPhones and GMS Android; dead on GMS-less mainland Android (reminders:F13, android:F11). Bark covers iPhones for ¥0. |
| APNs/FCM native push | 5–8 backend days + an app; FCM unusable on mainland phones (reminders:F14). Local notifications in phase 2 cover the need. |
| Native `ntfy` webhook format | 1 day (CHECK-constraint table rebuild in migration 0010 — android-verify F12); ntfy's template URL works with the unchanged `generic` format today (reminders:F9). |
| E-mail/SMTP channel | Deliverability from an overseas IP to QQ/163 unverified; every friend has WeChat (reminders:F10). |
| Domestic app-store listings | APP备案 presupposes mainland hosting + ICP; Xiaomi closed to individual developers since 2024-10; OPPO invite-only pilot; vivo individual channel excludes ordinary APK apps (android:F14, android-verify F14). |
| App Store (any storefront) / external TestFlight | Guideline 4.2 applies to a remote-shell app; a Beta App Review rejection kills the build for everyone; the CN storefront needs ICP (ios:F8/F19/F20, ios-verify omission 3). |
| HarmonyOS NEXT native app | New ArkTS codebase, DevEco, same 备案 problem — weeks (android:F5/F7). |
| Capacitor M2 (bundled dist) / M3 (bearer token) | 7–9 / 8–11 person-days with backend changes and per-change rebuilds; needed only for a storefront (capacitor:F2/F3/F22). |
| Public-launch hardening (ToS/privacy pages, admin TOTP, per-user AI quota, image vote threshold, password reset by e-mail, curation tooling, audit trail) | Nothing in the code must change for ≤ 10 trusted friends (security:F1); all are "later" rows of the security gap table. |
| ICP / 公安联网备案 | Not required for an overseas host (hosting:F12); the 公安 reading is a legal question the owner deferred. |
| `sqin` path generalisation, configurable `forwarded_allow_ips` | Unneeded while the VPS user is `sqin` and Caddy runs on the same host (deploy:F3/F6). |
| Curated-mode / model-replacement plan (docs/WORD_LIBRARY_CURATION.md) | Policy and model questions are deferred by owner direction; this plan assumes the existing `claude -p` runner with a credential of the owner's choice. |
| `WD_AI_EXTRA_ARGS="--effort low"` | Available (clivps:F7) but content quality was verified at the model's default effort; a cost knob for later, not a launch change. |
