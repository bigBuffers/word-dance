// auth — client-side mirrors of the account rules of API.md 2 / §3.1 (hints only; the server enforces them):
// username / e-mail shapes, the mainland phone number the code sign-in accepts, the password strength meter and the
// per-field messages of a 400 `validation_error`. Shared by /register, /forgot, /welcome step 0 and the settings sheets.
import { isApiError } from '@/api/client';

/** API.md 2: 2–32 chars of letters, digits, underscore or CJK — the range comes from code points so this file holds no Chinese text. */
export const USERNAME_RE = new RegExp(`^[A-Za-z0-9_${String.fromCharCode(0x4e00)}-${String.fromCharCode(0x9fa5)}]{2,32}$`);
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
/** The 11 digits of a mainland number (`1xxxxxxxxxx`) as typed after the fixed `+86` prefix (API.md §3.1 normalisation). */
export const PHONE_DIGITS_RE = /^1\d{10}$/;

export function isMainlandPhone(digits: string): boolean {
  return PHONE_DIGITS_RE.test(digits);
}

/** The E.164 form the API stores (`+86` + 11 digits). */
export function phoneToE164(digits: string): string {
  return `+86${digits}`;
}

/** 0 (empty) … 3 (strong) — a visual hint only; the server enforces API.md 2 / DESIGN §10. */
export function passwordStrength(password: string, username: string): 0 | 1 | 2 | 3 {
  if (!password) return 0;
  if (password.length < 8 || (username && password.toLowerCase() === username.toLowerCase())) return 1;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z\d]/].filter((re) => re.test(password)).length;
  if (password.length >= 12 && classes >= 3) return 3;
  return 2;
}

/** Joins the per-field messages of a 400 `validation_error` (API.md §1.1), or null. */
export function validationFieldMessages(e: unknown): string | null {
  if (!isApiError(e) || e.code !== 'validation_error') return null;
  const fields = e.details?.fields;
  if (typeof fields !== 'object' || fields === null) return null;
  const messages = Object.values(fields as Record<string, unknown>).filter((m): m is string => typeof m === 'string' && m.length > 0);
  return messages.length ? messages.join(' · ') : null;
}
