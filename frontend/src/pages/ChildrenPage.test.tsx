// ChildrenPage (FRONTEND §2 / §5.8, API.md 94–104): the list renders the children with their progress and devices, the guardian
// gate opens before the add sheet while `gate_until` is null and the action continues once endpoint 102 passed, a known stamp is
// attempted first (the server judges its age, never the device clock) and a 403 re-opens the gate with the sheet staying busy
// across it (one POST, never two), the PIN row is always gated (103), the add sheet posts endpoint 95 (the first child carries the
// PIN), the login-code sheet shows endpoint 99's digits grouped in fours, set free posts 100 then 101, the delete confirmation
// posts 97, the switch posts 104 and lands on /today, the readiness banner disables what needs the two-factor rule (with SMS off
// on the server it explains instead of linking to settings and set free is disabled), and a learner is sent to /settings.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChildAccount, ChildrenResponse, ServerFlags, Settings, User } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import ChildrenPage, { groupDigits, missingLabels } from './ChildrenPage';

const ISO = '2026-11-10T08:00:00Z';
const FUTURE = () => new Date(Date.now() + 600_000).toISOString();
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const guardian: User = {
  id: 1, username: 'mom', display_name: 'Mom', email: null, email_verified: false, role: 'user', onboarding_state: 'done', created_at: ISO,
  has_password: true, phone_masked: '138****8000', needs_profile: false, age_band: 'adult', account_kind: 'guardian', is_child: false, needs_profile_prompt: false, providers: [],
};
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: false, updated_at: ISO,
};
const server: ServerFlags = { version: '0.1.0', registration_mode: 'verified', email_configured: true, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', audio_zh: false, sms_enabled: true, wechat_enabled: false, qq_enabled: false, apple_enabled: false };
const child = (over: Partial<ChildAccount> = {}): ChildAccount => ({
  id: 4, display_name: 'Tao', username: null, has_password: false, phone_masked: null, age_band: 'u14', onboarding_state: 'pending', created_at: ISO, last_login_at: null,
  bank_size: 12, streak_days: 3, sessions: 1, ...over,
});

let user: User;
let items: ChildAccount[];
let gateUntil: string | null; // the mock server's stamp: null = no fresh stamp (it judges by its own clock, so any ISO value is "fresh")
let pinSet: boolean;
let ready: boolean;
let smsEnabled: boolean;
let holdCreate: Promise<void> | null; // when set, endpoint 95 answers only once it resolves
let calls: { method: string; path: string; body: Record<string, unknown> | null }[];

const gateRequired = () => json(403, { error: { code: 'guardian_gate_required', message: '' } });

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
      if (key === 'GET /api/auth/me') return json(200, { user, settings, server: { ...server, sms_enabled: smsEnabled }, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: gateUntil } });
      if (key === 'GET /api/guardian/children') {
        const res: ChildrenResponse = { items, pin_set: pinSet, ready, missing: ready ? [] : ['phone'], gate_until: gateUntil };
        return json(200, res);
      }
      if (key === 'POST /api/guardian/gate') {
        if (body?.['pin'] === '000000') return json(401, { error: { code: 'invalid_pin', message: '' } });
        gateUntil = FUTURE();
        return json(200, { gate_until: gateUntil });
      }
      if (key === 'POST /api/guardian/children') {
        if (gateUntil === null) return gateRequired();
        if (holdCreate) await holdCreate;
        const created = child({ id: items.length + 5, display_name: String(body?.['display_name']), username: typeof body?.['username'] === 'string' ? body['username'] : null });
        items = [...items, created];
        pinSet = true;
        return json(201, { child: created });
      }
      if (key === 'PUT /api/guardian/pin') {
        if (gateUntil === null) return gateRequired(); // 103 is always gated
        pinSet = true;
        return new Response(null, { status: 204 });
      }
      if (key === 'POST /api/guardian/children/4/login-code') return json(201, { code: '12345678', expires_in_s: 600 });
      if (key === 'POST /api/guardian/children/4/code') return json(202, { sent: true, expires_in_s: 600 });
      if (key === 'POST /api/guardian/children/4/emancipate') {
        items = items.filter((c) => c.id !== 4);
        return json(200, { child: child({ phone_masked: '139****9000', has_password: true, age_band: '14plus' }) });
      }
      if (key === 'DELETE /api/guardian/children/4') {
        items = items.filter((c) => c.id !== 4);
        return new Response(null, { status: 204 });
      }
      if (key === 'POST /api/auth/switch/4') {
        user = { ...guardian, id: 4, username: 'u_tao00001', display_name: 'Tao', account_kind: 'learner', is_child: true, age_band: 'u14', has_password: false, phone_masked: null };
        return json(200, { user, settings });
      }
      return json(404, { error: { code: 'not_found', message: '' } });
    }),
  );
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/children']}>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/children" element={<ChildrenPage />} />
            <Route path="/settings" element={<div>settings-page</div>} />
            <Route path="/today" element={<div>today-page</div>} />
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const card = (name: string) => screen.getByRole('listitem', { name }) as HTMLElement;
const openSheet = (): HTMLElement => {
  const sheets = [...document.querySelectorAll('dialog.sheet[open]')] as HTMLElement[];
  const last = sheets[sheets.length - 1];
  if (!last) throw new Error('no open sheet');
  return last;
};
const openConfirm = () => document.querySelector('dialog.confirm[open]') as HTMLElement;
const posted = (method: string, path: string) => calls.filter((c) => c.method === method && c.path === path);

