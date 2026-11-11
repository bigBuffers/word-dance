// NativeBridge (FRONTEND §6.6): the device reminder is synced only once the session is known — never from the loading state, never
// because /api/auth/me failed or the session expired — and cancelled only on an explicit sign-out; a resume re-arms a known session.
import { act, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Settings, User } from '@/api/types';
import { AuthProvider, useAuth } from '@/auth/AuthContext';
import { NativeBridge } from './NativeBridge';

const native = vi.hoisted(() => ({
  sync: vi.fn(async (_s: unknown) => 'scheduled' as const),
  handlers: null as null | { navigate: (p: string) => void; onResume: () => void },
  install: vi.fn((h: { navigate: (p: string) => void; onResume: () => void }) => {
    native.handlers = h;
    return () => undefined;
  }),
}));
vi.mock('@/native/capacitor', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/capacitor')>()),
  isNative: () => true,
  syncDailyReminder: native.sync,
  installNativeListeners: native.install,
}));

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const user: User = { id: 1, username: 'alice', display_name: 'alice', email: null, email_verified: false, role: 'user', onboarding_state: 'done', created_at: '2026-10-14T00:00:00Z', has_password: true, phone_masked: null, needs_profile: false, age_band: null, account_kind: 'learner', is_child: false, needs_profile_prompt: false, providers: [] };
const server = { version: '0.1.0', registration_mode: 'open', email_configured: false, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false };
const settings = { push_enabled: true, push_time: '08:00', timezone: 'Asia/Shanghai', stages: ['xs'], current_stage: 'xs' } as unknown as Settings;

let meStatus: number;
let releaseMe: () => void;

beforeEach(() => {
  native.sync.mockClear();
  native.install.mockClear();
  native.handlers = null;
  meStatus = 200;
  const gate = new Promise<void>((resolve) => (releaseMe = resolve));
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      const path = url.split('?')[0] ?? url;
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'GET' && path === '/api/auth/me') {
        await gate;
        return meStatus === 200 ? json(200, { user, settings, server, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: null } }) : json(meStatus, { error: { code: 'server_error', message: '' } });
      }
      if (method === 'POST' && path === '/api/auth/logout') return new Response(null, { status: 204 });
      if (method === 'GET' && path === '/api/health') return json(200, { status: 'ok', version: '0.1.0', registration_mode: 'open', needs_setup: false, time: '' });
      return json(404, { error: { code: 'not_found', message: '' } });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

function LogoutProbe() {
  const { logout, user: u, loading } = useAuth();
  return (
    <button type="button" onClick={() => void logout()}>
      {loading ? 'loading' : u ? 'signed-in' : 'signed-out'}
    </button>
  );
}

function mount() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <NativeBridge />
        <LogoutProbe />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('NativeBridge', () => {
  it('syncs once the session is known, not while /api/auth/me is loading', async () => {
    mount();
    expect(screen.getByRole('button').textContent).toBe('loading');
    expect(native.sync).not.toHaveBeenCalled();
    await act(async () => releaseMe());
    await waitFor(() => expect(native.sync).toHaveBeenCalledTimes(1));
    expect(native.sync.mock.calls[0]![0]).toMatchObject({ push_enabled: true, push_time: '08:00', timezone: 'Asia/Shanghai' });
    // a resume re-arms the known session
    act(() => native.handlers!.onResume());
    expect(native.sync).toHaveBeenCalledTimes(2);
    expect(native.sync.mock.calls[1]![0]).toMatchObject({ push_time: '08:00' });
    // navigating does not re-install the listeners (installed once, `navigate` kept in a ref)
    act(() => native.handlers!.navigate('/study'));
    await waitFor(() => expect(screen.getByRole('button').textContent).toBe('signed-in'));
    expect(native.install).toHaveBeenCalledTimes(1);
  });

  it('never cancels because the session could not be loaded (a 500 from /me)', async () => {
    meStatus = 500;
    mount();
    await act(async () => releaseMe());
    await screen.findByText('signed-out');
    act(() => native.handlers!.onResume());
    expect(native.sync).not.toHaveBeenCalled();
  });

  it('cancels only on an explicit sign-out', async () => {
    mount();
    await act(async () => releaseMe());
    await waitFor(() => expect(native.sync).toHaveBeenCalledTimes(1));
    act(() => screen.getByRole('button').click());
    await screen.findByText('signed-out');
    await waitFor(() => expect(native.sync).toHaveBeenCalledTimes(2));
    expect(native.sync.mock.calls[1]![0]).toBeNull();
    act(() => native.handlers!.onResume()); // signed out: a resume leaves the device alone
    expect(native.sync).toHaveBeenCalledTimes(2);
  });
});
