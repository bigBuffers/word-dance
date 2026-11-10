// AuthContext bootstrap + route guards (FRONTEND §2/§3).
import { act } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AUTH_EXPIRED_EVENT } from '@/api/client';
import type { MeResponse } from '@/api/endpoints';
import type { Settings, User } from '@/api/types';
import { clipUrl, serverAudioEnabled, setServerAudio } from '@/audio/serverAudio';
import { AuthProvider, RequireAdmin, RequireAuth, RequireOnboarded, loginPathFor, safeNext, useAuth } from './AuthContext';

const settings: Settings = {
  timezone: 'Asia/Shanghai',
  push_time: '08:00',
  push_enabled: true,
  daily_new_count: 10,
  daily_screen_count: 15,
  max_reviews: 100,
  stages: ['cet4', 'cet6'],
  current_stage: 'cet4',
  show_images: true,
  zh_examples: 'tap', dance_mode: 'full',
  auto_pronounce: false,
  accent: 'en-US',
  email_enabled: false,
  webhook_enabled: false,
  webhook_url: null,
  webhook_format: 'generic',
  next_push_at: '2026-10-15T00:00:00Z',
  email_verified: false,
  updated_at: '2026-10-14T00:00:00Z',
};

function me(user: Partial<User> = {}): MeResponse {
  return {
    user: {
      id: 1,
      username: 'alice',
      display_name: 'Alice',
      email: null,
      email_verified: false,
      role: 'user',
      onboarding_state: 'done',
      created_at: '2026-10-14T00:00:00Z',
      has_password: true,
      phone_masked: null,
      needs_profile: false,
      age_band: null,
      ...user,
    },
    settings,
    server: { version: '0.1.0', registration_mode: 'invite', email_configured: false, ai_enabled: true, images_enabled: true, dev: true, needs_setup: false, audio: true, audio_key: 'k1a2b3c4', sms_enabled: false },
    counters: { suggestions_open: 2, attention: 1 },
  };
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const unauthorized = () => json(401, { error: { code: 'unauthorized', message: '' } });
const health = () => json(200, { status: 'ok', version: '0.1.0', registration_mode: 'invite', needs_setup: true, time: '2026-10-14T00:00:00Z' });

function mockFetch(routes: Record<string, () => Response>) {
  const fn = vi.fn<typeof fetch>((input) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const path = url.split('?')[0] ?? url;
    const handler = routes[path];
    return Promise.resolve(handler ? handler() : json(404, { error: { code: 'not_found', message: '' } }));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="loc">{`${location.pathname}${location.search}`}</div>;
}

function CountersProbe() {
  const { counters, health: flags } = useAuth();
  return <div data-testid="probe">{`${counters?.suggestions_open ?? '-'}/${counters?.attention ?? '-'}/${flags?.needs_setup ?? '-'}`}</div>;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <LocationProbe />
        <CountersProbe />
        <Routes>
          <Route path="/login" element={<div>login-page</div>} />
          <Route path="/welcome" element={<div>welcome-page</div>} />
          <Route element={<RequireAuth />}>
            <Route element={<RequireOnboarded />}>
              <Route path="/today" element={<div>today-page</div>} />
            </Route>
            <Route element={<RequireAdmin />}>
              <Route path="/admin" element={<div>admin-page</div>} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('guards', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('RequireAuth sends guests to /login?next=<path+search> and loads the public health flags', async () => {
    const fetchMock = mockFetch({ '/api/auth/me': unauthorized, '/api/health': health });
    renderAt('/today?x=1');
    expect(await screen.findByText('login-page')).toBeTruthy();
    expect(screen.getByTestId('loc').textContent).toBe('/login?next=%2Ftoday%3Fx%3D1');
    expect((await screen.findByText('-/-/true')).textContent).toBe('-/-/true');
    expect(fetchMock.mock.calls.map(([u]) => String(u))).toEqual(['/api/auth/me', '/api/health']);
  });

  it('RequireOnboarded sends a user with onboarding_state != done to /welcome', async () => {
    mockFetch({ '/api/auth/me': () => json(200, me({ onboarding_state: 'pending' })) });
    renderAt('/today');
    expect(await screen.findByText('welcome-page')).toBeTruthy();
  });

  it('renders the page for an onboarded user and exposes counters from /api/auth/me', async () => {
    mockFetch({ '/api/auth/me': () => json(200, me()) });
    renderAt('/today');
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(screen.getByTestId('probe').textContent).toBe('2/1/-');
  });

  it('mirrors ServerFlags.audio into the server-audio module when /api/auth/me lands (the module-level speak() reads it)', async () => {
    setServerAudio(false);
    mockFetch({ '/api/auth/me': () => json(200, me()) }); // server.audio true in the fixture
    renderAt('/today');
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(serverAudioEnabled()).toBe(true);
    expect(clipUrl('farmer', 'en-US')).toContain('v=k1a2b3c4'); // ServerFlags.audio_key rides on the clip URLs
    setServerAudio(false);
    expect(clipUrl('farmer', 'en-US')).not.toContain('v=');
  });

  it('RequireAdmin sends non-admins to /today and lets admins through', async () => {
    mockFetch({ '/api/auth/me': () => json(200, me()) });
    const first = renderAt('/admin');
    expect(await screen.findByText('today-page')).toBeTruthy();
    first.unmount();
    vi.unstubAllGlobals();

    mockFetch({ '/api/auth/me': () => json(200, me({ role: 'admin' })) });
    renderAt('/admin');
    expect(await screen.findByText('admin-page')).toBeTruthy();
  });

  it('auth:expired clears the session so RequireAuth redirects to /login?next=', async () => {
    mockFetch({ '/api/auth/me': () => json(200, me()), '/api/health': health });
    renderAt('/today');
    await screen.findByText('today-page');
    act(() => {
      window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT, { detail: { path: '/api/today' } }));
    });
    expect(await screen.findByText('login-page')).toBeTruthy();
    expect(screen.getByTestId('loc').textContent).toBe('/login?next=%2Ftoday');
  });
});

describe('helpers', () => {
  it('loginPathFor omits next for the root path', () => {
    expect(loginPathFor({ pathname: '/', search: '' })).toBe('/login');
    expect(loginPathFor({ pathname: '/bank', search: '?state=new' })).toBe('/login?next=%2Fbank%3Fstate%3Dnew');
  });

  it('safeNext only accepts same-origin absolute paths', () => {
    expect(safeNext('/bank')).toBe('/bank');
    expect(safeNext('//evil.example')).toBe('/today');
    expect(safeNext('https://evil.example')).toBe('/today');
    expect(safeNext(null)).toBe('/today');
    expect(safeNext('', '/vocab')).toBe('/vocab');
  });
});
