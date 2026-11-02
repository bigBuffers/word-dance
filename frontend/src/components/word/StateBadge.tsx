// StateBadge — bank state label (zh.bank.tabs.*, zh.vocab.status.unmarked for null) plus a due suffix for learning words (FRONTEND §4).
// The due suffix mirrors the DESIGN §7 `humanize` thresholds from the SRS `due_at` (calendar days in the
// browser's local time) and adds the client-only `nextDue.today` / `nextDue.overdue` for a word whose review is due
// (FRONTEND §4 StateBadge row); the authoritative string right after a grade is `GradeResponse.next_due_zh`.
import type { Srs, UserState } from '@/api/types';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import './word.css';

const DAY_MS = 86_400_000;
const startOfLocalDay = (t: number) => {
  const d = new Date(t);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
};

export type DueKind = 'step' | 'overdue' | 'today' | 'future';

/** Classifies `dueAt` against `now`; null when `dueAt` is missing or unparsable (step 0). */
export function classifyDue(dueAt: string | null | undefined, step: 0 | 1 = 0, now: number = Date.now()): DueKind | null {
  const due = dueAt ? Date.parse(dueAt) : Number.NaN;
  if (step === 1) return Number.isNaN(due) || due > now ? 'step' : 'today';
  if (Number.isNaN(due)) return null;
  const days = Math.round((startOfLocalDay(due) - startOfLocalDay(now)) / DAY_MS);
  if (days < 0) return 'overdue';
  if (days === 0) return 'today';
  return 'future';
}

/**
 * `nextDue.tenMin` while in the learning step (`nextDue.today` once that step has elapsed); `nextDue.overdue`
 * for a review due on an earlier day, `nextDue.today` for one due today (whatever the hour), then
 * `nextDue.tomorrow`, `nextDue.days(N)` (2–59), `nextDue.months(M)` (≥ 60, M = N/30 half-up);
 * `null` only when `dueAt` is missing or unparsable.
 */
export function formatDue(dueAt: string | null | undefined, step: 0 | 1 = 0, now: number = Date.now()): string | null {
  const kind = classifyDue(dueAt, step, now);
  if (kind === null) return null;
  if (kind === 'step') return zh.study.nextDue.tenMin;
  if (kind === 'overdue') return zh.study.nextDue.overdue;
  if (kind === 'today') return zh.study.nextDue.today;
  const days = Math.round((startOfLocalDay(Date.parse(dueAt as string)) - startOfLocalDay(now)) / DAY_MS);
  if (days === 1) return zh.study.nextDue.tomorrow;
  if (days < 60) return zh.study.nextDue.days(days);
  return zh.study.nextDue.months(Math.floor(days / 30 + 0.5));
}

/** The due sentence of the detail page: `bank.dueIn(label)` for a future / today due date, the bare `nextDue.overdue` otherwise. */
export function formatDueSentence(dueAt: string | null | undefined, step: 0 | 1 = 0, now: number = Date.now()): string | null {
  const label = formatDue(dueAt, step, now);
  if (label === null) return null;
  return classifyDue(dueAt, step, now) === 'overdue' ? label : zh.bank.dueIn(label);
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
