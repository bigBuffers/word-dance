"""「单词之舞」 P1 — the rule-based ``DanceSpec`` (docs/WORD_DANCE_DESIGN.md §4.1–4.2, §6.2; API.md §9 ``DanceSpec``).

The study card lets a word "dance" its spelling and its rhythm: the letters enter syllable by syllable (拼写舞) and the
syllables then beat in turn with the stressed one highest (重音舞). Everything the card needs comes from two columns the
``words`` table already has — the display form and the ECDICT phonetic — so this module is pure, has no table behind it
and is cheap enough to run while a word is serialised (``services.words.word_detail`` / ``screen.study_item_dict``).

What the phonetic looks like (``data/seed/vocab.jsonl.gz``, ``0009_strip_phonetic_delimiters.sql``): ASCII apostrophe =
primary stress — two of them (``'fif'tiːn``, ``'ɑːftə'nuːn``) are the old double-stress notation whose LAST mark is the
citation primary —, a bare ``.`` / ``,`` / ``ˌ`` before a syllable = secondary stress, ``ː`` = length, variants separated
by ``". "`` / ``", "`` or a bare ``.`` between two unmarked monosyllables (``liv.laiv``); ``є`` stands for the /e/ of ``eə``
and ``^`` for a lost ``g``; diphthongs are written ``ai au ei əu ɔi ɒi iə eə uə`` (``iə`` / ``uə`` also stand for two
syllables when the spelling has i / u plus another vowel letter: se·ri·ous, Jan·u·a·ry) and a lone ``i`` / ``u`` / ``ɔ`` is
the short vowel. Claude-looked-up words carry IPA ``ˈ`` / ``ˌ`` instead. Syllabic consonants are written without a vowel
(``'æpl``, ``'sevn``, ``'fainl``, ``'stjuːdnt``); a few transcriptions elide a schwa the spelling keeps (``'intristiŋ``).

Degradation is deliberate (design principle 6): when the orthography and the transcription cannot agree on the number of
syllables, the spec keeps the whole word as ONE chunk (``letters == [display]``; ``stress`` 0 for a monosyllable, else
``None``) so the card still plays the plain entrance and one beat; a display that is not plain letters (phrases, ``Mr.``,
``o'clock``, ``ping-pong``) or a word without a phonetic gets no spec at all (``None``) and the card shows the headword as
today. The 2026-11-08 review of all 600 小学 splits against dictionary and phonics rules (docs/WORD_DANCE_DESIGN.md §10)
shaped the rules below; what it left to P2's Claude pass is listed there (heteronyms, hyphenated words).

P3b (docs/WORD_DANCE_DESIGN.md §13) moved the one suffix cut the review kept flagging into the rules: a derived -er word is cut
after its stem (work·er, farm·er, low·er) when :func:`er_evidence` can prove the derivation from the bank rows of the word
and its stem — :func:`er_stem` looks the stem up, :func:`rule_spec` is ``spec_for`` with that hint. The same release made the
rules the authority for everything mechanical in a stored annotation too: ``word_dances.corrected`` (0017) records whether
Claude changed the chunks or stress it was given, and :func:`spec_for_word` serves the stored chunks only where it did,
so every later rule improvement reaches the words whose cut the model merely confirmed.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from . import db
from .config import Settings, get_settings
from .jobs import queue

__all__ = ["DANCE_SPEC_VERSION", "DANCE_JOB", "spec_for", "spec_for_word", "rule_spec", "suggested_stress", "er_stem", "er_evidence", "active_spec", "active_record", "store_spec", "backfill_corrected", "mark_failed", "enqueue_if_needed", "nuclei", "ortho_groups", "split_letters", "silent_letters", "double_letters", "first_variant"]

log = logging.getLogger(__name__)

DANCE_SPEC_VERSION = 1

# ECDICT quirks on 小学 words that no rule can see: the month is the second variant of ``august`` (the first is the adjective
# /ɔːˈɡʌst/), and ``email`` keeps the double-stress notation although every modern dictionary says ˈiːmeɪl.
_PHONETIC_OVERRIDES: dict[str, str] = {"august": "'ɔːgəst", "email": "'iːmeil"}

# ----------------------------------------------------------------------------------------------- the transcription
_VOWELS = frozenset("aeiouæɑɒɔəɜɪʌʊɛ")
_DIPHTHONGS = frozenset({"ai", "au", "ei", "əu", "ɔi", "ɒi", "iə", "eə", "uə", "ou", "aɪ", "aʊ", "eɪ", "əʊ", "ɔɪ", "ɪə", "ʊə", "oʊ"})
_CENTRING = frozenset({"iə", "uə", "ɪə", "ʊə"})  # may stand for two syllables when the spelling says so (se·ri·ous, u·su·al)
# lax vowels: a stressed one before a single consonant closes its syllable (vis·it, sev·en, rab·bit); ə and every long
# vowel / diphthong leave the consonant to the next syllable (a·bout, ba·na·na, o·pen, pa·per)
_LAX = frozenset("iɪeɛæɒɔʌuʊ")
_R_COLOURED = frozenset({"ɔː", "ɑː", "ɜː"})  # or·ange, stor·y: the r stays with the vowel it colours
_PRIMARY = "'"
_SECONDARY = ".,"
_SONORANT_TAIL = frozenset("lnm")  # syllabic l / n / m after an obstruent, or l after n (ap·ple, sev·en, fi·nal, rhyth·m)
_NOT_BEFORE_SYLLABIC = frozenset("lrmwj") | _VOWELS


@dataclass(frozen=True)
class Nucleus:
    """One vowel nucleus of the transcription: its symbol, whether it carries primary / any stress, whether it is the
    second half of a triphthong (``aiə`` / ``auə``) that the orthography may treat as one syllable (hour, fire, our)."""

    symbol: str
    primary: bool
    stressed: bool
    tri: bool = False
    syllabic: str = ""  # the consonant letter that is the nucleus ('sevn → "n"): it stays in its own chunk (per·son·al)

    @property
    def open_before_single_consonant(self) -> bool:
        """pa·per, o·pen, a·bout, be·gin: long vowel, diphthong, ə, or an unstressed vowel."""
        return len(self.symbol) > 1 or self.symbol not in _LAX or not self.stressed


def _normalise(phonetic: str) -> str:
    p = (phonetic or "").strip().strip("/[]").replace("ˈ", _PRIMARY).replace("ˌ", ",").replace("є", "e").replace("ɛ", "e").replace("^", "g")
    return p.strip()


def first_variant(phonetic: str) -> str:
    """The first pronunciation when the field lists several (``dæns. dɑːns``, ``'^rænpɑː, '^rændpɑː``, ``liv.laiv``)."""
    p = _normalise(phonetic)
    for sep in (". ", ", ", "; ", " / ", "/"):
        if sep in p:
            p = p.split(sep)[0].strip()
    # a bare dot between two transcriptions that carry no stress mark of their own is a variant separator, not a
    # secondary-stress mark ('teli.viʒən keeps its dot; liv.laiv does not)
    if "." in p[1:]:
        head, _, tail = p.partition(".")
        if _PRIMARY not in head and _PRIMARY not in tail and _has_vowel(head) and _has_vowel(tail) and head and tail:
            p = head
    return p.strip().rstrip(" .,")


def _has_vowel(s: str) -> bool:
    return any(ch in _VOWELS for ch in s)


def nuclei(phonetic: str) -> list[Nucleus]:
    """The vowel nuclei of the first variant, in order, with stress marks attached to the nucleus they precede. With two
    primary marks (the old double-stress notation) the last one is the primary and the earlier ones count as secondary."""
    p = first_variant(phonetic)
    out: list[Nucleus] = []
    primary = secondary = False
    i = 0
    n = len(p)
    while i < n:
        ch = p[i]
        if ch == _PRIMARY:
            primary = True
            i += 1
            continue
        if ch in _SECONDARY:
            secondary = True
            i += 1
            continue
        if ch in _VOWELS:
            two = p[i : i + 2]
            sym, step = (two, 2) if two in _DIPHTHONGS else (ch, 1)
            if p[i + step : i + step + 1] == "ː":
                sym, step = sym + "ː", step + 1
            tri = bool(out) and ch == "ə" and step == 1 and out[-1].symbol in ("ai", "au", "aɪ", "aʊ") and p[i - 1] in "iɪuʊ"
            out.append(Nucleus(sym, primary, primary or secondary, tri))
            primary = secondary = False
            i += step
            continue
        if ch in _SONORANT_TAIL and i > 0:
            # obstruent (or n before l) + l/n/m with no vowel between and none following: a syllabic consonant
            # ('æpl, 'sevnti, 'stjuːdnt, 'fainl, 'pɜːsnl)
            j = i - 1
            while j > 0 and p[j] in "ː" + _PRIMARY + _SECONDARY:
                j -= 1
            prev = p[j]
            k = i + 1
            while k < n and p[k] in _PRIMARY + _SECONDARY:
                k += 1
            nxt = p[k] if k < n else ""
            consonant_before = prev not in _NOT_BEFORE_SYLLABIC and prev != "ː" and prev not in _PRIMARY + _SECONDARY
            if (consonant_before or (prev in "nm" and ch == "l")) and (not nxt or nxt not in _VOWELS):
                out.append(Nucleus("ə", primary, primary or secondary, syllabic=ch))
                primary = secondary = False
        i += 1
    primaries = [k for k, nuc in enumerate(out) if nuc.primary]
    if len(primaries) > 1:
        out = [Nucleus(nuc.symbol, k == primaries[-1], nuc.stressed, nuc.tri, nuc.syllabic) for k, nuc in enumerate(out)]
    return out


def _merge_triphthongs(nucs: list[Nucleus]) -> list[Nucleus]:
    merged: list[Nucleus] = []
    for nuc in nucs:
        if nuc.tri and merged:
            prev = merged[-1]
            merged[-1] = Nucleus(prev.symbol + "ə", prev.primary or nuc.primary, prev.stressed or nuc.stressed)
        else:
            merged.append(nuc)
    return merged


def _merge_syllabic_run(nucs: list[Nucleus]) -> list[Nucleus]:
    """'signl / 'pɜːsnl: an obstruent + n + l cluster is one syllable in sig·nal and two in per·son·al — the vowel groups of the
    spelling decide, so the merged reading is offered to ``_match`` as an alternative."""
    merged: list[Nucleus] = []
    for nuc in nucs:
        if nuc.syllabic and merged and merged[-1].syllabic:
            prev = merged[-1]
            merged[-1] = Nucleus(prev.symbol, prev.primary or nuc.primary, prev.stressed or nuc.stressed, prev.tri, prev.syllabic)
        else:
            merged.append(nuc)
    return merged


def _expand_centring(nucs: list[Nucleus], count: int) -> list[Nucleus]:
    """Read the last ``count`` centring diphthongs (iə / uə) as two syllables: se·ri·ous, Jan·u·a·ry, ex·pe·ri·ence."""
    out: list[Nucleus] = []
    todo = count
    for nuc in reversed(nucs):
        if todo > 0 and nuc.symbol.rstrip("ː") in _CENTRING:
            out.append(Nucleus("ə", False, False))
            out.append(Nucleus(nuc.symbol[0], nuc.primary, nuc.stressed))
            todo -= 1
        else:
            out.append(nuc)
    out.reverse()
    return out


# ----------------------------------------------------------------------------------------------- the spelling
_ORTHO_VOWELS = frozenset("aeiou")
_DIGRAPH_ONSETS = frozenset({"ch", "sh", "th", "ph", "wh", "gh", "qu"})  # stay together and open the next syllable
_CODA_DIGRAPHS = frozenset({"ck", "ng"})  # never begin a syllable: chick·en, sing·er
_LIQUID_BLENDS = frozenset({"bl", "br", "cl", "cr", "dr", "fl", "fr", "gl", "gr", "pl", "pr", "tr", "thr", "shr", "chr", "str", "spr", "scr", "spl"})
_S_BLENDS = frozenset({"sc", "sk", "sl", "sm", "sn", "sp", "st", "sw"})
_ONSET_BLENDS = _LIQUID_BLENDS | frozenset({"tw", "dw"})
_HIATUS = frozenset({"ia", "ie", "io", "iu", "eo", "ua", "ue", "uo", "oe", "ea", "ei", "oi", "ee"})  # vowel pairs that may be two syllables (only tried when the counts disagree)
_HIATUS_PREFER = frozenset({"ia", "io", "iu", "ua", "ue", "uo"})  # … and are, when the transcription has an iə / uə there
_LETTERS_RE = re.compile(r"[A-Za-z]+")


def ortho_groups(word: str, *, silent_w: bool = False, y_between_vowels: bool = False) -> list[tuple[int, int]]:
    """``(start, end)`` of every run of vowel letters. ``y`` is a vowel except word-initially or right before another
    vowel (yes, yellow, beyond) — unless ``y_between_vowels`` says the transcription has no /j/, then a y after a vowel
    closes its team (play·er, say·ing) —, ``u`` after ``q`` is part of the consonant, a final ``ye`` is one vowel (bye), and
    a ``w`` after a / e / o closes a vowel digraph (yellow, draw) — also before a vowel when the transcription has no /w/
    at all (``silent_w``: flow·er, tow·el, but a·way, to·ward)."""
    w = word.lower()
    groups: list[tuple[int, int]] = []
    i = 0
    n = len(w)
    while i < n:
        ch = w[i]
        vowel = ch in _ORTHO_VOWELS
        if ch == "y" and i > 0:
            nxt = w[i + 1] if i + 1 < n else ""
            vowel = nxt not in _ORTHO_VOWELS or (nxt == "e" and i + 2 == n)
        if ch == "u" and i > 0 and w[i - 1] == "q":
            vowel = False
        if not vowel:
            i += 1
            continue
        j = i + 1
        while j < n and (w[j] in _ORTHO_VOWELS or (w[j] == "y" and not (j + 1 < n and w[j + 1] in _ORTHO_VOWELS))):
            j += 1
        if j < n and w[j] == "y" and y_between_vowels and j + 1 < n and w[j + 1] in _ORTHO_VOWELS:
            j += 1  # play·er: the y closes the vowel team, the vowel after it starts the next group
        elif j < n and w[j] == "w" and w[j - 1] in "aeo" and (silent_w or j + 1 == n or w[j + 1] not in _ORTHO_VOWELS):
            j += 1  # the w closes the digraph; a vowel after it starts the next group (flow·er, tow·el)
        groups.append((i, j))
        i = j
    return groups


def _valid_onset(cluster: str) -> bool:
    return len(cluster) <= 1 or cluster in _DIGRAPH_ONSETS or cluster in _ONSET_BLENDS or cluster in _S_BLENDS


def _drop_final_e(w: str, groups: list[tuple[int, int]]) -> list[tuple[int, int]] | None:
    """dance, make, clothes, tired: a final ``e`` (or ``es`` / ``ed``) after a consonant that the transcription does not sound."""
    if not groups:
        return None
    s, e = groups[-1]
    final_e = e - s == 1 and w[s] == "e" and (e == len(w) or (e == len(w) - 1 and w[-1] in "sd")) and s >= 2 and w[s - 1] not in _ORTHO_VOWELS
    if final_e and e == len(w) and w[s - 1] == "l" and w[s - 2] not in _ORTHO_VOWELS and w[s - 2] != "y":
        final_e = False  # consonant + le is a syllable of its own (ta·ble, ap·ple, veg·e·ta·ble); vowel + le is magic e (mile, whole, style)
    return groups[:-1] if final_e and len(groups) > 1 else None


def _drop_internal_e(w: str, groups: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], int] | None:
    """care·ful, nine·teen, love·ly, eve·ning: exactly one single-letter ``e`` between consonants that is not sounded."""
    candidates = [k for k, (s, e) in enumerate(groups) if 0 < k < len(groups) - 1 and e - s == 1 and w[s] == "e" and w[s - 1] not in _ORTHO_VOWELS and e < len(w) and w[e] not in _ORTHO_VOWELS]
    if len(candidates) != 1:
        return None
    k = candidates[0]
    return groups[:k] + groups[k + 1 :], groups[k][0]


def _split_hiatus(w: str, groups: list[tuple[int, int]], phon: str = "", prefer: frozenset[str] = _HIATUS) -> list[tuple[int, int]] | None:
    """qui·et, li·on, sci·ence, cre·ate, twen·ti·eth: one vowel run that is really two syllables (the last candidate that is
    not the i + vowel of a /ʃ/ spelling: sit·u·a·tion keeps its -tion)."""
    picks = [k for k, (s, e) in enumerate(groups) if e - s >= 2 and w[s : s + 2] in prefer and not (s >= 1 and w[s - 1] in "tcs" and _shush(w, s, phon))]
    if not picks:
        return None
    k = picks[-1]
    s, e = groups[k]
    at = e - 1 if e - s == 3 and w[s : s + 2] not in _HIATUS_PREFER else s + 1  # see|ing, agree|ing · i|ous, qu·i|et
    return groups[:k] + [(s, at), (at, e)] + groups[k + 1 :]


@dataclass(frozen=True)
class Reading:
    """One way of reading the spelling: its vowel groups, the index of a dropped internal silent e, whether the final e
    was dropped, whether a hiatus pair was split."""

    groups: tuple[tuple[int, int], ...]
    dropped: int | None = None
    final_e: bool = False
    hiatus: bool = False


def _readings(w: str, raw: list[tuple[int, int]], phon: str) -> list[Reading]:
    """The orthographic readings in order of plausibility: as written, without a silent final e, each also without a
    silent internal e and with one vowel run split in two (hiatus). A final e after a consonant is read as silent first
    when the transcription ends in a consonant (cre·ate, min·ute); the ordinal ending -ieth always reads ie as two
    syllables."""
    if w.endswith("ieth") and raw and raw[-1][1] - raw[-1][0] >= 2:
        raw = _split_hiatus(w, raw, phon) or raw
    bases = [Reading(tuple(raw))]
    fe = _drop_final_e(w, raw)
    if fe:
        silent_first = bool(phon) and phon[-1] not in _VOWELS and phon[-1] != "ː"
        bases.insert(0 if silent_first else 1, Reading(tuple(fe), None, True))
    out: list[Reading] = []
    for base in bases:
        family = [base]
        ie = _drop_internal_e(w, list(base.groups))
        if ie:
            family.append(Reading(tuple(ie[0]), ie[1], base.final_e))
        for member in list(family):
            hs = _split_hiatus(w, list(member.groups), phon)
            if hs:
                family.append(Reading(tuple(hs), member.dropped, member.final_e, True))
        out.extend(family)
    return out


def _match(w: str, raw: list[tuple[int, int]], full: list[Nucleus], tri: list[Nucleus] | None, syl: list[Nucleus] | None, phon: str) -> tuple[Reading, list[Nucleus]] | None:
    """The first (reading, nuclei) pair with equal counts. Order: a spelling with a hiatus pair that the transcription writes
    as iə / uə prefers the two-syllable reading (se·ri·ous, Jan·u·a·ry); with a triphthong (``tri`` = merged), a true hiatus
    pair keeps both syllables (li·on, qui·et, sci·ence) and anything else is read as one (hour, fire, tired) before the
    two-syllable reading; a run of syllabic consonants (``syl`` = merged) is one syllable when only the spelling says so
    (sig·nal, but per·son·al)."""
    readings = _readings(w, raw, phon)
    pairs = sum(1 for s, e in raw if e - s >= 2 and w[s : s + 2] in _HIATUS_PREFER)
    centring = sum(1 for nuc in full if nuc.symbol.rstrip("ː") in _CENTRING)
    if pairs and centring:
        expanded = _expand_centring(full, min(pairs, centring))
        for r in readings:
            if r.hiatus and len(r.groups) == len(expanded):
                return r, expanded
    if tri is not None:
        hiatus = [r for r in readings if any(w[s : s + 2] in _HIATUS for s, e in r.groups if e - s == 1 and s + 1 < len(w) and w[s + 1] in _ORTHO_VOWELS)]
        pools: list[tuple[list[Reading], list[Nucleus]]] = [(hiatus, full), (readings, tri), (readings, full)]
    else:
        pools = [(readings, full)]
    if syl is not None:
        pools.append((readings, syl))
    for pool, nucs in pools:
        for r in pool:
            if len(r.groups) == len(nucs):
                return r, nucs
    return None


def _elided_schwa(w: str, raw: list[tuple[int, int]], full: list[Nucleus]) -> tuple[Reading, list[Nucleus]] | None:
    """in·ter·est·ing, con·sid·er, choc·o·late: the transcription writes one syllable fewer than the spelling has vowel
    groups and no reading explains it — read the spelling as written (minus a silent final e) and put the missing
    unstressed syllable after the stressed one."""
    if not full:
        return None
    fe = _drop_final_e(w, raw)
    for groups, final_e in ((raw, False), (fe, True)):
        if groups is None or len(groups) != len(full) + 1:
            continue
        at = next((k for k, nuc in enumerate(full) if nuc.primary), 0) + 1
        if at >= len(groups) - 1:
            return None  # the extra group is the last one: silent letters (sty·le, lea·gue, u·ni·que), not an elided schwa
        s, e = groups[at]
        if e - s != 1:
            return None  # a vowel team is never the elided schwa (som·ew·here)
        if any(e2 - s2 == 1 and w[s2] == "e" and w[e2 : e2 + 2] == "ly" or w[e2 : e2 + 4] == "ment" or w[e2 : e2 + 3] == "ful" for s2, e2 in groups if e2 - s2 == 1 and w[s2] == "e"):
            return None  # a silent e before -ly / -ment / -ful (com·plete·ly, man·age·ment) is not a syllable
        if w.endswith(("gue", "que")) and groups[-1] == (len(w) - 2, len(w)):
            return None  # … nor a silent -ue (cat·a·logue, u·nique)
        nucs = [*full[:at], Nucleus("ə", False, False), *full[at:]]
        return Reading(tuple(groups), None, final_e), nucs
    return None


def _shush(w: str, start: int, phon: str) -> bool:
    """i + vowel after a t / c / s that spells /ʃ/ or /ʒ/ (na·tion·al, spe·cial, mu·si·cian, vi·sion)."""
    return start + 1 < len(w) and w[start] == "i" and w[start + 1] in _ORTHO_VOWELS and ("ʃ" in phon or "ʒ" in phon)


def split_letters(word: str, phonetic: str) -> tuple[list[str], list[Nucleus], Reading] | None:
    """``word`` cut into one chunk per syllable, following its vowel groups; ``None`` when orthography and transcription
    disagree (the caller then keeps the whole word as one chunk). Also returns the nuclei used and the reading."""
    w = word.lower()
    full = nuclei(phonetic)
    if not full or not _LETTERS_RE.fullmatch(w):
        return None
    phon = first_variant(phonetic)
    tri = _merge_triphthongs(full)
    syl = _merge_syllabic_run(full)
    raw = ortho_groups(w, silent_w="w" not in phon, y_between_vowels="j" not in phon)
    matched = _match(w, raw, full, tri if len(tri) != len(full) else None, syl if len(syl) != len(full) else None, phon) or _elided_schwa(w, raw, full)
    if matched is None:
        return None
    reading, nucs = matched
    groups, dropped = list(reading.groups), reading.dropped
    count = len(groups)
    primary_at = next((i for i, nuc in enumerate(nucs) if nuc.primary), None)
    # ECDICT marks primary stress only: a word-initial lax vowel two or more syllables before it carries the unmarked
    # secondary stress and closes its syllable (sev·en·teen, not se·ven·teen); e·lev·en keeps its open prefix
    if primary_at is not None and primary_at >= 2 and not nucs[0].stressed and nucs[0].symbol in _LAX:
        nucs = [Nucleus(nucs[0].symbol, False, True, nucs[0].tri), *nucs[1:]]
    if count == 1:
        return [word], nucs, reading
    cuts: list[int] = []
    for g in range(count - 1):
        v_end, next_start = groups[g][1], groups[g + 1][0]
        cluster = w[v_end:next_start]
        k = len(cluster)
        last = g == count - 2
        g_start = groups[g][0]
        prev_shush = g_start >= 1 and w[g_start - 1] in "tcs" and _shush(w, g_start, phon)
        if dropped is not None and v_end <= dropped < next_start:
            cut = v_end + 1  # the silent e stays with the chunk it lengthens: care|ful, nine|teen, eve|ning
            while cut < next_start - 1 and not _valid_onset(w[cut:next_start]):
                cut += 1
        elif last and w.endswith("ing") and k >= 1 and not (k == 2 and cluster[0] == cluster[1]) and groups[g + 1] == (len(w) - 3, len(w) - 2):
            cut = next_start - 2 if w.endswith("thing") and count >= 3 else next_start  # meet|ing, morn|ing, est|ing · an·y|thing
        elif last and w.endswith("le") and k >= 2 and cluster.endswith("l"):
            cut = next_start - 1 if w[next_start - 3 : next_start - 1] == "ck" else next_start - 2  # lit|tle, mid|dle, un|cle, pick|le
        elif k == 1 and cluster in "tcs" and _shush(w, next_start, phon):
            cut = v_end  # na|tional, spe|cial, of·fi|cial, vi|sion, tel·e·vi|sion
        elif k == 1 and cluster == "n" and prev_shush:
            cut = v_end + 1  # na·tion|al, in·ter·na·tion|al: the -tion unit keeps its n
        elif g == 0 and groups[0] == (0, 1) and not nucs[0].stressed and k >= 2 and _valid_onset(cluster):
            cut = v_end  # a|sleep, a|cross, a|gree
        elif k == 0:
            cut = v_end
        elif k == 1:
            if cluster == "x":
                cut = v_end + 1  # ex|it, tax|i
            elif nucs[g].syllabic and cluster == nucs[g].syllabic:
                cut = v_end + 1  # per·son|al, sev·en|th: the syllabic consonant is its own chunk's nucleus
            elif cluster == "r" and (nucs[g].symbol in _R_COLOURED or (nucs[g].symbol == "ə" and w[groups[g][0] : groups[g][1]] == "e")):
                cut = v_end + 1  # or|ange, stor|y, in·ter|est, dif·fer|ent: the r stays with the vowel it colours
            else:
                cut = v_end if nucs[g].open_before_single_consonant else v_end + 1
        elif k == 2:
            if cluster in _CODA_DIGRAPHS:
                cut = v_end + 1 if cluster == "ng" and "ŋg" in phon else v_end + 2  # fin|ger, sing|er, chick|en
            elif cluster in _DIGRAPH_ONSETS:
                cut = v_end if nucs[g].open_before_single_consonant else v_end + 2  # fa|ther, tea|cher, e|phant · moth|er, weath|er
            elif cluster[0] == cluster[1] or cluster in _S_BLENDS or cluster not in _ONSET_BLENDS:
                cut = v_end + 1  # rab|bit, bas|ket, sis|ter, pic|ture, win|dow
            else:
                cut = v_end if nucs[g].open_before_single_consonant else v_end + 1  # ta|ble, se|cret · zeb|ra
        elif cluster.startswith("tch"):
            cut = v_end + 3  # kitch|en, watch|ing
        else:
            cut = v_end + 1
            while cut < next_start - 1 and not _valid_onset(w[cut:next_start]):
                cut += 1  # hun|dred, pump|kin, Wednes|day
        cuts.append(cut)
    parts: list[str] = []
    prev = 0
    for cut in cuts:
        if cut <= prev or cut >= len(word):
            return None
        parts.append(word[prev:cut])
        prev = cut
    parts.append(word[prev:])
    return parts, nucs, reading


# ----------------------------------------------------------------------------------------------- letter marks
def double_letters(word: str) -> list[list[int]]:
    """Index pairs of doubled letters (rab·bit's bb, book's oo): they jump together on the card."""
    w = word.lower()
    return [[i, i + 1] for i in range(len(w) - 1) if w[i] == w[i + 1] and w[i].isalpha()]


def _pattern_silent(w: str, p: str) -> set[int]:
    """The pattern-based silent letters of :func:`silent_letters` (everything but the magic e the split finds): ``w`` lower-case
    letters, ``p`` the first phonetic variant."""
    out: set[int] = set()
    q = p.lstrip(_PRIMARY + _SECONDARY)  # 'ɒnist: the leading-letter tests look past a stress mark
    if w.startswith("kn") and not q.startswith("k"):
        out.add(0)
    if w.startswith("wr") and not q.startswith("w"):
        out.add(0)
    if w.startswith("wh") and q.startswith("h") and not q.startswith("hw"):
        out.add(0)
    if w.startswith("h") and q and q[0] in _VOWELS:
        out.add(0)
    if w.startswith("tw") and "w" not in p:
        out.add(1)
    if w.endswith("mb") and "b" not in p:
        out.add(len(w) - 1)
    if w.endswith("mn") and "n" not in p[-2:]:
        out.add(len(w) - 1)
    if "g" not in p and p.count("f") <= w.count("f"):  # the gh of laugh / enough is the only /f/ of the word
        for m in re.finditer(r"[aeiou]+(gh)", w):
            out.update({m.start(1), m.start(1) + 1})
    if "l" not in p:
        for m in re.finditer(r"a(l)(?:k|f|m)|ou(l)d$", w):
            out.add(m.start(1) if m.group(1) else m.start(2))
    if "t" not in p:
        for m in re.finditer(r"[sf](t)(?:en|le)$|s(t)m", w):
            out.add(m.start(1) if m.group(1) else m.start(2))
    if "w" not in p:
        for m in re.finditer(r"s(w)", w):
            out.add(m.start(1))
    if p.count("d") < w.count("d"):
        for m in re.finditer(r"(d)n", w):
            out.add(m.start(1))  # Wed·nes·day's first d
    return out


def silent_letters(word: str, phonetic: str) -> list[int]:
    """Indexes of letters the transcription does not sound, by a few safe patterns: kn- wr- wh- (who) h- (hour) tw- (two),
    -mb -mn, gh after a vowel (night, eight, daughter, though — not laugh), the l of -alk/-alf/-alm/-ould, the t of
    -sten/-ften/-stle/-stm-, the w of -sw-, the d of -dn- (Wednesday), and the magic e (final, or internal as in care·ful)
    the split found silent."""
    w = word.lower()
    p = first_variant(phonetic)
    if not p or not _LETTERS_RE.fullmatch(w):
        return []
    out = _pattern_silent(w, p)
    groups = ortho_groups(w, silent_w="w" not in p, y_between_vowels="j" not in p)
    split = split_letters(w, phonetic)
    final_e = split[2].final_e if split is not None else (_drop_final_e(w, groups) is not None and len(groups) > len(nuclei(phonetic)))
    if final_e:
        out.add(groups[-1][0])
    if split is not None and split[2].dropped is not None:
        out.add(split[2].dropped)
    return sorted(out)


# ----------------------------------------------------------------------------------------------- the spec
def spec_for(display: str | None, phonetic: str | None, *, er_stem: tuple[str, str] | None = None) -> dict[str, Any] | None:
    """API.md §9 ``DanceSpec`` for a word, or ``None`` when the display is not plain letters or no phonetic is stored. ``er_stem`` =
    ``(stem display, stem phonetic)`` from :func:`er_stem` cuts a derived -er word after its stem (work·er); without the hint the
    word is cut by the ordinary rules alone (the pure P1 behaviour)."""
    text = (display or "").strip()
    if not text or not _LETTERS_RE.fullmatch(text):
        return None
    phonetic = _PHONETIC_OVERRIDES.get(text.lower(), phonetic)
    if not phonetic or not first_variant(phonetic):
        return None
    nucs = nuclei(phonetic)
    if not nucs:
        return None
    suffix = _er_split(text, phonetic, nucs, er_stem) if er_stem is not None else None
    split: tuple[list[str], list[Nucleus], Reading | None] | None
    if suffix is not None:
        # work·er: the stem's own silent letters (same offsets — the stem is a prefix of the display) plus the whole word's pattern
        # letters; the ordinary reading of the whole word (liste·ner with a "dropped" internal e) is the one this cut rejected, so
        # none of its marks — lis·ten·er keeps listen's silent t and sounds the e of ten
        letters, used, stem = suffix
        split = (letters, used, None)
        silent = sorted(_pattern_silent(text.lower(), first_variant(phonetic)) | set(stem["marks"]["silent"]))
    else:
        split = split_letters(text, phonetic)
        silent = silent_letters(text, phonetic)
    marks = {"double": double_letters(text), "silent": silent}
    if split is None:
        return {"version": DANCE_SPEC_VERSION, "letters": [text], "stress": 0 if len(nucs) == 1 else None, "marks": marks, "semantic": None, "source": "rule"}
    letters, used, _reading = split
    stress: int | None = next((i for i, n in enumerate(used) if n.primary), None)
    lower = text.lower()
    if len(letters) > 1 and lower.endswith(("teen", "teenth")):
        # the 13–19 numerals and ordinals stress -teen whatever ECDICT marks (ˌfɪfˈtiːn; 'fif'tiːn, 'θɜːtiːnθ)
        stress = next((i for i, chunk in enumerate(letters) if "teen" in chunk.lower()), stress)
    if stress is None:
        # no mark in the transcription (ʌŋkl): the first chunk whose vowel is not a schwa, else the first
        stress = next((i for i, n in enumerate(used) if n.symbol.rstrip("ː") != "ə"), 0) if len(letters) > 1 else 0
    return {"version": DANCE_SPEC_VERSION, "letters": letters, "stress": stress, "marks": marks, "semantic": None, "source": "rule"}


# ----------------------------------------------------------------------------------------------- the -er suffix (P3b)
# work·er, farm·er, low·er — not wor·ker / far·mer: a word that is a bank word plus -er keeps that stem whole and gives the suffix
# its own chunk, the way Merriam-Webster / Longman divide agent nouns and comparatives (the two VC·CV splits the P2 review kept
# flagging, docs/WORD_DANCE_DESIGN.md §11 / §13). Spelling alone cannot tell work·er from cor·ner, cen·ter, but·ter or mas·ter,
# so ``er_evidence`` demands four things of the pair (word row, stem row — ``er_stem`` supplies only public, valid, unmerged stem
# rows): the stem row is spelled exactly ``display[:-2]`` (lower-case letters only — a capitalised display such as Easter never gets
# the cut); the two transcriptions compose (stem + /ə/, /ər/ or /ɚ/ — num·ber's
# /bə/ and lon·ger's /gə/ fail); the stem is a content word (ECDICT pos has n / v / j — with·er, quar·ter fail); and the word is
# derived from it: ECDICT's exchange links a comparative to its base (``{"0": "low", "1": "r"}``), or — for a noun, or an
# adjective from an adjective, which keeps for·mer, ten·der, prop·er and in·ner out — the English definition names the stem
# (``a person who works …``), the two Chinese translations share a two-character word (农场 / 农场主) or the translation names
# the stem (``old的比较级``). 65 of the live bank's 95 spelling-plus-phonetic candidates pass (97 in the shipped seed, which
# still carries easter / mister; tests/fixtures/dance_er_splits.json pins the list); a derived word the evidence misses keeps the
# ordinary cut — fighter stays figh·ter, teller tel·ler — never worse than P1.
_ER_TAILS = frozenset({"ə", "ər", "ɚ", "ɝ", "ɜ", "ɜː"})
_ER_BARE_RE = re.compile(r"\(r\)|ʳ|[ˈˌ'.,\s]")
_LOWER_RE = re.compile(r"[a-z]+")
_POS_RE = re.compile(r"([a-z]):(\d+)")
_HAN_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
# two-character words so common in ECDICT glosses that sharing one proves nothing
_ER_GENERIC_BIGRAMS = frozenset({"的人", "东西", "一个", "起来", "使成", "成为", "进行", "某人", "某物", "某事", "使得", "一种", "一样", "一起", "的物", "可以", "没有", "不是", "表示", "用于", "用来", "或者", "做事"})


def _text(value: Any) -> str:
    """A ``words`` column the seed file stores as a list of lines and the table as newline-joined text."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v) for v in value)
    return str(value)


