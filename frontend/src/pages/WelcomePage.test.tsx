// FRONTEND §5.4 on /welcome step 2: one physical key press (keydown + OS auto-repeat keydowns) judges exactly
// one card, a double tap on a verdict button cannot judge the card that advanced under the finger, and the
// known toast / progress line use the shared screening copy. Step 1 (PLAN §6 S4): five roles whose presets keep
// the main stage inside the target stages, and the K-12 default that mirrors the server before any pick. Step 0
// (API.md 89): nickname + age band → the profile; a 409 `invalid_transition` (saved in another tab) refreshes the
// session and moves on; a 400 `validation_error` shows the server's field message; while the server has SMS off a note under
// the declarations says a guardian account needs it. Finish (endpoint 20) lands a learner on /today and a guardian on /children.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/api/client';
import * as endpoints from '@/api/endpoints';
import type { User } from '@/api/types';
import { ToastProvider } from '@/components/ui/Toast';
import { STAGE_ORDER } from '@/components/word/StageChips';
import { TAP_LOCK_MS } from '@/hooks/useTapLock';
import { zh } from '@/i18n/zh';

const h = vi.hoisted(() => {
  const card = (id: number) => ({
    word: {
      id,
      lemma: `word${id}`,
      display: `word${id}`,
      kind: 'word',
      phonetic: null,
      translation_short: `zh${id}`,
      stages: ['cet4'],
      stage_min: 4,
      cet6_star: false,
      frq: null,
      collins: null,
      oxford: null,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: null,
      content_state: 'ready',
      image_state: 'none',
    },
    phonetic: null,
  });
  const screenUser = { id: 1, username: 'u', display_name: 'u', email: null as string | null, email_verified: false, role: 'user', onboarding_state: 'screen', created_at: '2026-10-01T00:00:00Z', has_password: true, phone_masked: null as string | null, needs_profile: false, age_band: null as string | null, account_kind: 'learner' as string, is_child: false, needs_profile_prompt: false, providers: [] as string[] };
  const screenSettings = {
    timezone: 'Asia/Shanghai',
    push_time: '08:00',
    push_enabled: true,
    daily_new_count: 10,
    daily_screen_count: 10,
    max_reviews: 100,
    stages: ['cet4'],
    current_stage: 'cet4',
    show_images: true,
    zh_examples: 'tap', dance_mode: 'full', image_word: true,
    auto_pronounce: false,
    accent: 'en-US',
    email_enabled: false,
    webhook_enabled: false,
    webhook_url: null,
    webhook_format: 'generic',
    next_push_at: null,
    email_verified: false,
    updated_at: '2026-10-01T00:00:00Z',
  };
  return {
    cards: [1, 2, 3, 4, 5, 6, 7, 8].map(card),
    verdicts: [] as { word_id: number; verdict: string }[],
    profiles: [] as { display_name: string; age_band: string; account_kind?: string; username?: string; password?: string }[],
    profileError: null as unknown, // thrown once by the next saveProfile
    refreshes: 0,
    screenUser,
    screenSettings,
    // what the mocked useAuth() returns; the step-1 tests swap in a `pending` user without settings
    auth: { user: screenUser, settings: screenSettings as typeof screenSettings | null },
    server: null as { sms_enabled: boolean } | null,
  };
});

vi.mock('@/api/endpoints', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/endpoints')>();
  return {
    ...actual,
    getTimezones: vi.fn(async () => ({ items: ['Asia/Shanghai'] })),
    getScreenNext: vi.fn(async () => ({ items: h.cards, remaining: 100 })),
    postScreenVerdict: vi.fn(async (body: { word_id: number; verdict: string }) => {
      h.verdicts.push({ word_id: body.word_id, verdict: body.verdict });
      return { word_id: body.word_id, verdict: body.verdict, mine: null, added_to_today: false, study_item: null, today: null, duplicate: false };
    }),
    markWord: vi.fn(),
    completeOnboarding: vi.fn(),
    saveProfile: vi.fn(async (body: { display_name: string; age_band: string; account_kind?: string; username?: string; password?: string }) => {
      if (h.profileError) {
        const err = h.profileError;
        h.profileError = null;
        throw err;
      }
      h.profiles.push(body);
      return { user: { ...h.screenUser, onboarding_state: 'pending', display_name: body.display_name, needs_profile: false, age_band: body.age_band } };
    }),
  };
});

