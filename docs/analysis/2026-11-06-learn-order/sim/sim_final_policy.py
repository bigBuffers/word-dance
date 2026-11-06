#!/usr/bin/env python3
"""FINAL learning-order policy (docs/analysis/2026-11-06-learn-order/DESIGN.md §1) — reference simulation.

purist R1–R5 + M1 calendar sets + M2 glued inherited forms + M3 adverbs dealt evenly + G5 interjections dealt evenly,
packed into ONE integer key  learn_rank = closed·10^7 + rank·100 + sub  (NULL when the row has no rank at all), and the
stage distance with NULL → 11 (M4).  Three runs:
  A. the READ-ONLY live copy: first 30 per stage, acceptance counts, probe positions, 词库 全部 under the stage prefix;
  B. a scratch copy (sqlite backup API, deleted at the end): ALTER TABLE ADD COLUMN learn_rank, UPDATE, SQL ORDER BY ==
     Python order for every list shape, the C10 trap row, timings;
  C. the mini seed imported with the REAL importer into a fresh migrated database: the golden table + digest.
A tuple-key re-implementation of the judge's purist+grafts order is kept as an independent cross-check (same order).
Run: /Users/sqin/word-dance/.venv/bin/python -I sim_final_policy.py   → sim_output.txt + mini_seed_golden.json here.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import Counter
from statistics import median_low

from wd import db as wddb
from wd.images.style import FUNCTION_POS, dominant_pos
from wd.schemas import STAGE_ORDER, stage_to_index
from wd.seed import import_seed

HERE = os.path.dirname(os.path.abspath(__file__))
LIVE = ("file:/private/tmp/claude-501/-Users-sqin-word-dance/0be1d882-e939-4b1e-8c2e-b69435664161/"
        "scratchpad/deploy/precheck/word-dance.db?mode=ro&immutable=1")
MINI_SEED = "/Users/sqin/word-dance/backend/tests/fixtures/mini_seed.jsonl"
OUT: list[str] = []


def P(*a):
    s = " ".join(str(x) for x in a)
    OUT.append(s)
    print(s)


# ----------------------------------------------------------------------------------------------- the policy constants
ORDER_CLOSED_POS = FUNCTION_POS - {"u"}                      # G5: interjections leave the ORDER gate (image gate unchanged)
CLOSED_LEMMAS = frozenset("a an the be do have can could will would shall should may might must ought".split())  # 16
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
CALENDAR = {**{m: ("month", i + 1) for i, m in enumerate(MONTHS)}, **{d: ("weekday", i + 1) for i, d in enumerate(WEEKDAYS)}}
SUB_NATIVE, SUB_GLUED_BASE, SUB_DEALT, SUB_MONTH_BASE, SUB_WEEKDAY_BASE, SUB_ADVERB, SUB_INTERJ = 0, 0, 20, 20, 32, 40, 50
CLOSED_BASE, RANK_SCALE = 10_000_000, 100
STAGE_NULL_DISTANCE = 2 * len(STAGE_ORDER) + 1               # 11: beyond every stage (M4)
AUX_FACTS = set("be am is are was were been being do does did done have has had can could will would shall should may might must ought".split())


def to_rank(v):
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def native_rank(frq, bnc):
    return to_rank(frq) or to_rank(bnc)


def inherit_head(sources):
    for t in str(sources or "").split():
        if t.startswith("inherit:") and len(t) > 8:
            return t[8:]
    return None


def is_closed(lemma, pos, sources):
    if lemma in CALENDAR:
        return False                                          # M1 precedence over the modal list (`may`) and pos (`march`)
    return dominant_pos(pos) in ORDER_CLOSED_POS or lemma in CLOSED_LEMMAS or inherit_head(sources) is not None


def pack(closed, rank, sub):
    return None if rank is None else (CLOSED_BASE if closed else 0) + rank * RANK_SCALE + sub


def deal(unranked, hosts):
    """R3: the k-th of n_u goes right after host ceil((k − ½)·n_r/n_u) (1-based, clamped). Returns {id: host_rank}."""
    n_r, n_u = len(hosts), len(unranked)
    out = {}
    if n_r == 0:
        return out
    for k, w in enumerate(unranked, 1):
        idx = min(n_r, max(1, math.ceil((k - 0.5) * n_r / n_u)))
        out[w["id"]] = hosts[idx - 1]["rank"]
    return out


def rank_rows(rows, forms):
    """rows: dicts with id lemma pos frq bnc sources stage_min; forms: {form: {word_id,...}} → {id: learn_rank|None}, info."""
    by_lemma = {r["lemma"]: r for r in rows}
    by_id = {r["id"]: r for r in rows}
    work = {}
    for r in rows:
        head = inherit_head(r["sources"])
        glue_head = head if (head in by_lemma and head != r["lemma"]) else None
        closed = is_closed(r["lemma"], r["pos"], r["sources"])
        dp = dominant_pos(r["pos"])
        if r["lemma"] in CALENDAR:
            cls = "set"
        elif glue_head is not None:
            cls = "glued"
        elif not closed and dp == "r":
            cls = "adverb"
        elif not closed and dp == "u":
            cls = "interj"
        else:
            cls = "plain"
        work[r["id"]] = dict(r, closed=closed, rank=native_rank(r["frq"], r["bnc"]), sub=SUB_NATIVE, cls=cls, glue_head=glue_head, how="native")

    def resolve(token):
        r = by_lemma.get(token)
        if r is not None:
            return r
        ids = forms.get(token)
        if ids and len(ids) == 1:
            return by_id.get(next(iter(ids)))
        return None

    def token_rank(w):
        best = None
        for t in w["lemma"].replace("-", " ").split():
            h = resolve(t)
            if h is None or h["lemma"] == w["lemma"]:
                continue
            rk = native_rank(h["frq"], h["bnc"])
            if rk is not None and (best is None or rk > best):
                best = rk
        return best

    groups = {}
    for w in work.values():
        if w["cls"] != "glued":
            groups.setdefault((w["stage_min"], w["closed"]), []).append(w)
    for grp in groups.values():
        plain = [w for w in grp if w["cls"] == "plain"]
        hosts = sorted((w for w in plain if w["rank"] is not None), key=lambda w: (w["rank"], w["lemma"]))
        unranked = [w for w in plain if w["rank"] is None]
        for w in unranked:
            w["token_rank"] = token_rank(w)
        unranked.sort(key=lambda w: (w["token_rank"] is None, w["token_rank"] or 0, w["lemma"]))
        for wid, rk in deal(unranked, hosts).items():
            work[wid].update(rank=rk, sub=SUB_DEALT, how="dealt")
        for members, base in ((MONTHS, SUB_MONTH_BASE), (WEEKDAYS, SUB_WEEKDAY_BASE)):
            present = [w for w in grp if w["cls"] == "set" and w["lemma"] in members]
            if not present:
                continue
            ranks = [w["rank"] for w in present if w["rank"] is not None]
            if ranks:
                anchor = median_low(ranks)
                for w in present:
                    w.update(rank=anchor, sub=base + members.index(w["lemma"]) + 1, how="set")  # 1-based ordinal (DESIGN §1.2: months 21..32, weekdays 33..39; review N-7)
            else:
                dealt = deal(sorted(present, key=lambda w: members.index(w["lemma"])), hosts)
                for w in present:
                    w.update(rank=dealt.get(w["id"]), sub=base + members.index(w["lemma"]) + 1, how="set-dealt")  # 1-based (N-7)
        for cls, sub in (("adverb", SUB_ADVERB), ("interj", SUB_INTERJ)):
            pool = sorted((w for w in grp if w["cls"] == cls), key=lambda w: (w["rank"] is None, w["rank"] or 0, w["lemma"]))
            for wid, rk in deal(pool, hosts).items():
                work[wid].update(rank=rk, sub=sub, how=cls)
            for w in pool:
                if w["id"] not in {x["id"] for x in pool} or w["rank"] is None:
                    pass
    keys = {}
    for w in work.values():
        if w["cls"] != "glued":
            keys[w["id"]] = pack(w["closed"], w["rank"], w["sub"])
    for w in work.values():
        if w["cls"] == "glued":
            head = by_lemma[w["glue_head"]]
            siblings = sorted(x["lemma"] for x in work.values() if x["glue_head"] == w["glue_head"])
            hk = keys[head["id"]]
            keys[w["id"]] = None if hk is None else hk + SUB_GLUED_BASE + 1 + siblings.index(w["lemma"])
            w.update(closed=work[head["id"]]["closed"], how=f"glued:{w['glue_head']}")
    return keys, work


# ------------------------------------------------------------------------------------- judge.py tuple key (cross-check)
PUR_CLOSED_LEMMAS = CLOSED_LEMMAS


def judge_keys(rows, forms):
    """Verbatim logic of sim-judge/judge.py purist_keys(grafts={'sets','glue','adverbs-even','interj-even'}) → tuple keys."""
    by_lemma = {r["lemma"]: r for r in rows}
    by_id = {r["id"]: r for r in rows}

    def pur_closed(r):
        return dominant_pos(r["pos"]) in FUNCTION_POS or r["lemma"] in PUR_CLOSED_LEMMAS or any(t.startswith("inherit:") for t in (r["sources"] or "").split())

    def resolve(token):
        r = by_lemma.get(token)
        if r is not None:
            return r
        ids = forms.get(token)
        if ids and len(ids) == 1:
            return by_id.get(next(iter(ids)))
        return None

    def rarest(r):
        best = None
        for t in r["lemma"].replace("-", " ").split():
            h = resolve(t)
            if h is None or h["lemma"] == r["lemma"]:
                continue
            rk = native_rank(h["frq"], h["bnc"])
            if rk is None:
                continue
            if best is None or rk > best:
                best = rk
        return best

    def jdeal(unranked, hosts):
        n_r, n_u = len(hosts), len(unranked)
        if n_r == 0:
            return
        for k, r in enumerate(unranked, 1):
            idx = min(n_r, max(1, math.ceil((k - 0.5) * n_r / n_u)))
            r["rank"], r["rank_dealt"] = hosts[idx - 1]["rank"], 1

    work = {r["id"]: dict(r, closed=pur_closed(r), rank=native_rank(r["frq"], r["bnc"]), rank_dealt=0, sub=0) for r in rows}
    for w in work.values():
        w["token_rank"] = rarest(w) if w["rank"] is None else None
        w["is_set"] = w["lemma"] in MONTHS + WEEKDAYS
        head = next((t.split(":", 1)[1] for t in (w["sources"] or "").split() if t.startswith("inherit:")), None)
        w["glue_head"] = head if head in by_lemma else None
        w["adverb_pool"] = (not w["closed"] and not w["is_set"] and w["glue_head"] is None and dominant_pos(w["pos"]) == "r")
        w["interj_pool"] = dominant_pos(w["pos"]) == "u" and w["lemma"] not in PUR_CLOSED_LEMMAS and "inherit:" not in (w["sources"] or "")
        if w["interj_pool"]:
            w["closed"] = False
        if w["is_set"]:
            w["closed"] = False
    groups = {}
    for w in work.values():
        if w["glue_head"] is not None:
            continue
        groups.setdefault((w["stage_min"], w["closed"]), []).append(w)
    for grp in groups.values():
        plain = [w for w in grp if not w["is_set"] and not w["adverb_pool"] and not w["interj_pool"]]
        ranked = sorted((w for w in plain if w["rank"] is not None), key=lambda w: (w["rank"], w["lemma"]))
        unranked = sorted((w for w in plain if w["rank"] is None), key=lambda w: (w["token_rank"] is None, w["token_rank"] or 0, w["lemma"]))
        jdeal(unranked, ranked)
        for members in (MONTHS, WEEKDAYS):
            present = [w for w in grp if w["is_set"] and w["lemma"] in members]
            if not present:
                continue
            ranks = [w["rank"] for w in present if w["rank"] is not None]
            if ranks:
                anchor = median_low(ranks)
                for w in present:
                    w["rank"], w["rank_dealt"], w["sub"] = anchor, 1, members.index(w["lemma"]) + 1
            else:
                jdeal(sorted(present, key=lambda w: members.index(w["lemma"])), ranked)
                for w in present:
                    w["sub"] = members.index(w["lemma"]) + 1
        adv = sorted((w for w in grp if w["adverb_pool"]), key=lambda w: (w["rank"] is None, w["rank"] or 0, w["lemma"]))
        if adv:
            jdeal(adv, ranked)
            for w in adv:
                w["sub"] = 20
        pool = sorted((w for w in grp if w["interj_pool"]), key=lambda w: (w["rank"] is None, w["rank"] or 0, w["lemma"]))
        if pool:
            jdeal(pool, ranked)
            for w in pool:
                w["sub"] = 25
    keys = {}
    for w in work.values():
        if w["glue_head"] is None:
            keys[w["id"]] = (1 if w["closed"] else 0, 1 if w["rank"] is None else 0, w["rank"] or 0, w["rank_dealt"], w["sub"], w["lemma"])
    for w in work.values():
        if w["glue_head"] is not None:
            hk = keys[by_lemma[w["glue_head"]]["id"]]
            keys[w["id"]] = hk[:4] + (50 + sorted(x["lemma"] for x in work.values() if x["glue_head"] == w["glue_head"]).index(w["lemma"]), w["lemma"])
    return keys


# ------------------------------------------------------------------------------------------------------ helpers
def load(conn):
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT id, lemma, kind, pos, frq, bnc, sources, stage_min, stage_xs, stage_zk, stage_gk, stage_cet4, stage_cet6, is_public, is_valid_english, merged_into_word_id FROM words")]
    forms = {}
    for form, wid in conn.execute("SELECT form, word_id FROM word_forms"):
        forms.setdefault(form, set()).add(int(wid))
    return rows, forms


def sort_key(r, keys):
    k = keys[r["id"]]
    return (k is None, k if k is not None else 0, (r["frq"] is None or r["frq"] == 0), r["frq"] or 0, r["lemma"])


def stage_distance(sm, cur):
    if sm is None:
        return STAGE_NULL_DISTANCE
    return 0 if sm == cur else (2 * (sm - cur) - 1 if sm > cur else 2 * (cur - sm))


def facts_closed(r):
    return dominant_pos(r["pos"]) in FUNCTION_POS or r["lemma"] in AUX_FACTS or "inherit:" in (r["sources"] or "")


def is_adverb(r):
    return dominant_pos(r["pos"]) == "r" and not facts_closed(r)


def positions(ordered, lemmas):
    pos = {r["lemma"]: i for i, r in enumerate(ordered, 1)}
    return {l: pos.get(l) for l in lemmas}


def longest_null_run(ordered):
    best = cur = 0
    for r in ordered:
        cur = cur + 1 if not r["frq"] else 0
        best = max(best, cur)
    return best


def comp(ordered, n):
    win = ordered[:n]
    return dict(closed=sum(facts_closed(r) for r in win), adverb=sum(is_adverb(r) for r in win), interj=sum(dominant_pos(r["pos"]) == "u" for r in win),
                phrase=sum(r["kind"] == "phrase" for r in win), frq_null=sum(1 for r in win if not r["frq"]))


# ================================================================================================= A. live copy
P("# FINAL POLICY — reference simulation (purist + M1 M2 M3 + G5, packed key; M4 distance NULL→11)")
conn = sqlite3.connect(LIVE, uri=True)
ROWS, FORMS = load(conn)
conn.close()
t0 = time.perf_counter()
KEYS, WORK = rank_rows(ROWS, FORMS)
t_rank = time.perf_counter() - t0
JK = judge_keys(ROWS, FORMS)
P(f"rows {len(ROWS)}; rank_rows {t_rank*1000:.1f} ms; keys NULL: {sum(1 for v in KEYS.values() if v is None)}; max key {max(v for v in KEYS.values() if v is not None)} (< 2·10^7: {max(v for v in KEYS.values() if v is not None) < 2*CLOSED_BASE})")
P("distinct (key, lemma):", len({(KEYS[r['id']], r['lemma']) for r in ROWS}), "| distinct keys alone:", len({KEYS[r['id']] for r in ROWS}))
P("class counts:", dict(Counter(w["cls"] for w in WORK.values())), "| how:", dict(Counter(w["how"].split(":")[0] for w in WORK.values())), "| closed:", sum(w["closed"] for w in WORK.values()))

STAGES = {1: "xs", 2: "zk-new", 3: "gk-new", 4: "cet4-new", 5: "cet6-new", None: "课标外"}
orders = {}
mismatch = 0
for s in (1, 2, 3, 4, 5, None):
    sel = [r for r in ROWS if r["stage_min"] == s]
    mine = sorted(sel, key=lambda r: sort_key(r, KEYS))
    judge = sorted(sel, key=lambda r: JK[r["id"]])
    same = [r["lemma"] for r in mine] == [r["lemma"] for r in judge]
    mismatch += 0 if same else 1
    orders[s] = mine
    P(f"\n## {STAGES[s]} (n={len(sel)}) — packed-key order == judge tuple-key order: {same}")
    if not same:
        diff = next(i for i, (a, b) in enumerate(zip(mine, judge)) if a["lemma"] != b["lemma"])
        P("  first difference at", diff + 1, [r["lemma"] for r in mine[diff:diff + 6]], [r["lemma"] for r in judge[diff:diff + 6]])
    P("  first 30:", " ".join(r["lemma"] for r in mine[:30]))
    P("  31-60  :", " ".join(r["lemma"] for r in mine[30:60]))
    P("  comp first 30 / 100 / 300:", comp(mine, 30), comp(mine, 100), comp(mine, 300))
    P("  first FACTS-closed at", next((i for i, r in enumerate(mine, 1) if facts_closed(r)), None), "| first adverb at", next((i for i, r in enumerate(mine, 1) if is_adverb(r)), None), "| longest frq-NULL run", longest_null_run(mine))
    if s == 1:
        P("  months  :", positions(mine, MONTHS))
        P("  weekdays:", positions(mine, WEEKDAYS))
        P("  grammar :", positions(mine, ["the", "a", "an", "be", "am", "are", "is", "do", "does", "have", "i", "you", "in", "on", "like"]))
        P("  speech  :", positions(mine, ["hello", "hi", "yes", "no", "goodbye", "bye", "ok", "please", "sorry", "thank"]))
        P("  adverbs :", positions(mine, ["not", "very", "here", "too", "up", "so", "out", "now", "then", "also", "how", "well"]))
        P("  no-frq  :", positions(mine, ["colour", "schoolbag", "mr.", "mrs.", "ms.", "p.e.", "email", "ice cream", "ping-pong", "physical education"]))
        P("  numbers :", positions(mine, ["one", "two", "three", "four", "five", "ten", "first", "second", "hundred"]))
        P("  concrete:", positions(mine, ["cat", "dog", "apple", "book", "pen", "red", "blue", "mother", "father", "teacher"]))
        P("  closed block starts at", next(i for i, r in enumerate(mine, 1) if WORK[r["id"]]["closed"]), "| last 12:", " ".join(r["lemma"] for r in mine[-12:]))
        mp = [positions(mine, MONTHS)[m] for m in MONTHS]
        P("  ACCEPT months contiguous & calendar order:", mp == list(range(mp[0], mp[0] + 12)), "| weekdays contiguous:", [positions(mine, WEEKDAYS)[d] for d in WEEKDAYS] == list(range(positions(mine, WEEKDAYS)['monday'], positions(mine, WEEKDAYS)['monday'] + 7)))
    if s == 2:
        blocks = Counter((i - 1) // 100 for i, r in enumerate(mine, 1) if r["kind"] == "phrase")
        P("  phrases first 50 / 200:", sum(r["kind"] == "phrase" for r in mine[:50]), "/", sum(r["kind"] == "phrase" for r in mine[:200]), "| per 100:", [blocks.get(b, 0) for b in range(20)])
        P("  first 12 phrases:", " | ".join(r["lemma"] for r in mine if r["kind"] == "phrase")[:260])
        P("  grammar :", positions(mine, ["as", "if", "would", "could", "although", "unless", "whether", "since", "during", "without"]))
        P("  adverbs :", positions(mine, ["just", "only", "even", "still", "really"]))
        P("  phrases :", positions(mine, ["have to", "go in for", "get up", "look after", "would like", "because of", "be good at", "such as", "kung fu", "according to", "be made of"]))
        P("  british/proper:", positions(mine, ["london", "britain", "england", "centre", "programme", "grey", "favour", "honour", "queen"]))
    if s == 4:
        today = sorted(sel, key=lambda r: ((r["frq"] is None or r["frq"] == 0), r["frq"] or 0, r["lemma"]))
        P("  overlap first 100 with today:", len({r["lemma"] for r in today[:100]} & {r["lemma"] for r in mine[:100]}), "| oh / simply / particularly / due / via:", positions(mine, ["oh", "simply", "particularly", "due", "via"]))
    if s == 5:
        P("  yeah / alas / currently:", positions(mine, ["yeah", "alas", "currently"]))
P("\n## cross-check summary: stages whose order differs from the judge's tuple key:", mismatch)

P("\n## 词库 全部 (sort=freq) — stage prefix = stage_distance(stage_min, cur=1) ≡ COALESCE(stage_min, 6), then the key")
allo = sorted(ROWS, key=lambda r: (stage_distance(r["stage_min"], 1), *sort_key(r, KEYS)))
P("  first 30:", " ".join(r["lemma"] for r in allo[:30]))
P("  positions:", positions(allo, ["the", "is", "hello", "just", "other", "have to", "bookshelf", "monday"]), "| 课标外 starts at", next(i for i, r in enumerate(allo, 1) if r["stage_min"] is None))
P("  key-only order (prewarm stage=all shape) first 30:", " ".join(r["lemma"] for r in sorted(ROWS, key=lambda r: sort_key(r, KEYS))[:30]))
zk_tab = sorted((r for r in ROWS if r["stage_zk"] == 1), key=lambda r: (stage_distance(r["stage_min"], 2), *sort_key(r, KEYS)))
P("  词库 初中 tab (stage_zk=1, cur=2) first 20:", " ".join(r["lemma"] for r in zk_tab[:20]), "| first 小学 word at", next(i for i, r in enumerate(zk_tab, 1) if r["stage_min"] == 1))

P("\n## acceptance numbers (full_seed assertions)")
acc = {
    "closed_in_first_30_every_stage": {STAGES[s]: comp(orders[s], 30)["closed"] for s in (1, 2, 3, 4, 5)},
    "xs_adverbs_first_30": comp(orders[1], 30)["adverb"],
    "xs_months_contiguous": [positions(orders[1], MONTHS)[m] for m in MONTHS],
    "zk_phrases_first_200": sum(r["kind"] == "phrase" for r in orders[2][:200]),
    "longest_frq_null_run": {STAGES[s]: longest_null_run(orders[s]) for s in (1, 2, 3, 4, 5)},
    "stage_words_with_null_key": sum(1 for r in ROWS if r["stage_min"] is not None and KEYS[r["id"]] is None),
    "cet4_first100_overlap_today": len({r["lemma"] for r in sorted([r for r in ROWS if r["stage_min"] == 4], key=lambda r: ((r["frq"] is None or r["frq"] == 0), r["frq"] or 0, r["lemma"]))[:100]} & {r["lemma"] for r in orders[4][:100]}),
}
P(json.dumps(acc, ensure_ascii=False))

P("\n## per-stage statistics (what kv.learn_order.stats carries; derived, never typed into docs)")
for s in (1, 2, 3, 4, 5, None):
    sel = [WORK[r["id"]] for r in ROWS if r["stage_min"] == s]
    nat = sorted(w["rank"] for w in sel if w["how"] == "native" and w["rank"] is not None)
    q = lambda p: nat[min(len(nat) - 1, int(p * len(nat)))] if nat else None
    P(f"  {STAGES[s]}: n={len(sel)} native={len(nat)} from_bnc={sum(1 for w in sel if w['how']=='native' and not to_rank(w['frq']) and to_rank(w['bnc']))} dealt={sum(w['how']=='dealt' for w in sel)} set={sum(w['how'].startswith('set') for w in sel)} glued={sum(w['how'].startswith('glued') for w in sel)} adverb={sum(w['how']=='adverb' for w in sel)} interj={sum(w['how']=='interj' for w in sel)} closed={sum(w['closed'] for w in sel)} p10/p50/p90={q(0.1)}/{q(0.5)}/{q(0.9)} first8={' '.join(r['lemma'] for r in orders[s][:8])}")

# ================================================================================================= B. scratch copy
P("\n## B. scratch copy: ADD COLUMN + UPDATE + SQL differential (stage distance NULL → 11)")
tmpdir = tempfile.mkdtemp(prefix="synth-", dir=HERE)
scratch = os.path.join(tmpdir, "scratch.db")
src = sqlite3.connect(LIVE, uri=True)
dst = sqlite3.connect(scratch)
src.backup(dst)
src.close()
dst.close()
c = wddb.connect(scratch)
t0 = time.perf_counter()
c.execute("ALTER TABLE words ADD COLUMN learn_rank INTEGER")
t_mig = time.perf_counter() - t0
t0 = time.perf_counter()
with wddb.tx(c):
    c.executemany("UPDATE words SET learn_rank = ? WHERE id = ?", [(KEYS[r["id"]], r["id"]) for r in ROWS])
t_upd = time.perf_counter() - t0
P(f"  ADD COLUMN {t_mig*1000:.1f} ms; UPDATE {len(ROWS)} rows {t_upd*1000:.1f} ms; NULL learn_rank rows: {c.execute('SELECT COUNT(*) FROM words WHERE learn_rank IS NULL').fetchone()[0]}; updated_at distinct {c.execute('SELECT COUNT(DISTINCT updated_at) FROM words').fetchone()[0]}")
ORDER_SQL = "w.learn_rank IS NULL, w.learn_rank, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma"
DIST = f"CASE WHEN w.stage_min IS NULL THEN {STAGE_NULL_DISTANCE} WHEN w.stage_min = :cur THEN 0 WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END"
checks = [
    ("词库 全部 (cur=1 prefix)", f"SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.merged_into_word_id IS NULL ORDER BY {DIST}, {ORDER_SQL}", {"cur": 1}, allo),
    ("词库 小学 tab", f"SELECT w.lemma FROM words w WHERE w.stage_xs = 1 AND w.is_public = 1 AND w.merged_into_word_id IS NULL ORDER BY {DIST}, {ORDER_SQL}", {"cur": 1}, sorted((r for r in ROWS if r["stage_xs"] == 1), key=lambda r: (stage_distance(r["stage_min"], 1), *sort_key(r, KEYS)))),
    ("词库 初中 tab", f"SELECT w.lemma FROM words w WHERE w.stage_zk = 1 AND w.is_public = 1 AND w.merged_into_word_id IS NULL ORDER BY {DIST}, {ORDER_SQL}", {"cur": 2}, zk_tab),
    ("筛词 auto xs+zk+gk, 主攻 xs", f"SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND (w.stage_xs = 1 OR w.stage_zk = 1 OR w.stage_gk = 1) ORDER BY {DIST}, {ORDER_SQL}", {"cur": 1},
     sorted((r for r in ROWS if r["stage_xs"] or r["stage_zk"] or r["stage_gk"]), key=lambda r: (stage_distance(r["stage_min"], 1), *sort_key(r, KEYS)))),
    ("prewarm all (key only)", f"SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.stage_min IS NOT NULL ORDER BY {ORDER_SQL}", {},
     sorted((r for r in ROWS if r["stage_min"] is not None), key=lambda r: sort_key(r, KEYS))),
    ("difficulty sort", f"SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.merged_into_word_id IS NULL ORDER BY COALESCE(w.difficulty + 1, w.stage_min, 6), {ORDER_SQL}", {}, None),
]
for name, sql, params, expect in checks:
    t0 = time.perf_counter()
    got = [r[0] for r in c.execute(sql, params).fetchall()]
    dt = (time.perf_counter() - t0) * 1000
    if expect is None:
        P(f"  {name}: {len(got)} rows in {dt:.2f} ms (no Python twin; first 10: {' '.join(got[:10])})")
    else:
        same = got == [r["lemma"] for r in expect]
        P(f"  {name}: SQL == Python: {same} ({len(got)} rows, {dt:.2f} ms)")
        assert same, name
plan = c.execute(f"EXPLAIN QUERY PLAN SELECT w.* FROM words w WHERE w.is_public = 1 AND w.merged_into_word_id IS NULL ORDER BY {DIST}, {ORDER_SQL} LIMIT 50", {"cur": 1}).fetchall()
P("  plan 词库 全部:", " | ".join(str(tuple(r)[3]) for r in plan))
# C10 trap: a hand-inserted row with stage_xs = 1 and stage_min NULL
c.execute("INSERT INTO words(lemma, display, kind, stage_xs, stage_zk, stage_min, source, is_public, is_valid_english, safe_for_sharing, created_at, updated_at) VALUES ('zz-hand-inserted', 'zz-hand-inserted', 'word', 1, 1, NULL, 'seed', 1, 1, 1, '2026-11-06T00:00:00Z', '2026-11-06T00:00:00Z')")
got = [r[0] for r in c.execute(f"SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.stage_xs = 1 ORDER BY {DIST}, {ORDER_SQL}", {"cur": 1}).fetchall()]
P("  C10 trap row (stage_xs=1, stage_min NULL, learn_rank NULL) in a 小学 筛词 list: position", got.index("zz-hand-inserted") + 1, "of", len(got), "(was 1 of 601 today)")
old = [r[0] for r in c.execute("SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.is_valid_english = 1 AND w.merged_into_word_id IS NULL AND w.stage_xs = 1 ORDER BY CASE WHEN w.stage_min = :cur THEN 0 WHEN w.stage_min > :cur THEN 2 * (w.stage_min - :cur) - 1 ELSE 2 * (:cur - w.stage_min) END, (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma", {"cur": 1}).fetchall()]
P("  same row under TODAY's _STAGE_DISTANCE (NULL first): position", old.index("zz-hand-inserted") + 1)
# fail-soft: NULL every rank → exactly today's order
c.execute("UPDATE words SET learn_rank = NULL")
got = [r[0] for r in c.execute(f"SELECT w.lemma FROM words w WHERE w.stage_min = 1 ORDER BY {ORDER_SQL}").fetchall()]
today = [r[0] for r in c.execute("SELECT w.lemma FROM words w WHERE w.stage_min = 1 ORDER BY (w.frq IS NULL OR w.frq = 0), w.frq, w.lemma").fetchall()]
P("  fail-soft (all ranks NULL) == today's frq order:", got == today, "| first 8:", " ".join(got[:8]))
c.close()
shutil.rmtree(tmpdir)

# ================================================================================================= C. mini seed
P("\n## C. mini seed (backend/tests/fixtures/mini_seed.jsonl) imported with wd.seed.import_seed into a fresh migrated DB")
tmpdir = tempfile.mkdtemp(prefix="synth-mini-", dir=HERE)
mini = os.path.join(tmpdir, "mini.db")
c = wddb.connect(mini)
wddb.run_migrations(c)
st = import_seed(c, MINI_SEED)
P(f"  imported {st.records} records, {st.inserted} inserted, {st.forms} forms")
MROWS, MFORMS = load(c)
MK, MW = rank_rows(MROWS, MFORMS)
MJ = judge_keys(MROWS, MFORMS)
mo = sorted(MROWS, key=lambda r: sort_key(r, MK))
mj = sorted(MROWS, key=lambda r: MJ[r["id"]])
P("  packed == judge tuple order:", [r["lemma"] for r in mo] == [r["lemma"] for r in mj], "| NULL keys:", sum(1 for v in MK.values() if v is None))
golden = sorted(((r["lemma"], MK[r["id"]]) for r in MROWS), key=lambda t: t[0])
digest = hashlib.sha256(json.dumps(golden, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
P("  GOLDEN DIGEST sha256(json.dumps(sorted (lemma, learn_rank)), separators=(',',':')):", digest)
P("  table: lemma | stage_min | class/how | frq | bnc | learn_rank")
for r in mo:
    w = MW[r["id"]]
    P(f"    {r['lemma']:<20} {str(r['stage_min']):<5} {w['how']:<12} {str(r['frq']):<6} {str(r['bnc']):<6} {MK[r['id']]}")
with open(os.path.join(HERE, "mini_seed_golden.json"), "w", encoding="utf-8") as fh:
    json.dump({"policy": "lo-1", "digest": digest, "rows": [{"lemma": l, "learn_rank": k} for l, k in golden]}, fh, ensure_ascii=False, indent=1)
# what the rewritten pinned tests would see (informative, never pinned)
def q(sql, params=()):
    return [r[0] for r in c.execute(sql, params).fetchall()]
try:
    c.execute("ALTER TABLE words ADD COLUMN learn_rank INTEGER")
except sqlite3.OperationalError:
    pass  # the repository now carries migration 0014: run_migrations() already added the column
c.executemany("UPDATE words SET learn_rank = ? WHERE id = ?", [(MK[r["id"]], r["id"]) for r in MROWS])
P("  test_vocab 全部 first 10 (cur=1 prefix):", " ".join(q(f"SELECT w.lemma FROM words w WHERE w.is_public = 1 AND w.merged_into_word_id IS NULL ORDER BY {DIST}, {ORDER_SQL} LIMIT 10", {"cur": 1})))
P("  test_screen cet6 主攻 (stage_min=5) first 3:", q(f"SELECT w.lemma FROM words w WHERE w.stage_min = 5 ORDER BY {ORDER_SQL} LIMIT 3"), "| zk tab cur=2 first 3:", q(f"SELECT w.lemma FROM words w WHERE w.stage_zk = 1 ORDER BY {DIST}, {ORDER_SQL} LIMIT 3", {"cur": 2}))
P("  test_batches 主攻 cet4 screens first 2:", q(f"SELECT w.lemma FROM words w WHERE w.stage_cet4 = 1 ORDER BY {DIST}, {ORDER_SQL} LIMIT 2", {"cur": 4}))
P("  test_vocab xs first 5:", q(f"SELECT w.lemma FROM words w WHERE w.stage_xs = 1 ORDER BY {ORDER_SQL} LIMIT 5"))
c.close()
shutil.rmtree(tmpdir)

with open(os.path.join(HERE, "sim_output.txt"), "w", encoding="utf-8") as fh:
    fh.write("\n".join(OUT) + "\n")
print("\n[written]", os.path.join(HERE, "sim_output.txt"), "and mini_seed_golden.json")
