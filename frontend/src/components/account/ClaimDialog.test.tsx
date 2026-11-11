// ClaimDialog (FRONTEND §4, API.md 108 / 109): the guardian's phone receives the claim code (108), phone + code + age band post
// endpoint 109, the returned user replaces the session user and the sheet closes with a toast; without SMS on the server only the
// hint is shown.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ServerFlags, Settings, User } from '@/api/types';
import { AuthProvider, useAuth } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import { ClaimDialog } from './ClaimDialog';

const ISO = '2026-11-10T08:00:00Z';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const learner: User = {
  id: 2, username: 'bob', display_name: 'Bob', email: null, email_verified: false, role: 'user', onboarding_state: 'done', created_at: ISO,
  has_password: true, phone_masked: null, needs_profile: false, age_band: null, account_kind: 'learner', is_child: false, needs_profile_prompt: false, providers: [],
};
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: false, updated_at: ISO,
};
const baseServer: ServerFlags = { version: '0.1.0', registration_mode: 'verified', email_configured: false, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', sms_enabled: true, wechat_enabled: false, qq_enabled: false, apple_enabled: false };

let server: ServerFlags;
let me: User;
let calls: { method: string; path: string; body: Record<string, unknown> | null }[];

function installFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      const path = url.split('?')[0] ?? url;
      const method = (init?.method ?? 'GET').toUpperCase();
      const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null;
      calls.push({ method, path, body });
      const key = `${method} ${path}`;
      if (key === 'GET /api/auth/me') return json(200, { user: me, settings, server, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: null } });
      if (key === 'POST /api/account/guardian/code') return json(202, { sent: true, expires_in_s: 600 });
      if (key === 'POST /api/account/guardian') return json(200, { user: { ...me, is_child: true, age_band: body?.['age_band'] } });
      return json(404, { error: { code: 'not_found', message: '' } });
    }),
  );
}

function Probe() {
  const { user } = useAuth();
  return <div data-testid="child">{String(user?.is_child ?? '-')}</div>;
}

function renderClaim() {
  const onClose = vi.fn();
  render(
    <MemoryRouter>
      <ToastProvider>
        <AuthProvider>
          <Probe />
          <ClaimDialog open onClose={onClose} />
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
  return onClose;
}

describe('ClaimDialog', () => {
  beforeEach(() => {
    calls = [];
    server = baseServer;
    me = learner;
    installFetch();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('sends the claim code to the guardian phone (108), then posts phone + code + age band (109), patches the user and closes', async () => {
    const onClose = renderClaim();
    expect(await screen.findByRole('heading', { name: zh.children.claimTitle })).toBeTruthy();
    expect(screen.getByText(zh.children.claimLead)).toBeTruthy();
    const confirm = screen.getByRole('button', { name: zh.common.confirm }) as HTMLButtonElement;
    const send = () => screen.getByRole('button', { name: zh.auth.sendCode }) as HTMLButtonElement; // the CodeField remounts per target
    expect(send().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.children.guardianPhone}`)), { target: { value: '13800138000' } });
    expect(send().disabled).toBe(false);
    fireEvent.click(send());
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/guardian/code').map((c) => c.body)).toEqual([{ target: '+8613800138000' }]));
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.code}`)), { target: { value: '123456' } });
    expect(confirm.disabled).toBe(true); // the age band is still missing
    fireEvent.click(screen.getByLabelText(zh.children.claimU14));
    expect(confirm.disabled).toBe(false);
    expect(screen.queryByText(zh.children.claimDetach)).toBeNull(); // nothing bound to this account, nothing to detach
    fireEvent.click(confirm);
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/guardian').map((c) => c.body)).toEqual([{ target: '+8613800138000', code: '123456', age_band: 'u14' }]));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(screen.getByTestId('child').textContent).toBe('true');
    expect(await screen.findByText(zh.children.claimed)).toBeTruthy();
  });

  it('warns that a u14 claim detaches the phone and e-mail the account holds (API.md 109)', async () => {
    me = { ...learner, phone_masked: '139****9000', email: 'bob@example.com' };
    renderClaim();
    expect(await screen.findByRole('heading', { name: zh.children.claimTitle })).toBeTruthy();
    expect(screen.queryByText(zh.children.claimDetach)).toBeNull();
    fireEvent.click(screen.getByLabelText(zh.children.claimU14));
    expect(screen.getByText(zh.children.claimDetach)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(zh.children.claim14plus));
    expect(screen.queryByText(zh.children.claimDetach)).toBeNull(); // a 14plus claim keeps them
  });

  it('shows only the SMS hint while the server cannot send SMS', async () => {
    server = { ...baseServer, sms_enabled: false };
    renderClaim();
    expect(await screen.findByText(zh.children.claimSmsOff)).toBeTruthy();
    expect(screen.queryByRole('button', { name: zh.auth.sendCode })).toBeNull();
    expect(screen.queryByLabelText(new RegExp(`^${zh.children.guardianPhone}`))).toBeNull();
  });
});
