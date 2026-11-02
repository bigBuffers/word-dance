// SuggestionRow — one suggestions (FRONTEND §4/§5.7): copy per type, accept / keep for open rows, undo for
// auto-applied rows inside their 7-day window.
import type { Suggestion } from '@/api/types';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import { daysUntil } from '@/utils/date';
import { joinDot } from '@/utils/format';
import './bank.css';

/** The headline copy for a suggestion (exported for tests). */
export function suggestionText(s: Suggestion): string {
  const from = s.user_word?.display ?? s.payload.from ?? '';
  const to = s.target?.display ?? s.payload.to ?? '';
  switch (s.type) {
    case 'fix_spelling':
      return zh.suggestions.fix_spelling(from, to);
    case 'lemmatize':
      return s.status === 'auto' ? zh.suggestions.auto_lemmatize(from, to) : zh.suggestions.lemmatize(from, to);
    case 'merge_duplicate':
      return zh.suggestions.merge_duplicate(from, to);
    case 'invalid_word':
      return zh.suggestions.invalid_word(from);
    case 'split_phrase':
      return zh.suggestions.split_phrase(to);
    case 'fill_data':
      return zh.suggestions.fill_data(from);
    case 'confusable_group':
      return joinDot([zh.study.confusable, ...(s.payload.group ?? [])]);
    case 'difficulty':
    default:
      return s.payload.note_zh ?? (from ? zh.suggestions.fill_data(from) : '');
  }
}

/** Whether an auto-applied row can still be undone (API.md 42: `status='auto'` within `expires_at`). */
export function canUndo(s: Suggestion, now: Date = new Date()): boolean {
  if (s.status !== 'auto') return false;
  if (!s.expires_at) return true;
  return Date.parse(s.expires_at) > now.getTime();
}

export interface SuggestionRowProps {
  s: Suggestion;
  onAccept?: (s: Suggestion) => void | Promise<void>;
  onReject?: (s: Suggestion) => void | Promise<void>;
  onUndo?: (s: Suggestion) => void | Promise<void>;
  busy?: boolean;
  now?: Date;
  className?: string;
}

export function SuggestionRow({ s, onAccept, onReject, onUndo, busy = false, now, className }: SuggestionRowProps) {
  const text = suggestionText(s);
  const note = s.payload.note_zh && s.payload.note_zh !== text ? s.payload.note_zh : null;
  const days = s.expires_at ? daysUntil(s.expires_at, now) : null;
  const showExpiry = (s.status === 'open' || s.status === 'auto') && days !== null && days >= 0;
  const undoable = canUndo(s, now);

  return (
    <li className={cx('sugg', `sugg--${s.status}`, className)} aria-busy={busy || undefined}>
      <div className="sugg__body">
        <p className="sugg__text">{text}</p>
        {note && <p className="sugg__note">{note}</p>}
        <div className="sugg__meta">
          {s.status === 'auto' && <span>{zh.suggestions.autoSection}</span>}
          {s.status === 'undone' && <span>{zh.suggestions.undone}</span>}
          {showExpiry && <span>{days === 0 ? zh.suggestions.expiresToday : zh.suggestions.expiresIn(days)}</span>}
          {typeof s.payload.confidence === 'number' && <span aria-hidden="true">{Math.round(s.payload.confidence * 100)}%</span>}
        </div>
      </div>
      {s.status === 'open' && (onAccept || onReject) && (
        <div className="sugg__actions">
          {onAccept && (
            <Button variant="primary" size="sm" loading={busy} onClick={() => void onAccept(s)}>
              {zh.suggestions.accept}
            </Button>
          )}
          {onReject && (
            <Button variant="secondary" size="sm" disabled={busy} onClick={() => void onReject(s)}>
              {zh.suggestions.reject}
            </Button>
          )}
        </div>
      )}
      {s.status === 'auto' && onUndo && undoable && (
        <div className="sugg__actions">
          <Button variant="secondary" size="sm" loading={busy} onClick={() => void onUndo(s)}>
            {zh.suggestions.undo}
          </Button>
        </div>
      )}
    </li>
  );
}
