# House style「晨光动画」— the jury's decision

Three illustrators drew the pilot word *breakfast* in three styles; three judges (a child + parent, an art director, an
English teacher) compared the renders:

    pilot B   光影动画  — WINNER for the scene: light, depth, figure drawing, appetising detail
    pilot C   叠层剪纸  — WINNER for the lettering: biggest, boldest, reads at phone size; family warmth
    pilot A   晨光水彩  — WINNER for the hook staging: the child ACTS OUT the hook inside the scene; bright airy key

**The house style = B's light and drawing, at A's bright key, with C's lettering and A's enacted hook.**
The ten cards the owner approved are that style, finished — look at them before you draw, they are your references:
`studio/cards/*.svg` (`studio/tools/check studio/cards/breakfast.svg --word breakfast` renders one into `studio/png/`).
The three pilot cards themselves, with their renders and build scripts, are not in the repository (they are in the
archive named in `studio/README.md`). The technical recipe (palette logic, light recipe in drawing order, depth order,
gradient / blur snippets, rim light, mistakes already made) is `studio/pilots/B/STYLE.md` — read it and reuse its
snippets. The rules below correct the faults the jury found in B and are binding.

## 1. Light — the protagonist, at a bright key

- ONE light source, visible or clearly implied, ONE direction for the whole card; warm light against cool (never grey,
  never black) shadow; rim light on the sun side of hair, shoulders, objects; steam, dust, petals or spray catching the light.
- Pick one of the five house light setups (so 600 cards stay one family):
  1. **晨光窗** — low morning sun through a window, indoors (breakfast, sleep-in, classroom);
  2. **金色户外** — golden late-afternoon sun outdoors (park, 小区, autumn leaves, playground);
  3. **雨天柔光** — overcast or rain: soft pearl light, wet reflections, one warm accent (a yellow raincoat, a lit window);
  4. **晴空亮水** — high bright sun: sparkling water, white clouds, crisp short shadows (pool, beach, summer);
  5. **月夜灯光** — moon or lamp: a *luminous* night — blue-violet sky `#3B4C9A → #8FA3E0`, glowing moon, warm window or
     night-light; things stay readable, faces stay lit.
- **Value floor.** Day cards are bright: no wall, sky or table area darker than a mid-tone; no dark vignette (at most a
  10 % warm one); no plum or maroon bands along the bottom. B's right half read as dusk — do not repeat it. Night cards
  are deep blue, never near-black, and at least a third of the picture is lit.
- Light shapes stay separate and readable: a curtain, a light shaft and a column of steam must not merge into one white pillar.
- The subject that carries the meaning sits INSIDE the light — it is the brightest, sharpest, most saturated place.

## 2. Composition

- Three depth planes: a soft far plane (blurred once, as a group), a crisp middle plane with the action, and — optional —
  ONE soft foreground element. A foreground element must be instantly recognisable (a leafy branch, a curtain edge, a
  flower), light or mid-toned, and nowhere near the word. No dark blurred blobs, ever.
- One moment, one focal point, a clear path for the eye: light → subject → hook → word. Characters interact with each
  other or with the object — nobody poses to the camera in a row (C's fault).
- At most about six distinct props. Every prop is identifiable at phone size and belongs to a Chinese child's life
  (a small bowl, not a Western egg cup).
- Plan the **calm zone** for the word before anything else: a quiet surface or stretch of sky / water / floor, about a
  third of the canvas, with only soft light and shadow in it. Nothing cropped pokes into it from the edges.
- Figures: use the cast sheet (`studio/cast/CAST.md`). Faces as in pilot B (glossy eyes with highlights, open smile, blush);
  hands are mitten shapes with finger arcs, never balls; arms bend at an elbow; hair has form shading and a rim on the
  light side only — never a full outline that reads as a sticker; a figure is big enough to act (head radius ≥ 40 px).

## 3. The word — C's lettering

- As big as the calm zone allows: 3–5 letters 140–180 px em, 6–7 letters 115–140, 8–9 letters 96–115. Total width ≤ 720.
  Flat baseline, upright, `--track` 2–6.
- On a LIGHT zone: solid, saturated, darker-than-the-zone fills with a cream keyline (`stroke="#FFF8E7"`, width 6–8,
  `paint-order="stroke"`, `stroke-linejoin="round"`) and one soft `feDropShadow` under the whole word. On a DARK or
  mid-tone zone (night sky, deep water): luminous pale fills with a deep keyline of the same hue and a soft glow. A
  gentle top-to-bottom gradient inside the fill (same hue, ≤ 20 % lighter at the top) is welcome — the letters are lit
  by the scene's light. The word must be the highest-contrast text-like thing on the card.
- Chunk colours: the stressed chunk (`dance.stress_chunk_index`) takes the WARM colour (coral `#E8503A`, sunrise orange,
  gold on dark), its neighbour the COOL one (indigo `#2F3E9E`, teal, moon-blue on dark), a third chunk a green or
  plum that suits the card. Colours may carry meaning (sunrise *break*, night *fast*). A one-chunk word is one colour.
- Chunk gap: 8–16 px — colour does the separating. The word must read as ONE word. Only when a hook object truly has
  to stand in the seam may the gap grow, to at most one letter width — and then see §4.
- Ghost letters (silent): fill at 30–40 % opacity in the chunk colour + a dashed keyline (`stroke-dasharray="7 6"`) in
  the full chunk colour, so the letter is clearly *there* but "quiet". Twins (double letters): identical treatment and a
  tiny linking detail (a shared accent colour, a bridge, matching ornaments).
- Decorations stay OUTSIDE the letter strokes (inside a counter is fine: a moon inside an `o`). No generic sparkles or
  glitter on the word — every mark near the letters means something.
- The word rests on / floats in the scene: contact shadow on a table or path, reflection on water, glow in a sky.

## 4. The hook — A's staging

- The hook is **acted out in `#scene`** by a cast member or by the scene itself, and it survives when the word-art is
  hidden. The word-art then *points at it*: colours, a letter that holds or touches the object, an alignment.
- A hook object placed in or next to the word line never looks like a letter: no letter-style keyline, not the height of
  the x-height sitting on the baseline, not in a chunk colour. It is grounded (stands on something, casts a shadow).
- One hook per card. If it needs the caption to be understood, simplify it. It must be visible at phone size
  (the object ≥ 60 px on the 800 canvas).
- True to sound and meaning. Where the spelling chunks do not match the pronunciation or the everyday meaning of a
  part, say so in `note_zh` (`studio/STUDIO.md` §3).

## 5. Finish

- Budget 28–45 KB. Reuse gradients; share blur groups (3–4 filters, ≤ 10 filtered groups); one decimal.
- Zoom in on every face, hand and the word (`studio/tools/check … --zoom X,Y,W,H`) before you call a card finished.
- Known traps (from the pilots): a face on a yolk reads as a chick; dust motes on a face read as dandruff; a steam line
  across a face reads as a hair, a thin steam line reaching a shelf reads as a wire; bokeh rings read as soap bubbles;
  a low-opacity stroke as "glow" turns grey — use a radial-gradient ellipse; square fringe corners make the face a box;
  petals indoors need a source; a detached tail or limb behind a table edge looks broken; a spot on a bun reads as an eye.
