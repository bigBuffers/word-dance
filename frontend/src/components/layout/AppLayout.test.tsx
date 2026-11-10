// Shell: TopNav + TabBar with the counters badge and the today dot (FRONTEND 2/4), bare on /study.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { MeResponse } from '@/api/endpoints';
import type { TodayResponse } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { zh } from '@/i18n/zh';
import { AppLayout, PASSWORD_BANNER_PREF, hasUngradedItems, resetTodayBadge, setTodayUngraded, useTodayUngraded } from './AppLayout';

const ISO = '2026-10-14T00:00:00Z';

const me = (over: Partial<MeResponse['user']> = {}, counters = { suggestions_open: 2, attention: 1 }): MeResponse => ({
  user: { id: 1, username: 'alice', display_name: 'Alice', email: null, email_verified: false, role: 'user', onboarding_state: 'done', created_at: ISO, has_password: true, phone_masked: null, needs_profile: false, age_band: null, ...over },
  settings: {
    timezone: 'Asia/Shanghai',
    push_time: '08:00',
    push_enabled: true,
    daily_new_count: 10,
    daily_screen_count: 15,
    max_reviews: 60,
    stages: ['cet4'],
    current_stage: 'cet4',
    show_images: true,
    zh_examples: 'tap', dance_mode: 'full',
    auto_pronounce: true,
    accent: 'en-US',
    email_enabled: false,
    webhook_enabled: false,
    webhook_url: null,
    webhook_format: 'generic',
    next_push_at: null,
    email_verified: false,
    updated_at: ISO,
  },
  server: { version: '0.1.0', registration_mode: 'invite', email_configured: false, ai_enabled: true, images_enabled: true, dev: false, needs_setup: false, audio: false, audio_key: '', sms_enabled: false },
  counters,
});

const today = (done: number, total: number): TodayResponse => ({
  status: 'published',
  local_date: '2026-10-14',
  push_time: '08:00',
  next_push_at: null,
  can_build_now: false,
  batch: {
    id: 1,
    local_date: '2026-10-14',
    timezone: 'Asia/Shanghai',
    status: 'published',
    trigger: 'scheduled',
    gradable: true,
    counts: { total, done, review: total, review_done: done, new: 0, new_done: 0, screen: 0, screen_done: 0, extra: 0, extra_done: 0, pending_content: 0, deferred_reviews: 0 },
    items: [],
    extra_rounds: 0,
    can_request_more: true,
    built_at: ISO,
    published_at: ISO,
    completed_at: null,
  },
  streak_days: 3,
  goal_met: false,
  added: null,
  previous_open_batch: null,
  suggestions_open: 2,
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

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

function renderShell(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/today" element={<div>today-page</div>} />
            <Route path="/study" element={<div>study-page</div>} />
            <Route path="/admin" element={<div>admin-page</div>} />
          </Route>
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AppLayout', () => {
  beforeEach(() => resetTodayBadge());
  afterEach(() => {
    vi.unstubAllGlobals();
    resetTodayBadge();
  });

  it('renders the five primary destinations in both navs with the bank badge from counters and the today dot from /api/today', async () => {
    const fetchMock = mockFetch({ '/api/auth/me': () => json(200, me()), '/api/today': () => json(200, today(3, 10)) });
    renderShell('/today');
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(screen.getAllByText(zh.nav.today)).toHaveLength(2); // TopNav + TabBar
    expect(screen.getAllByText(zh.nav.bank)).toHaveLength(2);
    expect(screen.queryByText(zh.nav.admin)).toBeNull();
    expect(screen.getAllByText('3')).toHaveLength(2); // suggestions_open 2 + attention 1
    await waitFor(() => expect(document.querySelectorAll('.tabbar__dot')).toHaveLength(2));
    expect(fetchMock.mock.calls.map(([u]) => String(u).split('?')[0])).toContain('/api/today');
  });

  it('shows the admin entry for admins and no dot when everything is graded', async () => {
    mockFetch({ '/api/auth/me': () => json(200, me({ role: 'admin' }, { suggestions_open: 0, attention: 0 })), '/api/today': () => json(200, today(10, 10)) });
    renderShell('/admin');
    expect(await screen.findByText('admin-page')).toBeTruthy();
    expect(screen.getAllByText(zh.nav.admin).length).toBeGreaterThan(0);
    expect(screen.queryByText('0')).toBeNull();
    await waitFor(() => expect(document.querySelectorAll('.tabbar__dot')).toHaveLength(0));
  });

  it('does not check /api/today before onboarding and hides the shell on /study', async () => {
    const fetchMock = mockFetch({ '/api/auth/me': () => json(200, me({ onboarding_state: 'screen' })) });
    const first = renderShell('/today');
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(fetchMock.mock.calls.map(([u]) => String(u))).not.toContain('/api/today');
    first.unmount();

    renderShell('/study');
    expect(await screen.findByText('study-page')).toBeTruthy();
    expect(document.querySelector('nav')).toBeNull();
    expect(document.querySelector('.app-shell--bare')).not.toBeNull();
  });

  it('asks a learner without a password to set one (dismissible), never an admin or an account with a password', async () => {
    mockFetch({ '/api/auth/me': () => json(200, me({ has_password: false })), '/api/today': () => json(200, today(10, 10)) });
    const first = renderShell('/today');
    const note = await screen.findByText(zh.auth.passwordBanner);
    expect(note).toBeTruthy();
    expect(screen.getByRole('link', { name: zh.auth.passwordBannerAction }).getAttribute('href')).toBe('/settings');
    fireEvent.click(within(note.closest('.app-banner') as HTMLElement).getByRole('button', { name: zh.common.close }));
    expect(screen.queryByText(zh.auth.passwordBanner)).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(PASSWORD_BANNER_PREF) ?? '0')).toBeGreaterThan(0);
    first.unmount();
    window.localStorage.removeItem(PASSWORD_BANNER_PREF);
    vi.unstubAllGlobals();

    mockFetch({ '/api/auth/me': () => json(200, me({ has_password: false, role: 'admin' })), '/api/today': () => json(200, today(10, 10)) });
    const second = renderShell('/admin');
    await screen.findByText('admin-page');
    expect(screen.queryByText(zh.auth.passwordBanner)).toBeNull();
    second.unmount();
    vi.unstubAllGlobals();

    mockFetch({ '/api/auth/me': () => json(200, me()), '/api/today': () => json(200, today(10, 10)) });
    renderShell('/today');
    await screen.findByText('today-page');
    expect(screen.queryByText(zh.auth.passwordBanner)).toBeNull();
  });

  it('exposes the today badge store to pages', () => {
    expect(hasUngradedItems(today(3, 10))).toBe(true);
    expect(hasUngradedItems(today(10, 10))).toBe(false);
    expect(hasUngradedItems({ batch: null })).toBe(false);
    function Probe() {
      return <span>{useTodayUngraded() ? 'dot' : 'none'}</span>;
    }
    render(<Probe />);
    expect(screen.getByText('none')).toBeTruthy();
    act(() => setTodayUngraded(true));
    expect(screen.getByText('dot')).toBeTruthy();
  });
});
