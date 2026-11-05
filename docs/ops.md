# word-Dance — operations runbook

Companion to [`DEPLOY.md`](DEPLOY.md) (what is installed and why). This file is the *what do I do now* document for
the person running the box. Paths are the defaults of DEPLOY §1: checkout `/home/sqin/word-Dance`, data directory
`/home/sqin/word-dance-data` (`WD_DATA_DIR`), service user `sqin`, CLI `/home/sqin/word-Dance/.venv/bin/wd`
(`wd …` below). Every `wd` command reads `$WD_DATA_DIR/.env` itself, so it works from any shell as `sqin` — with
`WD_DATA_DIR` exported in that shell once the data directory has been moved (§5): the CLI defaults to
`/home/sqin/word-dance-data`, while `install.sh` follows the installed unit (§4).

## 1. Daily checks

| What | Command |
|---|---|
| Service state | `systemctl status word-dance` · `systemctl is-active word-dance` |
| Backup timer | `systemctl list-timers word-dance-backup.timer` (next run 03:30 Asia/Shanghai, randomised ≤ 10 min) |
| Liveness | `curl -fsS http://127.0.0.1:8000/api/health` → `{"status":"ok","needs_setup":false,…}` |
| Live log | `journalctl -u word-dance -f` · `journalctl -u word-dance --since today -p warning` |
| Last 200 log lines | `journalctl -u word-dance -n 200 -o cat` (JSON lines, DEPLOY §6). `wd logs --tail N` is **not** this: it tails `WD_LOG_FILE` when that is set (empty by default) and otherwise prints only a hint, because the 2000-line ring buffer it reads lives inside the `wd serve` process |
| Self-check | `wd check all` (db · claude · smtp · providers). `wd check db` also prints the stage-model invariants `stage_min_consistent` / `xs_subset_zk` / `stages_json_known` / `seed_version_matches_file` — `ok` or `N violation(s)`; any violation → `[FAIL] db`, exit 1 (`json_each` is built into SQLite ≥ 3.38; an older build prints `query failed` for the third line, which is reported but not counted) |
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

What happens: the archive is gunzipped to `word-dance.db.restore-<ts>` next to the database and `integrity_check`ed
first (a bad archive changes nothing); the current database is checkpointed — **restore also refuses (exit 2) while
any other connection holds an open transaction on it** (a forgotten `BEGIN;` in a `sqlite3` shell, a DB browser, a
long `wd stats`/`wd check`): SQLite then cannot fold the WAL and the `.bak` would silently miss the newest commits —
then kept as `word-dance.db.bak-<ts>` (a hard link, so no extra space), its `-wal`/`-shm` files move next to it
(`.bak-<ts>-wal`/`-shm`; SQLite recovers them when the `.bak` is opened, so the kept copy is complete even when the
checkpoint failed on a damaged file), and the verified copy is swapped in with one atomic rename (0600) — the
database path is never absent, and a failed swap leaves the current database untouched. The `.bak` is complete only
when `wd restore` printed `previous database kept at …`; delete the `.bak-*` files when you are sure. Images are
untouched (a restored database may reference images that were fetched later — they are simply re-fetched; or
earlier — the files stay in `images/` until `wd images-prune`).

## 4. Upgrade and rollback

```bash
cd /home/sqin/word-Dance && git pull && deploy/install.sh        # or: make install
```

`install.sh` is idempotent: it upgrades pip/npm dependencies, builds the SPA into a new snapshot
`/home/sqin/word-dance-data/frontend-releases/<sha>.new`, **stops the unit** (unless `--no-restart`), publishes that
snapshot (`<sha>.new` → `<sha>`, then the `frontend` symlink is replaced with one atomic rename; the two newest
snapshots are kept), runs `wd migrate` (which first writes `backups/pre-migrate-<from>-to-<to>.db.gz` when a migration
is pending), re-imports the seed only if the shipped file changed, starts the unit, and never touches `.env` (beyond
filling an empty `WD_PUBLIC_URL` / `WD_FRONTEND_DIST` once), the database or images. Downtime ≈ migration time + 3 s.
In-flight jobs are recovered by the stale-lock sweep; a Claude call in flight gets up to `TimeoutStopSec=300` to finish.

The service serves `WD_FRONTEND_DIST=/home/sqin/word-dance-data/frontend` (DEPLOY §1/§4), never `<repo>/frontend/dist`:
`make test` / `npm run build` in the checkout (§8) write `frontend/dist` and leave the live UI alone, and a browser tab
keeps finding its lazy chunks until the next publish + restart. `wd serve` resolves the symlink when it starts, so after
`--no-restart` (or without passwordless sudo) the old process keeps its old snapshot until you restart it.

