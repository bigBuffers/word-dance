// WordHeader with a dance spec (FRONTEND §4, §6.5): the display form becomes a DancingWord with the heading named after the word,
// a named list of syllable chips marks the stressed syllable, 🔊 replays the dance even without speech synthesis (the replay label),
// and without the prop the header renders exactly as before (no chips, plain text, 🔊 disabled in jsdom).
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DanceSpec } from '@/api/types';
import { zh } from '@/i18n/zh';
import { dancePlan } from './dances';
import { WordHeader } from './WordHeader';

const word = { display: 'yesterday', phonetic: "'jestədi", stages: ['xs' as const], stage_min: 1 as const, cet6_star: false };
const spec: DanceSpec = { version: 1, letters: ['yes', 'ter', 'day'], stress: 0, marks: { double: [], silent: [] }, source: 'rule' };

describe('WordHeader word dance', () => {
  it('shows the syllable chips with the stressed one marked, names the heading after the word and keeps its text', () => {
    render(<WordHeader word={word} as="h2" size="lg" dance={spec} />);
    const heading = screen.getByRole('heading', { level: 2, name: 'yesterday' });
    expect(heading.textContent).toBe('yesterday');
    const chips = screen.getAllByRole('listitem').filter((li) => li.classList.contains('syl__chip'));
    expect(chips.map((c) => c.textContent)).toEqual(['yes', 'ter', 'day']);
    expect(chips.map((c) => c.classList.contains('syl__chip--stressed'))).toEqual([true, false, false]);
    expect(screen.getByRole('list', { name: zh.word.syllables })).toBeTruthy();
    expect(screen.getByText("/'jestədi/")).toBeTruthy();
  });

  it('a one-chunk spec shows no chips, a null spec renders plain letters, and no prop means no dance at all', () => {
    const one: DanceSpec = { ...spec, letters: ['yesterday'] };
    const { container, rerender } = render(<WordHeader word={word} as="h2" dance={one} />);
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    expect(container.querySelector('.dword')).not.toBeNull();
    rerender(<WordHeader word={word} as="h2" dance={null} />);
    expect(container.querySelector('.dword')).toBeNull();
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('yesterday');
    expect(screen.getByRole('heading', { level: 2 }).getAttribute('aria-label')).toBeNull();
    rerender(<WordHeader word={word} as="h2" />);
    expect(container.querySelector('.dword')).toBeNull();
    expect(screen.queryByRole('list', { name: zh.word.syllables })).toBeNull();
    expect((screen.getByRole('button') as HTMLButtonElement).disabled).toBe(true); // no speechSynthesis and no dance: 🔊 is disabled as before
  });

  describe('🔊 replays the dance (element.animate stubbed, no speechSynthesis)', () => {
    let animate: ReturnType<typeof vi.fn>;
    beforeEach(() => {
      animate = vi.fn(() => ({ finished: Promise.resolve(), cancel: () => undefined }));
      Object.defineProperty(Element.prototype, 'animate', { value: animate, configurable: true, writable: true });
    });
    afterEach(() => {
      delete (Element.prototype as unknown as { animate?: unknown }).animate;
    });

    it('the button stays usable with the replay label and each click plays the whole plan once', () => {
      render(<WordHeader word={word} as="h2" dance={spec} playToken={2} />);
      const button = screen.getByRole('button', { name: zh.word.replayDance }) as HTMLButtonElement;
      expect(button.disabled).toBe(false);
      expect(animate).not.toHaveBeenCalled(); // the initial token never plays
      fireEvent.click(button);
      const steps = dancePlan(spec, 'currentColor').length;
      expect(animate).toHaveBeenCalledTimes(steps);
      fireEvent.click(button);
      expect(animate).toHaveBeenCalledTimes(2 * steps);
    });
  });
});
