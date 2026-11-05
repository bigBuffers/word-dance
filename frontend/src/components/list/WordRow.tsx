// WordRow — list row for vocab / bank (FRONTEND §4): display · phonetic · translation_short · stage
// chips · state badge · quick buttons unfamiliar / known (or in bank → sheet mastered / remove; mastered / known /
// removed words offer the deliberate unfamiliar re-add) · checkbox in bulk mode. The row body links to
// the word detail page; `meta` adds bank-specific chips and `actions` replaces the default buttons.
import { useState, type ReactNode } from 'react';
import { Link } from 'react-router';
import type { MarkAction, Stage, UserWord, WordBrief } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { Sheet } from '@/components/ui/Sheet';
import { StageChips } from '@/components/word/StageChips';
import { StateBadge } from '@/components/word/StateBadge';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import './list.css';

export interface WordRowProps {
  word: WordBrief;
  /** My bank row when known (adds the SRS due suffix to the state badge). */
  mine?: UserWord | null;
  /** Quick actions: `unfamiliar` / `known` for unmarked words, `mastered` / `remove` from the sheet, `unfamiliar` re-add otherwise. */
  onMark?: (action: MarkAction) => void | Promise<void>;
  /** Bulk mode: render a checkbox instead of the quick buttons. */
  selectable?: boolean;
  selected?: boolean;
  onSelect?: (selected: boolean) => void;
  /** A request for this row is in flight. */
  busy?: boolean;
  /** Extra chips/badges below the translation (bank page). */
  meta?: ReactNode;
  /** Replaces the default quick buttons (bank page overflow). */
  actions?: ReactNode;
  /** Full-width block under the row, outside the detail link (e.g. the AttentionBadge with its buttons). */
  footer?: ReactNode;
  /** Hide the state badge (e.g. when the parent shows a richer one). */
  hideState?: boolean;
  /** Narrows the stage chips to the learner's target stages plus the word's lowest stage (`StageChips.only`). */
  onlyStages?: readonly Stage[];
  className?: string;
}

export function WordRow({ word, mine, onMark, selectable = false, selected = false, onSelect, busy = false, meta, actions, footer, hideState = false, onlyStages, className }: WordRowProps) {
  const [sheetOpen, setSheetOpen] = useState(false);
  const state = mine?.state ?? word.my_state;

  const mark = (action: MarkAction) => {
    setSheetOpen(false);
    void onMark?.(action);
  };

  let defaultActions: ReactNode = null;
  if (onMark && !selectable) {
    if (state === null || state === undefined) {
      defaultActions = (
        <>
          <Button size="sm" tone="again" disabled={busy} onClick={() => mark('unfamiliar')}>
            {zh.vocab.markUnfamiliar}
          </Button>
          <Button size="sm" tone="good" disabled={busy} onClick={() => mark('known')}>
            {zh.vocab.markKnown}
          </Button>
        </>
      );
    } else if (state === 'new' || state === 'learning') {
      defaultActions = (
        <Button size="sm" variant="ghost" disabled={busy} aria-haspopup="dialog" aria-expanded={sheetOpen} onClick={() => setSheetOpen(true)}>
          {zh.vocab.inBank}
        </Button>
      );
    } else {
      defaultActions = (
        <Button size="sm" tone="again" disabled={busy} onClick={() => mark('unfamiliar')}>
          {zh.vocab.markUnfamiliar}
        </Button>
      );
    }
  }

  return (
    <li className={cx('word-row', selected && 'is-selected', busy && 'is-busy', className)} aria-busy={busy || undefined}>
      {selectable && (
        <label className="word-row__select">
          <input type="checkbox" checked={selected} disabled={busy} aria-label={word.display} onChange={(e) => onSelect?.(e.target.checked)} />
        </label>
      )}
      <Link to={routePaths.word(word.id)} className="word-row__main">
        <span className="word-row__head">
          <span className="word-row__display" lang="en">
            {word.display}
          </span>
          {word.phonetic && (
            <span className="word-row__phonetic" lang="en">
              /{word.phonetic}/
            </span>
          )}
        </span>
        {word.translation_short && <span className="word-row__trans">{word.translation_short}</span>}
        <span className="word-row__chips">
          <StageChips stages={word.stages} stageMin={word.stage_min} cet6Star={word.cet6_star} only={onlyStages} size="sm" />
          {!hideState && <StateBadge state={state ?? null} srs={mine?.srs ?? null} />}
          {meta}
        </span>
      </Link>
      {(actions ?? defaultActions) && <div className="word-row__actions">{actions ?? defaultActions}</div>}
      {footer && <div className="word-row__footer">{footer}</div>}
      {onMark && !actions && (state === 'new' || state === 'learning') && (
        <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} title={word.display}>
          <div className="word-row__sheet-actions">
            <Button variant="primary" tone="good" block onClick={() => mark('mastered')}>
              {zh.study.master}
            </Button>
            <Button variant="secondary" block onClick={() => mark('remove')}>
              {zh.word.remove}
            </Button>
          </div>
        </Sheet>
      )}
    </li>
  );
}
