"""kit.word — the memory layer (`#word-art`) by the rules of STYLE.md §3 and LESSONS #10–14, #22, #23.

Real letters from `studio/tools/letters`, as big as the calm zone allows, centred in it, one line; the chunks of the
brief in clearly different colours (the stressed chunk warm), silent letters as ghost letters, double letters as
twins with a small bridge; a cream keyline + ONE soft shadow on a light zone, luminous fills with a deep keyline on a
dark one. The hook's own marks are added with `.under()` / `.over()` using the letter metrics in `.letters`.
"""
from __future__ import annotations

import json
import subprocess

from .base import ST, n

ON_LIGHT = {'coral': ('#F26A48', '#D23C24'), 'indigo': ('#4A5CC6', '#2A3590'), 'green': ('#63A040', '#3F6A28'), 'plum': ('#A254A6', '#6E2F7A'),
            'orange': ('#FA962E', '#DC6A12'), 'teal': ('#2FA6A0', '#1A7272'), 'pink': ('#F2689A', '#C83A72'), 'brown': ('#B8703A', '#8A4A22')}
ON_DARK = {'gold': ('#FFF8D0', '#FFCF48'), 'moon': ('#F4F7FF', '#B4C6FF'), 'mint': ('#EAFFF2', '#9EE6B8'), 'pink': ('#FFECF2', '#FFA9C0'), 'coral': ('#FFE6DC', '#FF9A7E')}
GHOST_DARK = {'gold': '#FFB23A', 'moon': '#8FA8FF', 'mint': '#5ED69A', 'pink': '#FF7FA8', 'coral': '#FF7A5A'}      # saturated: a pale tint turns grey on a night sky
ORDER_LIGHT = ('coral', 'indigo', 'green', 'plum')
ORDER_DARK = ('gold', 'moon', 'mint', 'pink')


def _run(word, chunks, size, x, base, gap, track, dots, brief=False):
    cmd = [str(ST / 'tools/letters'), word, '--chunks', '|'.join(chunks), '--gap', n(gap), '--size', n(size), '--x', n(x), '--baseline', n(base), '--track', n(track)]
    if dots:
        cmd.append('--split-dots')
    if brief:
        cmd.append('--brief')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('tools/letters failed: ' + r.stderr[-400:])
    return json.loads(r.stdout)


