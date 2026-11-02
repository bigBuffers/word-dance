// FRONTEND §5.4 on /welcome step 2: one physical key press (keydown + OS auto-repeat keydowns) judges exactly
// one card, a double tap on a verdict button cannot judge the card that advanced under the finger, and the
// known toast / progress line use the shared screening copy.
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ToastProvider } from '@/components/ui/Toast';
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
      stage_min: 3,
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
  return { cards: [1, 2, 3, 4, 5, 6, 7, 8].map(card), verdicts: [] as { word_id: number; verdict: string }[] };
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
  const user = { id: 1, username: 'u', display_name: 'u', email: null, email_verified: false, role: 'user', onboarding_state: 'screen', created_at: '2026-10-01T00:00:00Z' };
  const settings = {
    timezone: 'Asia/Shanghai',
    push_time: '08:00',
    push_enabled: true,
    daily_new_count: 10,
    daily_screen_count: 10,
    max_reviews: 100,
    stages: ['cet4'],
    current_stage: 'cet4',
    show_images: true,
    zh_examples: 'tap',
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
  const value = { user, settings, server: null, counters: null, health: null, loading: false, applySession: () => undefined, refreshCounters: async () => undefined };
  return { ...actual, useAuth: () => value, useOptionalAuth: () => value };
});

import WelcomePage from './WelcomePage';

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
