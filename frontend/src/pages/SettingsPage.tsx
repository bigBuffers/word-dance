// P0 stub — replaced by WP7. Route `/settings` (user): push / learning / account / about sections (FRONTEND §5.8).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function SettingsPage() {
  usePageTitle(zh.settings.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.settings.title}</h1>
    </section>
  );
}
