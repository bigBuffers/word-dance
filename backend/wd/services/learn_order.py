"""Learning order (学习顺序): the derived ``words.learn_rank`` key — DESIGN §3.2 ("learn_rank") / §6.3 step 4, API.md 20/31,
migration ``0014_learn_rank.sql`` and docs/analysis/2026-11-06-learn-order/DESIGN.md §1 (the policy, ``LEARN_ORDER_VERSION``).

Every "which word next" list — 词库 ``sort=freq`` (UI 学习顺序), 筛词 (``GET /api/screen/next``), 每日推荐词 (``batches``) and the
admin 预生成 candidates — orders by :data:`ORDER_SQL`: the stored integer ``learn_rank`` first and the pre-0014 frequency tail
:data:`FRQ_TAIL` as the tie-break and as the fail-soft order of a NULL key (the lists then read exactly as before 0014), after the
stage distance of :func:`stage_distance_sql` wherever a 主攻阶段 applies (M4: NULL ``stage_min`` → :data:`STAGE_NULL_DISTANCE`,
beyond every stage). Lookup suggestions alone keep the raw :data:`FRQ_TAIL` (API.md 22: autocomplete ranks by commonness).

The key is DERIVED — never stored in the seed, never edited by hand — by :func:`rank_rows` from the columns the table already
has (``lemma``, ``pos`` read only through :func:`wd.images.style.dominant_pos`, ``frq``, ``bnc``, ``sources``, ``stage_min``) and
the ``word_forms`` table (DESIGN §1.1): the frequency-purist order with four pedagogy grafts.

* R2 rank: ``frq`` if > 0, else ``bnc`` if > 0, else NULL (:func:`native_rank`).
* R1 closed class (:func:`closed_class`): dominant pos in :data:`ORDER_CLOSED_POS` — the image gate ``FUNCTION_POS`` minus the
  interjections (G5) —, one of the 16 :data:`CLOSED_LEMMAS` (articles, primary auxiliaries, modals) or an ``inherit:`` token
  (``am is are does``). Months and weekdays are never closed (M1 precedence: ``may``, ``march``, ``august``). Closed words sort
  after every content word of their stage, in rank order among themselves (binary demotion, G10).
* Classes, tested in this order: ``set`` (lemma in :data:`MONTHS` / :data:`WEEKDAYS`) · ``glued`` (first ``inherit:X`` whose head
  ``X`` is a row and ``X ≠ lemma``) · ``adverb`` (not closed, dominant pos ``r``) · ``interj`` (not closed, ``u``) · ``plain``.
* Groups ``(stage_min, closed)`` over the non-glued rows; inside a group the plain rows with a rank are the *hosts* (``sub`` 0)
  and everything else is placed relative to them with the dealing formula :func:`deal_index`: frequency-less plain rows are
  dealt evenly, rarest resolvable token first (R3 — a token resolves to ``words.lemma`` or to the single word a ``word_forms``
  form points at; the row itself never counts); each calendar set takes the ``median_low`` of its members' ranks as one block in
  calendar order, or is dealt in calendar order when no member has a rank (M1); adverbs and interjections are dealt evenly in
  frequency order (M3 / G5); glued forms take their head's key plus their 1-based position among the head's forms by lemma
  (``be → am 1, are 2, is 3``; ``do → does 1``; M2); a row without any rank keeps NULL and sorts last by the frequency tail (R4).
* Packing (:func:`pack`): ``learn_rank = (CLOSED_BASE if closed else 0) + rank * RANK_SCALE + sub`` with the sub-key layout
  native 0 · glued 1–19 · dealt 20 · months 21–32 · weekdays 33–39 · adverb 40 · interjection 50 (encoding, not policy; A19).

**The group-ripple rule.** The dealing is a group computation: a seed import — or any recompute — may re-rank the frequency-less,
calendar, adverb and interjection rows of every ``(stage_min, closed)`` group it touches, while the key of a natively ranked,
non-dealt word depends on no other row (:func:`best_effort_rank` therefore gives a runtime ECDICT row its exact key at insert
time; a frequency-less or adverb runtime row is NULL or approximate until the next recompute). ``updated_at`` never moves for a
rank change. **What a runtime word or form can move.** R3 resolves phrase tokens against every ``words`` row and every
``word_forms`` row, so a word a learner's lookup created (``kung`` for ``kung fu``, ``sooner`` for ``sooner or later``) or a form
it wrote (``sooner → soon``) can make a token of a frequency-less STAGE phrase resolvable, re-sort that group's unranked rows and
re-deal every dealt row behind it — on the live seed up to a few hundred 初中 keys, one host slot each — until the next recompute
(service start, 03:30 maintenance, ``wd learn-order``). Hosts, calendar sets, adverbs, interjections and glued forms read
seed-managed inputs only (runtime rows carry no stage flags and no ``inherit:`` token), so their keys never drift at runtime.
The ``learn_rank_matches_policy`` invariant therefore counts the stage rows placed by those seed-only rules (:class:`Drift`
``policy``: a hand edit or a stale policy), while re-dealt stage rows and 课标外 drift are the informational ``dealt drift`` /
``课标外 drift`` counts of the stats line. :data:`LEARN_ORDER_VERSION` is bumped whenever :func:`rank_rows` would return a
different key for any input; the two golden digests of ``test_learn_order.py`` (mini seed; synthetic row set exercising every
rule) pin it.

Totality: :meth:`WordInput.from_row` coerces every column (``int()`` under ``try``, ``str()``, a ``stage_min`` outside the enum →
the 课标外 group), :func:`rank_rows` never raises over one row (a row whose inputs make no sense gets ``learn_rank`` NULL and
``how = 'unranked'``) and ``dominant_pos`` is the only reader of ``pos`` (a Claude label such as ``'v./n.'`` is a content word).

This module may import only ``wd.db``, ``wd.clock``, ``wd.schemas``, ``wd.images.style`` and the standard library — never
``wd.services.*`` — so ``seed.py``, ``main.py``, the services, the routers, ``diag.py``, the scheduler and
``scripts/rehearse_migration.py`` import it without a cycle. The pure half (constants, the policy, :func:`load_inputs`) does
no I/O beyond two SELECTs; the DB-writing half (DESIGN §2.1 / §2.5) follows the section marker: :func:`recompute` (the
stored-vs-computed compare IS the staleness test — only changed rows are written, ``updated_at`` never, then the
``kv.learn_order.*`` keys and a ``learn_order_recomputed`` event outside the seed import), :func:`ensure_current` (service start
and nightly maintenance, never raises: ``learn_order_failed`` event), :func:`is_current` / :func:`stale_count` /
:func:`unranked_stage_words` / :func:`check_lines` / :func:`stats_line` (the ``wd check db`` lines of §2.7), :func:`show`,
:func:`report` (the ``data/seed/learn_order.json`` document, §2.8), :func:`drift` (the three-way split behind the invariant and
the stats line) and ``wd learn-order`` (:func:`register_cli`).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from .. import db
from ..clock import now_iso
from ..images.style import FUNCTION_POS, dominant_pos
from ..schemas import STAGE_INDEX, STAGE_ORDER, index_to_stage, stage_to_index

log = logging.getLogger("wd.learn_order")

LEARN_ORDER_VERSION = "lo-1"  # bump whenever rank_rows() would return a different key for any input (golden digest test)
LEARN_ORDER_FROM_VERSION = 14  # schema version carrying words.learn_rank (0014_learn_rank.sql)
KV_VERSION = "learn_order.version"  # LEARN_ORDER_VERSION of the code that last wrote the ranks
KV_SEED = "learn_order.seed_version"  # the kv.seed_version digest the ranks were computed for
KV_STATS = "learn_order.stats"  # compact per-stage JSON (stage_stats + label_pos_stage_words + drift_none)
KV_AT = "learn_order.computed_at"  # ISO instant of the last write

# ------------------------------------------------------------------------------- §1.2 constants (the only curated data)
ORDER_CLOSED_POS: frozenset[str] = FUNCTION_POS - {"u"}  # {i c d p a t}: the image gate minus interjections (G5) — derived, never copied
CLOSED_LEMMAS: frozenset[str] = frozenset(
    {
        "a", "an", "the",  # articles (ECDICT gives `an` no pos)
        "be", "do", "have",  # primary auxiliaries
        "can", "could", "will", "would", "shall", "should", "may", "might", "must", "ought",  # modals
    }
)
MONTHS: tuple[str, ...] = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
WEEKDAYS: tuple[str, ...] = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
CALENDAR_LEMMAS: frozenset[str] = frozenset(MONTHS) | frozenset(WEEKDAYS)
STAGE_NULL_DISTANCE = 2 * len(STAGE_ORDER) + 1  # 11 — beyond every stage, derived from the enum (M4 / A18)
# key packing (encoding constants, not tunables — A19)
CLOSED_BASE, RANK_SCALE = 10_000_000, 100
SUB_NATIVE = 0  # a word's own rank
SUB_GLUED_BASE = 0  # glued form j (1-based among the head's forms sorted by lemma) → head.sub + j (1..19 in practice)
SUB_DEALT = 20  # frequency-less word dealt onto a host (R3)
SUB_MONTH_BASE = 20  # month ordinal 1..12 → 21..32
SUB_WEEKDAY_BASE = 32  # weekday ordinal 1..7 → 33..39
SUB_ADVERB = 40  # adverb dealt onto a host (M3)
SUB_INTERJ = 50  # interjection dealt onto a host (G5)

INPUT_COLUMNS: tuple[str, ...] = ("id", "lemma", "pos", "frq", "bnc", "sources", "stage_min")  # what load_inputs reads (DESIGN §1.1)
FRQ_TAIL = "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"  # the pre-0014 order; lookup suggestions keep it (API.md 22)
ORDER_SQL = f"w.learn_rank IS NULL, w.learn_rank, {FRQ_TAIL}"  # the learning order of every other list (API.md 20/31)

# class and `how` labels of RankRow (how is informational: it says which rule produced the key)
CLS_PLAIN, CLS_SET, CLS_GLUED, CLS_ADVERB, CLS_INTERJ = "plain", "set", "glued", "adverb", "interj"
HOW_NATIVE, HOW_DEALT, HOW_SET, HOW_SET_DEALT, HOW_ADVERB, HOW_INTERJ, HOW_UNRANKED = "native", "dealt", "set", "set-dealt", "adverb", "interj", "unranked"
STATS_NONE = "none"  # the 课标外 column of the per-stage stats (stage_min NULL)

_INHERIT = "inherit:"
_STAGE_INDEXES: frozenset[int] = frozenset(STAGE_INDEX.values())


# ------------------------------------------------------------------------------------------------ SQL fragments (§1.4)
def order_sql(alias: str = "w") -> str:
    """:data:`ORDER_SQL` for another table alias (``order_sql("w") == ORDER_SQL``)."""
    return f"{alias}.learn_rank IS NULL, {alias}.learn_rank, ({alias}.frq IS NULL OR {alias}.frq = 0), {alias}.frq, {alias}.lemma"


def stage_distance_sql(cur: str = ":cur", alias: str = "w") -> str:
    """The M4 ``CASE … END`` of DESIGN §6.3 step 4 with NULL → :data:`STAGE_NULL_DISTANCE`; ``cur`` is the placeholder of the
    主攻阶段 index (``:cur`` — the sites use named parameters; ``?`` and ``:name`` cannot mix in one statement)."""
    s = f"{alias}.stage_min"
    return f"CASE WHEN {s} IS NULL THEN {STAGE_NULL_DISTANCE} WHEN {s} = {cur} THEN 0 WHEN {s} > {cur} THEN 2 * ({s} - {cur}) - 1 ELSE 2 * ({cur} - {s}) END"


def stage_distance(stage_min: int | None, cur: int) -> int:
    """Python twin of :func:`stage_distance_sql`: 0 for the 主攻阶段, odd for higher stages, even for lower ones, 11 for NULL."""
    if stage_min is None:
        return STAGE_NULL_DISTANCE
    if stage_min == cur:
        return 0
    if stage_min > cur:
        return 2 * (stage_min - cur) - 1
    return 2 * (cur - stage_min)


def default_cur(stage: str | None) -> int:
    """A tab / filter stage → its index for the distance prefix; ``"all"`` / ``None`` → the first stage (G6: 全部 starts with the
    小学 course and ends with 课标外, i.e. ``COALESCE(stage_min, 6)`` ascending). An unknown code is the ``ValueError`` of
    :func:`wd.schemas.stage_to_index` (callers validate the wire value first)."""
    if stage is None or stage == "all":
        return stage_to_index(STAGE_ORDER[0])
    return stage_to_index(stage)


# ------------------------------------------------------------------------------------------------------ inputs (§1.1)
def _field(row: Any, key: str) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):  # dict, sqlite3.Row ("No item with that key" is an IndexError), garbage
        return None


def _int_or_none(value: Any) -> int | None:
    """``int()`` under ``try``; ``None`` for NULL, bools (a flag is never a rank or a stage), text and non-finite floats."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _to_rank(value: Any) -> int | None:
    n = _int_or_none(value)
    return n if n is not None and n > 0 else None


