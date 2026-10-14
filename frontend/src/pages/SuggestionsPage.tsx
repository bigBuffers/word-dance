// P0 stub — replaced by WP7. Route `/bank/suggestions` (user): consolidation-suggestion inbox (FRONTEND §5.7).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function SuggestionsPage() {
  usePageTitle(zh.suggestions.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.suggestions.title}</h1>
    </section>
  );
}
