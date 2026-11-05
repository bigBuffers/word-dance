"""Picture style and the function-word gate (DESIGN §9; design/images/SYNTHESIS.md §3.1.3, PLAN §5.1 C3).

Two questions the image pipeline asks about a word before it draws or searches anything:

* **Which style?** — :func:`style_for` answers ``"kid"`` (picture-book style for 6–11-year-olds, used for the Style line
  of the SVG prompt and for the illustration-first provider round of PLAN §5.1 C8 / DESIGN §9) or ``"neutral"`` (clean
  flat illustration for teenagers and adults). The answer is driven by the word's *stage code*, read from ``words.stage_min``
  through :func:`stage_code`, against ``Settings.image_kid_stages`` (``WD_IMAGE_KID_STAGES``). The default is the empty
  set, so every word is neutral until the pilot of SYNTHESIS §3.6 clears the child style for ``xs``; ``zk`` is never in
  the default (D-images-5: eighth-graders benefit from pictures, not from a picture-book look).
* **Is a picture worth having at all?** — :func:`skip_image`: a word whose *dominant* ECDICT part of speech is a
  function word (preposition, conjunction, determiner, pronoun, article, interjection, infinitive marker) gets the
  template card and no provider request (D-images-9; the live counter-examples are ``despite`` and ``of``). Adverbs are
  not in that gate — ``fast`` and ``today`` are drawable, ``very`` and ``why`` are not, so the pilot decides — but they
  never get a bare-lemma photo search (:func:`allows_bare_lemma`).

``dominant_pos`` is the one way every statistic, sample stratification and gate in this project reads the ``pos``
column (D-images-24): ECDICT's ``pos`` is a share distribution such as ``n:4/v:96`` (``frontend/src/utils/pos.ts``),
so the dominant code is the one with the largest share, never the first token.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..config import Settings
from ..schemas import index_to_stage

STYLE_KID = "kid"
STYLE_NEUTRAL = "neutral"
STYLES: tuple[str, ...] = (STYLE_KID, STYLE_NEUTRAL)

# ECDICT pos codes (the table of frontend/src/utils/pos.ts POS_LABELS): i prep. · c conj. · d det. · p pron. · a art. ·
# u int. · t inf. — no `r` (adverbs, see the module docstring) and no `x` (not a code the seed carries).
FUNCTION_POS: frozenset[str] = frozenset({"i", "c", "d", "p", "a", "u", "t"})
NO_BARE_LEMMA_POS: frozenset[str] = FUNCTION_POS | {"r"}


def dominant_pos(pos: str | None) -> str | None:
    """``'n:4/v:96'`` → ``'v'`` — the code with the largest share; ties keep the first listed.

    ``None``, an empty string and a plain label such as ``'v./n.'`` (Claude-filled words carry labels, not shares) give
    ``None``: the gate then does not fire and the word is treated like any content word.
    """
    if not pos:
        return None
    best_code: str | None = None
    best_share = -1
    for part in str(pos).split("/"):
        code, sep, share = part.strip().partition(":")
        code = code.strip()
        if not sep or not code or not code.isalpha():
            return None  # not a share distribution
        try:
            value = int(share.strip())
        except ValueError:
            return None
        if value > best_share:
            best_code, best_share = code, value
    return best_code


def skip_image(word: Mapping[str, Any]) -> bool:
    """True for a function word (dominant pos in :data:`FUNCTION_POS`): the template card is served, nothing is fetched."""
    return dominant_pos(word.get("pos")) in FUNCTION_POS


def allows_bare_lemma(word: Mapping[str, Any]) -> bool:
    """May the lemma itself be used as a photo search query when no content keyword survives? Adverbs and function
    words: no. An unknown or label-shaped ``pos`` (phrases, Claude words): yes."""
    return dominant_pos(word.get("pos")) not in NO_BARE_LEMMA_POS


def stage_code(stage_min: Any) -> str | None:
    """``words.stage_min`` → stage code.

    An integer index goes through :func:`wd.schemas.index_to_stage` (1 = ``xs`` … 5 = ``cet6`` after migration 0011); a
    string (a stages-as-data schema would store the code itself) is returned as is; ``None`` (a word outside every
    official list) and an out-of-range index give ``None`` — a job must never raise over a stored stage value.
    """
    if stage_min is None or isinstance(stage_min, bool):
        return None
    if isinstance(stage_min, str):
        return stage_min or None
    if isinstance(stage_min, int):
        try:
            return index_to_stage(stage_min)
        except ValueError:
            return None
    return None


def style_for(word: Mapping[str, Any], cfg: Settings) -> str:
    """``kid`` iff the word's stage code is listed in ``cfg.image_kid_stages`` (``WD_IMAGE_KID_STAGES``), else ``neutral``."""
    code = stage_code(word.get("stage_min"))
    return STYLE_KID if code is not None and code in cfg.image_kid_stages else STYLE_NEUTRAL


__all__ = [
    "FUNCTION_POS",
    "NO_BARE_LEMMA_POS",
    "STYLES",
    "STYLE_KID",
    "STYLE_NEUTRAL",
    "allows_bare_lemma",
    "dominant_pos",
    "skip_image",
    "stage_code",
    "style_for",
]
