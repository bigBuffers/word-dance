// PhoneField — a mainland mobile number: fixed `+86` prefix, 11 digits (`1xxxxxxxxxx`), `inputMode="tel"` and
// `autoComplete="tel-national"` so the keyboard and the browser's saved number fit (FRONTEND §4; API.md §3.1 normalises
// the same digits to E.164). The value is the digits only; `utils/auth.phoneToE164` builds the wire form.
import type { ReactNode } from 'react';
import { zh } from '@/i18n/zh';
import { Field } from './Field';
import './auth.css';

export const PHONE_DIGITS = 11;

export interface PhoneFieldProps {
  value: string;
  onChange: (digits: string) => void;
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  disabled?: boolean;
  autoFocus?: boolean;
  id?: string;
}

export function PhoneField({ value, onChange, label = zh.auth.phone, hint, error, required = true, disabled = false, autoFocus = false, id }: PhoneFieldProps) {
  return (
    <Field label={label} hint={hint} error={error} required={required} {...(id ? { htmlFor: id } : {})}>
      {(control) => (
        <div className="phone-field">
          <span className="phone-field__prefix" aria-hidden="true">
            {zh.auth.phonePrefix}
          </span>
          <input
            {...control}
            type="tel"
            inputMode="tel"
            autoComplete="tel-national"
            maxLength={PHONE_DIGITS}
            autoFocus={autoFocus}
            disabled={disabled}
            value={value}
            onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, PHONE_DIGITS))}
          />
        </div>
      )}
    </Field>
  );
}
