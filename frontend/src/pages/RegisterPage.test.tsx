import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import { AuthProvider } from '@/auth/AuthContext';
import { zh } from '@/i18n/zh';
import RegisterPage, { passwordStrength, validationFieldMessages } from './RegisterPage';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const unauthorized = () => json(401, { error: { code: 'unauthorized', message: '' } });
const health = (over: Record<string, unknown>) => () => json(200, { status: 'ok', version: '0.1.0', registration_mode: 'invite', needs_setup: false, time: '2026-10-14T00:00:00Z', ...over });

function mockFetch(routes: Record<string, () => Response>) {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>((input) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      const path = url.split('?')[0] ?? url;
      const handler = routes[path];
      return Promise.resolve(handler ? handler() : json(404, { error: { code: 'not_found', message: '' } }));
    }),
  );
}

function renderRegister() {
  return render(
    <MemoryRouter initialEntries={['/register']}>
      <AuthProvider>
        <Routes>
          <Route path="/register" element={<RegisterPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

const inviteLabel = new RegExp(`^${zh.auth.invite}`);

describe('RegisterPage', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows the invite field in invite mode', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'invite' }) });
    renderRegister();
    expect(await screen.findByLabelText(inviteLabel)).toBeTruthy();
    expect(screen.queryByText(zh.auth.firstUser)).toBeNull();
  });

  it('on a fresh server shows the first-admin notice and no invite field even in invite mode', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'invite', needs_setup: true }) });
    renderRegister();
    expect(await screen.findByText(zh.auth.firstUser)).toBeTruthy();
    await waitFor(() => expect(screen.queryByLabelText(inviteLabel)).toBeNull());
    expect(screen.getByRole('button', { name: zh.auth.register })).toBeTruthy();
  });

  it('shows registration-closed instead of the form on a closed server', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'closed' }) });
    renderRegister();
    expect(await screen.findByText(zh.errors.registrationClosed)).toBeTruthy();
    expect(screen.queryByRole('button', { name: zh.auth.register })).toBeNull();
    expect(screen.getByRole('link', { name: zh.auth.login })).toBeTruthy();
  });

  it('open mode shows the form without an invite field', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'open' }) });
    renderRegister();
    expect(await screen.findByRole('button', { name: zh.auth.register })).toBeTruthy();
    expect(screen.queryByLabelText(inviteLabel)).toBeNull();
  });

  it('a malformed e-mail shows errors.invalidEmail under the field (not the field label) and nothing is posted', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'open' }) });
    renderRegister();
    await screen.findByRole('button', { name: zh.auth.register });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.username}`)), { target: { value: 'alice' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password2}`)), { target: { value: 'Str0ng-Passphrase!' } });
    const email = screen.getByLabelText(new RegExp(`^${zh.auth.email}`)) as HTMLInputElement;
    fireEvent.change(email, { target: { value: 'foo@' } });
    fireEvent.click(screen.getByRole('button', { name: zh.auth.register }));
    const error = await screen.findByText(zh.errors.invalidEmail);
    expect(error.getAttribute('role')).toBe('alert');
    expect(email.getAttribute('aria-invalid')).toBe('true');
    expect(email.getAttribute('aria-describedby')).toBe(error.id);
    expect(screen.queryByText(zh.auth.email, { selector: '.field__error' })).toBeNull();
    const posted = vi.mocked(fetch).mock.calls.map((c) => (typeof c[0] === 'string' ? c[0] : String(c[0])));
    expect(posted.some((u) => u.includes('/api/auth/register'))).toBe(false);
  });
});

describe('helpers', () => {
  it('passwordStrength mirrors the API.md 2 minimums as a hint', () => {
    expect(passwordStrength('', 'alice')).toBe(0);
    expect(passwordStrength('short', 'alice')).toBe(1);
    expect(passwordStrength('alicealice', 'AliceAlice')).toBe(1);
    expect(passwordStrength('password1', 'alice')).toBe(2);
    expect(passwordStrength('Str0ng-Passphrase!', 'alice')).toBe(3);
  });

  it('validationFieldMessages joins the per-field server messages', () => {
    expect(validationFieldMessages(new ApiError('validation_error', 400, '', { fields: { username: 'too short', email: 'bad' } }))).toBe('too short · bad');
    expect(validationFieldMessages(new ApiError('validation_error', 400, '', {}))).toBeNull();
    expect(validationFieldMessages(new ApiError('weak_password', 400, ''))).toBeNull();
    expect(validationFieldMessages(new Error('x'))).toBeNull();
  });
});
