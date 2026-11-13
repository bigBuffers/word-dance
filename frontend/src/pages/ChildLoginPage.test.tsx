// ChildLoginPage (FRONTEND §2, API.md 107): eight digits enable the button, the code is posted once to /api/auth/child-login, the
// AuthResponse goes through applyAuth so the guest guard lands on /today, and a consumed code reads `errors.codeExpired`.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Settings, User } from '@/api/types';
import { AuthProvider, RequireGuest } from '@/auth/AuthContext';
import { zh } from '@/i18n/zh';
import ChildLoginPage, { CHILD_CODE_LENGTH } from './ChildLoginPage';

const ISO = '2026-11-10T08:00:00Z';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const child: User = {
  id: 4, username: 'u_tao00001', display_name: 'Tao', email: null, email_verified: false, role: 'user', onboarding_state: 'done', created_at: ISO,
  has_password: false, phone_masked: null, needs_profile: false, age_band: 'u14', account_kind: 'learner', is_child: true, needs_profile_prompt: false, providers: [],
};
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: false, updated_at: ISO,
};

function installFetch(loginStatus = 200) {
  let signedIn = false;
  const calls: { method: string; path: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      const path = url.split('?')[0] ?? url;
      const method = (init?.method ?? 'GET').toUpperCase();
      const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null;
      calls.push({ method, path, body });
      if (method === 'GET' && path === '/api/auth/me') {
        if (!signedIn) return json(401, { error: { code: 'unauthorized', message: '' } });
        return json(200, { user: child, settings, server: { version: '0.1.0', registration_mode: 'verified', email_configured: false, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', audio_zh: false, sms_enabled: true, wechat_enabled: false, qq_enabled: false, apple_enabled: false }, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: null } });
      }
      if (method === 'GET' && path === '/api/health') return json(200, { status: 'ok', version: '0.1.0', registration_mode: 'verified', needs_setup: false, sms_enabled: true, email_enabled: false, captcha: false, wechat_enabled: false, qq_enabled: false, apple_enabled: false, time: ISO });
      if (method === 'POST' && path === '/api/auth/child-login') {
        if (loginStatus !== 200) return json(loginStatus, { error: { code: 'invalid_code', message: '', details: { attempts_left: 0 } } });
        signedIn = true;
        return json(200, { user: child, settings });
      }
      return json(404, { error: { code: 'not_found', message: '' } });
    }),
  );
  return calls;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/child-login']}>
      <AuthProvider>
        <Routes>
          <Route element={<RequireGuest />}>
            <Route path="/child-login" element={<ChildLoginPage />} />
          </Route>
          <Route path="/today" element={<div>today-page</div>} />
          <Route path="/login" element={<div>login-page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

const codeInput = () => screen.getByLabelText(new RegExp(`^${zh.auth.childLoginCode}`)) as HTMLInputElement;
const loginButton = () => screen.getByRole('button', { name: zh.auth.login }) as HTMLButtonElement;

describe('ChildLoginPage', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('takes exactly eight digits, posts endpoint 107 once and lands on /today through applyAuth', async () => {
    const calls = installFetch();
    renderPage();
    expect(await screen.findByRole('heading', { name: zh.auth.childLogin })).toBeTruthy();
    expect(screen.getByText(zh.auth.childLoginLead)).toBeTruthy();
    expect(screen.getByRole('link', { name: zh.auth.backToLogin }).getAttribute('href')).toBe('/login');
    expect(codeInput().maxLength).toBe(CHILD_CODE_LENGTH);
    expect(screen.queryByRole('button', { name: zh.auth.sendCode })).toBeNull(); // the guardian's screen shows the code
    fireEvent.change(codeInput(), { target: { value: '1234567' } });
    expect(loginButton().disabled).toBe(true);
    fireEvent.change(codeInput(), { target: { value: '12345678x9' } }); // digits only, cut to eight
    expect(codeInput().value).toBe('12345678');
    expect(loginButton().disabled).toBe(false);
    fireEvent.click(loginButton());
    expect(await screen.findByText('today-page')).toBeTruthy();
    const posts = calls.filter((c) => c.method === 'POST');
    expect(posts.map((c) => [c.path, c.body])).toEqual([['/api/auth/child-login', { code: '12345678' }]]);
  });

  it('a consumed or unknown code reads errors.codeExpired and empties the input', async () => {
    installFetch(400);
    renderPage();
    await screen.findByRole('heading', { name: zh.auth.childLogin });
    fireEvent.change(codeInput(), { target: { value: '12345678' } });
    fireEvent.click(loginButton());
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.codeExpired);
    await waitFor(() => expect(codeInput().value).toBe(''));
    expect(screen.queryByText('today-page')).toBeNull();
  });
});
