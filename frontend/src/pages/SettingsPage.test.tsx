// Import reduction (API.md 11/75), the stage toggle, and the push-channel test buttons (FRONTEND §5.8): the webhook
// test is offered only once the switch is on AND a URL is saved (the server requires both), its failures are
// reported in zh from the response's closed-set `reason` (API.md 17; HTTP status / connection advice as the fallback,
// never the transport text), and the queued test e-mail is announced as queued, not as a success.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Settings, User } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { exportAccountUrl } from '@/api/endpoints';
import { zh } from '@/i18n/zh';
import SettingsPage, { buildImportBody, toggleStageSetting, webhookFailureReason } from './SettingsPage';

const HOOK = 'https://hooks.example.com/x';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const baseUser: User = { id: 1, username: 'alice', display_name: 'alice', email: 'a@example.com', email_verified: true, role: 'user', onboarding_state: 'done', created_at: '2026-10-14T00:00:00Z', has_password: true, phone_masked: null, needs_profile: false, age_band: null };
let user: User = baseUser;
const baseServer = { version: '0.1.0', registration_mode: 'open', email_configured: true, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', sms_enabled: false };
let server = baseServer;

let settings: Settings;
let calls: { method: string; path: string; body: unknown; status: number }[];
let webhookTestResponse: unknown;

function installFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      const path = url.split('?')[0] ?? url;
      const method = (init?.method ?? 'GET').toUpperCase();
      const body = typeof init?.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : null;
      const respond = (status: number, payload: unknown) => {
        calls.push({ method, path, body, status });
        return json(status, payload);
      };
      if (method === 'GET' && path === '/api/auth/me') return respond(200, { user, settings, server, counters: { suggestions_open: 0, attention: 0 } });
      if (method === 'GET' && path === '/api/settings/timezones') return respond(200, { items: ['Asia/Shanghai'] });
      if (method === 'PUT' && path === '/api/settings') {
        const changes = body ?? {};
        const enabled = 'webhook_enabled' in changes ? Boolean(changes['webhook_enabled']) : settings.webhook_enabled;
        const url_ = 'webhook_url' in changes ? (changes['webhook_url'] as string | null) : settings.webhook_url;
        if (enabled && !url_) return respond(409, { error: { code: 'webhook_unconfigured', message: '' } });
        settings = { ...settings, ...(changes as Partial<Settings>) };
        return respond(200, settings);
      }
      if (method === 'POST' && path === '/api/settings/webhook/test') {
        if (!settings.webhook_enabled || !settings.webhook_url) return respond(409, { error: { code: 'webhook_unconfigured', message: '' } });
        return respond(200, webhookTestResponse);
      }
      if (method === 'POST' && path === '/api/settings/email/test') return respond(202, { queued: true });
      // login methods (API.md 85-88): the code sends answer 202, bind / rebind / unbind answer the updated user
      if (method === 'POST' && path === '/api/account/code') return respond(202, { sent: true, expires_in_s: 600 });
      if (method === 'POST' && path === '/api/account/identities/phone') {
        user = { ...user, phone_masked: '138****8000' };
        return respond(200, { user });
      }
      if (method === 'DELETE' && path === '/api/account/identities/phone') {
        if (!user.has_password && !(user.email && user.email_verified)) return respond(409, { error: { code: 'last_login_method', message: '' } });
        user = { ...user, phone_masked: null };
        return respond(200, { user });
      }
      if (method === 'POST' && path === '/api/account/identities/phone/rebind') {
        user = { ...user, phone_masked: '139****9000' };
        return respond(200, { user });
      }
      if (method === 'DELETE' && path === '/api/account') return respond(204, undefined);
      if (method === 'POST' && path === '/api/auth/logout') return respond(204, undefined);
      if (method === 'GET' && path === '/api/health') return respond(200, { status: 'ok', version: '0.1.0', registration_mode: 'open', needs_setup: false, sms_enabled: true, email_enabled: true, captcha: false, time: '2026-10-14T00:00:00Z' });
      return respond(404, { error: { code: 'not_found', message: '' } });
    }),
  );
}

