// word-Dance HTTP client (FRONTEND.md §1 `api/client.ts`, API.md §1 conventions, DESIGN §10).
//
// * same-origin cookie session (`credentials: 'same-origin'`), JSON in/out;
// * every non-GET request carries the CSRF header `X-WD-Request: 1`;
// * the API error envelope `{error:{code,message,details}}` becomes a thrown `ApiError`;
// * a 401 with code `unauthorized` (expired/missing session) dispatches the window event
//   `auth:expired` so `AuthContext` can clear the session. A 401 `invalid_credentials` from
//   the login endpoint is an ordinary error and does NOT dispatch it.
import { zh } from '@/i18n/zh';
import type { ApiError as ApiErrorEnvelope } from './types';

export type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
export type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue>;

export interface RequestOptions {
  /** Query-string parameters. `undefined`/`null` are skipped; booleans are sent as `1`/`0` (API.md uses 0|1 flags). */
  query?: Query;
  signal?: AbortSignal;
  /** Extra headers (rarely needed). */
  headers?: Record<string, string>;
}

/** Window event dispatched when the server answers 401 `unauthorized`. `detail: { path }`. */
export const AUTH_EXPIRED_EVENT = 'auth:expired';
/** Dispatched by `AuthContext.logout()` after an explicit sign-out (the native shell cancels its reminder on it, never on an expiry). */
export const AUTH_SIGNED_OUT_EVENT = 'auth:signed-out';
/** CSRF header required on every non-GET `/api/*` request (API.md §1). */
export const CSRF_HEADER = 'X-WD-Request';

/** A failed API call. `message` is the server's zh message (may be empty); use `errorMessage()` for display. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown> | undefined;
  readonly requestId: string | null;

  constructor(code: string, status: number, message: string, details?: Record<string, unknown>, requestId: string | null = null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
    this.requestId = requestId;
  }

  /** A finite number stored under `details[key]` (e.g. `retry_after_s`), or `null`. */
  detailNumber(key: string): number | null {
    const v = this.details?.[key];
    return typeof v === 'number' && Number.isFinite(v) ? v : null;
  }
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

/** True for a fetch aborted through an `AbortSignal` (never surfaced to the user). */
export function isAbortError(e: unknown): boolean {
  return typeof e === 'object' && e !== null && (e as { name?: unknown }).name === 'AbortError';
}

/** Serialises a query object; empty → ''. Booleans become 1/0, null/undefined are omitted. */
export function buildQuery(query?: Query): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    params.set(key, typeof value === 'boolean' ? (value ? '1' : '0') : String(value));
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

function isEnvelope(x: unknown): x is ApiErrorEnvelope {
  if (typeof x !== 'object' || x === null) return false;
  const err = (x as { error?: unknown }).error;
  return typeof err === 'object' && err !== null && typeof (err as { code?: unknown }).code === 'string';
}

function defaultCode(status: number): string {
  switch (status) {
    case 401:
      return 'unauthorized';
    case 403:
      return 'forbidden';
    case 404:
      return 'not_found';
    case 429:
      return 'rate_limited';
    default:
      return status >= 500 ? 'internal_error' : 'http_error';
  }
}

function dispatchAuthExpired(path: string): void {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') return;
  window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { path } }));
}

async function send(method: Method, path: string, body: unknown, options: RequestOptions | undefined): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options?.headers };
  if (method !== 'GET') headers[CSRF_HEADER] = '1';
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const init: RequestInit = { method, headers, credentials: 'same-origin', cache: 'no-store' };
  if (body !== undefined) init.body = JSON.stringify(body);
  if (options?.signal) init.signal = options.signal;
  try {
    return await fetch(path + buildQuery(options?.query), init);
  } catch (e) {
    if (isAbortError(e)) throw e;
    throw new ApiError('network', 0, zh.errors.network);
  }
}

/** The `ApiError` for a non-OK response (envelope parsed when present); a 401 `unauthorized` also dispatches `auth:expired`. */
export async function toApiError(res: Response, path: string): Promise<ApiError> {
  const text = await res.text().catch(() => '');
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  const env = isEnvelope(parsed) ? parsed.error : null;
  const code = env?.code ?? defaultCode(res.status);
  const err = new ApiError(code, res.status, env?.message ?? '', env?.details, res.headers.get('X-Request-Id'));
  if (res.status === 401 && code === 'unauthorized') dispatchAuthExpired(path);
  return err;
}

/**
 * Performs one JSON API call. Resolves with the parsed body (`undefined` for 204 / empty bodies),
 * rejects with `ApiError` (or the original `AbortError` when `options.signal` aborted).
 */
