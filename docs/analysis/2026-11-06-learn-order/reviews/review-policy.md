# Adversarial review — lens "policy correctness: spec ↔ code ↔ simulation" · 2026-11-06

Reviewed: the uncommitted working tree against `cd3df8c` (37 modified files + the new `learn_order.py`, `0014_learn_rank.sql`,
`reference_order.py`, 5 new test files, `data/seed/learn_order.json`, the release note), the contract
`docs/analysis/2026-11-06-learn-order/DESIGN.md`, `FACTS.md`, `sim_final_policy.py` / `sim_output.txt` / `mini_seed_golden.json`.
Nothing in the repository was modified. Probes ran on my own `VACUUM INTO` copies under
`scratchpad/impl/review-policy/{live,cli}/word-dance.db` (never the live data directory, no port bound).

Scripts and outputs: `probe_policy.py` → `probe_policy.txt` (live differential, best_effort, determinism, acceptance, SQL ≡ Python),
`probe_edges.py` → `probe_edges.txt` (totality extras, glue chains, version-bump bypass, TEXT key, stale report),
`probe_ripple.py` (runtime word → stage ripple exposure), plus the inline CLI runs quoted below.

## What was verified and holds (no finding)

* **Every §1.3 rule** in `backend/wd/services/learn_order.py`: R2 (`frq > 0 else bnc > 0`), R1 with M1 precedence (`may` never
  closed; `an` closed only through `CLOSED_LEMMAS`; `inherit:` tokens; a bare `inherit:` is no head), class order
  set/glued/adverb/interj/plain, groups per `(stage_min, closed)` incl. NULL and garbage `stage_min` (99, "2", True, "zk" → 课标外),
  hosts = ranked plain rows by `(rank, lemma)`, R3 (`ceil((k−½)·n_r/n_u)` with both clamps, `n_u > n_r` sharing, `n_r = 0` → NULL;
  token resolution lemma → single-word form, ambiguous skipped, self skipped, hyphen split), M1 (`median_low`, 1-based subs
  21..32 / 33..39, no-rank fallback dealt in calendar order keeping the subs), M3/G5 dealing order, M2 (`j` by lemma among forms
  gluing to the same head, NULL head → NULL), R4, packing and the `CLOSED_BASE` bound, the frq tail.
