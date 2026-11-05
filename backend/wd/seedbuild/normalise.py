"""seedbuild.normalise — the twelve normalisation rules R1–R12 of the official word lists as pure functions.

Specification: ``docs/analysis/2026-11-05-stages-regions-images/design/PLAN.md`` §4.3 (rule table, binding) and
``design/word-lists/SYNTHESIS.md`` §3.3 (worked examples from the delivered files). Every example in this file and in
``tests/unit/test_seedbuild_normalise.py`` is a real line of ``data/lists/*``.

Why a separate pure module: the grammar of the delivered files (``colour (AmE color)``, ``a/an``, ``manner(s)``,
``be (am, is, are)``, ``a bit (of)``) is the only part of the seed build that needs judgement, so it lives here, free of
I/O, and is pinned by table-driven tests; ``build.py`` (PLAN §4.5) only wires files, the manifest and ECDICT around it.
ECDICT is reached exclusively through the :class:`Lexicon` protocol passed in by the caller — nothing here opens a
database, so the tests run on a dictionary of real rows and the real build passes ``build.Ecdict``.

Contract for ``build.py`` (inputs → outputs; every function is deterministic and side-effect free)
=================================================================================================

Text folding and lemmas
-----------------------
``fold(text) -> str``                              R1. NFKC → curly quotes / dashes / full-width ``（）＝／，`` → ASCII
                                                    (``words._CHAR_MAP`` plus the full-width additions) → NFD and the
                                                    combining marks removed (``café`` → ``cafe``) → whitespace collapsed
                                                    and stripped. Case is kept (``A.M.`` stays ``A.M.``).
``lemma_of(text) -> str | None``                   ``words.normalise_lemma(fold(text))`` — THE lemma of the seed records
                                                    and of the importer (``seed.seed_row``); None when nothing is left.
``canon(text, aliases) -> str | None``             R5/R6. ``lemma_of`` followed by the ``aliases.tsv`` rewrite
                                                    (``Mr`` → ``mr.``, ``hot-dog`` → ``hot dog``). Only for official heads,
                                                    variants and phrases — never for previous-seed lemmas (use
                                                    ``lemma_of`` for those; PLAN R5).
``load_aliases(text) -> dict[str, str]``           Parses ``aliases.tsv`` (``spelling<TAB>canonical[<TAB>note]``, ``#``
                                                    comments) into ``{lemma_of(spelling): lemma_of(canonical)}``; refuses
                                                    chains and self-maps (ValueError).
``has_cjk(text) -> bool``                          CJK / full-width character present (``words._CJK_RE``).

R12 strict gate
---------------
``strict_ok(lemma) -> bool`` / ``strict_reason(lemma) -> str | None``
                                                    ``words.normalise_input`` verdict (charset ``^[A-Za-z' .\\-]+$``, ≤ 48
                                                    chars, ≤ 4 tokens, no punctuation-only token, dotted token ≤ 6, no
                                                    leading ``-``/``'``). The zh reason is for the build log.

Head lines (R2–R7, R10, R12)
----------------------------
``split_head(raw, *, lexicon=None, aliases=None, previous=frozenset(), drop=frozenset()) -> ParsedHead``
    One line of a ``heads`` list or the word column of a TSV. ``raw`` is the printed text; ``lexicon`` the ECDICT view;
    ``aliases`` the ``load_aliases`` mapping; ``previous`` the set of previous-seed lemmas (``lemma_of`` of every record's
    ``word``); ``drop`` the lemmas with an ``overrides.tsv`` ``drop`` row. Returns:
      ``heads``       member lemmas produced by the head part (R3 ``/``, ``=`` parallels; R4 attached ``(s)``/``(es)``;
                      R5 aliases; R6 lower-case) plus R2 collocation phrases (``according to``) plus the bracket
                      variants of a head that produced no member (next item);
      ``variants``    ``(variant_lemma, head_lemma)`` pairs from the bracket note (R2/R11) — same stages as the head,
                      recorded as ``variant_of`` in the seed. ``head_lemma`` is always one of ``heads``: a head that
                      failed R12 or sits in ``drop`` has no member for ``variant_of`` to name (seed record v2, PLAN
                      §4.5), so its variants are promoted to plain heads — ``The United States of America (USA)`` →
                      ``heads=("usa",)``, ``variants=()``, the head itself still listed in ``rejected``;
      ``aliases``     ``(alias_form, lemma)`` pairs — the official spelling when it differs from the lemma (``mr`` →
                      ``mr.``); the importer writes them as ``word_forms(kind='alias')``;
      ``collocations`` the subset of ``heads`` that came from a function-word note (stats only);
      ``dropped``     texts that produce no member: inflection / plural / CJK notes, the bare head of a collocation note
                      that is not a previous-seed lemma (``according``), lemmas in ``drop``;
      ``rejected``    :class:`Rejected` entries that failed R12 (``role`` head | variant) — a ``main`` list head here is a
                      build failure, an appendix head or a variant is a warning;
      ``unparsed``    note items nothing matched (``BCE (Before the Common Era)``) → ``stats.unparsed_notes``;
      ``printed``     ``lemma → folded printed spelling`` for the display fallback of brand-new rows.
    ``ParsedHead.members`` = heads + variant lemmas (deduplicated, in order).
``classify_note(head, note, *, lexicon=None, aliases=None, previous=frozenset(), other_heads=()) -> list[NoteItem]``
    R2 on its own: the items of ONE bracket note classified as alias / inflection / plural / cjk / collocation /
    variant / unknown (see :class:`NoteItem`).
``note_items(note) -> list[str]``                  R2 ②: split on ``,`` / `` AmE `` / ``美 `` / ``或``, strip a leading
                                                    ``=`` / ``AmE`` / ``美``; when any item has more than two tokens the
                                                    whole note is one item (``UNESCO (United Nations Educational, …)``).
``head_text(raw) -> str`` / ``is_single_token(raw) -> bool``
                                                    The head part without its trailing note; ``single_token`` groups of the
                                                    appendices accept only heads without a space (``one hundred (and) one``
                                                    is skipped, ``twenty-one`` kept).
``ecdict_candidates(head) -> tuple[str, ...]``    R10: the spellings to try in ECDICT, in order — the folded head, then
                                                    hyphens as spaces, then spaces as hyphens. Never the words glued
                                                    together (``break down`` must not match ``breakdown``).
``lookup(lexicon, text) -> LexiconEntry | None``  ``lexicon.get`` over ``ecdict_candidates``; None for a None lexicon.

Phrase lines (R9, R12)
----------------------
``phrase_candidates(raw) -> set[str]``             Grammar only: ``…``/``...`` → `` ... ``; optional brackets expanded
                                                    with/without (attached ``movie(s)`` glues, spaced ``(of)`` inserts;
                                                    ``(in/on/at)`` lists alternatives); then ``/`` alternation per token
                                                    (``at first/last`` → ``at first``, ``at last``; cross-token parallels
                                                    such as ``a lot of/lots of`` are NOT recovered — PLAN R9).
``resolve_phrase(raw, *, lexicon=None, aliases=None, previous=frozenset()) -> PhraseResult``
                                                    Members = candidates that contain a space, are known (lexicon or
                                                    previous) and pass R12; ``skipped`` = ``'patterns'`` (``sb.`` /
                                                    ``sth.`` / ``one's`` / ``oneself`` / ``...`` in the raw text) or
                                                    ``'other'`` when nothing survived.
``is_template(raw) -> bool``                       The ``patterns`` test above.

Aggregation (R6, R8)
--------------------
``merge_heads(members) -> dict[str, Member]``      R6: same-lemma records merged in first-seen order — stages, tokens,
                                                    aliases and list ids unioned; ``variant_of`` cleared as soon as one
                                                    source lists the lemma as a head; ``printed`` = first non-empty.
``inherit_forms(inherit_stages, previous, official) -> dict[str, str]``
                                                    R8: ``{form_lemma: base_lemma}`` for the forms of
                                                    ``manifest.inherit_stages`` that already are previous-seed lemmas and
                                                    are not official members. ``official`` is EVERY official member
                                                    lemma — heads and bracket variants alike (PLAN §4.2 INH:
                                                    ``f ∉ L2∪L3∪SH∪HS``), so the build passes the union of all
                                                    ``ParsedHead.members``; it then gives each form the stages of its
                                                    base and the token ``inherit:<base>`` and never creates a row.

Where the rules are NOT applied (build.py's job): the stages / tokens of a member, appendix group policies and the
``member: false`` groups, ``overrides.tsv`` apart from ``drop``, the ``[网络] `` prefix, and the existence check of
``policy: main`` heads (``lexicon ∪ previous``).
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from dataclasses import dataclass, field
from typing import AbstractSet, Iterable, Mapping, Protocol, runtime_checkable

from ..services import words
from ..services.ecdict import FORM_CODES

# -------------------------------------------------------------------------------------------- constants
#: R2 ③ — a single bracket item in this set is a collocation note (``according (to)``), not a variant.
FUNCTION_NOTES: frozenset[str] = frozenset({"to", "for", "with", "on", "at", "in", "of", "up", "out"})
#: R2 ③ — heads whose bracket items are person forms without ECDICT pointers (``be (am, is, are)``, ``have (has)``).
INFLECTION_HEADS: frozenset[str] = frozenset({"be", "have", "do"})
#: R4 — the only optional suffixes (``manner(s)``, ``toward(s)``, ``Math(s)``); anything else is a note.
OPTIONAL_SUFFIXES: tuple[str, ...] = ("s", "es")

NoteKind = str  # 'alias' | 'inflection' | 'plural' | 'cjk' | 'collocation' | 'variant' | 'unknown'

# full-width brackets / equals / slash / comma and the ellipsis on top of words._CHAR_MAP (NFKC already maps most of
# them; listed explicitly because PLAN R1 names them and the lists were typed from Chinese PDFs)
_FOLD_MAP: dict[int, str] = {
    **dict(words._CHAR_MAP),
    **str.maketrans({"（": "(", "）": ")", "＝": "=", "／": "/", "，": ",", "…": "..."}),
}
_WS_RE = re.compile(r"\s+")
_SUFFIX_RE = re.compile(r"^(.*\S)\((s|es)\)$")  # attached: no whitespace before "("
_NOTE_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)$")  # the LAST bracket group, at the end of the line
_TRAILING_NOTE_RE = re.compile(r"\s*\([^()]*\)\s*$")
_HEAD_SPLIT_RE = re.compile(r"[/=]")
_NOTE_SPLIT_RE = re.compile(r",|\sAmE\s|美\s|或")
_NOTE_LEAD_RE = re.compile(r"^(=|AmE\s+|美\s*)")
_PLURAL_NOTE_RE = re.compile(r"^(pl\.|复)")
_PAREN_RE = re.compile(r"(\s?)\(([^()]*)\)")
_ELLIPSIS_RE = re.compile(r"\s*\.\.\.\s*")
_TEMPLATE_RE = re.compile(r"\b(sb|sth)\.|\bone's\b|\boneself\b|\.\.\.")
_FORM_CODES: frozenset[str] = frozenset(FORM_CODES)


# -------------------------------------------------------------------------------------------- protocols
@runtime_checkable
class LexiconEntry(Protocol):
    """What the rules need from an ECDICT row: the stored spelling and the parsed ``exchange`` map."""

    @property
    def word(self) -> str: ...

    @property
    def exchange(self) -> Mapping[str, str]: ...


class Lexicon(Protocol):
    """``build.Ecdict`` and the test fakes: ``get(word)`` is one ``word = ? COLLATE NOCASE`` lookup (None = no row)."""

    def get(self, word: str) -> LexiconEntry | None: ...


# -------------------------------------------------------------------------------------------- data classes
@dataclass(frozen=True)
class NoteItem:
    """One item of a bracket note after R2: ``text`` as printed (folded), ``lemma`` its canon lemma, ``kind`` the verdict.
    ``phrase`` is the member lemma of a collocation (``according to``); ``form`` the alias spelling of an ``alias`` item
    when it differs from the lemma."""

    text: str
    lemma: str | None
    kind: NoteKind
    phrase: str | None = None
    form: str | None = None


@dataclass(frozen=True)
class Rejected:
    """An R12 failure: ``role`` is ``head`` / ``variant`` / ``phrase``; ``reason`` the zh message of ``normalise_input``."""

    text: str
    lemma: str
    role: str
    reason: str


@dataclass(frozen=True)
class ParsedHead:
    """Result of :func:`split_head` (fields documented in the module docstring)."""

    raw: str
    heads: tuple[str, ...] = ()
    variants: tuple[tuple[str, str], ...] = ()
    aliases: tuple[tuple[str, str], ...] = ()
    collocations: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()
    rejected: tuple[Rejected, ...] = ()
    unparsed: tuple[str, ...] = ()
    printed: Mapping[str, str] = field(default_factory=dict)

    @property
    def members(self) -> tuple[str, ...]:
        """Every lemma this line makes a member of its list: heads first, then variants (deduplicated, in order)."""
        return _dedupe((*self.heads, *(v for v, _ in self.variants)))


@dataclass(frozen=True)
class PhraseResult:
    """Result of :func:`resolve_phrase`: ``members`` are canon lemmas (sorted); ``skipped`` is None when any survived."""

    raw: str
    candidates: tuple[str, ...]
    members: tuple[str, ...]
    rejected: tuple[Rejected, ...] = ()
    skipped: str | None = None


@dataclass(frozen=True)
class Member:
    """A membership record before/after :func:`merge_heads`: stages and tokens are sets of codes (``xs``…) and
    ``sources`` tokens (``moe22:l2``); ``variant_of`` is the head lemma for variant rows; ``aliases`` the alias forms;
    ``lists`` the manifest ids that mention the lemma."""

    lemma: str
    stages: frozenset[str] = frozenset()
    tokens: frozenset[str] = frozenset()
    printed: str = ""
    variant_of: str | None = None
    aliases: frozenset[str] = frozenset()
    lists: frozenset[str] = frozenset()


# -------------------------------------------------------------------------------------------- R1 folding
def fold(text: str | None) -> str:
    """R1: NFKC, typographic punctuation → ASCII, diacritics removed, whitespace collapsed; casing kept."""
    s = unicodedata.normalize("NFKC", text or "").translate(_FOLD_MAP)
    s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
    s = unicodedata.normalize("NFC", s)
    return _WS_RE.sub(" ", s).strip()


def lemma_of(text: str | None) -> str | None:
    """The seed/importer lemma of a printed form: ``words.normalise_lemma(fold(text))`` (lower-case, no outer punctuation)."""
    return words.normalise_lemma(fold(text)) if text is not None else None


def has_cjk(text: str) -> bool:
    """True when the text contains a CJK or full-width character (the ``hang (悬挂)`` disambiguation notes)."""
    return bool(words._CJK_RE.search(text or ""))


# -------------------------------------------------------------------------------------------- R5 aliases
def load_aliases(text: str) -> dict[str, str]:
    """Parse ``aliases.tsv`` into ``{lemma_of(spelling): lemma_of(canonical)}``.

    Lines starting with ``#`` and blank lines are ignored; a third column (note) is allowed. A canonical that is itself
    an alias spelling (a chain) or a spelling equal to its canonical is a file error — ``canon`` is one lookup, so chains
    would silently stop one step short.
    """
    out: dict[str, str] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.rstrip("\n").split("\t")
        if len(cols) < 2:
            raise ValueError(f"aliases.tsv line {lineno}: expected spelling<TAB>canonical, got {line!r}")
        spelling, canonical = lemma_of(cols[0]), lemma_of(cols[1])
        if not spelling or not canonical:
            raise ValueError(f"aliases.tsv line {lineno}: empty spelling or canonical in {line!r}")
        if spelling == canonical:
            raise ValueError(f"aliases.tsv line {lineno}: {spelling!r} maps to itself")
        if spelling in out:
            raise ValueError(f"aliases.tsv line {lineno}: duplicate spelling {spelling!r}")
        out[spelling] = canonical
    for spelling, canonical in out.items():
        if canonical in out:
            raise ValueError(f"aliases.tsv: chain {spelling!r} → {canonical!r} → {out[canonical]!r} is not allowed")
    return out


def canon(text: str | None, aliases: Mapping[str, str] | None = None) -> str | None:
    """R5 + R6: the canonical lemma of an official spelling — ``lemma_of`` then the alias rewrite.

    Never call this for previous-seed lemmas (``humourous`` keeps its own row; PLAN R5).
    """
    key = lemma_of(text)
    if key is None:
        return None
    return aliases.get(key, key) if aliases else key


# -------------------------------------------------------------------------------------------- R12 strict gate
def strict_reason(lemma: str | None) -> str | None:
    """None when ``words.normalise_input`` accepts the lemma, else its zh reason (for the build log)."""
    verdict = words.normalise_input(lemma or "")
    return None if verdict.ok else verdict.reason_zh  # type: ignore[union-attr]


def strict_ok(lemma: str | None) -> bool:
    """R12: the candidate passes every check of ``words.normalise_input`` (DESIGN §5.1 table)."""
    return strict_reason(lemma) is None


# -------------------------------------------------------------------------------------------- R10 ECDICT spellings
def ecdict_candidates(head: str) -> tuple[str, ...]:
    """R10: spellings to try in ECDICT, in order — as printed, hyphens → spaces, spaces → hyphens; never glued together."""
    h = fold(head)
    if not h:
        return ()
    out = [h]
    if "-" in h:
        out.append(h.replace("-", " "))
    if " " in h:
        out.append(h.replace(" ", "-"))
    return _dedupe(tuple(_WS_RE.sub(" ", c).strip() for c in out))


def lookup(lexicon: Lexicon | None, text: str) -> LexiconEntry | None:
    """``lexicon.get`` over :func:`ecdict_candidates`; None when there is no lexicon or no candidate has a row."""
    if lexicon is None:
        return None
    for cand in ecdict_candidates(text):
        entry = lexicon.get(cand)
        if entry is not None:
            return entry
    return None


# -------------------------------------------------------------------------------------------- R2 bracket notes
def note_items(note: str) -> list[str]:
    """R2 ②: the items of a bracket note (``=mathematics, AmE math`` → ``mathematics``, ``math``); a note with an item of
    more than two tokens is ONE item (``United Nations Educational, Scientific and Cultural Organization``)."""
    n = fold(note)
    if not n:
        return []
    items = [i.strip() for i in _NOTE_SPLIT_RE.split(n) if i.strip()]
    items = [_NOTE_LEAD_RE.sub("", i).strip() for i in items]
    items = [i for i in items if i]
    if any(len(i.split(" ")) > 2 for i in items):
        whole = _NOTE_LEAD_RE.sub("", n).strip()
        return [whole] if whole else []
    return items


def _form_values(entry: LexiconEntry | None) -> set[str]:
    """Lower-cased inflections listed in an ECDICT row's exchange (codes p d i 3 s r t)."""
    if entry is None:
        return set()
    return {v.lower() for k, v in entry.exchange.items() if k in _FORM_CODES and v}


