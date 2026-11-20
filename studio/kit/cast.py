"""kit.cast — the cast as poseable figures.

The faces, hair, torsos and standing lower bodies are the approved fragments of `studio/cast/CAST.md` and
`studio/cast/family/CAST-family.md`, read from those files by line (never retyped); arms and re-posed legs are built
by the rules of CAST.md §7 / CAST-family.md §9 (one polyline per limb, lit / shade colour pairs, cuff, rim line,
mitten hand). A figure is placed by where it stands or sits, told where to look and where its hands are.
"""
from __future__ import annotations

import math
import re

from .base import ST, P, box_of, dist, hang, ik2, lerp, n, rot, unit

_CT = (ST / 'cast/CAST.md').read_text()
_FT = (ST / 'cast/family/CAST-family.md').read_text()
_CL, _FL = _CT.split('\n'), _FT.split('\n')
_strip = lambda s: re.sub(r'<!--.*?-->', '', s)
C = lambda i: _strip(_CL[i - 1])
F = lambda i: _strip(_FL[i - 1])
assert _CL[45].startswith('<path d="M-56,6C-60,-40') and _CL[96].startswith('<ellipse cx="-45" cy="13"'), 'CAST.md changed'
assert _FL[40].startswith('<ellipse cx="-43.5"') and _FL[177].startswith('<path d="M-13,372L-14,399"'), 'CAST-family.md changed'

_EL = re.compile(r'<(?:path|rect|ellipse|circle)\b[^>]*/>')
_QG = '<g transform="translate(-14 0) scale(.9 1)">'


def _els(line):
    return _EL.findall(line)


def _unq(line):
    """A line of a 3/4 head's features group without the group's opening / closing tag."""
    if line.startswith(_QG):
        line = line[len(_QG):]
    return line[:-4] if line.endswith('</g>') and line.count('<g') < line.count('</g>') else line


def cast_grad(gid: str) -> str:
    """The cast gradient `gid` from the two cast files; `c-X-m` is the twin (x1 and x2 exchanged) for a turned head."""
    base = gid[:-2] if gid.endswith('-m') else gid
    m = None
    for t in (_CT, _FT):
        m = re.search(r'<(linear|radial)Gradient id="%s"[^>]*>(?:<stop[^>]*/>)+</\1Gradient>' % re.escape(base), t)
        if m:
            break
    if not m:
        raise SystemExit(f'unknown cast gradient {gid}')
    x = m.group(0)
    if gid != base:
        x = x.replace(f'id="{base}"', f'id="{gid}"').replace('x1="0"', 'x1="1"', 1).replace('x2="1"', 'x2="0"', 1)
    return x


HAND = ('<path d="M-8,-2C-10.5,6,-10,15,-6,20.5C-2,25,5.5,24.5,8.5,19C11,14,10,6,8,-2ZM7,3C13,0,17.5,5,15.5,10.5C14,14,9.5,14,8,10.5Z" fill="%s" stroke="#E2A283" stroke-width=".9" stroke-linejoin="round"/>'
        '<path d="M-4,14.5q1.6,4.5,.2,8.5M1.6,15q1.4,4.5,.4,8.8" fill="none" stroke="#E2A283" stroke-width="1.2" stroke-linecap="round"/>')
_THUMB = 'ZM7,3C13,0,17.5,5,15.5,10.5C14,14,9.5,14,8,10.5Z'
assert HAND.split('%s')[0][9:60] in _CT
POINT = ('<path d="M1,9C.8,16,.8,22,1.4,27.5C2,31.6,7.8,31.6,8.2,27.5C8.6,22,8.6,16,8.4,9Z" fill="%s" stroke="#E2A283" stroke-width=".9" stroke-linejoin="round"/>'
         '<path d="M-8,-2C-10.5,5,-10.5,12,-7.4,16.5C-3.4,20.5,5.4,20.3,8.8,16C11.2,12,10,5,8,-2ZM7,3C13,0,17.5,5,15.5,10.5C14,14,9.5,14,8,10.5Z" fill="%s" stroke="#E2A283" stroke-width=".9" stroke-linejoin="round"/>'
         '<path d="M-4.6,12.4q1.5,3.6,.3,6.8M-.4,12.6q1.4,3.3,.5,6.1" fill="none" stroke="#E2A283" stroke-width="1.2" stroke-linecap="round"/>')
SHOE_F = ('<path d="M-11.5,4C-12.5,-4,-7,-8,0,-8C7,-8,12.5,-4,11.5,4L12.5,10Q12.5,14,8,14L-8,14Q-12.5,14,-12.5,10Z" fill="%s"/>'
          '<path d="M-12.4,10.5Q0,13,12.4,10.5" fill="none" stroke="%s" stroke-width="2.4" stroke-linecap="round"/><path d="M-8,-2Q-4,-5.5,1,-5.5" fill="none" stroke="%s" stroke-width="2.2" stroke-linecap="round"/>')
SHOE_S = ('<path d="M7.5,-8C9.5,2,8.5,10,5,12L-18,12C-23.5,12,-24,5.5,-18.5,3C-12.5,.5,-8.5,-3,-6.5,-8Z" fill="%s"/>'
          '<path d="M-21,10.5L6,10.5" fill="none" stroke="%s" stroke-width="2.6" stroke-linecap="round"/><path d="M-15,4.5Q-11,2,-8,-1" fill="none" stroke="%s" stroke-width="2.2" stroke-linecap="round"/>')
SKIN = ('#FBD0AC', '#F0B894')
HANDS = ('#FBCFAA', '#F3BE9C')


def _shoes(line):
    """(lit, shade) colour triples of the two shoes in a 'shoes' line of the cast files."""
    f = re.findall(r'Z" fill="(#[0-9A-F]{6})"/><path d="M-12\.4,10\.5Q0,13,12\.4,10\.5" fill="none" stroke="(#[0-9A-F]{6})"[^>]*/><path d="M-8,-2Q-4,-5\.5,1,-5\.5" fill="none" stroke="(#[0-9A-F]{6})"', line)
    assert len(f) == 2, line[:80]
    return f[0], f[1]


def _split_neck(line):
    e = _els(line)
    return e[0], ''.join(e[1:])


