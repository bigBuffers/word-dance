# word-Dance — manual acceptance (QA) index

Automated coverage is `make test` (pytest + typecheck + vitest + build) and `make smoke` (`scripts/smoke.py`, the
end-to-end scenario of DESIGN §12 against a throwaway instance). What remains is manual and is split per area so
no checklist has to be edited by two packages:

* **Frontend shell, auth, onboarding, vocabulary, bank, settings, admin** → [`qa-frontend.md`](qa-frontend.md) (WP7;
  screenshots at 360 px and 1280 px, dark mode, copy/glossary checks).
* **Today, study session, screening, word detail, history** → [`qa-study.md`](qa-study.md) (WP8; phone + keyboard-only
  session, requeue, undo toasts, late session, TTS).
* **Deployment, operations, real Claude, delivery** → this file, below.

Tick a box only after the step was performed on this box (Ubuntu 24.04, `sqin`). Costs are noted where a real Claude
call is involved; everything else is free.

## A. Deployment on this box (TASKS WP9 acceptance)

- [ ] `systemd-analyze verify` passes on the rendered units: `cd /home/sqin/word-Dance && for f in word-dance.service word-dance-backup.service; do sed "s|__USER__|sqin|g; s|__REPO__|$PWD|g; s|__DATA__|/home/sqin/word-dance-data|g" deploy/$f > /tmp/$f; done && cp deploy/word-dance-backup.timer /tmp/ && systemd-analyze verify /tmp/word-dance.service /tmp/word-dance-backup.service /tmp/word-dance-backup.timer` → no line about `word-dance`.
- [ ] `bash -n deploy/install.sh && deploy/install.sh --dry-run && deploy/install.sh --with-ecdict --with-caddy words.example.com --no-restart --dry-run` → every mutating step printed with `+ `, nothing changed, exit 0.
- [ ] `grep -Ev '^[[:space:]]*(#|$)' deploy/env.example | grep -Ev "^WD_[A-Z0-9_]+=(\"[^\"\$\`\\\\]*\"|'[^']*')\$" | wc -l` → `0`.
- [ ] Unquoted `.env` value is rejected: `printf 'WD_AI_EXTRA_ARGS=--effort low\n' > /tmp/wd-bad.env && ! WD_DATA_DIR=/tmp/wd-bad-data WD_UNIT_FILE=/nonexistent bash -c 'DATA=/tmp/wd-bad-data; mkdir -p $DATA; cp /tmp/wd-bad.env $DATA/.env; deploy/install.sh --dry-run'` → clear `ERROR` naming the line, exit 1 (`WD_UNIT_FILE=/nonexistent` ignores the installed unit, whose data directory differs from `/tmp/wd-bad-data` — DEPLOY §2).
- [ ] `deploy/install.sh` (first real run, answers the contact-e-mail prompt or `--contact-email`) → `systemctl is-active word-dance` = `active`, `systemctl is-enabled word-dance-backup.timer` = `enabled`, `curl -fsS http://127.0.0.1:8000/api/health` → `needs_setup:true`.
- [ ] `grep -E '^WD_PUBLIC_URL="http://[0-9.]+:8000"$' /home/sqin/word-dance-data/.env` → the LAN URL was written on the proxy-less install.
- [ ] `deploy/install.sh` a second time → idempotent: `.env` unchanged (`md5sum` before/after), no reseed (`wd import-seed` prints "seed up to date"), `journalctl -u word-dance --since '-5 min'` shows `Stopped` → `Started` around `wd migrate`.
- [ ] `deploy/fetch_ecdict.sh /tmp/wd-ecdict-test && test -s /tmp/wd-ecdict-test/stardict.db` → sha256 `ea01f76a…3f3f6` verified, extracted with `python3 -m zipfile`; second run exits 0 at once; `rm -rf /tmp/wd-ecdict-test` afterwards (851 MB).
- [ ] `.venv/bin/wd backup --keep-daily 14 --keep-weekly 8 && ls /home/sqin/word-dance-data/backups/ | grep -E 'word-dance-[0-9]{8}-[0-9]{4}\.db\.gz'`; admin health shows `last_backup`.
- [ ] Restore drill: `sudo systemctl stop word-dance && .venv/bin/wd restore /home/sqin/word-dance-data/backups/<latest> --yes && sudo systemctl start word-dance` → health OK, data intact, `word-dance.db.bak-<ts>` present (delete it afterwards). Also: `wd restore … --yes` **while the service runs** exits 2 with the 「word-dance.service is running」 hint.
- [ ] `make smoke` → `SMOKE PASSED` (throwaway instance on port 8010; the production service keeps running).
- [ ] `ls -la /home/sqin/word-dance-data | grep -E '^drwx------'` and `stat -c %a /home/sqin/word-dance-data/.env | grep -x 600`; `stat -c %a /home/sqin/word-dance-data/word-dance.db` → `600`.
- [ ] `journalctl -u word-dance -n 50` shows JSON lines only (one per request at INFO, health at DEBUG), no tracebacks.

