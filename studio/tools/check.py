#!/usr/bin/env python3
"""check.py — validate, sanitise and render one memory card.

    studio/tools/check studio/cards/moon.svg --word moon     # → studio/clean/moon.svg, studio/png/moon.png, studio/png/moon.sheet.png + a JSON report

What it does, in order:
 1. runs the repository's own SVG sanitiser the way `wd images-import` runs it — `wd.images.sanitize_svg.clean(raw,
    allow_text=False, effects=True)` (docs/MEMORY_CARDS_DESIGN.md §3.1) — and reports everything it DROPPED: what you see
    in the render is exactly what the app would serve;
 2. runs the repository's structure check for a memory card, `wd.images.memo.check_structure(cleaned, word)` — viewBox
    0 0 800 500, a <g id="scene">, <g id="word-art"> as the LAST child of the root, the `wa-<index>-<letter>` paths spell
    the headword, ≤ 60 KB, the blur budget (how many elements carry a filter, how many primitives one filter chains, how
    far a stdDeviation goes — the three numbers are memo.py's, not repeated here), and the word layer can be cut off whole,
    leaving a picture that uses no gradient, filter or clip path defined inside it (the picture the app serves when
    「图片上显示单词」 is off). It is the very gate the import applies, so a card that passes here is not turned away there;
 3. adds what only the studio can check, because only the studio has the font: every word-art letter is a genuine glyph
    from letters.py (the `d` pasted unchanged) AND still one on the canvas — a transform may move it, scale it with one
    factor and tip it a few degrees, never mirror, flip, stretch, skew or turn it over; it is painted (fill / stroke /
    opacity / display / visibility, read through the groups around it — attributes are all there is to read: step 1
    dropped every `style` and said so), its ink stays
    inside the canvas; the letters run left to right and are big enough to read on a phone; a path under the dot's id
    is the dot of an i / j only when it is the font's dot in its place; plus the house-keeping the sanitiser does not
    do (duplicate ids, a url(#…) that points at no id — anywhere in the file, the word layer included, where the gate of
    step 2 answers only for the picture without it) and the softer advice on blur — a warning above :data:`MAX_BLURRED` filtered
    elements, before the gate's limit turns the card away;
 4. renders the cleaned file with headless Chrome: png/<name>.png (800×500) and png/<name>.sheet.png (the scene without
    the word-art + the phone-size view, 360 px wide), and one png/<name>.zoom<N>.png per --zoom. A page Chrome did not
    write is an error (run the check again), and the report lists only the files that exist.

Exit status 0 = no errors (warnings may remain); 1 = errors; 2 = the tool itself cannot run (bad arguments, the
repository's sanitiser not loadable). Always read the report AND look at the PNGs.

Every path is derived from this file's own location (studio/tools/ → the repository root), so the tool works from any
working directory and in any checkout; the one machine-specific constant is :data:`CHROME`.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import NoReturn
from xml.etree import ElementTree as ET

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as DET

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent
REPO = STUDIO.parent
BACKEND = REPO / "backend"
TMP = STUDIO / "tmp"  # render scaffolding (the html pages Chrome shoots, throwaway profiles) — gitignored, safe to delete
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"  # the renderer; edit here when Chrome lives elsewhere
TARGET_BYTES = 45_000
MAX_BLURRED = 14     # elements carrying filter="url(…)" before the old-tablet warning (STYLE.md §5 asks for ≤ 10); the limit that refuses a card is the import's own, memo.MAX_FILTERED
MIN_FONT_PX = 64.0   # smallest allowed em size of a word-art letter on the 800-wide canvas
WARN_FONT_PX = 76.0
EDGE_WARN_PX = 20.0  # ink of a word-art letter closer than this to the canvas edge is a warning (the handbook asks for 30 px; the approved cards come as close as 29.8); ink beyond the edge is an error
TILT_FREE_DEG = 5.0  # a letter may be tipped this far without a word: the pilot recipe tips each chunk ∓2.5° at the seam, a hook may lean one letter a little
TILT_MAX_DEG = 15.0  # up to here a tilt is a warning (the handbook wants upright letters, the illustrator may have a reason); beyond it the letter no longer stands — an error

sys.path.insert(0, str(HERE))
import letters as letters_tool  # noqa: E402


# ---------------------------------------------------------------- the repository's sanitiser and structure check
def load_backend() -> tuple[types.ModuleType, types.ModuleType]:
    """``(wd.images.sanitize_svg, wd.images.memo)`` — the repository's own files, the ones `wd images-import` runs.

    They are loaded under two bare package objects instead of through ``import wd.images``: ``wd/images/__init__.py``
    imports the whole image pipeline (pydantic, httpx, Pillow …) and the studio's virtualenv has only fonttools,
    skia-pathops and defusedxml (both modules are kept importable with defusedxml alone for exactly this caller — memo.py
    says so). Same files, same module names, no private copy of any rule: when the backend changes what a card may
    contain, this tool changes with it. A real ``wd`` package the caller already imported is used as it is.

    There is deliberately no fallback: a checkout whose backend cannot clean with ``effects=True`` or has no
    ``memo.check_structure`` cannot import a memory card either, and a studio verdict made up from rules of its own would
    be worth nothing — the tool stops (exit status 2) and says which piece is missing.
    """
    for name, path in (("wd", BACKEND / "wd"), ("wd.images", BACKEND / "wd" / "images")):
        if name not in sys.modules:
            pkg = types.ModuleType(name)
            pkg.__path__ = [str(path)]  # type: ignore[attr-defined]
            sys.modules[name] = pkg
    try:
        san = importlib.import_module("wd.images.sanitize_svg")
        memo = importlib.import_module("wd.images.memo")
    except ImportError as e:
        die(f"cannot load the repository's sanitiser / structure check from {BACKEND / 'wd' / 'images'}: {e!r} — this checkout needs "
            "backend/wd/images/sanitize_svg.py and memo.py (docs/MEMORY_CARDS_DESIGN.md §3.1), and the tool runs under studio/.venv "
            "(studio/requirements.txt: fonttools, skia-pathops, defusedxml) — use the wrapper studio/tools/check")
    if "effects" not in inspect.signature(san.clean).parameters or not callable(getattr(memo, "check_structure", None)):
        die(f"{BACKEND / 'wd' / 'images'} has no sanitize_svg.clean(…, effects=True) or no memo.check_structure — this checkout "
            "predates the memory cards (docs/MEMORY_CARDS_DESIGN.md §3.1); nothing was checked")
    return san, memo


def die(message: str) -> NoReturn:
    """The tool cannot do its job (not: the card is bad) — one line on stderr, exit status 2, no report."""
    print(f"check.py: {message}", file=sys.stderr)
    sys.exit(2)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def census(root: ET.Element) -> tuple[dict[str, int], dict[str, int]]:
    els: dict[str, int] = {}
    attrs: dict[str, int] = {}
    for el in root.iter():
        els[local(el.tag)] = els.get(local(el.tag), 0) + 1
        for k in el.attrib:
            k = local(k)
            attrs[k] = attrs.get(k, 0) + 1
    return els, attrs


# ---------------------------------------------------------------- path + transform helpers
NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
CMD_RE = re.compile(r"([MLHVQCZTSAmlhvqcztsa])([^MLHVQCZTSAmlhvqcztsa]*)")
ARITY = {"M": 2, "L": 2, "Q": 4, "C": 6, "H": 1, "V": 1, "Z": 0}


def parse_path(d: str) -> list[tuple[str, list[float]]] | None:
    """Absolute M L H V Q C Z only (what letters.py emits); H/V become L. None when anything else appears."""
    out: list[tuple[str, list[float]]] = []
    x = y = 0.0
    for cmd, rest in CMD_RE.findall(d or ""):
        if cmd not in ARITY:
            return None
        nums = [float(n) for n in NUM_RE.findall(rest)]
        n = ARITY[cmd]
        if n == 0:
            out.append(("Z", []))
            continue
        if not nums or len(nums) % n:
            return None
        for k in range(0, len(nums), n):
            seg = nums[k : k + n]
            if cmd == "H":
                x = seg[0]; out.append(("L", [x, y]))
            elif cmd == "V":
                y = seg[0]; out.append(("L", [x, y]))
            else:
                x, y = seg[-2], seg[-1]
                out.append(("L" if (cmd == "M" and k > 0) else cmd, seg))
    return out


def pts_of(segs) -> list[tuple[float, float]]:
    pts = []
    for _, c in segs:
        pts.extend((c[i], c[i + 1]) for i in range(0, len(c), 2))
    return pts


def bbox_of(pts) -> tuple[float, float, float, float]:
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def mat_mul(a, b):
    return (a[0] * b[0] + a[2] * b[1], a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3], a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5])


def parse_transform(value: str | None):
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for name, args in re.findall(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)", value or ""):
        a = [float(n) for n in NUM_RE.findall(args)]
        if name == "matrix" and len(a) == 6:
            t = tuple(a)
        elif name == "translate" and a:
            t = (1, 0, 0, 1, a[0], a[1] if len(a) > 1 else 0.0)
        elif name == "scale" and a:
            t = (a[0], 0, 0, a[1] if len(a) > 1 else a[0], 0, 0)
        elif name == "rotate" and a:
            r = math.radians(a[0]); c, s = math.cos(r), math.sin(r)
            t = (c, s, -s, c, 0, 0)
            if len(a) == 3:
                t = mat_mul(mat_mul((1, 0, 0, 1, a[1], a[2]), t), (1, 0, 0, 1, -a[1], -a[2]))
        elif name == "skewX" and a:
            t = (1, 0, math.tan(math.radians(a[0])), 1, 0, 0)
        elif name == "skewY" and a:
            t = (1, math.tan(math.radians(a[0])), 0, 1, 0, 0)
        else:
            continue
        m = mat_mul(m, t)
    return m


def apply(m, p):
    return (m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5])


def lineage(el: ET.Element, parent: dict) -> list[ET.Element]:
    """``el`` and every element around it, innermost first — what a composed transform and an inherited attribute are read from."""
    chain = []
    node = el
    while node is not None:
        chain.append(node)
        node = parent.get(node)
    return chain


def composed(chain: list[ET.Element]):
    """The matrix that takes the coordinates of ``chain[0]`` to the canvas: every `transform` from the root down to the element."""
    m = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for node in reversed(chain):
        m = mat_mul(m, parse_transform(node.attrib.get("transform")))
    return m


# ---------------------------------------------------------------- is it painted? (presentation attributes, the way a renderer resolves them)
def inherited(chain: list[ET.Element], name: str, default: str) -> str:
    """The value an inherited presentation attribute has on ``chain[0]``: its own, else the nearest group's, else the SVG default."""
    for node in chain:
        value = node.attrib.get(name, "").strip()
        if value and value.lower() != "inherit":
            return value
    return default


