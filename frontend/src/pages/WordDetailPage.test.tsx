// WordDetailPage render tests (FRONTEND §5.8): the remove / reset confirmations explain what happens, the bank
// panel reads "not reviewed yet" for a never-graded row and names an overdue review, and ECDICT's pos ratio is
// shown as readable shares. Memory cards (docs/MEMORY_CARDS_DESIGN.md §3.6–3.7): `settings.image_word` off asks for the picture
// without its word layer, the mnemonic lines are the picture's hook + caveat while it is shown (else the content's mnemonic),
// and such a picture offers flag-image only. A report on the picture (flag-image, or the sheet with a picture reason) takes a
// photo or an older drawing down, so the page waits for the next one (the 3-s poll); a memory card stays — the server only
// records the report — so there the page thanks and does nothing else: no poll, no parked button, the same picture.
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { getWordImage, reportWord } from '@/api/endpoints';
import type { Content, DanceMode, ImageMeta, UserWord, WordDetail } from '@/api/types';
import { dancePlan } from '@/components/word/dances';
import { ToastProvider } from '@/components/ui/Toast';
import { zh } from '@/i18n/zh';

const h = vi.hoisted(() => ({ detail: null as unknown, settings: { timezone: 'Asia/Shanghai', accent: 'en-US', show_images: false, zh_examples: 'tap', dance_mode: 'full' as DanceMode, image_word: true } }));

vi.mock('@/api/endpoints', () => ({
  getWord: vi.fn(() => Promise.resolve(h.detail)),
  getWordContent: vi.fn(),
  getWordImage: vi.fn(),
  markWord: vi.fn(() => new Promise(() => undefined)),
  refreshWordImage: vi.fn(),
  reportWord: vi.fn(),
  requestWordContent: vi.fn(),
}));
vi.mock('@/auth/AuthContext', () => {
  const fake = {
    get settings() {
      return h.settings;
    },
    counters: { suggestions_open: 0, attention: 0 },
    refreshCounters: vi.fn(() => Promise.resolve()),
  };
  return { useAuth: () => fake, useOptionalAuth: () => fake };
});

import WordDetailPage from './WordDetailPage';

const DAY = 86_400_000;

function mineRow(over: Partial<UserWord> = {}): UserWord {
  return {
    id: 11,
    word_id: 1,
    state: 'learning',
    origin: 'browse',
    priority: 50,
    note: null,
    input_text: null,
    needs_attention: false,
    attention_msg: null,
    suggested_word: null,
    srs: { ease: 2.5, interval_days: 3, step: 0, repetitions: 4, lapses: 1, consecutive_good: 2, due_at: new Date(Date.now() - 2 * DAY).toISOString(), last_graded_at: null, mastery_suggested: false },
    times_pushed: 3,
    times_added: 1,
    added_at: '2026-10-20T00:00:00Z',
    first_added_at: '2026-10-20T00:00:00Z',
    mastered_at: null,
    ...over,
  };
}

function detailOf(mine: UserWord | null, word: Partial<WordDetail['word']> = {}): WordDetail {
  return {
    word: {
      id: 1,
      lemma: 'abandon',
      display: 'abandon',
      kind: 'word',
      phonetic: null,
      translation_short: 'v. give up',
      stages: ['cet4'],
      stage_min: 4,
      cet6_star: false,
      frq: 1000,
      collins: 3,
      oxford: true,
      difficulty: 2,
      is_public: true,
      is_valid_english: true,
      my_state: mine?.state ?? null,
      content_state: 'none',
      image_state: 'none',
      definition: null,
      translation: 'v. give up\nn. wild abandon',
      pos: 'n:4/v:96',
      exam_tags: [],
      bnc: null,
      forms: [],
      source: 'seed',
      confusables: [], dance: null,
      ...word,
    },
    content: null,
    content_state: 'none',
    content_deferred_until: null,
    image: { id: null, url: '/media/card/1.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: null, height: null, alt_zh: null, attribution: null, dancing: false, word_layer: false, hook_zh: null, note_zh: null },
    mine,
    redirected_from: null,
    history: [],
  };
}

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={['/words/1']}>
      <ToastProvider>
        <Routes>
          <Route path="/words/:idOrLemma" element={<WordDetailPage />} />
        </Routes>
      </ToastProvider>
    </MemoryRouter>,
  );
}