def _bare_phonetic(phonetic: str | None) -> str:
    """The first variant without stress marks, syllable dots, spaces and the optional-r notation: just the segments."""
    return _ER_BARE_RE.sub("", first_variant(phonetic or ""))


def _pos_shares(pos: Any) -> dict[str, int]:
    """ECDICT's ``v:4/n:96`` → ``{"v": 4, "n": 96}`` (``j`` = adjective, ``r`` = adverb, ``i`` = preposition, ``d`` = determiner)."""
    return {m.group(1): int(m.group(2)) for m in _POS_RE.finditer(_text(pos))}


def _han_bigrams(text: str) -> set[str]:
    out: set[str] = set()
    for run in _HAN_RUN_RE.findall(text):
        out.update(run[i : i + 2] for i in range(len(run) - 1))
    return out - _ER_GENERIC_BIGRAMS


def er_evidence(word: Mapping[str, Any], stem: Mapping[str, Any]) -> str | None:
    """Why ``word`` is ``stem`` + -er — ``"comparative"``, ``"definition"`` or ``"translation"`` — or ``None`` when the pair fails
    any test of the section comment above. Pure: both arguments are ``words`` rows (or seed records with list-valued columns)."""
    display = str(word.get("display") or word.get("lemma") or "")
    stem_display = str(stem.get("display") or stem.get("lemma") or "")
    if len(display) < 4 or not display.endswith("er") or not _LOWER_RE.fullmatch(display) or display[:-2] != stem_display:
        return None
    w, s = _bare_phonetic(word.get("phonetic")), _bare_phonetic(stem.get("phonetic"))
    if not w or not s or not w.startswith(s) or w[len(s) :] not in _ER_TAILS:
        return None
    stem_pos, word_pos = _pos_shares(stem.get("pos")), _pos_shares(word.get("pos"))
    if not (stem_pos.keys() & {"n", "v", "j"}):
        return None
    exchange: Any = word.get("exchange_json") if word.get("exchange_json") is not None else word.get("exchange")
    if isinstance(exchange, str):
        try:
            exchange = json.loads(exchange)
        except ValueError:
            exchange = None
    if isinstance(exchange, Mapping) and str(exchange.get("0") or "") == stem_display and "r" in str(exchange.get("1") or ""):
        return "comparative"
    top = max(word_pos, key=word_pos.__getitem__) if word_pos else None
    if not (top in (None, "n") or ("j" in stem_pos and "j" in word_pos)):
        return None
    if re.search(rf"(?<![a-z]){re.escape(stem_display)}(?:s|es|ed|d|ing)?(?![a-z])", _text(word.get("definition")).lower()):
        return "definition"
    translation = _text(word.get("translation"))
    if _han_bigrams(translation) & _han_bigrams(_text(stem.get("translation"))) or re.search(rf"(?<![A-Za-z]){re.escape(stem_display)}(?![A-Za-z])", translation):
        return "translation"
    return None


