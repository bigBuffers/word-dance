# Mechanism judgement — lens "operations and data integrity" · 2026-11-06

Judged: `mech-query-time.md` (QT), `mech-derived-column.md` (DC), `mech-seed-carried.md` (SC), all three read in full, every
file:line reference checked against `/Users/sqin/word-dance` @ `cd3df8c` (clean tree, the code DEPLOYED on the Mac this morning).
Evidence beyond reading: the three authors' simulation scripts were copied into `sim-judge-ops/reuse-{qt,dc,sc}/` and re-run
(all exit 0; headline numbers reproduced), and `sim-judge-ops/judge_checks.py` ran five checks of my own on the read-only live
copy and on a scratch copy (output in `sim-judge-ops/judge_checks_output.txt`). Nothing under `/Users/sqin/word-dance` or
`/Users/sqin/word-dance-data` was touched.

## 0 Verdict

| Mechanism | Score | One line |
|---|---|---|
| **derived-column** (`words.learn_rank`, recomputed by the server) | **8.5** | Smallest integrity surface that still stores an inspectable order: additive 0014, 41 ms fill at startup inside a never-fatal hook, fail-soft tail identical to today's order, code-only rollback, three `wd check db` invariants, rehearsal prints the 小学/初中 head on the copy. Must close the "forgotten `LEARN_ORDER_VERSION` bump" hole and fill ranks in `install.sh`, not only at service start. |
| query-time (SQLite UDF, nothing stored) | 6.5 | Zero schema / zero data risk and a restart-only deploy, but the order exists nowhere an operator can look (no SQL, no `sqlite3`), cross-row statistics are a 10-minute-TTL process cache, exact positional spreading is impossible, and a single Python function is on the critical path of 词库 / 筛词 / the nightly batch for every request (+0.3–5.3 ms on the Mac, more on a Lighthouse vCPU). |
| seed-carried (`learn_rank` in seed record v3) | 6.0 | Best reviewability (DIFF.md §(f), `stats.json.learn_order`) and fleet determinism, but two verified integrity gaps as designed — the ORDER BY tail has no frq fallback (NULL ranks ⇒ alphabetical 筛词, worse than today) and the new invariants are *skipped* in exactly the failure state (a failed forced import leaves `kv.seed_version` empty, identical to "pending") — plus every policy iteration rewrites all 9,618 rows (`updated_at` 16 → 1 distinct values), regenerates a 1.4 MB artefact and the test fixture, and splits the truth between the seed file and the server's policy constant ("the seed wins"). |

Winner: **derived-column**. Rationale in §4, must-fix list in §5, grafts in §6.

## 1 Claim verification (what the three documents assert about the repository)

Every line reference below was opened. "✓" = exact; deviations are listed explicitly.

### 1.1 Shared ground (all three)

