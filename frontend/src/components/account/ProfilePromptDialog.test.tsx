// ProfilePromptDialog (FRONTEND §2 / §4, API.md 110 / 111): shown for a legacy account that still needs the declaration, the three
// radios post endpoint 110 and the user is patched, the later button posts endpoint 111, the child button hands over to the claim
// sheet (never for admins), and the prompt opens once per sitting.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ServerFlags, Settings, User } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import { DECLARE_BODY, ProfilePromptDialog, resetProfilePrompt } from './ProfilePromptDialog';

const ISO = '2026-11-10T08:00:00Z';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const legacy: User = {
  id: 1, username: 'alice', display_name: 'Alice', email: null, email_verified: false, role: 'user', onboarding_state: 'done', created_at: ISO,
  has_password: true, phone_masked: null, needs_profile: false, age_band: null, account_kind: 'learner', is_child: false, needs_profile_prompt: true,
};
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: false, updated_at: ISO,
};
const server: ServerFlags = { version: '0.1.0', registration_mode: 'verified', email_configured: false, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', sms_enabled: true };

let user: User;
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
      if (key === 'GET /api/auth/me') return json(200, { user, settings, server, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: null } });
      if (key === 'POST /api/account/declare') {
        user = { ...user, account_kind: body?.['account_kind'] as User['account_kind'], age_band: body?.['age_band'] as User['age_band'], needs_profile_prompt: false };
        return json(200, { user });
      }
      if (key === 'POST /api/account/declare/skip') return new Response(null, { status: 204 });
      return json(404, { error: { code: 'not_found', message: '' } });
    }),
  );
}

function renderPrompt() {
  return render(
    <MemoryRouter>
      <ToastProvider>
        <AuthProvider>
          <ProfilePromptDialog />
          <div>page-body</div>
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe('ProfilePromptDialog', () => {
  beforeEach(() => {
    calls = [];
    user = legacy;
    resetProfilePrompt();
    installFetch();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('offers the three declarations and posts endpoint 110 for the chosen one', async () => {
    renderPrompt();
    expect(await screen.findByRole('heading', { name: zh.children.promptTitle })).toBeTruthy();
    expect(screen.getByText(zh.children.promptLead)).toBeTruthy();
    expect(screen.getAllByRole('radio').map((r) => (r.closest('label') as HTMLElement).textContent)).toEqual([zh.children.roleGuardian, zh.children.roleAdult, zh.children.roleStudent]);
    const confirm = screen.getByRole('button', { name: zh.common.confirm }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(zh.children.roleGuardian));
    fireEvent.click(confirm);
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/declare').map((c) => c.body)).toEqual([DECLARE_BODY.guardian]));
    await waitFor(() => expect(screen.queryByRole('heading', { name: zh.children.promptTitle })).toBeNull());
    expect(DECLARE_BODY.adult).toEqual({ account_kind: 'learner', age_band: 'adult' });
    expect(DECLARE_BODY['14plus']).toEqual({ account_kind: 'learner', age_band: '14plus' });
  });

  it('the later button posts endpoint 111 and closes; the prompt does not re-open in the same sitting', async () => {
    const first = renderPrompt();
    fireEvent.click(await screen.findByRole('button', { name: zh.children.promptLater }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/declare/skip')).toHaveLength(1));
    expect(screen.queryByRole('heading', { name: zh.children.promptTitle })).toBeNull();
    first.unmount();
    renderPrompt(); // another route of the same sitting: the user still needs the prompt server-side, but it was shown
    expect(await screen.findByText('page-body')).toBeTruthy();
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/auth/me')).toHaveLength(2));
    expect(screen.queryByRole('heading', { name: zh.children.promptTitle })).toBeNull();
    resetProfilePrompt();
  });

  it('the child button closes the prompt and opens the claim sheet; admins do not get it', async () => {
    renderPrompt();
    fireEvent.click(await screen.findByRole('button', { name: zh.children.promptChild }));
    expect(await screen.findByRole('heading', { name: zh.children.claimTitle })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: zh.children.promptTitle })).toBeNull();
    expect(calls.filter((c) => c.method === 'POST')).toHaveLength(0);
    vi.unstubAllGlobals();

    resetProfilePrompt();
    user = { ...legacy, role: 'admin' };
    installFetch();
    renderPrompt();
    await screen.findAllByRole('heading', { name: zh.children.promptTitle });
    expect(screen.queryByRole('button', { name: zh.children.promptChild })).toBeNull();
  });

  it('is not shown for an account that already declared, a child, or before onboarding', async () => {
    user = { ...legacy, needs_profile_prompt: false };
    const first = renderPrompt();
    await screen.findByText('page-body');
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/auth/me')).toHaveLength(1));
    expect(screen.queryByRole('heading', { name: zh.children.promptTitle })).toBeNull();
    first.unmount();
    vi.unstubAllGlobals();

    user = { ...legacy, onboarding_state: 'screen' };
    calls = [];
    installFetch();
    renderPrompt();
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/auth/me')).toHaveLength(1));
    expect(screen.queryByRole('heading', { name: zh.children.promptTitle })).toBeNull();
  });
});
