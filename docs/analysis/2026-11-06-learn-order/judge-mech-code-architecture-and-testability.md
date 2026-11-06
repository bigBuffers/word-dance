# Mechanism judge — lens "code architecture and testability" · 2026-11-06

Inputs: `FACTS.md`; the three mechanism papers `mech-query-time.md`, `mech-derived-column.md`, `mech-seed-carried.md`; the
repository `/Users/sqin/word-dance` @ `cd3df8c` (read only, tree clean before and after this task); the read-only live copy
(`mode=ro&immutable=1`); the three papers' simulation suites (re-run, outputs under
`sim-judge-mech-code-architecture-and-testability/rerun-*.txt`) and my own probes (`probe_judge.py` → `probe_judge_output.txt`,
same directory). The policy (which word comes first) is still open; every paper uses the FACTS §2 stand-in only to make costs
realistic, and so does this judgement — nothing below depends on the final policy except where it says so.

Terms: 小学 = xs (stage index 1), 初中 = zk (2), 筛词 = `GET /api/screen/next` + onboarding, 推荐词 = the `kind='screen'`
rows of a daily batch, 词库 = `GET /api/vocab` (`sort=freq`, label `词频`), 预生成 = admin prewarm.

---

## 0 Verdict

**Winner: `derived-column`** (`words.learn_rank` filled by a pure module, additive migration 0014, recompute at startup when
stale / inside every seed import / by `wd learn-order`, one `ORDER_SQL` constant at the five sites).

| Design | Correctness | Blast radius & deploy risk | Repo conventions | Testability | Runtime cost | Extensibility (textbook) | **Score** |
|---|---|---|---|---|---|---|---|
| query-time (UDF `wd_order_key`, nothing stored) | 6 | 8 | 5 | 6 | 6 | 7 | **6.3** |
| **derived-column** (`learn_rank` derived, stored, versioned) | 8 | 8 | 8 | 8 | 9 | 7 | **8.0** |
| seed-carried (`learn_rank` in seed v3, importer verifies) | 7 | 5 | 7 | 6 | 8 | 9 | **7.0** |

One-paragraph rationale. Under this lens the derived column is the most *boring* architecture, which is the compliment: a
pure module (`rank_rows` / `rank_for`) with no import cycle, state that is stored, versioned (`LEARN_ORDER_VERSION`,
`kv.learn_order.*`), inspectable with plain SQL (`sqlite3` CLI, tests, `wd check db`), three explicit staleness
conditions, a fail-soft tail that is provably "never worse than today" (probe P1), and test expectations that are computed
from the database through one constant instead of pinned lemmas. The query-time design is the smallest diff but buys that
with a layering inversion (`wd.db.connect` late-importing a `services` module), a hidden process-level cache with a TTL and
a lock, an order that no tool outside the Python process can reproduce, a new whole-statement failure class (a raising
UDF takes 词库, 筛词 and the nightly batches down together) and +0.3–5.3 ms on every list request. The seed-carried design
has the best review artefacts (`stats.json`, `DIFF.md` section (f)) and the best fit for a *future authored* textbook
order, but it stores a value the importer recomputes anyway (two sources of truth that can disagree, "the seed wins"),
turns every policy iteration into a 1.4 MB data commit plus a fixture regeneration, rewrites all 9,618 rows (`updated_at`)
at each rebuild, touches ≈ 40 files, and its `ORDER_TAIL` has no frequency fallback — probe P1 shows 筛词/词库 collapse to
alphabetical order whenever the ranks are NULL (post-migration before the import, or after a failed import).

---

## 1 What was verified

### 1.1 File:line claims (all three papers)