| Claim | Verified |
|---|---|
| Five ORDER BY sites: `routers/vocab.py:75-82` (`_ORDER`, freq :76, difficulty :81; COUNT :117, SELECT :118-121) · `services/screen.py:65` (`_STAGE_DISTANCE` :34-36, params :62, COUNT :63) · `services/batches.py:61` `_SCREEN_ORDER` (used :271 `select_words` dict :272, :697 `add_more` dict :698) · `ai/prewarm.py:52` (positional tuple :53; docstrings :5 "by frequency", :45 "most frequent first") · `routers/words.py:106` | ✓ all |
| Startup `main.py:484-504`: `run_migrations(conn, pre_hook=backup_pre_hook())` :489 → `seed_check` :492 (never fatal; writes `system_events('seed_import_failed')`, leaves `kv.seed_version` unchanged on failure) → `public_url_guess` :493 → `registry.load_handlers` → workers | ✓ |
| Runner `db.run_migrations` (:195): each file inside the runner's own `BEGIN IMMEDIATE`, `executescript` without implicit commit (autocommit=True), `PRAGMA foreign_keys` OFF/ON around it, bookkeeping row written by the runner | ✓ |
| `db.connect` :88-101 (PRAGMA loop :99-100, `return conn` :101); `db.maybe_tx` :145 joins an open transaction; `backup_pre_hook` late import :252-261 | ✓ |
| Seed importer: `SEED_COLUMNS` :71-89, `_UPSERT_SQL` :93-103 (explicit column list, DO UPDATE only when a seed column differs), `_PLAN_COLUMNS` :105, `SeedPlan` :108, `SeedStats` :132, `seed_row` :243 (`seed_v`/`variant_of` ignored), unknown-code warning :451-459, `kv.seed_version` write :477, `format_stats` :523, "run `wd migrate` first" :569-579, `__all__` :615 | ✓ |
| Runtime word writers: `_word_defaults` :569-588, `_INSERT_WORD_COLUMNS` :592-596, `_INSERT_WORD_SQL` :597-601 (explicit columns), `_insert_word` :604-611, `_resolve_ecdict` :667, `_create_provisional` :703; `ecdict.word_columns` :168-188 | ✓ |
| `UPDATE words SET …` sites that touch rank inputs: `ai/lookup.py:317` (kind), `:368` (pos/kind), `ai/consolidate.py:292` (pos), `services/suggestions.py:418` (`RESTORABLE_WORD_COLUMNS` :44 incl. pos/kind) — nothing else changes `pos`/`kind`/`frq`/`bnc`/`stage_min` at runtime | ✓ (grep over `backend/wd`) |
| Diagnostics: `STAGE_INVARIANTS` :50-57, `STAGE_INVARIANTS_FROM_VERSION` :58, `check_db` :81-112 (kv tuple :97, seed-version line :105-107), `_seed_version_line` :129, `__all__` :361; `test_diag.py` pins four names (:27), the PLAN literal (:182-191), `count == 4` (:199), and "every line after `kv.backup.last` is an invariant line" (:57) | ✓ |
| Rehearsal: imports :50-52, constants :54-58, `snapshot` :129, `check_bookkeeping` :162, index set :215, `check_0012` :254, `check_0013` :272, `check_invariants` :291, `check_empty_database` :302, dispatch :363-376, `EXPECTED_TABLE_COUNT = 25` | ✓ |
| Tests that pin today's order exist at the quoted lines: `test_vocab.py:93/:163/:234`, `test_screen.py:122/:142/:161`, `test_batches.py:104 (:129)/:152`, `test_words.py:86-87`, `test_admin_ops.py:488` (set equality), `test_db.py:21/:42/:421`, `test_cli.py:58`, `test_main_seed_check.py:30`, `test_seed.py:245/:283/:323/:476/:497/:624`, `test_seedbuild_build.py:99/:427/:463`, `test_words_resolve.py:131/:271`, `test_seed_diff.py:80` | ✓ |
| Docs: `API.md:169` (endpoint 20 ORDER BY text), `DESIGN.md:196` (§3.2 heading, "v2"), `:205` (frq row "sorted last"), `:350` (§6.2 last sentence), `:364-370` (§6.3 step 4), `FRONTEND.md:147/:254`, `CLAUDE_INTEGRATION.md:303`, `WORD_LIBRARY_CURATION.md:150` (+ C10 at :296), release note `:212-213`, `DEPLOY.md:361/:421/:425`, `ops.md:19/:117-123`; `zh.ts:48`, `endpoints.ts:133`, `schemas.py:503`, `VocabPage.tsx:34` | ✓ (PLAN §9.2 #5 is `PLAN.md:755` — DC right, SC's `:749` is the §9.2 heading) |
| Connections that could order `words` all go through `db.connect` (deps :70, main :394/:435/:474/:487, scheduler :530, worker :376/:387, cli :90, diag :87/:240/:305, seed :567, batches :1066, security :713, health :29, admin_ops :270, images/handler, ai/consolidate, ai/probe, rehearsal :307/:335, conftest :145/:159); raw `sqlite3.connect` only in `backup.py:100/:359`, `ecdict.py:212`, `seedbuild/build.py:496/:503`, `eval_provider.py:310` | ✓ |

### 1.2 Per-design accuracy

* **QT** — accurate throughout. Two design-internal inconsistencies, not repo errors: (a) `order_key_total` says it counts rows where "the policy raises", but `order_key` is specified as a total wrapper that never raises → the check must call the inner policy; (b) the §5.2 claim that `an` lands at position 3 of 小学 because its `pos` is empty is a policy observation, correctly flagged as the stand-in's gap.
* **DC** — accurate; one inaccuracy: "v_bank's `w.*` column list" — `0011:86-87` defines `v_bank` as `SELECT uw.*, w.lemma, w.display, …` (named `w.` columns; the `*` is on `user_words`). The conclusion (ADD COLUMN on `words` cannot change the view) still holds. `sim_extend.py`'s "v_bank uses w.*: True" is a substring hit on `uw.*`.
* **SC** — accurate on every line reference and every measurement I re-ran (0014 draft 3.8 ms through the real runner; first v3 import 394 ms, 9,618 updated, `updated_at` 16 → 1; old importer reads v3 with 0/0 and no error — I also confirmed with `seed_row()` directly that the current importer silently drops the unknown `learn_rank` key). The two gaps in §3 below are design properties, not misstatements.

## 2 Evidence from the simulations

Re-runs (copied scripts, same read-only URI / private scratch copies; all `exit 0`):

| Script | Reproduced |
|---|---|
| `reuse-qt/bench_query_time_v2.py` | registration ≈ 1 µs/connection; UDF raise → `OperationalError: user-defined function raised exception` (whole statement); NULL key sorts first; `no such function` on a bare connection; site table A→C4: vocab 全部 p1 1.39 → 6.03 ms, 筛词 30 1.01 → 2.30, 推荐词 15 0.84 → 2.11, add_more 1.01 → 2.29, prewarm xs 0.72 → 1.02; plans identical to baseline; differential SQL == Python sorted identical on xs 600 / zk-new 1,949 / cet6 7,671 / all 9,618 |
| `reuse-dc/sim_recompute.py` | 0014 ADD COLUMN + index 2.2 ms, pages 2300 → 2300; recompute 9,618 rows: read 5.6 + compute 11.4 + write/commit 23.6 ms; no-op recompute 18 ms; stale-diff 18 ms; startup NULL probe 0.02 ms (index) ; every list query within ±0.1 ms of today with or without the index |
| `reuse-sc/sim_seed_carried.py` | builder rank_all 14.4 ms; v3 import 394 ms / 9,618 updated / `updated_at` 16 → 1 / card-LRU key miss; re-import 5.9 ms up to date; `--force` 0 rows; v2 fallback identical keys; old server + v3 seed 0/0 no error; rollback 0/0 column untouched; invariants 0.5 ms + 19 ms |

My own checks (`sim-judge-ops/judge_checks.py`, output `judge_checks_output.txt`):

```
A. xs ORDER BY tails while learn_rank is NULL on every row
   today (frq)                        : the be and of a in to have it i that for
   seed-carried ORDER_TAIL, rank NULL : a about after afternoon again age ago air all also always am
   derived-column ORDER_SQL, rank NULL: the be and of a in to have it i that for
B. sqlite 3.54.1 · python 3.12.16 · threadsafety 3; raising UDF fails the statement; NULL key ties fall to the next key;
   unregistered connection → "no such function"; create_function ≈ 0.2 µs
C. current importer (cd3df8c) seed_row() on a v3 record: accepted, stage_min 1, 'learn_rank' NOT in the row, NOT in SEED_COLUMNS
D. scratch copy: SC-style 0014 (ADD COLUMN + DELETE kv.seed_version) → kv.seed_version None, 0 ranked rows;
   import of a truncated gzip raises EOFError (what main.seed_check catches) → kv.seed_version STILL None, 0 ranked rows;
   SC's skip condition "kv.seed_version is empty" is True in BOTH states; a 小学 pupil's 筛词 in that state (SC tail):
   a about after afternoon again age ago air all also — with the DC tail: the be and of a in to have it i
E. DC fill on the copy: read+compute 13.6 ms, UPDATE 9,618 rows 22.7 ms, full stored-vs-computed compare 6.8 ms → 0 stale;
   updated_at distinct values stay 16 (the fill never touches updated_at)
```

## 3 Scoring by criterion

Scale 1–10 per criterion; the composite weights blast radius / data integrity double because that is this lens.

| Criterion | query-time | derived-column | seed-carried |
|---|---|---|---|
| Correctness: exact dominant POS | 9 — `dominant_pos` in Python (the SQL re-implementation was measured and rejected, D-images-24) | 9 — same reader | 9 — same reader, at build time |
| Correctness: deterministic | 8 — pure function + crc32; but per-stage quantiles come from a process cache refreshed on `(seed_version, COUNT, MAX(id))` or after 600 s, so two processes (server vs `wd order`) can disagree on the band for ≤ 10 min after an in-place `frq` fill | 9 — recomputed from the table, stamped `kv.learn_order.{version,seed_version}`; two instances starting together compute the same values | 10 — the file is the truth; Mac and Lighthouse order identically given the same seed, even across code versions |
| Correctness: cross-row statistics | 5 — only summary triples bound as parameters; exact positional spreading of frq-less words impossible (hash spread instead); statistics stale ≤ TTL | 9 — whole table at recompute; stored per-stage table for single rows; exact spreading possible with the documented "stale until next recompute" caveat for runtime rows | 10 — whole file at build time, any statistic, result stored |
| Blast radius / deploy, Mac today | 8 — no schema, no data write, restart-only, rollback = restart on previous commit. But one Python function sits on the critical path of 词库/筛词/推荐词/预生成 for every request; a raise = total list outage until a hotfix (mitigated by the total wrapper + the full-table check; the mitigation turns a loud failure into a silent "everything sorts last by lemma") | 9 — additive 0014 (0010/0012 class, `--no-restart`-safe), 41 ms fill inside `ensure_current` (never fatal), fail-soft tail reproduces today's order exactly (A above), pre-migrate snapshot automatic, code-only rollback safe (explicit-column INSERTs at `seed.py:94`, `words.py:598`; readers by name) | 5 — additive 0014 but it clears `kv.seed_version` → forced full re-import rewriting 9,618 rows and collapsing `updated_at` (card LRU emptied, the "unchanged row is not rewritten" rule broken once per policy change); between migration and import, or after a failed import, every list is alphabetical (A, D); a hand-inserted row sorts by lemma, not by frq |
| Blast radius / deploy, Lighthouse later | 8 — `install.sh` path unchanged; `deterministic=` needs SQLite ≥ 3.8.3 (any Ubuntu); Python UDF cost 2–3× on a vCPU | 8 — `install.sh` runs `wd migrate` + `wd import-seed` then starts the unit; the FILL happens only at service start (`ensure_current`), so `wd check db` between install and start reports violations, and a `--no-restart` upgrade leaves ranks NULL until the next restart → see must-fix 3 | 7 — `install.sh:141 wd import-seed` fills the ranks under the new code before the unit starts; a DB copied from the Mac needs nothing; but a failed import on the box leaves the alphabetical state with two `[skip]` lines (D) |
| Data integrity (drift, invariants, observability) | 6 — nothing stored ⇒ nothing drifts; but nothing is inspectable from SQL/`sqlite3` either (the order is reproducible only by `wd order` / the Python key); `order_key_total` as written cannot see a swallowed exception; policy change = code change only (no artefact to review) | 9 — column visible to `SELECT`, `wd learn-order --show`, three invariants (`learn_rank_present`, `learn_order_current`, `learn_rank_matches_policy` 18 ms) that never skip; drift from runtime `pos` fills is reported, repaired by restart; the only hole: a policy edit without a `LEARN_ORDER_VERSION` bump is caught by `wd check db`, not by startup (must-fix 1) | 6 — column visible, DIFF.md (f) and `stats.json.learn_order` are excellent review artefacts; but the invariants are skipped while `kv.seed_version` is empty, which is also the post-failure state (D) ⇒ `[ok] db` over an alphabetical list; a server whose policy differs from the seed's keeps serving the seed's ranks ("the seed wins") — loud, but the disagreement persists until a seed rebuild lands |
| Repo conventions (single source, doc-code pins, invariants, rehearsal) | 7 — `services/order.py` single source, `order_by()` rendered from `STAGE_INDEX` (R-1), docs pinned by `test_docs_contract`; `check_order` in the rehearsal though nothing migrates; API.md §20 would quote a function name instead of an ORDER BY the operator can run | 9 — `services/learn_order.py` + one `ORDER_SQL` constant quoted in API.md §20 / DESIGN §6.3 and pinned; kv stamps mirror `kv.seed_version`; `check_0014` modelled on `check_0012` with the 小学/初中 head printed on the copy (the preview FACTS §1 asked for); new CLI follows `CLI_MODULES`/`COMMAND_OWNERS`/DEPLOY §9; `STAGE_INVARIANTS` untouched (PLAN literal test) | 7 — strongest on "seed numbers live in stats.json" and `make seed` idempotence; `DIFF.md` section (f) fits the existing review flow; but a derived value shipped as source data contradicts the importer's own principle (the importer "never reads a list", derives everything else) and `--dry-run` reports 9,618 "updates" on every policy deploy |
| Testability | 7 — pure functions + differential test (SQL == Python sorted) are excellent; the process-level stats cache (keyed by DB path, TTL, lock) needs clock monkeypatching and is shared across the dozens of test databases of one pytest process | 8 — pure `rank_rows`/`rank_for`, idempotent `recompute`, `test_db_0014.py` on the 0013 pattern, startup test on the `test_main_seed_check` pattern; existing literal expectations become DB-derived; one ripple to handle (must-fix 5: `word()` in `test_seed.py:40` is `SELECT *`) | 6 — fixture regenerated as v3 (every `seeded` test changes data), a v2 copy kept for the fallback, ~12 test files touched, builder + diff + importer tests; the "fallback ripple" on 62 rows is real and forces the v3 fixture |
| Runtime cost | 5 — +0.3–5.3 ms per request on the Mac (0.49 µs × candidate rows, under the GIL), worst case 词库 全部 p40 ≈ 10 ms; the nightly builder pays ≈ 1.3 ms per user; grows with the table | 9 — 0 at query time (plans identical), 41 ms per stale start, 18 ms per `wd check db` | 9 — 0 at query time; 0.4 s import per policy change; builder +15 ms |
| Extensibility to a textbook / grade order | 6 — textbook rank as a leading `COALESCE` key or an 11th argument works, but the field itself must be stored by another mechanism | 8 — one more `INPUT_COLUMNS` member via additive 0015 or a side table; per-user scheme via per-scheme columns or a join; ranks re-derived on every deployment | 9 — textbook order IS seed data; registry of keys + `order_tail(key)`; per-user `order_key` at request time |
| **Composite (integrity ×2)** | **6.5** | **8.5** | **6.0** |

## 4 Why derived-column wins under this lens

1. **Same correctness as the stored alternatives, without the stored alternatives' failure states.** DC and SC both compute the key in Python with `dominant_pos` over the whole row set; only DC's tail (`learn_rank IS NULL, learn_rank, (frq IS NULL OR frq=0), frq, lemma`) keeps the lists *exactly today's* when ranks are missing (check A). SC's tail is alphabetical in that state (A, D). QT cannot be in that state, but it also cannot show its state to anyone.
2. **The truth stays in one place that the deployed code owns.** DC: policy = code, values = derived from the table at every start, stamped. SC: policy = code, values = file; a mismatch is a WARNING and a `wd check db` line, and the owner must remember "policy change = `make seed` + commit of a 1.4 MB artefact + fixture regeneration" during exactly the phase (policy tuning before inviting 小学生) when iterations will be frequent. QT: policy = code, values = nowhere.
3. **Deployment today is a restart with an automatic snapshot.** 0014 is one `ADD COLUMN` (+ an index the author concedes no plan uses), `ensure_current` fills 9,618 ranks in 41 ms before the first request, failure is logged as `learn_order_failed` and the service serves today's order. No stop-first runbook, no `updated_at` churn, no seed change, no frontend snapshot unless the owner changes the 词频 label.
4. **Operators keep their tools.** `SELECT lemma, learn_rank … ORDER BY learn_rank` works in `sqlite3`; `wd learn-order --show xs --top 30` and the rehearsal's `check_0014` print the head of the order before production is touched; three invariant lines flip `[FAIL] db` and name the one command that repairs all of them.
5. **The cost of being wrong is a restart.** A disliked policy, a wrong label, a bad constant: `git checkout cd3df8c && launchctl kickstart -k …` — the old code ignores the column (verified: both INSERT statements name their columns, every reader is by name, `v_bank` names its `w.` columns).

What QT does better and DC should copy: the total/defensive key function with pinned crc32 literals, the differential test helper, the informational `order stats:` line. What SC does better and DC should copy: a movers report before a policy deploy, acceptance numbers in the `full_seed` gate, the refresh hooks after the three runtime `pos`/`kind` writers (§6).

## 5 Must-fix for the winner (derived-column)

1. **Do not trust `LEARN_ORDER_VERSION` alone.** `is_current` fires on version / seed stamp / NULL rank; a policy edit that forgets the bump leaves stale ranks until someone runs `wd check db`. A full stored-vs-computed compare costs 6.8–18 ms on 9,618 rows (check E, author's 18 ms): make `ensure_current` run it at startup (or compare a digest of `rank_rows()` stored in `kv.learn_order.digest`) and recompute when it differs; additionally pin `LEARN_ORDER_VERSION` to a golden digest of `rank_rows(mini seed)` in `test_learn_order.py` so a policy change without a bump fails the suite.
2. **Make `rank_for` per-row pure, with the spread of frequency-less words by `zlib.crc32(lemma)` (never `hash()`), and pin the crc32 literals** (`monday 3755093257`, `ice cream 2295515455`, `schoolbag 3192515231`, `p.e. 3170141767` from QT §1.4). Then `best_effort_rank` for ECDICT/provisional rows equals the full recompute, `learn_rank_matches_policy` stays at 0 between recomputes, and the single-row path is exact rather than approximate (DC §1.6's own recommendation becomes a requirement).
3. **Fill the ranks in `deploy/install.sh` and in `wd migrate`-only paths, not only at service start.** Add `wd learn-order` after `wd import-seed` (`install.sh:141`; idempotent, ≤ 41 ms, refuses below schema 14 like `import-seed`). Otherwise `wd check db` run between `install.sh` and the unit start reports `learn_rank_present: N violation(s)`, and a `--no-restart` upgrade serves NULL ranks (today's order, but inconsistent with the runbook's "seven lines ok").
4. **Every per-row computation must be total.** Coerce `frq`/`bnc` with `int()` under `try`, route `pos` only through `dominant_pos` (label-shaped Claude values → `None` → content word), treat `stage_min` outside `STAGE_INDEX` as the 课标外 group; `recompute` must never raise on one row (log once, rank `None` for that row — it then sorts by the frq tail). Pin this with the parametrised garbage-input test QT §5.1 describes.
5. **Handle the cross-row ripple in the seed tests.** `test_seed.py:40 word()` is `SELECT *`; after 0014 it includes `learn_rank`. A stage-statistics-dependent policy can legitimately change the rank of an untouched record when another record moves stage (`test_changed_record_updates_only_that_row`, `test_never_touches_user_data_content_pointers_or_alt_forms`). Either compare `SEED_COLUMNS` explicitly in those tests or state in DESIGN §3.2 that `learn_rank` is derived and may move with the stage's statistics; `SeedStats.learn_rank_changed` reports it. (With must-fix 2 and the mini seed's six frq-less records — `a.m.`, `email`, `ice cream`, `ought to`, plus `is`/`an` via `bnc` — the ripple is confined to those rows.)
6. **Decide lookup suggestions (`routers/words.py:106`) explicitly and record it in API.md 22.** DC follows the learning order (one tail everywhere); QT argues "commonest word with this prefix" is the right ranking for autocomplete (`the` below `theatre` for `th`). Either is defensible; the owner decides, the doc states the exception or its absence, and `test_words.py:86-87` follows.
7. **Fix the `v_bank` sentence** in the 0014 header and §2.1: the view is `SELECT uw.*, w.lemma, …` (named `w.` columns); the safety argument is the same.
8. **Keep 0014 minimal unless the index earns its place.** No plan uses `ix_words_learn_rank` (author's measurement, reproduced); the startup NULL probe is 0.02 vs 0.43 ms without it. Either drop it (one `ADD COLUMN`, the 0012 shape) or keep it with the justification shortened to "the startup / `wd check` probe" — do not justify it by symmetry with `ix_words_frq`.
9. **Rehearsal before the Mac restart must run the recompute over the full live copy and print the 小学 / 初中 head** (already in `check_0014` step 5–6) — make it a numbered step of the release note with the expected first lemmas copied from the rehearsal output, not from the design document, and `wd check db` on the copy showing seven `ok` lines before `launchctl kickstart`.

## 6 Grafts from the other two designs

From **query-time**:

* `reference_order(settings, where_sql)` test helper: open `db.connect`, compute the stats, sort the rows with the Python key — the three integration tests (`test_vocab.py:93`, `test_screen.py:122/:142`) and `test_batches.py:104` then pin no policy literal; plus the differential test "SQL `ORDER BY ORDER_SQL` == `sorted(rows, key=rank_for)`" over the seeded database for 全部, each stage flag and the `_STAGE_DISTANCE`-prefixed form.
* The informational `order stats:` line in `wd check db` (`xs 64/721/4978 · zk 413/1622/5957 · … · frq-less 758 (bnc 225, spread 533)`) — never flips `ok`, but tells the operator what the band is.
* The documented rule that the stats cache / stored stats are *derived from `words`*, with the per-stage triples quoted from a run, not typed into docs (QT §2.1 lists today's six live triples; DC should print them from `wd learn-order --dry-run`).
* The `WORD_LIBRARY_CURATION.md:150` rewrite that keeps the C10 warning true and adds `pos` to the columns an admin must set together.

From **seed-carried**:

* A **movers report** before a policy deploy: `wd learn-order --dry-run` prints, per stage, `records · rank changed · moved ≥ 50 places · max shift · first 10 old → first 10 new` and the 20 biggest climbs/drops against the stored ranks (SC §2.4's section (f), computed from the table instead of two files). This is the review artefact DC lacks and the owner will want for every tuning iteration.
* Acceptance numbers in the `full_seed` gate: `GET /api/vocab?stage=xs` first 8 lemmas equal `wd learn-order --report` output committed next to `stats.json` (one place, numbers never in prose), `stale_count == 0`, every stage word ranked.
* The `refresh(conn, word_id)` one-liners after the three runtime writers that change rank inputs (`ai/lookup.py:317/:368`, `ai/consolidate.py:292`, `services/suggestions.py:418`) — DC leaves them optional; with must-fix 2 they are cheap and make `learn_rank_matches_policy` hold continuously, not only after a restart.
* The `format_stats` clause (`…, N learn ranks changed`) and the `system_events('seed_imported').learn_order` detail for the admin page.
* The CI-style assertion that the committed policy artefacts agree with the code (SC: `stats.json.learn_order.policy == POLICY_VERSION`; DC equivalent: the golden digest of must-fix 1).

Not grafted, deliberately: SC's `DELETE FROM kv WHERE key='seed_version'` in the migration (a forced full re-import is exactly the write DC avoids), SC's `learn_rank` as a `SEED_COLUMN`, QT's TTL cache (DC stores the stats table in `kv`).

## 7 Residual risks the winner still carries

* **Policy still open.** Every number above was measured with the FACTS §2 stand-in; the mechanism is policy-independent, but the owner will see `an` at position 3 of 小学 (empty `pos`) and `is` at 593 until the policy decides on inherited forms, adverbs and frq-less words. The movers report (graft) is the tool for that conversation.
* **Label.** `sort=freq` keeps its wire name; `词频` becomes untrue the moment function words move to the end. The two-line copy change (`zh.ts:48` + `FRONTEND.md:254`, `npm run check:copy`) needs a frontend snapshot; ship it as a separate commit so the backend fix remains restart-only (both DC and SC say this; agreed).
* **WAL growth** +4.7 MB per full recompute — auto-checkpointed; no action.
* **Runtime rows ranked from the stored stats table** use the statistics of the last recompute — intended, and with must-fix 2 identical to what the next recompute produces.
* **Lighthouse SQLite version unknown** (PLAN §9.2 #6) — 0014 is `ADD COLUMN` only; run `scripts/rehearse_migration.py` on the box anyway, as the K-12 release note already requires.

## Appendix — files

* This document: `…/scratchpad/order/judge-mech-operations-and-data-integrity.md`
* Judge script and output: `…/scratchpad/order/sim-judge-ops/judge_checks.py`, `…/sim-judge-ops/judge_checks_output.txt` (read-only live copy + a scratch copy created and deleted inside `sim-judge-ops/`)
* Re-runs of the authors' scripts (copied, unchanged): `…/sim-judge-ops/reuse-qt/run.log`, `…/sim-judge-ops/reuse-dc/run.log` (scratch DB `scratch-word-dance.db` in that directory), `…/sim-judge-ops/reuse-sc/run.log` (+ `vocab-v3.jsonl(.gz)`, `vocab-v2-fallback-ranked.jsonl`, `mig0014/` written there by the script)
* All runs: `/Users/sqin/word-dance/.venv/bin/python -I <script>`; nothing bound a port, nothing in the repository or the live data directory was modified.
