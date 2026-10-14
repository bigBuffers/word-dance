// LoginPage — `/login` (guest; FRONTEND §2): username + password, link register (hidden when registration is closed
// unless `needs_setup`), and the first-admin notice "no account yet, the first registration becomes admin" + go register while
// `GET /api/health.needs_setup` is true. A successful login sets the session in AuthContext and the
// <RequireGuest/> guard redirects to `?next=` (or /today).
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router';
import { errorMessage } from '@/api/client';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { Field } from '@/components/ui/Field';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import './LoginPage.css';

export default function LoginPage() {
  usePageTitle(zh.auth.login);
  const { login, health, refreshHealth } = useAuth();
  const [params] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!health) void refreshHealth();
  }, [health, refreshHealth]);

  const needsSetup = health?.needs_setup === true;
  const registrationVisible = needsSetup || health?.registration_mode !== 'closed';
  const next = params.get('next');
  const registerTo = next ? `${routePaths.register}?next=${encodeURIComponent(next)}` : routePaths.register;
  const canSubmit = username.trim().length > 0 && password.length > 0 && !busy;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <section className="page page--narrow auth">
      <header className="auth__brand">
        <h1 className="auth__name">{zh.app.name}</h1>
        <p className="auth__tagline">{zh.app.tagline}</p>
      </header>
      <h2 className="auth__title">{zh.auth.login}</h2>
      {needsSetup && (
        <div className="auth__notice" role="status">
          {zh.auth.needsSetup}
          <Link to={registerTo}>{zh.auth.goRegister}</Link>
        </div>
      )}
      <form className="auth__form" onSubmit={submit} noValidate>
        <Field label={zh.auth.username} required>
          {(control) => (
            <input
              {...control}
              type="text"
              value={username}
              autoComplete="username"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              autoFocus
              maxLength={32}
              onChange={(e) => setUsername(e.target.value)}
            />
          )}
        </Field>
        <Field label={zh.auth.password} required>
          {(control) => <input {...control} type="password" value={password} autoComplete="current-password" maxLength={64} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!canSubmit}>
          {zh.auth.login}
        </Button>
      </form>
      {!needsSetup && registrationVisible && (
        <p className="auth__hint muted">
          {zh.auth.noAccount} <Link to={registerTo}>{zh.auth.register}</Link>
        </p>
      )}
    </section>
  );
}
