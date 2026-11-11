// ChildLoginPage — `/child-login` (guest; FRONTEND §2; API.md 107; docs/AUTH_SIGNUP_DESIGN.md §5.2, guardian + child): a child's own
// device signs in with the 8-digit one-time code the guardian generated on the children page (endpoint 99, valid 10 minutes). One
// `CodeField` with `length={8}` and no send button (the guardian's screen shows the code) → `POST /api/auth/child-login` → a 90-day
// session → `AuthContext.applyAuth` (the guest guard redirects). An expired / consumed / unknown code is 400 `invalid_code` with
// `attempts_left: 0` → `errors.codeExpired`; ten misses an hour from one address → 429 (`errors.rateLimitedIn`). `backToLogin` → /login.
import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { CodeField } from '@/components/ui/CodeField';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import '@/components/ui/auth.css';

/** The child login code has eight digits (API.md 99 / 107; `family.CHILD_CODE_LEN`). */
export const CHILD_CODE_LENGTH = 8;

export default function ChildLoginPage() {
  usePageTitle(zh.auth.childLogin);
  const { applyAuth } = useAuth();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = code.length === CHILD_CODE_LENGTH && !busy;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const res = await endpoints.childLogin({ code });
      await applyAuth(res); // <RequireGuest/> redirects from here
    } catch (err) {
      setError(errorMessage(err));
      setCode('');
      setBusy(false);
    }
  };

  return (
    <section className="page page--narrow auth">
      <header className="auth__brand">
        <h1 className="auth__name">{zh.app.name}</h1>
        <p className="auth__tagline">{zh.app.tagline}</p>
      </header>
      <h2 className="auth__title">{zh.auth.childLogin}</h2>
      <p className="auth__lead">{zh.auth.childLoginLead}</p>
      <form className="auth__form" onSubmit={submit} noValidate>
        <CodeField label={zh.auth.childLoginCode} length={CHILD_CODE_LENGTH} value={code} onChange={setCode} disabled={busy} autoFocus />
        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!canSubmit}>
          {zh.auth.login}
        </Button>
      </form>
      <p className="auth__links">
        <Link to={routePaths.login}>{zh.auth.backToLogin}</Link>
      </p>
    </section>
  );
}
