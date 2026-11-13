# word-Dance 记忆图卡 — studio handbook

word-Dance（单词之舞）is a vocabulary app for Chinese primary-school pupils (6–11 years old). The back of every word
card shows one 16:10 picture. The 600 pictures of the 小学 list were drawn as tiny flat SVGs (≈ 2 KB each, a single
subject on a plain background). The owner finds them **不够生动** and asked for a new generation:

1. **更加生动形象，贴近生活** — a living moment from a child's everyday life, not an icon on a blank background.
2. **唯美风格** — genuinely beautiful: light, atmosphere, depth, a harmonious palette, delicate finishing.
3. **增加单词记忆功能** — the picture must help the child remember the WORD (its spelling and sound), not only the meaning.

The owner approved the first ten cards on 2026-11-13 (「样例图卡符合我的预期」): they are `studio/cards/*.svg`, and they
are the standard every further card is held to. Quality beats speed: a card that a parent would happily print and hang
on the wall, and that a seven-year-old understands at one glance.

Everything lives in `studio/` of the repository. The paths in this handbook are relative to the repository root; when
you call a tool or open a render, use the absolute path in your checkout:

    studio/README.md             (Chinese) the pipeline end to end, setting the tools up, importing finished cards into the app, undoing that
    studio/STUDIO.md             this handbook (contract, scene rules, memory layer, tools)
    studio/STYLE.md              the HOUSE STYLE chosen by the jury — read it right after this file; where it is stricter, it wins
    studio/LESSONS.md            what the juries marked down on the first batch trials — read it after STYLE.md, before you plan or draw
    studio/cast/CAST.md          the cast sheet: reusable SVG fragments for 朵朵, 乐乐, 奶奶, 团子 (use them, keep the look)
    studio/cards/<word>.svg      the approved cards — your references (render one with `studio/tools/check`, §4); a card joins them when it is approved
    studio/manifest.json         the captions of the approved cards (`alt_zh`, `hook_zh`, `note_zh`, §3) — what `wd images-import` reads
    studio/tools/letters         real letterforms for the word-art layer (see §3)
    studio/tools/check           sanitise + validate + render (see §4)
    studio/fonts/Andika-Bold.ttf Andika Bold (SIL OFL 1.1, `studio/fonts/OFL.txt`) — the literacy font all word-art uses

The **brief** of a word — the data you draw from — is a working file, not part of the repository: it is written for each
batch from the app's own data (the word's content and its 单词之舞 annotation), and you are given its path. It looks
like this (the fields this handbook refers to):

    {"word": "breakfast", "meaning_zh": "n. 早餐；早饭", "meaning_en": "The first meal of the day, eaten in the morning.",
     "examples": [{"en": "I eat breakfast at seven.", "zh": "我七点吃早餐。"}, …], "collocations": ["have breakfast", …],
     "mnemonic_zh_current": "联想：break＋fast，打破夜里的禁食（fast），就是早餐。",
     "dance": {"chunks": ["break", "fast"], "stress_chunk_index": 0, "double_letter_index_pairs": [], "silent_letter_indexes": []}}

## 1. The card = one SVG with two layers

    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500">
      <title>…</title>
      <defs> gradients, blur filters, clip paths </defs>
      <g id="scene"> the complete picture — beautiful and unmistakable on its own </g>
      <g id="word-art"> the memory layer: the word itself, made of real letters, woven into the picture </g>
    </svg>

