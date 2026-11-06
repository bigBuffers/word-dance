# Mechanism design — learning order carried by the seed (`words.learn_rank`, seed record v3)

Angle: **the seed is the source of truth**. The builder computes one integer `learn_rank` per record, the importer maps it onto a new column (migration 0014, additive, no rebuild), falls back to computing it for v2 files, `stats.json` carries the per-stage distribution, `DIFF.md` shows what moved, and runtime words get their rank from the same shared helper. Everything below is independent of the exact ordering policy: the policy is one pure function in one module; its inputs are fixed (lemma, `pos` via `wd.images.style.dominant_pos`, `frq`, `bnc`, `kind`, `sources` tokens, `stage_min`, plus per-stage statistics).

Inputs: FACTS.md (2026-11-06), the repository at `cd3df8c` (read only), the read-only live copy, and three simulation scripts under `sim-seed-carried/` (`probe_db.py`, `time_rank.py` reused from the cut-off attempt and re-run; `sim_seed_carried.py` new, end to end). All numbers in this document come from those runs on this Mac (Python 3.12, SQLite 3.54.1); `sim_output.txt` holds the full log. The ordering **policy** used in the simulations is a stand-in so that costs are realistic; nothing here decides the policy.

---

## 0 Decision summary

| Question | Answer |
|---|---|
| Where is the order computed? | In `backend/wd/learn_order.py` (new, ~180 lines). Three callers: the seed builder (`seedbuild/build.make_records`), the seed importer (`seed.import_seed`: v2 fallback + verification of carried values), runtime word writers (`services/words._insert_word`, the three lookup / consolidation / suggestion-restore `UPDATE words` sites). `wd check db` and `scripts/rehearse_migration.py` call the same module. |
| Where is it stored? | `words.learn_rank INTEGER NULL` (migration 0014, `ALTER TABLE … ADD COLUMN`, no index); in the seed file as record key `learn_rank` (`seed_v: 3`); per-stage statistics in `stats.json.learn_order` and, after import, in `kv.learn_order.stage_stats` + `kv.learn_order.policy` for runtime rows. |
| What is `learn_rank`? | An integer **sort key** (lower = earlier), not a dense position. Ties are broken by `lemma` in SQL. `NULL` = not ranked, sorts **last** inside its stage-distance group — the same contract `frq` NULL/0 has today. Reason: a key is a per-word function of the word plus frozen stage statistics, so a word created at runtime (ECDICT hit, provisional word, lookup-filled `pos`) can be ranked in isolation; a dense rank would need renumbering on every insert. |
| The five ORDER BY sites | All replace the tail `(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma` with the one constant `learn_order.ORDER_TAIL = "(w.learn_rank IS NULL), w.learn_rank, w.lemma"`. `_STAGE_DISTANCE` stays in front where it is today. Lookup prefix suggestions follow too (one tail in the codebase; one test line). Prewarm follows (content is generated for the words learners meet first). |
| What does a later policy change cost? | Edit one function + bump `POLICY_VERSION`; update `test_learn_order.py` literals; `make seed` (relabel-only build, no ECDICT needed, ~1 s) → commit the regenerated `vocab.jsonl.gz` / `stats.json` / `DIFF.md` (section (f) is the review artefact); regenerate `tests/fixtures/mini_seed.jsonl` with one command; deploy = restart (the content sha256 changes → `seed_check` re-imports, 9,618 rows rewritten in ≈ 0.4 s). No migration, no API/DTO change, no frontend build. |
| Deployment now | Mac: `git checkout <commit>` + `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`. `wd serve` applies 0014 (7 ms, pre-migrate snapshot `backups/pre-migrate-13-to-14.db.gz`), `seed_check` sees the cleared `kv.seed_version` and imports (≈ 0.4 s). No frontend snapshot unless the optional sort-label copy change ships. Lighthouse: plain `deploy/install.sh`. |
| Rollback | Code-only rollback is **safe** (unlike 0011): the old code ignores the column; its `seed_check` re-imports the v2 seed (0 rows changed, measured) and orders by `frq` again. No `wd restore` needed. |

---

## 1 Architecture and data flow

### 1.1 One function, three producers, one consumer set

```
                      data/lists/* + previous seed                      ECDICT stardict.db (only for NEW headwords)
                                  │                                                   │
                                  ▼                                                   │
   make seed ──► seedbuild/build.make_records ──► records (word, stages, sources, pos, frq, bnc …) ◄┘
                                  │   learn_order.rank_all(RankInput.from_record(r, kind=derive_kind(word)) for r)
                                  ▼
                 vocab.jsonl (v3: + learn_rank, seed_v 3)  stats.json (+ learn_order block)  ATTRIBUTION.md
                                  │ scripts/seed_diff.py → DIFF.md (+ section (f) learning order)
                                  │ scripts/pack_seed.sh (unchanged) → vocab.jsonl.gz  (content sha256 changes)
                                  ▼
   wd serve startup / wd import-seed ──► seed.import_seed
        │   seed_row: learn_rank = _int(rec.get("learn_rank"))            (v3: carried)
        │   after the parse loop: rows lacking a rank → learn_order.rank_all(all rows), fill the missing ones   (v2: fallback)
        │   always: verify carried ranks against rank_all → SeedStats.rank_mismatch (WARNING once; the seed's value wins)
        │   UPSERT writes learn_rank like any other SEED_COLUMN (updated_at moves for every row whose rank changed)
        │   kv.learn_order.policy, kv.learn_order.stage_stats written in the same BEGIN IMMEDIATE
        ▼
   words.learn_rank ──► ORDER BY {_STAGE_DISTANCE}, {learn_order.ORDER_TAIL}      (词库 sort=freq, 筛词, 每日推荐词, add_more, prewarm, lookup suggestions)
        ▲
        │   runtime rows: services/words._insert_word → learn_order.rank_for_row(conn, cols)   (ECDICT hit, provisional word)
        │   later pos/kind/lemma writers (ai/lookup, ai/consolidate, services/suggestions restore) → learn_order.refresh(conn, word_id)
        │
   wd check db: invariant learn_rank_present (SQL) · invariant learn_rank_matches_policy (learn_order.verify: recompute, compare)
   scripts/rehearse_migration.py: check_0014 + the same two invariants, skipped while the seed import is pending
```

### 1.2 Contracts that make the policy swappable

