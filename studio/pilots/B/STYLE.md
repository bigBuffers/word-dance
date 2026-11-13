# Style B「光影动画」— recipe (pilot: breakfast)

One frame of a hand-painted animated film: a **low sun behind the scene** (backlight), warm light against cool shadow, rim-lit
figures, light shafts with dust, steam that glows, a soft far layer / crisp middle / big blurred foreground shapes.
This file is the technical recipe `studio/STYLE.md` builds on. The pilot card itself (its build script, the SVG, the renders) is not in
the repository — it is in the archive named in `studio/README.md`; every snippet a card needs is quoted below, and the approved
`studio/cards/breakfast.svg` is the same word drawn in the final house style (where the two differ, `studio/STYLE.md` wins).

## 1. Palette logic
- **Light = warm** `#FFFFFF → #FFF4C4 → #FFD88F → #FFB573` (sun core, bloom, shafts, every rim and highlight).
- **Shadow = cool**: wall `#9CC2BC → #7399BA → #5565A6` (left → right, away from the window), ceiling veil `#2C2A66`, cast shadows on
  warm surfaces are plum `#3A1B44` (never grey, never black), vignette `#241244`.
- **Dominant family** amber / honey / terracotta (table `#F8C077 → #DC8F55 → #A35B46 → #6E3B4E`, food, 朵朵's yellow top);
  **counter** periwinkle-teal (wall, porcelain shade `#B9BEE2`, foreground foliage `#17414A`); **accent** one red (`#E8382E`: hair clip,
  clock pin, dates in the congee) + backlit lime leaves `#CFE064`.
- Whites are never `#FFF` flat: lit side white, turning lavender (`porc`, `shell`) or cream (`bun`) in shade.

## 2. The light recipe (in drawing order)
1. Pick ONE source and ONE 2-D direction for the whole card (here: sun at (130,92) in the window, travelling down-right, slope ≈ 0.55).
2. Window glass = vertical sky gradient; far view inside a `clip-path`, blurred once; then the sun: hot white core + star streaks.
3. Draw frame, sill, curtains normally (cool violet frame `#6E76AC`, cream edges where the light grazes), then **wash the bloom over them**:
   one full-canvas rect with a radial gradient centred on the sun. Everything drawn *after* the bloom stays crisp (cast, table, food).
4. Every mid-layer object gets a **rim on its sun side** (open stroke or tapered crescent, `#FFE2A0`–`#FFF7C8`) and a plum cast shadow
   that runs **down-right** on the table (one blurred group). Glass throws a bright caustic inside its shadow.
5. Steam: blurred cream volume (`b7`) + crisp white curl lines on top (2–2.5 px, opacity .7–.8) — the crisp line is what makes it "animated".
6. Shafts last (over the cast, under the foreground): 3–4 quads leaving the panes, slightly diverging, one shared gradient that starts
   at opacity 0 inside the window, peaks just outside it and dies away; blurred `b3`. Dust motes = 1–2.4 px cream dots placed only inside
   the shafts (seeded random, skipped over faces / bodies). 5–6 soft bokeh discs. 2–3 four-point glints on glass / porcelain / bamboo rim.
7. Foreground framing (dark teal foliage, a cup) in one `b5` group with warm rim strokes, then the vignette, then a few bokeh discs on top.
```xml
<radialGradient id="sun" gradientUnits="userSpaceOnUse" cx="130" cy="92" r="130"><stop offset="0" stop-color="#FFFFFF"/><stop offset=".1" stop-color="#FFFFFF"/><stop offset=".2" stop-color="#FFF4B8"/><stop offset=".5" stop-color="#FFD67A" stop-opacity=".5"/><stop offset="1" stop-color="#FFC56B" stop-opacity="0"/></radialGradient>
<path d="M130,36V148M72,92H188M90,52L170,132M170,52L90,132" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round" opacity=".4"/>
<radialGradient id="bloom" gradientUnits="userSpaceOnUse" cx="130" cy="92" r="540"><stop offset="0" stop-color="#FFF3C4" stop-opacity=".7"/><stop offset=".3" stop-color="#FFD88F" stop-opacity=".4"/><stop offset=".6" stop-color="#FFB573" stop-opacity=".2"/><stop offset="1" stop-color="#FF9E6A" stop-opacity="0"/></radialGradient>
<linearGradient id="shaft" gradientUnits="userSpaceOnUse" x1="230" y1="60" x2="780" y2="405"><stop offset="0" stop-color="#FFF4C4" stop-opacity="0"/><stop offset=".2" stop-color="#FFF4C4" stop-opacity=".6"/><stop offset=".6" stop-color="#FFE6A6" stop-opacity=".2"/><stop offset="1" stop-color="#FFD890" stop-opacity="0"/></linearGradient>
<g filter="url(#b3)" fill="url(#shaft)"><path d="M262,36L800,197.4V263.7L262,70Z" opacity=".6"/><path d="M262,80L800,359.8V448L262,136Z"/><path d="M250,170L800,456V500H688L250,246Z"/><path d="M100,176L723,500H524L100,254Z"/></g>
<path d="M480,280Q480,287,487,287Q480,287,480,294Q480,287,473,287Q480,287,480,280Z" fill="#FFFFFF"/>   <!-- glint: 4 Q-curves through the centre -->
```

## 3. Depth (bottom → top)
far: wall gradient + ceiling veil → window (sky, **blurred** buildings / tree crowns, sun) → frame, sill, backlit plant, curtains → BLOOM →
middle (crisp): shelf, clock (7:00, ticks only), cat + 朵朵's torso and head *behind* the table → table plane (plank seams fan out from a
vanishing point, glancing-light strip on the back edge, window-pane light patch + cast shadows in one blurred group) → food → 朵朵's arms,
hands, bun (they rest ON the table, so they come after it) → steam → shafts, motes, bokeh, glints →
near: blurred dark-teal leaves (bottom-left, top-right) + a blurred cup (bottom-right), vignette, foliage bokeh → `#word-art`.
The lower third of the table is the **calm zone** for the word: only soft light / shadow shapes there, every object base stays above y = 366.

