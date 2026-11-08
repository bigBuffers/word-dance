// dances — pure keyframe plans for the 「单词之舞」 (docs/WORD_DANCE_DESIGN.md §4.1–4.3; FRONTEND §4 `word/DancingWord`, §6.5).
// No DOM here: `DancingWord` hands each step to `element.animate()`; tests snapshot the plans.
//
// 拼写舞 (spell): the letters enter one by one in reading order, with a longer pause at every syllable boundary, so a long word
// is seen as its chunks (el·e·phant) rather than a string of letters; long words (8 letters or more) enter a little faster.
// 重音舞 (beats): the syllables then beat in turn; the primary-stressed one jumps highest, grows a little and takes the accent
// colour; silent letters (night's gh, the magic e) stay still and keep their muted colour. Doubled letters jump together once
// more at the end (rabbit's bb). 语义舞 (semantic): one motion from the closed library that IS the word's meaning — up rises,
// small shrinks, in walks into a box, cold shivers — played at the reveal, every primitive the same motion for the same meaning
// class (design principle 3). Everything is transform / opacity / color, so it composites; the form plan stays under 2.5 s and a
// semantic plan under 2.5 s.
import type { DanceColor, DancePrimitive, DanceSpec } from '@/api/types';

export type DanceTarget = 'letter' | 'word' | 'ghost' | 'stage';

export interface DanceStep {
  /** What the step animates: a letter span (`index` = letter), the whole word, a ghost copy (`index` = ghost), or the stage object. */
  target: DanceTarget;
  index: number;
  keyframes: Keyframe[];
  options: KeyframeAnimationOptions;
}

export const LETTER_MS = 85;
export const LETTER_MS_LONG = 55;
export const LONG_WORD = 8;
export const SYLLABLE_PAUSE_MS = 150;
export const SYLLABLE_PAUSE_LONG_MS = 120;
export const ENTER_MS = 280;
export const BEAT_MS = 300;
export const BEAT_STRESSED_MS = 330;
export const TWIN_MS = 420;
/** The pause between the stress dance and the semantic dance in a 'full' play. */
export const SEMANTIC_GAP_MS = 160;
const ENTER_EASING = 'cubic-bezier(0.2, 0.8, 0.2, 1)';
const BEAT_EASING = 'cubic-bezier(0.3, 0.7, 0.3, 1)';
const SETTLE = 'cubic-bezier(0.3, 0.6, 0.3, 1)';

/** `letters[i]` → index of the syllable chunk it belongs to (`spec.letters` concatenate to the display form). */
export function syllableIndexes(spec: DanceSpec): number[] {
  const out: number[] = [];
  spec.letters.forEach((chunk, s) => {
    for (let k = 0; k < chunk.length; k++) out.push(s);
  });
  return out;
}

function isLong(spec: DanceSpec): boolean {
  return syllableIndexes(spec).length >= LONG_WORD;
}

const letter = (index: number, keyframes: Keyframe[], options: KeyframeAnimationOptions): DanceStep => ({ target: 'letter', index, keyframes, options });
const word = (keyframes: Keyframe[], options: KeyframeAnimationOptions): DanceStep => ({ target: 'word', index: 0, keyframes, options });

/** Letters enter in order; the entrance of letter i starts at `delay(i)`; silent letters enter like the others. */
export function spellPlan(spec: DanceSpec): DanceStep[] {
  const syl = syllableIndexes(spec);
  const long = isLong(spec);
  const step = long ? LETTER_MS_LONG : LETTER_MS;
  const pause = long ? SYLLABLE_PAUSE_LONG_MS : SYLLABLE_PAUSE_MS;
  const steps: DanceStep[] = [];
  let t = 0;
  syl.forEach((s, i) => {
    if (i > 0 && s !== syl[i - 1]) t += pause;
    steps.push(
      letter(i, [{ opacity: 0, transform: 'translateY(0.35em) scale(0.86)' }, { opacity: 1, transform: 'none' }], {
        duration: ENTER_MS,
        delay: t,
        fill: 'backwards',
        easing: ENTER_EASING,
      }),
    );
    t += step;
  });
  return steps;
}

