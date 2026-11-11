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
| Self-check | `wd check all` (db · claude · smtp · providers). `wd check db` also prints the stage-model invariants `stage_min_consistent` / `xs_subset_zk` / `stages_json_known` / `seed_version_matches_file` and, from schema 14, the learning-order invariants `learn_rank_present` / `learn_order_current` / `learn_rank_matches_policy` / `calendar_words_in_xs` (`docs/releases/2026-11-learn-order.md`; one command repairs the first three: `wd learn-order`) — `ok` or `N violation(s)`; any violation → `[FAIL] db`, exit 1 (`json_each` is built into SQLite ≥ 3.38; an older build prints `query failed` for the third line, which is reported but not counted) |
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
`0013_word_forms_alias.sql` (the K-12 release, `docs/releases/2026-11-k12-stages.md`) and `0016_word_dances.sql` (the 单词之舞 P2 release,
`docs/releases/2026-11-word-dance-p2.md`: `jobs` / `ai_calls` rebuilt for the new job type, `word_dances` added) are table rebuilds — stop-first,
never `--no-restart`; `0012_word_images_meta.sql` and `0014_learn_rank.sql` (the learning-order release,
`docs/releases/2026-11-learn-order.md`: one `ADD COLUMN` on `words`, filled at the next service start or by the `wd learn-order`
step install.sh runs after `import-seed`) and `0015_dance_mode.sql` (the 单词之舞 release,
`docs/releases/2026-11-word-dance-p1.md`: one `ADD COLUMN` on `user_settings` with its default) and `0017_word_dances_corrected.sql` (the 单词之舞 P3b release,
`docs/releases/2026-11-word-dance-p3b.md`: one nullable `ADD COLUMN` on `word_dances`, filled by
`wd.dance.backfill_corrected` at the next service start) and `0018_auth_identities.sql` (the sign-up release,
`docs/releases/2026-11-auth-signup-1a.md`: two new tables `identities` / `login_codes`, nullable columns on `users` and
`sessions`, one backfill `UPDATE users SET password_set_at = created_at`) and `0019_family.sql` (the guardian + child release,
`docs/releases/2026-11-auth-signup-1b.md`: the `family_codes` table, `users.profile_prompted_at`, `sessions.guardian_gate_at`; no data
step) are additive. Rehearse before the real run: copy the database to a
private directory and `.venv/bin/python -I scripts/rehearse_migration.py <copy>` (applies the pending files through the
real runner and exits 0 only when every check of the release note passes — SQLite ≥ 3.26 on the box), then
`wd check db` after the upgrade for the eight invariants (the four stage-model lines and, from schema 14, the four
learning-order lines). Database and code roll back **together** for the K-12
release (the pre-migrate snapshot + `git checkout`); the Mac launchd instance follows the same order — backup → stop →
switch → start — spelled out in the release note; the learning-order release (0014) rolls back by `git checkout` alone — the
old code never reads `learn_rank`, the column and its `kv.learn_order.*` stamps stay and are harmless. Without passwordless
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

