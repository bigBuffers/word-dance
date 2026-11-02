// AddWordsPage render tests (FRONTEND §5.6): a pending-AI result row resolves to the validated badge once the poll
// sees the AI verdict (badge + header count); client-rejected lines carry the server's own reason; duplicate hint.
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AddResponse, LookupPreview, Srs, UserWord, WordBrief, WordDetail } from '@/api/types';
import { AuthProvider } from '@/auth/AuthContext';
import { ATTENTION_POLL_MS } from '@/components/bank/AttentionBadge';
import { zh } from '@/i18n/zh';
import AddWordsPage, { badgeStatus } from './AddWordsPage';

const ISO = '2026-10-14T00:00:00Z';
const srs: Srs = { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false };
const CJK_APPLE = String.fromCharCode(0x82f9, 0x679c); // a two-character Chinese word, built from code points (no CJK literals outside i18n)

const word = (over: Partial<WordBrief> = {}): WordBrief => ({
  id: 7,
  lemma: 'zzzq',
  display: 'zzzq',
  kind: 'word',
  phonetic: null,
  translation_short: '',
  stages: [],
  stage_min: null,
  cet6_star: false,
  frq: null,
  collins: null,
  oxford: null,
  difficulty: null,
  is_public: false,
  is_valid_english: null,
  my_state: 'new',
  content_state: 'none',
  image_state: 'none',
  ...over,
});
const mine = (over: Partial<UserWord> = {}): UserWord => ({
  id: 1,
  word_id: 7,
  state: 'new',
  origin: 'custom',
  priority: 100,
  note: null,
  input_text: 'zzzq',
  needs_attention: false,
  attention_msg: null,
  suggested_word: null,
  srs,
  times_pushed: 0,
  times_added: 1,
  added_at: ISO,
  first_added_at: ISO,
  mastered_at: null,
  ...over,
});
const detail = (w: WordBrief, m: UserWord | null): WordDetail => ({
  word: { ...w, definition: null, translation: null, pos: null, exam_tags: [], bnc: null, forms: [], source: 'user', confusables: [] },
  content: null,
  content_state: 'none',
  content_deferred_until: null,
  image: { id: null, url: '/media/card/7.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: null, attribution: null },
  mine: m,
  redirected_from: null,
  history: [],
});
const preview = (input: string): LookupPreview => ({ input, normalized: input, valid: true, reason_zh: null, via: 'none', match: null, lemma_note_zh: null, candidates: [], suggestions: [], mine: null });
const pendingAdd: AddResponse = {
  results: [{ input: 'zzzq', status: 'pending_ai', word: word(), mine: mine(), resolved_via: 'provisional', lemma_note_zh: null, candidates: [], error: null, message: null, added_to_today: false }],
  added: 0,
  readded: 0,
  exists: 0,
  pending_ai: 1,
  ambiguous: 0,
  invalid: 0,
};

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function mockFetch(routes: Record<string, (init?: RequestInit) => Response>) {
  const fn = vi.fn<typeof fetch>((input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const path = url.split('?')[0] ?? url;
    const handler = routes[path];
    return Promise.resolve(handler ? handler(init) : json(404, { error: { code: 'not_found', message: '' } }));
  });
  vi.stubGlobal('fetch', fn);
  return fn;
}

const tick = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const badgeText = () => document.querySelector('.result-row .status-badge')?.textContent ?? null;
const summaryText = () => document.querySelector('.addwords__summary')?.textContent ?? null;
const textarea = () => screen.getByLabelText(zh.bank.add, { selector: 'textarea' });

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/bank/add']}>
      <AuthProvider>
        <Routes>
          <Route path="/bank/add" element={<AddWordsPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

const baseRoutes = {
  '/api/auth/me': () => json(401, { error: { code: 'unauthorized', message: '' } }),
  '/api/health': () => json(200, { status: 'ok', version: '0.1.0', registration_mode: 'invite', needs_setup: false, time: ISO }),
  '/api/lookup': () => json(200, preview('x')),
};

describe('AddWordsPage', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('a pending-AI row becomes validated once the poll sees the AI verdict (badge and header count)', async () => {
    const resolved = detail(word({ is_valid_english: true, translation_short: 'validated-zh' }), mine());
    const fetchMock = mockFetch({ ...baseRoutes, '/api/bank/add': () => json(200, pendingAdd), '/api/words/7': () => json(200, resolved) });
    renderPage();
    await tick(10);
    fireEvent.change(textarea(), { target: { value: 'zzzq' } });
    await tick(300);
    fireEvent.click(screen.getByRole('button', { name: zh.bank.submit }));
    await tick(50);

    expect(badgeText()).toBe(zh.bank.status.pending_ai);
    expect(screen.getByText(zh.bank.pendingAi)).toBeTruthy(); // AttentionBadge chip
    expect(summaryText()).toContain(`${zh.bank.pendingAi} 1`);

    await tick(ATTENTION_POLL_MS);
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/words/7')).toHaveLength(1);
    await tick(ATTENTION_POLL_MS * 2);
    expect(fetchMock.mock.calls.filter(([u]) => String(u) === '/api/words/7')).toHaveLength(1); // resolved → polling stopped

    expect(screen.queryByText(zh.bank.pendingAi)).toBeNull();
    expect(badgeText()).toBe(zh.bank.status.validated);
    expect(summaryText()).toBe(zh.bank.counts(1));
    expect(document.querySelector('.result-row')?.textContent).toContain('validated-zh');
  });

  it('badgeStatus maps a validated pending row and leaves every other status alone', () => {
    const base = pendingAdd.results[0]!;
    expect(badgeStatus(base)).toBe('pending_ai');
    expect(badgeStatus({ ...base, validated: true })).toBe('validated');
    expect(badgeStatus({ ...base, status: 'exists' })).toBe('exists');
  });

  it('client-rejected lines show the server reason for their rule, not the charset sentence', async () => {
    mockFetch(baseRoutes);
    renderPage();
    await tick(10);
    fireEvent.change(textarea(), { target: { value: `${CJK_APPLE}\n${'a'.repeat(50)}\n-abandon\none two three four five\nabc123` } });
    await tick(300);
    expect(screen.getByText(zh.bank.invalidReason.not_english, { exact: false })).toBeTruthy();
    expect(screen.getByText(zh.bank.invalidReason.too_long, { exact: false })).toBeTruthy();
    expect(screen.getByText(zh.bank.invalidReason.leading_punct, { exact: false })).toBeTruthy();
    expect(screen.getByText(zh.bank.invalidReason.too_many_tokens, { exact: false })).toBeTruthy();
    expect(screen.getAllByText(zh.bank.invalidReason.charset, { exact: false })).toHaveLength(1); // only abc123
    expect((screen.getByRole('button', { name: zh.bank.submit }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('a line repeating an earlier lemma gets the duplicate hint', async () => {
    mockFetch(baseRoutes);
    renderPage();
    await tick(10);
    fireEvent.change(textarea(), { target: { value: 'abandon\nAbandon' } });
    await tick(300);
    expect(screen.getAllByText(zh.bank.preview.duplicate)).toHaveLength(1);
    expect(screen.getByText(zh.bank.counts(1))).toBeTruthy(); // the duplicate is not counted or posted
  });
});
