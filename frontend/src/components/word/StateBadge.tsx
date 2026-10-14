// StateBadge — bank state label (zh.bank.tabs.*, zh.vocab.status.unmarked for null) plus a due suffix for learning words (FRONTEND §4).
// The due suffix mirrors the DESIGN §7 `humanize` thresholds from the SRS `due_at` (calendar days in the
// browser's local time); the authoritative string after a grade is `GradeResponse.next_due_zh`.
import type { Srs, UserState } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import './word.css';

const DAY_MS = 86_400_000;
const startOfLocalDay = (t: number) => {
  const d = new Date(t);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
};

/**
 * `nextDue.tenMin` while in the learning step, `nextDue.tomorrow`, `nextDue.days(N)` (2–59), `nextDue.months(M)` (≥ 60, M = N/30 half-up);
 * `null` when the word is due now / overdue or `dueAt` is missing or unparsable.
 */
export function formatDue(dueAt: string | null | undefined, step: 0 | 1 = 0, now: number = Date.now()): string | null {
  const due = dueAt ? Date.parse(dueAt) : Number.NaN;
  if (step === 1) return Number.isNaN(due) || due > now ? zh.study.nextDue.tenMin : null;
  if (Number.isNaN(due) || due <= now) return null;
  const days = Math.round((startOfLocalDay(due) - startOfLocalDay(now)) / DAY_MS);
  if (days <= 0) return null;
  if (days === 1) return zh.study.nextDue.tomorrow;
  if (days < 60) return zh.study.nextDue.days(days);
  return zh.study.nextDue.months(Math.floor(days / 30 + 0.5));
}

export function stateLabel(state: UserState | null): string {
  return state ? zh.bank.tabs[state] : zh.vocab.status.unmarked;
}

export interface StateBadgeProps {
  state: UserState | null;
  /** Adds the due suffix for `learning` words. */
  srs?: Srs | null;
  /** Reference time (tests). */
  now?: number;
  className?: string;
}

export function StateBadge({ state, srs, now, className }: StateBadgeProps) {
  const due = state === 'learning' && srs ? formatDue(srs.due_at, srs.step, now) : null;
  return (
    <span className={cx('badge', 'state-badge', `state-badge--${state ?? 'none'}`, className)}>
      {stateLabel(state)}
      {due && <span className="state-badge__due">{` · ${due}`}</span>}
    </span>
  );
}
