# Mechanism design — derived column `words.learn_rank` (angle "derived-column") · 2026-11-06

Scope: WHERE the learning order (学习顺序) is computed and stored and HOW it reaches the five lists, independent of the exact
policy. The policy (closed-class gate, frq → bnc fallback, per-stage quantile spreading, phrases, 课标外 …) is treated as a
deterministic function of `lemma, pos (via wd.images.style.dominant_pos), frq, bnc, kind, sources, stage_min` plus per-stage
statistics; the stand-in rule of FACTS §2 is used only to measure costs. Everything below was verified against
`/Users/sqin/word-dance` @ cd3df8c and measured on a scratch copy of the live database (FACTS §0) with the three scripts in
`${OUT}/sim-derived-column/` (`probe.py` read-only, `sim_recompute.py` + `sim_extend.py` on scratch copies; all three run with
`/Users/sqin/word-dance/.venv/bin/python -I <script>`; `sim_extend.py` is new in this attempt).

Decision summary

| Question | Answer |
|---|---|
| Where is the order stored? | `words.learn_rank INTEGER` (NULL = not computed), added by additive migration `0014_learn_rank.sql`; no table rebuild, no view change. |
| Where is it computed? | New pure module `backend/wd/services/learn_order.py`: `rank_rows()` (whole table, cross-row stats allowed) and `rank_for()` (one row, from the stored per-stage table). |
| When? | `recompute(conn)` in ONE transaction: at startup when stale (version / seed stamp / NULL stage rank), inside every `import_seed` transaction, by `wd learn-order`; `_insert_word` writes a best-effort rank. |
| How do lists read it? | One constant `learn_order.ORDER_SQL = "w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` replaces the frq fragment at the five sites (stage distance stays in front at 筛词 / 推荐词); lookup suggestions follow too (recommended). |
| Cost (live copy, 9,618 rows) | migration 2.2 ms · full recompute 41 ms (read 7 / compute 14 / write+commit 20–25) · no-op recompute 18 ms · staleness probe 0.00 ms · `wd check db` stale-diff 18 ms · each list query ≤ 8 ms (unchanged plans). |
| Deployment on the Mac | `git checkout <sha>` + `launchctl kickstart -k gui/$(id -u)/com.word-dance.server` (+ a frontend snapshot only if the 词库 sort label changes). Startup applies 0014 and fills the ranks itself. |
| Rollback | Code-only rollback is safe (old code ignores the column; explicit-column INSERTs; rows read by name). |

---

## 1 Architecture and data flow

```
inputs (per words row)                         cross-row step                        storage                      readers
lemma, pos, frq, bnc, kind, sources, stage_min ─► learn_order.stage_stats(rows)  ─┐
                                                   (per stage_min group: n,         │
                                                    quantiles of frq|bnc …)        ▼
                                              learn_order.rank_rows(rows) ──► UPDATE words SET learn_rank = ?   ──► ORDER BY {stage distance,} learn_order.ORDER_SQL
                                                   = rank_for(row, stats[row.stage_min]) for every row            at: GET /api/vocab (freq + difficulty sorts)
                                                                                 kv.learn_order.version  = "lo-1"        GET /api/screen/next
                                                                                 kv.learn_order.seed_version = digest    batches.select_words / add_more (每日推荐词)
                                                                                 kv.learn_order.stats = {stage: table}   ai.prewarm.candidates (管理员预生成)
                                                                                 kv.learn_order.computed_at             GET /api/lookup suggestions
triggers:  main.startup (after seed_check) ── ensure_current ──► recompute  if version ≠ code | seed stamp ≠ kv.seed_version | a stage word has NULL rank
           seed.import_seed ─── inside its BEGIN IMMEDIATE, after _rebuild_forms ──► recompute(seed_version=digest)
           wd learn-order [--dry-run | --show STAGE] ──► recompute / report
           services.words._insert_word ──► learn_rank = best_effort_rank(conn, cols)   (one row, from kv.learn_order.stats)
checks:    wd check db  → learn_rank_present · learn_order_current · learn_rank_matches_policy (from schema 14)
           scripts/rehearse_migration.py → check_0014 (+ recompute on the copy, prints the 小学 / 初中 head of the order)
```

Principles the mechanism enforces regardless of policy:

1. `learn_rank` is a **global, cross-stage comparable integer key**, smaller = earlier, NULL = unknown. Lists that have no stage
   prefix (词库 全部 tab, `prewarm stage=all`, lookup suggestions) need a total order; lists with a stage prefix (`_STAGE_DISTANCE`)
   order inside each distance group. A per-stage ordinal (1..n inside the stage) would interleave stages in the 全部 tab and is
   therefore ruled out; the policy encodes e.g. `band * 1_000_000 + effective_frequency` (the stand-in used here).
2. **Derived, never authored**: the seed format (v2) does not change, the builder does not change, `SEED_COLUMNS` does not change;
   the seed UPSERT (`seed.py:93-103`) neither writes nor compares `learn_rank`, so an unchanged seed is still a no-op import.
3. **`updated_at` is never touched by a recompute**: it keys the card LRU (WORD_LIBRARY_CURATION §1.6) and the importer's
   "unchanged row" rule; `test_seed.py::test_changed_record_updates_only_that_row` already enforces the rule for the import.
4. **Fail-soft**: a row without a rank sorts after every ranked row of its group, by the pre-0014 frq order (the tail of
   `ORDER_SQL`). Between the migration and the first recompute, after a failed recompute, or for a hand-inserted row the lists
   are therefore still deterministic and never worse than today.
5. **One definition of the order** in code (`learn_order.ORDER_SQL`) and in docs (API.md §20 / DESIGN §6.3 quote the constant and
   `test_docs_contract.py` pins the quote).
6. The cross-row step is reduced to a **small per-stage table** stored in `kv.learn_order.stats` (379 bytes for deciles of six
   groups, measured) so that a single new row can be ranked consistently without a full recompute. If the policy uses exact
   positional spreading (sort the unknown words of a stage and give the j-th the j-th quantile) the single-row path cannot
   reproduce it; the mechanism supports that too, but then `learn_rank_matches_policy` reports runtime-created rows as stale
   until the next recompute (see §4). Recommendation to the policy author: make `rank_for(row, stats)` the truth and let
   `rank_rows` be its map (a lemma-hash quantile gives an even spread and is per-row pure).

---

## 2 File-by-file change list

### 2.1 New: `backend/wd/migrations/0014_learn_rank.sql` (draft)