const dialog = () => document.querySelector('dialog.confirm') as HTMLElement;

describe('WordDetailPage', () => {
  beforeEach(() => {
    h.detail = detailOf(mineRow());
  });

  it('the remove and reset confirmations carry a title and an explanatory sentence', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: zh.word.remove }));
    expect(within(dialog()).getByRole('heading').textContent).toBe(zh.word.remove);
    expect(dialog().querySelector('.confirm__message')?.textContent).toBe(zh.word.removeConfirm);
    expect(within(dialog()).getByRole('button', { name: zh.word.remove })).toBeTruthy();
    fireEvent.click(within(dialog()).getByRole('button', { name: zh.common.cancel }));
    await waitFor(() => expect(document.querySelector('dialog.confirm[open]')).toBeNull());

    fireEvent.click(screen.getByRole('button', { name: zh.word.reset }));
    expect(within(dialog()).getByRole('heading').textContent).toBe(zh.word.reset);
    expect(dialog().querySelector('.confirm__message')?.textContent).toBe(zh.word.resetConfirm);
  });

  it('shows the SRS line, the bare overdue label for a review due on an earlier day, and readable pos shares', async () => {
    renderDetail();
    await screen.findByRole('button', { name: zh.word.remove });
    expect(screen.getByText(zh.study.srsLine(4, 3))).toBeTruthy();
    expect(screen.getByText(zh.study.nextDue.overdue, { selector: 'dd' })).toBeTruthy();
    expect(screen.queryByText(zh.bank.dueIn(zh.study.nextDue.overdue))).toBeNull();
    expect(screen.getByText('v. 96% · n. 4%')).toBeTruthy();
    expect(screen.queryByText('n:4/v:96')).toBeNull();
  });

  it("the meaning leads the page: the card's own once the content is ready, else what the lists show — never under the dictionary title", async () => {
    const content: Content = {
      word: 'abandon', valid: true, meaning_zh: ' CARD-MEANING ', meaning_en: 'to leave', examples: [{ en: 'She abandoned hope.', zh: 'EXAMPLE-ZH' }], collocations: [], mnemonic_zh: 'MNEMONIC-ZH',
      image_keywords: [], image_alt_zh: 'ALT-ZH', difficulty: 2, version: 1, prompt_version: 'content_v2', model: 'sonnet', created_at: '2026-10-13T00:00:00Z',
    };
    const lead = (c: HTMLElement) => Array.from(c.querySelectorAll('.word-detail__meaning')).map((el) => `${el.parentElement?.className}: ${el.textContent}`);
    const dictionary = () => screen.getByRole('region', { name: zh.study.dictionary });

    h.detail = { ...detailOf(mineRow(), { translation_short: 'LIST-MEANING' }), content, content_state: 'ready' };
    const ready = renderDetail();
    await screen.findByText('CARD-MEANING');
    expect(lead(ready.container)).toEqual(['word-detail__head: CARD-MEANING']); // once, in the header — no longer above the examples
    expect(within(dictionary()).getAllByRole('listitem').map((li) => li.textContent)).toEqual(['v. give up', 'n. wild abandon']);
    expect(dictionary().compareDocumentPosition(ready.container.querySelector('.word-detail__meaning')!) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();
    ready.unmount();

    // content on its way (or deferred): the content's meaning is not shown yet, the list's is
    h.detail = { ...detailOf(mineRow(), { translation_short: 'LIST-MEANING' }), content, content_state: 'queued', content_deferred_until: '2026-10-14T00:00:00Z' };
    const waiting = renderDetail();
    await screen.findByText(zh.study.contentDeferred);
    expect(lead(waiting.container)).toEqual(['word-detail__head: LIST-MEANING']);
    waiting.unmount();

    // a word nothing is known about yet: no empty line, and the short meaning is not repeated as a "dictionary" line
    h.detail = detailOf(mineRow(), { translation_short: '', translation: null });
    const bare = renderDetail();
    await screen.findByText(zh.study.contentFailed);
    expect(lead(bare.container)).toEqual([]);
    expect(within(dictionary()).queryAllByRole('listitem')).toEqual([]);
    bare.unmount();

    h.detail = detailOf(mineRow(), { translation_short: 'LIST-MEANING', translation: null });
    renderDetail();
    await screen.findByText('LIST-MEANING');
    expect(screen.getAllByText('LIST-MEANING')).toHaveLength(1);
    expect(within(dictionary()).queryByText('LIST-MEANING')).toBeNull();
  });

  it('a never-graded bank row reads "not reviewed yet" instead of a zeroth review', async () => {
    h.detail = detailOf(mineRow({ state: 'new', srs: { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false } }));
    renderDetail();
    await screen.findByRole('button', { name: zh.word.remove });
    expect(screen.getByText(zh.study.srsNew)).toBeTruthy();
    expect(screen.queryByText(zh.study.srsLine(0, 0))).toBeNull();
    expect(screen.queryByText(zh.bank.sort.due, { selector: 'dt' })).toBeNull();
  });
});