The app serves every card in two forms: as drawn, and — when the learner switches 「图片上显示单词」 off — without
`#word-art`. So **the scene must be complete without it**; with it, the card becomes a memory card. `#word-art` is the
LAST child of the root (top layer; the server removes the layer by cutting the file at that group, so nothing may follow
it); every drawn shape is inside one of the two groups. Every gradient, filter and clip path the scene uses is defined
in the root `<defs>`, never inside `#word-art`: a definition in there is cut away with the layer, the scene would paint
without it, and the import refuses the card (the word layer may keep definitions of its own, and may use the root's).

Hard technical rules (the app's sanitiser and the import's structure check enforce them — `studio/tools/check` runs
both and shows you what would be dropped or refused):

- Elements: `svg g defs title desc rect circle ellipse line polyline polygon path linearGradient radialGradient stop
  filter feGaussianBlur feDropShadow clipPath`. Nothing else: no `text`/`tspan`, `image`, `use`, `mask`, `pattern`,
  `symbol`, `style`, `script`, `animate*`, `foreignObject`, other `fe*` primitives.
- Attributes: plain presentation attributes only (`fill stroke stroke-width stroke-linecap stroke-linejoin
  stroke-dasharray opacity fill-opacity stroke-opacity transform paint-order d points cx cy r rx ry x y x1 y1 x2 y2 width
  height id offset stop-color stop-opacity gradientUnits gradientTransform spreadMethod fx fy filter clip-path
  stdDeviation dx dy flood-color flood-opacity filterUnits clipPathUnits fill-rule`). No `class`, no `data-*`, no `href`, no CSS
  (no `style` attribute: the sanitiser drops every one, as it drops any attribute whose value holds a backslash, and
  `check` reports each as an error); `url(#id)`, written exactly so (no quotes, no
  spaces), only in `fill`, `stroke`, `filter`, `clip-path` and only to ids defined in the same file. Unique ids.
- **No text of any kind in the scene**: no letters, digits, Chinese characters, signs, logos, speech bubbles. Clocks
  have no numerals, books and calendars carry abstract marks only. The only letters on the card are the word-art glyphs.
- Size: aim for 18–40 KB; warning above 45 KB; the sanitiser rejects above 60 KB. Write numbers with at most one decimal.
- Blur (`<filter id=… x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="…"/></filter>`) is the
  tool for glow, mist, soft shadows and depth — but apply it to about a dozen elements at most (put several shapes in one
  filtered `<g>`); old tablets must render the card instantly. The import refuses a card that goes far beyond the house
  style: more than 16 elements with a `filter`, more than 3 `feGaussianBlur` / `feDropShadow` inside one `<filter>` (use
  ONE — a chain of shadows can double the time the card takes to paint with every link), or a `stdDeviation` that is not
  one or two plain numbers from 0 to 60 (the approved cards use .8 to 7; no unit, no exponent); `check` warns above 14
  filtered elements. A soft shadow that follows a shape exactly (letters, a figure) is one
  `<filter id=…><feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#3A1B44" flood-opacity=".35"/></filter>`
  on the group — never paste a shape twice to fake a shadow. A filter on a lone horizontal or vertical line renders
  nothing (zero-size bounding box): put the line in a filtered `<g>` with something else or use `filterUnits="userSpaceOnUse"`.
- Well-formed XML (write `&amp;`), no comments needed, no `width`/`height` on the root.

## 2. The scene (all styles)

- **生动**: one clear *moment* — somebody is doing or feeling something. Show motion and life: steam rising, hair and
  leaves in the wind, splashes, a cat stretching, light moving through a window. Simple, warm expressions (dot eyes,
  a small smile, blush). Diagonals and overlap beat a row of objects.
- **贴近生活**: the everyday world of a pupil in China — home (厨房、客厅、卧室、阳台), school (教室、操场、校门口),
  the 小区 and the park, grandparents' home, familiar food (包子、豆浆、鸡蛋、牛奶、面条、水果), familiar seasons and
  festivals. The child should think "这就是我的生活".
- **唯美**: mood comes from light — morning sun through a window, golden hour, moonlight, rain glow. Build depth in
  layers (far / middle / near), let the atmosphere soften the distance, keep one dominant colour family plus one accent,
  finish with delicate details (petals, leaves, steam, bokeh, reflections). Rich, never cluttered: every element earns
  its place and the eye knows where to go.
- **Meaning first**: the picture shows the sense in the brief (`meaning_zh` + the first example sentence). The subject
  that carries the meaning is the focal point — largest, brightest, sharpest. A child who sees the scene alone should
  be able to say the Chinese meaning.
- **The cast** (the same friends appear on every card — use whoever the scene needs, keep their look):
  - 朵朵 — a girl of about 8: dark-brown bob with a straight fringe, a small **red hair clip** on the picture-right side
    of her fringe, round face;
    usually a warm-yellow top (pyjamas, raincoat, swimsuit when the scene needs it — the hair and the clip stay).
  - 乐乐 — a boy, her classmate: short, slightly tousled black hair, sky-blue top.
  - 奶奶 — silver-grey hair in a low bun, round glasses, an indigo floral apron or cardigan, a kind smile.
  - 团子 — a small orange-and-white cat (an optional cameo that adds life).
  Children are drawn about 3 heads tall, with simple friendly faces (no realistic facial detail).
- Nothing frightening, violent, romantic or commercial. No brands.

## 3. The memory layer (`#word-art`)

The word is on the card as **real, perfectly formed letters** — a pupil copies what they see, so letterforms are never
hand-drawn or distorted. Get them from the tool and paste the `d` strings unchanged:

    studio/tools/letters breakfast --chunks "break|fast" --gap 24 --size 96 --x 400 --baseline 440
    studio/tools/letters rain --split-dots --size 140 --x 250 --baseline 200        # the dot of i / j as a separate path
    studio/tools/letters moon --size 150 --x 400 --baseline 330 --brief             # metrics only (no path data)

It prints JSON: for each letter its `id` (`wa-<index>-<letter>`, keep it — the import spells the headword from these
ids; a hyphen or an apostrophe is `wap-<index>` and does not count), `d` (canvas coordinates), `bbox`
`[x0,y0,x1,y1]`, centre `cx,cy` and `contours` — the bbox of every contour, `hole: true` for a counter (the inside of
`o e a d p b`…). Use these numbers to place decorations exactly on a letter. To move or resize a letter call the tool again
with other numbers; never edit a `d`. A `transform` on the `<path>` or on a group around it may only move a letter, scale
it by ONE factor (`scale(.9)`, never `scale(.8 1)`) and — where the hook truly needs it; the rule of point 1 below stays
"upright" — tip it a few degrees: `studio/tools/check` refuses a mirrored, flipped, stretched, squashed or skewed letter
and one turned more than 15°, and warns above 5°. A word too wide for its zone gets a smaller `--size`, not a squeeze.

The outlines the tool prints are **overlap-free**: the font builds `f`, `t`, `k`, `e` … from overlapping contours (the
crossbar, the arms) and `letters` merges them into one outline per letter, so a dashed keyline — the ghost letter of
`studio/LESSONS.md` #10 — shows no doubled dashes or seams inside the letter. (`--raw-outlines` prints the font's raw
contours instead, only to reproduce the first ten cards, which carry them; `check` accepts both.) The keyline of a
letter is `stroke` + `paint-order="stroke"` on the letter or on its chunk's `<g>`.

