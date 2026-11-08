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
shaped the rules below; what it left to P2's Claude pass is listed there (suffix-aware cuts such as teach·er, heteronyms,
hyphenated words).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = ["DANCE_SPEC_VERSION", "spec_for", "nuclei", "ortho_groups", "split_letters", "silent_letters", "double_letters", "first_variant"]

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


def silent_letters(word: str, phonetic: str) -> list[int]:
    """Indexes of letters the transcription does not sound, by a few safe patterns: kn- wr- wh- (who) h- (hour) tw- (two),
    -mb -mn, gh after a vowel (night, eight, daughter, though — not laugh), the l of -alk/-alf/-alm/-ould, the t of
    -sten/-ften/-stle/-stm-, the w of -sw-, the d of -dn- (Wednesday), and the magic e (final, or internal as in care·ful)
    the split found silent."""
    w = word.lower()
    p = first_variant(phonetic)
    if not p or not _LETTERS_RE.fullmatch(w):
        return []
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
    groups = ortho_groups(w, silent_w="w" not in p, y_between_vowels="j" not in p)
    split = split_letters(w, phonetic)
    final_e = split[2].final_e if split is not None else (_drop_final_e(w, groups) is not None and len(groups) > len(nuclei(phonetic)))
    if final_e:
        out.add(groups[-1][0])
    if split is not None and split[2].dropped is not None:
        out.add(split[2].dropped)
    return sorted(out)


# ----------------------------------------------------------------------------------------------- the spec
def spec_for(display: str | None, phonetic: str | None) -> dict[str, Any] | None:
    """API.md §9 ``DanceSpec`` for a word, or ``None`` when the display is not plain letters or no phonetic is stored."""
    text = (display or "").strip()
    if not text or not _LETTERS_RE.fullmatch(text):
        return None
    phonetic = _PHONETIC_OVERRIDES.get(text.lower(), phonetic)
    if not phonetic or not first_variant(phonetic):
        return None
    nucs = nuclei(phonetic)
    if not nucs:
        return None
    split = split_letters(text, phonetic)
    marks = {"double": double_letters(text), "silent": silent_letters(text, phonetic)}
    if split is None:
        return {"version": DANCE_SPEC_VERSION, "letters": [text], "stress": 0 if len(nucs) == 1 else None, "marks": marks, "source": "rule"}
    letters, used, _reading = split
    stress: int | None = next((i for i, n in enumerate(used) if n.primary), None)
    lower = text.lower()
    if len(letters) > 1 and lower.endswith(("teen", "teenth")):
        # the 13–19 numerals and ordinals stress -teen whatever ECDICT marks (ˌfɪfˈtiːn; 'fif'tiːn, 'θɜːtiːnθ)
        stress = next((i for i, chunk in enumerate(letters) if "teen" in chunk.lower()), stress)
    if stress is None:
        # no mark in the transcription (ʌŋkl): the first chunk whose vowel is not a schwa, else the first
        stress = next((i for i, n in enumerate(used) if n.symbol.rstrip("ː") != "ə"), 0) if len(letters) > 1 else 0
    return {"version": DANCE_SPEC_VERSION, "letters": letters, "stress": stress, "marks": marks, "source": "rule"}