**If the data directory was moved (§5), every `deploy/install.sh` / `make install` in this section — upgrade, code
rollback, migration rollback — keeps working as written**: when `WD_DATA_DIR` is unset the script takes the data
directory from the installed unit (`EnvironmentFile=<dir>/.env` in `/etc/systemd/system/word-dance.service`) and prints
`data dir from the installed unit: <dir>`. `WD_DATA_DIR=<dir>` in the environment (the profile export of §5) is fine as
long as it names that same directory; a **different** value is refused with exit 2 before anything is changed
(`ERROR: WD_DATA_DIR=… but the installed unit (…) uses …`) — a stale export or a typo can no longer build a second,
empty instance next to the real one. Only the move itself (§5) passes a new directory, with `--move-data`.

`--no-restart` keeps the service running while migrating — only for purely additive migrations (new tables,
columns, indexes; never `DROP`/`RENAME`/type changes). The script prints that reminder. `0011_primary_stage.sql` and
`0013_word_forms_alias.sql` (the K-12 release, `docs/releases/2026-11-k12-stages.md`) are table rebuilds — stop-first,
never `--no-restart`; `0012_word_images_meta.sql` is additive. Rehearse before the real run: copy the database to a
private directory and `.venv/bin/python -I scripts/rehearse_migration.py <copy>` (applies the pending files through the
real runner and exits 0 only when every check of the release note passes — SQLite ≥ 3.26 on the box), then
`wd check db` after the upgrade for the four stage invariants. Database and code roll back **together** for that
release (the pre-migrate snapshot + `git checkout`); the Mac launchd instance follows the same order — backup → stop →
switch → start — spelled out in the release note. Without passwordless
`sudo -n` the script cannot stop or restart the unit either: it prints the same NOTE plus `WARN: no passwordless
sudo — the OLD version keeps serving …`, and its last line is `health OK, but the OLD process answered — … run: sudo
systemctl restart word-dance` instead of a success message — run that restart yourself (or stop the unit before
re-running the script when a migration is not additive).

Rollback of the code: `git checkout <previous tag> && deploy/install.sh`. Rollback of a migration:

```bash
sudo systemctl stop word-dance
wd restore /home/sqin/word-dance-data/backups/pre-migrate-<from>-to-<to>.db.gz --yes
git checkout <previous tag> && deploy/install.sh
```

Rollback of the UI alone (a bad build, API unchanged — the previous snapshot is still there):

```bash
ls -1t /home/sqin/word-dance-data/frontend-releases                     # newest first; the second entry is the previous release
cd /home/sqin/word-dance-data && ln -sfn frontend-releases/<previous> frontend.tmp && mv -T frontend.tmp frontend
sudo systemctl restart word-dance                                       # wd serve resolves the symlink at startup
```

Dry runs: `deploy/install.sh --dry-run` prints every mutating step with a leading `+` and changes nothing;
`deploy/install.sh --help` lists the options (`--with-caddy DOMAIN`, `--with-nginx DOMAIN`, `--with-ecdict`,
`--no-restart`, `--contact-email ADDR`, `--move-data`; any order) and the data-directory rule.

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

**Moving the data directory** (a bigger disk — the 「Disk low」 row of §6). `install.sh` resolves the data directory in
step 0 (DEPLOY §2, read-only, also under `--dry-run`): the `WD_DATA_DIR` environment variable when set, otherwise the
directory in the installed unit's `EnvironmentFile=` line (`/etc/systemd/system/word-dance.service`), otherwise
`/home/sqin/word-dance-data`. Step 7 re-renders **both** units from that value (`EnvironmentFile=__DATA__/.env` in
`word-dance.service` and `word-dance-backup.service`), so the units are never edited by hand — an edit would be
overwritten. Because the installed unit still names the old directory, the script refuses a `WD_DATA_DIR` that differs
from it (exit 2, nothing changed) unless you say the move is intended with `--move-data`; the flag prints a `WARN` and
lets step 7 point both units at the new directory. (Before this guard a plain run after a move built a **second, empty
instance** at the default path — fresh `.env`, empty seeded database, units re-pointed at it, site answering
`needs_setup:true` — while the real data sat unused; now a plain run follows the unit and a wrong variable is refused.)
The sequence:

