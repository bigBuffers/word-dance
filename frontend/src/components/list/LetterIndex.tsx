// LetterIndex — A–Z index for the vocabulary browser (FRONTEND §4): a sticky right rail on desktop,
// horizontally scrolling chips on phones (CSS). Letters without words are disabled; the first chip
// clears the filter. Keyboard: arrows move between letters, Enter/Space pick (roving tabindex).
import { useRef, type KeyboardEvent } from 'react';
import type { LetterCount } from '@/api/endpoints';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import './list.css';

export const LETTERS: readonly string[] = 'abcdefghijklmnopqrstuvwxyz'.split('');

export interface LetterIndexProps {
  letters: readonly LetterCount[];
  /** Active letter (lower-case) or null for no letter filter. */
  active: string | null;
  onPick: (letter: string | null) => void;
  /** Render as the desktop side rail (sticky, vertical ≥ 1024 px). */
  rail?: boolean;
  className?: string;
}

export function LetterIndex({ letters, active, onPick, rail = false, className }: LetterIndexProps) {
  const ref = useRef<HTMLElement>(null);
  const counts = new Map(letters.map((l) => [l.letter.toLowerCase(), l.count]));

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const buttons = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? []);
    if (buttons.length === 0) return;
    const current = buttons.findIndex((b) => b === document.activeElement);
    let next: number | null = null;
    switch (e.key) {
      case 'ArrowRight':
      case 'ArrowDown':
        next = (current + 1) % buttons.length;
        break;
      case 'ArrowLeft':
      case 'ArrowUp':
        next = (current - 1 + buttons.length) % buttons.length;
        break;
      case 'Home':
        next = 0;
        break;
      case 'End':
        next = buttons.length - 1;
        break;
      default:
        return;
    }
    e.preventDefault();
    buttons[next]?.focus();
  };

  const activeKey = active?.toLowerCase() ?? null;
  return (
    <nav ref={ref} className={cx('letters', rail && 'letters--rail', className)} aria-label={zh.vocab.letters} onKeyDown={onKeyDown}>
      <button
        type="button"
        className="letters__btn"
        aria-pressed={activeKey === null}
        tabIndex={activeKey === null ? 0 : -1}
        onClick={() => onPick(null)}
      >
        {zh.common.all}
      </button>
      {LETTERS.map((letter) => {
        const count = counts.get(letter) ?? 0;
        const pressed = activeKey === letter;
        return (
          <button
            key={letter}
            type="button"
            className="letters__btn"
            aria-pressed={pressed}
            aria-label={`${letter.toUpperCase()} (${count})`}
            title={String(count)}
            disabled={count === 0 && !pressed}
            tabIndex={pressed ? 0 : -1}
            onClick={() => onPick(pressed ? null : letter)}
          >
            {letter.toUpperCase()}
          </button>
        );
      })}
    </nav>
  );
}