_kid_brows = lambda line: (_els(line)[0], line[len(_els(line)[0]):])
_tops = _els(F(221))
_d_neck, _d_skirt = _split_neck(C(73))
_l_neck, _l_shorts = _split_neck(C(108))
_d_brows, _d_mouth = _kid_brows(C(49))
_l_brows, _l_mouth = _kid_brows(C(100))
_KID_LAUGH, _KID_SHUT = C(57), C(56)
_AD_LAUGH, _AD_SHUT = _els(F(33)), _els(F(34))
_NN_SMILE = re.search(r'Smiling eyes instead of the eyes line: `(<path[^`]*/>)`', _CT).group(1)
_OPEN = '<ellipse cx="0" cy="33.5" rx="5.6" ry="7.2" fill="#B23A3C"/><ellipse cx="0" cy="37" rx="3.4" ry="3" fill="#F58E86"/>'
_CALM = '<path d="M-6.5,31Q0,35.5,6.5,31" fill="none" stroke="#C2473F" stroke-width="2.4" stroke-linecap="round"/>'

# features: [kind, xml] in drawing order — kinds: base (blush, lines, glasses, brows of adults), eyes, brows, mouth
_d_feat = [['base', C(47)], ['eyes', C(48)], ['brows', _d_brows], ['mouth', _d_mouth]]
_l_feat = [['base', C(98)], ['eyes', C(99)], ['brows', _l_brows], ['mouth', _l_mouth]]

SPEC = {
    'duoduo': dict(zh='朵朵', R=56, G=272, kid=True, sh=(28, 77), hip=(13, 172), arm=(33, 30), leg=(38, 40), aw=20, lw=18, hs=1.0,
                   hangE=(44, 106), hangW=(41, 135), waist=(31, 134),
                   front=dict(pre=C(46), feat=_d_feat, post=C(50), sun=C(51), clip=C(52)),
                   q=dict(pre=C(62), feat=_d_feat, post=C(64), sun=C(65), clip=C(66)),
                   torso=_d_neck + C(74), st_legs=C(71), st_shoes=C(72), st_bottom=_d_skirt,
                   sleeve=('#FFD750', '#EFA43A'), cuff=('#F7B93A', '#D98A2A'), rim='#FFF7C8', sep=('#E39232', '#C97A22'),
                   limb=SKIN, sock=('#FFFDF6', '#F1ECE6'), shoe=(('#E8503A', '#B8362A', '#FF9C86'), ('#D9442F', '#A82E24', '#F58A72')), ss=1.0,
                   bottom=('#8497D8', '#6073BC'), bgrad='c-denim', cover=(.8, 10), bag=('#FF9C8E', '#E87A72', '#FFE2A0')),
    'lele': dict(zh='乐乐', R=54, G=272, kid=True, sh=(29, 78), hip=(15, 174), arm=(33, 30), leg=(37, 37), aw=17, lw=18, hs=1.0,
                 hangE=(45, 108), hangW=(42, 137), waist=(32, 140),
                 front=dict(pre=C(97), feat=_l_feat, post=C(101), sun=C(102)),
                 torso=_l_neck + C(109), st_legs=C(106), st_shoes=C(107), st_bottom=_l_shorts,
                 bare=SKIN, sleeve=('#8FD0F6', '#4C96D8'), short=(.62, 22), rim='#E6F6FF', sep=('#4C96D8', '#3F88CE'),
                 limb=SKIN, sock=('#FFFDF6', '#F1ECE6'), shoe=(('#4753A8', '#F4F1EA', '#8E9AE0'), ('#3A4590', '#E4DFD8', '#7884CC')), ss=1.0,
                 bottom=('#4C58B0', '#343E8C'), bgrad='c-indigo', cover=(.6, 7), bag=('#8FD18A', '#62A868', '#FFF3B8')),
    'nainai': dict(zh='奶奶', R=52, G=392, sh=(40, 93), hip=(18, 216), arm=(51, 42), leg=(84, 80), aw=22, lw=28, hs=1.1,
                   hangE=(52, 143), hangW=(47, 184), waist=(33, 198),
                   front=dict(pre=C(120) + C(121), feat=[['base', C(122)], ['eyes', _NN_SMILE], ['mouth', C(124)]], post=C(125), sun=C(126)),
                   q=dict(pre=C(131) + C(132), feat=[['base', _unq(C(133))], ['eyes', C(134)], ['mouth', _unq(C(135))]], post=C(136), sun=C(137)),
                   torso=C(143) + '<path d="M-50,195L-51,226Q0,232,51,226L50,195Z" fill="url(#c-peri)"/>' + C(144) + C(145),
                   torso_low='<path d="M-32,195L-37,300Q0,307,37,300L32,195Z" fill="url(#c-indigo)"/><path d="M-12,214h.1M14,236h.1M-6,262h.1M19,280h.1M-20,286h.1" fill="none" stroke="#FFFFFF" stroke-width="5" stroke-linecap="round" opacity=".9"/>',
                   sleeve=('#DCE1FA', '#B0B8E6'), cuff=('#BFC7EE', '#8E97D0'), rim='#FFFFFF', sep=('#8E97D0', '#7F88C6'),
                   limb=('#8E97D0', '#7882BE'), hem=('#7A84C2', '#6670AE'), shoe=(('#4652AC', '#2B337A', '#7C86D2'), ('#3C479C', '#252C6A', '#6670BE')), ss=1.1,
                   bottom=('#8E97D0', '#7882BE'), bgrad=None, cover=None),
    'baba': dict(zh='爸爸', R=50, G=436, sh=(48, 96), hip=(21, 226), arm=(57, 53), leg=(96, 88), aw=21, lw=30, hs=1.2,
                 hangE=(59, 152), hangW=(55, 205), waist=(42, 206),
                 front=dict(pre=F(41), feat=[['base', F(42)], ['eyes', F(43)], ['mouth', F(44)]], post=F(45), sun=F(46)),
                 q=dict(pre=F(50), feat=[['base', _unq(F(51))], ['eyes', F(52)], ['mouth', _unq(F(53))]], post=F(54), sun=F(55)),
                 torso=F(61) + F(62), st_legs=F(59), st_shoes=F(60), st_bottom='', top=_tops[0] + _tops[1],
                 bare=SKIN, sleeve=('#8FD6CB', '#4FA29C'), short=(.48, 26), band=('#74C4B9', '#3F8F8C'), rim='#F2FFFB', sep=('#3F8F8C', '#3F8F8C'),
                 limb=('#7C87AE', '#5D678D'), hem=('#66709A', '#4C5578'), shoe=_shoes(F(60)), ss=1.2, bottom=('#7C87AE', '#5D678D'), bgrad=None, cover=None),
    'mama': dict(zh='妈妈', R=50, G=422, sh=(38, 91), hip=(17, 222), arm=(53, 48), leg=(90, 86), aw=21, lw=25.5, hs=1.1,
                 hangE=(47, 143), hangW=(43, 191), waist=(34, 202),
                 front=dict(pre=F(80) + F(81), feat=[['base', F(82)], ['eyes', F(83)], ['mouth', F(84)]], post=F(85), sun=F(86)),
                 q=dict(pre=F(90) + F(91), feat=[['base', _unq(F(92))], ['eyes', F(93)], ['mouth', _unq(F(94))]], post=F(95), sun=F(96)),
                 torso=F(102) + F(103), st_legs=F(100), st_shoes=F(101), st_bottom='', top=_tops[2] + _tops[3],
                 sleeve=('#FFAB9A', '#E87D72'), cuff=('#F79283', '#D4655F'), rim='#FFEDE4', sep=('#B9504E', '#B9504E'),
                 limb=('#8497D8', '#6073BC'), hem=('#6B7FC6', '#4D5EA6'), shoe=_shoes(F(101)), ss=1.1, bottom=('#8497D8', '#6073BC'), bgrad=None, cover=None),
    'yeye': dict(zh='爷爷', R=51, G=416, sh=(44, 94), hip=(21.5, 230), arm=(55, 50), leg=(84, 76), aw=24, lw=31, hs=1.2,
                 hangE=(56, 148), hangW=(53, 198), waist=(43, 210),
                 front=dict(pre=F(122), feat=[['base', F(123)], ['base', F(124)], ['eyes', F(125)], ['mouth', F(126)]], post=F(127), sun=F(128)),
                 q=dict(pre=F(133), feat=[['base', _unq(F(134))], ['base', F(135)], ['eyes', F(136)], ['mouth', _unq(F(137))]], post=F(138), sun=F(139)),
                 torso=F(146) + F(147), st_legs=F(144), st_shoes=F(145), st_bottom='', top=_tops[4] + _tops[5],
                 sleeve=('#B7CD88', '#819C5A'), cuff=('#97B06C', '#66814A'), rim='#F4F9DE', sep=('#56703A', '#56703A'),
                 limb=('#AEA29D', '#8C807C'), hem=('#978B87', '#786D6A'), shoe=_shoes(F(145)), ss=1.2, bottom=('#AEA29D', '#8C807C'), bgrad=None, cover=None),
    'laoshi': dict(zh='李老师', R=49, G=420, sh=(35, 89), hip=(13, 240), arm=(52, 47), leg=(78, 81), aw=20, lw=15, hs=1.1,
                   hangE=(44, 140), hangW=(40, 187), waist=(31, 172),
                   front=dict(pre=F(158), feat=[['base', F(159)], ['eyes', F(160)], ['mouth', F(161)]], post=F(162), sun=F(163)),
                   q=dict(pre=F(167), feat=[['base', _unq(F(168))], ['eyes', F(169)], ['mouth', _unq(F(170))]], post=F(171), sun=F(172)),
                   torso=F(181), st_legs=F(178), st_shoes=F(179), st_bottom=F(180),
                   sleeve=('#FDFEFF', '#DDE3F3'), cuff=('#E9EDF9', '#C5CDE5'), rim=None, sep=('#9AA6CC', '#9AA6CC'),
                   limb=SKIN, shoe=_shoes(F(179)), ss=1.1, bottom=('#A5CCEE', '#7BA8D8'), bgrad='c-powder', cover=(1.0, 21), long=.6),
}
NAMES = {v['zh']: k for k, v in SPEC.items()}
POSES = ('stand', 'bend', 'walk', 'run', 'sit', 'sit_front', 'kneel', 'sit_heels', 'crouch', 'sit_floor', 'cross', 'prone')
EXPR = ('smile', 'laugh', 'shut', 'open', 'calm')