Paint the letters with presentation attributes, on the `<path>` or on the `<g>` of its chunk (letters inherit `fill`,
`stroke`, `stroke-width` … from the groups around them). `check` reads the paint the same way and refuses a letter
nobody sees: neither fill nor stroke, `opacity="0"`, `display="none"`, `visibility="hidden"` — on the letter or
inherited — or a letter filed under `<defs>` / used as a `<clipPath>` (the path that carries the `wa-…` id is the one
the card draws). The `-dot` path of `--split-dots` stays exactly as printed, next to its letter (same group, or the same
`transform`) — or is deleted, with the object that replaces it drawn where it was; a `-dot` path that was reshaped,
moved on its own or hidden no longer counts as the dot, and `check` warns `dotless glyph`.

What the layer must do:

1. **Read instantly.** One line, left to right, on a flat horizontal baseline, upright letters — the way a textbook
   prints a word (no arcs, no per-letter tilts or bobbing). Letters at least 76 px em (64 px for words of nine letters
   or more); bigger is better. Strong
   contrast with whatever lies behind: a solid fill plus a contrasting outline (`stroke` with `paint-order="stroke"`
   and `stroke-linejoin="round"`) and, if needed, a soft backing glow drawn *inside* `#word-art` behind the letters.
   Plan a calm area of the composition for the word; nothing in the scene may cover it; keep 30 px clear of the edges
   (`check` measures the ink of the letters: closer than 20 px is a warning, a letter cut by the edge an error).
   Check the phone-size view: the word must still read at a glance.