function renderSettings() {
  return render(
    <MemoryRouter initialEntries={['/settings']}>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/login" element={<div>login-page</div>} />
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const testButton = () => screen.getByRole('button', { name: zh.settings.webhookTest }) as HTMLButtonElement;

describe('in a browser (no native shell)', () => {
  beforeEach(() => {
    calls = [];
    user = baseUser;
    server = baseServer;
    settings = {
      stages: ['xs'], current_stage: 'xs', timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, email_enabled: false, email_verified: true,
      webhook_enabled: false, webhook_url: null, webhook_format: 'generic', daily_new_count: 5, daily_screen_count: 5, max_reviews: 60,
      show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', next_push_at: null,
    } as unknown as Settings;
    installFetch();
  });

  it('keeps the export links, shows no shell-only copy, and saves the push toggle without a permission flow', async () => {
    renderSettings();
    await screen.findByText(zh.settings.export);
    const links = screen.getAllByRole('link').filter((a) => a.getAttribute('download') !== null) as HTMLAnchorElement[];
    expect(links.map((a) => a.getAttribute('href'))).toEqual([exportAccountUrl('csv'), exportAccountUrl('json')]);
    expect(screen.queryByText(zh.settings.nativeReminderHint)).toBeNull();
    expect(screen.queryByRole('button', { name: zh.settings.allowNotifications })).toBeNull();
    fireEvent.click(screen.getByRole('switch', { name: zh.settings.pushEnabled }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ push_enabled: true }]));
    expect(screen.queryByText(zh.settings.reminderDenied)).toBeNull();
  });
});
const urlInput = () => screen.getByLabelText(zh.settings.webhookUrl) as HTMLInputElement;
const saveUrl = async () => {
  fireEvent.change(urlInput(), { target: { value: HOOK } });
  fireEvent.blur(urlInput());
  await waitFor(() => expect(settings.webhook_url).toBe(HOOK));
};
const enableWebhook = async () => {
  fireEvent.click(screen.getByRole('switch', { name: zh.settings.webhook }));
  await waitFor(() => expect(settings.webhook_enabled).toBe(true));
};

describe('push settings test buttons', () => {
  beforeEach(() => {
    calls = [];
    user = baseUser;
    server = baseServer;
    webhookTestResponse = { ok: true, http_status: 200, error: null, reason: null };
    settings = {
      timezone: 'Asia/Shanghai',
      push_time: '08:00',
      push_enabled: true,
      daily_new_count: 10,
      daily_screen_count: 15,
      max_reviews: 60,
      stages: ['cet4', 'cet6'],
      current_stage: 'cet4',
      show_images: true,
      zh_examples: 'tap', dance_mode: 'full',
      auto_pronounce: true,
      accent: 'en-US',
      email_enabled: true,
      webhook_enabled: false,
      webhook_url: null,
      webhook_format: 'generic',
      next_push_at: null,
      email_verified: true,
      updated_at: '2026-10-14T00:00:00Z',
    };
    installFetch();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('the webhook test stays disabled with a saved URL while the switch is off, and works once it is on', async () => {
    renderSettings();
    await screen.findByRole('button', { name: zh.settings.webhookTest });
    expect(testButton().disabled).toBe(true);
    await saveUrl();
    expect(calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ webhook_url: HOOK }]);
    expect(testButton().disabled).toBe(true); // server would answer 409 webhook_unconfigured
    expect(screen.getByText(zh.settings.webhookEnableFirst)).toBeTruthy();
    expect(screen.queryByText(zh.errors.webhookUnconfigured)).toBeNull();

    await enableWebhook();
    await waitFor(() => expect(testButton().disabled).toBe(false));
    expect(screen.queryByText(zh.settings.webhookEnableFirst)).toBeNull();
    fireEvent.click(testButton());
    expect(await screen.findByText(zh.settings.webhookOk)).toBeTruthy();
    expect(calls.filter((c) => c.path === '/api/settings/webhook/test').map((c) => c.status)).toEqual([200]);
  });

  it('a failed webhook test is reported in zh without the transport text (no reason → connection advice)', async () => {
    webhookTestResponse = { ok: false, http_status: null, error: 'request failed: ConnectError: [Errno 111] Connection refused' };
    renderSettings();
    await screen.findByRole('button', { name: zh.settings.webhookTest });
    await saveUrl();
    await enableWebhook();
    await waitFor(() => expect(testButton().disabled).toBe(false));
    fireEvent.click(testButton());
    expect(await screen.findByText(zh.settings.webhookFail(zh.settings.webhookFailConnect))).toBeTruthy();
    expect(screen.queryByText(/ConnectError|Connection refused|request failed/)).toBeNull();
  });

  it('a failed webhook test names the server reason (dns_failed) in zh, never the English diagnostic', async () => {
    webhookTestResponse = { ok: false, http_status: null, error: 'rejected: cannot resolve hooks.example.com: [Errno -2] Name or service not known', reason: 'dns_failed' };
    renderSettings();
    await screen.findByRole('button', { name: zh.settings.webhookTest });
    await saveUrl();
    await enableWebhook();
    await waitFor(() => expect(testButton().disabled).toBe(false));
    fireEvent.click(testButton());
    expect(await screen.findByText(zh.settings.webhookFail(zh.settings.webhookFailDns))).toBeTruthy();
    expect(screen.queryByText(zh.settings.webhookFail(zh.settings.webhookFailConnect))).toBeNull();
    expect(screen.queryByText(/rejected|cannot resolve|Name or service/)).toBeNull();
  });

  it('the test e-mail toast says the mail was queued, not that the test succeeded', async () => {
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.emailTest }));
    expect(await screen.findByText(zh.settings.emailTestQueued)).toBeTruthy();
    expect(screen.queryByText(zh.settings.webhookOk)).toBeNull();
    expect(calls.filter((c) => c.path === '/api/settings/email/test').map((c) => c.status)).toEqual([202]);
  });
});