def er_stem(conn: sqlite3.Connection, word: Mapping[str, Any]) -> tuple[str, str] | None:
    """``(stem display, stem phonetic)`` when ``word`` is a bank word plus -er by :func:`er_evidence`, else ``None`` — the hint
    :func:`spec_for` needs to cut work·er. One lookup on ``ux_words_lemma`` among public, valid, unmerged words."""
    display = str(word.get("display") or word.get("lemma") or "")
    if len(display) < 4 or not display.endswith("er") or not _LOWER_RE.fullmatch(display):
        return None
    cur = conn.execute(
        "SELECT display, lemma, phonetic, translation, definition, pos FROM words "
        "WHERE lemma = ? AND is_public = 1 AND is_valid_english = 1 AND merged_into_word_id IS NULL",
        (display[:-2],),
    )
    row = cur.fetchone()
    if row is None:
        return None
    stem = {col[0]: row[i] for i, col in enumerate(cur.description)}
    if er_evidence(word, stem) is None:
        return None
    return display[:-2], str(stem["phonetic"] or "")


def suggested_stress(rule: Mapping[str, Any]) -> int:
    """The ``rule_stress`` the prompt sends for a rule spec: its stress, or 0 when the rules could not tell (a degraded one-chunk
    polysyllable). ``corrected`` compares the model's stress with THIS, never with the raw ``None``."""
    stress = rule.get("stress")
    return int(stress) if stress is not None else 0


