// P0 stub — replaced by WP8. Route `/screen/:stage` (user): rapid known / unfamiliar triage (FRONTEND §5.4).
// Title: `zh.screen.title · zh.stages[stage]`.
import { useParams } from 'react-router';
import { isStage } from '@/components/word/StageChips';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function ScreenRunPage() {
  const { stage } = useParams();
  const title = isStage(stage) ? `${zh.screen.title} · ${zh.stages[stage]}` : zh.screen.title;
  usePageTitle(title);
  return (
    <section className="page">
      <h1 className="page__title">{title}</h1>
    </section>
  );
}
