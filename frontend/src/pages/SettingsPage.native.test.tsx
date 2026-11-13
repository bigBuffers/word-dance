// SettingsPage inside the native shell (FRONTEND §6.6): the export links are not offered (a WebView cannot download them), the push
// section explains that the reminder is local, and switching push on asks for notification permission inside the gesture — a refusal
// is reported but the setting is still saved (the OS setting can be changed later). Slice 2-A (FRONTEND §5.8): the third-party
// login-methods rows follow `thirdPartyEntries` — in the Android shell only WeChat can be bound, in the iOS shell nothing, while an
// already-bound provider keeps its row for unbinding.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Settings, User } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import SettingsPage from './SettingsPage';

const native = vi.hoisted(() => ({
  platform: 'android' as 'ios' | 'android' | 'web',
  granted: true,
  permission: 'prompt' as 'granted' | 'denied' | 'prompt',
  // like the OS: a granted request is remembered by the later permission check
  request: vi.fn(async () => {
    if (native.granted) native.permission = 'granted';
    return native.granted;
  }),
  sync: vi.fn(async (_settings: unknown) => 'scheduled' as const),
}));
vi.mock('@/native/capacitor', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/native/capacitor')>()),
  isNative: () => true,
  nativePlatform: () => native.platform,
  requestReminderPermission: native.request,
  reminderPermission: async () => native.permission,
  syncDailyReminder: native.sync,
}));

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const baseUser: User = { id: 1, username: 'alice', display_name: 'alice', email: null, email_verified: false, role: 'user', onboarding_state: 'done', created_at: '2026-10-14T00:00:00Z', has_password: true, phone_masked: null, needs_profile: false, age_band: null, account_kind: 'learner', is_child: false, needs_profile_prompt: false, providers: [] };
const baseServer = { version: '0.1.0', registration_mode: 'open', email_configured: false, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, wechat_enabled: false, qq_enabled: false, apple_enabled: false };
let user: User = baseUser;
let server = baseServer;
let settings: Settings;
let puts: Record<string, unknown>[];

beforeEach(() => {
  native.platform = 'android';
  native.granted = true;
  native.permission = 'prompt';
  user = baseUser;
  server = baseServer;
  native.request.mockClear();
  native.sync.mockClear();
  puts = [];
  settings = {
    stages: ['xs'], current_stage: 'xs', timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, email_enabled: false, email_verified: false,
    webhook_enabled: false, webhook_url: null, webhook_format: 'generic', daily_new_count: 5, daily_screen_count: 5, max_reviews: 60,
    show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', image_word: true, next_push_at: null,
  } as unknown as Settings;
  vi.stubGlobal(
    'fetch',
    vi.fn<typeof fetch>(async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      const path = url.split('?')[0] ?? url;
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'GET' && path === '/api/auth/me') return json(200, { user, settings, server, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: null } });
      if (method === 'GET' && path === '/api/settings/timezones') return json(200, { items: ['Asia/Shanghai'] });
      if (method === 'PUT' && path === '/api/settings') {
        const changes = JSON.parse(String(init?.body)) as Record<string, unknown>;
        puts.push(changes);
        settings = { ...settings, ...(changes as Partial<Settings>) };
        return json(200, settings);
      }
      return json(404, { error: { code: 'not_found', message: '' } });
    }),
  );
});

afterEach(() => vi.unstubAllGlobals());

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