vi.mock('@/auth/AuthContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/AuthContext')>();
  const value = () => ({
    ...h.auth,
    server: h.server,
    counters: null,
    health: null,
    loading: false,
    applySession: () => undefined,
    refreshCounters: async () => undefined,
    refresh: async () => {
      h.refreshes += 1;
    },
  });
  return { ...actual, useAuth: value, useOptionalAuth: value };
});

import WelcomePage, { DEFAULT_PRESET, isThirdPartyOnly, ROLES, ROLE_PRESETS, type Role } from './WelcomePage';

const keydown = (key: string, repeat: boolean) => window.dispatchEvent(new KeyboardEvent('keydown', { key, repeat, bubbles: true, cancelable: true }));
const settle = (ms = 30) => act(async () => new Promise((r) => setTimeout(r, ms)));
const knownButton = () => screen.getByRole('button', { name: zh.study.known });

/** Renders step 2 and waits for the first card plus the effects that register the keyboard listener. */
async function renderStep2() {
  render(
    <MemoryRouter initialEntries={['/welcome']}>
      <ToastProvider>
        <WelcomePage />
      </ToastProvider>
    </MemoryRouter>,
  );
  await screen.findByText('word1');
  await settle();
}

describe('WelcomePage step 2', () => {
  beforeEach(() => {
    h.verdicts.length = 0;
  });

  it('a held key (one keydown followed by auto-repeat keydowns) judges exactly one card', async () => {
    await renderStep2();
    act(() => void keydown('1', false));
    for (let i = 0; i < 4; i += 1) act(() => void keydown('1', true));
    await waitFor(() => expect(h.verdicts.length).toBeGreaterThanOrEqual(1));
    await settle();
    expect(h.verdicts).toEqual([{ word_id: 1, verdict: 'known' }]);
    expect(screen.getByText('word2')).toBeTruthy();
    expect(screen.getByText(zh.screen.screenedCount(1))).toBeTruthy();
    expect(await screen.findByText(zh.screen.markedKnown('word1'))).toBeTruthy();
  });

  it('a lone auto-repeat keydown (no initial press) is ignored, Space peeks without judging', async () => {
    await renderStep2();
    act(() => void keydown('2', true));
    act(() => void keydown(' ', false));
    await settle();
    expect(h.verdicts).toEqual([]);
    expect(screen.getByText('word1')).toBeTruthy();
    expect(screen.getByText('zh1')).toBeTruthy();
  });

  it('a double tap on a verdict button judges one card; taps work again after the lock, keys are never locked', async () => {
    await renderStep2();
    fireEvent.click(knownButton());
    fireEvent.click(knownButton()); // lands on word2's button a few ms later
    await settle();
    expect(h.verdicts.map((v) => v.word_id)).toEqual([1]);
    expect(screen.getByText('word2')).toBeTruthy();
    await settle(TAP_LOCK_MS + 50);
    fireEvent.click(knownButton());
    await settle();
    expect(h.verdicts.map((v) => v.word_id)).toEqual([1, 2]);
    act(() => void keydown('s', false)); // keyboard right after a tap is the intended rapid flow
    await settle();
    expect(h.verdicts.map((v) => [v.word_id, v.verdict])).toEqual([
      [1, 'known'],
      [2, 'known'],
      [3, 'skip'],
    ]);
  });
});

const pressedStages = () =>
  within(screen.getByRole('group', { name: zh.welcome.stages }))
    .getAllByRole('button')
    .filter((b) => b.getAttribute('aria-pressed') === 'true')
    .map((b) => b.textContent);
const checkedMainStage = () =>
  within(screen.getByRole('radiogroup', { name: zh.welcome.currentStage }))
    .getAllByRole('radio')
    .filter((b) => b.getAttribute('aria-checked') === 'true')
    .map((b) => b.textContent);

