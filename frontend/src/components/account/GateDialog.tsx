// GateDialog — the guardian gate (docs/AUTH_SIGNUP_DESIGN.md §5.2, switching and boundaries; API.md 102 / 105; FRONTEND §4): a
// Segmented over the factors the guardian holds — PIN, password, verification code — and one input. Two modes. `gate`: a guardian in
// its own session passes endpoint 102 and gets the 10-minute stamp the G+gate endpoints (95–101, 103) need; `pinSet` / `hasPassword`
// decide which factors are offered (the code is always one: endpoint 85 `{channel, purpose:'reauth'}` to the guardian's own phone or
// verified e-mail), `onPassed(gate_until)` reports the stamp. `switch-back`: a switched child session becomes the guardian's again
// through endpoint 105 — the guardian's factors are unknown on the child's side, so PIN, password and code are all offered and the
// server answers (`invalid_pin` when no PIN exists, the password hint when none is set); the code goes through endpoint 106
// `{channel}` (channels offered by the server's `sms_enabled` / `email_configured` flags); the guardian's `AuthResponse` is installed
// with `applyAuth` (never `logout()`), then `onSwitched()`. 423 `account_locked` (`errors.accountLocked(retry_after_s)`), 401
// `invalid_pin` (`errors.invalidPin`) and the other codes read their copy through `errorMessage`; a 400 `validation_error` shows its
// field message (an account without a password, a guardian without a phone). Mounted only while `open`.
import { useState, type FormEvent } from 'react';
import { errorMessage } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { GateBody } from '@/api/endpoints';
import type { CodeChannel } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { Button } from '@/components/ui/Button';
import { CodeField, CODE_LENGTH } from '@/components/ui/CodeField';
import { Field } from '@/components/ui/Field';
import { Segmented } from '@/components/ui/Segmented';
import { Sheet } from '@/components/ui/Sheet';
import { useToast } from '@/hooks/useToast';
import { zh } from '@/i18n/zh';
import { validationFieldMessages } from '@/utils/auth';
import '@/components/ui/auth.css';

export type GateMode = 'gate' | 'switch-back';
export type GateFactor = 'pin' | 'password' | 'code';
/** The guardian PIN has six digits (API.md 95 / 103; `family.PIN_RE`). */
export const PIN_LENGTH = 6;
export const PIN_RE = /^\d{6}$/;

export interface GateDialogProps {
  open: boolean;
  mode: GateMode;
  /** gate mode: the guardian has a PIN (`ChildrenResponse.pin_set`). Switch-back offers the PIN regardless. */
  pinSet?: boolean;
  /** gate mode: the guardian has a password (`User.has_password`). Switch-back offers the password regardless. */
  hasPassword?: boolean;
  onClose: () => void;
  /** gate mode: endpoint 102 passed — `GateResponse.gate_until`. */
  onPassed?: (gateUntil: string) => void;
  /** switch-back mode: endpoint 105 passed and the guardian's session is installed. */
  onSwitched?: () => void;
}

/** The factors offered, in display order; the code is always available (the server names the missing channel otherwise). */
export function gateFactors(mode: GateMode, pinSet: boolean, hasPassword: boolean): GateFactor[] {
  if (mode === 'switch-back') return ['pin', 'password', 'code'];
  return [...(pinSet ? (['pin'] as const) : []), ...(hasPassword ? (['password'] as const) : []), 'code'];
}

const FACTOR_LABEL: Record<GateFactor, string> = { pin: zh.children.gatePin, password: zh.children.gatePassword, code: zh.children.gateCode };

