// Import reduction (API.md 11/75), the stage toggle, and the push-channel test buttons (FRONTEND §5.8): the webhook
// test is offered only once the switch is on AND a URL is saved (the server requires both), its failures are
// reported in zh (no transport text), and the queued test e-mail is announced as queued, not as a success.
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Settings, User } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import SettingsPage, { buildImportBody, toggleStageSetting, webhookFailureReason } from './SettingsPage';

const HOOK = 'https://hooks.example.com/x';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const user: User = { id: 1, username: 'alice', display_name: 'alice', email: 'a@example.com', email_verified: true, role: 'user', onboarding_state: 'done', created_at: '2026-10-14T00:00:00Z' };
const server = { version: '0.1.0', registration_mode: 'open', email_configured: true, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false };

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
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const testButton = () => screen.getByRole('button', { name: zh.settings.webhookTest }) as HTMLButtonElement;
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
    webhookTestResponse = { ok: true, http_status: 200, error: null };
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
      zh_examples: 'tap',
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

  it('a failed webhook test is reported in zh without the transport text', async () => {
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

  it('the test e-mail toast says the mail was queued, not that the test succeeded', async () => {
    renderSettings();
    fireEvent.click(await screen.findByRole('button', { name: zh.settings.emailTest }));
    expect(await screen.findByText(zh.settings.emailTestQueued)).toBeTruthy();
    expect(screen.queryByText(zh.settings.webhookOk)).toBeNull();
    expect(calls.filter((c) => c.path === '/api/settings/email/test').map((c) => c.status)).toEqual([202]);
  });
});

describe('webhookFailureReason', () => {
  it('maps a server-side failure to zh cause + action copy', () => {
    expect(webhookFailureReason({ http_status: 404, error: 'HTTP 404' })).toBe(zh.settings.webhookFailHttp(404));
    expect(webhookFailureReason({ http_status: null, error: 'rejected: cannot resolve hooks.example.com' })).toBe(zh.settings.webhookFailConnect);
    expect(webhookFailureReason({ http_status: null, error: null })).toBe(zh.settings.webhookFailConnect);
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