/** When the spelling dance has finished (the last letter's entrance ends). */
export function spellDuration(spec: DanceSpec): number {
  const plan = spellPlan(spec);
  const last = plan[plan.length - 1];
  return last ? Number(last.options.delay ?? 0) + ENTER_MS : 0;
}

/**
 * Syllables beat in order from `start`; the stressed one (`spec.stress`) jumps highest, scales and takes `accent`.
 * A spec without a stress mark beats evenly. Silent letters are skipped.
 */
export function beatPlan(spec: DanceSpec, accent: string, start = spellDuration(spec)): DanceStep[] {
  const syl = syllableIndexes(spec);
  const silent = new Set(spec.marks.silent);
  const steps: DanceStep[] = [];
  syl.forEach((s, i) => {
    if (silent.has(i)) return;
    const stressed = spec.stress !== null && s === spec.stress;
    steps.push(
      letter(
        i,
        stressed
          ? [{ transform: 'translateY(0)' }, { transform: 'translateY(-0.6em) scale(1.18)', color: accent, offset: 0.45 }, { transform: 'translateY(0)' }]
          : [{ transform: 'translateY(0)' }, { transform: 'translateY(-0.2em)', offset: 0.45 }, { transform: 'translateY(0)' }],
        { duration: stressed ? BEAT_STRESSED_MS : BEAT_MS, delay: start + s * BEAT_MS, easing: BEAT_EASING },
      ),
    );
  });
  return steps;
}

/** When the stress dance has finished. */
export function beatDuration(spec: DanceSpec, start = spellDuration(spec)): number {
  return start + spec.letters.length * BEAT_MS + (BEAT_STRESSED_MS - BEAT_MS);
}

/** Doubled letters jump together once more after the beats (rabbit's bb, happy's pp). */
export function twinPlan(spec: DanceSpec, start = beatDuration(spec)): DanceStep[] {
  return spec.marks.double.flatMap((pair) =>
    pair.map((index) => letter(index, [{ transform: 'none' }, { transform: 'translateY(-0.3em) rotate(-9deg)', offset: 0.5 }, { transform: 'none' }], { duration: TWIN_MS, delay: start, easing: BEAT_EASING })),
  );
}

/** The spelling + stress choreography: spell → beats → twins. */
export function dancePlan(spec: DanceSpec, accent: string): DanceStep[] {
  const spellEnd = spellDuration(spec);
  const beatsEnd = beatDuration(spec, spellEnd);
  return [...spellPlan(spec), ...beatPlan(spec, accent, spellEnd), ...twinPlan(spec, beatsEnd)];
}

/** Total length of the spelling + stress choreography in ms (design principle 2: ≤ 2.5 s for the words a pupil meets). */
export function danceDuration(spec: DanceSpec): number {
  const beatsEnd = beatDuration(spec);
  return spec.marks.double.length > 0 ? beatsEnd + TWIN_MS : beatsEnd;
}

// ---------------------------------------------------------------------------------------------------- 语义舞
/** The stage object a primitive moves against (drawn by DancingWord / word.css), or none. */
export type DanceObject = 'box' | 'roof' | 'table' | 'tree' | 'bars';

export const OBJECT_OF: Partial<Record<DancePrimitive, DanceObject>> = { enter: 'box', exit: 'box', arc: 'roof', under: 'table', behind: 'tree', between: 'bars' };

/** The colour a word wears at rest and in the static fallback: the `--pose-*` tokens of styles/tokens.css, which hold a deep tone
 * on the light theme and a bright one on the dark theme (≥ 3:1 on each `--bg` for the large bold headword); black / white keep
 * the ink (black darkens like `dim`, white glows like `glow` when the word dances). */
