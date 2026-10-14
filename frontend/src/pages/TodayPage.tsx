// P0 stub — replaced by WP8. Route `/today` (onboarded): today's batch (FRONTEND §2, §5.3).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function TodayPage() {
  usePageTitle(zh.today.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.today.title}</h1>
    </section>
  );
}