def _features(sp, view, expr):
    kid = sp.get('kid')
    out = []
    for kind, xml in sp[view]['feat']:
        if expr == 'smile' or kind == 'base':
            out.append(xml)
        elif kid and expr in ('laugh', 'shut'):
            if kind == 'eyes':
                out.append(_KID_LAUGH if expr == 'laugh' else _KID_SHUT)      # the kids' lines carry eyes + brows + mouth
        elif kind == 'eyes':
            out.append(xml if expr in ('open', 'calm') else (_NN_SMILE if sp['zh'] == '奶奶' and expr == 'laugh' else (_AD_LAUGH if expr == 'laugh' else _AD_SHUT)[0]))
        elif kind == 'brows':
            out.append(xml)
        elif kind == 'mouth':
            if expr in ('open', 'calm'):
                out.append(_OPEN if expr == 'open' else _CALM)
            elif sp['zh'] in ('奶奶', '爷爷'):
                out.append(xml)                                              # their own mouth under the laughing / closed eyes
            else:
                out.append(''.join((_AD_LAUGH if expr == 'laugh' else _AD_SHUT)[1:]))
    return ''.join(out)


def _twin(x):
    for g in ('c-skin', 'c-hair', 'c-black', 'c-silver'):
        x = x.replace(f'url(#{g})', f'url(#{g}-m)')
    return x


def head_xml(sp, view='front', expr='smile', fwd=0.0, down=0.0, flip=False, clip_alt=False):
    """A head in local coordinates (centre 0,0). view 'q' = three-quarter looking picture-left; flip = looking
    picture-right while the light stays left. fwd / down shift the features (the gaze)."""
    h = sp[view]
    feat = _features(sp, view, expr)
    clip = h.get('clip', '')
    if view == 'front':
        if clip and clip_alt:
            clip = clip.replace('translate(31 -17) rotate(18)', 'translate(-31 -17) rotate(-18)')
        blush = ''
        if sp.get('kid') and feat.startswith(h['feat'][0][1]):
            blush, feat = h['feat'][0][1], feat[len(h['feat'][0][1]):]
        return h['pre'] + blush + f'<g transform="translate({n(fwd)} {n(down)})">{feat}</g>' + h['post'] + h['sun'] + clip
    if not flip:
        if clip and clip_alt:
            clip = clip.replace('translate(19 -18) rotate(16)', 'translate(-24 -16) rotate(-16)')
        return h['pre'] + f'<g transform="translate({n(-14 - fwd)} {n(down)}) scale(.9 1)">{feat}</g>' + h['post'] + h['sun'] + clip
    if clip and not clip_alt:
        clip = clip.replace('translate(19 -18) rotate(16)', 'translate(-24 -16) rotate(-16)')
    return ('<g transform="scale(-1 1)">' + _twin(h['pre']) + f'<g transform="translate({n(-14 - fwd)} {n(down)}) scale(-.9 1)">{feat}</g>'
            + _twin(h['post']) + '<g transform="translate(8 0) scale(-1 1)">' + h['sun'] + '</g>' + clip + '</g>')


