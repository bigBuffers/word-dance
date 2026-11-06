# Learning order (学习顺序) — implementation plan · 2026-11-06

Status: **contract for implementation** (synthesis of the policy judge — winner `frequency-purist` with must-fix M1–M8 and grafts
G1–G10 — and the two mechanism judges — both pick `derived-column`; their must-fix lists are folded in below). Base: `main` @
`cd3df8c`, schema 13, seed content sha256 `24f3b949…6692` (9,618 words), deployed on the owner's Mac. Every number quoted as
"measured" comes from the reference simulation `sim/sim_final_policy.py` in this directory (→ `sim/sim_output.txt`,
`mini_seed_golden.json`) run on the read-only live copy, on a scratch copy and on the mini seed imported with the real importer;
such numbers are evidence for this document only — repository docs and tests must read them from `data/seed/stats.json`,
`data/seed/learn_order.json` or SQL, never as literals (FACTS §3 convention). zh-CN UI terms are used where the copy matters:
小学 / 初中 / 筛词 / 推荐词 / 词库.

---

## §0 Summary

Every "which word next" list — 词库 default sort, 筛词 (`GET /api/screen/next`, onboarding), 每日推荐词 (`batches.select_words` /
`add_more`) and admin 预生成 (`prewarm.candidates`) — stops ordering by the adult COCA rank `words.frq` and orders by a **derived,
stored integer key `words.learn_rank`** computed by one pure module (`backend/wd/services/learn_order.py`) from the columns the
database already has (`lemma`, `pos` through `dominant_pos`, `frq`, `bnc`, `sources`, `stage_min`, `word_forms`). The policy is the
frequency-purist order with the four pedagogy grafts the judge required: words come in corpus-frequency order (COCA, BNC where
COCA has none); grammar words (articles, pronouns, prepositions, conjunctions, auxiliaries, modals) come after all the content
words of their stage; frequency-less words (the 381 上海词组, abbreviations), adverbs and interjections are dealt evenly through
the stage; the 12 months and 7 weekdays each appear as one calendar-ordered block; `am/are/is` follow `be`, `does` follows `do`.
No numeric tunable; 16 + 19 curated lemmas. The key lives in one nullable column added by the additive migration `0014_learn_rank.sql`,
is recomputed inside every seed import, at every service start (stored-vs-computed compare, ≈ 20–40 ms) and nightly, is
inspectable with plain SQL, and degrades to exactly today's order when NULL. Deployment on the Mac is a restart; rollback is a code
checkout. Measured on the live seed: the first 30 小学 cards contain 0 grammar words (today 28) and 2 adverbs; months at 243–254,
weekdays 343–349 in calendar order; `be am are is` at 527–530; a 初中 learner meets a 词组 in 42 of the first 200 cards (today 0);
CET-4's first 100 keep 90 of today's words and no longer start with `oh`.

**Owner-facing explanation (two sentences, zh-CN):** 卡片按英语里的常用程度排序（COCA 词频，缺的用 BNC 补），语法词——冠词、代词、介词、
连词、助动词——排在本阶段所有实义词之后。没有词频的词（上海词组、缩写）、副词和感叹词按均匀间隔插入，月份和星期各作为一组按日历顺序出现，
am/is/are 紧跟 be。

---

## §1 The policy — exact rules

### 1.1 Inputs (and nothing else)

| input | read how | used by |
|---|---|---|
| `words.lemma` | as is | R1b lists, M1 calendar lists, R3 token split, tie-break |
| `words.pos` | **only** through `wd.images.style.dominant_pos` (D-images-24; `None` for NULL / empty / label-shaped `'v./n.'`) | R1a closed gate, M3 adverbs (`r`), G5 interjections (`u`) |
| `words.frq`, `words.bnc` | `int()` under `try`; `≤ 0`, NULL, text → unknown | R2 rank |
| `words.sources` | space-split tokens; the first `inherit:<head>` token | R1c, M2 glue |
| `words.stage_min` | `1..5` or NULL (课标外); any other value → treated as NULL | group key, stage distance |
| `word_forms(form → word_id)` | a form that points at exactly one word | R3 ordering token (`be located → locate`) |

Not read: `kind` (M1 uses lemma lists, G5 uses `pos`), `collins`, `oxford`, `difficulty`, `exchange_json`, user data, the clock.

### 1.2 Constants (the only curated data; every one pinned by `test_learn_order.py`)

```python
ORDER_CLOSED_POS: frozenset[str] = wd.images.style.FUNCTION_POS - {"u"}      # {i c d p a t}; G5 — imported, never copied
CLOSED_LEMMAS = frozenset({"a", "an", "the",                                  # articles (ECDICT gives `an` no pos)
                           "be", "do", "have",                                # primary auxiliaries
                           "can", "could", "will", "would", "shall", "should", "may", "might", "must", "ought"})  # modals — 16
MONTHS   = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
STAGE_NULL_DISTANCE = 2 * len(schemas.STAGE_ORDER) + 1                        # 11 — derived from the enum (M4)
# key packing (encoding constants, not tunables)
CLOSED_BASE, RANK_SCALE = 10_000_000, 100
SUB_NATIVE = 0            # a word's own rank
SUB_GLUED_BASE = 0        # glued form j (1-based among the head's forms sorted by lemma) → head.sub + j   (1..19 in practice)
SUB_DEALT = 20            # frequency-less word dealt onto a host (R3)
SUB_MONTH_BASE = 20       # month ordinal 1..12 → 21..32
SUB_WEEKDAY_BASE = 32     # weekday ordinal 1..7 → 33..39
SUB_ADVERB = 40           # adverb dealt onto a host (M3)
SUB_INTERJ = 50           # interjection dealt onto a host (G5)
```

`learn_rank = (CLOSED_BASE if closed else 0) + rank * RANK_SCALE + sub`; NULL when the row has no rank at all (R4). Max live key
13,812,400 < 2·10^7 (max seed rank 46,049 → 4,604,999 < CLOSED_BASE, pinned by a test). At equal `learn_rank` the SQL tail
`(frq IS NULL OR frq = 0), frq, lemma` decides (a COCA-ranked word before a BNC-rescued one with the same rank value, then lemma;
`lemma` is UNIQUE so the order is total).

### 1.3 Rules, in evaluation order

**R2 — rank.** `rank(w) = frq if frq > 0 else bnc if bnc > 0 else NULL`. Fires for 225 seed words via BNC (measured: xs 2 after the
calendar rule takes the months/weekdays, zk-new 50, gk 20, cet4 18, cet6 91, 课标外 27).

**R1 — closed class** (`closed(w)`), with M1's precedence:
```
closed(w) := False                                         if lemma ∈ MONTHS ∪ WEEKDAYS          (M1: `may` is a month here, `march` v, `august` j)
          := dominant_pos(pos) ∈ ORDER_CLOSED_POS          (R1a — adverbs `r` and interjections `u` are NOT closed)
             OR lemma ∈ CLOSED_LEMMAS                      (R1b)
             OR sources carries an `inherit:` token        (R1c — am is are does; future was/were/been/being/has/had/did/done)
```
Closed words sort after every content word of the same stage-distance group, in rank order among themselves (binary demotion,
G10 kept). Measured: 189 closed rows in the seed (xs 75).

**Classes.** Every row gets exactly one class, tested in this order: `set` (lemma ∈ MONTHS ∪ WEEKDAYS) · `glued` (first
`inherit:X` token whose head `X` exists in `words` and `X ≠ lemma`) · `adverb` (not closed, dominant pos `r`) · `interj` (not closed,
dominant pos `u`) · `plain` (everything else: content words, phrases, abbreviations, proper nouns, closed words). Measured: plain
9,191 · adverb 390 · interj 14 · set 19 · glued 4.

**Groups.** `G = (stage_min, closed)` over all non-glued rows (NULL `stage_min` = the 课标外 group; 12 groups on the live seed).
Inside each group:

1. **hosts** = plain rows with a rank, sorted by `(rank, lemma)`; `n_r = len(hosts)`. Every host keeps `sub = 0`.
2. **R3 — frequency-less plain rows are dealt evenly**, ordered by their rarest resolvable token:
   `tokens = lemma.replace('-', ' ').split()`; a token resolves to `words.lemma == token`, else to the single word the
   `word_forms` rows for that form point at (ambiguous forms do not resolve); tokens resolving to the row itself are skipped;
   `token_rank = max(rank(head))` over resolved tokens with a rank, NULL when none. Sort the unranked by
   `(token_rank IS NULL, token_rank, lemma)`; `n_u = len(unranked)`; the k-th (1-based) takes
   `host = hosts[min(n_r, max(1, ceil((k − 0.5) · n_r / n_u))) − 1]`, `rank = host.rank`, `sub = SUB_DEALT`. If `n_r = 0` the rows keep
   `rank = NULL` (R4).
3. **M1 — calendar sets.** For `members` in (`MONTHS`, `WEEKDAYS`): `present` = set rows of the group whose lemma ∈ members. If any
   member has a rank: `anchor = statistics.median_low(ranks of the present members with a rank)`; every present member gets
   `rank = anchor`, `sub = base + ordinal` (month ordinal 1..12 → 21..32, weekday 1..7 → 33..39). If no member has a rank: deal the
   present members in calendar order onto `hosts` with the step-2 formula, keeping the calendar `sub` (fallback for E1 "BNC gone";
   the block is then still contiguous and calendar-ordered when they share a host, else calendar-ordered across hosts).
4. **M3 — adverbs** (class `adverb`), sorted by `(rank IS NULL, rank, lemma)` — frequency order kept — dealt onto `hosts` with the
   step-2 formula; `sub = SUB_ADVERB`. No window constant: "adverbs are spread evenly through the stage".
5. **G5 — interjections** (class `interj`), same dealing, `sub = SUB_INTERJ`.

**M2 — glued inherited forms.** For a `glued` row with head `X`: `learn_rank = learn_rank(X) + j` where `j` is the row's 1-based
index among all rows gluing to `X`, sorted by lemma (`be → am 1, are 2, is 3`; `do → does 1`); the row's own `frq`/`bnc`/`pos` are
ignored (`is` has garbage BNC 24648). The head's `learn_rank` is NULL → the form is NULL too (R4). A head absent from the table →
the row is `plain` and R1c makes it closed, as today.

