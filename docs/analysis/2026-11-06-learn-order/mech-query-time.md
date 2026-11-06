# Mechanism "query-time": the learning order computed inside the query, stored nowhere

Angle of this document: **no schema change, no seed change** — the 词库 / 筛词 / 每日推荐词 order is produced at query time from the
columns the live database already has (`lemma pos frq bnc kind sources stage_min`) plus per-stage statistics derived from
the same table. The *policy* (which word comes first) is deliberately left open; the stand-in rule of FACTS §2 is used
only to make the measurements realistic. Everything measured below ran on the read-only live copy
(`…/scratchpad/deploy/precheck/word-dance.db`, `mode=ro&immutable=1`, sqlite 3.54.1, Python 3.12.16) with
`sim-qt/bench_query_time.py` (pass 1, output `bench_output.txt`) and `sim-qt/bench_query_time_v2.py` (pass 2, output
`bench_output_v2.txt`) — both scripts are in this directory and re-run with `.venv/bin/python -I`.

Terms: 小学 = xs (stage index 1), 初中 = zk (2), 筛词 = `GET /api/screen/next` + onboarding, 推荐词 = the `kind='screen'`
rows of a daily batch, 词库 = `GET /api/vocab`, 预生成 = admin prewarm.

---

## 0 Decision in one paragraph

Implement the order as **one application-defined SQLite function** (`conn.create_function`, option 2), registered in the
single place every application connection is born — `wd.db.connect` (backend/wd/db.py:88–101) — and **pure**: its ten
arguments are the seven row columns and the three per-stage quantiles, so the function reads no global state. The
quantiles are computed on the Python side (2.5 ms, cached per process, re-derived when `kv.seed_version`, `COUNT(*)` or
`MAX(id)` of `words` change or after 10 minutes) and reach the statement as 18 named parameters through three
`CASE w.stage_min WHEN 1 THEN :p50_1 … ELSE :p50_0 END` expressions rendered into a constant ORDER BY fragment.
Option 1 (SQL-only expressions) was measured and rejected: re-implementing `dominant_pos` in SQL violates the single-reader
rule D-images-24 and silently diverges on malformed `pos`; a SQL boolean key is NULL for the 724 pos-less rows and NULL
sorts *first* in SQLite (the earlier B2 run put `mrs. mr. ms. email ice cream …` at the top of 小学 for exactly this reason);
cross-row statistics in SQL cost 6.4 ms per statement (window CTE) against 2.5 ms once per cache refresh; SQLite has no hash
function, so a "spread" of frequency-less words needs a weak polynomial that is NULL for two-letter lemmas; and the SQL
variant depends on `exp()`/`ln()`, compile-time options whose presence on the Lighthouse SQLite is unknown. The UDF adds
0.3–5.3 ms per request (0.49 µs per candidate row), the query plans are byte-identical to today's, and the SQL order equals
`sorted()` with the same Python key on all 9,618 live rows (pass 2 §8). Nothing is stored; rollback is a restart on the
previous commit.

---

## 1 Architecture and data flow

### 1.1 Where the order is computed and stored

