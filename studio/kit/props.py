"""kit.props — scenery, furniture and small props in the house shading: a form gradient that runs along the light
(lit left → shade right), a warm highlight on the upper-left edge only, ONE soft contact shadow. Every function
adds its shapes to the card, registers the box they occupy and returns the anchor a figure needs (a seat line, a top).
"""
from __future__ import annotations

import math
import re

from .base import H, W, P, n, rot
from .stage import glint_xml, in_calm

LEAF = {'golden': ('#74AA50', '#96C458', '#C6DC6C', '#DCE87A'), 'window': ('#74AA50', '#96C458', '#C6DC6C', '#DCE87A'),
        'bright': ('#4FA85A', '#7CC656', '#B5E27C', '#D6F0A0'), 'rain': ('#6FA070', '#8FBE86', '#B9D8A6', '#D2E6C4'),
        'night': ('#44549C', '#5568B0', '#7184CE', '#93A4E2')}
WOOD = ('#F0CB96', '#D9A66E', '#B07E54', '#FFE9C0')
LEAFP = 'M0,0C8,-8,22,-8,30,0C22,8,8,8,0,0Z'


def _mix(c, to, k):
    a, b = [int(c[i:i + 2], 16) for i in (1, 3, 5)], [int(to[i:i + 2], 16) for i in (1, 3, 5)]
    return '#' + ''.join(f'{round(x + (y - x) * k):02X}' for x, y in zip(a, b))


def _c3(col, count=3):
    """A colour argument as `count` tones, lit → shade: accepts one '#RRGGBB' or a tuple of 1–3 of them."""
    if isinstance(col, str):
        col = (col,)
    col = [c for c in col if isinstance(c, str) and re.fullmatch(r'#[0-9A-Fa-f]{6}', c)]
    if not col:
        raise SystemExit('a colour must be "#RRGGBB" or a tuple of such strings (lit → shade)')
    if len(col) == 1:
        col = [_mix(col[0], '#FFFFFF', .28), col[0], _mix(col[0], '#3A2A4A', .22)]
    elif len(col) == 2:
        col = [col[0], col[1], _mix(col[1], '#3A2A4A', .2)]
    return tuple(col[:count]) if count <= 3 else tuple(col)


def _wood(card):
    return card.lin('wood', 0, WOOD[0], .5, WOOD[1], 1, WOOD[2], x1=0, y1=0, x2=1, y2=0)


def _form(card, gid, a, b, c):
    return card.lin(gid, 0, a, .5, b, 1, c, x1=0, y1=0, x2=1, y2=0)


def leaf(x, y, deg, col, s=1.0):
    sc = f' scale({n(s)})' if s != 1 else ''
    return f'<path transform="translate({n(x)} {n(y)}) rotate({n(deg)}){sc}" d="{LEAFP}" fill="{col}"/>'


# ------------------------------------------------------------------------------------------------------------ scenery
def tree(card, x, y, h=230, crown=92, layer='mid', name='tree'):
    """A whole tree standing on (x, y): trunk + a round crown. Small ones (h 120–160) for the middle distance."""
    lf = LEAF[card.light]
    tk = card.lin('trunk', 0, '#E4BB8A', .45, '#C2946C', 1, '#A67E68', x1=0, y1=0, x2=1, y2=0)
    tw = max(10.0, h * .075)
    cy = y - h + crown * .8
    o = [f'<path d="M{n(x - tw)},{n(y)}C{n(x - tw * .6)},{n(y - h * .3)},{n(x - tw * .5)},{n(cy + crown * .5)},{n(x - tw * .4)},{n(cy)}H{n(x + tw * .4)}C{n(x + tw * .5)},{n(cy + crown * .5)},{n(x + tw * .7)},{n(y - h * .3)},{n(x + tw * 1.1)},{n(y)}Z" fill="{tk}"/>']
    for dx, dy, rx, ry, c in ((0, .04, .96, .8, 0), (.56, .3, .56, .5, 0), (-.58, .32, .54, .46, 0), (-.62, -.22, .42, .4, 0), (.6, -.2, .4, .38, 0), (.08, -.56, .5, .36, 0),
                              (-.1, -.08, .74, .6, 1), (.42, .24, .42, .36, 1), (-.46, .26, .36, .3, 1), (-.28, -.3, .46, .36, 2), (.2, -.44, .3, .2, 2), (.34, .02, .2, .15, 2)):
        o.append(f'<ellipse cx="{n(x + dx * crown)}" cy="{n(cy + dy * crown)}" rx="{n(rx * crown)}" ry="{n(ry * crown)}" fill="{lf[c]}"/>')
    o.append(f'<path d="M{n(x - crown * .8)},{n(cy - crown * .34)}C{n(x - crown * .66)},{n(cy - crown * .66)},{n(x - crown * .36)},{n(cy - crown * .84)},{n(x - crown * .06)},{n(cy - crown * .86)}" fill="none" stroke="{card.L["rim"]}" stroke-width="2.6" stroke-linecap="round" opacity=".6"/>')
    card.add(''.join(o), layer, name=name, box=(x - tw - 4, cy + crown * .7, x + tw + 4, y), kind='prop')
    card.add('', layer, name=name + ' crown', box=(x - crown, cy - crown * .86, x + crown, cy + crown * .7), kind='soft')
    card.shadow(x + 8, y + 1, crown * .7)
    return (x, cy)


def big_tree(card, side='right', base=362, leaves=True):
    """An old tree that frames the picture: its trunk runs down one edge to `base`, its canopy spreads along the top
    over about half the width. The trunk and the canopy stay out of the calm zone by themselves only if you plan for it."""
    lf = LEAF[card.light]
    tk = card.lin('trunk2', 0, '#E4BB8A', .45, '#C2946C', 1, '#A67E68', x1=700, y1=0, x2=800, y2=0, user=True)
    e = lambda lst: ''.join(f'<ellipse cx="{a}" cy="{b}" rx="{c}" ry="{d}"/>' for a, b, c, d in lst)
    sh = base - 362
    o = [f'<path d="M733,98C700,86,664,66,634,44C612,28,592,12,580,0H628C640,10,658,24,680,36C700,48,722,58,742,62Z" fill="{tk}"/>',
         f'<path d="M748,{n(-sh - 2)}V0C748,36,740,70,731,100C724,126,718,150,720,174C722,196,725,212,717,224C700,232,698,262,714,270C722,284,723,302,717,324C712,342,704,352,692,362Q706,366,720,360Q732,372,750,366Q772,380,800,372V{n(-sh - 2)}Z" fill="{tk}"/>',
         '<path d="M762,96C758,130,766,160,760,174M781,110C785,150,777,170,783,228M746,238C742,262,750,290,744,318M772,248C778,280,768,300,776,342M792,140C790,180,796,210,792,252M734,292C738,310,732,326,726,346" fill="none" stroke="#9C7258" stroke-width="2" stroke-linecap="round" opacity=".6"/>',
         '<ellipse cx="760" cy="206" rx="15" ry="20" fill="#B3855F"/><ellipse cx="760" cy="207" rx="9" ry="13" fill="none" stroke="#8F664F" stroke-width="2.4"/><ellipse cx="760" cy="208" rx="3.4" ry="5.5" fill="#8F664F"/>',
         f'<path d="M733,92C725,122,718,150,720,174C722,196,725,211,716,224C700,233,698,262,713,271C721,284,722,302,716,324C711,340,704,351,694,360" fill="none" stroke="{card.L["rim"]}" stroke-width="3" stroke-linecap="round" opacity=".9"/>']
    trunk = f'<g transform="translate(0 {n(sh)})">' + ''.join(o) + '</g>'
    can = [f'<g fill="{lf[0]}">{e([(792, 44, 62, 52), (722, 22, 62, 36), (642, 8, 58, 28), (562, 0, 52, 22), (482, 2, 56, 24), (412, -2, 46, 22)])}</g>',
           f'<g fill="{lf[1]}">{e([(772, 24, 50, 32), (698, 8, 46, 24), (612, -2, 42, 18), (522, -4, 46, 18), (446, 0, 38, 14), (800, 84, 24, 24)])}</g>',
           f'<g fill="{lf[2]}">{e([(752, 8, 28, 13), (668, -2, 26, 11), (586, -6, 24, 10), (498, -6, 26, 10), (428, -5, 22, 9), (786, 58, 16, 10)])}</g>']
    if leaves:
        can.append('<path d="M432,6Q392,22,350,56" fill="none" stroke="#B08A62" stroke-width="3" stroke-linecap="round"/>')
        can += [leaf(414, 13, 105, lf[1]), leaf(396, 21, 62, lf[3]), leaf(378, 32, 112, lf[2]), leaf(362, 44, 70, lf[1]), leaf(350, 56, 128, lf[3]),
                leaf(640, 30, 100, lf[1], .8), leaf(704, 52, 78, lf[1], .8), leaf(540, 16, 104, lf[1], .8), leaf(470, 20, 82, lf[2], .8), leaf(778, 96, 96, lf[1], .8), leaf(600, 14, 96, lf[2], .7)]
    xml = trunk + ''.join(can)
    if side == 'left':
        xml = f'<g transform="translate({W} 0) scale(-1 1)">{xml}</g>'
    bx = (690, 0, 800, base + 8) if side == 'right' else (0, 0, 110, base + 8)
    card.add(xml, 'mid', name='old tree', box=bx, kind='prop')
    card.add('', 'mid', name='canopy', box=(360, 0, 800, 66) if side == 'right' else (0, 0, 440, 66), kind='soft')
    card.shadow(770 if side == 'right' else 30, base + 16, 66, 11, op=.3)
    return bx