Every reference I opened matched `cd3df8c`: `db.connect` 88–101 with the PRAGMA loop at 99–100 and the `backup_pre_hook`
late-import precedent at 252–261; `main.startup` 484–503 (`run_migrations` :489, `seed_check` :492, `public_url_guess`
:493, import `from .seed import import_seed, seed_digest` :68); `seed_check` 299–326; `vocab._ORDER` 75–82 (`freq` :76,
`alpha` :77, `difficulty` :81), COUNT :117, bind dict 118–121; `screen._STAGE_DISTANCE` 34–36, ORDER BY :65, `params` :62;
`batches._STAGE_DISTANCE` :60, `_SCREEN_ORDER` :61, uses at :271 (dict :272) and :697 (dict :698), `_cli_connect`
:1066; `prewarm.candidates` ORDER BY :52 with the positional tuple at :53, docstrings :5 "by frequency" / :45 "most frequent
first"; `routers/words.py:106`; `seed.SEED_COLUMNS` 71–89, `_UPSERT_SQL` 93–103 (sets `updated_at = excluded.updated_at`
whenever any `SEED_COLUMNS` value differs — so seed-carried's "every row's `updated_at` moves at the first v3 import" is
right), `_PLAN_COLUMNS` :105, `SeedPlan` 108–129, `SeedStats` 132–161, `seed_row` :243, the import transaction 469–503
(`_rebuild_forms` :476, `kv_set seed_version` :477), `format_stats` :523, CLI `db.connect` :567 and the pending-migration
refusal 572–579, `from .services.words import derive_kind, …` :60 (so `seed.py` may import a `services` module without a
cycle); `services/words.py` `_word_defaults` 569–588, `_INSERT_WORD_COLUMNS` 592–596 ("in DDL order"), `_INSERT_WORD_SQL`
597–601, `_insert_word` 604–611, `_resolve_ecdict` :667, `_create_provisional` :703, `from .. import db, images` :26,
`derive_kind` :148; the runtime `UPDATE words` sites `ai/lookup.py` :272/:317/:368 (+ :377), `ai/consolidate.py`
:292/:311/:418, `services/suggestions.py` :418/:432 with `RESTORABLE_WORD_COLUMNS` :44; `diag.STAGE_INVARIANTS` 50–57,
`STAGE_INVARIANTS_FROM_VERSION` :58, `check_db` 81–112 (kv tuple :97, seed-version line 105–107), `_seed_version_line`
129–156 (late import of `seed_digest`), `collect_stats` :270, `__all__` :361; `scripts/rehearse_migration.py` constants
54–58 (`EXPECTED_TABLE_COUNT = 25`, `BOOKKEEPING_TABLES`), `snapshot` 129–158, `check_bookkeeping` 162–175, the index pin
`wanted <= index_names` :215 (a *superset* check — adding `ix_words_learn_rank` passes), `check_0012` 254–269, `check_0013`
272–289, `check_invariants` 291–299, `check_empty_database` 302–319, dispatch 361–376, `db.connect` :307/:335;
`cli.CLI_MODULES` 31–42, `COMMAND_OWNERS` 45–56 (`test_cli.py:58` asserts the two key sets are equal); `seedbuild/build.py`
`SEED_V = 2` :83, `RECORD_KEYS` 102–105, `DICT_KEYS` 107–109, docstring 51–56, `make_records` :839, out-dict 927–934, sort
:952, `BuildStats` :977, `compute_stats` :1022 (`derive_kind` used at :1039), `_summary` :1299; `seedbuild/diff.py`
`FIELD_KEYS` 49–51, `Diff` :141, `compute` :177, `check_invariants` :233, `render_md` :274; `images/style.py`
`FUNCTION_POS` :35, `dominant_pos` :39 (returns `None` for empty / label-shaped `pos`); `images/card_svg.py` LRU key
`(word_id, active_content_id, updated_at)`; migrations `0010` (ADD COLUMN + CREATE INDEX), `0012` (ADD COLUMNs only),
`0011` (`DELETE FROM kv WHERE key = 'seed_version'` :132 + `system_events` row :133 — the DML precedent seed-carried
cites); `deps.get_db` 67–74, `scheduler.maintenance` :380 and its `connect()` 529–530, `worker.py` :376/:387,
`tests/conftest.py` :145/:159, `deploy/install.sh` stop :123, `wd migrate` :140, `wd import-seed` :141, restart :158.

