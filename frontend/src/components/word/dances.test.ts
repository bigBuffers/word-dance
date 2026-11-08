// dances.ts — the pure keyframe plans of the 单词之舞 P1 (FRONTEND §6.5): letters enter in order with a pause at every syllable
// boundary, syllables beat in turn with the stressed one highest and coloured, silent letters never beat, doubled letters jump
// together at the end, and the whole choreography of the longest 小学 words stays under 2.5 s.
import { describe, expect, it } from 'vitest';
import type { DanceSpec } from '@/api/types';
import type { DancePrimitive } from '@/api/types';
import { BEAT_MS, BEAT_STRESSED_MS, ENTER_MS, LETTER_MS, LETTER_MS_LONG, OBJECT_OF, ONTO_TOUCHDOWN, SEMANTIC_GAP_MS, SYLLABLE_PAUSE_MS, TWIN_MS, beatDuration, beatPlan, danceDuration, dancePlan, ghostCount, poseColor, semanticDuration, semanticPlan, spellDuration, spellPlan, syllableIndexes, twinPlan } from './dances';

const rabbit: DanceSpec = { version: 1, letters: ['rab', 'bit'], stress: 0, marks: { double: [[2, 3]], silent: [] }, semantic: null, source: 'rule' };
const night: DanceSpec = { version: 1, letters: ['night'], stress: 0, marks: { double: [], silent: [2, 3] }, semantic: null, source: 'rule' };
const banana: DanceSpec = { version: 1, letters: ['ba', 'na', 'na'], stress: 1, marks: { double: [], silent: [] }, semantic: null, source: 'rule' };
const supermarket: DanceSpec = { version: 1, letters: ['su', 'per', 'mar', 'ket'], stress: 0, marks: { double: [], silent: [] }, semantic: null, source: 'rule' };
const uncle: DanceSpec = { version: 1, letters: ['un', 'cle'], stress: null, marks: { double: [], silent: [] }, semantic: null, source: 'rule' };
// the longest 小学 choreographies (8 letters, 3–4 syllables, doubled letters) — the real worst cases, not hand-picked easy ones
const tomorrow: DanceSpec = { version: 1, letters: ['to', 'mor', 'row'], stress: 1, marks: { double: [[4, 5]], silent: [] }, semantic: null, source: 'rule' };
const umbrella: DanceSpec = { version: 1, letters: ['um', 'brel', 'la'], stress: 1, marks: { double: [[5, 6]], silent: [] }, semantic: null, source: 'rule' };
const january: DanceSpec = { version: 1, letters: ['Jan', 'u', 'a', 'ry'], stress: 0, marks: { double: [], silent: [] }, semantic: null, source: 'rule' };
const february: DanceSpec = { version: 1, letters: ['Feb', 'ru', 'a', 'ry'], stress: 0, marks: { double: [], silent: [] }, semantic: null, source: 'rule' };

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

