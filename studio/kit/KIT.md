# KIT.md — drawing a memory card with the kit

A card is ONE short Python script (60–110 lines) that calls `studio/kit`. The kit owns everything the house style
fixes — the cast (faces, hair, clothes, limbs that connect), the five light setups, ground and rooms, common props,
the word layer, the technical rules of `STUDIO.md` — and checks the layout in numbers. You own what makes the card
THIS word: the moment, where people are, what they do with their hands, where they look, the two or three props only
this scene has, the hook. You do not need the other handbooks.

```python
import sys; sys.path.insert(0, '/Users/sqin/word-dance/studio')
import kit
c = kit.new('run', 'bright', calm=(430, 322, 776, 478), brief='/…/briefs/run.json')   # word, light, calm zone, brief
c.sky(horizon=250, clouds=3); c.town(base=254, hmin=50, hmax=120)                      # far → near
c.ground(250, 'lawn'); c.hedge(-10, 330, 290, h=30, flowers='#FFB3C6'); c.ground(292, 'plaza')
c.tree(118, 300, h=236, crown=96); c.tree(585, 296, h=190, crown=78)
f = c.figure('乐乐', 'run', at=(232, 436), look=(560, 250), expr='laugh', bag=True, s=.84,
             l=(182, 322), r=(292, 290), elbow={'l': 'up'})
c.add('<g fill="#FFFFFF" opacity=".8"><path d="M30,300L150,294L150,302Z"/><path d="M52,352L160,344L160,354Z"/></g>')   # speed streaks
c.leaves([(96, 372, 30), (60, 396, -40)], cols=('#8FD06A', '#F2B63C'), s=.7)
c.write()                                                                             # the word, centred in the calm zone
c.caption(alt_zh='晴朗的早晨，背着书包的乐乐在上学路上飞快地奔跑……', hook_zh='r、u、n 三个字母三个音，u 读短音 /ʌ/。', note_zh='')
c.save('/…/out')          # writes out/cards/run.svg, runs tools/check, prints the report and the paths of the renders
```

Run it with `python3 card.py`. The report lists every figure (head, hands, box), the word (size, ink box), the layout
findings (lines starting with `!`) and the tool's `ERROR` / `warning` lines. Fix every `!` and `ERROR`, then open
`…/png/<word>.sheet.png` ONCE (the scene without the word + the phone-size card) and the zooms if a face or hand is in
doubt. One or two rounds are normal; do not polish beyond what the brief asks.

## 1. Plan (in your head, 5 lines) before you type
Canvas 800 × 500, y down, light from the UPPER LEFT. Decide: (1) the **calm zone** — a quiet rectangle of ground /
table / sky / water, about a third of the canvas (≈ 350 × 150 for a short word, the full width × 130 for a long one),
where NOTHING else stands; (2) where the figures stand so that the thing that carries the meaning is big and in the
light; (3) who looks at what. Typical layouts: figures on one side, word on the other at the bottom; or figures behind a
table / across the middle and the word on the table / ground in front.
Sizes at the default scale `s=.8`: a child's head radius 45 px, standing child 270 px tall (feet → hair top), sitting
on a stool 215; adults stand 350–400 px tall — an adult never fits standing over the word: seat them (bench, sofa, bed
edge), bend or crouch them, or cut them behind a table / counter (`at` below the table line, table drawn after).
Head radius must stay ≥ 40 px for children and ≥ 37 for adults (`s ≥ .75`). ONE `s` for everybody on a card.
Fill the frame: the figures take 55–75 % of the canvas height; a child behind a `tabletop` at line T stands with
`at=(x, T + 150)` so the table cuts it at the waist (hands and props on the table stay visible). An empty wall or sky
gets ONE quiet thing (a shelf, a picture, a plant, a lamp, a branch, a cloud), never a row of them.

## 2. Stage — one light setup per card
`kit.new(word, light, calm, brief, s=.8)` — light: `'window'` 晨光窗 (indoors, low morning sun through a window on the
left) · `'golden'` 金色户外 · `'bright'` 晴空亮水 · `'rain'` 雨天柔光 · `'night'` 月夜灯光 (also for lamp-lit rooms at night).
Call order = drawing order inside a layer; layers stack back → far (blurred) → ground → shadows → mid → fx → near.

