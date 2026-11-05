"""seedbuild.normalise — the R1–R12 rules of PLAN §4.3 pinned on real lines of ``data/lists`` (WL SYNTHESIS §3.3 examples).

Every head / phrase in the tables below is a verbatim line of a delivered list (``grep`` them); every ECDICT row of the
fake lexicon is a verbatim ``(word, exchange)`` pair of ECDICT 1.0.28. The lexicon is a dictionary, so the rules are
tested without the 851 MB ``stardict.db``; the fixture directory ``tests/fixtures/lists`` (mini lists, mini ECDICT SQL,
previous seed) is validated here too because ``test_seedbuild_build.py`` (S3b) builds on it.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from wd import schemas
from wd.seedbuild import normalise as N
from wd.services import words
from wd.services.ecdict import parse_exchange

TESTS = Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures" / "lists"
LISTS = Path(__file__).resolve().parents[3] / "data" / "lists"

# ----------------------------------------------------------------------------------- fake ECDICT (verbatim rows)
# word → exchange, exactly as stored in ECDICT 1.0.28 (None = SQL NULL). Casing is ECDICT's (``AM``, ``E-MAIL``, ``MS``).
ECDICT_ROWS: dict[str, str | None] = {
    "a": "s:some", "an": "0:a/s:some", "be": "p:was/3:is/d:been/i:being/s:bes", "AM": "s:ams", "is": "0:be/1:3", "are": "s:ares",
    "was": "0:be", "been": "1:d/0:be/s:beens", "being": "1:i/0:be/s:beings",
    "have": "i:having/p:had/3:has/d:had/s:haves", "has": "1:3/0:have", "had": "1:pd/0:have/s:hads",
    "do": "i:doing/p:did/3:does/d:done/s:does", "does": "0:doe/1:s",
    "child": "s:children", "children": "0:child/1:s/s:childrens",
    "colour": "s:colours/d:coloured/i:colouring/p:coloured/3:colours", "color": "s:colors/i:coloring/p:colored/3:colors/d:colored/f:colors",
    "maths": "0:math/s:mathss", "math": "s:maths", "mathematics": None,
    "mother": "s:mothers/i:mothering/p:mothered/3:mothers/d:mothered", "mum": "s:mums", "mom": "s:moms",
    "PE": "s:pes", "p.e.": "s:p.e.s", "physical education": "s:physical educations",
    "Mr": "s:mrs", "Mr.": "s:mr.s", "Mrs": "0:mr/s:mrss", "mrs.": "s:mrs.s", "MS": "0:m/s:mss", "Ms.": "s:ms.s", "a.m.": None,
    "according": "0:accord/1:i/s:accordings", "according to": "",
    "until": "", "till": "s:tills/i:tilling/p:tilled/d:tilled/3:tills",
    "kilo": "s:kilos", "kilogramme": "s:kilogrammes", "kilogram": "s:kilograms", "kilometre": "s:kilometres", "kilometer": "s:kilometers",
    "UNESCO": "s:unescoes", "United Nations Educational, Scientific and Cultural Organization": None, "united nations educational": None,
    "bce": "", "CE": "s:ces", "common era": "s:common eras", "cpc": "", "Communist Party of China": None,
    "the United States of America": "", "USA": "s:usas", "the united kingdom": "", "UK": "s:uks", "UN": "s:uns", "United Nations": "s:united nationss",
    "bund": "s:bunds", "the bund": None, "hang": "i:hanging/p:hung/d:hung/3:hangs/s:hangs",
    "E-MAIL": "s:e-mails/i:e-mailing/p:e-mailed/3:e-mails/d:e-mailed/f:e-mails", "email": "s:emails",
    "television": "s:televisions", "TV": "s:tvs", "tofu": "s:tofus", "bean curd": "s:bean curds",
    "advertisement": "s:advertisements", "ad": "s:ads",
    "excited": "0:excite/1:p", "stuck": "0:stick/1:pd", "united": "0:unite/1:p", "frightened": "0:frighten/1:p",
    "burn": "d:burnt/i:burning/p:burned/s:burns/3:burns", "burnt": "0:burn/1:dp", "burned": "0:burn/1:dp",
    "centre": "s:centres/p:centred/d:centred/3:centres/i:centring", "center": "s:centers/d:centered/p:centered/i:centering/3:centers/f:centers",
    "programme": "s:programmes/d:programmed/p:programmed/i:programming/3:programs", "program": "s:programs/i:programming/p:programmed/3:programs/d:programmed/f:programs",
    "realise": "p:realised/d:realised/i:realising/3:realises", "realize": "p:realized/d:realized/i:realizing/3:realizes",
    "theatre": "s:theatres", "theater": "s:theaters",
    "manner": "s:manners", "manners": "0:manner/1:s/s:mannerss", "toward": "", "towards": "",
    "actor": "s:actors", "actress": "s:actresses", "exam": "s:exams", "examination": "s:examinations", "although": "", "though": "",
    "grandma": "s:grandmas", "grandmother": "s:grandmothers", "policeman": "s:policemen", "policewoman": "s:policewomen", "policemen": "0:policeman/1:s",
    "ice cream": "s:ice creams", "ice-cream": "s:ice-creams", "paper cut": "", "paper-cut": "", "breakdown": "s:breakdowns",
    "dad": "s:dads", "bye": "s:byes", "goodbye": "s:goodbyes", "China": "s:chinas", "who": "s:whoes",
    "a bit": "", "a bit of": "", "at first": "", "at last": "", "catch a cold": "", "catch cold": "", "by bus": "", "by train": "", "by plane": "",
    "add ... to": None, "save one's life": None, "a lot of": "", "lots of": "", "arrive at": "", "arrive in": "",
    "be located": None, "be located in": "", "be located on": None, "be located at": None,
    "go to the cinema": None, "go to the movie": None, "go to the movies": "", "have to": "", "have got to": "",
    "be familiar with": "", "be familiar to": "", "get familiar with": None, "in hospital": None, "talk to sb.": "", "get into the habit of": "",
}


class FakeLexicon:
    """``normalise.Lexicon`` over a dict of verbatim rows: one case-insensitive lookup, None when absent."""

    def __init__(self, rows: dict[str, str | None] = ECDICT_ROWS, *, exclude: tuple[str, ...] = ()):
        self.rows = {w.lower(): SimpleNamespace(word=w, exchange=parse_exchange(x)) for w, x in rows.items() if w not in exclude}

    def get(self, word: str):
        return self.rows.get(word.lower())


LEX = FakeLexicon()
ALIASES = N.load_aliases((LISTS / "aliases.tsv").read_text(encoding="utf-8"))
PREVIOUS = frozenset(
    N.lemma_of(json.loads(line)["word"])
    for line in (FIXTURES / "previous_seed.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
)


def sh(raw: str, **kw) -> N.ParsedHead:
    """split_head with the shared fake ECDICT, the real aliases and the fixture's previous-seed lemmas."""
    kw.setdefault("lexicon", LEX)
    kw.setdefault("aliases", ALIASES)
    kw.setdefault("previous", PREVIOUS)
    return N.split_head(raw, **kw)