describe('WordDetailPage word dance (FRONTEND §6.5)', () => {
  const spec = { version: 1 as const, letters: ['a', 'ban', 'don'], stress: 1, marks: { double: [] as [number, number][], silent: [] as number[] }, semantic: null, source: 'rule' as const };
  const animate = vi.fn();
  beforeEach(() => {
    h.settings.dance_mode = 'full';
    Object.defineProperty(Element.prototype, 'animate', { value: animate, configurable: true });
  });
  afterEach(() => {
    delete (Element.prototype as unknown as { animate?: unknown }).animate;
    h.settings.dance_mode = 'full';
  });

  it.each(['full', 'form_only'] as const)('%s: a newly opened word dances before clicking the voice button, which can replay it', async (mode) => {
    h.settings.dance_mode = mode;
    h.detail = detailOf(mineRow({ state: 'new' }), { dance: spec });
    renderDetail();
    await screen.findByRole('heading', { level: 1, name: 'abandon' });
    const steps = dancePlan(spec, 'currentColor').length;
    expect(animate).toHaveBeenCalledTimes(steps);

    fireEvent.click(screen.getByRole('button', { name: zh.word.remove })); // unrelated page state (a confirm dialog) must not replay the dance
    expect(animate).toHaveBeenCalledTimes(steps);
    fireEvent.click(within(dialog()).getByRole('button', { name: zh.common.cancel }));
    fireEvent.click(screen.getByRole('button', { name: zh.word.replayDance })); // no speech engine in jsdom
    expect(animate).toHaveBeenCalledTimes(2 * steps);
  });

  it('shows the syllable chips and a dancing headword named after the word', async () => {
    h.detail = detailOf(mineRow(), { dance: spec });
    const { container } = renderDetail();
    await screen.findByRole('heading', { level: 1, name: 'abandon' });
    const chips = within(screen.getByRole('list', { name: zh.word.syllables })).getAllByRole('listitem');
    expect(chips.map((c) => c.textContent)).toEqual(['a', 'ban', 'don']);
    expect(chips.map((c) => c.classList.contains('syl__chip--stressed'))).toEqual([false, true, false]);
    expect(container.querySelector('.dword')).not.toBeNull();
  });

  it('dance_mode off → the plain headword without chips', async () => {
    h.settings.dance_mode = 'off';
    h.detail = detailOf(mineRow(), { dance: spec });
    const { container } = renderDetail();
    await screen.findByRole('heading', { level: 1 });
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    expect(container.querySelector('.dword')).toBeNull();
    expect(animate).not.toHaveBeenCalled();
  });
});