@dataclass(frozen=True)
class WordInput:
    """The only thing the policy sees of a ``words`` row (DESIGN §1.1): build it with :meth:`from_row`, which is total."""

    id: int
    lemma: str
    pos: str | None
    frq: int | None
    bnc: int | None
    sources: str | None
    stage_min: int | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any] | sqlite3.Row) -> "WordInput":
        """Coerce every column: ``id`` / ``frq`` / ``bnc`` through ``int()`` under ``try`` (``"12"`` → 12, ``"x"`` → None, a
        missing ``id`` → 0), ``lemma`` / ``pos`` / ``sources`` through ``str()``, a ``stage_min`` outside the enum → None (课标外)."""
        lemma = _field(row, "lemma")
        pos = _field(row, "pos")
        sources = _field(row, "sources")
        stage_min = _int_or_none(_field(row, "stage_min"))
        return cls(
            id=_int_or_none(_field(row, "id")) or 0,
            lemma="" if lemma is None else str(lemma),
            pos=None if pos is None else str(pos),
            frq=_int_or_none(_field(row, "frq")),
            bnc=_int_or_none(_field(row, "bnc")),
            sources=None if sources is None else str(sources),
            stage_min=stage_min if stage_min in _STAGE_INDEXES else None,
        )


def load_inputs(conn: sqlite3.Connection) -> tuple[list[WordInput], dict[str, frozenset[int]]]:
    """``SELECT INPUT_COLUMNS FROM words`` (every row: merged and private rows take part in their 课标外 group) and
    ``SELECT form, word_id FROM word_forms`` as ``form → {word_id, …}`` (a form pointing at exactly one word resolves, R3)."""
    rows = [WordInput.from_row(dict(zip(INPUT_COLUMNS, tuple(r)))) for r in conn.execute(f"SELECT {', '.join(INPUT_COLUMNS)} FROM words")]
    forms: dict[str, set[int]] = {}
    for form, word_id in conn.execute("SELECT form, word_id FROM word_forms"):
        forms.setdefault(str(form), set()).add(int(word_id))
    return rows, {form: frozenset(ids) for form, ids in forms.items()}


# ------------------------------------------------------------------------------------------------- primitives (§1.3)
def inherit_head(sources: str | None) -> str | None:
    """The head named by the first ``inherit:<head>`` token of the space-joined ``sources`` (``am is are`` → ``be``), else None."""
    for token in str(sources or "").split():
        if token.startswith(_INHERIT) and len(token) > len(_INHERIT):
            return token[len(_INHERIT):]
    return None


def native_rank(frq: Any, bnc: Any) -> int | None:
    """R2: ``frq`` if > 0, else ``bnc`` if > 0, else None (NULL, 0, negative and non-numeric values are unknown)."""
    return _to_rank(frq) or _to_rank(bnc)


def closed_class(lemma: str, pos: str | None, sources: str | None) -> bool:
    """R1 with M1's precedence: a month / weekday is never closed; otherwise R1a (dominant pos in :data:`ORDER_CLOSED_POS`),
    R1b (lemma in :data:`CLOSED_LEMMAS`) or R1c (an ``inherit:`` token)."""
    if lemma in CALENDAR_LEMMAS:
        return False
    return dominant_pos(pos) in ORDER_CLOSED_POS or lemma in CLOSED_LEMMAS or inherit_head(sources) is not None


def pack(closed: bool, rank: int | None, sub: int) -> int | None:
    """§1.2 packing: ``(CLOSED_BASE if closed else 0) + rank * RANK_SCALE + sub``; None when there is no rank (R4)."""
    if rank is None:
        return None
    return (CLOSED_BASE if closed else 0) + rank * RANK_SCALE + sub