class Figure:
    """Built by `Card.figure(...)`; afterwards read `.head`, `.hands['l'|'r']`, `.mouth`, `.eyes`, `.top`, `.box`, `.feet_y`
    (canvas coordinates) to hang props, sound arcs or the hook on the figure."""

    def describe(self):
        h = self.hands
        hd = ' · '.join(f'{k} hand ({n(v[0])},{n(v[1])})' for k, v in h.items())
        return (f'{self.name} {self.pose} face={self.face} look→({n(self.look[0])},{n(self.look[1])}) {self.view}{" tilt " + n(self.tilt) if self.tilt else ""}: '
                f'head ({n(self.head[0])},{n(self.head[1])}) r={n(self.r)} top y={n(self.top)} · {hd} · box {tuple(round(v) for v in self.box)}')


def _arm_xml(sp, side, S, E, W, lit, hand, hs, torso_x):
    """One arm (CAST §7): sleeve polyline, cuff, separation line or rim, hand. side −1 = picture-left arm."""
    k = 0 if lit else 1
    w = sp['aw']
    out = []
    line = f'M{P(S)}L{P(E)}L{P(W)}'
    if 'bare' in sp:
        out.append(f'<path d="{line}" fill="none" stroke="{sp["bare"][k]}" stroke-width="{n(w)}" stroke-linecap="round" stroke-linejoin="round"/>')
        f, sw = sp['short']
        q = lerp(S, E, f)
        out.append(f'<path d="M{P(S)}L{P(q)}" fill="none" stroke="{sp["sleeve"][k]}" stroke-width="{n(sw)}" stroke-linecap="round"/>')
        if 'band' in sp:
            u = unit(S, E)
            b0 = (q[0] + u[0] * 7, q[1] + u[1] * 7)
            b1 = (q[0] + u[0] * 13, q[1] + u[1] * 13)
            out.append(f'<path d="M{P(b0)}L{P(b1)}" fill="none" stroke="{sp["band"][k]}" stroke-width="{n(sw + .5)}"/>')
        rim_w = sw
    else:
        out.append(f'<path d="{line}" fill="none" stroke="{sp["sleeve"][k]}" stroke-width="{n(w)}" stroke-linecap="round" stroke-linejoin="round"/>')
        u = unit(E, W)
        c0 = (W[0] - u[0] * 5.5, W[1] - u[1] * 5.5)
        out.append(f'<path d="M{P(c0)}L{P(W)}" fill="none" stroke="{sp["cuff"][k]}" stroke-width="{n(w + .5)}"/>')
        rim_w = w
    u = unit(S, E)
    nx, ny = u[1], -u[0]                                   # normal of the upper arm
    if abs(E[0]) < torso_x + 16 and E[1] > S[1] + 8:           # the arm lies against the torso
        o = (rim_w / 2 - 1.2) * (1 if (nx * -side) > 0 else -1)                    # on the body side
        a, b = lerp(S, E, .3), lerp(S, E, .95)
        out.append(f'<path d="M{P((a[0] + nx * o, a[1] + ny * o))}L{P((b[0] + nx * o, b[1] + ny * o))}" fill="none" stroke="{sp["sep"][k]}" stroke-width="1.6" stroke-linecap="round" opacity=".5"/>')
    if lit and sp.get('rim'):
        o = rim_w / 2 - 1.4
        sg = 1 if (nx * -1 + ny * -1) > 0 else -1                                  # the upper-left side of the bone
        a, b = lerp(S, E, .02), lerp(S, E, .85)
        out.append(f'<path d="M{P((a[0] + nx * o * sg, a[1] + ny * o * sg))}L{P((b[0] + nx * o * sg, b[1] + ny * o * sg))}" fill="none" stroke="{sp["rim"]}" stroke-width="2.6" stroke-linecap="round"/>')
    sc = f' scale({n(-hs)} {n(hs)})' if side > 0 else (f' scale({n(hs)})' if hs != 1 else '')
    if hand != 'none':
        g = (POINT % (HANDS[k], HANDS[k])) if hand == 'point' else (HAND % HANDS[k])
        if hand == 'hold':
            g = g.replace(_THUMB, 'Z')
        out.append(f'<g transform="translate({n(W[0])} {n(W[1])}) rotate({n(hang(E, W))}){sc}">{g}</g>')
    return ''.join(out)


def _solve_arm(S, T, l1, l2, hs, elbow, side, notes, who, quiet=False):
    """Elbow and wrist for a palm at T. Lengthens the arm up to 20 % (LESSONS #3), then clamps and reports."""
    palm = 11.5 * hs
    reach = (l1 + l2) * 1.2 + palm
    d0 = dist(S, T)
    if d0 > reach:
        if not quiet:
            notes.append(f'REACH: {who} cannot reach its target, short by {round(d0 - reach)} px (arm already 20 % longer) — move the target, the figure or lean it')
        u = unit(S, T)
        T = (S[0] + u[0] * reach * (.8 if quiet else .995), S[1] + u[1] * reach * (.8 if quiet else .995))
    Wp, E = T, S
    for _ in range(4):
        d = dist(S, Wp)
        k = max(1.0, min(1.2, d / (l1 + l2) * 1.002))
        L1, L2 = l1 * k, l2 * k
        if d > L1 + L2:
            u = unit(S, Wp)
            Wp = (S[0] + u[0] * (L1 + L2) * .999, S[1] + u[1] * (L1 + L2) * .999)
        elif d < abs(L1 - L2) + 2:
            u = unit(S, Wp) if d > .1 else (0, 1)
            Wp = (S[0] + u[0] * (abs(L1 - L2) + 2), S[1] + u[1] * (abs(L1 - L2) + 2))
        a, b = ik2(S, Wp, L1, L2)
        if elbow == 'down':
            E = a if a[1] > b[1] else b
        elif elbow == 'up':
            E = a if a[1] < b[1] else b
        elif elbow == 'out':
            E = a if a[0] * side > b[0] * side else b
        else:
            E = a if a[0] * side < b[0] * side else b
        u = unit(E, Wp)
        Wn = (T[0] - u[0] * palm, T[1] - u[1] * palm)
        if dist(Wn, Wp) < .3:
            break
        Wp = Wn
    return E, Wp