describe('SettingsPage in the native shell', () => {
  it('hides the export links and explains the local reminder', async () => {
    renderSettings();
    await screen.findByText(zh.settings.nativeReminderHint);
    expect(screen.queryByText(zh.settings.export)).toBeNull();
    expect(screen.queryByText(zh.settings.exportCsv)).toBeNull();
    expect(screen.getAllByText(zh.settings.import).length).toBeGreaterThan(0); // importing a file still works in a WebView
  });

  it('asks for notification permission when push is switched on and saves either way', async () => {
    renderSettings();
    const toggle = await screen.findByRole('switch', { name: zh.settings.pushEnabled });
    fireEvent.click(toggle);
    await waitFor(() => expect(puts).toEqual([{ push_enabled: true }]));
    expect(native.request).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(zh.settings.reminderDenied)).toBeNull();
    // switching off never asks
    fireEvent.click(screen.getByRole('switch', { name: zh.settings.pushEnabled }));
    await waitFor(() => expect(puts).toHaveLength(2));
    expect(native.request).toHaveBeenCalledTimes(1);
  });

  it('reports a refused permission and still saves the setting', async () => {
    native.granted = false;
    renderSettings();
    fireEvent.click(await screen.findByRole('switch', { name: zh.settings.pushEnabled }));
    expect((await screen.findAllByText(zh.settings.reminderDenied)).length).toBeGreaterThan(0); // the toast, and the row with the button
    await waitFor(() => expect(puts).toEqual([{ push_enabled: true }]));
    expect(await screen.findByRole('button', { name: zh.settings.allowNotifications })).toBeTruthy();
  });

  it('offers the permission button to a learner whose push was already on, and arms the reminder once granted', async () => {
    settings = { ...settings, push_enabled: true };
    renderSettings();
    const allow = await screen.findByRole('button', { name: zh.settings.allowNotifications });
    expect(screen.getByText(zh.settings.reminderDenied)).toBeTruthy();
    expect(native.request).not.toHaveBeenCalled(); // never prompted from a render, only from the button
    fireEvent.click(allow);
    await waitFor(() => expect(native.sync).toHaveBeenCalledTimes(1));
    expect(native.request).toHaveBeenCalledTimes(1);
    expect(native.sync.mock.calls[0]![0]).toMatchObject({ push_enabled: true, push_time: '08:00', timezone: 'Asia/Shanghai' });
    await waitFor(() => expect(screen.queryByRole('button', { name: zh.settings.allowNotifications })).toBeNull());
    expect(puts).toEqual([]); // nothing to save: the setting was already on
  });

  it('shows no permission button when the OS already granted notifications', async () => {
    settings = { ...settings, push_enabled: true };
    native.permission = 'granted';
    renderSettings();
    await screen.findByText(zh.settings.nativeReminderHint);
    expect(screen.queryByRole('button', { name: zh.settings.allowNotifications })).toBeNull();
    expect(screen.queryByText(zh.settings.reminderDenied)).toBeNull();
  });
});

describe('SettingsPage in the native shell · third-party login methods (FRONTEND §5.8, slice 2-A)', () => {
  const accountSection = async () => (await screen.findByRole('heading', { name: zh.settings.account })).closest('section') as HTMLElement;
  /** The login-methods row of a provider (its label is the row's first span), or null. */
  const providerRow = (section: HTMLElement, label: string) => {
    const span = within(section).queryByText(label, { selector: '.settings__row > span' });
    return span ? (span.closest('.settings__row') as HTMLElement) : null;
  };

  it('Android: only WeChat can be bound (a QQ / Apple redirect would open the system browser); a bound QQ keeps its row for unbinding, an unbound Apple has none', async () => {
    server = { ...baseServer, wechat_enabled: true, qq_enabled: true, apple_enabled: true };
    user = { ...baseUser, providers: ['qq'] };
    renderSettings();
    const section = await accountSection();
    const wechat = providerRow(section, zh.settings.providers.wechat_mini) as HTMLElement;
    expect(within(wechat).getByText(zh.settings.unbound)).toBeTruthy();
    expect(within(wechat).getByRole('button', { name: zh.settings.bind })).toBeTruthy();
    const qq = providerRow(section, zh.settings.providers.qq) as HTMLElement;
    expect(within(qq).getByText(zh.settings.bound)).toBeTruthy();
    expect(within(qq).getByRole('button', { name: zh.settings.unbind })).toBeTruthy();
    expect(providerRow(section, zh.settings.providers.apple)).toBeNull();
    expect(screen.queryByRole('link', { name: zh.settings.bind })).toBeNull(); // no redirect link anywhere in the shell
  });

  it('iOS: nothing can be bound (WeChat only next to Apple, Apple only on the web); a bound WeChat still has its unbind button', async () => {
    native.platform = 'ios';
    server = { ...baseServer, wechat_enabled: true, qq_enabled: true, apple_enabled: true };
    user = { ...baseUser, providers: ['wechat_mini'] };
    renderSettings();
    const section = await accountSection();
    const wechat = providerRow(section, zh.settings.providers.wechat_mini) as HTMLElement;
    expect(within(wechat).getByText(zh.settings.bound)).toBeTruthy();
    expect(within(wechat).getByRole('button', { name: zh.settings.unbind })).toBeTruthy();
    expect(within(wechat).queryByRole('button', { name: zh.settings.bind })).toBeNull();
    expect(providerRow(section, zh.settings.providers.qq)).toBeNull();
    expect(providerRow(section, zh.settings.providers.apple)).toBeNull();
    expect(within(section).queryByRole('link', { name: zh.settings.bind })).toBeNull(); // no redirect link anywhere in the shell
  });
});