Tests pinned today, all at the quoted lines: `integration/test_vocab.py:93` (first lemma `be`, `frq` ascending, NULL last,
the `WordBrief` key set at 106–109), `:163` (`sort_key` lambda :174); `integration/test_screen.py:122` (`absorption, axe,
ought to` :130; `go, person, better` :136), `:142` (`expected_xs` :150 through `qrows`, which opens `db.connect` — so a
UDF would be available there), `:161`; `unit/test_batches.py:104` (`screens == ["absolutely", "axis"]` :129), `:152`
(kinds only); `integration/test_words.py:86–87`; `integration/test_admin_ops.py:488` (set equality); `unit/test_diag.py`
`INVARIANT_NAMES` :27, `:49–57` (line 57: *every* line after `kv.backup.last` must start with `invariant `), `:182–190`,
`:195–203` (`count("\n    invariant ") == 4` :199); `unit/test_db.py:21`, `:42–60`, `docs/SCHEMA.sql` byte pin :523–526;
`unit/test_db_0012.py` / `test_db_0013.py` exist (the pattern for a `test_db_0014.py`); `unit/test_seed.py` :245, :283
(`word(conn, "apple") == apple_before` compares the **whole row**, `SELECT *`), :323, :476 (`test_import_is_atomic`), :489
(`test_import_joins_an_open_transaction` — a nested `db.tx` raises, so an import-path recompute must use `db.maybe_tx`),
:497, :624 (`full_seed`); `unit/test_seedbuild_build.py:427` (`seed_v == 2` :435), `:463` (`seed_v == 2` :477, first six
`stats.json` keys pinned); `unit/test_seed_diff.py:80`, `:130`; `unit/test_main_seed_check.py:30–36` (`kinds()` filters
`'migration'`, so a migration's `system_events` row does not break it); `unit/test_words_resolve.py:131`, `:271`.

Docs: `API.md:169` (endpoint 20 ORDER BY literal) and `:187` (endpoint 31 "by frequency"); `DESIGN.md:32`, `:196` (§3.2
heading "record format **v2**"), `:205` (row "`0`/`null` frequency = unknown (sorted last)"), `:350` (§6.2 last sentence),
`:363–370` (§6.3 step 4); `FRONTEND.md:56`, `:145–147`, `:254` (byte mirror of `zh.ts:48`, `sort: { freq: '词频', … }`);
`VocabPage.tsx:34` `SORTS`; `endpoints.ts:133` `VocabSort`; `schemas.py:503` `sort: Literal[…]`;
`CLAUDE_INTEGRATION.md:303`; `WORD_LIBRARY_CURATION.md:150` (选词规则 核验 C10) and `:296`; `releases/2026-11-k12-stages.md:212–213`;
`PLAN.md:755` (§9.2 #5 — the seed-carried paper says `:749`, the section heading; harmless); `DEPLOY.md:361/:421/:425`;
`ops.md:19/:117–120/:123`. Also found: `docs/TASKS.md:172` lists the four invariant names in a runbook line — **none** of
the three papers lists it among the docs to update (§4 must-fix 6).

### 1.2 SQLite / sqlite3 behaviours the designs lean on (probed, Python 3.12.16, SQLite 3.54.1)

NULL sorts first in `ORDER BY … ASC` ✓ (the query-time paper's B2 trap is real); extra named parameters in a bind dict are
ignored ✓ (so `{**params, **stats_params}` may feed the sibling COUNT); a missing name raises `ProgrammingError` ✓; mixing
`?` and `:name` raises ✓ (prewarm's tuple must become a dict, as the paper says); a raising UDF fails the whole statement
with `OperationalError: user-defined function raised exception` ✓; a UDF returning NULL sorts first ✓; a connection without
the registration says `no such function` ✓; `create_function(…, deterministic=True)` accepted ✓; `exp()`/`ln()` present on
the Mac build (`ENABLE_MATH_FUNCTIONS`) ✓ — unknown on Lighthouse, which is why the paper's UDF variant (no math functions
in SQL) is the right one of its two options. Live copy: schema `1,8,9,10,11,12,13`; 9,618 words, all `source='seed'`,
0 merged, 16 distinct `updated_at`; `kv.seed_version 24f3b9496c14…`; 2,300 pages with 773 on the freelist (which is why
"ADD COLUMN + index, 2,300 → 2,300 pages" is consistent — the 27 index pages come from the freelist); `sqlite_stat1`
present; 727 rows with NULL/empty `pos`.

### 1.3 Simulation suites re-run (exit 0, repository untouched)

* `sim-qt/bench_query_time_v2.py` (2.1 s, read-only URI): site table reproduced — 词库 全部 p1 1.37 → 6.06 ms, p40 4.41 → 9.74,
  词库 小学 0.66 → 1.04, 筛词 ×30 1.02 → 2.29, 推荐词 ×15 0.83 → 2.09, 加练 1.01 → 2.28, 预生成 0.71 → 1.04; plans identical to
  the baseline; the differential check (SQL under the UDF == `sorted()` with the same key) identical on xs 600 / zk-new
  1,949 / cet6 7,671 / all 9,618 rows; quantile methods agree (2.47 ms Python vs 6.45 ms window CTE); `MAX(updated_at)`
  probe 0.44 ms (a scan) vs 0.001 ms for `kv` / `COUNT(*)` / `MAX(id)`.
* `sim-derived-column/sim_recompute.py` + `sim_extend.py` (0.9 s, scratch copies in their directory): 0014 2.2 ms; recompute
  9,618 rows 41 ms (read 5.7 / compute 11.4 / write+commit 24.0), no-op 18 ms; stale diff 18.2 ms; startup probe 0.03 ms
  via the index, 0.43 ms as a scan without it; WAL +4.7 MB per full recompute; the five list queries keep their plans and
  timings with or without `ix_words_learn_rank`; the robust tail puts two NULL-rank rows last by frq.
* `sim-seed-carried/sim_seed_carried.py` (4.2 s, private copies + v3 files in its directory, importer patched in process):
  `rank_all` 16.4 ms; jsonl +194,090 B, gz 1,342,623 → 1,383,800 B; rebuild from own output identical; old server (schema 13)
  reads the v3 seed `0 inserted / 0 updated` in 342 ms; rollback (old importer, schema 14, v2 file) `0/0` in 324 ms, column
  untouched; `page_count` unchanged.

### 1.4 Discrepancies found in the papers

| Paper | Claim | Finding | Weight |
|---|---|---|---|
| derived-column | "`v_bank`'s `w.*` column list was fixed when the view was created" (§2.1 migration header, Appendix "`v_bank` uses `w.*`") | The view is `SELECT uw.*, w.lemma, w.display, …` — the `sim_extend.py` test `"w.*" in sql` matched the substring of `uw.*`. And in SQLite a `SELECT w.*` view **does** pick up a column added later (probed: `v_star` gained `learn_rank`). The conclusion (0014 cannot change `v_bank`) still holds because the `words` columns are listed explicitly. Fix the header comment (§4 must-fix 4). | low |
| query-time | `wd check db` gains an informational `order stats:` line after the invariant lines (§4.1) | `test_diag.py:57` asserts every line after `kv.backup.last` starts with `invariant `; the line must be emitted before `kv.backup.last` (as a `kv.`-style line) or the test must change — the paper's §5.2 row for `test_diag` does not say so. | low |
| derived-column | "`test_seed.py::test_changed_record_updates_only_that_row` already enforces the rule for the import" (§1 principle 3) | True for `updated_at`, but the test compares the **whole** `apple` row. An import-path recompute may re-rank *other* rows of the moved record's stage group (probe P2: `a.m.` changes under every stats-dependent policy). The test survives only because `apple` is a frequency-bearing 小学 word. Not wrong, but the paper does not name the ripple that seed-carried names (its §8.1 risk 3). | medium → must-fix 1 |
| seed-carried | "`NULL` = not ranked, sorts last … the same contract `frq` NULL/0 has today" (§0) | Only inside a group of ranked rows. With every rank NULL (between 0014 and the import, or after a failed import) `ORDER_TAIL` has no fallback and the lists are alphabetical (probe P1). | medium |
| seed-carried | `PLAN.md:749` for §9.2 #5 | The item is at :755 (:749 is the section heading). | nil |
| all three | `docs/TASKS.md:172` | Lists the four invariant names; not in any paper's doc table. | low |

---

## 2 Criterion by criterion

### 2.1 Correctness — exact dominant POS, deterministic, cross-row statistics possible

All three read `pos` only through `wd.images.style.dominant_pos` (D-images-24) and get the 54 first-letter disagreements
right by construction (`one`, `answer`, `light` … stay content words). Differences:

* **Determinism.** query-time's key is a pure function of the row and of per-stage quantiles that are *computed from the
  live table and cached per process for ≤ 600 s* (`kv.seed_version`, `COUNT(*)`, `MAX(id)` as the key). A runtime word
  created by a lookup moves the quantile band of its group for every reader on the next cache miss; an in-place `frq` fill is
  invisible for up to ten minutes, so the server and `wd order` can disagree for that window. Derived: the stored rank changes
  only at explicit recomputes (startup when stale, import, CLI) — stable between them, and drift from the four runtime
  `pos`/`kind` writers is *reported* (`learn_rank_matches_policy`). Seed-carried: frozen per seed — the strongest
  "same seed → same order on every server" — but a server whose policy differs from the seed's keeps the seed's values with a
  warning: deterministic, yet possibly not what the running code says.
* **Cross-row statistics.** query-time can only pass what fits in bound parameters (18 per-stage quantiles); exact positional
  spreading (sort the frequency-less words of a stage and give the j-th the j-th quantile — one of the FACTS §2 open options)
  is impossible per row, and the crc32 spread is its approximation (KS 0.038 on the 381 上海词组). Derived: `rank_rows` sees
  the whole table, so any cross-row rule is expressible; the single-row path (`best_effort_rank` for a new ECDICT/provisional
  word) is approximate until the next recompute and the paper says so. Seed-carried: the builder sees the whole file; the
  §1.2 contract (`rank_all == rank_for ∘ stage_stats`) is the same restriction derived places on `rank_for`, with the stats
  allowed to carry lists.
* **Fail-soft order.** Probe P1 (scratch copy, column added, no fill), 筛词 for a 小学 主攻: today `the be and of a in to have
  it i that for`; derived `ORDER_SQL` → identical to today; seed-carried `ORDER_TAIL` → `a about after afternoon again age ago
  air all also always am`; 词库 全部 under seed-carried → `a a bit a bit of a couple of …`. With a single unranked row (`the`),
  both tails put it after the ranked rows of its group (derived at 570, seed-carried at 597 of the 600-word 小学 block, the
  difference being the 30 frq-less rows my pretend fill also left NULL). query-time has no NULL state at all (its risk is the
  raising UDF instead).

Scores 6 / 8 / 7.

### 2.2 Blast radius and deployment risk (Mac today, Lighthouse later)

| | query-time | derived-column | seed-carried |
|---|---|---|---|
| Migration | none | `0014`: ADD COLUMN (+ index), additive, 0012-class, 2.2 ms; applied by `wd serve` at restart with the pre-migrate snapshot | `0014`: ADD COLUMN **+ `DELETE FROM kv seed_version` + `system_events` row** (0011 precedent), 7 ms; forces a 0.4 s import of all 9,618 rows |
| Data rewritten | none | `learn_rank` of changed rows only (never `updated_at`); WAL +4.7 MB per full recompute | all 9,618 rows at the first v3 import and at every policy rebuild (`updated_at` 16 → 1 distinct value, card LRU emptied) |
| Seed / fixtures | unchanged | unchanged | `vocab.jsonl.gz` (+41 KB), `stats.json`, `DIFF.md`, `ATTRIBUTION.md`, `tests/fixtures/mini_seed.jsonl` (v3) + a v2 copy regenerated |
| Files / lines (papers' own counts) | ≈ 16 / ≈ 550 | ≈ 14 code + 7 test + 9 docs / ≈ 880 | ≈ 40 / ≈ 1,000 + regenerated data |
| Mac deployment | `git checkout` + `launchctl kickstart -k` | the same; startup migrates (2 ms) and fills (41 ms) before serving | the same; startup migrates (7 ms) and imports (0.4 s) |
| New failure classes | raising UDF → every list statement fails; a connection opened outside `db.connect` → `no such function`; `hash()` instead of `crc32` → per-process reshuffle | `ensure_current` failure → fail-soft (today's order) + `learn_order_failed` event; a raising `rank_for` inside `import_seed` would roll the **seed import** back (§4 must-fix 2) | import fails after 0014 → all ranks NULL → alphabetical lists until fixed (P1); policy/seed version mismatch → warning, seed wins |
| Rollback | restart on the previous commit | code-only (old code ignores the column; every `INSERT INTO words` in `backend/wd` names its columns — grepped; `sqlite3.Row` readers by name) | code-only (old `seed_check` re-imports the v2 seed: `0/0`, measured) |
| Lighthouse | `install.sh` as is (`--no-restart` pointless) | `install.sh` as is: `wd migrate` applies 0014, the unit start fills; `--no-restart` allowed, leaves old code serving frq | `install.sh` as is: `wd migrate` then `wd import-seed` fills before the start; rehearsal prints two `[skip]` lines until the import |

query-time is the smallest footprint and the only one with zero schema risk; derived is one additive file away from it and
is the only design whose worst case is provably "today's order"; seed-carried's DML migration, forced full rewrite and data
churn are the largest surface, and its all-NULL window is the one deployment state that is visibly *worse* than today.
Scores 8 / 8 / 5.

### 2.3 Consistency with repository conventions

* **Single sources.** All three keep `schemas.STAGE_ORDER` the stage source (query-time renders its CASE arms from
  `STAGE_INDEX`, the other two group by `stage_min`). query-time keeps `_STAGE_DISTANCE`'s two copies optional to unify; the
  others leave them. Seed-carried introduces a *second source for a derived value*: `learn_rank` is in the seed **and**
  recomputed by the importer for verification; disagreement is tolerated ("the seed wins"). Under a single-source lens that
  is the design's structural flaw; the derived column has exactly one producer (`rank_rows`) and the query-time key exactly
  one (`order_key`).
* **Doc ↔ code binding.** All three add `test_docs_contract` pins (derived/seed-carried pin the ORDER BY literal in API.md §20
  and DESIGN §6.3; query-time pins the function name and the seven input columns). All three update API.md 20/31, DESIGN §3.2
  / §6.3 / §6.2, FRONTEND §4/§8, CLAUDE_INTEGRATION :303, WORD_LIBRARY_CURATION :150, the release note and PLAN §9.2 #5.
  `TASKS.md:172` is missing from all three.
* **Invariants (`wd check db`).** derived (3 lines: `learn_rank_present`, `learn_order_current`, `learn_rank_matches_policy`)
  and seed-carried (2 lines) add *data* invariants, which is what the convention means; query-time's two lines check code
  registration and totality — useful, but there is no stored data to check, and the `sqlite3` CLI (the tool
  WORD_LIBRARY_CURATION's admin recipes assume) cannot evaluate the order at all.
* **Rehearsal.** derived and seed-carried add `check_0014` in the `check_0012` shape plus the 小学/初中 head preview;
  query-time adds `check_order` (nothing migrates). All keep `EXPECTED_TABLE_COUNT = 25` and `check_empty_database`.
* **"Seed numbers live in stats.json, never constants in docs."** Seed-carried extends `stats.json` with a `learn_order`
  block and `DIFF.md` with section (f) — the best review artefact of the three. derived/query-time have nothing comparable
  (the derived paper's rehearsal preview and `wd learn-order --show` are the operator's view; a movers report is a cheap graft,
  §5).
* **Layering.** derived: `services/learn_order.py` imports `db`, `clock`, `schemas`, `images.style` only; importers are
  `seed`, `main`, `services.words`, `diag`, the rehearsal script — no cycle (verified: `services/__init__.py` is a docstring,
  `services/words.py:26` already imports `images`). seed-carried: `wd/learn_order.py` top-level with eight importers incl.
  the builder, and `kind` passed in to avoid importing `services.words` — clean but the widest fan-in. query-time: `wd.db` →
  (late) `wd.services.order` → `wd.images.style`: the DB layer learning about a learning-order policy; the cited precedent
  (`backup_pre_hook`) imports a peer infrastructure module on demand from a function callers invoke, not from `connect()`
  itself, so it is a weaker precedent than the paper suggests.
* **Migration content.** seed-carried's DML in a migration has the 0011 precedent, but 0011 needed it (renumbering); here it
  is only a trigger for the fill — a side effect (`seed_version_matches_file: 1 violation(s)` until the import) that the
  derived design avoids by filling from the code path that owns the data.

Scores 5 / 8 / 7.

### 2.4 Testability

* **query-time.** `order_key` is unit-testable without a database and the differential test (SQL order == `sorted()` with the
  reference key) is strong. Against it: a process-level cache with a TTL and a lock means fixtures must call
  `invalidate_stats()` and TTL tests need a monkeypatched clock; the UDF needs a totality matrix (every garbage input → a
  finite float) because the alternative is every list statement failing; every ordering test must run through `db.connect`
  (they do today, but a bare `sqlite3.connect` in a future test silently gets `no such function`); `test_db.py`'s connect test
  grows an assertion about a `services` function; nothing can be checked from the `sqlite3` CLI; and the three integration
  tests need a `reference_order` helper because the API items lack `pos`/`bnc`/`sources`.
* **derived-column.** `rank_rows` / `rank_for` pure; stored ranks readable with plain SQL in any test; expectations computed
  through `learn_order.ORDER_SQL` (one constant) instead of pinned lemmas; `is_current` has three enumerable conditions each
  with a test; `recompute` idempotence, "writes only changed rows", "never `updated_at`", "joins an open transaction" are
  all one-assertion tests; `test_db_0014.py` follows the existing `test_db_0013.py` pattern; policy literals confined to
  `test_learn_order.py`; `wd learn-order --dry-run / --show` is scriptable. The two testability hazards are (a) the ripple of
  probe P2 — a stage move of one record may change the stored rank of a frequency-less word of the affected group inside the
  same import (`stats.updated` is computed from `total_changes` *before* the recompute, so the `(0, 1)` assertion holds, and
  `updated_at` does not move, so the LRU rule holds; but any future whole-row comparison on such a word would fail) — and
  (b) a non-total `rank_for` aborting an import. Both are one test each (§4).
* **seed-carried.** Pure module ✓ and literals in one file ✓, but every policy iteration regenerates the mini fixture (as v3)
  and the committed seed, keeps a v2 copy for fallback tests, and touches ≈ 12 test files (builder, diff, importer, diag,
  resolver, lookup-apply, docs-contract …). The ripple is acknowledged and dodged by shipping the fixture ranked — which also
  means the suite never exercises the fallback on the main fixture. The verification path (`rank_mismatch`) adds a third
  outcome ("stored ≠ computed, kept") that tests must cover.

Probe P2 numbers (mini seed, `abandon` moved to `['zk','gk','cet4','cet6']` as `test_changed_record_updates_only_that_row`
does): under `p50-constant`, `crc32-band` and `positional` stand-ins exactly one other row changes rank — `a.m.` (the only
frequency-less 初中-first word): 536 → 567 / 569 → 754 / 536 → 567; `apple` is unchanged in all three. Frequency-less rows
in the fixture: xs `email`, `ice cream`; zk `a.m.`; cet6 `ought to` — the rows any stats-dependent policy exposes.

Scores 6 / 8 / 6.

### 2.5 Runtime cost

query-time: +0.48 µs per candidate row (probe P3: `dominant_pos` 0.163 µs, the whole stand-in key 0.234 µs in Python, so
about half of the measured delta is the SQLite → Python callback) → 词库 全部 +4.7 ms (6.06 ms), page 40 9.7 ms, 筛词 +1.3 ms,
nightly batch +1.3 ms per user, plus ≈ 0.003 ms of cache probes per request. derived: lists unchanged (plans and timings
within noise), 41 ms at a stale start, 18 ms per `wd check db`, WAL +4.7 MB per recompute. seed-carried: lists unchanged,
0.4 s import per seed change, +41 KB gz. Scores 6 / 9 / 8.

### 2.6 Extensibility to a textbook / grade order

A 教材/年级/单元 order is *authored* data: whichever mechanism wins, that field must travel through the seed pipeline
(builder key, importer column, `stats.json`, `DIFF.md`). Seed-carried builds exactly that scaffolding now (`RECORD_KEYS`,
`FIELD_KEYS` exclusion, diff section (f), per-key invariants) and composes per-user choice at request time
(`order_tail(settings.order_key)` with `COALESCE`) — the best fit. derived absorbs it as one more `INPUT_COLUMN` of
`rank_for` via an additive 0015 and a version bump (per-user → per-scheme columns or a side-table join; both keep the five
sites). query-time takes it as a leading `COALESCE` key or an 11th UDF argument and handles per-user selection most naturally
(bound parameters already are its channel) but, like derived, still needs the seed pipeline it does not build. Scores 7 / 7 / 9.

---

## 3 Why derived-column wins under this lens

1. **One producer, one constant, one place to look.** `rank_rows` is the only thing that writes `learn_rank`; `ORDER_SQL` is the
   only thing that reads it; `LEARN_ORDER_VERSION` + `kv.learn_order.seed_version` + "a stage word has NULL rank" are the only
   reasons to recompute. Every piece is enumerable and therefore testable.
2. **Inspectable state.** `SELECT lemma, learn_rank, frq FROM words WHERE stage_min = 1 ORDER BY learn_rank LIMIT 40` answers the
   owner's question in the `sqlite3` CLI, in a test, in the rehearsal and in `wd learn-order --show`. query-time's order exists
   only inside a Python process; seed-carried's is inspectable but may not be the running code's.
3. **Fail-soft is provable.** The `frq` tail of `ORDER_SQL` makes "NULL rank" exactly today's behaviour (P1) — a property a
   single test can pin forever.
4. **Policy iteration is cheap while the policy is open.** Edit `rank_for`, bump the version, run the unit file, restart (41 ms).
   No seed rebuild, no 1.4 MB commit, no fixture regeneration, no `updated_at` churn.
5. **It uses the conventions as they are.** Additive migration like 0010/0012, `wd serve` self-migrates, `check_0014` like
   `check_0012`, a CLI module in `CLI_MODULES`/`COMMAND_OWNERS`, three `wd check db` data invariants, late imports in `diag`
   exactly like `_seed_version_line`.

What would have changed the verdict: if the policy were already decided and frozen for a year, seed-carried's reproducibility
(same seed → same order everywhere, reviewed in `DIFF.md`) would outweigh its churn; if the repository forbade new columns or
the Lighthouse SQLite were suspect, query-time's zero-schema footprint would win despite the layering cost.

---

## 4 Must-fix for the winner (derived-column)

1. **Pin the ripple (probe P2).** Add `test_seed.py::test_changed_record_may_rerank_only_frequency_less_words_of_its_stage_group`:
   move one record between stages, assert `(inserted, updated) == (0, 1)`, `apple` unchanged including `learn_rank`, `updated_at`
   unchanged for every row but the moved one, and that the set of rows whose `learn_rank` changed is ⊆ the frequency-less words
   of the two stage groups involved. State the ripple in the module docstring and in DESIGN §3.2 ("a seed change may re-rank
   frequency-less words of the affected stages; `updated_at` never moves for them").
2. **Make `rank_for` total and the import-path recompute fail-soft.** A raising policy inside `import_seed` would roll the
   whole seed import back (`seed_check` would then log `seed_import_failed` and the vocabulary would stay stale). Coerce every
   input (`int()` under `try`, `str()` for `sources`), never raise, and wrap the call in `import_seed` so a policy exception is
   logged as `learn_order_failed` while the import commits (ranks stay NULL → today's order). Unit matrix: `None` everywhere,
   text in `frq`, `pos='v./n.'`, `pos='n:x/v:1'`, `stage_min=99`, negative/zero frequencies, bytes → an `int` or `None`, never
   an exception (graft from query-time §5.1).
3. **Pin the fail-soft tail.** `test_learn_order.py::test_null_ranks_fall_back_to_the_pre_0014_order`: on a migrated, unfilled
   database the five sites return exactly the `(frq IS NULL OR frq = 0), frq, lemma` order (P1), and one NULL row sorts after
   every ranked row of its stage-distance group.
4. **Correct the 0014 header comment.** `v_bank` is `SELECT uw.*, w.lemma, w.display, …` — its `words` columns are explicit, that
   is why ADD COLUMN cannot affect it; drop the "`w.*` fixed at creation" sentence (false for SQLite, and the file is the
   column's schema documentation). Same sentence in the paper's appendix.
5. **`is_current` must also see a policy bump on an unchanged seed after a code-only rollback and roll-forward**: the paper's three
   conditions cover it (version ≠ code), but add the test "old code imported a seed while the column existed → `kv.learn_order.seed_version
   ≠ kv.seed_version` → recompute" explicitly, since that is the only reason the seed stamp exists.
6. **Docs that enumerate the invariant names**: `docs/TASKS.md:172` and `docs/ops.md:19/:123` (the paper lists ops only); the
   K-12 release note :180 is historical and stays. `test_docs_contract` should pin the seven names in ops.md.
7. **Golden table tied to the version string.** `test_learn_order.py` holds ≈ 20 `(inputs → rank)` rows under a comment naming
   `LEARN_ORDER_VERSION`; editing `rank_for` without bumping the version fails the golden, forcing both edits together (the
   analogue of seed-carried's `stats.json.learn_order.policy == POLICY_VERSION` guard).
8. **Keep `kv.learn_order.stats` compact** (quantiles only, 379 B as measured; never the full lists, 54 KiB) and round-trip it
   through JSON in a unit test, because `best_effort_rank` depends on its shape.
9. **Decide lookup suggestions in the same commit** and write the decision into API.md 22 either way (the paper follows; the
   query-time paper argues prefix search wants raw frequency — `the` vs `theatre`). Under this lens one `ORDER_SQL` everywhere
   is simpler and costs one assertion in `test_words.py:86–87`; if the owner prefers commonness for search, keep that one site
   on frq and let `test_docs_contract` pin the exception.
10. **Optional simplification worth deciding now, not later:** drop `ix_words_learn_rank` (no list query uses it — measured; the
    startup/`wd check` probe is 0.43 ms as a scan; the index costs 27 pages and 5 ms per recompute). 0014 then reads like 0012:
    one `ALTER TABLE … ADD COLUMN`. If kept, keep the paper's reason (3) out of the header — it is speculative.

---

## 5 Grafts from the other two designs

From **query-time**:
* The totality discipline and its parametrised garbage-input test (must-fix 2).
* The `crc32`-based spread helper with pinned values (`monday 3755093257`, `ice cream 2295515455`, `schoolbag 3192515231`,
  `p.e. 3170141767`) and the rule "never the salted `hash()`", if the policy ends up spreading frequency-less words.
* The `reference_order(settings, where_sql)` test helper pattern for the three integration tests, so no test pins a lemma to
  a policy that is still open (the derived paper already computes expectations from the DB; make the helper shared).
* `wd learn-order --show` columns `position lemma learn_rank closed frq bnc eff` (the `wd order` layout) — the operator sees
  *why* a word sits where it sits.
* An informational per-stage statistics line in `wd check db`, emitted as `kv.learn_order.stats: xs 64/721/4978 · …` **before**
  `kv.backup.last` (test_diag.py:57), or folded into the `learn_order_current` detail.
* The explicit verified inventory of every `db.connect` caller is not needed (nothing is registered per connection), but keep
  its by-product: a grep test that the literal `frq IS NULL` appears only inside `learn_order.ORDER_SQL`.

From **seed-carried**:
* A movers report: `wd learn-order --dry-run` prints per stage `rank_changed`, `moved ≥ 50`, the ten biggest climbs and drops
  versus the stored ranks (DIFF.md section (f) without the seed) — `recompute` already has old and new values in hand; this is
  the review artefact the owner will want while tuning the policy.
* The per-stage summary block (`n, from_frq, from_bnc, fallback, closed_class, first 8 lemmas`) in the
  `learn_order_recomputed` event detail and in the rehearsal's `[info]` lines.
* `refresh(conn, word_id)` after the four runtime `pos`/`kind` writers (`ai/lookup.py:317/:368`, `ai/consolidate.py:292`,
  `services/suggestions.py:418`) **or** — cheaper and complete — a nightly `recompute` in `scheduler.maintenance` when
  `stale_count(conn) > 0` (18 ms per day) so `learn_rank_matches_policy` self-heals instead of only reporting.
* The `RankInput.from_record / from_columns` adapter pair as the single way to build the policy's input (derived's `WordInput`
  already is that; add the adapter test "record vs row of the same word agree").
* The `full_seed` acceptance additions: every seed row ranked, `stale_count == 0`, `kv.learn_order.version == LEARN_ORDER_VERSION`,
  and `GET /api/vocab?stage=xs` page 1 equals the DB order (derived names these; keep them).

---

## 6 Notes on the two rejected designs (for the record)

* **query-time** would be the right answer for a *per-user* order that cannot be stored (bound parameters are its natural
  channel) — keep the paper for that day. Its two correctable weaknesses are the layering inversion (register the UDF from
  `deps.get_db` and the few worker/CLI connect sites instead of `db.connect`, at the price of the inventory it already wrote)
  and the `order stats:` line vs `test_diag.py:57`. Its uncorrectable one is that the order is unobservable outside Python.
* **seed-carried** would be the right answer once the policy is frozen and a reviewed, reproducible order per seed release is
  worth more than iteration speed; its `ORDER_TAIL` must then get the `frq` fallback (P1) and the migration should fill the
  column from the code path (`import_seed`) rather than clear `kv.seed_version` to force it. Its textbook-order scaffolding
  (§2.6) is the part to lift when that field arrives.

---

## Appendix — probes and outputs (`sim-judge-mech-code-architecture-and-testability/`)

* `probe_judge.py` → `probe_judge_output.txt`: P1 all-NULL degradation of the two stored tails and the single-unranked-row
  position; P2 the one-record ripple on the mini seed under three stand-in policies (+ the variant where the moved record also
  loses `frq`/`bnc`: 0 / 0 / 1 other rows change for p50-constant / crc32-band / positional); P3 `dominant_pos` 0.163 µs per
  call, whole stand-in key 0.234 µs per row over the 9,618 live rows. Scratch copy created with the backup API in this
  directory and removed at the end.
* `rerun-qt-v2.txt`, `rerun-derived-recompute.txt`, `rerun-derived-extend.txt`, `rerun-seed-carried.txt`: the three papers'
  suites re-run unchanged (their scratch files stay in their own directories; the seed-carried suite deletes its copies).
* All database access to the live copy used `file:…?mode=ro&immutable=1`; `/Users/sqin/word-dance-data` and the repository
  were not touched (`git status` clean after every run).
