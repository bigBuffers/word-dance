# Adversarial review — lens: architecture, tests and documentation · 2026-11-06

Scope: the uncommitted learn-order change in `/Users/sqin/word-dance` (diff against `cd3df8c`, 37 modified files + 11 new) against
`docs/analysis/2026-11-06-learn-order/DESIGN.md`, `scratchpad/order/FACTS.md` and the repository conventions. No repository file was
modified. Every probe ran under `scratchpad/impl/review-arch/` on my own `VACUUM INTO` copy of the read-only live database
(`live/word-dance.db`, migrated 13 → 14 and filled by `learn_order.recompute`); the live data directory was never opened.

## Verdict

No blocker, no major. The mechanism is implemented as contracted and the tests pin it through the stored column (`reference_order`)
rather than through seed lemma lists; the docs edits of DESIGN §5 are all present and every docs-contract pin binds. Seven findings:
three minor (a test-coverage gap for the committed report, an install-script abort path, one stale label in a QA doc) and four nits
(two off-by-one/doc slips in the DESIGN and release note, one stale test docstring, one misleading CLI help text).

## What was verified (evidence under `scratchpad/impl/review-arch/`)

* **Import graph** (`plans.py`, shell): a fresh interpreter importing `wd.services.learn_order` loads no `wd.services.*` sibling
  (`services siblings imported: []`); `wd.main`, `wd.seed`, `wd.diag`, `wd.cli`, `wd.services.{words,screen,batches}`,
  `wd.ai.prewarm`, `wd.routers.{vocab,words}`, `wd.jobs.scheduler` and `scripts/rehearse_migration.py --help` import cleanly.
* **One ORDER BY source**: `grep -rn "frq IS NULL" backend/wd` → only `services/learn_order.py:107,122`; `_STAGE_DISTANCE` gone from
  `backend/wd`; the four learning-order sites use `learn_order.stage_distance_sql()` + `learn_order.ORDER_SQL`, lookup suggestions
  `learn_order.FRQ_TAIL`; no other `ORDER BY … frq` exists in `backend/wd` or `frontend/src` (the remaining `ORDER BY` over words rows
  are alphabetical form lists, an image sweep and consolidate — not learning lists).
* **Dead code / stale docstrings**: `_STAGE_DISTANCE` copies deleted (screen.py, batches.py; bank.py:216 docstring updated);
  prewarm "by frequency" / "most frequent first" replaced; `grep -rn "by frequency|most frequent first|按词频" backend/wd docs/*.md`
  finds only unrelated sentences (ambiguous-form candidates, DESIGN §4 lookup). AST scan (`ast_checks.txt`): no unused import in the
  new module or the six new test files; every function of `learn_order.py` is fully annotated; every `__all__` name exists; no relative
  sibling import.
* **CLI registry**: `test_cli.py:58` (`set(COMMAND_OWNERS) == set(CLI_MODULES)`) still holds with the new entry; the new tests pin the
  option set, the schema-13 refusal, exit codes and `--show`/`--report`.
