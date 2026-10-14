// P0 stub — replaced by WP7. Route `/admin` (admin): overview / users & invites / jobs / AI / reports / events / config tabs (FRONTEND §5.8).
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function AdminPage() {
  usePageTitle(zh.admin.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.admin.title}</h1>
    </section>
  );
}