2. **Show how the word is built** — the chunks from the brief (`dance.chunks`, e.g. `break|fast`, `yes|ter|day`): give
   neighbouring chunks clearly different colours taken from the card's palette (a one-chunk word is one colour, unless
   the hook singles letters out). Silent letters (`dance.silent_letter_indexes`) are "ghost letters": a pale,
   see-through fill with a dashed outline — written but not spoken. Double letters (`dance.double_letter_index_pairs`)
   are twins: treat the pair identically and let it stand out.
3. **Carry one memory hook** that ties the spelling to the meaning *through the picture* — the thing the child will
   recall when spelling the word. In order of preference:
   a. real word-building: `break` + `fast`, `grand` + `ma`, `yester` + `day`;
   b. a sound pattern worth noticing: `ee`, `ai`, `sh`, a silent letter;
   c. a letter that *becomes* part of the picture: the two `o` of `moon` hold two moons, the dot of `i` in `rain` is a
      raindrop. The letter stays a real letter — the picture goes into, onto or around it, drawn as separate shapes.
   The hook must be true to spelling and sound: **no 谐音**, no invented etymology (a playful likeness is presented as
   "像…", never as a fact about the word). If no natural hook exists, colour the chunks, integrate the word beautifully
   and stop — a forced hook is worse than none. The brief's `mnemonic_zh_current` is a starting point, not a constraint;
   improve on it when you can.
4. **Belong to the picture.** Not a caption bar: the word lives in the scene (glowing in the sky, resting on the
   tablecloth, floating on the water, hanging in the steam), lit by the same light, with the same palette.

Also write the hook as ONE short Chinese sentence for the child (`hook_zh`, at most 34 characters counting everything,
e.g. 「两个 o 是两轮圆月：天上一个，水里一个。」) — the app shows it in the 「记忆」 line of the study card. When the
chunks could suggest a wrong sound or meaning (break + fast is said /ˈbrekfəst/, not "brake-fast"; `fast` here is 禁食,
not 快), add `note_zh` (at most 30 characters) that sets it right; otherwise leave it empty. And describe the scene in
one plain Chinese sentence (`alt_zh`, the picture's alternative text: who does what, where, in which light). The three
captions go into the manifest next to the card (`studio/manifest.json`); the import refuses a `hook_zh` or `note_zh`
longer than 60 characters and an `alt_zh` longer than 200.

## 4. Check, look, improve

Work on a card under `studio/tmp/` (ignored by git), e.g. `studio/tmp/batch-01/cards/<word>.svg`; it moves to
`studio/cards/` when it is approved.

    studio/tools/check <dir>/cards/<word>.svg --word <word> [--zoom X,Y,W,H ...]

writes `<dir>/clean/<word>.svg` (what the app would serve), `<dir>/png/<word>.png` (800×500) and
`<dir>/png/<word>.sheet.png` (the scene with the word-art hidden + the phone-size view), and prints a JSON report.
Each `--zoom X,Y,W,H` adds `<dir>/png/<word>.zoom<N>.png`, an enlarged crop of that canvas region — use it on every
face, every hand and the word-art; flaws hide at 800 px. (`--sheet` instead of `--word` renders a non-card SVG such as
the cast sheet; `--no-render` validates without Chrome.) Fix every `error`; weigh every `warning`. Then **open the PNGs with the Read tool and look at them as
the owner would**. Typical faults to hunt for: a stiff or empty composition; muddy or garish colours; a subject that is not
obviously the word's meaning; faces that look odd; limbs that do not connect; the word hard to read on its background
or covered by something; the hook not visible at phone size; the scene looking broken when the word-art is hidden.
Iterate — a first render is never the final card. (If Chrome fails to render — the report says `render failed: …` for
the card, the sheet or a zoom it did not write, and that is an `error`: never go on without the sheet — run the check
once more; if it still fails, say so in your report. On a busy machine Chrome now and then takes the screenshot before the last tiles are
painted: a clean-edged band of background where picture should be (it follows Chrome's 256-px raster tiles) is that —
run the check again before you "repair" the card.)
