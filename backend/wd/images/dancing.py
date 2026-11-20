"""跳动图卡 — a Claude drawing the page can animate (docs/releases/2026-11-dancing-cards.md).

Since prompt ``svg-v3`` the model wraps the one part of its picture that may move in ``<g id="actor">``, keeps the lowest
fifth of the canvas a plain ground for the word, and names — as data, never as code — a motion from the closed list
:data:`MOTIONS`, an optional run of letters to light up and an optional memory line. Nothing of that is animation in the
file: :func:`stage_svg` only records the validated choice as ``<desc id="wd-stage">{"v":1,"motion":…,"highlight":…}</desc>``
right after the root tag of the cleaned drawing, and the frontend (``DancingPicture``) plays it from its own keyframe
table and prints the word itself. The ``wd-`` id prefix is ours: an id of that shape written by the model is removed first,
so a stored file carries exactly one such element and its content always went through this function.

:func:`is_dancing` is the recognition rule, the ``memo.is_memo`` pattern: ``provider = 'claude_svg'`` and a
``prompt_version`` that starts with :data:`PROMPT_PREFIX` — no column of its own (``ImageMeta.dancing``).
"""

from __future__ import annotations

import json
import re
from typing import Any
from xml.sax.saxutils import escape

from . import sanitize_svg

PROVIDER = "claude_svg"
PROMPT_PREFIX = "svg-v3"
MOTIONS = ("none", "hop", "rise", "fall", "shiver", "sway", "spin", "pulse", "grow", "shrink", "dash", "float")  # == svg_v1.json `motion`, frontend dancingMotions.ts
STAGE_ID = "wd-stage"
HOOK_MAX_CHARS = 60
RESERVED_ID_RE = re.compile(r'\sid="wd-[^"]*"')  # in a clean() output: attributes are quoteattr()-escaped, one space before each
ACTOR_RE = re.compile(r'<g\b[^>]*\sid="actor"')
ACTOR_ID_RE = re.compile(r'\sid="actor"')


def is_dancing(row: Any) -> bool:
    """Is this ``word_images`` row (a ``sqlite3.Row``, a mapping, or None) a 跳动图卡?"""
    if row is None:
        return False
    try:
        provider, prompt_version = row["provider"], row["prompt_version"]
    except (KeyError, IndexError):
        return False
    return str(provider) == PROVIDER and str(prompt_version or "").startswith(PROMPT_PREFIX)


def highlight_of(display: str, highlight: Any) -> str:
    """The letters to light up: a run of 2+ letters found inside the headword and shorter than it, lower-cased; else ``""``."""
    run = str(highlight or "").strip().lower()
    word = str(display or "").lower()
    return run if 2 <= len(run) < len(word) and run.isalpha() and run in word else ""


def hook_of(hook: Any) -> str | None:
    """``word_images.hook_zh`` of a 跳动图卡: one line, at most :data:`HOOK_MAX_CHARS` characters, None when empty."""
    return " ".join(str(hook or "").split())[:HOOK_MAX_CHARS] or None


def stage_svg(cleaned: str, display: str, *, motion: Any, highlight: Any) -> str:
    """``cleaned`` (a ``sanitize_svg.clean`` output) with the stage record inserted after the root tag. A motion outside
    :data:`MOTIONS`, or a drawing without exactly one ``<g id="actor">``, is recorded as ``none`` — the picture stays still."""
    cleaned = RESERVED_ID_RE.sub("", cleaned)
    chosen = motion if motion in MOTIONS else "none"
    if len(ACTOR_ID_RE.findall(cleaned)) != 1 or not ACTOR_RE.search(cleaned):
        chosen = "none"
    m = sanitize_svg.ROOT_TAG_RE.match(cleaned)
    if not m or m.group(0).endswith("/>"):
        raise sanitize_svg.SvgRejected("stage_svg: no <svg> root with content")
    record = json.dumps({"v": 1, "motion": chosen, "highlight": highlight_of(display, highlight)}, separators=(",", ":"))
    return m.group(0) + f'<desc id="{STAGE_ID}">{escape(record)}</desc>' + cleaned[m.end():]


__all__ = ["HOOK_MAX_CHARS", "MOTIONS", "PROMPT_PREFIX", "STAGE_ID", "highlight_of", "hook_of", "is_dancing", "stage_svg"]
