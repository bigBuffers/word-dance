// CodeSignIn — the sign-in-or-register-by-code entry shared by /login and /register (FRONTEND §2, §4; API.md §3.1,
// docs/AUTH_SIGNUP_DESIGN.md §5.2): target (a phone with the fixed +86 prefix, or an e-mail), the consent line that must be
// ticked BEFORE a code can be sent (the number is processed at the send), the self-hosted captcha when the server asks
// for it (`health.captcha`), the send button (endpoint 80, 60-s countdown) and the one 6-digit input → endpoint 81.
// 81 answers a session (→ `AuthContext.applyAuth`, the guard redirects), or — for a phone nobody logged in with for
// WD_PHONE_STALE_DAYS — a `StaleChallenge`: the sheet below asks "is this your account?" and takes the second factor
// (password, or an e-mail code of endpoint 82) through endpoint 83, or "not my account" through endpoint 84 after a
// confirmation. The challenge is server state (a one-time token); nothing here sets `user` before a cookie exists.
// The sheet renders OUTSIDE the <form> (its own form must not nest: a nested submit bubbled into the outer `submit` and
// re-posted endpoint 81), and the sent state belongs to the target the code went to — editing the target, switching the
// channel or closing the sheet (81 consumed the code) empties the code input and restarts the CodeField.
import { useState, type FormEvent } from 'react';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { CaptchaToken } from '@/api/endpoints';
import type { CodeChannel, ServerFlags, StaleChallenge } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { zh } from '@/i18n/zh';
import { legalUrls } from '@/routes';
import { EMAIL_RE, isMainlandPhone, phoneToE164 } from '@/utils/auth';
import { Button } from './Button';
import { CaptchaField } from './CaptchaField';
import { CodeField, CODE_LENGTH } from './CodeField';
import { ConfirmDialog } from './ConfirmDialog';
import { Field } from './Field';
import { PhoneField } from './PhoneField';
import { Segmented } from './Segmented';
import { Sheet } from './Sheet';
import './auth.css';

export interface CodeSignInProps {
  /** The channels the server can send on (`health.sms_enabled` → phone, `health.email_enabled` → email); tabs when both. */
  channels: readonly CodeChannel[];
  /** `health.captcha`: a public send must carry a captcha token. */
  captcha: boolean;
  registrationMode: ServerFlags['registration_mode'] | undefined;
  /** `zh.auth.loginOrRegister` on the login page, `zh.auth.register` on the register page. */
  submitLabel: string;
  className?: string;
}

/** The consent line: checkbox + "I have read and agree to the terms / privacy policy" linking the static legal pages. */
export function ConsentLine({ checked, onChange, disabled = false }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="auth__consent">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        {zh.auth.consentPrefix}
        <a href={legalUrls.terms} target="_blank" rel="noopener noreferrer">
          {zh.auth.terms}
        </a>
        <a href={legalUrls.privacy} target="_blank" rel="noopener noreferrer">
          {zh.auth.privacy}
        </a>
      </span>
    </label>
  );
}