def _legs(pose, d, sp):
    """Hip, knee, ankle and shoe of both legs for a pose, in local coordinates. d = −1 facing picture-left."""
    hx, hy = sp['hip']
    T, N = sp['leg']
    lw, ss = sp['lw'], sp['ss']
    f = (T + N) / 78.0
    H = {s: (s * hx * .7, hy) for s in (-1, 1)}
    near = d                                        # the leg on the side the figure faces is drawn last
    legs, G, lean, over = {}, 0.0, 0.0, False

    def bend(h, a, fwd):
        a_, b_ = ik2(h, a, T, N) if dist(h, a) < T + N else (lerp(h, a, T / (T + N)),) * 2
        return a_ if a_[0] * fwd > b_[0] * fwd else b_

    if pose == 'walk':
        for s in (-1, 1):
            lead = s == d
            a = (H[s][0] + d * 20 * f, hy + T + N - 5) if lead else (H[s][0] - d * 20 * f, hy + T + N - 9)
            k = bend(H[s], a, d)
            legs[s] = (H[s], k, a, 'side', hang(k, a) + (0 if lead else -d * 14))
        G = hy + T + N - 5 + 12 * ss
    elif pose == 'run':
        for s in (-1, 1):
            if s == d:
                k, a = (H[s][0] + d * 30 * f, hy + 24 * f), (H[s][0] + d * 46 * f, hy + 64 * f)
                legs[s] = (H[s], k, a, 'side', hang(k, a) - d * 20)
            else:
                k, a = (H[s][0] - d * 27 * f, hy + 28 * f), (H[s][0] - d * 62 * f, hy + 15 * f)
                legs[s] = (H[s], k, a, 'side', hang(k, a))
        G, lean = hy + 64 * f + 12 * ss + 14, d * 12
    elif pose == 'sit':
        for s in (-1, 1):
            far = s != near
            k = (H[s][0] + d * T, hy + (0 if far else 3))
            a = (k[0] + d * (2 if not far else -5), k[1] + N)
            legs[s] = (H[s], k, a, 'side', 0 if d < 0 else 0)
        G = hy + lw / 2 + 1.5
    elif pose == 'sit_front':
        for s in (-1, 1):
            k = (s * (hx + 15), hy + 15)
            a = (s * (hx + 12), hy + 15 + N * .95)
            legs[s] = ((s * (hx + 12), hy + 8), k, a, 'front', -s * 8)
        G = hy + 13
    elif pose == 'kneel':
        for s in (-1, 1):
            k = (H[s][0] + d * 6, hy + T - 2)
            a = (k[0] - d * N * .95, k[1] - 3)
            legs[s] = (H[s], k, a, 'side', hang(k, a))
        G = hy + T - 2 + lw / 2
    elif pose == 'sit_heels':
        for s in (-1, 1):
            k = (H[s][0] + d * (T - 6), hy + 16)
            a = (H[s][0] - d * 6, hy + 21)
            legs[s] = (H[s], k, a, 'side', hang(k, a))
        G = hy + 16 + lw / 2 + 1
    elif pose == 'crouch':
        for s in (-1, 1):
            a = (H[s][0] + d * 8 + (0 if s == near else -d * 12), hy + 36 * f)
            k = bend(H[s], a, d)
            legs[s] = (H[s], k, a, 'side', 0)
        G = hy + 36 * f + 12 * ss
    elif pose == 'sit_floor':
        for s in (-1, 1):
            far = s != near
            k = (H[s][0] + d * T * .93, hy - (12 if not far else 18))
            a = (k[0] + d * N * .93, hy + (0 if not far else -5))
            legs[s] = (H[s], k, a, 'side', hang(k, a))
        G = hy + lw / 2 + 2
    elif pose == 'cross':
        for s in (-1, 1):
            legs[s] = ((s * hx, hy), (s * (hx + 27 * f), hy + 6), (-s * 9 * f, hy + 17), 'none', 0)
        G, over = hy + 17 + lw / 2 + 1, True
    elif pose == 'prone':
        for s in (-1, 1):
            k = (H[s][0] - d * T, hy + 3)
            a = (k[0] - d * (4 if s == near else 16), k[1] - N * (.92 if s == near else .8))
            legs[s] = (H[s], k, a, 'side', hang(k, a))
        G, lean = hy + lw / 2 + 3, d * 76
    else:
        raise SystemExit(f'pose must be one of {POSES}')
    return legs, G, lean, near, over


def _leg_xml(sp, leg, lit, d):
    """One re-posed leg: skin + sock (children, 老师) or trouser + hem (adults), then the shoe."""
    h, k, a, shoe, ang = leg
    c = 0 if lit else 1
    lw, ss = sp['lw'], sp['ss']
    out = []
    line = f'M{P(h)}L{P(k)}L{P(a)}'
    u = unit(k, a)
    if 'hem' in sp:
        out.append(f'<path d="{line}" fill="none" stroke="{sp["limb"][c]}" stroke-width="{n(lw)}" stroke-linejoin="round"/>')
        out.append(f'<path d="M{P((a[0] - u[0] * 7, a[1] - u[1] * 7))}L{P(a)}" fill="none" stroke="{sp["hem"][c]}" stroke-width="{n(lw + .5)}"/>')
        off = 9
    else:
        out.append(f'<path d="{line}" fill="none" stroke="{sp["limb"][c]}" stroke-width="{n(lw)}" stroke-linecap="round" stroke-linejoin="round"/>')
        if 'sock' in sp:
            out.append(f'<path d="M{P((a[0] - u[0] * 9, a[1] - u[1] * 9))}L{P((a[0] + u[0] * 3, a[1] + u[1] * 3))}" fill="none" stroke="{sp["sock"][c]}" stroke-width="{n(lw + 1)}" stroke-linecap="round"/>')
        off = 12 if sp.get('kid') else 6
    col = sp['shoe'][c]
    sc = f' scale({n(ss)})' if ss != 1 else ''
    if shoe == 'front':
        out.append(f'<g transform="translate({n(a[0])} {n(a[1] + off)}) rotate({n(ang)}){sc}">{SHOE_F % col}</g>')
    elif shoe == 'side':
        o_ = 9 if 'hem' in sp else 4
        p = (a[0] + u[0] * o_, a[1] + u[1] * o_)
        m = f' scale({n(-ss)} {n(ss)})' if d > 0 else sc
        out.insert(0, f'<g transform="translate({n(p[0])} {n(p[1])}) rotate({n(ang)}){m}">{SHOE_S % col}</g>')
    return ''.join(out)