def branch(card, corner='tr', count=7, layer='mid'):
    """A leafy branch reaching in from a top corner — the ONE framing element of a card (crisp, light-toned)."""
    lf, r = LEAF[card.light], card.rnd
    o = ['<path d="M-6,22Q70,10,150,58" fill="none" stroke="#B08A62" stroke-width="4" stroke-linecap="round"/><path d="M82,24Q110,14,132,18" fill="none" stroke="#B08A62" stroke-width="2.6" stroke-linecap="round"/>']
    for i in range(count):
        t = (i + .6) / count
        x, y = -6 + 156 * t, 22 - 24 * t * (1 - t) * 2 + 36 * t * t
        o.append(leaf(x, y, (58 if i % 2 else 118) + r.uniform(-14, 14), lf[(i % 3) + 1], r.uniform(.9, 1.3)))
    o.append(leaf(132, 18, 20, lf[2]) + leaf(150, 58, 96, lf[3], 1.2))
    xml = ''.join(o)
    if corner == 'tr':
        xml = f'<g transform="translate({W} 0) scale(-1 1)">{xml}</g>'
    card.add(xml, layer, name='branch', box=(0, 0, 176, 96) if corner == 'tl' else (W - 176, 0, W, 96), kind='soft')
    return card


def bush(card, x, y, r=30, flowers=None, layer='mid'):
    """A round bush sitting on (x, y); flowers = a colour for a few blossoms."""
    lf = LEAF[card.light]
    g = card.lin('bushg', 0, lf[2], 1, lf[0])
    o = [f'<ellipse cx="{n(x)}" cy="{n(y - r * .78)}" rx="{n(r)}" ry="{n(r * .86)}" fill="{g}"/><ellipse cx="{n(x - r * .7)}" cy="{n(y - r * .4)}" rx="{n(r * .56)}" ry="{n(r * .46)}" fill="{g}"/><ellipse cx="{n(x + r * .72)}" cy="{n(y - r * .36)}" rx="{n(r * .52)}" ry="{n(r * .42)}" fill="{g}"/>',
         f'<path d="M{n(x - r * .8)},{n(y - r * .9)}Q{n(x - r * .5)},{n(y - r * 1.56)},{n(x + r * .1)},{n(y - r * 1.6)}" fill="none" stroke="{lf[3]}" stroke-width="3" stroke-linecap="round" opacity=".9"/>']
    if flowers:
        for a, b in ((-.4, -1.1), (.3, -.8), (-.1, -.5), (.6, -.4), (-.7, -.5)):
            o.append(f'<circle cx="{n(x + a * r)}" cy="{n(y + b * r)}" r="{n(max(2.6, r * .13))}" fill="{flowers}"/>')
    card.add(''.join(o), layer, name='bush', box=(x - r * 1.2, y - r * 1.64, x + r * 1.2, y), kind='soft')
    return card


def hedge(card, x0, x1, y, h=34, flowers=None, layer='mid'):
    """A clipped hedge from x0 to x1 standing on y."""
    lf = LEAF[card.light]
    g = card.lin('hedgeg', 0, lf[2], 1, lf[0])
    d, hi, x, i = f'M{n(x0)},{n(y)}V{n(y - h * .8)}', '', x0, 0
    while x < x1:
        w = min(46.0 + (i % 3) * 9, x1 - x)
        d += f'Q{n(x + w / 2)},{n(y - h - 8 - (i % 2) * 4)},{n(x + w)},{n(y - h * .8)}'
        hi += f'M{n(x + 5)},{n(y - h * .84)}Q{n(x + w / 2)},{n(y - h - 5 - (i % 2) * 4)},{n(x + w - 6)},{n(y - h * .86)}'
        x += w
        i += 1
    o = [f'<path d="{d}V{n(y)}Z" fill="{g}"/><path d="{hi}" fill="none" stroke="{lf[3]}" stroke-width="3" stroke-linecap="round" opacity=".9"/>']
    if flowers:
        r = card.rnd
        pts = [(r.uniform(x0 + 8, x1 - 8), r.uniform(y - h * .8, y - 6)) for _ in range(int((x1 - x0) / 34))]
        o.append(f'<g fill="{flowers}">' + ''.join(f'<circle cx="{n(a)}" cy="{n(b)}" r="3.6"/>' for a, b in pts) + '</g>')
    card.add(''.join(o), layer, name='hedge', box=(x0, y - h - 10, x1, y), kind='soft')
    return card


def tufts(card, pts=None, count=10, y0=None, y1=H - 8):
    """Grass tufts on a lawn at `pts`, or `count` of them scattered between y0 and y1 (never where the word stands)."""
    r = card.rnd
    if pts is None:
        y0 = y0 if y0 is not None else getattr(card, 'ground_y', 262) + 14
        pts = []
        for _ in range(count * 4):
            if len(pts) >= count:
                break
            x, y = r.uniform(10, W - 10), r.uniform(y0, y1)
            if in_calm(card, x, y, 16) or any(i['box'][0] - 8 < x < i['box'][2] + 8 and i['box'][1] < y < i['box'][3] + 10 for i in card.items if i['kind'] != 'soft'):
                continue
            pts.append((x, y))
    d = ''.join(f'M{n(x)},{n(y)}q-3,-8,-7,-10M{n(x)},{n(y)}q0,-9,1,-13M{n(x)},{n(y)}q3,-7,8,-9' for x, y in pts)
    card.add(f'<path d="{d}" fill="none" stroke="{card.L["lawn"][3]}" stroke-width="2" stroke-linecap="round"/>', 'ground')
    return card


def flowers(card, pts=None, count=6, col='#FFFFFF', centre='#F7C948', y0=None, y1=H - 8, layer='ground'):
    """Small ground flowers (daisies by default) at `pts` or scattered like tufts()."""
    r = card.rnd
    if pts is None:
        y0 = y0 if y0 is not None else getattr(card, 'ground_y', 262) + 14
        pts = []
        for _ in range(count * 4):
            if len(pts) >= count:
                break
            x, y = r.uniform(10, W - 10), r.uniform(y0, y1)
            if not in_calm(card, x, y, 16) and not any(i['box'][0] - 8 < x < i['box'][2] + 8 and i['box'][1] < y < i['box'][3] + 10 for i in card.items if i['kind'] != 'soft'):
                pts.append((x, y))
    o = f'<g fill="{col}">' + ''.join(f'<circle cx="{n(x)}" cy="{n(y)}" r="3.6"/>' for x, y in pts) + '</g>'
    o += '<path d="' + ''.join(f'M{n(x)},{n(y)}h.1' for x, y in pts) + f'" fill="none" stroke="{centre}" stroke-width="2.8" stroke-linecap="round"/>'
    card.add(o, layer)
    return card


