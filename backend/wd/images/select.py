"""Candidate selection (DESIGN §9 "Selection"): hard rejects, the blocklist, the scoring table and :func:`rank`.

Hard rejects — ``mature``, a non-empty ``unstable__sensitivity``, Commons ``Restrictions``, a licence outside the
allow-list, a MIME type other than jpeg/png/webp, ``width < 400 or height < 300``, an aspect ratio outside
0.6–2.2, a blocklist hit on title / tags / categories / description, an excluded id or URL.

The blocklist is three lists (design/images/SYNTHESIS.md D-images-10, PLAN §5.1 C5): :data:`UNSAFE_RE` always rejects;
:data:`NON_PHOTO_RE` (maps, flags, charts, screenshots, text …) rejects unless the matched word is one of the query's
own tokens — ``map``, ``flag``, ``cover``, ``text`` are 小学 words that must be allowed to find a real map or flag, while a
search for ``apple`` still skips the map; :data:`KID_UNSAFE_RE` rejects only in the ``kid`` style. :func:`is_blocked`
is the one entry point (``ai/content.py`` filters Claude's ``image_keywords`` through it with the lemma's tokens allowed).

Score — +1 per keyword token found in title/tags (max +3), licence cc0/pd +3 · by +2 · by-sa +1 (Pixabay/Pexels
licences +2), aspect 1.2–1.8 +1, width ≥ 800 +1, Commons ``Assessments`` featured/quality/valued +2, filename-like
titles (``IMG_``, ``DSC``, years) −1, an already used image −2. Five signals added by PLAN §5.1 C6 (D-images-12, pure
string checks): a keyword token in the provider ``description`` / ``object_name`` +1 (capped at 1), the provider's own
media category (Openverse ``category``, Pixabay ``type``) matching the round's target +1 / the opposite target −1
(:data:`STYLE_TARGET`: ``kid`` wants ``illustration``/``vector``, ``neutral`` wants ``photograph``/``photo``), a portrait /
people word in title or tags −2 in the ``kid`` style (0 for ``neutral`` — the stock licences only restrict negative
portrayals, the picture-book style simply avoids faces), a signage / caption word −1, a portrait-orientation aspect
(< 1.0) −1 (the 16:10 card frame shows only ≈ 40 % of a tall picture). Minimum score 1.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from ..interfaces import Candidate
from .providers import base

UNSAFE_RE = re.compile(r"\b(nude|nudity|sex|porn|gore|blood|weapon|gun|corpse)\b", re.IGNORECASE)  # always rejected (also for Claude's keywords)
NON_PHOTO_RE = re.compile(r"\b(map|diagram|logo|flag|coat of arms|chart|graph|screenshot|poster|cover|scan|text|document)\b", re.IGNORECASE)  # unless a query token
KID_UNSAFE_RE = re.compile(r"\b(beer|wine|alcohol|cigarette|cigarettes|smoking|horror|zombie|zombies|skull|skulls|knife|knives|bikini|lingerie)\b", re.IGNORECASE)  # style="kid" only
FILENAME_RE = re.compile(r"(^|[\s_\-(])(IMG|DSC|DSCN|DSCF|DCIM|PXL|P\d{7,}|\d{8}_\d{6})([\s_\-)]|\d|$)|\b(19|20)\d{2}\b", re.IGNORECASE)
PEOPLE_RE = re.compile(r"\b(portrait|portraits|selfie|selfies|headshot|close-?up|face|faces|people|person|man|woman|boy|girl)\b", re.IGNORECASE)  # kid −2
TEXTY_RE = re.compile(r"\b(sign|signs|signage|caption|captions|typography|infographic|inscription|banner|banners|label|labels)\b", re.IGNORECASE)  # −1
STYLE_TARGET: dict[str, frozenset[str]] = {"kid": frozenset({"illustration", "vector"}), "neutral": frozenset({"photograph", "photo"})}
TOKEN_RE = re.compile(r"[a-z]+")
STOPWORDS = frozenset({"the", "a", "an", "of", "in", "on", "at", "and", "with", "to", "for", "by", "from", "into", "over"})

ALLOWED_MIMES = frozenset({"image/jpeg", "image/png", "image/webp"})
MIN_WIDTH, MIN_HEIGHT = 400, 300
MIN_ASPECT, MAX_ASPECT = 0.6, 2.2
GOOD_ASPECT = (1.2, 1.8)
GOOD_WIDTH = 800
MIN_SCORE = 1
KEYWORD_HITS_MAX = 3
DESCRIPTION_HITS_MAX = 1
PORTRAIT_ASPECT = 1.0  # below this the picture is taller than wide
ASSESSMENT_WORDS = ("featured", "quality", "valued")
LICENSE_POINTS = {base.LICENSE_CC0: 3, base.LICENSE_BY: 2, base.LICENSE_PERMISSIVE: 2, base.LICENSE_BY_SA: 1}


def is_blocked(text: str | None, *, allow: frozenset[str] = frozenset(), style: str = "neutral") -> bool:
    """True when ``text`` hits the DESIGN §9 blocklist: :data:`UNSAFE_RE` always; :data:`KID_UNSAFE_RE` when ``style`` is
    ``kid``; :data:`NON_PHOTO_RE` unless every matched word is in ``allow`` (the query's own tokens, :func:`keyword_tokens`).
    Also used for Claude's ``image_keywords`` (``ai/content.py``, with the lemma's tokens allowed)."""
    if not text:
        return False
    if UNSAFE_RE.search(text):
        return True
    if style == "kid" and KID_UNSAFE_RE.search(text):
        return True
    return any(m.group(1).lower() not in allow for m in NON_PHOTO_RE.finditer(text))


def keyword_tokens(keyword: str) -> frozenset[str]:
    """The lower-case ASCII tokens of a query (≥ 3 letters, stop-words dropped): the scoring hits and the ``allow`` set of
    :func:`is_blocked` — a search for ``world map`` may accept a map, a search for ``apple`` may not."""
    return frozenset(t for t in TOKEN_RE.findall(keyword.lower()) if len(t) >= 3 and t not in STOPWORDS)


def exclude_keys(cand: Candidate) -> set[str]:
    """The strings an ``exclude`` list may name this candidate by (provider ref, ``provider:ref``, image URL)."""
    return {cand.ref, f"{cand.provider}:{cand.ref}", cand.image_url}


def reject_reason(cand: Candidate, exclude: Iterable[str] = (), *, allow: frozenset[str] = frozenset(), style: str = "neutral") -> str | None:
    """The hard-reject reason for ``cand``, or None when it is acceptable.

    ``allow`` is the query's own token set (:func:`keyword_tokens`) exempted from :data:`NON_PHOTO_RE`; ``style`` ``kid``
    also applies :data:`KID_UNSAFE_RE` (PLAN §5.1 C5)."""
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
    if is_blocked(haystack, allow=allow, style=style):
        return "blocklist"
    if excluded and (exclude_keys(cand) & excluded):
        return "excluded"
    return None


def media_category(cand: Candidate) -> str | None:
    """The provider's own media category, lower-cased: Openverse ``extra.category`` (``photograph`` / ``illustration`` /
    ``digitized_artwork``), Pixabay ``extra.type`` (``photo`` / ``illustration`` / ``vector``, reported as ``vector/svg`` or
    ``vector/ai`` for vector hits — only the part before the slash is the kind); None when absent."""
    for key in ("category", "type"):
        value = cand.extra.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower().split("/", 1)[0]
    return None


def category_points(cand: Candidate, style: str) -> int:
    """+1 when the provider category matches the round's target, −1 when it matches the other style's target, else 0."""
    value = media_category(cand)
    if value is None:
        return 0
    if value in STYLE_TARGET.get(style, frozenset()):
        return 1
    if any(value in targets for other, targets in STYLE_TARGET.items() if other != style):
        return -1
    return 0


def score(cand: Candidate, keyword: str, *, used_refs: Iterable[str] = (), style: str = "neutral") -> int:
    """The DESIGN §9 score (before the minimum-score cut); ``style`` is the round's style (module docstring)."""
    points = 0
    haystack = (cand.title + " " + " ".join(cand.tags)).lower()
    tokens = keyword_tokens(keyword)
    hits = sum(1 for tok in tokens if re.search(r"\b" + re.escape(tok), haystack))
    points += min(KEYWORD_HITS_MAX, hits)
    description = " ".join([str(cand.extra.get("description") or ""), str(cand.extra.get("object_name") or "")]).lower()
    if description.strip():
        desc_hits = sum(1 for tok in tokens if re.search(r"\b" + re.escape(tok), description))
        points += min(DESCRIPTION_HITS_MAX, desc_hits)
    points += LICENSE_POINTS.get(base.license_family(cand.license), 0)
    if cand.width is not None and cand.height is not None and cand.height > 0:
        aspect = cand.width / cand.height
        if GOOD_ASPECT[0] <= aspect <= GOOD_ASPECT[1]:
            points += 1
        if cand.width >= GOOD_WIDTH:
            points += 1
        if aspect < PORTRAIT_ASPECT:
            points -= 1
    assessments = str(cand.extra.get("assessments") or "").lower()
    if any(word in assessments for word in ASSESSMENT_WORDS):
        points += 2
    if cand.title and FILENAME_RE.search(cand.title):
        points -= 1
    points += category_points(cand, style)
    if style == "kid" and PEOPLE_RE.search(haystack):
        points -= 2
    if TEXTY_RE.search(haystack):
        points -= 1
    used = set(used_refs)
    if used and (exclude_keys(cand) & used):
        points -= 2
    return points


def rank(
    cands: Sequence[Candidate],
    keyword: str,
    exclude: Iterable[str] = (),
    *,
    used_refs: Iterable[str] = (),
    allow: frozenset[str] = frozenset(),
    style: str = "neutral",
) -> list[Candidate]:
    """Acceptable candidates sorted best-first (ties keep the provider's order); each gets ``extra['score']``.

    Duplicates by ``(provider, ref)`` or image URL (e.g. two Commons URLs differing only in ``utm_*``, already
    stripped by the provider) collapse to the first occurrence. ``allow`` / ``style`` go to :func:`reject_reason` and
    :func:`score` (the handler passes ``allow=keyword_tokens(keyword)`` and the round's style).
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
        if reject_reason(cand, excluded, allow=allow, style=style) is not None:
            continue
        points = score(cand, keyword, used_refs=used, style=style)
        if points < MIN_SCORE:
            continue
        cand.extra["score"] = points
        scored.append((points, index, cand))
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [c for _, _, c in scored]
