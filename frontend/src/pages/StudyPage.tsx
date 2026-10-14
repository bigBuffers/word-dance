// P0 stub — replaced by WP8. Route `/study` (onboarded): the card session; `?batch=<id>` replays/finishes a batch (FRONTEND §5.1).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function StudyPage() {
  usePageTitle(zh.study.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.study.title}</h1>
    </section>
  );
}
