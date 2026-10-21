// TodayPage — today's words (FRONTEND §2, §5.3; API.md 43/44/46). States: none ("zh.today.notYet(push_time)" +
// buildNow, or the empty-bank state), building/ready/published (ring done/total, chips, deferred-reviews note,
// "zh.today.pending(n)" only while counts.pending_content > 0, suggestions badge from suggestions_open,
// more — also while building), complete ("zh.today.done + zh.today.seeYou" + more + goScreen + goVocab) and the
// "zh.today.continueYesterday(n)" card whenever previous_open_batch is set. `GET /api/today` is polled every
// 30 s while content is pending and the tab is visible.
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { errorMessage, isApiError } from '@/api/client';
import { buildToday, getBank, getToday, requestMore } from '@/api/endpoints';
import type { MoreSource } from '@/api/endpoints';
import type { TodayCounts, TodayResponse } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { hasUngradedItems, setTodayUngraded } from '@/components/layout/AppLayout';
import { ProgressRing } from '@/components/stats/ProgressRing';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { useApi } from '@/hooks/useApi';
import { usePageTitle } from '@/hooks/usePageTitle';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { formatMonthDay } from '@/utils/srsPreview';
import './TodayPage.css';

const PENDING_POLL_MS = 30_000;

type Chip = { key: keyof typeof zh.today.counts; label: string; done: number; total: number };

export function countChips(counts: TodayCounts): Chip[] {
  const chips: Chip[] = [
    { key: 'review', label: zh.today.counts.review, done: counts.review_done, total: counts.review },
    { key: 'new', label: zh.today.counts.new, done: counts.new_done, total: counts.new },
    { key: 'screen', label: zh.today.counts.screen, done: counts.screen_done, total: counts.screen },
    { key: 'extra', label: zh.today.counts.extra, done: counts.extra_done, total: counts.extra },
  ];
  return chips.filter((c) => c.total > 0);
}

