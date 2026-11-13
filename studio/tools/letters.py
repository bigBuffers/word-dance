#!/usr/bin/env python3
"""letters.py — real letterforms for the word-art layer of a memory card.

Lays a word out on a baseline with an open-licence (OFL) font and prints, per letter, the glyph outline as an SVG path
in canvas coordinates (y down) plus its metrics (advance box, ink bbox, the bbox of every contour — the counter of an
`o`, the dot of an `i`). The card author pastes the paths (never redraws or edits a `d`) and decorates around them.
Each letter is ONE overlap-free outline: the font's overlapping contours (the crossbar of `f` and `t`, the arms of `k`)
are merged, so a dashed or inner stroke shows no seams; `--raw-outlines` prints the font's raw contours, which the first
ten cards carry.

    studio/tools/letters moon --size 150 --x 400 --baseline 330                 # centred on x=400
    studio/tools/letters breakfast --chunks "break|fast" --gap 26 --size 96 --x 400 --baseline 440
    studio/tools/letters rain --split-dots --size 140 --x 60 --anchor start --baseline 200

Output: JSON on stdout (`letters[i].d`, `.bbox`, `.cx`, `.contours`, and a ready `snippet`). Letter ids are
`wa-<index>-<letter>` (index = position in the word as typed, spaces included); the hyphen of `T-shirt` or the apostrophe
of `o'clock` is `wap-<index>` — drawn like a letter, but not part of the spelling the import checks.

The font is found from this file's own location (studio/fonts/, see :data:`DEFAULT_FONT`), so the tool works from any
working directory; `studio/tools/letters` is the sh wrapper that runs it under studio/.venv (fonttools and skia-pathops
live only there — studio/requirements.txt).
check.py imports :func:`load_font` and :func:`layout` to rebuild the reference outline of every letter it validates — the
two tools must use the same font file, which is why the name is a constant here and nowhere else.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import RecordingPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HERE = Path(__file__).resolve().parent
FONT_DIR = HERE.parent / "fonts"
DEFAULT_FONT = "Andika-Bold"  # studio/fonts/Andika-Bold.ttf (SIL OFL 1.1, studio/fonts/OFL.txt) — the house font, chosen once for the whole set


def load_font(name: str) -> TTFont:
    path = Path(name)
    if not path.suffix:
        path = FONT_DIR / f"{name}.ttf"
    if not path.is_file():
        raise SystemExit(f"letters.py: font file not found: {path} (the house font is {FONT_DIR / (DEFAULT_FONT + '.ttf')})")
    return TTFont(str(path))


def ntos(v: float) -> str:
    s = f"{v:.1f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def split_contours(rec: RecordingPen) -> list[list[tuple]]:
    contours: list[list[tuple]] = []
    cur: list[tuple] = []
    for op, args in rec.value:
        cur.append((op, args))
        if op in ("closePath", "endPath"):
            contours.append(cur)
            cur = []
    if cur:
        contours.append(cur)
    return contours


def replay(ops: list[tuple], pen) -> None:
    for op, args in ops:
        getattr(pen, op)(*args)


def contour_bounds(ops: list[tuple], glyph_set, transform) -> list[float] | None:
    bp = BoundsPen(glyph_set)
    replay(ops, TransformPen(bp, transform))
    return None if bp.bounds is None else [round(v, 1) for v in bp.bounds]


def contour_path(ops: list[tuple], glyph_set, transform) -> str:
    sp = SVGPathPen(glyph_set, ntos=ntos)
    replay(ops, TransformPen(sp, transform))
    return sp.getCommands()


def signed_area(ops: list[tuple]) -> float:
    pts = []
    for op, args in ops:
        for a in args:
            if isinstance(a, tuple) and len(a) == 2:
                pts.append(a)
    area = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        area += x0 * y1 - x1 * y0
    return area / 2.0


# Overlap-free outlines (skia-pathops): the font builds f / t / k / e … from overlapping contours, so a dashed or inner stroke on the
# raw glyph shows seams inside the letter (the doubled dashes the jury saw on ghost letters) and `e` reports no counter. Merged into
# one outline per letter, both disappear. False = the font's raw contours, which the first ten cards carry (tools/check.py accepts both).
SIMPLIFY = True


def glyph_contours(font: TTFont, ch: str, simplify: bool | None = None):
    cmap = font.getBestCmap()
    if ord(ch) not in cmap:
        raise SystemExit(f"letters.py: the font has no glyph for {ch!r}")
    gname = cmap[ord(ch)]
    glyph_set = font.getGlyphSet()
    rec = RecordingPen()
    try:
        from fontTools.pens.recordingPen import DecomposingRecordingPen

        rec = DecomposingRecordingPen(glyph_set)
    except Exception:  # pragma: no cover
        pass
    glyph_set[gname].draw(rec)
    if SIMPLIFY if simplify is None else simplify:
        import pathops

        path = pathops.Path()
        rec.replay(pathops.PathPen(path))
        path.simplify(fix_winding=True, keep_starting_points=False)
        rec = RecordingPen()
        path.draw(rec)
    advance = font["hmtx"][gname][0]
    return glyph_set, split_contours(rec), advance


def layout(font: TTFont, word: str, *, size: float, x: float, baseline: float, anchor: str, track: float, chunks: list[str] | None, gap: float, split_dots: bool, prefix: str, simplify: bool | None = None) -> dict:
    upm = font["head"].unitsPerEm
    s = size / upm
    # chunk index per character (spaces inside the word are kept as advances)
    chunk_of: list[int] = []
    if chunks:
        if "".join(chunks) != word:
            raise SystemExit(f"letters.py: --chunks {'|'.join(chunks)!r} does not spell {word!r}")
        for ci, c in enumerate(chunks):
            chunk_of.extend([ci] * len(c))
    else:
        chunk_of = [0] * len(word)
    # first pass: advances
    items = []
    pen_x = 0.0
    for i, ch in enumerate(word):
        if i > 0:
            pen_x += track + (gap if chunk_of[i] != chunk_of[i - 1] else 0.0)
        if ch == " ":
            sp_adv = font["hmtx"][font.getBestCmap()[32]][0] * s if 32 in font.getBestCmap() else size * 0.3
            items.append((i, ch, pen_x, sp_adv, None))
            pen_x += sp_adv
            continue
        glyph_set, contours, adv = glyph_contours(font, ch, simplify)
        items.append((i, ch, pen_x, adv * s, (glyph_set, contours)))
        pen_x += adv * s
    total = pen_x
    x0 = {"start": x, "middle": x - total / 2.0, "end": x - total}[anchor]
    letters = []
    all_bounds: list[list[float]] = []
    for i, ch, off, adv, g in items:
        if g is None:
            continue
        glyph_set, contours, = g
        t = (s, 0, 0, -s, x0 + off, baseline)
        infos = []
        for ops in contours:
            b = contour_bounds(ops, glyph_set, t)
            if b is None:
                continue
            infos.append({"bbox": b, "area": signed_area(ops) * s * s, "ops": ops})
        if not infos:
            continue
        # outer contours share the sign of the largest contour; the others are holes (counters)
        big = max(infos, key=lambda c: abs(c["area"]))
        for c in infos:
            c["hole"] = (c["area"] > 0) != (big["area"] > 0)
        xs0 = min(c["bbox"][0] for c in infos); ys0 = min(c["bbox"][1] for c in infos)
        xs1 = max(c["bbox"][2] for c in infos); ys1 = max(c["bbox"][3] for c in infos)
        bbox = [xs0, ys0, xs1, ys1]
        all_bounds.append(bbox)
        # a letter or digit is `<prefix>-<index>-<char>` — the ids the import's structure check spells the headword from
        # (docs/MEMORY_CARDS_DESIGN.md §3.1: spaces, hyphens, apostrophes and full stops do not count). A punctuation mark
        # therefore gets an id of ANOTHER shape, `<prefix>p-<index>`: written as a letter id it would add a letter to the spelling.
        base_id = f"{prefix}-{i}-{ch}" if ch.isalnum() else f"{prefix}p-{i}"
        entry = {
            "i": i, "ch": ch, "chunk": chunk_of[i], "id": base_id,
            "x0": round(x0 + off, 1), "x1": round(x0 + off + adv, 1), "cx": round((xs0 + xs1) / 2.0, 1), "cy": round((ys0 + ys1) / 2.0, 1),
            "bbox": bbox,
            "contours": [{"bbox": c["bbox"], "hole": c["hole"]} for c in infos],
        }
        dot = None
        if split_dots and ch in "ij" and len([c for c in infos if not c["hole"]]) >= 2:
            # the dot is the outer contour that sits highest
            outers = [c for c in infos if not c["hole"]]
            dot = min(outers, key=lambda c: c["bbox"][1])
            body = [c for c in infos if c is not dot]
            entry["d"] = "".join(contour_path(c["ops"], glyph_set, t) for c in body)
            entry["dot"] = {"id": base_id + "-dot", "bbox": dot["bbox"], "cx": round((dot["bbox"][0] + dot["bbox"][2]) / 2, 1), "cy": round((dot["bbox"][1] + dot["bbox"][3]) / 2, 1),
                            "r": round((dot["bbox"][2] - dot["bbox"][0]) / 2, 1), "d": contour_path(dot["ops"], glyph_set, t)}
        else:
            entry["d"] = "".join(contour_path(c["ops"], glyph_set, t) for c in infos)
        letters.append(entry)
    os2 = font["OS/2"]
    xh = getattr(os2, "sxHeight", 0) or 0
    caph = getattr(os2, "sCapHeight", 0) or 0
    hhea = font["hhea"]
    out = {
        "word": word, "size": size, "baseline": baseline, "anchor": anchor, "track": track, "gap": gap,
        "chunks": chunks or [word],
        "advance_box": [round(x0, 1), round(x0 + total, 1)],
        "ink_bbox": [min(b[0] for b in all_bounds), min(b[1] for b in all_bounds), max(b[2] for b in all_bounds), max(b[3] for b in all_bounds)] if all_bounds else None,
        "x_height_y": round(baseline - xh * s, 1), "cap_height_y": round(baseline - caph * s, 1),
        "ascender_y": round(baseline - hhea.ascent * s, 1), "descender_y": round(baseline - hhea.descent * s, 1),
        "letters": letters,
    }
    lines = ['<g id="word-art">']
    for L in letters:
        lines.append(f'  <path id="{L["id"]}" d="{L["d"]}"/>')
        if "dot" in L:
            lines.append(f'  <path id="{L["dot"]["id"]}" d="{L["dot"]["d"]}"/>')
    lines.append("</g>")
    out["snippet"] = "\n".join(lines)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("word")
    ap.add_argument("--size", type=float, default=120.0, help="font size in canvas px (em size)")
    ap.add_argument("--x", type=float, default=400.0)
    ap.add_argument("--baseline", type=float, default=300.0)
    ap.add_argument("--anchor", choices=("start", "middle", "end"), default="middle")
    ap.add_argument("--track", type=float, default=0.0, help="extra space between letters, px")
    ap.add_argument("--chunks", default="", help='phonics chunks, e.g. "break|fast"')
    ap.add_argument("--gap", type=float, default=0.0, help="extra space between chunks, px")
    ap.add_argument("--split-dots", action="store_true", help="give the dot of i / j as its own path (so a drawn object may replace it)")
    ap.add_argument("--prefix", default="wa", help="id prefix (ids are <prefix>-<index>-<letter>)")
    ap.add_argument("--font", default=DEFAULT_FONT)
    ap.add_argument("--brief", action="store_true", help="omit the path data from the per-letter list (metrics only + snippet)")
    ap.add_argument("--raw-outlines", action="store_true", help="the font's raw, overlapping contours instead of the merged overlap-free outline (only to reproduce the first ten cards)")
    a = ap.parse_args()
    font = load_font(a.font)
    chunks = [c for c in a.chunks.split("|") if c] if a.chunks else None
    out = layout(font, a.word, size=a.size, x=a.x, baseline=a.baseline, anchor=a.anchor, track=a.track, chunks=chunks, gap=a.gap, split_dots=a.split_dots, prefix=a.prefix, simplify=not a.raw_outlines)
    if a.brief:
        out.pop("snippet", None)
        for L in out["letters"]:
            L.pop("d", None)
            if "dot" in L:
                L["dot"].pop("d", None)
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