## 4. Gradient / blur recipes
- Only **3 filters, 6 filtered groups** on the whole card: `b3` (far view; shafts), `b5` (table shadows + light patch; foreground; letter
  shadows), `b7` (steam). Group everything that shares a blur.
- All other softness is a **radial fade without a filter** — one gradient, reused on any circle / ellipse (object bounding box):
```xml
<radialGradient id="gw"><stop offset="0" stop-color="#FFF8DE"/><stop offset="1" stop-color="#FFF8DE" stop-opacity="0"/></radialGradient>  <!-- also gy #FFC25A (warm halo), gb #8FA6FF (cool halo) -->
<ellipse cx="560" cy="334" rx="260" ry="11" fill="url(#gw)" opacity=".4"/>   <!-- sheen on the table; same trick for bokeh, wall glow, halo behind hair, letter halos -->
<radialGradient id="vig" gradientUnits="userSpaceOnUse" cx="400" cy="235" r="560"><stop offset=".5" stop-color="#241244" stop-opacity="0"/><stop offset="1" stop-color="#241244" stop-opacity=".5"/></radialGradient>
```
- Form gradients run **along the light** (objectBoundingBox, left lit → right shade): `skin #FFE6C8→#FBD0AC→#EDAD8A`, `top #FFDF62→#FBBC38→#E39232`,
  `bam #FFE29A→#E6AC5E→#A9683C`, `porc #FFFFFF→#E9EBFA→#B9BEE2`; round things use an off-centre radial (`bun`: cx .4 cy .3 r .8, `#FFFFFF→#FFF2DA→#E3BE95`).
- Rim light = a **tapered crescent** (outer edge = the silhouette, inner edge 3–4 px inside, meeting at both ends) + a 1.5 px `#FFF8DC` core;
  small objects: an open stroke along the sun-side arc only. A uniform outline stroke all round reads as a sticker — don't.

