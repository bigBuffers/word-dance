# word-Dance — operations runbook

Companion to [`DEPLOY.md`](DEPLOY.md) (what is installed and why). This file is the *what do I do now* document for
the person running the box. Paths are the defaults of DEPLOY §1: checkout `/home/sqin/word-Dance`, data directory
`/home/sqin/word-dance-data` (`WD_DATA_DIR`), service user `sqin`, CLI `/home/sqin/word-Dance/.venv/bin/wd`
(`wd …` below). Every `wd` command reads `$WD_DATA_DIR/.env` itself, so it works from any shell as `sqin`.

## 1. Daily checks

| What | Command |
|---|---|
| Service state | `systemctl status word-dance` · `systemctl is-active word-dance` |
| Backup timer | `systemctl list-timers word-dance-backup.timer` (next run 03:30 Asia/Shanghai, randomised ≤ 10 min) |
| Liveness | `curl -fsS http://127.0.0.1:8000/api/health` → `{"status":"ok","needs_setup":false,…}` |
| Live log | `journalctl -u word-dance -f` · `journalctl -u word-dance --since today -p warning` |
| Last 200 log lines | `wd logs --tail 200` (DEPLOY §6) |
| Self-check | `wd check all` (db · claude · smtp · providers) |
| Admin view | log in as an admin → 管理 (overview: spend, queue, provider quotas, events, health incl. `last_backup`) |

Log lines are JSON (`ts level logger msg request_id user_id method path status duration_ms job_id job_type worker
cost_usd provider event`). Useful filters: `journalctl -u word-dance -o cat | grep '"event":"budget'`,
`… | grep '"job_type":"lookup_word"'`, `… | grep '"status":5'`. Bodies and prompts are never logged.

## 2. Backups

**Automatic.** `word-dance-backup.timer` runs `wd backup --keep-daily 14 --keep-weekly 8` nightly at 03:30
Asia/Shanghai, independent of the application process (a wedged service still gets backed up). The pipeline:
`VACUUM INTO` a consistent online copy (safe under WAL while the service is serving) → `PRAGMA integrity_check` on
the copy → gzip → `backups/word-dance-YYYYMMDD-HHMM.db.gz` (0600; name in `WD_TZ` local time) → retention → the
admin health page shows `last_backup {file, at, bytes}` (`kv.backup.last`). A failure writes
`system_events('backup_failed')`, leaves no file behind and exits non-zero (visible in `systemctl status
word-dance-backup`).

**Retention.** The newest 14 snapshots are kept; among the older ones a Sunday copy per week is kept, up to 8 weeks;
everything else is deleted. `pre-migrate-*.db.gz` snapshots (taken by `wd migrate`, §4) are never pruned — delete
them by hand once an upgrade has proven itself. `--with-images` additionally writes `images-YYYYMMDD.tar` (same
retention); images are re-fetchable and not archived by default.

**Manual.** `make backup` or `wd backup --keep-daily 14 --keep-weekly 8` any time (the service may keep running).

**Verify a snapshot** (no service interaction):

```bash
gunzip -c /home/sqin/word-dance-data/backups/word-dance-20261014-0330.db.gz > /tmp/check.db
python3 -c "import sqlite3; c=sqlite3.connect('/tmp/check.db'); print(c.execute('PRAGMA integrity_check').fetchone()[0], c.execute('select count(*) from users').fetchone()[0])"
rm /tmp/check.db
```

**Off-box copies.** `backups/` is plain files; from any other machine with SSH access:

```bash
rsync -a --delete sqin@<box>:/home/sqin/word-dance-data/backups/ /backups/word-dance/      # cron, e.g. 04:30
```

(`.env` holds the secrets and is *not* in `backups/`; copy it once to a password manager — `WD_SECRET_KEY` only
protects unexpired e-mail codes, everything else is regenerable.)

**Monthly drill.** Restore the newest snapshot somewhere harmless and look at it:

```bash
D=/home/sqin/word-dance-data; L=$(ls -t $D/backups/word-dance-*.db.gz | head -1)
gunzip -c "$L" > $D/tmp/drill.db && wd check db --db $D/tmp/drill.db && rm $D/tmp/drill.db
```

## 3. Restore

`wd restore` replaces the live database. It refuses (exit 2) while the service runs — it checks the worker lease
in the database **and** `systemctl is-active word-dance.service` — and asks for confirmation unless `--yes`.

