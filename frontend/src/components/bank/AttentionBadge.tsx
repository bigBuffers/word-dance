// AttentionBadge — the attention state machine of a bank row (FRONTEND §4, API.md §9.1 / endpoint 36):
//   needs_attention && attention_msg      → ⚠ msg + edit · retry (only while is_valid_english === null) ·
//                                           keep (label collect-only when is_valid_english === false) · delete · replace with "X"
//   needs_attention && !attention_msg     → re-validating (spinner; polls GET /api/words/{id} every 3 s, max 30)
//   !needs_attention && is_valid_english === null  → pending validation (polls the same way)
//   !needs_attention && is_valid_english === false → collect-only chip (muted, no buttons)
//   a pending typo suggestion on a valid word       → replace with "X" alone
// Buttons render only for the handlers the page supplies, so the badge doubles as a read-only chip.
import type { UserWord, WordBrief, WordDetail } from '@/api/types';
import * as endpoints from '@/api/endpoints';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { usePolling } from '@/hooks/usePolling';
import { zh } from '@/i18n/zh';
import './bank.css';

export type AttentionState = 'flagged' | 'rechecking' | 'pending' | 'collect_only' | 'suggestion' | 'none';

export const ATTENTION_POLL_MS = 3000;
export const ATTENTION_POLL_MAX = 30;

/** `WordDetail.word` → its `WordBrief` part (drops the detail-only fields) — for patching list rows after a poll. */
export function briefOf(word: WordDetail['word']): WordBrief {
  const { confusables, definition, translation, pos, exam_tags, bnc, forms, source, ...brief } = word;
  void [confusables, definition, translation, pos, exam_tags, bnc, forms, source];
  return brief;
}

export function attentionState(
  mine: Pick<UserWord, 'needs_attention' | 'attention_msg' | 'suggested_word'> | null | undefined,
  word: Pick<WordBrief, 'is_valid_english'>,
): AttentionState {
  if (!mine) return 'none';
  if (mine.needs_attention) return mine.attention_msg ? 'flagged' : 'rechecking';
  if (word.is_valid_english === null) return 'pending';
  if (word.is_valid_english === false) return 'collect_only';
  if (mine.suggested_word) return 'suggestion';
  return 'none';
}

/** True while the row waits on the `lookup_word` job (pending validation / re-validating). */
export function isPollingState(state: AttentionState): boolean {
  return state === 'pending' || state === 'rechecking';
}

export interface AttentionBadgeProps {
  mine: UserWord;
  word: WordBrief;
  /** keep (`PATCH {attention:'keep'}`); the page then calls `refreshCounters()`. */
  onKeep?: () => void | Promise<void>;
  /** retry (`PATCH {attention:'retry'}`), offered only while `is_valid_english === null`. */
  onRetry?: () => void | Promise<void>;
  /** edit: `mark remove` then `/bank/add?prefill=`. */
  onEdit?: () => void | Promise<void>;
  /** delete: `mark remove`. */
  onRemove?: () => void | Promise<void>;
  /** replace with "X": `POST /api/bank/{id}/accept-suggestion`. */
  onReplace?: () => void | Promise<void>;
  /** Called with the fresh detail once polling sees the flag resolve (or the row disappear). */
  onUpdate?: (detail: WordDetail) => void;
  /** Poll `GET /api/words/{id}` while pending validation / re-validating (default true). */
  poll?: boolean;
  busy?: boolean;
  className?: string;
}

export function AttentionBadge({ mine, word, onKeep, onRetry, onEdit, onRemove, onReplace, onUpdate, poll = true, busy = false, className }: AttentionBadgeProps) {
  const state = attentionState(mine, word);

  usePolling(
    async (signal) => {
      const detail = await endpoints.getWord(word.id, signal);
      const next = attentionState(detail.mine, detail.word);
      if (!detail.mine || next !== state) {
        onUpdate?.(detail);
        return false;
      }
      return true;
    },
    ATTENTION_POLL_MS,
    { enabled: poll && isPollingState(state), max: ATTENTION_POLL_MAX },
  );

  if (state === 'none') return null;

  if (state === 'rechecking') {
    return (
      <span className={cx('attn__chip', 'attn__chip--rechecking', className)} role="status">
        <span className="attn__spinner" aria-hidden="true" />
        {zh.bank.retrying}
      </span>
    );
  }
  if (state === 'pending') {
    return (
      <span className={cx('attn__chip', 'attn__chip--pending', className)} role="status">
        {zh.bank.pendingAi}
      </span>
    );
  }
  if (state === 'collect_only') {
    return (
      <span className={cx('attn__chip', 'attn__chip--collect', className)} title={zh.bank.keptOnly}>
        {zh.bank.keepOnly}
      </span>
    );
  }

  const suggested = mine.suggested_word;
  if (state === 'suggestion') {
    if (!suggested || !onReplace) return null;
    return (
      <div className={cx('attn', className)}>
        <div className="attn__actions">
          <Button size="sm" variant="primary" disabled={busy} onClick={() => void onReplace()}>
            {zh.bank.replaceWith(suggested.display)}
          </Button>
        </div>
      </div>
    );
  }

  // flagged
  const canRetry = word.is_valid_english === null;
  const keepLabel = word.is_valid_english === false ? zh.bank.keepOnly : zh.bank.keep;
  const hasActions = Boolean(onEdit || (onRetry && canRetry) || onKeep || onRemove || (onReplace && suggested));
  return (
    <div className={cx('attn', className)} role="group" aria-label={zh.bank.tabs.attention}>
      <p className="attn__msg" role="alert">
        <span className="attn__msg-icon" aria-hidden="true">
          ⚠
        </span>
        <span>{mine.attention_msg}</span>
      </p>
      {hasActions && (
        <div className="attn__actions">
          {onReplace && suggested && (
            <Button size="sm" variant="primary" disabled={busy} onClick={() => void onReplace()}>
              {zh.bank.replaceWith(suggested.display)}
            </Button>
          )}
          {onEdit && (
            <Button size="sm" disabled={busy} onClick={() => void onEdit()}>
              {zh.bank.edit}
            </Button>
          )}
          {onRetry && canRetry && (
            <Button size="sm" disabled={busy} onClick={() => void onRetry()}>
              {zh.bank.retry}
            </Button>
          )}
          {onKeep && (
            <Button size="sm" disabled={busy} onClick={() => void onKeep()}>
              {keepLabel}
            </Button>
          )}
          {onRemove && (
            <Button size="sm" variant="ghost" tone="again" disabled={busy} onClick={() => void onRemove()}>
              {zh.common.delete}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