def deal_index(k: int, n_r: int, n_u: int) -> int:
    """1-based position of the host the k-th (1-based) of ``n_u`` rows is dealt onto over ``n_r`` hosts:
    ``min(n_r, max(1, ceil((k − ½) · n_r / n_u)))`` — ``n_r=10, n_u=4`` → hosts 2 4 7 9 (DESIGN §1.3 step 2)."""
    return min(n_r, max(1, math.ceil((k - 0.5) * n_r / n_u)))


# ------------------------------------------------------------------------------------------------------ the policy
@dataclass(frozen=True)
class RankRow:
    """One ranked row: ``cls`` is the class of §1.3, ``how`` the rule that produced the key (``native`` / ``dealt`` / ``set`` /
    ``set-dealt`` / ``adverb`` / ``interj`` / ``glued:<head>`` / ``unranked``), ``rank`` and ``sub`` the parts the key encodes —
    ``pack(closed, rank, sub) == learn_rank`` for every row (a glued row reports its head's rank and ``head.sub + j``)."""

    id: int
    lemma: str
    stage_min: int | None
    closed: bool
    cls: str
    how: str
    rank: int | None
    sub: int
    learn_rank: int | None


@dataclass
class RankResult:
    """``ranks`` = ``id → learn_rank | None``; ``rows`` = ``id → RankRow``; ``stats`` = the per-stage table of :func:`stage_stats`."""

    ranks: dict[int, int | None]
    rows: dict[int, RankRow]
    stats: dict[str, Any]


@dataclass
class _Work:
    inp: WordInput
    stage_min: int | None
    closed: bool
    cls: str
    glue_head: str | None
    rank: int | None
    sub: int = SUB_NATIVE
    how: str = HOW_NATIVE
    token_rank: int | None = None
    learn_rank: int | None = None
    resolved: bool = False


def _deal(pool: Sequence[_Work], hosts: Sequence[_Work]) -> Iterator[tuple[_Work, _Work]]:
    """Pair the k-th row of ``pool`` with its host (:func:`deal_index`); nothing when there is no host (the rows keep NULL)."""
    n_r, n_u = len(hosts), len(pool)
    if n_r == 0:
        return
    for k, w in enumerate(pool, 1):
        yield w, hosts[deal_index(k, n_r, n_u) - 1]


def rank_rows(rows: Sequence[WordInput], forms: Mapping[str, frozenset[int]]) -> RankResult:
    """THE policy (DESIGN §1.3), pure and total: every row of ``rows`` gets a key or None, group-wise per ``(stage_min, closed)``.

    ``forms`` is ``word_forms`` as ``form → {word_id, …}``; a form pointing at exactly one word resolves a phrase token (R3).
    The result is deterministic for a given set of rows whatever their order (lemmas are unique in ``words``).
    """
    by_lemma: dict[str, WordInput] = {r.lemma: r for r in rows}
    by_id: dict[int, WordInput] = {r.id: r for r in rows}
    work: dict[int, _Work] = {}
    for r in rows:
        head = inherit_head(r.sources)
        glue_head = head if head is not None and head != r.lemma and head in by_lemma else None
        closed = closed_class(r.lemma, r.pos, r.sources)
        dp = dominant_pos(r.pos)
        if r.lemma in CALENDAR_LEMMAS:
            cls = CLS_SET
        elif glue_head is not None:
            cls = CLS_GLUED
        elif not closed and dp == "r":
            cls = CLS_ADVERB
        elif not closed and dp == "u":
            cls = CLS_INTERJ
        else:
            cls = CLS_PLAIN
        stage_min = r.stage_min if r.stage_min in _STAGE_INDEXES else None  # from_row already did this; direct constructions too
        work[r.id] = _Work(inp=r, stage_min=stage_min, closed=closed, cls=cls, glue_head=glue_head, rank=native_rank(r.frq, r.bnc))

    def resolve(token: str) -> WordInput | None:
        hit = by_lemma.get(token)
        if hit is not None:
            return hit
        ids = forms.get(token)
        if ids and len(ids) == 1:  # an ambiguous form (`axes` → ax, axis) does not resolve
            return by_id.get(next(iter(ids)))
        return None

    def token_rank(w: _Work) -> int | None:
        """R3: the rarest (largest) rank among the row's resolvable tokens; None when none resolves to a ranked word."""
        best: int | None = None
        for token in w.inp.lemma.replace("-", " ").split():
            head = resolve(token)
            if head is None or head.lemma == w.inp.lemma:  # the row itself never counts
                continue
            rk = native_rank(head.frq, head.bnc)
            if rk is not None and (best is None or rk > best):
                best = rk
        return best

    groups: dict[tuple[int | None, bool], list[_Work]] = {}
    for w in work.values():
        if w.cls != CLS_GLUED:
            groups.setdefault((w.stage_min, w.closed), []).append(w)
    for grp in groups.values():
        plain = [w for w in grp if w.cls == CLS_PLAIN]
        hosts = sorted((w for w in plain if w.rank is not None), key=lambda w: (w.rank, w.inp.lemma))
        # R3 — frequency-less plain rows, rarest resolvable token first, dealt evenly onto the hosts
        unranked = [w for w in plain if w.rank is None]
        for w in unranked:
            w.token_rank = token_rank(w)
        unranked.sort(key=lambda w: (w.token_rank is None, w.token_rank or 0, w.inp.lemma))
        for w, host in _deal(unranked, hosts):
            w.rank, w.sub, w.how = host.rank, SUB_DEALT, HOW_DEALT
        # M1 — calendar sets: one block at the median_low anchor, else dealt in calendar order keeping the calendar sub
        for members, base in ((MONTHS, SUB_MONTH_BASE), (WEEKDAYS, SUB_WEEKDAY_BASE)):
            present = [w for w in grp if w.cls == CLS_SET and w.inp.lemma in members]
            if not present:
                continue
            ranks = [w.rank for w in present if w.rank is not None]
            if ranks:
                anchor = statistics.median_low(ranks)
                for w in present:
                    w.rank, w.sub, w.how = anchor, base + members.index(w.inp.lemma) + 1, HOW_SET
            else:
                present.sort(key=lambda w: members.index(w.inp.lemma))
                for w in present:
                    w.sub, w.how = base + members.index(w.inp.lemma) + 1, HOW_SET_DEALT
                for w, host in _deal(present, hosts):
                    w.rank = host.rank
        # M3 / G5 — adverbs and interjections, frequency order kept, dealt evenly onto the hosts
        for cls, sub, how in ((CLS_ADVERB, SUB_ADVERB, HOW_ADVERB), (CLS_INTERJ, SUB_INTERJ, HOW_INTERJ)):
            pool = sorted((w for w in grp if w.cls == cls), key=lambda w: (w.rank is None, w.rank or 0, w.inp.lemma))
            for w, host in _deal(pool, hosts):
                w.rank, w.sub, w.how = host.rank, sub, how

    for w in work.values():
        if w.cls != CLS_GLUED:
            w.learn_rank = pack(w.closed, w.rank, w.sub)
            w.resolved = True
    # M2 — glued forms: key(head) + j, j = 1-based position among the head's forms sorted by lemma; the head's own frq / bnc / pos
    # decide, the form's are ignored. A head that is itself glued is followed to its head; a cycle gives NULL (R4), never an error.
    # Chains are outside the DESIGN (the seed glues `am is are → be` and `does → do` only): a chained form indexes among its
    # DIRECT head's forms, so `done → did → do` shares `does`'s key and the frq tail decides — recorded in the release note's 未决.
    siblings: dict[str, list[str]] = {}
    for w in work.values():
        if w.cls == CLS_GLUED and w.glue_head is not None:
            siblings.setdefault(w.glue_head, []).append(w.inp.lemma)
    for lemmas in siblings.values():
        lemmas.sort()
    for w in work.values():
        if w.cls == CLS_GLUED and not w.resolved:
            path: list[_Work] = []
            seen: set[int] = set()
            cur = w
            while cur.cls == CLS_GLUED and not cur.resolved and cur.inp.id not in seen:
                seen.add(cur.inp.id)
                path.append(cur)
                cur = work[by_lemma[cur.glue_head].id]  # type: ignore[index]  # glue_head is a lemma of `rows` by construction
            for x in reversed(path):  # the chain's end is resolved (or the cycle's unresolved member, whose key is None)
                head = work[by_lemma[x.glue_head].id]  # type: ignore[index]
                j = SUB_GLUED_BASE + siblings[x.glue_head].index(x.inp.lemma) + 1  # type: ignore[index]
                x.learn_rank = None if head.learn_rank is None else head.learn_rank + j
                x.closed, x.rank, x.sub, x.how = head.closed, head.rank, head.sub + j, f"{CLS_GLUED}:{x.glue_head}"
                x.resolved = True

    ranks: dict[int, int | None] = {}
    out: dict[int, RankRow] = {}
    for wid, w in work.items():
        if w.learn_rank is None:  # R4: nothing to encode — the frequency tail orders the row (today's order)
            w.rank, w.how = None, HOW_UNRANKED
        ranks[wid] = w.learn_rank
        out[wid] = RankRow(id=wid, lemma=w.inp.lemma, stage_min=w.stage_min, closed=w.closed, cls=w.cls, how=w.how, rank=w.rank, sub=w.sub, learn_rank=w.learn_rank)
    return RankResult(ranks=ranks, rows=out, stats=stage_stats(rows, out))


