// FRONTEND §7: one render test for StudyCard — reveal → grade bar; screen kind → known / unfamiliar;
// content_state 'failed' → the generate-examples button; content_deferred_until set → the deferred copy,
// no skeleton, no generate button.
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import type { Grade, ImageMeta, StudyItem } from '@/api/types';
import { zh } from '@/i18n/zh';
import { contentMode, resultLabel, StudyCard } from './StudyCard';

const image: ImageMeta = { id: null, url: '/media/card/5.svg', kind: 'card', provider: 'card_svg', mime: 'image/svg+xml', width: 800, height: 500, alt_zh: null, attribution: null };

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
      stage_min: 2,
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
      confusables: ['abundant'],
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

  it('exposes contentMode / resultLabel helpers', () => {
    expect(contentMode(item())).toBe('ready');
    expect(contentMode(item({ content: null, content_state: 'queued' }))).toBe('pending');
    expect(contentMode(item({ content_deferred_until: 'x' }))).toBe('deferred');
    expect(contentMode(item({ content: null, content_state: 'none' }))).toBe('failed');
    expect(resultLabel('master')).toBe(zh.study.master);
    expect(resultLabel(null)).toBeNull();
  });
});
