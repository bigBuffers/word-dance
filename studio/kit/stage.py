"""kit.stage — the five house light setups (STYLE.md §1) and the places they light: sky, distance, ground, room, window.

Each setup is a palette + a light recipe taken from the approved cards (studio/pilots/B/STYLE.md §2): ONE source at the
upper left, a warm wash over the far plane, cool shadows, a bright key. A card picks one and never mixes two.
"""
from __future__ import annotations

from .base import H, W, P, n

LIGHTS = {
    'window': dict(zh='晨光窗', sun=(118, 96), sky=(0, '#BFE3F5', .6, '#FFF1CC', 1, '#FFE3B0'),
                   sun_g=(0, '#FFFFFF', .12, '#FFFFFF', .22, '#FFF4B8', .5, ('#FFD67A', .5), 1, ('#FFC56B', 0)), sun_r=120,
                   bloom=(0, ('#FFF3C4', .7), .3, ('#FFD88F', .35), .6, ('#FFB573', .12), 1, ('#FF9E6A', 0)), bloom_r=540,
                   shadow='#9A78B8', shadow_op=.28, rim='#FFEBC0', green=('#7DB05C', '#9FC777', '#CFE3B0'),
                   blocks=('#F3D8BC', '#F5DCC6', '#E9D8E2', '#F6DDBE'), roofs=('#E6C0A2', '#E2B9A0', '#D8BECD', '#E5BE9C'), win=('#FFF6D8', '#EBCDB8'),
                   lawn=('#CBE38A', '#9AC65C', '#E6F2A8', '#7DB04C'), path=('#FFF3D3', '#FCE7BC', '#F5D8A8', '#E2C08C'),
                   wall=('#D3ECE2', '#C6E2EA', '#BDD6EE'), floor=('#FBE6BE', '#EFCB98', '#D9AE78'), cloth=('#FFF9EC', '#FFEFD4', '#F3DDB8'),
                   frame=('#FFFFFF', '#C9D2EE', '#9EAAD8'), dark=False),
    'golden': dict(zh='金色户外', sun=(96, 74), sky=(0, '#CDEAF5', .55, '#FFF1CC', 1, '#FFE0A8'),
                   sun_g=(0, '#FFFFFF', .12, '#FFFFFF', .22, '#FFF4B8', .5, ('#FFD67A', .5), 1, ('#FFC56B', 0)), sun_r=130,
                   bloom=(0, ('#FFF3C4', .75), .3, ('#FFD88F', .4), .6, ('#FFB573', .15), 1, ('#FF9E6A', 0)), bloom_r=560,
                   shadow='#8A68AA', shadow_op=.3, rim='#FFEBC0', green=('#7DB05C', '#9FC777', '#CFE3B0'),
                   blocks=('#F3D8BC', '#F5DCC6', '#E9D8E2', '#F6DDBE'), roofs=('#E6C0A2', '#E2B9A0', '#D8BECD', '#E5BE9C'), win=('#FFF6D8', '#EBCDB8'),
                   lawn=('#CBE38A', '#9AC65C', '#E6F2A8', '#7DB04C'), path=('#FFF3D3', '#FCE7BC', '#F5D8A8', '#E2C08C'),
                   wall=('#FCEFD6', '#F8E4CC', '#F1D8C6'), floor=('#FBE3B8', '#F0CB96', '#D9AE78'), cloth=('#FFF9EC', '#FFEFD4', '#F3DDB8'),
                   frame=('#FFFFFF', '#E8D6C0', '#CDB79E'), dark=False),
    'bright': dict(zh='晴空亮水', sun=(108, 66), sky=(0, '#5DB7F0', .6, '#A9DDF8', 1, '#E2F4FC'),
                   sun_g=(0, '#FFFFFF', .22, '#FFFFFF', .4, ('#FFFBE0', .8), 1, ('#FFF4C0', 0)), sun_r=84,
                   bloom=(0, ('#FFFFFF', .5), .4, ('#FFF8DC', .2), 1, ('#FFFFFF', 0)), bloom_r=480,
                   shadow='#5B6BB0', shadow_op=.32, rim='#FFFFFF', green=('#5FB06A', '#8ACB7A', '#C4E8B0'),
                   blocks=('#F7F3EA', '#EEF3F8', '#FBEEDD', '#F0F0F6'), roofs=('#E8A28C', '#9DB8D8', '#E6B98C', '#B8C2DC'), win=('#BFE0F5', '#D8E6F0'),
                   lawn=('#B5E27C', '#7CC656', '#DDF5A8', '#5FA844'), path=('#FFFBEF', '#F4EEDC', '#E9E0C6', '#D8CCAA'),
                   wall=('#EEF6F8', '#E2F0F6', '#D6E8F4'), floor=('#F8E8C6', '#EAD2A2', '#D2B27E'), cloth=('#FFFFFF', '#F4F8FC', '#DCE8F2'),
                   frame=('#FFFFFF', '#D2E0EE', '#A8BED8'), dark=False),
    'rain': dict(zh='雨天柔光', sun=(-200, -300), sky=(0, '#BFCDE0', .6, '#DCE4EE', 1, '#EEF0F0'), sun_g=None, sun_r=0,
                 bloom=(0, ('#FFFFFF', .45), 1, ('#FFFFFF', 0)), bloom_r=620, bloom_at=(400, -60),
                 shadow='#6C7AA8', shadow_op=.25, rim='#FFFFFF', green=('#8FB79A', '#A9C9B0', '#CFE0D2'),
                 blocks=('#C6D0E2', '#B9C6DA', '#CCD3E4', '#C0CBDF'), roofs=('#A9B6CE', '#A0AFC8', '#B3BDD4', '#A6B4CC'), win=('#FFE1A0', '#DCE4F0'),
                 lawn=('#B9D8A6', '#8FBE86', '#D6EAC4', '#6FA070'), path=('#DDE6F0', '#C9D6E6', '#B9C9DE', '#A9BAD2'),
                 wall=('#E3EAF0', '#D6E0EA', '#CBD7E4'), floor=('#EADBC2', '#D9C6A8', '#BFA888'), cloth=('#FFFDF6', '#F3EFE6', '#DDD6C8'),
                 frame=('#FFFFFF', '#CDD6E4', '#A6B4CC'), dark=False),
    'night': dict(zh='月夜灯光', sun=(110, 84), sky=(0, '#3B4C9A', 1, '#8FA3E0'), sun_g=None, sun_r=0,
                  bloom=(0, ('#DCE4FF', .35), .5, ('#B9C6F8', .12), 1, ('#B9C6F8', 0)), bloom_r=330,
                  shadow='#2C3470', shadow_op=.35, rim='#DCE4FF', green=('#4A5CA8', '#5A6CB8', '#7184CE'),
                  blocks=('#5C6AB8', '#6573C0', '#5361AE', '#6A78C6'), roofs=('#4B58A4', '#5462AE', '#44509A', '#5866B2'), win=('#FFD98A', '#7E8CD4'),
                  lawn=('#5B72C0', '#3F4F9C', '#8FA3E0', '#33418A'), path=('#93A0DE', '#7B89D0', '#6876C2', '#5A68B0'),
                  wall=('#8A96DA', '#7682CC', '#6470BE'), floor=('#A99CCB', '#8A80BA', '#6E66A6'), cloth=('#F4EEDC', '#DCD6E6', '#B9B6DC'),
                  frame=('#E6EAFB', '#A9B4E4', '#7C88CC'), dark=True, halo=True),
}


