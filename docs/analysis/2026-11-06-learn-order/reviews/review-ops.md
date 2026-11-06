# Adversarial review — lens: operations and data integrity · 2026-11-06

Scope: the whole uncommitted learn-order change (git diff against cd3df8c + the new files) against the contract
`docs/analysis/2026-11-06-learn-order/DESIGN.md`, `scratchpad/order/FACTS.md` and the repository conventions. No repository file was
modified. Every probe ran on a private `VACUUM INTO` copy of the read-only live database (schema 13, 9,618 words, seed 24f3b949…),
never on `/Users/sqin/word-dance-data`; nothing bound a port. Scratch: `scratchpad/impl/review-ops/` (probe scripts `probe_*.py|sh`,
outputs `probe_*.out`, copies `live13{,b,c,d}/`, the cd3df8c tree extracted with `git archive` under `old/`, the 75df534 seed under
`old_seed_75df534.jsonl.gz`).

## Probes run (command → result)

| # | probe | result |
|---|---|---|
| A | `python -I probe_a_migration.py` (live13): `db.run_migrations(conn, pre_hook=db.backup_pre_hook())` on the schema-13 copy | applied `[(14,'learn_rank')]` in 179 ms incl. the pre-migrate snapshot (`backups/pre-migrate-13-to-14.db.gz`, 2.0 MB); column `INTEGER` nullable no default cid 36; `v_bank` 18 rows unchanged, index set unchanged, 25 tables; page_count 1436 → 1437 (one schema page); the cd3df8c-style explicit-column INSERTs (`seed._UPSERT_SQL`, `_INSERT_WORD_SQL` minus `learn_rank`) still succeed and leave `learn_rank` NULL; first fill 9,618 rows in 88 ms, second recompute 0 rows (58 ms); 16 distinct `updated_at` and `MAX(updated_at)` unchanged; `push_items` (154 rows) and `user_words` (77) byte-identical; `kv.learn_order.stats` 1,486 bytes; max key 13,812,400; EXPLAIN of the 词库/筛词 shapes = `SEARCH … ix_words_public` + `USE TEMP B-TREE FOR ORDER BY`; **C10 trap row** (`stage_xs=1, stage_min NULL, frq 1`) → 筛词 position 601/601 for a 小学 learner and 9,381/9,619 in 词库 全部 (first 课标外 row), `stage_min_consistent` counts it |
| B | `python -I probe_b_oldcode.py` — the **cd3df8c code** (git archive, editable finder removed from `sys.meta_path`) against the filled copy | pending migrations for the old code `[]`; health 200; `GET /api/vocab?stage=xs` → `the be and of a in to have it i` (the frq order back at once); 全部, `screen/next`, `words/say`, `lookup?q=sa`, `admin/events` (kinds incl. `learn_order_recomputed`), `admin/overview` all 200; old `wd check db` ok with the four stage lines; old `import_seed` of the 75df534 seed: 4,357 rows updated, keys untouched |
| B2 | `python -I probe_b2_newcode_after_old_import.py` — the new code after B's old-code import | `is_current` → `(False, 'seed 24f3b9496c14… ≠ kv.seed_version 3b3ed209d37f…')`, `learn_order_current` 1 violation, `learn_rank_matches_policy` 931, `ensure_current` repaired 931 rows in 60 ms, re-import of the current seed → 931 ranks changed, stale 0, xs head `say go get make know one time year` |
| C | `python -I probe_c_startup.py` (live13b): `create_app` + `TestClient` (`WD_WORKER_ENABLED=0`) on the schema-13 copy = an old snapshot restored under the new code | start-to-health 0.46 s: `applied migration 0014_learn_rank`, seed_check silent (same digest), `learn order lo-1: 9618 rows, 9618 updated in 0.082 s … (startup)`, one `learn_order_recomputed` event, stamps set, snapshot written; second start 0.07 s, no row, no event, `computed_at` moved; a `BEGIN IMMEDIATE` held 3 s / 7 s by another connection delays the start by exactly that (busy_timeout + begin retries) and the start never fails; a raising policy → health 200 + `learn_order_failed {"trigger":"startup","error":"RuntimeError: policy exploded"}` (see F3 for the 3-s case's side effect) |
| D/E | `zsh probe_de_cli.sh` (live13c): the CLI path | `wd migrate` 0014 + snapshot; `wd import-seed` no-op leaves the column NULL (install.sh's `wd learn-order` line is what fills it); `wd learn-order --dry-run` and `wd import-seed --dry-run` leave the file sha256 unchanged (`8561bdc3b55208b4`); `--force` re-import → 9,618 ranks + the four kv keys + `seed_imported` only (no `learn_order_recomputed`); `wd learn-order` 0 updated; `--report` document keys/stages/acceptance as §2.8 (identical acceptance block to `data/seed/learn_order.json`); `--show xs --top 5 --cur xs`, `--show zk --top 3` (`have to` dealt onto `thing`); `wd check db` eight ok lines, kv.learn_order lines before `kv.backup.last`; the **older 75df534 seed** imported by the new code: 4,357 rows updated, 931 ranks changed, 656 of them rank-only without touching `updated_at`, stamps current, stale 0; refusal on a schema-13 copy (`--db`, with and without `--dry-run`): `schema version 13 has no words.learn_rank (migration 0014) — run \`wd migrate\` first`, exit 1; missing file → exit 1; `wd check db --db <v13>` prints none of the four lines |
| F | `python -I probe_f_checkdb_policy_error.py` | `diag.check_db` with `rank_rows` raising `RuntimeError` → **traceback** out of `check_lines` → `stale_count` (finding F2) |
| G | `python -I scripts/rehearse_migration.py live13/word-dance.db` on the already-upgraded copy | 52 passed, 0 failed; `check_0014` runs with `ran_here=False` (no "NULL everywhere" check), recompute 0 updated |
| H | `probe_tokens.out`, `probe_h_drift_how.out` (live13c) | 32 tokens of frequency-less **stage** phrases resolve to no row/form (`beijing`, `sooner`, `mid`, `curd`, `upside`, `semi`, `ping`, `pong`, `york`, `zealand`, …); 24 of them are ECDICT headwords with `frq` or `bnc`; `_insert_word` of `sooner` (bnc 3771) → **213 stale 初中 rows**, all `how == 'dealt'` → `invariant learn_rank_matches_policy: 213 violation(s)`; `beijing` → 32, `mid` → 12; a runtime `words.add_form('sooner' → soon)` → 57 (finding F1) |

## Findings

### F1 · major · CONFIRMED — `learn_rank_matches_policy` fails after ordinary user actions; the release note says runtime words only touch 课标外
`backend/wd/services/learn_order.py:721-725` (`stale_count`) / `:756`; `docs/releases/2026-11-learn-order.md:122` ("无词频的新词到下次重算才拿到撒入位置——**只影响课标外组**") and `:155`; DESIGN §2.1 :259 / A8 :648.
R3 resolves phrase tokens through `words.lemma` and `word_forms`, so a runtime row can change the `token_rank` of a frequency-less **stage** phrase
and re-deal every later dealt row of that `(stage_min, closed)` group. Evidence (probe H, live copy): a user adding `sooner` (an ECDICT headword, BNC
3771; `_insert_word` through `_resolve_ecdict`) leaves 213 初中 words stale → `wd check db` → `[FAIL] db`, exit 1, `invariant learn_rank_matches_policy: 213
violation(s) …` until the 03:30 maintenance or `wd learn-order`; `beijing` → 32, `mid` → 12, a lookup's `add_form('sooner' → soon)` → 57. 24 of the 32
unresolved tokens are ECDICT headwords. The A8 rationale ("stage words only, so the gate does not flip after a user adds an ECDICT word") therefore does
not hold; the module docstring (:35-37) admits the nuance but the operator-facing texts (release note §4.1, §4.3, ops.md "one command repairs the first
three") do not, so the §8 gate 8 / release note §6 step 3 `wd check db` can FAIL on the live box for a reason the operator was told cannot occur.
**Fix**: every drifted row is `how == 'dealt'` (natives, sets, adverbs, interjections and glued rows depend only on seed-managed inputs), so count the
FAIL-flipping violations over stage rows with `how != HOW_DEALT` and report the dealt drift informationally (e.g. append `· dealt drift N` to the
`kv.learn_order.stats` line, computed live in `check_lines`); add a `test_learn_order_db.py` case (insert an ECDICT-like row whose lemma is an unresolved
token → `check_lines` all ok, `stale_count(..)` scoped); correct release note :122/:155 and DESIGN A8. Alternative: run `recompute(conn,
trigger="runtime_insert")` (≈ 70 ms, probe H) from `_insert_word`/`add_form` when the lemma/form is a token of a frequency-less phrase.

### F2 · minor · CONFIRMED — `wd check db` tracebacks instead of `query failed (…)` when the policy raises
`backend/wd/services/learn_order.py:744-762` (`check_lines` catches only `sqlite3.OperationalError`), `backend/wd/diag.py:116` (`check_db` catches only
`sqlite3.Error`). DESIGN §2.7: "a failing query is reported as `query failed (…)` and not counted". Probe F: `rank_rows` raising `RuntimeError` →
uncaught traceback through `_learn_order_lines → check_lines → stale_count → _compare`, no lines printed. `ensure_current` guards the same policy for
the service, `wd check db` does not. **Fix**: `except Exception as e` around the `learn_rank_matches_policy` (and `learn_rank_present`) computation →
`(f"invariant …: query failed ({type(e).__name__}: {e})", False)`; one test with a monkeypatched `rank_rows`.

### F3 · minor · CONFIRMED — `recompute` reads the stored keys before `BEGIN IMMEDIATE`; a concurrent commit in that window is missed for the pass
`backend/wd/services/learn_order.py:620` (`_compare` outside the transaction) vs `:644` (`with db.maybe_tx(conn)`). Probe C: another connection held
`BEGIN IMMEDIATE; UPDATE words SET learn_rank = NULL WHERE stage_min = 1` for 3 s while the service started; the start waited 3.05 s for the lock, then
wrote its empty change set computed from the pre-commit snapshot and stamped `computed_at` — 600 stage words stayed NULL (`learn_rank_present: 600
violation(s)`) until the next start (the 7-s run then wrote `600 updated`). Realistic writers in the window: an operator's `wd import-seed`/`wd
learn-order` next to a restart, and at the nightly compare the lookup jobs (`_insert_word`, `add_form`) — self-healing next night, so minor. **Fix**:
re-read `_stored_keys(conn)` (≈ 3 ms) and derive `changed` inside the `maybe_tx` block (the policy compute stays outside, the lock stays ≤ 30 ms).

### F4 · nit · CONFIRMED (code) — `--report` without a recompute, and `report()["seed"]` is not the stamp
`backend/wd/services/learn_order.py:854` (`"seed": db.kv_get(conn, "seed_version")`) and `:915-931` (`--report` is written after `--show` / `--dry-run`
too, although the help text says "after the recompute"). On a database whose ranks were computed for another seed (B2 state) `wd learn-order --dry-run
--report x.json` documents the stored keys under the current `kv.seed_version`. **Fix**: `"seed": db.kv_get(conn, KV_SEED) or db.kv_get(conn,
"seed_version")`, and either refuse `--report` together with `--dry-run`/`--show` or say in the help that it then describes the stored state.

### F5 · nit · CONFIRMED (text) — rollback / symlink recipe gaps in the runbooks
`docs/releases/2026-11-learn-order.md:248` ("再把 `$D/frontend` 指回 `frontend-releases/cd3df8c`" without the command) and
`docs/analysis/2026-11-06-learn-order/DESIGN.md:598` §6.1 step 1 (`mv -f $D/frontend.tmp $D/frontend` — the BSD `mv` trap the K-12 note §6 step 5 / §7 and
this release note §6 step 1 avoid with `python3 -c "import os; os.rename(...)"`). **Fix**: spell out `ln -sfn frontend-releases/cd3df8c $D/frontend.tmp &&
python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"` in §8 and replace the `mv -f` in DESIGN §6.1.

### F6 · nit · CONFIRMED (gate report) — the contract names a frontend gate that does not exist
`docs/analysis/2026-11-06-learn-order/DESIGN.md:448, :454, :670` — `npm run check:copy`; `frontend/package.json` has no such script (the copy check is
`npm run lint` → `scripts/check-copy.mjs`). **Fix**: replace with `npm run lint` so a re-run of §8 gate 3 does not fail on a missing script.

## Verified and found correct (no finding)
* Migration file through the real runner (A): additive, no rebuild, `v_bank` untouched, old explicit-column INSERTs valid, snapshot hook writes
  `pre-migrate-13-to-14.db.gz`; code-only rollback to cd3df8c serves the frq order with the column present (B); old `wd check db` ok.
* Startup sequence migration → seed_check → ensure_current (C): fills before the first request, idempotent, never fatal, busy lock only delays.
* Seed import (D/E, B2): ranks + `kv.seed_version` in one transaction; dry runs write nothing (file hash); `--force` and an older seed re-import keep
  the stamps current and `updated_at` moves only for rows the UPSERT changed; the old-code-import stamp case is detected and repaired.
* Runtime inserts: ECDICT row carries `best_effort_rank` (exact), provisional row NULL; `lookup.fill_fields` (`if not word.get("pos")`),
  `consolidate._fill_data` (skips non-NULL and seed rows) never overwrite a non-empty `pos`.
* Nightly hook (`scheduler.maintenance`) guarded; CLI exit codes/refusal text/`--db` as §2.5; `wd check db` eight lines in order, kv lines before
  `kv.backup.last`, none on a v13 database; rehearsal script on fresh and upgraded copies; install.sh order migrate → import-seed → learn-order →
  claude-check (`run()` under `set -e`); C10 trap row sorts last everywhere; `push_items` / `user_words` untouched by the fill; `kv.learn_order.stats`
  1,486 bytes; EXPLAIN plans unchanged in shape; Mac runbook paths and launchd label match the installed plist.
