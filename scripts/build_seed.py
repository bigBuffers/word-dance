#!/usr/bin/env python3
"""Build the word-Dance vocabulary seed.

Inputs (already downloaded):
  - ECDICT stardict.db  (MIT, https://github.com/skywind3000/ECDICT)
  - mahavivo/english-wordlists syllabus lists (https://github.com/mahavivo/english-wordlists)

Output: <out>/vocab.jsonl  one JSON object per word, plus stats.json and ATTRIBUTION.md

Stage codes: zk = 初中(中考), gk = 高中(高考), cet4 = 大学英语四级, cet6 = 大学英语六级
Each stage set = ECDICT tag ∪ official syllabus list.
"""
import argparse, io, json, os, re, sqlite3, sys, collections

PLAIN_RE = re.compile(r"^[A-Za-z][A-Za-z'\-\.]*(?: [A-Za-z][A-Za-z'\-\.]*){0,3}$")
RICH_RE = re.compile(r"^([A-Za-z][A-Za-z'\-\.]*(?: [A-Za-z][A-Za-z'\-\.]*){0,3})(?:\s*\([^)]*\))?\s*(?:\[|/|$|\s)")
POS_RE = re.compile(r"^(n|v|vt|vi|a|ad|adj|adv|prep|conj|pron|art|num|int|interj|aux|modal|abbr|pl|phr)\.?$", re.I)


def parse_list(path, mode):
    """Return ordered unique list of head words from a mahavivo list file."""
    out, seen = [], set()
    for raw in io.open(path, encoding="utf-8-sig"):
        line = raw.strip()
        if not line or len(line) == 1:  # section headers like "A"
            continue
        if mode == "plain":
            if not PLAIN_RE.match(line):
                continue
            w = line
        else:
            m = RICH_RE.match(line)
            if not m:
                continue
            w = m.group(1).strip()
            # lines like "a (an) [...]" -> head "a"
            # lines without phonetics like "Oceania n. 大洋洲" -> drop trailing POS tokens
            toks = w.split()
            while len(toks) > 1 and POS_RE.match(toks[-1]):
                toks.pop()
            w = " ".join(toks)
        w = re.sub(r"\s+", " ", w).strip()
        wl = w.lower()
        # skip pure abbreviations with trailing dots like "a.m." ? keep them, they are in syllabi
        if wl not in seen:
            seen.add(wl)
            out.append(w)
    return out


EXCHANGE_CODES = {"p": "past", "d": "past_participle", "i": "present_participle", "3": "third_person",
                  "r": "comparative", "t": "superlative", "s": "plural", "0": "lemma", "1": "lemma_forms"}


def parse_exchange(s):
    if not s:
        return {}
    d = {}
    for part in s.split("/"):
        if ":" in part:
            k, v = part.split(":", 1)
            d[k] = v
    return d


