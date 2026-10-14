"""services/words.normalise_input — the DESIGN §5.1 table (WP1). The client-side preview (utils/normalizeInput.ts) mirrors it."""

from __future__ import annotations

import dataclasses

import pytest

from wd.services import words
from wd.services.words import Invalid, Normalised, derive_kind, lemma_note_zh, normalise_input, normalise_lemma, translation_short

# (input, lemma, display, kind)
VALID: list[tuple[str, str, str, str]] = [
    ("abandon", "abandon", "abandon", "word"),
    (" Abandoned ", "abandoned", "Abandoned", "proper_noun"),  # capitalised token keeps its casing (proper-noun hint)
    ("ABANDON", "abandon", "abandon", "word"),  # 7 upper-case letters: not an acronym → lower-cased
    ("\tabandon\n", "abandon", "abandon", "word"),
    ("a.m.", "a.m.", "a.m.", "abbreviation"),
    ("e.g.", "e.g.", "e.g.", "abbreviation"),
    ("etc.", "etc.", "etc.", "abbreviation"),
    ("e.g", "e.g", "e.g", "abbreviation"),
    ("U.S.A.", "u.s.a.", "U.S.A.", "abbreviation"),
    ("P.M.", "p.m.", "P.M.", "abbreviation"),
    ("Mr.", "mr.", "Mr.", "abbreviation"),
    ("Ph.D.", "ph.d.", "ph.d.", "abbreviation"),
    ("ab.cd.", "ab.cd.", "ab.cd.", "abbreviation"),
    ("ice cream", "ice cream", "ice cream", "phrase"),
    ("ought to", "ought to", "ought to", "phrase"),
    ("take off", "take off", "take off", "phrase"),
    ("look forward to", "look forward to", "look forward to", "phrase"),
    ("the pacific ocean", "the pacific ocean", "the pacific ocean", "phrase"),
    ("by and large", "by and large", "by and large", "phrase"),
    ("ice   cream", "ice cream", "ice cream", "phrase"),
    ("ice\tcream", "ice cream", "ice cream", "phrase"),
    ("New York", "new york", "New York", "phrase"),
    ("Middle East", "middle east", "Middle East", "phrase"),
    ("abandon　ship", "abandon ship", "abandon ship", "phrase"),  # ideographic space → NFKC → space
    ("CPU", "cpu", "CPU", "abbreviation"),
    ("GDP", "gdp", "GDP", "abbreviation"),
    ("NASA", "nasa", "NASA", "abbreviation"),
    ("OK", "ok", "OK", "abbreviation"),
    ("ok", "ok", "ok", "word"),
    ("TV", "tv", "TV", "abbreviation"),
    ("Kubernetes", "kubernetes", "Kubernetes", "proper_noun"),
    ("China", "china", "China", "proper_noun"),
    ("I", "i", "I", "proper_noun"),
    ("iPhone", "iphone", "iphone", "word"),
    ("don’t", "don't", "don't", "word"),  # curly apostrophe
    ("don‘t", "don't", "don't", "word"),
    ("rock ’n’ roll", "rock 'n' roll", "rock 'n' roll", "phrase"),
    ("“abandon”", "abandon", "abandon", "word"),  # curly double quotes are surrounding punctuation
    ("teachers'", "teachers'", "teachers'", "word"),
    ("O'Neill", "o'neill", "o'neill", "word"),
    ("well-known", "well-known", "well-known", "word"),
    ("well—known", "well-known", "well-known", "word"),  # em dash
    ("well–known", "well-known", "well-known", "word"),  # en dash
    ("mother-in-law", "mother-in-law", "mother-in-law", "word"),
    ("e-mail", "e-mail", "e-mail", "word"),
    ("CD-ROM", "cd-rom", "CD-ROM", "proper_noun"),
    ("ＡＢＣ", "abc", "ABC", "abbreviation"),  # full-width letters → NFKC
    ("ａｂａｎｄｏｎ", "abandon", "abandon", "word"),
    ("(abandon)", "abandon", "abandon", "word"),
    ("[abandon]", "abandon", "abandon", "word"),
    ("{abandon}", "abandon", "abandon", "word"),
    ("<abandon>", "abandon", "abandon", "word"),
    ('"abandon"', "abandon", "abandon", "word"),
    ("abandon,", "abandon", "abandon", "word"),
    ("abandon;", "abandon", "abandon", "word"),
    ("abandon:", "abandon", "abandon", "word"),
    ("abandon?!", "abandon", "abandon", "word"),
    ("abandon！", "abandon", "abandon", "word"),  # full-width exclamation → NFKC → '!'
    ("，abandon，", "abandon", "abandon", "word"),  # full-width commas
    ("a", "a", "a", "word"),
    ("x" * 48, "x" * 48, "x" * 48, "word"),  # exactly 48 chars is allowed
]

