// WordHeader — display form (long words shrink), phonetic, SpeakButton, StageChips, KindBadge (FRONTEND §4).
import type { ItemKind, Stage, WordBrief } from '@/api/types';
import { cx } from '@/components/ui/cx';
import type { Accent } from '@/hooks/useSpeech';
import { KindBadge } from './KindBadge';
import { SpeakButton } from './SpeakButton';
import { StageChips } from './StageChips';
import './word.css';

export type WordHeaderSize = 'sm' | 'md' | 'lg';

export interface WordHeaderProps {
  word: Pick<WordBrief, 'display' | 'phonetic' | 'stages' | 'stage_min' | 'cet6_star'>;
  size?: WordHeaderSize;
  /** Push-item kind → review / new / screen / extra badge; omitted outside a study context. */
  kind?: ItemKind;
  /** Pronunciation accent override (defaults to the user's setting). */
  accent?: Accent;
  showStages?: boolean;
  /** Narrows the stage chips to these stages plus the word's lowest stage (`StageChips.only`); omitted = every stage. */
  onlyStages?: readonly Stage[];
  /** Heading element for the display form (`h1` on the detail page, `h2` on cards, `div` in lists). */
  as?: 'h1' | 'h2' | 'h3' | 'div';
  className?: string;
}

function lengthBucket(display: string): 'long' | 'xlong' | undefined {
  const n = display.length;
  if (n > 22) return 'xlong';
  if (n > 14) return 'long';
  return undefined;
}

export function WordHeader({ word, size = 'md', kind, accent, showStages = true, onlyStages, as: Tag = 'div', className }: WordHeaderProps) {
  // StageChips always renders something when shown (a stageless word gets the dashed outside-the-lists chip), so it counts as meta.
  const hasMeta = Boolean(word.phonetic) || kind !== undefined || showStages;
  return (
    <header className={cx('word-head', `word-head--${size}`, className)} data-len={lengthBucket(word.display)}>
      <div className="word-head__row">
        <Tag className="word-head__display" lang="en">
          {word.display}
        </Tag>
        <SpeakButton text={word.display} lang={accent} size={size === 'lg' ? 'lg' : size === 'sm' ? 'sm' : 'md'} />
      </div>
      {hasMeta && (
        <div className="word-head__meta">
          {word.phonetic && (
            <span className="word-head__phonetic" lang="en">
              /{word.phonetic}/
            </span>
          )}
          {kind !== undefined && <KindBadge kind={kind} />}
          {showStages && <StageChips stages={word.stages} stageMin={word.stage_min} cet6Star={word.cet6_star} only={onlyStages} size={size === 'lg' ? 'md' : 'sm'} />}
        </div>
      )}
    </header>
  );
}
