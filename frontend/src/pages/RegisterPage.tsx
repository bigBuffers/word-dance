// P0 stub — replaced by WP7. Route `/register` (guest): username, password, display name, e-mail, invite code (FRONTEND §2).
import { Link } from 'react-router';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';

export default function RegisterPage() {
  usePageTitle(zh.auth.register);
  return (
    <section className="page page--narrow">
      <h1 className="page__title">{zh.auth.register}</h1>
      <p className="muted">
        {zh.auth.hasAccount} <Link to="/login">{zh.auth.login}</Link>
      </p>
    </section>
  );
}