def is_zero(value: str) -> bool:
    m = NUM_RE.match(value.strip())  # 0, 0.0, .0, 0%, 0px
    return m is not None and float(m.group()) == 0.0


def unseen(chain: list[ET.Element]) -> str | None:
    """Why the element ``chain[0]`` paints nothing, or None when it is drawn.

    `display="none"` and `opacity="0"` on the element or on ANY group around it take everything inside away, and what sits
    in <defs> or a <clipPath> is never painted itself. `visibility`, `fill` (default black), `stroke` (default none),
    their opacities and `stroke-width` are inherited: the nearest element that sets one decides — so a ghost letter that
    only says `fill="none"` inside a chunk group carrying the dashed keyline IS drawn, and a letter under `<g fill="none">`
    with no stroke anywhere is not. Only attributes are read, and on a cleaned card there is nothing else: the sanitiser's
    memory-card mode drops every `style` attribute (main() reports each as dropped), so no CSS can repaint or hide a
    letter behind this function's back."""
    for node in chain:
        where = "on the letter" if node is chain[0] else "on a group around it"
        if local(node.tag) in ("defs", "clipPath"):
            return f"inside <{local(node.tag)}>, which is never painted itself — the path that carries the letter's id must be the one the card draws"
        if node.attrib.get("display", "").strip().lower() == "none":
            return f'display="none" {where}'
        if is_zero(node.attrib.get("opacity", "")):
            return f'opacity="0" {where}'
    if inherited(chain, "visibility", "visible").lower() in ("hidden", "collapse"):
        return 'visibility="hidden" on the letter or inherited from a group around it'
    filled = inherited(chain, "fill", "black").lower() not in ("none", "transparent") and not is_zero(inherited(chain, "fill-opacity", "1"))
    stroked = inherited(chain, "stroke", "none").lower() not in ("none", "transparent") and not is_zero(inherited(chain, "stroke-width", "1")) and not is_zero(inherited(chain, "stroke-opacity", "1"))
    return None if filled or stroked else "no fill, no stroke"


