// HistoryPage — history (FRONTEND §2, §5.8; API.md 48/49/51): streak / longest streak, the study calendar (5 weeks, the 12
// loaded ones on demand) and ONE row per day, newest first — the day's status and what it held, linking to its batch —
// then the stubborn list from Stats.stubborn. The calendar and the rows use the same word for a finished day.
import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { errorMessage } from '@/api/client';
import { getHistory, getHistoryBatches, getStats } from '@/api/endpoints';
import type { BatchSummary, DayStats, TodayCounts } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { CALENDAR_WEEKS, CALENDAR_WEEKS_MAX, StudyCalendar, dayState, hasEarlier, weekdayName, type CalendarDay } from '@/components/stats/StudyCalendar';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/components/ui/cx';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { joinDot } from '@/utils/format';
import { addDays, formatMonthDay, localDateOf } from '@/utils/srsPreview';
import './HistoryPage.css';

/** 12 weeks = 84 days including today. */
export const HISTORY_DAYS = 84;

/** The day's goal from `DayStats` alone: the calendar's stand-in until `Stats.heatmap` (the server's predicate) has loaded. */
export function dayGoalMet(d: Pick<DayStats, 'batch_total' | 'batch_done'>): boolean {
  return d.batch_total !== null && d.batch_total > 0 && d.batch_done !== null && d.batch_done >= d.batch_total;
}

/** API.md §9.1 `goal_met` of a batch summary: completed once, or every review / new / extra item final (a screen-only batch counts its screen items). */
export function batchGoalMet(b: Pick<BatchSummary, 'counts' | 'completed_at'>): boolean {
  if (b.completed_at !== null) return true;
  const c = b.counts;
  const study = c.review + c.new + c.extra;
  if (study > 0) return c.review_done + c.new_done + c.extra_done >= study;
  return c.total > 0 && c.done >= c.total;
}

/** `done` = goal met · today's open batch is `progress` once something is graded, `pending` before · an older open batch is `unfinished`. */
export type DayStatus = keyof typeof zh.history.status;

export function batchStatus(b: Pick<BatchSummary, 'counts' | 'completed_at' | 'local_date'>, today: string): DayStatus {
  if (batchGoalMet(b)) return 'done';
  if (b.local_date !== today) return 'unfinished';
  return b.counts.done > 0 ? 'progress' : 'pending';
}

/** What the day held, per kind: plain totals once every item is done, done/total while something is left. */
export function kindsText(c: TodayCounts): string {
  const allDone = c.done >= c.total;
  const kinds = [
    { label: zh.today.counts.review, done: c.review_done, total: c.review },
    { label: zh.today.counts.new, done: c.new_done, total: c.new },
    { label: zh.today.counts.screen, done: c.screen_done, total: c.screen },
    { label: zh.today.counts.extra, done: c.extra_done, total: c.extra },
  ].filter((k) => k.total > 0);
  return joinDot(kinds.map((k) => (allDone ? `${k.label} ${k.total}` : `${k.label} ${k.done}/${k.total}`)));
}

export type DayRow =
  | { kind: 'batch'; date: string; batch: BatchSummary }
  | { kind: 'idle'; date: string } // a batch without items: nothing was due that day
  | { kind: 'graded'; date: string; graded: number } // graded (yesterday's leftovers) on a day without a batch
  | { kind: 'offline'; date: string };

/**
 * One row per day, newest first: the loaded batches, plus the batch-less days of `days` that were studied or offline. While
 * older batches are still to be loaded, a batch-less day older than the oldest loaded batch waits for its neighbours.
 */
