// SessionSummary — end-of-session card (FRONTEND §5.1.7): completed ring, counts, unfamiliar words as chips
// to the detail page, streak, buttons moreNew / moreScreen (while `can_request_more`) / goScreen / backToToday.
import { Link } from 'react-router';
import type { SessionSummary as SessionSummaryDto, WordBrief } from '@/api/types';
import { ProgressRing } from '@/components/stats/ProgressRing';
import { Button } from '@/components/ui/Button';
import { cx } from '@/components/ui/cx';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import './study.css';

export interface SessionSummaryProps {
  summary: SessionSummaryDto;
  /** Words graded unfamiliar during the session (chips → detail). */
  unfamiliarWords?: readonly WordBrief[];
  onMoreNew?: () => void;
  onMoreScreen?: () => void;
  busy?: boolean;
  className?: string;
}

export function SessionSummary({ summary, unfamiliarWords = [], onMoreNew, onMoreScreen, busy = false, className }: SessionSummaryProps) {
  const cards = summary.review + summary.new + summary.extra + summary.screen;
  const total = cards > 0 ? cards : 1;
  const hasGrades = summary.again + summary.hard + summary.good + summary.mastered > 0;
  const counts: { label: string; value: number }[] = [
    { label: zh.today.counts.review, value: summary.review },
    { label: zh.today.counts.new, value: summary.new },
    { label: zh.today.counts.screen, value: summary.screen },
    { label: zh.today.counts.extra, value: summary.extra },
  ].filter((c) => c.value > 0);
  const grades: { label: string; value: number }[] = [
    { label: zh.study.again, value: summary.again },
    { label: zh.study.hard, value: summary.hard },
    { label: zh.study.good, value: summary.good },
    { label: zh.study.master, value: summary.mastered },
  ].filter((c) => c.value > 0);

  return (
    <section className={cx('summary', className)} aria-labelledby="summary-title">
      <h2 id="summary-title" className="summary__title">
        {zh.study.summary.title}
      </h2>
      <ProgressRing done={total} total={total} caption={zh.today.done} className="summary__ring" />
      {counts.length > 0 && (
        <p className="summary__counts">
          {counts.map((c, i) => (
            <span key={c.label}>
              {i > 0 && <span className="summary__sep"> · </span>}
              {c.label} {c.value}
            </span>
          ))}
        </p>
      )}
      {hasGrades && (
        <p className="summary__grades muted">
          {grades.map((c, i) => (
            <span key={c.label}>
              {i > 0 && <span className="summary__sep"> · </span>}
              {c.label} {c.value}
            </span>
          ))}
        </p>
      )}
      <p className="summary__meta">
        <span>{zh.today.streak(summary.streak_days)}</span>
        {summary.study_minutes > 0 && <span className="summary__sep"> · </span>}
        {summary.study_minutes > 0 && <span>{zh.study.summary.minutes(summary.study_minutes)}</span>}
      </p>
      {unfamiliarWords.length > 0 && (
        <div className="summary__unfamiliar">
          <h3 className="summary__subtitle">{zh.study.summary.unfamiliarWords}</h3>
          <ul className="chips chips--md">
            {unfamiliarWords.map((w) => (
              <li key={w.id}>
                <Link className="chip chip--link" to={routePaths.word(w.id)} lang="en">
                  {w.display}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="summary__actions">
        {summary.can_request_more && onMoreNew && (
          <Button variant="primary" loading={busy} onClick={onMoreNew}>
            {zh.today.moreNew}
          </Button>
        )}
        {summary.can_request_more && onMoreScreen && (
          <Button variant="secondary" tone="screen" disabled={busy} onClick={onMoreScreen}>
            {zh.today.moreScreen}
          </Button>
        )}
        <Link className="btn btn--secondary btn--md" to={routePaths.screen}>
          <span className="btn__label">{zh.today.goScreen}</span>
        </Link>
        <Link className="btn btn--ghost btn--md" to={routePaths.today}>
          <span className="btn__label">{zh.common.backToToday}</span>
        </Link>
      </div>
    </section>
  );
}