# ---------------------------------------------------------------- the glyph check (needs the font: the studio's own part)
_REF_CACHE: dict[str, dict] = {}


def reference(ch: str) -> list[dict]:
    """The genuine outlines of ``ch``: the merged overlap-free one letters.py emits now, then the font's raw contours (the first ten cards)."""
    if ch not in _REF_CACHE:
        font = letters_tool.load_font(letters_tool.DEFAULT_FONT)
        entries = []
        for simplify in (True, False):
            full = letters_tool.layout(font, ch, size=1000, x=0, baseline=0, anchor="start", track=0, chunks=None, gap=0, split_dots=False, prefix="r", simplify=simplify)["letters"][0]
            entry = {"full": parse_path(full["d"]), "body": None, "dot": None}
            if ch in "ij":
                sp = letters_tool.layout(font, ch, size=1000, x=0, baseline=0, anchor="start", track=0, chunks=None, gap=0, split_dots=True, prefix="r", simplify=simplify)["letters"][0]
                entry["body"] = parse_path(sp["d"])
                entry["dot"] = parse_path(sp["dot"]["d"]) if "dot" in sp else None
            entries.append(entry)
        _REF_CACHE[ch] = entries
    return _REF_CACHE[ch]


def fit(cand, ref) -> float | None:
    """Uniform scale s with cand ≈ s·ref + t (same commands, coordinates within tolerance), else None."""
    if cand is None or ref is None or [c for c, _ in cand] != [c for c, _ in ref]:
        return None
    cp, rp = pts_of(cand), pts_of(ref)
    cb, rb = bbox_of(cp), bbox_of(rp)
    rh = max(rb[3] - rb[1], rb[2] - rb[0])
    ch = max(cb[3] - cb[1], cb[2] - cb[0])
    if rh <= 0 or ch <= 0:
        return None
    use_h = (rb[3] - rb[1]) >= (rb[2] - rb[0])
    s = ((cb[3] - cb[1]) / (rb[3] - rb[1])) if use_h else ((cb[2] - cb[0]) / (rb[2] - rb[0]))
    tx, ty = cb[0] - s * rb[0], cb[1] - s * rb[1]
    tol = max(0.8, 0.02 * ch)
    for (cx, cy), (rx, ry) in zip(cp, rp):
        if abs(cx - (s * rx + tx)) > tol or abs(cy - (s * ry + ty)) > tol:
            return None
    return s


