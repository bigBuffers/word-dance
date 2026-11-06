import { act, render, renderHook } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BOTTOM_BAR_CLASS, BOTTOM_BAR_VAR, bottomBarOffset, resetBottomBarOwner, useBottomBarOffset } from './useBottomBarOffset';

const root = () => document.documentElement;
const rectOf = (height: number) => ({ top: window.innerHeight - height, height, bottom: window.innerHeight, left: 0, right: 0, width: 0, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
const barOf = (height: number) => {
  const el = document.createElement('div');
  el.getBoundingClientRect = () => rectOf(height);
  return el;
};

afterEach(() => {
  resetBottomBarOwner();
  root().style.removeProperty(BOTTOM_BAR_VAR);
  root().classList.remove(BOTTOM_BAR_CLASS);
});

describe('bottomBarOffset', () => {
  it("is the distance from the viewport bottom to the bar's top edge for a bar near the bottom", () => {
    expect(bottomBarOffset({ top: 700, height: 100 }, 800)).toBe(100); // flush with the bottom (sticky grade bar)
    expect(bottomBarOffset({ top: 680, height: 100 }, 800)).toBe(120); // 20 px above the bottom: the toast still clears it
  });

  it('falls back to the bar height when the bar is in the upper half, and to 0 for an empty or offscreen bar', () => {
    expect(bottomBarOffset({ top: 100, height: 80 }, 800)).toBe(80);
    expect(bottomBarOffset({ top: 900, height: 80 }, 800)).toBe(0);
    expect(bottomBarOffset({ top: 700, height: 0 }, 800)).toBe(0);
  });
});

describe('useBottomBarOffset', () => {
  it('publishes the offset on <html> while a bar is attached and clears it when the bar goes away', () => {
    const { result, unmount } = renderHook(() => useBottomBarOffset<HTMLDivElement>());
    const bar = barOf(96);

    act(() => result.current(bar));
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(true);
    expect(root().style.getPropertyValue(BOTTOM_BAR_VAR)).toBe('96px');

    act(() => result.current(null));
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(false);
    expect(root().style.getPropertyValue(BOTTOM_BAR_VAR)).toBe('');

    const flat = document.createElement('div'); // not laid out (jsdom default 0 × 0): the default toast position stays
    act(() => result.current(flat));
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(false);

    act(() => result.current(bar));
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(true);
    unmount();
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(false);
    expect(root().style.getPropertyValue(BOTTOM_BAR_VAR)).toBe('');
  });

  it('re-measures on window resize and scroll', () => {
    const { result } = renderHook(() => useBottomBarOffset<HTMLDivElement>());
    let height = 96;
    const bar = document.createElement('div');
    bar.getBoundingClientRect = () => rectOf(height);
    act(() => result.current(bar));
    expect(root().style.getPropertyValue(BOTTOM_BAR_VAR)).toBe('96px');
    height = 140;
    act(() => {
      window.dispatchEvent(new Event('resize'));
    });
    expect(root().style.getPropertyValue(BOTTOM_BAR_VAR)).toBe('140px');
    height = 120;
    act(() => {
      window.dispatchEvent(new Event('scroll'));
    });
    expect(root().style.getPropertyValue(BOTTOM_BAR_VAR)).toBe('120px');
  });

  it('a keyed card swap keeps the new bar published although the old instance cleans up last', () => {
    // StudyPage / ScreenRunPage key the card per item: React detaches the old ref, attaches the new one, then
    // runs the OLD instance's effect cleanup — which must not wipe what the new bar just published.
    const rect = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(() => rectOf(96));
    function Bar() {
      const ref = useBottomBarOffset<HTMLDivElement>();
      return createElement('div', { ref, 'data-testid': 'bar' });
    }
    const { rerender, unmount } = render(createElement(Bar, { key: 'card-1' }));
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(true);
    rerender(createElement(Bar, { key: 'card-2' }));
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(true);
    expect(root().style.getPropertyValue(BOTTOM_BAR_VAR)).toBe('96px');
    unmount();
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(false);
    rect.mockRestore();
  });

  it('a bar-less instance (read-only card, front face) never clears another card\'s bar on resize', () => {
    const owner = renderHook(() => useBottomBarOffset<HTMLDivElement>());
    const idle = renderHook(() => useBottomBarOffset<HTMLDivElement>());
    act(() => owner.result.current(barOf(96)));
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(true);
    act(() => {
      window.dispatchEvent(new Event('resize'));
    });
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(true);
    idle.unmount();
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(true);
    owner.unmount();
    expect(root().classList.contains(BOTTOM_BAR_CLASS)).toBe(false);
  });
});