* **§4.1 items 1–27 → tests** (all present): 1 `test_learn_order.py::test_constants_are_derived_from_the_image_gate_and_the_enum` ·
  2 `test_golden_table_lo_1` · 3 `test_rank_rows_is_total` + `test_from_row_coercions_and_the_class_of_garbage_rows` ·
  4 `test_dealing_formula` · 5 `test_calendar_sets` · 6 `test_glued_forms` · 7 `test_adverbs_and_interjections_are_dealt` ·
  8 `test_packing_bounds_and_order` · 9 `test_stage_distance_and_sql` · 10 `test_best_effort_rank_equals_rank_rows_for_natively_ranked_rows` ·
  11 `test_learn_order_sql.py::test_sql_order_equals_python_order` · 12 `test_no_salted_hash_and_one_frq_fragment` ·
  13 `test_learn_order_db.py::test_recompute_writes_only_changed_rows_never_updated_at_and_is_idempotent` (+ `…_writes_null_for_a_row_that_lost_its_rank`) ·
  14 `test_recompute_joins_an_open_transaction_and_rolls_back_with_it` (+ `test_dry_run_writes_nothing`) · 15 `test_ensure_current_never_raises`
  (+ `…_survives_a_write_phase_fault_and_rolls_it_back`) · 16 `test_seed_stamp_trigger` · 17 `test_stats_round_trip_and_stale_count_scope`
  (+ failing-query and calendar tests) · 18 `test_show_and_movers_report` (+ `test_report_document_shape_and_acceptance_block`) ·
  19 `test_db_0014.py::test_upgrade_0014_adds_a_nullable_column_without_rebuild` (+ fresh path) · 20 `test_null_ranks_fall_back_to_the_pre_0014_order`
  (+ vocab tab / NULL-after-fill at every site) · 21 `test_main_learn_order.py::test_startup_fills_ranks_after_the_migration_and_is_a_noop_afterwards` ·
  22 `test_seed.py::test_changed_record_may_rerank_only_dealt_words_of_its_stage_groups`, `test_seed_import_event_carries_learn_order_detail`,
  `test_policy_failure_does_not_roll_the_import_back`, the `test_import_is_atomic` / `test_dry_run_writes_nothing` additions ·
  23 `test_docs_contract.py::test_docs_quote_the_learning_order`, `test_runbooks_name_the_eight_invariants_and_the_learn_order_command`,
  `test_learning_order_copy_and_release_note` · 24 `test_diag.py` (eight names, one test per new line, v13 variant, exit code 8) ·
  25 `test_cli.py` (three tests) · 26 `test_scheduler.py::test_maintenance_recomputes_the_learning_order_once_a_day_and_survives_its_failure` ·
  27 `test_words_resolve.py` (both extensions). §4.2 renames/rewrites all present; `test_words.py:86-87` untouched as planned;
  `test_main_seed_check` unchanged and green.
* **No live-seed lemma literal in tests**: the only lemma literals are mini-seed fixture words (the golden table the DESIGN requires,
  `take good child`, `be is a an some aboard`); the full-seed tests read `data/seed/learn_order.json` / `stats.json` / SQL.
* **Docs §5**: every row present and accurate — API.md 20/22/31 texts equal `ORDER_SQL` / `FRQ_TAIL` with the `w.` alias stripped
  (checked by `sql_shape` in the contract test and by eye); DESIGN §3.2 (both rows) / §6.2 / §6.3 step 4 (+ §14 example day) match
  the constants; FRONTEND §5.5 / §8 (= `zh.ts`, `npm run lint` green per the gate); CLAUDE_INTEGRATION prewarm paragraph;
  WORD_LIBRARY_CURATION §1.5 不能做 / §1.6 选词规则 / C10 row; DEPLOY §5 / §9 / §10; ops.md §1 / §4; TASKS.md; K-12 release note §9;
  PLAN §9.2 #5 prefixed; QUICK_DEPLOY 八条 + a new 0014 paragraph; the new release note carries the runbook, rollback, the eight
  `invariant …: ok` lines, accepted costs and 未决.
* **Docs-contract pins bind** (`test_pins_bind.py`, `test_pins_bind2.py`: 18 + 2 mutations on a temp copy of `docs/` + `zh.ts` with
  `test_docs_contract.REPO/DOCS` re-pointed): the untouched copy passes; each of the 20 mutations (API 20 fragment / 22 sentence /
  31 wording / `NULL → 11`; DESIGN §6.3 fragment and `11 if s is NULL`, §3.2 row; WLC `距离为 11`; CLAUDE_INTEGRATION; ops.md order;
  TASKS list; DEPLOY §9 option; release-note invariant line and snapshot name (all occurrences); FRONTEND §8 and `zh.ts` label;
  K-12 pointer; QUICK_DEPLOY 八条 (all occurrences); ops.md "eight invariants") fails the pinned test.
* **`data/seed/learn_order.json`**: well-formed; `policy == "lo-1"`; `seed == stats.json.content_sha256 ==
  24f3b949…6692`; six stage codes; acceptance block as §2.8.
