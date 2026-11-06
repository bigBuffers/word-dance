"""services/learn_order.py — the pure half of the learning order (docs/analysis/2026-11-06-learn-order/DESIGN.md §1, §4.1
items 1–10): constants derived from the image gate and the stage enum, the lo-1 golden table over the mini seed, totality on
garbage rows, the dealing formula with the word_forms token resolution, calendar sets, glued forms, adverbs / interjections,
key packing, the stage distance and its SQL twin, best_effort_rank against rank_rows; a second golden digest over a synthetic
row set that exercises every rule the mini seed lacks (F-4), and the stamps of the committed data/seed/learn_order.json (ARCH-1)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import statistics
from itertools import count
from pathlib import Path

import pytest

from wd.images import style
from wd.schemas import STAGE_INDEX, STAGE_ORDER, stage_to_index
from wd.services import learn_order as lo
from wd.services.learn_order import RankResult, WordInput, best_effort_rank, closed_class, load_inputs, native_rank, order_key, pack, rank_rows

# Golden table of DESIGN §4.1 item 2 (policy LEARN_ORDER_VERSION = "lo-1", mini seed backend/tests/fixtures/mini_seed.jsonl imported with
# wd.seed.import_seed into a fresh migrated database). Editing rank_rows() so that any key moves fails here: bump LEARN_ORDER_VERSION,
# regenerate the table / digest and data/seed/learn_order.json together (DESIGN §6.3 "policy-only" rollback).
GOLDEN: dict[str, int] = {
    "go": 3500, "take": 6300, "good": 11000, "child": 11500, "run": 20200, "water": 22600, "email": 22620, "study": 24000,
    "book": 24100, "house": 25700, "person": 34500, "teacher": 37100, "better": 45200, "decide": 45600, "receive": 49700,
    "base": 53600, "a.m.": 53620, "data": 55900, "recent": 56700, "computer": 58900, "bank": 66300, "color": 69700, "tv": 73000,
    "happy": 74700, "dog": 75300, "ability": 78300, "analysis": 81100, "glass": 82000, "ice cream": 82020, "mountain": 124000,
    "basis": 130700, "clothes": 143400, "cat": 177500, "aids": 179300, "abandon": 218200, "absence": 252400, "negotiate": 254100,
    "apple": 269500, "absorb": 312000, "absolute": 316500, "running": 325200, "abstract": 400700, "axis": 559800,
    "absolutely": 559840, "absurd": 590100, "abundant": 622300, "receipt": 651700, "abolish": 749000, "china": 794600,
    "abnormal": 824100, "absorption": 859600, "ought to": 859620, "abrupt": 870300, "bookshelf": 1117000, "ax": 1132200,
    "axe": 1138800, "be": 10000200, "is": 10000201, "a": 10000500, "an": 10003000, "some": 10006000, "aboard": 10498400,
}
GOLDEN_DIGEST = "8ba429d756f62e54a58a5aa11561eb702fd73511a28f64106eb00f5597aa91ef"  # sha256(json.dumps(sorted pairs, …)) for lo-1
SYNTHETIC_DIGEST = "cb4b375d18c1764f10852c81c916e7d21cb8787d4af04801ea5a0881a0d481ff"  # the same digest over synthetic_rows() for lo-1 (F-4: M1 / G5 / R3 token resolution / glue are pinned here)
REPO = Path(__file__).resolve().parents[3]

_ids = count(1)


def W(lemma: str, *, pos: str | None = None, frq: int | None = None, bnc: int | None = None, sources: str | None = None, stage_min: int | None = 1) -> WordInput:
    """A policy input row with a fresh id (lemmas must be unique within one rank_rows call, as in the words table)."""
    return WordInput(id=next(_ids), lemma=lemma, pos=pos, frq=frq, bnc=bnc, sources=sources, stage_min=stage_min)


def by_lemma(result: RankResult, rows: list[WordInput]) -> dict[str, lo.RankRow]:
    return {r.lemma: result.rows[r.id] for r in rows}


def ordered(result: RankResult, rows: list[WordInput], *, stage_min: int | None, closed: bool) -> list[str]:
    """The lemmas of one (stage_min, closed) group in ORDER_SQL order (the Python twin order_key)."""
    group = [r for r in rows if result.rows[r.id].stage_min == stage_min and result.rows[r.id].closed is closed]
    return [r.lemma for r in sorted(group, key=lambda r: order_key(r, result.ranks[r.id]))]


def hosts(n: int, *, stage_min: int = 1, step: int = 100) -> list[WordInput]:
    """n natively ranked content words with ranks step, 2·step, … (the hosts of a group)."""
    return [W(f"host{i:02d}", pos="n:100", frq=step * i, stage_min=stage_min) for i in range(1, n + 1)]


# ------------------------------------------------------------------------------------------------------ 1 constants
def test_constants_are_derived_from_the_image_gate_and_the_enum():
    assert lo.ORDER_CLOSED_POS == style.FUNCTION_POS - {"u"}
    assert lo.ORDER_CLOSED_POS | {"u"} == style.FUNCTION_POS and "u" not in lo.ORDER_CLOSED_POS and "r" not in lo.ORDER_CLOSED_POS
    assert isinstance(lo.ORDER_CLOSED_POS, frozenset) and isinstance(lo.CLOSED_LEMMAS, frozenset)
    assert lo.CLOSED_LEMMAS == frozenset(
        {"a", "an", "the", "be", "do", "have", "can", "could", "will", "would", "shall", "should", "may", "might", "must", "ought"}
    )
    assert len(lo.CLOSED_LEMMAS) == 16
    assert lo.MONTHS == ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
    assert lo.WEEKDAYS == ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    assert lo.CALENDAR_LEMMAS == frozenset(lo.MONTHS) | frozenset(lo.WEEKDAYS) and len(lo.CALENDAR_LEMMAS) == 19
    assert lo.STAGE_NULL_DISTANCE == 2 * len(STAGE_ORDER) + 1 == 11
    assert lo.LEARN_ORDER_VERSION == "lo-1" and lo.LEARN_ORDER_FROM_VERSION == 14
    assert (lo.KV_VERSION, lo.KV_SEED, lo.KV_STATS, lo.KV_AT) == (
        "learn_order.version", "learn_order.seed_version", "learn_order.stats", "learn_order.computed_at",
    )
    assert lo.INPUT_COLUMNS == ("id", "lemma", "pos", "frq", "bnc", "sources", "stage_min")
    assert lo.FRQ_TAIL == "(w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"
    assert lo.ORDER_SQL == f"w.learn_rank IS NULL, w.learn_rank, {lo.FRQ_TAIL}" == lo.order_sql("w") == lo.order_sql()
    assert lo.order_sql("x") == "x.learn_rank IS NULL, x.learn_rank, (x.frq IS NULL OR x.frq = 0), x.frq, x.lemma"
    # the packing layout (A19): native < glued 1..19 < dealt 20 < months 21..32 < weekdays 33..39 < adverb 40 < interjection 50 < RANK_SCALE
    assert (lo.CLOSED_BASE, lo.RANK_SCALE) == (10_000_000, 100)
    assert (lo.SUB_NATIVE, lo.SUB_GLUED_BASE, lo.SUB_DEALT, lo.SUB_MONTH_BASE, lo.SUB_WEEKDAY_BASE, lo.SUB_ADVERB, lo.SUB_INTERJ) == (0, 0, 20, 20, 32, 40, 50)
    assert lo.SUB_MONTH_BASE + len(lo.MONTHS) == lo.SUB_WEEKDAY_BASE
    assert lo.SUB_DEALT < lo.SUB_MONTH_BASE + 1 and lo.SUB_WEEKDAY_BASE + len(lo.WEEKDAYS) < lo.SUB_ADVERB < lo.SUB_INTERJ < lo.RANK_SCALE


# ---------------------------------------------------------------------------------------------------- 2 golden table
def test_golden_table_lo_1(seeded):
    # LEARN_ORDER_VERSION = "lo-1" — the digest below belongs to this version of rank_rows()
    assert lo.LEARN_ORDER_VERSION == "lo-1"
    rows, forms = load_inputs(seeded)
    assert len(rows) == len(GOLDEN) == 62 and all(isinstance(ids, frozenset) for ids in forms.values())
    assert forms["went"] == frozenset({next(r.id for r in rows if r.lemma == "go")})  # exchange form → its one word
    result = rank_rows(rows, forms)
    pairs = sorted((r.lemma, result.ranks[r.id]) for r in rows)
    assert dict(pairs) == GOLDEN
    digest = hashlib.sha256(json.dumps(pairs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert digest == GOLDEN_DIGEST
    # the `how` column of the table and the packing invariant
    how = {r.lemma: r.how for r in result.rows.values()}
    assert how["is"] == "glued:be" and how["absolutely"] == "adverb"
    assert {lemma for lemma, h in how.items() if h == "dealt"} == {"email", "a.m.", "ice cream", "ought to"}
    assert sum(h == "native" for h in how.values()) == len(GOLDEN) - 6
    assert all(pack(r.closed, r.rank, r.sub) == r.learn_rank for r in result.rows.values())
    assert {r.lemma for r in result.rows.values() if r.closed} == {"be", "is", "a", "an", "some", "aboard"}
    # the compact per-stage stats (§2.6): one table per stage code plus 课标外, counts derived from the rows, JSON round trip
    stats = result.stats
    assert set(stats) == set(STAGE_ORDER) | {"none"}
    assert stats["none"]["n"] == sum(r.stage_min is None for r in rows) == 1 and stats["none"]["first8"] == ["bookshelf"]
    for code in STAGE_ORDER:
        idx = stage_to_index(code)
        sel = [r for r in rows if r.stage_min == idx]
        s = stats[code]
        assert s["n"] == len(sel)
        assert s["n"] == s["ranked"] + s["dealt"] + s["set"] + s["glued"] + s["adverb"] + s["interj"]  # every row counted once (none unranked)
        assert s["ranked"] == s["from_frq"] + s["from_bnc"]
        assert s["first8"] == [r.lemma for r in sorted(sel, key=lambda r: order_key(r, result.ranks[r.id]))[:8]]
        assert (s["p10"] is None and not sel) or s["p10"] <= s["p50"] <= s["p90"]
    assert stats["xs"]["glued"] == 1 and stats["xs"]["dealt"] == 2 and stats["cet4"]["adverb"] == 1 and stats["gk"]["from_bnc"] == 1  # is · email, ice cream · absolutely · an
    assert json.loads(json.dumps(stats)) == stats
    assert lo.label_pos_count(rows) == 0  # the mini seed carries ECDICT share distributions or NULL, never a Claude label


# ------------------------------------------------------------------------------------------------------- 3 totality
GARBAGE = [
    {},
    {"id": None, "lemma": None, "pos": None, "frq": None, "bnc": None, "sources": None, "stage_min": None},
    {"id": 1, "lemma": "x", "pos": "n:100", "frq": "12"},
    {"id": 2, "lemma": "x", "frq": "x"},
    {"id": 3, "lemma": "x", "frq": -5},
    {"id": 4, "lemma": "x", "frq": 0},
    {"id": 5, "lemma": "x", "bnc": b"7"},
    {"id": 6, "lemma": "despite", "pos": "v./n.", "frq": 100},
    {"id": 7, "lemma": "x", "pos": "n:x/v:1", "frq": 100},
    {"id": 8, "lemma": "x", "pos": "", "frq": 100},
    {"id": 9, "lemma": "x", "frq": 100, "stage_min": 99},
    {"id": 10, "lemma": "x", "frq": 100, "stage_min": "2"},
    {"id": 11, "lemma": "x", "frq": 100, "sources": None},
    {"id": 12, "lemma": "x", "frq": 100, "sources": "inherit:"},
    {"id": 13, "lemma": "ice-cream cone"},
    {"id": 14, "lemma": "x", "frq": float("inf")},
    {"id": 15, "lemma": "x", "frq": float("nan")},
    {"id": 16, "lemma": "x", "frq": True, "bnc": False},
    {"id": 17, "lemma": "x", "pos": 5, "frq": 12.7},
    {"id": 18, "lemma": 3, "frq": 7},
    {"id": "19", "lemma": "x", "stage_min": True, "frq": 7},
    {"id": 20, "lemma": "x", "stage_min": "zk", "frq": 7},
    {"id": 21, "lemma": "x", "sources": ["inherit:be"], "frq": 7},
    {"id": 22, "lemma": "may", "pos": "v:100", "frq": 150},
    {"id": 23, "lemma": "monday"},
    {"id": 24, "lemma": "very", "pos": "r:100"},
    {"id": 25, "lemma": "be", "sources": "inherit:be", "frq": 2},
]


@pytest.mark.parametrize("garbage", GARBAGE, ids=[str(i) for i in range(len(GARBAGE))])
def test_rank_rows_is_total(garbage):
    w = WordInput.from_row(garbage)
    assert isinstance(w.id, int) and isinstance(w.lemma, str)
    assert w.pos is None or isinstance(w.pos, str)
    assert w.frq is None or isinstance(w.frq, int)
    assert w.bnc is None or isinstance(w.bnc, int)
    assert w.sources is None or isinstance(w.sources, str)
    assert w.stage_min is None or w.stage_min in STAGE_INDEX.values()
    result = rank_rows([w], {})  # alone …
    key = result.ranks[w.id]
    row = result.rows[w.id]
    assert key is None or isinstance(key, int)
    assert (key is None) == (row.how == "unranked") and pack(row.closed, row.rank, row.sub) == key
    assert set(result.stats) == set(STAGE_ORDER) | {"none"} and sum(s["n"] for s in result.stats.values()) == 1
    best = best_effort_rank(garbage)  # … and the per-row shortcut
    assert best is None or isinstance(best, int)
    company = hosts(3) + [W("be", pos="v:100", frq=2), W("january", pos="n:100", bnc=2700), W("not", pos="r:100", frq=10)]
    result = rank_rows([w, *company], {"located": frozenset({company[0].id}), "axes": frozenset({company[1].id, company[2].id})})  # … and in company
    assert set(result.ranks) == {w.id, *(c.id for c in company)}
    assert all(pack(r.closed, r.rank, r.sub) == r.learn_rank for r in result.rows.values())


def test_from_row_coercions_and_the_class_of_garbage_rows():
    assert WordInput.from_row({"frq": "12"}).frq == 12 and WordInput.from_row({"frq": "x"}).frq is None
    assert WordInput.from_row({"bnc": b"7"}).bnc == 7 and WordInput.from_row({"frq": 12.7}).frq == 12
    assert WordInput.from_row({"frq": True}).frq is None and WordInput.from_row({"stage_min": True}).stage_min is None
    assert WordInput.from_row({"stage_min": "2"}).stage_min == 2 and WordInput.from_row({"stage_min": 99}).stage_min is None
    assert WordInput.from_row({"stage_min": 0}).stage_min is None and WordInput.from_row({"stage_min": "zk"}).stage_min is None
    assert WordInput.from_row({}) == WordInput(id=0, lemma="", pos=None, frq=None, bnc=None, sources=None, stage_min=None)
    assert WordInput.from_row({"lemma": 3, "pos": 5, "sources": ["inherit:be"]}) == WordInput(0, "3", "5", None, None, "['inherit:be']", None)
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    row = mem.execute("SELECT 7 AS id, 'cat' AS lemma, 'n:100' AS pos, 1775 AS frq, NULL AS bnc, NULL AS sources, 1 AS stage_min").fetchone()
    assert WordInput.from_row(row) == WordInput(7, "cat", "n:100", 1775, None, None, 1)  # sqlite3.Row works like a mapping
    assert WordInput.from_row(mem.execute("SELECT 'x' AS lemma").fetchone()).frq is None  # a missing column is None, not an error
    # R2 on garbage: text ranks are read, ≤ 0 / NULL / non-numeric are unknown
    assert native_rank("12", None) == 12 and native_rank("x", 7) == 7 and native_rank(-5, 0) is None and native_rank(None, None) is None
    assert native_rank(0, 30) == 30 and native_rank(5, 30) == 5
    # the class of garbage: a label-shaped pos is a content word; a stage outside the enum is the 课标外 group
    label = WordInput.from_row({"id": 6, "lemma": "despite", "pos": "v./n.", "frq": 100})
    assert closed_class(label.lemma, label.pos, label.sources) is False
    result = rank_rows([label], {})
    assert result.rows[6].closed is False and result.rows[6].cls == "plain" and result.ranks[6] == pack(False, 100, 0)
    outside = WordInput.from_row({"id": 9, "lemma": "x", "frq": 100, "stage_min": 99})
    result = rank_rows([outside], {})
    assert result.rows[9].stage_min is None and result.stats["none"]["n"] == 1 and all(result.stats[c]["n"] == 0 for c in STAGE_ORDER)
    direct = WordInput(id=10, lemma="x", pos=None, frq=100, bnc=None, sources=None, stage_min=99)  # built without from_row
    assert rank_rows([direct], {}).rows[10].stage_min is None
    assert lo.inherit_head("inherit:") is None and lo.inherit_head("inherit:be moe22:l2") == "be" and lo.inherit_head(None) is None
    assert lo.inherit_head("moe22:l2 inherit:do inherit:be") == "do"  # the first token wins
    assert closed_class("x", None, "inherit:") is False and closed_class("x", None, "inherit:be") is True


# ------------------------------------------------------------------------------------------------------- 4 dealing
def test_dealing_formula():
    assert [lo.deal_index(k, 10, 4) for k in range(1, 5)] == [2, 4, 7, 9]  # ceil((k − ½) · 10 / 4)
    assert [lo.deal_index(k, 2, 5) for k in range(1, 6)] == [1, 1, 1, 2, 2]  # n_u > n_r shares hosts: ceil((k − ½) · 2 / 5)
    assert lo.deal_index(1, 7, 1) == 4 and lo.deal_index(1, 1, 1) == 1 and lo.deal_index(3, 3, 3) == 3  # clamped to 1..n_r
    # a group with ten hosts (go 100, locate 300, 400 … 1100) and four frequency-less plain rows
    go = W("go", pos="v:100", frq=100)
    locate = W("locate", pos="v:100", frq=300)
    others = [W(f"host{i:02d}", pos="n:100", frq=100 * i) for i in range(4, 12)]
    be = W("be", pos="v:100", frq=2)  # closed (R1b): another group, but a resolvable token
    ax, axis = W("ax", pos="n:90/v:10", frq=11322, stage_min=4), W("axis", pos="n:100", frq=5598, stage_min=4)
    go_on = W("go on")  # `go` resolves through words.lemma → token rank 100; `on` has no row
    be_located = W("be located")  # `located` resolves through word_forms → locate 300; `be` → 2: the rarest token wins → 300
    axes_thing = W("axes thing")  # `axes` points at two words (ax, axis): ambiguous, does not resolve → no token rank
    email = W("email")  # the only token is the row itself: skipped → no token rank
    rows = [go, locate, *others, be, ax, axis, go_on, be_located, axes_thing, email]
    forms = {"located": frozenset({locate.id}), "axes": frozenset({ax.id, axis.id}), "email": frozenset({email.id})}
    result = rank_rows(rows, forms)
    keys = {r.lemma: result.ranks[r.id] for r in rows}
    # unranked order (token_rank IS NULL, token_rank, lemma): go on 100 · be located 300 · axes thing · email → hosts 2 4 7 9
    assert keys["go on"] == pack(False, 300, lo.SUB_DEALT) == 30020  # host 2 = locate
    assert keys["be located"] == pack(False, 500, lo.SUB_DEALT)  # host 4
    assert keys["axes thing"] == pack(False, 800, lo.SUB_DEALT)  # host 7
    assert keys["email"] == pack(False, 1000, lo.SUB_DEALT)  # host 9
    assert all(result.rows[r.id].how == "dealt" and result.rows[r.id].cls == "plain" for r in (go_on, be_located, axes_thing, email))
    # a dealt word sorts right after its host and before the next host (sub 20)
    order = ordered(result, rows, stage_min=1, closed=False)
    assert order[:4] == ["go", "locate", "go on", "host04"]
    assert order.index("be located") == order.index("host05") + 1 and order.index("host06") == order.index("be located") + 1
    assert order.index("axes thing") == order.index("host08") + 1 and order.index("email") == order.index("host10") + 1
    assert keys["be"] == pack(True, 2, 0) and result.rows[be.id].closed  # the token donor keeps its own closed key
    # n_r = 0: nothing to deal onto → NULL (R4), never an error
    result = rank_rows([W("have to"), W("get up")], {})
    assert set(result.ranks.values()) == {None} and {r.how for r in result.rows.values()} == {"unranked"}
    # n_u > n_r: hosts are shared; frequency-less rows never displace a host
    small = hosts(2)
    phrases = [W(f"phrase {c}") for c in "abcde"]
    result = rank_rows(small + phrases, {})
    assert [result.ranks[p.id] for p in phrases] == [pack(False, 100, 20)] * 3 + [pack(False, 200, 20)] * 2
    assert ordered(result, small + phrases, stage_min=1, closed=False) == ["host01", "phrase a", "phrase b", "phrase c", "host02", "phrase d", "phrase e"]


# ------------------------------------------------------------------------------------------------- 5 calendar sets
def test_calendar_sets():
    hs = hosts(5)  # ranks 100 … 500
    month_ranks = {
        "january": 2700, "february": None, "march": 3100, "april": 2900, "may": 150, "june": 3300, "july": None, "august": 2600,
        "september": 3600, "october": 3000, "november": 3800, "december": 3400,
    }
    months = [W(m, pos=("v:100" if m == "may" else "n:100"), bnc=rk) for m, rk in month_ranks.items()]
    weekdays = [W(d, pos="n:100") for d in reversed(lo.WEEKDAYS)]  # no member has a rank → the dealing fallback
    rows = hs + months + weekdays
    result = rank_rows(rows, {})
    rank_of = by_lemma(result, rows)
    anchor = statistics.median_low([rk for rk in month_ranks.values() if rk is not None])
    for ordinal, m in enumerate(lo.MONTHS, 1):
        row = rank_of[m]
        assert (row.closed, row.cls, row.how, row.rank, row.sub) == (False, "set", "set", anchor, lo.SUB_MONTH_BASE + ordinal)
        assert row.learn_rank == pack(False, anchor, 20 + ordinal)  # subs 21..32, one block at the anchor
    assert rank_of["may"].closed is False and closed_class("may", "v:100", None) is False and closed_class("may", "i:100", None) is False
    assert closed_class("might", "v:100", None) is True  # the modal list still applies to a non-calendar lemma
    assert rank_of["february"].learn_rank is not None  # a member without a rank takes the anchor too
    order = ordered(result, rows, stage_min=1, closed=False)
    first = order.index("january")
    assert order[first : first + 12] == list(lo.MONTHS)  # contiguous, calendar order
    # weekdays: no rank at all → dealt in calendar order onto the hosts with the step-2 formula, keeping the calendar sub 33..39
    for k, d in enumerate(lo.WEEKDAYS, 1):
        row = rank_of[d]
        host = hs[lo.deal_index(k, len(hs), len(lo.WEEKDAYS)) - 1]
        assert (row.cls, row.how, row.rank, row.sub) == ("set", "set-dealt", host.frq, lo.SUB_WEEKDAY_BASE + k)
        assert row.learn_rank == pack(False, host.frq, 32 + k)
    positions = [order.index(d) for d in lo.WEEKDAYS]
    assert positions == sorted(positions)  # calendar-ordered across hosts
    # 5 hosts over 7 days: ceil((k − ½)·5/7) = 1 2 2 3 4 4 5 — tuesday and wednesday share host 2, saturday follows friday on host 4
    assert [lo.deal_index(k, 5, 7) for k in range(1, 8)] == [1, 2, 2, 3, 4, 4, 5]
    assert order.index("wednesday") == order.index("tuesday") + 1 == order.index("host02") + 2
    assert order.index("saturday") == order.index("friday") + 1 == order.index("host04") + 2
    # a calendar word is never closed even with a closed pos, and sets without hosts and without ranks are NULL
    result = rank_rows([W(d, pos="i:100") for d in lo.WEEKDAYS], {})
    assert set(result.ranks.values()) == {None} and all(r.closed is False and r.cls == "set" for r in result.rows.values())
    # a set with ranks needs no hosts
    result = rank_rows([W("june", pos="n:100", bnc=3300), W("july", pos="n:100")], {})
    assert [result.ranks[i] for i in sorted(result.ranks)] == [pack(False, 3300, 26), pack(False, 3300, 27)]


# -------------------------------------------------------------------------------------------------- 6 glued forms
def test_glued_forms():
    be = W("be", pos="v:100", frq=2)
    am, are, is_ = W("am", sources="inherit:be", bnc=5000), W("are", sources="inherit:be moe22:l2"), W("is", sources="inherit:be", bnc=24648)
    cat = W("cat", pos="n:100", frq=1775)
    rows = [is_, are, am, be, cat]
    result = rank_rows(rows, {})
    key_be = result.ranks[be.id]
    assert key_be == pack(True, 2, 0) == 10000200
    assert (result.ranks[am.id], result.ranks[are.id], result.ranks[is_.id]) == (key_be + 1, key_be + 2, key_be + 3)  # j by lemma
    for form, j in ((am, 1), (are, 2), (is_, 3)):
        row = result.rows[form.id]
        assert (row.closed, row.cls, row.how, row.rank, row.sub) == (True, "glued", "glued:be", 2, j)
    assert ordered(result, rows, stage_min=1, closed=True) == ["be", "am", "are", "is"]
    # the form's own frq / bnc / pos are ignored
    loud = W("is", sources="inherit:be", frq=50, bnc=1, pos="i:100")
    assert rank_rows([be, loud], {}).ranks[loud.id] == key_be + 1
    # an absent head: the row is plain and R1c makes it closed, ranked on its own
    does = W("does", sources="inherit:do", frq=300)
    result = rank_rows([does, cat], {})
    assert result.ranks[does.id] == pack(True, 300, 0)
    assert (result.rows[does.id].closed, result.rows[does.id].cls, result.rows[does.id].how) == (True, "plain", "native")
    # the head's key is NULL → the form is NULL too (R4)
    be_blank = W("be", pos="v:100")
    result = rank_rows([be_blank, W("am", sources="inherit:be", bnc=5000)], {})
    assert set(result.ranks.values()) == {None}
    # a head that is itself glued is followed; a cycle gives NULL and never raises; a self-reference is plain (R1c)
    do = W("do", pos="v:100", frq=40)
    did, done = W("did", sources="inherit:do"), W("done", sources="inherit:did")
    result = rank_rows([do, did, done], {})
    assert result.ranks[did.id] == pack(True, 40, 1) and result.ranks[done.id] == pack(True, 40, 1) + 1
    a, b = W("aa", sources="inherit:bb", frq=10), W("bb", sources="inherit:aa", frq=20)
    result = rank_rows([a, b, cat], {})
    assert result.ranks[a.id] is None and result.ranks[b.id] is None and result.ranks[cat.id] == pack(False, 1775, 0)
    selfie = W("be", sources="inherit:be", frq=2)
    result = rank_rows([selfie], {})
    assert result.rows[selfie.id].cls == "plain" and result.ranks[selfie.id] == pack(True, 2, 0)


# ------------------------------------------------------------------------------------- 7 adverbs and interjections
def test_adverbs_and_interjections_are_dealt():
    hs = hosts(10)  # 100 … 1000
    adverbs = [W("very", pos="r:100", frq=105), W("not", pos="r:100", frq=10), W("here", pos="r:100", frq=400), W("yonder", pos="r:100")]
    interjs = [W("hello", pos="u:100", frq=3000), W("yes", pos="u:100", frq=50)]
    must = W("must", pos="r:100", frq=200)  # adverb-tagged but in CLOSED_LEMMAS → R1b: closed, plain, native
    rows = hs + adverbs + interjs + [must]
    result = rank_rows(rows, {})
    rank_of = by_lemma(result, rows)
    # adverbs keep frequency order among themselves (not 10 · very 105 · here 400 · yonder —) and take hosts 2 4 7 9 with sub 40
    for lemma, host_rank in (("not", 200), ("very", 400), ("here", 700), ("yonder", 900)):
        row = rank_of[lemma]
        assert (row.cls, row.how, row.sub, row.learn_rank) == ("adverb", "adverb", 40, pack(False, host_rank, 40))
    assert rank_of["not"].learn_rank < rank_of["very"].learn_rank < rank_of["here"].learn_rank < rank_of["yonder"].learn_rank
    # interjections: yes 50 · hello 3000 → hosts ceil(2.5) = 3 and ceil(7.5) = 8, sub 50
    assert rank_of["yes"].learn_rank == pack(False, 300, 50) and rank_of["hello"].learn_rank == pack(False, 800, 50)
    assert rank_of["yes"].cls == "interj" == rank_of["hello"].cls and rank_of["hello"].how == "interj"
    assert all(rank_of[lemma].closed is False for lemma in ("not", "very", "here", "yonder", "yes", "hello"))
    order = ordered(result, rows, stage_min=1, closed=False)
    assert order.index("not") == order.index("host02") + 1 and order.index("yes") == order.index("host03") + 1
    assert order.index("hello") == order.index("host08") + 1 and order.index("yonder") == order.index("host09") + 1
    # the closed-list adverb follows R1b: closed group, its own rank, not dealt
    assert (rank_of["must"].closed, rank_of["must"].cls, rank_of["must"].how, rank_of["must"].learn_rank) == (True, "plain", "native", pack(True, 200, 0))
    assert ordered(result, rows, stage_min=1, closed=True) == ["must"]
    # a closed pos is not an adverb either (`up` as a preposition stays closed); groups are per stage
    up = W("up", pos="i:60/r:40", frq=50)
    far = W("far", pos="r:100", frq=600, stage_min=2)
    result = rank_rows(hs + [up, far] + hosts(2, stage_min=2, step=1000), {})
    assert result.rows[up.id].closed is True and result.rows[up.id].cls == "plain" and result.ranks[up.id] == pack(True, 50, 0)
    assert result.ranks[far.id] == pack(False, 1000, 40)  # dealt onto the hosts of its own stage (2), not stage 1's
    # without hosts an adverb keeps its own key (tiny fixtures); without a rank it is NULL
    result = rank_rows([W("very", pos="r:100", frq=105), W("yonder", pos="r:100")], {})
    assert sorted(result.ranks.values(), key=lambda k: (k is None, k or 0)) == [pack(False, 105, 0), None]


# ------------------------------------------------------------------------------------------------------- 8 packing
def test_packing_bounds_and_order():
    max_rank = lo.CLOSED_BASE // lo.RANK_SCALE - 1  # 99,999: every five-digit COCA / BNC rank packs below CLOSED_BASE
    assert pack(True, max_rank, 99) < 2 * lo.CLOSED_BASE
    assert pack(False, max_rank, 99) < pack(True, 1, 0)  # every content key before every closed key
    assert pack(False, 1, 0) == 100 and pack(True, 1, 0) == 10_000_100 and pack(False, 46049, 99) == 4_604_999
    assert pack(False, None, 0) is None and pack(True, None, 50) is None
    keys = [pack(False, r, s) for r in range(1, 40) for s in range(0, lo.RANK_SCALE)]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)  # monotone in (rank, sub), injective
    assert pack(False, 5, lo.RANK_SCALE - 1) < pack(False, 6, 0)  # a sub never crosses into the next rank
    assert pack(True, 5, 0) - pack(False, 5, 0) == lo.CLOSED_BASE
    at_rank = [pack(False, 7, s) for s in (lo.SUB_NATIVE, lo.SUB_GLUED_BASE + 1, lo.SUB_DEALT, lo.SUB_MONTH_BASE + 1, lo.SUB_WEEKDAY_BASE + 1, lo.SUB_ADVERB, lo.SUB_INTERJ)]
    assert at_rank == sorted(at_rank)  # native < glued < dealt < months < weekdays < adverb < interjection at one rank (A19)


# ---------------------------------------------------------------------------------------------- 9 stage distance
def test_stage_distance_and_sql():
    assert lo.stage_distance(None, 1) == lo.STAGE_NULL_DISTANCE == 11
    table = {(s, cur): lo.stage_distance(s, cur) for s in (None, 1, 2, 3, 4, 5) for cur in range(1, 6)}
    # the M4 table: 0 for the 主攻阶段, higher stages at odd distances, lower ones at even distances, NULL beyond every stage
    assert [table[(s, 2)] for s in (1, 2, 3, 4, 5, None)] == [2, 0, 1, 3, 5, 11]
    assert [table[(s, 1)] for s in (1, 2, 3, 4, 5, None)] == [0, 1, 3, 5, 7, 11]
    assert [table[(s, 5)] for s in (1, 2, 3, 4, 5, None)] == [8, 6, 4, 2, 0, 11]
    for cur in range(1, 6):
        distances = [table[(s, cur)] for s in range(1, 6)]
        assert len(set(distances)) == 5 and max(distances) < lo.STAGE_NULL_DISTANCE  # a total order with NULL last
    sql = lo.stage_distance_sql()
    assert sql == (
        f"CASE WHEN w.stage_min IS NULL THEN {lo.STAGE_NULL_DISTANCE} WHEN w.stage_min = :cur THEN 0 "
        "WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END"
    )
    mem = sqlite3.connect(":memory:")
    for (s, cur), want in table.items():
        got = mem.execute(f"SELECT {sql} FROM (SELECT :sm AS stage_min) AS w", {"sm": s, "cur": cur}).fetchone()[0]
        assert got == want, (s, cur)
    other = lo.stage_distance_sql(":c", "x")
    assert other.startswith(f"CASE WHEN x.stage_min IS NULL THEN {lo.STAGE_NULL_DISTANCE} WHEN x.stage_min = :c THEN 0")
    assert mem.execute(f"SELECT {other} FROM (SELECT 4 AS stage_min) AS x", {"c": 2}).fetchone()[0] == 3
    assert lo.default_cur("all") == lo.default_cur(None) == stage_to_index(STAGE_ORDER[0]) == 1
    assert lo.default_cur("zk") == 2 and [lo.default_cur(s) for s in STAGE_ORDER] == [stage_to_index(s) for s in STAGE_ORDER]
    with pytest.raises(ValueError):
        lo.default_cur("nope")


# ------------------------------------------------------------------------------------------ 10 best_effort_rank
def test_best_effort_rank_equals_rank_rows_for_natively_ranked_rows(seeded):
    rows, forms = load_inputs(seeded)
    result = rank_rows(rows, forms)
    db_rows = {r["lemma"]: r for r in seeded.execute("SELECT * FROM words")}  # sqlite3.Row, as _insert_word's params would be a dict
    natives = [r for r in result.rows.values() if r.how == "native"]
    assert len(natives) == len(GOLDEN) - 6
    for r in natives:
        assert best_effort_rank(db_rows[r.lemma]) == r.learn_rank == GOLDEN[r.lemma], r.lemma
    for r in result.rows.values():
        if r.how == "native":
            continue
        row = db_rows[r.lemma]
        own = native_rank(row["frq"], row["bnc"])
        want = None if own is None else pack(closed_class(row["lemma"], row["pos"], row["sources"]), own, lo.SUB_NATIVE)
        assert best_effort_rank(row) == want and best_effort_rank(row) != r.learn_rank, r.lemma  # the native-rank key or None, never the dealt key
    assert best_effort_rank(db_rows["email"]) is None and best_effort_rank(db_rows["absolutely"]) == pack(False, 1149, 0)
    # the shapes services/words._insert_word hands over: no id, a provisional row without frequency, an ECDICT hit, a function word
    assert best_effort_rank({"lemma": "zzz", "pos": None, "frq": None, "bnc": None, "sources": None, "stage_min": None}) is None
    assert best_effort_rank({"lemma": "quokka", "pos": "n:100", "frq": 30000, "bnc": 40000}) == pack(False, 30000, 0)
    assert best_effort_rank({"lemma": "despite", "pos": "i:100", "frq": 1000}) == pack(True, 1000, 0)
    assert best_effort_rank({"lemma": "may", "pos": "v:100", "frq": 150}) == pack(False, 150, 0)  # M1 precedence applies here too
    assert best_effort_rank({}) is None


# ------------------------------------------------------------------------------- 2b synthetic golden digest (F-4)
def synthetic_rows() -> tuple[list[WordInput], dict[str, frozenset[int]]]:
    """A row set that exercises EVERY rule of DESIGN §1.3 — what the mini seed lacks: twelve months with an even number of ranked
    members (so median_low ≠ median_high) incl. `may` / `march` / `august` with non-noun pos, rank-less weekdays (the dealing
    fallback), interjections with and without a rank, phrase tokens that resolve through a lemma, through a unique word_forms form,
    through a rank-less row, not at all (ambiguous form, self), a 课标外 donor row (`cream` for `ice-cream cone`), a closed group with
    a frequency-less row (`thee`), BNC rescue, a Claude label, glue (`be` / `do` families incl. the `done → did → do` chain and an
    absent head), two more stages and garbage inputs. Lemmas are unique, as in the words table; keys never depend on ids."""
    xs_hosts = [W(f"xs{i:02d}", pos="n:100", frq=frq) for i, frq in enumerate((100, 250, 480, 500, 760, 900, 1100, 1300, 2600), 1)]
    donors = [W("go", pos="v:100", frq=120), W("locate", pos="v:100", frq=300), W("education", pos="n:100", frq=1700)]
    colour, despite = W("colour", pos="n:100", bnc=642), W("despite", pos="v./n.", frq=5000)  # BNC rescue · a Claude label is a content word
    phrases = [W("go on"), W("be located"), W("axes thing"), W("email"), W("ice-cream cone"), W("physical education"), W("kung fu"), W("ought to")]
    month_pos = {"may": "v:100", "march": "v:100", "august": "j:100"}
    months = [W(m, pos=month_pos.get(m, "n:100"), bnc=rk) for m, rk in zip(lo.MONTHS, (2700, None, 3100, 2900, None, 3300, None, 2600, 3600, 3000, None, 3800))]
    weekdays = [W(d, pos="n:100") for d in reversed(lo.WEEKDAYS)]
    adverbs = [W("not", pos="r:100", frq=10), W("very", pos="r:100", frq=105), W("here", pos="r:100", frq=400), W("yonder", pos="r:100")]
    interjs = [W("yes", pos="u:100", frq=50), W("hello", pos="u:100", frq=3000), W("oops", pos="u:100")]
    closed = [
        W("the", pos="a:100", frq=1), W("be", pos="v:100", frq=2), W("to", pos="t:100", frq=5), W("on", pos="i:100", frq=30), W("do", pos="v:100", frq=40),
        W("up", pos="i:60/r:40", frq=50), W("must", pos="r:100", frq=200), W("has", sources="inherit:have", frq=300), W("ought", pos="v:100", frq=900),
        W("an", bnc=30), W("thee", pos="p:100"),
    ]
    glued = [
        W("am", sources="inherit:be", bnc=5000), W("are", sources="inherit:be moe22:l2"), W("is", sources="inherit:be", frq=50, bnc=24648, pos="i:100"),
        W("does", sources="inherit:do"), W("did", sources="inherit:do"), W("done", sources="inherit:did"),
    ]
    zk = [W(f"zk{i:02d}", pos="n:100", frq=1000 * i, stage_min=2) for i in range(1, 7)] + [
        W("have to", stage_min=2), W("the pacific ocean", stage_min=2), W("look after", stage_min=2),
        W("far", pos="r:100", frq=600, stage_min=2), W("although", pos="c:100", frq=2300, stage_min=2), W("if", pos="c:100", frq=40, stage_min=2),
    ]
    upper = [W("ax", pos="n:90/v:10", frq=11322, stage_min=4), W("axis", pos="n:100", frq=5598, stage_min=4), W("absorption", pos="n:100", frq=8596, stage_min=5), W("yeah", pos="u:100", frq=6420, stage_min=5)]
    none = [
        W("bookshelf", pos="n:100", frq=11170, stage_min=None), W("cream", pos="n:100", frq=2100, stage_min=None), W("zzz", stage_min=None),
        WordInput.from_row({"id": next(_ids), "lemma": "gamma", "frq": 777, "stage_min": 99}), WordInput.from_row({"id": next(_ids), "lemma": "delta", "frq": "12", "stage_min": "2"}),
    ]
    rows = [*xs_hosts, *donors, colour, despite, *phrases, *months, *weekdays, *adverbs, *interjs, *closed, *glued, *zk, *upper, *none]
    assert len({r.lemma for r in rows}) == len(rows)
    by = {r.lemma: r.id for r in rows}
    forms = {"located": frozenset({by["locate"]}), "axes": frozenset({by["ax"], by["axis"]}), "email": frozenset({by["email"]}), "went": frozenset({by["go"]}), "fu": frozenset({by["zzz"]})}
    return rows, forms


def digest_of(rows: list[WordInput], result: RankResult) -> str:
    pairs = sorted((r.lemma, result.ranks[r.id]) for r in rows)
    return hashlib.sha256(json.dumps(pairs, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def test_golden_digest_lo_1_over_the_synthetic_rule_set():
    """The version-bump guard for the rules the mini seed cannot reach (F-4): M1 (median_low anchor, calendar subs, the dealing
    fallback), G5 (SUB_INTERJ), R3 token resolution through lemma / word_forms, M2 glue incl. chains, the closed-group dealing.
    Editing any of them without bumping LEARN_ORDER_VERSION fails here; bump the version, regenerate both digests and
    data/seed/learn_order.json together."""
    assert lo.LEARN_ORDER_VERSION == "lo-1"
    rows, forms = synthetic_rows()
    result = rank_rows(rows, forms)
    assert digest_of(rows, result) == SYNTHETIC_DIGEST
    assert rank_rows(list(reversed(rows)), forms).ranks == result.ranks  # row order never matters
    how = {r.lemma: result.rows[r.id].how for r in rows}
    assert {m for m in lo.MONTHS if how[m] == "set"} == set(lo.MONTHS) and {d for d in lo.WEEKDAYS if how[d] == "set-dealt"} == set(lo.WEEKDAYS)
    assert result.rows[next(r.id for r in rows if r.lemma == "january")].rank == statistics.median_low([2700, 3100, 2900, 3300, 2600, 3600, 3000, 3800]) == 3000
    assert {lemma for lemma, h in how.items() if h == "interj"} == {"yes", "hello", "oops", "yeah"} and {lemma for lemma, h in how.items() if h == "adverb"} == {"not", "very", "here", "yonder", "far"}
    assert {lemma for lemma, h in how.items() if h == "dealt"} == {"go on", "be located", "axes thing", "email", "ice-cream cone", "physical education", "kung fu", "ought to", "thee", "have to", "the pacific ocean", "look after", "zzz"}
    assert how["is"] == "glued:be" and how["does"] == "glued:do" and how["done"] == "glued:did" and how["has"] == "native"
    assert result.rows[next(r.id for r in rows if r.lemma == "kung fu")].rank is not None  # `fu` resolves to the rank-less `zzz`: no token rank, still dealt
    assert {r.lemma for r in rows if result.rows[r.id].closed} == {"the", "be", "to", "on", "do", "up", "must", "has", "ought", "an", "thee", "am", "are", "is", "does", "did", "done", "although", "if"}
    assert result.rows[next(r.id for r in rows if r.lemma == "gamma")].stage_min is None and result.rows[next(r.id for r in rows if r.lemma == "delta")].stage_min == 2
    assert all(pack(r.closed, r.rank, r.sub) == r.learn_rank for r in result.rows.values())


# -------------------------------------------------------------------------------------- committed artefact (ARCH-1)
def test_committed_report_stamps_match_the_code():
    """data/seed/learn_order.json (`wd learn-order --report` on the seed-only database, DESIGN §2.8) describes THIS policy over THIS
    seed: always on, so a policy bump or a seed change that forgets to regenerate it fails here and not only under WD_FULL_SEED_DB.
    No seed number is typed — the document is compared with the code and with data/seed/stats.json."""
    report = json.loads((REPO / "data" / "seed" / "learn_order.json").read_text(encoding="utf-8"))
    stats = json.loads((REPO / "data" / "seed" / "stats.json").read_text(encoding="utf-8"))
    assert list(report) == ["policy", "seed", "computed_at", "generated_by", "stages", "acceptance"]
    assert report["policy"] == lo.LEARN_ORDER_VERSION and report["seed"] == stats["content_sha256"] and report["generated_by"] == "wd learn-order --report"
    assert isinstance(report["computed_at"], str) and report["computed_at"].endswith("Z")
    assert list(report["stages"]) == [*STAGE_ORDER, lo.STATS_NONE]
    for code, s in report["stages"].items():
        assert list(s) == ["n", "ranked", "dealt", "set", "glued", "adverb", "interj", "closed", "p10", "p50", "p90", "first"]
        assert s["n"] == stats["first_stage"][code] == s["ranked"] + s["dealt"] + s["set"] + s["glued"] + s["adverb"] + s["interj"]  # every row placed by one rule
        assert len(s["first"]) == min(lo.REPORT_FIRST, s["n"]) and len(set(s["first"])) == len(s["first"])
    assert sum(s["n"] for s in report["stages"].values()) == stats["total_words"]
    acc = report["acceptance"]
    assert list(acc) == ["closed_in_first_30", "xs_adverbs_first_30", "xs_months_positions", "zk_phrases_first_200", "longest_frq_null_run"]
    assert set(acc["closed_in_first_30"]) == set(STAGE_ORDER) == set(acc["longest_frq_null_run"]) and len(acc["xs_months_positions"]) == len(lo.MONTHS)