def list_rows(path: Path) -> list[str]:
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]


def head_cell(path: Path, line: str) -> str:
    """The head text of a list line: the word column of a TSV (manifest ``columns``), the whole line otherwise."""
    if path.suffix != ".tsv":
        return line
    cells = line.split("\t")
    return cells[1] if path.name.startswith("moe-2022-appendix") or path.name.startswith("mini-moe-2022-appendix") else cells[0]


# ======================================================================================= R1 fold / lemma_of
FOLD: list[tuple[str, str]] = [
    ("café", "cafe"),  # shmeea-2020-junior.txt:235, moe-2020-senior.tsv:410
    ("o’clock", "o'clock"),  # curly apostrophe (the lists already write o'clock; the PDFs printed ’)
    ("Tian’anmen Square", "Tian'anmen Square"),
    ("A.M.", "A.M."),  # casing kept — canon lower-cases
    ("China", "China"),
    ("maths (=mathematics，美 math)", "maths (=mathematics,美 math)"),  # full-width comma of the forms.tsv printed column
    ("colour（AmE color）", "colour(AmE color)"),  # full-width brackets
    ("a／an", "a/an"),
    ("exam＝examination", "exam=examination"),
    ("ice   cream", "ice cream"),
    ("  a/an \n", "a/an"),
    ("add…to", "add...to"),
    ("well—known", "well-known"),
    ("ＡＢＣ", "ABC"),
    ("", ""),
]


@pytest.mark.parametrize("text,expected", FOLD, ids=[repr(c[0]) for c in FOLD])
def test_r1_fold(text, expected):
    assert N.fold(text) == expected


def test_r1_fold_is_idempotent_and_keeps_case():
    for text, _ in FOLD:
        assert N.fold(N.fold(text)) == N.fold(text)
    assert N.fold("Mr") == "Mr" and N.fold("PE") == "PE"


def test_lemma_of_is_the_importer_lemma_for_every_fixture_head():
    """PLAN §4.2: every set element is ``words.normalise_lemma(fold(text))`` — the lemma ``seed.seed_row`` recomputes."""
    checked = 0
    for path in sorted(FIXTURES.glob("mini-*")):
        for line in list_rows(path):
            head = head_cell(path, line)
            assert N.lemma_of(head) == words.normalise_lemma(N.fold(head))
            checked += 1
    assert checked >= 80
    assert N.lemma_of("Mr") == "mr" and N.lemma_of("café") == "cafe" and N.lemma_of("The Great Wall") == "the great wall"
    assert N.lemma_of(None) is None and N.lemma_of("()") is None


def test_has_cjk():
    assert N.has_cjk("hang (悬挂)") and N.has_cjk("复 children") and not N.has_cjk("pl. children")


# ======================================================================================= R5 aliases / canon
def test_r5_load_aliases_reads_the_delivered_file():
    assert ALIASES == {"mr": "mr.", "mrs": "mrs.", "ms": "ms.", "pe": "p.e.", "hot-dog": "hot dog", "humourous": "humorous"}


CANON: list[tuple[str, str]] = [
    ("Mr", "mr."),  # moe-2022-level3.txt Mr (AmE Mr.), shmeea-2020-junior.txt Mr
    ("Mrs", "mrs."),
    ("Ms", "ms."),
    ("PE", "p.e."),  # moe-2022-level2.txt PE (=physical education)
    ("hot-dog", "hot dog"),  # shmeea-2020-junior.txt:756
    ("humourous", "humorous"),  # moe-2025rev-senior.tsv:1401
    ("Miss", "miss"),  # R6: lower-case only
    ("China", "china"),
    ("colour", "colour"),  # no alias → lemma_of
    ("A.M.", "a.m."),
    ("Mr.", "mr."),  # already the canonical spelling
]


@pytest.mark.parametrize("text,expected", CANON, ids=[repr(c[0]) for c in CANON])
def test_r5_r6_canon(text, expected):
    assert N.canon(text, ALIASES) == expected


def test_r5_canon_without_aliases_is_lemma_of():
    assert N.canon("Mr") == "mr" and N.canon("Mr", {}) == "mr" and N.canon(None, ALIASES) is None and N.canon("()", ALIASES) is None


@pytest.mark.parametrize(
    "text,message",
    [
        ("Mr\tmr.\nmr.\tmister\n", "chain"),
        ("Mr\tmr\n", "maps to itself"),
        ("Mr\tmr.\nMR\tmr.\n", "duplicate"),
        ("Mr\n", "expected spelling"),
    ],
)
def test_r5_load_aliases_rejects_chains_self_maps_and_duplicates(text, message):
    with pytest.raises(ValueError, match=message):
        N.load_aliases(text)


def test_r5_load_aliases_ignores_comments_and_notes():
    assert N.load_aliases("# c\n\nhot-dog\thot dog\tnote text\n") == {"hot-dog": "hot dog"}


# ======================================================================================= R12 strict gate
STRICT_OK = ["the united kingdom", "o'clock", "tian'anmen square", "children's day", "a.m.", "mid-autumn festival", "kung fu", "x" * 48, "u.s.a.", "according to"]
STRICT_BAD = [
    ("The United States of America", words.REASON_TOO_MANY_TOKENS),  # moe-2022-appendix.tsv 地理名称 (5 tokens)
    ("united nations educational, scientific and cultural organization", words.REASON_CHARSET),  # UNESCO note, 66 chars
    ("add ... to", words.REASON_PUNCT_TOKEN),  # shmeea phrase add...to
    ("get into the habit of", words.REASON_TOO_MANY_TOKENS),  # shmeea phrase, 5 tokens
    ("x" * 49, words.REASON_TOO_LONG),
    ("-abc", words.REASON_LEADING),
    ("example.com", words.REASON_DOT),
    ("hang (悬挂)", words.REASON_NOT_ENGLISH),
    ("", words.REASON_EMPTY),
]


@pytest.mark.parametrize("lemma", STRICT_OK, ids=[repr(c) for c in STRICT_OK])
def test_r12_strict_ok(lemma):
    assert N.strict_ok(lemma) and N.strict_reason(lemma) is None