def leaves(card, pts, cols=('#F2B63C', '#E99A2C', '#F4C24A'), s=.6, layer='fx'):
    """Loose leaves (falling, or lying on the ground) at pts = [(x, y, rotation), …]. Green ones: cols=LEAF colours."""
    card.add(''.join(leaf(x, y, a, cols[i % len(cols)], s) for i, (x, y, a) in enumerate(pts)), layer)
    return card


def puddle(card, x, y, rx=70, ry=None):
    ry = ry or rx * .2
    c = '#FFFFFF' if not card.L['dark'] else '#B9C6F8'
    card.add(f'<ellipse cx="{n(x)}" cy="{n(y)}" rx="{n(rx)}" ry="{n(ry)}" fill="{c}" opacity=".5"/><path d="M{n(x - rx * .6)},{n(y - ry * .2)}h{n(rx * .5)}M{n(x)},{n(y + ry * .3)}h{n(rx * .4)}" stroke="{c}" stroke-width="2" stroke-linecap="round" opacity=".9"/>', 'ground',
             name='puddle', box=(x - rx, y - ry, x + rx, y + ry), kind='soft')
    return card


# ---------------------------------------------------------------------------------------------------------- furniture
def bench(card, x, y, w=190, h=58, back=True, name='bench'):
    """A park bench seen from the front-side: the seat's top edge is the line y (sit a figure with at=(…, y)); legs reach y + h."""
    g = _wood(card)
    o = []
    if back:
        o.append(f'<path d="M{n(x - w / 2 + 12)},{n(y)}V{n(y - 58)}M{n(x + w / 2 - 12)},{n(y)}V{n(y - 58)}" stroke="{WOOD[2]}" stroke-width="8" stroke-linecap="round"/>'
                 f'<rect x="{n(x - w / 2)}" y="{n(y - 60)}" width="{n(w)}" height="13" rx="4" fill="{g}"/><rect x="{n(x - w / 2)}" y="{n(y - 40)}" width="{n(w)}" height="13" rx="4" fill="{g}"/>'
                 f'<path d="M{n(x - w / 2 + 4)},{n(y - 58)}H{n(x + w / 2 - 30)}" stroke="{WOOD[3]}" stroke-width="2.4" stroke-linecap="round"/>')
    o.append(f'<path d="M{n(x - w / 2 + 16)},{n(y + 8)}V{n(y + h)}M{n(x + w / 2 - 16)},{n(y + 8)}V{n(y + h)}" stroke="{WOOD[2]}" stroke-width="9" stroke-linecap="round"/>'
             f'<rect x="{n(x - w / 2 - 6)}" y="{n(y - 1)}" width="{n(w + 12)}" height="13" rx="5" fill="{g}"/><path d="M{n(x - w / 2 - 1)},{n(y + 1.5)}H{n(x + w / 2 - 24)}" stroke="{WOOD[3]}" stroke-width="2.6" stroke-linecap="round"/>')
    card.add(''.join(o), 'mid', name=name, box=(x - w / 2 - 6, y - (62 if back else 2), x + w / 2 + 6, y + h), kind='prop')
    card.shadow(x + 6, y + h + 1, w / 2 + 6)
    return y


def stool(card, x, y, w=62, h=44, col=None, name='stool'):
    """A small stool / stone seat: top edge on the line y, legs to y + h. col = (lit, mid, shade) for a stone or painted one."""
    c = _c3(col) if col else WOOD[:3]
    g = _form(card, 'st' + c[1].strip('#').lower(), *c)
    o = (f'<path d="M{n(x - w * .34)},{n(y + 8)}L{n(x - w * .42)},{n(y + h)}M{n(x + w * .34)},{n(y + 8)}L{n(x + w * .42)},{n(y + h)}" stroke="{c[2]}" stroke-width="7" stroke-linecap="round"/>'
         f'<rect x="{n(x - w / 2)}" y="{n(y - 1)}" width="{n(w)}" height="12" rx="5" fill="{g}"/><path d="M{n(x - w / 2 + 5)},{n(y + 1.5)}H{n(x + w * .2)}" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" opacity=".6"/>')
    card.add(o, 'mid', name=name, box=(x - w / 2, y - 1, x + w / 2, y + h), kind='prop')
    card.shadow(x + 4, y + h + 1, w * .56)
    return y


def chair(card, x, y, face='left', h=66, col=None, name='chair'):
    """A chair seen from the side: seat top on the line y, the back on the side away from `face`, legs to y + h."""
    c = _c3(col) if col else WOOD[:3]
    g = _form(card, 'ch' + c[1].strip('#').lower(), *c)
    s = 1 if face == 'left' else -1
    bx = x + s * 30
    o = (f'<path d="M{n(bx)},{n(y + h)}V{n(y - 76)}" stroke="{c[2]}" stroke-width="8" stroke-linecap="round"/><path d="M{n(x - s * 28)},{n(y + 8)}V{n(y + h)}" stroke="{c[1]}" stroke-width="8" stroke-linecap="round"/>'
         f'<rect x="{n(bx - 6)}" y="{n(y - 80)}" width="12" height="46" rx="5" fill="{g}"/><rect x="{n(x - 36)}" y="{n(y - 1)}" width="72" height="12" rx="5" fill="{g}"/>'
         f'<path d="M{n(x - 31)},{n(y + 1.5)}H{n(x + 14)}" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" opacity=".6"/>')
    card.add(o, 'mid', name=name, box=(x - 38, y - 82, x + 38, y + h), kind='prop')
    card.shadow(x + 4, y + h + 1, 46)
    return y


def table(card, x, y, w=220, h=110, kind='wood', name='table', layer='mid'):
    """A table seen from the side: the top surface is the line y (things stand on it), legs / pedestal to y + h.
    kind: wood (four legs) · desk (a panel with a drawer) · stone / round (a round top on a pedestal, seen a little from
    above: papers, cups and hands lie on the ellipse round the line y) · low (a tea table)."""
    c = {'stone': ('#FBF8F0', '#E6E0D4', '#C2BAAE'), 'round': WOOD[:3]}.get(kind, WOOD[:3])
    g = _form(card, 'tb' + c[1].strip('#').lower(), *c)
    o = []
    if kind in ('stone', 'round'):                        # a round top seen a little from above: things lie ON the ellipse round the line y
        ry = max(14.0, w * .09)
        o.append(f'<path d="M{n(x - w * .1)},{n(y + ry)}L{n(x - w * .16)},{n(y + h)}H{n(x + w * .16)}L{n(x + w * .1)},{n(y + ry)}Z" fill="{g}"/><ellipse cx="{n(x)}" cy="{n(y + h)}" rx="{n(w * .2)}" ry="6" fill="{c[2]}"/>'
                 f'<path d="M{n(x - w / 2)},{n(y + 4)}v9A{n(w / 2)},{n(ry)},0,0,0,{n(x + w / 2)},{n(y + 13)}v-9Z" fill="{c[2]}"/><ellipse cx="{n(x)}" cy="{n(y + 4)}" rx="{n(w / 2)}" ry="{n(ry)}" fill="{c[0]}"/>'
                 f'<path d="M{n(x - w * .44)},{n(y - 2)}Q{n(x - w * .2)},{n(y - ry + 4)},{n(x + w * .1)},{n(y - ry + 5)}" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" opacity=".8"/>')
        card.add(''.join(o), layer, name=name, box=(x - w / 2, y - ry + 4, x + w / 2, y + h), kind='prop')
        card.shadow(x + 8, y + h + 1, w * .4)
        return y
    if kind == 'desk':
        o.append(f'<rect x="{n(x - w / 2 + 8)}" y="{n(y + 10)}" width="{n(w - 16)}" height="{n(h - 10)}" rx="4" fill="{g}"/><rect x="{n(x + w * .1)}" y="{n(y + 22)}" width="{n(w * .32)}" height="26" rx="4" fill="{c[0]}" opacity=".7"/>'
                 f'<path d="M{n(x + w * .22)},{n(y + 35)}h{n(w * .08)}" stroke="{c[2]}" stroke-width="4" stroke-linecap="round"/>')
    else:
        o.append(f'<path d="M{n(x - w / 2 + 14)},{n(y + 10)}V{n(y + h)}M{n(x + w / 2 - 14)},{n(y + 10)}V{n(y + h)}" stroke="{c[2]}" stroke-width="10" stroke-linecap="round"/>')
    o.append(f'<rect x="{n(x - w / 2)}" y="{n(y - 1)}" width="{n(w)}" height="14" rx="6" fill="{g}"/><path d="M{n(x - w / 2 + 6)},{n(y + 1.6)}H{n(x + w * .22)}" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" opacity=".7"/>')
    card.add(''.join(o), layer, name=name, box=(x - w / 2, y - 1, x + w / 2, y + h), kind='prop')
    card.shadow(x + 8, y + h + 1, w * .5)
    return y