describe('webhookFailureReason', () => {
  const failed = { http_status: null, error: 'request failed: ConnectError: something went wrong' };

  it('keys on the closed-set reason first (API.md 17), one precise zh cause + action per value', () => {
    expect(webhookFailureReason({ ...failed, reason: 'dns_failed' })).toBe(zh.settings.webhookFailDns);
    expect(webhookFailureReason({ ...failed, reason: 'host_not_public' })).toBe(zh.settings.webhookFailPrivate);
    expect(webhookFailureReason({ ...failed, reason: 'connect_failed' })).toBe(zh.settings.webhookFailConnect);
    expect(webhookFailureReason({ ...failed, reason: 'timeout' })).toBe(zh.settings.webhookFailTimeout);
    expect(webhookFailureReason({ ...failed, reason: 'tls_failed' })).toBe(zh.settings.webhookFailTls);
    expect(webhookFailureReason({ ...failed, reason: 'invalid_url' })).toBe(zh.settings.webhookFailInvalidUrl);
    expect(webhookFailureReason({ http_status: 404, error: 'HTTP 404', reason: 'http_error' })).toBe(zh.settings.webhookFailHttp(404));
    const copies = new Set([zh.settings.webhookFailDns, zh.settings.webhookFailPrivate, zh.settings.webhookFailConnect, zh.settings.webhookFailTimeout, zh.settings.webhookFailTls, zh.settings.webhookFailInvalidUrl]);
    expect(copies.size).toBe(6); // every reason reads differently
  });

  it('falls back to the HTTP status, then the connection advice, and never echoes `error`', () => {
    expect(webhookFailureReason({ http_status: 404, error: 'HTTP 404' })).toBe(zh.settings.webhookFailHttp(404));
    expect(webhookFailureReason({ http_status: null, error: 'rejected: cannot resolve hooks.example.com' })).toBe(zh.settings.webhookFailConnect);
    expect(webhookFailureReason({ http_status: null, error: null })).toBe(zh.settings.webhookFailConnect);
    expect(webhookFailureReason({ http_status: null, error: null, reason: null })).toBe(zh.settings.webhookFailConnect);
    expect(webhookFailureReason({ http_status: null, error: 'HTTP ?', reason: 'http_error' })).toBe(zh.settings.webhookFailConnect); // no status to show
    for (const reason of ['dns_failed', 'host_not_public', 'connect_failed', 'timeout', 'tls_failed', 'invalid_url', 'http_error'] as const) {
      expect(webhookFailureReason({ http_status: 502, error: 'request failed: ConnectError: boom', reason })).not.toContain('ConnectError');
    }
  });
});