def _bloom(card):
    if card.layers['bloom']:
        return
    L = card.L
    c = L.get('bloom_at', L['sun'])
    card.rad('bloom', *L['bloom'], cx=c[0], cy=c[1], r=L['bloom_r'], user=True)
    card.layers['bloom'].append(f'<rect width="{W}" height="{H}" fill="url(#bloom)"/>')


def in_calm(card, x, y, pad=10):
    z = card.calm
    return bool(z) and z[0] - pad < x < z[2] + pad and z[1] - pad < y < z[3] + pad


def sky(card, horizon=262, clouds=2, moon='crescent', stars=26, milky=0):
    """Outdoors: the sky down to `horizon`, the sun (or the moon and stars at night), clouds. Call it first."""
    L, r = card.L, card.rnd
    card.horizon = horizon
    g = card.lin('sky', *L['sky'])
    out = [f'<rect width="{W}" height="{n(horizon + 46)}" fill="{g}"/>']
    sx, sy = L['sun']
    if L['sun_g']:
        card.rad('sun', *L['sun_g'], cx=sx, cy=sy, r=L['sun_r'], user=True)
        out.append(f'<circle cx="{n(sx)}" cy="{n(sy)}" r="{n(L["sun_r"])}" fill="url(#sun)"/>')
    if card.light == 'night':
        if moon:
            out.append(f'<circle cx="{n(sx)}" cy="{n(sy)}" r="92" fill="{card.glow("#DCE4FF")}" opacity=".5"/>')
        if moon == 'full':
            card.rad('moon', 0, '#FFFDF0', .7, '#FFF3C4', 1, '#FFE49A', cx=.4, cy=.38, r=.75)
            out.append(f'<circle cx="{n(sx)}" cy="{n(sy)}" r="40" fill="url(#moon)"/><ellipse cx="{n(sx - 12)}" cy="{n(sy - 8)}" rx="9" ry="6" fill="#F4D98A" opacity=".5"/><circle cx="{n(sx + 14)}" cy="{n(sy + 12)}" r="6" fill="#F4D98A" opacity=".4"/>')
        elif moon:
            out.append(f'<path d="M{n(sx + 14)},{n(sy - 46)}A48,48,0,1,0,{n(sx + 46)},{n(sy + 22)}A38,38,0,1,1,{n(sx + 14)},{n(sy - 46)}Z" fill="#FFF0B8"/>')
        pts = []
        for _ in range(stars):
            x, y = r.uniform(10, 790), r.uniform(8, horizon - 40)
            if (moon and abs(x - sx) < 70 and abs(y - sy) < 70) or in_calm(card, x, y, 6):
                continue
            pts.append((x, y))
        if milky:                                    # a band of many small stars from the lower left to the upper right
            out.append(f'<ellipse cx="400" cy="{n(horizon * .42)}" rx="470" ry="{n(horizon * .2)}" transform="rotate(-16 400 {n(horizon * .42)})" fill="{card.glow("#C9D4FF")}" opacity=".5"/>')
            for _ in range(milky):
                t_ = r.uniform(0, 1)
                x, y = 20 + 760 * t_ + r.gauss(0, 30), horizon * (.66 - .5 * t_) + r.gauss(0, horizon * .09)
                if 4 < x < 796 and 4 < y < horizon - 20 and not in_calm(card, x, y, 6):
                    pts.append((x, y))
        for k, (w_, op) in enumerate(((2.4, .7), (3.6, .9), (5.2, 1))):
            d = ''.join(f'M{n(x)},{n(y)}h.1' for i, (x, y) in enumerate(pts) if (i * 7 + 3) % 10 in ((0, 1, 2, 3, 4, 5), (6, 7, 8), (9,))[k])
            if d:
                out.append(f'<path d="{d}" fill="none" stroke="#FFFFFF" stroke-width="{w_}" stroke-linecap="round" opacity="{op}"/>')
        for x, y in pts[:4]:
            out.append(glint_xml(x, y, 7, '#FFFFFF'))
    card.add(''.join(out), 'back')
    cl = []
    for i in range(clouds):
        x, y, w = r.uniform(200, 720), r.uniform(28, max(60, horizon - 150)), r.uniform(90, 150)
        if abs(x - sx) < 120 or in_calm(card, x, y, 30):
            x, y = r.uniform(430, 760), r.uniform(24, 70)
        cl.append(cloud_xml(card, x, y, w))
    if cl:
        card.add(''.join(cl), 'far')
    _bloom(card)
    return card


