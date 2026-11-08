// DancingWord — the headword as letter spans that play the spelling dance (letters enter syllable by syllable), the stress dance
// (syllables beat in turn, the stressed one highest) and the semantic dance (the word does its meaning: up rises, in walks into a
// box) through the Web Animations API (FRONTEND §4, §6.5; docs/WORD_DANCE_DESIGN.md §4.1–4.3). It renders plain letters and never
// animates when the spec is null, when the browser has no `element.animate` (jsdom), or when the viewer prefers reduced motion —
// in that static case the stressed syllable keeps a colour mark, silent letters stay muted and a semantic pose colour (cold blue,
// red red) still shows, so the information survives without motion (design principle 6). A remount (the card turning over) does
// not replay: only a token that moves after mount does — except with `autoplay`, which plays once in the mount's layout phase so
// the first card show never paints the whole word before hiding it for the entrance.
import { useEffect, useLayoutEffect, useRef } from 'react';
import type { DanceSpec } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { OBJECT_OF, SEMANTIC_GAP_MS, danceDuration, dancePlan, ghostCount, poseColor, semanticPlan, syllableIndexes, type DanceColors, type DancePlayKind, type DanceStep } from './dances';
import './word.css';

export interface DancingWordProps {
  text: string;
  spec: DanceSpec | null;
  /** Increment to replay (🔊, key P). The initial value never plays. */
  playToken?: number;
  /** Play once on mount, before the first paint: 'form' on the card front, 'semantic' on the back (the reveal), 'full' for both. */
  autoplay?: DancePlayKind | false;
  /** What a replay plays: 'form' on the front (no meaning leak), 'full' on the back and the detail page. */
  replay?: DancePlayKind;
  /** `settings.dance_mode === 'form_only'`: the semantic dance is never played or posed. */
  semanticEnabled?: boolean;
  className?: string;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** `element.animate` exists (not in jsdom) and the viewer has not asked for reduced motion. */
export function canDance(): boolean {
  return typeof Element !== 'undefined' && typeof Element.prototype.animate === 'function' && !prefersReducedMotion();
}

/**
 * Play `kind` on the word inside `root`. 'full' runs the form dance now and the semantic dance after `danceDuration + SEMANTIC_GAP_MS`
 * as a second play (returned timer id, cancelled by the caller on the next play or unmount): scheduling the semantic steps with a
 * delay instead would let the `fill: 'backwards'` entrances of rise / fall / dash hide the letters during the whole form dance.
 */
function play(root: HTMLElement, spec: DanceSpec, kind: DancePlayKind): number | null {
  const letters = Array.from(root.querySelectorAll<HTMLElement>('.dword__l'));
  if (letters.length === 0) return null;
  const wordEl = root.querySelector<HTMLElement>('.dword') ?? root;
  const ghosts = Array.from(root.querySelectorAll<HTMLElement>('.dword__ghost'));
  const stage = root.querySelector<HTMLElement>('.dword-obj');
  for (const el of [...letters, wordEl, ...ghosts, ...(stage ? [stage] : [])]) el.getAnimations?.().forEach((a) => a.cancel());
  const wordStyle = getComputedStyle(wordEl);
  const accent = wordStyle.getPropertyValue('--dance-accent').trim() || 'currentColor';
  // the heading ink (the stage inherits it) and the word's resolved rest colour (its inline `--pose-*` pose, if any)
  const colors: DanceColors = { ink: getComputedStyle(root).color || undefined, pose: wordStyle.color || undefined };
  const run = (steps: DanceStep[]) => {
    for (const step of steps) {
      const target = step.target === 'letter' ? letters[step.index] : step.target === 'ghost' ? ghosts[step.index] : step.target === 'stage' ? stage : wordEl;
      target?.animate(step.keyframes, step.options);
    }
  };
  if (kind === 'semantic') {
    run(semanticPlan(spec, accent, 0, colors));
    return null;
  }
  run(dancePlan(spec, accent));
  if (kind === 'full' && spec.semantic) return window.setTimeout(() => run(semanticPlan(spec, accent, 0, colors)), danceDuration(spec) + SEMANTIC_GAP_MS);
  return null;
}

export function DancingWord({ text, spec, playToken = 0, autoplay = false, replay = 'form', semanticEnabled = true, className }: DancingWordProps) {
  const rootRef = useRef<HTMLSpanElement>(null);
  const lastToken = useRef(playToken);
  const live: DanceSpec | null = spec === null ? null : semanticEnabled ? spec : { ...spec, semantic: null };
  const liveRef = useRef(live);
  liveRef.current = live;
  const autoplayRef = useRef<DancePlayKind | false>(autoplay);
  const replayRef = useRef<DancePlayKind>(replay);
  replayRef.current = replay;
  const timerRef = useRef<number | null>(null); // the pending second half of a 'full' play
  const start = (kind: DancePlayKind) => {
    const current = liveRef.current;
    if (!rootRef.current || !current || !canDance()) return;
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = play(rootRef.current, current, kind);
  };

  useLayoutEffect(() => {
    const kind = autoplayRef.current;
    if (kind) start(kind);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // mount only: a later autoplay change is not a replay request

  useEffect(() => {
    if (playToken === lastToken.current) return;
    lastToken.current = playToken;
    start(replayRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playToken]); // a token move is the only trigger; the spec and replay kind are read through refs

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current); // unmount: the second half never plays on a gone word
    },
    [],
  );

  if (!live || live.letters.join('') !== text) {
    return (
      <span className={className} lang="en">
        {text}
      </span>
    );
  }
  const syl = syllableIndexes(live);
  const silent = new Set(live.marks.silent);
  const isStatic = !canDance();
  const object = live.semantic ? OBJECT_OF[live.semantic.primitive] : undefined;
  const pose = poseColor(live);
  const ghosts = ghostCount(live);
  const markStress = live.stress !== null && live.letters.length > 1; // a one-chunk word's stress mark carries no information (and would hide the pose)
  const wordNode = (
    <span className={cx('dword', isStatic && 'dword--static', pose && 'dword--posed', className)} lang="en" style={pose ? { color: pose } : undefined}>
      {[...text].map((ch, i) => (
        <span key={i} className={cx('dword__l', markStress && syl[i] === live.stress && 'dword__l--stressed', silent.has(i) && 'dword__l--silent')} data-syl={syl[i]}>
          {ch}
        </span>
      ))}
      {Array.from({ length: ghosts }, (_, g) => (
        <span key={`g${g}`} className="dword__ghost" aria-hidden="true">
          {text}
        </span>
      ))}
    </span>
  );
  return (
    <span ref={rootRef} className={cx('dword-stage', object && `dword-stage--${object}`)} data-primitive={live.semantic?.primitive}>
      {object && <span className={cx('dword-obj', `dword-obj--${object}`)} aria-hidden="true" />}
      {wordNode}
    </span>
  );
}
