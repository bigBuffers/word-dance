// api/client contract tests (FRONTEND §7): envelope → ApiError, 401 event, header injection.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { zh } from '@/i18n/zh';
import { ApiError, AUTH_EXPIRED_EVENT, buildQuery, CSRF_HEADER, errorMessage, request, requestText } from './client';

function jsonResponse(status: number, body?: unknown, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...headers },
  });
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function headersOf(call: number): Record<string, string> {
  const init = fetchMock.mock.calls[call]?.[1];
  return (init?.headers ?? {}) as Record<string, string>;
}

describe('request()', () => {
  it('sends same-origin credentials, a JSON body and the CSRF header on non-GET requests', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));
    const result = await request<{ ok: boolean }>('POST', '/api/words/1/mark', { action: 'unfamiliar' });
    expect(result).toEqual({ ok: true });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/words/1/mark');
    expect(init?.method).toBe('POST');
    expect(init?.credentials).toBe('same-origin');
    expect(init?.body).toBe(JSON.stringify({ action: 'unfamiliar' }));
    expect(headersOf(0)[CSRF_HEADER]).toBe('1');
    expect(headersOf(0)['Content-Type']).toBe('application/json');
    expect(headersOf(0)['Accept']).toBe('application/json');
  });

  it('adds the CSRF header to PUT/PATCH/DELETE as well', async () => {
    fetchMock.mockResolvedValue(jsonResponse(204));
    await request('PUT', '/api/settings', { push_time: '08:00' });
    await request('PATCH', '/api/bank/7', { attention: 'keep' });
    await request('DELETE', '/api/account', { password: 'x' });
    for (let i = 0; i < 3; i++) expect(headersOf(i)[CSRF_HEADER]).toBe('1');
  });

  it('omits the CSRF header and body on GET and serialises the query', async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { items: [] }));
    await request('GET', '/api/vocab', undefined, { query: { stage: 'cet6', new_only: true, page: 2, q: undefined } });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('/api/vocab?stage=cet6&new_only=1&page=2');
    expect(init?.method).toBe('GET');
    expect(init?.body).toBeUndefined();
    expect(headersOf(0)[CSRF_HEADER]).toBeUndefined();
    expect(headersOf(0)['Content-Type']).toBeUndefined();
  });

  it('resolves undefined for 204 / empty bodies', async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(request('POST', '/api/auth/logout')).resolves.toBeUndefined();
    fetchMock.mockResolvedValueOnce(new Response('', { status: 200 }));
    await expect(request('GET', '/api/anything')).resolves.toBeUndefined();
  });

  it('maps the error envelope to ApiError (code, status, message, details, request id)', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(400, { error: { code: 'invalid_word', message: zh.errors.invalidWord, details: { input: 'abc123' } } }, { 'X-Request-Id': 'rid-1' }),
    );
    const err: unknown = await request('POST', '/api/bank/add', { text: 'abc123' }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const apiError = err as ApiError;
    expect(apiError.code).toBe('invalid_word');
    expect(apiError.status).toBe(400);
    expect(apiError.message).toBe(zh.errors.invalidWord);
    expect(apiError.details).toEqual({ input: 'abc123' });
    expect(apiError.requestId).toBe('rid-1');
    expect(apiError.name).toBe('ApiError');
  });

  it('derives a code from the status when the body is not an envelope', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>bad gateway</html>', { status: 502 }));
    await expect(request('GET', '/api/today')).rejects.toMatchObject({ code: 'internal_error', status: 502 });
    fetchMock.mockResolvedValueOnce(new Response('', { status: 404 }));
    await expect(request('GET', '/api/nope')).rejects.toMatchObject({ code: 'not_found', status: 404 });
    fetchMock.mockResolvedValueOnce(new Response('', { status: 429 }));
    await expect(request('GET', '/api/nope')).rejects.toMatchObject({ code: 'rate_limited', status: 429 });
  });

  it('dispatches auth:expired on 401 unauthorized but not on 401 invalid_credentials', async () => {
    const handler = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, handler);
    try {
      fetchMock.mockResolvedValueOnce(jsonResponse(401, { error: { code: 'invalid_credentials', message: '' } }));
      await expect(request('POST', '/api/auth/login', { username: 'a', password: 'b' })).rejects.toMatchObject({ code: 'invalid_credentials' });
      expect(handler).not.toHaveBeenCalled();

      fetchMock.mockResolvedValueOnce(jsonResponse(401, { error: { code: 'unauthorized', message: '' } }));
      await expect(request('GET', '/api/today')).rejects.toMatchObject({ code: 'unauthorized', status: 401 });
      expect(handler).toHaveBeenCalledTimes(1);
      expect((handler.mock.calls[0]![0] as CustomEvent).detail).toEqual({ path: '/api/today' });

      // a bare 401 without an envelope counts as an expired session too
      fetchMock.mockResolvedValueOnce(new Response(null, { status: 401 }));
      await expect(request('GET', '/api/today')).rejects.toMatchObject({ code: 'unauthorized' });
      expect(handler).toHaveBeenCalledTimes(2);
    } finally {
      window.removeEventListener(AUTH_EXPIRED_EVENT, handler);
    }
  });

  it('wraps network failures as ApiError(network)', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));
    const err = (await request('GET', '/api/health').catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('network');
    expect(err.status).toBe(0);
    expect(err.message).toBe(zh.errors.network);
  });

  it('re-throws aborts untouched so callers can ignore them', async () => {
    const abort = new DOMException('aborted', 'AbortError');
    fetchMock.mockRejectedValue(abort);
    await expect(request('GET', '/api/today')).rejects.toBe(abort);
  });

  it('rejects a 2xx body that is not JSON', async () => {
    fetchMock.mockResolvedValue(new Response('<!doctype html>', { status: 200 }));
    await expect(request('GET', '/api/today')).rejects.toMatchObject({ code: 'invalid_response' });
  });
});