def build_figure(card, who, pose='stand', at=(400, 440), look=None, face=None, expr='smile', l='hang', r='hang', lean=None,
                 tilt=None, s=None, elbow=None, hand=None, behind=(), held='', bag=False, shadow=True, name=None, layer='mid',
                 view=None, halo=None, pieces=False, split=False):
    """See KIT.md §3. Returns the Figure (already added to the card unless pieces=True)."""
    key = NAMES.get(who, who)
    if key not in SPEC:
        raise SystemExit(f'unknown cast member {who}: use one of {sorted(NAMES)}')
    if pose not in POSES:
        raise SystemExit(f'pose must be one of {POSES}')
    if expr not in EXPR:
        raise SystemExit(f'expr must be one of {EXPR}')
    if look is None:
        raise SystemExit(f'{who}: look=(x, y) is required — every figure looks at what it does or at the other figure, never at the viewer')
    sp = SPEC[key]
    S = s or card.S
    fig = Figure()
    fig.name, fig.pose, fig.sp, fig.S = sp['zh'] if name is None else name, pose, sp, S
    fig.order = len(card.items)
    R, hy = sp['R'], sp['hip'][1]
    wb, by = sp['waist']
    piv = (0, by + 6)
    notes = card.notes
    if hasattr(look, 'head'):
        look = look.head
    # --- which way: from `face`, else from where the figure looks
    lx = look[0] - at[0]
    if face is None:
        face = 'left' if lx < -30 else ('right' if lx > 30 else 'front')
    d = -1 if face == 'left' else (1 if face == 'right' else (-1 if lx <= 0 else 1))
    fig.face = face
    # --- legs and placement
    standing = pose in ('stand', 'bend')
    if standing:
        G, dl, near, over, legs = sp['G'], (d * 30 if pose == 'bend' else 0), d, False, None
    else:
        legs, G, dl, near, over = _legs(pose, d, sp)
    lean = dl if lean is None else lean
    X, Y = at[0], at[1] - S * G
    to_c = lambda p: (X + S * p[0], Y + S * p[1])                      # local (un-leaned) → canvas
    lean_c = lambda p: to_c(rot(p, lean, piv))                          # local inside the lean group → canvas
    from_c = lambda p: rot(((p[0] - X) / S, (p[1] - Y) / S), -lean, piv)   # canvas → inside the lean group
    # --- head: rotation, view, gaze
    hk = max(0.0, min(1.0, (abs(lean) - 20) / 40))
    hc0 = lean_c((0, 0))
    v = (look[0] - hc0[0], look[1] - hc0[1])
    vd = math.hypot(*v) or 1.0
    side_look = abs(v[0]) > 34
    gd = (1 if v[0] > 0 else -1) if side_look else 0
    if tilt is None:
        tilt = max(-8.0, min(8.0, 11 * gd * v[1] / vd)) if gd else 0.0
    down = max(-5.0, min(5.0, 7 * v[1] / vd))
    has_q = 'q' in sp
    if view is None:
        view = 'q' if (has_q and gd) else 'front'
    if view == 'q' and not has_q:
        view = 'front'
    flip = view == 'q' and gd > 0
    fwd = (4.0 if side_look else 0) if view == 'q' else (6.0 * gd if gd else max(-3.0, min(3.0, 6 * v[0] / vd)))
    hrot = tilt - lean * hk
    hx_ = head_xml(sp, view, expr, fwd=fwd if view == 'q' else fwd, down=down, flip=flip)
    head = f'<g transform="rotate({n(hrot)} 0 48)">{hx_}</g>' if abs(hrot) > .05 else hx_
    if halo if halo is not None else card.L.get('halo'):
        head = f'<ellipse cx="-24" cy="-26" rx="{n(R + 10)}" ry="{n(R + 12)}" fill="{card.glow("#FFF8DE")}" opacity=".3"/>' + head
    fig.view, fig.tilt, fig.look = ('3/4 ' + ('right' if flip else 'left')) if view == 'q' else ('front' + (f' features {n(fwd)},{n(down)}' if (fwd or down) else '')), round(hrot, 1), look
    hc = lean_c(rot((0, 0), hrot, (0, 48)))
    fig.head, fig.r = hc, S * R
    fig.top = hc[1] - S * (R + 8)
    fx = (-14 * .9 - fwd) * (-1 if flip else 1) if view == 'q' else fwd
    fig.mouth = lean_c(rot((fx, 33 + down), hrot, (0, 48)))
    fig.eyes = lean_c(rot((fx, 11 + down), hrot, (0, 48)))
    fig.face_box = (hc[0] - S * R * .62, hc[1] - S * R * .5, hc[0] + S * R * .62, hc[1] + S * R * .8)
    if S * R < 37 and layer == 'mid':
        if not any(m.startswith(f'SIZE: {fig.name} ') for m in notes):
            notes.append(f'SIZE: {fig.name} head radius {round(S * R)} px — a figure that acts needs ≥ 40 (children) / ≥ 37 (adults): raise s')
    # --- arms
    elbow, hand, hs = dict(elbow or {}), dict(hand or {}), sp['hs']
    named = {'hip': lambda sd: ((sd * (wb + 3), by - 8), 'out'), 'chin': lambda sd: ((sd * 15, 49), 'down'), 'cheek': lambda sd: ((sd * 40, 27), 'down'),
             'ear': lambda sd: ((sd * 53, 6), 'down'), 'mouth': lambda sd: ((sd * 7, 36), 'down'), 'head': lambda sd: ((sd * 30, -46), 'out'),
             'up': lambda sd: ((sd * (sp['sh'][0] + sp['arm'][0] * .9), sp['sh'][1] - sp['arm'][1] * 1.5), 'out'), 'chest': lambda sd: ((sd * 9, sp['sh'][1] + 34), 'down'),
             'fwd': lambda sd: ((d * (sp['sh'][0] + sp['arm'][0] * 1.3), sp['sh'][1] + 18), 'down'), 'eyes': lambda sd: ((sd * 17, 12), 'down')}
    arms, fig.hands, pts = {}, {}, []
    for sd, key_, tgt in ((-1, 'l', l), (1, 'r', r)):
        Sh = (sd * sp['sh'][0], sp['sh'][1])
        if tgt == 'hang':
            E, Wr = (sd * sp['hangE'][0], sp['hangE'][1]), (sd * sp['hangW'][0], sp['hangW'][1])
            if pose == 'prone':
                tgt = 'chin'
        if tgt == 'knee' and legs:
            hh_, kk = legs[sd][0], legs[sd][1]
            on = lerp(hh_, kk, .85 if sp.get('kid') else .5)                 # a child's hand reaches the knee, an adult's rests on the thigh
            tgt_l = rot((on[0], on[1] - sp['lw'] / 2 - 5), -lean, piv)
            E, Wr = _solve_arm(Sh, tgt_l, *sp['arm'], hs, elbow.get(key_, 'down'), sd, notes, f'{fig.name} {key_} hand', quiet=True)
        elif tgt != 'hang':
            if isinstance(tgt, str):
                if tgt not in named:
                    raise SystemExit(f'hand target must be (x, y) on the canvas or one of hang, knee, {", ".join(named)}')
                tgt_l, eb = named[tgt](sd)
                if tgt in ('ear', 'cheek', 'head', 'eyes', 'chin', 'mouth'):
                    tgt_l = rot(tgt_l, hrot, (0, 48))
            else:
                tgt_l = from_c(tgt)
                eb = 'out' if tgt_l[1] < Sh[1] - 4 else 'down'
            E, Wr = _solve_arm(Sh, tgt_l, *sp['arm'], hs, elbow.get(key_, eb), sd, notes, f'{fig.name} {key_} hand', quiet=isinstance(tgt, str))
        u = unit(E, Wr)
        palm = (Wr[0] + u[0] * 11.5 * hs, Wr[1] + u[1] * 11.5 * hs)
        fig.hands[key_] = lean_c(palm)
        hc_l = rot((0, 0), hrot, (0, 48))
        on_head = dist(palm, hc_l) < R + 8 and key_ not in behind
        arms[key_] = (_arm_xml(sp, sd, Sh, E, Wr, sd < 0, hand.get(key_, 'open'), hs, wb), on_head)
        pts += [lean_c(E), lean_c(Wr), lean_c(palm)]
    # --- lower body
    low, legpts = [], []
    if standing:
        low = [sp.get('st_legs', ''), sp.get('st_shoes', ''), sp.get('st_bottom', '')]
        if key == 'nainai':
            low = [_leg_xml(sp, ((sx * 17, 216), (sx * 17.5, 300), (sx * 18, 380), 'front', -sx * 6), sx < 0, d) for sx in (1, -1)]
        hx0 = sp['hip'][0] + sp['lw'] / 2 + 6
        legpts = [to_c((-hx0, G)), to_c((hx0, G)), to_c((-wb - 16, by + 40)), to_c((wb + 16, by + 40))]
    else:
        order = [s_ for s_ in (-1, 1) if s_ != near] + [near]
        cov = sp.get('cover')
        parts = []
        for s_ in order:
            lit = s_ < 0
            parts.append(_leg_xml(sp, legs[s_], lit, d))
            if cov and pose != 'sit_front' and not (pose == 'walk' and sp.get('st_bottom')):
                h_, k_, a_ = legs[s_][:3]
                e_ = lerp(h_, k_, cov[0])
                cw = sp['lw'] + cov[1]
                parts.append(f'<path d="M{P(h_)}L{P(e_)}" fill="none" stroke="{sp["bottom"][0 if lit else 1]}" stroke-width="{n(cw)}" stroke-linecap="round"/>')
                if sp.get('long'):
                    parts.append(f'<path d="M{P(k_)}L{P(lerp(k_, a_, sp["long"]))}" fill="none" stroke="{sp["bottom"][0 if lit else 1]}" stroke-width="{n(cw)}" stroke-linecap="round"/>')
            legpts += [to_c(p) for p in legs[s_][:3]]
        fill = f'url(#{sp["bgrad"]})' if sp['bgrad'] else sp['bottom'][0]
        pel = f'<path d="M{n(-wb)},{n(by)}L{n(wb)},{n(by)}L{n(wb + 2)},{n(hy + 4)}Q0,{n(hy + sp["lw"] / 2 + 3)},{n(-wb - 2)},{n(hy + 4)}Z" fill="{fill}"/>'
        if not sp['bgrad']:
            pel += f'<path d="M0,{n(by)}L{n(wb)},{n(by)}L{n(wb + 2)},{n(hy + 4)}Q{n(wb / 2)},{n(hy + sp["lw"] / 2 + 1)},0,{n(hy + sp["lw"] / 2 + 3)}Z" fill="{sp["bottom"][1]}"/>'
        if pose == 'sit_front':                                              # the lap: skirt / trousers spread over the thighs, knees at its front edge
            lx_ = sp['hip'][0] + 15 + sp['lw'] * .62
            if sp.get('cover') and sp['bgrad'] in ('c-denim', 'c-powder'):       # a skirt: one lap, the knees peek out under its hem
                ly_ = hy + 14
                low_edge = f'Q0,{n(ly_ + 8)},{n(-lx_)},{n(ly_)}'
            else:                                                                # shorts / trousers: two thighs towards us, a notch between them
                ly_ = hy + 15 + (sp['lw'] * .5 if 'hem' in sp else 1)
                low_edge = f'Q{n(lx_ * .5)},{n(ly_ + 7)},3,{n(ly_ + 2)}L0,{n(hy + 2)}L-3,{n(ly_ + 2)}Q{n(-lx_ * .5)},{n(ly_ + 7)},{n(-lx_)},{n(ly_)}'
            pel = (f'<path d="M{n(-wb)},{n(by)}L{n(wb)},{n(by)}C{n(wb + 14)},{n(hy - 8)},{n(lx_ + 6)},{n(hy + 4)},{n(lx_)},{n(ly_)}{low_edge}C{n(-lx_ - 6)},{n(hy + 4)},{n(-wb - 14)},{n(hy - 8)},{n(-wb)},{n(by)}Z" fill="{fill}"/>')
        if pose == 'walk' and sp.get('st_bottom'):
            pel = sp['st_bottom']                                            # the standing skirt / shorts hang over walking legs
        low = [pel] + parts if over else parts + [pel]
        legpts += [to_c((0, G))]
    # --- assemble
    hide = ''
    if abs(lean) > 20:
        hide = f'<circle cx="0" cy="{n(piv[1])}" r="{n(wb - 1)}" fill="{sp["bottom"][0] if not sp["bgrad"] else "url(#" + sp["bgrad"] + ")"}"/>'
    bagb = bags = ''
    if bag:
        b0, b1, b2 = sp.get('bag', ('#8FB8E8', '#6C92CC', '#FFF3B8'))
        if bag is not True:
            b0, b1 = bag
        bagb = (f'<rect x="{n(-wb - 8)}" y="{n(sp["sh"][1] - 4)}" width="{n(2 * wb + 16)}" height="{n(by - sp["sh"][1] + 4)}" rx="15" fill="{b1}"/>'
                f'<rect x="{n(-wb - 8)}" y="{n(sp["sh"][1] - 4)}" width="{n(wb + 4)}" height="{n(by - sp["sh"][1] + 4)}" rx="15" fill="{b0}"/>')
        bags = ''.join(f'<path d="M{n(sx * (wb - 13))},{n(sp["sh"][1] - 11)}Q{n(sx * (wb - 8))},{n((sp["sh"][1] + by) / 2)},{n(sx * (wb - 9))},{n(by - 12)}" fill="none" stroke="{b0 if sx < 0 else b1}" stroke-width="6.5" stroke-linecap="round"/>' for sx in (1, -1))
    front = ''.join(a for k_, (a, oh) in arms.items() if k_ not in behind and not oh)
    back = ''.join(a for k_, (a, oh) in arms.items() if k_ in behind)
    overh = ''.join(a for k_, (a, oh) in arms.items() if oh)
    lg = (lambda x: f'<g transform="rotate({n(lean)} {n(piv[0])} {n(piv[1])})">{x}</g>') if abs(lean) > .05 else (lambda x: x)
    torso = sp['torso'] + (sp.get('torso_low', '') if standing else '')
    wrap = lambda x: f'<g transform="translate({n(X)} {n(Y)}) scale({n(S)})">{x}</g>'
    if held:                                     # given in canvas coordinates: undo the figure's own transform around it
        back_ = (f'rotate({n(-lean)} {n(piv[0])} {n(piv[1])}) ' if abs(lean) > .05 else '') + f'scale({1 / S:.4f}) translate({n(-X)} {n(-Y)})'
        held = f'<g transform="{back_}">{held}</g>'
    held = held or ''
    if split:                                    # the arms go on top of something drawn later (a table they rest on): card.add(fig.arms)
        fig.arms = wrap(lg(held + front + overh))
        front = overh = held = ''
    body = (lg(bagb + back) if (bagb or back) else '') + ''.join(low) + lg(hide + torso + bags + held + front + head + overh)
    xml = wrap(body)
    sh_pts = [lean_c((-sp['sh'][0] - sp['aw'] / 2, sp['sh'][1] - 10)), lean_c((sp['sh'][0] + sp['aw'] / 2, sp['sh'][1] - 10))]
    fig.box = box_of(pts + legpts + sh_pts + [(hc[0] - S * (R + 4), hc[1] - S * (R + 8)), (hc[0] + S * (R + 4), hc[1] + S * R)])
    fig.feet_y = max(p[1] for p in legpts)
    fig.zoom_box = (max(0, hc[0] - S * R * 1.9), max(0, hc[1] - S * R * 1.6), S * R * 3.8, S * R * 3.6)
    fig.xml = xml
    if not pieces:
        if shadow and pose not in ('sit', 'sit_front'):
            cx = (min(p[0] for p in legpts) + max(p[0] for p in legpts)) / 2
            rx = max(30.0, (max(p[0] for p in legpts) - min(p[0] for p in legpts)) / 2 + 8)
            card.shadow(cx, at[1] + 1, rx)
        card.add(xml, layer=layer, name=fig.name, box=fig.box, kind='figure')
        card.figures.append(fig)
    return fig