## 5. The cast
**朵朵** — head in its own group (origin = head centre, radius ≈ 56; tilt −5°; the pilot scales the whole figure 1.1). Order: bloom ellipse,
back hair, face, cheek rim, blush, eyes (+2 highlights each), brows, mouth, fringe with side locks (rounded corners so the face opening
is an oval, three small notches), sheen, warm translucence, rim crescent, red clip.
```xml
<g transform="translate(600 196) rotate(-5)">
<ellipse cx="-34" cy="-30" rx="58" ry="62" fill="url(#gw)" opacity=".3"/>
<path d="M-56,6C-60,-40,-34,-64,0,-64C34,-64,60,-40,56,6C58,24,58,40,52,52C44,58,34,56,30,50L-30,50C-34,56,-44,58,-52,52C-58,40,-58,24,-56,6Z" fill="url(#hair)"/>
<path d="M-44,6C-44,-26,-24,-42,0,-42C24,-42,44,-26,44,6C44,32,26,50,0,50C-26,50,-44,32,-44,6Z" fill="url(#skin)"/>
<path d="M-42,8C-42,24,-34,38,-22,45" fill="none" stroke="#FFF6DA" stroke-width="3" stroke-linecap="round" opacity=".9"/><ellipse cx="-27" cy="27" rx="9" ry="5.5" fill="#FF7A66" opacity=".5"/><ellipse cx="27" cy="27" rx="9" ry="5.5" fill="#FF7A66" opacity=".4"/>
<ellipse cx="-17" cy="12" rx="5.2" ry="6.8" fill="#3A2018"/><ellipse cx="17" cy="12" rx="5.2" ry="6.8" fill="#3A2018"/><circle cx="-18.8" cy="9.4" r="2.1" fill="#FFF"/><circle cx="15.2" cy="9.4" r="2.1" fill="#FFF"/><circle cx="-15.4" cy="14.6" r="1" fill="#FFF" opacity=".8"/><circle cx="18.6" cy="14.6" r="1" fill="#FFF" opacity=".8"/>
<path d="M-24,-1Q-17,-4,-11,-1M11,-1Q17,-4,24,-1" fill="none" stroke="#5A3626" stroke-width="1.8" stroke-linecap="round" opacity=".7"/><path d="M-8,28Q0,41,8,28Q0,31,-8,28Z" fill="#C2473F" stroke="#C2473F" stroke-width="1.5" stroke-linejoin="round"/>
<path d="M-50,10C-54,-30,-32,-60,0,-60C32,-60,54,-30,50,10C50,24,50,34,46,43C41,41,38,36,39,29C41,20,42,10,40,1Q38,-8,30,-8.5L27,-14L18,-8L6,-8L2,-13L-4,-8L-20,-8L-24,-13L-30,-8.5Q-38,-8,-40,1C-42,10,-41,20,-39,29C-38,36,-41,41,-46,43C-50,34,-50,24,-50,10Z" fill="url(#hair)"/>
<path d="M-38,-26Q-28,-40,-8,-45" fill="none" stroke="#D49A62" stroke-width="3.6" stroke-linecap="round" opacity=".5"/><ellipse cx="-36" cy="-36" rx="28" ry="32" fill="url(#gy)" opacity=".5"/>
<path d="M-53,50C-58,40,-58,24,-56,6C-60,-40,-34,-64,0,-64C16,-64,30,-58,40,-48C28,-56.5,14,-60,0,-60C-30,-60,-55,-38,-52,6C-54,24,-54,38,-51.6,49Z" fill="#FFE2A0"/><path d="M-56,6C-60,-40,-34,-64,0,-64" fill="none" stroke="#FFF8DC" stroke-width="1.5" stroke-linecap="round"/>
<g transform="translate(31 -17) rotate(18)"><rect x="-9" y="-3.6" width="18" height="7.2" rx="3.6" fill="#E8382E"/><rect x="-6" y="-2.3" width="8" height="1.8" rx=".9" fill="#FFB4A4"/></g>
</g>
```
`hair` = `#7A4A34 → #4E2F26 → #36202A` (top-left → bottom-right). Mirror the rim / bloom when the light comes from the right.
Body (canvas coords, head centre (600,196), table edge y = 322): neck, torso ≈ 0.8 head-width, collar arc, shoulder crescent; arms are
22 px round-joined strokes shoulder → elbow → wrist (lit arm lighter), a cuff stroke, mitten hands = tilted ellipses with two finger arcs.
```xml
<rect x="592.5" y="238" width="15" height="26" fill="#E7A27F"/><path d="M555,326C554,296,560,272,580,262Q600,256,620,262C640,272,646,296,645,326Z" fill="url(#top)"/><ellipse cx="600" cy="259" rx="15" ry="7.5" fill="#EDAD8A"/><path d="M584.5,258.5Q600,272,615.5,258.5" fill="none" stroke="#FFF4C4" stroke-width="3.2" stroke-linecap="round"/>
<path d="M555.2,322C554.2,296,560.4,272.4,580,262.2C565,272,560.4,296,560.4,322Z" fill="#FFF7C8"/><path d="M637,281L653,316L623,289" fill="none" stroke="#EFA43A" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/><path d="M563,281L547,316L577,289" fill="none" stroke="#FFD750" stroke-width="22" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M553.4,276.6L537.4,312" stroke="#FFF7C8" stroke-width="3" stroke-linecap="round"/><path d="M563.5,286L578,301" stroke="#FFF6CC" stroke-width="5.5" stroke-linecap="round"/><ellipse cx="573.5" cy="285" rx="10.5" ry="13" transform="rotate(-15 573.5 285)" fill="#FBCFAA" stroke="#DE9E80" stroke-width="1"/><path d="M570,280q6,-1,9,3M569,286q6,-1,10,3" fill="none" stroke="#DE9E80" stroke-width="1.3" stroke-linecap="round"/>
```
**团子** — peeks over the table edge (table drawn after hides the chin), paws on the edge, tail tip behind. `cat` = radial `#FFBE6A → #E5823A`.
```xml
<path d="M720,292L722,258L746,276Z" fill="#F4A450"/><path d="M780,292L778,258L754,276Z" fill="#E88C3A"/><path d="M725,283L726,267L738,277Z" fill="#FFC4B0"/><path d="M775,283L774,267L762,277Z" fill="#F4AE9A"/><path d="M716,306C714,284,728,272,750,272C772,272,786,284,784,306C784,324,770,336,750,336C730,336,716,324,716,306Z" fill="url(#cat)"/>
<path d="M724,308C726,296,740,294,750,302C760,294,774,296,776,308C778,324,766,336,750,336C734,336,722,324,724,308Z" fill="#FFF8EE"/><path d="M746,304L750,277L754,304Z" fill="#FFF8EE"/><path d="M737,277L739,285M763,277L761,285M730,283L733,289M770,283L767,289" stroke="#CF722A" stroke-width="2.2" stroke-linecap="round"/>
<ellipse cx="736.5" cy="301" rx="4.6" ry="6" fill="#3A2018"/><ellipse cx="759.5" cy="301" rx="4.6" ry="6" fill="#3A2018"/><circle cx="735" cy="298.8" r="1.7" fill="#FFF"/><circle cx="758" cy="298.8" r="1.7" fill="#FFF"/><path d="M747.5,310H752.5L750,313.5Z" fill="#F08A8A"/><path d="M750,313.5V316M750,316Q746.5,320,743.5,317M750,316Q753.5,320,756.5,317" fill="none" stroke="#8A4A3A" stroke-width="1.3" stroke-linecap="round"/>
<path d="M717,316C713,300,716,290,720,287L722,258L734,267" fill="none" stroke="#FFE7A8" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>   <!-- rim, sun side only --><ellipse cx="730" cy="322" rx="11" ry="7" fill="#FFF8EE"/><ellipse cx="770" cy="322" rx="11" ry="7" fill="#F4EADF"/>   <!-- paws, after the table -->
```

