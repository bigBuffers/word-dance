// ScreenCard — rapid known / unfamiliar / skip triage card (FRONTEND §4, §5.4): headword + phonetic + 🔊,
// swipe right = known, swipe left = unfamiliar on touch, reveal peek keeps the buttons.
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import type { ScreenVerdict, WordBrief } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { WordHeader } from '@/components/word/WordHeader';
import { useBottomBarOffset } from '@/hooks/useBottomBarOffset';
import type { Accent } from '@/hooks/useSpeech';
import { zh } from '@/i18n/zh';
import './study.css';

/** Horizontal distance (px) that counts as a swipe verdict. */
export const SWIPE_THRESHOLD = 80;

export interface ScreenCardProps {
  word: WordBrief;
  onVerdict: (verdict: ScreenVerdict) => void;
  onPeek?: () => void;
  /** Controlled peek state (optional; the card keeps its own otherwise). */
  peeked?: boolean;
  /** Disables the buttons while a verdict is being posted. */
  busy?: boolean;
  accent?: Accent;
  /** screen card inside a study session: shows the kind badge. */
  inSession?: boolean;
  className?: string;
}

export function ScreenCard({ word, onVerdict, onPeek, peeked, busy = false, accent, inSession = false, className }: ScreenCardProps) {
  const [localPeek, setLocalPeek] = useState(false);
  const [dx, setDx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const startX = useRef<number | null>(null);
  const barRef = useBottomBarOffset<HTMLDivElement>(); // toasts stack above the verdict bar, never over the known / unfamiliar buttons
  useEffect(() => {
    setLocalPeek(false);
    setDx(0);
    startX.current = null;
  }, [word.id]);

  const isPeeked = peeked ?? localPeek;
  const peek = () => {
    setLocalPeek(true);
    onPeek?.();
  };

  // No explicit pointer capture: capturing on the body would retarget the click of the speaker / peek
  // buttons inside it. Touch pointers are implicitly captured by their target, so pointerup still arrives.
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (busy || e.pointerType === 'mouse') return;
    startX.current = e.clientX;
    setDragging(true);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (startX.current === null) return;
    setDx(e.clientX - startX.current);
  };
  const finish = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (startX.current === null) return;
    const delta = e.clientX - startX.current;
    startX.current = null;
    setDragging(false);
    setDx(0);
    if (delta >= SWIPE_THRESHOLD) onVerdict('known');
    else if (delta <= -SWIPE_THRESHOLD) onVerdict('unfamiliar');
  };
  const cancel = () => {
    startX.current = null;
    setDragging(false);
    setDx(0);
  };

  const direction = dx >= SWIPE_THRESHOLD / 2 ? 'right' : dx <= -SWIPE_THRESHOLD / 2 ? 'left' : null;

  return (
    <article className={cx('screen-card', className)} role="group" aria-label={word.display}>
      <div
        className={cx('screen-card__body', dragging && 'is-dragging', direction === 'right' && 'is-right', direction === 'left' && 'is-left')}
        style={dx !== 0 ? { transform: `translateX(${dx}px) rotate(${dx / 30}deg)` } : undefined}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finish}
        onPointerCancel={cancel}
        onPointerLeave={cancel}
      >
        <span className="screen-card__swipe screen-card__swipe--right" aria-hidden="true">
          {zh.study.known}
        </span>
        <span className="screen-card__swipe screen-card__swipe--left" aria-hidden="true">
          {zh.study.unfamiliar}
        </span>
        <WordHeader word={word} size="lg" as="h2" kind={inSession ? 'screen' : undefined} accent={accent} showStages={false} className="screen-card__word" />
        {isPeeked ? (
          <p className="screen-card__peek" lang="zh-CN">
            {word.translation_short}
          </p>
        ) : (
          <button type="button" className="screen-card__peek-link" onClick={peek}>
            {zh.screen.peek}
          </button>
        )}
      </div>
      <div className="screen-card__bar" ref={barRef}>
        <Button variant="primary" tone="good" size="lg" disabled={busy} onClick={() => onVerdict('known')}>
          {zh.study.known}
          <kbd className="study-kbd" aria-hidden="true">
            1
          </kbd>
        </Button>
        <Button variant="primary" tone="again" size="lg" disabled={busy} onClick={() => onVerdict('unfamiliar')}>
          {zh.study.unfamiliar}
          <kbd className="study-kbd" aria-hidden="true">
            2
          </kbd>
        </Button>
        <Button variant="ghost" disabled={busy} onClick={() => onVerdict('skip')}>
          {zh.study.skip}
          <kbd className="study-kbd" aria-hidden="true">
            S
          </kbd>
        </Button>
      </div>
    </article>
  );
}