* **`RankInput`** is the only thing the policy sees: `lemma, pos, frq, bnc, kind, sources (frozenset of tokens), stage_min (1..5 or None)`. Two adapters build it: from a seed record (builder; `stage_min = stage_to_index(stages[0])`, `kind = services.words.derive_kind(word)` — the importer's own derivation, already used by `compute_stats`) and from a column mapping (importer `seed_row` dict, `_insert_word` cols, a `words` row; `sources` space-joined → split).
* **`stage_stats(inputs)`** is the only cross-row computation. It is computed over the whole file (builder, importer) and stored in `kv` at import so runtime rows use exactly the constants the shipped seed was built with. Invariant pinned by a unit test: `rank_all(inputs) == {i.lemma: rank_for(i, stage_stats(inputs))}` — a policy must be expressible as "one word + its stage's statistics" (statistics may carry whatever the policy needs, e.g. deciles of `frq`, the stage's median, the sorted list of frequency-less lemmas).
* **`POLICY_VERSION`** (string constant) travels with every output: `stats.json.learn_order.policy`, `system_events('seed_imported').learn_rank.policy`, `kv.learn_order.policy`. A server whose constant differs from the seed's keeps the seed's ranks (truth) and `wd check db` says so.
* **`ORDER_TAIL`** is the only SQL fragment; it assumes the table alias `w`, exactly as `_STAGE_DISTANCE` does.
* `learn_rank` is **never copied from the previous seed** by the builder (`DICT_KEYS` unchanged) — it is recomputed at every build, so "rebuild the seed" is the whole story of a policy change.

### 1.3 Why not the alternatives (one paragraph each, for the record)

A derived column recomputed by the server at startup would make the server, not the seed, the truth: two servers on different code would order differently with the same seed, and `make seed` reproducibility (`stats.json`, `DIFF.md`) would say nothing about order. Computing the key in SQL at query time was measured in the earlier `sim-qt` bench at 6–18 ms per request (vs 1–1.5 ms) and cannot express `dominant_pos` without a UDF. Carrying the rank in the seed keeps review (DIFF), rehearsal (`--dry-run`), and acceptance (`full_seed`) on the existing paths and costs one column.

---

## 2 File-by-file change list

Line numbers were verified by reading the files at `cd3df8c`.

### 2.1 New module `backend/wd/learn_order.py` (~180 lines)

```python
"""wd.learn_order — the learning order (学习顺序) of the vocabulary: ONE deterministic function from a word's own fields and
its stage's statistics to an integer sort key — `words.learn_rank`, seed record v3 `learn_rank` (DESIGN §3.2), the tail of
every "which word next" ORDER BY (DESIGN §6.3 step 4, API.md §20).

Producers: the seed builder (`seedbuild.build.make_records` → every record), the seed importer (`seed.import_seed`: fills v2
records that carry no rank and verifies carried ones), runtime word writers (`services.words._insert_word`, the pos/kind
writers in `ai.lookup`, `ai.consolidate`, `services.suggestions`). Consumers: the ORDER BY sites through :data:`ORDER_TAIL`,
`wd check db` and `scripts/rehearse_migration.py` through :func:`verify`.

Contract: `rank_all(inputs) == {i.lemma: rank_for(i, stage_stats(inputs)) for i in inputs}` — the policy is "one word plus its
stage's statistics", so a word created at runtime is ranked from the statistics the last import stored in kv
(:data:`KV_STAGE_STATS`) and agrees with what the builder would have written. A policy change edits :func:`_key` (and, when
it needs other statistics, :func:`stage_stats`), bumps :data:`POLICY_VERSION`, and rebuilds the seed (`make seed`); it never
touches a migration or an API type. Keys are compared only among words of the same stage distance (the sites put
`_STAGE_DISTANCE` first), so the absolute scale is free; ties are broken by lemma in SQL; NULL (never written by this module)
sorts last.
"""

POLICY_VERSION: str = "lo-1"
#: the tail of every learning-order ORDER BY (alias `w`): NULL last (an unranked hand-inserted row), then the key, then lemma
ORDER_TAIL: str = "(w.learn_rank IS NULL), w.learn_rank, w.lemma"
KV_POLICY: str = "learn_order.policy"
KV_STAGE_STATS: str = "learn_order.stage_stats"
STAGELESS_KEY: str = "none"  # the stage_stats key of words with stage_min NULL (课标外)


@dataclass(frozen=True)
class RankInput:
    """What the policy may look at. Built by the two adapters below and nowhere else."""
    lemma: str
    pos: str | None            # ECDICT share distribution; read ONLY through wd.images.style.dominant_pos (D-images-24)
    frq: int | None            # COCA-ish rank, None/0 = unknown
    bnc: int | None            # BNC rank, None/0 = unknown
    kind: str                  # word | phrase | abbreviation | proper_noun (services.words.derive_kind / words.kind)
    sources: frozenset[str]    # provenance tokens (moe22:app, shmeea20:phr, inherit:be …)
    stage_min: int | None      # 1..5 (schemas.STAGE_INDEX) or None

    @classmethod
    def from_record(cls, rec: Mapping[str, Any], *, kind: str) -> "RankInput":
        """Seed record (v2 or v3): stages[] → stage_min through schemas.stage_to_index; `kind` is passed in by the builder
        (words.derive_kind(word)) so this module does not import wd.services."""

    @classmethod
    def from_columns(cls, cols: Mapping[str, Any]) -> "RankInput":
        """A `words` row, the importer's seed_row dict or the `_insert_word` column mapping (`sources` space-joined)."""


@dataclass(frozen=True)
class StageStats:
    """Per-stage_min statistics the policy needs (JSON-serialisable; stored in kv and in stats.json.learn_order)."""
    n: int
    known: int                      # words with an effective frequency
    deciles: tuple[int, ...]        # of the effective frequency among `known` (empty when known == 0)

    def as_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "StageStats": ...


def stage_stats(inputs: Iterable[RankInput]) -> dict[str, StageStats]:
    """{'1'..'5', 'none'} → StageStats over the given inputs (the whole file or the whole table). Deterministic."""

def rank_for(inp: RankInput, stats: Mapping[str, StageStats]) -> int:
    """The key of ONE word under POLICY_VERSION given its stage's statistics (missing stage → the 'none' entry → a
    conservative default). Never returns None: every word this module sees gets a key."""

def rank_all(inputs: Sequence[RankInput]) -> dict[str, int]:
    """lemma → key for a whole file/table: stage_stats once, then rank_for each. Duplicate lemmas raise ValueError."""

def summary(inputs: Sequence[RankInput], ranks: Mapping[str, int]) -> dict[str, Any]:
    """The stats.json `learn_order` block: {'policy', 'per_stage': {code|'none': {n, from_frq, from_bnc, fallback, key_min,
    key_p50, key_max, first: [8 lemmas]}}} — keys in STAGE_ORDER order then 'none'. Numbers for tests and DIFF, never prose."""

def rank_for_row(conn: sqlite3.Connection, cols: Mapping[str, Any]) -> int | None:
    """Runtime path: the key for a row about to be written, from kv.learn_order.stage_stats (None when no import has run yet —
    the caller then stores NULL and the row sorts last until the next import ranks it). Ignores stats written by another
    POLICY_VERSION (kv.learn_order.policy differs) and recomputes them from the table instead (~7 ms, logged once)."""

def refresh(conn: sqlite3.Connection, word_id: int) -> bool:
    """Recompute the key of one existing row from its current columns and UPDATE words.learn_rank when it differs
    (no updated_at bump: the caller's UPDATE already moved it). Returns True when written. Used after pos/kind/lemma writes."""

def verify(conn: sqlite3.Connection) -> tuple[int, int]:
    """(rows, disagreements): recompute rank_all over the whole table and compare with the stored learn_rank. Runtime rows
    are compared too — they were ranked from the statistics of the same import, so they must agree. ~20 ms on 9,618
    rows. Backs the `learn_rank_matches_policy` invariant (diag) and the full_seed gate."""

def _key(inp: RankInput, st: StageStats) -> int:
    """THE policy (stand-in until decided). Pure; integer; lower = earlier."""
```

Imports: `wd.images.style.dominant_pos / FUNCTION_POS`, `wd.schemas.stage_to_index / STAGE_ORDER`, `wd.db.kv_get / kv_set`, stdlib. No `wd.services` import (no cycle: `seed.py`, `seedbuild`, `services.words` all import this module).

### 2.2 Migration `backend/wd/migrations/0014_learn_rank.sql` (draft, rehearsed on a copy: 7.3 ms through `run_migrations`)

```sql
-- 0014_learn_rank.sql — words.learn_rank: the learning-order sort key carried by seed record v3 (DESIGN §3.2; wd.learn_order).
--
-- Additive only (the 0012 precedent): one ADD COLUMN, no table rebuild, no view touched (v_bank lists its columns), so the file
-- is safe under `deploy/install.sh --no-restart` and a plain `launchctl kickstart -k` on the Mac. The runner wraps it in
-- BEGIN IMMEDIATE and records schema_migrations(14, 'learn_rank') itself (SCHEMA.sql §1) — nothing else belongs here.
--
-- The column is NULL after this file. kv.seed_version is cleared (the 0011 precedent) so the next `wd serve` start /
-- `wd import-seed` imports unconditionally and fills it: a v3 seed carries the values, a v2 seed gets them computed by the
-- importer through the same helper. Rows the seed does not know (ecdict/user words; none on the live database today) are
-- ranked when they are created or when a lookup fills their pos; a NULL key sorts LAST inside its stage-distance group,
-- exactly as an unknown frq did before (learn_order.ORDER_TAIL). No index: every learning-order query sorts after a CASE
-- (stage distance) or COALESCE (difficulty) term and uses a temp B-tree regardless (measured: ix_words_learn_rank changes no
-- plan and no timing). docs/SCHEMA.sql stays the 0001 baseline byte for byte (test_db.py).
ALTER TABLE words ADD COLUMN learn_rank INTEGER;   -- learning-order key, lower = earlier (wd.learn_order.POLICY_VERSION); NULL = not ranked yet

DELETE FROM kv WHERE key = 'seed_version';
INSERT INTO system_events(kind, detail_json, created_at)
VALUES ('migration', '{"version": 14, "name": "learn_rank", "note": "words.learn_rank added (NULL); kv.seed_version cleared so the next start / wd import-seed fills it from the seed"}',
        strftime('%Y-%m-%dT%H:%M:%SZ','now'));
```

Rehearsal facts (copy of the live DB): column `cid 36, INTEGER, notnull 0, no default`; all 9,618 rows NULL afterwards; row deltas only `kv 15→14, schema_migrations 7→8, system_events 19→20` (the set `rehearse_migration.BOOKKEEPING_TABLES` allows); `integrity_check ok`; `v_bank` 18 rows unchanged; a second run applies nothing; `page_count` unchanged (2300).

### 2.3 Seed builder `backend/wd/seedbuild/build.py`

| Where | Edit |
|---|---|
| `:83 SEED_V = 2` | `SEED_V = 3`. |
| `:102-105 RECORD_KEYS` | insert `"learn_rank"` between `"sources"` and `"aliases"` (fixed key order; `dumps_records` picks keys present). |
| `:107-109 DICT_KEYS` | unchanged — `learn_rank` is never carried from a previous record; a v3 previous seed round-trips (`test_rebuild_from_own_output_is_idempotent` stays green; measured: ranks identical). |
| `:51-56` module docstring "Seed record v2" | becomes "Seed record v3 … `learn_rank` integer on every record (also stageless ones), computed by `wd.learn_order` (`POLICY_VERSION`)". |
| `make_records` `:839-953` | after the loop and **before** the sort at `:952`: `inputs = [learn_order.RankInput.from_record(r, kind=words.derive_kind(r["word"])) for r in records]`; `ranks = learn_order.rank_all(inputs)`; `for r in records: r["learn_rank"] = ranks[r["lemma"]]`. Return `inputs` too (or recompute in `compute_stats`). The out-dict at `:927-934` gets the key after `"sources"` so `dumps_records` emits it in `RECORD_KEYS` order. The record sort key `(stage index, lemma)` at `:952` is unchanged — the FILE order stays by stage then lemma; the learning order lives in the value. |
| `BuildStats` `:977-1019` | new field `learn_order: dict[str, Any]` placed after `per_kind` (the `as_dict` order is the dataclass order; `test_stats_are_consistent_with_the_records` pins only the first six keys). |
| `compute_stats` `:1022-1074` | `learn_order=learn_order.summary(inputs, ranks)`. |
| `render_attribution` `:1219-1222` footer | optional one sentence: "`learn_rank` is a derived sort key computed by `backend/wd/learn_order.py` (policy `{stats.learn_order['policy']}`) from ECDICT frq/bnc/pos and list membership; it is not source data." |
| `_summary` `:1299-1314` | one line: `learn_order: policy lo-1; xs first: say, not, …` (from the stats block). |

`scripts/build_seed.py`, `scripts/pack_seed.sh` (reads only `total_words` / `content_sha256`), `Makefile` `seed` target `:105-115`: unchanged. A policy-only rebuild needs **no** `ECDICT_DB` (no new headwords) and is idempotent (two runs → identical bytes; measured deterministic).

Measured builder cost on the real seed: reading 9,618 v2 records 45 ms, `rank_all` 14.5 ms, serialisation + sha trivial; `vocab.jsonl` 5,602,203 → 5,796,293 bytes (+194 KB, ≈ 20 bytes/record), `vocab.jsonl.gz` 1,342,623 → 1,383,800 bytes (+41 KB). Content sha256 changes (`24f3b949…` → another value), which is what drives the import on every server at its next start.

### 2.4 Seed diff `backend/wd/seedbuild/diff.py` (+ `data/seed/DIFF.md`)

* `FIELD_KEYS :49-51`: **not** extended — `learn_rank` is not a dictionary field, so a policy-only rebuild shows 0 "dictionary-field changes" and all movement lands in the new section.
* `Diff :141-169`: new fields `order_note: str` ("old file carries no learn_rank (v2): positions compared against its frq order" or ""), `order_per_stage: dict[str, dict]` (per code and ∅: `records, rank_changed, moved_50, max_shift, first_old[10], first_new[10]`), `order_climbs / order_drops: list[{lemma, stage, old, new}]` (20 each).
* `compute :178-231`: positions per first stage under the old file's order (`learn_rank` when present, else the frq tail — exactly the SQL semantics: NULL/0 last, then frq, then lemma) and under the new file's `learn_rank`.
* `check_invariants :234-261` (section (e)): `every record carries an integer learn_rank when seed_v ≥ 3`; `stats.json learn_order.per_stage.n matches first_stage (and 'none' = stageless) and learn_order.policy is present` (skipped without stats.json, like the existing stats check).
* `render_md :275-416`: section `## (f) Learning order (learn_rank)` after (b): the note, the per-stage table, the two mover lists. Deterministic (sorted). `--only` gains `order`.

On the stand-in policy the first v3 diff reports (vs frq order): xs 600 records, 508 moved ≥ 50 places (biggest climbs `an 571→3`, `email 577→72`, `colour 574→207`); zk 1,660/1,949; gk 27/1,255; cet4 50/1,726; cet6 1,875/3,850; 课标外 99/238 — i.e. the section is informative precisely for the words the fact sheet complains about.

### 2.5 Seed importer `backend/wd/seed.py`

| Where | Edit |
|---|---|
| module docstring `:1-38` | bullet: "`learn_rank` is written from a v3 record; for records without it (v2 files) the importer computes it through `wd.learn_order.rank_all` over the whole file (the statistics need every row — the importer already loads the whole file); carried values are verified against the same function and a disagreement is counted (`SeedStats.rank_mismatch`, one WARNING: the seed's values win — the seed is the truth, the server may be older or newer); `kv.learn_order.policy` / `kv.learn_order.stage_stats` are written in the same transaction for runtime rows." |
| `SEED_COLUMNS :71-89` | append `"learn_rank"` → `_UPSERT_SQL :93-103` and `_PLAN_COLUMNS :105` follow automatically (the UPSERT's WHERE now also fires when only the rank differs). |
| `SeedPlan :108-129` | `rank_only: int = 0` — rows whose only differing column is `learn_rank` (so a policy deploy's `--dry-run` reads "update 9,618 (rank only 9,618)"). Set in `plan_import :335-340`. |
| `SeedStats :132-161` | `rank_from_seed: int = 0`, `rank_computed: int = 0`, `rank_mismatch: int = 0`, `rank_policy: str = ""`. |
| `seed_row :243-301` | `"learn_rank": _int(rec.get("learn_rank"))` in the returned dict (after `"ecdict_id"`). Docstring: "`learn_rank` (v3) — None for v2 records; filled by `import_seed`". |
| `import_seed` after the parse loop (`:450`, before the warnings at `:451`) | `inputs = [learn_order.RankInput.from_columns(r) for r in rows.values()]`; `ranks = learn_order.rank_all(inputs)`; for each row: if `row["learn_rank"] is None` → `row["learn_rank"] = ranks[lemma]`, `stats.rank_computed += 1`; else `stats.rank_from_seed += 1` and `if row["learn_rank"] != ranks[lemma]: stats.rank_mismatch += 1`. `stats.rank_policy = learn_order.POLICY_VERSION`. One WARNING when `rank_mismatch` (`event="seed_rank_mismatch"`): "N record(s) carry a learn_rank that differs from this server's policy lo-1 — the seed was built by other code; the seed's values are kept". Measured: 9,618 records, rank + verify 14–20 ms (72 ms including re-reading the file in the sim). |
| `import_seed` transaction `:469-503` | after `_rebuild_forms`: `db.kv_set(conn, learn_order.KV_POLICY, learn_order.POLICY_VERSION, now=now)`; `db.kv_set(conn, learn_order.KV_STAGE_STATS, json.dumps({k: v.as_dict() for k, v in learn_order.stage_stats(inputs).items()}), now=now)`. Event detail (`:483-499`) gains `"learn_rank": {"from_seed", "computed", "mismatch", "policy"}`. |
| `format_stats :523-552` | dry run: append `; ranks: {rank_from_seed} carried / {rank_computed} computed, {rank_mismatch} disagree with {rank_policy}; rank-only updates {plan.rank_only}`; real run: `; learn_rank {from_seed} from the seed, {computed} computed ({policy}), {mismatch} mismatches`. |
| `__all__ :615-628` | unchanged names. |

Importer behaviour measured on a schema-14 copy with the importer patched exactly like this (in process, repo untouched): first v3 import 393 ms, `inserted 0 updated 9618` (every row: `NULL → key`), `forms 14196`; re-import 6 ms `up_to_date`; `--force` 298 ms, 0 rows rewritten; a v2 file through the fallback: identical keys, 0 rows rewritten, only `kv.seed_version` flips; `--dry-run` afterwards: `update 0 / unchanged 9618`.

### 2.6 The ORDER BY sites (exact fragments)

All import `from .. import learn_order` (or `from ..learn_order import ORDER_TAIL`) and build the fragment with an f-string at module import time, as `_SCREEN_ORDER` already does.

| # | Site (verified) | Today | After |
|---|---|---|---|
| 1 | `backend/wd/routers/vocab.py:75-82` `_ORDER`, used at `:119` | `"freq": "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` · `"difficulty": "COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` | `"freq": learn_order.ORDER_TAIL` → `(w.learn_rank IS NULL), w.learn_rank, w.lemma` · `"difficulty": f"COALESCE(w.difficulty + 1, w.stage_min, 6), {learn_order.ORDER_TAIL}"` · `"alpha"` unchanged. The query key stays `freq` (no `VocabSort` / `check_contract.py` / `types.ts` change); the comment at `:78-80` gains "the frq tail is now the learning order, DESIGN §6.3 step 4". |
| 2 | `backend/wd/services/screen.py:65-66` (`screen_next`) | `ORDER BY {_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit` | `ORDER BY {_STAGE_DISTANCE}, {learn_order.ORDER_TAIL} LIMIT :limit`. Docstring `:3-4` "then frequency" → "then the learning order (`words.learn_rank`)". |
| 3 | `backend/wd/services/batches.py:61` `_SCREEN_ORDER` (used at `:271` `select_words` screens and `:697` `add_more` extra 推荐词) | `f"{_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` | `f"{_STAGE_DISTANCE}, {learn_order.ORDER_TAIL}"` — one edit covers both call sites. |
| 4 | `backend/wd/ai/prewarm.py:52` (`candidates`) | `ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT ?` | `ORDER BY {learn_order.ORDER_TAIL} LIMIT ?`; docstrings `:5` "by frequency" and `:45` "most frequent first" → "in learning order (`words.learn_rank`)". Prewarm **follows**: its purpose is content for the words learners will meet first. |
| 5 | `backend/wd/routers/words.py:106` (lookup prefix suggestions) | `ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit` | `ORDER BY {learn_order.ORDER_TAIL} LIMIT :limit`. **Follows**, so exactly one ordering tail exists in the codebase; cost = one assertion in `test_words.py:86-87` (below). If the owner prefers search-by-commonness here, leave this one site on `frq` and document it as the deliberate exception in API.md 22. |

`_STAGE_DISTANCE` keeps its two identical copies (`screen.py:34-36`, `batches.py:60`); deduplicating them is out of scope.

Query cost (copy of the live DB, median of 15, ms — `frq tail / rank tail / rank tail + index`): 词库 全部 p1 1.51 / 1.52 / 1.48 · 词库 小学 p1 0.71 / 0.72 / 0.73 · 词库 难度 1.58 / 1.58 / 1.62 · 筛词 auto xs+zk ×30 1.02 / 1.00 / 1.02 · 推荐词 ×15 (主攻 cet4) 1.65 / 1.59 / 1.62 · add_more ×5 0.96 / 0.95 / 0.95 · prewarm xs ×50 0.71 / 0.73 / 0.73 · lookup 'ab' 0.57 / 0.55 / 0.58. `EXPLAIN QUERY PLAN` with `ix_words_learn_rank` present: every site still `SEARCH w USING INDEX ix_words_public … USE TEMP B-TREE FOR ORDER BY` — the index is never used, hence none in 0014.

### 2.7 Runtime word writers

| Where (verified) | Edit |
|---|---|
| `backend/wd/services/words.py:569-588` `_word_defaults` | add `"learn_rank": None`. |
| `:592-596` `_INSERT_WORD_COLUMNS` / `:597-601` `_INSERT_WORD_SQL` | add `"learn_rank"` after `"ecdict_id"` (the SQL is rendered from the tuple). |
| `:604-611` `_insert_word(conn, cols)` | before `conn.execute`: `cols = {**cols, "learn_rank": learn_order.rank_for_row(conn, cols)}`. Covers `_resolve_ecdict` (`:684-690`, ECDICT rows carry pos/frq/bnc/stage flags from `EcdictEntry.word_columns`) and `_create_provisional` (`:705-716`, everything NULL → the 'none' default of the policy; the row is private anyway). Measured: kv read + key 0.0 ms. |
| `backend/wd/ai/lookup.py:317-320` `rename_word` (writes `kind`), `:350-352` + `:367-368` `fill_fields` (fills `pos`, may set `kind`) | after each `UPDATE words …`: `learn_order.refresh(conn, wid)`. Claude-filled `pos` is label-shaped (`'v./n.'`) → `dominant_pos` returns None → the policy treats it as a content word; the refresh keeps stored and computed in agreement (the `learn_rank_matches_policy` invariant). |
| `backend/wd/ai/consolidate.py:291-292` fill_data `UPDATE words SET …` (`FILL_COLUMNS` includes `pos`) | `learn_order.refresh(conn, int(word["id"]))` after the UPDATE. |
| `backend/wd/services/suggestions.py:414-418` undo/restore of `RESTORABLE_WORD_COLUMNS` (`:44`, includes `pos`, `kind`) | `learn_order.refresh(conn, int(wid))` after the UPDATE. |
| `backend/wd/ai/lookup.py:272` merge tombstone, `services/suggestions.py:432` unmerge, `consolidate.py:311/418` difficulty / validity | no edit: `difficulty`, `is_public`, `merged_into_word_id` are not policy inputs (`difficulty` must not become one: its scale is pinned and Claude-filled). |

Stage flags never change at runtime except through the seed import (which writes the rank in the same row), so no other hook exists.

### 2.8 Diagnostics `backend/wd/diag.py`

* New tuple next to `STAGE_INVARIANTS :50-57`:
  ```python
  # learning-order invariants (DESIGN §3.2 learn_rank; wd.learn_order). Only from 0014 on, and only once a seed import has run
  # (kv.seed_version set): between `wd migrate` and the import every seed row is legitimately NULL.
  LEARN_RANK_INVARIANTS_FROM_VERSION = 14
  LEARN_RANK_PRESENT_SQL = "SELECT COUNT(*) FROM words WHERE source = 'seed' AND learn_rank IS NULL"
  ```
* `check_db :101-108`: after the seed-version line, `if version >= 14: lines += learn_rank_lines(conn)` where `learn_rank_lines(conn) -> list[tuple[str, bool]]` returns
  * `invariant learn_rank_present: ok` | `N violation(s) (seed rows without a learning-order key; run wd import-seed)` | `skipped (seed import pending: kv.seed_version is empty)`;
  * `invariant learn_rank_matches_policy: ok` | `N violation(s) (stored keys disagree with wd.learn_order lo-1 — seed built by other code: rebuild it with make seed or upgrade the server)` | `skipped (seed import pending)` — implemented through `learn_order.verify(conn)` (python recompute, 19 ms on 9,618 rows; a hand edit of two rows is reported as 2 violations — measured).
* Keep `STAGE_INVARIANTS` untouched so `test_diag.py::test_stage_invariant_sql_is_the_plan_literal_rendered_from_the_enum` (`:182-191`) keeps pinning the PLAN literal; `__all__ :361` gains the new names.

### 2.9 `scripts/rehearse_migration.py`

* Constants `:54-58`: `WORDS_LEARN_RANK_COLUMN = "learn_rank"`.
* `snapshot :129-158`: add `snap["words_rows"]`, `snap["learn_rank_non_null"] = int(scalar(conn, "SELECT COUNT(*) FROM words WHERE learn_rank IS NOT NULL")) if has_column(conn, "words", "learn_rank") else None`.
* New `check_0014(rep, conn, before, ran_here)` modelled on `check_0012 :254-269`: column present with `type INTEGER, notnull 0, dflt_value None`; when `ran_here`: every row NULL, `kv.seed_version` gone (`was {before['kv_seed_version']!r}`), last `system_events` row is the 0014 trace (`'"version": 14'`), `words` row count unchanged, index set of `words` unchanged (no `ix_words_learn_rank`), `v_bank` row count unchanged; probe: `UPDATE words SET learn_rank = 1 WHERE id = ?` accepted and rolled back.
* `rehearse :363-376`: `if 14 in recorded: check_0014(...) else rep.skip("0014 checks", …)`.
* `check_invariants :291-299`: after the stage invariants, the two learning-order lines through the same `diag.learn_rank_lines(conn)` so the script and `wd check db` cannot drift; a `skipped (seed import pending)` is printed as `[skip]`, not a failure (0014 clears `kv.seed_version`, so on a fresh rehearsal both are skipped — correct).
* Docstring bullets `:16-31`: add the 0014 bullet and "the two learning-order invariants are skipped until a seed import has run on the copy".
* Optional (`--import-seed PATH`): after the migrations, `seed.import_seed(conn, PATH)` on the copy and re-run the invariants — this is what the release-note rehearsal does by hand today (`WD_DATA_DIR=$M wd import-seed`), so it can stay manual.

### 2.10 CLI / startup

No new command. `wd import-seed [--dry-run] [--force] [--report]` gains the ranks clause in its output (`format_stats`); `--dry-run` on the live database before the deploy prints `update 9618 … rank-only updates 9618` — the release note must say that this is expected. `main.seed_check :299-327` and `startup :484-504` are unchanged: the cleared `kv.seed_version` makes the normal path import.

### 2.11 Tests fixtures and data

* `backend/tests/fixtures/mini_seed.jsonl` (62 v2 records): regenerate as **v3** with the real helper so carried ranks are exercised by the whole suite and `test_changed_record_updates_only_that_row` keeps its meaning (a v2 fixture would route every test through the fallback, where moving one record between stages changes that stage's statistics and therefore other rows' computed keys — on a 62-record file the ripple is certain). Command (documented in the fixture README / test docstring): `.venv/bin/python -I -c "from wd.seedbuild import build as B; …"` — concretely a 15-line `scripts/rank_fixture_seed.py` or an inline snippet that reads the jsonl, calls `learn_order.rank_all(RankInput.from_record(r, kind=derive_kind(r['word'])))`, writes `learn_rank` + `seed_v: 3` in `RECORD_KEYS` order. Keep `backend/tests/fixtures/seed_v2/` v2 files (plus a copy of the mini seed without ranks, `mini_seed_v2.jsonl`) for the fallback tests.
* `data/seed/vocab.jsonl.gz`, `stats.json`, `DIFF.md`: regenerated by `make seed ECDICT_DB=<stardict.db>` (ECDICT optional for a relabel-only build; passing it changes nothing) and committed with the code.

---

## 3 Recompute / invalidation triggers and their cost

| Trigger | What recomputes | Where | Measured cost |
|---|---|---|---|
| `make seed` (lists changed **or** policy changed) | every record's `learn_rank`; `stats.json.learn_order`; `DIFF.md (f)` | builder | read 45 ms + rank 14.5 ms (+ the existing build ≈ 1 s); +41 KB gz |
| New seed content sha256 on a server (next `wd serve` start or `wd import-seed`) | UPSERT of every row whose `learn_rank` (or any seed column) differs; `kv.learn_order.*` | importer | 0.39 s first v3 import (9,618 rows), 0.30 s when nothing differs; rank + verify ≤ 20 ms |
| Migration 0014 | nothing — fills come from the forced import it schedules by clearing `kv.seed_version` | runner + importer | 7 ms + the import above |
| v2 seed file on a v14 server | ranks computed for every record lacking one | importer fallback | 14.5 ms, inside the import |
| New ECDICT / provisional row | that row's key from `kv.learn_order.stage_stats` | `_insert_word` | 0.0 ms (one kv read + one function) |
| Lookup fills `pos` / sets `kind` / renames; consolidation fill_data; suggestion-restore of pos/kind | that row's key (`refresh`) | three hooks | one SELECT + at most one UPDATE |
| Policy change without a rebuild (code deployed, old seed) | nothing is rewritten; `wd check db` reports `learn_rank_matches_policy: N violation(s)` until the seed is rebuilt or the import is forced (`wd import-seed --force` makes the fallback/verify path rewrite nothing — the seed's values win). Rule: a policy change **is** a seed rebuild; ship them in one commit. | — | — |
| `kv.learn_order.stage_stats` from another `POLICY_VERSION` | `rank_for_row` ignores it and recomputes stats from the table once (7 ms), logging a warning | runtime | 7 ms once |

Side effects of the first v3 import worth naming:

* `words.updated_at` moves for **all** 9,618 rows (16 distinct values → 1, measured). The template-card LRU (`images/card_svg.py:6, :21, :156`, key `(word_id, active_content_id, updated_at)`, 2,000 entries in memory) misses once per word afterwards and re-renders (pure template, sub-millisecond); the browser's `private, max-age=86400` card cache is untouched and visually correct (the card does not show the rank). The same happens on every later policy rebuild. No other reader of `updated_at` exists in the stage/order paths (`WORD_LIBRARY_CURATION.md §1.6` already documents the LRU key).
* `wd import-seed --dry-run` reports every row as `updated` once — expected, and labelled by the new `rank-only updates N` clause.
* `system_events('seed_imported')` carries `learn_rank.{from_seed, computed, mismatch, policy}` for the admin events page.

---

## 4 Integrity

### 4.1 `wd check db` text (from 0014 on; both lines `skipped (seed import pending …)` while `kv.seed_version` is empty)

```
invariant learn_rank_present: ok
invariant learn_rank_present: 9618 violation(s) (seed rows without a learning-order key; run wd import-seed)
invariant learn_rank_matches_policy: ok
invariant learn_rank_matches_policy: 2 violation(s) (stored keys disagree with wd.learn_order lo-1 — seed built by other code: rebuild it with make seed or upgrade the server)
invariant learn_rank_matches_policy: skipped (seed import pending: kv.seed_version is empty)
```

Costs on the live-size copy: present 0.5 ms (SQL), matches_policy 19 ms (python). `wd check db` therefore prints six `invariant` lines after an import (four stage + two order).

### 4.2 `scripts/rehearse_migration.py` additions — see §2.9. Expected rehearsal transcript on a copy of today's live DB: `[ok] every pending file applied` `[(14, 'learn_rank')]`, `[ok] only bookkeeping tables changed row counts`, `[ok] words.learn_rank column INTEGER NULL`, `[ok] every row NULL after 0014`, `[ok] kv.seed_version cleared (forces the seed re-import)`, `[ok] last system_events row is the 0014 migration trace`, `[ok] words indexes unchanged`, `[skip] invariant learn_rank_present: seed import pending`, `[skip] invariant learn_rank_matches_policy: seed import pending`, `[ok] second run applies nothing`, `[ok] empty database applies every shipped file` (`0001 → 0014`, 25 tables + v_bank).

### 4.3 Version skew (all four cases measured on copies)

| Server | Seed | What happens |
|---|---|---|
| **older** (schema 13, `cd3df8c` importer) | **newer v3** | `seed_row` ignores the unknown `learn_rank` key; the dictionary columns are identical → `inserted 0 updated 0` in 0.32 s; `kv.seed_version` becomes the v3 sha; no warning, no error. Ordering stays by `frq`. The older `wd check db` has no order invariants. Harmless. |
| **newer** (schema 14) | **older v2** | fallback computes every key (14.5 ms) → identical ordering semantics to a v3 import; `rank_computed = N`, `rank_from_seed = 0`, INFO only. |
| **newer**, policy `lo-2` | v3 built by `lo-1` | import keeps the seed's keys (truth); `rank_mismatch = N` → one WARNING + event detail; `wd check db` → `learn_rank_matches_policy: N violation(s)`. Fix = rebuild the seed (or deploy the matching seed). |
| **older code after a rollback** (schema 14 DB, v2 file) | — | its `seed_check` sees `kv.seed_version` (v3 sha) ≠ v2 sha → re-imports the v2 file: `inserted 0 updated 0` in 0.30 s; the `learn_rank` column is untouched (9,618 values stay, unused). |

The seed never deletes rows and never lowers visibility (unchanged); `learn_rank` never influences `is_public`, stage flags or `difficulty`.

---

## 5 Tests

### 5.1 New

* `backend/tests/unit/test_learn_order.py` — the only file allowed to hold literal expectations of the policy:
  `test_rank_input_adapters_agree` (record vs columns for the same word, incl. `sources` split/join and `stage_min` from stages); `test_policy_version_and_order_tail_are_the_documented_literals`; `test_rank_all_equals_rank_for_with_stage_stats` (the contract of §1.2 over the mini seed); `test_dominant_pos_is_the_only_pos_reader` (label-shaped `'v./n.'` and empty `pos` give the content-word branch; first-letter-of-pos is never used — `one`, `answer`, `light` style words); `test_stage_stats_roundtrip_json`; `test_rank_for_row_uses_kv_stats_and_falls_back_to_the_table_when_the_policy_differs`; `test_refresh_rewrites_only_when_the_key_changed`; `test_verify_counts_hand_edits`; `test_summary_block_shape_and_stage_order`; plus the policy's own table-driven cases (frq present / bnc fallback / neither; closed-class vs content; phrase; inherited form; stageless) — these are the lines a policy change edits.
* `backend/tests/unit/test_db_0014.py` (model: `test_db_0013.py`): upgrade a v13 database with seed-like rows → `(14, 'learn_rank')` applied, column NULL for existing rows, `kv.seed_version` gone, event row, table set `== EXPECTED_TABLES`, `v_bank` still there, idempotent second run; fresh path has the column.
* `test_seed.py`: `test_v3_record_rank_is_carried_and_verified` (mini v3 → `rank_from_seed == N`, `rank_computed == 0`, `rank_mismatch == 0`, `kv.learn_order.policy == POLICY_VERSION`, stage stats JSON parses); `test_v2_record_rank_is_computed_by_the_fallback` (the v2 copy → `rank_computed == N`, stored keys equal `rank_all` of the file); `test_carried_rank_that_disagrees_is_kept_and_counted` (edit one record's `learn_rank` in a tmp file → `rank_mismatch == 1`, WARNING with `event="seed_rank_mismatch"`, stored value is the file's); `test_dry_run_reports_rank_only_updates`; `test_seed_import_event_carries_learn_rank_detail`.
* `test_seedbuild_build.py`: `test_every_record_carries_an_integer_learn_rank_and_stats_describe_it` (also stageless records; `stats.learn_order.per_stage[code].n == first_stage[code]`); `test_learn_rank_is_recomputed_not_copied_from_the_previous_seed` (a v3 previous record with a wrong rank comes out corrected).
* `test_seed_diff.py`: `test_section_f_reports_movers_between_two_ranked_files`; `test_section_f_notes_a_rankless_old_file_and_uses_its_frq_order`; `test_missing_learn_rank_on_a_v3_record_fails_the_invariant`; `test_policy_only_rebuild_shows_zero_field_changes` (FIELD_KEYS excludes `learn_rank`).
* `test_diag.py`: `test_check_db_skips_the_order_invariants_until_a_seed_is_imported` (after 0014 on a fresh DB with no import: two `skipped` lines, verdict ok); `test_check_db_counts_rows_without_a_key_and_hand_edited_keys`.
* `test_words_resolve.py`: extend `test_ordinary_ecdict_row_is_public_valid_and_enqueues_nothing` (`:271`) — the inserted row's `learn_rank == learn_order.rank_for(RankInput.from_columns(row), stats_from_kv)`; extend `test_unknown_string_becomes_a_private_provisional_word…` (`:131`) — provisional row has a non-NULL key; new `test_lookup_filling_pos_refreshes_the_key` in `test_lookup_apply.py`.
* `test_docs_contract.py`: `test_docs_quote_the_learning_order_tail` — `learn_order.ORDER_TAIL` (with `w.` stripped the way API.md writes it) appears in API.md §20 and DESIGN.md §6.3 step 4; `POLICY_VERSION` appears in DESIGN §3.2.
* Frontend (only with the optional copy change): none beyond the byte mirror (`npm run check:copy`, `zh.test.ts`).

### 5.2 Existing pinned tests that must change (and the new expectation, in words)

| Test (verified location) | Today | New expectation |
|---|---|---|
| `integration/test_vocab.py::test_vocab_default_is_everything_sorted_by_frequency` `:93-110` | first lemma `"be"` (frq 2), `frq` ascending within the page, page 2 ends with `frq NULL` | rename `…_sorted_by_learning_order`: the two pages' lemma sequence equals the SQL `SELECT lemma FROM words WHERE is_public=1 AND merged_into_word_id IS NULL ORDER BY {ORDER_TAIL}` (import the constant, alias rewritten); the first lemma is whatever the helper ranks first on the mini seed (asserted via `learn_order.rank_all`, never a literal); the `WordBrief` key set is unchanged (`learn_rank` is not exposed). Drop the `frq`-monotonic assertions. |
| `::test_vocab_sort_alpha_and_difficulty` `:163-182` (`sort_key` lambda `:174`) | `(difficulty+1 or stage_min or 6, frq is None, frq, lemma)` | the lambda's tail becomes `(learn_rank is None, learn_rank, lemma)` with `learn_rank` read by SQL for the returned ids (the DTO does not carry it); the `absorption < abandon < absolutely < ought to < bookshelf` chain holds only if the policy keeps it — rewrite as "stage key non-decreasing, within a stage key ordered by the helper". |
| `::test_cet6_new_only_on_the_full_seed` `:233-275` (`@full_seed`) | totals vs `stats.json`, sort performance | add: the first lemma of `GET /api/vocab?stage=xs` equals `stats.json.learn_order.per_stage.xs.first[0]`; the first 8 equal `first`; timing budget unchanged (measured 0.7 ms). |
| `integration/test_screen.py::test_next_order_and_remaining` `:122-139` | `lemmas[:3] == ["absorption","axe","ought to"]` (`:130`), zk `== ["go","person","better"]` (`:136`) | both lists equal the SQL `ORDER BY {_STAGE_DISTANCE}, {ORDER_TAIL}` over the same filter (helper `expected(stages, cur, n)` in the test module); comments stop citing frq numbers. |
| `::test_next_auto_for_a_primary_school_learner_orders_by_stage_distance` `:142-158` (`:150`) | `expected_xs` computed with `ORDER BY (frq IS NULL OR frq = 0), frq, lemma` | the same query with `learn_order.ORDER_TAIL` (alias stripped) — the test already computes rather than pins, so this is a one-line edit. |
| `unit/test_batches.py::test_build_batch_caps_ordering_and_counts` `:104-136` (`:129`) | `screens == ["absolutely", "axis"]` | `screens == first two lemmas of SELECT … WHERE stage_cet4=1 … NOT EXISTS(user_words) ORDER BY {_STAGE_DISTANCE(cur=4)}, {ORDER_TAIL}` on the seeded DB. `::test_build_batch_cold_start_puts_screens_first` `:152-164` pins kinds only — unchanged. |
| `integration/test_words.py` `:86-87` (lookup suggestions) | `frqs == sorted(frqs)` | the suggestion lemmas equal the prefix query ordered by `ORDER_TAIL` (via SQL on the returned ids); if the owner keeps suggestions on `frq`, the line stays. |
| `unit/test_seed.py::test_seed_row_mapping_and_validation` `:497-514` | `SEED_COLUMNS ⊇ STAGE_COLUMNS` | also `"learn_rank" in SEED_COLUMNS`; `seed_row({... "learn_rank": "12"})["learn_rank"] == 12`, absent → None. `::test_changed_record_updates_only_that_row` `:283-295` keeps `(0, 1)` **because the fixture is v3** (carried keys). `::test_second_run_is_a_noop_and_force_changes_nothing` `:245-255` unchanged (0 rewritten, measured). `::test_full_seed_acceptance_numbers` `:623-650` adds: `count(source='seed' AND learn_rank IS NULL) == 0`; per stage `MIN/MAX(learn_rank)` and the median (`ORDER BY learn_rank LIMIT 1 OFFSET n//2`) equal `stats.learn_order.per_stage[s].{key_min,key_max,key_p50}`; `learn_order.verify(conn) == (N, 0)`; `kv.learn_order.policy == stats.learn_order.policy == POLICY_VERSION`. |
| `unit/test_seedbuild_build.py::test_every_record_is_a_valid_v2_record` `:427-445` (`:435 seed_v == 2`) and `::test_stats_are_consistent_with_the_records` `:463-482` (`:477 seed_v == 2`) | v2 | rename to `…_v3_record`; `seed_v == 3`; every record has `isinstance(rec["learn_rank"], int)`; `d["seed_v"] == 3`; `d["learn_order"]["policy"] == POLICY_VERSION`, `sum(per_stage[*].n) == total_words`. |
| `unit/test_seed_diff.py` fixture pair (`:80 test_fixture_pair_counts_matrix_and_invariants`, `:130 rendering stable`) | sections (a)–(e) | the new (f) section exists and is deterministic; invariants list grows by two names (assert the names). |
| `unit/test_diag.py::test_check_db_reports_the_four_invariants_ok_after_a_seed_import` `:49-58`, `::test_wd_check_db_exit_code_follows_the_invariants` `:195-203` (`:199 count == 4`) | four `invariant` lines | six lines after an import (`learn_rank_present`, `learn_rank_matches_policy` both `ok`); the stage-literal test `:182-191` is untouched because `STAGE_INVARIANTS` is untouched. |
| `unit/test_db.py::test_fresh_migration_creates_schema_and_one_bookkeeping_row_per_file` `:42-60` | shipped list | automatic (reads the directory); `EXPECTED_TABLES` unchanged. |
| `integration/test_admin_ops.py:488` prewarm candidates | compared as a **set** | unchanged. |

Everything else that lists words by `frq` in comments only (e.g. `test_screen.py:129, :134-135`) gets its comment rewritten; no behaviour.

---

## 6 Documentation edits by section

| Doc / anchor (verified) | Edit |
|---|---|
| `docs/API.md:169` (endpoint **20** `GET /api/vocab`) | `sort=freq` text: "default `freq`: the **learning order** — `ORDER BY (learn_rank IS NULL), learn_rank, lemma` (`words.learn_rank`, the seed-carried key computed by `wd.learn_order`, DESIGN §3.2; NULL = not ranked, last); `alpha`: `ORDER BY lemma`; `difficulty`: `ORDER BY COALESCE(difficulty + 1, stage_min, 6), (learn_rank IS NULL), learn_rank, lemma`". The query value stays `freq` (wire compatibility; the UI label is a copy question, FRONTEND §8). Endpoint 22 (`/api/lookup`) one clause: "suggestions in learning order". `WordBrief` (§9) unchanged — `learn_rank` is not exposed (note it as "internal; exposing it later is additive"). |
| `docs/DESIGN.md:196` §3.2 heading | "record format **v3** … (v2 files without `learn_rank` import with the key computed by the importer; v1 …)". |
| `DESIGN.md:205` row `pos, collins, oxford, bnc, frq` | note → "`0`/`null` frequency = unknown; **no longer a sort key** — the order is `learn_rank`". New row after `sources[] …`: "| `learn_rank` | `learn_rank` | integer learning-order key (lower = earlier) computed by `wd.learn_order` (`POLICY_VERSION` lo-1) from `pos` (via `dominant_pos`), `frq`, `bnc`, `kind`, `sources`, `stage_min` and the stage's statistics; carried by every v3 record, verified at import (`SeedStats.rank_mismatch`, the seed wins), computed by the importer for v2 records; runtime rows get it from `kv.learn_order.stage_stats`; `NULL` sorts last |". Row `variant_of, seed_v`: "`3`". Paragraph after the token table: `stats.json` list gains `learn_order`; the `@full_seed` gate's invariants gain "`learn_rank` present on every seed row and equal to `wd.learn_order`". |
| `DESIGN.md:363-370` §6.3 step 4 | `ORDER BY stage_distance(w.stage_min, current_stage) ASC, (w.learn_rank IS NULL) ASC, w.learn_rank ASC, w.lemma ASC   # the learning order (DESIGN §3.2 learn_rank), NULL last`; keep the `stage_distance` definition line. |
| `DESIGN.md:32` §0.1 and `:350` §6.2 | unchanged ("recommendation order derives from the user's choice" — still true: the stage distance comes first). |
| `docs/FRONTEND.md:145-147` §5.5 | one sentence: "sort `freq` = the learning order (`learn_rank`), not raw frequency". **Optional copy change** `:254` §8 mirror and `frontend/src/i18n/zh.ts:48`: `sort: { freq: '学习顺序', alpha: '字母', difficulty: '难度' }` (key unchanged; `VocabPage.test.tsx:112` reads the key, so no test edit; `npm run check:copy` needs the two lines byte-identical). Recommended as a **separate commit** so the backend fix ships by restart alone; it is the only change that needs a frontend snapshot. |
| `docs/CLAUDE_INTEGRATION.md:303` | "…candidate words of the stage (public, valid, `content_state IN ('none','failed')`, not yet enqueued, **in learning order — `words.learn_rank`, DESIGN §3.2**; …)". |
| `docs/WORD_LIBRARY_CURATION.md:150` (选词规则 核验 C10) | "…按阶段距离 → **学习顺序 `learn_rank`（为空排最后）** → 字母序。阶段距离按 `stage_min` 计算，一条有阶段标志但 `stage_min` 为空的手工插入行仍会排在每个用户筛词的**第一位**；`learn_rank` 为空的行在同一阶段距离组内排**最后**。所以管理员在服务端插入词条时必须同时给 `stage_*`、`stage_min` 和 `learn_rank`（用 `wd.learn_order.rank_for_row` 算，或留空等下一次种子导入——种子导入不会给非种子行赋值）。" (The existing warning stays true; the new column improves on it: a forgotten key sorts last, not first.) §1.6 LRU note: add "a seed import that changes `learn_rank` moves `updated_at` of every affected row and therefore empties the card LRU once". |
| `docs/releases/2026-11-k12-stages.md:212` §9 末 | replace the 「邀请小学生之前必须处理」 sentence by a pointer: "已处理：学习顺序改为种子携带的 `learn_rank`（迁移 0014，种子 v3，`docs/releases/2026-11-learn-order.md`）". |
| New `docs/releases/2026-11-learn-order.md` | the Mac/Lighthouse steps of §7 below, the expected `--dry-run` line (`update 9618 … rank-only updates 9618`), the six `wd check db` lines, the rollback. |
| `docs/DEPLOY.md:361` and `docs/ops.md:117-120` (which files are additive) | add `0014_learn_rank.sql` to the additive list next to 0012. |
| `docs/analysis/…/design/PLAN.md:749` §9.2 #5 | one line "resolved by `learn_rank` (seed-carried)". |
| `data/seed/ATTRIBUTION.md` | regenerated (optional footer sentence of §2.3). |

---

## 7 Deployment and rollback

### 7.1 Mac (launchd, data dir `D=/Users/sqin/word-dance-data`, agent `com.word-dance.server`)

A **restart is enough**; no stop-first runbook, no frontend snapshot (unless the optional label commit is included — then build `frontend-releases/<sha>.new` and swap the symlink first, the recipe of the K-12 release note step 1/5).

0. Rehearse (no downtime, private dir `$M`): `VACUUM INTO '$M/word-dance.db'` from the live file; `.venv/bin/python -I scripts/rehearse_migration.py $M/word-dance.db` → exit 0 with the §4.2 transcript (two `[skip] … seed import pending`); `WD_DATA_DIR=$M .venv/bin/wd import-seed --dry-run --report $M/dry.json` → `insert 0 / update 9618 / unchanged 0; orphans 0; … rank-only updates 9618; ranks: 9618 carried / 0 computed, 0 disagree with lo-1`; `WD_DATA_DIR=$M .venv/bin/wd import-seed` (≈ 0.4 s); `WD_FULL_SEED_DB=$M/word-dance.db .venv/bin/python -m pytest -q backend/tests -m full_seed`; `WD_DATA_DIR=$M .venv/bin/wd check db` → six invariants ok.
1. Optional: `.venv/bin/wd backup --keep-daily 14 --keep-weekly 8` (the runner also writes `backups/pre-migrate-13-to-14.db.gz`).
2. `git checkout <commit>` (the running process keeps its loaded code).
3. `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`. Startup: `applied migration 0014_learn_rank` (7 ms) → `seed version changed; importing` → `seed imported: 9618 records, 0 inserted, 9618 updated, 14196 forms …` (≈ 0.4 s) → ready. Downtime = process restart (seconds). The 03:30 backup agent need not be touched.
4. Verify: `curl --noproxy '*' http://127.0.0.1:8000/api/health`; `~/Library/Logs/word-dance/word-dance.log` has the three lines above and no `seed_rank_mismatch` / `seed_import_failed`; `WD_DATA_DIR=$D .venv/bin/wd check db` → six `ok`; `GET /api/vocab?stage=xs` first items are no longer `the be and of …`; `GET /api/screen/next?stage=xs&count=5` likewise; the admin system card shows the new `seed_version` prefix (= `stats.json.content_sha256`).

### 7.2 Lighthouse (systemd, `deploy/install.sh`)

Rehearse on the box the same way (`rehearse_migration.py` is portable; SQLite ≥ 3.26). Then `git pull && deploy/install.sh`: it stops the unit, publishes the SPA snapshot, `wd migrate` (0014, `install.sh:140`), `wd import-seed` (`:141`, fills the ranks under the new code), starts the unit. `--no-restart` is **technically safe** for 0014 (additive, 0012-class) but pointless: the old process would keep the `frq` order until restarted. A database copied from the Mac after the Mac deploy needs nothing (same commit, same content sha256).

### 7.3 Rollback

* **Code only** (the normal case): `git checkout cd3df8c && launchctl kickstart -k …` (Lighthouse: `git checkout … && deploy/install.sh`). The old code ignores the column; its `seed_check` re-imports the v2 seed (0 rows changed, `kv.seed_version` back — measured) and orders by `frq`. If the label commit shipped, swap the `frontend` symlink back to the previous snapshot. No data loss.
* **Database too** (only if the column itself must go): `launchctl bootout …; wd restore $D/backups/pre-migrate-13-to-14.db.gz --yes; git checkout cd3df8c; launchctl bootstrap …` — loses learning records made after the snapshot, so prefer the code-only path.
* **Seed only** (keep code and schema, go back to `frq`-like behaviour): not possible without code — `learn_rank` is always the sort key on the new code. Ship the previous seed instead and the fallback computes keys for it (the order is then the new policy over the old lists, which is probably not what anyone wants); in practice roll the code back.

---

## 8 Risks, blast radius, size

### 8.1 Risks and mitigations

1. **Every row is rewritten at the first v3 import and at every policy rebuild** (`updated_at` moves, card LRU emptied, `--dry-run` says `update 9618`). Mitigated by the `rank-only updates` clause and the release note; cost 0.4 s; browser caches unaffected.
2. **Policy literals in tests.** Only `test_learn_order.py` holds them; every other test computes expectations through `learn_order` / `ORDER_TAIL`. A policy change therefore touches one test file plus the regenerated fixture/seed.
3. **Fallback ripple.** On a v2 file the computed keys of all words in a stage depend on that stage's statistics; the mini-seed fixture is therefore shipped as v3 (§2.11) and the fallback is tested on a dedicated v2 copy. On production this only matters while an older v2 seed meets a newer server — identical to what the builder would have produced.
4. **Mixed versions.** Older server + newer seed is harmless (§4.3); newer policy + older seed is loud (`rank_mismatch`, `wd check db`). Rule: policy change = seed rebuild in the same commit; CI could assert `stats.json.learn_order.policy == learn_order.POLICY_VERSION` (a trivial unit test over the committed `stats.json`; add it to `test_seedbuild_build.py`).
5. **`kind` drift.** The builder derives `kind` with `services.words.derive_kind`; lookup may later set another `kind` (`ITEM_KINDS`) → the `refresh` hook keeps stored = computed. Without the hook the invariant would report it.
6. **Stage statistics frozen at import** for runtime rows: a provisional word or an ECDICT hit uses the last import's statistics, exactly what the seed was built with — intended. The 'none' group (课标外, 238 words) is their reference when they carry no stage.
7. **Seed size** +41 KB gz, +194 KB jsonl: negligible; `pack_seed.sh` round trip unchanged.
8. **Index temptation.** Measured useless (temp B-tree in every plan); adding one later is a one-line additive migration if a query shape ever changes.
9. **`ORDER_TAIL` assumes alias `w`** like `_STAGE_DISTANCE`; a future site without the alias must rewrite it (the docs-contract test pins the literal, so a drift is visible).
10. **Lookup suggestions following the learning order** may surprise power users who type a prefix expecting the commonest word first; the fallback is to leave `words.py:106` on `frq` (one site, one doc line, one test line).
11. **Optional copy change** ('词频' → '学习顺序') is the only frontend touch; shipping it separately keeps the backend deploy restart-only.

### 8.2 Blast radius

Backend modules touched: 1 new (`learn_order.py`), 1 migration, 2 seed-pipeline modules (`seed.py`, `seedbuild/build.py`), 1 report module (`seedbuild/diff.py`), 5 query sites in 5 files, 4 runtime writer sites in 3 files, `diag.py`, `scripts/rehearse_migration.py`. No change to `schemas.py`, `types.ts`, `check_contract.py`, `SCHEMA.sql`, `Makefile`, `pack_seed.sh`, `install.sh`, launchd plist, `.env`. Data: `vocab.jsonl.gz`, `stats.json`, `DIFF.md`, `ATTRIBUTION.md` regenerated; `tests/fixtures/mini_seed.jsonl` regenerated (+ one v2 copy). Frontend: 0 files (optional 1 line + its doc mirror).

### 8.3 Size estimate

| Area | Files | Lines (added/changed, excluding regenerated data) |
|---|---|---|
| `backend/wd/learn_order.py` | 1 | ~180 |
| `migrations/0014_learn_rank.sql` | 1 | ~18 |
| `seed.py`, `seedbuild/build.py`, `seedbuild/diff.py` | 3 | ~45 + ~40 + ~80 |
| five ORDER BY sites + lookup suggestions | 5 | ~15 |
| runtime hooks (`services/words.py`, `ai/lookup.py`, `ai/consolidate.py`, `services/suggestions.py`) | 4 | ~20 |
| `diag.py`, `scripts/rehearse_migration.py` | 2 | ~45 + ~45 |
| tests: new (`test_learn_order.py`, `test_db_0014.py`) + edits in 10 files | 12 | ~140 + ~60 + ~160 |
| fixtures + fixture script | 3 | ~20 (+ 62 regenerated lines) |
| docs (API, DESIGN, FRONTEND, CLAUDE_INTEGRATION, WORD_LIBRARY_CURATION, DEPLOY, ops, release note old + new, PLAN) | 10 | ~120 |
| **Total** | **≈ 40 files (≈ 30 code/test, ≈ 10 docs)** | **≈ 1,000 lines** + regenerated seed/stats/DIFF/fixture |

Effort: 2–3 focused days including the rehearsal; the policy itself is extra.

---

## 9 Extensibility: a future textbook / grade order field

The mechanism is a template, not a one-off:

* **Second key, same chain.** A textbook order (人教 PEP / 牛津上海 by grade·unit) becomes another seed-carried integer, e.g. `textbook_rank` (or several, one per series), added by an additive migration 0015 of the 0014 shape, produced by the builder from a new `data/lists/` file (`manifest` list `format: tsv`, `policy: "order"`, columns `word, series, grade, unit, position`; the manifest `format` bumps to 3), verified/filled by the importer, summarised in `stats.json.learn_order.keys[...]`, diffed in section (f) per key, checked by the same two invariants per key (`<key>_present`, `<key>_matches_policy`). `learn_order` grows a small registry `KEYS = {"learn_rank": <policy>, "textbook_rank": <table lookup>}` and `order_tail(key)` replaces the single constant; the five sites already import the tail from one place, so switching or combining keys is a one-line change there.
* **Per-user choice.** A `user_settings.order_key` (or a stages-like setting from onboarding: 「按教材顺序」/「按学习顺序」) selects the tail at request time: `ORDER BY {_STAGE_DISTANCE}, {order_tail(settings.order_key)}`, with `COALESCE(w.textbook_rank, w.learn_rank)` when a word is outside the chosen textbook. Stage distance stays first, so the K-12 stage model and the textbook order compose.
* **Cross-row statistics generalise.** `stage_stats` becomes `StageStats` per key; a textbook table needs none (pure lookup), which the contract of §1.2 allows (statistics may be empty).
* **What does not change.** The seed remains the truth; `wd import-seed --dry-run`, `DIFF.md`, `full_seed`, `wd check db`, `rehearse_migration.py` already cover a new key once it is registered; the API can expose any key additively in `WordBrief` when a UI needs to show it.

---

## Appendix A — measurements (live-size copies; this Mac)

| Step | Result |
|---|---|
| Live copy facts (`probe_db.py`) | schema 13 (1,8,9,10,11,12,13); 9,618 words, all `source='seed'`; `kv.seed_version 24f3b949…`; indexes `ux_words_lemma, ix_words_frq, ix_words_stage_min(stage_min,frq), ix_words_content, ix_words_created_by, ix_words_public`; 2,300 pages × 4 KB; 16 distinct `updated_at`; 77 user_words, 7 batches, 79 contents, 47 images |
| Builder (`sim_seed_carried.py` §1) | read 9,618 records 44.8 ms; `rank_all` 14.5 ms; deterministic; jsonl +194,090 B; gz 1,342,623 → 1,383,800 B; content sha256 changes |
| 0014 via `wd.db.run_migrations` | 7.3 ms; column `INTEGER NULL`; all NULL; kv cleared; event row; deltas kv/schema_migrations/system_events only; integrity ok; v_bank intact; idempotent; page_count unchanged |
| Import v3 (patched importer) | 392.7 ms, 9,618 updated, 14,196 forms; `updated_at` 16 → 1 distinct; card LRU key miss demonstrated; re-import 6.0 ms up_to_date; `--force` 298 ms / 0 rows; verification 0 mismatches (72 ms incl. file re-read); v2 fallback 0 rows rewritten; dry-run 0/9,618 |
| ORDER BY sites | all within ±0.05 ms of today (0.55–1.65 ms); index never used |
| Invariants | present 0.5–0.6 ms; matches_policy 19.1 ms; hand edit of 2 rows → 2 violations |
| Runtime insert | `rank_for` 0.0 ms; inserted row carries a key |
| Old server (schema 13, old importer) reads v3 | 0/0 in 320 ms, kv set, no error |
| Old code after rollback (schema 14 DB, v2 file) | 0/0 in 299 ms; column untouched |
| Earlier `time_rank.py` | rank 10.6 ms; forced import 0.32 s; UPDATE updated_at ×9,618 12 ms; ADD COLUMN + index + fill 24 ms |

## Appendix B — simulation scripts (`…/scratchpad/order/sim-seed-carried/`, run with `/Users/sqin/word-dance/.venv/bin/python -I`)

* `probe_db.py` (reused) — schema/plan/timing probe of the read-only live copy plus an in-memory ADD COLUMN/UPDATE rehearsal.
* `time_rank.py` (reused) — rank computation, forced re-import and full-table UPDATE timings on a private copy (deletes it afterwards).
* `sim_seed_carried.py` (new) — the whole chain of this document; writes `vocab-v3.jsonl(.gz)`, `vocab-v2-fallback-ranked.jsonl`, `mig0014/0014_learn_rank.sql`, `sim_output.txt`; copies are deleted at the end. The importer is patched **in process only**; the repository and the live data directory are never written.