## 6. Word-art
- `studio/tools/letters breakfast --chunks "break|fast" --size 104 --gap 84 --x 400 --baseline 458`; the word **stands on the table** in the calm
  zone. Each chunk is one `<g>` carrying the paint (letters inherit it) and a ∓2.5° tilt about its centre (the halves tip apart at the seam):
```xml
<linearGradient id="lb" gradientUnits="userSpaceOnUse" x1="0" y1="376" x2="0" y2="460"><stop offset="0" stop-color="#FFFBD0"/><stop offset=".5" stop-color="#FFD750"/><stop offset="1" stop-color="#FF9A2E"/></linearGradient>
<linearGradient id="lf" gradientUnits="userSpaceOnUse" x1="0" y1="376" x2="0" y2="460"><stop offset="0" stop-color="#F6F8FF"/><stop offset=".5" stop-color="#BCCBFF"/><stop offset="1" stop-color="#7A8EF2"/></linearGradient>
<g transform="rotate(-2.5 259.9 418.1)" fill="url(#lb)" stroke="#6B2A0C" stroke-width="7" stroke-linejoin="round" paint-order="stroke"> …wa-0-b … wa-4-k… </g>
<g transform="rotate(2.5 586.2 417.5)" fill="url(#lf)" stroke="#262C73" stroke-width="7" stroke-linejoin="round" paint-order="stroke"> …wa-5-f … wa-8-t… </g>
```
- Fill = luminous vertical gradient (pale top → saturated base) in the chunk's pole colour; outline = the darkest tone of the same hue
  (never black); the gradient is `userSpaceOnUse` over ascender-top → baseline so every letter of a chunk shares it.
