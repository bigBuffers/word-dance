// P0 stub — replaced by WP7. Route `*`: not-found page with a back-to-today action (FRONTEND §2).
import { Link } from 'react-router';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function NotFoundPage() {
  usePageTitle(zh.errors.notFound);
  return (
    <section className="page page--narrow">
      <h1 className="page__title">{zh.errors.notFound}</h1>
      <Link className="btn btn--primary btn--md" to="/today">
        <span className="btn__label">{zh.common.backToToday}</span>
      </Link>
    </section>
  );
}
