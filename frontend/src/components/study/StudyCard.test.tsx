// FRONTEND §7: one render test for StudyCard — reveal → grade bar; screen kind → known / unfamiliar;
// content_state 'failed' → the generate-examples button; content_deferred_until set → the deferred copy,
// no skeleton, no generate button. PLAN §6 S4: `onlyStages` reaches the WordHeader of all three faces, and a word
// outside every list keeps its dashed outside-the-lists chip even without a phonetic. Memory cards (docs/MEMORY_CARDS_DESIGN.md
// §3.6–3.7): the mnemonic section shows the picture's hook + caveat while the picture is shown (else the content's mnemonic),
// `imageWord` off asks for the picture without its word layer, and such a picture never offers refresh-image.
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Grade, ImageMeta, StudyItem } from '@/api/types';
import { zh } from '@/i18n/zh';
import { contentMode, resultLabel, StudyCard } from './StudyCard';

const image: ImageMeta = { id: null, url: '/media/card/5.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: null, attribution: null, dancing: false, word_layer: false, hook_zh: null, note_zh: null };

function item(over: Partial<StudyItem> = {}): StudyItem {
  return {
    item_id: 5,
    kind: 'new',
    position: 0,
    result: null,
    skip_count: 0,
    requeue_at: null,
    word: {
      id: 55,
      lemma: 'abandon',
      display: 'abandon',
      kind: 'word',
      phonetic: 'əˈbændən',
      translation_short: 'v. give up',
      stages: ['gk', 'cet4', 'cet6'],
      stage_min: 3,
      cet6_star: false,
      frq: 1200,
      collins: 3,
      oxford: true,
      difficulty: null,
      is_public: true,
      is_valid_english: true,
      my_state: 'new',
      content_state: 'ready',
      image_state: 'none',
      definition: 'to leave somebody or something',
      translation: 'v. give up; desert\nn. wild abandon',
      pos: 'n:4/v:96',
      forms: ['abandoned', 'abandoning', 'abandons'],
      confusables: ['abundant'], dance: null,
    },
    mine: {
      id: 9,
      word_id: 55,
      state: 'new',
      origin: 'browse',
      priority: 50,
      note: null,
      input_text: null,
      needs_attention: false,
      attention_msg: null,
      suggested_word: null,
      srs: { ease: 2.5, interval_days: 0, step: 0, repetitions: 0, lapses: 0, consecutive_good: 0, due_at: null, last_graded_at: null, mastery_suggested: false },
      times_pushed: 1,
      times_added: 1,
      added_at: '2026-10-13T00:00:00Z',
      first_added_at: '2026-10-13T00:00:00Z',
      mastered_at: null,
    },
    content: {
      word: 'abandon',
      valid: true,
      meaning_zh: 'MEANING-ZH',
      meaning_en: 'to leave',
      examples: [
        { en: 'They had to abandon the car in the snow.', zh: 'EXAMPLE-ZH-1' },
        { en: 'She abandoned hope.', zh: 'EXAMPLE-ZH-2' },
      ],
      collocations: ['abandon ship', 'abandon a plan'],
      mnemonic_zh: 'MNEMONIC-ZH',
      image_keywords: ['abandoned car'],
      image_alt_zh: 'ALT-ZH',
      difficulty: 2,
      version: 1,
      prompt_version: 'content_v1',
      model: 'sonnet',
      created_at: '2026-10-13T00:00:00Z',
    },
    content_state: 'ready',
    content_deferred_until: null,
    image,
    ...over,
  };
}

const preview: Record<Grade, string> = { again: zh.study.nextDue.tenMin, hard: zh.study.nextDue.tenMin, good: zh.study.nextDue.tenMin, master: zh.study.nextDue.mastered, skip: zh.study.nextDue.skipped };

function renderCard(props: Partial<Parameters<typeof StudyCard>[0]> = {}) {
  const handlers = { onReveal: vi.fn(), onGrade: vi.fn(), onMaster: vi.fn(), onSkip: vi.fn(), onRequestContent: vi.fn() };
  const utils = render(
    <MemoryRouter>
      <StudyCard item={item()} revealed={false} zhMode="tap" showImage={false} preview={preview} {...handlers} {...props} />
    </MemoryRouter>,
  );
  return { ...utils, ...handlers };
}

/** First button whose accessible name starts with `name` (the skip button exists twice: header and grade bar). */
const button = (name: string) => {
  const found = screen.getAllByRole('button', { name: new RegExp(`^${name}`) });
  if (!found[0]) throw new Error(`no button ${name}`);
  return found[0];
};
const queryButton = (name: string) => screen.queryAllByRole('button', { name: new RegExp(`^${name}`) })[0] ?? null;
/** The header's stage chips (the only named list on the card; collocation / confusable lists carry no name). */
const stageChips = () => within(screen.getByRole('list', { name: zh.word.examTags })).getAllByRole('listitem');

describe('StudyCard', () => {
  it('shows the front with the reveal button and no grade bar; reveal → grade bar with the preview', () => {
    const { onReveal, onGrade, rerender } = renderCard();
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('abandon');
    expect(queryButton(zh.study.good)).toBeNull();
    fireEvent.click(button(zh.study.reveal));
    expect(onReveal).toHaveBeenCalledTimes(1);

    rerender(
      <MemoryRouter>
        <StudyCard item={item()} revealed zhMode="tap" showImage={false} preview={{ ...preview, good: zh.study.nextDue.days(3) }} onReveal={onReveal} onGrade={onGrade} onMaster={vi.fn()} onSkip={vi.fn()} />
      </MemoryRouter>,
    );
    expect(queryButton(zh.study.reveal)).toBeNull();
    fireEvent.click(button(zh.study.again));
    fireEvent.click(button(zh.study.hard));
    fireEvent.click(button(zh.study.good));
    expect(onGrade.mock.calls.map((c) => c[0])).toEqual(['again', 'hard', 'good']);
    expect(button(zh.study.good).textContent).toContain(zh.study.nextDue.days(3));
    expect(screen.getByText(/^MEANING-ZH/)).toBeTruthy();
    // examples are highlighted, the collocations and the confusable chip are rendered
    expect(screen.getAllByText('abandon', { selector: 'mark' }).length).toBeGreaterThan(0);
    expect(screen.getByText('abandon ship')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'abundant' }).getAttribute('href')).toBe('/words/abundant');
    expect(screen.getByText(new RegExp(zh.study.nextLabel))).toBeTruthy();
    // a never-graded card says "not reviewed yet" instead of a zeroth review with a zero-day interval
    expect(screen.queryByText(zh.study.srsLine(0, 0), { exact: false })).toBeNull();
    expect(screen.getByText(zh.study.srsNew, { exact: false })).toBeTruthy();
    // ECDICT's pos ratio is rendered as readable shares, dominant class first
    expect(screen.getByText('v. 96% · n. 4%')).toBeTruthy();
    expect(screen.queryByText('n:4/v:96')).toBeNull();
  });

  it('shows the SRS line once the card has been reviewed and the position counter in the header', () => {
    const mine = item().mine!;
    renderCard({
      revealed: true,
      position: 12,
      total: 41,
      item: item({ kind: 'review', mine: { ...mine, state: 'learning', srs: { ...mine.srs, repetitions: 3, interval_days: 8 } } }),
    });
    expect(screen.getByText(zh.study.srsLine(3, 8), { exact: false })).toBeTruthy();
    expect(screen.queryByText(zh.study.srsNew, { exact: false })).toBeNull();
    expect(screen.getByText(zh.study.position(12, 41))).toBeTruthy();
  });

  it('shows the hint cloze on the front and calls onMaster / onSkip', () => {
    const { onMaster, onSkip } = renderCard({ hint: true, revealed: true });
    fireEvent.click(button(zh.study.master));
    fireEvent.click(button(zh.study.skip));
    expect(onMaster).toHaveBeenCalledTimes(1);
    expect(onSkip).toHaveBeenCalled();
    renderCard({ hint: true, revealed: false });
    expect(screen.getByText('They had to ___ the car in the snow.')).toBeTruthy();
  });

  it('renders a screen card with known / unfamiliar directly and the peek', () => {
    const { onGrade, onReveal } = renderCard({ item: item({ kind: 'screen', mine: null, content: null, content_state: 'none' }) });
    fireEvent.click(button(zh.study.known));
    fireEvent.click(button(zh.study.unfamiliar));
    expect(onGrade.mock.calls.map((c) => c[0])).toEqual(['known', 'unfamiliar']);
    expect(queryButton(zh.study.good)).toBeNull();
    fireEvent.click(button(zh.study.reveal));
    expect(onReveal).toHaveBeenCalledTimes(1);
  });

  it('content_state failed → the failed copy and the generate-examples button', () => {
    const { onRequestContent } = renderCard({ revealed: true, item: item({ content: null, content_state: 'failed' }) });
    expect(screen.getByText(zh.study.contentFailed)).toBeTruthy();
    fireEvent.click(button(zh.word.generateExamples));
    expect(onRequestContent).toHaveBeenCalledTimes(1);
  });

  it('content_deferred_until set → the deferred copy without skeleton or generate button', () => {
    const { container } = renderCard({ revealed: true, item: item({ content: null, content_state: 'queued', content_deferred_until: '2026-10-15T00:05:00Z' }) });
    expect(screen.getByText(zh.study.contentDeferred)).toBeTruthy();
    expect(container.querySelector('.skeleton')).toBeNull();
    expect(queryButton(zh.word.generateExamples)).toBeNull();
    expect(screen.queryByText(zh.study.contentPending)).toBeNull();
  });

  it('content queued and not deferred → pending copy with skeleton lines', () => {
    const { container } = renderCard({ revealed: true, item: item({ content: null, content_state: 'queued' }) });
    expect(screen.getByText(zh.study.contentPending)).toBeTruthy();
    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThan(0);
  });

  it('read-only replay shows the outcome chip and no grade bar', () => {
    renderCard({ readOnly: true, item: item({ result: 'good' }) });
    expect(screen.getByText(zh.study.good)).toBeTruthy();
    expect(queryButton(zh.study.again)).toBeNull();
    expect(queryButton(zh.study.skip)).toBeNull();
  });

  it('`onlyStages` narrows the header chips on the screen card, the front and the back to my targets plus the lowest stage', () => {
    // the fixture word is gk / cet4 / cet6 (stage_min 3)
    const screenCard = renderCard({ onlyStages: ['xs'], item: item({ kind: 'screen', mine: null, content: null, content_state: 'none' }) });
    expect(stageChips().map((li) => li.textContent)).toEqual([zh.stages.gk]); // nothing of it is targeted → lowest stage kept
    screenCard.unmount();
    const front = renderCard({ onlyStages: ['cet6'] });
    expect(stageChips().map((li) => li.textContent)).toEqual([zh.stages.gk, zh.stages.cet6]);
    front.unmount();
    renderCard({ onlyStages: ['cet6'], revealed: true });
    expect(stageChips().map((li) => li.textContent)).toEqual([zh.stages.gk, zh.stages.cet6]);
  });

  it('a word outside every list with no phonetic still shows the dashed chip on the card', () => {
    renderCard({ item: item({ word: { ...item().word, phonetic: null, stages: [], stage_min: null } }) });
    const chips = stageChips();
    expect(chips.map((li) => li.textContent)).toEqual([zh.stages.outside]);
    expect(chips[0]?.classList.contains('chip--outside')).toBe(true);
  });

  it('exposes contentMode / resultLabel helpers', () => {
    expect(contentMode(item())).toBe('ready');
    expect(contentMode(item({ content: null, content_state: 'queued' }))).toBe('pending');
    expect(contentMode(item({ content_deferred_until: 'x' }))).toBe('deferred');
    expect(contentMode(item({ content: null, content_state: 'none' }))).toBe('failed');
    expect(resultLabel('master')).toBe(zh.study.master);
    expect(resultLabel(null)).toBeNull();
  });
});

