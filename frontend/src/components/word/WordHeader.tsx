// WordHeader — display form (long words shrink), phonetic, SpeakButton, StageChips, KindBadge (FRONTEND §4). With a `dance` spec
// (word dance P1, §6.5) the display form is a DancingWord — the letters enter syllable by syllable and the syllables beat, the
// stressed one highest — a row of syllable chips marks the stressed syllable, and 🔊 replays the dance together with the sound.
import { useState } from 'react';
import type { DanceSpec, ItemKind, Stage, WordBrief } from '@/api/types';
import { cx } from '@/components/ui/cx';
import type { Accent } from '@/hooks/useSpeech';
import { zh } from '@/i18n/zh';
import { DancingWord } from './DancingWord';
import type { DancePlayKind } from './dances';
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
  /**
   * word dance: the word's `DanceSpec` (`null` = the word has no spec, the letters render plain); omitted = the feature is off for
   * this view (`settings.dance_mode === 'off'`, lists, the standalone screening deck).
   */
  dance?: DanceSpec | null;
  /** Replay counter driven by the page (key P); 🔊 adds its own replays on top. */
  playToken?: number;
  /** Play once on mount, before the first paint: 'form' on the card front, 'semantic' on the back (the reveal), 'full' for both. */
  autoplay?: DancePlayKind | false;
  /** What 🔊 / key P replay: 'form' (default, no meaning leak on the front) or 'full' (back face, detail page). */
  replay?: DancePlayKind;
  /** `settings.dance_mode === 'form_only'`: the semantic dance is never played or posed. */
  semanticEnabled?: boolean;
}

function lengthBucket(display: string): 'long' | 'xlong' | undefined {
  const n = display.length;
  if (n > 22) return 'xlong';
  if (n > 14) return 'long';
  return undefined;
}

export function WordHeader({ word, size = 'md', kind, accent, showStages = true, onlyStages, as: Tag = 'div', className, dance, playToken = 0, autoplay = false, replay = 'form', semanticEnabled = true }: WordHeaderProps) {
  const [replays, setReplays] = useState(0);
  const dancing = dance !== undefined;
  const chips = dance && dance.letters.length > 1 ? dance : null;
  // StageChips always renders something when shown (a stageless word gets the dashed outside-the-lists chip), so it counts as meta.
  const hasMeta = Boolean(word.phonetic) || kind !== undefined || showStages || chips !== null;
  return (
    <header className={cx('word-head', `word-head--${size}`, className)} data-len={lengthBucket(word.display)}>
      <div className="word-head__row">
        {/* the letter spans are inline-block, so the heading names itself (otherwise screen readers spell r a b b i t) */}
        <Tag className="word-head__display" lang="en" aria-label={dance ? word.display : undefined}>
          {dancing ? <DancingWord text={word.display} spec={dance} playToken={playToken + replays} autoplay={autoplay} replay={replay} semanticEnabled={semanticEnabled} /> : word.display}
        </Tag>
        <SpeakButton
          text={word.display}
          lang={accent}
          size={size === 'lg' ? 'lg' : size === 'sm' ? 'sm' : 'md'}
          onClick={dancing ? () => setReplays((n) => n + 1) : undefined}
        />
      </div>
      {hasMeta && (
        <div className="word-head__meta">
          {chips && (
            <ol className="syl" aria-label={zh.word.syllables}>
              {chips.letters.map((chunk, i) => (
                <li key={i} className={cx('syl__chip', chips.stress === i && 'syl__chip--stressed')} lang="en">
                  {chunk}
                </li>
              ))}
            </ol>
          )}
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