**R4 — no rank at all.** `learn_rank = NULL`; such a row sorts after every ranked row of its stage-distance group by the frq tail
(today's order). After R3 no live seed row is NULL (measured: 0; pinned by `learn_rank_present`); it is the degradation path for
runtime rows and tiny fixtures.

**M4 — stage distance** (筛词, 推荐词, 词库 tabs, prewarm):
`stage_distance(s, cur) = 0 if s == cur; 2·(s − cur) − 1 if s > cur; 2·(cur − s) if s < cur; STAGE_NULL_DISTANCE (11) if s is NULL`
— SQL rendered once by `learn_order.stage_distance_sql()`; the two identical copies in `screen.py:34` and `batches.py:60` are
replaced by it (M4 unification). The hand-inserted "C10" row (`stage_xs = 1`, `stage_min NULL`) moves from card 1 to card 601 of
601 in every 小学 筛词 list (measured on the scratch copy).

**G6 — the 词库 tabs read like a learner's stream.** `sort=freq` (UI 学习顺序) orders by `stage_distance(stage_min, cur)` first,
then the key, where `cur` = the tab's stage index and, for 全部, `cur = stage_to_index(STAGE_ORDER[0]) = 1` — which is exactly
`COALESCE(stage_min, 6)` ascending (the judge's G6: 全部 starts with the 小学 course, 课标外 last). On the 初中 tab the 初中新增
words come first and the 小学 words follow at 1,950 (measured) — the same order a 主攻 初中 learner's 筛词 produces.

### 1.4 Full ORDER BY (one fragment, `learn_order.ORDER_SQL`, table alias `w`)

```
w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma
```
preceded at 筛词 / 推荐词 / 词库 / prewarm by `CASE WHEN w.stage_min IS NULL THEN 11 WHEN w.stage_min = :cur THEN 0
WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END,` and at the `difficulty` sort by
`COALESCE(w.difficulty + 1, w.stage_min, 6),`. Lookup prefix suggestions (`routers/words.py:106`) keep the raw tail
`learn_order.FRQ_TAIL = "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` (M8 / both proposals: autocomplete ranks by commonness).

### 1.5 Simulated outcome on the live seed (reference, `sim_output.txt`)

First 30 of each stage's own words (`stage_min = s`, i.e. the distance-0 block a learner of that 主攻阶段 meets):

* **xs 小学 (600):** say go get make know one time year not think people take see come two want way look first new day use man find
  up give tell good physical education woman — 31–60: child work call world school try last ask feel three family so put old keep
  student let great big begin help talk turn hand show place week out hear question
* **zk-new 初中新增 (1,949):** other thing have to life need state become go in for high leave just mean go on group seem country
  problem get on start american part get on with case company system program get to government number point
* **cet4-new 四级新增 (1,726):** federal republican congress stock media growth analysis democratic executive simply entire religious
  management statement employee production sexual agent consumer shot senate relation effective troop investigation researcher
  particularly argument possibility define

Probe positions (xs unless noted): months 243–254 and weekdays 343–349 in calendar order · be 527 am 528 are 529 is 530 · do 545
does 546 · the 526 (first grammar word; closed block 526–600) · not 9, up 25, so 42, out 58, now 75, how 91, then 107, also 123,
here 139, well 156, very 172, too 222 · yes 64, hi 191, hello 329, goodbye 463 (G5) · colour 195, email 142, ice cream 85, mr. 198,
schoolbag 498, physical education 29 · one 6 two 15 three 40 first 19 · cat 357 dog 216 apple 399 book 83 pen 431 red 181 mother 76 ·
like 575 (accepted cost) · 初中: have to 3, go in for 8, be made of 41, get up 50, look after 294, just 11, only 52, london 44,
centre 78, as/if/would 1873–1875, although 1905 · CET-4: oh 854, simply 10, particularly 27, due 1707 · CET-6: yeah 642,
currently 16 · 词库 全部: the 526, is 530, just 611, other 601, bookshelf (课标外) 9,489, 课标外 starts at 9,381.

### 1.6 Acceptance numbers (the `full_seed` assertions of §4.3; counts, not lemmas)

| assertion (live seed, per stage's own words) | measured | gate |
|---|---|---|
| FACTS-closed words (`dominant_pos ∈ FUNCTION_POS` or the 25-form AUX list `learn_order.ACCEPTANCE_AUX_LEMMAS` or `inherit:`) in the first 30 | xs 0 · zk 0 · gk 0 · cet4 0 · cet6 0 | `== 0` every stage |
| adverbs in the xs first 30 | 2 | `≤ 2` |
| 12 months contiguous, calendar order | 243…254 | 12 consecutive positions, `january` first |
| 词组 (`kind='phrase'`) in the zk-new first 200 | 42 | `≥ 40` |
| longest run of frq-NULL cards | xs 7 (the weekday block) · zk 3 · gk 2 · cet4 1 · cet6 3 | `≤ 7` every stage |
| stage words with NULL `learn_rank` | 0 | `== 0` |
| CET-4 first-100 overlap with today's frq order | 90 | informational (release note) |

---

## §2 The mechanism

### 2.1 Module `backend/wd/services/learn_order.py` (new, ≈ 330 lines incl. CLI)

Imports only `wd.db`, `wd.clock`, `wd.schemas`, `wd.images.style`, stdlib — never `wd.services.*`, so `seed.py`, `main.py`,
`services/words.py`, `services/screen.py`, `services/batches.py`, `ai/prewarm.py`, `routers/*`, `diag.py`, `jobs/scheduler.py` and
`scripts/rehearse_migration.py` import it without a cycle.

```python
"""Learning order (学习顺序): the derived words.learn_rank key — DESIGN §3.2 / §6.3 step 4, API.md 20/31, migration 0014,
docs/analysis/2026-11-06-learn-order/DESIGN.md §1 (the policy, LEARN_ORDER_VERSION).  …  A seed import may re-rank the
frequency-less / dealt words of the stage groups it touches (the dealing is a group computation); updated_at never moves."""

LEARN_ORDER_VERSION = "lo-1"                      # bump whenever rank_rows() would return a different key for any input
LEARN_ORDER_FROM_VERSION = 14                     # schema version carrying words.learn_rank
KV_VERSION, KV_SEED, KV_STATS, KV_AT = "learn_order.version", "learn_order.seed_version", "learn_order.stats", "learn_order.computed_at"
ORDER_CLOSED_POS, CLOSED_LEMMAS, MONTHS, WEEKDAYS, STAGE_NULL_DISTANCE, CLOSED_BASE, RANK_SCALE, SUB_* ...   # §1.2
INPUT_COLUMNS = ("id", "lemma", "pos", "frq", "bnc", "sources", "stage_min")
FRQ_TAIL  = "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"                    # the pre-0014 order; lookup suggestions keep it
ORDER_SQL = f"w.learn_rank IS NULL, w.learn_rank, {FRQ_TAIL}"                 # the learning order (every other list)

def order_sql(alias: str = "w") -> str                                        # ORDER_SQL for another alias (tests)
def stage_distance_sql(cur: str = ":cur", alias: str = "w") -> str            # the M4 CASE … END incl. NULL → STAGE_NULL_DISTANCE
def stage_distance(stage_min: int | None, cur: int) -> int                    # Python twin (tests, show())
def default_cur(stage: str | None) -> int                                     # a tab/filter stage → its index; "all"/None → stage_to_index(STAGE_ORDER[0])

@dataclass(frozen=True)
class WordInput:                                                              # the only thing the policy sees
    id: int; lemma: str; pos: str | None; frq: int | None; bnc: int | None; sources: str | None; stage_min: int | None
    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "WordInput"                  # total: int() under try, str(), unknown stage → None

def inherit_head(sources: str | None) -> str | None
def native_rank(frq: Any, bnc: Any) -> int | None                              # R2
def closed_class(lemma: str, pos: str | None, sources: str | None) -> bool     # R1 with M1 precedence
def pack(closed: bool, rank: int | None, sub: int) -> int | None               # §1.2 packing

@dataclass(frozen=True)
class RankRow:    id: int; lemma: str; stage_min: int | None; closed: bool; cls: str; how: str; rank: int | None; sub: int; learn_rank: int | None
@dataclass
class RankResult: ranks: dict[int, int | None]; rows: dict[int, RankRow]; stats: dict[str, Any]   # stats = compact per-stage table (§2.6)

def rank_rows(rows: Sequence[WordInput], forms: Mapping[str, frozenset[int]]) -> RankResult   # THE policy, pure, total, group-wise (§1.3)
def best_effort_rank(cols: Mapping[str, Any]) -> int | None                   # per-row: closed, native rank, SUB_NATIVE; None when no rank — pure, no conn
def load_inputs(conn) -> tuple[list[WordInput], dict[str, frozenset[int]]]    # SELECT INPUT_COLUMNS FROM words; SELECT form, word_id FROM word_forms

@dataclass
class RecomputeResult: version: str; rows: int; changed: int; unranked_stage_words: int; seconds: float; trigger: str; stats: dict; movers: dict | None

def recompute(conn, *, now: str | None = None, seed_version: str | None = None, trigger: str = "cli", dry_run: bool = False, movers: bool = False) -> RecomputeResult
    # compute phase (pure) → write phase inside db.maybe_tx: UPDATE words SET learn_rank = ? WHERE id = ? only for changed rows,
    # never updated_at; then kv.learn_order.{version, seed_version, stats, computed_at}; system_events('learn_order_recomputed')
    # when changed > 0 and trigger != 'seed_import'. dry_run writes nothing; movers=True fills the per-stage movers report.
def ensure_current(conn, *, now: str | None = None, trigger: str = "startup") -> RecomputeResult | None
    # recompute(…) — the stored-vs-computed compare IS the staleness test (ops judge must-fix 1); never raises:
    # any exception → log.exception + system_events('learn_order_failed'); the lists then serve the fail-soft order.
def is_current(conn) -> tuple[bool, str]                                      # kv version == code, kv seed stamp == kv.seed_version, no NULL stage rank (diag only)
def drift(conn) -> Drift                                                       # rows whose stored key ≠ rank_rows(), split: policy (stage rows placed by seed-only rules — the invariant) · dealt (R3-dealt stage rows, informational) · none (课标外, informational)
def stale_count(conn, *, stage_only: bool = True) -> int                      # drift(conn).stage (every stage row, dealt included — the rehearsal / full_seed check) or .total
def unranked_stage_words(conn) -> int                                         # COUNT(*) … stage_min IS NOT NULL AND learn_rank IS NULL AND merged_into_word_id IS NULL
def check_lines(conn) -> list[tuple[str, bool]]                               # the four `invariant …` lines of §2.7
def stats_line(conn) -> str                                                   # `kv.learn_order.stats: …` (§2.7), never flips ok
def show(conn, stage: str, top: int, *, cur: int | None = None) -> list[ShowRow]   # position lemma learn_rank closed how frq bnc eff (eff = rank the key encodes)
def report(conn) -> dict[str, Any]                                            # the data/seed/learn_order.json document (§2.8)
def register_cli(sub) -> None                                                 # `wd learn-order` (§2.5)
```

Totality (mechanism must-fix): `WordInput.from_row` coerces every input; `rank_rows` never raises on one row (a row whose inputs make
no sense gets `learn_rank NULL` and `how = 'unranked'`); `dominant_pos` is the only `pos` reader; a `stage_min` outside
`STAGE_INDEX.values()` is the 课标外 group. Pinned by the parametrised garbage matrix of §4.1.

Why group dealing and not a per-row crc32 spread (the one point where the operations judge's must-fix 2 conflicts with the policy
judge's winner): R3's "rarest token first" is the policy's one pedagogical signal for the 381 词组 (`have to` before `the pacific
ocean`), M1's median anchor and M3's even dealing are group computations by definition, and the policy judge's verdict (M6) is
the authority on the policy. Per-row purity is recovered where it matters: a runtime row with a native rank (every ECDICT hit) gets
its exact key from `best_effort_rank` (the key of a natively ranked, non-dealt word depends on no other row); a frequency-less or
adverb/interjection runtime row is NULL / approximate until the next recompute, which runs at every start and nightly (§2.4).
**Reach of a runtime word or form (review finding F-1, fixed in the gate's scope, not in the policy):** R3 resolves phrase tokens
against every `words` row and every `word_forms` row, so a runtime word (`sooner`, `york`, `kung`) or a runtime form (`sooner →
soon`) can make a token of a frequency-less **stage** phrase resolvable and re-deal every dealt row of that `(stage_min, closed)`
group behind it (measured on the live seed: 2–341 初中 keys per such word, one host slot each) until the next recompute; hosts,
calendar sets, adverbs, interjections and glued forms read seed-managed inputs only (runtime rows carry no stage flags and no
`inherit:` token), so their keys never drift at runtime. Hence `learn_rank_matches_policy` counts `Drift.policy` (stage rows placed
by the seed-only rules) and the re-dealt stage rows are the informational `dealt drift` of the stats line (A8). `crc32` is
therefore not used; `hash()` is forbidden by a grep test anyway.

### 2.2 Migration `backend/wd/migrations/0014_learn_rank.sql`

```sql
-- 0014_learn_rank.sql — words.learn_rank: the derived learning-order key (学习顺序) of every words row
-- (DESIGN §3.2 "learn_rank" / §6.3 step 4; API.md 20; docs/releases/2026-11-learn-order.md; backend/wd/services/learn_order.py).
--
-- Additive only, the 0012_word_images_meta.sql precedent: ONE ADD COLUMN, no default (NULL = "not computed yet"), no index — no
-- list query would use one: every learning-order ORDER BY follows a CASE (stage distance) or COALESCE (difficulty) term and sorts
-- in a temp B-tree (measured, plans unchanged) — and no table rebuild. No view, trigger or foreign key references the column:
-- v_bank is `SELECT uw.*, w.lemma, w.display, …` with the words columns named explicitly (0011), so it cannot pick the new column
-- up. Safe under `deploy/install.sh --no-restart` (DEPLOY §10) and a plain `launchctl kickstart -k` on the Mac. The VALUES are
-- deliberately not written here: learn_rank is DERIVED by learn_order.rank_rows() from lemma / pos (dominant_pos) / frq / bnc /
-- sources / stage_min / word_forms and filled at the next service start (main.startup → learn_order.ensure_current), inside every
-- seed import, by `wd learn-order` (deploy/install.sh runs it after `wd import-seed`) and nightly by the 03:30 maintenance. Until
-- then a NULL rank sorts after every ranked row of its stage-distance group by the pre-0014 frq order (learn_order.ORDER_SQL):
-- the lists stay exactly today's. The runner wraps this file in BEGIN IMMEDIATE and records schema_migrations(14, 'learn_rank')
-- itself (SCHEMA.sql §1) — nothing else belongs here. docs/SCHEMA.sql stays the 0001 baseline byte for byte (test_db.py).
ALTER TABLE words ADD COLUMN learn_rank INTEGER;  -- closed·10^7 + rank·100 + sub (learn_order.py); smaller = earlier; NULL = not computed (sorts last in its group)
```
Measured on the live-size copy: 0.4 ms; `page_count` unchanged; first fill `UPDATE` of 9,618 rows 16 ms; `updated_at` untouched
(16 distinct values before and after). Nothing is cleared in `kv` (unlike 0011): the fill comes from the code path that owns the data.

### 2.3 The ORDER BY sites

| # | file:line (at `cd3df8c`) | today | after |
|---|---|---|---|
| 1 | `backend/wd/routers/vocab.py:75-82` `_ORDER`; `vocab()` :114-121 (COUNT :117, SELECT :118-121) | `"freq": "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` · `"difficulty": "COALESCE(w.difficulty + 1, w.stage_min, 6), (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` | `_ORDER` becomes `_order_sql(sort)`: `freq` → `f"{learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL}"`; `difficulty` → `f"COALESCE(w.difficulty + 1, w.stage_min, 6), {learn_order.ORDER_SQL}"`; `alpha` unchanged. `vocab()` adds `params["cur"] = learn_order.default_cur(q.stage)` (the COUNT at :117 may take the same dict — sqlite3 ignores unused names, verified). Comment :78-80 gains "the tail is the learning order (DESIGN §6.3 step 4)". |
| 2 | `backend/wd/services/screen.py:34-36` `_STAGE_DISTANCE`; `screen_next` :57-70 (params :62, ORDER BY :65) | `ORDER BY {_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit` | delete `_STAGE_DISTANCE`; `ORDER BY {learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL} LIMIT :limit`; docstring :3-4 "then frequency" → "then the learning order (`learn_order.ORDER_SQL`)". |
| 3 | `backend/wd/services/batches.py:60-61` `_STAGE_DISTANCE` / `_SCREEN_ORDER` (used :270-273 `select_words`, :691-699 `add_more`) | `f"{_STAGE_DISTANCE}, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"` | `_SCREEN_ORDER = f"{learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL}"`; `_STAGE_DISTANCE` deleted; `from . import learn_order` joins the import at :31. `bank.py:216` docstring mention of `_STAGE_DISTANCE` → `learn_order.stage_distance_sql`. |
| 4 | `backend/wd/ai/prewarm.py:44-55` `candidates` (ORDER BY :52, positional tuple :53); docstrings :5 "by frequency", :45 "most frequent first" | `ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT ?` | `ORDER BY {learn_order.stage_distance_sql()}, {learn_order.ORDER_SQL} LIMIT :limit` with `{"cur": learn_order.default_cur(stage), "limit": max(0, int(limit))}` (named placeholders only — `?` and `:name` cannot mix); docstrings → "in learning order (`learn_order.ORDER_SQL`, API.md 20)". `test_admin_ops.py:488` compares candidate sets — unchanged. |
| 5 | `backend/wd/routers/words.py:104-108` lookup suggestions (ORDER BY :106) | `ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma LIMIT :limit` | `ORDER BY {learn_order.FRQ_TAIL} LIMIT :limit` — **raw frequency, the deliberate exception** (API.md 22 says so; `test_words.py:86-87` stays). |

After this change the literal `frq IS NULL` exists in `backend/wd` only inside `learn_order.py` (grep test, §4.1).

### 2.4 Hooks, triggers, cost

| trigger | where (file:line) | what | measured cost |
|---|---|---|---|
| service start | `backend/wd/main.py:492` — after `seed_check(conn, cfg)`, before the `public_url_guess` block :493: `learn_order.ensure_current(conn)`; import at :68 (`from .services import learn_order`); module docstring pipeline :8-10 | recompute = compare stored vs computed, write changed rows only; never fatal (`learn_order_failed` event) | ≈ 20 ms when nothing changes, ≈ 40 ms first fill (read 7 / compute 14–23 / write 16) |
| seed import | `backend/wd/seed.py:476` — inside the `with db.maybe_tx(conn)` block after `_rebuild_forms(conn, rows, stats)` and before `db.kv_set(conn, "seed_version", digest, …)` :477: `try: lo = learn_order.recompute(conn, now=now, seed_version=digest, trigger="seed_import"); stats.learn_rank_changed = lo.changed  except Exception: log.exception(…, extra={"event": "learn_order_failed"}); INSERT system_events('learn_order_failed'); (import commits, ranks stay as they were)`. `seed_version=digest` is passed because `kv.seed_version` is written one statement later. | ranks and `seed_version` land in one transaction (`test_import_is_atomic` gains an assertion); compute-phase failure is fail-soft, a write-phase `sqlite3.Error` propagates (DB fault, the import rolls back as today) | +≈ 40 ms on a ≈ 0.5 s import |
| nightly | `backend/wd/jobs/scheduler.py:380` `maintenance`: after the image retries, `try: learn_order.ensure_current(conn, now=to_iso(now), trigger="maintenance") except Exception: log.exception(…)` | self-heal of runtime drift (pos fills, runtime inserts) | ≈ 20 ms/day |
| CLI | `wd learn-order` (§2.5) | operator fill / report / preview | ≈ 40 ms |
| Lighthouse install | `deploy/install.sh:141` — new line after `run "$REPO/.venv/bin/wd" import-seed`: `run "$REPO/.venv/bin/wd" learn-order || echo "WARN: …"   # fills words.learn_rank (0014) before the unit starts; idempotent; refuses below schema 14 like import-seed; the `|| echo WARN` guard (the claude-check precedent) keeps `set -e` from aborting the install between the stop and the systemd steps when stage words stay unranked — the service start is fail-soft for the same condition` | `wd check db` between install and unit start is consistent; `--no-restart` upgrades serve ranked lists | ≈ 40 ms |
| runtime insert | `backend/wd/services/words.py:604-611` `_insert_word`: `params = dict(cols); params.setdefault("learn_rank", learn_order.best_effort_rank(params))`; `_INSERT_WORD_COLUMNS` :592-596 gains `"learn_rank"` (DDL order — ADD COLUMN appends); `_word_defaults` :569-588 unchanged (the rank is computed, not defaulted). Covers `_resolve_ecdict` :667 and `_create_provisional` :703 without change. | exact for natively ranked rows, NULL for provisional rows | < 0.01 ms |
| runtime `pos`/`kind` writers (`ai/lookup.py:317`, `:368`; `ai/consolidate.py:292`; `services/suggestions.py:418`) | **no hook** (decision §7 A7): they only fill NULL `pos` with a Claude label, which `dominant_pos` reads as `None` — the class of a NULL-pos word is already content, so the key does not change; the nightly `ensure_current` covers everything else | — | — |

Not triggers: `wd migrate` alone (install.sh runs `wd learn-order` right after `import-seed`; on the Mac the service start fills),
`wd restore` (the restored file carries its ranks; an older one is filled at the next start).

### 2.5 CLI `wd learn-order` (owned by `wd.services.learn_order`)

`backend/wd/cli.py:31-42` `CLI_MODULES` += `"wd.services.learn_order"`; `:45-56` `COMMAND_OWNERS` += `"wd.services.learn_order": ("learn-order",)`
(`test_cli.py:58` asserts the two key sets are equal). Usage:

* `wd learn-order` — refuse with one line and exit 1 when `db.current_version(conn) < 14` ("run `wd migrate` first", the
  `import-seed` precedent `seed.py:572-579`); else `recompute(trigger="cli")` and print
  `learn order lo-1: 9618 rows, N updated in 0.04 s; 0 stage words unranked` (exit 1 if stage words stay unranked).
* `--dry-run` — writes nothing; prints the **movers report**: per stage `records · rank_changed · moved ≥ 50 places · max shift ·
  first 10 old → first 10 new`, then the 20 biggest climbs and the 20 biggest drops against the stored ranks (positions inside
  the stage's own words under `ORDER_SQL`). The review artefact for every policy tuning iteration.
* `--show STAGE [--top N] [--cur STAGE]` — `position  lemma  learn_rank  closed  how  frq  bnc  eff` of the first N words of
  `stage_min = STAGE` (or, with `--cur`, the tab/筛词 order of that 主攻 stage) — the operator sees why a word sits where it sits.
* `--report PATH` — writes the §2.8 JSON document (`data/seed/learn_order.json` in the release commit) from the ranks the recompute just stored; combined with `--dry-run` or `--show` it is a usage error (exit 2), because the document would describe un-recomputed stored keys under this code's policy stamp.
* `--db PATH` — like `wd check --db` (rehearsal copies, restore drills).
Safe next to the live service: one `BEGIN IMMEDIATE` ≤ 30 ms; readers see old or new ranks (a browsing page boundary may shift
once, as after a seed import).

### 2.6 kv keys and the stats document

| key | value |
|---|---|
| `learn_order.version` | `LEARN_ORDER_VERSION` of the code that last wrote the ranks |
| `learn_order.seed_version` | the `kv.seed_version` digest the ranks were computed for (the seed stamp: an older server importing a seed while the column exists leaves it ≠ `kv.seed_version`) |
| `learn_order.computed_at` | ISO instant |
| `learn_order.stats` | compact JSON (< 2 KB; never the full lists): per stage code (`xs … cet6`, `none`): `n, ranked, from_frq, from_bnc, dealt, set, glued, adverb, interj, closed, p10, p50, p90, first8` + `label_pos_stage_words` (count) + `drift_dealt` (stage rows R3 re-dealt since the last compare — a runtime word or form resolved a phrase token) + `drift_none` (课标外 rows whose stored key ≠ computed); both drift counts are 0 when the stored policy version is not the code's (after a bump every key moves, nothing drifted). Round-tripped through JSON in a unit test. |

### 2.7 `wd check db` (`backend/wd/diag.py`, from schema 14)

* `check_db` :81-112: the kv tuple at :97 gains `"learn_order.version"` and the rendered `kv.learn_order.stats: xs n=600 ranked=533
  dealt=9 … · 课标外 drift 0 · label-pos 0` line — both **before** `"backup.last"` (`test_diag.py:57` requires every line after
  `kv.backup.last` to be an `invariant` line). After the seed-version line (:105-107):
  `if version >= LEARN_ORDER_INVARIANTS_FROM_VERSION: for line, violated in _learn_order_lines(conn): …` (late import of
  `learn_order`, the `_seed_version_line` pattern). `STAGE_INVARIANTS` :50-57 stays untouched (pinned to the PLAN literal).
* The four new lines, exact texts:
  * `invariant learn_rank_present: ok` | `invariant learn_rank_present: N violation(s) (stage words without learn_rank — the next \`wd serve\` start or \`wd learn-order\` fills them)`
  * `invariant learn_order_current: ok` | `… 1 violation(s) (kv.learn_order.version lo-0 ≠ code lo-1; run \`wd learn-order\`)` | `… (computed for seed 24f3b9496c14… ≠ kv.seed_version …; run \`wd learn-order\`)` | `… (never computed; run \`wd learn-order\`)`
  * `invariant learn_rank_matches_policy: ok` | `… N violation(s) (stored learn_rank of stage words differs from learn_order.rank_rows(); run \`wd learn-order\`)` — `learn_order.drift(conn).policy`: stage words placed by the seed-only rules (native, set, glued, adverb, interjection); the R3-dealt stage rows a runtime word or form can re-deal (§2.1) and the 课标外 drift are the informational `dealt drift` / `课标外 drift` counts of the stats line (A8)
  * `invariant calendar_words_in_xs: ok` | `… N violation(s) (month/weekday rows without stage_xs = 1 / stage_min = 1)` — SQL rendered from `MONTHS`/`WEEKDAYS`: counts **present** calendar lemmas that violate; presence of all 19 is asserted by the `full_seed` gate (the mini seed has none)
  Each flips `ok` to FAIL; a failing query — or a raising policy — is reported as `query failed (…)` and not counted (`_invariant_line` rule; `check_lines` never raises). Cost: 0.4 +
  0.01 + ≈ 20 + 0.1 ms. `wd check db` therefore prints **eight** `invariant` lines after an import (4 stage + 4 learning order).
  `__all__` :361 gains `LEARN_ORDER_INVARIANTS_FROM_VERSION`.
* M4's "stage flag set ⇒ `stage_min` not NULL" is already `stage_min_consistent` (`NULL IS NOT 1` is true in SQLite) — no new line;
  WORD_LIBRARY_CURATION §1.6 now points at it.
* M5 protection: `ORDER_CLOSED_POS` is derived from the imported `FUNCTION_POS` (test), the `inherit:` tokens are pinned (mini seed
  `is`; full seed `am is are does`), the two Claude `pos` writers are pinned to "never overwrite a non-empty `pos`"
  (`ai/lookup.py:352-353` `if not word.get("pos")`; `ai/consolidate.py:265-270` skips seed rows) and the stats line counts stage words
  with a label-shaped `pos` (informational — 662 stage words legitimately have NULL `pos` and a lookup merge may fill a label into
  one; a label never changes the ordering class of a NULL-pos word, see §7 A9).

### 2.8 `data/seed/learn_order.json` (committed review artefact, written by `wd learn-order --report`)

```json
{"policy": "lo-1", "seed": "<kv.seed_version = stats.json.content_sha256>", "computed_at": "…", "generated_by": "wd learn-order --report",
 "stages": {"xs": {"n": 600, "ranked": 533, "dealt": 9, "set": 19, "glued": 4, "adverb": 31, "interj": 4, "closed": 75, "p10": …, "p50": …, "p90": …,
                   "first": ["say", "go", … 30 lemmas]}, "zk": {…}, "gk": {…}, "cet4": {…}, "cet6": {…}, "none": {…}},
 "acceptance": {"closed_in_first_30": {"xs": 0, …}, "xs_adverbs_first_30": 2, "xs_months_positions": [243, …], "zk_phrases_first_200": 42, "longest_frq_null_run": {…}}}
```
Regenerated on the full seed at every policy or seed change (release step §6.1 step 0e) and compared by the `full_seed` gate
(§4.3: `policy == LEARN_ORDER_VERSION`, `seed == stats.json.content_sha256`, `first[:8]` per stage equals the DB order).

### 2.9 Rehearsal `scripts/rehearse_migration.py`

* Imports :50-52 `from wd.services import learn_order`; constants :54-58 unchanged (`EXPECTED_TABLE_COUNT = 25`; the words index set
  pinned at :215 is a superset check — nothing added).
* `snapshot()` :129-158: `"has_learn_rank": has_column(conn, "words", "learn_rank")`, and when present `"learn_rank_nonnull"`.
* New `check_0014(rep, conn, before, ran_here)` after `check_0013` (:272-289), modelled on `check_0012` (:254-269):
  1. `words.learn_rank` exists, `type == 'INTEGER'`, `notnull == 0`, `dflt_value is None`; no `ix_words_learn_rank` (index set unchanged);
  2. `words` and `v_bank` row counts unchanged (no rebuild); when `ran_here`: `SUM(learn_rank IS NOT NULL) == 0` right after the file;
  3. **recompute on the copy**: `r = learn_order.recompute(conn, trigger="rehearsal")`; `unranked_stage_words(conn) == 0`;
     `kv.learn_order.version == LEARN_ORDER_VERSION`; `stale_count(conn) == 0`; a second recompute changes 0 rows; `MAX(updated_at)`
     unchanged; every stage's first 30 has 0 FACTS-closed words (the §1.6 counts, computed here);
  4. `rep.info("小学 order (first 15)", …)` and `rep.info("初中新增 order (first 15)", …)` from `learn_order.show(conn, "xs"|"zk", 15)` and
     the per-stage summary block (`n · ranked · dealt · closed · first 8`) — the operator sees the order before touching production;
  5. probe: `UPDATE words SET learn_rank = NULL WHERE id = ?` accepted inside BEGIN…ROLLBACK (NULL is a legal state).
* Dispatch :363-376: `if 14 in recorded: check_0014(rep, conn, before, ran_here=14 in applied_versions) else: rep.skip("0014 checks", …)`;
  `check_invariants` :291-299 additionally prints the four learning-order lines through `learn_order.check_lines(conn)` so script and
  `wd check db` cannot drift. Docstring :16-31: one 0014 bullet. `check_empty_database` passes unchanged (0001 → 0014, 25 tables + v_bank).

---

## §3 Work items — four parallel lanes

All lanes code against the §2.1 signatures; Lane A delivers the module's pure half first (half a day), the other lanes stub it
until then. Nothing below changes `docs/SCHEMA.sql`, `schemas.py`'s `VocabSort`, `types.ts`, `check_contract.py`, the seed file or
the builder. One commit for A+B+C (backend, restart-only) and one for D's label (needs a frontend snapshot) — both in one release.

### Lane A — the policy (pure)

| file | work |
|---|---|
| `backend/wd/services/learn_order.py` (new) | §1.2 constants; `WordInput.from_row`; `inherit_head`, `native_rank`, `closed_class`, `pack`; `rank_rows` (§1.3 incl. R3 token resolution through `word_forms`, M1 median anchor + fallback, M2 glue, M3/G5 dealing); `best_effort_rank`; `stage_distance`, `stage_distance_sql`, `default_cur`; `ORDER_SQL`, `FRQ_TAIL`, `order_sql`; compact `stats` builder; module docstring stating the group-ripple rule |
| `backend/tests/unit/test_learn_order.py` (new) | §4.1 items 1–12 (golden table + digest, totality matrix, dealing formula, sets, glue, adverbs/interjections, constants pinned to `FUNCTION_POS`, packing bounds, stage distance NULL → 11, `best_effort_rank` ≡ `rank_rows` for natively ranked rows, no `hash(`) |

Acceptance: `.venv/bin/python -m pytest backend/tests/unit/test_learn_order.py -q`; `rank_rows` over the mini seed imported into a fresh
DB reproduces the §4.1 golden digest `8ba429d756f62e54a58a5aa11561eb702fd73511a28f64106eb00f5597aa91ef`.

### Lane B — persistence, hooks, operations

| file | work |
|---|---|
| `backend/wd/migrations/0014_learn_rank.sql` (new) | §2.2 verbatim |
| `backend/wd/services/learn_order.py` (DB half) | `load_inputs`, `recompute` (write changed rows only, kv keys, event), `ensure_current` (never raises), `is_current`, `stale_count`, `unranked_stage_words`, `check_lines`, `stats_line`, `show`, `report`, movers report, `register_cli` |
| `backend/wd/main.py` | :68 import; :492 `learn_order.ensure_current(conn)` after `seed_check`; docstring :8-10 |
| `backend/wd/seed.py` | :56-60 import; `SeedStats` :132-161 `learn_rank_changed: int = 0`; :476 the guarded `recompute(… trigger="seed_import")`; event detail :479-500 `"learn_order": {"version", "changed"}`; `format_stats` :548-552 `, N learn ranks changed`; module docstring :28-31 bullet ("`learn_rank` is recomputed for every row inside the same transaction; a dry run computes nothing; a seed change may re-rank frequency-less words of the touched stages, `updated_at` never moves") |
| `backend/wd/services/words.py` | `_INSERT_WORD_COLUMNS` :592-596 + `"learn_rank"`; `_insert_word` :604-611 `setdefault("learn_rank", learn_order.best_effort_rank(params))`; import at :26 |
| `backend/wd/jobs/scheduler.py` | `maintenance` :380 nightly `ensure_current` (guarded) |
| `backend/wd/diag.py` | §2.7: kv lines, `_learn_order_lines`, `LEARN_ORDER_INVARIANTS_FROM_VERSION`, `__all__` |
| `backend/wd/cli.py` | :31-42 / :45-56 registry entries |
| `scripts/rehearse_migration.py` | §2.9 |
| `deploy/install.sh` | :141 `wd learn-order` line; `backend/tests/unit/test_deploy_files.py:253` needle `"/.venv/bin/wd learn-order"` (Linux-only test) |
| tests | `test_db_0014.py` (new), `test_main_learn_order.py` (new), `test_seed.py` additions (ripple, atomic, dry-run, event, fail-soft), `test_diag.py` (eight names, each new line), `test_cli.py` (`learn-order` flags, exit codes), `test_scheduler*.py` (maintenance calls `ensure_current`), `test_words_resolve.py` (inserted ECDICT row carries `best_effort_rank`; provisional row NULL) — §4.1 items 13–22, §4.2 |

Acceptance: `.venv/bin/python -m pytest backend/tests/unit/test_db_0014.py backend/tests/unit/test_main_learn_order.py backend/tests/unit/test_seed.py backend/tests/unit/test_diag.py backend/tests/unit/test_cli.py backend/tests/unit/test_words_resolve.py -q`;
`.venv/bin/python -I scripts/rehearse_migration.py <VACUUM INTO copy of the live DB>` exits 0 with `check_0014` ok and the 小学/初中 head printed;
`WD_DATA_DIR=<copy> .venv/bin/wd check db` prints eight `invariant …: ok` lines.

### Lane C — the five sites and the pinned tests

| file | work |
|---|---|
| `backend/wd/routers/vocab.py` | §2.3 #1 (`_order_sql`, `params["cur"]`) |
| `backend/wd/services/screen.py` | §2.3 #2 (delete `_STAGE_DISTANCE`) |
| `backend/wd/services/batches.py` | §2.3 #3 (delete `_STAGE_DISTANCE`, `_SCREEN_ORDER` from `learn_order`); `bank.py:216` docstring |
| `backend/wd/ai/prewarm.py` | §2.3 #4 (named params) |
| `backend/wd/routers/words.py` | §2.3 #5 (`FRQ_TAIL`) |
| `backend/tests/helpers/reference_order.py` (new; or in `conftest.py`) | `reference_order(settings, where_sql, *, cur=None, params=()) -> list[str]`: opens `db.connect(settings.db_path)`, reads the rows, returns lemmas sorted by `(stage_distance(stage_min, cur) if cur is not None, learn_rank IS NULL, learn_rank, frq IS NULL or 0, frq, lemma)` from the **stored** column (so the tests pin the mechanism, never a policy literal) |
| `backend/tests/integration/test_vocab.py`, `test_screen.py`, `backend/tests/unit/test_batches.py`, `backend/tests/integration/test_words.py` | §4.2 rewrites |
| `backend/tests/unit/test_learn_order.py` (shared with A) | differential test "SQL `ORDER BY …` == `sorted(rows, key=…)`" for 全部 (cur 1), each stage flag, the `_STAGE_DISTANCE`-prefixed 筛词 form, the difficulty form; grep test `frq IS NULL` only in `learn_order.py` |

Acceptance: `.venv/bin/python -m pytest backend/tests/integration/test_vocab.py backend/tests/integration/test_screen.py backend/tests/unit/test_batches.py backend/tests/integration/test_words.py backend/tests/integration/test_admin_ops.py backend/tests/unit/test_learn_order.py -q`;
`grep -rn "frq IS NULL" backend/wd | grep -v services/learn_order.py` prints nothing.

### Lane D — docs, copy, release, acceptance gate

| file | work |
|---|---|
| `frontend/src/i18n/zh.ts:48` + `docs/FRONTEND.md:254` | `sort: { freq: '学习顺序', alpha: '字母', difficulty: '难度' }` (byte-identical mirror; `npm run lint` = `scripts/check-copy.mjs`); `VocabPage.test.tsx` reads keys — no change |
| docs (§5) | API.md 20 / 22 / 31; DESIGN §3.2 / §6.2 / §6.3; FRONTEND §5.5; CLAUDE_INTEGRATION :303; WORD_LIBRARY_CURATION :150 / :296 / §1.5; DEPLOY §5 / §9 / §10; ops.md :19 / :117-123; TASKS.md :172; k12 release note :212-213; PLAN §9.2 #5; QUICK_DEPLOY_AND_MOBILE :156 (`wd check db` 八条); new `docs/releases/2026-11-learn-order.md` |
| `backend/tests/unit/test_docs_contract.py` | pins of §4.1 item 23 |
| `data/seed/learn_order.json` (new) | generated by `wd learn-order --report` on the rehearsal copy of the full seed (§6.1 step 0e) |
| `backend/tests/unit/test_seed.py::test_full_seed_acceptance_numbers`, `backend/tests/integration/test_vocab.py::test_cet6_new_only_on_the_full_seed` | §4.3 full_seed additions |

Acceptance: `.venv/bin/python -m pytest backend/tests/unit/test_docs_contract.py -q`; `cd frontend && npm run lint && npm run typecheck && npx vitest run`;
`WD_FULL_SEED_DB=<copy> .venv/bin/python -m pytest backend/tests -m full_seed -q`.

Follow-ups deliberately **outside** this change (tracked in the release note §"未决"): G8 as a seed-builder data rule (a British
spelling inherits its American twin's `frq`: colour←color, favourite←favorite, grey←gray, honour, centre, programme, realise,
theatre, labour, defence, licence, cheque …; deterministic, constant-free, changes the seed content sha → separate seed release);
the `mr.`/`mrs.` builder-side `frq` patch (purist §6 #8); a curated 第一课 starter list (concreteness) only after the first
Grade-3+ pupils' feedback; G10 (50 % window for grammar words at stages ≥ 初中) only if 中考 testers report grammar words too late.

---

## §4 Tests

### 4.1 New tests (file::name → expectation)

`backend/tests/unit/test_learn_order.py`
1. `test_constants_are_derived_from_the_image_gate_and_the_enum` — `ORDER_CLOSED_POS == style.FUNCTION_POS - {"u"}` (and `ORDER_CLOSED_POS | {"u"} == FUNCTION_POS`), `CLOSED_LEMMAS` is the 16-lemma set of §1.2, `MONTHS`/`WEEKDAYS` the calendar lists, `STAGE_NULL_DISTANCE == 2 * len(STAGE_ORDER) + 1 == 11`.
2. `test_golden_table_lo_1` — import the mini seed into a fresh migrated DB (`db.run_migrations` + `import_seed`), `rank_rows(*load_inputs(conn))`; the 62 `(lemma, learn_rank)` pairs equal the table below and `sha256(json.dumps(sorted pairs, ensure_ascii=False, separators=(",", ":")))` == `8ba429d756f62e54a58a5aa11561eb702fd73511a28f64106eb00f5597aa91ef`; a comment names `LEARN_ORDER_VERSION = "lo-1"` — editing the policy without bumping the version fails here (mechanism must-fix).
3. `test_rank_rows_is_total` — parametrised garbage matrix on `WordInput.from_row` / `rank_rows`: `None` everywhere, `frq="12"`, `frq="x"`, `frq=-5`, `frq=0`, `bnc=b"7"`, `pos="v./n."`, `pos="n:x/v:1"`, `pos=""`, `stage_min=99`, `stage_min="2"`, `sources=None`, `sources="inherit:"`, `lemma` with hyphen/space → an `int` or `None`, never an exception; a label-shaped `pos` is a content word; `stage_min=99` lands in the 课标外 group.
4. `test_dealing_formula` — `n_r=10, n_u=4` → hosts 2 4 7 9 (`ceil((k−½)·10/4)`); `n_u > n_r` shares hosts; `n_r=0` → NULL; a dealt word sorts after its host and before the next host (`sub 20`); unranked order by `(token_rank IS NULL, token_rank, lemma)` with `word_forms` resolution (`be located → locate`, ambiguous form skipped, self-reference skipped).
5. `test_calendar_sets` — twelve months with mixed ranks (incl. a NULL) take the `median_low` anchor and `sub 21..32` in calendar order; `may` with `pos='v:100'` is never closed; weekdays `33..39`; the no-rank fallback deals them in calendar order and keeps the subs.
6. `test_glued_forms` — `is`/`am`/`are` with `inherit:be` → `key(be) + 3/1/2`; a form whose head is absent is closed via R1c and ranked on its own; a glued row's own `bnc` is ignored.
7. `test_adverbs_and_interjections_are_dealt` — adverbs keep frequency order among themselves, `sub 40`; interjections `sub 50`; both land on hosts of their `(stage_min, closed)` group; a closed-list adverb-tagged lemma (e.g. `may`-like edge) follows R1b.
8. `test_packing_bounds_and_order` — `pack(True, 46049, 99) < 2 * CLOSED_BASE`, `pack(False, r, s)` monotone in `(r, s)`, `pack(False, 46049, 99) < pack(True, 1, 0)`.
9. `test_stage_distance_and_sql` — `stage_distance(None, 1) == 11`, the table of §1.3 M4 for `cur ∈ 1..5`; `stage_distance_sql()` evaluated by SQLite over `stage_min ∈ {NULL, 1..5}` equals the Python twin; `default_cur("all") == 1`, `default_cur("zk") == 2`.
10. `test_best_effort_rank_equals_rank_rows_for_natively_ranked_rows` — for every mini-seed row with `how == 'native'`, `best_effort_rank(row) == learn_rank`; for dealt/adverb rows it returns the native-rank key or `None`.
11. `test_sql_order_equals_python_order` (differential, `seeded` fixture after a recompute) — for 全部 (cur 1), each stage flag with its `cur`, the 筛词 form over the `alice` stage set, and the `difficulty` form: `SELECT lemma … ORDER BY <fragment>` == `reference_order(...)`.
12. `test_no_salted_hash_and_one_frq_fragment` — `grep` over `backend/wd`: `"hash("` absent from `learn_order.py`; the literal `frq IS NULL` occurs only in `backend/wd/services/learn_order.py`.
13. `test_recompute_writes_only_changed_rows_never_updated_at_and_is_idempotent` — first run `changed == 62`, second `changed == 0`, `MAX(updated_at)` unchanged, four kv keys set, `learn_order_recomputed` event only when `changed > 0` and `trigger != 'seed_import'`.
14. `test_recompute_joins_an_open_transaction_and_rolls_back_with_it` — inside `db.tx(conn)` then `ROLLBACK` → no ranks, no kv keys.
15. `test_ensure_current_never_raises` — monkeypatch `rank_rows` to raise → returns `None`, `system_events('learn_order_failed')`, lists still serve (fail-soft).
16. `test_seed_stamp_trigger` — write ranks, then simulate an old-code import (`kv_set('seed_version', 'other')`, one row's `frq` changed) → `is_current` is `(False, 'seed …')` and `ensure_current` rewrites that row.
17. `test_stats_round_trip_and_stale_count_scope` — `kv.learn_order.stats` parses back into the stats dict; a hand `UPDATE` of a stage word's key → `stale_count() == 1`; of a 课标外 word → `stale_count() == 0` and `stale_count(stage_only=False) == 1`.
18. `test_show_and_movers_report` — `show(conn, "xs", 5)` rows equal the SQL order; `--dry-run` after a hand edit reports it as a mover.

`backend/tests/unit/test_db_0014.py` (the `test_db_0013.py` pattern)
19. `test_upgrade_0014_adds_a_nullable_column_without_rebuild` — v13 fixture rows → `(14, 'learn_rank')` applied, column `INTEGER` nullable, every existing row NULL, no `ix_words_learn_rank`, table set `== EXPECTED_TABLES`, `v_bank` intact and row-count unchanged, old explicit-column INSERTs (`seed._UPSERT_SQL`, `words._INSERT_WORD_SQL` minus the new column) still succeed, second run applies nothing; fresh path 0001 → 14.
20. `test_null_ranks_fall_back_to_the_pre_0014_order` — migrated, unfilled `seeded` DB: the five sites (vocab 全部/xs, screen, batches selection, prewarm) return exactly the order `ORDER BY (frq IS NULL OR frq = 0), frq, lemma` inside each stage-distance group; after a fill, NULL-ing one row puts it after every ranked row of its group.

`backend/tests/unit/test_main_learn_order.py` (sibling of `test_main_seed_check.py`)
21. `test_startup_fills_ranks_after_the_migration_and_is_a_noop_afterwards` — `main.startup` on a freshly migrated DB → every stage word ranked, `kv.learn_order.version == LEARN_ORDER_VERSION`; a second start writes nothing and no event; a monkeypatched failure never fails startup (`learn_order_failed`).

`backend/tests/unit/test_seed.py` additions
22. `test_changed_record_may_rerank_only_dealt_words_of_its_stage_groups` — move `abandon` to `["zk","gk","cet4","cet6"]` as `test_changed_record_updates_only_that_row` does: `(inserted, updated) == (0, 1)`; `apple` unchanged **including** `learn_rank`; `updated_at` unchanged for every row but `abandon`; the set of rows whose `learn_rank` changed ⊆ rows with `how != 'native'` of the groups `(2, False)`, `(3, False)` (on the fixture: `a.m.`); `stats.learn_rank_changed` equals that count + 1. Also: `test_import_is_atomic` asserts no ranks and no `learn_order.*` kv after the rollback; `test_dry_run_writes_nothing` asserts ranks untouched; `test_seed_import_event_carries_learn_order_detail`; `test_policy_failure_does_not_roll_the_import_back` (monkeypatched `rank_rows` raising → import commits, `learn_order_failed` event, ranks NULL).

`backend/tests/unit/test_docs_contract.py`
23. `test_docs_quote_the_learning_order` — API.md 20 and DESIGN §6.3 step 4 contain `learn_order.ORDER_SQL` with the `w.` prefix stripped; API.md 22 contains the sentence "suggestions keep raw frequency"; API.md 31 no longer says "by frequency"; DEPLOY §9 lists `learn-order`; ops.md and TASKS.md name the eight invariant names in `diag` order; WORD_LIBRARY_CURATION §1.6 mentions `learn_rank` and `wd learn-order`; CLAUDE_INTEGRATION :303 mentions `learn_rank`; FRONTEND §8 mirror still byte-identical to `zh.ts` (existing test).

`backend/tests/unit/test_diag.py`, `test_cli.py`, `test_scheduler*.py`, `test_words_resolve.py`
24. `test_diag`: `INVARIANT_NAMES` → `("stage_min_consistent", "xs_subset_zk", "stages_json_known", "seed_version_matches_file", "learn_rank_present", "learn_order_current", "learn_rank_matches_policy", "calendar_words_in_xs")`; happy path eight `ok`; one test per new line (NULL a stage rank · `kv.learn_order.version = 'lo-0'` · hand-UPDATE a stage key · a month row with `stage_xs = 0` inserted); the stats line appears before `kv.backup.last`; a v13 database prints none of the four (extend `test_check_db_has_no_stage_invariants_before_schema_0011` with a 13-version variant); exit-code test `count == 8`.
25. `test_cli`: `learn-order` registered with `--dry-run / --show / --top / --cur / --report / --db`; refuses below schema 14 with exit 1; exit 0 after a fill.
26. `test_scheduler`: `maintenance` calls `learn_order.ensure_current` once per day and survives its exception.
27. `test_words_resolve`: extend `test_ordinary_ecdict_row_is_public_valid_and_enqueues_nothing` (:271) — the inserted row's `learn_rank == best_effort_rank(row)`, non-NULL; extend `test_unknown_string_becomes_a_private_provisional_word…` (:131) — `learn_rank IS NULL`.

**Golden table for item 2** (mini seed, `lo-1`; `how` is informational): `go 3500 · take 6300 · good 11000 · child 11500 · run 20200 ·
water 22600 · email 22620 (dealt) · study 24000 · book 24100 · house 25700 · person 34500 · teacher 37100 · better 45200 · decide 45600 ·
receive 49700 · base 53600 · a.m. 53620 (dealt) · data 55900 · recent 56700 · computer 58900 · bank 66300 · color 69700 · tv 73000 ·
happy 74700 · dog 75300 · ability 78300 · analysis 81100 · glass 82000 · ice cream 82020 (dealt) · mountain 124000 · basis 130700 ·
clothes 143400 · cat 177500 · aids 179300 · abandon 218200 · absence 252400 · negotiate 254100 · apple 269500 · absorb 312000 ·
absolute 316500 · running 325200 · abstract 400700 · axis 559800 · absolutely 559840 (adverb) · absurd 590100 · abundant 622300 ·
receipt 651700 · abolish 749000 · china 794600 · abnormal 824100 · absorption 859600 · ought to 859620 (dealt) · abrupt 870300 ·
bookshelf 1117000 · ax 1132200 · axe 1138800 · be 10000200 · is 10000201 (glued:be) · a 10000500 · an 10003000 · some 10006000 ·
aboard 10498400` (62 rows; `mini_seed_golden.json` in the simulation directory holds the same table as JSON).

### 4.2 Pinned tests to change (file::name → new expectation)

| test | today | new expectation |
|---|---|---|
| `integration/test_vocab.py::test_vocab_default_is_everything_sorted_by_frequency` (:93-109) | first lemma `be`; `frq` ascending; page 2 ends with `frq None` | renamed `…_in_learning_order`: the 62 lemmas of pages 1+2 equal `reference_order(settings, "is_public = 1 AND merged_into_word_id IS NULL", cur=1)`; the last item is the 课标外 word `bookshelf` (`stages == []`, `stage_min None`, distance 11); the `WordBrief` key set is unchanged (`learn_rank` is not exposed). Under `lo-1` the helper yields `take good child run water email study book house teacher …` — informative, never pinned. |
| `::test_vocab_sort_alpha_and_difficulty` (:163-181) | `sort_key` tail `(frq is None or 0, frq, lemma)` | the chain `absorption < abandon < absolutely < ought to < bookshelf` and `bookshelf` last stay (they depend on `difficulty + 1` / `stage_min` only); the within-tier key becomes `(learn_rank is None, learn_rank, frq is None or 0, frq, lemma)` with `learn_rank` read per lemma from the DB; determinism assertion stays; the `stage=zk` variant likewise. |
| `integration/test_screen.py::test_next_order_and_remaining` (:122-139) | `lemmas[:3] == ["absorption", "axe", "ought to"]`; zk `["go", "person", "better"]` | both equal `reference_order(settings, <the candidate WHERE of each call>, cur=5 / cur=2)[:3]`; comments stop citing frq numbers (under `lo-1`: `absorption, ought to, axe` — `ought to` is dealt onto `absorption`; zk stays `go, person, better`). |
| `::test_next_auto_for_a_primary_school_learner_orders_by_stage_distance` (:142-158) | `expected_xs` via `ORDER BY (frq IS NULL OR frq = 0), frq, lemma` | `expected_xs = reference_order(settings, "stage_xs = 1 AND is_public = 1 AND is_valid_english = 1", cur=1)`; the `distance` lambda gains `11 if m is None`; the `{0, 1, 3}` structure is unchanged. |
| `unit/test_batches.py::test_build_batch_caps_ordering_and_counts` (:104-136, :129) | `screens == ["absolutely", "axis"]` | `screens == reference_order(conn, "<the select_words screens WHERE for cet4>", cur=4)[:2]` (under `lo-1`: `axis, absolutely` — the adverb is dealt after its host). `::test_build_batch_cold_start_puts_screens_first` (:152-164) pins kinds only — unchanged. |
| `integration/test_words.py:86-87` | `frqs == sorted(frqs)` | **unchanged** (suggestions keep `FRQ_TAIL`); add one line asserting the lemmas equal `reference_frq_order(...)`? — not needed; the docs-contract pin of the exception suffices. |
| `unit/test_diag.py` (`INVARIANT_NAMES` :27, "four" :49-57, `count == 4` :199) | four names / four lines | eight names in order (§4.1 item 24); `test_stage_invariant_sql_is_the_plan_literal_rendered_from_the_enum` (:182-190) unchanged (`STAGE_INVARIANTS` untouched, `INVARIANT_NAMES[:3]` still matches). |
| `unit/test_seed.py::test_changed_record_updates_only_that_row` (:283-296), `::test_never_touches_user_data_content_pointers_or_alt_forms` (:323) | whole-row compares via `word()` = `SELECT *` | keep (apple is natively ranked, so its row including `learn_rank` is unchanged — pinned); the new ripple test (item 22) states the rule for dealt words. |
| `unit/test_main_seed_check.py::test_normal_path…` (:30-36) `kinds(conn) == ["seed_imported"]` | one event | unchanged by design (the import-path recompute writes no event) — verify. |
| `unit/test_deploy_files.py:253` (Linux only) | needles incl. `wd import-seed` | add the needle `"/.venv/bin/wd learn-order"`. |

### 4.3 `pytest -m full_seed` additions (read `WD_FULL_SEED_DB`, `data/seed/stats.json`, `data/seed/learn_order.json`)

* `test_seed.py::test_full_seed_acceptance_numbers`: every seed row with `stage_min IS NOT NULL` has `learn_rank IS NOT NULL`;
  `learn_order.stale_count(conn) == 0`; `kv.learn_order.version == LEARN_ORDER_VERSION == report["policy"]`;
  `report["seed"] == stats["content_sha256"] == kv.seed_version`; all 19 calendar lemmas present with `stage_xs = 1`;
  `am is are does` carry `inherit:` tokens; and the §1.6 counts computed from the DB (0 FACTS-closed in every stage's first 30,
  ≤ 2 adverbs in the xs first 30, the 12 months on 12 consecutive positions in calendar order, ≥ 40 词组 in the zk-new first 200,
  longest frq-NULL run ≤ 7 per stage).
* `test_vocab.py::test_cet6_new_only_on_the_full_seed`: `GET /api/vocab?stage=xs` page 1 first 8 lemmas == `report["stages"]["xs"]["first"][:8]`
  and == the DB order; `GET /api/screen/next?stage=xs&count=30` for a fresh user contains 0 FACTS-closed words (checked via the DB
  rows of the returned ids); the existing timing budget stays.

---

## §5 Documentation edits (section → the sentence to replace)

| doc / anchor | replace | with |
|---|---|---|
| `docs/API.md` endpoint 20 (:169) | "`sort=freq\|alpha\|difficulty` (default `freq`: `ORDER BY (frq IS NULL OR frq=0), frq, lemma`; `alpha`: `ORDER BY lemma`; `difficulty`: `ORDER BY COALESCE(difficulty + 1, stage_min, 6), (frq IS NULL OR frq=0), frq, lemma` — …" | "`sort=freq\|alpha\|difficulty` (default `freq`, UI label 学习顺序: `ORDER BY stage_distance(stage_min, cur), learn_rank IS NULL, learn_rank, (frq IS NULL OR frq=0), frq, lemma` — `cur` is the tab's stage index, `1` for `all` (the 小学 course first, 课标外 last: `stage_distance` is DESIGN §6.3 step 4's with NULL → 11), `learn_rank` the derived learning-order key of DESIGN §3.2 (NULL = not computed yet, such rows sort last by frequency); `alpha`: `ORDER BY lemma`; `difficulty`: `ORDER BY COALESCE(difficulty + 1, stage_min, 6), learn_rank IS NULL, learn_rank, (frq IS NULL OR frq=0), frq, lemma` — …" (rest of the sentence unchanged) |
| `docs/API.md` endpoint 22 (:171) | "`suggestions` (≤ 5 prefix matches on `lemma`)" | "`suggestions` (≤ 5 prefix matches on `lemma`; suggestions keep raw frequency — `ORDER BY (frq IS NULL OR frq=0), frq, lemma` — the one list that is autocomplete, not a learning order)" |
| `docs/API.md` endpoint 31 (:187) | "ordered as in DESIGN §6.3 step 4 (`auto` = the user's `stages` with `current_stage` first), by frequency" | "ordered as in DESIGN §6.3 step 4 (`auto` = the user's `stages` with `current_stage` first), then the learning order `learn_rank` (endpoint 20)" |
| `docs/DESIGN.md` §3.2 row `pos, collins, oxford, bnc, frq` (:205) | "`0`/`null` frequency = unknown (sorted last)" | "`0`/`null` frequency = unknown; `frq` (else `bnc`) feeds the derived `learn_rank` and is only the tie-break tail of every list" |
| `docs/DESIGN.md` §3.2 new row after `aliases[]` | — | "`—` \| `learn_rank` \| DERIVED, not in the seed: `services/learn_order.py` ranks every row from `lemma` / `pos` (`dominant_pos`) / `frq` / `bnc` / `sources` / `stage_min` / `word_forms` as a group computation per `(stage_min, closed)` (policy `LEARN_ORDER_VERSION`, docs/analysis/2026-11-06-learn-order/DESIGN.md §1); recomputed inside every import, at every start, nightly and by `wd learn-order` (migration 0014); a seed change may re-rank the frequency-less / dealt words of the touched stages, `updated_at` never moves; NULL sorts last in its stage-distance group" |
| `docs/DESIGN.md` §6.2 last sentence (:350) | "The default stage range and recommendation order therefore always derive from the user's own choice." | "The default stage range and recommendation order therefore always derive from the user's own choice; inside a stage-distance group the order is the derived learning order `learn_rank` (§3.2), not adult corpus frequency." |
| `docs/DESIGN.md` §6.3 step 4 (:364-369) | "ORDER BY stage_distance(w.stage_min, current_stage) ASC, … (w.frq IS NULL OR w.frq=0) ASC, w.frq ASC, w.lemma ASC … where stage_distance(s, cur) = 0 if s==cur, 2*(s-cur)-1 if s>cur, 2*(cur-s) if s<cur" | "ORDER BY stage_distance(w.stage_min, current_stage) ASC, w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq=0) ASC, w.frq ASC, w.lemma ASC   # learn_rank = the derived learning order (§3.2); frq only as the fail-soft tail … where stage_distance(s, cur) = 0 if s==cur, 2*(s-cur)-1 if s>cur, 2*(cur-s) if s<cur, 11 if s is NULL (a row with stage flags but no stage_min sorts LAST, never first)" |
| `docs/FRONTEND.md` §5.5 (:147) | "`GET /api/vocab?stage=&new_only=&q=&status=&sort=&letter=&page=&page_size=50`." | "`GET /api/vocab?stage=&new_only=&q=&status=&sort=&letter=&page=&page_size=50` (default sort 学习顺序 = `sort=freq`, the learning order of API.md 20: the tab's own stage first, grammar words after the content words; 字母; 难度)." |
| `docs/FRONTEND.md` §8 (:254) | `sort: { freq: '词频', alpha: '字母', difficulty: '难度' }` | `sort: { freq: '学习顺序', alpha: '字母', difficulty: '难度' }` (byte-identical to `zh.ts:48`) |
| `docs/CLAUDE_INTEGRATION.md` :303 | "…not yet enqueued, by frequency; `limit` is…" | "…not yet enqueued, in learning order (`words.learn_rank`, the order of 筛词 / 词库, API.md 20 — the cards learners meet first); `limit` is…" |
| `docs/WORD_LIBRARY_CURATION.md` :150 (选词规则 核验 C10) | "按阶段距离 → 词频（frq 为空排最后）→ 字母序。阶段距离按 `stage_min` 计算，一条有阶段标志但 `stage_min` 为空的手工插入行会排在每个用户筛词的**第一位**。所以管理员在服务端插入词条时必须同时给 `stage_*`、`stage_min` 和 `frq`。" | "按阶段距离 → 学习顺序 `learn_rank`（为空排最后）→ 词频 → 字母序。阶段距离按 `stage_min` 计算，`stage_min` 为空的行距离为 11，排在每个用户筛词的**末尾**（不再是第一位；`wd check db` 的 `stage_min_consistent` 会报这种行）；`learn_rank` 由 `services/learn_order.py` 从 `pos`（主词性）、`frq`/`bnc`、`sources`、`stage_min` 派生，服务启动、导种子、每夜维护和 `wd learn-order` 时重算，不能手改。所以管理员在服务端插入词条时必须同时给 `stage_*`、`stage_min`、`frq` 与 `pos`，然后跑 `wd learn-order`（或等下一次启动）。" |
| `docs/WORD_LIBRARY_CURATION.md` C10 row (:296) | "`stage_min` 为空的行排第一" | "`stage_min` 为空的行排最后（距离 11）；`learn_rank` 为空的行在同距离组内排最后" |
| `docs/WORD_LIBRARY_CURATION.md` §1.5 「不能做」 list | — | add "改排序只能改策略版本（`LEARN_ORDER_VERSION`）并重算，不能手改 `learn_rank`（`learn_rank_matches_policy` 会报）" |
| `docs/DEPLOY.md` §5 (:361) additive list | "`0012_word_images_meta.sql` (four `ADD COLUMN`s on `word_images`) is additive" | "`0012_word_images_meta.sql` (four `ADD COLUMN`s on `word_images`) and `0014_learn_rank.sql` (one `ADD COLUMN` on `words`, filled by the service start / `wd learn-order`) are additive" |
| `docs/DEPLOY.md` §9 (:421) | "… `stats` · `check [db\|claude\|smtp\|providers\|all]` · `logs --tail N` [`wd.diag`, WP5]." | "… `stats` · `check [db\|claude\|smtp\|providers\|all]` · `logs --tail N` [`wd.diag`, WP5] · `learn-order [--dry-run] [--show STAGE [--top N] [--cur STAGE]] [--report PATH] [--db PATH]` (recompute / preview / movers report of the learning order `words.learn_rank`; refuses below schema 14 like `import-seed`) [`wd.services.learn_order`]." |
| `docs/DEPLOY.md` §10 (:425) | "(new tables/columns/indexes, e.g. `0008_fk_child_indexes.sql`, `0012_word_images_meta.sql`; …)" | "(new tables/columns/indexes, e.g. `0008_fk_child_indexes.sql`, `0012_word_images_meta.sql`, `0014_learn_rank.sql`; …)" |
| `docs/ops.md` :19 | "`wd check db` also prints the stage-model invariants `stage_min_consistent` / `xs_subset_zk` / `stages_json_known` / `seed_version_matches_file`" | "`wd check db` also prints the stage-model invariants `stage_min_consistent` / `xs_subset_zk` / `stages_json_known` / `seed_version_matches_file` and, from schema 14, the learning-order invariants `learn_rank_present` / `learn_order_current` / `learn_rank_matches_policy` / `calendar_words_in_xs` (one command repairs the first three: `wd learn-order`)" |
| `docs/ops.md` :117-123 | "`0012_word_images_meta.sql` is additive … `wd check db` after the upgrade for the four stage invariants" | "`0012_word_images_meta.sql` and `0014_learn_rank.sql` are additive … `wd check db` after the upgrade for the eight invariants" |
| `docs/TASKS.md` :172 | "`# invariant stage_min_consistent / xs_subset_zk / stages_json_known / seed_version_matches_file: ok`" | "`# invariant stage_min_consistent / xs_subset_zk / stages_json_known / seed_version_matches_file / learn_rank_present / learn_order_current / learn_rank_matches_policy / calendar_words_in_xs: ok`" |
| `docs/releases/2026-11-k12-stages.md` §9 末 (:212-213) | "小学阶段的全部顺序——… **邀请小学生之前必须处理**（PLAN §9.2 #5；候选做法：…）" | "小学阶段的全部顺序：已处理——学习顺序改为派生列 `words.learn_rank`（迁移 0014，`services/learn_order.py`，策略 lo-1），见 `docs/releases/2026-11-learn-order.md`" (keep the rest of the paragraph) |
| `docs/analysis/2026-11-05-stages-regions-images/design/PLAN.md` §9.2 #5 (:755) | "小学页签仍按成人 `frq` 排序（前 15 词几乎全是功能词）；…" | prepend "已解决（2026-11-06，docs/analysis/2026-11-06-learn-order/DESIGN.md）：" |
| `docs/QUICK_DEPLOY_AND_MOBILE.md` :156 | "⑤ `wd check db` 四条不变量 ok" | "⑤ `wd check db` 八条不变量 ok（0014 起含学习顺序四条）" |
| new `docs/releases/2026-11-learn-order.md` | — | what changed (two owner sentences of §0, the §1.5 first 30 copied **from the rehearsal output**, not from this document), the restart-only Mac runbook of §6.1 with the expected log lines, the eight `wd check db` lines, the Lighthouse path, rollback, the 未决 follow-ups of §3 |

---

## §6 Deployment

### 6.1 The Mac (launchd; `D=/Users/sqin/word-dance-data`; agent `com.word-dance.server`) — restart-only

0. **Rehearse on a private copy** (service keeps running; numbered because the release note must carry the lemmas this prints):
   ```sh
   D=/Users/sqin/word-dance-data; M=$(mktemp -d /private/tmp/wd-learn-order-XXXX)
   a. .venv/bin/python -c "import sqlite3; sqlite3.connect('$D/word-dance.db').execute(\"VACUUM INTO '$M/word-dance.db'\")"
   b. git checkout <release sha>            # the editable install already points at backend/; no new dependency
   c. .venv/bin/python -I scripts/rehearse_migration.py $M/word-dance.db
      # expect: pending exactly [(14, 'learn_rank')]; check_0014 ok (column, no index, recompute on the copy: 0 unranked stage words,
      # stale 0, idempotent, updated_at unchanged, 0 closed words in every first 30); [info] 小学 / 初中新增 first 15; exit 0
   d. WD_DATA_DIR=$M .venv/bin/wd learn-order --dry-run     # movers report: every row "changed" (first fill) — read the first-10 lists per stage
      WD_DATA_DIR=$M .venv/bin/wd learn-order              # fill the copy; then: --show xs --top 30 / --show zk --top 30 — eyeball the order
   e. WD_DATA_DIR=$M .venv/bin/wd learn-order --report data/seed/learn_order.json   # the committed artefact (§2.8); git add it
   f. WD_DATA_DIR=$M .venv/bin/wd check db                 # eight `invariant …: ok` lines, kv.learn_order.version lo-1
   g. WD_FULL_SEED_DB=$M/word-dance.db .venv/bin/python -m pytest backend/tests -m full_seed -q
   ```
   Copy the first lemmas of step c/d into the release note; commit `learn_order.json` with the release.
1. **Frontend snapshot** (only because the 学习顺序 label ships; the SPA is API-compatible, so it may go first): the K-12 release note
   §6 steps 1/5 recipe — `SHA=$(git rev-parse --short HEAD); cd frontend && npm ci && npm run build -- --outDir $D/frontend-releases/$SHA.new --emptyOutDir`,
   `mv $D/frontend-releases/$SHA.new $D/frontend-releases/$SHA`, `ln -sfn frontend-releases/$SHA $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"` (BSD `mv` has no `-T` and `mv -f` would move the link INTO the old snapshot directory).
2. **Restart = migrate + fill**: `launchctl kickstart -k gui/$(id -u)/com.word-dance.server`. Startup applies 0014 (pre-migrate
   snapshot `$D/backups/pre-migrate-13-to-14.db.gz`), `seed_check` is a no-op (digest unchanged), `ensure_current` fills 9,618 ranks
   (≈ 40 ms) before the first request. Downtime ≈ the process restart.
3. **Verify**:
   ```sh
   curl --noproxy '*' -fsS http://127.0.0.1:8000/api/health
   grep -E 'applied migration 0014_learn_rank|learn_order_recomputed|learn order|learn_order_failed|MigrationError' ~/Library/Logs/word-dance/word-dance.log | tail
   ls -la $D/backups/pre-migrate-13-to-14.db.gz
   WD_DATA_DIR=$D .venv/bin/wd check db                   # eight ok lines on the live DB
   sqlite3 $D/word-dance.db "SELECT lemma FROM words WHERE stage_min = 1 ORDER BY learn_rank IS NULL, learn_rank, (frq IS NULL OR frq = 0), frq, lemma LIMIT 8"
   #   → the first 8 of data/seed/learn_order.json stages.xs.first (rehearsal: say go get make know one time year)
   sqlite3 $D/word-dance.db "SELECT COUNT(*) FROM words WHERE stage_min IS NOT NULL AND learn_rank IS NULL"      # 0
   # HTTP as a logged-in user: GET /api/vocab?stage=xs → items[0..7].lemma equal the SQL above; GET /api/vocab (全部) starts the same;
   # GET /api/screen/next?stage=xs&count=30 → no article / pronoun / preposition; the 词库 sort chip reads 学习顺序.
   ```
   Live effect: batches already built keep their materialised `push_items`; the next nightly build and every 筛词 page use the new
   order; words already graded stay graded (`NOT EXISTS user_words`).

### 6.2 Lighthouse (systemd, `deploy/install.sh`)

Rehearse on the box the same way (step 0a–0f; `rehearse_migration.py` is portable, SQLite ≥ 3.26). Then `git pull && deploy/install.sh`:
stop → publish snapshot → `wd migrate` (0014) → `wd import-seed` (no-op) → **`wd learn-order`** (new line, fills before the unit
starts) → start. `--no-restart` is allowed for this release (additive) but leaves the old process serving frq until restarted.
Afterwards `wd check db` (eight lines) — add it to `docs/QUICK_DEPLOY_AND_MOBILE.md`. A database copied from the Mac after the Mac
deployment already carries ranks and stamps: nothing happens on the VPS beyond the startup compare.

### 6.3 Rollback

* **Code-only (the normal case)**: `git checkout cd3df8c && launchctl kickstart -k gui/$(id -u)/com.word-dance.server` (+ re-point
  `$D/frontend` at `frontend-releases/cd3df8c` if the label shipped: `ln -sfn frontend-releases/cd3df8c $D/frontend.tmp && python3 -c "import os; os.rename('$D/frontend.tmp','$D/frontend')"`). Old code ignores `learn_rank` (every `INSERT INTO words` names
  its columns; readers are `sqlite3.Row` by name; `v_bank` names its `words` columns); lists return to the frq order at once; the column
  and kv keys stay and are harmless. Verified by the seed-carried judge's rollback run and the 0014 header's reasoning.
* **Policy-only**: edit `rank_rows`, bump `LEARN_ORDER_VERSION`, update the golden digest + `learn_order.json`, restart (≈ 40 ms recompute).
* **Full snapshot** (only if the file itself must go back): `launchctl bootout …; wd restore $D/backups/pre-migrate-13-to-14.db.gz --yes;
  git checkout cd3df8c; launchctl bootstrap …` — loses the learning records since the snapshot; not recommended for an additive migration.

---

## §7 Assumptions taken on the owner's behalf (with the cost of reversing each)

| # | decision | reversal cost |
|---|---|---|
| A1 | **G5 adopted**: interjections leave the ordering closed class and are dealt evenly (`yes` 64, `hi` 191, `hello` 329, `goodbye` 463; CET-4 `oh` 854). The order gate `ORDER_CLOSED_POS` therefore differs from the image gate `FUNCTION_POS` by `{u}` — the one derived constant the purist author reserved. | one constant (`ORDER_CLOSED_POS = FUNCTION_POS`), version bump, golden digest + `learn_order.json`, restart |
| A2 | **G6 extended to every 词库 tab**: `sort=freq` orders by the tab's stage distance first (全部 → `cur = 1`, ≡ `COALESCE(stage_min, 6)`; 初中 tab → 初中新增 first, 小学 words at 1,950). The judge adopted the no-stage form only; stage tabs reading like the 筛词 stream of that 主攻 stage is this plan's addition. | drop the prefix for stage tabs in `_order_sql` (one line) |
| A3 | **M7 by rename**: the wire value stays `freq`, the label becomes 学习顺序 (`zh.ts` + FRONTEND §8 mirror). No fourth `learn` sort. | adding `learn` later touches `VocabSort` TS↔Pydantic, `check_contract`, `VocabPage`, API.md §9/§20, FRONTEND §8 (≈ 8 files) |
| A4 | **Lookup suggestions keep raw frequency** (`FRQ_TAIL`), recorded in API.md 22. | one line in `routers/words.py`, one sentence, `test_words.py:86-87` to the reference form |
| A5 | Purist knobs as recommended: `have`/`do` stay closed; `like` 喜欢 (575), `front`/`near`/`behind` in the closed block accepted as a data question (ECDICT share override later); binary demotion (G10) kept; 课标外 words dealt too; `word_forms` token resolution kept. | each one constant or one rule + version bump |
| A6 | **No index** on `learn_rank` (0014 = one `ADD COLUMN`); measured: no plan uses it, the NULL probe is a 0.4 ms scan. | additive `0015` `CREATE INDEX`, 2 ms |
| A7 | **Nightly self-heal instead of per-site refresh hooks** after the four runtime `pos`/`kind` writers (they only fill NULL `pos`, which cannot change the class). | four one-liners `learn_order.refresh(conn, word_id)` + a `refresh` function |
| A8 | **`learn_rank_matches_policy` covers the stage words placed by seed-only rules** (`Drift.policy`); the R3-dealt stage rows a runtime word or form can re-deal (§2.1, review F-1) and the 课标外 drift are informational counts (`dealt drift` / `课标外 drift` in the stats line). | `drift(conn).stage` or `.total` in the invariant (one attribute) — then `wd check db` may FAIL transiently after a user looks up a word that resolves a stage phrase's token (`sooner`, `york`: 2–341 初中 keys) |
| A9 | **No FAIL-flipping `pos` invariant** (M5's first option): 662 stage words have NULL `pos` and a lookup merge may legitimately fill a Claude label into one without changing its class; protection = `FUNCTION_POS` import pin, `inherit:` pins, writer tests ("never overwrite a non-empty `pos`"), informational label count. | add `pos_share_shaped` as a fifth line (≈ 15 lines) and accept false alarms, or scope it to closed-relevant rows |
| A10 | **`ensure_current` always runs the stored-vs-computed compare** at start and nightly (≈ 20 ms) instead of trusting version / seed stamps (ops must-fix 1); the stamps remain for the `learn_order_current` line and events. | gate on `is_current` first (saves 20 ms per start) |
| A11 | **`data/seed/learn_order.json` is committed** (review artefact + `full_seed` expectations; regenerated on every policy/seed change by `wd learn-order --report` in the rehearsal). | delete the file and three asserts; keep the golden digest |
| A12 | **Group dealing kept, no crc32 spread** (§2.1 reasoning); runtime rows: exact key for natively ranked rows, NULL / native-key approximation for frequency-less / adverb rows until the next recompute. | swap `deal()` for a crc32 spread = a policy change (version bump) that loses "easiest 词组 first" |
| A13 | Tie-break at equal key: COCA-ranked before BNC-rescued (the `frq` tail), then lemma — this is where the plan's positions differ from the judge's tuple key by a few places (`an`/`by` at 554/555, months 243–254 instead of 241–252 because G5 moved `yes` and `hi` ahead). | none needed; a pure-lemma tie-break would mean dropping the fail-soft tail |
| A14 | `calendar_words_in_xs` checks the **present** calendar rows (the mini seed has none); presence of all 19 is a `full_seed` assertion. | make the invariant count missing lemmas too (then the mini seed needs the 19 rows) |
| A15 | **G8 (British spellings inherit the American twin's `frq`)**, the `mr.`/`mrs.` patch and any starter list are seed-builder follow-ups, not part of this change (they change the seed content sha). | separate seed release; no code change |
| A16 | `wd learn-order` is added to `deploy/install.sh` after `import-seed` (ops must-fix 3) and to the Linux-only needle test. | remove the line (the service start fills anyway) |
| A17 | Backend commit and label commit are deployed in **one window** (snapshot first, then restart); the backend alone is restart-only and may ship first if the frontend build is not at hand. | none — either order works |
| A18 | `STAGE_NULL_DISTANCE = 2 · len(STAGE_ORDER) + 1 = 11`, derived, so a sixth stage keeps NULL beyond every stage. | none |
| A19 | The sub-key layout (0 / 1–19 / 20 / 21–32 / 33–39 / 40 / 50) is encoding, not policy; it preserves "native before glued before dealt before sets before adverbs before interjections" at an equal rank. | renumber + version bump |
| A20 | `kind` is not an input (M1 by lemma, G5 by `pos`); a future `phrase_rank` override would be a new column, not a `kind` rule. | — |

---

## §8 Acceptance checklist (gates, in order)

1. **Backend**: `.venv/bin/python -m pytest backend/tests -q` — green on the Mac except the known Linux-only `test_deploy_files.py` /
   `test_config.py::test_defaults_without_environment`; `test_learn_order.py::test_golden_table_lo_1` reproduces digest
   `8ba429d756f62e54a58a5aa11561eb702fd73511a28f64106eb00f5597aa91ef`; `grep -rn "frq IS NULL" backend/wd` hits only `services/learn_order.py`.
2. **Contract**: `.venv/bin/python scripts/check_contract.py` exits 0 (no TS↔Pydantic change expected: `VocabSort` untouched).
3. **Frontend** (label commit): `cd frontend && npm run lint && npm run typecheck && npx vitest run && npm run build`
   (= the frontend part of `make test`); FRONTEND §8 byte-identical to `zh.ts`.
4. **Rehearsal**: `.venv/bin/python -I scripts/rehearse_migration.py <VACUUM INTO copy>` exits 0 — pending exactly `(14, 'learn_rank')`,
   `check_0014` ok incl. the recompute on the copy, the 小学 / 初中新增 heads printed and copied into `docs/releases/2026-11-learn-order.md`.
5. **Full seed**: `WD_FULL_SEED_DB=<filled copy> .venv/bin/python -m pytest backend/tests -m full_seed -q` — every stage word ranked,
   `stale_count == 0`, policy/seed stamps match `learn_order.json` / `stats.json`, 0 closed words in every stage's first 30, ≤ 2 adverbs
   in the 小学 first 30, 12 contiguous months, ≥ 40 词组 in the 初中 first 200, frq-NULL runs ≤ 7, `GET /api/vocab?stage=xs` page 1
   matches the DB order.
6. **`wd check db`** on the copy and, after the restart, on the live database: eight `invariant …: ok` lines, `kv.learn_order.version: lo-1`,
   the `kv.learn_order.stats` line before `kv.backup.last`.
7. **`make smoke`** (scripts/smoke.py, throwaway instance, fake providers) passes with the new startup step.
8. **Live verification** of §6.1 step 3: health ok, `applied migration 0014_learn_rank` and `learn_order_recomputed` in the log,
   `pre-migrate-13-to-14.db.gz` present, the SQL head equals `learn_order.json`, 筛词 for a fresh 小学 user shows no grammar word in 30
   cards, the 词库 sort chip reads 学习顺序.
