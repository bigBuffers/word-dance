// FRONTEND §5.4 on /welcome step 2: one physical key press (keydown + OS auto-repeat keydowns) judges exactly
// one card, a double tap on a verdict button cannot judge the card that advanced under the finger, and the
// known toast / progress line use the shared screening copy. Step 1 (PLAN §6 S4): five roles whose presets keep
// the main stage inside the target stages, and the K-12 default that mirrors the server before any pick.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
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
  const screenUser = { id: 1, username: 'u', display_name: 'u', email: null, email_verified: false, role: 'user', onboarding_state: 'screen', created_at: '2026-10-01T00:00:00Z' };
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
    zh_examples: 'tap', dance_mode: 'full',
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
    screenUser,
    screenSettings,
    // what the mocked useAuth() returns; the step-1 tests swap in a `pending` user without settings
    auth: { user: screenUser, settings: screenSettings as typeof screenSettings | null },
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
  };
});

vi.mock('@/auth/AuthContext', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/auth/AuthContext')>();
  const value = () => ({ ...h.auth, server: null, counters: null, health: null, loading: false, applySession: () => undefined, refreshCounters: async () => undefined });
  return { ...actual, useAuth: value, useOptionalAuth: value };
});

import WelcomePage, { DEFAULT_PRESET, ROLES, ROLE_PRESETS, type Role } from './WelcomePage';

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
