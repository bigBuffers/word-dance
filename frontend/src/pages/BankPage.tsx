// P0 stub — replaced by WP7. Route `/bank` (user): bank tabs, rows, add-words FAB (FRONTEND §5.7).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function BankPage() {
  usePageTitle(zh.bank.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.bank.title}</h1>
    </section>
  );
}
