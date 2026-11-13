"""记忆图卡 — the picture cards with the word woven in (docs/MEMORY_CARDS_DESIGN.md §3.1–§3.2).

A memory card is ONE 800×500 SVG made of two layers: ``<g id="scene">`` — a complete picture without any text — and, as the
LAST child of the root, ``<g id="word-art">`` — the headword itself in Andika letterforms (one ``<path id="wa-<index>-<char>">``
per letter, an optional ``wa-<index>-<char>-dot`` for a detached i / j dot) plus whatever the memory hook draws around the
letters. The cards are made offline in ``studio/`` and enter through ``wd images-import`` (``images/handler.py``):
:func:`wd.images.store.prepare_memo` cleans and checks a file, :func:`wd.images.store.store_memo` stores what was checked;
nothing online draws one.

What this module owns:

* :func:`is_memo` — the recognition rule: a ``word_images`` row is a memory card ⇔ ``provider = 'claude_svg'`` and
  ``prompt_version`` starts with :data:`PROMPT_PREFIX` (``memo-1`` in this release). No new column, no new provider value:
  the row stays a Claude drawing for every existing reader (``photo_mix``, the caption 「AI 生成示意图」, ``text_free = 1`` —
  the letters are paths, there is no ``<text>``).
* :func:`check_structure` — the import gate of §3.1 on a file that already went through
  ``sanitize_svg.clean(allow_text=False, effects=True)``: the viewBox, the two layers and their order, the ``wa-…`` letter
  paths spelling the headword, the 60 KB limit, the blur budget (:data:`MAX_FILTERED` and its two neighbours — the only
  place that bounds what a card costs to paint), and that the cut below works on this very file and leaves a picture that
  uses nothing the cut took away. It needs no font: whether a ``d`` really is the Andika glyph is the studio validator's job
  (``studio/tools/check.py`` has the font).
* :func:`strip_word_layer` — the second way to serve a card (§3.2, ``GET /media/images/{path}?plain=1``): the same file
  without its word layer. The picture is shown through ``<img>``, so no page script can reach the layer; the server cuts it
  off instead. A cleaned file is canonical — the sanitiser writes ``<`` / ``>`` only as tag delimiters and emits no comment,
  CDATA or processing instruction — and the word layer is the root's last child, so the cut is pure string work: everything
  before ``<g id="word-art"`` plus ``</svg>``. A file where that is not exactly the shape (no such group, two of them, the
  group nested or followed by a sibling) is answered with ``None`` and the route serves it whole.

This file imports nothing from the ``wd`` package on purpose: ``studio/tools/check.py`` loads it by path, next to
``sanitize_svg.py``, in the studio's own virtualenv (fonttools, skia-pathops, defusedxml — no ``wd`` install) — keep it that way.
:data:`MAX_BYTES` therefore repeats ``sanitize_svg.MAX_BYTES`` (pinned by ``test_memo.py``).
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DET

PROMPT_PREFIX = "memo-"  # word_images.prompt_version of a memory card: 'memo-1', later 'memo-2' … (the house style's revision)
PROVIDER = "claude_svg"
VIEWBOX = "0 0 800 500"
MAX_BYTES = 60_000  # = sanitize_svg.MAX_BYTES; a labelled card must still fit
SCENE_ID = "scene"
WORD_LAYER_ID = "word-art"
WORD_LAYER_OPEN = f'<g id="{WORD_LAYER_ID}"'  # how clean() writes the layer's start tag when `id` is its first attribute (the card contract)
LETTER_ID_RE = re.compile(r"wa-(\d+)-(\w)(-dot)?")  # studio/tools/letters.py: wa-<index>-<char>, and -dot for the detached dot of i / j
TAG_RE = re.compile(r"<(/?)[A-Za-z][^<>]*?(/?)>")  # a tag of a cleaned file: (closing slash, self-closing slash)
SVG_END = "</svg>"
# The blur budget of a card — the sanitiser's allow-list has no number in it, and what a filter costs to paint has no ceiling of
# its own. The ten approved cards and the bulk-recipe experiment use at most 7 filtered elements, ONE primitive per filter and a
# stdDeviation of .8–7 (always one number). The per-filter limit is the one that matters: a chain of feDropShadow can double the
# painting time with every link (one full-canvas shape under shadows of 60 and a filter region of three times its box, desktop
# Chrome without GPU raster: 6 → 1 s, 8 → 3 s, 10 → 11 s, 12 → 42 s), so there is no "or so many in the file" beside it. A
# card at all three limits — 16 full-canvas shapes, each under 3 chained shadows of 60 — paints in 1 to 1.5 s there (8 s when
# the 16 are nested in one another under a filter region of thousands of times the canvas: the residue the limits leave). The
# numbers only hold because a cleaned card has no `style` (sanitize_svg, effects mode): CSS would say filter:drop-shadow(…)
# twelve times where nothing here counts.
MAX_FILTERED = 16  # elements whose `filter` is not `none` (studio/STYLE.md asks for ≤ 10 filtered groups, studio/tools/check warns above 14)
MAX_FILTER_PRIMITIVES = 3  # feGaussianBlur / feDropShadow inside one <filter>
MAX_STD_DEVIATION = 60  # either number of a stdDeviation, in user units of the 800×500 canvas
FILTER_PRIMITIVES = frozenset({"feGaussianBlur", "feDropShadow"})  # the two primitives of sanitize_svg.EFFECT_ELEMENTS
STD_DEVIATION_RE = re.compile(r"([0-9]+|[0-9]*\.[0-9]+)(?:(?:\s*,\s*|\s+)([0-9]+|[0-9]*\.[0-9]+))?")  # one or two plain non-negative numbers: no sign, no exponent, no unit
URL_REF_RE = re.compile(r"""url\(\s*['"]?#([^'")\s]+)""")  # the id a fill / stroke / filter / clip-path of a cleaned file points at, in every spelling the sanitiser keeps


def is_memo(row: Any) -> bool:
    """Is this ``word_images`` row (a ``sqlite3.Row``, a mapping, or None) a memory card? ``provider = 'claude_svg'`` and a
    ``prompt_version`` starting with :data:`PROMPT_PREFIX`; a row read before migration 0012 (no ``prompt_version``) is not."""
    if row is None:
        return False
    try:
        provider, prompt_version = row["provider"], row["prompt_version"]
    except (KeyError, IndexError):
        return False
    return provider == PROVIDER and isinstance(prompt_version, str) and prompt_version.startswith(PROMPT_PREFIX)


def strip_word_layer(svg: str) -> str | None:
    """``svg`` without its word layer, or None when the file has no single word layer in the canonical place (module docstring).

    Exactly one ``<g id="word-art"`` must occur, and what follows it must be that one group — balanced to its own ``</g>``, or
    self-closed — and then nothing but ``</svg>``: the layer is a direct child of the root and the last one. Only the tail is
    scanned (a few KB), the picture before it is never parsed."""
    if svg.count(WORD_LAYER_OPEN) != 1:
        return None
    start = svg.index(WORD_LAYER_OPEN)
    depth = 0
    end = -1
    for m in TAG_RE.finditer(svg, start):
        if m.group(1):
            depth -= 1
        elif not m.group(2):
            depth += 1
        if depth <= 0:  # the group's own end tag (or its self-closing start tag): the first tag that brings the depth back to 0
            end = m.end()
            break
    if end < 0 or depth != 0 or svg[end:].strip() != SVG_END:
        return None
    return svg[:start] + SVG_END


def _local(tag: Any) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _is_group(el: ET.Element, group_id: str) -> bool:
    return _local(el.tag) == "g" and el.attrib.get("id") == group_id


def spelled_letters(headword: str) -> str:
    """The characters a card's word layer must spell: the headword's letters and digits in order — spaces, hyphens,
    apostrophes and periods (``ice cream``, ``T-shirt``, ``o'clock``, ``a.m.``) carry no ``wa-…`` path."""
    return "".join(ch for ch in headword if ch.isalnum())


def check_structure(cleaned_svg: str, headword: str) -> list[str]:
    """What is wrong with a cleaned card for ``headword`` (the word's display form), in plain English; ``[]`` when it satisfies
    docs/MEMORY_CARDS_DESIGN.md §3.1:

    * the root ``viewBox`` is ``0 0 800 500``;
    * the root has a direct child ``<g id="scene">`` and its LAST child is ``<g id="word-art">`` (each id once in the file);
    * inside ``#word-art`` the ``<path>`` elements whose id is ``wa-<index>-<char>`` (the ``-dot`` ones aside), read in index
      order, spell exactly the headword's letters and digits (:func:`spelled_letters`) — every index once, the same case;
      a ``wa-…`` id on anything but a path, or outside the word layer (a letter in the scene would survive ``?plain=1``), is a
      problem too;
    * the file is at most :data:`MAX_BYTES` bytes;
    * the blur budget (the comment above :data:`MAX_FILTERED`): at most :data:`MAX_FILTERED` elements carry a ``filter`` other
      than ``none``, no ``<filter>`` holds more than :data:`MAX_FILTER_PRIMITIVES` ``feGaussianBlur`` / ``feDropShadow``, and
      every ``stdDeviation`` is one or two plain numbers from 0 to :data:`MAX_STD_DEVIATION` — a card inside the three paints
      in a second or two on a desktop without GPU raster, one outside them can take a minute or never appear;
    * :func:`strip_word_layer` can cut this file — the guarantee the media route's ``?plain=1`` relies on — and what the cut
      leaves stands on its own: every ``url(#id)`` used outside the word layer names an element outside it. A gradient, clip
      path or filter of the scene that is defined inside ``#word-art`` paints on the full card and is gone from the cut one
      (the layer may keep definitions of its own, and may use the root's). Read on the parsed tree, not by a pattern over
      the text: a ``<title>`` that says ``id="sky"`` defines nothing.

    The input must be a ``sanitize_svg.clean(…, effects=True)`` output (optionally labelled); anything that does not parse is
    reported as the single problem it is."""
    problems: list[str] = []
    size = len(cleaned_svg.encode("utf-8"))
    if size > MAX_BYTES:
        problems.append(f"the cleaned file is {size} bytes, the limit is {MAX_BYTES}")
    try:
        root = DET.fromstring(cleaned_svg, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ET.ParseError, ValueError, SyntaxError) as e:
        return [*problems, f"not well-formed XML: {e}"]
    if root is None or _local(root.tag) != "svg":
        return [*problems, "the root element is not <svg>"]
    viewbox = root.attrib.get("viewBox", "")
    if viewbox != VIEWBOX:
        problems.append(f'viewBox is "{viewbox}", must be "{VIEWBOX}"')

    children = list(root)
    for group_id in (SCENE_ID, WORD_LAYER_ID):
        n = sum(1 for el in root.iter() if el.attrib.get("id") == group_id)
        if n > 1:
            problems.append(f'id "{group_id}" appears {n} times, must be unique')
    if not any(_is_group(el, SCENE_ID) for el in children):
        problems.append(f'no <g id="{SCENE_ID}"> as a direct child of the root <svg>')
    art = children[-1] if children and _is_group(children[-1], WORD_LAYER_ID) else None
    if art is None:
        last = f'<{_local(children[-1].tag)} id="{children[-1].attrib.get("id", "")}">' if children else "nothing"
        where = "it is not the last one" if any(_is_group(el, WORD_LAYER_ID) for el in children) else "there is none among the root's children"
        problems.append(f'<g id="{WORD_LAYER_ID}"> must be the LAST child of the root <svg> (the top layer): {where}; the last child is {last}')

    filtered = sum(1 for el in root.iter() if el.attrib.get("filter", "none").strip() != "none")
    if filtered > MAX_FILTERED:
        problems.append(f"{filtered} elements carry a filter, at most {MAX_FILTERED} may: put the shapes that share a blur into one filtered <g>")
    deviations: dict[str, None] = {}  # one sentence per value and element name, however many primitives repeat it
    for el in root.iter():
        if _local(el.tag) == "filter":
            chained = sum(1 for primitive in el.iter() if _local(primitive.tag) in FILTER_PRIMITIVES)
            if chained > MAX_FILTER_PRIMITIVES:
                problems.append(
                    f'<filter id="{el.attrib.get("id", "")}"> chains {chained} feGaussianBlur / feDropShadow primitives, at most {MAX_FILTER_PRIMITIVES} may: '
                    "use one per filter (a chain of shadows can double the painting time with every link)"
                )
        deviation = el.attrib.get("stdDeviation")
        if deviation is not None:
            m = STD_DEVIATION_RE.fullmatch(deviation)
            if not m or any(float(number) > MAX_STD_DEVIATION for number in m.groups() if number):
                shown = deviation if len(deviation) <= 40 else deviation[:40] + "…"
                deviations[f'stdDeviation="{shown}" on <{_local(el.tag)}>: write one or two plain numbers from 0 to {MAX_STD_DEVIATION} (no unit, no exponent) — the approved cards blur by .8 to 7'] = None
    problems.extend(deviations)

    inside = {id(el) for el in art.iter()} if art is not None else set()
    letters: dict[int, str] = {}
    for el in root.iter():
        el_id = el.attrib.get("id", "")
        m = LETTER_ID_RE.fullmatch(el_id)
        if not m:
            continue
        if id(el) not in inside:
            problems.append(f'{el_id}: a word-art letter outside <g id="{WORD_LAYER_ID}"> (it would stay in the picture without the word)')
            continue
        if _local(el.tag) != "path":
            problems.append(f"{el_id}: a word-art letter must be a <path>, not <{_local(el.tag)}>")
            continue
        if m.group(3):
            continue  # the detached dot of an i / j: part of the letter with the same index
        index = int(m.group(1))
        if index in letters:
            problems.append(f"letter index {index} appears twice ({el_id})")
            continue
        letters[index] = m.group(2)
    if art is not None:
        want = spelled_letters(headword)
        spelled = "".join(letters[i] for i in sorted(letters))
        if not want:
            problems.append(f"the headword {headword!r} has no letter or digit to spell")
        elif spelled != want:
            ids = ", ".join(f"wa-{i}-{letters[i]}" for i in sorted(letters)) or "no wa-<index>-<char> path"
            problems.append(f"word-art spells {spelled!r} ({ids}), expected {want!r} — the letters and digits of {headword!r} in order, one <path id=\"wa-<index>-<char>\"> each")
        if strip_word_layer(cleaned_svg) is None:
            problems.append(f"the word layer cannot be cut off for ?plain=1: write its start tag as {WORD_LAYER_OPEN} …> (id first) and use that id text nowhere else")
        else:  # the cut is the file up to the layer: exactly the elements that are not `inside`
            outside = [el for el in root.iter() if id(el) not in inside]
            missing = {ref for el in outside for value in el.attrib.values() for ref in URL_REF_RE.findall(value)} - {el.attrib.get("id") for el in outside}
            cut = sorted(missing & {el.attrib.get("id") for el in art.iter()})
            if cut:
                problems.append(
                    f'the picture without the word layer (?plain=1) uses {", ".join("#" + ref for ref in cut)}, defined inside <g id="{WORD_LAYER_ID}"> and cut away with it: '
                    f'move the definition{"s" if len(cut) > 1 else ""} to the root <defs>'
                )
            lost = sorted(missing - set(cut))
            if lost:
                problems.append(f'the picture without the word layer uses {", ".join("#" + ref for ref in lost)}, which no element of the file defines: define it in the root <defs> or drop the reference')
    return problems


__all__ = [
    "LETTER_ID_RE", "MAX_BYTES", "MAX_FILTERED", "MAX_FILTER_PRIMITIVES", "MAX_STD_DEVIATION", "PROMPT_PREFIX", "SCENE_ID", "URL_REF_RE", "VIEWBOX", "WORD_LAYER_ID", "WORD_LAYER_OPEN",
    "check_structure", "is_memo", "spelled_letters", "strip_word_layer",
]