@pytest.mark.parametrize("lemma,reason", STRICT_BAD, ids=[repr(c[0]) for c in STRICT_BAD])
def test_r12_strict_rejects_with_the_zh_reason(lemma, reason):
    assert not N.strict_ok(lemma)
    assert N.strict_reason(lemma) == reason


def test_r12_strict_ok_none():
    assert N.strict_ok(None) is False


# ======================================================================================= R10 ECDICT spellings
@pytest.mark.parametrize(
    "head,expected",
    [
        ("break down", ("break down", "break-down")),
        ("ice-cream", ("ice-cream", "ice cream")),  # shmeea-2020-junior.txt:773
        ("ice cream", ("ice cream", "ice-cream")),  # moe-2022-level2.txt:227
        ("e-mail", ("e-mail", "e mail")),
        ("Mid-Autumn Festival", ("Mid-Autumn Festival", "Mid Autumn Festival", "Mid-Autumn-Festival")),
        ("hello", ("hello",)),
        ("", ()),
    ],
)
def test_r10_ecdict_candidates(head, expected):
    assert N.ecdict_candidates(head) == expected
    assert all(" " in c or "-" in c or c == head for c in expected)


def test_r10_multiword_head_never_matches_the_glued_spelling():
    lex = FakeLexicon({"breakdown": "s:breakdowns", "ice-cream": "s:ice-creams", "paper cut": ""})
    assert N.lookup(lex, "break down") is None  # breakdown is a different word
    assert N.lookup(lex, "ice cream").word == "ice-cream"  # space ↔ hyphen is allowed
    assert N.lookup(lex, "paper-cut").word == "paper cut"
    assert N.lookup(None, "ice cream") is None


def test_r10_ice_cream_and_ice_cream_hyphen_coexist():
    """Both spellings have ECDICT rows and both are official heads (level-2 ``ice cream``, Shanghai ``ice-cream``): they stay two lemmas."""
    assert N.lookup(LEX, "ice-cream").word == "ice-cream" and N.lookup(LEX, "ice cream").word == "ice cream"
    assert N.canon("ice-cream", ALIASES) != N.canon("ice cream", ALIASES)


# ======================================================================================= R2 bracket notes
@pytest.mark.parametrize(
    "note,expected",
    [
        ("AmE color", ["color"]),  # colour (AmE color)
        ("=mathematics, AmE math", ["mathematics", "math"]),  # maths (=mathematics, AmE math)
        ("mum AmE mom", ["mum", "mom"]),  # mother (mum AmE mom)
        ("mum, mom", ["mum", "mom"]),  # 2025: mother (mum, mom)
        ("=physical education", ["physical education"]),
        ("kilogramme, kilogram", ["kilogramme", "kilogram"]),  # 2020: kilo (kilogramme, kilogram)
        ("United Nations Educational, Scientific and Cultural Organization", ["United Nations Educational, Scientific and Cultural Organization"]),
        ("Before the Common Era", ["Before the Common Era"]),  # 2025: BCE (Before the Common Era)
        ("Communist Party of China", ["Communist Party of China"]),  # appendix 缩写
        ("=mathematics，美 math", ["mathematics", "math"]),  # forms.tsv printed column (full-width comma, 美)
        ("美 center", ["center"]),  # forms.tsv centre
        ("burned, burned 或 burnt, burnt", ["burned", "burned", "burnt", "burnt"]),  # forms.tsv burn
        ("the Bund", ["the Bund"]),
        ("", []),
    ],
)
def test_r2_note_items(note, expected):
    assert N.note_items(note) == expected


def kinds(items: list[N.NoteItem]) -> list[tuple[str, str]]:
    return [(i.text, i.kind) for i in items]


@pytest.mark.parametrize(
    "head,note,expected",
    [
        ("colour", "AmE color", [("color", "variant")]),
        ("maths", "=mathematics, AmE math", [("mathematics", "variant"), ("math", "variant")]),
        ("PE", "=physical education", [("physical education", "variant")]),
        ("Mr", "AmE Mr.", [("Mr.", "alias")]),  # same lemma mr. → no member
        ("A.M.", "a.m.", [("a.m.", "alias")]),
        ("be", "am, is, are", [("am", "inflection"), ("is", "inflection"), ("are", "inflection")]),  # head ∈ {be, have, do}
        ("be", "am, are, is", [("am", "inflection"), ("are", "inflection"), ("is", "inflection")]),  # 2020/2025 order
        ("have", "has", [("has", "inflection")]),
        ("child", "pl. children", [("pl. children", "plural")]),
        ("child", "复 children", [("复 children", "plural")]),  # forms.tsv printed column
        ("policeman/policewoman", "pl. policemen/policewomen", [("pl. policemen/policewomen", "plural")]),
        ("hang", "悬挂", [("悬挂", "cjk")]),  # appendix 不规则动词 disambiguation
        ("according", "to", [("to", "collocation")]),  # function word + ``according to`` known
        ("until", "till", [("till", "variant")]),
        ("kilo", "kilogramme, kilogram", [("kilogramme", "variant"), ("kilogram", "variant")]),
        ("UNESCO", "United Nations Educational, Scientific and Cultural Organization", [("United Nations Educational, Scientific and Cultural Organization", "variant")]),
        ("BCE", "Before the Common Era", [("Before the Common Era", "unknown")]),  # no ECDICT row → unparsed_notes
        ("CE", "Common Era", [("Common Era", "variant")]),
        ("bund", "the Bund", [("the Bund", "variant")]),  # dropped later by overrides.tsv
        ("tofu", "bean curd", [("bean curd", "variant")]),
        ("a", "an", [("an", "variant")]),  # ECDICT ``an`` = 0:a without a form code → variant, not inflection (PLAN §6 S3)
        ("burn", "burned, burned 或 burnt, burnt", [("burned", "inflection"), ("burned", "inflection"), ("burnt", "inflection"), ("burnt", "inflection")]),
        ("centre", "美 center", [("center", "variant")]),
        ("television", "TV", [("TV", "variant")]),
        ("TV", "=television", [("television", "variant")]),
        ("advertisement", "ad", [("ad", "variant")]),
        ("CPC", "Communist Party of China", [("Communist Party of China", "variant")]),
        ("The United States of America", "USA", [("USA", "variant")]),
    ],
)
def test_r2_classify_note(head, note, expected):
    assert kinds(N.classify_note(head, note, lexicon=LEX, aliases=ALIASES, previous=PREVIOUS)) == expected