```bash
NEW=/data/word-dance                                            # the new location; keeps its 0700 mode through mv
sudo systemctl stop word-dance
mv /home/sqin/word-dance-data "$NEW"
sed -i "s|^WD_DATA_DIR=.*|WD_DATA_DIR=\"$NEW\"|" "$NEW/.env"      # install.sh sources .env AFTER resolving the data dir: a stale line here
                                                                # would send wd migrate / import-seed back to the old path
grep -n '/home/sqin/word-dance-data' "$NEW/.env" || true        # fix any other absolute path under the old directory the same way
                                                                # (WD_DB_PATH, WD_CLAUDE_CWD, WD_ECDICT_DB_PATH, WD_LOG_FILE)
WD_DATA_DIR="$NEW" deploy/install.sh --move-data                # WARN, then re-renders both units with EnvironmentFile=$NEW/.env, migrates nothing, restarts
echo "export WD_DATA_DIR=\"$NEW\"" >> ~/.profile                # every later `wd …` (the CLI, not install.sh) defaults to the old path
```

From then on a plain `deploy/install.sh` / `make install` (§4) follows the unit (`data dir from the installed unit:
$NEW`); the profile export above (new login shells, `sudo -iu sqin`) is for the `wd` CLI and is accepted by install.sh
because it names the same directory. A forgotten or stale `WD_DATA_DIR` can no longer create a second instance: a value
other than `$NEW` is refused with `ERROR: WD_DATA_DIR=… but the installed unit (…) uses $NEW` — fix the variable, do not
reach for `--move-data`. If an older script version did build a second instance at `/home/sqin/word-dance-data`:
`sudo systemctl stop word-dance`, confirm that directory is the fresh install (created minutes ago, no
`backups/word-dance-*.db.gz`), remove it, and run `WD_DATA_DIR=$NEW deploy/install.sh --move-data`. Nothing is lost in
that scenario — the moved directory is untouched.

## 6. Runbook