Outdoors: `c.sky(horizon=262, clouds=2, moon='crescent'|'full'|None, stars=26, milky=0)` · `c.town(base, hmin, hmax)` soft
blocks · `c.far_trees(base, x0, x1, h)` · `c.hills(base)` · `c.ground(y, kind, tilt=0)` kind `lawn | path | plaza | wet | water
| sand` — stack calls for bands (lawn strip at 250, paving from 292). Seams, tufts, ripples stay out of the calm zone.
Indoors: `c.room(floor_y=336, floor='wood'|'tile'|'rug'|None)` · `c.window(x, y, w, h, view='trees'|'town'|'sky', curtains=True,
panes=(2, 2))` — in `'window'` light keep it at the left with the sun (118, 96) inside it: shafts and the light patch
follow · `c.lamp(x, y, kind='ceiling'|'desk'|'floor'|'wall', glow=150)` — the warm accent of rain / night cards.
Weather: `c.rain()` (call it AFTER the figures) · `c.motes()` · `c.bokeh([(x, y, r)…])` · `c.glint(x, y)`.

## 3. Figures
`f = c.figure(who, pose, at=(x, y), look=(x, y), expr='smile', l='hang', r='hang', …)`
- who: 朵朵 · 乐乐 · 奶奶 · 爸爸 · 妈妈 · 爷爷 · 李老师.  `c.cat(pose, at, look, face)` = 团子: `sit | curl | pounce | peek`.
  `c.passerby('man'|'woman'|'child', at, s=.4)` only small and far.
- A seated child on front steps: `ys = c.steps(...)`, then `pose='sit_front', at=(x, ys[0])` — it sits on the top
  step with its feet on the next one.
- pose and what `at` means: `stand` `bend` `walk` `run` `kneel` (upright on the knees) `sit_heels` (跪坐) `crouch`
  `sit_floor` (legs forward) `cross` (cross-legged, front) `prone` (趴着, chin on hands) → `at` = the spot on the GROUND
  under the body; `sit` (side view on a seat, legs to the facing side) and `sit_front` (seat faces us) → `at` = the
  middle of the SEAT's top edge (draw the seat first: `c.bench / stool / chair / sofa / bed / steps` return that line).
- `look=(x, y)` is REQUIRED: the thing or the face (`other.head`) this figure looks at. Nobody looks at the viewer.
  The kit turns the head (3/4 view, tilt, shifted features) from it; `face='left'|'right'` only to override the body's
  direction. 乐乐 has a front head only — he turns by the features.
- hands: `l=` (picture-left arm) and `r=`: a canvas point for the palm, or `'hang' 'hip' 'knee' 'chin' 'cheek' 'ear'
  'mouth' 'eyes' 'head' 'chest' 'up' 'fwd'`. Reach from the shoulder at s .8: child ≈ 60 px, adult ≈ 100 px — a `REACH`
  note means move the target or the figure. `elbow={'l': 'up'|'down'|'out'|'in'}`, `hand={'r': 'hold'|'point'|'none'}`
  (`hold` = closed round a handle). `held='<svg…>'` (canvas coordinates) is drawn between body and hands: a book or a
  schoolbag hugged against the chest (`l='chest', r='chest'`), a pencil from `c.pencil(tip, end)` whose tip is the hand
  target; for a thing in ONE raised hand draw it after the figure at `f.hands['r']`.
- `expr`: `smile` · `laugh` · `calm` (lips closed, eyes open: concentrating, listening to somebody) · `open` (mouth open:
  speaking, counting, amazed) · `shut` (EYES closed: asleep, listening to a sound, hurt-but-laughing).
- `lean=deg` tips the upper body (+ = to picture-right) · `tilt=deg` overrides the head tilt · `bag=True` schoolbag on
  the back · `s=` scale · `split=True` + later `c.add(f.arms)` when the arms rest on a table drawn after the body.
- Afterwards: points `f.head` (centre) `f.mouth` `f.eyes` `f.hands['l'|'r']`; numbers `f.r` (head radius) `f.top` (y of the
  hair top) `f.feet_y`; `f.box` = (x0, y0, x1, y1) — use them to place props, sound arcs, the umbrella, the other's `look`.
Two people who talk stand / sit close (heads 110–170 px apart) and look at EACH OTHER; an adult looks at the child.

