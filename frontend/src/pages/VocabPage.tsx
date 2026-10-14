// P0 stub — replaced by WP7. Route `/vocab` (user): vocabulary browser (FRONTEND §5.5).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function VocabPage() {
  usePageTitle(zh.vocab.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.vocab.title}</h1>
    </section>
  );
}