def _points_to(entry: LexiconEntry | None, head_lemma: str) -> bool:
    """True when the item's ECDICT row says ``0:<head>`` AND carries a ``1:`` form code — a real inflection (``is``
    ``0:be/1:3``, ``children`` ``0:child/1:s``). A bare ``0:`` pointer without a form code marks a related alternate
    (``an`` ``0:a/s:some``), which R2 treats as a variant, so PLAN's ``a (an)`` example yields the variant ``an``."""
    if entry is None:
        return False
    pointer = lemma_of(entry.exchange.get("0", ""))
    codes = entry.exchange.get("1", "") or ""
    return pointer == head_lemma and any(c in _FORM_CODES for c in codes)


def classify_note(
    head: str,
    note: str,
    *,
    lexicon: Lexicon | None = None,
    aliases: Mapping[str, str] | None = None,
    previous: AbstractSet[str] = frozenset(),
    other_heads: Iterable[str] = (),
) -> list[NoteItem]:
    """R2: classify the items of the bracket note of ``head`` (the printed first head of the line).

    Order per item (PLAN §4.3 R2): same lemma as a head → ``alias``; person form of be/have/do, an inflection listed in
    the head's ECDICT exchange, or a row pointing back at the head with a form code → ``inflection``; a single function
    word whose ``head item`` phrase is known → ``collocation``; otherwise known (lexicon or previous) → ``variant``;
    else ``unknown``. ``pl.``/``复`` notes and CJK notes are dropped whole (``plural`` / ``cjk``).
    """
    n = fold(note)
    if not n:
        return []
    if _PLURAL_NOTE_RE.match(n):
        return [NoteItem(n, None, "plural")]
    items = note_items(n)
    # the CJK test runs on the items: ``美``/``或`` are separators of the printed notes (forms.tsv), a CJK item is a
    # Chinese disambiguation gloss (``hang (悬挂)``) and drops the whole note
    if any(has_cjk(i) for i in items):
        return [NoteItem(n, None, "cjk")]
    head_f = fold(head)
    head_lemma = canon(head_f, aliases)
    head_lemmas = {head_lemma, *(canon(h, aliases) for h in other_heads)} - {None}
    head_forms = _form_values(lookup(lexicon, head_f))
    out: list[NoteItem] = []
    for it in items:
        lem = canon(it, aliases)
        if lem is None:
            continue
        if lem in head_lemmas:
            form = lemma_of(it)
            out.append(NoteItem(it, lem, "alias", form=form if form != lem else None))
            continue
        if (head_lemma in INFLECTION_HEADS) or (lemma_of(it) in head_forms) or _points_to(lookup(lexicon, it), head_lemma or ""):
            out.append(NoteItem(it, lem, "inflection"))
            continue
        if len(items) == 1 and lem in FUNCTION_NOTES and head_f:
            phrase = f"{head_f} {it}"
            phrase_lemma = canon(phrase, aliases)
            if phrase_lemma and _known(phrase, phrase_lemma, lexicon, previous):
                out.append(NoteItem(it, lem, "collocation", phrase=phrase_lemma))
                continue
        if _known(it, lem, lexicon, previous):
            out.append(NoteItem(it, lem, "variant"))
        else:
            out.append(NoteItem(it, lem, "unknown"))
    return out