```sql
-- 0014_learn_rank.sql — derived learning-order key (学习顺序) on every words row (DESIGN §3.2, §6.3 step 4; API.md 20;
-- docs/releases/2026-11-learn-order.md).
--
-- Additive only, the 0010_ai_provider.sql / 0012_word_images_meta.sql precedent: one ADD COLUMN (no default — NULL means
-- "not computed yet") and one index. Nothing is rebuilt and no view, trigger or foreign key references the column (v_bank's
-- `w.*` column list was fixed when the view was created in 0011), so the file is safe under `deploy/install.sh --no-restart`
-- (DEPLOY §10) and a plain `wd serve` restart applies it on the Mac. The VALUES are deliberately not written here: learn_rank
-- is derived by backend/wd/services/learn_order.py from pos/frq/bnc/kind/sources/stage_min plus per-stage statistics, and is
-- filled at the next start (main.startup → learn_order.ensure_current: "a stage word has NULL rank"), inside every seed import
-- and by `wd learn-order`. Until then a NULL rank sorts after every ranked row of its stage-distance group, by the old frq
-- order (learn_order.ORDER_SQL), so the lists stay deterministic between the migration and the first recompute.
-- The runner wraps this file in BEGIN IMMEDIATE and records schema_migrations(14, 'learn_rank') itself (SCHEMA.sql §1) —
-- nothing else belongs here. docs/SCHEMA.sql stays the 0001 baseline byte for byte (test_db.py).
ALTER TABLE words ADD COLUMN learn_rank INTEGER;        -- derived sort key: smaller = earlier; NULL = not computed (sorts last in its group)
CREATE INDEX ix_words_learn_rank ON words(learn_rank);  -- the order key's own index, as ix_words_frq is frq's (see the design note)
```

Index justification (measured, `sim_extend.py`, three shapes on fresh copies):

| shape | pages | startup probe `stage_min IS NOT NULL AND learn_rank IS NULL` | list queries (5 sites) | recompute |
|---|---|---|---|---|
| A `(learn_rank)` | 27 (≈ 108 KB) | 0.00 ms, `SEARCH … USING INDEX ix_words_learn_rank (learn_rank=?)` | identical plans/times | 41 ms |
| B `(stage_min, learn_rank)` | 33 | 0.08 ms covering range scan | identical | 40 ms |
| C none | 0 | 0.43 ms `SCAN words` | identical | 36 ms |

None of the five sites ever uses the new index: the planner keeps `ix_words_public` for the WHERE and sorts ≤ 9,618 rows in a
temp B-tree (`vocab 全部` page 1 = 1.2 ms, page 100 = 7.6 ms, 筛词 1.0 ms, 推荐词 1.5 ms, prewarm 1.9 ms, suggestions 0.6 ms, with
or without an index). Shape A is kept for three reasons that are not speed today: (1) symmetry — the order key keeps the index
the previous order key has (`ix_words_frq`, 0011), so the schema reads as intended; (2) the startup / `wd check db` NULL probes
and the `--show STAGE` listing are index lookups instead of table scans, which matters once the probe runs on every start and
on every `wd check`; (3) it is the index the planner will pick for an ORDER-BY-only listing (词库 全部 without filters) once the
table grows past what `ANALYZE` prices as a cheap sort. It costs 5 ms per full recompute and 27 pages. Shape B is the alternative
if the 仅本阶段新增 listing (`stage_min = :idx ORDER BY learn_rank`) ever shows up in profiles. `ix_words_frq` and
`ix_words_stage_min(stage_min, frq)` stay: `scripts/rehearse_migration.py:215` pins their presence and the frq tail of
`ORDER_SQL` still reads frq.

### 2.2 New: `backend/wd/services/learn_order.py` (≈ 250 lines incl. CLI)

```python
"""Learning order (学习顺序): the derived ``words.learn_rank`` column — DESIGN §3.2 / §6.3 step 4, API.md 20, migration 0014.

Every "which word next" list (词库 ``sort=freq``, 筛词 ``GET /api/screen/next``, 每日推荐词 ``batches.select_words`` /
``add_more``, 管理员预生成 ``ai.prewarm.candidates``, lookup suggestions) orders by :data:`ORDER_SQL`: ``learn_rank`` ascending,
NULL last, then the pre-0014 frq order as the tail. The rank is DERIVED — never part of the seed, never edited by hand — from the
inputs :data:`INPUT_COLUMNS` (``lemma, pos, frq, bnc, kind, sources, stage_min``) and the per-stage statistics
:func:`stage_stats` computes over the whole table (quantiles of the known frequencies of each ``stage_min`` group, 课标外 =
group ``None``). The policy itself lives in :func:`rank_for`; its version is :data:`LEARN_ORDER_VERSION` and MUST be bumped
whenever :func:`rank_for` or :func:`stage_stats` would return a different value for any input, because the stored column is
only refreshed when the version, the seed or a NULL rank says so (:func:`ensure_current`).

Rank semantics the readers rely on (policy-independent): an INTEGER comparable across stages (smaller = earlier; the 全部 tab
and ``prewarm stage=all`` have no stage prefix), deterministic, NULL = unknown. ``pos`` is read through
:func:`wd.images.style.dominant_pos` only (D-images-24). ``updated_at`` is never touched here (it keys the card LRU and the
importer's "unchanged row" rule).
"""

LEARN_ORDER_VERSION = "lo-1"                 # bump on any policy change (rank_for / stage_stats output)
LEARN_ORDER_FROM_VERSION = 14                # schema version that carries words.learn_rank (0014_learn_rank.sql)
KV_VERSION, KV_SEED, KV_STATS, KV_AT = "learn_order.version", "learn_order.seed_version", "learn_order.stats", "learn_order.computed_at"
INPUT_COLUMNS: tuple[str, ...] = ("id", "lemma", "pos", "frq", "bnc", "kind", "sources", "stage_min")
ORDER_SQL = "w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"  # alias `w`, as at every site

def order_sql(alias: str = "w") -> str:
    """:data:`ORDER_SQL` for another table alias (tests and ad-hoc SQL; the five sites all use ``w``)."""

@dataclass(frozen=True)
class WordInput:
    """The rank inputs of one ``words`` row, built with :func:`word_input` from a Row/Mapping (missing keys → None)."""
    id: int; lemma: str; pos: str | None; frq: int | None; bnc: int | None; kind: str; sources: str | None; stage_min: int | None

@dataclass(frozen=True)
class StageStats:
    """Per-``stage_min`` table the policy needs across rows: ``n`` and the quantiles of the known frequencies (frq, else bnc).
    Serialised into ``kv.learn_order.stats`` (≈ 400 bytes for six groups) so :func:`rank_for` can rank one new row later."""
    n: int; quantiles: tuple[int, ...]            # e.g. deciles; empty when the group has no known frequency

def stage_stats(rows: Iterable[WordInput]) -> dict[int | None, StageStats]:
    """The cross-row step: one :class:`StageStats` per ``stage_min`` group (``None`` = 课标外). Pure."""

def rank_for(row: WordInput, stats: Mapping[int | None, StageStats]) -> int | None:
    """THE policy: the rank of one row given its stage's statistics; None only when nothing can be said (no frq, no bnc and
    an empty stats table). Pure and deterministic; reads ``pos`` through ``dominant_pos``. Documented in DESIGN §3.2."""

def rank_rows(rows: Sequence[WordInput]) -> tuple[dict[int, int | None], dict[int | None, StageStats]]:
    """``({word_id: rank}, stats)`` for a whole table — ``stage_stats`` then ``rank_for`` per row. Pure; the truth that
    :func:`recompute` stores and :func:`stale_count` compares against."""

@dataclass
class RecomputeResult:
    version: str; rows: int; changed: int; unranked_stage_words: int; seconds: float; trigger: str

def recompute(conn, *, now: str | None = None, seed_version: str | None = None, trigger: str = "cli") -> RecomputeResult:
    """Rank every row and store the result inside ONE transaction (``db.maybe_tx``: joins the caller's — ``import_seed`` —
    or opens ``BEGIN IMMEDIATE``). Writes only rows whose rank differs (``UPDATE words SET learn_rank = ? WHERE id = ?``,
    never ``updated_at``), then ``kv.learn_order.version/seed_version/stats/computed_at``. ``seed_version`` defaults to
    ``kv.seed_version`` (the importer passes the digest it is about to store). Writes ``system_events('learn_order_recomputed',
    {version, rows, changed, trigger, seconds})`` unless ``trigger == 'seed_import'`` (the ``seed_imported`` event carries
    the summary). Measured: 9,618 rows in ≈ 41 ms, 18 ms when nothing changes."""

def is_current(conn) -> tuple[bool, str]:
    """``(True, 'ok')`` or ``(False, reason)``: ``kv.learn_order.version != LEARN_ORDER_VERSION`` · ``kv.learn_order.seed_version
    != kv.seed_version`` · ``EXISTS (SELECT 1 FROM words WHERE stage_min IS NOT NULL AND learn_rank IS NULL)`` (0.00 ms with
    ix_words_learn_rank). Raises ``sqlite3.OperationalError`` before schema 14 (no column) — callers gate on the version."""

def ensure_current(conn, *, now: str | None = None) -> RecomputeResult | None:
    """The startup hook (``main.startup``, after ``seed_check``): :func:`recompute` iff :func:`is_current` says stale; None when
    current. Never raises — like ``main.seed_check`` every exception is logged with its traceback and recorded as
    ``system_events('learn_order_failed')``; the service then serves the fail-soft order (NULL ranks sort last by frq)."""

def best_effort_rank(conn, cols: Mapping[str, Any]) -> int | None:
    """``rank_for`` for a row that is being inserted at runtime (``services.words._insert_word``), with the stats table read
    from ``kv.learn_order.stats``; None before the first recompute or when the inputs allow no rank."""

def stale_count(conn) -> int:
    """Rows whose stored ``learn_rank`` differs from :func:`rank_rows` over the current inputs (the ``wd check db``
    ``learn_rank_matches_policy`` invariant; 18 ms on the live copy)."""

def unranked_stage_words(conn) -> int:
    """``COUNT(*) FROM words WHERE stage_min IS NOT NULL AND learn_rank IS NULL AND merged_into_word_id IS NULL``."""

def show(conn, stage: str, top: int) -> list[tuple[str, int | None, int | None]]:
    """``(lemma, learn_rank, frq)`` of the first ``top`` words first listed at ``stage`` (``stage_min = stage_to_index(stage)``),
    in :data:`ORDER_SQL` order — the operator preview for the rehearsal and ``wd learn-order --show``."""

def register_cli(sub) -> None:
    """``wd learn-order [--dry-run] [--show STAGE [--top N]] [--db PATH]`` — see §2.7."""
```