export function buildDayRows(batches: readonly BatchSummary[], days: readonly DayStats[], allLoaded: boolean): DayRow[] {
  const rows: DayRow[] = batches.map((b) => (b.counts.total > 0 ? { kind: 'batch', date: b.local_date, batch: b } : { kind: 'idle', date: b.local_date }));
  const batchDates = new Set(batches.map((b) => b.local_date));
  const oldest = batches.reduce<string | null>((min, b) => (min === null || b.local_date < min ? b.local_date : min), null);
  for (const d of days) {
    if (d.batch_id !== null || batchDates.has(d.date) || (d.graded <= 0 && !d.offline)) continue;
    if (!allLoaded && oldest !== null && d.date < oldest) continue;
    rows.push(d.graded > 0 ? { kind: 'graded', date: d.date, graded: d.graded } : { kind: 'offline', date: d.date });
  }
  return rows.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

export default function HistoryPage() {
  usePageTitle(zh.history.title);
  const { settings } = useAuth();
  const timeZone = settings?.timezone;
  const today = localDateOf(new Date(), timeZone);
  const from = addDays(today, -(HISTORY_DAYS - 1));

  const history = useApi((signal) => getHistory({ from, to: today }, signal), [from, today]);
  const stats = useApi((signal) => getStats(signal), []);
  // The pages accumulate inside the fetcher's result, so the list and its total arrive in one render: the day rows are built
  // from both, and a list filled one render after its page would first show the batch-less days alone.
  const [page, setPage] = useState(1);
  const loadedRef = useRef<BatchSummary[]>([]);
  const batchPage = useApi(
    async (signal) => {
      const next = await getHistoryBatches(page, signal);
      const prev = page === 1 ? [] : loadedRef.current;
      loadedRef.current = [...prev, ...next.items.filter((b) => !prev.some((p) => p.id === b.id))];
      return { items: loadedRef.current, total: next.total };
    },
    [page],
  );
  const batches = batchPage.data?.items ?? [];
  const batchTotal = batchPage.data?.total ?? 0;
  const [expanded, setExpanded] = useState(false);

  const days = history.data?.days ?? [];
  const goalByDate = new Map((stats.data?.heatmap ?? []).map((h) => [h.date, h.goal_met]));
  const calendarDays: CalendarDay[] = days.map((d) => ({ date: d.date, graded: d.graded, goal_met: goalByDate.get(d.date) ?? dayGoalMet(d) }));
  const batchByDate = new Map(days.flatMap((d) => (d.batch_id !== null && (d.batch_total ?? 0) > 0 ? [[d.date, d.batch_id] as const] : [])));
  const earlier = hasEarlier(calendarDays, today);
  const rows = buildDayRows(batches, days, batches.length >= batchTotal);
  const streak = history.data?.streak_days ?? stats.data?.streak_days ?? 0;
  const longest = history.data?.longest_streak ?? stats.data?.longest_streak ?? 0;
  const stubborn = stats.data?.stubborn ?? [];
  const loading = (history.loading && !history.data) || (batchPage.loading && !batchPage.data);
  const listFailed = batchPage.error !== null && !batchPage.data; // the days cannot be listed without their batches
  const empty = !loading && history.data !== null && !listFailed && rows.length === 0 && calendarDays.every((d) => dayState(d) === 'none');

  if (history.error && !history.data) {
    return (
      <section className="page history">
        <h1 className="page__title">{zh.history.title}</h1>
        <EmptyState title={errorMessage(history.error)} action={{ label: zh.common.retry, onClick: () => void history.reload() }} />
      </section>
    );
  }

  return (
    <section className="page history">
      <header className="history__head">
        <h1 className="page__title">{zh.history.title}</h1>
        <p className="history__streaks">
          <span className="history__streak">{zh.today.streak(streak)}</span>
          <span className="muted">{zh.history.longest(longest)}</span>
        </p>
      </header>

      {loading ? (
        <div aria-busy="true" className="stack">
          <Skeleton height={280} />
          <Skeleton lines={5} />
        </div>
      ) : empty ? (
        <EmptyState title={zh.history.empty} action={{ label: zh.today.start, to: routePaths.today }} />
      ) : (
        <>
          <section className="history__section card" aria-label={zh.history.calendar}>
            <div className="history__section-head">
              <h2 className="history__section-title">{zh.history.calendar}</h2>
              {earlier && (
                <Button variant="ghost" size="sm" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
                  {expanded ? zh.history.collapse : zh.history.earlier}
                </Button>
              )}
            </div>
            <StudyCalendar
              days={calendarDays}
              today={today}
              weeks={expanded && earlier ? CALENDAR_WEEKS_MAX : CALENDAR_WEEKS}
              hrefFor={(date) => {
                const id = batchByDate.get(date);
                return id === undefined ? null : routePaths.batch(id);
              }}
            />
          </section>

          {listFailed && batchPage.error ? (
            <EmptyState title={errorMessage(batchPage.error)} action={{ label: zh.common.retry, onClick: () => void batchPage.reload() }} />
          ) : rows.length > 0 ? (
            <section className="history__section" aria-label={zh.history.days}>
              <h2 className="history__section-title">{zh.history.days}</h2>
              <ol className="history__days">
                {rows.map((row) => {
                  const date = joinDot([`${formatMonthDay(row.date)} ${weekdayName(row.date)}`, row.date === today ? zh.history.today : null]);
                  if (row.kind === 'batch') {
                    const status = batchStatus(row.batch, today);
                    return (
                      <li key={row.date}>
                        <Link className="history__day card" to={routePaths.batch(row.batch.id)}>
                          <span className="history__day-head">
                            <span className="history__day-date">{date}</span>
                            <span className={cx('history__status', `history__status--${status}`)}>{zh.history.status[status]}</span>
                          </span>
                          <span className="history__day-kinds muted">{kindsText(row.batch.counts)}</span>
                        </Link>
                      </li>
                    );
                  }
                  const note = row.kind === 'idle' ? zh.history.noTasks : row.kind === 'offline' ? zh.history.offline : zh.history.gradedCount(row.graded);
                  return (
                    <li key={row.date} className={cx('history__note', row.kind === 'offline' && 'history__note--offline')}>
                      {joinDot([date, note])}
                    </li>
                  );
                })}
              </ol>
              {batches.length < batchTotal && (
                // a page that failed is asked for again, not skipped
                <Button variant="secondary" block loading={batchPage.loading} onClick={() => (batchPage.error ? void batchPage.reload() : setPage((p) => p + 1))}>
                  {zh.common.loadMore}
                </Button>
              )}
            </section>
          ) : null}

          {stubborn.length > 0 && (
            <section className="history__section card" aria-label={zh.history.stubborn}>
              <h2 className="history__section-title">{zh.history.stubborn}</h2>
              <ul className="history__stubborn">
                {stubborn.map((w) => (
                  <li key={w.id}>
                    <Link className="history__stubborn-row" to={routePaths.word(w.id)}>
                      <span className="history__stubborn-word" lang="en">
                        {w.display}
                      </span>
                      <span className="muted history__stubborn-zh">{w.translation_short}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </section>
  );
}
