// P0 stub — replaced by WP8. Route `/words/:idOrLemma` (user): word detail (FRONTEND §5.8).
import { useParams } from 'react-router';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function WordDetailPage() {
  const { idOrLemma } = useParams();
  usePageTitle(zh.word.title);
  return (
    <section className="page">
      <h1 className="page__title">{zh.word.title}</h1>
      {idOrLemma && (
        <p className="muted" lang="en">
          {idOrLemma}
        </p>
      )}
    </section>
  );
}
