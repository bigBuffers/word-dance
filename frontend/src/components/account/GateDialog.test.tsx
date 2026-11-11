// GateDialog (FRONTEND §4, API.md 102 / 105): gate mode offers the factors the guardian holds (PIN only with pinSet, the password only
// with hasPassword, the code always), a wrong PIN reads errors.invalidPin and a lockout errors.accountLocked, a pass reports
// gate_until; switch-back mode offers all three factors, sends its code through endpoint 106 and installs the guardian's session
// through endpoint 105 → applyAuth.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ServerFlags, Settings, User } from '@/api/types';
import { AuthProvider, useAuth } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import { GateDialog, gateFactors, type GateDialogProps } from './GateDialog';

const ISO = '2026-11-10T08:00:00Z';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const guardian: User = {
  id: 1, username: 'mom', display_name: 'Mom', email: 'mom@example.com', email_verified: true, role: 'user', onboarding_state: 'done', created_at: ISO,
  has_password: true, phone_masked: '138****8000', needs_profile: false, age_band: 'adult', account_kind: 'guardian', is_child: false, needs_profile_prompt: false, providers: [],
};
const child: User = { ...guardian, id: 4, username: 'u_tao00001', display_name: 'Tao', email: null, email_verified: false, has_password: false, phone_masked: null, age_band: 'u14', account_kind: 'learner', is_child: true };
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: true, updated_at: ISO,
};
const server: ServerFlags = { version: '0.1.0', registration_mode: 'verified', email_configured: true, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', sms_enabled: true, wechat_enabled: false, qq_enabled: false, apple_enabled: false };

let me: User;
let calls: { method: string; path: string; body: Record<string, unknown> | null }[];
let gateStatus: number;

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
      if (key === 'GET /api/auth/me') return json(200, { user: me, settings, server, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: me.is_child ? { id: 1, display_name: 'Mom' } : null, gate_until: null } });
      if (key === 'POST /api/guardian/gate') {
        if (gateStatus === 401) return json(401, { error: { code: 'invalid_pin', message: '' } });
        if (gateStatus === 423) return json(423, { error: { code: 'account_locked', message: '', details: { retry_after_s: 900 } } });
        return json(200, { gate_until: '2026-11-10T08:10:00Z' });
      }
      if (key === 'POST /api/account/code') return json(202, { sent: true, expires_in_s: 600 });
      if (key === 'POST /api/auth/switch/code') return json(202, { sent: true, expires_in_s: 600 });
      if (key === 'POST /api/auth/switch/back') {
        me = guardian;
        return json(200, { user: guardian, settings });
      }
      return json(404, { error: { code: 'not_found', message: '' } });
    }),
  );
}

function Probe() {
  const { user } = useAuth();
  return <div data-testid="who">{user?.username ?? '-'}</div>;
}