def tabletop(card, y=300, kind='cloth'):
    """A table / counter across the whole foreground, seen from the diner's side: its back edge is the line y and it
    fills the card to the bottom — the classic calm zone for the word (breakfast). kind: cloth · wood."""
    L = card.L
    c = L['cloth'] if kind == 'cloth' else (('#FFEFD0', '#FBDDB0', '#F2CB98') if not L['dark'] else ('#C9B6D8', '#A996C6', '#8A7AB4'))
    g = card.lin('ttop', 0, c[0], .5, c[1], 1, c[2], x1=0, y1=y, x2=0, y2=H, user=True)
    o = [f'<rect y="{n(y)}" width="{W}" height="{n(H - y)}" fill="{g}"/><rect y="{n(y)}" width="{W}" height="7" fill="#FFFFFF" opacity=".7"/>']
    if kind == 'cloth':
        d = ''
        for k in range(1, 9):
            xb = -160 + 140 * k
            pts = [(400 + (xb - 400) * (.55 + .45 * j / 8), y + (H - y) * j / 8) for j in range(9)]
            seg = [p for p in pts if not in_calm(card, p[0], p[1], 10)]
            if len(seg) > 1 and seg == pts:
                d += f'M{P(pts[0])}L{P(pts[-1])}'
        o.append(f'<path d="{d}" fill="none" stroke="{c[2]}" stroke-width="14" opacity=".25"/>')
    if card.calm:
        z = card.calm
        o.append(f'<ellipse cx="{n((z[0] + z[2]) / 2)}" cy="{n((z[1] + z[3]) / 2)}" rx="{n((z[2] - z[0]) * .6)}" ry="{n((z[3] - z[1]) * .6)}" fill="{card.glow("#FFFBEA" if not L["dark"] else "#FFE2A8")}" opacity=".5"/>')
    card.add(''.join(o), 'mid', name='table', box=(0, y, W, y + 8), kind='soft')
    card.table_y = y
    return y


def sofa(card, x, y, w=300, col=('#FFE3B4', '#F7C98E', '#E2A870'), name='sofa'):
    """A sofa seen from the front: the seat cushion's top is the line y (figures sit with pose 'sit_front' or 'cross')."""
    col = _c3(col)
    g = _form(card, 'sofa', *col)
    o = (f'<rect x="{n(x - w / 2)}" y="{n(y - 84)}" width="{n(w)}" height="120" rx="26" fill="{g}"/><path d="M{n(x - w / 2 + 22)},{n(y - 80)}Q{n(x)},{n(y - 88)},{n(x + w / 2 - 40)},{n(y - 80)}" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" opacity=".6"/>'
         f'<rect x="{n(x - w / 2 - 20)}" y="{n(y - 34)}" width="42" height="92" rx="19" fill="{col[1]}"/><rect x="{n(x + w / 2 - 22)}" y="{n(y - 34)}" width="42" height="92" rx="19" fill="{col[2]}"/>'
         f'<rect x="{n(x - w / 2 + 14)}" y="{n(y)}" width="{n(w - 28)}" height="34" rx="12" fill="{col[0]}"/><rect x="{n(x - w / 2 + 6)}" y="{n(y + 30)}" width="{n(w - 12)}" height="28" rx="8" fill="{col[1]}"/>'
         f'<path d="M{n(x)},{n(y + 2)}V{n(y + 32)}" stroke="{col[2]}" stroke-width="2" opacity=".5"/>')
    card.add(o, 'mid', name=name, box=(x - w / 2 - 20, y - 84, x + w / 2 + 20, y + 58), kind='prop')
    card.shadow(x, y + 60, w / 2 + 10)
    return y


def bed(card, x, y, w=420, head='left', quilt=('#BFE0F7', '#93C4EC', '#6FA6DC'), name='bed'):
    """A bed seen from the side: the mattress top is the line y; headboard and pillow at the `head` end; the quilt covers
    the other two thirds (a figure under it: pose 'sit_floor' drawn BEFORE the bed's quilt — call bed(…) after the figure)."""
    s = -1 if head == 'left' else 1
    hx = x + s * w / 2
    quilt = _c3(quilt)
    g = _form(card, 'quilt', *quilt)
    wg = _wood(card)
    o = (f'<rect x="{n(min(hx, hx + s * 16))}" y="{n(y - 92)}" width="16" height="150" rx="7" fill="{wg}"/>'
         f'<rect x="{n(x - w / 2)}" y="{n(y)}" width="{n(w)}" height="40" rx="10" fill="#FFFDF6"/><rect x="{n(x - w / 2)}" y="{n(y + 34)}" width="{n(w)}" height="26" rx="6" fill="{WOOD[1]}"/>'
         f'<ellipse cx="{n(hx - s * 62)}" cy="{n(y - 8)}" rx="56" ry="20" fill="#FFFFFF"/><path d="M{n(hx - s * 104)},{n(y - 14)}Q{n(hx - s * 62)},{n(y - 30)},{n(hx - s * 20)},{n(y - 14)}" fill="none" stroke="#E6E2F2" stroke-width="2"/>'
         f'<path d="M{n(x - s * w * .12)},{n(y - 12)}Q{n(x + s * w * .1)},{n(y - 30)},{n(x - s * -w / 2 * 1)},{n(y - 10)}V{n(y + 44)}H{n(x - s * w * .16)}Q{n(x - s * w * .2)},{n(y + 14)},{n(x - s * w * .12)},{n(y - 12)}Z" fill="{g}"/>')
    card.add(o, 'mid', name=name, box=(x - w / 2 - 16, y - 92, x + w / 2 + 16, y + 60), kind='prop')
    card.shadow(x, y + 62, w / 2 + 10)
    return y


def steps(card, x0, x1, y, count=3, rise=26, col=None, name='steps'):
    """Front steps seen head-on: the top landing is the line y; each step is `rise` lower and 26 px wider. Returns the
    y of each tread, top first — sit figures on one with pose 'sit_front'."""
    c = col or (('#FBF3E2', '#EADCC0', '#CDBB9A') if not card.L['dark'] else ('#A9B2E6', '#8B95D6', '#6C76BE'))
    o, ys = [], []
    for k in range(count):
        yy, e = y + k * rise, k * 26
        o.append(f'<rect x="{n(x0 - e)}" y="{n(yy)}" width="{n(x1 - x0 + 2 * e)}" height="{n(rise + 2)}" fill="{c[1]}"/><rect x="{n(x0 - e)}" y="{n(yy)}" width="{n(x1 - x0 + 2 * e)}" height="9" fill="{c[0]}"/>'
                 f'<path d="M{n(x0 - e)},{n(yy + rise + 1)}H{n(x1 + e)}" stroke="{c[2]}" stroke-width="2" opacity=".6"/>')
        ys.append(yy)
    card.add(''.join(o), 'mid', name=name, box=(x0 - count * 26, y, x1 + count * 26, y + count * rise), kind='soft')
    return ys