export default function TodayPage() {
  usePageTitle(zh.today.title);
  const { settings } = useAuth();
  const toast = useToast();
  const [building, setBuilding] = useState(false);
  const [moreBusy, setMoreBusy] = useState<MoreSource | null>(null);

  const today = useApi<TodayResponse>((signal) => getToday(signal), []);
  const { data, reload, setData } = today;
  const batch = data?.batch ?? null;
  const pending = batch?.counts.pending_content ?? 0;

  // the empty-bank state needs to know whether the bank has anything to push (FRONTEND §6.1)
  const probe = useApi((signal) => getBank({ state: 'active', page_size: 1 }, signal), [], { enabled: data?.status === 'none' });
  const bankEmpty = data?.status === 'none' && probe.data !== null && probe.data.total === 0;

  // shell today-badge (WP7 AppLayout): mirror "ungraded items exist" from every TodayResponse we hold
  useEffect(() => {
    if (data) setTodayUngraded(hasUngradedItems(data));
  }, [data]);

  useEffect(() => {
    if (pending <= 0) return;
    const timer = setInterval(() => {
      if (document.visibilityState !== 'visible') return;
      void reload();
    }, PENDING_POLL_MS);
    return () => clearInterval(timer);
  }, [pending, reload]);

  const build = useCallback(async () => {
    setBuilding(true);
    try {
      setData(await buildToday());
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setBuilding(false);
    }
  }, [setData, toast]);

  const more = useCallback(
    async (source: MoreSource) => {
      setMoreBusy(source);
      try {
        const res = await requestMore({ source });
        setData(res);
        if ((res.added ?? 0) === 0) toast.toast(zh.today.nothingMore);
      } catch (e) {
        if (isApiError(e) && e.code === 'batch_not_ready') toast.error(zh.today.buildFirst);
        else toast.error(errorMessage(e));
      } finally {
        setMoreBusy(null);
      }
    },
    [setData, toast],
  );

  if (today.loading && !data) {
    return (
      <section className="page today" aria-busy="true">
        <h1 className="page__title">{zh.today.title}</h1>
        <Skeleton height={120} width={120} variant="circle" />
        <Skeleton lines={3} />
      </section>
    );
  }

  if (today.error && !data) {
    return (
      <section className="page today">
        <h1 className="page__title">{zh.today.title}</h1>
        <EmptyState title={errorMessage(today.error)} action={{ label: zh.common.retry, onClick: () => void reload() }} />
      </section>
    );
  }
  if (!data) return null;

  const pushTime = data.push_time || settings?.push_time || '08:00';
  const previous = data.previous_open_batch;
  const continueCard = previous && previous.remaining > 0 && (
    <Link className="today__yesterday card" to={routePaths.studyBatch(previous.id)}>
      <span className="today__yesterday-title">{zh.today.continueYesterday(previous.remaining)}</span>
      <span className="today__yesterday-sub muted">
        {zh.today.yesterdayBatch} · {formatMonthDay(previous.local_date)}
      </span>
    </Link>
  );

  const header = (
    <header className="today__head">
      <div>
        <h1 className="page__title today__title">{zh.today.title}</h1>
        <p className="today__date muted">{formatMonthDay(data.local_date)}</p>
      </div>
      <p className="today__streak">{zh.today.streak(data.streak_days)}</p>
    </header>
  );

  // ---- no batch yet ----------------------------------------------------------------------------------
  if (!batch) {
    return (
      <section className="page today">
        {header}
        {continueCard}
        {bankEmpty ? (
          <EmptyState title={zh.today.emptyBank} action={{ label: zh.today.goScreen, to: routePaths.screen }} />
        ) : (
          <div className="today__none card">
            <p className="today__none-text">{zh.today.notYet(pushTime)}</p>
            {data.can_build_now && (
              <Button variant="primary" size="lg" loading={building} onClick={() => void build()}>
                {zh.today.buildNow}
              </Button>
            )}
          </div>
        )}
        <div className="today__links">
          {bankEmpty && (
            <Link className="btn btn--secondary btn--md" to={routePaths.vocab}>
              <span className="btn__label">{zh.today.goVocab}</span>
            </Link>
          )}
          {data.suggestions_open > 0 && (
            <Link className="btn btn--ghost btn--md" to={routePaths.bankSuggestions}>
              <span className="btn__label">{zh.today.suggestions(data.suggestions_open)}</span>
            </Link>
          )}
        </div>
      </section>
    );
  }

  // ---- batch exists ---------------------------------------------------------------------------------
  const counts = batch.counts;
  const chips = countChips(counts);
  const allDone = counts.total > 0 && counts.done >= counts.total;
  const finished = data.goal_met || allDone || batch.completed_at !== null;
  const canMore = batch.can_request_more;
  const studyLabel = counts.done > 0 ? zh.today.resume : zh.today.start;

  return (
    <section className="page today">
      {header}
      {continueCard}

      <div className="today__hero card">
        <ProgressRing done={counts.done} total={counts.total} size={128} />
        <div className="today__hero-body">
          <ul className="today__chips" aria-label={zh.today.title}>
            {chips.map((c) => (
              <li key={c.key} className={`today__chip today__chip--${c.key}`}>
                <span className="today__chip-label">{c.label}</span>
                <span className="today__chip-count">
                  {c.done}/{c.total}
                </span>
              </li>
            ))}
          </ul>
          {counts.deferred_reviews > 0 && <p className="today__note muted">{zh.today.deferred(counts.deferred_reviews)}</p>}
          {counts.pending_content > 0 && (
            <p className="today__note today__note--pending" role="status">
              {zh.today.pending(counts.pending_content)}
            </p>
          )}
          {data.suggestions_open > 0 && (
            <Link className="today__suggestions" to={routePaths.bankSuggestions}>
              {zh.today.suggestions(data.suggestions_open)}
            </Link>
          )}
        </div>
      </div>

      {finished ? (
        <div className="today__done card">
          <p className="today__done-title">{zh.today.done}</p>
          <p className="muted">{zh.today.seeYou(pushTime)}</p>
          {!allDone && (
            <Link className="btn btn--secondary btn--md" to={routePaths.study}>
              <span className="btn__label">{zh.today.resume}</span>
            </Link>
          )}
        </div>
      ) : (
        <Link className="btn btn--primary btn--lg btn--block today__cta" to={routePaths.study}>
          <span className="btn__label">{studyLabel}</span>
        </Link>
      )}

      <div className="today__actions">
        <Button variant="secondary" disabled={!canMore || moreBusy !== null} loading={moreBusy === 'new'} onClick={() => void more('new')}>
          {zh.today.moreNew}
        </Button>
        <Button variant="secondary" tone="screen" disabled={!canMore || moreBusy !== null} loading={moreBusy === 'screen'} onClick={() => void more('screen')}>
          {zh.today.moreScreen}
        </Button>
        <Link className="btn btn--ghost btn--md" to={routePaths.screen}>
          <span className="btn__label">{zh.today.goScreen}</span>
        </Link>
        <Link className="btn btn--ghost btn--md" to={routePaths.vocab}>
          <span className="btn__label">{zh.today.goVocab}</span>
        </Link>
      </div>
    </section>
  );
}
