// DancingWord — the headword as letter spans that play the spelling dance (letters enter syllable by syllable) and the stress dance (syllables
// beat in turn, the stressed one highest) through the Web Animations API whenever `playToken` changes (FRONTEND §4, §6.5;
// docs/WORD_DANCE_DESIGN.md §4.1–4.2). It renders plain letters and never animates when the spec is null, when the browser has
// no `element.animate` (jsdom), or when the viewer prefers reduced motion — in that static case the stressed syllable keeps a
// colour mark and silent letters stay muted, so the information survives without motion (design principle 6). A remount (the
// card turning over) does not replay: only a token that moves after mount does — except with `autoplay`, which plays once in
// the mount's layout phase so the first card show never paints the whole word before hiding it for the entrance.
import { useEffect, useLayoutEffect, useRef } from 'react';
import type { DanceSpec } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { dancePlan, syllableIndexes } from './dances';
import './word.css';

export interface DancingWordProps {
  text: string;
  spec: DanceSpec | null;
  /** Increment to play the choreography (🔊, key P). The initial value never plays. */
  playToken?: number;
  /** Play once on mount, before the first paint (the card show of a word on its first exposures). */
  autoplay?: boolean;
  className?: string;
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** `element.animate` exists (not in jsdom) and the viewer has not asked for reduced motion. */
export function canDance(): boolean {
  return typeof Element !== 'undefined' && typeof Element.prototype.animate === 'function' && !prefersReducedMotion();
}

function play(root: HTMLElement, spec: DanceSpec): void {
  const letters = Array.from(root.querySelectorAll<HTMLElement>('.dword__l'));
  if (letters.length === 0) return;
  for (const el of letters) el.getAnimations?.().forEach((a) => a.cancel());
  const accent = getComputedStyle(root).getPropertyValue('--dance-accent').trim() || 'currentColor';
  for (const step of dancePlan(spec, accent)) letters[step.index]?.animate(step.keyframes, step.options);
}

export function DancingWord({ text, spec, playToken = 0, autoplay = false, className }: DancingWordProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const lastToken = useRef(playToken);
  const autoplayRef = useRef(autoplay);

  useLayoutEffect(() => {
    if (autoplayRef.current && ref.current && spec && canDance()) play(ref.current, spec);
    // mount only: a later autoplay change is not a replay request
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (playToken === lastToken.current) return;
    lastToken.current = playToken;
    if (ref.current && spec && canDance()) play(ref.current, spec);
  }, [playToken, spec]);

  if (!spec || spec.letters.join('') !== text) {
    return (
      <span className={className} lang="en">
        {text}
      </span>
    );
  }
  const syl = syllableIndexes(spec);
  const silent = new Set(spec.marks.silent);
  const isStatic = !canDance();
  return (
    <span ref={ref} className={cx('dword', isStatic && 'dword--static', className)} lang="en">
      {[...text].map((ch, i) => (
        <span
          key={i}
          className={cx('dword__l', spec.stress !== null && syl[i] === spec.stress && 'dword__l--stressed', silent.has(i) && 'dword__l--silent')}
          data-syl={syl[i]}
        >
          {ch}
        </span>
      ))}
    </span>
  );
}