describe('WordDetailPage memory cards (FRONTEND §5.8; docs/MEMORY_CARDS_DESIGN.md §3.6–3.7)', () => {
  const memoryCard: ImageMeta = { id: 8, url: '/media/images/ab/0123.svg', kind: 'svg', provider: 'claude_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: 'SCENE-ZH', attribution: null, dancing: false, word_layer: true, hook_zh: 'HOOK-ZH', note_zh: 'NOTE-ZH' };
  const content: Content = {
    word: 'abandon', valid: true, meaning_zh: 'MEANING-ZH', meaning_en: 'to leave', examples: [{ en: 'She abandoned hope.', zh: 'EXAMPLE-ZH' }], collocations: ['abandon ship'], mnemonic_zh: 'MNEMONIC-ZH',
    image_keywords: [], image_alt_zh: 'ALT-ZH', difficulty: 2, version: 1, prompt_version: 'content_v1', model: 'sonnet', created_at: '2026-10-13T00:00:00Z',
  };
  const ready = (image: ImageMeta): WordDetail => ({ ...detailOf(mineRow()), content, content_state: 'ready', image });
  const src = () => (screen.getByRole('img') as HTMLImageElement).getAttribute('src');
  /** The mnemonic lines: every paragraph after the mnemonic subtitle inside the examples card. */
  const lines = () => {
    const title = screen.queryByRole('heading', { level: 3, name: zh.study.mnemonic });
    const out: (string | null)[] = [];
    for (let el = title?.nextElementSibling ?? null; el && el.tagName === 'P'; el = el.nextElementSibling) out.push(el.textContent);
    return out;
  };
  beforeEach(() => {
    h.settings.show_images = true;
    h.settings.image_word = true;
  });
  afterEach(() => {
    h.settings.show_images = false;
    h.settings.image_word = true;
  });

  it("shows the whole picture, its hook and — quieter — its caveat instead of the content's mnemonic; flag-image only", async () => {
    h.detail = ready(memoryCard);
    const { container } = renderDetail();
    await screen.findByText('MEANING-ZH');
    expect(src()).toBe('/media/images/ab/0123.svg');
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    expect(container.querySelector('.word-detail__mnemonic-note')?.textContent).toBe('NOTE-ZH');
    expect(screen.queryByText('MNEMONIC-ZH')).toBeNull();
    expect(screen.getByText(zh.word.aiImage)).toBeTruthy();
    expect(screen.queryByRole('button', { name: zh.word.changeImage })).toBeNull();
    expect(screen.getByRole('button', { name: zh.word.flagImage })).toBeTruthy();
  });

  it('image_word off → the same picture without its word layer (?plain=1), the hook stays', async () => {
    h.settings.image_word = false;
    h.detail = ready(memoryCard);
    renderDetail();
    await screen.findByText('MEANING-ZH');
    expect(src()).toBe('/media/images/ab/0123.svg?plain=1');
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
  });

  it("falls back to the content's mnemonic when pictures are hidden or the picture brings no hook", async () => {
    h.settings.show_images = false;
    h.detail = ready(memoryCard);
    const hidden = renderDetail();
    await screen.findByText('MEANING-ZH');
    expect(screen.queryByRole('img')).toBeNull();
    expect(lines()).toEqual(['MNEMONIC-ZH']);
    expect(screen.queryByText('HOOK-ZH')).toBeNull();
    expect(screen.queryByText('NOTE-ZH')).toBeNull();
    hidden.unmount();

    h.settings.show_images = true;
    h.settings.image_word = false;
    h.detail = ready({ ...memoryCard, dancing: false, word_layer: false, hook_zh: null, note_zh: null }); // an older drawing
    renderDetail();
    await screen.findByText('MEANING-ZH');
    expect(src()).toBe('/media/images/ab/0123.svg'); // nothing to drop
    expect(lines()).toEqual(['MNEMONIC-ZH']);
    expect(screen.getByRole('button', { name: zh.word.changeImage })).toBeTruthy(); // and it can still be replaced
  });

  it("a picture that could not be loaded takes its hook with it; the failure is not held against the next word's picture, nor against a retry that arrives", async () => {
    const first: WordDetail = { ...ready(memoryCard), word: { ...ready(memoryCard).word, confusables: ['abundant'] } };
    const other: ImageMeta = { ...memoryCard, id: 9, url: '/media/images/cd/4567.svg', hook_zh: 'HOOK-2', note_zh: null };
    h.detail = first;
    renderDetail();
    await screen.findByText('MEANING-ZH');
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.queryByRole('img')).toBeNull(); // the box is empty …
    expect(lines()).toEqual(['MNEMONIC-ZH']); // … so the line about the picture goes too

    // the page moves on to another word without remounting: what it remembers is the source that failed, not "the picture failed"
    h.detail = { ...ready(other), word: { ...ready(other).word, id: 2, lemma: 'abundant', display: 'abundant', confusables: ['abandon'] } };
    fireEvent.click(screen.getByRole('link', { name: 'abundant' }));
    await screen.findByRole('heading', { level: 1, name: 'abundant' });
    expect(src()).toBe('/media/images/cd/4567.svg');
    expect(lines()).toEqual(['HOOK-2']);

    // and back: the source that failed is requested again — the content's mnemonic until it has arrived, then its hook
    h.detail = first;
    fireEvent.click(screen.getByRole('link', { name: 'abandon' }));
    await screen.findByRole('heading', { level: 1, name: 'abandon' });
    expect(src()).toBe('/media/images/ab/0123.svg');
    expect(lines()).toEqual(['MNEMONIC-ZH']);
    fireEvent.load(screen.getByRole('img'));
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
  });

  it('the hook comes with the picture: it shows while the word has no content yet; without a hook there is no mnemonic then', async () => {
    h.detail = { ...detailOf(mineRow()), image: memoryCard };
    const first = renderDetail();
    await screen.findByText(zh.study.contentFailed);
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    first.unmount();

    h.detail = detailOf(mineRow());
    renderDetail();
    await screen.findByText(zh.study.contentFailed);
    expect(lines()).toEqual([]);
  });
});

