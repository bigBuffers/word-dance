import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from '@/auth/AuthContext';
import { zh } from '@/i18n/zh';
import LoginPage from './LoginPage';

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const unauthorized = () => json(401, { error: { code: 'unauthorized', message: '' } });
const health = (over: Record<string, unknown>) => () => json(200, { status: 'ok', version: '0.1.0', registration_mode: 'invite', needs_setup: false, time: '2026-10-14T00:00:00Z', ...over });

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

function renderLogin(path = '/login') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('LoginPage', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('shows the first-admin notice with a register link instead of the normal hint while needs_setup is true', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ needs_setup: true, registration_mode: 'closed' }) });
    renderLogin();
    expect(await screen.findByText(zh.auth.needsSetup, { exact: false })).toBeTruthy();
    expect(screen.getByRole('link', { name: zh.auth.goRegister }).getAttribute('href')).toBe('/register');
    expect(screen.queryByText(zh.auth.noAccount, { exact: false })).toBeNull();
  });

  it('hides the register link on a closed server and keeps it otherwise, carrying ?next=', async () => {
    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'closed' }) });
    const first = renderLogin();
    await screen.findByRole('button', { name: zh.auth.login });
    await waitFor(() => expect(screen.queryByRole('link', { name: zh.auth.register })).toBeNull());
    first.unmount();
    vi.unstubAllGlobals();

    mockFetch({ '/api/auth/me': unauthorized, '/api/health': health({ registration_mode: 'invite' }) });
    renderLogin('/login?next=%2Fbank');
    expect((await screen.findByRole('link', { name: zh.auth.register })).getAttribute('href')).toBe('/register?next=%2Fbank');
  });

  it('posts the credentials and shows the server error inline on failure', async () => {
    const fetchMock = mockFetch({
      '/api/auth/me': unauthorized,
      '/api/health': health({}),
      '/api/auth/login': () => json(401, { error: { code: 'invalid_credentials', message: '' } }),
    });
    renderLogin();
    const submit = await screen.findByRole('button', { name: zh.auth.login });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(new RegExp(zh.auth.username)), { target: { value: ' alice ' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password}`)), { target: { value: 'secret123' } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.invalidCredentials);
    const loginCall = fetchMock.mock.calls.find(([u]) => String(u) === '/api/auth/login');
    expect(loginCall?.[1]?.method).toBe('POST');
    expect(loginCall?.[1]?.body).toBe(JSON.stringify({ username: 'alice', password: 'secret123' }));
    expect((loginCall?.[1]?.headers as Record<string, string>)['X-WD-Request']).toBe('1');
  });
});