def rule_spec(conn: sqlite3.Connection, word: Mapping[str, Any]) -> dict[str, Any] | None:
    """The rule layer's spec for a ``words`` row: :func:`spec_for` with the -er stem hint when the bank knows the stem."""
    return spec_for(word.get("display") or word.get("lemma"), word.get("phonetic"), er_stem=er_stem(conn, word))


def _er_split(text: str, phonetic: str, nucs: list[Nucleus], er_stem: tuple[str, str]) -> tuple[list[str], list[Nucleus], dict[str, Any]] | None:
    """work·er: ``(letters, nuclei used, the stem's spec)`` — the stem's own chunks (ordinary rules; a stem is never suffix-split
    again) plus the -er chunk, when the two transcriptions compose and the word has exactly one syllable more than the stem has
    chunks (or the transcription swallowed the stem's syllabic consonant, lis·ten·er); ``None`` sends the word to the ordinary cut."""
    stem_text, stem_phonetic = er_stem
    if len(text) < 4 or not text.endswith("er") or text[:-2] != stem_text:
        return None
    w, s = _bare_phonetic(phonetic), _bare_phonetic(stem_phonetic)
    if not w or not s or not w.startswith(s) or w[len(s) :] not in _ER_TAILS:
        return None
    stem = spec_for(stem_text, stem_phonetic)
    if stem is None or "".join(stem["letters"]) != stem_text:
        return None
    letters = [*stem["letters"], text[-2:]]
    if len(letters) == len(nucs):
        return letters, nucs, stem
    stem_nucs = nuclei(stem_phonetic)
    if len(letters) == len(nucs) + 1 and stem_nucs and stem_nucs[-1].syllabic and len(stem["letters"]) == len(stem_nucs):
        # lis·ten·er /ˈlɪsnə/, trav·el·er /ˈtrævlə/: the transcription swallows the stem's syllabic consonant before the suffix vowel;
        # the spelling keeps the syllable, as the elided-schwa rule does for in·ter·est·ing — a stressless ə stands in for it
        return letters, [*nucs[:-1], Nucleus("ə", False, False), nucs[-1]], stem
    return None


