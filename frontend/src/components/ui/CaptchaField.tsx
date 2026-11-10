// CaptchaField — the self-hosted image captcha of the public code sends (API.md 79 → 80 / 90; design §5.2: no third-party
// script, CSP `img-src 'self' data:`): fetches a challenge, shows its PNG data URI and takes the 4 digits; `onChange`
// receives the `CaptchaToken` (id / exp / sig + answer) once four digits are typed, null otherwise. A token is accepted
// once, so the parent bumps `nonce` after every send attempt (success or `invalid_captcha`) and a new image loads;
// the refresh link (`zh.auth.captchaRefresh`) and a tap on the image reload it too.
import { useEffect, useRef, useState } from 'react';
import { errorMessage, isAbortError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { CaptchaToken } from '@/api/endpoints';
import type { CaptchaChallenge } from '@/api/types';
import { zh } from '@/i18n/zh';
import { Field } from './Field';
import './auth.css';

export const CAPTCHA_LENGTH = 4;

export interface CaptchaFieldProps {
  onChange: (token: CaptchaToken | null) => void;
  /** Increment to load a fresh challenge (after a send consumed the token). */
  nonce?: number;
  disabled?: boolean;
}

export function CaptchaField({ onChange, nonce = 0, disabled = false }: CaptchaFieldProps) {
  const [challenge, setChallenge] = useState<CaptchaChallenge | null>(null);
  const [answer, setAnswer] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setAnswer('');
    onChangeRef.current(null);
    endpoints.getCaptcha(controller.signal).then(
      (c) => {
        if (controller.signal.aborted) return;
        setChallenge(c);
        setLoading(false);
      },
      (e: unknown) => {
        if (controller.signal.aborted || isAbortError(e)) return;
        setChallenge(null);
        setError(errorMessage(e));
        setLoading(false);
      },
    );
    return () => controller.abort();
  }, [nonce, tick]);

  const reload = () => setTick((t) => t + 1);
  const update = (raw: string) => {
    const digits = raw.replace(/\D/g, '').slice(0, CAPTCHA_LENGTH);
    setAnswer(digits);
    onChangeRef.current(challenge && digits.length === CAPTCHA_LENGTH ? { id: challenge.id, exp: challenge.exp, sig: challenge.sig, answer: digits } : null);
  };

  return (
    <Field label={zh.auth.captcha} hint={zh.auth.captchaHint} error={error} required>
      {(control) => (
        <>
          <div className="captcha">
            <button type="button" className="captcha__image" onClick={reload} disabled={disabled} title={zh.auth.captchaRefresh}>
              {challenge && !loading ? <img src={challenge.image} alt={zh.auth.captchaAlt} width={120} height={44} /> : <span className="captcha__loading">{loading ? zh.auth.captchaLoading : zh.common.retry}</span>}
            </button>
            <input
              {...control}
              type="text"
              inputMode="numeric"
              autoComplete="off"
              pattern="[0-9]{4}"
              maxLength={CAPTCHA_LENGTH}
              disabled={disabled || !challenge}
              value={answer}
              onChange={(e) => update(e.target.value)}
            />
          </div>
          <button type="button" className="captcha__refresh" onClick={reload} disabled={disabled || loading}>
            {zh.auth.captchaRefresh}
          </button>
        </>
      )}
    </Field>
  );
}