| Situation | What you see | Action |
|---|---|---|
| Claude not logged in / token expired | admin banner 「Claude CLI 未登录」, `system_events claude_auth`, CLI paused for `WD_AI_FAILOVER_COOLDOWN_MIN`; mode `claude_cli` — or `auto` while no provider can take the kind (fallback unconfigured / paused / marked `'0'`, or the kind removed from `WD_AI_FALLBACK_KINDS`): jobs stay queued, UI runs on dictionary data; mode `auto` with a usable fallback: lookups, consolidates and ordinary content groups rerun on the fallback at once (`ai_failover` event; prewarm groups and `svg` keep waiting for the CLI, DEPLOY §11) | `sudo -iu sqin claude` (interactive login) → `wd claude-check` (one probe call ≤ $0.05; a successful probe lifts the pause, fails back and requeues the content / lookup jobs that died during the outage, CLAUDE_INTEGRATION §10.6) → 管理 → AI 恢复 (`POST /api/admin/ai/pause {paused:false}`) only if the admin pause is set |
| Daily AI cap reached | `budget_daily` event; cards say 「今日 AI 额度已用完」; content jobs deferred to 00:05 `WD_TZ` | raise `WD_AI_DAILY_BUDGET_USD` in `.env` + restart, or wait for the next day |
| Many text-only cards (low photo hit rate) | overview `words.card_only` high vs `with_photo`/`with_claude_svg`; `budget_svg` event | raise `WD_AI_SVG_DAILY_BUDGET_USD` (≈ $0.0124 per call, $0.014 per delivered card) + restart; add a keyed provider; register an Openverse app; `wd images-retry --dry-run` lists the failed words of active learners the 03:30 maintenance will re-fetch by itself (`failed` for ≥ 6 h, ≤ 3 automatic retries per 30 days, ≤ 50 per night; `wd images-retry` without the flag enqueues them now). Function words (`of`, `despite` …) are card-only by design and never retried; the admin's `refetch-image` with a `provider` or `query` (e.g. `{provider:"claude_svg"}`) still works per word, while 换一张 and a `refetch-image` without either carry no override, so the gate applies and the current card/image is kept |
| Fresh install, nobody can log in | `GET /api/health` → `needs_setup:true`; login page says the first account becomes admin | open the site and register (first account = admin, no invite needed) — or `wd create-admin` on the box |
| Need more accounts in `invite` mode | registration page asks for a code | `wd invite --uses 5 --days 7` (printed once) or 管理 → 邀请码 |
| Openverse 429 | provider cooldown in the overview | nothing; Wikimedia continues; optionally register an Openverse app key |
| Disk low | admin health `disk_free_bytes` | `wd images-prune --unused-days 365` (cached files of words nobody studies — never while a 预生成/prewarm plan is running, and note that the nightly retry re-fetches a studied word's failed image, so pruning only ever costs a re-download), `claude-logs/` is pruned to 14 days automatically, trim `backups/` by hand, or move the data directory to a bigger disk — the §5 procedure: stop → `mv` → fix `WD_DATA_DIR=` in the moved `.env` → `WD_DATA_DIR=<new> deploy/install.sh --move-data` (without the flag a differing `WD_DATA_DIR` is refused; never a hand-edited unit; later upgrades follow the unit by themselves) |
| Service down for days | first tick builds **today's** batches only (back *before* a user's push time → built in the normal window, published + delivered at push time; back *after* it → published at once, e-mail/webhook `skipped` when > 6 h late); `downtime` event; history shows 「服务器离线」 | nothing — missed days are not back-filled by design |
| A job is `dead` | 管理 → 任务 (or `GET /api/admin/jobs?status=dead`) with `last_error` | fix the cause (auth, budget, provider), then 重试 / `POST /api/admin/jobs/requeue-dead`; nightly maintenance requeues dead content/lookup jobs once |
| Second instance / stray CLI | log `lease_busy`; `wd worker-once` / `wd tick` / `wd restore` exit 2 「word-dance.service is running …」 | never drain the queue next to the service — watch `journalctl -u word-dance -f` or `GET /api/admin/jobs`; stop the service first if you really must. A `lease_busy` right after a crash restart is normal: the service retries every 30 s and logs `lease_acquired` once the dead instance's 90-s lease expires |
| Service lost the worker lease (log `lease_lost` / `lease_fenced`) | its renewals lapsed > 90 s (stall, paused VM) and another instance took the lease; the losing process keeps serving requests but claims no jobs and sweeps nothing until `lease_reacquired` / `lease_resumed` | stop the extra instance (`ps -ef | grep 'wd serve'`); the fenced service re-acquires within 30 s on its own — no restart needed |
| Restore needed | — | §3 |
| Flag tier fell back to 0 | `claude_probe_fallback` event | inspect the stderr excerpt in the event; upgrade the CLI or stay on tier 0 (fully functional) |
| Reverse proxy / HTTPS wanted later | — | `deploy/install.sh --with-caddy words.example.com` (sets `WD_HOST=127.0.0.1`, `WD_PUBLIC_URL`, `WD_TRUST_PROXY=1`) |
| UI stale or mixed after an upgrade (old pages, lazy chunk imports failing, 「前端尚未构建」) | `readlink /home/sqin/word-dance-data/frontend` does not name the snapshot the last `deploy/install.sh` printed (`==> frontend publish: …`), or the service was not restarted after it (`--no-restart`, no passwordless sudo — `wd serve` resolves the symlink at startup) | `sudo systemctl restart word-dance`, reload the tab. Symlink missing, or `.env` still has `WD_FRONTEND_DIST=""` → re-run `deploy/install.sh` (fills the value, publishes the snapshot, §4). Bad build → the UI rollback in §4 |

## 7. Optional ECDICT dictionary

`deploy/fetch_ecdict.sh /home/sqin/word-dance-data` (or `install.sh --with-ecdict`) downloads the 216 MB release
zip, verifies the pinned sha256, extracts `stardict.db` (851 MB) with `python3 -m zipfile`, installs it 0600 and
writes `WD_ECDICT_DB_PATH` into `.env` (restart afterwards). It exits 0 at once when the file already exists and
needs ≈ 1.1 GB free during extraction. Without it, words outside the seed are validated by Claude (`lookup_word`,
≈ 20 s debounce) instead of instantly.

## 8. Tests and smoke on the box

* `make test` — pytest + typecheck + vitest + vite build (no network, fake claude). The vite build writes
  `frontend/dist`, which the installed service does not serve (it serves the snapshot behind
  `/home/sqin/word-dance-data/frontend`, §4), so the gate is safe to run in the production checkout.