def test_r2_collocation_carries_the_phrase_lemma_and_alias_carries_the_form():
    (item,) = N.classify_note("according", "to", lexicon=LEX, aliases=ALIASES, previous=PREVIOUS)
    assert item.kind == "collocation" and item.phrase == "according to" and item.lemma == "to"
    (item,) = N.classify_note("Mr", "AmE Mr.", lexicon=LEX, aliases=ALIASES)
    assert item.kind == "alias" and item.lemma == "mr." and item.form is None  # ``mr.`` is already the lemma
    (item,) = N.classify_note("Mr.", "Mr", lexicon=LEX, aliases=ALIASES)
    assert item.kind == "alias" and item.form == "mr"  # the undotted spelling becomes an alias form


def test_r2_inflection_pointer_needs_a_form_code():
    """``is`` (0:be/1:3), ``has`` (1:3/0:have), ``children`` (0:child/1:s) are inflections; ``an`` (0:a) is a related alternate."""
    assert N._points_to(LEX.get("is"), "be") and N._points_to(LEX.get("has"), "have") and N._points_to(LEX.get("children"), "child")
    assert not N._points_to(LEX.get("an"), "a") and not N._points_to(None, "a")
    assert kinds(N.classify_note("child", "children", lexicon=LEX)) == [("children", "inflection")]  # exchange s:children


def test_r2_without_a_lexicon_unknown_items_stay_unknown():
    assert kinds(N.classify_note("colour", "AmE color")) == [("color", "unknown")]
    assert kinds(N.classify_note("colour", "AmE color", previous={"color"})) == [("color", "variant")]  # previous-seed lemma counts as known
    assert kinds(N.classify_note("be", "am, is, are")) == [("am", "inflection"), ("is", "inflection"), ("are", "inflection")]


# ======================================================================================= R2–R7 split_head on real lines
HEAD_CASES: list[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...], tuple[tuple[str, str], ...], tuple[str, ...], tuple[str, ...]]] = [
    # raw                                              heads                      variants                               aliases              dropped                      unparsed
    ("colour (AmE color)", ("colour",), (("color", "colour"),), (), (), ()),
    ("maths (=mathematics, AmE math)", ("maths",), (("mathematics", "maths"), ("math", "maths")), (), (), ()),
    ("mother (mum AmE mom)", ("mother",), (("mum", "mother"), ("mom", "mother")), (), (), ()),
    ("PE (=physical education)", ("p.e.",), (("physical education", "p.e."),), (("pe", "p.e."),), (), ()),
    ("Mr (AmE Mr.)", ("mr.",), (), (("mr", "mr."),), (), ()),
    ("Mrs (AmE Mrs.)", ("mrs.",), (), (("mrs", "mrs."),), (), ()),
    ("Mr (Mr.)", ("mr.",), (), (("mr", "mr."),), (), ()),  # 2025
    ("Mr", ("mr.",), (), (("mr", "mr."),), (), ()),  # shmeea
    ("A.M. (a.m.)", ("a.m.",), (), (), (), ()),
    ("be (am, is, are)", ("be",), (), (), ("am", "is", "are"), ()),
    ("be (am, are, is)", ("be",), (), (), ("am", "are", "is"), ()),
    ("have (has)", ("have",), (), (), ("has",), ()),
    ("child (pl. children)", ("child",), (), (), ("pl. children",), ()),
    ("according (to)", ("according to",), (), (), ("according",), ()),  # bare head not a previous-seed lemma
    ("until (till)", ("until",), (("till", "until"),), (), (), ()),
    ("kilo (kilogramme, kilogram)", ("kilo",), (("kilogramme", "kilo"), ("kilogram", "kilo")), (), (), ()),
    ("kilo (=kilogram)", ("kilo",), (("kilogram", "kilo"),), (), (), ()),
    ("BCE (Before the Common Era)", ("bce",), (), (), (), ("Before the Common Era",)),
    ("CE (Common Era)", ("ce",), (("common era", "ce"),), (), (), ()),
    ("bund (the Bund)", ("bund",), (("the bund", "bund"),), (), (), ()),
    ("hang (悬挂)", ("hang",), (), (), ("悬挂",), ()),
    ("e-mail (email)", ("e-mail",), (("email", "e-mail"),), (), (), ()),
    ("television (TV)", ("television",), (("tv", "television"),), (), (), ()),
    ("TV (=television)", ("tv",), (("television", "tv"),), (), (), ()),
    ("tofu (bean curd)", ("tofu",), (("bean curd", "tofu"),), (), (), ()),
    ("bean curd (tofu)", ("bean curd",), (("tofu", "bean curd"),), (), (), ()),
    ("CPC (Communist Party of China)", ("cpc",), (("communist party of china", "cpc"),), (), (), ()),
    ("UN (United Nations)", ("un",), (("united nations", "un"),), (), (), ()),
    ("The United Kingdom (UK)", ("the united kingdom",), (("uk", "the united kingdom"),), (), (), ()),
    ("a (an)", ("a",), (("an", "a"),), (), (), ()),  # PLAN §6 S3: NOT eaten by the suffix rule
    ("advertisement (ad)", ("advertisement",), (("ad", "advertisement"),), (), (), ()),
    ("ad (=advertisement)", ("ad",), (("advertisement", "ad"),), (), (), ()),
    ("father (dad)", ("father",), (("dad", "father"),), (), (), ()),
    ("goodbye (bye)", ("goodbye",), (("bye", "goodbye"),), (), (), ()),
    # R3 parallels
    ("a/an", ("a", "an"), (), (), (), ()),
    ("exam=examination", ("exam", "examination"), (), (), (), ()),
    ("grandma=grandmother", ("grandma", "grandmother"), (), (), (), ()),
    ("although/though", ("although", "though"), (), (), (), ()),
    ("actor/actress", ("actor", "actress"), (), (), (), ()),
    ("policeman/policewoman (pl. policemen/policewomen)", ("policeman", "policewoman"), (), (), ("pl. policemen/policewomen",), ()),
    # R4 attached optional suffix
    ("manner(s)", ("manner", "manners"), (), (), (), ()),
    ("toward(s)", ("toward", "towards"), (), (), (), ()),
    ("Math(s)", ("math", "maths"), (), (), (), ()),
    # R6 casing, R7 participles as heads, R1 folding
    ("Miss", ("miss",), (), (), (), ()),
    ("China", ("china",), (), (), (), ()),
    ("I", ("i",), (), (), (), ()),
    ("excited", ("excited",), (), (), (), ()),
    ("stuck", ("stuck",), (), (), (), ()),
    ("united", ("united",), (), (), (), ()),
    ("frightened", ("frightened",), (), (), (), ()),
    ("café", ("cafe",), (), (), (), ()),
    ("hot-dog", ("hot dog",), (), (("hot-dog", "hot dog"),), (), ()),
    ("humourous", ("humorous",), (), (("humourous", "humorous"),), (), ()),
    ("P.E.", ("p.e.",), (), (), (), ()),
    ("o'clock", ("o'clock",), (), (), (), ()),
    ("kung fu", ("kung fu",), (), (), (), ()),
    ("T-shirt", ("t-shirt",), (), (), (), ()),
    # R11 British / American pairs
    ("programme (AmE program)", ("programme",), (("program", "programme"),), (), (), ()),
    ("realise (AmE realize)", ("realise",), (("realize", "realise"),), (), (), ()),
    ("theatre (AmE theater)", ("theatre",), (("theater", "theatre"),), (), (), ()),
    ("colour (color)", ("colour",), (("color", "colour"),), (), (), ()),  # 2020/2025 shape without AmE
    ("centre (AmE center)", ("centre",), (("center", "centre"),), (), (), ()),
]