# ----------------------------------------------------------------------------------------------- stored specs (P2)
DANCE_JOB = "generate_dance"


def active_record(conn: sqlite3.Connection, word: Mapping[str, Any]) -> tuple[dict[str, Any], int | None] | None:
    """The word's stored annotation (the ``word_dances`` row ``words.active_dance_id`` points at, ``source == 'claude'``) as
    ``(spec, corrected)`` — ``corrected`` 1 when Claude changed the chunks or stress it was given, 0 when it confirmed them, ``None``
    for a row the 0017 backfill has not reached — or ``None`` without one; a stored spec whose chunks no longer spell the display
    form (a later rename) is ignored."""
    dance_id = word.get("active_dance_id")
    if not dance_id:
        return None
    row = conn.execute("SELECT spec_json, corrected FROM word_dances WHERE id = ? AND status = 'active'", (int(dance_id),)).fetchone()
    if row is None:
        return None
    try:
        spec = json.loads(row[0])
    except (TypeError, ValueError):
        return None
    display = str(word.get("display") or word.get("lemma") or "")
    if not isinstance(spec, dict) or "".join(spec.get("letters") or []) != display:
        return None
    return spec, (None if row[1] is None else int(row[1]))


def active_spec(conn: sqlite3.Connection, word: Mapping[str, Any]) -> dict[str, Any] | None:
    """The stored spec alone (see :func:`active_record`); what the card gets is :func:`spec_for_word`."""
    record = active_record(conn, word)
    return None if record is None else record[0]