def best_effort_rank(cols: Mapping[str, Any]) -> int | None:
    """Per-row key without a connection (``services/words._insert_word``): closed class, native rank, ``SUB_NATIVE`` — exact for
    a natively ranked, non-dealt word (its key depends on no other row), None for a frequency-less row (filled by the next
    recompute), approximate for an adverb / interjection / calendar / glued row until then (DESIGN §2.1 purity note)."""
    w = WordInput.from_row(cols)
    return pack(closed_class(w.lemma, w.pos, w.sources), native_rank(w.frq, w.bnc), SUB_NATIVE)


# ---------------------------------------------------------------------------------------------------- order + stats
def order_key(row: WordInput, learn_rank: int | None) -> tuple[bool, int, bool, bool, int, str]:
    """Python twin of :data:`ORDER_SQL` for one row: NULL keys last, then the key, then the frequency tail — a COCA-ranked word
    before an unknown one, SQLite's NULL before 0 inside the unknown bucket, then ``frq``, then ``lemma`` (unique: total order)."""
    unknown = row.frq is None or row.frq == 0
    return (learn_rank is None, learn_rank or 0, unknown, row.frq is not None, row.frq or 0, row.lemma)


def _quantile(sorted_values: Sequence[int], p: float) -> int | None:
    if not sorted_values:
        return None
    return sorted_values[min(len(sorted_values) - 1, int(p * len(sorted_values)))]


def stage_code(stage_min: int | None) -> str:
    """``stage_min`` → the stats column: a stage code of ``STAGE_ORDER`` or ``"none"`` (NULL / out of range, the 课标外 group)."""
    return index_to_stage(stage_min) if stage_min in _STAGE_INDEXES else STATS_NONE


def stage_stats(rows: Sequence[WordInput], ranked: Mapping[int, RankRow]) -> dict[str, dict[str, Any]]:
    """The compact per-stage table of DESIGN §2.6 (``kv.learn_order.stats``, < 2 KB, never the full lists): one entry per code
    of ``STAGE_ORDER`` plus ``"none"`` with ``n`` (rows), ``ranked`` (natively ranked: ``how == 'native'``), ``from_frq`` /
    ``from_bnc`` (where that rank came from), ``dealt``, ``set``, ``glued``, ``adverb``, ``interj`` (rows placed by R3 / M1 / M2 /
    M3 / G5), ``closed``, ``p10`` / ``p50`` / ``p90`` of the native ranks and ``first8`` (the stage's first eight lemmas under
    :data:`ORDER_SQL`). ``ranked`` is ``RankResult.rows`` (``id → RankRow``) for ``rows``; JSON-serialisable; derived, never
    typed into docs or tests."""
    per: dict[str, list[WordInput]] = {code: [] for code in (*STAGE_ORDER, STATS_NONE)}
    for r in rows:
        per[stage_code(ranked[r.id].stage_min if r.id in ranked else r.stage_min)].append(r)
    out: dict[str, dict[str, Any]] = {}
    for code, sel in per.items():
        rr = [ranked[r.id] for r in sel if r.id in ranked]
        native = [(r, ranked[r.id]) for r in sel if r.id in ranked and ranked[r.id].how == HOW_NATIVE and ranked[r.id].rank is not None]
        from_frq = sum(1 for r, _ in native if _to_rank(r.frq) is not None)
        nat = sorted(x.rank for _, x in native if x.rank is not None)
        ordered = sorted(sel, key=lambda r: order_key(r, ranked[r.id].learn_rank if r.id in ranked else None))
        out[code] = {
            "n": len(sel),
            "ranked": len(native),
            "from_frq": from_frq,
            "from_bnc": len(native) - from_frq,
            "dealt": sum(1 for x in rr if x.how == HOW_DEALT),
            "set": sum(1 for x in rr if x.how in (HOW_SET, HOW_SET_DEALT)),
            "glued": sum(1 for x in rr if x.how.startswith(f"{CLS_GLUED}:")),
            "adverb": sum(1 for x in rr if x.how == HOW_ADVERB),
            "interj": sum(1 for x in rr if x.how == HOW_INTERJ),
            "closed": sum(1 for x in rr if x.closed),
            "p10": _quantile(nat, 0.1),
            "p50": _quantile(nat, 0.5),
            "p90": _quantile(nat, 0.9),
            "first8": [r.lemma for r in ordered[:8]],
        }
    return out


def label_pos_count(rows: Iterable[WordInput]) -> int:
    """Stage words whose ``pos`` is a label (``'v./n.'`` from a Claude lookup), not an ECDICT share distribution — the
    informational ``label_pos_stage_words`` count of §2.6 / §2.7 (a label never changes the class of a NULL-pos word, A9)."""
    return sum(1 for r in rows if r.stage_min is not None and r.pos is not None and r.pos.strip() and dominant_pos(r.pos) is None)


# ------------------------------------------------------------------------------------------- persistence (DB half)
# recompute / ensure_current / is_current / stale_count / unranked_stage_words / check_lines / stats_line / show / report /
# register_cli — the DB-writing half of DESIGN §2.1 (KV_* keys, system_events, `wd learn-order` of §2.5). It uses wd.db and
# wd.clock (never wd.services.*); the CLI handler imports wd.config late, like diag._settings().
EVENT_RECOMPUTED = "learn_order_recomputed"  # system_events kind: a recompute that changed rows (never from the seed import, which has its own event)
EVENT_FAILED = "learn_order_failed"  # system_events kind: ensure_current / the seed import caught a policy failure (fail-soft)
TRIGGER_SEED_IMPORT = "seed_import"  # the trigger that writes no learn_order_recomputed event (seed_imported carries the count)
MOVERS_SHIFT = 50  # the movers report counts rows that moved at least this many places inside their stage (§2.5 --dry-run)
MOVERS_TOP = 20  # … and lists this many biggest climbs and drops
MOVERS_FIRST = 10  # … and the first lemmas of each stage before / after
REPORT_FIRST = 30  # lemmas per stage in the report document (§2.8) = the window of the §1.6 acceptance counts
REPORT_ZK_FIRST = 200  # the 词组 window of the 初中新增 acceptance count (§1.6)
SHOW_COLUMNS: tuple[str, ...] = ("position", "lemma", "learn_rank", "closed", "how", "frq", "bnc", "eff")  # `wd learn-order --show`
# The §1.6 acceptance predicate ("FACTS-closed": the image gate FUNCTION_POS, the auxiliary / modal forms of FACTS §2 or an
# inherit: token) — a MEASUREMENT shared by report(), scripts/rehearse_migration.py and the full_seed gate, not a policy
# input (the policy's closed class is closed_class() above; this one is wider: interjections and inflected auxiliaries count).
ACCEPTANCE_AUX_LEMMAS: frozenset[str] = frozenset(
    "be am is are was were been being do does did done have has had can could will would shall should may might must ought".split()
)
# `calendar_words_in_xs` (§2.7): PRESENT month / weekday rows must carry the 小学 flag and stage_min (all 19 present is a full_seed assertion)
CALENDAR_INVARIANT_SQL = (
    "SELECT COUNT(*) FROM words WHERE lemma IN (" + ", ".join(f"'{lemma}'" for lemma in (*MONTHS, *WEEKDAYS)) + ") "
    f"AND (stage_{STAGE_ORDER[0]} IS NOT 1 OR stage_min IS NOT {stage_to_index(STAGE_ORDER[0])})"
)
_UNRANKED_STAGE_SQL = "SELECT COUNT(*) FROM words WHERE stage_min IS NOT NULL AND learn_rank IS NULL AND merged_into_word_id IS NULL"
_ERROR_TEXT_MAX = 500  # main.seed_check's cap on the error text of a failure event