describe('WelcomePage step 1', () => {
  beforeEach(() => {
    h.auth = { user: { ...h.screenUser, onboarding_state: 'pending' }, settings: null };
  });
  afterEach(() => {
    h.auth = { user: h.screenUser, settings: h.screenSettings };
  });

  it('offers the five roles in order and pre-selects the server default (xs + zk, main stage xs) before any pick', () => {
    render(
      <MemoryRouter initialEntries={['/welcome']}>
        <ToastProvider>
          <WelcomePage />
        </ToastProvider>
      </MemoryRouter>,
    );
    const roles = within(screen.getByRole('group', { name: zh.welcome.whoAreYou })).getAllByRole('button');
    expect(roles.map((b) => b.textContent)).toEqual(ROLES.map((r) => zh.welcome.roles[r]));
    expect(roles).toHaveLength(5);
    expect(pressedStages()).toEqual([zh.stages.xsFull, zh.stages.zkFull]);
    expect(checkedMainStage()).toEqual([zh.stages.xs]);
  });

  it('a role pick applies its preset: the junior-high preset includes xs, the high-school one does not', () => {
    render(
      <MemoryRouter initialEntries={['/welcome']}>
        <ToastProvider>
          <WelcomePage />
        </ToastProvider>
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.roles.xs }));
    expect(pressedStages()).toEqual([zh.stages.xsFull]);
    expect(checkedMainStage()).toEqual([zh.stages.xs]);
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.roles.zk }));
    expect(pressedStages()).toEqual([zh.stages.xsFull, zh.stages.zkFull]);
    expect(checkedMainStage()).toEqual([zh.stages.zk]);
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.roles.gk }));
    expect(pressedStages()).toEqual([zh.stages.zkFull, zh.stages.gkFull]);
    expect(checkedMainStage()).toEqual([zh.stages.gk]);
  });
});