function renderGate(props: Partial<GateDialogProps> = {}) {
  const onClose = vi.fn();
  const onPassed = vi.fn();
  const onSwitched = vi.fn();
  render(
    <MemoryRouter>
      <ToastProvider>
        <AuthProvider>
          <Probe />
          <GateDialog open mode="gate" pinSet hasPassword onClose={onClose} onPassed={onPassed} onSwitched={onSwitched} {...props} />
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
  return { onClose, onPassed, onSwitched };
}

const radios = () => screen.getAllByRole('radio').map((r) => r.textContent);
const verify = () => screen.getByRole('button', { name: zh.children.gateVerify }) as HTMLButtonElement;
const pinInput = () => screen.getByLabelText(new RegExp(`^${zh.children.pin}`)) as HTMLInputElement;

describe('GateDialog', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('offers only the factors the guardian holds in gate mode and all three in switch-back mode', () => {
    expect(gateFactors('gate', true, true)).toEqual(['pin', 'password', 'code']);
    expect(gateFactors('gate', false, true)).toEqual(['password', 'code']);
    expect(gateFactors('gate', false, false)).toEqual(['code']);
    expect(gateFactors('switch-back', false, false)).toEqual(['pin', 'password', 'code']);
  });

  it('gate mode: three factors, a wrong PIN reads errors.invalidPin and clears the input, a lockout names the wait, a pass reports gate_until', async () => {
    calls = [];
    me = guardian;
    gateStatus = 401;
    installFetch();
    const { onPassed } = renderGate();
    expect(await screen.findByRole('heading', { name: zh.children.gateTitle })).toBeTruthy();
    expect(radios()).toEqual([zh.children.gatePin, zh.children.gatePassword, zh.children.gateCode]);
    expect(verify().disabled).toBe(true);
    fireEvent.change(pinInput(), { target: { value: '27491' } });
    expect(verify().disabled).toBe(true); // six digits needed
    fireEvent.change(pinInput(), { target: { value: '274913' } });
    fireEvent.click(verify());
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.invalidPin);
    expect(pinInput().value).toBe('');
    gateStatus = 423;
    fireEvent.change(pinInput(), { target: { value: '274913' } });
    fireEvent.click(verify());
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe(zh.errors.accountLocked(900)));
    gateStatus = 200;
    fireEvent.change(pinInput(), { target: { value: '274913' } });
    fireEvent.click(verify());
    await waitFor(() => expect(onPassed).toHaveBeenCalledWith('2026-11-10T08:10:00Z'));
    expect(calls.filter((c) => c.path === '/api/guardian/gate').map((c) => c.body)).toEqual([{ pin: '274913' }, { pin: '274913' }, { pin: '274913' }]);
  });

  it('gate mode without a PIN offers the password and the code; the code goes through endpoint 85 reauth to the chosen channel', async () => {
    calls = [];
    me = guardian;
    gateStatus = 200;
    installFetch();
    const { onPassed } = renderGate({ pinSet: false });
    await screen.findByRole('heading', { name: zh.children.gateTitle });
    expect(radios()).toEqual([zh.children.gatePassword, zh.children.gateCode]);
    fireEvent.click(screen.getByRole('radio', { name: zh.children.gateCode }));
    // both of the guardian's own channels are offered, the masked targets as labels
    expect(screen.getByRole('radio', { name: '138****8000' })).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: 'mom@example.com' }));
    fireEvent.click(screen.getByRole('button', { name: zh.auth.sendCode }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/code').map((c) => c.body)).toEqual([{ channel: 'email', purpose: 'reauth' }]));
    fireEvent.change(screen.getByRole('textbox', { name: new RegExp(`^${zh.auth.code}`) }), { target: { value: '123456' } });
    fireEvent.click(verify());
    await waitFor(() => expect(onPassed).toHaveBeenCalledWith('2026-11-10T08:10:00Z'));
    expect(calls.filter((c) => c.path === '/api/guardian/gate').map((c) => c.body)).toEqual([{ code: '123456' }]);
  });

  it('switch-back mode: all three factors, the code through endpoint 106, then endpoint 105 installs the guardian session (applyAuth) and reports onSwitched', async () => {
    calls = [];
    me = child;
    gateStatus = 200;
    installFetch();
    const { onSwitched } = renderGate({ mode: 'switch-back', pinSet: false, hasPassword: false });
    await screen.findByRole('heading', { name: zh.children.gateTitle });
    expect(screen.getByTestId('who').textContent).toBe('u_tao00001');
    expect(radios()).toEqual([zh.children.gatePin, zh.children.gatePassword, zh.children.gateCode]);
    fireEvent.click(screen.getByRole('radio', { name: zh.children.gateCode }));
    expect(screen.getByRole('radio', { name: zh.auth.methodPhone })).toBeTruthy(); // generic labels: the guardian's identities are unknown here
    fireEvent.click(screen.getByRole('button', { name: zh.auth.sendCode }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/auth/switch/code').map((c) => c.body)).toEqual([{ channel: 'phone' }]));
    fireEvent.change(screen.getByRole('textbox', { name: new RegExp(`^${zh.auth.code}`) }), { target: { value: '654321' } });
    fireEvent.click(verify());
    await waitFor(() => expect(onSwitched).toHaveBeenCalledTimes(1));
    expect(calls.filter((c) => c.path === '/api/auth/switch/back').map((c) => c.body)).toEqual([{ code: '654321' }]);
    await waitFor(() => expect(screen.getByTestId('who').textContent).toBe('mom')); // the context holds the guardian now
    expect(calls.filter((c) => c.path === '/api/auth/logout')).toHaveLength(0);
  });

  it('renders nothing while closed', () => {
    calls = [];
    me = guardian;
    installFetch();
    renderGate({ open: false });
    expect(screen.queryByRole('heading', { name: zh.children.gateTitle })).toBeNull();
  });
});