def norm_phonetic(p):
    if not p:
        return ""
    return p.replace("ә", "ə").replace("ɒ:", "ɔː").replace("ɔ:", "ɔː").replace("i:", "iː").replace("u:", "uː").replace("ɑ:", "ɑː").replace("ә:", "əː").replace("ə:", "ɜː").strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--lists", required=True, help="dir with mahavivo txt files")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    L = a.lists
    syllabus = {
        "zk": parse_list(os.path.join(L, "中考英语词汇表.txt"), "rich"),
        "gk": parse_list(os.path.join(L, "Highschool_edited.txt"), "plain"),
        "cet4": parse_list(os.path.join(L, "CET4_edited.txt"), "rich"),
        "cet6": parse_list(os.path.join(L, "CET6_edited.txt"), "rich"),
        "cet46": parse_list(os.path.join(L, "CET_4+6_edited.txt"), "plain"),
        "cet6star": parse_list(os.path.join(L, "英语六级词汇（星标，1726）.txt"), "plain"),
    }
    for k, v in syllabus.items():
        print(f"syllabus {k}: {len(v)} words", file=sys.stderr)

    con = sqlite3.connect(a.db)
    cur = con.cursor()
    cols = "id,word,sw,phonetic,definition,translation,pos,collins,oxford,tag,bnc,frq,exchange"

    def lookup(w):
        r = cur.execute(f"select {cols} from stardict where word = ? collate nocase", (w,)).fetchone()
        if r is None and " " in w:
            r = cur.execute(f"select {cols} from stardict where word = ? collate nocase", (w.replace(" ", "-"),)).fetchone()
        return r

    # 1) all ECDICT rows tagged with any stage tag
    words = {}  # key: lowercase word -> record
    missing = collections.defaultdict(list)
    q = ("select " + cols + " from stardict where ' '||tag||' ' like '% zk %' or ' '||tag||' ' like '% gk %' "
         "or ' '||tag||' ' like '% cet4 %' or ' '||tag||' ' like '% cet6 %'")
    for r in cur.execute(q):
        rec = make_record(r)
        words[rec["word"].lower()] = rec

    # 2) union syllabus lists
    stage_from_list = {"zk": "zk", "gk": "gk", "cet4": "cet4", "cet6": "cet6"}
    cet4_set = {w.lower() for w in syllabus["cet4"]}
    for lst, stage in stage_from_list.items():
        for w in syllabus[lst]:
            key = w.lower()
            rec = words.get(key)
            if rec is None:
                r = lookup(w)
                if r is None:
                    missing[lst].append(w)
                    continue
                rec = make_record(r)
                words[rec["word"].lower()] = rec
            if stage not in rec["stages"]:
                rec["stages"].append(stage)
            rec["sources"].append(lst)
    # CET_4+6 combined syllabus: words not in the CET4 list count as CET6 syllabus words
    for w in syllabus["cet46"]:
        key = w.lower()
        rec = words.get(key)
        if rec is None:
            r = lookup(w)
            if r is None:
                missing["cet46"].append(w)
                continue
            rec = make_record(r)
            words[rec["word"].lower()] = rec
        rec["sources"].append("cet46")
        stage = "cet4" if key in cet4_set else "cet6"
        if stage not in rec["stages"]:
            rec["stages"].append(stage)
    star = {w.lower() for w in syllabus["cet6star"]}
    for key, rec in words.items():
        rec["cet6_star"] = key in star
        rec["sources"] = sorted(set(rec["sources"]))
        rec["stages"] = [s for s in ("zk", "gk", "cet4", "cet6") if s in rec["stages"]]

    # 3) write
    order = {"zk": 0, "gk": 1, "cet4": 2, "cet6": 3}
    recs = sorted(words.values(), key=lambda r: (min(order[s] for s in r["stages"]), r["word"].lower()))
    out_path = os.path.join(a.out, "vocab.jsonl")
    with io.open(out_path, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    stats = {
        "total_words": len(recs),
        "per_stage": {s: sum(1 for r in recs if s in r["stages"]) for s in order},
        "only_stage": {s: sum(1 for r in recs if r["stages"] == [s]) for s in order},
        "first_stage": {s: sum(1 for r in recs if r["stages"][0] == s) for s in order},
        "with_phonetic": sum(1 for r in recs if r["phonetic"]),
        "with_translation": sum(1 for r in recs if r["translation"]),
        "with_definition": sum(1 for r in recs if r["definition"]),
        "with_exchange": sum(1 for r in recs if r["exchange"]),
        "multiword": sum(1 for r in recs if " " in r["word"]),
        "uppercase": sum(1 for r in recs if r["word"] != r["word"].lower()),
        "syllabus_sizes": {k: len(v) for k, v in syllabus.items()},
        "missing_from_ecdict": {k: v for k, v in missing.items()},
        "file_bytes": os.path.getsize(out_path),
    }
    with io.open(os.path.join(a.out, "stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)
    print(json.dumps(stats, ensure_ascii=False, indent=1), file=sys.stderr)

    with io.open(os.path.join(a.out, "ATTRIBUTION.md"), "w", encoding="utf-8") as f:
        f.write(ATTRIBUTION)


def make_record(r):
    (id_, word, sw, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange) = r
    tags = (tag or "").split()
    return {
        "word": word,
        "phonetic": norm_phonetic(phonetic),
        "translation": [s.strip() for s in (translation or "").replace("\r", "").split("\n") if s.strip()],
        "definition": [s.strip() for s in (definition or "").replace("\r", "").split("\n") if s.strip()],
        "pos": pos or "",
        "collins": int(collins) if collins else 0,
        "oxford": int(oxford) if oxford else 0,
        "stages": [t for t in ("zk", "gk", "cet4", "cet6") if t in tags],
        "exam_tags": [t for t in tags if t in ("ky", "toefl", "ielts", "gre")],
        "bnc": int(bnc) if bnc else None,
        "frq": int(frq) if frq else None,
        "exchange": parse_exchange(exchange),
        "sources": ["ecdict"] if tags else [],
        "ecdict_id": id_,
    }


ATTRIBUTION = """# Vocabulary data attribution

The seed vocabulary (`vocab.jsonl`) is derived from:

1. **ECDICT** — Free English to Chinese Dictionary Database by skywind3000
   https://github.com/skywind3000/ECDICT — MIT License.
   Fields used: word, phonetic, definition, translation, pos, collins, oxford, tag, bnc, frq, exchange.
   Release used: 1.0.28 (ecdict-sqlite-28.zip).

2. **english-wordlists** by mahavivo — https://github.com/mahavivo/english-wordlists
   Exam-syllabus word lists: 中考英语词汇表.txt, Highschool_edited.txt, CET4_edited.txt, CET6_edited.txt,
   CET_4+6_edited.txt (2016 CET syllabus), 英语六级词汇（星标，1726）.txt. Only the head words are used to
   decide stage membership (初中 / 高中 / CET-4 / CET-6).

Stage codes: `zk` = 初中（中考）, `gk` = 高中（高考）, `cet4` = 大学英语四级, `cet6` = 大学英语六级.
A word's `stages` is the union of the ECDICT exam tag and the official syllabus lists.
`exam_tags` keeps ECDICT's other tags (ky 考研, toefl, ielts, gre). `exchange` codes (ECDICT):
p=过去式, d=过去分词, i=现在分词, 3=第三人称单数, r=比较级, t=最高级, s=复数, 0=原型, 1=原型的变换形式.
"""

if __name__ == "__main__":
    main()