def _known(text: str, lemma: str, lexicon: Lexicon | None, previous: AbstractSet[str]) -> bool:
    """A spelling is known when ECDICT has a row for one of its R10 spellings or the lemma is a previous-seed lemma."""
    return lookup(lexicon, text) is not None or lemma in previous


# -------------------------------------------------------------------------------------------- R2–R6 head lines
def head_text(raw: str) -> str:
    """The head part of a line: the folded text without a trailing bracket note (``Math(s)`` → ``Math``)."""
    s = fold(raw)
    m = _SUFFIX_RE.match(s)
    if m:
        return m.group(1)
    return _TRAILING_NOTE_RE.sub("", s).strip()


def is_single_token(raw: str) -> bool:
    """``single_token`` appendix groups: the head part has no space (``twenty-one`` yes, ``one hundred (and) one`` no)."""
    h = head_text(raw)
    return bool(h) and " " not in h


def split_head(
    raw: str,
    *,
    lexicon: Lexicon | None = None,
    aliases: Mapping[str, str] | None = None,
    previous: AbstractSet[str] = frozenset(),
    drop: AbstractSet[str] = frozenset(),
) -> ParsedHead:
    """R2–R6 + R12 for one head line; see the module docstring for the result fields."""
    s = fold(raw)
    if not s:
        return ParsedHead(raw=raw)
    heads: list[str] = []
    variants: list[tuple[str, str]] = []
    alias_pairs: list[tuple[str, str]] = []
    collocations: list[str] = []
    dropped: list[str] = []
    rejected: list[Rejected] = []
    unparsed: list[str] = []
    printed: dict[str, str] = {}

    note: str | None = None
    m = _SUFFIX_RE.match(s)
    if m:  # R4: manner(s) → manner, manners
        base, suffix = m.group(1), m.group(2)
        parts = [base, base + suffix]
    else:
        m = _NOTE_RE.match(s)
        if m:
            text, note = m.group(1).strip(), m.group(2).strip()
        else:
            text = s
        parts = [p.strip() for p in _HEAD_SPLIT_RE.split(text) if p.strip()]  # R3: a/an, exam=examination

    def _admit(part: str, lemma: str, role: str, into: list, extra=None) -> bool:
        """Shared R12 / drop gate for heads and variants; records printed spelling and alias form."""
        if lemma in drop:
            dropped.append(part)
            return False
        reason = strict_reason(lemma)
        if reason is not None:
            rejected.append(Rejected(part, lemma, role, reason))
            return False
        into.append(extra if extra is not None else lemma)
        printed.setdefault(lemma, part)
        form = lemma_of(part)
        if form and form != lemma and (form, lemma) not in alias_pairs:
            alias_pairs.append((form, lemma))
        return True

    for part in parts:
        lemma = canon(part, aliases)
        if lemma is None:
            continue
        _admit(part, lemma, "head", heads)

    if note is not None and parts:
        head0 = parts[0]
        items = classify_note(head0, note, lexicon=lexicon, aliases=aliases, previous=previous, other_heads=parts[1:])
        head0_lemma = canon(head0, aliases)
        for item in items:
            if item.kind in ("plural", "cjk", "inflection"):
                dropped.append(item.text)
            elif item.kind == "alias":
                if item.form and item.lemma and (item.form, item.lemma) not in alias_pairs:
                    alias_pairs.append((item.form, item.lemma))
            elif item.kind == "collocation" and item.phrase:
                if _admit(f"{head0} {item.text}", item.phrase, "head", heads):
                    collocations.append(item.phrase)
                # the bare head is a member only when it already is a previous-seed lemma (``according`` is not)
                if head0_lemma in heads and head0_lemma not in previous:
                    heads.remove(head0_lemma)
                    printed.pop(head0_lemma, None)
                    dropped.append(head0)
            elif item.kind == "variant" and item.lemma:
                if item.lemma in heads or any(item.lemma == v for v, _ in variants):
                    continue
                if head0_lemma is not None:
                    _admit(item.text, item.lemma, "variant", variants, extra=(item.lemma, head0_lemma))
            else:
                unparsed.append(item.text)

    # seed record v2 (PLAN §4.5): ``variant_of`` names a member lemma. A head that failed R12 or sits in ``drop`` made no
    # member, so its bracket variants stand on their own — ``The United States of America (USA)`` yields the plain head
    # ``usa`` instead of a variant pointing at a lemma the seed will never contain (review S3a F2).
    promoted = [v for v, h in variants if h not in heads]
    if promoted:
        variants = [(v, h) for v, h in variants if h in heads]
        heads.extend(promoted)

    return ParsedHead(
        raw=raw,
        heads=_dedupe(tuple(heads)),
        variants=tuple(variants),
        aliases=tuple(alias_pairs),
        collocations=tuple(collocations),
        dropped=tuple(dropped),
        rejected=tuple(rejected),
        unparsed=tuple(unparsed),
        printed=printed,
    )