```bash
sudo systemctl stop word-dance
wd restore /home/sqin/word-dance-data/backups/word-dance-20261014-0330.db.gz --yes
sudo systemctl start word-dance
```

What happens: the archive is gunzipped into `tmp/` and `integrity_check`ed first (a bad archive changes nothing);
the current database is checkpointed and moved to `word-dance.db.bak-<ts>`, stale `-wal`/`-shm` files are removed,
the verified copy is put in place (0600). Delete the `.bak-*` file when you are sure. Images are untouched (a
restored database may reference images that were fetched later — they are simply re-fetched; or earlier — the
files stay in `images/` until `wd images-prune`).

## 4. Upgrade and rollback

```bash
cd /home/sqin/word-Dance && git pull && deploy/install.sh        # or: make install
```

`install.sh` is idempotent: it upgrades pip/npm dependencies, rebuilds the SPA, **stops the unit** (unless
`--no-restart`), runs `wd migrate` (which first writes `backups/pre-migrate-<from>-to-<to>.db.gz` when a migration is
pending), re-imports the seed only if the shipped file changed, starts the unit, and never touches `.env`, the
database or images. Downtime ≈ migration time + 3 s. In-flight jobs are recovered by the stale-lock sweep; a Claude
call in flight gets up to `TimeoutStopSec=300` to finish.

`--no-restart` keeps the service running while migrating — only for purely additive migrations (new tables,
columns, indexes; never `DROP`/`RENAME`/type changes). The script prints that reminder.

Rollback of the code: `git checkout <previous tag> && deploy/install.sh`. Rollback of a migration:

```bash
sudo systemctl stop word-dance
wd restore /home/sqin/word-dance-data/backups/pre-migrate-<from>-to-<to>.db.gz --yes
git checkout <previous tag> && deploy/install.sh
```

Dry runs: `deploy/install.sh --dry-run` prints every mutating step with a leading `+` and changes nothing;
`deploy/install.sh --help` lists the options (`--with-caddy DOMAIN`, `--with-nginx DOMAIN`, `--with-ecdict`,
`--no-restart`, `--contact-email ADDR`; any order).

## 5. Configuration changes

