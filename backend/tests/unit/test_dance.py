"""wd.dance — the rule-based 「单词之舞」 DanceSpec (docs/WORD_DANCE_DESIGN.md §4.1–4.2, §10; API.md §9 ``DanceSpec``).

A golden table pins the chunking, stress and letter marks of words that exercise every rule (ECDICT and IPA notations, the old
double-stress marks, syllabic consonants, triphthongs, magic e, hiatus, iə / uə read as two syllables, /ʃ/ spellings, -le /
-tion / -ing / -ieth endings, r-coloured vowels, secondary stress, the elided-schwa and -teen rules, the two phonetic
overrides), then two sweeps check the invariants over the mini seed and over the full shipped seed: the chunks always spell the
display form, the stress index is in range, marks point at real letters, and the function never raises."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from wd import dance, schemas

REPO = Path(__file__).resolve().parents[3]
FULL_SEED = REPO / "data" / "seed" / "vocab.jsonl.gz"

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
