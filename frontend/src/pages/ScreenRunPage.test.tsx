// FRONTEND §5.4 on /screen/:stage: a double tap on a verdict button must not judge the card that advanced under
// the finger (the deck advances optimistically), while discrete key presses stay unlocked; toast / progress copy.
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ScreenResponse, WordBrief } from '@/api/types';
import { ToastProvider } from '@/components/ui/Toast';
import { TAP_LOCK_MS } from '@/hooks/useTapLock';
import { zh } from '@/i18n/zh';

vi.mock('@/api/endpoints', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/endpoints')>()),
  getScreenNext: vi.fn(),
  postScreenVerdict: vi.fn(),
  markWord: vi.fn(),
}));
vi.mock('@/auth/AuthContext', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/auth/AuthContext')>()),
  useAuth: () => ({ settings: { accent: 'en-US' } }),
  useOptionalAuth: () => null,
}));

import { getScreenNext, postScreenVerdict } from '@/api/endpoints';
import ScreenRunPage from './ScreenRunPage';

const brief = (id: number, display: string): WordBrief => ({
  id,
  lemma: display,
  display,
  kind: 'word',
  phonetic: null,
  translation_short: `${display}-zh`,
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
  content_state: 'none',
  image_state: 'none',
});

const response = (wordId: number, verdict: ScreenResponse['verdict']): ScreenResponse => ({ word_id: wordId, verdict, mine: null, added_to_today: false, study_item: null, today: null, duplicate: false });

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/screen/cet4']}>
      <ToastProvider>
        <Routes>
          <Route path="/screen/:stage" element={<ScreenRunPage />} />
          <Route path="/screen" element={<div>screen-index</div>} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const settle = (ms = 30) => act(async () => new Promise((r) => setTimeout(r, ms)));
const knownButton = () => screen.getByRole('button', { name: new RegExp(`^${zh.study.known}`) });
const posted = () => vi.mocked(postScreenVerdict).mock.calls.map((c) => c[0].word_id);

describe('ScreenRunPage', () => {
  beforeEach(() => {
    vi.mocked(getScreenNext).mockResolvedValue({ items: [brief(1, 'alpha'), brief(2, 'beta'), brief(3, 'gamma')].map((word) => ({ word, phonetic: null })), remaining: 3 });
    vi.mocked(postScreenVerdict).mockImplementation(async (body) => response(body.word_id, body.verdict));
  });

  it('a double tap posts one verdict; the next tap counts again after the lock', async () => {
    renderPage();
    await screen.findByRole('group', { name: 'alpha' });
    fireEvent.click(knownButton());
    expect(screen.queryByRole('group', { name: 'beta' })).not.toBeNull(); // optimistic advance
    fireEvent.click(knownButton()); // beta's button, under the finger
    await settle();
    expect(posted()).toEqual([1]);
    expect(screen.queryByRole('group', { name: 'beta' })).not.toBeNull();
    await settle(TAP_LOCK_MS + 50);
    fireEvent.click(knownButton());
    await settle();
    expect(posted()).toEqual([1, 2]);
    expect(screen.queryByRole('group', { name: 'gamma' })).not.toBeNull();
  });

  it('discrete key presses are never locked and auto-repeat is ignored', async () => {
    renderPage();
    await screen.findByRole('group', { name: 'alpha' });
    await settle(); // let the useKeyboard effect register its window listener
    fireEvent.keyDown(window, { key: '1' });
    fireEvent.keyDown(window, { key: '1' });
    fireEvent.keyDown(window, { key: '1', repeat: true });
    await settle();
    expect(posted()).toEqual([1, 2]);
  });

  it('shows the shared known toast and the "screened this round" line, never a bare total', async () => {
    vi.mocked(getScreenNext).mockResolvedValue({ items: [{ word: brief(1, 'alpha'), phonetic: null }], remaining: 10 });
    renderPage();
    await screen.findByRole('group', { name: 'alpha' });
    fireEvent.click(knownButton());
    expect(await screen.findByText(zh.screen.markedKnown('alpha'))).toBeTruthy();
    expect(screen.getByText(zh.screen.screenedCount(1))).toBeTruthy();
    expect(screen.queryByText(zh.bank.counts(1))).toBeNull();
    expect(screen.getByRole('button', { name: zh.screen.another })).toBeTruthy();
  });

  it('an exhausted stage on a fresh visit shows no zero count under the all-done message', async () => {
    vi.mocked(getScreenNext).mockResolvedValue({ items: [], remaining: 0 });
    renderPage();
    await screen.findByText(zh.screen.allDone);
    expect(screen.queryByText(zh.screen.screenedCount(0))).toBeNull();
    expect(screen.queryByText(zh.bank.counts(0))).toBeNull();
  });
});