describe('requestText()', () => {
  it('returns the raw body (exports)', async () => {
    fetchMock.mockResolvedValue(new Response('word,phonetic\nabandon,x', { status: 200 }));
    await expect(requestText('GET', '/api/account/export', { query: { format: 'csv' } })).resolves.toBe('word,phonetic\nabandon,x');
    expect(fetchMock.mock.calls[0]![0]).toBe('/api/account/export?format=csv');
  });
});

describe('buildQuery()', () => {
  it('skips null/undefined and encodes booleans as 1/0', () => {
    expect(buildQuery({ stage: 'cet6', new_only: true, q: undefined, letter: null, page: 2, all: false })).toBe('?stage=cet6&new_only=1&page=2&all=0');
    expect(buildQuery({ q: 'ice cream' })).toBe('?q=ice+cream');
    expect(buildQuery()).toBe('');
    expect(buildQuery({})).toBe('');
  });
});

describe('errorMessage()', () => {
  it('prefers deterministic client copy by code', () => {
    expect(errorMessage(new ApiError('network', 0, ''))).toBe(zh.errors.network);
    expect(errorMessage(new ApiError('csrf_rejected', 403, ''))).toBe(zh.errors.csrf);
    expect(errorMessage(new ApiError('word_not_found', 404, ''))).toBe(zh.errors.notFound);
    expect(errorMessage(new ApiError('undo_expired', 409, ''))).toBe(zh.errors.undoExpired);
    expect(errorMessage(new ApiError('budget_exhausted', 409, ''))).toBe(zh.errors.budgetExhausted);
    expect(errorMessage(new ApiError('import_too_large', 400, ''))).toBe(zh.errors.importTooLarge);
  });

  it('formats account_locked from details.retry_after_s', () => {
    expect(errorMessage(new ApiError('account_locked', 423, '', { retry_after_s: 601 }))).toBe(zh.errors.accountLocked(601));
    expect(errorMessage(new ApiError('account_locked', 423, '', {}))).toBe(zh.errors.accountLocked(900));
  });

  it('falls back to the server message for other codes, then to the generic copy', () => {
    expect(errorMessage(new ApiError('invalid_transition', 409, 'server says so'))).toBe('server says so');
    expect(errorMessage(new ApiError('validation_error', 400, ''))).toBe(zh.errors.server);
    expect(errorMessage(new Error('boom'))).toBe(zh.errors.server);
    expect(errorMessage(undefined)).toBe(zh.errors.server);
  });
});