* **Performance** (`plans.txt`): `EXPLAIN QUERY PLAN` IDENTICAL old vs new at vocab 全部/xs/zk/difficulty, 筛词, 推荐词, prewarm and
  lookup suggestions (`USE TEMP B-TREE FOR ORDER BY`, same indexes); startup no-change compare 54–63 ms on 9,618 rows; first fill
  86 ms of which the write phase ≈ 23 ms (≤ 30 ms claim holds); `kv.learn_order.stats` 1,486 bytes (< 2 KB); max key 13,812,400;
  0 unranked; `updated_at` 16 distinct values before and after.
* **Policy == reference simulation on the live seed** (`probes_vs_sim.txt`): class counts `plain 9191 · adverb 390 · glued 4 · set 19 ·
  interj 14`, how counts, `closed 189`, `distinct keys 9480` identical to `sim_output.txt`; all 70 小学 probe positions, 24 初中 probes,
  the CET-4/CET-6 probes, the 词库 全部 probes (`the 526 … bookshelf 9489`), 课标外 start 9,381, the 初中 tab's first 小学 word at 1,950
  and the C10 trap row at 601/601 equal the simulation.

## Findings

| # | sev | verdict | where | finding |
|---|---|---|---|---|
| 1 | minor | CONFIRMED | `backend/tests/unit/test_seed.py:763` (and no always-on test) | The committed artefact's stamps (`policy == LEARN_ORDER_VERSION`, `seed == stats.json.content_sha256`, shape) are asserted only inside the two `@pytest.mark.full_seed` tests, which the default suite skips (`pytest … test_full_seed_acceptance_numbers test_cet6_new_only_on_the_full_seed -q` → `2 skipped`). A policy bump or a seed change that forgets to regenerate `data/seed/learn_order.json` passes `pytest backend/tests` and is caught only when someone sets `WD_FULL_SEED_DB`. Fix: one always-on unit test (e.g. in `test_learn_order.py`) that loads `data/seed/learn_order.json` and `data/seed/stats.json` and asserts `policy == lo.LEARN_ORDER_VERSION`, `seed == stats["content_sha256"]`, `generated_by`, the key order and `set(stages) == set(STAGE_ORDER) | {"none"}`. |
| 2 | minor | CONFIRMED | `deploy/install.sh:142` | `run "$REPO/.venv/bin/wd" learn-order` runs under `set -euo pipefail` (line 6) and `run(){ … "$@"; }` (line 28) without a `\|\| echo WARN` guard, and `wd learn-order` exits 1 when a stage word stays unranked (`cmd_learn_order`, pinned by `test_cli.py::test_learn_order_fills_previews_and_reports`). On the Lighthouse stop-first path that exit aborts the install after the unit was stopped — the systemd steps (`daemon-reload`, `enable`, `restart`) never run — for a seed defect the service start itself would have survived (`ensure_current` is fail-soft and the NULL row sorts last). Demonstrated with `set_e_demo.sh` (nothing after `run false`, exit 1). Fix: `run "$REPO/.venv/bin/wd" learn-order \|\| echo "WARN: learning order incomplete — run 'wd learn-order' and 'wd check db' after the start"` (the `claude-check` precedent on the next line), or let the CLI return 0 with a printed warning for the unranked case and keep exit 1 for the schema refusal. |
| 3 | minor | CONFIRMED | `docs/qa-frontend.md:43` | The manual QA checklist still reads "sort 词频 / 字母 / 难度" while the chip now says 学习顺序 (`zh.ts:48`, FRONTEND §8). A tester following the checklist looks for a chip that no longer exists. Fix: "sort 学习顺序 / 字母 / 难度". |
| 4 | nit | CONFIRMED | `docs/releases/2026-11-learn-order.md:90`, `docs/analysis/2026-11-06-learn-order/DESIGN.md:173` | "24 形助动词清单" / "24-form AUX list" — the list the code and the tests use (`learn_order.ACCEPTANCE_AUX_LEMMAS`, `reference_order.AUX_FACTS`, `test_report_document_shape_and_acceptance_block` asserts `len == 25`) has 25 lemmas (8 be-forms + 4 do-forms + 3 have-forms + 10 modals). Fix: write 25 (or drop the count). |
| 5 | nit | CONFIRMED | `docs/analysis/2026-11-06-learn-order/DESIGN.md:448,454,670` | Lane D and §8 gate 3 tell the team to run `npm run check:copy`; `frontend/package.json` has no such script (`scripts`: dev, build, preview, typecheck, test, lint) — the copy checker is `npm run lint` (`node scripts/check-copy.mjs`, what `make test` runs). The gate agent discovered this at run time. Fix: replace with `npm run lint` in the DESIGN (it is part of the commit) or add a `check:copy` alias to `package.json`. |
| 6 | nit | CONFIRMED | `backend/tests/unit/test_api_schemas.py:48` | The docstring of `test_stage_index_is_position_plus_one` still cites `_STAGE_DISTANCE` as a position-derived consumer; that constant was deleted by the M4 unification (`grep -rn _STAGE_DISTANCE backend/wd` → nothing). Fix: name `learn_order.stage_distance_sql` instead. |
| 7 | nit | CONFIRMED | `backend/wd/services/learn_order.py:946` (`register_cli`), `:869` docstring | `--report` is documented as written "(after the recompute)" / "`--report` then writes the §2.8 document", but with `--dry-run` or `--show` no recompute runs and the document is written from the stored keys: on my copy `wd learn-order --dry-run --report r.json` printed both `dry run: … nothing written` and `report written to …` while `kv.learn_order.computed_at` stayed `2026-11-06T07:44:39Z`. Harmless for the release (the runbook writes the report after a plain `wd learn-order`), but the help text misleads an operator who reviews a policy change with `--dry-run --report`. Fix: say "from the stored ranks (after the recompute unless --dry-run / --show)" or refuse `--report` together with `--dry-run`. |