describe('WelcomePage step 0 (first setup of a code-created account, API.md 89)', () => {
  beforeEach(() => {
    h.profiles.length = 0;
    h.profileError = null;
    h.refreshes = 0;
    h.auth = { user: { ...h.screenUser, username: 'u_ab23cd45', display_name: '', onboarding_state: 'pending', has_password: false, phone_masked: '138****8000', needs_profile: true }, settings: null };
  });
  afterEach(() => {
    h.auth = { user: h.screenUser, settings: h.screenSettings };
  });

  it('asks for the nickname and the age band before step 1, posts the profile and moves on to the roles', async () => {
    render(
      <MemoryRouter initialEntries={['/welcome']}>
        <ToastProvider>
          <WelcomePage />
        </ToastProvider>
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { name: zh.welcome.step0 })).toBeTruthy();
    expect(screen.queryByRole('group', { name: zh.welcome.whoAreYou })).toBeNull();
    expect(screen.getByText(zh.welcome.under14)).toBeTruthy();
    const next = screen.getByRole('button', { name: zh.welcome.next });
    fireEvent.click(next); // nothing filled: the nickname error shows, nothing is posted
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.welcome.nicknameHint);
    expect(h.profiles).toEqual([]);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.nickname}`)), { target: { value: ' Xiao Ming ' } });
    fireEvent.click(screen.getByLabelText(zh.welcome.age14plus));
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.optionalPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    await waitFor(() => expect(h.profiles).toEqual([{ display_name: 'Xiao Ming', age_band: '14plus', account_kind: 'learner', password: 'Str0ng-Passphrase!' }]));
    expect(await screen.findByRole('group', { name: zh.welcome.whoAreYou })).toBeTruthy(); // step 1
    expect(screen.queryByRole('heading', { name: zh.welcome.step0 })).toBeNull();
    expect(h.refreshes).toBe(0);
  });

  const renderStep0 = () =>
    render(
      <MemoryRouter initialEntries={['/welcome']}>
        <ToastProvider>
          <WelcomePage />
        </ToastProvider>
      </MemoryRouter>,
    );

  it('a 409 invalid_transition (the profile was saved in another tab) refreshes the session and moves on without an error', async () => {
    h.profileError = new ApiError('invalid_transition', 409, '');
    renderStep0();
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.nickname}`)), { target: { value: 'Xiao Ming' } });
    fireEvent.click(screen.getByLabelText(zh.welcome.ageAdult));
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    expect(await screen.findByRole('group', { name: zh.welcome.whoAreYou })).toBeTruthy(); // step 1
    expect(h.refreshes).toBe(1); // the context's user (display_name, needs_profile) comes from the server, not from the stale copy
    expect(screen.queryByRole('alert')).toBeNull();
    expect(h.profiles).toEqual([]);
  });

  it('a 400 validation_error shows the server field message (a username that looks like a phone number) and stays on step 0', async () => {
    h.profileError = new ApiError('validation_error', 400, '', { fields: { username: 'username-must-not-be-a-phone-number' } });
    renderStep0();
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.nickname}`)), { target: { value: 'Xiao Ming' } });
    fireEvent.click(screen.getByLabelText(zh.welcome.age14plus));
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.optionalUsername}`)), { target: { value: '13800138000' } }); // passes the client shape check
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', 'username-must-not-be-a-phone-number');
    expect(screen.getByRole('heading', { name: zh.welcome.step0 })).toBeTruthy();
    expect(screen.queryByRole('group', { name: zh.welcome.whoAreYou })).toBeNull();
    expect(h.refreshes).toBe(0);
  });

  it('the guardian declaration requires a password while the e-mail is not verified, and posts account_kind guardian / adult', async () => {
    renderStep0();
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.nickname}`)), { target: { value: 'Mom' } });
    expect(screen.getByText(zh.welcome.under14)).toBeTruthy();
    fireEvent.click(screen.getByLabelText(zh.welcome.ageGuardian));
    expect(screen.getByLabelText(new RegExp(`^${zh.welcome.guardianPassword}`))).toBeTruthy(); // the label switches to the required wording
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.auth.passwordHint);
    expect(h.profiles).toEqual([]);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.guardianPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    await waitFor(() => expect(h.profiles).toEqual([{ display_name: 'Mom', account_kind: 'guardian', age_band: 'adult', password: 'Str0ng-Passphrase!' }]));
  });

  it('a guardian with a verified e-mail may leave the password empty; a learner never needs one', async () => {
    h.auth = { user: { ...h.auth.user!, email: 'mom@example.com', email_verified: true }, settings: null };
    renderStep0();
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.nickname}`)), { target: { value: 'Mom' } });
    fireEvent.click(screen.getByLabelText(zh.welcome.ageGuardian));
    expect(screen.getByLabelText(new RegExp(`^${zh.welcome.optionalPassword}`))).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    await waitFor(() => expect(h.profiles).toEqual([{ display_name: 'Mom', account_kind: 'guardian', age_band: 'adult' }]));
  });

  it('a claim-created guardian arrives with the guardian declaration pre-selected and locked', async () => {
    h.auth = { user: { ...h.auth.user!, account_kind: 'guardian' }, settings: null };
    renderStep0();
    expect((screen.getByLabelText(zh.welcome.ageGuardian) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByLabelText(zh.welcome.ageAdult) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText(zh.welcome.age14plus) as HTMLInputElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.nickname}`)), { target: { value: 'Mom' } });
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.guardianPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    await waitFor(() => expect(h.profiles).toEqual([{ display_name: 'Mom', account_kind: 'guardian', age_band: 'adult', password: 'Str0ng-Passphrase!' }]));
  });

  it('while the server has SMS off (or the flags are unknown) a note says a guardian account needs it; the guardian choice stays available', () => {
    renderStep0(); // server flags null
    expect(screen.getByRole('note').textContent).toBe(zh.welcome.guardianSmsOff);
    expect((screen.getByLabelText(zh.welcome.ageGuardian) as HTMLInputElement).disabled).toBe(false);
    fireEvent.click(screen.getByLabelText(zh.welcome.ageGuardian));
    expect((screen.getByLabelText(zh.welcome.ageGuardian) as HTMLInputElement).checked).toBe(true);
  });

  it('with SMS on the server the note is absent', () => {
    h.server = { sms_enabled: true };
    try {
      renderStep0();
      expect(screen.queryByText(zh.welcome.guardianSmsOff)).toBeNull();
      expect(screen.getByText(zh.welcome.under14)).toBeTruthy();
    } finally {
      h.server = null;
    }
  });

  it('a third-party-only account (WeChat / QQ / Apple is its only way in, slice 2-A) must set a password — the endpoint-89 rule; a bound phone makes it optional again', async () => {
    h.auth = { user: { ...h.auth.user!, phone_masked: null, has_password: false, providers: ['wechat_mini'] }, settings: null };
    const first = renderStep0();
    expect(screen.getByLabelText(new RegExp(`^${zh.welcome.requiredPassword}`))).toBeTruthy();
    expect(screen.getByText(zh.welcome.thirdPartyPassword)).toBeTruthy();
    expect(screen.queryByText(zh.welcome.passwordWhy)).toBeNull();
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.nickname}`)), { target: { value: 'Xiao Ming' } });
    fireEvent.click(screen.getByLabelText(zh.welcome.ageAdult));
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', zh.auth.passwordHint); // empty → required
    expect(h.profiles).toEqual([]);
    fireEvent.change(screen.getByLabelText(new RegExp(`^${zh.welcome.requiredPassword}`)), { target: { value: 'Str0ng-Passphrase!' } });
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.next }));
    await waitFor(() => expect(h.profiles).toEqual([{ display_name: 'Xiao Ming', account_kind: 'learner', age_band: 'adult', password: 'Str0ng-Passphrase!' }]));
    first.unmount();

    h.auth = { user: { ...h.auth.user!, phone_masked: '138****8000' }, settings: null }; // the phone is a second way in
    renderStep0();
    expect(screen.getByLabelText(new RegExp(`^${zh.welcome.optionalPassword}`))).toBeTruthy();
    expect(screen.getByText(zh.welcome.passwordWhy)).toBeTruthy();
    expect(screen.queryByText(zh.welcome.thirdPartyPassword)).toBeNull();
  });
});