const COLOR_OF: Record<DanceColor, string | null> = {
  red: 'var(--pose-red)',
  orange: 'var(--pose-orange)',
  yellow: 'var(--pose-yellow)',
  green: 'var(--pose-green)',
  blue: 'var(--pose-blue)',
  purple: 'var(--pose-purple)',
  pink: 'var(--pose-pink)',
  brown: 'var(--pose-brown)',
  black: null,
  white: null,
  grey: 'var(--pose-grey)',
};
const COLD = 'var(--pose-blue)';
const HOT = 'var(--pose-red)';
const SAD = 'var(--pose-grey)';

/** The static pose of a semantic primitive: a rest colour or nothing (poses never change size or letterforms, principle 5). */
export function poseColor(spec: DanceSpec): string | null {
  const s = spec.semantic;
  if (!s) return null;
  switch (s.primitive) {
    case 'color':
      return s.params.color ? COLOR_OF[s.params.color] : null;
    case 'shiver':
      return COLD;
    case 'shimmer':
      return HOT;
    case 'droop':
      return SAD;
    default:
      return null;
  }
}

/** How many ghost copies a spec needs (`multiply`: n − 1, at most 2). */
export function ghostCount(spec: DanceSpec): number {
  if (spec.semantic?.primitive !== 'multiply') return 0;
  const n = spec.semantic.params.n ?? 3;
  return Math.max(1, Math.min(2, n - 1));
}

const halves = (spec: DanceSpec): { left: number[]; right: number[] } => {
  const n = syllableIndexes(spec).length;
  const mid = Math.floor(n / 2);
  return { left: Array.from({ length: mid }, (_, i) => i), right: Array.from({ length: n - mid }, (_, i) => mid + i) };
};

/** Resolved colours DancingWord reads from the DOM before a play: the heading ink (where a colour pour starts) and the word's
 * computed rest colour (where it ends — the `--pose-*` token resolved for the active theme). */
export interface DanceColors {
  ink?: string;
  pose?: string;
}

/**
 * The semantic dance of `spec` from `start`: one motion per meaning class (§4.3). Word-level motions animate the whole word;
 * letter-level ones stagger the letters; `multiply` fans ghost copies out and back; `between` also fades its bars in; `dim`,
 * `glow` and `color` animate the colour — `color` pours from `colors.ink` (the heading ink, not the pose the word already wears)
 * into `colors.pose`; black plays as `dim`, white as `glow`. Returns [] when the spec has no semantic.
 */