## Deviations from the DESIGN that are correct as coded (recorded, not findings)

* §4.1 item 22 expected `stats.learn_rank_changed == len(changed) + 1` (abandon's own key moving); the key encodes no stage, so abandon's
  key is unchanged and the test rightly asserts `== len(changed)`, and adds a second step (`frq` 400) that provably ripples `a.m.`.
* `reference_order.py` lives in `backend/tests/` next to `fake_claude.py` / `fake_openai.py` instead of `backend/tests/helpers/` — the
  repository's existing helper location; the §4.1 tests are split over `test_learn_order.py` / `_db.py` / `_sql.py` (lane split).
* The seed import re-raises every `sqlite3.Error` out of `recompute`, not only write-phase ones (a compute-phase `OperationalError`
  is impossible after `wd migrate`; propagating is the safer reading).
* `main.startup` passes the app clock (`now_iso(app.state.clock)`) to `ensure_current` so `kv.learn_order.computed_at` follows the
  FrozenClock in tests; the DESIGN wrote `ensure_current(conn)`.
* `recompute()` rewrites the four `kv.learn_order.*` rows on every compare (one `BEGIN IMMEDIATE` per start / night even when nothing
  changed) — the DESIGN's A10 wording; the event is written only when rows changed.

## Not findings (checked and fine)

`check_lines` catching only `sqlite3.OperationalError` mirrors `diag._invariant_line`; `register_cli` without a docstring matches
`seed.py` / `diag.py` / `backup.py`; the `--db` help "instead of WD_DB_PATH" matches `wd check --db`; `ConfigError → exit 2` matches
`import-seed`; the 0014 header is the §2.2 text; `docs/SCHEMA.sql`, `schemas.VocabSort`, `types.ts`, `check_contract.py` and the seed
file are untouched; `test_main_seed_check` still sees exactly `["seed_imported"]` (the import path writes no recompute event and the
startup compare finds nothing to write); the release note's numbers are labelled 参考模拟 / 排练输出 and the authoritative values live
in `learn_order.json`, as DESIGN §5 allows.