| Component | Lives in | Computed when | Stored |
|---|---|---|---|
| Policy (pure functions `closed_class`, `effective_frq`, `order_key`) | new `backend/wd/services/order.py` | per candidate row, inside SQLite's sort, by the UDF `wd_order_key` | nowhere |
| Registration of the UDF | `wd.db.connect` (db.py:88) → `order.register(conn)` after the PRAGMA loop (db.py:99–100) | every connection (≈ 1 µs, pass 2 §3) | — |
| Per-stage statistics (`p10 p50 p90` of `frq` among the stage's public, unmerged words that have one; the 课标外 group is `stage_min IS NULL`) | `order.stage_stats(conn)` | first use per process, then re-derived when the cache key changes or after 600 s (2.47 ms, pass 2 §2) | process memory only (6 triples) |
| ORDER BY fragment | `order.order_by(alias)` — a constant string | import time | — |
| Statistics → statement | `order.stats_params(conn)` → `{"p10_0" … "p90_5"}` merged into the site's parameter dict | per request (3 probes ≈ 0.003 ms) | — |

Data flow for one `GET /api/vocab?stage=xs` request:

```
deps.get_db ─ db.connect(path) ─ PRAGMAs ─ order.register(conn)           # wd_order_key now exists on this connection
routers.vocab.vocab() ─ where/params ─ params |= order.stats_params(conn)   # probes kv.seed_version, COUNT(*), MAX(id) → cache hit
   SELECT w.*, uw.state … ORDER BY <order.order_by('w')> LIMIT :limit OFFSET :offset
      SQLite: for each candidate row → CASE w.stage_min → :p10_k, :p50_k, :p90_k
              → wd_order_key(lemma, pos, frq, bnc, kind, sources, stage_min, p10, p50, p90)   (Python, 0.49 µs)
              → TEMP B-TREE sort on (key, lemma) → LIMIT
```

The same fragment, with `_STAGE_DISTANCE` in front, orders 筛词 (`screen.screen_next`), the 推荐词 selection
(`batches.select_words`) and 加练 refills (`batches.add_more`); 预生成 (`prewarm.candidates`) uses it without the stage
distance. Lookup suggestions (`routers/words.py:106`) stay on raw frequency (see §2.3).

### 1.2 Why a UDF and not SQL expressions (measured)

| Criterion | (1) SQL-only (`B1`/`B2` of pass 1) | (2) UDF `wd_order_key` (`C4` of pass 2) |
|---|---|---|
| Dominant pos | `json_each('{"n":4,"v":96}') ORDER BY value DESC, id LIMIT 1` — 0 mismatches with `dominant_pos` on today's 9,618 rows, but a second parser (D-images-24 forbids it), needs JSON1, accepts `x1:50` that `dominant_pos` rejects | calls `wd.images.style.dominant_pos` itself |
| Boolean terms | NULL for 724 rows (`pos` empty, not AUX/inherit) → sorted **first**; every term needs `COALESCE(…, 0)`/`IS TRUE` | Python bool, never NULL |
| Cross-row statistics | window CTE 6.43 ms **per statement**, `MATERIALIZE ss` + automatic index in every plan | Python 2.47 ms per cache refresh, 0.003 ms per request |
| Spread of frequency-less words | no hash in SQLite; the polynomial over 3 letters is NULL for 2-letter lemmas (11 of 758) | `zlib.crc32(lemma)` — stable across processes/machines; KS distance 0.038 on the 381 zk phrases (5 % bound 0.070) |
| Portability | `exp()`/`ln()` are `SQLITE_ENABLE_MATH_FUNCTIONS` (present in the Mac build, unknown on Lighthouse) | none beyond `sqlite3.create_function(deterministic=)` (Python ≥ 3.8) |
| Cost at the sites | +6.4 … +17.7 ms | +0.02 … +5.3 ms |
| Visible to the `sqlite3` CLI | yes | no (`no such function: wd_order_key`) — mitigated by `wd check db` and an optional `wd order` preview (§2.2) |

### 1.3 Why the pure variant C4 and not the memo variant C3

Pass 1's C3 (the UDF reads a process-level dict) and pass 2's C4 (quantiles arrive as parameters) cost the same
(vocab all p1 5.59 vs 6.01 ms; 筛词 2.28 vs 2.32 ms). C4 wins on correctness grounds: `deterministic=True` is then true, no
Python global is read from inside SQLite's callback, the function is unit-testable without a database, the per-database
keying problem of a memo (pytest runs dozens of databases in one process) moves to the Python side where the connection is
known, and the SQL text stays constant (sqlite3's statement cache keys on text; only the bound values change). The pure
function is also exactly the reference the differential tests sort with (§5).

### 1.4 The per-stage fallback and the spread without stored state

```
effective_frq(lemma, frq, bnc, p10, p50, p90):
    frq > 0           → frq                                   # COCA rank, as today
    elif bnc > 0      → bnc                                   # same scale (FACTS §2: covers 19/30 xs, 50/449 zk, 20/26 gk …)
    elif p50 is None  → UNKNOWN_FRQ (1e8)                     # no statistics (empty stage, pre-import database): sort last, as today
    elif p90 <= p10   → p50                                   # degenerate stage (tiny test seeds): one constant
    else              → exp(ln p10 + u · (ln p90 − ln p10)),  u = crc32(lemma) / 2^32   # log-uniform inside the stage's middle 80 %
```

The statistics are a pure function of the `words` table, the hash is a pure function of the lemma — nothing is written, two
processes (server and `wd order`) and two machines compute the same order for the same database. The stand-in policy then
adds `CLOSED_CLASS_OFFSET = 1e7` when `closed_class()` holds, which puts function words after every content word of the
same stage distance; a policy that wants the constant-`p50` block instead of the spread flips one branch. Measured effect
on the live copy (pass 2 §9): the 30 frequency-less 小学 words land at positions 3–600 instead of 571–600 (`monday` 353,
`january` 261, `colour` 209, `schoolbag` 348), the 381 上海词组 of 初中 spread from position 124 to 1707 (29 in the first
200, median 849) instead of forming a block at 1501–1949. `hash()` must never be used (salted per process); the test pins
`crc32('monday') == 3755093257`, `crc32('ice cream') == 2295515455`, `crc32('schoolbag') == 3192515231`,
`crc32('p.e.') == 3170141767`.

---

## 2 File-by-file change list

### 2.1 New module `backend/wd/services/order.py` (≈ 160 lines with docstrings)

```python
"""Learning order (推荐顺序) — the one place that says which word a learner meets next (DESIGN §6.3 step 4, API.md 20/31,
CLAUDE_INTEGRATION §6.1 prewarm, WORD_LIBRARY_CURATION §1.6).

The order is computed at query time by the SQLite application-defined function ``wd_order_key`` (:func:`order_key`),
registered on every connection by :func:`register` from ``wd.db.connect``; nothing is stored. Its inputs are the row's
``lemma pos frq bnc kind sources stage_min`` and the stage's frequency quantiles, which :func:`stage_stats` derives from
``words`` and :func:`stats_params` binds as ``:p10_<idx> :p50_<idx> :p90_<idx>`` (``<idx>`` = ``schemas.STAGE_INDEX``
value, ``0`` for 课标外). :func:`order_by` renders the ORDER BY fragment every site uses; :func:`sort_key` is the Python
reference the tests sort with. The function is TOTAL: it never raises and never returns NULL (a raising UDF fails the whole
statement, a NULL key sorts first), so every input is coerced defensively.

Policy inputs are read exactly as elsewhere: the dominant part of speech through :func:`wd.images.style.dominant_pos`
(D-images-24, FUNCTION_POS = prep conj det pron art int inf — adverbs are content), provenance through the space-joined
``sources`` tokens (``inherit:``), kind through ``words.kind``. The spread of frequency-less words is ``zlib.crc32`` based —
never the salted builtin ``hash()``.
"""

FUNCTION_NAME = "wd_order_key"
ORDER_INPUT_COLUMNS: tuple[str, ...] = ("lemma", "pos", "frq", "bnc", "kind", "sources", "stage_min")
STATS_NAMES: tuple[str, ...] = ("p10", "p50", "p90")
UNKNOWN_FRQ = 100_000_000.0          # no frequency, no statistics: after everything, as today
CLOSED_CLASS_OFFSET = 10_000_000.0   # stand-in policy: function words after every content word (same stage distance)
STATS_TTL_S = 600.0
AUX: frozenset[str] = frozenset("be am is are was were been being do does did done have has had can could will would shall should may might must ought".split())

@dataclass(frozen=True)
class StageStats:
    """``p10 p50 p90`` of ``frq`` among the public, unmerged words of one ``stage_min`` group that have ``frq > 0``
    (positions ``(n+9)//10``, ``(n+1)//2``, ``n*9//10``, 1-based); ``None`` fields when the group has no such word."""
    p10: int | None
    p50: int | None
    p90: int | None

def hash01(lemma: str) -> float:
    """``crc32(lemma) / 2**32`` in ``[0, 1)`` — deterministic across processes and machines (never ``hash()``)."""

def closed_class(lemma: str, pos: str | None, sources: str | None) -> bool:
    """Stand-in policy gate: ``dominant_pos(pos) in FUNCTION_POS`` or ``lemma in AUX`` or an ``inherit:`` provenance token."""

def effective_frq(lemma: str, frq: Any, bnc: Any, stats: StageStats | None) -> float:
    """Section 1.4: ``frq`` → ``bnc`` → log-uniform spread inside ``[p10, p90]`` → ``p50`` → :data:`UNKNOWN_FRQ`."""

def order_key(lemma, pos, frq, bnc, kind, sources, stage_min, p10, p50, p90) -> float:
    """The body of ``wd_order_key`` — a total function of its ten arguments (every input coerced; a failure inside the policy
    returns :data:`UNKNOWN_FRQ` and logs once per process instead of raising)."""

def sort_key(row: Mapping[str, Any], stats: Mapping[int | None, StageStats]) -> tuple[float, str]:
    """``(order_key(...), lemma)`` for a ``words`` row dict — the Python reference order (tests, ``wd order``, diag)."""

def register(conn: sqlite3.Connection) -> None:
    """``conn.create_function(FUNCTION_NAME, 10, order_key, deterministic=True)`` — called by ``wd.db.connect`` for every
    connection; registering twice is harmless (SQLite replaces the definition)."""

def order_by(alias: str = "w") -> str:
    """The ORDER BY fragment (without the keyword): ``wd_order_key(<alias>.lemma, …, <alias>.stage_min, CASE … END ×3), <alias>.lemma``.
    The CASE arms are rendered from ``schemas.STAGE_INDEX`` so a new stage flows through (PLAN R-1); ``ELSE :pXX_0`` is 课标外."""

def compute_stage_stats(conn: sqlite3.Connection) -> dict[int | None, StageStats]:
    """One fetch of ``(stage_min, frq)`` over the public, unmerged words with ``frq > 0`` and the quantiles per group (≈ 2.5 ms)."""

def stage_stats(conn: sqlite3.Connection) -> dict[int | None, StageStats]:
    """Process-level cache of :func:`compute_stage_stats`, keyed by ``(database file, kv.seed_version, COUNT(*) words, MAX(id) words)``
    (three probes ≈ 0.003 ms) and refreshed at the latest after :data:`STATS_TTL_S`; guarded by a lock (worker threads share it)."""

def stats_params(conn: sqlite3.Connection) -> dict[str, int | None]:
    """``{"p10_0": …, "p10_1": …, …, "p90_5": …}`` for the current statistics — merge into the statement's named parameters
    (sqlite3 ignores names the statement does not use, so the same dict may feed the sibling COUNT query)."""

def invalidate_stats() -> None:
    """Drop the cache (called by ``seed.import_seed`` after its commit and by tests)."""
```

Implementation notes verified in the measurements: `order_key` must coerce `frq`/`bnc` with `int()` under `try` (rows written
by future tools may store text); the database-file key for the cache comes from `PRAGMA database_list` (row 0, column 2);
`compute_stage_stats` uses the single-fetch form (2.47 ms) — the window CTE (6.43 ms) and the per-stage OFFSET probes
(3.43 ms) give identical numbers but cost more (pass 2 §2). The six live triples today:
xs (64, 721, 4978) · zk (413, 1622, 5957) · gk (1163, 2865, 6958) · cet4 (2505, 5267, 11417) · cet6 (4244, 8685, 18056) ·
课标外 (4798, 12444, 23679).

Optional (recommended, ≈ 40 lines): `register_cli(sub)` in the same module adding **`wd order [--stage xs|zk|gk|cet4|cet6|all]
[--limit 40] [--user ID]`** that prints `position lemma key closed frq bnc eff` using the same fragment on a `db.connect`
connection — the operator's replacement for the `sqlite3` CLI, which cannot evaluate the key. Needs `"wd.services.order"` in
`cli.CLI_MODULES` (backend/wd/cli.py:31–42) and `COMMAND_OWNERS` (:45–56), plus the DEPLOY §9 CLI reference row.

### 2.2 Hook: `backend/wd/db.py`

* `connect()` (db.py:88–101): after the PRAGMA loop (:99–100) and before `return conn` (:101):

  ```python
      from .services import order  # late import: services import this module (precedent: backup_pre_hook, db.py:252–261)

      order.register(conn)
  ```
  Module docstring (db.py:1–25) gains one bullet: "`connect` also registers the application-defined function `wd_order_key`
  (services/order.py); a connection opened any other way (the `sqlite3` CLI, `backup.py`'s read-only verifier) cannot run the
  ordering queries". Cost per connection ≈ 1 µs (pass 2 §3: 0.029 → 0.030 ms open+register).

* Verified: every connection that runs an ordering query goes through `db.connect` — `deps.get_db` (deps.py:67–74), the
  worker/scheduler `connect()` closures (main.py:393–394, :434–435; jobs/scheduler.py:529–530; jobs/worker.py:376, :387),
  `cli.py:90`, `diag.py:87/:240/:305`, `seed.py:567`, `services/batches.py:1066` (`build-batch` CLI), `images/handler.py`,
  `ai/consolidate.py`, `ai/probe.py`, `security.py:713`, `routers/health.py:29`, `routers/admin_ops.py:270`,
  `scripts/rehearse_migration.py:307/:335`, `tests/conftest.py:145/:159`. The direct `sqlite3.connect` calls
  (`backup.py:100` read-only verifier, `backup.py:359` checkpoint, `services/ecdict.py:212` and `seedbuild/build.py:496/:503`
  ECDICT, `scripts/eval_provider.py:310`) never order `words` rows.

### 2.3 The five sites (exact fragments; `F = order.order_by("w")`)

Rendered `F` (477 characters; the CASE arms come from `schemas.STAGE_INDEX`):

```sql
wd_order_key(w.lemma, w.pos, w.frq, w.bnc, w.kind, w.sources, w.stage_min,
  CASE w.stage_min WHEN 1 THEN :p10_1 WHEN 2 THEN :p10_2 WHEN 3 THEN :p10_3 WHEN 4 THEN :p10_4 WHEN 5 THEN :p10_5 ELSE :p10_0 END,
  CASE w.stage_min WHEN 1 THEN :p50_1 WHEN 2 THEN :p50_2 WHEN 3 THEN :p50_3 WHEN 4 THEN :p50_4 WHEN 5 THEN :p50_5 ELSE :p50_0 END,
  CASE w.stage_min WHEN 1 THEN :p90_1 WHEN 2 THEN :p90_2 WHEN 3 THEN :p90_3 WHEN 4 THEN :p90_4 WHEN 5 THEN :p90_5 ELSE :p90_0 END), w.lemma
```

| # | Site (verified line) | Today | After | Parameter change |
|---|---|---|---|---|
| 1 | 词库 `backend/wd/routers/vocab.py:76` `_ORDER["freq"]` | `(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma` | `F` | `vocab()` :118–121 binds `{**params, **order.stats_params(conn), "limit": …, "offset": …}`; the COUNT at :117 may take the same dict (extra names are ignored — verified) |
| 1b | 词库 `vocab.py:81` `_ORDER["difficulty"]` | `COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma` | `COALESCE(w.difficulty + 1, w.stage_min, 6), F` | same dict; `alpha` (:77) unchanged |
| 2 | 筛词 `backend/wd/services/screen.py:65` | `ORDER BY {_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit` | `ORDER BY {_STAGE_DISTANCE}, {F} LIMIT :limit` | `params` (:62) gains `**order.stats_params(conn)`; the COUNT at :63 is unaffected |
| 3 | 推荐词 `backend/wd/services/batches.py:61` `_SCREEN_ORDER` | `f"{_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` | `f"{_STAGE_DISTANCE}, {F}"` | `select_words` dict at :272 and `add_more` dict at :698 gain `**order.stats_params(conn)`; both queries (:271, :697) keep `_SCREEN_ORDER` |
| 4 | 预生成 `backend/wd/ai/prewarm.py:52` | `ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT ?` | `ORDER BY {F} LIMIT :limit` | the positional tuple at :53 becomes `{"limit": max(0, int(limit)), **order.stats_params(conn)}` (named and positional placeholders cannot be mixed in one sqlite3 call) |
| 5 | lookup suggestions `backend/wd/routers/words.py:106` | `ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit` | **unchanged** (recommendation) | — |

Recommendation for site 5: do **not** follow. Suggestions complete a string the user is typing; "most frequent word with this
prefix" is the right ranking for that, and a learning order would push `the` below `theatre` for the prefix `th`. The
integration test `tests/integration/test_words.py:86–87` pins ascending `frq` there and stays. If the owner wants one order
everywhere, it is the same one-line edit (`ORDER BY {F} LIMIT :limit`, `params |= order.stats_params(conn)`), costs 0.02 ms
(pass 2 §7, 5 rows) and flips that one test to the differential form of §5.

Site 4 should follow: 预生成 exists to have content ready for the words learners meet first, which is this order by
definition (the admin test `tests/integration/test_admin_ops.py:488` compares candidate *sets*, so it does not change).

`_STAGE_DISTANCE` exists twice (screen.py:34–36, batches.py:60); moving it to `order.STAGE_DISTANCE` is a cheap
de-duplication while both lines are being touched (optional, 4 lines).

### 2.4 No migration

There is no `0014_*.sql`: no column, index, view or trigger. The function must **never** appear in a schema object (an index
or generated column on `wd_order_key` would make every INSERT from a connection without the registration — `sqlite3` CLI,
`wd restore`'s verifier — fail with `no such function`, and `PRAGMA integrity_check` from such a tool would report the index
as corrupt). `docs/SCHEMA.sql` stays byte-identical to 0001, `scripts/rehearse_migration.py`'s `EXPECTED_TABLE_COUNT = 25`
and `check_empty_database` are untouched.

### 2.5 Seed importer `backend/wd/seed.py`

One line after the import transaction (`with db.maybe_tx(conn):` seed.py:469–503, `kv.seed_version` written at :477):
`order.invalidate_stats()` once the block has committed — belt and braces; the cache key (`kv.seed_version`) would catch it
on the next request anyway.

### 2.6 Diagnostics `backend/wd/diag.py` (details in §4)

New `_order_line(conn) -> list[tuple[str, bool]]` next to `_seed_version_line` (:129–156), called from `check_db` after
:105–107 under the same `version >= STAGE_INVARIANTS_FROM_VERSION` guard; `collect_stats` (:270–295) unchanged.

### 2.7 Frontend (copy only, optional)

The API value `sort=freq` keeps its name (no `VocabSort` union change at `frontend/src/api/endpoints.ts:133` ↔
`schemas.VocabQuery.sort` at `backend/wd/schemas.py:503`, so `scripts/check_contract.py` and API.md §9 are untouched). What
the owner must decide is the label: `frontend/src/i18n/zh.ts:48` `sort: { freq: '词频', alpha: '字母', difficulty: '难度' }`.
If the policy leaves `freq` recognisably frequency-based, `词频` stays and the frontend is not rebuilt; if function words
move to the end and 词组 are spread, `词频` is no longer truthful and the honest label is `推荐顺序` — a two-line change
(`zh.ts:48` + its byte-for-byte mirror `docs/FRONTEND.md:254`, checked by `npm run check:copy`) that needs a new frontend
snapshot (§7). A third option — add `sort=learn` as the new default and keep `freq` as raw frequency — touches the TS union,
the Pydantic Literal, `VocabPage.tsx` `SORTS`, `zh.ts`, API.md §9/§20, FRONTEND.md §8 and `check_contract` (~8 files) and is
not recommended for the first release.

---

## 3 Recompute / invalidation triggers and their cost (measured on the live copy)

| Trigger | How it is noticed | Cost |
|---|---|---|
| every request / job query | `stats_params()` probes `SELECT value FROM kv WHERE key='seed_version'` (0.001 ms, PK), `SELECT COUNT(*) FROM words` (0.001 ms, covering index `ix_words_frq`), `SELECT MAX(id) FROM words` (0.001 ms) and reads the cache | ≈ 0.003 ms + dict copy of 18 values |
| seed import (startup `main.seed_check` :299–326 or `wd import-seed` in another process) | `kv.seed_version` changes → cache miss; same process also calls `invalidate_stats()` | one `compute_stage_stats` = 2.47 ms (median; max 2.56) |
| runtime word creation (`services/words._insert_word` :604 via `_resolve_ecdict` :667 / `_create_provisional` :703) | `COUNT(*)`/`MAX(id)` change → cache miss on the next ordering query | 2.47 ms per new word, a few per day |
| in-place `frq`/`pos` fill by `lookup_apply` / consolidation (services/words.py:284, 579, 593, 673) | not detected by the key (`MAX(updated_at)` would cost 0.525 ms per request — a full scan, no index — and is not worth it) → TTL 600 s | at most one 2.47 ms recompute per 10 minutes per process; the word itself sorts by its new `frq` immediately because `frq` is a row input — only the stage's quantile band is stale by ≤ 1 rank |
| `is_public` flips by hand (WORD_LIBRARY_CURATION §1.5) | TTL | same |
| per-connection registration | `db.connect` | ≈ 1 µs |
| the ordering queries themselves | — | see table below |

Site cost, median ms over 21 runs (pass 2 §7; A = today, C4 = this design; pass-1 B1 = SQL-only for comparison):

| Site (user kimi, 主攻 xs, 目标 xs+zk) | rows sorted | A today | C4 | Δ | B1 SQL-only |
|---|---|---|---|---|---|
| `GET /api/vocab?stage=all` page 1 | 9,618 | 1.39 | 6.01 | +4.6 | 18.13 |
| `GET /api/vocab?stage=all` page 40 (OFFSET 1950) | 9,618 | 4.43 | 9.69 | +5.3 | 22.21 |
| `GET /api/vocab?stage=xs` page 1 | 600 | 0.65 | 1.01 | +0.36 | 7.92 |
| 筛词 `screen_next` count 30 | 2,549 | 1.05 | 2.32 | +1.27 | 10.18 |
| 推荐词 `select_words` screens 15 | 2,549 | 0.89 | 2.14 | +1.25 | 9.92 |
| 加练 `add_more` 5 | 2,549 | 1.02 | 2.32 | +1.30 | 10.11 |
| 预生成 candidates xs 50 | 600 | 0.72 | 1.03 | +0.31 | 7.84 |
| lookup suggestions `ab` 5 (if followed) | ~40 | 0.02 | 0.04 | +0.02 | 6.38 |

The delta is 0.48–0.60 µs per candidate row — the Python call (`dominant_pos` alone is 0.22 µs/row, the whole key 0.49). The
query plans are identical to today's for every site (`SCAN w` / `SEARCH w USING INDEX ix_words_public …` → `USE TEMP B-TREE
FOR ORDER BY`; pass 2 §7 prints them); the sort was already a full sort of the candidate set because today's leading
expression `(w.frq IS NULL OR w.frq = 0)` cannot use `ix_words_frq` either. Worst case is the 全部 tab of 词库 at ≈ 10 ms;
筛词 and the nightly batch builder pay ≈ 1.3 ms per user.

---

## 4 Integrity

### 4.1 `wd check db` (diag.py)

Two new lines after `invariant seed_version_matches_file`, under the same schema-11 guard (`kind`, `sources`, `stage_xs` exist
from 0011):

```
invariant order_function_registered: ok | 1 violation(s) (wd_order_key missing on a db.connect connection)
invariant order_key_total: ok | N violation(s) (first: <lemma> — <ExceptionType>)
order stats: xs 64/721/4978 · zk 413/1622/5957 · gk 1163/2865/6958 · cet4 2505/5267/11417 · cet6 4244/8685/18056 · 课标外 4798/12444/23679 · frq-less 758 (bnc 225, spread 533)
```

* `order_function_registered` runs `SELECT wd_order_key('x', NULL, 1, NULL, 'word', NULL, 1, NULL, NULL, NULL)` on the check's
  own connection — it catches a regression in `db.connect`, the single point of failure of this design.
* `order_key_total` does **not** rely on the UDF (a raising UDF surfaces as `OperationalError`, which `_invariant_line` reports
  as "query failed" and would not count): it fetches `lemma pos frq bnc kind sources stage_min` of every unmerged word
  (`SELECT … FROM words WHERE merged_into_word_id IS NULL`) and calls `order.order_key` in Python with the live statistics,
  counting rows where the policy raises or returns a non-finite value. 9,618 rows × ≈ 1 µs ≈ 10 ms. A violation flips the
  check to FAIL exactly like the stage invariants; it is the operator's post-import gate for the order.
* the `order stats` line is informational (never flips `ok`).

`STAGE_INVARIANTS` itself (diag.py:50–57) is **not** extended: it is pinned to the PLAN §6 S6 literal by `test_diag.py` and
holds data invariants, whereas this is a code/data compatibility check — hence a sibling function like `_seed_version_line`.

### 4.2 `scripts/rehearse_migration.py`

Nothing migrates, but the script is the operator's dress rehearsal on a copy, so it gains `check_order(rep, conn)` called after
`check_invariants` (:375–376) when `db.current_version(conn) >= STAGE_INVARIANTS_FROM_VERSION`:

```
[ok] wd_order_key registered on the rehearsal connection
[ok] invariant order_key_total: 9618 rows, 0 violation(s)
[info] order stats: xs 64/721/4978 · … (2.5 ms); first 10 of 小学 in learning order: say not an go get make know up one time
```

Import `from wd.services import order` next to `:50–52`. The module docstring bullet list (:16–31) gets one bullet. The empty
database check (:302–319) is untouched; a fresh database has no statistics → `stage_stats` returns `{}` → every key falls to
`UNKNOWN_FRQ` → the function is still total (one unit test pins that).

### 4.3 Version skew

* **Older server, newer seed** (seed v2 unchanged by this design): exactly as today — the importer's unknown-code warning path
  (DESIGN §3.2) is untouched; the older server orders by `frq`.
* **Newer server, older database** (schema ≥ 11): all inputs exist; the statistics come from whatever `words` holds; a database
  before any import (`kv.seed_version` NULL, `words` empty) yields `{}` statistics and the function stays total. On schema < 11
  the server migrates at startup before serving (main.py:489), so no ordering query ever runs against the old DDL.
* **Newer database, older server** (a future 6th stage, `stage_min = 6`): the older server's CASE has no arm for 6 → `ELSE :p10_0`
  (the 课标外 band); still total, still deterministic. A stages-as-data schema (PLAN P7) would change `stage_min`'s type;
  `order_by()` and `compute_stage_stats` are the two places to adapt.
* **Frontend skew**: the API shape is unchanged; an older SPA snapshot keeps working.
* The WORD_LIBRARY_CURATION warning (C10, :150) stays true: `_STAGE_DISTANCE` remains the first key in 筛词/推荐词, so a hand-inserted
  row with stage flags but `stage_min IS NULL` still sorts first for every user; the admin rule becomes "set `stage_*`,
  `stage_min` and `frq` (and `pos`, which the gate reads) together".

---

## 5 Tests

### 5.1 New `backend/tests/unit/test_order.py` (≈ 180 lines)

* `order_key` is total: parametrised over garbage inputs (`None` everywhere, text in `frq`, `pos='v./n.'`, `pos='n:x/v:1'`,
  `stage_min=99`, negative/zero `frq`, bytes) → a finite float, never an exception.
* `closed_class` reads the dominant pos exactly like `wd.images.style` (the 54 first-letter disagreements of FACTS §2: `one
  answer light part next other half all any both following past` are content; `of`, `despite`, `the` are closed; `very`/`not`
  adverbs are content under the stand-in policy); `inherit:be` rows (`is`) are closed; `ought to` is not AUX.
* `effective_frq`: `frq` → `bnc` → spread inside `[p10, p90]` (property: for 1,000 synthetic lemmas every value lies in the band
  and the deciles are each within 3σ of n/10) → constant `p50` when `p90 <= p10` → `UNKNOWN_FRQ` without statistics.
* `hash01` pins: `monday 3755093257`, `ice cream 2295515455`, `schoolbag 3192515231`, `p.e. 3170141767` (crc32), and `hash01(x) in [0,1)`.
* `order_by("w")` contains `FUNCTION_NAME`, every `ORDER_INPUT_COLUMNS` as `w.<col>`, one arm per `schemas.STAGE_INDEX` value
  and an `ELSE :p10_0`; `order_by("x")` uses the alias; the text is constant across calls (statement-cache argument).
* `register`: `db.connect(settings.db_path)` → `SELECT wd_order_key(...)` works; a bare `sqlite3.connect` → `no such function`.
* `compute_stage_stats` on the `seeded` fixture equals a hand computation over the mini seed (stage 5: `(8596, 8596, 8596)`,
  degenerate), and `stage_stats` refreshes after `INSERT INTO words` (COUNT/MAX(id) key), after `kv_set('seed_version', …)`, after
  `invalidate_stats()`, and not before TTL on an in-place `UPDATE words SET frq` (monkeypatched clock).
* `stats_params` keys are exactly `{p10,p50,p90} × {0..5}`.
* differential: for the `seeded` database, `SELECT lemma … ORDER BY <order_by>` with `stats_params` equals
  `sorted(rows, key=lambda r: order.sort_key(r, stats))` for 全部, each stage flag and the `_STAGE_DISTANCE`-prefixed form.

### 5.2 Existing tests that pin the order (FACTS §3) and their new expectation

| Test | Today pins | New expectation (in words) |
|---|---|---|
| `tests/integration/test_vocab.py:93` `test_vocab_default_is_everything_sorted_by_frequency` | first lemma `be`, `frq` ascending, NULL last | renamed `…_in_learning_order`: the 50+12 items equal the Python reference order built from the DB rows with `order.sort_key` (stable under any policy); `bookshelf` is still listed under 全部 with `stages == []`; the "NULL last" assertion goes (frequency-less words now sit inside their stage's band). Under the stand-in policy the first lemmas become `an` (bnc 30; its `pos` is empty, so the gate cannot see the article — the stand-in's known gap, also visible on the live copy at position 3 of 小学), `go` (35), `take` (63), and `be`/`a`/`some`/`is` move to the tail of their stage (`sim-qt/mini_seed_reference.py`) |
| `test_vocab.py:163` `test_vocab_sort_alpha_and_difficulty` | `sort_key` lambda `(COALESCE(difficulty+1, stage_min, 6), frq is None, frq, lemma)` over API items | tier assertions (`absorption < abandon < absolutely < ought to < bookshelf`, `bookshelf` last) stay; the within-tier key is `order.sort_key` over DB rows (API items lack `pos`/`bnc`/`sources`), so the lambda is replaced by a lookup into the reference computed via `qrows`; determinism assertion stays |
| `tests/integration/test_screen.py:122` `test_next_order_and_remaining` | cet6 first three `absorption, axe, ought to`; zk `go, person, better` | both lists equal the reference order of the respective candidate sets (compute with the same helper); under the stand-in policy cet6 becomes `absorption, ought to, axe` (`ought to` has neither `frq` nor `bnc`; the degenerate stage-5 statistics give it the constant 8596, tie broken by lemma) and zk stays `go, person, better` |
| `test_screen.py:142` `test_next_auto_for_a_primary_school_learner_orders_by_stage_distance` (`expected_xs` at :150 computed with the frq ORDER BY) | distance-0 block in frq order | `expected_xs` computed from the DB rows with `order.sort_key` (or via `order.order_by` on a `db.connect` connection); the distance assertions `{0, 1, 3}` are untouched |
| `test_screen.py:161` `test_next_default_count_and_default_settings` | first item `stage_min == 1` | unchanged (stage distance still leads) |
| `tests/unit/test_batches.py:104` `test_build_batch_caps_ordering_and_counts` (`screens == ["absolutely", "axis"]` at :129) | 主攻 cet4 by frequency | the two 推荐词 are the first two cet4-first words of the reference order; under the stand-in policy still `absolutely, axis` (`absolutely` is an adverb → content) — if the policy later demotes adverbs the assertion follows the reference, not a literal |
| `test_batches.py:152` `test_build_batch_cold_start_puts_screens_first` | kinds only | unchanged |
| `tests/integration/test_words.py:86–87` (suggestions `frq` ascending) | raw `frq` | unchanged while site 5 stays on `frq` |
| `tests/integration/test_admin_ops.py:488` (prewarm candidates as a set) | set equality | unchanged |
| `tests/unit/test_diag.py:49` `test_check_db_reports_the_four_invariants_ok_after_a_seed_import` and `INVARIANT_NAMES` | four `invariant` lines in PLAN §6 S6 order | six lines: the four, then `order_function_registered`, `order_key_total`; the `order stats:` line is not an `invariant` line. New cases: a monkeypatched raising policy → `order_key_total: N violation(s)` and `ok=False`; a connection without registration → `order_function_registered: 1 violation(s)` |
| `tests/unit/test_db.py:21` `test_connect_pragmas_and_autocommit` | PRAGMAs, autocommit, Row | add one assertion: `wd_order_key` callable on the connection (or a sibling test) |
| `tests/unit/test_docs_contract.py` | API.md/DEPLOY/TASKS pins | new `test_api_and_design_name_the_order_function`: API.md §20 and DESIGN §6.3 step 4 contain `order.FUNCTION_NAME` and the seven `ORDER_INPUT_COLUMNS` in order; CLAUDE_INTEGRATION §6.1 and WORD_LIBRARY_CURATION §1.6 contain `wd_order_key` |
| `pytest -m full_seed` (reads `data/seed/stats.json` against `WD_FULL_SEED_DB`) | seed numbers | new full-seed test: on the real seed, `order_key_total` has 0 violations and the first 40 小学 words contain no `closed_class` word (mechanism-level: the gate the policy declares is honoured by the SQL order) |
| frontend `vitest` + `npm run check:copy` | `zh.vocab.sort.freq === '词频'` mirrored in FRONTEND.md §8 | only if the label changes (§2.7): mirror line `docs/FRONTEND.md:254` edited byte for byte |

Helper worth adding to `tests/integration/conftest`-level utilities: `reference_order(settings, where_sql) -> list[str]`
that opens `db.connect`, computes `order.stage_stats`, fetches the rows and sorts with `order.sort_key` — used by the three
integration tests above so no literal word list is pinned to a policy that is still open.

---

## 6 Documentation edits (lockstep with the code; `test_docs_contract` pins the function name)

| Doc / section | Today | Edit |
|---|---|---|
| `docs/API.md` endpoint 20 (:169) | `default freq: ORDER BY (frq IS NULL OR frq=0), frq, lemma; … difficulty: ORDER BY COALESCE(difficulty + 1, stage_min, 6), (frq IS NULL OR frq=0), frq, lemma` | `freq` (推荐顺序): `ORDER BY wd_order_key(w.lemma, w.pos, w.frq, w.bnc, w.kind, w.sources, w.stage_min, p10, p50, p90), w.lemma` — `wd_order_key` is the application-defined function of `services/order.py` (registered by `db.connect`), `p10/p50/p90` the stage's frequency quantiles bound per request; `difficulty`: `COALESCE(difficulty + 1, stage_min, 6)` then the same key; link to DESIGN §6.3 step 4 for the policy; the sentence "the order is always deterministic" stays true and should say why (pure function of the rows + crc32) |
| `docs/API.md` endpoint 31 (`GET /api/screen/next … by frequency`) | "by frequency" | "then the learning order of endpoint 20 (`wd_order_key`)" |
| `docs/DESIGN.md` §3.2 (:205) row `pos, collins, oxford, bnc, frq` | "`0`/`null` frequency = unknown (sorted last)" | "`0`/`null` frequency = unknown; the learning order falls back to `bnc`, then to a deterministic position inside the stage's p10–p90 band (§6.3 step 4) — never 'last' any more" |
| `docs/DESIGN.md` §6.3 step 4 (:364–370) | `ORDER BY stage_distance(…) ASC, (w.frq IS NULL OR w.frq=0) ASC, w.frq ASC, w.lemma ASC` | `ORDER BY stage_distance(…) ASC, wd_order_key(w.lemma, w.pos, w.frq, w.bnc, w.kind, w.sources, w.stage_min, p10, p50, p90) ASC, w.lemma ASC` + a short "learning order" sub-block: inputs, where it is computed (query time, `services/order.py`, nothing stored), the statistics and their cache, the policy summary once decided |
| `docs/DESIGN.md` §6.2 (:350 last sentence) | "The default stage range and recommendation order therefore always derive from the user's own choice." | keep; append "(the within-stage order is the learning order of §6.3 step 4)" |
| `docs/FRONTEND.md` §4/§5 `/vocab` (:56, :147) and §8 (:254) | sort labels `词频 / 字母 / 难度` | no change unless the label becomes `推荐顺序` (§2.7) — then :254 byte for byte with `zh.ts:48`, and :147 mentions the default sort name |
| `docs/CLAUDE_INTEGRATION.md` :303 (`prewarm_plan` mechanics) | "… not yet enqueued, by frequency; …" | "… not yet enqueued, in the learning order (`services/order.py` `wd_order_key`, API.md 20); …" |
| `docs/WORD_LIBRARY_CURATION.md` :150 (选词规则, 核验 C10) | "按阶段距离 → 词频（frq 为空排最后）→ 字母序 … 必须同时给 `stage_*`、`stage_min` 和 `frq`" | "按阶段距离 → 学习顺序键 `wd_order_key`（查询时由 `services/order.py` 计算，不落库：主词性、`frq`→`bnc`→按阶段频率分位带确定位置）→ 字母序。`stage_min` 为空的手工行仍排在筛词**第一位**；管理员插入词条须同时给 `stage_*`、`stage_min`、`frq` 与 `pos`" |
| `docs/releases/2026-11-k12-stages.md` §9 末 (:212–213 未决 paragraph) | "小学阶段的全部顺序 … 仍按成人语料 `frq` 排序 … **邀请小学生之前必须处理**" | mark resolved by the follow-up release note (new `docs/releases/2026-11-learning-order.md`: what changed, no migration, restart-only, how to verify with `wd check db` / `wd order`, rollback) and point to it |
| `docs/analysis/…/design/PLAN.md` §9.2 #5 (:755) | open | "resolved by mechanism query-time, see …" |
| `docs/DEPLOY.md` §9 CLI reference | — | one row for `wd order` if the optional subcommand ships |
| `docs/SCHEMA.sql`, `docs/API.md` §9 types | — | **no change** (no column, no union change) |

---

## 7 Deployment and rollback

### 7.1 Mac (launchd, data dir `/Users/sqin/word-dance-data`)

* Nothing pending in `schema_migrations`, no table rebuild, no seed change → the **stop-first runbook is not needed**. A
  restart is enough: `launchctl kickstart -k gui/$(id -u)/com.word-dance.server` after the checkout is on the new commit
  (`wd serve` runs the editable install of `backend/`). The pre-migrate snapshot hook does not fire (nothing to apply); no
  data is written by this change, so no manual backup is required either — `wd backup` before the restart is harmless.
* Frontend snapshot: **only if the `zh.ts` label changes** (§2.7). Then build and publish as in the K-12 runbook step 1/5:
  `SHA=$(git rev-parse --short HEAD)`, `npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir`, `mv`, `ln -sfn`
  to `frontend.tmp`, `os.rename` onto `frontend`, then the kickstart. With the label unchanged the running snapshot
  `frontend-releases/cd3df8c` stays.
* Verify: `curl --noproxy '*' http://127.0.0.1:8000/api/health`; `WD_DATA_DIR=/Users/sqin/word-dance-data .venv/bin/wd check db`
  → `invariant order_function_registered: ok`, `invariant order_key_total: ok`, the `order stats:` line; `wd order --stage xs
  --limit 40` (if shipped) or a logged-in `GET /api/vocab?stage=xs` → first three no longer `the, be, and`.
* Effect on live users: batches already built keep their `push_items` (materialised rows); the next nightly build and every
  筛词 page load use the new order; a user mid-onboarding sees a different candidate stream after the restart (the words
  already graded stay graded — `NOT EXISTS user_words` still excludes them).
* Rollback: `git checkout cd3df8c` (or the previous tag) and the same `kickstart -k`; no data to undo. If the label was
  changed, re-point `frontend` at `frontend-releases/cd3df8c` as in the release note §7.

### 7.2 Lighthouse (systemd, `deploy/install.sh`)

`git pull && deploy/install.sh` does more than necessary but is correct: it builds and publishes the snapshot, stops the unit,
runs `wd migrate` (nothing pending) and `wd import-seed` (no-op: `kv.seed_version` matches), restarts. `--no-restart` is
pointless here (there is no migration to protect) and would leave the old code serving. Downtime ≈ 3 s. Before the run,
`scripts/rehearse_migration.py <copy>` on a private copy prints the two new order checks (§4.2) — the dress rehearsal also
proves the target machine's Python/SQLite build registers the function (no math-function dependency to check).
Rollback: `git checkout <previous> && deploy/install.sh` (DEPLOY §10).

---

## 8 Risks, blast radius, size

| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| The UDF raises on some row → every ordering statement fails (`OperationalError: user-defined function raised exception`) → 词库, 筛词, nightly batches down | low (total function by construction) / high | `order_key` catches everything and returns `UNKNOWN_FRQ` with one log line per process; `order_key_total` in `wd check db` and the rehearsal script over the whole live table; the full-seed test |
| `db.connect` stops registering (refactor) → `no such function` everywhere | low / high | `order_function_registered` check; `test_db` assertion; integration tests run through `db.connect` |
| A query opened outside `db.connect` orders words | low / medium | the verified inventory in §2.2; the module docstring rule; grep `frq IS NULL` finds only the five sites today |
| Someone puts `wd_order_key` into an index/view/trigger | low / high (DB unusable from the CLI, `wd restore` verifier) | the §2.4 rule in db.py's docstring and DESIGN §6.3; `check_empty_database` would also fail if a migration did it |
| Operators cannot inspect the order with the `sqlite3` CLI | certain / low | `wd order` preview; `wd check db` stats line; the reference key is a 10-line Python function |
| Stale statistics (≤ 10 min after an in-place `frq` fill) | certain / negligible | TTL; the key only moves a band by one rank |
| Performance regression at the 全部 tab (+5 ms) or on a slower VPS (Lighthouse CPU unknown) | medium / low | 0.49 µs/row today; 9,618 rows is the worst case; an API request is tens of ms end to end |
| Policy change needs new cross-row inputs (e.g. per-stage count of frequency-less words) | medium / low | extend `StageStats` + the CASE params; the fragment and the reference key change in one module |
| Thread safety of the cache (scheduler/worker threads + request threads) | low / low | one `threading.Lock`; the dict is replaced, never mutated; the UDF reads only its arguments |
| `hash()` sneaks in instead of `crc32` (order differs per process → flaky tests, users see a reshuffle after each restart) | low / medium | pinned crc32 values in `test_order` |
| Copy drift (`词频` label vs a non-frequency order) | medium / low | §2.7 decision recorded; `npm run check:copy` mirrors §8 |

Blast radius: five query sites + one hook in `db.connect`; no schema, seed, API shape or stored data; frontend at most one
label. Everything is reversible by a restart on the previous commit.

Size estimate: `services/order.py` ≈ 160 lines (≈ 200 with `wd order`); `db.py` +8; `routers/vocab.py` +4/−2;
`services/screen.py` +3/−1; `services/batches.py` +4/−1; `ai/prewarm.py` +4/−2; `seed.py` +2; `diag.py` +40; `cli.py` +2 (optional);
`scripts/rehearse_migration.py` +20; tests: new `test_order.py` ≈ 180, edits ≈ 70 across `test_vocab.py`, `test_screen.py`,
`test_batches.py`, `test_diag.py`, `test_db.py`, `test_docs_contract.py`, one full-seed test; docs ≈ 50 lines across API.md,
DESIGN.md, CLAUDE_INTEGRATION.md, WORD_LIBRARY_CURATION.md, the release note(s), PLAN.md, optionally FRONTEND.md/`zh.ts`/DEPLOY.md.
≈ 16 files, ≈ 550 lines; one or two commits (code + tests + docs, then the optional copy change with its snapshot).

---

## 9 Extensibility to a textbook / grade order field

A future seed-carried field (e.g. `textbook_rank INTEGER` per word, or `(grade, unit)` for one 教材 edition) arrives by the
seed-carried/derived-column mechanism of the sibling documents; this mechanism absorbs it without changing where the order is
computed:

* **Column as a leading key**: `order_by()` returns `COALESCE(w.textbook_rank, 1e9), wd_order_key(…), w.lemma` — textbook order
  first where it exists, the learning key as the tie-break and for words outside the textbook. One function, one constant,
  the same five sites unchanged (they already take the fragment from `order.order_by`).
* **Column as an input of the key**: add an 11th argument (`w.textbook_rank`) so the policy can blend it (e.g. a textbook
  rank wins only within the same stage distance). `ORDER_INPUT_COLUMNS`, `register` (arity), `sort_key` and the docs pin change
  together; `test_docs_contract` catches a doc left behind.
* **Per-user textbook**: the fragment can take a bound `:textbook_id` (`CASE WHEN tw.textbook_id = :textbook_id …` via a join
  to a `textbook_words` table) — parameters are already the channel the statistics use.
* **Statistics**: `StageStats` can grow (per-stage count of frequency-less words for an even spread by rank, or per-textbook
  bounds); `compute_stage_stats` stays one fetch; the cache key (`seed_version`, COUNT, MAX(id)) already covers a seed that
  adds the column.
* What does **not** fit this mechanism: an order that depends on the user's own history beyond "not yet seen" (that is the
  SRS/bank's job, DESIGN §6.3 steps 2–3), and an order that must be identical across releases for stored artefacts — batches
  materialise their rows, so they are already immune to policy changes.

---

### Appendix A — measurement provenance

* `sim-qt/bench_query_time.py` → `bench_output.txt` (pass 1): variants A/B1/B2/C1/C2/C3, per-row UDF costs, SQL-vs-Python
  dominant-pos agreement (0 mismatches, 0 gate disagreements, 727 empty `pos`), EXPLAIN QUERY PLAN for every site, the xs/zk
  illustrations.
* `sim-qt/bench_query_time_v2.py` → `bench_output_v2.txt` (pass 2): the NULL-key trap (724 rows) and its fix, variant C4, the
  three statistics methods (6.43 / 2.47 / 3.43 ms, identical numbers), registration cost (≈ 1 µs), staleness probes
  (0.001 ms for kv/COUNT/MAX(id), 0.525 ms for MAX(updated_at)), crc32 evenness (KS 0.104 / 0.038 / 0.025 for n = 30 / 381 /
  758), failure modes (raise → statement fails; NULL → sorts first; unregistered → `no such function`), the site table with
  plans identical to the baseline, the differential check (identical on xs 600, zk-new 1,949, cet6 7,671, all 9,618 rows),
  and the stand-in illustration (xs first 40: `say not an go get make know up one time year so think people take out see
  come now how then two want way look first also new day use man find here give well tell very back good woman`).
* `sim-qt/mini_seed_reference.py` → `mini_seed_reference_output.txt`: the reference order of `backend/tests/fixtures/mini_seed.jsonl`
  under the stand-in key (stage statistics xs (60, 257, 1434) · zk (345, 536, 697) · gk (811, 3165, 7490) · cet4 (1149, 5598, 5598) ·
  cet6 (8596, 8596, 8596) · 课标外 (11170, 11170, 11170)), the source of the literal expectations quoted in §5.2.
* All three scripts open the live copy only through `file:…?mode=ro&immutable=1` (or read the fixture) and write nothing but stdout.