def door(card, x, y, w=120, h=230, opened=False, lit=False, col=('#F2A46C', '#DE8650', '#BF6A40'), name='door', layer='mid'):
    """A door standing on the line y (x = its centre). opened: the leaf swings aside and shows the inside; lit: a warm
    lit inside (the accent of a night / rain card)."""
    col = _c3(col)
    g = _form(card, 'door' + col[1].strip('#').lower(), *col)
    fr = '#FFFFFF' if not card.L['dark'] else '#C9D0F4'
    o = [f'<rect x="{n(x - w / 2 - 9)}" y="{n(y - h - 9)}" width="{n(w + 18)}" height="{n(h + 9)}" rx="4" fill="{fr}"/>']
    if opened:
        ig = card.lin('inside', 0, '#FFF3C4', 1, '#FFD890') if lit else card.lin('inside', 0, '#E9DCC6', 1, '#D2C0A4')
        o.append(f'<rect x="{n(x - w / 2)}" y="{n(y - h)}" width="{n(w)}" height="{n(h)}" fill="{ig}"/>')
    if lit:                                           # warm light from inside: a glow round the door and a pool on the ground
        card.add(f'<ellipse cx="{n(x)}" cy="{n(y - h * .5)}" rx="{n(w * 1.5)}" ry="{n(h * .9)}" fill="{card.glow("#FFE2A8")}" opacity=".6"/>', 'back')
        if opened:
            card.layers['shadow'].append(f'<path d="M{n(x - w / 2)},{n(y)}h{n(w)}l{n(w * .5)},{n(70)}h{n(-w * 2)}Z" fill="#FFE2A8" opacity=".5"/>')
    if opened:
        o.append(f'<path d="M{n(x + w / 2)},{n(y - h)}l{n(w * .42)},{n(14)}V{n(y + 12)}L{n(x + w / 2)},{n(y)}Z" fill="{g}"/><circle cx="{n(x + w / 2 + w * .32)}" cy="{n(y - h * .46)}" r="4.5" fill="#FFE2A0"/>')
    else:
        o.append(f'<rect x="{n(x - w / 2)}" y="{n(y - h)}" width="{n(w)}" height="{n(h)}" fill="{g}"/><rect x="{n(x - w / 2 + 14)}" y="{n(y - h + 16)}" width="{n(w - 28)}" height="{n(h * .36)}" rx="4" fill="{"#FFEDB4" if lit else col[0]}" opacity="{"1" if lit else ".6"}"/>'
                 f'<rect x="{n(x - w / 2 + 14)}" y="{n(y - h * .5)}" width="{n(w - 28)}" height="{n(h * .4)}" rx="4" fill="{col[0]}" opacity=".5"/><circle cx="{n(x + w / 2 - 15)}" cy="{n(y - h * .48)}" r="5" fill="#FFE2A0"/>')
    card.add(''.join(o), layer, name=name, box=(x - w / 2 - 9, y - h - 9, x + w / 2 + (w * .42 if opened else 9), y + (12 if opened else 0)), kind='soft')
    return (x, y - h)


def shelf(card, x, y, w=150, h=120, rows=2, name='shelf', layer='mid'):
    """A bookshelf standing on the line y (x = its centre): rows of book spines with abstract bands, no titles."""
    r, g = card.rnd, _wood(card)
    cols = ('#F58F7C', '#F7C24A', '#8FC6F0', '#9BD08A', '#C5A4E6', '#F9A65A')
    o = [f'<rect x="{n(x - w / 2)}" y="{n(y - h)}" width="{n(w)}" height="{n(h)}" rx="5" fill="{g}"/>']
    rh = (h - 10) / rows
    for k in range(rows):
        by, bx = y - h + 6 + k * rh, x - w / 2 + 8
        o.append(f'<rect x="{n(x - w / 2 + 6)}" y="{n(by)}" width="{n(w - 12)}" height="{n(rh - 6)}" fill="#8A5E44" opacity=".5"/>')
        while bx < x + w / 2 - 22:
            bw, bh = r.uniform(9, 15), (rh - 10) * r.uniform(.72, 1)
            o.append(f'<rect x="{n(bx)}" y="{n(by + rh - 6 - bh)}" width="{n(bw)}" height="{n(bh)}" rx="1.5" fill="{r.choice(cols)}"/>')
            bx += bw + 1.5
    card.add(''.join(o), layer, name=name, box=(x - w / 2, y - h, x + w / 2, y), kind='prop')
    return (x, y - h)


def house(card, x, y, w=260, h=190, wall=('#FFF6E4', '#F6E6CC', '#E6CFAE'), roof=('#F08A6C', '#D8684E'), door_col=('#E8503A', '#D9442F', '#B8362A'), floors=2, layer='mid', name='house'):
    """A small building seen from outside, standing on the line y: wall, a tiled roof with an eave, windows, a door,
    a shade strip under the eave and at the far corner (LESSONS #24)."""
    wall, door_col = _c3(wall), _c3(door_col)
    roof = _c3(roof)[:2] if isinstance(roof, str) else roof
    g = _form(card, 'hw' + wall[1].strip('#').lower(), *wall)
    x0 = x - w / 2
    o = [f'<rect x="{n(x0)}" y="{n(y - h)}" width="{n(w)}" height="{n(h)}" fill="{g}"/><rect x="{n(x0 + w - 16)}" y="{n(y - h)}" width="16" height="{n(h)}" fill="{wall[2]}" opacity=".6"/>',
         f'<path d="M{n(x0 - 22)},{n(y - h + 4)}L{n(x0 + 26)},{n(y - h - 58)}H{n(x0 + w - 26)}L{n(x0 + w + 22)},{n(y - h + 4)}Z" fill="{roof[0]}"/><path d="M{n(x0 - 22)},{n(y - h + 4)}H{n(x0 + w + 22)}" stroke="{roof[1]}" stroke-width="7" stroke-linecap="round"/>',
         f'<rect x="{n(x0)}" y="{n(y - h + 7)}" width="{n(w)}" height="9" fill="{wall[2]}" opacity=".5"/><path d="M{n(x0 - 14)},{n(y - h - 2)}L{n(x0 + 28)},{n(y - h - 54)}H{n(x0 + w * .5)}" fill="none" stroke="#FFE2C8" stroke-width="3" stroke-linecap="round" opacity=".8"/>']
    dw, dh = w * .2, min(h * .46, 96)
    o.append(f'<rect x="{n(x - dw / 2 - 5)}" y="{n(y - dh - 5)}" width="{n(dw + 10)}" height="{n(dh + 5)}" fill="#FFFFFF"/><rect x="{n(x - dw / 2)}" y="{n(y - dh)}" width="{n(dw)}" height="{n(dh)}" fill="{_form(card, "hd" + door_col[1].strip("#").lower(), *door_col)}"/><circle cx="{n(x + dw / 2 - 8)}" cy="{n(y - dh * .5)}" r="3.4" fill="#FFE2A0"/>')
    glass = card.L['win'][0] if card.L['dark'] or card.light == 'rain' else '#BFE3F5'
    for fl in range(floors):
        wy = y - h + 26 + fl * (h - 30) / floors
        for sx in (-.32, .32):
            if fl == floors - 1 and abs(sx) < .1:
                continue
            wx = x + sx * w
            o.append(f'<rect x="{n(wx - 22)}" y="{n(wy)}" width="44" height="{n(min(46, (h - 40) / floors - 14))}" rx="3" fill="{glass}" stroke="#FFFFFF" stroke-width="5"/><path d="M{n(wx)},{n(wy)}v{n(min(46, (h - 40) / floors - 14))}" stroke="#FFFFFF" stroke-width="3"/>')
    card.add(''.join(o), layer, name=name, box=(x0 - 22, y - h - 58, x0 + w + 22, y), kind='prop')
    card.shadow(x + 10, y + 2, w * .56, 9)
    return (x, y - h)


