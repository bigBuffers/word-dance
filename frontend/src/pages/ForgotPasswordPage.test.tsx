// ForgotPasswordPage (FRONTEND §2, API.md 90 / 91): identifier (+ captcha when the server asks) → endpoint 90 (always 202) →
// code + new password → endpoint 91 → /login?reset=1 (keeping `?next`); a weak password is refused client-side before any request.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '@/auth/AuthContext';
import { zh } from '@/i18n/zh';
import ForgotPasswordPage from './ForgotPasswordPage';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const unauthorized = () => json(401, { error: { code: 'unauthorized', message: '' } });
const health = (over: Record<string, unknown>) => () =>
  json(200, { status: 'ok', version: '0.1.0', registration_mode: 'verified', needs_setup: false, sms_enabled: true, email_enabled: false, captcha: false, time: '2026-10-14T00:00:00Z', ...over });

function mockFetch(routes: Record<string, (init?: RequestInit) => Response>) {
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const path = url.split('?')[0] ?? url;
    const handler = routes[path];
    return Promise.resolve(handler ? handler(init) : json(404, { error: { code: 'not_found', message: '' } }));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}
const bodyOf = (fetchMock: ReturnType<typeof mockFetch>, path: string) => {
  const call = fetchMock.mock.calls.find(([u]) => String(u) === path);
  return call?.[1]?.body ? (JSON.parse(String(call[1].body)) as Record<string, unknown>) : null;
};

/** The login route prints its query string so the redirect target is visible. */
function LoginProbe() {
  const location = useLocation();
  return <div>login-page{location.search}</div>;
}

function renderForgot(path = '/forgot') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/forgot" element={<ForgotPasswordPage />} />
          <Route path="/login" element={<LoginProbe />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('ForgotPasswordPage', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends the reset code for the identifier, then resets the password with the code and lands on /login?reset=1', async () => {
    const fetchMock = mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({}),
      '/api/auth/password/forgot': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/password/reset': () => new Response(null, { status: 204 }),
    });
    renderForgot();
    const send = (await screen.findByRole('button', { name: zh.auth.sendCode })) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.identifier}`)), { target: { value: ' 13800138000 ' } });
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    expect(await screen.findByText(zh.auth.forgotSent)).toBeTruthy();
    expect(bodyOf(fetchMock, '/api/auth/password/forgot')).toEqual({ identifier: '13800138000' });

    const reset = screen.getByRole('button', { name: zh.auth.resetPassword }) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.code}`)), { target: { value: '123456' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.settings.newPassword}`)), { target: { value: 'short' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password2}`)), { target: { value: 'short' } });
    expect(reset.disabled).toBe(true); // too weak, nothing is posted
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.settings.newPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password2}`)), { target: { value: 'Str0ng-Passphrase!' } });
    expect(reset.disabled).toBe(false);
    fireEvent.click(reset);
    expect(await screen.findByText('login-page?reset=1')).toBeTruthy();
    expect(bodyOf(fetchMock, '/api/auth/password/reset')).toEqual({ identifier: '13800138000', code: '123456', new_password: 'Str0ng-Passphrase!' });
  });

  it('keeps ?next through the detour: the back link and the post-reset redirect both carry it', async () => {
    mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({}),
      '/api/auth/password/forgot': () => json(202, { sent: true, expires_in_s: 600 }),
      '/api/auth/password/reset': () => new Response(null, { status: 204 }),
    });
    renderForgot('/forgot?next=%2Fbank');
    expect((await screen.findByRole('link', { name: zh.common.back })).getAttribute('href')).toBe('/login?next=%2Fbank');
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.identifier}`)), { target: { value: 'alice' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.sendCode }));
    await screen.findByText(zh.auth.forgotSent);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.code}`)), { target: { value: '123456' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.settings.newPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password2}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.resetPassword }));
    expect(await screen.findByText('login-page?next=%2Fbank&reset=1')).toBeTruthy();
  });

  it('asks for the captcha when the server requires it and sends its token with the identifier', async () => {
    const fetchMock = mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({ captcha: true }),
      '/api/auth/captcha': () => json(200, { id: 'cap1', image: 'data:image/png;base64,AAAA', exp: 1_900_000_000, sig: 'sig1', expires_in_s: 120 }),
      '/api/auth/password/forgot': () => json(202, { sent: true, expires_in_s: 600 }),
    });
    renderForgot();
    await screen.findByAltText(zh.auth.captchaAlt);
    const send = screen.getByRole('button', { name: zh.auth.sendCode }) as HTMLButtonElement;
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.identifier}`)), { target: { value: 'alice' } });
    expect(send.disabled).toBe(true); // the captcha digits are missing
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.captcha}`)), { target: { value: '4821' } });
    await waitFor(() => expect(send.disabled).toBe(false));
    fireEvent.click(send);
    await waitFor(() => expect(bodyOf(fetchMock, '/api/auth/password/forgot')).toEqual({ identifier: 'alice', captcha: { id: 'cap1', exp: 1_900_000_000, sig: 'sig1', answer: '4821' } }));
  });
});
