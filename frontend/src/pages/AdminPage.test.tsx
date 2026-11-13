// AdminPage (FRONTEND §5.8, API.md 54 / 56 / 92 / 93): the SMS tile reads `AdminOverview.sms` (the day count against the cap and
// whether new-account sends are still open), the users table marks accounts without a password and shows the masked phone, and
// the disputed-bindings card lists endpoint 92's rows with the restore action → endpoint 93 (the row leaves the list on success; a 409
// `identity_taken` is a toast and the row stays).
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { AdminHealth, AdminOverview, AdminUser, DisputedIdentity, Page, Settings, User } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';
import AdminPage from './AdminPage';

const ISO = '2026-11-10T08:00:00Z';
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

const admin: User = { id: 1, username: 'root', display_name: 'root', email: 'root@example.com', email_verified: true, role: 'admin', onboarding_state: 'done', created_at: ISO, has_password: true, phone_masked: null, needs_profile: false, age_band: 'adult', account_kind: 'learner', is_child: false, needs_profile_prompt: false, providers: [] };
const settings: Settings = {
  timezone: 'Asia/Shanghai', push_time: '08:00', push_enabled: false, daily_new_count: 10, daily_screen_count: 15, max_reviews: 60, stages: ['xs'], current_stage: 'xs',
  show_images: true, zh_examples: 'tap', auto_pronounce: false, accent: 'en-US', dance_mode: 'full', image_word: true, email_enabled: false, webhook_enabled: false, webhook_url: null, webhook_format: 'generic',
  next_push_at: null, email_verified: true, updated_at: ISO,
};
const me = () => json(200, { user: admin, settings, server: { version: '0.1.0', registration_mode: 'verified', email_configured: true, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', audio_zh: false, sms_enabled: true, wechat_enabled: false, qq_enabled: false, apple_enabled: false }, counters: { suggestions_open: 0, attention: 0 }, session: { guardian: null, gate_until: null } });

const overview: AdminOverview = {
  users: { total: 12, active_7d: 5 },
  words: { total: 6000, with_content: 600, with_photo: 100, with_claude_svg: 400, card_only: 100, user_added: 3, pending_validation: 0 },
  bank_entries: 240,
  batches_today: 4,
  jobs: { queued: 2, running: 1, dead: 0, by_type: { generate_content: 2 } },
  ai: {
    enabled: true, paused_until: null, manual_paused_until: null, flag_tier: 1, today_usd: 0.12, month_usd: 1.5, daily_budget_usd: 2, monthly_budget_usd: 30,
    svg_today_usd: 0, svg_daily_budget_usd: 1, dance_today_usd: 0, dance_daily_budget_usd: 1, calls_today: 9, avg_cost_per_word_7d: 0.002, last_error: null,
    active_provider: 'claude', fallback_configured: true, fallback_paused_until: null, fallback_calls_today: 0, fallback_available: null,
  },
  images: { providers: [] },
  scheduler: { last_tick_at: ISO, alive: true },
  sms: { provider: 'aliyun_verify', sent_today: 150, daily_cap: 200, sent_hour: 7, hourly_cap: 40, registration_open: false },
  events_24h: [],
};
const health: AdminHealth = {
  db_ok: true, db_size_bytes: 1024, disk_free_bytes: 1 << 30, data_dir: '/data', scheduler_alive: true, scheduler_last_tick_at: ISO, claude_worker_alive: true, io_worker_alive: true,
  claude_bin: { path: '/usr/local/bin/claude', version: '2.0.0', ok: true, flag_tier: 1, last_probe_at: ISO }, seed_version: 'abc', migrations_version: 18, worker_lease: null, last_backup: null,
};
const users: Page<AdminUser> = {
  items: [
    { ...admin, id: 2, username: 'u_ab23cd45', display_name: 'Xiao Ming', email: null, email_verified: false, role: 'user', has_password: false, phone_masked: '138****8000', age_band: '14plus', is_active: true, last_login_at: ISO, bank_size: 12, streak_days: 3 },
    { ...admin, id: 3, username: 'mom', display_name: 'Mom', role: 'user', phone_masked: '139****9000', account_kind: 'guardian', is_active: true, last_login_at: ISO, bank_size: 0, streak_days: 0 },
    { ...admin, id: 4, username: 'u_tao00001', display_name: 'Tao', email: null, email_verified: false, role: 'user', has_password: false, age_band: 'u14', is_child: true, is_active: true, last_login_at: null, bank_size: 5, streak_days: 1 },
  ],
  page: 1, page_size: 50, total: 3,
};
const disputedRow: DisputedIdentity = { id: 7, user: { id: 2, username: 'u_ab23cd45', display_name: 'Xiao Ming' }, provider: 'phone', subject_masked: '138****8001', verified_at: ISO, last_login_at: null, disputed_at: ISO, current_user_id: 3 };
const disputed = (): Page<DisputedIdentity> => ({ items: [disputedRow], page: 1, page_size: 50, total: 1 });

type Handler = (init?: RequestInit) => Response;
function mockFetch(routes: Record<string, Handler>) {
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const path = url.split('?')[0] ?? url;
    const handler = routes[path];
    return Promise.resolve(handler ? handler(init) : json(404, { error: { code: 'not_found', message: '' } }));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}
const baseRoutes = (): Record<string, Handler> => ({
  '/api/auth/me': me,
  '/api/admin/overview': () => json(200, overview),
  '/api/admin/health': () => json(200, health),
  '/api/admin/users': () => json(200, users),
  '/api/admin/invites': () => json(200, { items: [] }),
  '/api/admin/identities/disputed': () => json(200, disputed()),
});

function renderAdmin() {
  return render(
    <MemoryRouter initialEntries={['/admin']}>
      <ToastProvider>
        <AuthProvider>
          <Routes>
            <Route path="/admin" element={<AdminPage />} />
          </Routes>
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>,
  );
}

/** The disputed-bindings card of the users tab, once its rows are in. */
async function openDisputedCard() {
  fireEvent.click(await screen.findByRole('tab', { name: zh.admin.tabs.users }));
  const card = (await screen.findByRole('heading', { name: zh.admin.disputed })).closest('section') as HTMLElement;
  const row = (await within(card).findByText('138****8001')).closest('tr') as HTMLElement;
  return { card, row };
}

describe('AdminPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear(); // the selected tab is a local preference
  });

  it('the SMS tile shows the day count against the cap, the hour count, the provider, and that new-account sends are stopped', async () => {
    mockFetch(baseRoutes());
    renderAdmin();
    const tile = (await screen.findByText('150 / 200')).closest('.tile') as HTMLElement;
    expect(within(tile).getByText(zh.admin.sms)).toBeTruthy();
    expect(tile.textContent).toContain(`${zh.admin.smsHour} 7 / 40`);
    expect(tile.textContent).toContain(zh.admin.smsRegistrationClosed);
    expect(tile.textContent).not.toContain(zh.admin.smsRegistrationOpen);
    expect(tile.textContent).toContain('aliyun_verify');
    expect(tile.className).toContain('tile--bad');
  });

  it('the SMS tile reads smsRegistrationOpen without the warning tone while registration_open is true', async () => {
    mockFetch({ ...baseRoutes(), '/api/admin/overview': () => json(200, { ...overview, sms: { ...overview.sms, sent_today: 20, registration_open: true } }) });
    renderAdmin();
    const tile = (await screen.findByText('20 / 200')).closest('.tile') as HTMLElement;
    expect(tile.textContent).toContain(zh.admin.smsRegistrationOpen);
    expect(tile.className).not.toContain('tile--bad');
  });

  it('the users table marks an account without a password and shows its masked phone', async () => {
    mockFetch(baseRoutes());
    renderAdmin();
    fireEvent.click(await screen.findByRole('tab', { name: zh.admin.tabs.users }));
    const row = (await screen.findByText('u_ab23cd45')).closest('tr') as HTMLElement;
    expect(within(row).getByText(zh.admin.noPassword)).toBeTruthy();
    expect(within(row).getByText('138****8000')).toBeTruthy();
    expect(within(row).getByText('Xiao Ming')).toBeTruthy();
    expect(within(row).queryByText(zh.admin.guardian)).toBeNull();
    expect(within(row).queryByText(zh.admin.child)).toBeNull();
  });

  it('the users table marks guardians and children with chips next to the role (slice 1-B)', async () => {
    mockFetch(baseRoutes());
    renderAdmin();
    fireEvent.click(await screen.findByRole('tab', { name: zh.admin.tabs.users }));
    const mom = (await screen.findByText('mom')).closest('tr') as HTMLElement;
    expect(within(mom).getByText(zh.admin.guardian)).toBeTruthy();
    expect(within(mom).queryByText(zh.admin.child)).toBeNull();
    const tao = (await screen.findByText('u_tao00001')).closest('tr') as HTMLElement;
    expect(within(tao).getByText(zh.admin.child)).toBeTruthy();
    expect(within(tao).getByText(zh.admin.noPassword)).toBeTruthy();
    expect(within(tao).queryByText(zh.admin.guardian)).toBeNull();
  });

  it('the disputed-bindings card lists endpoint 92 rows; restore posts endpoint 93, drops the row and toasts zh.admin.restored', async () => {
    const fetchMock = mockFetch({ ...baseRoutes(), '/api/admin/identities/7/restore': () => json(200, { ...disputedRow, disputed_at: null }) });
    renderAdmin();
    const { card, row } = await openDisputedCard();
    expect(within(row).getByText('#2')).toBeTruthy(); // the account that held the binding
    expect(within(row).getByText('#3')).toBeTruthy(); // the account holding the number now
    fireEvent.click(within(row).getByRole('button', { name: zh.admin.restore }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([u, init]) => String(u) === '/api/admin/identities/7/restore' && init?.method === 'POST')).toHaveLength(1));
    await waitFor(() => expect(within(card).queryByText('138****8001')).toBeNull());
    expect(within(card).getByText(zh.common.none)).toBeTruthy();
    expect(await screen.findByText(zh.admin.restored)).toBeTruthy();
  });

  it('a 409 identity_taken on restore is a toast and the row stays', async () => {
    mockFetch({ ...baseRoutes(), '/api/admin/identities/7/restore': () => json(409, { error: { code: 'identity_taken', message: 'the number is live elsewhere' } }) });
    renderAdmin();
    const { card, row } = await openDisputedCard();
    fireEvent.click(within(row).getByRole('button', { name: zh.admin.restore }));
    expect(await screen.findByText('the number is live elsewhere')).toBeTruthy(); // identity_taken shows the server's wording (it names the identity)
    expect(within(card).getByText('138****8001')).toBeTruthy();
    expect(screen.queryByText(zh.admin.restored)).toBeNull();
  });
});