Edit `/home/sqin/word-dance-data/.env`, then `sudo systemctl restart word-dance`. The file is read by three parsers
(bash in `install.sh`, systemd `EnvironmentFile=`, python-dotenv in the CLI), so **every line is `KEY="value"`**
(single quotes only for a secret containing `$`, `` ` `` or `\`). `install.sh` validates the shape before sourcing
and aborts with the offending line; `deploy/env.example` documents every variable with its default (DEPLOY §4).
Secrets are masked in `GET /api/admin/config` and never logged.

Common edits: `WD_AI_DAILY_BUDGET_USD` (daily Claude cap), `WD_AI_SVG_DAILY_BUDGET_USD` (SVG concept cards),
`WD_REGISTRATION_MODE` (`open`/`invite`/`closed`), `WD_PUBLIC_URL` (base of e-mail/webhook links and an accepted
CSRF origin), SMTP (`WD_SMTP_*`), optional provider keys (`WD_PIXABAY_KEY`, `WD_PEXELS_KEY`, `WD_OPENVERSE_CLIENT_*`).

Rotating secrets: replace the value in `.env`, restart. Rotating `WD_SECRET_KEY` only invalidates unexpired
e-mail verification codes.

## 6. Runbook

| Situation | What you see | Action |
|---|---|---|
| Claude not logged in / token expired | admin banner 「Claude CLI 未登录」, `system_events claude_auth`, jobs stay queued, UI runs on dictionary data | `sudo -iu sqin claude` (interactive login) → `wd claude-check` (one probe call ≤ $0.05) → 管理 → AI 恢复 (`POST /api/admin/ai/pause {paused:false}`) if paused |
| Daily AI cap reached | `budget_daily` event; cards say 「今日 AI 额度已用完」; content jobs deferred to 00:05 `WD_TZ` | raise `WD_AI_DAILY_BUDGET_USD` in `.env` + restart, or wait for the next day |
| Many text-only cards (low photo hit rate) | overview `words.card_only` high vs `with_photo`/`with_claude_svg`; `budget_svg` event | raise `WD_AI_SVG_DAILY_BUDGET_USD` (≈ $0.028 per card) + restart; add a keyed provider; or register an Openverse app |
| Fresh install, nobody can log in | `GET /api/health` → `needs_setup:true`; login page says the first account becomes admin | open the site and register (first account = admin, no invite needed) — or `wd create-admin` on the box |
| Need more accounts in `invite` mode | registration page asks for a code | `wd invite --uses 5 --days 7` (printed once) or 管理 → 邀请码 |
| Openverse 429 | provider cooldown in the overview | nothing; Wikimedia continues; optionally register an Openverse app key |
| Disk low | admin health `disk_free_bytes` | `wd images-prune --unused-days 365` (cached files of words nobody studies), `claude-logs/` is pruned to 14 days automatically, trim `backups/` by hand, or move `WD_DATA_DIR` (stop → `mv` → edit `.env` + unit `EnvironmentFile` path → `install.sh`) |
| Service down for days | first tick builds **today's** batches only; `downtime` event; history shows 「服务器离线」 | nothing — missed days are not back-filled by design |
| A job is `dead` | 管理 → 任务 (or `GET /api/admin/jobs?status=dead`) with `last_error` | fix the cause (auth, budget, provider), then 重试 / `POST /api/admin/jobs/requeue-dead`; nightly maintenance requeues dead content/lookup jobs once |
| Second instance / stray CLI | log `lease_busy`; `wd worker-once` / `wd tick` / `wd restore` exit 2 「word-dance.service is running …」 | never drain the queue next to the service — watch `journalctl -u word-dance -f` or `GET /api/admin/jobs`; stop the service first if you really must |
| Restore needed | — | §3 |
| Flag tier fell back to 0 | `claude_probe_fallback` event | inspect the stderr excerpt in the event; upgrade the CLI or stay on tier 0 (fully functional) |
| Reverse proxy / HTTPS wanted later | — | `deploy/install.sh --with-caddy words.example.com` (sets `WD_HOST=127.0.0.1`, `WD_PUBLIC_URL`, `WD_TRUST_PROXY=1`) |

## 7. Optional ECDICT dictionary

`deploy/fetch_ecdict.sh /home/sqin/word-dance-data` (or `install.sh --with-ecdict`) downloads the 216 MB release
zip, verifies the pinned sha256, extracts `stardict.db` (851 MB) with `python3 -m zipfile`, installs it 0600 and
writes `WD_ECDICT_DB_PATH` into `.env` (restart afterwards). It exits 0 at once when the file already exists and
needs ≈ 1.1 GB free during extraction. Without it, words outside the seed are validated by Claude (`lookup_word`,
≈ 20 s debounce) instead of instantly.

## 8. Tests and smoke on the box

* `make test` — pytest + typecheck + vitest + vite build (no network, fake claude).
* `make smoke` — `scripts/smoke.py`: boots a throwaway instance (temporary data dir, port 8010, fake claude,
  mocked image providers, registration open) and walks the whole product: first registration → invite → onboarding
  → browse/mark → bank add → jobs → batch → every grade kind → master/restore/re-add → export/import → history →
  admin → logout. Safe next to the production service (different port and data dir). `--keep` keeps the data dir,
  `--port` changes the port.
* `make dev` — `scripts/dev.sh`: backend with auto-reload on :8000 + Vite on :5173 using `./.dev-data`;
  `WD_DEV_REAL_CLAUDE=1 make dev` uses the real CLI (spends money).

Real-Claude acceptance (≤ $0.20 total) and the delivery checks are manual: see [`qa.md`](qa.md).

## 9. Files and permissions

`WD_DATA_DIR` is 0700; `.env`, the database (+ `-wal`/`-shm`), images, backups and claude logs are 0600 — guaranteed
by `UMask=0077` in the units, `os.umask(0o077)` in `wd serve` and an explicit chmod in `wd migrate`/`wd backup`/`wd
restore`. Check with `ls -la /home/sqin/word-dance-data` (expect `drwx------`) and `stat -c %a
/home/sqin/word-dance-data/.env` (expect `600`). `git clean -fdx` in the checkout can never touch the data directory.

## 10. Known issues and deferred items (integration hand-over)

State at the end of TASKS post-steps 1–3 (late imports replaced, contract audit clean, `make test` + `make smoke` +
the P0 "migrate twice" and WP1 full-seed acceptance green). Left open deliberately:

**Manual acceptance still to run (post-steps 4–7, docs/qa.md)**

* Real-box deployment (`deploy/install.sh`, `systemctl is-active word-dance`, LAN `WD_PUBLIC_URL`, idempotent
  second run, `fetch_ecdict.sh` download, restore drill, data-dir permissions) — needs sudo/systemd; qa.md §A.
* Real-Claude acceptance (≤ $0.20: `wd claude-check`, three lookups incl. `recieve`/`GDP`, one 10-word prewarm) —
  spends money, so it was not run by the integrator; everything was verified against `backend/tests/fake_claude.py`.
  qa.md §C.
* Browser checklists `docs/qa-frontend.md` (WP7) and `docs/qa-study.md` (WP8) at 360 px / 1280 px; delivery check
  (qa.md §D) and the zh-CN copy pass (§E, post-step 7).

**Observed at integration**

* The one real provider run (`WD_IMAGE_PROVIDERS=wikimedia,openverse wd fetch-image abandon`) got **HTTP 503 from the
  Wikimedia Commons API** for every request from this box's egress IP (`216.228.127.131`) — a plain `curl` with a browser
  User-Agent received the same `503` / `retry-after: 52` HTML page, so it is not our request shape or UA. The quota layer
  recorded the Retry-After cooldown as designed and the chain fell through to **Openverse**, which delivered
  「"Abandoned Mansion, Beirut" by craigfinlay is licensed under CC BY 2.0」 (https://www.flickr.com/photos/71284091@N00/3180066090,
  800×536 JPEG, attribution stored). Re-run the command from the production box to confirm Commons answers from there.
* Pixabay / Pexels parsers are verified only against inline fixtures modelled on the public API docs (both providers
  are optional, keyed and off by default).
* `wd images-prune` has no worker-lease refusal: safe next to the live service, but it could race a fetch for a word
  that becomes studied in the same second.
* Every pytest run prints one `StarletteDeprecationWarning` from `fastapi/testclient.py` (httpx with
  `starlette.testclient` is deprecated) — harmless until the pins move.

**Behaviour notes (by design, recorded so nobody hunts for a bug)**

* A provisional (unknown) word keeps `display`/`kind` from `normalise_input` until `lookup_word` fills them — typing
  ` Abandoned ` for a string outside the seed gives display `Abandoned`, kind `proper_noun` until the lookup runs.
  Backend `normalise_input` and frontend `normalizeInput.ts` agree on the lemma; the server stays authoritative for the
  preview display.
* A `lookup_word` merge records `W.lemma → L` as an `alt` word form while the merged-away row keeps its lemma
  (`merged_into_word_id`), so the headword-guard invariant on a live database carries `AND w.merged_into_word_id IS
  NULL` (DESIGN §3.2).
* `POST /api/admin/jobs/run-once` answers 403 `forbidden` unless `WD_DEV=1`; the admin page shows the button only in
  dev mode.
* The register throttle (5/h per IP) also applies to the test client's IP: a test that registers more than five users
  on one app must advance the frozen clock or insert users directly.
* Onboarding screening card: Space reveals the translation through a window keydown handler; a focused button may
  additionally activate on keyup in some browsers (keys 1/2/S are unaffected).

**Deferred clean-ups (no behaviour change)**

* Frontend: WP8's date helpers live in `utils/srsPreview.ts` next to WP7's `utils/date.ts`; content polling is
  inlined in the study pages instead of `hooks/usePolling.ts`. Copy-pass candidates without their own `zh.ts` key:
  queued test e-mail toast (reuses 测试成功), validated add result shows 已识别 (spec 已校验), 重置进度 confirmation
  text, duplicate-line hint in the add-words preview, admin table headers (DTO field names), heat-strip tooltip,
  `i/n` card counter, 推荐词 认识 toast, WaitingPanel label.
* Tests: the full-seed acceptance (`backend/tests/unit/test_seed.py` + the `@full_seed` vocab test) is skipped by
  `make test`; run it after `wd import-seed` into a scratch data dir with
  `WD_FULL_SEED_DB=<that DB> PYTHONPATH=backend .venv/bin/pytest -q backend/tests -m full_seed`.
* Dev environment: always run the suite with `PYTHONPATH=backend` (what `make test` does). The venv's editable install
  maps `wd` to the main checkout, so a git worktree run without that variable imports the main checkout's modules.
