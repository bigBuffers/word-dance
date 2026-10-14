import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import { readPref, useLocalPref, writePref } from './useLocalPref';

describe('useLocalPref', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('reads, writes (functional too) and resets', () => {
    const { result } = renderHook(() => useLocalPref('wd.test', 'a'));
    expect(result.current[0]).toBe('a');
    act(() => result.current[1]('b'));
    expect(result.current[0]).toBe('b');
    expect(window.localStorage.getItem('wd.test')).toBe('"b"');
    act(() => result.current[1]((prev) => `${prev}c`));
    expect(result.current[0]).toBe('bc');
    act(() => result.current[2]());
    expect(result.current[0]).toBe('a');
    expect(window.localStorage.getItem('wd.test')).toBeNull();
  });

  it('falls back when storage holds garbage and persists objects as JSON', () => {
    window.localStorage.setItem('wd.bad', '{not json');
    const { result } = renderHook(() => useLocalPref('wd.bad', 42));
    expect(result.current[0]).toBe(42);

    writePref('wd.obj', { tab: 'cet6', zh: true });
    expect(readPref<{ tab: string; zh: boolean }>('wd.obj', { tab: 'all', zh: false })).toEqual({ tab: 'cet6', zh: true });
    expect(readPref('wd.missing', 'dflt')).toBe('dflt');
  });

  it('picks up changes from other tabs through the storage event', () => {
    const { result } = renderHook(() => useLocalPref('wd.sync', 1));
    window.localStorage.setItem('wd.sync', '7');
    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'wd.sync', newValue: '7' }));
    });
    expect(result.current[0]).toBe(7);
  });
});