Import direction: `learn_order` imports `wd.db`, `wd.clock`, `wd.schemas` and `wd.images.style` only (no `services.*`), so
`seed.py`, `main.py`, `services/words.py`, `diag.py` and `scripts/rehearse_migration.py` can import it without a cycle
(`services/words.py:26` already imports the `wd.images` package; `wd.images.style` pulls only `config` and `schemas`).

### 2.3 The five ORDER BY sites (+ lookup suggestions)

| # | file:line (verified) | today | after |
|---|---|---|---|
| 1 | `backend/wd/routers/vocab.py:75-82` `_ORDER` | `"freq": "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` · `"difficulty": "COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` | `"freq": learn_order.ORDER_SQL` · `"difficulty": f"COALESCE(w.difficulty + 1, w.stage_min, 6), {learn_order.ORDER_SQL}"` · `"alpha"` unchanged |
| 2 | `backend/wd/services/screen.py:65` (`screen_next`) | `ORDER BY {_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit` | `ORDER BY {_STAGE_DISTANCE}, {learn_order.ORDER_SQL} LIMIT :limit`; docstring `screen.py:3-4` "then frequency" → "then `learn_order.ORDER_SQL`" |
| 3 | `backend/wd/services/batches.py:61` `_SCREEN_ORDER` (used at :271 `select_words` and :697 `add_more`) | `f"{_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` | `f"{_STAGE_DISTANCE}, {learn_order.ORDER_SQL}"` (`from . import learn_order` joins the import at :31) |
| 4 | `backend/wd/ai/prewarm.py:52` (`candidates`) | `"ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT ?"` | `f"ORDER BY {learn_order.ORDER_SQL} LIMIT ?"`; docstrings :5 "by frequency" and :45 "most frequent first" → "in learning order (learn_order.ORDER_SQL)" |
| 5 | `backend/wd/routers/words.py:106` (lookup suggestions) | `"AND w.id != :exclude ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit"` | `f"AND w.id != :exclude ORDER BY {learn_order.ORDER_SQL} LIMIT :limit"` |

Exact fragment after the change, written out once: `w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma`
— for 筛词 / 推荐词 preceded by `CASE WHEN w.stage_min = :cur THEN 0 WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END,`
and for the `difficulty` sort preceded by `COALESCE(w.difficulty + 1, w.stage_min, 6),`.

Should lookup suggestions follow? **Yes, in the same commit.** (a) They are the same learner's view of the same 词库 — a pupil
typing `mon` should see `monday` (frq NULL, today unreachable in a 5-item list) rather than only `money, month…`; (b) one
constant = one explanation in API.md 22; (c) the cost is one pinned assertion (`test_words.py:86-87`, §5). Leaving it on frq
would require API.md to document two orders. The two `_STAGE_DISTANCE` copies (`screen.py:34-36`, `batches.py:60`) are not
unified here (out of scope; a follow-up can move both to `learn_order.stage_distance_sql()` with zero behaviour change).

### 2.4 Hook: `backend/wd/main.py`

* `startup` (`main.py:484-503`): after `seed_check(conn, cfg)` at **line 492** and before the `public_url_guess` block at :493:

  ```python
          seed_check(conn, cfg)
          learn_order.ensure_current(conn)   # fills ranks after 0014 / a policy bump / a seed imported by older code; never fatal
          guess = first_non_loopback_ipv4()
  ```
  Order matters: `seed_check` → `import_seed` already recomputed inside the import transaction, so `ensure_current` is a no-op
  on a seed change (≈ 0.1 ms: three kv reads + one indexed EXISTS) and fires only for the migration-just-applied, version-bump
  and seed-imported-by-old-code cases. It runs before `start_background` so the 08:00 batch build and prewarm never see NULL ranks.
* Imports (:68): `from .seed import import_seed, seed_digest` + `from .services import learn_order`.
* Module docstring pipeline (:8-10): `migrate → seed import … → learn_order.ensure_current → kv.public_url_guess → …`.

### 2.5 Hook: `backend/wd/seed.py`