def cloud_xml(card, x, y, w):
    col, op = {'night': ('#7C8CD6', .5), 'rain': ('#FFFFFF', .6), 'bright': ('#FFFFFF', .95)}.get(card.light, ('#FFF9EA', .8))
    return (f'<g fill="{col}" opacity="{n(op)}"><ellipse cx="{n(x)}" cy="{n(y + w * .07)}" rx="{n(w * .5)}" ry="{n(w * .11)}"/>'
            f'<ellipse cx="{n(x - w * .12)}" cy="{n(y - w * .03)}" rx="{n(w * .24)}" ry="{n(w * .13)}"/><ellipse cx="{n(x + w * .16)}" cy="{n(y)}" rx="{n(w * .2)}" ry="{n(w * .1)}"/></g>')


def glint_xml(x, y, s, col='#FFFFFF', op=None):
    o = f' opacity="{n(op)}"' if op else ''
    return f'<path d="M{n(x)},{n(y - s)}Q{n(x)},{n(y)},{n(x + s)},{n(y)}Q{n(x)},{n(y)},{n(x)},{n(y + s)}Q{n(x)},{n(y)},{n(x - s)},{n(y)}Q{n(x)},{n(y)},{n(x)},{n(y - s)}Z" fill="{col}"{o}/>'