## 4. Props
Scenery: `c.tree(x, y, h, crown)` · `c.big_tree(side)` (old tree framing one edge + canopy along the top) ·
`c.branch('tl'|'tr')` · `c.bush(x, y, r, flowers=col)` · `c.hedge(x0, x1, y, h)` · `c.tufts(count=…)` · `c.flowers(count=…)` ·
`c.leaves([(x, y, deg)…])` · `c.puddle(x, y, rx)` · `c.house(x, y, w, h)`.
Furniture (y = the top edge things sit / stand on): `c.bench(x, y, w, h)` · `c.stool(x, y)` · `c.chair(x, y, face)` ·
`c.table(x, y, w, h, kind='wood'|'desk'|'stone'|'round'|'low')` (stone / round = a round top seen a little from above) ·
`c.tabletop(y, kind='cloth'|'wood')` (a table across the whole foreground — the calm zone lies on it; a figure behind
it is added BEFORE it with `at=(x, y + 150)`, so the table cuts it at the waist) · `c.sofa(x, y, w)` · `c.bed(x, y, w, head)` ·
`c.steps(x0, x1, y, count, rise)` · `c.door(x, y, w, h, opened, lit)` · `c.shelf(x, y, w, h)`.
Small (x, y = where it STANDS, unless said otherwise; pass every option BY KEYWORD; a colour is one `'#RRGGBB'` or a
tuple lit → shade): `c.book(x, y, w=44, h=58, col=, deg=0, opened=False)` (x, y = centre) · `c.bag(x, y, col=)` ·
`c.ball(x, y, r=22, kind='football'|'plain'|'basket')` (centre) · `c.cup(x, y, kind='mug'|'glass', steam_h=40)` ·
`c.bowl(x, y, w=60, food=col)` · `c.pencil(tip, end, col=, w=9)` (returns SVG: `c.add(...)` it or pass it as `held=`) ·
`c.paper(x, y, w=90, h=62)` (centre) · `c.umbrella(x, y, r=110, col=, hand=f.hands['r'])` (x, y = top of the dome) ·
`c.bird(x, y, s=1, col=, face='left'|'right', sing=False)` (x, y = its feet; returns the beak tip) ·
`c.sound(x, y, deg, count=3, size=1)` voice arcs leaving (x, y), deg 0 = right, 180 = left · `c.steam(x, y, h)` ·
`c.plant(x, y, s=1)` · `c.picture(x, y, w, h)` (wall).
Your own prop: `c.shape(d, fill, name=, box=, rim=)` (fill = one colour or three, lit → shade) or
`c.add('<svg shapes>', name=, box=(x0, y0, x1, y1))`. Allowed elements: `g rect circle ellipse line polyline polygon path`
with plain attributes (`fill stroke stroke-width stroke-linecap stroke-linejoin stroke-dasharray opacity transform d …`);
no `text`, `style`, `class`, `use`, `image`; at most one decimal. Draw a prop from 3–8 simple shapes: body in its
colour, a darker shade on the right / lower side, a pale highlight stroke on the upper left, and put it ON something
(`c.shadow(x, y, rx)` under it). At most about six props; each identifiable at phone size (≥ 60 px when it carries the
meaning or the hook), from a Chinese pupil's everyday life. NO letters, digits, characters, signs or logos anywhere
in the scene; clocks without numerals, books and papers with abstract lines.

## 5. The word and the hook
`w = c.write(zone=None, colors=None, letters=None, on=None, size=None)` — real letters, as big as the zone allows,
centred in it. Chunks, stress, silent letters (ghost letters) and double letters (twins + a small bridge) come from
the brief's `dance`; the stressed chunk is coral, its neighbour indigo, a third green (on a dark zone gold / moon /
mint). A ghost letter keeps its chunk's colour: recolour a whole one-chunk word with `colors='indigo'`. `colors=['green', 'coral']` per chunk or `letters={0: 'coral', 3: 'plum'}` per letter only when the hook needs
it or a default would vanish on its ground (never coral on red, indigo on deep blue, green on grass — the calm zone
of a lawn is pale, that is fine). Light zone: `coral indigo green plum orange teal pink brown`; dark: `gold moon mint pink coral`.
A `WORD` note = something stands within 24 px of the letters, or the zone is too small: move things, not the rules.
The hook is ACTED OUT in the scene (it must survive without the word); the word then points at it by colour or
alignment. For a letter that becomes part of the picture use `w.letter(i)['bbox' | 'cx' | 'cy']`, `w.counter(i)` (the hole of
`o a e d p b g`), `w.chunk_box(k)`, `w.ink`, then `w.over('<shapes>')` / `w.under('<shapes>')` — never on the strokes,
never a generic sparkle; nothing in a chunk colour next to the word that could read as a letter. If the direction
says "no forced hook", colour the chunks and stop.
`c.caption(alt_zh=…, hook_zh=…, note_zh=…)`: alt_zh = who does what, where, in which light (one plain sentence);
hook_zh ≤ 34 characters, for the child; note_zh ≤ 30, only what the direction gives. No 谐音, no invented etymology.

## 6. What still depends on you (the juries' most frequent findings)
1. The thing that carries the meaning is BIG and inside the light; the caption's named gestures are visible.
2. Everybody looks at what they do or at each other — check the `look→` of every figure in the report.
3. Poses are asymmetric and say one thing; hands touch what they hold; seats, feet and props stand on something.
4. Day cards stay bright (no dark or brown corners); night cards are deep blue with a warm lit area for the faces.
5. Nothing crosses a face (steam, rain, umbrella rim, a branch) — a `FACE` note tells you.
6. A light effect is soft and never reads as an object; no mechanical rows; nothing countable besides the subject of a number card.
