"""kit.base — numbers, geometry and the Card (layers, defs, layout register, save + check).

A card script builds ONE `Card`, calls stage / prop / figure / word methods on it (each appends SVG to a layer and
registers the box it occupies) and ends with `card.save(out_dir)`, which writes `<out_dir>/cards/<file>.svg`, runs
`studio/tools/check` on it and prints a short report: the layout findings of the kit first, then the tool's errors
and warnings and the paths of the renders. Everything a script needs is documented in `studio/kit/KIT.md`.
"""
from __future__ import annotations

import json
import math
import pathlib
import random
import re
import subprocess

ST = pathlib.Path(__file__).resolve().parents[1]          # studio/
W, H = 800, 500


def n(x) -> str:
    """One decimal at most, no trailing zero, no '-0'."""
    s = f'{x:.1f}'
    if s.endswith('.0'):
        s = s[:-2]
    return '0' if s == '-0' else s


def P(p) -> str:
    return f'{n(p[0])},{n(p[1])}'


def rot(p, deg, c=(0, 0)):
    a = math.radians(deg)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * math.cos(a) - y * math.sin(a), c[1] + x * math.sin(a) + y * math.cos(a))


def unit(a, b):
    d = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
    return ((b[0] - a[0]) / d, (b[1] - a[1]) / d)