const fakeFile = (name: string, text: string) => ({ name, text: () => Promise.resolve(text) });

describe('buildImportBody', () => {
  it('drops review_logs from a JSON export and keeps only {version, words}', async () => {
    const exportJson = JSON.stringify({
      version: 1,
      exported_at: '2026-10-14T00:00:00Z',
      username: 'alice',
      words: [{ word: 'abandon', state: 'learning', ease: 2.5 }],
      review_logs: Array.from({ length: 5000 }, (_, i) => ({ created_at: '2026-10-14T00:00:00Z', word: `w${i}`, action: 'good' })),
    });
    const body = await buildImportBody(fakeFile('word-dance-export-20261014.json', exportJson));
    expect(body?.format).toBe('json');
    expect(body?.data).toBe(JSON.stringify({ version: 1, words: [{ word: 'abandon', state: 'learning', ease: 2.5 }] }));
    expect(body!.data.length).toBeLessThan(exportJson.length / 10);
  });

  it('sniffs JSON without an extension, returns null for an unparsable or non-export file, and posts CSV verbatim', async () => {
    expect((await buildImportBody(fakeFile('export', '{"version":1,"words":[]}')))?.format).toBe('json');
    expect(await buildImportBody(fakeFile('x.json', '{not json'))).toBeNull();
    expect(await buildImportBody(fakeFile('x.json', JSON.stringify({ foo: 1 })))).toBeNull();
    expect(await buildImportBody(fakeFile('empty.csv', '   '))).toBeNull();
    const csv = 'word,phonetic,translation,state\nabandon,,give up,learning\n';
    expect(await buildImportBody(fakeFile('word-dance-export-20261014.csv', csv))).toEqual({ format: 'csv', data: csv });
  });
});

describe('toggleStageSetting', () => {
  it('keeps the list non-empty and the current stage inside it, in canonical order', () => {
    expect(toggleStageSetting(['cet4', 'cet6'], 'cet4', 'gk')).toEqual({ stages: ['gk', 'cet4', 'cet6'], current_stage: 'cet4' });
    expect(toggleStageSetting(['cet4', 'cet6'], 'cet4', 'cet4')).toEqual({ stages: ['cet6'], current_stage: 'cet6' });
    expect(toggleStageSetting(['cet6'], 'cet6', 'cet6')).toEqual({ stages: ['cet6'], current_stage: 'cet6' });
    expect(toggleStageSetting(['zk'], 'zk', 'cet6')).toEqual({ stages: ['zk', 'cet6'], current_stage: 'zk' });
  });
});