describe('ChildrenPage', () => {
  beforeEach(() => {
    calls = [];
    user = guardian;
    items = [child(), child({ id: 6, display_name: 'Mei', username: 'mei2016', has_password: true, age_band: '14plus', last_login_at: ISO, sessions: 2, bank_size: 40, streak_days: 7 })];
    gateUntil = null;
    pinSet = true;
    ready = true;
    smsEnabled = true;
    holdCreate = null;
    installFetch();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('renders a card per child with the age chip, the progress line and the devices, and the hint', async () => {
    renderPage();
    const tao = await screen.findByRole('listitem', { name: 'Tao' });
    expect(within(tao).getByText(zh.children.u14)).toBeTruthy();
    expect(within(tao).getByText(new RegExp(zh.children.progress(12, 3)))).toBeTruthy();
    expect(within(tao).getByText(new RegExp(zh.children.neverLoggedIn))).toBeTruthy();
    expect(within(tao).getByText(zh.children.devices(1))).toBeTruthy();
    const mei = card('Mei');
    expect(within(mei).getByText(zh.children.plus14)).toBeTruthy();
    expect(within(mei).getByText('mei2016')).toBeTruthy();
    expect(within(mei).getByText(zh.children.devices(2))).toBeTruthy();
    expect(screen.getByText(zh.children.hint)).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.children.pinChange })).toBeTruthy(); // pin_set → change
    expect(screen.queryByRole('status', { name: '' })).toBeNull;
  });

  it('shows the empty state with one action when there are no children', async () => {
    items = [];
    renderPage();
    expect(await screen.findByText(zh.children.empty)).toBeTruthy();
    expect(screen.getAllByRole('button', { name: zh.children.add })).toHaveLength(1);
  });

  it('opens the guardian gate before the add sheet while gate_until is null, then continues after endpoint 102', async () => {
    items = [];
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: zh.children.add }));
    expect(await screen.findByRole('heading', { name: zh.children.gateTitle })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: zh.children.add })).toBeNull();
    // a PIN exists and the account has a password: three factors, the PIN first
    const radios = screen.getAllByRole('radio');
    expect(radios.map((r) => r.textContent)).toEqual([zh.children.gatePin, zh.children.gatePassword, zh.children.gateCode]);
    const pin = screen.getByLabelText(new RegExp(`^${zh.children.pin}`)) as HTMLInputElement;
    fireEvent.change(pin, { target: { value: '000000' } });
    fireEvent.click(screen.getByRole('button', { name: zh.children.gateVerify }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.errors.invalidPin); // 401 invalid_pin
    expect(pin.value).toBe('');
    fireEvent.change(pin, { target: { value: '274913' } });
    fireEvent.click(screen.getByRole('button', { name: zh.children.gateVerify }));
    expect(await screen.findByRole('heading', { name: zh.children.add })).toBeTruthy(); // the pending action ran
    expect(screen.queryByRole('heading', { name: zh.children.gateTitle })).toBeNull();
    expect(posted('POST', '/api/guardian/gate').map((c) => c.body)).toEqual([{ pin: '000000' }, { pin: '274913' }]);
  });

  it('posts endpoint 95 from the add sheet — the first child carries the PIN — and the list reloads', async () => {
    gateUntil = FUTURE();
    pinSet = false;
    renderPage();
    await screen.findByRole('listitem', { name: 'Tao' });
    expect(screen.getByRole('button', { name: zh.children.pinSet })).toBeTruthy(); // no PIN yet
    fireEvent.click(screen.getByRole('button', { name: zh.children.add }));
    const sheet = openSheet();
    expect(screen.queryByRole('heading', { name: zh.children.gateTitle })).toBeNull(); // the stamp is valid: no gate
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.displayName}`)), { target: { value: ' Xiao Bao ' } });
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.children.pin}`)), { target: { value: '274913' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.children.add }));
    await waitFor(() => expect(posted('POST', '/api/guardian/children').map((c) => c.body)).toEqual([{ display_name: 'Xiao Bao', pin: '274913' }]));
    expect(await screen.findByRole('listitem', { name: 'Xiao Bao' })).toBeTruthy();
    await waitFor(() => expect(document.querySelector('dialog.sheet[open]')).toBeNull());
  });

  it('a 403 guardian_gate_required from the action re-opens the gate and retries once after the pass; the sheet stays busy throughout', async () => {
    gateUntil = FUTURE(); // the client believes the stamp is valid…
    renderPage();
    await screen.findByRole('listitem', { name: 'Tao' });
    fireEvent.click(screen.getByRole('button', { name: zh.children.add }));
    const sheet = openSheet();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.displayName}`)), { target: { value: 'Bao' } });
    gateUntil = null; // …but the server's stamp expired meanwhile
    const submit = within(sheet).getByRole('button', { name: zh.children.add }) as HTMLButtonElement;
    fireEvent.click(submit);
    expect(await screen.findByRole('heading', { name: zh.children.gateTitle })).toBeTruthy();
    expect(submit.disabled).toBe(true); // the action waits behind the gate: no second submit possible
    expect(submit.getAttribute('aria-busy')).toBe('true');
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.children.pin}`)), { target: { value: '274913' } });
    fireEvent.click(screen.getByRole('button', { name: zh.children.gateVerify }));
    fireEvent.click(submit); // a tap during the retry hits a disabled button
    await waitFor(() => expect(posted('POST', '/api/guardian/children')).toHaveLength(2)); // 403, then the retry
    expect(await screen.findByRole('listitem', { name: 'Bao' })).toBeTruthy();
    await waitFor(() => expect(document.querySelector('dialog.sheet[open]')).toBeNull()); // the sheet closed once the child existed
    expect(posted('POST', '/api/guardian/children')).toHaveLength(2);
  });

  it('dismissing the gate releases the waiting sheet: the button is usable again and nothing was posted', async () => {
    gateUntil = FUTURE();
    renderPage();
    await screen.findByRole('listitem', { name: 'Tao' });
    fireEvent.click(screen.getByRole('button', { name: zh.children.add }));
    const sheet = openSheet();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.displayName}`)), { target: { value: 'Bao' } });
    gateUntil = null;
    const submit = within(sheet).getByRole('button', { name: zh.children.add }) as HTMLButtonElement;
    fireEvent.click(submit);
    const gateSheet = (await screen.findByRole('heading', { name: zh.children.gateTitle })).closest('dialog') as HTMLElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(within(gateSheet).getByRole('button', { name: zh.common.close }));
    await waitFor(() => expect(submit.disabled).toBe(false));
    expect(screen.queryByRole('heading', { name: zh.children.gateTitle })).toBeNull();
    expect(screen.getByRole('heading', { name: zh.children.add })).toBeTruthy(); // the add sheet is still there with its input
    expect(posted('POST', '/api/guardian/children')).toHaveLength(1); // only the 403
  });

  it('the add sheet stays busy until endpoint 95 answers: a second tap cannot post twice', async () => {
    gateUntil = FUTURE();
    let release: () => void = () => undefined;
    holdCreate = new Promise<void>((resolve) => {
      release = resolve;
    });
    renderPage();
    await screen.findByRole('listitem', { name: 'Tao' });
    fireEvent.click(screen.getByRole('button', { name: zh.children.add }));
    const sheet = openSheet();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.displayName}`)), { target: { value: 'Bao' } });
    const submit = within(sheet).getByRole('button', { name: zh.children.add }) as HTMLButtonElement;
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(posted('POST', '/api/guardian/children')).toHaveLength(1));
    expect(submit.disabled).toBe(true);
    expect(submit.getAttribute('aria-busy')).toBe('true');
    release();
    expect(await screen.findByRole('listitem', { name: 'Bao' })).toBeTruthy();
    await waitFor(() => expect(document.querySelector('dialog.sheet[open]')).toBeNull());
    expect(posted('POST', '/api/guardian/children')).toHaveLength(1);
  });

  it('a stamp the device clock already considers expired is still attempted: the server judges the stamp, not the device', async () => {
    gateUntil = new Date(Date.now() - 3_600_000).toISOString(); // the device clock runs an hour ahead of the server's
    renderPage();
    await screen.findByRole('listitem', { name: 'Tao' });
    fireEvent.click(screen.getByRole('button', { name: zh.children.add }));
    expect(screen.queryByRole('heading', { name: zh.children.gateTitle })).toBeNull();
    const sheet = openSheet();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.displayName}`)), { target: { value: 'Bao' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.children.add }));
    expect(await screen.findByRole('listitem', { name: 'Bao' })).toBeTruthy();
    expect(posted('POST', '/api/guardian/gate')).toHaveLength(0);
  });

  it('the PIN row goes through the gate even before a PIN exists (103 is always gated); the PIN sheet follows the pass and posts 103', async () => {
    pinSet = false;
    renderPage();
    await screen.findByRole('listitem', { name: 'Tao' });
    fireEvent.click(screen.getByRole('button', { name: zh.children.pinSet }));
    expect(await screen.findByRole('heading', { name: zh.children.gateTitle })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: zh.children.pin })).toBeNull(); // the PIN sheet waits behind the gate
    expect(screen.getAllByRole('radio').map((r) => r.textContent)).toEqual([zh.children.gatePassword, zh.children.gateCode]); // no PIN to offer
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.auth.password}`)), { target: { value: 'secret-pass' } });
    fireEvent.click(screen.getByRole('button', { name: zh.children.gateVerify }));
    expect(await screen.findByRole('heading', { name: zh.children.pin })).toBeTruthy();
    expect(screen.queryByRole('heading', { name: zh.children.gateTitle })).toBeNull();
    const sheet = openSheet();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.children.pin}`)), { target: { value: '274913' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.children.pinSet }));
    await waitFor(() => expect(posted('PUT', '/api/guardian/pin').map((c) => c.body)).toEqual([{ pin: '274913' }]));
    expect(await screen.findByText(zh.children.pinSaved)).toBeTruthy();
    await waitFor(() => expect(document.querySelector('dialog.sheet[open]')).toBeNull());
    expect(await screen.findByRole('button', { name: zh.children.pinChange })).toBeTruthy(); // the list reloaded with pin_set
    expect(posted('POST', '/api/guardian/gate').map((c) => c.body)).toEqual([{ password: 'secret-pass' }]);
  });

  it('the login-code sheet shows endpoint 99 digits grouped in fours with the validity hint and a regenerate button', async () => {
    gateUntil = FUTURE();
    renderPage();
    fireEvent.click(within(await screen.findByRole('listitem', { name: 'Tao' })).getByRole('button', { name: zh.children.loginCode }));
    expect(await screen.findByText('1234 5678')).toBeTruthy();
    expect(screen.getByText(zh.children.codeHint)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.children.regenerate }));
    await waitFor(() => expect(posted('POST', '/api/guardian/children/4/login-code')).toHaveLength(2));
  });

  it('set free sends the code to the phone (100) and then posts phone + code + password (101); the card leaves the list', async () => {
    gateUntil = FUTURE();
    renderPage();
    fireEvent.click(within(await screen.findByRole('listitem', { name: 'Tao' })).getByRole('button', { name: zh.children.manage }));
    const manage = openSheet();
    fireEvent.click(within(manage).getByRole('button', { name: zh.children.emancipate }));
    const sheet = openSheet();
    expect(within(sheet).getByText(zh.children.emancipateLead)).toBeTruthy();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.children.childPhone}`)), { target: { value: '13900139000' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.auth.sendCode }));
    await waitFor(() => expect(posted('POST', '/api/guardian/children/4/code').map((c) => c.body)).toEqual([{ target: '+8613900139000' }]));
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.code}`)), { target: { value: '123456' } });
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.newPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.children.emancipate }));
    await waitFor(() => expect(posted('POST', '/api/guardian/children/4/emancipate').map((c) => c.body)).toEqual([{ target: '+8613900139000', code: '123456', password: 'Str0ng-Passphrase!' }]));
    await waitFor(() => expect(screen.queryByRole('listitem', { name: 'Tao' })).toBeNull());
    expect(await screen.findByText(zh.children.emancipated)).toBeTruthy();
  });

  it('delete asks for confirmation and posts endpoint 97', async () => {
    gateUntil = FUTURE();
    renderPage();
    fireEvent.click(within(await screen.findByRole('listitem', { name: 'Tao' })).getByRole('button', { name: zh.children.manage }));
    fireEvent.click(within(openSheet()).getByRole('button', { name: zh.children.deleteChild }));
    const confirm = openConfirm();
    expect(within(confirm).getByText(zh.children.deleteConfirm)).toBeTruthy();
    fireEvent.click(within(confirm).getByRole('button', { name: zh.common.confirm }));
    await waitFor(() => expect(posted('DELETE', '/api/guardian/children/4')).toHaveLength(1));
    await waitFor(() => expect(screen.queryByRole('listitem', { name: 'Tao' })).toBeNull());
    expect(screen.getByRole('listitem', { name: 'Mei' })).toBeTruthy();
  });

  it('switch posts endpoint 104 without a gate and lands on /today', async () => {
    renderPage(); // gate_until null: the switch needs no stamp
    fireEvent.click(within(await screen.findByRole('listitem', { name: 'Tao' })).getByRole('button', { name: zh.children.switchTo }));
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(posted('POST', '/api/auth/switch/4')).toHaveLength(1);
    expect(posted('POST', '/api/guardian/gate')).toHaveLength(0);
  });

  it('the readiness banner names what is missing and disables the actions that need it; with SMS on it links to settings', async () => {
    ready = false;
    renderPage();
    const tao = await screen.findByRole('listitem', { name: 'Tao' });
    expect(screen.getByRole('status').textContent).toBe(`${zh.children.notReady}${zh.children.missingPhone}${zh.children.goSettings}`);
    expect(screen.getByRole('link', { name: zh.children.goSettings }).getAttribute('href')).toBe('/settings');
    expect(screen.queryByText(zh.children.smsOffHint)).toBeNull();
    expect((within(tao).getByRole('button', { name: zh.children.switchTo }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(tao).getByRole('button', { name: zh.children.loginCode }) as HTMLButtonElement).disabled).toBe(true);
    expect((within(tao).getByRole('button', { name: zh.children.manage }) as HTMLButtonElement).disabled).toBe(false);
    expect((screen.getByRole('button', { name: zh.children.add }) as HTMLButtonElement).disabled).toBe(true);
    // set free needs readiness too: disabled in the manage sheet, the banner's text as the reason
    fireEvent.click(within(tao).getByRole('button', { name: zh.children.manage }));
    const manage = openSheet();
    expect((within(manage).getByRole('button', { name: zh.children.emancipate }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(manage).getByRole('note').textContent).toBe(`${zh.children.notReady}${zh.children.missingPhone}`);
  });

  it('with SMS off on the server and the phone missing, the banner explains instead of linking to settings and set free is disabled', async () => {
    ready = false;
    smsEnabled = false;
    renderPage();
    const tao = await screen.findByRole('listitem', { name: 'Tao' });
    expect(screen.getByRole('status').textContent).toBe(`${zh.children.notReady}${zh.children.missingPhone}${zh.children.smsOffHint}`);
    expect(screen.queryByRole('link', { name: zh.children.goSettings })).toBeNull();
    fireEvent.click(within(tao).getByRole('button', { name: zh.children.manage }));
    const manage = openSheet();
    expect((within(manage).getByRole('button', { name: zh.children.emancipate }) as HTMLButtonElement).disabled).toBe(true);
    expect(within(manage).getByRole('note').textContent).toBe(zh.children.emancipateSmsOff);
    expect((within(manage).getByRole('button', { name: zh.children.revokeSessions }) as HTMLButtonElement).disabled).toBe(false); // the other actions stay
  });

  it('sends a learner to /settings with the forbidden toast', async () => {
    user = { ...guardian, account_kind: 'learner' };
    renderPage();
    expect(await screen.findByText('settings-page')).toBeTruthy();
    expect(await screen.findByText(zh.errors.forbidden)).toBeTruthy();
    expect(posted('GET', '/api/guardian/children')).toHaveLength(0);
  });
});

describe('helpers', () => {
  it('groupDigits and missingLabels format the copy', () => {
    expect(groupDigits('12345678')).toBe('1234 5678');
    expect(groupDigits('123456')).toBe('1234 56');
    expect(missingLabels(['phone', 'second_factor'])).toBe(`${zh.children.missingPhone} / ${zh.children.missingSecondFactor}`);
    expect(missingLabels([])).toBe('');
  });
});