# -------------------------------------------------------------------------------------------- R9 phrases
def is_template(raw: str) -> bool:
    """``sb.`` / ``sth.`` / ``one's`` / ``oneself`` / ``...`` in the printed phrase → ``skipped.patterns`` when unresolved."""
    return bool(_TEMPLATE_RE.search(fold(raw)))


def _expand_parens(s: str) -> set[str]:
    """Optional bracket groups, recursively: spaced ``(of)`` inserts a token, attached ``movie(s)`` glues the suffix,
    ``(in/on/at)`` lists alternatives; each group yields the text without it as well."""
    m = _PAREN_RE.search(s)
    if not m:
        return {s}
    lead, inner = m.group(1), m.group(2)
    before, after = s[: m.start()], s[m.end() :]
    joined = (before + " " + after) if lead else (before + after)
    out = {_squash(joined)}
    for alt in inner.split("/"):
        alt = alt.strip()
        if alt:
            out.add(_squash(before + (" " if lead else "") + alt + after))
    result: set[str] = set()
    for cand in out:
        result |= _expand_parens(cand)
    return result


def _expand_slashes(s: str) -> set[str]:
    """Token-level ``/`` alternation, every slash token independently (``be/get familiar to/with`` → 4 candidates)."""
    options = [tok.split("/") if "/" in tok else [tok] for tok in s.split(" ")]
    options = [[o for o in opts if o] or [""] for opts in options]
    return {_squash(" ".join(combo)) for combo in itertools.product(*options)}