export async function request<T>(method: Method, path: string, body?: unknown, options?: RequestOptions): Promise<T> {
  const res = await send(method, path, body, options);
  if (!res.ok) throw await toApiError(res, path);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError('invalid_response', res.status, zh.errors.server, undefined, res.headers.get('X-Request-Id'));
  }
}

/** Like `request` but returns the raw response text (used for `GET /api/account/export`). */
export async function requestText(method: Method, path: string, options?: RequestOptions): Promise<string> {
  const res = await send(method, path, undefined, { ...options, headers: { Accept: '*/*', ...options?.headers } });
  if (!res.ok) throw await toApiError(res, path);
  return res.text();
}

/** Method shorthands used by `endpoints.ts`. */
export const api = {
  get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, undefined, { query, signal }),
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('POST', path, body, options),
  put: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PUT', path, body, options),
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PATCH', path, body, options),
  delete: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('DELETE', path, body, options),
};

/**
 * Display text for any thrown value: deterministic client copy by error code (`zh.errors`),
 * then the server's zh envelope message, then a generic fallback. Never shows raw codes.
 */
export function errorMessage(e: unknown): string {
  if (!isApiError(e)) return zh.errors.server;
  const z = zh.errors;
  switch (e.code) {
    case 'network':
      return z.network;
    case 'unauthorized':
      return z.unauthorized;
    case 'forbidden':
    case 'account_disabled':
      return z.forbidden;
    case 'csrf_rejected':
      return z.csrf;
    case 'not_found':
    case 'word_not_found':
    case 'batch_not_found':
      return z.notFound;
    case 'rate_limited': {
      const retry = e.detailNumber('retry_after_s'); // the server's window when it names one (code sends, lookups)
      return retry !== null && retry > 0 ? z.rateLimitedIn(Math.ceil(retry)) : z.rateLimited;
    }
    case 'internal_error':
    case 'invalid_response':
    case 'http_error':
      return z.server;
    case 'invalid_word':
      return z.invalidWord;
    case 'too_many_words':
      return z.tooManyWords;
    case 'weak_password':
      return z.weakPassword;
    case 'username_taken':
      return z.usernameTaken;
    case 'email_taken':
      return z.emailTaken;
    case 'invalid_credentials':
      return z.invalidCredentials;
    case 'account_locked':
      return z.accountLocked(e.detailNumber('retry_after_s') ?? 900);
    case 'registration_closed':
      return z.registrationClosed;
    case 'invalid_invite':
      return z.invalidInvite;
    case 'budget_exhausted':
      return z.budgetExhausted;
    case 'ai_disabled':
      return z.aiDisabled;
    case 'email_not_verified':
      return z.emailNotVerified;
    case 'smtp_unconfigured':
      return z.smtpUnconfigured;
    case 'webhook_unconfigured':
      return z.webhookUnconfigured;
    case 'undo_expired':
      return z.undoExpired;
    case 'import_too_large':
      return z.importTooLarge;
    // sign-in by verification code (API.md §1.1, slice 1-A)
    case 'setup_required':
      return z.setupRequired;
    case 'password_required':
      return z.passwordRequired;
    case 'admin_needs_password':
      return z.adminNeedsPassword;
    case 'verification_required':
      return z.verificationRequired;
    case 'consent_required':
      return z.consentRequired;
    case 'captcha_required':
      return z.captchaRequired;
    case 'invalid_captcha':
      return z.invalidCaptcha;
    case 'invalid_phone':
      return z.invalidPhone;
    case 'challenge_expired':
      return z.challengeExpired;
    case 'second_factor_required':
      return z.secondFactorRequired;
    case 'identity_taken':
      return z.identityTaken;
    case 'last_login_method':
      return z.lastLoginMethod;
    case 'sms_unconfigured':
      return z.smsUnconfigured;
    case 'sms_budget_exhausted':
      return z.smsBudgetExhausted;
    case 'sms_send_failed':
      return z.smsSendFailed;
    case 'invalid_code': {
      const left = e.detailNumber('attempts_left'); // 0 (or absent) = the code is gone: expired, consumed by an earlier check, or its tries used up
      return left !== null && left > 0 ? z.invalidCode(left) : z.codeExpired;
    }
    case 'email_send_failed':
      return z.emailSendFailed;
    // guardian and child accounts (API.md §1.1, slice 1-B)
    case 'invalid_pin':
      return z.invalidPin;
    case 'guardian_required':
      return z.guardianRequired;
    case 'guardian_gate_required':
      return z.guardianGateRequired;
    case 'guardian_factors_required':
      return z.guardianFactorsRequired;
    case 'has_children':
      return z.hasChildren;
    default:
      return e.message || z.server;
  }
}
