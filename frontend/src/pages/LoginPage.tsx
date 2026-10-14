// P0 stub — replaced by WP7. Route `/login` (guest): username + password, register link, needs_setup notice (FRONTEND §2).
import { Link } from 'react-router';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function LoginPage() {
  usePageTitle(zh.auth.login);
  return (
    <section className="page page--narrow">
      <h1 className="page__title">{zh.auth.login}</h1>
      <p className="muted">
        {zh.auth.noAccount} <Link to="/register">{zh.auth.register}</Link>
      </p>
    </section>
  );
}
