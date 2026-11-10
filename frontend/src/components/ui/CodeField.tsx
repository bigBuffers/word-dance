// CodeField — the one 6-digit verification-code input of every code flow (sign-in, bind / rebind / re-authentication,
// forgot password; FRONTEND §4): a single <input> with `autoComplete="one-time-code"` + `inputMode="numeric"` (a split
// six-box input breaks the iOS / Android SMS autofill), digits only, next to the send button that turns into a 60-second
// countdown once a send succeeded (the code's 10-minute validity is the field hint). `onSend` performs the request
// (endpoint 80 / 82 / 85 / 90) and reports its own errors; the countdown starts when it resolves — or, after a 429
// `rate_limited`, for the server's `retry_after_s` (the send already counted against the per-target window, so the button
// waits it out); any other rejection (503, captcha) leaves the button usable. Without `onSend` the field is just the input
// (the code was sent by an earlier step).
import { useEffect, useState, type ReactNode } from 'react';
import { isApiError } from '@/api/client';
import { zh } from '@/i18n/zh';
import { Button } from './Button';
import { Field } from './Field';
import './auth.css';

/** Seconds before a resend is offered again (the server's per-target limit is 1 per minute, API.md §1). */
export const RESEND_COOLDOWN_S = 60;
export const CODE_LENGTH = 6;

export interface CodeFieldProps {
  value: string;
  onChange: (digits: string) => void;
  /** Sends (or re-sends) the code; rejections are the caller's to show. Omitted → no send button. */
  onSend?: () => Promise<void>;
  /** The send button is enabled only while true (target typed, consent given, captcha filled). Default true. */
  canSend?: boolean;
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  disabled?: boolean;
  autoFocus?: boolean;
  /** Stable control id (tests / labels); generated otherwise. */
  id?: string;
}

export function CodeField({ value, onChange, onSend, canSend = true, label = zh.auth.code, hint, error, disabled = false, autoFocus = false, id }: CodeFieldProps) {
  const [sending, setSending] = useState(false);
  const [sentOnce, setSentOnce] = useState(false);
  const [remaining, setRemaining] = useState(0);

  // one timeout per tick: the countdown survives re-renders and stops by itself at 0
  useEffect(() => {
    if (remaining <= 0) return;
    const timer = window.setTimeout(() => setRemaining((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => window.clearTimeout(timer);
  }, [remaining]);

  const send = async () => {
    if (!onSend || sending || remaining > 0 || !canSend) return;
    setSending(true);
    try {
      await onSend();
      setSentOnce(true);
      setRemaining(RESEND_COOLDOWN_S);
    } catch (e) {
      // the caller displayed the error; a 429 names the window to wait, anything else leaves the button usable
      if (isApiError(e) && e.code === 'rate_limited') setRemaining(Math.max(1, Math.ceil(e.detailNumber('retry_after_s') ?? RESEND_COOLDOWN_S)));
    } finally {
      setSending(false);
    }
  };

  const sendLabel = remaining > 0 ? zh.auth.resendIn(remaining) : sentOnce ? zh.auth.resend : zh.auth.sendCode;
  const shownHint = hint ?? (sentOnce ? zh.auth.codeHint : undefined);

  return (
    <Field label={label} hint={shownHint} error={error} required {...(id ? { htmlFor: id } : {})}>
      {(control) => (
        <div className="code-field">
          <input
            {...control}
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]{6}"
            maxLength={CODE_LENGTH}
            autoFocus={autoFocus}
            disabled={disabled}
            value={value}
            onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, CODE_LENGTH))}
          />
          {onSend && (
            <Button type="button" size="md" loading={sending} disabled={disabled || !canSend || remaining > 0} onClick={() => void send()}>
              {sendLabel}
            </Button>
          )}
        </div>
      )}
    </Field>
  );
}
