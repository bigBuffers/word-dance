// ForgotPasswordPage — `/forgot` (guest; FRONTEND §2, API.md 90 / 91, docs/AUTH_SIGNUP_DESIGN.md §5.2 forgot password). Step 1:
// the identifier (username / phone / e-mail) + the captcha while `health.captcha` → endpoint 90, which always answers 202 (an
// unknown account or one without a channel looks the same — no enumeration), so the page simply moves on. Step 2: the
// 6-digit code + the new password (strength meter of utils/auth) → endpoint 91 → every session revoked → /login?reset=1
// (keeping `?next`), where the login page shows `zh.auth.resetDone`. The resend goes back to step 1 (a captcha token is single-use).
import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { CaptchaToken } from '@/api/endpoints';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { CaptchaField } from '@/components/ui/CaptchaField';
import { CodeField, CODE_LENGTH } from '@/components/ui/CodeField';
import { Field } from '@/components/ui/Field';
import { usePageTitle } from '@/hooks/usePageTitle';
import { zh } from '@/i18n/zh';
import { routePaths } from '@/routes';
import { passwordStrength, validationFieldMessages } from '@/utils/auth';
import '@/components/ui/auth.css';

export default function ForgotPasswordPage() {
  usePageTitle(zh.auth.forgotTitle);
  const { health, refreshHealth } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [step, setStep] = useState<1 | 2>(1);
  const [identifier, setIdentifier] = useState('');
  const [captchaToken, setCaptchaToken] = useState<CaptchaToken | null>(null);
  const [captchaNonce, setCaptchaNonce] = useState(0);
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!health) void refreshHealth();
  }, [health, refreshHealth]);

  const captcha = health?.captcha === true;
  const next = params.get('next');
  const loginTo = next ? `${routePaths.login}?next=${encodeURIComponent(next)}` : routePaths.login;
  const trimmed = identifier.trim();
  const canSend = trimmed.length > 0 && (!captcha || captchaToken !== null) && !busy;
  const strength = passwordStrength(password, trimmed);
  const passwordError = touched && strength === 1 ? zh.errors.weakPassword : null;
  const mismatch = touched && password2 !== password ? zh.auth.mismatch : null;
  const canReset = code.length === CODE_LENGTH && strength >= 2 && password2 === password && !busy;

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSend) return;
    setBusy(true);
    setError(null);
    try {
      await endpoints.forgotPassword({ identifier: trimmed, ...(captcha && captchaToken ? { captcha: captchaToken } : {}) });
      setStep(2);
    } catch (err) {
      setError(errorMessage(err));
      if (captcha) setCaptchaNonce((n) => n + 1); // the token was consumed either way
    } finally {
      setBusy(false);
    }
  };

  const reset = async (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!canReset) return;
    setBusy(true);
    setError(null);
    try {
      await endpoints.resetPassword({ identifier: trimmed, code, new_password: password });
      navigate(`${loginTo}${next ? '&' : '?'}reset=1`, { replace: true }); // the original destination survives the detour
    } catch (err) {
      setError(validationFieldMessages(err) ?? errorMessage(err));
      setBusy(false);
    }
  };

  const backToSend = () => {
    setStep(1);
    setCode('');
    setError(null);
    if (captcha) setCaptchaNonce((n) => n + 1);
  };

  return (
    <section className="page page--narrow auth">
      <header className="auth__brand">
        <h1 className="auth__name">{zh.app.name}</h1>
        <p className="auth__tagline">{zh.app.tagline}</p>
      </header>
      <h2 className="auth__title">{zh.auth.forgotTitle}</h2>
      {step === 1 ? (
        <form className="auth__form" onSubmit={send} noValidate>
          <p className="auth__lead">{zh.auth.forgotHint}</p>
          <Field label={zh.auth.identifier} required>
            {(control) => (
              <input {...control} type="text" autoComplete="username" autoCapitalize="off" autoCorrect="off" spellCheck={false} autoFocus maxLength={254} value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
            )}
          </Field>
          {captcha && <CaptchaField nonce={captchaNonce} onChange={setCaptchaToken} disabled={busy} />}
          {error && (
            <p className="auth__error" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!canSend}>
            {zh.auth.sendCode}
          </Button>
        </form>
      ) : (
        <form className="auth__form" onSubmit={reset} noValidate>
          <div className="auth__notice" role="status">
            {zh.auth.forgotSent}
          </div>
          <CodeField value={code} onChange={setCode} hint={zh.auth.codeHint} disabled={busy} autoFocus />
          <Field label={zh.settings.newPassword} hint={passwordError ? undefined : zh.auth.passwordHint} error={passwordError} required>
            {(control) => (
              <>
                <input {...control} type="password" autoComplete="new-password" maxLength={64} disabled={busy} value={password} onChange={(e) => setPassword(e.target.value)} />
                <div className="auth__meter" data-level={strength} aria-hidden="true">
                  <span />
                  <span />
                  <span />
                </div>
              </>
            )}
          </Field>
          <Field label={zh.auth.password2} error={mismatch} required>
            {(control) => <input {...control} type="password" autoComplete="new-password" maxLength={64} disabled={busy} value={password2} onChange={(e) => setPassword2(e.target.value)} />}
          </Field>
          {error && (
            <p className="auth__error" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!canReset}>
            {zh.auth.resetPassword}
          </Button>
          <p className="auth__links">
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={backToSend}>
              {zh.auth.backToSend}
            </Button>
          </p>
        </form>
      )}
      <p className="auth__hint muted">
        <Link to={loginTo}>{zh.common.back}</Link>
      </p>
    </section>
  );
}