def _squash(s: str) -> str:
    return _WS_RE.sub(" ", s).strip()


def phrase_candidates(raw: str) -> set[str]:
    """R9 grammar: every expansion of a phrase line (folded, not lower-cased, empty strings removed)."""
    s = _ELLIPSIS_RE.sub(" ... ", fold(raw))
    s = _squash(s)
    if not s:
        return set()
    out: set[str] = set()
    for cand in _expand_parens(s):
        out |= _expand_slashes(cand)
    return {c for c in out if c}


def resolve_phrase(
    raw: str,
    *,
    lexicon: Lexicon | None = None,
    aliases: Mapping[str, str] | None = None,
    previous: AbstractSet[str] = frozenset(),
) -> PhraseResult:
    """R9 + R12: members are the candidates with a space that are known (lexicon or previous) and pass the strict gate."""
    cands = tuple(sorted(phrase_candidates(raw)))
    members: list[str] = []
    rejected: list[Rejected] = []
    for cand in cands:
        if " " not in cand:
            continue
        lemma = canon(cand, aliases)
        if lemma is None or not _known(cand, lemma, lexicon, previous):
            continue
        reason = strict_reason(lemma)
        if reason is not None:
            rejected.append(Rejected(cand, lemma, "phrase", reason))
        elif lemma not in members:
            members.append(lemma)
    skipped = None if members else ("patterns" if is_template(raw) else "other")
    return PhraseResult(raw=raw, candidates=cands, members=tuple(sorted(members)), rejected=tuple(rejected), skipped=skipped)