**Real-time generation on the domestic model** (`WD_AI_PROVIDER="split"`, `docs/releases/2026-11-ai-split.md`): the learners' kinds — a custom word's lookup, a card requested at study time, the nightly consolidation — run on the fallback, the operator's pre-generation (prewarm content, SVG cards, dance annotations) on the Claude CLI, and neither side ever takes the other's work. Needs the fallback fully configured: `WD_AI_FALLBACK_KIND="openai_http"`, `WD_AI_FALLBACK_BASE_URL="https://open.bigmodel.cn/api/paas/v4"`, `WD_AI_FALLBACK_MODEL="glm-4.7-flash"`, `WD_AI_FALLBACK_DIALECT="zhipu"`, the key in a 0600 file named by `WD_AI_FALLBACK_API_KEY_FILE` (never in `.env`); then `wd ai-check --provider fallback` (exact-match probe), the AI_FALLBACK_MODEL §5 eval if content quality is in doubt, set `WD_AI_PROVIDER="split"`, restart (the startup log event `ai_provider_mode` names the mode and the fallback). A paused fallback (event `ai_fallback_paused` after a 401 / balance / 1308 quota window, `ai_fallback_quality` after three unusable answers; the admins get the `fallback_paused` / `fallback_quality` webhook) means the learners' jobs wait for it — a custom word stays 「待 AI 校验」, a card request shows 「今日 AI 额度已用完，例句将在明天补齐」 until the pause ends; a configuration failure (404 / unknown model / missing key) pauses it for the cooldown, marks it unavailable (`ai.fallback.available=0`, `wd check` shows it) and alerts once with that state named; afterwards — and after a failed `wd ai-check --provider fallback`, which marks silently — the jobs are re-deferred every 30 minutes without further alerts until the configuration is fixed and `wd ai-check --provider fallback` (or the admin's 探测 / 恢复) lifts the mark. Raise `WD_AI_FALLBACK_HOURLY_CALL_CAP` (default 40) if lookups and cards of several learners hit it. In this mode a learner's action queues no SVG card and no dance annotation (template card and rule dance serve; `wd dance-annotate` and the admin's `claude_svg` request still run on the CLI), and the admin's 重新生成 / manual 整理 follow the learners' lane. Back to `claude_cli` or `auto` is one edit + restart; if the fallback was paused at that moment press 恢复 or wait the pause out.

