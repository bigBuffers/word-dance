// DancingWord (FRONTEND §6.5): letter spans with the syllable / stress / silent marks, the plain fallback without a spec, the
// static fallback when the Web Animations API is missing, and — with element.animate stubbed — the play contract: the initial
// token never plays, a token that moves after mount plays one animation per plan step, a remount with the same token does not
// replay, and `autoplay` plays once on mount before the first paint.
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DanceSpec } from '@/api/types';
import { DancingWord, canDance, prefersReducedMotion } from './DancingWord';
import { dancePlan } from './dances';

const rabbit: DanceSpec = { version: 1, letters: ['rab', 'bit'], stress: 0, marks: { double: [[2, 3]], silent: [] }, source: 'rule' };
const night: DanceSpec = { version: 1, letters: ['night'], stress: 0, marks: { double: [], silent: [2, 3] }, source: 'rule' };

describe('DancingWord', () => {
  it('renders one span per letter with the syllable index, the stressed and the silent marks, and reads as the word', () => {
    const { container } = render(
      <h2>
        <DancingWord text="rabbit" spec={rabbit} />
      </h2>,
    );
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('rabbit');
    const letters = container.querySelectorAll('.dword__l');
    expect(Array.from(letters).map((l) => l.textContent)).toEqual(['r', 'a', 'b', 'b', 'i', 't']);
    expect(Array.from(letters).map((l) => l.getAttribute('data-syl'))).toEqual(['0', '0', '0', '1', '1', '1']);
    expect(Array.from(letters).map((l) => l.classList.contains('dword__l--stressed'))).toEqual([true, true, true, false, false, false]);
    expect(container.querySelectorAll('.dword__l--silent')).toHaveLength(0);
  });

  it('marks silent letters and falls back to static in jsdom', () => {
    const { container } = render(<DancingWord text="night" spec={night} />);
    expect(Array.from(container.querySelectorAll('.dword__l--silent')).map((l) => l.textContent)).toEqual(['g', 'h']);
    expect(canDance()).toBe(false); // jsdom has no element.animate
    expect(prefersReducedMotion()).toBe(false); // the test setup's matchMedia answers false
    expect(container.querySelector('.dword--static')).not.toBeNull();
  });

  it('renders the plain text without a spec or when the spec does not spell the text', () => {
    const { container, rerender } = render(<DancingWord text="rabbit" spec={null} />);
    expect(container.querySelector('.dword')).toBeNull();
    expect(container.textContent).toBe('rabbit');
    rerender(<DancingWord text="rabbits" spec={rabbit} />);
    expect(container.querySelector('.dword')).toBeNull();
    expect(container.textContent).toBe('rabbits');
  });

  it('a moving token does not crash without the Web Animations API', () => {
    const { rerender, container } = render(<DancingWord text="rabbit" spec={rabbit} playToken={0} />);
    rerender(<DancingWord text="rabbit" spec={rabbit} playToken={1} />);
    rerender(<DancingWord text="rabbit" spec={rabbit} playToken={2} autoplay />);
    expect(container.querySelectorAll('.dword__l')).toHaveLength(6);
  });
});

describe('DancingWord play path (element.animate stubbed)', () => {
  let animate: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    animate = vi.fn(() => ({ finished: Promise.resolve(), cancel: () => undefined }));
    Object.defineProperty(Element.prototype, 'animate', { value: animate, configurable: true, writable: true });
  });
  afterEach(() => {
    delete (Element.prototype as unknown as { animate?: unknown }).animate;
  });

  it('the initial token never plays, a moved token plays one animation per plan step, a remount with that token does not replay', () => {
    const steps = dancePlan(rabbit, 'currentColor').length; // 6 letters enter + 6 beats + 2 twins
    const { rerender, unmount, container } = render(<DancingWord text="rabbit" spec={rabbit} playToken={3} />);
    expect(canDance()).toBe(true);
    expect(container.querySelector('.dword--static')).toBeNull();
    expect(animate).not.toHaveBeenCalled();
    rerender(<DancingWord text="rabbit" spec={rabbit} playToken={4} />);
    expect(animate).toHaveBeenCalledTimes(steps);
    expect(animate.mock.calls.every((call) => Array.isArray(call[0]) && typeof call[1] === 'object')).toBe(true);
    rerender(<DancingWord text="rabbit" spec={rabbit} playToken={4} />); // same token: nothing
    expect(animate).toHaveBeenCalledTimes(steps);
    unmount();
    render(<DancingWord text="rabbit" spec={rabbit} playToken={4} />); // the reveal remounts the header with the same token
    expect(animate).toHaveBeenCalledTimes(steps);
  });

  it('autoplay plays once on mount and the token still replays afterwards', () => {
    const steps = dancePlan(night, 'currentColor').length; // 5 letters enter + 3 beats (gh stay still), no twins
    const { rerender } = render(<DancingWord text="night" spec={night} autoplay />);
    expect(animate).toHaveBeenCalledTimes(steps);
    rerender(<DancingWord text="night" spec={night} autoplay playToken={1} />);
    expect(animate).toHaveBeenCalledTimes(2 * steps);
  });

  it('prefers-reduced-motion keeps the word static and never animates', () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: query.includes('reduce'), media: query, onchange: null, addListener: () => undefined, removeListener: () => undefined, addEventListener: () => undefined, removeEventListener: () => undefined, dispatchEvent: () => false })) as typeof window.matchMedia;
    try {
      const { rerender, container } = render(<DancingWord text="rabbit" spec={rabbit} autoplay />);
      expect(prefersReducedMotion()).toBe(true);
      expect(container.querySelector('.dword--static')).not.toBeNull();
      rerender(<DancingWord text="rabbit" spec={rabbit} autoplay playToken={1} />);
      expect(animate).not.toHaveBeenCalled();
    } finally {
      window.matchMedia = original;
    }
  });
});