def check_word_art(root: ET.Element, memo: types.ModuleType, errors: list[str], warnings: list[str]) -> dict:
    """The font-dependent half of the word-art contract: each `wa-<index>-<letter>` path under the root's
    `<g id="word-art">` IS the Andika glyph of its letter and is still one where the card puts it.

    * The `d` is the glyph letters.py prints (any uniform scale and position, nothing else).
    * The transforms on the letter and on the groups around it, composed, may move it, scale it by ONE factor and tip it:
      up to :data:`TILT_FREE_DEG` silently, up to :data:`TILT_MAX_DEG` with a warning. A mirror or a flip (b ↔ d, p ↔ q),
      two different factors, a skew, a letter lying down or standing on its head are errors — every `d` is still the
      pasted glyph there, and the pupil copies what the card shows. sqrt(|det|) alone, which the size is measured with,
      cannot tell any of them from a uniform scale.
    * CSS could do all of the above, and hide or recolour the letter, where this check does not look — but ``root`` is a
      cleaned card, and `sanitize_svg.clean(…, effects=True)` keeps no `style` attribute at all: one written on a letter
      or on a group around it is gone before this function runs and is reported by main() among the dropped attributes
      (the import drops it the same way), so there is no rule about `style` here.
    * The letter is painted — :func:`unseen` — and its ink box (the four corners through the transform, the genuine dot of
      an i / j included) lies inside the canvas: beyond the edge is an error, within :data:`EDGE_WARN_PX` a warning.
    * The letters' centres run left to right in index order, none is smaller than :data:`MIN_FONT_PX` em.
    * An i / j pasted without its dot (`letters --split-dots`) is a warning unless `wa-<index>-<letter>-dot` is the font's
      dot: stem + dot fit the reference's stem + dot in ONE :func:`fit` (shape, size and the offset between the two), the
      dot is moved by the same transform as the stem, and it is painted. Just a warning either way — a drawn object may
      stand in for the dot, and only the render shows whether it does.

    WHICH letters must be there — the spelling, one path per index, a letter id on nothing but a path, the group being
    the root's last child — is `memo.check_structure`, not repeated here: a misspelt card is reported once, in the words
    the import would use. What a letter id looks like is the backend's definition too (`memo.LETTER_ID_RE`).
    """
    info: dict = {}
    parent = {c: p for p in root.iter() for c in p}
    art = None
    for el in root:
        if local(el.tag) == "g" and el.attrib.get("id") == memo.WORD_LAYER_ID:
            art = el
    if art is None:
        return info
    found: list[tuple[int, str, ET.Element]] = []
    dots: dict[int, ET.Element] = {}
    for el in art.iter():
        m = memo.LETTER_ID_RE.fullmatch(el.attrib.get("id", ""))
        if not m or local(el.tag) != "path":
            continue
        if m.group(3):
            dots.setdefault(int(m.group(1)), el)
        else:
            found.append((int(m.group(1)), m.group(2), el))
    found.sort(key=lambda f: f[0])
    width, height = (float(v) for v in memo.VIEWBOX.split()[2:])  # the canvas the structure check demands: 800 × 500
    sizes = []
    centres = []
    boxes: list[tuple[str, tuple[float, float, float, float]]] = []
    for idx, ch, el in found:
        name = f"wa-{idx}-{ch}"
        try:
            refs = reference(ch)
        except SystemExit:  # letters.py: the font has no glyph for this character
            errors.append(f"{name}: the house font has no glyph for {ch!r}")
            continue
        cand = parse_path(el.attrib.get("d", ""))
        s = None
        dotless = False
        for ref in refs:  # the overlap-free outline first, then the raw contours of the first ten cards
            s = fit(cand, ref["full"])
            if s is None and ref.get("body") is not None:
                s = fit(cand, ref["body"])
                dotless = s is not None
            if s is not None:
                break
        if s is None:
            errors.append(f"{name}: the path data is not the glyph letters.py produces for {ch!r} — paste the d unchanged (use transform to move or uniformly scale a letter)")
            continue
        chain = lineage(el, parent)
        m = composed(chain)
        ink = pts_of(cand)
        if dotless:
            dot = dots.get(idx)
            dot_segs = parse_path(dot.attrib.get("d", "")) if dot is not None else None
            dot_chain = lineage(dot, parent) if dot is not None else []
            if dot is None:
                warnings.append(f"{name}: dotless glyph — make sure a drawn object sits exactly where the dot was (check the render)")
            elif (dot_segs and any(ref["dot"] and fit(cand + dot_segs, ref["body"] + ref["dot"]) is not None for ref in refs if ref.get("body"))
                  and max(abs(p - q) for p, q in zip(composed(dot_chain), m)) < 1e-6 and unseen(dot_chain) is None):
                ink = ink + pts_of(dot_segs)  # the font's dot, where the font puts it, moved with its stem and painted: part of the letter
            else:
                warnings.append(f"{name}: dotless glyph — the path {name}-dot is not the font's dot in its place (reshaped, moved apart from its letter, hidden or empty); "
                                "make sure a drawn object sits exactly where the dot was (check the render)")
        # what the composed transform does to the letterform: [la lc; lb ld] is a uniform scale times a rotation ⇔ la = ld and lb = −lc
        la, lb, lc, ld = m[:4]
        sdet = la * ld - lb * lc
        k = math.sqrt(abs(sdet))
        tilt = round(math.degrees(math.atan2(lb, la)), 1)  # the angle rotate() was given (positive turns the letter clockwise on the canvas), to the digit a card writes: a 5° tip spelled as matrix(.9962 .0872 …) is 5°
        linear = " ".join(f"{round(v, 3):g}" for v in (la, lb, lc, ld))
        allowed = "a transform may move a letter, scale it by ONE factor and tip it a few degrees, nothing else"
        if sdet <= 0:
            errors.append(f"{name}: mirrored by the transform on it or on a group around it (matrix a b c d = {linear}) — a mirrored or flipped letter is another letter (b / d, p / q) or none; {allowed}")
        elif abs(la - ld) > 0.02 * k or abs(lb + lc) > 0.02 * k:
            errors.append(f"{name}: stretched, squashed or skewed by the transform on it or on a group around it (matrix a b c d = {linear}) — {allowed}; "
                          "for another size call tools/letters again with another --size")
        elif abs(tilt) > TILT_MAX_DEG:
            errors.append(f"{name}: turned {tilt:g}° by the transform on it or on a group around it — word-art letters stand upright on a flat baseline; {allowed}")
        elif abs(tilt) > TILT_FREE_DEG:
            warnings.append(f"{name}: tilted {tilt:g}° — the handbook asks for upright letters on a flat baseline; keep the tilt only if the hook needs it (beyond {TILT_MAX_DEG:g}° it is an error)")
        why = unseen(chain)
        if why:
            errors.append(f"{name}: invisible letter ({why})")
        px = s * 1000.0 * k
        b = bbox_of(pts_of(cand))
        cx, cy = apply(m, ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2))
        sizes.append(px)
        centres.append((idx, ch, round(cx, 1), round(cy, 1)))
        b = bbox_of(ink)
        corners = [apply(m, p) for p in ((b[0], b[1]), (b[2], b[1]), (b[0], b[3]), (b[2], b[3]))]
        boxes.append((name, (min(p[0] for p in corners), min(p[1] for p in corners), max(p[0] for p in corners), max(p[1] for p in corners))))
    xs = [c[2] for c in centres]
    if any(b <= a for a, b in zip(xs, xs[1:])):
        errors.append(f"word-art letters are not in left-to-right reading order: {centres}")
    ink_bbox = [round(v, 1) for v in (min(b[0] for _, b in boxes), min(b[1] for _, b in boxes), max(b[2] for _, b in boxes), max(b[3] for _, b in boxes))] if boxes else None
    if boxes:
        slack = 0.05  # half the last digit a card writes: a letter laid exactly on the edge is not "beyond" it for a rounding's sake
        cut = [name for name, b in boxes if b[0] < -slack or b[1] < -slack or b[2] > width + slack or b[3] > height + slack]
        near = [name for name, b in boxes if name not in cut and (b[0] < EDGE_WARN_PX or b[1] < EDGE_WARN_PX or b[2] > width - EDGE_WARN_PX or b[3] > height - EDGE_WARN_PX)]
        if cut:
            errors.append(f"word-art letters cut by the canvas edge: {', '.join(cut)} (the word's ink box is {ink_bbox}, the canvas {memo.VIEWBOX}) — move the word inside, 30 px clear of the edges")
        if near:
            warnings.append(f"word-art letters within {EDGE_WARN_PX:g} px of the canvas edge: {', '.join(near)} (the word's ink box is {ink_bbox}) — keep the word 30 px clear of the edges")
    if sizes:
        info["letter_em_px"] = [round(v, 1) for v in sizes]
        if min(sizes) < MIN_FONT_PX:
            errors.append(f"smallest word-art letter is {min(sizes):.0f} px em — below the {MIN_FONT_PX:.0f} px minimum (unreadable on a phone)")
        elif min(sizes) < WARN_FONT_PX:
            warnings.append(f"smallest word-art letter is {min(sizes):.0f} px em — {WARN_FONT_PX:.0f}+ is preferred unless the word is long")
    info["letter_centres"] = centres
    if ink_bbox:
        info["ink_bbox"] = ink_bbox  # [x0, y0, x1, y1] of the word on the canvas, through every transform — the name letters.py uses
    return info