# -------------------------------------------------------------------------------------------------------- small props
def book(card, x, y, w=44, h=58, col=('#FFD750', '#F7B93A', '#D98A2A'), deg=0, opened=False, layer='mid', name='book', reg=True):
    """A book centred on (x, y). opened=True: two pages with abstract lines (never letters). Returns its SVG too, for held=…"""
    col = _c3(col)
    if opened:
        o = (f'<path d="M0,{n(-h / 2 + 4)}C{n(-w * .3)},{n(-h / 2 - 5)},{n(-w * .8)},{n(-h / 2 - 3)},{n(-w)},{n(-h / 2 + 2)}V{n(h / 2)}C{n(-w * .8)},{n(h / 2 - 5)},{n(-w * .3)},{n(h / 2 - 6)},0,{n(h / 2 + 2)}Z" fill="#FFFDF6"/>'
             f'<path d="M0,{n(-h / 2 + 4)}C{n(w * .3)},{n(-h / 2 - 5)},{n(w * .8)},{n(-h / 2 - 3)},{n(w)},{n(-h / 2 + 2)}V{n(h / 2)}C{n(w * .8)},{n(h / 2 - 5)},{n(w * .3)},{n(h / 2 - 6)},0,{n(h / 2 + 2)}Z" fill="#F3EBDD"/>'
             f'<path d="M{n(-w * .82)},{n(-h * .2)}h{n(w * .6)}M{n(-w * .82)},{n(-h * .02)}h{n(w * .6)}M{n(-w * .82)},{n(h * .16)}h{n(w * .4)}M{n(w * .2)},{n(-h * .2)}h{n(w * .6)}M{n(w * .2)},{n(-h * .02)}h{n(w * .6)}" fill="none" stroke="#C9BFAE" stroke-width="2.4" stroke-linecap="round"/>'
             f'<path d="M{n(-w)},{n(h / 2)}C{n(-w * .8)},{n(h / 2 - 5)},{n(-w * .3)},{n(h / 2 - 6)},0,{n(h / 2 + 2)}C{n(w * .3)},{n(h / 2 - 6)},{n(w * .8)},{n(h / 2 - 5)},{n(w)},{n(h / 2)}" fill="none" stroke="{col[1]}" stroke-width="4" stroke-linecap="round"/>')
        bw = w
    else:
        o = (f'<rect x="{n(-w / 2)}" y="{n(-h / 2)}" width="{n(w)}" height="{n(h)}" rx="4" fill="{col[0]}"/><rect x="{n(-w / 2)}" y="{n(-h / 2)}" width="{n(w * .16)}" height="{n(h)}" rx="3" fill="{col[1]}"/>'
             f'<rect x="{n(-w * .16)}" y="{n(-h * .26)}" width="{n(w * .46)}" height="{n(h * .2)}" rx="3" fill="#FFF8E7" opacity=".9"/><path d="M{n(-w / 2 + 3)},{n(h / 2 - 2)}h{n(w - 6)}" stroke="{col[2]}" stroke-width="3" stroke-linecap="round"/>')
        bw = w / 2
    xml = f'<g transform="translate({n(x)} {n(y)}) rotate({n(deg)})">{o}</g>'
    if reg:
        card.add(xml, layer, name=name, box=(x - bw - 2, y - h / 2 - 6, x + bw + 2, y + h / 2 + 4), kind='prop')
    return xml


def bag(card, x, y, s=1.0, col=('#FF9C8E', '#E87A72', '#FFE2A0'), layer='mid', name='schoolbag'):
    """A schoolbag standing on (x, y)."""
    col = _c3(col) if not (isinstance(col, tuple) and len(col) == 3) else col
    g = _form(card, 'bag' + col[0].strip('#').lower(), col[0], col[0], col[1])
    o = (f'<g transform="translate({n(x)} {n(y)}) scale({n(s)})"><path d="M-12,-62Q0,-80,12,-62" fill="none" stroke="{col[1]}" stroke-width="6" stroke-linecap="round"/>'
         f'<rect x="-33" y="-64" width="66" height="64" rx="16" fill="{g}"/><path d="M-33,-40Q0,-26,33,-40V-48Q33,-64,17,-64H-17Q-33,-64,-33,-48Z" fill="{col[1]}"/>'
         f'<rect x="-19" y="-26" width="38" height="20" rx="6" fill="{col[1]}" opacity=".7"/><rect x="-5" y="-42" width="10" height="13" rx="3" fill="{col[2]}"/><path d="M-27,-52Q-18,-60,-6,-61" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" opacity=".6"/></g>')
    card.add(o, layer, name=name, box=(x - 34 * s, y - 80 * s, x + 34 * s, y), kind='prop')
    if layer == 'mid':
        card.shadow(x + 4, y + 1, 36 * s)
    return (x, y - 64 * s)


def ball(card, x, y, r=22, kind='football', col=('#FFFFFF', '#E6E8F2'), layer='mid', name='ball', shadow=True):
    """A ball centred on (x, y): football (black patches) · plain (col) · basket."""
    c = {'basket': ('#FFB36A', '#E8803A')}.get(kind, _c3(col)[:2] if isinstance(col, str) else col)
    g = card.rad('ball' + c[1].strip('#').lower(), 0, c[0], 1, c[1], cx=.36, cy=.32, r=.8)
    o = [f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r)}" fill="{g}"/>']
    if kind == 'football':
        o.append(f'<path d="M{n(x)},{n(y - r * .36)}l{n(r * .34)},{n(r * .25)}l{n(-r * .13)},{n(r * .4)}h{n(-r * .42)}l{n(-r * .13)},{n(-r * .4)}Z" fill="#4A4E6A"/>'
                 f'<path d="M{n(x)},{n(y - r * .36)}V{n(y - r * .9)}M{n(x + r * .34)},{n(y - r * .11)}L{n(x + r * .84)},{n(y - r * .3)}M{n(x + r * .21)},{n(y + r * .29)}L{n(x + r * .52)},{n(y + r * .76)}M{n(x - r * .21)},{n(y + r * .29)}L{n(x - r * .52)},{n(y + r * .76)}M{n(x - r * .34)},{n(y - r * .11)}L{n(x - r * .84)},{n(y - r * .3)}" stroke="#4A4E6A" stroke-width="{n(max(1.6, r * .09))}" stroke-linecap="round"/>')
    elif kind == 'basket':
        o.append(f'<path d="M{n(x - r)},{n(y)}H{n(x + r)}M{n(x)},{n(y - r)}V{n(y + r)}M{n(x - r * .7)},{n(y - r * .7)}Q{n(x - r * .1)},{n(y)},{n(x - r * .7)},{n(y + r * .7)}M{n(x + r * .7)},{n(y - r * .7)}Q{n(x + r * .1)},{n(y)},{n(x + r * .7)},{n(y + r * .7)}" fill="none" stroke="#A8502A" stroke-width="1.8"/>')
    o.append(f'<path d="M{n(x - r * .7)},{n(y - r * .5)}Q{n(x - r * .4)},{n(y - r * .86)},{n(x)},{n(y - r * .9)}" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round" opacity=".8"/>')
    card.add(''.join(o), layer, name=name, box=(x - r, y - r, x + r, y + r), kind='prop')
    if shadow:
        card.shadow(x + 3, y + r + 1, r * .9)
    return (x, y)