@pytest.mark.parametrize("raw,heads,variants,aliases,dropped,unparsed", HEAD_CASES, ids=[c[0] for c in HEAD_CASES])
def test_split_head_on_delivered_lines(raw, heads, variants, aliases, dropped, unparsed):
    p = sh(raw)
    assert p.heads == heads
    assert p.variants == variants
    assert p.aliases == aliases
    assert p.dropped == dropped
    assert p.unparsed == unparsed
    assert p.rejected == ()
    assert p.members == N._dedupe((*heads, *(v for v, _ in variants)))
    for lemma in p.members:
        assert lemma == lemma.lower() and N.strict_ok(lemma)
        assert lemma in p.printed


def test_r2_collocation_keeps_the_bare_head_only_when_it_is_a_previous_lemma():
    without = sh("according (to)")
    assert without.heads == ("according to",) and without.collocations == ("according to",) and without.dropped == ("according",)
    with_prev = sh("according (to)", previous=PREVIOUS | {"according"})
    assert with_prev.heads == ("according", "according to") and with_prev.dropped == ()
    assert with_prev.printed["according to"] == "according to"


def test_r2_drop_set_removes_the_overridden_variant():
    p = sh("bund (the Bund)", drop={"the bund"})
    assert p.heads == ("bund",) and p.variants == () and p.dropped == ("the Bund",)
    p = sh("bund (the Bund)", drop={"bund"})
    assert p.heads == ("the bund",) and p.dropped == ("bund",) and p.variants == ()  # dropped head → its variant stands alone


def test_r2_variant_of_a_head_that_made_no_member_is_promoted_to_a_head():
    """Seed record v2 (PLAN §4.5): ``variant_of`` names a member lemma, so a head rejected by R12 or dropped by
    ``overrides.tsv`` hands its bracket variants over as plain heads (review S3a F2); a member head keeps them as variants."""
    usa = sh("The United States of America (USA)")
    assert usa.heads == ("usa",) and usa.variants == () and [r.role for r in usa.rejected] == ["head"]
    dropped = sh("bund (the Bund)", drop={"bund"})
    assert dropped.heads == ("the bund",) and dropped.variants == () and dropped.dropped == ("bund",)
    ok = sh("colour (AmE color)")
    assert ok.heads == ("colour",) and ok.variants == (("color", "colour"),)
    # invariant: every variant of a line points at a head of the same line — over the rule table and the whole appendix
    for raw, *_ in HEAD_CASES:
        p = sh(raw)
        assert all(h in p.heads for _, h in p.variants), raw
    for line in list_rows(LISTS / "moe-2022-appendix.tsv"):
        p = sh(line.split("\t")[1])
        assert all(h in p.heads for _, h in p.variants), line


def test_r12_in_split_head_rejects_heads_and_variants_separately():
    p = sh("The United States of America (USA)")  # moe-2022-appendix.tsv 地理名称
    assert p.heads == ("usa",) and p.variants == ()  # the head made no member, so ``usa`` is a plain head (no dangling variant_of)
    assert [(r.text, r.role, r.reason) for r in p.rejected] == [("The United States of America", "head", words.REASON_TOO_MANY_TOKENS)]
    assert p.members == ("usa",) and p.printed == {"usa": "USA"}
    p = sh("UNESCO (United Nations Educational, Scientific and Cultural Organization)")  # 缩写
    assert p.heads == ("unesco",) and p.variants == ()
    assert [(r.lemma, r.role, r.reason) for r in p.rejected] == [("united nations educational, scientific and cultural organization", "variant", words.REASON_CHARSET)]
    assert p.unparsed == ()


def test_r4_suffix_must_be_attached_and_be_s_or_es():
    assert sh("manner(s)").heads == ("manner", "manners")
    assert sh("a (an)").heads == ("a",)  # a space before "(" is a note
    assert sh("a(an)").heads == ("a",) and sh("a(an)").variants == (("an", "a"),)  # attached but not s/es → still a note
    assert N.head_text("Math(s)") == "Math" and N.head_text("one hundred (and) one") == "one hundred (and) one"
    assert N.head_text("The United Kingdom (UK)") == "The United Kingdom"


@pytest.mark.parametrize(
    "raw,single",
    [("twenty-one", True), ("Math(s)", True), ("hundredth", True), ("one hundred", False), ("one hundred (and) one", False), ("one hundred and first", False), ("", False)],
)
def test_is_single_token_for_numeral_groups(raw, single):
    assert N.is_single_token(raw) is single


def test_split_head_printed_keeps_the_official_spelling():
    p = sh("Mr (AmE Mr.)")
    assert p.printed == {"mr.": "Mr"}
    p = sh("colour (AmE color)")
    assert p.printed == {"colour": "colour", "color": "color"}
    assert sh("").heads == () and sh("   ") == N.ParsedHead(raw="   ")


def test_r7_participle_heads_are_not_lemmatised():
    """ECDICT says excited = 0:excite/1:p, but an official head is a row of its own (seed.py's headword guard drops the form row)."""
    for raw in ("excited", "stuck", "united", "frightened"):
        assert sh(raw).heads == (N.lemma_of(raw),)
        assert LEX.get(raw).exchange.get("0")  # the lexicon really marks it as an inflection