export function semanticPlan(spec: DanceSpec, accent: string, start = 0, colors: DanceColors = {}): DanceStep[] {
  const s = spec.semantic;
  if (!s) return [];
  const n = syllableIndexes(spec).length;
  const each = (fn: (i: number) => Keyframe[], options: (i: number) => KeyframeAnimationOptions): DanceStep[] =>
    Array.from({ length: n }, (_, i) => {
      const o = options(i);
      return letter(i, fn(i), { ...o, delay: start + Number(o.delay ?? 0) });
    });
  const whole = (keyframes: Keyframe[], options: KeyframeAnimationOptions): DanceStep[] => [word(keyframes, { ...options, delay: start + Number(options.delay ?? 0) })];
  const enterEach = (fn: (i: number) => Keyframe[], duration: number, easing = SETTLE, stagger = 40): DanceStep[] => each(fn, (i) => ({ duration, delay: i * stagger, fill: 'backwards', easing }));
  const dim = (): DanceStep[] => whole([{ opacity: 1 }, { opacity: 0.25, offset: 0.35 }, { opacity: 0.25, offset: 0.7 }, { opacity: 1 }], { duration: 1800, easing: 'ease-in-out' });
  const glow = (): DanceStep[] =>
    whole([{ color: 'currentColor', textShadow: '0 0 0 transparent' }, { color: accent, textShadow: `0 0 0.5em ${accent}`, offset: 0.35 }, { color: accent, textShadow: `0 0 0.5em ${accent}`, offset: 0.7 }, { color: 'currentColor', textShadow: '0 0 0 transparent' }], { duration: 1800, easing: 'ease-in-out' });
  switch (s.primitive) {
    case 'rise': // up, high, climb: the word comes up from below into place
      return enterEach(() => [{ transform: 'translateY(1.1em)', opacity: 0 }, { transform: 'translateY(-0.25em)', opacity: 1, offset: 0.7 }, { transform: 'none' }], 720, ENTER_EASING);
    case 'fall': // down, low, drop: it comes down from above and lands with a bounce
      return enterEach(() => [{ transform: 'translateY(-1.4em)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1, offset: 0.6, easing: 'cubic-bezier(0.4, 0, 1, 1)' }, { transform: 'translateY(-0.3em)', offset: 0.78 }, { transform: 'none' }], 820, SETTLE, 30);
    case 'grow': // big, large, grow: it grows into its size
      return whole([{ transform: 'scale(0.35)', opacity: 0.5 }, { transform: 'scale(1.08)', opacity: 1, offset: 0.8 }, { transform: 'none' }], { duration: 1100, easing: SETTLE });
    case 'shrink': // small, little: it shrinks into its size
      return whole([{ transform: 'scale(2.2)', opacity: 0.5 }, { transform: 'scale(0.92)', opacity: 1, offset: 0.8 }, { transform: 'none' }], { duration: 1100, easing: SETTLE });
    case 'dash': // fast, quick, run: it dashes in with a skew
      return enterEach(() => [{ transform: 'translateX(-3.5em) skewX(22deg)', opacity: 0 }, { transform: 'translateX(0.3em) skewX(-8deg)', opacity: 1, offset: 0.62 }, { transform: 'none' }], 480, 'cubic-bezier(0.1, 0.9, 0.2, 1)', 18);
    case 'creep': // slow: it creeps in
      return [
        ...whole([{ transform: 'translateX(-1.6em)' }, { transform: 'none' }], { duration: 2300, easing: 'linear' }),
        ...each(() => [{ transform: 'none' }, { transform: 'translateY(-0.1em)' }, { transform: 'none' }, { transform: 'translateY(-0.1em)' }, { transform: 'none' }], (i) => ({ duration: 2000, delay: i * 40, easing: 'ease-in-out' })),
      ];
    case 'enter': // in, into, inside: it walks into the box
      return whole([{ transform: 'translateX(-3em) translateY(-0.6em)', opacity: 0.9 }, { transform: 'translateX(-1.2em) translateY(-0.6em)', offset: 0.5 }, { transform: 'translateX(0) translateY(0.2em)', offset: 0.82 }, { transform: 'none' }], { duration: 1200, easing: SETTLE });
    case 'exit': // out, outside: it comes out of the box
      return whole([{ transform: 'translateX(-2.6em) scale(0.8)', opacity: 0.7 }, { transform: 'translateX(-2.6em) translateY(-0.7em) scale(0.9)', opacity: 1, offset: 0.35 }, { transform: 'translateX(-0.4em) translateY(-0.4em)', offset: 0.75 }, { transform: 'none' }], { duration: 1200, easing: SETTLE });
    case 'arc': // over, above, across: it flies over the roof
      return whole([{ transform: 'translateX(-4em)', opacity: 0.8 }, { transform: 'translateX(-2em) translateY(-1.6em)', opacity: 1, offset: 0.5 }, { transform: 'none' }], { duration: 1500, easing: 'ease-in-out' });
    case 'under': // under, below: it ducks under the table
      return whole([{ transform: 'translateX(-4em) translateY(-1em)', opacity: 0.8 }, { transform: 'translateX(-2em) translateY(0.15em)', opacity: 1, offset: 0.55 }, { transform: 'none' }], { duration: 1400, easing: 'ease-in-out' });
    case 'behind': // behind: it comes out from behind the tree
      return whole([{ transform: 'translateX(-1.6em) scale(0.9)', opacity: 0 }, { transform: 'translateX(-1.6em) scale(0.9)', opacity: 0, offset: 0.25 }, { transform: 'translateX(-0.5em)', opacity: 1, offset: 0.7 }, { transform: 'none' }], { duration: 1300, easing: SETTLE });
    case 'between': // between, middle: the bars close in on both sides and it settles between them
      return [
        ...whole([{ transform: 'scaleX(1.25)' }, { transform: 'scaleX(0.96)', offset: 0.7 }, { transform: 'none' }], { duration: 1100, easing: SETTLE }),
        { target: 'stage', index: 0, keyframes: [{ opacity: 0, transform: 'scaleX(1.4)' }, { opacity: 1, transform: 'none' }], options: { duration: 700, delay: start, fill: 'backwards', easing: SETTLE } },
      ];
    case 'split': {
      // open, apart: the halves part
      const { left } = halves(spec);
      return each(
        (i) => [{ transform: left.includes(i) ? 'translateX(0.3em)' : 'translateX(-0.3em)' }, { transform: 'none' }],
        () => ({ duration: 900, delay: 250, easing: BEAT_EASING }),
      );
    }
    case 'join': {
      // close, together, meet: the halves come together
      const { left } = halves(spec);
      return each(
        (i) => [{ transform: left.includes(i) ? 'translateX(-1.2em)' : 'translateX(1.2em)', opacity: 0.7 }, { transform: 'none', opacity: 1, offset: 0.75 }, { transform: left.includes(i) ? 'translateX(0.08em)' : 'translateX(-0.08em)', offset: 0.88 }, { transform: 'none' }],
        () => ({ duration: 950, easing: BEAT_EASING }),
      );
    }
    case 'shiver': // cold, afraid: it shivers
      return each(() => [{ transform: 'none' }, { transform: 'translateX(-0.08em) rotate(-3deg)' }, { transform: 'translateX(0.08em) rotate(3deg)' }, { transform: 'none' }], (i) => ({ duration: 110, delay: i * 12, iterations: 9, easing: 'linear' }));
    case 'shimmer': // hot, warm: heat rises through it
      return each(() => [{ transform: 'none' }, { transform: 'translateY(-0.25em) scaleY(1.12) skewX(-4deg)' }, { transform: 'none' }, { transform: 'translateY(-0.15em) skewX(4deg)' }, { transform: 'none' }], (i) => ({ duration: 1300, delay: i * 90, easing: 'ease-in-out' }));
    case 'wave': // happy, fun, excited: a happy wave runs through it
      return each(() => [{ transform: 'none' }, { transform: 'translateY(-0.5em) rotate(-7deg)', offset: 0.4 }, { transform: 'none' }], (i) => ({ duration: 650, delay: i * 70, iterations: 2, easing: 'ease-in-out' }));
    case 'droop': // sad, tired, sorry: it droops and sighs back up
      return each(
        (i) => [{ transform: 'none' }, { transform: `translateY(${0.25 + (i % 3) * 0.08}em) rotate(${i % 2 ? 6 : -6}deg)`, opacity: 0.6, offset: 0.55 }, { transform: `translateY(${0.2 + (i % 3) * 0.08}em)`, opacity: 0.7, offset: 0.8 }, { transform: 'none', opacity: 1 }],
        (i) => ({ duration: 1800, delay: i * 60, easing: 'ease-in-out' }),
      );
    case 'stretch': // tall, long: it stretches up
      return whole([{ transform: 'scaleY(0.5)' }, { transform: 'scaleY(1.3)', offset: 0.72 }, { transform: 'none' }], { duration: 1000, easing: SETTLE });
    case 'squash': // short, flat, low: it squashes down
      return whole([{ transform: 'scaleY(1.4)' }, { transform: 'scaleY(0.7)', offset: 0.7 }, { transform: 'none' }], { duration: 1000, easing: SETTLE });
    case 'thud': // heavy, strong: it drops with a thud
      return whole([{ transform: 'translateY(-2em)' }, { transform: 'translateY(0) scaleY(0.72) scaleX(1.18)', offset: 0.6, easing: 'cubic-bezier(0.5, 0, 1, 1)' }, { transform: 'translateY(0) scaleY(1.06)', offset: 0.8 }, { transform: 'none' }], { duration: 780 });
    case 'float': // light, fly, balloon: it floats up and settles
      return whole([{ transform: 'translateY(0.8em)', opacity: 0.6 }, { transform: 'translateY(-0.5em) rotate(-3deg)', opacity: 1, offset: 0.55 }, { transform: 'translateY(0.1em) rotate(2deg)', offset: 0.8 }, { transform: 'none' }], { duration: 1600, easing: 'ease-in-out' });
    case 'spin': // turn, round, around: it turns once
      return whole([{ transform: 'rotate(0)' }, { transform: 'rotate(360deg)' }], { duration: 950, easing: 'cubic-bezier(0.45, 0.05, 0.3, 1)' });
    case 'repeat': // again, always, often: it enters twice
      return whole([{ opacity: 0, transform: 'translateX(-0.8em)' }, { opacity: 1, transform: 'none', offset: 0.3 }, { opacity: 1, transform: 'none', offset: 0.48 }, { opacity: 0, transform: 'translateX(-0.8em)', offset: 0.54 }, { opacity: 1, transform: 'none', offset: 0.86 }, { opacity: 1, transform: 'none' }], { duration: 1700, easing: 'ease-out' });
    case 'multiply': {
      // two, three, many: copies fan out and come back
      const ghosts = ghostCount(spec);
      return Array.from({ length: ghosts }, (_, g) => ({
        target: 'ghost' as const,
        index: g,
        keyframes: [{ transform: 'none', opacity: 0 }, { transform: `translateX(${g === 0 ? '-105%' : '105%'})`, opacity: 1, offset: 0.35 }, { transform: `translateX(${g === 0 ? '-105%' : '105%'})`, opacity: 1, offset: 0.72 }, { transform: 'none', opacity: 0 }],
        options: { duration: 1600, delay: start, easing: 'ease-in-out' },
      }));
    }
    case 'dim': // night, dark: it dims and comes back
      return dim();
    case 'glow': // light, bright, sun: it glows
      return glow();
    case 'color': {
      // red, yellow …: the colour pours in letter by letter from the heading ink into the rest colour the word already wears
      // (the pose is applied statically, so the pour must start from the ink, not from `currentColor`); black darkens, white glows
      if (s.params.color === 'black') return dim();
      if (s.params.color === 'white') return glow();
      const c = colors.pose ?? poseColor(spec);
      if (!c) return [];
      const from = colors.ink ?? 'currentColor';
      // fill backwards: every letter holds the ink until its turn, so the colour visibly arrives letter by letter
      return each(() => [{ color: from, transform: 'none' }, { color: c, transform: 'translateY(-0.15em)', offset: 0.5 }, { color: c, transform: 'none' }], (i) => ({ duration: 500, delay: i * 50, fill: 'backwards', easing: 'ease-out' }));
    }
    default:
      return [];
  }
}

/** Length of the semantic dance in ms (0 without a semantic). */
export function semanticDuration(spec: DanceSpec, accent = 'currentColor'): number {
  return Math.max(0, ...semanticPlan(spec, accent).map((s) => Number(s.options.delay ?? 0) + Number(s.options.duration ?? 0) * Number(s.options.iterations ?? 1)));
}

export type DancePlayKind = 'form' | 'semantic' | 'full';

/** What one play of DancingWord performs: 'form' = dancePlan, 'semantic' = semanticPlan, 'full' = the form dance now and the
 * semantic dance as a second play `danceDuration + SEMANTIC_GAP_MS` later (DancingWord.play sequences the two halves itself — a
 * single delayed plan would let the `fill: 'backwards'` entrances hide the letters during the form dance). */
