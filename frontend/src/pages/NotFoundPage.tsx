// NotFoundPage — route `*` (FRONTEND §2): one action, back to today.
import { EmptyState } from '@/components/ui/EmptyState';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';

export default function NotFoundPage() {
  usePageTitle(zh.errors.notFound);
  return (
    <section className="page page--narrow">
      <EmptyState title={zh.errors.notFound} action={{ label: zh.common.backToToday, to: routePaths.today }} />
    </section>
  );
}
