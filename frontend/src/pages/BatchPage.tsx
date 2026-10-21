// BatchPage — `/history/:batchId` (FRONTEND §2, §5.8; API.md 50): read-only batch with outcome chips.
// Title = the batch date (Oct 12). "replay" → `/study?batch=<id>` (replay); when the batch is still
// gradable (today's / yesterday's open batch) the button is resume and opens the grade bar instead.
import { Link, useParams } from 'react-router';
import { errorMessage } from '@/api/client';
import { getBatch } from '@/api/endpoints';
import type { TodayCounts } from '@/api/types';
import { ProgressRing } from '@/components/stats/ProgressRing';
import { resultLabel } from '@/components/study/StudyCard';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/components/ui/cx';
import { KindBadge } from '@/components/word/KindBadge';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { formatMonthDay } from '@/utils/srsPreview';
import './BatchPage.css';

function kindCounts(counts: TodayCounts): { label: string; done: number; total: number }[] {
  return [
    { label: zh.today.counts.review, done: counts.review_done, total: counts.review },
    { label: zh.today.counts.new, done: counts.new_done, total: counts.new },
    { label: zh.today.counts.screen, done: counts.screen_done, total: counts.screen },
    { label: zh.today.counts.extra, done: counts.extra_done, total: counts.extra },
  ].filter((c) => c.total > 0);
}

export default function BatchPage() {
  const { batchId } = useParams();
  const id = Number(batchId);
  const valid = Number.isInteger(id) && id > 0;
  const { data, error, loading, reload } = useApi((signal) => getBatch(id, signal), [id], { enabled: valid });
  const batch = data?.batch ?? null;
  const title = batch ? formatMonthDay(batch.local_date) : zh.history.title;
  usePageTitle(title);

  if (!valid || (error && error.status === 404)) {
    return (
      <section className="page batch">
        <EmptyState title={zh.errors.notFound} action={{ label: zh.history.title, to: routePaths.history }} />
      </section>
    );
  }
  if (error && !data) {
    return (
      <section className="page batch">
        <EmptyState title={errorMessage(error)} action={{ label: zh.common.retry, onClick: () => void reload() }} />
      </section>
    );
  }
  if (loading && !data) {
    return (
      <section className="page batch" aria-busy="true">
        <Skeleton height={32} width="40%" />
        <Skeleton height={120} width={120} variant="circle" />
        <Skeleton lines={6} />
      </section>
    );
  }
  if (!batch) {
    return (
      <section className="page batch">
        <EmptyState title={zh.history.empty} action={{ label: zh.history.title, to: routePaths.history }} />
      </section>
    );
  }

  const counts = batch.counts;
  return (
    <section className="page batch">
      <header className="batch__head">
        <Link to={routePaths.history} className="batch__back">
          {zh.common.back}
        </Link>
        <h1 className="page__title batch__title">{title}</h1>
      </header>

      <div className="batch__hero card">
        <ProgressRing done={counts.done} total={counts.total} />
        <div className="batch__hero-body">
          <ul className="batch__kinds">
            {kindCounts(counts).map((c) => (
              <li key={c.label}>
                {c.label} {c.done}/{c.total}
              </li>
            ))}
          </ul>
          <Link className={cx('btn', 'btn--md', batch.gradable ? 'btn--primary' : 'btn--secondary')} to={routePaths.studyBatch(batch.id)}>
            <span className="btn__label">{batch.gradable ? zh.today.resume : zh.history.replay}</span>
          </Link>
        </div>
      </div>

      <ol className="batch__items">
        {batch.items.map((it) => {
          const result = resultLabel(it.result);
          return (
            <li key={it.item_id}>
              <Link className="batch__item" to={routePaths.word(it.word.id)}>
                <span className="batch__item-word">
                  <span className="batch__item-display" lang="en">
                    {it.word.display}
                  </span>
                  <span className="batch__item-zh muted">{it.word.translation_short}</span>
                </span>
                <span className="batch__item-meta">
                  <KindBadge kind={it.kind} />
                  {result && <span className={cx('badge', 'batch__result', `batch__result--${it.result ?? 'none'}`)}>{result}</span>}
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