# ---------------------------------------------------------------------------------------------------- 团子 and 路人
_CAT = {'sit': ([C(156), C(157), C(158)], (C(159), C(160)), 91, (-42, -46, 62, 91), None),
        'curl': ([C(171), C(172)], None, 47, (-38, -52, 102, 52), C(173) + C(174)),
        'pounce': ([C(178), C(179), C(180), C(181)], None, 66, (-58, -88, 152, 60), C(182) + C(183)),
        'peek': ([], (C(164), C(165)), 20, (-42, -46, 42, 30), None)}


def build_cat(card, pose='sit', at=(400, 440), look=None, face='left', s=None, tilt=0.0, layer='mid', shadow=True, name='团子'):
    """团子. sit / curl (asleep) / pounce (to the side it faces) / peek (head + paws over YOUR edge at y = at[1])."""
    if pose not in _CAT:
        raise SystemExit(f'cat pose must be one of {sorted(_CAT)}')
    S = s or card.S
    body, head, G, bx, tail = _CAT[pose]
    m = -1 if (face == 'right' and pose in ('curl', 'pounce')) else 1
    X, Y = at[0], at[1] - S * G
    if head:
        gx = gy = 0.0
        if look is not None:
            hc = (X, Y)
            v = (look[0] - hc[0], look[1] - hc[1])
            vd = math.hypot(*v) or 1
            gx, gy = 3.2 * v[0] / vd, 2.4 * v[1] / vd
            tilt = tilt or max(-8, min(8, 7 * v[0] / vd))
        hx = head[0] + f'<g transform="translate({n(gx)} {n(gy)})">{head[1]}</g>'
        inner = ''.join(body) + (f'<g transform="rotate({n(tilt)} 0 24)">{hx}</g>' if tilt else hx)
        if pose == 'peek':
            inner += C(167)
    else:
        inner = ''.join(body) + tail
    xml = f'<g transform="translate({n(X)} {n(Y)}) scale({n(m * S)} {n(S)})">{inner}</g>'
    xs = sorted((X + m * S * bx[0], X + m * S * bx[2]))
    box = (xs[0], Y + S * bx[1], xs[1], Y + S * bx[3])
    f = Figure()
    f.name, f.pose, f.face, f.view, f.tilt, f.look = name, pose, face, 'cat', tilt, look or (X, Y)
    f.head, f.r, f.top, f.hands, f.box, f.order = (X, Y), S * 34, Y - S * 46, {}, box, len(card.items)
    f.mouth, f.eyes = (X, Y + S * 12), (X, Y - S * 3)
    f.face_box = (X - S * 26, Y - S * 16, X + S * 26, Y + S * 22)
    f.zoom_box = (max(0, box[0] - 20), max(0, box[1] - 20), box[2] - box[0] + 40, box[3] - box[1] + 40)
    f.feet_y, f.xml = at[1], xml
    if shadow and pose != 'peek':
        card.shadow((box[0] + box[2]) / 2, at[1] + 1, (box[2] - box[0]) / 2 * .8)
    card.add(xml, layer=layer, name=name, box=box, kind='figure')
    card.figures.append(f)
    return f


_PASS = {'man': ([F(i) for i in range(193, 197)], 436, 46), 'woman': ([F(i) for i in range(197, 202)], 416, 48), 'child': ([F(i) for i in range(202, 206)], 272, 50)}


def build_passerby(card, kind='man', at=(600, 300), s=.4, flip=False, layer='mid', opacity=.8):
    """路人: a small flat figure for the distance (s .3 – .5), feet on at[1]. Never in the foreground, never the subject."""
    lines, G, R = _PASS[kind]
    X, Y = at[0], at[1] - s * G
    xml = f'<g transform="translate({n(X)} {n(Y)}) scale({n(-s if flip else s)} {n(s)})" opacity="{n(opacity)}">{"".join(lines)}</g>'
    card.add(xml, layer=layer, name='路人', box=(X - s * 60, Y - s * R, X + s * 70, at[1]), kind='soft')
    return (X, Y)