# ======================================================================================= R6 merge_heads
def test_r6_merge_heads_unions_same_lemma_records():
    miss_cap = N.Member("miss", frozenset({"xs"}), frozenset({"moe22:l2"}), printed="Miss", lists=frozenset({"moe22:l2"}))
    miss_low = N.Member("miss", frozenset({"zk"}), frozenset({"moe22:l3", "shmeea20"}), printed="miss", lists=frozenset({"moe22:l3"}))
    tv_variant = N.Member("tv", frozenset({"zk"}), frozenset({"shmeea20"}), printed="TV", variant_of="television")
    tv_head = N.Member("tv", frozenset({"xs"}), frozenset({"moe22:l2"}), printed="TV")
    merged = N.merge_heads([miss_cap, miss_low, tv_variant, tv_head])
    assert list(merged) == ["miss", "tv"]
    assert merged["miss"] == N.Member("miss", frozenset({"xs", "zk"}), frozenset({"moe22:l2", "moe22:l3", "shmeea20"}), printed="Miss", lists=frozenset({"moe22:l2", "moe22:l3"}))
    assert merged["tv"].variant_of is None and merged["tv"].stages == frozenset({"xs", "zk"})
    only_variants = N.merge_heads([N.Member("color", variant_of="colour"), N.Member("color", stages=frozenset({"gk"}), variant_of="colour")])
    assert only_variants["color"].variant_of == "colour"


@pytest.mark.parametrize("a,b", [("Miss", "miss"), ("China", "china"), ("May", "may"), ("A.M.", "a.m."), ("Mr", "Mr.")])
def test_r6_same_lemma_pairs_from_the_lists(a, b):
    assert N.canon(a, ALIASES) == N.canon(b, ALIASES)


# ======================================================================================= R8 inheritance
INHERIT = {"be": ["am", "is", "are", "was", "were", "been", "being"], "have": ["has", "had"], "do": ["does", "did", "done"]}


def test_r8_inherit_forms_only_previous_lemmas_that_are_not_official_members():
    """``official`` is heads ∪ variants of every list (PLAN §4.2 INH: ``f ∉ L2∪L3∪SH∪HS``), not the heads alone."""
    previous = {"be", "do", "have", "am", "is", "are", "being", "does"}  # was/were/been/has/had/did/done are not seed lemmas (live-copy.db)
    official = {"be", "do", "have", "being"}  # being is a 2025 head (hs25)
    assert N.inherit_forms(INHERIT, previous, official) == {"am": "be", "is": "be", "are": "be", "does": "do"}
    # a form any list names — as a head or inside a bracket note (variant) — keeps its own membership instead of inheriting
    assert N.inherit_forms(INHERIT, previous, official | {"is"}) == {"am": "be", "are": "be", "does": "do"}
    assert N.inherit_forms(INHERIT, set(), official) == {}
    assert N.inherit_forms({"be": ["Am"], "do": ["am"]}, {"am"}, set()) == {"am": "be"}  # lemma_of + first base wins


def test_r8_inherit_forms_on_the_fixture_previous_seed():
    assert N.inherit_forms(INHERIT, PREVIOUS, {"be", "do"}) == {"am": "be", "is": "be", "are": "be", "being": "be", "does": "do"}


# ======================================================================================= R9 phrases
PHRASES: list[tuple[str, set[str]]] = [
    ("a bit (of)", {"a bit", "a bit of"}),
    ("at first/last", {"at first", "at last"}),
    ("catch (a) cold", {"catch cold", "catch a cold"}),
    ("by bus/train/plane", {"by bus", "by train", "by plane"}),
    ("be located (in/on/at)", {"be located", "be located in", "be located on", "be located at"}),
    ("go to the cinema/movie(s)", {"go to the cinema", "go to the movie", "go to the movies"}),
    ("have (got) to", {"have to", "have got to"}),
    ("go to (the) hospital", {"go to hospital", "go to the hospital"}),
    ("be/get familiar to/with", {"be familiar to", "be familiar with", "get familiar to", "get familiar with"}),
    ("on the/one's way (to)", {"on the way", "on the way to", "on one's way", "on one's way to"}),
    ("add...to", {"add ... to"}),
    ("not...at all", {"not ... at all"}),
    ("agree with sb.", {"agree with sb."}),
    ("a lot of/lots of", {"a lot of of", "a lot lots of"}),  # PLAN R9: token-level only — the cross-token parallel is not recovered
    ("a couple of", {"a couple of"}),
    ("", set()),
]


@pytest.mark.parametrize("raw,expected", PHRASES, ids=[repr(c[0]) for c in PHRASES])
def test_r9_phrase_candidates(raw, expected):
    assert N.phrase_candidates(raw) == expected


def test_r9_resolve_phrase_members_skips_and_rejections():
    r = N.resolve_phrase("a bit (of)", lexicon=LEX, aliases=ALIASES)
    assert r.members == ("a bit", "a bit of") and r.skipped is None and r.rejected == ()
    assert N.resolve_phrase("at first/last", lexicon=LEX).members == ("at first", "at last")
    assert N.resolve_phrase("catch (a) cold", lexicon=LEX).members == ("catch a cold", "catch cold")
    assert N.resolve_phrase("by bus/train/plane", lexicon=LEX).members == ("by bus", "by plane", "by train")
    assert N.resolve_phrase("be located (in/on/at)", lexicon=LEX).members == ("be located", "be located at", "be located in", "be located on")
    r = N.resolve_phrase("agree with sb.", lexicon=LEX)
    assert r.members == () and r.skipped == "patterns"
    r = N.resolve_phrase("add...to", lexicon=LEX)
    assert r.members == () and r.skipped == "patterns"
    assert [(x.text, x.role, x.reason) for x in r.rejected] == [("add ... to", "phrase", words.REASON_PUNCT_TOKEN)]
    r = N.resolve_phrase("get into the habit of", lexicon=LEX)  # the 7th R12 rejection of PLAN §4.3: five tokens, no template marker
    assert r.members == () and r.skipped == "other"
    assert [(x.text, x.role, x.reason) for x in r.rejected] == [("get into the habit of", "phrase", words.REASON_TOO_MANY_TOKENS)]
    r = N.resolve_phrase("a lot of/lots of", lexicon=LEX)
    assert r.members == () and r.skipped == "other"
    r = N.resolve_phrase("arrive at/in a place", lexicon=LEX)
    assert r.members == () and r.skipped == "other"
    assert N.resolve_phrase("save one's life", lexicon=LEX).members == ("save one's life",)  # template marker but a known phrase
    assert N.resolve_phrase("talk to/with sb.", lexicon=LEX).members == ("talk to sb.",)
    assert N.resolve_phrase("according (to)", lexicon=None, previous=PREVIOUS).members == ("according to",)  # previous lemma counts as known
    assert N.resolve_phrase("tofu", lexicon=LEX).members == () and N.resolve_phrase("tofu", lexicon=LEX).skipped == "other"  # no space → never a phrase