## B. First use through the browser (post-step 4)

- [ ] Open `http://<LAN-ip>:8000` from a phone and a desktop on the LAN; the login page shows the first-admin notice (`needs_setup`), **no invite field**.
- [ ] Register the admin (first user) → lands on `/welcome`; complete onboarding as 职场人士 (cet4 + cet6), timezone auto-detected, 筛词 step works and is skippable.
- [ ] 管理 → 邀请码 → create one → register a test user with it in a private window (invite field present now); a second use of a 1-use code fails with the 邀请码无效 message.
- [ ] Health header, CSP and cookie flags: `curl -sI http://<LAN-ip>:8000/api/health | grep -Ei 'x-request-id|content-security-policy|cache-control'`; `Set-Cookie` of login has `HttpOnly; SameSite=Lax` (and `Secure` only behind https).

## C. Real Claude acceptance (post-step 5 — total ≤ $0.20; watch `journalctl -u word-dance -f`)

- [ ] `.venv/bin/wd claude-check` → prints the flag tier and cost (≤ $0.05); `ai_calls` has one `kind='probe'` row; admin overview `ai.flag_tier` matches.
- [ ] 添加生词: `recieve`, `GDP`, one ordinary seed word → **wait for the service's own worker** (never `wd worker-once` while the service runs): `lookup_word` runs after the ≈ 20 s debounce → `recieve` gets a 拼写建议 (receive), `GDP` becomes an `abbreviation`, no auto-change of the typed word.
- [ ] One real 10-word `generate_content` call: 管理 → 预生成 (`POST /api/admin/content/prewarm {stage:'cet4', limit:10, max_budget_usd:0.1}`) → `GET /api/admin/ai/calls` shows `cost_usd ≈ 0.04`; inspect examples / collocations / mnemonic of two words; images came from Wikimedia first, Openverse second (attribution line under each photo).
- [ ] Build today's batch (今日 → 立即生成) and study it on a phone: card, 发音, 换一张, 已掌握 + 撤销.
- [ ] Budget guard: set `WD_AI_DAILY_BUDGET_USD="0.01"` temporarily, restart, request content for a new word → 「今日 AI 额度已用完」 and a `budget_daily` event; restore the value and restart.

## D. Delivery (post-step 6)

- [ ] Webhook test with a 企业微信 / 飞书 / Bark URL if available → 设置 → 发送测试 → message received, body shape per DESIGN §6.5.
- [ ] SSRF guard: a `generic` webhook pointing at `python3 -m http.server` on another LAN machine (private IP) is **rejected** by `PUT /api/settings`; a public https endpoint (e.g. a request-bin) is accepted and receives the test payload with `url` = `WD_PUBLIC_URL`.
- [ ] E-mail (when `WD_SMTP_*` is configured): verify an address with the 6-digit code, 发送测试邮件 → subject 【word-Dance】测试邮件 with the next push time.
- [ ] Scheduled push: set 推送时间 to a few minutes ahead → the batch is built ≤ 3 h before and published at the time (`journalctl` shows the tick, `push_batches.status='published'`), notifications sent once.

## E. Copy and glossary (post-step 7)

- [ ] `grep -rn '[一-龥]' frontend/src --include=*.tsx | grep -v i18n` → empty; `grep -rn 单词本 frontend/src` → empty.
- [ ] Native zh-CN read-through of `frontend/src/i18n/zh.ts` (glossary of DESIGN §0.3 respected).

## F. Hand-over

- [ ] Tag `v0.1.0`; README quick start verified from a fresh clone (`make setup && make test && make smoke`).
- [ ] Screenshots (360 px and 1280 px) attached to `qa-frontend.md` / `qa-study.md`; lessons learned added to [`ops.md`](ops.md) §6.
