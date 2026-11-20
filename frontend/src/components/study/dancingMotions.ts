// The motion library of a dancing picture card (API.md §9.1 `ImageMeta.dancing`; docs/releases/2026-11-dancing-cards.md).
// A drawing of prompt svg-v3 names ONE motion from a closed list for its `<g id="actor">`; this file is the only place that turns
// such a name into keyframes — the drawing itself carries no animation. Each motion moves the picture's actor and, with a smaller
// amplitude, the word printed on the picture's ground, so both say the same thing. Lengths are user units of the 800 x 500 canvas.
// Like `dances.ts`: per-keyframe easings only (an options-level easing on a multi-keyframe step warps its offsets).

export const DANCING_MOTIONS = ['none', 'hop', 'rise', 'fall', 'shiver', 'sway', 'spin', 'pulse', 'grow', 'shrink', 'dash', 'float'] as const;
export type DancingMotion = (typeof DANCING_MOTIONS)[number];

export interface StageRecord {
  motion: DancingMotion;
  /** A run of letters of the headword to light up, or ''. */
  highlight: string;
}

export interface MotionStep {
  frames: Keyframe[];
  duration: number;
  iterations?: number;
  /** The point of the target's own box the transform is anchored to. */
  origin: '50% 100%' | '50% 50%';
}

export const LETTER_STEP_MS = 85;
export const LETTER_ENTER_MS = 280;
export const BEAT_MS = 300;
export const BEAT_GAP_MS = 160;
export const HIGHLIGHT_MS = 600;

/** `<desc id="wd-stage">` of a stored drawing: anything unreadable, or a motion this build does not know, is a still picture. */
export function parseStage(text: string | null | undefined): StageRecord {
  try {
    const data: unknown = JSON.parse(text ?? '');
    if (data && typeof data === 'object') {
      const { motion, highlight } = data as { motion?: unknown; highlight?: unknown };
      return {
        motion: (DANCING_MOTIONS as readonly string[]).includes(motion as string) ? (motion as DancingMotion) : 'none',
        highlight: typeof highlight === 'string' ? highlight : '',
      };
    }
  } catch {
    /* not JSON: a still picture */
  }
  return { motion: 'none', highlight: '' };
}

/** Letter indexes of the first place `highlight` occurs in `word` (case-insensitive); empty when it does not. */
export function highlightIndexes(word: string, highlight: string): number[] {
  const at = highlight ? word.toLowerCase().indexOf(highlight.toLowerCase()) : -1;
  return at < 0 ? [] : Array.from({ length: highlight.length }, (_, i) => at + i);
}

const y = (v: number, rest = '') => `translateY(${v}px)${rest}`;
const shake = (a: number): Keyframe[] => [0, -a, a, -a, a, -a, a, -a * 0.6, a * 0.6, 0].map((x) => ({ transform: `translateX(${x}px)` }));
const rock = (deg: number): Keyframe[] => [0, deg, -deg, deg, -deg, 0].map((d) => ({ transform: `rotate(${d}deg)`, easing: 'ease-in-out' }));
const hop = (h: number): Keyframe[] => [
  { transform: y(0, ' scale(1,1)') },
  { transform: y(0, ' scale(1.06,.9)'), offset: 0.12, easing: 'ease-out' },
  { transform: y(-h, ' scale(.97,1.04)'), offset: 0.4, easing: 'ease-in' },
  { transform: y(0, ' scale(1.08,.88)'), offset: 0.62, easing: 'ease-out' },
  { transform: y(-h * 0.4, ' scale(1,1)'), offset: 0.78, easing: 'ease-in' },
  { transform: y(0, ' scale(1,1)'), offset: 0.92 },
  { transform: y(0, ' scale(1,1)') },
];
const lift = (h: number): Keyframe[] => [
  { transform: y(0), easing: 'ease-out' },
  { transform: y(-h), offset: 0.45 },
  { transform: y(-h), offset: 0.72, easing: 'ease-in-out' },
  { transform: y(0) },
];
const scaleTo = (s: number): Keyframe[] => [
  { transform: 'scale(1)', easing: 'ease-out' },
  { transform: `scale(${s})`, offset: 0.4 },
  { transform: `scale(${s})`, offset: 0.75, easing: 'ease-in-out' },
  { transform: 'scale(1)' },
];
const beatOf = (s: number): Keyframe[] => [{ transform: 'scale(1)', easing: 'ease-out' }, { transform: `scale(${s})`, offset: 0.4, easing: 'ease-in' }, { transform: 'scale(1)' }];
const slideIn = (from: number): Keyframe[] => [
  { transform: `translateX(${from}px)`, opacity: 0, easing: 'ease-out' },
  { transform: `translateX(${from * 0.6}px)`, opacity: 1, offset: 0.2, easing: 'ease-out' },
  { transform: 'translateX(18px)', opacity: 1, offset: 0.75, easing: 'ease-in-out' },
  { transform: 'translateX(0px)', opacity: 1 },
];
const drift = (h: number): Keyframe[] => [
  { transform: y(0, ' rotate(0deg)'), easing: 'ease-in-out' },
  { transform: y(-h, ' rotate(-2deg)'), offset: 0.3, easing: 'ease-in-out' },
  { transform: y(-h * 0.6, ' rotate(2deg)'), offset: 0.55, easing: 'ease-in-out' },
  { transform: y(-h, ' rotate(-1deg)'), offset: 0.78, easing: 'ease-in-out' },
  { transform: y(0, ' rotate(0deg)') },
];