def acceptance_closed(lemma: str, pos: str | None, sources: str | None) -> bool:
    """The §1.6 "FACTS-closed" measurement (see :data:`ACCEPTANCE_AUX_LEMMAS`) — wider than the policy's :func:`closed_class`,
    so "0 closed words in a stage's first 30" is the stricter claim."""
    return dominant_pos(pos) in FUNCTION_POS or lemma in ACCEPTANCE_AUX_LEMMAS or inherit_head(sources) is not None


@dataclass
class RecomputeResult:
    """What one :func:`recompute` did: ``changed`` rows differ between the stored and the computed key (written unless
    ``dry_run``), ``unranked_stage_words`` after the compute, ``stats`` the ``kv.learn_order.stats`` document (§2.6),
    ``movers`` the per-stage movers report when asked for (§2.5 ``--dry-run``)."""

    version: str
    rows: int
    changed: int
    unranked_stage_words: int
    seconds: float
    trigger: str
    stats: dict[str, Any]
    movers: dict[str, Any] | None = None
    dry_run: bool = False


@dataclass(frozen=True)
class ShowRow:
    """One line of :func:`show`: the stored key next to the policy's explanation (``how``) and the rank the key encodes (``eff``)."""

    position: int
    lemma: str
    learn_rank: int | None
    closed: bool
    how: str
    frq: int | None
    bnc: int | None
    eff: int | None


def _stored_keys(conn: sqlite3.Connection) -> dict[int, int | None]:
    """``id → stored learn_rank``; a value that is not an integer (INTEGER affinity keeps a hand-written ``'abc'`` as TEXT)
    reads as NULL, so it counts as changed and the next compare rewrites it instead of raising (totality)."""
    return {int(r[0]): _int_or_none(r[1]) for r in conn.execute("SELECT id, learn_rank FROM words")}


def _compare(conn: sqlite3.Connection) -> tuple[list[WordInput], dict[int, int | None], RankResult]:
    """Read the inputs and the stored keys and run the policy — the stored-vs-computed compare behind :func:`recompute`,
    :func:`stale_count` and :func:`report` (≈ 30–70 ms on the live seed; pure after the two SELECTs)."""
    rows, forms = load_inputs(conn)
    stored = _stored_keys(conn)
    return rows, stored, rank_rows(rows, forms)


@dataclass(frozen=True)
class Drift:
    """Rows whose stored key differs from :func:`rank_rows` now, split by what the difference means (§2.7): ``policy`` — stage
    rows placed by a rule that reads seed-managed inputs only (native, calendar set, glued, adverb, interjection, or no rank at
    all): the ``learn_rank_matches_policy`` violations — a hand edit or a stale policy; ``dealt`` — stage rows dealt by R3, which
    a runtime word or form can re-deal until the next recompute (module docstring; informational); ``none`` — 课标外 rows (A8,
    informational)."""

    policy: int
    dealt: int
    none: int

    @property
    def stage(self) -> int:
        """Every stage row that differs (``policy + dealt``): the rehearsal's / ``full_seed``'s "the column equals the policy"."""
        return self.policy + self.dealt

    @property
    def total(self) -> int:
        return self.stage + self.none


def _drift(stored: Mapping[int, int | None], result: RankResult, *, count_fills: bool = True) -> Drift:
    """Split the rows whose stored key ≠ computed key; ``count_fills=False`` leaves out the rows whose stored key is NULL (a
    fill, not drift — the rule of the stats document, so a first fill reports 0)."""
    policy = dealt = none = 0
    for wid, key in result.ranks.items():
        old = stored.get(wid)
        if old == key or (old is None and not count_fills):
            continue
        row = result.rows[wid]
        if row.stage_min is None:
            none += 1
        elif row.how == HOW_DEALT:
            dealt += 1
        else:
            policy += 1
    return Drift(policy, dealt, none)


def drift(conn: sqlite3.Connection) -> Drift:
    """:class:`Drift` of the database now (one stored-vs-computed compare, ≈ 60 ms on the live seed)."""
    _, stored, result = _compare(conn)
    return _drift(stored, result)


def _by_stage(rows: Sequence[WordInput], result: RankResult) -> dict[str, list[WordInput]]:
    per: dict[str, list[WordInput]] = {code: [] for code in (*STAGE_ORDER, STATS_NONE)}
    for r in rows:
        per[stage_code(result.rows[r.id].stage_min)].append(r)
    return per


def _movers(rows: Sequence[WordInput], stored: Mapping[int, int | None], result: RankResult) -> dict[str, Any]:
    """The §2.5 movers report: per stage ``records · rank_changed · moved (≥ MOVERS_SHIFT places) · max_shift · first lemmas old
    → new`` and the biggest climbs / drops — positions inside the stage's own words under :data:`ORDER_SQL`, stored vs computed."""
    stages: dict[str, Any] = {}
    moves: list[dict[str, Any]] = []
    for code, sel in _by_stage(rows, result).items():
        old = sorted(sel, key=lambda r: order_key(r, stored.get(r.id)))
        new = sorted(sel, key=lambda r: order_key(r, result.ranks[r.id]))
        old_pos = {r.id: i for i, r in enumerate(old, 1)}
        new_pos = {r.id: i for i, r in enumerate(new, 1)}
        shifts = {r.id: old_pos[r.id] - new_pos[r.id] for r in sel}  # positive = climbed
        stages[code] = {
            "records": len(sel),
            "rank_changed": sum(1 for r in sel if stored.get(r.id) != result.ranks[r.id]),
            "moved": sum(1 for s in shifts.values() if abs(s) >= MOVERS_SHIFT),
            "max_shift": max((abs(s) for s in shifts.values()), default=0),
            "first_old": [r.lemma for r in old[:MOVERS_FIRST]],
            "first_new": [r.lemma for r in new[:MOVERS_FIRST]],
        }
        moves.extend({"lemma": r.lemma, "stage": code, "old": old_pos[r.id], "new": new_pos[r.id], "shift": shifts[r.id]} for r in sel if shifts[r.id])
    climbs = sorted((m for m in moves if m["shift"] > 0), key=lambda m: (-m["shift"], m["lemma"]))[:MOVERS_TOP]
    drops = sorted((m for m in moves if m["shift"] < 0), key=lambda m: (m["shift"], m["lemma"]))[:MOVERS_TOP]
    return {"shift_threshold": MOVERS_SHIFT, "stages": stages, "climbs": climbs, "drops": drops}


