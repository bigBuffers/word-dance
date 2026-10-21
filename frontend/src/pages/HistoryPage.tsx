// HistoryPage — history (FRONTEND §2, §5.8; API.md 48/49/51): 12-week heat strip, streak / longest streak, day rows
// "<date> · completed 41/41 🔥" / "<date> · offline", stubborn list from Stats.stubborn and the past batches.
import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import { errorMessage } from '@/api/client';
import { getHistory, getHistoryBatches, getStats } from '@/api/endpoints';
import type { BatchSummary, DayStats } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { HeatStrip, type HeatDay } from '@/components/stats/HeatStrip';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/components/ui/cx';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { addDays, formatMonthDay, localDateOf } from '@/utils/srsPreview';
import './HistoryPage.css';

/** 12 weeks = 84 days including today. */
export const HISTORY_DAYS = 84;
const MAX_DAY_ROWS = 42;

export function dayGoalMet(d: Pick<DayStats, 'batch_total' | 'batch_done'>): boolean {
  return d.batch_total !== null && d.batch_total > 0 && d.batch_done !== null && d.batch_done >= d.batch_total;
}

/** Day row copy (FRONTEND §5.8). */
export function dayRowText(d: DayStats): string {
  const date = formatMonthDay(d.date);
  if (d.offline) return `${date} · ${zh.history.offline}`;
  if (d.batch_total !== null) return `${date} · ${zh.history.completed(d.batch_done ?? 0, d.batch_total)}${dayGoalMet(d) ? ' 🔥' : ''}`;
  return `${date} · ${zh.common.total(d.graded)}`;
}

/** Days worth a row: a batch, an offline gap or any grading — newest first. */
export function visibleDays(days: readonly DayStats[]): DayStats[] {
  return days
    .filter((d) => d.batch_id !== null || d.offline || d.graded > 0)
    .slice()
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))
    .slice(0, MAX_DAY_ROWS);
}

export default function HistoryPage() {
  usePageTitle(zh.history.title);
  const { settings } = useAuth();
  const timeZone = settings?.timezone;
  const today = localDateOf(new Date(), timeZone);
  const from = addDays(today, -(HISTORY_DAYS - 1));

  const history = useApi((signal) => getHistory({ from, to: today }, signal), [from, today]);
  const stats = useApi((signal) => getStats(signal), []);
  const [page, setPage] = useState(1);
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [batchTotal, setBatchTotal] = useState(0);
  const batchPage = useApi((signal) => getHistoryBatches(page, signal), [page]);
  const pageData = batchPage.data;
  useEffect(() => {
    if (!pageData) return;
    setBatchTotal(pageData.total);
    setBatches((prev) => (page === 1 ? pageData.items : [...prev, ...pageData.items.filter((b) => !prev.some((p) => p.id === b.id))]));
  }, [pageData, page]);

  const days = history.data?.days ?? [];
  const heatDays: HeatDay[] = stats.data?.heatmap ?? days.map((d) => ({ date: d.date, graded: d.graded, goal_met: dayGoalMet(d) }));
  const rows = visibleDays(days);
  const streak = history.data?.streak_days ?? stats.data?.streak_days ?? 0;
  const longest = history.data?.longest_streak ?? stats.data?.longest_streak ?? 0;
  const stubborn = stats.data?.stubborn ?? [];
  const loading = (history.loading && !history.data) || (batchPage.loading && !pageData && page === 1);
  const empty = !loading && history.data !== null && rows.length === 0 && batches.length === 0 && heatDays.every((d) => d.graded === 0);

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
          <Skeleton height={110} />
          <Skeleton lines={5} />
        </div>
      ) : empty ? (
        <EmptyState title={zh.history.empty} action={{ label: zh.today.start, to: routePaths.today }} />
      ) : (
        <>
          <section className="history__section card" aria-label={zh.history.heat}>
            <h2 className="history__section-title">{zh.history.heat}</h2>
            <HeatStrip days={heatDays} today={today} />
          </section>

          {rows.length > 0 && (
            <section className="history__section" aria-label={zh.history.title}>
              <ol className="history__days">
                {rows.map((d) => {
                  const text = dayRowText(d);
                  const cls = cx('history__day', d.offline && 'history__day--offline', dayGoalMet(d) && 'history__day--goal');
                  return (
                    <li key={d.date}>
                      {d.batch_id !== null ? (
                        <Link className={cls} to={routePaths.batch(d.batch_id)}>
                          {text}
                        </Link>
                      ) : (
                        <span className={cls}>{text}</span>
                      )}
                    </li>
                  );
                })}
              </ol>
            </section>
          )}

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

          {batches.length > 0 && (
            <section className="history__section" aria-label={zh.today.title}>
              <ul className="history__batches">
                {batches.map((b) => (
                  <li key={b.id}>
                    <Link className="history__batch card" to={routePaths.batch(b.id)}>
                      <span className="history__batch-date">{formatMonthDay(b.local_date)}</span>
                      <span className="muted">{zh.history.completed(b.counts.done, b.counts.total)}</span>
                      <span className="history__batch-kinds muted">
                        {zh.today.counts.review} {b.counts.review} · {zh.today.counts.new} {b.counts.new} · {zh.today.counts.screen} {b.counts.screen}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
              {batches.length < batchTotal && (
                <Button variant="secondary" block loading={batchPage.loading} onClick={() => setPage((p) => p + 1)}>
                  {zh.common.loadMore}
                </Button>
              )}
            </section>
          )}
        </>
      )}
    </section>
  );
}