describe('semantic dances (语义舞, FRONTEND §6.5)', () => {
  const PRIMITIVES: DancePrimitive[] = ['rise', 'fall', 'hop', 'grow', 'shrink', 'dash', 'creep', 'enter', 'exit', 'arc', 'onto', 'under', 'behind', 'between', 'split', 'join', 'shiver', 'shimmer', 'wave', 'droop', 'stretch', 'squash', 'thud', 'float', 'spin', 'repeat', 'multiply', 'dim', 'glow', 'color'];
  const withSemantic = (primitive: DancePrimitive, params: { n?: number; color?: 'red' | 'black' } = {}): DanceSpec => ({ ...banana, letters: ['ba', 'na', 'na'], semantic: { primitive, params } });

  it('every primitive yields a plan whose steps point at real targets and ends within 2.5 s', () => {
    for (const primitive of PRIMITIVES) {
      const spec = withSemantic(primitive, primitive === 'color' ? { color: 'red' } : primitive === 'multiply' ? { n: 3 } : {});
      const plan = semanticPlan(spec, 'red');
      expect(plan.length, primitive).toBeGreaterThan(0);
      for (const step of plan) {
        expect(['letter', 'word', 'ghost', 'stage']).toContain(step.target);
        if (step.target === 'letter') expect(step.index).toBeLessThan(6);
        if (step.target === 'ghost') expect(step.index).toBeLessThan(ghostCount(spec));
        expect(step.keyframes.length).toBeGreaterThan(1);
        // only transform / opacity / colour properties: anything else (transform-origin, say) takes the effect off the compositor
        for (const k of step.keyframes) for (const key of Object.keys(k)) expect(['transform', 'opacity', 'color', 'textShadow', 'offset', 'easing', 'composite'], `${primitive}: ${key}`).toContain(key);
      }
      expect(semanticDuration(spec), primitive).toBeLessThanOrEqual(2500);
    }
  });

  it('a spec without a semantic has no semantic plan; black keeps the ink and darkens like dim, white glows like glow', () => {
    expect(semanticPlan(rabbit, 'red')).toEqual([]);
    expect(semanticDuration(rabbit)).toBe(0);
    expect(poseColor(withSemantic('color', { color: 'black' }))).toBeNull();
    expect(semanticPlan(withSemantic('color', { color: 'black' }), 'red')).toEqual(semanticPlan(withSemantic('dim'), 'red'));
    expect(semanticPlan({ ...banana, letters: ['ba', 'na', 'na'], semantic: { primitive: 'color', params: { color: 'white' } } }, 'red')).toEqual(semanticPlan(withSemantic('glow'), 'red'));
  });

  it('the colour pour starts from the heading ink (the pose is already worn) and ends in the resolved pose colour', () => {
    const plan = semanticPlan(withSemantic('color', { color: 'red' }), 'x', 0, { ink: 'rgb(29, 36, 51)', pose: 'rgb(196, 60, 60)' });
    expect(plan.length).toBe(6); // one step per letter (banana)
    expect(plan[0]?.keyframes[0]?.color).toBe('rgb(29, 36, 51)');
    expect(plan.every((s) => s.options.fill === 'backwards')).toBe(true); // each letter holds the ink until its turn
    expect(plan[0]?.keyframes.at(-1)?.color).toBe('rgb(196, 60, 60)');
    // without the DOM colours the plan still targets the token and starts from currentColor (what the static tests see)
    const bare = semanticPlan(withSemantic('color', { color: 'red' }), 'x');
    expect(bare[0]?.keyframes.at(-1)?.color).toBe('var(--pose-red)');
  });

  it('poses, objects and ghosts follow the primitive', () => {
    expect(poseColor(withSemantic('color', { color: 'red' }))).toBe('var(--pose-red)');
    expect(poseColor(withSemantic('shiver'))).toBe('var(--pose-blue)');
    expect(poseColor(withSemantic('rise'))).toBeNull();
    expect(OBJECT_OF.enter).toBe('box');
    expect(OBJECT_OF.under).toBe('table');
    expect(OBJECT_OF.rise).toBeUndefined();
    expect(OBJECT_OF.onto).toBe('shelf'); // P3: on lands on a shelf
    expect(OBJECT_OF.hop).toBeUndefined();
    expect(ghostCount(withSemantic('multiply', { n: 3 }))).toBe(2);
    expect(ghostCount(withSemantic('multiply', { n: 2 }))).toBe(1);
    expect(ghostCount(withSemantic('multiply'))).toBe(2);
    expect(ghostCount(withSemantic('grow'))).toBe(0);
    expect(semanticPlan(withSemantic('multiply', { n: 2 }), 'red').every((s) => s.target === 'ghost')).toBe(true);
    expect(semanticPlan(withSemantic('between'), 'red').some((s) => s.target === 'stage')).toBe(true);
    expect(semanticPlan(withSemantic('onto'), 'red').some((s) => s.target === 'stage')).toBe(true); // the shelf gives under the landing
    const hop = semanticPlan(withSemantic('hop'), 'red');
    expect(hop.every((s) => s.target === 'word')).toBe(true); // the whole word jumps …
    expect(hop[0]?.keyframes.some((k) => String(k.transform).includes('translateY(-'))).toBe(true); // … up …
    expect(hop[0]?.keyframes.at(-1)?.transform).toBe('none'); // … and comes back to the standard glyphs (principle 4)
    const onto = semanticPlan(withSemantic('onto'), 'red', 500);
    const ontoWord = onto.find((s) => s.target === 'word');
    const shelf = onto.find((s) => s.target === 'stage');
    expect(String(ontoWord?.keyframes[0]?.transform)).toMatch(/translateX\(-.*translateY\(-/); // enters from the upper left …
    expect(ontoWord?.keyframes.at(-1)?.transform).toBe('none'); // … and settles on the shelf
    expect(ontoWord?.options.delay).toBe(500);
    expect(shelf?.options.delay).toBe(500); // the shelf step starts with the word …
    expect(shelf?.options.easing).toBeUndefined(); // … carries no effect-level easing (it would warp the offsets) …
    expect(shelf?.keyframes[1]).toMatchObject({ transform: 'none', offset: ONTO_TOUCHDOWN }); // … holds still until the word has touched down …
    expect(Number(shelf?.keyframes[2]?.offset)).toBeGreaterThan(ONTO_TOUCHDOWN); // … then gives …
    expect(String(shelf?.keyframes[2]?.transform)).toContain('translateY(');
    expect(shelf?.keyframes.at(-1)?.transform).toBe('none'); // … and comes back
  });

  it('a full play = the form dance followed by the semantic dance after SEMANTIC_GAP_MS (sequenced by DancingWord, pinned here as durations)', () => {
    const spec = withSemantic('rise');
    expect(SEMANTIC_GAP_MS).toBeGreaterThan(0);
    expect(danceDuration(spec) + SEMANTIC_GAP_MS + semanticDuration(spec)).toBeLessThanOrEqual(5500); // both halves within a 5.5 s replay
    expect(semanticPlan(rabbit, 'red')).toEqual([]); // no semantic → the full play is the form dance alone
  });
});
