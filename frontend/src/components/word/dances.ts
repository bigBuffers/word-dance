// dances — pure keyframe plans for the 「单词之舞」 P1 dances (docs/WORD_DANCE_DESIGN.md §4.1–4.2; FRONTEND §4 `word/DancingWord`,
// §6.5). No DOM here: `DancingWord` hands each step to `element.animate()`; tests snapshot the plans.
//
// 拼写舞 (spell): the letters enter one by one in reading order, with a longer pause at every syllable boundary, so a long word
// is seen as its chunks (el·e·phant) rather than a string of letters; long words (8 letters or more) enter a little faster. 重音舞 (beats): the syllables then beat in turn; the
// primary-stressed one jumps highest, grows a little and takes the accent colour; silent letters (night's gh, the magic e) stay
// still and keep their muted colour. Doubled letters jump together once more at the end (rabbit's bb). Everything is
// transform / opacity / color, so it composites; the whole plan stays under ~2.5 s even for the longest 小学 words.
import type { DanceSpec } from '@/api/types';

export interface DanceStep {
  /** Index of the letter span the step animates. */
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
const ENTER_EASING = 'cubic-bezier(0.2, 0.8, 0.2, 1)';
const BEAT_EASING = 'cubic-bezier(0.3, 0.7, 0.3, 1)';

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
    steps.push({
      index: i,
      keyframes: [
        { opacity: 0, transform: 'translateY(0.35em) scale(0.86)' },
        { opacity: 1, transform: 'none' },
      ],
      options: { duration: ENTER_MS, delay: t, fill: 'backwards', easing: ENTER_EASING },
    });
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
    steps.push({
      index: i,
      keyframes: stressed
        ? [{ transform: 'translateY(0)' }, { transform: 'translateY(-0.6em) scale(1.18)', color: accent, offset: 0.45 }, { transform: 'translateY(0)' }]
        : [{ transform: 'translateY(0)' }, { transform: 'translateY(-0.2em)', offset: 0.45 }, { transform: 'translateY(0)' }],
      options: { duration: stressed ? BEAT_STRESSED_MS : BEAT_MS, delay: start + s * BEAT_MS, easing: BEAT_EASING },
    });
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
    pair.map((index) => ({
      index,
      keyframes: [{ transform: 'none' }, { transform: 'translateY(-0.3em) rotate(-9deg)', offset: 0.5 }, { transform: 'none' }],
      options: { duration: TWIN_MS, delay: start, easing: BEAT_EASING },
    })),
  );
}

/** The complete P1 choreography: spell → beats → twins. */
export function dancePlan(spec: DanceSpec, accent: string): DanceStep[] {
  const spellEnd = spellDuration(spec);
  const beatsEnd = beatDuration(spec, spellEnd);
  return [...spellPlan(spec), ...beatPlan(spec, accent, spellEnd), ...twinPlan(spec, beatsEnd)];
}

/** Total length of the choreography in ms (design principle 2: ≤ 2.5 s for the words a pupil meets). */
export function danceDuration(spec: DanceSpec): number {
  const beatsEnd = beatDuration(spec);
  return spec.marks.double.length > 0 ? beatsEnd + TWIN_MS : beatsEnd;
}