export function GateDialog({ open, mode, pinSet = false, hasPassword = false, onClose, onPassed, onSwitched }: GateDialogProps) {
  const { user, server, applyAuth } = useAuth();
  const toast = useToast();
  const [choice, setChoice] = useState<GateFactor | null>(null);
  const [channelChoice, setChannelChoice] = useState<CodeChannel | null>(null);
  const [pin, setPin] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const factors = gateFactors(mode, pinSet, hasPassword);
  const factor: GateFactor = choice !== null && factors.includes(choice) ? choice : (factors[0] ?? 'code');
  const smsOn = server?.sms_enabled === true;
  const mailOn = server?.email_configured !== false;
  // gate mode knows the guardian's identities; switch-back only knows what the server can send on
  const channels: CodeChannel[] =
    mode === 'gate'
      ? [...(smsOn && user?.phone_masked ? (['phone'] as const) : []), ...(mailOn && user?.email && user.email_verified ? (['email'] as const) : [])]
      : [...(smsOn ? (['phone'] as const) : []), ...(mailOn ? (['email'] as const) : [])];
  const channel: CodeChannel | null = channelChoice !== null && channels.includes(channelChoice) ? channelChoice : (channels[0] ?? null);
  const channelLabel = (c: CodeChannel) => (mode === 'gate' ? (c === 'phone' ? (user?.phone_masked ?? '') : (user?.email ?? '')) : c === 'phone' ? zh.auth.methodPhone : zh.auth.methodEmail);
  const ready = !busy && (factor === 'pin' ? pin.length === PIN_LENGTH : factor === 'password' ? password.length > 0 : code.length === CODE_LENGTH);

  const reset = () => {
    setPin('');
    setPassword('');
    setCode('');
    setError(null);
    setChoice(null);
    setBusy(false);
  };
  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const sendCode = async () => {
    if (!channel) return;
    setError(null);
    try {
      if (mode === 'gate') await endpoints.requestAccountCode({ channel, purpose: 'reauth' });
      else await endpoints.requestSwitchCode({ channel });
      toast.success(zh.auth.codeSent);
    } catch (e) {
      setError(validationFieldMessages(e) ?? errorMessage(e));
      throw e; // the CodeField skips its countdown
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    const body: GateBody = factor === 'pin' ? { pin } : factor === 'password' ? { password } : { code };
    setBusy(true);
    setError(null);
    try {
      if (mode === 'gate') {
        const res = await endpoints.passGate(body);
        reset();
        onPassed?.(res.gate_until);
      } else {
        const res = await endpoints.switchBack(body);
        await applyAuth(res); // the guardian's session replaces the child's on this device; no sign-out event
        reset();
        onSwitched?.();
      }
    } catch (err) {
      setError(validationFieldMessages(err) ?? errorMessage(err));
      setBusy(false);
      if (factor === 'pin') setPin('');
    }
  };

  return (
    <Sheet open onClose={close} title={zh.children.gateTitle} dismissible={!busy}>
      <form className="auth__form" onSubmit={submit} noValidate>
        <p className="auth__lead">{zh.children.gateLead}</p>
        {factors.length > 1 && (
          <Segmented
            className="auth__entries"
            block
            aria-label={zh.children.gateTitle}
            options={factors.map((f) => ({ value: f, label: FACTOR_LABEL[f] }))}
            value={factor}
            onChange={(f) => {
              setChoice(f);
              setError(null);
            }}
          />
        )}
        {factor === 'pin' && (
          <Field label={zh.children.pin} required>
            {(control) => (
              <input
                {...control}
                type="password"
                inputMode="numeric"
                autoComplete="off"
                pattern="[0-9]{6}"
                maxLength={PIN_LENGTH}
                autoFocus
                disabled={busy}
                value={pin}
                onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, PIN_LENGTH))}
              />
            )}
          </Field>
        )}
        {factor === 'password' && (
          <Field label={zh.auth.password} required>
            {(control) => <input {...control} type="password" autoComplete="current-password" maxLength={64} autoFocus disabled={busy} value={password} onChange={(e) => setPassword(e.target.value)} />}
          </Field>
        )}
        {factor === 'code' &&
          (channel === null ? (
            <p className="auth__error" role="status">
              {zh.settings.reauthUnavailable}
            </p>
          ) : (
            <>
              {channels.length > 1 && (
                <Segmented size="sm" className="auth__entries" aria-label={zh.settings.reauthVia} options={channels.map((c) => ({ value: c, label: channelLabel(c) }))} value={channel} onChange={setChannelChoice} />
              )}
              {channels.length === 1 && (
                <p className="auth__lead">
                  {zh.settings.reauthVia} {channelLabel(channel)}
                </p>
              )}
              <CodeField value={code} onChange={setCode} onSend={sendCode} canSend={channel !== null} disabled={busy} />
            </>
          ))}
        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" variant="primary" size="lg" block loading={busy} disabled={!ready}>
          {zh.children.gateVerify}
        </Button>
      </form>
    </Sheet>
  );
}