# ---------------------------------------------------------------- render
def chrome_shot(url: str, out: Path, w: int, h: int) -> None:
    """One headless screenshot; ``out`` is absent afterwards when Chrome failed or timed out (a stale PNG never passes for a new one)."""
    out.unlink(missing_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    prof = tempfile.mkdtemp(prefix="chrome-", dir=str(TMP))
    try:
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", "--run-all-compositor-stages-before-draw", f"--user-data-dir={prof}",
                        f"--window-size={w},{h}", f"--screenshot={out}", url], capture_output=True, timeout=90, check=False)
    except (subprocess.TimeoutExpired, OSError):
        pass
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def lost(png: Path) -> str:
    """The error for a page Chrome did not write — the card, its sheet or a zoom, each named. A missing sheet or zoom used
    to be a quiet ``null`` (or a listed file that was not there) beside ``ok: true``, and a batch keyed on the exit status
    went on without the scene-only / phone-size view and the face and hand zooms the handbook makes everybody look at."""
    return f"render failed: {png.name} was not written (Chrome crashed or timed out on that page — run the check again)"


URL_REF_RE = re.compile(r"""url\(\s*(['"]?)#([^)'"\s]+)\1\s*\)""")  # a local reference in every spelling the sanitiser lets through: url(#a), url('#a'), url("#a"), url( #a )