* `make smoke` — `scripts/smoke.py`: boots a throwaway instance (temporary data dir, port 8010, fake claude,
  mocked image providers, registration open) and walks the whole product: first registration → invite → onboarding
  → browse/mark → bank add → jobs → batch → every grade kind → master/restore/re-add → export/import → history →
  admin → logout. Safe next to the production service (different port and data dir) and offline: the script sets
  `WD_SMOKE_MOCK_HTTP=1` + `WD_DEV=1` for the server **and** for every `wd` subprocess it spawns (`wd worker-once`,
  `wd tick --once`), which `wd.cli.main` honours like `create_app` does, so Wikimedia/Openverse searches and image
  downloads are answered from `backend/tests/fixtures` (`wd.smoke_mock`) and nothing leaves the box. `--keep`
  keeps the data dir, `--port` changes the port.
* `make dev` — `scripts/dev.sh`: backend with auto-reload on :8000 + Vite on :5173 using `./.dev-data`;
  `WD_DEV_REAL_CLAUDE=1 make dev` uses the real CLI (spends money). Vite binds `localhost` only (`::1` on this box):
  open `http://localhost:5173`, not `127.0.0.1:5173`; a phone on the LAN cannot reach it — run
  `cd frontend && npm run dev -- --host` for the 360-px checks (then `http://<LAN-ip>:5173`), or use the built SPA
  of the installed service on `http://<LAN-ip>:8000`.

Real-Claude acceptance (≤ $0.20 total) and the delivery checks are manual: see [`qa.md`](qa.md).

## 9. Files and permissions

`WD_DATA_DIR` is 0700; `.env`, the database (+ `-wal`/`-shm`), images, backups and claude logs are 0600 — guaranteed
by `UMask=0077` in the units, `os.umask(0o077)` in `wd serve` and an explicit chmod in `wd migrate`/`wd backup`/`wd
restore`. Check with `ls -la /home/sqin/word-dance-data` (expect `drwx------`) and `stat -c %a
/home/sqin/word-dance-data/.env` (expect `600`). `frontend-releases/` (the SPA snapshots, §4) is 0700 as well; the files
inside keep the build's modes — static assets, private through the parent directory and served by the same user.
`git clean -fdx` in the checkout can never touch the data directory.

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
  **2026-10-28:** the deployed instance fetched 27 Wikimedia Commons photos with attribution for its first batch without
  a single 503, so the earlier 503 was transient egress throttling, not a block of this box; the Retry-After cooldown and
  the fall-through to Openverse described above remain the behaviour when it happens again.
* Pixabay / Pexels parsers are verified only against inline fixtures modelled on the public API docs (both providers
  are optional, keyed and off by default).
* `wd images-prune` has no worker-lease refusal: safe next to the live service, but it could race a fetch for a word
  that becomes studied in the same second.
* starlette 1.8 / fastapi 0.143 emit a `StarletteDeprecationWarning` (httpx with `starlette.testclient` is deprecated)
  while `conftest.py` imports `TestClient`; `backend/pyproject.toml` filters that message, so `pytest` ends without a
  warnings summary. Drop the filter once the pins move (or `httpx2` is added).

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
* Screening / study keyboard shortcuts go through `hooks/useKeyboard` (also on the onboarding card since the
  fix(frontend) commit): auto-repeat keydowns are dropped (a held `1` judges one card), and Space yields to a focused
  `<button>`/`<summary>` so the native activation still happens (Chrome suppresses the click when that keydown is
  cancelled; keys 1/2/S never activate buttons and keep working there). Button / swipe verdicts are ignored for
  250 ms after a card advanced (`hooks/useTapLock`), so a double tap cannot judge the next card.

**Deferred clean-ups (no behaviour change)**

* Frontend: WP8's date helpers live in `utils/srsPreview.ts` next to WP7's `utils/date.ts`; content polling is
  inlined in the study pages instead of `hooks/usePolling.ts`. Copy-pass candidate without its own `zh.ts` key:
  WaitingPanel label (the queued test e-mail toast, validated add result, reset / remove confirmations, duplicate-line
  hint, admin labels, heat-strip tooltip, card counter and the 推荐词 认识 toast received keys in the fix(frontend)
  commit, ratified in FRONTEND §8).
* Tests: the full-seed acceptance (`backend/tests/unit/test_seed.py` + the `@full_seed` vocab test) is skipped by
  `make test`; run it after `wd import-seed` into a scratch data dir with
  `WD_FULL_SEED_DB=<that DB> PYTHONPATH=backend .venv/bin/pytest -q backend/tests -m full_seed`.
* Dev environment: always run the suite with `PYTHONPATH=backend` (what `make test` does). The venv's editable install
  maps `wd` to the main checkout, so a git worktree run without that variable imports the main checkout's modules.