class WordArt:
    def __init__(self, card, zone=None, colors=None, on=None, size=None, gap=12, track=4, dots=False, shadow=True, stress=None, letters=None):
        zone = zone or card.calm
        if not zone:
            raise SystemExit('word(): give zone=(x0, y0, x1, y1) or set calm= on the Card')
        self.card, self.zone = card, zone
        dance = (card.brief or {}).get('dance') or {}
        word = card.word
        chunks = dance.get('chunks') or [word]
        if ''.join(chunks).replace(' ', '') != word.replace(' ', ''):
            chunks = [word]
        self.chunks = chunks
        self.stress = dance.get('stress_chunk_index', 0) if stress is None else stress
        self.silent = set(dance.get('silent_letter_indexes') or [])
        self.pairs = [tuple(p) for p in (dance.get('double_letter_index_pairs') or [])]
        self.on = on or ('dark' if card.L['dark'] else 'light')
        nl = len(word.replace(' ', ''))
        lo, hi = (150, 190) if nl <= 2 else (140, 180) if nl <= 5 else (115, 140) if nl <= 7 else (96, 115) if nl <= 9 else (64, 96)
        zw, zh = zone[2] - zone[0], zone[3] - zone[1]
        g = gap if len(chunks) > 1 else 0
        if size is None:
            size = hi
            for _ in range(3):
                m = _run(word, chunks, size, 400, 300, g, track, dots, brief=True)
                iw, ih = m['ink_bbox'][2] - m['ink_bbox'][0], m['ink_bbox'][3] - m['ink_bbox'][1]
                k = min(1.0, (zw - 16) / iw, (zh - 12) / ih, 720 / iw)
                if k > .995:
                    break
                size = int(size * k)
            if size < lo:
                card.note(f'WORD: only {size} px fits the zone {tuple(round(v) for v in zone)} — the house size for {nl} letters is {lo}–{hi}; widen / heighten the calm zone')
        m = _run(word, chunks, size, 400, 300, g, track, dots, brief=True)
        ib = m['ink_bbox']
        x = 400 + (zone[0] + zone[2]) / 2 - (ib[0] + ib[2]) / 2
        base = 300 + (zone[1] + zone[3]) / 2 - (ib[1] + ib[3]) / 2
        j = _run(word, chunks, size, x, base, g, track, dots)
        self.size, self.baseline, self.letters = size, base, j['letters']
        self.ink = tuple(j['ink_bbox'])
        self.x_height_y, self.ascender_y = j['x_height_y'], j['ascender_y']
        order = ORDER_DARK if self.on == 'dark' else ORDER_LIGHT
        pal = ON_DARK if self.on == 'dark' else ON_LIGHT
        if colors is None:
            colors, k = [], 1
            for c in range(len(chunks)):
                if c == self.stress or len(chunks) == 1:
                    colors.append(order[0])
                else:
                    colors.append(order[k])
                    k = k + 1 if k + 1 < len(order) else 1
        if isinstance(colors, str):
            colors = [colors] * len(chunks)
        for c in colors:
            if c not in pal:
                raise SystemExit(f'word colour {c!r}: on a {self.on} zone use one of {sorted(pal)}')
        self.colors = list(colors)
        self.letter_colors = dict(letters or {})          # {letter index: colour name} — only when the hook singles letters out
        for c in self.letter_colors.values():
            if c not in pal:
                raise SystemExit(f'word colour {c!r}: on a {self.on} zone use one of {sorted(pal)}')
        self._under, self._over, self.shadow = [], [], shadow

    # ---- metrics for the hook
    def letter(self, i):
        """The metrics of letter i (0-based position in the word): bbox, cx, cy, contours, dot."""
        return next(l for l in self.letters if l['i'] == i)

    def counter(self, i):
        """The box of the hole inside letter i (o, a, e, d, p, b, g, q) — a place for a small picture."""
        return next(c['bbox'] for c in self.letter(i)['contours'] if c['hole'])

    def chunk_box(self, k):
        bs = [l['bbox'] for l in self.letters if l['chunk'] == k]
        return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))

    def under(self, xml):
        """Hook shapes drawn UNDER the letters, inside #word-art (a halo, an object a letter holds)."""
        self._under.append(xml)
        return self

    def over(self, xml):
        """Hook shapes drawn OVER the letters (a moon inside an o, a drop in place of a dot). Keep them off the strokes."""
        self._over.append(xml)
        return self

    def describe(self):
        return (f'word "{self.card.word}" {self.size} px on a {self.on} zone, chunks {"|".join(self.chunks)} = {"/".join(self.colors)}, ink {tuple(round(v) for v in self.ink)}, '
                f'baseline {n(self.baseline)}, x-height y {n(self.x_height_y)}' + (f', ghost letters {sorted(self.silent)}' if self.silent else '') + (f', twins {self.pairs}' if self.pairs else ''))

    def xml(self):
        card, dark = self.card, self.on == 'dark'
        pal = ON_DARK if dark else ON_LIGHT
        top = min(l['bbox'][1] for l in self.letters)
        out = list(self._under)
        if dark:
            i = self.ink
            out.append(f'<ellipse cx="{n((i[0] + i[2]) / 2)}" cy="{n((i[1] + i[3]) / 2)}" rx="{n((i[2] - i[0]) * .6)}" ry="{n((i[3] - i[1]) * .8)}" fill="{card.glow("#B9C6F8")}" opacity=".3"/>')
        key = '#2B3078' if dark else '#FFF8E7'
        solid, ghost, by_col = [], [], {}
        for l in self.letters:
            by_col.setdefault(self.letter_colors.get(l['i'], self.colors[l['chunk']]), []).append(l)
        for col, ls in by_col.items():
            a, b = pal[col]
            gid = f'wl-{col}'
            card.lin(gid, 0, a, 1, b, x1=0, y1=top, x2=0, y2=self.baseline, user=True)
            s = ''.join(f'<path id="{l["id"]}" d="{l["d"]}"/>' + (f'<path id="{l["dot"]["id"]}" d="{l["dot"]["d"]}"/>' if l.get('dot') else '') for l in ls if l['i'] not in self.silent)
            if s:
                solid.append(f'<g fill="url(#{gid})">{s}</g>')
            for l in ls:
                if l['i'] in self.silent:
                    fo, sc = ('.55', b) if dark else ('.38', b)                  # LESSONS #10 / #22: the chunk colour, see-through, dashed keyline
                    ghost.append(f'<path id="{l["id"]}" d="{l["d"]}" fill="{GHOST_DARK[col] if dark else b}" fill-opacity="{fo}" stroke="{sc}" stroke-width="3.5" stroke-dasharray="7 6" stroke-linejoin="round" stroke-linecap="round"/>')
        f = ''
        if self.shadow:
            fc, fo = ('#1E2460', .5) if dark else (('#8A5A2A', .35) if card.light in ('golden', 'window') else ('#3A3F78', .3))
            card.define('ws', f'<filter id="ws" x="-10%" y="-15%" width="125%" height="140%"><feDropShadow dx="3" dy="5" stdDeviation="4" flood-color="{fc}" flood-opacity="{n(fo)}"/></filter>')
            f = ' filter="url(#ws)"'
        out.append(f'<g{f} stroke="{key}" stroke-width="7" stroke-linejoin="round" paint-order="stroke">' + ''.join(solid) + '</g>')
        out += ghost
        for p in self.pairs:
            a, b = self.letter(p[0]), self.letter(p[1])
            x0, x1, y = a['bbox'][0] + 6, b['bbox'][2] - 6, max(a['bbox'][3], b['bbox'][3]) + 15
            d = f'M{n(x0)},{n(y)}Q{n((x0 + x1) / 2)},{n(y + 11)},{n(x1)},{n(y)}'
            out.append(f'<path d="{d}" fill="none" stroke="{key}" stroke-width="9" stroke-linecap="round"/><path d="{d}" fill="none" stroke="{"#FFD24A" if dark else "#F7B93A"}" stroke-width="4.5" stroke-linecap="round"/>')
        out += self._over
        return '<g id="word-art">' + ''.join(out) + '</g>'
