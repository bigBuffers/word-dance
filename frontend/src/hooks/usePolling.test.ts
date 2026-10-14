import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { usePolling } from './usePolling';

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility('visible');
  });
  afterEach(() => {
    vi.useRealTimers();
    setVisibility('visible');
  });

  it('polls every interval while enabled and stops at max', async () => {
    const fn = vi.fn(async () => undefined);
    const { result } = renderHook(() => usePolling(fn, 1000, { max: 3 }));
    expect(fn).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fn).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fn).toHaveBeenCalledTimes(3);
    expect(result.current.exhausted).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fn).toHaveBeenCalledTimes(3);
    expect(result.current.polls).toBe(3);
  });

  it('stops when the poll function resolves false and restarts on demand', async () => {
    let resolved = false;
    const fn = vi.fn(async () => !resolved);
    const { result } = renderHook(() => usePolling(fn, 500));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fn).toHaveBeenCalledTimes(2);
    resolved = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(fn).toHaveBeenCalledTimes(3);
    expect(result.current.exhausted).toBe(true);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fn).toHaveBeenCalledTimes(3);

    resolved = false;
    act(() => result.current.restart());
    expect(result.current.exhausted).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(fn).toHaveBeenCalledTimes(4);
    expect(result.current.polls).toBe(1);
  });

  it('does nothing while disabled and pauses in a hidden tab', async () => {
    const fn = vi.fn(async () => undefined);
    const { rerender } = renderHook(({ enabled }) => usePolling(fn, 1000, { enabled }), { initialProps: { enabled: false } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fn).not.toHaveBeenCalled();

    rerender({ enabled: true });
    setVisibility('hidden');
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fn).not.toHaveBeenCalled(); // tick fired while hidden → waits
    setVisibility('visible');
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it('runs immediately when asked and aborts the in-flight request on unmount', async () => {
    let seenSignal: AbortSignal | null = null;
    const fn = vi.fn((signal: AbortSignal) => {
      seenSignal = signal;
      return new Promise<void>(() => undefined); // never settles
    });
    const { unmount } = renderHook(() => usePolling(fn, 1000, { immediate: true }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fn).toHaveBeenCalledTimes(1);
    unmount();
    expect(seenSignal).not.toBeNull();
    expect((seenSignal as unknown as AbortSignal).aborted).toBe(true);
  });
});
