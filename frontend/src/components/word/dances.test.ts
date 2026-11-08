// dances.ts — the pure keyframe plans of the 单词之舞 P1 (FRONTEND §6.5): letters enter in order with a pause at every syllable
// boundary, syllables beat in turn with the stressed one highest and coloured, silent letters never beat, doubled letters jump
// together at the end, and the whole choreography of the longest 小学 words stays under 2.5 s.
import { describe, expect, it } from 'vitest';
import type { DanceSpec } from '@/api/types';
import { BEAT_MS, BEAT_STRESSED_MS, ENTER_MS, LETTER_MS, LETTER_MS_LONG, SYLLABLE_PAUSE_MS, TWIN_MS, beatDuration, beatPlan, danceDuration, dancePlan, spellDuration, spellPlan, syllableIndexes, twinPlan } from './dances';

const rabbit: DanceSpec = { version: 1, letters: ['rab', 'bit'], stress: 0, marks: { double: [[2, 3]], silent: [] }, source: 'rule' };
const night: DanceSpec = { version: 1, letters: ['night'], stress: 0, marks: { double: [], silent: [2, 3] }, source: 'rule' };
const banana: DanceSpec = { version: 1, letters: ['ba', 'na', 'na'], stress: 1, marks: { double: [], silent: [] }, source: 'rule' };
const supermarket: DanceSpec = { version: 1, letters: ['su', 'per', 'mar', 'ket'], stress: 0, marks: { double: [], silent: [] }, source: 'rule' };
const uncle: DanceSpec = { version: 1, letters: ['un', 'cle'], stress: null, marks: { double: [], silent: [] }, source: 'rule' };
// the longest 小学 choreographies (8 letters, 3–4 syllables, doubled letters) — the real worst cases, not hand-picked easy ones
const tomorrow: DanceSpec = { version: 1, letters: ['to', 'mor', 'row'], stress: 1, marks: { double: [[4, 5]], silent: [] }, source: 'rule' };
const umbrella: DanceSpec = { version: 1, letters: ['um', 'brel', 'la'], stress: 1, marks: { double: [[5, 6]], silent: [] }, source: 'rule' };
const january: DanceSpec = { version: 1, letters: ['Jan', 'u', 'a', 'ry'], stress: 0, marks: { double: [], silent: [] }, source: 'rule' };
const february: DanceSpec = { version: 1, letters: ['Feb', 'ru', 'a', 'ry'], stress: 0, marks: { double: [], silent: [] }, source: 'rule' };

describe('dances', () => {
  it('maps every letter to its syllable chunk', () => {
    expect(syllableIndexes(rabbit)).toEqual([0, 0, 0, 1, 1, 1]);
    expect(syllableIndexes(banana)).toEqual([0, 0, 1, 1, 2, 2]);
  });

  it('spellPlan enters the letters in order and pauses at the syllable boundary', () => {
    const plan = spellPlan(rabbit);
    expect(plan.map((s) => s.index)).toEqual([0, 1, 2, 3, 4, 5]);
    const delays = plan.map((s) => Number(s.options.delay));
    expect(delays).toEqual([0, LETTER_MS, 2 * LETTER_MS, 3 * LETTER_MS + SYLLABLE_PAUSE_MS, 4 * LETTER_MS + SYLLABLE_PAUSE_MS, 5 * LETTER_MS + SYLLABLE_PAUSE_MS]);
    expect(plan[0]?.options.fill).toBe('backwards'); // invisible until its turn, visible afterwards
    expect(plan[0]?.keyframes[0]).toMatchObject({ opacity: 0 });
    expect(spellDuration(rabbit)).toBe(5 * LETTER_MS + SYLLABLE_PAUSE_MS + ENTER_MS);
  });

  it('words of 8 letters or more enter faster so the longest 小学 dances stay within 2.5 s', () => {
    const plan = spellPlan(supermarket);
    expect(Number(plan[1]?.options.delay)).toBe(LETTER_MS_LONG);
    expect(Number(spellPlan(tomorrow)[1]?.options.delay)).toBe(LETTER_MS_LONG); // exactly 8 letters already take the fast path
    expect(Number(spellPlan(rabbit)[1]?.options.delay)).toBe(LETTER_MS);
    for (const spec of [supermarket, rabbit, tomorrow, umbrella, january, february]) expect(danceDuration(spec)).toBeLessThanOrEqual(2500);
  });

  it('beatPlan beats syllable by syllable, the stressed one higher and coloured, after the spelling', () => {
    const start = spellDuration(banana);
    const plan = beatPlan(banana, 'rgb(1, 2, 3)', start);
    expect(plan).toHaveLength(6);
    expect(plan.map((s) => Number(s.options.delay))).toEqual([start, start, start + BEAT_MS, start + BEAT_MS, start + 2 * BEAT_MS, start + 2 * BEAT_MS]);
    const stressed = plan.filter((s) => s.index === 2 || s.index === 3);
    const unstressed = plan.filter((s) => s.index === 0);
    expect(stressed[0]?.options.duration).toBe(BEAT_STRESSED_MS);
    expect(stressed[0]?.keyframes[1]).toMatchObject({ color: 'rgb(1, 2, 3)', transform: 'translateY(-0.6em) scale(1.18)' });
    expect(unstressed[0]?.options.duration).toBe(BEAT_MS);
    expect(unstressed[0]?.keyframes[1]).toMatchObject({ transform: 'translateY(-0.2em)' });
    expect(beatDuration(banana, start)).toBe(start + 3 * BEAT_MS + (BEAT_STRESSED_MS - BEAT_MS));
  });

  it('a spec without a stress mark beats evenly, and silent letters do not beat', () => {
    expect(beatPlan(uncle, 'red').every((s) => s.options.duration === BEAT_MS && !('color' in (s.keyframes[1] ?? {})))).toBe(true);
    expect(beatPlan(night, 'red').map((s) => s.index)).toEqual([0, 1, 4]); // g and h stay still
  });

  it('twinPlan makes doubled letters jump together after the beats', () => {
    const plan = twinPlan(rabbit, 1000);
    expect(plan.map((s) => s.index)).toEqual([2, 3]);
    expect(plan.every((s) => s.options.delay === 1000 && s.options.duration === TWIN_MS)).toBe(true);
    expect(twinPlan(banana)).toEqual([]);
  });

  it('dancePlan is spell → beats → twins and danceDuration covers it', () => {
    const plan = dancePlan(rabbit, 'red');
    expect(plan).toHaveLength(6 + 6 + 2);
    const end = Math.max(...plan.map((s) => Number(s.options.delay) + Number(s.options.duration)));
    expect(end).toBe(danceDuration(rabbit));
  });
});