def cup(card, x, y, s=1.0, col=('#FFFFFF', '#E9EBFA', '#B9BEE2'), kind='mug', steam_h=0, drink='#FFF4D6', layer='mid', name='cup', reg=True):
    """A mug / glass standing on (x, y). steam_h > 0 adds a soft steam cloud of that height. Returns the SVG too (held=…)."""
    col = _c3(col)
    if kind == 'glass':
        o = (f'<path d="M-14,-44L-11,0H11L14,-44Z" fill="#FFFFFF" opacity=".5"/><path d="M-13,-30L-11,0H11L13,-30Z" fill="{drink}" opacity=".9"/><path d="M-14,-44H14" stroke="#FFFFFF" stroke-width="2.4" stroke-linecap="round"/>'
             f'<path d="M-9.5,-38L-8,-6" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" opacity=".9"/>')
        hh = 44
    else:
        g = _form(card, 'cup' + col[1].strip('#').lower(), *col)
        o = (f'<path d="M15,-24Q30,-22,26,-10Q22,-3,13,-6" fill="none" stroke="{col[1]}" stroke-width="5" stroke-linecap="round"/><path d="M-16,-32H16L13,-3Q12,0,8,0H-8Q-12,0,-13,-3Z" fill="{g}"/>'
             f'<ellipse cx="0" cy="-32" rx="16" ry="4.5" fill="{drink}"/><path d="M-12.5,-27L-10.5,-6" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" opacity=".9"/>')
        hh = 34
    xml = f'<g transform="translate({n(x)} {n(y)}) scale({n(s)})">{o}</g>'
    if reg:
        card.add(xml, layer, name=name, box=(x - 17 * s, y - hh * s, x + 28 * s, y), kind='prop')
        if steam_h:
            steam(card, x, y - hh * s - 4, steam_h)
    return xml


def bowl(card, x, y, w=60, col=('#FFFFFF', '#E9EBFA', '#B9BEE2'), band='#5B66BE', food=None, layer='mid', name='bowl'):
    """A bowl standing on (x, y); food = a fill colour for what is in it."""
    col = _c3(col)
    g = _form(card, 'bowl' + col[1].strip('#').lower(), *col)
    h = w * .46
    o = (f'<path d="M{n(x - w / 2)},{n(y - h)}Q{n(x - w * .44)},{n(y)},{n(x - w * .16)},{n(y)}H{n(x + w * .16)}Q{n(x + w * .44)},{n(y)},{n(x + w / 2)},{n(y - h)}Z" fill="{g}"/>'
         f'<ellipse cx="{n(x)}" cy="{n(y - h)}" rx="{n(w / 2)}" ry="{n(w * .1)}" fill="{food or "#F8E6C0"}"/><path d="M{n(x - w * .46)},{n(y - h * .72)}Q{n(x)},{n(y - h * .5)},{n(x + w * .46)},{n(y - h * .72)}" fill="none" stroke="{band}" stroke-width="2.4"/>')
    card.add(o, layer, name=name, box=(x - w / 2, y - h - w * .1, x + w / 2, y), kind='prop')
    return (x, y - h)


def pencil(card, tip, end, col=('#FFD750', '#F7B93A'), w=9, layer='mid', reg=False):
    """A pencil from its tip to its end (canvas points). Returns the SVG (pass it as held=… to put it in a hand)."""
    col = _c3(col)[1:] if isinstance(col, str) else _c3(col)[:2]
    L = math.hypot(end[0] - tip[0], end[1] - tip[1])
    a = math.degrees(math.atan2(end[1] - tip[1], end[0] - tip[0]))
    h = w / 2
    xml = (f'<g transform="translate({n(tip[0])} {n(tip[1])}) rotate({n(a)})"><path d="M0,0L{n(w * 1.3)},{n(-h)}V{n(h)}Z" fill="#F3D2A8"/><path d="M0,0L{n(w * .45)},{n(-h * .36)}V{n(h * .36)}Z" fill="{col[1]}"/>'
           f'<rect x="{n(w * 1.3)}" y="{n(-h)}" width="{n(L - w * 2.2)}" height="{n(w)}" fill="{col[0]}"/><rect x="{n(w * 1.3)}" y="{n(h * .2)}" width="{n(L - w * 2.2)}" height="{n(h * .8)}" fill="{col[1]}"/>'
           f'<rect x="{n(L - w * .9)}" y="{n(-h)}" width="{n(w * .9)}" height="{n(w)}" rx="2" fill="#F58FA0"/></g>')
    if reg:
        card.add(xml, layer, name='pencil', box=(min(tip[0], end[0]) - 4, min(tip[1], end[1]) - 4, max(tip[0], end[0]) + 4, max(tip[1], end[1]) + 4), kind='soft')
    return xml


def paper(card, x, y, w=90, h=62, deg=0, lines=3, layer='mid', name='paper', skew=.3):
    """A sheet of paper lying on a surface, centred on (x, y) and seen at an angle (skew); abstract pencil lines, no letters."""
    k = w * skew
    o = (f'<path d="M{n(-w / 2 + k)},{n(-h / 2)}H{n(w / 2 + k)}L{n(w / 2 - k)},{n(h / 2)}H{n(-w / 2 - k)}Z" fill="#FFFEF8"/><path d="M{n(-w / 2 - k)},{n(h / 2)}H{n(w / 2 - k)}" stroke="#E6DCC8" stroke-width="2"/>'
         + ''.join(f'<path d="M{n(-w * .32 + k * (1 - 2 * (j + 1) / (lines + 2)))},{n(-h / 2 + h * (j + 1) / (lines + 2))}h{n(w * (.56 if j < lines - 1 else .3))}" stroke="#B9B2C8" stroke-width="2.2" stroke-linecap="round"/>' for j in range(lines)))
    card.add(f'<g transform="translate({n(x)} {n(y)}) rotate({n(deg)})">{o}</g>', layer, name=name, box=(x - w / 2 - k, y - h / 2, x + w / 2 + k, y + h / 2), kind='prop')
    return (x, y)


def umbrella(card, x, y, r=110, col=('#FF8A72', '#F06A5A', '#D8483E'), hand=None, tilt=0, layer='mid', name='umbrella'):
    """An open umbrella: (x, y) is the top of its dome, r its half width; the shaft runs to `hand` (a figure's hand)."""
    col = _c3(col)
    g = _form(card, 'umb' + col[1].strip('#').lower(), *col)
    hh = r * .52
    o = [f'<path d="M{n(-r)},{n(hh)}C{n(-r * .9)},{n(-hh * .1)},{n(-r * .45)},{n(-hh * .1)},0,0C{n(r * .45)},{n(-hh * .1)},{n(r * .9)},{n(-hh * .1)},{n(r)},{n(hh)}'
         + ''.join(f'Q{n(r - (k + .5) * r * .5)},{n(hh - 14)},{n(r - (k + 1) * r * .5)},{n(hh)}' for k in range(4)) + f'Z" fill="{g}"/>',
         f'<path d="M0,0Q{n(-r * .3)},{n(hh * .4)},{n(-r * .5)},{n(hh)}M0,0V{n(hh)}M0,0Q{n(r * .3)},{n(hh * .4)},{n(r * .5)},{n(hh)}" fill="none" stroke="{col[2]}" stroke-width="2" opacity=".6"/>',
         f'<path d="M{n(-r * .92)},{n(hh * .78)}C{n(-r * .8)},{n(hh * .1)},{n(-r * .4)},{n(-hh * .02)},{n(-r * .1)},{n(hh * .02)}" fill="none" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" opacity=".7"/><path d="M0,0V-9" stroke="{col[2]}" stroke-width="4" stroke-linecap="round"/>']
    dome = f'<g transform="translate({n(x)} {n(y)}) rotate({n(tilt)})">' + ''.join(o) + '</g>'
    shaft = ''
    if hand:
        b = rot((0, hh * .1), tilt)
        shaft = f'<path d="M{n(x + b[0])},{n(y + b[1])}L{n(hand[0])},{n(hand[1] + 16)}" stroke="#8E97D0" stroke-width="4.5" stroke-linecap="round"/>'
    card.add(shaft + dome, layer, name=name, box=(x - r, y - 10, x + r, y + hh), kind='prop')
    return shaft + dome