# (input, reason)
INVALID: list[tuple[str | None, str]] = [
    ("", words.REASON_EMPTY),
    ("   ", words.REASON_EMPTY),
    (",;:", words.REASON_EMPTY),
    ('()[]{}"', words.REASON_EMPTY),
    (None, words.REASON_EMPTY),
    ("放弃", words.REASON_NOT_ENGLISH),
    ("放弃 abandon", words.REASON_NOT_ENGLISH),
    ("abandon 放弃", words.REASON_NOT_ENGLISH),
    ("日本語", words.REASON_NOT_ENGLISH),
    ("한국어", words.REASON_NOT_ENGLISH),
    ("ひらがな", words.REASON_NOT_ENGLISH),
    ("abc123", words.REASON_CHARSET),
    ("123", words.REASON_CHARSET),
    ("abandon@home", words.REASON_CHARSET),
    ("a_b", words.REASON_CHARSET),
    ("café", words.REASON_CHARSET),
    ("abandon&ship", words.REASON_CHARSET),
    ("abandon/ship", words.REASON_CHARSET),
    ("abandon\\ship", words.REASON_CHARSET),
    ("x" * 49, words.REASON_TOO_LONG),
    ("abandon " * 12, words.REASON_TOO_LONG),  # length is checked before the token count
    ("this is a five token", words.REASON_TOO_MANY_TOKENS),
    ("I love you very much", words.REASON_TOO_MANY_TOKENS),
    ("a b c d e", words.REASON_TOO_MANY_TOKENS),
    ("it's a long phrase here", words.REASON_TOO_MANY_TOKENS),
    ("example.com", words.REASON_DOT),
    ("www.example.com", words.REASON_DOT),
    ("abandon.txt", words.REASON_DOT),
    ("ab.cdefg", words.REASON_DOT),
    ("abandon.", words.REASON_DOT),  # a trailing dot stays on the token ('.' is never stripped) and the token is > 6 chars
    ("-abc", words.REASON_LEADING),
    ("--abandon", words.REASON_LEADING),
    ("'abc", words.REASON_LEADING),
    ("'tis", words.REASON_LEADING),
    ("’abc", words.REASON_LEADING),  # curly apostrophe maps to ' first
    ("ice - cream", words.REASON_PUNCT_TOKEN),
    ("ice . cream", words.REASON_PUNCT_TOKEN),
    ("...", words.REASON_PUNCT_TOKEN),
    ("'", words.REASON_PUNCT_TOKEN),
    ("-", words.REASON_PUNCT_TOKEN),
    ("—", words.REASON_PUNCT_TOKEN),
    ("ice '-' cream", words.REASON_PUNCT_TOKEN),
]


def test_table_has_at_least_60_cases():
    assert len(VALID) + len(INVALID) >= 60


@pytest.mark.parametrize("text,lemma,display,kind", VALID, ids=[repr(c[0]) for c in VALID])
def test_valid_inputs(text, lemma, display, kind):
    n = normalise_input(text)
    assert isinstance(n, Normalised), getattr(n, "reason_zh", None)
    assert n.ok is True
    assert (n.lemma, n.display, n.kind) == (lemma, display, kind)
    assert n.tokens == tuple(lemma.split(" "))
    assert 1 <= len(n.tokens) <= words.MAX_TOKENS
    assert len(n.lemma) <= words.MAX_CHARS
    assert n.lemma == n.display.lower()
    assert n.kind in words.KINDS


@pytest.mark.parametrize("text,reason", INVALID, ids=[repr(c[0]) for c in INVALID])
def test_invalid_inputs(text, reason):
    n = normalise_input(text)  # type: ignore[arg-type]
    assert isinstance(n, Invalid)
    assert n.ok is False
    assert n.reason_zh == reason


def test_results_are_immutable_values():
    n = normalise_input("abandon")
    assert isinstance(n, Normalised)
    with pytest.raises(dataclasses.FrozenInstanceError):
        n.lemma = "x"  # type: ignore[misc]
    assert normalise_input("abandon") == n  # value semantics
    bad = normalise_input("放弃")
    with pytest.raises(dataclasses.FrozenInstanceError):
        bad.reason_zh = "y"  # type: ignore[misc]


def test_reasons_are_chinese_and_the_charset_reason_matches_the_api_catalogue():
    from wd.errors import CATALOGUE

    assert words.REASON_CHARSET == CATALOGUE["invalid_word"][1]
    for reason in (words.REASON_EMPTY, words.REASON_NOT_ENGLISH, words.REASON_TOO_LONG, words.REASON_TOO_MANY_TOKENS, words.REASON_PUNCT_TOKEN, words.REASON_DOT, words.REASON_LEADING):
        assert any("一" <= ch <= "鿿" for ch in reason), reason


@pytest.mark.parametrize(
    "text,expected",
    [
        ("  Running ", "running"),
        ("Olympic  Gamess", "olympic gamess"),
        ("ice creams", "ice creams"),
        ("don’t", "don't"),
        ("a.m.", "a.m."),
        ("", None),
        ("   ", None),
        (None, None),
        (",,", None),
        ("ＡＢＣ", "abc"),
    ],
)
def test_normalise_lemma_is_lenient(text, expected):
    assert normalise_lemma(text) == expected


@pytest.mark.parametrize(
    "display,kind",
    [
        ("abandon", "word"),
        ("China", "proper_noun"),
        ("a.m.", "abbreviation"),
        ("TV", "abbreviation"),
        ("AIDS", "abbreviation"),
        ("ice cream", "phrase"),
        ("Middle East", "phrase"),
        ("CD-ROM", "proper_noun"),
        ("ABCDEFG", "proper_noun"),  # 7 letters is no acronym by the ^[A-Z]{2,6}$ rule
        ("I", "proper_noun"),
        ("Mr.", "abbreviation"),
        ("e-mail", "word"),
    ],
)
def test_derive_kind_follows_the_seed_rule(display, kind):
    assert derive_kind(display) == kind


def test_lemma_note_and_translation_short():
    assert lemma_note_zh("go", "p") == "已归为原形 go（过去式）"
    assert lemma_note_zh("child", "s") == "已归为原形 child（复数）"
    assert lemma_note_zh("abandon", "alt") == "已归为原形 abandon（变体）"
    assert lemma_note_zh("abandon", "??") == "已归为原形 abandon（变体）"
    assert translation_short("v. 放弃\nn. 放纵") == "v. 放弃"
    assert translation_short("\n\n  第二行  ") == "第二行"
    assert translation_short(None) == "" and translation_short("") == ""
    long = "放" * 80
    short = translation_short(long)
    assert len(short) == 60 and short.endswith("…")
    assert translation_short("x" * 60) == "x" * 60