def spec_for_word(conn: sqlite3.Connection, word: Mapping[str, Any]) -> dict[str, Any] | None:
    """API.md §9.1: the rule spec of the word (:func:`rule_spec`), overlaid with its stored annotation when it has one — the semantic
    primitive always, the chunks and stress only where Claude corrected the suggestion it was given (``word_dances.corrected``;
    a row the backfill has not reached counts as corrected). A stored row the model merely confirmed therefore follows every later
    improvement of the rules (work·er); the marks are always the rules'. Without a rule spec the stored spec serves as it is;
    without a stored row the rule spec serves (``source: 'rule'``)."""
    rule = rule_spec(conn, word)
    record = active_record(conn, word)
    if record is None:
        return rule
    spec, corrected = record
    if rule is None:
        return spec
    if corrected != 0:
        return {**spec, "marks": rule["marks"]}  # the model's chunks and stress; the letter marks are the rules' whatever the row says
    return {**rule, "semantic": spec.get("semantic"), "source": "claude"}


def store_spec(
    conn: sqlite3.Connection,
    word_id: int,
    spec: Mapping[str, Any],
    *,
    model: str | None,
    prompt_version: str,
    now: str,
    reason: str | None = None,
    corrected: bool | None = None,
) -> int:
    """Insert the new active ``word_dances`` row (``reason`` = the model's short justification, kept for the human review;
    ``corrected`` = whether the model changed the chunks or stress of the rule suggestion, ``None`` only for rows written without that
    knowledge), supersede the previous one and point the word at it (one transaction)."""
    with db.maybe_tx(conn):
        conn.execute("UPDATE word_dances SET status = 'superseded' WHERE word_id = ? AND status = 'active'", (int(word_id),))
        cur = conn.execute(
            "INSERT INTO word_dances(word_id, status, spec_json, model, prompt_version, reason, created_at, corrected) VALUES (?, 'active', ?, ?, ?, ?, ?, ?)",
            (int(word_id), json.dumps(dict(spec), ensure_ascii=False), model, prompt_version, (reason or None), now, None if corrected is None else int(bool(corrected))),
        )
        dance_id = int(cur.lastrowid)
        conn.execute("UPDATE words SET active_dance_id = ?, dance_state = 'ready', updated_at = ? WHERE id = ?", (dance_id, now, int(word_id)))
    return dance_id


