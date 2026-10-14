// P0 stub — replaced by WP8. Route `/screen` (user): stage picker cards with unseen counts (FRONTEND §2).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function ScreenPage() {
  usePageTitle(zh.screen.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.screen.title}</h1>
      <p className="muted">{zh.screen.subtitle}</p>
    </section>
  );
}