describe('WordDetailPage picture reports (FRONTEND §5.8, API.md 28; docs/MEMORY_CARDS_DESIGN.md §8)', () => {
  const photo: ImageMeta = { id: 5, url: '/media/images/cd/4567.jpg', kind: 'photo', provider: 'wikimedia', mime: 'image/jpeg', width: 1024, height: 640, alt_zh: 'PHOTO-ZH', attribution: null, dancing: false, word_layer: false, hook_zh: null, note_zh: null };
  /** An older drawing (svg-v2): same provider as a memory card, no word layer. */
  const drawing: ImageMeta = { id: 7, url: '/media/images/ab/0123.svg', kind: 'svg', provider: 'claude_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: 'SCENE-ZH', attribution: null, dancing: false, word_layer: false, hook_zh: null, note_zh: null };
  const memoryCard: ImageMeta = { ...drawing, id: 8, word_layer: true, hook_zh: 'HOOK-ZH', note_zh: 'NOTE-ZH' };
  /** What `GET …/image` answers once the reported picture is down. */
  const next: ImageMeta = { ...photo, id: 6, url: '/media/images/ef/89ab.jpg' };
  const src = () => (screen.getByRole('img') as HTMLImageElement).getAttribute('src');
  const flag = () => screen.getByRole('button', { name: zh.word.flagImage }) as HTMLButtonElement;
  const toasts = () => screen.queryAllByRole('status').map((t) => t.querySelector('.toast__msg')?.textContent);
  /** Lets the image poll tick: only the interval is faked, so `findBy…` / `waitFor` keep their real timers. */
  const tick = (ms: number) => act(async () => void (await vi.advanceTimersByTimeAsync(ms)));
  const open = async (image: ImageMeta) => {
    h.detail = { ...detailOf(mineRow()), image };
    const view = renderDetail();
    await screen.findByRole('img');
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] });
    return view;
  };

  beforeEach(() => {
    h.settings.show_images = true;
    vi.mocked(reportWord).mockResolvedValue({ id: 1 });
    vi.mocked(getWordImage).mockResolvedValue(next);
  });
  afterEach(() => {
    vi.useRealTimers();
    h.settings.show_images = false;
  });

  it.each([['a photo', photo], ['an older drawing', drawing]])('flag-image on %s: the report, the thanks, then the wait for the next picture — as before', async (_kind, image) => {
    await open(image);
    fireEvent.click(flag());
    await waitFor(() => expect(toasts()).toEqual([zh.word.reported]));
    expect(vi.mocked(reportWord).mock.calls).toEqual([[1, { target: 'image', reason: 'irrelevant_image' }]]);
    expect(flag().disabled).toBe(true); // parked until the replacement is in
    expect(screen.getByRole('button', { name: zh.word.changeImage }).getAttribute('aria-busy')).toBe('true');
    expect(getWordImage).not.toHaveBeenCalled();
    await tick(3_000);
    expect(vi.mocked(getWordImage).mock.calls).toEqual([[1]]);
    await waitFor(() => expect(src()).toBe(next.url));
    expect(flag().disabled).toBe(false);
    await tick(9_000);
    expect(getWordImage).toHaveBeenCalledTimes(1); // the poll ended with the new picture
  });

  it('flag-image on a memory card: the same report and the same thanks, and nothing else — the picture stays, nothing is polled, the button is not parked', async () => {
    await open(memoryCard);
    fireEvent.click(flag());
    await waitFor(() => expect(toasts()).toEqual([zh.word.reported])); // thanks only: the text promises no other picture
    expect(vi.mocked(reportWord).mock.calls).toEqual([[1, { target: 'image', reason: 'irrelevant_image' }]]);
    expect(flag().disabled).toBe(false);
    await tick(61_000); // longer than the whole poll (20 × 3 s) would run
    expect(getWordImage).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    expect(src()).toBe(memoryCard.url);
    expect(screen.getByText('HOOK-ZH')).toBeTruthy();
    expect(screen.queryByRole('button', { name: zh.word.changeImage })).toBeNull();
    expect(flag().disabled).toBe(false);
  });

  it('the report sheet with a picture reason follows the same rule: a photo is waited for, a memory card is not', async () => {
    for (const [image, polls] of [[photo, 1], [memoryCard, 0]] as const) {
      const view = await open(image);
      fireEvent.click(screen.getByRole('button', { name: zh.word.report }));
      fireEvent.click(screen.getByRole('radio', { name: zh.word.reportReasons.inappropriate_image }));
      fireEvent.click(screen.getByRole('button', { name: zh.common.confirm }));
      await waitFor(() => expect(toasts()).toEqual([zh.word.reported]));
      expect(vi.mocked(reportWord).mock.lastCall).toEqual([1, { target: 'image', reason: 'inappropriate_image' }]);
      await tick(3_000);
      expect(getWordImage).toHaveBeenCalledTimes(polls);
      view.unmount();
      vi.useRealTimers();
      vi.mocked(getWordImage).mockClear();
    }
  });

  it('a report that fails shows the error and starts no wait, whatever the picture', async () => {
    vi.mocked(reportWord).mockRejectedValue(new Error('offline'));
    await open(photo);
    fireEvent.click(flag());
    await waitFor(() => expect(toasts().length).toBe(1));
    expect(toasts()).not.toContain(zh.word.reported);
    await tick(3_000);
    expect(getWordImage).not.toHaveBeenCalled();
    expect(flag().disabled).toBe(false);
  });
});