describe('bottom bar offset (toasts stack above the grade bar)', () => {
  it('the grade bar publishes --bottom-bar-h on <html> while mounted; a read-only replay and an unmounted card do not', () => {
    const root = document.documentElement;
    // jsdom lays nothing out: pretend every measured element is a 96 px bar flush with the bottom of the viewport
    const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return { top: window.innerHeight - 96, height: 96, bottom: window.innerHeight, left: 0, right: 0, width: 0, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    });
    const { unmount } = renderCard({ revealed: true });
    expect(root.classList.contains('has-bottom-bar')).toBe(true);
    expect(root.style.getPropertyValue('--bottom-bar-h')).toMatch(/^\d+px$/);
    unmount();
    expect(root.classList.contains('has-bottom-bar')).toBe(false);
    expect(root.style.getPropertyValue('--bottom-bar-h')).toBe('');

    const screenCard = renderCard({ item: item({ kind: 'screen' }) });
    expect(root.classList.contains('has-bottom-bar')).toBe(true);
    screenCard.unmount();

    renderCard({ readOnly: true, item: item({ result: 'good' }) });
    expect(root.classList.contains('has-bottom-bar')).toBe(false);
    rect.mockRestore();
  });
});

describe('StudyCard word dance (FRONTEND §5.1.1, §6.5)', () => {
  const spec = { version: 1 as const, letters: ['a', 'ban', 'don'], stress: 1, marks: { double: [] as [number, number][], silent: [] as number[] }, semantic: null, source: 'rule' as const };

  it('danceMode full → the headword dances and the syllable chips mark the stressed chunk on the front and on the back', () => {
    const danced = item();
    danced.word = { ...danced.word, dance: spec };
    const { rerender, onReveal, onGrade, onMaster, onSkip, onRequestContent } = renderCard({ item: danced, danceMode: 'full', danceToken: 0 });
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('abandon');
    const chips = within(screen.getByRole('list', { name: zh.word.syllables })).getAllByRole('listitem');
    expect(chips.map((c) => c.textContent)).toEqual(['a', 'ban', 'don']);
    expect(chips.map((c) => c.classList.contains('syl__chip--stressed'))).toEqual([false, true, false]);
    rerender(
      <MemoryRouter>
        <StudyCard item={danced} revealed zhMode="tap" showImage={false} preview={preview} onReveal={onReveal} onGrade={onGrade} onMaster={onMaster} onSkip={onSkip} onRequestContent={onRequestContent} danceMode="full" danceToken={1} />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('abandon');
    expect(screen.getByRole('list', { name: zh.word.syllables })).toBeTruthy();
  });

  it('a screen item carries the dancing headword and the syllable chips too; danceMode off keeps it plain', () => {
    const danced = item({ kind: 'screen' });
    danced.word = { ...danced.word, dance: spec };
    const first = renderCard({ item: danced, danceMode: 'full', danceToken: 1, danceAutoplay: true });
    expect(within(screen.getByRole('list', { name: zh.word.syllables })).getAllByRole('listitem').map((c) => c.textContent)).toEqual(['a', 'ban', 'don']);
    expect(first.container.querySelector('.dword')).not.toBeNull();
    expect(screen.getByRole('heading', { level: 2, name: 'abandon' }).textContent).toBe('abandon');
    first.unmount();
    const second = renderCard({ item: danced });
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    expect(second.container.querySelector('.dword')).toBeNull();
  });

  it('danceMode off (the default) and a null spec render the plain headword without chips', () => {
    const danced = item();
    danced.word = { ...danced.word, dance: spec };
    const first = renderCard({ item: danced });
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    expect(first.container.querySelector('.dword')).toBeNull();
    first.unmount();
    const second = renderCard({ danceMode: 'full' }); // item().word.dance is null
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    expect(second.container.querySelector('.dword')).toBeNull();
  });
});

describe('StudyCard semantic dance at the reveal (FRONTEND §5.1.2, §6.5; element.animate stubbed)', () => {
  const spec = { version: 1 as const, letters: ['a', 'ban', 'don'], stress: 1, marks: { double: [] as [number, number][], silent: [] as number[] }, semantic: { primitive: 'rise' as const, params: {} }, source: 'claude' as const };
  let animate: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    animate = vi.fn(() => ({ finished: Promise.resolve(), cancel: () => undefined }));
    Object.defineProperty(Element.prototype, 'animate', { value: animate, configurable: true, writable: true });
  });
  afterEach(() => {
    delete (Element.prototype as unknown as { animate?: unknown }).animate;
  });

  it("full mode: the front autoplays the form dance, the back autoplays the meaning; form_only never plays the meaning", () => {
    const danced = item();
    danced.word = { ...danced.word, dance: spec };
    const { rerender, onReveal, onGrade, onMaster, onSkip, onRequestContent, container } = renderCard({ item: danced, danceMode: 'full', danceToken: 0, danceAutoplay: true });
    const formSteps = animate.mock.calls.length;
    expect(formSteps).toBeGreaterThan(0);
    expect(container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBeNull(); // the front never shows the meaning (no object, pose or ghosts)
    rerender(
      <MemoryRouter>
        <StudyCard item={danced} revealed zhMode="tap" showImage={false} preview={preview} onReveal={onReveal} onGrade={onGrade} onMaster={onMaster} onSkip={onSkip} onRequestContent={onRequestContent} danceMode="full" danceToken={0} danceAutoplay />
      </MemoryRouter>,
    );
    expect(container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBe('rise'); // the back carries the primitive
    expect(animate.mock.calls.length).toBeGreaterThan(formSteps); // the back face mounted and played the semantic dance
    const afterReveal = animate.mock.calls.length;

    animate.mockClear();
    const second = renderCard({ item: danced, danceMode: 'form_only', danceToken: 0, danceAutoplay: true });
    expect(animate.mock.calls.length).toBe(formSteps);
    expect(second.container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBeNull();
    second.rerender(
      <MemoryRouter>
        <StudyCard item={danced} revealed zhMode="tap" showImage={false} preview={preview} onReveal={onReveal} onGrade={onGrade} onMaster={onMaster} onSkip={onSkip} onRequestContent={onRequestContent} danceMode="form_only" danceToken={0} danceAutoplay />
      </MemoryRouter>,
    );
    expect(animate.mock.calls.length).toBe(formSteps); // nothing on the back in form_only
    expect(afterReveal).toBeGreaterThan(formSteps);
  });

  it('a screen item plays the spelling + stress dance when it shows — never the meaning, not even in full mode or after the peek', () => {
    const front = renderCard({ item: (() => { const it = item(); it.word = { ...it.word, dance: spec }; return it; })(), danceMode: 'full', danceToken: 0, danceAutoplay: true });
    const formSteps = animate.mock.calls.length; // what a card front plays
    front.unmount();
    animate.mockClear();

    const danced = item({ kind: 'screen' });
    danced.word = { ...danced.word, dance: spec };
    const { rerender, onReveal, onGrade, onMaster, onSkip, onRequestContent, container } = renderCard({ item: danced, danceMode: 'full', danceToken: 0, danceAutoplay: true });
    expect(formSteps).toBeGreaterThan(0);
    expect(animate.mock.calls.length).toBe(formSteps); // the same form dance, on show
    expect(container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBeNull(); // no stage object, pose or ghosts: the meaning stays hidden
    rerender(
      <MemoryRouter>
        <StudyCard item={danced} revealed zhMode="tap" showImage={false} preview={preview} onReveal={onReveal} onGrade={onGrade} onMaster={onMaster} onSkip={onSkip} onRequestContent={onRequestContent} danceMode="full" danceToken={0} danceAutoplay />
      </MemoryRouter>,
    );
    expect(animate.mock.calls.length).toBe(formSteps); // the peek shows the meaning as text; the header does not remount and nothing replays
    expect(container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBeNull();
    rerender(
      <MemoryRouter>
        <StudyCard item={danced} revealed zhMode="tap" showImage={false} preview={preview} onReveal={onReveal} onGrade={onGrade} onMaster={onMaster} onSkip={onSkip} onRequestContent={onRequestContent} danceMode="full" danceToken={1} danceAutoplay />
      </MemoryRouter>,
    );
    expect(animate.mock.calls.length).toBe(2 * formSteps); // key P (the page's token): the form dance again, still no meaning

    animate.mockClear();
    const quiet = renderCard({ item: danced, danceMode: 'full', danceToken: 0 }); // the page decides: without danceAutoplay nothing plays on show
    expect(animate).not.toHaveBeenCalled();
    quiet.unmount();
  });
});

describe('StudyCard memory cards (FRONTEND §5.1.2; docs/MEMORY_CARDS_DESIGN.md §3.6–3.7)', () => {
  const memoryCard: ImageMeta = { id: 8, url: '/media/images/ab/0123.svg', kind: 'svg', provider: 'claude_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: 'SCENE-ZH', attribution: null, dancing: false, word_layer: true, hook_zh: 'HOOK-ZH', note_zh: 'NOTE-ZH' };
  const mnemonic = () => screen.queryByRole('region', { name: zh.study.mnemonic });
  const lines = () => Array.from(mnemonic()?.querySelectorAll('p') ?? []).map((p) => p.textContent);
  const src = () => (screen.getByRole('img') as HTMLImageElement).getAttribute('src');

  it("the mnemonic section shows the picture's hook and, in a quieter second line, its caveat — not the content's mnemonic", () => {
    const both = renderCard({ revealed: true, showImage: true, item: item({ image: memoryCard }) });
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    expect(mnemonic()?.querySelector('.study-card__mnemonic')?.textContent).toBe('HOOK-ZH');
    expect(mnemonic()?.querySelector('.study-card__mnemonic-note')?.textContent).toBe('NOTE-ZH');
    expect(screen.queryByText('MNEMONIC-ZH')).toBeNull();
    both.unmount();

    renderCard({ revealed: true, showImage: true, item: item({ image: { ...memoryCard, note_zh: null } }) });
    expect(lines()).toEqual(['HOOK-ZH']); // no caveat → one line
  });

  it("falls back to the content's mnemonic when pictures are hidden or the picture brings no hook", () => {
    const hidden = renderCard({ revealed: true, showImage: false, item: item({ image: memoryCard }) });
    expect(lines()).toEqual(['MNEMONIC-ZH']);
    expect(screen.queryByText('HOOK-ZH')).toBeNull();
    expect(screen.queryByText('NOTE-ZH')).toBeNull();
    hidden.unmount();

    renderCard({ revealed: true, showImage: true }); // the fixture's template card: no hook
    expect(lines()).toEqual(['MNEMONIC-ZH']);
  });

  it('the hook comes with the picture, not with the content: it shows while the examples are pending; neither → no section', () => {
    const waiting = item({ image: memoryCard, content: null, content_state: 'queued' });
    const pending = renderCard({ revealed: true, showImage: true, item: waiting });
    expect(screen.getByText(zh.study.contentPending)).toBeTruthy();
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    pending.unmount();

    renderCard({ revealed: true, showImage: false, item: waiting });
    expect(mnemonic()).toBeNull();
  });

  it("a picture that could not be loaded takes its hook with it — the content's mnemonic is back —, and only that source's", () => {
    const handlers = { onReveal: vi.fn(), onGrade: vi.fn(), onMaster: vi.fn(), onSkip: vi.fn() };
    const card = (imageWord: boolean, over: Partial<StudyItem> = {}) => (
      <MemoryRouter>
        <StudyCard item={item({ image: memoryCard, ...over })} revealed zhMode="tap" showImage imageWord={imageWord} preview={preview} {...handlers} />
      </MemoryRouter>
    );
    const { rerender, unmount } = render(card(true));
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    fireEvent.error(screen.getByRole('img'));
    expect(screen.queryByRole('img')).toBeNull(); // the box is empty …
    expect(lines()).toEqual(['MNEMONIC-ZH']); // … so the line about the picture goes too, and the content's own mnemonic shows
    expect(screen.queryByText('NOTE-ZH')).toBeNull();

    // the failure belongs to the source that failed: the other variant is another request, and its hook is not withheld
    rerender(card(false));
    expect(src()).toBe('/media/images/ab/0123.svg?plain=1');
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);

    // back on the source that failed, which is requested again: the content's mnemonic until the picture has arrived
    rerender(card(true));
    expect(src()).toBe('/media/images/ab/0123.svg');
    expect(lines()).toEqual(['MNEMONIC-ZH']);
    fireEvent.load(screen.getByRole('img'));
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    unmount();

    // no ready content to fall back to → no section at all, rather than a line about a picture that is not there
    render(card(true, { content: null, content_state: 'queued' }));
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']);
    fireEvent.error(screen.getByRole('img'));
    expect(mnemonic()).toBeNull();
  });

  it('the front face leaks neither the picture nor its hook', () => {
    renderCard({ showImage: true, item: item({ image: memoryCard }) });
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByText('HOOK-ZH')).toBeNull();
    expect(mnemonic()).toBeNull();
  });

  it('imageWord off → the same picture without its word layer (?plain=1); on, and when omitted, the whole picture', () => {
    const off = renderCard({ revealed: true, showImage: true, imageWord: false, item: item({ image: memoryCard }) });
    expect(src()).toBe('/media/images/ab/0123.svg?plain=1');
    expect(lines()).toEqual(['HOOK-ZH', 'NOTE-ZH']); // the hook is about the picture, with or without the word on it
    off.unmount();
    const on = renderCard({ revealed: true, showImage: true, imageWord: true, item: item({ image: memoryCard }) });
    expect(src()).toBe('/media/images/ab/0123.svg');
    on.unmount();
    const omitted = renderCard({ revealed: true, showImage: true, item: item({ image: memoryCard }) });
    expect(src()).toBe('/media/images/ab/0123.svg');
    omitted.unmount();
    renderCard({ revealed: true, showImage: true, imageWord: false }); // the template card has no word layer to drop
    expect(src()).toBe('/media/card/5.svg');
  });

  it('never offers refresh-image on a memory card while flag-image stays; other images keep both', () => {
    const onImageRefresh = vi.fn();
    const onImageFlag = vi.fn();
    const card = renderCard({ revealed: true, showImage: true, item: item({ image: memoryCard }), onImageRefresh, onImageFlag });
    expect(queryButton(zh.word.changeImage)).toBeNull();
    fireEvent.click(button(zh.word.flagImage));
    expect(onImageFlag).toHaveBeenCalledTimes(1);
    card.unmount();

    renderCard({ revealed: true, showImage: true, onImageRefresh, onImageFlag });
    fireEvent.click(button(zh.word.changeImage));
    expect(onImageRefresh).toHaveBeenCalledTimes(1);
    expect(button(zh.word.flagImage)).toBeTruthy();
  });
});
