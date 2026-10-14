// P0 stub — replaced by WP8. Route `/history` (onboarded): heat strip, streak, stubborn words, past batches (FRONTEND §5.8).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function HistoryPage() {
  usePageTitle(zh.history.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.history.title}</h1>
    </section>
  );
}