@pytest.mark.parametrize(
    "raw,template",
    [("agree with sb.", True), ("help sb. with sth.", True), ("do one's best", True), ("enjoy oneself", True), ("add...to", True), ("add…to", True), ("a bit (of)", False), ("by bus/train/plane", False)],
)
def test_r9_is_template(raw, template):
    assert N.is_template(raw) is template


def test_r9_every_delivered_phrase_expands_and_all_sixteen_dotted_lines_fail_strict():
    """All 342 lines expand, and no expansion of the 16 ``...`` lines can pass R12 (``...`` is a punctuation-only token).

    PLAN §4.3 R12's 「7 条 ``...`` 词组」 counts the phrases that REACH the gate with the real ECDICT, not the dotted lines:
    the six dotted lines ECDICT lists (``add...to``, ``keep...from``, ``prefer...to``, ``provide...with``, ``see...off``,
    ``share...with``) plus the five-token ``get into the habit of``; the other ten dotted lines have no row and are
    skipped as ``patterns`` before R12 (``test_r9_resolve_phrase_members_skips_and_rejections`` pins both shapes).
    """
    rows = list_rows(LISTS / "shmeea-2020-junior-phrases.txt")
    assert len(rows) == 342
    dotted = []
    for raw in rows:
        cands = N.phrase_candidates(raw)
        assert cands and all(c == N._squash(c) for c in cands)
        if "..." in N.fold(raw):
            dotted.append(raw)
            assert all(not N.strict_ok(N.canon(c, ALIASES)) for c in cands)
    assert len(dotted) == 16  # add...to, as...as, both...and, keep...from, no longer/not...any longer, not...at all, prefer...to, …


# ======================================================================================= whole-list smoke (delivered files)
@pytest.mark.parametrize(
    "name,expect_rows",
    [("moe-2022-level2.txt", 505), ("moe-2022-level3.txt", 1600), ("shmeea-2020-junior.txt", 1724), ("moe-2020-senior.tsv", 3000), ("moe-2025rev-senior.tsv", 3099)],
)
def test_every_main_list_head_yields_a_member_and_passes_strict(name, expect_rows):
    path = LISTS / name
    rows = list_rows(path)
    assert len(rows) == expect_rows
    for line in rows:
        p = N.split_head(head_cell(path, line), aliases=ALIASES)  # no lexicon: notes stay unknown, heads are grammar only
        assert p.heads, line
        assert p.rejected == (), line
        for lemma in p.heads:
            assert lemma == lemma.lower() and not N.has_cjk(lemma)


def test_appendix_heads_only_the_usa_fails_strict_and_cjk_only_in_irregular_verbs():
    rows = list_rows(LISTS / "moe-2022-appendix.tsv")
    assert len(rows) == 267
    rejected, cjk_groups = [], set()
    for line in rows:
        group, word, *_ = line.split("\t")
        if N.has_cjk(word):
            cjk_groups.add(group)
        p = N.split_head(word, aliases=ALIASES)
        rejected += [r.text for r in p.rejected if r.role == "head"]
    assert rejected == ["The United States of America"]
    assert cjk_groups == {"不规则动词"}  # hang (悬挂), lie (躺): member: false group, dropped before membership


# ======================================================================================= data/lists metadata (S3a files)
OVERRIDE_FIELDS = {"translation", "word", "phonetic", "definition", "drop"}


def test_manifest_lists_the_eleven_delivered_files_and_matches_their_row_counts():
    m = json.loads((LISTS / "manifest.json").read_text(encoding="utf-8"))
    assert m["format"] == 2 and len(m["lists"]) == 11
    assert m["checksums"] == "SHA256SUMS" and m["aliases"] == "aliases.tsv" and m["overrides"] == "overrides.tsv"
    assert m["ecdict_member_tags"] == ["cet4", "cet6"] and set(m["inherit_stages"]) == {"be", "have", "do"}
    ids = [l["id"] for l in m["lists"]]
    assert len(set(ids)) == 11 and {"moe22:l2", "moe22:l3", "moe22:app", "shmeea20", "shmeea20:app", "shmeea20:phr", "shmeea20:forms", "hs25", "hs20", "hs25:app", "hs20:app"} == set(ids)
    for spec in m["lists"]:
        path = LISTS / spec["file"]
        assert path.is_file(), spec["file"]
        assert len(list_rows(path)) == spec["expect_rows"], spec["id"]
        assert spec["policy"] in {"main", "appendix", "phrases", "reference"} and spec["format"] in {"heads", "tsv", "phrases"}
        for stage in spec.get("stages", []):
            assert stage in schemas.STAGE_ORDER
        for group in spec.get("groups", {}).values():
            for stage in group.get("stages", []):
                assert stage in schemas.STAGE_ORDER
        if spec["format"] == "tsv":
            assert spec["columns"] and all(len(l.split("\t")) == len(spec["columns"]) for l in list_rows(path)), spec["id"]
    by_id = {l["id"]: l for l in m["lists"]}
    assert by_id["hs20"]["level_token"] == "hs20:{level}" and by_id["hs25"]["level_token"] == "hs25:{level}" and by_id["hs25"]["provisional"] is True
    assert by_id["moe22:app"]["groups"]["不规则动词"] == {"member": False} and by_id["shmeea20:app"]["groups"]["*"] == {"stages": ["zk"]}
    # the stage order and the zh stage names live in schemas.py only
    assert not {"stage_order", "stages", "stage_names", "stage_names_zh", "order"} & set(m)
    text = (LISTS / "manifest.json").read_text(encoding="utf-8")
    assert "小学" not in text  # the new stage's name appears nowhere; list titles may quote official document names

    def leaves(node):
        if isinstance(node, dict):
            for v in node.values():
                yield from leaves(v)
        elif isinstance(node, list):
            for v in node:
                yield from leaves(v)
        else:
            yield node

    assert not set(schemas.STAGE_NAMES_ZH.values()) & {v for v in leaves(m) if isinstance(v, str)}