const FOOT = '50% 100%' as const;
const CENTRE = '50% 50%' as const;

/** What the picture's actor does, and what the word does with it; null for `none`. */
export function motionSteps(motion: DancingMotion): { actor: MotionStep; word: MotionStep } | null {
  switch (motion) {
    case 'hop':
      return { actor: { frames: hop(50), duration: 1300, origin: FOOT }, word: { frames: hop(40), duration: 1300, origin: FOOT } }; // a drawn jumper often stands high in the canvas: a bigger lift cuts its head off
    case 'rise':
      return { actor: { frames: lift(60), duration: 1200, origin: FOOT }, word: { frames: lift(44), duration: 1200, origin: FOOT } };
    case 'fall':
      return {
        actor: {
          frames: [{ transform: y(-80), opacity: 0, easing: 'ease-in' }, { opacity: 1, offset: 0.3 }, { transform: y(0), opacity: 1, offset: 0.85 }, { transform: y(0), opacity: 1 }],
          duration: 520,
          iterations: 3,
          origin: FOOT,
        },
        word: {
          frames: [
            { transform: y(0, ' scale(1,1)'), easing: 'ease-out' },
            { transform: y(-56, ' scale(.94,1.1)'), offset: 0.3, easing: 'ease-in' },
            { transform: y(0, ' scale(1.14,.8)'), offset: 0.62, easing: 'ease-out' },
            { transform: y(0, ' scale(1,1)'), offset: 0.8 },
            { transform: y(0, ' scale(1,1)') },
          ],
          duration: 1100,
          origin: FOOT,
        },
      };
    case 'shiver':
      return { actor: { frames: shake(7), duration: 1000, origin: FOOT }, word: { frames: shake(5), duration: 1000, origin: FOOT } };
    case 'sway':
      return { actor: { frames: rock(6), duration: 1400, origin: FOOT }, word: { frames: rock(4), duration: 1400, origin: FOOT } };
    case 'spin':
      return {
        actor: { frames: [{ transform: 'rotate(0deg)', easing: 'ease-in-out' }, { transform: 'rotate(360deg)' }], duration: 1200, origin: CENTRE },
        word: { frames: rock(5), duration: 1200, origin: FOOT },
      };
    case 'pulse':
      return { actor: { frames: beatOf(1.12), duration: 420, iterations: 3, origin: CENTRE }, word: { frames: beatOf(1.07), duration: 420, iterations: 3, origin: FOOT } };
    case 'grow':
      return { actor: { frames: scaleTo(1.25), duration: 1400, origin: FOOT }, word: { frames: scaleTo(1.22), duration: 1400, origin: FOOT } };
    case 'shrink':
      return { actor: { frames: scaleTo(0.6), duration: 1400, origin: FOOT }, word: { frames: scaleTo(0.7), duration: 1400, origin: FOOT } };
    case 'dash':
      return { actor: { frames: slideIn(-520), duration: 900, origin: FOOT }, word: { frames: slideIn(-360), duration: 900, origin: FOOT } };
    case 'float':
      return { actor: { frames: drift(40), duration: 1800, origin: FOOT }, word: { frames: drift(24), duration: 1800, origin: FOOT } };
    default:
      return null;
  }
}

/** When the meaning part starts: after the last letter has entered and the word has beaten once. */
export function meaningStart(letterCount: number): number {
  return Math.max(0, letterCount - 1) * LETTER_STEP_MS + LETTER_ENTER_MS + BEAT_MS + BEAT_GAP_MS;
}
