// P0 stub — replaced by WP8. Route `/history/:batchId` (onboarded): read-only batch; the real title is the batch date (FRONTEND §2).
import { useParams } from 'react-router';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function BatchPage() {
  const { batchId } = useParams();
  usePageTitle(zh.history.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.history.title}</h1>
      {batchId && <p className="muted">#{batchId}</p>}
    </section>
  );
}
