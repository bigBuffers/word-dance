// ScreenPage — screening stage picker (FRONTEND §2): one card per stage from `GET /api/stages` with the unseen
// count (zh.screen.remaining(n)), a progress bar of screened words and the last picked stage highlighted.
import { Link } from 'react-router';
import { errorMessage } from '@/api/client';
import { getStages } from '@/api/endpoints';
import type { Stage, StageInfo } from '@/api/types';
import { EmptyState } from '@/components/ui/EmptyState';
import { Skeleton } from '@/components/ui/Skeleton';
import { cx } from '@/components/ui/cx';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { useApi } from '@/hooks/useApi';
import { readPref } from '@/hooks/useLocalPref';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import './ScreenPage.css';

export const SCREEN_STAGE_KEY = 'wd.screenStage';

const FULL_NAME: Record<Stage, string> = { xs: zh.stages.xsFull, zk: zh.stages.zkFull, gk: zh.stages.gkFull, cet4: zh.stages.cet4Full, cet6: zh.stages.cet6Full };

export function screenedFraction(info: StageInfo): number {
  if (info.total <= 0) return 0;
  return Math.min(1, Math.max(0, (info.total - info.unseen) / info.total));
}

export default function ScreenPage() {
  usePageTitle(zh.screen.title);
  const { data, error, loading, reload } = useApi((signal) => getStages(signal), []);
  const last = readPref<string | null>(SCREEN_STAGE_KEY, null);
  const items = data ? STAGE_ORDER.map((s) => data.items.find((i) => i.stage === s)).filter((i): i is StageInfo => i !== undefined) : [];

  return (
    <section className="page screen">
      <header className="screen__head">
        <h1 className="page__title">{zh.screen.title}</h1>
        <p className="muted screen__subtitle">{zh.screen.subtitle}</p>
      </header>
      {loading && !data && (
        <div className="screen__grid" aria-busy="true">
          {STAGE_ORDER.map((s) => (
            <Skeleton key={s} height={120} />
          ))}
        </div>
      )}
      {error && !data && <EmptyState title={errorMessage(error)} action={{ label: zh.common.retry, onClick: () => void reload() }} />}
      {data && (
        <ul className="screen__grid">
          {items.map((info) => {
            const pct = Math.round(screenedFraction(info) * 100);
            return (
              <li key={info.stage}>
                <Link className={cx('stage-card card', last === info.stage && 'stage-card--last')} to={routePaths.screenRun(info.stage)}>
                  <span className="stage-card__name">{zh.stages[info.stage]}</span>
                  <span className="stage-card__full muted">{FULL_NAME[info.stage]}</span>
                  <span className="stage-card__unseen">{zh.screen.remaining(info.unseen)}</span>
                  <span className="stage-card__bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={zh.stages[info.stage]}>
                    <span className="stage-card__fill" style={{ width: `${pct}%` }} />
                  </span>
                  <span className="stage-card__counts muted">
                    {zh.vocab.status.unfamiliar} {info.unfamiliar} · {zh.vocab.status.known} {info.known} · {zh.vocab.status.mastered} {info.mastered}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