def lerp(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def ik2(s, w, l1, l2):
    """The two joint positions of a two-bone limb from `s` to `w` (bone lengths l1, l2); `w` must be in reach."""
    d = max(dist(s, w), 1e-6)
    a = math.atan2(w[1] - s[1], w[0] - s[0])
    b = math.acos(max(-1.0, min(1.0, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    return [(s[0] + l1 * math.cos(a + sg * b), s[1] + l1 * math.sin(a + sg * b)) for sg in (1, -1)]


def hang(e, w) -> float:
    """Rotation of a hand / side shoe that continues the bone e → w (0 = pointing down)."""
    return math.degrees(math.atan2(-(w[0] - e[0]), w[1] - e[1]))


def box_of(points, pad=0.0):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def boxes_hit(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def stops(*pairs) -> str:
    """stops(0, '#FFF', .5, ('#FFD', .4), 1, '#000') → <stop> elements; a tuple colour carries its opacity."""
    out = []
    for off, col in zip(pairs[::2], pairs[1::2]):
        op = ''
        if isinstance(col, tuple):
            col, o = col
            op = f' stop-opacity="{n(o)}"'
        out.append(f'<stop offset="{n(off)}" stop-color="{col}"{op}/>')
    return ''.join(out)


LAYERS = ('back', 'far', 'bloom', 'ground', 'shadow', 'mid', 'fx', 'near')


class Card:
    """One memory card. Layers, bottom → top: back (sky / wall, crisp) · far (ONE blurred group) · bloom (the light's
    wash) · ground · shadow (ONE blurred group of contact shadows) · mid (the action, in the order you add it) · fx
    (shafts, rain, steam, glints) · near (ONE soft foreground group) · the word."""

    def __init__(self, word: str, light: str = 'golden', file: str | None = None, brief: dict | None = None, seed: int = 7):
        from .stage import LIGHTS
        if light not in LIGHTS:
            raise SystemExit(f'light must be one of {sorted(LIGHTS)}')
        self.word, self.file, self.brief = word, file or word.replace(' ', '_'), brief or {}
        self.light, self.L = light, dict(LIGHTS[light])
        self.sun = self.L['sun']
        self.rnd = random.Random(seed)
        self.defs: dict[str, str] = {}
        self.layers: dict[str, list[str]] = {k: [] for k in LAYERS}
        self.items: list[dict] = []          # what stands where: name, box, kind ('figure' | 'prop' | 'soft'), layer, order
        self.figures: list = []
        self.notes: list[str] = []           # layout findings, printed by save()
        self.wordart = None
        self.captions: dict[str, str] = {}
        self.title = word
        self.calm = None                     # (x0, y0, x1, y1): where the word will stand; scatter functions keep out of it
        self.S = .8                          # ONE scale for everybody on the card (head radius = S × R)

    # ---- low level -------------------------------------------------------------------------------------------------
    def add(self, xml: str, layer: str = 'mid', name: str | None = None, box=None, kind: str = 'prop'):
        """Append raw SVG to a layer. Give `name` and `box=(x0,y0,x1,y1)` for anything solid, so the layout check sees it."""
        self.layers[layer].append(xml)
        if box is not None:
            self.items.append({'name': name or 'shape', 'box': tuple(box), 'kind': kind, 'layer': layer, 'order': len(self.items)})
        return self

    def define(self, gid: str, xml: str) -> str:
        """Register a gradient / filter / clipPath once; returns 'url(#gid)'."""
        if gid in self.defs and self.defs[gid] != xml:
            raise SystemExit(f'two different definitions for id {gid}')
        self.defs[gid] = xml
        return f'url(#{gid})'

    def lin(self, gid, *st, x1=0, y1=0, x2=0, y2=1, user=False) -> str:
        """Linear gradient (default top → bottom over the shape's box; user=True: canvas coordinates)."""
        u = ' gradientUnits="userSpaceOnUse"' if user else ''
        return self.define(gid, f'<linearGradient id="{gid}"{u} x1="{n(x1)}" y1="{n(y1)}" x2="{n(x2)}" y2="{n(y2)}">{stops(*st)}</linearGradient>')

    def rad(self, gid, *st, cx=None, cy=None, r=None, user=False) -> str:
        geo = '' if cx is None else f' cx="{n(cx)}" cy="{n(cy)}" r="{n(r)}"'
        u = ' gradientUnits="userSpaceOnUse"' if user else ''
        return self.define(gid, f'<radialGradient id="{gid}"{u}{geo}>{stops(*st)}</radialGradient>')

    def blur(self, sd: float) -> str:
        gid = 'b' + n(sd).replace('.', '_')
        return self.define(gid, f'<filter id="{gid}" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="{n(sd)}"/></filter>')

    def glow(self, col: str = '#FFF8DE') -> str:
        """A soft radial fade without a filter — fill any ellipse / circle with it (halo, sheen, bokeh, light pool)."""
        gid = 'g' + col.strip('#').lower()
        return self.rad(gid, 0, col, 1, (col, 0))

    def shadow(self, x, y, rx, ry=None, op=None, layer='shadow'):
        """ONE soft contact shadow on the ground under something (layer 'shadow' is blurred as a group)."""
        ry = ry or max(4.0, rx * .16)
        self.layers[layer].append(f'<ellipse cx="{n(x)}" cy="{n(y)}" rx="{n(rx)}" ry="{n(ry)}" opacity="{n(op or self.L["shadow_op"])}"/>')
        return self

    def note(self, msg: str):
        self.notes.append(msg)

    # ---- output ----------------------------------------------------------------------------------------------------
    def svg(self) -> str:
        from .cast import cast_grad
        L = self.layers
        scene = []
        scene += L['back']
        if L['far']:
            scene.append(f'<g filter="{self.blur(3)}">' + ''.join(L['far']) + '</g>')
        scene += L['bloom'] + L['ground']
        if L['shadow']:
            scene.append(f'<g filter="{self.blur(5)}" fill="{self.L["shadow"]}">' + ''.join(L['shadow']) + '</g>')
        scene += L['mid'] + L['fx']
        if L['near']:
            scene.append(f'<g filter="{self.blur(4)}">' + ''.join(L['near']) + '</g>')
        body = '\n'.join(scene)
        word = self.wordart.xml() if self.wordart else '<g id="word-art"></g>'
        for gid in sorted(set(re.findall(r'url\(#(c-[a-z-]+)\)', body))):
            self.defs.setdefault(gid, cast_grad(gid))
        defs = '\n'.join(self.defs[k] for k in sorted(self.defs))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}">\n<title>{self.title}</title>\n<defs>\n{defs}\n</defs>\n'
                f'<g id="scene">\n{body}\n</g>\n{word}\n</svg>\n')

    def layout_check(self):
        """The numeric checks a look at the render used to be needed for."""
        out = list(self.notes)
        solid = [i for i in self.items if i['kind'] in ('figure', 'prop')]
        if self.wordart:
            ink = self.wordart.ink
            pad = (ink[0] - 24, ink[1] - 24, ink[2] + 24, ink[3] + 24)
            for i in solid:
                if i.get('layer') in ('back', 'far'):
                    continue
                if boxes_hit(i['box'], pad):
                    out.append(f'WORD: {i["name"]} box {tuple(round(v) for v in i["box"])} comes within 24 px of the word ink {tuple(round(v) for v in ink)} — move it or the word')
            if ink[0] < 30 or ink[2] > W - 30 or ink[1] < 30 or ink[3] > H - 30:
                out.append(f'WORD: ink {tuple(round(v) for v in ink)} is closer than 30 px to the canvas edge')
        else:
            out.append('WORD: no word layer — call card.word(zone=…)')
        props = [i for i in solid if i['kind'] == 'prop' and i.get('layer') not in ('back', 'far')]
        if len(props) > 9:
            out.append(f'PROPS: {len(props)} props registered in the middle plane — the house style allows about six; drop the ones that do not carry the scene')
        for f in self.figures:
            for i in self.items:
                if i['order'] > f.order and i['kind'] in ('prop', 'figure') and i['name'] != f.name and boxes_hit(i['box'], f.face_box):
                    out.append(f'FACE: {i["name"]} (drawn after {f.name}) overlaps {f.name}\'s face {tuple(round(v) for v in f.face_box)} — nothing may cross a face')
        return out

    def save(self, out_dir, zoom: bool = True, check: bool = True) -> dict:
        out_dir = pathlib.Path(out_dir)
        (out_dir / 'cards').mkdir(parents=True, exist_ok=True)
        path = out_dir / 'cards' / f'{self.file}.svg'
        text = self.svg()
        path.write_text(text)
        print(f'== {self.word} · light {self.light} · {len(text.encode())} bytes → {path}')
        for f in self.figures:
            print('  ' + f.describe())
        if self.wordart:
            print('  ' + self.wordart.describe())
        notes = self.layout_check()
        for m in notes:
            print('  ! ' + m)
        report = {}
        if check:
            cmd = [str(ST / 'tools/check'), str(path), '--word', self.word]
            zooms = []
            if zoom:
                for f in self.figures[:4]:
                    b = f.zoom_box
                    zooms.append(b)
                    cmd += ['--zoom', ','.join(str(int(v)) for v in b)]
                if self.wordart:
                    i = self.wordart.ink
                    b = (max(0, i[0] - 30), max(0, i[1] - 30), min(W, i[2] + 30) - max(0, i[0] - 30), min(H, i[3] + 30) - max(0, i[1] - 30))
                    cmd += ['--zoom', ','.join(str(int(v)) for v in b)]
            r = subprocess.run(cmd, capture_output=True, text=True)
            try:
                report = json.loads(r.stdout)
            except ValueError:
                print('  ! check did not return JSON:', (r.stdout + r.stderr)[-600:])
                report = {'errors': ['check failed to run'], 'warnings': []}
            for e in report.get('errors', []):
                print('  ERROR ' + str(e))
            for w_ in report.get('warnings', []):
                print('  warning ' + str(w_))
            print(f'  check: ok={report.get("ok")} · clean {report.get("clean_bytes")} bytes · filtered elements {report.get("blurred_elements")}')
            png = out_dir / 'png'
            print(f'  look: {png / (self.file + ".sheet.png")} (scene without the word + phone size) · {png / (self.file + ".png")}')
            if zoom:
                print('  zooms: ' + ' '.join(str(png / f'{self.file}.zoom{k + 1}.png') for k in range(len(cmd[4:]) // 2)))
        if self.captions:
            (out_dir / 'captions').mkdir(exist_ok=True)
            (out_dir / 'captions' / f'{self.file}.json').write_text(json.dumps({'word': self.word, **self.captions}, ensure_ascii=False, indent=1))
        report['layout'] = notes
        return report