describe('isThirdPartyOnly', () => {
  const base: Parameters<typeof isThirdPartyOnly>[0] = { providers: ['qq'] as User['providers'], phone_masked: null, email: null, email_verified: false, has_password: false };

  it('is true only while a third-party identity is the sole way in (no phone, no verified e-mail, no password)', () => {
    expect(isThirdPartyOnly(base)).toBe(true);
    expect(isThirdPartyOnly({ ...base, providers: ['wechat_mini', 'apple'] })).toBe(true);
    expect(isThirdPartyOnly({ ...base, providers: [] })).toBe(false);
    expect(isThirdPartyOnly({ ...base, phone_masked: '138****8000' })).toBe(false);
    expect(isThirdPartyOnly({ ...base, email: 'a@example.com', email_verified: true })).toBe(false);
    expect(isThirdPartyOnly({ ...base, email: 'a@example.com' })).toBe(true); // an unverified e-mail is no way in
    expect(isThirdPartyOnly({ ...base, has_password: true })).toBe(false);
  });
});

describe('WelcomePage finish (POST /api/onboarding/complete)', () => {
  const renderWithRoutes = () =>
    render(
      <MemoryRouter initialEntries={['/welcome']}>
        <ToastProvider>
          <Routes>
            <Route path="/welcome" element={<WelcomePage />} />
            <Route path="/today" element={<div>today-page</div>} />
            <Route path="/children" element={<div>children-page</div>} />
          </Routes>
        </ToastProvider>
      </MemoryRouter>,
    );
  beforeEach(() => {
    vi.mocked(endpoints.completeOnboarding).mockResolvedValue({ onboarding_state: 'done' });
  });
  afterEach(() => {
    vi.mocked(endpoints.completeOnboarding).mockReset();
    h.auth = { user: h.screenUser, settings: h.screenSettings };
  });

  it('a learner lands on /today', async () => {
    renderWithRoutes();
    await screen.findByText('word1');
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.finish }));
    expect(await screen.findByText('today-page')).toBeTruthy();
    expect(endpoints.completeOnboarding).toHaveBeenCalledTimes(1);
  });

  it('a guardian lands on /children, where the children are managed', async () => {
    h.auth = { user: { ...h.screenUser, account_kind: 'guardian' }, settings: h.screenSettings };
    renderWithRoutes();
    await screen.findByText('word1');
    fireEvent.click(screen.getByRole('button', { name: zh.welcome.skip }));
    expect(await screen.findByText('children-page')).toBeTruthy();
    expect(endpoints.completeOnboarding).toHaveBeenCalledTimes(1);
  });
});

describe('ROLE_PRESETS / DEFAULT_PRESET', () => {
  it('every preset keeps its main stage inside its stages, in canonical order; the fallback mirrors the server default', () => {
    expect(ROLES).toEqual(['xs', 'zk', 'gk', 'uni', 'pro']);
    for (const role of ROLES) {
      const { stages, current } = ROLE_PRESETS[role];
      expect(stages).toContain(current);
      expect(stages).toEqual(STAGE_ORDER.filter((s) => stages.includes(s)));
    }
    expect(ROLE_PRESETS.xs).toEqual({ stages: ['xs'], current: 'xs' });
    expect(ROLE_PRESETS.zk).toEqual({ stages: ['xs', 'zk'], current: 'zk' });
    expect(ROLE_PRESETS.gk).toEqual({ stages: ['zk', 'gk'], current: 'gk' });
    expect(ROLE_PRESETS.uni).toEqual({ stages: ['gk', 'cet4', 'cet6'], current: 'cet4' });
    expect(ROLE_PRESETS.pro).toEqual({ stages: ['cet4', 'cet6'], current: 'cet4' });
    expect(DEFAULT_PRESET).toEqual({ stages: ['xs', 'zk'], current: 'xs' }); // user_settings DDL default / bank.DEFAULT_*
    const labels: Record<Role, string> = zh.welcome.roles; // compile-time: a label for every role
    expect(Object.keys(labels)).toEqual([...ROLES]);
  });
});