def test_sha256sums_covers_exactly_the_eleven_list_files_and_matches():
    lines = [l for l in (LISTS / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 11
    m = json.loads((LISTS / "manifest.json").read_text(encoding="utf-8"))
    listed = {l.split("  ", 1)[1] for l in lines}
    assert listed == {spec["file"] for spec in m["lists"]}
    for line in lines:
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((LISTS / name).read_bytes()).hexdigest() == digest, name
    assert "README.md" not in listed and "manifest.json" not in listed


def test_overrides_tsv_has_the_twenty_eight_rows_within_the_field_enum():
    """PLAN §4.1 / P13: ≤ 30 rows, every field in OVERRIDE_FIELDS, one (lemma, field) each, lemma already normalised. 23 rows
    from S3, the three the final review added (`am` display + translation, `mrs.` display — impl-review final F3) and the two
    the integration pass added after reading the imported 小学 / 初中 rows (`is` second line was computing jargon, `download`
    was glossed 「卸载」= uninstall)."""
    rows = list_rows(LISTS / "overrides.tsv")
    assert len(rows) == 28 <= 30
    seen = set()
    for line in rows:
        lemma, fld, value, note = line.split("\t")
        assert fld in OVERRIDE_FIELDS, line
        assert lemma == N.lemma_of(lemma), lemma  # already a lemma (no aliases apply to the previous seed)
        assert (lemma, fld) not in seen
        seen.add((lemma, fld))
        if fld == "drop":
            assert value == ""
        else:
            assert value and note
    by_lemma = {l.split("\t")[0]: l.split("\t")[1] for l in rows}
    assert by_lemma["the bund"] == "drop" and by_lemma["e-mail"] == "word" and by_lemma["bund"] == "translation" and by_lemma["stuck"] == "translation"
    fields = {(l.split("\t")[0], l.split("\t")[1]): l.split("\t")[2] for l in rows}
    assert fields[("am", "word")] == "am" and fields[("am", "translation")].startswith("v. 是") and fields[("mrs.", "word")] == "Mrs."


def test_aliases_tsv_rows_are_official_spellings_of_the_lists():
    rows = list_rows(LISTS / "aliases.tsv")
    assert len(rows) == 6
    heads = set()
    for name in ("moe-2022-level2.txt", "moe-2022-level3.txt", "shmeea-2020-junior.txt", "moe-2025rev-senior.tsv"):
        path = LISTS / name
        heads |= {N.head_text(head_cell(path, l)).lower() for l in list_rows(path)}
    for line in rows:
        spelling = line.split("\t")[0]
        assert spelling.lower() in heads, spelling


# ======================================================================================= fixture directory (for S3b)
def test_fixture_manifest_and_checksums_are_consistent():
    m = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    assert m["format"] == 2 and len(m["lists"]) == 6
    sums = dict(reversed(l.split("  ", 1)) for l in (FIXTURES / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if l.strip())
    assert set(sums) == {spec["file"] for spec in m["lists"]}
    for spec in m["lists"]:
        path = FIXTURES / spec["file"]
        assert len(list_rows(path)) == spec["expect_rows"], spec["id"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sums[spec["file"]]
        for stage in spec.get("stages", []):
            assert stage in schemas.STAGE_ORDER
    assert N.load_aliases((FIXTURES / "aliases.tsv").read_text(encoding="utf-8")) == ALIASES
    ov = [l.split("\t") for l in list_rows(FIXTURES / "overrides.tsv")]
    assert len(ov) == 9 and all(f in OVERRIDE_FIELDS for _, f, _, _ in ov)


REAL_OF = {
    "mini-moe-2022-level2.txt": "moe-2022-level2.txt",
    "mini-moe-2022-level3.txt": "moe-2022-level3.txt",
    "mini-moe-2022-appendix.tsv": "moe-2022-appendix.tsv",
    "mini-shmeea-2020-junior.txt": "shmeea-2020-junior.txt",
    "mini-shmeea-2020-junior-phrases.txt": "shmeea-2020-junior-phrases.txt",
    "mini-moe-2025rev-senior.tsv": "moe-2025rev-senior.tsv",
}


@pytest.mark.parametrize("mini,real", sorted(REAL_OF.items()))
def test_every_fixture_line_is_a_verbatim_line_of_the_delivered_file(mini, real):
    real_rows = set(list_rows(LISTS / real))
    rows = list_rows(FIXTURES / mini)
    assert rows and all(l in real_rows for l in rows), [l for l in rows if l not in real_rows]
    level2 = list_rows(FIXTURES / "mini-moe-2022-level2.txt")
    assert set(level2) <= set(list_rows(FIXTURES / "mini-moe-2022-level3.txt"))  # xs ⊆ zk by construction


def test_fixture_mini_stardict_loads_and_holds_the_plan_rows():
    conn = sqlite3.connect(":memory:")
    conn.executescript((FIXTURES / "mini_stardict.sql").read_text(encoding="utf-8"))
    assert conn.execute("SELECT COUNT(*) FROM stardict").fetchone()[0] >= 100
    for word in ("Mr", "Mr.", "hot dog", "hotdog", "hot-dog", "excited", "the Bund", "humourous", "an", "is", "has", "children", "according to", "a bit of", "save one's life"):
        assert conn.execute("SELECT COUNT(*) FROM stardict WHERE word = ? COLLATE NOCASE", (word,)).fetchone()[0] == 1, word
    assert conn.execute("SELECT exchange FROM stardict WHERE word = 'an'").fetchone()[0] == "0:a/s:some"
    assert conn.execute("SELECT exchange FROM stardict WHERE word = 'is'").fetchone()[0] == "0:be/1:3"
    assert conn.execute("SELECT COUNT(*) FROM stardict WHERE word = 'breakdown'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM stardict WHERE word = 'break down'").fetchone()[0] == 0  # R10 negative case stays negative
    # the one ECDICT value with a CR (row ``a``) is spelled char(13, 10) in the file: the text-mode read above (universal
    # newlines) would turn a raw ``\r\n`` into ``\n`` and the row would no longer be verbatim (review S3a F4)
    assert b"\r" not in (FIXTURES / "mini_stardict.sql").read_bytes()
    assert conn.execute("SELECT translation FROM stardict WHERE word = 'a'").fetchone()[0] == "第一个字母 A; 一个; 第一的\r\nart. [计] 累加器, 加法器, 地址, 振幅, 模拟, 区域, 面积, 汇编, 组件, 异步"
    conn.close()


def test_fixture_previous_seed_is_v1_shaped_with_the_inheritance_and_retain_rows():
    records = [json.loads(l) for l in (FIXTURES / "previous_seed.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    lemmas = [N.lemma_of(r["word"]) for r in records]
    assert len(records) == 53 and len(set(lemmas)) == 53
    assert {"am", "is", "are", "does", "being", "hotdog", "humourous", "bookshelf", "according to", "mum", "colour", "color", "mr.", "p.e."} <= set(lemmas)
    for r in records:
        assert set(r) == {"word", "phonetic", "translation", "definition", "pos", "collins", "oxford", "stages", "exam_tags", "bnc", "frq", "exchange", "sources", "ecdict_id", "cet6_star"}
        assert all(s in ("zk", "gk", "cet4", "cet6") for s in r["stages"])  # v1 codes (pre-0011)
    assert "according" not in lemmas  # so ``according (to)`` drops its bare head in the fixture build