def reid(svg: str, suffix: str) -> str:
    """Every id of a cleaned ``svg`` — and every `url(#id)` that points at one — gets ``suffix``, so that several cards, or
    two copies of one, can stand in the same page: the sheet shows a card twice, the gallery page shows them all, and
    every card calls its sky gradient `sky`. A reference is found in each spelling the sanitiser keeps (:data:`URL_REF_RE`)
    and written back in the plain one; with the suffix on the ids alone a quoted reference dangles and its shape goes
    unpainted — two empty panels beside a perfect PNG. build_gallery.py calls this very function."""
    svg = re.sub(r'\bid="([^"]+)"', lambda m: f'id="{m.group(1)}{suffix}"', svg)
    return URL_REF_RE.sub(lambda m: f"url(#{m.group(2)}{suffix})", svg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svg")
    ap.add_argument("--word", default="", help="the headword exactly as displayed, e.g. breakfast (required unless --sheet)")
    ap.add_argument("--out-dir", default="", help="where clean/ and png/ live (default: next to the svg's parent dir, e.g. studio/cards/x.svg → studio/clean/, studio/png/)")
    ap.add_argument("--no-render", action="store_true", help="validate and write clean/<name>.svg only (no Chrome needed)")
    ap.add_argument("--zoom", action="append", default=[], metavar="X,Y,W,H", help="also render an enlarged crop of this canvas region to png/<name>.zoom<N>.png (repeatable) — use it to inspect faces, hands, letters")
    ap.add_argument("--sheet", action="store_true", help="not a card (e.g. the cast sheet): sanitise + render only, skip the card contract and the word-art checks; any viewBox")
    a = ap.parse_args()
    if not a.sheet and not a.word:
        ap.error("--word is required (or pass --sheet)")
    src = Path(a.svg).resolve()
    if not src.is_file():
        ap.error(f"no such file: {src}")
    base = Path(a.out_dir).resolve() if a.out_dir else src.parent.parent
    name = src.stem
    clean_dir, png_dir = base / "clean", base / "png"
    errors: list[str] = []
    warnings: list[str] = []
    report: dict = {"file": str(src), "word": a.word}
    raw = src.read_text(encoding="utf-8")
    report["raw_bytes"] = len(raw.encode("utf-8"))
    tmp_tag = f"{name}-{hashlib.md5(str(src).encode()).hexdigest()[:8]}"  # two cards of the same word in different directories render concurrently
    san, memo = load_backend()
    try:
        raw_root = DET.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)  # a drawing is model output: never expand entities
    except (ET.ParseError, DefusedXmlException, ValueError) as e:
        print(json.dumps({"ok": False, "errors": [f"not well-formed XML (or it declares a DOCTYPE / entities): {e!r}"]}, ensure_ascii=False, indent=1))
        return 1
    try:
        cleaned = san.clean(raw, allow_text=False, effects=True)  # exactly the import's call (wd.images.store.prepare_memo)
    except san.SvgRejected as e:
        print(json.dumps({"ok": False, "errors": [f"sanitiser rejected the file: {e}"]}, ensure_ascii=False, indent=1))
        return 1
    clean_root = ET.fromstring(cleaned)
    re_els, re_attrs = census(raw_root)
    ce_els, ce_attrs = census(clean_root)
    dropped_els = {k: v - ce_els.get(k, 0) for k, v in re_els.items() if v - ce_els.get(k, 0) > 0}
    dropped_attrs = {k: v - ce_attrs.get(k, 0) for k, v in re_attrs.items() if v - ce_attrs.get(k, 0) > 0 and k not in ("width", "height", "version")}
    if dropped_els:
        errors.append(f"the sanitiser DROPPED these elements (with their subtrees): {dropped_els} — the allowed elements are listed in studio/STUDIO.md §1 (no text / tspan, image, use, mask, pattern, style, script …)")
    if dropped_attrs:
        errors.append(f"the sanitiser DROPPED these attributes: {dropped_attrs} (no href / style / on* / data-* / class, no backslash in a value; url(#id) only in fill, stroke, filter, clip-path) — "
                      "write presentation attributes (fill, stroke, opacity, transform …), the import drops the same")
    report["clean_bytes"] = len(cleaned.encode("utf-8"))
    report["elements"] = sum(ce_els.values())
    if report["clean_bytes"] > TARGET_BYTES:
        warnings.append(f"cleaned file is {report['clean_bytes']} bytes — target ≤ {TARGET_BYTES}, hard limit {san.MAX_BYTES}")
    vb = clean_root.attrib.get("viewBox", "")
    if not a.sheet:
        errors.extend(memo.check_structure(cleaned, a.word))  # the import's gate, in the import's words
        stray = [local(el.tag) for el in clean_root if local(el.tag) not in ("g", "defs", "title", "desc")]
        if stray:
            warnings.append(f"shapes directly under the root {stray}: put every drawn shape inside #scene or #word-art")
    all_ids = [el.attrib["id"] for el in clean_root.iter() if "id" in el.attrib]
    dup = sorted({i for i in all_ids if all_ids.count(i) > 1})
    if dup:
        errors.append(f"duplicate ids: {dup}")
    refs = set(re.findall(r"url\(\s*['\"]?#([^)'\"\s]+)", cleaned))
    missing = sorted(refs - set(all_ids))
    if missing:
        errors.append(f"url(#…) references with no matching id: {missing}")
    if not a.sheet:
        report["word_art"] = check_word_art(clean_root, memo, errors, warnings)
    blur = ce_els.get("feGaussianBlur", 0)
    blurred = sum(1 for el in clean_root.iter() if el.attrib.get("filter", "").lstrip().startswith("url("))  # counted on the tree: the sanitiser writes filter='url("#b")' in single quotes
    report["blur_filters"] = blur
    report["blurred_elements"] = blurred
    if blurred > MAX_BLURRED:
        warnings.append(f"{blurred} elements use a blur filter — keep it to about a dozen (group shapes under one filtered <g>) so old tablets render quickly; the import refuses a card with more than {memo.MAX_FILTERED}")
    clean_dir.mkdir(parents=True, exist_ok=True)
    (clean_dir / f"{name}.svg").write_text(cleaned, encoding="utf-8")
    report["clean_svg"] = str(clean_dir / f"{name}.svg")
    if not a.no_render and not Path(CHROME).exists():
        errors.append(f"cannot render: Google Chrome not found at {CHROME} — install it or edit CHROME at the top of studio/tools/check.py (--no-render validates without it)")
    elif not a.no_render:
        png_dir.mkdir(parents=True, exist_ok=True)
        TMP.mkdir(parents=True, exist_ok=True)
        png = png_dir / f"{name}.png"
        vbm = re.match(r"\s*(-?[\d.]+)[\s,]+(-?[\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)", vb or memo.VIEWBOX)
        vw, vh = (float(vbm.group(3)), float(vbm.group(4))) if vbm else (800.0, 500.0)
        out_w = 800 if not a.sheet else int(min(1600, max(800, vw)))
        out_h = int(round(out_w * vh / vw))
        full_html = TMP / f"full-{tmp_tag}.html"
        full_html.write_text(f"<!doctype html><meta charset='utf-8'><body style='margin:0;background:#fff'><div style='width:{out_w}px;height:{out_h}px'>{cleaned}</div></body>", encoding="utf-8")
        chrome_shot(f"file://{full_html}", png, out_w, out_h)
        zooms = []
        asked = 0
        for zi, z in enumerate(a.zoom, 1):
            try:
                zx, zy, zw, zh = (float(v) for v in z.split(","))
            except ValueError:
                warnings.append(f"--zoom {z!r} ignored: expected X,Y,W,H")
                continue
            asked += 1
            zW = 800 if zw >= zh else int(round(800 * zw / zh))
            zH = int(round(zW * zh / zw))
            crop = re.sub(r'viewBox="[^"]*"', f'viewBox="{zx:g} {zy:g} {zw:g} {zh:g}"', cleaned, count=1)
            zhtml = TMP / f"zoom-{tmp_tag}-{zi}.html"
            zhtml.write_text(f"<!doctype html><meta charset='utf-8'><body style='margin:0;background:#fff'><div style='width:{zW}px;height:{zH}px'>{crop}</div></body>", encoding="utf-8")
            zpng = png_dir / f"{name}.zoom{zi}.png"
            chrome_shot(f"file://{zhtml}", zpng, zW, zH)
            if zpng.exists():
                zooms.append(str(zpng))
            else:
                errors.append(lost(zpng))
        if asked:
            report["zoom_pngs"] = zooms  # only the files that are there
        if a.sheet:
            report["png"] = str(png) if png.exists() else None
            if not png.exists():
                errors.append(lost(png))
            report["errors"] = errors; report["warnings"] = warnings; report["ok"] = not errors
            print(json.dumps(report, ensure_ascii=False, indent=1))
            return 0 if not errors else 1
        scene_only = re.sub(r'<g id="word-art"', '<g id="word-art" display="none"', cleaned, count=1)
        # the second copy must not clash with the first copy's ids: reid() gives each its own suffix
        html = ("<!doctype html><meta charset='utf-8'><body style='margin:0;background:#2b2f3a;font:13px -apple-system,sans-serif;color:#fff'>"
                "<div style='display:flex;gap:16px;padding:12px;align-items:flex-start'>"
                f"<div><div>scene only (word-art hidden)</div><div style='width:400px'>{reid(scene_only, '_a')}</div></div>"
                f"<div><div>phone size (360 px wide)</div><div style='width:360px'>{reid(cleaned, '_b')}</div></div>"
                "</div></body>")
        sheet_html = TMP / f"sheet-{tmp_tag}.html"
        sheet_html.write_text(html, encoding="utf-8")
        sheet = png_dir / f"{name}.sheet.png"
        chrome_shot(f"file://{sheet_html}", sheet, 800, 290)
        report["png"] = str(png) if png.exists() else None
        report["sheet_png"] = str(sheet) if sheet.exists() else None
        if not png.exists():
            errors.append(lost(png))
        if not sheet.exists():
            errors.append(lost(sheet))
    report["errors"] = errors
    report["warnings"] = warnings
    report["ok"] = not errors
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
