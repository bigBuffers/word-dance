// RegisterPage — `/register` (guest; FRONTEND §2, API.md 2 / §3.1): in `verified` mode (after the bootstrap) the page is
// the shared code entry — phone / e-mail tabs by `health.sms_enabled` / `email_enabled`, the consent line, captcha, code →
// endpoint 81 creates the account (username + password come later, /welcome step 0 or settings); username/password
// registration (strength hint, optional display name / e-mail, invite code when `registration_mode='invite'`) stays
// for `open` / `invite` and for the bootstrap (`needs_setup`: "the first registration becomes admin", no invite field,
// any mode). A closed server without `needs_setup` shows registration closed. After registration <RequireGuest/>
// redirects (→ /welcome through RequireOnboarded).
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router';
import { errorMessage } from '@/api/client';
import type { RegisterBody } from '@/api/endpoints';
import type { CodeChannel } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { CodeSignIn } from '@/components/ui/CodeSignIn';
import { Field } from '@/components/ui/Field';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { EMAIL_RE, USERNAME_RE, passwordStrength, validationFieldMessages } from '@/utils/auth';
import '@/components/ui/auth.css';

// the helpers moved to utils/auth.ts (shared with /forgot and /welcome); re-exported for their tests and older imports
export { passwordStrength, validationFieldMessages };

export default function RegisterPage() {
  usePageTitle(zh.auth.register);
  const { register, health, refreshHealth } = useAuth();
  const [params] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [invite, setInvite] = useState('');
  const [touched, setTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!health) void refreshHealth();
  }, [health, refreshHealth]);

  const needsSetup = health?.needs_setup === true;
  const mode = health?.registration_mode ?? 'open';
  const closed = !needsSetup && mode === 'closed';
  const verified = !needsSetup && mode === 'verified';
  const showInvite = !needsSetup && mode === 'invite';
  // the channels the server can send a code on (API.md 1); none → the code sign-up cannot happen here
  const channels: CodeChannel[] = [...(health?.sms_enabled ? (['phone'] as const) : []), ...(health?.email_enabled ? (['email'] as const) : [])];
  const next = params.get('next');
  const loginTo = next ? `${routePaths.login}?next=${encodeURIComponent(next)}` : routePaths.login;

  const trimmedUser = username.trim();
  const trimmedEmail = email.trim();
  const usernameOk = USERNAME_RE.test(trimmedUser);
  const strength = passwordStrength(password, trimmedUser);
  const emailOk = !trimmedEmail || EMAIL_RE.test(trimmedEmail);
  const inviteOk = !showInvite || invite.trim().length > 0;
  const valid = usernameOk && strength >= 2 && password2 === password && emailOk && inviteOk;

  const usernameError = touched && !usernameOk ? zh.auth.usernameHint : null;
  const passwordError = touched && strength === 1 ? zh.errors.weakPassword : null;
  const mismatch = touched && password2 !== password ? zh.auth.mismatch : null;
  const emailError = touched && !emailOk ? zh.errors.invalidEmail : null;
  const inviteError = touched && !inviteOk ? zh.errors.invalidInvite : null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    const body: RegisterBody = { username: trimmedUser, password };
    if (displayName.trim()) body.display_name = displayName.trim();
    if (trimmedEmail) body.email = trimmedEmail;
    if (showInvite) body.invite_code = invite.trim();
    try {
      await register(body);
    } catch (err) {
      setError(validationFieldMessages(err) ?? errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <section className="page page--narrow auth">
      <header className="auth__brand">
        <h1 className="auth__name">{zh.app.name}</h1>
        <p className="auth__tagline">{zh.app.tagline}</p>
      </header>
      <h2 className="auth__title">{zh.auth.register}</h2>
      {needsSetup && (
        <div className="auth__notice" role="status">
          {zh.auth.firstUser}
        </div>
      )}
      {closed ? (
        <>
          <p className="auth__error" role="status">
            {zh.errors.registrationClosed}
          </p>
          <p className="auth__hint muted">
            {zh.auth.hasAccount} <Link to={loginTo}>{zh.auth.login}</Link>
          </p>
        </>
      ) : verified ? (
        <>
          {channels.length > 0 ? (
            <CodeSignIn channels={channels} captcha={health?.captcha === true} registrationMode={mode} submitLabel={zh.auth.register} />
          ) : (
            <p className="auth__error" role="status">
              {zh.auth.noChannel}
            </p>
          )}
          <p className="auth__hint muted">
            {zh.auth.hasAccount} <Link to={loginTo}>{zh.auth.login}</Link>
          </p>
        </>
      ) : (
        <>
          <form className="auth__form" onSubmit={submit} noValidate>
            <Field label={zh.auth.username} hint={usernameError ? undefined : zh.auth.usernameHint} error={usernameError} required>
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
            <Field label={zh.auth.password} hint={passwordError ? undefined : zh.auth.passwordHint} error={passwordError} required>
              {(control) => (
                <>
                  <input {...control} type="password" value={password} autoComplete="new-password" maxLength={64} onChange={(e) => setPassword(e.target.value)} />
                  <div className="auth__meter" data-level={strength} aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </div>
                </>
              )}
            </Field>
            <Field label={zh.auth.password2} error={mismatch} required>
              {(control) => <input {...control} type="password" value={password2} autoComplete="new-password" maxLength={64} onChange={(e) => setPassword2(e.target.value)} />}
            </Field>
            <Field label={zh.auth.displayName}>
              {(control) => <input {...control} type="text" value={displayName} autoComplete="nickname" maxLength={32} onChange={(e) => setDisplayName(e.target.value)} />}
            </Field>
            <Field label={zh.auth.email} error={emailError}>
              {(control) => <input {...control} type="email" value={email} autoComplete="email" inputMode="email" onChange={(e) => setEmail(e.target.value)} />}
            </Field>
            {showInvite && (
              <Field label={zh.auth.invite} error={inviteError} required>
                {(control) => <input {...control} type="text" value={invite} autoComplete="off" autoCapitalize="characters" spellCheck={false} onChange={(e) => setInvite(e.target.value)} />}
              </Field>
            )}
            {error && (
              <p className="auth__error" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" size="lg" block loading={busy}>
              {zh.auth.register}
            </Button>
          </form>
          <p className="auth__hint muted">
            {zh.auth.hasAccount} <Link to={loginTo}>{zh.auth.login}</Link>
          </p>
        </>
      )}
    </section>
  );
}