- Under the letters, inside `#word-art`: (a) cast shadows — one parallelogram per letter from its foot, offset (+29, +16) like every table
  shadow, in a `b5` group, plum, opacity .5, same tilt as the chunk; (b) a `gy` / `gb` halo ellipse per chunk, opacity .5 (no filter).
- Chunk colour rule: stressed / "day" / active chunk = warm light gradient; the other = cool shadow gradient; a third chunk would take the
  accent family (coral `#FFE1D6 → #FF8E7A`, outline `#7A1F2A`). Decorations (four-point sparkles, moon) sit in the free space above the
  x-height between ascenders, inside the tilted group with `stroke="none"`, never touching a letter.
- Hook objects are separate shapes drawn **before** the letters (letters stay whole): here a cracked egg in the seam, its yolk rising as
  the morning sun (cap popped towards "break", ray strokes, 2.6 px plum outline `#4A2A52`), and a crescent moon + stars on "fast"
  (the night's fast). hook_zh: 「break 敲开蛋壳，打破一夜没吃的 fast，早餐来了！」

## 7. Mistakes made and fixed
1. A smiling face on the yolk-sun inside an eggshell read as **a hatching chick** → no face, glossy yolk + rays.
2. Sun "glare" drawn as long thin triangles looked like scratches; shafts that started above the window looked pasted on → short star
   streaks at the sun only; shafts start inside the panes with a gradient that begins at opacity 0.
3. A warm low-opacity **stroke** around the hair as "glow" turned grey over the blue wall → a `gw` radial ellipse behind the head instead.
4. Rim light as a uniform 4 px stroke looked like a hairband → tapered crescent + thin hot core.
5. Dust motes landed on the face and sleeves (dandruff / buttons) and a steam curl past the cheek looked like a stray hair → exclusion
   zones for head, body and cat; steam only against a cool, empty background, never across a face.
6. Arms the same yellow as a too-wide torso merged into a mound → narrower torso, lit / shade arm colours, inner shade line, cuffs.
7. Bokeh with stroked rings looked like soap bubbles → filled radial discs only. A straight fringe with square corners made the face
   a box → rounded corners where the fringe meets the side locks.
8. Word gap of 92 px split the word in two → 84 px, the egg tucked tightly between `k` and `f` (letters drawn on top stay intact).
9. Two-decimal opacities crept in → a final half-up pass to one decimal (re-check the render: `scale(1.12)` became `1.1`).