* Inside `import_seed`'s transaction (`seed.py:469-503`), after `_rebuild_forms(conn, rows, stats)` at **line 476** and before
  `db.kv_set(conn, "seed_version", digest, now=now)` at :477:

  ```python
          _rebuild_forms(conn, rows, stats)
          lo = learn_order.recompute(conn, now=now, seed_version=digest, trigger="seed_import")  # same transaction: ranks and seed_version land together
          stats.learn_rank_changed = lo.changed
          db.kv_set(conn, "seed_version", digest, now=now)
  ```
  `seed_version=digest` is passed explicitly because `kv.seed_version` is written one statement later; the stamp must equal
  the value `ensure_current` will compare against.
* `SeedStats` (:132-158): new field `learn_rank_changed: int = 0` (flows into `--report` JSON through `as_dict`).
* The `seed_imported` event detail (:482-500): new key `"learn_order": {"version": lo.version, "changed": lo.changed}`.
* `format_stats` (:548-552): append `, {stats.learn_rank_changed} learn ranks changed`.
* Module docstring bullets (:28-31): one bullet "`learn_rank` is recomputed for every row inside the same transaction
  (`services.learn_order.recompute`, DESIGN §3.2); a dry run computes nothing".
* `dry_run` path (:464-467): unchanged — nothing is written; `wd learn-order --dry-run` answers "what would the ranks do".
* Import (:56-60): `from .services import learn_order` next to `from .services.words import …` (no cycle, §2.2).

### 2.6 Hook: `backend/wd/services/words.py`

* `_INSERT_WORD_COLUMNS` (`words.py:592-596`): append `"learn_rank"` (DDL order — `ADD COLUMN` appends; the tuple comment
  "in DDL order" stays true). `_INSERT_WORD_SQL` (:597-601) picks it up automatically (`:learn_rank`).
* `_insert_word` (:604-611):

  ```python
  def _insert_word(conn, cols):
      """Insert a ``words`` row unless its lemma exists (UNIQUE lemma race-safe); returns ``(row, created)``.
      ``learn_rank`` is filled best-effort from the stored per-stage table (``learn_order.best_effort_rank``); the next
      recompute (startup / seed import / `wd learn-order`) makes it exact."""
      params = dict(cols)
      params.setdefault("learn_rank", learn_order.best_effort_rank(conn, params))
      cur = conn.execute(_INSERT_WORD_SQL, params)
  ```
  Both callers — `_resolve_ecdict` (:667-700, ECDICT rows carry pos/frq/bnc/stage flags via `ecdict.word_columns`,
  `ecdict.py:168-188`) and `_create_provisional` (:703-723, NULL dictionary fields, `stage_min` NULL) — need no change.
  `_word_defaults` (:569-588) is NOT given a `learn_rank` key: the rank is computed, not defaulted.