* **Live differential**: module vs `sim_final_policy.rank_rows` on the 9,618-row copy — 19 raw key differences, all 19 the
  calendar rows at +1 (the simulation's 0-based ordinal, see N-7), 0 unexplained; all six per-stage orders identical; class /
  how / closed labels identical; stats counts identical. `probe_policy.txt`.
* **`best_effort_rank ≡ rank_rows`** for all 8,662 native rows of the live copy (0 mismatches); None for the 529 dealt rows,
  the native-rank approximation for adverb/set/interj/glued rows, as §2.1 says.
* **Determinism**: rows shuffled + `forms` insertion order shuffled (3 seeds) → identical `ranks`, `rows`, `stats`.
* **Totality**: the §4.1 item 3 matrix plus tabs in a lemma, duplicate lemmas, empty lemmas, huge/negative/bool/inf/nan
  ranks, label `pos`, forms pointing at missing ids, glue chains and cycles, sets without hosts — no exception.
* **Golden digest** `8ba429d7…91ef` reproduced from the mini seed; the test's `GOLDEN` table == `mini_seed_golden.json`.
* **Idempotency / persistence**: first fill 9,618 changed (80 ms), second recompute 0, `stale_count` 0 / 0, `unranked` 0,
  `is_current (True, ok)`, stats 1,486 bytes, one `learn_order_recomputed` event, `updated_at` 16 distinct values before and
  after, four `invariant …: ok` lines, the stats line as specified.
* **§1.5 probe positions and §1.6 acceptance numbers** recomputed on my copy: every xs probe (the 526 · be 527 am 528 are 529
  is 530 · do 545 does 546 · not 9 up 25 … like 575), every zk probe (have to 3 … although 1905), cet4 oh 854 / simply 10 /
  particularly 27 / due 1707, cet6 yeah 642 / currently 16, 词库 全部 the 526 / is 530 / just 611 / other 601 / bookshelf 9,489 /
  课标外 from 9,381; acceptance `{closed 0 0 0 0 0, xs adverbs 2, months 243–254, zk phrases 42, null runs 7 3 2 1 3}` — identical
  to `sim_output.txt`, to DESIGN §1.5/§1.6 and to the committed `data/seed/learn_order.json` (every stage block and the
  acceptance block equal; `seed` equal).
* **SQL ≡ Python** (`order_key` / `stage_distance`) for 全部 cur 1, xs / zk / cet6 tabs, 筛词 xs+zk+gk cur 1 and cet4+cet6 cur 5,
  prewarm all, key-only, and the `difficulty` shape; plan `ix_words_public` + temp B-tree as before.
* **Lock window**: the write phase of a first fill (9,618 UPDATEs + 4 kv rows) inside `BEGIN IMMEDIATE` = 15.8 ms; compare
  phase 21 ms load + 29 ms rank; no-change recompute 70 ms — the release note's ≤ 30 ms lock and ≈ 60 / 80 ms figures hold.
* **Packing bound for runtime words**: ECDICT `stardict.db` max `frq` 47,062 / max `bnc` 50,000, 0 entries ≥ 100,000; live copy
  max 46,049 / 49,824 — every runtime ECDICT key stays below `CLOSED_BASE`.
* **No test pins a live-seed lemma literally** (grep for `say`, `physical education`, `other/thing`: only the pre-existing
  seed-builder normalisation tests); the new tests go through `reference_order` / `GOLDEN` (mini-seed fixture) / the report.
* The docs quoted by `test_docs_contract` match the code (API.md 20/22/31, DESIGN §3.2/§6.2/§6.3, WLC §1.6 incl. the
  `stage_min_consistent` claim — `NULL IS NOT (CASE …)` is true for a flagged row without `stage_min`).

## Findings (most severe first)

### F-1 · major · CONFIRMED — a runtime word or form re-ranks STAGE words through R3 token resolution; `learn_rank_matches_policy` then FAILs until the next recompute (contradicts DESIGN §2.1 and A8)

`backend/wd/services/learn_order.py:329-348` (`resolve` / `token_rank` resolve against **every** row and **every** `word_forms`
row) and `:35-37` (the docstring calls it "one accepted nuance … shift *that phrase's* dealt position").
DESIGN §2.1 (lines 256-260) states the recompute "only ever affects the 课标外 group (runtime rows carry no stage flags)" and A8
scopes `learn_rank_matches_policy` to stage words on that premise ("then `wd check db` may FAIL transiently after a user adds an
ECDICT word" is listed as the cost A8 *avoids*). Both are false: R3 orders the group's frequency-less rows by their rarest
resolvable token, and a new row or a new form can make a token of a **stage** phrase resolvable (or change which token is
rarest), which shifts that phrase in the `unranked` sort and therefore the `k` index — and the host — of every dealt row behind it.

Evidence (my filled copy, the real code path):
```
# words._insert_word(cols for ECDICT 'york': frq None, bnc 1010, source ecdict, stage_min NULL)  — as _resolve_ecdict would
inserted york: created True learn_rank 101000
stale_count stage-only after the insert: 203 | all: 231
check_lines violated: ['invariant learn_rank_matches_policy: 203 violation(s) (stored learn_rank of stage words differs …; run `wd learn-order`)']
stage rows whose key would change: 203 by stage: {1: 0, 2: 203, 3: 0, 4: 0, 5: 0}
  examples: [('a bit', 2, 222420, 222020), ('a bit of', 2, 224620, 222420), ('a couple of', 2, 159420, 158720), …]
recompute changed: 231
# words.add_form('sooner' → soon, 'r')  — what a lookup of "sooner" writes through ECDICT's lemma pointer (no new row at all)
stale_count stage-only: 57 → 'invariant learn_rank_matches_policy: 57 violation(s) …' → recompute changed: 57
```
Exposure (`probe_ripple.py`): 40 stage phrases carry 31 tokens that do not resolve today; ECDICT ranks 19 of them; of the 40
most common, adding any one of 11 (`mid`, `ping`, `pong`, `semi`, `kung`, `sooner`, `wi`, `yangtze`, `york`, `zealand`,
`zealander`) moves between 2 and 341 初中 keys. The learner-visible shift is one host slot per phrase (harmless), but
`wd check db` exits 1 with a false alarm from the moment a user looks such a word up until the next start / 03:30, and the
release note §4.1 "群体涟漪 … 只影响课标外组" and DESIGN §2.1 / A8 mislead the operator about what the FAIL means.

Fix (pick one, then correct the docstring, DESIGN §2.1 and the release note §4.1 paragraph):
1. keep the policy and scope the invariant to what is actually invariant at runtime: `stale_count(conn)` counts stage rows
   with `how == 'native'` (a hand edit of a native key is still caught; dealt / set / adverb / interj drift is reported in the
   stats line like `drift_none`), i.e. one filter in `stale_count` + its test and the §2.7 text; or
2. hook `learn_order.ensure_current` (≈ 70 ms) after `_insert_word` / `add_form` (A7's reversal) so stored keys never lag; or
3. restrict the R3 token universe to seed rows (`source = 'seed'` would need `source` in `WordInput`/`INPUT_COLUMNS`; or
   `stage_min IS NOT NULL` with existing inputs) — a policy change: bump `LEARN_ORDER_VERSION`, regenerate the digest and
   `learn_order.json` (and forms written at runtime, e.g. `sooner → soon`, still ripple unless forms are filtered too).

### F-2 · minor · CONFIRMED — a TEXT value in `learn_rank` crashes `wd check db` and `wd learn-order` with a traceback and blocks the self-heal

`backend/wd/services/learn_order.py:559` `_stored_keys` does `int(r[1])`; `learn_rank INTEGER` has only affinity, so
`UPDATE words SET learn_rank = 'abc'` (a hand edit the docs forbid, but totality is the module's stated rule) is stored as TEXT.
```
$ WD_DATA_DIR=<copy> wd check db      → ValueError: invalid literal for int() with base 10: 'abc'   (traceback, no [FAIL] line)
$ WD_DATA_DIR=<copy> wd learn-order   → same traceback (cmd_learn_order catches sqlite3.Error only)
ensure_current → None + system_events('learn_order_failed') on every start; the row is never rewritten
```
Fix: `_stored_keys` → `_int_or_none(r[1])` (garbage reads as NULL → counted as changed → rewritten by the next compare), and
let `cmd_learn_order` / `_learn_order_lines` treat `ValueError` like `sqlite3.OperationalError` (`query failed (…)`).

### F-3 · minor · CONFIRMED — `--report` after `--dry-run` / `--show` (and `report()` on a stale or unfilled DB) writes a document labelled `policy: lo-1` whose lists are the STORED (frq) order

`backend/wd/services/learn_order.py:924-931` writes `report(conn)` whatever ran before; `report()` (`:836-851`) takes `first`
and the whole `acceptance` block from `stored.get(r.id)` while `ranked / dealt / closed / p10…` come from the fresh
`rank_rows`. On the migrated, unfilled copy:
```
$ WD_DATA_DIR=<copy> wd learn-order --dry-run --report dry_report.json
policy lo-1 | computed_at None | xs first 8 ['the', 'be', 'and', 'of', 'a', 'in', 'to', 'have'] | xs ranked/dealt/closed 533 9 75
acceptance closed_in_first_30 {'xs': 28, 'zk': 12, 'gk': 1, 'cet4': 1, 'cet6': 1} months [582, 578, 478]
```
An operator who treats `--dry-run` as "the safe preview" and adds `--report` gets a lo-1 artefact describing the pre-0014 order
(the `full_seed` gate would catch it only if it were committed). Fix: in `cmd_learn_order` refuse `--report` unless this
invocation recomputed (or write `first` / `acceptance` from `result.ranks` and add `"order": "stored"|"computed"`).

### F-4 · minor · CONFIRMED — the version-bump guard (golden digest) is blind to M1, G5 and R3 token resolution

`backend/tests/unit/test_learn_order.py:173-206` (`test_golden_table_lo_1`) is the DESIGN §4.1 item 2 mechanism "editing the
policy without bumping the version fails here". The mini seed has no calendar word, no interjection and no phrase whose token
resolves (`probe_edges.txt`: calendar `[]`, interjections `[]`, resolvable tokens `{}`), so:
```
M1 edit (statistics.median_low → median_high) → digest unchanged: True
G5 sub edit (SUB_INTERJ 50 → 55)              → digest unchanged: True
```
The dedicated tests (`test_calendar_sets`, `test_adverbs_and_interjections_are_dealt`, `test_dealing_formula`, the constants
test) do fail on such edits, but none of them is tied to `LEARN_ORDER_VERSION`, so a rule change can land with its own test
"updated" and the version untouched (`kv.learn_order.version` then lies; the committed `learn_order.json` would catch it only
through the full_seed gate). Fix: a second golden digest in `test_learn_order.py` over a synthetic row set exercising every rule
(months with mixed ranks incl. NULL, weekdays without ranks, an interjection, phrases with lemma and `word_forms` tokens, glue),
asserted together with `LEARN_ORDER_VERSION`; or extend the mini seed accordingly.

### N-5 · nit · CONFIRMED — glue chains collide with siblings

`backend/wd/services/learn_order.py:398-412` follows a glued head that is itself glued (`done → did → do`): `done` gets
`key(did) + 1 = key(do) + 2`, the same key as `does` (`key(do) + 2`), broken only by the frq tail
(`probe_edges.txt`: `did 10004001, does 10004002, done 10004002`). Not in the live data (only `am is are does`), and the DESIGN
defines no chains. Fix: index `j` among all forms transitively gluing to the chain's root, or state chains are out of scope.

### N-6 · nit · CONFIRMED — "24-form AUX list" is 25 forms

`docs/analysis/2026-11-06-learn-order/DESIGN.md:173` and `docs/releases/2026-11-learn-order.md:90` say 24; the list
(`ACCEPTANCE_AUX_LEMMAS`, `reference_order.AUX_FACTS`, FACTS §2) has 25 (8 be + 4 do + 3 have + 10 modals) and
`test_learn_order_db.py:313` asserts 25. Fix: write 25.

### N-7 · nit · CONFIRMED — the reference simulation encodes the calendar sub 0-based; the module follows the DESIGN

`sim_final_policy.py:162/166` uses `base + members.index(lemma)` (january 20 = `SUB_DEALT`, sunday 38) while DESIGN §1.2 / §1.3
step 3 / A19 say 21..32 / 33..39; the module and `test_calendar_sets` are 1-based. Positions are identical (19 keys +1,
`diff_vs_sim.txt`, `probe_policy.txt`); the mini-seed digest is unaffected (no calendar word). Record only; fix the simulation
if it stays the reference.

### N-8 · nit · PLAUSIBLE — `drift_none` misreports on the first compare after a policy-version bump

`backend/wd/services/learn_order.py:627` counts every 课标外 row whose stored key differs and is non-NULL; after a
`LEARN_ORDER_VERSION` bump every row changes, so the stats line shows `课标外 drift 238` until the following compare (nightly)
resets it. Fix: compute `drift_none` only when `kv.learn_order.version` already equals the code's version.

## Not reported (decided by DESIGN §7 or confirmed safe)

`like` 575 / `have` closed / `may` as a month (A1, A5); 全部 and the stage tabs ordered by stage distance incl. the `q` prefix
search (A2 / G6); suggestions keep `FRQ_TAIL` (A4); `learn_rank_matches_policy` scoped to stage words (A8 — see F-1 for the part
of its premise that does not hold); no index (A6); nightly self-heal (A7); COCA-before-BNC tie (A13); the `--show --cur` WHERE
(`stage_X = 1 AND merged_into_word_id IS NULL`, no `is_public` filter) as an operator view; merged / private rows as hosts of
the 课标外 group (§2.1); `RecomputeResult.unranked_stage_words` counting merged rows while the SQL excludes them (no stage word
can be merged today).