# -------------------------------------------------------------------------------------------- R6 / R8 aggregation
def merge_heads(members: Iterable[Member]) -> dict[str, Member]:
    """R6: one record per lemma in first-seen order; sets unioned, ``variant_of`` kept only while every source is a
    variant, ``printed`` from the first source that has one."""
    out: dict[str, Member] = {}
    for m in members:
        cur = out.get(m.lemma)
        if cur is None:
            out[m.lemma] = m
            continue
        out[m.lemma] = Member(
            lemma=m.lemma,
            stages=cur.stages | m.stages,
            tokens=cur.tokens | m.tokens,
            printed=cur.printed or m.printed,
            variant_of=None if (cur.variant_of is None or m.variant_of is None) else cur.variant_of,
            aliases=cur.aliases | m.aliases,
            lists=cur.lists | m.lists,
        )
    return out


def inherit_forms(
    inherit_stages: Mapping[str, Iterable[str]],
    previous: AbstractSet[str],
    official: AbstractSet[str],
) -> dict[str, str]:
    """R8: ``{form_lemma: base_lemma}`` for the listed forms that are previous-seed lemmas and not official members.

    ``official`` is the set of every official member lemma — heads AND bracket variants (PLAN §4.2 INH:
    ``f ∉ L2∪L3∪SH∪HS``): a form that any list names, even inside a note, keeps its own membership instead of
    inheriting. Lemmas are ``lemma_of`` (no aliases: these are previous-seed rows). A form listed under two bases keeps
    the first base in mapping order. The build never creates a row for a form (PLAN R8: ``am, is, are ← be``;
    ``does ← do``).
    """
    out: dict[str, str] = {}
    for base, forms in inherit_stages.items():
        base_lemma = lemma_of(base)
        if not base_lemma:
            continue
        for form in forms:
            f = lemma_of(form)
            if f and f in previous and f not in official and f not in out:
                out[f] = base_lemma
    return out


# -------------------------------------------------------------------------------------------- helpers
def _dedupe(items: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return tuple(out)