* Runtime writers that may change a rank input afterwards (grep `UPDATE words SET`): `ai/lookup.py:317` (`kind` on rename),
  `ai/lookup.py:368` (`pos` when NULL, `kind` for the user's own row), `ai/consolidate.py:292` (fill columns incl. `pos`),
  `services/suggestions.py:418` (undo restores `RESTORABLE_WORD_COLUMNS`). None changes `frq`, `bnc` or `stage_min`; a Claude
  `pos` is label-shaped (`'v./n.'`) and `dominant_pos` returns None for it, so these rarely move a rank. v1 adds **no** per-row
  refresh there: drift is reported by `learn_rank_matches_policy`, fixed by the next restart or `wd learn-order`. Optional
  one-liner if wanted later: `learn_order.refresh_row(conn, word_id)` after those four statements.

### 2.7 CLI: `backend/wd/cli.py` + the module's `register_cli`

* `cli.py:31-42` `CLI_MODULES`: add `"wd.services.learn_order"`; `cli.py:45-56` `COMMAND_OWNERS`: add
  `"wd.services.learn_order": ("learn-order",)` (`test_cli.py:58` asserts the two sets are equal).
* `wd learn-order` (default): refuse with one line when `db.current_version(conn) < 14` ("run `wd migrate` first", exit 1 —
  the `import-seed` precedent `seed.py:572-579`); otherwise `recompute(trigger="cli")` and print
  `learn order lo-1: 9618 rows, 42 updated in 0.05 s; 0 stage words unranked` (exit 0; exit 1 if stage words remain unranked).
  `--dry-run`: compute in memory, print `would update N (xs a, zk b, …); kv.learn_order.version lo-1 computed <at> for seed <digest[:12]>`,
  write nothing. `--show STAGE [--top N]` (STAGE ∈ `STAGE_ORDER`): print `show()` — `lemma  learn_rank  frq` per line. `--db PATH`
  like `wd check --db` (restore drills, rehearsal copies). Safe next to the live service: one ≤ 30 ms `BEGIN IMMEDIATE`;
  readers see old or new ranks (a browsing page boundary may shift once, exactly as after a seed import); no lease check needed.

### 2.8 Diagnostics: `backend/wd/diag.py`

* New constants next to `STAGE_INVARIANTS_FROM_VERSION` (:58): `LEARN_ORDER_INVARIANTS_FROM_VERSION = 14` (imported from
  `learn_order.LEARN_ORDER_FROM_VERSION`). `STAGE_INVARIANTS` itself is untouched — `test_diag.py:182-190` pins its SQL to the
  PLAN §6 S6 literal.
* `check_db` (:81-112): the kv tuple at :97 gains `"learn_order.version"` **before** `"backup.last"`
  (`test_diag.py:57` requires every line after `kv.backup.last` to be an `invariant` line); after the seed-version line (:105-107):

  ```python
          if version >= LEARN_ORDER_INVARIANTS_FROM_VERSION:
              for line, violated in _learn_order_lines(conn):
                  lines.append(line)
                  ok = ok and not violated
  ```
* `_learn_order_lines(conn)` (late import of `learn_order`, like `_seed_version_line` imports `seed_digest`) renders exactly:
  * `invariant learn_rank_present: ok` | `invariant learn_rank_present: N violation(s) (stage words without learn_rank — the next \`wd serve\` start or \`wd learn-order\` fills them)`
  * `invariant learn_order_current: ok` | `invariant learn_order_current: 1 violation(s) (kv.learn_order.version lo-0 ≠ code lo-1; run \`wd learn-order\`)` | `… (computed for seed 24f3b9496c14… ≠ kv.seed_version 9c0e3d1a7b55…; run \`wd learn-order\`)` | `… (never computed; run \`wd learn-order\`)`
  * `invariant learn_rank_matches_policy: ok` | `invariant learn_rank_matches_policy: N violation(s) (stored learn_rank differs from learn_order.rank_rows(); run \`wd learn-order\`)`
  Each flips `ok` to FAIL (one command fixes all three). A failing query is reported as `query failed (…)` and not counted,
  the `_invariant_line` rule. Cost: 0.00 + 0.01 + 18 ms.
* `__all__` (:361): add `LEARN_ORDER_INVARIANTS_FROM_VERSION`.

### 2.9 Rehearsal: `scripts/rehearse_migration.py`

* Constants (:54-58): `WORDS_INDEXES_0014 = ("ix_words_learn_rank",)`; import `from wd.services import learn_order`.
* `snapshot()` (:129-158): add `"has_learn_rank": has_column(conn, "words", "learn_rank")` and, when present,
  `"learn_rank_nonnull": SUM(learn_rank IS NOT NULL)`.
* New `check_0014(rep, conn, before, ran_here)` after `check_0013` (:272-289), modelled on `check_0012`:
  1. `words` has `learn_rank` with `type == 'INTEGER'`, `notnull == 0`, `dflt_value is None` (pragma table_info);
  2. `ix_words_learn_rank` exists and its SQL is `CREATE INDEX ix_words_learn_rank ON words(learn_rank)`;
  3. `words` row count unchanged; `v_bank` row count unchanged (no rebuild);
  4. when `ran_here`: `SUM(learn_rank IS NOT NULL) == 0` right after the file (the migration writes no values);
  5. then **recompute on the copy** (it is a private copy, PLAN §2.5): `r = learn_order.recompute(conn, trigger="rehearsal")`;
     check `learn_order.unranked_stage_words(conn) == 0`, `db.kv_get(conn, "learn_order.version") == learn_order.LEARN_ORDER_VERSION`,
     `learn_order.stale_count(conn) == 0`, a second `recompute` changes 0 rows (idempotent), `updated_at` MAX unchanged;
  6. `rep.info("小学 order (first 15)", …)` / `rep.info("初中-first order (first 15)", …)` from `learn_order.show(conn, "xs"|"zk", 15)` —
     the operator sees the order before touching production (FACTS §1 asked exactly for this preview);
  7. probes: `UPDATE words SET learn_rank = NULL WHERE id = ?` accepted inside BEGIN…ROLLBACK (`accepted()` helper) — NULL is a legal state.
* Dispatch in `rehearse()` (:371-374): after the 0013 block, `if 14 in recorded: check_0014(rep, conn, before, ran_here=14 in applied_versions) else: rep.skip("0014 checks", "not recorded in schema_migrations")`.
  `check_bookkeeping` (:162-175) is unaffected: ADD COLUMN changes no row counts; the recompute runs after it and only UPDATEs.
  `EXPECTED_TABLE_COUNT` stays 25; `check_empty_database` passes (0001 → 0014 on an empty table).
* Docstring (:20-31): one bullet for 0014 — "column + index present, every rank NULL right after the file, a recompute on the
  copy ranks every stage word, is idempotent and prints the head of the 小学 / 初中 order".

### 2.10 Frontend (optional but recommended): the 词库 sort label

The wire value `sort=freq` is kept (no `schemas.VocabQuery` Literal change at `schemas.py:503`, no `VocabSort` change at
`frontend/src/api/endpoints.ts:133`, `scripts/check_contract.py` untouched, `VocabPage.tsx:34` `SORTS` untouched). Only the label
changes, because 词频 would misdescribe the new order: `frontend/src/i18n/zh.ts:48` `sort: { freq: '推荐顺序', alpha: '字母', difficulty: '难度' }`
and the byte-identical mirror `docs/FRONTEND.md:254` (`npm run check:copy`). Alternative (not recommended now): a fourth value
`learn` as the default with `freq` kept as raw frequency — touches the Pydantic Literal, the TS union, `check_contract`, API.md §9
and §20, FRONTEND §8 and `VocabPage`; nothing in a K-12 app needs raw adult frequency as a user-facing sort when 难度 exists.
`WordBrief` does NOT gain `learn_rank` (`test_vocab.py:106-109` pins the exact key set; the TS ↔ Pydantic audit would need a
field): the order is observable, the key is an implementation detail; an admin-only exposure can come later.

---

## 3 Recompute / invalidation triggers and their cost (measured on the live copy, SQLite 3.54.1, Python 3.12)

| trigger | condition | where | cost |
|---|---|---|---|
| migration 0014 | pending file | `wd serve` start / `wd migrate` | 2.2 ms (ADD COLUMN + index; file 2,300 pages → 2,300, no growth), pre-migrate snapshot `backups/pre-migrate-13-to-14.db.gz` by the hook |
| startup, stale | `kv.learn_order.version ≠ "lo-1"` · `kv.learn_order.seed_version ≠ kv.seed_version` · `∃ stage word with NULL rank` | `main.startup` after `seed_check` | probe 0.00 ms (index) + three kv reads; recompute 41 ms = read 7.4 + compute 13.6 (incl. `dominant_pos` × 9,618) + write/commit 20–25; WAL +4.7 MB (every words page is touched once; auto-checkpointed at 1,000 pages) |
| startup, current | none of the above | same | ≈ 0.1 ms, nothing written |
| seed import | every `import_seed` that writes | inside the import's transaction | +41 ms on a ≈ 0.5 s import (release note §6 step 7); 0 extra fsyncs (same commit) |
| CLI | `wd learn-order` | operator | 41 ms (18 ms when nothing changes: read + compute + 0 UPDATEs + kv) |
| runtime insert | `_insert_word` | per created word | `rank_for` on one row from the stored table: < 0.01 ms (1,000 calls in 0.00 ms measured) + one kv read |
| `wd check db` | from schema 14 | operator / runbook | 0.00 + 0.01 + 18 ms |
| rehearsal | `check_0014` | `scripts/rehearse_migration.py` | one recompute on the copy ≈ 50 ms |

Not triggers (deliberately): `wd migrate` (the runner only runs SQL files; the next service start fills the ranks — the
install.sh path), the 03:30 maintenance (nothing changes the inputs nightly; an optional `learn_order.ensure_current(conn)` line
in `scheduler.maintenance` (`scheduler.py:380`) would cost ≈ 0.1 ms/day and close the runtime-drift gap of §2.6), `wd restore`
(the restored file carries its own ranks and stamps; if it predates 0014 the next start migrates and fills).

Concurrency: the write phase is one `BEGIN IMMEDIATE` ≤ 30 ms; request connections keep reading the previous snapshot (WAL);
a concurrent writer waits inside `busy_timeout=5000`. Two instances starting at once (lease waiter case) both recompute to the
same values — idempotent. `kv.learn_order.stats` is a few hundred bytes (store quantiles, not the full lists: the full lists
measured 54 KiB).

---

## 4 Integrity

**`wd check db` lines** (from schema 14, exact texts in §2.8): `learn_rank_present` (no stage word without a rank),
`learn_order_current` (version and seed stamp match), `learn_rank_matches_policy` (stored == `rank_rows()`, 18 ms). Before
schema 14 no line is printed (the `STAGE_INVARIANTS_FROM_VERSION` pattern). ops.md:19 and :123 list the invariant names and must
say seven instead of four.

**Rehearsal** (§2.9): `check_0014` plus the preview of the 小学 / 初中 order on the copy; exit status counts failures as today.

**Older server, newer seed / newer server, older seed.** The seed record format does not change (no new key, `seed_v` stays 2,
`SEED_COLUMNS` unchanged), so this mechanism introduces no new cross-version seed case — the main advantage over a seed-carried
rank. A newer server importing an older seed (`git checkout 75df534 -- data/seed/vocab.jsonl.gz && wd import-seed --force`,
release note §7) re-ranks from the restored inputs inside the import; consistent by construction.

**Older code on a schema-14 database** (code-only rollback): harmless, like 0012 — `seed._UPSERT_SQL` and
`words._INSERT_WORD_SQL` name their columns, every reader uses `sqlite3.Row` by name, `v_bank`'s column list was fixed at
creation. The old importer leaves `learn_rank` untouched (stale for changed frq) or NULL (new rows) and advances `kv.seed_version`;
when the new code returns, `ensure_current` sees `kv.learn_order.seed_version ≠ kv.seed_version` or a NULL stage rank and
recomputes. This is why the seed stamp is a trigger and not only the version constant.

**Newer code on a schema-13 database**: impossible in practice (startup migrates first); `wd learn-order` and `wd check db` gate on
`current_version ≥ 14` and say "run `wd migrate` first" / print no learn-order lines.

**Hand edits** (WORD_LIBRARY_CURATION §1.6): an admin-inserted row without `learn_rank` sorts LAST within its stage-distance
group (frq tail), no longer first — but the existing warning stays true: a row with stage flags and NULL `stage_min` still
has a NULL stage distance and sorts first for every user; `stage_min_consistent` flags it. The paragraph gains: after inserting
run `wd learn-order` (or restart) so the row gets its rank; `learn_rank_present` flags the omission.

**Atomicity**: `recompute` joins `import_seed`'s transaction, so a failing import leaves neither new rows nor new ranks
(`test_seed.py::test_import_is_atomic` gets one more assertion); standalone it is one `BEGIN IMMEDIATE`.

---

## 5 Tests

### 5.1 New

* `backend/tests/unit/test_learn_order.py` — the pure functions: `rank_rows` deterministic and equal to `rank_for` per row given
  `stage_stats` (if the policy is per-row pure, §1.6); every stage word of the mini seed gets a rank; ranks are cross-stage
  comparable integers; `recompute` writes only changed rows, never `updated_at`, is idempotent (second run `changed == 0`), joins
  an open transaction and rolls back with it, stores the four kv keys, writes `learn_order_recomputed` except for
  `trigger="seed_import"`; `is_current` / `ensure_current` fire on each of the three conditions and are a no-op otherwise;
  `ensure_current` never raises (monkeypatched failure → `system_events('learn_order_failed')`, service state unchanged);
  `best_effort_rank` before any recompute → None, after → equals `rank_for` with the stored table; `show()` order equals
  `ORDER_SQL`; `ORDER_SQL` text is the one quoted by API.md §20 (or pin that in `test_docs_contract.py`); `order_sql("x")` aliasing.
* `backend/tests/unit/test_db_0014.py` (the `test_db_0013.py` pattern): a v13 fixture database migrates to 14 — column, index,
  NULL ranks, `v_bank` intact, 25 tables, old explicit-column INSERTs (seed UPSERT, `_INSERT_WORD_SQL`) still succeed; empty DB 0001 → 14.
* `backend/tests/unit/test_main_learn_order.py` (sibling of `test_main_seed_check.py`): `startup` on a freshly migrated DB fills
  ranks (condition c) and logs; after `seed_check` imported, `ensure_current` is a no-op (stamps equal, no event); a failure never
  fails startup.
* `backend/tests/unit/test_seed.py` additions: ranks written in the same transaction; `seed_imported` detail has `learn_order`;
  `SeedStats.learn_rank_changed`; `test_dry_run_writes_nothing` asserts ranks untouched; `test_import_is_atomic` asserts no ranks after rollback.
* `backend/tests/unit/test_diag.py` additions: one test per new line — NULL a stage rank → `learn_rank_present: 1 violation(s) (…)`;
  `kv.learn_order.version='lo-0'` → `learn_order_current …`; hand-UPDATE a rank → `learn_rank_matches_policy: 1 violation(s) (…)`; the
  v13 database prints none of the three (extend `test_check_db_has_no_stage_invariants_before_schema_0011` with a 13-version variant).
* `backend/tests/unit/test_cli.py`: `learn-order` registered with `--dry-run / --show / --top / --db`; refuses below schema 14; exit codes.
* `backend/tests/unit/test_docs_contract.py`: API.md §20 and DESIGN §6.3 step 4 contain `learn_order.ORDER_SQL` (alias-stripped);
  DEPLOY §9 lists `learn-order`; WORD_LIBRARY_CURATION §1.6 mentions `learn_rank`; ops.md names the three invariants.
* `pytest -m full_seed` (`test_seed.py::test_full_seed_acceptance_numbers` area): on the full seed every stage word is ranked,
  `kv.learn_order.version == LEARN_ORDER_VERSION`, `stale_count == 0`, and `GET /api/vocab?stage=xs` page 1 equals the DB order.
* Frontend: `npm run check:copy` (FRONTEND §8 mirror) if the label changes; no vitest asserts `词频` (grep).

### 5.2 Existing pinned tests that must change (FACTS §3) — new expectation in words

| test | today | new expectation |
|---|---|---|
| `integration/test_vocab.py::test_vocab_default_is_everything_sorted_by_frequency` (:93-109) | first lemma `be`, `frq` ascending, NULL frq last | renamed `…_sorted_by_learn_order`: the 100 items equal `SELECT lemma … ORDER BY learn_rank IS NULL, learn_rank, (frq IS NULL OR frq = 0), frq, lemma` read from the DB (ranks are not in `WordBrief`); ranked rows precede unranked; the `WordBrief` key set is unchanged (no `learn_rank`); `bookshelf` (课标外) still listed under 全部. No literal lemma is pinned — the policy module owns literals. |
| `::test_vocab_sort_alpha_and_difficulty` (:163-181) | `sort_key` tail `(frq is None or frq == 0, frq or 0, lemma)` | tail becomes `(rank is None, rank or 0, frq is None or frq == 0, frq or 0, lemma)` with `rank` looked up per lemma from the DB; the chain `absorption < abandon < absolutely < ought to < bookshelf` still holds (it depends on `difficulty + 1` / `stage_min` only). |
| `integration/test_screen.py::test_next_order_and_remaining` (:122-139) | cet6 first three `absorption, axe, ought to`; zk first three `go, person, better` | the first three are the three `stage_min = 5` words in `ORDER_SQL` order (set unchanged; `ought to` has frq NULL and may move); zk: the first three `stage_min = 2` words in `ORDER_SQL` order (the mini seed has `go, person, better, decide, receive, bank, base, ability, recent, color, mountain, a.m.` there — `a.m.` has frq NULL, so under spreading the literal triple can change) — compute both from the DB with the `qrows` helper. |
| `::test_next_auto_for_a_primary_school_learner_orders_by_stage_distance` (:142-158) | `expected_xs` via `ORDER BY (frq IS NULL OR frq = 0), frq, lemma` | the same query with `ORDER BY learn_rank IS NULL, learn_rank, (frq IS NULL OR frq = 0), frq, lemma`; distances 0/1/3 structure unchanged. |
| `unit/test_batches.py::test_build_batch_caps_ordering_and_counts` (:104-136) | `screens == ["absolutely", "axis"]` | the first two `stage_min = 4` public valid words in `ORDER_SQL` order, read from the DB (a closed-class policy keeps the literal — adverbs are content — but the test should not pin policy). |
| `::test_build_batch_cold_start_puts_screens_first` (:152-164) | kinds only | **no change** (asserts kinds and counts, not lemmas); listed for verification. |
| `integration/test_words.py::test_lookup_preview_shapes` (:86-87) | `frqs == sorted(frqs)` for `q=ab` suggestions | suggestion ranks ascending with NULL last (from the DB), since suggestions follow `ORDER_SQL`. |
| `unit/test_diag.py` (`INVARIANT_NAMES` :27, `…four…` :49-57, `:85`, `:199` `count == 4`) | four names / four lines | seven names in order (`…seed_version_matches_file, learn_rank_present, learn_order_current, learn_rank_matches_policy`); `test_stage_invariant_sql…` (:182-190) unchanged because `STAGE_INVARIANTS` is untouched and `INVARIANT_NAMES[:3]` still matches. |
| `unit/test_main_seed_check.py::test_normal_path…` (:30-36) `kinds(conn) == ["seed_imported"]` | one event | unchanged by design (the import-path recompute writes no event); verify. |

---

## 6 Documentation edits by section

* **API.md §20** (`docs/API.md:169`): `sort=freq` (default; UI label 推荐顺序): `ORDER BY learn_rank IS NULL, learn_rank, (frq IS NULL OR frq=0), frq, lemma`
  — `learn_rank` is the derived learning-order key (DESIGN §3.2; NULL = not computed yet, such rows sort last by frequency);
  `difficulty`: `ORDER BY COALESCE(difficulty + 1, stage_min, 6), <same tail>`. Endpoint 22 (`GET /api/lookup`): suggestions "in
  the same order". Endpoint 31 keeps its DESIGN §6.3 step 4 reference. §9 TS types unchanged.
* **DESIGN.md §3.2** (`:205` row and a new row): `pos, collins, oxford, bnc, frq | same names | 0/null frequency = unknown; frq (else bnc) feeds the derived learn_rank and is the tie-break tail of every list`;
  new row `— | learn_rank | DERIVED, not in the seed: services/learn_order.py ranks every row from lemma/pos (dominant_pos)/frq/bnc/kind/sources/stage_min + per-stage statistics; recomputed inside every import, at startup when stale, by wd learn-order (migration 0014; policy version kv.learn_order.version)`;
  a short paragraph "学习顺序 (`learn_rank`)" after the tokens table stating the rank semantics of §1 and the fail-soft rule.
* **DESIGN.md §6.3 step 4** (`:367-368`): replace the two frq lines with `ORDER BY stage_distance(w.stage_min, current_stage) ASC, w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq=0) ASC, w.frq ASC, w.lemma ASC   # learn_rank = derived learning order (§3.2), frq only as the tail`.
* **DESIGN.md §6.2** (`:350`, last sentence): "…derive from the user's own choice; inside a stage the order is the derived `learn_rank` (§3.2), not adult corpus frequency."
* **FRONTEND.md §4** `/vocab` (`:147`): "sort (default 推荐顺序 = `sort=freq`, the learning order of API.md 20; 字母; 难度)"; **§8** (`:254`) byte-identical to `zh.ts:48`.
* **CLAUDE_INTEGRATION.md:303**: "…not yet enqueued, by frequency" → "…not yet enqueued, in learning order (`words.learn_rank`, the order of 筛词 / 词库, API.md 20)".
* **WORD_LIBRARY_CURATION.md:150** (选词规则): "按阶段距离 → 学习顺序 `learn_rank`（为空排最后）→ 词频 → 字母序。`learn_rank` 由 `services/learn_order.py` 派生，启动、导种子、`wd learn-order` 时重算；手工插入的行在重算前排在同距离组的**末尾**（不再是第一位），但 `stage_min` 为空仍排第一的告警不变 — 所以插入时给全 `stage_*`、`stage_min`、`frq`/`pos`，然后 `wd learn-order`"; row C10 at `:296` accordingly; §1.5's "不能做" list gains "改排序只能改策略版本（`LEARN_ORDER_VERSION`），不能手改 `learn_rank`（`wd check db` 会报）".
* **DEPLOY.md §9** (`:421`): add `learn-order [--dry-run] [--show STAGE [--top N]] [--db PATH]` [`wd.services.learn_order`]; **§10** (`:425`): add `0014_learn_rank.sql` to the additive examples.
* **ops.md:19 / :123**: seven invariants; name the three new ones.
* **Release note** `docs/releases/2026-11-k12-stages.md` §9 末 (`:212-213`): mark "小学阶段的全部顺序…仍按成人语料 `frq` 排序" as resolved by `0014_learn_rank` + `services/learn_order.py`, link a new short note `docs/releases/2026-11-learn-order.md` (what changed, the restart-only deployment of §7, `wd check db` seven lines, rollback). PLAN §9.2 #5 (`PLAN.md:755`) is an analysis document — leave it, the release note carries the resolution.
* **SCHEMA.sql**: unchanged (byte-identical to 0001, pinned by `test_db.py`); the 0014 file's header comment is the schema documentation of the column.

---

## 7 Deployment and rollback

### 7.1 The Mac (launchd) — why one restart is the whole deployment

1. 0014 is additive (no `DROP`/`RENAME`, no CHECK change, no view touched) — the DEPLOY §10 class that `0010`/`0012` are in.
2. `wd serve`'s lifespan applies pending migrations itself with the pre-migrate snapshot (`main.startup:489`, `db.run_migrations`);
   the release note §6 stop-first runbook existed only because 0011/0013 rebuilt tables.
3. The same startup fills the ranks (`ensure_current`, condition "stage word with NULL rank") before the app serves a request,
   and `seed_check` is a no-op (digest unchanged — the seed file is not touched by this change).
4. No `.env` change, no new dependency, no new table.
5. The frontend is only affected if the 词库 sort label changes (§2.10); the API shape is unchanged.

Runbook (`D=/Users/sqin/word-dance-data`, `export WD_DATA_DIR=$D`):

```sh
# 0 rehearse on a private copy (service may keep running; VACUUM INTO gives a consistent copy)
M=<private dir>; .venv/bin/python -c "import sqlite3; sqlite3.connect('$D/word-dance.db').execute(\"VACUUM INTO '$M/word-dance.db'\")"
git checkout <new sha> && .venv/bin/pip install -e backend            # no new deps; editable install already points here
.venv/bin/python -I scripts/rehearse_migration.py $M/word-dance.db    # expect: pending exactly (14,'learn_rank'); check_0014 ok; the 小学 / 初中 head printed; exit 0
WD_DATA_DIR=$M .venv/bin/wd learn-order --show xs --top 30            # eyeball the order the pupils will see
WD_DATA_DIR=$M .venv/bin/wd check db                                  # seven invariant lines ok
# 1 (only if zh.ts changed) build + publish the snapshot exactly as release note §6 steps 1 and 5 (SHA.new → SHA, symlink swap via os.rename)
# 2 restart = migrate + recompute
launchctl kickstart -k gui/$(id -u)/com.word-dance.server
curl --noproxy '*' http://127.0.0.1:8000/api/health
grep -E "applied migration 0014|learn order|MigrationError|learn_order_failed" ~/Library/Logs/word-dance/word-dance.log | tail
ls $D/backups/pre-migrate-13-to-14.db.gz
.venv/bin/wd check db                                                 # seven invariant lines ok on the live DB
# 3 verify in the UI: 词库 小学 tab first page, 筛词 (GET /api/screen/next?stage=xs&count=30), the admin 预生成 preview
```

Downtime: the restart (≈ 1–2 s) + 2 ms migration + 41 ms recompute. No `VACUUM` needed (no page growth).

### 7.2 Lighthouse (systemd, `deploy/install.sh`)

`deploy/install.sh` stops the unit (:123), publishes the snapshot, runs `wd migrate` (:140 — applies 0014) and `wd import-seed`
(:141 — no-op, same digest), starts the unit (:158); the service start then fills the ranks. `--no-restart` is allowed for
this release (additive) but unnecessary. Add `wd check db` after the start (seven lines) to the Lighthouse runbook
(docs/QUICK_DEPLOY_AND_MOBILE.md). A database copied from the Mac after the Mac deployment already carries ranks and stamps —
nothing happens on the VPS except the version check.

### 7.3 Rollback

* **Code-only** (bad policy, bad label): `git checkout cd3df8c && launchctl kickstart -k …` (+ previous frontend snapshot symlink if
  the label shipped). Old code ignores `learn_rank` (§4), lists return to the frq order immediately; the column and kv keys stay
  and are harmless; no data loss. This is the normal rollback — unlike 0011 there is no "DB and code together" constraint.
* **Policy-only**: ship a new `LEARN_ORDER_VERSION`; the next restart recomputes (41 ms). No migration, no seed.
* **Full snapshot**: `launchctl bootout …; wd restore $D/backups/pre-migrate-13-to-14.db.gz --yes; git checkout cd3df8c; bootstrap` —
  only if the file itself must go back; loses the learning records since the snapshot (release note §7 caveat), so not recommended for 0014.

---

## 8 Risks, blast radius, size

Risks (likelihood · impact · mitigation):

1. The policy produces an order the owner dislikes · likely during tuning · the rehearsal preview (`check_0014` info lines,
   `wd learn-order --show`) shows it before deployment; a policy bump is a restart; code-only rollback restores frq.
2. `sort=freq` keeps its wire name but changes meaning · certain · label change + API.md §20; no client caches (`no-store`).
3. Tests pinned on literal lemmas drift with every policy iteration · certain if literals stay · the expectations in §5.2 are
   derived from the DB; literals live only in `test_learn_order.py`.
4. Startup grows by the recompute on every stale start · 41 ms, negligible · failure is never fatal (`ensure_current`).
5. Runtime drift (`pos`/`kind` written by lookup/consolidation after the rank) · rare, tiny effect · reported by
   `learn_rank_matches_policy`; optional nightly `ensure_current`.
6. A recompute while the service runs (CLI) shifts a browsing page once · harmless · documented.
7. Exact positional spreading (if chosen) makes the single-row path approximate · design choice · prefer a per-row-pure
   spreading (§1.6) or accept "stale until next recompute" for runtime rows.
8. WAL +4.7 MB per full recompute · on every policy bump or seed import · auto-checkpoint; no `VACUUM`.
9. `wd check db` now imports `learn_order` → `images.style` → `config`: `Settings` is already loaded by `check`; no new failure mode
   (late import like `seed_digest`).

Blast radius: 5 query sites (vocab, screen, batches, prewarm, words router), 3 hooks (main, seed, words service), diag, cli,
rehearsal script, 1 migration, 1 new module; docs API/DESIGN/FRONTEND/CLAUDE_INTEGRATION/WORD_LIBRARY_CURATION/DEPLOY/ops/release
note; frontend 1 line. No schema change beyond one nullable column + one index; no API contract change; no seed/builder change.

Size estimate: code ≈ 14 files / ≈ 420 lines (new module ≈ 250 incl. CLI and docstrings, migration ≈ 15, hooks ≈ 25, diag ≈ 40,
rehearsal ≈ 60, five sites ≈ 10, cli ≈ 3, zh.ts 1); tests ≈ 7 files / ≈ 380 lines (new ≈ 250, changed ≈ 130); docs ≈ 9 files /
≈ 80 lines + a ≈ 40-line release note. One commit for the mechanism with the stand-in policy constants, one for the final policy.

---

## 9 Extensibility to a textbook / grade order field

* A 教材/年级/单元 order arrives as DATA (seed record key, e.g. `textbook: {"pep": "3A-U2"}` or a `seq`), lands in a column by an
  additive migration (`0015`: `words.textbook_seq INTEGER` or, for several schemes, a side table `word_orders(word_id, scheme, seq)`),
  and becomes one more member of `INPUT_COLUMNS` / `WordInput`. `rank_for` uses it as the primary key inside the stage (textbook
  order first, the current policy as the tail for words the textbook does not cover); `LEARN_ORDER_VERSION` bumps → every
  deployment re-ranks at its next start. Nothing changes at the five sites, in `wd check db`, the CLI or the rehearsal.
* If the order becomes **per user** (a pupil on 人教版 vs. one on 牛津上海版), one derived column no longer suffices. The mechanism
  then grows in one of two ways, both keeping the call sites: (a) one derived column per scheme (`learn_rank_pep`, `learn_rank_oup`)
  and `order_sql(scheme)` chosen from `user_settings.order_scheme` — the recompute/invariant/CLI machinery runs per scheme; or
  (b) the side table joined at the five sites (`LEFT JOIN word_orders o ON o.word_id = w.id AND o.scheme = :scheme`) with
  `ORDER BY o.seq IS NULL, o.seq, <ORDER_SQL>`. (a) is the straight extension of this design; (b) is the stages-as-data analogue
  DESIGN §3.1 already reserves for 拓展 layers. The per-stage statistics table generalises to per-(stage, scheme).
* The 课标外 group (`stage_min NULL`) already has its own statistics group, so a future "拓展" layer or a sixth stage only adds a
  group key; nothing in the mechanism assumes five stages (`STAGE_ORDER` stays the single source).

---

Appendix — simulation scripts (all under `${OUT}/sim-derived-column/`, run with `/Users/sqin/word-dance/.venv/bin/python -I`):
`probe.py` (read-only facts of the live copy: schema 13, 9,618 rows, 9,380 stage words, inputs read in 9 ms, current plans);
`sim_recompute.py` (scratch copy: 0014 draft 2.9 ms, recompute 45 ms / no-op 18 ms, stale diff 18 ms, startup probe 0.02 ms,
the eight list queries with and without the index, stand-in order samples); `sim_extend.py` (new: index shapes A/B/C, WAL 4.7 MB
per full recompute, `sqlite_stat1` present, `v_bank` uses `w.*`, single-row rank cost, compact 379-byte stats table, the robust
ORDER BY tail placing two NULL-rank rows last by frq).
