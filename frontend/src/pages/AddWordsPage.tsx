// P0 stub — replaced by WP7. Route `/bank/add` (user): paste many words, live preview, `?prefill=` (FRONTEND §5.6).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function AddWordsPage() {
  usePageTitle(zh.bank.add);
  return (
    <section className="page">
      <h1 className="page__title">{zh.bank.add}</h1>
    </section>
  );
}