def recompute(
    conn: sqlite3.Connection,
    *,
    now: str | None = None,
    seed_version: str | None = None,
    trigger: str = "cli",
    dry_run: bool = False,
    movers: bool = False,
) -> RecomputeResult:
    """Compute phase (pure): :func:`load_inputs` + the stored keys → :func:`rank_rows`; the rows whose stored key differs from
    the computed one are the change set (the stored-vs-computed compare IS the staleness test, A10). Write phase inside
    ``db.maybe_tx`` (joins the seed import's transaction, atomic on its own): ``UPDATE words SET learn_rank = ? WHERE id = ?``
    for the changed rows only — never ``updated_at`` —, then ``kv.learn_order.{version, seed_version, stats, computed_at}``
    (``seed_version`` = the given digest, else the current ``kv.seed_version``; the importer passes the digest it writes one
    statement later) and ``system_events('learn_order_recomputed')`` when rows changed and the trigger is not the seed import.
    ``dry_run`` writes nothing; ``movers`` fills the per-stage movers report (§2.5). Raises on a database fault (callers
    that must not fail use :func:`ensure_current`).

    The stored keys are read (again) UNDER the write lock: the policy runs outside it (so the lock stays ≈ 20 ms), and a writer
    that committed meanwhile — a ``wd learn-order`` or ``wd import-seed`` next to a restart, a lookup's insert at 03:30 — is seen
    by this pass instead of being stamped over. The informational ``drift_dealt`` / ``drift_none`` counts of the stats document
    (rows whose stored, non-NULL key moved: re-dealt stage rows, 课标外 rows) are 0 when the stored policy version is not this
    code's, because after a version bump every key moves and nothing has drifted."""
    t0 = time.perf_counter()
    rows, forms = load_inputs(conn)
    result = rank_rows(rows, forms)
    unranked = sum(1 for r in result.rows.values() if r.stage_min is not None and r.learn_rank is None)

    def compare(stored: Mapping[int, int | None]) -> tuple[list[tuple[int | None, int]], dict[str, Any]]:
        changed = [(key, wid) for wid, key in result.ranks.items() if stored.get(wid) != key]
        moved = _drift(stored, result, count_fills=False) if db.kv_get(conn, KV_VERSION) == LEARN_ORDER_VERSION else Drift(0, 0, 0)
        stats: dict[str, Any] = {
            **result.stats,
            "label_pos_stage_words": label_pos_count(rows),
            "drift_dealt": moved.dealt,  # stage rows R3 re-dealt since the last compare (a runtime word or form resolved a phrase token)
            "drift_none": moved.none,  # 课标外 rows whose stored key moved (A8: runtime inserts shift that group's dealt rows)
        }
        return changed, stats

    def outcome(stored: Mapping[int, int | None], changed: Sequence[tuple[int | None, int]], stats: dict[str, Any]) -> RecomputeResult:
        return RecomputeResult(
            version=LEARN_ORDER_VERSION,
            rows=len(rows),
            changed=len(changed),
            unranked_stage_words=unranked,
            seconds=time.perf_counter() - t0,
            trigger=trigger,
            stats=stats,
            movers=_movers(rows, stored, result) if movers else None,
            dry_run=dry_run,
        )

    if dry_run:
        stored = _stored_keys(conn)
        return outcome(stored, *compare(stored))
    now = now or now_iso()
    with db.maybe_tx(conn):
        stored = _stored_keys(conn)  # under the lock, see the docstring
        changed, stats = compare(stored)
        out = outcome(stored, changed, stats)
        if changed:
            conn.executemany("UPDATE words SET learn_rank = ? WHERE id = ?", changed)
        stamp = seed_version if seed_version is not None else (db.kv_get(conn, "seed_version") or "")
        db.kv_set(conn, KV_VERSION, LEARN_ORDER_VERSION, now=now)
        db.kv_set(conn, KV_SEED, stamp, now=now)
        db.kv_set(conn, KV_STATS, json.dumps(stats, ensure_ascii=False, separators=(",", ":")), now=now)
        db.kv_set(conn, KV_AT, now, now=now)
        out.seconds = time.perf_counter() - t0
        if changed and trigger != TRIGGER_SEED_IMPORT:
            detail = {
                "version": LEARN_ORDER_VERSION,
                "trigger": trigger,
                "rows": out.rows,
                "changed": out.changed,
                "unranked_stage_words": out.unranked_stage_words,
                "seconds": round(out.seconds, 3),
            }
            conn.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES (?, ?, ?)", (EVENT_RECOMPUTED, json.dumps(detail), now))
    out.seconds = time.perf_counter() - t0
    (log.info if changed else log.debug)(
        "learn order %s: %d rows, %d updated in %.3f s; %d stage words unranked (%s)",
        out.version,
        out.rows,
        out.changed,
        out.seconds,
        out.unranked_stage_words,
        trigger,
        extra={"event": EVENT_RECOMPUTED if changed else "learn_order_checked"},
    )
    return out


def record_failure(conn: sqlite3.Connection, trigger: str, exc: BaseException, *, now: str | None = None) -> None:
    """``system_events('learn_order_failed')`` with ``{trigger, error}`` (the error text capped like ``main.seed_check``'s);
    joins an open transaction (the seed import's) and never raises — the log line of the caller is the last resort."""
    detail = {"trigger": trigger, "error": f"{type(exc).__name__}: {exc}"[:_ERROR_TEXT_MAX]}
    try:
        with db.maybe_tx(conn):
            conn.execute("INSERT INTO system_events(kind, detail_json, created_at) VALUES (?, ?, ?)", (EVENT_FAILED, json.dumps(detail, ensure_ascii=False), now or now_iso()))
    except Exception:  # noqa: BLE001 - a database that cannot take an event row: nothing more to do than log it
        log.exception("learning order: could not record the %s event", EVENT_FAILED)


def ensure_current(conn: sqlite3.Connection, *, now: str | None = None, trigger: str = "startup") -> RecomputeResult | None:
    """:func:`recompute` for the service start and the nightly maintenance — the compare is the staleness test (A10), and it
    never raises: any exception is logged with its traceback (``event: learn_order_failed``) and recorded as
    ``system_events('learn_order_failed')``; the lists then serve the stored or the fail-soft frequency order. Returns None
    on failure."""
    try:
        return recompute(conn, now=now, trigger=trigger)
    except Exception as e:  # noqa: BLE001 - never fatal (DESIGN §2.4): the lists keep working on the stored / NULL keys
        log.exception("learning order: recompute failed (trigger %s); the lists keep the stored or fail-soft order", trigger, extra={"event": EVENT_FAILED})
        record_failure(conn, trigger, e, now=now)
        return None


def _short(digest: str | None) -> str:
    return f"{digest[:12]}…" if digest else "-"


def is_current(conn: sqlite3.Connection) -> tuple[bool, str]:
    """``(True, "ok")`` when ``kv.learn_order.version`` is this code's :data:`LEARN_ORDER_VERSION` and the seed stamp
    ``kv.learn_order.seed_version`` equals ``kv.seed_version``; else ``(False, reason)`` with the reason ``never computed``,
    ``kv.learn_order.version <v> ≠ code <v>`` or ``seed <stamp>… ≠ kv.seed_version <digest>…`` (an older server imported a
    seed while the column existed). A diagnostic (``wd check db``), not a gate: :func:`ensure_current` always compares."""
    version = db.kv_get(conn, KV_VERSION)
    if version is None:
        return False, "never computed"
    if version != LEARN_ORDER_VERSION:
        return False, f"kv.{KV_VERSION} {version} ≠ code {LEARN_ORDER_VERSION}"
    stamp, seed = db.kv_get(conn, KV_SEED) or "", db.kv_get(conn, "seed_version") or ""
    if stamp != seed:
        return False, f"seed {_short(stamp)} ≠ kv.seed_version {_short(seed)}"
    return True, "ok"


def stale_count(conn: sqlite3.Connection, *, stage_only: bool = True) -> int:
    """Rows whose stored key differs from :func:`rank_rows` now — every stage word by default (the dealt ones included: the
    rehearsal's and the ``full_seed`` gate's "the column equals the policy" check), every row with ``stage_only=False``. The
    ``learn_rank_matches_policy`` line counts :func:`drift` ``.policy`` instead (§2.7, module docstring)."""
    d = drift(conn)
    return d.stage if stage_only else d.total


def unranked_stage_words(conn: sqlite3.Connection) -> int:
    """Stage words (``stage_min IS NOT NULL``, not merged) without a key — 0 after any recompute on the seed (R3 deals every
    frequency-less stage word; pinned by the ``learn_rank_present`` invariant)."""
    return int(conn.execute(_UNRANKED_STAGE_SQL).fetchone()[0])


def _invariant(name: str, n: int, why: str) -> tuple[str, bool]:
    return (f"invariant {name}: ok", False) if n == 0 else (f"invariant {name}: {n} violation(s) ({why})", True)


def _failed(name: str, e: BaseException) -> tuple[str, bool]:
    """``invariant <name>: query failed (…)`` — not counted (diag's ``_invariant_line`` rule: unverifiable ≠ violated). An SQLite
    error keeps diag's bare message; anything else (a policy bug inside :func:`rank_rows`) names its type."""
    text = str(e) if isinstance(e, sqlite3.OperationalError) else f"{type(e).__name__}: {e}"
    return f"invariant {name}: query failed ({text})", False