describe('learning settings · word dance (FRONTEND §5.8, §6.5)', () => {
  beforeEach(() => {
    calls = [];
    user = baseUser;
    server = baseServer;
    settings = {
      timezone: 'Asia/Shanghai',
      push_time: '08:00',
      push_enabled: true,
      daily_new_count: 10,
      daily_screen_count: 15,
      max_reviews: 60,
      stages: ['xs', 'zk'],
      current_stage: 'xs',
      show_images: true,
      zh_examples: 'tap',
      auto_pronounce: true,
      accent: 'en-US',
      dance_mode: 'full',
      email_enabled: false,
      webhook_enabled: false,
      webhook_url: null,
      webhook_format: 'generic',
      next_push_at: null,
      email_verified: true,
      updated_at: '2026-11-08T00:00:00Z',
    };
    installFetch();
  });
  afterEach(() => vi.unstubAllGlobals());

  it('the three-way control reflects dance_mode and saves form_only / off / full', async () => {
    renderSettings();
    const group = await screen.findByRole('radiogroup', { name: zh.settings.dance });
    const radio = (label: string) => within(group).getByRole('radio', { name: label }) as HTMLButtonElement;
    expect(within(group).getAllByRole('radio').map((r) => r.textContent)).toEqual([zh.settings.danceModes.full, zh.settings.danceModes.form_only, zh.settings.danceModes.off]);
    expect(radio(zh.settings.danceModes.full).getAttribute('aria-checked')).toBe('true');
    const hint = screen.getByText(zh.settings.danceHint);
    for (const r of within(group).getAllByRole('radio')) expect(r.getAttribute('aria-describedby')).toBe(hint.id); // the hint stays the control's description (the Switch had aria-describedby)
    fireEvent.click(radio(zh.settings.danceModes.form_only));
    await waitFor(() => expect(settings.dance_mode).toBe('form_only'));
    await waitFor(() => expect(radio(zh.settings.danceModes.form_only).getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(radio(zh.settings.danceModes.off));
    await waitFor(() => expect(settings.dance_mode).toBe('off'));
    expect(calls.filter((c) => c.method === 'PUT').map((c) => c.body)).toEqual([{ dance_mode: 'form_only' }, { dance_mode: 'off' }]);
    await waitFor(() => expect(radio(zh.settings.danceModes.off).getAttribute('aria-checked')).toBe('true'));
    fireEvent.click(radio(zh.settings.danceModes.full));
    await waitFor(() => expect(settings.dance_mode).toBe('full'));
  });
});

describe('account - login methods (FRONTEND 5.8, API.md 85-88, 7 / 8 with a code)', () => {
  const minimalSettings = () =>
    ({
      stages: ['xs'], current_stage: 'xs', timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, email_enabled: false, email_verified: true,
      webhook_enabled: false, webhook_url: null, webhook_format: 'generic', daily_new_count: 5, daily_screen_count: 5, max_reviews: 60,
      show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', next_push_at: null,
    }) as unknown as Settings;
  beforeEach(() => {
    calls = [];
    settings = minimalSettings();
    user = baseUser;
    server = { ...baseServer, sms_enabled: true };
    installFetch();
  });
  afterEach(() => vi.unstubAllGlobals());

  const dialogOf = (title: string) => screen.getByRole('heading', { name: title }).closest('dialog') as HTMLDialogElement;
  /** The send button of the `CodeField` labelled `label` inside `scope` (two code fields share one sheet in the rebind flow). */
  const codeSendButton = (scope: HTMLElement, label: string) =>
    within(within(scope).getByLabelText(new RegExp(`^${label}`), { selector: 'input' }).closest('.code-field') as HTMLElement).getByRole('button') as HTMLButtonElement;

  it('without SMS on the server the phone row is absent; with it, bind sends a bind_phone code to the new number and binds it', async () => {
    server = baseServer;
    const first = renderSettings();
    await screen.findByText(zh.settings.loginMethods);
    expect(screen.queryByText(zh.settings.unbound)).toBeNull(); // no phone row (the closed sheets are inaccessible)
    expect(screen.queryByRole('button', { name: zh.settings.bind })).toBeNull();
    expect(screen.getByRole('button', { name: zh.settings.changePassword })).toBeTruthy(); // has_password → change, not set
    expect(screen.getByText('alice', { selector: '.muted' })).toBeTruthy(); // the read-only username
    first.unmount();
    vi.unstubAllGlobals();

    server = { ...baseServer, sms_enabled: true };
    installFetch();
    renderSettings();
    expect(await screen.findByText(zh.settings.unbound)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.settings.bind }));
    const sheet = dialogOf(zh.settings.bindPhone);
    const send = within(sheet).getByRole('button', { name: zh.auth.sendCode }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.phone}`)), { target: { value: '13800138000' } });
    expect(send.disabled).toBe(false);
    fireEvent.click(send);
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/code').map((c) => c.body)).toEqual([{ channel: 'phone', purpose: 'bind_phone', target: '+8613800138000' }]));
    expect(await within(sheet).findByRole('button', { name: zh.auth.resendIn(60) })).toBeTruthy();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.code}`)), { target: { value: '123456' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.settings.bind }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/identities/phone').map((c) => c.body)).toEqual([{ target: '+8613800138000', code: '123456' }]));
    expect(await screen.findByText('138****8000')).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.settings.rebind })).toBeTruthy();
    expect(screen.getByRole('button', { name: zh.settings.unbind })).toBeTruthy();
  });

  it('unbind re-authenticates with the password (DELETE /api/account/identities/phone {password}) and the row returns to unbound', async () => {
    user = { ...baseUser, phone_masked: '138****8000' };
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.unbind }));
    const sheet = dialogOf(zh.settings.unbindPhone);
    expect(within(sheet).getByText(zh.settings.unbindHint)).toBeTruthy();
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.password}`)), { target: { value: 'secret123' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.settings.unbind }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => [c.path, c.body])).toEqual([['/api/account/identities/phone', { password: 'secret123' }]]));
    expect(await screen.findByText(zh.settings.unbound)).toBeTruthy();
  });

  it('an account without a password gets set-password through a reauth code (endpoint 85 -> 7 {code, new_password}) and a code-confirmed delete', async () => {
    user = { ...baseUser, has_password: false, phone_masked: '138****8000' };
    renderSettings();
    const setPw = await screen.findByRole('button', { name: zh.settings.setPassword });
    expect(screen.queryByRole('button', { name: zh.settings.changePassword })).toBeNull();
    expect(screen.getByText(zh.settings.noPasswordYet)).toBeTruthy();
    fireEvent.click(setPw);
    const sheet = dialogOf(zh.settings.setPassword);
    expect(within(sheet).queryByLabelText(new RegExp(`^${zh.settings.currentPassword}`))).toBeNull();
    // both channels (bound phone with SMS on, verified e-mail) → a choice, the phone first
    const via = within(sheet).getByRole('radiogroup', { name: zh.settings.reauthVia });
    expect(within(via).getAllByRole('radio').map((r) => r.textContent)).toEqual(['138****8000', 'a@example.com']);
    fireEvent.click(within(via).getByRole('radio', { name: 'a@example.com' }));
    fireEvent.click(within(sheet).getByRole('button', { name: zh.auth.sendCode }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/code').map((c) => c.body)).toEqual([{ channel: 'email', purpose: 'reauth' }]));
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.code}`), { selector: 'input' }), { target: { value: '654321' } });
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.newPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.common.save }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/password').map((c) => c.body)).toEqual([{ code: '654321', new_password: 'Str0ng-Passphrase!' }]));

    fireEvent.click(screen.getByRole('button', { name: zh.settings.deleteAccount }));
    const del = dialogOf(zh.settings.deleteAccount);
    expect(within(del).getByText(zh.settings.deleteConfirmCode)).toBeTruthy();
    expect(within(del).queryByLabelText(new RegExp(`^${zh.auth.password}`))).toBeNull();
    expect(within(del).getByLabelText(new RegExp(`^${zh.auth.code}`), { selector: 'input' })).toBeTruthy();
  });

  it('rebind: a code to the old number, a code to the new number, then both codes with the new number (endpoint 88) and the row shows it', async () => {
    user = { ...baseUser, phone_masked: '138****8000' };
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.rebind }));
    const sheet = dialogOf(zh.settings.rebindPhone);
    expect(within(sheet).getByText(zh.settings.rebindHint)).toBeTruthy();
    fireEvent.click(codeSendButton(sheet, zh.settings.oldPhoneCode));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/code').map((c) => c.body)).toEqual([{ channel: 'phone', purpose: 'rebind_phone' }]));
    const newSend = codeSendButton(sheet, zh.settings.newPhoneCode);
    expect(newSend.disabled).toBe(true); // no new number yet
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.newPhone}\\*?$`)), { target: { value: '13900139000' } });
    expect(newSend.disabled).toBe(false);
    fireEvent.click(newSend);
    await waitFor(() =>
      expect(calls.filter((c) => c.path === '/api/account/code').map((c) => c.body)).toEqual([
        { channel: 'phone', purpose: 'rebind_phone' },
        { channel: 'phone', purpose: 'bind_phone', target: '+8613900139000' },
      ]),
    );
    const submit = within(sheet).getByRole('button', { name: zh.settings.rebind }) as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.oldPhoneCode}`), { selector: 'input' }), { target: { value: '111111' } });
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.settings.newPhoneCode}`), { selector: 'input' }), { target: { value: '222222' } });
    expect(submit.disabled).toBe(false);
    fireEvent.click(submit);
    await waitFor(() =>
      expect(calls.filter((c) => c.path === '/api/account/identities/phone/rebind').map((c) => [c.method, c.body])).toEqual([['POST', { code_old: '111111', target_new: '+8613900139000', code_new: '222222' }]]),
    );
    expect(await screen.findByText('139****9000', { selector: '.muted' })).toBeTruthy();
    expect(await screen.findByText(zh.settings.phoneRebound)).toBeTruthy(); // toast
    expect(screen.queryByText('138****8000', { selector: '.muted' })).toBeNull();
  });

  it('an account without a password deletes itself with a reauth code (DELETE /api/account {code}) and lands on /login', async () => {
    user = { ...baseUser, has_password: false, phone_masked: '138****8000' };
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.deleteAccount }));
    const del = dialogOf(zh.settings.deleteAccount);
    fireEvent.click(within(del).getByRole('button', { name: zh.auth.sendCode }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/code').map((c) => c.body)).toEqual([{ channel: 'phone', purpose: 'reauth' }])); // the bound phone is the first channel
    fireEvent.change(within(del).getByLabelText(new RegExp(`^${zh.auth.code}`), { selector: 'input' }), { target: { value: '654321' } });
    fireEvent.click(within(del).getByRole('button', { name: zh.settings.deleteAccount }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account').map((c) => [c.method, c.body])).toEqual([['DELETE', { code: '654321' }]]));
    expect(await screen.findByText('login-page')).toBeTruthy();
    expect(calls.some((c) => c.method === 'POST' && c.path === '/api/auth/logout')).toBe(true);
  });

  it('unbinding the only login method (no password, no verified e-mail) is refused: 409 last_login_method → toast, the number stays', async () => {
    user = { ...baseUser, has_password: false, email: null, email_verified: false, phone_masked: '138****8000' };
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.unbind }));
    const sheet = dialogOf(zh.settings.unbindPhone);
    expect(within(sheet).queryByRole('radiogroup', { name: zh.settings.reauthVia })).toBeNull(); // the phone is the only channel
    expect(within(sheet).getByText(`${zh.settings.reauthVia} 138****8000`)).toBeTruthy();
    fireEvent.click(within(sheet).getByRole('button', { name: zh.auth.sendCode }));
    await waitFor(() => expect(calls.filter((c) => c.path === '/api/account/code').map((c) => c.body)).toEqual([{ channel: 'phone', purpose: 'reauth' }]));
    fireEvent.change(within(sheet).getByLabelText(new RegExp(`^${zh.auth.code}`), { selector: 'input' }), { target: { value: '654321' } });
    fireEvent.click(within(sheet).getByRole('button', { name: zh.settings.unbind }));
    await waitFor(() => expect(calls.filter((c) => c.method === 'DELETE').map((c) => [c.path, c.body, c.status])).toEqual([['/api/account/identities/phone', { code: '654321' }, 409]]));
    expect(await screen.findByText(zh.errors.lastLoginMethod)).toBeTruthy(); // toast
    expect(screen.getByText('138****8000', { selector: '.muted' })).toBeTruthy();
  });

  it('without a mail server the verified e-mail is not offered for the reauth code; with no channel at all the sheet says so instead of a code input', async () => {
    server = { ...baseServer, sms_enabled: true, email_configured: false };
    user = { ...baseUser, has_password: false, phone_masked: '138****8000' };
    const first = renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.setPassword }));
    let sheet = dialogOf(zh.settings.setPassword);
    expect(within(sheet).queryByRole('radiogroup', { name: zh.settings.reauthVia })).toBeNull(); // the e-mail dropped out → no choice
    expect(within(sheet).getByText(`${zh.settings.reauthVia} 138****8000`)).toBeTruthy();
    first.unmount();
    vi.unstubAllGlobals();

    user = { ...baseUser, has_password: false, phone_masked: null }; // a verified e-mail but no SMTP, no phone
    installFetch();
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.setPassword }));
    sheet = dialogOf(zh.settings.setPassword);
    expect(within(sheet).getByText(zh.settings.reauthUnavailable)).toBeTruthy();
    expect(within(sheet).queryByLabelText(new RegExp(`^${zh.auth.code}`), { selector: 'input' })).toBeNull();
    expect(within(sheet).queryByRole('button', { name: zh.auth.sendCode })).toBeNull();
    expect((within(sheet).getByRole('button', { name: zh.common.save }) as HTMLButtonElement).disabled).toBe(true);
  });
});
