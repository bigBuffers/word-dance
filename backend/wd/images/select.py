"""Candidate selection (DESIGN §9 "Selection"): hard rejects, the blocklist, the scoring table and :func:`rank`.

Hard rejects — ``mature``, a non-empty ``unstable__sensitivity``, Commons ``Restrictions``, a licence outside the
allow-list, a MIME type other than jpeg/png/webp, ``width < 400 or height < 300``, an aspect ratio outside
0.6–2.2, a blocklist hit on title / tags / categories / description, an excluded id or URL.

Score — +1 per keyword token found in title/tags (max +3), licence cc0/pd +3 · by +2 · by-sa +1 (Pixabay/Pexels
licences +2), aspect 1.2–1.8 +1, width ≥ 800 +1, Commons ``Assessments`` featured/quality/valued +2, filename-like
titles (``IMG_``, ``DSC``, years) −1, an already used image −2. Minimum score 1.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from ..interfaces import Candidate
from .providers import base

BLOCKLIST_RE = re.compile(
    r"\b(map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document|"
    r"nude|nudity|sex|porn|gore|blood|weapon|gun|corpse)\b",
    re.IGNORECASE,
)
FILENAME_RE = re.compile(r"(^|[\s_\-(])(IMG|DSC|DSCN|DSCF|DCIM|PXL|P\d{7,}|\d{8}_\d{6})([\s_\-)]|\d|$)|\b(19|20)\d{2}\b", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z]+")
STOPWORDS = frozenset({"the", "a", "an", "of", "in", "on", "at", "and", "with", "to", "for", "by", "from", "into", "over"})

ALLOWED_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
MIN_WIDTH, MIN_HEIGHT = 400, 300
MIN_ASPECT, MAX_ASPECT = 0.6, 2.2
GOOD_ASPECT = (1.2, 1.8)
GOOD_WIDTH = 800
MIN_SCORE = 1
KEYWORD_HITS_MAX = 3
ASSESSMENT_WORDS = ("featured", "quality", "valued")
LICENSE_POINTS = {base.LICENSE_CC0: 3, base.LICENSE_BY: 2, base.LICENSE_PERMISSIVE: 2, base.LICENSE_BY_SA: 1}


def is_blocked(text: str | None) -> bool:
    """True when ``text`` matches the DESIGN §9 blocklist (also used for Claude's ``image_keywords``)."""
    return bool(text) and BLOCKLIST_RE.search(text) is not None


def keyword_tokens(keyword: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(keyword.lower()) if len(t) >= 3 and t not in STOPWORDS]


def exclude_keys(cand: Candidate) -> set[str]:
    """The strings an ``exclude`` list may name this candidate by (provider ref, ``provider:ref``, image URL)."""
    return {cand.ref, f"{cand.provider}:{cand.ref}", cand.image_url}


def reject_reason(cand: Candidate, exclude: Iterable[str] = ()) -> str | None:
    """The hard-reject reason for ``cand``, or None when it is acceptable."""
    excluded = set(exclude)
    if cand.mature:
        return "mature"
    if cand.extra.get("sensitivity"):
        return "sensitivity"
    if str(cand.extra.get("restrictions") or "").strip():
        return "restrictions"
    if not base.license_allowed(cand.license):
        return "license"
    if cand.mime is not None and cand.mime.split(";")[0].strip().lower() not in ALLOWED_MIMES:
        return "mime"
    if cand.width is not None and cand.height is not None:
        if cand.width < MIN_WIDTH or cand.height < MIN_HEIGHT:
            return "size"
        if cand.height <= 0 or not (MIN_ASPECT <= cand.width / cand.height <= MAX_ASPECT):
            return "aspect"
    haystack = " ".join([cand.title or "", *cand.tags, str(cand.extra.get("description") or ""), str(cand.extra.get("object_name") or "")])
    if is_blocked(haystack):
        return "blocklist"
    if excluded and (exclude_keys(cand) & excluded):
        return "excluded"
    return None


def score(cand: Candidate, keyword: str, *, used_refs: Iterable[str] = ()) -> int:
    """The DESIGN §9 score (before the minimum-score cut)."""
    points = 0
    haystack = (cand.title + " " + " ".join(cand.tags)).lower()
    hits = sum(1 for tok in keyword_tokens(keyword) if re.search(r"\b" + re.escape(tok), haystack))
    points += min(KEYWORD_HITS_MAX, hits)
    points += LICENSE_POINTS.get(base.license_family(cand.license), 0)
    if cand.width is not None and cand.height is not None and cand.height > 0:
        aspect = cand.width / cand.height
        if GOOD_ASPECT[0] <= aspect <= GOOD_ASPECT[1]:
            points += 1
        if cand.width >= GOOD_WIDTH:
            points += 1
    assessments = str(cand.extra.get("assessments") or "").lower()
    if any(word in assessments for word in ASSESSMENT_WORDS):
        points += 2
    if cand.title and FILENAME_RE.search(cand.title):
        points -= 1
    used = set(used_refs)
    if used and (exclude_keys(cand) & used):
        points -= 2
    return points


def rank(cands: Sequence[Candidate], keyword: str, exclude: Iterable[str] = (), *, used_refs: Iterable[str] = ()) -> list[Candidate]:
    """Acceptable candidates sorted best-first (ties keep the provider's order); each gets ``extra['score']``.

    Duplicates by ``(provider, ref)`` or image URL (e.g. two Commons URLs differing only in ``utm_*``, already
    stripped by the provider) collapse to the first occurrence.
    """
    excluded = set(exclude)
    used = set(used_refs)
    seen: set[str] = set()
    scored: list[tuple[int, int, Candidate]] = []
    for index, cand in enumerate(cands):
        key = f"{cand.provider}:{cand.ref}"
        if key in seen or cand.image_url in seen:
            continue
        seen.add(key)
        seen.add(cand.image_url)
        if reject_reason(cand, excluded) is not None:
            continue
        points = score(cand, keyword, used_refs=used)
        if points < MIN_SCORE:
            continue
        cand.extra["score"] = points
        scored.append((points, index, cand))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [c for _, _, c in scored]
