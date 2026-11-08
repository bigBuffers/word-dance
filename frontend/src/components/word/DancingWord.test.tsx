// DancingWord (FRONTEND §6.5): letter spans with the syllable / stress / silent marks, the plain fallback without a spec, the
// static fallback when the Web Animations API is missing, and — with element.animate stubbed — the play contract: the initial
// token never plays, a token that moves after mount plays one animation per plan step, a remount with the same token does not
// replay, and `autoplay` plays once on mount before the first paint.
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DanceSpec } from '@/api/types';
import { DancingWord, canDance, prefersReducedMotion } from './DancingWord';
import { SEMANTIC_GAP_MS, danceDuration, dancePlan, semanticPlan } from './dances';

const rabbit: DanceSpec = { version: 1, letters: ['rab', 'bit'], stress: 0, marks: { double: [[2, 3]], silent: [] }, semantic: null, source: 'rule' };
const night: DanceSpec = { version: 1, letters: ['night'], stress: 0, marks: { double: [], silent: [2, 3] }, semantic: null, source: 'rule' };

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
    rerender(<DancingWord text="rabbit" spec={rabbit} playToken={2} autoplay="form" />);
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
    const { rerender } = render(<DancingWord text="night" spec={night} autoplay="form" />);
    expect(animate).toHaveBeenCalledTimes(steps);
    rerender(<DancingWord text="night" spec={night} autoplay="form" playToken={1} />);
    expect(animate).toHaveBeenCalledTimes(2 * steps);
  });

  it('prefers-reduced-motion keeps the word static and never animates', () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: query.includes('reduce'), media: query, onchange: null, addListener: () => undefined, removeListener: () => undefined, addEventListener: () => undefined, removeEventListener: () => undefined, dispatchEvent: () => false })) as typeof window.matchMedia;
    try {
      const { rerender, container } = render(<DancingWord text="rabbit" spec={rabbit} autoplay="form" />);
      expect(prefersReducedMotion()).toBe(true);
      expect(container.querySelector('.dword--static')).not.toBeNull();
      rerender(<DancingWord text="rabbit" spec={rabbit} autoplay="form" playToken={1} />);
      expect(animate).not.toHaveBeenCalled();
    } finally {
      window.matchMedia = original;
    }
  });
});