def town(card, base=None, x0=-10, x1=810, hmin=70, hmax=170, trees=True, gap=18):
    """The far plane: a soft row of residential blocks (lit windows at night / in the rain) with tree crowns between."""
    L, r = card.L, card.rnd
    base = base if base is not None else getattr(card, 'horizon', 262) + 4
    out, x, i = [], x0, r.randrange(4)
    while x < x1:
        w, h = r.uniform(96, 150), r.uniform(hmin, hmax)
        c, rf = L['blocks'][i % 4], L['roofs'][i % 4]
        out.append(f'<rect x="{n(x)}" y="{n(base - h)}" width="{n(w)}" height="{n(h)}" fill="{c}"/><rect x="{n(x - 5)}" y="{n(base - h - 7)}" width="{n(w + 10)}" height="9" fill="{rf}"/>')
        rows = int((h - 26) // 22)
        d = ''.join(f'M{n(x + 12)},{n(base - h + 22 + k * 22)}h{n(w - 24)}' for k in range(rows))
        if d:
            a, b = r.choice(((12, 10, 12, 24), (10, 9, 10, 22), (9, 12, 9, 20))), L['win']
            out.append(f'<path d="{d}" fill="none" stroke="{b[0]}" stroke-width="9" stroke-dasharray="{" ".join(map(str, a))}"/>')
            if rows > 1:
                d2 = ''.join(f'M{n(x + 12)},{n(base - h + 33 + k * 44)}h{n(w - 24)}' for k in range(rows // 2))
                out.append(f'<path d="{d2}" fill="none" stroke="{b[1]}" stroke-width="9" stroke-dasharray="{a[2]} {a[3]} {a[0]} {a[1]}"/>')
        if trees:
            out.append(f'<ellipse cx="{n(x + w + gap / 2)}" cy="{n(base - 22)}" rx="{n(r.uniform(18, 26))}" ry="{n(r.uniform(26, 36))}" fill="{L["green"][1]}"/>')
        x += w + r.uniform(gap, gap + 26)
        i += 1
    card.add(''.join(out), 'far')
    return card


def far_trees(card, base=None, x0=380, x1=820, h=150, count=None):
    """The far plane: a soft bank of tree crowns (a park, the edge of the 小区, a river bank)."""
    L, r = card.L, card.rnd
    base = base if base is not None else getattr(card, 'horizon', 262) + 6
    g = card.lin('fc', 0, L['green'][0], .6, L['green'][1], 1, L['green'][2], x1=0, y1=base - h, x2=0, y2=base, user=True)
    count = count or max(3, int((x1 - x0) / 62))
    out = [f'<g fill="{g}">']
    for k in range(count):
        cx = x0 + (x1 - x0) * (k + .5) / count + r.uniform(-14, 14)
        hh = h * r.uniform(.62, 1)
        out.append(f'<ellipse cx="{n(cx)}" cy="{n(base - hh * .5)}" rx="{n(r.uniform(44, 64))}" ry="{n(hh * .56)}"/>')
    out.append('</g>')
    card.add(''.join(out), 'far')
    return card


def hills(card, base=None, col=None):
    L = card.L
    base = base if base is not None else getattr(card, 'horizon', 262) + 6
    c = col or L['green'][2]
    card.add(f'<path d="M-10,{n(base)}C120,{n(base - 90)},260,{n(base - 96)},380,{n(base - 40)}C470,{n(base - 96)},640,{n(base - 120)},810,{n(base - 30)}V{n(base)}Z" fill="{c}"/>', 'far')
    return card


def _seams(card, y0, y1, col, vp=(400, None), rows=4, cols=9, op=.6):
    """Perspective seams of a paved / planked surface, left out where the word will stand (the calm zone)."""
    vx, vy = vp[0], vp[1] if vp[1] is not None else y0 - 150
    d = []
    for k in range(1, rows + 1):
        y = y0 + (y1 - y0) * (k / (rows + 1)) ** 1.6
        xs = [-10]
        z = card.calm
        if z and z[1] - 6 < y < z[3] + 6:
            xs += [z[0] - 14, z[2] + 14]
        xs.append(W + 10)
        for a, b in zip(xs[::2], xs[1::2]):
            if b - a > 30:
                d.append(f'M{n(a)},{n(y)}H{n(b)}')
    for k in range(cols):
        xb = -260 + (W + 520) * k / (cols - 1) + (17 if k % 2 else -9)
        t0 = (y0 - vy) / (H - vy)
        a = (vx + (xb - vx) * t0, y0)
        segs, cur = [], None
        for j in range(13):
            t = t0 + (1 - t0) * j / 12
            p = (vx + (xb - vx) * t, vy + (H - vy) * t)
            if in_calm(card, p[0], p[1], 12) or not -20 < p[0] < W + 20:
                if cur and len(cur) > 1:
                    segs.append(cur)
                cur = None
            else:
                cur = (cur or []) + [p]
        if cur and len(cur) > 1:
            segs.append(cur)
        for s in segs:
            d.append(f'M{P(s[0])}L{P(s[-1])}')
    return f'<path d="{"".join(d)}" fill="none" stroke="{col}" stroke-width="1.6" opacity="{n(op)}"/>'


def ground(card, y=None, kind='lawn', tilt=0, seams=True):
    """The ground from the line y (left end y + tilt, right end y − tilt) to the bottom. kind: lawn · path (paving) · plaza
    (pale tiles) · wet (rain-wet paving with a sheen) · water (lake, river) · sand · floor (indoor, see room()).
    Stack calls for bands: ground(250,'lawn') then ground(300,'path') = a lawn strip above a pavement."""
    L = card.L
    y = y if y is not None else getattr(card, 'horizon', 262)
    yl, yr = y + tilt, y - tilt
    out = []
    k = len([1 for x in card.defs if x.startswith('gd')])
    if kind == 'lawn':
        g = card.lin(f'gd{k}', 0, L['lawn'][0], 1, L['lawn'][1], x1=0, y1=y, x2=0, y2=H, user=True)
        out.append(f'<path d="M0,{n(yl)}L{W},{n(yr)}V{H}H0Z" fill="{g}"/><path d="M0,{n(yl + 1.5)}L{W},{n(yr + 1.5)}" fill="none" stroke="{L["lawn"][2]}" stroke-width="3" opacity=".7"/>')
    elif kind in ('path', 'plaza', 'wet', 'sand', 'floor'):
        pal = {'plaza': ('#FFF9EA', '#F6EBD2', '#ECDDBE', '#D9C7A2') if not L['dark'] and card.light != 'rain' else L['path'],
               'sand': ('#FFF3CF', '#F8E2A8', '#EFD08A', '#DDB870'), 'floor': L['floor'][:2] + L['floor'][1:]}.get(kind, L['path'])
        g = card.lin(f'gd{k}', 0, pal[0], .5, pal[1], 1, pal[2], x1=0, y1=y, x2=0, y2=H, user=True)
        out.append(f'<path d="M0,{n(yl)}L{W},{n(yr)}V{H}H0Z" fill="{g}"/><path d="M0,{n(yl + 1.5)}L{W},{n(yr + 1.5)}" fill="none" stroke="{pal[3]}" stroke-width="2" opacity=".6"/>')
        if seams and kind != 'sand':
            out.append(_seams(card, max(yl, yr) + 6, H, pal[3], rows=4 if kind != 'floor' else 0, op=.5 if kind != 'wet' else .4))
        if kind == 'wet':
            out.append(f'<ellipse cx="400" cy="{n((y + H) / 2 + 30)}" rx="420" ry="{n((H - y) * .34)}" fill="{card.glow("#FFFFFF")}" opacity=".5"/>')
    elif kind == 'water':
        c = {'night': ('#6C7ED0', '#4C5CB0', '#B9C6F8'), 'rain': ('#C6D4E6', '#A6BAD6', '#FFFFFF'), 'golden': ('#BFE3EE', '#8CC6E0', '#FFF6D8')}.get(card.light, ('#9ADAF6', '#58B4E8', '#FFFFFF'))
        g = card.lin(f'gd{k}', 0, c[0], 1, c[1], x1=0, y1=y, x2=0, y2=H, user=True)
        out.append(f'<path d="M0,{n(yl)}L{W},{n(yr)}V{H}H0Z" fill="{g}"/>')
        r, d = card.rnd, []
        for _ in range(16):
            x, yy = r.uniform(20, 780), r.uniform(y + 10, H - 10)
            if not in_calm(card, x, yy, 16):
                d.append(f'M{n(x)},{n(yy)}h{n(r.uniform(18, 46) * (.5 + (yy - y) / (H - y)))}')
        out.append(f'<path d="{"".join(d)}" fill="none" stroke="{c[2]}" stroke-width="2.4" stroke-linecap="round" opacity=".7"/>')
    else:
        raise SystemExit('ground kind must be lawn, path, plaza, wet, water, sand or floor')
    if card.calm and kind != 'water':
        z = card.calm
        if (z[1] + z[3]) / 2 > max(yl, yr):
            out.append(f'<ellipse cx="{n((z[0] + z[2]) / 2)}" cy="{n((z[1] + z[3]) / 2)}" rx="{n((z[2] - z[0]) * .62)}" ry="{n((z[3] - z[1]) * .62)}" fill="{card.glow("#FFF8DE" if not L["dark"] else "#B9C6F8")}" opacity="{".7" if not L["dark"] else ".35"}"/>')
    card.add(''.join(out), 'ground')
    card.ground_y = y
    _bloom(card)
    return card


def room(card, floor_y=336, floor='wood', wall=None, skirting=True, patch=True):
    """Indoors: the wall (bright, lit from the left) down to floor_y and the floor below it (wood planks · tile · rug · none).
    floor=None leaves the bottom to a table / counter / bed you draw across it."""
    L = card.L
    w = wall or L['wall']
    g = card.lin('wall', 0, w[0], .55, w[1], 1, w[2], x1=0, y1=0, x2=1, y2=0)
    out = [f'<rect width="{W}" height="{H}" fill="{g}"/>']
    if not L['dark']:
        out.append(f'<ellipse cx="250" cy="{n(floor_y * .45)}" rx="330" ry="{n(floor_y * .6)}" fill="{card.glow("#FFF8DE")}" opacity=".6"/>')
    card.add(''.join(out), 'back')
    card.horizon = card.ground_y = floor_y
    if floor:
        f = L['floor'] if floor == 'wood' else {'tile': ('#FBF6EA', '#EEE6D4', '#CFC4AC'), 'rug': ('#FFF4E0', '#F6E2C4', '#E4C9A2')}.get(floor, L['floor'])
        if L['dark'] and floor != 'wood':
            f = L['floor']
        g2 = card.lin('floor', 0, f[0], 1, f[1], x1=0, y1=floor_y, x2=0, y2=H, user=True)
        o = [f'<rect y="{n(floor_y)}" width="{W}" height="{n(H - floor_y)}" fill="{g2}"/>']
        if floor in ('wood', 'tile'):
            o.append(_seams(card, floor_y + 4, H, f[2], rows=0 if floor == 'wood' else 3, cols=11 if floor == 'wood' else 8, op=.5))
        if skirting:
            sk = '#FFFFFF' if not L['dark'] else '#B4BEEC'
            o.append(f'<rect y="{n(floor_y - 9)}" width="{W}" height="10" fill="{sk}" opacity=".85"/><path d="M0,{n(floor_y + 1)}H{W}" stroke="{f[2]}" stroke-width="2" opacity=".5"/>')
        if card.calm:
            z = card.calm
            o.append(f'<ellipse cx="{n((z[0] + z[2]) / 2)}" cy="{n((z[1] + z[3]) / 2)}" rx="{n((z[2] - z[0]) * .62)}" ry="{n((z[3] - z[1]) * .62)}" fill="{card.glow("#FFF8DE" if not L["dark"] else "#FFE2A8")}" opacity="{".6" if not L["dark"] else ".3"}"/>')
        card.add(''.join(o), 'ground')
    _bloom(card)
    return card


def window(card, x=40, y=40, w=250, h=210, view='trees', curtains=True, panes=(2, 2), shafts=True, patch=None, sill=True):
    """A window on the wall (x, y = its top-left). view: trees · town · sky · rain · night. In the 晨光窗 setup put it on the
    left with the sun inside it: the light shafts and the light patch on the floor / table come from it."""
    L, r = card.L, card.rnd
    k = len([1 for q in card.defs if q.startswith('wc')])
    cid = f'wc{k}'
    card.define(cid, f'<clipPath id="{cid}"><rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}"/></clipPath>')
    sk = card.lin(f'wsky{k}', *L['sky'])
    out = [f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" fill="{sk}"/>']
    far = []
    if view in ('trees', 'town'):
        base = y + h + 4
        if view == 'town':
            for i in range(3):
                bx, bh = x + w * (i * .34) + r.uniform(-6, 10), h * r.uniform(.34, .62)
                far.append(f'<rect x="{n(bx)}" y="{n(base - bh)}" width="{n(w * .28)}" height="{n(bh)}" fill="{L["blocks"][i]}"/><rect x="{n(bx - 3)}" y="{n(base - bh - 5)}" width="{n(w * .28 + 6)}" height="7" fill="{L["roofs"][i]}"/>')
                far.append(f'<path d="M{n(bx + 8)},{n(base - bh + 18)}h{n(w * .28 - 16)}M{n(bx + 8)},{n(base - bh + 38)}h{n(w * .28 - 16)}" fill="none" stroke="{L["win"][0]}" stroke-width="7" stroke-dasharray="9 8"/>')
        for i in range(4):
            far.append(f'<ellipse cx="{n(x + w * (i + .5) / 4 + r.uniform(-12, 12))}" cy="{n(base - h * .12)}" rx="{n(w * .2)}" ry="{n(h * r.uniform(.2, .34))}" fill="{L["green"][i % 2 + 1]}"/>')
    if far:
        out.append(f'<g clip-path="url(#{cid})"><g filter="{card.blur(3)}">' + ''.join(far) + '</g></g>')
    sx, sy = L['sun']
    inside = x < sx < x + w and y < sy < y + h
    if inside and L['sun_g']:
        card.rad('sun', *L['sun_g'], cx=sx, cy=sy, r=L['sun_r'], user=True)
        out.append(f'<g clip-path="url(#{cid})"><circle cx="{n(sx)}" cy="{n(sy)}" r="{n(L["sun_r"])}" fill="url(#sun)"/>'
                   f'<path d="M{n(sx)},{n(sy - 52)}V{n(sy + 52)}M{n(sx - 54)},{n(sy)}H{n(sx + 54)}M{n(sx - 38)},{n(sy - 38)}L{n(sx + 38)},{n(sy + 38)}M{n(sx + 38)},{n(sy - 38)}L{n(sx - 38)},{n(sy + 38)}" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" opacity=".4"/></g>')
    if view == 'night' or card.light == 'night':
        mx, my = x + w * .32, y + h * .3
        out.append(f'<g clip-path="url(#{cid})"><circle cx="{n(mx)}" cy="{n(my)}" r="{n(h * .34)}" fill="{card.glow("#DCE4FF")}" opacity=".6"/><path d="M{n(mx + 6)},{n(my - 22)}A23,23,0,1,0,{n(mx + 22)},{n(my + 10)}A18,18,0,1,1,{n(mx + 6)},{n(my - 22)}Z" fill="#FFF0B8"/>'
                   + ''.join(f'<circle cx="{n(x + w * a)}" cy="{n(y + h * b)}" r="1.5" fill="#FFFFFF"/>' for a, b in ((.62, .16), (.8, .34), (.5, .5), (.9, .12), (.7, .62), (.14, .7))) + '</g>')
    if view == 'rain' or card.light == 'rain':
        d = ''.join(f'M{n(x + r.uniform(6, w - 6))},{n(y + r.uniform(4, h - 30))}l-3,{n(r.uniform(12, 24))}' for _ in range(22))
        out.append(f'<path d="{d}" fill="none" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" opacity=".7"/>')
        out.append('<g fill="#FFFFFF" opacity=".8">' + ''.join(f'<ellipse cx="{n(x + r.uniform(10, w - 10))}" cy="{n(y + r.uniform(10, h - 10))}" rx="2" ry="3"/>' for _ in range(9)) + '</g>')
    fr = L['frame']
    px, py = panes
    bars = ''.join(f'M{n(x + w * i / px)},{n(y)}V{n(y + h)}' for i in range(1, px)) + ''.join(f'M{n(x)},{n(y + h * j / py)}H{n(x + w)}' for j in range(1, py))
    out.append(f'<path d="{bars}" fill="none" stroke="{fr[1]}" stroke-width="7"/><path d="{bars}" fill="none" stroke="{fr[0]}" stroke-width="2.4" opacity=".9"/>')
    out.append(f'<rect x="{n(x - 5)}" y="{n(y - 5)}" width="{n(w + 10)}" height="{n(h + 10)}" fill="none" stroke="{fr[1]}" stroke-width="10"/><path d="M{n(x - 9)},{n(y + h + 9)}V{n(y - 9)}H{n(x + w + 9)}" fill="none" stroke="{fr[0]}" stroke-width="3" opacity=".9"/>')
    if sill:
        out.append(f'<rect x="{n(x - 20)}" y="{n(y + h + 9)}" width="{n(w + 40)}" height="13" rx="3" fill="{fr[0]}"/><rect x="{n(x - 20)}" y="{n(y + h + 18)}" width="{n(w + 40)}" height="5" rx="2" fill="{fr[2]}" opacity=".7"/>')
    if curtains:
        cc = ('#FFF8E4', '#FBE8C4', '#F2A28C') if not L['dark'] else ('#C9CCF0', '#A9AEE0', '#F2A28C')
        cg = card.lin('curt', 0, cc[0], .5, cc[1], 1, cc[0], x1=0, y1=0, x2=1, y2=0)
        cw = w * .17
        for sd in (0, 1):
            cx0 = x - 16 if sd == 0 else x + w + 16 - cw
            mid = cx0 + cw / 2
            out.append(f'<path d="M{n(cx0)},{n(y - 14)}H{n(cx0 + cw)}C{n(cx0 + cw - 4)},{n(y + h * .3)},{n(mid + 8)},{n(y + h * .5)},{n(mid + 6)},{n(y + h * .56)}C{n(mid + 10)},{n(y + h * .7)},{n(cx0 + cw + 2)},{n(y + h * .9)},{n(cx0 + cw)},{n(y + h + 6)}H{n(cx0)}C{n(cx0 - 2)},{n(y + h * .9)},{n(mid - 10)},{n(y + h * .7)},{n(mid - 6)},{n(y + h * .56)}C{n(mid - 8)},{n(y + h * .5)},{n(cx0 + 4)},{n(y + h * .3)},{n(cx0)},{n(y - 14)}Z" fill="{cg}"/>'
                       f'<path d="M{n(mid - 7)},{n(y + h * .56)}H{n(mid + 7)}" stroke="{cc[2]}" stroke-width="7" stroke-linecap="round"/>'
                       f'<path d="M{n(cx0 + cw * .3)},{n(y - 8)}Q{n(cx0 + cw * .34)},{n(y + h * .3)},{n(mid - 2)},{n(y + h * .52)}M{n(cx0 + cw * .68)},{n(y - 8)}Q{n(cx0 + cw * .64)},{n(y + h * .3)},{n(mid + 2)},{n(y + h * .52)}" fill="none" stroke="{cc[1]}" stroke-width="2" opacity=".8"/>')
        out.append(f'<path d="M{n(x - 26)},{n(y - 15)}H{n(x + w + 26)}" stroke="#C9A27E" stroke-width="4" stroke-linecap="round"/>')
    card.add(''.join(out), 'back', name='window', box=(x - 20, y - 16, x + w + 20, y + h + 24), kind='soft')
    if inside and shafts and L['sun_g']:
        slope = .55
        gy = card.ground_y if getattr(card, 'ground_y', None) else 336
        card.lin('shaft', 0, ('#FFF4C4', 0), .2, ('#FFF4C4', .55), .6, ('#FFE6A6', .2), 1, ('#FFD890', 0), x1=x + w * .7, y1=y, x2=x + w + 460, y2=y + 460 * slope + 40, user=True)
        q = []
        for j in range(py):
            a, b = y + h * j / py + 8, y + h * (j + 1) / py - 8
            x_, run = x + w + 6, 480
            q.append(f'<path d="M{n(x_)},{n(a)}L{n(x_ + run)},{n(a + run * slope)}V{n(b + run * slope * 1.25)}L{n(x_)},{n(b)}Z" opacity="{".6" if j == 0 else "1"}"/>')
        card.add(f'<g filter="{card.blur(3)}" fill="url(#shaft)">' + ''.join(q) + '</g>', 'fx')
        if patch is None or patch:
            px0 = x + w + 40 if patch is None else patch[0]
            py0 = gy + 26 if patch is None else patch[1]
            card.layers['shadow'].append(f'<path d="M{n(px0)},{n(py0)}h{n(w * .5)}l{n(120)},{n(74)}h{n(-w * .62)}Z" fill="#FFF3C4" opacity=".55"/>')
    return card


def lamp(card, x, y, kind='ceiling', glow=150, on=True, col='#FFB65C'):
    """A warm lamp: ceiling (hangs to (x, y)) · desk / floor (stands on (x, y)) · wall (a small night light at (x, y)).
    At night and in the rain it is the warm accent and the pool of light the action sits in."""
    out = []
    lit = '#FFF6D0' if on else '#E8E2D4'
    if kind == 'ceiling':
        out.append(f'<path d="M{n(x)},0V{n(y - 26)}" stroke="#B9987A" stroke-width="2.4"/><path d="M{n(x - 34)},{n(y)}C{n(x - 32)},{n(y - 30)},{n(x + 32)},{n(y - 30)},{n(x + 34)},{n(y)}Z" fill="{col}"/>'
                   f'<path d="M{n(x - 31)},{n(y - 6)}C{n(x - 26)},{n(y - 24)},{n(x - 6)},{n(y - 27)},{n(x + 2)},{n(y - 26)}" fill="none" stroke="#FFE2A0" stroke-width="3" stroke-linecap="round"/><ellipse cx="{n(x)}" cy="{n(y + 1)}" rx="30" ry="6" fill="{lit}"/>')
        gc = (x, y + glow * .5)
    elif kind in ('desk', 'floor'):
        hgt = 86 if kind == 'desk' else 230
        out.append(f'<ellipse cx="{n(x)}" cy="{n(y - 4)}" rx="24" ry="6" fill="#8A7FB8"/><path d="M{n(x)},{n(y - 6)}V{n(y - hgt + 30)}" stroke="#A59CCB" stroke-width="5" stroke-linecap="round"/>'
                   f'<path d="M{n(x - 30)},{n(y - hgt + 34)}L{n(x - 17)},{n(y - hgt)}H{n(x + 17)}L{n(x + 30)},{n(y - hgt + 34)}Z" fill="{col}"/><path d="M{n(x - 26)},{n(y - hgt + 30)}L{n(x - 15)},{n(y - hgt + 3)}" stroke="#FFE2A0" stroke-width="3" stroke-linecap="round"/>'
                   f'<ellipse cx="{n(x)}" cy="{n(y - hgt + 35)}" rx="29" ry="5" fill="{lit}"/>')
        gc = (x, y - hgt + 60)
    else:
        out.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="13" fill="{lit}"/><circle cx="{n(x)}" cy="{n(y)}" r="13" fill="none" stroke="{col}" stroke-width="3"/>')
        gc = (x, y)
    if on:
        card.add(f'<ellipse cx="{n(gc[0])}" cy="{n(gc[1])}" rx="{n(glow * 1.25)}" ry="{n(glow)}" fill="{card.glow("#FFE2A8")}" opacity="{".8" if card.L["dark"] else ".55"}"/>', 'ground')
    card.add(''.join(out), 'mid', name='lamp', box=(x - 34, min(y - 30, gc[1] - 40), x + 34, y + 8), kind='soft')
    return card


def rain(card, count=64, slant=-3, ripples=5):
    """Rain streaks over the scene (never across a face or the word) and a few ring ripples on the ground."""
    r = card.rnd
    d = []
    boxes = [f.face_box for f in card.figures]
    for _ in range(count * 3):
        if len(d) >= count:
            break
        x, y, ln = r.uniform(0, W), r.uniform(-10, H - 60), r.uniform(12, 26)
        if in_calm(card, x, y + ln / 2, 4) or any(b[0] - 6 < x < b[2] + 6 and b[1] - 26 < y < b[3] + 4 for b in boxes):
            continue
        d.append(f'M{n(x)},{n(y)}l{n(slant * ln / 14)},{n(ln)}')
    out = [f'<path d="{"".join(d)}" fill="none" stroke="#FFFFFF" stroke-width="1.8" stroke-linecap="round" opacity=".7"/>']
    gy = getattr(card, 'ground_y', 300)
    rp = []
    for _ in range(ripples * 4):
        if len(rp) >= ripples:
            break
        x, y = r.uniform(30, W - 30), r.uniform(gy + 24, H - 14)
        if in_calm(card, x, y, 22) or any(i['box'][0] - 20 < x < i['box'][2] + 20 and i['box'][1] < y < i['box'][3] + 8 for i in card.items):
            continue
        s = .6 + (y - gy) / (H - gy) * .7
        rp.append(f'<ellipse cx="{n(x)}" cy="{n(y)}" rx="{n(15 * s)}" ry="{n(4 * s)}"/><ellipse cx="{n(x)}" cy="{n(y)}" rx="{n(7 * s)}" ry="{n(2 * s)}"/><path d="M{n(x - 5 * s)},{n(y - 5 * s)}l{n(-3 * s)},{n(-5 * s)}M{n(x)},{n(y - 6 * s)}v{n(-6 * s)}M{n(x + 5 * s)},{n(y - 5 * s)}l{n(3 * s)},{n(-5 * s)}"/>')
    out.append('<g fill="none" stroke="#FFFFFF" stroke-width="1.5" stroke-linecap="round" opacity=".8">' + ''.join(rp) + '</g>')
    card.add(''.join(out), 'fx')
    return card


def motes(card, count=18, box=(300, 60, 760, 300)):
    """Dust motes / pollen in the light (inside `box`, never on a face or the word)."""
    r, out = card.rnd, []
    boxes = [f.box for f in card.figures]
    for _ in range(count * 3):
        if len(out) >= count:
            break
        x, y = r.uniform(box[0], box[2]), r.uniform(box[1], box[3])
        if in_calm(card, x, y, 6) or any(b[0] - 6 < x < b[2] + 6 and b[1] - 6 < y < b[3] + 6 for b in boxes):
            continue
        out.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r.uniform(1, 2.4))}"/>')
    card.add('<g fill="#FFF8DC" opacity=".8">' + ''.join(out) + '</g>', 'fx')
    return card