def backfill_corrected(conn: sqlite3.Connection) -> int:
    """Fill ``word_dances.corrected`` where it is NULL — every row right after migration 0017 (the file only adds the column) and any
    row written without the flag: 1 when the stored chunks or stress differ from the suggestion the model was given — the ordinary
    rules without the -er hint (which did not exist before 0017), the stress as the prompt sends it (0 when the rules had none) —
    else 0; a word without a rule spec today counts as corrected (its stored chunks keep serving). Called at every service start
    (``main.startup``); returns the number of rows filled."""
    rows = conn.execute(
        "SELECT d.id, d.spec_json, w.display, w.lemma, w.phonetic FROM word_dances d JOIN words w ON w.id = d.word_id WHERE d.corrected IS NULL"
    ).fetchall()
    if not rows:
        return 0
    updates: list[tuple[int, int]] = []
    for dance_id, spec_json, display, lemma, phonetic in rows:
        try:
            spec = json.loads(spec_json)
        except (TypeError, ValueError):
            spec = {}
        if not isinstance(spec, dict):
            spec = {}
        letters = spec.get("letters")
        if not isinstance(letters, list):
            letters = []
        base = spec_for(display or lemma, phonetic)
        corrected = 1 if base is None else int(letters != base["letters"] or spec.get("stress") != suggested_stress(base))
        updates.append((corrected, int(dance_id)))
    with db.maybe_tx(conn):
        conn.executemany("UPDATE word_dances SET corrected = ? WHERE id = ?", updates)
    return len(updates)