describe('DancingWord semantic dance', () => {
  const inSpec: DanceSpec = { version: 1, letters: ['in'], stress: 0, marks: { double: [], silent: [] }, semantic: { primitive: 'enter', params: {} }, source: 'claude' };
  const three: DanceSpec = { version: 1, letters: ['three'], stress: 0, marks: { double: [[3, 4]], silent: [] }, semantic: { primitive: 'multiply', params: { n: 3 } }, source: 'claude' };
  const red: DanceSpec = { version: 1, letters: ['red'], stress: 0, marks: { double: [], silent: [] }, semantic: { primitive: 'color', params: { color: 'red' } }, source: 'claude' };
  const onSpec: DanceSpec = { version: 1, letters: ['on'], stress: 0, marks: { double: [], silent: [] }, semantic: { primitive: 'onto', params: {} }, source: 'claude' };
  const jump: DanceSpec = { version: 1, letters: ['jump'], stress: 0, marks: { double: [], silent: [] }, semantic: { primitive: 'hop', params: {} }, source: 'claude' };

  it('draws the stage object, the ghost copies and the pose colour the primitive asks for', () => {
    const { container, rerender } = render(<DancingWord text="in" spec={inSpec} />);
    expect(container.querySelector('.dword-stage--box .dword-obj--box')).not.toBeNull();
    expect(container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBe('enter');
    rerender(<DancingWord text="on" spec={onSpec} />);
    expect(container.querySelector('.dword-stage--shelf .dword-obj--shelf')).not.toBeNull(); // P3: on lands on a shelf
    expect(container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBe('onto');
    rerender(<DancingWord text="jump" spec={jump} />);
    expect(container.querySelector('.dword-stage[data-primitive="hop"] .dword')).not.toBeNull(); // the hook word.css keys the foot transform-origin on
    expect(container.querySelector('.dword-obj')).toBeNull(); // hop has no stage object
    rerender(<DancingWord text="three" spec={three} />);
    expect(container.querySelectorAll('.dword__ghost')).toHaveLength(2);
    expect(container.querySelector('.dword-obj')).toBeNull();
    rerender(<DancingWord text="red" spec={red} />);
    expect((container.querySelector('.dword') as HTMLElement).style.color).toBe('var(--pose-red)'); // the theme token, resolved by the browser
    expect(container.querySelector('.dword')?.classList.contains('dword--posed')).toBe(true); // the static fallback lets the pose win over the stress mark
    expect(container.querySelectorAll('.dword__l--stressed')).toHaveLength(0); // a one-chunk word carries no stress information
    rerender(<DancingWord text="in" spec={inSpec} />);
    expect(container.querySelector('.dword')?.classList.contains('dword--posed')).toBe(false);
  });

  it('semanticEnabled=false (form_only) drops the object, the ghosts and the pose', () => {
    const { container, rerender } = render(<DancingWord text="in" spec={inSpec} semanticEnabled={false} />);
    expect(container.querySelector('.dword-obj')).toBeNull();
    expect(container.querySelector('.dword-stage')?.getAttribute('data-primitive')).toBeNull();
    rerender(<DancingWord text="red" spec={red} semanticEnabled={false} />);
    expect((container.querySelector('.dword') as HTMLElement).style.color).toBe('');
  });

  describe('with element.animate stubbed', () => {
    let animate: ReturnType<typeof vi.fn>;
    beforeEach(() => {
      animate = vi.fn(() => ({ finished: Promise.resolve(), cancel: () => undefined }));
      Object.defineProperty(Element.prototype, 'animate', { value: animate, configurable: true, writable: true });
    });
    afterEach(() => {
      delete (Element.prototype as unknown as { animate?: unknown }).animate;
    });

    it("autoplay 'semantic' plays the meaning alone; a 'full' replay plays the form now and the meaning after the gap; 'form' never leaks the meaning", () => {
      vi.useFakeTimers();
      try {
        const semantic = semanticPlan(inSpec, 'currentColor').length;
        const form = dancePlan(inSpec, 'currentColor').length;
        const { rerender, unmount } = render(<DancingWord text="in" spec={inSpec} autoplay="semantic" replay="full" />);
        expect(animate).toHaveBeenCalledTimes(semantic);
        rerender(<DancingWord text="in" spec={inSpec} autoplay="semantic" replay="full" playToken={1} />);
        expect(animate).toHaveBeenCalledTimes(semantic + form); // the form half plays at once …
        vi.advanceTimersByTime(danceDuration(inSpec) + SEMANTIC_GAP_MS);
        expect(animate).toHaveBeenCalledTimes(semantic + form + semantic); // … the meaning follows as a second play (no backwards fill over the form dance)
        rerender(<DancingWord text="in" spec={inSpec} autoplay="semantic" replay="full" playToken={2} />);
        expect(animate).toHaveBeenCalledTimes(semantic + form + semantic + form);
        unmount(); // the pending second half never plays on a gone word
        vi.advanceTimersByTime(10_000);
        expect(animate).toHaveBeenCalledTimes(semantic + form + semantic + form);
        animate.mockClear();
        const front = render(<DancingWord text="in" spec={inSpec} autoplay="form" replay="form" />);
        expect(animate).toHaveBeenCalledTimes(form);
        front.rerender(<DancingWord text="in" spec={inSpec} autoplay="form" replay="form" playToken={1} />);
        vi.advanceTimersByTime(10_000);
        expect(animate).toHaveBeenCalledTimes(2 * form);
      } finally {
        vi.useRealTimers();
      }
    });

    it('a stage step animates the stage object itself (onto: the shelf gives under the landing)', () => {
      const plan = semanticPlan(onSpec, 'currentColor');
      const { container } = render(<DancingWord text="on" spec={onSpec} autoplay="semantic" />);
      expect(animate).toHaveBeenCalledTimes(plan.length);
      const targets = animate.mock.contexts as unknown[];
      expect(targets).toContain(container.querySelector('.dword-obj--shelf')); // the shelf …
      expect(targets).toContain(container.querySelector('.dword')); // … and the word
    });

    it('semanticEnabled=false plays the form dance only, even for a full replay', () => {
      const form = dancePlan(inSpec, 'currentColor').length;
      const { rerender } = render(<DancingWord text="in" spec={inSpec} autoplay="semantic" replay="full" semanticEnabled={false} />);
      expect(animate).not.toHaveBeenCalled(); // nothing semantic to play
      rerender(<DancingWord text="in" spec={inSpec} autoplay="semantic" replay="full" semanticEnabled={false} playToken={1} />);
      expect(animate).toHaveBeenCalledTimes(form);
    });
  });
});