def check_lines(conn: sqlite3.Connection) -> list[tuple[str, bool]]:
    """The four learning-order lines of ``wd check db`` (§2.7), ``(line, violated)`` each, in this order:
    ``learn_rank_present`` · ``learn_order_current`` · ``learn_rank_matches_policy`` (:class:`Drift` ``policy``: stage words
    placed by the seed-only rules — re-dealt stage rows and 课标外 drift are informational, see the module docstring) ·
    ``calendar_words_in_xs``. A failing query or a raising policy is reported as ``query failed (…)`` and not counted (diag's
    ``_invariant_line`` rule: unverifiable ≠ violated); nothing here raises. Run from schema :data:`LEARN_ORDER_FROM_VERSION` on."""
    out: list[tuple[str, bool]] = []
    try:
        out.append(_invariant("learn_rank_present", unranked_stage_words(conn), "stage words without learn_rank — the next `wd serve` start or `wd learn-order` fills them"))
    except Exception as e:  # noqa: BLE001 - reported in place, never raised (a diagnostic, not a gate on the policy's health)
        out.append(_failed("learn_rank_present", e))
    try:
        ok, reason = is_current(conn)
    except Exception as e:  # noqa: BLE001
        out.append(_failed("learn_order_current", e))
    else:
        detail = f"computed for {reason}" if reason.startswith("seed ") else reason
        out.append(("invariant learn_order_current: ok", False) if ok else (f"invariant learn_order_current: 1 violation(s) ({detail}; run `wd learn-order`)", True))
    try:
        out.append(_invariant("learn_rank_matches_policy", drift(conn).policy, "stored learn_rank of stage words differs from learn_order.rank_rows(); run `wd learn-order`"))
    except Exception as e:  # noqa: BLE001
        out.append(_failed("learn_rank_matches_policy", e))
    try:
        out.append(_invariant("calendar_words_in_xs", int(conn.execute(CALENDAR_INVARIANT_SQL).fetchone()[0]), f"month/weekday rows without stage_{STAGE_ORDER[0]} = 1 / stage_min = {stage_to_index(STAGE_ORDER[0])}"))
    except Exception as e:  # noqa: BLE001
        out.append(_failed("calendar_words_in_xs", e))
    return out


def stats_line(conn: sqlite3.Connection) -> str:
    """``kv.learn_order.stats: xs n=600 ranked=533 dealt=9 … · dealt drift 0 · 课标外 drift 0 · label-pos 0`` — the stored §2.6
    document rendered for ``wd check db`` (``dealt drift`` = stage rows the last compare re-dealt because a runtime word or form
    resolved a phrase token; ``课标外 drift`` = 课标外 rows whose key moved); ``-`` before the first recompute. Informational:
    never flips the check."""
    raw = db.kv_get(conn, KV_STATS)
    if raw is None:
        return f"kv.{KV_STATS}: -"
    try:
        stats = json.loads(raw)
    except ValueError:
        return f"kv.{KV_STATS}: unreadable ({raw[:40]}…)"
    if not isinstance(stats, dict):
        return f"kv.{KV_STATS}: unreadable"
    parts: list[str] = []
    for code in (*STAGE_ORDER, STATS_NONE):
        s = stats.get(code)
        if isinstance(s, dict):
            parts.append(f"{code} " + " ".join(f"{k}={s.get(k)}" for k in ("n", "ranked", "dealt", "set", "glued", "adverb", "interj", "closed")))
    parts.append(f"dealt drift {stats.get('drift_dealt', '-')}")
    parts.append(f"课标外 drift {stats.get('drift_none', '-')}")
    parts.append(f"label-pos {stats.get('label_pos_stage_words', '-')}")
    return f"kv.{KV_STATS}: " + " · ".join(parts)


def show(conn: sqlite3.Connection, stage: str, top: int, *, cur: int | None = None) -> list[ShowRow]:
    """The first ``top`` words of ``stage_min = stage`` under :data:`ORDER_SQL` (the stored keys, as the lists serve them) —
    or, with ``cur``, the 词库 tab / 筛词 order of that 主攻 stage index over the stage's flagged words (stage distance first)
    — each with the policy's ``closed`` / ``how`` and the rank the key encodes (``eff``), so the operator sees why a word sits
    where it sits. ``ValueError`` for an unknown stage code."""
    idx = stage_to_index(stage)
    rows, forms = load_inputs(conn)
    result = rank_rows(rows, forms)
    params: dict[str, Any] = {"limit": max(0, int(top))}
    if cur is None:
        where, order = "w.stage_min = :idx", ORDER_SQL
        params["idx"] = idx
    else:
        where, order = f"w.stage_{stage} = 1 AND w.merged_into_word_id IS NULL", f"{stage_distance_sql()}, {ORDER_SQL}"
        params["cur"] = int(cur)
    out: list[ShowRow] = []
    sql = f"SELECT w.id, w.lemma, w.learn_rank, w.frq, w.bnc FROM words w WHERE {where} ORDER BY {order} LIMIT :limit"
    for position, r in enumerate(conn.execute(sql, params), 1):
        rr = result.rows.get(int(r[0]))
        out.append(
            ShowRow(
                position=position,
                lemma=str(r[1]),
                learn_rank=_int_or_none(r[2]),
                closed=rr.closed if rr is not None else False,
                how=rr.how if rr is not None else HOW_UNRANKED,
                frq=_int_or_none(r[3]),
                bnc=_int_or_none(r[4]),
                eff=rr.rank if rr is not None else None,
            )
        )
    return out


def _longest_unknown_frq_run(sel: Sequence[WordInput]) -> int:
    best = run = 0
    for r in sel:
        run = run + 1 if (r.frq is None or r.frq == 0) else 0
        best = max(best, run)
    return best


def report(conn: sqlite3.Connection) -> dict[str, Any]:
    """The ``data/seed/learn_order.json`` document (§2.8): ``policy``, ``seed`` (the ``kv.learn_order.seed_version`` stamp the
    stored ranks were computed for — ``kv.seed_version`` right after a recompute, which is when ``wd learn-order --report``
    writes it), ``computed_at``, ``generated_by``, per stage code (plus ``none``) the compact counts of :func:`stage_stats` and
    the first :data:`REPORT_FIRST` lemmas in the STORED order, and the §1.6 acceptance block computed from the database — the
    five stage codes only, never the 课标外 group: FACTS-closed words in each first 30, adverbs in the 小学 first 30, the
    positions of the 12 months in the 小学 order, 词组 in the 初中新增 first 200, the longest run of frequency-less cards per stage."""
    rows, stored, result = _compare(conn)
    kinds = {int(r[0]): str(r[1] or "") for r in conn.execute("SELECT id, kind FROM words")}
    ordered = {code: sorted(sel, key=lambda r: order_key(r, stored.get(r.id))) for code, sel in _by_stage(rows, result).items()}
    stages: dict[str, Any] = {}
    for code, sel in ordered.items():
        s = result.stats[code]
        stages[code] = {**{k: s[k] for k in ("n", "ranked", "dealt", "set", "glued", "adverb", "interj", "closed", "p10", "p50", "p90")}, "first": [r.lemma for r in sel[:REPORT_FIRST]]}
    xs, zk = ordered["xs"], ordered["zk"]
    xs_positions = {r.lemma: i for i, r in enumerate(xs, 1)}
    acceptance = {
        "closed_in_first_30": {code: sum(1 for r in ordered[code][:REPORT_FIRST] if acceptance_closed(r.lemma, r.pos, r.sources)) for code in STAGE_ORDER},
        "xs_adverbs_first_30": sum(1 for r in xs[:REPORT_FIRST] if dominant_pos(r.pos) == "r" and not acceptance_closed(r.lemma, r.pos, r.sources)),
        "xs_months_positions": [xs_positions.get(month) for month in MONTHS],
        "zk_phrases_first_200": sum(1 for r in zk[:REPORT_ZK_FIRST] if kinds.get(r.id) == "phrase"),
        "longest_frq_null_run": {code: _longest_unknown_frq_run(ordered[code]) for code in STAGE_ORDER},
    }
    return {
        "policy": LEARN_ORDER_VERSION,
        "seed": db.kv_get(conn, KV_SEED) or db.kv_get(conn, "seed_version"),
        "computed_at": db.kv_get(conn, KV_AT),
        "generated_by": "wd learn-order --report",
        "stages": stages,
        "acceptance": acceptance,
    }


# ------------------------------------------------------------------------------------------- CLI `wd learn-order` (§2.5)
def format_result(r: RecomputeResult) -> str:
    """``learn order lo-1: 9618 rows, N updated in 0.04 s; 0 stage words unranked``."""
    return f"learn order {r.version}: {r.rows} rows, {r.changed} updated in {r.seconds:.2f} s; {r.unranked_stage_words} stage words unranked"