def mark_failed(conn: sqlite3.Connection, word_id: int, *, now: str) -> None:
    """The dead-job side effect: ``dance_state = 'failed'`` for a word without a Claude spec (the rule spec keeps serving the card);
    a word that still has an active spec — a dead forced re-annotation — goes back to ``'ready'`` (keyed on ``active_dance_id``,
    like ``content.mark_failed``), so no word is left ``'queued'`` without a live job."""
    with db.maybe_tx(conn):
        conn.execute(
            "UPDATE words SET dance_state = CASE WHEN active_dance_id IS NOT NULL THEN 'ready' ELSE 'failed' END, updated_at = ? WHERE id = ?",
            (now, int(word_id)),
        )


def mark_unattempted(conn: sqlite3.Connection, word_id: int, *, now: str) -> None:
    """A job finished without trying (budget switched off, no rule spec, the word merged or invalidated meanwhile): the state goes
    back to ``'none'`` — or ``'ready'`` when a spec is active — because nothing was attempted and nothing failed."""
    with db.maybe_tx(conn):
        conn.execute(
            "UPDATE words SET dance_state = CASE WHEN active_dance_id IS NOT NULL THEN 'ready' ELSE 'none' END, updated_at = ? WHERE id = ?",
            (now, int(word_id)),
        )


def enqueue_if_needed(
    conn: sqlite3.Connection, word_id: int, *, priority: int, now: str, force: bool = False, cfg: Settings | None = None, operator: bool = False
) -> int | None:
    """``generate_dance`` for a validated, unmerged word that has a rule spec (plain letters + phonetic) and no usable Claude spec
    yet; ``force`` re-annotates a word that already has one. Sets ``dance_state = 'queued'``. Nothing is queued while the dance
    sub-cap is ``0`` (the annotations are switched off — queuing would only churn skipped jobs on every bank action). A word is
    re-queued when its active spec no longer spells the display form (a later rename) or when it is ``'queued'`` without a live
    ``dance:<id>`` job (a group that died on the worker's crash path), restoring the "queued ⇔ live job" invariant.
    ``operator`` marks the operator's own request (``wd dance-annotate``): in AI mode ``split`` (AI_FALLBACK_MODEL §4.3) a
    learner's action queues no Claude work — the rule dance plays until the operator annotates — so without the flag nothing is
    queued there; the flag travels in the payload for the handler's run-time check."""
    settings = cfg if cfg is not None else get_settings()
    if settings.ai_dance_daily_budget_usd <= 0:
        return None
    if not operator and str(getattr(settings, "ai_provider", "") or "") == "split":
        return None
    row = conn.execute(
        "SELECT id, lemma, display, phonetic, is_valid_english, merged_into_word_id, dance_state, active_dance_id FROM words WHERE id = ?",
        (int(word_id),),
    ).fetchone()
    if row is None or row["is_valid_english"] != 1 or row["merged_into_word_id"] is not None:
        return None
    if not force:
        if row["active_dance_id"] and active_spec(conn, dict(row)) is not None:
            return None  # annotated (a stale spec whose chunks no longer spell the display falls through and is redone)
        if (row["dance_state"] or "none") == "queued":
            live = queue.live_job(conn, f"dance:{int(row['id'])}")
            if live is not None:
                if operator:  # the operator's request adopts a learner-queued job (mode split would otherwise skip it)
                    _stamp_operator(conn, int(live.id), now)
                    return int(live.id)
                return None  # a live job already exists
    if spec_for(row["display"] or row["lemma"], row["phonetic"]) is None:
        return None  # phrases, abbreviations with a dot, words without a phonetic: nothing to annotate
    payload: dict[str, Any] = {"word_id": int(row["id"])}
    if force:
        payload["force"] = True
    if operator:
        payload["operator"] = True
    job_id = queue.enqueue(conn, DANCE_JOB, payload, dedupe_key=f"dance:{int(row['id'])}", priority=int(priority), now=now)
    if operator:
        _stamp_operator(conn, int(job_id), now)  # the UPSERT keeps an existing job's payload: the flag must reach it too
    conn.execute("UPDATE words SET dance_state = 'queued', updated_at = ? WHERE id = ?", (now, int(row["id"])))
    return job_id


def _stamp_operator(conn: sqlite3.Connection, job_id: int, now: str) -> None:
    """Marks a queued / running ``generate_dance`` job as the operator's (``payload.operator``), which mode ``split`` runs on Claude."""
    conn.execute(
        "UPDATE jobs SET payload_json = json_set(payload_json, '$.operator', json('true')), updated_at = ? WHERE id = ? AND status IN ('queued', 'running')",
        (now, int(job_id)),
    )