def bird(card, x, y, s=1.0, col=('#8FD0F6', '#4C96D8', '#FFF8EE'), face='left', sing=False, layer='mid', name='bird'):
    """A small round bird perched on (x, y) (its feet). sing=True opens the beak. face: left / right."""
    if face not in ('left', 'right'):
        raise SystemExit("bird: face must be 'left' or 'right' — pass options by keyword")
    col = (_c3(col)[0], _c3(col)[1], '#FFF8EE') if isinstance(col, str) or len(col) < 3 else col
    g = card.rad('bird' + col[1].strip('#').lower(), 0, col[0], 1, col[1], cx=.35, cy=.3, r=.9)
    beak = '<path d="M-22,-34L-36,-38L-23,-30Z" fill="#F7B93A"/><path d="M-22,-31L-34,-27L-22,-27Z" fill="#E89A2C"/>' if sing else '<path d="M-22,-34L-35,-30L-22,-27Z" fill="#F7B93A"/>'
    o = (f'<path d="M14,-14L40,-6L16,-4Z" fill="{col[1]}"/><ellipse cx="0" cy="-20" rx="21" ry="18" fill="{g}"/><ellipse cx="-4" cy="-13" rx="13" ry="10" fill="{col[2]}"/><circle cx="-12" cy="-32" r="13" fill="{g}"/>'
         f'<path d="M2,-24Q16,-26,20,-12Q8,-8,2,-24Z" fill="{col[1]}"/>{beak}<ellipse cx="-15" cy="-34" rx="2.4" ry="3" fill="#3A2018"/><circle cx="-15.8" cy="-35" r=".9" fill="#FFFFFF"/>'
         f'<path d="M-4,-3V0M4,-3V0" stroke="#E89A2C" stroke-width="2.2" stroke-linecap="round"/><path d="M-22,-40Q-14,-47,-4,-42" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round" opacity=".7"/>')
    m = -s if face == 'right' else s
    card.add(f'<g transform="translate({n(x)} {n(y)}) scale({n(m)} {n(s)})">{o}</g>', layer, name=name, box=(x - 40 * s, y - 46 * s, x + 40 * s, y), kind='prop')
    return (x - m * 36, y - 34 * s)                 # the tip of the beak


def sound(card, x, y, deg=0, count=3, col='#F7B93A', size=1.0, layer='fx'):
    """Widening arcs for a voice or a sound, leaving (x, y) in direction deg (0 = to the right, 90 = down, 180 = left)."""
    o = ''.join(f'<path d="M{n(10 + 11 * k)},{n(-(6 + 5 * k))}Q{n(16 + 13 * k)},0,{n(10 + 11 * k)},{n(6 + 5 * k)}" fill="none" stroke="{col}" stroke-width="3" stroke-linecap="round" opacity="{n(1 - k * .22)}"/>' for k in range(count))
    card.add(f'<g transform="translate({n(x)} {n(y)}) rotate({n(deg)}) scale({n(size)})">{o}</g>', layer)
    return card


def steam(card, x, y, h=46, layer='fx'):
    """A soft steam cloud rising from (x, y) with one short curl (never across a face)."""
    card.add(f'<ellipse cx="{n(x)}" cy="{n(y - h * .5)}" rx="{n(h * .3)}" ry="{n(h * .56)}" fill="{card.glow("#FFFFFF")}" opacity=".8"/>'
             f'<path d="M{n(x - 4)},{n(y)}q-6,{n(-h * .25)},0,{n(-h * .45)}q5,{n(-h * .2)},1,{n(-h * .36)}" fill="none" stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" opacity=".8"/>', layer)
    return card


def glint(card, x, y, s=8, col='#FFFFFF', layer='fx'):
    """A four-point glint on glass, water, metal (2–3 per card at most; never on the word)."""
    card.add(glint_xml(x, y, s, col), layer)
    return card


def bokeh(card, pts, col='#FFF8DE', layer='fx'):
    """Soft filled light discs at pts = [(x, y, r), …] (5–6 at most, in the far or near plane, never on a face)."""
    g = card.glow(col)
    card.add(''.join(f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(q)}" fill="{g}" opacity=".5"/>' for x, y, q in pts), layer)
    return card


def shape(card, d, fill, name=None, box=None, rim=None, layer='mid', extra=''):
    """Your own prop: a path `d` with a fill (a colour, or lit→shade colours (a, b, c) for a form gradient); rim = a path
    along its upper-left edge for the warm highlight. Give name + box so the layout check sees it."""
    if isinstance(fill, (tuple, list)):
        fill = _form(card, 'sh' + ''.join(c.strip('#').lower()[:3] for c in fill), *fill)
    o = f'<path d="{d}" fill="{fill}"{extra}/>'
    if rim:
        o += f'<path d="{rim}" fill="none" stroke="{card.L["rim"]}" stroke-width="2.6" stroke-linecap="round" opacity=".9"/>'
    card.add(o, layer, name=name, box=box, kind='prop')
    return card


def plant(card, x, y, s=1.0, pot=('#FFFFFF', '#E9EBFA', '#B9BEE2'), layer='mid', name='plant'):
    """A potted plant standing on (x, y) — a quiet filler for a sill, a shelf top, a corner."""
    lf, pot = LEAF[card.light], _c3(pot)
    g = _form(card, 'pot' + pot[1].strip('#').lower(), *pot)
    o = (''.join(f'<path d="M0,-30C{n(dx * .3)},{n(-60)},{n(dx * .9)},{n(-74 + abs(dx) * .3)},{n(dx)},{n(-88 + abs(dx) * .5)}C{n(dx * .7)},{n(-60)},{n(dx * .5)},{n(-44)},0,-30Z" fill="{lf[k % 3]}"/>' for k, dx in enumerate((-34, -14, 8, 30, 46)))
         + f'<path d="M-21,-32H21L16,0H-16Z" fill="{g}"/><rect x="-24" y="-37" width="48" height="9" rx="3" fill="{pot[0]}"/><path d="M-17,-24h34" stroke="#5B66BE" stroke-width="2.2" opacity=".7"/>')
    card.add(f'<g transform="translate({n(x)} {n(y)}) scale({n(s)})">{o}</g>', layer, name=name, box=(x - 40 * s, y - 92 * s, x + 50 * s, y), kind='soft')
    return (x, y - 92 * s)


def picture(card, x, y, w=96, h=72, layer='back', name='picture'):
    """A framed picture on the wall, centred on (x, y): an abstract little landscape, no text — a quiet wall filler."""
    o = (f'<rect x="{n(x - w / 2 - 6)}" y="{n(y - h / 2 - 6)}" width="{n(w + 12)}" height="{n(h + 12)}" rx="4" fill="#FFFFFF"/><rect x="{n(x - w / 2)}" y="{n(y - h / 2)}" width="{n(w)}" height="{n(h)}" fill="#DCEEF6"/>'
         f'<path d="M{n(x - w / 2)},{n(y + h * .2)}Q{n(x - w * .2)},{n(y - h * .1)},{n(x)},{n(y + h * .16)}T{n(x + w / 2)},{n(y + h * .1)}V{n(y + h / 2)}H{n(x - w / 2)}Z" fill="#BFE0A8"/><circle cx="{n(x + w * .22)}" cy="{n(y - h * .2)}" r="{n(h * .12)}" fill="#FFE49A"/>'
         f'<rect x="{n(x - w / 2 - 6)}" y="{n(y - h / 2 - 6)}" width="{n(w + 12)}" height="{n(h + 12)}" rx="4" fill="none" stroke="#E6CDA8" stroke-width="3"/>')
    card.add(o, layer, name=name, box=(x - w / 2 - 6, y - h / 2 - 6, x + w / 2 + 6, y + h / 2 + 6), kind='soft')
    return card