export function CodeSignIn({ channels, captcha, registrationMode, submitLabel, className }: CodeSignInProps) {
  const { applyAuth } = useAuth();
  const [channel, setChannel] = useState<CodeChannel>(channels[0] ?? 'phone');
  const active: CodeChannel = channels.includes(channel) ? channel : (channels[0] ?? 'phone');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [consent, setConsent] = useState(false);
  const [captchaToken, setCaptchaToken] = useState<CaptchaToken | null>(null);
  const [captchaNonce, setCaptchaNonce] = useState(0);
  const [code, setCode] = useState('');
  const [invite, setInvite] = useState('');
  const [sentTo, setSentTo] = useState<string | null>(null); // the target the last code went to; `sent` only while it is still the target
  const [fieldKey, setFieldKey] = useState(0); // bumped to remount the CodeField (its countdown) when the sheet closes
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [challenge, setChallenge] = useState<StaleChallenge | null>(null);

  const target = active === 'phone' ? (isMainlandPhone(phone) ? phoneToE164(phone) : null) : EMAIL_RE.test(email.trim()) ? email.trim() : null;
  const sent = sentTo !== null && sentTo === target;
  const showInvite = registrationMode === 'invite';
  const canSend = consent && target !== null && (!captcha || captchaToken !== null) && !busy;
  const canSubmit = sent && code.length === CODE_LENGTH && !busy;

  const switchChannel = (next: CodeChannel) => {
    setChannel(next);
    setSentTo(null);
    setCode('');
    setError(null);
  };

  const resetCode = () => {
    setSentTo(null);
    setCode('');
    setFieldKey((k) => k + 1);
  };

  const send = async () => {
    if (!target) return;
    setError(null);
    try {
      await endpoints.sendCode({ channel: active, target, purpose: 'login', consent: true, ...(captcha && captchaToken ? { captcha: captchaToken } : {}) });
      setSentTo(target);
    } catch (e) {
      setError(errorMessage(e));
      throw e; // CodeField skips its countdown
    } finally {
      if (captcha) setCaptchaNonce((n) => n + 1); // a token is accepted once (also after `invalid_captcha`)
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (challenge) return; // the sheet owns the next step; nothing re-posts 81 while it is open
    if (!canSubmit || !target) return;
    setBusy(true);
    setError(null);
    try {
      const res = await endpoints.loginWithCode({ channel: active, target, code, ...(showInvite && invite.trim() ? { invite_code: invite.trim() } : {}) });
      if (res.challenge) {
        setChallenge(res.challenge);
        setBusy(false);
        return;
      }
      if (res.user && res.settings) {
        await applyAuth({ user: res.user, settings: res.settings }); // the guest guard redirects from here
        return;
      }
      setError(zh.errors.server);
      setBusy(false);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <>
      <form className={className ? `auth__form ${className}` : 'auth__form'} onSubmit={submit} noValidate>
        {channels.length > 1 && (
          <Segmented
            className="auth__entries"
            block
            aria-label={zh.auth.loginMethod}
            options={channels.map((c) => ({ value: c, label: c === 'phone' ? zh.auth.methodPhone : zh.auth.methodEmail }))}
            value={active}
            onChange={switchChannel}
          />
        )}
        {active === 'phone' ? (
          <PhoneField value={phone} onChange={setPhone} hint={zh.auth.phoneHint} disabled={busy} autoFocus />
        ) : (
          <Field label={zh.auth.emailAddress} required>
            {(control) => <input {...control} type="email" inputMode="email" autoComplete="email" disabled={busy} value={email} autoFocus onChange={(e) => setEmail(e.target.value)} />}
          </Field>
        )}
        <ConsentLine checked={consent} onChange={setConsent} disabled={busy} />
        {captcha && <CaptchaField nonce={captchaNonce} onChange={setCaptchaToken} disabled={busy} />}
        <CodeField key={`${active}:${target ?? ''}:${fieldKey}`} value={code} onChange={setCode} onSend={send} canSend={canSend} disabled={busy} />
        {showInvite && (
          <Field label={zh.auth.inviteForNew}>
            {(control) => <input {...control} type="text" autoComplete="off" autoCapitalize="characters" spellCheck={false} disabled={busy} value={invite} onChange={(e) => setInvite(e.target.value)} />}
          </Field>
        )}
        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!canSubmit}>
          {submitLabel}
        </Button>
      </form>
      <StaleChallengeSheet
        challenge={challenge}
        inviteCode={showInvite && invite.trim() ? invite.trim() : undefined}
        onClose={() => {
          setChallenge(null);
          resetCode(); // 81 consumed that code: a fresh one is needed
        }}
      />
    </>
  );
}

type Factor = 'password' | 'email';

/**
 * "Is this your account?" (design §5.2, recycled numbers): masked nickname + registration month; yes → the second factor the
 * challenge allows (password → 83 `{token, password}`; e-mail code → 82 then 83 `{token, code}`); neither available →
 * the contact-admin text; no → ConfirmDialog → 84 (the old binding is disputed, a new account is created for this phone).
 */
export function StaleChallengeSheet({ challenge, inviteCode, onClose }: { challenge: StaleChallenge | null; inviteCode?: string; onClose: () => void }) {
  const { applyAuth } = useAuth();
  const [factor, setFactor] = useState<Factor | null>(null);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [disputeOpen, setDisputeOpen] = useState(false);

  if (!challenge) return null;
  const canPassword = challenge.can_password;
  const canEmail = challenge.can_email;
  const chosen: Factor | null = factor ?? (canPassword ? 'password' : canEmail ? 'email' : null);
  const canConfirm = chosen === 'password' ? password.length > 0 : chosen === 'email' ? sent && code.length === CODE_LENGTH : false;

  const close = () => {
    if (busy) return;
    setPassword('');
    setCode('');
    setSent(false);
    setError(null);
    setFactor(null);
    onClose();
  };

  const sendEmailCode = async () => {
    setError(null);
    try {
      await endpoints.challengeEmail({ token: challenge.token });
      setSent(true);
    } catch (e) {
      setError(errorMessage(e));
      throw e;
    }
  };

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    e.stopPropagation(); // defensive: never let this submit reach an enclosing form
    if (!canConfirm || !chosen) return;
    setBusy(true);
    setError(null);
    try {
      const res = await endpoints.challengeConfirm({ token: challenge.token, ...(chosen === 'password' ? { password } : { code }) });
      await applyAuth(res);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  const dispute = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await endpoints.challengeDispute({ token: challenge.token, ...(inviteCode ? { invite_code: inviteCode } : {}) });
      setDisputeOpen(false);
      await applyAuth(res);
    } catch (err) {
      setDisputeOpen(false);
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <Sheet open onClose={close} title={zh.auth.staleTitle} dismissible={!busy}>
      <form className="auth__form" onSubmit={confirm} noValidate>
        <p className="auth__lead">
          <strong>{zh.auth.staleBody(challenge.display_name_masked, challenge.since)}</strong>
          <br />
          {zh.auth.staleHint}
        </p>
        {canPassword && canEmail && (
          <Segmented
            className="auth__entries"
            block
            aria-label={zh.auth.loginMethod}
            options={[
              { value: 'password', label: zh.auth.staleUsePassword },
              { value: 'email', label: zh.auth.staleUseEmail },
            ]}
            value={chosen ?? 'password'}
            onChange={(f) => {
              setFactor(f);
              setError(null);
            }}
          />
        )}
        {chosen === 'password' && (
          <Field label={zh.auth.password} required>
            {(control) => <input {...control} type="password" autoComplete="current-password" maxLength={64} disabled={busy} value={password} autoFocus onChange={(e) => setPassword(e.target.value)} />}
          </Field>
        )}
        {chosen === 'email' && (
          <>
            <p className="auth__lead">{zh.auth.staleEmailHint(challenge.email_masked ?? '')}</p>
            <CodeField value={code} onChange={setCode} onSend={sendEmailCode} disabled={busy} />
          </>
        )}
        {chosen === null && (
          <p className="auth__error" role="status">
            {zh.auth.staleContactAdmin}
          </p>
        )}
        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}
        {chosen !== null && (
          <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!canConfirm}>
            {zh.auth.staleYes}
          </Button>
        )}
        <div className="auth__links">
          <Button type="button" variant="ghost" tone="again" disabled={busy} onClick={() => setDisputeOpen(true)}>
            {zh.auth.staleNo}
          </Button>
        </div>
      </form>
      <ConfirmDialog open={disputeOpen} title={zh.auth.staleNo} message={zh.auth.staleDisputeConfirm} danger busy={busy} onConfirm={dispute} onCancel={() => setDisputeOpen(false)} />
    </Sheet>
  );
}