**Pronunciation clips on a Linux host** (no `say`). The licensed way — and the only one for a public deployment, since the macOS `say` voices are personal and non-commercial — is the cloud provider: `WD_AUDIO_PROVIDER="bailian"` with `WD_BAILIAN_API_KEY_FILE` (a 0600 file holding the 百炼 API key), `WD_BAILIAN_WORKSPACE_ID` and, if not the defaults, `WD_BAILIAN_REGION` / `WD_BAILIAN_TTS_MODEL` / `WD_BAILIAN_TTS_VOICES` (DEPLOY §4), restart, `wd check providers` (the `audio:` / `bailian:` lines), `WD_DATA_DIR=… wd audio-probe` (one real clip — the day-0 check of the key), then `… wd audio-prewarm --dry-run` (the plan prices the run: ≈ ¥1 per 10 000 characters, ≈ ¥115 for the whole library) and `… wd audio-prewarm --purge-others` to replace the `say` clips; the server then synthesises every later text on demand and the mirror below is optional. Without a 百炼 account, the mirror: set `WD_AUDIO_PROVIDER="cache"` and `WD_AUDIO_CACHE_VOICES="en-US=Ava (Premium);en-GB=Serena (Premium)"` (the pair `wd audio-voices` prints on the Mac), restart, and keep `audio/` mirrored from the Mac. The loop, nightly from a cron on the Mac: `ssh server /path/to/.venv/bin/wd audio-texts > texts.txt` (the server's study path, one text per line, the count on stderr; `--stage xs` adds a stage's headwords) → `WD_DATA_DIR=/Users/sqin/word-dance-data /Users/sqin/word-dance/.venv/bin/wd audio-prewarm --texts texts.txt` (both accents; only the missing clips are made) → `rsync -a --no-owner --no-group --exclude='*.tmp*' --exclude='*.aiff' ~/word-dance-data/audio/ server:/home/sqin/word-dance-data/audio/` (no `--delete` in the nightly run: the server never writes its own clips in this mode, and a mirrored clip is served as it is — `WD_AUDIO_CACHE_MB` is not enforced there, nothing is touched or pruned; the Mac's cap and the rsync decide what exists). A text the server has no clip for answers 503 `{reason:"missing"}` (log event `audio_clip_missing` at INFO, no budget spent — their count since the last sync is the signal to run the loop early): a browser that still has `speechSynthesis` (it had no English voice, which is why it asked the server) speaks it with its default voice meanwhile, the tablet App shows 「这条发音还没有生成，请稍后再试」 until the next sync. Changing the voice, without a gap on the server: download it on the Mac → restart the Mac service (its log event `audio_voice` names it; `wd audio-voices` prints the new pair) → Mac `wd audio-prewarm --purge-others` → the loop once without `--delete` (the new voice's clips land next to the old ones) → server `.env` `WD_AUDIO_CACHE_VOICES` = the new pair + restart → one rsync with `--delete` so the old voice's files leave the mirror. `wd audio-prewarm` itself refuses to run on the server in this mode; deleting the server's `audio/` means `missing` for everything until the next sync.

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
| Many text-only cards (low photo hit rate) | overview `words.card_only` high vs `with_photo`/`with_claude_svg`; `budget_svg` event | raise `WD_AI_SVG_DAILY_BUDGET_USD` (≈ $0.0124 per call, $0.014 per delivered card) + restart; add a keyed provider; register an Openverse app; `wd images-retry --dry-run` lists the failed words of active learners the 03:30 maintenance will re-fetch by itself (`failed` for ≥ 6 h, ≤ 3 automatic retries per 30 days, ≤ 50 per night; `wd images-retry` without the flag enqueues them now). Function words (`of`, `despite` …) are card-only by design and never retried; the admin's `refetch-image` with a `provider` or `query` (e.g. `{provider:"claude_svg"}`) still works per word, while 换一张 and a `refetch-image` without either carry no override, so the gate applies and the current card/image is kept. After a provider outage (`wd check providers` shows `wikimedia … errors=N cooldown_until=…` with a `ConnectError` / `SSL` last_error, or the day counter hit `WD_WIKIMEDIA_DAILY_LIMIT`), every word fetched meanwhile was marked `failed` without a usable provider request: once Wikimedia answers again, out of cooldown and with quota left, `wd images-retry --since <outage start ISO> --limit 100` requeues them library-wide (Wikimedia only, no SVG, no retry flag), one round of ≤ 100 at a time so a relapse mid-round costs few words — a word fetched twice in the window is never swept again |
| Fresh install, nobody can log in | `GET /api/health` → `needs_setup:true`; login page says the first account becomes admin | open the site and register (first account = admin, no invite needed) — or `wd create-admin` on the box |
| Need more accounts in `invite` mode | registration page asks for a code | `wd invite --uses 5 --days 7` (printed once) or 管理 → 邀请码 |
| Openverse 429 | provider cooldown in the overview | nothing; Wikimedia continues; optionally register an Openverse app key |
| Disk low | admin health `disk_free_bytes` | `wd images-prune --unused-days 365` (cached files of words nobody studies — never while a 预生成/prewarm plan is running, and note that the nightly retry re-fetches a studied word's failed image, so pruning only ever costs a re-download), `claude-logs/` is pruned to 14 days automatically, trim `backups/` by hand, or move the data directory to a bigger disk — the §5 procedure: stop → `mv` → fix `WD_DATA_DIR=` in the moved `.env` → `WD_DATA_DIR=<new> deploy/install.sh --move-data` (without the flag a differing `WD_DATA_DIR` is refused; never a hand-edited unit; later upgrades follow the unit by themselves) |
| Service down for days | first tick builds **today's** batches only (back *before* a user's push time → built in the normal window, published + delivered at push time; back *after* it → published at once, e-mail/webhook `skipped` when > 6 h late); `downtime` event; history shows 「服务器离线」 | nothing — missed days are not back-filled by design |
| A job is `dead` | 管理 → 任务 (or `GET /api/admin/jobs?status=dead`) with `last_error` | fix the cause (auth, budget, provider), then 重试 / `POST /api/admin/jobs/requeue-dead`; nightly maintenance requeues dead content/lookup jobs once |
| Second instance / stray CLI | log `lease_busy`; `wd worker-once` / `wd tick` / `wd restore` exit 2 「word-dance.service is running …」 | never drain the queue next to the service — watch `journalctl -u word-dance -f` or `GET /api/admin/jobs`; stop the service first if you really must. A `lease_busy` right after a crash restart is normal: the service retries every 30 s and logs `lease_acquired` once the dead instance's 90-s lease expires |
| Service lost the worker lease (log `lease_lost` / `lease_fenced`) | its renewals lapsed > 90 s (stall, paused VM) and another instance took the lease; the losing process keeps serving requests but claims no jobs and sweeps nothing until `lease_reacquired` / `lease_resumed` | stop the extra instance (`ps -ef | grep 'wd serve'`); the fenced service re-acquires within 30 s on its own — no restart needed |
| 发音 has no sound in the App / on a phone; toast 「这台设备没有英文语音，服务器也没有配置发音…」 | the device has no English TTS (Android's WebView, the Android container of HarmonyOS NEXT — the family's Huawei tablet —, many domestic ROMs) **and** the server has no provider: `WD_AUDIO_PROVIDER` resolves to `off` (a Linux host without an explicit provider — `audio:false` in `GET /api/auth/me`, so the client never even asks; or the provider was switched off since the page loaded and `GET /media/audio` answered 503 `{reason:"off"}`) | set `WD_AUDIO_PROVIDER="say"` (macOS host), `"cache"` (a Linux host mirroring the Mac's clips, with `WD_AUDIO_CACHE_VOICES` — §5) or `"youdao"` in `.env` + restart; the startup log event `audio_provider` shows what is in force, `ls $WD_DATA_DIR/audio` fills as words are played (or as the §5 sync runs). The other toasts name their cause: 「发音服务器正忙，请稍后再试」 = the two synthesis slots or the 60 misses / minute budget (429); 「服务器暂时无法生成这条发音，请稍后再试」 = a provider error — `audio_unavailable` events in the log say which (no English voice `say` resolves, a `WD_AUDIO_SAY_VOICE` `say` does not know, `afconvert` failure, Youdao answered something that is not audio); 「这段文字无法发音」 = the server refused the text (400); 「发音音频无法播放」 = the device could not decode the clip; 「发音加载失败，请检查网络后再试」 = the clip could not be fetched at all; 「这条发音还没有生成，请稍后再试」 = `cache` mode and the clip is not in the mirror yet (event `audio_clip_missing`) — run the §5 loop |
| 发音 waits half a second to three seconds at the first tap of a word; or a better voice was downloaded and should take over | every new text is synthesised at its first tap (0.5–1 s per word or sentence with `say`), and the voice probes (1–3 s) used to run at the first tap after a start — now at startup; a downloaded voice is only picked up by a restart, and the old voice's clips stay cached under their own keys | `WD_DATA_DIR=… wd audio-voices` (the installed voices of the preference lists, what resolves, the choice per accent) → restart (grep the log for `audio_voice`, one line per accent; `audio_voice_failed` = no voice resolved) → `WD_DATA_DIR=… wd audio-prewarm --dry-run` then `… wd audio-prewarm --purge-others` (the headwords with content or in a bank and their example sentences in learning order — `--stage xs` adds a stage's headwords —; the purge drops the old voice's clips and needs the restart first) — safe next to the live service, DEPLOY §9 |
| 发音片段 503 `busy` / `failed` with `WD_AUDIO_PROVIDER=bailian`; the log's `audio_unavailable` detail starts with `bailian …`; the App shows 「发音服务器正忙」 or 「服务器暂时无法生成这条发音」 | `bailian InvalidApiKey` = the key is wrong, or belongs to another region / 业务空间 (keys never cross regions, the endpoint host and the key must match); `bailian InvalidParameter … voice` = `WD_BAILIAN_TTS_VOICES` names a voice the model in `WD_BAILIAN_TTS_MODEL` does not have; `bailian ModelNotFound` = the model name or the region; `bailian Arrearage` / `AccessDenied` / `AllocationQuota.FreeTierOnly` = the account is in arrears, the model not enabled, or 「免费额度用完即停」 is on; `bailian: API key file unreadable` = `WD_BAILIAN_API_KEY_FILE` vanished or is empty; `busy` (`bailian answered 429 Throttling…` or a 5xx) = the 180 requests / minute limit or a 百炼 outage — the client retries by itself | `wd check providers` (the `audio:` / `bailian:` lines: model, region, both voices, key file `ok` / `missing` — never the key), fix `.env` + restart, then `WD_DATA_DIR=… wd audio-probe` (one clip; exit 1 prints the kind and message, e.g. `failed: bailian InvalidApiKey: …`); for a `busy` flood wait — limits are per account and model, 「通常 1 分钟内恢复」 —; `wd audio-prewarm` paces itself at 0.4 s and stops after five failures in a row: rerun it later, cached clips are skipped |
| Restore needed | — | §3 |
| Flag tier fell back to 0 | `claude_probe_fallback` event | inspect the stderr excerpt in the event; upgrade the CLI or stay on tier 0 (fully functional) |
| Reverse proxy / HTTPS wanted later | — | `deploy/install.sh --with-caddy words.example.com` (sets `WD_HOST=127.0.0.1`, `WD_PUBLIC_URL`, `WD_TRUST_PROXY=1`) |
| UI stale or mixed after an upgrade (old pages, lazy chunk imports failing, 「前端尚未构建」) | `readlink /home/sqin/word-dance-data/frontend` does not name the snapshot the last `deploy/install.sh` printed (`==> frontend publish: …`), or the service was not restarted after it (`--no-restart`, no passwordless sudo — `wd serve` resolves the symlink at startup) | `sudo systemctl restart word-dance`, reload the tab. Symlink missing, or `.env` still has `WD_FRONTEND_DIST=""` → re-run `deploy/install.sh` (fills the value, publishes the snapshot, §4). Bad build → the UI rollback in §4 |
| AI 配额 (per-user AI quota) — one learner's 不熟悉 marks stop producing example sentences: the cards stay on dictionary data and offer 「生成例句」, which answers 429 「操作太频繁，请稍后再试」 | `ai_quota_user` event in the admin overview (`{user_id, limit, used}`, once per user and UTC day; log event `ai_quota_user`); `SELECT * FROM auth_throttle WHERE key = 'ai:user:<id>'` shows the day's count (`window_start` = the UTC day) | expected: `WD_AI_USER_DAILY_WORDS` (80 words per account per UTC day, CLAUDE_INTEGRATION §7) protects the shared AI budget — nothing to do, the words are generated when the learner asks again tomorrow. Lift it for one learner today: `DELETE FROM auth_throttle WHERE key = 'ai:user:<id>'` against the service database (`WD_DB_PATH`; safe next to the live service, the row is GC'd a day later anyway). Change the cap for everyone: `WD_AI_USER_DAILY_WORDS` in `.env` (`0` = unlimited) + restart |
| SMS cap reached — learners see 「今日短信额度已用完，请改用邮箱或密码登录」 (503 `sms_budget_exhausted`); new phone sign-ups stop earlier, at 70 % of the day cap | `sms_budget_50` / `_80` / `_100` events in the admin overview (the admins' webhooks get 「短信额度提醒」 at 80 % and 100 %), the overview's SMS tile (`sent_today / daily_cap`, `sent_hour / hourly_cap`, `registration_open`), kv `sms.sent.<YYYY-MM-DD>` (`WD_TZ` day) / `sms.sent.<YYYY-MM-DDTHH>` (UTC hour) | expected: `WD_SMS_DAILY_CAP` (200) and `WD_SMS_HOURLY_CAP` (40) protect the Aliyun bill; the hour cap clears at the next full hour, the day cap at 00:00 `WD_TZ`; e-mail codes and password logins are unaffected. Raise the caps in `.env` + restart, or for today alone `UPDATE kv SET value = '0' WHERE key = 'sms.sent.<YYYY-MM-DD>'` against the service database (safe next to the live service) |
| A phone number changed hands — its new owner tapped 「不是我的账号」 and the old account cannot log in with that number any more | `phone_disputed` event (`{old_user_id, new_user_id, identity_id}`), the row under 管理 → 用户与邀请 → 争议绑定 (masked number, the account now holding it), a notice mail to the old account's verified e-mail | nothing while the dispute is genuine: the old account keeps its password / e-mail login (`wd set-password <username>` when it has neither). When it was wrong, 恢复 (`POST /api/admin/identities/{id}/restore`) gives the binding back once the new account no longer holds the number (409 `identity_taken` while it does — that account deletes itself or unbinds first); `phone_restored` event |
| A learner is locked out (423 「登录失败次数过多」) and asks for help | log event `login_lockout`; `auth_throttle` rows `login:user:<identifier>:<ip>` | the lock is per identifier **and** client IP (a stranger cannot lock the owner out) and expires by itself (15 min, doubling per further 5 failures); `WD_DATA_DIR=… wd unlock <username | phone | e-mail>` clears every IP's row at once (safe next to the live service) |
| Day 0 of SMS, or after an Aliyun signature / template change: does a real code arrive? | — | `WD_DATA_DIR=… wd sms-probe +86138…` sends ONE real login code (template 100001) through the configured provider and prints the provider's `Code` / `Message` / `RequestId` (exit 0 sent, 1 refused, 2 not configured); it touches neither the database nor the SMS counters |
| 「我的孩子」 shows 家长账号还缺：绑定手机号 with the hint 服务器尚未开启短信 (and Settings has no phone row) — every guardian action answers 409 `guardian_factors_required` | `WD_SMS_PROVIDER=off` in `.env` (`wd check` → `sms_provider: off`) | the two-factor rule needs a verified phone and a phone is bound only through SMS: enable the Aliyun channel (release note 2026-11-auth-signup-1a §3.1, `wd sms-probe`), restart; nothing else to fix |
| A guardian forgot the 家长 PIN (切回家长 / 家长验证 answer 401 「家长 PIN 不正确」) | `gate_failed` log events (`factor: pin`); after 10 wrong factors 423 `account_locked` and a `gate_lockout` event | the gate takes any ONE of PIN / password / verification code (API.md 102 / 105): pass it with the account's password or a `reauth` code (设置 → 账号 sends one to the bound phone or verified e-mail; from the child's screen 「切回家长」 → 验证码 sends it to the guardian, 106), then set a new PIN under 我的孩子 → 家长 PIN (103 — the stamp of the passed gate is what it needs). A guardian with neither a password nor a reachable channel: `WD_DATA_DIR=… wd set-password <guardian username>` gives it a password to pass the gate with (safe next to the live service) |
| The 家长门 is locked — 423 「登录失败次数过多，账号已暂时锁定」 on 家长验证 / 切回家长 for one guardian on every device | log event `gate_lockout` (`user_id` = the guardian); `auth_throttle` row `gate:user:<guardian id>` (`blocked_until`) | the lock is per guardian (the guesser sits on the guardian's own tablet) and expires by itself — 15 min, doubling per further 5 failures, max 24 h, cleared by a passed gate; to lift it now: `DELETE FROM auth_throttle WHERE key = 'gate:user:<id>'` against the service database (`WD_DB_PATH`; safe next to the live service — `wd unlock` clears login lockouts only) |
| A child is locked out of their own device (the 90-day session expired or was revoked by 退出所有设备 / a password change; the old login code is dead) | the child's device shows the login page; 我的孩子 lists the child with 「已登录设备 0 台」 (`ChildAccount.sessions`) | the guardian generates a new login code under 我的孩子 → 登录码 (API.md 99: 8 digits, 10 minutes, single use, 5 per hour per child — a 429 means wait for the next hour) and types it on the child's device under 孩子登录 (107); a child with a username + password (管理 → 用户名 + 密码, 96) can also sign in on the login page. A device that keeps failing codes is paused after 10 misses per hour (`child_login:ip:<ip>`; a valid code never counts): wait, or `DELETE FROM auth_throttle WHERE key = 'child_login:ip:<ip>'` |
| A child was set free by 独立 (101) or by the guardian's deletion with 「同时注销孩子账号」 (8) and the family wants it back | `child_emancipated` / `guardian_deleted` event; the account is a learner with its own phone (and password), gone from 我的孩子 | **irreversible by design** — there is no API or CLI path that turns a learner back into a child; the learner may join the family again only as a child of the 14+ band through 「这是孩子的账号」 (108 / 109 with `age_band: '14plus'`, the guardian confirming with the code sent to their phone); the phone and password it gained stay |
| 「二维码加载不出来」 — the login page's 微信 sheet shows the pairing code but no picture | `GET /api/auth/wechat/ticket/<t>/qr` answers 502 `provider_error`; log event `wx_qr_failed` (`kind` config / temporary, the WeChat `errcode`) and `wechat_api_error` (`call` stable_token / getwxacodeunlimit) | the pairing code still works (the learner opens the mini program and types it — the bridge never depends on the picture). `kind: config` (40013 / 40125) = `WD_WECHAT_APPID` / the first line of `WD_WECHAT_SECRET_FILE` do not match the mini program (reset the AppSecret in the mini-program console, rewrite the 0600 file, restart); 40001 / 42001 are retried once with a fresh stable token by themselves; a page / env error (41030, `invalid page`) = `WD_WECHAT_PAGE` or `WD_WECHAT_ENV` names a page / version the mini program does not have (an unpublished mini program needs `develop` or `trial`, miniprogram/README.md §5); `temporary` = network / 系统繁忙 — wait. `wd check` prints `third-party sign-in: wechat on` when the pair is configured |
| 「小程序说二维码已过期」 right after scanning, or the web sheet shows 二维码已过期 | 404 on `POST /api/auth/wechat/scan` / the poll says `expired` | expected: a ticket lives **3 minutes** from the moment the sheet opened (`wechat_tickets.expires_at`), the mini program's confirmation proof 5 more (`mp_token`); the sheet's 刷新 creates a new ticket. The clock matters: a server clock more than a minute off against the phone's is the usual cause when it happens every time (`timedatectl`; the Mac's `sntp -sS time.apple.com`). A ticket scanned on another phone first answers 409 `scanned_elsewhere` instead — a second person is looking at that screen |
| 「小程序提示操作太频繁」 — the mini program toasts 操作太频繁 on a scan or a confirmation (or the web sheet says so) | 429 `rate_limited` on `POST /api/auth/wechat/scan` / `confirm` (`details.retry_after_s`, `Retry-After`); `SELECT key, count, window_start FROM auth_throttle WHERE key LIKE 'wx_%'` names the window | behind the mainland relay EVERY mini-program request arrives from the relay's one IP (`deploy/relay/README.md` §5 — the Tokyo front trusts only the local proxy, so `client_ip` is the relay), which is why the per-IP windows of 115 / 116 are wide flood brakes (`wx_scan:ip` / `wx_confirm:ip`, 600 a minute, site-wide) and the real brakes are per WeChat user: `wx_scan:openid` 10 scans a minute, `wx_confirm:openid` 20 confirmation attempts a minute (hashed keys — the openid is never in the table). One learner tapping over and over hits the openid windows (wait a minute; nothing to do); an IP window at 600 means a flood through the relay (the relay's `relay.access.log` has the source address — block it there) or a mini program stuck in a retry loop. The web side is per browser IP: 30 tickets a minute / 300 an hour and 1 200 polls a minute (`wx_ticket:ip`, `wx_poll:ip` — a classroom behind one NAT fits; the 小程序码 picture, 114, is never throttled). Windows are fixed 60-s / 3600-s buckets in `auth_throttle`; `DELETE FROM auth_throttle WHERE key = '…'` opens one at once |
| 「用户解绑后登不进去」 — a learner unbound WeChat / QQ / Apple and now has no way to sign in | log event `auth_identity_unbound` (`provider`, `user_id`); `SELECT * FROM identities WHERE user_id = <id> AND disputed_at IS NULL` is empty and `password_set_at` is NULL | should not happen: 117 refuses to drop the last way in (409 `last_login_method`, `third_party.ways_in` counts the password, a live phone, a verified e-mail and every third-party identity — the identity about to go included) and the re-authentication itself needs a password or a code channel. When it did (a row edited by hand, an e-mail un-verified after the unbind): `WD_DATA_DIR=… wd set-password <username>` gives the account a password to sign in with (safe next to the live service); the learner may then bind the provider again from 设置 → 账号 |

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
`audio/` (cached pronunciation clips, API.md 76) is 0700 with 0600 files like `images/`; it is a cache capped by `WD_AUDIO_CACHE_MB`
(least recently played clips go first) — deleting it only costs a re-synthesis the next time each word is played; `wd audio-prewarm` (DEPLOY §9) fills it ahead of time; `--purge-others` first deletes every clip outside that run's set — another voice's after a voice change, but also ad-hoc or earlier `--stage` texts, one re-synthesis each at the next tap. Under `WD_AUDIO_PROVIDER=cache` it is the mirror of the Mac's clips instead: deleting it means `missing` for everything until the next §5 sync, `wd audio-prewarm` refuses there and the cap is not enforced. `git clean -fdx` in the checkout can never touch the data directory.

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
