"""wd.dance — the rule-based 「单词之舞」 DanceSpec (docs/WORD_DANCE_DESIGN.md §4.1–4.2, §10; API.md §9 ``DanceSpec``).

A golden table pins the chunking, stress and letter marks of words that exercise every rule (ECDICT and IPA notations, the old
double-stress marks, syllabic consonants, triphthongs, magic e, hiatus, iə / uə read as two syllables, /ʃ/ spellings, -le /
-tion / -ing / -ieth endings, r-coloured vowels, secondary stress, the elided-schwa and -teen rules, the two phonetic
overrides), then two sweeps check the invariants over the mini seed and over the full shipped seed: the chunks always spell the
display form, the stress index is in range, marks point at real letters, and the function never raises. P3b adds the -er suffix
cut: a golden table for ``spec_for(..., er_stem=…)``, the four tests of ``er_evidence`` on synthetic bank rows (true derivations in,
cor·ner / cen·ter / but·ter / for·mer / ten·der / with·er / num·ber out), ``er_stem`` + ``rule_spec`` against the bank, and the
list of every seed word the rule applies to pinned in ``tests/fixtures/dance_er_splits.json``."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from wd import dance, db, schemas

REPO = Path(__file__).resolve().parents[3]
FULL_SEED = REPO / "data" / "seed" / "vocab.jsonl.gz"
ER_SPLITS = Path(__file__).resolve().parents[1] / "fixtures" / "dance_er_splits.json"

# word, phonetic, chunks, stress, silent letter indexes, double letter pairs
GOLDEN = [
    ("rabbit", "'ræbit", "rab·bit", 0, [], [[2, 3]]),
    ("banana", "bə'nɑːnə", "ba·na·na", 1, [], []),
    ("yesterday", "'jestədi", "yes·ter·day", 0, [], []),
    ("elephant", "'elifənt", "el·e·phant", 0, [], []),
    ("happy", "'hæpi", "hap·py", 0, [], [[2, 3]]),
    ("night", "nait", "night", 0, [2, 3], []),
    ("fight", "fait", "fight", 0, [2, 3], []),  # the gh is silent although the word has an /f/ of its own
    ("laugh", "lɑːf", "laugh", 0, [], []),  # … but not when gh IS the /f/
    ("daughter", "'dɔːtə", "daugh·ter", 0, [3, 4], []),
    ("apple", "'æpl", "ap·ple", 0, [], [[1, 2]]),
    ("little", "'litl", "lit·tle", 0, [], [[2, 3]]),
    ("table", "'teibl", "ta·ble", 0, [], []),
    ("seven", "'sevn", "sev·en", 0, [], []),
    ("seventeen", "sevn'tiːn", "sev·en·teen", 2, [], [[6, 7]]),
    ("fifteen", "'fif'tiːn", "fif·teen", 1, [], [[4, 5]]),  # old double-stress notation: the last mark is the primary
    ("thirteenth", "'θɜːtiːnθ", "thir·teenth", 1, [], [[5, 6]]),  # the -teen numerals stress -teen whatever ECDICT marks
    ("afternoon", "'ɑːftə'nuːn", "af·ter·noon", 2, [], [[6, 7]]),
    ("email", "'iː'meil", "e·mail", 0, [], []),  # phonetic override: modern ˈiːmeɪl
    ("august", "ɔː'gʌst. 'ɔːgəst", "au·gust", 0, [], []),  # phonetic override: the month, not the adjective
    ("student", "'stjuːdnt", "stu·dent", 0, [], []),
    ("final", "'fainl", "fi·nal", 0, [], []),  # syllabic l after n
    ("personal", "'pɜːsnl", "per·son·al", 0, [], []),  # two syllabic consonants; the n stays in its chunk
    ("eleven", "i'levn", "e·lev·en", 1, [], []),
    ("about", "ə'baut", "a·bout", 1, [], []),
    ("begin", "bi'gin", "be·gin", 1, [], []),
    ("open", "'əupən", "o·pen", 0, [], []),
    ("water", "'wɔːtə", "wa·ter", 0, [], []),
    ("orange", "'ɔːrindʒ", "or·ange", 0, [5], []),  # r-coloured vowel keeps its r
    ("visit", "'vizit", "vis·it", 0, [], []),
    ("city", "'siti", "cit·y", 0, [], []),
    ("computer", "kəm'pjuːtə", "com·pu·ter", 1, [], []),
    ("people", "'piːpl", "peo·ple", 0, [], []),
    ("basket", "'bɑːskit", "bas·ket", 0, [], []),
    ("sister", "'sistə", "sis·ter", 0, [], []),
    ("chicken", "'tʃikin", "chick·en", 0, [], []),
    ("kitchen", "'kitʃin", "kitch·en", 0, [], []),
    ("teacher", "'tiːtʃə", "tea·cher", 0, [], []),
    ("mother", "'mʌðə", "moth·er", 0, [], []),
    ("father", "'fɑːðə", "fa·ther", 0, [], []),
    ("hundred", "'hʌndrəd", "hun·dred", 0, [], []),
    ("question", "'kwestʃən", "ques·tion", 0, [], []),
    ("national", "'næʃənl", "na·tion·al", 0, [], []),  # the ti of /ʃ/ opens the suffix, the n stays with it
    ("special", "'speʃəl", "spe·cial", 0, [], []),
    ("situation", ".sitʃu'eiʃən", "sit·u·a·tion", 2, [], []),
    ("television", "'teli.viʒən", "tel·e·vi·sion", 0, [], []),
    ("mathematics", ".mæθə'mætiks", "math·e·mat·ics", 2, [], []),
    ("between", "bi'twiːn", "be·tween", 1, [], [[4, 5]]),
    ("quiet", "'kwaiət", "qui·et", 0, [], []),
    ("lion", "'laiən", "li·on", 0, [], []),
    ("science", "'saiəns", "sci·ence", 0, [6], []),
    ("create", "kri'eit", "cre·ate", 1, [5], []),
    ("hour", "auə", "hour", 0, [0], []),
    ("fire", "'faiə", "fire", 0, [3], []),
    ("tired", "taiəd", "tired", 0, [3], []),
    ("flower", "'flauə", "flow·er", 0, [], []),
    ("player", "'pleiə", "play·er", 0, [], []),  # y closes the vowel team when the transcription has no /j/
    ("beyond", "bi'jɒnd", "be·yond", 1, [], []),
    ("serious", "'siəriəs", "se·ri·ous", 0, [], []),  # the second iə spells two syllables
    ("January", "'dʒænjuəri", "Jan·u·a·ry", 0, [], []),
    ("careful", "'kєəful", "care·ful", 0, [3], []),
    ("nineteen", ".nain'tiːn", "nine·teen", 1, [3], [[5, 6]]),
    ("ninetieth", "'naintiiθ", "nine·ti·eth", 0, [3], []),
    ("twentieth", "'twentiiθ", "twen·ti·eth", 0, [], []),
    ("interesting", "'intristiŋ", "in·ter·est·ing", 0, [], []),  # elided schwa read back from the spelling; -ing keeps the base
    ("meeting", "'miːtiŋ", "meet·ing", 0, [], [[1, 2]]),
    ("something", "'sʌmθiŋ", "some·thing", 0, [3], []),
    ("pudding", "'pudiŋ", "pud·ding", 0, [], [[2, 3]]),
    ("being", "'biːiŋ", "be·ing", 0, [], []),
    ("business", "'biznis", "bus·i·ness", 0, [], [[6, 7]]),
    ("dance", "dæns. dɑːns", "dance", 0, [4], []),
    ("live", "liv.laiv", "live", 0, [3], []),
    ("grandpa", "'^rænpɑː, '^rændpɑː", "grand·pa", 0, [], []),
    ("knife", "naif", "knife", 0, [0, 4], []),
    ("write", "rait", "write", 0, [0, 4], []),
    ("who", "huː", "who", 0, [0], []),
    ("whole", "həul", "whole", 0, [0, 4], []),
    ("two", "tuː", "two", 0, [1], []),
    ("walk", "wɔːk", "walk", 0, [2], []),
    ("would", "wud", "would", 0, [3], []),
    ("listen", "'lisn", "lis·ten", 0, [3], []),
    ("often", "'ɔːfn", "of·ten", 0, [2], []),
    ("answer", "'ɑːnsə", "an·swer", 0, [3], []),
    ("climb", "klaim", "climb", 0, [4], []),
    ("autumn", "'ɔːtəm", "au·tumn", 0, [5], []),
    ("though", "ðəu", "though", 0, [4, 5], []),
    ("the", "ðə", "the", 0, [], []),
    ("abandon", "ə'bændən", "a·ban·don", 1, [], []),
    ("abandon", "əˈbændən", "a·ban·don", 1, [], []),  # the IPA stress mark of Claude-looked-up words
    ("Monday", "'mʌndi", "Mon·day", 0, [], []),
    ("Wednesday", "'wenzdi", "Wednes·day", 0, [2, 4], []),  # the first d and the e are unsounded
    ("I", "ai", "I", 0, [], []),
    ("uncle", "ʌŋkl", "un·cle", 0, [], []),  # no stress mark → the first non-schwa chunk
    ("honest", "'ɒnist", "hon·est", 0, [0], []),  # the silent h behind a stress mark
    ("signal", "'signl", "sig·nal", 0, [], []),  # one syllable for the n + l run (per·son·al keeps two)
    ("camel", "'kæml", "cam·el", 0, [], []),  # syllabic l after m
    ("lifestyle", "'laifstail", "life·style", 0, [3, 8], []),  # y + le keeps its magic e
    ("style", "stail", "style", 0, [4], []),  # … and a monosyllable never gains a chunk for it
    ("league", "liːg", "league", 0, [], []),  # a silent -ue is not an elided syllable: one chunk
    ("unique", "juː'niːk", "unique", None, [], []),
    ("completely", "kəm'pliːtli", "completely", None, [], []),  # a silent e before -ly is not an elided syllable
    ("somewhere", "'sʌmhwєə", "somewhere", None, [8], []),
]


@pytest.mark.parametrize("word,phonetic,chunks,stress,silent,double", GOLDEN, ids=[f"{g[0]}-{i}" for i, g in enumerate(GOLDEN)])
def test_golden_table(word, phonetic, chunks, stress, silent, double):
    spec = dance.spec_for(word, phonetic)
    assert spec is not None
    assert "·".join(spec["letters"]) == chunks
    assert spec["stress"] == stress
    assert spec["marks"] == {"double": double, "silent": silent}
    assert spec["version"] == dance.DANCE_SPEC_VERSION == 1 and spec["source"] == "rule" and spec["semantic"] is None
    schemas.DanceSpec.model_validate(spec)


def test_no_spec_for_phrases_abbreviations_and_missing_phonetics():
    assert dance.spec_for("ice cream", "ais kriːm") is None
    assert dance.spec_for("Mr.", "'mistə(r)") is None
    assert dance.spec_for("o'clock", "ə'klɔk") is None
    assert dance.spec_for("ping-pong", "'piŋpɔŋ") is None
    assert dance.spec_for("apple", None) is None and dance.spec_for("apple", "") is None
    assert dance.spec_for("", "ə") is None and dance.spec_for(None, "ə") is None


def test_disagreement_falls_back_to_one_chunk():
    # a spelling with fewer vowel groups than the transcription has nuclei and no hiatus to split: one chunk, stress unknown
    spec = dance.spec_for("rhythm", "'riðəm")
    assert spec == {"version": 1, "letters": ["rhythm"], "stress": None, "marks": {"double": [], "silent": []}, "semantic": None, "source": "rule"}
    # letters without a vowel letter (an abbreviation) stay one chunk too
    assert dance.spec_for("TV", "'tiː'viː")["letters"] == ["TV"]


def test_nuclei_read_both_notations_and_variants():
    assert [n.symbol for n in dance.nuclei("bə'nɑːnə")] == ["ə", "ɑː", "ə"]
    assert [n.primary for n in dance.nuclei("bə'nɑːnə")] == [False, True, False]
    assert [n.stressed for n in dance.nuclei(".mæθə'mætiks")] == [True, False, True, False]  # a leading secondary mark counts as stressed
    assert [n.primary for n in dance.nuclei("'fif'tiːn")] == [False, True] and [n.stressed for n in dance.nuclei("'fif'tiːn")] == [True, True]
    assert [n.symbol for n in dance.nuclei("'æpl")] == ["æ", "ə"] and dance.nuclei("'æpl")[1].syllabic == "l"
    assert [n.symbol for n in dance.nuclei("kɔːl")] == ["ɔː"]  # a long vowel before l is not a syllabic consonant
    assert [n.symbol for n in dance.nuclei("'pɜːsnl")] == ["ɜː", "ə", "ə"]  # n after s, l after n
    assert dance.first_variant("dæns. dɑːns") == "dæns" and dance.first_variant("liv.laiv") == "liv" and dance.first_variant("'teli.viʒən") == "'teli.viʒən"
    assert dance.first_variant(".mæθə'mætiks").startswith(".")  # a leading secondary mark survives
    assert [n.tri for n in dance.nuclei("auə")] == [False, True]


def _check(display: str, phonetic: str | None) -> None:
    spec = dance.spec_for(display, phonetic)
    if spec is None:
        return
    assert "".join(spec["letters"]) == display and all(spec["letters"])
    assert spec["stress"] is None or 0 <= spec["stress"] < len(spec["letters"])
    assert all(0 <= i < len(display) for i in spec["marks"]["silent"])
    assert all(len(p) == 2 and 0 <= p[0] < p[1] < len(display) and display[p[0]].lower() == display[p[1]].lower() for p in spec["marks"]["double"])
    schemas.DanceSpec.model_validate(spec)


def test_invariants_over_the_mini_seed(seeded):
    rows = seeded.execute("SELECT display, lemma, phonetic FROM words").fetchall()
    assert rows
    for r in rows:
        _check(r["display"] or r["lemma"], r["phonetic"])


def test_invariants_and_coverage_over_the_full_seed():
    if not FULL_SEED.is_file():
        pytest.skip("data/seed/vocab.jsonl.gz not present")
    total = split = 0
    none: set[str] = set()
    one_chunk_poly: set[str] = set()
    with gzip.open(FULL_SEED, "rt", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            display = row.get("display") or row["lemma"]
            phonetic = row.get("phonetic")
            _check(display, phonetic)
            if "xs" not in (row.get("stages") or []):
                continue
            total += 1
            spec = dance.spec_for(display, phonetic)
            if spec is None:
                none.add(display.lower())
            elif len(spec["letters"]) > 1 or len(dance._merge_triphthongs(dance.nuclei(phonetic or ""))) == 1:
                split += 1  # cut, or a monosyllable (fire / hour / our / tired read as one syllable on purpose)
            else:
                one_chunk_poly.add(display.lower())
    # the 小学 list (release note §1): phrases / abbreviations with a dot or a space have no spec; two letter-only abbreviations
    # with no vowel letter stay one chunk; every other word is cut or a monosyllable
    assert total >= 500
    assert none == {"ice cream", "physical education", "mr.", "mrs.", "ms.", "p.e.", "ping-pong", "o'clock"}
    assert one_chunk_poly == {"ok", "tv"}
    assert split / total >= 0.97


# ------------------------------------------------------------------------------------------------- the -er suffix (P3b)
# word, phonetic, stem, stem phonetic → chunks, stress, silent, double (double over the whole word; silent = the stem's own silent
# letters plus the whole word's pattern letters — never the ordinary reading the cut rejected)
ER_GOLDEN = [
    ("worker", "'wɜːkə", "work", "wɜːk", "work·er", 0, [], []),
    ("farmer", "'fɑːmə", "farm", "fɑːm", "farm·er", 0, [], []),
    ("teacher", "'tiːtʃə", "teach", "tiːtʃ", "teach·er", 0, [], []),  # the cut the P2 model had to make by hand
    ("seller", "'selə", "sell", "sel", "sell·er", 0, [], [[2, 3]]),  # the doubled l stays with its stem, not sel·ler
    ("quieter", "'kwaiətə", "quiet", "'kwaiət", "qui·et·er", 0, [], []),  # a polysyllabic stem keeps its own cut
    ("reporter", "ri'pɔːtə", "report", "ri'pɔːt", "re·port·er", 1, [], []),
    ("listener", "'lisnə", "listen", "'lisn", "lis·ten·er", 0, [3], []),  # the transcription swallows the stem's syllabic n; the stem's silent t, not the e
    ("traveler", "'trævlə", "travel", "'trævl", "trav·el·er", 0, [], []),  # travel marks nothing silent, so neither does its -er word
    ("fastener", "'fɑːsnə", "fasten", "'fɑːsn", "fas·ten·er", 0, [3], []),
    ("foreigner", "'fɔrinə", "foreign", "'fɔrin", "for·eign·er", 0, [], []),
    ("lower", "'ləuə", "low", "ləu", "low·er", 0, [], []),
]


@pytest.mark.parametrize("word,phonetic,stem,stem_phonetic,chunks,stress,silent,double", ER_GOLDEN, ids=[g[0] for g in ER_GOLDEN])
def test_er_golden_table(word, phonetic, stem, stem_phonetic, chunks, stress, silent, double):
    spec = dance.spec_for(word, phonetic, er_stem=(stem, stem_phonetic))
    assert spec is not None
    assert "·".join(spec["letters"]) == chunks and spec["stress"] == stress
    assert spec["marks"] == {"double": double, "silent": silent}
    assert spec["source"] == "rule" and spec["semantic"] is None
    schemas.DanceSpec.model_validate(spec)
    stem_spec = dance.spec_for(stem, stem_phonetic)
    assert spec["letters"][:-1] == stem_spec["letters"]  # the stem's own cut, plus the suffix chunk
    assert set(stem_spec["marks"]["silent"]) <= set(spec["marks"]["silent"])  # … and the stem's silent letters at the same offsets
    for chunk_start, chunk in zip([0, *__import__("itertools").accumulate(len(c) for c in spec["letters"])], spec["letters"]):
        vowels = [chunk_start + i for i, ch in enumerate(chunk.lower()) if ch in "aeiouy"]
        assert not vowels or not set(vowels) <= set(spec["marks"]["silent"]), (chunk, spec["marks"])  # a syllable never mutes its only vowel letter


def test_er_hint_is_ignored_when_it_cannot_apply():
    plain = dance.spec_for("number", "'nʌmbə")
    assert plain["letters"] == ["num", "ber"]
    # the transcriptions do not compose (/bə/ is not the suffix): the ordinary cut, even with a hint
    assert dance.spec_for("number", "'nʌmbə", er_stem=("numb", "nʌm")) == plain
    # a hint for another stem, a stem without a phonetic, a stem that is not the display minus -er: ordinary cut
    assert dance.spec_for("worker", "'wɜːkə", er_stem=("wor", "wɜː")) == dance.spec_for("worker", "'wɜːkə")
    assert dance.spec_for("worker", "'wɜːkə", er_stem=("work", "")) == dance.spec_for("worker", "'wɜːkə")
    assert dance.spec_for("worker", "'wɜːkə", er_stem=("walk", "wɔːk")) == dance.spec_for("worker", "'wɜːkə")
    # the syllable count must add up: a stem whose chunk count is not its syllable count gets no suffix cut
    assert dance.spec_for("rhythmer", "'riðəmə", er_stem=("rhythm", "'riðəm"))["letters"] == dance.spec_for("rhythmer", "'riðəmə")["letters"]
    # no hint = the P1 behaviour byte for byte
    assert dance.spec_for("teacher", "'tiːtʃə")["letters"] == ["tea", "cher"]


def _row(display, phonetic, *, translation="", definition="", pos=None, exchange=None):
    return {"display": display, "lemma": display.lower(), "phonetic": phonetic, "translation": translation, "definition": definition, "pos": pos, "exchange_json": exchange}


def test_er_evidence_accepts_true_derivations():
    work = _row("work", "wɜːk", translation="n. 工作, 劳动", pos="n:38/v:62")
    assert dance.er_evidence(_row("worker", "'wɜːkə", translation="n. 工人", definition="n. a person who works at a specific occupation", pos="n:100"), work) == "definition"
    # inflected mentions count (works / working), the stem as a bare substring does not (workaholic)
    assert dance.er_evidence(_row("worker", "'wɜːkə", definition="someone working for wages", pos="n:100"), work) == "definition"
    assert dance.er_evidence(_row("worker", "'wɜːkə", definition="a workaholic", pos="n:100"), work) is None
    farm = _row("farm", "fɑːm", translation="n. 农场, 农田 vt. 耕种", pos="v:4/n:96")
    assert dance.er_evidence(_row("farmer", "'fɑːmə", translation="n. 农夫, 农场主", definition="n. a person who operates a farm", pos="n:100"), farm) == "definition"
    assert dance.er_evidence(_row("farmer", "'fɑːmə", translation="n. 农夫, 农场主", definition="", pos="n:100"), farm) == "translation"  # 农场 shared
    low = _row("low", "ləu", translation="a. 低的", pos="r:4/j:93/v:1/n:2")
    assert dance.er_evidence(_row("lower", "'ləuə", translation="a. 低的, 下级的 vi. 降低", pos="v:100", exchange='{"0": "low", "1": "r"}'), low) == "comparative"
    assert dance.er_evidence(_row("lower", "'ləuə", translation="a. 低的", pos="v:100", exchange={"0": "low", "1": "r"}), low) == "comparative"  # a parsed exchange too
    old = _row("old", "əuld", translation="a. 老的, 旧的", pos="j:100")
    assert dance.er_evidence(_row("older", "'əuldə", translation="a. 年长的; old的比较级", pos="j:100"), old) == "translation"  # the stem named in the gloss
    # seed records carry list-valued columns, an American tail and the optional-r notation
    assert dance.er_evidence({"lemma": "reviewer", "phonetic": "rɪˈvjuːə(r)", "translation": ["n. 评论者"], "definition": ["someone who reviews books"], "pos": "n:100"}, {"lemma": "review", "phonetic": "rɪˈvjuː", "translation": ["n. 评论"], "pos": "n:60/v:40"}) == "definition"
    assert dance.er_evidence(_row("banker", "'bæŋkɚ", definition="a person who owns a bank", pos="n:100"), _row("bank", "bæŋk", pos="n:96/v:4")) == "definition"


def test_er_evidence_rejects_false_friends():
    # not derived: no definition mention, no shared two-character word, no comparative link
    assert dance.er_evidence(_row("corner", "'kɔːnə", translation="n. 角落, 转角", definition="a place off to the side of an area", pos="v:3/n:97"), _row("corn", "kɔːn", translation="n. 玉蜀黍, 谷类", pos="n:100")) is None
    assert dance.er_evidence(_row("butter", "'bʌtə", translation="n. 奶油, 黄油", definition="an edible emulsion of fat globules", pos="v:3/n:97"), _row("butt", "bʌt", translation="n. 粗大的一头, 烟头", pos="v:17/n:83")) is None
    # the stem is not a content word (no pos at all; a preposition)
    assert dance.er_evidence(_row("center", "'sentə", translation="n. 中心", definition="an area that is approximately central", pos="n:93"), _row("cent", "sent", translation="n. 分", pos=None)) is None
    assert dance.er_evidence(_row("wither", "'wiðə", translation="vi. 枯萎", definition="lose freshness, vigor, or vitality, as with age", pos="v:100"), _row("with", "wið", translation="prep. 和...在一起", pos="i:100")) is None
    # the transcriptions do not compose
    assert dance.er_evidence(_row("number", "'nʌmbə", translation="n. 数字, 号码", definition="the property possessed by a sum", pos="n:97"), _row("numb", "nʌm", translation="a. 麻木的", pos="j:100")) is None
    assert dance.er_evidence(_row("longer", "'lɒŋgə", translation="a. 更长的; long的比较级", pos="j:100"), _row("long", "lɒŋ", translation="a. 长的", pos="j:80/v:20")) is None
    # the parts of speech disagree: a determiner / an adjective from a verb or noun stem
    assert dance.er_evidence(_row("former", "'fɔːmə", translation="a. 从前的, 前者的 n. 起形成作用的人", definition="the first of two", pos="d:99/n:1"), _row("form", "fɔːm", translation="n. 形状 v. 形成", pos="v:37/n:63")) is None
    assert dance.er_evidence(_row("tender", "'tendə", translation="a. 嫩的, 温柔的 n. 照料人", pos="j:91/v:4/n:5"), _row("tend", "tend", translation="vi. 走向, 照料", pos="v:100")) is None
    assert dance.er_evidence(_row("inner", "'inə", translation="a. 内部的", definition="located inward", pos="j:100"), _row("inn", "in", translation="n. 旅馆, 客栈", pos="n:100")) is None
    # a proper noun (capital letter), a stem that is not display[:-2], too short, a generic shared word only
    assert dance.er_evidence(_row("Easter", "'iːstə", translation="n. 复活节", pos="n:100"), _row("East", "iːst", translation="n. 东方", pos="n:100")) is None
    assert dance.er_evidence(_row("worker", "'wɜːkə", definition="a person who works", pos="n:100"), _row("walk", "wɔːk", pos="v:100")) is None
    assert dance.er_evidence(_row("her", "hɜː", pos="r:100"), _row("h", "", pos="n:100")) is None
    assert dance.er_evidence(_row("porter", "'pɔːtə", translation="n. 门房, 搬运工人", definition="a person employed to carry luggage", pos="n:100"), _row("port", "pɔːt", translation="n. 港口, 舱门", pos="v:1/n:99")) is None
    assert dance.er_evidence(_row("tester", "'testə", translation="n. 做事的人", pos="n:100"), _row("test", "test", translation="v. 做事", pos="v:100")) is None  # 做事 alone proves nothing


def _insert(conn, display, phonetic, **cols):
    cols.setdefault("is_valid_english", 1)  # what the seed import sets; the stem lookup only trusts validated public words
    keys = ["lemma", "display", "source", "phonetic", *cols]
    conn.execute(f"INSERT INTO words({', '.join(keys)}) VALUES ({', '.join('?' * len(keys))})", [display.lower(), display, "seed", phonetic, *cols.values()])
    return dict(conn.execute("SELECT * FROM words WHERE lemma = ?", (display.lower(),)).fetchone())


def test_er_stem_and_rule_spec_look_the_stem_up_in_the_bank(seeded):
    conn = seeded
    with db.tx(conn):
        work = _insert(conn, "work", "wɜːk", translation="n. 工作, 劳动", pos="n:38/v:62")
        worker = _insert(conn, "worker", "'wɜːkə", translation="n. 工人", definition="n. a person who works", pos="n:100")
        corner = _insert(conn, "corner", "'kɔːnə", translation="n. 角落", definition="a place off to the side", pos="n:97")
        _insert(conn, "corn", "kɔːn", translation="n. 玉蜀黍", pos="n:100")
        painter = _insert(conn, "painter", "'peintə", translation="n. 画家", definition="an artist who paints", pos="n:100")
        _insert(conn, "paint", "peint", translation="n. 油漆 vt. 画", pos="n:35/v:65", is_public=0)  # a private stem does not count
        hunter = _insert(conn, "hunter", "'hʌntə", translation="n. 猎人", definition="someone who hunts game", pos="n:100")
        _insert(conn, "hunt", "hʌnt", translation="vt. 狩猎", pos="v:63/n:37", merged_into_word_id=int(work["id"]))  # nor a merged one
    assert dance.er_stem(conn, worker) == ("work", "wɜːk")
    assert dance.rule_spec(conn, worker)["letters"] == ["work", "er"] and dance.spec_for_word(conn, worker)["letters"] == ["work", "er"]
    assert dance.er_stem(conn, corner) is None and dance.rule_spec(conn, corner)["letters"] == ["cor", "ner"]
    assert dance.er_stem(conn, painter) is None and dance.er_stem(conn, hunter) is None
    assert dance.er_stem(conn, work) is None  # not an -er word
    assert dance.er_stem(conn, {"display": "teacher", "lemma": "teacher", "phonetic": "'tiːtʃə"}) is None  # the mini seed has no `teach`
    # a word row without its own dictionary columns still gets the cut when the evidence is in the definition it does carry
    assert dance.rule_spec(conn, {"display": "worker", "lemma": "worker", "phonetic": "'wɜːkə", "definition": "one who works"})["letters"] == ["work", "er"]
    assert dance.rule_spec(conn, {"display": "worker", "lemma": "worker", "phonetic": "'wɜːkə"})["letters"] == ["wor", "ker"]  # … and the ordinary cut without any


def _seed_records():
    with gzip.open(FULL_SEED, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def test_er_splits_over_the_full_seed_match_the_golden_fixture():
    """Every seed word the -er rule applies to, with its cut: the fixture is regenerated on purpose (docs/WORD_DANCE_DESIGN.md §13),
    never by accident — a change here is a change of the rules or of the dictionary data and must be reviewed."""
    if not FULL_SEED.is_file():
        pytest.skip("data/seed/vocab.jsonl.gz not present")
    expected = json.loads(ER_SPLITS.read_text(encoding="utf-8"))
    by: dict[str, dict] = {}
    for row in _seed_records():
        by.setdefault(row.get("display") or row["lemma"], row)
    actual: dict[str, dict] = {}
    for key, row in by.items():
        if len(key) < 4 or not key.endswith("er") or (stem := by.get(key[:-2])) is None:
            continue
        evidence = dance.er_evidence(row, stem)
        if evidence is None:
            continue
        spec = dance.spec_for(key, row.get("phonetic"), er_stem=(key[:-2], stem.get("phonetic")))
        stem_spec = dance.spec_for(key[:-2], stem.get("phonetic"))
        actual[key] = {"chunks": "·".join(spec["letters"]), "stress": spec["stress"], "evidence": evidence, "applied": spec["letters"][-1] == "er" and spec["letters"][:-1] == stem_spec["letters"]}
    assert actual == expected
    assert all(v["applied"] for v in actual.values()) and len(actual) == 65
    for word in ("worker", "farmer", "teacher", "sweater", "player", "leader", "speaker", "listener"):
        assert word in actual, word
    for word in ("corner", "center", "butter", "former", "tender", "quarter", "master", "mister", "offer", "porter", "number", "wither", "inner", "customer", "charter", "ponder", "proper"):
        assert word not in actual, word