def format_movers(r: RecomputeResult) -> str:
    """The ``--dry-run`` movers report (§2.5): per stage one summary line and the first lemmas old → new, then the biggest
    climbs and drops (``lemma (stage old→new, ±shift)``)."""
    m = r.movers or {"shift_threshold": MOVERS_SHIFT, "stages": {}, "climbs": [], "drops": []}
    lines = [f"dry run: learn order {r.version} over {r.rows} rows — {r.changed} would change, nothing written ({r.seconds:.2f} s); {r.unranked_stage_words} stage words unranked"]
    for code, s in m["stages"].items():
        lines.append(f"  {code}: {s['records']} records · {s['rank_changed']} rank changed · {s['moved']} moved ≥ {m['shift_threshold']} places · max shift {s['max_shift']}")
        lines.append(f"      first {MOVERS_FIRST} old: {' '.join(s['first_old']) or '-'}")
        lines.append(f"      first {MOVERS_FIRST} new: {' '.join(s['first_new']) or '-'}")
    lines.append(f"  biggest climbs: " + (" · ".join(f"{x['lemma']} ({x['stage']} {x['old']}→{x['new']}, +{x['shift']})" for x in m["climbs"]) or "-"))
    lines.append(f"  biggest drops: " + (" · ".join(f"{x['lemma']} ({x['stage']} {x['old']}→{x['new']}, {x['shift']})" for x in m["drops"]) or "-"))
    return "\n".join(lines)


def format_show(rows: Sequence[ShowRow]) -> str:
    """The ``--show`` table: :data:`SHOW_COLUMNS` as the header, one row per word."""
    widths = (8, 24, 10, 6, 14, 6, 6, 6)
    cells = lambda values: "  ".join(f"{v:<{w}}" if i in (1, 3, 4) else f"{v:>{w}}" for i, (v, w) in enumerate(zip(values, widths)))  # noqa: E731
    lines = [cells(SHOW_COLUMNS)]
    for r in rows:
        lines.append(cells((r.position, r.lemma, "-" if r.learn_rank is None else r.learn_rank, "yes" if r.closed else "no", r.how, "-" if r.frq is None else r.frq, "-" if r.bnc is None else r.bnc, "-" if r.eff is None else r.eff)))
    return "\n".join(lines)


def cmd_learn_order(args: argparse.Namespace) -> int:
    """``wd learn-order [--dry-run] [--show STAGE [--top N] [--cur STAGE]] [--report PATH] [--db PATH]`` (DEPLOY §9): refuses a
    database below schema :data:`LEARN_ORDER_FROM_VERSION` with one line and exit 1 (the ``import-seed`` precedent); ``--show``
    prints the table, ``--dry-run`` the movers report (writes nothing), otherwise recomputes and prints :func:`format_result`
    (exit 1 when stage words stay unranked) and ``--report`` then writes the §2.8 document from the ranks just stored.
    ``--report`` together with ``--dry-run`` or ``--show`` is a usage error (exit 2): the document would describe the stored
    ranks under this code's policy stamp without a recompute having run."""
    from ..config import ConfigError, Settings  # late: wd.config is a leaf, and only the CLI handler needs the settings

    if args.report and (args.dry_run or args.show):
        print("wd learn-order: --report writes the document from the ranks the recompute just stored; it cannot be combined with --dry-run or --show (run `wd learn-order --report PATH` on its own)", file=sys.stderr)
        return 2
    try:
        cfg = Settings.from_env()
    except ConfigError as e:
        print(f"wd: configuration error: {e}", file=sys.stderr)
        return 2
    path = Path(args.db).expanduser() if args.db else cfg.db_path
    if not path.is_file():
        print(f"wd learn-order: database {path} does not exist (run `wd migrate`)", file=sys.stderr)
        return 1
    conn = db.connect(path)
    try:
        version = db.current_version(conn)
        if version < LEARN_ORDER_FROM_VERSION:
            print(f"wd learn-order: schema version {version} has no words.learn_rank (migration {LEARN_ORDER_FROM_VERSION:04d}) — run `wd migrate` first", file=sys.stderr)
            return 1
        rc = 0
        if args.show:
            cur = default_cur(args.cur) if args.cur else None
            print(format_show(show(conn, args.show, int(args.top), cur=cur)))
        elif args.dry_run:
            print(format_movers(recompute(conn, trigger="cli", dry_run=True, movers=True)))
        else:
            result = recompute(conn, trigger="cli")
            print(format_result(result))
            rc = 1 if result.unranked_stage_words else 0
        if args.report:
            out = Path(args.report).expanduser()
            try:
                out.write_text(json.dumps(report(conn), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except OSError as e:
                print(f"wd learn-order: cannot write report {out}: {e}", file=sys.stderr)
                return 1
            print(f"report written to {out}")
        return rc
    except sqlite3.Error as e:  # a hand-edited table, a foreign file: one line like import-seed, never a traceback
        print(f"wd learn-order: database error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def register_cli(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("learn-order", help="recompute / preview / report the learning order words.learn_rank (idempotent; refuses below schema 14)")
    p.add_argument("--dry-run", action="store_true", help="write nothing; print the movers report of the stored ranks against the policy")
    p.add_argument("--show", default=None, choices=STAGE_ORDER, metavar="STAGE", help=f"print the first N words of this stage's own words ({' '.join(SHOW_COLUMNS)})")
    p.add_argument("--top", type=int, default=REPORT_FIRST, metavar="N", help=f"rows for --show (default {REPORT_FIRST})")
    p.add_argument("--cur", default=None, choices=(*STAGE_ORDER, "all"), metavar="STAGE", help="with --show: print the 词库 tab / 筛词 order of this 主攻 stage instead of the stage's own words")
    p.add_argument("--report", default=None, metavar="PATH", help="write the data/seed/learn_order.json document to PATH from the ranks the recompute just stored (not with --dry-run / --show)")
    p.add_argument("--db", default=None, metavar="PATH", help="use this database file instead of WD_DB_PATH (rehearsal copies, restore drills)")
    p.set_defaults(func=cmd_learn_order)


__all__ = [
    "ACCEPTANCE_AUX_LEMMAS",
    "CALENDAR_INVARIANT_SQL",
    "CALENDAR_LEMMAS",
    "CLOSED_BASE",
    "CLOSED_LEMMAS",
    "CLS_ADVERB",
    "CLS_GLUED",
    "CLS_INTERJ",
    "CLS_PLAIN",
    "CLS_SET",
    "EVENT_FAILED",
    "EVENT_RECOMPUTED",
    "FRQ_TAIL",
    "HOW_ADVERB",
    "HOW_DEALT",
    "HOW_INTERJ",
    "HOW_NATIVE",
    "HOW_SET",
    "HOW_SET_DEALT",
    "HOW_UNRANKED",
    "INPUT_COLUMNS",
    "KV_AT",
    "KV_SEED",
    "KV_STATS",
    "KV_VERSION",
    "LEARN_ORDER_FROM_VERSION",
    "LEARN_ORDER_VERSION",
    "MONTHS",
    "MOVERS_FIRST",
    "MOVERS_SHIFT",
    "MOVERS_TOP",
    "ORDER_CLOSED_POS",
    "ORDER_SQL",
    "RANK_SCALE",
    "REPORT_FIRST",
    "REPORT_ZK_FIRST",
    "SHOW_COLUMNS",
    "STAGE_NULL_DISTANCE",
    "STATS_NONE",
    "SUB_ADVERB",
    "SUB_DEALT",
    "SUB_GLUED_BASE",
    "SUB_INTERJ",
    "SUB_MONTH_BASE",
    "SUB_NATIVE",
    "SUB_WEEKDAY_BASE",
    "TRIGGER_SEED_IMPORT",
    "WEEKDAYS",
    "Drift",
    "RankResult",
    "RankRow",
    "RecomputeResult",
    "ShowRow",
    "WordInput",
    "acceptance_closed",
    "best_effort_rank",
    "check_lines",
    "closed_class",
    "cmd_learn_order",
    "deal_index",
    "default_cur",
    "drift",
    "ensure_current",
    "format_movers",
    "format_result",
    "format_show",
    "inherit_head",
    "is_current",
    "label_pos_count",
    "load_inputs",
    "native_rank",
    "order_key",
    "order_sql",
    "pack",
    "rank_rows",
    "recompute",
    "record_failure",
    "register_cli",
    "report",
    "show",
    "stage_code",
    "stage_distance",
    "stage_distance_sql",
    "stage_stats",
    "stale_count",
    "stats_line",
    "unranked_stage_words",
]
